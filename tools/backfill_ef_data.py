#!/usr/bin/env python3
"""
backfill_ef_data.py — recover eFootball richness the orphan dedup would otherwise drop. When
dedup_players.py removed an eFootball-native orphan and kept its squad twin, the twin sometimes
lacked the orphan's skills / playstyles / traits / appearance / a few attributes. This reads the
PRE-DEDUP backup, maps each removed orphan to its surviving twin (full name + nationality + age),
and GAP-FILLS the twin: copies the orphan's rows for any per-player table the twin is missing, and
fills in any attribute keys the twin lacks. Never overwrites data the twin already has, so curated
values (ratings, faces) stay; nothing eFootball is lost.

    python tools/backfill_ef_data.py --dry
    python tools/backfill_ef_data.py
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
BAK = REPO / "build" / "master.db.bak-predede"

# per-player feature tables to gap-fill wholesale when the twin has none
FEATURE_TABLES = ["player_skills", "player_playstyles", "player_traits",
                  "player_appearance", "player_appearance_raw", "player_potential"]


def ident(nm, nat, age):
    n = unicodedata.normalize("NFKD", nm or "").encode("ascii", "ignore").decode().lower()
    return (tuple(sorted(re.sub(r"[^a-z ]", " ", n).split())), (nat or "").split("/")[0].strip().lower(), age)


def cols(con, tbl):
    return [c[1] for c in con.execute(f"PRAGMA table_info({tbl})")]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    if not BAK.exists():
        sys.exit(f"backup {BAK.name} not found — nothing to recover from")
    cur = sqlite3.connect(DB, timeout=60)
    bak = sqlite3.connect(f"file:{BAK}?mode=ro", uri=True)

    curids = {r[0] for r in cur.execute("SELECT id FROM players")}
    insquad = {r[0] for r in cur.execute("SELECT DISTINCT player_id FROM squad_members")}
    twin = {}
    for pid, nm, nat, age in cur.execute("SELECT id, name, nationality, age FROM players"):
        if pid in insquad:
            twin.setdefault(ident(nm, nat, age), pid)

    # removed orphan -> twin
    pairs = []
    for pid, nm, nat, age in bak.execute("SELECT id, name, nationality, age FROM players"):
        if pid in curids:
            continue
        t = twin.get(ident(nm, nat, age))
        if t:
            pairs.append((pid, t))
    print(f"removed orphans mapped to a surviving twin: {len(pairs):,}")

    filled = {t: 0 for t in FEATURE_TABLES}
    attr_filled = 0
    if not dry:
        cur.execute("BEGIN")
    for tbl in FEATURE_TABLES:
        tc = cols(cur, tbl)
        if "player_id" not in tc:
            continue
        placeholders = ",".join("?" * len(tc))
        for orphan, t in pairs:
            # only fill when the twin has NOTHING in this table (don't clobber curated rows)
            if cur.execute(f"SELECT 1 FROM {tbl} WHERE player_id=? LIMIT 1", (t,)).fetchone():
                continue
            rows = bak.execute(f"SELECT {','.join(tc)} FROM {tbl} WHERE player_id=?", (orphan,)).fetchall()
            if not rows:
                continue
            filled[tbl] += 1
            if not dry:
                pidpos = tc.index("player_id")
                newrows = [tuple(t if i == pidpos else v for i, v in enumerate(r)) for r in rows]
                cur.executemany(f"INSERT OR IGNORE INTO {tbl}({','.join(tc)}) VALUES({placeholders})", newrows)

    # attributes: add only the keys the twin is missing
    for orphan, t in pairs:
        have = {r[0] for r in cur.execute("SELECT attribute FROM player_attributes WHERE player_id=?", (t,))}
        miss = [(t, a, v) for a, v in
                bak.execute("SELECT attribute, value FROM player_attributes WHERE player_id=?", (orphan,))
                if a not in have]
        if miss:
            attr_filled += len(miss)
            if not dry:
                cur.executemany("INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) "
                                "VALUES(?,?,?)", miss)
    if not dry:
        cur.commit()
    print("gap-filled twins per table:", {k: v for k, v in filled.items() if v})
    print(f"attribute values added: {attr_filled:,}")
    print("(dry run — no writes)" if dry else "done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
