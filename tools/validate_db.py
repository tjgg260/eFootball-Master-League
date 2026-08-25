#!/usr/bin/env python3
"""
validate_db.py — the blueprint's VALIDATION GATE (docs/database-blueprint.md, audit-as-build-step).

master.db is a compiled artifact; this gate fails the build if the output is broken. Nine
assertions, each printing PASS/FAIL + counts; exit code 1 if ANY fails:

  1  zero dangling references in every player_id / team_id / fixture_id-bearing table
     (aliases included: home/away/from/to_team_id, owner_team, host_team, seller_id, rival_id,
      parent_team_id — discovered by PRAGMA scan, never a hand-kept list)
  2  one squad membership per player
  3  every squad player fully attributed (>= 20 player_attributes rows)
  4  every catalog club (build/catalog.json): exists in teams, >= 18 players incl >= 2 GKs,
     a logo file that exists on disk, a league that exists in leagues
  5  no duplicate identity (full name + age) inside one squad
  6  all stored asset paths repo-relative (absolute paths allowed only under OneDrive — the RFS
     crest/portrait store lives there by design, see relativize_paths.py)
  7  id namespaces respected for squad members: eF < 20M · career 20M-700M (no spine row) ·
     RFS 700M-10B · FM 10-13B · curated 45-46B · generated >= 50B, and the band must agree with
     player_identity.kind — a band-gap id or a kind/band mismatch is a violation
  8  RENDER PROJECTION dry-run: for every catalog club, the top-18 squad (by squad slot — the XI
     + bench play_match compiles) must be projectable into eFootball exactly the way
     play_match.py / ml_author.py would write it:
       - position maps through ml_author.POS_MAP (no silent CMF fallback)
       - all 26 bit-packed abilities present (ability_bits.ABILITY_BITS names); no value above
         103 (the 6-bit field's ceiling — values under 40 clamp up at write and are only counted)
       - primary playstyle mappable: the (position-category, style) pair exists in the game-built
         primary table (playstyle_bits), or — GKs only — the style is a "* Goalkeeper" alias of a
         STYLE_INDEX GK style (GK styles render through the secondary field)
       - secondary playstyle in playstyle_secondary.STYLE_INDEX (Basic / Box-to-Box / Anchor Man
         are the documented deliberate-Basic mirrors and pass)
       - player name non-empty, no NUL, <= 60 UTF-8 bytes (the Player.bin name field cut is
         byte-blind and would corrupt a longer name mid-codepoint); club name <= 480 bytes

  9  superseded records dormant: a players.superseded_by mark (supersede_twins.py, one
     record per human) implies no world squad row, an existing target, and no mark chains

READ-ONLY BY DESIGN: the DB is opened with mode=ro and nothing is ever written — this tool has
no --apply because a validation gate must never mutate what it judges. --dry is accepted for
pipeline symmetry and is the only behaviour.

    python tools/validate_db.py --dry
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from ability_bits import ABILITY_BITS                      # noqa: E402  (the 26-name template)
from ml_author import POS_MAP                              # noqa: E402  (writeback position map)
from playstyle_bits import _pos_cat                        # noqa: E402
from playstyle_secondary import STYLE_INDEX                # noqa: E402

DB = REPO / "build" / "master.db"
CATALOG = REPO / "build" / "catalog.json"

# --- assertion 1: which columns reference which table (matched by exact column name) ----------
PLAYER_COLS = {"player_id"}
TEAM_COLS = {"team_id", "home_team_id", "away_team_id", "from_team_id", "to_team_id",
             "owner_team", "host_team", "seller_id", "rival_id", "parent_team_id"}
FIXTURE_COLS = {"fixture_id"}

# --- assertion 6: every column that stores an asset path --------------------------------------
PATH_COLUMNS = [
    ("players", "portrait_path"), ("players", "real_face_path"),
    ("teams", "logo_path"), ("teams", "kit_home_path"), ("teams", "kit_away_path"),
    ("leagues", "logo_path"), ("results", "screenshot_path"),
]

# --- assertion 7: id namespace bands (docs/database-blueprint.md) -----------------------------
# eFootball's own pids run past 2^24 — 861 of them (Nakashima Yuki at 16,782,442 and up) — so the
# old 1<<24 line left real eFootball players in a nameless GAP band. The namespace ends where the
# career copies begin.
EF_MAX = CAREER_LO = 20_000_000      # eFootball native pids
CAREER_HI = 700_000_000
RFS_LO, RFS_HI = 700_000_000, 10_000_000_000
FM_LO, FM_HI = 10_000_000_000, 13_000_000_000
CUR_LO, CUR_HI = 45_000_000_000, 46_000_000_000
GEN_LO = 50_000_000_000

BAND_CASE = f"""CASE
    WHEN id < {EF_MAX} THEN 'ef'
    WHEN id >= {CAREER_LO} AND id < {CAREER_HI} THEN 'career'
    WHEN id >= {RFS_LO} AND id < {RFS_HI} THEN 'rfs'
    WHEN id >= {FM_LO} AND id < {FM_HI} THEN 'fm'
    WHEN id >= {CUR_LO} AND id < {CUR_HI} THEN 'curated'
    WHEN id >= {GEN_LO} THEN 'generated'
    ELSE 'GAP' END"""

# Secondary styles that deliberately mean Basic (playstyle_secondary.write_secondary docstring:
# offensive styles mirroring the primary are not real secondary styles -> field cleared to 0).
SECONDARY_BASIC_OK = {"Basic", "Box-to-Box", "Anchor Man"}

NAME_BYTES_MAX = 60      # Player.bin name fields: 61 bytes, ml_author cuts at [:60]
TEAM_NAME_BYTES_MAX = 480  # Team.bin name field: 490 bytes, rename cuts at [:480]


def gk_alias(style: str) -> str:
    """'Defensive Goalkeeper' -> 'Defensive GK' (the STYLE_INDEX spelling)."""
    return style.replace("Goalkeeper", "GK").strip()


def load_primary_table():
    """(position category, style) -> raw value, built from the game's own data. Needs
    build/tree_base + samples/editor-bundled-players.csv; None if either is unavailable."""
    try:
        from playstyle_bits import build_style_table
        return build_style_table()
    except Exception as exc:                                  # noqa: BLE001 — degrade, don't die
        print(f"  note: primary-style table unavailable ({exc}) — primary mappability SKIPPED")
        return None


class Gate:
    """Collects PASS/FAIL per assertion and renders the report."""

    def __init__(self, max_detail: int):
        self.failed = 0
        self.max_detail = max_detail

    def report(self, name: str, bad: int, total: int, unit: str, detail: list[str] | None = None):
        status = "PASS" if bad == 0 else "FAIL"
        if bad:
            self.failed += 1
        print(f"{status}  {name}  ({bad:,} offending / {total:,} {unit})")
        for line in (detail or [])[: self.max_detail]:
            print(f"       {line}")
        if detail and len(detail) > self.max_detail:
            print(f"       ... and {len(detail) - self.max_detail:,} more")


# ============================================================================ assertions

def check_dangling(con, gate: Gate) -> None:
    tables = [t for (t,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    targets = {**{c: "players" for c in PLAYER_COLS},
               **{c: "teams" for c in TEAM_COLS},
               **{c: "fixtures" for c in FIXTURE_COLS}}
    bad_total = checked_cols = 0
    detail: list[str] = []
    for t in sorted(tables):
        cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
        for c in cols:
            ref = targets.get(c)
            if ref is None:
                continue
            checked_cols += 1
            # negotiations.seller_id=0 is the documented "free agent — no selling club" sentinel
            sentinel = " AND NOT (seller_id = 0)" if (t, c) == ("negotiations", "seller_id") else ""
            n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL "
                            f"AND {c} NOT IN (SELECT id FROM {ref}){sentinel}").fetchone()[0]
            if n:
                bad_total += n
                ex = [str(v) for (v,) in con.execute(
                    f"SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL "
                    f"AND {c} NOT IN (SELECT id FROM {ref}) LIMIT 5")]
                detail.append(f"{t}.{c} -> {ref}: {n:,} dangling (e.g. {', '.join(ex)})")
    gate.report("1 zero dangling references", bad_total,
                checked_cols, "ref columns scanned", detail)


def check_single_membership(con, gate: Gate) -> None:
    total = con.execute("SELECT COUNT(DISTINCT player_id) FROM squad_members").fetchone()[0]
    rows = con.execute("""
        SELECT player_id, COUNT(*) FROM squad_members GROUP BY player_id
        HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC""").fetchall()
    detail = [f"player {p}: {n} squads" for p, n in rows]
    gate.report("2 one squad membership per player", len(rows), total, "squad players", detail)


def check_attributed(con, gate: Gate) -> None:
    total = con.execute("SELECT COUNT(DISTINCT player_id) FROM squad_members").fetchone()[0]
    rows = con.execute("""
        SELECT m.player_id, COUNT(pa.attribute) AS n
        FROM (SELECT DISTINCT player_id FROM squad_members) m
        LEFT JOIN player_attributes pa ON pa.player_id = m.player_id
        GROUP BY m.player_id HAVING n < 20""").fetchall()
    detail = [f"player {p}: {n} attribute rows" for p, n in rows]
    gate.report("3 every squad player >= 20 attribute rows", len(rows), total,
                "squad players", detail)


def load_catalog() -> dict[int, dict]:
    """Catalog clubs deduped by team_id (a club can appear in several catalog leagues)."""
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    clubs: dict[int, dict] = {}
    for country in cat["countries"]:
        for league in country["leagues"]:
            for team in league["teams"]:
                clubs.setdefault(team["team_id"], team)
    return clubs


def logo_exists(logo: str | None) -> bool:
    if not logo:
        return False
    p = Path(logo)
    return p.exists() if p.is_absolute() else (REPO / logo).exists()


def check_catalog_clubs(con, gate: Gate, clubs: dict[int, dict]) -> None:
    con.execute("CREATE TEMP TABLE IF NOT EXISTS cat(team_id INTEGER PRIMARY KEY)")
    con.executemany("INSERT OR IGNORE INTO cat VALUES(?)", [(t,) for t in clubs])
    rows = con.execute("""
        SELECT c.team_id, t.id IS NULL, t.name,
               (SELECT COUNT(*) FROM leagues l WHERE l.id = t.league_id),
               (SELECT COUNT(*) FROM squad_members sm WHERE sm.team_id = c.team_id),
               (SELECT COUNT(*) FROM squad_members sm JOIN players p ON p.id = sm.player_id
                 WHERE sm.team_id = c.team_id AND p.position = 'GK')
        FROM cat c LEFT JOIN teams t ON t.id = c.team_id""").fetchall()
    detail: list[str] = []
    bad = 0
    for tid, missing, name, league_ok, squad_n, gk_n in rows:
        club = clubs[tid]
        reasons = []
        if missing:
            reasons.append("not in teams table")
        else:
            if squad_n < 18:
                reasons.append(f"squad {squad_n} < 18")
            if gk_n < 2:
                reasons.append(f"{gk_n} GK < 2")
            if not league_ok:
                reasons.append("no league")
        if not logo_exists(club.get("logo")):
            reasons.append("logo missing" if not club.get("logo") else "logo file not found")
        if reasons:
            bad += 1
            detail.append(f"{club['name']} (team {tid}): " + "; ".join(reasons))
    gate.report("4 catalog clubs: >=18 players, >=2 GK, logo file, league",
                bad, len(clubs), "catalog clubs", detail)


def check_squad_duplicates(con, gate: Gate) -> None:
    """A name and an age are not an identity. Altos really does field two Brazilians called
    'Henrique', both 25, and FM gives them two different uids — that is the spine saying they are
    two people, and it outranks the heuristic. Only groups the spine does NOT separate count."""
    total = con.execute("SELECT COUNT(*) FROM squad_members").fetchone()[0]
    rows = con.execute("""
        SELECT sm.team_id, t.name, p.name, p.age, COUNT(*),
               COUNT(DISTINCT pi.fm_uid)
        FROM squad_members sm
        JOIN players p ON p.id = sm.player_id
        LEFT JOIN teams t ON t.id = sm.team_id
        LEFT JOIN player_identity pi ON pi.player_id = p.id
        GROUP BY sm.team_id, p.name, p.age HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC""").fetchall()
    dupes = [r for r in rows if r[5] < r[4]]        # fewer distinct uids than records
    detail = [f"{tname or tid}: '{pname}' age {age} x{n}" for tid, tname, pname, age, n, _u in dupes]
    named = len(rows) - len(dupes)
    if named:
        detail.append(f"(plus {named} namesake group(s) the FM spine separates by uid)")
    gate.report("5 no duplicate (name+age) inside one squad", len(dupes), total,
                "squad rows", detail)


def check_paths(con, gate: Gate, clubs: dict[int, dict]) -> None:
    """Absolute = drive letter, leading slash, or backslashes; allowed only under OneDrive."""
    bad = total = 0
    detail: list[str] = []
    for table, col in PATH_COLUMNS:
        total += con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''").fetchone()[0]
        rows = con.execute(f"""
            SELECT {col}, COUNT(*) FROM {table}
            WHERE {col} IS NOT NULL AND {col} <> ''
              AND ({col} LIKE '_:%' OR {col} LIKE '/%' OR instr({col}, char(92)) > 0)
              AND instr({col}, 'OneDrive') = 0
            GROUP BY {col} LIMIT 6""").fetchall()
        n = con.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE {col} IS NOT NULL AND {col} <> ''
              AND ({col} LIKE '_:%' OR {col} LIKE '/%' OR instr({col}, char(92)) > 0)
              AND instr({col}, 'OneDrive') = 0""").fetchone()[0]
        if n:
            bad += n
            detail.append(f"{table}.{col}: {n:,} non-OneDrive absolute "
                          f"(e.g. {rows[0][0]!r})")
    for tid, club in clubs.items():
        logo = club.get("logo") or ""
        if not logo:
            continue
        total += 1
        if (("\\" in logo or logo.startswith("/") or (len(logo) > 1 and logo[1] == ":"))
                and "OneDrive" not in logo):
            bad += 1
            detail.append(f"catalog logo (team {tid}): {logo!r}")
    gate.report("6 stored paths repo-relative (OneDrive allowlisted)", bad, total,
                "stored paths", detail)


