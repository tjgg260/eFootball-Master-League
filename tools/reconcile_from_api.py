#!/usr/bin/env python3
"""
reconcile_from_api.py — replace the major leagues in build/catalog.json with AUTHORITATIVE
current-season membership from football-data.org (build/league_data.json). Each authoritative club
is matched to our DB record (token-subset name match, country-constrained, largest squad wins) and
its crest comes from the API (assets/badges). Fixes wrong league sizes (La Liga -> the real 20) and
gives clean crests. Non-covered leagues keep their RFS-derived membership.

    python tools/fetch_league_data.py     # first, to produce build/league_data.json
    python tools/reconcile_from_api.py
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
LD = REPO / "build" / "league_data.json"
BADGES = REPO / "assets" / "badges"

STOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de",
        "club", "the", "afc", "ca", "rcd", "sd", "ogc", "rsc", "cp", "il", "aic", "und"}
ALIAS = {"utd": "united", "munchen": "munich"}


def toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    out = set()
    for w in re.sub(r"[^a-z0-9 ]", " ", s).split():
        w = ALIAS.get(w, w)
        if w and w not in STOP:
            out.add(w)
    return out


def cnorm(x: str) -> str:
    x = (x or "").lower()
    return "netherlands" if x in ("holland", "netherlands") else x


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "")
                  .encode("ascii", "ignore").decode().lower())


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
            "SELECT s.team_id, p.nationality, COUNT(*) FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE p.nationality IS NOT NULL "
            "GROUP BY s.team_id, p.nationality"):
        cnt[tid][cnorm((nat or "").split("/")[0])] += k
    tcountry = {tid: c.most_common(1)[0][0] for tid, c in cnt.items()}

    teams = []
    for tid, nm in con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''"):
        if squad.get(tid, 0) == 0 or re.search(r"\b(u\d+|b|ii|reserve|academy|women|fem)\b", nm, re.I):
            continue
        teams.append((tid, nm, toks(nm)))

    def match(name: str, country: str):
        ct = cnorm(country)
        want = toks(name)
        best, bestsq = None, -1
        for tid, nm, tk in teams:
            if not tk or not want or not (want <= tk or tk <= want):
                continue
            if tcountry.get(tid) and cnorm(tcountry[tid]) != ct:
                continue
            if squad.get(tid, 0) > bestsq:
                best, bestsq = (tid, nm), squad.get(tid, 0)
        return best

    ld = json.loads(LD.read_text(encoding="utf-8"))
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    new_leagues, misses = {}, []
    for comp in ld.values():
        tlist = []
        for t in comp["teams"]:
            m = match(t["name"], comp["country"])
            if not m:
                misses.append(f"{comp['name']}: {t['name']}")
                continue
            tid, dbnm = m
            crest = BADGES / f"{t['crest_id']}.png"
            tlist.append({"name": dbnm, "team_id": tid, "rating": rating.get(tid, 60),
                          "squad": squad.get(tid, 0), "faces": int(faces.get(tid) or 0),
                          "logo": str(crest) if crest.exists() else None})
        new_leagues[(cnorm(comp["country"]), lkey(comp["name"]))] = (comp["name"], tlist)

    replaced = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            key = (cnorm(co["name"]), lkey(lg["name"]))
            if key in new_leagues:
                lg["teams"] = new_leagues[key][1]
                replaced += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"reconciled {replaced} leagues from authoritative data:")
    for _, (nm, tl) in new_leagues.items():
        print(f"  {nm}: {len(tl)} teams, {sum(1 for x in tl if x['logo'])} with API crest")
    for m in misses:
        print(f"  UNMATCHED: {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
