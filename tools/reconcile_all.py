#!/usr/bin/env python3
"""
reconcile_all.py — rebuild catalog.json league memberships from AUTHORITATIVE sources: football-
data.org (build/league_data.json, the 9 majors, highest quality) preferred, TheSportsDB
(build/sportsdb_data.json, worldwide) for the rest. Each authoritative club is matched to our DB
record by Jaccard token similarity (country-constrained) with GREEDY PER-LEAGUE DEDUP so a club is
never assigned twice and two clubs never share a record (the Espanyol->Barcelona trap). Crests come
from the APIs. Non-covered leagues keep their existing membership.

    python tools/fetch_league_data.py && python tools/fetch_sportsdb.py   # produce the two inputs
    python tools/reconcile_all.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
FD = REPO / "build" / "league_data.json"
SDB = REPO / "build" / "sportsdb_data.json"
BADGES = REPO / "assets" / "badges"

STOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de", "club",
        "the", "afc", "ca", "rcd", "sd", "ogc", "rsc", "cp", "il", "aic", "und", "cfr", "kv", "sv",
        "vfl", "vfb", "tsg", "fsv", "ssc", "us", "acf", "as", "rc"}
ALIAS = {"utd": "united", "munchen": "munich"}


def toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return {ALIAS.get(w, w) for w in re.sub(r"[^a-z0-9 ]", " ", s).split()
            if (ALIAS.get(w, w) not in STOP and w not in STOP)}


def cnorm(x: str) -> str:
    x = (x or "").lower()
    return {"holland": "netherlands", "korea republic": "south korea",
            "usa": "united states"}.get(x, x)


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "",
                  unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def main() -> int:
    con = sqlite3.connect(DB)
    squad = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    rating = dict(con.execute(
        "SELECT s.team_id, CAST(AVG(COALESCE(p.overall_rating,55)) AS INT) FROM squad_members s "
        "JOIN players p ON p.id=s.player_id GROUP BY s.team_id"))
    faces = dict(con.execute(
        "SELECT s.team_id, SUM(COALESCE(p.real_face_path,p.portrait_path) IS NOT NULL) "
        "FROM squad_members s JOIN players p ON p.id=s.player_id GROUP BY s.team_id"))
    cnt: dict[int, Counter] = defaultdict(Counter)
    for tid, nat, k in con.execute(
            "SELECT s.team_id, p.nationality, COUNT(*) FROM squad_members s JOIN players p "
            "ON p.id=s.player_id WHERE p.nationality IS NOT NULL GROUP BY s.team_id, p.nationality"):
        cnt[tid][cnorm((nat or "").split("/")[0])] += k
    tcountry = {tid: c.most_common(1)[0][0] for tid, c in cnt.items()}

    teams = []
    for tid, nm in con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''"):
        if squad.get(tid, 0) == 0 or re.search(r"\b(u\d+|ii|reserve|academy|women|fem|sub)\b", nm, re.I):
            continue
        teams.append((tid, nm, toks(nm)))

    def sim(want, tk):
        """Token similarity that also credits prefix pairs (Hamburg~Hamburger, Lyon~Lyonnais)."""
        m = 0
        for x in want:
            if any(x == y or (len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x)))
                   for y in tk):
                m += 1
        denom = len(want) + len(tk) - m
        return m / denom if denom else 0.0

    def assign(clubs, country):
        """Greedy: rank every (club, db-team) pair by similarity, assign best-first, each side once."""
        ct = cnorm(country)
        pairs = []
        for i, ac in enumerate(clubs):
            want = toks(ac["name"])
            if not want:
                continue
            for tid, nm, tk in teams:
                if not tk or (tcountry.get(tid) and cnorm(tcountry[tid]) != ct):
                    continue
                j = sim(want, tk)
                if j >= 0.34:
                    pairs.append((j, squad.get(tid, 0), i, tid, nm))
        pairs.sort(key=lambda x: (-x[0], -x[1]))
        used_t, used_c, out = set(), set(), {}
        for j, sq, i, tid, nm in pairs:
            if i in used_c or tid in used_t:
                continue
            out[i] = (tid, nm)
            used_c.add(i)
            used_t.add(tid)
        return out

    # authoritative leagues: (country, lkey) -> (display_name, [club dicts with name+crest])
    auth = {}
    if FD.exists():
        for comp in json.loads(FD.read_text(encoding="utf-8")).values():
            clubs = [{"name": t["name"], "crest": BADGES / f"{t['crest_id']}.png"} for t in comp["teams"]]
            auth[(cnorm(comp["country"]), lkey(comp["name"]))] = (comp["name"], clubs, "fd")
    if SDB.exists():
        for k, comp in json.loads(SDB.read_text(encoding="utf-8")).items():
            country, league = k.split("|", 1)
            key = (cnorm(country), lkey(league))
            if key in auth:            # football-data already covers it (higher quality) -> keep
                continue
            clubs = [{"name": t["name"], "crest": BADGES / f"sdb_{t['badge_id']}.png"} for t in comp["teams"]]
            auth[key] = (league, clubs, "sdb")

    replaced, total_clubs, matched = 0, 0, 0
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    for co in cat["countries"]:
        for lg in co["leagues"]:
            key = (cnorm(co["name"]), lkey(lg["name"]))
            if key not in auth:
                continue
            _, clubs, _src = auth[key]
            got = assign(clubs, co["name"])
            tlist = []
            for i, ac in enumerate(clubs):
                total_clubs += 1
                if i not in got:
                    continue
                matched += 1
                tid, dbnm = got[i]
                crest = ac["crest"]
                tlist.append({"name": dbnm, "team_id": tid, "rating": rating.get(tid, 60),
                              "squad": squad.get(tid, 0), "faces": int(faces.get(tid) or 0),
                              "logo": str(crest) if crest.exists() else None})
            if tlist:
                lg["teams"] = tlist
                replaced += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"reconciled {replaced} leagues from authoritative data "
          f"({matched}/{total_clubs} clubs matched to DB records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
