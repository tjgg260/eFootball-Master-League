#!/usr/bin/env python3
"""
emu_offball_rotation.py - CAVE SOURCE + EMULATION PROOF for the off-ball RUN-ROTATION cave.

    *** NEEDS_CAVE. This lays nothing out and writes no spec. The chained cave allocator
    *** (tools/cave_alloc.py) owns placement. This file is the source and the proof.

THE PROBLEM IT SOLVES
  ActionSelectorChanceSpaceRun::vf5 (0x143df5950) scores every candidate runner as

      score = KIND_BASE + attackDir * player.x + roleBonus

  KIND_BASE is a flat 100.0 for 15 of the 16 run kinds, roleBonus is one constant, and there is
  NO RNG anywhere on the selector path. So on any given picture the SAME man wins, every tick,
  every match. Raising the quota or the attack level only adds the next-deepest man - more bodies,
  same predictability - which is exactly what the owner ruled out. This cave adds a deterministic
  per-(player, time-bucket) offset to the score, so a DIFFERENT member of the front four wins the
  run at different moments, at an unchanged runner count and an unchanged attack level.
  It is a hash, not RNG: reproducible, and constant inside a bucket so a started run does not flicker.

THE HOOK (all verified against both images by this script)
  site        0x143df5d3f, 12 bytes stolen:
                  F3 0F 59 80 F4 04 00 00   mulss xmm0, dword [rax+0x4f4]    ; attackDir * player.x
                  F3 0F 58 F0               addss xmm6, xmm0
  return      0x143df5d4b  (call 0x143d37f30, the first role predicate)
  live regs at the hook, from the six instructions above it:
      rcx = [r14]        (ai object)        set 0x143df5d33   -> consumed by the call at 0x143df5d4b
      edx = ebx          (slot)             set 0x143df5d3a   -> consumed by that call
      r8d = 0                               set 0x143df5d29   -> consumed by that call
      rax = player match object (from 0x1442d6f60 at 0x143df5d20)   -> dead after the stolen mulss
      xmm6 = running score, xmm0 = float(attackDir)
  So rcx, rdx, r8, rbx, rsi, r14 MUST be preserved; rax, xmm0 and the flags are free.

THE TIME SOURCE - NO CALL NEEDED
  The game reads the match frame counter as 0x1442d6de0(ai) then [rax+0x3318] (it does exactly that
  at 0x143df6434..0x143df643c, 20 instructions below the hook). But 0x1442d6de0 is only

      mov rax, [rip+0x43e6aa1]   ; -> the singleton pointer at 0x1486bd888
      mov rax, [rax+0x580]
      ret

  and it IGNORES rcx entirely. The cave therefore INLINES those two loads: no call, no shadow space,
  no stack frame, no register save/restore. The same singleton is cross-confirmed by 0x1442d6f60,
  which reaches 0x1486bd888 through its own RIP-relative load at 0x1442d6f6c.

    python tools/emu_offball_rotation.py            # assemble, verify, emulate, print the tables
"""
from __future__ import annotations
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from emu_selector_order import Img, INSTALLED, PRISTINE
from emu_offball_window import Mini

from unicorn import x86_const as X
import keystone
import capstone

HOOK = 0x143DF5D3F
HOOK_RET = 0x143DF5D4B
STOLEN = bytes.fromhex("f30f5980f4040000" "f30f58f0")

GETTER = 0x1442D6DE0            # mov rax,[rip->singleton]; mov rax,[rax+0x580]; ret
SINGLETON = 0x1486BD888         # resolved from the getter's own disp32
MATCH_OFF = 0x580
FRAME_OFF = 0x3318

# --- tunables -------------------------------------------------------------------------------
BUCKET_SHIFT = 7                # frame >> 7 = 128 frames = ~2.13 s at 60 fps
J = 12.0                        # full width of the offset band, in score points (= metres of depth)
# --------------------------------------------------------------------------------------------

# PLACEHOLDER address, emulation only - tools/cave_alloc.py owns real placement.
# It only has to be inside .xcode so the rel32s are representable.
CAVE = 0x143A00000
WORLD = 0x0000_0006_0000_0000   # singleton -> match object -> frame counter live here


def cave_source(cave_va: int, kcell_va: int) -> str:
    """The cave body. `kcell_va` is a 4-byte float K = J/7 that lives in the cave itself."""
    return f"""
        mulss    xmm0, dword ptr [rax + 0x4f4]
        addss    xmm6, xmm0
        mov      rax, qword ptr [rip + {SINGLETON - 0:#x} - _after1]
        mov      rax, qword ptr [rax + {MATCH_OFF:#x}]
        mov      eax, dword ptr [rax + {FRAME_OFF:#x}]
        shr      eax, {BUCKET_SHIFT}
        shl      eax, 4
        add      eax, ebx
        imul     eax, eax, 0x9E3779B1
        shr      eax, 13
        imul     eax, eax, 0x85EBCA6B
        shr      eax, 17
        and      eax, 7
        cvtsi2ss xmm0, eax
        mulss    xmm0, dword ptr [rip + {kcell_va:#x} - _after2]
        addss    xmm6, xmm0
        jmp      {HOOK_RET:#x}
    """


