#!/usr/bin/env python3
"""
cave_scan.py — enumerate and SAFETY-CLASSIFY int3 code caves in eFootball.exe.

Produces build/caves.json: a stable, sorted allocation pool that tools/exe_patch.py's
chained-cave allocator draws from.  Every cave in the pool is padding that the linker
emitted *between* two functions; nothing in the image can reach it.

    python tools/cave_scan.py scan                     # installed exe -> build/caves.json
    python tools/cave_scan.py scan --image <path>      # e.g. the PRISTINE reference
    python tools/cave_scan.py scan --min 12            # only keep runs >= 12 bytes
    python tools/cave_scan.py scan --out build/caves-pristine.json --image <PRISTINE>
    python tools/cave_scan.py report                   # re-print the report from build/caves.json
    python tools/cave_scan.py near 0x143da6529 12 40   # caves nearest a hook, >=12 B, best 40
    python tools/cave_scan.py show 0x1438b4835 [n]     # disassemble a VA (is this cave occupied?)
    python tools/cave_scan.py reach                    # prove a 5-byte jmp rel32 spans .xcode

NOTHING here writes to the game.  It only reads the image.

----------------------------------------------------------------------------------------
THE SAFETY ORACLE
----------------------------------------------------------------------------------------
.pdata (the EXCEPTION data directory — in this image the whole `.trace` section) is a
sorted array of RUNTIME_FUNCTION {BeginAddress, EndAddress, UnwindInfoAddress}.  It is
authoritative: the OS unwinder uses it.  A byte range that lies strictly BETWEEN one
entry's EndAddress and the next entry's BeginAddress is not part of any function that
has unwind data.

Tier A ("pdata-bounded padding") is the only tier admitted to the pool by default:

  * the run starts EXACTLY at some function's EndAddress, and
  * the run ends   EXACTLY at the next function's BeginAddress, and
  * that next BeginAddress is 16-byte aligned (it is a function entry), and
  * no rel32 call/jmp/jcc anywhere in .xcode targets a byte of the run, and
  * no rel8 branch decoded from the preceding function's real instruction stream
    targets a byte of the run, and that sweep's LAST instruction is a function
    terminator (ret / jmp / int3 / ud2 / hlt / nop) — a function that appears to fall
    through into the padding is rejected, and
  * no 8-aligned qword anywhere in the image equals a VA inside the run
    (vftable / function-pointer table entry), and
  * no JUMP TABLE reaches it: MSVC x64 switch tables are runs of image-relative u32s,
    so we veto on a u32 that is part of a table (>=3 consecutive 4-aligned u32s all
    pointing into .xcode within 64 KB of each other) and not on a bare u32 coincidence
    -- a bare match fires half a million times in a 352 MB image and means nothing, and
  * the run does not overlap any byte named by a spec in tools/data/patches/*.json.

Tier B ("unaccounted gap") is outside every RUNTIME_FUNCTION but is NOT tightly bounded:
the neighbouring pdata entries are further away, so the space between them contains
something pdata does not describe — leaf functions with no unwind data, jump tables, or
read-only blobs embedded in .xcode.  Those runs may well be padding too, but the proof
is weaker.  They are emitted with safety "B" and are excluded from the pool unless you
pass --include-b.

Anything overlapping a RUNTIME_FUNCTION body is "reject/inside-function" and never
offered: padding *inside* a function is usually a jump-table gutter or an aligned loop
head, and writing there corrupts live code.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
PATCHES = REPO / "tools" / "data" / "patches"
INSTALLED = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
PRISTINE = Path.home() / "Backups" / "eFootball" / "eFootball.exe.PRISTINE"
OUT = BUILD / "caves.json"

IMAGE_BASE_DEFAULT = 0x140000000
CODE_SECTION = ".xcode"
JMP_LEN = 5                      # jmp rel32
MATCH_BAND = (0x143000000, 0x144800000)

# a cave must hold at least one payload byte plus the 5-byte chain jump
MIN_USEFUL = JMP_LEN + 1

WHY_LEGEND = {
    "pdata-bounded": "run starts exactly at a RUNTIME_FUNCTION EndAddress and ends exactly at the "
                     "next BeginAddress — it is the linker's inter-function alignment padding",
    "align16": "that next function entry is 16-byte aligned",
    "no-refs": "no rel32 call/jmp/jcc in .xcode, no 8-aligned qword in the image, and no jump-table "
               "u32 anywhere in the image targets a byte of this run",
    "sweep:<insn>": "linear disassembly of the preceding function, anchored on its RUNTIME_FUNCTION "
                    "BeginAddress, reached the padding exactly; <insn> is the last real instruction "
                    "and no rel8 branch in that function enters the run",
    "rel8-backstop": "the preceding function was too long to sweep; instead no byte in the 130 before "
                     "the run could possibly be a rel8 branch landing inside it",
    "outside-all-functions": "tier B only — outside every RUNTIME_FUNCTION but not tightly bounded",
    "gap:<n>": "tier B only — the unaccounted gap the run sits in is <n> bytes",
}


# ----------------------------------------------------------------------------------------
# PE
# ----------------------------------------------------------------------------------------

class Image:
    def __init__(self, path: Path):
        import numpy as np
        self.path = Path(path)
        self.m = np.fromfile(self.path, dtype=np.uint8)
        d = self.m[:0x2000].tobytes()
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        self.nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.dll_characteristics = struct.unpack_from("<H", d, pe + 24 + 70)[0]
        ndir = struct.unpack_from("<I", d, pe + 24 + 108)[0]
        self.dirs = [struct.unpack_from("<II", d, pe + 24 + 112 + 8 * i) for i in range(min(ndir, 16))]
        self.secs = []
        for i in range(self.nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            ch = struct.unpack_from("<I", s, 36)[0]
            self.secs.append(dict(name=s[:8].rstrip(b"\0").decode(errors="replace"),
                                  rva=va, vsize=vsize, raw=raw, rsize=rsize, ch=ch,
                                  exec=bool(ch & 0x20000000)))

    def sec(self, name):
        for s in self.secs:
            if s["name"] == name:
                return s
        sys.exit(f"section {name} not found in {self.path}")

    def rva2off(self, rva: int):
        for s in self.secs:
            if s["rva"] <= rva < s["rva"] + s["vsize"]:
                o = rva - s["rva"]
                return None if o >= s["rsize"] else s["raw"] + o
        return None

    def sha1(self) -> str:
        h = hashlib.sha1()
        h.update(self.m.tobytes())
        return h.hexdigest()


# ----------------------------------------------------------------------------------------
# steps
# ----------------------------------------------------------------------------------------

def find_runs(img: Image, code, min_len: int):
    """every maximal run of 0xCC in the code section -> (starts_rva, lengths) numpy arrays."""
    import numpy as np
    x = img.m[code["raw"]: code["raw"] + code["rsize"]]
    cc = (x == 0xCC).view(np.int8)
    d = np.diff(np.concatenate(([np.int8(0)], cc, [np.int8(0)])).astype(np.int16))
    s = np.flatnonzero(d == 1).astype(np.int64)
    e = np.flatnonzero(d == -1).astype(np.int64)
    L = e - s
    keep = L >= min_len
    return s[keep] + code["rva"], L[keep], x


def load_pdata(img: Image):
    """merged, sorted [begin,end) RVA intervals of every RUNTIME_FUNCTION in the image."""
    import numpy as np
    rva, size = img.dirs[3]
    if not rva or not size:
        sys.exit("image has no EXCEPTION directory — cannot classify safely")
    off = img.rva2off(rva)
    n = (size // 12) * 12
    a = np.frombuffer(img.m[off:off + n].tobytes(), dtype="<u4").reshape(-1, 3)
    a = a[a[:, 0] != 0]
    o = np.argsort(a[:, 0], kind="stable")
    b = a[o, 0].astype(np.int64)
    e = a[o, 1].astype(np.int64)
    mb, me = [], []
    cb, ce = int(b[0]), int(e[0])
    for bi, ei in zip(b[1:], e[1:]):
        bi, ei = int(bi), int(ei)
        if bi <= ce:
            ce = max(ce, ei)
        else:
            mb.append(cb); me.append(ce); cb, ce = bi, ei
    mb.append(cb); me.append(ce)
    return len(a), np.array(mb, dtype=np.int64), np.array(me, dtype=np.int64)


def rel32_targets(img: Image, code, x, mask):
    """RVAs inside a run that a rel32 call/jmp/jcc in the code section points at.

    Byte-level scan, so it over-reports (an 0xE8 inside an operand looks like a call).
    Over-reporting only makes us MORE conservative, which is the right error to make.
    """
    import numpy as np
    xr = code["rva"]
    hits = []

    def rel(pos, extra):
        r = (x[pos].astype(np.int64) | (x[pos + 1].astype(np.int64) << 8)
             | (x[pos + 2].astype(np.int64) << 16) | (x[pos + 3].astype(np.int64) << 24))
        r = np.where(r >= 2 ** 31, r - 2 ** 32, r)
        return pos + 4 + r

    p = np.flatnonzero((x[:-5] == 0xE8) | (x[:-5] == 0xE9))
    t = rel(p + 1, 5)
    hits.append(t[(t >= 0) & (t < len(x))])
    p = np.flatnonzero((x[:-6] == 0x0F) & (x[1:-5] >= 0x80) & (x[1:-5] <= 0x8F))
    t = rel(p + 2, 6)
    hits.append(t[(t >= 0) & (t < len(x))])
    t = np.concatenate(hits)
    t = t[mask[t]]
    return np.unique(t) + xr


def pointer_refs(img: Image, code, mask):
    """(abs_qword_hits, rva32_table_hits, raw_rva32_count).

    * abs_qword: an 8-aligned qword anywhere in the image equal to a VA inside a run —
      a vftable slot or a function-pointer table entry.  Full 64-bit equality, so a
      random collision is ~impossible: every hit is worth vetoing.
    * rva32_table: MSVC x64 switch jump tables store IMAGE-RELATIVE u32s.  A bare
      "some u32 equals this RVA" test is useless here — 88 M u32s in a 352 MB image
      produce a quarter of a million coincidences.  So we only trust a u32 that is part
      of a TABLE: >= 3 consecutive 4-aligned u32s that all point into the code section
      and all lie within 64 KB of each other (a real jump table's arms are inside one
      function).  That drops the hit count by ~5000x and leaves a real signal.
    """
    import numpy as np
    xr, xsz = code["rva"], code["rsize"]
    lo_va, hi_va = img.base + xr, img.base + xr + xsz
    n8 = (len(img.m) // 8) * 8
    q = img.m[:n8].view("<u8")
    sel = q[(q >= lo_va) & (q < hi_va)]
    r = (sel - img.base - xr).astype(np.int64)
    qhit = np.unique(r[mask[r]]) + xr

    n4 = (len(img.m) // 4) * 4
    w = img.m[:n4].view("<u4")
    idx = np.flatnonzero((w >= xr) & (w < xr + xsz))
    raw = int(mask[(w[idx].astype(np.int64) - xr)].sum())
    d = np.diff(idx)
    brk = np.flatnonzero(d != 1)
    s0 = np.concatenate(([0], brk + 1))
    s1 = np.concatenate((brk + 1, [len(idx)]))
    keep = []
    for s, e in zip(s0[(s1 - s0) >= 3].tolist(), s1[(s1 - s0) >= 3].tolist()):
        v = w[idx[s:e]]
        if int(v.max()) - int(v.min()) <= 0x10000:
            keep.append(idx[s:e])
    if keep:
        tv = np.unique(w[np.concatenate(keep)]).astype(np.int64)
        whit = np.unique(tv[mask[tv - xr]])
    else:
        whit = np.zeros(0, dtype=np.int64)
    return qhit, whit, raw


def rel8_into(x, xr, func_begin_rva, run_lo, run_hi):
    """PRECISE rel8 test: linear-sweep the real instruction stream of the function that
    precedes the run and see whether any short branch lands inside [run_lo, run_hi).

    func_begin_rva is a RUNTIME_FUNCTION BeginAddress, so it is a guaranteed instruction
    boundary — the sweep is trustworthy, unlike a backwards guess.
    Returns (verdict, last_mnemonic): verdict in {"clean","hit","desync"}.
    """
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    md = _md(Cs, CS_ARCH_X86, CS_MODE_64)
    lo = max(func_begin_rva, run_lo - 4096)
    if lo != func_begin_rva:                      # too far to sweep honestly
        return "unswept", None
    buf = x[lo - xr: run_lo - xr].tobytes()
    last = None
    addr = lo
    for ins in md.disasm(buf, lo):
        addr = ins.address + ins.size
        last = ins
        if ins.mnemonic in _SHORT and ins.op_str.startswith("0x"):
            try:
                t = int(ins.op_str, 16)
            except ValueError:
                continue
            if run_lo <= t < run_hi:
                return "hit", ins.mnemonic
    if addr != run_lo:
        return "desync", (last.mnemonic if last else None)
    return "clean", (last.mnemonic if last else None)


_SHORT = {"jmp", "je", "jne", "jz", "jnz", "ja", "jae", "jb", "jbe", "jg", "jge", "jl",
          "jle", "js", "jns", "jo", "jno", "jp", "jnp", "jrcxz", "loop", "loope", "loopne"}
# what a function is allowed to end with, immediately before alignment padding
_TERMINATOR = {"ret", "retf", "jmp", "int3", "ud2", "hlt", "iret", "iretd", "iretq", "nop"}


def rel8_backstop(x, xr, run_lo, run_hi):
    """Cheap, deliberately over-eager rel8 test for runs we could not sweep honestly.

    A rel8 branch reaches +-127, so only the 130 bytes before the run matter.  We do not
    know which of those bytes are real opcodes, so we treat EVERY byte that could be one
    as if it were.  False alarms only cost us a cave we did not need.
    """
    lo = max(0, run_lo - 130 - xr)
    b = x[lo: run_lo - xr]
    for i in range(len(b) - 1):
        op = int(b[i])
        if op == 0xEB or 0x70 <= op <= 0x7F or 0xE0 <= op <= 0xE3:
            r = int(b[i + 1])
            t = lo + xr + i + 2 + (r - 256 if r >= 128 else r)
            if run_lo <= t < run_hi:
                return False
    return True
_MDCACHE = {}


def _md(Cs, arch, mode):
    k = (arch, mode)
    if k not in _MDCACHE:
        md = Cs(arch, mode)
        md.detail = False
        _MDCACHE[k] = md
    return _MDCACHE[k]


def spec_intervals():
    """[(rva, rva+len, specname, patchname)] for every byte any patch spec touches."""
    out = []
    if not PATCHES.exists():
        return out
    for p in sorted(PATCHES.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = d.get("patches", d) if isinstance(d, dict) else d
        if isinstance(items, dict):
            items = [items]
        for s in items or []:
            if not isinstance(s, dict) or "patch" not in s:
                continue
            if "module_offset" in s:
                rva = int(s["module_offset"], 16)
            elif "va" in s:
                rva = int(s["va"], 16) - IMAGE_BASE_DEFAULT
            else:
                continue
            n = len(bytes.fromhex(s["patch"].replace(" ", "").replace("_", "")))
            out.append((rva, rva + n, p.name, s.get("name", "")))
    return out


# ----------------------------------------------------------------------------------------
# scan
# ----------------------------------------------------------------------------------------

def cmd_scan(a):
    import numpy as np
    img = Image(Path(a.image))
    code = img.sec(CODE_SECTION)
    if code["rsize"] < code["vsize"]:
        print(f"note: {CODE_SECTION} has {code['vsize']-code['rsize']} virtual-only bytes (not scannable)")
    print(f"image  {img.path}")
    print(f"       {len(img.m):,} B, base {img.base:#x}, ASLR {'on' if img.dll_characteristics & 0x40 else 'OFF'}")
    print(f"{CODE_SECTION}  VA {img.base+code['rva']:#x}  size {code['rsize']:#x}  file {code['raw']:#x}  "
          f"exec {code['exec']}")

    starts, L, x = find_runs(img, code, a.scan_min)
    print(f"\nint3 runs >= {a.scan_min} B in {CODE_SECTION}: {len(starts):,}  ({int(L.sum()):,} bytes)")

    nfun, mb, me = load_pdata(img)
    xr, xsz = code["rva"], code["rsize"]
    covsel = mb < xr + xsz
    cov = int((np.minimum(me[covsel], xr + xsz) - np.maximum(mb[covsel], xr)).clip(0).sum())
    print(f".pdata: {nfun:,} RUNTIME_FUNCTIONs -> {len(mb):,} merged ranges; "
          f"they cover {cov:,}/{xsz:,} = {cov/xsz*100:.1f}% of {CODE_SECTION}")

    rs = starts
    re_ = starts + L
    i = np.searchsorted(mb, rs, side="right") - 1
    ii = np.clip(i, 0, len(mb) - 1)
    prev_end = np.where(i >= 0, me[ii], xr)
    nxt_beg = np.where(i + 1 < len(mb), mb[np.clip(i + 1, 0, len(mb) - 1)], xr + xsz)
    inside = ~((prev_end <= rs) & (re_ <= nxt_beg))
    bounded = (rs == prev_end) & (re_ == nxt_beg)
    align16 = (re_ % 16) == 0

    print(f"\npdata verdict on those runs:")
    print(f"  inside a RUNTIME_FUNCTION body (REJECTED)          {int(inside.sum()):,}")
    print(f"  outside every RUNTIME_FUNCTION                     {int((~inside).sum()):,}")
    print(f"    of which exactly End..Begin bounded (tier A)     {int(bounded.sum()):,}")
    print(f"    of which in a larger unaccounted gap (tier B)    {int((~inside & ~bounded).sum()):,}")

    # byte mask of every run byte, for the reference scans
    mask = np.zeros(xsz, dtype=bool)
    for s, l in zip(rs.tolist(), L.tolist()):
        mask[s - xr: s - xr + l] = True

    t32 = rel32_targets(img, code, x, mask)
    qhit, whit, raw32 = pointer_refs(img, code, mask)
    print(f"\nreference scans over the whole image:")
    print(f"  rel32 call/jmp/jcc targets landing inside a run    {len(t32):,} byte(s)")
    print(f"  8-aligned qwords pointing inside a run             {len(qhit):,}")
    print(f"  u32 RVAs inside a run, bare (mostly coincidence)   {raw32:,}")
    print(f"  u32 RVAs inside a run, part of a jump TABLE        {len(whit):,}")

    def veto_runs(hit_rvas):
        out = np.zeros(len(rs), dtype=bool)
        if len(hit_rvas) == 0:
            return out
        h = np.asarray(hit_rvas, dtype=np.int64)
        j = np.searchsorted(rs, h, side="right") - 1
        ok = j >= 0
        j, h = j[ok], h[ok]
        ok = h < rs[j] + L[j]                      # the hit really is inside that run
        out[np.unique(j[ok])] = True
        return out

    v32, vq, vw = veto_runs(t32), veto_runs(qhit), veto_runs(whit)
    print(f"  -> runs vetoed: rel32 {int(v32.sum()):,}  qword {int(vq.sum()):,}  u32 {int(vw.sum()):,}")

    specs = spec_intervals()
    vspec = np.zeros(len(rs), dtype=bool)
    spec_why = {}
    for lo, hi, sname, pname in specs:
        j = np.flatnonzero((rs < hi) & (re_ > lo))
        for k in j.tolist():
            vspec[k] = True
            spec_why.setdefault(k, []).append(f"{sname}:{pname}")
    print(f"  -> runs reserved by tools/data/patches/*.json       {int(vspec.sum()):,} "
          f"(from {len(specs)} patch byte-ranges)")

    # precise rel8 sweep, only for the tier-A survivors (cheap: they have a real anchor)
    cand = np.flatnonzero(bounded & ~v32 & ~vq & ~vw & ~vspec & (L >= a.min))
    print(f"\ntier-A survivors before the rel8 sweep: {len(cand):,}")
    r8_hit, r8_desync, r8_clean = 0, 0, 0
    last_mn = collections.Counter()
    verdicts = {}
    if not a.no_rel8:
        # the anchor for run k is the merged range that ends exactly at its start
        for k in cand.tolist():
            ai = int(np.searchsorted(me, rs[k], side="left"))
            fb = int(mb[ai]) if ai < len(mb) and me[ai] == rs[k] else -1
            if fb < 0:
                verdicts[k] = ("unswept", None)
                continue
            v, mn = rel8_into(x, xr, fb, int(rs[k]), int(re_[k]))
            if v == "unswept":                       # preceding function too long to sweep
                v = "backstop" if rel8_backstop(x, xr, int(rs[k]), int(re_[k])) else "hit"
                mn = None
            verdicts[k] = (v, mn)
            if v == "hit":
                r8_hit += 1
            elif v == "desync":
                r8_desync += 1
            elif v == "clean":
                r8_clean += 1
                last_mn[mn or "?"] += 1
        print(f"  rel8 sweep of the preceding function: clean {r8_clean:,}  "
              f"desync {r8_desync:,}  branch-into-run {r8_hit:,}  "
              f"byte-backstop {len(cand)-r8_clean-r8_desync-r8_hit:,}")
        print(f"  last instruction before the padding (clean sweeps): "
              f"{', '.join(f'{m} x{c:,}' for m, c in last_mn.most_common(10))}")
        good = sum(c for m, c in last_mn.items() if m in _TERMINATOR)
        print(f"  -> {good:,}/{r8_clean:,} = {good/max(r8_clean,1)*100:.2f}% of clean sweeps end on a "
              f"function terminator ({'/'.join(sorted(_TERMINATOR))})")

    caves = []
    rejected = collections.Counter()
    tier_b_stats = [0, 0]
    for k in range(len(rs)):
        va = int(img.base + rs[k])
        why = []
        if inside[k]:
            rejected["inside-function"] += 1
            continue
        if vspec[k]:
            rejected["reserved-by-patch-spec"] += 1
            continue
        if v32[k]:
            rejected["rel32-branch-target"] += 1
            continue
        if vq[k]:
            rejected["absolute-pointer-target"] += 1
            continue
        if vw[k]:
            rejected["jump-table-reference"] += 1
            continue
        if int(L[k]) < a.min:
            rejected["below-min"] += 1
            continue
        if bounded[k]:
            v, mn = verdicts.get(k, ("skipped", None))
            if v == "hit":
                rejected["rel8-branch-target"] += 1
                continue
            if v == "desync":
                rejected["preceding-code-desync"] += 1
                continue
            if v == "clean" and mn not in _TERMINATOR:
                rejected["no-terminator-before-padding"] += 1
                continue
            if not align16[k]:
                rejected["run-end-not-16-aligned"] += 1
                continue
            safety = "A"
            why = ["pdata-bounded", "align16", "no-refs"]
            why.append(f"sweep:{mn}" if v == "clean" else "rel8-backstop")
        else:
            safety = "B"
            why = ["outside-all-functions", "no-refs", f"gap:{int(nxt_beg[k]-prev_end[k])}"]
        if safety == "B":
            tier_b_stats[0] += 1
            tier_b_stats[1] += int(L[k])
            if not a.include_b:
                rejected["tier-B-not-admitted"] += 1
                continue
        caves.append(dict(va=f"{va:#x}", file_off=f"{img.rva2off(int(rs[k])):#x}",
                          length=int(L[k]), safety=safety, why=why))

    caves.sort(key=lambda c: int(c["va"], 16))

    tot = sum(c["length"] for c in caves)
    pay = sum(c["length"] - JMP_LEN for c in caves)
    band = [c for c in caves if MATCH_BAND[0] <= int(c["va"], 16) < MATCH_BAND[1]]
    meta = dict(
        tool="tools/cave_scan.py",
        image=str(img.path), image_size=len(img.m), image_sha1=img.sha1(),
        image_base=f"{img.base:#x}",
        section=dict(name=CODE_SECTION, va=f"{img.base+code['rva']:#x}", size=code["rsize"],
                     file_off=code["raw"]),
        pdata=dict(entries=nfun, merged=len(mb), coverage_pct=round(cov / xsz * 100, 2)),
        scan_min=a.scan_min, min=a.min, include_b=bool(a.include_b),
        jmp_len=JMP_LEN,
        counts=dict(runs_scanned=len(rs), pool=len(caves),
                    tier_A=sum(1 for c in caves if c["safety"] == "A"),
                    tier_B=sum(1 for c in caves if c["safety"] == "B"),
                    rejected=dict(rejected),
                    tier_B_available=dict(runs=tier_b_stats[0], raw_bytes=tier_b_stats[1],
                                          payload_bytes=max(tier_b_stats[1] - JMP_LEN * tier_b_stats[0], 0))),
        capacity=dict(total_bytes=tot, payload_bytes_after_chain_jumps=pay,
                      in_match_band=dict(lo=f"{MATCH_BAND[0]:#x}", hi=f"{MATCH_BAND[1]:#x}",
                                         caves=len(band),
                                         payload_bytes=sum(c["length"] - JMP_LEN for c in band))),
    )
    meta["why_legend"] = WHY_LEGEND
    BUILD.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if getattr(a, "out", None) else OUT
    with open(out, "w", encoding="utf-8", newline="\n") as f:   # one cave per line:
        f.write('{\n "meta": ')                                #   greppable, diffable, 4x smaller
        f.write(json.dumps(meta, indent=1))
        f.write(',\n "caves": [\n')
        for i, c in enumerate(caves):
            f.write("  " + json.dumps(c, separators=(",", ":"))
                    + (",\n" if i + 1 < len(caves) else "\n"))
        f.write(" ]\n}\n")

    print(f"\ntier B (outside every function, but in an unaccounted gap): {tier_b_stats[0]:,} runs, "
          f"{tier_b_stats[1]:,} B raw, {max(tier_b_stats[1] - JMP_LEN * tier_b_stats[0], 0):,} B payload "
          f"— {'ADMITTED' if a.include_b else 'held back (pass --include-b to use them)'}")
    print(f"\nrejections: " + ", ".join(f"{k} {v:,}" for k, v in rejected.most_common()))
    print(f"\nwrote {out}  ({len(caves):,} caves, {tot:,} B raw, {pay:,} B payload after "
          f"{JMP_LEN}-byte chain jumps)")
    _capacity_table(caves)
    print(f"\nin the match band {MATCH_BAND[0]:#x}-{MATCH_BAND[1]:#x}: {len(band):,} caves, "
          f"{sum(c['length']-JMP_LEN for c in band):,} B payload")
    return 0


def _capacity_table(caves):
    print(f"\n{'min run':>8} {'caves':>9} {'raw bytes':>12} {'payload bytes':>14}")
    for t in (6, 8, 10, 12, 14, 16, 20, 24, 32, 40, 64):
        sel = [c for c in caves if c["length"] >= t]
        if not sel:
            print(f"{t:>8} {0:>9} {0:>12} {0:>14}")
            continue
        print(f"{t:>8} {len(sel):>9,} {sum(c['length'] for c in sel):>12,} "
              f"{sum(c['length']-JMP_LEN for c in sel):>14,}")


def cmd_near(a):
    """the caves closest to a hook site — proximity buys nothing but easier debugging."""
    pool = Path(a.pool) if a.pool else OUT
    d = json.loads(pool.read_text(encoding="utf-8"))
    va = int(a.va, 16)
    sel = [c for c in d["caves"] if c["length"] >= a.min]
    sel.sort(key=lambda c: abs(int(c["va"], 16) - va))
    run = 0
    print(f"{len(sel):,} caves >= {a.min} B in {pool.name}; nearest to {va:#x}:")
    print(f"{'va':>14} {'file_off':>11} {'len':>4} {'payload':>8} {'delta':>12} {'cum payload':>12}  why")
    for c in sel[:a.n]:
        cv = int(c["va"], 16)
        run += c["length"] - JMP_LEN
        print(f"{c['va']:>14} {c['file_off']:>11} {c['length']:>4} {c['length']-JMP_LEN:>8} "
              f"{cv-va:>+12,} {run:>12}  {','.join(c['why'])}")
    return 0


def cmd_report(a):
    d = json.loads(OUT.read_text(encoding="utf-8"))
    print(json.dumps(d["meta"], indent=1))
    _capacity_table(d["caves"])
    return 0


def cmd_show(a):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    img = Image(Path(a.image))
    va = int(a.va, 16)
    off = img.rva2off(va - img.base)
    n = a.n
    buf = img.m[off:off + n].tobytes()
    print(f"{img.path.name} @ va {va:#x} (file {off:#x}), {n} bytes")
    print("  raw:", buf.hex())
    nonCC = sum(1 for b in buf if b != 0xCC)
    print(f"  {nonCC}/{n} bytes are NOT 0xCC")
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    for ins in md.disasm(buf, va):
        print(f"  {ins.address:#x}  {ins.bytes.hex():<20} {ins.mnemonic} {ins.op_str}")
    return 0


def cmd_reach(a):
    img = Image(Path(a.image))
    code = img.sec(CODE_SECTION)
    lo = img.base + code["rva"]
    hi = lo + code["rsize"]
    worst = (hi - 1) - lo - JMP_LEN
    print(f"{CODE_SECTION}: {lo:#x} .. {hi:#x}  ({code['rsize']:,} B)")
    print(f"worst-case jmp rel32 displacement (last byte <- first byte, minus the 5-byte insn):")
    print(f"  {worst:+,} = {worst:#x}")
    print(f"rel32 range: {-2**31:+,} .. {2**31-1:+,}")
    print(f"headroom factor: {(2**31-1)/worst:.1f}x")
    print(f"VERDICT: a 5-byte jmp rel32 reaches from ANY byte of {CODE_SECTION} to ANY other: "
          f"{abs(worst) < 2**31 - 1}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", default=str(INSTALLED), help="PE to scan (default: the installed exe)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--min", type=int, default=MIN_USEFUL, help="smallest cave admitted to the pool")
    p.add_argument("--scan-min", type=int, default=1, help="smallest int3 run to consider at all")
    p.add_argument("--include-b", action="store_true", help="also admit tier-B (unaccounted gap) runs")
    p.add_argument("--no-rel8", action="store_true", help="skip the precise rel8 sweep (faster, weaker)")
    p.add_argument("--out", default=None, help="write the pool here instead of build/caves.json")
    p = sub.add_parser("report")
    p = sub.add_parser("show"); p.add_argument("va"); p.add_argument("n", nargs="?", type=int, default=96)
    p = sub.add_parser("near")
    p.add_argument("va"); p.add_argument("min", nargs="?", type=int, default=6)
    p.add_argument("n", nargs="?", type=int, default=30)
    p.add_argument("--pool", default=None)
    sub.add_parser("reach")
    a = ap.parse_args()
    return dict(scan=cmd_scan, report=cmd_report, show=cmd_show, reach=cmd_reach,
                near=cmd_near)[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
