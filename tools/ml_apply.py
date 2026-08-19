#!/usr/bin/env python3
"""
ml_apply.py — read, edit and repack eFootball's PlayerAssignment.bin.

This is the Phase 4 writeback path in miniature: decrypt the WESYS container, edit records,
validate the result, and only then write. It never edits the game's files directly — it works
on an extracted tree and rebuilds a CPK from it.

Safety rules, enforced not documented:
  * every write is preceded by a byte-exact round-trip proof on the ORIGINAL bytes
  * every write takes a timestamped backup first
  * squad legality is validated before anything is written; failure aborts the write
  * the WESYS key nibble and zlib level are taken from the source file, never assumed

WESYS decryption comes from vendored Sider code (GPL-3.0) — see tools/vendor/sider/.
That licence is why this repository is GPL-3.0.

Usage:
    python tools/ml_apply.py inspect
    python tools/ml_apply.py squad --team 102
    python tools/ml_apply.py transfer --pid 137924 --to 102 --shirt 18 \
                                      --swap-pid 127322 --swap-shirt 29
    python tools/ml_apply.py build-cpk --out dt200_console_all.cpk
"""
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))

import wesys  # noqa: E402  (vendored, path set above)
import pesdb  # noqa: E402

BINS = REPO / "bins"
ASSIGNMENT_BIN = BINS / "common" / "etc" / "pesdb" / "PlayerAssignment.bin"
BACKUP_DIR = Path.home() / "Backups" / "eFootball"
CPKMAKEC = REPO / "CRI_File_System_Tools_v2.40.13.0" / "crifilesystem v2.40.13.0" / "cpkmakec.exe"

REC = pesdb.ASSIGNMENT_RECORD_SIZE  # 24

# v1 record layout, confirmed against a real export of all 23,687 rows.
OFF_RECORD_ID = 0
OFF_PLAYER_ID = 8
OFF_TEAM_ID = 16
OFF_SHIRT = 20   # stored 0-based: shirt number minus one
OFF_SORT_KEY = 21   # squad slot times four
OFF_ROLE = 22

SLOT_STRIDE = 4


class ApplyError(RuntimeError):
    pass


# --------------------------------------------------------------------------- load / save

def load() -> tuple[bytes, bytearray, int]:
    """Returns (original container bytes, mutable payload, key nibble)."""
    if not ASSIGNMENT_BIN.exists():
        raise ApplyError(f"Not found: {ASSIGNMENT_BIN}\nExtract the CPK first.")
    blob = ASSIGNMENT_BIN.read_bytes()
    if not wesys.is_wesys_container(blob):
        raise ApplyError("Not a WESYS container — is this file already unwrapped?")
    payload = wesys.unpack_wesys_payload(blob)
    if len(payload) % REC:
        raise ApplyError(f"Payload {len(payload)} is not a multiple of {REC}")
    return blob, bytearray(payload), blob[1] & 0x0F


def prove_round_trip(blob: bytes, payload: bytes, nibble: int) -> int:
    """
    Find the zlib level that reproduces the source file byte for byte, and fail if none does.

    This runs against the UNMODIFIED payload. If we cannot rebuild the original exactly, we do
    not understand the format well enough to be trusted with an edit, and nothing is written.
    """
    for level in range(10):
        if wesys.pack_wesys_container(payload, key_nibble=nibble, compression_level=level) == blob:
            return level
    raise ApplyError(
        "Round-trip proof FAILED: no zlib level reproduces the original file.\n"
        "Refusing to write. The container format may have changed in a game patch.")


def save(payload: bytes, nibble: int, level: int) -> None:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"PlayerAssignment.bin.{stamp}"
    shutil.copy2(ASSIGNMENT_BIN, backup)

    packed = wesys.pack_wesys_container(payload, key_nibble=nibble, compression_level=level)
    if wesys.unpack_wesys_payload(packed) != payload:
        raise ApplyError("Repacked container does not decode to our edit. Nothing written.")

    ASSIGNMENT_BIN.write_bytes(packed)
    print(f"  backup  {backup}")
    print(f"  written {ASSIGNMENT_BIN}  ({len(packed):,} bytes)")


