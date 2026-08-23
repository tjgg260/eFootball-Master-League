#!/usr/bin/env python3
"""
career_seed.py — seed a real, playable career into build/master.db for ANY club.

    python tools/career_seed.py --team "Liverpool FC"
    python tools/career_seed.py --team "Red Star Belgrade" --size 12

Given a club, this builds its league as the strongest clubs in the same country (RFS has no clean
division field, so top-of-country ≈ top flight), pulls every club's REAL squad from RFS with
translated abilities and face photos, wires coach tactics, generates a full double round-robin
season plus the opening preseason friendly, and marks the chosen club as the one you manage.

Everything lives in reserved id ranges (league 9000, teams 800000+, players 20,000,000+) so a new
career overwrites the last without touching the 57k-player universe the Market browses.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb          # noqa: E402
from rfs_translate import translate    # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
RFS_PLAYERS = Path.home() / "OneDrive/Documents/RFS/Players"
RFS_TEAMS = Path.home() / "OneDrive/Documents/RFS/Teams"
EF_CSV = REPO / "samples" / "editor-bundled-players.csv"
CATALOG = REPO / "build" / "catalog.json"

_EF_ABIL = ["offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
            "lofted_pass", "finishing", "heading", "set_piece_taking", "curl", "speed", "acceleration",
            "kicking_power", "jumping", "physical_contact", "balance", "stamina", "defensive_awareness",
            "tackling", "aggression", "defensive_engagement", "gk_awareness", "gk_catching",
            "gk_parrying", "gk_reflexes", "gk_reach"]


def _norm(s: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "o"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def load_ef_index():
    """eFootball's player export keyed by name -> (overall, abilities, bio). Priority over RFS
    ratings; bio carries height/weight/age/nationality for the player card (columns verified
    against samples/editor-bundled-players.csv — never guess CSV column names)."""
    import csv
    import io
    idx = {}
    if not EF_CSV.exists():
        return idx
    for r in csv.DictReader(io.StringIO(EF_CSV.read_bytes().decode("utf-8-sig"))):
        nm = r.get("player_name", "").strip()
        if not nm or not r.get("overall_rating", "").isdigit():
            continue
        bio = {
            "height": int(r["height"]) if r.get("height", "").isdigit() else None,
            "weight": int(r["weight"]) if r.get("weight", "").isdigit() else None,
            "age": int(r["age"]) if r.get("age", "").isdigit() else None,
            "nationality": r.get("nationality", "").strip() or None,
        }
        entry = (int(r["overall_rating"]),
                 {a: int(r[a]) for a in _EF_ABIL if r.get(a, "").isdigit()}, bio)
        idx.setdefault(_norm(nm), entry)
        idx.setdefault(_norm(nm.split()[-1]), entry)
    return idx

LEAGUE_ID = 9000       # top flight
LEAGUE_ID_2 = 9001     # second division (promotion/relegation between the two)
SEASON_ID = 9000
TEAM_BASE = 800_000
PLAYER_BASE = 20_000_000
FIXTURE_BASE = 9_000_000
FORMATION_BASE = 910_000   # per-team formation-id pairs: fid0 = 910000 + idx*2, fid1 = fid0 + 1

# Curated fallback shapes: (label, [(role_code, x, y) per slot 0..10]). Used when a club has no
# real eFootball counterpart to copy a formation from. Game coordinate ranges: x 12-92 (centre
# 52), y 3-43 (depth from own goal; GK = 3). Role codes: 0 GK, 1 CB, 2 LB, 3 RB, 4 DMF, 5 CMF,
# 6 LMF, 7 RMF, 8 AMF, 9 LWF, 10 RWF, 11 SS, 12 CF.
FALLBACK_SHAPES = [
    ("4-4-2", [(0, 52, 3), (2, 16, 15), (1, 40, 13), (1, 64, 13), (3, 88, 15),
               (6, 16, 28), (5, 42, 26), (5, 62, 26), (7, 88, 28), (12, 42, 40), (12, 62, 40)]),
    ("4-3-3", [(0, 52, 3), (2, 16, 15), (1, 40, 13), (1, 64, 13), (3, 88, 15),
               (4, 52, 22), (5, 36, 28), (5, 68, 28), (9, 18, 39), (10, 86, 39), (12, 52, 41)]),
    ("4-2-3-1", [(0, 52, 3), (2, 16, 15), (1, 40, 13), (1, 64, 13), (3, 88, 15),
                 (4, 40, 23), (4, 64, 23), (6, 18, 33), (8, 52, 33), (7, 86, 33), (12, 52, 41)]),
    ("3-5-2", [(0, 52, 3), (1, 30, 13), (1, 52, 12), (1, 74, 13), (6, 14, 26),
               (4, 52, 22), (5, 38, 28), (5, 66, 28), (7, 90, 26), (12, 42, 40), (12, 62, 40)]),
]


def real_team_templates(con):
    """Normalised real-club name -> team_id for every eFootball (is_custom=0) team in the DB, so
    a career club can copy its real counterpart's formation geometry. Same normalisation as the
    match compiler, so 'Liverpool FC' finds eFootball's 'Liverpool R'."""
    from play_match import _norm_club
    idx = {}
    for tid, name in con.execute("SELECT id, name FROM teams WHERE is_custom=0"):
        key = _norm_club(name or "")
        if key:
            idx.setdefault(key, tid)
    return idx


