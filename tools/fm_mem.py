#!/usr/bin/env python3
"""
fm_mem.py — read FM24's live player data straight from process memory (what Genie Scout does).

EXPERIMENT stage: locate the in-memory player records using KNOWN ground truth (build/oracle.json:
UID -> the 46 real 1-20 attributes, from the FM HTML export). Anchor on the UID (an exact, stable
u32); then inspect the bytes around each hit to find where the attribute block lives and its stride.

    python tools/fm_mem.py scan        # find every occurrence of the oracle UIDs, hexdump context
    python tools/fm_mem.py validate --uid-off O --attr-off A --stride S   # test a hypothesis
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import sys
from ctypes import wintypes as W
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORACLE = json.loads((REPO / "build" / "oracle.json").read_text())

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_READABLE = {0x02, 0x04, 0x20, 0x40}  # R, RW, EX_R, EX_RW
PAGE_GUARD = 0x100

k32 = C.WinDLL("kernel32", use_last_error=True)
psapi = C.WinDLL("psapi", use_last_error=True)


class MBI(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("__a", W.DWORD), ("RegionSize", C.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def fm_pid() -> int:
    import os, subprocess
    proc = os.environ.get("FM_PROC", "fm")
    out = subprocess.check_output(
        ["powershell", "-c", f"(Get-Process '{proc}' -ErrorAction SilentlyContinue).Id"], text=True).strip()
    if not out:
        sys.exit(f"process '{proc}' is not running")
    return int(out.splitlines()[0])


def open_proc(pid: int):
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        sys.exit(f"OpenProcess failed ({C.get_last_error()}) — run this shell as admin")
    return h


def regions(h):
    addr = 0
    mbi = MBI()
    while k32.VirtualQueryEx(h, C.c_void_p(addr), C.byref(mbi), C.sizeof(mbi)):
        size = mbi.RegionSize
        base = mbi.BaseAddress or 0
        if (mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in PAGE_READABLE
                and not (mbi.Protect & PAGE_GUARD) and size):
            yield base, size
        nxt = base + size
        if nxt <= addr:
            break
        addr = nxt


def read(h, base, size):
    buf = (C.c_char * size)()
    got = C.c_size_t(0)
    if k32.ReadProcessMemory(h, C.c_void_p(base), buf, size, C.byref(got)):
        return bytes(buf[:got.value])
    return b""


def cmd_scan():
    pid = fm_pid()
    h = open_proc(pid)
    print(f"FM pid {pid}")
    uids = {int(u): v for u, v in ORACLE["oracle"].items()}
    needles = {struct.pack("<I", u): u for u in uids}
    hits = {u: [] for u in uids}
    scanned = 0
    for base, size in regions(h):
        if size > 512 * 1024 * 1024:
            continue
        data = read(h, base, size)
        scanned += len(data)
        for needle, u in needles.items():
            start = 0
            while True:
                i = data.find(needle, start)
                if i < 0:
                    break
                hits[u].append((base + i, data[max(0, i - 8):i + 200]))
                start = i + 1
    print(f"scanned {scanned/1e9:.2f} GB")
    for u, hs in hits.items():
        print(f"\nUID {u}: {len(hs)} occurrence(s)")
        for addr, ctx in hs[:4]:
            print(f"  @ {addr:#014x}")
            # show the 200 bytes after the UID as ints, hunting for the 1-20 attribute run
            after = ctx[8:]
            ints = list(after)
            # where does a long run of 1-20 bytes start?
            run = [j for j in range(len(ints) - 20)
                   if all(1 <= ints[j + k] <= 20 for k in range(20))]
            print(f"    hex: {ctx[:64].hex()}")
            if run:
                print(f"    20+ run of 1-20 bytes at +{8 + run[0]}: {ints[run[0]:run[0]+24]}")
    # persist hit addresses for validate step
    (REPO / "build" / "fm_mem_hits.json").write_text(json.dumps(
        {str(u): [a for a, _ in hs] for u, hs in hits.items()}))


def cmd_validate(uid_off, attr_off, stride):
    pid = fm_pid()
    h = open_proc(pid)
    hits = json.loads((REPO / "build" / "fm_mem_hits.json").read_text())
    order = ORACLE["order"]
    for u, vec in ((int(k), v) for k, v in ORACLE["oracle"].items()):
        for addr in hits.get(str(u), [])[:1]:
            rec = addr - uid_off
            data = read(h, rec + attr_off, len(order))
            got = list(data)
            match = sum(1 for a, b in zip(got, vec) if a == b)
            print(f"UID {u}: {match}/{len(order)} attrs match  got[:12]={got[:12]} exp[:12]={vec[:12]}")



def cmd_findrec():
    """Locate attribute RECORDS by exact histogram: N bytes all in 1-20 whose sorted multiset
    equals the oracle's (order-independent). Works if attributes are stored as contiguous bytes."""
    import collections
    import numpy as np
    pid = fm_pid(); h = open_proc(pid)
    order = ORACLE["order"]; N = len(order)
    targets = {int(u): tuple(sorted(v)) for u, v in ORACLE["oracle"].items()}
    tset = set(targets.values())
    print(f"pid {pid}; N={N}; {len(targets)} target histograms", flush=True)
    found = collections.defaultdict(list)
    cands = 0
    for base, size in regions(h):
        if size > 512 * 1024 * 1024: continue
        data = read(h, base, size)
        if len(data) < N: continue
        a = np.frombuffer(data, dtype=np.uint8)
        ok = (a >= 1) & (a <= 20)
        csum = np.concatenate(([0], np.cumsum(ok, dtype=np.int32)))
        starts = np.nonzero((csum[N:] - csum[:-N]) == N)[0]
        for s in starts:
            cands += 1
            sig = tuple(sorted(data[s:s+N]))
            if sig in tset:
                for u, tg in targets.items():
                    if tg == sig:
                        found[u].append((base + int(s), bytes(data[s:s+N])))
    print(f"candidate windows: {cands:,}", flush=True)
    for u, hs in found.items():
        print(chr(10) + f"UID {u}: {len(hs)} record(s)")
        for addr, win in hs[:2]:
            print(f"  @ {addr:#014x}  {list(win)}")
    (REPO / "build" / "fm_mem_recs.json").write_text(json.dumps(
        {str(u): [a for a, _ in hs] for u, hs in found.items()}))


