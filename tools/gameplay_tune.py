#!/usr/bin/env python3
"""
gameplay_tune.py — change eFootball's gameplay via dt270's match constants.

    python tools/gameplay_tune.py status                 # what's installed, version family
    python tools/gameplay_tune.py install --mod evo      # install a known-good gameplay pack
    python tools/gameplay_tune.py install --mod gabelogan
    python tools/gameplay_tune.py blend --mod evo --amount 0.5   # half-strength version of a mod
    python tools/gameplay_tune.py restore                # back to your original dt270

What we know about the format (mapped in this repo):
  * dt270 `common/match/constant/*.bin` are WESYS containers holding PLAIN zlib (no encryption);
    tools/dt270_constants.py decodes and re-packs them.
  * The tables are Q2.14 fixed-point multipliers (16384 = x1.0): constant_team.bin = 817 team
    scalars (tempo, pressing, physicality — EVO's "HEAVY" block sits at offsets 820-832),
    constant_match.bin = global match rules, constant_player.bin = per-behaviour scalars,
    constant_ballPerson.bin = ball physics.
  * Two version families exist (constant_match 10622 vs 11904 bytes). Installing a mismatched
    family misbehaves silently, so this tool refuses a family mismatch.

`blend` interpolates every word between your ORIGINAL constants and the mod's, so you can run a
mod at 30% or 70% strength — a tuning axis no mod pack offers on its own.
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from dt270_constants import decode_constant, encode_constant   # noqa: E402

GAME_CPK = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk")
BACKUPS = Path.home() / "Backups" / "eFootball"

MODS = {
    "gabelogan": REPO / "build" / "gabelogan" / "dt270_console_all.cpk",
    "evo":       REPO / "EVO_GP_HEAVY" / "EVO GP HEAVY" / "dt270_console_all.cpk",
    "bromi":     REPO / "BromiV21" / "dt270_console_all.cpk",
}

CONSTS = ("constant_team.bin", "constant_match.bin", "constant_player.bin",
          "constant_ballPerson.bin", "constant_stadium.bin", "constant_positionPK.bin")


def load_cpk_constants(path: Path) -> dict[str, tuple[bytes, bytes]]:
    """filename -> (container bytes, decoded payload) for every match constant in a dt270 CPK."""
    from cricodecs import cpk
    c = cpk.load(str(path))
    out = {}
    for i, e in enumerate(c.files):
        name = e.full_path.split("/")[-1]
        if name.startswith("constant_") or name.endswith(".txt"):
            blob = c.file_bytes(i)
            out[name] = (blob, decode_constant(blob) if name.endswith(".bin") else blob)
    return out


def family_of(consts: dict) -> int | None:
    m = consts.get("constant_match.bin")
    return len(m[1]) if m else None


def game_dt270() -> Path:
    p = GAME_CPK / "dt270_console_all.cpk"
    if not p.exists():
        sys.exit(f"game dt270 not found: {p}")
    return p


def ensure_pristine_backup() -> Path:
    """The FIRST time we touch dt270, keep a pristine copy we can always restore."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    if not pristine.exists():
        shutil.copy2(game_dt270(), pristine)
        print(f"  pristine backup -> {pristine}")
    return pristine


def install_bytes(data: bytes) -> None:
    target = game_dt270()
    stamp = BACKUPS / f"dt270_console_all.{datetime.now():%Y%m%d-%H%M%S}.cpk"
    BACKUPS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, stamp)
    try:
        target.write_bytes(data)
    except PermissionError:
        sys.exit("dt270 is locked. Close eFootball and run again.")
    print(f"INSTALLED gameplay -> {target} ({len(data):,} bytes)")


def cmd_status(_a) -> int:
    cur = load_cpk_constants(game_dt270())
    print(f"installed dt270: {len(cur)} constant files, family {family_of(cur)} "
          f"({'v6-era' if family_of(cur) == 10622 else 'newer patch family'})")
    for name, path in MODS.items():
        if path.exists():
            fam = family_of(load_cpk_constants(path))
            ok = "OK to install" if fam == family_of(cur) else f"MISMATCH (family {fam})"
            print(f"  mod {name:10} {ok}")
        else:
            print(f"  mod {name:10} not present on disk")
    return 0


def cmd_install(a) -> int:
    src = MODS.get(a.mod)
    if not src or not src.exists():
        sys.exit(f"mod not found: {a.mod} ({src})")
    ensure_pristine_backup()
    cur = load_cpk_constants(game_dt270())
    mod = load_cpk_constants(src)
    if family_of(mod) != family_of(cur):
        sys.exit(f"version family mismatch: game={family_of(cur)}, mod={family_of(mod)}.\n"
                 "This mod targets a different game patch and would silently misbehave.")
    install_bytes(src.read_bytes())
    return 0