def template_geometry(con, tid):
    """A real team's {phase: (style, [(slot, role, x, y) x11])} from its own fid pair, or None
    if either phase's geometry is incomplete in the DB."""
    out = {}
    for phase, fid, style in con.execute(
            "SELECT phase, formation_id, style FROM team_tactics WHERE team_id=? ORDER BY phase",
            (tid,)).fetchall():
        slots = con.execute(
            "SELECT slot_index, position, x, y FROM formation_slots WHERE formation_id=? "
            "ORDER BY slot_index", (fid,)).fetchall()
        if len(slots) != 11:
            return None
        out[phase] = (style, slots)
    if 0 not in out:
        return None
    out.setdefault(1, out[0])
    return out


def norm_club_key(name: str):
    from play_match import _norm_club
    return _norm_club(name or "")


def player_portrait(rfs_pid: int) -> str | None:
    p = RFS_PLAYERS / f"p{rfs_pid}.png"
    return str(p) if p.exists() else None


def all_leagues(catalog: dict):
    """(country, league) pairs across the whole catalog (v2 format: countries → leagues)."""
    for c in catalog.get("countries", []):
        for lg in c["leagues"]:
            yield c, lg


def find_by_comp(catalog: dict, comp_id: int):
    for c, lg in all_leagues(catalog):
        if lg["comp_id"] == comp_id:
            return c, lg
    return None, None


def find_club(catalog: dict, rfs_id: int | None, team: str | None):
    """Locate a club (and its real league) by id, else by name."""
    t = (team or "").lower()
    best = None
    for c, lg in all_leagues(catalog):
        for club in lg["teams"]:
            if rfs_id is not None and club["rfs_id"] == rfs_id:
                return c, lg, club
            if rfs_id is None and t:
                if club["name"].lower() == t:
                    return c, lg, club
                if best is None and t in club["name"].lower():
                    best = (c, lg, club)
    return best if best else (None, None, None)


def second_tier(country: dict, league: dict):
    """The real league one tier below the chosen one in the same country, if the catalog has it."""
    below = [lg for lg in country["leagues"] if lg["tier"] == league["tier"] + 1]
    return below[0] if below else None