def check_namespaces(con, gate: Gate) -> None:
    total = con.execute("SELECT COUNT(DISTINCT player_id) FROM squad_members").fetchone()[0]
    rows = con.execute(f"""
        WITH m AS (SELECT DISTINCT player_id AS id FROM squad_members),
        b AS (SELECT id, {BAND_CASE} AS band,
                     (SELECT kind FROM player_identity pi WHERE pi.player_id = m.id) AS kind
              FROM m)
        SELECT band, COALESCE(kind, '(no spine row)'), COUNT(*), MIN(id), MAX(id)
        FROM b
        WHERE NOT ((kind IS NULL AND band = 'career') OR (kind IS NOT NULL AND band = kind))
        GROUP BY band, kind ORDER BY COUNT(*) DESC""").fetchall()
    bad = sum(r[2] for r in rows)
    detail = [f"band {band} but kind {kind}: {n:,} players (ids {lo:,}..{hi:,})"
              for band, kind, n, lo, hi in rows]
    gate.report("7 id namespaces respected for squad members", bad, total,
                "squad players", detail)


def check_render_projection(con, gate: Gate, clubs: dict[int, dict]) -> None:
    primary_table = load_primary_table()
    con.execute("DROP TABLE IF EXISTS temp.top18")
    con.execute("""
        CREATE TEMP TABLE top18 AS
        SELECT team_id, player_id, rn FROM (
            SELECT sm.team_id, sm.player_id,
                   ROW_NUMBER() OVER (PARTITION BY sm.team_id
                                      ORDER BY sm.slot, sm.player_id) AS rn
            FROM squad_members sm JOIN cat c ON c.team_id = sm.team_id)
        WHERE rn <= 18""")
    core_names = tuple(ABILITY_BITS)
    ph = ",".join("?" * len(core_names))
    rows = con.execute(f"""
        SELECT t.team_id, t.player_id, p.name, p.position,
               COALESCE(a.core_n, 0), COALESCE(a.hi, 0), COALESCE(a.lo, 0),
               pri.playstyle, sec.playstyle
        FROM top18 t
        JOIN players p ON p.id = t.player_id
        LEFT JOIN (SELECT player_id, COUNT(*) AS core_n,
                          SUM(value > 103) AS hi, SUM(value < 40) AS lo
                   FROM player_attributes
                   WHERE attribute IN ({ph})
                     AND player_id IN (SELECT player_id FROM top18)
                   GROUP BY player_id) a ON a.player_id = t.player_id
        LEFT JOIN player_playstyles pri ON pri.player_id = t.player_id AND pri.kind = 'primary'
        LEFT JOIN player_playstyles sec ON sec.player_id = t.player_id AND sec.kind = 'secondary'
        ORDER BY t.team_id, t.rn""", core_names).fetchall()

    fails: dict[int, list[str]] = defaultdict(list)
    projected_players = 0
    clamped_low = 0
    seen_teams = set()
    for tid, pid, name, pos, core_n, hi, lo, pri, sec in rows:
        seen_teams.add(tid)
        projected_players += 1
        clamped_low += lo or 0
        pos_key = (pos or "").strip().upper()
        if pos_key not in POS_MAP:
            fails[tid].append(f"'{name}' position {pos!r} not in POS_MAP")
        if core_n < len(core_names):
            fails[tid].append(f"'{name}' only {core_n}/{len(core_names)} core abilities")
        if hi:
            fails[tid].append(f"'{name}' {hi} ability value(s) above 103 (6-bit ceiling)")
        if not name or not name.strip() or "\x00" in name:
            fails[tid].append(f"player {pid}: empty/NUL name")
        elif len(name.encode("utf-8")) > NAME_BYTES_MAX:
            fails[tid].append(f"'{name}': {len(name.encode('utf-8'))} UTF-8 bytes "
                              f"> {NAME_BYTES_MAX} (name field cut corrupts)")
        cat_ = _pos_cat(pos_key)
        if pri and primary_table is not None and (cat_, pri) not in primary_table:
            if not (cat_ == "GK" and gk_alias(pri) in STYLE_INDEX):
                fails[tid].append(f"'{name}' ({cat_}): primary style {pri!r} unmappable")
        if sec and sec not in STYLE_INDEX and sec not in SECONDARY_BASIC_OK:
            fails[tid].append(f"'{name}': secondary style {sec!r} not in STYLE_INDEX")

    for tid, club in clubs.items():
        row = con.execute("SELECT name FROM teams WHERE id=?", (tid,)).fetchone()
        if row is None:
            fails[tid].append("club not in teams — nothing to project")
        elif not (row[0] or "").strip():
            fails[tid].append("club has an empty name")
        elif len(row[0].encode("utf-8")) > TEAM_NAME_BYTES_MAX:
            fails[tid].append(f"club name {len(row[0].encode('utf-8'))} UTF-8 bytes "
                              f"> {TEAM_NAME_BYTES_MAX}")
        if tid not in seen_teams:
            fails[tid].append("no squad members to project")

    detail = [f"{clubs[tid]['name']} (team {tid}): " + "; ".join(reasons)
              for tid, reasons in sorted(fails.items()) if reasons]
    print(f"  projection scope: {len(clubs):,} clubs, {projected_players:,} top-18 players; "
          f"{clamped_low:,} ability values under 40 will clamp up at write (allowed)")
    gate.report("8 render projection dry-run (top-18 per catalog club)",
                len(detail), len(clubs), "catalog clubs", detail)


