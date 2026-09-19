#!/usr/bin/env python3
"""
emu_spin.py - emulation PROOFS for the mishit "linked side spin" work. READ-ONLY on the game.

Nothing here writes to eFootball.exe. It maps the exe's own bytes lazily into Unicorn and runs
the game's own code with controlled inputs, so every claim about axes / registers / signs is a
measured number, not a static inference.

    python tools/emu_spin.py magnus      # STEP 1 : air-force routine 0x144089620 -> Magnus truth table
    python tools/emu_spin.py builder     # STEP 2a: what 0x144018c10 really reads / writes (velocity, not spin)
    python tools/emu_spin.py chain       # STEP 2b: local spin -> ball state init -> air force (axis + sign)
    python tools/emu_spin.py hookval     # STEP 2c: what xmm6 / r15 / [rbp-0x28] hold at the hook
    python tools/emu_spin.py live        # STEP 2d: the LIVE launch path (record -> solver mode 4 -> ball init) + re-entry
    python tools/emu_spin.py cave        # STEP 4 : differential proof of the cave (+ liveness, refs, end-to-end)
    python tools/emu_spin.py traj        # tuning numbers from the game's own ball stepper 0x14408d0f0
    python tools/emu_spin.py all         # everything above
    python tools/emu_spin.py spec [--gain 0.15 --cap 3]   # re-prove, then write tools/data/patches/linked-spin.json

--gain is the POSITIVE magnitude (rev/s of side spin per degree of miss); the tool always encodes the
curl-AWAY sign (a negative float immediate). Negative / zero --gain is rejected.

Needs: unicorn, capstone (keystone for the cave checks).
"""
from __future__ import annotations

import argparse
import math
import mmap
import struct
import sys
from pathlib import Path

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED,
                     UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UC_HOOK_MEM_WRITE,
                     UC_HOOK_MEM_READ, UcError)
from unicorn import x86_const as X

EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")

DEFAULT_GAIN = 0.15

DEFAULT_CAP = 3.0
STACK = 0x7FF000000000
STACK_SZ = 0x100000
HEAP = 0x600000000000          # synthetic objects live here
HEAP_SZ = 0x400000
RET_MAGIC = 0x7FFE00000000     # return address sentinel (mapped, holds a hlt)


def f2u(f: float) -> int:
    return struct.unpack("<I", struct.pack("<f", f))[0]


def u2f(u: int) -> float:
    return struct.unpack("<f", struct.pack("<I", u & 0xFFFFFFFF))[0]


class Image:
    def __init__(self, path: Path = EXE):
        self.f = open(path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        d = self.m[:0x1000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.secs = []
        for i in range(nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            self.secs.append((s[:8].rstrip(b"\0").decode(), va, vsize, raw, rsize))
        self.size = max(va + vs for _, va, vs, _, _ in self.secs)

    def read_va(self, va: int, n: int) -> bytes:
        """Bytes as the loader would map them (zero fill for virtual-only parts)."""
        out = bytearray(n)
        rva = va - self.base
        for _, sva, vs, raw, rs in self.secs:
            lo, hi = max(rva, sva), min(rva + n, sva + min(vs, rs))
            if lo < hi:
                out[lo - rva:hi - rva] = self.m[raw + lo - sva: raw + hi - sva]
        return bytes(out)

    def f32(self, va: int) -> float:
        return struct.unpack("<f", self.read_va(va, 4))[0]


class Emu:
    """Lazy-mapping Unicorn harness. stubs: {va: callable(emu)} run INSTEAD of the callee."""

    def __init__(self, img: Image, overlay: dict[int, bytes] | None = None):
        self.img = img
        self.overlay = overlay or {}          # {va: bytes} = hypothetical patches, emulation only
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        uc.mem_map(STACK, STACK_SZ)
        uc.mem_map(HEAP, HEAP_SZ)
        uc.mem_map(RET_MAGIC, 0x1000)
        uc.mem_write(RET_MAGIC, b"\xf4")
        self.heap_top = HEAP + 0x1000
        self.stubs: dict[int, callable] = {}
        self.trace: list[int] = []
        self.calls: list[tuple[int, int]] = []
        self.do_trace = False
        self.mapped: set[int] = set()
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED,
                    self._unmapped)
        uc.hook_add(UC_HOOK_CODE, self._code)

    # -- memory ---------------------------------------------------------------------------
    def _unmapped(self, uc, access, addr, size, value, ud):
        img = self.img
        if img.base <= addr < img.base + img.size:
            b = addr & ~0xFFFF
            if b not in self.mapped:
                uc.mem_map(b, 0x10000)
                data = bytearray(img.read_va(b, 0x10000))
                for va, pb in self.overlay.items():
                    for i, byte in enumerate(pb):
                        if b <= va + i < b + 0x10000:
                            data[va + i - b] = byte
                uc.mem_write(b, bytes(data))
                self.mapped.add(b)
            return True
        rip = uc.reg_read(X.UC_X86_REG_RIP)
        self.fault = f"unmapped access {addr:#x} (size {size}) at rip={rip:#x}"
        return False

    def alloc(self, n: int, fill: bytes = b"") -> int:
        a = self.heap_top
        self.heap_top += (n + 0x3F) & ~0x3F
        if fill:
            self.uc.mem_write(a, fill)
        return a

    def wf(self, addr, *vals):
        self.uc.mem_write(addr, struct.pack(f"<{len(vals)}f", *vals))

    def rf(self, addr, n=1):
        v = struct.unpack(f"<{n}f", bytes(self.uc.mem_read(addr, 4 * n)))
        return v if n > 1 else v[0]

    def w64(self, addr, v): self.uc.mem_write(addr, struct.pack("<Q", v))
    def w32(self, addr, v): self.uc.mem_write(addr, struct.pack("<I", v & 0xFFFFFFFF))
    def w8(self, addr, v): self.uc.mem_write(addr, bytes([v & 0xFF]))

    def poke_image(self, va: int, data: bytes):
        """Write into the (copied) image, e.g. a runtime-initialised global pointer."""
        try:
            self.uc.mem_read(va, 1)
        except UcError:
            self._unmapped(self.uc, 0, va, 1, 0, None)
        self.uc.mem_write(va, data)

    # -- xmm helpers -----------------------------------------------------------------------
    def set_xmm(self, n: int, f: float):
        self.uc.reg_write(X.UC_X86_REG_XMM0 + n, f2u(f))

    def get_xmm(self, n: int) -> float:
        return u2f(self.uc.reg_read(X.UC_X86_REG_XMM0 + n) & 0xFFFFFFFF)

    def get_xmm_raw(self, n: int) -> int:
        return self.uc.reg_read(X.UC_X86_REG_XMM0 + n)

    # -- control ---------------------------------------------------------------------------
    def _code(self, uc, addr, size, ud):
        if self.do_trace:
            self.trace.append(addr)
        h = self.stubs.get(addr)
        if h is not None:
            self.calls.append((addr, uc.reg_read(X.UC_X86_REG_RCX)))
            h(self)
            self.ret()

    def ret(self):
        uc = self.uc
        rsp = uc.reg_read(X.UC_X86_REG_RSP)
        ra = struct.unpack("<Q", bytes(uc.mem_read(rsp, 8)))[0]
        uc.reg_write(X.UC_X86_REG_RSP, rsp + 8)
        uc.reg_write(X.UC_X86_REG_RIP, ra)

    def call(self, fn: int, rcx=0, rdx=0, r8=0, r9=0, stack_args=(), max_insn=2_000_000, until=None):
        uc = self.uc
        self.fault = None
        rsp = STACK + STACK_SZ - 0x4000
        rsp &= ~0xF
        rsp -= 8                                   # as after a CALL: rsp % 16 == 8
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        for i, a in enumerate(stack_args):         # 5th arg at [rsp+0x28]
            uc.mem_write(rsp + 0x28 + 8 * i, struct.pack("<Q", a))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, rcx)
        uc.reg_write(X.UC_X86_REG_RDX, rdx)
        uc.reg_write(X.UC_X86_REG_R8, r8)
        uc.reg_write(X.UC_X86_REG_R9, r9)
        try:
            uc.emu_start(fn, until or RET_MAGIC, count=max_insn)
        except UcError as e:
            rip = uc.reg_read(X.UC_X86_REG_RIP)
            if rip != (until or RET_MAGIC):
                raise RuntimeError(f"emulation stopped: {e} rip={rip:#x} {self.fault or ''}")
        return uc.reg_read(X.UC_X86_REG_RAX)


# =========================================================================================
# STEP 1 - the air-force routine 0x144089620: Magnus truth table
# =========================================================================================
AIRFORCE = 0x144089620
G_MATCH = 0x1486BD888              # runtime global the routine dereferences (+0x630 -> flag object)

# stock dt270 'ball' values (python tools/gameplay_tune.py get ball <field>), runtime struct offsets
# from tools/data/dt270_struct_offsets.json. The routine receives (struct + 8), so its [rcx+0x200]
# is struct +0x208 = magnusRate.
BALL_STOCK = {0x008: 1.0,        # airRegistNormal
              0x148: 96.995,     # dragSpeedMax
              0x14C: 56.9956,    # dragSpeedMin
              0x208: 0.035,      # magnusRate
              0x244: 105.0,      # nonSpinMax
              0x248: 45.0,       # nonSpinMin
              0x24C: 1.0}        # nonSpinRate


def airforce(emu: Emu, v, w, dt=1 / 60, ball=BALL_STOCK, knuckle=False):
    """Run the game's air-force routine. Returns the acceleration vec3 it writes."""
    out = emu.alloc(0x10)
    state = emu.alloc(0x100)                 # ball motion state: velocity at +0xc, [+0x90]=0 -> omega from arg5
    if knuckle:                              # [+0x90]!=0: 'non-spin' program, omega comes from the keyframe
        emu.w8(state + 0x90, 1)              # table state+0x2c.. (times at +0x74) via 0x1440a1460, NOT from arg5
        for i in range(6):
            emu.wf(state + 0x74 + 4 * i, 0.4 * (i + 1))
    omega = emu.alloc(0x10)
    cst = emu.alloc(0x300)
    flagobj = emu.alloc(0x100)               # [+0xca]=0 -> helper 0x1442c7f30 returns 0 (its own code runs)
    gobj = emu.alloc(0x700)
    emu.w64(gobj + 0x630, flagobj)
    emu.poke_image(G_MATCH, struct.pack("<Q", gobj))
    emu.wf(state + 0xC, *v)
    emu.wf(omega, *w)
    for off, val in ball.items():
        emu.wf(cst + off, val)
    emu.set_xmm(1, dt)
    emu.call(AIRFORCE, rcx=out, rdx=0, r8=0, r9=state, stack_args=(omega, cst + 8))
    return emu.rf(out, 3)


def cmd_magnus(img: Image):
    print("=" * 96)
    print("STEP 1 - Magnus truth table from the game's own air-force routine 0x144089620")
    print("  accel = routine(v, omega); 'magnus' = accel(omega) - accel(omega=0)  [drag+gravity cancel]")
    print("=" * 96)
    emu = Emu(img)
    base = airforce(emu, (20.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    print(f"omega=0, v=(20,0,0):  accel = ({base[0]:+.4f}, {base[1]:+.4f}, {base[2]:+.4f})"
          f"   <- gravity is in component [1] => Y IS UP in ball physics")
    rows = []
    for vname, v in (("+X", (20.0, 0, 0)), ("+Z", (0, 0, 20.0)), ("-X", (-20.0, 0, 0))):
        b = airforce(emu, v, (0, 0, 0))
        for wname, w in (("+x", (1, 0, 0)), ("-x", (-1, 0, 0)), ("+y", (0, 1, 0)), ("-y", (0, -1, 0)),
                         ("+z", (0, 0, 1)), ("-z", (0, 0, -1))):
            a = airforce(emu, v, w)
            d = tuple(a[i] - b[i] for i in range(3))
            rows.append((vname, wname, d))
    print(f"\n{'v':>3} {'omega':>6} | {'dAx':>9} {'dAy(UP)':>9} {'dAz':>9} | effect")
    for vname, wname, d in rows:
        eff = []
        if abs(d[1]) > 1e-6:
            eff.append("LIFT" if d[1] > 0 else "DIP")
        lat = [(i, d[i]) for i in (0, 2) if abs(d[i]) > 1e-6]
        for i, val in lat:
            eff.append(f"lateral {'+' if val > 0 else '-'}{'xz'[i // 2] if i else 'x'}".replace("xz", "z"))
        print(f"{vname:>3} {wname:>6} | {d[0]:+9.5f} {d[1]:+9.5f} {d[2]:+9.5f} | {', '.join(eff) or 'none'}")
    # verify it is exactly k * (omega x v)
    k = None
    a = airforce(emu, (20.0, 0, 0), (0, 1, 0)); b = airforce(emu, (20.0, 0, 0), (0, 0, 0))
    k = (a[2] - b[2]) / (-1 * 20.0)
    print(f"\nform: magnus = k * (omega x v), k = {k:.6f} at |v|=20 m/s "
          f"(= magnusRate*pi^2*0.0118126*0.108686*min(HORIZONTAL speed,23.61) = "
          f"{0.035 * math.pi ** 2 * 0.0118126 * 0.108686 * 20:.6f})")
    # generic check with an oblique case
    v, w = (12.0, 5.0, -9.0), (0.3, -0.8, 0.5)
    a = airforce(emu, v, w); b = airforce(emu, v, (0, 0, 0))
    sp = math.hypot(v[0], v[2]); kk =0.035 * math.pi ** 2 * 0.0118126 * 0.108686 * min(sp, 23.6111)
    cx = (w[1] * v[2] - w[2] * v[1], w[2] * v[0] - w[0] * v[2], w[0] * v[1] - w[1] * v[0])
    print("oblique check  game:", tuple(round(a[i] - b[i], 5) for i in range(3)),
          " k*(w x v):", tuple(round(kk * c, 5) for c in cx))
    k0 = airforce(emu, (20.0, 0, 0), (0, 0, 0), knuckle=True)
    k1 = airforce(emu, (20.0, 0, 0), (0, 50.0, 30.0), knuckle=True)
    print(f"knuckle program ([state+0x90]=1, empty keyframes): accel with omega arg (0,0,0) = "
          f"{tuple(round(c, 4) for c in k0)}, with (0,50,30) = {tuple(round(c, 4) for c in k1)}"
          f"  -> arg omega IGNORED: {k0 == k1}")
    print("""
TRUTH TABLE (ball physics frame is Y-UP: X,Z horizontal, Y vertical; gravity -9.80665 on [1])
  omega.y (spin about the VERTICAL axis)      -> pure SIDEWAYS curl, never lift
  omega horizontal & perpendicular to travel  -> pure LIFT / DIP (back/top spin)
  omega parallel to travel (rifle spin)       -> nothing
  sign: v=+X, omega=+y -> accel -Z ;  v=+X, omega=+z -> accel +Y (lift)
""")


# =========================================================================================
# STEP 2a - what 0x144018c10 (the function the old notes call "the spin builder") really does
# =========================================================================================
BUILDER = 0x144018C10
G_FPS = 0x148C22ABC                # float returned by 0x14533ea80 (sim frames per second)
P1 = (0x144018DF0, "f30f1035989db301")     # old mishit-spin P1: 45 -> 90 clamp re-aim
P2B = (0x14401914C, "f30f5935f418a701")    # old P2b: 50 -> 80
P2 = (0x144019177, "f30f590539718303")     # old P2:  0.9 -> 1.0
MEM_WRITE_T = 17                           # unicorn UC_MEM_WRITE


def prep_common(emu: Emu):
    emu.poke_image(G_FPS, struct.pack("<f", 60.0))


def run_builder(img, v_in, facing, overlay=None, lo=0.0, hi=400.0, incoming=0.0, acc=0.5, assisted=0):
    """Emulate 0x144018c10(player, info, r8=vec, r9=vec2). Returns (vec_out, vec2_out, touched)."""
    emu = Emu(img, overlay)
    prep_common(emu)
    player = emu.alloc(0x5000)
    team = emu.alloc(0x100)
    ballobj = emu.alloc(0x100)
    flagobj = emu.alloc(0x100)
    info = emu.alloc(0x200)
    vec = emu.alloc(0x40)
    vec2 = emu.alloc(0x40)
    emu.w64(player + 0x47C0, team)
    emu.uc.mem_write(player + 0x2F6E, struct.pack("<h", 1))      # kick id 1 (valid, not 0x5d)
    emu.wf(player + 0xC98, facing)
    emu.wf(vec, *v_in)
    emu.wf(vec2, 1.25, -2.5, 3.75)                               # marker "second vector"
    S = emu.stubs
    S[0x1442D6C50] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, ballobj)
    S[0x1442D6DC0] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, flagobj)
    S[0x143EDF8B0] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, 0)

    def rng(lo_, hi_):
        def h(e):
            e.wf(e.uc.reg_read(X.UC_X86_REG_RDX), lo_)
            e.wf(e.uc.reg_read(X.UC_X86_REG_R8), hi_)
        return h
    S[0x143ED7C20] = rng(-90.0, 90.0)                            # elevation range: no clamp
    S[0x143ED83D0] = rng(lo, hi)                                 # speed range km/h
    S[0x144307000] = lambda e: e.set_xmm(0, incoming)            # incoming ball speed (m/frame)
    S[0x143EDFA30] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, assisted)
    S[0x143ED71D0] = lambda e: e.set_xmm(0, acc)                 # accuracy factor f
    touched = {"r": set(), "w": set()}

    def on_mem(uc, access, addr, size, value, ud):
        for base, name in ((vec, "r8vec"), (vec2, "r9vec")):
            if base <= addr < base + 0x40:
                touched["w" if access == MEM_WRITE_T else "r"].add(f"{name}+{addr - base:#x}")
    emu.uc.hook_add(UC_HOOK_MEM_WRITE | UC_HOOK_MEM_READ, on_mem, begin=vec, end=vec2 + 0x40)
    emu.call(BUILDER, rcx=player, rdx=info, r8=vec, r9=vec2)
    return emu.rf(vec, 3), emu.rf(vec2, 3), touched


