#!/usr/bin/env python3
"""
emu_linebreak.py — reviving match::ai::ActionSelectorLineBreak (action id 0x20).

Konami ships LineBreak's quota table and its tactical gate but gutted both layers: the
selector's vf3/vf4 are stubs, and the executor match::player::ActionLineBreak is a 0x40-byte
husk whose movement slots are stubs.  This tool works out what can be BORROWED from a sibling
or a base class and what has to be written, and it proves the borrow is memory-safe rather
than asserting it.

The whole risk in this job is object size.  The ten selectors are packed into
ActionSelectorManager with ZERO slack between neighbours, so a borrowed method that touches a
member past the end of LineBreak's subobject silently corrupts the next selector.  Every
`bounds` / `guard` claim below is about exactly that.

    python tools/emu_linebreak.py sizes        # class sizes from operator delete + ctor placement
    python tools/emu_linebreak.py vtables      # the selector / executor vtables side by side
    python tools/emu_linebreak.py bounds 0x143df0cf0        # static this-relative access set
    python tools/emu_linebreak.py guard 0x143df0cf0         # Unicorn, guard page at LineBreak+0x2c8
    python tools/emu_linebreak.py exec-guard                # executor donors with a poisoned `this`
    python tools/emu_linebreak.py gate         # the quota / difficulty gate for action 0x20
    python tools/emu_linebreak.py target       # offside line + run-target geometry
    python tools/emu_linebreak.py caves        # where the stage-2/3 payloads would land
    python tools/emu_linebreak.py build        # write the stage specs (no game write)
    python tools/emu_linebreak.py proof        # run everything, write build/linebreak-proof.txt

Read-only with respect to the game.  Nothing here applies a patch; `build` writes JSON specs
into tools/data/patches/ and the owner applies them himself, one stage at a time.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLED = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
PRISTINE = Path.home() / "Backups" / "eFootball" / "eFootball.exe.PRISTINE"
BASE = 0x140000000

# ---------------------------------------------------------------- the cast (verified by `vtables`)
SEL_VFT = {
    "Score":      0x146b26a20,
    "Chance":     0x146b26a60,
    "Counter":    0x146b26aa0,
    "SecondLine": 0x146b26ae0,
    "LineBreak":  0x146b26b20,
    "PullAway":   0x146b26b60,
    "Diagonal":   0x146b379f8,
    "PostPlay":   0x146b26bc8,
    "GoalGet":    0x146b26ba0,
    "Overlap":    0x146b269f8,
}
# manager-relative placement of each selector subobject, read by `sizes` from the ctor
MANAGER_CTOR = 0x143d519d0
DISPATCH = 0x143df1080          # ActionSelectorScore::vf2, the shared bidding dispatcher
MANAGER_UPDATE = 0x143d52470

LINEBREAK_SIZE = 0x2c8          # proven by `sizes`
SCORE_BASE_SIZE = 0x2c0

STUBS = {
    0x140c853c0: "xor al,al; ret            -> bool false",
    0x140c837d0: "xor eax,eax; ret          -> int 0",
    0x140c83810: "mov al,1; ret             -> bool true",
    0x140c83910: "ret                       -> void",
    0x143e02700: "movss xmm0,[0x145a8aa4c]; ret -> 100.0f",
    0x14143aec0: "xorps xmm0,xmm0; ret      -> 0.0f",
    0x143d520d0: "zero vec3 out; ret out    -> (0,0,0) target",
}


# =============================================================================== image / disasm
class Image:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        d = self.data
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.secs = []
        for i in range(nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            chars = struct.unpack_from("<I", s, 36)[0]
            self.secs.append(dict(name=s[:8].rstrip(b"\0").decode(), va=va, vsize=vsize,
                                  raw=raw, rsize=rsize, chars=chars))

    def va_to_file(self, va: int):
        rva = va - self.base
        for s in self.secs:
            if s["va"] <= rva < s["va"] + s["vsize"]:
                o = rva - s["va"]
                return None if o >= s["rsize"] else s["raw"] + o
        return None

    def read(self, va: int, n: int) -> bytes:
        f = self.va_to_file(va)
        if f is None:
            raise ValueError(f"{va:#x} not backed by file bytes")
        return self.data[f:f + n]

    def u32(self, va):
        return struct.unpack_from("<I", self.read(va, 4))[0]

    def u64(self, va):
        return struct.unpack_from("<Q", self.read(va, 8))[0]

    def f32(self, va):
        return struct.unpack_from("<f", self.read(va, 4))[0]


_MD = None


def md():
    global _MD
    if _MD is None:
        import capstone
        _MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        _MD.detail = True
    return _MD


def disasm_fn(img: Image, va: int, max_ins: int = 4000):
    """Linear-sweep the function's basic blocks, following intra-function branches."""
    import capstone
    seen, order, work = {}, [], [va]
    while work:
        pc = work.pop()
        while pc not in seen and len(seen) < max_ins:
            try:
                code = img.read(pc, 16)
            except ValueError:
                break
            ins = next(md().disasm(code, pc, 1), None)
            if ins is None:
                break
            seen[pc] = ins
            order.append(pc)
            m = ins.mnemonic
            if m in ("ret", "jmp", "int3"):
                if m == "jmp" and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
                    t = ins.operands[0].imm
                    if abs(t - va) < 0x20000:      # intra-function tail
                        work.append(t)
                break
            if m.startswith("j") and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
                work.append(ins.operands[0].imm)
            pc += ins.size
    return [seen[a] for a in sorted(seen)]


# ============================================================ static `this`-relative access set
def bounds(img: Image, va: int, this_reg: str = "rcx", depth: int = 0, _seen=None):
    """
    Track which registers hold `this + K` and report every memory access through them.
    Also reports calls that receive a this-derived pointer in an argument register, since the
    callee could then touch a member out of our sight.
    """
    import capstone
    from capstone.x86 import X86_OP_REG, X86_OP_MEM, X86_OP_IMM

    _seen = _seen if _seen is not None else set()
    if va in _seen or depth > 3:
        return [], []
    _seen.add(va)

    R = capstone.x86
    name = md().reg_name

    def base64(r):
        n = name(r)
        m = {"eax": "rax", "ebx": "rbx", "ecx": "rcx", "edx": "rdx", "esi": "rsi", "edi": "rdi",
             "ebp": "rbp", "esp": "rsp"}
        if n in m:
            return m[n]
        if n and n.startswith("r") and n[-1] == "d" and n[1:-1].isdigit():
            return "r" + n[1:-1]
        return n

    taint = {this_reg: 0}
    accesses, passes = [], []
    ins_list = disasm_fn(img, va)

    for ins in ins_list:
        ops = ins.operands
        # memory operands first (read before the destination is retainted)
        for o in ops:
            if o.type == X86_OP_MEM and o.mem.base != 0:
                b = base64(o.mem.base)
                if b in taint and o.mem.index == 0:
                    off = taint[b] + o.mem.disp
                    accesses.append((ins.address, off, o.size, ins.mnemonic, str(ins.op_str)))
                elif b in taint:
                    accesses.append((ins.address, taint[b] + o.mem.disp, o.size,
                                     ins.mnemonic + "[IDX]", str(ins.op_str)))

        m = ins.mnemonic
        if m == "call":
            for areg in ("rcx", "rdx", "r8", "r9"):
                if areg in taint:
                    tgt = ops[0].imm if ops and ops[0].type == X86_OP_IMM else None
                    passes.append((ins.address, areg, taint[areg], tgt))
            # volatile registers die across a call
            for r in ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11"):
                taint.pop(r, None)
            continue

        if m == "lea" and ops and ops[0].type == X86_OP_REG and ops[1].type == X86_OP_MEM:
            b = base64(ops[1].mem.base) if ops[1].mem.base else None
            d = base64(ops[0].reg)
            if b in taint and ops[1].mem.index == 0:
                taint[d] = taint[b] + ops[1].mem.disp
            else:
                taint.pop(d, None)
            continue

        if m == "mov" and ops and ops[0].type == X86_OP_REG:
            d = base64(ops[0].reg)
            if ops[1].type == X86_OP_REG and base64(ops[1].reg) in taint:
                taint[d] = taint[base64(ops[1].reg)]
            else:
                taint.pop(d, None)
            continue

        # anything else that writes a register kills the taint on it
        for o in ops:
            if o.type == X86_OP_REG and o.access & capstone.CS_AC_WRITE:
                taint.pop(base64(o.reg), None)

    return accesses, passes


