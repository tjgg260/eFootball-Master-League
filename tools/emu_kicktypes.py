#!/usr/bin/env python3
"""
emu_kicktypes.py - WHICH KINDS OF KICK CAN MIS-HIT AT ALL.  Emulation + static proof.

Nothing here touches the game.  Images are opened READ-ONLY (mmap ACCESS_READ) and their pages are
lazily copied into a Unicorn address space; every "patch" is an emulator-only overlay.  By default
the PRISTINE backup is emulated; `--exe live` emulates the installed image (which already carries
technique-realism + scuff-wobble entries 1/2 + knuckle-off + linked-spin).

    python tools/emu_kicktypes.py                 # every section
    python tools/emu_kicktypes.py --only S4 S6    # selected sections
    python tools/emu_kicktypes.py --exe live      # against the installed exe

THE TWO MODELS (this tool's headline result)

  * IN-PLAY kicks use the error builder 0x14401a900.  It is reached from exactly ONE place:
    match::anime::action::Kick::vf8 0x143ed0f80 -> 0x144016a70 -> 0x14401a900 (S1).
    Kick::vf8 is dispatched from exactly TWO sites (S2): the kick finaliser 0x143ea46c0, which
    looks the action object up by the player's current action id [player+0xad0], and
    goal_keeper::PuntKick::vf8 0x143f2e9c0, which explicitly forwards to the action-8 object.
    Only action ids 8, 9 and 0xa map to the Kick object, so only in-play passes/shots (+ the GK
    punt) ever see the builder.
  * SET PIECES use a completely separate model, 0x143f05730, called from Restart::vf8 0x143f05150.
    Two jump tables decide who gets any error at all (S5/S6): only direct free kicks and the
    standard corner do.  Quick restarts, seamless corners/goal kicks, penalties, throw-ins,
    kickoffs and goal kicks come out mathematically exact.

Sections
  S1  the single static path into the builder, and the single caller of each randomiser.
  S2  action id -> action class table (from the work-object ctor 0x143eee750 + the two init
      functions), the vf8 of every action class read straight out of its vftable, and the two
      vf8 dispatch sites found by scanning every `call/jmp qword ptr [reg+0x40]` in match code.
  S3  the 176-entry kick-property table 0x14804e0e0 decoded by EMULATING the game's own accessors
      (0x143eda730 = error class byte13, 0x143ed80f0 = kind byte12, 0x143edf8b0 = kind<=1), and
      0x143ed7440 emulated over every kick id to show which ids take the HEADING ability path.
  S4  the in-play builder run end to end with controlled cleanliness slots: the output ceilings
      depend ONLY on the c-slots, never on the ability factor f directly; c=1 on an axis gives a
      ceiling of EXACTLY zero.  Plus the flat kick-class multiplier (0.90/0.88/0.86/none) and the
      forced-exact predicate 0x143edf000.
  S5  the set-piece model 0x143f05730 emulated per action id: the measured azimuth / elevation /
      speed / spin deviation for a 40-, 70- and 99-rated taker.
  S6  the two set-piece jump tables printed byte by byte, with the VA of every index byte (these
      are the cheapest levers).
  S7  summary table: kick kind -> reaches builder? can mis-hit today? what limits it.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import capstone                                                      # noqa: E402
from unicorn import UC_HOOK_CODE, UcError                            # noqa: E402
from unicorn import x86_const as X                                   # noqa: E402

from exe_map import Image as MapImage, scan_xrefs                    # noqa: E402
from exe_census import load_pdata                                    # noqa: E402
from dt270_schema_gen import Image as EmuImage                       # noqa: E402
from emu_kickerror import (Emu, f2i, i2f, ARENA, STACK_TOP, RET_MAGIC, GPR, XMM,   # noqa: E402
                           BUILDER, BUILDER_END, FOLD, COOKIE_CHECK, F_ABILITY,
                           PLAYER, OUT, VEC)

LIVE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
PRISTINE = Path(r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE")
MAP = REPO / "build" / "exe_map.json"

# ---- addresses -------------------------------------------------------------------------------
KICK_VF8 = 0x143ED0F80          # match::anime::action::Kick::vf8
KICK_EXEC = 0x144016A70         # kick execution (velocity -> miss params -> randomiser)
RAND4, RAND13, RAND0 = 0x14401A060, 0x144019E40, 0x144019320
FINALISE = 0x143EA46C0          # the only caller of the vf8 kick slot by player action id
PUNT_VF8 = 0x143F2E9C0          # goal_keeper::PuntKick::vf8 -> forwards to action-8's vf8
ACT_LOOKUP = 0x143EEE720        # actionObject(work, id) = [work + 0x1b20 + 8*id]
ACT_CTOR = 0x143EEE750          # writes the action-object table
ACT_INIT = (0x143E9EB00, 0x143EA0410)
BASE_VF8 = 0x140C83910          # `ret 0` - the do-nothing kick slot
RESTART_VF8 = 0x143F05150
SETPLAY_ERR = 0x143F05730       # the set-piece error model
SETPLAY_OUTER_JT, SETPLAY_OUTER_IX = 0x143F05700, 0x143F05708
SETPLAY_INNER_JT, SETPLAY_INNER_IX = 0x143F060B0, 0x143F060C0
KICK_TABLE = 0x14804E0E0        # 176 x 16 kick-property records (record[id], ids 1..0xb0)
CLASS_GET = 0x143EDA730         # record byte 13 (error class)
KIND_GET = 0x143ED80F0          # record byte 12 (kick kind)
KIND_LE1 = 0x143EDF8B0          # record byte 12 <= 1  (the HEADING-ability predicate)
ABILITY_SEL = 0x143ED7440       # effective kick ability + weak-foot penalty
ABILITY_F = 0x143ED71D0         # ability -> 0..1 factor f
FORCED_EXACT = 0x143EDF000      # bit 17 of [player+0xad8] && !([player+0x362d]&8)
CLASS_MULT_SITE = 0x14401BE1E   # movss xmm6,[0.90f] - head of the kick-class multiplier
ATTR_GET = 0x143EA8CB0
FACTORS = (0x144020D00, 0x14401EB40, 0x14401BDB0, 0x14401CA10, 0x14401F770)
MALLOC, FREE, MEMCPY = 0x140E999A0, 0x140E999B0, 0x144F8307A

KICK_ACTION_IDS = (8, 9, 0xA)
# the set-piece action ids Restart::vf8 gives a real body to (proved in S6)
SETPLAY_NAMES = {
    0x1B: "KickoffKickerLoop", 0x1C: "KickoffReceiver", 0x1D: "KickoffOther", 0x1E: "KickoffKicker",
    0x1F: "ThrowinLoop", 0x20: "ThrowinNormal", 0x21: "ThrowinLong", 0x22: "SeamlessThrowin",
    0x23: "FreeKickLoop", 0x24: "FreeKick", 0x25: "FreeKick", 0x26: "FreeKick",
    0x27: "FreeKick2ndLoop", 0x28: "FreeKick2ndCede", 0x29: "FreeKick2ndPassToKicker",
    0x2A: "FreeKick", 0x2B: "FreeKick", 0x2C: "FreeKick",
    0x2D: "QuickRestartReady", 0x2E: "QuickRestartKick", 0x2F: "QuickRestartKick", 0x30: "QuickRestartKick",
    0x31: "WallLoop", 0x32: "WallJump", 0x33: "WallNotJump", 0x34: "WallRunOut", 0x35: "WallNotRunOut",
    0x36: "CornerKickLoop", 0x37: "CornerKick", 0x38: "CornerKick",
    0x39: "SeamlessCornerKickReady", 0x3A: "SeamlessCornerKick", 0x3B: "SeamlessCornerKick",
    0x3C: "SeamlessGoalKickReady", 0x3D: "SeamlessGoalKick", 0x3E: "SeamlessGoalKick",
    0x3F: "PostManLoop", 0x40: "PenaltyKickLoop", 0x41: "PenaltyKick", 0x42: "PkWait",
    0x4A: "GoalKickStandby", 0x4B: "GoalKickLongPass", 0x4C: "GoalKickShortPass",
    0x4D: "gk::PuntKick", 0x4E: "gk::Throw", 0x50: "gk::DropBall",
}


# ==============================================================================================
# helpers
# ==============================================================================================
def img_pair(which):
    p = LIVE if which == "live" else PRISTINE
    return MapImage(p), EmuImage(p), p


def func_bounds(mimg, pd, va):
    import numpy as np
    rva = va - mimg.base
    i = int(np.searchsorted(pd[:, 0], rva, side="right")) - 1
    if i < 0 or not (pd[i, 0] <= rva < pd[i, 1]):
        return None
    root = int(pd[i, 2])
    ch = pd[pd[:, 2] == root]
    return root + mimg.base, int(ch[:, 1].max()) + mimg.base


def dis(mimg, va, end):
    return list(mimg.md.disasm(mimg.read(va - mimg.base, end - va), va))


def call_fn(eimg, entry, regs=None, stack=None, mem=None, stubs=None, count=2_000_000):
    """Run `entry` to its ret.  stubs: {target_va: callable(uc)}.  Returns (Emu, err)."""
    e = Emu(eimg, permissive=True)
    uc = e.uc
    rsp = STACK_TOP - 0x40000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    for r, v in (regs or {}).items():
        uc.reg_write(GPR[r], v)
    for off, v in (stack or {}).items():
        uc.mem_write(rsp + off, struct.pack("<Q", v))
    for a, b in (mem or {}).items():
        uc.mem_write(a, b)
    stubs = stubs or {}

    def code(u, addr, size, ud):
        b = bytes(u.mem_read(addr, size))
        if b[0] not in (0xE8, 0xE9):
            return
        tgt = addr + 5 + struct.unpack("<i", b[1:5])[0]
        if tgt not in stubs:
            return
        stubs[tgt](u)
        if b[0] == 0xE8:
            u.reg_write(X.UC_X86_REG_RIP, addr + size)
        else:                                   # tail jmp: return to the caller
            sp = u.reg_read(X.UC_X86_REG_RSP)
            u.reg_write(X.UC_X86_REG_RIP, struct.unpack("<Q", bytes(u.mem_read(sp, 8)))[0])
            u.reg_write(X.UC_X86_REG_RSP, sp + 8)

    uc.hook_add(UC_HOOK_CODE, code)
    err = None
    try:
        uc.emu_start(entry, RET_MAGIC, count=count)
    except UcError as ex:
        err = f"{ex} at rip {uc.reg_read(X.UC_X86_REG_RIP):#x}"
    return e, err


# ==============================================================================================
# S1  the single static path into the builder
# ==============================================================================================
def s1_path(mimg, pd):
    print("\n== S1  who reaches the kick-error builder ==")
    ok = True
    for name, va in (("builder 0x14401a900", BUILDER), ("randomiser type 4 0x14401a060", RAND4),
                     ("randomiser types 1/3 0x144019e40", RAND13), ("randomiser type 0/2 0x144019320", RAND0),
                     ("kick execution 0x144016a70", KICK_EXEC), ("Kick::vf8 0x143ed0f80", KICK_VF8)):
        hits = scan_xrefs(mimg, va - mimg.base)
        fns = sorted({func_bounds(mimg, pd, r + mimg.base)[0] for k, r in hits
                      if func_bounds(mimg, pd, r + mimg.base)} )
        print(f"  {name:34s} referrers {len(hits):2d}  enclosing functions {[hex(f) for f in fns] or 'NONE (vtable only)'}")
        if va in (BUILDER, RAND4, RAND13, RAND0):
            ok &= fns == [KICK_EXEC]
        if va == KICK_EXEC:
            ok &= fns == [KICK_VF8]
        if va == KICK_VF8:
            ok &= not hits                      # reached only through the vftable
    print(f"  -> the ONLY static path is  Kick::vf8 -> 0x144016a70 -> builder/randomisers : {'PASS' if ok else 'FAIL'}")
    return ok


# ==============================================================================================
# S2  action id -> class, vf8 per class, and the vf8 dispatch sites
# ==============================================================================================
def _scan_vft_stores(mimg, pd, fva, vft_names, basereg="rdi"):
    b, e = func_bounds(mimg, pd, fva)
    regs, vals, out = {}, {}, []
    for i in dis(mimg, b, e):
        if i.mnemonic == "lea":
            m = re.match(r"^(\w+), \[rip \+ (-?0x[0-9a-f]+)\]$", i.op_str)
            if m:
                vals[m.group(1)] = i.address + i.size + int(m.group(2), 16)
                regs.pop(m.group(1), None)
                continue
            m = re.match(r"^(\w+), \[(\w+)(?: \+ (0x[0-9a-f]+))?\]$", i.op_str)
            if m:
                r, bs, d = m.group(1), m.group(2), int(m.group(3), 16) if m.group(3) else 0
                if bs == basereg:
                    regs[r] = d
                elif bs in regs:
                    regs[r] = regs[bs] + d
                else:
                    regs.pop(r, None)
                vals.pop(r, None)
                continue
        elif i.mnemonic == "mov":
            m = re.match(r"^qword ptr \[(\w+)(?: \+ (0x[0-9a-f]+))?\], (\w+)$", i.op_str)
            if m:
                bs, d, src = m.group(1), int(m.group(2), 16) if m.group(2) else 0, m.group(3)
                off = d if bs == basereg else (regs[bs] + d if bs in regs else None)
                if off is not None and src in vals and vals[src] in vft_names:
                    out.append((off, vals[src]))
                continue
            m = re.match(r"^(\w+), (\w+)$", i.op_str)
            if m:
                r, s = m.group(1), m.group(2)
                if s in vals:
                    vals[r] = vals[s]
                else:
                    vals.pop(r, None)
                if s in regs:
                    regs[r] = regs[s]
                else:
                    regs.pop(r, None)
    return out


def action_map(mimg, pd):
    """-> {action id: (object offset, class name)}   (table slot value = object base + 8)."""
    mp = json.loads(MAP.read_text(encoding="utf-8"))
    base = mp["base"]
    vft_names, bases = {}, {}
    for c, lst in mp["classes"].items():
        bases[c] = set(lst[0]["bases"])
        for v in lst:
            vft_names[v["vftable"] + base] = c
    res = defaultdict(list)
    for fva in ACT_INIT:
        for off, v in _scan_vft_stores(mimg, pd, fva, vft_names):
            res[off].append(vft_names[v])
    final = {}
    for off, cs in res.items():
        cand = [c for c in cs if not any(c in bases.get(o, ()) for o in cs if o != c)]
        final[off] = (cand or cs)[-1]
    b, e = func_bounds(mimg, pd, ACT_CTOR)
    slots, lastlea = {}, None
    for i in dis(mimg, b, e):
        if i.mnemonic == "lea":
            m = re.match(r"^(\w+), \[rcx(?: \+ (0x[0-9a-f]+))?\]$", i.op_str)
            if m:
                lastlea = int(m.group(2) or "0", 16)
        if i.mnemonic == "mov":
            m = re.match(r"^qword ptr \[rcx \+ (0x[0-9a-f]+)\], rax$", i.op_str)
            if m:
                d = int(m.group(1), 16)
                if 0x1B20 <= d < 0x1B20 + 0x71 * 8 and (d - 0x1B20) % 8 == 0:
                    slots[(d - 0x1B20) // 8] = lastlea
    return {k: (v, final.get((v - 8) if v is not None else -1, "?")) for k, v in slots.items()}, vft_names


def s2_dispatch(mimg, pd):
    print("\n== S2  action id -> action class -> which vf8 ==")
    amap, vft_names = action_map(mimg, pd)
    mp = json.loads(MAP.read_text(encoding="utf-8"))
    base = mp["base"]
    vft_of = {}
    for c, lst in mp["classes"].items():
        vft_of.setdefault(c, lst[0]["vftable"] + base)
    kick_ids = [k for k, (o, c) in sorted(amap.items()) if c.endswith("::Kick")]
    print(f"  action ids whose object is match::anime::action::Kick : {[hex(k) for k in kick_ids]}")
    print("  vf8 read straight out of each action class's vftable (slot 8 = vftable + 0x40):")
    seen = {}
    for k, (off, cls) in sorted(amap.items()):
        if cls == "?" or cls not in vft_of:
            continue
        vf8 = struct.unpack("<Q", mimg.read(vft_of[cls] + 0x40 - mimg.base, 8))[0]
        seen.setdefault(vf8, []).append((k, cls.split("::")[-1]))
    label = {BASE_VF8: "Base::vf8 = `ret 0`  (NO kick error of any kind)",
             KICK_VF8: "Kick::vf8 -> the IN-PLAY error builder",
             RESTART_VF8: "Restart::vf8 -> the SET-PIECE model 0x143f05730",
             PUNT_VF8: "PuntKick::vf8 -> forwards to the action-8 object = Kick::vf8"}
    for vf8, lst in sorted(seen.items()):
        print(f"   vf8 {vf8:#x}  {label.get(vf8, '(other)')}")
        print(f"      {', '.join(f'{hex(k)}={n}' for k, n in lst)}")
    # every vf8 dispatch site in match code
    import numpy as np
    lo, hi = 0x143C00000 - mimg.base, 0x144600000 - mimg.base
    sel = pd[(pd[:, 0] >= lo) & (pd[:, 0] < hi)]
    md = mimg.md
    sites = []
    for b, e, _ in sel:
        for i in md.disasm(mimg.read(int(b), int(e - b)), mimg.base + int(b)):
            if i.mnemonic in ("call", "jmp") and i.op_str.startswith("qword ptr [") and i.op_str.endswith("+ 0x40]"):
                f = func_bounds(mimg, pd, i.address)
                sites.append((i.address, f[0] if f else None, i.mnemonic, i.op_str))
    disp = [s for s in sites if s[1] in (FINALISE, PUNT_VF8)]
    print(f"  `call/jmp qword ptr [reg+0x40]` sites in match code: {len(sites)}; "
          f"on an action object: {len(disp)}")
    for va, f, m, o in disp:
        print(f"      {va:#x} {m} {o}   in {f:#x}")
    ok = len(disp) == 2 and set(kick_ids) == set(KICK_ACTION_IDS)
    print(f"  S2 {'PASS' if ok else 'CHECK'}")
    return ok


# ==============================================================================================
# S3  the kick-property table, decoded by emulating the game's own accessors
# ==============================================================================================
def s3_table(eimg):
    print("\n== S3  kick-property table 0x14804e0e0 (emulated accessors) ==")
    KID = ARENA + 0x30000
    rows = {}
    for kid in range(0, 0xB2):
        mem = {KID: struct.pack("<i", kid)}
        e, _ = call_fn(eimg, CLASS_GET, regs={"rcx": KID}, mem=mem)
        cls = e.uc.reg_read(X.UC_X86_REG_RAX) & 0xFF
        e, _ = call_fn(eimg, KIND_GET, regs={"rcx": KID}, mem=mem)
        kind = e.uc.reg_read(X.UC_X86_REG_RAX) & 0xFF
        e, _ = call_fn(eimg, KIND_LE1, regs={"rcx": KID}, mem=mem)
        head = e.uc.reg_read(X.UC_X86_REG_RAX) & 1
        rows[kid] = (cls, kind, head)
    valid = {k: v for k, v in rows.items() if 1 <= k <= 0xB0}
    print(f"  error class (byte 13) histogram over the 176 valid ids: {dict(Counter(v[0] for v in valid.values()))}")
    cls4 = [k for k, v in valid.items() if v[0] == 4]
    print(f"  class 4 = NO flat multiplier at all -> ids {[hex(k) for k in cls4]}")
    for k in cls4:
        rec = eimg.read(KICK_TABLE + 16 * k - eimg.base, 16)
        print(f"      id {k:#04x} record {rec.hex(' ')}  (category byte4={rec[4]:#x}, kind byte12={rec[12]:#x})")
    print(f"  kick kind (byte 12) histogram: {dict(sorted(Counter(v[1] for v in valid.values()).items()))}")
    hd = [k for k, v in valid.items() if v[2]]
    print(f"  kind<=1 (0x143edf8b0 true) -> {len(hd)} ids: {' '.join(hex(k) for k in hd)}")

    # which ability index does 0x143ed7440 actually ask for, per kick id?
    def probe(kid, action):
        asked = []
        e = Emu(eimg, permissive=True)
        uc = e.uc
        rsp = STACK_TOP - 0x20000
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, PLAYER)
        uc.reg_write(X.UC_X86_REG_RDX, KID)
        uc.reg_write(X.UC_X86_REG_R8, 0)
        uc.reg_write(X.UC_X86_REG_R9, action)
        uc.mem_write(rsp + 0x28, struct.pack("<I", 1))
        uc.mem_write(KID, struct.pack("<i", kid))

        def code(u, addr, size, ud):
            b = bytes(u.mem_read(addr, size))
            if b[0] == 0xE8:
                t = addr + 5 + struct.unpack("<i", b[1:5])[0]
                if t == ATTR_GET:
                    asked.append(u.reg_read(X.UC_X86_REG_RDX) & 0xFFFFFFFF)
                    u.reg_write(X.UC_X86_REG_RAX, 70)
                else:
                    u.reg_write(X.UC_X86_REG_RAX, 0)
                    u.reg_write(XMM[0], 0)
                u.reg_write(X.UC_X86_REG_RIP, addr + size)
            elif b[0] == 0xFF and (b[1] >> 3) & 7 == 2:
                u.reg_write(X.UC_X86_REG_RAX, 0)
                u.reg_write(X.UC_X86_REG_RIP, addr + size)

        uc.hook_add(UC_HOOK_CODE, code)
        try:
            uc.emu_start(ABILITY_SEL, RET_MAGIC, count=500000)
        except UcError:
            pass
        return asked[0] if asked else None

    names = {0x1B: "SHOT", 0x1C: "SHORT_PASS", 0x1D: "LONG_PASS", 0x1E: "HEADING"}
    groups = defaultdict(set)
    for kid in range(1, 0xB1):
        for act in KICK_ACTION_IDS:
            groups[probe(kid, act)].add(kid)
    print("  0x143ed7440 emulated over every (kick id, kick action id): primary ability requested")
    for prim, kids in sorted(groups.items(), key=lambda x: (x[0] or 0)):
        print(f"      {prim if prim is None else hex(prim)} ({names.get(prim, '?')}): {len(kids)} kick ids")
    hd_by_ability = groups.get(0x1E, set())
    ok = hd_by_ability == set(hd)
    print(f"  the HEADING set from the emulated selector == the kind<=1 set: {'PASS' if ok else 'FAIL'}")
    print("  -> headers ARE ordinary kick ids: they run the same builder, only the ability differs.")
    return ok


# ==============================================================================================
# S4  the in-play builder end to end
# ==============================================================================================
def build_out(eimg, f=0.0, slots=(1.0,) * 6, action=0x01, kickid=0x27, forced_exact=False):
    e = Emu(eimg, permissive=True)
    uc = e.uc
    heap = [ARENA + 0x180000]
    ncalls = [0]

    def code(u, addr, size, ud):
        if addr in (MALLOC, FREE, MEMCPY):
            sp = u.reg_read(X.UC_X86_REG_RSP)
            if addr == MALLOC:
                heap[0] += 0x100
                u.reg_write(X.UC_X86_REG_RAX, heap[0])
            elif addr == MEMCPY:
                dst, src, n = (u.reg_read(GPR[r]) for r in ("rcx", "rdx", "r8"))
                u.mem_write(dst, bytes(u.mem_read(src, n)))
                u.reg_write(X.UC_X86_REG_RAX, dst)
            u.reg_write(X.UC_X86_REG_RIP, struct.unpack("<Q", bytes(u.mem_read(sp, 8)))[0])
            u.reg_write(X.UC_X86_REG_RSP, sp + 8)
            return
        if not (BUILDER <= addr < BUILDER_END):
            return
        b = bytes(u.mem_read(addr, size))
        if b[0] == 0xE8:
            tgt = addr + 5 + struct.unpack("<i", b[1:5])[0]
            if tgt == FOLD:
                return
            ncalls[0] += 1
            u.reg_write(X.UC_X86_REG_RAX, 0)
            if tgt == F_ABILITY:
                u.reg_write(XMM[0], f2i(f))
            elif tgt in FACTORS:
                r9 = u.reg_read(X.UC_X86_REG_R9)
                for k, v in enumerate(slots):
                    u.mem_write(r9 + 4 * k, struct.pack("<f", v))
                u.reg_write(XMM[0], 0)
            elif tgt == FORCED_EXACT:
                u.reg_write(X.UC_X86_REG_RAX, 1 if forced_exact else 0)
            else:
                u.reg_write(XMM[0], 0)
            u.reg_write(X.UC_X86_REG_RIP, addr + size)
        elif b[0] == 0xFF and (b[1] >> 3) & 7 == 2:
            u.reg_write(X.UC_X86_REG_RAX, 0)
            u.reg_write(XMM[0], 0)
            u.reg_write(X.UC_X86_REG_RIP, addr + size)

    uc.hook_add(UC_HOOK_CODE, code)
    e.overlay(COOKIE_CHECK, b"\xc3")
    rsp = STACK_TOP - 0x8000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, OUT)
    uc.reg_write(X.UC_X86_REG_RDX, PLAYER)
    uc.reg_write(X.UC_X86_REG_R8, VEC)
    uc.reg_write(X.UC_X86_REG_R9, VEC + 0x100)
    uc.mem_write(rsp + 0x28, struct.pack("<QQQQ", VEC + 0x200, VEC + 0x300, VEC + 0x400, VEC + 0x500))
    uc.mem_write(OUT, b"\x00" * 0x80)
    uc.mem_write(PLAYER + 0xAD0, bytes([action]))
    uc.mem_write(PLAYER + 0x2F6E, struct.pack("<h", kickid))
    err = None
    try:
        uc.emu_start(BUILDER, RET_MAGIC, count=2_000_000)
    except UcError as ex:
        err = f"{ex} at rip {uc.reg_read(X.UC_X86_REG_RIP):#x}"
    o = [e.rf(OUT + 4 * k) for k in range(16)]
    return dict(horiz=o[0], vert=o[4], power=o[8], sigH=o[2], sigV=o[6], sigP=o[10],
                raw=o, err=err, ncalls=ncalls[0])


def s4_builder(mimg, eimg):
    print("\n== S4  the in-play builder 0x14401a900, run end to end ==")
    print("  output struct field map (proved by driving one cleanliness slot at a time):")
    for k, lbl in ((0, "slot0 -> +0x00 horizontal ceiling (deg)"), (1, "slot1 -> +0x10 vertical ceiling (deg)"),
                   (2, "slot2 -> +0x20 power ceiling (fraction)"), (3, "slot3 -> +0x08 sigma horizontal"),
                   (4, "slot4 -> +0x18 sigma vertical"), (5, "slot5 -> +0x28 sigma power")):
        s = [1.0] * 6
        s[k] = 0.9
        r = build_out(eimg, 0.0, tuple(s))
        print(f"      slot{k}=0.9 -> horiz {r['horiz']:7.4f} vert {r['vert']:7.4f} power {r['power']:7.4f} "
              f"sig {r['sigH']:.4f}/{r['sigV']:.4f}/{r['sigP']:.4f}   [{lbl}]")
    print("  ability factor f does NOT enter the ceilings directly (same slots, different f):")
    for f in (0.0, 0.5, 1.0):
        r = build_out(eimg, f, (1.0,) * 6)
        print(f"      f={f:.1f}, all c=1.0 -> horiz {r['horiz']:.4f} vert {r['vert']:.4f} power {r['power']:.4f}")
    print("  -> a PERFECTLY CLEAN kick (every c = 1.0) has ceilings of EXACTLY zero on all three")
    print("     axes, for a 40-rated player and a 99-rated player alike.")
    # kick-class multiplier
    print("  the flat kick-class multiplier on the horizontal slot (0x14401be1e, unconditional):")
    ins = dis(mimg, CLASS_MULT_SITE, CLASS_MULT_SITE + 0x50)
    for i in ins:
        for op in i.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP and \
                    i.mnemonic in ("movss", "mulss"):
                t = i.address + i.size + op.mem.disp
                v = struct.unpack("<f", mimg.read(t - mimg.base, 4))[0]
                if 0.5 < v < 1.0:
                    print(f"      {i.address:#x} {i.mnemonic} {i.op_str}   cell {t:#x} = {v}")
    for cls, m in (("class 0", 0.90), ("class 1", 0.88), ("class 2/3", 0.86), ("class 4", 1.0)):
        r = build_out(eimg, 0.0, (m, 1.0, 1.0, 1.0, 1.0, 1.0))
        print(f"      clean kick, {cls:9s} c1={m:.2f} -> horizontal ceiling {r['horiz']:6.3f} deg, "
              f"vertical {r['vert']:.3f}, power {r['power']:.4f}")
    print("  -> the ONLY residual error on an unpressured kick is horizontal, it is the same for")
    print("     every player, and the 4 class-4 ids do not even get that.")
    a = build_out(eimg, 0.0, (0.90, 1, 1, 1, 1, 1), forced_exact=False)
    b = build_out(eimg, 0.0, (0.90, 1, 1, 1, 1, 1), forced_exact=True)
    print(f"  forced-exact predicate 0x143edf000: FALSE -> horiz {a['horiz']:.3f} ({a['ncalls']} stubbed calls); "
          f"TRUE -> horiz {b['horiz']:.3f} ({b['ncalls']} calls)")
    print("     (true also skips the mishit-TYPE probability block at 0x14401b5b8 - fewer calls)")
    return b["horiz"] == 0.0


# ==============================================================================================
# S5  the set-piece error model
# ==============================================================================================
SET_STUBS_MEM = dict(MATCHDATA=ARENA + 0x61000, ABILARR=ARENA + 0x62000, RNGCTX=ARENA + 0x63000,
                     THIS=ARENA + 0x64000, VELP=ARENA + 0x60000, SPINP=ARENA + 0x60100)


def run_setplay(eimg, action_id, ability=70, gauss=99, rand=0, strong_foot=0, glob=1,
                vel=(20.0, 5.0, 0.0), spin=(1.0, 1.0, 1.0)):
    M = SET_STUBS_MEM
    e = Emu(eimg, permissive=True)
    uc = e.uc
    rsp = STACK_TOP - 0x40000
    uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
    uc.reg_write(X.UC_X86_REG_RSP, rsp)
    uc.reg_write(X.UC_X86_REG_RCX, M["THIS"])
    uc.reg_write(X.UC_X86_REG_RDX, PLAYER)
    uc.reg_write(X.UC_X86_REG_R8, M["VELP"])
    uc.reg_write(X.UC_X86_REG_R9, M["SPINP"])
    uc.mem_write(rsp + 0x20, struct.pack("<Q", 0))
    uc.mem_write(rsp + 0x28, struct.pack("<Q", 0))
    for k, v in enumerate(vel):
        uc.mem_write(M["VELP"] + 4 * k, struct.pack("<f", v))
    for k, v in enumerate(spin):
        uc.mem_write(M["SPINP"] + 4 * k, struct.pack("<f", v))
    uc.mem_write(PLAYER + 0xAD0, bytes([action_id]))
    uc.mem_write(PLAYER + 0x2BD8, b"\x00")
    uc.mem_write(PLAYER + 0x47C0, struct.pack("<Q", M["MATCHDATA"]))
    uc.mem_write(PLAYER + 0x34A4, b"\x00" * 0x1A0)
    uc.mem_write(PLAYER + 0x34A8, struct.pack("<f", 0.5))
    uc.mem_write(PLAYER + 0x34AC, struct.pack("<f", 0.5))
    asked = []
    S = {0x1442D6EF0: lambda u: u.reg_write(X.UC_X86_REG_RAX, M["MATCHDATA"] + 0x100),
         0x144301840: lambda u: u.reg_write(X.UC_X86_REG_RAX, M["ABILARR"]),
         0x14533EB60: lambda u: u.reg_write(X.UC_X86_REG_RAX, glob),
         0x1441172B0: lambda u: u.reg_write(X.UC_X86_REG_RAX, strong_foot),
         0x143EA9260: lambda u: u.reg_write(X.UC_X86_REG_RAX, rand),
         0x143EA9250: lambda u: u.reg_write(X.UC_X86_REG_RAX, M["RNGCTX"]),
         0x144345EB0: lambda u: u.reg_write(X.UC_X86_REG_RAX, gauss)}

    def attr(u):
        asked.append(u.reg_read(X.UC_X86_REG_RDX) & 0xFFFFFFFF)
        u.reg_write(X.UC_X86_REG_RAX, ability)
    S[ATTR_GET] = attr

    def code(u, addr, size, ud):
        b = bytes(u.mem_read(addr, size))
        if b[0] != 0xE8:
            return
        t = addr + 5 + struct.unpack("<i", b[1:5])[0]
        if t in S:
            S[t](u)
            u.reg_write(X.UC_X86_REG_RIP, addr + size)

    uc.hook_add(UC_HOOK_CODE, code)
    err = None
    try:
        uc.emu_start(SETPLAY_ERR, RET_MAGIC, count=3_000_000)
    except UcError as ex:
        err = f"{ex} at rip {uc.reg_read(X.UC_X86_REG_RIP):#x}"
    return ([e.rf(M["VELP"] + 4 * k) for k in range(3)],
            [e.rf(M["SPINP"] + 4 * k) for k in range(3)], asked, err)


def _ang(v):
    import math
    return (math.degrees(math.atan2(v[0], v[2])),
            math.degrees(math.atan2(v[1], math.hypot(v[0], v[2]))),
            math.sqrt(sum(x * x for x in v)))


def s5_setplay(eimg):
    print("\n== S5  the SET-PIECE error model 0x143f05730, emulated per action id ==")
    IN, SP = (20.0, 5.0, 0.0), (1.0, 1.0, 1.0)
    az0, el0, sp0 = _ang(IN)
    print("   input velocity (20, 5, 0) m/s, spin (1,1,1) rev/s; Gaussian stubbed at its maximum (99)")
    print(f"   {'aid':>5} {'kind':24s} {'abil':>4} | {'d azimuth':>10} {'d elev':>8} {'speed x':>8} {'spin x':>7}")
    for act in (0x25, 0x26, 0x2B, 0x2C, 0x2F, 0x37, 0x3A, 0x3D, 0x4B, 0x41, 0x20, 0x4C):
        for ab in (40, 70, 99):
            v, s, asked, err = run_setplay(eimg, act, ability=ab, vel=IN, spin=SP)
            az, el, sp = _ang(v)
            print(f"   {act:#04x} {SETPLAY_NAMES.get(act, '?'):24s} {ab:4d} | {az - az0:10.3f} {el - el0:8.3f} "
                  f"{sp / sp0:8.4f} {s[0]:7.4f}" + (f"   ERR {err}" if err else ""))
    v, s, asked, err = run_setplay(eimg, 0x26)
    print(f"   the only ability it reads: index {[hex(a) for a in set(asked)]} "
          f"(under the project's +0x15 rule that is ball_spin_control / Curl; place_kicking would be 0x20)")
    print("   full spread of the corner-kick branch (ability 40, sweeping the two RNG stubs):")
    for rnd in (0, 40, 60, 99):
        for g in (0, 50, 99):
            v, s, _, _ = run_setplay(eimg, 0x37, ability=40, gauss=g, rand=rnd, vel=IN, spin=SP)
            az, el, sp = _ang(v)
            print(f"      rand={rnd:3d} gauss={g:3d} -> dAz {az - az0:7.3f}  dEl {el - el0:7.3f}  "
                  f"speed x{sp / sp0:.4f}  spin x{s[0]:.4f}")
    return True


# ==============================================================================================
# S6  the two set-piece jump tables (the cheapest levers)
# ==============================================================================================
def s6_tables(mimg):
    print("\n== S6  the two set-piece jump tables, byte by byte ==")
    ot = [struct.unpack("<I", mimg.read(SETPLAY_OUTER_JT + 4 * k - mimg.base, 4))[0] + 0x140000000 for k in range(2)]
    it = [struct.unpack("<I", mimg.read(SETPLAY_INNER_JT + 4 * k - mimg.base, 4))[0] + 0x140000000 for k in range(4)]
    OT = {0: f"BODY {ot[0]:#x}", 1: f"epilogue {ot[1]:#x} (no error)"}
    IT = {0: "cross/corner error", 1: "free-kick-shot error", 2: "goal-kick-long error", 3: "ZERO (default)"}
    print(f"  Restart::vf8 outer table  targets {[hex(x) for x in ot]}   index bytes at {SETPLAY_OUTER_IX:#x}..")
    print(f"  0x143f05730 inner table   targets {[hex(x) for x in it]}   index bytes at {SETPLAY_INNER_IX:#x}..")
    print(f"  {'aid':>5} {'kind':24s} {'outer index byte':>36} {'inner index byte':>34}")
    for k in range(0x27):
        aid = 0x25 + k
        o = mimg.read(SETPLAY_OUTER_IX + k - mimg.base, 1)[0]
        i = mimg.read(SETPLAY_INNER_IX + k - mimg.base, 1)[0]
        print(f"  {aid:#04x} {SETPLAY_NAMES.get(aid, '?'):24s} "
              f"{SETPLAY_OUTER_IX + k:#x}={o} {OT.get(o, '?'):22s} {SETPLAY_INNER_IX + k:#x}={i} {IT.get(i, '?')}")
    print("  -> an action id only gets error when its OUTER byte is 0 AND its INNER byte is 0/1/2.")
    return True


# ==============================================================================================
# S7  the summary
# ==============================================================================================
def s7_summary():
    print("\n== S7  kick kind -> can it mis-hit? ==")
    rows = [
        ("ground pass / lofted pass / through ball / cross", "in-play Kick action 8 or 9",
         "YES - builder", "only the flat kick-class term is ability-free"),
        ("shot / volley / first-time shot", "in-play Kick action 0xa", "YES - builder",
         "power error is additionally softened at 0x14401b379"),
        ("header", "in-play Kick, kick ids with record byte12<=1 (35 of 176)", "YES - builder",
         "HEADING ability, no weak-foot penalty at all"),
        ("GK punt / drop kick", "gk::PuntKick 0x4d -> forwards to the Kick object", "YES - builder", ""),
        ("direct free kick", "FreeKick 0x26 / 0x2c", "YES - set-piece model only", "max ~1.9 deg at ability 40"),
        ("free-kick cross / lay-off", "FreeKick 0x25 / 0x2b", "YES - set-piece model only", "max ~3.0 deg"),
        ("corner (set-piece camera)", "CornerKick 0x37", "YES - set-piece model only", "max ~3.0 deg"),
        ("seamless corner", "SeamlessCornerKick 0x3a / 0x3b", "NO", "inner jump-table byte = ZERO branch"),
        ("quick restart / quick free kick", "QuickRestartKick 0x2e / 0x2f / 0x30", "NO",
         "inner jump-table byte = ZERO branch"),
        ("goal kick (long)", "GoalKickLongPass 0x4b", "NO", "its vf8 is Base::vf8 = `ret 0`"),
        ("goal kick (short)", "GoalKickShortPass 0x4c", "NO", "its vf8 is Base::vf8 = `ret 0`"),
        ("seamless goal kick", "SeamlessGoalKick 0x3d / 0x3e", "NO", "inner jump-table byte = ZERO branch"),
        ("penalty kick", "PenaltyKick 0x41", "NO", "outer jump-table byte = epilogue"),
        ("throw-in", "Throwin* 0x1f-0x22", "NO", "outside the outer jump table's 0x25..0x4b range"),
        ("kickoff", "Kickoff* 0x1b-0x1e", "NO", "outside the outer jump table's range"),
        ("GK throw / drop ball", "gk::Throw 0x4e, gk::DropBall 0x50", "NO", "vf8 is Base::vf8 = `ret 0`"),
    ]
    print(f"  {'kind':48s} {'where':46s} {'mis-hit?':26s} note")
    for a, b, c, d in rows:
        print(f"  {a:48s} {b:46s} {c:26s} {d}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default="pristine", choices=("pristine", "live"))
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    mimg, eimg, path = img_pair(a.exe)
    pd = load_pdata(mimg)
    print(f"image: {path}  ({path.stat().st_size:,} B)   base {mimg.base:#x}")
    want = set(x.upper() for x in a.only) if a.only else None
    res = {}
    for tag, fn in (("S1", lambda: s1_path(mimg, pd)), ("S2", lambda: s2_dispatch(mimg, pd)),
                    ("S3", lambda: s3_table(eimg)), ("S4", lambda: s4_builder(mimg, eimg)),
                    ("S5", lambda: s5_setplay(eimg)), ("S6", lambda: s6_tables(mimg)),
                    ("S7", s7_summary)):
        if want and tag not in want:
            continue
        res[tag] = fn()
    print("\n" + "  ".join(f"{k}={'ok' if v else 'CHECK'}" for k, v in res.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