def sph(v):
    """(azimuth deg by atan2(x,z), elevation deg, |v|) - Y up."""
    h = math.hypot(v[0], v[2])
    return math.degrees(math.atan2(v[0], v[2])), math.degrees(math.atan2(v[1], h)), math.sqrt(sum(c * c for c in v))


def mk(az, el, sp):
    a, e = math.radians(az), math.radians(el)
    return (math.sin(a) * math.cos(e) * sp, math.sin(e) * sp, math.cos(a) * math.cos(e) * sp)


def cmd_builder(img: Image):
    print("=" * 96)
    print("STEP 2a - 0x144018c10 emulated (callees that need live game objects are stubbed; all maths native)")
    print("=" * 96)
    sp = 100 / 3.6 / 60                       # 100 km/h in m/frame
    v = mk(30.0, 20.0, sp)
    out, v2, t = run_builder(img, v, facing=30.0)
    print(f"in  r8 vec = {tuple(round(c, 5) for c in v)}  (az 30, elev 20, 100 km/h, facing 30)")
    print(f"out r8 vec = {tuple(round(c, 5) for c in out)}  -> az/el/|v| = {tuple(round(c, 3) for c in sph(out))}")
    print(f"r9 vec after = {v2} (marker 1.25,-2.5,3.75)")
    print(f"memory touched: reads={sorted(t['r'])} writes={sorted(t['w'])}")
    print("=> the function DECOMPOSES r8 into azimuth/elevation/speed and RE-COMPOSES it: r8 is the ball")
    print("   VELOCITY (m/frame, Y-up), not an angular velocity. r9 is never read or written.\n")
    print("clamp at 0x144018df0: travel azimuth vs body facing [player+0xc98]")
    print(f"{'case':<22} {'d_az in':>8} {'d_az out':>9} {'elev':>7} {'km/h':>7} {'vy(m/frame)':>12}")
    for label, ov in (("stock (45 deg)", None), ("P1 re-aim (90 deg)", {P1[0]: bytes.fromhex(P1[1])})):
        for d in (10.0, 40.0, 70.0, -70.0, 120.0):
            vin = mk(30.0 + d, 20.0, sp)
            o, _, _ = run_builder(img, vin, facing=30.0, overlay=ov)
            az, el, s = sph(o)
            print(f"{label:<22} {d:>8.1f} {((az - 30 + 180) % 360) - 180:>9.2f} {el:>7.2f} {s * 60 * 3.6:>7.2f} {o[1]:>12.6f}")
    print("=> the 'lean' is a clamp of the VELOCITY azimuth to within +/-45 deg of the body facing, i.e. a yaw")
    print("   about the vertical (Y) axis. It moves where the ball GOES; it writes no spin. Re-aiming it to 90")
    print("   only lets kicks leave further off the body line. Elevation, speed and vy are identical: by")
    print("   itself it can add neither curl nor lift.\n")
    print("old 'spin magnitude' patches P2b (50->80) and P2 (0.9->1.0) are SPEED edits (kick of a fast")
    print("incoming ball; final speed = max(kick speed, blend) capped at cap*hi):")
    print(f"{'case':<12} {'km/h out':>9} {'vy m/s':>8} {'apex (vy^2/2g) m':>17}")
    vin = mk(30.0, 35.0, 60 / 3.6 / 60)       # 60 km/h lofted kick, 35 deg
    for label, ov in (("stock", {}), ("P2b", {P2B[0]: bytes.fromhex(P2B[1])}),
                      ("P2b+P2", {P2B[0]: bytes.fromhex(P2B[1]), P2[0]: bytes.fromhex(P2[1])})):
        # synthetic: lo=110 km/h, hi=112, incoming ball 170 km/h, accuracy 1.0, assisted kick
        o, _, _ = run_builder(img, vin, facing=30.0, overlay=ov, lo=110.0, hi=112.0, incoming=170 / 3.6 / 60,
                              acc=1.0, assisted=1)
        az, el, s = sph(o)
        vy = o[1] * 60
        print(f"{label:<12} {s * 60 * 3.6:>9.2f} {vy:>8.3f} {vy * vy / (2 * 9.80665):>17.3f}")
    print("=> they change |v| only (elevation preserved), so vy scales with them: extra HEIGHT / CARRY, which")
    print("   is what 'ballooning' looks like - not curl. The inputs (lo/hi/incoming/accuracy) are SYNTHETIC")
    print("   stubs, so the size of the effect in a real match is NOT measured here, only its nature.\n")


