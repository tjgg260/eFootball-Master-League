"""Recover the IoStore global AES-256 key from the RUNNING game's memory (read-only).

The static scan (find_aes_key.py) fails because eFootball.exe is VM-protected: the key only
exists after the protector decrypts it in memory. But to load its paks the game MUST expand the
AES-256 key schedule into RAM. This tool attaches read-only to the live process, walks its
committed memory with ReadProcessMemory, and runs the same aeskeyfind invariant to find that
schedule. It NEVER writes to the game's memory — it only reads, like a debugger inspecting.

Repo note: the standing rule "nothing from tools/vendor/sider runs while the game is running"
is about the Sider decryption/injection code. This tool imports none of that; it is a
read-only observer. Still, run it only on your own offline install, by choice.

How to use:
  1. Launch eFootball, sit at the main menu (paks are loaded by then).
  2. In an ADMIN terminal:  python tools/find_aes_key_live.py
  3. It prints  AES-256 key = <64 hex chars>  when found.

Then that key unlocks the IoStore paks for reading with retoc / FModel / ZenTools.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_aes_key import _verify  # reuse the full AES-256 expansion verifier

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = 0x02 | 0x04 | 0x20 | 0x40  # R, RW, RX, RWX


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD),
        ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("__alignment2", wt.DWORD),
    ]


def find_pid(name: str = "eFootball.exe") -> int | None:
    arr = (wt.DWORD * 4096)()
    need = wt.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(need)):
        return None
    count = need.value // ctypes.sizeof(wt.DWORD)
    for i in range(count):
        pid = arr[i]
        h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(h, None, buf, 260) and buf.value.lower() == name.lower():
                return pid
        finally:
            k32.CloseHandle(h)
    return None


def scan_bytes(data: bytes, base: int) -> list[tuple[int, bytes]]:
    import numpy as np
    a8 = np.frombuffer(data[: len(data) - len(data) % 4], dtype=np.uint8)
    w = a8.view(np.dtype(">u4"))
    if len(w) < 60:
        return []
    diff = w[8:] ^ w[:-8] ^ w[7:-1]
    zero = (diff == 0)
    must = [i for i in range(8, 60) if i % 8 not in (0, 4)]
    limit = len(w) - 60
    if limit < 0:
        return []
    cond = np.ones(limit + 1, dtype=bool)
    for i in must:
        idx = i - 8
        cond &= zero[idx: idx + limit + 1]
    hits = []
    for s in np.nonzero(cond)[0]:
        words = [int(x) for x in w[s: s + 60]]
        if _verify(words):
            key = b"".join(int(x).to_bytes(4, "big") for x in words[:8])
            hits.append((base + int(s) * 4, key))
    return hits


def main() -> int:
    pid = find_pid()
    if pid is None:
        print("eFootball.exe not running. Launch the game to the main menu, then re-run.")
        return 2
    print(f"attached read-only to eFootball.exe (pid {pid}); scanning committed memory…")
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        print("OpenProcess failed — run this terminal as Administrator.")
        return 2
    seen: set[str] = set()
    try:
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION64()
        max_addr = 0x7FFFFFFFFFFF
        while addr < max_addr:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr),
                                      ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize
            usable = (mbi.State == MEM_COMMIT and (mbi.Protect & READABLE)
                      and not (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)))
            if usable and 0 < size <= 512 * 1024 * 1024:
                buf = (ctypes.c_char * size)()
                read = ctypes.c_size_t(0)
                if k32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, size,
                                         ctypes.byref(read)) and read.value >= 240:
                    for off, key in scan_bytes(bytes(buf[: read.value]), mbi.BaseAddress):
                        hexk = key.hex()
                        if hexk not in seen:
                            seen.add(hexk)
                            print(f"  @0x{off:x}: AES-256 key = {hexk}")
            addr = mbi.BaseAddress + size
    finally:
        k32.CloseHandle(h)

    if not seen:
        print("no AES-256 schedule found in memory. Make sure the game is fully at the menu "
              "(paks loaded) and the terminal is elevated.")
        return 1
    print("\nCandidate IoStore key(s) above. UE IoStore uses AES-256 ECB; the container's "
          "key-GUID is zero, so this global key unlocks every pc*.ucas.")
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only (uses ReadProcessMemory).")
    raise SystemExit(main())
