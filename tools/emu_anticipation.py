#!/usr/bin/env python3
"""
emu_anticipation.py — ABILITY-SCALED DEFENSIVE ANTICIPATION code cave (design + Unicorn proof).

Nothing here touches the game.  Both images are opened READ-ONLY (mmap ACCESS_READ), their pages
are lazily copied into a Unicorn address space, and the hook + cave bytes are overlaid IN THE
EMULATOR ONLY.  --write-spec writes a JSON spec into the repo; applying it is a separate,
deliberate `exe_patch.py apply` that the owner runs with the game closed.

    python tools/emu_anticipation.py                 # every proof, every table
    python tools/emu_anticipation.py --gain 1.5 --pivot 70
    python tools/emu_anticipation.py --sweep         # + the GAIN sweep that justifies the default
    python tools/emu_anticipation.py --write-spec    # + tools/data/patches/anticipation-ability.json

--------------------------------------------------------------------------------------------------
WHAT THE SITE ACTUALLY IS  (this corrects the brief, and follows the predict:semantics finding)
--------------------------------------------------------------------------------------------------
0x143da63b0 is not a "prediction horizon" function.  It is the AI gait (movement-urgency) chooser's
"ease off while the ball is in flight" rule, called once per player per tick from the vf13 slot of
every move-type Action.  Its shape, from the real bytes:

    ebx  = frames for the ball to reach the team reference point  (0x143da64cd..0x143da650e,
           inflated 1/0.6 = 1.67x; 10000 if the ball is not moving; 0 if it is within 1.2 m)
    edi  = basePosition.marginPredictionFrameBase   [r12+0x240]          (dt270, currently 0)
           - (int)(marginPredictionFrameAdjust * -0.0f)                  (DEAD: always 0)
           + ebx
    loop: candidate = gait - 1
          margin = (candidate <= minGait) ? 0 : (int)(fps*0.6 + 0.5)     ( = 36 at 60 fps )
          arrival = 0x143e54f70(... candidate ...)                       (frames to reach the spot)
          if (arrival >= margin + edi) stop;  else accept candidate and keep stepping down

So edi is a TIME BUDGET: "ease off to the slowest gait that still gets you there before the ball
does".  Raising edi makes a player coast sooner; LOWERING it makes him keep running.  The brief's
proposed sign is therefore backwards, and this module inverts it:

    delta = clamp(attr, 0, ATTR_CAP) - PIVOT, scaled by GAIN   ->   edi -= delta

    elite defender  -> POSITIVE delta -> smaller budget -> demands to arrive EARLIER than the ball
                       -> refuses to downshift -> stays with the runner
    poor defender   -> NEGATIVE delta -> bigger budget  -> allows himself to arrive later
                       -> coasts while the pass travels -> men run off him

That is the owner's complaint expressed in the game's own arithmetic, and the multiply it replaces
is provably dead (S2), so at attr == PIVOT the patched image is bit-identical to stock (S7).

ATTRIBUTE: match ability array index 0x15 = DATA_PARAMETER_DEFENSE_DECISION = Defensive Awareness
("reads the game").  That is the attr:index finding (enum registrar emulated + range-table pinned),
NOT docs/exe-gameplay-map.md line 47, which is off by one — see S3.

Sections (each prints its own numbers):
  S1  static: the 16 stolen bytes decode exactly, installed == pristine there, the literal is -0.0f,
      nothing in the image branches into the stolen window, the neighbourhood is unpatched.
  S2  deadness: the real 44-byte block run under Unicorn for hostile marginPredictionFrameAdjust.
  S3  attribute: the game's own range getters + the inline byte read == the game's ATTR_get chain.
  S4  the cave's only call (0x1442d6ef0): full register/flag/xmm/memory footprint, rcx-deadness.
  S5  cave standalone: register diff, memory-write watch, rsp/flags, attr -> delta table.
  S6  end-to-end: stock path vs hook->cave->return, edi for 40..99 and for hostile inputs.
  S7  identity at the pivot: every register bit-identical to stock.
  S8  clamps: hostile attribute and hostile dt270 base cannot push edi out of the safe band, and
      'lea ecx,[rbx+rdi]' cannot overflow.
  S9  BEHAVIOUR: the game's OWN decision loop emulated, stock vs patched, for 40..99 -> accepted gait.
  S10 layout: the payload laid across real int3 caves by tools/cave_alloc.py, chained with jmp rel32,
      re-proved through the chain (S5/S6 repeated on the chunked bytes).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capstone
from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_PROT_ALL, UC_HOOK_CODE, UC_HOOK_MEM_WRITE,
                     UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_HOOK_MEM_FETCH_UNMAPPED, UcError)
from unicorn import x86_const as X

import cave_alloc
from cave_alloc import Refuse

REPO = Path(__file__).resolve().parent.parent
EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
PRISTINE = Path.home() / "Backups" / "eFootball" / "eFootball.exe.PRISTINE"
SPEC = REPO / "tools" / "data" / "patches" / "anticipation-ability.json"
BASE = 0x140000000

# ---------------------------------------------------------------------------------- the site
FUNC = 0x143DA63B0                 # the gait "ease off while the ball is in flight" refiner
REGION = 0x143DA6529               # movd xmm0,[r12+0x23c]   (start of the dead block)
HOOK = 0x143DA6545                 # mulss xmm0,[rip -> -0.0f]
STOLEN_LEN = 16                    # mulss(8) cvttss2si(4) sub edi,eax(2) add edi,ebx(2)
HOOK_RET = 0x143DA6555             # call 0x1442d6ef0
STOLEN = bytes.fromhex("f30f5905eb9faa03f30f2cc02bf803fb")
NEG_ZERO_CELL = 0x147850538        # the -0.0f multiplier that kills the adjust term
SIXTENTHS_CELL = 0x147850258       # 0.6f — the ball-frame inflation AND the loop's hysteresis
LOOP_ENTRY = 0x143DA6562           # mov ecx,[r14]
LOOP_DONE = 0x143DA6618

ENTITY_TO_DATA = 0x1442D6EF0       # (rcx dead, edx = entity index) -> player DATA object
ENTITY_TO_MATCH = 0x1442D6F60      # the OTHER lookup (+0x4058) — r13 in this function, NOT ours
ATTR_CHAIN = 0x1442DD650           # the game's own (_, entityIdx, attrIdx) -> attribute byte
ATTR_GET = 0x143EA8CB0             # the general ATTR_get(matchPlayer, idx)
ATTR_ARRAY = 0x394                 # player data object + 0x394 = the 61-byte attribute table
RANGE_FIELD = 0x1442BFAE0          # (min*, max*, idx) field range
FPS_FN = 0x14533EA80               # movss xmm0,[0x148c22abc]
FPS_CELL = 0x148C22ABC
ARRIVAL_FN = 0x143E54F70           # arrival time in frames for a candidate gait
G_CONTAINER = 0x1486BD888          # global entity container root

ATTR_DEF_AWARE = 0x15              # DATA_PARAMETER_DEFENSE_DECISION  (= enum 0x0e + 7)
ATTR_CAP = 120                     # the game's own level-up cap for a 40..99 ability (range table)
EDI_LIMIT = 4_000_000              # hard band on the final budget (see S8)

# ------------------------------------------------------------------------------ emulator map
STACK = 0x7FF000000000
STACK_SZ = 0x200000
HEAP = 0x200000000
HEAP_SZ = 0x100000
RET_MAGIC = 0x00001000             # a mapped 'hlt' page used as the return address of a call

CONTAINER = HEAP + 0x10000
DATAOBJ = HEAP + 0x20000
MATCHOBJ = HEAP + 0x28000
CONSTS = HEAP + 0x30000            # the basePosition constant object (r12)
CTX = HEAP + 0x40000               # the ai context (rbp)
GAIT = HEAP + 0x50000              # r14
TARGETV = HEAP + 0x58000           # r15
ENTITY = 7

GPR = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in
       "rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15".split()}
XMM = {f"xmm{i}": getattr(X, f"UC_X86_REG_XMM{i}") for i in range(16)}
MARK = {"rax": 0xA1A1A1A1A1A1A1A1, "rbx": 0xB2B2B2B2B2B2B2B2, "rcx": 0xC3C3C3C3C3C3C3C3,
        "rdx": 0xD4D4D4D4D4D4D4D4, "rsi": 0x5151515151515151, "r8": 0x8888888888888888,
        "r9": 0x9999999999999999, "r10": 0xAAAAAAAAAAAAAAAA, "r11": 0xBBBBBBBBBBBBBBBB}


def f2i(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", v))[0]


def i2f(v: int) -> float:
    return struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


# ==================================================================================== payload
def cave_source(gain: float, pivot: int, attr_idx: int = ATTR_DEF_AWARE,
                attr_cap: int = ATTR_CAP, edi_limit: int = EDI_LIMIT, guarded: bool = True) -> str:
    """The cave, one instruction per line — the SINGLE SOURCE OF TRUTH for the emulation, the
    layout and the spec.  `$NAME` is an external VA, `@name` a label (there are none: the payload
    is branch-free), and there is no rip-relative operand at all.

    Registers written: rax, rcx, edx (reloaded), edi (the budget), flags.  rdi's incoming value is
    the dt270 base; rbx (ball frames) and rbp (ai ctx) are read and never written.  Everything else
    is preserved by the Win64 ABI across the one call, which is a 7-instruction pure leaf (S4).

    GAIN is fixed point Q8 (frames per attribute point x 256) so the whole payload is integer:
    delta = ((min(attr, CAP) - PIVOT) * GAIN_Q8) >> 8      (arithmetic shift = floor)
    """
    q8 = int(round(gain * 256))
    if not (1 <= q8 <= 0x7FFFFFFF):
        raise SystemExit(f"gain {gain} out of range")
    if q8 <= 127:
        raise SystemExit(f"gain {gain} (Q8 {q8}) would let keystone pick the imm8 form of imul — "
                         f"the GAIN tunable cell must stay 4 bytes; use >= 0.5")
    tail = ("""
        sub    edi, eax                             ; edi = base - delta          (was 'sub edi,eax')
        add    edi, ebx                             ; edi += ball frames          (was 'add edi,ebx')
        mov    ecx, {lim}                           ; hard band on the final budget
        cmp    edi, ecx
        cmovg  edi, ecx
        neg    ecx
        cmp    edi, ecx
        cmovl  edi, ecx""".format(lim=edi_limit) if guarded else "")
    return """
        mov    edx, dword ptr [rbp + 4]             ; entity index (the value the stolen tail uses)
        call   $ENTITY_TO_DATA                      ; rax = player data object (pure leaf, S4)
        movzx  eax, byte ptr [rax + {slot}]         ; attribute[{idx:#04x}] Defensive Awareness
        mov    ecx, {cap}                           ; ATTR_CAP
        cmp    eax, ecx
        cmovg  eax, ecx                             ; attr = min(attr, CAP)   (hostile byte -> bounded)
        mov    ecx, {pivot}                         ; PIVOT      <- tunable cell
        sub    eax, ecx
        imul   eax, eax, {q8}                       ; GAIN Q8    <- tunable cell
        sar    eax, 8                               ; delta = floor((attr-PIVOT)*GAIN){tail}
        mov    edx, dword ptr [rbp + 4]             ; restore the call args the stolen tail needs
        mov    rcx, qword ptr [rbp + 0x30]
        jmp    $HOOK_RET
""".format(slot=hex(ATTR_ARRAY + attr_idx), idx=attr_idx, cap=attr_cap, pivot=pivot, q8=q8, tail=tail)


def delta_model(attr: int, gain: float, pivot: int, attr_cap: int = ATTR_CAP) -> int:
    """Independent python model of the payload's arithmetic (32-bit, floor shift)."""
    q8 = int(round(gain * 256))
    a = min(attr & 0xFF, attr_cap)
    return s32((a - pivot) * q8) >> 8


# ================================================================================== emulator
class Emu:
    """Lazy page-faulting Unicorn view of a PE image, plus overlays and call stubs."""

    def __init__(self, img: cave_alloc.Image, overlays: list[tuple[int, bytes]] = ()):
        self.img = img
        self.span = (img.base, img.base + max(s["rva"] + s["vsize"] for s in img.sections))
        self.faults: list[tuple[int, int]] = []
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped: set[int] = set()
        self.overlays = list(overlays)
        self.writes: list[tuple[int, int, int]] = []
        self.stubs: dict[int, callable] = {}
        self.probes: dict[int, callable] = {}
        self.trace: list[int] = []
        self.uc.mem_map(STACK, STACK_SZ, UC_PROT_ALL)
        self.uc.mem_map(HEAP, HEAP_SZ, UC_PROT_ALL)
        self.uc.mem_map(RET_MAGIC & ~0xFFF, 0x1000, UC_PROT_ALL)
        self.uc.mem_write(RET_MAGIC, b"\xf4")                        # hlt = "the call returned"
        # SSE must be enabled or every movss faults
        self.uc.reg_write(X.UC_X86_REG_CR0, (self.uc.reg_read(X.UC_X86_REG_CR0) & ~4) | 2)
        self.uc.reg_write(X.UC_X86_REG_CR4, self.uc.reg_read(X.UC_X86_REG_CR4) | 0x600)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._on_write)
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)
        for h in (UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED):
            self.uc.hook_add(h, self._on_fault)

    # ---- memory
    def ensure(self, va: int, n: int = 0x40):
        lo, hi = va & ~0xFFF, (va + n + 0xFFF) & ~0xFFF
        for p in range(lo, hi, 0x1000):
            if p in self.mapped:
                continue
            self.uc.mem_map(p, 0x1000, UC_PROT_ALL)
            try:
                b = self.img.read_va(p, 0x1000)
                if b:
                    self.uc.mem_write(p, b)
            except Exception:
                pass                                              # not file-backed: leave it zero
            self.mapped.add(p)
        for va_o, b in self.overlays:                                 # re-apply after a fresh map
            if lo <= va_o < hi or lo < va_o + len(b) <= hi:
                self.uc.mem_write(va_o, b)

    def _on_fault(self, uc, access, address, size, value, user):
        self.faults.append((address, size))
        if self.span[0] <= address < self.span[1]:
            self.ensure(address, size)
            return True
        return False

    def _on_write(self, uc, access, address, size, value, user):
        if not (STACK <= address < STACK + STACK_SZ):
            self.writes.append((address, size, value))

    def _on_code(self, uc, address, size, user):
        self.trace.append(address)
        p = self.probes.get(address)
        if p is not None:
            p(uc)
        fn = self.stubs.get(address)
        if fn is not None:
            fn(uc)
            sp = uc.reg_read(X.UC_X86_REG_RSP)
            ret = struct.unpack("<Q", uc.mem_read(sp, 8))[0]
            uc.reg_write(X.UC_X86_REG_RSP, sp + 8)
            uc.reg_write(X.UC_X86_REG_RIP, ret)

    # ---- world
    def world(self, attr: dict[int, int] | int = 70, adjust: int = 100, base: int = 0,
              fps: float = 60.0):
        """A synthetic but faithful world: the entity container, the player data object with a real
        attribute table, the basePosition constant object, and the ai context."""
        self.ensure(G_CONTAINER, 16)
        self.ensure(FPS_CELL, 16)
        self.uc.mem_write(G_CONTAINER, struct.pack("<Q", CONTAINER))
        self.uc.mem_write(CONTAINER + ENTITY * 0x58 + 0x55A8, struct.pack("<Q", DATAOBJ))
        self.uc.mem_write(CONTAINER + ENTITY * 0x58 + 0x4058, struct.pack("<Q", MATCHOBJ))
        table = bytearray(0x40)
        if isinstance(attr, int):
            for i in range(0x14, 0x31):
                table[i] = attr & 0xFF
        else:
            for i, v in attr.items():
                table[i] = v & 0xFF
        self.uc.mem_write(DATAOBJ + ATTR_ARRAY, bytes(table))
        self.uc.mem_write(CONSTS + 0x23C, struct.pack("<i", adjust))
        self.uc.mem_write(CONSTS + 0x240, struct.pack("<i", base))
        self.uc.mem_write(CTX + 4, struct.pack("<I", ENTITY))
        self.uc.mem_write(CTX + 0x30, struct.pack("<Q", MATCHOBJ))
        self.uc.mem_write(CTX + 0x38, struct.pack("<Q", MATCHOBJ))
        self.uc.mem_write(FPS_CELL, struct.pack("<f", fps))

    def regs(self) -> dict:
        d = {n: self.uc.reg_read(r) for n, r in GPR.items()}
        d.update({n: self.uc.reg_read(r) for n, r in XMM.items()})
        d["eflags"] = self.uc.reg_read(X.UC_X86_REG_EFLAGS) & ~0x10000  # RF is emulator noise
        return d

    def setregs(self, **kw):
        for n, v in kw.items():
            self.uc.reg_write(GPR[n] if n in GPR else XMM[n], v)

    def run(self, start: int, stop: int, count: int = 4000):
        self.ensure(start, 0x200)
        self.ensure(stop, 0x40)
        self.writes.clear()
        self.trace.clear()
        self.uc.emu_start(start, stop, count=count)


