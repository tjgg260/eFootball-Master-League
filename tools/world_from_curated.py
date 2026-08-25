#!/usr/bin/env python3
"""
world_from_curated.py — give the REFERENCE WORLD its own record for humans that exist only as
curated career-overlay rows (45-46B), so FM membership can place them.

Why: the hand-typed 2026/27 overlay (update_career_squad.py, retired 2026-08-23) minted
Liverpool's and Arsenal's squads straight into the CAREER band. 36 of those humans — Van Dijk,
Wirtz, Isak, Szoboszlai, Saka... — have no world record at all, so world Liverpool fielded its
academy while the stars sat in a career squad. sync_membership_fm.py cannot fix that: placing a
career-squadded record into the world is the double-membership its own guards forbid.

This mints the missing WORLD twin at the canonical FM id (10B + fm_uid), cloning the curated
row's bio, attributes and satellites. The career squad keeps its curated record untouched —
a career copy shadowing a world record is the normal architecture, not a duplicate to hide
(supersede_twins.py exempts the curated band for the same reason).

Skips any human already present in the world under any spelling (name tokens + age +- 2), so
re-running mints nothing. After this, run:
    python tools/sync_membership_fm.py      (places them at their FM club)
    python tools/rerank_slots.py            (they take their XI slots)

    python tools/world_from_curated.py --dry
    python tools/world_from_curated.py
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
FM_BASE = 10_000_000_000
CUR_LO, CUR_HI = 45_000_000_000, 46_000_000_000
SATELLITES = ["player_attributes", "player_playstyles", "player_skills", "player_traits",
              "player_potential", "player_appearance", "player_appearance_raw"]


def toks(s: str) -> frozenset[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(re.sub(r"[^a-z ]", " ", s).split())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cur = con.cursor()

    linked = {uid for (uid,) in con.execute(
        "SELECT DISTINCT fm_uid FROM player_identity WHERE fm_uid IS NOT NULL "
        f"AND NOT (player_id>={CUR_LO} AND player_id<{CUR_HI})")}

    # every world (non-career, non-curated) record, for the name+age safety net
    world = []
    for pid, nm, age in con.execute(
            "SELECT id, name, age FROM players WHERE superseded_by IS NULL "
            f"AND (id < 20000000 OR (id >= 700000000 AND NOT (id>={CUR_LO} AND id<{CUR_HI})))"):
        world.append((toks(nm), age))

    todo = []
    for pid, uid in con.execute(
            "SELECT pi.player_id, pi.fm_uid FROM player_identity pi "
            f"WHERE pi.player_id>={CUR_LO} AND pi.player_id<{CUR_HI} AND pi.fm_uid IS NOT NULL"):
        if uid in linked:
            continue
        row = con.execute("SELECT name, age FROM players WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        t, age = toks(row[0]), row[1]
        if any(t == wt and (age is None or wa is None or abs(wa - age) <= 2)
               for wt, wa in world):
            continue                                   # already in the world under some id
        new_id = FM_BASE + uid
        if con.execute("SELECT 1 FROM players WHERE id=?", (new_id,)).fetchone():
            continue
        todo.append((pid, uid, new_id, row[0]))

    print(f"curated humans missing from the world: {len(todo)}")
    for _p, _u, nid, nm in todo[:8]:
        print(f"   mint {nid}  {nm}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not todo:
        return 0

    shutil.copy2(DB, str(DB) + ".bak-preworldmint")
    pcols = [r[1] for r in cur.execute("PRAGMA table_info(players)")]
    # game_pid is NOT NULL + UNIQUE and equals id for every one of the 372k existing records;
    # base/donor_pid describe how a record was authored into Player.bin and belong to the
    # render layer (dt200_grow.py / ml_author.py), not to a freshly minted world row
    copy_cols = [c for c in pcols
                 if c not in ("id", "superseded_by", "game_pid", "base_pid", "donor_pid")]
    rest = ",".join(copy_cols)
    for src, uid, nid, _nm in todo:
        cur.execute(f"INSERT INTO players(id,game_pid,{rest}) SELECT ?,?,{rest} FROM players "
                    f"WHERE id=?", (nid, nid, src))
        for tbl in SATELLITES:
            try:
                cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})")]
                if "player_id" not in cols:
                    continue
                r2 = ",".join(c for c in cols if c != "player_id")
                cur.execute(f"INSERT INTO {tbl}(player_id,{r2}) SELECT ?,{r2} FROM {tbl} "
                            f"WHERE player_id=?", (nid, src))
            except sqlite3.OperationalError:
                pass
        cur.execute("INSERT OR REPLACE INTO player_identity"
                    "(player_id, kind, fm_uid, fm_method, confidence) "
                    "VALUES(?,'fm',?, 'id', 1.0)", (nid, uid))
    con.commit()
    print(f"minted {len(todo)} world records. Run sync_membership_fm.py, then rerank_slots.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
