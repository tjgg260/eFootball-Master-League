#!/usr/bin/env python3
"""
dt270_liveness.py - which dt270 gameplay fields does eFootball.exe actually read?

Every dt270 constant object is created by ConstantManager (singleton pointer in a global) and
handed out by get(mgr, idx). Consumers do

    mov rcx,[rip -> ConstantManager]; mov edx,IDX; call get      ; rax = object
    movss xmm0,[rax+0x38]                                        ; trap.ballControlRate

This tool finds every such consumer statically and classifies EVERY field of EVERY object:

  1. runtime struct offsets  - the game's own JSON loaders are emulated (JsonEmu from
     dt270_schema_gen.py) -> key path -> RUNTIME struct offset/size/kind. Written to
     tools/data/dt270_struct_offsets.json. (dt270_schema.json 'off' values are .o FILE offsets and
     are NOT usable for this.)
  2. consumer scan - every call/jmp to get() and to its forwarding wrappers; the idx constant
     is recovered by dataflow (never guessed; unknown-idx sites are listed separately); the
     returned pointer is tracked through the enclosing function with a may-dataflow over the
     CFG (register copies, stack spills/reloads, lea/add derived pointers, scaled indices,
     survival across calls only in non-volatile registers).
  3. interprocedural - (a) a pointer handed to a DIRECT callee in rcx/rdx/r8/r9 or in a stack
     argument slot written since the previous call is followed into that callee (depth
     MAX_DEPTH, memoised per (callee, seeds), cycle-safe); (b) functions that return the pointer
     become get-like themselves; (c) CONTEXT OBJECTS: when a function stores the pointer into a
     struct it was handed ([arg+K] = ptr), the store is summarised and applied at every direct
     call site onto the caller's own frame struct / argument object, and a struct known to hold
     the pointer is followed into the direct callees it is passed to, where [arg+K] reloads the
     pointer. That is real dataflow (example: basePosition is stored at ctx+0xf0 by
     0x143ddb220, ctx lives on 0x143ddb8f0's stack, and 0x143e86b00 reads minWidth through
     [ctx+0xf0] four calls down); (d) pointers parked in a global make every function that
     references the global a consumer.
  4. cached pointers (heuristic, step B) - pointers stored through an UNTRACKED base (heap /
     member objects reached some other way) are only matched by offset: a second pass finds
     functions that reload [reg+K] and then read [thatReg+disp]. K collisions are possible, so a
     function is only accepted when EVERY read through the reloaded pointer lands exactly on a
     field of the right width/kind; such fields get status 'cached'.

SEMANTICS - read these before trusting a status:
  'read'      an instruction reads the field through a pointer that provably came from
              get(idx) (mechanisms 2-3). It does NOT prove the value affects gameplay - a load
              can be dead (example: basePosition.forceDashDistDefence is loaded at 0x143da9420
              and overwritten before use; 'read' is correct by this definition). Each reader
              carries 'via' (get / ret / ...>[obj+K] = reloaded from a context object) and a
              confidence.
  'cached'    only reached through mechanism 4 (or a global). Offset collisions are possible:
              medium confidence, the evidence instructions are listed.
  'unread'    the object WAS located, its pointer flow was followed, and no reader was found.
              How far to trust it is per object: unread_confidence 'high' = nothing escaped;
              'reduced' = n_escapes_unfollowed / n_pointer_stores_unfollowed > 0 (a reader may
              hide behind an indirect call or an untracked store). A field can additionally
              carry candidate_readers: an unknown-idx get() site whose access pattern fits this
              struct type reads the same offset - unproven, but a reason not to call it inert.
  'unlocated' NO get() site / pointer source was found for the object at all (its idx is
              computed at runtime from game data, or it is never fetched). This says NOTHING
              about liveness. 140 of 245 objects are in this state; candidate_readers give
              struct-fingerprint leads only.
  Indexed reads ([ptr+idx*scale+disp]) are attributed to the array whose byte range / stride
  contains them; array fields are reported once per array ("name[]"), with the element index
  when it is a constant.

Static analysis of this binary has been confidently wrong before. Nothing here executes game
code paths; indirect calls, virtual dispatch and pointers parked in heap objects are blind
spots and are counted, not hidden.

    python tools/dt270_liveness.py build            # -> build/dt270_liveness.json (+ struct offsets)
    python tools/dt270_liveness.py show trap        # compact per-field table
    python tools/dt270_liveness.py show trap -v     # with every reader instruction
    python tools/dt270_liveness.py sites shoot      # get() sites / escapes / cache stores
    python tools/dt270_liveness.py verify           # acceptance tests (hand-proven ground truth)

Read-only on the exe. Needs capstone, unicorn, numpy.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from dt270_schema_gen import EXE, STRUCT, Image, JsonEmu, locate_helpers, locate_types  # noqa: E402

OUT_LIVENESS = REPO / "build" / "dt270_liveness.json"
OUT_OFFSETS = REPO / "tools" / "data" / "dt270_struct_offsets.json"
EXE_MAP = REPO / "build" / "exe_map.json"

# Verified addresses (docs/exe-gameplay-map.md). Shapes are re-checked at start-up.
VA_MANAGER_GLOBAL = 0x148C22B98
VA_GET = 0x145348D70
VA_WRAPPER = 0x145349560
VA_CREATE = 0x145349AB0
KNOWN_IDX = {"ball": 0x4D, "modeMatchup": 0x50, "passget": 0x6C, "shoot": 0x6D, "throughpass": 0x6E,
             "trap": 0x6F, "basePosition": 0xE2}

MAX_FN_INSNS = 60000
MAX_DEPTH = 12               # direct-call depth a tracked pointer / pointer-holding object is followed
OBJ_WINDOW = 0x2000         # bytes above a passed frame address that are treated as "the object"
MAX_K_FUNCS = 6000          # per cached K: more candidate functions than this -> not scanned


# ----------------------------------------------------------------------------------------
# 1. runtime struct layouts
# ----------------------------------------------------------------------------------------

def pstr(path) -> str:
    out = ""
    for p in path:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += ("." if out else "") + p
    return out


def cstr(path) -> str:
    """collapsed name: array indices dropped -> 'RouteParameter[].acc'."""
    out = ""
    for p in path:
        if isinstance(p, int):
            out += "[]"
        else:
            out += ("." if out else "") + p
    return out


class Layout:
    """Runtime struct of one object type: leaves + arrays, offset lookup."""

    def __init__(self, name: str, size: int, fields: dict):
        self.name, self.size = name, size
        self.leaves = sorted(((fd["off"], fd["size"], fd["type"], p) for p, fd in fields.items()),
                             key=lambda x: x[0])
        self.starts = [l[0] for l in self.leaves]
        # arrays: prefix path -> element min offsets
        elems = defaultdict(dict)
        for off, size_, _k, p in self.leaves:
            for i, part in enumerate(p):
                if isinstance(part, int):
                    d = elems[p[:i]]
                    d[part] = min(d.get(part, 1 << 60), off)
        ends = defaultdict(int)
        for off, size_, _k, p in self.leaves:
            for i, part in enumerate(p):
                if isinstance(part, int):
                    ends[p[:i + 1]] = max(ends[p[:i + 1]], off + size_)
        self.arrays = {}
        for ap, d in elems.items():
            n = max(d) + 1
            base = d[0]
            if n > 1:
                stride = d[1] - d[0]
            else:
                stride = ends[ap + (0,)] - base
            self.arrays[ap] = dict(base=base, stride=stride, count=n)
        # collapsed fields
        self.fields = {}
        for off, size_, kind, p in self.leaves:
            c = cstr(p)
            f = self.fields.get(c)
            if f is None:
                dims = []
                for i, part in enumerate(p):
                    if isinstance(part, int):
                        a = self.arrays[p[:i]]
                        dims.append(dict(stride=a["stride"], count=a["count"]))
                self.fields[c] = dict(path=c, soff=off, size=size_, kind=kind, dims=dims, n_leaves=1)
            else:
                f["n_leaves"] += 1
                f["soff"] = min(f["soff"], off)

    def leaf_at(self, off: int):
        i = bisect.bisect_right(self.starts, off) - 1
        if i < 0:
            return None
        l = self.leaves[i]
        return l if l[0] <= off < l[0] + l[1] else None

    def leaves_in(self, lo: int, hi: int):
        i = max(0, bisect.bisect_right(self.starts, lo) - 1)
        out = []
        while i < len(self.leaves) and self.leaves[i][0] < hi:
            l = self.leaves[i]
            if l[0] + l[1] > lo:
                out.append(l)
            i += 1
        return out

    def enclosing_arrays(self, path):
        return [self.arrays[path[:i]] | {"path": path[:i]} for i, part in enumerate(path) if isinstance(part, int)]

    def to_json(self):
        arrays = [dict(path=cstr(ap), base=a["base"], stride=a["stride"], count=a["count"])
                  for ap, a in sorted(self.arrays.items(), key=lambda kv: kv[1]["base"])]
        return dict(struct_size=self.size, n_leaves=len(self.leaves),
                    fields=sorted(self.fields.values(), key=lambda f: f["soff"]),
                    arrays=arrays,
                    leaves=[[pstr(p), off, size_, kind] for off, size_, kind, p in self.leaves])


def build_layouts(img: Image, types: list[dict], helpers: dict) -> dict[str, Layout]:
    out = {}
    for t in types:
        je = JsonEmu(img, helpers)
        je.run(t["loadJson"], STRUCT, je.newnode(()))
        out[t["members"][0]] = Layout(t["members"][0], t["size"] or 0, je.fields)
    return out


def registration_table(img: Image, types: list[dict]):
    """idx -> (object name, type name). The table address is read out of the create path."""
    body = img.disasm(VA_CREATE - img.base, 0x80)
    lookup = None
    for i, ins in enumerate(body):
        if ins.mnemonic == "call" and i and body[i - 1].mnemonic == "mov" and body[i - 1].op_str.startswith("ecx,"):
            lookup = int(ins.op_str, 16)
    if lookup is None:
        raise RuntimeError("create path shape changed: no table lookup call found")
    table = count = None
    for ins in img.disasm(lookup - img.base, 0x30):
        if ins.mnemonic == "cmp" and count is None:
            count = ins.operands[1].imm
        if ins.mnemonic == "lea":
            table = img.lea_target(ins)
    if table is None or count is None:
        raise RuntimeError("registration lookup shape changed")
    by_factory = {t["factory"]: t for t in types}
    reg = {}
    for idx in range(count):
        p, fn = img.u64(table + 16 * idx), img.u64(table + 16 * idx + 8)
        path = img.cstr(p - img.base) if img.is_code(p) else ""
        name = path.split("/")[-1][:-5] if path.endswith(".json") else f"#{idx}"
        t = by_factory.get(fn - img.base)
        reg[idx] = dict(name=name, json=path, type=t["members"][0] if t else None, factory=fn)
    return reg, table + img.base, count


# ----------------------------------------------------------------------------------------
# function table (.pdata, chained chunks merged) + call index
# ----------------------------------------------------------------------------------------

class Funcs:
    def __init__(self, img: Image):
        import numpy as np
        self.img = img
        d = img.m[:0x1000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        rva, sz = struct.unpack_from("<II", d, pe + 24 + 112 + 8 * 3)
        o = img.rva2off(rva)
        a = np.frombuffer(img.m[o:o + sz - sz % 12], dtype="<u4").reshape(-1, 3)
        a = a[a[:, 0] != 0]
        self.begin = a[:, 0].tolist()
        self.end = a[:, 1].tolist()
        self.unw = a[:, 2].tolist()
        self._root = {}
        self._chunks = None

    def index_of(self, rva: int):
        i = bisect.bisect_right(self.begin, rva) - 1
        if i >= 0 and self.begin[i] <= rva < self.end[i]:
            return i
        return None

    def root(self, i: int) -> int:
        r = self._root.get(i)
        if r is not None:
            return r
        img, j = self.img, i
        for _ in range(16):
            uo = img.rva2off(self.unw[j])
            if uo is None:
                break
            if not ((img.m[uo] >> 3) & 4):
                break
            n = (img.m[uo + 2] + 1) & ~1
            b = struct.unpack_from("<I", img.m, uo + 4 + 2 * n)[0]
            k = bisect.bisect_left(self.begin, b)
            if k >= len(self.begin) or self.begin[k] != b or k == j:
                break
            j = k
        self._root[i] = j
        return j

    def function_of(self, rva: int):
        """(root rva, [(begin, end), ...]) of the function containing rva, chained chunks merged."""
        i = self.index_of(rva)
        if i is None:
            return None
        r = self.root(i)
        chunks = {r, i}
        # chained chunks are almost always adjacent: walk both directions while roots match
        for step in (1, -1):
            j, miss = r + step, 0
            while 0 <= j < len(self.begin) and miss < 3:
                if self.root(j) == r:
                    chunks.add(j)
                    miss = 0
                else:
                    miss += 1
                j += step
        return self.begin[r], sorted((self.begin[c], self.end[c]) for c in chunks)


def import_slots(img: Image) -> dict[int, str]:
    """IAT slot rva -> 'dll!name' from the PE import directory. A 'call [rip+slot]' through one of
    these leaves the image (OS / CRT / Steam code), which cannot interpret a dt270 struct."""
    out = {}
    try:
        d = img.m[:0x1000]
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        rva, _sz = struct.unpack_from("<II", d, pe + 24 + 112 + 8)
        o = img.rva2off(rva)
        while o is not None:
            oft, _ts, _fc, name, ft = struct.unpack_from("<IIIII", img.m, o)
            if not name and not ft:
                break
            no = img.rva2off(name)
            dll = bytes(img.m[no:no + 64]).split(b"\0")[0].decode("latin1") if no is not None else "?"
            to = img.rva2off(oft or ft)
            k = 0
            while to is not None:
                v = struct.unpack_from("<Q", img.m, to + 8 * k)[0]
                if not v:
                    break
                fn = f"#{v & 0xFFFF}"
                if not v >> 63:
                    fo = img.rva2off(v & 0x7FFFFFFF)
                    if fo is not None:
                        fn = bytes(img.m[fo + 2:fo + 66]).split(b"\0")[0].decode("latin1")
                out[ft + 8 * k] = f"{dll}!{fn}"
                k += 1
            o += 20
    except Exception as ex:                               # reporting aid only
        print(f"  (import directory not parsed: {ex})")
    return out


class CallIndex:
    """All rel32 call/jmp (E8/E9) in .xcode, for 'who calls X'."""

    def __init__(self, img: Image):
        import numpy as np
        self.np = np
        sec = next(s for s in img.secs if s[0] == ".xcode")
        _, va, vs, raw, rs = sec
        self.va, self.raw, self.n = va, raw, min(vs, rs)
        buf = np.frombuffer(img.m, dtype=np.uint8, count=self.n, offset=raw)
        self.buf = buf
        pos = np.flatnonzero((buf[:-5] == 0xE8) | (buf[:-5] == 0xE9)).astype(np.int64)
        rel = (buf[pos + 1].astype(np.int64) | (buf[pos + 2].astype(np.int64) << 8) |
               (buf[pos + 3].astype(np.int64) << 16) | (buf[pos + 4].astype(np.int64) << 24))
        rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
        tgt = pos + 5 + rel
        ok = (tgt >= 0) & (tgt < self.n)
        self.pos, self.tgt = pos[ok], tgt[ok]
        order = np.argsort(self.tgt, kind="stable")
        self.pos, self.tgt = self.pos[order], self.tgt[order]

    def callers(self, rva: int) -> list[int]:
        np = self.np
        t = rva - self.va
        lo, hi = np.searchsorted(self.tgt, t, "left"), np.searchsorted(self.tgt, t, "right")
        return [int(p) + self.va for p in self.pos[lo:hi]]

    def rip_refs(self, target_rva: int) -> list[int]:
        """rva of every disp32 field in .xcode that RIP-resolves to target_rva (instruction-agnostic)."""
        np = self.np
        out = []
        for k in range(4):
            n4 = (self.n - k) // 4
            v = np.frombuffer(self.img_bytes(k, n4 * 4), dtype="<i4").astype(np.int64)
            p = self.va + k + 4 * np.arange(n4, dtype=np.int64)
            hit = np.flatnonzero(v + p + 4 == target_rva)
            out += [int(p[h]) for h in hit]
        return sorted(out)

    def img_bytes(self, k, n):
        return self.buf[k:k + n].tobytes()


# ----------------------------------------------------------------------------------------
# dataflow
# ----------------------------------------------------------------------------------------

_R64 = ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi"]
REGMAP: dict[str, tuple[str, int]] = {}
for _r in _R64:
    s = _r[1:]
    REGMAP[_r] = (_r, 8)
    REGMAP["e" + s] = (_r, 4)
    REGMAP[s] = (_r, 2)
for _a, _l, _h in (("rax", "al", "ah"), ("rcx", "cl", "ch"), ("rdx", "dl", "dh"), ("rbx", "bl", "bh")):
    REGMAP[_l] = (_a, 1)
    REGMAP[_h] = (_a, 1)
for _a, _l in (("rsi", "sil"), ("rdi", "dil"), ("rbp", "bpl"), ("rsp", "spl")):
    REGMAP[_l] = (_a, 1)
for _i in range(8, 16):
    REGMAP[f"r{_i}"] = (f"r{_i}", 8)
    REGMAP[f"r{_i}d"] = (f"r{_i}", 4)
    REGMAP[f"r{_i}w"] = (f"r{_i}", 2)
    REGMAP[f"r{_i}b"] = (f"r{_i}", 1)
VOLATILE = ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11")
ARGREGS = ("rcx", "rdx", "r8", "r9")
EMPTY = frozenset()
COND_JUMPS = {"je", "jne", "jz", "jnz", "ja", "jae", "jb", "jbe", "jg", "jge", "jl", "jle", "js", "jns", "jo", "jno",
              "jp", "jnp", "jc", "jnc", "jcxz", "jecxz", "jrcxz", "loop", "loope", "loopne"}
SSE_FLOAT = {"movss", "addss", "subss", "mulss", "divss", "comiss", "ucomiss", "minss", "maxss", "sqrtss",
             "cvtss2sd", "cvtss2si", "cvttss2si", "movd", "shufps", "unpcklps", "movups", "movaps", "cmpss",
             "rsqrtss", "rcpss", "insertps", "vmovss", "cmpltss", "cmpless", "cmpeqss", "cmpneqss", "cmpnltss",
             "cmpnless", "andps", "andnps", "orps", "xorps", "mulps", "addps", "subps", "divps", "minps",
             "maxps", "movlps", "movhps", "movq", "movdqu", "movdqa", "cvtps2pd", "roundss"}


class Analyzer:
    """May-dataflow of ConstantManager object pointers through one function at a time.

    Atoms (values are frozensets of atoms):
      ('P', obj, off, strides, via)  pointer obj+off (+ n*stride for each stride); obj = idx int or
                                     ('?', site_va) for an unknown-idx get(); via = 'get' | 'ret' |
                                     'K:<hex>' | 'G:<hex>'
      ('C', v)                       integer constant
      ('S', k)                       unknown multiple of k (scaled index)
      ('F', d)                       frame address: entry-rsp + d
      ('A', reg)                     the function's own incoming argument register
      ('O', name, off)               address name+off inside an abstract OBJECT the function was handed by
                                     pointer (name = the argument it arrived in: 'rcx', ..., 'sa28').
                                     off None = somewhere inside (widened). State keys ('o', name, off)
                                     hold the tracked pointers stored in that object's fields.

    Objects are what carries a constant pointer through a context struct: a caller builds a struct
    on its stack, an init function stores get()'s result into struct+K, workers reload struct+K.
    Stores through an object pointer are summarised per function ('ostores') and mapped back onto
    the caller's own frame slots / objects at the call site, so this is real dataflow along DIRECT
    calls, not offset matching. Heap objects reached some other way stay untracked (counted).
    """

    def __init__(self, img: Image, funcs: Funcs, obj_size):
        import capstone
        self.cs = capstone
        self.X = capstone.x86
        self.img, self.funcs = img, funcs
        self.obj_size = obj_size                      # obj -> struct size (for bounding offsets)
        self.getlike = {VA_GET - img.base: "rdx"}     # fn rva -> register that carries idx
        self.returners = {}                           # fn rva -> frozenset of P atoms it returns
        self.storers = {}                             # fn rva -> {(argname, off): frozenset(P)} (unseeded summary)
        self.kmap = {}                                # K -> [(obj, off)] cached-pointer loads (pass 2)
        self.gmap = {}                                # global rva -> [(obj, off)]
        self._decoded = {}
        self._memo = {}
        self._regname = {}
        self._noarg = {}                              # fn rva -> True for __security_check_cookie-like stubs
        self.iat = import_slots(img)                  # IAT slot rva -> 'dll!name'

    # -- decoding ---------------------------------------------------------------------
    def reg(self, rid):
        if rid == 0:
            return None
        r = self._regname.get(rid)
        if r is None:
            r = REGMAP.get(self.img.md.reg_name(rid), (None, 0))
            self._regname[rid] = r
        return r

    def decode(self, root: int):
        d = self._decoded.get(root)
        if d is not None:
            return d
        fo = self.funcs.function_of(root)
        if fo is None:
            # not in .pdata (leaf function): linear sweep to padding
            body = self.img.function_body(root, 0x4000)
            chunks = [(root, (body[-1].address + body[-1].size - self.img.base) if body else root)]
            root_rva = root
        else:
            root_rva, chunks = fo
        insns = []
        for b, e in chunks:
            pos = b
            while pos < e:
                got = False
                for ins in self.img.md.disasm(self.img.read(pos, e - pos), self.img.base + pos):
                    insns.append(ins)
                    pos = ins.address + ins.size - self.img.base
                    got = True
                    if len(insns) > MAX_FN_INSNS:
                        break
                if len(insns) > MAX_FN_INSNS:
                    break
                if pos < e and not got:
                    pos += 1
                elif pos < e:
                    pos += 1          # undecodable byte (jump table / data): skip
            if len(insns) > MAX_FN_INSNS:
                break
        d = dict(root=root_rva, chunks=chunks, insns=insns, too_big=len(insns) > MAX_FN_INSNS)
        self._build_cfg(d)
        self._decoded[root] = d
        if root_rva != root:
            self._decoded[root_rva] = d
        return d

    def _in_func(self, d, va):
        r = va - self.img.base
        return any(b <= r < e for b, e in d["chunks"])

    def _build_cfg(self, d):
        insns = d["insns"]
        addr2i = {ins.address: i for i, ins in enumerate(insns)}
        leaders = {insns[0].address} if insns else set()
        for b, _e in d["chunks"]:
            if self.img.base + b in addr2i:
                leaders.add(self.img.base + b)
        term_next = set()
        for i, ins in enumerate(insns):
            m = ins.mnemonic
            nxt = insns[i + 1].address if i + 1 < len(insns) else None
            if m in COND_JUMPS or m == "jmp":
                op = ins.operands[0] if ins.operands else None
                if op is not None and op.type == self.X.X86_OP_IMM and op.imm in addr2i:
                    leaders.add(op.imm)
                if nxt is not None:
                    leaders.add(nxt)
                    if m == "jmp":
                        term_next.add(nxt)
            elif m in ("ret", "int3", "retf"):
                if nxt is not None:
                    leaders.add(nxt)
                    term_next.add(nxt)
        order = sorted(leaders)
        blocks = {}
        for bi, a in enumerate(order):
            i0 = addr2i[a]
            i1 = addr2i[order[bi + 1]] if bi + 1 < len(order) else len(insns)
            # stop the block where addresses stop being contiguous
            blocks[a] = (i0, i1)
        succ, has_pred = {}, set()
        indirect = []
        for a, (i0, i1) in blocks.items():
            last = insns[i1 - 1]
            m = last.mnemonic
            s = []
            nxt = insns[i1].address if i1 < len(insns) else None
            contiguous = nxt is not None and nxt == last.address + last.size
            if m == "jmp":
                op = last.operands[0]
                if op.type == self.X.X86_OP_IMM:
                    if op.imm in addr2i:
                        s.append(op.imm)
                else:
                    indirect.append(a)
            elif m in COND_JUMPS:
                op = last.operands[0]
                if op.type == self.X.X86_OP_IMM and op.imm in addr2i:
                    s.append(op.imm)
                if contiguous:
                    s.append(nxt)
            elif m in ("ret", "int3", "retf"):
                pass
            elif contiguous:
                s.append(nxt)
            succ[a] = s
            has_pred.update(s)
        entry = insns[0].address if insns else None
        orphans = [a for a in blocks if a not in has_pred and a != entry]
        for a in indirect:                       # switch: unknown targets -> every orphan block
            succ[a] = list(set(succ[a]) | set(orphans))
        d.update(addr2i=addr2i, blocks=blocks, succ=succ, entry=entry)

    # -- value helpers ------------------------------------------------------------------
    def norm(self, atoms):
        if len(atoms) <= 1:
            return atoms
        ps = defaultdict(list)
        rest = []
        for a in atoms:
            if a[0] == "P":
                ps[(a[1], a[4])].append(a)
            else:
                rest.append(a)
        out = []
        for (obj, via), lst in ps.items():
            if len(lst) > 4:
                offs = sorted({a[2] for a in lst})
                g = 0
                for o in offs[1:]:
                    g = math.gcd(g, o - offs[0])
                strides = set()
                for a in lst:
                    strides.update(a[3])
                if g:
                    strides.add(g)
                out.append(("P", obj, offs[0], tuple(sorted(strides))[:4], via))
            else:
                out += lst
        onames = defaultdict(list)
        for a in rest:
            if a[0] == "O":
                onames[a[1]].append(a)
        for name, lst in onames.items():
            if len(lst) > 4 or (len(lst) > 1 and any(a[2] is None for a in lst)):
                # widen: "somewhere inside the object" (absorbing, keeps the join monotone)
                rest = [a for a in rest if not (a[0] == "O" and a[1] == name)] + [("O", name, None)]
        if len(rest) > 8:
            rest = sorted((a for a in rest if a[0] in ("F", "A", "O")), key=repr)[:8]
        return frozenset(out + rest)

    def padd(self, a, delta=0, stride=None):
        off = a[2] + delta
        size = self.obj_size(a[1])
        if off < -0x400 or off > size + 0x400:
            return None
        strides = a[3]
        if stride is not None and stride not in strides:
            strides = tuple(sorted(set(strides) | {stride}))[:4]
        return ("P", a[1], off, strides, a[4])

    @staticmethod
    def has_p(atoms):
        return any(a[0] == "P" for a in atoms)

    # -- function analysis --------------------------------------------------------------
    def analyze(self, root: int, seeds=None, depth=0, kmode=False, limit=None):
        """-> result dict(events, caches, escapes, returns, gets). Memoized."""
        key = (root, seeds, kmode)
        r = self._memo.get(key)
        if r is not None and not (r.get("truncated") and r["depth"] > depth):
            return r                     # (a depth-truncated result is only reused at the same or deeper depth)
        res = dict(events=[], caches=[], escapes=[], returns=set(), gets=[], forwards=None, fn=root,
                   ostores={}, truncated=False, depth=depth)
        self._memo[key] = res            # recursion guard: a cycle sees the (empty) partial result
        d = self.decode(root)
        if not d["insns"] or d["too_big"]:
            res["skipped"] = True
            return res
        entry = {"sp": 0}
        for r_ in ARGREGS:
            entry[r_] = frozenset([("A", r_), ("O", r_, 0)])
        if seeds:
            for r_, atoms in seeds:
                entry[r_] = atoms
        blocks, succ, insns = d["blocks"], d["succ"], d["insns"]
        instate = {d["entry"]: entry}
        work = [d["entry"]]
        visits = defaultdict(int)
        ctx = dict(d=d, depth=depth, kmode=kmode, res=None, limit=MAX_DEPTH if limit is None else limit)
        while work:
            a = work.pop()
            visits[a] += 1
            if visits[a] > 60:
                continue
            st = dict(instate[a])
            i0, i1 = blocks[a]
            for ins in insns[i0:i1]:
                self.step(ins, st, ctx)
            for s in succ[a]:
                old = instate.get(s)
                if old is None:
                    instate[s] = dict(st)
                    work.append(s)
                else:
                    new = self.join(old, st)
                    if new is not None:
                        instate[s] = new
                        work.append(s)
        ctx["res"] = res
        for a in sorted(instate):
            st = dict(instate[a])
            i0, i1 = blocks[a]
            for ins in insns[i0:i1]:
                self.step(ins, st, ctx)
        res["returns"] = frozenset(res["returns"])
        return res

    def join(self, old, st):
        changed = False
        new = dict(old)
        for k, v in st.items():
            if k == "sp":
                if old.get("sp", "x") != v and old.get("sp") is not None:
                    new["sp"] = None
                    changed = True
                continue
            if k in ("fresh", "members"):
                o = old.get(k, EMPTY)
                if not v <= o:
                    new[k] = o | v
                    changed = True
                continue
            o = old.get(k)
            if o is None:
                if v:
                    new[k] = v
                    changed = True
            elif not v <= o:
                u = self.norm(o | v)
                if u != o:
                    new[k] = u
                    changed = True
        return new if changed else None

    # -- operand helpers ------------------------------------------------------------------
    def slot(self, st, mem):
        if mem.index != 0 or mem.segment != 0:
            return None
        b = self.reg(mem.base)
        if b is None or b[0] is None:
            return None
        if b[0] == "rsp":
            sp = st.get("sp")
            return None if sp is None else ("s", sp + mem.disp)
        atoms = st.get(b[0], EMPTY)
        if len(atoms) == 1:
            a = next(iter(atoms))
            if a[0] == "F":
                return ("s", a[1] + mem.disp)
        return None

    def okeys(self, st, mem):
        """[('o', name, off)] when the operand is [reg+disp] and reg holds object addresses."""
        if mem.index != 0 or mem.segment != 0:
            return []
        b = self.reg(mem.base)
        if b is None or b[0] is None or b[1] != 8 or b[0] == "rsp":
            return []
        return [("o", a[1], a[2] + mem.disp) for a in st.get(b[0], EMPTY) if a[0] == "O" and a[2] is not None]

    @staticmethod
    def via_mem(a, k):
        """P atom reloaded from an object field: remember that in 'via' (once)."""
        via = a[4] if ">" in a[4] else f"{a[4]}>[obj+{k:#x}]"
        return ("P", a[1], a[2], a[3], via)

    def mem_ptrs(self, st, mem):
        """[(atom-with-effective-offset)] for a memory operand whose base/index holds a pointer."""
        out = []
        b, x = self.reg(mem.base), self.reg(mem.index)
        if b and b[0] and b[1] == 8:
            for a in st.get(b[0], EMPTY):
                if a[0] == "P":
                    stride = None
                    if x and x[0]:
                        stride = self.index_stride(st, x[0], mem.scale)
                    p = self.padd(a, mem.disp, stride)
                    if p:
                        out.append(p)
        if x and x[0] and x[1] == 8 and mem.scale == 1:
            for a in st.get(x[0], EMPTY):
                if a[0] == "P":
                    stride = self.index_stride(st, b[0], 1) if b and b[0] else None
                    p = self.padd(a, mem.disp, stride)
                    if p:
                        out.append(p)
        return out

    @staticmethod
    def index_stride(st, regname, scale):
        ks = [a[1] for a in st.get(regname, EMPTY) if a[0] == "S"]
        cs = [a[1] for a in st.get(regname, EMPTY) if a[0] == "C"]
        if ks:
            return abs(ks[0] * scale) or 1
        if cs and len(cs) == 1:
            return None if cs[0] == 0 else 1
        return scale

    def rip_target(self, ins, mem):
        if mem.base == self.X.X86_REG_RIP:
            return ins.address + ins.size + mem.disp - self.img.base
        return None

    # -- transfer function ----------------------------------------------------------------
    def step(self, ins, st, ctx):
        X = self.X
        m = ins.mnemonic
        ops = ins.operands
        res = ctx["res"]

        # 1. memory operands through tracked pointers -> read / write events
        if m not in ("lea", "nop"):
            for op in ops:
                if op.type != X.X86_OP_MEM:
                    continue
                if op.mem.base == X.X86_REG_RIP:
                    continue
                ptrs = self.mem_ptrs(st, op.mem)
                if ptrs and res is not None:
                    acc = op.access
                    kind = "w" if acc == self.cs.CS_AC_WRITE else ("rw" if acc & self.cs.CS_AC_WRITE else "r")
                    for p in ptrs:
                        res["events"].append(dict(va=ins.address, fn=ctx["d"]["root"], insn=f"{m} {ins.op_str}",
                                                  obj=p[1], off=p[2], strides=p[3], via=p[4], size=op.size,
                                                  mn=m, acc=kind, depth=ctx["depth"]))

        # 2. calls
        if m == "call" or (m == "jmp" and ops and ops[0].type == X.X86_OP_IMM
                           and not self._in_func(ctx["d"], ops[0].imm)):
            self.do_call(ins, st, ctx, tail=(m == "jmp"))
            return
        if m == "ret":
            if res is not None:
                for a in st.get("rax", EMPTY):
                    if a[0] == "P":
                        res["returns"].add(a)
                        res["escapes"].append(dict(va=ins.address, fn=ctx["d"]["root"], kind="returned", obj=a[1],
                                                   insn="ret", followed=True))
            return
        if not ops:
            self.generic(ins, st)
            return

        o0 = ops[0]
        o1 = ops[1] if len(ops) > 1 else None
        if m == "mov" and o1 is not None:
            if o0.type == X.X86_OP_REG:
                dst = self.reg(o0.reg)
                if dst is None or dst[0] is None:
                    return
                if dst[0] == "rsp":
                    src = self.reg(o1.reg) if o1.type == X.X86_OP_REG else None
                    fa = [a for a in st.get(src[0], EMPTY) if a[0] == "F"] if src and src[0] else []
                    st["sp"] = fa[0][1] if len(fa) == 1 else None
                    return
                val = EMPTY
                if dst[1] >= 4:
                    if o1.type == X.X86_OP_REG:
                        src = self.reg(o1.reg)
                        if src and src[0]:
                            if src[0] == "rsp":
                                val = frozenset([("F", st["sp"])]) if st.get("sp") is not None else EMPTY
                            else:
                                val = st.get(src[0], EMPTY)
                                if dst[1] == 4:
                                    val = frozenset(a for a in val if a[0] in ("C", "S"))
                    elif o1.type == X.X86_OP_IMM:
                        val = frozenset([("C", o1.imm & 0xFFFFFFFFFFFFFFFF)])
                    elif o1.type == X.X86_OP_MEM:
                        sl = self.slot(st, o1.mem)
                        if sl is not None:
                            val = st.get(sl, EMPTY)
                            if dst[1] == 4:
                                val = frozenset(a for a in val if a[0] in ("C", "S"))
                        elif dst[1] == 8:
                            got = set()
                            for k_ in self.okeys(st, o1.mem):
                                got.update(self.via_mem(a, k_[2]) for a in st.get(k_, EMPTY) if a[0] == "P")
                            val = frozenset(got) if got else self.cached_load(ins, o1.mem, st, ctx)
                self.setreg(st, dst[0], val)
                return
            if o0.type == X.X86_OP_MEM:
                sl = self.slot(st, o0.mem)
                val = EMPTY
                if o1.type == X.X86_OP_REG:
                    src = self.reg(o1.reg)
                    if src and src[0] and src[1] == 8:
                        val = st.get(src[0], EMPTY) if src[0] != "rsp" else EMPTY
                    elif src and src[0] and src[1] == 4:
                        val = frozenset(a for a in st.get(src[0], EMPTY) if a[0] in ("C", "S"))
                elif o1.type == X.X86_OP_IMM:
                    val = frozenset([("C", o1.imm & 0xFFFFFFFFFFFFFFFF)])
                if sl is not None:
                    if val:
                        st[sl] = val
                        if o0.size == 8:
                            # written since the last call: a candidate outgoing stack argument
                            st["fresh"] = st.get("fresh", EMPTY) | {sl[1]}
                    else:
                        st.pop(sl, None)
                elif o0.size == 8 and self.has_p(val) and self.okeys(st, o0.mem):
                    pv = frozenset(a for a in val if a[0] == "P")
                    oks = self.okeys(st, o0.mem)
                    for k_ in oks:
                        st[k_] = self.norm(st.get(k_, EMPTY) | pv)          # weak update
                        if res is not None:
                            res["ostores"][(k_[1], k_[2])] = res["ostores"].get((k_[1], k_[2]), EMPTY) | pv
                    if res is not None:
                        b = self.reg(o0.mem.base)
                        for a in pv:
                            res["caches"].append(dict(va=ins.address, fn=ctx["d"]["root"], insn=f"{m} {ins.op_str}",
                                                      obj=a[1], off=a[2], strides=a[3], via=a[4], depth=ctx["depth"],
                                                      kind="field", K=o0.mem.disp, base=b[0],
                                                      into=sorted({str(k_[1]) for k_ in oks})))
                elif res is not None and o0.size == 8 and self.has_p(val):
                    mem = o0.mem
                    tgt = self.rip_target(ins, mem)
                    b = self.reg(mem.base)
                    for a in val:
                        if a[0] != "P":
                            continue
                        c = dict(va=ins.address, fn=ctx["d"]["root"], insn=f"{m} {ins.op_str}", obj=a[1], off=a[2],
                                 strides=a[3], via=a[4], depth=ctx["depth"])
                        if tgt is not None:
                            c.update(kind="global", addr=tgt)
                        elif b and b[0] and mem.index == 0:
                            c.update(kind="field", K=mem.disp, base=b[0])
                        else:
                            c.update(kind="other")
                        res["caches"].append(c)
                return
        if m in ("movsxd", "movzx", "movsx") and o0.type == X.X86_OP_REG:
            dst = self.reg(o0.reg)
            val = EMPTY
            if o1.type == X.X86_OP_REG:
                src = self.reg(o1.reg)
                if src and src[0] and src[1] >= 4:
                    val = frozenset(a for a in st.get(src[0], EMPTY) if a[0] in ("C", "S"))
            if dst and dst[0]:
                self.setreg(st, dst[0], val)
            return
        if m == "lea" and o0.type == X.X86_OP_REG:
            dst = self.reg(o0.reg)
            mem = o1.mem
            val = set()
            b, x = self.reg(mem.base), self.reg(mem.index)
            if mem.base == X.X86_REG_RIP:
                pass
            else:
                for p in self.mem_ptrs(st, mem):
                    val.add(p)
                if b and b[0] == "rsp" and not (x and x[0]):
                    if st.get("sp") is not None:
                        val.add(("F", st["sp"] + mem.disp))
                elif b and b[0] and not (x and x[0]):
                    for a in st.get(b[0], EMPTY):
                        if a[0] == "F":
                            val.add(("F", a[1] + mem.disp))
                        elif a[0] == "O":
                            val.add(("O", a[1], None if a[2] is None else a[2] + mem.disp))
                        elif a[0] == "C":
                            val.add(("C", (a[1] + mem.disp) & 0xFFFFFFFFFFFFFFFF))
                        elif a[0] == "S":
                            val.add(a)
                elif b and b[0] and b[1] == 8:
                    for a in st.get(b[0], EMPTY):          # [obj + idx*s + disp]: somewhere inside the object
                        if a[0] == "O":
                            val.add(("O", a[1], None))
                if not val and x and x[0]:
                    # pure index arithmetic: lea r,[x*s] / [x+x*s] / [y+x*s]
                    kx = [a[1] for a in st.get(x[0], EMPTY) if a[0] == "S"]
                    k = (kx[0] if kx else 1) * mem.scale
                    if b and b[0]:
                        if b[0] == x[0]:
                            k = (kx[0] if kx else 1) * (mem.scale + 1)
                        else:
                            kb = [a[1] for a in st.get(b[0], EMPTY) if a[0] == "S"]
                            k = math.gcd(k, kb[0]) if kb else 1
                    if k > 1:
                        val.add(("S", k))
            if dst and dst[0]:
                if dst[0] == "rsp":
                    fa = [a for a in val if a[0] == "F"]
                    st["sp"] = fa[0][1] if len(fa) == 1 else None
                else:
                    self.setreg(st, dst[0], frozenset(val) if dst[1] == 8 else
                                frozenset(a for a in val if a[0] in ("C", "S")))
            return
        if m in ("add", "sub") and o0.type == X.X86_OP_REG:
            dst = self.reg(o0.reg)
            if dst is None or dst[0] is None:
                return
            sign = 1 if m == "add" else -1
            if dst[0] == "rsp":
                if o1.type == X.X86_OP_IMM and st.get("sp") is not None:
                    st["sp"] += sign * o1.imm
                else:
                    st["sp"] = None
                self.drop_below_sp(st)
                return
            cur = st.get(dst[0], EMPTY)
            val = set()
            if dst[1] >= 4:
                if o1.type == X.X86_OP_IMM:
                    for a in cur:
                        if a[0] == "P" and dst[1] == 8:
                            p = self.padd(a, sign * o1.imm)
                            if p:
                                val.add(p)
                        elif a[0] == "C":
                            val.add(("C", (a[1] + sign * o1.imm) & 0xFFFFFFFFFFFFFFFF))
                        elif a[0] == "S":
                            val.add(a)
                        elif a[0] == "F" and dst[1] == 8:
                            val.add(("F", a[1] + sign * o1.imm))
                        elif a[0] == "O" and dst[1] == 8:
                            val.add(("O", a[1], None if a[2] is None else a[2] + sign * o1.imm))
                elif o1.type == X.X86_OP_REG:
                    src = self.reg(o1.reg)
                    sv = st.get(src[0], EMPTY) if src and src[0] else EMPTY
                    if dst[1] == 8 and m == "add":
                        for a in cur:
                            if a[0] == "P":
                                consts = [c[1] for c in sv if c[0] == "C"]
                                if consts and len(sv) == len(consts):
                                    for c in consts:
                                        p = self.padd(a, c if c < 1 << 63 else c - (1 << 64))
                                        if p:
                                            val.add(p)
                                else:
                                    p = self.padd(a, 0, self.index_stride(st, src[0], 1) if src and src[0] else 1)
                                    if p:
                                        val.add(p)
                        for a in sv:
                            if a[0] == "P":
                                p = self.padd(a, 0, self.index_stride(st, dst[0], 1))
                                if p:
                                    val.add(p)
                    if not val:
                        ka = [a[1] for a in cur if a[0] == "S"]
                        kb = [a[1] for a in sv if a[0] == "S"]
                        if ka and kb:
                            g = math.gcd(ka[0], kb[0])
                            if g > 1:
                                val.add(("S", g))
            self.setreg(st, dst[0], frozenset(val))
            return
        if m == "imul" and o0.type == X.X86_OP_REG and len(ops) == 3 and ops[2].type == X.X86_OP_IMM:
            dst = self.reg(o0.reg)
            k = abs(ops[2].imm)
            if o1.type == X.X86_OP_REG:
                src = self.reg(o1.reg)
                ks = [a[1] for a in st.get(src[0], EMPTY) if a[0] == "S"] if src and src[0] else []
                if ks:
                    k *= ks[0]
            if dst and dst[0]:
                self.setreg(st, dst[0], frozenset([("S", k)]) if k > 1 else EMPTY)
            return
        if m in ("shl", "sal") and o0.type == X.X86_OP_REG and o1 is not None and o1.type == X.X86_OP_IMM:
            dst = self.reg(o0.reg)
            if dst and dst[0]:
                ks = [a[1] for a in st.get(dst[0], EMPTY) if a[0] == "S"]
                k = (ks[0] if ks else 1) << (o1.imm & 63)
                self.setreg(st, dst[0], frozenset([("S", k)]) if dst[1] >= 4 and k < 1 << 20 else EMPTY)
            return
        if m == "xor" and o0.type == X.X86_OP_REG and o1 is not None and o1.type == X.X86_OP_REG and o0.reg == o1.reg:
            dst = self.reg(o0.reg)
            if dst and dst[0]:
                self.setreg(st, dst[0], frozenset([("C", 0)]))
            return
        if m.startswith("cmov") and o0.type == X.X86_OP_REG:
            dst = self.reg(o0.reg)
            if dst and dst[0]:
                val = st.get(dst[0], EMPTY)
                if o1.type == X.X86_OP_REG:
                    src = self.reg(o1.reg)
                    if src and src[0]:
                        val = val | st.get(src[0], EMPTY)
                elif o1.type == X.X86_OP_MEM:
                    sl = self.slot(st, o1.mem)
                    if sl is not None:
                        val = val | st.get(sl, EMPTY)
                if dst[1] != 8:
                    val = frozenset(a for a in val if a[0] in ("C", "S"))
                self.setreg(st, dst[0], self.norm(val))
            return
        if m == "xchg" and o0.type == X.X86_OP_REG and o1.type == X.X86_OP_REG:
            a_, b_ = self.reg(o0.reg), self.reg(o1.reg)
            if a_ and b_ and a_[0] and b_[0] and a_[1] == 8 and b_[1] == 8:
                va_, vb_ = st.get(a_[0], EMPTY), st.get(b_[0], EMPTY)
                self.setreg(st, a_[0], vb_)
                self.setreg(st, b_[0], va_)
                return
        if m == "push":
            if st.get("sp") is not None:
                st["sp"] -= 8
                val = EMPTY
                if o0.type == X.X86_OP_REG:
                    src = self.reg(o0.reg)
                    if src and src[0] and src[1] == 8 and src[0] != "rsp":
                        val = st.get(src[0], EMPTY)
                if val:
                    st[("s", st["sp"])] = val
                else:
                    st.pop(("s", st["sp"]), None)
            return
        if m == "pop":
            val = EMPTY
            if st.get("sp") is not None:
                val = st.get(("s", st["sp"]), EMPTY)
                st["sp"] += 8
                self.drop_below_sp(st)
            if o0.type == X.X86_OP_REG:
                dst = self.reg(o0.reg)
                if dst and dst[0] and dst[0] != "rsp":
                    self.setreg(st, dst[0], val)
            return
        self.generic(ins, st)

    def drop_below_sp(self, st):
        sp = st.get("sp")
        if sp is None:
            for k in [k for k in st if isinstance(k, tuple) and k[0] == "s"]:
                del st[k]

    @staticmethod
    def setreg(st, r, val):
        if val:
            st[r] = val
        else:
            st.pop(r, None)

    def generic(self, ins, st):
        X = self.X
        try:
            _rd, wr = ins.regs_access()
        except Exception:
            wr = [op.reg for op in ins.operands[:1] if op.type == X.X86_OP_REG]
        for rid in wr:
            r = self.reg(rid)
            if r and r[0]:
                if r[0] == "rsp":
                    st["sp"] = None
                    self.drop_below_sp(st)
                else:
                    st.pop(r[0], None)
        for op in ins.operands:
            if op.type == X.X86_OP_MEM and (op.access & self.cs.CS_AC_WRITE):
                sl = self.slot(st, op.mem)
                if sl is not None:
                    st.pop(sl, None)

    def cached_load(self, ins, mem, st, ctx):
        """mov r64,[mem]: pointer reloaded from a field / global where a get() result is cached."""
        tgt = self.rip_target(ins, mem)
        if tgt is not None:
            hits = self.gmap.get(tgt)
            if hits:
                return frozenset(("P", obj, off, (), f"G:{tgt + self.img.base:#x}") for obj, off in hits)
            return EMPTY
        if not ctx["kmode"] or mem.index != 0:
            return EMPTY
        hits = self.kmap.get(mem.disp)
        if not hits:
            return EMPTY
        b = self.reg(mem.base)
        if not b or not b[0] or b[0] == "rsp":
            return EMPTY
        if any(a[0] in ("F", "P") for a in st.get(b[0], EMPTY)):
            return EMPTY
        return frozenset(("P", obj, off, (), f"K:{mem.disp:#x}") for obj, off in hits)

    def call_args(self, st, tail):
        """[(callee entry key, callee object name, caller state key)] for the 4 register arguments and
        the stack arguments written since the previous call (see 'fresh')."""
        out = [(r, r, r) for r in ARGREGS]
        sp_ = st.get("sp")
        fresh = st.get("fresh", EMPTY)
        if sp_ is not None and not tail:
            # caller [rsp+0x20+8i] is the callee's [entry rsp+0x28+8i]. Only slots WRITTEN SINCE THE
            # PREVIOUS CALL count: the callee owns its argument area, so a compiler never relies on a
            # stale slot - and a stale slot still holding the pointer would otherwise be reported as
            # an argument of every later call.
            for i in range(8):
                if sp_ + 0x20 + 8 * i in fresh:
                    out.append((("s", 0x28 + 8 * i), f"sa{0x28 + 8 * i:x}", ("s", sp_ + 0x20 + 8 * i)))
        elif sp_ == 0 and tail:
            for i in range(8):                   # tail jump: our incoming stack arguments are the callee's
                out.append((("s", 0x28 + 8 * i), f"sa{0x28 + 8 * i:x}", ("s", 0x28 + 8 * i)))
        return out

    def obj_contents(self, st, atoms, pslots, members):
        """tracked pointers inside the object(s) an argument value points at.
        -> {k: (frozenset(P), definite)}; definite=False for a frame slot that was written directly by
        this function (it may be an unrelated spill that merely sits above the passed address)."""
        out = {}
        for a in atoms:
            if a[0] == "F":
                for key, pv in pslots:
                    if key[0] == "s" and 0 <= key[1] - a[1] < OBJ_WINDOW:
                        k = key[1] - a[1]
                        old = out.get(k, (EMPTY, False))
                        # definite only when a callee stored it THROUGH THIS SAME ADDRESS (a real member of the
                        # struct at a[1]); any other tracked slot above the address may be an unrelated spill
                        out[k] = (old[0] | pv, old[1] or (a[1], k) in members)
            elif a[0] == "O" and a[2] is not None:
                for key, pv in pslots:
                    if key[0] == "o" and key[1] == a[1] and -0x100 <= key[2] - a[2] < OBJ_WINDOW:
                        k = key[2] - a[2]
                        old = out.get(k, (EMPTY, False))
                        out[k] = (old[0] | pv, True)
        return out

    def is_cookie_check(self, target):
        """__security_check_cookie: 'cmp rcx,[rip+cookie]; jne; rol rcx,0x10; test cx,0xffff'. It takes
        the cookie in rcx and nothing else; whatever still sits in rdx/r8/r9 is not an argument."""
        r = self._noarg.get(target)
        if r is None:
            b = self.img.read(target, 16)
            r = b[:3] == b"\x48\x3b\x0d" and b[7:9] == b"\x75\x10" and b[9:13] == b"\x48\xc1\xc1\x10"
            self._noarg[target] = r
        return r

    def do_call(self, ins, st, ctx, tail):
        X = self.X
        res = ctx["res"]
        op = ins.operands[0]
        target = op.imm - self.img.base if op.type == X.X86_OP_IMM else None
        ret = EMPTY
        if target is not None and self.is_cookie_check(target):
            return                                       # preserves every register it is given
        idxreg = self.getlike.get(target) if target is not None else None
        if idxreg is not None:
            iv = st.get(idxreg, EMPTY)
            consts = sorted({a[1] for a in iv if a[0] == "C" and a[1] < 0x1000})
            args = [a for a in iv if a[0] == "A"]
            site = ins.address
            if consts:
                ret = frozenset(("P", c, 0, (), "get") for c in consts)
            else:
                ret = frozenset([("P", ("?", site), 0, (), "get")])
            if res is not None:
                res["gets"].append(dict(va=site, fn=ctx["d"]["root"], idx=consts, insn=f"{ins.mnemonic} {ins.op_str}",
                                        idx_from_arg=args[0][1] if args and not consts else None))
                if args and not consts and tail:
                    res["forwards"] = args[0][1]
        else:
            if target is not None and target in self.returners:
                ret = frozenset(("P", a[1], a[2], a[3], "ret") for a in self.returners[target])
            cargs = self.call_args(st, tail)
            pslots = [(k, frozenset(a for a in v if a[0] == "P")) for k, v in st.items()
                      if isinstance(k, tuple) and isinstance(v, frozenset)]
            pslots = [(k, v) for k, v in pslots if v]
            members = st.get("members", EMPTY)
            # 1. the pointer itself handed to the callee
            passed = []
            for ekey, _name, ckey in cargs:
                v = frozenset(a for a in st.get(ckey, EMPTY) if a[0] == "P")
                if v:
                    passed.append((ekey, v))
            # 2. an object (frame struct / object we were handed) that HOLDS the pointer handed to the callee
            objs = []                                    # (ekey, name, contents)
            if pslots:
                for ekey, name, ckey in cargs:
                    av = st.get(ckey, EMPTY)
                    if any(a[0] == "P" for a in av):
                        continue
                    cont = self.obj_contents(st, av, pslots, members)
                    if cont:
                        objs.append((ekey, name, cont))
            seeds = list(passed)
            for ekey, name, cont in objs:
                if not isinstance(ekey, str):
                    seeds.append((ekey, frozenset([("O", name, 0)])))
                for k, (pv, definite) in cont.items():
                    if not definite:
                        pv = frozenset(("P", a[1], a[2], a[3], a[4] if ">" in a[4] else f"{a[4]}>[frame+{k:#x}]")
                                       for a in pv)
                    seeds.append((("o", name, k), pv))
            sub = None
            followed = False
            if seeds:
                if target is not None and self.img.is_code(target + self.img.base):
                    if ctx["depth"] < ctx["limit"]:
                        sub = self.analyze(target, seeds=tuple(sorted(seeds, key=repr)), depth=ctx["depth"] + 1,
                                           limit=ctx["limit"])
                        followed = not sub.get("skipped")
                        ret = ret | frozenset(a for a in sub["returns"] if a[0] == "P")
                        if res is not None and sub.get("truncated"):
                            res["truncated"] = True
                    elif res is not None:
                        res["truncated"] = True
                if res is not None:
                    why = ext = None
                    if not followed:
                        why = ("indirect call" if target is None else
                               "depth limit" if ctx["depth"] >= ctx["limit"] else "callee not analysable")
                        if target is None and op.type == X.X86_OP_MEM:
                            slot_rva = self.rip_target(ins, op.mem)
                            ext = self.iat.get(slot_rva) if slot_rva is not None else None
                            if ext:
                                why = f"import {ext}: leaves the image"
                    for ekey, v in passed:
                        rn = ekey if isinstance(ekey, str) else f"stack+{ekey[1] - 8:#x}"
                        for a in v:
                            res["escapes"].append(dict(va=ins.address, fn=ctx["d"]["root"], kind=f"arg:{rn}", obj=a[1],
                                                       insn=f"{ins.mnemonic} {ins.op_str}", followed=followed,
                                                       certain=">[frame+" not in a[4], why=why, external=ext))
                    for ekey, name, cont in objs:
                        for k, (pv, definite) in cont.items():
                            for a in pv:
                                res["escapes"].append(dict(va=ins.address, fn=ctx["d"]["root"],
                                                           kind=f"in-object:{name}+{k:#x}", obj=a[1],
                                                           insn=f"{ins.mnemonic} {ins.op_str}", followed=followed,
                                                           certain=definite and ">[frame+" not in a[4],
                                                           why=why, external=ext))
                    if sub is not None and followed:
                        for e in sub["events"]:
                            e2 = dict(e)
                            e2.setdefault("entry", f"{ins.address:#x} -> {target + self.img.base:#x}")
                            res["events"].append(e2)
                        res["caches"] += sub["caches"]
                        res["escapes"] += sub["escapes"]
            # 3. pointer stores the callee made through its object arguments -> our own view of those objects
            ost = {}
            if target is not None and target in self.storers:
                ost.update(self.storers[target])
            if sub is not None and followed:
                for k_, v in sub["ostores"].items():
                    ost[k_] = ost.get(k_, EMPTY) | v
            if ost:
                name2ckey = {name: ckey for _e, name, ckey in cargs}
                for (name, k), pv in ost.items():
                    ckey = name2ckey.get(name)
                    tracked = False
                    for a in (st.get(ckey, EMPTY) if ckey is not None else EMPTY):
                        if a[0] == "F":
                            key = ("s", a[1] + k)
                            st[key] = self.norm(st.get(key, EMPTY) | pv)
                            st["members"] = st.get("members", EMPTY) | {(a[1], k)}
                            tracked = True
                        elif a[0] == "O" and a[2] is not None:
                            key = ("o", a[1], a[2] + k)
                            st[key] = self.norm(st.get(key, EMPTY) | pv)
                            if res is not None:
                                res["ostores"][(a[1], a[2] + k)] = res["ostores"].get((a[1], a[2] + k), EMPTY) | pv
                            tracked = True
                    if not tracked and res is not None:
                        for a in pv:
                            res["escapes"].append(dict(va=ins.address, fn=ctx["d"]["root"],
                                                       kind=f"stored-by-callee:[{name}+{k:#x}]", obj=a[1],
                                                       insn=f"{ins.mnemonic} {ins.op_str}", followed=False, certain=True,
                                                       why="callee stored the pointer into an object this function "
                                                           "does not own (heap / member object): reloads are not followed"))
        for r in VOLATILE:
            st.pop(r, None)
        st.pop("fresh", None)
        sp = st.get("sp")
        if sp is not None:
            for k in range(0, 0x20, 8):
                st.pop(("s", sp + k), None)
        if ret:
            st["rax"] = self.norm(ret)
        if tail and res is not None:
            for a in ret:
                if a[0] == "P":
                    res["returns"].add(a)


# ----------------------------------------------------------------------------------------
# field attribution
# ----------------------------------------------------------------------------------------

def size_kind_ok(leaf, ev) -> bool:
    off, size, kind, _p = leaf
    mn, asz = ev["mn"], ev["size"]
    if kind == "string":
        return asz == 8 and (ev["off"] - off) in (0, 8, 16, 24)
    if ev["off"] != off:
        return False
    if kind == "float":
        return (mn in SSE_FLOAT and asz in (4, 16, 8)) or (mn == "mov" and asz == 4)
    if kind == "double":
        return asz == 8
    if kind in ("int", "int64"):
        return asz == size and (mn not in SSE_FLOAT or mn in ("movd", "movq"))
    if kind in ("bool", "int8"):
        return asz == 1
    if kind == "int16":
        return asz == 2
    return asz == size


def attribute(layout: Layout, ev) -> list[dict]:
    """event -> [{field, elem, fit, note}] (several when a wide read covers several leaves)."""
    off, strides, size = ev["off"], [k for k in ev["strides"]], max(ev["size"], 1)
    known = [k for k in strides if k > 1]
    if 0 <= off < 8 and not strides:
        return [dict(field=None, note="vtable/header", fit=True)]
    leaf0 = layout.leaf_at(off)
    if not strides:
        leaves = layout.leaves_in(off, off + size) if size > 8 else ([leaf0] if leaf0 else [])
        if not leaves:
            return [dict(field=None, note=f"unmapped struct offset {off:#x}", fit=False)]
        out = []
        for l in leaves:
            idx = tuple(p for p in l[3] if isinstance(p, int))
            out.append(dict(field=cstr(l[3]), elem=list(idx) if idx else None,
                            fit=size_kind_ok(l, ev) if l is leaves[0] else True, note=None))
        return out
    # indexed
    cands = []                                   # (leaf, effective first-element offset, note)
    if leaf0:
        encl = layout.enclosing_arrays(leaf0[3])
        if encl and (not known or any(k % a["stride"] == 0 for k in known for a in encl if a["stride"])):
            cands.append((leaf0, off, "indexed"))
    if not cands and known:
        for ap, a in layout.arrays.items():
            s = a["stride"]
            if not s or not any(k % s == 0 for k in known):
                continue
            if a["base"] - 2 * s <= off < a["base"] + a["count"] * s:
                eff = a["base"] + (off - a["base"]) % s
                l = layout.leaf_at(eff)
                if l:
                    cands.append((l, eff, f"indexed (stride {s:#x} match, operand offset {off:#x})"))
    if not cands and leaf0:
        cands.append((leaf0, off, "indexed read starting here; index stride does not match a decoded array - "
                                  "neighbouring fields may be read too"))
    if not cands:
        return [dict(field=None, note=f"indexed read at unmapped offset {off:#x} strides {strides}", fit=False)]
    return [dict(field=cstr(l[3]), elem="*", fit=size_kind_ok(l, dict(ev, off=eff)), note=note)
            for l, eff, note in cands]


# ----------------------------------------------------------------------------------------
# build
# ----------------------------------------------------------------------------------------

def find_k_candidates(img: Image, ci: CallIndex, K: int) -> list[int]:
    """rva of instructions 'mov r64,[reg+K]' in .xcode (byte-pattern; verified later by decoding)."""
    buf = img.m
    lo, hi = ci.raw, ci.raw + ci.n
    out = []
    if -0x80 <= K < 0x80:
        kb = struct.pack("<b", K)
        pat = re.compile(rb"[\x48\x49\x4c\x4d]\x8b(?:[\x40-\x43\x45-\x4b\x4d-\x53\x55-\x5b\x5d-\x63\x65-\x6b\x6d-\x73\x75-\x7b\x7d-\x7f]|[\x44\x4c\x54\x5c\x64\x6c\x74\x7c]\x24)" + re.escape(kb))
    else:
        kb = struct.pack("<i", K)
        pat = re.compile(rb"[\x48\x49\x4c\x4d]\x8b(?:[\x80-\x83\x85-\x8b\x8d-\x93\x95-\x9b\x9d-\xa3\xa5-\xab\xad-\xb3\xb5-\xbb\xbd-\xbf]|[\x84\x8c\x94\x9c\xa4\xac\xb4\xbc]\x24)" + re.escape(kb))
    for mt in pat.finditer(buf, lo, hi):
        out.append(mt.start() - ci.raw + ci.va)
    return out


def build(args) -> int:
    t0 = time.time()
    img = Image(Path(args.exe))
    print(f"exe: {args.exe}")
    # shape checks: fail loudly rather than analyse the wrong thing
    g = img.disasm(VA_GET - img.base, 0x40)
    if not any(i.mnemonic == "mov" and "rax + rbx*8" in i.op_str for i in g):
        sys.exit("get() shape changed - re-verify VA_GET")
    w = img.disasm(VA_WRAPPER - img.base, 0x14)
    if img.lea_target(w[0]) != VA_MANAGER_GLOBAL - img.base or w[-1].mnemonic != "jmp":
        sys.exit("wrapper shape changed - re-verify VA_WRAPPER / VA_MANAGER_GLOBAL")
    print(f"  wrapper {VA_WRAPPER:#x}: '{w[0].mnemonic} {w[0].op_str}' ... '{w[-1].mnemonic} {w[-1].op_str}' "
          f"-> idx stays in edx (the wrapper only loads rcx)")

    types = locate_types(img)
    helpers = locate_helpers(img, types)
    layouts = build_layouts(img, types, helpers)
    reg, table_va, count = registration_table(img, types)
    name2idx = {v["name"]: k for k, v in reg.items()}
    print(f"  registration table {table_va:#x}: {count} entries, {len(layouts)} types")
    bad = {n: (name2idx.get(n), i) for n, i in KNOWN_IDX.items() if name2idx.get(n) != i}
    if bad:
        sys.exit(f"registration table disagrees with known indices: {bad}")
    print(f"  known indices cross-check OK: {', '.join(f'{n}={i:#x}' for n, i in KNOWN_IDX.items())}")

    OUT_OFFSETS.parent.mkdir(parents=True, exist_ok=True)
    off_doc = dict(meta=dict(generated=time.strftime("%Y-%m-%d"), exe=str(args.exe),
                             note="RUNTIME struct offsets from the emulated JSON loaders (JsonEmu). "
                                  "NOT the .o file offsets of dt270_schema.json. +0 is the vtable."),
                   registration={f"{k:#x}": dict(name=v["name"], type=v["type"]) for k, v in reg.items()},
                   types={n: l.to_json() | dict(members=next(t["members"] for t in types if t["members"][0] == n))
                          for n, l in layouts.items()})
    OUT_OFFSETS.write_text(json.dumps(off_doc, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {OUT_OFFSETS} ({OUT_OFFSETS.stat().st_size:,} B)")

    funcs = Funcs(img)
    ci = CallIndex(img)
    print(f"  .pdata: {len(funcs.begin):,} entries; call index: {len(ci.pos):,} rel32 call/jmp  [{time.time() - t0:.1f}s]")

    def obj_size(obj):
        if isinstance(obj, int) and obj in reg and reg[obj]["type"]:
            return layouts[reg[obj]["type"]].size
        return 0x13000

    an = Analyzer(img, funcs, obj_size)

    leaf_cache = {}

    def fn_root(site_rva):
        """enclosing function start: .pdata, else (leaf functions have no unwind info) the closest
        16-aligned address after int3 padding from which a linear sweep lands exactly on the site."""
        fo = funcs.function_of(site_rva)
        if fo:
            return fo[0]
        a = site_rva & ~0xF
        for _ in range(0x40):
            if a in leaf_cache:
                return leaf_cache[a]
            if funcs.index_of(a) is not None:
                return None
            if img.read(a - 1, 1) == bytes([0xCC]):
                addrs = {i.address - img.base for i in img.function_body(a, 0x800)}
                if site_rva in addrs:
                    leaf_cache[a] = a
                    return a
            a -= 0x10
        return None

    # ---- pass 1: get sites, fixpoint over get-like forwarders and pointer-returning functions
    site_fns: dict[int, set] = defaultdict(set)      # function root -> call sites inside it
    orphan_sites = []
    seen_targets = set()
    todo = [VA_GET - img.base]
    results = {}
    known_globals = set()
    for rnd in range(8):
        new_targets = [t for t in todo if t not in seen_targets]
        if not new_targets:
            break
        dirty = set()
        for t in new_targets:
            seen_targets.add(t)
            for site in ci.callers(t):
                r = fn_root(site)
                if r is None:
                    orphan_sites.append((site, t))
                    continue
                site_fns[r].add(site)
                dirty.add(r)
        an._memo.clear()
        todo = []
        for r in sorted(site_fns):
            res = an.analyze(r)
            results[r] = res
            if res.get("forwards") and r not in an.getlike:
                an.getlike[r] = res["forwards"]
                todo.append(r)
            rets = frozenset(a for a in res["returns"] if a[0] == "P" and isinstance(a[1], int))
            if rets and an.returners.get(r) != rets and r not in an.getlike:
                an.returners[r] = rets
                todo.append(r)
                seen_targets.discard(r)
            # the function stores the pointer into an object it was handed (this->member = get(..)):
            # its callers own that object, so they are analysed with the store applied at the call.
            ost = {k: frozenset(a for a in v if isinstance(a[1], int)) for k, v in res["ostores"].items()}
            ost = {k: v for k, v in ost.items() if v}
            if ost and an.storers.get(r) != ost:
                an.storers[r] = ost
                todo.append(r)
                seen_targets.discard(r)
            # pointer parked in a global: every function that references the global is analysed too
            for c in res["caches"]:
                if c["kind"] == "global" and isinstance(c["obj"], int):
                    an.gmap.setdefault(c["addr"], [])
                    if (c["obj"], c["off"]) not in an.gmap[c["addr"]]:
                        an.gmap[c["addr"]].append((c["obj"], c["off"]))
        for addr in sorted(set(an.gmap) - known_globals):
            known_globals.add(addr)
            for pp in ci.rip_refs(addr):
                f_ = fn_root(pp)
                if f_ is not None and f_ not in site_fns:
                    site_fns[f_].add(pp)
                    todo.append(VA_GET - img.base)            # force another round
                    seen_targets.discard(VA_GET - img.base)
        print(f"  round {rnd}: {len(site_fns)} functions with get-like sites, {len(an.getlike)} get-like, "
              f"{len(an.returners)} pointer-returning, {len(an.storers)} pointer-storing, "
              f"{len(an.gmap)} globals  [{time.time() - t0:.1f}s]")
        for t in todo:
            seen_targets.discard(t)
    # final consistent run
    an._memo.clear()
    results = {r: an.analyze(r) for r in sorted(site_fns)}

    # references to the manager global that are NOT followed by a get-like call (inlined get / other methods)
    grefs = ci.rip_refs(VA_MANAGER_GLOBAL - img.base)
    gref_fns = defaultdict(list)
    for p in grefs:
        gref_fns[fn_root(p)].append(p)
    unexplained = {f: v for f, v in gref_fns.items() if f not in site_fns and f != VA_WRAPPER - img.base}

    events, caches, escapes, gets = [], [], [], []
    seen_ev = set()
    for r, res in results.items():
        for e in res["events"]:
            k = (e["va"], e["obj"], e["off"], e["strides"], e["via"])
            if k not in seen_ev:
                seen_ev.add(k)
                events.append(e)
        caches += res["caches"]
        escapes += res["escapes"]
        gets += res["gets"]

    def dedup(lst, keyf):
        seen, out = set(), []
        for x in lst:
            k = keyf(x)
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out
    caches = dedup(caches, lambda c: (c["va"], c["obj"], c["off"]))
    escapes = dedup(escapes, lambda c: (c["va"], c["obj"], c["kind"]))
    gets = dedup(gets, lambda c: c["va"])
    print(f"  pass 1: {len(gets)} get sites ({sum(1 for g_ in gets if not g_['idx'])} unknown idx), "
          f"{len(events)} pointer-relative accesses, {len(caches)} pointer stores, {len(escapes)} escapes")

    # ---- pass 2: cached pointers
    kmap, gmap = defaultdict(set), defaultdict(set)
    for c in caches:
        if not isinstance(c["obj"], int):
            continue
        if c["kind"] == "field":
            kmap[c["K"]].add((c["obj"], c["off"]))
        elif c["kind"] == "global":
            gmap[c["addr"]].add((c["obj"], c["off"]))
    an.kmap = {k: sorted(v) for k, v in kmap.items()}
    an.gmap = {k: sorted(v) for k, v in gmap.items()}
    k_stats = {}
    cached_events = []
    rejected = []
    if not args.no_cache_pass:
        cand_fns = defaultdict(set)
        for K in sorted(an.kmap):
            hits = find_k_candidates(img, ci, K)
            fns = {fn_root(h) for h in hits} - {None}
            k_stats[K] = dict(K=K, objects=[reg[o]["name"] for o, _ in an.kmap[K]], n_load_sites=len(hits),
                              n_functions=len(fns), scanned=len(fns) <= MAX_K_FUNCS)
            if len(fns) > MAX_K_FUNCS:
                print(f"    K={K:#x}: {len(fns)} candidate functions > {MAX_K_FUNCS}; NOT scanned")
                continue
            for f in fns:
                cand_fns[f].add(K)
        for addr in an.gmap:
            for p in ci.rip_refs(addr):
                f = fn_root(p)
                if f is not None:
                    cand_fns[f].add(("G", addr))
        print(f"  pass 2: {len(an.kmap)} cached K offsets, {len(an.gmap)} cached globals -> "
              f"{len(cand_fns)} candidate functions  [{time.time() - t0:.1f}s]")
        an._memo.clear()
        for n, f in enumerate(sorted(cand_fns)):
            res = an.analyze(f, kmode=True, limit=2)      # heuristic pass: keep it shallow
            groups = defaultdict(list)
            for e in res["events"]:
                if e["via"].startswith(("K:", "G:")) and isinstance(e["obj"], int):
                    groups[(e["via"], e["obj"])].append(e)
            for (via, obj), evs in groups.items():
                lay = layouts.get(reg[obj]["type"]) if obj in reg else None
                if lay is None:
                    continue
                reads = [e for e in evs if "r" in e["acc"]]
                fits = [all(a["fit"] and a["field"] for a in attribute(lay, e)) for e in evs]
                ok = bool(reads) and all(fits) and not any(e["acc"] != "r" for e in evs)
                if ok:
                    for e in evs:
                        e["n_fit_in_fn"] = len(evs)
                    cached_events += evs
                else:
                    rejected.append(dict(fn=f, via=via, obj=obj, n=len(evs), n_fit=sum(fits)))
            if n and n % 1000 == 0:
                print(f"    ... {n}/{len(cand_fns)}  [{time.time() - t0:.1f}s]")
        cached_events = dedup(cached_events, lambda e: (e["va"], e["obj"], e["off"], e["via"]))
        print(f"  pass 2: {len(cached_events)} accepted cached reads, {len(rejected)} candidate (fn,K,obj) groups rejected")

    # ---- labels
    labels = {}
    if EXE_MAP.exists():
        try:
            em = json.loads(EXE_MAP.read_text(encoding="utf-8"))
            for cname, vts in em["classes"].items():
                for vt in vts:
                    for i, mth in enumerate(vt["methods"]):
                        labels.setdefault(mth, f"{cname}::vf{i}")
        except Exception as ex:                                  # labels are cosmetic
            print(f"  (exe_map labels unavailable: {ex})")

    def fn_label(r):
        return labels.get(r)

    # ---- pointer stores: which ones does the object mechanism follow?
    def has_direct_callers(fn):
        return bool(ci.callers(fn))

    for c in caches:
        if c["kind"] == "global":
            c["followed"] = True
            c["why"] = "global: every function referencing it is analysed (readers get status 'cached')"
        elif c["kind"] == "field" and c.get("into"):
            if c["depth"] > 0 or has_direct_callers(c["fn"]):
                c["followed"] = True
                c["why"] = ("stored into an object the function was handed (" + ",".join(c["into"]) + "): applied in every "
                            "direct caller; callers that do not own the object emit a 'stored-by-callee' escape")
            else:
                c["followed"] = False
                c["why"] = "stored into an argument object of a function with no direct callers (virtual / indirect)"
        else:
            c["followed"] = False
            c["why"] = "stored through a pointer this analysis does not track (heap / member object): reloads not followed"

    # ---- struct fingerprint of the unknown-idx sites (REPORTED, never promoted to 'read')
    type_objs = defaultdict(list)
    for idx_, info_ in reg.items():
        if info_["type"]:
            type_objs[info_["type"]].append(info_["name"])
    unknown_events = defaultdict(list)
    for e in events:
        if not isinstance(e["obj"], int):
            unknown_events[e["obj"][1]].append(e)

    best_fit = {}

    def fingerprint(evs):
        body = [e for e in evs if not (0 <= e["off"] < 8 and not e["strides"]) and "r" in e["acc"]]
        if len({e["off"] for e in body}) < 3:
            return None                                  # too few distinct offsets to mean anything
        out = []
        ratios = []
        for tname, lay in layouts.items():
            nfit = sum(1 for e in body if all(a_["fit"] and a_["field"] for a_ in attribute(lay, e)))
            ratios.append((nfit / len(body), tname))
            if nfit == len(body):
                out.append(tname)
        best_fit[id(evs)] = [f"{t}:{r:.2f}" for r, t in sorted(ratios, reverse=True)[:3]]
        return out

    site_types = {}                                       # site va -> candidate type list / None
    cand_sites = defaultdict(list)                        # type -> [site va] whose every access fits the type
    for g_ in gets:
        if g_["idx"] or g_["fn"] in an.getlike:
            continue
        ft = fingerprint(unknown_events.get(g_["va"], []))
        site_types[g_["va"]] = ft
        for tname in ft or []:
            cand_sites[tname].append(g_["va"])

    # ---- assemble per object
    per_obj_events = defaultdict(list)
    for e in events:
        if isinstance(e["obj"], int):
            per_obj_events[e["obj"]].append(e)
    for e in cached_events:
        per_obj_events[e["obj"]].append(e)

    objects = {}
    summary = defaultdict(int)
    n_unl_cand = n_unread_cand = 0
    for idx in range(count):
        info = reg[idx]
        lay = layouts.get(info["type"]) if info["type"] else None
        o_gets = [g_ for g_ in gets if idx in g_["idx"]]
        o_esc = [x for x in escapes if x["obj"] == idx]
        o_caches = [c for c in caches if c["obj"] == idx]
        located = bool(o_gets) or bool(per_obj_events.get(idx))
        fields = {}
        if lay:
            for c, f in lay.fields.items():
                fields[c] = dict(object=info["name"], type=info["type"], path=c, soff=f["soff"], size=f["size"],
                                 kind=f["kind"], dims=f["dims"], status="unread" if located else "unlocated",
                                 readers=[], note=None)
        unmapped, writes = [], []
        for e in per_obj_events.get(idx, []):
            if lay is None:
                continue
            via_cached = e["via"].startswith(("K:", "G:"))
            via_obj = ">[obj+" in e["via"]
            via_frame = ">[frame+" in e["via"]
            for a in attribute(lay, e):
                rd = dict(va=f"{e['va']:#x}", fn=f"{e['fn'] + img.base:#x}", insn=e["insn"], via=e["via"])
                if fn_label(e["fn"]):
                    rd["fn_name"] = fn_label(e["fn"])
                if e.get("entry"):
                    rd["via"] += f" arg-followed ({e['entry']})"
                if a.get("elem") not in (None, "*"):
                    rd["elem"] = a["elem"]
                if a.get("elem") == "*":
                    rd["indexed"] = True
                if a.get("note") and a["note"] != "indexed":
                    rd["note"] = a["note"]
                if a["field"] is None:
                    if a["note"] != "vtable/header":
                        unmapped.append(rd | dict(off=f"{e['off']:#x}"))
                    continue
                if not a["fit"]:
                    rd["misfit"] = "access width/kind/alignment does not match the decoded field"
                if e["acc"] == "w":
                    writes.append(rd | dict(field=a["field"]))
                    continue
                f = fields[a["field"]]
                if not a["fit"]:
                    rd["confidence"] = "low"
                elif via_cached or via_frame:
                    rd["confidence"] = "medium"
                elif e.get("entry") or via_obj:
                    rd["confidence"] = "medium-high"
                else:
                    rd["confidence"] = "high"
                f["readers"].append(rd)
                if via_cached:
                    if f["status"] in ("unread", "unlocated"):
                        f["status"] = "cached"
                else:
                    f["status"] = "read"
        for f in fields.values():
            f["readers"].sort(key=lambda r_: r_["va"])
            if f["status"] == "cached":
                f["note"] = "only reached through a cached pointer (offset collisions possible) - see readers"
        # unlocated objects: what the fingerprinted unknown-idx sites read at this offset (NOT a status)
        cs = cand_sites.get(info["type"], []) if info["type"] else []
        if lay and cs:
            for sva in cs:
                for e in unknown_events.get(sva, []):
                    if "r" not in e["acc"]:
                        continue
                    for a in attribute(lay, e):
                        if a["field"] and a["fit"]:
                            f = fields[a["field"]]
                            cr = f.setdefault("candidate_readers", [])
                            if len(cr) < 8 and not any(r_["va"] == f"{e['va']:#x}" for r_ in cr):
                                cr.append(dict(va=f"{e['va']:#x}", fn=f"{e['fn'] + img.base:#x}", insn=e["insn"],
                                               site=f"{sva:#x}"))
            for f in fields.values():
                if f["status"] not in ("unlocated", "unread"):
                    f.pop("candidate_readers", None)
                elif f.get("candidate_readers"):
                    f["note"] = ("this offset is read at unknown-idx get() site(s) whose whole access pattern fits this "
                                 "struct type; WHICH object is fetched there is decided at runtime, so this proves "
                                 "nothing - but it is why 'unread' / 'unlocated' must not be read as 'inert' here")
                    if f["status"] == "unlocated":
                        n_unl_cand += 1
                    else:
                        n_unread_cand += 1
        unf = [x for x in o_esc if not x["followed"]]
        n_external = sum(1 for x in unf if x.get("external"))
        n_unfollowed = sum(1 for x in unf if x.get("certain", True) and not x.get("external"))
        n_possible = len(unf) - n_unfollowed - n_external
        n_stores_unf = sum(1 for c in o_caches if not c["followed"])
        if not lay:
            note = "no decoded struct type"
            conf = None
        elif not located:
            note = ("UNLOCATED: no constant-idx get() site and no other pointer source was found - the idx is computed at "
                    "runtime (or the object is never fetched). Fields are 'unlocated', which says NOTHING about liveness.")
            if cs:
                note += (f" {len(cs)} unknown-idx site(s) read a struct whose layout fits type '{info['type']}' (not "
                         f"necessarily only this type): see candidate_sites / candidate_readers.")
            conf = None
        elif n_unfollowed or n_stores_unf:
            note = (f"{n_unfollowed} unfollowed pointer escapes, {n_stores_unf} unfollowed pointer stores: a reader behind "
                    f"them would be missed, so 'unread' here is REDUCED confidence")
            conf = "reduced"
        else:
            note = "every tracked pointer was followed to the end (into direct callees and through context objects)"
            conf = "high"
        st = defaultdict(int)
        for f in fields.values():
            st[f["status"]] += 1
            summary[f["status"]] += 1
            if f["status"] == "unread":
                summary["unread_" + conf] += 1
        esc_out = [dict(va=f"{x['va']:#x}", fn=f"{x['fn'] + img.base:#x}", kind=x["kind"], insn=x["insn"],
                        followed=x["followed"], certain=x.get("certain", True), why=x.get("why"),
                        external=x.get("external")) for x in o_esc]
        esc_unf = [x for x in esc_out if not x["followed"]]
        esc_fol = [x for x in esc_out if x["followed"]]
        objects[info["name"]] = dict(
            idx=idx, type=info["type"], json=info["json"], struct_size=lay.size if lay else None,
            located=located, unread_confidence=conf,
            stats=dict(n_fields=len(fields), read=st["read"], cached=st["cached"], unread=st["unread"],
                       unlocated=st["unlocated"],
                       n_get_sites=len(o_gets), n_unknown_idx_sites=None,
                       n_pointer_escapes=len(o_esc), n_escapes_unfollowed=n_unfollowed,
                       n_possible_frame_escapes_unfollowed=n_possible, n_escapes_to_imports=n_external,
                       n_pointer_stores=len(o_caches), n_pointer_stores_unfollowed=n_stores_unf,
                       n_unmapped_reads=len(unmapped), n_writes=len(writes)),
            note=note,
            get_sites=[dict(va=f"{g_['va']:#x}", fn=f"{g_['fn'] + img.base:#x}", fn_name=fn_label(g_["fn"])) for g_ in o_gets],
            candidate_sites=[f"{v:#x}" for v in cs],
            escapes=esc_unf + esc_fol[:150], n_followed_escapes_total=len(esc_fol),
            pointer_stores=[dict(va=f"{c['va']:#x}", fn=f"{c['fn'] + img.base:#x}", insn=c["insn"], kind=c["kind"],
                                 K=(f"{c['K']:#x}" if c["kind"] == "field" else None),
                                 addr=(f"{c['addr'] + img.base:#x}" if c["kind"] == "global" else None),
                                 followed=c["followed"], why=c["why"]) for c in o_caches],
            unmapped_reads=unmapped, writes=writes,
            fields=sorted(fields.values(), key=lambda f: f["soff"]))

    unknown_sites = []
    for g_ in gets:
        if g_["idx"]:
            continue
        evs = unknown_events.get(g_["va"], [])
        offs = sorted({e["off"] for e in evs})
        ft = site_types.get(g_["va"])
        unknown_sites.append(dict(va=f"{g_['va']:#x}", fn=f"{g_['fn'] + img.base:#x}", fn_name=fn_label(g_["fn"]),
                                  idx_from_arg=g_.get("idx_from_arg"),
                                  forwarder=(g_["fn"] in an.getlike),
                                  offsets_read=[f"{o:#x}" for o in offs][:64],
                                  n_accesses=len(evs),
                                  fitting_types=ft, best_fit=best_fit.get(id(evs)),
                                  fingerprint=("too few distinct offsets" if ft is None else
                                               "no decoded type fits every access" if not ft else
                                               "unique" if len(ft) == 1 else "ambiguous"),
                                  candidate_objects=(type_objs[ft[0]] if ft is not None and len(ft) == 1 else None)))
    n_unknown_real = sum(1 for u in unknown_sites if not u["forwarder"])
    for o in objects.values():
        o["stats"]["n_unknown_idx_sites"] = n_unknown_real

    # manager references that are not a get(): which ConstantManager method do they call, and what happens to rax?
    mgr_other = []
    for f_, refs in unexplained.items():
        for pp in refs:
            row = dict(fn=(f"{f_ + img.base:#x}" if f_ is not None else None), ref=f"{pp + img.base:#x}")
            body = img.disasm(pp - 3, 0x40)
            for i_, ins in enumerate(body):
                if ins.mnemonic == "call":
                    row["calls"] = ins.op_str
                    row["after_call"] = [f"{x.mnemonic} {x.op_str}" for x in body[i_ + 1:i_ + 3]]
                    break
                if ins.mnemonic in ("ret", "jmp"):
                    break
            if "calls" not in row and body and body[0].mnemonic == "mov" and "rip" in body[0].op_str.split(",")[0]:
                row["calls"] = None
                row["note"] = "WRITES the manager global (create/destroy path)"
            mgr_other.append(row)

    located_objs = [o for o in objects.values() if o["located"]]
    n_located = len(located_objs)
    all_unf = [x for x in escapes if not x["followed"] and isinstance(x["obj"], int)]
    why_hist = defaultdict(int)
    for x in all_unf:
        if x.get("certain", True) and not x.get("external"):
            why_hist[x.get("why") or "?"] += 1
    doc = dict(
        meta=dict(generated=time.strftime("%Y-%m-%d %H:%M"), exe=str(args.exe), tool="tools/dt270_liveness.py",
                  manager_global=f"{VA_MANAGER_GLOBAL:#x}", get=f"{VA_GET:#x}", wrapper=f"{VA_WRAPPER:#x}",
                  registration_table=f"{table_va:#x}", n_objects=count, max_depth=MAX_DEPTH,
                  semantics=dict(
                      read="an instruction reads the field via a pointer proven to come from get(idx) - directly, through a direct callee that was handed the pointer, or through a context object the pointer was stored in and reloaded from along direct calls; does NOT prove the value affects gameplay (a load can be dead)",
                      cached="only reached via a pointer reloaded from an object field/global where a get() result was stored; offset collisions possible (medium confidence)",
                      unread="the object WAS located and its pointer flow followed, and no reader was found. Trust it only as far as the object's unread_confidence: 'high' = nothing escaped the analysis; 'reduced' = n_escapes_unfollowed / n_pointer_stores_unfollowed > 0, a reader may hide behind them",
                      escapes="n_escapes_unfollowed counts (object, call site) pairs where a tracked pointer - or an object PROVEN to hold it - reaches an indirect call. n_possible_frame_escapes_unfollowed: the pointer merely sits in a stack slot above a frame address that reaches an indirect call (usually an unrelated spill; not counted against confidence). n_escapes_to_imports: passed to an OS/CRT import.",
                      unlocated="no get() site / pointer source for this object was found at all (runtime-computed idx). NOT evidence of anything; candidate_readers are struct-fingerprint hints, unproven")),
        summary=dict(n_objects=count, n_objects_located=n_located, n_objects_unlocated=count - n_located,
                     n_objects_with_get_sites=sum(1 for o in objects.values() if o["stats"]["n_get_sites"]),
                     n_objects_unread_confidence_high=sum(1 for o in located_objs if o["unread_confidence"] == "high"),
                     n_objects_unread_confidence_reduced=sum(1 for o in located_objs if o["unread_confidence"] == "reduced"),
                     n_fields=sum(v for k, v in summary.items() if not k.startswith("unread_")),
                     read=summary["read"], cached=summary["cached"],
                     unread=summary["unread"], unread_high_confidence=summary["unread_high"],
                     unread_reduced_confidence=summary["unread_reduced"],
                     unread_with_candidate_reader_at_unknown_idx_site=n_unread_cand,
                     unlocated=summary["unlocated"], unlocated_with_candidate_reader=n_unl_cand,
                     fields_in_located_objects=sum(o["stats"]["n_fields"] for o in located_objs),
                     n_get_like_functions=len(an.getlike), n_pointer_returning_functions=len(an.returners),
                     n_pointer_storing_functions=len(an.storers),
                     n_get_sites=len(gets), n_unknown_idx_sites=n_unknown_real,
                     n_unknown_idx_sites_fingerprint_unique=sum(1 for u in unknown_sites if u["fingerprint"] == "unique"),
                     n_forwarder_sites=len(unknown_sites) - n_unknown_real,
                     n_pointer_escapes=len(escapes),
                     n_escapes_unfollowed=sum(1 for x in all_unf if x.get("certain", True) and not x.get("external")),
                     n_escapes_unfollowed_unique_call_sites=len({x["va"] for x in all_unf
                                                                 if x.get("certain", True) and not x.get("external")}),
                     n_possible_frame_escapes_unfollowed=sum(1 for x in all_unf if not x.get("certain", True)
                                                             and not x.get("external")),
                     n_escapes_to_imports=sum(1 for x in all_unf if x.get("external")),
                     escapes_unfollowed_by_reason=dict(why_hist),
                     n_pointer_stores=len(caches), n_pointer_stores_unfollowed=sum(1 for c in caches if not c["followed"]),
                     n_manager_global_refs=len(grefs),
                     n_functions_touching_manager_without_get=len(unexplained),
                     n_cached_reads_accepted=len(cached_events), n_cached_groups_rejected=len(rejected),
                     runtime_s=round(time.time() - t0, 1)),
        get_like={f"{k + img.base:#x}": v for k, v in an.getlike.items()},
        pointer_returning={f"{k + img.base:#x}": sorted({reg[a[1]]["name"] for a in v}) for k, v in an.returners.items()},
        pointer_storing={f"{k + img.base:#x}": sorted({f"[{n}+{o_:#x}] <- {reg[a[1]]['name']}" for (n, o_), v in d_.items() for a in v})
                         for k, d_ in an.storers.items()},
        cached_offsets=[k_stats[k] | dict(K=f"{k:#x}") for k in sorted(k_stats)],
        cached_globals=[dict(addr=f"{a + img.base:#x}", objects=[reg[o]["name"] for o, _ in v]) for a, v in an.gmap.items()],
        unknown_idx_sites=unknown_sites,
        orphan_call_sites=[dict(va=f"{s + img.base:#x}", target=f"{t + img.base:#x}") for s, t in orphan_sites],
        manager_refs_without_get=mgr_other,
        objects=objects)
    OUT_LIVENESS.parent.mkdir(parents=True, exist_ok=True)
    OUT_LIVENESS.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    sm = doc["summary"]
    print(f"wrote {OUT_LIVENESS} ({OUT_LIVENESS.stat().st_size:,} B) in {sm['runtime_s']}s")
    print(f"  objects: {count}  located {n_located}  UNLOCATED {count - n_located}")
    print(f"  fields: {sm['n_fields']}  read {sm['read']}  cached {sm['cached']}  unread {sm['unread']} "
          f"(high-confidence {sm['unread_high_confidence']}, reduced {sm['unread_reduced_confidence']}; "
          f"{sm['unread_with_candidate_reader_at_unknown_idx_site']} of them have an unproven candidate reader)  "
          f"unlocated {sm['unlocated']} ({sm['unlocated_with_candidate_reader']} with a fingerprint candidate reader)")
    print(f"  get sites {sm['n_get_sites']}  unknown-idx {sm['n_unknown_idx_sites']} "
          f"({sm['n_unknown_idx_sites_fingerprint_unique']} with a unique struct fingerprint)  "
          f"escapes {sm['n_pointer_escapes']} ({sm['n_escapes_unfollowed']} unfollowed at "
          f"{sm['n_escapes_unfollowed_unique_call_sites']} call sites, "
          f"+{sm['n_possible_frame_escapes_unfollowed']} possible frame-window, "
          f"{sm['n_escapes_to_imports']} into imports)  "
          f"pointer stores {sm['n_pointer_stores']} ({sm['n_pointer_stores_unfollowed']} unfollowed)")
    for why, n in sorted(why_hist.items(), key=lambda kv: -kv[1]):
        print(f"    unfollowed because: {why[:100]}: {n}")
    return 0


# ----------------------------------------------------------------------------------------
# show
# ----------------------------------------------------------------------------------------

def load_doc():
    if not OUT_LIVENESS.exists():
        sys.exit(f"{OUT_LIVENESS} missing - run: python tools/dt270_liveness.py build")
    return json.loads(OUT_LIVENESS.read_text(encoding="utf-8"))


def show(args) -> int:
    doc = load_doc()
    o = doc["objects"].get(args.object)
    if o is None:
        close = [n for n in doc["objects"] if args.object.lower() in n.lower()]
        sys.exit(f"no object '{args.object}'" + (f"; did you mean {close[:8]}" if close else ""))
    st = o["stats"]
    print(f"{args.object}  idx={o['idx']:#x}  type={o['type']}  struct_size={o['struct_size']:#x}" if o["struct_size"]
          else f"{args.object}  idx={o['idx']:#x}  (no decoded type)")
    print(f"  fields {st['n_fields']}: read {st['read']}  cached {st['cached']}  unread {st['unread']}  "
          f"unlocated {st.get('unlocated', 0)}   get sites {st['n_get_sites']}  "
          f"escapes {st['n_pointer_escapes']} ({st['n_escapes_unfollowed']} unfollowed"
          f", +{st.get('n_possible_frame_escapes_unfollowed', 0)} possible)  "
          f"pointer stores {st['n_pointer_stores']} ({st.get('n_pointer_stores_unfollowed', 0)} unfollowed)  "
          f"unmapped reads {st['n_unmapped_reads']}")
    print(f"  located: {o.get('located')}   confidence of 'unread' for this object: {o.get('unread_confidence')}")
    print(f"  note: {o['note']}")
    print(f"  {'soff':>7} {'sz':>3} {'kind':6} {'status':9} {'#rd':>3}  {'path':52} first reader")
    for f in o["fields"]:
        if args.status and f["status"] != args.status:
            continue
        dims = "".join(f"[{d['count']}]" for d in f["dims"])
        rd = f["readers"][0] if f["readers"] else None
        first = f"{rd['va']} {rd['insn']}" if rd else ""
        if not rd and f.get("candidate_readers"):
            c_ = f["candidate_readers"][0]
            first = f"(candidate, unproven: {c_['va']} {c_['insn']})"
        print(f"  {f['soff']:#7x} {f['size']:>3} {f['kind']:6} {f['status']:9} {len(f['readers']):>3}  "
              f"{(f['path'] + ('  ' + dims if dims else ''))[:52]:52} {first}")
        if args.verbose:
            for r in f["readers"]:
                extra = " ".join(f"{k}={r[k]}" for k in ("elem", "indexed", "confidence", "note", "misfit", "fn_name") if r.get(k))
                print(f"            {r['va']}  fn {r['fn']}  {r['insn']:44} via {r['via']}  {extra}")
    if o["unmapped_reads"]:
        print("  reads at offsets the JSON loader never writes (padding / derived members?):")
        for r in o["unmapped_reads"][:20]:
            print(f"            {r['va']}  +{r['off']}  {r['insn']}")
    return 0


def sites(args) -> int:
    doc = load_doc()
    o = doc["objects"].get(args.object)
    if o is None:
        sys.exit(f"no object '{args.object}'")
    print(f"{args.object} idx={o['idx']:#x}")
    for title, key in (("get sites", "get_sites"), ("pointer escapes", "escapes"), ("pointer stores", "pointer_stores"),
                       ("writes", "writes")):
        print(f"  {title}: {len(o[key])}")
        for x in o[key]:
            print("    " + "  ".join(f"{k}={v}" for k, v in x.items() if v is not None))
    return 0


# ----------------------------------------------------------------------------------------
# verify - acceptance tests against hand-proven ground truth
# ----------------------------------------------------------------------------------------

# (object, struct offset, name fragment, expectation, expected reader addresses, reader-function, note)
#   expectation: 'read' | 'unread' | 'not-unread'
#   an expected address passes when it is (a) a reader instruction of the field, or (b) a get() call
#   site whose function contains a reader of the field - (b) is reported as such with the real
#   reader, never silently; "~addr" = a reader within 0x40 bytes.
ACCEPTANCE = [
    ("trap", 0x38, "ballControlRate", "read", ["0x144079c38", "0x144079dc3", "0x14407aa63"], None, None),
    ("trap", 0x3C, "ballControlWeekFootDownLimit", "read", ["0x144079163"], None, None),
    ("shoot", 0x15C, "normal_dy.gageMax", "read", ["0x143fdfad3"], None, None),
    ("shoot", 0x160, "normal_dy.gageMin", "read", [], None, None),
    ("shoot", 0xB4, "control_dy.gageMin", "read", [], None, None),
    ("shoot", 0x1E0, "powerfullShootGageMin99", "read", ["0x143eeef80"], None, None),
    ("ball", 0x208, "magnusRate", "read", [], "0x144089620", "air-force routine"),
    ("ball", 0x8, "airRegistNormal", "read", [], "0x144089620", "air-force routine"),
    ("ball", 0x58, "boundRate", "read", [], "0x14408d0f0", "integrator"),
    ("basePosition", 0x188, "forceDashDistOffence", "read", ["0x143da9414"], None, None),
    ("basePosition", 0x240, "marginPredictionFrameBase", "read", ["0x143da6533"], None, None),
    ("moveMatching", None, "accRateDif180", "read", [], None, None),
    ("moveMatching", None, "decMaxSpeedR", "read", [], None, None),
    ("basePosition", 0x2BC, "pressRate", "unread", [], None, None),
    ("passget", 0x44, "defence.secMin", "unread", [], None, None),
    ("passget", 0x40, "defence.secMax", "unread", [], None, None),
    ("basePosition", 0x284, "minWidth", "not-unread", ["0x143e870d8"], None, "via the pointer cached at [ctx+0xf0]"),
    ("basePosition", 0x28C, "minWidth_stratagy_defensive", "not-unread", ["0x143e870e0"], None, "via [ctx+0xf0]"),
    ("basePosition", 0x154, "dfLineCloseRate", "not-unread", ["0x143e87710"], None, "via [ctx+0xf0]"),
    ("basePosition", 0x218, "lastLineCloseMaxRate", "not-unread", ["0x143e872c5"], None, "via [ctx+0xf0]"),
    ("basePosition", 0x318, "spaceCoverRate", "not-unread", ["~0x143e8608b"], None, "via [ctx+0xf0]"),
    ("basePosition", 0x184, "forceDashDistDefence", "read", ["0x143da9420"], None,
     "kept limitation: the load at 0x143da9420 is DEAD, 'read' is still the correct output"),
]


def verify(args) -> int:
    doc = load_doc()
    img = None

    def dis(va, n=5):
        nonlocal img
        if img is None:
            img = Image(Path(doc["meta"]["exe"]))
        out = []
        for ins in img.disasm(va - img.base, 0x40)[:n]:
            out.append(f"          {ins.address:#x}  {ins.mnemonic} {ins.op_str}")
        return "\n".join(out)

    rows = []
    for obj, soff, frag, want, addrs, want_fn, note in ACCEPTANCE:
        name = f"{obj}.{frag}" + (f" +{soff:#x}" if soff is not None else "")
        o = doc["objects"].get(obj)
        if o is None:
            rows.append((name, False, "object not in output"))
            continue
        fs = [f for f in o["fields"] if frag in f["path"] and (soff is None or f["soff"] == soff)]
        if not fs:
            at = [f["path"] for f in o["fields"] if f["soff"] == soff]
            rows.append((name, False, f"no field '{frag}' at {soff:#x}" if soff is not None else f"no field '{frag}'"
                         + (f"; the field at that offset is {at}" if at else "")))
            continue
        ok_all, details = True, []
        for f in fs:
            st = f["status"]
            ok = (st == want) if want != "not-unread" else (st in ("read", "cached"))
            d = [f"{f['path']} status={st}"]
            rvas = {r["va"] for r in f["readers"]}
            for a in addrs:
                near = a.startswith("~")
                av = int(a.lstrip("~"), 16)
                if near:
                    hit = [r for r in f["readers"] if abs(int(r["va"], 16) - av) <= 0x40]
                    if hit:
                        d.append(f"reader near {av:#x}: {hit[0]['va']} {hit[0]['insn']}")
                    else:
                        ok = False
                        d.append(f"NO reader near {av:#x}; exe there:\n{dis(av)}")
                elif f"{av:#x}" in rvas:
                    d.append(f"reader {av:#x} found")
                else:
                    site = next((g for g in o["get_sites"] if int(g["va"], 16) == av), None)
                    same_fn = [r for r in f["readers"] if site and r["fn"] == site["fn"]]
                    if same_fn:
                        d.append(f"{av:#x} is the get() CALL SITE, not a load; the field is read in the same function "
                                 f"({site['fn']}) at {same_fn[0]['va']}: {same_fn[0]['insn']}")
                    else:
                        ok = False
                        d.append(f"reader {av:#x} MISSING; exe there:\n{dis(av)}")
            if want_fn:
                hit = [r for r in f["readers"] if r["fn"] == want_fn]
                if hit:
                    d.append(f"read in {want_fn}: {hit[0]['va']} {hit[0]['insn']} (via {hit[0]['via']})")
                else:
                    ok = False
                    d.append(f"no reader inside {want_fn}")
            ok_all &= ok
            details.append("; ".join(d))
        rows.append((name + (f"  [{note}]" if note else ""), ok_all, " | ".join(details)))

    # honesty: a field of an object with no located pointer source must not be 'unread'
    bad = [n for n, o in doc["objects"].items()
           if not o.get("located") and any(f["status"] == "unread" for f in o["fields"])]
    rows.append(("honesty: no 'unread' field in an unlocated object", not bad,
                 f"{sum(1 for o in doc['objects'].values() if not o.get('located'))} unlocated objects, "
                 f"{len(bad)} of them carry 'unread' fields {bad[:5]}"))
    missing = [n for n, o in doc["objects"].items()
               if "n_escapes_unfollowed" not in o["stats"] or "n_pointer_stores_unfollowed" not in o["stats"]]
    rows.append(("honesty: every object carries its unfollowed-escape / unfollowed-store counts", not missing,
                 f"{len(missing)} objects without the counters"))
    lo = [n for n, o in doc["objects"].items() if o.get("located") and o.get("unread_confidence") not in ("high", "reduced")]
    rows.append(("honesty: every located object states the confidence of its 'unread' verdicts", not lo, f"{len(lo)} missing"))

    npass = sum(1 for _n, ok, _d in rows if ok)
    for n, ok, d in rows:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}\n         {d}")
    print(f"{npass}/{len(rows)} passed")
    if args.json:
        Path(args.json).write_text(json.dumps([dict(test=n, passed=ok, detail=d) for n, ok, d in rows], indent=1),
                                   encoding="utf-8")
    return 0 if npass == len(rows) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="analyse the exe -> build/dt270_liveness.json")
    b.add_argument("--exe", default=str(EXE))
    b.add_argument("--no-cache-pass", action="store_true", help="skip the cached-pointer second pass")
    b.set_defaults(func=build)
    s = sub.add_parser("show", help="per-field table for one object")
    s.add_argument("object")
    s.add_argument("-v", "--verbose", action="store_true", help="list every reader instruction")
    s.add_argument("--status", choices=["read", "cached", "unread", "unlocated"])
    s.set_defaults(func=show)
    s2 = sub.add_parser("sites", help="get sites / escapes / pointer stores of one object")
    s2.add_argument("object")
    s2.set_defaults(func=sites)
    v = sub.add_parser("verify", help="acceptance tests against hand-proven ground truth (reads the build output)")
    v.add_argument("--json", help="also write the results to this file")
    v.set_defaults(func=verify)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
