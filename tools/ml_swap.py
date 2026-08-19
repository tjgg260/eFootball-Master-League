#!/usr/bin/env python3
"""
ml_swap.py — move players between clubs by EXCHANGING SLOT OCCUPANTS.

The thing that took a whole evening to learn: PlayerAssignment is a POSITIONAL format.
A record's club is its physical position in the file, not the value in its TeamID column.
Rewriting TeamID leaves the record stranded in the old club's block, and the game — which
walks records in order collecting each squad — picks it up in the wrong place. Do that to a
Liverpool record and the displaced player is collected first, i.e. put in goal.

So a transfer never edits TeamID, Slot or RowNum. It swaps WHO OCCUPIES two existing
records. Both squads keep their size, their contiguous slots and their file ordering by
construction, because none of those fields is touched.

Sider's pesdb.py has nine readers and exactly one writer — replace_team_squad, and all it
writes is player_id. That is not a missing feature. That is the format telling you what the
only legal edit is.

Usage:
    python tools/ml_swap.py --csv PlayerAssignment.csv --a 126918 --b 122012
    python tools/ml_swap.py --csv PlayerAssignment.csv --a 126918 --b 122012 --apply
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
import sys
from datetime import datetime
from pathlib import Path

FIELDS = ["PlayerID", "Name", "TeamID", "SquadNumber", "Slot", "Role", "RowNum"]


def load(path: Path) -> list[dict]:
    text = path.read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def dump(path: Path, rows: list[dict]) -> None:
    """Write back exactly as the editor exported it: UTF-8 BOM, CRLF, no trailing blank."""
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def club_row(rows: list[dict], pid: int) -> dict:
    """
    The club record, not the international one. A player has one row per squad; the national
    side must never be touched by a transfer.
    """
    hits = [r for r in rows if int(r["PlayerID"]) == pid]
    if not hits:
        raise SystemExit(f"player {pid} not found")
    if len(hits) == 1:
        return hits[0]

    # National sides sit in a contiguous low block of team ids; clubs follow. Rather than
    # hardcode a boundary, take the row whose squad is the larger one — club squads carry
    # 30-40 players, international call-ups around 26.
    sized = sorted(hits, key=lambda r: sum(1 for x in rows if x["TeamID"] == r["TeamID"]))
    return sized[-1]


def squad(rows: list[dict], team: str) -> list[dict]:
    return sorted((r for r in rows if r["TeamID"] == team), key=lambda r: int(r["Slot"]))


def check(rows: list[dict], teams: set[str]) -> list[str]:
    problems = []
    for t in sorted(teams):
        sq = squad(rows, t)
        slots = [int(r["Slot"]) for r in sq]
        shirts = [int(r["SquadNumber"]) for r in sq]
        if slots != list(range(len(sq))):
            problems.append(f"team {t}: slots not 0..{len(sq)-1}")
        if len(set(shirts)) != len(shirts):
            dup = sorted({s for s in shirts if shirts.count(s) > 1})
            problems.append(f"team {t}: duplicate shirt(s) {dup}")
        idx = [i for i, r in enumerate(rows) if r["TeamID"] == t]
        if idx != list(range(idx[0], idx[0] + len(idx))):
            problems.append(f"team {t}: rows not physically contiguous")
        order = [int(rows[i]["Slot"]) for i in idx]
        if order != sorted(order):
            problems.append(f"team {t}: slot order does not follow file order")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--a", type=int, required=True, help="PID of the player moving in")
    ap.add_argument("--b", type=int, required=True, help="PID of the player he swaps with")
    ap.add_argument("--apply", action="store_true", help="write the file (default: dry run)")
    args = ap.parse_args()

    path = Path(args.csv)
    rows = load(path)

    ra, rb = club_row(rows, args.a), club_row(rows, args.b)
    if ra["TeamID"] == rb["TeamID"]:
        raise SystemExit("both players are already at the same club")

    print(f"  {ra['Name']}  team {ra['TeamID']} shirt {ra['SquadNumber']} slot {ra['Slot']}"
          f"   ->  team {rb['TeamID']} shirt {rb['SquadNumber']} slot {rb['Slot']}")
    print(f"  {rb['Name']}  team {rb['TeamID']} shirt {rb['SquadNumber']} slot {rb['Slot']}"
          f"   ->  team {ra['TeamID']} shirt {ra['SquadNumber']} slot {ra['Slot']}")

    # Exchange occupants only. TeamID / Slot / RowNum stay with the RECORD, and each player
    # inherits the shirt of the man he replaces, so a collision is impossible by construction.
    (ra["PlayerID"], rb["PlayerID"]) = (rb["PlayerID"], ra["PlayerID"])
    (ra["Name"], rb["Name"]) = (rb["Name"], ra["Name"])

    problems = check(rows, {ra["TeamID"], rb["TeamID"]})
    if problems:
        print("\nVALIDATION FAILED - nothing written:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("validation passed: slots contiguous, shirts unique, blocks contiguous, order intact")

    if not args.apply:
        print("dry run: not written (pass --apply)")
        return 0

    backup = path.with_suffix(f".{datetime.now():%Y%m%d-%H%M%S}.bak")
    shutil.copy2(path, backup)
    dump(path, rows)
    print(f"  backup  {backup.name}")
    print(f"  written {path}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
