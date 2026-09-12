"""External-process live patcher / prober for eFootball.exe (x64, Denuvo-protected).

READ-first, write-guarded. No DLL injection, no code caves, no Cheat Engine. Everything here
runs from our own process using the same OpenProcess / EnumProcessModules / ReadProcessMemory
path that tools/mem_probe.py and tools/mem_scan.py already proved works against the live game
(docs/live-stats-extraction.md: plain external RPM returns real data; CE is singled out, we are
not). Writes go through VirtualProtectEx + WriteProcessMemory + protection-restore.

    ALWAYS RUN `probe` FIRST. It only READS. It proves we attached to the right process and that
    our RVA->runtime-VA relocation math is correct, before any byte is ever written.

Commands
    python tools/live_patch.py probe                       # read-only attach + relocation proof
    python tools/live_patch.py probe --vftable 0x146ba33a0 --method0 0x1440e1fb0
    python tools/live_patch.py info                         # pid, module base, ASLR slide
    python tools/live_patch.py apply  spec.json --i-understand-denuvo
    python tools/live_patch.py apply  spec.json --i-understand-denuvo --dry-run
    python tools/live_patch.py restore [journal.json]       # undo, restoring saved original bytes
    python tools/live_patch.py wait  [--apply spec.json --i-understand-denuvo]   # poll for launch

Spec file format (JSON): a single object or a list of objects
    {
      "name":          "human label",
      "module_offset": "0x1234abc",     # RVA into eFootball.exe (VA - 0x140000000)
      "expect":        "0f 84 aa bb",   # bytes that MUST currently be there (hex, spaces ok)
      "patch":         "90 90 90 90",   # bytes to write (same length as expect)
      "kind":          "data"           # "data" (safer) or "code" (may trip anti-tamper)
    }

Denuvo note: see the DENUVO_NOTES string below and the survey printed by `probe`. Writing to an
executable code page can trip an integrity/CRC check -> the game CRASHES (it does not ban; this
is offline single-player). A data-page write is the safer first real test. The
`--i-understand-denuvo` flag is required for any write and exists to make that risk a deliberate,
typed choice. This tool NEVER modifies eFootball.exe on disk.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------------------------
# Constants and Win32 plumbing (mirrors tools/mem_probe.py so behaviour is identical)
# ---------------------------------------------------------------------------------------------
IMAGE_BASE = 0x140000000          # eFootball.exe preferred base (DYNAMIC_BASE=False in the PE)
EXE_NAME = "eFootball.exe"
JOURNAL = Path("build/live_patch_journal.json")

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
READABLE = 0x02 | 0x04 | 0x20 | 0x40
EXECUTABLE = 0x10 | 0x20 | 0x40 | 0x80    # X, RX, RWX, WCX
LIST_MODULES_ALL = 0x03

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)


class MODULEINFO(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                ("SizeOfImage", wt.DWORD),
                ("EntryPoint", ctypes.c_void_p)]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
                ("AllocationProtect", wt.DWORD), ("__a1", wt.DWORD),
                ("RegionSize", ctypes.c_ulonglong), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD), ("__a2", wt.DWORD)]


DENUVO_NOTES = """\
Denuvo anti-tamper — what the binary tells us about external memory writes
--------------------------------------------------------------------------
Confirmed from the PE (tools/live_patch.py info / probe prints the live view):

  * The real code lives in a section named `.xcode` (execute+read, ~94 MB) and a giant
    executable blob `.impdata` (~183 MB) — that blob is the Denuvo VM/protection code.
    (The section literally named `.text` here is marked READ|WRITE data, not code — Denuvo
    shuffles the names.) So integrity checks, if present, cover `.xcode` / `.impdata`.
  * DllCharacteristics has DYNAMIC_BASE OFF, so the image normally loads at its preferred
    base 0x140000000 and the runtime slide is usually 0 — but this tool never assumes that:
    it reads the ACTUAL module base and relocates every offset. `probe` proves the math.
  * Anti-tamper / anti-debug import surface is all present and is the toolkit Denuvo uses to
    police itself at runtime:
      - VirtualProtect / NtProtectVirtualMemory / NtQueryVirtualMemory  (guard + re-check pages)
      - VirtualQuery                                                     (walk its own regions)
      - AddVectoredExceptionHandler                                     (trap tampered code)
      - IsDebuggerPresent, GetThreadContext, QueryPerformanceCounter, GetTickCount/64
        (debugger + timing checks: a stall from a breakpoint or a slow hook is noticed)
      - CreateThread                                                    (background watchdog)