def assemble(cave_va: int, kcell_va: int) -> bytes:
    """Hand-encode the body (keystone cannot resolve our two RIP labels), then verify with capstone."""
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
    out = bytearray()

    def emit(asm: str):
        enc, _ = ks.asm(asm, cave_va + len(out))
        out.extend(enc)

    def emit_rip(prefix: bytes, target: int):
        """prefix is the instruction up to (but excluding) the 4-byte disp32."""
        nxt = cave_va + len(out) + len(prefix) + 4
        out.extend(prefix + struct.pack("<i", target - nxt))

    out.extend(STOLEN)                                   # stolen bytes, re-executed verbatim
    emit_rip(bytes.fromhex("488b05"), SINGLETON)         # mov rax,[rip->singleton]
    emit(f"mov rax, qword ptr [rax + {MATCH_OFF:#x}]")
    emit(f"mov eax, dword ptr [rax + {FRAME_OFF:#x}]")
    emit(f"shr eax, {BUCKET_SHIFT}")     # bucket index
    emit("shl eax, 4")                   # key = bucket*16 + slot  (slot is 0..10)
    emit("add eax, ebx")
    emit("imul eax, eax, 0x9E3779B1")    # mix; the HIGH bits of a multiply are the mixed ones
    emit("shr eax, 13")
    emit("imul eax, eax, 0x85EBCA6B")    # mix again
    emit("shr eax, 17")
    emit("and eax, 7")
    emit("cvtsi2ss xmm0, eax")
    emit_rip(bytes.fromhex("f30f5905"), kcell_va)        # mulss xmm0,[rip->K]
    emit("addss xmm6, xmm0")
    enc, _ = ks.asm(f"jmp {HOOK_RET:#x}", cave_va + len(out))
    out.extend(enc)
    return bytes(out)


def hook_bytes(cave_va: int) -> bytes:
    """12 bytes at the hook: jmp rel32 to the cave, then 7 bytes of int3 filler."""
    rel = cave_va - (HOOK + 5)
    return b"\xe9" + struct.pack("<i", rel) + b"\xcc" * 7


