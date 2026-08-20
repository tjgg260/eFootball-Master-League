"""Light hardware-breakpoint tracer: find what writes up to 4 addresses, and where it reads FROM.

Attaches as a debugger (proven to work on eFootball where CE is blocked). x64 has four debug
registers (DR0-DR3), so ONE debugger watches up to four addresses at once — e.g. the team
passes-total AND an individual player's rating simultaneously. (Two separate debuggers are
impossible: Windows allows only one debugger per process. Four hardware breakpoints in one
debugger is the way to "watch both".)

On each write hit it logs RIP + the full register snapshot and flags any register equal to
`target - small_offset` — that register is the base pointer of the struct being written and the
offset is the field. The writing code reads the per-player stats to produce the rating/total, so
the registers reveal the per-player struct.

Runs DURING a live match (writes only happen when stats change). Read-only except the CPU debug
registers; no game code is patched. kill-on-exit is forced OFF so detach never kills the game.

Usage:
  python tools/trace_writes.py --addr 0xECF6126C --seconds 30
  python tools/trace_writes.py --addr 0xA,0xB --team-passes away --seconds 40   # up to 4 total
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid, _open, _read, k32

k32.CloseHandle.argtypes = [wt.HANDLE]
DBG_CONTINUE = 0x00010002
EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
EXIT_PROCESS_DEBUG_EVENT = 5
TH32CS_SNAPTHREAD = 0x4
THREAD_ALL = 0x1FFFFF
CTX_FLAGS = 0x00100013     # AMD64 | CONTROL | INTEGER | DEBUG_REGISTERS


class M128A(ctypes.Structure):
    _fields_ = [("Low", ctypes.c_ulonglong), ("High", ctypes.c_longlong)]


class CONTEXT(ctypes.Structure):
    _fields_ = [
        ("P1Home", ctypes.c_ulonglong), ("P2Home", ctypes.c_ulonglong),
        ("P3Home", ctypes.c_ulonglong), ("P4Home", ctypes.c_ulonglong),
        ("P5Home", ctypes.c_ulonglong), ("P6Home", ctypes.c_ulonglong),
        ("ContextFlags", ctypes.c_ulong), ("MxCsr", ctypes.c_ulong),
        ("SegCs", ctypes.c_ushort), ("SegDs", ctypes.c_ushort), ("SegEs", ctypes.c_ushort),
        ("SegFs", ctypes.c_ushort), ("SegGs", ctypes.c_ushort), ("SegSs", ctypes.c_ushort),
        ("EFlags", ctypes.c_ulong),
        ("Dr0", ctypes.c_ulonglong), ("Dr1", ctypes.c_ulonglong), ("Dr2", ctypes.c_ulonglong),
        ("Dr3", ctypes.c_ulonglong), ("Dr6", ctypes.c_ulonglong), ("Dr7", ctypes.c_ulonglong),
        ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong), ("Rdx", ctypes.c_ulonglong),
        ("Rbx", ctypes.c_ulonglong), ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
        ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong), ("R8", ctypes.c_ulonglong),
        ("R9", ctypes.c_ulonglong), ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
        ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong), ("R14", ctypes.c_ulonglong),
        ("R15", ctypes.c_ulonglong), ("Rip", ctypes.c_ulonglong),
        ("FltSave", ctypes.c_byte * 512), ("VectorRegister", M128A * 26),
        ("VectorControl", ctypes.c_ulonglong), ("DebugControl", ctypes.c_ulonglong),
        ("LastBranchToRip", ctypes.c_ulonglong), ("LastBranchFromRip", ctypes.c_ulonglong),
        ("LastExceptionToRip", ctypes.c_ulonglong), ("LastExceptionFromRip", ctypes.c_ulonglong),
    ]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("_u", ctypes.c_byte * 184)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", wt.LONG),
                ("tpDeltaPri", wt.LONG), ("dwFlags", wt.DWORD)]


GP = ["Rax", "Rcx", "Rdx", "Rbx", "Rsp", "Rbp", "Rsi", "Rdi",
      "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]
DR = ["Dr0", "Dr1", "Dr2", "Dr3"]


def _aligned_context():
    buf = (ctypes.c_char * (ctypes.sizeof(CONTEXT) + 16))()
    a = (ctypes.addressof(buf) + 15) & ~15
    return CONTEXT.from_address(a), buf


def thread_ids(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32(); te.dwSize = ctypes.sizeof(te)
    ids = []
    if k32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                ids.append(te.th32ThreadID)
            if not k32.Thread32Next(snap, ctypes.byref(te)):
                break
    k32.CloseHandle(snap)
    return ids


def set_bps(tid, targets, clear=False):
    """Arm/clear a 4-byte WRITE breakpoint per target in DR0..DR3."""
    h = k32.OpenThread(THREAD_ALL, False, tid)
    if not h:
        return
    ctx, _buf = _aligned_context()
    ctx.ContextFlags = CTX_FLAGS
    k32.SuspendThread(h)
    if k32.GetThreadContext(h, ctypes.byref(ctx)):
        dr7 = ctx.Dr7
        for i in range(4):
            if clear or i >= len(targets):
                setattr(ctx, DR[i], 0)
                dr7 &= ~((1 << (2 * i)) | (0b11 << (16 + 4 * i)) | (0b11 << (18 + 4 * i)))
            else:
                setattr(ctx, DR[i], targets[i])
                dr7 |= (1 << (2 * i)) | (0b01 << (16 + 4 * i)) | (0b11 << (18 + 4 * i))  # write,4B
        ctx.Dr7 = dr7
        ctx.ContextFlags = CTX_FLAGS
        k32.SetThreadContext(h, ctypes.byref(ctx))
    k32.ResumeThread(h)
    k32.CloseHandle(h)


def locate_team_passes(side):
    from read_team_stats import locate_and_read
    h = _open(find_pid())
    try:
        addr, _stats = locate_and_read(h)
    finally:
        k32.CloseHandle(h)
    if addr is None:
        sys.exit("couldn't locate team-stats struct — be on the Team Stats screen first.")
    passes = addr + 7 * 8 + (4 if side == "away" else 0)
    print(f"team passes ({side}) total @ 0x{passes:x}")
    return passes


def main():
    a = sys.argv
    seconds = int(a[a.index("--seconds") + 1]) if "--seconds" in a else 30
    targets = []
    if "--addr" in a:
        targets += [int(x, 16) for x in a[a.index("--addr") + 1].split(",")]
    if "--team-passes" in a:
        targets.append(locate_team_passes(a[a.index("--team-passes") + 1]))
    if "--match-passes" in a:
        # locate by the EXACT on-screen passes pair (deterministic, works while paused),
        # then watch BOTH teams' passes so whichever ticks first fires.
        from read_team_stats import locate_by_passes
        home, away = (int(x) for x in a[a.index("--match-passes") + 1].split(","))
        h0 = _open(find_pid())
        addr = locate_by_passes(h0, home, away)
        k32.CloseHandle(h0)
        if addr is None:
            sys.exit(f"no team-stats struct with passes {home}/{away} — re-read the current "
                     f"numbers off the paused stats screen and pass them exactly.")
        print(f"located struct @ 0x{addr:x}  (passes {home}/{away})")
        targets += [addr + 7 * 8, addr + 7 * 8 + 4]     # home + away passes
    targets = targets[:4]
    if not targets:
        print(__doc__)
        return 2

    pid = find_pid() or sys.exit("eFootball not running.")
    k32.DebugActiveProcess.argtypes = [wt.DWORD]
    k32.DebugActiveProcessStop.argtypes = [wt.DWORD]
    k32.DebugSetProcessKillOnExit.argtypes = [wt.BOOL]
    k32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wt.DWORD]
    k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]

    if not k32.DebugActiveProcess(pid):
        sys.exit(f"attach failed (err {ctypes.get_last_error()}) — is another debugger attached?")
    k32.DebugSetProcessKillOnExit(False)
    for tid in thread_ids(pid):
        set_bps(tid, targets)
    print("WRITE breakpoints armed:")
    for i, t in enumerate(targets):
        print(f"  DR{i} -> 0x{t:x}")
    print(f"Play the match — tracing for {seconds}s…\n")

    ev = DEBUG_EVENT()
    hits = 0
    seen = set()
    dumped = set()
    ph = _open(pid)            # separate read handle to snapshot pointers DURING each hit
    t0 = time.time()
    try:
        while time.time() - t0 < seconds and hits < 400:
            if not k32.WaitForDebugEvent(ctypes.byref(ev), 200):
                continue
            code = ev.dwDebugEventCode
            if code == CREATE_THREAD_DEBUG_EVENT:
                set_bps(ev.dwThreadId, targets)
            elif code == EXIT_PROCESS_DEBUG_EVENT:
                break
            elif code == EXCEPTION_DEBUG_EVENT:
                h = k32.OpenThread(THREAD_ALL, False, ev.dwThreadId)
                ctx, _buf = _aligned_context()
                ctx.ContextFlags = CTX_FLAGS
                if h and k32.GetThreadContext(h, ctypes.byref(ctx)) and (ctx.Dr6 & 0xf):
                    which = [i for i in range(len(targets)) if ctx.Dr6 & (1 << i)]
                    for i in which:
                        tgt = targets[i]
                        rip = ctx.Rip
                        regs = {r: getattr(ctx, r) for r in GP}
                        bases = [(r, tgt - v) for r, v in regs.items() if 0 <= tgt - v < 8192]
                        key = (i, rip)
                        if key not in seen:
                            seen.add(key)
                            hits += 1
                            print(f"[DR{i} 0x{tgt:x}] RIP=0x{rip:x}")
                            for r, off in bases:
                                print(f"    dest base {r}=0x{regs[r]:x}  -> field offset +{off}")
                            # full snapshot: any register holding a heap pointer is a SOURCE lead
                            ptrs = [(r, v) for r, v in regs.items() if 0x10000 < v < 0x7FFFFFFFFFFF]
                            print("    source-candidate pointers: " +
                                  ", ".join(f"{r}=0x{v:x}" for r, v in ptrs))
                            # CAPTURE each pointer's memory NOW (process is frozen at the BP) —
                            # survives the anti-tamper delayed kill. Hunt small-int arrays.
                            for r, v in ptrs:
                                if v in dumped:
                                    continue
                                dumped.add(v)
                                d = _read(ph, v, 192)
                                if len(d) < 192:
                                    continue
                                vals = [int.from_bytes(d[k:k+4], "little", signed=True)
                                        for k in range(0, 192, 4)]
                                small = [x for x in vals if 0 <= x <= 200]
                                print(f"      [{r} 0x{v:x}] ints: " +
                                      " ".join(str(x) for x in vals[:24]))
                                if len(small) >= 8:
                                    print(f"         ^ {len(small)} small ints, sum(0..200)="
                                          f"{sum(small)} — possible per-player array")
                    ctx.Dr6 = 0
                    ctx.ContextFlags = CTX_FLAGS
                    k32.SetThreadContext(h, ctypes.byref(ctx))
                if h:
                    k32.CloseHandle(h)
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
    finally:
        for tid in thread_ids(pid):
            set_bps(tid, targets, clear=True)
        k32.DebugSetProcessKillOnExit(False)
        k32.DebugActiveProcessStop(pid)
        k32.CloseHandle(ph)

    print(f"\n{len(seen)} distinct writing instruction(s) across {len(targets)} target(s).")
    print("A base-register + small offset is the per-player struct. Dump it:  "
          "python tools/memdump.py 0x<base> 512")
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only.")
    raise SystemExit(main())
