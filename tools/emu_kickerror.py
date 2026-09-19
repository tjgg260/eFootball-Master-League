#!/usr/bin/env python3
"""
emu_kickerror.py - emulation proof for the SPRINT-EXERTION (and optional WEAK-FOOT) kick-error code cave
(spec files keep their historical names cave-fatigue*.json; the input is NOT tiredness - see S10).

Nothing here touches the game: images are opened READ-ONLY (mmap ACCESS_READ), their pages are lazily
copied into a Unicorn address space, and the cave/hook bytes are overlaid IN THE EMULATOR ONLY.
By default the PRISTINE backup (~/Backups/eFootball/eFootball.exe.PRISTINE) is emulated, so the proof is
against STOCK code even while the live exe carries other patches; the live exe is checked for
"hook bytes still stock, padding still int3" and used for the LIVE tables in S9/S10.  --exe <path> emulates
any other image.

    python tools/emu_kickerror.py                          # exertion build: every proof, print the tables
    python tools/emu_kickerror.py --write-spec             # + (re)generate tools/data/patches/cave-fatigue.json
    python tools/emu_kickerror.py --wf 50 [--write-spec]   # + weak-foot variant -> cave-fatigue-weakfoot.json
    python tools/emu_kickerror.py --tiredness none [--write-spec]   # ABILITY BASELINE -> cave-ability-error.json
    python tools/emu_kickerror.py --k 4.25 --gain 1.0 --axes hvp    # other tunables (a spec is only written if all proofs pass)

Model (builder 0x14401a900, hook 0x14401b3a7 = the 8-byte 'movss xmm3,[rip->4.25f]'):
    --tiredness meter : S = max(0, min(1, 1 - gain * t * (1 - f)))  t = meter/100   (wf variant: max(meter, WF)/100)
    --tiredness none  : S = max(0, min(1, 1 - gain * (1 - f)))      ABILITY ALONE - no situational input, so a bad
                        player mis-hits a standing, unpressured kick.  Defaults K=4.25 (STOCK), gain=0.35, axes=hvp.
    chosen axes:  c1 (xmm1, horizontal), c2 (xmm12, vertical), c3 (xmm6, power)  *=  S ;   xmm3 = K (immediate)
    game then does  ceiling = (1-c)*Hceil / (1-c)*Vceil / (1-c)*Prate ,  sigma = max(.1, .75 + K*(1-s)^2)

What is demonstrated (each section prints its own numbers):
  S1  static: stolen bytes at the hook, return address, no branch lands inside the stolen instruction,
      nothing between the hook and the next call reads flags or rax/xmm0/xmm2/xmm5, padding is all int3,
      xmm9 is zeroed once before the hook and never rewritten (only the weak-foot cave relies on it).
  S2  whole-builder run (game code, every CALL stubbed except the pure fold 0x144021780): at the hook
      rdi = arg2 (player), rsi = arg1 (out struct), [rsp+0x40] = the float returned by 0x143ed71d0 (f),
      xmm8 = 1.0, xmm9 = 0.0, xmm15 = 0.75, factor-array slots 0..5 land in xmm1/xmm12/xmm6/xmm13/xmm10/xmm7.
  S2b [rsp+0x40] is stored once and the builder itself re-reads it as f AFTER the hook (0x14401b72f); the five
      factor functions, run with their calls stubbed three ways and a write-watch on the slot, never write it.
  S3  stock region hook..0x14401b4bc with marker values: which register feeds which output field;
      differential scratch test (garbage A vs B in rax/rcx/rdx/r8-r11/xmm0,2,3,4,5).
  S4  cave standalone: register diff before/after, no memory writes, rsp untouched; meter=0 is BIT-exact; unscaled
      axes BIT-exact; hostile inputs (meter 1e9/inf/NaN/negative, f<0/NaN, gain 2.0) keep S inside [0,1].
  S5  patched end-to-end (hook jmp -> cave -> back -> stock tail) vs unpatched: output struct; hostile inputs bounded.
  S6  the game's own meter writer clamps player+0x30f4 to 0..100; 0x143ed71d0 f range (f CAN exceed 1).
  S7  weak foot: inline attribute read == the game's ATTR_get 0x143ea8cb0; the cave's weak/strong decision
      == the game's own branch at 0x143ed787a..0x143ed7899 (emulated as the oracle).
  S8  stamina lead: 0x145614eb0 returns a POSITION vec3 (+0.3 on y), not a stamina value.
  S9  what the STOCK game already does with the meter: census of every [reg+0x30f4] access; the one read inside a
      c-factor function (0x14401c143) scales ONLY the horizontal slot (fragment emulated: x0.36 at f=0.1, x0.72 at
      f=0.7, full meter); the other five readers are post-hook mishit-type odds.  Hence the default axes = vp.
      Side fact: the horizontal c carries an unconditional x0.86-0.90 kick-class term on 172 of 176 kick ids.
  S10 what the meter IS: the real updater emulated at 60 fps - rises only in action ids 4/5/6 above the speed gate,
      full in 2.5 s, empty 0.5 s after slowing, frozen (or -500/s) during kick actions.  Sprint exertion, not tiredness.
  --- ABILITY BUILD ONLY (--tiredness none) -------------------------------------------------------------------
  S11 is there already a STOCK ability baseline?  Each of the five factor functions run on an all-1.0 array with a
      zeroed world and its calls stubbed three ways, f swept 0..1.2: every factor that is 1.0 at zero difficulty
      stays 1.0 for every f, so NO, and the cave double-counts nothing.
  S12 Monte Carlo: whole builder (stock vs patched) -> 0x3c kick-miss struct -> the game's REAL type-4 randomiser
      0x14401a060 with its real LCG + Box-Muller, n draws per row, for abilities 40/60/75/90/99.
  S13 gain sweep with the same machinery, in degrees and in cm over a 20 m pass: the evidence for the default gain.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dt270_schema_gen import Image  # PE image w/ rva2off/read (read-only mmap)

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED,
                     UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UC_HOOK_MEM_WRITE, UcError)
from unicorn import x86_const as X
import capstone
import keystone
import numpy as np

REPO = Path(__file__).resolve().parent.parent
EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
SPEC = REPO / "tools" / "data" / "patches" / "cave-fatigue.json"

BUILDER = 0x14401A900
BUILDER_END = 0x14401B900          # generous; only used for the branch-target scan
HOOK = 0x14401B3A7                 # movss xmm3,[rip->4.25f]  (8 bytes)
HOOK_RET = 0x14401B3AF             # lea r9,[rsi+0x20]
XMM9_ZERO = 0x14401AA2E            # xorps xmm9,xmm9 (the builder's 0.0f)
TAIL_CALL = 0x14401B4BC            # call 0x144021870 (first call after the hook)
STOLEN = bytes.fromhex("f30f101d011cb202")
CAVE_A = 0x1438B4835               # 91 bytes of int3
CAVE_A_LEN = 91
CAVE_B = 0x1438B4804               # 44 bytes of int3
CAVE_B_LEN = 44
F_ABILITY = 0x143ED71D0            # player -> ability factor f
F_ABILITY_INNER = 0x143ED7440
FOLD = 0x144021780
COOKIE_CHECK = 0x144F7E0D0
ATTR_GET = 0x143EA8CB0
G_MATCH = 0x1486BD888              # global used by 0x1442d6ef0 (team/player table root)

ARENA = 0x10000000
ARENA_SZ = 0x200000
PLAYER = ARENA + 0x00000
OUT = ARENA + 0x20000
VEC = ARENA + 0x21000
FRAME = ARENA + 0x40000            # fake rbp frame for region runs
STACK_TOP = ARENA + 0x100000
RET_MAGIC = 0x7FFF0000

XMM = [getattr(X, f"UC_X86_REG_XMM{i}") for i in range(16)]
GPR = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in
       "rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15".split()}


def f2i(v: float) -> int: return struct.unpack("<I", struct.pack("<f", v))[0]
def i2f(v: int) -> float: return struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]


# ----------------------------------------------------------------------------------------------
# cave source (single source of truth for BOTH the emulation and the spec file)
# ----------------------------------------------------------------------------------------------
AXIS_REG = {"h": ("xmm1", "c1 horizontal"), "v": ("xmm12", "c2 vertical"), "p": ("xmm6", "c3 power")}


def cave_source(k: float, gain: float, wf: float | None, axes: str = "vp", tiredness: str = "meter"):
    """Returns [(va, maxlen, asm_text)], ENTRY PART FIRST.  Registers written: rax, xmm0, xmm2, xmm5 (dead
    scratch at the hook), xmm3 (= K, the stolen load) and the chosen magnitudes (axes: h=xmm1, v=xmm12, p=xmm6).
    No stack use, no calls, no memory writes.  Flags are clobbered only in the weak-foot variant
    (flags are dead at the hook: S1).

    tiredness="meter" : E = gain * (meter/100) * (1-f)   - the sprint-exertion build (cave-fatigue.json)
    tiredness="none"  : E = gain * (1-f)                 - the ABILITY-BASELINE build (cave-ability-error.json):
                        no situational input at all, so a poor player mis-hits a standing, unpressured kick.
    S is clamped on BOTH sides: minss 1.0 (NaN-safe: a NaN S becomes 1.0) then maxss 0.0, so whatever the
    meter / f / gain hold, every c stays inside [0, c] and every ceiling inside [stock, full ceiling].
    The fatigue-only cave zeroes its own scratch (xorps xmm0); the weak-foot variant has no room for that
    and uses xmm9, which the builder zeroes once at 0x14401aa2e and never writes again before the hook
    (S1 static + S2 dynamic)."""
    floor = ("""
        xorps xmm0, xmm0
        maxss xmm2, xmm0                    ; S >= 0  (gain > 1, corrupt meter, f < 0)""" if wf is None else """
        maxss xmm2, xmm9                    ; S >= 0  (xmm9 = the builder's 0.0f: S1/S2)""")
    mults = "".join(f"""
        mulss {AXIS_REG[a][0]}, xmm2                   ; {AXIS_REG[a][1]}""" for a in "hvp" if a in axes)
    tail = f"""
        movaps xmm5, xmm8                   ; 1.0 (xmm8 is the builder's 1.0f; the stock tail uses it the same way)
        subss xmm5, dword ptr [rsp + 0x40]  ; 1 - f
        mulss xmm0, xmm5                    ; E = gain*t*(1-f)
        movaps xmm2, xmm8
        subss xmm2, xmm0                    ; S = 1 - E
        minss xmm2, xmm8                    ; S <= 1  (f can exceed 1 via ability bonuses: S6; NaN -> 1.0){floor}{mults}
        jmp {HOOK_RET:#x}
    """
    if tiredness == "none":
        # ABILITY BASELINE: no meter read at all.  E = gain*(1-f); everything else (the double clamp, the
        # axis multiplies, the return) is byte-for-byte the same tail as the exertion build.
        assert wf is None, "--wf needs the exertion meter (t); it is meaningless with --tiredness none"
        a = f"""
        mov eax, {f2i(k):#x}
        movd xmm3, eax                      ; K  (replaces the stolen movss xmm3,[4.25f])
        mov eax, {f2i(gain):#x}
        movd xmm0, eax                      ; gain   (t == 1: ability alone, no situational input)
        """ + tail
        return [(CAVE_A, CAVE_A_LEN, a)]
    if wf is None:
        a = f"""
        mov eax, {f2i(k):#x}
        movd xmm3, eax                      ; K  (replaces the stolen movss xmm3,[4.25f])
        mov eax, {f2i(gain):#x}
        movd xmm0, eax                      ; gain
        movss xmm5, dword ptr [rdi + 0x30f4]
        mulss xmm5, dword ptr [rip + RIPREL_0x145aacd38] ; t = meter * 0.01f (the game's own normaliser cell, cf 0x14401c14c)
        mulss xmm0, xmm5                    ; gain*t
        """ + tail
        return [(CAVE_A, CAVE_A_LEN, a)]
    # ---- weak-foot variant: entry in the 44-byte run, short-jumps into the adjacent 91-byte run ----
    # t is kept in METER UNITS (0..100) and the 0.01 is folded into the gain immediate (= gain/100);
    # the weak-foot floor is a re-aimable pool cell (meter units).
    wf_cell = WF_CELLS[wf]
    part2 = f"""
        add rax, qword ptr [rip + RIPREL_{G_MATCH:#x}]
        mov rax, qword ptr [rax + 0x55a8]   ; per-player match data (0x1442d6ef0)
        cmp byte ptr [rax + 0x3c9], 0       ; ability byte 0x394+0x35 (stronger foot) == 0 ?   (0x144301840 / 0x1441172b0)
        sete al
        cmp al, byte ptr [rdi + 0x2bf6]     ; == kicking foot  ->  weak-foot kick  (game: 0x143ed788b..0x143ed7899)
        jne nowf
        maxss xmm5, dword ptr [rip + RIPREL_{wf_cell:#x}] ; t = max(meter, WF floor)
    nowf:
        mulss xmm0, xmm5                    ; (gain/100)*t
    """ + tail
    p2 = assemble([(CAVE_A, CAVE_A_LEN, part2)])[0][2]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    nowf = next(i.address for i in md.disasm(p2, CAVE_A) if i.mnemonic == "mulss" and i.op_str == "xmm0, xmm5")
    part1 = f"""
        mov eax, {f2i(k):#x}
        movd xmm3, eax                      ; K
        mov eax, {f2i(gain / 100.0):#x}
        movd xmm0, eax                      ; gain/100
        movss xmm5, dword ptr [rdi + 0x30f4]; t = meter (0..100)
        movsx eax, byte ptr [rdi + 0x2bd8]  ; player slot, exactly as ATTR_get 0x143ea8cb0 reads it
        cmp eax, 0x1f
        jae {nowf:#x}                        ; out of range: the game would use slot 0; we just skip weak foot
        imul rax, rax, 0x58
        jmp {CAVE_A:#x}
    """
    return [(CAVE_B, CAVE_B_LEN, part1), (CAVE_A, CAVE_A_LEN, part2)]


WF_CELLS = {25.0: 0x145DA7DE0, 30.0: 0x145A8DD80, 40.0: 0x145D58EC8, 50.0: 0x145AE7580, 60.0: 0x145A8DD84,
            75.0: 0x145E9C05C}   # read-only .tls$ pool floats (census: 180..1512 referrers, 0 writers)


def assemble(parts):
    """keystone for the text; `[rip + RIPREL_0x<va>]` operands are assembled with a dummy disp32 and then
    fixed up to the absolute target (keystone would otherwise take the number as a raw displacement)."""
    import re
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    out = []
    for va, maxlen, text in parts:
        src = "\n".join(l.split(";")[0] for l in text.splitlines())
        targets = [int(t, 16) for t in re.findall(r"RIPREL_(0x[0-9a-fA-F]+)", src)]
        src = re.sub(r"RIPREL_0x[0-9a-fA-F]+", "0x11223344", src)
        enc, _ = ks.asm(src, va)
        b = bytearray(enc)
        it = iter(targets)
        for ins in md.disasm(bytes(b), va):
            if ins.disp_offset and ins.disp == 0x11223344:
                tgt = next(it)
                o = ins.address - va + ins.disp_offset
                b[o:o + 4] = struct.pack("<i", tgt - (ins.address + ins.size))
        assert next(it, None) is None, "unresolved RIPREL"
        if len(b) > maxlen:
            raise SystemExit(f"cave part at {va:#x} is {len(b)} bytes > {maxlen} available")
        out.append((va, maxlen, bytes(b)))
    return out


def hook_bytes(entry: int = CAVE_A):
    rel = entry - (HOOK + 5)
    return b"\xe9" + struct.pack("<i", rel) + b"\x0f\x1f\x00"   # jmp cave ; 3-byte nop (never executed)


def find_imm(code: bytes, va: int, imm: int, nth: int = 0):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    n = 0
    for ins in md.disasm(code, va):
        if ins.mnemonic == "mov" and ins.op_str.startswith("eax, ") and ins.bytes[0] == 0xB8 \
                and struct.unpack("<I", ins.bytes[1:5])[0] == imm:
            if n == nth:
                return ins.address + 1
            n += 1
    return None


# ----------------------------------------------------------------------------------------------
# emulator
# ----------------------------------------------------------------------------------------------
class Emu:
    def __init__(self, img: Image, permissive: bool = False):
        self.img = img
        self.permissive = permissive
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        uc.mem_map(ARENA, ARENA_SZ)
        uc.mem_map(RET_MAGIC, 0x1000)
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED,
                    self._unmapped)
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.overlays = []

    def _map_img(self, b):
        img = self.img
        self.uc.mem_map(b, 0x10000)
        self.uc.mem_write(b, b"".join(img.read(b - img.base + k * 0x1000, 0x1000) for k in range(16)))
        self.mapped.add(b)
        for va, data in self.overlays:
            if b <= va < b + 0x10000:
                self.uc.mem_write(va, data)

    def _unmapped(self, uc, access, addr, size, value, ud):
        img = self.img
        if img.base <= addr < img.base + img.size_of_image:
            base = addr & ~0xFFFF
            for b in (base, base + 0x10000):
                if b not in self.mapped:
                    self._map_img(b)
            return True
        if self.permissive:
            b = addr & ~0xFFFF
            try:
                uc.mem_map(b, 0x10000)
            except UcError:
                return False
            return True
        return False

    def overlay(self, va: int, data: bytes):
        """Emulator-only patch (the file on disk is never written)."""
        self.overlays.append((va, data))
        for b in {va & ~0xFFFF, (va + len(data)) & ~0xFFFF}:
            if b not in self.mapped:
                self._map_img(b)
        self.uc.mem_write(va, data)

    # register helpers
    def setx(self, i, v): self.uc.reg_write(XMM[i], f2i(v))
    def getx(self, i): return i2f(self.uc.reg_read(XMM[i]) & 0xFFFFFFFF)
    def setx_raw(self, i, v): self.uc.reg_write(XMM[i], v)
    def getx_raw(self, i): return self.uc.reg_read(XMM[i])
    def wf(self, addr, v): self.uc.mem_write(addr, struct.pack("<f", v))
    def rf(self, addr): return struct.unpack("<f", bytes(self.uc.mem_read(addr, 4)))[0]

    def snapshot(self):
        s = {n: self.uc.reg_read(r) for n, r in GPR.items()}
        s.update({f"xmm{i}": self.uc.reg_read(XMM[i]) for i in range(16)})
        s["eflags"] = self.uc.reg_read(X.UC_X86_REG_EFLAGS)
        return s


def diff(a, b, ignore=()):
    return {k: (a[k], b[k]) for k in a if a[k] != b[k] and k not in ignore}


def show_regdiff(d):
    for k, (u, v) in d.items():
        if k.startswith("xmm"):
            print(f"      {k:6s} {i2f(u):.6g} -> {i2f(v):.6g}   (raw {u & 0xffffffff:#010x} -> {v & 0xffffffff:#010x})")
        else:
            print(f"      {k:6s} {u:#x} -> {v:#x}")