def cmd_bounds(a):
    img = Image(a.exe or INSTALLED)
    va = int(a.va, 16)
    acc, passes = bounds(img, va)
    ins_list = disasm_fn(img, va)
    print(f"== {va:#x}  ({len(ins_list)} instructions reached)")
    if not acc:
        print("   NO `this`-relative memory access at all")
    offs = {}
    for addr, off, size, mn, ops in acc:
        offs.setdefault(off, []).append((addr, size, mn, ops))
    for off in sorted(offs):
        sites = offs[off]
        mark = "  <-- PAST LineBreak+0x2c8 !!" if off >= LINEBREAK_SIZE else ""
        print(f"   this+{off:#06x}  size {sites[0][1]:>2}  x{len(sites)}  "
              f"{sites[0][2]} {sites[0][3][:56]}{mark}")
    if offs:
        print(f"   --> max touched byte: this+{max(o + s[0][1] for o, s in offs.items()) - 1:#x}")
    for addr, reg, off, tgt in passes:
        print(f"   {addr:#x}: passes this+{off:#x} in {reg} to "
              f"{tgt:#x}" if tgt else f"   {addr:#x}: passes this+{off:#x} in {reg} to <indirect>")
    return 0


# =========================================================================== class sizes
def find_sized_delete(img: Image, vf0: int):
    """MSVC scalar deleting destructor passes the object size in edx to operator delete."""
    import capstone
    from capstone.x86 import X86_OP_IMM, X86_OP_REG
    for ins in disasm_fn(img, vf0, 80):
        if ins.mnemonic == "mov" and len(ins.operands) == 2:
            o0, o1 = ins.operands
            if o0.type == X86_OP_REG and md().reg_name(o0.reg) == "edx" and o1.type == X86_OP_IMM:
                return o1.imm, ins.address
    return None, None


def cmd_sizes(a):
    img = Image(a.exe or INSTALLED)
    print("== selector subobject sizes, from the scalar deleting destructor (vf0)")
    sizes = {}
    for nm, vft in SEL_VFT.items():
        vf0 = img.u64(vft)
        sz, at = find_sized_delete(img, vf0)
        sizes[nm] = sz
        print(f"   {nm:<11} vft {vft:#x}  vf0 {vf0:#x}  "
              f"{'size ' + hex(sz) + f'  (mov edx,imm at {at:#x})' if sz else 'no sized delete'}")

    print("\n== placement offsets in ActionSelectorManager::ctor", hex(MANAGER_CTOR))
    place = manager_placement(img)
    prev = None
    for off, ctor, dl in place:
        line = f"   +{off:#06x}  ctor {ctor:#x}" + (f"  maxSlots(dl)={dl}" if dl is not None else "")
        if prev is not None:
            line += f"   [gap from previous start: {off - prev:#x}]"
        print(line)
        prev = off
    return 0


def manager_placement(img: Image):
    """`lea rcx,[r?+K]` immediately before each selector-ctor call inside the manager ctor."""
    import capstone
    from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_OP_REG
    out, pending, dl = [], None, None
    for ins in disasm_fn(img, MANAGER_CTOR, 600):
        if ins.mnemonic == "lea" and ins.operands[0].type == X86_OP_REG \
                and md().reg_name(ins.operands[0].reg) == "rcx":
            m = ins.operands[1].mem
            if m.base and md().reg_name(m.base) not in ("rsp", "rip"):
                pending = m.disp
        elif ins.mnemonic == "mov" and ins.operands[0].type == X86_OP_REG \
                and md().reg_name(ins.operands[0].reg) == "dl" \
                and ins.operands[1].type == X86_OP_IMM:
            dl = ins.operands[1].imm
        elif ins.mnemonic == "call" and pending is not None:
            t = ins.operands[0].imm if ins.operands[0].type == X86_OP_IMM else 0
            out.append((pending, t, dl))
            pending, dl = None, None
    return out


# ================================================================================ vtables
def cmd_vtables(a):
    img = Image(a.exe or INSTALLED)
    order = ["Score", "Chance", "Counter", "SecondLine", "LineBreak", "Diagonal", "PullAway", "PostPlay"]
    print("== selector vtables (slot: address, [STUB] marked)")
    print(f"{'slot':<5}" + "".join(f"{n:<14}" for n in order))
    for slot in range(7):
        row = f"{slot:<5}"
        for n in order:
            v = img.u64(SEL_VFT[n] + 8 * slot)
            tag = "*" if v in STUBS else " "
            row += f"{v:#x}{tag}    "
        print(row)
    print("\n   * = stub:")
    for k, v in STUBS.items():
        print(f"     {k:#x}  {v}")
    return 0




# ============================================================== Unicorn guard-page memory proof
#
# The bounds analysis above is static and path-insensitive.  This is the hard proof: run the
# candidate donor on a REAL object of LineBreak's real size with the very next page UNMAPPED, so
# a single byte touched past the end of the subobject is a Unicorn fault carrying the exact
# address.  Every call out of the function is stubbed and the stub's return value is fuzzed, so
# the run explores branches instead of walking one happy path.

