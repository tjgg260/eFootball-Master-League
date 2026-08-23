#!/usr/bin/env python3
"""
rebuild_catalog_spine.py — rebuild catalog league memberships THROUGH THE IDENTITY SPINE instead
of raw name similarity. The old Jaccard reconcile poisoned the catalog (Serie A carried
'FC Milanese' where AC Milan belongs; River Plate vanished from Primera). Now every authoritative
club resolves by ID:

  API club --(team_identity.footballdata_id / sportsdb_id)--> team
          \\--(fm_clubs licensed name+nation -> uid -> team_identity.fm_club_id)--> team
          \\--(existing catalog entry of the same name)--> team          (last resort, reported)

Display name = the authoritative licensed name. Logo = DVX (fm id) > API crest > existing.
A league's list is only replaced when >=80%% of its authoritative clubs resolve; otherwise it is
left alone and reported. Also repairs the known Argentina hole (River Plate) via the spine, and
reports every high-reputation FM club whose spine team is absent from the catalog.

    python tools/rebuild_catalog_spine.py --dry
    python tools/rebuild_catalog_spine.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
FD = REPO / "build" / "league_data.json"
SDB = REPO / "build" / "sportsdb_data.json"
BADGES = REPO / "assets" / "badges"
DVX = REPO / "assets" / "dvx_logos"


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "",
                  unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def cnorm(x: str) -> str:
    x = (x or "").strip().lower()
    return {"holland": "netherlands", "korea republic": "south korea", "usa": "united states",
            "china pr": "china", "turkiye": "turkey", "republic of ireland": "ireland"}.get(x, x)


_XB = [{"england", "wales", "scotland", "northern ireland"}, {"france", "monaco"},
       {"switzerland", "liechtenstein"}, {"united states", "canada"},
       {"spain", "andorra"}, {"italy", "san marino"}]


def compatible(a, b):
    return a == b or any(a in g and b in g for g in _XB)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cat = json.loads(CAT.read_text(encoding="utf-8"))

    fd_team, sdb_team, fm_team = {}, {}, {}
    for tid, fmid, sdbid, fdid in con.execute(
            "SELECT team_id, fm_club_id, sportsdb_id, footballdata_id FROM team_identity"):
        if fdid:
            fd_team[fdid] = tid
        if sdbid:
            sdb_team[sdbid] = tid
        if fmid:
            fm_team[fmid] = tid
    fm_by_name = defaultdict(list)
    fm_meta = {}
    for uid, nm, nat, rep in con.execute(
            "SELECT uid, name, nation, COALESCE(reputation,0) FROM fm_clubs WHERE name IS NOT NULL"):
        fm_by_name[lkey(nm)].append((uid, cnorm(nat), rep))
        fm_meta[uid] = (nm, cnorm(nat), rep)
    squad = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    rating = dict(con.execute(
        "SELECT s.team_id, CAST(AVG(COALESCE(p.overall_rating,55)) AS INT) FROM squad_members s "
        "JOIN players p ON p.id=s.player_id GROUP BY s.team_id"))
    tname = dict(con.execute("SELECT id, name FROM teams"))

    # authoritative snapshots: (country_lkey, league_lkey) -> (source, [clubs])
    auth = {}
    if FD.exists():
        for comp in json.loads(FD.read_text(encoding="utf-8")).values():
            clubs = [{"name": t["name"], "aid": t.get("crest_id"), "src": "fd"}
                     for t in comp["teams"]]
            auth[(cnorm(comp["country"]), lkey(comp["name"]))] = clubs
    if SDB.exists():
        for k, comp in json.loads(SDB.read_text(encoding="utf-8")).items():
            country, league = k.split("|", 1)
            key = (cnorm(country), lkey(league))
            if key not in auth:
                auth[key] = [{"name": t["name"], "aid": t.get("badge_id"), "src": "sdb"}
                             for t in comp.get("teams", []) if t.get("name")]

    def resolve(club, country):
        # FM FIRST: membership is FM's truth, so the record its fm id points at is where the
        # SQUAD actually lives post-refresh (the API-named twin is often a husk now).
        cands = [(u, n, r) for u, n, r in fm_by_name.get(lkey(club["name"]), [])
                 if compatible(n, country)]
        if cands:
            u = max(cands, key=lambda x: x[2])[0]
            t = fm_team.get(u)
            if t:
                return t, "fm-id", u
        aid = club.get("aid")
        try:
            aid = int(aid) if aid is not None else None
        except (TypeError, ValueError):
            aid = None
        if aid is not None:
            t = fd_team.get(aid) if club["src"] == "fd" else sdb_team.get(aid)
            if t:
                return t, "api-id", None
        return None, None, None

    replaced = kept = 0
    unresolved_report = []
    used_global = set()
    for co in cat["countries"]:
        country = cnorm(co["name"])
        for lg in co["leagues"]:
            clubs = auth.get((country, lkey(lg["name"])))
            if not clubs:
                continue
            entries, misses = [], []
            for club in clubs:
                t, how, fmuid = resolve(club, country)
                if t is None or t in used_global:
                    # fall back: keep the existing entry with the same licensed name if any
                    old = next((e for e in lg["teams"] if lkey(e["name"]) == lkey(club["name"])
                                and e["team_id"] not in used_global), None)
                    if old is not None:
                        t, how, fmuid = old["team_id"], "kept", None
                    else:
                        misses.append(club["name"])
                        continue
                # logo: DVX (via spine fm id) > API crest > whatever the team row has
                fmid = fmuid or next((f for f, tt in fm_team.items() if tt == t), None)
                logo = None
                if fmid and (DVX / f"{fmid}.webp").exists():
                    logo = (DVX / f"{fmid}.webp").relative_to(REPO).as_posix()
                elif club.get("aid") is not None:
                    p = BADGES / (f"{club['aid']}.png" if club["src"] == "fd"
                                  else f"sdb_{club['aid']}.png")
                    if p.exists():
                        logo = p.relative_to(REPO).as_posix()
                if logo is None:
                    row = con.execute("SELECT logo_path FROM teams WHERE id=?", (t,)).fetchone()
                    logo = row[0] if row and row[0] else None
                entries.append({"name": club["name"], "team_id": t,
                                "rating": rating.get(t, 60), "squad": squad.get(t, 0),
                                "faces": 0, "logo": logo})
                used_global.add(t)
            share = len(entries) / len(clubs) if clubs else 0
            # replace when well-resolved OR when it IMPROVES a hollow league (2-club husks must
            # never survive just because the API list didn't fully resolve)
            if entries and (share >= 0.8 or len(entries) > len(lg["teams"])):
                if [e["team_id"] for e in entries] != [e["team_id"] for e in lg["teams"]] \
                        or [e["name"] for e in entries] != [e["name"] for e in lg["teams"]]:
                    replaced += 1
                lg["teams"] = entries
                if misses:
                    unresolved_report.append((co["name"], lg["name"], misses))
            else:
                kept += 1
                unresolved_report.append((co["name"], lg["name"],
                                          [f"LEAGUE KEPT ({share:.0%} resolved)"] + misses))

    # -- targeted hole repair: big FM clubs whose spine team is in NO catalog league
    in_cat = {t["team_id"] for co in cat["countries"] for lg in co["leagues"] for t in lg["teams"]}
    missing_big = []
    for uid, (nm, nat, rep) in fm_meta.items():
        t = fm_team.get(uid)
        if t and rep >= 6800 and t not in in_cat:
            missing_big.append((rep, nm, nat, t))
    missing_big.sort(reverse=True)
    # name aliases so an FM shortform finds the catalog's licensed entry to REPLACE in place
    ALIAS = {"man city": "manchester city", "man utd": "manchester united",
             "psg": "paris saint-germain", "inter": "inter milan", "a.c. milan": "ac milan",
             "bayern munich": "bayern münchen", "gladbach": "borussia mönchengladbach",
             "hsv": "hamburger sv", "lyon": "olympique lyonnais", "marseille": "olympique marseille",
             "atletico": "atlético madrid", "sporting": "sporting cp"}
    for rep, nm, nat, t in missing_big:
        co = next((c for c in cat["countries"] if cnorm(c["name"]) == nat), None)
        if not co or not co.get("leagues"):
            continue
        # 1) an existing catalog entry of the SAME CLUB (licensed name or alias) -> repoint it at
        #    the record where the squad now lives; never append a duplicate.
        keys = {lkey(nm), lkey(ALIAS.get(nm.lower(), ""))} - {""}
        entry = None
        for lg in co["leagues"]:
            for e in lg["teams"]:
                ek = lkey(e["name"])
                if ek in keys or any(k and (k in ek or ek in k) and len(min(k, ek, key=len)) >= 5
                                     for k in keys):
                    entry = (lg, e)
                    break
            if entry:
                break
        fmid = next((f for f, tt in fm_team.items() if tt == t), None)
        logo = ((DVX / f"{fmid}.webp").relative_to(REPO).as_posix()
                if fmid and (DVX / f"{fmid}.webp").exists() else None)
        if entry is not None:
            lg, e = entry
            if e["team_id"] != t:
                print(f"  repointed: {e['name']} ({lg['name']}) {e['team_id']} -> {t} "
                      f"(squad {squad.get(e['team_id'],0)} -> {squad.get(t,0)})")
                e["team_id"] = t
                e["rating"] = rating.get(t, e.get("rating", 70))
                e["squad"] = squad.get(t, 0)
                if logo:
                    e["logo"] = logo
            continue
        # 2) genuinely absent -> append to the country's real top flight (never a Simulated league)
        real = [x for x in co["leagues"] if "simulated" not in (x.get("name") or "").lower()]
        top = min(real or co["leagues"], key=lambda x: x.get("tier") or 9)
        top["teams"].append({"name": nm, "team_id": t, "rating": rating.get(t, 70),
                             "squad": squad.get(t, 0), "faces": 0, "logo": logo})
        print(f"  hole repaired: {nm} ({nat}, rep {rep}) -> {top['name']} as team {t}")

    # safety net: collapse same-club double entries inside one league (name-similar), keeping the
    # fuller squad — no repair path can leave two Bayerns in the Bundesliga.
    dropped = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            seen: list[dict] = []
            for e in sorted(lg["teams"], key=lambda x: -(x.get("squad") or 0)):
                ek = lkey(e["name"])
                dup = next((s for s in seen if s["team_id"] == e["team_id"] or ek == lkey(s["name"])
                            or (len(ek) >= 5 and len(lkey(s["name"])) >= 5
                                and (ek in lkey(s["name"]) or lkey(s["name"]) in ek))), None)
                if dup is None:
                    seen.append(e)
                else:
                    dropped += 1
            lg["teams"] = seen
    if dropped:
        print(f"same-club double entries collapsed: {dropped}")
    print(f"leagues rebuilt through the spine: {replaced} | kept (under 80% resolved): {kept}")
    for co_n, lg_n, misses in unresolved_report[:10]:
        print(f"  {co_n}/{lg_n}: unresolved {misses[:4]}")
    if dry:
        print("(dry run — catalog not written)")
        return 0
    shutil.copy2(CAT, str(CAT) + ".bak-prespine")
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    # keep teams.league_id in step with the rebuilt membership
    n = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            lid = lg.get("league_id")
            if not lid:
                continue
            for t in lg["teams"]:
                con.execute("UPDATE teams SET league_id=? WHERE id=? AND "
                            "(league_id IS NULL OR league_id<>?)", (lid, t["team_id"], lid))
                n += con.total_changes and 0
    con.commit()
    print("catalog written; teams.league_id resynced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
