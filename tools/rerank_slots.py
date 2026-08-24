#!/usr/bin/env python3
"""
rerank_slots.py — rebuild squad_members.slot for the world after membership sync + twin
supersede left arrivals parked at the bottom and 1,800+ teams with gapped slot spaces.

The slot contract (see the writers/readers themselves, not this doc, if they disagree):
  - slot is a plain 0-based ordinal, unique and CONTIGUOUS per team — append-at-end writers
    (Session signings, MoveIntoSquad, fill_squads) use COUNT(*) as the next slot, so a gap
    makes a future signing collide; play_match's ORDER BY slot has no tiebreak, so a
    duplicate slot compiles a nondeterministic XI
  - slots 0..10 are the STARTING XI and map positionally onto the host team's
    PlayerAssignment records (record 0 = the goalkeeper slot): slot 0 must be a GK, and
    exactly one GK belongs in 0..10 (SessionXiRepair's legality rule)
  - only slot is rewritten — squad_number is the shirt (user-visible data) and role rides
    along untouched (cleanup_db's renumber clobbers shirts; do not copy that)

Catalog clubs get a position-aware order: best GK at 0, then the best four defenders,
four midfielders, two forwards (block order is the convention every record layout and the
curated career writer already use), shortages borrowed from the best remaining outfielders;
bench opens with the backup GK, then rating order. Other world teams keep their existing
order, renumbered 0..N-1. Career bands (800k-1M) and career youth sides (9.0M-9.2M) are
never touched — the app's PrepareMatchday owns those slots.

    python tools/rerank_slots.py --dry
    python tools/rerank_slots.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

DF = {"CB", "LB", "RB"}
MF = {"DMF", "CMF", "AMF", "LMF", "RMF"}
FW = {"CF", "SS", "LWF", "RWF"}


def order_catalog(rows):
    """rows: (pid, position, rating) -> pid list in slot order (GK, 4 DF, 4 MF, 2 FW, bench)."""
    by_r = sorted(rows, key=lambda r: -(r[2] or 0))
    gks = [r for r in by_r if r[1] == "GK"]
    outf = [r for r in by_r if r[1] != "GK"]
    xi = [gks[0]] if gks else []
    used = {xi[0][0]} if xi else set()
    picked = {"DF": [], "MF": [], "FW": []}

    def take(posset, want, key):
        for r in by_r:
            if len(picked[key]) >= want:
                return
            if r[0] not in used and r[1] in posset:
                picked[key].append(r)
                used.add(r[0])

    # A back four is 2 centre-backs and 2 fullbacks, not the four best defenders by rating —
    # rating-only picking gave 19% of clubs a back line of four centre-halves and no width.
    take({"LB"}, 1, "DF")
    take({"RB"}, 1, "DF")
    take({"CB"}, 2, "DF")
    take(DF, 4, "DF")                    # shortages fall back to any defender
    take(MF, 4, "MF")
    take(FW, 2, "FW")
    # borrow shortages from the best remaining outfielders, kept in block order
    short = 10 - sum(len(v) for v in picked.values())
    if short > 0:
        extra = [r for r in outf if r[0] not in used][:short]
        for r in extra:
            key = "DF" if r[1] in DF else "FW" if r[1] in FW else "MF"
            picked[key].append(r)
            used.add(r[0])
    xi += picked["DF"] + picked["MF"] + picked["FW"]
    bench = []
    if len(gks) > 1:
        bench.append(gks[1])
        used.add(gks[1][0])
    bench += [r for r in by_r if r[0] not in used]
    return [r[0] for r in xi + bench]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    catalog = {t["team_id"] for co in cat["countries"] for lg in co["leagues"] for t in lg["teams"]}

    teams = [t for (t,) in con.execute("SELECT DISTINCT team_id FROM squad_members")
             if not (800_000 <= t < 1_000_000) and not (9_000_000 <= t < 9_200_000)]
    updates = []                                     # (slot, team, pid)
    n_cat = n_renum = 0
    for tid in teams:
        rows = con.execute(
            "SELECT s.player_id, COALESCE(p.position,''), COALESCE(p.overall_rating,0), s.slot "
            "FROM squad_members s JOIN players p ON p.id=s.player_id WHERE s.team_id=? "
            "ORDER BY s.slot, s.player_id", (tid,)).fetchall()
        if not rows:
            continue
        if tid in catalog:
            order = order_catalog([(r[0], r[1], r[2]) for r in rows])
            n_cat += 1
        else:
            order = [r[0] for r in rows]             # keep order, fix numbering
        changed = [(i, tid, pid) for i, pid in enumerate(order)
                   if rows[[r[0] for r in rows].index(pid)][3] != i]
        if changed:
            if tid not in catalog:
                n_renum += 1
            updates.extend(changed)
    print(f"catalog clubs re-ranked: {n_cat:,} | other teams renumbered: {n_renum:,} | "
          f"slot updates: {len(updates):,}")

    # preview: a club the sync rebuilt
    for tid in (3000110,):
        order = [u for u in updates if u[1] == tid]
        if order:
            nm = dict(con.execute(
                "SELECT s.player_id, p.name FROM squad_members s JOIN players p "
                "ON p.id=s.player_id WHERE s.team_id=?", (tid,)))
            xi = sorted(order)[:11]
            print("  preview XI", tid, ":", ", ".join(nm[p] for _i, _t, p in xi))

    if dry:
        print("--dry: nothing written.")
        return 0
    shutil.copy2(DB, str(DB) + ".bak-prererank")
    cur = con.cursor()
    cur.executemany("UPDATE squad_members SET slot=? WHERE team_id=? AND player_id=?", updates)
    con.commit()
    bad = 0
    for tid in teams:
        slots = [r[0] for r in cur.execute(
            "SELECT slot FROM squad_members WHERE team_id=?", (tid,))]
        if sorted(slots) != list(range(len(slots))):
            bad += 1
    print(f"applied. teams with non-contiguous slots after: {bad} (must be 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
