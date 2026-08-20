#!/usr/bin/env python3
"""
update_career_squad.py — set a career club's squad to a hand-supplied real roster (e.g. the latest
2026/27 lists pulled from the web), keeping our DB the source of truth.

Each player is matched to RFS by name for real abilities + face photo; unmatched players (brand new
signings RFS predates) get sensible defaults from the given position. Players are stored in the
21,000,000+ id block so re-running is idempotent.
"""
from __future__ import annotations

import re
import sqlite3
import struct
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb          # noqa: E402
from rfs_translate import translate    # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
RFS_PLAYERS = Path.home() / "OneDrive/Documents/RFS/Players"
EF_CSV = REPO / "samples" / "editor-bundled-players.csv"
PLAYER_BASE = 21_000_000

POS = {"GK": "GK", "DF": "CB", "MF": "CMF", "FW": "CF"}

# eFootball's own attribute set — its ratings take priority over RFS for any player it has.
EF_ABILITIES = [
    "offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
    "lofted_pass", "finishing", "heading", "set_piece_taking", "curl", "speed", "acceleration",
    "kicking_power", "jumping", "physical_contact", "balance", "stamina", "defensive_awareness",
    "tackling", "aggression", "defensive_engagement", "gk_awareness", "gk_catching",
    "gk_parrying", "gk_reflexes", "gk_reach",
]


def load_ef_index():
    """eFootball's own player export keyed by normalised name -> (overall, abilities, bio).
    Priority source; bio carries height/weight/age/nationality for the player card."""
    import csv
    import io
    idx = {}
    rows = csv.DictReader(io.StringIO(EF_CSV.read_bytes().decode("utf-8-sig")))
    for r in rows:
        nm = r.get("player_name", "").strip()
        if not nm or not r.get("overall_rating", "").isdigit():
            continue
        ab = {a: int(r[a]) for a in EF_ABILITIES if r.get(a, "").isdigit()}
        bio = {
            "height": int(r["height"]) if r.get("height", "").isdigit() else None,
            "weight": int(r["weight"]) if r.get("weight", "").isdigit() else None,
            "age": int(r["age"]) if r.get("age", "").isdigit() else None,
            "nationality": r.get("nationality", "").strip() or None,
        }
        entry = (int(r["overall_rating"]), ab, bio)
        idx.setdefault(norm(nm), entry)
        idx.setdefault(norm(nm.split()[-1]), entry)
    return idx

