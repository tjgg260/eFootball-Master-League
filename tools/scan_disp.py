import sys, struct
sys.path.insert(0,'tools')
import bpx, numpy as np, capstone
im=bpx.img()
def scan(disp, lo=0x143000000, hi=0x146000000, mnem=None):
    sec=im.xcode(); n=min(sec['vsize'],sec['rsize'])
    blob=np.frombuffer(im.data,dtype=np.uint8,count=n,offset=sec['raw'])
    base=bpx.BASE+sec['rva']
    pat=np.frombuffer(struct.pack('<i',disp),dtype=np.uint8)
    # find all 4-byte occurrences
    cand=np.where((blob[:-3]==pat[0])&(blob[1:-2]==pat[1])&(blob[2:-1]==pat[2])&(blob[3:]==pat[3]))[0]
    out=[]
    for c in cand:
        va=base+int(c)
        # try to decode an instruction starting up to 10 bytes earlier whose length covers disp
        for back in range(2,12):
            s=va-back
            if s<lo or s>hi: continue
            try:
                ins=next(bpx.md.disasm(im.read_va(s,16),s))
            except StopIteration:
                continue
            if ins.address+ins.size< va+4: continue
            ok=False
            for op in ins.operands:
                if op.type==capstone.x86.X86_OP_MEM and op.mem.disp==disp and op.mem.base!=capstone.x86.X86_REG_RIP:
                    ok=True
            if ok:
                out.append((s,bpx.fmt(ins)))
                break
    return out
if __name__=='__main__':
    d=int(sys.argv[1],0)
    lo=int(sys.argv[2],0) if len(sys.argv)>2 else 0x140000000
    hi=int(sys.argv[3],0) if len(sys.argv)>3 else 0x146000000
    for va,s in scan(d,lo,hi):
        f=bpx.func_of(va)
        print(f"{s}   [fn {hex(f) if f else '?'}]")