# ----------------------------------------------------------------------------------------------
# S1 static checks
# ----------------------------------------------------------------------------------------------
def s1_static(img: Image, parts):
    print("\n== S1  static facts on the exe on disk ==")
    ok = True
    got = img.read(HOOK - img.base, 8)
    print(f"  hook {HOOK:#x}: bytes {got.hex(' ')}  expected {STOLEN.hex(' ')}  -> {'OK' if got == STOLEN else 'MISMATCH'}")
    ok &= got == STOLEN
    ins = next(img.md.disasm(got + img.read(HOOK_RET - img.base, 8), HOOK))
    cell = ins.address + ins.size + ins.operands[1].mem.disp
    kval = struct.unpack("<f", img.read(cell - img.base, 4))[0]
    print(f"    = {ins.mnemonic} {ins.op_str}   (cell {cell:#x} = {kval}f)   size {ins.size} -> return {ins.address + ins.size:#x}")
    ok &= ins.address + ins.size == HOOK_RET and ins.size == 8
    nxt = next(img.md.disasm(img.read(HOOK_RET - img.base, 8), HOOK_RET))
    print(f"    return instruction {HOOK_RET:#x}: {nxt.mnemonic} {nxt.op_str}")
    # branch targets into the stolen instruction (other than its first byte)
    bad, into = [], []
    for i in img.md.disasm(img.read(BUILDER - img.base, BUILDER_END - BUILDER), BUILDER):
        if i.mnemonic.startswith("j") and i.operands and i.operands[0].type == capstone.x86.X86_OP_IMM:
            t = i.operands[0].imm
            if HOOK < t < HOOK_RET:
                bad.append((i.address, t))
            if t == HOOK:
                into.append(i.address)
    print(f"    branches to the hook's first byte (fine): {[hex(x) for x in into]}")
    print(f"    branches INTO the stolen instruction body: {bad or 'none'}")
    ok &= not bad
    # flags / scratch use between hook and the first call
    flag_readers, scratch_reads = [], []
    written = set()
    sc = {capstone.x86.X86_REG_XMM0: "xmm0", capstone.x86.X86_REG_XMM2: "xmm2", capstone.x86.X86_REG_XMM5: "xmm5",
          capstone.x86.X86_REG_RAX: "rax", capstone.x86.X86_REG_EAX: "rax", capstone.x86.X86_REG_AL: "rax"}
    for i in img.md.disasm(img.read(HOOK_RET - img.base, TAIL_CALL - HOOK_RET), HOOK_RET):
        rr, rw = i.regs_access()
        if capstone.x86.X86_REG_EFLAGS in rr:
            flag_readers.append(hex(i.address))
        for r in rr:
            if r in sc and sc[r] not in written:
                scratch_reads.append((hex(i.address), sc[r], f"{i.mnemonic} {i.op_str}"))
        for r in rw:
            if r in sc:
                written.add(sc[r])
    print(f"    flag readers {HOOK_RET:#x}..{TAIL_CALL:#x}: {flag_readers or 'none'}")
    print(f"    reads of rax/xmm0/xmm2/xmm5 before a write in that span: {scratch_reads or 'none'}"
          f"   (written there: {sorted(written)})")
    ok &= not flag_readers and not scratch_reads
    # xmm9: zeroed once (0x14401aa2e) on the straight-line entry path and never written again before the hook.
    # (xmm6-xmm15 are callee-saved in the Win64 ABI; the builder itself reads xmm9 as 0.0 at 0x14401b0a4 and,
    #  after the hook, at 0x14401b5d1/0x14401b5da.)  Only the weak-foot cave relies on this.
    x9_writes, skip = [], []
    for i in img.md.disasm(img.read(BUILDER - img.base, HOOK - BUILDER), BUILDER):
        _, rw = i.regs_access()
        if capstone.x86.X86_REG_XMM9 in rw:
            x9_writes.append(f"{i.address:#x} {i.mnemonic} {i.op_str}")
        if i.mnemonic.startswith("j") and i.operands and i.operands[0].type == capstone.x86.X86_OP_IMM \
                and i.address < XMM9_ZERO < i.operands[0].imm:
            skip.append(hex(i.address))
    print(f"    writes to xmm9 between the builder entry and the hook: {x9_writes}")
    print(f"    branches that jump over {XMM9_ZERO:#x}: {skip or 'none'}")
    ok &= x9_writes == [f"{XMM9_ZERO:#x} xorps xmm9, xmm9"] and not skip
    for va, maxlen, b in parts:
        pad = img.read(va - img.base, maxlen)
        allcc = pad == b"\xcc" * maxlen
        print(f"  cave {va:#x}: {maxlen} bytes on disk all int3: {allcc};  cave code {len(b)} bytes")
        ok &= allcc
    print(f"  S1 {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# S2 whole-builder run with stubbed calls
# ----------------------------------------------------------------------------------------------
def s2_builder(img: Image):
    print("\n== S2  whole builder 0x14401a900 (game code; calls stubbed, fold 0x144021780 real) ==")
    F_MARK = 0.3125
    # six slots written into the FIRST factor array (r9 of 0x14401eb40); other arrays stay 1.0
    slots = [0.91, 0.82, 0.73, 0.64, 0.55, 0.46]
    e = Emu(img, permissive=True)
    uc = e.uc
    state = {}
    md = e.md

    def code(uc_, addr, size, ud):
        if addr == HOOK:
            state["hook"] = e.snapshot()
            state["f_slot"] = e.rf(uc_.reg_read(X.UC_X86_REG_RSP) + 0x40)
            uc_.emu_stop()
            return
        if addr in (0x140E999A0, 0x140E999B0, 0x144F8307A):    # the sort's malloc / free / memcpy import
            rsp_ = uc_.reg_read(X.UC_X86_REG_RSP)
            if addr == 0x140E999A0:
                state["heap"] = state.get("heap", ARENA + 0x180000) + 0x100
                uc_.reg_write(X.UC_X86_REG_RAX, state["heap"])
            elif addr == 0x144F8307A:
                dst, src_, n = (uc_.reg_read(GPR[r]) for r in ("rcx", "rdx", "r8"))
                uc_.mem_write(dst, bytes(uc_.mem_read(src_, n)))
                uc_.reg_write(X.UC_X86_REG_RAX, dst)
            uc_.reg_write(X.UC_X86_REG_RIP, struct.unpack("<Q", bytes(uc_.mem_read(rsp_, 8)))[0])
            uc_.reg_write(X.UC_X86_REG_RSP, rsp_ + 8)
            return
        if not (BUILDER <= addr < BUILDER_END):
            return
        b = bytes(uc_.mem_read(addr, size))
        if b[0] == 0xE8 or (b[0] == 0xFF and (b[1] >> 3) & 7 == 2):
            tgt = addr + 5 + struct.unpack("<i", b[1:5])[0] if b[0] == 0xE8 else None
            if tgt == FOLD:
                return                                  # run the real fold
            uc_.reg_write(X.UC_X86_REG_RAX, 0)
            if tgt == F_ABILITY:
                uc_.reg_write(XMM[0], f2i(F_MARK))
            elif tgt == 0x14401EB40:
                r9 = uc_.reg_read(X.UC_X86_REG_R9)
                for k, v in enumerate(slots):
                    uc_.mem_write(r9 + 4 * k, struct.pack("<f", v))
            else:
                uc_.reg_write(XMM[0], 0)
            state.setdefault("calls", []).append(tgt)
            uc_.reg_write(X.UC_X86_REG_RIP, addr + size)

    uc.hook_add(UC_HOOK_CODE, code)
    # the fold's /GS cookie check: stub (it only compares)
    e.overlay(COOKIE_CHECK, b"\xc3")
    rsp = STACK_TOP - 0x1000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, OUT)
    uc.reg_write(X.UC_X86_REG_RDX, PLAYER)
    uc.reg_write(X.UC_X86_REG_R8, VEC)
    uc.reg_write(X.UC_X86_REG_R9, VEC + 0x100)
    uc.mem_write(rsp + 0x28, struct.pack("<QQQQ", VEC + 0x200, VEC + 0x300, VEC + 0x400, VEC + 0x500))
    uc.mem_write(PLAYER + 0xAD0, b"\x01")               # action id != 0xa (not a shot)
    uc.mem_write(PLAYER + 0x2F6E, struct.pack("<h", 0x10))
    try:
        uc.emu_start(BUILDER, RET_MAGIC, count=200000)
    except UcError as ex:
        print(f"  emulation stopped: {ex} at rip {uc.reg_read(X.UC_X86_REG_RIP):#x}")
    if "hook" not in state:
        print(f"  did NOT reach the hook - S2 FAIL (rip {uc.reg_read(X.UC_X86_REG_RIP):#x}, calls {[hex(c or 0) for c in state.get('calls', [])][-6:]})")
        return False
    s = state["hook"]
    exp_rsp = rsp - 8 * 8 - 0x1B8
    print(f"  reached hook after {len(state['calls'])} stubbed calls")
    print(f"    rdi = {s['rdi']:#x}   (arg2 / player buffer = {PLAYER:#x})   {'OK' if s['rdi'] == PLAYER else 'NO'}")
    print(f"    rsi = {s['rsi']:#x}   (arg1 / out struct   = {OUT:#x})   {'OK' if s['rsi'] == OUT else 'NO'}")
    print(f"    rsp = {s['rsp']:#x}   (entry rsp - 8 pushes - 0x1b8 = {exp_rsp:#x})   {'OK' if s['rsp'] == exp_rsp else 'NO'}")
    print(f"    [rsp+0x40] = {state['f_slot']}   (0x143ed71d0 stub returned {F_MARK})   {'OK' if state['f_slot'] == F_MARK else 'NO'}")
    x = lambda i: i2f(s[f'xmm{i}'])
    print(f"    xmm8 = {x(8)}  xmm15 = {x(15)}  xmm9 = {x(9)}  xmm14 = {x(14)}")
    print(f"    xmm9 raw low dword = {s['xmm9'] & 0xFFFFFFFF:#010x}  (must be +0.0f)   {'OK' if s['xmm9'] & 0xFFFFFFFF == 0 else 'NO'}")
    # predicted fold of (v,1,1,1): fold(a, b) = (max*min+min)/2 three times with 1.0
    def fold(v):
        acc = (max(1.0, v) * min(1.0, v) + min(1.0, v)) * 0.5
        for _ in range(3):
            acc = (max(acc, 1.0) * min(acc, 1.0) + min(acc, 1.0)) * 0.5
        return acc
    print("    factor-array slot -> register at the hook (value = real fold(slot,1,1,1)):")
    names = {0: "xmm1  (c1 horizontal magnitude)", 1: "xmm12 (c2 vertical magnitude)", 2: "xmm6  (c3 power magnitude)",
             3: "xmm13 (sigma factor horizontal)", 4: "xmm10 (sigma factor vertical)", 5: "xmm7  (sigma factor power)"}
    regs = {0: 1, 1: 12, 2: 6, 3: 13, 4: 10, 5: 7}
    ok = s["rdi"] == PLAYER and s["rsi"] == OUT and s["rsp"] == exp_rsp and state["f_slot"] == F_MARK \
        and x(8) == 1.0 and x(15) == 0.75 and s["xmm9"] & 0xFFFFFFFF == 0
    for k in range(6):
        got = x(regs[k])
        good = abs(got - fold(slots[k])) < 1e-6
        ok &= good
        print(f"      slot[{k}]={slots[k]}  ->  {names[k]} = {got:.6f}   expect {fold(slots[k]):.6f}  {'OK' if good else 'NO'}")
    print(f"  S2 {'PASS' if ok else 'FAIL'}")
    return ok


FACTOR_END = {0x144020D00: 0x144021780, 0x14401EB40: 0x14401F770, 0x14401BDB0: 0x14401CA10, 0x14401CA10: 0x14401D4F0,
              0x14401F770: 0x14401FC80}


def s2b_f_slot(img: Image):
    """Is [rsp+0x40] still f at the hook?  The five factor functions receive r8 = &[rsp+0x40]."""
    print("\n== S2b  [rsp+0x40] (ability factor f) between its store and the hook ==")
    refs = []
    for i in img.md.disasm(img.read(BUILDER - img.base, BUILDER_END - BUILDER), BUILDER):
        if "[rsp + 0x40]" in i.op_str:
            refs.append(f"{i.address:#x} {i.mnemonic} {i.op_str}")
    print("    every builder instruction touching [rsp+0x40]:")
    for r in refs:
        print("      " + r)
    print("    -> one zero-init, ONE store (the 0x143ed71d0 result), address-of passes, and the builder's own READ")
    print("       at 0x14401b72f *after* the hook region: the game itself relies on the slot still being f there.")
    ok = True
    for fn in (0x144020D00, 0x14401EB40, 0x14401BDB0, 0x14401CA10, 0x14401F770):
        # static: registers that hold the r8 argument, and memory writes based on them
        holders = {capstone.x86.X86_REG_R8}
        wr = []
        for i in img.function_body(fn - img.base):
            ops = i.operands
            if i.mnemonic == "mov" and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG \
                    and ops[1].type == capstone.x86.X86_OP_REG:
                if ops[1].reg in holders:
                    holders.add(ops[0].reg)
                elif ops[0].reg in holders and ops[0].reg != capstone.x86.X86_REG_R8:
                    holders.discard(ops[0].reg)
            if ops and ops[0].type == capstone.x86.X86_OP_MEM and ops[0].mem.base in holders \
                    and ops[0].mem.base != capstone.x86.X86_REG_R8 and (ops[0].access & capstone.CS_AC_WRITE) \
                    and ops[0].mem.index == 0:        # (indexed 'add [rsi+rbp*8]' hits are jump-table bytes, not code)
                wr.append(f"{i.address:#x} {i.mnemonic} {i.op_str}")
        # dynamic: run the real function body with every CALL it makes stubbed (three different stub answers, so
        # different branches are taken), laid out as in the builder (rdx = ctx, r8 = ctx+0x10 = &f); write-watch on f.
        runs = []
        for ret_i, ret_f in ((0, 0.0), (1, 0.5), (2, 30.0)):
            e = Emu(img, permissive=True)
            uc = e.uc
            rsp = STACK_TOP - 0x8000
            CTX, OA = ARENA + 0x50000, ARENA + 0x52000
            FS = CTX + 0x10
            uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
            uc.mem_write(rsp + 0x28, struct.pack("<QQ", OA + 0x100, OA + 0x200))   # args 5/6 as seen at entry
            for kk in range(6):
                e.wf(OA + 4 * kk, 1.0)
            e.wf(FS, 0.3125)
            e.wf(PLAYER + 0x30F4, 100.0)
            for r, v in (("rsp", rsp), ("rcx", PLAYER), ("rdx", CTX), ("r8", FS), ("r9", OA)):
                uc.reg_write(GPR[r], v)
            w, ncalls = [], [0]

            def code(u, addr, size, ud, fn=fn, ret_i=ret_i, ret_f=ret_f, ncalls=ncalls):
                b = bytes(u.mem_read(addr, size))
                if b[0] == 0xE8 or (b[0] == 0xFF and (b[1] >> 3) & 7 == 2) or (len(b) > 2 and b[0] in (0x41, 0x48) and b[1] == 0xFF and (b[2] >> 3) & 7 == 2):
                    ncalls[0] += 1
                    u.reg_write(X.UC_X86_REG_RAX, ret_i)
                    u.reg_write(XMM[0], f2i(ret_f))
                    u.reg_write(X.UC_X86_REG_RIP, addr + size)
            fs_, fe_ = fn, FACTOR_END[fn]          # whole body (the exception directory splits these into chunks)
            uc.hook_add(UC_HOOK_CODE, code, begin=fs_, end=fe_)
            uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, a, ad, sz, val, ud, w=w: w.append(ad), begin=FS, end=FS + 3)
            try:
                uc.emu_start(fn, RET_MAGIC, count=300000)
                st = "returned" if uc.reg_read(X.UC_X86_REG_RIP) == RET_MAGIC else f"stopped at {uc.reg_read(X.UC_X86_REG_RIP):#x}"
            except UcError as ex:
                st = f"faulted at {uc.reg_read(X.UC_X86_REG_RIP):#x}"
            runs.append(f"stub({ret_i},{ret_f:g}): {st}, {ncalls[0]} calls stubbed, writes to f: {len(w)}, f after = {e.rf(FS)}")
            ok &= not w and e.rf(FS) == 0.3125
        print(f"    {fn:#x}: static writes via the r8 pointer: {wr or 'none'}")
        for r_ in runs:
            print(f"        {r_}")
        ok &= not wr
    print("    NOTE: call-stubbed runs cover the functions' OWN code on three stub answers, not their callees and not every")
    print("    path; the static half follows plain mov copies only.  Worst case the cave reads the f the builder re-reads.")
    print(f"  S2b {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# region runner (hook .. first call), stock or patched
# ----------------------------------------------------------------------------------------------
MARK = dict(c1=0.90, c2=0.80, c3=0.70, s1=0.60, s2=0.50, s3=0.40)


def run_region(img, parts=None, *, c=(1.0, 1.0, 1.0), sg=(1.0, 1.0, 1.0), f=0.5, meter=0.0, scratch=0x1111,
               weakfoot=None, start=HOOK):
    e = Emu(img)
    uc = e.uc
    if parts is not None:
        for va, _, b in parts:
            e.overlay(va, b)
        e.overlay(HOOK, hook_bytes(parts[0][0]))
    rsp = STACK_TOP - 0x4000
    rbp = FRAME
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RBP, rbp)
    uc.reg_write(X.UC_X86_REG_RDI, PLAYER)
    uc.reg_write(X.UC_X86_REG_RSI, OUT)
    uc.reg_write(X.UC_X86_REG_RBX, VEC)
    for n in ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11"):
        uc.reg_write(GPR[n], scratch * 0x100010001 & 0xFFFFFFFFFFFFFFFF)
    e.wf(rsp + 0x40, f)
    e.wf(PLAYER + 0x30F4, meter)
    for off, v in ((0x120, 0.51), (0x110, 0.52), (0x100, 0.53), (0x108, 0.54)):
        e.wf(rbp + off, v)
    e.setx(1, c[0]); e.setx(12, c[1]); e.setx(6, c[2])
    e.setx(13, sg[0]); e.setx(10, sg[1]); e.setx(7, sg[2])
    e.setx(8, 1.0); e.setx(15, 0.75); e.setx(9, 0.0)
    for i in (0, 2, 3, 4, 5):
        e.setx_raw(i, (scratch << 96) | (scratch << 64) | (scratch << 32) | (0x7FC00000 + scratch))  # NaN garbage
    if weakfoot is None and parts is not None and len(parts) == 2:
        weakfoot = (5, 1, 1)                 # weak-foot variant: default world = a STRONGER-foot kick
    if weakfoot is not None:
        setup_attr_world(e, *weakfoot)
    before = e.snapshot()
    trace = []
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: trace.append(a))
    uc.emu_start(start, TAIL_CALL, count=2000)
    after = e.snapshot()
    out = {k: e.rf(OUT + o) for k, o in (("h_max", 0), ("h_prob", 4), ("h_sigma", 8), ("v_max", 0x10), ("v_prob", 0x14),
                                         ("v_sigma", 0x18), ("p_max", 0x20), ("p_prob", 0x24), ("p_sigma", 0x28))}
    return out, before, after, trace, e


def site_consts(img):
    """(K, horizontal ceiling, vertical ceiling, power rate) as THIS image's instructions load them, so the
    proofs hold on the stock exe and on one that already carries ceiling/sigma re-aims."""
    out = []
    for va in (HOOK, 0x14401B3DF, 0x14401B423, 0x14401B3D6):
        ins = next(img.md.disasm(img.read(va - img.base, 16), va))
        out.append(struct.unpack("<f", img.read(img.lea_target(ins), 4))[0])
    return tuple(out)


def s3_region(img):
    print("\n== S3  STOCK region 0x14401b3a7..0x14401b4bc with marker registers ==")
    m = MARK
    out, b, a, tr, _ = run_region(img, None, c=(m["c1"], m["c2"], m["c3"]), sg=(m["s1"], m["s2"], m["s3"]))
    K, HC, VC, PC = site_consts(img)
    print(f"  constants this image loads: K={K} @0x14401b3a7, horizontal ceiling={HC} @0x14401b3df, "
          f"vertical ceiling={VC} @0x14401b423, power rate={PC:.4g} @0x14401b3d6")
    exp = dict(h_max=(1 - m["c1"]) * HC, v_max=(1 - m["c2"]) * VC, p_max=(1 - m["c3"]) * PC,
               h_sigma=max(0.1, 0.75 + K * (1 - m["s1"]) ** 2), v_sigma=max(0.1, 0.75 + K * (1 - m["s2"]) ** 2),
               p_sigma=max(0.1, 0.75 + K * (1 - m["s3"]) ** 2), h_prob=0.51, v_prob=0.52, p_prob=0.53)
    src = dict(h_max="(1-xmm1)*Hceil", v_max="(1-xmm12)*Vceil", p_max="(1-xmm6)*Prate", h_sigma="max(.1,.75+K(1-xmm13)^2)",
               v_sigma="max(.1,.75+K(1-xmm10)^2)", p_sigma="max(.1,.75+K(1-xmm7)^2)", h_prob="[rbp+0x120]",
               v_prob="[rbp+0x110]", p_prob="[rbp+0x100]")
    ok = True
    print(f"  inputs: xmm1={m['c1']} xmm12={m['c2']} xmm6={m['c3']} xmm13={m['s1']} xmm10={m['s2']} xmm7={m['s3']}")
    for k in out:
        good = abs(out[k] - exp[k]) < 1e-5
        ok &= good
        print(f"    out.{k:8s} = {out[k]:.6f}   expect {exp[k]:.6f}  = {src[k]:28s} {'OK' if good else 'NO'}")
    # differential scratch test
    o1, _, a1, _, e1 = run_region(img, None, c=(.9, .8, .7), sg=(.6, .5, .4), scratch=0x1111)
    o2, _, a2, _, e2 = run_region(img, None, c=(.9, .8, .7), sg=(.6, .5, .4), scratch=0x2222)
    d = diff(a1, a2)
    mem1 = bytes(e1.uc.mem_read(OUT, 0x40)) + bytes(e1.uc.mem_read(STACK_TOP - 0x4000, 0x100))
    mem2 = bytes(e2.uc.mem_read(OUT, 0x40)) + bytes(e2.uc.mem_read(STACK_TOP - 0x4000, 0x100))
    print(f"  differential: rax/rcx/rdx/r8-r11/xmm0,2,3,4,5 seeded with garbage A vs garbage B at the hook:")
    print(f"    registers that still differ at the call 0x14401b4bc: {sorted(d) or 'none'}")
    print(f"    out struct + stack args identical: {mem1 == mem2}")
    live_leak = [k for k in d if k not in ("xmm2", "xmm5", "r10", "r11")]
    ok &= mem1 == mem2 and not live_leak
    print("    (xmm2/xmm5/r10/r11 are never written in the span, so their garbage survives untouched - they are")
    print("     volatile in the Win64 ABI and the callee 0x144021870 takes (rcx,rdx,r8,r9,[rsp+20],[rsp+28]) only)")
    print(f"  S3 {'PASS' if ok else 'FAIL'}")
    return ok


