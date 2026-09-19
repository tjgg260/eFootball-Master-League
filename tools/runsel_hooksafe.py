#!/usr/bin/env python3
"""Static safety proof for the two proposed hook windows. READ-ONLY."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sys, struct, re
from pathlib import Path
import capstone
from cave_alloc import Image

PRIS = Path(r"C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE")
INST = Path(r"C:/Program Files (x86)/Steam/steamapps/common/eFootball/eFootball/Binaries/Win64/eFootball.exe")

WINDOWS = {
 "ChanceSpaceRun::vf5 tail": (0x143DF5D6A, 11),
 "DiagonalRun::vf5 success": (0x143E03FB4, 6),
}

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True

def decode(img, va, n):
    b = img.read_va(va, n)
    out=[]; tot=0
    for ins in md.disasm(b, va):
        out.append(ins); tot += ins.size
        if tot >= n: break
    return b, out, tot

for name,(va,n) in WINDOWS.items():
    print(f"== {name}  hook {va:#x} steal {n} ==")
    for who,p in (("PRISTINE",PRIS),("INSTALLED",INST)):
        img = Image(p)
        b, ins, tot = decode(img, va, n)
        print(f"  {who}: bytes {b.hex()}  decoded {tot} bytes {'OK' if tot==n else 'MISALIGNED'}")
        for i in ins:
            rip = any(o.type==capstone.x86.X86_OP_MEM and o.mem.base==capstone.x86.X86_REG_RIP for o in i.operands)
            print(f"      {i.address:#x}  {i.mnemonic:10} {i.op_str}{'   [RIP-RELATIVE]' if rip else ''}")
    print()

# ---- image-wide scan: does anything branch INTO the interior of a window?
img = Image(PRIS)
xc = [s for s in img.sections if s["name"]==".xcode"][0]
seg = img.data[xc["raw"]:xc["raw"]+xc["rsize"]]
segva = img.base + xc["rva"]
print("== image-wide: branches whose target lands strictly INSIDE a stolen window ==")
inner = {}
for name,(va,n) in WINDOWS.items():
    for a in range(va+1, va+n):
        inner[a] = name
found = {k: [] for k in WINDOWS}
# rel32: E8/E9 and 0F 8x
for m in re.finditer(rb"[\xe8\xe9]", seg):
    o = m.start()
    if o+5 > len(seg): continue
    t = segva + o + 5 + struct.unpack_from("<i", seg, o+1)[0]
    if t in inner: found[inner[t]].append((segva+o, "rel32 E8/E9"))
for m in re.finditer(rb"\x0f[\x80-\x8f]", seg):
    o = m.start()
    if o+6 > len(seg): continue
    t = segva + o + 6 + struct.unpack_from("<i", seg, o+2)[0]
    if t in inner: found[inner[t]].append((segva+o, "rel32 Jcc"))
# rel8: EB, 70-7F, E0-E3
for m in re.finditer(rb"[\xeb\x70-\x7f\xe0-\xe3]", seg):
    o = m.start()
    if o+2 > len(seg): continue
    t = segva + o + 2 + struct.unpack_from("<b", seg, o+1)[0]
    if t in inner: found[inner[t]].append((segva+o, "rel8"))
for k,v in found.items():
    print(f"  {k}: {len(v)} candidate branch(es) into the interior")
    for a,kind in v[:20]: print(f"      {a:#x}  {kind}")

# ---- absolute 4-byte / 8-byte pointers to interior addresses (jump tables, vtables)
print()
print("== absolute pointers (u32 rva-style / u64 VA) to any address in a window interior ==")
d = img.data
for a,name in sorted(inner.items()):
    pats = [("u64 VA", struct.pack("<Q", a)),
            ("u32 off-from-image-base", struct.pack("<I", a - img.base))]
    for lbl,pat in pats:
        i = d.find(pat)
        while i >= 0:
            sec = next((s["name"] for s in img.sections if s["raw"]<=i<s["raw"]+s["rsize"]), "?")
            print(f"  {a:#x} ({name}) referenced as {lbl} at file {i:#x} [{sec}]")
            i = d.find(pat, i+1)
print("  (done)")