# (shirt, name, position, more-specific eFootball position or None)
LIVERPOOL = [
    (1, "Alisson", "GK", None), (25, "Giorgi Mamardashvili", "GK", None),
    (28, "Freddie Woodman", "GK", None), (41, "Armin Pecsi", "GK", None),
    (2, "Joe Gomez", "DF", "CB"), (4, "Virgil van Dijk", "DF", "CB"),
    (5, "Jeremy Jacquet", "DF", "CB"), (6, "Milos Kerkez", "DF", "LB"),
    (12, "Conor Bradley", "DF", "RB"), (15, "Giovanni Leoni", "DF", "CB"),
    (30, "Jeremie Frimpong", "DF", "RB"), (33, "Ronald Araujo", "DF", "CB"),
    (3, "Wataru Endo", "MF", "DMF"), (8, "Dominik Szoboszlai", "MF", "CMF"),
    (10, "Alexis Mac Allister", "MF", "CMF"), (17, "Curtis Jones", "MF", "CMF"),
    (38, "Ryan Gravenberch", "MF", "DMF"), (42, "Trey Nyoni", "MF", "CMF"),
    (7, "Florian Wirtz", "FW", "AMF"), (9, "Alexander Isak", "FW", "CF"),
    (14, "Federico Chiesa", "FW", "RWF"), (18, "Cody Gakpo", "FW", "LWF"),
    (22, "Hugo Ekitike", "FW", "CF"), (23, "Victor Munoz", "FW", "CF"),
    (73, "Rio Ngumoha", "FW", "LWF"),
]
ARSENAL = [
    (1, "David Raya", "GK", None), (13, "Kepa Arrizabalaga", "GK", None),
    (30, "Illan Meslier", "GK", None), (35, "Tommy Setford", "GK", None),
    (2, "William Saliba", "DF", "CB"), (3, "Cristhian Mosquera", "DF", "CB"),
    (4, "Ben White", "DF", "RB"), (5, "Piero Hincapie", "DF", "CB"),
    (6, "Gabriel", "DF", "CB"), (12, "Jurrien Timber", "DF", "RB"),
    (33, "Riccardo Calafiori", "DF", "LB"), (49, "Myles Lewis-Skelly", "DF", "LB"),
    (36, "Martin Zubimendi", "MF", "DMF"), (41, "Declan Rice", "MF", "CMF"),
    (39, "Bruno Guimaraes", "MF", "CMF"), (8, "Martin Odegaard", "MF", "AMF"),
    (23, "Mikel Merino", "MF", "CMF"), (21, "Fabio Vieira", "MF", "AMF"),
    (7, "Bukayo Saka", "FW", "RWF"), (11, "Gabriel Martinelli", "FW", "LWF"),
    (14, "Viktor Gyokeres", "FW", "CF"), (9, "Gabriel Jesus", "FW", "CF"),
    (10, "Eberechi Eze", "FW", "AMF"), (29, "Kai Havertz", "FW", "CF"),
    (17, "Christos Tzolis", "FW", "LWF"), (20, "Noni Madueke", "FW", "RWF"),
    (24, "Reiss Nelson", "FW", "RWF"),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def build_rfs_index(db: RfsDb):
    pt = db.tables["players"]
    by_name = {}
    for i in range(pt.rows):
        rec = db.record("players", i)
        pid = struct.unpack_from("<I", rec, 0)[0]
        full = rec[76:100].split(b"\0")[0].decode("utf-8", "replace")
        surname = rec[28:52].split(b"\0")[0].decode("utf-8", "replace")
        for key in (norm(full), norm(surname)):
            if key:
                by_name.setdefault(key, (i, pid))
    return by_name


def update(con: sqlite3.Connection, db: RfsDb, by_name, ef_index, team_id: int, squad, next_pid: int) -> int:
    con.execute("DELETE FROM squad_members WHERE team_id=?", (team_id,))
    for slot_ix, (shirt, name, coarse, fine) in enumerate(squad):
        key = norm(name)
        surname_key = norm(name.split()[-1])
        hit = by_name.get(key) or by_name.get(surname_key)          # RFS record (for face photo)
        ef = ef_index.get(key) or ef_index.get(surname_key)          # eFootball record (priority)
        pos = fine or POS[coarse]
        portrait = None
        if hit:                                                      # face photo comes from RFS
            img = RFS_PLAYERS / f"p{hit[1]}.png"
            portrait = str(img) if img.exists() else None
        bio = ef[2] if ef else {}
        if ef:                                                       # eFootball rating/abilities win
            overall, abilities = ef[0], ef[1]
        elif hit:                                                    # else fall back to RFS translation
            p = translate(db.record("players", hit[0]))
            overall, abilities = p["overall"], p["abilities"]
        else:
            overall, abilities = 76, {}
        our = next_pid
        next_pid += 1
        con.execute("DELETE FROM player_attributes WHERE player_id=?", (our,))
        con.execute("INSERT OR REPLACE INTO players(id,game_pid,is_custom,name,position,overall_rating,"
                    "portrait_path,height_cm,weight_kg,age,nationality) VALUES(?,?,1,?,?,?,?,?,?,?,?)",
                    (our, our, name, pos, overall, portrait,
                     bio.get("height"), bio.get("weight"), bio.get("age"), bio.get("nationality")))
        con.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                        [(our, a, v) for a, v in abilities.items()])
        con.execute("INSERT INTO squad_members(team_id,player_id,squad_number,slot) VALUES(?,?,?,?)",
                    (team_id, our, shirt, slot_ix))
    return next_pid


def main() -> int:
    con = sqlite3.connect(REPO / "build" / "master.db")
    con.execute("PRAGMA foreign_keys=OFF")
    db = RfsDb(RFS_DB)
    by_name = build_rfs_index(db)
    ef_index = load_ef_index()

    # Resolve the career team ids for Liverpool + Arsenal by name.
    def team(nm):
        row = con.execute("SELECT id FROM teams WHERE id>=800000 AND name LIKE ?", (f"%{nm}%",)).fetchone()
        return row[0] if row else None

    con.execute("BEGIN")
    con.execute("DELETE FROM players WHERE id>=?", (PLAYER_BASE,))
    con.execute("DELETE FROM player_attributes WHERE player_id>=?", (PLAYER_BASE,))
    try:   # replaced players take their condition rows with them (table absent on old DBs)
        con.execute("DELETE FROM player_condition WHERE player_id>=?", (PLAYER_BASE,))
    except sqlite3.OperationalError:
        pass
    next_pid = PLAYER_BASE + 1
    done = []
    for nm, squad in (("Liverpool", LIVERPOOL), ("Arsenal", ARSENAL)):
        tid = team(nm)
        if tid is None:
            print(f"  {nm}: not in current career (skipped)")
            continue
        next_pid = update(con, db, by_name, ef_index, tid, squad, next_pid)
        matched = con.execute("SELECT COUNT(*) FROM players p JOIN squad_members s ON s.player_id=p.id "
                              "WHERE s.team_id=? AND p.portrait_path IS NOT NULL", (tid,)).fetchone()[0]
        done.append(f"{nm} (team {tid}): {len(squad)} players, {matched} with face photos")
    con.commit()
    for d in done:
        print("  " + d)
    print("Squads updated to 2026/27." if done else "No matching career teams — start a Liverpool or Arsenal career first.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