def callee_scratch_check(img):
    """First use of xmm2/xmm5/rax inside 0x144021870 must be a write (linear sweep of its entry block)."""
    print("  callee 0x144021870 entry: first touch of rax/xmm2/xmm5 (linear sweep until first branch/call):")
    names = {capstone.x86.X86_REG_XMM2: "xmm2", capstone.x86.X86_REG_XMM5: "xmm5",
             capstone.x86.X86_REG_RAX: "rax", capstone.x86.X86_REG_EAX: "rax", capstone.x86.X86_REG_AL: "rax"}
    seen = {}
    for i in img.md.disasm(img.read(0x144021870 - img.base, 0x200), 0x144021870):
        rr, rw = i.regs_access()
        for r in rr:
            if r in names and names[r] not in seen:
                seen[names[r]] = ("READ", hex(i.address), f"{i.mnemonic} {i.op_str}")
        for r in rw:
            if r in names and names[r] not in seen:
                seen[names[r]] = ("write", hex(i.address), f"{i.mnemonic} {i.op_str}")
        if i.mnemonic in ("ret",) or len(seen) == 3:
            break
    for k, v in seen.items():
        print(f"      {k}: {v}")
    return all(v[0] == "write" for v in seen.values())


# ----------------------------------------------------------------------------------------------
# float32 model of the cave arithmetic (op for op), used as the expectation in S4/S5/S7
# ----------------------------------------------------------------------------------------------
def model_S(gain, meter, f, wf_floor=None, weak=False, tiredness="meter"):
    F = np.float32
    with np.errstate(all="ignore"):
        if tiredness == "none":
            e = F(gain)                                          # no meter read: t == 1
        elif wf_floor is None:
            e = F(gain) * (F(meter) * F(0.01))
        else:
            t = F(meter)
            if weak:
                t = t if t > F(wf_floor) else F(wf_floor)        # maxss t,[floor]  (NaN -> floor)
            e = F(gain / 100.0) * t
        S = F(1.0) - e * (F(1.0) - F(f))
        S = S if S < F(1.0) else F(1.0)                          # minss S,1.0   (NaN -> 1.0)
        S = S if S > F(0.0) else F(0.0)                          # maxss S,0.0
    return float(S)


def close(got, exp):
    return abs(got - exp) <= 2e-6 * max(1.0, abs(exp))


PATHOLOGICAL = [("meter=1e9 (corrupt)", 1e9, 0.1), ("meter=+inf", float("inf"), 0.1), ("meter=NaN", float("nan"), 0.1),
                ("meter=-50", -50.0, 0.1), ("f=-10", 100.0, -10.0), ("f=NaN", 100.0, float("nan"))]
# the ability build never reads the meter, so its hostile inputs are all in f (and the meter column is ignored)
PATHOLOGICAL_ABILITY = [("f=-10 (corrupt)", 0.0, -10.0), ("f=NaN", 0.0, float("nan")), ("f=+inf", 0.0, float("inf")),
                        ("f=-inf", 0.0, float("-inf")), ("f=1e30", 0.0, 1e30), ("f=1.05 (ability bonus)", 0.0, 1.05),
                        ("meter=NaN (never read)", float("nan"), 0.1)]


def pathological(tiredness):
    return PATHOLOGICAL_ABILITY if tiredness == "none" else PATHOLOGICAL


# ----------------------------------------------------------------------------------------------
# S4 cave standalone
# ----------------------------------------------------------------------------------------------
def run_cave(img, parts, meter, f, c):
    e = Emu(img)
    for va, _, b in parts:
        e.overlay(va, b)
    uc = e.uc
    rsp = STACK_TOP - 0x4000
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RDI, PLAYER)
    uc.reg_write(X.UC_X86_REG_RSI, OUT)
    uc.reg_write(X.UC_X86_REG_RBP, FRAME)
    uc.reg_write(X.UC_X86_REG_RBX, VEC)
    for i in range(16):
        e.setx(i, 0.001 * (i + 1))
    e.setx(1, c[0]); e.setx(12, c[1]); e.setx(6, c[2]); e.setx(8, 1.0); e.setx(15, 0.75); e.setx(9, 0.0)
    e.wf(rsp + 0x40, f); e.wf(PLAYER + 0x30F4, meter)
    uc.mem_write(PLAYER + 0x2BD8, b"\x7f")           # weak-foot variant: index out of range -> skipped
    stack_before = bytes(uc.mem_read(rsp - 0x100, 0x300))
    player_before = bytes(uc.mem_read(PLAYER, 0x5000))
    writes = []
    uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, ud: writes.append((addr, size)))
    b4 = e.snapshot()
    uc.emu_start(parts[0][0], HOOK_RET, count=200)
    af = e.snapshot()
    clean = (not writes and af["rsp"] == b4["rsp"] and bytes(uc.mem_read(rsp - 0x100, 0x300)) == stack_before
             and bytes(uc.mem_read(PLAYER, 0x5000)) == player_before)
    return b4, af, clean, len(writes)