# =========================================================================================
# STEP 2b - the real chain: (velocity, LOCAL spin rev/s) -> ball state -> air force
# =========================================================================================
BALLINIT = 0x14408AC90             # ball motion-state init(state, kickinfo, obj, &pos, &vel m/s, &spin, flag)
SPIN_L2W = 0x14408C7E0             # Kick solver's own local-spin -> world-omega converter


def chain(img, v_ms, spin, overlay=None):
    """Game code only: 0x14408ac90 builds the state from (v, local spin); 0x144089620 gives accel."""
    emu = Emu(img, overlay)
    prep_common(emu)
    cst = emu.alloc(0x300)
    for off, val in BALL_STOCK.items():
        emu.wf(cst + off, val)
    state = emu.alloc(0x200)
    obj = emu.alloc(0x6000)
    zero = emu.alloc(0x40)
    pos = emu.alloc(0x10); vel = emu.alloc(0x10); spn = emu.alloc(0x10)
    emu.wf(pos, 0.0, 1.0, 0.0); emu.wf(vel, *v_ms); emu.wf(spn, *spin)
    emu.stubs[0x145348D70] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, cst)      # ConstantManager.get(0x4d)
    emu.stubs[0x144300F00] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, zero)
    emu.call(BALLINIT, rcx=state, rdx=0, r8=obj, r9=pos, stack_args=(vel, spn, 1))
    omega = emu.rf(state + 0x18, 3)
    flag90 = emu.uc.mem_read(state + 0x90, 1)[0]
    # air force with omega = state+0x18 exactly as the integrator 0x14408d0f0 passes it
    out = emu.alloc(0x10)
    flagobj = emu.alloc(0x100); gobj = emu.alloc(0x700)
    emu.w64(gobj + 0x630, flagobj)
    emu.poke_image(G_MATCH, struct.pack("<Q", gobj))
    om = emu.alloc(0x10); emu.wf(om, *omega)
    emu.set_xmm(1, 1 / 60)
    emu.call(AIRFORCE, rcx=out, rdx=0, r8=0, r9=state, stack_args=(om, cst + 8))
    return emu.rf(state + 0xC, 3), omega, flag90, emu.rf(out, 3)


def lat_up(v, a):
    """Decompose accel into (toward +azimuth, up, along travel). +az unit = d/daz (sin az, 0, cos az)."""
    az = math.atan2(v[0], v[2])
    e_az = (math.cos(az), 0.0, -math.sin(az))
    h = math.hypot(v[0], v[2])
    e_f = (v[0] / h, 0.0, v[2] / h)
    return (sum(a[i] * e_az[i] for i in range(3)), a[1], sum(a[i] * e_f[i] for i in range(3)))


def cmd_chain(img: Image):
    print("=" * 96)
    print("STEP 2b - LOCAL spin (rev/s; what Kick code holds in r15 = vf8 arg5) -> world omega -> Magnus")
    print("  game code: 0x14408ac90 (state init; the mishit fn itself calls it at 0x14401887d with")
    print("  vel=r14*fps, spin=r15) then 0x144089620 (air force)")
    print("=" * 96)
    print(f"{'az':>5} {'spin(x,y,z) rev/s':>18} | {'omega world rad/s':>30} | {'d_toward+az':>11} {'d_up':>9} {'d_along':>9}")
    f90 = None
    for az in (0.0, 90.0, 215.0):
        v = mk(az, 12.0, 22.0)
        _, _, f90, a0 = chain(img, v, (0, 0, 0))
        for s in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)):
            vs, om, _, a = chain(img, v, s)
            d = tuple(a[i] - a0[i] for i in range(3))
            l, u, f = lat_up(v, d)
            print(f"{az:>5.0f} {str(s):>18} | ({om[0]:+9.4f},{om[1]:+9.4f},{om[2]:+9.4f}) | {l:>+11.5f} {u:>+9.5f} {f:>+9.5f}")
    print(f"(state[+0x90] after init = {f90}: 0 => the air-force routine takes omega from its argument)")
    emu = Emu(img); prep_common(emu)
    o = emu.alloc(0x10); s = emu.alloc(0x10); a = emu.alloc(0x10)
    emu.wf(s, 0.5, 2.0, -1.0); emu.wf(a, 215.0)
    emu.call(SPIN_L2W, rcx=o, rdx=s, r8=a)
    _, om, _, _ = chain(img, mk(215.0, 0.0, 22.0), (0.5, 2.0, -1.0))
    print(f"cross-check: Kick solver's own converter 0x14408c7e0 (spin (0.5,2,-1), az 215) = "
          f"{tuple(round(c, 4) for c in emu.rf(o, 3))}\n             state init 0x14408ac90 gives               "
          f"{tuple(round(c, 4) for c in om)}")


# =========================================================================================
# =========================================================================================
# STEP 3/4 - the cave: hook 0x1440187b4 inside the mishit master fn 0x144016a70
# =========================================================================================
# At the hook the game executes  movss [r13+0x148], xmm6  where (by the code just above it)
#   xmm6 = wrap180( azimuth(final velocity r14) - azimuth(ORIGINAL velocity [rbp-0x28]) )  = horizontal miss, deg
#   r13  = kick record, r15 = &local spin vec3 (rev/s) = arg r9 of the fn = arg5 of Kick::vf8
# and the very next thing the game does (0x14401887d) is feed r14/r15 to the ball-state init.
MISHIT_FN = 0x144016A70
HOOK = 0x1440187B4
HOOK_STOLEN = "f3410f11b548010000"          # movss dword ptr [r13+0x148], xmm6   (9 bytes, not RIP-relative)
HOOK_RET = 0x1440187BD                      # call 0x14533ea80
CAVE = 0x14105ED1E                          # the whole 86-byte int3 run 0x14105ed1e..0x14105ed73 (85 B used)
CAVE_END = 0x14105ED74
PAD_RUNS = ((0x14105ED1E, 0x14105ED74),)
HOOK_HEAD = "movaps xmm0, xmm6"             # first cave instruction lives IN the hook (3 B) to make the cave fit one run
SPEC = Path(__file__).resolve().parent / "data" / "patches" / "linked-spin.json"

GPR = ["RAX", "RBX", "RCX", "RDX", "RSI", "RDI", "RBP", "RSP", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]


def rel32(src_next: int, dst: int) -> bytes:
    return struct.pack("<i", dst - src_next)


def check_tunables(a):
    if not (a.gain > 0 and a.cap > 0):
        raise SystemExit("--gain and --cap must be POSITIVE magnitudes. The tool encodes the curl-AWAY sign itself "
                         "(a negative float immediate); a curl-BACK build is deliberately not offered.")


def build_cave(gain: float, cap: float):
    """spin.y' = clamp( spin.y + (-gain)*miss,  min(spin.y, -cap),  max(spin.y, +cap) ),  NaN miss -> no change.
    Returns ([(va, bytes)], hook_bytes, {name: va of float32 immediate})."""
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    assert gain > 0 and cap > 0
    ks = Ks(KS_ARCH_X86, KS_MODE_64)
    k = -gain                                        # measured: spin.y < 0 curls toward +azimuth (= sign of miss)
    body = [
        ("stolen", bytes.fromhex(HOOK_STOLEN)),      # movss [r13+0x148], xmm6  - verbatim
        ("cmpordss xmm0, xmm0", None),               # xmm0 = miss (set in the hook); mask = all-ones unless NaN
        ("andps xmm0, xmm6", None),                  # xmm0 = miss, or +0.0 for a NaN miss
        (f"mov eax, {f2u(k):#x}", "GAIN"), ("movd xmm1, eax", None), ("mulss xmm0, xmm1", None),
        ("addss xmm0, dword ptr [r15 + 4]", None),   # candidate = old + add
        (f"mov eax, {f2u(cap):#x}", "CAP_POS"), ("movd xmm1, eax", None),
        ("maxss xmm1, dword ptr [r15 + 4]", None),   # hi = max(+cap, old)  -> never cuts the game's own value
        ("minss xmm0, xmm1", None),
        (f"mov eax, {f2u(-cap):#x}", "CAP_NEG"), ("movd xmm1, eax", None),
        ("minss xmm1, dword ptr [r15 + 4]", None),   # lo = min(-cap, old)
        ("maxss xmm0, xmm1", None),
        ("movss dword ptr [r15 + 4], xmm0", None),
    ]
    tun = {}
    code = b""
    for text, tag in body:
        if isinstance(tag, bytes):
            code += tag
            continue
        enc, _ = ks.asm(text, CAVE + len(code))
        if tag:
            tun[tag] = CAVE + len(code) + 1          # imm32 follows the b8 opcode
        code += bytes(enc)
    code += bytes([0xE9]) + rel32(CAVE + len(code) + 5, HOOK_RET)
    assert CAVE + len(code) <= CAVE_END, f"cave too long: {len(code)}"
    head, _ = ks.asm(HOOK_HEAD, HOOK)
    head = bytes(head)
    hook = head + bytes([0xE9]) + rel32(HOOK + len(head) + 5, CAVE)
    hook += bytes([0x90]) * (len(bytes.fromhex(HOOK_STOLEN)) - len(hook))
    assert len(hook) == len(bytes.fromhex(HOOK_STOLEN))
    return [(CAVE, code)], hook, tun


def model(old: float, miss: float, gain: float, cap: float) -> float:
    """Independent float32 model of what the cave must compute."""
    import numpy as np
    f = np.float32
    with np.errstate(all="ignore"):
        m = f(0.0) if miss != miss else f(miss)
        new = f(f(old) + f(m * f(-gain)))
        new = min(new, max(f(cap), f(old)))
        new = max(new, min(f(-cap), f(old)))
    return float(new)


def snapshot(uc):
    st = {r: uc.reg_read(getattr(X, f"UC_X86_REG_{r}")) for r in GPR}
    st["RFLAGS"] = uc.reg_read(X.UC_X86_REG_EFLAGS)
    st["MXCSR"] = uc.reg_read(X.UC_X86_REG_MXCSR)
    for i in range(16):
        st[f"XMM{i}"] = uc.reg_read(X.UC_X86_REG_XMM0 + i)
    return st


def run_hook(img, overlay, hmiss_bits: int, spin, flags=0x8D7):
    """Execute from HOOK until HOOK_RET with marker values everywhere. Returns (state, writes, trace, addrs)."""
    emu = Emu(img, overlay)
    uc = emu.uc
    rec = emu.alloc(0x200, b"\xA5" * 0x200)
    spn = emu.alloc(0x40, b"\x5A" * 0x40)
    emu.wf(spn, *spin)
    for i, r in enumerate(GPR):
        uc.reg_write(getattr(X, f"UC_X86_REG_{r}"), 0x1111111111111111 * (i + 1) & 0xFFFFFFFFFFFFFFFF)
    uc.reg_write(X.UC_X86_REG_R13, rec)
    uc.reg_write(X.UC_X86_REG_R15, spn)
    uc.reg_write(X.UC_X86_REG_RSP, STACK + STACK_SZ - 0x8000)
    for i in range(16):
        uc.reg_write(X.UC_X86_REG_XMM0 + i, (0xABCD0000 + i) << 96 | (0x1234 + i) << 64 | (0x77770000 + i) << 32 | f2u(100.0 + i))
    uc.reg_write(X.UC_X86_REG_XMM6, (0xDEAD << 96) | (0xBEEF << 64) | (0xCAFE << 32) | hmiss_bits)
    uc.reg_write(X.UC_X86_REG_EFLAGS, flags)            # CF PF AF ZF SF OF all set
    writes = []
    uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, ac, ad, sz, val, ud: writes.append((ad, sz, val & (1 << 8 * sz) - 1)))
    emu.do_trace = True
    uc.emu_start(HOOK, HOOK_RET, count=200)
    assert uc.reg_read(X.UC_X86_REG_RIP) == HOOK_RET, hex(uc.reg_read(X.UC_X86_REG_RIP))
    return snapshot(uc), writes, emu.trace, (rec, spn), emu


