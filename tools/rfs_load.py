#!/usr/bin/env python3
"""
rfs_load.py — load RFS players eFootball DOESN'T have into the master DB.

The rule (user's): never overwrite eFootball's existing players — they carry real faces and
official data. Only ADD the RFS players whose name is NOT already in eFootball, so the master DB
gains the coverage eFootball lacks (lower leagues, etc.) without degrading what's there.

Net-new players get a fresh game_pid from the 9,000,000+ block (below the 2^24 variant boundary),
their eFootball position + overall + translated abilities. They're authored into a CPK only when
a fixture that uses them is compiled — the master DB holds the whole universe; each match compiles
just its two squads.

Creates/updates a file-based master DB (default build/master.db) using ML.Data's schema.
"""
from __future__ import annotations

import sqlite3
import sys
import csv as _csv
import io
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb          # noqa: E402
from rfs_translate import translate   # noqa: E402

PID_BASE = 9_000_000


def existing_efootball_names() -> set[str]:
    """Names already in eFootball (from the bundled 42k CSV). Case/space-normalised."""
    path = REPO / "samples" / "editor-bundled-players.csv"
    rows = _csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig")))
    return {r["player_name"].strip().lower() for r in rows if r["player_name"].strip()}


def open_master(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript((REPO / "src" / "ML.Data" / "schema.sql").read_text(encoding="utf-8"))
    return con


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build" / "master.db"
    rfs = RfsDb(Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB")
    have = existing_efootball_names()
    con = open_master(db_path)

    t = rfs.tables["players"]
    next_pid = PID_BASE + 1
    added = skipped = 0
    seen: set[str] = set()

    con.execute("BEGIN")
    for i in range(t.rows):
        rec = rfs.record("players", i)
        p = translate(rec)
        key = p["name"].strip().lower()
        if not key:
            continue
        if key in have or key in seen:      # already in eFootball, or a dup within RFS
            skipped += 1
            continue
        seen.add(key)

        pid = next_pid
        next_pid += 1
        con.execute(
            "INSERT OR IGNORE INTO players(id,game_pid,is_custom,name,position,overall_rating) "
            "VALUES(?,?,1,?,?,?)",
            (pid, pid, p["name"], p["position"], p["overall"]))
        con.executemany(
            "INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
            [(pid, a, v) for a, v in p["abilities"].items()])
        added += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    print(f"RFS players scanned: {t.rows:,}")
    print(f"  skipped (already in eFootball or dup): {skipped:,}")
    print(f"  ADDED (net-new): {added:,}")
    print(f"master DB now holds {total:,} players -> {db_path}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
