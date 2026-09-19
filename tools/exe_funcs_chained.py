"""True function extents from .pdata + chained UNWIND_INFO (UNW_FLAG_CHAININFO)."""
import numpy as np, struct, bpx
from pathlib import Path
SCR = Path(__file__).resolve().parent
def build():
    cache = SCR / "funcs_chained.npz"
    if cache.exists():
        z = np.load(cache); return z["beg"], z["end"], z["root"]
    im = bpx.img(); d = im.data
    off = im.rva_to_file(im.pdata_rva); n = im.pdata_size // 12
    rf = np.frombuffer(d, dtype=np.uint32, count=n*3, offset=off).reshape(n,3)
    beg, end, root = [], [], []
    for b, e, u in rf:
        if b == 0: continue
        r = int(b)
        # follow chain
        for _ in range(8):
            uo = im.rva_to_file(int(u))
            if uo is None: break
            flags = d[uo] >> 3
            if not (flags & 4): break
            cnt = d[uo+2]
            p = uo + 4 + ((cnt + 1) & ~1) * 2
            pb, pe, pu = struct.unpack_from("<III", d, p)
            r = int(pb); u = pu
        beg.append(int(b)); end.append(int(e)); root.append(r)
    beg = np.array(beg, dtype=np.int64) + bpx.BASE; end = np.array(end, dtype=np.int64) + bpx.BASE; root = np.array(root, dtype=np.int64) + bpx.BASE
    o = np.argsort(beg); beg, end, root = beg[o], end[o], root[o]
    np.savez(cache, beg=beg, end=end, root=root)
    return beg, end, root
BEG, END, ROOT = build()
def chunk_of(va):
    i = np.searchsorted(BEG, va, "right") - 1
    if i < 0 or va >= END[i]: return None
    return i
def func_root(va):
    i = chunk_of(va)
    return None if i is None else int(ROOT[i])
def func_chunks(root):
    idx = np.where(ROOT == root)[0]
    return [(int(BEG[i]), int(END[i])) for i in idx]
def func_range(va):
    """(begin,end) of the primary chunk (the one starting at root)."""
    r = func_root(va)
    if r is None: return None
    for b, e in func_chunks(r):
        if b == r: return (b, e)
    return None
if __name__ == "__main__":
    import sys
    print(len(BEG), "chunks;", len(set(ROOT.tolist())), "roots")
    for a in sys.argv[1:]:
        va = int(a, 0); r = func_root(va); print(hex(va), "root", hex(r) if r else None, [(hex(b),hex(e)) for b,e in func_chunks(r)] if r else "")