def run_continuation(img, garbage: int):
    """STOCK code from HOOK_RET to 0x1440187f8 (past call 0x14533ea80 and call 0x144300f00, both native)
    with rax/xmm0/xmm1 = garbage: proves those three are dead at the hook's return point."""
    emu = Emu(img)
    prep_common(emu)
    uc = emu.uc
    frame = emu.alloc(0x1000)
    obj = emu.alloc(0x6000)
    for i, r in enumerate(GPR):
        uc.reg_write(getattr(X, f"UC_X86_REG_{r}"), 0x0101010101010101 * (i + 1))
    uc.reg_write(X.UC_X86_REG_RBP, frame + 0x800)
    uc.reg_write(X.UC_X86_REG_R12, obj)
    uc.reg_write(X.UC_X86_REG_RSP, STACK + STACK_SZ - 0x8000)
    emu.wf(frame + 0x800 - 0x38, 0.3, 0.1, 0.2)
    for i in range(16):
        uc.reg_write(X.UC_X86_REG_XMM0 + i, 0x4000000040000000 + i)
    uc.reg_write(X.UC_X86_REG_RAX, garbage)
    uc.reg_write(X.UC_X86_REG_XMM0, garbage * 3)
    uc.reg_write(X.UC_X86_REG_XMM1, garbage * 7)
    writes = []
    uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, ac, ad, sz, val, ud: writes.append((ad, sz, val & (1 << 8 * sz) - 1)))
    uc.emu_start(HOOK_RET, 0x1440187F8, count=500)
    assert uc.reg_read(X.UC_X86_REG_RIP) == 0x1440187F8
    return snapshot(uc), writes


def cmd_hookval(img: Image, a):
    """What do xmm6 / r15 / [rbp-0x28] hold at the hook? Emulate the game's own code around it."""
    print("=" * 96)
    print("STEP 2c - register identity at the hook 0x1440187b4, from the game's own code")
    print("=" * 96)
    # ---- head of 0x144016a70: entry -> just before the miss-builder call (0x144016d3d) -------------
    emu = Emu(img); prep_common(emu)
    player = emu.alloc(0x5000); team = emu.alloc(0x100); obj = emu.alloc(0x200); rec = emu.alloc(0x200)
    vel = emu.alloc(0x10); spn = emu.alloc(0x10); loc = emu.alloc(0x10)
    emu.w64(player + 0x47C0, team)
    emu.uc.mem_write(player + 0x2F6E, struct.pack("<h", 1))
    v0 = mk(37.0, 9.0, 80 / 3.6 / 60)
    emu.wf(vel, *v0); emu.wf(spn, -1.5, 0.75, 0.0)
    emu.stubs[0x1442D6DC0] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, obj)
    emu.stubs[0x1442D6C50] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, obj)
    emu.stubs[0x143EDA730] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, 1)
    emu.call(MISHIT_FN, rcx=player, rdx=rec, r8=vel, r9=spn, stack_args=(loc, 0), until=0x144016D3D)
    uc = emu.uc
    rbp, rsp = uc.reg_read(X.UC_X86_REG_RBP), uc.reg_read(X.UC_X86_REG_RSP)
    print(f"head: entry r8 = velocity az 37.0 el 9.0 80 km/h, r9 = spin (-1.5, 0.75, 0)")
    print(f"  at 0x144016d3d (call miss builder): r14 == r8: {uc.reg_read(X.UC_X86_REG_R14) == vel}, "
          f"r15 == r9: {uc.reg_read(X.UC_X86_REG_R15) == spn}, r13 == rdx(kick record): {uc.reg_read(X.UC_X86_REG_R13) == rec}")
    print(f"  [rbp-0x28] = {emu.rf(rbp - 0x28):.3f} deg (original azimuth)   input triple [rsp+0x58..] = "
          f"{tuple(round(c, 3) for c in emu.rf(rsp + 0x58, 3))} (az, elev, m/frame)   [rbp+0x38..] copy of spin = "
          f"{emu.rf(rbp + 0x38, 3)}")
    # ---- type-4 randomiser 0x14401a060: which triple is input, which is output -----------------------
    emu = Emu(img); prep_common(emu)
    player = emu.alloc(0x5000); team = emu.alloc(0x100); obj = emu.alloc(0x200); zero = emu.alloc(0x100)
    kt = emu.alloc(0x40); miss = emu.alloc(0x80); tin = emu.alloc(0x10); tout = emu.alloc(0x10)
    emu.w64(player + 0x47C0, team)
    emu.wf(miss + 0x10, 22.5); emu.wf(miss + 0x14, 0.5); emu.wf(miss + 0x18, 100.0)      # horizontal block
    emu.wf(miss + 0x20, 10.0); emu.wf(miss + 0x24, 0.5); emu.wf(miss + 0x28, 100.0)     # vertical block
    emu.wf(miss + 0x30, 0.2); emu.wf(miss + 0x34, 0.5); emu.wf(miss + 0x38, 100.0)      # speed block
    emu.wf(tin, 37.0, 9.0, 0.37); emu.wf(tout, 37.0, 9.0, 0.37)
    emu.stubs[0x1442D6C50] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, obj)
    emu.stubs[0x143EA9250] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, obj)
    emu.stubs[0x144345EB0] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, 80)      # rng(0..100) -> 80 => |80-50|/50 = 0.6
    emu.stubs[0x143EAFD30] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, 1)       # coin flip -> +
    emu.stubs[0x144307180] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, zero)
    wr = []
    emu.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, ac, ad, sz, val, ud: wr.append(ad), begin=tin, end=tout + 0x10)
    emu.call(0x14401A060, rcx=player, rdx=kt, r8=miss, r9=tin, stack_args=(tout,))
    print(f"type-4 randomiser 0x14401a060 (rng stubbed to 0.6, sign +, errMax 22.5):")
    print(f"  r9 triple after   = {tuple(round(c, 3) for c in emu.rf(tin, 3))}   writes into it: {sum(1 for w in wr if w < tin + 0x10)}  (INPUT, untouched)")
    print(f"  arg5 triple after = {tuple(round(c, 3) for c in emu.rf(tout, 3))}   (OUTPUT: az + 0.6*22.5 = 50.5)")
    print("  caller then sets [rbp-0x28] = r9-triple.az (0x144016eba) and rebuilds r14 from the arg5 triple (0x144017558..)")
    # ---- tail: 0x1440186cb -> hook, the game computes xmm6 itself -------------------------------------
    print("tail: game code 0x1440186cb -> 0x1440187b4 run with synthetic final velocity r14 and [rbp-0x28]:")
    print(f"{'orig az':>8} {'final az':>9} | {'xmm6 at hook':>12} {'expected wrap180(final-orig)':>29}")
    good = True
    for oaz, faz in ((37.0, 49.0), (37.0, 25.0), (350.0, 8.0), (5.0, 352.5), (180.0, 181.0)):
        emu = Emu(img); prep_common(emu)
        uc = emu.uc
        frame = emu.alloc(0x1000); rec = emu.alloc(0x200); vel = emu.alloc(0x10); spn = emu.alloc(0x10)
        rbp = frame + 0x400
        rsp = STACK + STACK_SZ - 0x8000
        emu.wf(vel, *mk(faz, 11.0, 0.35)); emu.wf(rbp - 0x28, oaz); emu.wf(rsp + 0x6C, 9.0); emu.wf(rbp - 0x6C, 0.37)
        uc.reg_write(X.UC_X86_REG_RBP, rbp); uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_R14, vel); uc.reg_write(X.UC_X86_REG_R13, rec); uc.reg_write(X.UC_X86_REG_R15, spn)
        emu.set_xmm(9, 0.0); emu.set_xmm(13, 1.0); emu.set_xmm(15, -1.0)       # fn-wide constants held in xmm9/13/15
        uc.emu_start(0x1440186CB, HOOK, count=5000)
        x6 = emu.get_xmm(6)
        exp = ((faz - oaz + 180.0) % 360.0) - 180.0
        good &= abs(x6 - exp) < 0.2
        print(f"{oaz:>8.1f} {faz:>9.1f} | {x6:>12.3f} {exp:>29.3f}   r15 unchanged: {uc.reg_read(X.UC_X86_REG_R15) == spn}")
    print(f"=> xmm6 at the hook = signed horizontal miss in degrees (final - intended azimuth), wrapped. "
          f"{'OK' if good else 'FAIL'}")
    # ---- same tail WITH the patch overlaid: game computes the miss, hook + cave consume it -------------
    parts, hook, _ = build_cave(a.gain, a.cap)
    overlay = {HOOK: hook}
    overlay.update(dict(parts))
    print("same tail with the hook + cave bytes overlaid, run to the return address (spin starts at (-0.7, 0.2, 0.25)):")
    for oaz, faz in ((37.0, 49.0), (37.0, 25.0), (350.0, 8.0), (5.0, 352.5)):
        emu = Emu(img, overlay); prep_common(emu)
        uc = emu.uc
        frame = emu.alloc(0x1000); rec = emu.alloc(0x200); vel = emu.alloc(0x10); spn = emu.alloc(0x10)
        rbp = frame + 0x400
        rsp = STACK + STACK_SZ - 0x8000
        emu.wf(vel, *mk(faz, 11.0, 0.35)); emu.wf(rbp - 0x28, oaz); emu.wf(rsp + 0x6C, 9.0); emu.wf(rbp - 0x6C, 0.37)
        emu.wf(spn, -0.7, 0.2, 0.25)
        uc.reg_write(X.UC_X86_REG_RBP, rbp); uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_R14, vel); uc.reg_write(X.UC_X86_REG_R13, rec); uc.reg_write(X.UC_X86_REG_R15, spn)
        emu.set_xmm(9, 0.0); emu.set_xmm(13, 1.0); emu.set_xmm(15, -1.0)
        uc.emu_start(0x1440186CB, HOOK_RET, count=5000)
        at_ret = uc.reg_read(X.UC_X86_REG_RIP) == HOOK_RET
        miss = emu.rf(rec + 0x148)
        sp = emu.rf(spn, 3)
        exp = model(0.2, miss, a.gain, a.cap)
        okrow = at_ret and sp[1] == exp and sp[0] == u2f(f2u(-0.7)) and sp[2] == 0.25 and (sp[1] - 0.2) * miss < 0
        good &= okrow
        print(f"   az {oaz:>5.1f} -> {faz:>5.1f}: record+0x148 = {miss:+8.3f} deg, spin = ({sp[0]:.2f}, {sp[1]:+.4f}, {sp[2]:.2f}), "
              f"rip = {uc.reg_read(X.UC_X86_REG_RIP):#x}  {'OK' if okrow else 'FAIL'}")
    print("   (positive miss = azimuth increased -> spin.y pushed NEGATIVE -> curls toward increasing azimuth, per `chain`)\n")
    return good


