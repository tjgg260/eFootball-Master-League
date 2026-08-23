#!/usr/bin/env python3
"""
build_competitions.py — competitions & the league pyramid (the blueprint's biggest structural gap).

Built from what already exists — no new sources, no fuzzy name matching across sources:
  * build/catalog.json         country -> league -> tier structure (the pyramid contract)
  * leagues + rfs_standings    the RFS competition import (leagues, cups, phase artefacts)
  * teams.league_id            which leagues row each club actually references
  * build/sportsdb_data.json + build/league_data.json   API snapshots, scanned for cup names

Creates and populates:
  competitions(id, name, country, kind[league|cup|continental], tier)
      kind='league'       one row per catalog league. Its id is resolved to the leagues row the
                          league's clubs actually reference (strict majority of teams.league_id
                          over the catalog's own team_ids — exact-id joins), then the RFS comp id
                          (L_BASE + catalog league_id), then an unclaimed exact-name row, else a
                          minted 4,000,000+ id. Global exclusivity: an id is claimed once.
      kind='cup'          domestic cups already present in the RFS leagues import; country by
                          membership vote (rfs_standings members -> catalog country, or the
                          member's own pyramid league's country), country-name fallback.
      kind='continental'  UCL/UEL/UECL/Libertadores/CAF/AFC/CONCACAF/FIFA club comps, by
                          explicit name patterns. country NULL.
  league_links(country, upper_league_id, lower_league_id, promotion_places, relegation_places)
      chains each country's tiers in catalog order; exchange size from the upper league's
      RFS relegation data, defaulting 3 for 20+-team divisions else 2.
  league_rules repair
      a correct row is upserted for every pyramid league (catalog club count, sane rounds,
      3/1 points, relegation = the downward link); rows keyed to cups, continental comps,
      national-team comps or phase artefacts are deleted; leagues rows for pyramid ids get
      tier/promotion/relegation mirrored, and minted pyramid ids get a leagues row inserted so
      every league_rules row references a real, team-bearing league.

Cups from the API snapshots get competition rows only — NO fixtures; the app draws brackets at
runtime.

DEFAULT IS A DRY REPORT (the DB is opened read-only, nothing is written). --apply writes, after
backing up master.db (and its -wal). Idempotent: competitions/league_links rebuild from scratch,
the league_rules repair re-converges.

    python tools/build_competitions.py            # dry: report what would be created per country
    python tools/build_competitions.py --apply    # write master.db
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
SDB = REPO / "build" / "sportsdb_data.json"
FDB = REPO / "build" / "league_data.json"

L_BASE = 3_000_000      # RFS competition rows in `leagues` (matches rfs_competitions.py)
MINT_BASE = 4_000_000   # pyramid leagues with no usable leagues row: id = MINT_BASE + catalog id
API_BASE = 4_500_000    # cups named only by the API snapshots

# classification of leagues rows NOT claimed by the catalog pyramid, tested in this order
NAT_RE = re.compile(r"(?<!club )world cup|wc qualification|euro(?![a-z])|copa america|asian cup|"
                    r"africa's cup|golden cup|nations league|friendl|u2[01]|caribbean cup|"
                    r"central american cup|rest of america")
ART_RE = re.compile(r"playoff|play-off|relegation|reg\.?\s?season|aggregate|ranking|zones draw|"
                    r"reducido|playout|finals?\b|nacompetitie|championsh?ip|apertura|clausura")
CONT_RE = re.compile(r"champions[_ ]league|europa league|conference[_ ]league|uefa supercup|"
                     r"libertadores|sudamericana|recopa|concacaf|caf cl|afc c[lu]|caf conference|"
                     r"caf supecup|fifa club world|fifa intercontinental")
CUP_RE = re.compile(r"cup|coppa|copa|coupe|pokal|poh[aá]r|kupa|kubok|kubogy|kobuku|kypello|beker|"
                    r"ta[çc]a|schaal|shield|trophy|\bkup\b|superkop|kop cfa|gavat|"
                    r"norgesmesterskapet|t\. des champions|tr\.de campeones")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apply_ = "--apply" in sys.argv

    if apply_:
        shutil.copy2(DB, str(DB) + ".bak-precomps")
        if Path(str(DB) + "-wal").exists():
            shutil.copy2(str(DB) + "-wal", str(DB) + ".bak-precomps-wal")
        con = sqlite3.connect(DB, timeout=60)
    else:
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)

    # ---- load ----
    league_names = dict(con.execute("SELECT id, name FROM leagues"))
    league_rel = dict(con.execute("SELECT id, relegation_places FROM leagues"))
    rules_now = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT league_id, num_teams, rounds, points_win, points_draw, relegation_places "
        "FROM league_rules")}
    club_league = dict(con.execute("SELECT id, league_id FROM teams"))
    teams_per_league = Counter(v for v in club_league.values() if v)
    members = defaultdict(list)                       # leagues id -> member team ids (RFS season)
    for lid, tid in con.execute("SELECT league_id, team_id FROM rfs_standings"):
        members[lid].append(tid)
    catalog = json.loads(CAT.read_text(encoding="utf-8"))
    cat_team_country = {t["team_id"]: co["name"] for co in catalog["countries"]
                        for lg in co["leagues"] for t in lg["teams"]}
    name_to_lid = {}                                  # exact leagues name -> id (unique only)
    for lid, nm in league_names.items():
        name_to_lid[nm] = None if nm in name_to_lid else lid

    # ---- resolve the pyramid: one competition per catalog league, globally exclusive ids ----
    claimed: dict[int, str] = {}
    pyramid: list[dict] = []
    for co in catalog["countries"]:
        for lg in sorted(co["leagues"], key=lambda l: l["tier"]):
            tids = [t["team_id"] for t in lg["teams"]]
            votes = Counter(club_league.get(t) for t in tids if club_league.get(t))
            comp_id = src = None
            if votes:
                best, n = votes.most_common(1)[0]
                # >=3 voters: a 1-2 club "majority" once hijacked the wrong row entirely
                if n >= 3 and n * 2 > sum(votes.values()) and best not in claimed:
                    comp_id, src = best, f"clubs' own league row, {n}/{len(tids)} clubs"
            if comp_id is None:
                cand = L_BASE + lg["league_id"]
                if cand in league_names and cand not in claimed:
                    comp_id, src = cand, "rfs comp id"
            if comp_id is None:
                cand = name_to_lid.get(lg["name"])
                if cand is not None and cand not in claimed:
                    comp_id, src = cand, "exact-name row"
            if comp_id is None:
                comp_id, src = MINT_BASE + lg["league_id"], "MINTED — no league row"
            claimed[comp_id] = lg["name"]
            pyramid.append({"country": co["name"], "tier": lg["tier"], "id": comp_id,
                            "name": lg["name"], "n": len(tids), "src": src})
    claimed_names = set(claimed.values())
    country_of_pyramid = {p["id"]: p["country"] for p in pyramid}

    # ---- classify every remaining leagues row ----
    countries_desc = sorted({c["name"] for c in catalog["countries"]}, key=len, reverse=True)

    def attribute(lid: int, low: str) -> tuple[str | None, str]:
        votes = Counter()
        for m in members.get(lid, []):
            c = cat_team_country.get(m) or country_of_pyramid.get(club_league.get(m))
            if c:
                votes[c] += 1
        tot = sum(votes.values())
        if tot:
            c, n = votes.most_common(1)[0]
            # RFS standings keep only ~2 members (the finalists) for most cups, so accept a
            # unanimous 2+ as well as a >=60% majority of a real sample
            if (tot >= 2 and n == tot) or (tot >= 4 and n / tot >= 0.6):
                return c, f"membership {n}/{tot}"
        for c in countries_desc:
            if c.lower() in low:
                return c, "name"
        return None, f"unattributed ({tot} known members)"

    cups, continental = [], []
    legacy, nat_skip, art_skip, dup_skip, other_skip = [], [], [], [], []
    class_of: dict[int, str] = dict.fromkeys(claimed, "pyramid")
    for lid in sorted(league_names):
        if lid in claimed:
            continue
        name = league_names[lid]
        low = name.lower()
        if lid < L_BASE:
            legacy.append((lid, name)); class_of[lid] = "legacy"
        elif name in claimed_names:
            dup_skip.append((lid, name)); class_of[lid] = "dup"
        elif NAT_RE.search(low):
            nat_skip.append((lid, name)); class_of[lid] = "national"
        elif ART_RE.search(low):
            art_skip.append((lid, name)); class_of[lid] = "artefact"
        elif CONT_RE.search(low):
            continental.append((lid, name)); class_of[lid] = "continental"
        elif CUP_RE.search(low):
            country, how = attribute(lid, low)
            cups.append((lid, name, country, how)); class_of[lid] = "cup"
        else:
            other_skip.append((lid, name, teams_per_league.get(lid, 0)))
            class_of[lid] = "other"

    # ---- league_links: chain each country's tiers in catalog order ----
    by_country: dict[str, list[dict]] = defaultdict(list)
    for p in pyramid:
        by_country[p["country"]].append(p)

    def exchange(upper: dict) -> int:
        rel = league_rel.get(upper["id"]) or 0
        if not 1 <= rel <= 6:
            rel = (rules_now.get(upper["id"]) or (0, 0, 0, 0, 0))[4]
        return rel if 1 <= rel <= 6 else (3 if upper["n"] >= 20 else 2)

    links, gaps = [], []
    for country, pl in by_country.items():
        pl.sort(key=lambda p: p["tier"])
        for up, lo in zip(pl, pl[1:]):
            x = exchange(up)
            links.append((country, up["id"], lo["id"], x, x))
            if lo["tier"] != up["tier"] + 1:
                gaps.append((country, up["tier"], lo["tier"]))
    link_down = {u: x for _, u, _l, x, _ in links}     # upper id -> relegation places
    link_up = {l: x for _, _u, l, x, _ in links}       # lower id -> promotion places

    # ---- league_rules repair plan ----
    desired = {}
    rules_new, rules_changed = [], []
    for p in pyramid:
        old = rules_now.get(p["id"])
        rounds = old[1] if old and old[1] in (1, 2) else 2
        # catalog club count is the fielded size; if it is implausibly small (catalog gap),
        # keep the RFS format size rather than emit a broken league
        n = p["n"] if p["n"] >= 8 else (old[0] if old and old[0] >= 8 else p["n"])
        want = (n, rounds, 3, 1, link_down.get(p["id"], 0))
        desired[p["id"]] = want
        if old is None:
            rules_new.append(p["id"])
        elif old != want:
            rules_changed.append((p["id"], old, want))
    rules_del = [lid for lid in rules_now if lid not in desired and (
        class_of.get(lid) in ("cup", "continental", "national", "artefact", "dup")
        or (class_of.get(lid) == "other" and teams_per_league.get(lid, 0) == 0))]
    rules_leftover = [lid for lid in rules_now if lid not in desired and lid not in rules_del]

    # ---- leagues mirror plan (tier/promotion/relegation onto real rows, insert minted ids) ----
    league_updates, league_inserts = [], []
    for p in pyramid:
        promo, rel = link_up.get(p["id"], 0), link_down.get(p["id"], 0)
        if p["id"] in league_names:
            league_updates.append((p["tier"], promo, rel, p["id"]))
        else:
            league_inserts.append((p["id"], p["name"], p["tier"], promo, rel))

    # ---- API snapshots: do they name any domestic cup we don't already have? ----
    all_comp_names = (claimed_names | set(league_names.values())
                      | {nm for _, nm, *_ in cups} | {nm for _, nm in continental})
    api_cups, api_notes = [], []

    def scan_api(nm: str | None, country: str | None, src: str) -> None:
        low = (nm or "").lower()
        if not nm or not CUP_RE.search(low) or NAT_RE.search(low) or CONT_RE.search(low) \
                or ART_RE.search(low):
            return
        if nm in all_comp_names:
            api_notes.append(f"{src}: '{nm}' already a competition")
        else:
            api_cups.append((nm, country, src))

    if SDB.exists():
        for key, blob in json.loads(SDB.read_text(encoding="utf-8")).items():
            country, _, lname = key.partition("|")
            nm = blob.get("sdb_league") or ""
            if lname in all_comp_names and CUP_RE.search(nm.lower()):
                api_notes.append(f"sportsdb: '{nm}' is its name for existing competition "
                                 f"'{lname}' ({country}) — same competition, not a new cup")
            else:
                scan_api(nm, country, "sportsdb")
    if FDB.exists():
        for _code, blob in json.loads(FDB.read_text(encoding="utf-8")).items():
            scan_api(blob.get("name"), blob.get("country"), "football-data")
    api_rows = [(API_BASE + i, nm, country)
                for i, (nm, country, _src) in enumerate(sorted(set(api_cups)))]

    # ---- report ----
    mode = "APPLY" if apply_ else "DRY RUN — nothing written"
    print(f"== build_competitions ({mode}) ==\n")
    cups_by_country: dict[str, list] = defaultdict(list)
    cups_lost = []
    for lid, nm, country, how in cups:
        (cups_by_country[country] if country else cups_lost).append((lid, nm, how))
    link_by_upper = {u: (l, x) for _, u, l, x, _ in links}
    for country in sorted(by_country):
        print(country)
        for p in by_country[country]:
            print(f"  league  {p['id']:>7}  {p['name']:<34} tier {p['tier']}  "
                  f"{p['n']:>2} clubs   [{p['src']}]")
            if p["id"] in link_by_upper:
                lo, x = link_by_upper[p["id"]]
                print(f"  link    {p['id']:>7} -> {lo:<7} {x} up / {x} down")
        for lid, nm, how in sorted(cups_by_country.get(country, [])):
            print(f"  cup     {lid:>7}  {nm:<34} [{how}]")
        print()
    if cups_lost:
        print("Cups with no attributable country (kept, country NULL):")
        for lid, nm, how in sorted(cups_lost):
            print(f"  cup     {lid:>7}  {nm:<34} [{how}]")
        print()
    print("Continental:")
    for lid, nm in sorted(continental):
        print(f"  cont    {lid:>7}  {nm}")
    print()
    if api_rows:
        print("Cups added from API snapshots (competition row only, no fixtures):")
        for cid, nm, country in api_rows:
            print(f"  cup     {cid:>7}  {nm:<34} [{country or '?'}]")
    else:
        print("Cups added from API snapshots: none "
              "(snapshots name no domestic cup we don't already have)")
    for note in api_notes:
        print(f"  note: {note}")
    print()
    print("Skipped leagues rows (no competition row):")
    print(f"  national-team comps: {len(nat_skip)}  "
          f"(e.g. {', '.join(n for _, n in nat_skip[:4])})")
    print(f"  phase artefacts:     {len(art_skip)}  "
          f"(e.g. {', '.join(n for _, n in art_skip[:4])})")
    print(f"  duplicate names:     {len(dup_skip)}  "
          f"({', '.join(f'{i} {n}' for i, n in dup_skip)})")
    print(f"  legacy placeholders: {len(legacy)}  "
          f"({', '.join(f'{i} {n}' for i, n in legacy)}) — left untouched")
    print(f"  unclassified:        {len(other_skip)}")
    for lid, nm, nt in sorted(other_skip, key=lambda r: -r[2])[:12]:
        print(f"      {lid:>7}  {nm:<34} {nt} teams reference it")
    print()
    print("league_rules repair:")
    print(f"  upsert (new):     {len(rules_new)}")
    print(f"  upsert (changed): {len(rules_changed)}")
    for lid, old, want in rules_changed[:8]:
        print(f"      {lid:>7}  {league_names.get(lid, claimed.get(lid))!s:<28} {old} -> {want}")
    print(f"  delete (cup/artefact/national/team-less): {len(rules_del)}")
    print(f"  left as-is (team-bearing, non-pyramid):   {len(rules_leftover)}")
    print(f"  leagues rows mirrored: {len(league_updates)} updated, "
          f"{len(league_inserts)} minted ids inserted")
    if gaps:
        print(f"  tier gaps chained anyway: {gaps}")
    minted = [p for p in pyramid if p["id"] >= MINT_BASE]
    print(f"\nTotals: {len(pyramid)} pyramid leagues ({len(minted)} minted), {len(links)} links, "
          f"{len(cups) + len(api_rows)} cups ({len(cups_lost)} unattributed), "
          f"{len(continental)} continental, over {len(by_country)} countries.")
    if minted:
        print("Minted (clubs keep catalog membership; no teams.league_id points here yet):")
        for p in minted:
            print(f"    {p['id']}  {p['country']}: {p['name']}")

    if not apply_:
        print("\nDRY run — re-run with --apply to write.")
        con.close()
        return 0

    # ---- write ----
    con.execute("BEGIN")
    con.execute("CREATE TABLE IF NOT EXISTS competitions("
                "id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT, "
                "kind TEXT NOT NULL CHECK(kind IN ('league','cup','continental')), tier INTEGER)")
    con.execute("CREATE TABLE IF NOT EXISTS league_links("
                "country TEXT NOT NULL, upper_league_id INTEGER NOT NULL, "
                "lower_league_id INTEGER NOT NULL, promotion_places INTEGER NOT NULL, "
                "relegation_places INTEGER NOT NULL, PRIMARY KEY(upper_league_id, lower_league_id))")
    con.execute("DELETE FROM competitions")
    con.execute("DELETE FROM league_links")
    con.executemany("INSERT INTO competitions(id,name,country,kind,tier) VALUES(?,?,?,?,?)",
                    [(p["id"], p["name"], p["country"], "league", p["tier"]) for p in pyramid]
                    + [(lid, nm, country, "cup", None) for lid, nm, country, _ in cups]
                    + [(cid, nm, country, "cup", None) for cid, nm, country in api_rows]
                    + [(lid, nm, None, "continental", None) for lid, nm in continental])
    con.executemany("INSERT INTO league_links(country,upper_league_id,lower_league_id,"
                    "promotion_places,relegation_places) VALUES(?,?,?,?,?)", links)
    con.executemany("INSERT OR REPLACE INTO league_rules"
                    "(league_id,num_teams,rounds,points_win,points_draw,relegation_places) "
                    "VALUES(?,?,?,?,?,?)",
                    [(lid, *want) for lid, want in desired.items()])
    con.executemany("DELETE FROM league_rules WHERE league_id=?", [(l,) for l in rules_del])
    con.executemany("UPDATE leagues SET tier=?, promotion_places=?, relegation_places=? "
                    "WHERE id=?", league_updates)
    con.executemany("INSERT OR REPLACE INTO leagues(id,name,tier,promotion_places,"
                    "relegation_places) VALUES(?,?,?,?,?)", league_inserts)
    con.commit()
    n_comp = con.execute("SELECT COUNT(*) FROM competitions").fetchone()[0]
    n_link = con.execute("SELECT COUNT(*) FROM league_links").fetchone()[0]
    n_rules = con.execute("SELECT COUNT(*) FROM league_rules").fetchone()[0]
    dangling = con.execute(
        "SELECT COUNT(*) FROM league_rules r WHERE NOT EXISTS "
        "(SELECT 1 FROM leagues l WHERE l.id=r.league_id)").fetchone()[0]
    print(f"\nAPPLIED: competitions={n_comp}, league_links={n_link}, league_rules={n_rules} "
          f"(dangling: {dangling}). Backup: master.db.bak-precomps")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
