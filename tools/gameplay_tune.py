#!/usr/bin/env python3
"""
gameplay_tune.py — change eFootball's gameplay via dt270's match constants, BY NAME.

    python tools/gameplay_tune.py status                 # what's installed, version family
    python tools/gameplay_tune.py get ball magnusRate     # read a parameter (dotted paths)
    python tools/gameplay_tune.py set ball magnusRate=0.05 basePosition.dfLine=12
    python tools/gameplay_tune.py apply tuning.json       # batch of edits (see below)
    python tools/gameplay_tune.py diff                    # installed vs pristine, by name
    python tools/gameplay_tune.py scale --object ball --factor 0.9 [--match bound]
    python tools/gameplay_tune.py restore                 # back to the pristine original
    python tools/gameplay_tune.py install --mod evo       # legacy mod packs (family-guarded)
    python tools/gameplay_tune.py blend --mod evo --amount 0.5

Format (fully decoded 2026-08-23 — see docs/dt270-gameplay.md, docs/dt270-fields.md):
  * dt270 `common/match/constant/*.bin` are WESYS containers of PLAIN zlib (level 9 reproduces
    Konami's bytes exactly). Each holds a PACK of named objects (`ball.o`, `ballplayer.o`, …).
  * An object is a compiled JSON document: float/int/bool scalars inline, nested objects /
    arrays / strings as u32 offsets to blocks. Field names, types and layouts come from the
    game's own loaders (tools/dt270_schema_gen.py -> tools/data/dt270_schema.json).
  * `set`/`apply`/`scale` edit values IN PLACE in the pristine pack and patch the CPK slot in
    place; the object never changes size and every other byte of the CPK is untouched.

tuning.json for `apply` — a list of edits, or {"edits": [...]}:
    [{"object": "ball", "path": "magnusRate", "value": 0.05},
     {"object": "basePosition", "path": "dfLine", "value": 12},
     {"object": "shoot", "path": "normalShootGageMax99.5", "value": 110.0}]

Version families still matter for the LEGACY packs (EVO/GabeLogan/Bromi target older
layouts and are refused on mismatch); named edits are patch-proof as long as the schema was
regenerated for the installed exe.
"""
from __future__ import annotations

import argparse
import shutil
import sys
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
    """Run a (same-family) mod pack at partial strength: every float parameter is interpolated
    by NAME between the pristine value and the mod's; ints/bools take the mod's value from 50%.
    The installed schema applies to both packs because the family check guarantees the same
    exe struct layout."""
    src = MODS.get(a.mod)
    if not src or not src.exists():
        sys.exit(f"mod not found: {a.mod}")
    pristine = ensure_pristine_backup()
    if family_of(load_cpk_constants(src)) != family_of(load_cpk_constants(pristine)):
        sys.exit("version family mismatch: this mod targets a different game patch")
    t = max(0.0, min(1.0, a.amount))
    _schema, base = _schema_packs(pristine)
    _schema, mod = _schema_packs(src)
    touched, changed = set(), 0
    for fname, (_blob, pb) in base.items():
        if fname not in mod:
            continue
        pm = mod[fname][1]
        for name in pb.names():
            if name not in pm.names() or name not in pb.schema.by_object:
                continue
            vb, vm = pb.object(name), pm.object(name)
            lm = {lf.path: lf for lf in vm.leaves() if lf.writable}
            for lb in vb.leaves():
                lf = lm.get(lb.path)
                if lf is None or not lb.writable or lb.kind == "string":
                    continue
                x, y = vb.read_leaf(lb), vm.read_leaf(lf)
                if x == y:
                    continue
                if lb.kind in ("float", "double"):
                    vb.write_leaf(lb, x + (y - x) * t)
                elif t >= 0.5:
                    vb.write_leaf(lb, y)
                else:
                    continue
                changed += 1
                touched.add(fname)
    if not touched:
        sys.exit("the mod changes nothing the schema can address")
    _patch_and_install(pristine, base, touched, f"{a.mod} blended at {t:.0%} ({changed} parameters)")
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


def _schema_packs(path: Path):
    from dt270_objects import Schema, Pack
    schema = Schema.load()
    base = load_cpk_constants(path)
    return schema, {name: (blob, Pack(payload, schema)) for name, (blob, payload) in base.items()
                    if name.endswith(".bin") and payload}