def pdata_ranges(img: Image):
    """[(begin_va, end_va)] of every RUNTIME_FUNCTION chunk (exception directory)."""
    d = img.m[:0x1000]
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    rva, size = struct.unpack_from("<II", d, pe + 24 + 112 + 8 * 3)
    raw = img.read_va(img.base + rva, size)
    return [(img.base + b, img.base + e) for b, e, _ in struct.iter_unpack("<III", raw[:size - size % 12]) if b]


def scan_refs(img: Image, ranges):
    """Could anything in the image transfer control into / point at the given VA ranges?
    rel32 call/jmp/jcc and rel8 jmp/jcc/loop from every EXECUTABLE section (every byte offset, no alignment or
    instruction-boundary assumption, so junk bytes can produce false positives that must be reviewed), plus absolute
    8-byte pointers from every section. Chunked: the image is ~350 MB."""
    import numpy as np
    hits = []
    d = img.m[:0x1000]
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    CH = 8 << 20
    for i in range(nsec):
        sh = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
        vsize, sva, rsize, raw = struct.unpack_from("<IIII", sh, 8)
        execable = bool(struct.unpack_from("<I", sh, 36)[0] & 0x20000000)      # IMAGE_SCN_MEM_EXECUTE
        n = min(vsize, rsize)
        for c in range(0, n, CH):
            blk = np.frombuffer(img.m[raw + c: raw + min(n, c + CH + 8)], dtype=np.uint8)
            m = len(blk) - 8
            if m <= 0:
                continue
            base = img.base + sva + c
            w = lambda k: blk[k:k + m].astype(np.int64)                         # noqa: E731
            lo32 = w(0) | (w(1) << 8) | (w(2) << 16) | (w(3) << 24)
            hi32 = w(4) | (w(5) << 8) | (w(6) << 16) | (w(7) << 24)
            full = (hi32 << 32) | lo32
            for lo, hi in ranges:
                idx = np.flatnonzero((full >= lo) & (full < hi))
                hits += [("ptr64", base + int(j), int(full[j])) for j in idx]
            if not execable:
                continue
            pos = np.arange(m, dtype=np.int64)
            rel = w(1) | (w(2) << 8) | (w(3) << 16) | (w(4) << 24)
            rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
            tgt32 = base + pos + 5 + rel              # opcode byte at pos, rel32 at pos+1 (E8/E9; 0F 8x has its 0F at pos-1)
            op = blk[:m]
            is_e = (op == 0xE8) | (op == 0xE9)
            is_j = np.zeros(m, dtype=bool)
            is_j[1:] = (op[:-1] == 0x0F) & ((op[1:] & 0xF0) == 0x80)
            if c:                                      # 0F at the last byte of the previous chunk
                prev = img.m[raw + c - 1]
                is_j[0] = prev == 0x0F and (int(op[0]) & 0xF0) == 0x80
            rel8 = w(1)
            rel8 = np.where(rel8 >= 128, rel8 - 256, rel8)
            tgt8 = base + pos + 2 + rel8
            is_s = (op == 0xEB) | ((op & 0xF0) == 0x70) | ((op & 0xFC) == 0xE0)
            for lo, hi in ranges:
                for kind, mask, tg in (("rel32", is_e | is_j, tgt32), ("rel8", is_s, tgt8)):
                    idx = np.flatnonzero(mask & (tg >= lo) & (tg < hi))
                    hits += [(kind, base + int(j), int(tg[j])) for j in idx]
    return sorted(set(hits))


def cmd_cave(img: Image, a):
    import capstone
    check_tunables(a)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    parts, hook, tun = build_cave(a.gain, a.cap)
    print("=" * 96)
    print(f"STEP 3/4 - cave proof   gain={a.gain} rev/s per deg (curl away), result cap=+/-{a.cap} rev/s "
          f"(reached at a {a.cap / a.gain:.1f} deg miss on a ball with no side spin)")
    print("  spin.y' = clamp( spin.y + (-gain)*miss,  min(spin.y,-cap),  max(spin.y,+cap) );  NaN miss -> no change")
    print("=" * 96)
    stock_hook = img.read_va(HOOK, len(hook))
    print(f"stock bytes at hook {HOOK:#x}: {stock_hook.hex()}  (expected {HOOK_STOLEN}) "
          f"{'OK' if stock_hook.hex() == HOOK_STOLEN else 'MISMATCH'}")
    assert stock_hook.hex() == HOOK_STOLEN
    for (va, code), (lo, hi) in zip(parts, PAD_RUNS):
        run = img.read_va(lo, hi - lo)
        edge = img.read_va(lo - 1, 1) + img.read_va(hi, 1)
        ok = run == bytes([0xCC]) * (hi - lo) and lo <= va and va + len(code) <= hi
        print(f"padding run {lo:#x}..{hi - 1:#x}: {hi - lo} x int3 (neighbour bytes {edge.hex()}), cave part uses "
              f"{va:#x}..{va + len(code) - 1:#x} ({len(code)} B)  {'OK' if ok else 'MISMATCH'}")
        assert ok
    print(f"\nhook ({len(hook)} B): {hook.hex()}")
    for ins in md.disasm(hook, HOOK):
        print(f"   {ins.address:#x}  {ins.mnemonic} {ins.op_str}")
    for va, code in parts:
        print(f"cave part @ {va:#x} ({len(code)} B): {code.hex()}")
        for ins in md.disasm(code, va):
            print(f"   {ins.address:#x}  {ins.mnemonic} {ins.op_str}")
    print("float32 immediates (little-endian, 4 bytes each): " + ", ".join(f"{k} @ {v:#x}" for k, v in tun.items()) + "\n")
    overlay = {HOOK: hook}
    overlay.update({va: code for va, code in parts})
    ok_all = True

    # --- nothing else may reach the padding or the middle of the hooked instruction ------------
    refs = scan_refs(img, list(PAD_RUNS) + [(HOOK + 1, HOOK_RET)])
    print(f"reference scan (rel32 call/jmp/jcc + rel8 jmp/jcc/loop at EVERY byte offset of every executable section, "
          f"absolute 8-byte pointers in every section) into the padding run and the hook interior "
          f"{HOOK + 1:#x}..{HOOK_RET - 1:#x}: {len(refs)} raw hit(s)")
    funcs = pdata_ranges(img)
    for kind, src, tgt in refs:
        fn = next(((b, e) for b, e in funcs if b <= src < e), None)
        real = False
        if fn:                                         # inside a real function: is src an instruction boundary?
            real = any(i.address == src for i in md.disasm(img.read_va(fn[0], src - fn[0] + 16), fn[0]))
        hard = real or kind == "ptr64" or HOOK < tgt < HOOK_RET
        ctx = img.read_va(src - 8, 20).hex(" ")
        print(f"   {kind} at {src:#x} -> {tgt:#x}: source is "
              f"{'an INSTRUCTION in function %#x' % fn[0] if real else ('inside function %#x but NOT on an instruction boundary' % fn[0] if fn else 'outside every .pdata function (protector junk island around the padding)')}"
              f"  bytes[-8..+12] = {ctx}  -> {'FAIL' if hard else 'byte coincidence, not code'}")
        ok_all &= not hard
    if refs:
        print("   why a coincidence is safe to call: the scan tests EVERY byte offset, and the padding sits in an island of "
              "random filler bytes;\n   a LIVE branch into this run would execute int3 in the stock game; and the old slice "
              "cave overwrote 0x14105ed20..0x14105ed60\n   (both target addresses) and ran in game without a trap. Computed "
              "jumps cannot be excluded by any static scan - NOT proven.")

    # --- differential run: stock vs patched, marker registers ---------------------------------
    inf = float("inf")
    cases = [(0.5, f2u(h)) for h in (0.0, -0.0, 3.0, -7.5, 12.0, -12.0, 20.0, 45.0, -170.0, 179.9, inf, -inf, 1e-40)]
    cases += [(0.5, 0x7FC00000), (0.5, 0xFFC00000), (0.5, 0x7FA00000)]            # QNaN, -QNaN, SNaN
    cases += [(o, f2u(h)) for o, h in ((3.5, -12.0), (3.5, 12.0), (-3.9, 20.0), (6.0, -20.0), (6.0, 20.0), (-9.5, 20.0),
                                       (-9.5, -20.0), (9.5, 0.0), (-9.5, 0.0), (0.0, 0.0))]
    print(f"{'old spin.y':>10} {'hmiss deg':>10} | {'stock':>9} {'cave':>10} {'model':>10} | regs changed | extra memory writes")
    t0 = t1 = []
    diff_ok = True
    for flags in (0x8D7, 0x602):                           # all six status flags set ; none set + DF
        for old, hb in cases:
            h = u2f(hb)
            spin0 = (-2.0, old, 0.25)
            s0, w0, t0, (rec0, spn0), e0 = run_hook(img, None, hb, spin0, flags)
            s1, w1, t1, (rec1, spn1), e1 = run_hook(img, overlay, hb, spin0, flags)
            diff = sorted(kk for kk in s0 if s0[kk] != s1[kk])
            exp = model(old, h, a.gain, a.cap)
            got0, got1 = e0.rf(spn0, 3), e1.rf(spn1, 3)
            extra = [w for w in w1 if w not in w0]
            same_rec = bytes(e0.uc.mem_read(rec0, 0x200)) == bytes(e1.uc.mem_read(rec1, 0x200))
            only_spin_y = all(spn1 + 4 <= ad < spn1 + 8 for ad, sz, v in extra)
            in_cave = all(HOOK <= t < HOOK_RET or any(va <= t < va + len(c) for va, c in parts) for t in t1)
            ok = (set(diff) <= {"RAX", "XMM0", "XMM1"} and got1[1] == exp and got1[0] == spin0[0] and got1[2] == spin0[2]
                  and got0[1] == u2f(f2u(old))
                  and bytes(e1.uc.mem_read(rec1 + 0x148, 4)) == struct.pack("<I", hb)
                  and same_rec and only_spin_y and in_cave
                  and s0["RFLAGS"] == s1["RFLAGS"] and s0["RSP"] == s1["RSP"] and s0["MXCSR"] == s1["MXCSR"])
            if h == 0.0 or h != h:                          # zero / NaN miss must leave spin.y bit-identical
                ok = ok and f2u(got1[1]) == f2u(got0[1])
            diff_ok &= bool(ok)
            if flags == 0x8D7:
                print(f"{old:>10.3f} {h:>10.3g} | {got0[1]:>9.4f} {got1[1]:>10.5f} {exp:>10.5f} | {','.join(diff) or '-':<12}"
                      f" | {[(hex(ad - spn1), sz) for ad, sz, v in extra]} {'OK' if ok else 'FAIL'}")
    print(f"  (the same {len(cases)} cases were re-run with RFLAGS=0x602 = no status flags + DF: "
          f"{'all OK' if diff_ok else 'FAIL'}; offsets are relative to r15; the whole 0x200-byte kick record incl. "
          f"[r13+0x148] is byte-identical; RFLAGS, RSP, xmm2-15 identical)")
    ok_all &= diff_ok
    print(f"  patched path: {' -> '.join(hex(t) for t in t1[:2])} ... {' -> '.join(hex(t) for t in t1[-2:])} -> {HOOK_RET:#x}"
          f" ({len(t1)} insns, all inside the hook or the cave); stock path: {' -> '.join(hex(t) for t in t0)}")
    print("  NOT modelled: Unicorn does not track MXCSR sticky exception bits (PE/IE). On real hardware mulss/addss/cmpordss")
    print("  may set them; they are status-only with FP exceptions masked, and the stock code around the hook does the same maths.")

    # --- re-entry: apply the cave N times to the same vector (what a repeated finalise pass would do) ---
    print("\nre-entry bound: cave applied 6 times in a row to the SAME spin vector, miss = +12 deg every pass")
    seq, sy = [], 0.5
    for _ in range(6):
        _, _, _, (_, spn), e = run_hook(img, overlay, f2u(12.0), (-2.0, sy, 0.25))
        sy = e.rf(spn, 3)[1]
        seq.append(sy)
    bounded = all(abs(v) <= a.cap + 1e-6 for v in seq) and seq[-1] == seq[-2]
    ok_all &= bounded
    print(f"  spin.y: 0.5 -> {' -> '.join(f'{v:.3f}' for v in seq)}   saturates at the cap, cannot grow: {'OK' if bounded else 'FAIL'}")

    # --- liveness of rax / xmm0 / xmm1 at the return point ------------------------------------
    sA, wA = run_continuation(img, 0x1122334455667788)
    sB, wB = run_continuation(img, 0x0F0F0F0F0F0F0F0F)
    dl = sorted(kk for kk in sA if sA[kk] != sB[kk])
    live_ok = not dl and wA == wB
    ok_all &= live_ok
    print(f"\nliveness: stock code {HOOK_RET:#x}..0x1440187f8 run twice with different garbage in rax/xmm0/xmm1:"
          f" differing registers afterwards = {dl or 'none'}, memory writes identical = {wA == wB}"
          f"  {'OK' if live_ok else 'FAIL'}")
    print("  (0x14533ea80 = movss xmm0,[fps]; ret  overwrites xmm0; 0x1440187c2 reloads xmm1; 0x144300f00 starts"
          " with mov eax,[..] - none read the old values)")

    # --- end to end: spin after the cave -> game's ball init -> game's air force --------------
    print("\nend-to-end (all game code): cave output spin -> 0x14408ac90 -> 0x144089620, v = 22 m/s, elev 12 deg, "
          "old spin (-2, 0.5, 0.25)")
    print(f"{'hmiss':>7} {'spin.y in':>9} {'spin.y out':>10} | {'d_lateral toward miss m/s^2':>27} {'d_up m/s^2':>11}")
    spin0 = (-2.0, 0.5, 0.25)
    for az, h in ((40.0, 12.0), (40.0, -12.0), (300.0, 5.0), (300.0, -35.0)):
        v = mk(az, 12.0, 22.0)
        s0, _, _, (_, spn0), e0 = run_hook(img, None, f2u(h), spin0)
        s1, _, _, (_, spn1), e1 = run_hook(img, overlay, f2u(h), spin0)
        sp_st, sp_cv = e0.rf(spn0, 3), e1.rf(spn1, 3)
        _, _, _, acc0 = chain(img, v, sp_st)
        _, _, _, acc1 = chain(img, v, sp_cv)
        d = tuple(acc1[i] - acc0[i] for i in range(3))
        l, u, f = lat_up(v, d)
        toward = l * (1 if h > 0 else -1)
        good = toward > 0 and abs(u) < 1e-4
        ok_all &= good
        print(f"{h:>7.1f} {sp_st[1]:>9.3f} {sp_cv[1]:>10.3f} | {toward:>+27.5f} {u:>+11.6f}  {'OK' if good else 'FAIL'}")
    print("  (instantaneous launch acceleration; for metres of drift use `traj` - drag and spin decay matter)")
    print("\nRESULT:", "ALL CHECKS PASSED" if ok_all else "*** SOMETHING FAILED ***")
    return ok_all


