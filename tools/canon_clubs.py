#!/usr/bin/env python3
"""
canon_clubs.py — conservatively fold pre-existing duplicate club rows (same real club represented
across dt200 / eF / RFS) into one canonical team, WITHOUT fusing genuinely-different same-name
clubs (Botafogo-RJ vs -PB, the three Brazilian "Nacional", River Plate ARG/URU/ZAM).

Merge a (club_key, country) bucket ONLY when it holds EXACTLY 2 teams and either:
  * one of them is a dt200 base club (id 800000-899999, the playable/licensed set), OR
  * the two share >=1 squad member (identity-confirmed).
Buckets with 3+ same-country teams are LEFT ALONE (that's where the dangerous generics live).

Canonical = the dt200 (800xxx) id if present, else the team with the most members. Squad
membership follows the existing priority already baked into the data (FM>eF>RFS); we just union
members into the canonical id and drop the empty duplicate. Backup master.db before running.
"""
from __future__ import annotations
import sqlite3, re, sys, unicodedata
from collections import defaultdict, Counter
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "build" / "master.db"
CLUB_STOP = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "club", "de", "the", "fk", "if", "bk",
             "us", "as", "rc", "1", "1899", "1900"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def ck(s):
    return " ".join(t for t in norm(s).split() if t not in CLUB_STOP)


def is_dt200(tid):
    return 800000 <= tid <= 899999


def main(apply):
    con = sqlite3.connect(DB)
    members = defaultdict(set)
    for tid, pid in con.execute("SELECT team_id, player_id FROM squad_members"):
        members[tid].add(pid)
    natof = dict(con.execute("SELECT id, nationality FROM players WHERE nationality IS NOT NULL"))

    def country(tid):
        nats = [natof[p] for p in members.get(tid, ()) if p in natof and natof[p]]
        return norm(Counter(nats).most_common(1)[0][0]) if nats else None

    bucket = defaultdict(list)   # (ck, country) -> [tid]
    names = {}
    for tid, nm in con.execute("SELECT id, name FROM teams t "
                               "WHERE EXISTS(SELECT 1 FROM squad_members s WHERE s.team_id=t.id)"):
        names[tid] = nm
        bucket[(ck(nm), country(tid))].append(tid)

    plan = []   # (keep, drop)
    for (k, co), tids in bucket.items():
        if len(tids) != 2:
            continue
        a, b = tids
        shared = len(members[a] & members[b])
        if not (is_dt200(a) or is_dt200(b) or shared >= 1):
            continue
        keep = a if is_dt200(a) else b if is_dt200(b) else (a if len(members[a]) >= len(members[b]) else b)
        drop = b if keep == a else a
        plan.append((keep, drop, shared))

    print(f"merge plan: {len(plan)} duplicate teams to fold\n")
    marquee = {"manchester city", "liverpool", "arsenal", "everton", "chelsea", "real madrid",
               "fc barcelona", "barcelona", "bayern munchen", "juventus", "santos"}
    for keep, drop, shared in plan:
        if ck(names[keep]) in marquee or ck(names.get(drop, "")) in marquee:
            print(f"  keep {keep} {names[keep]!r} ({len(members[keep])})  <=  "
                  f"drop {drop} {names[drop]!r} ({len(members[drop])})  shared={shared}")

    if not apply:
        print(f"\n(dry-run) pass --apply to execute {len(plan)} merges")
        return 0

    con.execute("BEGIN")
    for keep, drop, _ in plan:
        con.execute("UPDATE OR IGNORE squad_members SET team_id=? WHERE team_id=?", (keep, drop))
        con.execute("DELETE FROM squad_members WHERE team_id=?", (drop,))
        con.execute("UPDATE teams SET base_team_id=? WHERE base_team_id=?", (keep, drop))
        con.execute("DELETE FROM teams WHERE id=?", (drop,))
    con.commit()
    print(f"\napplied {len(plan)} merges.")
    print(f"teams now: {con.execute('SELECT COUNT(*) FROM teams').fetchone()[0]:,}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