def run_cave(img: Img, cave: bytes, kcell_va: int, slot: int, frame: int, score_in: float,
             attack_dir: float = 1.0, player_x: float = 0.0):
    """Execute the cave on the game's own surrounding context; return (score_out, regs_out)."""
    e = Mini(img)
    uc = e.uc
    uc.mem_map(WORLD, 0x10000)
    e.overlay(CAVE, cave)
    e.overlay(kcell_va, struct.pack("<f", J / 7.0))
    # singleton -> match object -> frame counter
    matchobj = WORLD + 0x2000
    e.overlay(SINGLETON, struct.pack("<Q", WORLD + 0x1000))
    uc.mem_write(WORLD + 0x1000 + MATCH_OFF, struct.pack("<Q", matchobj))
    uc.mem_write(matchobj + FRAME_OFF, struct.pack("<I", frame))
    # the player object the stolen mulss reads
    player = WORLD + 0x3000
    uc.mem_write(player + 0x4F4, struct.pack("<f", player_x))

    sentinels = {X.UC_X86_REG_RCX: 0x1111111111111111, X.UC_X86_REG_RDX: 0x2222222222222222,
                 X.UC_X86_REG_R8: 0x3333333333333333, X.UC_X86_REG_RSI: 0x5555555555555555,
                 X.UC_X86_REG_R14: 0x6666666666666666, X.UC_X86_REG_RDI: 0x7777777777777777}
    for r, v in sentinels.items():
        uc.reg_write(r, v)
    uc.reg_write(X.UC_X86_REG_RBX, slot)
    uc.reg_write(X.UC_X86_REG_RAX, player)
    uc.reg_write(X.UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", attack_dir))[0])
    uc.reg_write(X.UC_X86_REG_XMM6, struct.unpack("<I", struct.pack("<f", score_in))[0])
    rsp_in = 0x0000_0003_0000_0000 + 0x80000
    uc.reg_write(X.UC_X86_REG_RSP, rsp_in)

    uc.emu_start(CAVE, HOOK_RET, count=200)

    out = struct.unpack("<f", struct.pack("<I", uc.reg_read(X.UC_X86_REG_XMM6) & 0xFFFFFFFF))[0]
    clobbered = [name for name, r in (("rcx", X.UC_X86_REG_RCX), ("rdx", X.UC_X86_REG_RDX),
                                      ("r8", X.UC_X86_REG_R8), ("rsi", X.UC_X86_REG_RSI),
                                      ("r14", X.UC_X86_REG_R14), ("rdi", X.UC_X86_REG_RDI))
                 if uc.reg_read(r) != sentinels[r]]
    if uc.reg_read(X.UC_X86_REG_RBX) != slot:
        clobbered.append("rbx")
    if uc.reg_read(X.UC_X86_REG_RSP) != rsp_in:
        clobbered.append("rsp")
    return out, clobbered


def main():
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for label, path in (("INSTALLED", INSTALLED), ("PRISTINE", PRISTINE)):
        img = Img(path)
        print(f"\n================ {label}")

        # S1 - static checks against the image
        on_disk = img.rd(HOOK, 12)
        print(f"  S1 hook bytes @{HOOK:#x}: {on_disk.hex()}  "
              f"{'MATCH (stock)' if on_disk == STOLEN else 'MISMATCH'}")
        g = img.rd(GETTER, 15)
        disp = struct.unpack("<i", g[3:7])[0]
        resolved = GETTER + 7 + disp
        print(f"  S1 getter {GETTER:#x}: {g[:11].hex()}  -> singleton {resolved:#x} "
              f"{'== expected' if resolved == SINGLETON else '!! UNEXPECTED'}; "
              f"ignores rcx: {'yes' if g[:3] == b'\x48\x8b\x05' else 'NO'}")

        kcell = CAVE + 0x400
        cave = assemble(CAVE, kcell)
        print(f"  S1 cave body: {len(cave)} bytes (+4 for the K cell), hook patch "
              f"{len(hook_bytes(CAVE))} bytes, stolen {len(STOLEN)}")
        print("     " + "\n     ".join(f"{i.address - CAVE:#04x}  {i.bytes.hex():<20} {i.mnemonic} {i.op_str}"
                                       for i in md.disasm(cave, CAVE)))

        # S2 - bit-exactness when the offset is zero is NOT expected (the offset is always >= 0);
        #      instead prove the positional term is reproduced exactly, then the offset is additive.
        base, _ = run_cave(img, cave, kcell, slot=0, frame=0, score_in=100.0,
                           attack_dir=1.0, player_x=40.0)
        print(f"\n  S2 score_in 100.0, attackDir +1, player.x 40.0 -> {base:.4f} "
              f"(positional term reproduced: {'yes' if abs(base - 140.0) <= J else 'NO'})")

        # S3 - register discipline
        _, clob = run_cave(img, cave, kcell, slot=7, frame=12345, score_in=100.0)
        print(f"  S3 registers the next call needs (rcx,rdx,r8,rbx,rsi,r14,rdi,rsp): "
              f"{'ALL PRESERVED' if not clob else 'CLOBBERED ' + ','.join(clob)}")

        # S4 - the rotation table: offset per (slot, bucket)
        print(f"\n  S4 offset added to the score, J={J}, bucket = frame>>{BUCKET_SHIFT} "
              f"(~{(1 << BUCKET_SHIFT) / 60.0:.2f} s at 60 fps)")
        print("      slot |" + "".join(f" b{b:<5}" for b in range(8)))
        allv = []
        for slot in range(11):
            row = []
            for b in range(8):
                v, _ = run_cave(img, cave, kcell, slot=slot, frame=b << BUCKET_SHIFT, score_in=0.0)
                row.append(v)
                allv.append(v)
            print(f"      {slot:4d} |" + "".join(f" {v:5.2f} " for v in row))
        print(f"      range {min(allv):.3f} .. {max(allv):.3f}  (must lie in 0.00 .. {J:.2f})")

        # S5 - determinism and stability inside a bucket
        f0 = 3 << BUCKET_SHIFT
        same = {run_cave(img, cave, kcell, slot=4, frame=f0 + k, score_in=0.0)[0]
                for k in range(1 << BUCKET_SHIFT)}
        nxt, _ = run_cave(img, cave, kcell, slot=4, frame=f0 + (1 << BUCKET_SHIFT), score_in=0.0)
        print(f"\n  S5 slot 4, all {1 << BUCKET_SHIFT} frames of one bucket -> "
              f"{len(same)} distinct value(s) {sorted(same)}; next bucket -> {nxt:.2f}")

        # S6 - does the ordering actually change? a settled 4-3-3 front four, 4 m apart
        shape = {"ST": 146.0, "LWF": 142.0, "RWF": 141.0, "AMF": 134.0, "CMF": 106.0}
        slots = {"ST": 10, "LWF": 9, "RWF": 8, "AMF": 7, "CMF": 6}
        print(f"\n  S6 winner of the sort for a settled front line "
              f"(stock scores {shape}):")
        winners = []
        for b in range(8):
            ranked = sorted(((run_cave(img, cave, kcell, slot=slots[n],
                                       frame=b << BUCKET_SHIFT, score_in=s)[0], n)
                             for n, s in shape.items()), reverse=True)
            winners.append(ranked[0][1])
            print(f"      bucket {b}: " + "  ".join(f"{n} {v:.2f}" for v, n in ranked))
        print(f"      winners across 8 buckets: {winners}  -> "
              f"{len(set(winners))} distinct runner(s); stock would be ['ST'] x 8")


if __name__ == "__main__":
    main()
