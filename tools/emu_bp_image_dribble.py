#!/usr/bin/env python3
"""emu_bp_image_dribble.py -- match::ai::bp ImageUnits + DribbleImages, executed on the PRISTINE exe's own
bytes under Unicorn. READ-ONLY: nothing here touches the game. Sections (python tools/emu_bp_image_dribble.py A B C D):
  A  ImageUnitCross::canStart roll segment (real LCG)     B  Roulette/BodyFake weight functions (real)
  C  DribbleChallenge stage A end to end (real pool fill, sort, LCG)   D  the image loop with 16 instrumented fake units
Findings are written up in docs/ball-carrier-brain.md (image/dribble section, 2026-09-19)."""
import sys, struct, json
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cave_alloc import Image
import capstone
PRIS = Image("C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True
def rq(va, img=PRIS): return struct.unpack("<Q", img.read_va(va, 8))[0]
def rd(va, img=PRIS): return struct.unpack("<I", img.read_va(va, 4))[0]
def dis(va, n=60, img=PRIS, stop_ret=True, maxb=0x2000):
    out=[]
    b = img.read_va(va, maxb)
    for i in md.disasm(b, va):
        out.append(i)
        if len(out)>=n: break
        if stop_ret and i.mnemonic in ('ret','int3'): break
    return out
def pdis(va, n=60, img=PRIS, stop_ret=True):
    for i in dis(va, n, img, stop_ret):
        print(f"{i.address:#x}  {i.mnemonic:8s} {i.op_str}")
def vtable(vft, n, img=PRIS):
    return [rq(vft+8*i, img) for i in range(n)]
IMAGE_UNITS = {"None":0x147728248,"Dribble":0x147728280,"Lilux":0x1477282b8,"Safety":0x1477282f0,"CBOverlap":0x147728328,
 "ShotShort":0x147728360,"MiddleShot":0x147728398,"CurveShot":0x1477283d0,"PassThrough":0x147728408,"PassForward":0x147728440,
 "Cross":0x147728478,"Long":0x1477284b0,"SideChange":0x1477284e8,"Expand":0x147728520,"ShotPassFromGoal":0x147728558,"BackDFLine":0x147728590}
DRIBBLE_IMAGES = {"Base":0x147723df0,"NoFeint":0x14772ddc8,"BodyFake":0x14772de78,"Roulette":0x14772de20,"DoubleTouch":0x14772ded0,
 "EdgeTurn":0x14772df28,"Eracico":0x14772df80,"KickFeint":0x14772dfd8,"DrawOpen":0x14772e030,"Chapeu":0x14772e088,"Humiliating":0x14772e0e0,
 "TrapThrough":0x14772e138,"Shielding":0x14772e190,"SharpCut":0x14772e1e8,"TapTrick":0x14772e240,"Burst":0x14772ff58}

"""imgdrb_emu.py -- image units + dribble moves, executed on the PRISTINE image's own bytes under Unicorn.
Nothing here touches the game. Sections: A cross roll, B dribble weights, C stage A, D image loop.
(Unique filename: the scratchpad is shared with sibling probes.)"""
import struct, sys, math
from collections import Counter, defaultdict
from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_PROT_ALL, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED,
                     UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UcError)
from unicorn import x86_const as X
IMG = PRIS
STACK = 0x7fff0000; STACK_SZ = 0x40000; HEAP = 0x20000000; HEAP_SZ = 0x100000; SC = 0x30000000; RET = 0x40000000


def f2i(v): return struct.unpack('<I', struct.pack('<f', v))[0]
def i2f(v): return struct.unpack('<f', struct.pack('<I', v & 0xffffffff))[0]