def fresh(img, overlays=(), *, attr=70, adjust=100, base=0, fps=60.0, ebx=0, rdi=0) -> Emu:
    e = Emu(img, overlays)
    e.world(attr=attr, adjust=adjust, base=base, fps=fps)
    e.setregs(rsp=STACK + 0x100000, rbp=CTX, r12=CONSTS, r13=MATCHOBJ, r14=GAIT, r15=TARGETV,
              rbx=ebx, rdi=rdi)
    for n, v in MARK.items():
        if n not in ("rbx",):
            e.setregs(**{n: v})
    return e


# ================================================================================== the proofs
def ok(flag: bool) -> str:
    return "PASS" if flag else "*** FAIL ***"


def s1_static(inst, pris) -> bool:
    print("== S1  static: the stolen window, the neighbourhood, and who can reach it")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    cur = inst.read_va(HOOK, STOLEN_LEN)
    good = cur == STOLEN
    print(f"   installed bytes at {HOOK:#x}  {cur.hex()}   == the expected stolen bytes: {good}")
    print(f"   pristine  bytes at {HOOK:#x}  {pris.read_va(HOOK, STOLEN_LEN).hex()}   "
          f"identical: {pris.read_va(HOOK, STOLEN_LEN) == cur}")
    n, last = 0, None
    for ins in md.disasm(cur, HOOK):
        print(f"      {ins.address:#x}  {ins.bytes.hex():<18s} {ins.mnemonic} {ins.op_str}")
        n += ins.size
        last = ins
    boundary = n == STOLEN_LEN and last.address + last.size == HOOK_RET
    print(f"   decode covers exactly {n}/{STOLEN_LEN} B and ends at the return site {HOOK_RET:#x}: {boundary}")
    lit = inst.read_va(NEG_ZERO_CELL, 4)
    neg0 = lit == b"\x00\x00\x00\x80"
    print(f"   multiplier cell {NEG_ZERO_CELL:#x} = {i2f(struct.unpack('<I', lit)[0])!r} (raw {lit.hex()}) "
          f"-> the adjust term is dead: {neg0}")
    same_fn = inst.read_va(FUNC, 0x2AA) == pris.read_va(FUNC, 0x2AA)
    print(f"   whole function {FUNC:#x}+0x2aa identical installed vs pristine (no existing edit "
          f"in it): {same_fn}")
    hits = cave_alloc.refs_into(inst, [(HOOK, HOOK + STOLEN_LEN)])
    print(f"   branch/pointer references INTO the stolen window anywhere in the image: {len(hits)}"
          + ("" if not hits else f"  {hits}"))
    intra = []
    for ins in md.disasm(inst.read_va(FUNC, 0x2AA), FUNC):
        for o in ins.operands:
            if o.type == capstone.x86.X86_OP_IMM and ins.mnemonic[0] == "j":
                if HOOK <= o.imm < HOOK + STOLEN_LEN:
                    intra.append((ins.address, o.imm))
    print(f"   jumps inside {FUNC:#x} that land in the window: {len(intra)}")
    # the cave makes a call, so RSP at the hook must already be call-ready
    body = list(md.disasm(inst.read_va(HOOK, STOLEN_LEN), HOOK))
    nostack = not any("rsp" in i.op_str for i in body)
    print(f"   no stack adjustment between {HOOK:#x} and the stock call at {HOOK_RET:#x}, so RSP at "
          f"the hook is exactly the RSP that call runs on: {nostack}")
    # what the cave is allowed to leave dirty: xmm0 and the flags must be dead at HOOK_RET.
    # Stated carefully — the naive "first mention of xmm0" reading is WRONG here.
    seq = list(md.disasm(inst.read_va(HOOK_RET, 0x52), HOOK_RET))
    first_xmm0 = next(i for i in seq if "xmm0" in i.op_str)
    prev = [i for i in seq if i.address < first_xmm0.address][-1]
    print(f"   first instruction mentioning xmm0 after the hook: {first_xmm0.address:#x} "
          f"{first_xmm0.mnemonic} {first_xmm0.op_str}")
    print(f"      — it READS xmm0, but the instruction before it is {prev.address:#x} "
          f"{prev.mnemonic} {prev.op_str},")
    print(f"        and 0x14533ea80 is 'movss xmm0,[rip+..]; ret' — it writes xmm0 unconditionally.")
    print(f"        The other path out of the loop head writes xmm0 outright "
          f"(0x143da65a7 movss xmm0,[rsp+0xc0]).  S7 proves the deadness by EXECUTION rather than")
    print(f"        by this reading.")
    print(f"   flags: the first flag user after the hook is inside the call at {HOOK_RET:#x} "
          f"(0x1442d6ef0 opens 'cmp edx,0x1f'), i.e. a WRITE before any read — flags are dead too")
    good_all = good and boundary and neg0 and same_fn and not hits and not intra and nostack
    print("   ", ok(good_all))
    return good_all


