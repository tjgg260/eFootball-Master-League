"""E5: the JOB-A cave. Real vf5 bytes + the cave spliced in, emulated."""
import struct, math
from emu_lib import Emu, X, b2f, f2b
import keystone
from asmlib import assemble

VF5, GLOBAL_PTR = 0x143df5950, 0x1486bd888
HOOK, RESUME = 0x143df5d3f, 0x143df5d4b
CAVE = 0x142000000                      # emulator-only stand-in for the chained caves
CELLS = 0x142100000                     # emulator-only stand-in for the literal cells
ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)

# ---- tunable constants the spec would expose ------------------------------
K_ABIL   = 0.20      # score points per attribute point above PIVOT
PIVOT    = 70.0
K_NOISE  = 4.0       # +/- amplitude of the noise term
INV_L    = 1.0/25.0  # spatial frequency: one full ripple per 25 m of dir*x
FLOOR    = 1.0       # the score may never be pushed to or below 0
ATTR_IDX = 0x14      # OFFENSE_DECISION / Offensive Awareness

PAYLOAD = f"""
        mulss    xmm0, dword ptr [rax + 0x4f4]        ; stolen #1  xmm0 = dir * player.x
        addss    xmm6, xmm0                           ; stolen #2  xmm6 = base + dir*x
        movaps   xmm2, xmm0                           ; keep dir*x for the noise phase
        mov      r10, {GLOBAL_PTR:#x}
        mov      r10, qword ptr [r10]
        test     r10, r10
        jz       @out
        movsxd   r11, ebx
        cmp      r11d, 0x1f
        jae      @out
        imul     r11, r11, 0x58
        mov      r10, qword ptr [r10 + r11 + 0x55a8]
        test     r10, r10
        jz       @out
        movzx    eax, byte ptr [r10 + {0x394 + ATTR_IDX:#x}]
        sub      eax, {int(PIVOT)}
        cvtsi2ss xmm1, eax
        mulss    xmm1, dword ptr [rip + RIPREL_$k_abil]
        addss    xmm6, xmm1                           ; += K_ABIL * (attr - PIVOT)
        movsxd   r11, ebx
        imul     r11d, r11d, 2654435761
        mov      eax, r11d
        shr      eax, 16
        and      eax, 0xffff
        cvtsi2ss xmm3, eax
        mulss    xmm3, dword ptr [rip + RIPREL_$inv65k]
        addss    xmm3, dword ptr [rip + RIPREL_$fmin]
        mulss    xmm3, dword ptr [rip + RIPREL_$inv_l]
        mulss    xmm2, xmm3
        shr      r11d, 4
        and      r11d, 0xffff
        cvtsi2ss xmm3, r11d
        mulss    xmm3, dword ptr [rip + RIPREL_$inv65k]
        addss    xmm2, xmm3
        cvttss2si eax, xmm2
        cvtsi2ss xmm4, eax
        comiss   xmm2, xmm4
        jae      @nofix
        subss    xmm4, dword ptr [rip + RIPREL_$one]
    nofix:
        subss    xmm2, xmm4                           ; t = frac(t) in [0,1)
        addss    xmm2, xmm2
        subss    xmm2, dword ptr [rip + RIPREL_$one]  ; u = 2t-1 in [-1,1)
        andps    xmm2, xmmword ptr [rip + RIPREL_$absmask]
        addss    xmm2, xmm2
        subss    xmm2, dword ptr [rip + RIPREL_$one]  ; tri = 2|u|-1 in [-1,1]
        mulss    xmm2, dword ptr [rip + RIPREL_$k_noise]
        addss    xmm6, xmm2
        comiss   xmm6, dword ptr [rip + RIPREL_$floor]
        jae      @out
        movss    xmm6, dword ptr [rip + RIPREL_$floor]
    out:
        jmp      {RESUME:#x}
"""

CELLVALS = {"fmin": f2b(0.6), "k_abil": f2b(K_ABIL), "inv_l": f2b(INV_L), "inv65k": f2b(1.0/65536.0),
            "one": f2b(1.0), "k_noise": f2b(K_NOISE), "floor": f2b(FLOOR)}

def setup(e):
    off = {}
    for i, (n, v) in enumerate(CELLVALS.items()):
        off[n] = CELLS + 16*i
        e.w32(CELLS + 16*i, v)
    off["absmask"] = CELLS + 0x200
    for i in range(4):
        e.w32(CELLS + 0x200 + 4*i, 0x7FFFFFFF)
    src = PAYLOAD
    code, _lbl = assemble(src, CAVE, off)
    e.map(CAVE, len(code) + 0x100)
    e.uc.mem_write(CAVE, bytes(code))
    # the hook itself
    rel = CAVE - (HOOK + 5)
    e.map(HOOK, 32)
    e.uc.mem_write(HOOK, b"\xe9" + struct.pack("<i", rel) + b"\x90" * 7)
    return len(code)