class Emu:
    def __init__(self):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64); self.mapped = set(); self.stubs = {}; self.trace = []; self.stops = set(); self.stopped = None
        for a, s in ((STACK, STACK_SZ), (HEAP, HEAP_SZ), (SC, 0x10000), (RET, 0x1000)): self.uc.mem_map(a, s, UC_PROT_ALL)
        self.uc.mem_write(RET, b'\xf4')
        self.uc.reg_write(X.UC_X86_REG_CR0, (self.uc.reg_read(X.UC_X86_REG_CR0) & ~4) | 2)
        self.uc.reg_write(X.UC_X86_REG_CR4, self.uc.reg_read(X.UC_X86_REG_CR4) | 0x600)
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        for h in (UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED): self.uc.hook_add(h, self._fault)
        self.span = (IMG.base, IMG.base + max(s['rva'] + s['vsize'] for s in IMG.sections))

    def ensure(self, va, n=0x40):
        for p in range(va & ~0xfff, (va + n + 0xfff) & ~0xfff, 0x1000):
            if p in self.mapped: continue
            self.mapped.add(p)
            try: self.uc.mem_map(p, 0x1000, UC_PROT_ALL)
            except Exception: continue
            try:
                b = IMG.read_va(p, 0x1000)
                if b: self.uc.mem_write(p, b)
            except Exception: pass

    def _fault(self, uc, acc, addr, size, val, u):
        if self.span[0] <= addr < self.span[1]: self.ensure(addr, size); return True
        return False

    def _code(self, uc, addr, size, u):
        self.trace.append(addr)
        if addr in self.stops: self.stopped = addr; uc.emu_stop(); return
        fn = self.stubs.get(addr)
        if fn is not None:
            fn(uc); sp = uc.reg_read(X.UC_X86_REG_RSP); ret = struct.unpack('<Q', uc.mem_read(sp, 8))[0]
            uc.reg_write(X.UC_X86_REG_RSP, sp + 8); uc.reg_write(X.UC_X86_REG_RIP, ret)

    def wq(self, a, v): self.uc.mem_write(a, struct.pack('<Q', v & 0xffffffffffffffff))
    def wd(self, a, v): self.uc.mem_write(a, struct.pack('<I', v & 0xffffffff))
    def wf(self, a, v): self.uc.mem_write(a, struct.pack('<f', v))
    def wb(self, a, v): self.uc.mem_write(a, bytes([v & 0xff]))
    def rd(self, a): return struct.unpack('<I', self.uc.mem_read(a, 4))[0]
    def rf(self, a): return struct.unpack('<f', self.uc.mem_read(a, 4))[0]
    def reg(self, n): return self.uc.reg_read(getattr(X, 'UC_X86_REG_' + n.upper()))
    def sreg(self, n, v): self.uc.reg_write(getattr(X, 'UC_X86_REG_' + n.upper()), v)
    def xmm0(self):
        v = self.uc.reg_read(X.UC_X86_REG_XMM0); return i2f(v & 0xffffffff)

    def run(self, start, until=RET, count=2000000):
        self.stopped = None; self.trace = []
        try: self.uc.emu_start(start, until, count=count)
        except UcError as e:
            return ('ERR', str(e), hex(self.reg('rip')))
        return 'OK'


def ret_val(v):
    def f(uc): uc.reg_write(X.UC_X86_REG_RAX, v & 0xffffffffffffffff)
    return f


def ret_f(v):
    def f(uc): uc.reg_write(X.UC_X86_REG_XMM0, f2i(v))
    return f


def nop(uc): pass
def fabs_stub(uc): v = uc.reg_read(X.UC_X86_REG_XMM0); uc.reg_write(X.UC_X86_REG_XMM0, v & 0x7fffffff)


def memmove_stub(uc):
    d = uc.reg_read(X.UC_X86_REG_RCX); s = uc.reg_read(X.UC_X86_REG_RDX); n = uc.reg_read(X.UC_X86_REG_R8)
    uc.mem_write(d, bytes(uc.mem_read(s, n))); uc.reg_write(X.UC_X86_REG_RAX, d)


def memset_stub(uc):
    d = uc.reg_read(X.UC_X86_REG_RCX); v = uc.reg_read(X.UC_X86_REG_RDX) & 0xff; n = uc.reg_read(X.UC_X86_REG_R8)
    uc.mem_write(d, bytes([v]) * n); uc.reg_write(X.UC_X86_REG_RAX, d)


