#!/usr/bin/env python3
"""
build_catalog.py (v3) — the browsable country → league → club catalog for the New Career screen.

HYBRID sourcing (the honest best of both worlds):
  * STRUCTURE (countries, leagues, tiers, membership) comes from RFS — its competitions table
    carries verified tiers (Premier League=1 … National League=5) and previuosseason gives real
    membership. master.db's teams.league_id is unusable (the FM export's Division column was
    garbage), so RFS remains the structural truth.
  * CLUBS resolve into master.db teams (club_key + country match, largest squad wins) so the New
    Career screen and the seeder get the MERGED world: FM-authoritative squads, facepack faces,
    best ratings.

Writes build/catalog.json:
  { version: 3, countries: [ { name,
      leagues: [ { league_id, name, tier,
        teams: [ {name, team_id, rating, faces, squad, logo} ] } ] } ] }

team_id is the master.db team id (the seeder's roster source). Clubs that can't be resolved to a
master team with a real squad are dropped (a club we can't field isn't playable).
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
OUT = REPO / "build" / "catalog.json"
RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"

sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb   # noqa: E402

MIN_CLUBS = 8
MIN_SQUAD = 8   # thin-but-real clubs (Celta 10, Mallorca 8) must not be dropped from their league
MAX_TIERS = 6
YOUTH = ("U21", "U-21", "U20", "U-20", "U23", "U-23", "U19", "U-18", "Olympic")
ARTEFACT_RE = re.compile(
    r"playoff|play-off|relegation|aggregate|zone|reducido|ranking|supercup|super cup|"
    r"championsip|championship_|_relegation|draw|apertura|clausura", re.I)
CLUB_STOP = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "club", "de", "the", "fk", "if", "bk",
             "us", "as", "rc", "1", "1899", "1900"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


ALIASES = {"utd": "united", "&": "and", "st.": "st"}


def club_key(s: str) -> str:
    words = [ALIASES.get(t, t) for t in norm(s).split()]
    return " ".join(t for t in words if t not in CLUB_STOP)


def main() -> int:
    con = sqlite3.connect(DB)

    # ---- master.db side: squads, ratings, faces, countries per team ----
    stats = {}
    for tid, n, avg in con.execute(
            "SELECT s.team_id, COUNT(*), AVG(COALESCE(p.overall_rating,55)) "
            "FROM squad_members s JOIN players p ON p.id=s.player_id GROUP BY s.team_id"):
        stats[tid] = (n, avg or 55)
    faces = dict(con.execute(
        "SELECT s.team_id, SUM(COALESCE(p.real_face_path, p.portrait_path) IS NOT NULL) "
        "FROM squad_members s JOIN players p ON p.id=s.player_id GROUP BY s.team_id"))
    team_country: dict[int, str] = {}
    cnt: dict[int, Counter] = defaultdict(Counter)
    for tid, nat, k in con.execute(
            "SELECT s.team_id, p.nationality, COUNT(*) FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE p.nationality IS NOT NULL "
            "GROUP BY s.team_id, p.nationality"):
        cnt[tid][(nat or "").split("/")[0].strip()] += k
    for tid, c in cnt.items():
        team_country[tid] = c.most_common(1)[0][0]

    by_key: dict[str, list[int]] = defaultdict(list)
    tname_master: dict[int, tuple[str, str | None]] = {}
    for tid, name, logo in con.execute(
            "SELECT id, name, logo_path FROM teams WHERE name IS NOT NULL AND name<>''"):
        if any(y in name for y in YOUTH):
            continue
        if stats.get(tid, (0, 0))[0] < MIN_SQUAD:
            continue
        tname_master[tid] = (name, logo)
        by_key[club_key(name)].append(tid)

    # prefix index: first word(s) of a club key -> team ids (for FM short names:
    # master "Huddersfield" must match RFS "Huddersfield Town")
    by_prefix: dict[str, list[int]] = defaultdict(list)
    for k, tids in by_key.items():
        by_prefix[k].extend(tids)

    def resolve(rfs_name: str, want_country: str) -> int | None:
        """RFS club name -> master.db team id: exact name, club_key, then prefix-subset
        (master short name is a leading subset of the RFS full name), country-checked."""
        cands = [t for t, (nm, _) in tname_master.items() if nm == rfs_name]
        if not cands:
            cands = by_key.get(club_key(rfs_name), [])
        if not cands:
            words = club_key(rfs_name).split()
            for cut in range(len(words) - 1, 0, -1):
                short = " ".join(words[:cut])
                hit = by_prefix.get(short, [])
                if hit:
                    cands = hit
                    break
        if not cands:
            return None
        wc = norm(want_country)
        scored = []
        for t in cands:
            tc = norm(team_country.get(t, ""))
            scored.append((0 if tc == wc else 1, -stats[t][0], t))
        scored.sort()
        # if the best candidate's country actively disagrees, drop it (Everton Chile trap)
        best = scored[0]
        if best[0] == 1 and len(cands) > 1:
            return None
        chosen = best[2]
        # SPLIT REPAIR: some clubs got fragmented across records (FM's "Mallorca" vs eFootball's
        # "RCD Mallorca"). If the chosen record is THIN and exactly ONE same-key, same-country twin
        # is clearly fuller (>=18 and >=2x), it's a split — use the fuller record. Requiring a
        # SINGLE dominant twin avoids collapsing genuine homonyms (Brazil's several "América"s,
        # which are multiple full-sized records).
        chosen_sq = stats.get(chosen, (0,))[0]
        if chosen_sq < 18:
            twins = [t for t in by_key.get(club_key(rfs_name), [])
                     if t != chosen and norm(team_country.get(t, "")) == wc
                     and stats.get(t, (0,))[0] >= max(18, chosen_sq * 2)]
            if len(twins) == 1:
                return twins[0]
        return chosen

    # ---- RFS side: structure ----
    db = RfsDb(RFS_DB)
    ct = db.tables["countries"]
    country = {}
    for i in range(ct.rows):
        r = db.record("countries", i)
        country[r[0]] = r[1:1 + 24].split(b"\0")[0].decode("utf-8", "replace").strip()
    country_names = set(country.values())

    cp = db.tables["competitions"]
    comps = {}
    for i in range(cp.rows):
        r = db.record("competitions", i)
        cid = struct.unpack_from("<H", r, 0)[0]
        comps[cid] = {
            "name": r[2:2 + 40].split(b"\0")[0].decode("utf-8", "replace").strip(),
            "tier": r[51], "country": r[53],
        }

    tt = db.tables["teams"]
    rfs_tname = {}
    for i in range(tt.rows):
        r = db.record("teams", i)
        rfs_tname[struct.unpack_from("<I", r, 0)[0]] = \
            r[36:36 + 32].split(b"\0")[0].decode("utf-8", "replace").strip()

    ps = db.tables["previuosseason"]
    comp_members = defaultdict(set)
    for i in range(ps.rows):
        r = db.record("previuosseason", i)
        comp_members[struct.unpack_from("<H", r, 0)[0]].add(struct.unpack_from("<I", r, 2)[0])

    # ---- join: league -> resolved master clubs ----
    dropped = Counter()
    by_country_leagues = defaultdict(list)
    for cid, members in comp_members.items():
        c = comps.get(cid)
        if not c or c["country"] not in country or not (1 <= c["tier"] <= 9):
            continue
        if ARTEFACT_RE.search(c["name"]):
            continue
        cname = country[c["country"]]
        teams = []
        seen = set()
        for rid in members:
            nm = rfs_tname.get(rid, "")
            if not nm or any(y in nm for y in YOUTH) or nm in country_names:
                continue
            tid = resolve(nm, cname)
            if tid is None or tid in seen:
                if tid is None:
                    dropped[cname] += 1
                continue
            seen.add(tid)
            mname, logo = tname_master[tid]
            teams.append({"name": mname, "team_id": tid,
                          "rating": round(stats[tid][1], 1), "squad": stats[tid][0],
                          "faces": int(faces.get(tid) or 0), "logo": logo})
        if len(teams) < MIN_CLUBS:
            continue
        teams.sort(key=lambda t: -t["rating"])
        by_country_leagues[cname].append(
            {"league_id": cid, "name": c["name"], "tier": min(c["tier"], MAX_TIERS),
             "teams": teams})

    catalog = {"version": 3, "countries": []}
    for cname in sorted(by_country_leagues):
        leagues = by_country_leagues[cname]
        # one league per tier: strongest keeps it, extras push down
        leagues.sort(key=lambda l: (l["tier"], -sum(t["rating"] for t in l["teams"][:16])))
        seen_tiers: set[int] = set()
        final = []
        for l in leagues:
            t = l["tier"]
            while t in seen_tiers and t <= MAX_TIERS:
                t += 1
            if t > MAX_TIERS:
                continue
            l["tier"] = t
            seen_tiers.add(t)
            final.append(l)
        if final:
            catalog["countries"].append({"name": cname, "leagues": final})

    # Backfill logos: a club can resolve to a reference record with no crest while a same-named
    # record HAS one (Chelsea 3000005 vs 800003). Prefer any available logo, matched by name.
    def _lkey(n):
        n = n.lower().replace("&", "and")
        n = re.sub(r"\b(fc|afc|cf)\b", "", n)
        return re.sub(r"[^a-z0-9]", "", n)
    logo_by_key = {}
    for _nm, _lp in tname_master.values():
        if _lp:
            logo_by_key.setdefault(_lkey(_nm), _lp)
    # eFootball/PES crests live at RFS/Teams/T_<pes_id>.png, and a reference club's team_id is
    # 3_000_000 + pes_id — so T_<team_id-3_000_000>.png is the club's real crest (verified 99%).
    rfs_teams = Path.home() / "OneDrive" / "Documents" / "RFS" / "Teams"
    for _co in catalog["countries"]:
        for _lg in _co["leagues"]:
            for _t in _lg["teams"]:
                if _t.get("logo"):
                    continue
                _t["logo"] = logo_by_key.get(_lkey(_t["name"]))
                if not _t.get("logo") and 3_000_000 <= _t.get("team_id", 0) < 3_200_000:
                    cand = rfs_teams / f"T_{_t['team_id'] - 3_000_000}.png"
                    if cand.exists():
                        _t["logo"] = str(cand)

    nl = sum(len(c["leagues"]) for c in catalog["countries"])
    nt = sum(len(l["teams"]) for c in catalog["countries"] for l in c["leagues"])
    OUT.write_text(json.dumps(catalog), encoding="utf-8")
    print(f"catalog v3: {len(catalog['countries'])} countries, {nl} leagues, {nt:,} clubs -> {OUT}")
    tiers = Counter(l["tier"] for c in catalog["countries"] for l in c["leagues"])
    print(f"tiers: {dict(sorted(tiers.items()))}")
    print(f"unresolved clubs dropped (top): {dropped.most_common(5)}")
    for c in catalog["countries"]:
        if c["name"] == "England":
            print("England:", [(l["name"], l["tier"], len(l["teams"])) for l in c["leagues"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