def s2_deadness(inst) -> bool:
    print("\n== S2  deadness: the real 44 bytes 0x143da6529..0x143da6555, hostile adjust values")
    rows, bad = [], False
    for adj in (-2**31, -1_000_000, -100, -1, 0, 1, 100, 1_000_000, 2**31 - 1):
        e = fresh(inst, attr=70, adjust=adj, base=25, ebx=37)
        e.run(REGION, HOOK_RET)
        eax, edi = e.uc.reg_read(X.UC_X86_REG_EAX), s32(e.uc.reg_read(X.UC_X86_REG_EDI))
        rows.append((adj, eax, edi))
        bad |= (eax != 0 or edi != 25 + 37)
    print("      marginPredictionFrameAdjust        eax      edi (base 25 + ballFrames 37)")
    for adj, eax, edi in rows:
        print(f"      {adj:>14d}   {eax:>8d}   {edi:>8d}")
    print(f"   the multiply-by--0.0 term is 0 for every int32 input: {not bad}")
    print("   ", ok(not bad))
    return not bad


def s3_attribute(inst) -> bool:
    print("\n== S3  which attribute: index 0x15 and the inline read")
    e = Emu(inst)
    e.ensure(RANGE_FIELD, 0x80)
    e.ensure(0x146C00860, 0x200)
    OUT = HEAP + 0x60000
    rng = {}
    for idx in (0x14, 0x15, 0x16, 0x17, 0x27, 0x2F, 0x30):
        e.uc.mem_write(OUT, b"\xAA\xAA")
        e.setregs(rsp=STACK + 0x100000)
        sp = STACK + 0x100000
        e.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        e.uc.reg_write(X.UC_X86_REG_RSP, sp)
        e.uc.reg_write(X.UC_X86_REG_RCX, OUT)
        e.uc.reg_write(X.UC_X86_REG_RDX, OUT + 1)
        e.uc.reg_write(X.UC_X86_REG_R8, idx)
        e.uc.emu_start(RANGE_FIELD, RET_MAGIC, count=200)
        rng[idx] = tuple(e.uc.mem_read(OUT, 2))
    print("      the game's own field-range table (0x1442bfae0), which PINS the +7 enum alignment:")
    names = {0x14: "OFFENSE_DECISION", 0x15: "DEFENSE_DECISION", 0x16: "GK_DECISION",
             0x17: "DRIBBLE", 0x27: "R_FOOT_ACC (1-4 stars)", 0x2F: "STABILITY (8 form levels)",
             0x30: "DURABILITY (3 injury levels)"}
    for idx, (lo, hi) in rng.items():
        print(f"      match idx {idx:#04x}  range {lo:3d}..{hi:3d}   = DATA_PARAMETER_{names[idx]}")
    pinned = rng[0x27] == (0, 3) and rng[0x2F] == (0, 7) and rng[0x30] == (0, 2) and rng[0x15] == (40, 99)
    print(f"      0x27/0x2f/0x30 are the 0..3 / 0..7 / 0..2 holes that only the +7 alignment fits: {pinned}")

    # inline byte read == the game's own chain
    e2 = fresh(inst, attr={i: 40 + i for i in range(0x14, 0x31)})
    agree = True
    for idx in (0x14, 0x15, 0x16, 0x20):
        sp = STACK + 0x100000
        e2.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        e2.uc.reg_write(X.UC_X86_REG_RSP, sp)
        e2.uc.reg_write(X.UC_X86_REG_RCX, 0xDEAD0000)          # arg1 poisoned on purpose
        e2.uc.reg_write(X.UC_X86_REG_RDX, ENTITY)
        e2.uc.reg_write(X.UC_X86_REG_R8, idx)
        e2.uc.emu_start(ATTR_CHAIN, RET_MAGIC, count=400)
        game = e2.uc.reg_read(X.UC_X86_REG_RAX) & 0xFF
        inline = e2.uc.mem_read(DATAOBJ + ATTR_ARRAY + idx, 1)[0]
        agree &= game == inline
        print(f"      game chain 0x1442dd650(_, entity {ENTITY}, {idx:#04x}) = {game:3d}   "
              f"inline byte [obj+{ATTR_ARRAY + idx:#x}] = {inline:3d}   equal: {game == inline}")
    print("   ", ok(pinned and agree))
    return pinned and agree


