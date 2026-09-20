import sys; sys.path.insert(0,'tools')
import bpx, funcs, numpy as np, capstone
im=bpx.img()
roots=sorted(set(funcs.ROOT.tolist()))
lo,hi=0x143c00000,0x145800000
hits=[]
for r in roots:
    if not (lo<=r<hi): continue
    have9=have12=False
    for b,e in funcs.func_chunks(r):
        try: ins=bpx.disasm(b,end=e)
        except Exception: continue
        for i in ins:
            if i.mnemonic in ('shl','sal') and i.op_str.endswith(', 9'): have9=True
            if i.mnemonic in ('shl','sal') and (i.op_str.endswith(', 0xc')): have12=True
    if have9 and have12:
        hits.append(r)
print(len(hits))
for h in hits: print(hex(h))
