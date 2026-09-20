import struct, sys
PRIS = r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE"
BASE = 0x140000000
_d = open(PRIS,'rb').read()
# parse PE sections
pe = struct.unpack_from('<I', _d, 0x3c)[0]
nsec = struct.unpack_from('<H', _d, pe+6)[0]
opt = struct.unpack_from('<H', _d, pe+20)[0]
secs=[]
off = pe+24+opt
for i in range(nsec):
    e = _d[off+i*40:off+(i+1)*40]
    name = e[:8].rstrip(b'\0').decode('latin1')
    vsz, va, rsz, rof = struct.unpack_from('<IIII', e, 8)
    ch = struct.unpack_from('<I', e, 36)[0]
    secs.append((name, va, vsz, rof, rsz, ch))

def sec_of(vaddr):
    rva = vaddr - BASE
    for s in secs:
        if s[1] <= rva < s[1]+max(s[2],s[4]): return s
    return None

def read(vaddr, n):
    rva = vaddr - BASE
    for name, va, vsz, rof, rsz, ch in secs:
        if va <= rva < va+max(vsz,rsz):
            o = rva - va
            if o >= rsz: return b'\0'*n
            avail = rsz - o
            b = _d[rof+o: rof+o+min(n,avail)]
            return b + b'\0'*(n-len(b))
    raise ValueError(hex(vaddr))

def u32(v): return struct.unpack('<I', read(v,4))[0]
def u64(v): return struct.unpack('<Q', read(v,8))[0]
def f32(v): return struct.unpack('<f', read(v,4))[0]

from capstone import *
md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail=True
def dis(vaddr, n=20, count=0):
    code = read(vaddr, n)
    out=[]
    for i in md.disasm(code, vaddr):
        out.append("0x%x %-24s %s %s" % (i.address, i.bytes.hex(), i.mnemonic, i.op_str))
        if count and len(out)>=count: break
    return "\n".join(out)
