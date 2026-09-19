import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct, sys
from unicorn import *
from unicorn import x86_const as X
from cave_alloc import Image
import runsel_emu_cave as C1
from runsel_emu_score import STACK, STACK_SZ, RET_MAGIC, SEL, CTX, i2f, f2i, INST

def stub_f(v):
    def f(uc): uc.reg_write(X.UC_X86_REG_XMM0, f2i(v))
    return f

def go(base_k3, x, cave=None, idx=0):
    img = Image(INST)
    xs = [x]*11
    e = C1.build(img, xs, [0.0]*11, [0]*11, [40]*11, cave, kind=3, idx=idx)
    e.stubs[0x143df5de0] = stub_f(base_k3)
    uc = e.uc
    sp = (STACK + STACK_SZ//2) & ~0xF
    uc.reg_write(X.UC_X86_REG_RSP, sp); uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RCX, SEL); uc.reg_write(X.UC_X86_REG_RDX, CTX)
    uc.reg_write(X.UC_X86_REG_R8, idx); uc.reg_write(X.UC_X86_REG_R9, 0)
    uc.emu_start(0x143DF5950, RET_MAGIC, count=400000)
    return i2f(uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF)

import runsel_emu_cave2 as C2
cave = C2.payload(0.30, 4.0)
print("kind 3 (situational base) worst cases, INSTALLED image:")
for base in (100.0, 72.0):
    for x in (-52.5, -60.0, -70.0):
        s = go(base, x)
        h = go(base, x, cave)
        print("   base=%5.1f  x=%6.1f   stock=%8.3f   hooked(GAIN .3 NOISE 4 cap16 floor1)=%8.3f" % (base, x, s, h))