# =========================================================================================
# STEP 2d - the LIVE launch path, and what a repeated finalise pass would do
# =========================================================================================
# Static chain (disassembly): per-tick handler 0x143eb2190 -> finalise 0x143ea46c0:
#     0x14408eaa0 (ctx from record) -> solver 0x14408ed10(ctx, &vel, &spin) -> Kick::vf8 (-> mishit fn 0x144016a70, the
#     hook) -> 0x143ea480e: record.mode[+0x8c] = 4 via 0x143eb69d0, vel -> +0xd0.., spin -> +0x114/+0x11c/+0x120, flags
#     +0x110 = +0x118 = 1.
# Ball side 0x143c59350 (the real launch): per kicking player  0x14408eaa0 -> solver 0x14408ed10 (its FIRST act is the
#     seed 0x144098cd0 = read spin back from the record; mode 4 = copy +0xd0.. to the out velocity) -> average over
#     players -> 0x14409d710(ball, idx, &vel, &spin, record) -> 0x14408ac90(state, kickinfo=record, obj, &pos, &vel, &spin).
FINALISE_TAIL = 0x143EA480E        # inside 0x143ea46c0, right after the Kick::vf8 virtual call
FINALISE_TAIL_END = 0x143EA4894
SOLVER = 0x14408ED10
REC_RESET = 0x143C58EA0


def cmd_live(img: Image, a):
    print("=" * 96)
    print("STEP 2d - LIVE launch path: kick record -> solver (mode 4) -> ball-state init with kickinfo = record")
    print("=" * 96)
    ok_all = True
    v_mf = mk(49.0, 11.0, 0.35)                       # deviated launch velocity, m/frame
    spin = (-0.7, -1.8, 0.25)                         # spin as the mishit fn (+cave) leaves it in vf8's arg5
    emu = Emu(img); prep_common(emu)
    uc = emu.uc
    rec = emu.alloc(0x200)
    cst0 = emu.alloc(0x300)
    emu.wf(cst0 + 0x240, 0.77)                        # marker for the 'default spin.x' constant the seed reads
    emu.stubs[0x145348D70] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, cst0)     # ConstantManager.get -> ball struct
    emu.call(REC_RESET, rcx=rec)                      # game's own record reset
    # (1) game's own write-back: tail of 0x143ea46c0 with [rsp+0x30]=velocity, [rsp+0x40]=spin, rdi=record
    frame = STACK + STACK_SZ - 0x9000
    player = emu.alloc(0x5000)
    emu.wf(frame + 0x30, *v_mf); emu.wf(frame + 0x40, *spin)
    uc.reg_write(X.UC_X86_REG_RSP, frame); uc.reg_write(X.UC_X86_REG_RDI, rec); uc.reg_write(X.UC_X86_REG_RBX, player)
    uc.emu_start(FINALISE_TAIL, FINALISE_TAIL_END, count=200)
    assert uc.reg_read(X.UC_X86_REG_RIP) == FINALISE_TAIL_END
    mode = struct.unpack("<i", bytes(uc.mem_read(rec + 0x8C, 4)))[0]
    fl = struct.unpack("<ii", bytes(uc.mem_read(rec + 0x110, 4)) + bytes(uc.mem_read(rec + 0x118, 4)))
    print(f"(1) finalise tail 0x143ea480e..0x143ea4894 (game code): record.mode[+0x8c] = {mode}, "
          f"+0xd0 vel = {tuple(round(c, 5) for c in emu.rf(rec + 0xD0, 3))}, flags(+0x110,+0x118) = {fl}, "
          f"spin(+0x114,+0x11c,+0x120) = ({emu.rf(rec + 0x114):g}, {emu.rf(rec + 0x11C):g}, {emu.rf(rec + 0x120):g})")
    ok_all &= mode == 4 and fl == (1, 1)

    # (2) ball side: the solver exactly as 0x143c59350 calls it (ctx = {record*, obj*}, zeroed outputs)
    def solve(record):
        ctx = emu.alloc(0x40); ov = emu.alloc(0x10); os_ = emu.alloc(0x10)
        emu.w64(ctx, record); emu.w64(ctx + 8, emu.alloc(0x100))
        n0 = len(emu.calls)
        emu.call(SOLVER, rcx=ctx, rdx=ov, r8=os_)
        return emu.rf(ov, 3), emu.rf(os_, 3)
    ov, os_ = solve(rec)
    good = all(abs(ov[i] - u2f(f2u(v_mf[i]))) < 1e-9 for i in range(3)) and all(os_[i] == u2f(f2u(spin[i])) for i in range(3))
    ok_all &= good
    print(f"(2) solver 0x14408ed10 on that record (native, no stubs): out velocity = {tuple(round(c, 5) for c in ov)}, "
          f"out spin = {os_}   -> velocity and spin pass through UNCHANGED (x,y,z order kept): {'OK' if good else 'FAIL'}")

    # (3) ball-state init with kickinfo = the record (the branch the first build never emulated)
    def init(kick, v_ms, sp):
        e = Emu(img); prep_common(e)
        cst = e.alloc(0x300)
        for off, val in BALL_STOCK.items():
            e.wf(cst + off, val)
        state = e.alloc(0x200); obj = e.alloc(0x6000); zero = e.alloc(0x100)
        pos = e.alloc(0x10); vel = e.alloc(0x10); spn = e.alloc(0x10)
        e.wf(pos, 0.0, 1.0, 0.0); e.wf(vel, *v_ms); e.wf(spn, *sp)
        e.stubs[0x145348D70] = lambda x: x.uc.reg_write(X.UC_X86_REG_RAX, cst)
        e.stubs[0x144300F00] = lambda x: x.uc.reg_write(X.UC_X86_REG_RAX, zero)
        k = 0
        if kick is not None:
            k = e.alloc(0x200, kick)
        e.call(BALLINIT, rcx=state, rdx=k, r8=obj, r9=pos, stack_args=(vel, spn, 1))
        return e.rf(state + 0xC, 3), e.rf(state + 0x18, 3), e.uc.mem_read(state + 0x90, 1)[0]
    recbytes = bytes(uc.mem_read(rec, 0x200))
    v_ms = tuple(c * 60.0 for c in ov)
    vN, wN, fN = init(None, v_ms, os_)
    vK, wK, fK = init(recbytes, v_ms, os_)
    same = vN == vK and wN == wK and fN == fK
    ok_all &= same and abs(wK[1] + 2 * math.pi * spin[1]) < 1e-3
    print(f"(3) 0x14408ac90 with kickinfo = NULL   : omega = {tuple(round(c, 4) for c in wN)}  [state+0x90] = {fN}")
    print(f"    0x14408ac90 with kickinfo = record : omega = {tuple(round(c, 4) for c in wK)}  [state+0x90] = {fK}"
          f"   identical: {same};  omega.y = -2*pi*spin.y = {-2 * math.pi * spin[1]:.4f}: {'OK' if ok_all else 'FAIL'}")
    print("    (the kickinfo-only branches are gated by record +0x124 > 0 (velocity blend) and +0x140 > 0 (spin blend),")
    print("     the first-touch deflection rates; the handler 0x143eb2190 zeroes both unless the ball is being deflected.")
    for r124, r140 in ((0.0, 0.5), (0.5, 0.0)):
        rb = bytearray(recbytes)
        struct.pack_into("<f", rb, 0x124, r124); struct.pack_into("<f", rb, 0x140, r140)
        try:
            vB, wB, fB = init(bytes(rb), v_ms, os_)
            print(f"     with +0x124={r124:g} +0x140={r140:g} and a ZERO incoming ball: vel = {tuple(round(c, 3) for c in vB)}, "
                  f"omega = {tuple(round(c, 4) for c in wB)}  (vs {tuple(round(c, 4) for c in wK)})")
        except RuntimeError as ex:
            print(f"     with +0x124={r124:g} +0x140={r140:g}: NOT EMULATED ({str(ex)[:90]})")
    print("     -> the deflection blend (incoming ball spin/velocity mixed in) is NOT proven; it is stock behaviour that acts")
    print("        on whatever spin the kick has, with or without this patch.)")

    # (4) re-entry: what a SECOND finalise pass on the same (un-reset) record would start from
    print("(4) re-entry: solver run again on the record after the write-back (= start of a hypothetical 2nd finalise pass):")
    ov2, os2 = solve(rec)
    print(f"    start velocity = {tuple(round(c, 5) for c in ov2)} (the ALREADY-DEVIATED one), start spin = {os2}")
    print("    => stock itself is not idempotent here: a 2nd pass would re-roll the miss on top of the deviated velocity;")
    print("       the cave would then add GAIN * (2nd miss), i.e. total added spin tracks the TOTAL deviation, and the")
    print("       result cap bounds it (see `cave`: re-entry bound). Whether a 2nd pass ever happens is NOT proven.")
    emu.call(REC_RESET, rcx=rec)
    ov3, os3 = solve(rec)
    mode3 = struct.unpack("<i", bytes(uc.mem_read(rec + 0x8C, 4)))[0]
    print(f"    after the game's record reset 0x143c58ea0 (called right before the handler at 2 of its 3 call sites, "
          f"0x14410fdb1 / 0x1441116fb): mode = {mode3:#x} (> 0xb: solver returns at once), solver out = {ov3} / {os3}")
    good = mode3 == 0xC and os3[1] == 0.0
    ok_all &= good
    print(f"    => on those two paths nothing carries over between ticks: {'OK' if good else 'FAIL'}. The third call site "
          f"0x144241b8a passes an external record [rsi+0x15a28]; no reset was found there - NOT proven.")
    print("\nRESULT(live):", "ALL CHECKS PASSED" if ok_all else "*** SOMETHING FAILED ***")
    return ok_all


