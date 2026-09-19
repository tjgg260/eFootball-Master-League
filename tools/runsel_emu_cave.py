#!/usr/bin/env python3
"""End-to-end emulation: ChanceSpaceRun::vf5 with the proposed hook + cave overlaid IN THE
EMULATOR ONLY, plus the DiagonalRun tail. Nothing is written to any game file."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct, sys
from pathlib import Path
import keystone, capstone
from unicorn import *
from unicorn import x86_const as X
from cave_alloc import Image
from runsel_emu_score import (Emu, STACK, STACK_SZ, HEAP, RET_MAGIC, SEL, CTX, CTXA, TEAMAI,
                       CONTAINER, PLAYER0, G_CONTAINER, i2f, f2i, ret_bool, CHANCE_VF5, PRIS, INST)

CAVE       = 0x141000000          # emulator-only stand-in for the chained cave chunks
HOOK       = 0x143DF5D6A
HOOK_RET   = 0x143DF5D75
STOLEN     = bytes.fromhex("0f28c60f28b424c0000000")   # movaps xmm0,xmm6 ; movaps xmm6,[rsp+0xc0]
ATTR_ARRAY = 0x394
ATTR_OFF_AWARE = 0x14                # DATA_PARAMETER_OFFENSE_DECISION  (enum 0x0d + 7)
DATAOBJ0   = HEAP + 0x180000

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)


def cave_asm(gain_q8, noise_q8, pivot, cell_shift):
    return """
      movaps xmm0, xmm6
      movaps xmm6, xmmword ptr [rsp+0xc0]
      cmp   ebx, 0x1f
      jae   done
      movsxd r9, ebx
      imul  r9, r9, 0x58
      mov   r10, 0x1486bd888
      mov   r10, qword ptr [r10]
      test  r10, r10
      jz    done
      mov   r11, qword ptr [r9 + r10 + 0x55a8]
      test  r11, r11
      jz    done
      mov   r10, qword ptr [r9 + r10 + 0x4058]
      test  r10, r10
      jz    done
      movzx eax, byte ptr [r11 + %(aoff)d]
      cmp   eax, 99
      jbe   attr_ok
      mov   eax, 99
    attr_ok:
      cmp   eax, 40
      jae   attr_lo_ok
      mov   eax, 40
    attr_lo_ok:
      sub   eax, %(pivot)d
      imul  eax, eax, %(gain)d
      sar   eax, 8
      cvttss2si ecx, dword ptr [r10 + 0x4f4]
      cvttss2si edx, dword ptr [r10 + 0x4fc]
      sar   ecx, %(shift)d
      sar   edx, %(shift)d
      imul  ecx, ecx, 0x9e3779b1
      imul  edx, edx, 0x85ebca77
      xor   ecx, edx
      mov   edx, ebx
      imul  edx, edx, 0xc2b2ae35
      xor   ecx, edx
      mov   edx, ecx
      shr   edx, 15
      xor   ecx, edx
      imul  ecx, ecx, 0x2545f491
      mov   edx, ecx
      shr   edx, 13
      xor   ecx, edx
      movzx ecx, cx
      sub   ecx, 0x8000
      imul  ecx, ecx, %(noise)d
      sar   ecx, 15
      sar   ecx, 8
      add   eax, ecx
      cmp   eax, 16
      jle   hi_ok
      mov   eax, 16
    hi_ok:
      cmp   eax, -16
      jge   lo_ok
      mov   eax, -16
    lo_ok:
      cvtsi2ss xmm1, eax
      addss xmm0, xmm1
      mov   eax, 0x3f800000
      movd  xmm1, eax
      maxss xmm0, xmm1
    done:
      mov   r11, 0x%(ret)x
      jmp   r11
    """ % dict(aoff=ATTR_ARRAY + ATTR_OFF_AWARE, pivot=pivot, gain=gain_q8,
               shift=cell_shift, noise=noise_q8, ret=HOOK_RET)


def assemble(src, at):
    b, _ = ks.asm(src, at, as_bytes=True)
    return b


def build(img, xs, zs, roles, attrs, cave_bytes=None, attackdir=1, kind=5, target_y=1.0, idx=0):
    ov = []
    if cave_bytes is not None:
        hook = assemble("jmp 0x%x" % CAVE, HOOK)
        assert len(hook) == 5, len(hook)
        ov.append((HOOK, hook + b"\x90" * (len(STOLEN) - 5)))
    e = Emu(img, overlays=ov)
    e.ensure(CHANCE_VF5, 0x600)
    if cave_bytes is not None:
        e.ensure(CAVE, len(cave_bytes) + 0x100)
        e.uc.mem_write(CAVE, cave_bytes)
    e.wq(G_CONTAINER, CONTAINER)
    for i in range(22):
        e.wq(CONTAINER + i * 0x58 + 0x4058, PLAYER0 + i * 0x1000)
        e.wq(CONTAINER + i * 0x58 + 0x55a8, DATAOBJ0 + i * 0x400)
        e.wb(DATAOBJ0 + i * 0x400 + ATTR_ARRAY + ATTR_OFF_AWARE, attrs[i % len(attrs)])
    e.wq(CTX + 0, CTXA); e.wq(CTX + 8, TEAMAI)
    e.wb(TEAMAI + 0x28c, attackdir & 0xFF)
    for slot in range(11):
        e.wf(SEL + 0x60 + 12 * slot + 0, 10.0)
        e.wf(SEL + 0x60 + 12 * slot + 4, target_y)
        e.wf(SEL + 0x60 + 12 * slot + 8, 0.0)
    for k in range(16):
        e.wd(SEL + 0x2c8 + 4 * k, 0x7FF if k == kind else 0)
    for i in range(len(xs)):
        e.wf(PLAYER0 + i * 0x1000 + 0x4f4, xs[i])
        e.wf(PLAYER0 + i * 0x1000 + 0x4fc, zs[i])
    e.stubs[0x143d37f30] = ret_bool(roles[idx])
    e.stubs[0x143d32a90] = ret_bool(False)
    e.stubs[0x143d37d70] = ret_bool(True)
    return e


def run(img, xs, zs, roles, attrs, cave_bytes=None, **kw):
    out = []
    for i in range(len(xs)):
        e = build(img, xs, zs, roles, attrs, cave_bytes, idx=i, **kw)
        uc = e.uc
        sp = (STACK + STACK_SZ // 2) & ~0xF
        uc.reg_write(X.UC_X86_REG_RSP, sp)
        uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RCX, SEL); uc.reg_write(X.UC_X86_REG_RDX, CTX)
        uc.reg_write(X.UC_X86_REG_R8, i); uc.reg_write(X.UC_X86_REG_R9, 0)
        for r in ("RBX", "RSI", "RDI", "RBP", "R12", "R13", "R14", "R15"):
            uc.reg_write(getattr(X, "UC_X86_REG_" + r), 0)
        try:
            uc.emu_start(CHANCE_VF5, RET_MAGIC, count=400000)
        except UcError as ex:
            print("  [!] idx %d: %s rip=%#x" % (i, ex, uc.reg_read(X.UC_X86_REG_RIP)))
            out.append(None); continue
        out.append(i2f(uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF))
    return out


LAB = ["ST", "LW", "RW", "AMF", "RB", "LB", "CM1", "CM2", "DMF", "CB1", "CB2"]
XS = [38.0, 34.0, 33.0, 26.0, 22.0, 21.0, 18.0, 16.0, 10.0, 2.0, 1.0]
ROLE = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
ATTR = [92, 88, 78, 85, 62, 66, 74, 70, 68, 55, 50]

GAIN_Q8, NOISE_Q8, PIVOT, SHIFT = int(0.20 * 256), int(3.0 * 256), 70, 2

if __name__ == "__main__":
    cave = assemble(cave_asm(GAIN_Q8, NOISE_Q8, PIVOT, SHIFT), CAVE)
    print("cave payload: %d bytes (assembled at the emulator-only address %#x)" % (len(cave), CAVE))
    img = Image(INST)
    ZS = [0.0] * 11

    print("\n== A. IDENTITY: cave with GAIN=0 NOISE=0 must reproduce stock exactly ==")
    zero = assemble(cave_asm(0, 0, PIVOT, SHIFT), CAVE)
    stock = run(img, XS, ZS, ROLE, ATTR)
    ident = run(img, XS, ZS, ROLE, ATTR, zero)
    print("   stock   :", stock)
    print("   cave(0) :", ident)
    print("   identical:", stock == ident)

    print("\n== B. hooked scores, INSTALLED image (roleBonus=20), z=0 ==")
    hooked = run(img, XS, ZS, ROLE, ATTR, cave)
    for i in range(11):
        print("   %-4s x=%5.1f role=%d OffAware=%3d  stock=%7.2f  hooked=%7.2f  delta=%+6.2f"
              % (LAB[i], XS[i], ROLE[i], ATTR[i], stock[i], hooked[i], hooked[i] - stock[i]))
    print("   stock order :", [LAB[i] for i in sorted(range(11), key=lambda i: -stock[i])])
    print("   hooked order:", [LAB[i] for i in sorted(range(11), key=lambda i: -hooked[i])])

    print("\n== C. slow-varying: sweep z 0..12 m in 0.5 m steps (4 m noise cells) ==")
    for i in (0, 1, 2, 3):
        row = []
        for k in range(25):
            ZS2 = list(ZS); ZS2[i] = k * 0.5
            row.append(round(run(img, XS, ZS2, ROLE, ATTR, cave)[i] - stock[i], 2))
        print("   %-4s: %s" % (LAB[i], row))

    print("\n== D. worst case: hostile inputs cannot produce score <= 0 ==")
    for tag, xs2, at2 in (("deep own half x=-52.5, attr 40", [-52.5] * 11, [40] * 11),
                          ("hostile attribute byte 255", [-52.5] * 11, [255] * 11),
                          ("hostile attribute byte 0", [-52.5] * 11, [0] * 11)):
        s2 = run(img, xs2, [0.0] * 11, [0] * 11, at2, cave)
        print("   %-32s min=%.4f  all>0: %s" % (tag, min(s2), all(v > 0 for v in s2)))

    print("\n== E. the 0.0 reject sentinel still returns EXACTLY 0.0 through the hooked build ==")
    s3 = run(img, XS, ZS, ROLE, ATTR, cave, target_y=-1.0)
    print("   target.y=-1 ->", s3[:3], " all exactly 0.0:", all(v == 0.0 for v in s3))