def s4_cave(img, parts, k, gain, wf, axes, tiredness="meter"):
    print("\n== S4  cave standalone (enter at cave, stop at the return address 0x14401b3af) ==")
    print(f"  cave bytes: " + " | ".join(f"{va:#x}:{len(b)}B" for va, _, b in parts) + f"   axes scaled: {axes}")
    ok = True
    if tiredness == "none":
        # the identity case is no longer "meter 0" but "f >= 1" (the ability-99 player)
        cases = [("f=1.0 clean  (ability 99)", 0.0, 1.0, (1.0, 1.0, 1.0)),
                 ("f=1.0 dirty  (ability 99)", 0.0, 1.0, (0.9, 0.8, 0.7)),
                 ("f=1.5 dirty  (ability+bonus)", 0.0, 1.5, (0.9, 0.8, 0.7)),
                 ("f=0.0 clean  (ability 40)", 0.0, 0.0, (1.0, 1.0, 1.0)),
                 ("f=0.1 clean  (ability 60)", 0.0, 0.1, (1.0, 1.0, 1.0)),
                 ("f=0.5 clean  (ability 75)", 0.0, 0.5, (1.0, 1.0, 1.0)),
                 ("f=0.9 clean  (ability 90)", 0.0, 0.9, (1.0, 1.0, 1.0)),
                 ("f=0.1 dirty  (ability 60)", 0.0, 0.1, (0.9, 0.8, 0.7)),
                 ("f=0.1 meter=100 (unread)", 100.0, 0.1, (1.0, 1.0, 1.0))]
    else:
        cases = [("fresh, standing", 0.0, 0.1, (1.0, 1.0, 1.0)),
                 ("fresh, dirty kick", 0.0, 0.1, (0.9, 0.8, 0.7)),
                 ("meter=100 f=0.1 clean", 100.0, 0.1, (1.0, 1.0, 1.0)),
                 ("meter=100 f=0.7 clean", 100.0, 0.7, (1.0, 1.0, 1.0)),
                 ("meter=50  f=0.1 clean", 50.0, 0.1, (1.0, 1.0, 1.0)),
                 ("meter=100 f=0.1 dirty", 100.0, 0.1, (0.9, 0.8, 0.7)),
                 ("meter=100 f=1.05 (bonus>1)", 100.0, 1.05, (1.0, 1.0, 1.0))]
    cases += [(n, m, f, (0.9, 0.8, 0.7)) for n, m, f in pathological(tiredness)]
    regs = {"h": "xmm1", "v": "xmm12", "p": "xmm6"}
    scaled = {regs[a] for a in axes}
    untouched = set(regs.values()) - scaled
    print(f"    {'case':28s} {'S(model)':>9s} {'xmm1':>9s} {'xmm12':>9s} {'xmm6':>9s} {'xmm3=K':>7s}  other registers changed")

    def one(name, parts_, gain_, meter, f, c):
        b4, af, clean, nw = run_cave(img, parts_, meter, f, c)
        S = model_S(gain_, meter, f, wf_floor=wf, tiredness=tiredness)
        d = diff(b4, af)
        allowed = {"rax", "xmm0", "xmm2", "xmm3", "xmm5", "eflags"} | scaled
        extra = sorted(set(d) - allowed)
        got = {r: i2f(af[r]) for r in regs.values()}
        good = i2f(af["xmm3"]) == k and not extra and clean and 0.0 <= S <= 1.0
        for r, cv in zip(("xmm1", "xmm12", "xmm6"), c):
            if r in scaled:
                good &= close(got[r], float(np.float32(cv) * np.float32(S))) and 0.0 <= got[r] <= float(np.float32(cv))
            else:
                good &= af[r] == b4[r]                      # an unscaled axis must be BIT-identical
        if S == 1.0:
            good &= all(af[r] == b4[r] for r in regs.values())   # BIT-exact (meter build: meter 0; ability build: f >= 1)
        others = sorted(set(d) - set(regs.values()) - {"xmm3"})
        print(f"    {name:28s} {S:9.6f} {got['xmm1']:9.6f} {got['xmm12']:9.6f} {got['xmm6']:9.6f} {i2f(af['xmm3']):7.3f}  "
              f"{others}  mem writes={nw}  {'OK' if good else 'NO'}")
        return good

    for name, meter, f, c in cases:
        ok &= one(name, parts, gain, meter, f, c)
    # a mis-set gain > 1 must floor at S = 0 (c = 0 -> the game's full ceiling, never beyond it)
    big = assemble(cave_source(k, 2.0, wf, axes, tiredness))
    ok &= one("GAIN=2.0 meter=100 f=0", big, 2.0, 100.0, 0.0, (0.9, 0.8, 0.7))
    print(f"    (allowed to change: rax xmm0 xmm2 xmm5 = dead scratch proven in S1/S3; xmm3 = K; {sorted(scaled)} = the scaled c")
    print(f"     values, each checked to stay inside [0, c]; {sorted(untouched) or 'no axis'} must stay BIT-identical)")
    print(f"  S4 {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# S5 patched end-to-end vs stock
# ----------------------------------------------------------------------------------------------
def s5_end_to_end(img, k, gain, wf, axes, tiredness="meter"):
    print("\n== S5  patched path: hook jmp -> cave -> 0x14401b3af -> stock tail, vs stock ==")
    ok = True
    K0, HC, VC, PC = site_consts(img)
    # (a) cave assembled with K = the image's own K: the IDENTITY case must be BIT-identical to unpatched in
    #     every output field.  meter build: meter = 0.  ability build: f >= 1 (the ability-99 player).
    parts425 = assemble(cave_source(K0, gain, wf, axes, tiredness))
    id_cases = [("f=1.0", 0.0, 1.0), ("f=1.5", 0.0, 1.5)] if tiredness == "none" else [("meter=0", 0.0, 0.1)]
    for lbl, m_id, f_id in id_cases:
        for c, sg in (((1.0, 1.0, 1.0), (1.0, 1.0, 1.0)), ((0.9, 0.8, 0.7), (0.6, 0.5, 0.4))):
            o_s, _, a_s, _, e_s = run_region(img, None, c=c, sg=sg, f=f_id, meter=m_id)
            o_p, _, a_p, tr, e_p = run_region(img, parts425, c=c, sg=sg, f=f_id, meter=m_id)
            same_out = bytes(e_s.uc.mem_read(OUT, 0x40)) == bytes(e_p.uc.mem_read(OUT, 0x40))
            d = sorted(diff(a_s, a_p, ignore=("xmm2", "xmm5", "eflags")))
            went = all(any(va <= t < va + n for t in tr) for va, n, _ in parts425)
            print(f"    K={K0} {lbl} c={c}: out struct bit-identical to stock: {same_out}; live-register diffs: {d or 'none'}; cave executed: {went}")
            ok &= same_out and not d and went
    # (b) default tunables
    parts = assemble(cave_source(k, gain, wf, axes, tiredness))
    print(f"    tunables K={k} gain={gain} axes={axes}   (this image's ceilings: H {HC:g} deg, V {VC:g} deg, power {PC:.3g})")
    print(f"    {'case':36s} {'h_max deg':>10s} {'v_max deg':>10s} {'p_max':>8s} {'h_sigma':>8s} {'v_sigma':>8s} {'p_sigma':>8s}")
    if tiredness == "none":
        rows = [("STOCK   clean", None, 0.0, 0.1, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean f=0.0  (ability 40)", parts, 0.0, 0.0, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean f=0.1  (ability 60)", parts, 0.0, 0.1, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean f=0.5  (ability 75)", parts, 0.0, 0.5, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean f=0.9  (ability 90)", parts, 0.0, 0.9, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean f=1.0  (ability 99)", parts, 0.0, 1.0, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean f=0.1 meter=100", parts, 100.0, 0.1, (1, 1, 1), (1, 1, 1)),
                ("STOCK   dirty c=.9/.8/.7 s=.6/.5/.4", None, 0.0, 0.1, (.9, .8, .7), (.6, .5, .4)),
                ("PATCHED dirty f=1.0", parts, 0.0, 1.0, (.9, .8, .7), (.6, .5, .4)),
                ("PATCHED dirty f=0.1", parts, 0.0, 0.1, (.9, .8, .7), (.6, .5, .4))]
    else:
        rows = [("STOCK   clean", None, 0.0, 0.1, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean meter=0   f=0.1", parts, 0.0, 0.1, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean meter=100 f=0.1", parts, 100.0, 0.1, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean meter=100 f=0.5", parts, 100.0, 0.5, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean meter=100 f=0.7", parts, 100.0, 0.7, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean meter=100 f=0.95", parts, 100.0, 0.95, (1, 1, 1), (1, 1, 1)),
                ("PATCHED clean meter=50  f=0.7", parts, 50.0, 0.7, (1, 1, 1), (1, 1, 1)),
                ("STOCK   dirty c=.9/.8/.7 s=.6/.5/.4", None, 0.0, 0.1, (.9, .8, .7), (.6, .5, .4)),
                ("PATCHED dirty meter=0   f=0.1", parts, 0.0, 0.1, (.9, .8, .7), (.6, .5, .4)),
                ("PATCHED dirty meter=100 f=0.1", parts, 100.0, 0.1, (.9, .8, .7), (.6, .5, .4))]
    for name, p, meter, f, c, sg in rows:
        o, _, _, _, _ = run_region(img, p, c=c, sg=sg, f=f, meter=meter)
        S = model_S(gain, meter, f, wf_floor=wf, tiredness=tiredness) if p else 1.0
        Sa = {a: (S if a in axes else 1.0) for a in "hvp"}
        kk = k if p else K0
        exp = ((1 - c[0] * Sa["h"]) * HC, (1 - c[1] * Sa["v"]) * VC, (1 - c[2] * Sa["p"]) * PC,
               max(.1, .75 + kk * (1 - sg[0]) ** 2), max(.1, .75 + kk * (1 - sg[1]) ** 2), max(.1, .75 + kk * (1 - sg[2]) ** 2))
        got = (o["h_max"], o["v_max"], o["p_max"], o["h_sigma"], o["v_sigma"], o["p_sigma"])
        good = all(abs(g - x) < 1e-4 for g, x in zip(got, exp)) and abs(o["h_prob"] - .51) < 1e-6 \
            and abs(o["v_prob"] - .52) < 1e-6 and abs(o["p_prob"] - .53) < 1e-6
        ok &= good
        print(f"    {name:36s} {got[0]:10.4f} {got[1]:10.4f} {got[2]:8.4f} {got[3]:8.4f} {got[4]:8.4f} {got[5]:8.4f}  {'OK' if good else 'NO'}")
    # (c) hostile inputs: every ceiling must stay finite and inside [the unpatched value, the game's full ceiling]
    print("    hostile inputs through the whole patched path (dirty kick c=.9/.8/.7) - ceilings must stay bounded:")
    o0, _, _, _, _ = run_region(img, None, c=(.9, .8, .7), sg=(.6, .5, .4), f=0.1, meter=0.0)
    for name, meter, f in pathological(tiredness):
        o, _, _, _, _ = run_region(img, parts, c=(.9, .8, .7), sg=(.6, .5, .4), f=f, meter=meter)
        good = all(np.isfinite(o[key]) and o0[key] - 1e-5 <= o[key] <= full + 1e-5
                   for key, full in (("h_max", HC), ("v_max", VC), ("p_max", PC)))
        ok &= good
        print(f"      {name:22s} h_max {o['h_max']:8.4f}  v_max {o['v_max']:8.4f}  p_max {o['p_max']:7.4f}   "
              f"(unpatched {o0['h_max']:.3f}/{o0['v_max']:.3f}/{o0['p_max']:.3f}, full {HC:g}/{VC:g}/{PC:.3g})  {'OK' if good else 'NO'}")
    print(f"  S5 {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# S6 meter clamp + f range (game code)
# ----------------------------------------------------------------------------------------------
def s6_ranges(img):
    print("\n== S6  ranges, from the game's own code ==")
    ok = True
    # meter increase: 0x143eb86ea call fps ; 40/fps*xmm7 + meter ; minss 100 ; store   (stop at 0x143eb8717)
    # meter decrease: 0x143eb8773 .. 0x143eb87a7 (200/fps*xmm8, maxss xmm7(=0))
    for label, start, stop, meter, x7, x8 in (("rise  from 99.9", 0x143EB86EA, 0x143EB8717, 99.9, 1.0, 0.0),
                                                ("rise  from 10.0", 0x143EB86EA, 0x143EB8717, 10.0, 1.0, 0.0),
                                                ("decay from 0.5 ", 0x143EB8773, 0x143EB87A7, 0.5, 0.0, 1.0),
                                                ("decay from 80  ", 0x143EB8773, 0x143EB87A7, 80.0, 0.0, 1.0)):
        e = Emu(img)
        uc = e.uc
        uc.reg_write(X.UC_X86_REG_RSP, STACK_TOP - 0x4000)
        uc.reg_write(X.UC_X86_REG_RDI, PLAYER)
        e.wf(PLAYER + 0x30F4, meter)
        e.setx(7, x7); e.setx(8, x8)

        def code(u, addr, size, ud):
            b = bytes(u.mem_read(addr, 1))
            if b[0] == 0xE8:                              # 0x14533ea80 = frame rate
                u.reg_write(XMM[0], f2i(60.0))
                u.reg_write(X.UC_X86_REG_RIP, addr + size)
        uc.hook_add(UC_HOOK_CODE, code)
        uc.emu_start(start, stop, count=100)
        v = e.rf(PLAYER + 0x30F4)
        print(f"    meter {label} @60fps one frame -> {v:.4f}")
        ok &= 0.0 <= v <= 100.0
    # f range: real 0x143ed71d0 with the inner ability selector stubbed to a chosen integer
    print("    ability -> f  (real 0x143ed71d0, inner 0x143ed7440 stubbed to return the ability):")
    line = []
    for ab in (30, 40, 50, 60, 75, 90, 99, 105, 111):
        e = Emu(img, permissive=True)
        uc = e.uc
        e.overlay(F_ABILITY_INNER, b"\xb8" + struct.pack("<I", ab) + b"\xc3")
        e.overlay(COOKIE_CHECK, b"\xc3")
        rsp = STACK_TOP - 0x4000
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, PLAYER)
        uc.reg_write(X.UC_X86_REG_RDX, 1)
        try:
            uc.emu_start(F_ABILITY, RET_MAGIC, count=5000)
            line.append(f"{ab}->{e.getx(0):.4f}")
        except UcError as ex:
            line.append(f"{ab}->emu error {ex}")
    print("      " + "  ".join(line))
    print("    => f may exceed 1.0 when bonuses push the effective ability past 99; the cave clamps S <= 1.")
    print(f"  S6 {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# S7 weak foot: inline read == game's ATTR_get
# ----------------------------------------------------------------------------------------------
WORLD = ARENA + 0x80000
PDATA = ARENA + 0x90000


def setup_attr_world(e: Emu, idx: int, stronger_attr: int, kicking_foot: int):
    uc = e.uc
    e.overlay(G_MATCH, struct.pack("<Q", WORLD))
    uc.mem_write(WORLD + idx * 0x58 + 0x55A8, struct.pack("<Q", PDATA + idx * 0x1000))
    uc.mem_write(PDATA + idx * 0x1000 + 0x394 + 0x35, bytes([stronger_attr]))
    uc.mem_write(PLAYER + 0x2BD8, bytes([idx]))
    uc.mem_write(PLAYER + 0x2BF6, bytes([kicking_foot]))
    uc.mem_write(PLAYER + 0x47C0, struct.pack("<Q", WORLD))


def s7_weakfoot(img, k, gain, wf, axes):
    print("\n== S7  weak foot ==")
    ok = True
    print("    game's ATTR_get 0x143ea8cb0(player, 0x35) under emulation vs the byte the cave reads:")
    for idx, attr in ((0, 0), (3, 1), (30, 0), (30, 1)):
        e = Emu(img)
        setup_attr_world(e, idx, attr, 0)
        uc = e.uc
        rsp = STACK_TOP - 0x4000
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, PLAYER)
        uc.reg_write(X.UC_X86_REG_RDX, 0x35)
        uc.emu_start(ATTR_GET, RET_MAGIC, count=500)
        got = uc.reg_read(X.UC_X86_REG_RAX) & 0xFF
        print(f"      idx={idx:2d} planted byte={attr} -> game returns {got}  {'OK' if got == attr else 'NO'}")
        ok &= got == attr
    # the game's own weak-foot decision: 0x143ed787a (ATTR_get 0x35 ; sete ; cmp [player+0x2bf6] ; jne skip)
    print("    game's weak-foot branch 0x143ed787a..0x143ed7899 under emulation (falls to 0x143ed789f = weak-foot penalty):")
    game_rule = {}
    for attr in (0, 1, 2):
        for foot in (0, 1):
            e = Emu(img)
            setup_attr_world(e, 5, attr, foot)
            uc = e.uc
            uc.reg_write(X.UC_X86_REG_RSP, STACK_TOP - 0x4000)
            uc.reg_write(X.UC_X86_REG_RDI, PLAYER)
            seen = []
            uc.hook_add(UC_HOOK_CODE, lambda u, a_, s_, d_, seen=seen: (seen.append(a_), u.emu_stop())
                        if a_ in (0x143ED789F, 0x143ED7A7B) else None)
            uc.emu_start(0x143ED787A, 0, count=500)
            game_rule[(attr, foot)] = seen[-1] == 0x143ED789F
            print(f"      attr35={attr} kickfoot={foot} -> game says weak-foot kick: {game_rule[(attr, foot)]}")
    if wf is None:
        print("    (cave built WITHOUT the weak-foot block; pass --wf 50 to build/prove the weak-foot variant)")
        return ok
    parts = assemble(cave_source(k, gain, wf, axes))
    print(f"    weak-foot cave, WF floor={wf}: game rule (0x143ed7887): weak  <=>  (attr35==0) == [player+0x2bf6]")
    print(f"    {'attr35':>6s} {'kickfoot':>8s} {'game:weak?':>10s} {'meter':>6s} {'v_max deg':>10s} {'expected':>10s}")
    for attr, foot, meter in ((0, 1, 0.0), (0, 0, 0.0), (1, 0, 0.0), (1, 1, 0.0), (2, 0, 0.0), (2, 1, 0.0),
                              (0, 1, 100.0), (1, 1, 100.0), (0, 1, 30.0)):
        weak = game_rule[(attr, foot)]          # the GAME's decision (emulated above) is the oracle
        o, _, _, _, _ = run_region(img, parts, f=0.1, meter=meter, weakfoot=(5, attr, foot))
        exp = (1 - model_S(gain, meter, 0.1, wf_floor=wf, weak=weak)) * site_consts(img)[2]
        good = abs(o["v_max"] - exp) < 1e-4 and (("h" in axes) or o["h_max"] == 0.0)
        ok &= good
        print(f"    {attr:6d} {foot:8d} {str(weak):>10s} {meter:6.0f} {o['v_max']:10.4f} {exp:10.4f}  {'OK' if good else 'NO'}")
    print(f"  S7 {'PASS' if ok else 'FAIL'}")
    return ok


def s8_stamina_lead(img):
    """The ModelStaminaGauge lead: what does 0x145614eb0(uiData, out, playerIdx) really return?"""
    print("\n== S8  stamina lead 0x145614eb0(uiData, out, idx) ==")
    UI = ARENA + 0x60000
    OUTV = ARENA + 0x70000
    ok = True
    for idx in (0, 7, 21, 22):
        e = Emu(img)
        uc = e.uc
        for k in range(0x40):
            uc.mem_write(UI + (k + 0xC2) * 12, struct.pack("<fff", 1000.0 + k, 2000.0 + k, 3000.0 + k))
        rsp = STACK_TOP - 0x4000
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        for r, v in (("rsp", rsp), ("rcx", UI), ("rdx", OUTV), ("r8", idx)):
            uc.reg_write(GPR[r], v)
        uc.emu_start(0x145614EB0, RET_MAGIC, count=200)
        v = struct.unpack("<fff", bytes(uc.mem_read(OUTV, 12)))
        exp = (1000.0 + idx, 2000.0 + idx + 0.3, 3000.0 + idx) if idx < 0x16 else (0.0, 0.3, 0.0)
        good = all(abs(x - y) < 1e-3 for x, y in zip(v, exp))
        ok &= good
        print(f"    idx={idx:2d}: out = ({v[0]:.1f}, {v[1]:.1f}, {v[2]:.1f})   = uiData[(idx+0xc2)*12] vec3 with +0.3 on [1]  {'OK' if good else 'NO'}")
    print("    => a 12-byte vector per player (22 slots) with a fixed +0.3 lift: the gauge's WORLD ANCHOR, not stamina.")
    print("       The displayed value is the BYTE uiData[slot*0x1c + 0x14c] / 100 (method [20] 0x14561a260, divss 100f")
    print("       at 0x14561a30c) - a UI-side copy; its match-side source was NOT located, so no stamina term is used.")
    print(f"  S8 {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# S9 what the STOCK game already does with the meter (so the cave is not sold as something it is not)
# ----------------------------------------------------------------------------------------------
METER_OFF = 0x30F4
FACTOR_FUNCS = {0x144020D00: "prob arrays [rbp+0x100..0x120]", 0x14401EB40: "c/sigma array A [rbp-0x18]",
                0x14401BDB0: "c/sigma array B [rbp-0x30]", 0x14401CA10: "c/sigma array C [rbp-0x48]",
                0x14401F770: "c/sigma array D [rbp-0x70]"}
METER_FRAG = (0x14401C12C, 0x14401C216)     # inside 0x14401bdb0: the only meter read in any factor function
SPEED_FLOOR_SITE = 0x14401BFA2              # movss xmm6,[11f]


def runtime_functions(img):
    """The PE exception directory, sorted by begin RVA (read-only)."""
    with open(img.path, "rb") as fh:
        hdr = fh.read(0x1000)
    pe = struct.unpack_from("<I", hdr, 0x3C)[0]
    rva, size = struct.unpack_from("<II", hdr, pe + 24 + 112 + 8 * 3)
    arr = np.frombuffer(img.read(rva, size - size % 12), dtype="<u4").reshape(-1, 3)
    return arr[np.argsort(arr[:, 0], kind="stable")]


def func_of(rf, img, va):
    i = int(np.searchsorted(rf[:, 0], va - img.base, side="right")) - 1
    if i >= 0 and rf[i, 0] <= va - img.base < rf[i, 1]:
        return img.base + int(rf[i, 0]), img.base + int(rf[i, 1])
    return None, None


def xcode(img):
    nm, rva, vs, _, _ = next(s for s in img.secs if s[0] == ".xcode")
    return rva, img.read(rva, vs)


def meter_refs(img):
    """Every instruction in .xcode with a memory operand [reg+0x30f4]; returns (va, text, 'read'|'write'|'rw')."""
    rva, data = xcode(img)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    out, pos, pat = [], 0, struct.pack("<I", METER_OFF)
    while True:
        pos = data.find(pat, pos)
        if pos < 0:
            break
        for back in range(9, 1, -1):                      # longest decode first (mandatory f3/66 prefixes)
            ins = next(md.disasm(data[pos - back:pos - back + 16], img.base + rva + pos - back), None)
            if ins is not None and ins.disp_offset == back and ins.disp == METER_OFF and ins.size >= back + 4:
                mem = next((o for o in ins.operands if o.type == capstone.x86.X86_OP_MEM), None)
                acc = mem.access if mem is not None else 0
                kind = {capstone.CS_AC_READ: "read", capstone.CS_AC_WRITE: "write"}.get(acc, "rw")
                out.append((ins.address, f"{ins.mnemonic} {ins.op_str}", kind))
                break
        pos += 1
    return out


def branch_xrefs(img, targets):
    """rel32 call/jmp sites in .xcode whose target is in `targets`."""
    rva, data = xcode(img)
    d = np.frombuffer(data, dtype=np.uint8)
    res = {t: [] for t in targets}
    for opc in (0xE8, 0xE9):
        pos = np.flatnonzero(d[:-5] == opc).astype(np.int64)
        rel = (d[pos + 1].astype(np.int64) | (d[pos + 2].astype(np.int64) << 8) | (d[pos + 3].astype(np.int64) << 16)
               | (d[pos + 4].astype(np.int64) << 24))
        rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
        tgt = img.base + rva + pos + 5 + rel
        for t in targets:
            res[t] += [int(x) + img.base + rva for x in pos[tgt == t]]
    return res


def stock_meter_mult(img, meter, f, speed, kang=0.0):
    """Run the game's fragment 0x14401c12c..0x14401c216 (factor fn 0x14401bdb0) on a 6-slot array of 1.0s."""
    e = Emu(img)
    uc = e.uc
    ARR, FS = VEC, VEC + 0x100
    for k in range(6):
        e.wf(ARR + 4 * k, 1.0)
    e.wf(FS, f)
    e.wf(PLAYER + METER_OFF, meter)
    ins = next(img.md.disasm(img.read(SPEED_FLOOR_SITE - img.base, 16), SPEED_FLOOR_SITE))
    floor = struct.unpack("<f", img.read(img.lea_target(ins), 4))[0]
    for r, v in (("rsp", STACK_TOP - 0x4000), ("rbx", ARR), ("rdi", PLAYER), ("r14", FS)):
        uc.reg_write(GPR[r], v)
    e.setx(9, speed); e.setx(6, floor); e.setx(1, kang); e.setx(11, 100.0); e.setx(8, 1.0)
    uc.emu_start(METER_FRAG[0], METER_FRAG[1], count=200)
    return [e.rf(ARR + 4 * k) for k in range(6)], floor


def s9_stock_meter(img, live, k, gain, wf, axes, tiredness="meter"):
    print("\n== S9  what the STOCK game already does with the meter [player+0x30f4] ==")
    ok = True
    rf = runtime_functions(img)
    refs = meter_refs(img)
    print("    every [reg+0x30f4] access in .xcode, by containing function (exception directory):")
    readers_in_factor, kick_readers = [], []
    for va, text, kind in refs:
        fs, fe = func_of(rf, img, va)
        tag = ""
        if fs in FACTOR_FUNCS:
            tag = f"  <- FACTOR FUNCTION ({FACTOR_FUNCS[fs]})"
            if kind != "write":
                readers_in_factor.append(va)
        if fs is not None and 0x144019000 <= fs < 0x144022000 and kind != "write":
            kick_readers.append((va, fs))
        if fs is not None and (0x143EA0000 <= fs < 0x143EC0000 or 0x144019000 <= fs < 0x144022000):
            print(f"      {va:#x}  {kind:5s} {text:48s} in {fs:#x}{tag}")
    other = [va for va, _, _ in refs if not (0x143EA0000 <= va < 0x143EC0000 or 0x144019000 <= va < 0x144022000)]
    print(f"      ({len(other)} further byte-pattern hits outside the player/kick code - other classes or non-code bytes: "
          f"{[hex(v) for v in other]})")
    print(f"    meter READS inside the five factor functions: {[hex(v) for v in readers_in_factor]}")
    good = readers_in_factor == [0x14401C143]
    ok &= good
    print(f"      -> exactly one, 0x14401c143 in 0x14401bdb0   {'OK' if good else 'NO'}")
    others = sorted({fs for va, fs in kick_readers if fs not in FACTOR_FUNCS})
    xr = branch_xrefs(img, others + [0x14401E5B0])
    for fs in others + [0x14401E5B0]:
        sites = xr[fs]
        print(f"    callers of {fs:#x}: " + ", ".join(f"{s_:#x} (in {func_of(rf, img, s_)[0] or 0:#x})" for s_ in sites))
    post = all(all((func_of(rf, img, s_)[0] == BUILDER and s_ > HOOK) or func_of(rf, img, s_)[0] == 0x14401E5B0
                   for s_ in xr[fs]) and xr[fs] for fs in others + [0x14401E5B0])
    ok &= post
    print(f"      -> the other kick-code readers sit in the mishit-TYPE probability functions, reached only from the builder")
    print(f"         AFTER the hook (0x14401b5d5 / 0x14401b5f3): they do not feed c1/c2/c3.   {'OK' if post else 'NO'}")

    def table(im, label):
        nonlocal ok
        K0, HC, VC, PC = site_consts(im)
        print(f"    {label}: game fragment 0x14401c12c..0x14401c216 emulated, 6-slot array of 1.0, speed 25 km/h, angle term 0")
        print(f"      {'f':>5s} {'meter':>6s} {'slot0 (horizontal c)':>21s} {'slots1-5':>9s} {'stock H ceiling':>16s}"
              + (f" {'with cave':>10s}" if "h" in axes else ""))
        for f in (0.1, 0.5, 0.7, 0.9):
            for meter in (0.0, 50.0, 80.0, 100.0):
                slots, floor = stock_meter_mult(im, meter, f, 25.0)
                rest = all(struct.pack("<f", v) == struct.pack("<f", 1.0) for v in slots[1:])
                good_ = rest and (slots[0] == 1.0 if meter == 0.0 else True) and (slots[0] < 1.0 if meter == 100.0 else True)
                ok &= good_
                S = model_S(gain, meter, f, wf_floor=wf, tiredness=tiredness)
                extra = f" {(1 - slots[0] * S) * HC:9.3f}d" if "h" in axes else ""
                print(f"      {f:5.2f} {meter:6.0f} {slots[0]:21.4f} {'1.0 x5' if rest else 'CHANGED':>9s} {(1 - slots[0]) * HC:15.3f}d{extra}"
                      f"  {'OK' if good_ else 'NO'}")
        slots, floor = stock_meter_mult(im, 100.0, 0.1, 5.0)
        print(f"      speed 5 km/h (< the {floor:g} km/h floor) meter 100 f 0.1: slot0 = {slots[0]:.4f}  (the stock term is off below the floor)")
        ok &= slots[0] == 1.0

    # side fact (verifier finding): 'ordinary play has c == 1.0' is NOT true for the horizontal axis.  0x14401bdb0 scales
    # slot0 by a kick-CLASS constant before anything else; the class is a table byte returned by the real 0x143eda730.
    hist = {}
    for kid in range(1, 0xB1):
        e = Emu(img)
        uc = e.uc
        rsp = STACK_TOP - 0x4000
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.mem_write(VEC, struct.pack("<i", kid))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, VEC)
        uc.emu_start(0x143EDA730, RET_MAGIC, count=60)
        cl = struct.unpack("<b", struct.pack("<B", uc.reg_read(X.UC_X86_REG_RAX) & 0xFF))[0]
        hist[cl] = hist.get(cl, 0) + 1
    base = {}
    for cl in sorted(hist):
        e = Emu(img)
        uc = e.uc
        e.wf(VEC, 1.0)
        uc.reg_write(X.UC_X86_REG_RSP, STACK_TOP - 0x4000)
        uc.reg_write(X.UC_X86_REG_RBX, VEC)
        uc.reg_write(X.UC_X86_REG_RAX, cl & 0xFFFFFFFF)
        uc.emu_start(0x14401BE1E, 0x14401BE65, count=40)
        base[cl] = e.rf(VEC)
    print(f"    kick-class histogram over kick ids 1..0xb0 (real 0x143eda730): {dict(sorted(hist.items()))}")
    print(f"    unconditional horizontal base multiplier per class (game code 0x14401be1e..0x14401be65): "
          + ", ".join(f"class {c_}: x{v:.2f}" for c_, v in base.items()))
    print("      -> for classes 0-3 the horizontal c is at most 0.86-0.90 even for a standing, fresh player, i.e. a 2.25-3.15 deg")
    print("         horizontal ceiling on the stock game.  'A clean kick has zero error' is false for the horizontal axis (the other")
    print("         axes were not audited for such base terms; the cave is an exact identity at meter 0 whatever the c values are).")
    table(img, "PRISTINE")
    if live is not None and site_consts(live) != site_consts(img) or (live is not None and
            live.read(0x14401C15A - live.base, 8) != img.read(0x14401C15A - img.base, 8)):
        table(live, "LIVE exe (carries technique-realism / scuff-wobble re-aims)")
    print("    => a full meter ALREADY costs horizontal accuracy in the stock game (fold(x,1,1,1) = x: S2), and the stock game")
    print("       has NO meter term on the vertical (slot1) or power (slot2) c.  The cave's honest contribution is those two axes;")
    print(f"       with --axes {axes}: horizontal is {'ALSO scaled (stacks on the stock term)' if 'h' in axes else 'left entirely to the game'}.")
    if tiredness == "none":
        print("    FOR THE ABILITY BUILD: the cave reads NO meter, so it computes a different quantity from the stock 0x14401c143")
        print("    term - no double-counting of the same input.  The two horizontal reductions still COMPOSE multiplicatively")
        print("    while the player is sprinting: c1_final = c1_stock(meter) * S(ability).  At meter 0 (standing / walking /")
        print("    jogging below the gate) the stock term is exactly 1.0 (rows above), so the cave is the ONLY horizontal")
        print("    ability term on the unpressured kick the owner is asking about.")
    print(f"  S9 {'PASS' if ok else 'FAIL'}")
    return ok


# ----------------------------------------------------------------------------------------------
# S10 what the meter IS (the game's own updater, emulated): sprint exertion, not tiredness
# ----------------------------------------------------------------------------------------------
PRED_RISE = 0x144311BF0            # action-id flag table 0x146c14e80 bit 3
PRED_KICK = 0x144311E40            # same table, bit 16
METER_BODY = (0x143EB85D9, 0x143EB87AC)
FPS_FLOAT, FPS_INT, ACT_COUNTER = 0x14533EA80, 0x14533EB20, 0x143EA9040


def action_pred(img, fn, aid):
    e = Emu(img)
    uc = e.uc
    rsp = STACK_TOP - 0x4000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, aid)
    uc.emu_start(fn, RET_MAGIC, count=50)
    return bool(uc.reg_read(X.UC_X86_REG_RAX) & 0xFF)


def meter_sim(img, action, speed, sprint, meter0, frames, part=0, counter=0, every=6):
    """The game's updater body 0x143eb85d9..0x143eb87ac at 60 fps; predicates REAL, frame-rate/counter calls stubbed."""
    e = Emu(img)
    uc = e.uc
    ARG2 = VEC + 0x1000
    e.wf(ARG2 + 0x570, 1.0 if sprint else 0.0)
    uc.mem_write(PLAYER + 0xAD0, bytes([action]))
    uc.mem_write(PLAYER + 0x2BDC, bytes([part]))
    e.wf(PLAYER + 0xB38, speed)
    e.wf(PLAYER + METER_OFF, meter0)

    def code(u, addr, size, ud):
        if size == 5 and bytes(u.mem_read(addr, 1)) == b"\xe8":
            tgt = addr + 5 + struct.unpack("<i", bytes(u.mem_read(addr + 1, 4)))[0]
            if tgt == FPS_FLOAT:
                u.reg_write(XMM[0], f2i(60.0))
            elif tgt == FPS_INT:
                u.reg_write(X.UC_X86_REG_RAX, 60)
            elif tgt == ACT_COUNTER:
                u.reg_write(X.UC_X86_REG_RAX, counter)
            else:
                return                                   # the two action-id predicates run for real
            u.reg_write(X.UC_X86_REG_RIP, addr + 5)
    uc.hook_add(UC_HOOK_CODE, code, begin=METER_BODY[0], end=METER_BODY[1])
    seq = [meter0]
    for n in range(1, frames + 1):
        uc.reg_write(X.UC_X86_REG_RSP, STACK_TOP - 0x4000)
        uc.reg_write(X.UC_X86_REG_RDI, PLAYER)
        uc.reg_write(X.UC_X86_REG_RBX, ARG2)
        uc.emu_start(METER_BODY[0], METER_BODY[1], count=400)
        if n % every == 0:
            seq.append(e.rf(PLAYER + METER_OFF))
    return seq


def s10_meter_nature(img, live):
    print("\n== S10  what the meter IS: the game's own updater 0x143eb84c0 (body 0x143eb85d9..0x143eb87ac), 60 fps ==")
    ok = True
    rise_ids = [a for a in range(0x71) if action_pred(img, PRED_RISE, a)]
    kick_ids = [a for a in range(0x71) if action_pred(img, PRED_KICK, a)]
    print(f"    action ids for which the RISE predicate 0x144311bf0 is true: {[hex(a) for a in rise_ids]}")
    print(f"    action ids for which the KICK predicate 0x144311e40 is true: {[hex(a) for a in kick_ids]}")
    print("    (0xa is the shot id the builder itself tests at 0x14401b32f; the NAMES of ids 4/5/6 are NOT proven -")
    print("     they share flag bit 14 with 7 and 0xb..0xe and are very probably the on-ball dribble states)")

    def show(im, label, rows):
        nonlocal ok
        print(f"    {label}: meter every 0.1 s")
        for name, kw in rows:
            seq = meter_sim(im, **kw)
            ok &= all(0.0 <= v <= 100.0 for v in seq)
            print(f"      {name:58s} " + " ".join(f"{v:5.1f}" for v in seq))
        return

    rows = [("action 4, 30 km/h, sprint flag: RISE (40/s)", dict(action=4, speed=30.0, sprint=1, meter0=0.0, frames=60)),
            ("action 4, 18.5 km/h, sprint flag: slow rise, never decays", dict(action=4, speed=18.5, sprint=1, meter0=50.0, frames=60)),
            ("action 4, 10 km/h from 100: EMPTY in 0.5 s", dict(action=4, speed=10.0, sprint=1, meter0=100.0, frames=60)),
            ("action 8 (kick) from 100, body part != 0x10: frozen", dict(action=8, speed=0.0, sprint=0, meter0=100.0, frames=30)),
            ("action 8 (kick) from 100, part 0x10 + counter 60: -500/s", dict(action=8, speed=0.0, sprint=0, meter0=100.0, frames=30, part=0x10, counter=60))]
    show(img, "PRISTINE", rows)
    for a in (0, 1, 2, 3, 7, 0xB, 0xC):
        seq = meter_sim(img, action=a, speed=30.0, sprint=1, meter0=0.0, frames=60)
        good = max(seq) == 0.0
        ok &= good or a in rise_ids
        print(f"      action {a:#x} at 30 km/h for 1 s with the sprint flag: max meter {max(seq):.1f}   {'OK (never rises)' if good else 'rises'}")
    seq = meter_sim(img, action=4, speed=30.0, sprint=1, meter0=0.0, frames=60)
    ok &= seq[-1] > 30.0
    if live is not None and live.read(0x143EB867D - live.base, 8) != img.read(0x143EB867D - img.base, 8):
        show(live, "LIVE exe (technique-realism re-aims the 17.5 km/h gate at 0x143eb867d)",
             [("action 4, 14 km/h jog, sprint flag (pristine: stays 0)", dict(action=4, speed=14.0, sprint=1, meter0=0.0, frames=60)),
              ("action 4, 10 km/h from 100", dict(action=4, speed=10.0, sprint=1, meter0=100.0, frames=60))])
        seq = meter_sim(img, action=4, speed=14.0, sprint=1, meter0=0.0, frames=60)
        print(f"      (same 14 km/h jog on PRISTINE: max meter {max(seq):.1f})")
    print("    => the meter is SHORT-TERM SPRINT EXERTION: it needs a rise-predicate action id and speed above the gate, fills")
    print("       in 2.5 s, is gone 0.5 s after slowing down, and carries nothing from minute 1 to minute 90.  It is NOT tiredness.")
    print(f"  S10 {'PASS' if ok else 'FAIL'}")
    return ok


# ==============================================================================================
# ABILITY-BASELINE build only: S11 / S12 / S13
# ==============================================================================================
ABILITIES = (40, 60, 75, 90, 99)


def ability_f(img, ab: int) -> float:
    """The game's own ability -> f map: real 0x143ed71d0 with the inner ability selector stubbed to `ab`."""
    e = Emu(img, permissive=True)
    uc = e.uc
    e.overlay(F_ABILITY_INNER, b"\xb8" + struct.pack("<I", ab) + b"\xc3")
    e.overlay(COOKIE_CHECK, b"\xc3")
    rsp = STACK_TOP - 0x4000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, PLAYER)
    uc.reg_write(X.UC_X86_REG_RDX, 1)
    uc.emu_start(F_ABILITY, RET_MAGIC, count=5000)
    return e.getx(0)


