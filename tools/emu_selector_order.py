#!/usr/bin/env python3
"""
emu_selector_order.py - EMULATION PROOF for the off-ball selector BIDDING ORDER.

Nothing here touches the game. Both images are opened READ-ONLY, their pages are copied lazily
into a Unicorn address space, and every candidate byte edit is overlaid IN THE EMULATOR ONLY.

WHAT IT PROVES
  The registration function match::ai::ActionSelectorManager::registerSelectors (0x143d520e0)
  appends ten (actionId, selectorPtr) pairs to the 16-byte array at mgr+0x1720 (count mgr+0x218)
  and then, as its LAST act (call at 0x143d52456), SORTS that array with the general sort
  0x143b45ce0 using comparator 0x143d520a0 (priority(a)-priority(b) via 0x1442ed810).
  The sort is an UNSTABLE quicksort, so the append order is NOT the bidding order and the outcome
  of a swap cannot be read off the source. This harness runs the game's own bytes end to end on a
  zeroed manager object and prints the resulting order, stock and for each candidate edit.

    python tools/emu_selector_order.py              # both images, stock + every candidate swap
    python tools/emu_selector_order.py --exe <path>
"""
from __future__ import annotations
import argparse, struct, sys
from pathlib import Path

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE,
                     UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_HOOK_MEM_FETCH_UNMAPPED, UcError)
from unicorn import x86_const as X

INSTALLED = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
PRISTINE = Path(r"C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE")

REGISTER = 0x143D520E0
MEMSET_THK = 0x144F8306E          # IAT thunk, called once to zero the array
MEMCPY_THK = 0x144F8307A          # IAT thunk, used by the sort to move 16-byte elements
ARRAY_OFF = 0x1720
COUNT_OFF = 0x218

MGR = 0x0000_0002_0000_0000       # synthetic manager object
MGR_SZ = 0x4000
STACK = 0x0000_0003_0000_0000
STACK_SZ = 0x100000
RET_MAGIC = 0x0000_0004_0000_0000

NAMES = {0x27: "Overlap", 0x1e: "ChanceSpaceRun", 0x1f: "CounterSpaceRun",
         0x1d: "SecondLineSpaceRun", 0x20: "LineBreak", 0x21: "DiagonalRun",
         0x26: "CenteringGet", 0x2e: "PullAway", 0x29: "GoalGet", 0x2a: "PostPlay"}

# the ten append blocks: name -> (lea disp32 VA, cmp imm8 VA, store imm32 VA, sel offset, action id)
BLOCKS = {
    "Overlap":            (0x143D52107, 0x143D52132, 0x143D5214C, 0x280,  0x27),
    "ChanceSpaceRun":     (0x143D5215E, 0x143D52182, 0x143D5219C, 0x288,  0x1e),
    "CounterSpaceRun":    (0x143D521AE, 0x143D521D2, 0x143D521EC, 0x590,  0x1f),
    "SecondLineSpaceRun": (0x143D521FE, 0x143D52222, 0x143D5223C, 0x858,  0x1d),
    "LineBreak":          (0x143D5224E, 0x143D52272, 0x143D5228C, 0xb40,  0x20),
    "DiagonalRun":        (0x143D5229E, 0x143D522C2, 0x143D522DC, 0xe08,  0x21),
    "CenteringGet":       (0x143D522EE, 0x143D52312, 0x143D5232C, 0x10e0, 0x26),
    "PullAway":           (0x143D5233E, 0x143D52362, 0x143D5237C, 0x1188, 0x2e),
    "GoalGet":            (0x143D5238E, 0x143D523B2, 0x143D523CC, 0x1450, 0x29),
    "PostPlay":           (0x143D523DE, 0x143D52402, 0x143D5241C, 0x1460, 0x2a),
}


class Img:
    def __init__(self, path: Path):
        self.path = path
        self.data = open(path, "rb").read()
        d = self.data
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
        self.size_of_image = struct.unpack_from("<I", d, pe + 24 + 56)[0]
        self.secs = []
        for i in range(nsec):
            s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
            vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
            self.secs.append((s[:8].rstrip(b"\0").decode(), va, vsize, raw, rsize))

    def read_rva(self, rva, n):
        out = bytearray(n)
        for name, sva, vsize, raw, rsize in self.secs:
            lo, hi = sva, sva + min(vsize, rsize)
            a, b = max(rva, lo), min(rva + n, hi)
            if a < b:
                out[a - rva:b - rva] = self.data[raw + (a - sva): raw + (b - sva)]
        return bytes(out)

    def rd(self, va, n):
        return self.read_rva(va - self.base, n)