def _find(packs, obj: str):
    for fname, (blob, pack) in packs.items():
        if obj in pack.names():
            return fname, blob, pack
    sys.exit(f"object {obj!r} not found (see docs/dt270-fields.md)")


def build_patched_cpk(pristine: Path, packs, touched: set[str]) -> bytes:
    """Re-encode the edited packs and drop them into their original CPK slots (in place).
    Every other byte of the CPK is untouched; a round-trip gate re-decodes each slot."""
    raw = bytearray(pristine.read_bytes())
    for fname in sorted(touched):
        blob, pack = packs[fname]
        try:
            packed = encode_constant(pack.payload(), blob, level=9, max_len=len(blob))
        except ValueError as ex:
            sys.exit(f"{fname}: {ex} — fewer edits, or values that compress better")
        idx = raw.find(blob[:16])
        if idx < 0 or raw.find(blob[:16], idx + 1) >= 0:
            sys.exit(f"{fname}: container slot not uniquely located — aborting")
        raw[idx:idx + len(blob)] = packed + b"\x00" * (len(blob) - len(packed))
        if decode_constant(bytes(raw[idx:idx + len(blob)])) != pack.payload():
            sys.exit(f"{fname}: round-trip check failed — not installing")
    return bytes(raw)


def _patch_and_install(base_path: Path, packs, touched: set[str], what: str) -> None:
    data = build_patched_cpk(base_path, packs, touched)
    install_bytes(data)
    _record_install(data)
    print(f"INSTALLED: {what} ({', '.join(sorted(touched))})")


def _parse_value(text: str):
    t = text.strip()
    if t.lower() in ("true", "false"):
        return t.lower() == "true"
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def _edits_from_args(items: list[str], default_obj: str | None):
    """['magnusRate=0.05', 'basePosition.dfLine=12'] (+ default object) -> [(obj, path, value)]"""
    out = []
    for it in items:
        if "=" not in it:
            sys.exit(f"expected object.path=value, got {it!r}")
        lhs, rhs = it.split("=", 1)
        if default_obj and "." not in lhs.split("[")[0]:
            obj, path = default_obj, lhs
        else:
            obj, path = lhs.split(".", 1)
        out.append((obj, path, _parse_value(rhs)))
    return out


def cmd_get(a) -> int:
    import json
    _schema, packs = _schema_packs(game_dt270())
    _fname, _blob, pack = _find(packs, a.object)
    v = pack.object(a.object).get(a.path) if a.path else pack.object(a.object).to_dict()
    print(json.dumps(v, indent=1) if isinstance(v, (dict, list)) else (f"{v:g}" if isinstance(v, float) else v))
    return 0


def _apply_edits(edits, a) -> int:
    from dt270_objects import _parse_path
    cmd_capture(a)                      # pristine backup + sha baseline (idempotent)
    _guard()
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    src = pristine if not getattr(a, "stack", False) else game_dt270()
    _schema, packs = _schema_packs(src)
    touched = set()
    for obj, path, value in edits:
        fname, _blob, pack = _find(packs, obj)
        view = pack.object(obj)
        lf = view.leaf(_parse_path(path))
        before = view.read_leaf(lf)
        if lf.kind == "string" and view.string_slot_shared(lf):
            print(f"  note: {obj}.{path} shares its string slot with another field (both change)")
        view.write_leaf(lf, value)
        print(f"  {obj}.{lf.dotted}: {before!r} -> {view.read_leaf(lf)!r}")
        touched.add(fname)
    if not touched:
        sys.exit("nothing to do")
    _patch_and_install(src, packs, touched,
                       f"{len(edits)} named edit(s) " + ("stacked on current" if src != pristine else "on pristine"))
    return 0


def cmd_set(a) -> int:
    """set ball magnusRate=0.05  |  set ball.magnusRate=0.05 basePosition.dfLine=12"""
    items = list(a.items)
    default_obj = items.pop(0) if items and "=" not in items[0] else None
    return _apply_edits(_edits_from_args(items, default_obj), a)


