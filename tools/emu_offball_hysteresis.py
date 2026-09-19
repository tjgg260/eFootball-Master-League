#!/usr/bin/env python3
"""
emu_offball_hysteresis.py - Unicorn proof harness for the OFF-BALL RUN persistence machinery.

Nothing here touches the game.  Both images are opened READ-ONLY (mmap ACCESS_READ) and their
pages are lazily copied into a Unicorn address space; the game's OWN bytes are executed.
Default image is the PRISTINE backup so the proofs are against stock code.

    python tools/emu_offball_hysteresis.py                # all sections
    python tools/emu_offball_hysteresis.py --exe <path>   # emulate another image

Sections
  S1  ring-record layout: the game's own accessor 0x1442eda20 (get) / 0x1442eda50 (stamp) /
      0x1442eda60 (push) executed against a record we control -> proves
      teamAI+0x8f78+slot*0x34 is a 4-entry ring of {actionId, startFrame, lastFrame} + head@+0x30.
  S2  ChanceSpaceRun::vf3 (0x143df72d0) truth table: real bytes, every helper call stubbed to a
      chosen value, elapsed swept.  Shows exactly what aborts a run and what the 0.2 s timer
      does and does not protect.
  S3  DiagonalRun::vf3 (0x143e05130) truth table, same method.
  S4  churn model: given the vf3 truth table, how many CONSECUTIVE ~33 ms manager ticks a run
      survives, and what the protection window buys, as a function of the window literal.
  S5  the two latch arrays: predicate classifiers 0x143d32920 (latch A kind table) executed for
      every action id, and 0x143d32850 (latch B) -> which action/phase arms each latch.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dt270_schema_gen import Image

import capstone
from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE,
                     UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_HOOK_MEM_FETCH_UNMAPPED, UcError)
from unicorn import x86_const as X

PRISTINE = Path(r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE")

# ---- addresses (VA at preferred base 0x140000000) ---------------------------------------------
CSR_VF3 = 0x143DF72D0        # ActionSelectorChanceSpaceRun::vf3   "abort this run?"
DR_VF3 = 0x143E05130         # ActionSelectorDiagonalRun::vf3
RING_GET = 0x1442EDA20       # ring: entry = get(rec, back)
RING_STAMP = 0x1442EDA50     # ring: head.lastFrame = frame
RING_PUSH = 0x1442EDA60      # ring: push(rec, actionId, frame)
KIND_TBL = 0x143D32920       # latch-A kind classifier (jump table on actionId)
LATCHB_PRED = 0x143D32850    # latch-B predicate
FPS_GET = 0x14533EA80        # returns the frame rate as a float

ARENA = 0x10000000
ARENA_SZ = 0x400000
CTX = ARENA + 0x1000         # the selector context struct
TEAMAI = ARENA + 0x10000     # teamAI base (records live at +0x8f78)
OBJ = ARENA + 0x80000        # the "match object" (ctx+0)
PLAYER = ARENA + 0xC0000     # a player object
SCRATCH = ARENA + 0xE0000
STACK_TOP = ARENA + 0x300000
RET_MAGIC = 0x7FFF0000

GPR = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in
       "rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15".split()}
XMMR = [getattr(X, f"UC_X86_REG_XMM{i}") for i in range(16)]


def f2i(v): return struct.unpack("<I", struct.pack("<f", v))[0]


class Emu:
    """Lazily maps the read-only image into Unicorn; nothing is ever written back."""

    def __init__(self, img: Image):
        self.img = img
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        uc.mem_map(ARENA, ARENA_SZ)
        uc.mem_map(RET_MAGIC & ~0xFFF, 0x1000)
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED |
                    UC_HOOK_MEM_FETCH_UNMAPPED, self._unmapped)

    def _unmapped(self, uc, access, addr, size, value, ud):
        img = self.img
        if img.base <= addr < img.base + img.size_of_image:
            b = addr & ~0xFFFF
            if b not in self.mapped:
                uc.mem_map(b, 0x10000)
                try:
                    uc.mem_write(b, b"".join(img.read(b - img.base + k * 0x1000, 0x1000)
                                             for k in range(16)))
                except Exception:
                    pass
                self.mapped.add(b)
            return True
        b = addr & ~0xFFFF
        try:
            uc.mem_map(b, 0x10000)
        except UcError:
            return False
        return True

    def reset_regs(self):
        for r in GPR.values():
            self.uc.reg_write(r, 0)
        for r in XMMR:
            self.uc.reg_write(r, 0)

    def call(self, va, args=(), stubs=None, fps=None, max_ins=200000):
        """Run `va` as a __fastcall; `stubs` maps callee VA -> int return (or ('f', float))."""
        uc = self.uc
        stubs = dict(stubs or {})
        if fps is not None:
            stubs[FPS_GET] = ("f", fps)
        self.reset_regs()
        sp = STACK_TOP - 0x2000
        uc.mem_write(sp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RSP, sp)
        for i, a in enumerate(args[:4]):
            uc.reg_write([X.UC_X86_REG_RCX, X.UC_X86_REG_RDX,
                          X.UC_X86_REG_R8, X.UC_X86_REG_R9][i], a)
        for i, a in enumerate(args[4:]):
            uc.mem_write(sp + 0x28 + 8 * i, struct.pack("<Q", a))

        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.trace = []
        self.stubbed = []

        def code(uc_, addr, size, ud):
            self.trace.append(addr)
            try:
                b = bytes(uc_.mem_read(addr, size))
            except Exception:
                return
            if b[:1] != b"\xe8":            # only direct near calls
                return
            tgt = (addr + 5 + struct.unpack("<i", b[1:5])[0]) & 0xFFFFFFFFFFFFFFFF
            if tgt in stubs:
                v = stubs[tgt]
                if isinstance(v, tuple) and v[0] == "f":
                    uc_.reg_write(X.UC_X86_REG_XMM0, f2i(v[1]))
                else:
                    uc_.reg_write(X.UC_X86_REG_RAX, v & 0xFFFFFFFFFFFFFFFF)
                self.stubbed.append((addr, tgt))
                uc_.reg_write(X.UC_X86_REG_RIP, addr + 5)

        h = uc.hook_add(UC_HOOK_CODE, code)
        try:
            uc.emu_start(va, RET_MAGIC, count=max_ins)
        finally:
            uc.hook_del(h)
        return uc.reg_read(X.UC_X86_REG_RAX)


# ------------------------------------------------------------------------------------------------
def s1_ring(emu: Emu):
    print("\n=== S1  per-slot action record: the game's own ring accessors ===")
    rec = TEAMAI + 0x8F78 + 3 * 0x34          # slot 3
    emu.uc.mem_write(rec, b"\x00" * 0x34)
    # push three different action ids at increasing frames, then stamp
    frames = [(0x1E, 100), (0x1F, 140), (0x1E, 210)]
    for aid, fr in frames:
        emu.call(RING_PUSH, (rec, aid, fr))
    raw = bytes(emu.uc.mem_read(rec, 0x34))
    head = struct.unpack_from("<i", raw, 0x30)[0]
    print(f"  after pushes {frames}:  head = {head}")
    for i in range(4):
        a, s, l = struct.unpack_from("<iii", raw, i * 12)
        print(f"    entry[{i}] actionId=0x{a & 0xffffffff:02x}  start={s}  last={l}")
    for extra in (215, 224, 260):
        emu.call(RING_STAMP, (rec, extra))
    raw = bytes(emu.uc.mem_read(rec, 0x34))
    a, s, l = struct.unpack_from("<iii", raw, head * 12)
    print(f"  after stamp(215/224/260): head entry = id 0x{a:02x} start={s} last={l}"
          f"  -> elapsed = last-start = {l - s}")
    p = emu.call(RING_GET, (rec, 0))
    p1 = emu.call(RING_GET, (rec, 1))
    print(f"  get(rec,0) = rec+0x{p - rec:x}   get(rec,1) = rec+0x{p1 - rec:x}"
          f"   (12-byte entries, head at +0x30)  [a-emulated]")
    # re-push the SAME id: must be a no-op (start frame preserved)
    before = bytes(emu.uc.mem_read(rec, 0x34))
    emu.call(RING_PUSH, (rec, 0x1E, 999))
    after = bytes(emu.uc.mem_read(rec, 0x34))
    print(f"  push(same id 0x1e, frame 999) changed the record: {before != after}"
          f"   -> a re-won run does NOT restart the timer if the id is unchanged")


# ------------------------------------------------------------------------------------------------
CSR_HELPERS = {
    0x1442D6EF0: "getPlayerA",     # -> player obj (used for +0x48c and +0x488)
    0x144301F90: "flag_48c",       # byte [player+0x48c]      (RUN for real)
    0x1442DE630: "controlledIdx",
    0x1442D6BA0: "ptrToByte",
    0x144311E40: "roleOk",
    0x1442D6F60: "getPlayerB",
    0x1442FBB50: "someCount",
    0x143D2F710: "P_bypass",       # the predicate that BYPASSES the timer
    0x144301850: "state_488",      # dword [player+0x488]     (RUN for real)
    0x143E461F0: "q_1e",           # (obj, pid, 0x1e)
    0x143D368C0: "q_flag1",
    0x143DCB330: "q_ctx",
}


def csr_vf3(emu, *, elapsed, fps=60.0, P=0, flag48c=0, state488=0, ctrl_is_me=False,
            roleOk=1, cnt=0, p568=0, q1e=0, qflag=0, qctx=0, pid=3):
    """Run the REAL ChanceSpaceRun::vf3 bytes; 1 = abort the run."""
    uc = emu.uc
    slot = pid % 11
    rec = TEAMAI + 0x8F78 + slot * 0x34
    uc.mem_write(rec, b"\x00" * 0x34)
    uc.mem_write(rec, struct.pack("<iii", 0x1E, 1000, 1000 + elapsed))
    uc.mem_write(CTX, struct.pack("<QQ", OBJ, TEAMAI))
    uc.mem_write(PLAYER, b"\x00" * 0x600)
    uc.mem_write(PLAYER + 0x48C, bytes([flag48c]))
    uc.mem_write(PLAYER + 0x488, struct.pack("<I", state488))
    uc.mem_write(PLAYER + 0x568, struct.pack("<I", p568))
    uc.mem_write(SCRATCH, b"\x05")
    stubs = {
        0x1442D6EF0: PLAYER, 0x1442D6F60: PLAYER, 0x1442D6BA0: SCRATCH,
        0x1442DE630: pid if ctrl_is_me else 99,
        0x144311E40: roleOk, 0x1442FBB50: cnt,
        0x143D2F710: P, 0x143E461F0: q1e, 0x143D368C0: qflag, 0x143DCB330: qctx,
    }
    return emu.call(CSR_VF3, (0, CTX, pid), stubs=stubs, fps=fps) & 0xFF


def s2_csr(emu):
    print("\n=== S2  ChanceSpaceRun::vf3 0x143df72d0 - what aborts a run  [a-emulated] ===")
    base = dict(elapsed=60, P=0, flag48c=0, state488=0, roleOk=1, cnt=0, p568=0,
                q1e=0, qflag=0, qctx=0)
    print(f"  baseline (nothing wrong, run 1.0 s old)          -> abort={csr_vf3(emu, **base)}")
    for k, v, why in [("flag48c", 1, "player+0x48c set (ball/contact flag)"),
                      ("q1e", 1, "0x143e461f0(obj,pid,0x1e) true"),
                      ("qflag", 1, "0x143d368c0(obj,pid,1) true"),
                      ("qctx", 1, "0x143dcb330(ctx,pid,teamAI) true"),
                      ("state488", 6, "player+0x488 == 6"),
                      ("P", 1, "0x143d2f710 predicate true")]:
        d = dict(base); d[k] = v
        print(f"  {why:48s} -> abort={csr_vf3(emu, **d)}")
    d = dict(base); d["roleOk"] = 0; d["ctrl_is_me"] = True
    print(f"  {'controlled player and 0x144311e40 false':48s} -> abort={csr_vf3(emu, **d)}")
    d = dict(base); d["cnt"] = 2; d["p568"] = 5
    print(f"  {'0x1442fbb50>1 and player+0x568 == 5':48s} -> abort={csr_vf3(emu, **d)}")

    print("\n  the 0.2 s window: elapsed sweep, fps=60 -> threshold int(60*0.2+0.5) = 12 frames")
    print("    elapsed :  " + " ".join(f"{e:>3d}" for e in range(0, 20, 2)))
    for name, d in [("no abort cause", dict(base)),
                    ("q1e=1", dict(base, q1e=1)),
                    ("qflag=1", dict(base, qflag=1)),
                    ("qctx=1", dict(base, qctx=1)),
                    ("P=1 (bypass)", dict(base, P=1)),
                    ("flag48c=1", dict(base, flag48c=1))]:
        row = []
        for e in range(0, 20, 2):
            d2 = dict(d); d2["elapsed"] = e
            row.append(csr_vf3(emu, **d2))
        print(f"    {name:14s}:  " + " ".join(f"{v:>3d}" for v in row))

    print("\n  the same sweep with the window literal repointed 0.2f -> 2.0f (threshold 120):")
    print("    elapsed :  " + " ".join(f"{e:>4d}" for e in (0, 12, 30, 60, 90, 119, 121, 200)))
    for name, d in [("q1e=1", dict(base, q1e=1)), ("qctx=1", dict(base, qctx=1)),
                    ("flag48c=1", dict(base, flag48c=1)), ("P=1", dict(base, P=1))]:
        row = []
        for e in (0, 12, 30, 60, 90, 119, 121, 200):
            d2 = dict(d); d2["elapsed"] = e
            # equivalent to multiplying the literal by 10: emulate by raising fps 10x
            row.append(csr_vf3(emu, fps=600.0, **d2))
        print(f"    {name:14s}:  " + " ".join(f"{v:>4d}" for v in row))


MATCHOBJ = ARENA + 0x120000       # what 0x1442d6de0 returns
TEAMAI2 = ARENA + 0x180000        # what 0x1442d7090 returns


def dr_vf3(emu, *, elapsed, fps=60.0, pid=3, g3308=1, g28d=1, ctx1c=99, q8a970=0):
    """Run the REAL DiagonalRun::vf3 bytes; 1 = abort."""
    uc = emu.uc
    slot = pid % 11
    rec = TEAMAI + 0x8F78 + slot * 0x34
    uc.mem_write(rec, b"\x00" * 0x34)
    uc.mem_write(rec, struct.pack("<iii", 0x21, 1000, 1000 + elapsed))
    uc.mem_write(CTX, b"\x00" * 0x40)
    uc.mem_write(CTX, struct.pack("<QQ", OBJ, 0))
    uc.mem_write(CTX + 0x18, struct.pack("<ii", 0, ctx1c))
    uc.mem_write(MATCHOBJ + 0x3308, struct.pack("<I", g3308))
    uc.mem_write(TEAMAI2, b"\x00" * 0x9200)
    uc.mem_write(TEAMAI2 + 0x28D, bytes([g28d]))
    uc.mem_write(TEAMAI2 + 0x8F78 + slot * 0x34,
                 struct.pack("<iii", 0x21, 1000, 1000 + elapsed))
    stubs = {0x1442D6DE0: MATCHOBJ, 0x1442D7090: TEAMAI2, 0x143E8A970: q8a970}
    return emu.call(DR_VF3, (0, CTX, pid), stubs=stubs, fps=fps) & 0xFF


def s3_dr(emu, img):
    print("\n=== S3  DiagonalRun::vf3 0x143e05130  [a-emulated] ===")
    print("  gates BEFORE the timer (all return abort=1 immediately):")
    print(f"    matchObj+0x3308 != 1                  -> abort={dr_vf3(emu, elapsed=60, g3308=0)}")
    print(f"    teamAI+0x28d == 0                     -> abort={dr_vf3(emu, elapsed=60, g28d=0)}")
    print(f"    ctx+0x1c == this player               -> abort={dr_vf3(emu, elapsed=60, ctx1c=3)}")
    print(f"    all gates pass, run 1.0 s old         -> abort={dr_vf3(emu, elapsed=60)}")
    print("\n  timer sweep, fps=60 -> threshold int(60*0.2+0.5) = 12 frames")
    print("    elapsed  :  " + " ".join(f"{e:>3d}" for e in range(0, 20, 2)))
    for name, kw in [("nothing wrong", {}), ("0x143e8a970=1", dict(q8a970=1))]:
        row = [dr_vf3(emu, elapsed=e, **kw) for e in range(0, 20, 2)]
        print(f"    {name:14s}:  " + " ".join(f"{v:>3d}" for v in row))


REPOINTS = {  # site -> (disp32 address, {label: 4 patch bytes})
    "ChanceSpaceRun::vf3 window 0x143df73a8": (0x143DF73AC, {
        "0.2f STOCK": bytes.fromhex("108ea503"), "1.0f": bytes.fromhex("088fa503"),
        "1.5f": bytes.fromhex("908fa503"), "2.0f": bytes.fromhex("e090a503")}),
    "DiagonalRun::vf3 window 0x143e051b2": (0x143E051B6, {
        "0.2f STOCK": bytes.fromhex("06b0a403"), "1.0f": bytes.fromhex("feb0a403"),
        "1.5f": bytes.fromhex("86b1a403"), "2.0f": bytes.fromhex("d6b2a403")}),
}


def s6_repoint(emu):
    print("\n=== S6  the one-instruction lever: repoint the window literal  [a-emulated] ===")
    print("  the 0.2f cell 0x1478501c0 has 800+ other readers in this image - the VALUE must")
    print("  never be edited.  The lever is the 4-byte RIP disp32 of the one mulss.\n")
    base = dict(P=0, flag48c=0, state488=0, roleOk=1, cnt=0, p568=0, q1e=1, qflag=0, qctx=0)
    for site, (dva, variants) in REPOINTS.items():
        print(f"  {site}")
        for label, patch in variants.items():
            emu.uc.mem_write(dva, patch)          # EMULATOR ONLY - no file is touched
            if "ChanceSpaceRun" in site:
                row = [csr_vf3(emu, elapsed=e, **base) for e in
                       (0, 11, 12, 30, 59, 60, 89, 90, 119, 120)]
            else:
                row = [dr_vf3(emu, elapsed=e, q8a970=1) for e in
                       (0, 11, 12, 30, 59, 60, 89, 90, 119, 120)]
            first = next((e for e, v in zip((0, 11, 12, 30, 59, 60, 89, 90, 119, 120), row)
                          if v), None)
            print(f"    {label:11s} disp32={patch.hex()}  abort at elapsed>= {first:>4}"
                  f" frames = {first / 60.0:.2f} s   row={row}")
        emu.uc.mem_write(dva, variants["0.2f STOCK"])


def s5_latches(emu):
    print("\n=== S5  what arms the two latch arrays  [a-emulated] ===")
    print("  latch A kind table 0x143d32920(obj, actionId, arg3, arg4, state) as the manager"
          " calls it (arg3=0, arg4=1):")
    for aid in range(0x18, 0x2C):
        vals = []
        for st in (0, 4, 6):
            emu.uc.mem_write(STACK_TOP - 0x2000 + 0x28, struct.pack("<Q", st))
            r = emu.call(KIND_TBL, (OBJ, aid, 0, 1, st)) & 0xFF
            vals.append(r)
        print(f"    actionId 0x{aid:02x}: state0={vals[0]} state4={vals[1]} state6={vals[2]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(PRISTINE))
    a = ap.parse_args()
    img = Image(a.exe)
    print(f"image: {a.exe}")
    emu = Emu(img)
    s1_ring(emu)
    s2_csr(emu)
    s3_dr(emu, img)
    s5_latches(emu)
    s6_repoint(emu)


if __name__ == "__main__":
    main()