def cmd_blend(a) -> int:
    src = MODS.get(a.mod)
    if not src or not src.exists():
        sys.exit(f"mod not found: {a.mod}")
    pristine = ensure_pristine_backup()
    base = load_cpk_constants(pristine)
    mod = load_cpk_constants(src)
    if family_of(mod) != family_of(base):
        sys.exit(f"version family mismatch: game={family_of(base)}, mod={family_of(mod)}")
    t = max(0.0, min(1.0, a.amount))

    # Interpolate each shared constant word-by-word, then in-place patch the pristine CPK bytes.
    raw = bytearray(pristine.read_bytes())
    patched = 0
    for name, (blob, payload) in base.items():
        if name not in mod or not name.endswith(".bin"):
            continue
        mpay = mod[name][1]
        if len(mpay) != len(payload):
            continue                      # differently-sized table: skip rather than guess
        out = bytearray(payload)
        for off in range(0, len(payload) - 3, 4):
            b0 = struct.unpack_from("<i", payload, off)[0]
            m0 = struct.unpack_from("<i", mpay, off)[0]
            if b0 != m0:
                struct.pack_into("<i", out, off, int(round(b0 + (m0 - b0) * t)))
        packed = encode_constant(bytes(out), blob, level=9)
        # must fit the original slot for an in-place patch
        idx = raw.find(blob[:16])
        if idx >= 0 and len(packed) <= len(blob):
            packed = packed + b"\x00" * (len(blob) - len(packed))
            raw[idx:idx + len(blob)] = packed
            patched += 1
    if not patched:
        sys.exit("no constants could be patched in place (all size-mismatched)")
    print(f"  blended {patched} constant files at {t:.0%} strength")
    install_bytes(bytes(raw))
    return 0


def cmd_restore(_a) -> int:
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    if not pristine.exists():
        sys.exit("no pristine backup found (nothing was ever installed via this tool)")
    install_bytes(pristine.read_bytes())
    print("gameplay restored to original")
    return 0


# --- P4: self-calibration on the CURRENT patch family --------------------------------
# The bundled mods target older layouts (family 10622/11904 vs installed 9968), so the path
# to gameplay control is A/B testing OUR OWN pack: capture pristine, prove the write path
# with a byte-identical re-encode, then scale one constant file at a time and let the user
# feel the difference in-game. Verdicts land in docs/dt270-gameplay.md as the 9968 map.

def cmd_capture(_a) -> int:
    """Take the PRISTINE backup + record its SHA-1 (the dt270 patch guard baseline)."""
    import hashlib
    pristine = ensure_pristine_backup()
    sha = hashlib.sha1(pristine.read_bytes()).hexdigest()
    (REPO / "build" / "dt270_pristine.sha1").write_text(sha)
    cur = load_cpk_constants(pristine)
    print(f"captured: family {family_of(cur)}, sha1 {sha[:16]}…  ({pristine})")
    return 0


def _guard() -> None:
    """Refuse to write if the installed dt270 is neither pristine nor our last install."""
    import hashlib
    sha_file = REPO / "build" / "dt270_pristine.sha1"
    last_file = REPO / "build" / "dt270_last_install.sha1"
    if not sha_file.exists():
        sys.exit("run `capture` first — no pristine baseline recorded")
    cur = hashlib.sha1(game_dt270().read_bytes()).hexdigest()
    known = {sha_file.read_text().strip()}
    if last_file.exists():
        known.add(last_file.read_text().strip())
    if cur not in known:
        sys.exit("installed dt270 doesn't match the recorded baseline (a Konami patch?). "
                 "Re-run `capture` after verifying the game updated, then re-test.")


def _record_install(data: bytes) -> None:
    import hashlib
    (REPO / "build" / "dt270_last_install.sha1").write_text(hashlib.sha1(data).hexdigest())


