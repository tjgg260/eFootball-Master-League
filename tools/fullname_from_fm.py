#!/usr/bin/env python3
"""
fullname_from_fm.py — upgrade surname-only names to FULL names through the identity spine.
~15% of squad players carry RFS-style stubs ('Kenny', 'Kadlec V.') while their FM twin knows the
real name ('Amario Cozier-Duberry'). Name priority stays eF > FM: eFootball-native records are
never touched; only RFS/curated records with a KNOWN fm identity and a clearly-worse name are
upgraded, and only when the FM name is a genuine full name that doesn't collide inside the squad.

    python tools/fullname_from_fm.py --dry
    python tools/fullname_from_fm.py
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

STUB = re.compile(r"(^\S+$)|(^\S+ [A-Z]\.?$)|(^[A-Z]\.? \S+$)")   # 'Kenny' | 'Kadlec V.' | 'V. Kadlec'


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    # FM full names by uid — from the net-new FM rows AND the raw export CSVs, because most
    # face-derived spine links point at uids we never imported as player rows.
    fm_name = {pid - 10_000_000_000: nm for pid, nm in con.execute(
        "SELECT id, name FROM players WHERE id>=10000000000 AND id<45000000000 "
        "AND name LIKE '% %'")}
    import csv
    for src in (REPO / "allavailable columns players.csv", REPO / "allplayers.csv"):
        if not src.exists():
            continue
        with open(src, encoding="cp1252", errors="replace", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                u, nm = (r.get("Unique ID") or "").strip(), (r.get("Name") or "").strip()
                if u.lstrip("-").isdigit() and " " in nm:
                    fm_name.setdefault(int(u), nm)
    print(f"FM full names available: {len(fm_name):,}")

    # candidates: NON-eF squad players with a spine fm identity and a stub name
    rows = con.execute("""
        SELECT p.id, p.name, pi.fm_uid, s.team_id
        FROM players p
        JOIN player_identity pi ON pi.player_id = p.id AND pi.fm_uid IS NOT NULL
        JOIN (SELECT DISTINCT player_id, MIN(team_id) team_id FROM squad_members GROUP BY player_id) s
             ON s.player_id = p.id
        WHERE p.id >= 700000000 AND pi.kind IN ('rfs', 'curated')""").fetchall()

    # in-squad name sets to refuse collisions (gate assertion 5 must stay green)
    squad_names: dict[int, set] = {}
    for tid, nm in con.execute("SELECT s.team_id, p.name FROM squad_members s "
                               "JOIN players p ON p.id=s.player_id"):
        squad_names.setdefault(tid, set()).add(nm)

    updates, skipped_collide = [], 0
    for pid, nm, fu, tid in rows:
        if not STUB.match(nm or ""):
            continue
        full = fm_name.get(fu)
        if not full or full == nm:
            continue
        # the stub must actually appear in the full name (safety against a bad spine link)
        stub_last = re.sub(r"[^a-z]", "", (nm or "").replace(" ", "").lower())[:12]
        if stub_last[:5] and stub_last[:5] not in re.sub(r"[^a-z]", "", full.lower()):
            continue
        if full in squad_names.get(tid, set()):
            skipped_collide += 1
            continue
        squad_names.setdefault(tid, set()).add(full)
        updates.append((full, pid))

    print(f"stub names upgradable to FM full names: {len(updates):,} "
          f"(collision-skipped: {skipped_collide})")
    if dry:
        for full, pid in updates[:10]:
            old = con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()[0]
            print(f"  {old!r} -> {full!r}")
        return 0
    shutil.copy2(DB, str(DB) + ".bak-prenames")
    con.executemany("UPDATE players SET name=? WHERE id=?", updates)
    con.commit()
    print(f"upgraded {len(updates):,} names.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
