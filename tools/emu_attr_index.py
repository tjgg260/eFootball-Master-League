#!/usr/bin/env python3
"""emu_attr.py - Unicorn proof of the eFootball attribute index space.

Proves, by executing the real bytes of the PRISTINE image:
  1. ATTR_get 0x143ea8cb0(player, idx) resolves to byte[playerData+0x394 + idx].
  2. 0x1442bfae0 / 0x1442bfb10 (attribute range getters) accept idx 0..0x3c except
     0x12/0x13, and return the per-index (min,max) pair -> the 61-entry index space.
  3. At the anticipation site 0x143da6529 the multiplier at 0x147850538 is -0.0f, so
     the marginPredictionFrameAdjust term is ALWAYS 0 for every possible input value.
"""
import struct, sys
from pathlib import Path
sys.path.insert(0, r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b/tools")
from exe_map import Image
from unicorn import *
from unicorn.x86_const import *

B = 0x140000000
EXE = Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")
img = Image(EXE)

PAGE = 0x1000

def ensure(uc, va, size):
    mapped = uc._mapped
    lo = va & ~(PAGE - 1)
    hi = (va + size + PAGE - 1) & ~(PAGE - 1)
    for p in range(lo, hi, PAGE):
        if p in mapped:
            continue
        uc.mem_map(p, PAGE, UC_PROT_ALL)
        data = img.read(p - B, PAGE)
        uc.mem_write(p, data)
        mapped.add(p)

STACK = 0x7ff000000000
HEAP  = 0x200000000

def new_uc():
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc._mapped = set()
    uc.mem_map(STACK, 0x100000, UC_PROT_ALL)
    uc.mem_map(HEAP, 0x100000, UC_PROT_ALL)
    uc.mem_map(0x1000, PAGE, UC_PROT_ALL)
    uc.mem_write(0x1000, bytes([0xf4]))
    return uc

def call(uc, fn, rcx=0, rdx=0, r8=0, r9=0, spans=()):
    for va, n in spans:
        ensure(uc, va, n)
    ensure(uc, fn, 0x400)
    RET = 0x1000
    sp = STACK + 0x80000
    uc.mem_write(sp, struct.pack("<Q", RET))
    uc.reg_write(UC_X86_REG_RSP, sp)
    uc.reg_write(UC_X86_REG_RCX, rcx)
    uc.reg_write(UC_X86_REG_RDX, rdx)
    uc.reg_write(UC_X86_REG_R8, r8)
    uc.reg_write(UC_X86_REG_R9, r9)
    uc.emu_start(fn, RET, count=2000)
    return uc.reg_read(UC_X86_REG_RAX)


# ---------------------------------------------------------------- 1. ATTR_get
print("== 1. ATTR_get 0x143ea8cb0(player, idx) -> byte[data+0x394+idx]")
uc = new_uc()
for fn in (0x143ea8cb0, 0x1442dd650, 0x1442d6ef0, 0x144301840, 0x1441172b0):
    ensure(uc, fn, 0x40)
ensure(uc, 0x1486bd888, 0x10)          # the global container base pointer

PLAYER   = HEAP + 0x10000
DATAOBJ  = HEAP + 0x20000
CONTBASE = HEAP + 0x30000
ENTITY   = 7                            # arbitrary entity index 0..0x1e

uc.mem_write(PLAYER + 0x47c0, struct.pack("<Q", 0xdeadbeef))   # first arg to 0x1442dd650 (unused)
uc.mem_write(PLAYER + 0x2bd8, bytes([ENTITY]))
uc.mem_write(0x1486bd888, struct.pack("<Q", CONTBASE))
uc.mem_write(CONTBASE + ENTITY * 0x58 + 0x55a8, struct.pack("<Q", DATAOBJ))
# fill the 61-byte attribute array with idx+100 so a read is self-identifying
uc.mem_write(DATAOBJ + 0x394, bytes([(i + 100) & 0xff for i in range(0x40)]))

ok = True
for idx in (0x14, 0x15, 0x16, 0x1e, 0x27, 0x2d, 0x30, 0x35):
    got = call(uc, 0x143ea8cb0, rcx=PLAYER, rdx=idx) & 0xff
    exp = (idx + 100) & 0xff
    ok &= (got == exp)
    print(f"   idx {idx:#04x} -> {got:3d} (expected byte[+0x394+{idx:#04x}] = {exp})")
print("   VERDICT:", "ATTR_get is a plain byte-table read" if ok else "MISMATCH")

# ---------------------------------------------------------------- 2. range tables
print()
print("== 2. attribute range getters 0x1442bfae0 (field) / 0x1442bfb10 (level-up)")
uc2 = new_uc()
for fn in (0x1442bfae0, 0x1442bfb10):
    ensure(uc2, fn, 0x80)
ensure(uc2, 0x146c00860, 0x200)
OUT = HEAP + 0x40000
rows = []
for idx in range(0, 0x41):
    uc2.mem_write(OUT, b"\xAA\xAA\xAA\xAA")
    r1 = call(uc2, 0x1442bfae0, rcx=OUT, rdx=OUT + 1, r8=idx) & 0xff
    a1, b1 = uc2.mem_read(OUT, 2)
    uc2.mem_write(OUT + 2, b"\xAA\xAA")
    r2 = call(uc2, 0x1442bfb10, rcx=OUT + 2, rdx=OUT + 3, r8=idx) & 0xff
    a2, b2 = uc2.mem_read(OUT + 2, 2)
    rows.append((idx, r1, a1, b1, r2, a2, b2))
print("   idx  ok  min  max   | levelup ok  min  max")
for idx, r1, a1, b1, r2, a2, b2 in rows:
    if r1 == 0:
        print(f"   {idx:#04x}  REJECTED                 | REJECTED")
    else:
        print(f"   {idx:#04x}   1  {a1:3d}  {b1:3d}   |    1      {a2:3d}  {b2:3d}")
valid = [r[0] for r in rows if r[1]]
print(f"   accepted indices: {len(valid)}  -> {hex(min(valid))}..{hex(max(valid))}, "
      f"rejected: {[hex(r[0]) for r in rows if not r[1]]}")

# ------------------------------------------- 3. the dead marginPredictionFrameAdjust
print()
print("== 3. anticipation site 0x143da6529: is the adjust term always 0?")
uc3 = new_uc()
uc3.reg_write(UC_X86_REG_CR0, uc3.reg_read(UC_X86_REG_CR0) & ~4 | 2)
uc3.reg_write(UC_X86_REG_CR4, uc3.reg_read(UC_X86_REG_CR4) | 0x600)
ensure(uc3, 0x143da6529, 0x40)
ensure(uc3, 0x147850538, 0x10)
mult = struct.unpack("<f", img.read(0x147850538 - B, 4))[0]
print(f"   literal cell 0x147850538 = {mult!r}  (raw {img.read(0x147850538-B,4).hex()})")
R12 = HEAP + 0x50000
worst = []
for adj in (-2**31, -1000, -7, -1, 0, 1, 7, 1000, 2**31 - 1):
    uc3.mem_write(R12 + 0x23c, struct.pack("<i", adj))
    uc3.mem_write(R12 + 0x240, struct.pack("<i", 30))     # base prediction frames
    uc3.reg_write(UC_X86_REG_R12, R12)
    uc3.reg_write(UC_X86_REG_RBP, HEAP + 0x60000)
    uc3.reg_write(UC_X86_REG_RSP, STACK + 0x80000)
    uc3.emu_start(0x143da6529, 0x143da6553, count=50)      # stop before 'sub edi,eax'
    eax = uc3.reg_read(UC_X86_REG_EAX)
    worst.append(eax)
    print(f"   marginPredictionFrameAdjust={adj:12d} -> eax={eax}  (edi would become 30-{eax})")
print("   VERDICT:", "term is DEAD for every input" if set(worst) == {0} else "term is LIVE")
