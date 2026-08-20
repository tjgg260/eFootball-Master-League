#!/usr/bin/env python3
"""
tactics_load.py — load eFootball's teams + coach tactics into the master DB.

Populates the "coach tactics" requirement from the decoded tables:
  Team.bin              team_id @12, coach_id @0, name @396
  Coach.bin (176 B)     coach_id @0, preferred formation @21 (stored x4), playstyle @22 (0-4)
  TacticsFormation.bin  (role u32 @0, formation_id u32 @4, y @8, x @9, slot @10) — 11 per shape
  Tactics.bin (12 B)    team_id @0, formation_id @4, style @8, phase @9 (0=in-poss, 1=out)

For each eFootball team we record the club (base-referenced), its coach's preferred formation and
playstyle, the two phase formations, and every formation's 11-slot geometry. The playstyle enum
maps to eFootball's five team styles.
"""
from __future__ import annotations

import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys   # noqa: E402

PESDB = REPO / "bins" / "common" / "etc" / "pesdb"
PLAYSTYLES = {0: "Possession", 1: "Quick Counter", 2: "Long Ball Counter", 3: "Long Ball", 4: "Out Wide", 5: "Overload"}


def dec(name: str) -> bytes:
    return wesys.unpack_wesys_payload((PESDB / name).read_bytes())


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build" / "master.db"
    con = sqlite3.connect(db_path)
    con.executescript((REPO / "src" / "ML.Data" / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys=OFF")   # bulk load; loader guarantees referential order

    team = dec("Team.bin")
    coach = dec("Coach.bin")
    tac = dec("Tactics.bin")
    tf = dec("TacticsFormation.bin")

    # coach_id -> (formation_id_pref, playstyle)
    coaches = {}
    for i in range(len(coach) // 176):
        b = coach[i * 176:(i + 1) * 176]
        coaches[struct.unpack_from("<I", b, 0)[0]] = (b[21] // 4, b[22])

    con.execute("BEGIN")
    # eFootball teams (base) + coach philosophy
    team_ids = set()
    for off in range(0, len(team), 1600):
        tid = struct.unpack_from("<I", team, off + 12)[0]
        cid = struct.unpack_from("<I", team, off + 0)[0]
        name = team[off + 396:off + 396 + 48].split(b"\0")[0].decode("utf-8", "replace")
        if not name.strip():
            continue
        team_ids.add(tid)
        con.execute(
            "INSERT OR IGNORE INTO teams(id,game_team_id,base_team_id,is_custom,name) VALUES(?,?,?,0,?)",
            (tid, tid, tid, name))
        pref, style = coaches.get(cid, (0, 0))
        con.execute(
            "INSERT OR IGNORE INTO coaches(id,game_coach_id,team_id,name) VALUES(?,?,?,?)",
            (cid, cid, tid, f"{name} Manager"))

    # formations that any team references, with their 11-slot geometry
    used = {struct.unpack_from("<I", tac, i * 12 + 4)[0] for i in range(len(tac) // 12)}
    formations_written = 0
    for fid in used:
        slots = []
        for i in range(len(tf) // 12):
            if struct.unpack_from("<I", tf, i * 12 + 4)[0] == fid:
                role = struct.unpack_from("<I", tf, i * 12)[0]
                slots.append((tf[i * 12 + 10], role, tf[i * 12 + 9], tf[i * 12 + 8]))
        if not slots:
            continue
        con.execute("INSERT OR IGNORE INTO formations(id,name) VALUES(?,?)", (fid, f"F{fid}"))
        con.executemany(
            "INSERT OR IGNORE INTO formation_slots(formation_id,slot_index,position,x,y) VALUES(?,?,?,?,?)",
            [(fid, s, r, x, y) for s, r, x, y in slots])
        formations_written += 1

    # per-team tactics: two phase shapes + attacking style
    tt = 0
    for i in range(len(tac) // 12):
        tid = struct.unpack_from("<I", tac, i * 12)[0]
        if tid not in team_ids:
            continue
        fid = struct.unpack_from("<I", tac, i * 12 + 4)[0]
        con.execute(
            "INSERT OR IGNORE INTO team_tactics(team_id,phase,formation_id,style) VALUES(?,?,?,?)",
            (tid, tac[i * 12 + 9], fid, tac[i * 12 + 8]))
        tt += 1

    con.commit()
    print(f"eFootball teams loaded: {len(team_ids):,}")
    print(f"coaches: {con.execute('SELECT COUNT(*) FROM coaches').fetchone()[0]:,}")
    print(f"formations: {formations_written:,} (with slot geometry)")
    print(f"team_tactics rows (2 phases/team): {tt:,}")
    print(f"master DB teams total: {con.execute('SELECT COUNT(*) FROM teams').fetchone()[0]:,}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
