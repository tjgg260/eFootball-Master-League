#!/usr/bin/env python3
"""cave_alloc.py — CHAINED code-cave allocator for eFootball.exe patches.

A code cave used to need ONE contiguous int3 run big enough for the whole payload.  The only two
runs >= 64 B in the image are both occupied (cave-ability-error, linked-spin), and the *safe* pool
(tier A: padding bounded exactly by two RUNTIME_FUNCTIONs) tops out at 21 bytes because MSVC aligns
function entries to 16.  So a payload is SPLIT across many small runs, each chunk ending in a
5-byte `jmp rel32` to the next; the final chunk ends in the payload's own exit jmp back to the hook
return address.

    payload source (one instruction per line, labels, @label / $extern / RIPREL_$cell)
        -> size pass   (labels pinned to a FAR dummy => rel32, rip-rel pinned to disp32
                        => every reserved size is ADDRESS-INDEPENDENT, so no fixpoint is needed)
        -> pack        (greedy over a deterministically ordered free pool, one chunk per cave)
        -> emit        (assemble each instruction AT ITS FINAL VA, pad any shorter encoding with nop)
        -> verify      (independent capstone read-back: see verify_layout)
        -> spec        (one ordinary patch entry per chunk, expect = the original "cc"*n,
                        so `exe_patch.py remove` restores the padding byte for byte)

Nothing here writes to the game.  `emit_spec()` writes a JSON spec file into the repo; applying it
is still `exe_patch.py apply`, with its own expect-gate.

CLI (read-only):
    python tools/cave_alloc.py pool  [--min 12] [--near 0x143da6529] [--limit 20]
    python tools/cave_alloc.py audit
    python tools/cave_alloc.py seed-ledger
    python tools/cave_alloc.py demo  [--near 0x143da6529]      # lay out a sample payload, no write
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parent.parent
EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
PRISTINE = Path.home() / "Backups" / "eFootball" / "eFootball.exe.PRISTINE"
POOL_JSON = REPO / "build" / "caves.json"
LEDGER = REPO / "tools" / "data" / "cave_reservations.json"
PATCH_DIR = REPO / "tools" / "data" / "patches"

BASE = 0x140000000
CHAIN_LEN = 5                      # jmp rel32
PAD_BYTE = 0x90                    # nop
MAX_STOLEN = 32                    # refuse to steal more of a live function than this
# Trailing filler a chunk may legitimately carry AFTER its terminator: a chain or exit jmp that
# encodes as rel8 is nop-padded out to the reservation, so the transfer is not the last decode.
_PAD_MNEMONICS = frozenset(("nop", "int3"))
_BRANCH_WINDOW = 4096              # bytes either side of a hook scanned for inbound branches
FAR_DUMMY = BASE + 0x02000000      # 32 MB from anywhere in .xcode => every label branch sizes as rel32
MAGIC_DISP = 0x11223344            # placeholder displacement for a rip-relative operand
ALLOCATOR_ID = "cave_alloc v1"


class Refuse(Exception):
    """The allocator refuses to emit.  Never caught internally — a refusal is a result."""


# --------------------------------------------------------------------------------------- image
class Image:
    """Read-only view of a PE image on disk."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        d = self.data
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.sections = []
        for i in range(nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            chars = struct.unpack_from("<I", s, 36)[0]
            self.sections.append(dict(name=s[:8].rstrip(b"\0").decode(), rva=va, vsize=vsize,
                                      raw=raw, rsize=rsize, chars=chars))
        self.pdata_rva, self.pdata_size = struct.unpack_from("<II", d, pe + 24 + 112 + 8 * 3)
        self._sha1 = None

    @property
    def sha1(self) -> str:
        if self._sha1 is None:
            self._sha1 = hashlib.sha1(self.data).hexdigest()
        return self._sha1

    def rva_to_file(self, rva: int) -> int | None:
        for s in self.sections:
            if s["rva"] <= rva < s["rva"] + s["vsize"]:
                o = rva - s["rva"]
                return None if o >= s["rsize"] else s["raw"] + o
        return None

    def va_to_file(self, va: int) -> int | None:
        return self.rva_to_file(va - self.base)

    def read_va(self, va: int, n: int) -> bytes:
        f = self.va_to_file(va)
        if f is None:
            raise Refuse(f"va {va:#x} is not backed by file bytes")
        return self.data[f:f + n]

    def section_of(self, va: int):
        for s in self.sections:
            if s["rva"] <= va - self.base < s["rva"] + s["vsize"]:
                return s
        return None

    def xcode(self):
        for s in self.sections:
            if s["name"] == ".xcode":
                return s
        raise Refuse("no .xcode section")


def _np():
    import numpy
    return numpy


def int3_runs(img: Image, sec: dict | None = None):
    """(starts_va, lengths) of every MAXIMAL 0xCC run in `sec` (default .xcode)."""
    np = _np()
    sec = sec or img.xcode()
    n = min(sec["vsize"], sec["rsize"])
    blob = np.frombuffer(img.data, dtype=np.uint8, count=n, offset=sec["raw"])
    dif = np.diff(np.concatenate(([0], (blob == 0xCC).astype(np.int8), [0])))
    s = np.where(dif == 1)[0]
    e = np.where(dif == -1)[0]
    return img.base + sec["rva"] + s, e - s


def pdata_ranges(img: Image):
    """Sorted (begin_va, end_va) of every RUNTIME_FUNCTION in the exception directory."""
    np = _np()
    off = img.rva_to_file(img.pdata_rva)
    if off is None:
        raise Refuse("exception directory (.pdata) is not on disk — refusing to allocate")
    n = img.pdata_size // 12
    rf = np.frombuffer(img.data, dtype=np.uint32, count=n * 3, offset=off).reshape(n, 3).astype(np.int64)
    rf = rf[rf[:, 0] != 0]
    o = np.argsort(rf[:, 0], kind="stable")
    return img.base + rf[o, 0], img.base + rf[o, 1]


def refs_into(img: Image, ranges: Sequence[tuple[int, int]]):
    """Every byte position in the image that could transfer control into / point at one of `ranges`.

    rel32 (E8/E9, 0F 8x) and rel8 (EB, 70-7F, E0-E3) from every EXECUTABLE section at EVERY byte
    offset (no instruction-boundary assumption, so junk bytes give false positives — we reject on
    the possibility), plus absolute 8-byte pointers from every section.  Returns [(kind, site_va,
    target_va)].  One pass; `ranges` need not be sorted."""
    np = _np()
    if not ranges:
        return []
    lo = np.array([r[0] for r in ranges], dtype=np.int64)
    hi = np.array([r[1] for r in ranges], dtype=np.int64)
    o = np.argsort(lo, kind="stable")
    lo, hi = lo[o], hi[o]

    def inside(vals):
        i = np.searchsorted(lo, vals, side="right") - 1
        ok = i >= 0
        out = np.zeros(len(vals), bool)
        out[ok] = vals[ok] < hi[i[ok]]
        return out

    hits = []
    CH = 8 << 20
    for s in img.sections:
        n = min(s["vsize"], s["rsize"])
        execable = bool(s["chars"] & 0x20000000)
        for c in range(0, n, CH):
            end = min(n, c + CH + 8)
            blk = np.frombuffer(img.data, dtype=np.uint8, count=end - c, offset=s["raw"] + c)
            m = len(blk) - 8
            if m <= 0:
                continue
            base = img.base + s["rva"] + c
            w = lambda k: blk[k:k + m].astype(np.int64)                      # noqa: E731
            full = ((w(4) | (w(5) << 8) | (w(6) << 16) | (w(7) << 24)) << 32) | \
                   (w(0) | (w(1) << 8) | (w(2) << 16) | (w(3) << 24))
            idx = np.flatnonzero(inside(full))
            hits += [("ptr64", base + int(j), int(full[j])) for j in idx]
            if not execable:
                continue
            pos = np.arange(m, dtype=np.int64)
            op = blk[:m]
            rel = w(1) | (w(2) << 8) | (w(3) << 16) | (w(4) << 24)
            rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
            t32 = base + pos + 5 + rel
            is_e = (op == 0xE8) | (op == 0xE9)
            is_j = np.zeros(m, dtype=bool)
            is_j[1:] = (op[:-1] == 0x0F) & ((op[1:] & 0xF0) == 0x80)
            if c:
                prev = img.data[s["raw"] + c - 1]
                is_j[0] = prev == 0x0F and (int(op[0]) & 0xF0) == 0x80
            r8 = w(1)
            r8 = np.where(r8 >= 128, r8 - 256, r8)
            t8 = base + pos + 2 + r8
            is_s = (op == 0xEB) | ((op & 0xF0) == 0x70) | ((op & 0xFC) == 0xE0)
            for kind, mask, tg in (("rel32", is_e | is_j, t32), ("rel8", is_s, t8)):
                sel = np.flatnonzero(mask)
                if not len(sel):
                    continue
                sel = sel[inside(tg[sel])]
                hits += [(kind, base + int(j), int(tg[j])) for j in sel]
    return sorted(set(hits))


# ---------------------------------------------------------------------------------- the pool
@dataclass(frozen=True, order=True)
class Cave:
    va: int
    length: int
    safety: str = "A"
    why: tuple = ()

    @property
    def end(self) -> int:
        return self.va + self.length

    @property
    def payload(self) -> int:
        """Bytes usable for payload once the chunk's outgoing 5-byte jmp is deducted."""
        return self.length - CHAIN_LEN


def _overlap_test(np, ranges):
    """Exact 'does [va,end) hit any of these ranges?' test.

    `ranges` must be sorted by start.  A window of the few nearest entries is NOT enough — one long
    range starting well before the query (a 3 KB RUNTIME_FUNCTION, say) can still cover it — so the
    test uses a running maximum of the ends: any range k with start[k] < end and runmax_end[k] > va
    is an overlap, and runmax is monotone, so checking the last such k is exact."""
    if not len(ranges):
        return lambda va, end: False
    lo = np.array([r[0] for r in ranges], dtype=np.int64)
    hi = np.maximum.accumulate(np.array([r[1] for r in ranges], dtype=np.int64))

    def test(va, end):
        i = int(np.searchsorted(lo, end, side="left")) - 1
        return i >= 0 and int(hi[i]) > va
    return test


def _spec_files() -> list[Path]:
    return sorted(PATCH_DIR.glob("*.json")) if PATCH_DIR.exists() else []


def claimed_ranges(*, patches: bool = True, ledger: bool = True) -> list[tuple[int, int, str]]:
    """Every byte range already claimed by a committed patch spec or by the reservation ledger.

    Claims are byte RANGES, never VA equality: linked-spin (0x14105ed1e+85) and the retired
    slice-cave (0x14105ed20+49) collide *inside* one run at different start VAs."""
    out = []
    if patches:
        for p in _spec_files():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception as ex:                                   # a malformed spec must not
                raise Refuse(f"cannot parse {p.name}: {ex}")          # silently disable the gate
            entries = d["patches"] if isinstance(d, dict) and "patches" in d else d
            for e in (entries if isinstance(entries, list) else [entries]):
                if "va" in e:
                    va = int(e["va"], 16)
                elif "module_offset" in e:
                    va = BASE + int(e["module_offset"], 16)
                else:
                    continue
                n = len(bytes.fromhex(e.get("patch", e.get("expect", "")).replace(" ", "")))
                out.append((va, va + n, p.name))
    if ledger and LEDGER.exists():
        led = json.loads(LEDGER.read_text(encoding="utf-8"))
        for r in led.get("reservations", []):
            va = int(r["cave_va"], 16)
            out.append((va, va + int(r.get("used", r.get("cave_len", 0))), r["spec"] + " (ledger)"))
    return sorted(out)


def load_pool_file(path: Path, target: Image) -> list[Cave]:
    """The classified pool produced by tools/cave_scan.py.  Fail closed on a sha1 mismatch."""
    if not path.exists():
        raise Refuse(f"no cave pool at {path} — run tools/cave_scan.py scan first (refusing to "
                     f"allocate without the classifier's gates)")
    d = json.loads(path.read_text(encoding="utf-8"))
    meta = d.get("meta", {})
    if meta.get("image_sha1") != target.sha1:
        raise Refuse(f"cave pool {path.name} was built for image sha1 {meta.get('image_sha1')} but the "
                     f"target is {target.sha1} — re-run tools/cave_scan.py scan")
    return [Cave(int(c["va"], 16), int(c["length"]), c.get("safety", "A"), tuple(c.get("why", ())))
            for c in d["caves"]]


def cave_pool(*, target: Image, pristine: Image | None = None, min_len: int = 12,
              anchor: int | None = None, pool_file: Path = POOL_JSON,
              exclude: Iterable[tuple[int, int]] = (), safety: str = "A",
              hook_guard: int = 32) -> tuple[list[Cave], dict]:
    """Deterministically ordered free list.  Every gate is fail-closed.

    Order: nearest to `anchor` first, ties by VA — no set iteration, no dict order, no clock,
    no randomness, so the same inputs always produce the same allocation."""
    if min_len < CHAIN_LEN + 1:
        raise Refuse(f"min_len {min_len} < {CHAIN_LEN + 1}: a cave must hold at least one payload "
                     f"byte plus its {CHAIN_LEN}-byte chain jmp")
    caves = load_pool_file(pool_file, target)
    claims = list(exclude) + [(a, b) for a, b, _ in claimed_ranges()]
    if anchor is not None:
        claims.append((anchor - hook_guard, anchor + hook_guard))
    claims.sort()
    np = _np()
    claimed = _overlap_test(np, claims)

    rej = dict(below_min=0, safety=0, not_int3_target=0, claimed=0)
    out = []
    for c in caves:
        if c.length < min_len:
            rej["below_min"] += 1
            continue
        if safety and c.safety not in safety:
            rej["safety"] += 1
            continue
        if target.read_va(c.va, c.length) != b"\xcc" * c.length:
            rej["not_int3_target"] += 1
            continue
        if claimed(c.va, c.end):
            rej["claimed"] += 1
            continue
        out.append(c)
    if anchor is None:
        out.sort(key=lambda c: c.va)
    else:
        out.sort(key=lambda c: (abs(c.va - anchor), c.va))
    return out, rej


def classify_site(img: Image, site: int, beg, end) -> str:
    """Is `site` a REAL instruction start, or a byte inside one?

    A byte-offset scan for branch opcodes is deliberately paranoid and mostly finds coincidences:
    0x74/0xEB/0xE8 turn up constantly as modrm/sib/displacement bytes.  The arbiter is the image's
    own exception data — linear-sweep the enclosing RUNTIME_FUNCTION from its BeginAddress and see
    whether the sweep lands on `site`.  Returns "real", "junk" or "unverified" (no .pdata entry
    covers the site, so nothing can settle it)."""
    np = _np()
    i = int(np.searchsorted(beg, site, side="right")) - 1
    if i < 0 or not (beg[i] <= site < end[i]):
        return "unverified"
    lo, hi = int(beg[i]), min(int(end[i]), site + 16)
    code = img.read_va(lo, hi - lo)
    for ins in _md().disasm(code, lo):
        if ins.address == site:
            return "real"
        if ins.address > site:
            return "junk"
    return "junk"


def audit_caves(caves: Sequence[Cave], *, target: Image, pristine: Image | None = None,
                stats: dict | None = None) -> list[str]:
    """INDEPENDENT re-derivation of the safety of the caves we actually allocated — from the image
    bytes, not from the pool file.  Returns a list of problems (empty == clean)."""
    np = _np()
    problems = []
    st = stats if stats is not None else {}
    st.update(caves=len(caves), ptr64=0, branch_real=0, branch_junk=0, branch_unverified=0)
    ranges = [(c.va, c.end) for c in caves]
    # 1. all-int3 and MAXIMAL in the target (and, if given, in the pristine reference)
    for img, tag in ((target, "target"), (pristine, "pristine")):
        if img is None:
            continue
        for c in caves:
            body = img.read_va(c.va, c.length)
            edge = img.read_va(c.va - 1, 1) + img.read_va(c.end, 1)
            if body != b"\xcc" * c.length:
                problems.append(f"{c.va:#x}+{c.length}: not all int3 in {tag} ({body[:8].hex()}…)")
            if 0xCC in edge:
                problems.append(f"{c.va:#x}+{c.length}: not a MAXIMAL run in {tag} (neighbours {edge.hex()})")
    # 2. no overlap with any RUNTIME_FUNCTION body
    beg, end = pdata_ranges(target)
    hits = _overlap_test(np, list(zip(beg.tolist(), end.tolist())))
    for c in caves:
        if hits(c.va, c.end):
            i = int(np.searchsorted(beg, c.end, side="left")) - 1
            problems.append(f"{c.va:#x}+{c.length}: overlaps RUNTIME_FUNCTION near "
                            f"[{int(beg[i]):#x},{int(end[i]):#x}) — it is INSIDE a live function")
    # 3. nothing in the image branches into or points at the run.  A branch hit is only a real
    #    reference if its site is a real instruction (see classify_site); an 8-byte pointer is a
    #    pointer wherever it lies, so those are rejected outright.
    for kind, site, tgt in refs_into(target, ranges):
        if kind == "ptr64":
            st["ptr64"] += 1
            problems.append(f"{tgt:#x} inside an allocated cave is pointed at by an absolute "
                            f"8-byte pointer at {site:#x}")
            continue
        cls = classify_site(target, site, beg, end)
        st["branch_" + cls] += 1
        if cls == "real":
            problems.append(f"{tgt:#x} inside an allocated cave is the target of a {kind} branch at "
                            f"{site:#x} (a REAL instruction per a .pdata-anchored sweep)")
        elif cls == "unverified":
            problems.append(f"{tgt:#x} inside an allocated cave looks like a {kind} target from "
                            f"{site:#x}, which no RUNTIME_FUNCTION covers — cannot be settled")
    return problems


# ------------------------------------------------------------------------------ assembler
_KS = None
_MD = None


def _ks():
    global _KS
    if _KS is None:
        import keystone
        _KS = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
    return _KS


def _branches_into(img, lo: int, hi: int, window: int = _BRANCH_WINDOW) -> list[str]:
    """Direct branches in a window around [lo,hi) whose target lands strictly inside it.

    A linear sweep is not a disassembly of the enclosing function, so this is a DETECTOR, not a
    proof of absence: it can miss a branch from outside the window, and a byte pair that merely
    looks like a rel8 jcc can produce a false positive.  It is here to catch the common, fatal
    case -- a loop or a short forward jump inside the same function hopping over the bytes we are
    about to replace with a 5-byte jmp."""
    import capstone
    md = _md()
    start = lo - window
    try:
        blob = img.read_va(start, (hi + window) - start)
    except Exception:
        return []
    hits: list[str] = []
    for ins in md.disasm(blob, start):
        if ins.mnemonic == "nop" or not ins.operands:
            continue
        m = ins.mnemonic
        is_branch = m == "call" or (m[0] == "j") or m in ("loop", "loope", "loopne")
        if not is_branch:
            continue
        o = ins.operands[0]
        if o.type != capstone.x86.X86_OP_IMM:
            continue
        if lo <= o.imm < hi and not (lo <= ins.address < hi):
            hits.append(f"{ins.address:#x} {m} {ins.op_str}")
    return hits


def _md():
    global _MD
    if _MD is None:
        import capstone
        _MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        _MD.detail = True
    return _MD


_RIPREL = re.compile(r"RIPREL_(?:\$([A-Za-z_]\w*)|(0x[0-9a-fA-F]+))")
_LABEL = re.compile(r"@([A-Za-z_]\w*)")
_EXTERN = re.compile(r"\$([A-Za-z_]\w*)")


def _prep(line: str, labels: Mapping[str, int], externals: Mapping[str, int],
          cells: Mapping[str, int]) -> tuple[str, list[int]]:
    """@label -> VA, $extern -> VA, RIPREL_$cell / RIPREL_0x.. -> MAGIC_DISP (target collected)."""
    txt = line.split(";")[0].strip()
    if hex(MAGIC_DISP) in txt.lower().replace("0X", "0x"):
        raise Refuse(f"source line contains the placeholder displacement {MAGIC_DISP:#x}: {line}")
    riprel: list[int] = []

    def sub_rip(m):
        name, lit = m.group(1), m.group(2)
        if name is not None:
            if name not in cells:
                raise Refuse(f"undeclared rip-relative cell ${name} in: {line}")
            riprel.append(cells[name])
        else:
            riprel.append(int(lit, 16))
        return hex(MAGIC_DISP)

    txt = _RIPREL.sub(sub_rip, txt)
    if len(riprel) > 1:
        raise Refuse(f"more than one rip-relative operand on one line (x86 allows one): {line}")
    if riprel and "rip" not in txt:
        raise Refuse(f"RIPREL_ without 'rip +' — that assembles to an ABSOLUTE disp32 form: {line}")

    def sub_label(m):
        if m.group(1) not in labels:
            raise Refuse(f"undefined label @{m.group(1)} in: {line}")
        return hex(labels[m.group(1)])

    txt = _LABEL.sub(sub_label, txt)

    def sub_ext(m):
        if m.group(1) not in externals:
            raise Refuse(f"undeclared external ${m.group(1)} in: {line}")
        return hex(externals[m.group(1)])

    txt = _EXTERN.sub(sub_ext, txt)
    return txt, riprel


def asm_one(line: str, addr: int, labels: Mapping[str, int] = {},
            externals: Mapping[str, int] = {}, cells: Mapping[str, int] = {}) -> bytes:
    """Assemble ONE instruction at its final VA and fix up its rip-relative displacement."""
    txt, riprel = _prep(line, labels, externals, cells)
    try:
        enc, cnt = _ks().asm(txt, addr)
    except Exception as ex:
        raise Refuse(f"keystone rejected {txt!r} at {addr:#x}: {ex}")
    if enc is None:
        raise Refuse(f"keystone produced nothing for {txt!r} at {addr:#x}")
    if cnt != 1:
        raise Refuse(f"{txt!r} assembled to {cnt} instructions — one instruction per source line")
    b = bytearray(enc)
    bound = 0
    for ins in _md().disasm(bytes(b), addr):
        if ins.disp_offset and ins.disp == MAGIC_DISP:
            o = ins.address - addr + ins.disp_offset
            b[o:o + 4] = struct.pack("<i", riprel[bound] - (ins.address + ins.size))
            bound += 1
    if bound != len(riprel):
        raise Refuse(f"rip-relative fixup bound {bound} of {len(riprel)} placeholder(s) in: {line}")
    return bytes(b)


def parse_payload(asm_text: str) -> tuple[list[str], dict[str, int]]:
    """Source text -> (one instruction per line, label -> index of the NEXT instruction)."""
    lines: list[str] = []
    labels_at: dict[str, int] = {}
    for raw in asm_text.strip().splitlines():
        t = raw.split(";")[0].strip()
        if not t:
            continue
        if t.endswith(":"):
            name = t[:-1].strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", name):
                raise Refuse(f"bad label {t!r}")
            if name in labels_at:
                raise Refuse(f"duplicate label {name!r}")
            labels_at[name] = len(lines)
            continue
        lines.append(t)
    if not lines:
        raise Refuse("empty payload")
    for name, j in labels_at.items():
        if j >= len(lines):
            raise Refuse(f"label {name!r} is at the end of the payload with no instruction after it "
                         f"— branch to an explicit exit instead")
    return lines, labels_at


# --------------------------------------------------------------------------------- layout
@dataclass(frozen=True)
class Chunk:
    index: int
    cave: Cave
    va: int
    code: bytes
    chain_to: int | None
    asm: tuple[str, ...]

    @property
    def end(self) -> int:
        return self.va + len(self.code)


@dataclass(frozen=True)
class Layout:
    entry: int
    chunks: tuple[Chunk, ...]
    labels: dict
    exits: tuple
    externals: dict
    cells: dict
    source: str
    policy: dict

    # --- consumers -------------------------------------------------------------------
    def overlays(self) -> list[tuple[int, bytes]]:
        """(va, bytes) pairs — feed these to Unicorn so the emulator proves the EXACT bytes that
        would be written, at the EXACT addresses they would be written to."""
        return [(c.va, c.code) for c in self.chunks]

    def total_used(self) -> int:
        return sum(len(c.code) for c in self.chunks)

    def payload_bytes(self) -> int:
        return sum(len(c.code) - (CHAIN_LEN if c.chain_to is not None else 0) for c in self.chunks)

    def patches(self, target: Image, prefix: str) -> list[dict]:
        """One ordinary exe_patch entry per chunk.  `expect` is the original int3 bytes, so
        `exe_patch.py remove` restores the padding exactly."""
        out = []
        n = len(self.chunks)
        for c in self.chunks:
            cur = target.read_va(c.va, len(c.code))
            if cur != b"\xcc" * len(c.code):
                raise Refuse(f"chunk {c.index} target bytes at {c.va:#x} are not int3 ({cur.hex()})")
            out.append(dict(
                name=f"{prefix} cave chunk {c.index + 1}/{n} "
                     f"({len(c.code)} B in the {c.cave.length} B int3 run at {c.cave.va:#x})",
                va=f"{c.va:#x}", expect=cur.hex(), patch=c.code.hex(), kind="code",
                chunk=c.index, cave={"va": f"{c.cave.va:#x}", "len": c.cave.length}))
        return out

    def provenance(self) -> dict:
        return dict(
            allocator=ALLOCATOR_ID,
            entry=f"{self.entry:#x}",
            exits=[f"{e:#x}" for e in self.exits],
            externals={k: f"{v:#x}" for k, v in sorted(self.externals.items())},
            cells={k: f"{v:#x}" for k, v in sorted(self.cells.items())},
            labels={k: f"{v:#x}" for k, v in sorted(self.labels.items())},
            policy=self.policy,
            chain_len=CHAIN_LEN,
            chunks=[dict(index=c.index, cave_va=f"{c.cave.va:#x}", cave_len=c.cave.length,
                         cave_safety=c.cave.safety, used=len(c.code),
                         chain_to=None if c.chain_to is None else f"{c.chain_to:#x}",
                         asm=list(c.asm)) for c in self.chunks],
            total_used=self.total_used(),
            payload_bytes=self.payload_bytes(),
            source_sha1=hashlib.sha1(self.source.encode()).hexdigest(),
        )


def layout_payload(asm_text: str, *, pool: Sequence[Cave], exits: Iterable[int],
                   externals: Mapping[str, int] = {}, cells: Mapping[str, int] = {},
                   policy: Mapping | None = None) -> Layout:
    """Split a payload across `pool` caves, chaining the chunks with 5-byte jmp rel32.

    SIZING IS ADDRESS-INDEPENDENT.  Every label is sized against a FAR dummy (so a label branch is
    always its rel32 form, the MAXIMUM encoding) and every rip-relative operand against a disp32.
    The emit pass, at the real VA, can therefore only produce a SHORTER encoding — padded with nop
    — never a longer one, which is asserted.  So one pass suffices: no fixpoint, no oscillation,
    no rel8 -> rel32 promotion problem."""
    exits = tuple(exits)
    lines, labels_at = parse_payload(asm_text)

    # 1. size pass — far dummy for every label
    dummy = {name: FAR_DUMMY for name in labels_at}
    reserved = [len(asm_one(l, BASE, dummy, externals, cells)) for l in lines]
    biggest = max(reserved)
    room_max = max((c.payload for c in pool), default=0)
    if biggest > room_max:
        j = reserved.index(biggest)
        raise Refuse(f"instruction {lines[j]!r} needs {biggest} B but the largest cave in the pool "
                     f"offers {room_max} B of payload (cave length - {CHAIN_LEN} B chain jmp)")

    # 2. pack — greedy, first fit, one chunk per cave, in the pool's (deterministic) order.
    #    Every chunk reserves CHAIN_LEN for its outgoing jmp, including the last (whose own exit
    #    jmp is a payload instruction).  Wastes 5 bytes in one cave; removes a special case.
    packs: list[tuple[Cave, list[int]]] = []
    i = 0
    for cave in pool:
        if i >= len(lines):
            break
        room, take, n = cave.payload, [], 0
        while i + len(take) < len(lines) and n + reserved[i + len(take)] <= room:
            n += reserved[i + len(take)]
            take.append(i + len(take))
        if not take:
            continue                                  # this cave cannot hold the next instruction
        packs.append((cave, take))
        i += len(take)
    if i < len(lines):
        raise Refuse(f"payload does not fit the pool: {len(lines) - i} of {len(lines)} instruction(s) "
                     f"unplaced after {len(packs)} chunk(s)")

    # 3. addresses and labels, from the reserved sizes
    at: dict[int, int] = {}
    for cave, take in packs:
        p = cave.va
        for j in take:
            at[j] = p
            p += reserved[j]
    labels = {name: at[j] for name, j in labels_at.items()}

    # 4. emit each instruction AT ITS FINAL VA; pad a shorter encoding
    chunks = []
    for k, (cave, take) in enumerate(packs):
        buf = bytearray()
        for j in take:
            b = asm_one(lines[j], at[j], labels, externals, cells)
            if len(b) > reserved[j]:
                raise Refuse(f"instruction grew past its reservation ({len(b)} > {reserved[j]}): "
                             f"{lines[j]!r} at {at[j]:#x} — an address-dependent encoding was missed")
            buf += b + bytes([PAD_BYTE]) * (reserved[j] - len(b))
        chain = packs[k + 1][0].va if k + 1 < len(packs) else None
        if chain is not None:
            jv = cave.va + len(buf)
            jb = asm_one(f"jmp {chain:#x}", jv)
            if len(jb) > CHAIN_LEN:
                raise Refuse(f"chain jmp is {len(jb)} B, more than the reserved {CHAIN_LEN}")
            buf += jb + bytes([PAD_BYTE]) * (CHAIN_LEN - len(jb))
        if len(buf) > cave.length:
            raise Refuse(f"chunk {k} needs {len(buf)} B, cave {cave.va:#x} holds {cave.length}")
        chunks.append(Chunk(k, cave, cave.va, bytes(buf), chain, tuple(lines[j] for j in take)))

    pol = dict(policy or {})
    pol.setdefault("order", "nearest-first" if pol.get("anchor") else "ascending-va")
    return Layout(chunks[0].va, tuple(chunks), labels, exits, dict(externals), dict(cells),
                  asm_text, pol)


# ---------------------------------------------------------------------------------- verify
def verify_layout(lay: Layout, *, target: Image | None = None, verbose: bool = False) -> list[str]:
    """INDEPENDENT capstone read-back of the emitted bytes.  Returns problems (empty == clean).

    Gates: decode covers the chunk exactly; the chunk ends in an unconditional transfer; every
    branch/call target is a declared exit, a declared external, or an INSTRUCTION BOUNDARY inside
    one of our chunks; every rip-relative operand resolves to a declared cell; no absolute
    (base=0, index=0, disp!=0) memory operand; chunk inside its cave; no two chunks overlap; and,
    if `target` is given, the bytes we are about to overwrite are all 0xCC."""
    import capstone
    md = _md()
    problems: list[str] = []
    decoded: dict[int, list] = {}
    decoded_term: dict[int, object] = {}
    boundaries: set[int] = set()
    for c in lay.chunks:
        ins_list = list(md.disasm(c.code, c.va))
        decoded[c.index] = ins_list
        n = sum(i.size for i in ins_list)
        if n != len(c.code):
            problems.append(f"chunk {c.index}: capstone decoded {n} of {len(c.code)} B "
                            f"(truncated or mis-encoded tail)")
        boundaries.update(i.address for i in ins_list)
        # The real terminator is the last NON-PADDING instruction: a chain/exit jmp that encodes
        # as rel8 leaves nop padding after it, so ins_list[-1] is not the transfer.  Checking
        # ins_list[-1] directly mis-fires on exactly the layouts we most need to trust.
        term = None
        term_idx = -1
        for k in range(len(ins_list) - 1, -1, -1):
            if ins_list[k].mnemonic in _PAD_MNEMONICS:
                continue
            term, term_idx = ins_list[k], k
            break
        decoded_term[c.index] = term
        if term is None or term.mnemonic not in ("jmp", "ret"):
            problems.append(f"chunk {c.index}: does not end in an unconditional transfer "
                            f"(last non-padding = {term.mnemonic if term else '<empty>'}) — execution "
                            f"would fall out of the cave into whatever follows")
        elif term.mnemonic == "jmp" and (not term.operands
                                         or term.operands[0].type != capstone.x86.X86_OP_IMM):
            # `jmp rax` / `jmp [rip+x]` satisfies a naive mnemonic test but its destination is
            # invisible to the branch-target gate below, so nothing would ever check where it goes.
            problems.append(f"chunk {c.index}: terminator {term.mnemonic} {term.op_str} at "
                            f"{term.address:#x} is INDIRECT — the destination cannot be verified; "
                            f"only a direct 'jmp <imm>' or 'ret' may end a chunk")
        if term is not None and not all(i.mnemonic in _PAD_MNEMONICS for i in ins_list[term_idx + 1:]):
            problems.append(f"chunk {c.index}: non-padding instructions follow the terminator at "
                            f"{term.address:#x} — they are unreachable and would be silently lost")
        if len(c.code) > c.cave.length:
            problems.append(f"chunk {c.index}: {len(c.code)} B overflows its {c.cave.length} B cave")
        if c.va < c.cave.va or c.end > c.cave.end:
            problems.append(f"chunk {c.index}: not inside its cave")
        _t = decoded_term.get(c.index)
        if c.chain_to is not None and (_t is None or _t.mnemonic != "jmp" or not _t.operands
                                       or _t.operands[0].type != capstone.x86.X86_OP_IMM
                                       or _t.operands[0].imm != c.chain_to):
            problems.append(f"chunk {c.index}: chain jmp does not target {c.chain_to:#x}")
    chunk_ranges = sorted((c.va, c.end, c.index) for c in lay.chunks)
    for a, b in zip(chunk_ranges, chunk_ranges[1:]):
        if b[0] < a[1]:
            problems.append(f"chunks {a[2]} and {b[2]} overlap ({a[0]:#x}..{a[1]:#x} / {b[0]:#x}..)")
    allowed_branch = set(lay.exits) | set(lay.externals.values()) | boundaries
    cellset = set(lay.cells.values())
    for c in lay.chunks:
        for ins in decoded[c.index]:
            is_branch = ins.mnemonic == "call" or (ins.mnemonic[0] == "j" and ins.mnemonic != "jecxz") \
                or ins.mnemonic in ("loop", "loope", "loopne", "jecxz", "jrcxz")
            if is_branch and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
                t = ins.operands[0].imm
                if t not in allowed_branch:
                    inside = any(a <= t < b for a, b, _ in chunk_ranges)
                    problems.append(
                        f"{ins.address:#x} {ins.mnemonic} {ins.op_str}: target {t:#x} is "
                        + ("INSIDE an instruction (not a boundary)" if inside else
                           "not a declared exit/external and not in any chunk"))
            for o in ins.operands:
                if o.type != capstone.x86.X86_OP_MEM:
                    continue
                if o.mem.base == capstone.x86.X86_REG_RIP:
                    t = ins.address + ins.size + o.mem.disp
                    if t not in cellset:
                        problems.append(f"{ins.address:#x} {ins.mnemonic} {ins.op_str}: rip-relative "
                                        f"target {t:#x} is not a declared cell")
                elif o.mem.base == 0 and o.mem.index == 0 and o.mem.disp:
                    problems.append(f"{ins.address:#x} {ins.mnemonic} {ins.op_str}: ABSOLUTE memory "
                                    f"operand — a RIPREL placeholder was written without 'rip +'")
    if target is not None:
        for c in lay.chunks:
            cur = target.read_va(c.va, len(c.code))
            if cur != b"\xcc" * len(c.code):
                problems.append(f"chunk {c.index}: target bytes at {c.va:#x} are not int3 "
                                f"({cur.hex()}) — the spec would not reverse cleanly")
    if verbose:
        for c in lay.chunks:
            print(f"  chunk {c.index}: cave {c.cave.va:#x} ({c.cave.length} B) uses {len(c.code)} B"
                  + ("" if c.chain_to is None else f", chain -> {c.chain_to:#x}"))
            for ins in decoded[c.index]:
                print(f"      {ins.address:#x}  {ins.bytes.hex():<20s} {ins.mnemonic} {ins.op_str}")
    return problems


# ------------------------------------------------------------------------------- the hook
def hook_patch(target: Image, hook_va: int, stolen_len: int, entry_va: int, name: str) -> dict:
    """The 5-byte `jmp rel32` into the cave entry, padded with nop to `stolen_len`.

    Refuses unless the stolen region ends exactly on an instruction boundary.  Reports (does not
    fix) a rip-relative stolen instruction: this allocator never relocates stolen bytes — the
    caller's payload must re-materialise that instruction itself."""
    import capstone
    if stolen_len < CHAIN_LEN:
        raise Refuse(f"hook needs {CHAIN_LEN} bytes, only {stolen_len} stolen")
    if stolen_len > MAX_STOLEN:
        raise Refuse(f"stolen_len {stolen_len} > {MAX_STOLEN}: stealing this much of a live "
                     f"function is almost always a mis-derived hook, and every stolen byte must be "
                     f"re-materialised by hand in the payload")
    cur = target.read_va(hook_va, stolen_len)
    md = _md()
    n, rip, relbr = 0, [], []
    for ins in md.disasm(cur, hook_va):
        n += ins.size
        if any(o.type == capstone.x86.X86_OP_MEM and o.mem.base == capstone.x86.X86_REG_RIP
               for o in ins.operands):
            rip.append(f"{ins.address:#x} {ins.mnemonic} {ins.op_str}")
        # A RELATIVE branch among the stolen bytes is position-dependent in the same way a
        # rip-relative operand is: re-emitted verbatim at the cave's address it silently retargets
        # by (cave_va - hook_va), which is tens of MB away.  Only rip-relative MEMORY operands were
        # detected before, so this class went unreported.
        _m = ins.mnemonic
        if (_m == "call" or _m[0] == "j" or _m in ("loop", "loope", "loopne")) and ins.operands                 and ins.operands[0].type == capstone.x86.X86_OP_IMM:
            relbr.append(f"{ins.address:#x} {_m} {ins.op_str}")
        if n >= stolen_len:
            break
    if n != stolen_len:
        raise Refuse(f"stolen region {hook_va:#x}+{stolen_len} does not end on an instruction "
                     f"boundary (decode covers {n} B)")
    # A branch elsewhere that lands INSIDE the stolen region would arrive mid-`jmp` after the
    # patch.  hook_va itself is a legitimate destination; anything strictly inside is fatal.
    inbound = _branches_into(target, hook_va + 1, hook_va + stolen_len)
    if inbound:
        raise Refuse(f"stolen region {hook_va:#x}+{stolen_len} is branched INTO by "
                     + ", ".join(inbound[:4])
                     + (f" (+{len(inbound) - 4} more)" if len(inbound) > 4 else "")
                     + " — patching it would send those branches into the middle of the hook jmp")
    jb = asm_one(f"jmp {entry_va:#x}", hook_va)
    if len(jb) > CHAIN_LEN:
        raise Refuse("hook jmp did not encode as rel32")
    patch = jb + bytes([PAD_BYTE]) * (stolen_len - len(jb))
    d = dict(name=name, va=f"{hook_va:#x}", expect=cur.hex(), patch=patch.hex(), kind="code")
    if rip:
        d["stolen_riprel"] = rip          # provenance: the caller must have re-materialised these
    if relbr:
        raise Refuse("stolen bytes contain relative branch(es): " + ", ".join(relbr)
                     + " — re-emitting these in the cave would retarget them by the cave offset. "
                       "Move the hook, or shorten stolen_len so the branch stays in place.")
    return d


# -------------------------------------------------------------------------------- reserve
def reserve_caves(lay: Layout, spec_name: str, *, ledger: Path = LEDGER,
                  exclusive_group: str | None = None) -> None:
    """Record the claim so a later allocation cannot hand the same run out twice."""
    led = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else \
        dict(version=1, reservations=[])
    keep = [r for r in led.get("reservations", []) if r["spec"] != spec_name]
    for c in lay.chunks:
        e = dict(cave_va=f"{c.cave.va:#x}", cave_len=c.cave.length, used=len(c.code),
                 spec=spec_name, chunk=c.index)
        if exclusive_group:
            e["exclusive_group"] = exclusive_group
        keep.append(e)
    keep.sort(key=lambda r: (int(r["cave_va"], 16), r["spec"], r.get("chunk", 0)))
    led["version"] = 1
    led["reservations"] = keep
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(led, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------- the spec writer
def build_spec(*, description: str, prefix: str, asm_text: str, hook_va: int, stolen_len: int,
               exits: Iterable[int], target: Image, pristine: Image | None = None,
               externals: Mapping[str, int] = {}, cells: Mapping[str, int] = {},
               min_cave: int = 12, pool: Sequence[Cave] | None = None, safety: str = "A",
               extra: Mapping | None = None, audit: bool = True) -> tuple[dict, Layout]:
    """Lay out, verify, audit, prove determinism, and return (spec document, layout).

    The caller writes the file (and calls reserve_caves) only after ITS OWN proofs pass, so what
    was emulated is bit-for-bit what is written."""
    exits = tuple(exits)
    pol = dict(anchor=f"{hook_va:#x}", min_cave=min_cave, safety=safety,
               source="tools/cave_scan.py build/caves.json",
               gates=["length", "safety-tier", "int3-in-target", "unclaimed", "hook-guard"])
    if pool is None:
        pool, rej = cave_pool(target=target, pristine=pristine, min_len=min_cave, anchor=hook_va,
                              safety=safety)
        pol["free_caves"] = len(pool)
        pol["rejected"] = rej
    lay = layout_payload(asm_text, pool=pool, exits=exits, externals=externals, cells=cells,
                         policy=pol)
    again = layout_payload(asm_text, pool=pool, exits=exits, externals=externals, cells=cells,
                           policy=pol)
    if [c.code for c in lay.chunks] != [c.code for c in again.chunks] or \
       [c.cave.va for c in lay.chunks] != [c.cave.va for c in again.chunks]:
        raise Refuse("NON-DETERMINISTIC layout: re-running the allocation produced different bytes")
    problems = verify_layout(lay, target=target)
    if problems:
        raise Refuse("verification failed:\n  " + "\n  ".join(problems))
    if audit:
        problems = audit_caves([c.cave for c in lay.chunks], target=target, pristine=pristine)
        if problems:
            raise Refuse("cave audit failed:\n  " + "\n  ".join(problems))
    patches = lay.patches(target, prefix)                      # chunks FIRST …
    patches.append(hook_patch(target, hook_va, stolen_len, lay.entry,
                              f"{prefix} hook -> cave entry {lay.entry:#x}"))  # … hook LAST
    # intra-spec overlap
    rs = sorted((int(p["va"], 16), int(p["va"], 16) + len(bytes.fromhex(p["patch"])), p["name"])
                for p in patches)
    for a, b in zip(rs, rs[1:]):
        if b[0] < a[1]:
            raise Refuse(f"spec entries overlap: {a[2]!r} and {b[2]!r}")
    # collision with any committed spec / the ledger
    for va, end, owner in claimed_ranges():
        for lo, hi, nm in rs:
            if lo < end and hi > va:
                raise Refuse(f"{nm!r} ({lo:#x}..{hi:#x}) collides with {owner} ({va:#x}..{end:#x})")
    doc = dict(description=description)
    doc.update(dict(extra or {}))
    doc["cave_layout"] = lay.provenance()
    doc["cave_layout"]["target_image_sha1"] = target.sha1
    if pristine is not None:
        doc["cave_layout"]["pristine_sha1"] = pristine.sha1
    doc["patches"] = patches
    return doc, lay


def write_spec(doc: dict, lay: Layout, path: Path, *, reserve: bool = True,
               exclusive_group: str | None = None) -> Path:
    """Write the spec file and claim its caves.  Call this ONLY after the caller's own proofs
    (emulation of `lay.overlays()`) have passed — what was proven is then what is written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    if reserve:
        reserve_caves(lay, path.name, exclusive_group=exclusive_group)
    return path


# ------------------------------------------------------------------------------------- CLI
def _images(a):
    t = Image(Path(a.exe))
    p = Image(PRISTINE) if PRISTINE.exists() else None
    return t, p


def cmd_pool(a):
    t, p = _images(a)
    anchor = int(a.near, 16) if a.near else None
    pool, rej = cave_pool(target=t, pristine=p, min_len=a.min, anchor=anchor, safety=a.safety)
    tot = sum(c.payload for c in pool)
    print(f"target {t.path.name} sha1 {t.sha1[:16]}…")
    print(f"pool source {POOL_JSON}  safety tier {a.safety!r}  min length {a.min}")
    print(f"free caves {len(pool):,}   payload capacity {tot:,} B   rejected {rej}")
    if pool:
        print(f"lengths: min {min(c.length for c in pool)} max {max(c.length for c in pool)} "
              f"mean {sum(c.length for c in pool) / len(pool):.2f}; "
              f"largest single instruction placeable: {max(c.payload for c in pool)} B")
    if anchor:
        print(f"nearest {a.limit} to {anchor:#x}:")
        for c in pool[:a.limit]:
            print(f"   {c.va:#x}  len {c.length:3d}  payload {c.payload:3d}  "
                  f"{'+' if c.va >= anchor else '-'}{abs(c.va - anchor):#x}  {','.join(c.why)}")
    return 0


def seed_ledger(target: Image, *, write: bool = False) -> dict:
    """Derive the ledger from what is already committed: every patch entry whose `expect` is all
    0xCC is a cave claim.  Runs claimed by more than one spec are grouped — those specs are
    mutually exclusive BY HAND (five of them target 0x1438b4835), and a ledger that pretended the
    conflict did not exist would either abort every future allocation or teach the reader to
    ignore ledger errors."""
    pool_runs = {}
    for va, ln in zip(*int3_runs(Image(PRISTINE) if PRISTINE.exists() else target)):
        pool_runs[int(va)] = int(ln)
    starts = sorted(pool_runs)
    np = _np()
    sa = np.array(starts, dtype=np.int64)
    res = []
    for p in _spec_files():
        d = json.loads(p.read_text(encoding="utf-8"))
        entries = d["patches"] if isinstance(d, dict) and "patches" in d else d
        for e in (entries if isinstance(entries, list) else [entries]):
            exp = bytes.fromhex(e.get("expect", "").replace(" ", ""))
            if not exp or set(exp) != {0xCC}:
                continue
            va = int(e["va"], 16) if "va" in e else BASE + int(e["module_offset"], 16)
            i = int(np.searchsorted(sa, va, side="right")) - 1
            run_va = starts[i] if i >= 0 and va < starts[i] + pool_runs[starts[i]] else va
            res.append(dict(cave_va=f"{run_va:#x}", cave_len=pool_runs.get(run_va, len(exp)),
                            used=len(exp), at=f"{va:#x}", spec=p.name))
    groups = {}
    for r in res:
        groups.setdefault(r["cave_va"], []).append(r["spec"])
    for r in res:
        if len({s for s in groups[r["cave_va"]]}) > 1:
            r["exclusive_group"] = f"run-{r['cave_va']}"
    res.sort(key=lambda r: (int(r["cave_va"], 16), r["at"], r["spec"]))
    led = dict(version=1,
               note=("Cave claims. Derived from tools/data/patches/*.json by "
                     "`python tools/cave_alloc.py seed-ledger` (every entry whose expect is all "
                     "0xCC), plus whatever tools/cave_alloc.py reserve_caves() adds. Entries "
                     "sharing an exclusive_group are alternative payloads for the SAME run and "
                     "are mutually exclusive by hand — at most one may be applied at a time."),
               reservations=res)
    if write:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(led, indent=1) + "\n", encoding="utf-8")
    return led


def cmd_seed(a):
    t, _ = _images(a)
    led = seed_ledger(t, write=True)
    print(f"wrote {LEDGER} — {len(led['reservations'])} claim(s) across "
          f"{len({r['cave_va'] for r in led['reservations']})} run(s)")
    for r in led["reservations"]:
        print(f"   {r['cave_va']} len {r['cave_len']:>3}  at {r['at']} +{r['used']:>3}  {r['spec']}"
              + ("   [" + r["exclusive_group"] + "]" if "exclusive_group" in r else ""))
    return 0


def cmd_audit(a):
    t, _p = _images(a)
    claims = claimed_ranges()
    print(f"{len(claims)} claimed byte range(s) across {len(_spec_files())} spec file(s) + ledger")
    norm = lambda o: o.replace(" (ledger)", "")                             # noqa: E731
    overlaps, pairs = 0, set()
    for i, (va, end, owner) in enumerate(claims):
        for va2, end2, owner2 in claims[i + 1:]:
            if va2 >= end:
                break
            if norm(owner2) == norm(owner):          # a spec and its own ledger row are one claim
                continue
            key = tuple(sorted((norm(owner), norm(owner2))))
            if key in pairs:
                continue
            pairs.add(key)
            overlaps += 1
            if overlaps <= 20:
                print(f"  COLLISION {va:#x}..{end:#x} {norm(owner)}  vs  "
                      f"{va2:#x}..{end2:#x} {norm(owner2)}")
    print(f"{overlaps} colliding spec pair(s) — EXPECTED for the alternative payloads that share a "
          f"run (see the exclusive_group rows in the ledger); at most one of each group may be "
          f"applied, which the expect-gate enforces anyway")
    if LEDGER.exists():
        led = json.loads(LEDGER.read_text(encoding="utf-8"))
        names = {r["spec"] for r in led.get("reservations", [])}
        missing = sorted(n for n in names if not (PATCH_DIR / n).exists())
        print(f"ledger: {len(led.get('reservations', []))} reservation(s); "
              f"{'orphans: ' + ', '.join(missing) if missing else 'no orphans'}")
    else:
        print(f"ledger: {LEDGER} does not exist yet (no chained cave has been reserved)")
    return 0


DEMO = """
        movsxd   rax, dword ptr [r12 + 0x23c]
        cvtsi2ss xmm0, eax
        mulss    xmm0, dword ptr [rip + RIPREL_$gain]
        cvttss2si eax, xmm0
        cmp      eax, 4000
        jle      @clamped
        mov      eax, 4000
    clamped:
        sub      edi, eax
        jmp      @done
    done:
        jmp      {exit:#x}
"""


def cmd_demo(a):
    t, p = _images(a)
    anchor = int(a.near, 16)
    pool, rej = cave_pool(target=t, pristine=p, min_len=a.min, anchor=anchor, safety=a.safety)
    print(f"free caves {len(pool):,}  rejected {rej}")
    lay = layout_payload(DEMO.format(exit=anchor + 0x1C), pool=pool, exits=(anchor + 0x1C,),
                         cells={"gain": 0x145AE7580}, policy=dict(anchor=f"{anchor:#x}"))
    print(f"entry {lay.entry:#x}, {len(lay.chunks)} chunk(s), {lay.total_used()} B written, "
          f"{lay.payload_bytes()} B payload")
    probs = verify_layout(lay, target=t, verbose=True)
    print("verify:", "PASS" if not probs else "FAIL\n  " + "\n  ".join(probs))
    return 0 if not probs else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--min", type=int, default=12)
    ap.add_argument("--safety", default="A")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("pool"); q.add_argument("--near"); q.add_argument("--limit", type=int, default=20)
    sub.add_parser("audit")
    sub.add_parser("seed-ledger")
    q = sub.add_parser("demo"); q.add_argument("--near", default="0x143da6529")
    a = ap.parse_args(argv)
    try:
        return {"pool": cmd_pool, "audit": cmd_audit, "demo": cmd_demo,
                "seed-ledger": cmd_seed}[a.cmd](a)
    except Refuse as ex:
        print(f"REFUSED: {ex}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
