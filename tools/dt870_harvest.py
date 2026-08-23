#!/usr/bin/env python3
"""
dt870_harvest.py — mine dt870 (the live/Dream-Team DB) for REAL players and fold their full data
into master.db, so the app's own database becomes the single source of truth we later author back
into dt200 (the layer proven to render offline).

Why this and not "edit dt870": dt870 is 65% variant/Epic cards ("shiny Salahs" — MESSI x42) and is
almost certainly the online layer; dt200 is what renders offline. So we harvest dt870 as a DATA
SOURCE and keep dt200 as the render target.

Target real-player set:
    real = (all dt200 players)  ∪  (dt870 players with base-style PID < 2^31)
    MINUS the giant-PID (>= 2^31) variant/Epic cards.
We only import players the editor CSV covers (it carries every attribute, skill, both playstyles,
weak foot, form) — that's ~93% of dt870, and needs zero binary reverse-engineering of the
392-byte dt870 layout. Uncovered PIDs are logged for a later binary pass.

Writes ONLY master.db (players, player_attributes, player_skills, player_playstyles). Idempotent:
re-running re-derives each target player's rows. Career/custom players (id >= 800000) are untouched.
"""
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CSV = REPO / "samples" / "editor-bundled-players.csv"
GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk")
VARIANT_PID = 2 ** 31  # PIDs at/above this are Dream-Team special/Epic cards

sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402

# The 26 numeric ability columns, stored verbatim into player_attributes.
ABILITIES = [
    "offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
    "lofted_pass", "finishing", "heading", "set_piece_taking", "curl", "speed", "acceleration",
    "kicking_power", "jumping", "physical_contact", "balance", "stamina", "defensive_awareness",
    "tackling", "aggression", "defensive_engagement", "gk_awareness", "gk_catching", "gk_parrying",
    "gk_reflexes", "gk_reach",
]
# Categorical fields → integer codes (eFootball's own scales).
WEAK_FOOT = {"Rarely": 1, "Occasionally": 2, "Regularly": 3, "Frequently": 4}
FORM = {"Inconsistent": 1, "Unstable": 2, "Standard": 3, "Wavering": 3, "Steady": 4,
        "Consistent": 5, "Unwavering": 6}
INJURY = {"Low": 1, "Medium": 2, "High": 3}
FOOT = {"Right foot": 0, "Left foot": 1}