def s4_callee(inst) -> bool:
    print("\n== S4  the cave's only call, 0x1442d6ef0: footprint and rcx-deadness")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    body = inst.read_va(ENTITY_TO_DATA, 0x2C)
    ins = list(md.disasm(body, ENTITY_TO_DATA))
    for i in ins[:10]:
        print(f"      {i.address:#x}  {i.bytes.hex():<16s} {i.mnemonic} {i.op_str}")
        if i.mnemonic == "ret":
            break
    txt = " ".join(i.mnemonic for i in ins[:9])
    no_xmm = not any(m in txt for m in ("movss", "mulss", "movaps", "xmm", "movd"))
    no_call = "call" not in txt
    print(f"      leaf (no call): {no_call}   xmm-free: {no_xmm}")

    res, writes, diffs = [], [], []
    for poison in (0, 0xDEADBEEFDEADBEEF, MATCHOBJ):
        e = fresh(inst, attr=77)
        sp = STACK + 0x100000
        e.uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        e.uc.reg_write(X.UC_X86_REG_RSP, sp)
        e.uc.reg_write(X.UC_X86_REG_RCX, poison)
        e.uc.reg_write(X.UC_X86_REG_RDX, ENTITY)
        e.ensure(ENTITY_TO_DATA, 0x40)
        before = e.regs()                       # captured AFTER the arguments are in place
        e.writes.clear()
        e.uc.emu_start(ENTITY_TO_DATA, RET_MAGIC, count=200)
        after = e.regs()
        res.append(e.uc.reg_read(X.UC_X86_REG_RAX))
        writes.append(list(e.writes))
        changed = sorted(k for k in before if k not in ("rip",) and before[k] != after[k]
                         and k not in ("rcx", "rax", "rsp", "eflags"))
        diffs.append(changed)
    same = len(set(res)) == 1 and res[0] == DATAOBJ
    print(f"      rax for rcx = 0 / garbage / the real ctx: {[hex(r) for r in res]}  -> "
          f"rcx is DEAD and the object is the one at container+idx*0x58+0x55a8: {same}")
    print(f"      registers changed besides rax/rcx/rsp/flags: {diffs[0]}  (edx preserved: "
          f"{'rdx' not in diffs[0]})")
    print(f"      memory writes outside the stack: {writes[0]}")
    good = same and no_call and no_xmm and not diffs[0] and not writes[0]
    print("   ", ok(good))
    return good


def s5_cave(inst, lay, gain, pivot) -> bool:
    print("\n== S5  the cave standalone: register diff, memory watch, attr -> delta")
    overlays = lay.overlays()
    rows, bad = [], False
    touched = set()
    for attr in (0, 1, 40, 50, 55, 60, 70, 80, 90, 99, 120, 200, 255):
        e = fresh(inst, overlays, attr=attr, base=0, ebx=0, rdi=0)
        before = e.regs()
        e.run(lay.entry, HOOK_RET)
        after = e.regs()
        delta = s32(before["rdi"]) - s32(after["rdi"])
        model = delta_model(attr, gain, pivot)
        rows.append((attr, s32(after["rax"]), delta, model))
        bad |= delta != model or s32(after["rax"]) != model
        bad |= before["rsp"] != after["rsp"]
        bad |= bool(e.writes)
        # the stolen tail's own call args must be exactly what the stock code had loaded
        bad |= after["rdx"] != ENTITY or after["rcx"] != MATCHOBJ
        for k in before:
            if before[k] != after[k]:
                touched.add(k)
    print("      attr   eax(delta)   edi change   python model")
    for attr, eax, d, m in rows:
        print(f"      {attr:>4d}   {eax:>10d}   {d:>10d}   {m:>12d}"
              + ("   <- clamped at CAP" if attr > ATTR_CAP else ""))
    print(f"      registers the cave changes: {sorted(touched)}")
    print(f"      on exit rdx == [rbp+4] (entity index) and rcx == [rbp+0x30]: the exact arguments "
          f"the stolen tail's call at {HOOK_RET:#x} needs — checked on every row above")
    expect_touched = {"rax", "rcx", "rdx", "rdi", "rip", "eflags"}
    clean = touched <= expect_touched
    print(f"      that set is inside the permitted {sorted(expect_touched)}: {clean}")
    print(f"      rsp unchanged: True   non-stack memory writes: 0")
    print("      preserved (verified above by absence from the diff): rbx ball frames, rbp ai ctx, "
          "rsi, r12 consts, r13 player, r14 gait ptr, r15 target, xmm0-xmm15")
    good = not bad and clean
    print("   ", ok(good))
    return good


