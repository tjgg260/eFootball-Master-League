"""Emulate match::anime::action::Restart::vf8's dead-ball accuracy roll on the game's own bytes.

Fragments emulated (PRISTINE image, read-only):
  0x143f05404 .. 0x143f05445   SetPieceTaking (ATTR 0x21) -> sigma, via the real expf 0x140a24cd0
  0x143f0568b .. 0x143f0569e   sigma -> 100*sigma^2, the value compared against RandInt(0,100)
"""
import sys, struct
from pathlib import Path
TOOL = Path(r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b/tools")
sys.path.insert(0, str(TOOL))
import bpx
from unicorn import *
from unicorn.x86_const import *

im = bpx.img()
M = 1 << 20

def run(sp):
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    done = set()
    def do_map(addr):
        a = addr & ~(M - 1)
        if a in done:
            return
        done.add(a)
        mu.mem_map(a, M)
        for off in range(0, M, 0x1000):
            try:
                mu.mem_write(a + off, im.read_va(a + off, 0x1000))
            except Exception:
                pass
    for a in (0x140a00000, 0x143f00000, 0x145c00000, 0x146b00000,
              0x145d00000, 0x147800000, 0x145a00000):
        do_map(a)
    def on_unmapped(uc, access, address, size, value, user):
        do_map(address)
        return True
    mu.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    STACK = 0x200000000
    mu.mem_map(STACK, 0x100000)
    mu.reg_write(UC_X86_REG_RSP, STACK + 0x80000)
    mu.reg_write(UC_X86_REG_EAX, sp)
    # xmm9 = 1.0f, loaded at 0x143f05242 from [0x1478502b8]; the fragment starts after that
    one = struct.unpack('<f', bpx.read(0x1478502b8, 4))[0]
    assert one == 1.0, one
    mu.reg_write(UC_X86_REG_XMM9, struct.unpack('<I', struct.pack('<f', one))[0])
    mu.emu_start(0x143f05404, 0x143f05445)
    x7 = mu.reg_read(UC_X86_REG_XMM7)
    s = struct.unpack('<f', struct.pack('<Q', x7 & 0xFFFFFFFFFFFFFFFF)[:4])[0]
    mu.reg_write(UC_X86_REG_XMM7, x7)
    mu.emu_start(0x143f0568b, 0x143f0569e)
    x2 = mu.reg_read(UC_X86_REG_XMM7)
    pct = struct.unpack('<f', struct.pack('<Q', x2 & 0xFFFFFFFFFFFFFFFF)[:4])[0]
    return s, pct

if __name__ == "__main__":
    print("SetPieceTaking   sigma     100*sigma^2  (compared against RandInt(0,100) at 0x143f0569e)")
    for sp in [40, 45, 50, 55, 60, 65, 70, 72, 73, 75, 80, 85, 90, 95, 99]:
        s, pct = run(sp)
        print(f"     {sp:3d}        {s:.5f}    {pct:7.3f} %")
    # positive control: the three literal pool cells the fragment reads
    for a, want in ((0x145c36ac4, 99.0), (0x146b368f4, -59.0), (0x145d8be98, 5.5),
                    (0x145c1dd28, 2.5), (0x145a8aa4c, 100.0)):
        got = struct.unpack('<f', bpx.read(a, 4))[0]
        print(f"  control {a:#x} = {got}  (expect {want})  {'OK' if got == want else 'MISMATCH'}")