# layout in HEAP
MATCH = HEAP + 0x0000; ENT = HEAP + 0x1000; R = ENT + 0x394; CTX = HEAP + 0x2000; CTX8 = HEAP + 0x2400; THIS = HEAP + 0x2800; INPUT = HEAP + 0x2c00
TEAM = HEAP + 0x3000; RTEAM = TEAM + 0xe8; CLOCK = HEAP + 0x4000; WORK = HEAP + 0x5000; UNITS = HEAP + 0x8000; VT = HEAP + 0xa000; MGR = HEAP + 0x10000
NOWBLK = HEAP + 0x20000; SIT = HEAP + 0x20100; LISTOBJ = HEAP + 0x20200; BLK = HEAP + 0x21000


def set_card(e, base, cid, on):
    w = e.rd(base + 0xc0 + (cid >> 5) * 4); w = (w | (1 << (cid & 31))) if on else (w & ~(1 << (cid & 31))); e.wd(base + 0xc0 + (cid >> 5) * 4, w)


def new():
    e = Emu(); e.uc.mem_write(HEAP, b'\0' * HEAP_SZ); return e


# ------------------------------------------------------------------------------------ A
A_START = 0x14567b3c0; A_ACC = 0x14567b54e; A_REJ = 0x14567b162; A_CMP = 0x14567b546


def cross_roll(attr=70, card_e=False, style8=False, com3=False, state=0, sil=0, this14=0xff, seed_t=12.5):
    e = new(); e.stubs[0x1442d6ef0] = ret_val(ENT); e.stops = {A_ACC, A_REJ}
    e.wq(CTX, MATCH); e.wq(CTX + 8, CTX8); e.wf(CTX + 0x48, seed_t); e.wd(CTX8, 5); e.wd(CTX8 + 0x7c, state); e.wd(THIS + 0x14, this14)
    e.wb(R + 0x1d, attr); set_card(e, R, 0xe, card_e); e.wd(R + 0xcc, (1 << 8) if style8 else 0); e.wd(R + 0xd4, (1 << 3) if com3 else 0)
    e.sreg('rdi', CTX); e.sreg('rbp', THIS); e.sreg('r14', R); e.sreg('rsi', sil); e.sreg('rsp', STACK + 0x20000)
    e.uc.reg_write(X.UC_X86_REG_XMM13, f2i(1.0)); e.uc.reg_write(X.UC_X86_REG_XMM6, 0)   # live-ins set by the prologue
    got = {}

    def hook(uc, addr, size, u):
        if addr == A_CMP: got['score'] = uc.reg_read(X.UC_X86_REG_EBX); got['draw'] = uc.reg_read(X.UC_X86_REG_EAX)
    e.uc.hook_add(UC_HOOK_CODE, hook)
    r = e.run(A_START, count=100000)
    return r, e.stopped == A_ACC, got


# ------------------------------------------------------------------------------------ B
def weight(fn, attrs, cards=(), com=0):
    e = new(); e.stubs[0x1442d6ef0] = ret_val(ENT); e.stubs[0x144f7e0d0] = nop
    for k, v in attrs.items(): e.wb(R + 0x3d + k, v)
    for c in cards: set_card(e, R, c, True)
    e.wd(R + 0xd4, com)
    e.wq(CTX, INPUT); e.wq(CTX + 0x18, MATCH); e.wd(INPUT, 5)
    e.sreg('rcx', THIS); e.sreg('rdx', CTX); e.sreg('rsp', STACK + 0x20000 - 8); e.wq(STACK + 0x20000 - 8, RET)
    r = e.run(fn, count=200000)
    return r, e.xmm0()