# ============================================================================ main

def check_superseded(con, gate: Gate) -> None:
    """9: superseded records are dormant history (supersede_twins.py) — never squadded in the
    world, never the target of a mark themselves (no chains), targets always exist. Absent
    column = zero offenders (pre-supersede database)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(players)")}
    if "superseded_by" not in cols:
        gate.report("9 superseded records dormant (column absent — vacuous)", 0, 0, "marks")
        return
    total = con.execute(
        "SELECT COUNT(*) FROM players WHERE superseded_by IS NOT NULL").fetchone()[0]
    detail, bad = [], 0
    for pid, tid in con.execute(
            "SELECT s.player_id, s.team_id FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE p.superseded_by IS NOT NULL "
            "AND NOT (s.team_id>=800000 AND s.team_id<1000000) "
            "AND NOT (s.team_id>=9000000 AND s.team_id<9200000)"):
        bad += 1
        detail.append(f"superseded player {pid} still squadded at team {tid}")
    for pid, tgt in con.execute(
            "SELECT a.id, a.superseded_by FROM players a JOIN players b "
            "ON b.id=a.superseded_by WHERE b.superseded_by IS NOT NULL"):
        bad += 1
        detail.append(f"chained mark: {pid} -> {tgt} which is itself superseded")
    for (pid,) in con.execute(
            "SELECT a.id FROM players a LEFT JOIN players b ON b.id=a.superseded_by "
            "WHERE a.superseded_by IS NOT NULL AND b.id IS NULL"):
        bad += 1
        detail.append(f"dangling mark: {pid} -> missing player")
    gate.report("9 superseded records dormant (unsquadded, unchained, targets exist)",
                bad, total, "marks", detail)


def main() -> int:
    global DB, CATALOG
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true",
                    help="accepted for pipeline symmetry; the gate is always read-only")
    ap.add_argument("--db", default=str(DB), help="master DB (opened read-only)")
    ap.add_argument("--catalog", default=str(CATALOG), help="build/catalog.json")
    ap.add_argument("--max-detail", type=int, default=25,
                    help="max detail lines printed per assertion")
    args = ap.parse_args()

    DB, CATALOG = Path(args.db), Path(args.catalog)
    for p in (DB, CATALOG):
        if not p.exists():
            sys.exit(f"missing: {p}")

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    clubs = load_catalog()

    n_players, n_teams, n_members = (con.execute(q).fetchone()[0] for q in (
        "SELECT COUNT(*) FROM players", "SELECT COUNT(*) FROM teams",
        "SELECT COUNT(*) FROM squad_members"))
    print(f"VALIDATION GATE  {DB}")
    print(f"  {n_players:,} players | {n_teams:,} teams | {n_members:,} squad rows | "
          f"{len(clubs):,} catalog clubs (read-only; nothing is ever written)\n")

    gate = Gate(args.max_detail)
    check_dangling(con, gate)
    check_single_membership(con, gate)
    check_attributed(con, gate)
    check_catalog_clubs(con, gate, clubs)      # creates temp cat table used by projection too
    check_squad_duplicates(con, gate)
    check_paths(con, gate, clubs)
    check_namespaces(con, gate)
    check_render_projection(con, gate, clubs)
    check_superseded(con, gate)
    con.close()

    print(f"\n{'GATE PASSED' if gate.failed == 0 else 'GATE FAILED'}: "
          f"{9 - gate.failed}/9 assertions clean")
    return 0 if gate.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
