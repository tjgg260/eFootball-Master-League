"""Depth-bounded forward call closure over chained-unwind function extents; report RNG reach."""
import sys; sys.path.insert(0,'tools')
import bpx, funcs, capstone
RNG={0x144345d90,0x144345e00,0x144345e50,0x144345eb0,0x1443461a0}
_calls={}
def direct_calls(root):
    if root in _calls: return _calls[root]
    out=set()
    for b,e in funcs.func_chunks(root):
        try: ins=bpx.disasm(b,end=e)
        except Exception: continue
        for i in ins:
            if i.mnemonic in ('call','jmp') and i.op_str.startswith('0x'):
                t=int(i.op_str,16)
                if 0x140000000<=t<0x149000000: out.add(t)
    _calls[root]=out
    return out
def closure(start, maxdepth=6, cap=20000):
    r0=funcs.func_root(start) or start
    seen={r0}; frontier=[r0]; hits=[]
    for d in range(1,maxdepth+1):
        nxt=[]
        for f in frontier:
            for t in direct_calls(f):
                if t in RNG: hits.append((d,f,t))
                r=funcs.func_root(t) or t
                if r in RNG: hits.append((d,f,r))
                if r not in seen and len(seen)<cap:
                    seen.add(r); nxt.append(r)
        frontier=nxt
        if hits: return len(seen), min(h[0] for h in hits), hits[:6]
        if not frontier: break
    return len(seen), None, []
if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('addrs',nargs='+'); ap.add_argument('--depth',type=int,default=6)
    a=ap.parse_args()
    for s in a.addrs:
        va=int(s,0)
        n,d,h=closure(va,a.depth)
        print(f"{va:#x}: explored {n}, RNG depth {d}, e.g. {[(x[0],hex(x[1]),hex(x[2])) for x in h[:3]]}")
