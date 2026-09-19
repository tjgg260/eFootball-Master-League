"""Shared Unicorn harness: map the PRISTINE image lazily, run real bytes."""
import sys, struct
from pathlib import Path
REPO = Path(r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b")
sys.path.insert(0, str(REPO / "tools"))
import cave_alloc as CA
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError, UC_HOOK_MEM_UNMAPPED
from unicorn import x86_const as X

BASE = 0x140000000
STOP = 0x0BAD0000          # magic return address; we stop there
STACK = 0x20000000
HEAP  = 0x30000000

class Emu:
    def __init__(self, image_path=None):
        self.img = CA.Image(image_path or CA.PRISTINE)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.map(STACK - 0x100000, 0x200000)
        self.map(HEAP, 0x400000)
        self.map(STOP & ~0xFFFF, 0x10000)
        self.uc.mem_write(STOP, b"\xf4")           # hlt
        self.heap_next = HEAP + 0x1000

    def _on_unmapped(self, uc, access, addr, size, value, user):
        p = addr & ~0xFFFFF
        try:
            self.map(p, 0x100000)
        except Exception:
            return False
        return True

    def map(self, va, size):
        for p in range(va & ~0xFFF, va + size, 0x1000):
            if p in self.mapped:
                continue
            try:
                self.uc.mem_map(p & ~0xFFFF, 0x10000)
            except UcError:
                pass
            for q in range(p & ~0xFFFF, (p & ~0xFFFF) + 0x10000, 0x1000):
                self.mapped.add(q)
            f = self.img.va_to_file(p & ~0xFFFF)
            if f is not None:
                self.uc.mem_write(p & ~0xFFFF, self.img.data[f:f + 0x10000])

    def alloc(self, n, align=0x100):
        a = (self.heap_next + align - 1) & ~(align - 1)
        self.heap_next = a + n
        self.map(a, n + 0x1000)
        self.uc.mem_write(a, b"\0" * n)
        return a

    def w8(self, va, v):  self.map(va, 8); self.uc.mem_write(va, struct.pack("<B", v & 0xFF))
    def w32(self, va, v): self.map(va, 8); self.uc.mem_write(va, struct.pack("<I", v & 0xFFFFFFFF))
    def w64(self, va, v): self.map(va, 8); self.uc.mem_write(va, struct.pack("<Q", v & (2**64-1)))
    def wf(self, va, v):  self.map(va, 8); self.uc.mem_write(va, struct.pack("<f", v))
    def r32(self, va):
        self.map(va, 8)
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]
    def rf(self, va):     return struct.unpack("<f", self.uc.mem_read(va, 4))[0]

    def call(self, fn, rcx=0, rdx=0, r8=0, r9=0, xmm=None, count=200000):
        uc = self.uc
        sp = STACK & ~0xF
        sp -= 0x200
        uc.mem_write(sp, struct.pack("<Q", STOP))    # return address
        uc.reg_write(X.UC_X86_REG_RSP, sp)
        for r, v in ((X.UC_X86_REG_RCX, rcx), (X.UC_X86_REG_RDX, rdx),
                     (X.UC_X86_REG_R8, r8), (X.UC_X86_REG_R9, r9)):
            uc.reg_write(r, v)
        err = None
        try:
            uc.emu_start(fn, STOP, count=count)
        except UcError as e:
            err = f"{e} @rip={uc.reg_read(X.UC_X86_REG_RIP):#x}"
        return uc.reg_read(X.UC_X86_REG_RAX), err

    def run_block(self, code_va, code, entry, stop, regs=None, xmmregs=None, count=100000):
        """Write `code` at code_va (emulator-only) and run entry->stop."""
        uc = self.uc
        self.map(code_va, len(code) + 0x100)
        uc.mem_write(code_va, code)
        self.map(stop, 16)
        uc.mem_write(stop, b"\xf4")
        sp = (STACK & ~0xF) - 0x400
        uc.reg_write(X.UC_X86_REG_RSP, sp)
        for r, v in (regs or {}).items():
            uc.reg_write(r, v)
        for r, v in (xmmregs or {}).items():
            uc.reg_write(r, v)
        err = None
        try:
            uc.emu_start(entry, stop, count=count)
        except UcError as e:
            err = f"{e} @rip={uc.reg_read(X.UC_X86_REG_RIP):#x}"
        return err

def f2b(f):  return struct.unpack("<I", struct.pack("<f", f))[0]
def b2f(b):  return struct.unpack("<f", struct.pack("<I", b & 0xFFFFFFFF))[0]
