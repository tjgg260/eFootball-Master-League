#!/usr/bin/env python3
"""
fix_club_display_names.py — a club in a top division should carry its own name.

merge_duplicate_clubs consolidated the doubled club records correctly (Konami's empty AC Milan
record was drained into the RFS record that actually holds Maignan and Leao), but the survivor
kept the RFS *nickname*: Serie A fields 'Casciavit' and 'Blu-neri', Ligue 1 fields 'PSG 2' and
'Marseille 2'. The squads behind those names are right; only the label is wrong.

build/catalog.json carries the display name for every league slot and is the better source here.
FM's registry is not — it stores short forms ('PSG', 'Inter', 'Wolves'). So:

  - teams.name and the catalog name conflict outright  -> take the catalog name
  - teams.name is the catalog name plus a bare number   -> take the catalog name ('Rennes 2')
  - teams.name is the catalog name plus real words      -> keep it ('Stade Rennais FC' beats 'Rennes')

EXPLICIT holds the handful where both sources are weak and the club's real name is not in dispute.

    python tools/fix_club_display_names.py --dry
    python tools/fix_club_display_names.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

# 'Club de Lyon' is a Florida side; the catalog's 'Lyon' and Konami's drained 'Olympique Lyon'
# record both point at the same club, whose name is not ambiguous.
EXPLICIT = {3130433: "Olympique Lyonnais"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    nm = dict(con.execute("SELECT id, name FROM teams"))

    changes = []
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                tid = t["team_id"]
                cname = (t.get("name") or "").strip()
                dbname = (nm.get(tid) or "").strip()
                if tid in EXPLICIT:
                    if dbname != EXPLICIT[tid]:
                        changes.append((EXPLICIT[tid], tid, dbname, "explicit"))
                    continue
                if not cname or not dbname or cname == dbname:
                    continue
                a, b = norm(cname), norm(dbname)
                if set(a) == set(b):
                    continue
                if set(a) <= set(b):
                    extra = set(b) - set(a)
                    if all(x.isdigit() and len(x) <= 2 for x in extra):
                        changes.append((cname, tid, dbname, "numbered"))
                    continue                                  # more specific name: keep it
                if set(b) <= set(a):
                    changes.append((cname, tid, dbname, "fuller"))
                    continue
                changes.append((cname, tid, dbname, "conflict"))

    print(f"catalog clubs to rename: {len(changes)}")
    for new, tid, old, why in changes:
        print(f"   {tid}  {old!r} -> {new!r}   ({why})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not changes:
        return 0
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prenames")
    con.executemany("UPDATE teams SET name=? WHERE id=?", [(n, t) for n, t, _o, _w in changes])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(changes)} clubs renamed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