# =========================================================================================
# tuning numbers from the game's own ball stepper 0x14408d0f0 (drag + spin decay + ground included)
# =========================================================================================
STEPPER = 0x14408D0F0
DT270_PRISTINE = Path.home() / "Backups" / "eFootball" / "dt270_console_all.PRISTINE.cpk"


def full_ball_struct():
    """Complete runtime 'ball' constant struct with STOCK values (pristine dt270 + runtime offsets)."""
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dt270_objects as D
    packs = D.load_game_packs(DT270_PRISTINE)
    _f, pack = D.find_object(packs, "ball")
    obj = pack.object("ball").to_dict()
    offs = json.loads((Path(__file__).resolve().parent / "data" / "dt270_struct_offsets.json").read_text(encoding="utf-8"))
    offs = offs["types"]["ball"]
    buf = bytearray(offs["struct_size"])
    for f in offs["fields"]:
        try:
            cur = obj
            for part in f["path"].split("."):
                cur = cur[part[:-2] if part.endswith("[]") else part]
        except (KeyError, TypeError):
            continue
        vals = cur if isinstance(cur, list) else [cur]
        if len(f["dims"]) > 1:
            continue
        stride = f["dims"][0]["stride"] if f["dims"] else 0
        for i, x in enumerate(vals):
            if isinstance(x, (dict, list)):
                break
            o = f["soff"] + i * stride
            if f["kind"] == "float":
                struct.pack_into("<f", buf, o, float(x))
            elif f["kind"] == "int":
                struct.pack_into("<i", buf, o, int(x))
            elif f["kind"] == "bool":
                buf[o] = 1 if x else 0
    return bytes(buf)


def fly(img, ball, v_ms, spin, dist, tmax=8.0):
    """Game code only: 0x14408ac90 then the stepper 0x14408d0f0 at 60 Hz until `dist` m downrange."""
    emu = Emu(img); prep_common(emu)
    cst = emu.alloc(len(ball) + 0x40, ball)
    q = emu.alloc(0x100); emu.wf(q + 0xC, 0.0, 0.0, 0.0, 1.0)
    flagobj = emu.alloc(0x400); gobj = emu.alloc(0x8000)
    emu.w64(gobj + 0x630, flagobj)
    emu.poke_image(G_MATCH, struct.pack("<Q", gobj))
    emu.stubs[0x145348D70] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, cst)
    emu.stubs[0x144300F00] = lambda e: e.uc.reg_write(X.UC_X86_REG_RAX, q)
    state = emu.alloc(0x200); obj = emu.alloc(0x6000)
    pos = emu.alloc(0x10); vel = emu.alloc(0x10); spn = emu.alloc(0x10)
    emu.wf(pos, 0.0, 0.108686, 0.0); emu.wf(vel, *v_ms); emu.wf(spn, *spin)
    emu.call(BALLINIT, rcx=state, rdx=0, r8=obj, r9=pos, stack_args=(vel, spn, 1))
    apex, t, p = 0.0, 0.0, (0.0, 0.0, 0.0)
    for i in range(int(tmax * 60)):
        emu.set_xmm(0, 1 / 60)
        emu.call(STEPPER, rcx=0, rdx=0, r8=0, r9=state, stack_args=(cst + 8, 1 if i == 0 else 0, 0, 0))
        p = emu.rf(state, 3)
        apex = max(apex, p[1]); t = (i + 1) / 60
        if math.hypot(p[0], p[2]) >= dist:
            break
    return p, t, apex


def cmd_traj(img: Image, a):
    check_tunables(a)
    print("=" * 96)
    print(f"TUNING NUMBERS from the game's own ball stepper 0x14408d0f0 (60 Hz, stock dt270 ball constants, magnusRate 0.035)")
    print(f"  added side spin = -{a.gain} * miss, capped at +/-{a.cap} rev/s, on a ball with no other spin; drift = extra sideways")
    print("  distance toward the MISS side at equal downrange distance, patched minus stock")
    print("=" * 96)
    try:
        ball = full_ball_struct()
    except Exception as ex:                                  # noqa: BLE001
        print(f"cannot build the stock ball struct ({ex!r}) - traj skipped (needs {DT270_PRISTINE})")
        return None
    rows = (("ground pass 50 km/h, 30 m", 0.0, 13.9, 30.0, 10.0), ("ground pass 50 km/h, 30 m", 0.0, 13.9, 30.0, -10.0),
            ("short pass 40 km/h, 10 m", 0.0, 11.1, 10.0, 10.0), ("driven 70 km/h el 5, 30 m", 5.0, 19.4, 30.0, 10.0),
            ("lofted 65 km/h el 25, 30 m", 25.0, 18.0, 30.0, 10.0), ("lofted 65 km/h el 25, 30 m", 25.0, 18.0, 30.0, 5.0),
            ("shot 100 km/h el 8, 25 m", 8.0, 27.8, 25.0, 5.0), ("shot 100 km/h el 8, 25 m", 8.0, 27.8, 25.0, 10.0),
            ("shot 100 km/h el 8, 25 m", 8.0, 27.8, 25.0, 20.0), ("long ball 90 km/h el 30, 50 m", 30.0, 25.0, 50.0, 10.0))
    print(f"{'case':<30} {'miss':>6} {'add rev/s':>9} | {'miss alone m':>12} {'extra drift m':>13} {'apex stock->patched m':>22} {'t s':>5}")
    ok = True
    for name, el, sp, dist, miss in rows:
        az0 = 40.0
        v = mk(az0 + miss, el, sp)
        add = model(0.0, miss, a.gain, a.cap)
        p0, t0, h0 = fly(img, ball, v, (0.0, 0.0, 0.0), dist)
        p1, t1, h1 = fly(img, ball, v, (0.0, add, 0.0), dist)
        d0 = (math.sin(math.radians(az0)), math.cos(math.radians(az0)))
        d1 = (math.sin(math.radians(az0 + miss)), math.cos(math.radians(az0 + miss)))
        dot = d0[0] * d1[0] + d0[1] * d1[1]
        m = (d1[0] - dot * d0[0], d1[1] - dot * d0[1]); ml = math.hypot(*m); m = (m[0] / ml, m[1] / ml)
        drift = (p1[0] - p0[0]) * m[0] + (p1[2] - p0[2]) * m[1]
        ok &= drift > 0
        print(f"{name:<30} {miss:>+6.1f} {add:>+9.2f} | {dist * math.sin(math.radians(abs(miss))):>12.2f} {drift:>+13.2f} "
              f"{h0:>10.3f} -> {h1:<9.3f} {t0:>5.2f}")
    print("second-order lift coupling (added side spin on top of heavy backspin, lofted 22 m/s el 12, 30 m):")
    for base in ((0.0, 0.0, 0.0), (-4.0, 0.0, 0.0), (-8.0, 0.0, 0.0)):
        v = mk(50.0, 12.0, 22.0)
        _, _, h0 = fly(img, ball, v, base, 30.0)
        _, _, h1 = fly(img, ball, v, (base[0], base[1] - a.cap, base[2]), 30.0)
        print(f"  base spin {base}: apex {h0:.3f} -> {h1:.3f} m  (delta {h1 - h0:+.3f})")
    print("RESULT(traj):", "drift is toward the miss side in every row" if ok else "*** SIGN FAILURE ***")
    return ok


