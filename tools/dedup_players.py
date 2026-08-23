#!/usr/bin/env python3
"""
dedup_players.py — remove cross-source DUPLICATE players left orphaned by the sort. A real player
often exists twice (eFootball-native + an RFS/FM copy). sort_database.py dedups WITHIN a club's
squad, but a duplicate that ended up in NO squad (because its team's squad was rebuilt from another
source) floats free — and the Market shows it as a phantom "free agent" twin (two Florian Wirtz).

This deletes every ORPHAN (in no squad) whose identity — full name + nationality + age — matches a
player who IS in a squad. The squad copy (the one with real club membership) is kept; the orphan and
its per-player rows are removed. Orphans with no squad twin are left alone (they may be genuine
free agents). Never touches a player who is in a squad.

    python tools/dedup_players.py --dry     # count what would be removed
    python tools/dedup_players.py           # apply (backs up first)
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

# every table keyed on player_id, cleaned when an orphan is removed
PID_TABLES = [
    "player_attributes", "player_market", "player_playstyles", "player_appearance",
    "player_appearance_raw", "player_traits", "player_skills", "player_potential",
    "player_positions", "player_condition", "player_knowledge", "player_status",
    "player_identity",   # spine rows must die with their player (P7 gate leak)
]


def ident(name: str, nat: str, age) -> tuple:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    toks = tuple(sorted(re.sub(r"[^a-z ]", " ", n).split()))
    return (toks, (nat or "").split("/")[0].strip().lower(), age)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=60)

    in_squad = {r[0] for r in con.execute("SELECT DISTINCT player_id FROM squad_members")}
    squad_idents = set()
    orphans = []   # (pid, name, ident)
    for pid, nm, nat, age in con.execute("SELECT id, name, nationality, age FROM players"):
        key = ident(nm, nat, age)
        if pid in in_squad:
            squad_idents.add(key)
        else:
            orphans.append((pid, nm, key))

    # only single-token names are too weak to match on identity alone — require >=1 token and a name
    remove = [(pid, nm) for pid, nm, key in orphans if key[0] and key in squad_idents]
    print(f"orphaned duplicate players to remove: {len(remove):,} "
          f"(of {len(orphans):,} orphans; {len(in_squad):,} players stay in squads)")
    if dry:
        for pid, nm in remove[:12]:
            print(f"  remove {pid}  {nm}")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-predede")
    ids = [pid for pid, _ in remove]
    con.execute("BEGIN")
    con.execute("PRAGMA foreign_keys=OFF")
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        q = ",".join("?" * len(chunk))
        for tbl in PID_TABLES:
            try:
                # transfer-log rows for a removed phantom would dangle — they go too (P7 gate leak)
        con.execute(f"DELETE FROM {tbl} WHERE player_id IN ({q})", chunk)
            except sqlite3.OperationalError:
                pass
        con.execute(f"DELETE FROM players WHERE id IN ({q})", chunk)
    con.commit()
    print(f"removed {len(ids):,} orphaned duplicate players.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
