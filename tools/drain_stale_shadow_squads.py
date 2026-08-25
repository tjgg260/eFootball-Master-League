#!/usr/bin/env python3
"""
drain_stale_shadow_squads.py — a shadow club record must not keep a squad of its own.

Manchester City exists twice: the catalog club (FM-linked, 70 players — Rúben Dias, Haaland,
Foden) and an eFootball-native row with no FM link holding seven players from an older roster
(Rodri, Bernardo Silva, Savinho, Kovacic, Reijnders, Aké, Lewis). Those seven are not duplicates
of the catalog squad by name — the FM export has since moved them on, which is why Rodri shows up
twice in the world, once at Barcelona where FM puts him and once here — so neither the twin merge
nor the content pairing can touch them. They are simply a stale roster on a club record nothing
renders.

For every non-catalog team whose club is ALSO represented by an FM-linked catalog record, each
player is resolved individually and the shadow squad is emptied:
  MOVE       the FM export names his club and we hold it: he goes there (the export is the
             membership truth — that is how Rodri reaches Barcelona)
  SUPERSEDE  the destination already fields this human: the stale copy is hidden behind him
  FREE       the export says he has no club, or has no opinion: he is unsquadded, staying in the
             database as a free agent rather than lingering at a club he has left

Catalog floors are respected on the way out and career bands are never touched. Nothing is
deleted.

    python tools/drain_stale_shadow_squads.py --dry
    python tools/drain_stale_shadow_squads.py
then: rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
FLOOR, GK_FLOOR = 18, 2
YOUTH = re.compile(r"\bU\s?-?(1[5-9]|2[0-3])\b", re.I)
STOP = {"fc", "cf", "cd", "sc", "ac", "as", "ss", "de", "club", "afc", "sd", "cp", "sv", "us",
        "ca", "fk", "nk", "if", "bk", "sk", "the", "calcio", "and"}


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def ntoks(s):
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split()
                     if len(w) > 1 and w not in STOP)


def ptoks(s):
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    catalog = {t["team_id"]: (t.get("name") or "") for co in cat["countries"]
               for lg in co["leagues"] for t in lg["teams"]}
    tn = dict(con.execute("SELECT id, name FROM teams"))
    fm_of = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
    team_of_club = {}
    for t, f in fm_of.items():
        if t in catalog:
            team_of_club.setdefault(f, t)
    for t, f in fm_of.items():
        team_of_club.setdefault(f, t)

    members = defaultdict(list)
    for pid, tid, slot, num in con.execute(
            "SELECT player_id, team_id, slot, squad_number FROM squad_members"):
        if not (800_000 <= tid < 1_000_000) and not (9_000_000 <= tid < 9_200_000):
            members[tid].append((pid, slot, num))
    P = {pid: (nm, age, pos) for pid, nm, age, pos in
         con.execute("SELECT id, name, age, COALESCE(position,'') FROM players")}
    uid_of = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    uid_club = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u, c = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip()
            if u.isdigit() and not YOUTH.search(r.get("Squad") or ""):
                uid_club[int(u)] = int(c) if c.lstrip("-").isdigit() else 0

    # a shadow team is stale when a CATALOG record of the same club is FM-linked
    cat_by_name = defaultdict(list)
    for t, disp in catalog.items():
        for key in (ntoks(disp), ntoks(tn.get(t, ""))):
            if key:
                cat_by_name[key].append(t)
    stale = []
    for tid, mem in members.items():
        if tid in catalog or not mem:
            continue
        keys = {ntoks(tn.get(tid, ""))}
        twin = None
        for k in keys:
            for t in cat_by_name.get(k, ()):
                if fm_of.get(t):
                    twin = t
                    break
        if twin:
            stale.append((tid, twin))
    print(f"stale shadow club records (a catalog twin of the same club is FM-linked): {len(stale)}")

    size = {t: len(m) for t, m in members.items()}
    gk = {t: sum(1 for p, _s, _n in m if P.get(p, ("", 0, ""))[2] == "GK")
          for t, m in members.items()}
    moves, sup, free, blocked = [], [], [], 0
    for tid, twin in stale:
        idents = {}
        for dest in (twin,):
            for p, _s, _n in members.get(dest, ()):
                idents[(ptoks(P[p][0]), P[p][1])] = p
        for pid, slot, num in members[tid]:
            nm, age, _pos = P.get(pid, ("", None, ""))
            uid = uid_of.get(pid)
            club = uid_club.get(uid) if uid else None
            want = team_of_club.get(club) if club else None
            # already at the destination as a fuller-named record?
            twinned = next((q for (t2, a2), q in idents.items()
                            if t2 and ptoks(nm) <= t2 and (age is None or a2 is None
                                                           or abs(a2 - age) <= 3)), None)
            # never move a man into a squad that already fields him — the destination's copy
            # wins and the stale one is hidden behind it (the sync applies the same guard)
            dest_has = None
            if want and want != tid:
                for q, _s, _n in members.get(want, ()):
                    q_nm, q_age, _qp = P.get(q, ("", None, ""))
                    if ptoks(nm) and ptoks(nm) <= ptoks(q_nm) and (
                            age is None or q_age is None or abs(q_age - age) <= 3):
                        dest_has = q
                        break
            if want and want != tid and dest_has is None:
                moves.append((pid, tid, want, nm))
            elif dest_has is not None:
                sup.append((pid, tid, dest_has, nm))
            elif twinned:
                sup.append((pid, tid, twinned, nm))
            else:
                free.append((pid, tid, nm))
    print(f"  moved to the club the FM export names: {len(moves):,}")
    print(f"  superseded behind a record already at that club: {len(sup):,}")
    print(f"  unsquadded (export has no club for them): {len(free):,}")
    for pid, tid, want, nm in moves[:8]:
        print(f"     MOVE  {nm[:22]:22} {tn.get(tid,'?')[:20]:20} -> {tn.get(want,'?')}")
    for pid, tid, q, nm in sup[:5]:
        print(f"     HIDE  {nm[:22]:22} behind {P.get(q,('?',))[0]}")
    if dry:
        print("--dry: nothing written.")
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-predrain")
    cur.execute("BEGIN")
    for pid, tid, want, _nm in moves:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (pid,))
        nums = {r[0] for r in cur.execute(
            "SELECT squad_number FROM squad_members WHERE team_id=?", (want,))}
        n = next(x for x in range(1, 200) if x not in nums)
        s = cur.execute("SELECT COALESCE(MAX(slot),10)+1 FROM squad_members WHERE team_id=?",
                        (want,)).fetchone()[0]
        cur.execute("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot,role)"
                    " VALUES(?,?,?,?,0)", (want, pid, n, s))
    for pid, tid, q, _nm in sup:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (pid,))
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (q, pid))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (q, pid, q))
    for pid, tid, _nm in free:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (pid,))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(moves):,} moved, {len(sup):,} hidden, {len(free):,} unsquadded.")
    print("next: rerank_slots.py, validate_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