def cmd_findrec16():
    """Same histogram search but attributes stored as int16 (or int32). Reinterpret memory as
    uint16/uint32 arrays, find N consecutive values all in 1-20, exact multiset match."""
    import collections
    import numpy as np
    pid = fm_pid(); h = open_proc(pid)
    order = ORACLE["order"]; N = len(order)
    targets = {int(u): tuple(sorted(v)) for u, v in ORACLE["oracle"].items()}
    tset = set(targets.values())
    for width, dt in ((2, np.uint16), (4, np.uint32)):
        print(f"pid {pid}; int{width*8} attribute search, N={N}", flush=True)
        found = collections.defaultdict(list)
        cands = 0
        for base, size in regions(h):
            if size > 512 * 1024 * 1024: continue
            data = read(h, base, size)
            if len(data) < N * width: continue
            trim = len(data) - (len(data) % width)
            a = np.frombuffer(data[:trim], dtype=dt)
            ok = (a >= 1) & (a <= 20)
            if len(a) <= N: continue
            csum = np.concatenate(([0], np.cumsum(ok, dtype=np.int32)))
            starts = np.nonzero((csum[N:] - csum[:-N]) == N)[0]
            for s in starts:
                cands += 1
                sig = tuple(sorted(int(x) for x in a[s:s+N]))
                if sig in tset:
                    for u, tg in targets.items():
                        if tg == sig:
                            found[u].append((base + int(s)*width, [int(x) for x in a[s:s+N]]))
        print(f"  int{width*8}: candidate windows {cands:,}", flush=True)
        for u, hs in found.items():
            print(f"    UID {u}: {len(hs)} record(s)")
            for addr, win in hs[:2]:
                print(f"      @ {addr:#014x}  {win}")
        if found:
            (REPO / "build" / f"fm_recs_int{width*8}.json").write_text(json.dumps(
                {str(u): [a for a, _ in hs] for u, hs in found.items()}))
            return


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    sub.add_parser("findrec")
    sub.add_parser("findrec16")
    v = sub.add_parser("validate")
    v.add_argument("--uid-off", type=int, default=0)
    v.add_argument("--attr-off", type=int, required=True)
    v.add_argument("--stride", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "scan":
        cmd_scan()
    elif a.cmd == "findrec":
        cmd_findrec()
    elif a.cmd == "findrec16":
        cmd_findrec16()
    else:
        cmd_validate(a.uid_off, a.attr_off, a.stride)


if __name__ == "__main__":
    main()