def s11_no_stock_ability_baseline(img):
    """Does the STOCK game already reduce any cleanliness factor because the player is bad, with no difficulty?

    Each of the five factor functions is run on an all-1.0 six-slot array with a zeroed player/context and its
    own CALLs stubbed (three different stub answers, so different branches are taken); only f is varied.  Any
    change in the output array is an ability term.  The answer decides whether the cave double-counts.
    """
    print("\n== S11  is there a STOCK ability baseline on the cleanliness factors? (game code, f swept) ==")
    ok = True
    FS_OFF = 0x10
    CTX, OA = ARENA + 0x50000, ARENA + 0x52000

    def run_factor(fn, f, ret_i, ret_f):
        e = Emu(img, permissive=True)
        uc = e.uc
        rsp = STACK_TOP - 0x8000
        FS = CTX + FS_OFF
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.mem_write(rsp + 0x28, struct.pack("<QQ", OA + 0x100, OA + 0x200))
        for kk in range(6):
            e.wf(OA + 4 * kk, 1.0)
        e.wf(FS, f)
        uc.mem_write(PLAYER, b"\x00" * 0x5000)                 # zero world: no speed, no meter, no flags
        for r, v in (("rsp", rsp), ("rcx", PLAYER), ("rdx", CTX), ("r8", FS), ("r9", OA)):
            uc.reg_write(GPR[r], v)

        def code(u, addr, size, ud):
            b = bytes(u.mem_read(addr, size))
            if b[0] == 0xE8 or (b[0] == 0xFF and (b[1] >> 3) & 7 == 2) or \
               (len(b) > 2 and b[0] in (0x41, 0x48) and b[1] == 0xFF and (b[2] >> 3) & 7 == 2):
                u.reg_write(X.UC_X86_REG_RAX, ret_i)
                u.reg_write(XMM[0], f2i(ret_f))
                u.reg_write(X.UC_X86_REG_RIP, addr + size)
        uc.hook_add(UC_HOOK_CODE, code, begin=fn, end=FACTOR_END[fn])
        try:
            uc.emu_start(fn, RET_MAGIC, count=300000)
            st = "ok" if uc.reg_read(X.UC_X86_REG_RIP) == RET_MAGIC else "stopped"
        except UcError:
            st = "fault"
        return st, tuple(e.rf(OA + 4 * kk) for kk in range(6))

    fs = [0.0, 0.1, 0.5, 0.9, 1.0, 1.2]
    print(f"    {'factor fn':>12s} {'stub':>12s} {'c1':>8s} {'c2':>8s} {'c3':>8s} {'s1':>8s} {'s2':>8s} {'s3':>8s}   f-dependence")
    for fn in (0x144020D00, 0x14401EB40, 0x14401BDB0, 0x14401CA10, 0x14401F770):
        for ret_i, ret_f in ((0, 0.0), (1, 0.5), (2, 30.0)):
            rows = {f: run_factor(fn, f, ret_i, ret_f) for f in fs}
            cvary = len({tuple(v[1][:3]) for v in rows.values()}) > 1
            svary = len({tuple(v[1][3:]) for v in rows.values()}) > 1
            allone = all(all(x == 1.0 for x in v[1]) for v in rows.values())
            tag = ("all factors 1.0 (no difficulty) -> NO ability term" if allone else
                   ("c DEPENDS on f" if cvary else "c is f-INDEPENDENT") + ("; sigma depends on f" if svary else "; sigma f-indep"))
            v0 = rows[0.0][1]
            v1 = rows[1.0][1]
            print(f"    {fn:#12x} {f'({ret_i},{ret_f:g})':>12s} " + " ".join(f"{x:8.4f}" for x in v0) + f"   f=0.0   {tag}")
            print(f"    {'':12s} {'':12s} " + " ".join(f"{x:8.4f}" for x in v1) + "   f=1.0")
            ok &= rows[0.0][0] == "ok"
    print("    READING (narrow, and it is the ONLY thing this section establishes): the MAGNITUDE factors c1/c2/c3")
    print("    carry no ability term of their own.  Ability only multiplies an existing difficulty D (shape")
    print("    'slot *= 1 - (A + B*(1-f))*D' at 0x14401c1d7..0x14401c212), so D = 0 removes the ability weighting.")
    print("    DO NOT READ THIS AS 'the stock game has no error on a clean kick' - it does, and it IS partly")
    print("    ability-dependent.  S11b measures the real thing; this section only says WHERE the dependence is not.")
    print("    LIMIT: these runs stub each function's own CALLs, so they cover the functions' own code on three stub")
    print("    answers, not every reachable path, and they plant an all-1.0 array the game never produces.")
    print(f"  S11 {'PASS' if ok else 'FAIL'}")
    return ok


def s11b_real_stock_baseline(img):
    """THE HONEST STOCK BASELINE.  Runs the whole builder with the five factor functions LIVE on a standing,
    unpressured, zeroed world, so the six slots are whatever the game itself computes.  This replaces the
    planted (1,1,1,1,1,1) vector that earlier revisions of this tool used and that produced the false claim
    'the stock ceilings are exactly zero'."""
    print("\n== S11b  the REAL stock clean-kick baseline (five factor functions EXECUTED, zeroed world) ==")
    ok = True
    _, HC, VC, PC = site_consts(img)
    print(f"    {'ability':>7s} {'f':>6s} | {'h_ceil':>8s} {'v_ceil':>8s} {'p_ceil':>8s} | {'c1':>6s} {'c2':>6s} {'c3':>6s}"
          f" | {'sig_h':>6s} {'sig_v':>6s} {'sig_p':>6s} | {'s1':>6s} {'s2':>6s} {'s3':>6s}")
    rows = {}
    for ab in ABILITIES:
        f = ability_f(img, ab)
        b = full_builder(img, f, (1.0,) * 6, keep=FACTOR_FNS)
        hm, vm, pm = (struct.unpack_from("<f", b, o)[0] for o in (0x00, 0x10, 0x20))
        sg = [struct.unpack_from("<f", b, o)[0] for o in (0x08, 0x18, 0x28)]
        c = (1 - hm / HC, 1 - vm / VC, 1 - pm / PC)
        K0 = site_consts(img)[0]
        s = [1 - np.sqrt(max(0.0, (x - 0.75) / K0)) for x in sg]
        rows[ab] = (f, hm, vm, pm, sg, c, s)
        print(f"    {ab:7d} {f:6.3f} | {hm:8.4f} {vm:8.4f} {pm*100:7.3f}% | {c[0]:6.3f} {c[1]:6.3f} {c[2]:6.3f}"
              f" | {sg[0]:6.3f} {sg[1]:6.3f} {sg[2]:6.3f} | {s[0]:6.3f} {s[1]:6.3f} {s[2]:6.3f}")
    r40, r99 = rows[40], rows[99]
    ceil_flat = all(abs(r40[i] - r99[i]) < 1e-6 for i in (1, 2, 3))
    ceil_nonzero = r40[1] > 0 and r40[2] > 0 and r40[3] > 0
    sigma_varies = any(abs(r40[4][i] - r99[4][i]) > 1e-3 for i in range(3))
    print("    FINDING 1 - the ceilings are NOT zero on a clean kick: a 40-rated and a 99-rated player both get")
    print(f"      h {r40[1]:.3f} deg / v {r40[2]:.3f} deg / p {r40[3]*100:.2f}%.  c1 = {r40[5][0]:.3f} comes from the")
    print("      unconditional kick-class multiply at 0x14401be1e; c2 and c3 are DERIVED from c1 at 0x14401c849")
    print("      (c2 = 0.5*c1 + 0.5) and 0x14401c76a (c3 = (0.5*c1 + 0.5) then *0.3), so c = (1,1,1) is unreachable.")
    print(f"    FINDING 2 - the ceilings are ability-INDEPENDENT: identical for every ability  -> {ceil_flat}")
    print("    FINDING 3 - the stock game DOES weight ability, but on the SIGMA factors only: s_i = c_i*(0.5 + 0.5*f)")
    print(f"      (0x14401c76a / 0x14401c85f).  sigma_h {r40[4][0]:.3f} at ability 40 vs {r99[4][0]:.3f} at 99.")
    print("    SO THE OWNER'S COMPLAINT, STATED CORRECTLY: a bad player is not incapable of mis-hitting an")
    print("    unpressured ball - he is capped at the SAME ceiling as an elite player and only spreads a little")
    print("    wider inside it.  This cave lowers the ceiling's cleanliness for him, which is the missing half.")
    ok &= ceil_flat and ceil_nonzero and sigma_varies
    print("    LIMIT: the world is synthetic (zeroed player object, most object getters inside the factor functions")
    print("    stubbed to 0).  These are the stock numbers for a standing, unpressured, zero-meter kick as this")
    print("    harness can reach it, not a capture from a live match.")
    print(f"  S11b {'PASS' if ok else 'FAIL'}")
    return ok


# ---- S12: Monte Carlo through the game's real type-4 randomiser 0x14401a060 --------------------
RANDOMISER = 0x14401A060
MC_PARAMS = ARENA + 0x30000
MC_TIN = ARENA + 0x31000
MC_TOUT = ARENA + 0x31100
MC_TEAM = ARENA + 0x32000
MC_OBJ = ARENA + 0x33000
MC_KT = ARENA + 0x34000
MC_AZ, MC_EL, MC_SP = 37.0, 9.0, 0.37          # intended azimuth deg, elevation deg, speed m/frame
MC_STUBS = {0x1442D6C50: MC_OBJ, 0x1442D6D80: MC_OBJ, 0x144307180: MC_OBJ, 0x1442D6DC0: MC_OBJ}


FACTOR_FNS = (0x144020D00, 0x14401EB40, 0x14401BDB0, 0x14401CA10, 0x14401F770)
# calls made from INSIDE a live factor function are stubbed too, except these (the kick-property accessors the
# factor code needs to reach its kick-class / kick-kind branches at all)
INNER_KEEP = {0x143EDA730, 0x143EDA770, 0x143ED80F0, 0x143ED8130, 0x143EDF8B0, FOLD}
D_SITE = 0x14401C1FC                # 'mulss xmm1,xmm9' inside 0x14401bdb0: xmm9 IS the situational difficulty D


def full_builder(img, f, slots, k=None, parts=None, action=1, keep=(), inject_D=None, pred=None):
    """Run the WHOLE builder 0x14401a900 to its ret and return the 0x3c-byte kick-miss struct it produced.

    keep = ()          : every CALL in the builder body is stubbed and `slots` are planted into the factor
                         array (the cheap, fully-controlled run used by S2/S4/S5).
    keep = FACTOR_FNS  : the five cleanliness-factor functions EXECUTE, so the six slots are whatever the game
                         itself computes for a standing, unpressured, zeroed-world kick.  `slots` is ignored.
                         This is the only honest stock baseline - see S11b.
    inject_D           : force xmm9 at D_SITE, i.e. drive the builder's own situational difficulty (S14).
    pred               : overlay 0x143edf000 to return this value (the forced-horizontally-exact predicate).
    """
    e = Emu(img, permissive=True)
    uc = e.uc
    if parts is not None:
        for va, _, b in parts:
            e.overlay(va, b)
        e.overlay(HOOK, hook_bytes(parts[0][0]))
    if pred is not None:
        e.overlay(0x143EDF000, b"\xb0" + bytes([pred]) + b"\xc3")
        keep = tuple(keep) + (0x143EDF000,)
    st = {"calls": 0}
    live_ranges = [(fn, FACTOR_END[fn]) for fn in keep if fn in FACTOR_END] + \
                  ([(0x143EDF000, 0x143EDF003)] if pred is not None else [])

    def code(uc_, addr, size, ud):
        if inject_D is not None and addr == D_SITE:
            uc_.reg_write(XMM[9], f2i(inject_D))
        inner = any(a <= addr < b for a, b in live_ranges)
        if inner:
            b = bytes(uc_.mem_read(addr, size))
            if b[0] == 0xE8 or (b[0] == 0xFF and (b[1] >> 3) & 7 == 2) or \
               (len(b) > 2 and b[0] in (0x41, 0x48) and b[1] == 0xFF and (b[2] >> 3) & 7 == 2):
                tgt = addr + 5 + struct.unpack("<i", b[1:5])[0] if b[0] == 0xE8 else None
                if tgt in INNER_KEEP:
                    return
                uc_.reg_write(X.UC_X86_REG_RAX, 0)
                uc_.reg_write(XMM[0], 0)
                uc_.reg_write(X.UC_X86_REG_RIP, addr + size)
            return
        return _fb_body(uc_, addr, size, st, f, slots, keep)
    uc.hook_add(UC_HOOK_CODE, code)
    return _fb_run(e, uc, action, parts)


def _fb_body(uc_, addr, size, st, f, slots, keep):
    """Builder-body call policy: stub everything except the pure fold and whatever is in `keep`."""
    if addr in (0x140E999A0, 0x140E999B0, 0x144F8307A):
        rsp_ = uc_.reg_read(X.UC_X86_REG_RSP)
        if addr == 0x140E999A0:
            st["heap"] = st.get("heap", ARENA + 0x180000) + 0x100
            uc_.reg_write(X.UC_X86_REG_RAX, st["heap"])
        elif addr == 0x144F8307A:
            dst, src_, n = (uc_.reg_read(GPR[r]) for r in ("rcx", "rdx", "r8"))
            uc_.mem_write(dst, bytes(uc_.mem_read(src_, n)))
            uc_.reg_write(X.UC_X86_REG_RAX, dst)
        uc_.reg_write(X.UC_X86_REG_RIP, struct.unpack("<Q", bytes(uc_.mem_read(rsp_, 8)))[0])
        uc_.reg_write(X.UC_X86_REG_RSP, rsp_ + 8)
        return
    if not (BUILDER <= addr < BUILDER_END):
        return
    b = bytes(uc_.mem_read(addr, size))
    if b[0] == 0xE8 or (b[0] == 0xFF and (b[1] >> 3) & 7 == 2):
        tgt = addr + 5 + struct.unpack("<i", b[1:5])[0] if b[0] == 0xE8 else None
        if tgt == FOLD or (tgt in keep):
            return                      # execute the real thing
        uc_.reg_write(X.UC_X86_REG_RAX, 0)
        if tgt == F_ABILITY:
            uc_.reg_write(XMM[0], f2i(f))
        elif tgt == 0x14401EB40:
            r9 = uc_.reg_read(X.UC_X86_REG_R9)
            for kk, v in enumerate(slots):
                uc_.mem_write(r9 + 4 * kk, struct.pack("<f", v))
        else:
            uc_.reg_write(XMM[0], 0)
        st["calls"] += 1
        uc_.reg_write(X.UC_X86_REG_RIP, addr + size)


