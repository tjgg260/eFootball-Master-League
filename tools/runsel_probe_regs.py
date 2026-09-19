import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct, sys
from pathlib import Path
from unicorn import *
from unicorn import x86_const as X
from cave_alloc import Image
import runsel_emu_cave as C1
from runsel_emu_score import STACK, STACK_SZ, RET_MAGIC, SEL, CTX, CTXA, TEAMAI, PLAYER0, i2f, INST
from runsel_emu_cave import DATAOBJ0

HOOK = 0x143DF5D6A
NAMES = "rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15".split()
img = Image(INST)
IDX = 3
e = C1.build(img, C1.XS, [0.0]*11, C1.ROLE, C1.ATTR, None, idx=IDX)
snap = {}
def probe(uc, address, size, user):
    if address == HOOK and not snap:
        for n in NAMES:
            snap[n] = uc.reg_read(getattr(X, "UC_X86_REG_" + n.upper()))
        snap["xmm6"] = i2f(uc.reg_read(X.UC_X86_REG_XMM6) & 0xFFFFFFFF)
e.uc.hook_add(UC_HOOK_CODE, probe)
uc = e.uc
sp = (STACK + STACK_SZ//2) & ~0xF
uc.reg_write(X.UC_X86_REG_RSP, sp); uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
uc.reg_write(X.UC_X86_REG_RCX, SEL); uc.reg_write(X.UC_X86_REG_RDX, CTX)
uc.reg_write(X.UC_X86_REG_R8, IDX); uc.reg_write(X.UC_X86_REG_R9, 0)
uc.emu_start(0x143DF5950, RET_MAGIC, count=400000)
known = {SEL: "SEL (selector this)", CTX: "CTX (ctx arg / rdx)", CTXA: "ctx[0]",
         TEAMAI: "ctx[8] teamAI", PLAYER0 + IDX*0x1000: "player MATCH object",
         DATAOBJ0 + IDX*0x400: "player DATA object", IDX: "playerIdx"}
print("registers at the Chance hook 0x143df5d6a (playerIdx = %d):" % IDX)
for n in NAMES:
    v = snap[n]
    print("   %-4s = %#018x   %s" % (n, v, known.get(v, "")))
print("   xmm6 = %s  (the finished score)" % snap["xmm6"])
print("   rsp%16 =", snap["rsp"] % 16, "in THIS harness. The harness starts with a 16-aligned rsp,"
      " whereas a real call leaves rsp%16 == 8 at function entry, so the real in-game value at the"
      " hook is (this + 8) % 16 == 0 — correctly 16-aligned for a further `call`.")
