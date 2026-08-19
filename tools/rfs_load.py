#!/usr/bin/env python3
"""
rfs_load.py — load RFS players eFootball DOESN'T have into the master DB.

The rule (user's): never overwrite eFootball's existing players — they carry real faces and
official data. Only ADD the RFS players whose name is NOT already in eFootball, so the master DB
gains the coverage eFootball lacks (lower leagues, etc.) without degrading what's there.

Net-new players get a fresh game_pid from the 9,000,000+ block (below the 2^24 variant boundary),
their eFootball position + overall + translated abilities. They're authored into a CPK only when
a fixture that uses them is compiled — the master DB holds the whole universe; each match compiles
just its two squads.

Creates/updates a file-based master DB (default build/master.db) using ML.Data's schema.
"""
from __future__ import annotations

import sqlite3
import sys
import csv as _csv
import io
import re
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb          # noqa: E402
from rfs_translate import translate   # noqa: E402

PID_BASE = 9_000_000


def _norm(s: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces — 'Grimaldo' == 'grimaldo'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


class NameMatcher:
    """
    Decides whether an RFS player already exists in eFootball. Exact-name matching missed real
    players because RFS stores a short display name ('Grimaldo') while eFootball has the full one
    ('Alejandro Grimaldo'). So we index eFootball by full name AND by (surname, first-initial),
    and an RFS player matches on any of several name forms. We deliberately lean toward MORE
    dedup — skipping a borderline net-new player is cheaper than adding a duplicate of one
    eFootball already ships.
    """

    def __init__(self):
        self.full: set[str] = set()
        self.surname_initial: set[tuple[str, str]] = set()
        self.lone_surname: set[str] = set()
        self.full_surnames: set[str] = set()   # last word of every multi-word eFootball name

    def add_efootball(self, name: str) -> None:
        n = _norm(name)
        if not n:
            return
        self.full.add(n)
        parts = n.split()
        if len(parts) >= 2:
            self.surname_initial.add((parts[-1], parts[0][0]))
            self.full_surnames.add(parts[-1])
        elif parts:
            self.lone_surname.add(parts[0])

    def exists(self, first: str, last: str, full: str) -> bool:
        nf, nl, nfull = _norm(first), _norm(last), _norm(full)
        candidates = {nfull, f"{nf} {nl}".strip()}
        if any(c and c in self.full for c in candidates):
            return True
        if nl:
            if nf and (nl, nf[0]) in self.surname_initial:
                return True
            if nl in self.lone_surname:            # eFootball ships a single-name 'Grimaldo'
                return True
        # RFS single-name display ('Grimaldo') vs eFootball full ('alejandro grimaldo')
        if nfull and " " not in nfull and nfull in self.full_surnames:
            return True
        return False


def build_matcher() -> NameMatcher:
    path = REPO / "samples" / "editor-bundled-players.csv"
    rows = _csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig")))
    m = NameMatcher()
    for r in rows:
        if r["player_name"].strip():
            m.add_efootball(r["player_name"])
    return m


def open_master(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript((REPO / "src" / "ML.Data" / "schema.sql").read_text(encoding="utf-8"))
    return con


# The eFootball ability columns present in the bundled CSV, in schema order.
EF_ABILITIES = [
    "offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
    "lofted_pass", "finishing", "heading", "set_piece_taking", "curl", "speed", "acceleration",
    "kicking_power", "jumping", "physical_contact", "balance", "stamina", "defensive_awareness",
    "tackling", "aggression", "defensive_engagement", "gk_awareness", "gk_catching",
    "gk_parrying", "gk_reflexes", "gk_reach",
]


def load_efootball_base(con: sqlite3.Connection) -> int:
    """
    Load eFootball's own players from the bundled CSV as BASE-referenced records (is_custom=0,
    base_pid = their real PID). These keep their real faces and official data in-game; the master
    DB just tracks them so it holds the complete universe alongside the RFS net-new additions.
    """
    path = REPO / "samples" / "editor-bundled-players.csv"
    rows = _csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig")))
    n = 0
    for r in rows:
        try:
            pid = int(r["player_id"])
        except (ValueError, KeyError):
            continue
        name = r.get("player_name", "").strip()
        if not name:
            continue
        con.execute(
            "INSERT OR IGNORE INTO players(id,game_pid,base_pid,is_custom,name,position,overall_rating) "
            "VALUES(?,?,?,0,?,?,?)",
            (pid, pid, pid, name, r.get("position", ""),
             int(r["overall_rating"]) if r.get("overall_rating", "").isdigit() else None))
        con.executemany(
            "INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
            [(pid, a, int(r[a])) for a in EF_ABILITIES if r.get(a, "").isdigit()])
        n += 1
    return n


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build" / "master.db"
    rfs = RfsDb(Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB")
    matcher = build_matcher()
    con = open_master(db_path)

    con.execute("BEGIN")
    base = load_efootball_base(con)   # eFootball's own players first (base-referenced)
    print(f"eFootball base players loaded: {base:,}")

    t = rfs.tables["players"]
    next_pid = PID_BASE + 1
    added = skipped = 0
    seen: set[str] = set()
    for i in range(t.rows):
        rec = rfs.record("players", i)
        p = translate(rec)
        key = _norm(p["name"])
        if not key:
            continue
        # already in eFootball, a dup within RFS (also add each net-new to the matcher so a
        # later RFS row for the same person is caught too)
        if key in seen or matcher.exists(p["first"], p["last"], p["name"]):
            skipped += 1
            continue
        seen.add(key)
        matcher.add_efootball(p["name"])

        pid = next_pid
        next_pid += 1
        con.execute(
            "INSERT OR IGNORE INTO players(id,game_pid,is_custom,name,position,overall_rating) "
            "VALUES(?,?,1,?,?,?)",
            (pid, pid, p["name"], p["position"], p["overall"]))
        con.executemany(
            "INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
            [(pid, a, v) for a, v in p["abilities"].items()])
        added += 1

    # --- teams (catalog: RFS clubs get a high id + game_team_id block, clear of eFootball's) ---
    tt = rfs.tables["teams"]
    team_pk = 100_000
    game_team = 20_000
    for i in range(tt.rows):
        r = rfs.record("teams", i)
        name = r[36:36 + 32].split(b"\0")[0].decode("utf-8", "replace") or \
            r[4:4 + 24].split(b"\0")[0].decode("utf-8", "replace")
        if not name.strip():
            continue
        con.execute(
            "INSERT OR IGNORE INTO teams(id,game_team_id,is_custom,name) VALUES(?,?,1,?)",
            (team_pk, game_team, name))
        team_pk += 1
        game_team += 1

    # --- competitions -> leagues (high id block, clear of eFootball's) ---
    ct = rfs.tables["competitions"]
    for i in range(ct.rows):
        r = rfs.record("competitions", i)
        name = r[2:2 + 40].split(b"\0")[0].decode("utf-8", "replace")
        if name.strip():
            con.execute("INSERT OR IGNORE INTO leagues(id,name,tier) VALUES(?,?,1)", (100_000 + i, name))

    con.commit()
    counts = {tbl: con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
              for tbl in ("players", "teams", "leagues")}
    print(f"RFS players scanned: {t.rows:,}")
    print(f"  skipped (already in eFootball or dup): {skipped:,}")
    print(f"  ADDED (net-new players): {added:,}")
    print(f"master DB: {counts['players']:,} players, {counts['teams']:,} teams, "
          f"{counts['leagues']:,} competitions -> {db_path}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
