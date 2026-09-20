#!/usr/bin/env python3
"""Runtime code injection for eFootball.exe: arbitrary-size payloads, no PE surgery.

tools/cave_alloc.py scavenges inter-function padding and is therefore capped at 21 bytes per
chunk (MSVC aligns function entries to 16, so padding never exceeds 15). This tool removes that
ceiling by allocating a fresh page in the LIVE process with VirtualAllocEx, placed within
+/-2GB of the module so an ordinary 5-byte `jmp rel32` at the hook site reaches it. Nothing on
disk is touched and the PE headers are not modified, so Denuvo's file-integrity surface is
untouched -- which is the whole point of doing it this way first.

    hook site  ->  jmp rel32  ->  [ payload | relocated stolen bytes | jmp rel32 back ]
                                  (VirtualAllocEx'd, RWX, arbitrary size)

Commands
    plan         OFFLINE. Decode the hook site from PRISTINE, prove the steal is safe, print the
                 exact bytes that would be written. Needs no running game. Run this first.
    alloc-probe  READ-ONLY against the live process: show where a near allocation would land.

`install` / `uninstall` are deliberately NOT implemented yet: the owner's standing rule is that
no exe or dt270 change is applied without asking, and `plan` is what makes that question
answerable. Add them once a plan has been reviewed.

Safety gates in `plan` -- all three are things tools/cave_alloc.py currently lacks:
  * whole instructions only; never splits one
  * refuses to relocate RIP-relative or pc-relative instructions (they break when moved)
  * REFERENCE GATE: refuses if any branch elsewhere in .xcode targets a byte strictly inside
    the stolen range, which would drop control into the middle of our jump
and it proves rel32 reach in both directions rather than assuming it.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import struct
import sys
from pathlib import Path

import capstone

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_patch as lp  # noqa: E402  (plumbing: find_pid, open_proc, module_base, query)

PRISTINE = Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")
IMAGE_BASE = 0x140000000
XCODE_VA = 0x140001000
XCODE_RAW = 0x400
XCODE_SIZE = 0x59FB000
REL32_MAX = 0x7FFF0000          # a safety margin under the true 2GB

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_FREE = 0x10000
PAGE_EXECUTE_READWRITE = 0x40

_wt = ctypes.wintypes
lp.k32.VirtualAllocEx.restype = ctypes.c_void_p
lp.k32.VirtualAllocEx.argtypes = [_wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                  _wt.DWORD, _wt.DWORD]
lp.k32.VirtualFreeEx.restype = _wt.BOOL
lp.k32.VirtualFreeEx.argtypes = [_wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, _wt.DWORD]

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
md.detail = True


# ------------------------------------------------------------------ static image helpers

def load_image() -> bytes:
    if not PRISTINE.exists():
        sys.exit(f"PRISTINE image not found: {PRISTINE}")
    return PRISTINE.read_bytes()


def va_to_off(va: int) -> int:
    if not (XCODE_VA <= va < XCODE_VA + XCODE_SIZE):
        sys.exit(f"0x{va:x} is outside .xcode - this tool hooks gameplay code only")
    return va - IMAGE_BASE - 0xC00


def steal_instructions(img: bytes, va: int, minimum: int = 5):
    """Decode forward from `va` until at least `minimum` bytes of WHOLE instructions."""
    off = va_to_off(va)
    out, total = [], 0
    for ins in md.disasm(img[off:off + 64], va):
        out.append(ins)
        total += ins.size
        if total >= minimum:
            return out, total
    sys.exit(f"could not decode {minimum} bytes of instructions at 0x{va:x}")


def relocation_problem(ins) -> str | None:
    """Return a reason if this instruction cannot be moved verbatim, else None."""
    if ins.mnemonic.startswith(("j", "call", "loop")) and ins.op_str.startswith("0x"):
        return f"{ins.mnemonic} {ins.op_str} is pc-relative"
    try:
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                return "RIP-relative memory operand"
    except Exception:
        pass
    if "rip" in ins.op_str:
        return "mentions rip"
    return None


def reference_gate(img: bytes, lo: int, hi: int, cap: int = 24):
    """Branches anywhere in .xcode whose target lands STRICTLY inside (lo, hi).

    Deliberately conservative: it scans for the rel32 (E8/E9) and rel8 (EB/7x) encodings
    without a full decode, so it can report bytes that are not really instructions. A false
    positive costs you a different hook site; a false negative costs you a crash.
    """
    hits = []
    body = img[XCODE_RAW:XCODE_RAW + XCODE_SIZE]
    base = XCODE_VA
    for i in range(len(body) - 5):
        b = body[i]
        if b in (0xE8, 0xE9):
            tgt = base + i + 5 + struct.unpack_from("<i", body, i + 1)[0]
        elif b == 0xEB or 0x70 <= b <= 0x7F:
            tgt = base + i + 2 + struct.unpack_from("<b", body, i + 1)[0]
        else:
            continue
        if lo < tgt < hi:
            hits.append((base + i, tgt))
            if len(hits) >= cap:
                break
    return hits


def enc_jmp_rel32(src: int, dst: int) -> bytes:
    delta = dst - (src + 5)
    if not (-REL32_MAX <= delta <= REL32_MAX):
        sys.exit(f"rel32 out of range: 0x{src:x} -> 0x{dst:x} (delta 0x{delta:x})")
    return b"\xE9" + struct.pack("<i", delta)


def enc_jmp_abs(dst: int) -> bytes:
    """14-byte absolute indirect jump, for the cave-trampoline fallback."""
    return b"\xFF\x25\x00\x00\x00\x00" + struct.pack("<Q", dst)


# ------------------------------------------------------------------ the plan

def build_plan(spec: dict, img: bytes, block_va: int):
    raw = spec["hook_va"]
    hook = int(raw, 16) if isinstance(raw, str) else raw
    payload = bytes.fromhex(spec.get("payload_hex", "").replace(" ", ""))
    want = max(5, int(spec.get("min_steal", 5)))

    ins, stolen_len = steal_instructions(img, hook, want)
    off = va_to_off(hook)
    stolen = img[off:off + stolen_len]

    problems = [f"0x{i.address:x} {i.mnemonic} {i.op_str} -- {w}"
                for i in ins for w in [relocation_problem(i)] if w]
    refs = reference_gate(img, hook, hook + stolen_len)

    body = payload + stolen
    body += enc_jmp_rel32(block_va + len(body), hook + stolen_len)
    patch = enc_jmp_rel32(hook, block_va) + b"\x90" * (stolen_len - 5)

    return {
        "hook_va": hex(hook),
        "stolen_len": stolen_len,
        "stolen_hex": stolen.hex(),
        "stolen_disasm": [f"0x{i.address:x}  {i.mnemonic} {i.op_str}" for i in ins],
        "payload_len": len(payload),
        "block_va": hex(block_va),
        "block_len": len(body),
        "block_bytes_hex": body.hex(),
        "hook_patch_hex": patch.hex(),
        "relocation_problems": problems,
        "reference_gate_hits": [f"0x{a:x} -> 0x{t:x}" for a, t in refs],
        "safe": not problems and not refs,
    }


def cmd_plan(a):
    img = load_image()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    block_va = int(a.assume_block, 16) if a.assume_block else IMAGE_BASE + 0x16000000
    p = build_plan(spec, img, block_va)

    print(f"hook site       0x{int(p['hook_va'], 16):x}")
    print(f"stolen          {p['stolen_len']} bytes (whole instructions)")
    for line in p["stolen_disasm"]:
        print(f"                  {line}")
    print(f"payload         {p['payload_len']} bytes")
    print(f"block           {p['block_va']}  ({p['block_len']} bytes total)")
    print()
    for label, rows in (("REFUSED - stolen bytes are not relocatable:", p["relocation_problems"]),
                        ("REFUSED - something branches into the middle of the steal:",
                         p["reference_gate_hits"])):
        if rows:
            print(label)
            for r in rows:
                print(f"   {r}")
    if p["safe"]:
        print("SAFE: whole instructions, nothing pc-relative, no branch lands inside the steal.")
        print(f"   hook patch    {p['hook_patch_hex']}")
        blk = p["block_bytes_hex"]
        print(f"   block image   {blk[:96]}{'...' if len(blk) > 96 else ''}")
    if a.out:
        Path(a.out).write_text(json.dumps(p, indent=1), encoding="utf-8")
        print(f"\nplan written to {a.out}")
    return 0 if p["safe"] else 1


# ------------------------------------------------------------------ live process

def alloc_near(h, anchor: int, size: int, dry=True):
    """Find a MEM_FREE region that can actually host `size` at 64K granularity, within
    rel32 range of `anchor`; commit RWX there unless dry.

    Windows allocates at 64K granularity, so the usable base is the region's start rounded
    UP to 64K -- and that rounded base plus the payload must still fit INSIDE the region.
    Skipping that second check proposes bases that are not in the free block at all and
    VirtualAllocEx rejects them with ERROR_INVALID_ADDRESS (487).
    """
    GRAN = 0x10000
    best = None
    for direction in (1, -1):
        addr = anchor
        steps = 0
        while 0 < addr < 0x7FFFFFFF0000 and steps < 20000:
            steps += 1
            mbi = lp.query(h, addr)
            if mbi is None or mbi.RegionSize == 0:
                break
            if abs(mbi.BaseAddress - anchor) >= REL32_MAX:
                break
            if mbi.State == MEM_FREE:
                base = (mbi.BaseAddress + GRAN - 1) & ~(GRAN - 1)
                end = mbi.BaseAddress + mbi.RegionSize
                if base + size <= end and abs(base - anchor) < REL32_MAX:
                    best = base
                    break
            addr = (mbi.BaseAddress + mbi.RegionSize) if direction > 0 else (mbi.BaseAddress - 1)
        if best:
            break
    if not best:
        return None, "no free region of that size at 64K granularity within rel32 range"
    if dry:
        return best, None
    p = lp.k32.VirtualAllocEx(h, ctypes.c_void_p(best), ctypes.c_size_t(size),
                              MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not p:
        return None, f"VirtualAllocEx at 0x{best:x} failed (err {ctypes.get_last_error()})"
    return int(p), None


def cmd_alloc_probe(a):
    pid = lp.find_pid()
    if not pid:
        print("eFootball.exe is not running - nothing to probe.")
        return 2
    h = lp.open_proc(pid)
    base, _ = lp.module_base(h)
    anchor = base + 0x3000000                       # roughly the middle of the match band
    print(f"pid {pid}   module base 0x{base:x}   slide 0x{base - IMAGE_BASE:x}")
    got, err = alloc_near(h, anchor, a.size, dry=True)
    if got:
        print(f"a {a.size}-byte block would land near 0x{got:x} "
              f"(delta 0x{abs(got - anchor):x} from the anchor - rel32 reachable)")
        return 0
    print(f"no candidate: {err}")
    return 1


def cmd_alloc_test(a):
    """Real round trip: VirtualAllocEx -> write -> read back -> VirtualFreeEx.

    Allocates and frees memory in the target. Touches no game code and no game state.
    """
    pid = lp.find_pid()
    if not pid:
        print("eFootball.exe is not running.")
        return 2
    h = lp.open_proc(pid, write=True)
    base, _ = lp.module_base(h)
    anchor = base + 0x3000000
    size = a.size

    where, err = alloc_near(h, anchor, size, dry=True)
    if not where:
        print(f"no candidate region: {err}")
        return 1
    print(f"candidate base   0x{where:x}  (delta 0x{abs(where - anchor):x} from anchor)")

    got = lp.k32.VirtualAllocEx(h, ctypes.c_void_p(where), ctypes.c_size_t(size),
                                MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not got:
        e = ctypes.get_last_error()
        print(f"VirtualAllocEx at the chosen base FAILED (err {e}); retrying with base=NULL...")
        got = lp.k32.VirtualAllocEx(h, None, ctypes.c_size_t(size),
                                    MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if not got:
            print(f"VirtualAllocEx(NULL) also failed (err {ctypes.get_last_error()})")
            return 1
    got = int(got)
    delta = got - anchor
    reach = abs(delta) < REL32_MAX
    print(f"ALLOCATED        0x{got:x}  ({size} bytes, RWX)")
    print(f"distance from anchor 0x{abs(delta):x}  -> rel32 reachable: {reach}")

    probe = bytes.fromhex("cc4831c0c390") + b"eFB-live-inject"
    ok, _old, werr = lp.write_mem(h, got, probe)
    print(f"write {len(probe)} bytes: {'OK' if ok else 'FAILED - ' + werr}")
    back = lp.read_mem(h, got, len(probe))
    same = back == probe
    print(f"read back        {'MATCHES' if same else 'MISMATCH'}  ({back[:8].hex()}...)")

    freed = lp.k32.VirtualFreeEx(h, ctypes.c_void_p(got), 0, 0x8000)  # MEM_RELEASE
    print(f"VirtualFreeEx    {'OK' if freed else 'FAILED (err %d)' % ctypes.get_last_error()}")
    gone = lp.query(h, got)
    print(f"region state now 0x{gone.State:x} ({'MEM_FREE' if gone and gone.State == MEM_FREE else 'still committed'})")

    return 0 if (ok and same and freed) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="OFFLINE: prove a hook site is safe and show the byte image")
    p.add_argument("spec", help='JSON: {"hook_va": "0x...", "payload_hex": "...", "min_steal": 5}')
    p.add_argument("--assume-block", help="pretend the block lands at this hex VA")
    p.add_argument("--out", help="write the plan JSON here")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("alloc-test",
                       help="REAL round trip: allocate, write, read back, free. Mutates nothing "
                            "in the game - only asks Windows for memory and gives it back.")
    p.add_argument("--size", type=lambda s: int(s, 0), default=0x1000)
    p.set_defaults(fn=cmd_alloc_test)

    p = sub.add_parser("alloc-probe", help="READ-ONLY: where would a near allocation land?")
    p.add_argument("--size", type=lambda s: int(s, 0), default=0x1000,
                   help="bytes; decimal or 0x-hex")
    p.set_defaults(fn=cmd_alloc_probe)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