def s6_end_to_end(inst, lay, gain, pivot) -> bool:
    print("\n== S6  end-to-end: stock vs hook -> cave -> return, over the whole dead block")
    hook = cave_alloc.hook_patch(inst, HOOK, STOLEN_LEN, lay.entry, "hook")
    ov = lay.overlays() + [(HOOK, bytes.fromhex(hook["patch"]))]
    print(f"      hook bytes at {HOOK:#x}: {hook['patch']}  (jmp {lay.entry:#x} + "
          f"{STOLEN_LEN - 5} nop)")
    print("      attr    stock edi   patched edi   delta   budget vs stock")
    bad = False
    for attr in (40, 50, 60, 70, 80, 90, 99):
        a = fresh(inst, attr=attr, adjust=100, base=0, ebx=138)
        a.run(REGION, HOOK_RET)
        b = fresh(inst, ov, attr=attr, adjust=100, base=0, ebx=138)
        b.run(REGION, HOOK_RET)
        se, pe = s32(a.uc.reg_read(X.UC_X86_REG_EDI)), s32(b.uc.reg_read(X.UC_X86_REG_EDI))
        m = delta_model(attr, gain, pivot)
        bad |= pe != se - m
        # every other register must agree with stock
        ra, rb = a.regs(), b.regs()
        # rcx/rdx ARE compared: the patched path must hand the stock call the same arguments.
        differ = sorted(k for k in ra if ra[k] != rb[k] and k not in ("rdi", "rax", "eflags", "rip",
                                                                     "xmm0"))
        bad |= bool(differ)
        print(f"      {attr:>4d}   {se:>10d}   {pe:>11d}   {m:>+6d}   {-m:>+6d} frames"
              + (f"   OTHER REGS DIFFER: {differ}" if differ else ""))
    print("\n      hostile inputs (the cave must stay bounded and never fault):")
    for attr, adj, base in ((0, 0, 0), (255, 0, 0), (99, 2**31 - 1, 0), (40, -2**31, 0),
                            (99, 0, 2**31 - 1), (40, 0, -2**31), (255, -2**31, 1_000_000)):
        b = fresh(inst, ov, attr=attr, adjust=adj, base=base, ebx=1_999_999)
        b.run(REGION, HOOK_RET)
        edi = s32(b.uc.reg_read(X.UC_X86_REG_EDI))
        inside = -EDI_LIMIT <= edi <= EDI_LIMIT
        bad |= not inside
        print(f"      attr {attr:>3d}  adjust {adj:>11d}  base {base:>11d}  ballFrames 1999999"
              f"  -> edi {edi:>11d}   inside +-{EDI_LIMIT}: {inside}")
    print("   ", ok(not bad))
    return not bad


def s7_identity(inst, lay, gain, pivot) -> bool:
    print("\n== S7  identity at the pivot: attr == PIVOT must be bit-identical to stock")
    hook = cave_alloc.hook_patch(inst, HOOK, STOLEN_LEN, lay.entry, "hook")
    ov = lay.overlays() + [(HOOK, bytes.fromhex(hook["patch"]))]
    bad = False
    for adjust, base, ebx in ((100, 0, 138), (100, 25, 0), (0, -30, 10_000), (12345, 7, 99)):
        a = fresh(inst, attr=pivot, adjust=adjust, base=base, ebx=ebx)
        a.run(REGION, HOOK_RET)
        b = fresh(inst, ov, attr=pivot, adjust=adjust, base=base, ebx=ebx)
        b.run(REGION, HOOK_RET)
        ra, rb = a.regs(), b.regs()
        live = [k for k in ra if k not in ("rip", "eflags", "xmm0")]     # xmm0/flags dead: see S1/S8
        differ = sorted(k for k in live if ra[k] != rb[k])
        bad |= bool(differ)
        print(f"      adjust {adjust:>6d} base {base:>5d} ballFrames {ebx:>7d}: "
              f"edi stock {s32(ra['rdi']):>8d} patched {s32(rb['rdi']):>8d}   "
              f"live registers differing: {differ if differ else 'NONE'}")
    print("      (xmm0 differs by construction: the stock block leaves -0.0f in it, the cave leaves")
    print("       the pre-hook (float)adjust.  That it is DEAD is proved by execution below.)")
    print("\n      xmm0 deadness, by EXECUTION: the rest of the function (the two calls at 0x143da6555")
    print("      /0x143da655d and the whole decision loop) run from HOOK_RET with different incoming")
    print("      xmm0 values; the gait and the register state must come out identical.")
    outs = []
    for x in (f2i(-0.0), f2i(0.0), f2i(100.0), f2i(-2147483648.0), 0xDEADBEEF):
        e = fresh(inst, attr=pivot, adjust=100, base=0, ebx=138)
        e.uc.mem_write(GAIT, struct.pack("<i", 5))
        e.uc.reg_write(X.UC_X86_REG_XMM7, struct.unpack("<I", inst.read_va(SIXTENTHS_CELL, 4))[0])
        e.uc.reg_write(X.UC_X86_REG_XMM0, x)
        e.uc.reg_write(X.UC_X86_REG_RDI, 138)
        e.uc.reg_write(X.UC_X86_REG_RSI, 0)
        e.uc.reg_write(X.UC_X86_REG_RSP, STACK + 0x100000 - 0x200)
        e.uc.reg_write(X.UC_X86_REG_RDX, ENTITY)
        e.uc.reg_write(X.UC_X86_REG_RCX, MATCHOBJ)
        e.stubs[ARRIVAL_FN] = lambda uc: uc.reg_write(X.UC_X86_REG_RAX, 150)
        e.run(HOOK_RET, LOOP_DONE, count=20000)
        g = struct.unpack("<i", e.uc.mem_read(GAIT, 4))[0]
        st = {k: v for k, v in e.regs().items() if k not in ("xmm0", "rip", "eflags", "rax")}
        outs.append((g, tuple(sorted(st.items()))))
        print(f"      incoming xmm0 = {x:#018x}  ->  gait {g}")
    same = len({o for o in outs} ) == 1
    bad |= not same
    print(f"      every run identical (gait and registers): {same}")
    print("   ", ok(not bad))
    return not bad


def s8_clamps(inst, lay, gain, pivot) -> bool:
    print("\n== S8  the clamps, and the one overflow the stock code could have had")
    lo = delta_model(0, gain, pivot)
    hi = delta_model(255, gain, pivot)
    print(f"      the attribute is a BYTE, so delta is bounded by construction: "
          f"attr 0 -> {lo:+d}, attr 255 -> capped at {ATTR_CAP} -> {hi:+d} frames")
    print(f"      the final budget is clamped to +-{EDI_LIMIT:,} frames, so 'lea ecx,[rbx+rdi]' at "
          f"0x143da65fe (rbx <= 1,999,999) cannot overflow int32: "
          f"{EDI_LIMIT + 1_999_999 < 2**31}")
    print(f"      the clamp can only fire if basePosition.marginPredictionFrameBase is set beyond "
          f"+-{EDI_LIMIT - 1_999_999:,}; the stock value is 0 and the largest ball-frame count the "
          f"game itself produces is 1,999,999, so NO stock-reachable state is clamped.")
    e = fresh(inst, lay.overlays(), attr=99, base=2**31 - 1, ebx=1_999_999, rdi=0)
    hook = cave_alloc.hook_patch(inst, HOOK, STOLEN_LEN, lay.entry, "hook")
    ov = lay.overlays() + [(HOOK, bytes.fromhex(hook["patch"]))]
    worst = []
    for base in (2**31 - 1, -2**31, 2**30, -2**30, 0):
        b = fresh(inst, ov, attr=99, adjust=0, base=base, ebx=1_999_999)
        b.run(REGION, HOOK_RET)
        edi = s32(b.uc.reg_read(X.UC_X86_REG_EDI))
        worst.append(edi)
        print(f"      dt270 base {base:>12d} + ballFrames 1,999,999 -> edi {edi:>12d}")
    good = all(-EDI_LIMIT <= v <= EDI_LIMIT for v in worst)
    print("   ", ok(good))
    return good


# ------------------------------------------------------------------ S9: the game's own loop
GAIT_SPEED = {5: 7.5, 4: 6.0, 3: 4.5, 2: 3.0, 1: 1.5}     # ASSUMED m/s ladder — labelled, not proven


LADDER_B = {5: 6.5, 4: 5.5, 3: 4.0, 2: 2.5, 1: 1.2}       # a second ASSUMED ladder, for sensitivity


