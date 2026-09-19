#!/usr/bin/env python3
"""
emu_padinput.py — Unicorn proof of eFootball's match pad-input layer.

READ-ONLY.  The PRISTINE image is mmapped ACCESS_READ, pages are lazily copied into a
Unicorn address space, and every experiment runs the GAME'S OWN BYTES over a synthetic
pad-history ring that this script builds.  Nothing is written to the game.

    python tools/emu_padinput.py

What it proves, with numbers:

  P1  ring layout        the pad history is 100 records x 0x40 bytes with the write cursor at
                         +0x1900; record(framesAgo) = base + ((cursor - framesAgo) mod 100)*0x40;
                         qword at +0 is the LOGICAL-command bitmask.
  P2  press edge         0x14430f9b0(pad, bit, frame) is true ONLY on the frame the bit goes down.
  P3  ThinkUnitBase::vf17  0x1440d8000 — the default "should I fire?" predicate of ~40 think units
                         (ThinkUnitCursorChange among them) is exactly that press edge.
  P4  Super Cancel       0x1440e5890 (ThinkUnitSuperCancel::vf17) = isDown(0x13) && isDown(0x15).
                         0x13/0x15 are R2/R1 -> the classic R1+R2 super cancel.  This is the
                         anchor that pins logical id 0x13 = R2 and 0x15 = R1.
  P5  tap vs hold        the game's OWN descriptor builders (0x14430edf0/edb0/ee30/eec0) are run to
                         construct ThinkUnitPassAndGo's two real input sequences, then the game's
                         OWN matcher (0x14430fb40) is run over synthetic rings.  Shows the TAP
                         descriptor and the HOLD descriptor are separable, with the real threshold.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_PROT_ALL, UC_HOOK_CODE,
                     UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_HOOK_MEM_FETCH_UNMAPPED)
from unicorn import x86_const as X

import exe_map as EM

BASE = 0x140000000
PRISTINE = Path.home() / "Backups" / "eFootball" / "eFootball.exe.PRISTINE"

STACK, STACK_SZ = 0x7F0000000000, 0x200000
HEAP = 0x10000000
RING = HEAP + 0x1000          # pad history ring base
WRAP = HEAP + 0x8000          # "pad wrapper": [0] = ring base
UNIT = HEAP + 0x9000          # a synthetic ThinkUnit
CTX = HEAP + 0xA000           # a synthetic pad context: [8] = wrapper
STEPS = HEAP + 0xB000         # scratch for step descriptors
RET_MAGIC = 0x7FFFFFFF0000

# logical command ids (verified against the game's default logical->physical table)
L1, R2, L2, R1 = 0x12, 0x13, 0x14, 0x15
NAMES = {L1: "L1/LB", R2: "R2/RT", L2: "L2/LT", R1: "R1/RB",
         0x16: "Y", 0x17: "B", 0x18: "A", 0x19: "X"}

FPS_STUB = 0x14533ea80        # returns the frame rate in xmm0
COOKIE_CHK = 0x144f7e0d0      # __security_check_cookie


class Emu:
    def __init__(self, img):
        self.img = img
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        self.stubs = {}
        self.uc.mem_map(STACK, STACK_SZ, UC_PROT_ALL)
        self.uc.mem_map(HEAP, 0x20000, UC_PROT_ALL)
        self.uc.mem_map(RET_MAGIC & ~0xFFF, 0x1000, UC_PROT_ALL)
        self.uc.mem_write(RET_MAGIC, b"\xf4")
        self.uc.reg_write(X.UC_X86_REG_CR0, (self.uc.reg_read(X.UC_X86_REG_CR0) & ~4) | 2)
        self.uc.reg_write(X.UC_X86_REG_CR4, self.uc.reg_read(X.UC_X86_REG_CR4) | 0x600)
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        for h in (UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED):
            self.uc.hook_add(h, self._fault)

    def ensure(self, va, n=0x40):
        lo, hi = va & ~0xFFF, (va + n + 0xFFF) & ~0xFFF
        for p in range(lo, hi, 0x1000):
            if p in self.mapped:
                continue
            self.uc.mem_map(p, 0x1000, UC_PROT_ALL)
            rva = p - BASE
            off = self.img.rva2off(rva)
            if off is not None:
                self.uc.mem_write(p, self.img.m[off:off + 0x1000])
            self.mapped.add(p)

    def _fault(self, uc, access, address, size, value, user):
        if BASE <= address < BASE + 0x60000000:
            self.ensure(address, size)
            return True
        return False

    def _code(self, uc, address, size, user):
        fn = self.stubs.get(address)
        if fn is not None:
            fn(uc)
            sp = uc.reg_read(X.UC_X86_REG_RSP)
            ret = struct.unpack("<Q", uc.mem_read(sp, 8))[0]
            uc.reg_write(X.UC_X86_REG_RSP, sp + 8)
            uc.reg_write(X.UC_X86_REG_RIP, ret)

    def stub(self, va, fn):
        self.ensure(va, 0x10)
        self.stubs[va] = fn

    def call(self, target, rcx=0, rdx=0, r8=0, r9=0, stack=(), xmm3=0.0, count=200000):
        sp = STACK + 0x100000
        # shadow space + stack args
        for i, v in enumerate(stack):
            self.uc.mem_write(sp + 0x20 + 8 * i, struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF))
        sp -= 8
        self.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        self.uc.reg_write(X.UC_X86_REG_RSP, sp)
        for r, v in ((X.UC_X86_REG_RCX, rcx), (X.UC_X86_REG_RDX, rdx),
                     (X.UC_X86_REG_R8, r8), (X.UC_X86_REG_R9, r9)):
            self.uc.reg_write(r, v)
        self.uc.reg_write(X.UC_X86_REG_XMM3, struct.unpack("<I", struct.pack("<f", xmm3))[0])
        self.ensure(target, 0x800)
        self.uc.emu_start(target, RET_MAGIC, count=count)
        return self.uc.reg_read(X.UC_X86_REG_RAX)

    def run(self, start, stop, count=200000):
        self.ensure(start, 0x800)
        self.ensure(stop, 0x40)
        sp = STACK + 0x100000 - 8
        self.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        self.uc.reg_write(X.UC_X86_REG_RSP, sp)
        self.uc.emu_start(start, stop, count=count)


# ------------------------------------------------------------------ the synthetic pad ring
def build_ring(e, frames):
    """frames[i] = set of logical ids down i frames ago (i = 0 is 'now'). Cursor fixed at 50."""
    cursor = 50
    e.uc.mem_write(RING, b"\0" * 0x1904)
    for ago, ids in enumerate(frames):
        idx = (cursor - ago) % 100
        mask = 0
        for b in ids:
            mask |= 1 << b
        e.uc.mem_write(RING + idx * 0x40, struct.pack("<Q", mask))
        # per-command analog byte, 0xff for a digital press
        for b in ids:
            e.uc.mem_write(RING + idx * 0x40 + 0x18 + b, b"\xff")
    e.uc.mem_write(RING + 0x1900, struct.pack("<I", cursor))
    e.uc.mem_write(WRAP, struct.pack("<Q", RING))


def hold(ids, n):
    return [set(ids) for _ in range(n)]


def main():
    img = EM.Image(PRISTINE)
    print(f"image: {PRISTINE}  ({PRISTINE.stat().st_size:,} B)\n")

    def new():
        e = Emu(img)
        e.stub(FPS_STUB, lambda uc: uc.reg_write(
            X.UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", 60.0))[0]))
        e.stub(COOKIE_CHK, lambda uc: None)
        return e

    # ---------------------------------------------------------------- P1 / P2  press edge
    print("P1/P2  0x14430f9b0  pressEdge(pad, logicalId, framesAgo)")
    print("       ring: 100 x 0x40 records, cursor at +0x1900, qword@+0 = logical bitmask")
    cases = [
        ("L1 goes down this frame      ", [{L1}, set(), set(), set()], L1, 1),
        ("L1 held for 4 frames         ", hold({L1}, 4), L1, 0),
        ("L1 up                        ", [set(), set(), set(), set()], L1, 0),
        ("R1 goes down this frame      ", [{R1}, set(), set(), set()], R1, 1),
        ("R1 down, but L1 asked        ", [{R1}, set(), set(), set()], L1, 0),
        ("L1+R1 both go down           ", [{L1, R1}, set(), set(), set()], L1, 1),
    ]
    for label, frames, bit, want in cases:
        e = new()
        build_ring(e, frames)
        got = e.call(0x14430f9b0, rcx=WRAP, rdx=bit, r8=0) & 0xFF
        print(f"   {label} bit {bit:#04x} ({NAMES[bit]:5}) -> {got}   expected {want}   "
              f"{'OK' if got == want else 'MISMATCH'}")

    # ---------------------------------------------------------------- P3 base vf17
    print("\nP3  match::pad::ThinkUnitBase::vf17 @0x1440d8000 (the default trigger predicate;")
    print("    ThinkUnitCursorChange, bound to logical 0x12 = L1, uses exactly this slot)")
    for label, frames, want in [
        ("L1 press edge                ", [{L1}, set(), set(), set()], 1),
        ("L1 held (frame 2 of the hold)", hold({L1}, 6), 0),
        ("L1 released                  ", [set()] + hold({L1}, 5), 0),
    ]:
        e = new()
        build_ring(e, frames)
        e.uc.mem_write(UNIT, b"\0" * 0x60)
        e.uc.mem_write(UNIT + 8, struct.pack("<I", L1))      # [+8]  = logical button id
        e.uc.mem_write(UNIT + 0x14, struct.pack("<I", 0))    # [+0x14] = trigger mode (CursorChange: 0)
        e.uc.mem_write(CTX + 8, struct.pack("<Q", WRAP))
        got = e.call(0x1440d8000, rcx=UNIT, rdx=CTX) & 0xFF
        print(f"   {label} -> {got}   expected {want}   {'OK' if got == want else 'MISMATCH'}")

    # ---------------------------------------------------------------- P4 super cancel
    print("\nP4  match::pad::ThinkUnitSuperCancel::vf17 @0x1440e5890  (unit's [+8] = 0x13)")
    for label, frames, want in [
        ("R2 alone held                ", hold({R2}, 6), 0),
        ("R1 alone held                ", hold({R1}, 6), 0),
        ("R2+R1 held                   ", hold({R2, R1}, 6), 1),
    ]:
        e = new()
        build_ring(e, frames)
        e.uc.mem_write(UNIT, b"\0" * 0x60)
        e.uc.mem_write(UNIT + 8, struct.pack("<I", R2))
        e.uc.mem_write(CTX + 8, struct.pack("<Q", WRAP))
        got = e.call(0x1440e5890, rcx=UNIT, rdx=CTX) & 0xFF
        print(f"   {label} -> {got}   expected {want}   {'OK' if got == want else 'MISMATCH'}")

    # ------------------------------------------------- P5 the real PassAndGo input sequences
    print("\nP5  ThinkUnitPassAndGo::vf17's two REAL input sequences, built by the game's own")
    print("    descriptor builders and matched by the game's own matcher 0x14430fb40.")
    e = new()
    # run the two lazy-init blocks inside 0x1440e5280 verbatim (fps stubbed to 60)
    e.run(0x1440e548c, 0x1440e54dd)      # descriptor B  (3 steps) at 0x1486b8930
    e.run(0x1440e5508, 0x1440e5544)      # descriptor A  (2 steps) at 0x1486b88d0
    KIND = {1: "PRESS-EDGE", 2: "HELD-FOR-N", 4: "TAP (press+release within N)", 8: "MUST-BE-UP (exclusion)"}
    descs = {}
    for name, addr, n in (("A", 0x1486b88d0, 2), ("B", 0x1486b8930, 3)):
        print(f"   descriptor {name} @{addr:#x}, {n} steps:")
        steps = []
        for i in range(n):
            raw = bytes(e.uc.mem_read(addr + i * 0x28, 0x28))
            mask, kind, pa, pb = struct.unpack_from("<IIII", raw, 0)
            bit = mask.bit_length() - 1
            steps.append((bit, kind, pa, pb))
            print(f"      step[{i}] mask {mask:#010x} = bit {bit:#04x} ({NAMES.get(bit,'?'):5})  "
                  f"kind {kind} = {KIND.get(kind,'?'):30} paramA {pa}  paramB {pb}")
        descs[name] = (addr, n, steps)

    print("\n   matching real rings (frame 0 = 'now'):")
    pats = [
        ("R1 never pressed                    ", [False] * 60),
        ("R1 down now, 1 frame so far         ", [True] * 1 + [False] * 59),
        ("R1 down now, 3 frames so far        ", [True] * 3 + [False] * 57),
        ("R1 down now, 6 frames so far        ", [True] * 6 + [False] * 54),
        ("R1 down now, 20 frames so far       ", [True] * 20 + [False] * 40),
        ("R1 tapped 3f, released 1f ago       ", [False] + [True] * 3 + [False] * 56),
        ("R1 tapped 3f, released 3f ago       ", [False] * 3 + [True] * 3 + [False] * 54),
        ("R1 tapped 6f, released 1f ago       ", [False] + [True] * 6 + [False] * 53),
    ]
    for r2held in (False, True):
        print(f"   --- R2 (dash) {'HELD' if r2held else 'NOT held'} ---")
        for label, p in pats:
            frames = [({R1} if (i < len(p) and p[i]) else set()) | ({R2} if r2held else set())
                      for i in range(60)]
            out = {}
            for name, (addr, n, _) in descs.items():
                e2 = new()
                e2.run(0x1440e548c, 0x1440e54dd)
                e2.run(0x1440e5508, 0x1440e5544)
                build_ring(e2, frames)
                out[name] = e2.call(0x14430fb40, rcx=WRAP, rdx=addr, r8=n,
                                    stack=(0, 0, 0x64, 0)) & 0xFF
            fire = "FIRES" if (out["A"] or out["B"]) else "."
            print(f"     {label}  A(tap)={out['A']}  B(hold)={out['B']}   -> {fire}")

    print("\n   (A||B is what vf17 uses.  kind 8 is an EXCLUSION step — 'this button must NOT be")
    print("    down' — so the R2 step is there to keep pass-and-go off the R1+R2 super-cancel.)")

    # ------------------------------------------------- P6 ThinkUnitCursorChange, frame by frame
    print("\nP6  match::pad::ThinkUnitBase::vf8 @0x1440d7bd0 driven frame by frame for")
    print("    ThinkUnitCursorChange (logical 0x12 = L1, [+0xc]=2, [+0x10]=2, [+0x14]=0).")
    print("    Non-zero = the command id this unit emitted that frame (0x37 = Cursor Change).")
    for label, pattern in [
        ("tap L1 for 3 frames ", [0, 1, 1, 1, 0, 0, 0, 0]),
        ("hold L1 for 8 frames", [0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0]),
    ]:
        e = new()
        obj = HEAP + 0xC000
        e.stub(0x1442d6de0, lambda uc: uc.reg_write(X.UC_X86_REG_RAX, obj))
        e.stub(0x1442d6ba0, lambda uc: uc.reg_write(X.UC_X86_REG_RAX, obj))
        e.stub(0x1442d6fe0, lambda uc: uc.reg_write(X.UC_X86_REG_RAX, obj))
        e.uc.mem_write(UNIT, b"\0" * 0x60)
        e.uc.mem_write(UNIT + 8, struct.pack("<I", L1))
        e.uc.mem_write(UNIT + 0xC, struct.pack("<I", 2))
        e.uc.mem_write(UNIT + 0x10, struct.pack("<I", 2))
        e.uc.mem_write(UNIT + 0x14, struct.pack("<I", 0))
        e.uc.mem_write(UNIT + 0x18, b"\x01")
        e.uc.mem_write(CTX, struct.pack("<Q", obj))
        e.uc.mem_write(CTX + 8, struct.pack("<Q", WRAP))
        # the class's own vtable, so vf12 really is ThinkUnitCursorChange's 'mov eax,0x37'
        e.uc.mem_write(UNIT, struct.pack("<Q", 0x146ba3db8))
        hist = []
        out = []
        for down in pattern:
            hist.insert(0, {L1} if down else set())
            build_ring(e, hist + [set()] * 8)
            out.append(e.call(0x1440d7bd0, rcx=UNIT, rdx=CTX, r8=0) & 0xFFFFFFFF)
        print(f"   {label}  L1 = {pattern}")
        print(f"   {'':20}  cmd= {[hex(v) if v else 0 for v in out]}")


if __name__ == "__main__":
    main()
