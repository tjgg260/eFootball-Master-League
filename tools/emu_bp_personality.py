#!/usr/bin/env python3
from __future__ import annotations
"""emu_bp_personality.py - match::ai::bp::Personality::update (0x145663920) and the carrier-brain RNG,
executed as the game's own bytes under Unicorn (ANALYSIS ONLY - reads eFootball.exe, writes nothing).

    python tools/emu_bp_personality.py model [p|i] [N]   # closed-form model vs N random worlds (both ability
                                                          # arrays, 73 cards, 3 style masks, role) - expect 0 mismatches
    python tools/emu_bp_personality.py probe             # which style/card/role bits move which Personality field
    python tools/emu_bp_personality.py rng               # the game's rand() under each seeding pattern the carrier brain uses

Personality lives at BallPlayer+0x41f8 = {vtable, 8 floats P0..P7}; update(this, match, playerRef=BP+0x18, BP+0xb0)
reads ability array A (playerData+0x394, getter 0x1442dd650) and B (+0x394+0x3d, getter 0x1442dd5b0), the 73 skill-card
bits at R+0xC0, the in/out-possession style masks R+0xCC / R+0xD0, the 7 COM/AI flags R+0xD4 and the role code at
playerRef+0x18. Match ability index = DATA_PARAMETER enum + 7 (tools/emu_enum_names.py):
0x14 OFFENSE_DECISION 0x18 TRAP 0x19 BALL_TOUCH 0x1a SHOT 0x1c LONG_PASS 0x1d HEADING 0x27 R_FOOT_ACC(0..3)
0x28 SPEED 0x29 BODY_BALANCE 0x2c AGILITY 0x36 (0..3, unnamed).
Re-run after every Konami patch; addresses are for the 2026-09 build. Derived from the scratch work of 2026-09-18/19.
"""
import sys, struct, random, mmap, json, os, bisect
from pathlib import Path
#!/usr/bin/env python3
"""bpcore — shared analysis core for match::ai::bp decode (ANALYSIS ONLY, read-only)."""
import mmap, struct, json, os, bisect
from pathlib import Path

