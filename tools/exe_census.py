#!/usr/bin/env python3
"""
exe_census.py — census of tunable constants in eFootball.exe match gameplay code, with the
safety class that decides HOW each one may be tuned.

Why: almost every float the gameplay code uses is a RIP-relative load from a COALESCED literal
pool (section `.tls$`). A pool cell read by many unrelated sites must never be edited in place
(repoint that ONE instruction's disp32 at a private cell instead); a cell with exactly one
referrer in the whole image is genuinely private and can be tuned in place — a data-page
write, the safest class. Inline immediates are private to their instruction (code-page write).

    python tools/exe_census.py build              # -> build/exe_constant_census.json + refs .npz
    python tools/exe_census.py show <class|va>    # functions / cells / immediates of a class or fn
    python tools/exe_census.py private [prefix]   # the prize list: private floats in gameplay code
    python tools/exe_census.py cell <va>          # EVERY referrer of a data cell (whole image)
    python tools/exe_census.py summary [prefix]   # per-namespace / per-class counts
    python tools/exe_census.py ranges             # the derived gameplay address ranges
    python tools/exe_census.py verify             # hand-proven acceptance checks

How (all static, read-only — the exe is never written):
  1. FUNCTIONS  PE exception directory (.pdata RUNTIME_FUNCTION) gives exact bounds of every
     non-leaf function; chained unwind infos are folded into their root. The bytes BETWEEN
     .pdata entries (leaf functions + int3 padding) are swept too and split on int3.
  2. REFCOUNT   one capstone linear sweep of every .pdata function + every gap in every
     executable section: RIP-relative memory operand -> target. refcount[target] is the
     private-vs-shared ground truth. An independent numpy byte-pattern scan (modrm mod=00
     rm=101 + disp32) cross-checks it: any pattern hit on a cell that capstone did NOT explain
     is reported as `raw_unexplained` and vetoes `private`.
  3. CENSUS     for gameplay functions (match:: vtable methods + everything inside the address
     ranges derived from them): every RIP-relative operand on a data cell holding a plausible
     f32/f64/i32, plus — via a linear taint walk from ATTR_get / RNG / RandInt / percent-roll /
     GetParam — the inline immediates that gate or scale those values, the constant args fed
     to those helpers, and the constant GetParam row indices.

Honesty notes (static analysis on this binary has been confidently wrong before):
  * refcount counts DIRECT RIP-relative operands only. A cell reached through `lea base` +
    index, through a pointer stored in data, or from Denuvo-virtualised code is invisible.
    `lea_near` / `ptr_refs` flag the first two; nothing can flag the third.
  * the taint walk is LINEAR (address order), not CFG-aware: a heuristic, not a proof.
  * class attribution is exact only for vtable methods; `~Class` means "nearest vtable method".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from exe_map import EXE, MAP, Image  # noqa: E402  (reuse the PE mapper; do not duplicate)

BUILD = REPO / "build"


def paths(tag=None):
    """stock census = build/exe_constant_census.json; an --overlay build gets a .<tag> suffix."""
    sfx = f".{tag}" if tag else ""
    return (BUILD / f"exe_constant_census{sfx}.json", BUILD / f"exe_census_refs{sfx}.npz",
            BUILD / f"exe_constant_census_summary{sfx}.txt")


# helper functions whose results / arguments define "probability & threshold knobs"
HELPERS = {   # va: (kind, description, constant-arg register family, RESULT register family)
    0x143EA8CB0: ("attr", "ATTR_get(player, idx) -> ability byte", "rdx", "rax"),
    0x1442DD650: ("attr", "inner ability getter (ctx, ?, idx) -> al; ATTR_get is a thin wrapper of this "
                          "[stock disasm: mov ebx,r8d ... mov edx,ebx; jmp 0x1441172b0]", "r8", "rax"),
    0x144345D90: ("rng", "RNG(state*, slot) -> raw LCG int", None, "rax"),
    0x144345E00: ("randint", "RandInt(state*, max, slot) -> [0,max)", "rdx", "rax"),
    0x143EAFD30: ("pct_roll", "PercentRoll(player, pct) -> (rand%100) < pct", "rdx", None),
    0x143EA9260: ("randint", "RandInt wrapper (player ctx, max) [doc-derived]", "rdx", "rax"),
    0x144345EB0: ("gauss", "Gaussian(state*, sigma xmm1, mean xmm2) -> int 0..99 in eax (Box-Muller; "
                           "stock disasm: cvttss2si eax,xmm1; cmp eax,0x63)", None, "rax"),
    0x143ED71D0: ("accuracy", "ability -> 0..1 accuracy factor in xmm0 (kick error model)", None, "xmm0"),
    0x1442E48F0: ("level", "AiLevelUnit::GetParam(unit, row) -> float (table 0x146c06f40)", "rdx", "xmm0"),
    0x1442E4C00: ("level_flag", "AiLevelUnit::IsEnabled(unit, row) = |GetParam| > eps", "rdx", None),
}
GETPARAM = {0x1442E48F0, 0x1442E4C00}
LEVEL_TABLE = 0x146C06F40
LEVEL_ROWS = 44

BUCKET = 0x4000           # range derivation granularity
MIN_DENSITY = 25          # match:: vtable methods per MB for a run to count as match code
GAP_CLOSE = 0x100000      # close holes up to 1 MB between match-dominant buckets
GAP_MAX_OTHER = 24        # ... if they hold at most this many non-match vtable methods

VOLATILE = ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11", "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5")
CMP_MN = {"cmp", "test", "comiss", "ucomiss", "comisd", "ucomisd", "bt", "ptest", "vcomiss", "vucomiss"}
WRITE1_MN = {"inc", "dec", "neg", "not", "pop"}


# ----------------------------------------------------------------------------------------
# PE helpers
# ----------------------------------------------------------------------------------------

def _hex(s):
    return bytes.fromhex(s.replace(" ", ""))


class PatchedImage(Image):
    """Image with live_patch.py specs overlaid IN MEMORY ONLY (copy-on-write mapping of a file
    opened read-only; the exe on disk is never touched). Lets the census describe the
    *installed* build, where repointed disp32s change which cells are shared."""

    def __init__(self, path, overlays=()):
        super().__init__(Path(path))
        self.overlay_log = []
        if not overlays:
            return
        import mmap
        self.m.close()
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_COPY)
        for spec in overlays:
            j = json.loads(Path(spec).read_text(encoding="utf-8"))
            for pt in (j.get("patches") if isinstance(j, dict) else j) or []:
                rva = int(pt["va"], 16) - self.base if "va" in pt else int(pt["module_offset"], 16)
                exp, new = _hex(pt["expect"]), _hex(pt["patch"])
                off = self.rva2off(rva)
                cur = bytes(self.m[off:off + len(exp)]) if off is not None else None
                if cur == exp:
                    self.m[off:off + len(new)] = new
                    st = "applied"
                elif cur == new:
                    st = "already"
                else:
                    st = "MISMATCH-skipped"
                self.overlay_log.append(dict(spec=Path(spec).name, name=pt.get("name", ""),
                                             va=self.base + rva, status=st))


def data_directory(img: Image, idx: int):
    d = img.m[:0x1000]
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    return struct.unpack_from("<II", d, pe + 24 + 112 + 8 * idx)


def section_flags(img: Image):
    d = img.m[:0x1000]
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    out = {}
    for i in range(nsec):
        s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
        ch = struct.unpack_from("<I", s, 36)[0]
        out[s[:8].rstrip(b"\0").decode()] = dict(write=bool(ch & 0x80000000), exec=bool(ch & 0x20000000),
                                                   code=bool(ch & 0x20))
    return out


def load_pdata(img: Image):
    """-> numpy (n,3) [begin, end, root_begin] rvas, chained unwind infos folded into the root."""
    import numpy as np
    rva, size = data_directory(img, 3)
    if not rva or not size:
        return None
    off = img.rva2off(rva)
    a = np.frombuffer(img.m[off:off + size - size % 12], dtype="<u4").reshape(-1, 3).copy()
    a = a[a[:, 0] != 0]
    a = a[np.argsort(a[:, 0], kind="stable")]
    root = a[:, 0].copy()
    begin_idx = {int(b): i for i, b in enumerate(a[:, 0])}
    for i in range(len(a)):
        uw = int(a[i, 2])
        hops = 0
        b = int(a[i, 0])
        while hops < 8:
            hdr = img.read(uw & ~1, 4) if not (uw & 1) else b""
            if uw & 1:                                  # some linkers point at another RUNTIME_FUNCTION
                pb = img.u32(uw & ~1)
                j = begin_idx.get(pb)
                if j is None:
                    break
                b, uw = pb, int(a[j, 2]); hops += 1
                continue
            flags = hdr[0] >> 3
            if not (flags & 4):
                break
            cnt = hdr[2]
            chain = (uw + 4 + ((cnt + 1) & ~1) * 2)
            pb, pe_, puw = struct.unpack("<III", img.read(chain, 12))
            if pb == 0 or pb == b:
                break
            b, uw = pb, puw
            hops += 1
        root[i] = b
    out = np.empty((len(a), 3), dtype=np.uint32)
    out[:, 0], out[:, 1], out[:, 2] = a[:, 0], a[:, 1], root
    return out


# ----------------------------------------------------------------------------------------
# RTTI attribution + gameplay ranges
# ----------------------------------------------------------------------------------------

def load_methods():
    """method rva -> dict(cls primary owner, vf index, owners n, match bool)."""
    if not MAP.exists():
        sys.exit("run first: python tools/exe_map.py build")
    mp = json.loads(MAP.read_text(encoding="utf-8"))
    owners = defaultdict(list)
    for c, lst in mp["classes"].items():
        for v in lst:
            for i, m in enumerate(v["methods"]):
                owners[m].append((len(v["bases"]), c, i))
    meth = {}
    for m, lst in owners.items():
        lst.sort()                                   # fewest bases = most-base class = definer
        names = sorted({c for _, c, _ in lst})
        is_match = any("match::" in c for c in names) and len(names) < 40
        prim = lst[0]
        if is_match and "match::" not in prim[1]:
            prim = next(x for x in lst if "match::" in x[1])
        meth[m] = dict(cls=prim[1], vf=prim[2], owners=len(names), match=is_match,
                       stub=len(names) >= 40)
    return mp, meth


def derive_ranges(meth):
    """64 KB buckets that are match-dominant, holes closed when they hold (almost) no foreign
    vtable methods. Returns [(lo_rva, hi_rva, n_match_methods)]."""
    nm, no = Counter(), Counter()
    for m, d in meth.items():
        if d["stub"]:
            continue
        (nm if d["match"] else no)[m // BUCKET] += 1
    dom = sorted(k for k in nm if nm[k] >= no[k])
    runs = []
    for k in dom:
        if runs:
            lo, hi = runs[-1]
            gap_other = sum(no[j] for j in range(hi + 1, k))
            if (k - hi - 1) * BUCKET <= GAP_CLOSE and gap_other <= GAP_MAX_OTHER:
                runs[-1] = (lo, k)
                continue
        runs.append((k, k))
    out = []
    for lo, hi in runs:
        n = sum(nm[j] for j in range(lo, hi + 1))
        mb = (hi + 1 - lo) * BUCKET / 1e6
        if n >= 8 and n / mb >= MIN_DENSITY:         # ignore stray islands elsewhere in the image
            out.append((lo * BUCKET, (hi + 1) * BUCKET, n))
    return out


def in_ranges(rva, ranges):
    return any(lo <= rva < hi for lo, hi, _ in ranges)


# ----------------------------------------------------------------------------------------
# Pass 1: global sweep (multiprocess, capstone lite)
# ----------------------------------------------------------------------------------------

def _rip_target(a, sz, ops):
    i = ops.find("[rip")
    if i < 0:
        return None
    j = ops.find("]", i)
    inner = ops[i + 4:j].strip()
    if not inner:
        return a + sz
    v = int(inner[1:].strip(), 0)
    return a + sz + v if inner[0] == "+" else a + sz - v


def _ref_kind(mn, ops):
    """0 read, 1 lea, 2 write (incl. read-modify-write), 3 indirect call/jmp."""
    if mn == "lea":
        return 1
    if mn in ("call", "jmp"):
        return 3
    c = ops.find(",")
    if c < 0:
        return 2 if (mn in WRITE1_MN or mn.startswith("set")) else 0
    if "rip" in ops[:c] and mn not in CMP_MN:
        return 2
    return 0


def _table_runs(np, buf, s, e):
    """MSVC keeps switch jump tables (4-aligned u32 RVAs into the same function) INSIDE the
    .pdata range. Return [(off_lo, off_hi)] runs of >= 3 such entries so the linear sweep can
    step over them instead of decoding them as junk."""
    a0 = (-s) % 4
    n4 = (len(buf) - a0) // 4
    if n4 < 3:
        return []
    v = np.frombuffer(buf, dtype="<u4", count=n4, offset=a0)
    ok = (v >= max(0x1000, s - 0x8000)) & (v < e + 0x8000)
    if int(ok.sum()) < 3:
        return []
    idx = np.flatnonzero(ok).tolist()
    runs, start, prev = [], idx[0], idx[0]
    for i in idx[1:] + [-10]:
        if i != prev + 1:
            if prev - start + 1 >= 3:
                runs.append((a0 + 4 * start, a0 + 4 * (prev + 1)))
            start = i
        prev = i
    return runs


_PTR_W = (("xmmword ptr", 16), ("ymmword ptr", 32), ("zmmword ptr", 64), ("xword ptr", 10), ("qword ptr", 8),
          ("dword ptr", 4), ("word ptr", 2), ("byte ptr", 1))


def access_width(mn: str, ops: str) -> int:
    """Bytes the instruction really touches at its memory operand. Typed by the MNEMONIC first:
    this capstone build prints `comisd xmm0, xmmword ptr [...]` although comisd reads 8 bytes
    (that mis-typed a f64 threshold as a 16-byte vector). 0 = unknown extent (lea)."""
    if mn == "lea":
        return 0
    m = mn[1:] if mn[0] == "v" else mn
    if not m.startswith("cvtsi2"):
        if m.startswith(("cvtsd2", "cvttsd2")) or m in ("comisd", "ucomisd"):
            return 8
        if m.startswith(("cvtss2", "cvttss2")) or m in ("comiss", "ucomiss"):
            return 4
        if "xmm" in ops:
            if m.endswith("sd"):
                return 8
            if m.endswith("ss"):
                return 4
    for k, w in _PTR_W:
        if k in ops:
            return w
    return 8


def _imgbase_disp(ops: str):
    """`[reg + idx*s + 0x6b4ea50]` with NO rip: MSVC's image-base-relative table addressing
    (`lea reg,[rip -> ImageBase]` earlier in the function). -> (disp, scale) or None."""
    i = ops.find("[")
    j = ops.find("]", i)
    if i < 0 or j < 0:
        return None
    inner = ops[i + 1:j]
    k = inner.rfind("+ 0x")
    if k <= 0 or len(inner) - k < 10:                # disp >= 0x100000
        return None
    try:
        disp = int(inner[k + 2:], 16)
    except ValueError:
        return None
    st = inner.find("*")
    scale = int(inner[st + 1]) if st > 0 and inner[st + 1].isdigit() else 1
    return disp, scale


def _short_float_imm(v: int):
    """imm32 of `mov dword ptr [mem], imm32` that is really a float literal -> value or None."""
    if v < 0x10000 or v > 0xFFFFFFFF:
        return None
    ex = (v >> 23) & 0xFF
    if ex < 0x70 or ex > 0x96:                       # ~1.5e-5 .. 1.6e7
        return None
    f = struct.unpack("<f", struct.pack("<I", v))[0]
    for p_ in range(1, 7):
        if struct.pack("<f", float(f"{f:.{p_}g}")) == struct.pack("<f", f):
            return float(f"{f:.{p_}g}")
    return None


def _decode_chunk(md, img, buf, s, e, gap, keep, tables, helper_vas, exec_ranges):
    """one linear decode of [s,e) stepping over `tables` (chunk-relative [lo,hi) byte ranges)."""
    base = img.base
    n = len(buf)
    R = dict(sites=[], targets=[], kinds=[], dpos=[], widths=[], leafs=[], text=[], calls=[], esites=[],
             etargets=[], ib=[], ibtext=[], iblea=[], fimm=[], code_tbl=set(), nins=0, desync=0)
    segs, p0 = [], 0
    for lo_, hi_ in tables:
        if lo_ > p0:
            segs.append((p0, lo_))
        p0 = max(p0, hi_)
    if p0 < n:
        segs.append((p0, n))
    seg_start = None
    for pos, stop in segs:
        while pos < stop:
            if gap and buf[pos] in (0xCC, 0x00):
                pos += 1
                continue
            last = pos
            hit_int3 = False
            for a, sz, mn, ops in md.disasm_lite(buf[pos:stop] if (pos or stop < n) else buf, base + s + pos):
                if mn == "int3":
                    last = a - base - s + sz
                    if gap:
                        hit_int3 = True
                        break
                    continue
                R["nins"] += 1
                if gap and seg_start is None:
                    seg_start = a - base
                last = a - base - s + sz
                if "rip" in ops:
                    t = _rip_target(a, sz, ops)
                    if t == base and mn == "lea":
                        R["iblea"].append(a - base)      # lea reg,[rip -> ImageBase]
                    elif t is not None and base < t < base + 0xFFFFFFFF:
                        io = a - base - s
                        d = t - a - sz
                        p = buf.find(struct.pack("<i", d), io, io + sz)
                        k = _ref_kind(mn, ops)
                        R["sites"].append(a - base); R["targets"].append(t - base); R["kinds"].append(k)
                        R["dpos"].append(s + p if p >= 0 else 0)
                        R["widths"].append(access_width(mn, ops))
                        if keep:
                            R["text"].append((a - base, sz, mn, ops, t - base, k))
                elif (mn == "call" or mn == "jmp") and ops.startswith("0x"):
                    tv = int(ops, 16)
                    if (mn == "call" or not (s <= tv - base < e)) and base < tv < base + 0xFFFFFFFF:
                        R["esites"].append(a - base); R["etargets"].append(tv - base)
                    if keep and tv in helper_vas:
                        R["calls"].append((a - base, tv))
                elif "+ 0x" in ops and "[" in ops:
                    dd = _imgbase_disp(ops)
                    if dd is not None:
                        disp, scale = dd
                        w = access_width(mn, ops)
                        if any(lo_ <= disp < hi_ for lo_, hi_ in exec_ranges):
                            R["code_tbl"].add((disp, w))     # switch table inside the code (this chunk or a sibling)
                        elif img.rva2off(disp) is not None:
                            R["ib"].append((a - base, disp, w, scale, 1 if mn == "lea" else 0))
                            if keep:
                                R["ibtext"].append((a - base, sz, mn, ops, disp, scale))
                if keep and mn == "mov" and ops.startswith("dword ptr [") and ", 0x" in ops:
                    iv = int(ops[ops.rfind(", 0x") + 2:], 16)
                    fv = _short_float_imm(iv)
                    if fv is not None:
                        R["fimm"].append((a - base, a - base + sz - 4, fv, f"{mn} {ops}"))
            if gap and (hit_int3 or last >= stop or last == pos):
                if seg_start is not None:
                    R["leafs"].append((seg_start, s + last, keep))
                    seg_start = None
            if last == pos:                      # undecodable byte: resync
                R["desync"] += 1
                pos += 1
            else:
                pos = last
    if gap and seg_start is not None:
        R["leafs"].append((seg_start, e, keep))
    return R


def _code_table_ranges(buf, s, e, gap, runs, code_tbl):
    """skip-ranges for the switch tables the DISPATCH CODE itself names (`[imgbase + idx*k + RVA]`
    with RVA inside this chunk): any alignment, u32 RVA tables AND byte/word index tables.
    A u32 table extends while its entries are RVAs of this function; a byte/word index table has
    no self-describing end, so it extends to the next table / the next int3 (gaps) / chunk end
    (MSVC emits switch tables after the function's last instruction). Over-skipping can only
    LOSE references, and every lost reference is caught by the raw-pattern veto."""
    n = len(buf)
    starts = sorted({o for o, _ in code_tbl} | {lo for lo, _ in runs})
    out = list(runs)
    for o, w in sorted(code_tbl):
        if any(lo <= o < hi for lo, hi in runs):
            continue
        if w == 4:
            q = o
            while q + 4 <= n:
                v = struct.unpack_from("<I", buf, q)[0]
                if not (max(0x1000, s - 0x8000) <= v < e + 0x8000):
                    break
                q += 4
            if q > o:
                out.append((o, q))
            continue
        nxt = next((x for x in starts if x > o), n)
        if gap:
            c = buf.find(b"\xCC", o)
            if 0 <= c < nxt:
                nxt = c
        out.append((o, nxt))
    out.sort()
    merged = []
    for lo, hi in out:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


def _sweep_task(arg):
    exe, overlays, groups, helper_vas = arg
    import capstone
    import numpy as np
    img = PatchedImage(exe, overlays)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    ex = [x for x in img.secs if x["exec"] and x["rsize"]]
    exec_ranges = [(x["va"], x["va"] + x["vsize"]) for x in ex]
    acc = dict(sites=[], targets=[], kinds=[], dpos=[], widths=[], leafs=[], text=[], calls=[], esites=[],
               etargets=[], ib=[], ibtext=[], iblea=[], fimm=[])
    nins = desync = ntables = ncodetbl = 0
    chunk_q = []                                       # (start rva, resyncs, code tables) of kept chunks
    for group in groups:                               # all .pdata chunks of ONE function (or one gap)
        st = []
        named = set()
        for s, e, gap, keep in group:
            off = img.rva2off(s)
            if off is None:
                continue
            buf = bytes(img.m[off:off + (e - s)])
            runs = _table_runs(np, buf, s, e) if (len(buf) >= 24 and not gap) else []
            R = _decode_chunk(md, img, buf, s, e, gap, keep, runs, helper_vas, exec_ranges)
            named |= R["code_tbl"]
            st.append([s, e, gap, keep, buf, runs, runs, R])
        for _round in range(3):                        # tables named by the dispatch code -> re-decode
            again = False
            for c_ in st:
                s, e, gap, keep, buf, runs, tables, R = c_
                mine = {(d - s, w) for d, w in named if s <= d < e}
                if not mine:
                    continue
                t2 = _code_table_ranges(buf, s, e, gap, runs, mine)
                if t2 != tables:
                    c_[6] = t2
                    c_[7] = _decode_chunk(md, img, buf, s, e, gap, keep, t2, helper_vas, exec_ranges)
                    new = c_[7]["code_tbl"] - named
                    if new:
                        named |= new
                        again = True
            if not again:
                break
        for s, e, gap, keep, buf, runs, tables, R in st:
            ntables += len(tables)
            nmine = sum(1 for d, _ in named if s <= d < e)
            ncodetbl += nmine
            for k_ in acc:
                acc[k_] += R[k_]
            nins += R["nins"]; desync += R["desync"]
            if keep and (R["desync"] or nmine):
                chunk_q.append((s, R["desync"], nmine))
    return (np.array(acc["sites"], dtype=np.uint32), np.array(acc["targets"], dtype=np.uint32),
            np.array(acc["kinds"], dtype=np.uint8), np.array(acc["dpos"], dtype=np.uint32),
            acc["leafs"], acc["text"], acc["calls"], nins, desync, ntables,
            np.array(acc["esites"], dtype=np.uint32), np.array(acc["etargets"], dtype=np.uint32),
            np.array(acc["widths"], dtype=np.uint8),
            np.array(acc["ib"], dtype=np.int64).reshape(-1, 5), acc["ibtext"],
            np.array(acc["iblea"], dtype=np.uint32), acc["fimm"], chunk_q, ncodetbl)


def _split(groups, nparts):
    """groups = lists of (s, e, gap, keep) that must stay together (the chunks of one function)."""
    parts = [[] for _ in range(nparts)]
    load = [0] * nparts
    import heapq
    heap = [(0, i) for i in range(nparts)]
    for g in sorted(groups, key=lambda g: -sum(t[1] - t[0] for t in g)):
        l, i = heapq.heappop(heap)
        parts[i].append(g)
        heapq.heappush(heap, (l + sum(t[1] - t[0] for t in g), i))
    return [sorted(p_, key=lambda g: g[0][0]) for p_ in parts if p_]


# ----------------------------------------------------------------------------------------
# Pass 3: linear taint / constant walk (capstone detail) on functions that call the helpers
# ----------------------------------------------------------------------------------------

_FAM = {}


def _fam_of(name: str):
    f = _FAM.get(name)
    if f is not None:
        return f
    n = name
    if n.startswith(("xmm", "ymm", "zmm")):
        f = "xmm" + n[3:]
    elif n in ("rip", "eip", "eflags", "rflags", "rsp", "esp", "sp", "spl"):
        f = "" if n not in ("rsp", "esp", "sp", "spl") else "rsp"
    elif n[0] == "r" and n[1:].rstrip("dwb").isdigit():
        f = "r" + n[1:].rstrip("dwb")
    else:
        core = n.lstrip("re")
        table = {"ax": "rax", "al": "rax", "ah": "rax", "bx": "rbx", "bl": "rbx", "bh": "rbx",
                 "cx": "rcx", "cl": "rcx", "ch": "rcx", "dx": "rdx", "dl": "rdx", "dh": "rdx",
                 "si": "rsi", "sil": "rsi", "di": "rdi", "dil": "rdi", "bp": "rbp", "bpl": "rbp"}
        f = table.get(core, table.get(n, ""))
    _FAM[name] = f
    return f


def _taint_task(arg):
    exe, overlays, funcs = arg
    import capstone
    from capstone import x86 as X
    img = PatchedImage(exe, overlays)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    base = img.base
    results = {}

    def fam(ins, rid):
        return _fam_of(ins.reg_name(rid)) if rid else ""

    for root, chunks in funcs:
        imms, helper_calls, cell_taint = [], [], {}
        for (s, e) in chunks:
            inss = list(md.disasm(img.read(s, e - s), base + s))
            labels = set()
            for ins in inss:
                if ins.mnemonic[0] == "j" and ins.operands and ins.operands[0].type == X.X86_OP_IMM:
                    labels.add(ins.operands[0].imm)
            taint, const, slots = {}, {}, {}
            last_cmp = None
            pending_eq = None
            for ins in inss:
                a = ins.address
                mn = ins.mnemonic
                ops = ins.operands
                if a in labels:
                    const.clear()
                    pending_eq = None
                if pending_eq:
                    const[pending_eq[0]] = pending_eq[1]
                    pending_eq = None
                # ---- calls / tail jumps to helpers
                if mn == "call" or (mn == "jmp" and ops and ops[0].type == X.X86_OP_IMM and ops[0].imm in HELPERS):
                    tgt = ops[0].imm if ops and ops[0].type == X.X86_OP_IMM else None
                    tag = None
                    if tgt in HELPERS:
                        kind, _, argreg, _res = HELPERS[tgt]
                        c = const.get(argreg) if argreg else None
                        rec = dict(va=a, helper=tgt, kind=kind)
                        if c:
                            rec.update(arg=c[0], arg_site=c[1], arg_how=c[2], arg_text=c[3])
                        if kind == "randint" and tgt == 0x144345E00 and const.get("r8"):
                            rec["slot"] = const["r8"][0]
                        helper_calls.append(rec)
                        tag = (kind, a, c[0] if c else None)
                    for r in VOLATILE:
                        taint.pop(r, None)
                        const.pop(r, None)
                    if tag and HELPERS[tgt][3]:
                        taint[HELPERS[tgt][3]] = tag
                    last_cmp = None
                    continue
                if mn in ("jmp", "ret"):
                    const.clear()
                    last_cmp = None
                    continue
                if mn[0] == "j":
                    if mn == "jne" and last_cmp and last_cmp[3] == a:
                        pending_eq = (last_cmp[0], (last_cmp[1], last_cmp[2], "cmp-eq", last_cmp[4]))
                    last_cmp = None
                    continue
                # ---- operand survey
                regs_r, regs_w = (), ()
                try:
                    regs_r, regs_w = ins.regs_access()
                except capstone.CsError:
                    pass
                rf = [f for f in (fam(ins, r) for r in regs_r) if f and f != "rsp"]
                wf = [f for f in (fam(ins, r) for r in regs_w) if f and f != "rsp"]
                imm = None
                op_regs, slot_r, slot_w, ripmem = [], None, None, False
                for i, op in enumerate(ops):
                    if op.type == X.X86_OP_IMM:
                        imm = op.imm
                    elif op.type == X.X86_OP_REG:
                        op_regs.append(fam(ins, op.reg))
                    elif op.type == X.X86_OP_MEM:
                        b = fam(ins, op.mem.base)
                        if op.mem.base == X.X86_REG_RIP:
                            ripmem = True
                        elif b in ("rsp", "rbp") and op.mem.index == 0:
                            key = (b, op.mem.disp)
                            if i == 0 and mn not in CMP_MN:
                                slot_w = key
                                if mn not in ("mov", "movss", "movsd", "movaps", "movups", "movd", "movq"):
                                    slot_r = key
                            else:
                                slot_r = key
                src_tag = None
                same = len(ops) == 2 and ops[0].type == X.X86_OP_REG and ops[1].type == X.X86_OP_REG \
                    and ops[0].reg == ops[1].reg and mn in ("xor", "sub", "xorps", "xorpd", "pxor")
                if not same:
                    for f in rf:
                        if f in taint:
                            src_tag = taint[f]
                            break
                    if src_tag is None and slot_r is not None:
                        src_tag = slots.get(slot_r)
                # ---- record: tainted value against an inline immediate
                txt = f"{mn} {ins.op_str}"
                role = {"cmp": "gate", "test": "gate", "imul": "scale", "shl": "scale", "shr": "scale",
                        "sar": "scale", "add": "offset", "sub": "offset", "and": "mask", "or": "mask",
                        "xor": "mask", "div": "scale", "idiv": "scale", "mul": "scale"}.get(mn)
                if role and src_tag is not None:
                    explicit_tainted = any(f in taint for f in op_regs) or (slot_r is not None and slot_r in slots) \
                        or mn in ("div", "idiv", "mul")
                    if imm is not None and explicit_tainted and len(ops) >= 2:
                        imms.append(dict(va=a, text=txt, imm=imm, imm_size=ins.imm_size,
                                         imm_va=a + ins.imm_offset, role=role,
                                         src=src_tag[0], src_call=src_tag[1], src_arg=src_tag[2]))
                    elif imm is None and explicit_tainted:
                        for f in op_regs:
                            if f not in taint and f in const:
                                c = const[f]
                                imms.append(dict(va=c[1], text=c[3], imm=c[0], role=role, via=a, via_text=txt,
                                                 how=c[2], src=src_tag[0], src_call=src_tag[1], src_arg=src_tag[2]))
                if ripmem and src_tag is not None:
                    cell_taint[a] = (src_tag[0], src_tag[1], src_tag[2])
                # ---- constants
                newconst = None
                if len(ops) == 2 and ops[0].type == X.X86_OP_REG:
                    d = fam(ins, ops[0].reg)
                    if mn == "mov" and ops[1].type == X.X86_OP_IMM:
                        newconst = (d, (ops[1].imm, a, "mov-imm", txt))
                    elif same and mn in ("xor", "sub"):
                        newconst = (d, (0, a, "xor-zero", txt))
                    elif mn in ("mov", "movsxd", "movzx") and ops[1].type == X.X86_OP_REG:
                        c = const.get(fam(ins, ops[1].reg))
                        if c:
                            newconst = (d, c)
                    elif mn == "lea" and ops[1].type == X.X86_OP_MEM and ops[1].mem.index == 0 \
                            and ops[1].mem.base not in (0, X.X86_REG_RIP):
                        c = const.get(fam(ins, ops[1].mem.base))
                        if c:
                            v = (c[0] + ops[1].mem.disp) & (0xFFFFFFFF if ops[0].size == 4 else 0xFFFFFFFFFFFFFFFF)
                            newconst = (d, (v, a, "lea-const", f"{txt}  ; base const from {c[1]:#x} {c[3]}"))
                if mn == "cmp" and len(ops) == 2 and ops[0].type == X.X86_OP_REG and ops[1].type == X.X86_OP_IMM:
                    last_cmp = (fam(ins, ops[0].reg), ops[1].imm, a, a + ins.size, txt)
                elif mn not in CMP_MN:
                    last_cmp = None
                # ---- propagate
                cond = mn.startswith("cmov")
                for f in wf:
                    if src_tag is not None:
                        taint[f] = src_tag
                    elif not cond:
                        taint.pop(f, None)
                    const.pop(f, None)
                if newconst:
                    const[newconst[0]] = newconst[1]
                if slot_w is not None:
                    if src_tag is not None:
                        slots[slot_w] = src_tag
                    else:
                        slots.pop(slot_w, None)
        results[root] = (imms, helper_calls, cell_taint)
    return results


# ----------------------------------------------------------------------------------------
# value decoding
# ----------------------------------------------------------------------------------------

F32_MN = ("ss",)


def _short_f32(v):
    import numpy as np
    for p in range(1, 10):
        s = f"{v:.{p}g}"
        if np.float32(float(s)) == np.float32(v):
            return float(s)
    return float(v)


KIND_WIDTH = dict(f32=4, i32=4, f64=8, i8=1, i16=2, vec32=16, vec64=16, vecmask=16, veci32=16)


def _plaus32(v):
    import math
    return math.isfinite(v) and 1e-6 <= abs(v) <= 1e7


def _printable(c):
    return 0x20 <= c <= 0x7E or c in (9, 10, 13)


def text_extent(img: Image, t: int, w: int):
    """-> (lo, hi, 'ascii'|'utf16') when the bytes [t,t+w) sit inside a string literal, else None.
    MSVC copies short strings with movsd/movups/mov chunks, which otherwise show up as absurd
    f64 / i32 / vec 'constants' - and other code reads the same string through `lea`."""
    PAD = 256
    raw = img.read(t - PAD, PAD * 2 + w)
    c0, c1 = PAD, PAD + w
    # ASCII: the cell's leading bytes are printable (a terminator may fall inside the cell)
    k = c0
    while k < c1 and _printable(raw[k]):
        k += 1
    if k > c0 and (k == c1 or raw[k] == 0):
        lo = c0
        while lo > 0 and _printable(raw[lo - 1]):
            lo -= 1
        hi = k
        while hi < len(raw) and _printable(raw[hi]):
            hi += 1
        outside = (c0 - lo) + max(0, hi - c1)
        if hi - lo >= 12 and outside >= 8:
            return t - PAD + lo, t - PAD + hi, "ascii"
    # UTF-16LE: (printable, 0) pairs; try both phases
    for ph in (0, 1):
        q = c0 - ((c0 - ph) % 2)
        if not (_printable(raw[q]) and raw[q + 1] == 0):
            continue
        lo = q
        while lo >= 2 and _printable(raw[lo - 2]) and raw[lo - 1] == 0:
            lo -= 2
        hi = q
        while hi + 1 < len(raw) and _printable(raw[hi]) and raw[hi + 1] == 0:
            hi += 2
        if (hi - lo) // 2 >= 6 and (hi >= c1 or raw[hi:hi + 2] == b"\0\0"):
            return t - PAD + lo, t - PAD + hi, "utf16"
    return None


def decode_table(img: Image, t: int, limit: int, elem: str = None):
    """a `lea` / image-base table base -> ('table'|'itable', preview, est_len) or None. A float table
    may START with 0.0 (CPU level table A = [0,32,28,...]); `limit` = bytes to the next referenced
    target, the only (weak) length evidence there is."""
    n = max(1, min(64, limit // 4 if limit else 8))
    raw = img.read(t, 4 * n)
    fs = struct.unpack(f"<{n}f", raw)
    us = struct.unpack(f"<{n}i", raw)
    head = min(n, 8)
    fl = sum(1 for v in fs[:head] if v != 0 and _plaus32(v))
    fz = sum(1 for v, u in zip(fs[:head], us[:head]) if u == 0 or (v != 0 and _plaus32(v)))
    if elem != "int" and fz == head and fl >= max(1, min(2, head)):
        m = 0
        while m < n and (us[m] == 0 or _plaus32(fs[m])):
            m += 1
        return "table", [_short_f32(x) for x in fs[:min(m, 16)]], m
    il = sum(1 for u in us[:head] if u != 0 and abs(u) <= 100000)
    iz = sum(1 for u in us[:head] if abs(u) <= 100000)
    if elem != "float" and iz == head and il >= max(1, min(3, head)):
        m = 0
        while m < n and abs(us[m]) <= 100000:
            m += 1
        return "itable", list(us[:min(m, 16)]), m
    if elem != "int" and fs[0] != 0 and _plaus32(fs[0]):   # mixed struct array that starts with a float
        return "table", [_short_f32(f_) if (u_ == 0 or _plaus32(f_)) else u_ for f_, u_ in zip(fs[:8], us[:8])], 1
    return None


def decode_cell(img: Image, t: int, mn: str, ops: str, kind: int, limit: int = 0):
    """-> (kind, value) or None. Typed by the INSTRUCTION (mnemonic first, then the operand size
    capstone prints), never by guessing from the bytes."""
    import math
    if img.rva2off(t) is None:
        return None
    if kind == 1:                                     # lea: a table base
        dt = decode_table(img, t, limit)
        return (dt[0], dt[1]) if dt else None
    if kind == 3:
        return None
    w = access_width(mn, ops)
    m = mn[1:] if mn[0] == "v" else mn
    sse = "xmm" in ops or "ymm" in ops
    if w >= 16:
        raw = img.read(t, 16)
        fs = struct.unpack("<4f", raw)
        us = struct.unpack("<4I", raw)
        si = struct.unpack("<4i", raw)
        if all(u in (0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0) for u in us):
            return "vecmask", [f"{u:#010x}" for u in us]
        if m.endswith("pd") or m in ("movapd", "movupd"):
            ds = struct.unpack("<2d", raw)
            if all(math.isfinite(d) and (d == 0 or 1e-9 <= abs(d) <= 1e12) for d in ds):
                return "vec64", [float(f"{d:.17g}") for d in ds]
            return None
        if all(math.isfinite(f) and (f == 0 or 1e-9 <= abs(f) <= 1e10) for f in fs):
            return "vec32", [_short_f32(f) for f in fs]
        if all(abs(x) <= 100000 for x in si) and any(si):      # integer SIMD: ability-index tuples, ladders
            return "veci32", list(si)
        return None
    if w == 8:
        if sse and (m.endswith("sd") or m.startswith(("cvtsd2", "cvttsd2")) or m in ("comisd", "ucomisd", "movddup")):
            v = struct.unpack("<d", img.read(t, 8))[0]
            if math.isfinite(v) and (v == 0 or 1e-9 <= abs(v) <= 1e12):     # else: bytes of a string / pointer
                return "f64", float(f"{v:.17g}")
        return None
    if w == 4:
        if sse or m.endswith("ss"):
            v = struct.unpack("<f", img.read(t, 4))[0]
            if m in ("movd", "cvtsi2ss", "cvtsi2sd", "cvtdq2ps", "pinsrd") or not math.isfinite(v):
                if m == "movd" and math.isfinite(v) and (v == 0 or 1e-6 <= abs(v) <= 1e7):
                    return "f32", _short_f32(v)
                return "i32", struct.unpack("<i", img.read(t, 4))[0]
            return "f32", _short_f32(v)
        return "i32", struct.unpack("<i", img.read(t, 4))[0]
    if w in (1, 2) and (m.startswith(("movzx", "movsx")) or m in ("cmp", "mov", "test")):
        return ("i8", struct.unpack("<b", img.read(t, 1))[0]) if w == 1 else ("i16", struct.unpack("<h", img.read(t, 2))[0])
    return None


def classify_base(img: Image, b: int, base: int, image_size: int):
    """What object starts at data address `b` (a lea / stored-pointer target), and where does it END?
    -> (class, end_rva or None). Only a PROVEN end may clear a cell that follows the base."""
    raw = img.read(b, 0x400)
    # pointer run (vtable / pointer array): qwords that are VAs inside the image
    q = 0
    while q + 8 <= len(raw):
        v = struct.unpack_from("<Q", raw, q)[0]
        if not (base + 0x1000 <= v < base + image_size):
            break
        q += 8
    if q >= 8:
        return "pointers", (b + q if q < len(raw) else None)
    k = 0
    while k < len(raw) and _printable(raw[k]):
        k += 1
    if k >= 4:
        if k == len(raw):
            return "string?", None                     # unterminated within 0x400: extent unknown
        if raw[k] == 0:
            return "string", b + k + 1
    k = 0
    while k + 1 < len(raw) and _printable(raw[k]) and raw[k + 1] == 0:
        k += 2
    if k >= 8:
        return ("wstring", b + k + 2) if raw[k:k + 2] == b"\0\0" else ("string?", None)
    return "array?", None


def role_of(mn: str, kind: int):
    if kind == 1:
        return "table"
    if kind == 2:
        return "write"
    if mn in CMP_MN or mn.startswith(("cmp", "pcmp")):
        return "compare"
    if mn.startswith(("min", "max")):
        return "clamp"
    if mn.startswith(("mov", "cvt", "lea", "push", "pshuf", "shuf", "unpck", "vmov", "vbroadcast")):
        return "load"
    return "arith"


# ----------------------------------------------------------------------------------------
# build
# ----------------------------------------------------------------------------------------

def tool_sha1():
    return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()


NEAR_WINDOW = 0x100        # unbounded lea / pointer base this close before a cell -> unproven
BASE_WINDOW = 0x400        # how far back lea / pointer bases are classified (strings, vtables)
IMGBASE_WINDOW = 0x800     # image-base table base this close before a cell -> unproven
SHALLOW = 2                # caller-derived class labels deeper than this are namespace-level only


def scan_pointers(np, img, lo_rva, hi_rva):
    """UNALIGNED abs64 scan of the whole file: every 8-byte window holding a VA inside
    [base+lo, base+hi). -> sorted unique target rvas (numpy int64)."""
    base = img.base
    n = len(img.m)
    out = []
    CH = 1 << 24
    lo_v, hi_v = np.uint64(base + lo_rva), np.uint64(base + hi_rva)
    for c0 in range(0, n, CH):
        seg = np.frombuffer(img.m[c0:min(n, c0 + CH + 7)], dtype=np.uint8)
        for sh in range(8):
            m8 = (len(seg) - sh) // 8
            if m8 <= 0:
                continue
            q = seg[sh:sh + 8 * m8].view("<u8")
            hit = q[(q >= lo_v) & (q < hi_v)]
            if len(hit):
                out.append(np.unique(hit))
    if not out:
        return np.array([], dtype=np.int64)
    return (np.unique(np.concatenate(out)) - np.uint64(base)).astype(np.int64)


def cmd_build(a):
    import numpy as np
    from multiprocessing import Pool
    t0 = time.time()
    exe = Path(a.exe)
    overlays = [str(o if Path(o).exists() else REPO / "tools" / "data" / "patches" / o) for o in (a.overlay or [])]
    tag = a.tag or ("+".join(Path(o).stem for o in overlays) if overlays else None)
    OUT, REFS, SUMMARY = paths(tag)
    img = PatchedImage(exe, overlays)
    base = img.base
    flags = section_flags(img)
    print(f"exe: {exe} ({exe.stat().st_size:,} B)")
    for l in img.overlay_log:
        print(f"   overlay {l['spec']}: {l['va']:#x} {l['status']:17} {l['name'][:70]}")
    sha1 = hashlib.sha1()
    with open(exe, "rb") as f:
        while True:
            blk = f.read(1 << 24)
            if not blk:
                break
            sha1.update(blk)
    sha1 = sha1.hexdigest()
    state = REPO / "build" / "exe_patch_state.json"
    pristine = None
    if state.exists():
        pristine = json.loads(state.read_text()).get("pristine_sha1")
    print(f"sha1: {sha1}" + (f"  ({'== pristine' if sha1 == pristine else '!= pristine ' + str(pristine)})" if pristine else ""))

    # 1. functions ------------------------------------------------------------------------
    mp, meth = load_methods()
    ranges = derive_ranges(meth)
    print("gameplay ranges (derived from match:: vtable methods):")
    for lo, hi, n in ranges:
        print(f"   {base + lo:#x}-{base + hi:#x}  {(hi - lo) / 1e6:6.2f} MB  {n} match methods")
    pd = load_pdata(img)
    if pd is None:
        sys.exit("no exception directory - this build of the tool needs .pdata")
    exec_secs = [s for s in img.secs if s["exec"] and s["rsize"]]
    print(f".pdata: {len(pd):,} RUNTIME_FUNCTIONs, {len(np.unique(pd[:, 2])):,} root functions "
          f"({int((pd[:, 0] != pd[:, 2]).sum()):,} chained chunks)")
    match_meth = {m for m, d in meth.items() if d["match"]}
    tasks, task_root = [], []
    helper_vas = set(HELPERS)
    for s in exec_secs:
        lo, hi = s["va"], s["va"] + min(s["vsize"], s["rsize"])
        sel = pd[(pd[:, 0] >= lo) & (pd[:, 0] < hi)]
        prev = lo
        sweep_gaps = s["name"] == ".xcode" or a.gaps_everywhere
        for b, e, r in sel.tolist():
            e = min(e, hi)
            if b > prev and sweep_gaps:
                keep = in_ranges(prev, ranges) or in_ranges(b - 1, ranges)
                tasks.append((prev, b, True, keep))
                task_root.append(-1)
            keep = in_ranges(r, ranges) or r in match_meth or b in match_meth
            if e > b:
                tasks.append((b, e, False, keep))
                task_root.append(r)
            prev = max(prev, e)
        if prev < hi and sweep_gaps:
            tasks.append((prev, hi, True, in_ranges(prev, ranges)))
            task_root.append(-1)
    # match:: methods that live in gaps outside the ranges: keep their gap's text too
    gap_idx = [i for i, t in enumerate(tasks) if t[2] and not t[3]]
    if gap_idx:
        gs = np.array([tasks[i][0] for i in gap_idx]); ge = np.array([tasks[i][1] for i in gap_idx])
        for m in match_meth:
            j = int(np.searchsorted(gs, m, "right")) - 1
            if j >= 0 and m < ge[j]:
                t = tasks[gap_idx[j]]
                tasks[gap_idx[j]] = (t[0], t[1], True, True)
    jobs = a.jobs or max(1, min(24, (os.cpu_count() or 4) - 2))
    groups = defaultdict(list)
    for i, (t, r) in enumerate(zip(tasks, task_root)):
        groups[r if r >= 0 else -1 - i].append(t)     # a function's chunks stay together; gaps stand alone
    parts = _split(list(groups.values()), jobs * 6)
    print(f"sweep: {len(tasks):,} chunks, {sum(t[1] - t[0] for t in tasks) / 1e6:.1f} MB, {jobs} workers ...", flush=True)
    sites, targets, kinds, dposs, widths, leafs, text, hcalls, esites, etargets = [], [], [], [], [], [], [], [], [], []
    ibs, ibtext, ibleas, fimm, chunk_q = [], [], [], [], []
    nins = desync = ntables = ncodetbl = 0
    with Pool(jobs) as pool:
        for r in pool.imap_unordered(_sweep_task, [(str(exe), overlays, p_, helper_vas) for p_ in parts]):
            sites.append(r[0]); targets.append(r[1]); kinds.append(r[2]); dposs.append(r[3])
            leafs += r[4]; text += r[5]; hcalls += r[6]
            nins += r[7]; desync += r[8]; ntables += r[9]
            esites.append(r[10]); etargets.append(r[11]); widths.append(r[12])
            ibs.append(r[13]); ibtext += r[14]; ibleas.append(r[15]); fimm += r[16]; chunk_q += r[17]; ncodetbl += r[18]
    sites = np.concatenate(sites); targets = np.concatenate(targets)
    kinds = np.concatenate(kinds); dposs = np.concatenate(dposs); widths = np.concatenate(widths)
    esites = np.concatenate(esites); etargets = np.concatenate(etargets)
    ib = np.concatenate(ibs) if ibs else np.zeros((0, 5), dtype=np.int64)
    ib = ib[np.argsort(ib[:, 0], kind="stable")]
    iblea = np.sort(np.concatenate(ibleas)) if ibleas else np.array([], dtype=np.uint32)
    o = np.argsort(sites, kind="stable")
    sites, targets, kinds, dposs, widths = sites[o], targets[o], kinds[o], dposs[o], widths[o]
    print(f"   {nins:,} instructions, {len(sites):,} RIP-relative operands, {len(esites):,} direct call/tail-jmp edges, "
          f"{ntables:,} in-code switch tables skipped ({ncodetbl:,} named by their dispatch code), {desync:,} resyncs, "
          f"{len(leafs):,} leaf/gap segments  [{time.time() - t0:.0f}s]", flush=True)
    print(f"   image-base-relative addressing: {len(iblea):,} `lea reg,[rip->ImageBase]` sites, "
          f"{len(ib):,} `[reg+idx*s+RVA]` operands into data sections ({len(np.unique(ib[:, 1])):,} distinct bases)")

    # function table: pdata chunks + leaf segments
    leafs.sort()
    fb = np.concatenate([pd[:, 0], np.array([l[0] for l in leafs], dtype=np.uint32)])
    fe = np.concatenate([pd[:, 1], np.array([l[1] for l in leafs], dtype=np.uint32)])
    fr = np.concatenate([pd[:, 2], np.array([l[0] for l in leafs], dtype=np.uint32)])
    fleaf = np.concatenate([np.zeros(len(pd), bool), np.ones(len(leafs), bool)])
    o = np.argsort(fb, kind="stable")
    fb, fe, fr, fleaf = fb[o], fe[o], fr[o], fleaf[o]

    def func_of(rva_arr):
        rva_arr = np.asarray(rva_arr, dtype=np.int64)
        idx = np.searchsorted(fb, rva_arr, "right") - 1
        ok = (idx >= 0) & (rva_arr < fe[np.clip(idx, 0, None)])
        return np.where(ok, fr[np.clip(idx, 0, None)], 0)

    site_fn = func_of(sites)
    ib_fn = func_of(ib[:, 0]) if len(ib) else np.array([], dtype=np.int64)
    iblea_fns = np.unique(func_of(iblea)) if len(iblea) else np.array([], dtype=np.int64)
    ib_conf = np.isin(ib_fn, iblea_fns) & (ib_fn != 0) if len(ib) else np.array([], dtype=bool)
    print(f"   ... {int(ib_conf.sum()):,} of them in a function that provably loads ImageBase (the rest still veto: a false "
          f"positive can only cost a `private`)")

    # 2. refcounts -------------------------------------------------------------------
    ut, inv, cnt = np.unique(targets, return_inverse=True, return_counts=True)
    writes = np.bincount(inv, weights=(kinds == 2), minlength=len(ut)).astype(np.int64)
    leas = np.bincount(inv, weights=(kinds == 1), minlength=len(ut)).astype(np.int64)
    print(f"   {len(ut):,} distinct RIP targets")

    # whole-file UNALIGNED abs64 pointer scan (any section, any alignment)
    ptr_targets = scan_pointers(np, img, 0x1000, img.size_of_image)
    print(f"   stored pointers: {len(ptr_targets):,} distinct image addresses held as abs64 anywhere in the file  [{time.time() - t0:.0f}s]", flush=True)

    # method VA -> root function (a vtable slot may point into a function)
    meth_root = {}
    mv = np.array(sorted(meth), dtype=np.uint32)
    mroot = func_of(mv)
    for m, r in zip(mv.tolist(), mroot.tolist()):
        meth_root[m] = r or m
    fn_class = {}
    for m, d in meth.items():
        r = meth_root[m]
        if d["stub"]:
            continue
        if r not in fn_class or (d["match"] and not fn_class[r]["match"]) or (r == m and fn_class[r].get("_via") != r):
            fn_class[r] = dict(d, _via=m)
    attributed = np.array(sorted(fn_class), dtype=np.uint32)

    def near_class(root):
        j = int(np.searchsorted(attributed, root))
        best = None
        for k in (j - 1, j):
            if 0 <= k < len(attributed):
                dist = abs(int(attributed[k]) - root)
                if dist <= 0x4000 and (best is None or dist < best[0]):
                    best = (dist, int(attributed[k]))
        return fn_class[best[1]]["cls"] if best else None

    # gameplay function set
    roots_all = np.unique(fr)
    gp_roots = set(int(r) for r in roots_all if in_ranges(int(r), ranges))
    for m in match_meth:
        gp_roots.add(meth_root[m])
    chunks_of = defaultdict(list)
    sel = np.isin(fr, np.array(sorted(gp_roots), dtype=np.uint32))
    for b, e, r, lf in zip(fb[sel].tolist(), fe[sel].tolist(), fr[sel].tolist(), fleaf[sel].tolist()):
        chunks_of[r].append((b, e, lf))
    for m in match_meth:                          # a method no sweep found (should not happen)
        r = meth_root[m]
        if r not in chunks_of:
            body = img.function_body(r, 0x4000)
            end = (body[-1].address + body[-1].size - base) if body else r + 1
            chunks_of[r].append((r, end, True))
    # caller-derived attribution: a non-virtual function whose EVERY direct caller belongs to one
    # class (and whose address is never taken - by lea OR by a pointer stored in data) is reachable
    # only from that class. The label is only as good as the chain is short: `depth` = hops to the
    # vtable method(s); deeper than SHALLOW it is reported at namespace level only.
    e_from = func_of(esites)
    e_to = func_of(etargets)
    okm = (e_from != 0) & (e_to != 0) & (e_from != e_to) & (e_to == etargets)   # calls to function STARTS
    edges = np.unique(np.stack([e_to[okm], e_from[okm]], axis=1), axis=0)
    callers_of, callees_of = defaultdict(list), defaultdict(set)
    for t_, f_ in edges.tolist():
        if t_ in gp_roots:
            callers_of[t_].append(f_)
        if f_ in gp_roots:
            callees_of[f_].add(t_)
    code_lo, code_hi = exec_secs[0]["va"], exec_secs[0]["va"] + exec_secs[0]["vsize"]
    addr_taken = set(np.unique(targets[(kinds == 1) & (targets >= code_lo) & (targets < code_hi)]).tolist())
    n_lea_taken = len(addr_taken)
    addr_taken |= set(ptr_targets[(ptr_targets >= code_lo) & (ptr_targets < code_hi)].tolist())
    derived = {}
    for _round in range(12):
        changed = 0
        for f_, cl in callers_of.items():
            if f_ in derived or f_ in addr_taken or f_ in fn_class:
                continue
            labs = {fn_class[c]["cls"] if c in fn_class else (derived[c][0] if c in derived else None) for c in cl}
            if len(labs) == 1 and None not in labs:
                depth = 1 + max(0 if c in fn_class else derived[c][1] for c in cl)
                derived[f_] = (next(iter(labs)), depth)
                changed += 1
        if not changed:
            break

    def owner(root):
        """class label good enough to call a cell 'same class only': vtable method or shallow caller chain."""
        c = fn_class.get(root)
        if c:
            return c["cls"]
        d = derived.get(root)
        return d[0] if d and d[1] <= SHALLOW else None

    def owner_ns(root):
        c = fn_class.get(root)
        if c:
            return _ns(c["cls"])
        d = derived.get(root)
        return _ns(d[0]) if d else None

    print(f"gameplay functions: {len(chunks_of):,} "
          f"({sum(1 for r in chunks_of if r in fn_class):,} vtable-attributed, "
          f"{sum(1 for r in chunks_of if r in derived and derived[r][1] <= SHALLOW):,} caller-derived within {SHALLOW} hops, "
          f"{sum(1 for r in chunks_of if r in derived and derived[r][1] > SHALLOW):,} deeper (namespace-level only), "
          f"{sum(1 for c in chunks_of.values() if c[0][2]):,} leaf/gap); address-taken: {n_lea_taken:,} by lea, "
          f"{len(addr_taken) - n_lea_taken:,} more by stored pointer")

    # 3. census ----------------------------------------------------------------------
    text.sort()
    t_sites = np.array([t[0] for t in text], dtype=np.uint32)
    t_fn = func_of(t_sites) if len(text) else np.array([], dtype=np.uint32)
    data_secs = {s["name"]: s for s in img.secs if not s["exec"]}
    cell_info, fn_cells = {}, defaultdict(list)
    text_cache, dropped_text = {}, {}
    ut64 = ut.astype(np.int64)

    def next_target_gap(t):
        j = int(np.searchsorted(ut64, t, "right"))
        return int(ut64[j]) - t if j < len(ut64) else 0

    for (site, sz, mn, ops, t, k), root in zip(text, t_fn.tolist()):
        if root not in chunks_of:
            continue
        sec = img.section_of(t)
        if sec not in data_secs:
            continue
        dv = decode_cell(img, t, mn, ops, k, next_target_gap(t) if k == 1 else 0)
        if dv is None:
            continue
        wr = flags.get(sec, {}).get("write")
        if wr and (dv[0] not in ("f32", "f64") or dv[1] == 0):
            continue                              # runtime globals: keep only initialised floats
        if dv[0] in KIND_WIDTH:
            key = (t, KIND_WIDTH[dv[0]])
            if key not in text_cache:
                text_cache[key] = text_extent(img, t, KIND_WIDTH[dv[0]])
            if text_cache[key]:                   # bytes of a string literal (inlined strcpy), not a constant
                dropped_text[t] = text_cache[key]
                continue
        fn_cells[root].append(dict(va=site, mn=mn, ops=ops, role=role_of(mn, k), cell=t))
        if t not in cell_info:
            cell_info[t] = dict(section=sec, kind=dv[0], value=dv[1])
        elif cell_info[t]["kind"] != dv[0] and dv[0] in ("f32", "f64") and cell_info[t]["kind"] in ("i32", "table", "itable", "i8", "i16"):
            cell_info[t].update(kind=dv[0], value=dv[1])
    # image-base tables read from gameplay code become census cells too
    ibtext.sort()
    ibt_fn = func_of(np.array([x[0] for x in ibtext], dtype=np.int64)) if ibtext else []
    ib_bases_u = np.unique(ib[:, 1]) if len(ib) else np.array([], dtype=np.int64)
    for (site, sz, mn, ops, t, scale), root in zip(ibtext, ibt_fn.tolist() if len(ibtext) else []):
        if root not in chunks_of:
            continue
        sec = img.section_of(t)
        if sec not in data_secs or flags.get(sec, {}).get("write"):
            continue
        w = access_width(mn, ops)
        m_ = mn[1:] if mn[0] == "v" else mn
        if w == 4:
            j = int(np.searchsorted(ib_bases_u, t, "right"))
            lim = min(next_target_gap(t) or 0x100, (int(ib_bases_u[j]) - t) if j < len(ib_bases_u) else 0x100)
            dt = decode_table(img, t, lim, "float" if ("xmm" in ops and m_ != "movd") else None)
        else:
            dt = None
        fn_cells[root].append(dict(va=site, mn=mn, ops=ops, role="table[i]", cell=t))
        if t not in cell_info:
            if dt:
                kd_, val_ = dt[0], dt[1]
            elif w == 1:
                kd_, val_ = "itable", list(img.read(t, 16))
            elif w == 2:
                kd_, val_ = "itable", list(struct.unpack("<8h", img.read(t, 16)))
            elif w == 8 and m_.endswith("sd"):
                kd_, val_ = "table", [float(f"{x:.9g}") for x in struct.unpack("<4d", img.read(t, 32))]
            else:
                kd_, val_ = "itable", []
            cell_info[t] = dict(section=sec, kind=kd_, value=val_, via="imgbase", stride=scale, elem_bytes=w)
            if dt:
                cell_info[t]["est_len"] = dt[2]

    # helper-calling functions -> taint walk
    hfn = defaultdict(int)
    if hcalls:
        hs = np.array([c[0] for c in hcalls], dtype=np.uint32)
        for r in func_of(hs).tolist():
            if r in chunks_of:
                hfn[r] += 1
    tt = [(r, [(b, e) for b, e, _ in sorted(chunks_of[r])]) for r in sorted(hfn)]
    tt.sort(key=lambda x: -sum(e - b for b, e in x[1]))
    print(f"taint walk: {len(tt):,} functions call one of the {len(HELPERS)} helpers ...", flush=True)
    taint_res = {}
    nparts = max(1, min(len(tt), jobs * 4))
    with Pool(min(jobs, nparts)) as pool:
        for r in pool.imap_unordered(_taint_task, [(str(exe), overlays, tt[i::nparts]) for i in range(nparts)]):
            taint_res.update(r)

    # raw byte-pattern cross-check: the WHOLE FILE, every section -----------------------------
    cells_sorted = np.array(sorted(cell_info), dtype=np.int64)
    cell_w = np.array([KIND_WIDTH.get(cell_info[t]["kind"], 4) for t in cells_sorted.tolist()], dtype=np.int64)
    raw_unexpl = np.zeros(len(cells_sorted), dtype=np.int64)       # code-flagged section, 4-aligned offset in the cell
    raw_noncode = np.zeros(len(cells_sorted), dtype=np.int64)      # weak: data sections, or an odd offset inside the cell
    raw_total = np.zeros(len(cells_sorted), dtype=np.int64)
    explained = np.unique(dposs[dposs != 0]).astype(np.int64)
    stats_raw = dict(candidates=0, explained=0, sections={})
    for s in img.secs:
        if not s["rsize"]:
            continue
        fl = flags.get(s["name"], {})
        codeish = bool(fl.get("exec") or fl.get("code"))
        nsec_hits = 0
        raw = np.frombuffer(img.m[s["raw"]:s["raw"] + s["rsize"]], dtype=np.uint8)
        CH = 1 << 24
        for c0 in range(0, len(raw) - 5, CH):
            seg = raw[c0:c0 + CH + 5]
            pos = np.flatnonzero((seg[:-5] & 0xC7) == 0x05)
            if not len(pos):
                continue
            d = (seg[pos + 1].astype(np.int64) | (seg[pos + 2].astype(np.int64) << 8)
                 | (seg[pos + 3].astype(np.int64) << 16) | (seg[pos + 4].astype(np.int64) << 24))
            d = np.where(d >= 1 << 31, d - (1 << 32), d)
            dp = s["va"] + c0 + pos + 1              # rva of the disp32 field
            is_expl = np.isin(dp, explained)
            for k in (0, 1, 2, 4):                   # trailing immediate bytes after the disp32
                tg = dp + 4 + k + d
                for back in (0, 1):                  # the cell starting at/below tg, and the (wider) one before it
                    j0 = np.searchsorted(cells_sorted, tg, "right") - 1 - back
                    j = np.clip(j0, 0, len(cells_sorted) - 1)
                    hit = (j0 >= 0) & (cells_sorted[j] <= tg) & (tg < cells_sorted[j] + cell_w[j])
                    exact = hit & (cells_sorted[j] == tg)
                    if k == 0 and not back:
                        np.add.at(raw_total, j[exact], 1)
                        stats_raw["candidates"] += int(exact.sum())
                        stats_raw["explained"] += int((exact & is_expl).sum())
                    un = hit & ~is_expl
                    nsec_hits += int(un.sum())
                    strong = un & (((tg - cells_sorted[j]) % 4) == 0) if codeish else (un & False)
                    np.add.at(raw_unexpl, j[strong], 1)
                    np.add.at(raw_noncode, j[un & ~strong], 1)
        stats_raw["sections"][s["name"]] = dict(code_flag=codeish, unexplained_hits=nsec_hits)
    print(f"raw modrm-pattern cross-check (whole file, k=0/1/2/4): {stats_raw['candidates']:,} exact disp32 hits on census cells, "
          f"{stats_raw['explained']:,} explained by capstone "
          f"({100.0 * stats_raw['explained'] / max(1, stats_raw['candidates']):.2f}%)  [{time.time() - t0:.0f}s]", flush=True)
    # aligned u32 RVA hits in data sections: ADVISORY only (chance hits are expected at this file size)
    rva32 = np.zeros(len(cells_sorted), dtype=np.int64)
    for s in img.secs:
        if s["exec"] or s["rsize"] < 4:
            continue
        v = np.frombuffer(img.m[s["raw"]:s["raw"] + (s["rsize"] // 4) * 4], dtype="<u4").astype(np.int64)
        v = v[(v >= cells_sorted[0]) & (v <= cells_sorted[-1])] if len(cells_sorted) else v[:0]
        j = np.clip(np.searchsorted(cells_sorted, v), 0, max(0, len(cells_sorted) - 1))
        hit = cells_sorted[j] == v
        np.add.at(rva32, j[hit], 1)

    # bases: every lea target and every stored-pointer target that lands in a data section
    lea_targets = np.unique(targets[kinds == 1]).astype(np.int64)
    ptr_data = ptr_targets[(ptr_targets < code_lo) | (ptr_targets >= code_hi)]
    bases_all = np.unique(np.concatenate([lea_targets, ptr_data]))
    is_ptr_base = np.isin(bases_all, ptr_data)
    is_lea_base = np.isin(bases_all, lea_targets)
    base_cache = {}

    def base_class(b_):
        if b_ not in base_cache:
            base_cache[b_] = classify_base(img, b_, base, img.size_of_image)
        return base_cache[b_]

    ib_sorted = ib[np.argsort(ib[:, 1], kind="stable")] if len(ib) else ib
    ib_t = ib_sorted[:, 1] if len(ib) else np.array([], dtype=np.int64)
    pool_section = Counter(v["section"] for v in cell_info.values() if v["kind"] == "f32").most_common(1)
    pool_section = pool_section[0][0] if pool_section else None

    # per-cell facts
    order = np.argsort(targets, kind="stable")
    t_sorted = targets[order].astype(np.int64)
    for ci, t in enumerate(cells_sorted.tolist()):
        info = cell_info[t]
        w = KIND_WIDTH.get(info["kind"], 4)
        lo = int(np.searchsorted(t_sorted, t, "left")); hi = int(np.searchsorted(t_sorted, t, "right"))
        idx = order[lo:hi]
        rs = sites[idx]; fns = site_fn[idx]
        rc = hi - lo
        ui = int(np.searchsorted(ut, t))
        has_direct = ui < len(ut) and int(ut[ui]) == t
        classes = set()
        for f in set(fns.tolist()):
            classes.add(owner(f))
        sec = info["section"]
        writable = flags.get(sec, {}).get("write", False)
        veto, unproven, notes = [], [], []
        # --- (a) interval test: any OTHER access whose bytes intersect [t, t+w)
        lo2 = int(np.searchsorted(t_sorted, t - 63, "left")); hi2 = int(np.searchsorted(t_sorted, t + w, "left"))
        ov = []
        for q in range(lo2, hi2):
            T = int(t_sorted[q])
            if T == t:
                continue
            oi = order[q]
            kd, wd = int(kinds[oi]), int(widths[oi])
            if kd == 3:
                continue
            if T > t or (kd != 1 and T + wd > t):
                ov.append((int(sites[oi]), T, wd, kd))
        if ov:
            veto.append("overlap")
            info["overlap_refs"] = [dict(site=base + s_, target=base + T, width=wd, lea=(kd == 1)) for s_, T, wd, kd in ov[:6]]
            info["overlap_count"] = len(ov)
        # --- (b) image-base tables
        lo3 = int(np.searchsorted(ib_t, t - IMGBASE_WINDOW, "left")); hi3 = int(np.searchsorted(ib_t, t + w, "left"))
        if hi3 > lo3:
            rows = ib_sorted[lo3:hi3]
            nb = int(rows[-1, 1])
            same = rows[rows[:, 1] == nb]
            info["imgbase_near"] = dict(base=base + nb, dist=t - nb, sites=[base + int(x) for x in same[:4, 0]],
                                        n_sites=int(len(same)), elem_bytes=int(same[0, 2]), scale=int(same[0, 3]),
                                        tables_in_window=int(len(np.unique(rows[:, 1]))))
            if nb >= t:
                veto.append("imgbase_table_base")
            else:
                unproven.append("imgbase_table_near")
        # --- (c) lea / stored-pointer bases: strings, vtables, arrays
        lo4 = int(np.searchsorted(bases_all, t - BASE_WINDOW, "left")); hi4 = int(np.searchsorted(bases_all, t + w, "left"))
        near = []
        for q in range(lo4, hi4):
            b_ = int(bases_all[q])
            how = ("lea" if is_lea_base[q] else "") + ("+ptr" if is_ptr_base[q] else "")
            if b_ >= t:
                if b_ == t and not is_ptr_base[q]:
                    continue                          # a lea of the cell itself is counted in `leas`
                veto.append("pointer_to_cell" if b_ == t else "base_inside_cell")
                near.append(dict(base=base + b_, how=how, cls="exact" if b_ == t else "inside"))
                continue
            cls_, end = base_class(b_)
            rec_ = dict(base=base + b_, how=how, cls=cls_, dist=t - b_)
            if end is not None:
                rec_["end"] = base + end
                if end > t:
                    veto.append(f"inside_{cls_}")
                    near.append(rec_)
                elif t - b_ <= NEAR_WINDOW:
                    near.append(rec_)                 # proven to end before the cell: cleared
            elif t - b_ <= NEAR_WINDOW:
                unproven.append(f"after_unbounded_{cls_.rstrip('?')}")
                near.append(rec_)
        if near:
            info["bases_near"] = near[-4:]
        # --- (d) the rest
        if info.get("via") == "imgbase" or info["kind"] in ("table", "itable"):
            veto.append("table")
        if writable:
            veto.append("writable_section")
        if has_direct and int(writes[ui]):
            veto.append("written")
        if has_direct and int(leas[ui]):
            veto.append("address_taken_by_lea")
        if int(raw_unexpl[ci]):
            veto.append("raw_pattern_in_code_section")
        if int(raw_noncode[ci]):
            unproven.append("raw_pattern_weak")
        if w >= 2 and t % min(w, 4):
            veto.append("misaligned")
        if sec != pool_section and not writable:
            unproven.append("outside_literal_pool")
        if int(rva32[ci]):
            notes.append(f"rva32_hits={int(rva32[ci])}")
        info.update(width=w, refcount=rc, writers=int(writes[ui]) if has_direct else 0,
                    leas=int(leas[ui]) if has_direct else 0,
                    raw_unexplained=int(raw_unexpl[ci]), raw_noncode_hits=int(raw_noncode[ci]),
                    ptr_refs=int("pointer_to_cell" in veto), rva32_hits=int(rva32[ci]),
                    writable_section=writable,
                    same_function_only=len(set(fns.tolist())) == 1,
                    same_class_only=(len(classes) == 1 and None not in classes),
                    classes=sorted(c for c in classes if c)[:6] + (["<unattributed>"] if None in classes else []))
        veto = sorted(set(veto)); unproven = sorted(set(unproven))
        if "table" in veto:
            status = "table"
        elif rc != 1:
            status = "shared"
        elif veto:
            status = "vetoed"
        elif unproven:
            status = "private_unproven"
        else:
            status = "private"
        info["status"] = status
        info["private"] = status == "private"
        if rc == 1 or status == "table":
            if veto:
                info["veto"] = veto
            if unproven:
                info["unproven"] = unproven
        if rc <= 8:
            info["referrers"] = [int(x) for x in rs.tolist()]

    # 4. assemble ----------------------------------------------------------------------------
    cq = defaultdict(lambda: [0, 0])
    if chunk_q:
        for r_, (s_, ds_, ct_) in zip(func_of(np.array([c[0] for c in chunk_q], dtype=np.int64)).tolist(), chunk_q):
            cq[r_][0] += ds_; cq[r_][1] += ct_
    fimm.sort()
    fimm_fn = func_of(np.array([x[0] for x in fimm], dtype=np.int64)).tolist() if fimm else []
    fn_fimm = defaultdict(list)
    for (site, imm_va, val, txt), r_ in zip(fimm, fimm_fn):
        fn_fimm[r_].append(dict(va=base + site, imm_va=base + imm_va, value=val, text=txt, kind="imm_f32", role="store",
                                low_interest=abs(val) in (1.0, 0.5, 2.0)))
    functions = {}
    for root in sorted(chunks_of):
        ch = sorted(chunks_of[root])
        c = fn_class.get(root)
        rec = dict(size=sum(e - b for b, e, _ in ch), kind="leaf" if ch[0][2] else "pdata",
                   in_range=in_ranges(root, ranges))
        if len(ch) > 1:
            rec["chunks"] = [[base + b, base + e] for b, e, _ in ch]
        if root in cq:
            if cq[root][0]:
                rec["resyncs"] = cq[root][0]          # linear sweep lost sync here: refs of this fn are low-confidence
            if cq[root][1]:
                rec["switch_tables"] = cq[root][1]
        if c:
            rec.update(cls=c["cls"], vf=c["vf"], owners=c["owners"])
            if c["_via"] != root:
                rec["vtable_entry"] = base + c["_via"]
        else:
            cl = callers_of.get(root, [])
            rec["n_callers"] = len(cl)
            if root in derived:
                rec["callers_cls"], rec["callers_depth"] = derived[root]
                rec["callers"] = [base + x for x in cl[:6]]
            else:
                ns_ = {owner_ns(x) for x in cl}
                if len(cl) >= 4 or len(ns_ - {None}) >= 2:
                    rec["shared_helper"] = True       # many / mixed callers: the nearest vtable method says nothing
                else:
                    nc = near_class(root)
                    if nc:
                        rec["near"] = nc
            if root in addr_taken:
                rec["address_taken"] = True
        tr = taint_res.get(root)
        cells = fn_cells.get(root, [])
        if tr:
            for cr in cells:
                tg = tr[2].get(base + cr["va"])
                if tg:
                    cr["taint"] = tg[0]
                    cr["taint_call"] = tg[1]
                    if tg[2] is not None:
                        cr["taint_arg"] = tg[2]
        for cr in cells:
            cr["va"] += base
            cr["cell"] += base
        if cells:
            rec["cells"] = sorted(cells, key=lambda x: x["va"])
        if root in fn_fimm:
            rec["fimms"] = fn_fimm[root]
        if tr:
            imms, hc, _ = tr
            seen = set()
            out_imm = []
            for im in imms:
                key = (im["va"], im.get("via"))
                if key in seen:
                    continue
                seen.add(key)
                out_imm.append(im)
            args, gps, attrs = [], [], []
            for h in hc:
                kind = h["kind"]
                if h["helper"] in GETPARAM:
                    g = dict(va=h["va"], helper=h["helper"], row=h.get("arg"))
                    if "arg_site" in h:
                        g.update(row_site=h["arg_site"], row_how=h["arg_how"], row_text=h["arg_text"])
                    gps.append(g)
                elif kind == "attr":
                    attrs.append(dict(va=h["va"], idx=h.get("arg"), helper=h["helper"]))
                elif kind in ("pct_roll", "randint") and "arg" in h:
                    args.append(dict(va=h["arg_site"], text=h["arg_text"], imm=h["arg"], role="arg",
                                     how=h["arg_how"], src=kind, feeds=h["helper"], call=h["va"]))
                elif kind in ("pct_roll", "randint", "rng", "gauss", "accuracy"):
                    args.append(dict(va=h["va"], text="call (non-constant arg)", imm=None, role="arg-dynamic",
                                     src=kind, feeds=h["helper"], call=h["va"]))
            if out_imm or args:
                rec["imms"] = sorted(out_imm + args, key=lambda x: x["va"])
            if gps:
                rec["getparam"] = gps
            if attrs:
                rec["attr_calls"] = attrs
        functions[f"{base + root:#x}"] = rec

    cells_out = {f"{base + t:#x}": v for t, v in sorted(cell_info.items())}
    for v in cells_out.values():
        if "referrers" in v:
            v["referrers"] = [base + x for x in v["referrers"]]

    # helper-set review aid: small gameplay functions whose only callees are known helpers
    helper_rvas = {h - base for h in HELPERS}
    hcount = Counter(int(x) for x in etargets[np.isin(etargets, np.array(sorted(helper_rvas), dtype=np.uint32))].tolist())
    wrappers = []
    for f_, cs_ in callees_of.items():
        if f_ in helper_rvas or not cs_ or not (cs_ <= helper_rvas):
            continue
        size_ = sum(e - b for b, e, _ in chunks_of.get(f_, []))
        if 0 < size_ <= 0x60:
            wrappers.append(dict(va=base + f_, size=size_, wraps=[base + x for x in sorted(cs_)],
                                 callers=len(callers_of.get(f_, []))))
    wrappers.sort(key=lambda x: -x["callers"])

    summary = summarise(functions, cells_out)
    meta = dict(exe=str(exe), size=exe.stat().st_size, sha1=sha1, pristine=(sha1 == pristine) if pristine else None,
                tool_sha1=tool_sha1(),
                built=time.strftime("%Y-%m-%d %H:%M:%S"), base=base,
                ranges=[[base + lo, base + hi, n] for lo, hi, n in ranges],
                pdata_entries=int(len(pd)), instructions=nins, rip_operands=int(len(sites)),
                distinct_targets=int(len(ut)), resyncs=desync, leaf_segments=len(leafs),
                jump_tables=ntables, dispatch_named_tables=ncodetbl, call_edges=int(len(esites)),
                imgbase=dict(lea_sites=int(len(iblea)), operands=int(len(ib)), confirmed=int(ib_conf.sum()) if len(ib) else 0,
                             distinct_bases=int(len(ib_bases_u))),
                stored_pointers=int(len(ptr_targets)), dropped_text_cells=len(dropped_text),
                pool_section=pool_section,
                coverage=dict(
                    refcount="capstone linear sweep: every .pdata function of every executable section + every gap of .xcode",
                    raw_crosscheck="whole file, all sections, k=0/1/2/4, any byte of the cell; an unexplained hit in an EXECUTE/"
                                   "CNT_CODE section at a 4-aligned offset of the cell vetoes; any other hit (data sections, "
                                   "odd offsets - mostly Denuvo junk / coincidence) -> private_unproven",
                    pointers="whole file, unaligned abs64",
                    not_covered="addresses computed at run time (Denuvo VM / lea + arithmetic), imm16 operand forms other "
                                "than k=2, references from code that is packed or generated at run time"),
                overlays=img.overlay_log, tag=tag,
                raw_crosscheck=stats_raw, helpers={f"{k:#x}": v[1] for k, v in HELPERS.items()},
                helper_call_sites={f"{base + k:#x}": v for k, v in sorted(hcount.items())},
                helper_wrapper_candidates=wrappers[:40],
                level_table=LEVEL_TABLE, seconds=round(time.time() - t0, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(meta=meta, summary=summary, cells=cells_out, functions=functions)), encoding="utf-8")
    np.savez_compressed(REFS, sites=sites, targets=targets, kinds=kinds, widths=widths, site_fn=site_fn,
                        fb=fb, fe=fe, fr=fr, ib=ib, ib_fn=ib_fn, ib_conf=ib_conf)
    SUMMARY.write_text(format_summary(summary, meta), encoding="utf-8")
    print(format_summary(summary, meta, top=25))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB), {REFS.name}, {SUMMARY.name}  [{time.time() - t0:.0f}s]")
    return 0


def _label(rec):
    """Class          vtable method (exact)
    >Class           non-virtual; every direct caller chain ends in Class within SHALLOW hops
    >>ns::*          same, but the chain is longer: measured precision is namespace-level only
                     (long chains collapse onto container classes such as match::MatchControl)
    ~Class           merely the nearest vtable method (weak hint; suppressed for shared helpers)"""
    if rec.get("cls"):
        return rec["cls"]
    if rec.get("callers_cls"):
        if rec.get("callers_depth", 1) <= SHALLOW:
            return ">" + rec["callers_cls"]
        return ">>" + _ns(rec["callers_cls"]) + "::*"
    if rec.get("shared_helper"):
        return "<shared helper>"
    return "~" + rec["near"] if rec.get("near") else "<unattributed>"


def _ns(label):
    l = label.lstrip("~>")
    if l.endswith("::*"):
        l = l[:-3]
    if l.startswith("<"):
        return l
    parts = [p for p in l.split("::") if p]
    if not parts:
        return "<global>"
    if parts[0] == "match" and len(parts) >= 2 and (len(parts) > 2 or label.endswith("::*")):
        return "::".join(parts[:2])
    return parts[0] if parts[0] != "match" else "match"


def summarise(functions, cells):
    def blank():
        return dict(functions=0, cell_refs=0, private_cells=set(), unproven_cells=set(), shared_cells=set(),
                    immediates=0, float_imms=0, helper_args=0, getparam_rows=set(), getparam_calls=0)
    by_cls, by_ns = defaultdict(blank), defaultdict(blank)
    for fva, rec in functions.items():
        lab = _label(rec)
        for agg in (by_cls[lab], by_ns[_ns(lab)]):
            agg["functions"] += 1
            for c in rec.get("cells", ()):
                agg["cell_refs"] += 1
                ci = cells[f"{c['cell']:#x}"]
                (agg["private_cells"] if ci["private"] else agg["unproven_cells"] if ci["status"] == "private_unproven"
                 else agg["shared_cells"]).add(c["cell"])
            agg["float_imms"] += sum(1 for x in rec.get("fimms", ()) if not x["low_interest"])
            for im in rec.get("imms", ()):
                if im["role"].startswith("arg"):
                    agg["helper_args"] += 1
                else:
                    agg["immediates"] += 1
            for g in rec.get("getparam", ()):
                agg["getparam_calls"] += 1
                if g["row"] is not None:
                    agg["getparam_rows"].add(g["row"])

    def fin(d):
        return {k: dict(v, private_cells=len(v["private_cells"]), unproven_cells=len(v["unproven_cells"]),
                        shared_cells=len(v["shared_cells"]),
                        getparam_rows=sorted(v["getparam_rows"])) for k, v in sorted(d.items())}
    kinds = Counter(v["kind"] for v in cells.values())
    tot = dict(functions=len(functions), cells=len(cells), cells_by_kind=dict(kinds),
               private_cells=sum(1 for v in cells.values() if v["private"]),
               private_floats=sum(1 for v in cells.values() if v["private"] and v["kind"] in ("f32", "f64")),
               private_unproven=sum(1 for v in cells.values() if v["status"] == "private_unproven"),
               private_unproven_floats=sum(1 for v in cells.values() if v["status"] == "private_unproven" and v["kind"] in ("f32", "f64")),
               single_ref_vetoed=sum(1 for v in cells.values() if v["status"] == "vetoed"),
               veto_reasons=dict(Counter(r for v in cells.values() if v["status"] == "vetoed" for r in v.get("veto", ()))),
               unproven_reasons=dict(Counter(r for v in cells.values() if v["status"] == "private_unproven" for r in v.get("unproven", ()))),
               float_imm_stores=sum(len(r.get("fimms", ())) for r in functions.values()),
               float_imm_stores_interesting=sum(1 for r in functions.values() for x in r.get("fimms", ()) if not x["low_interest"]),
               low_confidence_functions=sum(1 for r in functions.values() if r.get("resyncs")),
               immediates=sum(1 for r in functions.values() for i in r.get("imms", ()) if not i["role"].startswith("arg")),
               helper_args=sum(1 for r in functions.values() for i in r.get("imms", ()) if i["role"] == "arg"),
               getparam_calls=sum(len(r.get("getparam", ())) for r in functions.values()),
               getparam_rows=sorted({g["row"] for r in functions.values() for g in r.get("getparam", ()) if g["row"] is not None}),
               attr_calls=sum(len(r.get("attr_calls", ())) for r in functions.values()))
    return dict(total=tot, by_namespace=fin(by_ns), by_class=fin(by_cls))


def format_summary(summary, meta, top=None):
    L = []
    t = summary["total"]
    L.append(f"eFootball.exe constant census  ({meta['built']}, sha1 {meta['sha1'][:12]}, pristine={meta['pristine']})")
    L.append(f"  whole image: {meta['instructions']:,} instructions, {meta['rip_operands']:,} RIP operands, "
             f"{meta['distinct_targets']:,} distinct targets, {meta['resyncs']:,} resyncs")
    L.append(f"  gameplay: {t['functions']:,} functions, {t['cells']:,} data cells {t['cells_by_kind']}")
    L.append(f"  single-referrer cells: PRIVATE {t['private_cells']:,} ({t['private_floats']:,} floats) | "
             f"private_UNPROVEN {t['private_unproven']:,} ({t['private_unproven_floats']:,} floats) | VETOED {t['single_ref_vetoed']:,}")
    L.append(f"     unproven because: {t['unproven_reasons']}")
    L.append(f"     vetoed because:   {t['veto_reasons']}")
    L.append(f"  float immediates stored inline (mov dword [mem],imm32): {t['float_imm_stores']:,} "
             f"({t['float_imm_stores_interesting']:,} other than +-1 / 0.5 / 2); functions where the sweep lost sync: "
             f"{t['low_confidence_functions']:,}")
    L.append(f"  immediates on attr/rng/level-derived values: {t['immediates']:,}; constant helper args: {t['helper_args']:,}; "
             f"ATTR_get calls: {t['attr_calls']:,}")
    L.append(f"  GetParam/IsEnabled calls: {t['getparam_calls']}, constant rows seen: {t['getparam_rows']}")
    hdr = f"{'':60} {'fns':>6} {'refs':>7} {'priv':>6} {'unprv':>6} {'shared':>7} {'imm':>5} {'fimm':>5} {'args':>5}  getparam rows"
    for title, key in (("per namespace", "by_namespace"), ("per class", "by_class")):
        L.append("")
        L.append(f"-- {title} " + "-" * 40)
        L.append(hdr)
        rows = sorted(summary[key].items(), key=lambda kv: -kv[1]["cell_refs"])
        if top and key == "by_class":
            rows = rows[:top]
        for k, v in rows:
            L.append(f"{k[:60]:60} {v['functions']:6} {v['cell_refs']:7} {v['private_cells']:6} {v['unproven_cells']:6} "
                     f"{v['shared_cells']:7} {v['immediates']:5} {v['float_imms']:5} {v['helper_args']:5}  {v['getparam_rows'] or ''}")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------
# queries
# ----------------------------------------------------------------------------------------

def load_census(a=None):
    out = paths(getattr(a, "tag", None))[0]
    if not out.exists():
        sys.exit(f"{out.name} missing - run: python tools/exe_census.py build")
    cz = json.loads(out.read_text(encoding="utf-8"))
    built_by = cz["meta"].get("tool_sha1")
    cz["meta"]["_stale"] = built_by != tool_sha1()
    if cz["meta"]["_stale"]:
        print(f"!! STALE: {out.name} was built by a different version of exe_census.py "
              f"({(built_by or 'unrecorded')[:12]} != {tool_sha1()[:12]}). Rebuild before trusting anything below.\n",
              file=sys.stderr)
    return cz


def _fmt_val(ci):
    v = ci["value"]
    return f"{v}" + ("f" if ci["kind"] == "f32" else "")


def _cell_line(c, ci):
    st_ = ci["status"]
    safety = {"private": "PRIVATE", "shared": f"shared x{ci['refcount']}", "table": "table"}.get(st_)
    if st_ == "private_unproven":
        safety = "private-UNPROVEN(" + ",".join(ci.get("unproven", ())) + ")"
    elif st_ == "vetoed":
        safety = "single-ref VETOED(" + ",".join(ci.get("veto", ())) + ")"
    extra = ""
    if c.get("taint"):
        extra = f"  <- {c['taint']}" + (f"[{c['taint_arg']:#x}]" if c.get("taint_arg") is not None else "") + f" @{c['taint_call']:#x}"
    return (f"    {c['va']:#x}  {c['role']:7} {c['mn']:9} {c['ops'][:44]:44} {c['cell']:#x} [{ci['section']}] "
            f"{ci['kind']}={_fmt_val(ci)!s:<14} {safety}{extra}")


def cmd_show(a):
    cz = load_census(a)
    fns, cells = cz["functions"], cz["cells"]
    key = a.what
    sel = []
    try:
        va = int(key, 16)
        if va < cz["meta"]["base"]:
            va += cz["meta"]["base"]
    except ValueError:
        va = None
    if va is not None:
        if f"{va:#x}" in fns:
            sel = [f"{va:#x}"]
        else:                                        # containing function, or a cell
            for k, r in fns.items():
                b = int(k, 16)
                spans = r.get("chunks") or [[b, b + r["size"]]]
                if any(lo <= va < hi for lo, hi in spans):
                    sel = [k]
                    break
            if not sel:
                a.va, a.all = key, False
                return cmd_cell(a)
    else:
        kl = key.lower()
        exact = [k for k, r in fns.items() if _label(r).lower() == kl or _label(r).lower().endswith("::" + kl)]
        sel = exact or [k for k, r in fns.items() if kl in _label(r).lower()]
    if not sel:
        print("nothing matches (gameplay functions only; try `cell <va>` for any data cell)")
        return 1
    for k in sel:
        r = fns[k]
        print(f"== fn {k}  {_label(r)}" + (f"::vf{r['vf']}" if "vf" in r else "") +
              f"  [{r['kind']}, {r['size']} B{'' if r['in_range'] else ', outside ranges'}]" +
              (f"  reached only via {r['callers_cls']} (depth {r['callers_depth']})" if r.get("callers_cls") else "") +
              (f"  !! LOW CONFIDENCE: sweep lost sync {r['resyncs']}x in this function" if r.get("resyncs") else ""))
        for c in r.get("cells", ()):
            print(_cell_line(c, cells[f"{c['cell']:#x}"]))
        for fi in r.get("fimms", ()):
            print(f"    {fi['va']:#x}  fimm    {fi['text'][:54]:54} = {fi['value']}f  imm bytes @ {fi['imm_va']:#x}"
                  + ("  (low interest)" if fi["low_interest"] else ""))
        for im in r.get("imms", ()):
            s = f"    {im['va']:#x}  imm     {im['text'][:54]:54} role={im['role']:6} src={im['src']}"
            if im.get("src_arg") is not None:
                s += f"[{im['src_arg']:#x}]"
            if im.get("src_call"):
                s += f" @{im['src_call']:#x}"
            if im.get("feeds"):
                s += f" -> {im['feeds']:#x} @{im['call']:#x}"
            if im.get("via"):
                s += f"  (used at {im['via']:#x}: {im['via_text']})"
            print(s)
        for g in r.get("getparam", ()):
            row = "dynamic" if g["row"] is None else g["row"]
            print(f"    {g['va']:#x}  level   call {g['helper']:#x}  row={row}" +
                  (f"  ({g['row_how']} @{g['row_site']:#x}: {g['row_text']})" if g.get("row_site") else ""))
        for at in r.get("attr_calls", ()):
            print(f"    {at['va']:#x}  attr    {'ATTR_get' if at.get('helper', 0x143EA8CB0) == 0x143EA8CB0 else 'attr_inner'} idx="
                  + (f"{at['idx']:#x}" if at["idx"] is not None else "dynamic"))
    return 0


def _evidence(ci):
    fl = []
    for b_ in ci.get("bases_near", ()):
        fl.append(f"{b_['how']}->{b_['base']:#x}:{b_['cls']}" + (f"(ends {b_['end']:#x})" if b_.get("end") else ""))
    ib_ = ci.get("imgbase_near")
    if ib_:
        fl.append(f"imgbase_table@{ib_['base']:#x}(+{ib_['dist']:#x}, {ib_['n_sites']} site(s), elem {ib_['elem_bytes']}B)")
    if ci.get("overlap_count"):
        o_ = ci["overlap_refs"][0]
        fl.append(f"overlap x{ci['overlap_count']} e.g. {o_['site']:#x}->{o_['target']:#x}/{o_['width']}B")
    if ci.get("rva32_hits"):
        fl.append(f"rva32_hits={ci['rva32_hits']}(advisory)")
    return fl


def cmd_private(a):
    cz = load_census(a)
    fns, cells = cz["functions"], cz["cells"]
    pref = (a.prefix or "").lower()
    want = {"private"} | ({"private_unproven"} if a.unproven else set()) | ({"vetoed"} if a.vetoed else set())
    rows = []
    for k, r in fns.items():
        lab = _label(r)
        if pref and pref not in lab.lower() and pref not in (r.get("callers_cls") or "").lower():
            continue
        for c in r.get("cells", ()):
            ci = cells[f"{c['cell']:#x}"]
            if ci["status"] in want and (a.all_kinds or ci["kind"] in ("f32", "f64")):
                rows.append((lab, k, c, ci))
    rows.sort(key=lambda x: (x[0].lstrip("~>"), x[1], x[2]["va"]))
    print(f"# {len(rows)} {'/'.join(sorted(want))} {'cells' if a.all_kinds else 'floats'}" + (f" matching '{a.prefix}'" if pref else ""))
    print("# PRIVATE = exactly one referrer in the whole image AND no other access overlaps the cell's bytes AND it is not inside a")
    print("#   lea'd/pointed-to string, vtable or array, not after an image-base table, read-only, aligned, in the literal pool.")
    print("# private_unproven = one referrer, nothing disproves it, but an array/table base with UNKNOWN extent sits just before it.")
    print("# Nothing static can see an address computed at run time (Denuvo). Treat PRIVATE as 'no static evidence against'.")
    print(f"# {'cell':14} {'value':>14} {'site':14} {'mnemonic':9} {'role':7} {'fn':14} class  status  [evidence]")
    for lab, k, c, ci in rows:
        fl = ([] if ci["status"] == "private" else [ci["status"].upper() + ":" + ",".join(ci.get("unproven", []) + ci.get("veto", []))])
        fl += _evidence(ci)
        if c.get("taint"):
            fl.append(f"taint={c['taint']}")
        if fns[k].get("resyncs"):
            fl.append("fn-low-confidence")
        print(f"{c['cell']:#x}  {_fmt_val(ci):>14} {c['va']:#x}  {c['mn']:9} {c['role']:7} {k:14} {lab}  {' '.join(fl)}")
    return 0


def cmd_cell(a):
    import numpy as np
    cz = load_census(a)
    base = cz["meta"]["base"]
    va = int(a.va, 16)
    if va < base:
        va += base
    ci = cz["cells"].get(f"{va:#x}")
    if ci:
        print(f"cell {va:#x} [{ci['section']}] {ci['kind']}={_fmt_val(ci)} width={ci.get('width')}  STATUS={ci['status']}  "
              f"refcount={ci['refcount']} writers={ci['writers']} "
              f"leas={ci['leas']} raw_unexplained={ci['raw_unexplained']} raw_noncode_hits={ci.get('raw_noncode_hits')} "
              f"ptr_refs={ci['ptr_refs']} rva32_hits={ci.get('rva32_hits')} "
              f"private={ci['private']} same_class_only={ci['same_class_only']} same_function_only={ci['same_function_only']}")
        if ci.get("veto"):
            print(f"   veto: {ci['veto']}")
        if ci.get("unproven"):
            print(f"   unproven: {ci['unproven']}")
        for e_ in _evidence(ci):
            print(f"   evidence: {e_}")
    else:
        print(f"cell {va:#x}: not referenced from gameplay code (or not a plausible constant); raw referrers:")
    z = np.load(paths(getattr(a, "tag", None))[1])
    idx = np.flatnonzero(z["targets"] == np.uint32(va - base))
    fns = cz["functions"]
    print(f"{len(idx)} referrers in the whole image:")
    kn = {0: "read", 1: "lea", 2: "WRITE", 3: "call/jmp"}
    lim = None if a.all else 60
    for i in idx[:lim].tolist():
        s = int(z["sites"][i]) + base
        f = int(z["site_fn"][i])
        r = fns.get(f"{f + base:#x}")
        print(f"   {s:#x}  {kn[int(z['kinds'][i])]:8} fn {f + base:#x}  " + (_label(r) if r else "(non-gameplay)" if f else "(no function)"))
    if lim and len(idx) > lim:
        print(f"   ... {len(idx) - lim} more (--all)")
    w = (ci or {}).get("width", 4)
    tg64 = z["targets"].astype(np.int64)
    r_ = va - base
    ov = np.flatnonzero((tg64 != r_) & (tg64 > r_ - 64) & (tg64 < r_ + w) & (z["kinds"] != 3)
                        & ((tg64 > r_) | ((z["kinds"] != 1) & (tg64 + z["widths"].astype(np.int64) > r_))))
    if len(ov):
        print(f"{len(ov)} OTHER direct accesses whose bytes overlap [{va:#x}, {va + w:#x}):")
        for i in ov[:20].tolist():
            print(f"   {int(z['sites'][i]) + base:#x}  -> {int(tg64[i]) + base:#x} / {int(z['widths'][i])} B  {kn[int(z['kinds'][i])]}")
    ib = z["ib"]
    if len(ib):
        m = np.flatnonzero((ib[:, 1] > r_ - IMGBASE_WINDOW) & (ib[:, 1] < r_ + w))
        if len(m):
            print(f"{len(m)} image-base-relative table operand(s) `[reg+idx*s+RVA]` with a base within {IMGBASE_WINDOW:#x} before the cell "
                  f"(index bound NOT analysed - the table may or may not reach the cell):")
            for i in m[:20].tolist():
                print(f"   {int(ib[i, 0]) + base:#x}  base {int(ib[i, 1]) + base:#x} (cell is +{r_ - int(ib[i, 1]):#x})  elem {int(ib[i, 2])} B  "
                      f"scale {int(ib[i, 3])}{'  lea' if ib[i, 4] else ''}{'' if z['ib_conf'][i] else '  [fn has no visible lea ImageBase]'}")
    return 0


def cmd_summary(a):
    cz = load_census(a)
    s = cz["summary"]
    if a.prefix:
        p = a.prefix.lower()
        s = dict(s, by_namespace={k: v for k, v in s["by_namespace"].items() if p in k.lower()},
                 by_class={k: v for k, v in s["by_class"].items() if p in k.lower()})
    print(format_summary(s, cz["meta"], top=None if a.prefix else 60))
    return 0


def cmd_ranges(a):
    cz = load_census(a)
    for lo, hi, n in cz["meta"]["ranges"]:
        print(f"{lo:#x}-{hi:#x}  {(hi - lo) / 1e6:6.2f} MB  {n} match:: vtable methods")
    return 0


# ----------------------------------------------------------------------------------------
# acceptance (hand-proven ground truth; never adjusted to pass)
# ----------------------------------------------------------------------------------------

def cmd_verify(a):
    """Acceptance checks against hand-proven ground truth of the STOCK exe. Where the exe disagrees
    the check FAILS and prints the real disassembly plus every tools/data/patches spec that
    rewrites that site. (Four expectations that used to circulate - 0x14401b3a7 on the 6.0f cell,
    imm 0x28 at 0x143c84d2e, 0.4f at 0x14401b3d6 - were recorded from a PATCHED build; they are
    replaced below by what the stock bytes really say.) On an --overlay census, a check whose site
    is rewritten by an applied overlay is reported N/A instead of being forced either way."""
    import numpy as np
    cz = load_census(a)
    meta = cz["meta"]
    base = meta["base"]
    fns, cells = cz["functions"], cz["cells"]
    z = np.load(paths(getattr(a, "tag", None))[1])
    tg, st = z["targets"], z["sites"]
    pdir = REPO / "tools" / "data" / "patches"
    ov = []
    for l in meta.get("overlays") or []:
        if str(pdir / l["spec"]) not in ov:
            ov.append(str(pdir / l["spec"]))
    img = PatchedImage(meta["exe"], ov)
    state = f"{'stock' if not ov else 'stock + overlay ' + '+'.join(Path(o).stem for o in ov)} exe (sha1 {meta['sha1'][:12]}, pristine={meta['pristine']})"
    print(f"verifying census of: {state}\n")
    res = []

    def refs(cell):
        return set((st[tg == np.uint32(cell - base)].astype(np.int64) + base).tolist())

    applied = [(l["va"], l["spec"]) for l in (meta.get("overlays") or []) if l["status"] in ("applied", "already")]

    def check(name, ok, detail, sites=()):
        hit = sorted({sp for va_, sp in applied for s_ in sites if va_ - 8 <= s_ < va_ + 16})
        if hit and not ok:
            res.append(dict(test=name, passed=None, detail=f"N/A: site rewritten by overlay {hit}. {detail}"))
            print(f"[ N/A] {name}\n       stock expectation; the site is rewritten by overlay {hit}\n       {detail}")
            return
        res.append(dict(test=name, passed=bool(ok), detail=f"[{state.split(' (')[0]}] {detail}"))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       {detail}")

    def site_cell(site):
        """(cell va, f32 there) for the RIP operand of the instruction at `site`, from the REFS table."""
        t_ = tg[st == np.uint32(site - base)]
        if not len(t_):
            return None, None
        c_ = int(t_[0]) + base
        return c_, struct.unpack("<f", img.read(c_ - base, 4))[0]

    # 0 -- the outputs were produced by THIS tool
    check("census outputs were built by this version of tools/exe_census.py", not meta.get("_stale"),
          f"meta.tool_sha1={str(meta.get('tool_sha1'))[:12]} running={tool_sha1()[:12]} built={meta.get('built')}")

    def fn_containing(va):
        for k, r in fns.items():
            b_ = int(k, 16)
            if any(lo <= va < hi for lo, hi in (r.get("chunks") or [[b_, b_ + r["size"]]])):
                return k, r
        return None, None

    def explain(va, n=1):
        """actual disassembly at va + every patch spec that rewrites it."""
        out = []
        for ins in img.disasm(va - base, 16)[:n]:
            t = next(iter(img.rip_targets(ins)), None)
            note = ""
            if t is not None:
                note = f"  ; -> {base + t:#x} = {struct.unpack('<f', img.read(t, 4))[0]:g}f"
            out.append(f"{ins.address:#x}: {ins.bytes.hex()}  {ins.mnemonic} {ins.op_str}{note}")
        hits = []
        for spec in sorted(pdir.glob("*.json")):
            j = json.loads(spec.read_text(encoding="utf-8"))
            for pt in (j.get("patches") if isinstance(j, dict) else j) or []:
                pva = int(pt["va"], 16) if "va" in pt else base + int(pt["module_offset"], 16)
                if pva <= va < pva + len(_hex(pt["expect"])):
                    hits.append(f"{spec.name}:'{pt.get('name', '')[:40]}' {pt['expect']}->{pt['patch']}")
        return " | ".join(out) + ("  || rewritten by: " + "; ".join(hits) if hits else "")

    # 1 -- the private canary
    r = refs(0x146BC6B14); ci = cells.get("0x146bc6b14", {})
    k, f = fn_containing(0x144176A3D)
    callers = (f or {}).get("callers", [])
    in_vf2 = k == "0x1441761c0" or (callers and all(fn_containing(c)[0] == "0x1441761c0" for c in callers))
    check("cell 0x146bc6b14 (44.5f): refcount == 1 -> private (ActionFeint vf2 0x1441761c0, site 0x144176a3d)",
          len(r) == 1 and 0x144176A3D in r and ci.get("private") is True and ci.get("value") == 44.5 and in_vf2,
          f"refcount={len(r)} sites={[hex(x) for x in sorted(r)][:4]} value={ci.get('value')} status={ci.get('status')} "
          f"veto={ci.get('veto')} unproven={ci.get('unproven')} evidence={_evidence(ci) if ci else None} "
          f"raw_unexplained={ci.get('raw_unexplained')} ptr_refs={ci.get('ptr_refs')}. Precise location: .pdata puts the site in "
          f"fn {k} [{_label(f) if f else None}], a separate NON-virtual function (own prolog + stack cookie) whose only direct "
          f"caller(s) {[hex(c) for c in callers]} lie inside ActionFeint vf2 0x1441761c0 (vf2 itself ends at 0x14417652a).")

    # 2 -- shared pool cells
    r = refs(0x145AB244C)
    v = struct.unpack("<f", img.read(0x145AB244C - base, 4))[0]
    check("cell 0x145ab244c (6.0f): about 647 refs (+/-15%) and lists site 0x143ed79bf",
          abs(len(r) - 647) <= 0.15 * 647 and v == 6.0 and 0x143ED79BF in r,
          f"refcount={len(r)} ({100.0 * (len(r) - 647) / 647:+.1f}%) value={v:g} 0x143ed79bf listed={0x143ED79BF in r}")
    c_, v_ = site_cell(0x14401B3A7)
    check("STOCK: site 0x14401b3a7 loads cell 0x146b3cfb0 = 4.25f (Gaussian sigma scale), NOT the 6.0f cell",
          c_ == 0x146B3CFB0 and v_ == 4.25 and 0x14401B3A7 not in r,
          f"site -> {c_ and hex(c_)} = {v_}f; listed among the 6.0f referrers={0x14401B3A7 in r}. "
          f"Actual instruction: {explain(0x14401B3A7)}", sites=(0x14401B3A7,))
    for cell, val, want in ((0x145B28A88, 0.3, 895), (0x147850490, 2.0, 1995), (0x146B1FF34, 6.5, 60),
                            (0x146744828, 1.3, 95), (0x145A8DD84, 60.0, 1512)):
        r = refs(cell)
        v = struct.unpack("<f", img.read(cell - base, 4))[0]
        ci = cells.get(f"{cell:#x}", {})
        check(f"cell {cell:#x} ({val}f): about {want} refs (+/-15%)",
              abs(len(r) - want) <= 0.15 * want and abs(v - val) < 1e-6,
              f"refcount={len(r)} ({100.0 * (len(r) - want) / want:+.1f}% vs the earlier brute scan) value={v:g} "
              f"private={ci.get('private')} distinct owner classes>={len(ci.get('classes', []))}")

    # 3 -- RNG threshold immediate
    k, f = fn_containing(0x143C84D2E)
    im = [i for i in (f or {}).get("imms", ()) if i["va"] == 0x143C84D2E]
    check("site 0x143c84d2e (cmp eax,imm8 after RandInt call 0x143c84d22) appears as an RNG-threshold immediate",
          bool(im) and im[0]["src"] == "randint" and im[0]["src_call"] == 0x143C84D22 and im[0]["role"] == "gate",
          (f"fn {k}: '{im[0]['text']}' role={im[0]['role']} src={im[0]['src']}(max={im[0].get('src_arg')}) "
           f"call @{im[0]['src_call']:#x}, imm byte @ {im[0].get('imm_va', 0):#x}") if im else f"not found in fn {k}")
    check("STOCK: ... and that instruction is `cmp eax,0x1e` (30)", bool(im) and im[0]["imm"] == 0x1E,
          (f"imm={im[0]['imm']:#x}. " if im else "") + f"Actual instruction: {explain(0x143C84D2E)}", sites=(0x143C84D2E,))

    # 4 -- percent-roll args
    k, f = fn_containing(0x143F0F3B1)
    got = {i["va"]: i for i in (f or {}).get("imms", ()) if i.get("feeds") == 0x143EAFD30}
    ok = all(v_ in got for v_ in (0x143F0F3B1, 0x143F0F3CA)) and got[0x143F0F3B1]["imm"] == 0x3C and got[0x143F0F3CA]["imm"] == 0x50
    check("sites 0x143f0f3b1 'mov edx,0x3c' and 0x143f0f3ca 'mov edx,0x50' feed PercentRoll 0x143eafd30", ok,
          f"fn {k} [{_label(f) if f else None}]: " + ("; ".join(f"{v_:#x} '{got[v_]['text']}' -> call @{got[v_]['call']:#x}"
                                                          for v_ in (0x143F0F3B1, 0x143F0F3CA) if v_ in got) or "none"))

    # 5 -- GetParam rows
    for site, row, fnva in ((0x144193A21, 2, "0x144193150"), (0x143D77837, 1, None)):
        k, f = fn_containing(site)
        g = [x for x in (f or {}).get("getparam", ()) if x["va"] == site]
        ok = bool(g) and g[0]["row"] == row and (fnva is None or k == fnva)
        check(f"GetParam 0x1442e48f0 row {row} at {site:#x}" + (f" (ActionPress fn {fnva})" if fnva else ""), ok,
              (f"fn {k} [{_label(f)}]: row={g[0]['row']} via {g[0].get('row_how')} @{g[0].get('row_site', 0):#x} '{g[0].get('row_text')}'"
               if g else f"no GetParam record in fn {k}"))

    # 6 -- kick-error builder
    f = fns.get("0x14401a900")
    cs = {c["va"]: c for c in (f or {}).get("cells", ())}
    det = "fn 0x14401a900 missing from inventory"
    if f is not None:
        det = f"fn 0x14401a900 [{_label(f)}; {f['kind']}, {f['size']} B, {len(cs)} constant refs, {len(f.get('imms', ()))} imms]"
        for s_ in (0x14401B3DF, 0x14401B3D6):
            if s_ in cs:
                ci = cells[f"{cs[s_]['cell']:#x}"]
                det += f"; {s_:#x} {cs[s_]['mn']} -> {cs[s_]['cell']:#x} = {_fmt_val(ci)} (refcount {ci['refcount']}, private={ci['private']})"
    check("non-virtual kick-error builder 0x14401a900 is in the inventory with constants at sites 0x14401b3df and 0x14401b3d6",
          f is not None and 0x14401B3DF in cs and 0x14401B3D6 in cs, det)
    for s_, want_cell, want_val in ((0x14401B3DF, 0x14676E980, 22.5), (0x14401B3D6, 0x145B28A88, 0.3)):
        c_, v_ = site_cell(s_)
        in_census = s_ in cs and cs[s_]["cell"] == want_cell and abs(cells[f"{want_cell:#x}"]["value"] - want_val) < 1e-6
        check(f"STOCK: kick-error builder site {s_:#x} -> cell {want_cell:#x} = {want_val}f",
              c_ == want_cell and v_ is not None and abs(v_ - want_val) < 1e-6 and in_census,
              f"site -> {c_ and hex(c_)} = {v_}f (census agrees={in_census}). Actual instruction: {explain(s_)}", sites=(s_,))

    n = sum(1 for x in res if x["passed"])
    na = sum(1 for x in res if x["passed"] is None)
    print(f"\n{n}/{len(res) - na} passed" + (f" ({na} N/A under overlay)" if na else "") + f" on the {state}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0 if n == len(res) - na else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--tag", help="query/write the census built with --overlay (default: stock)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("--jobs", type=int, default=0)
    p.add_argument("--gaps-everywhere", action="store_true", help="also sweep non-.pdata bytes of .impdata (Denuvo; slow, noisy)")
    p.add_argument("--overlay", action="append", metavar="SPEC.json",
                   help="overlay a tools/data/patches spec IN MEMORY (repeatable, in apply order) to census the installed build")
    p = sub.add_parser("show"); p.add_argument("what")
    p = sub.add_parser("private"); p.add_argument("prefix", nargs="?"); p.add_argument("--all-kinds", action="store_true")
    p.add_argument("--unproven", action="store_true", help="also list private_unproven cells, with the evidence")
    p.add_argument("--vetoed", action="store_true", help="also list single-referrer cells that were vetoed, with the reason")
    p = sub.add_parser("cell"); p.add_argument("va"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("summary"); p.add_argument("prefix", nargs="?")
    sub.add_parser("ranges")
    p = sub.add_parser("verify"); p.add_argument("--json")
    a = ap.parse_args()
    return {"build": cmd_build, "show": cmd_show, "private": cmd_private, "cell": cmd_cell,
            "summary": cmd_summary, "ranges": cmd_ranges, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