def world(e, xs, attrs, attack_dir=1):
    G = e.alloc(0xA000); e.w64(GLOBAL_PTR, G)
    for ent in range(0x1f):
        rec = e.alloc(0x600); p = e.alloc(0x5000)
        for i in range(0x40): e.w8(rec + 0x394 + i, 50)
        if ent < len(attrs): e.w8(rec + 0x394 + ATTR_IDX, attrs[ent])
        e.w8(p + 0x2bd8, ent); e.w64(p + 0x47c0, rec)
        e.wf(p + 0x4f4, xs[ent] if ent < len(xs) else 0.0)
        e.w64(G + ent*0x58 + 0x4058, p)
        e.w64(G + ent*0x58 + 0x55a8, rec)
    t = e.alloc(0x10000); e.w8(t + 0x28c, attack_dir & 0xFF)
    ctx = e.alloc(0x100); e.w64(ctx, t); e.w64(ctx + 8, t)
    sel = e.alloc(0x400)
    for s in range(11):
        b = sel + 0x60 + 12*s
        e.wf(b, 30.0); e.wf(b+4, 5.0); e.wf(b+8, 0.0)
    for k in range(16): e.w32(sel + 0x2c8 + 4*k, 0x7FF if k == 5 else 0)
    for fn, r in ((0x143d37d70,1),(0x143d37f30,0),(0x143d32a90,0)):
        e.map(fn, 16); e.uc.mem_write(fn, bytes(ks.asm(f"mov eax,{r}; ret", fn)[0]))
    return sel, ctx

def sc(e, sel, ctx, ent):
    e.uc.reg_write(X.UC_X86_REG_XMM6, 0)
    _, err = e.call(VF5, rcx=sel, rdx=ctx, r8=ent)
    return b2f(e.uc.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF), err

ATTRS = [91, 62, 75, 48, 88, 55, 70, 81, 59, 66, 95] + [50]*20
XS    = [ 5.0, 12.0, -3.0, 20.0, 8.0, 0.0, 15.0, -8.0, 25.0, 4.0, 30.0] + [0.0]*20

e = Emu(); sel, ctx = world(e, XS, ATTRS)
stock = {ent: sc(e, sel, ctx, ent)[0] for ent in range(11)}

e2 = Emu(); sel2, ctx2 = world(e2, XS, ATTRS); n = setup(e2)
print(f"cave payload assembles to {n} bytes "
      f"(~{math.ceil(n/8)+2} tier-A chunks at 13 B avg)\n")
print("=== per-player score, stock vs caved (attackDir=+1) ===")
print(" ent   x(m)  OffAwr    stock    caved    delta   (abil, noise)")
rows = []
for ent in range(11):
    s2, err = sc(e2, sel2, ctx2, ent)
    ab = K_ABIL * (ATTRS[ent] - PIVOT)
    rows.append((ent, stock[ent], s2))
    print(f"  {ent:2d}  {XS[ent]:5.1f}   {ATTRS[ent]:3d}   {stock[ent]:7.3f}  {s2:7.3f}  "
          f"{s2-stock[ent]:+7.3f}   ({ab:+.2f}, {s2-stock[ent]-ab:+.2f})  err={err}")
print("\n  stock ranking:", [r[0] for r in sorted(rows, key=lambda r: -r[1])])
print("  caved ranking:", [r[0] for r in sorted(rows, key=lambda r: -r[2])])

print("\n=== the y<0 NON-CANDIDATE gate still returns exactly 0.0 with the cave in ===")
for ent in (3, 7):
    e2.wf(sel2 + 0x60 + 12*(ent % 11) + 4, -1.0)
    s2, err = sc(e2, sel2, ctx2, ent)
    print(f"  ent {ent}: caved score = {s2!r}   {'STILL 0.0 (hook not reached)' if s2 == 0.0 else 'LEAKED'}")
    e2.wf(sel2 + 0x60 + 12*(ent % 11) + 4, 5.0)

print("\n=== noise vs position: one player walking the pitch (ent 4, OffAwr 88) ===")
print("   x(m)   caved score   noise component")
for x in range(-50, 55, 5):
    e2.wf(struct.unpack("<Q", e2.uc.mem_read(0,8))[0] if False else 0, 0)
    G = struct.unpack("<Q", e2.uc.mem_read(GLOBAL_PTR, 8))[0]
    p = struct.unpack("<Q", e2.uc.mem_read(G + 4*0x58 + 0x4058, 8))[0]
    e2.wf(p + 0x4f4, float(x))
    s2, _ = sc(e2, sel2, ctx2, 4)
    base = 100.0 + x + K_ABIL*(88-PIVOT)
    print(f"  {x:5d}   {s2:9.3f}     {s2-base:+7.3f}")
