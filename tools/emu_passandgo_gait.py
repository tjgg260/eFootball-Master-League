"""Emulate match::player::ActionPassAndGo::vf13 (0x1441bb220) on the real bytes.
vf13 is the movement-urgency (gait) chooser called once per tick for the running player.
Signature from the call site: (rcx=this, rdx=aiCtx, ...) -> eax = gait."""
import sys, struct
from pathlib import Path
REPO = Path(r"C:/Users/tjgg2/Downloads/eFootball Master League/.claude/worktrees/dt270-full-decode-12718b")
sys.path.insert(0, str(REPO / "tools"))
import cave_alloc
from emu_anticipation import Emu, STACK, HEAP, RET_MAGIC
from unicorn import x86_const as X

VF13   = 0x1441BB220
GETTEAM= 0x1442D7090   # (env, teamIdx) -> team obj   ([+0x28c] = attack direction, signed char)
GETPLR = 0x1442D6F60   # (env, playerIdx) -> match player obj ([+0x4f4] = x)
GETFLD = 0x140EFD260   # mov rax,[rcx+0x48]  -> field/situation object

CTX  = HEAP + 0x40000       # rdx : ai ctx  ([+4]=playerIdx, [+0x30]=env)
ENV  = HEAP + 0x44000
TEAM = HEAP + 0x48000
PLR  = HEAP + 0x4c000
FLD  = HEAP + 0x50000       # [+0x44 + team*20] = LINE[team]; [+0x25bbc] = reference x (ball)

def gait(img, player_x, opp_line, ball_x, attack_dir=1, player_idx=7):
    e = Emu(img)
    e.stubs[GETTEAM] = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, TEAM)
    e.stubs[GETPLR]  = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, PLR)
    e.stubs[GETFLD]  = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, FLD)
    e.uc.mem_write(TEAM + 0x28c, struct.pack("<b", attack_dir))
    e.uc.mem_write(PLR  + 0x4f4, struct.pack("<f", player_x))
    e.uc.mem_write(CTX  + 4,     struct.pack("<I", player_idx))
    e.uc.mem_write(CTX  + 0x30,  struct.pack("<Q", ENV))
    for t in (0, 1):
        e.uc.mem_write(FLD + 0x44 + t*20, struct.pack("<f", opp_line))
    e.uc.mem_write(FLD + 0x25bbc, struct.pack("<f", ball_x))
    sp = STACK + 0x100000
    e.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
    e.setregs(rsp=sp, rcx=HEAP+0x60000, rdx=CTX, r8=0, r9=0)
    e.ensure(VF13, 0x200)
    e.uc.emu_start(VF13, RET_MAGIC, count=20000)
    return e.uc.reg_read(X.UC_X86_REG_RAX) & 0xFFFFFFFF

for tag, p in (("INSTALLED", Path(r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe")),
               ("PRISTINE",  Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE"))):
    img = cave_alloc.Image(p)
    print(f"\n=== {tag}  ActionPassAndGo::vf13 gait  [a-emulated, real bytes] ===")
    print("opp line at x = 40.0, ball at x = 0.0, attack dir = +1")
    print(" runner x :  " + " ".join(f"{x:>6.1f}" for x in (20,35,40,41,42,42.4,42.5,42.6,45,50)))
    print(" gait     :  " + " ".join(f"{gait(img,x,40.0,0.0):>6d}" for x in (20,35,40,41,42,42.4,42.5,42.6,45,50)))
    print(" (runner is 'past the line' by x-40; the step is at +2.5 m)")
    print("\n ball-distance rule: opp line far away (x=200), attack dir +1, ball at x=0")
    print(" runner x :  " + " ".join(f"{x:>6.1f}" for x in (10,20,24,24.9,25,25.1,30,40)))
    print(" gait     :  " + " ".join(f"{gait(img,x,200.0,0.0):>6d}" for x in (10,20,24,24.9,25,25.1,30,40)))
    print("\n attack dir = -1 (mirror), opp line x = -40, ball x = 0")
    print(" runner x :  " + " ".join(f"{x:>7.1f}" for x in (-20,-40,-42,-42.6,-45)))
    print(" gait     :  " + " ".join(f"{gait(img,x,-40.0,0.0,attack_dir=-1):>7d}" for x in (-20,-40,-42,-42.6,-45)))

print("\n\n=== ISOLATED line rule (ball kept 10 m behind the runner so the 25 m rule never fires) ===")
for tag, p in (("INSTALLED", Path(r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe")),
               ("PRISTINE",  Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE"))):
    img = cave_alloc.Image(p)
    xs = (30,38,40,41,42,42.4,42.49,42.5,42.51,43,45)
    print(f"{tag}: opp line x=40, attack dir +1")
    print("  runner x :  " + " ".join(f"{x:>6.2f}" for x in xs))
    print("  past line:  " + " ".join(f"{x-40:>6.2f}" for x in xs))
    print("  gait     :  " + " ".join(f"{gait(img,x,40.0,x-10.0):>6d}" for x in xs))
