#!/usr/bin/env python3
"""
build_catalog.py — the browsable country → league → club catalog for the New Career screen.

The real division structure comes from RFS:
  competitions  id u16@0, name@2 (40B), tier u8@51, country u8@53   (verified: Premier League
                id 13 tier 1 country 14; Championship id 14 tier 2; ... National League tier 5)
  previuosseason  comp u16@0, team u32@2, position u8@6 — one row per team per competition it
                played in. A team appears for its LEAGUE and its cups; the league row is the one
                whose competition has a plausible tier + enough members.
  countries     id u8@0, name@1

Writes build/catalog.json:
  { countries: [ { id, name,
      leagues: [ { comp_id, name, tier, teams: [ {name, rfs_id, rating, logo} ] } ] } ] }
Leagues sorted by tier, countries by name. Clubs sorted by squad strength within a league.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb   # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
RFS_TEAMS = Path.home() / "OneDrive/Documents/RFS/Teams"

YOUTH = ("U21", "U-21", "U20", "U-20", "U23", "U-23", "U19", "U-18", "Olympic")


def main() -> int:
    db = RfsDb(RFS_DB)

    ct = db.tables["countries"]
    country = {}
    for i in range(ct.rows):
        r = db.record("countries", i)
        country[r[0]] = r[1:1 + 24].split(b"\0")[0].decode("utf-8", "replace").strip()
    country_names = set(country.values())

    # competitions: id, name, tier, country
    cp = db.tables["competitions"]
    comps = {}
    for i in range(cp.rows):
        r = db.record("competitions", i)
        cid = struct.unpack_from("<H", r, 0)[0]
        comps[cid] = {
            "name": r[2:2 + 40].split(b"\0")[0].decode("utf-8", "replace").strip(),
            "tier": r[51], "country": r[53],
        }

    # squad strength per team
    pt = db.tables["players"]
    pidx = {struct.unpack_from("<I", db.record("players", i), 0)[0]: i for i in range(pt.rows)}
    tpl = db.tables["teamplayerlinks"]
    squads = defaultdict(list)
    for i in range(tpl.rows):
        r = db.record("teamplayerlinks", i)
        squads[struct.unpack_from("<I", r, 0)[0]].append(struct.unpack_from("<I", r, 4)[0])

    tt = db.tables["teams"]
    tname = {}
    for i in range(tt.rows):
        r = db.record("teams", i)
        tname[struct.unpack_from("<I", r, 0)[0]] = \
            r[36:36 + 32].split(b"\0")[0].decode("utf-8", "replace").strip()

    # league membership: for each team keep every competition row; the league row is the comp
    # with a country + tier 1-9 and at least 6 members (cups and continental comps fail that).
    ps = db.tables["previuosseason"]
    comp_members = defaultdict(set)
    for i in range(ps.rows):
        r = db.record("previuosseason", i)
        comp_members[struct.unpack_from("<H", r, 0)[0]].add(struct.unpack_from("<I", r, 2)[0])

    def club_entry(rfs_id: int):
        name = tname.get(rfs_id, "")
        if not name or any(y in name for y in YOUTH) or name in country_names:
            return None
        sq = [p for p in squads.get(rfs_id, []) if p in pidx]
        if len(sq) < 11:
            return None
        ovr = [db.record("players", pidx[p])[196] for p in sq]
        logo = RFS_TEAMS / f"T_{rfs_id}.png"
        return {"name": name, "rfs_id": rfs_id, "rating": round(sum(ovr) / len(ovr), 1),
                "logo": str(logo) if logo.exists() else None}

    by_country = defaultdict(list)
    for cid, members in comp_members.items():
        c = comps.get(cid)
        if not c or c["country"] not in country or not (1 <= c["tier"] <= 9):
            continue
        # playoff / relegation-group phases are the same league sliced up — not separate leagues
        low = c["name"].lower()
        if "playoff" in low or "relegation" in low or "championsip" in low or "championship_" in low:
            continue
        teams = [e for e in (club_entry(t) for t in members) if e]
        if len(teams) < 8:
            continue
        teams.sort(key=lambda t: -t["rating"])
        by_country[c["country"]].append(
            {"comp_id": cid, "name": c["name"], "tier": c["tier"], "teams": teams})

    catalog = {"countries": []}
    for ccode, leagues in by_country.items():
        leagues.sort(key=lambda lg: (lg["tier"], -len(lg["teams"])))
        catalog["countries"].append({"id": ccode, "name": country[ccode], "leagues": leagues})
    catalog["countries"].sort(key=lambda c: c["name"])

    out = REPO / "build" / "catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    n_leagues = sum(len(c["leagues"]) for c in catalog["countries"])
    n_teams = sum(len(lg["teams"]) for c in catalog["countries"] for lg in c["leagues"])
    print(f"catalog: {len(catalog['countries'])} countries, {n_leagues} leagues, {n_teams:,} clubs -> {out}")
    eng = next((c for c in catalog["countries"] if c["name"] == "England"), None)
    if eng:
        for lg in eng["leagues"]:
            print(f"  England t{lg['tier']}: {lg['name']:<24} {len(lg['teams'])} clubs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