def _fb_run(e, uc, action, parts):
    e.overlay(COOKIE_CHECK, b"\xc3")
    rsp = STACK_TOP - 0x1000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, OUT)
    uc.reg_write(X.UC_X86_REG_RDX, PLAYER)
    uc.reg_write(X.UC_X86_REG_R8, VEC)
    uc.reg_write(X.UC_X86_REG_R9, VEC + 0x100)
    uc.mem_write(rsp + 0x28, struct.pack("<QQQQ", VEC + 0x200, VEC + 0x300, VEC + 0x400, VEC + 0x500))
    uc.mem_write(PLAYER, b"\x00" * 0x8000)          # zeroed world: standing, unpressured, meter 0
    uc.mem_write(PLAYER + 0xAD0, bytes([action]))
    uc.mem_write(PLAYER + 0x2F6E, struct.pack("<h", 0x10))
    uc.emu_start(BUILDER, RET_MAGIC, count=4000000)
    assert uc.reg_read(X.UC_X86_REG_RIP) == RET_MAGIC, "builder did not return"
    return bytes(uc.mem_read(OUT, 0x3C))


def mc_draw(img, miss_blob, seed, action=1, assist=0):
    """One kick through the game's REAL type-4 randomiser with the REAL RNG (LCG 0x144345e00 + Box-Muller
    0x144345eb0 + sign 0x143eafd30 + wrap 0x144345ae0 all executed; only four object getters are stubbed).
    Returns (dAzimuth deg, dElevation deg, speed ratio - 1)."""
    e = Emu(img, permissive=True)
    uc = e.uc
    uc.mem_write(MC_PARAMS, b"\x00" * 0x60)
    uc.mem_write(MC_PARAMS + 0x10, miss_blob)      # caller layout: params+0x10 == builder out+0x00 (0x144016d6b)
    for base in (MC_TIN, MC_TOUT):
        e.wf(base, MC_AZ); e.wf(base + 4, MC_EL); e.wf(base + 8, MC_SP)
    uc.mem_write(PLAYER, b"\x00" * 0x5000)
    uc.mem_write(PLAYER + 0x47C0, struct.pack("<Q", MC_TEAM))
    uc.mem_write(PLAYER + 0xAD0, bytes([action]))
    uc.mem_write(PLAYER + 0x362C, bytes([assist]))
    for kk in range(8):                            # the LCG seed array lives at player+0x3bb4 (0x143ea9250)
        uc.mem_write(PLAYER + 0x3BB4 + 4 * kk, struct.pack("<I", (seed * 2654435761 + 12345 * kk) & 0x7FFFFFFF))

    def code(uc_, addr, size, ud):
        if bytes(uc_.mem_read(addr, 1))[0] == 0xE8:
            tgt = addr + 5 + struct.unpack("<i", bytes(uc_.mem_read(addr + 1, 4)))[0]
            if tgt in MC_STUBS:
                uc_.reg_write(X.UC_X86_REG_RAX, MC_STUBS[tgt])
                uc_.reg_write(X.UC_X86_REG_RIP, addr + 5)
    uc.hook_add(UC_HOOK_CODE, code)
    rsp = STACK_TOP - 0x8000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.mem_write(rsp + 0x28, struct.pack("<Q", MC_TOUT))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, PLAYER)
    uc.reg_write(X.UC_X86_REG_RDX, MC_KT)
    uc.reg_write(X.UC_X86_REG_R8, MC_PARAMS)
    uc.reg_write(X.UC_X86_REG_R9, MC_TIN)
    uc.emu_start(RANDOMISER, RET_MAGIC, count=200000)
    assert uc.reg_read(X.UC_X86_REG_RIP) == RET_MAGIC, "randomiser did not return"
    o = (e.rf(MC_TOUT), e.rf(MC_TOUT + 4), e.rf(MC_TOUT + 8))
    return (((o[0] - MC_AZ + 180.0) % 360.0) - 180.0, o[1] - MC_EL, o[2] / MC_SP - 1.0)


def mc_stats(img, miss_blob, n, seed0=1):
    a = np.array([mc_draw(img, miss_blob, seed0 + i) for i in range(n)])
    out = []
    for col in range(3):
        v = np.abs(a[:, col])
        out.append((v.mean(), np.percentile(v, 90), v.max()))
    return out


def s12_montecarlo(img, k, gain, axes, n=400, slots=(1.0,) * 6,
                   label="the game's OWN clean-kick factors (five factor functions executed, S11b)"):
    """The whole chain for real: builder (patched / stock) -> kick-miss struct -> real randomiser -> deviation."""
    print(f"\n== S12  Monte Carlo through the game's REAL randomiser 0x14401a060, n={n} per row ==")
    print(f"    baseline: {label}")
    print(f"    intended kick: azimuth {MC_AZ} deg, elevation {MC_EL} deg, {MC_SP * 60 * 3.6:.0f} km/h; "
          f"player+0x362c = 0 (NOT assisted), action id 1 (not a shot)")
    K0, HC, VC, PC = site_consts(img)
    parts = assemble(cave_source(k, gain, None, axes, "none"))
    ok = True
    print(f"    {'ability':>7s} {'f':>6s} {'S':>6s} | {'h_ceil':>7s} {'v_ceil':>7s} {'p_ceil':>7s} | "
          f"{'mean|dh|':>8s} {'p90|dh|':>8s} {'mean|dv|':>8s} {'p90|dv|':>8s} {'mean|dp|':>8s} {'p90|dp|':>8s}")
    rows = {}
    for ab in ABILITIES:
        f = ability_f(img, ab)
        for tag, p in (("STOCK  ", None), ("PATCHED", parts)):
            blob = full_builder(img, f, slots, parts=p, keep=FACTOR_FNS)
            hm, vm, pm = struct.unpack_from("<f", blob, 0)[0], struct.unpack_from("<f", blob, 0x10)[0], \
                struct.unpack_from("<f", blob, 0x20)[0]
            st = mc_stats(img, blob, n, seed0=1)
            S = model_S(gain, 0.0, f, tiredness="none")
            rows[(ab, tag)] = (f, S, hm, vm, pm, st)
            print(f"    {ab:3d} {tag} {f:6.3f} {S:6.3f} | {hm:7.3f} {vm:7.3f} {pm * 100:6.2f}% | "
                  f"{st[0][0]:8.3f} {st[0][1]:8.3f} {st[1][0]:8.3f} {st[1][1]:8.3f} "
                  f"{st[2][0] * 100:7.2f}% {st[2][1] * 100:7.2f}%")
        # monotone: patched ceilings >= stock ceilings, and equal iff S == 1
        s_, p_ = rows[(ab, "STOCK  ")], rows[(ab, "PATCHED")]
        good = all(p_[2 + i] >= s_[2 + i] - 1e-6 for i in range(3))
        if p_[1] == 1.0:
            good &= all(abs(p_[2 + i] - s_[2 + i]) < 1e-9 for i in range(3))
        ok &= good
        if not good:
            print(f"      ^ ability {ab}: MONOTONICITY/IDENTITY CHECK FAILED")
    # WHOLE-STRUCT liveness: xmm6/xmm12 are callee-SAVED in the Win64 ABI, so the builder could legitimately read
    # them again after the call at 0x14401b4bc.  Diff every one of the 0x3c output bytes, stock vs patched.
    print("    whole-struct liveness (full builder to its ret, stock vs patched, f = 0.1): which of the 15 output")
    print("    dwords differ - must be exactly +0x00 (h_max), +0x10 (v_max), +0x20 (p_max):")
    f01 = ability_f(img, 60)
    for cvec, kp, tag in (((1.0,) * 6, (), "planted (1,1,1,1,1,1)"),
                          ((0.9, 0.8, 0.7, 0.6, 0.5, 0.4), (), "planted dirty vector"),
                          ((1.0,) * 6, FACTOR_FNS, "factor functions LIVE")):
        b_s = full_builder(img, f01, cvec, keep=kp)
        b_p = full_builder(img, f01, cvec, parts=parts, keep=kp)
        difs = [o for o in range(0, 0x3C, 4) if b_s[o:o + 4] != b_p[o:o + 4]]
        good = difs == [0x00, 0x10, 0x20]
        ok &= good
        print(f"      {tag:24s}: differing dwords {[hex(o) for o in difs]}  "
              f"{'OK' if good else 'NO - a scaled register is reused elsewhere'}")
    # identity at f >= 1 with the factor functions live (the earlier revision only checked it with planted slots)
    for fv in (1.0, 1.5, 2.0):
        same = full_builder(img, fv, (1.0,) * 6, keep=FACTOR_FNS) == \
            full_builder(img, fv, (1.0,) * 6, parts=parts, keep=FACTOR_FNS)
        ok &= same
        print(f"      identity at f = {fv} with LIVE factor functions: whole 0x3c struct bit-identical = {same}")
    print("    dh/dv in degrees, dp as a fraction of the intended speed.  ceilings are the builder's own out struct")
    print(f"    fields (h at +0x00, v at +0x10, p at +0x20) on THIS image (H {HC:g} deg, V {VC:g} deg, power {PC * 100:.0f}%).")
    print("    Ability 99 (f = 1.0) must be identical to stock in every column - that is the identity requirement.")
    print(f"  S12 {'PASS' if ok else 'FAIL'}")
    return ok, rows


def s13_gain_choice(img, axes, gains=(0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.35), n=250, dist_m=20.0):
    """Sweep the gain against the STOCK baseline and against the game's own LIGHT-PRESSURE error for the same
    player, both measured here.  This is the evidence for the default; the earlier revision chose 0.35 against a
    stock column that was wrongly believed to be zero."""
    print(f"\n== S13  choosing GAIN: measured spray of a {dist_m:.0f} m clean, unpressured pass (n={n} per cell) ==")
    K0, HC, VC, PC = site_consts(img)
    fs = {ab: ability_f(img, ab) for ab in (40, 75, 99)}
    print("    ability -> f (the game's own 0x143ed71d0): " + "  ".join(f"{a}->{v:.3f}" for a, v in fs.items()))
    cmf = lambda deg: dist_m * np.tan(np.radians(deg)) * 100
    # --- the anchor: what the STOCK game already gives THIS player once there is a little difficulty ---
    print("    ANCHOR - the same player, stock, with the builder's own situational difficulty D injected at")
    print(f"    {D_SITE:#x} ('mulss xmm1,xmm9'; xmm9 is D).  D is a fraction 0..1 on an undecoded scale, so treat")
    print("    D=0.25 as 'a little pressure', not as a calibrated game state:")
    anchor = {}
    for D in (0.0, 0.25, 0.5, 1.0):
        blob = full_builder(img, fs[40], (1.0,) * 6, keep=FACTOR_FNS, inject_D=D)
        st = mc_stats(img, blob, n)
        anchor[D] = (cmf(st[0][1]), cmf(st[1][1]))
        print(f"      ability 40, D={D:4.2f}: h_ceil {struct.unpack_from('<f', blob, 0)[0]:6.3f} deg  "
              f"lat p90 {anchor[D][0]:5.0f} cm   vert p90 {anchor[D][1]:5.0f} cm")
    AL, AV = anchor[0.25]
    print(f"    RULE USED FOR THE DEFAULT: the WORST player's UNPRESSURED clean kick must stay below what the stock")
    print(f"    game already gives him under light pressure ({AL:.0f} cm lateral / {AV:.0f} cm vertical p90).  A patch that")
    print("    makes standing still worse than being closed down reads as a bug, not as a human error.")
    out = {"anchor": (AL, AV)}
    print(f"    {'gain':>5s} | {'ab40 lat':>8s} {'ab40 vert':>9s} | {'ab75 lat':>8s} {'ab75 vert':>9s} | "
          f"{'ab99 lat':>8s} {'ab99 vert':>9s} | {'sep lat':>7s} {'sep vert':>8s} | rule")
    for g in (None,) + tuple(gains):
        parts = None if g is None else assemble(cave_source(K0, g, None, axes, "none"))
        r = {}
        for ab in (40, 75, 99):
            blob = full_builder(img, fs[ab], (1.0,) * 6, parts=parts, keep=FACTOR_FNS)
            st = mc_stats(img, blob, n)
            r[ab] = (cmf(st[0][1]), cmf(st[1][1]))
        passes = r[40][0] <= AL and r[40][1] <= AV
        tag = "STOCK" if g is None else f"{g:.2f}"
        print(f"    {tag:>5s} | {r[40][0]:8.0f} {r[40][1]:9.0f} | {r[75][0]:8.0f} {r[75][1]:9.0f} | "
              f"{r[99][0]:8.0f} {r[99][1]:9.0f} | {r[40][0]/r[99][0]:7.2f} {r[40][1]/r[99][1]:8.2f} | "
              f"{'ok' if passes else 'OVER ANCHOR'}")
        out[g] = dict(rows=r, passes=passes)
    print("    'sep' = the worst player's p90 divided by the best player's - the thing the owner is actually asking")
    print("    for.  Stock is about 2x on both axes; the cave is what widens it.  cm figures are the angular miss")
    print(f"    projected over {dist_m:.0f} m, so the vertical column is over/under-hit weight plus loft, not a landing error.")
    return True, out


def s13b_squad(img, k, gain, axes, n=250, dist_m=20.0):
    """At the CHOSEN gain, what every rung of a real squad gets.  Real eFootball passing bytes cluster 60..95."""
    print(f"\n== S13b  the chosen gain {gain} across a realistic squad (n={n} per row, {dist_m:.0f} m pass) ==")
    K0, HC, VC, PC = site_consts(img)
    parts = assemble(cave_source(k, gain, None, axes, "none"))
    print(f"    {'ability':>7s} {'f':>6s} {'S':>6s} | {'h_ceil':>7s} {'v_ceil':>7s} {'p_ceil':>7s} | {'mean|dh|':>8s} "
          f"{'mean|dv|':>8s} {'p90|dv|':>8s} {'mean cm':>8s} {'p90 cm':>7s} | {'mean|dp|':>8s} {'spin+':>7s}")
    for ab in (55, 60, 65, 70, 75, 80, 85, 90, 95, 99):
        f = ability_f(img, ab)
        blob = full_builder(img, f, (1.0,) * 6, parts=parts, keep=FACTOR_FNS)
        hm, vm, pm = (struct.unpack_from("<f", blob, o)[0] for o in (0, 0x10, 0x20))
        st = mc_stats(img, blob, n)
        S = model_S(gain, 0.0, f, tiredness="none")
        print(f"    {ab:7d} {f:6.3f} {S:6.3f} | {hm:7.3f} {vm:7.3f} {pm * 100:6.2f}% | {st[0][0]:8.3f} "
              f"{st[1][0]:8.3f} {st[1][1]:8.3f} {dist_m * np.tan(np.radians(st[1][0])) * 100:8.1f} "
              f"{dist_m * np.tan(np.radians(st[1][1])) * 100:7.1f} | {st[2][0] * 100:7.2f}% {0.5 * st[0][0]:6.2f}")
    print("    'spin+' = the mean side spin linked-spin.json adds from this horizontal miss (its GAIN = -0.5 rev/s")
    print("    per degree, capped at 8 rev/s = a 16 deg miss), i.e. mean|dh| * 0.5 rev/s.  NOTE: the stock clean kick")
    print("    is NOT 0 here - it already carries the kick-class horizontal ceiling, so linked-spin is already live.")
    print("    A football is 22 cm across.  The STOCK row for comparison is printed by S11b/S13.")
    return True


def s14_behaviour_changes(img, k, gain, axes, n=400, dist_m=20.0):
    """The two things the cave changes that the owner has to AGREE to, measured rather than described, plus the
    two downstream facts that make the horizontal axis behave differently from the vertical one on HIS image."""
    print(f"\n== S14  behaviour changes and downstream couplings, measured (n={n}) ==")
    ok = True
    cmf = lambda deg: dist_m * np.tan(np.radians(deg)) * 100
    parts = assemble(cave_source(k, gain, None, axes, "none"))

    print("  (a) FORCED-HORIZONTALLY-EXACT kicks.  0x143edf000 (bit 17 of [player+0xad8] set AND [player+0x362d]&8")
    print("      clear) sets c1 = 1.0 and the horizontal sigma factor to 1.0 at 0x14401b34a, BEFORE the hook, so")
    print("      those kicks are exactly straight in stock.  The cave multiplies c1 AFTER that, which removes the")
    print("      guarantee.  WHAT SETS THAT BIT IS NOT KNOWN.  Cost at this gain, predicate forced true:")
    for ab in (40, 75, 99):
        f = ability_f(img, ab)
        b0 = full_builder(img, f, (1.0,) * 6, keep=FACTOR_FNS, pred=1)
        b1 = full_builder(img, f, (1.0,) * 6, keep=FACTOR_FNS, pred=1, parts=parts)
        s0, s1 = mc_stats(img, b0, n), mc_stats(img, b1, n)
        h0 = struct.unpack_from("<f", b0, 0)[0]
        h1 = struct.unpack_from("<f", b1, 0)[0]
        ok &= h0 == 0.0
        print(f"      ability {ab:3d}: stock h_ceil {h0:.3f} (lat p90 {cmf(s0[0][1]):.1f} cm) -> patched h_ceil {h1:.3f} "
              f"(lat p90 {cmf(s1[0][1]):5.1f} cm, worst {cmf(s1[0][2]):5.1f} cm at {dist_m:.0f} m; "
              f"{11 * np.tan(np.radians(s1[0][1])) * 100:4.1f} cm at a penalty's 11 m)")
    print("      --axes vp removes this entirely, at the cost of the sideways miss on every other kick.")

    print("  (b) AZIMUTH SIGN BIAS on THIS image.  0x14401a12c ('mulss xmm0,[cell]') is inside the randomiser's")
    print("      FIRST block, which reads [rdi+0x10]/[rdi+0x14]/[rdi+0x48] - and the caller copies kick-miss+0x00,")
    print("      the HORIZONTAL ceiling, to that struct (0x144016d4f..0x144016e85).  So it is the AZIMUTH sign coin,")
    print("      not a vertical one: the project's note calling scuff-wobble entry 2 a 'vertical sign bias' is wrong.")
    for nm, im in (("this image", img),):
        ins = next(im.md.disasm(im.read(0x14401A12C - im.base, 16), 0x14401A12C))
        cellv = struct.unpack("<f", im.read(im.lea_target(ins), 4))[0]
        blob = bytearray(0x3C)
        struct.pack_into("<fff", blob, 0x00, 10.0, 0.5, 0.75)
        struct.pack_into("<i", blob, 0x34, 4)
        d = np.array([mc_draw(im, bytes(blob), 1 + i)[0] for i in range(n)])
        pos, neg = 100 * (d > 1e-6).mean(), 100 * (d < -1e-6).mean()
        print(f"      {nm}: cell = {cellv:g} (stock 100) -> azimuth positive {pos:.1f}% / negative {neg:.1f}%, "
              f"signed mean {d.mean():+.3f} of a 10 deg ceiling")
        if abs(pos - neg) > 15:
            print("      => the new sideways error is ONE-SIDED on this image: a bad player drags the ball the same")
            print("         way most of the time, and linked-spin curls it the same way too.  Fix is at 0x14401a12c")
            print("         (scuff-wobble entry 2), not here.")

    print("  (c) struct+0x38 is a DETERMINISTIC floor, not a draw: the randomiser computes")
    print("      dev = ceil*(w + (1-w)*random) at 0x14401a115..0x14401a13d with w = [rdi+0x48].  Every number in")
    print("      this tool is measured with w = 0, which is what the builder writes at 0x14401a991 and what this")
    print("      synthetic world produces.  Only 0x14401e5b0 (called at 0x14401b5d5) can make it non-zero.  If it")
    print("      ever does, the cave multiplies a certainty rather than a probability:")
    for w in (0.0, 0.1, 0.2):
        blob = bytearray(0x3C)
        struct.pack_into("<fff", blob, 0x10, 10.0, 0.5, 1.9665)
        struct.pack_into("<i", blob, 0x34, 4)
        struct.pack_into("<f", blob, 0x38, w)
        v = np.abs(np.array([mc_draw(img, bytes(blob), 1 + i)[1] for i in range(n)]))
        print(f"      w = {w:4.2f}: minimum observed miss over {n} draws = {v.min():.3f} deg = {cmf(v.min()):5.1f} cm "
              f"(= w x ceiling exactly)")
    print("      NOT PROVEN: whether 0x14401e5b0 ever writes a non-zero w in a real match.")

    print("  (d) WHICH CONSUMER THE NUMBERS DESCRIBE.  The builder stores a miss type at out+0x34 (4 by default,")
    print("      0x14401a937).  The caller dispatches at 0x144016dc6: types 0 and 2 -> 0x144019320 (which then sets")
    print("      [rbp+0x104] = 4 and falls into the same randomiser), types 1 and 3 -> 0x144019e40, type 4 ->")
    print("      0x14401a060.  Every table in this tool is measured through 0x14401a060.  0x144019e40 reads the same")
    print("      three triples but applies its own formula and was NOT emulated, so types 1 and 3 are covered by the")
    print("      mechanism and NOT by the degree/cm figures.")
    print(f"  S14 {'PASS' if ok else 'FAIL'}")
    return ok