class Guard:
    """Emulator with an object whose end is a page boundary backed by nothing."""

    STACK = 0x00200000
    ARENA = 0x00400000          # scratch structures (args, globals, fake world)
    OBJPAGE = 0x00800000        # the object ends exactly here; this page is NOT mapped
    RET = 0x00100000

    def __init__(self, img, obj_size: int):
        import unicorn
        from unicorn import x86_const as C
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
        self.img, self.C = img, C
        self.obj_size = obj_size
        self.obj = self.OBJPAGE - obj_size
        u = self.uc
        # merge the section ranges first: mapping 352 MB one page at a time is far too slow,
        # and a section that overlaps an already-mapped page must still get its bytes written
        # (an unmapped literal pool would otherwise look like a fault).
        rng = sorted((img.base + x["va"] & ~0xFFF,
                      (img.base + x["va"] + max(x["vsize"], x["rsize"]) + 0xFFF) & ~0xFFF)
                     for x in img.secs)
        merged = []
        for lo, hi in rng:
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        for lo, hi in merged:
            u.mem_map(lo, hi - lo)
        for x in img.secs:
            if x["rsize"]:
                u.mem_write(img.base + x["va"],
                            img.data[x["raw"]:x["raw"] + min(x["rsize"], x["vsize"])])
        self.mapped = merged
        u.mem_map(self.STACK, 0x100000)
        u.mem_map(self.ARENA, 0x200000)
        u.mem_map(self.RET, 0x1000)
        u.mem_write(self.RET, b"\xc3")
        # the object's own page (the one BEFORE OBJPAGE).  OBJPAGE itself stays unmapped.
        u.mem_map(self.OBJPAGE - 0x1000, 0x1000)
        self.faults = []

    def w64(self, a, v):
        self.uc.mem_write(a, struct.pack("<Q", v & ((1 << 64) - 1)))

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def wf(self, a, v):
        self.uc.mem_write(a, struct.pack("<f", v))

    def rf(self, a):
        return struct.unpack("<f", self.uc.mem_read(a, 4))[0]

    def run(self, fn_va: int, regs: dict, *, stub_ret=0, max_ins=400000, trace=True,
            stub_outside=True):
        """Run fn_va to its return; every call leaving the function's own body is stubbed."""
        import unicorn
        from unicorn import x86_const as C
        u = self.uc
        body = {i.address for i in disasm_fn(self.img, fn_va)}
        self.calls, self.touch, self.faults = [], [], []
        stub_iter = iter(stub_ret) if isinstance(stub_ret, (list, tuple)) else None

        def hook_code(uc, addr, size, _):
            if addr in body or addr == self.RET:
                return
            sp = uc.reg_read(C.UC_X86_REG_RSP)
            try:
                ret = struct.unpack("<Q", uc.mem_read(sp, 8))[0]
            except Exception:
                uc.emu_stop(); return
            self.calls.append(addr)
            if stub_iter is not None:
                try:
                    v = next(stub_iter)
                except StopIteration:
                    v = 0
            else:
                v = stub_ret
            uc.reg_write(C.UC_X86_REG_RAX, v)
            uc.reg_write(C.UC_X86_REG_RSP, sp + 8)
            uc.reg_write(C.UC_X86_REG_RIP, ret)

        def hook_mem(uc, access, addr, size, value, _):
            if self.obj <= addr < self.obj + self.obj_size:
                self.touch.append((addr - self.obj, size, access))
            return True

        def hook_bad(uc, access, addr, size, value, _):
            self.faults.append((uc.reg_read(C.UC_X86_REG_RIP), addr, size, access))
            return False

        hooks = ([u.hook_add(unicorn.UC_HOOK_CODE, hook_code)] if stub_outside else []) + [
                 u.hook_add(unicorn.UC_HOOK_MEM_READ_UNMAPPED | unicorn.UC_HOOK_MEM_WRITE_UNMAPPED
                            | unicorn.UC_HOOK_MEM_FETCH_UNMAPPED, hook_bad)]
        if trace:
            hooks.append(u.hook_add(unicorn.UC_HOOK_MEM_READ | unicorn.UC_HOOK_MEM_WRITE, hook_mem))
        sp = self.STACK + 0x80000
        u.reg_write(C.UC_X86_REG_RSP, sp)
        self.w64(sp, self.RET)
        for r, v in regs.items():
            u.reg_write(getattr(C, "UC_X86_REG_" + r.upper()), v)
        err = None
        try:
            u.emu_start(fn_va, self.RET, count=max_ins)
        except unicorn.UcError as e:
            err = e
        for h in hooks:
            u.hook_del(h)
        return err


GLOBAL_PLAYER_TABLE = 0x1486bd888


def _world(g):
    """A minimal plausible set of structures: W, teamAI, matchCtx, WORLD, the player table."""
    A = g.ARENA
    W, teamAI, matchCtx, WORLD, players = A, A + 0x1000, A + 0x20000, A + 0x40000, A + 0x80000
    g.w64(W + 0x00, matchCtx)
    g.w64(W + 0x08, teamAI)
    g.w32(W + 0x18, 0)              # teamIdx
    g.w32(W + 0x1c, 7)              # ball-holder pid
    g.w32(W + 0x20, 1)
    g.w32(W + 0x24, 2)              # quota
    g.w64(matchCtx + 0x48, WORLD)
    g.w64(matchCtx + 0x30, matchCtx)
    for slot in range(11):
        g.w32(teamAI + 0x8f4c + 4 * slot, 0)
    tbl = A + 0x100000
    for i in range(31):
        p = players + i * 0x2000
        g.wf(p + 0x4f4, 20.0 - i)       # x  (pitch length axis, metres)
        g.wf(p + 0x4f8, 0.0)            # y
        g.wf(p + 0x4fc, -15.0 + 3 * i)  # z  (lateral)
        g.w64(tbl + i * 0x58 + 0x4058, p)
        g.w64(tbl + i * 0x58 + 0x55a8, p)
        g.w64(tbl + i * 0x58 + 0x35b0, p)
    for t in range(2):
        g.w64(tbl + t * 0x58 + 0x3450, teamAI)     # 0x1442d7090 reads this
    g.w32(WORLD + 0x28780, 7)                      # 0x1442de630 reads this (ball-holder pid)
    g.wf(WORLD + 0x25bbc, 0.0)
    g.wf(WORLD + 0x25bc0, 0.0)
    g.wf(WORLD + 0x25bc4, 0.0)
    g.uc.mem_write(teamAI + 0x28c, bytes([1]))     # attackDir = +1
    g.w64(GLOBAL_PLAYER_TABLE, tbl)
    return dict(W=W, teamAI=teamAI, matchCtx=matchCtx, WORLD=WORLD, players=players, tbl=tbl)


SELECTOR_DONORS = [
    ("vf3  cancel test", "CounterSpaceRun::vf3", 0x143dfb5a0, "sel_w_pid"),
    ("vf4  eligibility", "ActionSelectorScore::vf4", 0x143df0cf0, "sel_w_team"),
    ("vf5  score  (stock)", "LineBreak::vf5 -> 100.0f", 0x143e02700, "sel_w_pid_team"),
    ("vf6  target (stock)", "shared zero-vec3", 0x143d520d0, "sel_out_w_pid"),
    ("vf3  alt", "DiagonalRun::vf3", 0x143e05130, "sel_w_pid"),
]
EXECUTOR_DONORS = [
    ("vf4  destination", "ActionMove::vf4", 0x1442060f0, "this_out_ctx"),
    ("vf18 (uncalled by upd)", "ActionMove::vf18", 0x145625830, "this_ctx"),
    ("vf20 steering", "ActionMove::vf20", 0x1456220d0, "this_ctx"),
    ("vf20 alt", "ActionDiagonalRun::vf20", 0x144200e10, "this_ctx"),
]
# positive controls: these MUST fault, or the harness is not reaching the dangerous code
FATAL_CONTROLS = [
    ("ChanceSpaceRun::vf4  (selector, writes 0x2c8..0x307)", 0x143df6010, "sel_w_team", LINEBREAK_SIZE),
    ("ChanceSpaceRun::vf5  (selector, reads 0x2c8+4k)", 0x143df5950, "sel_w_pid_team", LINEBREAK_SIZE),
    ("ActionDiagonalRun::vf3 (executor, writes 0x30..0x5c)", 0x144200e70, "this_ctx", 0x40),
    ("ActionDiagonalRun::vf18 callee 0x1442010f0 (reads 0x4c..0x5b)", 0x1442010f0, "this_ctx", 0x40),
]


def _setup(g, va, obj_size, argmode, rnd):
    """Re-initialise only the small regions.  The 352 MB image is mapped once per function."""
    g.uc.mem_write(g.ARENA, bytes(0x200000))
    g.uc.mem_write(g.OBJPAGE - 0x1000, bytes(0x1000))
    w = _world(g)
    SEL = g.obj
    if obj_size == LINEBREAK_SIZE:
        g.w64(SEL, SEL_VFT["LineBreak"])
        g.w32(SEL + 0x128, 0x20)                 # action id, written by the LineBreak ctor
        g.uc.mem_write(SEL + 0xe4, bytes([1]))   # maxSlots, written by the LineBreak ctor
        g.w32(SEL + 0x2c0, 0)                    # the one private int the ctor writes
    else:
        g.w64(SEL, 0x146bbeb98)                  # ActionLineBreak vftable
        g.uc.mem_write(SEL + 0x30, bytes([1]))   # what ActionLineBreak::vf3 writes
    OUT = g.ARENA + 0x180000
    ctx = g.ARENA + 0x1a0000
    g.w64(ctx + 0x30, w["matchCtx"])
    g.w32(ctx + 4, rnd.randrange(22))
    regs = dict(rcx=SEL)
    if argmode == "sel_w_pid":
        regs.update(rdx=w["W"], r8=rnd.randrange(22))
    elif argmode == "sel_w_team":
        regs.update(rdx=w["W"], r8=w["teamAI"])
    elif argmode == "sel_w_pid_team":
        regs.update(rdx=w["W"], r8=rnd.randrange(22), r9=w["teamAI"])
    elif argmode == "sel_out_w_pid":
        regs.update(rdx=OUT, r8=w["W"], r9=rnd.randrange(22))
    elif argmode == "this_out_ctx":
        regs.update(rdx=OUT, r8=ctx)
    elif argmode == "this_ctx":
        regs.update(rdx=ctx, r8=OUT, r9=OUT + 0x40)
    return w, regs, OUT


