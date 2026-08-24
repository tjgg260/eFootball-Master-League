#!/usr/bin/env python3
"""
reclaim_real_squads.py — real clubs must field real players (owner ruling 2026-08-24: "I don't
want big real clubs with fake players — only create players where clubs genuinely have very few").

679 catalog clubs carried 4,267 generated players, and only ~20 of them are genuinely small.
The rest were padded because their REAL squad is sitting in another record: Ligue 1's Troyes had
20 invented players while 'Troyes 2' held 49 real ones, Hull City was empty while 'Hull' held 54,
Stoke City while 'Stoke' held 56. fill_squads.py then did its job on a club that only looked
short. The squads were never missing — the fm_club_id was on the wrong record.

This moves the link, not the players: the catalog club takes the fm_club_id from the shadow
holder, and sync_membership_fm.py then walks the real squad over on its own terms (floors,
twin guards and all). Strictly gated, because a name rule is what put 'Wanderers F.C.' on Wolves:
  - the catalog club must actually be short of REAL players (< FLOOR non-generated)
  - the shadow holder must carry >= 11 real players of its own
  - the FM club's REGISTRY name must match the CATALOG DISPLAY name as a token subset either way
    ('Hull' <= 'Hull City'); the shadow's own team name is ignored, since being called
    'Troyes 2' is the very mis-naming being corrected
  - nations must be known and compatible, and senior/reserve status must agree
  - exactly one candidate, or the club is skipped and reported

    python tools/reclaim_real_squads.py --dry
    python tools/reclaim_real_squads.py
then: sync_membership_fm.py -> strip_surplus_filler.py -> rerank_slots.py -> validate_db.py
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
CSVP = REPO / "allavailable columns players.csv"
FLOOR = 18
GEN = 50_000_000_000
YOUTH = re.compile(r"\bU\s?-?(1[5-9]|2[0-3])\b", re.I)
RESV = re.compile(r"\b(ii|iii|b|reserves?|u\d\d?|acad|youth|next gen|futuro)\b")
RESV_NUM = re.compile(r"\s[2-4]$")
STOP = {"fc", "cf", "cd", "sc", "ac", "as", "ss", "de", "club", "afc", "sd", "cp", "sv", "us",
        "ca", "fk", "nk", "if", "bk", "sk", "the", "calcio", "and", "rc", "ud", "ssd", "acf"}
# club-type words: the only surplus allowed when the shorter name is a single token
GENERIC = {"city", "town", "united", "utd", "athletic", "county", "wanderers", "rovers",
           "albion", "borough", "sporting", "association", "football"}


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s):
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split()
                     if len(w) > 1 and w not in STOP)


def resv(s):
    n = norm(s).strip()
    return bool(RESV.search(n)) or bool(RESV_NUM.search(n))


def cnorm(x):
    x = norm(x).strip()
    return {"holland": "netherlands", "korea republic": "south korea", "china pr": "china",
            "usa": "united states", "turkiye": "turkey", "republic of ireland": "ireland"}.get(x, x)


_XB = [{"england", "wales", "scotland", "northern ireland"}, {"france", "monaco"},
       {"switzerland", "liechtenstein"}, {"united states", "canada"}, {"spain", "andorra"},
       {"italy", "san marino"}]


def compatible(a, b):
    return a == b or any(a in g and b in g for g in _XB)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cur = con.cursor()
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    slot, cat_country = {}, {}
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                slot[t["team_id"]] = t.get("name") or ""
                cat_country[t["team_id"]] = cnorm(co["name"])

    tn = dict(con.execute("SELECT id, name FROM teams"))
    real, gen = Counter(), Counter()
    for pid, tid in con.execute("SELECT player_id, team_id FROM squad_members"):
        if 800_000 <= tid < 1_000_000 or 9_000_000 <= tid < 9_200_000:
            continue
        (gen if pid >= GEN else real)[tid] += 1

    fm_of = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
    holders = defaultdict(list)
    for t, f in fm_of.items():
        holders[f].append(t)

    # FM registry: club -> (display name, nation, senior roster size)
    nc, bc, rn = defaultdict(Counter), defaultdict(Counter), Counter()
    with open(CSVP, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            c = (r.get("Club ID") or "").strip()
            if not (c.lstrip("-").isdigit() and int(c) > 0):
                continue
            cid = int(c)
            nc[cid][(r.get("Club") or "").strip()] += 1
            bc[cid][cnorm(r.get("Based") or "")] += 1
            if not YOUTH.search(r.get("Squad") or ""):
                rn[cid] += 1
    reg = {cid: (nc[cid].most_common(1)[0][0], bc[cid].most_common(1)[0][0]) for cid in nc}

    moves, skipped = [], []
    for tid, disp in sorted(slot.items()):
        if real[tid] >= FLOOR or gen[tid] == 0:
            continue                                  # already has a real squad, or no filler
        want, tc = toks(disp), cat_country.get(tid)
        if not want or not tc:
            continue
        cands = []
        for src, fc in fm_of.items():
            if src == tid or src in slot or fc not in reg:
                continue
            if real[src] < 11 or rn.get(fc, 0) < 11:
                continue
            rname, rnat = reg[fc]
            if not rnat or not compatible(tc, rnat):
                continue
            if resv(disp) != resv(rname):
                continue
            rt = toks(rname)
            if not rt or not (rt <= want or want <= rt):
                continue                              # 'Hull' <= 'Hull City'; never a partial
            # a subset alone is not enough when the short side is ONE generic word: 'FC United'
            # ⊆ 'Boston United' and 'Aalborg' ⊆ 'KB 81 Aalborg' are different clubs. Either the
            # short side carries two real tokens, or the surplus must be club-type filler
            short, long_ = (rt, want) if len(rt) <= len(want) else (want, rt)
            if len(short) < 2 and not (long_ - short) <= GENERIC:
                continue
            cands.append((real[src], src, fc, rname))
        cands.sort(reverse=True)
        if not cands:
            continue
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            skipped.append((tid, disp, [(c[2], c[3]) for c in cands[:3]]))
            continue
        n_real, src, fc, rname = cands[0]
        moves.append((tid, disp, src, tn.get(src, "?"), fc, rname, n_real, fm_of.get(tid)))

    print(f"catalog clubs short of real players with a reclaimable squad: {len(moves)} "
          f"(ambiguous, skipped: {len(skipped)})")
    for tid, disp, src, sname, fc, rname, n, old in moves[:20]:
        o = f" (drops bogus link {old})" if old and old != fc else ""
        print(f"   {disp[:26]:26} <- {sname[:24]:24} fm {fc} '{rname}' with {n} real{o}")
    for tid, disp, c in skipped[:6]:
        print(f"   SKIP {disp}: {c}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not moves:
        return 0

    shutil.copy2(DB, str(DB) + ".bak-prereclaim")
    for tid, _disp, src, _sn, fc, _rn, _n, _old in moves:
        cur.execute("UPDATE team_identity SET fm_club_id=NULL, method=NULL WHERE team_id=?", (src,))
        if cur.execute("SELECT 1 FROM team_identity WHERE team_id=?", (tid,)).fetchone():
            cur.execute("UPDATE team_identity SET fm_club_id=?, method='reclaim', confidence=0.9 "
                        "WHERE team_id=?", (fc, tid))
        else:
            cur.execute("INSERT INTO team_identity(team_id, fm_club_id, method, confidence) "
                        "VALUES(?,?,'reclaim',0.9)", (tid, fc))
    con.commit()
    dup = cur.execute("""SELECT COUNT(*) FROM (SELECT fm_club_id FROM team_identity
        WHERE fm_club_id IS NOT NULL AND NOT (team_id>=800000 AND team_id<1000000)
        GROUP BY fm_club_id HAVING COUNT(*)>1)""").fetchone()[0]
    print(f"moved {len(moves)} club links. duplicate claims: {dup} (must be 0)")
    print("next: sync_membership_fm.py, then strip_surplus_filler.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