def cmd_apply(a) -> int:
    import json
    data = json.loads(Path(a.file).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("edits", data)
    edits = [(e["object"], e["path"], e["value"]) for e in data]
    return _apply_edits(edits, a)


def cmd_diff(a) -> int:
    """Installed dt270 vs pristine, reported by field name."""
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    if not pristine.exists():
        sys.exit("no pristine backup yet (nothing installed through this tool)")
    _s, base = _schema_packs(pristine)
    _s, cur = _schema_packs(game_dt270())
    n = 0
    for fname, (_b, pb) in base.items():
        if fname not in cur:
            print(f"  {fname}: missing in installed pack")
            continue
        pc = cur[fname][1]
        for name in pb.names():
            if name not in pc.names() or name not in pb.schema.by_object:
                continue
            vb, vc = pb.object(name), pc.object(name)
            for lb, lc in zip(vb.leaves(), vc.leaves()):
                x, y = vb.read_leaf(lb), vc.read_leaf(lc)
                if x != y:
                    n += 1
                    print(f"  {name}.{lb.dotted}: {x!r} -> {y!r}")
    print(f"{n} parameter(s) differ from pristine" if n else "installed dt270 == pristine (by value)")
    return 0


def cmd_scale(a) -> int:
    """Calibration probe, schema-aware: multiply every FLOAT leaf of one object (optionally
    only paths containing --match) by --factor. Unlike the old blind word-scaler this never
    touches ints, bools, strings or pointers, so the pack stays structurally valid.
        scale --object ball --factor 0.9                 # heavier ball
        scale --object basePosition --factor 1.1 --match dfLine
        scale --object moveMatching --factor 0.95 --match acc
    Play ~10 minutes, `log --note ...`, then `restore` (or stack another probe with --stack)."""
    cmd_capture(a)                      # pristine backup + sha baseline (idempotent)
    _guard()
    pristine = BACKUPS / "dt270_console_all.PRISTINE.cpk"
    src = pristine if not a.stack else game_dt270()
    _schema, packs = _schema_packs(src)
    fname, _blob, pack = _find(packs, a.object)
    view = pack.object(a.object)
    changed = 0
    for lf in view.leaves():
        if lf.kind != "float" or not lf.writable:
            continue
        if a.match and a.match.lower() not in lf.dotted.lower():
            continue
        v = view.read_leaf(lf)
        if v == 0.0:
            continue
        view.write_leaf(lf, v * a.factor)
        changed += 1
    if not changed:
        sys.exit("no float parameters matched")
    _patch_and_install(src, packs, {fname},
                       f"{a.object} x{a.factor} ({changed} floats" + (f" matching {a.match!r}" if a.match else "") + ")")
    print("Play ~10 min, note what feels different, then:")
    print(f'  python tools/gameplay_tune.py log --note "{a.object} x{a.factor}{(" " + a.match) if a.match else ""}: <your verdict>"')
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
    p = sub.add_parser("get", help="read a parameter by name")
    p.add_argument("object")
    p.add_argument("path", nargs="?")
    p = sub.add_parser("set", help="set parameters by name and install")
    p.add_argument("items", nargs="+", help="[object] path=value ...  or object.path=value ...")
    p.add_argument("--stack", action="store_true", help="edit on top of the installed pack instead of pristine")
    p = sub.add_parser("apply", help="apply a JSON batch of edits and install")
    p.add_argument("file")
    p.add_argument("--stack", action="store_true")
    sub.add_parser("diff", help="installed vs pristine, by field name")
    p = sub.add_parser("scale", help="probe: scale every float of one object")
    p.add_argument("--object", required=True, help="e.g. ball, basePosition, shoot, moveMatching")
    p.add_argument("--factor", type=float, required=True, help="e.g. 0.9 or 1.15")
    p.add_argument("--match", default=None, help="only paths containing this text")
    p.add_argument("--stack", action="store_true")
    p = sub.add_parser("log")
    p.add_argument("--note", required=True)
    a = ap.parse_args()
    return {"status": cmd_status, "install": cmd_install, "blend": cmd_blend, "restore": cmd_restore,
            "capture": cmd_capture, "selftest": cmd_selftest, "get": cmd_get, "set": cmd_set,
            "apply": cmd_apply, "diff": cmd_diff, "scale": cmd_scale, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
