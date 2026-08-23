#!/usr/bin/env python3
"""
rfs_competitions.py — link RFS teams to their leagues and import competition structure.

Cracked from RFS.DB: the `previuosseason` table is (competition_id u16 @0, team_id 3-byte @2 =
plain teams-table id, position u8 @6) — i.e. last season's full standings for every competition.
The competition_id maps to the competitions table via its id field at offset 54 (name at offset 2).

This gives, per competition: its member teams and their finishing positions. We:
  * re-key leagues by competition_id (id = L_BASE + comp_id) with the real name,
  * set each RFS team's league_id to its primary LEAGUE (the competition it's in with the most
    members — leagues are larger than the domestic cups it also appears in),
  * store the standings (team, position) per competition in a new rfs_standings table.

Writes only master.db. Idempotent.
"""
from __future__ import annotations

import sqlite3
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb   # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
T_BASE = 3_000_000     # must match rfs_full_import
L_BASE = 3_000_000
COMP_ID_OFF = 54       # competition id field in the competitions table
COMP_NAME_OFF = 2


def load():
    db = RfsDb(RFS_DB)
    ct = db.tables["competitions"]
    comp_name = {}
    for i in range(ct.rows):
        r = db.record("competitions", i)
        cid = struct.unpack_from("<H", r, COMP_ID_OFF)[0]
        name = r[COMP_NAME_OFF:COMP_NAME_OFF + 40].split(b"\0")[0].decode("utf-8", "replace").strip()
        if name:
            comp_name[cid] = name

    ps = db.tables["previuosseason"]
    standings = []          # (comp_id, team_id, position)
    for i in range(ps.rows):
        r = db.record("previuosseason", i)
        comp = struct.unpack_from("<H", r, 0)[0]
        team = int.from_bytes(r[2:5], "little")
        pos = r[6]
        if comp in comp_name and 1 <= team <= 200000:
            standings.append((comp, team, pos))
    return comp_name, standings


def main() -> int:
    comp_name, standings = load()
    members = defaultdict(list)          # comp_id -> [team_id]
    for comp, team, pos in standings:
        members[comp].append(team)
    comp_size = {c: len(v) for c, v in members.items()}

    # each team's primary league = the competition it's in with the most members
    team_comps = defaultdict(list)
    for comp, team, pos in standings:
        team_comps[team].append(comp)
    primary = {t: max(cs, key=lambda c: comp_size.get(c, 0)) for t, cs in team_comps.items()}

    con = sqlite3.connect(DB)
    con.execute("BEGIN")
    # re-key RFS leagues by competition id
    con.execute("DELETE FROM leagues WHERE id >= ?", (L_BASE,))
    con.executemany("INSERT OR REPLACE INTO leagues(id,name,tier) VALUES(?,?,1)",
                    [(L_BASE + cid, name) for cid, name in comp_name.items()])
    # link teams to their primary league
    linked = 0
    for team, comp in primary.items():
        cur = con.execute("UPDATE teams SET league_id=? WHERE id=?",
                          (L_BASE + comp, T_BASE + team))
        linked += cur.rowcount
    # standings table (full competition structure snapshot)
    con.execute("CREATE TABLE IF NOT EXISTS rfs_standings "
                "(league_id INTEGER, team_id INTEGER, position INTEGER, "
                "PRIMARY KEY(league_id, team_id))")
    con.execute("DELETE FROM rfs_standings")
    con.executemany("INSERT OR REPLACE INTO rfs_standings(league_id,team_id,position) VALUES(?,?,?)",
                    [(L_BASE + c, T_BASE + t, p) for c, t, p in standings])
    con.commit()

    print("RFS competition structure imported:")
    print(f"  competitions (leagues): {len(comp_name)}")
    print(f"  team->league links set: {linked}")
    print(f"  standings rows:         {len(standings)}")
    # sanity: show a real league with its clubs
    for cid, name in list(comp_name.items()):
        if comp_size.get(cid, 0) >= 18:
            teams = con.execute(
                "SELECT t.name FROM rfs_standings s JOIN teams t ON t.id=s.team_id "
                "WHERE s.league_id=? ORDER BY s.position LIMIT 6", (L_BASE + cid,)).fetchall()
            print(f"    {name}: {comp_size[cid]} clubs -> {[t[0] for t in teams]}")
            break
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
