"""Copied from the 2026-09-19 ball-carrier probe scratchpad. Depends on bpx.py (scratch) -- see docs/ball-carrier-brain.md. Read-only over the PRISTINE image."""
"""Unicorn harness for match::ai::bp experiments (read-only image, everything synthetic)."""
import struct, sys
import numpy as np
import bpx  # tools/bpx.py
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_PROT_ALL, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UcError
from unicorn import x86_const as X
BASE = bpx.BASE
STACK = 0x7ff00000; STACK_SZ = 0x100000
HEAP = 0x10000000;  HEAP_SZ = 0x400000
RET_MAGIC = 0x7fee0000

class Emu:
    def __init__(self, im=None):
        self.im = im or bpx.img()
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        d = self.im.data
        for s in self.im.sections:
            va = BASE + s["rva"]; size = (max(s["vsize"], s["rsize"]) + 0xfff) & ~0xfff
            if size == 0: continue
            self.uc.mem_map(va & ~0xfff, size, UC_PROT_ALL)
            n = min(s["rsize"], s["vsize"]) if s["vsize"] else s["rsize"]
            if n: self.uc.mem_write(va, d[s["raw"]:s["raw"]+n])
        self.uc.mem_map(STACK, STACK_SZ, UC_PROT_ALL)
        self.uc.mem_map(HEAP, HEAP_SZ, UC_PROT_ALL)
        self.uc.mem_map(RET_MAGIC & ~0xfff, 0x1000, UC_PROT_ALL)
        self.heap = HEAP
        self.hooks = {}
        self.trace = []
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
    def alloc(self, n, align=16):
        self.heap = (self.heap + align - 1) & ~(align - 1)
        p = self.heap; self.heap += n; return p
    def hook(self, va, fn): self.hooks[va] = fn
    def _unmapped(self, uc, access, addr, size, value, data):
        print(f"  !! unmapped access at {addr:#x} rip={uc.reg_read(X.UC_X86_REG_RIP):#x}"); return False
    def _code(self, uc, addr, size, data):
        fn = self.hooks.get(addr)
        if fn is not None:
            r = fn(uc)
            # emulate 'ret'
            rsp = uc.reg_read(X.UC_X86_REG_RSP)
            ret = struct.unpack("<Q", uc.mem_read(rsp, 8))[0]
            uc.reg_write(X.UC_X86_REG_RSP, rsp + 8)
            uc.reg_write(X.UC_X86_REG_RIP, ret)
    def call(self, va, rcx=0, rdx=0, r8=0, r9=0, stack_args=(), xmm=None, max_ins=5_000_000):
        uc = self.uc
        rsp = STACK + STACK_SZ - 0x4000
        # shadow space + stack args
        frame = rsp - 0x20 - 8*len(stack_args); frame &= ~0xf; frame -= 8
        uc.mem_write(frame, struct.pack("<Q", RET_MAGIC))
        for i, a in enumerate(stack_args):
            uc.mem_write(frame + 0x28 + 8*i, struct.pack("<Q", a & 0xffffffffffffffff))
        uc.reg_write(X.UC_X86_REG_RSP, frame)
        uc.reg_write(X.UC_X86_REG_RCX, rcx); uc.reg_write(X.UC_X86_REG_RDX, rdx)
        uc.reg_write(X.UC_X86_REG_R8, r8); uc.reg_write(X.UC_X86_REG_R9, r9)
        if xmm:
            for i, v in xmm.items():
                uc.reg_write(getattr(X, f"UC_X86_REG_XMM{i}"), struct.unpack("<Q", struct.pack("<f", v) + b"\0"*4)[0] if isinstance(v, float) else v)
        uc.emu_start(va, RET_MAGIC, count=max_ins)
        return uc.reg_read(X.UC_X86_REG_RAX)
    def xmm0f(self):
        v = self.uc.reg_read(X.UC_X86_REG_XMM0)
        return struct.unpack("<f", struct.pack("<Q", v & 0xffffffffffffffff)[:4])[0]
    def w(self, va, fmt, *vals): self.uc.mem_write(va, struct.pack(fmt, *vals))
    def r(self, va, fmt): return struct.unpack(fmt, self.uc.mem_read(va, struct.calcsize(fmt)))
    def u32(self, va): return self.r(va, "<I")[0]
    def u64(self, va): return self.r(va, "<Q")[0]
    def f32(self, va): return self.r(va, "<f")[0]
    def set_rax(self, v): self.uc.reg_write(X.UC_X86_REG_RAX, v & 0xffffffffffffffff)
    def set_xmm0(self, f): self.uc.reg_write(X.UC_X86_REG_XMM0, struct.unpack("<Q", struct.pack("<f", f) + b"\0"*4)[0])
    def reg(self, name): return self.uc.reg_read(getattr(X, "UC_X86_REG_" + name.upper()))
