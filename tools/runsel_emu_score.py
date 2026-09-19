#!/usr/bin/env python3
"""Unicorn emulation of ChanceSpaceRun::vf5 (0x143df5950) and DiagonalRun::vf5 (0x143e036e0).
READ-ONLY on both images. Nothing is written to the game."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct, sys
from pathlib import Path
import capstone
from unicorn import *
from unicorn import x86_const as X
from cave_alloc import Image

BASE = 0x140000000
PRIS = Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")
INST = Path(r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe")

CHANCE_VF5 = 0x143DF5950
DIAG_VF5   = 0x143E036E0
G_CONTAINER = 0x1486BD888

STACK = 0x7FF000000000; STACK_SZ = 0x200000
HEAP  = 0x200000000;    HEAP_SZ  = 0x400000
RET_MAGIC = 0x1000

SEL      = HEAP + 0x10000
CTX      = HEAP + 0x20000
CTXA     = HEAP + 0x28000      # ctx[0]
TEAMAI   = HEAP + 0x30000      # ctx[8]
CONTAINER= HEAP + 0x40000
PLAYER0  = HEAP + 0x80000      # match player objects, 0x1000 apart

def f2i(v): return struct.unpack("<I", struct.pack("<f", v))[0]
def i2f(v): return struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]

class Emu:
    def __init__(self, img, overlays=()):
        self.img = img
        self.span = (img.base, img.base + max(s["rva"]+s["vsize"] for s in img.sections))
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped=set(); self.overlays=list(overlays)
        self.stubs={}; self.trace=[]; self.faults=[]
        self.uc.mem_map(STACK, STACK_SZ, UC_PROT_ALL)
        self.uc.mem_map(HEAP, HEAP_SZ, UC_PROT_ALL)
        self.uc.mem_map(RET_MAGIC & ~0xFFF, 0x1000, UC_PROT_ALL)
        self.uc.mem_write(RET_MAGIC, b"\xf4")
        self.uc.reg_write(X.UC_X86_REG_CR0,(self.uc.reg_read(X.UC_X86_REG_CR0)&~4)|2)
        self.uc.reg_write(X.UC_X86_REG_CR4, self.uc.reg_read(X.UC_X86_REG_CR4)|0x600)
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        for h in (UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED):
            self.uc.hook_add(h, self._fault)
    def ensure(self, va, n=0x40):
        lo,hi = va & ~0xFFF, (va+n+0xFFF)&~0xFFF
        for p in range(lo,hi,0x1000):
            if p in self.mapped: continue
            try: self.uc.mem_map(p,0x1000,UC_PROT_ALL)
            except Exception: self.mapped.add(p); continue
            self.mapped.add(p)
            try:
                b=self.img.read_va(p,0x1000)
                if b: self.uc.mem_write(p,b)
            except Exception: pass
        for va_o,b in self.overlays:
            if lo <= va_o < hi: self.uc.mem_write(va_o,b)
    def _fault(self, uc, access, address, size, value, user):
        self.faults.append((address,size))
        if self.span[0] <= address < self.span[1]:
            self.ensure(address,size); return True
        return False
    def _code(self, uc, address, size, user):
        self.trace.append(address)
        fn=self.stubs.get(address)
        if fn is not None:
            fn(uc)
            sp=uc.reg_read(X.UC_X86_REG_RSP)
            ret=struct.unpack("<Q", uc.mem_read(sp,8))[0]
            uc.reg_write(X.UC_X86_REG_RSP, sp+8)
            uc.reg_write(X.UC_X86_REG_RIP, ret)
    def wq(self,a,v): self.ensure(a,8); self.uc.mem_write(a,struct.pack("<Q",v))
    def wd(self,a,v): self.ensure(a,4); self.uc.mem_write(a,struct.pack("<i",v))
    def wf(self,a,v): self.ensure(a,4); self.uc.mem_write(a,struct.pack("<f",v))
    def wb(self,a,v): self.ensure(a,1); self.uc.mem_write(a,bytes([v & 0xFF]))

def ret_bool(v):
    def f(uc): uc.reg_write(X.UC_X86_REG_RAX, 1 if v else 0)
    return f

def build_chance(img, *, xs, roles, attackdir=1, kind=5, target_y=1.0):
    e = Emu(img)
    e.ensure(CHANCE_VF5, 0x600)
    e.ensure(G_CONTAINER, 16)
    e.wq(G_CONTAINER, CONTAINER)
    for i in range(22):
        e.wq(CONTAINER + i*0x58 + 0x4058, PLAYER0 + i*0x1000)
    # ctx
    e.wq(CTX+0, CTXA); e.wq(CTX+8, TEAMAI)
    e.wb(TEAMAI+0x28c, attackdir & 0xFF)
    e.wf(TEAMAI+0x288, 0.0)
    # selector: run target per slot + kind masks
    for slot in range(11):
        e.wf(SEL+0x60+12*slot+0, 10.0)
        e.wf(SEL+0x60+12*slot+4, target_y)
        e.wf(SEL+0x60+12*slot+8, 0.0)
        for k in range(16):
            e.wd(SEL+0x2c8+4*k, 0)
    for k in range(16):
        e.wd(SEL+0x2c8+4*k, (0x7FF if k==kind else 0))
    for i,x in enumerate(xs):
        e.wf(PLAYER0+i*0x1000+0x4f4, x)
        e.wf(PLAYER0+i*0x1000+0x4fc, 0.0)
    e.stubs[0x143d37f30] = lambda uc, R=roles: None
    return e

def run_chance(img, xs, roles, attackdir=1, kind=5, target_y=1.0, idx=None, trace=False):
    out=[]
    for i in range(len(xs)):
        e = build_chance(img, xs=xs, roles=roles, attackdir=attackdir, kind=kind, target_y=target_y)
        e.stubs[0x143d37f30] = ret_bool(roles[i])
        e.stubs[0x143d32a90] = ret_bool(False)
        e.stubs[0x143d37d70] = ret_bool(True)
        uc=e.uc
        sp = STACK + STACK_SZ//2
        sp &= ~0xF
        uc.reg_write(X.UC_X86_REG_RSP, sp)
        uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RCX, SEL)
        uc.reg_write(X.UC_X86_REG_RDX, CTX)
        uc.reg_write(X.UC_X86_REG_R8, i)
        uc.reg_write(X.UC_X86_REG_R9, 0)
        try:
            uc.emu_start(CHANCE_VF5, RET_MAGIC, count=200000)
        except UcError as ex:
            print(f"  [!] player {i}: {ex}  rip={uc.reg_read(X.UC_X86_REG_RIP):#x} faults={e.faults[-3:]}")
            out.append(None); continue
        xmm0 = uc.reg_read(X.UC_X86_REG_XMM0)
        out.append(i2f(xmm0 & 0xFFFFFFFF))
        if trace and i==0:
            print("   trace:", " ".join(f"{a:#x}" for a in e.trace[:6]), "...")
    return out

if __name__ == "__main__":
    LAB = ["ST","LW","RW","AMF","RB","LB","CM1","CM2","DMF","CB1","CB2"]
    XS  = [38.0,34.0,33.0,26.0,22.0,21.0,18.0,16.0,10.0,2.0,1.0]
    ROLE= [True,True,True,False,False,False,False,False,False,False,False]
    for name,p in (("PRISTINE",PRIS),("INSTALLED",INST)):
        img=Image(p)
        print(f"== ChanceSpaceRun::vf5 emulated, {name} (attackDir=+1, kind=5, target.y=+1) ==")
        sc = run_chance(img, XS, ROLE, trace=(name=="PRISTINE"))
        order = sorted(range(11), key=lambda i: -(sc[i] if sc[i] is not None else -1e9))
        for r,i in enumerate(order):
            print(f"   {r+1:2}. {LAB[i]:4} x={XS[i]:5.1f} role={int(ROLE[i])}  score={sc[i]}")
        print()
    # negative / rejection paths (pristine)
    img=Image(PRIS)
    print("== rejection sentinel: target.y sweep, player ST (idx 0), PRISTINE ==")
    for y in (-5.0, -0.001, -0.0, 0.0, 0.001, 5.0):
        sc = run_chance(img, XS, ROLE, target_y=y)
        print(f"   target.y={y:>8}  score={sc[0]}")
    print()
    print("== attackDir = -1 (other direction), PRISTINE ==")
    sc = run_chance(img, XS, ROLE, attackdir=-1)
    for i in range(11): print(f"   {LAB[i]:4} x={XS[i]:5.1f} -> {sc[i]}")
