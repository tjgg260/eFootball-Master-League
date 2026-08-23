#!/usr/bin/env python3
"""
rfs_full_import.py — import the ENTIRE RFS.DB world into master.db.

Unlike rfs_load.py (which added only the deduped subset of players eFootball lacked, and no squads
or managers), this imports RFS in full and self-consistently: every player, every team with its
REAL squad (teamplayerlinks), every competition, every manager. RFS ids are preserved via fixed
base offsets so the squad links resolve exactly.

master.db is the unbounded world; eFootball is only the per-match render target (any player is
rendered by cloning a donor at kickoff — see dt200_grow.py), so there is no size limit here.

Id blocks (chosen clear of eFootball base <16.7M, career 800k+, and giant variant PIDs):
    players  700,000,000 + rfs_player_id     (rfs ids 18k..507k)
    teams      3,000,000 + rfs_team_id       (rfs ids 1..131k)
    leagues    3,000,000 + row_index
    managers -> new table rfs_managers, id = row_index+1

Idempotent: clears its own id blocks (and the old rfs_load blocks) before importing. Writes only
master.db. Back up first (caller does).
"""
from __future__ import annotations

import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb            # noqa: E402
from rfs_translate import translate     # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
P_BASE = 700_000_000
T_BASE = 3_000_000
L_BASE = 3_000_000


def _str(rec: bytes, off: int, length: int) -> str:
    return rec[off:off + length].split(b"\0")[0].decode("utf-8", "replace").strip()


def clear_prior(con: sqlite3.Connection) -> None:
    """Remove the old partial rfs_load rows and this tool's own blocks, so re-runs are clean."""
    # old rfs_load: teams 100000-199999, players 9,000,000-9,999,999, leagues 100000-100999
    old_players = [P_BASE, "players", 0]
    con.execute("DELETE FROM player_attributes WHERE player_id BETWEEN 9000000 AND 9999999 "
                "OR player_id >= ?", (P_BASE,))
    for tbl in ("player_skills", "player_playstyles", "player_appearance", "player_appearance_raw"):
        try:
            con.execute(f"DELETE FROM {tbl} WHERE player_id BETWEEN 9000000 AND 9999999 "
                        f"OR player_id >= ?", (P_BASE,))
        except sqlite3.OperationalError:
            pass
    con.execute("DELETE FROM players WHERE id BETWEEN 9000000 AND 9999999 OR id >= ?", (P_BASE,))
    con.execute("DELETE FROM squad_members WHERE team_id BETWEEN 100000 AND 199999 OR team_id >= ?",
                (T_BASE,))
    con.execute("DELETE FROM teams   WHERE id BETWEEN 100000 AND 199999 OR id >= ?", (T_BASE,))
    con.execute("DELETE FROM leagues WHERE id BETWEEN 100000 AND 100999 OR id >= ?", (L_BASE,))
    con.execute("CREATE TABLE IF NOT EXISTS rfs_managers "
                "(id INTEGER PRIMARY KEY, name TEXT, nationality TEXT)")
    con.execute("DELETE FROM rfs_managers")


def _country_map(db) -> dict:
    """RFS country id (byte0) -> country name (name starts at offset 1)."""
    ct = db.tables.get("countries")
    out = {}
    if ct:
        for i in range(ct.rows):
            r = db.record("countries", i)
            out[r[0]] = r[1:1 + 40].split(b"\0")[0].decode("utf-8", "replace").strip()
    return out


def import_players(con, db) -> int:
    t = db.tables["players"]
    countries = _country_map(db)
    prows, arows = [], []
    ok = 0
    for i in range(t.rows):
        rec = db.record("players", i)
        try:
            p = translate(rec)
        except Exception:
            continue
        rid = p.get("rfs_id") or struct.unpack_from("<I", rec, 0)[0]
        pid = P_BASE + rid
        nation = countries.get(p.get("nation_code"))
        prows.append((pid, pid, 1, p["name"], p.get("position", ""), p.get("overall"),
                      nation, p.get("age"), p.get("height"), p.get("weight")))
        for a, v in (p.get("abilities") or {}).items():
            arows.append((pid, a, v))
        ok += 1
    # full characteristics: nationality, age, height, weight (RFS players only; eFootball rows untouched)
    con.executemany("INSERT OR REPLACE INTO players"
                    "(id,game_pid,is_custom,name,position,overall_rating,nationality,age,height_cm,weight_kg) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)", prows)
    con.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)", arows)
    return ok


