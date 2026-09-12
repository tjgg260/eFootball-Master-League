#!/usr/bin/env python3
"""
exe_map.py — static map of eFootball.exe for gameplay research.

MSVC left the RTTI in: ~6,900 type descriptors, 871 of them in the `match` namespace
(match::ai::*, match::pad::ThinkUnit*, match::player::Action*, match::ai::bp::*, ...). From a
type descriptor we can reach every class's vftable and therefore its virtual methods:

    ".?AVThinkUnitShoot@pad@match@@"  (TypeDescriptor, name at +16)
        <- RTTICompleteObjectLocator { sig, offset, cdOffset, TD rva, CHD rva, self rva }
        <- vftable[-1] == &COL   -> vftable[0..n] = virtual method addresses

Also: class hierarchy (base classes from the ClassHierarchyDescriptor), RIP-relative string
references inside each method (debug/format strings = free semantic labels), and the code
xrefs to any address (who calls a method, who reads a table).

    python tools/exe_map.py build                 # -> build/exe_map.json (+ summary)
    python tools/exe_map.py class ThinkUnitShoot  # vtable, bases, methods, strings per method
    python tools/exe_map.py grep Shoot            # classes whose name matches
    python tools/exe_map.py xrefs 0x145349f40     # callers / referrers of an address
    python tools/exe_map.py strings 0x14534a530 0x400   # strings referenced by a code range

Read-only; works on the installed exe (no game running needed). Denuvo note: the exe must
never be modified on disk — runtime patches go through tools/live_patch.py.
"""
from __future__ import annotations

import argparse
import json
import mmap
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
MAP = REPO / "build" / "exe_map.json"


