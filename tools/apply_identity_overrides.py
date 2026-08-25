#!/usr/bin/env python3
"""
apply_identity_overrides.py — re-apply the identity decisions the owner made by hand.

build_identity.py rebuilds the spine from scratch (DELETE FROM player_identity / team_identity),
so a hand-made ruling survives exactly as long as nobody rebuilds. data/identity_overrides.json
holds those rulings with the reasoning behind each, and this re-applies them; build_identity.py
calls it at the end of its own run so a rebuild can no longer silently discard them.

Idempotent, and safe to run at any time.

    python tools/apply_identity_overrides.py --dry
    python tools/apply_identity_overrides.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
FILE = REPO / "data" / "identity_overrides.json"


def apply(con: sqlite3.Connection, verbose: bool = True) -> int:
    """Apply every override to an open connection. Returns how many rows it touched."""
    if not FILE.exists():
        return 0
    spec = json.loads(FILE.read_text(encoding="utf-8"))
    cur = con.cursor()
    n = 0
    for row in spec.get("player_links", []):
        pid = row["player_id"]
        if not cur.execute("SELECT 1 FROM players WHERE id=?", (pid,)).fetchone():
            if verbose:
                print(f"  skip player {pid}: no such record")
            continue
        cur.execute("INSERT OR IGNORE INTO player_identity(player_id, kind, confidence) "
                    "VALUES(?, 'fm', 1.0)", (pid,))
        if row.get("ef_pid") is not None:
            cur.execute("UPDATE player_identity SET ef_pid=?, ef_method='owner', confidence=1.0 "
                        "WHERE player_id=?", (row["ef_pid"], pid))
        if row.get("fm_uid") is not None:
            cur.execute("UPDATE player_identity SET fm_uid=?, fm_method='owner', confidence=1.0 "
                        "WHERE player_id=?", (row["fm_uid"], pid))
        n += 1
    for row in spec.get("team_links", []):
        tid = row["team_id"]
        if not cur.execute("SELECT 1 FROM teams WHERE id=?", (tid,)).fetchone():
            if verbose:
                print(f"  skip team {tid}: no such record")
            continue
        cur.execute("INSERT OR IGNORE INTO team_identity(team_id, confidence) VALUES(?, 1.0)",
                    (tid,))
        cur.execute("UPDATE team_identity SET fm_club_id=?, method='owner', confidence=1.0 "
                    "WHERE team_id=?", (row["fm_club_id"], tid))
        n += 1
    if verbose:
        print(f"owner identity overrides re-applied: {n}")
    return n


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    spec = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    print(f"{FILE.relative_to(REPO)}: {len(spec.get('player_links', [])):,} player links, "
          f"{len(spec.get('team_links', [])):,} team links")
    for row in spec.get("player_links", []):
        print(f"   player {row['player_id']} -> ef {row.get('ef_pid')} fm {row.get('fm_uid')}"
              f"  ({row.get('ruled', '?')})")
    if dry:
        print("--dry: nothing written.")
        return 0
    con = sqlite3.connect(DB, timeout=180)
    apply(con)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
