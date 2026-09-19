"""Emulate match::ai off-ball run QUOTA function 0x1442f9a90 on the real bytes."""
import sys, struct
from pathlib import Path
REPO = Path(r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b")
sys.path.insert(0, str(REPO / "tools"))
import cave_alloc
from emu_anticipation import Emu, STACK, HEAP, RET_MAGIC
from unicorn import x86_const as X

BASE = 0x140000000
IMGS = {"INSTALLED": REPO and Path(r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe"),
        "PRISTINE":  Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")}

QUOTA   = 0x1442F9A90
GETTEAM = 0x1442D7090   # (teamCtx, playerIdx) -> team object
ROLE4   = 0x1442E1200   # (teamCtx, playerIdx, 4, 0xff) -> bool  (Overlap role test)
F_DE630 = 0x1442DE630
F_EFD260= 0x140EFD260
F_E0C00 = 0x1442E0C00
STK_CK  = 0x144F7E0D0   # __security_check_cookie
COOKIE  = 0x148250268

TEAM = HEAP + 0x60000
NAMES = {0x1d:"SecondLineSpaceRun",0x1e:"ChanceSpaceRun",0x1f:"CounterSpaceRun",0x20:"LineBreak(dead)",
         0x21:"DiagonalRun",0x26:"CenteringGet",0x27:"Overlap",0x29:"GoalGet",0x2a:"PostPlay",0x2e:"PullAway(dead)"}

def run(img, action, level, role_ok=1, counterflag=0, e0c00=0):
    e = Emu(img)
    e.ensure(COOKIE, 0x10)
    e.uc.mem_write(COOKIE, struct.pack("<Q", 0))
    e.uc.mem_write(TEAM + 0xb450, bytes([level & 0xff]))
    e.stubs[GETTEAM]  = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, TEAM)
    e.stubs[ROLE4]    = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, role_ok)
    e.stubs[F_DE630]  = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, 0)
    e.stubs[F_EFD260] = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, TEAM)
    e.stubs[F_E0C00]  = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, e0c00)
    e.stubs[STK_CK]   = lambda uc: None
    sp = STACK + 0x100000
    e.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
    e.setregs(rsp=sp, rcx=TEAM, rdx=7, r8=action, r9=counterflag)
    e.ensure(QUOTA, 0x400)
    e.writes.clear(); e.trace.clear()
    e.uc.emu_start(QUOTA, RET_MAGIC, count=20000)
    return e.uc.reg_read(X.UC_X86_REG_RAX) & 0xFF

for tag, p in IMGS.items():
    img = cave_alloc.Image(p)
    print(f"\n=== {tag} : quota = f(actionId, attackLevel)  [a-emulated, real bytes] ===")
    print(f"{'action':26} " + " ".join(f"L{l}" for l in range(5)))
    for a in sorted(NAMES):
        row = [run(img, a, l) for l in range(5)]
        print(f"{NAMES[a]:<12}({a:#04x})    " + "  ".join(str(v) for v in row))
    print("  Overlap with role-test FAILING:      " + "  ".join(str(run(img,0x27,l,role_ok=0)) for l in range(5)))
    print("  counter/trait bump (4th arg = 1):")
    for a in (0x1d,0x1e,0x1f,0x21):
        print(f"    {NAMES[a]:<22} " + "  ".join(str(run(img,a,l,counterflag=1)) for l in range(5)))
