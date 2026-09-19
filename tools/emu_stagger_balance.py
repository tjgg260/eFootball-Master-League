#!/usr/bin/env python3
"""emu_stagger_balance.py - the Balance term in match::anime::action::Stagger::vf32.

Emulates the real arithmetic slice 0x143f00ac8 .. 0x143f00b29 on the game's own bytes
and reports, per Balance rating, how many EXTRA frames a stagger is held before it may
end.  Used to compare stock (K=6.0) against falls-stagger-lock-balance.json (K=8.0,
which LENGTHENS the lock) and against the inverted specs (K=4.0 / 3.0 / 2.0).

    extra = clamp( K - trunc( x*x*K ), 0, 5 ),  x = clamp( (Balance-40)/60, 0, 1 )

Entry state reproduced from the real function:
    r14d = 5    (the clamp ceiling, loaded at 0x143f00874)
    ebx  = 0    (the clamp floor,  loaded at 0x143f00885)
    xmm7 = 60.0 (the divisor,      loaded at 0x143f00a3a)
    xmm8 = 1.0  (the x>=1 case,    loaded at 0x143f0080a)
    eax  = the Balance rating returned by ATTR_get(player, 0x2a)

Image opened READ-ONLY; K is changed by overlaying the instruction's disp32 only.

    python tools/emu_stagger_balance.py
"""
import struct, mmap
from unicorn import *
from unicorn.x86_const import *

PRISTINE = r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE"
INSTALLED = r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe"

START = 0x143f00ac8      # just after the ATTR_get call, eax = Balance
STOP = 0x143f00b29       # the second Balance read; r14d holds the clamped result
KSITE = 0x143f00af8      # movss xmm1,[rip -> K]


class Img:
    def __init__(s, p):
        s.f = open(p, 'rb')
        s.m = mmap.mmap(s.f.fileno(), 0, access=mmap.ACCESS_READ)
        d = s.m[:0x1000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        n = struct.unpack_from("<H", d, pe + 6)[0]
        o = struct.unpack_from("<H", d, pe + 20)[0]
        s.secs = []
        for i in range(n):
            x = d[pe + 24 + o + 40 * i: pe + 24 + o + 40 * (i + 1)]
            vs, va, rs, raw = struct.unpack_from("<IIII", x, 8)
            s.secs.append((va, vs, raw, rs))

    def off(s, rva):
        for va, vs, raw, rs in s.secs:
            if va <= rva < va + vs:
                d = rva - va
                return raw + d if d < rs else None
        return None

    def read(s, va, n):
        o = s.off(va - 0x140000000)
        return None if o is None else s.m[o:o + n]


def f2i(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def i2f(b):
    return struct.unpack("<f", b)[0]


def run(img, balance, kcell=None):
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    mapped = set()

    def mp(a, n):
        for p in range(a & ~0xFFF, (a + n + 0xFFF) & ~0xFFF, 0x1000):
            if p not in mapped:
                uc.mem_map(p, 0x1000)
                mapped.add(p)
                b = img.read(p, 0x1000)
                if b and len(b) == 0x1000:
                    uc.mem_write(p, b)

    def miss(uc_, t, addr, sz, v, u):
        mp(addr & ~0xFFF, 0x1000)
        return True

    uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED |
                UC_HOOK_MEM_FETCH_UNMAPPED, miss)
    mp(START, 0x200)
    uc.mem_map(0x20000000 - 0x10000, 0x20000)
    if kcell is not None:
        b = bytearray(img.read(KSITE, 8))
        b[4:8] = struct.pack("<i", kcell - (KSITE + 8))
        uc.mem_write(KSITE, bytes(b))
    uc.reg_write(UC_X86_REG_RSP, 0x20000000)
    uc.reg_write(UC_X86_REG_RAX, balance)
    uc.reg_write(UC_X86_REG_R14D, 5)
    uc.reg_write(UC_X86_REG_EBX, 0)
    uc.reg_write(UC_X86_REG_XMM7, f2i(60.0))
    uc.reg_write(UC_X86_REG_XMM8, f2i(1.0))
    uc.emu_start(START, STOP, count=2000)
    return uc.reg_read(UC_X86_REG_R14D)


def main():
    img = Img(PRISTINE)
    inst = Img(INSTALLED)
    out = []

    def P(*a):
        line = " ".join(str(x) for x in a)
        print(line)
        out.append(line)

    CELLS = [("stock 6.0", 0x145ab244c),
             ("OLD SPEC 8.0", 0x145b52fbc),
             ("4.0", 0x145ab1b48),
             ("THIS SPEC 3.0", 0x1478504e8),
             ("2.0", 0x145a8a630)]

    P("emu_stagger_balance - extra locked frames after a stagger, Stagger::vf32")
    P("real bytes 0x143f00ac8..0x143f00b29, eFootball.exe PRISTINE, K re-aimed by disp32 overlay")
    P("")
    P("site 0x143f00af8  pristine=%s  installed=%s  %s" %
      (img.read(KSITE, 8).hex().upper(), inst.read(KSITE, 8).hex().upper(),
       "SAME (still stock)" if img.read(KSITE, 8) == inst.read(KSITE, 8) else "*** DIFFERS ***"))
    P("")
    P("pool cells (read, never written - only this instruction's disp32 moves):")
    for name, c in CELLS:
        P("  %-14s %s = %s" % (name, hex(c), i2f(img.read(c, 4))))
    P("")

    BAL = [40, 50, 60, 65, 70, 75, 80, 85, 88, 90, 92, 95, 97, 99]
    P("Balance:      " + " ".join("%3d" % b for b in BAL))
    P("              " + "----" * len(BAL))
    rows = {}
    for name, c in CELLS:
        r = [run(img, b, c) for b in BAL]
        rows[name] = r
        P("  %-12s" % name + " ".join("%3d" % v for v in r))
    P("")
    P("(extra frames on top of the stagger's own cancel keyframe; 1 frame = 16.7 ms at 60 fps)")
    P("")
    P("delta vs stock, in frames:")
    for name, c in CELLS[1:]:
        d = [rows[name][i] - rows["stock 6.0"][i] for i in range(len(BAL))]
        P("  %-12s" % name + " ".join("%+3d" % v for v in d))
    P("")
    P("READ THIS: the whole term is clamped to 5 frames = 83 ms. falls-stagger-lock-balance.json")
    P("(K=8.0) ADDS up to 1 frame in the 80-92 band - it is aimed the wrong way for this")
    P("request AND it is a rounding error next to the cancel gate, which is tens of frames.")

    with open("build/emu_stagger_balance_proof.txt", "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwritten: build/emu_stagger_balance_proof.txt")


main()
