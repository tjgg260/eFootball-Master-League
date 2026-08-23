#!/usr/bin/env python3
"""
rfs_managers_link.py — assign a manager to every RFS club in master.db.

RFS.DB has no explicit manager->club field (verified: teams @109 is a country/league code, not a
manager id). So we assign HEURISTICALLY but sensibly: each club gets a DISTINCT manager whose
nationality matches the club's country, falling back to any unused manager when a nation runs out.

Signals decoded from RFS.DB:
    teams:    country/league code  u16 @109
    managers: name @2 (40B),  nationality code u16 @45   (same code space as the team country)

Managers are written into the existing `staff` table as (team_id, role='Manager', name). Writes
only master.db. Idempotent (clears prior RFS 'Manager' staff rows first). This is a plausible
assignment, not RFS ground truth — labelled as such.
"""
from __future__ import annotations

import sqlite3
import struct
import sys
from collections import defaultdict, deque
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb   # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
T_BASE = 3_000_000


def main() -> int:
    db = RfsDb(RFS_DB)
    tt, mg = db.tables["teams"], db.tables["managers"]

    teams = []                       # (plain_id, country, name)
    for i in range(tt.rows):
        r = db.record("teams", i)
        tid = struct.unpack_from("<I", r, 0)[0]
        country = struct.unpack_from("<H", r, 109)[0]
        name = r[36:36 + 32].split(b"\0")[0].decode("utf-8", "replace").strip()
        if name:
            teams.append((tid, country, name))

    by_nat = defaultdict(deque)       # nationality -> queue of manager names
    allmgr = deque()
    for i in range(mg.rows):
        r = db.record("managers", i)
        nm = r[2:2 + 40].split(b"\0")[0].decode("utf-8", "replace").strip()
        nat = struct.unpack_from("<H", r, 45)[0]
        if nm:
            by_nat[nat].append(nm)
            allmgr.append(nm)

    # assign, preferring nationality match, each manager used once
    used = set()
    assignments = []                  # (team_id, manager_name)
    for tid, country, tname in teams:
        pick = None
        q = by_nat.get(country)
        while q:
            cand = q.popleft()
            if cand not in used:
                pick = cand
                break
        if pick is None:              # fall back to any unused manager
            while allmgr:
                cand = allmgr.popleft()
                if cand not in used:
                    pick = cand
                    break
        if pick:
            used.add(pick)
            assignments.append((T_BASE + tid, pick))

    con = sqlite3.connect(DB)
    con.execute("BEGIN")
    con.execute("DELETE FROM staff WHERE role='Manager' AND team_id >= ?", (T_BASE,))
    con.executemany("INSERT INTO staff(team_id,role,name) VALUES(?,'Manager',?)", assignments)
    con.commit()

    nat_matched = sum(1 for (tid, country, _), (_, m) in zip(teams, assignments)) if False else None
    print(f"Managers assigned to {len(assignments)} clubs (nationality-matched where possible).")
    for name in ("Arsenal FC", "Real Madrid", "Bayern Munich", "Juventus FC"):
        row = con.execute(
            "SELECT s.name FROM teams t JOIN staff s ON s.team_id=t.id "
            "WHERE t.name=? AND s.role='Manager' LIMIT 1", (name,)).fetchone()
        print(f"  {name:16s} -> {row[0] if row else '(none)'}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
