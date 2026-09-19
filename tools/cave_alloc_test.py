#!/usr/bin/env python3
"""cave_alloc_test.py — the proof harness for the chained code-cave allocator.

NOTHING here touches the installed game.  Both real images are opened READ-ONLY; every write goes
to a COPY of the pristine exe in the scratchpad (--work), which is deleted at the end unless
--keep.  Run with the game running; that is the point.

    PYTHONIOENCODING=utf-8 python tools/cave_alloc_test.py            # all tests
    PYTHONIOENCODING=utf-8 python tools/cave_alloc_test.py --only exec

Tests:
  exec       THE CENTRAL PROOF.  A payload that needs >= 3 chunks, with a branch whose target is
             in a different chunk, is laid out across REAL int3 runs, loaded into Unicorn at those
             real VAs, executed from the hook, and compared against (a) a pure-python model and
             (b) the SAME payload assembled contiguously in one synthetic cave.
  roundtrip  apply a generated multi-chunk spec to a copy of the exe, remove it, assert the file
             is byte-identical to before (sha1).  The project's hard gate.
  refuse     every refusal condition the allocator implements, asserted to actually refuse.
  pool       the allocator never hands out an occupied, claimed, unsafe or too-near run.
  determ     generating the spec twice produces byte-identical JSON.
  hook       the hook builder refuses a mid-instruction steal and flags a rip-relative one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cave_alloc as CA                                                    # noqa: E402
from cave_alloc import Cave, Image, Refuse                                 # noqa: E402

REPO = CA.REPO
EXE = CA.EXE
PRISTINE = CA.PRISTINE
BASE = CA.BASE

HOOK = 0x143DA6529          # the anticipation site: movd xmm0,[r12+0x23c]  (10 B, base+disp only)
HOOK_LEN = 10
RESUME = 0x143DA6533        # the instruction after it: mov edi,[r12+0x240]
GAIN_CELL = 0x145AE7580     # a real read-only float cell in .tls$

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{'  — ' + note if note else ''}")
    return cond


def banner(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


# =============================================================================== the payload
# Deliberately more instructions than any single tier-A cave (max 21 B) can hold, with a forward
# branch whose target lands in another chunk and a rip-relative read of a real literal cell.
PAYLOAD = """
        movsxd    rax, dword ptr [r12 + 0x23c]     ; the (dead) prediction-frame adjust field
        cvtsi2ss  xmm0, eax
        mulss     xmm0, dword ptr [rip + RIPREL_$gain]
        cvttss2si eax, xmm0
        cmp       eax, 0x1388
        jle       @lo
        mov       eax, 0x1388
        jmp       @done
    lo:
        cmp       eax, -0x1388
        jge       @done
        mov       eax, -0x1388
    done:
        sub       edi, eax
        movd      xmm0, dword ptr [r12 + 0x23c]    ; re-materialise the stolen instruction
        jmp       {resume:#x}
"""


def model(adjust: int, gain: float) -> int:
    """Pure-python model of PAYLOAD's effect on edi, written independently of the asm.

    cvttss2si truncates toward zero and returns the 'integer indefinite' value INT_MIN when the
    result does not fit int32 — which the clamp below then turns into -0x1388, not +0x1388."""
    import numpy as np
    f = np.float32(np.float32(adjust) * np.float32(gain))
    v = -2 ** 31 if (np.isnan(f) or not (-2 ** 31 <= float(f) < 2 ** 31)) else int(f)
    return min(0x1388, max(-0x1388, v))


# =============================================================================== emulation
def run_chain(pristine: Image, overlays, entry: int, adjust: int, edi0: int = 10000):
    """Execute the laid-out bytes at their REAL VAs on top of the real image."""
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError
    from unicorn import x86_const as X
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    ARENA, STACK = 0x10000000, 0x10100000
    uc.mem_map(ARENA, 0x200000)
    pages = {GAIN_CELL & ~0xFFFF, RESUME & ~0xFFFF, HOOK & ~0xFFFF, entry & ~0xFFFF}
    for va, code in overlays:
        for p in range(va & ~0xFFFF, (va + len(code)) | 0xFFFF, 0x10000):
            pages.add(p & ~0xFFFF)
    for p in sorted(pages):
        uc.mem_map(p, 0x10000)
        f = pristine.va_to_file(p)
        if f is not None:
            uc.mem_write(p, pristine.data[f:f + 0x10000])
    for va, code in overlays:
        uc.mem_write(va, code)                       # EMULATOR ONLY — nothing on disk changes
    uc.mem_write(RESUME, b"\xf4")                    # hlt = stop marker
    uc.reg_write(X.UC_X86_REG_RSP, STACK)
    uc.reg_write(X.UC_X86_REG_R12, ARENA)
    uc.reg_write(X.UC_X86_REG_RDI, edi0)
    uc.reg_write(X.UC_X86_REG_RAX, 0xDEAD0000)
    uc.mem_write(ARENA + 0x23C, struct.pack("<i", adjust))
    err = None
    try:
        uc.emu_start(entry, RESUME, count=4000)
    except UcError as ex:
        err = str(ex)
    return dict(edi=uc.reg_read(X.UC_X86_REG_RDI) & 0xFFFFFFFF,
                rip=uc.reg_read(X.UC_X86_REG_RIP), rsp=uc.reg_read(X.UC_X86_REG_RSP),
                err=err)


# =============================================================================== tests
def t_exec(target: Image, pristine: Image):
    banner("exec — THE CENTRAL PROOF: a chained payload executes across the hops")
    gain = struct.unpack("<f", pristine.read_va(GAIN_CELL, 4))[0]
    print(f"literal cell {GAIN_CELL:#x} = {gain}f (read from the pristine image)")
    src = PAYLOAD.format(resume=RESUME)

    pool, rej = CA.cave_pool(target=target, pristine=pristine, min_len=12, anchor=HOOK)
    lay = CA.layout_payload(src, pool=pool, exits=(RESUME,), cells={"gain": GAIN_CELL},
                            policy=dict(anchor=f"{HOOK:#x}"))
    print(f"\nchained layout: entry {lay.entry:#x}, {len(lay.chunks)} chunks, "
          f"{lay.total_used()} B written across {len(lay.chunks)} int3 runs")
    probs = CA.verify_layout(lay, target=target, verbose=True)
    ok("chained layout verifies", not probs, "; ".join(probs))
    ok("layout needs >= 3 chunks", len(lay.chunks) >= 3, f"{len(lay.chunks)} chunks")

    # the cross-chunk branch really is cross-chunk
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    crossing = []
    for c in lay.chunks:
        for ins in md.disasm(c.code, c.va):
            if ins.mnemonic in ("jle", "jge") and not (c.va <= ins.operands[0].imm < c.end):
                crossing.append((ins.address, ins.mnemonic, ins.operands[0].imm))
    ok("an intra-payload conditional branch crosses a chunk boundary", len(crossing) >= 1,
       ", ".join(f"{a:#x} {m} -> {t:#x}" for a, m, t in crossing))

    # the same payload in ONE synthetic cave (emulator-only address, never written anywhere)
    FLAT = 0x14105E000                     # inside .xcode, mapped, but only ever written in Unicorn
    flat = CA.layout_payload(src, pool=[Cave(FLAT, 200, "SYNTHETIC")], exits=(RESUME,),
                             cells={"gain": GAIN_CELL})
    ok("contiguous control layout is a single chunk", len(flat.chunks) == 1)

    rows, good = [], True
    for adjust in (-1000, -37, -1, 0, 1, 37, 100, 1000, 100000, -100000, 2147483647, -2147483648):
        a = run_chain(pristine, lay.overlays(), lay.entry, adjust)
        b = run_chain(pristine, flat.overlays(), flat.entry, adjust)
        exp = (10000 - model(adjust, gain)) & 0xFFFFFFFF
        row_ok = (a["err"] is None and b["err"] is None and a["rip"] == RESUME
                  and a["rsp"] == 0x10100000 and a["edi"] == exp and a["edi"] == b["edi"])
        good &= row_ok
        rows.append((adjust, a["edi"], b["edi"], exp, row_ok, a["err"] or ""))
    print("\n   adjust        chained edi   contiguous edi   python model   ok")
    for adj, e, f, m, g, err in rows:
        print(f"   {adj:>12}   {e:>11}   {f:>14}   {m:>12}   {'OK' if g else 'NO ' + err}")
    ok("chained == contiguous == model on 12 inputs, rip lands on the resume address, rsp intact",
       good)

    # --- rel8 collapse: in the contiguous layout the label branches are NEAR, so keystone emits
    #     the 2-byte form inside a 6-byte reservation and the allocator pads with nop.  The padding
    #     is executed, so prove it changes nothing.
    short = [ins for c in flat.chunks for ins in md.disasm(c.code, c.va)
             if ins.mnemonic in ("jle", "jge") and ins.size == 2]
    nops = sum(1 for c in flat.chunks for ins in md.disasm(c.code, c.va) if ins.mnemonic == "nop")
    ok("a near label branch collapses to rel8 and the slack is nop-padded, not left as int3",
       len(short) == 2 and nops >= 8,
       f"{len(short)} rel8 branch(es), {nops} pad nop(s) in the contiguous layout")
    ok("the padded layout still verifies and still computes the same answers",
       not CA.verify_layout(flat) and good)
    return lay


def t_roundtrip(target: Image, pristine: Image, work: Path):
    banner("roundtrip — apply a multi-chunk spec to a COPY of the exe, remove it, byte-identical")
    img = Image(work)                       # the copy is pristine, so its free pool differs
    # the pool file is keyed to the installed image; allocate against the installed image's pool
    # but write `expect` from the copy — assert they agree (they must: both are int3 there).
    pool, _ = CA.cave_pool(target=target, pristine=pristine, min_len=12, anchor=HOOK)
    doc, lay = CA.build_spec(
        description="TEST ONLY — chained-cave round-trip fixture. Never apply to the game.",
        prefix="roundtrip-test", asm_text=PAYLOAD.format(resume=RESUME), hook_va=HOOK,
        stolen_len=HOOK_LEN, exits=(RESUME,), target=target, pristine=pristine,
        cells={"gain": GAIN_CELL}, pool=pool, audit=True)
    spec = work.parent / "cave-roundtrip-test.json"
    spec.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"spec {spec.name}: {len(doc['patches'])} entries "
          f"({len(lay.chunks)} chunks + 1 hook), {lay.total_used()} B of cave + {HOOK_LEN} B hook")

    before = hashlib.sha1(work.read_bytes()).hexdigest()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    run = lambda *a: subprocess.run([sys.executable, str(REPO / "tools" / "exe_patch.py"),
                                     "--exe", str(work), *a], capture_output=True, text=True,
                                    env=env, cwd=str(REPO))                      # noqa: E731

    r = run("apply", str(spec), "--dry-run")
    ok("dry-run plans every entry and writes nothing",
       r.returncode == 0 and r.stdout.count("PATCH ") == len(doc["patches"])
       and hashlib.sha1(work.read_bytes()).hexdigest() == before,
       f"rc={r.returncode}, {r.stdout.count('PATCH ')} planned")

    r = run("apply", str(spec))
    applied = hashlib.sha1(work.read_bytes()).hexdigest()
    ok("apply writes every entry", r.returncode == 0 and applied != before, r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr)
    # the written bytes really are the layout's bytes, at the layout's addresses
    after = Image(work)
    same = all(after.read_va(c.va, len(c.code)) == c.code for c in lay.chunks)
    hookb = after.read_va(HOOK, HOOK_LEN).hex() == doc["patches"][-1]["patch"]
    ok("every chunk + the hook is on disk exactly as emulated", same and hookb)

    r = run("apply", str(spec), "--dry-run")
    ok("re-apply is a no-op ('already applied', nothing to do)",
       r.returncode == 0 and "nothing to do" in r.stdout
       and hashlib.sha1(work.read_bytes()).hexdigest() == applied)

    r = run("remove", str(spec))
    end = hashlib.sha1(work.read_bytes()).hexdigest()
    ok("ROUND TRIP: remove restores the file byte-for-byte", end == before,
       f"{before[:16]}… -> {applied[:16]}… -> {end[:16]}…")
    ok("remove reverted the hook FIRST (chunks last)",
       r.stdout.find("hook") < r.stdout.find("chunk 1/"),
       "hook at col %d, first chunk at col %d" % (r.stdout.find("hook"), r.stdout.find("chunk 1/")))
    ok("padding is 0xCC again in every cave",
       all(Image(work).read_va(c.cave.va, c.cave.length) == b"\xcc" * c.cave.length
           for c in lay.chunks))

    # a corrupted chunk must make `remove` refuse rather than write half a restore
    d = bytearray(work.read_bytes())
    f = Image(work).va_to_file(lay.chunks[0].va)
    run("apply", str(spec))
    d = bytearray(work.read_bytes())
    d[f] ^= 0xFF
    work.write_bytes(bytes(d))
    r = run("remove", str(spec))
    ok("remove REFUSES when a chunk was tampered with", r.returncode != 0 and
       "UNEXPECTED BYTES" in r.stdout, r.stdout.strip().splitlines()[-1] if r.stdout else "")
    d[f] ^= 0xFF
    work.write_bytes(bytes(d))
    run("remove", str(spec))
    ok("file is pristine again after the tamper test",
       hashlib.sha1(work.read_bytes()).hexdigest() == before)
    return doc, spec


def t_determinism(target: Image, pristine: Image, doc: dict):
    banner("determ — regenerating the spec produces identical bytes")
    pool, _ = CA.cave_pool(target=target, pristine=pristine, min_len=12, anchor=HOOK)
    doc2, _ = CA.build_spec(
        description="TEST ONLY — chained-cave round-trip fixture. Never apply to the game.",
        prefix="roundtrip-test", asm_text=PAYLOAD.format(resume=RESUME), hook_va=HOOK,
        stolen_len=HOOK_LEN, exits=(RESUME,), target=target, pristine=pristine,
        cells={"gain": GAIN_CELL}, pool=pool, audit=False)
    a = json.dumps(doc, indent=1, sort_keys=True)
    b = json.dumps(doc2, indent=1, sort_keys=True)
    ok("two independent generations are byte-identical JSON", a == b,
       f"{len(a)} vs {len(b)} chars")
    ok("no timestamp / host path / random id in the spec",
       not any(k in a.lower() for k in ("users\\\\", "20260", "timestamp", "uuid")))


def t_pool(target: Image, pristine: Image):
    banner("pool — the allocator never hands out an occupied, claimed, unsafe or too-near run")
    pool, rej = CA.cave_pool(target=target, pristine=pristine, min_len=12, anchor=HOOK)
    vas = {c.va for c in pool}
    ok("the two live caves (0x1438b4835 / 0x14105ed1e) are not in the pool",
       0x1438B4835 not in vas and 0x14105ED1E not in vas)
    ok("the run reserved by cave-fatigue-weakfoot (0x1438b4804) is not in the pool",
       0x1438B4804 not in vas)
    ok("every cave is all-int3 in the TARGET image right now",
       all(target.read_va(c.va, c.length) == b"\xcc" * c.length for c in pool[:4000]),
       "checked the 4,000 nearest to the hook")
    ok("no cave is within 32 B of the hook",
       all(not (c.va < HOOK + 32 and c.end > HOOK - 32) for c in pool))
    ok("every cave is tier A (pdata-bounded padding, no recorded reference)",
       all(c.safety == "A" and "no-refs" in c.why for c in pool))

    # exclusion really excludes
    victim = pool[0]
    p2, _ = CA.cave_pool(target=target, pristine=pristine, min_len=12, anchor=HOOK,
                         exclude=[(victim.va + 1, victim.va + 2)])
    ok("an explicit exclusion removes the overlapping run (by BYTE RANGE, not VA equality)",
       victim.va not in {c.va for c in p2} and len(p2) == len(pool) - 1,
       f"{victim.va:#x}+{victim.length}")

    # an independent re-derivation of safety, from the image bytes rather than the pool file
    t0 = time.time()
    st = {}
    probs = CA.audit_caves(pool[:40], target=target, pristine=pristine, stats=st)
    ok("independent audit of the 40 nearest caves: maximal int3 in both images, outside every "
       "RUNTIME_FUNCTION, no rel32/rel8/ptr64 reference anywhere in the image",
       not probs, f"{time.time() - t0:.1f}s, refs {st}; " + "; ".join(probs[:3]))

    # a KNOWN-BAD cave must be caught by that same audit
    bad = CA.audit_caves([Cave(0x1438B4835, 91, "X")], target=target, pristine=pristine)
    ok("the audit rejects the already-written cave 0x1438b4835", bool(bad), bad[0] if bad else "")
    bad = CA.audit_caves([Cave(HOOK, 16, "X")], target=target, pristine=pristine)
    ok("the audit rejects a range inside a live function", bool(bad),
       next((b for b in bad if "RUNTIME_FUNCTION" in b), bad[0] if bad else ""))


def t_refuse(target: Image, pristine: Image):
    banner("refuse — every refusal condition, asserted to actually refuse")
    pool, _ = CA.cave_pool(target=target, pristine=pristine, min_len=12, anchor=HOOK)
    small = [c for c in pool[:6]]

    def refuses(name, fn, needle=""):
        try:
            fn()
        except Refuse as ex:
            return ok(name, needle.lower() in str(ex).lower(), str(ex).splitlines()[0][:110])
        return ok(name, False, "DID NOT REFUSE")

    refuses("payload does not fit the pool",
            lambda: CA.layout_payload("\n".join(["nop"] * 400) + f"\njmp {RESUME:#x}",
                                      pool=small, exits=(RESUME,)), "does not fit")
    refuses("one instruction bigger than any cave's payload room",
            lambda: CA.layout_payload("mov qword ptr [rbx+0x11223], 0x44556677\n"
                                      f"jmp {RESUME:#x}", pool=[Cave(pool[0].va, 12)],
                                      exits=(RESUME,)), "largest cave in the pool")
    refuses("undefined label", lambda: CA.layout_payload("jmp @nowhere", pool=small,
                                                         exits=(RESUME,)), "undefined label")
    refuses("duplicate label",
            lambda: CA.layout_payload("a:\nnop\na:\nnop\njmp 0x143da6533", pool=small,
                                      exits=(RESUME,)), "duplicate label")
    refuses("trailing label with no instruction after it",
            lambda: CA.layout_payload("nop\njmp 0x143da6533\nend:", pool=small, exits=(RESUME,)),
            "end of the payload")
    refuses("undeclared rip-relative cell",
            lambda: CA.layout_payload("mulss xmm0, dword ptr [rip + RIPREL_$nope]\n"
                                      f"jmp {RESUME:#x}", pool=small, exits=(RESUME,)),
            "undeclared rip-relative cell")
    refuses("RIPREL written WITHOUT 'rip +' (assembles to an absolute disp32 form)",
            lambda: CA.layout_payload("mulss xmm0, dword ptr [RIPREL_$gain]\n"
                                      f"jmp {RESUME:#x}", pool=small, exits=(RESUME,),
                                      cells={"gain": GAIN_CELL}), "without 'rip +'")
    refuses("undeclared external", lambda: CA.layout_payload(f"call $ATTR_get\njmp {RESUME:#x}",
                                                             pool=small, exits=(RESUME,)),
            "undeclared external")
    refuses("more than one instruction handed to asm_one",
            lambda: CA.asm_one("nop\nnop", BASE), "one instruction per source line")
    ok("';' starts a comment (so a stray 'nop; nop' is one instruction, not two)",
       CA.asm_one("nop; nop", BASE) == b"\x90")
    refuses("empty payload", lambda: CA.layout_payload("   \n  ", pool=small, exits=(RESUME,)),
            "empty payload")
    refuses("min_cave below one payload byte + the chain jmp",
            lambda: CA.cave_pool(target=target, pristine=pristine, min_len=5), "min_len")
    refuses("pool file built for a different image",
            lambda: CA.load_pool_file(CA.REPO / "build" / "caves-pristine.json", target),
            "re-run tools/cave_scan.py")
    refuses("missing pool file (fail closed — never allocate without the classifier's gates)",
            lambda: CA.load_pool_file(CA.REPO / "build" / "no-such-pool.json", target),
            "refusing to allocate")

    # verification gates: build a deliberately broken layout and check verify_layout catches it
    lay = CA.layout_payload(PAYLOAD.format(resume=RESUME), pool=pool, exits=(RESUME,),
                            cells={"gain": GAIN_CELL})
    ok("a good layout has zero verification problems", not CA.verify_layout(lay, target=target))

    from dataclasses import replace
    broken = replace(lay, chunks=tuple(
        replace(c, code=c.code[:-CA.CHAIN_LEN] + b"\x90" * CA.CHAIN_LEN, chain_to=None)
        if c.index == 0 else c for c in lay.chunks))
    ok("verify catches a chunk that no longer ends in an unconditional transfer",
       any("unconditional transfer" in p for p in CA.verify_layout(broken)))

    bad_branch = replace(lay, chunks=tuple(
        replace(c, code=c.code[:-4] + struct.pack("<i", 0x1234)) if c.chain_to else c
        for c in lay.chunks))
    probs = CA.verify_layout(bad_branch)
    ok("verify catches a chain jmp retargeted to nowhere",
       any("chain jmp does not target" in p or "not in any chunk" in p for p in probs))

    # a branch that lands one byte INSIDE an instruction
    c0 = lay.chunks[0]
    mid = replace(lay, chunks=(replace(c0, code=CA.asm_one(f"jmp {c0.va + 1:#x}", c0.va) +
                                       c0.code[5:]),) + lay.chunks[1:])
    ok("verify catches a branch target that is not an instruction boundary",
       any("INSIDE an instruction" in p for p in CA.verify_layout(mid)))

    # a rip-relative operand pointing somewhere undeclared
    rip = CA.layout_payload("mulss xmm0, dword ptr [rip + RIPREL_0x145ae7590]\n"
                            f"jmp {RESUME:#x}", pool=pool, exits=(RESUME,),
                            cells={"gain": GAIN_CELL})
    ok("verify catches a rip-relative target outside the declared cell set",
       any("not a declared cell" in p for p in CA.verify_layout(rip)))

    # non-int3 destination
    ok("verify catches a chunk whose target bytes are not 0xCC",
       any("not int3" in p for p in CA.verify_layout(
           replace(lay, chunks=(replace(lay.chunks[0], va=HOOK, cave=Cave(HOOK, 32)),)),
           target=target)))

    # collision with a committed spec.  0x1438b4804 is still all-int3 on disk but is claimed by
    # cave-fatigue-weakfoot.json — exactly the case an image-only "is it free?" test gets wrong.
    claimed = Cave(0x1438B4804, 44, "A")
    ok("0x1438b4804 really is still int3 in the target (an image-only check would hand it out)",
       target.read_va(0x1438B4804, 44) == b"\xcc" * 44)
    refuses("a spec colliding with a range claimed by another spec file",
            lambda: CA.build_spec(description="x", prefix="collide",
                                  asm_text=f"nop\njmp {RESUME:#x}", hook_va=HOOK,
                                  stolen_len=HOOK_LEN, exits=(RESUME,), target=target,
                                  pristine=pristine, pool=[claimed], audit=False), "collides with")


def t_hook(target: Image, pristine: Image):
    banner("hook — the hook builder refuses a mid-instruction steal and flags rip-relative bytes")
    h = CA.hook_patch(target, HOOK, HOOK_LEN, 0x143DA5F24, "test")
    ok("10-byte steal at the anticipation site encodes as jmp rel32 + 5 nop",
       h["patch"].startswith("e9") and h["patch"].endswith("9090909090")
       and len(bytes.fromhex(h["patch"])) == HOOK_LEN, h["patch"])
    ok("expect == the stock bytes at the hook",
       h["expect"] == target.read_va(HOOK, HOOK_LEN).hex(), h["expect"])
    ok("no rip-relative instruction in this stolen region", "stolen_riprel" not in h)
    try:
        CA.hook_patch(target, HOOK, 9, 0x143DA5F24, "test")
        ok("refuses a steal that ends mid-instruction", False, "DID NOT REFUSE")
    except Refuse as ex:
        ok("refuses a steal that ends mid-instruction", "instruction boundary" in str(ex), str(ex)[:90])
    try:
        CA.hook_patch(target, HOOK, 4, 0x143DA5F24, "test")
        ok("refuses a steal shorter than 5 bytes", False, "DID NOT REFUSE")
    except Refuse as ex:
        ok("refuses a steal shorter than 5 bytes", "only 4 stolen" in str(ex), str(ex)[:90])
    # 0x143da6545 is the rip-relative `mulss xmm0,[rip+..]` — hooking there must be FLAGGED
    h2 = CA.hook_patch(target, 0x143DA6545, 12, 0x143DA5F24, "test")
    ok("flags a stolen RIP-relative instruction (the allocator never relocates stolen bytes)",
       "stolen_riprel" in h2, str(h2.get("stolen_riprel")))


def t_regression():
    banner("regression — the existing commands still work on the INSTALLED (read-only) exe")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    run = lambda *a: subprocess.run([sys.executable, str(REPO / "tools" / "exe_patch.py"), *a],
                                    capture_output=True, text=True, env=env, cwd=str(REPO))  # noqa
    r = run("status")
    ok("`exe_patch.py status` parses all 95 specs", r.returncode == 0 and r.stdout.count(".json") > 90,
       f"rc={r.returncode}, {r.stdout.count('.json')} spec lines")
    for name, expect_rc in (("latebox-reach.json", 0), ("press-radius.json", 0),
                            ("cave-ability-error.json", 0), ("error-sigma.json", 1)):
        r = run("apply", f"tools/data/patches/{name}", "--dry-run")
        ok(f"`apply {name} --dry-run` -> rc {expect_rc}", r.returncode == expect_rc,
           (r.stdout.strip().splitlines() or [""])[-1][:100])


# =================================================================================== main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--work", default=None, help="where to copy the pristine exe (default: temp)")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    sel = set(a.only or ["exec", "pool", "refuse", "hook", "roundtrip", "determ", "regression"])

    t0 = time.time()
    target = Image(EXE)
    pristine = Image(PRISTINE)
    print(f"target   {EXE}  sha1 {target.sha1[:16]}… ({len(target.data):,} B)  READ-ONLY")
    print(f"pristine {PRISTINE}  sha1 {pristine.sha1[:16]}…  READ-ONLY")

    if "exec" in sel:
        t_exec(target, pristine)
    if "pool" in sel:
        t_pool(target, pristine)
    if "refuse" in sel:
        t_refuse(target, pristine)
    if "hook" in sel:
        t_hook(target, pristine)
    doc = None
    if "roundtrip" in sel or "determ" in sel:
        work_dir = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="cavetest-"))
        work_dir.mkdir(parents=True, exist_ok=True)
        work = work_dir / "eFootball.exe.COPY"
        if not work.exists():
            print(f"\ncopying the pristine image -> {work} (352 MB, ~20 s)")
            shutil.copy2(PRISTINE, work)
        try:
            if "roundtrip" in sel:
                doc, _spec = t_roundtrip(target, pristine, work)
            if "determ" in sel and doc:
                t_determinism(target, pristine, doc)
        finally:
            if not a.keep and not a.work:
                shutil.rmtree(work_dir, ignore_errors=True)
                print(f"\nremoved the working copy {work_dir}")
    if "regression" in sel:
        t_regression()

    banner(f"{len(PASS)} passed, {len(FAIL)} failed  ({time.time() - t0:.0f}s)")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
