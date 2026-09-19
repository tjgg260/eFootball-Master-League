"""E7: 'which of three runners goes' - the realistic case, plus the per-frame-RNG
counterfactual measured on the same geometry."""
import importlib.util, io, contextlib, struct, sys, random
spec = importlib.util.spec_from_file_location("m", "e5_cave.py")
m = importlib.util.module_from_spec(spec); sys.modules["m"] = m
with contextlib.redirect_stdout(io.StringIO()):
    try: spec.loader.exec_module(m)
    except Exception: pass
from emu_lib import Emu, X, b2f

e = Emu(); sel, ctx = m.world(e, m.XS, m.ATTRS); m.setup(e)
G = struct.unpack("<Q", e.uc.mem_read(m.GLOBAL_PTR, 8))[0]
P = {ent: struct.unpack("<Q", e.uc.mem_read(G + ent*0x58 + 0x4058, 8))[0] for ent in range(11)}

def caved(ent):
    e.uc.reg_write(X.UC_X86_REG_XMM6, 0)
    e.call(m.VF5, rcx=sel, rdx=ctx, r8=ent)
    return b2f(e.uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF)

# three forwards abreast: 2 m apart, same speed, the realistic "who goes" case
R = [(0, 28.0, 7.0), (4, 30.0, 7.0), (10, 26.0, 7.0)]      # ent, x0, v
DT, N = 1/30.0, 300                                        # 10 s
print("Offensive Awareness: " + ", ".join(f"ent{e_}={m.ATTRS[e_]}" for e_, _, _ in R))
print("\n  t(s)   x0      s0      x4      s4     x10     s10   stockLeader  cavedLeader")
stock_flip = caved_flip = 0
pl = pc = None
hist = []
for k in range(N + 1):
    t = k*DT
    st, cv = {}, {}
    for ent, x0, v in R:
        x = x0 + v*t
        e.wf(P[ent] + 0x4f4, x)
        cv[ent] = caved(ent)
        st[ent] = 100.0 + x
    ls, lc = max(st, key=st.get), max(cv, key=cv.get)
    if pl is not None and ls != pl: stock_flip += 1
    if pc is not None and lc != pc: caved_flip += 1
    pl, pc = ls, lc
    hist.append((t, lc))
    if k % 30 == 0:
        print(f"  {t:4.1f} " + " ".join(f"{R[i][1]+R[i][2]*t:6.1f} {cv[R[i][0]]:7.2f}" for i in range(3))
              + f"    {ls:^11d} {lc:^11d}")
print(f"\n  stock: leader changed {stock_flip} times in {N*DT:.0f} s  (it is a fixed ordering)")
print(f"  caved: leader changed {caved_flip} times in {N*DT:.0f} s "
      f"= one hand-over every {N*DT/max(caved_flip,1):.1f} s")
runs, cur, ln = [], hist[0][1], 0
for _, l in hist:
    if l == cur: ln += 1
    else: runs.append(ln*DT); cur, ln = l, 1
runs.append(ln*DT)
print(f"  caved: uninterrupted leadership spells (s): "
      f"{[round(r,2) for r in runs]}")
print(f"         shortest spell {min(runs):.2f} s "
      f"(the hysteresis window is 0.20 s)")

print("\n=== counterfactual: the SAME geometry with per-evaluation RNG noise ===")
for amp in (4.0, 1.0):
    random.seed(1); pc2 = None; flips = 0; spells = []; cur = None; ln = 0
    for k in range(N + 1):
        t = k*DT
        sc = {ent: 100.0 + x0 + v*t + m.K_ABIL*(m.ATTRS[ent]-m.PIVOT)
                   + random.uniform(-amp, amp) for ent, x0, v in R}
        l = max(sc, key=sc.get)
        if pc2 is not None and l != pc2: flips += 1
        if l == cur: ln += 1
        else:
            if cur is not None: spells.append(ln*DT)
            cur, ln = l, 1
        pc2 = l
    spells.append(ln*DT)
    print(f"  amplitude +/-{amp}: leader changed {flips} times in {N*DT:.0f} s "
          f"({flips/(N*DT):.1f}/s), shortest spell {min(spells):.2f} s "
          f"-> {'TWITCH' if min(spells) < 0.2 else 'ok'}")
