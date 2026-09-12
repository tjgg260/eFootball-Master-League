#!/usr/bin/env python3
"""
exe_patch.py — ON-DISK hex patches for eFootball.exe, with a byte-exact pristine backup.

Same spec format as tools/live_patch.py (patch specs in tools/data/patches/*.json):
    {"description": "...", "patches": [
        {"name": "...", "module_offset": "0x401b3df" | "va": "0x14401b3df",
         "expect": "f3 0f 59 05 99 35 75 02", "patch": "f3 0f 59 05 29 25 b0 01", "kind": "code"} ]}

    python tools/exe_patch.py status                       # pristine sha, which patches are applied
    python tools/exe_patch.py apply  tools/data/patches/kick-error-x2.json [--dry-run]
    python tools/exe_patch.py remove tools/data/patches/kick-error-x2.json    # reverse that spec
    python tools/exe_patch.py restore                      # byte-exact pristine exe back
    python tools/exe_patch.py diff                         # every byte that differs from pristine

Rules baked in:
  * First apply copies the untouched exe to ~/Backups/eFootball/eFootball.exe.PRISTINE (352 MB)
    and records its sha1; `restore` copies it back. A timestamped backup is taken before
    every write as well.
  * A patch is written only if every `expect` byte matches the file right now (so a spec built
    for another game version, or already applied, cannot corrupt anything). `remove` requires
    the `patch` bytes to be present and writes `expect` back.
  * VA -> file offset goes through the PE section table (no hard-coded section maths).

Denuvo Anti-Tamper: the exe's protected code validates itself; a modified image MAY refuse to
start or crash (offline single-player: no ban). If it does, `restore`. Steam's "verify integrity
of game files" also reverts the exe. Keep the game closed while patching.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
BACKUPS = Path.home() / "Backups" / "eFootball"
PRISTINE = BACKUPS / "eFootball.exe.PRISTINE"
STATE = REPO / "build" / "exe_patch_state.json"


def sections(exe: Path):
    with open(exe, "rb") as f:
        d = f.read(0x1000)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    base = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
    secs = []
    for i in range(nsec):
        s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
        vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
        secs.append((s[:8].rstrip(b"\0").decode(), va, vsize, raw, rsize))
    return base, secs


def rva_to_file(secs, rva: int):
    for name, va, vsize, raw, rsize in secs:
        if va <= rva < va + vsize:
            o = rva - va
            if o >= rsize:
                sys.exit(f"rva {rva:#x} is in the virtual-only part of {name} (not on disk)")
            return raw + o
    sys.exit(f"rva {rva:#x} is not in any section")


def hexbytes(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", "").replace("_", ""))


def load_spec(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    desc = ""
    if isinstance(data, dict) and "patches" in data:
        desc = data.get("description", "")
        data = data["patches"]
    specs = data if isinstance(data, list) else [data]
    out = []
    for i, s in enumerate(specs):
        for k in ("name", "expect", "patch"):
            if k not in s:
                sys.exit(f"spec[{i}] missing '{k}'")
        if "module_offset" in s:
            rva = int(s["module_offset"], 16)
        elif "va" in s:
            rva = int(s["va"], 16) - 0x140000000
        else:
            sys.exit(f"spec[{i}] needs module_offset or va")
        e, p = hexbytes(s["expect"]), hexbytes(s["patch"])
        if len(e) != len(p):
            sys.exit(f"spec '{s['name']}': expect/patch length differ")
        out.append(dict(name=s["name"], rva=rva, expect=e, patch=p, kind=s.get("kind", "code")))
    return desc, out


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_pristine(exe: Path) -> None:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    if not PRISTINE.exists():
        print(f"  backing up pristine exe -> {PRISTINE} (this takes a moment)")
        shutil.copy2(exe, PRISTINE)
        state = dict(pristine_sha1=sha1(PRISTINE), pristine_size=PRISTINE.stat().st_size, applied=[])
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
        print(f"  pristine sha1 {state['pristine_sha1'][:16]}…")


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else dict(pristine_sha1=None, applied=[])


def save_state(st):
    STATE.write_text(json.dumps(st, indent=1))


def write_patches(exe: Path, specs, reverse: bool, dry: bool, label: str) -> int:
    base, secs = sections(exe)
    plan = []
    with open(exe, "rb") as f:
        for s in specs:
            off = rva_to_file(secs, s["rva"])
            f.seek(off)
            cur = f.read(len(s["expect"]))
            want_now, want_new = (s["patch"], s["expect"]) if reverse else (s["expect"], s["patch"])
            if cur != want_now:
                state = "already applied" if cur == want_new else "UNEXPECTED BYTES (different game version?)"
                print(f"  {s['name']}: {state}: file has {cur.hex()} at {off:#x}")
                if cur != want_new:
                    sys.exit("aborting — nothing written")
                continue
            plan.append((off, want_new, s))
    if not plan:
        print("nothing to do")
        return 0
    for off, new, s in plan:
        print(f"  {'REVERT' if reverse else 'PATCH '} {s['name']}  @file {off:#x} (va {base + s['rva']:#x}) {s['kind']}: {s['expect'].hex() if reverse else s['patch'].hex()}")
    if dry:
        print("dry run — nothing written")
        return 0
    ensure_pristine(exe)
    stamp = BACKUPS / f"eFootball.exe.{datetime.now():%Y%m%d-%H%M%S}.bak-meta.json"
    stamp.write_text(json.dumps([dict(off=o, old=s["patch"].hex() if reverse else s["expect"].hex(), new=n.hex(), name=s["name"]) for o, n, s in plan], indent=1))
    try:
        with open(exe, "r+b") as f:
            for off, new, s in plan:
                f.seek(off)
                f.write(new)
    except PermissionError:
        sys.exit("eFootball.exe is locked — close the game (and Steam's overlay) and retry")
    st = load_state()
    if reverse:
        st["applied"] = [a for a in st["applied"] if a != label]
    elif label not in st["applied"]:
        st["applied"].append(label)
    save_state(st)
    print(f"{'reverted' if reverse else 'written'} {len(plan)} patch(es); undo log {stamp.name}")
    return 0


def cmd_apply(a):
    desc, specs = load_spec(Path(a.spec))
    if desc:
        print(f"spec: {desc}")
    return write_patches(Path(a.exe), specs, reverse=False, dry=a.dry_run, label=Path(a.spec).name)


def cmd_remove(a):
    desc, specs = load_spec(Path(a.spec))
    return write_patches(Path(a.exe), specs, reverse=True, dry=a.dry_run, label=Path(a.spec).name)


def cmd_restore(a):
    if not PRISTINE.exists():
        sys.exit("no pristine backup — nothing was ever patched with this tool")
    exe = Path(a.exe)
    try:
        shutil.copy2(PRISTINE, exe)
    except PermissionError:
        sys.exit("eFootball.exe is locked — close the game and retry")
    st = load_state()
    st["applied"] = []
    save_state(st)
    print(f"restored pristine exe ({sha1(exe)[:16]}…)")
    return 0


def cmd_status(a):
    st = load_state()
    exe = Path(a.exe)
    print(f"exe: {exe} ({exe.stat().st_size:,} B)")
    print(f"pristine backup: {'present' if PRISTINE.exists() else 'none yet'}  sha1 {str(st.get('pristine_sha1'))[:16]}")
    print(f"applied specs (per state file): {st.get('applied') or '-'}")
    for spec in sorted((REPO / "tools" / "data" / "patches").glob("*.json")):
        _d, specs = load_spec(spec)
        base, secs = sections(exe)
        with open(exe, "rb") as f:
            states = []
            for s in specs:
                f.seek(rva_to_file(secs, s["rva"]))
                cur = f.read(len(s["expect"]))
                states.append("applied" if cur == s["patch"] else "pristine" if cur == s["expect"] else "OTHER")
        print(f"  {spec.name:45} {', '.join(states)}")
    return 0


def cmd_diff(a):
    if not PRISTINE.exists():
        sys.exit("no pristine backup to diff against")
    exe = Path(a.exe)
    n = 0
    with open(exe, "rb") as f1, open(PRISTINE, "rb") as f2:
        pos = 0
        while True:
            b1, b2 = f1.read(1 << 20), f2.read(1 << 20)
            if not b1 and not b2:
                break
            if b1 != b2:
                for i in range(max(len(b1), len(b2))):
                    x, y = (b1[i] if i < len(b1) else None), (b2[i] if i < len(b2) else None)
                    if x != y:
                        n += 1
                        if n <= 64:
                            print(f"  file {pos + i:#x}: pristine {y:02x} -> now {x:02x}")
            pos += len(b1)
    print(f"{n} byte(s) differ from pristine")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(EXE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("apply"); p.add_argument("spec"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("remove"); p.add_argument("spec"); p.add_argument("--dry-run", action="store_true")
    sub.add_parser("restore")
    sub.add_parser("diff")
    a = ap.parse_args()
    return {"status": cmd_status, "apply": cmd_apply, "remove": cmd_remove, "restore": cmd_restore, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
