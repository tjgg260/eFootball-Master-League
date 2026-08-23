#!/usr/bin/env python3
"""
dedupe_players.py — collapse the same real player appearing across our data layers into ONE
canonical row, keeping the highest-priority source's version:

    eFootball (dt870 > dt200)  >  RFS  >  Football Manager

Cross-source identity is the FM Unique ID: the facepack matcher stamped every matched player with
face_<UID>.png, so two rows carrying the same UID are the same person. We group by that UID; when a
group spans more than one source we keep the top-priority row, REMAP squad_members (and any refs)
from the discarded rows onto the kept row so squads stay intact, then delete the discarded rows and
their attributes. Players without a face-UID are left untouched (no risky name-only merging), and
career rows (the mutable career world, ids 20M–<700M) are never touched.

Dry run by default; --apply writes (back up master.db first).
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
EF_MAX = 16_700_000          # eFootball base PIDs below this
RFS_BASE = 700_000_000        # RFS import at/above this
FM_BASE = 10_000_000_000      # FM import (when present) at/above this


def source_priority(pid: int) -> int | None:
    """0 eFootball, 1 RFS, 2 FM. None = career/other → excluded from dedup."""
    if pid < EF_MAX:
        return 0
    if RFS_BASE <= pid < FM_BASE:
        return 1
    if pid >= FM_BASE:
        return 2
    return None                # 16.7M..700M = career world, leave alone


def uid_of(real_face_path: str | None) -> int | None:
    if not real_face_path:
        return None
    m = re.search(r"face_(\d+)\.png$", real_face_path)
    return int(m.group(1)) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    rows = con.execute("SELECT id, name, real_face_path FROM players").fetchall()

    by_uid: dict[int, list[tuple[int, int, str]]] = defaultdict(list)  # uid -> [(prio, id, name)]
    for pid, name, face in rows:
        prio = source_priority(pid)
        uid = uid_of(face)
        if prio is not None and uid is not None:
            by_uid[uid].append((prio, pid, name))

    # a group is a duplicate only if it spans >1 source (distinct priorities)
    merges = []  # (keep_id, [discard_ids], name)
    for uid, members in by_uid.items():
        prios = {p for p, _, _ in members}
        if len(members) < 2 or len(prios) < 2:
            continue
        members.sort(key=lambda m: (m[0], m[1]))   # top priority first
        keep = members[0]
        discard = [m[1] for m in members[1:]]
        merges.append((keep[1], discard, keep[2]))

    n_discard = sum(len(d) for _, d, _ in merges)
    print(f"players: {len(rows):,}")
    print(f"cross-source duplicate groups: {len(merges):,}")
    print(f"rows that would be removed (kept canonical stays): {n_discard:,}")
    print("\nsample merges (keep <- discard):")
    for keep_id, discard, name in merges[:8]:
        srcs = []
        for d in discard:
            p = source_priority(d)
            srcs.append({0: "eF", 1: "RFS", 2: "FM"}.get(p, "?"))
        print(f"   {name:22s} keep {keep_id} (eF) <- discard {list(zip(discard, srcs))}")

    if not args.apply:
        print("\n(dry run — pass --apply; back up master.db first)")
        con.close()
        return 0

    con.execute("BEGIN")
    remapped = 0
    for keep_id, discard, _ in merges:
        for d in discard:
            # move squad membership onto the canonical player (skip if it would collide)
            cur = con.execute(
                "UPDATE OR IGNORE squad_members SET player_id=? WHERE player_id=?", (keep_id, d))
            remapped += cur.rowcount
            con.execute("DELETE FROM squad_members WHERE player_id=?", (d,))
            con.execute("DELETE FROM player_attributes WHERE player_id=?", (d,))
            for tbl in ("player_skills", "player_playstyles", "player_appearance",
                        "player_appearance_raw", "player_condition"):
                try:
                    con.execute(f"DELETE FROM {tbl} WHERE player_id=?", (d,))
                except sqlite3.OperationalError:
                    pass
            con.execute("DELETE FROM players WHERE id=?", (d,))
    con.commit()
    print(f"\nremoved {n_discard:,} duplicate rows; remapped {remapped:,} squad memberships to canonical.")
    print(f"players now: {con.execute('SELECT COUNT(*) FROM players').fetchone()[0]:,}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
