#!/usr/bin/env python3
"""emu_enum.py - execute the real DATA_PARAMETER enum registrar and record what it emits.

The registrar is a straight-line block per enum member:
    mov  dword [rip+G], <enum value>
    mov  eax,[rbx] ; cmp [rip+H],eax ; jg <skip>
    mov  r8d,<strlen> ; lea rdx,<name> ; lea rcx,<sink> ; call <register>
We emulate it with Unicorn, stub out the register call, and print (value, name) as the
CPU actually computes them - no static pattern matching.
"""
import struct, sys
from pathlib import Path
sys.path.insert(0, r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b/tools")
from exe_map import Image
from unicorn import *
from unicorn.x86_const import *
import capstone

B = 0x140000000
img = Image(Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE"))
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

START = 0x1409f5043
END   = 0x1409f5c00
PAGE = 0x1000
uc = Uc(UC_ARCH_X86, UC_MODE_64)
STACK = 0x7ff000000000
SCRATCH = 0x300000000
uc.mem_map(STACK, 0x100000, UC_PROT_ALL)
uc.mem_map(SCRATCH, 0x100000, UC_PROT_ALL)

# map every image page the block can touch: code window + all of .rdata-ish neighbours
def mapva(va, size):
    lo = va & ~(PAGE-1); hi = (va+size+PAGE-1) & ~(PAGE-1)
    for p in range(lo, hi, PAGE):
        try:
            uc.mem_map(p, PAGE, UC_PROT_ALL)
            uc.mem_write(p, img.read(p-B, PAGE))
        except UcError:
            pass
mapva(0x1409f4000, 0x3000)
mapva(0x14748c000, 0x4000)      # the DATA_PARAMETER strings
mapva(0x148200000, 0x400000)    # the .data globals the block writes / compares

def on_unmapped(uc, access, address, size, value, user):
    p = address & ~(PAGE-1)
    try:
        uc.mem_map(p, PAGE, UC_PROT_ALL)
        if B <= p < B + 0x40000000:
            uc.mem_write(p, img.read(p - B, PAGE))
    except UcError:
        pass
    return True

uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)

records = []
def hook(uc, address, size, user):
    code = uc.mem_read(address, size)
    ins = next(md.disasm(bytes(code), address), None)
    if ins is None:
        return
    if ins.mnemonic == "call":
        rdx = uc.reg_read(UC_X86_REG_RDX)
        name = img.cstr(rdx - B, 80) if rdx > B else "?"
        # the enum value is whatever this block just stored
        records.append((user["last"], name))
        uc.reg_write(UC_X86_REG_RIP, address + size)   # skip the registration call
    elif ins.mnemonic == "mov" and ins.op_str.startswith("dword ptr [rip"):
        try:
            user["last"] = int(ins.op_str.split(", ")[1], 16)
        except ValueError:
            pass

state = {"last": None}
uc.hook_add(UC_HOOK_CODE, hook, user_data=state)
uc.reg_write(UC_X86_REG_RSP, STACK + 0x80000)
uc.reg_write(UC_X86_REG_RBX, SCRATCH)
uc.mem_write(SCRATCH, struct.pack("<i", 0x7fffffff))   # keep every 'jg' untaken
uc.reg_write(UC_X86_REG_RBP, SCRATCH + 0x1000)
try:
    uc.emu_start(START, END, count=200000)
except UcError as e:
    print(f"(stopped: {e} at rip={uc.reg_read(UC_X86_REG_RIP):#x})")

seen = [(v, n) for v, n in records if n.startswith("DATA_PARAMETER_")]
print(f"executed registrations: {len(seen)}")
for v, n in seen:
    print(f"   {v:#04x} ({v:2d})  {n}")
names = {v: n for v, n in seen}
print()
print("ability-block cross-check against the emulated range table (min,max):")
tab = img.read(0x146c00860 - B, 0x100)
for match_idx in range(0x14, 0x31):
    dp = match_idx - 7
    print(f"   match idx {match_idx:#04x}  range {tab[2*match_idx]:3d}..{tab[2*match_idx+1]:3d}   "
          f"<- DATA_PARAMETER {dp:#04x} {names.get(dp,'?')}")