class Image:
    def __init__(self, path: Path = EXE):
        self.path = path
        self.f = open(path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        d = self.m[:0x1000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.secs = []
        for i in range(nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            chars = struct.unpack_from("<I", s, 36)[0]
            self.secs.append(dict(name=s[:8].rstrip(b"\0").decode(), va=va, vsize=vsize, raw=raw, rsize=rsize,
                                  exec=bool(chars & 0x20000000)))
        self.size_of_image = max(s["va"] + s["vsize"] for s in self.secs)
        self._md = None

    # -- address translation --
    def rva2off(self, r):
        for s in self.secs:
            if s["va"] <= r < s["va"] + s["vsize"]:
                o = r - s["va"]
                return s["raw"] + o if o < s["rsize"] else None
        return None

    def off2rva(self, o):
        for s in self.secs:
            if s["raw"] <= o < s["raw"] + s["rsize"]:
                return s["va"] + (o - s["raw"])
        return None

    def va_ok(self, va):
        r = va - self.base
        return 0 < r < self.size_of_image and self.rva2off(r) is not None

    def read(self, rva, n):
        o = self.rva2off(rva)
        if o is None:
            return b"\0" * n
        b = self.m[o:o + n]
        return b + b"\0" * (n - len(b))

    def u64(self, rva): return struct.unpack("<Q", self.read(rva, 8))[0]
    def u32(self, rva): return struct.unpack("<I", self.read(rva, 4))[0]

    def cstr(self, rva, limit=400):
        o = self.rva2off(rva)
        if o is None:
            return ""
        e = self.m.find(b"\0", o, o + limit)
        return self.m[o:e if e >= 0 else o + limit].decode("latin1")

    def section_of(self, rva):
        for s in self.secs:
            if s["va"] <= rva < s["va"] + s["vsize"]:
                return s["name"]
        return None

    @property
    def md(self):
        if self._md is None:
            import capstone
            self._md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            self._md.detail = True
        return self._md

    def disasm(self, rva, n):
        return list(self.md.disasm(self.read(rva, n), self.base + rva))

    def function_body(self, rva, limit=0x20000):
        out, run = [], 0
        for ins in self.md.disasm(self.read(rva, limit), self.base + rva):
            if ins.mnemonic == "int3":
                run += 1
                if run >= 2:
                    break
                continue
            run = 0
            out.append(ins)
            if ins.mnemonic == "ret" and len(out) > 2:
                # keep going only if the next bytes aren't padding; cheap heuristic
                nxt = self.read(ins.address + ins.size - self.base, 2)
                if nxt.startswith(b"\xcc"):
                    break
        return out

    def rip_targets(self, ins):
        import capstone
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                yield op.mem.disp + ins.address + ins.size - self.base


# ----------------------------------------------------------------------------------------
# RTTI
# ----------------------------------------------------------------------------------------

def demangle(n: str) -> str:
    """'ThinkUnitShoot@pad@match' -> 'match::pad::ThinkUnitShoot' (templates left raw)."""
    parts = n.split("@")
    return "::".join(reversed(parts))


def build_map(img: Image) -> dict:
    m = img.m
    tds = {}      # TD rva -> name
    for mt in re.finditer(rb"\.\?A[VU]([A-Za-z0-9_@?$]{2,300})@@", m):
        rva = img.off2rva(mt.start() - 16)
        if rva is None:
            continue
        tds[rva] = demangle(mt.group(1).decode("latin1"))
    print(f"  type descriptors: {len(tds)}")

    # COLs: scan for the 4-byte TD rva preceded by (sig=1 at -12) — COL = [sig, off, cdoff, TD, CHD, self]
    cols = {}     # COL rva -> (TD rva, offset, CHD rva)
    td_set = set(tds)
    for s in img.secs:
        if s["exec"] or s["rsize"] == 0:
            continue
        seg = m[s["raw"]:s["raw"] + s["rsize"]]
        for i in range(0, len(seg) - 24, 4):
            td = struct.unpack_from("<I", seg, i + 12)[0]
            if td in td_set and struct.unpack_from("<I", seg, i)[0] == 1:
                selfrva = struct.unpack_from("<I", seg, i + 20)[0]
                rva = s["va"] + i
                if selfrva == rva:
                    cols[rva] = (td, struct.unpack_from("<I", seg, i + 4)[0], struct.unpack_from("<I", seg, i + 16)[0])
    print(f"  complete object locators: {len(cols)}")

    # vftables: 8-byte pointer to COL VA, vftable starts right after
    col_va = {img.base + r: r for r in cols}
    vtables = {}  # vft rva -> dict
    for s in img.secs:
        if s["exec"] or s["rsize"] == 0:
            continue
        seg = m[s["raw"]:s["raw"] + s["rsize"]]
        for i in range(0, len(seg) - 8, 8):
            q = struct.unpack_from("<Q", seg, i)[0]
            if q in col_va:
                col = cols[col_va[q]]
                vft = s["va"] + i + 8
                methods = []
                j = 0
                while True:
                    p = struct.unpack_from("<Q", seg, i + 8 + j * 8)[0] if i + 16 + j * 8 <= len(seg) else 0
                    if not img.va_ok(p):
                        break
                    sec = img.section_of(p - img.base)
                    if sec is None or not any(x["name"] == sec and x["exec"] for x in img.secs):
                        break
                    methods.append(p - img.base)
                    j += 1
                    # stop at the next vftable's COL pointer
                    nxt = struct.unpack_from("<Q", seg, i + 8 + j * 8)[0] if i + 16 + j * 8 <= len(seg) else 0
                    if nxt in col_va:
                        break
                vtables[vft] = dict(cls=tds[col[0]], offset=col[1], chd=col[2], methods=methods)
    print(f"  vftables: {len(vtables)}")

    # class hierarchy: CHD { sig, attrs, numBase, pBaseClassArray(rva) } ; BCD { TD rva, numContained, pmd[3], attrs }
    bases = {}
    for vft, v in vtables.items():
        chd = v["chd"]
        nb = img.u32(chd + 8)
        arr = img.u32(chd + 12)
        lst = []
        for k in range(min(nb, 64)):
            bcd = img.u32(arr + 4 * k)
            td = img.u32(bcd)
            if td in tds:
                lst.append(tds[td])
        v["bases"] = lst[1:]   # first entry is the class itself
    classes = defaultdict(list)
    for vft, v in vtables.items():
        classes[v["cls"]].append(dict(vftable=vft, offset=v["offset"], methods=v["methods"], bases=v["bases"]))
    return dict(base=img.base, exe=str(img.path), size=img.path.stat().st_size,
                sections=img.secs, classes=classes)


def load_map():
    if not MAP.exists():
        sys.exit("run: python tools/exe_map.py build")
    return json.loads(MAP.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------------------------

def method_strings(img: Image, rva: int, limit=0x4000):
    """Strings referenced RIP-relatively from a function (debug/format strings etc.)."""
    out = []
    for ins in img.function_body(rva, limit):
        if ins.mnemonic not in ("lea", "mov"):
            continue
        for t in img.rip_targets(ins):
            s = img.cstr(t, 200)
            if len(s) >= 4 and all(32 <= ord(c) < 127 for c in s):
                out.append((ins.address - img.base, s))
    return out


def calls_of(img: Image, rva: int, limit=0x4000):
    out = []
    for ins in img.function_body(rva, limit):
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            out.append(int(ins.op_str, 16) - img.base)
    return out


def scan_xrefs(img: Image, target_rva: int):
    """Direct calls/jmps (rel32) and RIP-relative data references to target, across all code."""
    hits = []
    for s in img.secs:
        if not s["exec"] or s["rsize"] == 0:
            continue
        seg = img.m[s["raw"]:s["raw"] + s["rsize"]]
        # E8/E9 rel32
        for mt in re.finditer(rb"[\xe8\xe9]", seg):
            o = mt.start()
            if o + 5 > len(seg):
                continue
            disp = struct.unpack_from("<i", seg, o + 1)[0]
            if s["va"] + o + 5 + disp == target_rva:
                hits.append(("call" if seg[o] == 0xE8 else "jmp", s["va"] + o))
        # RIP-relative modrm (05/0D/15/1D/25/2D/35/3D after common opcodes)
        for mt in re.finditer(rb"[\x48\x4c\x4d\x49]?[\x8d\x8b\x89\x3b\x39\xff\x0f][\x05\x0d\x15\x1d\x25\x2d\x35\x3d\x10\x11\x2e\x28\x29\x59\x58\x5c]", seg):
            o = mt.start()
            k = o + len(mt.group())
            if k + 4 > len(seg):
                continue
            disp = struct.unpack_from("<i", seg, k)[0]
            if s["va"] + k + 4 + disp == target_rva:
                hits.append(("ref", s["va"] + o))
    return hits


def cmd_build(a):
    img = Image(Path(a.exe))
    print(f"exe: {img.path} ({img.path.stat().st_size:,} B)")
    mp = build_map(img)
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(mp), encoding="utf-8")
    cls = mp["classes"]
    match = [c for c in cls if c.startswith("match::")]
    nmeth = sum(len(v["methods"]) for c in cls.values() for v in c)
    print(f"classes with vftables: {len(cls)} ({len(match)} in match::), virtual methods: {nmeth}")
    print(f"wrote {MAP}")
    return 0


def cmd_grep(a):
    mp = load_map()
    pat = re.compile(a.pattern, re.I)
    for c in sorted(mp["classes"]):
        if pat.search(c):
            v = mp["classes"][c]
            print(f"{c:70} vft={v[0]['vftable'] + mp['base']:#x} methods={len(v[0]['methods'])} bases={' < '.join(v[0]['bases'][:3])}")
    return 0


def cmd_class(a):
    mp = load_map()
    img = Image(Path(a.exe))
    hits = [c for c in mp["classes"] if c == a.name or c.endswith("::" + a.name)]
    if not hits:
        hits = [c for c in mp["classes"] if a.name.lower() in c.lower()]
    for c in hits[:a.max]:
        for v in mp["classes"][c]:
            print(f"== {c}  vftable {v['vftable'] + mp['base']:#x}  (this+{v['offset']})  bases: {' < '.join(v['bases']) or '-'}")
            for i, mrva in enumerate(v["methods"]):
                body = img.function_body(mrva, 0x4000)
                strs = method_strings(img, mrva) if a.strings else []
                ncall = sum(1 for ins in body if ins.mnemonic == "call")
                print(f"   [{i:2}] {mrva + mp['base']:#x}  {len(body):5} ins  {ncall:3} calls" + (f"  strings: {[s for _, s in strs][:6]}" if strs else ""))
    return 0


def cmd_xrefs(a):
    img = Image(Path(a.exe))
    tgt = int(a.addr, 16)
    if tgt >= img.base:
        tgt -= img.base
    for kind, rva in scan_xrefs(img, tgt):
        print(f"{kind:5} {rva + img.base:#x}")
    return 0


def cmd_strings(a):
    img = Image(Path(a.exe))
    rva = int(a.addr, 16)
    if rva >= img.base:
        rva -= img.base
    for at, s in method_strings(img, rva, int(a.length, 16) if a.length else 0x4000):
        print(f"{at + img.base:#x}  {s}")
    return 0


def cmd_disasm(a):
    """Disassemble a function (until padding) or a fixed byte length, annotating RIP-relative
    targets with strings / vftable class names / known functions from the map."""
    img = Image(Path(a.exe))
    mp = load_map() if MAP.exists() else None
    vft_names = {}
    meth_names = {}
    if mp:
        for c, lst in mp["classes"].items():
            for v in lst:
                vft_names[v["vftable"]] = c
                for i, mrva in enumerate(v["methods"]):
                    meth_names.setdefault(mrva, f"{c}::vf{i}")
    rva = int(a.addr, 16)
    if rva >= img.base:
        rva -= img.base
    body = img.disasm(rva, int(a.length, 16)) if a.length else img.function_body(rva, 0x8000)
    for ins in body:
        note = ""
        for t in img.rip_targets(ins):
            if t in vft_names:
                note = f"   ; vftable {vft_names[t]}"
            else:
                s = img.cstr(t, 120)
                if len(s) >= 4 and all(32 <= ord(c) < 127 for c in s):
                    note = f'   ; "{s}"'
                else:
                    sec = img.section_of(t)
                    note = f"   ; {img.base + t:#x} [{sec}]" + (f" = {struct.unpack('<f', img.read(t, 4))[0]:g}f / {img.u32(t):#x}" if sec and not any(x['name'] == sec and x['exec'] for x in img.secs) else "")
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16) - img.base
            if t in meth_names:
                note = f"   ; {meth_names[t]}"
        print(f"{ins.address - img.base:08x}  {ins.mnemonic:10} {ins.op_str}{note}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EXE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p = sub.add_parser("grep"); p.add_argument("pattern")
    p = sub.add_parser("class"); p.add_argument("name"); p.add_argument("--strings", action="store_true"); p.add_argument("--max", type=int, default=5)
    p = sub.add_parser("xrefs"); p.add_argument("addr")
    p = sub.add_parser("strings"); p.add_argument("addr"); p.add_argument("length", nargs="?")
    p = sub.add_parser("disasm"); p.add_argument("addr"); p.add_argument("length", nargs="?")
    a = ap.parse_args()
    return {"build": cmd_build, "grep": cmd_grep, "class": cmd_class, "xrefs": cmd_xrefs, "strings": cmd_strings,
            "disasm": cmd_disasm}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
