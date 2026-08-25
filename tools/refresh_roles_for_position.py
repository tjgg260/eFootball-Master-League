#!/usr/bin/env python3
"""
refresh_roles_for_position.py — a playstyle belongs to a position, so a position correction
invalidates it.

fix_positions_from_fm.py moved 80,728 players onto the position FM actually gives them. Their
playstyles stayed where they were, and the render projection then refused 658 catalog clubs:
a 'Target Man' is a centre-forward role and cannot compile onto a midfielder, an 'Attacking
Full-back' cannot compile onto a MID. assign_roles.py alone will not repair this — by design it
only fills a role a player does not already have, so it left every stale pairing in place.

Clear ONLY the rows whose role is incompatible with the player's current position (per the same
two catalogs assign_roles uses, which mirror the Tactics UI), then let assign_roles refill them
by attribute fit. A playstyle that is still legal for the new position is left alone, so a
hand-picked role survives unless the player has moved out from under it.

    python tools/refresh_roles_for_position.py --dry
    python tools/refresh_roles_for_position.py
then: assign_roles.py, validate_db.py
"""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"


def load_catalogs():
    spec = importlib.util.spec_from_file_location("assign_roles", REPO / "tools" / "assign_roles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok = {}
    for name, poss, _attrs in mod.PRIMARY:
        ok[("primary", name)] = set(poss)
    for name, poss, _attrs in mod.SECONDARY:
        ok[("secondary", name)] = set(poss)
    return ok


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    ok = load_catalogs()
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    pos = dict(con.execute("SELECT id, COALESCE(position,'') FROM players"))
    stale, why = [], Counter()
    for pid, style, kind in con.execute(
            "SELECT player_id, playstyle, COALESCE(kind,'primary') FROM player_playstyles"):
        allowed = ok.get((kind, style))
        if allowed is None:
            continue                                  # a role we do not own: leave it
        p = pos.get(pid, "")
        if p and p not in allowed:
            stale.append((pid, style, kind))
            why[(p, style)] += 1

    print(f"playstyle rows incompatible with the player's position: {len(stale):,}")
    for (p, s), n in why.most_common(8):
        print(f"   {p:>4}  carrying '{s}'  {n:,}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not stale:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preroles")
    cur.execute("BEGIN")
    cur.executemany(
        "DELETE FROM player_playstyles WHERE player_id=? AND playstyle=? AND kind=?", stale)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"cleared {len(stale):,} stale roles.")
    print("next: assign_roles.py refills them by attribute fit, then validate_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