Practical consequences for US (external, read-mostly, offline):
  * READS are safe and proven (mem_probe.py read 40 regions of real data). `probe` is read-only.
  * A WRITE to an executable page (kind:"code") is the risk: if a CRC/integrity loop later hashes
    that page it will mismatch -> the game CRASHES. This is a self-integrity crash, NOT an online
    ban (we are offline single-player, no VAC here). Undo may not help once it has crashed.
  * A WRITE to a DATA page (kind:"data") — a tuning value, a table entry, a flag the game reads
    each frame — is far less likely to be under an integrity hash and is the correct FIRST real
    write to try. Prefer expressing patches as data edits (many dt270 gameplay constants are
    loaded into writable structs — see tools/data/dt270_schema.json) over code NOPs.
  * We cannot enumerate Denuvo's exact CRC loops statically (they are obfuscated inside the
    .impdata VM), so treat every code write as "may crash", keep patches tiny, and always keep
    the journal so `restore` can put the original bytes back while the process still lives.
"""


# ---------------------------------------------------------------------------------------------
# Attach helpers
# ---------------------------------------------------------------------------------------------
def find_pid(name=EXE_NAME):
    arr = (wt.DWORD * 8192)()
    need = wt.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(need)):
        return None
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


def open_proc(pid, write=False):
    rights = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    if write:
        rights |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    h = k32.OpenProcess(rights, False, pid)
    if not h:
        err = ctypes.get_last_error()
        sys.exit(f"OpenProcess failed (err {err}). Run this terminal as Administrator"
                 + (" (writes need elevation)." if write else "."))
    return h


def module_base(h, name=EXE_NAME):
    """Return (base_va, size) of the main module. EnumProcessModulesEx path, matches by name."""
    needed = wt.DWORD()
    psapi.EnumProcessModulesEx(h, None, 0, ctypes.byref(needed), LIST_MODULES_ALL)
    count = needed.value // ctypes.sizeof(ctypes.c_void_p)
    if count == 0:
        return None, None
    mods = (ctypes.c_void_p * count)()
    if not psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(needed),
                                      LIST_MODULES_ALL):
        return None, None
    for m in mods[:count]:
        namebuf = ctypes.create_unicode_buffer(260)
        if psapi.GetModuleBaseNameW(h, ctypes.c_void_p(m), namebuf, 260) \
                and namebuf.value.lower() == name.lower():
            mi = MODULEINFO()
            if psapi.GetModuleInformation(h, ctypes.c_void_p(m), ctypes.byref(mi),
                                          ctypes.sizeof(mi)):
                return int(mi.lpBaseOfDll), int(mi.SizeOfImage)
            return int(m), None
    # Fallback: the first module is the exe itself.
    return int(mods[0]), None


def read_mem(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)) and got.value:
        return bytes(buf[:got.value])
    return b""


def query(h, addr):
    mbi = MBI()
    if k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        return mbi
    return None


def write_mem(h, addr, data):
    """VirtualProtectEx -> WriteProcessMemory -> restore original protection. Returns (ok, oldprot)."""
    n = len(data)
    old = wt.DWORD(0)
    if not k32.VirtualProtectEx(h, ctypes.c_void_p(addr), n, PAGE_EXECUTE_READWRITE,
                                ctypes.byref(old)):
        return False, None, f"VirtualProtectEx failed (err {ctypes.get_last_error()})"
    written = ctypes.c_size_t(0)
    ok = bool(k32.WriteProcessMemory(h, ctypes.c_void_p(addr),
                                     (ctypes.c_char * n)(*data), n, ctypes.byref(written)))
    err = "" if ok else f"WriteProcessMemory failed (err {ctypes.get_last_error()})"
    if ok and written.value != n:
        ok, err = False, f"short write ({written.value}/{n})"
    # Flush instruction cache so a live CPU picks up code edits immediately.
    k32.FlushInstructionCache(h, ctypes.c_void_p(addr), n)
    # Restore the page's original protection regardless of write outcome.
    restored = wt.DWORD(0)
    k32.VirtualProtectEx(h, ctypes.c_void_p(addr), n, old.value, ctypes.byref(restored))
    return ok, old.value, err


def hexbytes(s):
    return bytes.fromhex(s.replace(" ", "").replace("0x", ""))


def as_hex(b):
    return " ".join(f"{x:02x}" for x in b)


# ---------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------
def cmd_info(_a):
    pid = find_pid()
    if pid is None:
        print(f"{EXE_NAME} is not running.")
        return 2
    h = open_proc(pid, write=False)
    try:
        base, size = module_base(h)
        slide = (base - IMAGE_BASE) if base is not None else None
        print(f"pid            : {pid} ({hex(pid)})")
        print(f"module base    : {hex(base) if base else '?'}  (preferred {hex(IMAGE_BASE)})")
        print(f"module size    : {hex(size) if size else '?'}")
        print(f"ASLR slide     : {hex(slide) if slide is not None else '?'}"
              + ("  (image at preferred base — RVA==VA)" if slide == 0 else ""))
        print()
        print(DENUVO_NOTES)
    finally:
        k32.CloseHandle(h)
    return 0


def cmd_probe(a):
    """READ-ONLY. Prove attach + relocation by reading a known vftable and checking that its
    first slot points at the known first method, relocated by the real module base."""
    vft_va = int(a.vftable, 0)
    m0_va = int(a.method0, 0)
    vft_rva = vft_va - IMAGE_BASE
    m0_rva = m0_va - IMAGE_BASE

    pid = find_pid()
    if pid is None:
        print(f"{EXE_NAME} is not running. Launch it, or use `wait`.")
        return 2
    h = open_proc(pid, write=False)
    try:
        base, size = module_base(h)
        if base is None:
            print("could not resolve module base.")
            return 1
        slide = base - IMAGE_BASE
        print(f"attached to pid {pid}, module base {hex(base)} (slide {hex(slide)}).")

        vft_addr = base + vft_rva
        mbi = query(h, vft_addr)
        prot = mbi.Protect if mbi else 0
        print(f"vftable {hex(vft_va)} -> live {hex(vft_addr)} "
              f"(region protect {hex(prot)}, {'readable' if prot & READABLE else 'NOT readable'})")

        raw = read_mem(h, vft_addr, 8 * 18)
        if len(raw) < 8:
            print("READ FAILED at the vftable address — attach/relocation is wrong, or reads are "
                  "walled off. Do NOT attempt any patch.")
            return 1

        slot0 = int.from_bytes(raw[:8], "little")
        expected0 = base + m0_rva
        ok = (slot0 == expected0)
        print(f"vftable[0] read: {hex(slot0)}")
        print(f"expected      : {hex(expected0)}  (method0 rva {hex(m0_rva)} + base)")
        # Show a few more slots, resolved back to their preferred-base VAs, as a sanity list.
        print("first slots (resolved back to preferred-base VA):")
        for i in range(min(8, len(raw) // 8)):
            v = int.from_bytes(raw[i * 8:i * 8 + 8], "little")
            back = v - slide
            in_code = 0 <= (back - IMAGE_BASE) < (size or 0)
            print(f"  [{i:2}] {hex(v)}  -> {hex(back)} {'(in module)' if in_code else ''}")
        print()
        if ok:
            print("PROBE PASSED: external attach works and relocation math is correct. "
                  "Reads are reliable; you may proceed to a guarded write if you choose.")
            return 0
        print("PROBE MISMATCH: vftable[0] is not the expected method pointer. Either the exe "
              "map is stale for this build, the base is wrong, or memory is being masked. "
              "Do NOT patch until this passes.")
        return 1
    finally:
        k32.CloseHandle(h)


def _load_specs(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "patches" in data:      # {"description": ..., "patches": [...]}
        if data.get("description"):
            print(f"spec: {data['description']}")
        data = data["patches"]
    specs = data if isinstance(data, list) else [data]
    for i, s in enumerate(specs):
        for key in ("name", "module_offset", "expect", "patch"):
            if key not in s:
                sys.exit(f"spec[{i}] missing required key '{key}'")
        s.setdefault("kind", "data")
        if len(hexbytes(s["expect"])) != len(hexbytes(s["patch"])):
            sys.exit(f"spec '{s['name']}': expect and patch must be the same length")
    return specs


def cmd_apply(a):
    if not a.i_understand_denuvo and not a.dry_run:
        sys.exit("Refusing to write without --i-understand-denuvo. A code-page write can trip "
                 "Denuvo's integrity check and CRASH the game (offline, no ban). Run `probe` "
                 "first, prefer kind:\"data\", and re-run with the flag when ready. "
                 "(--dry-run needs no flag and only verifies expected bytes.)")
    specs = _load_specs(a.spec)

    pid = find_pid()
    if pid is None:
        sys.exit(f"{EXE_NAME} is not running.")
    h = open_proc(pid, write=not a.dry_run)
    journal_entries = []
    try:
        base, size = module_base(h)
        if base is None:
            sys.exit("could not resolve module base.")
        slide = base - IMAGE_BASE
        print(f"pid {pid}, base {hex(base)}, slide {hex(slide)}. "
              f"{'DRY RUN — no writes.' if a.dry_run else 'WRITING.'}")

        # Pass 1: verify every expected-bytes match before touching anything.
        planned = []
        for s in specs:
            rva = int(str(s["module_offset"]), 0)
            addr = base + rva
            expect = hexbytes(s["expect"])
            patch = hexbytes(s["patch"])
            cur = read_mem(h, addr, len(expect))
            mbi = query(h, addr)
            prot = mbi.Protect if mbi else 0
            is_exec = bool(prot & EXECUTABLE)
            status = "OK" if cur == expect else "MISMATCH"
            print(f"  [{s['name']}] {hex(addr)} kind={s['kind']} "
                  f"page={'EXEC' if is_exec else 'data'} prot={hex(prot)}")
            print(f"      current : {as_hex(cur) or '<read failed>'}")
            print(f"      expect  : {as_hex(expect)}   [{status}]")
            print(f"      patch   : {as_hex(patch)}")
            if cur != expect:
                sys.exit(f"  ABORT: expected bytes do not match for '{s['name']}'. Nothing "
                         "written. The build/offset may be wrong or already patched.")
            if is_exec and s["kind"] != "code":
                sys.exit(f"  ABORT: '{s['name']}' targets an EXECUTABLE page but kind is "
                         f"'{s['kind']}'. Set kind:\"code\" to acknowledge the anti-tamper risk.")
            planned.append((s, addr, expect, patch, prot, is_exec))

        if a.dry_run:
            print("dry run complete — all expected bytes matched. No writes performed.")
            return 0

        # Pass 2: write, journaling each original before it changes.
        for s, addr, expect, patch, prot, is_exec in planned:
            ok, oldprot, err = write_mem(h, addr, patch)
            verify = read_mem(h, addr, len(patch))
            wrote_ok = ok and verify == patch
            print(f"  [{s['name']}] {'WROTE' if wrote_ok else 'FAILED'} @ {hex(addr)}"
                  + (f"  ({err})" if err else "")
                  + (f"  readback {as_hex(verify)}" if not wrote_ok else ""))
            if wrote_ok:
                journal_entries.append({
                    "name": s["name"], "pid": pid, "module_base": hex(base),
                    "module_offset": hex(int(str(s["module_offset"]), 0)),
                    "addr": hex(addr), "kind": s["kind"],
                    "original": as_hex(expect), "patched": as_hex(patch),
                    "page_was_exec": is_exec, "time": datetime.now(timezone.utc).isoformat()})
    finally:
        k32.CloseHandle(h)

    if journal_entries:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        prev = []
        if JOURNAL.exists():
            try:
                prev = json.loads(JOURNAL.read_text(encoding="utf-8"))
            except Exception:
                prev = []
        JOURNAL.write_text(json.dumps(prev + journal_entries, indent=2), encoding="utf-8")
        print(f"journaled {len(journal_entries)} write(s) to {JOURNAL}. "
              f"`restore` puts the original bytes back.")
    return 0


def cmd_restore(a):
    path = Path(a.journal) if a.journal else JOURNAL
    if not path.exists():
        sys.exit(f"no journal at {path}.")
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not entries:
        print("journal is empty — nothing to restore.")
        return 0
    pid = find_pid()
    if pid is None:
        sys.exit(f"{EXE_NAME} is not running (restore only matters while it lives).")
    h = open_proc(pid, write=True)
    remaining = []
    try:
        base, _ = module_base(h)
        for e in reversed(entries):
            rva = int(e["module_offset"], 0)
            addr = base + rva
            orig = hexbytes(e["original"])
            patched = hexbytes(e["patched"])
            cur = read_mem(h, addr, len(orig))
            if cur == orig:
                print(f"  [{e['name']}] already original @ {hex(addr)} — skipped.")
                continue
            if cur != patched:
                print(f"  [{e['name']}] @ {hex(addr)} holds neither original nor our patch "
                      f"({as_hex(cur)}); restoring original anyway.")
            ok, _old, err = write_mem(h, addr, orig)
            verify = read_mem(h, addr, len(orig))
            if ok and verify == orig:
                print(f"  [{e['name']}] restored @ {hex(addr)}.")
            else:
                print(f"  [{e['name']}] restore FAILED @ {hex(addr)} ({err}); keeping in journal.")
                remaining.append(e)
    finally:
        k32.CloseHandle(h)
    path.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
    print(f"{len(remaining)} entr{'y' if len(remaining)==1 else 'ies'} left in journal.")
    return 0


def cmd_wait(a):
    print(f"waiting for {EXE_NAME} to start (Ctrl+C to stop)...")
    while True:
        pid = find_pid()
        if pid is not None:
            print(f"{EXE_NAME} is up (pid {pid}).")
            # Give the loader a moment to map modules and let Denuvo finish decrypting.
            time.sleep(2.0)
            if a.apply:
                ns = argparse.Namespace(spec=a.apply, i_understand_denuvo=a.i_understand_denuvo,
                                        dry_run=a.dry_run)
                return cmd_apply(ns)
            print("run `probe` now to verify attach, then `apply` when ready.")
            return 0
        time.sleep(a.interval)


# ---------------------------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(description="External live patcher/prober for eFootball.exe.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="READ-ONLY: prove attach + relocation via a known vftable")
    p.add_argument("--vftable", default="0x146ba33a0",
                   help="VA of a known vftable (default: match::pad::ThinkUnitShoot)")
    p.add_argument("--method0", default="0x1440e1fb0",
                   help="VA of that vftable's first method (default matches ThinkUnitShoot[0])")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("info", help="pid, module base, ASLR slide, Denuvo survey")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("apply", help="verify expected bytes then patch (guarded)")
    p.add_argument("spec", help="patch spec JSON (object or list)")
    p.add_argument("--i-understand-denuvo", dest="i_understand_denuvo", action="store_true",
                   help="required for any write; acknowledges code-page writes may crash the game")
    p.add_argument("--dry-run", action="store_true",
                   help="verify expected bytes only; write nothing (no flag needed)")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("restore", help="undo writes from the journal, restoring original bytes")
    p.add_argument("journal", nargs="?", help=f"journal file (default {JOURNAL})")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("wait", help="poll until eFootball.exe launches, optionally then apply")
    p.add_argument("--apply", help="spec JSON to apply once the process appears")
    p.add_argument("--i-understand-denuvo", dest="i_understand_denuvo", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--interval", type=float, default=1.0, help="poll seconds (default 1.0)")
    p.set_defaults(func=cmd_wait)
    return ap


def main(argv=None):
    if sys.platform != "win32":
        sys.exit("Windows only.")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
