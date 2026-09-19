#!/usr/bin/env python3
"""
career_seed.py — seed a real, playable career into build/master.db for ANY club.

    python tools/career_seed.py --team "Liverpool FC"
    python tools/career_seed.py --comp-id 13 --rfs-id 3000005

Given a club, this builds division 1 from that club's real league in build/catalog.json and
division 2 from the real tier below it, copies every club's squad out of master.db — the single
source of truth — into the career's own id range, wires coach tactics, generates a full double
round-robin season plus the opening preseason friendly, and marks the chosen club as the one you
manage.

Everything lives in reserved id ranges (leagues 9000-9999, teams 800000+, players 20,000,000+) so a
new career overwrites the last without touching the world the Market browses.

WHY THERE IS NO RFS HERE ANY MORE. This opened the owner's private RFS binary on every seed to feed
a fallback for "a club the sort left without a squad" — a case that does not exist. Not one of the
catalog's 2,037 clubs has an empty master.db squad, and the fallback looked players up by the wrong
kind of id anyway, so it matched nothing even on the days it ran. A career seeded with it and one
seeded without it come out byte for byte the same. All it did was make the seed impossible for
anyone who does not own that private file — which is everyone who downloads the release.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

# The MVP world (ruling 2026-09-13): build/game_world.db, built from the player's own eFootball by
# tools/game_world.py, with its picker list build/game_catalog.json beside it. The curated
# build/master.db + build/catalog.json still seed when named explicitly with --db / --catalog.
DEFAULT_DB = REPO / "build" / "game_world.db"
GAME_CATALOG = "game_catalog.json"
CURATED_CATALOG = REPO / "build" / "catalog.json"

LEAGUE_ID = 9000       # top flight
LEAGUE_ID_2 = 9001     # second division (promotion/relegation between the two)
SEASON_ID = 9000
TEAM_BASE = 800_000
PLAYER_BASE = 20_000_000
FIXTURE_BASE = 9_000_000
FORMATION_BASE = 910_000   # per-team formation-id pairs: fid0 = 910000 + idx*2, fid1 = fid0 + 1

# ── the career's id bands ──────────────────────────────────────────────────────────────────────
# Everything a career owns sits inside these, and everything outside them belongs to the world.
# Every delete in clear_career() is bounded by one of them — an open-ended ">= base" would reach
# past the career and wipe the imported world above it (RFS players start at 700,000,000, RFS
# teams at 3,000,000). A career is finite; the DELETEs that clear it must be too.
TEAM_LO, TEAM_HI = 800_000, 1_000_000            # career clubs
YOUTH_LO, YOUTH_HI = 9_000_000, 9_200_000        # their U21/U18 sides
PLAYER_LO, PLAYER_HI = 20_000_000, 700_000_000   # career copies of players
CURATED_LO, CURATED_HI = 45_000_000_000, 46_000_000_000   # the 2026/27 overlay (rows NEVER deleted)
LEAGUE_LO, LEAGUE_HI = 9000, 10_000              # 9000/9001 divisions + 9002-9004 cups
SEASON_LO = 9000
INF = 1 << 62

# ── what survives a new career ─────────────────────────────────────────────────────────────────
# The meta table holds two different things under one roof: the machine you play on and the
# preferences you set once (yours — they outlive any career), and the state of the save itself
# (the board's mood, your sacking, whose corners you take — all of it belongs to a career that no
# longer exists). The old clear deleted three key patterns by LIKE and left everything else, so a
# brand-new career started already sacked, with the previous board's confidence, the last squad's
# penalty taker and a stale list of job offers. An allowlist cannot make that mistake: anything not
# named here is career state and goes.
CARRY_OVER_META = frozenset({
    "ui_skin",              # Settings: which skin the app wears
    "mask_strict",          # Settings: how much you know about players you have not scouted
    "attr_fm_mode",         # Settings: FM colour bands instead of raw attribute numbers
    "transfer_difficulty",  # Settings: how hard selling clubs bargain
    "injury_freq",          # Settings: how often the world gets injured
    "sack_leniency",        # Settings: how patient boards are, everywhere
    "auto_boot",            # Settings: whether Play Match boots eFootball for you
    "real_names",           # Settings: real club names in the compiled match
    "record_matches",       # Settings: record matches through OBS
    "obs_url",              # Settings: your OBS WebSocket address
    "obs_password",         # Settings: your OBS WebSocket password
    "ffmpeg_path",          # Settings: where ffmpeg lives on this machine
    "video_dir",            # Settings: where recorded matches are written
    "steam_root",           # machine path: your Steam install
    "steam_user_id",        # machine path: which Steam account's screenshots to watch
    "manager_name",         # you. The new-career screen offers it back as the default
    "manager_nat",          # you
})

# Nothing carries over from the career itself — a new job is a new life. This set exists to hold
# the one key that is still an open question rather than a settled no:
#   manager_rep — your standing in the game. A real manager keeps his reputation when he changes
#   clubs, so carrying it would be defensible; but it also decides which clubs will have you, and
#   a fresh download inheriting a previous save's reputation is the wrong first impression.
#   Left OUT until the owner rules. Adding the string here is the whole change.
CARRY_OVER_CAREER: frozenset[str] = frozenset()

# Facts about the WORLD, not the save: which eFootball it was read from and, above all, the id
# range its careers copy players into. They are not preferences either, so they sit in neither
# list above — and the allowlist clear would have deleted them. Losing career_player_band is not
# cosmetic: the next career would fall back to 20M-700M, where a game-built world keeps ~1,600
# REAL players, and its clean slate would delete them.
WORLD_META = frozenset({"world_source", "world_scope", "world_reader_version", "world_built_at",
                        "world_archives", "career_player_band"})

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


def lower_tier_clubs(country: dict, league: dict, size: int):
    """Division 2's clubs, and the name to put on it.

    The real tier below, when the catalog has one: Premier League → Championship.

    THE BUG THIS FIXES: when it did not — when you picked a club in the bottom league the catalog
    carries for that country — division 2 used to be filled with "every other club in the country,
    strongest first". Every other club includes the ones ABOVE you. Start in Austria's 2.Liga and
    Red Bull Salzburg turned up in your second division; across the catalog that happened in 33 of
    144 leagues, and in 8 of them the same club was fielded in both of your divisions at once.
    Clubs may only ever come from a tier BELOW the one you are playing in — the next tier down
    first, and inside a tier the strongest first. If there is no tier below, there is no second
    division, and the career is a single-division one, which the app already handles.
    """
    used = {c["rfs_id"] for c in league["teams"]}
    # Every club that plays at or ABOVE the chosen tier somewhere in this country.
    higher = {c["rfs_id"] for lg in country["leagues"] if lg["tier"] <= league["tier"]
              for c in lg["teams"]}
    below = second_tier(country, league)
    filler = False
    if below is not None:
        pool = [(below["tier"], c) for c in below["teams"]]
        name, cap = below["name"], None
        # A "(Simulated)" league is an invented filler division the catalog build stocked with
        # whoever was left over — which included clubs that play HIGHER: Spain's Primera RFEF
        # career got FC Barcelona in division 2 out of "Spain 4 (Simulated)", Germany's 3.Liga got
        # SC Freiburg. A real lower league (Brazil's state championships, which genuinely run in
        # parallel with Série A) keeps its cross-listed clubs; a filler one may not.
        filler = "(Simulated)" in below["name"]
    else:
        pool = [(lg["tier"], c) for lg in country["leagues"] if lg["tier"] > league["tier"]
                for c in lg["teams"]]
        pool.sort(key=lambda p: (p[0], -p[1]["rating"]))   # nearest tier first, then by rating
        name, cap = f"{league['name']} · Division 2", size
    # No club twice in division 2, and no club in both divisions — the catalog cross-lists a few
    # (a Colombian Apertura club is also in its Clausura), and a duplicate id would seed two
    # career clubs off one record and give the league an unplayable fixture list.
    out, seen = [], set(used)
    for _tier, club in pool:
        if club["rfs_id"] in seen:
            continue
        if filler and club["rfs_id"] in higher:
            continue
        seen.add(club["rfs_id"])
        out.append(club)
        if cap is not None and len(out) >= cap:
            break
    # A second division has to be able to PLAY. Colombia's catalog lists the Apertura and the
    # Clausura as tiers 1 and 2 of one championship — 17 of 18 clubs shared — so the de-duplicated
    # "division 2" was one club, with no fixtures, and the rollover still relegated three into it
    # and promoted one out: the top flight lost two clubs a season. Fewer clubs than the movement
    # between the divisions needs is not a division; it is a single-division career.
    if len(out) <= 3:
        if out:
            print(f"note: only {len(out)} club(s) sit below {league['name']} in {country['name']} "
                  f"once cross-listed clubs are removed — not enough for a second division")
        return [], name
    return out, name


def player_band(con) -> tuple[int, int]:
    """[lo, hi): the id range this world's careers copy players into. A world built from the game
    records its own (meta career_player_band), because real eFootball PIDs occupy 20M-700M; the
    curated world has no key and keeps PLAYER_LO/PLAYER_HI, exactly as before."""
    try:
        row = con.execute("SELECT value FROM meta WHERE key='career_player_band'").fetchone()
    except sqlite3.Error:
        row = None
    if row and row[0]:
        lo, hi = (int(x) for x in str(row[0]).split(","))
        if 0 < lo < hi:
            return lo, hi
    return PLAYER_LO, PLAYER_HI


def clear_career(con) -> dict[str, int]:
    """Wipe every trace of the previous career out of an open connection — and nothing else.

    Runs inside the CALLER's transaction: it opens none and commits none, so if anything raises,
    the whole clear rolls back with it and the database still holds a coherent career. Returns
    {step: rows removed}, for the caller to print.

    Also imported by tools/sanitize_release_db.py under exactly this name, to strip the owner's
    save out of the database that ships in the release.

    THE BUG THIS REPLACES: the clear was a list of bounded DELETEs scattered through main() plus
    three meta keys matched by LIKE, and everything it did not name survived into the next save.
    A brand-new career therefore opened already sacked, with the previous board's confidence and
    its list of job offers, the last squad's penalty taker and captain, staff still on the wage
    bill, open transfer negotiations, ghost contracts, inherited rivalries and a club history for
    clubs that no longer existed. A new job has to be a new life.

    THE TRAP IT MUST NOT FALL INTO: all 26,040 of the world's transfers carry season_id 9000 —
    the very id a career season uses. Deleting transfers by season would erase the entire transfer
    history of the world. A career transfer is identified by the CLUB at one end of it. Never by
    the season.

    PRECONDITION: PRAGMA foreign_keys must be OFF on the connection (both callers set it before
    they open their transaction). The deletes are grouped by id band, not ordered child-first, so
    with enforcement on a career player's negotiation or loan row would block the player's own
    delete half way through. Rather than half-clear, this refuses up front.
    """
    counts: dict[str, int] = {}
    if con.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise RuntimeError("clear_career: PRAGMA foreign_keys must be OFF before the transaction "
                           "opens — the deletes are band-ordered, not FK-ordered")

    band_lo, band_hi = player_band(con)

    def run(step: str, sql: str, params: tuple = ()) -> None:
        before = con.total_changes
        try:
            con.execute(sql, params)
        except sqlite3.OperationalError as e:
            # Only the one case this tolerates: a table this DB never had (older saves predate
            # half of these). A typo, a renamed column or a locked file is a real fault, and
            # swallowing it here would leave the caller's transaction committing a half-clear.
            if "no such table" not in str(e):
                raise
            counts.setdefault(step + " (skipped: table absent)", 0)
            return
        counts[step] = counts.get(step, 0) + (con.total_changes - before)

    def teams_band(col: str) -> str:
        """SQL for 'this column names a career club or one of its youth sides'."""
        return (f"(({col} >= {TEAM_LO} AND {col} < {TEAM_HI}) "
                f"OR ({col} >= {YOUTH_LO} AND {col} < {YOUTH_HI}))")

    # ── 1. the career's players, and everything hanging off them ───────────────────────────────
    # The curated 45-46bn overlay is deliberately absent: those player ROWS pair 1:1 with
    # player_identity spine rows (kind='curated', validate gate 7) that nothing re-mints. Only
    # their squad memberships are career state, and those go with the squads below.
    for tbl in ("player_attributes", "player_skills", "player_playstyles", "player_traits",
                "player_appearance", "player_market", "player_potential", "player_knowledge",
                "player_positions", "player_status", "player_condition", "morale", "promises",
                "training_focus", "skill_training", "academy", "contracts", "transfers",
                "squad_members", "players"):
        col = "id" if tbl == "players" else "player_id"
        run("career player rows", f"DELETE FROM {tbl} WHERE {col} >= ? AND {col} < ?",
            (band_lo, band_hi))

    # ── 2. squads: career clubs' rosters, and the curated overlay's memberships ────────────────
    run("squad rows", f"DELETE FROM squad_members WHERE {teams_band('team_id')}")
    run("squad rows", "DELETE FROM squad_members WHERE player_id >= ? AND player_id < ?",
        (CURATED_LO, CURATED_HI))
    # The youth layer is also identified by what it IS, not only by where it sits, in case a U21
    # side was ever minted outside the band.
    run("squad rows", "DELETE FROM squad_members WHERE team_id IN "
                      f"(SELECT id FROM teams WHERE team_kind IN ('u21','u18') AND {teams_band('id')})")

    # ── 3. everything keyed by a career CLUB ──────────────────────────────────────────────────
    for tbl in ("team_tactics", "coaches", "objectives", "contracts", "club_history",
                "board_confidence", "stadiums"):
        run("club rows", f"DELETE FROM {tbl} WHERE {teams_band('team_id')}")
    run("club rows", "DELETE FROM board_confidence WHERE season_id >= ?", (SEASON_LO,))
    run("club rows", "DELETE FROM club_history WHERE season_id >= ?", (SEASON_LO,))
    run("club rows", f"DELETE FROM team_rivals WHERE {teams_band('team_id')} "
                     f"OR {teams_band('rival_id')}")
    # The transfer trap: by club, never by season.
    run("club rows", f"DELETE FROM transfers WHERE {teams_band('to_team_id')} "
                     f"OR {teams_band('from_team_id')}")

    # ── 4. everything keyed by a career FIXTURE ───────────────────────────────────────────────
    for tbl in ("results", "match_events", "match_team_stats", "match_player_ratings",
                "player_match_ratings", "match_player_stats", "match_exports"):
        run("match rows", f"DELETE FROM {tbl} WHERE fixture_id >= ? AND fixture_id < ?",
            (FIXTURE_BASE, INF))
    run("match rows", "DELETE FROM fixtures WHERE id >= ? AND id < ?", (FIXTURE_BASE, INF))
    run("match rows", "DELETE FROM fixtures WHERE league_id >= ? AND league_id < ?",
        (LEAGUE_LO, LEAGUE_HI))

    # ── 5. the clubs, their shapes, their competitions ────────────────────────────────────────
    # Bounded like every other delete here: the day the world itself carries U21/U18 sides (the
    # youth-teams direction the project notes describe), an unbounded by-kind delete would wipe
    # them on the next New Career.
    run("career clubs", f"DELETE FROM teams WHERE team_kind IN ('u21','u18') AND {teams_band('id')}")
    run("career clubs", f"DELETE FROM teams WHERE {teams_band('id')}")
    run("career clubs", "DELETE FROM formation_slots WHERE formation_id >= ?", (FORMATION_BASE,))
    run("career clubs", "DELETE FROM formations WHERE id >= ?", (FORMATION_BASE,))
    # 9000/9001 are the two divisions; 9002-9004 are the National Cup, League Cup and Continental
    # Cup the app mints as it goes. Clearing only 9000/9001 left three orphan cups behind.
    run("career clubs", "DELETE FROM league_rules WHERE league_id >= ? AND league_id < ?",
        (LEAGUE_LO, LEAGUE_HI))
    run("career clubs", "DELETE FROM leagues WHERE id >= ? AND id < ?", (LEAGUE_LO, LEAGUE_HI))
    run("career clubs", "DELETE FROM seasons WHERE id >= ?", (SEASON_LO,))

    # ── 6. whole tables that only ever hold career state ──────────────────────────────────────
    # Mail, scout missions, honours, loans and open negotiations are the save's own memory. None
    # of them mean anything to the next one.
    for tbl in ("inbox", "scout_jobs", "honours", "loans", "negotiations"):
        run("career-only tables", f"DELETE FROM {tbl}")

    # THE BUG THIS REPLACES (found 2026-09-19): staff_people is world-wide state that
    # Session.AssignStartingStaff (ML.App, B7) hands out to EVERY club in the new career's two
    # divisions, not just the club you manage — real world club ids (800000+ on this MVP world),
    # never the OLD curated world's 20M-700M "career copy" band the line below was written for.
    # `teams_band('team_id')` only ever matched that old band, so it silently matched NOTHING
    # here: a reseed never released anyone, EnsureStaffPool's own "table already has rows,
    # nothing to do" guard then skipped rebuilding it, and every career after the very first one
    # ever built on this world kept the exact same frozen, unassigned pool — a fresh new career
    # showing 0 of 9 desks filled despite AssignStartingStaff running (and working) the moment
    # staff_people was genuinely empty. Whole-table wipe matches "a new job has to be a new
    # life": the pool's own content is deterministic from the world seed regardless of which
    # club you manage, so there is nothing useful to preserve — only the world's very first
    # build, ever, should skip rebuilding it.
    for tbl in ("staff_people", "staff"):
        run("career-only tables", f"DELETE FROM {tbl}")

    # ── 7. world rows that merely POINT at the career — corrected, not deleted ─────────────────
    # 14 world players were marked as duplicates OF a career copy. Left pointing at a deleted id,
    # the mark still hides them from every pool that reads "WHERE superseded_by IS NULL".
    run("pointers cleared",
        "UPDATE players SET superseded_by=NULL WHERE superseded_by >= ? AND superseded_by < ?",
        (band_lo, band_hi))
    # And a world club that recorded a career club as the team it derives from.
    run("pointers cleared", f"UPDATE teams SET base_team_id=NULL "
                            f"WHERE {teams_band('base_team_id')} AND NOT {teams_band('id')}")

    # ── 8. meta: keep the allowlist, delete the save ──────────────────────────────────────────
    keep = tuple(sorted(CARRY_OVER_META | CARRY_OVER_CAREER | WORLD_META))
    run("meta keys", f"DELETE FROM meta WHERE key NOT IN ({','.join('?' * len(keep))})", keep)
    return counts


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
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--catalog", default=None,
                    help="the picker list (default: game_catalog.json beside --db)")
    args = ap.parse_args()

    # ── career-save guard (roadmap item 7): a reseed DELETES the current career's id ranges.
    # guard_reseed refuses while a played career exists, unless ML_CONFIRM_RESEED=1 — and then
    # it snapshots the career to /careers first. Must stay ahead of any DB write.
    from career_snapshot import guard_reseed
    if not guard_reseed(Path(args.db), action="career reseed"):
        return 2

    catalog_path = Path(args.catalog) if args.catalog else Path(args.db).with_name(GAME_CATALOG)
    if not args.catalog and not catalog_path.exists() and Path(args.db).name == "master.db":
        catalog_path = CURATED_CATALOG                     # the curated world, named explicitly
    if not catalog_path.exists():
        sys.exit(f"{catalog_path} missing — build the world first: python tools/game_world.py")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
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

    # Division 1 is the chosen club's real league. No club twice in it — the catalog cross-lists a
    # few, and the same club seeded twice would give the league an unplayable fixture list.
    div1_clubs, _seen = [], set()
    for club in league["teams"]:
        if club["rfs_id"] in _seen:
            continue
        _seen.add(club["rfs_id"])
        div1_clubs.append(club)
    div2_clubs, div2_name = lower_tier_clubs(country, league, len(div1_clubs))
    # Some countries only carry one league in the data, and so does the bottom tier of every other
    # country — a single-division career is fine (the app skips promotion and relegation when the
    # second tier is empty).
    if not div2_clubs:
        print(f"note: no second division could be formed below {league['name']} in "
              f"{country['name']} — a single-division career, no promotion or relegation")
    tier_clubs = {LEAGUE_ID: div1_clubs, LEAGUE_ID_2: div2_clubs}
    size = len(tier_clubs[LEAGUE_ID])

    con = sqlite3.connect(args.db, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")   # wait out any concurrent writer (e.g. face import)
    # The schema ships beside the app in the release, but a release does not ship the C# sources.
    # Its only job here is to add tables an older master.db predates; a database that already has
    # them (every released one does) is unchanged by skipping it.
    schema = REPO / "src" / "ML.Data" / "schema.sql"
    if schema.exists():
        con.executescript(schema.read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys=OFF")
    game_world = (con.execute("SELECT value FROM meta WHERE key='world_source'").fetchone()
                  or [None])[0] == "game"
    # Career copies carry their original's game thumbnail (tools/game_faces.py). The app adds the
    # column on open; a database the app has never opened may not have it yet.
    if "game_face_path" not in {r[1] for r in con.execute("PRAGMA table_info(players)")}:
        con.execute("ALTER TABLE players ADD COLUMN game_face_path TEXT")

    templates = real_team_templates(con)

    con.execute("BEGIN")
    # CLEAN SLATE. Every delete and every pointer-fix lives in clear_career() — one function, so
    # nothing can be forgotten in one place and remembered in another, and so the release's
    # sanitiser can call the exact same code. It runs inside this transaction and commits nothing.
    cleared = clear_career(con)
    for step, rows in cleared.items():
        print(f"cleared {rows:,} {step}")

    con.execute("INSERT INTO leagues(id,name,tier,promotion_places,relegation_places,competition_slot) "
                "VALUES(?,?,1,0,3,586)", (LEAGUE_ID, league["name"]))
    con.execute("INSERT INTO leagues(id,name,tier,promotion_places,relegation_places,competition_slot) "
                "VALUES(?,?,2,3,3,586)", (LEAGUE_ID_2, div2_name))
    con.execute("INSERT INTO seasons(id,year,is_current) VALUES(?,?,1)", (SEASON_ID, 2026))

    band_lo, band_hi = player_band(con)
    next_pid = band_lo + 1
    tid_counter = 0
    tier_team_ids = {LEAGUE_ID: [], LEAGUE_ID_2: []}
    managed_tid, managed_lg = TEAM_BASE, LEAGUE_ID
    portraits = 0
    empty_squads: list[str] = []
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
            # The crest comes from the LIVE team row, not from club['logo'] — the catalog is a
            # snapshot and a career club would otherwise keep whatever crest the world happened to
            # be wearing on the day it was seeded. That is how a career Liverpool ended up in AFC
            # Liverpool's badge long after the world's had been corrected.
            live_logo = con.execute("SELECT logo_path FROM teams WHERE id=?",
                                    (club["rfs_id"],)).fetchone()
            con.execute(
                "INSERT INTO teams(id,game_team_id,is_custom,name,short_name,league_id,budget,logo_path)"
                " VALUES(?,?,1,?,?,?,?,?)",
                (tid, tid, club["name"], short[:12], lg,
                 fm_budget.get(norm_club_key(club["name"])) or (1_000_000 + (size - i) * 60_000),
                 (live_logo[0] if live_logo and live_logo[0] else club.get("logo"))))
            # And it records WHICH club it is a copy of. Not by copying the FM club id — that is
            # exclusive, one club to one id, and verify_identity_fm asserts it — but through
            # base_team_id, the pointer the schema already uses for "this team derives from that
            # one". Every id-keyed repair can then reach the career band by following it.
            con.execute("UPDATE teams SET base_team_id=? WHERE id=?", (club["rfs_id"], tid))
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
            # copied into the career namespace with its own attributes + face. There is no second
            # source: see the note at the top of this file about the RFS fallback that never fired.
            db_squad = con.execute(
                "SELECT player_id, squad_number FROM squad_members WHERE team_id=? ORDER BY slot",
                (club["rfs_id"],)).fetchall()
            placed = 0
            for src_pid, shirt in db_squad:
                row = con.execute(
                    "SELECT name,position,overall_rating,portrait_path,real_face_path,game_face_path,"
                    "height_cm,weight_kg,age,nationality FROM players WHERE id=?", (src_pid,)).fetchone()
                if row is None:
                    continue
                nm, pos, ovr, portrait, face, game_face, h, w, age, nat = row
                our = next_pid
                next_pid += 1
                if portrait or face or game_face:
                    portraits += 1
                # base_pid: in a game-built world the source row's id IS its eFootball PID. The
                # copy carries it so Play Match puts the real record on the pitch and the stats
                # host's export (which reports real PIDs) links back to this player. Without it a
                # career fixture's export never linked — the collaborator's open issue.
                con.execute(
                    "INSERT INTO players(id,game_pid,base_pid,is_custom,name,position,overall_rating,"
                    "portrait_path,real_face_path,game_face_path,height_cm,weight_kg,age,nationality) "
                    "VALUES(?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
                    (our, our, src_pid if game_world else None, nm, pos, ovr, portrait, face,
                     game_face, h, w, age, nat))
                con.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                                [(our, a, v) for a, v in con.execute(
                                    "SELECT attribute,value FROM player_attributes WHERE player_id=?",
                                    (src_pid,)).fetchall()])
                if game_world:
                    # The game's own roles and skills travel with the player: Play Match writes
                    # the career copy's playstyles back into Player.bin, and a copy with none
                    # would have them wiped on the pitch.
                    con.executemany(
                        "INSERT OR IGNORE INTO player_playstyles(player_id,playstyle,kind) VALUES(?,?,?)",
                        [(our, st, k) for st, k in con.execute(
                            "SELECT playstyle,kind FROM player_playstyles WHERE player_id=?",
                            (src_pid,)).fetchall()])
                    con.executemany(
                        "INSERT OR IGNORE INTO player_skills(player_id,skill,source) VALUES(?,?,?)",
                        [(our, sk, so) for sk, so in con.execute(
                            "SELECT skill,source FROM player_skills WHERE player_id=?",
                            (src_pid,)).fetchall()])
                s = shirt if (shirt and 1 <= shirt <= 99) else 1
                con.execute("INSERT INTO squad_members(team_id,player_id,squad_number,slot) VALUES(?,?,?,?)",
                            (tid, our, s, placed))
                placed += 1
            if placed == 0:
                # Say so, loudly, and carry on. No catalog club is in this state today, but if the
                # world is ever rebuilt badly enough to empty one, a career that quietly fields an
                # eleven of nobody is far worse than a career that tells you which club is short.
                empty_squads.append(club["name"])
                print(f"warning: {club['name']} has no players in the database — "
                      f"it joins the league with an empty dressing room")
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
        "OR (team_id >= ? AND team_id < ?)) "
        "AND player_id NOT IN (SELECT id FROM players)",
        (TEAM_LO, TEAM_HI, YOUTH_LO, YOUTH_HI))
    swept = con.execute("SELECT changes()").fetchone()[0]
    if swept:
        print(f"integrity sweep: removed {swept} squad rows that referenced missing players")

    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('current_team_id',?)", (str(managed_tid),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('current_season_id',?)", (str(SEASON_ID),))
    con.commit()

    # borrow the canonical facepack face for each career copy (full name+nationality+age match
    # against the reference world); the copied portrait_path stays as the UI's fallback
    faced = _backfill_real_faces(con)

    # Count the CAREER, not the world. These were open-ended ">= 800000", which swept up all
    # 36,594 imported RFS clubs sitting above the band and reported a 44-club career as
    # "36638 clubs" — a number that told the reader nothing except that something was wrong.
    total = con.execute("SELECT COUNT(*) FROM teams WHERE id >= ? AND id < ?",
                        (TEAM_LO, TEAM_HI)).fetchone()[0]
    sp = con.execute("SELECT COUNT(*) FROM squad_members WHERE team_id >= ? AND team_id < ?",
                     (TEAM_LO, TEAM_HI)).fetchone()[0]
    tier_name = "top flight" if managed_lg == LEAGUE_ID else "Division 2"
    n_tiers = 2 if tier_clubs[LEAGUE_ID_2] else 1
    print(f"Career: {chosen['name']} in {league['name']} — {tier_name} ({total} clubs, {n_tiers} tier{'s' if n_tiers > 1 else ''})")
    print(f"  {sp} squad players, {portraits} with face photos, {faced} matched to facepack faces")
    if empty_squads:
        print(f"  {len(empty_squads)} club(s) started with nobody in them: {', '.join(empty_squads)}")
    con.close()
    return 0


def _backfill_real_faces(con) -> int:
    """Match each career copy (20M-700M) to its reference-world counterpart and copy that player's
    real_face_path.

    On the FULL name, not the surname. This matched on `words[-1]` — the last word alone — plus
    nationality and age, which is how a career squad ended up wearing other people's photographs:
    Brazil has a great many players called Alisson, all of an age, and one of them keeps goal for
    Liverpool. A face belongs to a person; a surname does not identify one. Anything this cannot
    settle is left blank for tools/link_faces_by_fm_id.py, which joins on the FM uid and cannot be
    wrong about who it is."""
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
        words = tuple(sorted(norm(nm).split()))
        if len(words) > 1:
            canon.setdefault((words, norm(nat or "")), []).append((age or 0, face))

    hit = 0
    for pid, nm, nat, age in con.execute(
            "SELECT id, name, nationality, age FROM players "
            "WHERE id BETWEEN 20000000 AND 699999999 AND real_face_path IS NULL").fetchall():
        words = tuple(sorted(norm(nm).split()))
        if len(words) < 2:
            continue                      # a mononym is not enough to hang a face on
        faces = {f for ca, f in canon.get((words, norm(nat or "")), [])
                 if abs(ca - (age or 0)) <= 2}
        if len(faces) == 1:
            con.execute("UPDATE players SET real_face_path=? WHERE id=?", (faces.pop(), pid))
            hit += 1
    con.commit()
    return hit


if __name__ == "__main__":
    raise SystemExit(main())