# --------------------------------------------------------------------------- record access

def records(payload: bytes) -> list[dict]:
    return pesdb.parse_player_assignment_bin(bytes(payload))


def find(payload: bytes, pid: int, team: int | None = None) -> list[dict]:
    hits = [r for r in records(payload) if r["player_id"] == pid]
    if team is not None:
        hits = [r for r in hits if r["team_id"] == team]
    return hits


def write_record(payload: bytearray, index: int, *, team_id: int, shirt: int, slot: int) -> None:
    base = index * REC
    if not 1 <= shirt <= 99:
        raise ApplyError(f"Shirt {shirt} out of range 1-99")
    if slot * SLOT_STRIDE > 0xFF:
        raise ApplyError(f"Slot {slot} too large to encode")
    struct.pack_into("<I", payload, base + OFF_TEAM_ID, team_id)
    payload[base + OFF_SHIRT] = shirt - 1
    payload[base + OFF_SORT_KEY] = slot * SLOT_STRIDE


# --------------------------------------------------------------------------- validation

def validate(payload: bytes, teams: set[int]) -> list[str]:
    """Squad legality for the touched clubs. Mirrors ML.Core's WorldInvariants."""
    problems: list[str] = []
    by_team: dict[int, list[dict]] = {}
    for r in records(payload):
        by_team.setdefault(r["team_id"], []).append(r)

    for team in sorted(teams):
        squad = by_team.get(team, [])
        if not squad:
            problems.append(f"team {team}: no players")
            continue

        shirts = [r["shirt_number"] for r in squad]
        dupes = {s for s in shirts if shirts.count(s) > 1}
        if dupes:
            problems.append(f"team {team}: duplicate shirt number(s) {sorted(dupes)}")

        slots = [r["sort_key"] for r in squad]
        if len(set(slots)) != len(slots):
            problems.append(f"team {team}: duplicate squad slots")

        pids = [r["player_id"] for r in squad]
        if len(set(pids)) != len(pids):
            problems.append(f"team {team}: same player listed twice")

    # A player must not hold two places in the same squad anywhere in the file.
    seen: set[tuple[int, int]] = set()
    for r in records(payload):
        key = (r["player_id"], r["team_id"])
        if key in seen:
            problems.append(f"player {r['player_id']} appears twice in team {r['team_id']}")
        seen.add(key)

    return problems


# --------------------------------------------------------------------------- commands

def cmd_inspect(_args) -> int:
    blob, payload, nibble = load()
    level = prove_round_trip(blob, bytes(payload), nibble)
    recs = records(payload)
    teams = {r["team_id"] for r in recs}
    print(f"file        {ASSIGNMENT_BIN}")
    print(f"container   {len(blob):,} bytes, header {blob[:3].hex()}, key nibble {nibble}")
    print(f"payload     {len(payload):,} bytes = {len(recs):,} records of {REC}")
    print(f"layout      {pesdb.detect_assignment_layout(bytes(payload))}")
    print(f"round-trip  byte-exact at zlib level {level}")
    print(f"teams       {len(teams):,}   players {len({r['player_id'] for r in recs}):,}")
    return 0


def cmd_squad(args) -> int:
    _, payload, _ = load()
    squad = sorted(
        (r for r in records(payload) if r["team_id"] == args.team),
        key=lambda r: r["shirt_number"])
    if not squad:
        print(f"No players in team {args.team}")
        return 1
    print(f"Team {args.team}: {len(squad)} players")
    for r in squad:
        cap = " (C)" if r["is_captain"] else ""
        print(f"  {r['shirt_number']:>3}  slot {r['sort_key'] // SLOT_STRIDE:>3}  "
              f"pid {r['player_id']:<10}{cap}")
    used = {r["shirt_number"] for r in squad}
    print(f"  free shirts: {', '.join(str(n) for n in range(1, 41) if n not in used)}")
    return 0


