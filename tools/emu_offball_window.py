#!/usr/bin/env python3
"""
emu_offball_window.py - EMULATION PROOF for the off-ball RUN COMMITMENT WINDOW re-aims.

Both images are opened READ-ONLY and every candidate disp32 is overlaid IN THE EMULATOR ONLY.
Nothing on disk is written.

WHAT IT PROVES
  ActionSelectorChanceSpaceRun::vf3 (0x143df72d0) and ActionSelectorDiagonalRun::vf3 (0x143e05130)
  both compute the protected-run window the same way:

      call 0x14533ea80           ; xmm0 = fps   (the whole function is 'movss xmm0,[rip->fps]; ret')
      mulss xmm0,[rip->0.2f]     ; 0x143df73a8 / 0x143e051b2   <- THE RE-AIM SITE
      addss xmm0,[rip->0.5f]     ; rounding
      cvttss2si rcx/rax, xmm0    ; threshold, in FRAMES
      cmp ebx, rcx/rax           ; ebx = elapsed = [rec+8]-[rec+4] of the per-slot action record

  and below the threshold the run is protected from the timer-deferred abort causes.
  This harness executes those four instructions from the game's own bytes at 60 fps, with each
  candidate constant-pool cell overlaid on the mulss disp32, and prints the resulting threshold.

    python tools/emu_offball_window.py
"""
from __future__ import annotations
import struct
from pathlib import Path

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_MEM_READ_UNMAPPED,
                     UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED)
from unicorn import x86_const as X

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from emu_selector_order import Img, INSTALLED, PRISTINE, STACK, STACK_SZ, RET_MAGIC

FPS_GETTER = 0x14533EA80

SITES = {
    "ChanceSpaceRun::vf3": (0x143DF73A8, 0x143DF73BD, X.UC_X86_REG_RCX),
    "DiagonalRun::vf3":    (0x143E051B2, 0x143E051C7, X.UC_X86_REG_RAX),
}

CELLS = [("0.2f  STOCK", 0x1478501C0), ("0.5f", 0x147850248), ("1.0f", 0x1478502B8),
         ("1.5f", 0x147850340), ("2.0f", 0x147850490), ("3.0f", 0x1478504E8)]


class Mini:
    """Minimal lazy-mapping emulator: image pages on demand, one stack, no stubs needed."""

    def __init__(self, img: Img):
        self.img = img
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.mapped = set()
        self.overlays = []
        uc.mem_map(STACK, STACK_SZ)
        uc.mem_map(RET_MAGIC, 0x1000)
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED |
                    UC_HOOK_MEM_FETCH_UNMAPPED, self._unmapped)

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

    def overlay(self, va, data):
        self.overlays.append((va, bytes(data)))
        for b in {va & ~0xFFFF, (va + len(data)) & ~0xFFFF}:
            if b not in self.mapped:
                self._map_img(b)
        self.uc.mem_write(va, bytes(data))

    def threshold(self, start, stop, out_reg, fps):
        uc = self.uc
        uc.reg_write(X.UC_X86_REG_RSP, STACK + STACK_SZ // 2)
        uc.reg_write(X.UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", fps))[0])
        uc.emu_start(start, stop, count=100)
        return uc.reg_read(out_reg)


def disp_for(site_va: int, cell: int) -> bytes:
    """The 4-byte RIP disp32 that makes the 8-byte instruction at site_va read `cell`."""
    return struct.pack("<i", cell - (site_va + 8))


def main():
    for label, path in (("INSTALLED", INSTALLED), ("PRISTINE", PRISTINE)):
        img = Img(path)
        print(f"\n===== {label}")
        for name, (site, stop, reg) in SITES.items():
            on_disk = img.rd(site, 8)
            stock_ok = on_disk == b"\xf3\x0f\x59\x05" + disp_for(site, 0x1478501C0)
            print(f"  {name}  {site:#x}  bytes {on_disk.hex()}  "
                  f"{'STOCK (reads 0.2f)' if stock_ok else 'NOT STOCK'}")
            for cname, cell in CELLS:
                e = Mini(img)
                e.overlay(site + 4, disp_for(site, cell))
                t60 = e.threshold(site, stop, reg, 60.0)
                t30 = e.threshold(site, stop, reg, 30.0)
                print(f"      -> {cname:<12} cell {cell:#x} = {img.rd(cell, 4) and struct.unpack('<f', img.rd(cell, 4))[0]:<6} "
                      f"threshold @60fps = {t60:4d} frames = {t60 / 60.0:.2f} s   @30fps = {t30:3d} frames")


if __name__ == "__main__":
    main()