# ------------------------------------------------------------------------------------ C
STAGEA = 0x1456a9570; POOLFILL = 0x1456ab3b0
MOVES = {1: 'NoFeint', 2: 'Burst', 3: 'Roulette', 4: 'BodyFake', 5: 'DoubleTouch', 6: 'EdgeTurn', 7: 'Eracico', 8: 'KickFeint',
         9: 'DrawOpen', 10: 'Chapeu', 11: 'Humiliating', 12: 'TrapThrough', 13: 'Shielding', 14: 'SharpCut', 15: 'TapTrick'}


def stage_a(weights, cards=(), com_team=0, com_ent=0, level=0, scaleA=0.0, scaleB=1.0, clock_ms=1000, attrs=None):
    """weights: move id -> weight returned by that move's slot 2 (ids 3,4 use REAL fns if not given)"""
    e = new()
    e.stubs[0x1442d6e40] = ret_val(TEAM); e.stubs[0x1442c3080] = ret_val(RTEAM); e.stubs[0x1442d6fc0] = ret_val(CLOCK)
    e.stubs[0x144f8306e] = memset_stub; e.stubs[0x144f83080] = memmove_stub; e.stubs[0x144f7e3a0] = nop; e.stubs[0x144f7e0d0] = nop; e.stubs[0x1442d6ef0] = ret_val(ENT)
    for c in cards: set_card(e, RTEAM, c, True); set_card(e, R, c, True)
    e.wd(RTEAM + 0xd4, com_team); e.wd(R + 0xd4, com_ent)
    if attrs:
        for k, v in attrs.items(): e.wb(R + 0x3d + k, v)
    e.wd(CLOCK, clock_ms); e.wf(CLOCK + 8, clock_ms / 1000.0)
    e.wq(CTX, INPUT); e.wq(CTX + 0x18, MATCH); e.wd(INPUT, 5); e.wd(INPUT + 8, 0)
    key = 0x5a5a5a5a; e.wd(INPUT + 0x8c, level ^ key); e.wd(INPUT + 0x90, key)
    e.wq(CTX + 0x50, BLK); e.wf(BLK, scaleA); e.wq(CTX + 0x58, BLK + 0x10); e.wf(BLK + 0x18, scaleB)
    calls = []
    for i in range(1, 16):
        obj = UNITS + i * 0x40; vt = VT + i * 0x80; e.wq(obj, vt); e.wq(WORK + 0x5b0 + i * 8, obj)
        if i in weights:
            st = SC + i * 0x40 + 0x10; e.uc.mem_write(st, b'\xc3')
            e.wq(vt + 0x10, st)

            def mk(i):
                def f(uc): calls.append(i); uc.reg_write(X.UC_X86_REG_XMM0, f2i(weights[i]))
                return f
            e.stubs[st] = mk(i)
        else:
            e.wq(vt + 0x10, {3: 0x1456bb810, 4: 0x1456bcb10}.get(i, SC + 0x3000))
    e.uc.mem_write(SC + 0x3000, b'\xc3'); e.stubs[SC + 0x3000] = ret_f(0.0)
    e.sreg('rcx', WORK); e.sreg('rdx', CTX); e.sreg('rsp', STACK + 0x20000 - 8); e.wq(STACK + 0x20000 - 8, RET)
    r = e.run(STAGEA, count=500000)
    n = e.rd(WORK + 0x78); pool = [e.rd(WORK + 0x7c + 4 * k) for k in range(n)]
    m = e.rd(WORK + 0xbc); short = [e.rd(WORK + 0xc0 + 4 * k) for k in range(m)]
    return r, pool, short, calls


# ------------------------------------------------------------------------------------ D
LOOP = 0x14566aa10
NAMES = ['None', 'Dribble', 'Lilux', 'ShotShort', 'MiddleShot', 'CurveShot', 'ShotPassFromGoal', 'PassThrough', 'PassForward', 'Cross', 'Long', 'SideChange', 'BackDFLine', 'Expand', 'Safety', 'CBOverlap']


