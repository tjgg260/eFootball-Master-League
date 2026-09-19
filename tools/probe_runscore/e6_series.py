"""E6: hook-byte check in BOTH images; noise time series; rank-churn; floor stress."""
import importlib.util, io, contextlib, struct, math, sys
spec = importlib.util.spec_from_file_location("m", "e5_cave.py")
m = importlib.util.module_from_spec(spec); sys.modules["m"] = m
with contextlib.redirect_stdout(io.StringIO()):
    try: spec.loader.exec_module(m)
    except Exception: pass
from emu_lib import Emu, X, b2f
import cave_alloc as CA

HOOK, RESUME = 0x143df5d3f, 0x143df5d4b
print("=== hook site 0x143df5d3f, 12 stolen bytes, both images ===")
for name, p in (("PRISTINE", CA.PRISTINE), ("INSTALLED", CA.EXE)):
    img = CA.Image(p)
    b = img.read_va(HOOK, RESUME - HOOK)
    print(f"  {name:9s} {b.hex()}   ({RESUME-HOOK} B)")
import capstone
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for i in md.disasm(CA.Image(CA.PRISTINE).read_va(HOOK, 12), HOOK):
    print(f"    {i.address:#x} {i.mnemonic} {i.op_str}   "
          f"{'RIP-RELATIVE!' if 'rip' in i.op_str else 'base+disp only, relocatable'}")

# ------------------------------------------------------------------ series
e = Emu(); sel, ctx = m.world(e, m.XS, m.ATTRS); n = m.setup(e)
G = struct.unpack("<Q", e.uc.mem_read(m.GLOBAL_PTR, 8))[0]
pobj = {ent: struct.unpack("<Q", e.uc.mem_read(G + ent*0x58 + 0x4058, 8))[0] for ent in range(11)}

def caved(ent):
    e.uc.reg_write(X.UC_X86_REG_XMM6, 0)
    e.call(m.VF5, rcx=sel, rdx=ctx, r8=ent)
    return b2f(e.uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF)

print("\n=== noise(t) for three runners, 30 Hz, 4 s ===")
# three attackers sprinting forward at different speeds from different x
runners = [(0, -5.0, 7.5), (4, 0.0, 6.0), (10, 5.0, 8.5)]   # ent, x0, v (m/s)
DT = 1/30.0
print("   t(s) " + "".join(f"  ent{r[0]:<2d} x   noise " for r in runners) + "  leader")
series = {r[0]: [] for r in runners}
leaders, prev_leader, flips = [], None, 0
for k in range(0, 121):
    t = k*DT
    row, sc = [], {}
    for ent, x0, v in runners:
        x = x0 + v*t
        e.wf(pobj[ent] + 0x4f4, x)
        s = caved(ent)
        base = 100.0 + x + m.K_ABIL*(m.ATTRS[ent] - m.PIVOT)
        sc[ent] = s
        series[ent].append(s - base)
        row.append(f"  {x:6.1f} {s-base:+6.2f} ")
    ld = max(sc, key=sc.get)
    leaders.append(ld)
    if prev_leader is not None and ld != prev_leader: flips += 1
    prev_leader = ld
    if k % 6 == 0:
        print(f"  {t:4.2f} " + "".join(row) + f"   {ld}")
print(f"\n  leader changed {flips} times in 4.00 s "
      f"({flips/4.0:.2f} changes/s) across 121 evaluations")
mx = max(abs(v) for s in series.values() for v in s)
print(f"  |noise| max {mx:.3f} (K_NOISE = {m.K_NOISE})")
# how fast does the noise move within one hysteresis window (0.2 s = 6 evals)?
worst = 0.0
for ent, s in series.items():
    for i in range(len(s)-6):
        worst = max(worst, abs(s[i+6]-s[i]))
print(f"  worst change over one 0.2 s hysteresis window: {worst:.3f} points")
worst1 = max(abs(s[i+1]-s[i]) for s in series.values() for i in range(len(s)-1))
print(f"  worst change between CONSECUTIVE evaluations (1/30 s): {worst1:.3f} points")

print("\n=== a player standing still ===")
e.wf(pobj[4] + 0x4f4, 12.0)
vals = {caved(4) for _ in range(20)}
print(f"  20 consecutive evaluations at x = 12.0 -> {vals}  (noise is a pure "
      f"function of position, so it cannot flicker)")

print("\n=== same x, different players: the hash decorrelates them ===")
for ent in range(11):
    e.wf(pobj[ent] + 0x4f4, 12.0)
print("   ent  score-base (= abil + noise)")
for ent in range(11):
    s = caved(ent)
    base = 100.0 + 12.0
    print(f"   {ent:2d}   {s-base:+7.3f}   (abil {m.K_ABIL*(m.ATTRS[ent]-m.PIVOT):+.2f}, "
          f"noise {s-base-m.K_ABIL*(m.ATTRS[ent]-m.PIVOT):+.3f})")

print("\n=== FLOOR stress: absurd gains, can the cave ever return <= 0? ===")
import e5_cave as _x   # noqa
for kn, ka in ((400.0, 20.0), (10000.0, 0.0)):
    src = m.PAYLOAD
    cells = dict(m.CELLVALS); cells["k_noise"] = m.f2b(kn); cells["k_abil"] = m.f2b(ka)
    e2 = Emu(); sel2, ctx2 = m.world(e2, m.XS, m.ATTRS)
    saveC, saveK = m.CELLVALS, None
    m.CELLVALS = cells
    m.setup(e2)
    m.CELLVALS = saveC
    G2 = struct.unpack("<Q", e2.uc.mem_read(m.GLOBAL_PTR, 8))[0]
    lo = 1e9
    for ent in range(11):
        p = struct.unpack("<Q", e2.uc.mem_read(G2 + ent*0x58 + 0x4058, 8))[0]
        for x in range(-52, 53):
            e2.wf(p + 0x4f4, float(x))
            e2.uc.reg_write(X.UC_X86_REG_XMM6, 0)
            e2.call(m.VF5, rcx=sel2, rdx=ctx2, r8=ent)
            lo = min(lo, b2f(e2.uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF))
    print(f"  K_NOISE={kn}, K_ABIL={ka}: minimum score over 11 players x 105 positions "
          f"= {lo:.3f}   {'FLOOR HELD (>0)' if lo > 0 else 'FLOOR BREACHED'}")
