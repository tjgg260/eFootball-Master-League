#!/usr/bin/env python3
"""
merge_split_club.py — a league cannot list the same club twice.

merge_duplicate_clubs pairs on names, so it cannot see a split whose two records are named
'Stade Rennais FC' and 'Rennes 2': neither string contains the other. The evidence that they are
one club is in the squads, not the names — every one of Rennes 2's 17 identified players is a
Rennes player in the FM export, and so is every one of Stade Rennais' 34. Brice Samba and Seko
Fofana were fielded by different halves of the same club.

So vote instead: for each catalog slot, ask which FM club its squad belongs to, and merge when two
slots of the SAME league return the same answer. The keeper is the slot carrying team_identity's
verified fm_club_id (falling back to the larger squad); the other slot's players move across,
superseded behind the keeper's copy when he already fields that human, and its league slot is
removed. Across the whole world this finds exactly one pair, which is the point — it is a check
that happens to have work to do today.

    python tools/merge_split_club.py --dry
    python tools/merge_split_club.py
then: fix_club_display_names.py, rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
MEMBER = REPO / "allavailable columns players.csv"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    nm = dict(con.execute("SELECT id, name FROM teams"))
    linked = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))

    uid2club = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u, c = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip()
            if u.isdigit() and c.isdigit():
                uid2club[int(u)] = int(c)
    pl2uid = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))

    pairs = []
    for co in cat["countries"]:
        for lg in co["leagues"]:
            vote = {}
            for t in lg["teams"]:
                tid = t["team_id"]
                c = Counter()
                for (p,) in con.execute("SELECT player_id FROM squad_members WHERE team_id=?",
                                        (tid,)):
                    cl = uid2club.get(pl2uid.get(p))
                    if cl:
                        c[cl] += 1
                if c:
                    top, n = c.most_common(1)[0]
                    if n >= 5 and n >= 0.4 * sum(c.values()):
                        vote[tid] = (top, n)
            by_club = defaultdict(list)
            for tid, (cl, n) in vote.items():
                by_club[cl].append((tid, n))
            for cl, ts in by_club.items():
                if len(ts) < 2:
                    continue
                sz = {tid: con.execute("SELECT COUNT(*) FROM squad_members WHERE team_id=?",
                                       (tid,)).fetchone()[0] for tid, _n in ts}
                keep = max(ts, key=lambda x: (linked.get(x[0]) == cl, sz[x[0]]))[0]
                for tid, _n in ts:
                    if tid != keep:
                        pairs.append((lg["name"], cl, keep, tid))

    print(f"split clubs found (two slots of one league, one FM club): {len(pairs)}")
    moves, sup = [], []
    for lgname, cl, keep, src in pairs:
        have = {pl2uid.get(p) for (p,) in con.execute(
            "SELECT player_id FROM squad_members WHERE team_id=?", (keep,))}
        have.discard(None)
        n_move = n_sup = 0
        for (p,) in con.execute("SELECT player_id FROM squad_members WHERE team_id=?", (src,)):
            u = pl2uid.get(p)
            twin = None
            if u is not None and u in have:
                twin = con.execute(
                    "SELECT s.player_id FROM squad_members s JOIN player_identity pi "
                    "ON pi.player_id=s.player_id WHERE s.team_id=? AND pi.fm_uid=?",
                    (keep, u)).fetchone()
            if twin:
                sup.append((twin[0], p))
                n_sup += 1
            else:
                moves.append((keep, p))
                n_move += 1
        print(f"   {lgname}: {nm.get(src)!r} -> {nm.get(keep)!r}   "
              f"move {n_move}, supersede {n_sup}")

    if dry:
        print("--dry: nothing written.")
        return 0
    if not pairs:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-presplit")
    cur.execute("BEGIN")
    for keep, pid in moves:
        n = cur.execute("SELECT COALESCE(MAX(slot),-1)+1 FROM squad_members WHERE team_id=?",
                        (keep,)).fetchone()[0]
        cur.execute("UPDATE squad_members SET team_id=?, slot=? WHERE player_id=?", (keep, n, pid))
    for twin, pid in sup:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (pid,))
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (twin, pid))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (twin, pid, twin))
    con.commit()

    drop = {src for _l, _c, _k, src in pairs}
    for co in cat["countries"]:
        for lg in co["leagues"]:
            lg["teams"] = [t for t in lg["teams"] if t["team_id"] not in drop]
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. moved {len(moves)}, superseded {len(sup)}, "
          f"removed {len(drop)} duplicate league slot(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
