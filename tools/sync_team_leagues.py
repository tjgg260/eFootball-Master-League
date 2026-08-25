#!/usr/bin/env python3
"""
sync_team_leagues.py — teams.league_id follows build/catalog.json, because the catalog is where
league structure is decided.

build_catalog says it plainly: the FM export's Division column was garbage, so RFS's competition
tables are the structural truth and the catalog is their compiled form. teams.league_id was left
behind by that decision and drifted — Turkish clubs carrying 3000068 beside 68, Serie C clubs
carrying 2017 or nothing at all. When the country-synonym fix admitted 107 more clubs to their
leagues, 42 of them landed in a catalog league while still holding no league_id, and the gate
called it: a catalog club with no league.

For every club the catalog lists, write the league it is listed in, and mint the leagues row when
it is missing. Clubs outside the catalog are not touched — their league_id is not the catalog's
business.

    python tools/sync_team_leagues.py --dry
    python tools/sync_team_leagues.py
then: validate_db.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    cat = json.loads(CAT.read_text(encoding="utf-8"))

    have_league = {i for (i,) in con.execute("SELECT id FROM leagues")}
    cur_lid = dict(con.execute("SELECT id, league_id FROM teams"))

    want, new_leagues = [], []
    for co in cat["countries"]:
        for lg in co["leagues"]:
            lid = lg["league_id"]
            if lid not in have_league:
                new_leagues.append((lid, lg["name"], lg.get("tier") or 1))
                have_league.add(lid)
            for t in lg["teams"]:
                tid = t["team_id"]
                if cur_lid.get(tid) != lid:
                    want.append((lid, tid))

    missing = sum(1 for lid, tid in want if cur_lid.get(tid) is None)
    print(f"catalog clubs whose league_id is wrong or absent: {len(want):,} "
          f"(absent: {missing:,}) | leagues rows to mint: {len(new_leagues)}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not want and not new_leagues:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preleagues")
    cur.execute("BEGIN")
    cur.executemany("INSERT OR IGNORE INTO leagues(id, name, tier) VALUES(?,?,?)", new_leagues)
    cur.executemany("UPDATE teams SET league_id=? WHERE id=?", want)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(want):,} clubs pointed at their catalog league.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