def cmd_transfer(args) -> int:
    blob, payload, nibble = load()
    level = prove_round_trip(blob, bytes(payload), nibble)
    print(f"round-trip proven byte-exact at zlib level {level}")

    moves = [(args.pid, args.to, args.shirt)]
    if args.swap_pid is not None:
        moves.append((args.swap_pid, None, args.swap_shirt))  # destination resolved below

    # Resolve the club rows. A player has one row per squad (club AND country), so we must
    # pick the row whose team is a club side, never the international one.
    primary = find(payload, args.pid)
    if not primary:
        raise ApplyError(f"Player {args.pid} not found")
    if args.from_team is not None:
        matching = [r for r in primary if r["team_id"] == args.from_team]
        if not matching:
            detail = ", ".join(f"team {r['team_id']}" for r in primary)
            raise ApplyError(
                f"Player {args.pid} is not in team {args.from_team}. Rows: {detail}")
        src = matching[0]
    else:
        candidates = [r for r in primary if r["team_id"] != args.to]
        if len(candidates) != 1:
            detail = ", ".join(f"team {r['team_id']} shirt {r['shirt_number']}" for r in primary)
            raise ApplyError(
                f"Player {args.pid} has {len(primary)} rows ({detail}).\n"
                "One is their country, one their club — pass --from-team to say which to move.")
        src = candidates[0]
    from_team = src["team_id"]

    if args.swap_pid is None:
        raise ApplyError("A straight move changes squad sizes. Pass --swap-pid to exchange.")

    swap_rows = [r for r in find(payload, args.swap_pid) if r["team_id"] == args.to]
    if len(swap_rows) != 1:
        raise ApplyError(f"Player {args.swap_pid} is not in team {args.to}")
    swap = swap_rows[0]

    print(f"  {args.pid}: team {from_team} shirt {src['shirt_number']} "
          f"-> team {args.to} shirt {args.shirt} slot {swap['sort_key'] // SLOT_STRIDE}")
    print(f"  {args.swap_pid}: team {args.to} shirt {swap['shirt_number']} "
          f"-> team {from_team} shirt {args.swap_shirt} slot {src['sort_key'] // SLOT_STRIDE}")

    # Exchange places: each takes the other's slot, keeping both squads the same size and
    # their slot ranges contiguous.
    write_record(payload, src["index"], team_id=args.to,
                 shirt=args.shirt, slot=swap["sort_key"] // SLOT_STRIDE)
    write_record(payload, swap["index"], team_id=from_team,
                 shirt=args.swap_shirt, slot=src["sort_key"] // SLOT_STRIDE)

    problems = validate(bytes(payload), {args.to, from_team})
    if problems:
        print("\nVALIDATION FAILED — nothing written:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("validation passed")

    if args.dry_run:
        print("dry run: not written")
        return 0
    save(bytes(payload), nibble, level)
    return 0


def cmd_build_cpk(args) -> int:
    if not CPKMAKEC.exists():
        raise ApplyError(f"cpkmakec not found at {CPKMAKEC}")
    out = Path(args.out).resolve()
    cmd = [str(CPKMAKEC), str(BINS), str(out), f"-mode={args.mode}", f"-align={args.align}", "-view"]
    print("  " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode
    print(f"built {out} ({out.stat().st_size:,} bytes)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inspect", help="decrypt and summarise the assignment file")

    p = sub.add_parser("squad", help="list a club's squad and its free shirt numbers")
    p.add_argument("--team", type=int, required=True)

    p = sub.add_parser("transfer", help="exchange two players between clubs")
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--to", type=int, required=True, help="destination team id")
    p.add_argument("--shirt", type=int, required=True)
    p.add_argument("--from-team", type=int, default=None, dest="from_team")
    p.add_argument("--swap-pid", type=int, default=None, dest="swap_pid")
    p.add_argument("--swap-shirt", type=int, default=None, dest="swap_shirt")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("build-cpk", help="rebuild a CPK from bins/ via cpkmakec")
    p.add_argument("--out", required=True)
    p.add_argument("--mode", default="FILENAME")
    p.add_argument("--align", type=int, default=2048)

    args = ap.parse_args()
    try:
        return {
            "inspect": cmd_inspect,
            "squad": cmd_squad,
            "transfer": cmd_transfer,
            "build-cpk": cmd_build_cpk,
        }[args.cmd](args)
    except ApplyError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