def player_pids(cpk: Path) -> set[int]:
    """External PID set from a CPK's Player.bin (auto-detects 392/400 stride)."""
    k = _load_cpk(cpk)
    payload = None
    for idx, e in enumerate(k.files):
        fp = (e.full_path or "").replace(chr(92), "/").lower()
        if fp.endswith("common/etc/pesdb/player.bin"):
            payload = wesys.unpack_wesys_payload(k.file_bytes(idx))
            break
    if payload is None:
        raise SystemExit(f"Player.bin not found in {cpk.name}")
    stride = 392 if len(payload) % 392 == 0 else 400
    return {struct.unpack_from("<Q", payload, i * stride + 8)[0]
            for i in range(len(payload) // stride)}


def _load_cpk(path: Path):
    from cricodecs import cpk as C
    return C.load(str(path))


def target_set() -> tuple[set[int], dict]:
    """The real-player PID set to harvest, plus a stats dict."""
    s200 = player_pids(GAME / "dt200_console_all.cpk")
    s870 = player_pids(GAME / "dt870_console_win.cpk")
    new_base = {p for p in (s870 - s200) if p < VARIANT_PID}
    variants = {p for p in (s870 - s200) if p >= VARIANT_PID}
    real = {p for p in (s200 | new_base)}          # keep all dt200 (offline base) + new real
    return real, {
        "dt200": len(s200), "dt870": len(s870),
        "new_real": len(new_base), "variants_excluded": len(variants),
        "real_total": len(real),
    }


def _int(v: str, default=None):
    v = (v or "").strip()
    try:
        return int(v)
    except ValueError:
        return default


def harvest(apply: bool) -> int:
    real, stats = target_set()
    print("Player-set analysis:")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")

    rows = list(csv.DictReader(io.StringIO(CSV.read_bytes().decode("utf-8-sig"))))
    by_pid = {int(r["player_id"]): r for r in rows if r.get("player_id", "").isdigit()}

    targets = sorted(real & set(by_pid))
    missing = sorted(real - set(by_pid))
    print(f"\nReal players covered by CSV: {len(targets)}  (no CSV data for {len(missing)})")
    if not apply:
        print("\n(dry run — pass --apply to write master.db)")
        return 0

    con = sqlite3.connect(DB)
    _ensure_schema(con)
    con.commit()
    cur = con.cursor()

    pl_rows, attr_rows, skill_rows, style_rows = [], [], [], []
    for pid in targets:
        r = by_pid[pid]
        pl_rows.append((pid, pid, pid, 0, r.get("player_name", "").strip(),
                        r.get("player_name", "").strip(), r.get("position", "").strip(),
                        _int(r.get("age")), r.get("nationality", "").strip(),
                        _int(r.get("height")), _int(r.get("weight")),
                        _int(r.get("overall_rating"))))
        for a in ABILITIES:
            val = _int(r.get(a))
            if val is not None:
                attr_rows.append((pid, a, val))
        # categorical → coded numeric, kept in player_attributes so the writeback reads them uniformly
        for name, table, col in (("weak_foot_usage", WEAK_FOOT, "weak_foot_usage"),
                                  ("weak_foot_accuracy", WEAK_FOOT, "weak_foot_accuracy"),
                                  ("form", FORM, "form"), ("injury_resistance", INJURY,
                                  "injury_resistance"), ("foot", FOOT, "foot")):
            code = table.get((r.get(col, "") or "").strip())
            if code is not None:
                attr_rows.append((pid, name, code))
        for kind, col in (("primary", "primary_playing_style"), ("secondary", "secondary_playing_style")):
            s = (r.get(col, "") or "").strip()
            if s:
                style_rows.append((pid, s, kind))
        for sk in (r.get("player_skills", "") or "").split(";"):
            sk = sk.strip()
            if sk:
                skill_rows.append((pid, sk, "csv"))

    # idempotent replace for the target pids only
    chunk = [targets[i:i + 400] for i in range(0, len(targets), 400)]
    for c in chunk:
        q = ",".join("?" * len(c))
        cur.execute(f"DELETE FROM player_attributes WHERE player_id IN ({q})", c)
        cur.execute(f"DELETE FROM player_skills     WHERE player_id IN ({q})", c)
        cur.execute(f"DELETE FROM player_playstyles WHERE player_id IN ({q})", c)
    cur.executemany(
        "INSERT OR REPLACE INTO players "
        "(id,game_pid,base_pid,is_custom,name,short_name,position,age,nationality,"
        "height_cm,weight_kg,overall_rating) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", pl_rows)
    cur.executemany("INSERT INTO player_attributes (player_id,attribute,value) VALUES (?,?,?)", attr_rows)
    cur.executemany("INSERT INTO player_skills (player_id,skill,source) VALUES (?,?,?)", skill_rows)
    cur.executemany("INSERT OR REPLACE INTO player_playstyles (player_id,playstyle,kind) VALUES (?,?,?)", style_rows)
    con.commit()

    print(f"\nWrote: {len(pl_rows)} players, {len(attr_rows)} attributes, "
          f"{len(skill_rows)} skills, {len(style_rows)} playstyle rows.")
    print("  players with skills now:",
          con.execute("SELECT COUNT(DISTINCT player_id) FROM player_skills").fetchone()[0])
    print("  players with 2 playstyles now:",
          con.execute("SELECT COUNT(*) FROM (SELECT player_id FROM player_playstyles "
                      "GROUP BY player_id HAVING COUNT(*)=2)").fetchone()[0])
    con.close()
    return 0


def _ensure_schema(con: sqlite3.Connection) -> None:
    # player_playstyles must key on (player_id, kind) so a player can hold primary AND secondary
    # even when they're the same style. The shipped table keys on (player_id, playstyle) — rebuild.
    ddl = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='player_playstyles'").fetchone()
    needs = not ddl or "kind" not in (ddl[0] or "") or "PRIMARY KEY(player_id, kind)" not in (ddl[0] or "")
    if needs:
        con.execute("DROP TABLE IF EXISTS player_playstyles_new")
        con.execute("CREATE TABLE player_playstyles_new "
                    "(player_id INTEGER, playstyle TEXT, kind TEXT DEFAULT 'primary', "
                    "PRIMARY KEY(player_id, kind))")
        con.execute("INSERT OR IGNORE INTO player_playstyles_new (player_id, playstyle, kind) "
                    "SELECT player_id, playstyle, COALESCE(kind,'primary') FROM player_playstyles")
        con.execute("DROP TABLE player_playstyles")
        con.execute("ALTER TABLE player_playstyles_new RENAME TO player_playstyles")
    con.execute("CREATE INDEX IF NOT EXISTS ix_attr_pid ON player_attributes(player_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_skill_pid ON player_skills(player_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_style_pid ON player_playstyles(player_id)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to master.db (default: dry run)")
    raise SystemExit(harvest(ap.parse_args().apply))