def write_spec_ability(img, live, parts, k, gain, axes, mc_rows, gain_tbl=None):
    """The ABILITY-BASELINE spec.  Expect bytes are taken from `expect_img` = the image the OWNER will patch."""
    spec_path = SPEC.with_name("cave-ability-error.json")
    expect_img = live if live is not None else img
    entry, maxlen, code1 = parts[0]
    on_disk = expect_img.read(entry - expect_img.base, len(code1))
    hook_disk = expect_img.read(HOOK - expect_img.base, 8)
    # the expect bytes go into the spec verbatim; refuse to author a spec against anything but virgin padding
    assert expect_img.read(entry - expect_img.base, maxlen) == b"\xcc" * maxlen, \
        f"padding at {entry:#x} in {expect_img.path} is not all int3 - refusing to author"
    assert hook_disk == STOLEN, f"hook bytes at {HOOK:#x} in {expect_img.path} are not the stock load - refusing to author"
    print(f"\nexpect bytes taken from: {expect_img.path}")
    patches = [dict(name=f"cave-ability-error body ({len(code1)} B in {maxlen} B int3 padding at {entry:#x})",
                    va=f"{entry:#x}", expect=on_disk.hex(), patch=code1.hex(), kind="code"),
               dict(name=f"cave-ability-error hook (replaces 'movss xmm3,[rip->4.25f]' with jmp {entry:#x} + 3-byte nop)",
                    va=f"{HOOK:#x}", expect=hook_disk.hex(), patch=hook_bytes(entry).hex(), kind="code")]
    if gain_tbl:
        _AL, _AV = gain_tbl["anchor"]
        _rows = "; ".join(f"{gv:.2f}{' (DEFAULT)' if gv == gain else ''} -> "
                          f"{gain_tbl[gv]['rows'][40][0]:.0f} / {gain_tbl[gv]['rows'][40][1]:.0f}"
                          for gv in sorted(g for g in gain_tbl if isinstance(g, float)))
        _stock = gain_tbl.get(None, {}).get("rows")
        gain_tun = (
            "S = clamp01(1 - gain*(1 - f)), f = the ability factor. It is how much of the game's own remaining error "
            "headroom a 40-rated player (f = 0) gives up on a clean kick. Measured p90 miss for a 40-rated player on an "
            "unpressured 20 m ball, lateral / weight in cm: "
            + (f"stock {_stock[40][0]:.0f} / {_stock[40][1]:.0f}; " if _stock else "")
            + _rows
            + f". The anchor the default is chosen against is {_AL:.0f} / {_AV:.0f} cm - what the stock game already gives "
              f"the SAME player under light pressure (D = 0.25 injected at 0x14401c1fc). The default is the LARGEST value "
              f"that stays inside it on both axes, so treat it as the top of the sensible range, not the middle. Values "
              f"above 1 only saturate (S is floored at 0). CHANGE THIS BY REGENERATING THE SPEC (python "
              f"tools/emu_kickerror.py --tiredness none --gain <g> --write-spec), not by editing these bytes - a hand-edit "
              f"makes 'exe_patch remove' refuse (see ROLLBACK in the description).")
    else:
        gain_tun = "S = clamp01(1 - gain*(1 - f)); regenerate the spec to embed the measured sweep."
    k_at = find_imm(code1, entry, f2i(k))
    g_at = find_imm(code1, entry, f2i(gain), 1 if f2i(gain) == f2i(k) else 0)
    tun = {"K": dict(va=f"{k_at:#x}", bytes=4, encoding="float32 LE", value=k,
                     meaning="Gaussian sigma scale in sigma = max(0.1, 0.75 + K*(1-s)^2). DEFAULT 4.25 = the STOCK value, so "
                             "this cave does NOT bundle the sigma change. Setting it to 6.0 makes this spec include "
                             "error-sigma.json's effect. Applies to EVERY kick."),
           "gain": dict(va=f"{g_at:#x}", bytes=4, encoding="float32 LE", value=gain, meaning=gain_tun)}
    _, HC, VC, PC = site_consts(expect_img)
    tbl = []
    cmv = lambda deg: 20.0 * np.tan(np.radians(deg)) * 100
    for ab in ABILITIES:
        f_, S_, hm, vm, pm, st = mc_rows[(ab, "PATCHED")]
        s0 = mc_rows[(ab, "STOCK  ")]
        tbl.append(f"ability {ab} (f={f_:.2f}, S={S_:.3f}): ceilings h {hm:.2f} / v {vm:.2f} deg / p {pm * 100:.1f}% "
                   f"vs STOCK h {s0[2]:.2f} / v {s0[3]:.2f} deg / p {s0[4] * 100:.1f}%; over a 20 m ball the p90 miss "
                   f"goes {cmv(s0[5][0][1]):.0f} -> {cmv(st[0][1]):.0f} cm sideways and {cmv(s0[5][1][1]):.0f} -> "
                   f"{cmv(st[1][1]):.0f} cm in weight/loft")
    axn = ", ".join(f"{AXIS_REG[a][1]} ({AXIS_REG[a][0]})" for a in "hvp" if a in axes)
    s40, s99 = mc_rows[(40, "STOCK  ")], mc_rows[(99, "STOCK  ")]
    p40, p99 = mc_rows[(40, "PATCHED")], mc_rows[(99, "PATCHED")]
    sep_s = cmv(s40[5][1][1]) / max(1e-9, cmv(s99[5][1][1]))
    sep_p = cmv(p40[5][1][1]) / max(1e-9, cmv(p99[5][1][1]))
    if gain_tbl:
        AL, AV = gain_tbl["anchor"]
        def _g(gv):
            r = gain_tbl.get(gv, {}).get("rows")
            return f"{r[40][0]:.0f} / {r[40][1]:.0f} cm" if r else "not measured"
        worse = sorted(g for g, v in gain_tbl.items() if isinstance(g, float) and not v["passes"])
        gain_note = (
            f"a stock ability-40 player at D = 0.25 has a p90 miss of {AL:.0f} cm sideways / {AV:.0f} cm in weight over a "
            f"20 m ball, against {_g(None) if None in gain_tbl else f'{cmv(s40[5][0][1]):.0f} / {cmv(s40[5][1][1]):.0f} cm'} "
            f"unpressured in stock. Measured unpressured p90 for that same player by gain: "
            + "; ".join(f"{gv:.2f} -> {_g(gv)}" for gv in sorted(g for g in gain_tbl
                                                                              if isinstance(g, float)))
            + f". The chosen {gain} is the largest value on that sweep that stays inside the anchor on BOTH axes"
            + (f"; {min(worse):.2f} and above break it" if worse else "")
            + f". Be aware the vertical margin at the default is thin - {_g(gain)} against a {AV:.0f} cm anchor - so treat "
              f"the default as the TOP of the sensible range, not the middle, and drop to 0.08 or 0.06 for headroom. "
              f"An earlier revision of this spec shipped 0.35, chosen against a stock column that was wrongly believed to "
              f"be zero; on this sweep 0.35 puts an unpressured 40-rated player further off line than the stock game's own "
              f"HALF-pressure error for him. ALL cm figures in this spec are Monte-Carlo estimates from a few hundred to a "
              f"few thousand draws - treat them as +-5%, and do not read a 5 cm difference between two of them as real")
    else:
        gain_note = "(gain sweep not available - regenerate with emu_kickerror.py to embed the measured table)"
    desc = (
        f"ABILITY BASELINE -> kick error on: {axn} (code cave). "
        f"WHAT IT DOES: it makes the kick-error CEILING depend on the player. "
        f"THE PROBLEM, STATED CORRECTLY (this paragraph replaces an earlier, wrong one): the stock game does NOT give an "
        f"unpressured clean kick zero error. With the five cleanliness-factor functions actually executing "
        f"(emu_kickerror S11b) a standing, unpressured, zeroed-world kick leaves the builder with "
        f"h {s40[2]:.3f} deg / v {s40[3]:.3f} deg / p {s40[4] * 100:.2f}% - because c1 carries the unconditional kick-class "
        f"multiply at 0x14401be1e and c2, c3 are DERIVED from c1 (c2 = 0.5*c1 + 0.5 at 0x14401c849; c3 = (0.5*c1 + 0.5) "
        f"then *0.3 at 0x14401c76a/0x14401c8ce), so the ideal vector c = (1,1,1) is unreachable on 172 of 176 kick ids. "
        f"The stock game also DOES weight ability, but only on the SIGMA factors (s_i = c_i*(0.5 + 0.5*f)), i.e. on how "
        f"wide the draw spreads INSIDE that ceiling, never on the ceiling itself. Net effect in stock: the ceiling is "
        f"IDENTICAL for a 40-rated and a 99-rated player, and the p90 miss on a 20 m ball separates them by only about "
        f"{sep_s:.1f}x ({cmv(s40[5][1][1]):.0f} cm vs {cmv(s99[5][1][1]):.0f} cm of weight/loft error). A bad player "
        f"therefore cannot mis-hit an unpressured ball any WORSE than an elite one can - he only does it a bit more often. "
        f"That is the gap this cave fills: it scales the cleanliness factors themselves by an ability term, so the ceiling "
        f"moves. At gain {gain} the same separation becomes about {sep_p:.1f}x, and ability 99 stays bit-identical to stock. "
        f"MECHANISM: hooks the kick-miss builder 0x14401a900 at {HOOK:#x} (the 8-byte 'movss xmm3,[rip->4.25f]' sigma-K "
        f"load), jumps to the 91-byte int3 run at {entry:#x}, computes S = max(0, min(1, 1 - gain*(1 - f))) where f = the "
        f"ability factor at [rsp+0x40] (0x143ed71d0: 40 -> 0.0, 60 -> 0.1, 75 -> 0.5, 90 -> 0.9, 99 -> 1.0, and it can "
        f"exceed 1), multiplies {axn} by S, re-materialises xmm3 = K from an immediate, and returns to {HOOK_RET:#x}. "
        f"NO memory reads except [rsp+0x40] (which the builder itself re-reads at 0x14401b72f), no calls, no stack use, no "
        f"memory writes; clobbers only rax/xmm0/xmm2/xmm5, proven dead at the hook, and not even EFLAGS "
        f"(mov/movd/movaps/subss/mulss/minss/maxss/xorps write no flags). xmm2 and xmm5 do still differ from stock at the "
        f"builder's ret - they are volatile in the Win64 ABI and the stock builder already leaves garbage in them, so that "
        f"is harmless, but the earlier wording 'no live register differs' was too strong. The clamp is two-sided and "
        f"NaN-safe, so f < 0, f = NaN, f = +-inf or a mis-set gain can at worst zero a cleanliness factor (= the game's own "
        f"full ceiling) and never exceed it. "
        f"IDENTITY: at f >= 1.0 (ability 99, or anyone whose skill/team bonuses push the effective ability past 99) S is "
        f"exactly 1.0 and the whole 0x3c-byte kick-miss struct is BIT-IDENTICAL to unpatched - checked both with planted "
        f"factors and with the factor functions live, at f = 1.0, 1.5 and 2.0. Below that, exactly three of the fifteen "
        f"output dwords move (+0x00, +0x10, +0x20) and nothing else in the struct does. "
        f"EFFECT, measured end to end on THIS image (H {HC:g} deg, V {VC:g} deg, power {PC * 100:.0f}%) at K={k} gain={gain}, "
        f"standing unpressured kick, the game's OWN cleanliness factors, deviations drawn through its own type-4 randomiser "
        f"0x14401a060 with its real LCG and Box-Muller: " + "; ".join(tbl) + ". "
        f"WHY GAIN = {gain}: chosen against a rule that is not taste - the worst player's UNPRESSURED clean kick must stay "
        f"BELOW what the stock game already gives that same player under light pressure, because a patch that makes standing "
        f"still worse than being closed down reads as a bug rather than as a human error. The anchor is measured on this "
        f"image by injecting the builder's own difficulty scalar D at 0x14401c1fc: " + gain_note + " "
        f"INTERACTIONS - read before applying: "
        f"(1) this spec OCCUPIES {HOOK:#x} and materialises K itself, so it is MUTUALLY EXCLUSIVE with error-sigma.json, "
        f"cave-fatigue.json, cave-fatigue-weakfoot.json, loose-realism-v2.json and slices-scuffs*.json; exe_patch refuses "
        f"the second one on the expect bytes. With the default K={k} (the stock value) applying this spec does NOT change "
        f"sigma; regenerate with --k 6 to bundle error-sigma.json's change. "
        f"(2) the flat per-kick-class multiplier at 0x14401be1e (x0.90 class 0, x0.88 class 1, x0.86 classes 2/3, x1.00 "
        f"class 4; 57/46/34/35/4 of kick ids 1..0xb0) is ABILITY-INDEPENDENT and sits on the horizontal factor. The cave "
        f"multiplies AFTER it, so the patched horizontal ceiling is (1 - c1_class*S)*{HC:g} deg - and because c2/c3 are "
        f"derived from c1, that class term is already baked into the vertical and power ceilings as well. No class is exempt. "
        f"(3) BEHAVIOUR CHANGE TO AGREE TO: the forced-horizontally-exact predicate 0x143edf000 (bit 17 of [player+0xad8] "
        f"set AND [player+0x362d]&8 clear) sets c1 = 1.0 and the horizontal sigma factor to 1.0 at 0x14401b34a, BEFORE the "
        f"hook, so those kicks are exactly straight in stock. The cave multiplies c1 after that and REMOVES that guarantee. "
        f"WHAT SETS THAT BIT IS NOT KNOWN - a scripted, cutscene or set-piece kick are all live possibilities. Measured "
        f"cost at gain 0.10 (S14a): ability 40 goes from exactly 0.0 to a p90 of 28 cm over 20 m (16 cm at a penalty's "
        f"11 m; worst observed 57 cm over 20 m), ability 75 to 14 cm, ability 99 unchanged. At the old gain 0.35 the same "
        f"figures were 149 cm p90 and 275 cm worst case, which is a large part of why the gain came down. Regenerate with "
        f"--axes vp to keep those kicks exact, at the cost of the sideways miss on every other kick. "
        f"(4) the assisted-pass flag [player+0x362c]&1 still zeroes the HORIZONTAL deviation inside the randomiser at "
        f"0x14401a15d, whatever ceiling the builder produced; vertical and power are unaffected by it. Turn pass assistance "
        f"OFF before concluding the patch does nothing. "
        f"(5) technique-realism.json (APPLIED on the live exe) re-aims six difficulty thresholds; it does not touch this "
        f"site and its expect bytes are unaffected. It also changed the ability weight B at 0x14401c1dc from 0.60 to 0.75 "
        f"in c *= 1 - clamp01(0.1 + B*(1-f))*D, so it already made a bad player worse UNDER PRESSURE. Measured composition "
        f"at ability 40 (p90 lateral / vertical cm over a 20 m ball): D=0 pristine 86/42, installed 86/56, installed + this "
        f"cave at gain 0.10 139/130; D=0.25 188/91, 214/135, 259/206; D=1.00 524/240, 606/379, 615/430. The two terms "
        f"multiply the same c and the ceiling saturates, so the cave's effect is concentrated exactly where it was aimed - "
        f"the unpressured kick - and adds little on top of a heavily pressured one. "
        f"(6) scuff-wobble.json entries 1+2 (APPLIED). Entry 1 raised the vertical ceiling 22.5 -> 30 deg at 0x14401b423, "
        f"and every vertical number here is on that image (on pristine they would be 25% smaller). Entry 2, at 0x14401a12c, "
        f"is recorded in this project as a 'vertical sign bias' and THAT LABEL IS WRONG: 0x14401a12c sits in the "
        f"randomiser's FIRST block, which reads [rdi+0x10]/[rdi+0x14]/[rdi+0x48] - the slot the caller fills from kick-miss "
        f"+0x00, i.e. the HORIZONTAL ceiling; it is the slot the assist flag kills and the one that is angle-wrapped into "
        f"azimuth. Its 100 -> 50 change makes the AZIMUTH sign coin roughly 3:1 one-sided: measured over 1200 draws, 24% "
        f"positive / 72% negative on the installed image versus 47% / 49% on pristine, with the elevation block identical "
        f"on both. So the sideways error this cave opens up will DRAG ONE WAY rather than spray symmetrically, and "
        f"linked-spin will curl it one way too. If that is not wanted the fix is at 0x14401a12c, not here. "
        f"(7) linked-spin.json (APPLIED, hook 0x1440187b4, cave 0x14105ed1e - DIFFERENT padding, not disturbed): "
        f"|added spin.y| = 0.5 rev/s per degree of horizontal miss, capped at 8 rev/s. Correcting an earlier claim in this "
        f"spec: a stock clean kick does NOT produce zero horizontal miss, so linked-spin is already live on every kick. "
        f"Measured at gain 0.10, mean added spin goes 0.63 -> 1.01 rev/s at ability 40 and 0.45 -> 0.59 at 75, and is "
        f"unchanged at 0.30 for ability 99; worst cases 1.58 -> 2.54. All far inside the 8 rev/s cap, so the two compose "
        f"without saturating. "
        f"(8) shots (action id 0xa) that pass the 0x14401b379-b398 checks have c3 remapped to 0.25*c3 + 0.75 at 0x14401b39a "
        f"BEFORE the hook, and all shots get their three sigma factors halved at 0x14401b338. The cave applies after both. "
        f"WHERE THIS SITS IN THE EXE - it is NOT 'linker padding'. {entry:#x} is the empty body of the FOURTH 0x60-byte "
        f"record of an anti-tamper trampoline pool starting at 0x1438b4710 (stride 0x60; records 1-3 at 0x1438b4710 / "
        f"0x1438b4770 / 0x1438b47d0 each open with a live 5-byte jmp into .impdata followed by 43-46 bytes of relocated "
        f"branch data). The cave begins 5 bytes after record 4's own live 'jmp 0x15272c020', and .impdata carries "
        f"characteristics 0x60000020 - CODE | EXECUTE | READ, i.e. the protector's own executable region. No unwind data "
        f"covers that span. Nothing in the image references the run - no 64-bit pointer, no RVA, no direct branch, and both "
        f"of the builder's indirect jumps are fully enumerated MSVC switch tables (0x14401b868/0x14401b878 and "
        f"0x14401b948/0x14401b954) whose targets all lie inside the builder - so the CORRECTNESS case is clean. It is the "
        f"TAMPER-DETECTION case that is untested: writing 70 bytes into a live protector pool slot is a different bet from "
        f"writing into ordinary alignment padding, and Denuvo's reaction to it is unknown. The 44-byte run at 0x1438b4804 "
        f"is the tail of record 3 and carries exactly the same caveat. Per the backup metadata this same run was "
        f"previously WRITTEN by the retired slice-cave-v2 / cave-axis-fix / test-spin specs; none of them is present now "
        f"(the run is 91 clean int3 bytes on both the installed image and the pristine backup, checked here), and they "
        f"must not be re-applied alongside this spec. The closest thing to real-world evidence either way is "
        f"linked-spin.json: its own 85-byte cave at 0x14105ed1e sits in a region of the same character (an int3 run "
        f"immediately after dense relocated branch data in .xcode) and is ALREADY APPLIED on this exe. If that build "
        f"has been played without incident, that is a precedent for Denuvo tolerating bytes in these gaps - but it is "
        f"the owner's observation to make, not something measured here. "
        f"NOT PROVEN / EMULATION ONLY: "
        f"(a) nothing at all has been observed in a running match; "
        f"(b) the world these numbers come from is synthetic - a zeroed player object, with most object getters inside the "
        f"factor functions stubbed - so the stock baseline is this harness's best reconstruction of a standing unpressured "
        f"kick, not a capture from a real one; "
        f"(c) every degree/cm figure is measured through the type-4 consumer 0x14401a060, which is what the builder selects "
        f"by default (out+0x34 = 4 at 0x14401a937). Miss types 1 and 3 (set at 0x14401b5fd / 0x14401b7be) are consumed by "
        f"0x144019e40 instead, which reads the same three triples but applies its own formula and was NOT emulated: the "
        f"mechanism covers them, the numbers do not; "
        f"(d) struct+0x38 is a DETERMINISTIC floor, not a draw - the randomiser computes dev = ceil*(w + (1-w)*random) at "
        f"0x14401a115..0x14401a13d. Everything here is measured with w = 0, which is what the builder writes at "
        f"0x14401a991; only 0x14401e5b0 (called at 0x14401b5d5) can make it non-zero and whether it ever does in a real "
        f"match is unknown. If it does, the cave multiplies a certainty rather than a probability - at w = 0.2 every 20 m "
        f"pass from a 40-rated player would be at least ~70 cm off before any dice are rolled; "
        f"(e) the D values quoted in (5) are injected at 0x14401c1fc, not reached naturally, and D's real scale is undecoded; "
        f"(f) the ability -> f map is the game's own 0x143ed71d0 with the inner selector 0x143ed7440 stubbed to a chosen "
        f"integer; the mapping from on-screen stats to that integer is taken from the existing docs, not re-derived here. "
        f"ROLLBACK: python tools/exe_patch.py remove <this file>. IMPORTANT: exe_patch's remove compares the file against "
        f"this spec's 'patch' bytes and aborts if they differ, so if you hand-edit the K or gain immediates at the "
        f"addresses listed under tunables, remove will REFUSE - and the only tool left is restore, which reverts the exe to "
        f"pristine and therefore also discards technique-realism, scuff-wobble and linked-spin. Change the gain by "
        f"regenerating this spec (python tools/emu_kickerror.py --tiredness none --gain <g> --write-spec), not by editing "
        f"bytes; if you have already hand-edited, edit the 'patch' hex in this JSON to match before running remove. "
        f"Authored only - NOT applied, never run in-game.")
    doc = dict(description=desc,
               status="authored, not applied, never run in-game. Mechanics proven by emulation (emu_kickerror.py "
                      "--tiredness none: S1-S14 pass, exe_patch --dry-run passes). CALIBRATION REVISED after review: "
                      "an earlier revision claimed the stock unpressured ceilings were zero and shipped gain 0.35 on "
                      "that basis; both were wrong. The stock baseline is now measured with the factor functions "
                      "executing (S11b) and the gain is derived from the game's own light-pressure error (S13). "
                      "The one thing the owner must consciously accept is interaction (3), the forced-exact kicks.",
               axes=axes, tunables=tun, patches=patches)
    spec_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"\nspec written: {spec_path}")
    for kx, v in tun.items():
        print(f"  tunable {kx}: {v}")
    return spec_path


