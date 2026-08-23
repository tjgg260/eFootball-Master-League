#!/usr/bin/env python3
"""
rfs_comp_rules.py — import competition RULES from RFS.DB into master.db.

Decoded from RFS's `competformat` (comp_id u16 @0, then the format fields), confirmed across the
big leagues:
    byte 4  = number of teams        (Premier/La Liga/Serie A = 20; Bundesliga/Ligue 1 = 18)
    byte 10 = rounds                 (2 = double round-robin, home & away)
    byte 26 = relegation places      (3 for 20-team leagues, 2 for 18-team; correlates cleanly)
Points are the universal 3 for a win, 1 for a draw (every real league here). We keep the FIRST
format row per competition (multi-stage cups have several).

Stores a league_rules table keyed by league id (= L_BASE + comp_id, matching rfs_competitions),
and mirrors relegation_places onto the leagues row. Writes only master.db. Idempotent.
"""
from __future__ import annotations

import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb   # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
L_BASE = 3_000_000
COMP_ID_OFF = 54


def main() -> int:
    db = RfsDb(RFS_DB)
    cf = db.tables["competformat"]

    first = {}                       # comp_id -> first format row
    for i in range(cf.rows):
        r = db.record("competformat", i)
        cid = struct.unpack_from("<H", r, 0)[0]
        if cid not in first:
            first[cid] = r

    rules = []
    for cid, r in first.items():
        num_teams = r[4]
        rounds = r[10] if r[10] in (1, 2) else 2
        releg = r[26]
        if not (2 <= num_teams <= 64):       # skip cups / malformed rows
            continue
        rules.append((L_BASE + cid, num_teams, rounds, 3, 1, releg))

    con = sqlite3.connect(DB)
    con.execute("BEGIN")
    con.execute("CREATE TABLE IF NOT EXISTS league_rules "
                "(league_id INTEGER PRIMARY KEY, num_teams INTEGER, rounds INTEGER, "
                "points_win INTEGER, points_draw INTEGER, relegation_places INTEGER)")
    con.execute("DELETE FROM league_rules")
    con.executemany("INSERT OR REPLACE INTO league_rules "
                    "(league_id,num_teams,rounds,points_win,points_draw,relegation_places) "
                    "VALUES(?,?,?,?,?,?)", rules)
    for lid, nt, rnd, pw, pd, rel in rules:
        con.execute("UPDATE leagues SET relegation_places=? WHERE id=?", (rel, lid))
    con.commit()

    print(f"Competition rules imported for {len(rules)} leagues.")
    for name in ("Premier League", "Bundesliga", "Serie A", "Eredivisie"):
        row = con.execute(
            "SELECT r.num_teams,r.rounds,r.points_win,r.relegation_places "
            "FROM leagues l JOIN league_rules r ON r.league_id=l.id WHERE l.name=? LIMIT 1",
            (name,)).fetchone()
        if row:
            print(f"  {name:16s} teams={row[0]} rounds={row[1]} win={row[2]}pts releg={row[3]}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