def _classify(faults, obj_size):
    """A fault inside the guard page means the object was overrun.  Anything else is the harness
    reaching a structure we did not synthesise (a fuzzed stub returned a junk pointer, say) and
    says nothing about `this`."""
    oob = [x for x in faults if Guard.OBJPAGE <= x[1] < Guard.OBJPAGE + 0x1000]
    other = [x for x in faults if not (Guard.OBJPAGE <= x[1] < Guard.OBJPAGE + 0x1000)]
    return oob, other


def _guard_one(img, va, obj_size, argmode, trials=32, seed=1, _cache={}):
    import random
    rnd = random.Random(seed)
    key = (id(img), obj_size)
    g = _cache.get(key)
    if g is None:
        g = _cache[key] = Guard(img, obj_size)
    faults, calls, touched, reached = [], 0, set(), set()
    for _ in range(trials):
        w, regs, OUT = _setup(g, va, obj_size, argmode, rnd)
        stubs = [rnd.choice([0, 1, 2, 3, 5, 0xb, 0x15, 0xff, 0xffffffff,
                             w["matchCtx"], w["players"], w["teamAI"], w["tbl"]])
                 for _ in range(600)]
        g.run(va, regs, stub_ret=stubs)
        calls += len(g.calls)
        faults += g.faults
        for off, size, _a in g.touch:
            touched.add(off)
        reached |= set(g.calls)
    return faults, calls, touched, reached