def run_loop(inst, overlays, *, attr, budget_hook, dist_m, fps=60.0, gait0=5, mingait=0,
             ballframes=138, base=0, ladder=None):
    """Emulate the game's OWN decision loop 0x143da6562..0x143da6618 on the real bytes.

    The only stub is the arrival estimator 0x143e54f70, which is fed a plausible speed ladder
    (GAIT_SPEED, ASSUMED) and otherwise left alone; the fps getter runs for real off the image
    global.  `budget_hook` supplies edi as the patched/stock block would have left it."""
    e = fresh(inst, overlays, attr=attr, base=base, ebx=ballframes, fps=fps)
    e.uc.mem_write(GAIT, struct.pack("<i", gait0))
    e.uc.mem_write(STACK + 0x100000 - 0x100 + 0xC0, struct.pack("<f", 1.0))
    # xmm7 = the 0.6f the function loads at 0x143da64cd, BEFORE this region: the loop's own
    # hysteresis term is (int)(fps*xmm7 + xmm6) and xmm6 (0.5f) is set by the emulated code itself.
    e.uc.reg_write(X.UC_X86_REG_XMM7, struct.unpack("<I", inst.read_va(SIXTENTHS_CELL, 4))[0])

    lad = ladder or GAIT_SPEED

    def arrival(uc):
        r9 = uc.reg_read(X.UC_X86_REG_R9)
        cand = struct.unpack("<i", uc.mem_read(r9, 4))[0]
        secs = dist_m / lad.get(max(1, min(5, cand)), min(lad.values()))
        uc.reg_write(X.UC_X86_REG_RAX, int(secs * fps))

    e.stubs[ARRIVAL_FN] = arrival
    seen = []
    e.probes[0x143DA65FE] = lambda uc: seen.append((uc.reg_read(X.UC_X86_REG_EBX),
                                                    s32(uc.reg_read(X.UC_X86_REG_EDI)),
                                                    uc.reg_read(X.UC_X86_REG_EAX)))
    e.ensure(FPS_FN, 0x20)
    e.setregs(rsp=STACK + 0x100000 - 0x200, rdi=budget_hook & 0xFFFFFFFF,
              rsi=mingait, r12=CONSTS, r14=GAIT)
    e.uc.reg_write(X.UC_X86_REG_RDI, budget_hook & 0xFFFFFFFF)
    e.uc.reg_write(X.UC_X86_REG_RSI, mingait)
    e.uc.reg_write(X.UC_X86_REG_R12, 0)            # r12d is zeroed by the stock code at 0x143da6578
    e.run(LOOP_ENTRY, LOOP_DONE, count=20000)
    return struct.unpack("<i", e.uc.mem_read(GAIT, 4))[0], seen


def s9_behaviour(inst, lay, gain, pivot) -> bool:
    print("\n== S9  BEHAVIOUR: the game's own gait loop, stock vs patched")
    print("      The loop is real bytes (0x143da6562..0x143da6618) with ONE stub: the arrival")
    print("      estimator 0x143e54f70, fed an ASSUMED gait->speed ladder "
          f"{GAIT_SPEED} m/s (c-inferred).")
    print("      fps global 0x148c22abc planted at 60.0; the loop's own hysteresis term comes out of")
    print("      the game's 0.6f at 0x147850258 as (int)(60*0.6+0.5) = 36 frames.")
    hook = cave_alloc.hook_patch(inst, HOOK, STOLEN_LEN, lay.entry, "hook")
    ov = lay.overlays() + [(HOOK, bytes.fromhex(hook["patch"]))]
    good, margins = True, set()
    for dist, ball in ((12.0, 138), (18.0, 138), (25.0, 200)):
        print(f"\n      defender {dist:.0f} m from the spot, ball arrives in {ball} frames "
              f"({ball / 60:.2f} s of budget):")
        print("      attr   delta   budget   gait(stock)   gait(patched)")
        for attr in (40, 50, 60, 70, 80, 90, 99):
            a = fresh(inst, attr=attr, adjust=100, base=0, ebx=ball)
            a.run(REGION, HOOK_RET)
            stock_budget = s32(a.uc.reg_read(X.UC_X86_REG_EDI))
            b = fresh(inst, ov, attr=attr, adjust=100, base=0, ebx=ball)
            b.run(REGION, HOOK_RET)
            pat_budget = s32(b.uc.reg_read(X.UC_X86_REG_EDI))
            gs, ts = run_loop(inst, (), attr=attr, budget_hook=stock_budget, dist_m=dist,
                              ballframes=ball)
            gp, tp = run_loop(inst, (), attr=attr, budget_hook=pat_budget, dist_m=dist,
                              ballframes=ball)
            margins.update(t[0] for t in ts + tp)
            good &= (attr != pivot) or (gs == gp)
            print(f"      {attr:>4d}  {delta_model(attr, gain, pivot):>+6d}  {pat_budget:>7d}   "
                  f"{gs:>11d}   {gp:>13d}" + ("   <- pivot: identical" if attr == pivot else ""))
    print(f"\n      the loop's own hysteresis term, MEASURED in the emulator at the compare "
          f"0x143da65fe over every run above: {sorted(margins)} frames")
    print(f"      (the code computes it as (int)(fps * 0.6f + 0.5f) from the game's own 0.6f at "
          f"{SIXTENTHS_CELL:#x}; it is the granularity this decision already has, and the bar the "
          f"GAIN default has to clear)")
    print("\n      LADDER SENSITIVITY — the same 12 m case on a second, slower assumed ladder")
    print(f"      {LADDER_B} m/s:")
    print("      attr   gait(stock)   gait(patched)")
    mono = []
    for attr in (40, 50, 60, 70, 80, 90, 99):
        a = fresh(inst, attr=attr, adjust=100, base=0, ebx=138)
        a.run(REGION, HOOK_RET)
        b = fresh(inst, ov, attr=attr, adjust=100, base=0, ebx=138)
        b.run(REGION, HOOK_RET)
        gs, _ = run_loop(inst, (), attr=attr, budget_hook=s32(a.uc.reg_read(X.UC_X86_REG_EDI)),
                         dist_m=12.0, ballframes=138, ladder=LADDER_B)
        gp, _ = run_loop(inst, (), attr=attr, budget_hook=s32(b.uc.reg_read(X.UC_X86_REG_EDI)),
                         dist_m=12.0, ballframes=138, ladder=LADDER_B)
        mono.append(gp)
        good &= (attr != pivot) or (gs == gp)
        print(f"      {attr:>4d}   {gs:>11d}   {gp:>13d}")
    is_mono = all(x <= y for x, y in zip(mono, mono[1:]))
    print(f"      patched gait is non-decreasing in the attribute on this ladder too: {is_mono}")
    print("      LADDER-INDEPENDENT CLAIM (a-emulated for the arithmetic, not for the ladder): the")
    print("      budget is strictly decreasing in the attribute and the loop accepts strictly more")
    print("      downshifts as the budget grows, so for ANY monotone gait->speed map a higher")
    print("      Defensive Awareness can only produce a gait >= the one a lower rating produces,")
    print("      and the pivot rating always reproduces the stock decision exactly.")
    print("\n      (gait 5 = the force-dash/sprint value the same function sets at 0x143da963d; 1 is")
    print("       the floor the loop stops at and the [1,5] clamp in ActionMark::vf6 confirms.)")
    good &= is_mono
    print("   ", ok(good))
    return good


def s10_layout(inst, lay) -> bool:
    print("\n== S10  layout: the payload chained across real int3 caves")
    problems = cave_alloc.verify_layout(lay, target=inst, verbose=True)
    print(f"      chunks {len(lay.chunks)}   bytes written {lay.total_used()}   "
          f"payload {lay.payload_bytes()}")
    print(f"      allocator verify_layout problems: {problems if problems else 'NONE'}")
    audit = cave_alloc.audit_caves([c.cave for c in lay.chunks], target=inst)
    print(f"      independent cave audit (int3 + maximal + no pdata overlap + no refs): "
          f"{audit if audit else 'NONE'}")
    good = not problems and not audit
    print("   ", ok(good))
    return good