class Emu:
    def __init__(self, img: Img):
        self.img = img
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        self.overlays = []
        uc.mem_map(MGR, MGR_SZ)
        uc.mem_map(STACK, STACK_SZ)
        uc.mem_map(RET_MAGIC, 0x1000)
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED |
                    UC_HOOK_MEM_FETCH_UNMAPPED, self._unmapped)
        uc.hook_add(UC_HOOK_CODE, self._code, begin=MEMSET_THK, end=MEMSET_THK)
        uc.hook_add(UC_HOOK_CODE, self._code, begin=MEMCPY_THK, end=MEMCPY_THK)

    def _map_img(self, b):
        self.uc.mem_map(b, 0x10000)
        self.uc.mem_write(b, self.img.read_rva(b - self.img.base, 0x10000))
        self.mapped.add(b)
        for va, data in self.overlays:
            if b <= va < b + 0x10000:
                self.uc.mem_write(va, data)

    def _unmapped(self, uc, access, addr, size, value, ud):
        img = self.img
        if img.base <= addr < img.base + img.size_of_image:
            for b in (addr & ~0xFFFF, (addr + size) & ~0xFFFF):
                if b not in self.mapped:
                    self._map_img(b)
            return True
        return False

    def _code(self, uc, addr, size, ud):
        # the only two imports on this path: memset(rcx,edx,r8) and memcpy(rcx,rdx,r8)
        dst = uc.reg_read(X.UC_X86_REG_RCX)
        n = uc.reg_read(X.UC_X86_REG_R8)
        if addr == MEMSET_THK:
            val = uc.reg_read(X.UC_X86_REG_EDX) & 0xFF
            uc.mem_write(dst, bytes([val]) * n)
        elif addr == MEMCPY_THK:
            src = uc.reg_read(X.UC_X86_REG_RDX)
            uc.mem_write(dst, bytes(uc.mem_read(src, n)) if n else b"")
        else:
            return
        uc.reg_write(X.UC_X86_REG_RAX, dst)
        rsp = uc.reg_read(X.UC_X86_REG_RSP)
        ret = struct.unpack("<Q", bytes(uc.mem_read(rsp, 8)))[0]
        uc.reg_write(X.UC_X86_REG_RSP, rsp + 8)
        uc.reg_write(X.UC_X86_REG_RIP, ret)

    def overlay(self, va, data):
        self.overlays.append((va, bytes(data)))
        for b in {va & ~0xFFFF, (va + len(data)) & ~0xFFFF}:
            if b not in self.mapped:
                self._map_img(b)
        self.uc.mem_write(va, bytes(data))

    def run_registration(self):
        uc = self.uc
        uc.mem_write(MGR, b"\0" * MGR_SZ)
        rsp = STACK + STACK_SZ // 2
        uc.mem_write(rsp, struct.pack("<Q", RET_MAGIC))
        uc.reg_write(X.UC_X86_REG_RSP, rsp)
        uc.reg_write(X.UC_X86_REG_RCX, MGR)
        uc.emu_start(REGISTER, RET_MAGIC, count=5_000_000)
        n = struct.unpack("<i", bytes(uc.mem_read(MGR + COUNT_OFF, 4)))[0]
        out = []
        for i in range(n):
            e = bytes(uc.mem_read(MGR + ARRAY_OFF + 16 * i, 16))
            aid = struct.unpack_from("<I", e, 0)[0]
            ptr = struct.unpack_from("<Q", e, 8)[0]
            out.append((aid, ptr - MGR))
        return out


def fmt(order):
    return " > ".join(NAMES.get(a, hex(a)) for a, _ in order)


def swap_edits(a: str, b: str):
    """Byte edits that swap the bidding blocks of selectors a and b (18 bytes, no length change)."""
    la, ca, sa, oa, ia = BLOCKS[a]
    lb, cb, sb, ob, ib = BLOCKS[b]
    return [(la, struct.pack("<I", ob)), (ca, bytes([ib])), (sa, struct.pack("<I", ib)),
            (lb, struct.pack("<I", oa)), (cb, bytes([ia])), (sb, struct.pack("<I", ia))]


def check_stock(img: Img):
    """Every block's three fields must read exactly what BLOCKS claims."""
    bad = []
    for name, (lv, cv, sv, off, aid) in BLOCKS.items():
        if struct.unpack("<I", img.rd(lv, 4))[0] != off:
            bad.append(f"{name} lea disp {lv:#x}")
        if img.rd(cv, 1)[0] != aid:
            bad.append(f"{name} cmp imm {cv:#x}")
        if struct.unpack("<I", img.rd(sv, 4))[0] != aid:
            bad.append(f"{name} store imm {sv:#x}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", type=Path, default=None)
    args = ap.parse_args()
    images = [("INSTALLED", INSTALLED), ("PRISTINE", PRISTINE)] if args.exe is None else [("EXE", args.exe)]

    candidates = [("L1 DiagonalRun <-> ChanceSpaceRun", "ChanceSpaceRun", "DiagonalRun"),
                  ("L2 CounterSpaceRun <-> ChanceSpaceRun", "ChanceSpaceRun", "CounterSpaceRun"),
                  ("L3 SecondLineSpaceRun <-> ChanceSpaceRun", "ChanceSpaceRun", "SecondLineSpaceRun"),
                  ("L4 PullAway(dead) <-> ChanceSpaceRun", "ChanceSpaceRun", "PullAway")]

    for label, path in images:
        img = Img(path)
        print(f"\n===== {label}  {path}")
        bad = check_stock(img)
        print(f"  block-field check: {'ALL 30 FIELDS MATCH' if not bad else 'MISMATCH ' + ', '.join(bad)}")
        e = Emu(img)
        stock = e.run_registration()
        print(f"  STOCK  n={len(stock):2d}  {fmt(stock)}")
        for name, a, b in candidates:
            e2 = Emu(img)
            for va, data in swap_edits(a, b):
                e2.overlay(va, data)
            got = e2.run_registration()
            ok = sorted(x for x, _ in got) == sorted(x for x, _ in stock)
            print(f"  {name:<42} n={len(got):2d} {'OK ' if ok else 'SET-CHANGED!'} {fmt(got)}")


if __name__ == "__main__":
    main()