def import_teams(con, db) -> tuple[int, set[int]]:
    t = db.tables["teams"]
    rows, ids = [], set()
    for i in range(t.rows):
        r = db.record("teams", i)
        rid = struct.unpack_from("<I", r, 0)[0]
        full = _str(r, 36, 32) or _str(r, 4, 32)
        short = _str(r, 4, 32) or full
        if not full:
            continue
        tid = T_BASE + rid
        rows.append((tid, tid, 1, full, short[:12]))
        ids.add(rid)
    con.executemany("INSERT OR REPLACE INTO teams(id,game_team_id,is_custom,name,short_name) "
                    "VALUES(?,?,?,?,?)", rows)
    return len(rows), ids


def import_squads(con, db, team_ids: set[int], player_ids: set[int]) -> int:
    t = db.tables["teamplayerlinks"]
    per_team: dict[int, int] = {}
    rows = []
    for i in range(t.rows):
        r = db.record("teamplayerlinks", i)
        rt = struct.unpack_from("<I", r, 0)[0]
        rp = struct.unpack_from("<I", r, 4)[0]
        order = r[8] if len(r) > 8 else 0
        if rt not in team_ids or rp not in player_ids:
            continue
        slot = per_team.get(rt, 0)
        per_team[rt] = slot + 1
        shirt = order if 1 <= order <= 99 else slot + 1
        rows.append((T_BASE + rt, P_BASE + rp, shirt, slot, 0))
    con.executemany("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot,role) "
                    "VALUES(?,?,?,?,?)", rows)
    return len(rows)


def import_competitions(con, db) -> int:
    t = db.tables["competitions"]
    rows = []
    for i in range(t.rows):
        name = _str(db.record("competitions", i), 2, 40)
        if name:
            rows.append((L_BASE + i, name, 1))
    con.executemany("INSERT OR REPLACE INTO leagues(id,name,tier) VALUES(?,?,?)", rows)
    return len(rows)


def import_managers(con, db) -> int:
    t = db.tables["managers"]
    rows = []
    for i in range(t.rows):
        name = _str(db.record("managers", i), 2, 40)
        if name:
            rows.append((i + 1, name, None))
    con.executemany("INSERT OR REPLACE INTO rfs_managers(id,name,nationality) VALUES(?,?,?)", rows)
    return len(rows)


def main() -> int:
    if not RFS_DB.exists():
        sys.exit(f"RFS.DB not found at {RFS_DB}")
    db = RfsDb(RFS_DB)
    con = sqlite3.connect(DB)
    con.execute("BEGIN")
    clear_prior(con)

    np = import_players(con, db)
    nt, team_ids = import_teams(con, db)
    player_ids = {struct.unpack_from("<I", db.record("players", i), 0)[0]
                  for i in range(db.tables["players"].rows)}
    ns = import_squads(con, db, team_ids, player_ids)
    nc = import_competitions(con, db)
    nm = import_managers(con, db)
    con.commit()

    print("RFS full import complete:")
    print(f"  players     {np:>7,}")
    print(f"  teams       {nt:>7,}")
    print(f"  squad links {ns:>7,}")
    print(f"  competitions{nc:>7,}")
    print(f"  managers    {nm:>7,}")
    # sanity: a couple of real squads
    for tid, name in con.execute(
            "SELECT id,name FROM teams WHERE id>=? ORDER BY id LIMIT 2", (T_BASE,)):
        n = con.execute("SELECT COUNT(*) FROM squad_members WHERE team_id=?", (tid,)).fetchone()[0]
        print(f"    {name}: {n} players")
    print(f"  DB totals: players {con.execute('SELECT COUNT(*) FROM players').fetchone()[0]:,}, "
          f"teams {con.execute('SELECT COUNT(*) FROM teams').fetchone()[0]:,}, "
          f"leagues {con.execute('SELECT COUNT(*) FROM leagues').fetchone()[0]:,}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
