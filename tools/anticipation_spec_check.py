#!/usr/bin/env python3
"""
anticipation_spec_check.py — re-prove the SHIPPED spec file, from the file.

emu_anticipation.py proves a Layout object it just built in memory and then asks cave_alloc to
write a spec from an equivalent one.  This tool closes the last gap: it reads
tools/data/patches/anticipation-ability.json off disk, takes the chunk VAs and bytes from the
`patches` array ONLY, and re-runs the proof at those FINAL addresses.  If the spec writer ever
emitted something other than what was proven, this fails.

Read-only.  Both images are opened with mmap ACCESS_READ; nothing is written anywhere.

    python tools/anticipation_spec_check.py
    python tools/anticipation_spec_check.py --exe <path>

Checks, in order:
  C1  the spec validates against the target image: every `expect` matches the bytes on disk,
      len(expect) == len(patch), chunk expects are all-0xCC (so `remove` restores padding),
      the hook expect is the 16 stolen bytes, and no two entries overlap each other.
  C2  the tunable cells named in the spec really hold PIVOT and GAIN_Q8, inside a chunk's bytes.
  C3  the chain is connected: disassemble from the hook, follow every jmp, and confirm the walk
      visits all chunks and terminates at the return site — from the file's bytes, not the layout.
  C4  emulation at the FINAL addresses: hook -> chain -> return, attr 40..99, edi must equal
      base - floor((min(attr,cap)-PIVOT)*GAIN) + ballFrames, with the register/memory footprint
      bounded and the stolen tail's call arguments restored.
  C5  identity: at attr == PIVOT every live register is bit-identical to the stock path.
  C6  no collision: the spec's byte ranges against every other spec in tools/data/patches,
      against the reservation ledger, and against the two historically occupied caves.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capstone

import cave_alloc
import emu_anticipation as EA
from emu_anticipation import HOOK, HOOK_RET, REGION, STOLEN, ATTR_CAP, fresh

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "tools" / "data" / "patches" / "anticipation-ability.json"
OCCUPIED = {0x1438B4835: 91, 0x14105ED1E: 86}      # the two historic >=64 B runs
STATE = REPO / "build" / "exe_patch_state.json"


def ok(v):
    return "PASS" if v else "FAIL"


def load(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    ents = []
    for e in d["patches"]:
        va = int(e["va"], 16) if "va" in e else cave_alloc.BASE + int(e["module_offset"], 16)
        ents.append(dict(va=va, expect=bytes.fromhex(e["expect"]), patch=bytes.fromhex(e["patch"]),
                         name=e.get("name", ""), chunk=e.get("chunk")))
    return d, ents


# ------------------------------------------------------------------------------------ C1
def c1_validate(d, ents, img) -> bool:
    print("\n== C1  the spec validates against the target image")
    good = True
    for e in ents:
        cur = img.read_va(e["va"], len(e["expect"]))
        m = cur == e["expect"]
        same_len = len(e["expect"]) == len(e["patch"])
        kind = "chunk" if e["chunk"] is not None else "HOOK "
        extra = ""
        if e["chunk"] is not None:
            allcc = set(e["expect"]) == {0xCC}
            extra = f"  expect all-int3 {allcc}"
            good &= allcc
        else:
            st = e["expect"] == STOLEN
            extra = f"  expect == the 16 stolen bytes {st}"
            good &= st
        print(f"   {kind} {e['va']:#x}  {len(e['patch']):>3d} B  on-disk expect matches {m}"
              f"   len(expect)==len(patch) {same_len}{extra}")
        good &= m and same_len
    rs = sorted((e["va"], e["va"] + len(e["patch"])) for e in ents)
    olap = any(rs[i][1] > rs[i + 1][0] for i in range(len(rs) - 1))
    print(f"   entries overlapping each other: {olap}  (must be False)")
    print(f"   entry order: {'chunks first, hook last' if ents[-1]['chunk'] is None else 'HOOK NOT LAST'}")
    good &= not olap and ents[-1]["chunk"] is None
    lay = d["cave_layout"]
    sha_ok = lay["target_image_sha1"] == img.sha1
    print(f"   spec was built for image sha1 {lay['target_image_sha1']}  == target {sha_ok}")
    return bool(good and sha_ok)


# ------------------------------------------------------------------------------------ C2
def c2_tunables(d, ents) -> bool:
    print("\n== C2  the tunable cells hold what the spec says they hold")
    blob = {e["va"]: e["patch"] for e in ents}
    good = True
    for name, t in d["tunables"].items():
        va = int(t["va"], 16)
        host = [b for b in blob if b <= va and va + 4 <= b + len(blob[b])]
        if not host:
            print(f"   {name:<8s} {va:#x}  NOT INSIDE ANY PATCHED RANGE")
            good = False
            continue
        b = blob[host[0]]
        got = struct.unpack_from("<i", b, va - host[0])[0]
        m = got == t["value"]
        print(f"   {name:<8s} {va:#x}  int32 LE = {got}   spec says {t['value']}   {m}")
        good &= m
    return bool(good)


# ------------------------------------------------------------------------------------ C3
def c3_chain(d, ents, img) -> bool:
    print("\n== C3  the chain is connected, walked from the file's bytes")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    blob = {}
    for e in ents:
        blob[e["va"]] = e["patch"]
    chunks = {e["va"]: e for e in ents if e["chunk"] is not None}
    hook = [e for e in ents if e["chunk"] is None][0]

    def at(va):
        for b, code in blob.items():
            if b <= va < b + len(code):
                return code[va - b:], b
        return img.read_va(va, 16), None

    # the hook itself
    code, _ = at(hook["va"])
    ins = next(md.disasm(bytes(code), hook["va"]))
    print(f"   hook {hook['va']:#x}  {ins.mnemonic} {ins.op_str}")
    if ins.mnemonic != "jmp":
        print("   the hook does not start with a jmp — FAIL")
        return False
    tgt = int(ins.op_str, 16)
    entry = int(d["cave_layout"]["entry"], 16)
    print(f"   hook jumps to {tgt:#x}   cave_layout entry {entry:#x}   match {tgt == entry}")
    good = tgt == entry
    pad = bytes(code[ins.size:len(hook['patch'])])
    print(f"   hook tail padding {pad.hex()}  ({len(pad)} B, all nop {set(pad) <= {0x90}})")
    good &= set(pad) <= {0x90}

    seen, va, steps = [], tgt, 0
    while steps < 200:
        steps += 1
        if va not in chunks:
            print(f"   walk left the chunk set at {va:#x} — FAIL")
            return False
        if va in seen:
            print(f"   the chain loops back to {va:#x} — FAIL")
            return False
        seen.append(va)
        code = blob[va]
        n, last = 0, None
        for i in md.disasm(code, va):
            n += i.size
            last = i
        if n != len(code):
            print(f"   chunk {va:#x} does not decode exactly ({n}/{len(code)}) — FAIL")
            return False
        if last.mnemonic != "jmp":
            print(f"   chunk {va:#x} does not end in jmp ({last.mnemonic}) — FAIL")
            return False
        nxt = int(last.op_str, 16)
        print(f"   chunk {chunks[va]['chunk']:>2d} {va:#x} {len(code):>3d} B -> {nxt:#x}"
              f"{'   (the return site)' if nxt == HOOK_RET else ''}")
        if nxt == HOOK_RET:
            break
        va = nxt
    all_seen = len(seen) == len(chunks)
    print(f"   chunks visited {len(seen)}/{len(chunks)}  every chunk on the path {all_seen}")
    print(f"   terminates at the stock return site {HOOK_RET:#x}: {nxt == HOOK_RET}")
    return bool(good and all_seen and nxt == HOOK_RET)


# ------------------------------------------------------------------------------------ C4/C5
def overlays_from_spec(ents):
    return [(e["va"], e["patch"]) for e in ents if e["chunk"] is not None]


def hook_overlay(ents):
    h = [e for e in ents if e["chunk"] is None][0]
    return (h["va"], h["patch"])


def model(attr, gain_q8, pivot, cap=ATTR_CAP):
    a = min(attr, cap)
    v = (a - pivot) * gain_q8
    return v >> 8 if v >= 0 else -((-v + 255) >> 8)     # sar = floor


def sar_model(attr, gain_q8, pivot, cap=ATTR_CAP):
    a = min(attr, cap)
    v = (a - pivot) * gain_q8
    return v >> 8                                       # python >> on negatives IS floor == sar


def c4_emulate(d, ents, img) -> bool:
    print("\n== C4  emulation at the FINAL laid-out addresses (bytes and VAs from the file)")
    ov = overlays_from_spec(ents) + [hook_overlay(ents)]
    pivot = d["tunables"]["PIVOT"]["value"]
    q8 = d["tunables"]["GAIN_Q8"]["value"]
    base, ebx = 0, 138
    print(f"   overlays: {len(ov)} regions, {sum(len(b) for _, b in ov)} bytes, "
          f"taken from the spec's patches[] only")
    print("      attr    stock edi   patched edi   delta   model   match")
    good = True
    for attr in (0, 40, 50, 60, pivot, 80, 90, 99, 120, 255):
        s = fresh(img, (), attr=attr, base=base, ebx=ebx)
        s.run(REGION, HOOK_RET)
        stock = EA.s32(s.uc.reg_read(EA.X.UC_X86_REG_EDI))
        e = fresh(img, ov, attr=attr, base=base, ebx=ebx)
        e.run(REGION, HOOK_RET)
        got = EA.s32(e.uc.reg_read(EA.X.UC_X86_REG_EDI))
        want = base - sar_model(attr, q8, pivot) + ebx
        delta = sar_model(attr, q8, pivot)
        m = got == want
        good &= m
        print(f"      {attr:>4d}   {stock:>10d}   {got:>11d}   {delta:>+5d}   {want:>5d}   {m}")
    # one detailed footprint pass over the cave alone, at a representative attribute
    e = fresh(img, ov, attr=99, base=base, ebx=ebx, rdi=base)
    r0 = e.regs()
    e.run(HOOK, HOOK_RET)
    r1 = e.regs()
    changed = sorted(k for k in r0 if r0[k] != r1[k] and k != "rip")
    allowed = {"rax", "rcx", "rdx", "rdi", "eflags", "rsp"}
    inside = set(changed) <= allowed
    print(f"   registers the chained payload changes: {changed}")
    print(f"   inside the permitted set {sorted(allowed)}: {inside}")
    print(f"   rsp unchanged: {r0['rsp'] == r1['rsp']}   non-stack memory writes: {len(e.writes)}")
    ctx = e.uc.reg_read(EA.X.UC_X86_REG_RBP)
    want_rdx = struct.unpack("<I", e.uc.mem_read(ctx + 4, 4))[0]
    want_rcx = struct.unpack("<Q", e.uc.mem_read(ctx + 0x30, 8))[0]
    args = (r1["rdx"] & 0xFFFFFFFF) == want_rdx and r1["rcx"] == want_rcx
    print(f"   the stolen tail's call args are restored on exit (rdx=[rbp+4], rcx=[rbp+0x30]): {args}")
    return bool(good and inside and r0["rsp"] == r1["rsp"] and not e.writes and args)


def c5_identity(d, ents, img) -> bool:
    print("\n== C5  identity at the pivot")
    ov = overlays_from_spec(ents) + [hook_overlay(ents)]
    pivot = d["tunables"]["PIVOT"]["value"]
    good = True
    for adjust, base, ebx in ((100, 0, 138), (0, 25, 37), (-1000, -25, 0), (2**31 - 1, 0, 10000)):
        s = fresh(img, (), attr=pivot, adjust=adjust, base=base, ebx=ebx)
        s.run(REGION, HOOK_RET)
        a = s.regs()
        e = fresh(img, ov, attr=pivot, adjust=adjust, base=base, ebx=ebx)
        e.run(REGION, HOOK_RET)
        b = e.regs()
        diff = sorted(k for k in a if a[k] != b[k] and k not in ("rip", "xmm0", "eflags"))
        print(f"   adjust {adjust:>11d} base {base:>5d} ballFrames {ebx:>6d}: "
              f"edi {EA.s32(a['rdi']):>7d} both -> {EA.s32(b['rdi']):>7d}   "
              f"live registers differing: {diff or 'NONE'}")
        good &= not diff and a["rdi"] == b["rdi"]
    print("   (xmm0 and flags are excluded: S7 in emu_anticipation.py proves both are dead at the")
    print("    return site BY EXECUTION — it runs the rest of the function for five different")
    print("    incoming xmm0 values and gets an identical gait and register state each time.)")
    return bool(good)


# ------------------------------------------------------------------------------------ C6
def c6_collision(d, ents) -> bool:
    print("\n== C6  no collision")
    mine = [(e["va"], e["va"] + len(e["patch"])) for e in ents]
    hits = []
    for a, b, who in cave_alloc.claimed_ranges():
        if who.startswith(SPEC.name):
            continue
        for x, y in mine:
            if a < y and x < b:
                hits.append((who, a, b))
    print(f"   other specs / ledger rows claiming any of our bytes: {hits or 'NONE'}")
    occ = [(hex(v), n) for v, n in OCCUPIED.items()
           if any(v < y and x < v + n for x, y in mine)]
    print(f"   overlap with the two historically occupied caves "
          f"(0x1438b4835, 0x14105ed1e): {occ or 'NONE'}")
    if STATE.exists():
        st = json.loads(STATE.read_text(encoding="utf-8"))
        applied = st.get("applied", [])
        print(f"   build/exe_patch_state.json lists {len(applied)} applied spec(s); "
              f"is {SPEC.name} among them: {SPEC.name in applied}  (must be False)")
        good_state = SPEC.name not in applied
    else:
        good_state = True
    led = json.loads(cave_alloc.LEDGER.read_text(encoding="utf-8")) if cave_alloc.LEDGER.exists() else {}
    ours = [r for r in led.get("reservations", []) if r["spec"] == SPEC.name]
    print(f"   our own rows in {cave_alloc.LEDGER.name}: {len(ours)} "
          f"(one per chunk, expected {len(mine) - 1})")
    return bool(not hits and not occ and good_state and len(ours) == len(mine) - 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EA.EXE))
    ap.add_argument("--spec", default=str(SPEC))
    a = ap.parse_args()
    img = cave_alloc.Image(Path(a.exe))
    d, ents = load(Path(a.spec))
    print(f"spec   {a.spec}")
    print(f"target {a.exe}\n       sha1 {img.sha1}")
    print(f"layout {len(ents) - 1} chunk(s) + 1 hook, entry {d['cave_layout']['entry']}, "
          f"{d['cave_layout']['total_used']} B written, {d['cave_layout']['payload_bytes']} B payload")

    r = {}
    r["C1 validates"] = c1_validate(d, ents, img)
    r["C2 tunables"] = c2_tunables(d, ents)
    r["C3 chain"] = c3_chain(d, ents, img)
    r["C4 emulation"] = c4_emulate(d, ents, img)
    r["C5 identity"] = c5_identity(d, ents, img)
    r["C6 collision"] = c6_collision(d, ents)

    print("\n== VERDICT (the shipped file, re-proven at its final addresses)")
    for k, v in r.items():
        print(f"   {k:<16s} {ok(v)}")
    allgood = all(r.values())
    print(f"   overall: {ok(allgood)}")
    sys.exit(0 if allgood else 1)


if __name__ == "__main__":
    main()