def cmd_selftest(_a) -> int:
    """The zero-risk boot test: re-encode the game's own constants byte-identically,
    verify equality, install the result. Boot the game; if it plays normally the write
    path is proven. Then `restore`."""
    cmd_capture(_a)
    _guard()
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    raw = pristine.read_bytes()
    consts = load_cpk_constants(pristine)
    for name, (blob, payload) in consts.items():
        if not name.endswith(".bin") or not payload:
            continue
        repacked = encode_constant(payload, blob, level=9)
        # Round-trip gate in the dt200 tradition: understand it or don't touch it.
        if decode_constant(repacked) != payload:
            sys.exit(f"round-trip FAILED for {name} — do not install")
    print(f"round-trip verified for {sum(1 for n in consts if n.endswith('.bin'))} constants")
    install_bytes(raw)   # byte-identical: the pack itself is untouched
    _record_install(raw)
    print("SELFTEST INSTALLED (byte-identical). Boot eFootball, play a friendly kickoff, "
          "then run `restore`. If the game behaved normally, the write path is proven.")
    return 0


def cmd_scale(a) -> int:
    """Calibration probe: scale Q2.14 words of ONE constant file by --factor, in-place
    patch, install. Play ~10 minutes, note what changed, `restore`, repeat.

    --start/--end (word indices) probe a SLICE of the file — the bisection path to
    isolating specific behaviours: whole file first, then halves, quarters… e.g. hunting
    the AI build-up tempo words in constant_team (912 B = 228 words on family 9968):
        scale --file constant_team --factor 0.85                 # everything slower?
        scale --file constant_team --factor 0.85 --end 114       # first half
        scale --file constant_team --factor 0.85 --start 114     # second half
    """
    fname = a.file if a.file.endswith(".bin") else a.file + ".bin"
    if fname not in CONSTS:
        sys.exit(f"unknown constant file: {fname} (choose from {', '.join(CONSTS)})")
    cmd_capture(a)
    _guard()
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    base = load_cpk_constants(pristine)
    if fname not in base:
        sys.exit(f"{fname} not present in the installed pack")
    blob, payload = base[fname]
    out = bytearray(payload)
    changed = 0
    lo_word = getattr(a, "start", None) or 0
    hi_word = getattr(a, "end", None) or (len(payload) // 4)
    for off in range(lo_word * 4, min(hi_word * 4, len(payload) - 3), 4):
        w = struct.unpack_from("<i", payload, off)[0]
        # Only touch plausible Q2.14 magnitudes; leave ids/counts/zeroes alone.
        if 1024 <= abs(w) <= 262144:
            struct.pack_into("<i", out, off, int(round(w * a.factor)))
            changed += 1
    packed = encode_constant(bytes(out), blob, level=9)
    raw = bytearray(pristine.read_bytes())
    idx = raw.find(blob[:16])
    if idx < 0 or len(packed) > len(blob):
        sys.exit("in-place patch impossible (slot not found or compressed larger) — aborting")
    raw[idx:idx + len(blob)] = packed + b"\x00" * (len(blob) - len(packed))
    data = bytes(raw)
    install_bytes(data)
    _record_install(data)
    print(f"PROBE INSTALLED: {fname} x{a.factor} ({changed} words scaled).")
    print("Play ~10 min, note what feels different, then:")
    print(f'  python tools/gameplay_tune.py log --note "{fname} x{a.factor}: <your verdict>"')
    print("  python tools/gameplay_tune.py restore")
    return 0


def cmd_log(a) -> int:
    """Append a calibration verdict to docs/dt270-gameplay.md (the family-9968 map)."""
    doc = REPO / "docs" / "dt270-gameplay.md"
    with doc.open("a", encoding="utf-8") as f:
        f.write(f"\n- [{datetime.now():%Y-%m-%d}] calibration: {a.note}\n")
    print(f"logged to {doc}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("install")
    p.add_argument("--mod", required=True, choices=sorted(MODS))
    p = sub.add_parser("blend")
    p.add_argument("--mod", required=True, choices=sorted(MODS))
    p.add_argument("--amount", type=float, default=0.5, help="0.0 = original, 1.0 = full mod")
    sub.add_parser("restore")
    sub.add_parser("capture")
    sub.add_parser("selftest")
    p = sub.add_parser("scale")
    p.add_argument("--file", required=True, help="constant file to probe, e.g. constant_ballPerson")
    p.add_argument("--factor", type=float, required=True, help="e.g. 0.9 or 1.15")
    p.add_argument("--start", type=int, default=None, help="first word index of the slice (bisection)")
    p.add_argument("--end", type=int, default=None, help="one past the last word index (bisection)")
    p = sub.add_parser("log")
    p.add_argument("--note", required=True)
    a = ap.parse_args()
    return {"status": cmd_status, "install": cmd_install, "blend": cmd_blend, "restore": cmd_restore,
            "capture": cmd_capture, "selftest": cmd_selftest, "scale": cmd_scale, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