def cmd_spec(img: Image, a):
    import json
    check_tunables(a)
    parts, hook, tun = build_cave(a.gain, a.cap)
    (cave_va, cave), = parts
    k = -a.gain
    sat = a.cap / a.gain
    desc = (
        "LINKED SIDE SPIN for mishits (one hook + one 85-byte cave). STATUS: NOT APPLIED, NEVER RUN IN GAME. Authored and "
        "emulation-proved only; re-run every proof with `python tools/emu_spin.py all` (add --exe <PRISTINE backup> to run on "
        "the pristine image; output is identical). Revised after two adversarial reviews: NaN guard, bounded result, live "
        "launch path traced, tuning numbers re-measured with the game's own ball stepper. "
        "WHAT IT DOES: in the mishit master function 0x144016a70 (Kick::vf8 0x143ed0f80 -> here) the game stores the signed "
        "horizontal miss  wrap180(final azimuth - intended azimuth), degrees, from xmm6 into [kickrecord+0x148] at "
        f"{HOOK:#x}. That 9-byte instruction becomes  movaps xmm0,xmm6 ; jmp {cave_va:#x} ; nop. The cave re-runs the stolen "
        "store verbatim, then does  spin.y' = clamp( spin.y + GAIN*miss , min(spin.y,-CAP) , max(spin.y,+CAP) )  on the kick's "
        f"LOCAL spin vector [r15+4] (rev/s) and jumps back to {HOOK_RET:#x}. GAIN = {k:g} rev/s per degree (the negative sign "
        f"is what makes the ball curl AWAY from the target: a slice keeps slicing, a pull keeps pulling); CAP = {a.cap:g} rev/s, "
        f"reached at a {sat:.1f} deg miss. Properties (all emulated): a zero or NaN miss leaves spin.y bit-identical; the game's "
        "own side spin is never cut (if |spin.y| already exceeds CAP the cave can only leave it or move it toward zero/CAP on "
        "the other side); repeated application saturates at CAP instead of growing. "
        "PROVEN BY EMULATING THE GAME'S OWN CODE: (1) ball physics is Y-UP (gravity -9.80665 on component [1]); Magnus = "
        "k*(omega x v) in 0x144089620; only omega about the vertical axis curls and its first-order lift is zero. (2) 0x144018c10 "
        "('the spin builder' in older notes) only re-clamps the VELOCITY azimuth/speed and never touches spin; the old 45->90 "
        "re-aim and P2/P2b were direction/speed edits, the old slice caves wrote into the velocity vector. (3) Local spin "
        "convention (ball-state init 0x14408ac90, cross-checked with the solver's converter 0x14408c7e0): spin = (x top/back, "
        "y SIDE, z rifle) rev/s, world omega.y = -2*pi*spin.y at every azimuth, spin.y<0 curls toward increasing azimuth. "
        "(4) Register identity at the hook: r14 = velocity, r15 = spin, r13 = kick record, xmm6 = miss (12.000 / -11.933 / "
        "17.999 / -12.500 for four azimuth pairs); the same game tail run WITH the patch overlaid ends at the return address "
        "with spin.y moved by GAIN*miss and x/z untouched. (5) Differential run vs stock (26 inputs incl. +/-0, +/-inf, "
        "denormal, QNaN/-QNaN/SNaN, |old spin| above CAP; two RFLAGS images incl. DF): only rax, xmm0, xmm1 and the 4 bytes at "
        "[r15+4] differ; the 0x200-byte kick record incl. +0x148, [r15+0], [r15+8], RSP, RFLAGS, xmm2-15 identical; result "
        "equals an independent float32 model bit for bit. rax/xmm0/xmm1 are dead at the return point (stock continuation "
        "through both following calls emulated with different garbage: identical state). No flag-writing instruction, no "
        "stack use, no RIP-relative instruction copied. (6) LIVE LAUNCH PATH, stage by stage: the finalise tail "
        "0x143ea480e..0x143ea4894 sets record.mode[+0x8c]=4 and writes velocity to +0xd0.. and spin to +0x114/+0x11c/+0x120 "
        "with flags +0x110=+0x118=1; the solver 0x14408ed10 run on that record returns exactly that velocity and that spin "
        "(seed 0x144098cd0 + mode-4 copy); 0x14408ac90 with kickinfo = the record gives the same omega as with kickinfo = NULL "
        "(omega.y = -2*pi*spin.y). (7) End to end with game code only: extra acceleration is toward the miss side for both "
        "signs, vertical change 0.000000 at launch. "
        "FROM DISASSEMBLY ONLY (not emulated): the glue of the live path - ball-side 0x143c59350 loops over kicking players, "
        "calls 0x14408eaa0 + 0x14408ed10, averages, and passes &vel/&spin/record to 0x14409d710, which hands them to "
        "0x14408ac90 at 0x14409da15 (rdx = record, arg6 = spin). 0x144016a70 has one caller. The hook is on an instruction "
        "boundary; the only branch into the 9 bytes (jbe 0x1440187b4) lands on the first byte, which is still a whole "
        "instruction. "
        "NOT PROVEN: (a) single application per kick. The per-tick handler 0x143eb2190 is reached from 3 sites; at 2 of them "
        "(0x14410fdb1, 0x1441116fb) the record is reset by 0x143c58ea0 immediately before (emulated: mode 0xc, spin flags 0, "
        "nothing carries over). The third (0x144241b8a, external record [rsi+0x15a28]) has no visible reset. If a record were "
        "finalised twice, stock itself would re-roll the miss on top of the already-deviated velocity (emulated: the solver "
        "hands the deviated velocity back), and this cave would add GAIN*(second miss) - so the added spin tracks the total "
        "deviation and CAP bounds it. (b) The first-touch deflection blend in 0x14408ac90 (record +0x124/+0x140 > 0) was only "
        "run with a zero incoming ball; it is stock behaviour acting on whatever spin the kick has. (c) Whether the live ball "
        "update ever calls the stepper with its skip-Magnus flag (dl=1 -> air routine r8b=1); if it does in some ball state, "
        "curl is zero there, as it is for the game's own curl. (d) Computed jumps into the padding cannot be excluded by any "
        "static scan: the scan (rel32/rel8 at every byte offset of every executable section + 8-byte pointers everywhere) finds "
        "2 rel8 byte-coincidences in the protector's filler bytes next to the run (0x14105ecea, 0x14105eda7; neither is inside "
        "a .pdata function) and nothing into the hook interior. A live branch into this run would hit int3 in the stock game, "
        "and the old slice cave occupied 0x14105ed20..0x14105ed60 in game without a trap; bytes 0x14105ed1e-1f and "
        "0x14105ed61..72 have never been overwritten in game. (e) Denuvo tolerance of a jmp at this exact site; in-game look "
        "and the right GAIN. (f) MXCSR sticky status bits are not modelled by Unicorn (status-only, exceptions masked). "
        "(g) 'rev/s' as the unit is inferred from the 2*pi factor and the game's own 8.0 cap. "
        "INTERACTIONS: the INSTALLED exe is not stock (technique-realism.json + scuff-wobble.json, 33 bytes, one at "
        "0x144017656 inside this function); no byte overlaps, and the dry-run passes on both the installed and the pristine "
        "image. With scuff-wobble/knuckle-mishit every type 0-3 situational mishit flies the keyframed non-spin program, where "
        "the air routine ignores the spin vector (emulated) - so on that build this patch acts only on type-4 (ordinary random "
        "error) kicks. Without them, types 0-3 already carry the game's own contact-model spin (capped at 8 rev/s just before "
        "the hook); the cave then only adds up to CAP and never cuts it - that combination was not flown end to end. Fully "
        "assisted passes have zero miss in stock, so zero added spin. The miss is measured before Kick::vf8's later "
        "0x144018c10 call, which can clamp the launch azimuth to +/-45 deg of body facing, so on extreme body angles the spin "
        "reflects the pre-clamp miss. The function's own landing prediction (second 0x14408ac90 at 0x14401887d, result in "
        "record+0x154) will include the curl; readers of +0x154 were not traced. Same padding as the dead slice-cave.json / "
        "slice-cave-v2.json / balloon-fix.json / cave-remove.json - never stack with them; in particular cave-remove.json "
        "applied on top of this would int3-fill the cave while the hook still jumps into it (crash on the first mishit) - "
        "undo this patch only by reverting THIS spec's two entries. "
        "TUNING: three float32 immediates, little-endian: "
        f"GAIN at {tun['GAIN']:#x} (raw value NEGATIVE, currently {k:g}), CAP at {tun['CAP_POS']:#x} (+{a.cap:g}) and "
        f"{tun['CAP_NEG']:#x} (-{a.cap:g}; keep the pair equal and opposite). Do not hand-edit: run `python tools/emu_spin.py "
        "spec --gain <g> --cap <c>` - BOTH ARE POSITIVE MAGNITUDES on the command line (the tool writes the negative "
        "immediate itself and rejects zero/negative input); it re-runs the proofs and only then rewrites this file. Measured "
        f"with the game's own stepper 0x14408d0f0 (stock magnusRate 0.035, gain {a.gain:g}): 10 deg miss on a 30 m pass = about "
        "+1.1 m extra drift on the ground at 50 km/h (the miss itself is 5.2 m), +1.5 m driven, +1.8 m lofted; 5 deg lofted "
        "+0.9 m; 25 m shot at 100 km/h: +0.6 m (5 deg), +1.15 m (10 deg), +2.15 m (20 deg); 50 m long ball, 10 deg: +5 m on "
        "top of 8.7 m - if long balls look wild, lower GAIN. Ground passes DO curl in the game's model (the stepper applies "
        "Magnus on the ground too). Apex change from the added spin: 0.000 m with no other spin, -0.01 m on top of 8 rev/s "
        "backspin - no ballooning. dt270 ball.magnusRate scales all of this linearly. "
        "FIRST IN-GAME TEST (owner's decision): apply this spec ALONE on the known-good build so any crash is attributable; "
        "use an exaggerated build first (`spec --gain 0.5 --cap 8`), hit a long manual lofted pass off target and confirm the "
        "ball bends further AWAY from the intended line; if it bends back, or not at all, stop and report - do not flip the "
        "sign by hand. Then regenerate with the defaults."
    )
    spec = {"description": desc, "patches": [
        {"name": f"linked-spin cave @ {cave_va:#x} ({len(cave)} B of the 86-byte int3 run): store miss; "
                 f"spin.y = clamp(spin.y + ({k:g})*miss, min(spin.y,-{a.cap:g}), max(spin.y,+{a.cap:g})); NaN miss -> no change",
         "va": f"{cave_va:#x}", "expect": ("cc" * len(cave)), "patch": cave.hex(), "kind": "code"},
        {"name": f"linked-spin hook @ {HOOK:#x}: movss [r13+0x148],xmm6 -> movaps xmm0,xmm6 ; jmp cave ; nop "
                 f"(cave returns to {HOOK_RET:#x})",
         "va": f"{HOOK:#x}", "expect": HOOK_STOLEN, "patch": hook.hex(), "kind": "code"},
    ]}
    if not (cmd_hookval(img, a) and cmd_live(img, a) and cmd_cave(img, a)):
        raise SystemExit("proof failed - spec NOT written")
    SPEC.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(f"\nwrote {SPEC}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["magnus", "builder", "chain", "hookval", "live", "cave", "traj", "spec", "all"])
    ap.add_argument("--gain", type=float, default=DEFAULT_GAIN,
                    help="POSITIVE magnitude: side spin added per degree of horizontal miss, rev/s per deg. The tool "
                         "always encodes curl-AWAY (a negative immediate); zero/negative values are rejected")
    ap.add_argument("--cap", type=float, default=DEFAULT_CAP,
                    help="POSITIVE: limit on |spin.y| after the add, rev/s (never cuts the game's own value); also "
                         "bounds any re-entry")
    ap.add_argument("--exe", default=str(EXE), help="image to emulate (read-only); e.g. the PRISTINE backup")
    a = ap.parse_args()
    check_tunables(a)
    img = Image(Path(a.exe))
    print(f"image: {a.exe}")
    res = {}
    if a.cmd in ("magnus", "all"):
        cmd_magnus(img)
    if a.cmd in ("builder", "all"):
        cmd_builder(img)
    if a.cmd in ("chain", "all"):
        cmd_chain(img)
    if a.cmd in ("hookval", "all"):
        res["hookval"] = cmd_hookval(img, a)
    if a.cmd in ("live", "all"):
        res["live"] = cmd_live(img, a)
    if a.cmd in ("cave", "all"):
        res["cave"] = cmd_cave(img, a)
    if a.cmd in ("traj", "all"):
        res["traj"] = cmd_traj(img, a)
    if a.cmd == "spec":
        cmd_spec(img, a)
    bad = [k for k, v in res.items() if v is False]
    if res:
        print("\nSUMMARY:", ", ".join(f"{k}={'PASS' if v else ('SKIPPED' if v is None else 'FAIL')}" for k, v in res.items()))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