def write_spec(img, parts, k, gain, wf, axes):
    spec_path = SPEC if wf is None else SPEC.with_name("cave-fatigue-weakfoot.json")
    patches = []
    for n, (va, maxlen, b) in enumerate(parts):
        patches.append(dict(name=f"{spec_path.stem} body part {n + 1} ({len(b)} B in {maxlen} B int3 padding)",
                            va=f"{va:#x}", expect="cc" * len(b), patch=b.hex(), kind="code"))
    entry = parts[0][0]
    patches.append(dict(name=f"{spec_path.stem} hook (replaces 'movss xmm3,[4.25f]' with jmp {entry:#x} + 3-byte nop)",
                        va=f"{HOOK:#x}", expect=STOLEN.hex(), patch=hook_bytes(entry).hex(), kind="code"))
    code1 = parts[0][2]
    gimm = gain if wf is None else gain / 100.0
    k_at = find_imm(code1, entry, f2i(k))
    g_at = find_imm(code1, entry, f2i(gimm), 1 if f2i(gimm) == f2i(k) else 0)
    tun = {"K": dict(va=f"{k_at:#x}", bytes=4, encoding="float32 LE", value=k,
                     meaning="Gaussian sigma scale in sigma = max(0.1, 0.75 + K*(1-s)^2); stock 4.25; 6.0 == error-sigma.json. "
                             "Applies to EVERY kick, exertion or not."),
           "gain": dict(va=f"{g_at:#x}", bytes=4, encoding="float32 LE", value=gimm,
                        meaning=("gain: S = clamp01(1 - gain*(meter/100)*(1-f)). Useful range 0.2 (barely visible) .. 1.0 (strong); "
                                 "values above 1 only saturate (S is floored at 0)." if wf is None else
                                 "gain/100 (meter units folded in): S = clamp01(1 - (gain/100)*max(meter, WF)*(1-f))"))}
    if wf is not None:
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        md.detail = True
        mx = next(i for i in md.disasm(parts[1][2], parts[1][0]) if i.mnemonic == "maxss" and "rip" in i.op_str)
        tun["WF floor"] = dict(va=f"{mx.address + mx.disp_offset:#x}", bytes=4, encoding="disp32 re-aim (rip-relative)",
                               value=wf, next_ip=f"{mx.address + mx.size:#x}",
                               meaning="weak-foot kick counts as at least this much exertion (meter units 0..100); "
                                       "re-aim at another pool float: " + ", ".join(f"{v:g}f={c:#x}" for v, c in WF_CELLS.items()))
    axn = ", ".join(f"{AXIS_REG[a][1]} ({AXIS_REG[a][0]})" for a in "hvp" if a in axes)
    _, HC, VC, PC = site_consts(img)
    eff = "; ".join(f"f={f:g}: {(1 - model_S(gain, 100.0, f, wf_floor=wf)) * VC:.2f} deg / {(1 - model_S(gain, 100.0, f, wf_floor=wf)) * PC * 100:.1f}%"
                    for f in (0.1, 0.5, 0.7, 0.9))
    status = ("MECHANICS PROVEN BY EMULATION (tools/emu_kickerror.py S1-S10 all pass on the pristine image; exe_patch --dry-run passes); "
              "NEVER RUN IN-GAME. NOT A FATIGUE LAYER: match-long stamina was NOT located, so the requested tiredness cause is "
              "NOT READY - this spec only delivers sprint-exertion error.")
    desc = (
        f"SPRINT-EXERTION{' + WEAK FOOT' if wf is not None else ''} -> kick error on: {axn} (code cave). STATUS: {status} "
        f"WHAT THE INPUT REALLY IS (S10, the game's own updater emulated): [player+0x30f4] is a 0..100 SPRINT-EXERTION meter. It rises "
        f"(40/s) only while the player is in action id 4/5/6 (very probably on-ball sprint-dribbling; the names are unproven) above the "
        f"speed gate (17.5 km/h stock), fills in 2.5 s, is back to 0 within 0.5 s of slowing down, never rises in any other action, and is "
        f"the same in minute 1 and minute 90. It is NOT tiredness. "
        f"WHAT THE STOCK GAME ALREADY DOES WITH IT (S9): factor function 0x14401bdb0 (0x14401c143) multiplies the HORIZONTAL c by "
        f"1 - clamp(0.1+0.6(1-f))*ramp, i.e. a full meter already gives a 14.4 deg (f=0.1) / 6.3 deg (f=0.7) horizontal ceiling on the "
        f"stock exe; the five other readers are mishit-TYPE odds after the hook. The stock game has NO meter term on the vertical or "
        f"power c - that gap is what this cave fills{'' if 'h' not in axes else ' (this build ALSO scales the horizontal c, stacking on the stock term)'}. "
        f"MECHANISM: hooks the kick-miss builder 0x14401a900 at {HOOK:#x} (the 8-byte 'movss xmm3,[rip->4.25f]' sigma-K load), jumps to "
        f"int3 padding at {entry:#x}, computes S = max(0, min(1, 1 - gain*t*(1-f))), t = meter/100"
        + (f" (or max(meter, {wf:g})/100 when the kick is with the weaker foot - the game's own rule (attr 0x35 == 0) == [player+0x2bf6], "
           f"read inline; this floor is a DESIGN CHOICE, and f already contains the game's weak-foot ability penalty)" if wf is not None else "")
        + f", f = ability factor [rsp+0x40], multiplies {axn} by S, sets xmm3 = K from an immediate, returns to {HOOK_RET:#x}. No calls, no "
        f"stack, no memory writes; clobbers only rax/xmm0/xmm2/xmm5 (dead there) - flags too in the weak-foot variant (dead). S is "
        f"clamped on BOTH sides and the clamp is NaN-safe, so a corrupt meter, f<0 or gain>1 can at worst zero a c (= the game's own "
        f"full ceiling), never exceed it (S4/S5 hostile-input rows). With the meter at 0"
        + (" and the stronger foot" if wf is not None else "")
        + f" every c is BIT-identical to stock. "
        f"EFFECT at the defaults (K={k}, gain={gain}), clean kick, meter 100, on the STOCK ceilings (V {VC:g} deg, power {PC * 100:.0f}%) - "
        f"vertical ceiling / power ceiling: {eff}. The real randomiser draws about 0.17 x the ceiling on average for a clean kick "
        f"(sigma stays 0.75; exertion does not widen it). "
        f"INTERACTIONS - read before applying: (1) this spec OCCUPIES {HOOK:#x} and sets K={k} itself for EVERY kick, so applying it "
        f"INCLUDES the error-sigma.json change (4.25 -> 6) and is mutually exclusive with error-sigma.json / slices-scuffs 'E' / "
        f"loose-realism gauss-sigma (exe_patch refuses the second on the expect bytes); regenerate with --k 4.25 to leave sigma stock. "
        f"(2) technique-realism.json (currently APPLIED on the live exe) lowers the meter gate 17.5 -> 11 km/h: the meter then fills "
        f"from jogging (13 /s at 14 km/h) and ball-carriers are near full meter most of the time, so this error lands on most moving "
        f"kicks - halve the gain if that is too much. (3) scuff-wobble.json (APPLIED live) makes the vertical ceiling 30 deg, and "
        f"error-spread.json makes horizontal 30 deg / power 40%: multiply the numbers above by 1.33 on those builds. (4) shots that "
        f"pass the 0x14401b379-b398 checks have c3 remapped to 0.25*c3+0.75 BEFORE the hook; S is applied after that remap. "
        + ("(5) kicks the game forces horizontally exact (predicate 0x143edf000, meaning unknown) still get the horizontal term here. "
           if "h" in axes else
           "(5) the horizontal c (xmm1) is never touched, so kicks the game forces horizontally exact (predicate 0x143edf000) stay exact. ")
        + f"(6) the assisted-pass flag [player+0x362c]&1 still zeroes HORIZONTAL error in the randomiser; vertical/power are unaffected by it. "
        + ("MUTUALLY EXCLUSIVE with cave-fatigue.json (same hook and padding). " if wf is not None else
           "MUTUALLY EXCLUSIVE with cave-fatigue-weakfoot.json (same hook and padding). ")
        + "NOT PROVEN: anything in-game; Denuvo's tolerance of bytes at this padding (0x1438b4835 was previously WRITTEN by the retired "
          "slice-cave-v2 / cave-axis-fix / test-spin specs per the backup metadata - those must not be present; whether they executed "
          "there is unknown; the cave has no unwind entry, which matters only if it faults, and its only faultable reads are "
          "[rdi+0x30f4], which the game reads off the same pointer, and [rsp+0x40]"
        + (", plus the weak-foot chain [[0x1486bd888]+idx*0x58+0x55a8]+0x3c9, which the game's ATTR_get dereferences earlier in the same call"
           if wf is not None else "")
        + "); that no callee writes [rsp+0x40] is shown statically plus by call-stubbed emulation of the five factor functions, not "
          "exhaustively - worst case the cave reads the same f the builder itself re-reads at 0x14401b72f. "
          "ROLLBACK: python tools/exe_patch.py remove <this file>. Authored only - not applied.")
    doc = dict(description=desc, status="not-run-in-game; NOT the fatigue layer (stamina not located)", axes=axes, tunables=tun, patches=patches)
    spec_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"\nspec written: {spec_path}")
    for kx, v in tun.items():
        print(f"  tunable {kx}: {v}")
    return spec_path


def verify_spec(img, spec_path):
    """Independent read-back: disassemble the bytes IN THE SPEC FILE and check every control transfer."""
    print(f"\n== spec read-back: {spec_path.name} ==")
    d = json.loads(spec_path.read_text(encoding="utf-8"))
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    ok = True
    regions = [(int(p["va"], 16), bytes.fromhex(p["patch"])) for p in d["patches"]]
    inside = lambda t: any(va <= t < va + len(b) for va, b in regions)
    for p in d["patches"]:
        va, b = int(p["va"], 16), bytes.fromhex(p["patch"])
        on_disk = img.read(va - img.base, len(b))
        exp_ok = on_disk == bytes.fromhex(p["expect"])
        ok &= exp_ok
        print(f"  {p['name']}\n    expect matches image: {exp_ok}")
        n = 0
        for i in md.disasm(b, va):
            n += i.size
            note = ""
            if i.mnemonic.startswith("j"):
                t = i.operands[0].imm
                good = t == HOOK_RET or inside(t)
                ok &= good
                note = f"   -> {'return to builder' if t == HOOK_RET else 'inside cave' if inside(t) else 'BAD TARGET'}"
            elif i.disp_offset and "rip" in i.op_str:
                t = i.address + i.size + i.disp
                sec = next((nm for nm, sva, vs, _, _ in img.secs if sva <= t - img.base < sva + vs), "?")
                note = f"   -> {t:#x} [{sec}]"
                if i.mnemonic in ("mulss", "maxss"):
                    note += f" = {struct.unpack('<f', img.read(t - img.base, 4))[0]}f"
            print(f"      {i.address:#x}  {i.bytes.hex():<22s} {i.mnemonic} {i.op_str}{note}")
            if i.mnemonic == "jmp" and i.operands[0].imm == HOOK_RET:
                break
        if va != HOOK:
            ok &= n == len(b)
    print(f"  read-back {'PASS' if ok else 'FAIL'}")
    return ok


DEFAULTS = {"meter": dict(k=6.0, gain=0.5, axes="vp"),      # cave-fatigue.json      (unchanged)
            "none":  dict(k=4.25, gain=0.10, axes="hvp")}   # cave-ability-error.json (K = STOCK on purpose)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiredness", default="meter", choices=["meter", "none"],
                    help="what drives the error besides ability. 'meter' = the sprint-exertion build (cave-fatigue.json, "
                         "the historical default). 'none' = the ABILITY-BASELINE build (cave-ability-error.json): "
                         "S = clamp01(1 - gain*(1-f)), no situational input at all.")
    ap.add_argument("--ability-only", dest="tiredness", action="store_const", const="none",
                    help="alias for --tiredness none")
    ap.add_argument("--k", type=float, default=None, help="Gaussian sigma scale the cave materialises (stock 4.25; 6.0 = "
                                                          "error-sigma.json). Default 6.0 for --tiredness meter, 4.25 (STOCK) for none")
    ap.add_argument("--gain", type=float, default=None, help="meter build: S = 1 - gain*(meter/100)*(1-f).  ability build: "
                                                             "S = 1 - gain*(1-f).  Any value is safe (S is clamped to 0..1)")
    ap.add_argument("--axes", default=None, choices=["vp", "hvp", "v", "p", "hv", "hp", "h"],
                    help="which cleanliness factors S scales: h=xmm1 horizontal, v=xmm12 vertical, p=xmm6 power.  Default vp for "
                         "the meter build (the stock game already applies that meter to the horizontal axis: S9), hvp for the "
                         "ability build (no stock ability term on any axis: S11)")
    ap.add_argument("--wf", type=float, default=None, choices=sorted(WF_CELLS), help="weak-foot exertion floor in METER units (builds the two-part variant)")
    ap.add_argument("--mc", type=int, default=400, help="Monte Carlo draws per row in S12/S13 (ability build only)")
    ap.add_argument("--write-spec", action="store_true")
    ap.add_argument("--exe", default=None, help="image to emulate (default: the PRISTINE backup if present, else the live exe)")
    a = ap.parse_args()
    d = DEFAULTS[a.tiredness]
    if a.k is None:
        a.k = d["k"]
    if a.gain is None:
        a.gain = d["gain"]
    if a.axes is None:
        a.axes = d["axes"]
    if a.tiredness == "none" and a.wf is not None:
        sys.exit("--wf needs the exertion meter; it is meaningless with --tiredness none")
    pristine = Path.home() / "Backups" / "eFootball" / "eFootball.exe.PRISTINE"
    src = Path(a.exe) if a.exe else (pristine if pristine.exists() else EXE)
    print(f"emulating image: {src}  (opened read-only)")
    print(f"build: --tiredness {a.tiredness}   K={a.k}  gain={a.gain}  axes={a.axes}  wf={a.wf}")
    img = Image(src)
    live = None
    if src != EXE and EXE.exists():
        live = Image(EXE)
        okl = live.read(HOOK - live.base, 8) == STOLEN and all(
            live.read(va - live.base, n) == bytes([0xCC]) * n for va, n in ((CAVE_A, CAVE_A_LEN), (CAVE_B, CAVE_B_LEN)))
        print(f"live exe {EXE.name}: hook bytes stock + both cave paddings all int3: {okl}")
        # site_consts() re-derives the constants by disassembling the hook, so it only works while the
        # hook still holds the stock RIP-relative load. Once a cave of ours is installed the hook is a
        # jmp with no memory operand and lea_target() returns None. Report what we can instead of dying:
        # the proofs themselves run against `img` (the pristine image), which is unaffected.
        if okl:
            print(f"live exe constants (K, Hceil, Vceil, Prate) = {site_consts(live)}   pristine = {site_consts(img)}")
        else:
            # The live image is only useful here as a STOCK cross-reference. Once one of our caves is
            # installed its hook is a jmp with no memory operand, so every site_consts(live) downstream
            # would crash. Drop it: the proofs all run against `img` (pristine) and are unaffected.
            print(f"live exe constants: SKIPPED - a cave is already installed at the hook, so the live "
                  f"image cannot be used as a stock reference. pristine = {site_consts(img)}")
            print("  (expected when regenerating a spec while the previous build is still applied;"
                  " remove the old spec before applying the new one)")
            live = None
    parts = assemble(cave_source(a.k, a.gain, a.wf, a.axes, a.tiredness))
    res = [s1_static(img, parts), s2_builder(img), s2b_f_slot(img), s3_region(img)]
    res.append(callee_scratch_check(img))
    res += [s4_cave(img, parts, a.k, a.gain, a.wf, a.axes, a.tiredness),
            s5_end_to_end(img, a.k, a.gain, a.wf, a.axes, a.tiredness), s6_ranges(img),
            s7_weakfoot(img, a.k, a.gain, a.wf, a.axes), s8_stamina_lead(img),
            s9_stock_meter(img, live, a.k, a.gain, a.wf, a.axes, a.tiredness), s10_meter_nature(img, live)]
    mc_rows = None
    if a.tiredness == "none":
        res.append(s11_no_stock_ability_baseline(img))
        mc_img = live if live is not None else img            # the numbers the owner will actually get
        res.append(s11b_real_stock_baseline(mc_img))
        print(f"\n(the S12/S13 numbers below are measured on the image the owner patches: "
              f"{'LIVE ' + EXE.name if live is not None else src.name})")
        ok12, mc_rows = s12_montecarlo(mc_img, a.k, a.gain, a.axes, n=a.mc)
        res.append(ok12)
        ok13, gain_tbl = s13_gain_choice(mc_img, a.axes, n=max(100, a.mc // 2))
        res.append(ok13)
        res.append(s13b_squad(mc_img, a.k, a.gain, a.axes, n=max(100, a.mc // 2)))
        res.append(s14_behaviour_changes(mc_img, a.k, a.gain, a.axes, n=max(100, a.mc // 2)))
    print("\nRESULT:", "ALL PASS" if all(res) else f"FAILURES {res}")
    if a.write_spec:
        if not all(res):
            sys.exit("refusing to write a spec while a proof fails")
        if a.tiredness == "none":
            sp = write_spec_ability(img, live, parts, a.k, a.gain, a.axes, mc_rows, gain_tbl)
        else:
            sp = write_spec(img, parts, a.k, a.gain, a.wf, a.axes)
        expect_img = live if (a.tiredness == "none" and live is not None) else img
        if not verify_spec(expect_img, sp):
            sys.exit("spec read-back failed")
    return 0 if all(res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
