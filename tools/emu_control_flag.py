#!/usr/bin/env python3
"""Emulate the REAL bytes of 0x144308db0 (the writer-input of UMatchInfo+0x41f6)
against a synthetic world, to pin the rule flag(idx) = (rank[idx] <= count[team]).
Read-only over PRISTINE."""
import struct, sys
sys.path.insert(0, r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b/tools")
import cave_alloc
from emu_anticipation import Emu, STACK, HEAP, RET_MAGIC, STACK_SZ, HEAP_SZ
import unicorn.x86_const as X

PRIS = r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE"
XOBJ = HEAP + 0x20000        # the command-config object
MINF = HEAP + 0x40000        # UMatchInfo
FN   = 0x144308db0

LIST = HEAP + 0x60000        # the 0x30-byte squad-order buffer 0x1442ee640 returns

def new():
    e = Emu(cave_alloc.Image(PRIS))
    for lo, sz in ((STACK, STACK_SZ), (HEAP, HEAP_SZ), (RET_MAGIC & ~0xFFF, 0x1000)):
        for pg in range(lo, lo + sz, 0x1000):
            e.mapped.add(pg)
    e.setregs(rsp=STACK + 0x100000)
    import struct as _s
    # STUB 0x1442ee640: the squad-order accessor. Return a buffer holding the identity
    # order 0..10 (count 11) -- i.e. squad slot k sits at list position k.
    def _sq(uc):
        buf = _s.pack("<I", 11) + b"".join(_s.pack("<I", k) for k in range(11))
        buf = buf.ljust(0x30, bytes(1))
        uc.mem_write(LIST, buf)
        uc.reg_write(X.UC_X86_REG_RAX, LIST)
    e.stubs[0x1442ee640] = _sq
    e.stubs[0x1442c4430] = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, 0xff)
    return e

def call(e, fn, rcx=0, rdx=0, r8=0, r9=0):
    sp = STACK + 0x100000 - 0x400
    e.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
    e.setregs(rsp=sp, rcx=rcx, rdx=rdx, r8=r8, r9=r9)
    e.run(fn, RET_MAGIC, count=400000)
    return e.uc.reg_read(X.UC_X86_REG_RAX) & 0xFF

def world(e, count0, count1, sel14=1, sel18=0, cursor0=0xff, cursor1=0xff, mode3308=1):
    e.uc.mem_write(XOBJ, b"\0" * 0x10000)
    e.uc.mem_write(MINF, b"\0" * 0x6000)
    e.uc.mem_write(XOBJ + 0x3c, struct.pack("<ii", count0, count1))
    e.uc.mem_write(XOBJ + 0x14, struct.pack("<ii", sel14, sel18))
    e.uc.mem_write(MINF + 0x3308, struct.pack("<i", mode3308))
    e.uc.mem_write(MINF + 0x41d8, struct.pack("<ii", cursor0, cursor1))

def run(count0, count1, **kw):
    e = new(); out = []
    for idx in range(22):
        world(e, count0, count1, **kw)
        try:
            out.append(call(e, FN, rcx=XOBJ, rdx=idx, r8=MINF))
        except Exception as ex:
            out.append("E:" + str(ex)[:24])
    return out

if __name__ == "__main__":
    print("rule check: flag[idx] for (count_team0, count_team1)")
    for c0, c1 in ((11, 0), (11, 11), (1, 0), (0, 0), (-1, -1), (3, 3), (11, -1)):
        r = run(c0, c1)
        print(f"  c0={c0:3} c1={c1:3}  team0 idx0-10 {r[:11]}  team1 idx11-21 {r[11:]}")
    print()
    print("cursor override (count 0/0, cursor player forced to rank 0):")
    for cur in (0, 5, 10, 13):
        r = run(0, 0, cursor0=cur, mode3308=2)
        print(f"  cursor0={cur:3} -> {r}")
