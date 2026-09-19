#!/usr/bin/env python3
"""v2 payload (Q8 fractional, single rounding) + parameter sweep + DiagonalRun tail proof.
READ-ONLY on both images; the hook and cave exist only inside Unicorn."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct, sys
from pathlib import Path
import keystone
from unicorn import *
from unicorn import x86_const as X
from cave_alloc import Image
from runsel_emu_score import (Emu, STACK, STACK_SZ, HEAP, RET_MAGIC, i2f, INST, PRIS)
import runsel_emu_cave as C1

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
CAVE = 0x141000000
HOOK, HOOK_RET = 0x143DF5D6A, 0x143DF5D75
ATTR_ARRAY, ATTR_OFF_AWARE = 0x394, 0x14

PAYLOAD = """
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
  jbe   a1
  mov   eax, 99
a1:
  cmp   eax, 40
  jae   a2
  mov   eax, 40
a2:
  sub   eax, %(pivot)d
  imul  eax, eax, %(gain)d
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
  add   eax, ecx
  cmp   eax, %(capq)d
  jle   b1
  mov   eax, %(capq)d
b1:
  cmp   eax, -%(capq)d
  jge   b2
  mov   eax, -%(capq)d
b2:
  cvtsi2ss xmm1, eax
  mov   eax, 0x3b800000
  movd  xmm2, eax
  mulss xmm1, xmm2
  addss xmm0, xmm1
  mov   eax, 0x3f800000
  movd  xmm1, eax
  maxss xmm0, xmm1
done:
  mov   r11, 0x%(ret)x
  jmp   r11
"""


def payload(gain, noise, pivot=70, shift=2, cap=16.0):
    src = PAYLOAD % dict(aoff=ATTR_ARRAY + ATTR_OFF_AWARE, pivot=pivot,
                         gain=int(round(gain * 256)), noise=int(round(noise * 256)),
                         shift=shift, capq=int(cap * 256), ret=HOOK_RET)
    b, _ = ks.asm(src, CAVE, as_bytes=True)
    return b


LAB = C1.LAB
XS = C1.XS
ROLE = C1.ROLE


def order(v):
    return [LAB[i] for i in sorted(range(11), key=lambda i: -v[i])]


def swaps(a, b):
    oa, ob = order(a), order(b)
    return sum(1 for i in range(11) if oa[i] != ob[i]), oa, ob


if __name__ == "__main__":
    img = Image(INST)
    ZS = [0.0] * 11
    ATTR_FLAT = [70] * 11
    ATTR_REAL = [78, 92, 85, 88, 62, 66, 74, 70, 68, 55, 50]   # LW is the best off-ball runner
    stock = C1.run(img, XS, ZS, ROLE, ATTR_FLAT)
    print("stock (installed, roleBonus=20):", stock)
    print("cave size, GAIN=0.30 NOISE=4.0:", len(payload(0.30, 4.0)), "bytes")

    print("\n== identity: GAIN=0 NOISE=0 ==")
    z = C1.run(img, XS, ZS, ROLE, ATTR_FLAT, payload(0.0, 0.0))
    print("   identical:", z == stock)

    print("\n== heterogeneity ALONE (NOISE=0), OffAware = %s ==" % ATTR_REAL)
    for g in (0.10, 0.20, 0.30, 0.50):
        h = C1.run(img, XS, ZS, ROLE, ATTR_REAL, payload(g, 0.0))
        n, oa, ob = swaps(stock, h)
        print("   GAIN=%.2f  |HET|max=%.1f  scores=%s" % (g, max(abs(x - stock[i]) for i, x in enumerate(h)),
                                                          [round(x, 2) for x in h]))
        print("               order: %s   (%d positions moved)" % (ob, n))

    print("\n== noise ALONE (GAIN=0), flat attributes, z sweep to show draw variety ==")
    for nz in (2.0, 4.0, 6.0):
        seen = set()
        for k in range(12):
            ZS2 = [k * 4.0] * 11
            h = C1.run(img, XS, ZS2, ROLE, ATTR_FLAT, payload(0.0, nz))
            seen.add(tuple(order(h)))
        print("   NOISE=+-%.1f  distinct orderings over 12 pitch cells: %d" % (nz, len(seen)))
        for o in list(seen)[:4]:
            print("        ", list(o))

    print("\n== combined, recommended GAIN=0.30 NOISE=4.0 cell=4m ==")
    for k in range(6):
        ZS2 = [k * 4.0] * 11
        h = C1.run(img, XS, ZS2, ROLE, ATTR_REAL, payload(0.30, 4.0))
        print("   cell %d: %s   order %s" % (k, [round(x, 2) for x in h], order(h)))

    print("\n== hostile-input bound, GAIN=0.30 NOISE=4.0 (cap +-16) ==")
    for tag, xs2, at2 in (("x=-52.5 attr 40", [-52.5] * 11, [40] * 11),
                          ("x=-52.5 attr 255", [-52.5] * 11, [255] * 11),
                          ("x=-60 attr 0", [-60.0] * 11, [0] * 11)):
        s2 = C1.run(img, xs2, [0.0] * 11, [0] * 11, at2, payload(0.30, 4.0))
        print("   %-20s min=%.4f all>0=%s" % (tag, min(s2), all(v > 0 for v in s2)))

    print("\n== sentinel through the hooked build ==")
    s3 = C1.run(img, XS, ZS, ROLE, ATTR_REAL, payload(0.30, 4.0), target_y=-1.0)
    print("   target.y=-1 ->", s3[:4], "all exactly 0.0:", all(v == 0.0 for v in s3))
