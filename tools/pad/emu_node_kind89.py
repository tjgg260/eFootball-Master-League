"""Emulate pattern-node kinds 8 and 9 (0x14430db10 / 0x14430dbd0) on the game's own bytes.

Repair pass 2026-09-20: settles whether the 'slack' in kinds 8/9 is positional (only the
newest frame may be contrary) or a budget of one contrary frame anywhere in [0, start].
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from padimg import read, secs, BASE
from unicorn import *
from unicorn.x86_const import *

CODE_LO = 0x140001000
STACK = 0x200000000
DATA = 0x300000000          # pad-slot block
NODE = 0x300010000
RET = 0x400000000

BTN = 21
CURSOR = 50


def build_block(down_ages):
    """100 x 64-byte frames + cursor at +0x1900. down_ages = set of k (frames ago) held down."""
    b = bytearray(0x1908)
    for k in range(100):
        i = CURSOR - k
        if i < 0:
            i += 100
        mask = (1 << BTN) if k in down_ages else 0
        struct.pack_into('<Q', b, i * 64, mask)
    struct.pack_into('<I', b, 0x1900, CURSOR)
    return bytes(b)


def build_node(kind):
    n = bytearray(0x28)
    struct.pack_into('<I', n, 0x00, 1 << BTN)     # mask
    struct.pack_into('<I', n, 0x04, kind)
    n[0x10] = 0                                    # no stick constraint -> table C
    struct.pack_into('<f', n, 0x20, -1.0)
    struct.pack_into('<f', n, 0x24, -1.0)
    return bytes(n)


def run(handler, down_ages, start, window=100):
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    # map the whole executable image region we might touch
    for name, va, vsz, rof, rsz, ch in secs:
        lo = (BASE + va) & ~0xFFF
        size = (max(vsz, rsz) + 0xFFF) & ~0xFFF
        if name not in ('.xcode',):
            continue
        uc.mem_map(lo, size)
        uc.mem_write(lo, read(BASE + va, rsz))
    uc.mem_map(STACK - 0x100000, 0x200000)
    uc.mem_map(DATA, 0x10000)
    uc.mem_map(NODE, 0x1000)
    uc.mem_map(RET, 0x1000)
    uc.mem_write(DATA, build_block(down_ages))
    uc.mem_write(NODE, build_node(8))
    uc.reg_write(UC_X86_REG_RSP, STACK)
    uc.mem_write(STACK, struct.pack('<Q', RET))
    uc.reg_write(UC_X86_REG_RCX, DATA)
    uc.reg_write(UC_X86_REG_RDX, NODE)
    uc.reg_write(UC_X86_REG_R8D, start)
    uc.reg_write(UC_X86_REG_R9D, window)
    uc.emu_start(handler, RET, count=2_000_000)
    v = uc.reg_read(UC_X86_REG_EAX) & 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


K8 = 0x14430db10
K9 = 0x14430dbd0
ALL = set(range(100))

print("kind 8 (0x14430db10) -- UP test.  start=8, window=100")
for label, down in (("nothing down", set()),
                    ("down at age 0 only", {0}),
                    ("down at age 1 only", {1}),
                    ("down at age 2 only", {2}),
                    ("down at age 8 only", {8}),
                    ("down at ages 0,1", {0, 1}),
                    ("down at age 9 only", {9}),
                    ("down at age 10 only", {10})):
    print("   %-22s -> %s" % (label, run(K8, down, 8)))

print("kind 9 (0x14430dbd0) -- DOWN test (mirror).  start=8, window=100")
for label, down in (("all down", ALL),
                    ("up at age 0 only", ALL - {0}),
                    ("up at age 1 only", ALL - {1}),
                    ("up at age 2 only", ALL - {2}),
                    ("up at ages 0,1", ALL - {0, 1}),
                    ("up at age 9 only", ALL - {9})):
    print("   %-22s -> %s" % (label, run(K9, down, 8)))

print("kind 8 start sweep, never down:     ", [run(K8, set(), s) for s in range(9)])
print("kind 8 start sweep, up f0..f4 only: ", [run(K8, set(range(5, 100)), s) for s in range(9)])