def sweep(inst, lay_for, pivot):
    print("\n== GAIN sweep (the evidence for the default)")
    print("      The loop's own hysteresis term is (int)(fps*0.6+0.5) = 36 frames at 60 fps.")
    print("      A gain whose whole 40..99 spread is under that is smaller than the granularity the")
    print("      game already applies to this decision, and will usually change nothing.")
    print("      But 'does a 40 differ from a 99' is too coarse a test — it is already true at gain")
    print("      0.5 in the geometries below, because ONE decision boundary happens to sit between")
    print("      them.  The measure that matches the complaint is HOW MUCH OF THE LEAGUE moves: the")
    print("      share of ratings 40..99 whose decision differs from stock in at least one geometry,")
    print("      and the worst-case gait spread across the band.  Budgets come from the identity S6")
    print("      verified (edi = base - delta + ballFrames); the gait comes out of the game's own")
    print("      loop, emulated on the real bytes.")
    geoms = ((12.0, 138), (18.0, 138), (25.0, 200))
    stock = {}
    for dist, ball in geoms:
        stock[dist] = run_loop(inst, (), attr=70, budget_hook=ball, dist_m=dist, ballframes=ball)[0]
    print("      gain   delta@40  delta@99  spread  spread/36   ratings moved   worst gait spread")
    for g in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
        d40, d99 = (delta_model(a, g, pivot) for a in (40, 99))
        moved, worst = 0, 0
        for attr in range(40, 100):
            d = delta_model(attr, g, pivot)
            diff = False
            for dist, ball in geoms:
                gp, _ = run_loop(inst, (), attr=attr, budget_hook=ball - d, dist_m=dist,
                                 ballframes=ball)
                diff |= gp != stock[dist]
                lo, hi = sorted((gp, stock[dist]))
                worst = max(worst, hi - lo)
            moved += diff
        print(f"      {g:<5.2f}  {d40:>8d}  {d99:>8d}  {d99 - d40:>6d}  {(d99 - d40) / 36:>8.2f}x   "
              f"{moved:>3d}/60 ({moved / 60:4.0%})      {worst} gait step(s)")
    print("      -> the default 1.5 is the LARGEST gain that still keeps the worst case to one gait")
    print("         step, and at that setting 77% of the 40..99 band behaves differently from stock.")
    print("         0.5-0.75 is the 'too conservative to notice' failure (a third to a half of the")
    print("         band never moves at all); 2.0 and above start putting two steps between")
    print("         neighbouring ratings, which reads as a caricature rather than as a defender.")


# ==================================================================================== the spec
DESCRIPTION = """ABILITY-SCALED DEFENSIVE ANTICIPATION (chained code cave).  WHAT IT DOES: it makes \
"does this player keep running while the pass is in the air, or does he coast" depend on his \
Defensive Awareness.  Today it is FLAT: every player on the pitch eases off on exactly the same \
schedule, which is the 'men run off a bad defender the same as off Saliba' complaint.  THE SITE: \
0x143da63b0 is the AI gait (movement-urgency) chooser's 'ease off while the ball is in flight' \
rule, called once per player per tick from the vf13 slot of every move-type Action (ActionFreeMove, \
ActionSpaceRun, ActionMoveOnPass, ActionPassSupportThrowIn, the ActionBasePosition cascade).  It \
computes a frame BUDGET edi = basePosition.marginPredictionFrameBase (dt270, currently 0) - \
(int)(marginPredictionFrameAdjust * -0.0f) + ballFrames, and then walks the gait DOWN one step at a \
time, accepting each step while the player would still arrive before the budget expires \
('arrival >= margin + edi' stops it, at 0x143da65fe..0x143da6603).  Because the multiplier at \
0x147850538 is -0.0f, the marginPredictionFrameAdjust term is ALWAYS 0 - proven under Unicorn for \
every int32 value including +-INT_MAX - so those 12 bytes are dead code inside a live function.  \
MECHANISM: the hook replaces the dead 'mulss xmm0,[rip->-0.0f]' + 'cvttss2si eax,xmm0' + the two \
tail instructions 'sub edi,eax' / 'add edi,ebx' (16 bytes at 0x143da6545, ending exactly at the \
call site 0x143da6555) with a jmp into a chained cave that reads the player's Defensive Awareness \
(match attribute array index 0x15 = DATA_PARAMETER_DEFENSE_DECISION) via the same pure leaf \
0x1442d6ef0 the stock code calls six bytes later, computes delta = floor((min(attr,120) - PIVOT) * \
GAIN) and does edi = base - delta + ballFrames, clamped to +-4,000,000 frames.  DIRECTION - NOTE \
THIS, IT IS THE OPPOSITE OF THE OBVIOUS ONE: 'sub edi,eax' means a POSITIVE delta SHRINKS the \
budget, and a smaller budget means the player refuses to downshift.  So an elite defender gets a \
positive delta (he behaves as though the ball arrives ~0.7 s earlier than it does, and keeps \
sprinting), and a poor one a negative delta (he gives himself ~0.75 s of extra slack and coasts \
while the pass travels).  WHY GAIN = 1.5: not taste.  Two measured bars.  (i) The loop's OWN granularity is the hysteresis term it computes at 0x143da6590 as (int)(fps*0.6f + 0.5f) = 36 frames at 60 fps (measured in the emulator at the compare, every run: 36) - a gain whose whole 40..99 spread is under that is smaller than the step the game already applies, so 0.5 (spread 29) is below the noise floor.  (ii) Running the game's own loop for every rating 40..99 across three chase geometries (12 m / 18 m / 25 m, ball 2.3-3.3 s away): gain 0.5 moves 33% of the band, 0.75 moves 55%, 1.0 moves 67%, 1.25 moves 73%, 1.5 moves 77%, 2.0 moves 83% and 3.0 moves 88% - but 2.0 and above put TWO gait steps between neighbouring ratings, while everything up to 1.5 keeps the worst case at one.  1.5 is therefore the largest value that is still one step, and it is deliberately at the top of the sensible range rather than in the middle.  Drop to 1.0 for a gentler build; do not go below 0.75.  IDENTITY: at attr == PIVOT the delta is exactly 0 and every live register \
is bit-identical to stock - the patch adds no global bias.  SAFETY: no stack use beyond the one \
call, no memory writes, no rip-relative operand, no flag dependency (flags are dead at the hook: \
the stolen 'sub edi,eax' sets them and nothing reads them before 0x143da6555 overwrites them), and \
the only call is a 7-instruction pure leaf that is xmm-free and preserves every non-volatile.  \
WHAT IS NOT PROVEN: (a) nothing has been observed in a running match; (b) the gait -> km/h map is \
NOT decoded, so the size of the on-pitch effect of one gait step is unknown - the S9 table's \
speed ladder is an ASSUMPTION, only the decision arithmetic is emulated; (c) this function runs \
for EVERY player in a move action on BOTH teams, so an attacker's run is paced by his own \
Defensive Awareness too - there is a defence gate available (0x1442d7090(ctx) -> [rax+0x28d]==0) \
but its meaning was not proven, so it is deliberately not used; (d) Denuvo's tolerance of written \
int3 padding is untested, and a chained payload writes into several distinct sites instead of one.  \
ROLLBACK: python tools/exe_patch.py remove tools/data/patches/anticipation-ability.json.  Change \
GAIN or PIVOT by REGENERATING (python tools/emu_anticipation.py --gain <g> --pivot <p> \
--write-spec), not by editing bytes - a hand-edit makes remove refuse.  Authored only - NOT \
applied, never run in-game."""