def cmd_guard(a):
    img = Image(a.exe or INSTALLED)
    trials = a.trials
    print(f"== Unicorn guard-page memory proof   (image: {img.path})")
    print(f"   The LineBreak SELECTOR subobject is {LINEBREAK_SIZE:#x} bytes and sits at")
    print(f"   manager+0xb38, immediately followed by ActionSelectorDiagonalRun at manager+0xe00.")
    print(f"   Here the object is placed so sel+{LINEBREAK_SIZE:#x} is the first byte of an UNMAPPED")
    print(f"   page, so one byte touched past the end is a fault with an exact address.")
    print(f"   match::player::ActionLineBreak is 0x40 bytes and gets the same treatment.")
    print(f"   Every call out of the body is stubbed with a fuzzed return so branches are taken.\n")
    bad = 0
    for title, donors, size in (("SELECTOR donors  (object 0x2c8)", SELECTOR_DONORS, LINEBREAK_SIZE),
                                ("EXECUTOR donors  (object 0x40)", EXECUTOR_DONORS, 0x40)):
        print(f"-- {title}")
        for slot, nm, va, mode in donors:
            f, calls, touched, reached = _guard_one(img, va, size, mode, trials=trials)
            oob, other = _classify(f, size)
            if oob:
                bad += 1
            t = ("touches " + ", ".join(f"+{o:#x}" for o in sorted(touched))) if touched else "touches NOTHING in the object"
            print(f"   {slot:<22} {nm:<28} {va:#x}")
            print(f"        {trials} runs, {calls:6d} stubbed calls, {len(reached)} distinct callees; {t}")
            note = f"  ({len(other)} unrelated harness faults)" if other else ""
            print(f"        -> {'IN BOUNDS' if not oob else 'OVERRUNS THE OBJECT x' + str(len(oob))}{note}")
            for x in oob[:3]:
                print(f"           FAULT rip {x[0]:#x} at obj+{x[1] - (Guard.OBJPAGE - size):#x} size {x[2]}")
        print()
    print("-- POSITIVE CONTROLS: these are the donors that must NOT be used.")
    print("   If one of them came back clean, the harness is not reaching the dangerous block")
    print("   and the IN BOUNDS results above would be worthless.")
    seen_fault = 0
    for nm, va, mode, size in FATAL_CONTROLS:
        f, calls, touched, _r = _guard_one(img, va, size, mode, trials=max(6, trials // 3))
        oob, other = _classify(f, size)
        if oob:
            seen_fault += 1
            where = ", ".join(sorted({f"obj+{x[1] - (Guard.OBJPAGE - size):#x}" for x in oob})[:4])
            print(f"   {nm:<62} -> FAULTS as predicted at {where}")
        else:
            print(f"   {nm:<62} -> no fault reached (control INCONCLUSIVE)")
    print(f"\n   {seen_fault}/{len(FATAL_CONTROLS)} controls faulted; {bad} donor(s) out of bounds.")
    return 0 if bad == 0 else 1




# =================================================================================== the plan
#
# Everything below is keyed to facts this file proves: `sizes` for the object sizes and the
# zero-slack packing, `bounds` + `guard` for the borrow safety, `gate` for the quota, and
# `target` for the geometry.
#
# BORROWED (redirect a vtable slot at an address that already exists in the image):
#   selector vf3 <- match::ai::ActionSelectorCounterSpaceRun::vf3   0x143dfb5a0
#   selector vf4 <- match::ai::ActionSelectorScore::vf4             0x143df0cf0
#   executor vf4  <- match::ai::ActionMove::vf4                     0x1442060f0
#   executor vf18 <- match::ai::ActionMove::vf18                    0x145625830
#   executor vf20 <- match::ai::ActionMove::vf20                    0x1456220d0
# NEW (a cave):
#   selector vf6 (stage 2) — the line-break run target
#   selector vf5 (stage 3) — the score that picks the runner
# NOT BORROWED, and why: see FATAL_CONTROLS and `guard`.

OFFSIDE_FN = 0x143d24d60        # (matchCtx, teamIdx) -> float: this team's attacking offside line
PLAYER_FN = 0x1442d6f60         # (matchCtx, pid)     -> match player object (pos at +0x4f4)

SEL_SLOT = {n: SEL_VFT["LineBreak"] + 8 * n for n in range(7)}
EXE_VFT = 0x146bbeb98
EXE_SLOT = {n: EXE_VFT + 8 * n for n in range(23)}

STAGE1 = [
    # (vtable slot address, old target, new target, what it is)
    (SEL_SLOT[3], 0x140c853c0, 0x143dfb5a0,
     "selector vf3 cancel-test: 'never cancel' stub -> CounterSpaceRun::vf3 (reads no member)"),
    (SEL_SLOT[4], 0x140c837d0, 0x143df0cf0,
     "selector vf4 eligibility: 'mask 0' stub -> ActionSelectorScore::vf4 (reads only this+0x128)"),
    (EXE_SLOT[4], 0x143d520d0, 0x1442060f0,
     "executor vf4 destination: zero-vec3 (the CENTRE SPOT) -> ActionMove::vf4 (own position)"),
    (EXE_SLOT[18], 0x140c83810, 0x145625830,
     "executor vf18: 'return true' stub -> ActionMove::vf18 (reads only the vptr)"),
    (EXE_SLOT[20], 0x140c83910, 0x1456220d0,
     "executor vf20 steering: 'ret' stub -> ActionMove::vf20 (reads no member)"),
]

# ---------------------------------------------------------------------------- stage 2 payload
#
# vf6(sel /*rcx*/, vec3* out /*rdx*/, W /*r8*/, int pid /*r9d*/) -> vec3*   (dispatcher 0x143df123e)
#
# The target's X is taken from the engine's OWN offside line (0x143d24d60), which is what every
# shipped run target uses, so the run is onside by construction and cannot build an offside trap.
# The Z cuts the runner in toward the middle: that is what makes it a LINE BREAK rather than
# ChanceSpaceRun (which maximises divergence from the ball, i.e. runs away into space).
# out.y = 0.0, which is >= 0 and therefore a VALID target under the engine's own rule.
VF6_ASM = """
push rbx
push rsi
push rdi
sub rsp, 0x30
mov qword ptr [rsp + 0x20], rcx
mov rbx, rdx
mov edi, r9d
mov rsi, r8
mov rcx, qword ptr [rsi]
mov edx, dword ptr [rsi + 0x18]
call $offside
movss dword ptr [rsp + 0x28], xmm0
mov rcx, qword ptr [rsi]
mov edx, edi
call $player
test rax, rax
je @fail
movss xmm1, dword ptr [rax + 0x4fc]
mov ecx, 0x3eb33333
movd xmm2, ecx
mulss xmm1, xmm2
mov ecx, 0x41f00000
movd xmm2, ecx
minss xmm1, xmm2
xorps xmm3, xmm3
subss xmm3, xmm2
maxss xmm1, xmm3
movss xmm0, dword ptr [rsp + 0x28]
movss dword ptr [rbx], xmm0
xorps xmm2, xmm2
movss dword ptr [rbx + 4], xmm2
movss dword ptr [rbx + 8], xmm1
jmp @kind
fail:
xorps xmm0, xmm0
movss dword ptr [rbx], xmm0
movss dword ptr [rbx + 4], xmm0
movss dword ptr [rbx + 8], xmm0
kind:
cmp edi, 0x15
ja @done
mov eax, 0xba2e8ba3
mul edi
shr edx, 3
imul eax, edx, 0xb
mov ecx, edi
sub ecx, eax
mov rax, qword ptr [rsp + 0x20]
mov byte ptr [rax + rcx + 0xe5], 0
done:
mov rax, rbx
add rsp, 0x30
pop rdi
pop rsi
pop rbx
ret
"""
VF6_TUNABLES = {
    "Z_KEEP": (0x3eb33333, 0.35, "fraction of the runner's own lateral offset he keeps; "
                                 "lower = cuts harder into the middle (0.0 = straight to the "
                                 "central seam, 1.0 = straight up his own channel)"),
    "HALF_W": (0x41f00000, 30.0, "hard clamp on |target z| in metres"),
}

# ---------------------------------------------------------------------------- stage 3 payload
#
# vf5(sel /*rcx*/, W /*rdx*/, int pid /*r8d*/, teamAI /*r9*/) -> float   (dispatcher 0x143df1256)
#
# Score = BASE + GAIN * runway, runway = (offsideLine - player.x) * attackDir, i.e. how much room
# the runner still has BEHIND the defensive line — the same quantity DiagonalRun::vf5 uses.
# 0.0 means "not a candidate" and is returned for the ball holder and for anyone with no runway.
# The dispatcher sorts DESCENDING and stops at the first score <= 0, so the zeros collect at the
# bottom and the walk stops exactly where it should.  The computed branch can never reach 0:
# its minimum is BASE + GAIN * MIN_RUN.
VF5_ASM = """
push rbx
push rsi
push rdi
sub rsp, 0x30
mov rbx, rdx
mov esi, r8d
mov rdi, r9
mov eax, dword ptr [rbx + 0x1c]
cmp eax, esi
je @nocand
mov rcx, qword ptr [rbx]
mov edx, dword ptr [rbx + 0x18]
call $offside
movss dword ptr [rsp + 0x28], xmm0
mov rcx, qword ptr [rbx]
mov edx, esi
call $player
test rax, rax
je @nocand
movss xmm0, dword ptr [rsp + 0x28]
subss xmm0, dword ptr [rax + 0x4f4]
movsx ecx, byte ptr [rdi + 0x28c]
cvtsi2ss xmm2, ecx
mulss xmm0, xmm2
mov ecx, 0x40000000
movd xmm3, ecx
comiss xmm0, xmm3
jb @nocand
mov ecx, 0x41f00000
movd xmm3, ecx
minss xmm0, xmm3
mov ecx, 0x40000000
movd xmm3, ecx
mulss xmm0, xmm3
mov ecx, 0x42200000
movd xmm3, ecx
addss xmm0, xmm3
jmp @out
nocand:
xorps xmm0, xmm0
out:
add rsp, 0x30
pop rdi
pop rsi
pop rbx
ret
"""
VF5_TUNABLES = {
    "MIN_RUN": (0x40000000, 2.0, "metres of runway behind the line below which a player is NOT a "
                                 "candidate (returns the 0.0 sentinel)"),
    "MAX_RUN": (0x41f00000, 30.0, "runway is capped here before scoring"),
    "GAIN": (0x40000000, 2.0, "score points per metre of runway"),
    "BASE": (0x42200000, 40.0, "floor of the computed branch; the score can never reach 0 from "
                               "above, so a real candidate can never truncate the sorted walk"),
}


# ================================================================================ geometry proof
def cmd_target(a):
    """Emulate the engine's own offside-line getter, then the stage-2 cave, on real bytes."""
    import random
    img = Image(a.exe or INSTALLED)
    print("== the offside line is the engine's own number, not ours")
    print(f"   {OFFSIDE_FN:#x}(matchCtx, teamIdx) reads [WORLD + 20*opp + 0x44] where")
    print("   opp = (teamIdx == 0), i.e. the OPPOSING team's row of the per-team line table")
    print("   {TopLine, MiddleLine, LastLine, OffsideLine, -} at WORLD+0x38+20*t.\n")
    g = Guard(img, LINEBREAK_SIZE)
    rnd = random.Random(7)
    for rowA, rowB in ((( -8, -18, -34, -30), (12, 22, 40, 36)),
                       ((-20, -30, -44, -41), (3, 9, 18, 15))):
        _setup(g, OFFSIDE_FN, LINEBREAK_SIZE, "sel_w_team", rnd)
        w = _world(g)
        for t, row in ((0, rowA), (1, rowB)):
            for k, v in enumerate(row):
                g.wf(w["WORLD"] + 0x38 + 20 * t + 4 * k, float(v))
        g.w32(w["WORLD"] + 0x28780, 7)
        for teamIdx in (0, 1):
            g.run(OFFSIDE_FN, dict(rcx=w["matchCtx"], rdx=teamIdx), trace=False, stub_outside=False)
            from unicorn import x86_const as C
            got = struct.unpack("<f", struct.pack("<I", g.uc.reg_read(C.UC_X86_REG_XMM0) & 0xFFFFFFFF))[0]
            want = (rowB if teamIdx == 0 else rowA)[3]
            print(f"   rows {rowA}/{rowB}  teamIdx {teamIdx} -> {got:+8.2f}   "
                  f"(opposing OffsideLine {want:+.2f})  {'MATCH' if abs(got - want) < 1e-3 else 'MISMATCH'}")
    return 0




# ==================================================================== cave layout + spec writing
def _ca():
    sys.path.insert(0, str(REPO / "tools"))
    import cave_alloc
    return cave_alloc


def _vtable_patch(img, slot_va, old, new, note):
    cur = img.read(slot_va, 8)
    want = struct.pack("<Q", old)
    if cur != want:
        raise SystemExit(f"vtable slot {slot_va:#x} holds {cur.hex()}, expected {want.hex()} "
                         f"— the image is not the one this spec was built for")
    return dict(name=note, va=f"{slot_va:#x}", expect=cur.hex(),
                patch=struct.pack("<Q", new).hex(), kind="vtable")


def _layout(ca, asm, target, pristine, anchor):
    pool, rej = ca.cave_pool(target=target, pristine=pristine, min_len=12, anchor=anchor, safety="A")
    lay = ca.layout_payload(asm, pool=pool, exits=(), externals=dict(offside=OFFSIDE_FN,
                                                                    player=PLAYER_FN), cells={})
    again = ca.layout_payload(asm, pool=pool, exits=(), externals=dict(offside=OFFSIDE_FN,
                                                                       player=PLAYER_FN), cells={})
    if [c.code for c in lay.chunks] != [c.code for c in again.chunks]:
        raise SystemExit("NON-DETERMINISTIC layout")
    problems = ca.verify_layout(lay, target=target)
    if problems:
        raise SystemExit("verify_layout: " + "; ".join(problems))
    problems = ca.audit_caves([c.cave for c in lay.chunks], target=target, pristine=pristine)
    if problems:
        raise SystemExit("audit_caves: " + "; ".join(problems))
    # Another session on this machine may be allocating caves from the same pool and ledger while
    # we run.  cave_pool filtered the claims that existed when it was built; re-check them now,
    # immediately before the spec is written, so a concurrent reservation cannot be overwritten.
    mine = sorted((c.va, c.end) for c in lay.chunks)
    for va, end, owner in ca.claimed_ranges():
        for lo, hi in mine:
            if lo < end and hi > va:
                raise SystemExit(f"cave {lo:#x}..{hi:#x} collides with {owner} ({va:#x}..{end:#x}) "
                                 f"— another spec claimed it after our pool was built")
    return lay, len(pool), rej


def _emulate_cave(img, lay, which, *, verbose=True):
    """Run the EXACT emitted bytes, at the EXACT addresses, through the real call chain."""
    import random
    from unicorn import x86_const as C
    g = Guard(img, LINEBREAK_SIZE)
    for va, code in lay.overlays():
        g.uc.mem_write(va, code)
    rnd = random.Random(11)
    rows = []

    def world(offside, holder=7):
        w = _world(g)
        for t, row in ((0, (-8, -18, -34, -30)), (1, (12, 22, 40, offside))):
            for k, v in enumerate(row):
                g.wf(w["WORLD"] + 0x38 + 20 * t + 4 * k, float(v))
        g.w32(w["WORLD"] + 0x28780, holder)
        g.w32(w["W"] + 0x1c, holder)
        g.uc.mem_write(w["teamAI"] + 0x28c, bytes([1]))     # attackDir = +1
        return w

    if which == "vf6":
        for (px, pz, offside) in [(10.0, -28.0, 36.0), (10.0, 0.0, 36.0), (22.0, 14.0, 36.0),
                                  (-5.0, 31.0, 20.0), (0.0, -40.0, 5.0), (30.0, 2.0, 36.0)]:
            _setup(g, lay.entry, LINEBREAK_SIZE, "sel_out_w_pid", rnd)
            w = world(offside)
            pid = 5
            p = w["players"] + pid * 0x2000
            g.wf(p + 0x4f4, px); g.wf(p + 0x4fc, pz)
            OUT = g.ARENA + 0x180000
            g.uc.mem_write(g.obj + 0xe5 + (pid % 11), bytes([0xAB]))   # poison the kind byte
            err = g.run(lay.entry, dict(rcx=g.obj, rdx=OUT, r8=w["W"], r9=pid),
                        trace=True, stub_outside=False)
            tx, ty, tz = g.rf(OUT), g.rf(OUT + 4), g.rf(OUT + 8)
            kind = g.uc.mem_read(g.obj + 0xe5 + (pid % 11), 1)[0]
            oob, _o = _classify(g.faults, LINEBREAK_SIZE)
            rows.append(dict(px=px, pz=pz, offside=offside, tx=tx, ty=ty, tz=tz,
                             kind=kind, oob=len(oob), err=str(err) if err else ""))
        if verbose:
            print("   player.x  player.z   offsideX |  target.x  target.y  target.z | kind | onside?")
            for r in rows:
                on = "YES" if abs(r["tx"] - r["offside"]) < 1e-3 else "NO  <-- OFFSIDE BUG"
                print(f"   {r['px']:8.1f} {r['pz']:9.1f} {r['offside']:10.1f} |"
                      f" {r['tx']:9.2f} {r['ty']:9.2f} {r['tz']:9.2f} | {r['kind']:#04x} | {on}"
                      + (f"  ERR {r['err']}" if r["err"] else "")
                      + ("  OVERRUN!" if r["oob"] else ""))
    else:
        for (px, offside, holder, adir) in [(10.0, 36.0, 7, 1), (34.0, 36.0, 7, 1),
                                            (36.0, 36.0, 7, 1), (40.0, 36.0, 7, 1),
                                            (-20.0, 36.0, 7, 1), (10.0, 36.0, 5, 1),
                                            (-10.0, -36.0, 7, -1), (-34.0, -36.0, 7, -1)]:
            _setup(g, lay.entry, LINEBREAK_SIZE, "sel_w_pid_team", rnd)
            w = world(offside if adir > 0 else 36.0, holder)
            if adir < 0:
                for k, v in enumerate((-8, -18, -34, offside)):
                    g.wf(w["WORLD"] + 0x38 + 4 * k, float(v))
            g.uc.mem_write(w["teamAI"] + 0x28c, bytes([adir & 0xFF]))
            g.w32(w["W"] + 0x18, 1 if adir < 0 else 0)
            pid = 5
            p = w["players"] + pid * 0x2000
            g.wf(p + 0x4f4, px)
            err = g.run(lay.entry, dict(rcx=g.obj, rdx=w["W"], r8=pid, r9=w["teamAI"]),
                        trace=True, stub_outside=False)
            sc = struct.unpack("<f", struct.pack("<I", g.uc.reg_read(C.UC_X86_REG_XMM0) & 0xFFFFFFFF))[0]
            oob, _o = _classify(g.faults, LINEBREAK_SIZE)
            rows.append(dict(px=px, offside=offside, holder=holder, adir=adir, score=sc,
                             oob=len(oob), err=str(err) if err else ""))
        if verbose:
            print("   player.x  offsideX  dir  holder |   score  | meaning")
            for r in rows:
                runway = (r["offside"] - r["px"]) * r["adir"]
                if r["holder"] == 5:
                    why = "ball holder -> sentinel"
                elif r["score"] == 0.0:
                    why = f"runway {runway:+.1f} m < 2 m -> sentinel"
                else:
                    why = f"runway {runway:+.1f} m -> candidate"
                print(f"   {r['px']:8.1f} {r['offside']:9.1f} {r['adir']:+4d} {r['holder']:7d} |"
                      f" {r['score']:8.3f} | {why}"
                      + ("  OVERRUN!" if r["oob"] else "")
                      + (f"  ERR {r['err']}" if r["err"] else ""))
    return rows


def cmd_build(a):
    ca = _ca()
    target = ca.Image(Path(a.exe) if a.exe else ca.EXE)
    pristine = ca.Image(ca.PRISTINE) if ca.PRISTINE.exists() else None
    img = Image(a.exe or INSTALLED)
    outdir = REPO / "tools" / "data" / "patches"
    print(f"== target {target.path.name}  sha1 {target.sha1[:16]}…")

    # ---------------------------------------------------------------- stage 1: no cave at all
    p1 = [_vtable_patch(img, va, old, new, note) for va, old, new, note in STAGE1]
    doc1 = dict(
        description="LineBreak stage 1 — wake the dead selector (vtable redirects only, no code). "
                    "Points match::ai::ActionSelectorLineBreak's 'return false' cancel test and "
                    "'mask 0' eligibility builder at two implementations that already exist in the "
                    "image and provably touch no member past LineBreak's 0x2c8-byte subobject, and "
                    "un-disables three movement slots on the 0x40-byte match::player::ActionLineBreak "
                    "husk. The run still has no geometry of its own: that is stage 2.",
        linebreak=dict(
            stage=1, action_id="0x20",
            selector=dict(vftable=f"{SEL_VFT['LineBreak']:#x}", size="0x2c8",
                          placed_at="ActionSelectorManager+0xb38",
                          next_object="ActionSelectorDiagonalRun at +0xe00 (zero slack)"),
            executor=dict(vftable=f"{EXE_VFT:#x}", size="0x40"),
            borrowed_not_written=True,
            proof="tools/emu_linebreak.py guard  (Unicorn, guard page at sel+0x2c8 / this+0x40)"),
        patches=p1)
    (outdir / "linebreak-1-selector.json").write_text(json.dumps(doc1, indent=1) + "\n", "utf-8")
    print(f"   stage 1 -> tools/data/patches/linebreak-1-selector.json  ({len(p1)} vtable slots, 0 caves)")

    # ---------------------------------------------------------------- stage 2: vf6 target cave
    lay6, npool, rej = _layout(ca, VF6_ASM, target, pristine, DISPATCH)
    print(f"\n   stage 2 cave: {lay6.payload_bytes()} B payload in {len(lay6.chunks)} chunks "
          f"({lay6.total_used()} B used), entry {lay6.entry:#x}, pool {npool} free tier-A caves")
    rows6 = _emulate_cave(img, lay6, "vf6")
    if any(r["oob"] or r["err"] for r in rows6):
        raise SystemExit("stage 2 cave faulted — not writing the spec")
    if any(abs(r["tx"] - r["offside"]) > 1e-3 for r in rows6):
        raise SystemExit("stage 2 cave produced a target off the offside line — not writing the spec")
    p2 = lay6.patches(target, "linebreak-vf6")
    p2.append(_vtable_patch(img, SEL_SLOT[6], 0x143d520d0, lay6.entry,
                            f"selector vf6 run target: shared zero-vec3 -> cave {lay6.entry:#x}"))
    doc2 = dict(
        description="LineBreak stage 2 — give the run its own geometry. Replaces the selector's "
                    "shared zero-vec3 vf6 with a cave that targets the ENGINE'S OWN offside line "
                    f"({OFFSIDE_FN:#x}) with the runner's lateral offset cut toward the middle, so "
                    "the run breaks the line through the central seam instead of drifting away "
                    "from the ball like ChanceSpaceRun. Onside by construction. Apply on top of "
                    "stage 1.",
        linebreak=dict(stage=2, slot="selector vf6", entry=f"{lay6.entry:#x}",
                       signature="vec3* vf6(sel /*rcx*/, vec3* out /*rdx*/, W /*r8*/, int pid /*r9d*/)",
                       tunables={k: dict(imm32=f"{v[0]:#010x}", value=v[1], what=v[2])
                                 for k, v in VF6_TUNABLES.items()},
                       emulated=[{k: (round(v, 3) if isinstance(v, float) else v)
                                  for k, v in r.items()} for r in rows6]),
        cave_layout=lay6.provenance(), patches=p2)
    doc2["cave_layout"]["target_image_sha1"] = target.sha1
    (outdir / "linebreak-2-run-target.json").write_text(json.dumps(doc2, indent=1) + "\n", "utf-8")
    ca.reserve_caves(lay6, "linebreak-2-run-target.json")
    print(f"   stage 2 -> tools/data/patches/linebreak-2-run-target.json  ({len(p2)} entries)")

    # ---------------------------------------------------------------- stage 3: vf5 score cave
    lay5, npool5, _r = _layout(ca, VF5_ASM, target, pristine, DISPATCH)
    print(f"\n   stage 3 cave: {lay5.payload_bytes()} B payload in {len(lay5.chunks)} chunks "
          f"({lay5.total_used()} B used), entry {lay5.entry:#x}")
    rows5 = _emulate_cave(img, lay5, "vf5")
    if any(r["oob"] or r["err"] for r in rows5):
        raise SystemExit("stage 3 cave faulted — not writing the spec")
    if any(r["score"] < 0 for r in rows5):
        raise SystemExit("stage 3 cave returned a NEGATIVE score — that truncates the sorted walk")
    p3 = lay5.patches(target, "linebreak-vf5")
    p3.append(_vtable_patch(img, SEL_SLOT[5], 0x143e02700, lay5.entry,
                            f"selector vf5 score: flat 100.0f -> cave {lay5.entry:#x}"))
    doc3 = dict(
        description="LineBreak stage 3 — pick the right runner. Replaces the selector's flat "
                    "100.0f vf5 with a cave that scores by RUNWAY behind the opposition defensive "
                    "line (the same quantity DiagonalRun::vf5 uses), returns the engine's 0.0 "
                    "'not a candidate' sentinel for the ball holder and for anyone with under 2 m "
                    "of runway, and can never return a negative score. Apply on top of stages 1-2.",
        linebreak=dict(stage=3, slot="selector vf5", entry=f"{lay5.entry:#x}",
                       signature="float vf5(sel /*rcx*/, W /*rdx*/, int pid /*r8d*/, teamAI /*r9*/)",
                       tunables={k: dict(imm32=f"{v[0]:#010x}", value=v[1], what=v[2])
                                 for k, v in VF5_TUNABLES.items()},
                       emulated=[{k: (round(v, 3) if isinstance(v, float) else v)
                                  for k, v in r.items()} for r in rows5]),
        cave_layout=lay5.provenance(), patches=p3)
    doc3["cave_layout"]["target_image_sha1"] = target.sha1
    (outdir / "linebreak-3-score.json").write_text(json.dumps(doc3, indent=1) + "\n", "utf-8")
    ca.reserve_caves(lay5, "linebreak-3-score.json")
    print(f"   stage 3 -> tools/data/patches/linebreak-3-score.json  ({len(p3)} entries)")
    print("\n   NOTHING WAS APPLIED.  Apply one stage at a time with tools/exe_patch.py.")
    return 0




# ============================================================ dry-run + byte-exact round trip
SPECS = ["linebreak-1-selector.json", "linebreak-2-run-target.json", "linebreak-3-score.json"]


def cmd_check(a):
    """`exe_patch --dry-run` against the real images, then a real apply/remove on a COPY."""
    import hashlib
    import shutil
    import subprocess
    import tempfile
    patches = REPO / "tools" / "data" / "patches"
    exe_patch = REPO / "tools" / "exe_patch.py"

    def run(*args):
        return subprocess.run([sys.executable, str(exe_patch), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    print("== dry-run against the INSTALLED image (nothing is written)")
    for s in SPECS:
        r = run("--exe", str(INSTALLED), "apply", str(patches / s), "--dry-run")
        print(f"-- {s}  rc={r.returncode}")
        for line in (r.stdout + r.stderr).strip().splitlines():
            print("   " + line)

    print("\n== dry-run against the PRISTINE image (the specs are image-independent: every byte")
    print("   they touch is a vtable slot or int3 padding, identical in both images)")
    for s in SPECS:
        r = run("--exe", str(PRISTINE), "apply", str(patches / s), "--dry-run")
        print(f"-- {s}  rc={r.returncode}  {'OK' if r.returncode == 0 else 'REFUSED'}")

    print("\n== byte-exact round trip on a scratchpad COPY of the exe")
    tmp = Path(tempfile.mkdtemp(prefix="linebreak-"))
    work = tmp / "eFootball.exe"
    try:
        print(f"   copying {PRISTINE.stat().st_size / 1e6:.0f} MB -> {work}")
        shutil.copy2(PRISTINE, work)

        def sha(p):
            h = hashlib.sha1()
            with open(p, "rb") as f:
                for c in iter(lambda: f.read(1 << 24), b""):
                    h.update(c)
            return h.hexdigest()

        before = sha(work)
        print(f"   before        {before}")
        for s in SPECS:
            r = run("--exe", str(work), "apply", str(patches / s))
            print(f"   apply  {s:<30} rc={r.returncode}")
            if r.returncode:
                print("   " + (r.stdout + r.stderr).strip()[:400])
                return 1
        after = sha(work)
        print(f"   all applied   {after}   ({'CHANGED' if after != before else 'NO CHANGE - BUG'})")
        for s in reversed(SPECS):
            r = run("--exe", str(work), "remove", str(patches / s))
            print(f"   remove {s:<30} rc={r.returncode}")
            if r.returncode:
                print("   " + (r.stdout + r.stderr).strip()[:400])
                return 1
        end = sha(work)
        print(f"   after remove  {end}")
        ok = end == before
        print(f"\n   ROUND TRIP: {'BYTE-EXACT' if ok else 'FAILED - the copy did not return to its'
                                                        ' original bytes'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"   (working copy {tmp} deleted; the installed game was never touched)")


# ================================================================================ the quota gate
def cmd_gate(a):
    img = Image(a.exe or INSTALLED)
    print("== the quota for action 0x20 (LineBreak), read out of the shipped switch")
    print("   0x1442f9a90(matchCtx, teamIdx, actionId) reads attackLevel = byte[teamAI+0xb450]")
    print("   (0..4) then switches on actionId - 0x1d through the table at 0x1442f9ca4.")
    blocks = {}
    for k in range(0x12):
        blocks[0x1d + k] = BASE + img.u32(0x1442f9ca4 + 4 * k)
    named = {0x1d: "SecondLineSpaceRun", 0x1e: "ChanceSpaceRun", 0x1f: "CounterSpaceRun",
             0x20: "LineBreak", 0x21: "DiagonalRun", 0x2e: "PullAway"}
    import capstone
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM
    for aid, blk in sorted(blocks.items()):
        if aid not in named:
            continue
        tbl, tail = None, None
        for ins in list(md().disasm(img.read(blk, 0x40), blk))[:12]:
            if ins.mnemonic == "mov" and ins.operands[0].type == X86_OP_MEM \
                    and ins.operands[0].mem.disp == -0x10 and ins.operands[1].type == X86_OP_IMM:
                tbl = ins.operands[1].imm
            if ins.mnemonic == "mov" and ins.operands[0].type == X86_OP_MEM \
                    and ins.operands[0].mem.disp == -0xc:
                tail = ins.operands[1].imm if ins.operands[1].type == X86_OP_IMM else "dil"
        q = list(struct.pack("<I", tbl)) + [tail] if tbl is not None else []
        print(f"   {aid:#04x} {named[aid]:<20} block {blk:#x}  quota by attack level = {q}")
    print("\n== the gate that can force LineBreak's quota to 0")
    print("   0x143df0080 fills the quota array at [rsp+0x44 + 4*actionId], then:")
    print("     0x143df02c5  call 0x1442e4c00(playPoint, 0x15)")
    print("     if it returns FALSE -> [rsp+0xc4] = 0  (0x44 + 4*0x20 = LineBreak)")
    print("                         -> [rsp+0xfc] = 0  (0x44 + 4*0x2e = PullAway)")
    print("   0x1442e4c00(v, k) = |0x1442e48f0(v, k)| > 1.19e-7, i.e. 'tactical parameter k is")
    print("   non-zero'.  Sibling gates: k=0x13 zeroes SecondLine+Chance, 0x14 zeroes Counter,")
    print("   0x16 zeroes Diagonal.  So k is a TACTICS index, one per run family.")
    print("\n   NOT CONFIRMED: the brief's '0x15 is a difficulty table row {0,0,0,1,1,1,1,1,1,1},")
    print("   off at the three lowest difficulties'.  Nothing at 0x1442e4c00 reads a difficulty")
    print("   level; it reads a per-playPoint tactical value.  Treat 'set a high difficulty' as")
    print("   unproven and watch instead for the quota array being non-zero in open play.")
    return 0




# ========================================================= does stage 1 actually produce a run?
def cmd_plumb(a):
    """Run the borrowed eligibility builder on the game's own bytes, real call chain, no stubs."""
    import random
    from unicorn import x86_const as C
    img = Image(a.exe or INSTALLED)
    g = Guard(img, LINEBREAK_SIZE)
    rnd = random.Random(3)
    print("== stage 1 end to end: ActionSelectorScore::vf4(sel, W, teamAI) -> 11-bit mask")
    print("   0x143df0cf0 walks slot 0..10, reads each slot's CURRENT action from")
    print("   teamAI+0x8f4c+4*slot, asks 0x144300ba0 for the slot's role and then the engine's")
    print("   own transition gate 0x1442ed7c0(cur, role, 0x20, teamAI) whether that slot may")
    print("   switch to LineBreak.  Its only `this` access is [this+0x128] = the action id, which")
    print("   the LineBreak ctor writes as 0x20 at 0x143d51cb7.  Nothing is stubbed here.\n")
    for label, fill in (("all 11 slots idle (action 0)", 0),
                        ("all 11 already on ChanceSpaceRun (0x1e)", 0x1e),
                        ("all 11 already on CounterSpaceRun (0x1f)", 0x1f),
                        ("all 11 already on DiagonalRun (0x21)", 0x21),
                        ("all 11 on CenteringGet (0x26)", 0x26),
                        ("all 11 on PullAway (0x2e)", 0x2e),
                        ("all 11 already on LineBreak (0x20)", 0x20),
                        ("slots 0-5 idle, 6-10 on ChanceSpaceRun", None)):
        _setup(g, 0x143df0cf0, LINEBREAK_SIZE, "sel_w_team", rnd)
        w = _world(g)
        for s in range(11):
            g.w32(w["teamAI"] + 0x8f4c + 4 * s, (0 if s < 6 else 0x1e) if fill is None else fill)
        err = g.run(0x143df0cf0, dict(rcx=g.obj, rdx=w["W"], r8=w["teamAI"]),
                    trace=True, stub_outside=False)
        m = g.uc.reg_read(C.UC_X86_REG_EAX) & 0x7ff
        oob, _o = _classify(g.faults, LINEBREAK_SIZE)
        print(f"   {label:<42} mask {m:#05x} = {bin(m)[2:].zfill(11)}  "
              f"({bin(m).count('1'):2d} candidates)"
              + ("  OVERRUN" if oob else "") + (f"  ERR {err}" if err else ""))
    print("\n   Reading: a slot already holding ANY run action cannot be taken (every run action")
    print("   ties at rank 2 in 0x1442ed8d0, and the gate needs rank(new) < rank(cur)).  LineBreak")
    print("   bids 5th, so at a high attack level the four earlier bidders can starve it.  If")
    print("   stage 1 produces nothing in game, that is the first thing to suspect, not the patch.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sizes").set_defaults(fn=cmd_sizes)
    sub.add_parser("vtables").set_defaults(fn=cmd_vtables)
    sub.add_parser("target").set_defaults(fn=cmd_target)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("gate").set_defaults(fn=cmd_gate)
    sub.add_parser("plumb").set_defaults(fn=cmd_plumb)
    g = sub.add_parser("guard"); g.add_argument("--trials", type=int, default=32); g.set_defaults(fn=cmd_guard)
    p = sub.add_parser("bounds"); p.add_argument("va"); p.set_defaults(fn=cmd_bounds)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
