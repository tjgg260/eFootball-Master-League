"""Read-only memory scanner for mapping eFootball's live per-player stats struct.

Cheat-Engine-style workflow, but scripted and READ-ONLY (ReadProcessMemory only — never writes
to the game). Used to locate the rating field (a value we can see on screen), narrow to it by
successive filtering, then inspect the surrounding struct to map counter offsets.

Session state (candidate address list) persists in build/mem_scan_state.json between runs so you
can scan, play a bit, then filter.

Commands:
  python tools/mem_scan.py find  <value> [--type f32|f64|i32|u32|u16] [--eps 0.01]
  python tools/mem_scan.py filter <value> [--eps 0.01]        # keep candidates now == value
  python tools/mem_scan.py list                               # show surviving candidates
  python tools/mem_scan.py dump  <hexaddr> [--bytes 256] [--as f32]   # inspect a struct region
  python tools/mem_scan.py near  <value> --of <hexaddr> [--span 512]  # find value near an addr

Run in an ELEVATED terminal with eFootball running.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
from pathlib import Path

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
WRITABLE = 0x04 | 0x08 | 0x40 | 0x80   # RW, WC, RWX — live stats live in writable data pages
STATE = Path("build/mem_scan_state.json")

FMT = {"f32": ("<f", 4), "float": ("<f", 4), "f64": ("<d", 8), "double": ("<d", 8),
       "i32": ("<i", 4), "u32": ("<I", 4), "u16": ("<H", 2)}


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
                ("AllocationProtect", wt.DWORD), ("__a1", wt.DWORD),
                ("RegionSize", ctypes.c_ulonglong), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD), ("__a2", wt.DWORD)]


def find_pid(name="eFootball.exe"):
    arr = (wt.DWORD * 8192)()
    need = wt.DWORD()
    psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(need))
    for i in range(need.value // ctypes.sizeof(wt.DWORD)):
        h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, arr[i])
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(h, None, buf, 260) and buf.value.lower() == name.lower():
                return arr[i]
        finally:
            k32.CloseHandle(h)
    return None


def _open(pid):
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        sys.exit("OpenProcess failed — run the terminal as Administrator.")
    return h


def _regions(h):
    addr, mbi = 0, MBI()
    while addr < 0x7FFFFFFFFFFF:
        if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        if (mbi.State == MEM_COMMIT and (mbi.Protect & WRITABLE)
                and not (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))
                and 0 < mbi.RegionSize <= 512 * 1024 * 1024):
            yield mbi.BaseAddress, mbi.RegionSize
        addr = mbi.BaseAddress + mbi.RegionSize


def _read(h, base, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
        return bytes(buf[:got.value])
    return b""


import numpy as np

# numpy dtype + alignment per scan type. Alignment 4 matches typical struct field packing and
# makes a full first-scan fast; the correlation still nails the exact field.
NPT = {"f32": ("<f4", 4), "float": ("<f4", 4), "f64": ("<f8", 8), "double": ("<f8", 8),
       "i32": ("<i4", 4), "u32": ("<u4", 4), "u16": ("<u2", 2)}


def _matches(data, base, typ, value, eps):
    dt, step = NPT[typ]
    n = len(data) - (len(data) % step)
    if n < step:
        return []
    a = np.frombuffer(data[:n], dtype=dt)
    if a.dtype.kind == "f":
        with np.errstate(invalid="ignore"):     # NaN floats in some regions — ignore, not match
            idx = np.nonzero(np.abs(a - value) <= eps)[0]
    else:
        idx = np.nonzero(a == int(value))[0]
    return (base + idx.astype(np.int64) * step).tolist()


def cmd_find(value, typ, eps):
    pid = find_pid() or sys.exit("eFootball not running.")
    h = _open(pid)
    hits = []
    try:
        for base, size_r in _regions(h):
            data = _read(h, base, size_r)
            if data:
                hits.extend(_matches(data, base, typ, value, eps))
                if len(hits) > 2_000_000:
                    break
    finally:
        k32.CloseHandle(h)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"pid": pid, "type": typ, "eps": eps,
                                 "addrs": hits[:2_000_000]}))
    print(f"{len(hits)} candidates hold {value} ({typ}). Change the value in-game "
          "(new match / different player), then run:  filter <new value>")


def cmd_filter(value, eps):
    st = json.loads(STATE.read_text())
    fmt, size = FMT[st["type"]]
    h = _open(st["pid"])
    keep = []
    try:
        for a in st["addrs"]:
            d = _read(h, a, size)
            if len(d) == size:
                v = struct.unpack(fmt, d)[0]
                if (abs(v - value) <= eps) if isinstance(v, float) else (v == int(value)):
                    keep.append(a)
    finally:
        k32.CloseHandle(h)
    st["addrs"] = keep
    STATE.write_text(json.dumps(st))
    print(f"{len(keep)} candidates now equal {value}.")
    for a in keep[:30]:
        print(f"  0x{a:x}")


def cmd_list():
    st = json.loads(STATE.read_text())
    print(f"{len(st['addrs'])} candidates (type {st['type']}):")
    for a in st["addrs"][:60]:
        print(f"  0x{a:x}")


def cmd_dump(hexaddr, nbytes, as_type):
    st = json.loads(STATE.read_text()) if STATE.exists() else {"pid": find_pid()}
    h = _open(st["pid"])
    addr = int(hexaddr, 16)
    d = _read(h, addr, nbytes)
    k32.CloseHandle(h)
    print(f"0x{addr:x}  ({len(d)} bytes)")
    fmt, size = FMT.get(as_type, ("<I", 4))
    for off in range(0, len(d) - size, size):
        v = struct.unpack_from(fmt, d, off)[0]
        raw = d[off:off + size].hex()
        show = f"{v:.3f}" if isinstance(v, float) else str(v)
        print(f"  +{off:>4} 0x{addr + off:x}  {raw:<16} {as_type}={show}")


def main():
    a = sys.argv
    if len(a) < 2:
        print(__doc__)
        return 2
    cmd = a[1]
    if cmd == "find":
        typ = a[a.index("--type") + 1] if "--type" in a else "f32"
        eps = float(a[a.index("--eps") + 1]) if "--eps" in a else 0.01
        cmd_find(float(a[2]), typ, eps)
    elif cmd == "filter":
        eps = float(a[a.index("--eps") + 1]) if "--eps" in a else 0.01
        cmd_filter(float(a[2]), eps)
    elif cmd == "list":
        cmd_list()
    elif cmd == "dump":
        nb = int(a[a.index("--bytes") + 1]) if "--bytes" in a else 256
        as_t = a[a.index("--as") + 1] if "--as" in a else "f32"
        cmd_dump(a[2], nb, as_t)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only.")
    raise SystemExit(main())
