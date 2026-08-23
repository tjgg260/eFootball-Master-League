#!/usr/bin/env python3
"""
fetch_league_data.py — pull AUTHORITATIVE current-season league memberships (+ crest images) from
football-data.org, so we reconcile our fragmented DB against ground truth instead of RFS guesswork.

Free token (no payment): register at https://www.football-data.org/client/register — the token is
emailed instantly. Then either:
    setx FOOTBALL_DATA_TOKEN <your-token>     (Windows, new shell picks it up)
or drop it in tokens/football_data.txt (gitignored).

    python tools/fetch_league_data.py                 # fetch all mapped competitions
    python tools/fetch_league_data.py PD SA           # just La Liga + Serie A

Writes build/league_data.json ({competition: {name, country, teams:[{name,short,tla,crest_id}]}})
and downloads crests to assets/badges/<id>.png. Free tier = 10 req/min, so it paces itself.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "build" / "league_data.json"
BADGES = REPO / "assets" / "badges"
API = "https://api.football-data.org/v4"

# football-data.org competition code -> (our country, our league name). These are the free-tier
# competitions — exactly the majors where our DB is fragmented.
COMPS = {
    "PL":  ("England", "Premier League"),
    "ELC": ("England", "Championship"),
    "PD":  ("Spain", "La Liga"),
    "SA":  ("Italy", "Serie A"),
    "BL1": ("Germany", "Bundesliga"),
    "FL1": ("France", "Ligue 1"),
    "PPL": ("Portugal", "Primeira Liga"),
    "DED": ("Holland", "Eredivisie"),
    "BSA": ("Brazil", "Série A"),
}


def token() -> str:
    t = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    if not t:
        f = REPO / "tokens" / "football_data.txt"
        if f.exists():
            t = f.read_text(encoding="utf-8").strip()
    if not t:
        sys.exit("No token. Register free at football-data.org, then set FOOTBALL_DATA_TOKEN "
                 "or write it to tokens/football_data.txt")
    return t


def get(url: str, tok: str) -> tuple[dict, dict]:
    req = urllib.request.Request(url, headers={"X-Auth-Token": tok, "User-Agent": "ml-career/1.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read()), dict(resp.headers)


def throttle(headers: dict) -> None:
    """Respect football-data.org's own rate-limit headers instead of guessing: if we're near the
    per-minute cap, sleep until the counter resets (the API tells us how long)."""
    try:
        avail = int(headers.get("X-Requests-Available-Minute", "10"))
        reset = int(headers.get("X-RequestCounter-Reset", "60"))
    except (TypeError, ValueError):
        avail, reset = 10, 60
    if avail <= 1:
        print(f"  (rate limit near — waiting {reset + 1}s for reset)")
        time.sleep(reset + 1)


def main() -> int:
    tok = token()
    want = sys.argv[1:] or list(COMPS)
    BADGES.mkdir(parents=True, exist_ok=True)
    result = {}
    for i, code in enumerate(want):
        if code not in COMPS:
            print(f"  {code}: not a mapped competition, skipping")
            continue
        country, league = COMPS[code]
        try:
            data, headers = get(f"{API}/competitions/{code}/teams", tok)
        except Exception as e:  # noqa: BLE001
            print(f"  {code}: FAILED ({e})")
            continue
        teams = []
        for t in data.get("teams", []):
            crest = t.get("crest") or ""
            cid = str(t.get("id"))
            teams.append({"name": t.get("name"), "short": t.get("shortName"),
                          "tla": t.get("tla"), "crest_id": cid, "crest_url": crest})
            if crest:
                ext = ".svg" if crest.lower().endswith(".svg") else ".png"
                dest = BADGES / f"{cid}{ext}"
                if not dest.exists():
                    try:
                        urllib.request.urlretrieve(crest, dest)
                    except Exception:  # noqa: BLE001
                        pass
        result[code] = {"name": league, "country": country, "teams": teams}
        print(f"  {code} {league}: {len(teams)} teams (+ crests)")
        throttle(headers)   # obey the API's own rate-limit headers (per football-data.org's advice)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(c["teams"]) for c in result.values())
    print(f"\nwrote {len(result)} competitions, {total} clubs -> {OUT}")
    print(f"crests -> {BADGES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
