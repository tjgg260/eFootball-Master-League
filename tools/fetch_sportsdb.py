#!/usr/bin/env python3
"""
fetch_sportsdb.py — authoritative league -> teams + badges for EVERY catalog league, from
TheSportsDB (premium key in tokens/thesportsdb.txt). Complements fetch_league_data.py (football-
data, the 9 majors) with worldwide coverage. Writes build/sportsdb_data.json + badges to
assets/badges/sdb_<idTeam>.png. Paces itself under the 100 req/min premium limit.

    python tools/fetch_sportsdb.py
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY = (REPO / "tokens" / "thesportsdb.txt").read_text(encoding="utf-8").strip()
BASE = f"https://www.thesportsdb.com/api/v1/json/{KEY}"
BADGES = REPO / "assets" / "badges"
OUT = REPO / "build" / "sportsdb_data.json"
CAT = REPO / "build" / "catalog.json"

# our catalog country name -> TheSportsDB country name (where they differ)
CMAP = {
    "holland": "Netherlands", "korea republic": "South Korea", "usa": "United States",
    "united states": "United States", "china": "China", "ivory coast": "Ivory Coast",
    "bosnia": "Bosnia and Herzegovina", "north macedonia": "North Macedonia",
}


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "",
                  unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def get(url: str):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                               timeout=30)
    return json.loads(r.read())


def main() -> int:
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    BADGES.mkdir(parents=True, exist_ok=True)
    result, calls = {}, 0
    for co in cat["countries"]:
        cname = co["name"]
        if "Rest of" in cname or "Simulated" in cname:
            continue
        sdb_country = CMAP.get(cname.lower(), cname)
        try:
            d = get(f"{BASE}/search_all_leagues.php?c={urllib.parse.quote(sdb_country)}&s=Soccer")
            calls += 1
        except Exception as e:  # noqa: BLE001
            print(f"{cname}: leagues FAILED ({e})", flush=True)
            continue
        idx = [(lkey(l["strLeague"]), l["strLeague"]) for l in (d.get("countries") or [])
               if l.get("strLeague")]
        for lg in co["leagues"]:
            if "Simulated" in lg["name"]:
                continue
            ourk = lkey(lg["name"])
            cand = [x for x in idx if ourk and (ourk in x[0] or x[0] in ourk)]
            if not cand:
                continue
            cand.sort(key=lambda x: abs(len(x[0]) - len(ourk)))   # closest length = best fit
            sname = cand[0][1]
            try:
                td = get(f"{BASE}/search_all_teams.php?l={urllib.parse.quote(sname)}")
                calls += 1
            except Exception:  # noqa: BLE001
                continue
            teams = []
            for t in td.get("teams") or []:
                bid, badge = t.get("idTeam"), t.get("strBadge")
                teams.append({"name": t.get("strTeam"), "badge_id": bid, "badge_url": badge})
                if badge:
                    dest = BADGES / f"sdb_{bid}.png"
                    if not dest.exists():
                        try:
                            urllib.request.urlretrieve(badge, dest)
                        except Exception:  # noqa: BLE001
                            pass
            if teams:
                result[f"{cname}|{lg['name']}"] = {"sdb_league": sname, "teams": teams}
                print(f"  {cname} / {lg['name']} <- {sname}: {len(teams)} teams", flush=True)
            time.sleep(0.7)   # stay well under 100/min
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nfetched {len(result)} leagues in {calls} API calls -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