class ImageWorld:
    def __init__(self, sit_class=1, shots=False, cooldown=54, safety714=0, listcount=0, profile84=0, ctxfloat=0.0):
        e = self.e = new(); self.log = []; self.canstart = {}; self.shouldend = {}; self.execout = {}
        e.stubs[0x140a22910] = fabs_stub; e.stubs[0x143e33fd0] = ret_val(0); e.stubs[0x14566b350] = nop
        self.abort = 0; e.stubs[0x143e34060] = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, self.abort)
        e.stubs[0x144300990] = ret_val(0); e.stubs[0x144300a40] = ret_val(0); e.stubs[0x143e31cb0] = ret_val(0 if shots else 1)
        e.stubs[0x145660c50] = ret_val(LISTOBJ); e.wd(LISTOBJ + 0x10, listcount)
        e.stubs[0x14533eb20] = ret_val(cooldown); e.stubs[0x143e8fde0] = nop; e.stubs[0x1456762e0] = nop; e.stubs[0x14566b7f0] = nop; e.stubs[0x144f7e0d0] = nop
        e.wd(SIT + 8, sit_class); e.wd(MGR + 0x714, safety714); e.wd(CTX8 + 0x84, profile84); self.ctxfloat = ctxfloat
        for i in range(16):
            obj = UNITS + i * 0x40; vt = VT + i * 0x80; e.wq(obj, vt); e.wq(MGR + 0x718 + i * 8, obj)
            for s in range(6):
                st = SC + (i * 8 + s) * 0x10; e.uc.mem_write(st, b'\xc3'); e.wq(vt + s * 8, st); e.stubs[st] = self.mk(i, s)
        self.frame = 0

    def mk(self, i, s):
        def f(uc):
            self.log.append((self.frame, i, s))
            if s == 2: uc.reg_write(X.UC_X86_REG_RAX, 1 if self.canstart.get(i, False) else 0)
            elif s == 3: uc.reg_write(X.UC_X86_REG_RAX, 1 if self.shouldend.get(i, False) else 0)
            elif s == 5:
                out = uc.reg_read(X.UC_X86_REG_R8); k, t = self.execout.get(i, (0, 0xff)); uc.mem_write(out, struct.pack('<ii', k, t))
        return f

    def tick(self):
        e = self.e; self.frame += 1; e.wd(NOWBLK, self.frame)
        S = STACK + 0x20000; e.wq(S, RET)
        e.wq(S + 0x28, BLK + 0x100); e.wq(S + 0x30, NOWBLK); e.wq(S + 0x38, BLK + 0x200); e.wq(S + 0x40, SIT); e.wq(S + 0x48, BLK + 0x300)
        e.wf(S + 0x50, self.ctxfloat); e.wd(S + 0x58, 0); e.wq(S + 0x60, BLK + 0x400); e.wq(S + 0x68, BLK + 0x800); e.wq(S + 0x70, BLK + 0x500)
        e.sreg('rcx', MGR); e.sreg('rdx', MATCH); e.sreg('r8', CTX8); e.sreg('r9', BLK + 0x600); e.sreg('rsp', S)
        return e.run(LOOP, count=300000)

    def state(self):
        e = self.e; return dict(cur=e.rd(MGR + 0x530), kind=e.rd(MGR + 0x538), tgt=e.rd(MGR + 0x53c), n=e.rd(MGR + 0x534))

    def cands(self, frame): return [i for f, i, s in self.log if f == frame and s == 1]
    def tried(self, frame): return [i for f, i, s in self.log if f == frame and s == 2]


def hdr(t): print("\n" + "=" * 100 + "\n" + t + "\n" + "=" * 100)