PRISTINE = Path(r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE")
INSTALLED = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
REPO = Path(r"C:\Users\tjgg2\Downloads\eFootball Master League\.claude\worktrees\dt270-full-decode-12718b")

class Img:
    def __init__(self, path=PRISTINE):
        self.path = Path(path)
        self.f = open(self.path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        d = self.m[:0x2000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.secs = []
        for i in range(nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            ch = struct.unpack_from("<I", s, 36)[0]
            self.secs.append(dict(name=s[:8].rstrip(b"\0").decode(), va=va, vsize=vsize,
                                  raw=raw, rsize=rsize, exec=bool(ch & 0x20000000)))
        self.size_of_image = max(s["va"] + s["vsize"] for s in self.secs)
        # data dirs: exception dir is index 3
        dd = pe + 24 + 112  # optional header magic PE32+ : data dir at offset 112
        self.exc_rva, self.exc_size = struct.unpack_from("<II", d, dd + 3 * 8)
        self._md = None
        self._pdata = None
        self._starts = None

    def rva2off(self, r):
        for s in self.secs:
            if s["va"] <= r < s["va"] + s["vsize"]:
                o = r - s["va"]
                return s["raw"] + o if o < s["rsize"] else None
        return None

    def va_ok(self, va):
        r = va - self.base
        return 0 < r < self.size_of_image and self.rva2off(r) is not None

    def read_va(self, va, n):
        o = self.rva2off(va - self.base)
        if o is None:
            return None
        return bytes(self.m[o:o + n])

    def u8(self, va):  return struct.unpack("<B", self.read_va(va,1))[0]
    def u32(self, va): return struct.unpack("<I", self.read_va(va, 4))[0]
    def i32(self, va): return struct.unpack("<i", self.read_va(va, 4))[0]
    def u64(self, va): return struct.unpack("<Q", self.read_va(va, 8))[0]
    def f32(self, va): return struct.unpack("<f", self.read_va(va, 4))[0]

    def sect(self, va):
        r = va - self.base
        for s in self.secs:
            if s["va"] <= r < s["va"] + s["vsize"]:
                return s["name"]
        return None

    @property
    def md(self):
        if self._md is None:
            import capstone
            self._md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            self._md.detail = True
        return self._md

    # ---- merged .pdata function ranges ----
    def pdata(self):
        if self._pdata is not None:
            return self._pdata
        off = self.rva2off(self.exc_rva)
        n = self.exc_size // 12
        raw = self.m[off:off + n * 12]
        ents = []
        for i in range(n):
            s, e, u = struct.unpack_from("<III", raw, i * 12)
            if s and e > s:
                ents.append((s, e))
        ents.sort()
        merged = []
        for s, e in ents:
            if merged and s <= merged[-1][1]:
                if e > merged[-1][1]:
                    merged[-1][1] = e
            else:
                merged.append([s, e])
        self._pdata = [(self.base + s, self.base + e) for s, e in merged]
        self._starts = [a for a, b in self._pdata]
        return self._pdata

    def func_range(self, va):
        self.pdata()
        i = bisect.bisect_right(self._starts, va) - 1
        if i < 0:
            return None
        s, e = self._pdata[i]
        if s <= va < e:
            return (s, e)
        return None

    # ---- disasm a function (linear over its merged pdata range) ----
    def func_insns(self, va, cap=0x40000):
        r = self.func_range(va)
        if r is None:
            # fall back: linear until int3 int3 / ret-then-align
            data = self.read_va(va, 0x800)
            out = []
            for ins in self.md.disasm(data, va):
                out.append(ins)
                if ins.mnemonic in ("ret", "jmp") :
                    break
                if ins.mnemonic == "int3":
                    break
            return out
        s, e = r
        e = min(e, s + cap)
        data = self.read_va(s, e - s)
        return list(self.md.disasm(data, s))

    def insns_at(self, va, n=60):
        data = self.read_va(va, 16 * n + 32)
        out = []
        for ins in self.md.disasm(data, va):
            out.append(ins)
            if len(out) >= n:
                break
        return out


def direct_calls(img, va):
    """return (calls, indirect_count, indirect_details) for the function containing va"""
    import capstone
    calls = set()
    ind = []
    for ins in img.func_insns(va):
        if ins.mnemonic in ("call", "jmp"):
            op = ins.operands[0] if ins.operands else None
            if op is None:
                continue
            if op.type == capstone.x86.X86_OP_IMM:
                t = op.imm
                if img.va_ok(t):
                    if ins.mnemonic == "call":
                        calls.add(t)
                    else:
                        # tail jump outside function range = tail call
                        r = img.func_range(va)
                        if r and not (r[0] <= t < r[1]):
                            calls.add(t)
            else:
                ind.append((ins.address, ins.mnemonic + " " + ins.op_str))
    return calls, len(ind), ind


def closure(img, roots, depth=12, limit=200000, stop=None):
    """direct-call closure. returns dict va->depth"""
    seen = {}
    frontier = [(r, 0) for r in roots]
    while frontier:
        va, d = frontier.pop()
        if va in seen and seen[va] <= d:
            continue
        seen[va] = d
        if d >= depth or len(seen) > limit:
            continue
        if stop and va in stop:
            continue
        try:
            cs, _, _ = direct_calls(img, va)
        except Exception:
            continue
        for t in cs:
            if t not in seen or seen[t] > d + 1:
                frontier.append((t, d + 1))
    return seen



import struct
from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_PROT_ALL, UC_HOOK_CODE,
                     UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_HOOK_MEM_FETCH_UNMAPPED, UC_HOOK_MEM_WRITE, UcError)
import unicorn.x86_const as X

STACK, STACK_SZ = 0x7F0000000000, 0x200000
RET_MAGIC = 0x7E0000000000

GPR = {n: getattr(X, 'UC_X86_REG_' + n.upper()) for n in
       ['rax','rbx','rcx','rdx','rsi','rdi','rbp','rsp','r8','r9','r10','r11','r12','r13','r14','r15']}

class Emu:
    def __init__(self, img):
        self.img = img
        self.span = (img.base, img.base + img.size_of_image)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        self.stubs = {}
        self.trace = []
        self.traceon = False
        self.faults = []
        self.writes = []
        self.watch = None
        self.uc.mem_map(STACK, STACK_SZ, UC_PROT_ALL)
        self.uc.mem_map(RET_MAGIC & ~0xFFF, 0x1000, UC_PROT_ALL)
        self.uc.mem_write(RET_MAGIC, b"\xf4")
        self.uc.reg_write(X.UC_X86_REG_CR0, (self.uc.reg_read(X.UC_X86_REG_CR0) & ~4) | 2)
        self.uc.reg_write(X.UC_X86_REG_CR4, self.uc.reg_read(X.UC_X86_REG_CR4) | 0x600)
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._w)
        for h in (UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED):
            self.uc.hook_add(h, self._fault)

    def ensure(self, va, n=0x40):
        lo, hi = va & ~0xFFF, (va + n + 0xFFF) & ~0xFFF
        for p in range(lo, hi, 0x1000):
            if p in self.mapped: continue
            try: self.uc.mem_map(p, 0x1000, UC_PROT_ALL)
            except Exception:
                self.mapped.add(p); continue
            self.mapped.add(p)
            try:
                b = self.img.read_va(p, 0x1000)
                if b: self.uc.mem_write(p, b)
            except Exception: pass

    def _fault(self, uc, access, address, size, value, user):
        self.faults.append((access, address, size))
        self.ensure(address, size)
        return True

    def _w(self, uc, access, address, size, value, user):
        if self.watch and self.watch[0] <= address < self.watch[1]:
            self.writes.append((uc.reg_read(X.UC_X86_REG_RIP), address, size, value))

    def _code(self, uc, address, size, user):
        if self.traceon: self.trace.append(address)
        fn = self.stubs.get(address)
        if fn is not None:
            fn(uc)
            sp = uc.reg_read(X.UC_X86_REG_RSP)
            ret = struct.unpack("<Q", uc.mem_read(sp, 8))[0]
            uc.reg_write(X.UC_X86_REG_RSP, sp + 8)
            uc.reg_write(X.UC_X86_REG_RIP, ret)

    def wq(self,a,v): self.ensure(a,8); self.uc.mem_write(a,struct.pack("<Q",v))
    def wd(self,a,v): self.ensure(a,4); self.uc.mem_write(a,struct.pack("<I",v&0xffffffff))
    def wf(self,a,v): self.ensure(a,4); self.uc.mem_write(a,struct.pack("<f",v))
    def wb(self,a,v): self.ensure(a,1); self.uc.mem_write(a,bytes([v&0xff]))
    def wbs(self,a,bs): self.ensure(a,len(bs)); self.uc.mem_write(a,bytes(bs))
    def rf(self,a): return struct.unpack("<f", self.uc.mem_read(a,4))[0]
    def rd(self,a): return struct.unpack("<I", self.uc.mem_read(a,4))[0]

    def call(self, fn, args=(), stack_args=(), timeout=0, count=2_000_000):
        sp = (STACK + STACK_SZ//2) & ~0xF
        sp -= 0x200
        for i,v in enumerate(stack_args):
            self.uc.mem_write(sp + 0x28 + 8*i, struct.pack("<Q", v))
        self.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        self.uc.reg_write(X.UC_X86_REG_RSP, sp)
        for i,r in enumerate(['rcx','rdx','r8','r9']):
            if i < len(args): self.uc.reg_write(GPR[r], args[i])
        self.ensure(fn, 0x40)
        self.uc.emu_start(fn, RET_MAGIC, timeout, count)
        return self.uc.reg_read(X.UC_X86_REG_RAX)

import unicorn.x86_const as X

TBL  = 0x300000000
ENT  = 0x310000000
PERS = 0x320000000
P15  = 0x320100000
MATCH= 0x330000000
GLOB = 0x1486bd888
PERS_UPDATE = 0x145663920

ATTR_NAMES = {0x14:'OffAwareness',0x15:'DefAwareness',0x16:'GKAwareness',0x17:'Dribbling',
 0x18:'BallControl',0x19:'TightPossession',0x1a:'Finishing',0x1b:'LowPass',0x1c:'LoftedPass',
 0x1d:'Heading',0x1e:'BallWinning',0x1f:'Aggression',0x20:'DefEngagement',0x21:'SetPiece',
 0x22:'Curl',0x27:'WeakFootAcc',0x28:'Speed',0x29:'PhysicalContact',0x2a:'Balance',
 0x2b:'KickPower',0x2c:'Acceleration',0x2d:'Jumping',0x2e:'Stamina',0x36:'idx0x36'}

class World:
    def __init__(self, img=None):
        self.img = img or Img(PRISTINE)
        self.e = Emu(self.img)
        e=self.e
        e.wq(GLOB, TBL)
        e.wq(TBL + 0*0x58 + 0x55a8, ENT)
        self.R = ENT + 0x394
        # default attrs 70 everywhere in both arrays
        e.wbs(self.R, bytes([70])*0x100)
        e.wd(self.R+0xC0,0); e.wd(self.R+0xC4,0); e.wd(self.R+0xC8,0)
        e.wd(self.R+0xCC,0); e.wd(self.R+0xD0,0); e.wd(self.R+0xD4,0)
        e.wd(P15, 0)          # entity index 0
        e.wd(P15+0x18, 0)     # role
        e.wbs(PERS, bytes(0x28))
    def attrA(self, idx, v): self.e.wb(self.R+idx, v)
    def attrB(self, idx, v): self.e.wb(self.R+0x3d+idx, v)
    def attr(self, idx, v): self.attrA(idx,v); self.attrB(idx,v)
    def stylein(self, m): self.e.wd(self.R+0xCC, m)
    def styleout(self, m): self.e.wd(self.R+0xD0, m)
    def comai(self, m): self.e.wd(self.R+0xD4, m)
    def card(self, n, on=True):
        a=self.R+0xC0+ (n//32)*4
        v=self.e.rd(a)
        v = v | (1<<(n%32)) if on else v & ~(1<<(n%32))
        self.e.wd(a, v)
    def role(self, r): self.e.wd(P15+0x18, r)
    def run(self):
        self.e.wbs(PERS, bytes(0x28))
        self.e.call(PERS_UPDATE, (PERS, MATCH, P15, 0), (0,))
        return [self.e.rf(PERS+8+4*i) for i in range(8)]

def show(v):
    return '  '.join('P%d=%.4f'%(i,x) for i,x in enumerate(v))


import random

def norm(a, lo, hi):
    if lo >= a: return 0.0
    if a >= hi: return 1.0
    return (a - lo) / float(hi - lo)
def inv(a, lo, hi):
    if lo >= a: return 1.0
    if a >= hi: return 0.0
    return (a - hi) / float(lo - hi)

def model(A, B, sin, sout, comai, cards, role):
    P=[None]*8
    sb=lambda m,b: (m>>b)&1
    cb=lambda n: (cards>>n)&1
    # P0
    if any(sb(sin,b) for b in (0,5,9,10,12,13)) or sb(sout,8):
        P[0] = 0.5*norm(A[0x1a],75,85) + 0.1*inv(A[0x28],65,85) + 0.4*norm(A[0x19],75,85)
    else:
        P[0] = 0.0
    # P1
    P[1] = (0.3*norm(A[0x2c],75,85) + 0.2*norm(A[0x2c]-A[0x28],0,8)
            + 0.4*norm(A[0x18],75,85) + 0.1*norm(A[0x19],75,85))
    # P2
    P[2] = 0.25*norm(A[0x1c],70,90) + 0.25*norm(A[0x1d],70,90) \
           + 0.1*(cb(12)+cb(43)+cb(14)+cb(17)+cb(13))
    # P3
    if role in (7,9):
        g = 0.5 if any(sb(sin,b) for b in (3,9,4,0)) else 0.0
        P[3] = g + 0.3*norm(A[0x29],70,90) + 0.2*norm(A[0x14],60,80)
    else:
        P[3] = 0.0
    # P4  (scaled /100 then max(0,.))
    t = ( 0.5*(norm(A[0x18],70,90)+norm(B[0x18],70,90))*30.0
        + 0.5*(norm(A[0x2c],70,90)+norm(B[0x2c],70,90))*15.0
        + 0.5*(norm(A[0x28],70,90)+norm(B[0x28],70,90))*15.0
        + 10.0*(sb(comai,0)+sb(comai,1)+sb(comai,4)+sb(comai,2))
        - 10.0*sb(comai,6) )
    P[4] = max(0.0, t/100.0)
    # P5
    P[5] = 0.7*inv(B[0x36],0,3) + 0.3*inv(B[0x27],0,3)
    # P6 never written
    P[6] = 0.0
    # P7
    P[7] = 0.6*norm(A[0x29],70,90) + 0.3*inv(A[0x1a],60,80) + 0.1*sb(comai,1)
    return P

def run_one(seed):
    rnd=random.Random(seed)
    A=[rnd.randint(0,99) for _ in range(0x3d)]
    B=[rnd.randint(0,99) for _ in range(0x3d)]
    for i in (0x27,0x36): B[i]=rnd.randint(0,3); A[i]=rnd.randint(0,3)
    sin=rnd.getrandbits(21); sout=rnd.getrandbits(16); comai=rnd.getrandbits(7)
    cards=rnd.getrandbits(73); role=rnd.randint(0,15)
    w=World(IMG)
    for i,v in enumerate(A): w.attrA(i,v)
    for i,v in enumerate(B): w.attrB(i,v)
    w.stylein(sin); w.styleout(sout); w.comai(comai); w.role(role)
    for n in range(73):
        if (cards>>n)&1: w.card(n)
    got=w.run()
    exp=model(A,B,sin,sout,comai,cards,role)
    return got,exp


def cmd_rng():
    S=0x340000000
    for tag,path in (('PRISTINE',PRISTINE),('INSTALLED',INSTALLED)):
        e=Emu(Img(path))
        def f(seed,N,stream=2):
            e.wbs(S,bytes(16)); e.call(0x1443461c0,(S,stream,seed)); return e.call(0x144345e00,(S,N,stream))&0xffffffff
        print('==',tag)
        print('  attribute-seeded rand(100) (0x145674ec0 pattern, seed = ability byte):', ' '.join('%d:%d'%(a,f(a,100)) for a in range(40,100)))
        print('  frame-seeded rand(100) frames 0..39 (0x145668ec0 pattern):', [f(x,100) for x in range(40)])
        print('  time-seeded rand(100), seed=(int)(t*1500) (ImageUnit canStart pattern):', ' '.join('%.2f:%d'%(t/4,f(int(t/4*1500),100)) for t in range(13)))
        print('  clock-seeded rand(10) counter 0..19 (Roulette/TapTrick pattern):', [f(c,10) for c in range(20)])

def cmd_probe():
    b=World().run()
    def diff(v): return [i for i in range(8) if abs(v[i]-b[i])>1e-6]
    for bit in range(21):
        w=World(); w.stylein(1<<bit); v=w.run(); d=diff(v)
        if d: print('  style-in bit %2d -> %s'%(bit,['P%d=%.4f'%(i,v[i]) for i in d]))
    for bit in range(16):
        w=World(); w.styleout(1<<bit); v=w.run(); d=diff(v)
        if d: print('  style-out bit %2d -> %s'%(bit,['P%d=%.4f'%(i,v[i]) for i in d]))
    for bit in range(7):
        w=World(); w.comai(1<<bit); v=w.run(); d=diff(v)
        if d: print('  comai bit %d -> %s'%(bit,['P%d=%.4f'%(i,v[i]) for i in d]))
    for n in range(73):
        w=World(); w.card(n); v=w.run(); d=diff(v)
        if d: print('  card %2d -> %s'%(n,['P%d=%+.4f'%(i,v[i]-b[i]) for i in d]))
    for r in range(16):
        w=World(); w.role(r); v=w.run(); d=diff(v)
        if d: print('  role %2d -> %s'%(r,['P%d=%.4f'%(i,v[i]) for i in d]))

if __name__=='__main__':
    cmd=sys.argv[1] if len(sys.argv)>1 else 'model'
    if cmd=='model':
        which=sys.argv[2] if len(sys.argv)>2 else 'p'
        IMG=Img(PRISTINE if which=='p' else INSTALLED)
        N=int(sys.argv[3]) if len(sys.argv)>3 else 40
        bad=0
        for s in range(N):
            got,exp=run_one(s)
            for i in range(8):
                if abs(got[i]-exp[i])>2e-6: bad+=1; print('seed %d P%d got %.6f exp %.6f'%(s,i,got[i],exp[i]))
        print('%s: %d random worlds x 8 fields, mismatches=%d'%(which.upper(),N,bad))
    elif cmd=='probe': cmd_probe()
    elif cmd=='rng': cmd_rng()
