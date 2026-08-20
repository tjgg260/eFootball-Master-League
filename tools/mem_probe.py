"""Decisive test: can ANY external process read eFootball's live memory?

Attaches read-only, enumerates committed regions, and tries to actually read bytes from a few
of them. Reports whether reads succeed and return real (non-zero) data. This distinguishes:
  - anti-tamper blocks ALL external reads  -> reads fail / return zeros  -> live memory dead
  - only Cheat Engine is singled out       -> plain RPM here returns real data -> route around CE
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = 0x02 | 0x04 | 0x20 | 0x40


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


def main():
    pid = find_pid()
    if pid is None:
        print("eFootball.exe not running (or its handle can't be opened at all).")
        return 2
    print(f"opened a handle to eFootball.exe (pid {pid}={hex(pid)}).")
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("OpenProcess FAILED even though the pid exists -> reads blocked at the handle level.")
        return 1

    committed = readable = read_ok = nonzero = 0
    total_read = 0
    addr, mbi = 0, MBI()
    try:
        while addr < 0x7FFFFFFFFFFF and read_ok < 40:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize
            if mbi.State == MEM_COMMIT:
                committed += 1
                if (mbi.Protect & READABLE) and not (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)):
                    readable += 1
                    n = min(size, 65536)
                    buf = (ctypes.c_char * n)()
                    got = ctypes.c_size_t(0)
                    if k32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, n,
                                             ctypes.byref(got)) and got.value:
                        read_ok += 1
                        total_read += got.value
                        if any(buf[:got.value]):
                            nonzero += 1
            addr = mbi.BaseAddress + size
    finally:
        k32.CloseHandle(h)

    print(f"committed regions seen: {committed}")
    print(f"readable regions:       {readable}")
    print(f"regions actually read:  {read_ok}  ({total_read:,} bytes)")
    print(f"regions with real data: {nonzero}")
    print()
    if read_ok == 0:
        print("VERDICT: external reads are BLOCKED — anti-tamper walls off live memory. "
              "Live per-player stats are not reachable; fall back to OCR of what's on screen.")
    elif nonzero == 0:
        print("VERDICT: reads 'succeed' but every region is ZEROED — anti-tamper is feeding "
              "fake memory. Same conclusion: live values not reachable.")
    else:
        print("VERDICT: external RPM WORKS and returns real data. Cheat Engine was being singled "
              "out; we can map the stats struct with our own tools (no CE needed).")
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only.")
    raise SystemExit(main())
