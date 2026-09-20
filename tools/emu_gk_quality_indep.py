import sys, struct
sys.path.insert(0, r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b/tools")
import bpx
from unicorn import *
from unicorn.x86_const import *

im = bpx.img()
FN_LO, FN_HI = 0x144032870, 0x144032a90

STUBS = {
    0x143ea8cb0: "attr",
    0x1442d6c50: "obj1",
    0x144307000: "ballspeed",
    0x14533ea80: "fps",
    0x143eadbe0: "flag",
    0x1442d6fe0: "obj2",
    0x1442eaba0: "obj3",
}

CODE_BASE = 0x140000000
STACK = 0x7ff000000
DATA   = 0x200000000   # scratch for player/objects

def run(actionId, sub, attrs, ball_kmh=80.0, fps=60.0, flag1e=0, sit1c=0, trace=False):
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    # map code regions we need: text around the function + rip-relative constants
    # simplest: map whole image sections we can read
    for lo, hi in [(0x143e00000, 0x144400000), (0x145300000, 0x145400000),
                   (0x145a00000, 0x145b00000), (0x145ae0000, 0x145af0000),
                   (0x140000000, 0x140001000)]:
        pass
    # map big chunk of image by VA using bpx.read
    regions = [(0x143f00000, 0x200000), (0x145a80000, 0x10000), (0x145ae0000, 0x10000), (0x140000000, 0x10000)]
    mapped = []
    def mapva(va, size):
        a = va & ~0xFFF
        sz = ((va + size - a) + 0xFFF) & ~0xFFF
        try: mu.mem_map(a, sz)
        except UcError: return
        try: mu.mem_write(a, im.read_va(a, sz))
        except Exception:
            for off in range(0, sz, 0x1000):
                try: mu.mem_write(a+off, im.read_va(a+off, 0x1000))
                except Exception: pass
    mapva(FN_LO - 0x1000, (FN_HI - FN_LO) + 0x3000)
    mapva(0x140000000, 0x1000)          # jump-table base page
    mapva(0x145a8d000, 0x2000)          # 60.0 / 1000.0
    mapva(0x145ae7000, 0x2000)          # 50.0
    for sa in STUBS: mapva(sa, 0x40)    # stub entry pages must be mapped to hook
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(DATA, 0x10000)
    mu.mem_write(DATA + 0x47c0, struct.pack("<Q", DATA + 0x8000))
    mu.mem_write(DATA + 0x100 + 0x1c, struct.pack("<I", sit1c))

    mu.reg_write(UC_X86_REG_RSP, STACK)
    mu.reg_write(UC_X86_REG_RCX, DATA)
    mu.reg_write(UC_X86_REG_RDX, actionId)
    mu.reg_write(UC_X86_REG_R8D, sub)
    log = []

    def hook_code(mu, addr, size, ud):
        if addr in STUBS:
            kind = STUBS[addr]
            if kind == "attr":
                idx = mu.reg_read(UC_X86_REG_EDX)
                v = attrs.get(idx, 40)
                log.append(("attr", hex(idx), v))
                mu.reg_write(UC_X86_REG_EAX, v)
            elif kind == "ballspeed":
                mu.reg_write(UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", ball_kmh / (fps*3.6)))[0])
            elif kind == "fps":
                mu.reg_write(UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", fps))[0])
            elif kind == "flag":
                mu.reg_write(UC_X86_REG_EAX, flag1e)
            else:
                mu.reg_write(UC_X86_REG_RAX, DATA + 0x100)
            # emulate ret
            rsp = mu.reg_read(UC_X86_REG_RSP)
            ret = struct.unpack("<Q", mu.mem_read(rsp, 8))[0]
            mu.reg_write(UC_X86_REG_RSP, rsp + 8)
            mu.reg_write(UC_X86_REG_RIP, ret)
        elif trace:
            log.append(("ins", hex(addr)))
    mu.hook_add(UC_HOOK_CODE, hook_code)
    # push a sentinel return
    RET = 0x7ffe00000
    mu.mem_map(RET & ~0xFFF, 0x1000)
    mu.mem_write(STACK - 8, struct.pack("<Q", RET))
    mu.reg_write(UC_X86_REG_RSP, STACK - 8)
    try:
        mu.emu_start(FN_LO, RET)
    except UcError as e:
        return ("ERR", str(e), log)
    return mu.reg_read(UC_X86_REG_EAX), log

if __name__ == "__main__":
    ALL = {0x23:40,0x24:40,0x25:40,0x26:40}
    print("sanity:", run(0x44, 0, dict(ALL), ball_kmh=80.0))
