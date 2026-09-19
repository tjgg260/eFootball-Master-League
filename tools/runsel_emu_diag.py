#!/usr/bin/env python3
"""DiagonalRun::vf5 tail: prove the three exits and prove the proposed hook at 0x143e03fb4.
READ-ONLY on both images; hook + cave exist only inside Unicorn."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct, sys
from pathlib import Path
import keystone
from unicorn import *
from unicorn import x86_const as X
from cave_alloc import Image
from runsel_emu_score import Emu, STACK, STACK_SZ, HEAP, RET_MAGIC, i2f, f2i, INST, PRIS

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
CAVE = 0x141000000
TAIL_OK = 0x143E03F95        # cmp byte [rsp+0x180], 0   -> success epilogue
TAIL_BAD = 0x143E03FBA       # xorps xmm0, xmm0          -> reject
HOOK = 0x143E03FB4           # movaps xmm0, xmm9 ; jmp 0x143e03fbd   (6 bytes)
HOOK_RET = 0x143E03FBD
SELOBJ = HEAP + 0x10000
PLAYER = HEAP + 0x20000
DATAOBJ = HEAP + 0x30000
CONTAINER = HEAP + 0x40000
G_CONTAINER = 0x1486BD888
ATTR_ARRAY, ATTR_OFF_AWARE = 0x394, 0x14
IDX = 7

PAYLOAD = """
  movaps xmm0, xmm9
  cmp   edi, 0x1f
  jae   done
  movsxd r9, edi
  imul  r9, r9, 0x58
  mov   r10, 0x1486bd888
  mov   r10, qword ptr [r10]
  test  r10, r10
  jz    done
  mov   r11, qword ptr [r9 + r10 + 0x55a8]
  test  r11, r11
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
  cvttss2si ecx, dword ptr [rbp]
  cvttss2si edx, dword ptr [rbp + 8]
  sar   ecx, %(shift)d
  sar   edx, %(shift)d
  imul  ecx, ecx, 0x9e3779b1
  imul  edx, edx, 0x85ebca77
  xor   ecx, edx
  mov   edx, edi
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
  mov   eax, 0x3f800000
  movd  xmm2, eax
  addss xmm1, xmm2
  mulss xmm0, xmm1
done:
  mov   r11, 0x%(ret)x
  jmp   r11
"""


def payload(gain, noise, pivot=70, shift=2, cap=0.5):
    src = PAYLOAD % dict(aoff=ATTR_ARRAY + ATTR_OFF_AWARE, pivot=pivot,
                         gain=int(round(gain * 256)), noise=int(round(noise * 256)),
                         shift=shift, capq=int(cap * 256), ret=HOOK_RET)
    b, _ = ks.asm(src, CAVE, as_bytes=True)
    return b


def run_tail(img, start, xmm9, attr=70, px=20.0, pz=0.0, cave=None, latched_byte=0):
    ov = []
    if cave is not None:
        h, _ = ks.asm("jmp 0x%x" % CAVE, HOOK, as_bytes=True)
        assert len(h) == 5
        ov.append((HOOK, h + b"\x90"))
    e = Emu(img, overlays=ov)
    e.ensure(start, 0x200)
    if cave is not None:
        e.ensure(CAVE, len(cave) + 0x100); e.uc.mem_write(CAVE, cave)
    e.wq(G_CONTAINER, CONTAINER)
    e.wq(CONTAINER + IDX * 0x58 + 0x55a8, DATAOBJ)
    e.wq(CONTAINER + IDX * 0x58 + 0x4058, PLAYER)
    e.wb(DATAOBJ + ATTR_ARRAY + ATTR_OFF_AWARE, attr)
    e.wf(PLAYER + 0x4f4, px); e.wf(PLAYER + 0x4fc, pz)
    uc = e.uc
    entry = (STACK + STACK_SZ // 2) & ~0xF
    rsp = entry - 0x168
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.mem_write(entry, struct.pack("<Q", RET_MAGIC))     # the caller's return address
    uc.mem_write(rsp + 0x170, struct.pack("<Q", SELOBJ))  # saved rcx = selector 'this'
    uc.mem_write(rsp + 0x68, struct.pack("<Q", IDX % 11))
    uc.mem_write(rsp + 0x180, bytes([latched_byte]))
    for off in (0x90, 0xa0, 0xb0, 0xc0, 0xd0, 0xe0, 0xf0, 0x100, 0x110, 0x120):
        uc.mem_write(rsp + off, b"\x00" * 16)
    for off in (0x130, 0x138, 0x140, 0x178):
        uc.mem_write(rsp + off, struct.pack("<Q", 0))
    uc.reg_write(X.UC_X86_REG_RDI, IDX)
    uc.reg_write(X.UC_X86_REG_RBP, PLAYER + 0x4f4)
    uc.reg_write(X.UC_X86_REG_XMM9, f2i(xmm9))
    uc.emu_start(start, RET_MAGIC, count=200000)
    return i2f(uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF)


if __name__ == "__main__":
    img = Image(INST)
    print("== DiagonalRun::vf5 tail, stock ==")
    for v in (0.0, 0.5, 3.0, 12.0, 27.5):
        a = run_tail(img, TAIL_OK, v)
        b = run_tail(img, TAIL_BAD, v)
        print("   xmm9=%6.2f  success-exit returns %-8s reject-exit returns %s" % (v, a, b))

    print("\n== identity: hook + cave with GAIN=0 NOISE=0 (multiplier == 1.0) ==")
    z = payload(0.0, 0.0)
    ok = all(run_tail(img, TAIL_OK, v, cave=z) == run_tail(img, TAIL_OK, v) for v in
             (0.0, 0.5, 3.0, 12.0, 27.5))
    print("   identical on every tested xmm9:", ok)

    print("\n== multiplicative term, GAIN=0.006/attr-pt NOISE=0.12, cap +-0.5 ==")
    cv = payload(0.006, 0.12, cap=0.5)
    print("   cave size:", len(cv), "bytes")
    for attr in (40, 55, 70, 85, 99):
        row = [round(run_tail(img, TAIL_OK, 8.0, attr=attr, px=20.0 + 4 * k, cave=cv), 3) for k in range(6)]
        print("   OffAware=%3d  xmm9=8.0 -> %s" % (attr, row))
    print("   xmm9 == 0.0 stays exactly 0.0:",
          all(run_tail(img, TAIL_OK, 0.0, attr=a, cave=cv) == 0.0 for a in (40, 70, 99)))
    print("   reject exit untouched (never passes through the hook):",
          run_tail(img, TAIL_BAD, 8.0, cave=cv))
    print("   latched fast-exit path is a SEPARATE ret at 0x143e03766 returning a flat 100.0")
