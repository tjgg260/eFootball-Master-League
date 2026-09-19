"""E4: run the REAL ChanceSpaceRun::vf5 bytes, then the same bytes with the
JOB-A cave spliced in, and compare scores player by player."""
import struct, math
from emu_lib import Emu, X, f2b, b2f
import keystone

VF5        = 0x143df5950
GLOBAL_PTR = 0x1486bd888
HOOK       = 0x143df5d3f          # mulss xmm0,[rax+0x4f4]   (8 B) + addss xmm6,xmm0 (4 B)
RESUME     = 0x143df5d4b
STRIDE, TBL, ARR = 0x58, 0x55a8, 0x394
ROLE_STUBS = {0x143d37d70: 1,     # "eligible for a space run"  -> true
              0x143d37f30: 0,     # role query A -> false
              0x143d32a90: 0}     # role query B -> false  (so no +20 bonus)

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)

def build_world(e, attrs, xs, attack_dir=1, kind_bit_slot=lambda s: 3, target_y=1.0):
    G = e.alloc(0x9000); e.w64(GLOBAL_PTR, G)
    for ent in range(0x1f):
        rec = e.alloc(0x600)
        e.w64(G + ent*STRIDE + TBL, rec)
        for i in range(0x40):
            e.w8(rec + ARR + i, 50)
        if ent < len(attrs):
            for idx, v in attrs[ent].items():
                e.w8(rec + ARR + idx, v)
        p = e.alloc(0x5000)
        e.w8(p + 0x2bd8, ent)
        e.w64(p + 0x47c0, rec)
        e.wf(p + 0x4f4, xs[ent] if ent < len(xs) else 0.0)
        e.w64(G + ent*STRIDE + TBL + 8, p)     # unused, keeps the block distinct
        # 0x1442d6f60 must return the player object; find its offset empirically below
    return G

e = Emu()
# --- what offset does 0x1442d6f60 read?  probe it ---------------------------
G = e.alloc(0x9000); e.w64(GLOBAL_PTR, G)
probe = 0xAB0000
for off in (0x55a8,):
    for ent in range(0x1f):
        e.w64(G + ent*STRIDE + off, probe + ent)
r, err = e.call(0x1442d6f60, rcx=0, rdx=7)
print(f"0x1442d6f60(_, 7) -> {r:#x}   (planted {probe+7:#x} at G+7*0x58+0x55a8)  err={err}")
r2, _ = e.call(0x1442d6ef0, rcx=0, rdx=7)
print(f"0x1442d6ef0(_, 7) -> {r2:#x}   SAME TABLE: {r==r2}")

# --- full world -------------------------------------------------------------
e = Emu()
OFF_ATK = 0x14        # OFFENSE_DECISION
attrs = [{OFF_ATK: v} for v in (91, 62, 75, 48, 88, 55, 70, 81, 59, 66, 95,
                                 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50)]
xs    = [ 5.0, 12.0, -3.0, 20.0, 8.0, 0.0, 15.0, -8.0, 25.0, 4.0, 30.0] + [0.0]*20
G = e.alloc(0xA000); e.w64(GLOBAL_PTR, G)
players = []
for ent in range(0x1f):
    rec = e.alloc(0x600)
    for i in range(0x40): e.w8(rec + ARR + i, 50)
    if ent < len(attrs):
        for k, v in attrs[ent].items(): e.w8(rec + ARR + k, v)
    p = e.alloc(0x5000)
    e.w8(p + 0x2bd8, ent)
    e.w64(p + 0x47c0, rec)
    e.wf(p + 0x4f4, xs[ent] if ent < len(xs) else 0.0)
    e.w64(G + ent*STRIDE + 0x4058, p)       # match-player-by-entity table
    e.w64(G + ent*STRIDE + TBL, rec)        # player-DATA-by-entity table (attrs)
    # ATTR_get reaches the byte array through ent again, so plant rec under the
    # SAME slot for the attribute path by making the player object BE the record
    players.append(p)

teamAI = e.alloc(0x10000)
e.w8(teamAI + 0x28c, 1)                 # attackDir = +1
ctx = e.alloc(0x100)
e.w64(ctx + 0, teamAI)
e.w64(ctx + 8, teamAI)
sel = e.alloc(0x400)
for slot in range(11):
    base = sel + 0x60 + 12*slot
    e.wf(base + 0, 30.0); e.wf(base + 4, 5.0); e.wf(base + 8, 0.0)   # target.y = 5 > 0
for k in range(16):                     # run-kind masks: kind 5 set for every slot
    e.w32(sel + 0x2c8 + 4*k, 0x7FF if k == 5 else 0)

for fn, ret in ROLE_STUBS.items():
    e.map(fn, 16)
    e.uc.mem_write(fn, bytes(ks.asm(f"mov eax, {ret}; ret", fn)[0]))

def score(ent):
    e.uc.reg_write(X.UC_X86_REG_XMM6, 0)
    r, err = e.call(VF5, rcx=sel, rdx=ctx, r8=ent)
    return b2f(e.uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF), err

print("\n=== STOCK ChanceSpaceRun::vf5, real bytes ===")
print("  ent  x(m)  OffAwr   score      = 100 + dir*x ?")
stock = {}
for ent in range(11):
    s, err = score(ent)
    stock[ent] = s
    print(f"   {ent:2d}  {xs[ent]:5.1f}   {attrs[ent][OFF_ATK]:3d}   {s:8.3f}    "
          f"{'OK' if abs(s-(100.0+xs[ent]))<1e-3 else 'DIFFERS'}  err={err}")

# the y<0 non-candidate gate
e.wf(sel + 0x60 + 12*4 + 4, -1.0)
s, err = score(4)
print(f"  slot 4 with target.y = -1  -> score {s}   (the 'NOT A CANDIDATE' 0.0)")
e.wf(sel + 0x60 + 12*4 + 4, 5.0)
