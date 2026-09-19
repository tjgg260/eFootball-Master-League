"""Scratch helper: read-only disassembly / xref / pdata tooling over the PRISTINE image."""
import sys, struct, os
import numpy as np
import capstone
from pathlib import Path
REPO = Path(r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b")
sys.path.insert(0, str(REPO / "tools"))
import cave_alloc
from cave_alloc import Image
SCR = Path(__file__).resolve().parent
PRISTINE = Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")
INSTALLED = Path(r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe")
BASE = 0x140000000

_img = None
def img(path=PRISTINE):
    global _img
    if _img is None or _img.path != Path(path):
        _img = Image(path)
    return _img

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True

_ranges = None
def merged_ranges(im=None):
    global _ranges
    if _ranges is not None: return _ranges
    im = im or img()
    cache = SCR / "pdata_merged.npz"
    if cache.exists():
        z = np.load(cache); _ranges = (z["b"], z["e"]); return _ranges
    b, e = cave_alloc.pdata_ranges(im)
    mb, me = [], []
    cb, ce = int(b[0]), int(e[0])
    for x, y in zip(b[1:], e[1:]):
        x, y = int(x), int(y)
        if x <= ce:
            ce = max(ce, y)
        else:
            mb.append(cb); me.append(ce); cb, ce = x, y
    mb.append(cb); me.append(ce)
    _ranges = (np.array(mb, dtype=np.int64), np.array(me, dtype=np.int64))
    np.savez(cache, b=_ranges[0], e=_ranges[1])
    return _ranges

def func_range(va):
    b, e = merged_ranges()
    i = np.searchsorted(b, va, side="right") - 1
    if i < 0 or va >= e[i]: return None
    return int(b[i]), int(e[i])

def read(va, n, im=None):
    return (im or img()).read_va(va, n)

def disasm(va, n=None, end=None, im=None):
    if end is None and n is None:
        r = func_range(va)
        end = r[1] if r else va + 0x400
    if n is None: n = end - va
    return list(md.disasm(read(va, n, im), va))

def fmt(ins):
    return f"{ins.address:#x}: {ins.mnemonic} {ins.op_str}"

def dump(va, n=None, end=None, im=None, out=None):
    lines = [fmt(i) for i in disasm(va, n, end, im)]
    s = "\n".join(lines)
    if out: Path(out).write_text(s)
    return s

# -------- xref index (calls/jmps rel32 + rip-relative lea/mov) over .xcode
_xr = None
def xref_index():
    global _xr
    if _xr is not None: return _xr
    cache = SCR / "xrefs_pristine.npz"
    if cache.exists():
        z = np.load(cache); _xr = {k: z[k] for k in z.files}; return _xr
    im = img(); sec = im.xcode()
    n = min(sec["vsize"], sec["rsize"])
    blob = np.frombuffer(im.data, dtype=np.uint8, count=n, offset=sec["raw"])
    base = BASE + sec["rva"]
    # E8 / E9 rel32
    pos = np.where((blob[:-5] == 0xE8) | (blob[:-5] == 0xE9))[0]
    disp = blob[pos[:,None] + np.arange(1,5)].astype(np.uint8).view(np.uint8)
    d = (disp[:,0].astype(np.int64) | (disp[:,1].astype(np.int64)<<8) | (disp[:,2].astype(np.int64)<<16) | (disp[:,3].astype(np.int64)<<24))
    d = np.where(d >= 1<<31, d - (1<<32), d)
    tgt = base + pos + 5 + d
    kind = blob[pos]
    ok = (tgt >= base) & (tgt < base + n)
    call_pos, call_tgt, call_kind = base + pos[ok], tgt[ok], kind[ok]
    # rip-relative: opcode byte followed by modrm with mod=00 rm=101 (05,0d,15,1d,25,2d,35,3d)
    # handle 1-byte opcodes 8D,8B,89,3B,39,FF,C7? and 0F-prefixed 2-byte (10,11,28,29,2E,2F,58,59,5C,5E,B6,B7,BE,BF,10..)
    modrm_ok = np.isin(blob, [0x05,0x0d,0x15,0x1d,0x25,0x2d,0x35,0x3d])
    one = np.isin(blob, [0x8d,0x8b,0x89,0x3b,0x39,0xff,0x8a,0x88,0x80,0x83,0x81,0x38,0x3a,0x63,0xf6,0xf7,0xc7,0xc6])
    # position of opcode i with modrm at i+1 -> disp at i+2..i+5, next at i+6
    p1 = np.where(one[:-6] & modrm_ok[1:-5])[0]
    two = (blob[:-7] == 0x0f) & modrm_ok[2:-5]
    p2 = np.where(two)[0]
    def rip(p, oplen):
        k = p + oplen
        dd = blob[k[:,None] + np.arange(4)]
        v = (dd[:,0].astype(np.int64) | (dd[:,1].astype(np.int64)<<8) | (dd[:,2].astype(np.int64)<<16) | (dd[:,3].astype(np.int64)<<24))
        v = np.where(v >= 1<<31, v - (1<<32), v)
        t = base + k + 4 + v
        # immediates after disp (for 83/81/c7/c6/80) shift the target; we accept small error by also indexing imm variants
        return base + p, t
    r1p, r1t = rip(p1, 2); r2p, r2t = rip(p2, 3)
    # imm8 forms (80 /x, 83 /x, c6 ...) => +1, imm32 (81, c7) => +4
    imm1 = np.isin(blob[p1], [0x80,0x83,0xc6]); imm4 = np.isin(blob[p1], [0x81,0xc7])
    r1t = r1t + imm1 + 4*imm4
    rp = np.concatenate([r1p, r2p]); rt = np.concatenate([r1t, r2t])
    ok = (rt >= BASE) & (rt < BASE + 0x10000000)
    rp, rt = rp[ok], rt[ok]
    _xr = dict(call_pos=call_pos, call_tgt=call_tgt, call_kind=call_kind, ref_pos=rp, ref_tgt=rt)
    # sort by target
    o = np.argsort(call_tgt); _xr["call_pos"], _xr["call_tgt"], _xr["call_kind"] = call_pos[o], call_tgt[o], call_kind[o]
    o = np.argsort(rt); _xr["ref_pos"], _xr["ref_tgt"] = rp[o], rt[o]
    np.savez(cache, **_xr)
    return _xr

def callers(va):
    x = xref_index()
    lo = np.searchsorted(x["call_tgt"], va, "left"); hi = np.searchsorted(x["call_tgt"], va, "right")
    return [(int(p), "call" if k == 0xE8 else "jmp") for p, k in zip(x["call_pos"][lo:hi], x["call_kind"][lo:hi])]

def refs(va):
    x = xref_index()
    lo = np.searchsorted(x["ref_tgt"], va, "left"); hi = np.searchsorted(x["ref_tgt"], va, "right")
    return [int(p) for p in x["ref_pos"][lo:hi]]

def func_of(va):
    r = func_range(va)
    return r[0] if r else None

def calls_in(va):
    out = []
    for i in disasm(va):
        if i.mnemonic == "call":
            out.append((i.address, i.op_str))
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"); ap.add_argument("addr"); ap.add_argument("n", nargs="?", type=lambda s:int(s,0))
    a = ap.parse_args(); va = int(a.addr, 0)
    if a.cmd == "dis":
        print(dump(va, a.n))
    elif a.cmd == "range":
        print(func_range(va))
    elif a.cmd == "callers":
        for p, k in callers(va): print(f"{p:#x} {k} in func {func_of(p):#x}" if func_of(p) else f"{p:#x} {k}")
    elif a.cmd == "refs":
        for p in refs(va): print(f"{p:#x} in func {func_of(p) and hex(func_of(p))}")
    elif a.cmd == "calls":
        for a_, o in calls_in(va): print(f"{a_:#x}: call {o}")

# ---------- annotation from build/exe_map.json
_names = None
def names():
    global _names
    if _names is not None: return _names
    import json
    m = json.load(open(REPO / "build" / "exe_map.json"))
    vt, meth = {}, {}
    for cls, ents in m["classes"].items():
        for e in ents:
            vt[BASE + e["vftable"]] = cls
            for i, mv in enumerate(e["methods"]):
                meth.setdefault(BASE + mv, []).append(f"{cls}::vf{i}")
    _names = (vt, meth); return _names

def annotate(ins):
    vt, meth = names()
    s = fmt(ins); notes = []
    if ins.mnemonic in ("call", "jmp") and ins.op_str.startswith("0x"):
        t = int(ins.op_str, 16)
        if t in meth: notes.append(",".join(meth[t][:3]))
    for op in ins.operands:
        if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
            t = op.mem.disp + ins.address + ins.size
            if t in vt: notes.append("VT " + vt[t])
            elif t in meth: notes.append(",".join(meth[t][:2]))
            else: notes.append(f"-> {t:#x}")
    return s + ("   ; " + " | ".join(notes) if notes else "")

def adump(va, n=None, end=None, im=None, out=None):
    s = "\n".join(annotate(i) for i in disasm(va, n, end, im))
    if out: Path(out).write_text(s)
    return s

# ---------- override func_range with chained-unwind extents
def func_range(va):
    import funcs
    r = funcs.func_root(va)
    if r is None: return None
    ch = sorted(funcs.func_chunks(r))
    return (ch[0][0], max(e for b, e in ch))
def func_of(va):
    r = func_range(va); return r[0] if r else None
