"""Throwaway probe: can we attach a debugger to eFootball at all? (decides if per-player is reachable)

Anti-tamper blocks Cheat Engine's debugger; this tests whether a plain, unrecognised debugger
can attach where CE can't. It attaches, IMMEDIATELY sets kill-on-exit=FALSE (so detaching can
never take the game down), pumps debug events for ~1.5s to keep the target running, then detaches
cleanly and verifies the game is still alive.

This is the first thing that can crash the game / trip anti-tamper — run only with consent, not
mid-match. Nothing is written to game memory; it only attaches/detaches.

Usage: python tools/debug_probe.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)

DBG_CONTINUE = 0x00010002
TOKEN_ADJUST_PRIVILEGES = 0x20
SE_PRIVILEGE_ENABLED = 0x2


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wt.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wt.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


class DEBUG_EVENT(ctypes.Structure):
    # only the 12-byte header (code/pid/tid) is read; the union is an opaque buffer
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("_u", ctypes.c_byte * 184)]


def enable_se_debug() -> bool:
    tok = wt.HANDLE()
    if not advapi.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES,
                                   ctypes.byref(tok)):
        return False
    luid = LUID()
    if not advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
        return False
    tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
    advapi.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
    return ctypes.get_last_error() == 0


def main() -> int:
    pid = find_pid()
    if pid is None:
        print("eFootball.exe not running.")
        return 2
    print(f"target eFootball.exe pid {pid} ({hex(pid)})")
    print("enabling SeDebugPrivilege:", "ok" if enable_se_debug() else "FAILED (need admin)")

    k32.DebugActiveProcess.argtypes = [wt.DWORD]
    k32.DebugActiveProcessStop.argtypes = [wt.DWORD]
    k32.DebugSetProcessKillOnExit.argtypes = [wt.BOOL]
    k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]
    k32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wt.DWORD]

    print("attempting DebugActiveProcess…")
    if not k32.DebugActiveProcess(pid):
        err = ctypes.get_last_error()
        print(f"ATTACH FAILED (error {err}). Anti-tamper blocks debugging — per-player via "
              f"breakpoint tracing is NOT possible. Game untouched.")
        return 1
    # CRUCIAL: make sure detaching (or us dying) never kills the game.
    k32.DebugSetProcessKillOnExit(False)
    print("ATTACHED. Pumping debug events for ~1.5s (kill-on-exit is OFF)…")

    ev = DEBUG_EVENT()
    events = 0
    t0 = time.time()
    try:
        while time.time() - t0 < 1.5:
            if k32.WaitForDebugEvent(ctypes.byref(ev), 200):
                events += 1
                k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
    finally:
        k32.DebugSetProcessKillOnExit(False)
        stopped = k32.DebugActiveProcessStop(pid)

    time.sleep(0.5)
    alive = find_pid() is not None
    print(f"detached cleanly: {bool(stopped)} | debug events seen: {events}")
    print(f"game still running afterwards: {alive}")
    if alive:
        print("\nVERDICT: a plain debugger CAN attach and the game survived — per-player via "
              "breakpoint tracing is VIABLE. Next: build the light tracer.")
    else:
        print("\nVERDICT: game is gone — attaching killed it (anti-tamper reaction). "
              "Debugger route is not safe; per-player stays out of reach.")
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only.")
    raise SystemExit(main())
