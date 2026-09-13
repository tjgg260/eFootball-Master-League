#!/usr/bin/env python3
"""
dt270_schema_gen.py — recover the dt270 constant-object schema from eFootball.exe.

Why this exists: the `.o` objects inside dt270's constant_*.bin carry NO field names. The game
binary does — every object type has a JSON loader (dev path, `DevelopData/.../*.json`) that
walks the keys by name, and a binary loader (release path) that copies the `.o` bytes into the
same C++ struct. This script finds both loaders for all object types and EMULATES them:

  1. JSON loader against a synthetic DOM  -> key path -> (struct offset, type)
  2. binary loader on the real `.o` bytes -> struct offset -> `.o` byte offset (+ pointer slots)

Joining the two gives a per-type template: names, types, record layouts, array strides and
which fields are u32 block pointers. The template is validated by a pure reader against EVERY
object in the installed pack, then written to tools/data/dt270_schema.json.

Run it again after each Konami patch (the structs change; the method doesn't):

    python tools/dt270_schema_gen.py                 # uses the installed exe + dt270
    python tools/dt270_schema_gen.py --exe X --cpk Y

Needs: capstone, unicorn (pip install capstone unicorn). Nothing here touches the game.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import mmap
import re
import struct
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
CPK = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk\dt270_console_all.cpk")
OUT = REPO / "tools" / "data" / "dt270_schema.json"
JSON_PREFIX = b"DevelopData/common/match/constant/"


# ----------------------------------------------------------------------------------------
# PE image
# ----------------------------------------------------------------------------------------

class Image:
    def __init__(self, path: Path):
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
            self.secs.append((s[:8].rstrip(b"\0").decode(), va, vsize, raw, rsize))
        self.size_of_image = max(va + vs for _, va, vs, _, _ in self.secs)
        import capstone
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True
        self.cs = capstone

    def rva2off(self, r: int):
        for _, va, vs, raw, rs in self.secs:
            if va <= r < va + vs:
                o = r - va
                return raw + o if o < rs else None
        return None

    def off2rva(self, o: int):
        for _, va, vs, raw, rs in self.secs:
            if raw <= o < raw + rs:
                return va + (o - raw)
        return None

    def read(self, rva: int, n: int) -> bytes:
        o = self.rva2off(rva)
        if o is None:
            return b"\0" * n
        b = self.m[o:o + n]
        return b + b"\0" * (n - len(b))

    def u64(self, rva): return struct.unpack("<Q", self.read(rva, 8))[0]
    def u32(self, rva): return struct.unpack("<I", self.read(rva, 4))[0]

    def cstr(self, rva: int) -> str:
        o = self.rva2off(rva)
        e = self.m.find(b"\0", o)
        return self.m[o:e].decode("latin1")

    def is_code(self, va: int) -> bool:
        r = va - self.base
        return 0 < r < self.size_of_image and self.rva2off(r) is not None

    def disasm(self, rva: int, n: int):
        return list(self.md.disasm(self.read(rva, n), self.base + rva))

    def lea_target(self, ins):
        """rva of a RIP-relative memory operand, or None."""
        for op in ins.operands:
            if op.type == self.cs.x86.X86_OP_MEM and op.mem.base == self.cs.x86.X86_REG_RIP:
                return op.mem.disp + ins.address + ins.size - self.base
        return None

    def function_body(self, rva: int, limit: int = 0x40000):
        """Linear sweep until two consecutive int3 (MSVC padding)."""
        out, run = [], 0
        for ins in self.md.disasm(self.read(rva, limit), self.base + rva):
            if ins.mnemonic == "int3":
                run += 1
                if run >= 2:
                    break
                continue
            run = 0
            out.append(ins)
        return out


# ----------------------------------------------------------------------------------------
# Locate: registration table -> types -> helper functions
# ----------------------------------------------------------------------------------------

def locate_types(img: Image) -> list[dict]:
    """{json path -> factory} pairs, then factory -> alloc size, vtable, loadJson, loadBin."""
    m = img.m
    paths = []
    for mt in re.finditer(re.escape(JSON_PREFIX) + rb"[A-Za-z0-9_/]+\.json\0", m):
        paths.append((mt.start(), mt.group()[:-1].decode()))
    if not paths:
        sys.exit("no DevelopData/common/match/constant paths in the exe — wrong binary?")
    entries = []
    for off, p in paths:
        va = img.base + img.off2rva(off)
        key = struct.pack("<Q", va)
        i = m.find(key)
        if i < 0:
            continue
        fn = struct.unpack_from("<Q", m, i + 8)[0]
        if img.is_code(fn):
            entries.append((p, fn - img.base))
    print(f"  registration table: {len(entries)} objects")

    def find_factory_vtable(fn):
        size, vts, f = None, [], fn
        for _ in range(3):
            nxt, prev = None, None
            for ins in img.disasm(f, 0x3000):
                if ins.mnemonic == "mov" and ins.op_str.startswith("ecx, 0x") and size is None:
                    size = int(ins.op_str.split(",")[1], 16)
                t = img.lea_target(ins) if ins.mnemonic == "lea" else None
                if t is not None and all(img.is_code(img.u64(t + 8 * k)) for k in range(3)):
                    vts.append(t)
                tail = ins.mnemonic == "jmp" and prev is not None and prev.mnemonic == "add" and "rsp" in prev.op_str
                ctor = ins.mnemonic == "call" and prev is not None and prev.op_str == "rcx, rax"
                if (tail or ctor) and ins.op_str.startswith("0x"):
                    nxt = int(ins.op_str, 16) - img.base
                    break
                if ins.mnemonic == "ret":
                    break
                prev = ins
            if nxt is None:
                break
            f = nxt
        if not vts:
            raise RuntimeError(f"no vtable found from factory {fn:#x}")
        return size, vts[-1]

    types: dict[int, dict] = {}
    for p, fn in entries:
        name = p.split("/")[-1][:-5]
        group = p.split("/")[-2]
        if fn not in types:
            size, vt = find_factory_vtable(fn)
            types[fn] = dict(factory=fn, size=size, vtable=vt, loadJson=img.u64(vt + 8) - img.base,
                             loadBin=img.u64(vt + 16) - img.base, group=group, members=[])
        types[fn]["members"].append(name)
    return list(types.values())


def locate_helpers(img: Image, types: list[dict]) -> dict:
    """Identify the JsonCpp accessors + runtime helpers the loaders call, by shape."""
    calls_json = collections.Counter()
    calls_bin = collections.Counter()
    after_lea_str = collections.Counter()
    after_mov_edx = collections.Counter()
    cookie = None
    strassign = collections.Counter()
    for t in types:
        body = img.function_body(t["loadJson"])
        for i, ins in enumerate(body):
            if ins.mnemonic != "call" or not ins.op_str.startswith("0x"):
                continue
            tgt = int(ins.op_str, 16) - img.base
            calls_json[tgt] += 1
            prev = body[max(0, i - 3):i]
            if any(p.mnemonic == "lea" and p.op_str.startswith("rdx") and img.lea_target(p) is not None for p in prev):
                after_lea_str[tgt] += 1
            if any(p.mnemonic == "mov" and p.op_str.startswith("edx, ") and not p.op_str.startswith("edx, dword") for p in prev):
                after_mov_edx[tgt] += 1
            if any(p.mnemonic == "xor" and p.op_str == "rcx, rsp" for p in body[max(0, i - 6):i]):
                cookie = tgt
            # std::string::assign(ptr, len): preceded by a strlen loop `cmp byte ptr [rax + r8], 0`
            if any(p.mnemonic == "lea" and p.op_str.startswith("rcx, [r") for p in prev) and \
               any(b.mnemonic == "cmp" and "byte ptr [rax" in b.op_str for b in body[max(0, i - 12):i]):
                strassign[tgt] += 1
        for ins in img.function_body(t["loadBin"]):
            if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
                calls_bin[int(ins.op_str, 16) - img.base] += 1

    def body_has(rva, mnems, n=0x100):
        ms = {i.mnemonic for i in img.disasm(rva, n)}
        return all(x in ms for x in mnems)

    get = after_lea_str.most_common(1)[0][0]
    at = next(t for t, _ in after_mov_edx.most_common() if t != get)
    switchers = [t for t in calls_json if img.read(t, 2) == b"\x48\x0f" or img.disasm(t, 8)[0].mnemonic == "movsx"]
    as_double = next(t for t in switchers if body_has(t, ["cvtsi2sd"]))
    as_int = next(t for t in switchers if body_has(t, ["cvttsd2si"]))
    as_bool = next(t for t in switchers if body_has(t, ["ucomisd"]) and not body_has(t, ["cvttsd2si"]))
    as_cstr = next(t for t in calls_json
                   if [i.mnemonic for i in img.disasm(t, 8)][:2] == ["mov", "ret"] and "[rcx]" in img.disasm(t, 8)[0].op_str)
    resolve = calls_bin.most_common(1)[0][0]
    assert img.disasm(resolve, 8)[0].mnemonic == "test", "resolve() shape changed"
    h = dict(get=get, at=at, asDouble=as_double, asInt=as_int, asBool=as_bool, asCString=as_cstr,
             strAssign=strassign.most_common(1)[0][0], resolve=resolve, cookie=cookie)
    for k, v in h.items():
        print(f"  helper {k:10} {v:#x}" if v else f"  helper {k:10} (not used by these loaders)")
    return h


# ----------------------------------------------------------------------------------------
# Emulation
# ----------------------------------------------------------------------------------------

STRUCT, STRUCT_SZ = 0x10000000, 0x200000
NODES, NODES_SZ = 0x20000000, 0x400000
HEAP, HEAP_SZ = 0x30000000, 0x1000000
STACK, STACK_SZ = 0x40000000, 0x100000
OBIN, OBIN_SZ = 0x50000000, 0x200000
STRBUF, STRBUF_SZ = 0x60000000, 0x100000
RET_MAGIC = 0x7FFF0000


class Emu:
    def __init__(self, img: Image, helpers: dict):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ, \
            UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED
        from unicorn import x86_const as X
        self.X = X
        self.img, self.h = img, helpers
        uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.uc = uc
        self.mapped = set()
        for base, sz in [(STRUCT, STRUCT_SZ), (NODES, NODES_SZ), (HEAP, HEAP_SZ), (STACK, STACK_SZ),
                         (OBIN, OBIN_SZ), (STRBUF, STRBUF_SZ), (RET_MAGIC, 0x1000)]:
            uc.mem_map(base, sz)
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, self._unmapped)
        self.hooks = {}
        uc.hook_add(UC_HOOK_CODE, self._code, begin=img.base, end=img.base + img.size_of_image)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._write, begin=STRUCT, end=STRUCT + STRUCT_SZ)
        uc.hook_add(UC_HOOK_MEM_READ, self._read_o, begin=OBIN, end=OBIN + OBIN_SZ)
        self.heap = HEAP
        self.hooks[helpers["strAssign"]] = self.h_strassign
        if helpers.get("cookie"):
            self.hooks[helpers["cookie"]] = self.h_nop

    def _unmapped(self, uc, access, addr, size, value, ud):
        img = self.img
        if img.base <= addr < img.base + img.size_of_image:
            base = addr & ~0xFFFF
            for b in (base - 0x10000, base, base + 0x10000):
                if b in self.mapped or b < img.base:
                    continue
                uc.mem_map(b, 0x10000)
                uc.mem_write(b, b"".join(img.read(b - img.base + k * 0x1000, 0x1000) for k in range(16)))
                self.mapped.add(b)
            return True
        raise RuntimeError(f"unmapped access at {addr:#x} rip={uc.reg_read(self.X.UC_X86_REG_RIP) - img.base:#x}")

    def _code(self, uc, addr, size, ud):
        h = self.hooks.get(addr - self.img.base)
        if h is not None:
            h(uc)

    def ret(self, uc, rax=None):
        X = self.X
        rsp = uc.reg_read(X.UC_X86_REG_RSP)
        ra = struct.unpack("<Q", uc.mem_read(rsp, 8))[0]
        uc.reg_write(X.UC_X86_REG_RSP, rsp + 8)
        if rax is not None:
            uc.reg_write(X.UC_X86_REG_RAX, rax)
        uc.reg_write(X.UC_X86_REG_RIP, ra)

    def h_nop(self, uc): self.ret(uc)
    def h_strassign(self, uc): self.ret(uc, uc.reg_read(self.X.UC_X86_REG_RCX))
    def _write(self, uc, access, addr, size, value, ud): self.on_write(addr - STRUCT, size, value)
    def _read_o(self, uc, access, addr, size, value, ud): self.on_read_o(addr - OBIN, size, value)
    def on_write(self, off, size, value): pass
    def on_read_o(self, off, size, value): pass

    def run(self, fn, rcx, rdx):
        X, uc = self.X, self.uc
        rsp = STACK + STACK_SZ - 0x1000
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, rcx)
        uc.reg_write(X.UC_X86_REG_RDX, rdx)
        uc.emu_start(self.img.base + fn, RET_MAGIC, count=0)


class JsonEmu(Emu):
    """loadJson against a synthetic DOM: every accessor returns a sentinel; struct writes of a
    sentinel bind (key path -> struct offset, type)."""

    def __init__(self, img, helpers):
        super().__init__(img, helpers)
        self.nodes, self.nid = {}, 0
        self.pending_bool, self.pending_int = [], []
        self.float_sent, self.int_sent, self.strings = {}, {}, {}
        self.fields = {}
        h = helpers
        self.hooks.update({h["get"]: self.h_get, h["at"]: self.h_at, h["asDouble"]: self.h_asdouble,
                           h["asBool"]: self.h_asbool, h["asInt"]: self.h_asint, h["asCString"]: self.h_ascstr,
                           h["strAssign"]: self.h_strassign})

    def newnode(self, path):
        self.nid += 1
        a = NODES + self.nid * 16
        self.uc.mem_write(a, struct.pack("<QB", 0, 7) + b"\0" * 7)
        self.nodes[a] = path
        return a

    def _key(self, a):
        img = self.img
        if img.base <= a < img.base + img.size_of_image:
            return img.cstr(a - img.base)
        out = b""
        while True:
            c = self.uc.mem_read(a, 1)
            if c == b"\0":
                return out.decode("latin1")
            out += c
            a += 1

    def h_get(self, uc):
        X = self.X
        n = uc.reg_read(X.UC_X86_REG_RCX)
        self.ret(uc, self.newnode(self.nodes.get(n, ("?",)) + (self._key(uc.reg_read(X.UC_X86_REG_RDX)),)))

    def h_at(self, uc):
        X = self.X
        n = uc.reg_read(X.UC_X86_REG_RCX)
        self.ret(uc, self.newnode(self.nodes.get(n, ("?",)) + (uc.reg_read(X.UC_X86_REG_EDX),)))

    def h_asdouble(self, uc):
        path = self.nodes.get(uc.reg_read(self.X.UC_X86_REG_RCX))
        self.nid += 1
        v = 1000000.0 + self.nid
        self.float_sent[struct.unpack("<I", struct.pack("<f", v))[0]] = path
        self.float_sent[("d", struct.unpack("<Q", struct.pack("<d", v))[0])] = path
        uc.reg_write(self.X.UC_X86_REG_XMM0, struct.unpack("<Q", struct.pack("<d", v))[0])
        self.ret(uc)

    def h_asint(self, uc):
        path = self.nodes.get(uc.reg_read(self.X.UC_X86_REG_RCX))
        self.nid += 1
        v = 0x7000000 + self.nid
        self.int_sent[v] = path
        self.pending_int.append((v, path))
        self.ret(uc, v)

    def h_asbool(self, uc):
        self.pending_bool.append(self.nodes.get(uc.reg_read(self.X.UC_X86_REG_RCX)))
        self.ret(uc, 1)

    def h_ascstr(self, uc):
        path = self.nodes.get(uc.reg_read(self.X.UC_X86_REG_RCX))
        self.nid += 1
        a = STRBUF + self.nid * 16
        uc.mem_write(a, b"S%d\0" % self.nid)
        self.strings[a] = path
        self.ret(uc, a)

    def h_strassign(self, uc):
        X = self.X
        dst, src = uc.reg_read(X.UC_X86_REG_RCX), uc.reg_read(X.UC_X86_REG_RDX)
        path = self.strings.get(src)
        if path is not None and STRUCT <= dst < STRUCT + STRUCT_SZ:
            self.fields[path] = dict(off=dst - STRUCT, type="string", size=32)
        self.ret(uc, dst)

    def on_write(self, off, size, value):
        if size == 4:
            p = self.float_sent.get(value)
            if p is not None:
                self.fields[p] = dict(off=off, type="float", size=4); return
            p = self.int_sent.get(value)
            if p is not None:
                self.fields[p] = dict(off=off, type="int", size=4); return
        elif size == 8:
            p = self.float_sent.get(("d", value))
            if p is not None:
                self.fields[p] = dict(off=off, type="double", size=8); return
            p = self.int_sent.get(value)
            if p is not None:
                self.fields[p] = dict(off=off, type="int64", size=8); return
        elif size == 1:
            if self.pending_int and value == (self.pending_int[-1][0] & 0xFF):
                _, p = self.pending_int.pop()
                self.fields[p] = dict(off=off, type="int8", size=1); return
            if value == 1 and self.pending_bool:
                p = self.pending_bool.pop(0)
                self.fields[p] = dict(off=off, type="bool", size=1); return
        elif size == 2:
            if self.pending_int and value == (self.pending_int[-1][0] & 0xFFFF):
                _, p = self.pending_int.pop()
                self.fields[p] = dict(off=off, type="int16", size=2); return


class BinEmu(Emu):
    """loadBin on real .o bytes: record resolve() calls (pointer slots), struct writes with the
    .o offset they were read from, and string assigns."""

    def __init__(self, img, helpers, obytes):
        super().__init__(img, helpers)
        self.uc.mem_write(OBIN, obytes)
        self.last_read = None
        self.events = []
        self.hooks[helpers["resolve"]] = self.h_resolve

    def h_resolve(self, uc):
        X = self.X
        off = uc.reg_read(X.UC_X86_REG_ECX)
        self.events.append(("resolve", self.last_read[0] if self.last_read else None, off))
        base = uc.reg_read(X.UC_X86_REG_RDX)
        self.ret(uc, base + off if off else 0)

    def on_read_o(self, off, size, value): self.last_read = (off, size, value)

    def on_write(self, off, size, value):
        lr = self.last_read
        self.events.append(("write", off, lr[0] if lr and lr[1] >= size else None, size))

    def h_strassign(self, uc):
        X = self.X
        dst, src = uc.reg_read(X.UC_X86_REG_RCX), uc.reg_read(X.UC_X86_REG_RDX)
        if STRUCT <= dst < STRUCT + STRUCT_SZ:
            self.events.append(("str", dst - STRUCT, src - OBIN if OBIN <= src < OBIN + OBIN_SZ else None))
        self.ret(uc, dst)


# ----------------------------------------------------------------------------------------
# Measure + template
# ----------------------------------------------------------------------------------------

def measure(img, helpers, t, obytes):
    je = JsonEmu(img, helpers)
    je.run(t["loadJson"], STRUCT, je.newnode(()))
    be = BinEmu(img, helpers, obytes)
    be.run(t["loadBin"], STRUCT, OBIN)
    by_struct = {fd["off"]: (p, fd["type"]) for p, fd in je.fields.items()}
    leaf, ptr, chain, inline, stray = {}, {}, [], set(), []
    for ev in be.events:
        if ev[0] == "resolve":
            chain.append((ev[1], ev[2]))
            continue
        if ev[0] == "write":
            _, soff, ooff, _size = ev
            if soff not in by_struct:
                continue
            path, _ = by_struct[soff]
            leaf[path] = ooff
        else:
            _, soff, _src = ev
            if soff not in by_struct:
                continue
            path, _ = by_struct[soff]
            if chain:
                slot, target = chain.pop()          # the last resolve is the string's own pointer
                ptr[path] = (slot, target)
                leaf[path] = slot
            else:
                leaf[path] = None
        # remaining resolves descend the path: assign to the outermost unassigned ancestors
        anc = [path[:i] for i in range(1, len(path))]
        todo = [a for a in anc if a not in ptr and a not in inline and not isinstance(a[-1], int)]
        k = 0
        for slot, target in chain:
            while k < len(todo) and todo[k] in ptr:
                k += 1
            if k >= len(todo):
                stray.append((slot, target, path))
                break
            ptr[todo[k]] = (slot, target)
            k += 1
        for a in anc:
            if a not in ptr:
                inline.add(a)
        chain = []
    return je, leaf, ptr, stray


def build_template(je, leaf, ptr):
    kinds = {p: fd["type"] for p, fd in je.fields.items()}
    nodes = {(): "record"}
    for p in kinds:
        for i in range(1, len(p)):
            nodes.setdefault(p[:i], "array" if isinstance(p[i], int) else "record")
    childmap: dict[tuple, set] = {}
    for p in list(kinds) + list(nodes):
        if p:
            childmap.setdefault(p[:-1], set()).add(p)

    def children(a):
        return sorted(childmap.get(a, ()), key=lambda c: (0, c[-1]) if isinstance(c[-1], int) else (1, c[-1]))

    base = {(): 0}

    def node_base(a):
        if a in base:
            return base[a]
        if a in ptr:
            base[a] = ptr[a][1]
        else:
            items = []
            for c in children(a):
                if c in kinds:
                    items.append(leaf[c] if leaf.get(c) is not None else 10 ** 9)
                elif c in ptr:
                    items.append(ptr[c][0])
                else:
                    items.append(node_base(c))
            base[a] = min(items) if items else 10 ** 9
        return base[a]

    def tmpl(a):
        k = nodes.get(a) or kinds[a]
        b = node_base(a)
        if k == "record":
            fields = []
            for c in children(a):
                ck = nodes.get(c) or kinds[c]
                if c in kinds:
                    off = leaf[c]
                    f = {"name": c[-1], "kind": ck, "off": None if off is None else off - b}
                    if ck == "string":
                        f["ptr"] = True
                    fields.append(f)
                else:
                    sub = tmpl(c)
                    sub["name"] = c[-1]
                    if c in ptr:
                        sub["ptr"] = True
                        sub["off"] = ptr[c][0] - b
                    else:
                        sub["off"] = node_base(c) - b
                    fields.append(sub)
            fields.sort(key=lambda f: f["off"] if f["off"] is not None else 10 ** 9)
            return {"kind": "record", "fields": fields}
        if k == "array":
            ch = children(a)
            elems = []
            for c in ch:
                if c in kinds:
                    elems.append(({"kind": kinds[c]} | ({"ptr": True} if kinds[c] == "string" else {}), leaf[c]))
                else:
                    elems.append((tmpl(c), node_base(c)))
            e0, b0 = elems[0]
            stride = (elems[1][1] - b0) if len(elems) > 1 else None
            sig = json.dumps(e0, sort_keys=True)
            for i, (e, bb) in enumerate(elems):
                if json.dumps(e, sort_keys=True) != sig:
                    raise RuntimeError(f"heterogeneous array at {a}")
                if stride is not None and bb != b0 + i * stride:
                    raise RuntimeError(f"irregular stride at {a}")
            return {"kind": "array", "count": len(elems), "stride": stride, "elem": e0}
        return {"kind": k}

    return tmpl(())


# ----------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--cpk", default=str(CPK))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    from dt270_objects import Pack, Schema, load_game_packs   # noqa: E402
    t0 = time.time()
    img = Image(Path(a.exe))
    print(f"exe: {a.exe} ({Path(a.exe).stat().st_size:,} B, {len(img.secs)} sections)")
    types = locate_types(img)
    print(f"  {len(types)} object types")
    helpers = locate_helpers(img, types)

    # objects from the installed pack (schema-less Pack parse)
    sys.path.insert(0, str(REPO / "tools"))
    import cpk_patch                                    # noqa: E402
    from dt270_constants import decode_constant         # noqa: E402
    c = cpk_patch.load(a.cpk)
    objects: dict[str, bytes] = {}
    for f in c.files:
        name = f.path.split("/")[-1]
        if name.startswith("constant_") and name.endswith(".bin"):
            pack = Pack(decode_constant(c.read(f.path)))
            for n in pack.names():
                objects[n] = pack.object_bytes(n)
    print(f"  {len(objects)} objects in {a.cpk}")

    out_types = {}
    problems = 0
    for t in types:
        members = [m for m in t["members"] if m in objects]
        if not members:
            print(f"  {t['members'][0]}: no object in pack, skipped")
            continue
        rep = members[0]
        je, leaf, ptr, stray = measure(img, helpers, t, objects[rep])
        if stray:
            print(f"  {rep}: {len(stray)} stray pointer resolves (layout heuristic failed)")
            problems += 1
        template = build_template(je, leaf, ptr)
        # validate every member: pure reader offsets == emulated offsets
        from dt270_objects import ObjectView
        for m in members:
            lf_emu = leaf if m == rep else measure(img, helpers, t, objects[m])[1]
            view = ObjectView(m, bytearray(objects[m]), 0, len(objects[m]), template)
            got = {lf.path: lf.off for lf in view.leaves() if lf.writable}
            declined = {lf.path for lf in view.leaves() if not lf.writable}
            def is_declined(p):
                return any(p[:i] in declined for i in range(1, len(p) + 1))
            mism = [(p, got.get(p), o) for p, o in lf_emu.items()
                    if o is not None and not is_declined(p) and got.get(p) != o]
            extra = [p for p in got if p not in lf_emu]
            if mism or extra:
                problems += 1
                print(f"  MISMATCH {m}: {len(mism)} leaves differ, {len(extra)} unexpected, e.g. {mism[:3]}{extra[:3]}")
            elif declined:
                print(f"  note {m}: {len(declined)} leaves past the emitted data (loader reads garbage there; kept read-only)")
        out_types[t["members"][0]] = dict(members=t["members"], group=t["group"], struct_size=t["size"],
                                          template=template)
        nleaf = len(je.fields)
        print(f"  {t['members'][0]:28} {len(members):3} objects  {nleaf:6} fields  ok")

    meta = dict(generated=str(date.today()), exe=str(a.exe), exe_size=Path(a.exe).stat().st_size,
                exe_sha1=hashlib.sha1(img.m[:0x2000000]).hexdigest(), cpk=str(a.cpk),
                helpers={k: f"{v:#x}" for k, v in helpers.items() if v},
                note="exe_sha1 covers the first 32 MB only")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"meta": meta, "types": out_types}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {a.out} ({Path(a.out).stat().st_size:,} B) in {time.time() - t0:.1f}s; problems: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