def find_imm(chunks, value: int, size: int = 4):
    """Locate a 4-byte immediate in the emitted chunks (for the tunables block)."""
    want = struct.pack("<i", value)
    hits = []
    for c in chunks:
        i = c.code.find(want)
        while i >= 0:
            hits.append(c.va + i)
            i = c.code.find(want, i + 1)
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--gain", type=float, default=1.5, help="frames of anticipation per attribute point")
    ap.add_argument("--pivot", type=int, default=70, help="the attribute that behaves exactly like stock")
    ap.add_argument("--attr", type=lambda s: int(s, 0), default=ATTR_DEF_AWARE)
    ap.add_argument("--min-cave", type=int, default=12)
    ap.add_argument("--no-guard", action="store_true", help="drop the final edi clamp (smaller payload)")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--write-spec", action="store_true")
    ap.add_argument("--print-source", action="store_true")
    a = ap.parse_args()

    if a.write_spec and SPEC.exists():
        # Regenerating must not collide with the PREVIOUS revision of this same spec: the allocator
        # treats every committed spec (and the ledger) as a claim, including ours.  Withdraw the old
        # claim BEFORE the pool is built, so the proofs run on the layout the spec writer will emit.
        # Refuse if the old revision is applied to the image — that would orphan live bytes.
        old = json.loads(SPEC.read_text(encoding="utf-8"))
        for e in old["patches"]:
            va, pat = int(e["va"], 16), bytes.fromhex(e["patch"])
            if cave_alloc.Image(Path(a.exe)).read_va(va, len(pat)) == pat:
                raise SystemExit(f"the current {SPEC.name} is APPLIED at {va:#x} — run "
                                 f"'exe_patch.py remove {SPEC}' first; refusing to regenerate")
        SPEC.unlink()
        if cave_alloc.LEDGER.exists():
            led = json.loads(cave_alloc.LEDGER.read_text(encoding="utf-8"))
            led["reservations"] = [r for r in led.get("reservations", []) if r["spec"] != SPEC.name]
            cave_alloc.LEDGER.write_text(json.dumps(led, indent=1) + "\n", encoding="utf-8")
        print(f"(withdrew the previous, unapplied {SPEC.name} and its reservations before "
              f"re-allocating)")

    inst = cave_alloc.Image(Path(a.exe))
    pris = cave_alloc.Image(PRISTINE) if PRISTINE.exists() else None
    print(f"target   {a.exe}\n         sha1 {inst.sha1}")
    if pris:
        print(f"pristine {PRISTINE}\n         sha1 {pris.sha1}")
    print(f"payload  GAIN {a.gain} frames/point (Q8 {int(round(a.gain * 256))})   PIVOT {a.pivot}   "
          f"attr idx {a.attr:#04x}   cap {ATTR_CAP}   edi band +-{EDI_LIMIT:,}")

    src = cave_source(a.gain, a.pivot, a.attr, guarded=not a.no_guard)
    if a.print_source:
        print(src)

    # lay the payload out over real caves (this is what the emulator will execute)
    pool, rej = cave_alloc.cave_pool(target=inst, pristine=pris, min_len=a.min_cave, anchor=HOOK)
    print(f"\ncave pool: {len(pool)} free tier-A caves >= {a.min_cave} B (rejected {rej})")
    lay = cave_alloc.layout_payload(src, pool=pool, exits=(HOOK_RET,),
                                    externals={"ENTITY_TO_DATA": ENTITY_TO_DATA, "HOOK_RET": HOOK_RET},
                                    policy=dict(anchor=f"{HOOK:#x}", min_cave=a.min_cave, safety="A"))
    print(f"laid out: {len(lay.chunks)} chunk(s), {lay.total_used()} bytes written, "
          f"{lay.payload_bytes()} payload bytes, entry {lay.entry:#x}\n")

    results = {}
    results["S1 static"] = s1_static(inst, pris or inst)
    results["S2 deadness"] = s2_deadness(inst)
    results["S3 attribute"] = s3_attribute(inst)
    results["S4 callee"] = s4_callee(inst)
    results["S5 cave"] = s5_cave(inst, lay, a.gain, a.pivot)
    results["S6 end-to-end"] = s6_end_to_end(inst, lay, a.gain, a.pivot)
    results["S7 identity"] = s7_identity(inst, lay, a.gain, a.pivot)
    results["S8 clamps"] = s8_clamps(inst, lay, a.gain, a.pivot)
    results["S9 behaviour"] = s9_behaviour(inst, lay, a.gain, a.pivot)
    results["S10 layout"] = s10_layout(inst, lay)
    if a.sweep:
        sweep(inst, lay, a.pivot)

    print("\n== the table the owner will feel (GAIN {0}, PIVOT {1})".format(a.gain, a.pivot))
    print("      Defensive    delta      budget change     what it means while a pass is in flight")
    print("      Awareness   (frames)      (frames)")
    for attr in (40, 50, 60, 65, 70, 75, 80, 85, 90, 95, 99):
        d = delta_model(attr, a.gain, a.pivot)
        s = "eases off sooner" if d < 0 else ("STOCK — unchanged" if d == 0 else "keeps running")
        print(f"      {attr:>7d}    {d:>+7d}      {-d:>+9d}        {s}"
              f"  ({abs(d) / 60:.2f} s)")

    allgood = all(results.values())
    print("\n== VERDICT")
    for k, v in results.items():
        print(f"   {k:<16s} {ok(v)}")
    print(f"   overall: {ok(allgood)}")

    if a.write_spec:
        if not allgood:
            raise SystemExit("a proof failed — refusing to write the spec")
        extra = dict(
            status="authored, not applied, never run in-game. Proven by emulation "
                   "(tools/emu_anticipation.py: S1-S10 pass).",
            tunables={})
        doc, lay2 = cave_alloc.build_spec(
            description=DESCRIPTION, prefix="anticipation-ability", asm_text=src,
            hook_va=HOOK, stolen_len=STOLEN_LEN, exits=(HOOK_RET,), target=inst, pristine=pris,
            externals={"ENTITY_TO_DATA": ENTITY_TO_DATA, "HOOK_RET": HOOK_RET},
            min_cave=a.min_cave, extra=extra)
        if [c.code for c in lay2.chunks] != [c.code for c in lay.chunks]:
            raise SystemExit("the spec's layout differs from the one that was proven — refusing")
        pv = find_imm(lay2.chunks, a.pivot)
        gv = find_imm(lay2.chunks, int(round(a.gain * 256)))
        doc["tunables"] = {
            "PIVOT": {"va": f"{pv[0]:#x}" if len(pv) == 1 else [f"{v:#x}" for v in pv], "bytes": 4,
                      "encoding": "int32 LE", "value": a.pivot,
                      "meaning": "the Defensive Awareness that behaves EXACTLY like the stock game. "
                                 "Above it a player keeps running while the ball is in flight, below "
                                 "it he coasts. 70 is about a first-team average; raise it to make "
                                 "the whole league lazier, lower it to make everyone keener."},
            "GAIN_Q8": {"va": f"{gv[0]:#x}" if len(gv) == 1 else [f"{v:#x}" for v in gv], "bytes": 4,
                        "encoding": "int32 LE, fixed point x256", "value": int(round(a.gain * 256)),
                        "meaning": f"frames of anticipation per attribute point x 256 (default "
                                   f"{a.gain} -> {int(round(a.gain * 256))}). The 40..99 spread is "
                                   f"{delta_model(99, a.gain, a.pivot) - delta_model(40, a.gain, a.pivot)}"
                                   f" frames against the loop's own 36-frame hysteresis term; a gain "
                                   f"whose spread is under 36 will usually change nothing."}}
        SPEC.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        cave_alloc.reserve_caves(lay2, SPEC.name)
        print(f"\nwrote {SPEC}  ({len(doc['patches'])} entries) and reserved its caves in "
              f"{cave_alloc.LEDGER.name}")
    sys.exit(0 if allgood else 1)


if __name__ == "__main__":
    main()