def double_round_robin(team_ids: list[int]) -> list[tuple[int, int, int]]:
    ts = list(team_ids)
    if len(ts) % 2:
        ts.append(-1)
    n = len(ts)
    rounds = []
    for md in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = ts[i], ts[n - 1 - i]
            if a != -1 and b != -1:
                pairs.append((a, b) if md % 2 == 0 else (b, a))
        rounds.append(pairs)
        ts = [ts[0]] + [ts[-1]] + ts[1:-1]
    out = []
    for md, pairs in enumerate(rounds, 1):
        out += [(md, h, a) for h, a in pairs]
    for md, pairs in enumerate(rounds, len(rounds) + 1):
        out += [(md, a, h) for h, a in pairs]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default=None, help="managed club name (within --comp-id if given)")
    ap.add_argument("--rfs-id", type=int, default=None, dest="rfs_id",
                    help="unambiguous managed-club id (preferred over --team)")
    ap.add_argument("--comp-id", type=int, default=None, dest="comp_id",
                    help="REAL league to play in (catalog comp_id, e.g. 13 = Premier League)")
    ap.add_argument("--db", default=str(REPO / "build" / "master.db"))
    args = ap.parse_args()

    # ── career-save guard (roadmap item 7): a reseed DELETES the current career's id ranges.
    # guard_reseed refuses while a played career exists, unless ML_CONFIRM_RESEED=1 — and then
    # it snapshots the career to /careers first. Must stay ahead of any DB write.
    from career_snapshot import guard_reseed
    if not guard_reseed(Path(args.db), action="career reseed"):
        return 2

    if not CATALOG.exists():
        sys.exit("build/catalog.json missing — run tools/build_catalog.py first")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    # Catalog v3 renamed comp_id->league_id and rfs_id->team_id. Alias the old keys so the rest of
    # this seeder (which reads comp_id/rfs_id) works against both v2 and v3 catalogs.
    for _co in catalog.get("countries", []):
        for _lg in _co.get("leagues", []):
            _lg.setdefault("comp_id", _lg.get("league_id"))
            for _t in _lg.get("teams", []):
                _t.setdefault("rfs_id", _t.get("team_id"))

    # Resolve the REAL league (division 1 of the career) and the managed club.
    if args.comp_id is not None:
        country, league = find_by_comp(catalog, args.comp_id)
        if league is None:
            sys.exit(f"league comp_id {args.comp_id} not in catalog")
        chosen = None
        if args.rfs_id is not None:
            chosen = next((c for c in league["teams"] if c["rfs_id"] == args.rfs_id), None)
        elif args.team:
            t = args.team.lower()
            chosen = next((c for c in league["teams"] if c["name"].lower() == t), None) \
                or next((c for c in league["teams"] if t in c["name"].lower()), None)
        if chosen is None:
            chosen = league["teams"][0]
    else:
        country, league, chosen = find_club(catalog, args.rfs_id, args.team or "FK Partizan Belgrade")
        if chosen is None:
            sys.exit(f"club not found in catalog: {args.rfs_id or args.team!r}")

    # Division 2 is the country's REAL next tier down when the catalog has one (Premier League →
    # Championship); otherwise the strongest clubs of the country not already in division 1.
    lower = second_tier(country, league)
    if lower is not None:
        div2_clubs = list(lower["teams"])
        div2_name = lower["name"]
    else:
        used = {c["rfs_id"] for c in league["teams"]}
        rest = [c for lg in country["leagues"] for c in lg["teams"] if c["rfs_id"] not in used]
        rest.sort(key=lambda c: -c["rating"])
        div2_clubs = rest[:len(league["teams"])]
        div2_name = f"{league['name']} · Division 2"
    # Some countries only carry one league in the data — a single-division career is fine
    # (the app skips promotion/relegation when the second tier is empty).
    if not div2_clubs:
        print(f"note: {country['name']} has a single division — no second tier this career")
    tier_clubs = {LEAGUE_ID: list(league["teams"]), LEAGUE_ID_2: div2_clubs}
    size = len(tier_clubs[LEAGUE_ID])

    import sqlite3
    con = sqlite3.connect(args.db, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")   # wait out any concurrent writer (e.g. face import)
    con.executescript((REPO / "src" / "ML.Data" / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys=OFF")
    rfs = RfsDb(RFS_DB)
    pt = rfs.tables["players"]
    pidx = {struct.unpack_from("<I", rfs.record("players", i), 0)[0]: i for i in range(pt.rows)}
    tpl = rfs.tables["teamplayerlinks"]
    links = defaultdict(list)
    for i in range(tpl.rows):
        r = rfs.record("teamplayerlinks", i)
        links[struct.unpack_from("<I", r, 0)[0]].append((r[8], struct.unpack_from("<I", r, 4)[0]))

    ef_index = load_ef_index()
    templates = real_team_templates(con)

    con.execute("BEGIN")
    # A career reseed clears ONLY its own reserved id range — never the imported world above it.
    # Imported RFS players live at >= 700,000,000 and RFS teams at >= 3,000,000 (tools/rfs_full_import),
    # carrying facepack real_face_path; an open-ended ">= base" DELETE would wipe them, so every
    # career DELETE is upper-bounded to stay below the import ranges.
    RFS_PLAYER_BASE, RFS_TEAM_BASE, INF = 700_000_000, 3_000_000, 1 << 62
    # The curated 2026/27 overlay (tools/update_career_squad.py) lives at 45-46bn and is only
    # ever ATTACHED to career squads — its memberships are career state and must fall with the
    # career. Its player rows are NOT deleted here: they pair 1:1 with player_identity spine
    # rows (kind='curated', validate gate 7) that update_career_squad does not re-mint, and the
    # overlay ids are stable across reseeds by construction.
    CURATED_LO, CURATED_HI = 45_000_000_000, 46_000_000_000
    for tbl, col, base, cap in (
            ("player_attributes", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("squad_members", "team_id", TEAM_BASE, RFS_TEAM_BASE),
            ("squad_members", "player_id", CURATED_LO, CURATED_HI),
            ("team_tactics", "team_id", TEAM_BASE, RFS_TEAM_BASE),
            ("coaches", "team_id", TEAM_BASE, RFS_TEAM_BASE),
            ("results", "fixture_id", FIXTURE_BASE, INF),
            ("fixtures", "id", FIXTURE_BASE, INF),
            ("players", "id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("teams", "id", TEAM_BASE, RFS_TEAM_BASE),
            # CASCADE (audit 2026-08-23): a reset used to leave every one of these behind —
            # ghost contracts inflating the wage bill, dead players' skills silently inherited
            # by the next career's reused pids, match data for deleted fixtures.
            ("player_skills", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_playstyles", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_traits", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_appearance", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_market", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_potential", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_knowledge", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_positions", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("player_status", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("morale", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("promises", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("training_focus", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("skill_training", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("academy", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("contracts", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("transfers", "player_id", PLAYER_BASE, RFS_PLAYER_BASE),
            ("objectives", "team_id", TEAM_BASE, RFS_TEAM_BASE),
            ("match_events", "fixture_id", FIXTURE_BASE, INF),
            ("match_team_stats", "fixture_id", FIXTURE_BASE, INF),
            ("match_player_ratings", "fixture_id", FIXTURE_BASE, INF)):
        try:
            con.execute(f"DELETE FROM {tbl} WHERE {col} >= ? AND {col} < ?", (base, cap))
        except sqlite3.OperationalError:
            pass                       # table absent on an older DB — nothing to cascade
    # team-scoped meta + the per-club youth layer are career artefacts too
    con.execute("DELETE FROM meta WHERE (key LIKE 'chairman_8%' OR key LIKE 'mgrname_8%' "
                "OR key LIKE 'ttalk_pre_9%')")
    # A new career is a new life (P5 audit): the previous save's mail, scout missions,
    # honours and loans must not haunt the fresh one. All four are pure career artefacts.
    for tbl in ("inbox", "scout_jobs", "honours", "loans"):
        try:
            con.execute(f"DELETE FROM {tbl}")
        except sqlite3.OperationalError:
            pass
    try:
        con.execute("DELETE FROM squad_members WHERE team_id IN "
                    "(SELECT id FROM teams WHERE team_kind IN ('u21','u18'))")
        con.execute("DELETE FROM teams WHERE team_kind IN ('u21','u18')")
    except sqlite3.OperationalError:
        pass
    # Career clubs own their formation-id pairs (>= FORMATION_BASE) and their condition rows;
    # both are reseeded below. player_condition may predate this schema on old DBs — tolerate.
    con.execute("DELETE FROM formation_slots WHERE formation_id >= ?", (FORMATION_BASE,))
    con.execute("DELETE FROM formations WHERE id >= ?", (FORMATION_BASE,))
    try:
        con.execute("DELETE FROM player_condition WHERE player_id >= ? AND player_id < ?",
                    (PLAYER_BASE, RFS_PLAYER_BASE))
    except sqlite3.OperationalError:
        pass
    con.execute("DELETE FROM board_confidence WHERE season_id=?", (SEASON_ID,))
    for lg in (LEAGUE_ID, LEAGUE_ID_2):
        con.execute("DELETE FROM fixtures WHERE league_id=?", (lg,))
        con.execute("DELETE FROM leagues WHERE id=?", (lg,))
    con.execute("DELETE FROM seasons WHERE id=?", (SEASON_ID,))

    con.execute("INSERT INTO leagues(id,name,tier,promotion_places,relegation_places,competition_slot) "
                "VALUES(?,?,1,0,3,586)", (LEAGUE_ID, league["name"]))
    con.execute("INSERT INTO leagues(id,name,tier,promotion_places,relegation_places,competition_slot) "
                "VALUES(?,?,2,3,3,586)", (LEAGUE_ID_2, div2_name))
    con.execute("INSERT INTO seasons(id,year,is_current) VALUES(?,?,1)", (SEASON_ID, 2026))

    next_pid = PLAYER_BASE + 1
    tid_counter = 0
    tier_team_ids = {LEAGUE_ID: [], LEAGUE_ID_2: []}
    managed_tid, managed_lg = TEAM_BASE, LEAGUE_ID
    portraits = 0
    # Real FM finances where we have them (resolved by club name): a club's own transfer budget,
    # else ~40% of its cash balance. Falls back to a rank formula for clubs FM didn't load.
    fm_budget = {}
    try:
        for nm, tb, bal in con.execute(
                "SELECT name, transfer_budget, balance FROM fm_clubs WHERE name IS NOT NULL"):
            key = norm_club_key(nm)
            if key in fm_budget:
                continue
            if tb and tb > 0:
                fm_budget[key] = int(tb)
            elif bal and bal > 0:
                fm_budget[key] = int(bal * 0.4)
        print(f"fm_clubs budgets available for {len(fm_budget):,} clubs")
    except sqlite3.OperationalError:
        pass   # fm_clubs not imported on this DB — fall back to the rank formula
    for lg, clubs in tier_clubs.items():
        for i, club in enumerate(clubs):
            tid = TEAM_BASE + tid_counter
            tid_counter += 1
            tier_team_ids[lg].append(tid)
            if club["rfs_id"] == chosen["rfs_id"]:
                managed_tid, managed_lg = tid, lg
            short = club["name"].replace("FK ", "").replace("FC ", "").replace(" FC", "").split(" ")[0]
            con.execute(
                "INSERT INTO teams(id,game_team_id,is_custom,name,short_name,league_id,budget,logo_path)"
                " VALUES(?,?,1,?,?,?,?,?)",
                (tid, tid, club["name"], short[:12], lg,
                 fm_budget.get(norm_club_key(club["name"])) or (1_000_000 + (size - i) * 60_000),
                 club.get("logo")))
            con.execute("INSERT INTO coaches(id,game_coach_id,team_id,name) VALUES(?,?,?,?)",
                        (tid, tid, tid, f"{short} Manager"))

            # Every career club OWNS a formation-id pair (Main + Sub) — geometry is per-team
            # property, edited in place, never shared and never repointed. Template: the club's
            # real eFootball counterpart's shape + style where one exists, else a rotating
            # curated standard shape.
            idx = tid - TEAM_BASE
            fid0 = FORMATION_BASE + idx * 2
            tpl_tid = templates.get(norm_club_key(club["name"]))
            tpl = template_geometry(con, tpl_tid) if tpl_tid else None
            if tpl:
                phases = {0: tpl[0], 1: tpl[1]}
                shape_label = None
            else:
                shape_label, shape = FALLBACK_SHAPES[idx % len(FALLBACK_SHAPES)]
                slots = [(s, role, x, y) for s, (role, x, y) in enumerate(shape)]
                phases = {0: (i % 5, slots), 1: (i % 5, slots)}
            for phase in (0, 1):
                fid = fid0 + phase
                style, slots = phases[phase]
                con.execute("INSERT INTO formations(id,name) VALUES(?,?)",
                            (fid, shape_label or f"{short} {'Main' if phase == 0 else 'Sub'}"))
                con.executemany(
                    "INSERT INTO formation_slots(formation_id,slot_index,position,x,y) "
                    "VALUES(?,?,?,?,?)", [(fid, s, role, x, y) for s, role, x, y in slots])
                con.execute("INSERT INTO team_tactics(team_id,phase,formation_id,style) "
                            "VALUES(?,?,?,?)", (tid, phase, fid, style))
            # Squad source: the SORTED master.db (the single source of truth — consolidated,
            # deduped, real membership from tools/sort_database.py). Each reference-world player is
            # copied into the career namespace with its own attributes + face. Fall back to the RFS
            # binary only for a club the sort left without a squad, so no career is ever empty.
            db_squad = con.execute(
                "SELECT player_id, squad_number FROM squad_members WHERE team_id=? ORDER BY slot",
                (club["rfs_id"],)).fetchall()
            placed = 0
            for src_pid, shirt in db_squad:
                row = con.execute(
                    "SELECT name,position,overall_rating,portrait_path,real_face_path,"
                    "height_cm,weight_kg,age,nationality FROM players WHERE id=?", (src_pid,)).fetchone()
                if row is None:
                    continue
                nm, pos, ovr, portrait, face, h, w, age, nat = row
                our = next_pid
                next_pid += 1
                if portrait or face:
                    portraits += 1
                con.execute(
                    "INSERT INTO players(id,game_pid,is_custom,name,position,overall_rating,"
                    "portrait_path,real_face_path,height_cm,weight_kg,age,nationality) "
                    "VALUES(?,?,1,?,?,?,?,?,?,?,?,?)",
                    (our, our, nm, pos, ovr, portrait, face, h, w, age, nat))
                con.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                                [(our, a, v) for a, v in con.execute(
                                    "SELECT attribute,value FROM player_attributes WHERE player_id=?",
                                    (src_pid,)).fetchall()])
                s = shirt if (shirt and 1 <= shirt <= 99) else 1
                con.execute("INSERT INTO squad_members(team_id,player_id,squad_number,slot) VALUES(?,?,?,?)",
                            (tid, our, s, placed))
                placed += 1
            if placed == 0:                       # legacy RFS fallback for a club the sort missed
                for shirt, pid in sorted(links.get(club["rfs_id"], [])):
                    if pid not in pidx:
                        continue
                    p = translate(rfs.record("players", pidx[pid]))
                    ef = ef_index.get(_norm(p["name"])) or ef_index.get(_norm(p["name"].split()[-1]))
                    overall = ef[0] if ef else p["overall"]
                    abilities = ef[1] if ef and ef[1] else p["abilities"]
                    bio = ef[2] if ef else {}
                    our = next_pid
                    next_pid += 1
                    portrait = player_portrait(pid)
                    if portrait:
                        portraits += 1
                    con.execute(
                        "INSERT INTO players(id,game_pid,is_custom,name,position,overall_rating,"
                        "portrait_path,height_cm,weight_kg,age,nationality) VALUES(?,?,1,?,?,?,?,?,?,?,?)",
                        (our, our, p["name"], p["position"], overall, portrait,
                         bio.get("height"), bio.get("weight"), bio.get("age"), bio.get("nationality")))
                    con.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                                    [(our, a, v) for a, v in abilities.items()])
                    slot = shirt if 1 <= shirt <= 99 else 1
                    con.execute("INSERT INTO squad_members(team_id,player_id,squad_number,slot) VALUES(?,?,?,?)",
                                (tid, our, slot, placed))
                    placed += 1
            con.execute("INSERT INTO board_confidence(team_id,season_id,confidence,expectation) VALUES(?,?,?,?)",
                        (tid, SEASON_ID, 58, "Title challenge" if i == 0 else "Mid-table"))

    fid = FIXTURE_BASE
    for lg, ids in tier_team_ids.items():
        for md, h, a in double_round_robin(ids):
            con.execute("INSERT INTO fixtures(id,season_id,league_id,matchday,home_team_id,away_team_id,"
                        "played,kind) VALUES(?,?,?,?,?,?,0,'league')", (fid, SEASON_ID, lg, md, h, a))
            fid += 1
    rival = next((t for t in tier_team_ids[managed_lg] if t != managed_tid), managed_tid)
    con.execute("INSERT INTO fixtures(id,season_id,league_id,matchday,home_team_id,away_team_id,"
                "played,kind) VALUES(?,?,?,0,?,?,0,'friendly')", (fid, SEASON_ID, managed_lg,
                managed_tid, rival))

    # Membership integrity sweep (audit 2026-08-23): a career squad row must never reference a
    # player id with no players row. Two id families legitimately sit OUTSIDE the career band
    # and therefore outside every bounded DELETE above — world signings (eF/RFS/FM ids) and the
    # curated 45-46bn overlay — so band arithmetic cannot prove them. Existence is the test:
    # a membership whose player row is missing is a dangling ghost that silently empties every
    # per-squad query for that club, and it dies here.
    con.execute(
        "DELETE FROM squad_members WHERE ((team_id >= ? AND team_id < ?) "
        "OR (team_id >= 9000000 AND team_id < 9200000)) "
        "AND player_id NOT IN (SELECT id FROM players)", (TEAM_BASE, RFS_TEAM_BASE))
    swept = con.execute("SELECT changes()").fetchone()[0]
    if swept:
        print(f"integrity sweep: removed {swept} squad rows that referenced missing players")

    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('current_team_id',?)", (str(managed_tid),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('current_season_id',?)", (str(SEASON_ID),))
    con.commit()

    # borrow the canonical facepack face for each career copy (surname+nationality+age match
    # against the reference world); the RFS portrait_path stays as the UI's fallback
    faced = _backfill_real_faces(con)

    total = con.execute("SELECT COUNT(*) FROM teams WHERE id>=?", (TEAM_BASE,)).fetchone()[0]
    sp = con.execute("SELECT COUNT(*) FROM squad_members WHERE team_id>=?", (TEAM_BASE,)).fetchone()[0]
    tier_name = "top flight" if managed_lg == LEAGUE_ID else "Division 2"
    n_tiers = 2 if tier_clubs[LEAGUE_ID_2] else 1
    print(f"Career: {chosen['name']} in {league['name']} — {tier_name} ({total} clubs, {n_tiers} tier{'s' if n_tiers > 1 else ''})")
    print(f"  {sp} squad players, {portraits} with face photos, {faced} matched to facepack faces")
    con.close()
    return 0


def _backfill_real_faces(con) -> int:
    """Match each career copy (20M-700M) to its reference-world counterpart by
    surname + nationality (+ age within 2) and copy that player's real_face_path."""
    import re
    import unicodedata

    def norm(s):
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s.lower())).strip()

    canon = {}
    for nm, nat, age, face in con.execute(
            "SELECT name, nationality, age, real_face_path FROM players "
            "WHERE real_face_path IS NOT NULL AND (id<20000000 OR id>=700000000)"):
        words = norm(nm).split()
        if words:
            canon.setdefault((words[-1], norm(nat or "")), []).append((age or 0, face))

    hit = 0
    for pid, nm, nat, age in con.execute(
            "SELECT id, name, nationality, age FROM players "
            "WHERE id BETWEEN 20000000 AND 699999999 AND real_face_path IS NULL").fetchall():
        words = norm(nm).split()
        if not words:
            continue
        faces = {f for ca, f in canon.get((words[-1], norm(nat or "")), [])
                 if abs(ca - (age or 0)) <= 2}
        if len(faces) == 1:
            con.execute("UPDATE players SET real_face_path=? WHERE id=?", (faces.pop(), pid))
            hit += 1
    con.commit()
    return hit


if __name__ == "__main__":
    raise SystemExit(main())