if __name__ == '__main__':
    sec = sys.argv[1:] or ['A', 'B', 'C', 'D']
    if 'A' in sec:
        hdr("A  ImageUnitCross::canStart -- the roll segment 0x14567b3c0..0x14567b548, REAL bytes, REAL LCG")
        print("score = f(attr 0x1d) [+30 style] [+40 card 0xe] * situational factor, capped 100; accept iff score >= draw, draw=RandInt(100) seeded from int(t*1500)")
        print(" attr  card style state sil this14 | score draw accept")
        for attr in (40, 60, 70, 75, 80, 85, 90, 99):
            r, acc, g = cross_roll(attr=attr); print(f"  {attr:3d}    -     -     0   0  0xff  | {g.get('score'):5} {g.get('draw'):4}  {acc}  {r if r != 'OK' else ''}")
        for kw in (dict(card_e=True), dict(style8=True), dict(com3=True), dict(card_e=True, style8=True), dict(state=4), dict(sil=1), dict(sil=1, state=4), dict(this14=3), dict(attr=99, card_e=True, style8=True, sil=1, state=4)):
            r, acc, g = cross_roll(**{**dict(attr=80), **kw}); print(f"  {kw}  | score {g.get('score')} draw {g.get('draw')} accept {acc} {r if r != 'OK' else ''}")
        base = cross_roll(attr=80)[2]['score']
        print("\n draw vs latched time t (seed=int(t*1500)); attr 80 no bonuses -> score", base)
        draws = []; accs = 0; N = 0
        for k in range(0, 3000):
            t = k / 1500.0; r, acc, g = cross_roll(attr=80, seed_t=t); draws.append(g['draw']); accs += acc; N += 1
        print(f"  t=0..2s step 1/1500: draws min {min(draws)} max {max(draws)} distinct {len(set(draws))}  accept rate {accs / N:.3f} ((score+1)/100 = {(base + 1) / 100:.2f})")
        same = [cross_roll(attr=80, seed_t=12.5)[2]['draw'] for _ in range(3)]; print("  same t=12.5 three times -> draws", same, "(deterministic in t)")
        print("  consecutive seeds t=12.5000,12.5007,12.5013 ->", [cross_roll(attr=80, seed_t=12.5 + k / 1500)[2]['draw'] for k in range(3)])
        print("\n empirical accept rate over 1500 seeds, by attr (no card/style):")
        for attr in (40, 70, 75, 80, 85, 90, 99):
            a = sum(cross_roll(attr=attr, seed_t=k / 1500)[1] for k in range(1500)); print(f"   attr {attr}: {a / 1500:.3f}   score {cross_roll(attr=attr)[2]['score']}")
        for kw, lab in ((dict(card_e=True), 'card 0xe'), (dict(style8=True), 'style bit8'), (dict(card_e=True, style8=True), 'both')):
            a = sum(cross_roll(attr=80, seed_t=k / 1500, **kw)[1] for k in range(1500)); print(f"   attr 80 + {lab}: {a / 1500:.3f}   score {cross_roll(attr=80, **kw)[2]['score']}")
    if 'B' in sec:
        hdr("B  DribbleImage slot 2 = weight, REAL functions 0x1456bb810 (Roulette) and 0x1456bcb10 (BodyFake)")
        print(" attrs read via 0x1442dd5b0 -> R[0x3d+idx] (second array). Roulette: 0x18,0x1a,0x2a,0x2c ; BodyFake: 0x18,0x28,0x2c,0x19")
        for v in (40, 70, 75, 80, 85, 90, 99):
            r1, w1 = weight(0x1456bb810, {0x18: v, 0x1a: v, 0x2a: v, 0x2c: v}, cards=(2,)); r2, w2 = weight(0x1456bcb10, {0x18: v, 0x28: v, 0x2c: v, 0x19: v}, cards=(0,))
            print(f"  all four attrs={v}: Roulette(card2) {w1:6.2f}   BodyFake(card0) {w2:6.2f}  {r1 if r1 != 'OK' else ''}{r2 if r2 != 'OK' else ''}")
        print(" Roulette single-attribute sensitivity (others 70):")
        for k, n in ((0x18, 'BallControl'), (0x1a, 'Finishing'), (0x2a, 'Balance'), (0x2c, 'Accel')):
            print(f"   {n:12s} 90 -> {weight(0x1456bb810, {0x18: 70, 0x1a: 70, 0x2a: 70, 0x2c: 70, k: 90}, cards=(2,))[1]:.2f}")
        print(" Roulette COM bit0:", weight(0x1456bb810, {0x18: 90, 0x1a: 90, 0x2a: 90, 0x2c: 90}, cards=(2,), com=1)[1], " no card2:", weight(0x1456bb810, {0x18: 90, 0x1a: 90, 0x2a: 90, 0x2c: 90})[1])
        print(" BodyFake single-attribute sensitivity (others 70):")
        for k, n in ((0x18, 'BallControl'), (0x28, 'Speed'), (0x2c, 'Accel'), (0x19, 'TightPoss')):
            print(f"   {n:12s} 90 -> {weight(0x1456bcb10, {0x18: 70, 0x28: 70, 0x2c: 70, 0x19: 70, k: 90}, cards=(0,))[1]:.2f}")
        A = {0x18: 90, 0x28: 90, 0x2c: 90, 0x19: 90}
        print(" BodyFake all 90: card0", weight(0x1456bcb10, A, cards=(0,))[1], " card0+COM0", weight(0x1456bcb10, A, cards=(0,), com=1)[1], " nocard", weight(0x1456bcb10, A)[1], " nocard+COM2", weight(0x1456bcb10, A, com=4)[1], " nocard+COM2+COM4", weight(0x1456bcb10, A, com=0x14)[1], " nocard+COM0", weight(0x1456bcb10, A, com=1)[1])
    if 'C' in sec:
        hdr("C  Stage A 0x1456a9570 end to end: REAL pool fill 0x1456ab3b0 (card gates), REAL sort, REAL LCG, stubbed weights")
        W = {2: 90.0, 8: 50.0, 4: 30.0, 9: 10.0, 12: 0.0, 5: 100.0, 3: 60.0, 6: 70.0, 7: 20.0, 10: 40.0, 11: 80.0, 14: 55.0, 15: 65.0}
        r, pool, short, calls = stage_a(W); print(" no cards:  pool", pool, [MOVES[i] for i in pool]); print("   shortlist", short, r if r != 'OK' else '')
        r, pool, short, calls = stage_a(W, cards=(0x28, 2, 0x29, 1, 3, 0x43, 0x42), com_team=1, com_ent=1); print(" all 7 cards + COM0: pool", pool, [MOVES[i] for i in pool]); print("   shortlist", short)
        r, pool, short, calls = stage_a(W, cards=(1,), com_team=0, com_ent=0); print(" card 1 without COM0 (Eracico needs both): pool", pool)
        r, pool, short, calls = stage_a(W, cards=(), com_team=1, com_ent=0); print(" COM0 on team block only: pool", pool)
        freq = Counter(); N = 400
        for ms in range(N):
            r, pool, short, calls = stage_a(W, cards=(0x28, 2, 0x29, 1, 3, 0x43, 0x42), com_team=1, com_ent=1, clock_ms=1000 + ms * 17)
            for i in short: freq[i] += 1
        print(f" shortlist frequency over {N} clock values (expect ~weight/100 for weight<=100, always for 100):")
        for i in sorted(W): print(f"   move {i:2d} {MOVES[i]:12s} weight {W[i]:5.1f}: {freq[i] / N:.3f}")
        r, pool, short, calls = stage_a(W, cards=(0x28, 2, 0x29, 1, 3, 0x43, 0x42), com_team=1, com_ent=1, level=6); print(" level>=6 (x1.2): shortlist", short)
        r, pool, short, calls = stage_a(W, cards=(0x28, 2, 0x29, 1, 3, 0x43, 0x42), com_team=1, com_ent=1, scaleA=1.0, scaleB=0.5); print(" scaleA>scaleB(0.5): shortlist", short)
        print(" ordering of slot-2 calls = pool order:", stage_a(W, cards=(0x28, 2, 0x29, 1, 3, 0x43, 0x42), com_team=1, com_ent=1)[3])
        print(" shortlist order for clock 1000:", stage_a(W, cards=(0x28, 2, 0x29, 1, 3, 0x43, 0x42), com_team=1, com_ent=1, clock_ms=1000)[2], "(sorted by weight desc, then rolled)")
    if 'D' in sec:
        hdr("D  image loop 0x14566aa10 with 16 instrumented fake units")
        for cls in (0, 1, 2, 3, 4):
            w = ImageWorld(sit_class=cls, shots=False); r = w.tick(); print(f" class {cls} no-shot candidate list:", [NAMES[i] for i in w.cands(1)], r if r != 'OK' else '')
        w = ImageWorld(sit_class=1, shots=True); w.tick(); print(" class 1 with shots:", [NAMES[i] for i in w.cands(1)])
        w = ImageWorld(sit_class=1, safety714=1); w.tick(); print(" class 1 with mgr+0x714>0:", [NAMES[i] for i in w.cands(1)])
        w = ImageWorld(sit_class=1, profile84=1, ctxfloat=99.0); w.tick(); print(" class 1 with ctx8+0x84==1 and float>thr:", [NAMES[i] for i in w.cands(1)])
        w = ImageWorld(sit_class=0, listcount=2); w.tick(); print(" class 0 with list>=2 (mgr+0x714=0):", [NAMES[i] for i in w.cands(1)])
        w = ImageWorld(sit_class=1); w.tick(); print(" tried canStart order (all false):", [NAMES[i] for i in w.tried(1)], "state", w.state())
        w = ImageWorld(sit_class=1); w.canstart = {9: True, 10: True}; w.tick(); print(" Cross+Long both true -> held", NAMES[w.state()['cur']], "tried", [NAMES[i] for i in w.tried(1)], "(first TRUE in list order wins; later never asked)")
        w = ImageWorld(sit_class=1); w.canstart = {9: True}; w.execout = {9: (5, 7)}; w.tick(); s = w.state(); print(" Cross held, execute wrote kind/target:", s)
        w.canstart = {9: True, 13: True}; w.tick(); print(" next frame Expand (earlier in list) also true -> held", NAMES[w.state()['cur']], "tried", [NAMES[i] for i in w.tried(2)], "PREEMPTION by earlier-listed image")
        w = ImageWorld(sit_class=1); w.canstart = {9: True}; w.tick(); w.canstart = {9: True, 1: True}; w.tick(); print(" Cross held, Dribble(last) true next frame -> held", NAMES[w.state()['cur']], "tried", [NAMES[i] for i in w.tried(2)], "(stops at held one)")
        w = ImageWorld(sit_class=1, cooldown=54); w.canstart = {9: True}; w.tick(); w.shouldend = {9: True}; w.tick(); print(" Cross ends at frame 2 -> state", w.state(), "onEnd called:", any(s == 4 for f, i, s in w.log if f == 2), "tried after end:", [NAMES[i] for i in w.tried(2)])
        w.shouldend = {}; w.canstart = {9: True}
        held = []
        for k in range(60): w.tick(); held.append(w.state()['cur'])
        first = next((k + 3 for k, h in enumerate(held) if h == 9), None); print(f" Cross wants restart every frame: re-held at frame {first} (ended frame 2, cooldown getter=54 -> expect 2+54=56)")
        w = ImageWorld(sit_class=1, shots=True, cooldown=54); w.canstart = {3: True}; w.tick(); w.shouldend = {3: True}; w.tick(); w.shouldend = {}; w.tick(); print(" ShotShort(3) ends frame 2, retried frame 3 -> held", NAMES[w.state()['cur']], "(index 3 exempt from cooldown)")
        w = ImageWorld(sit_class=1); w.canstart = {9: True}; w.tick(); w.abort = 1; w.tick(); print(" abort flag -> state", w.state(), "slot0 reset called on held:", any(i == 9 and s == 0 for f, i, s in w.log if f == 2))
        w = ImageWorld(sit_class=1); w.tick(); print(" nothing startable: Dribble(1) asked last:", w.tried(1)[-1] == 1, "state", w.state(), "execute called on None(0):", any(i == 0 and s == 5 for f, i, s in w.log))
