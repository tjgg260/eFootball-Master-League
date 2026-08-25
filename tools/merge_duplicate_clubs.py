#!/usr/bin/env python3
"""
merge_duplicate_clubs.py — one club, one team record holding players.

Three separate passes have each removed a slice of club duplication (fix_catalog_dupes for one
record in several countries, reclaim_real_squads for a link on the wrong record,
drain_stale_shadow_squads for a stale roster). What is left is the plain case: the SAME club
exists as two team records that both hold players, under names no exact rule pairs —
'Olympique Marseille' beside the catalog's 'Marseille', 'PSV Eindhoven' beside 'PSV', and even two
Al-Hilal slots inside the Saudi Pro League.

A pair is merged only when all of this holds:
  - the destination is a CATALOG club and is linked to FM; the source is not linked, or is a
    catalog slot that duplicates the destination inside the same league
  - one name's significant tokens contain the other's, and the surplus is either nothing or
    club-type filler ('Olympique', 'FC', 'SFC'), never a distinguishing word
    ('Sydney' vs 'Western Sydney' must not merge)
  - both sit in the same country
Players move to the destination unless it already fields that human, in which case the source copy
is superseded behind him. A source that is itself a catalog slot has that slot removed, because a
league cannot list one club twice.

    python tools/merge_duplicate_clubs.py --dry
    python tools/merge_duplicate_clubs.py
then: rerank_slots.py, validate_db.py
"""
from __future__ import annotations

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
CAT = REPO / "build" / "catalog.json"

STOP = {"fc", "cf", "cd", "sc", "sfc", "ac", "as", "ss", "de", "club", "afc", "sd", "cp", "sv",
        "us", "ca", "fk", "nk", "if", "bk", "sk", "the", "calcio", "and", "ksa", "cfc"}
# surplus words that never distinguish two clubs from each other
# "real" is NOT generic: Real Noroeste and Noroeste are different Brazilian clubs, as are
# Real Madrid and Madrid. A word only belongs here if it never distinguishes two clubs.
GENERIC = {"olympique", "sporting", "athletic", "football", "association", "city",
           "town", "united", "utd", "eindhoven", "sfc", "cf", "calcio", "sport"}


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s):
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split()
                     if len(w) > 1 and w not in STOP)


def ptoks(s):
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    cat = json.loads(CAT.read_text(encoding="utf-8"))

    slot_of, country_of, disp_of = {}, {}, {}
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                slot_of[t["team_id"]] = lg
                country_of[t["team_id"]] = norm(co["name"])
                disp_of[t["team_id"]] = t.get("name") or ""

    tn = dict(con.execute("SELECT id, name FROM teams"))
    fm_of = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
    members = defaultdict(list)
    for pid, tid, slot, num in con.execute(
            "SELECT player_id, team_id, slot, squad_number FROM squad_members"):
        if not (800_000 <= tid < 1_000_000) and not (9_000_000 <= tid < 9_200_000):
            members[tid].append((pid, slot, num))
    P = {pid: (nm, age) for pid, nm, age in con.execute("SELECT id, name, age FROM players")}

    # squad nationality gives a team its country when the catalog does not
    natc = defaultdict(Counter)
    for tid, nat in con.execute("SELECT s.team_id, p.nationality FROM squad_members s "
                                "JOIN players p ON p.id=s.player_id WHERE p.nationality IS NOT NULL"):
        natc[tid][norm(nat.split("/")[0])] += 1
    squad_country = {t: c.most_common(1)[0][0] for t, c in natc.items()}

    def country(tid):
        return country_of.get(tid) or squad_country.get(tid)

    dests = [t for t in slot_of if fm_of.get(t)]
    by_tok = defaultdict(list)
    for t in dests:
        for k in (toks(disp_of[t]), toks(tn.get(t, ""))):
            if k:
                by_tok[k].append(t)

    pairs = []
    for src, mem in members.items():
        if not mem or fm_of.get(src):
            continue                                   # a linked record is a club in its own right
        keys = {toks(tn.get(src, "")), toks(disp_of.get(src, ""))}
        cand = set()
        for k in keys:
            for w in k:
                for kk, ts in by_tok.items():
                    if w in kk:
                        cand.update(ts)
        best = None
        for d in cand:
            if d == src or not country(src) or country(src) != country(d):
                continue
            a, b = toks(tn.get(src, "")), toks(disp_of[d]) or toks(tn.get(d, ""))
            if not a or not b:
                continue
            short, long_ = (a, b) if len(a) <= len(b) else (b, a)
            if not short <= long_:
                continue
            if (long_ - short) and not (long_ - short) <= GENERIC:
                continue
            if best is None or len(members.get(d, ())) > len(members.get(best, ())):
                best = d
        if best:
            pairs.append((src, best))
    print(f"same-club team records to merge: {len(pairs)}")

    moves, sup = [], []
    for src, dest in pairs:
        idents = [(ptoks(P[p][0]), P[p][1], p) for p, _s, _n in members.get(dest, ()) if p in P]
        for pid, _slot, _num in members[src]:
            nm, age = P.get(pid, ("", None))
            twin = next((q for t2, a2, q in idents
                         if t2 and ptoks(nm) <= t2
                         and (age is None or a2 is None or abs(a2 - age) <= 3)), None)
            (sup if twin else moves).append((pid, src, dest, twin, nm))
    print(f"  players moved to the surviving record: {len(moves):,}")
    print(f"  superseded because the destination already fields them: {len(sup):,}")
    for src, dest in pairs[:12]:
        print(f"   {tn.get(src, '?')[:26]:26} ({len(members.get(src, ())):>3}) -> "
              f"{disp_of.get(dest) or tn.get(dest, '?'):26} ({len(members.get(dest, ())):>3})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not pairs:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-premergeclubs")
    shutil.copy2(CAT, str(CAT) + ".bak-premergeclubs")
    cur.execute("BEGIN")
    for pid, src, dest, twin, _nm in moves:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (pid,))
        nums = {r[0] for r in cur.execute(
            "SELECT squad_number FROM squad_members WHERE team_id=?", (dest,))}
        n = next(x for x in range(1, 200) if x not in nums)
        s = cur.execute("SELECT COALESCE(MAX(slot),10)+1 FROM squad_members WHERE team_id=?",
                        (dest,)).fetchone()[0]
        cur.execute("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot,role)"
                    " VALUES(?,?,?,?,0)", (dest, pid, n, s))
    for pid, src, dest, twin, _nm in sup:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (pid,))
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (twin, pid))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (twin, pid, twin))
    # a league must not list the same club twice
    dropped = 0
    srcs = {s for s, _d in pairs}
    for co in cat["countries"]:
        for lg in co["leagues"]:
            before = len(lg["teams"])
            lg["teams"] = [t for t in lg["teams"] if t["team_id"] not in srcs]
            dropped += before - len(lg["teams"])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied. moved {len(moves):,}, superseded {len(sup):,}, "
          f"catalog slots removed {dropped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
