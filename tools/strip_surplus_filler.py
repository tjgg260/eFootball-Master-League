#!/usr/bin/env python3
"""
strip_surplus_filler.py — invented players exist to keep a club LEGAL, never to pad a real one
(owner ruling 2026-08-24: "I don't want big real clubs with fake players — only create players
where clubs genuinely have very few").

fill_squads.py tops a catalog club up to 20 whenever it is under 18. That was right at the time,
but a club is often short only because its real squad was parked on another record
(reclaim_real_squads.py) or because membership had not run yet. Once the real players arrive the
filler stays behind, so Angers ended up with 38 real players AND 17 invented ones.

Filler is generated-band (id >= 50e9) and disposable: it holds no identity, no history and no
career reference. This removes it from every squad that no longer needs it, worst-first, keeping
just enough to hold the 18-player / 2-GK floor, and then DELETES any generated player who is left
without a club (they are not people, and leaving them would put invented names in transfer
search). Career-band teams and their squads are never touched.

    python tools/strip_surplus_filler.py --dry
    python tools/strip_surplus_filler.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
FLOOR, GK_FLOOR, GEN = 18, 2, 50_000_000_000
SATELLITES = ["player_attributes", "player_playstyles", "player_skills", "player_traits",
              "player_potential", "player_appearance", "player_appearance_raw", "player_market",
              "player_identity", "player_condition", "morale", "academy", "contracts"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cur = con.cursor()
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    catalog = {t["team_id"] for co in cat["countries"] for lg in co["leagues"] for t in lg["teams"]}
    tn = dict(con.execute("SELECT id, name FROM teams"))

    pos = dict(con.execute("SELECT id, COALESCE(position,'') FROM players"))
    squads = defaultdict(list)
    for pid, tid, slot in con.execute("SELECT player_id, team_id, slot FROM squad_members"):
        if 800_000 <= tid < 1_000_000 or 9_000_000 <= tid < 9_200_000:
            continue
        squads[tid].append((slot, pid))

    drop = []
    for tid, mem in squads.items():
        fill = [(s, p) for s, p in mem if p >= GEN]
        if not fill:
            continue
        real = [(s, p) for s, p in mem if p < GEN]
        n, gk = len(mem), sum(1 for _s, p in mem if pos.get(p) == "GK")
        real_gk = sum(1 for _s, p in real if pos.get(p) == "GK")
        # a non-catalog club has no floor to hold at all; a catalog club keeps the weakest
        # filler only until 18 players / 2 keepers are covered by anyone
        keep_needed = max(0, FLOOR - len(real)) if tid in catalog else 0
        gk_needed = max(0, GK_FLOOR - real_gk) if tid in catalog else 0
        fill.sort(key=lambda x: -x[0])                 # deepest slots go first
        kept_gk = 0
        for slot, pid in fill:
            is_gk = pos.get(pid) == "GK"
            if is_gk and kept_gk < gk_needed:
                kept_gk += 1
                continue
            if keep_needed > 0:
                keep_needed -= 1
                continue
            drop.append((tid, pid))
    by_team = defaultdict(int)
    for tid, _pid in drop:
        by_team[tid] += 1
    print(f"invented players to remove from squads: {len(drop):,} across {len(by_team):,} clubs")
    for tid, n in sorted(by_team.items(), key=lambda x: -x[1])[:12]:
        left = len(squads[tid]) - n
        print(f"   {tn.get(tid, tid)[:30]:30} -{n:<3} leaving {left} real")

    # gate 2 guarantees one squad row per player, so every filler dropped here loses its only
    # club and becomes deletable — count it honestly rather than after the fact
    held = {p for (p,) in con.execute(
        "SELECT player_id FROM squad_members GROUP BY player_id HAVING COUNT(*) > 1")}
    orphan = {p for _t, p in drop} - held
    print(f"invented players left with no club (deleted outright): {len(orphan):,}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not drop:
        return 0

    shutil.copy2(DB, str(DB) + ".bak-prestrip")
    cur.execute("BEGIN")
    cur.executemany("DELETE FROM squad_members WHERE team_id=? AND player_id=?", drop)
    # anything generated with no squad row anywhere is now noise in the market: delete it whole
    gone = [r[0] for r in cur.execute(
        "SELECT id FROM players WHERE id >= ? AND NOT EXISTS "
        "(SELECT 1 FROM squad_members s WHERE s.player_id = players.id)", (GEN,))]
    for i in range(0, len(gone), 500):
        chunk = gone[i:i + 500]
        q = ",".join("?" * len(chunk))
        for tbl in SATELLITES:
            try:
                cur.execute(f"DELETE FROM {tbl} WHERE player_id IN ({q})", chunk)
            except sqlite3.OperationalError:
                pass
        cur.execute(f"DELETE FROM players WHERE id IN ({q})", chunk)
    con.commit()
    print(f"removed {len(drop):,} squad rows and deleted {len(gone):,} invented players.")
    print("next: rerank_slots.py, validate_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
