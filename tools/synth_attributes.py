#!/usr/bin/env python3
"""
synth_attributes.py — give squad players who have NO attributes a full, position-appropriate
eFootball attribute set so they are playable in-game. ~11k FM-sourced players reached a squad with
only an overall_rating + position and no 1-20 FM attributes to translate, so nothing can be
CONVERTED — instead we SYNTHESISE: spread the 26 abilities around the player's overall, high on his
position's core skills and lower off it (a CB defends, can't finish), GK vs outfield split, so the
top-weighted overall formula lands back near his real rating. Deterministic per player (hashed
jitter) — reruns are identical. Only touches players with zero attribute rows; never overwrites.

    python tools/synth_attributes.py --dry
    python tools/synth_attributes.py
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

POSITION_CORE = {
    "GK":  ["gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach", "low_pass"],
    "CB":  ["defensive_awareness", "tackling", "heading", "physical_contact", "jumping", "speed",
            "balance", "low_pass"],
    "LB":  ["defensive_awareness", "tackling", "speed", "acceleration", "stamina", "low_pass",
            "dribbling", "tight_possession", "curl"],
    "RB":  ["defensive_awareness", "tackling", "speed", "acceleration", "stamina", "low_pass",
            "dribbling", "tight_possession", "curl"],
    "DMF": ["defensive_awareness", "tackling", "low_pass", "lofted_pass", "ball_control",
            "physical_contact", "stamina", "offensive_awareness"],
    "CMF": ["low_pass", "lofted_pass", "ball_control", "tight_possession", "offensive_awareness",
            "defensive_awareness", "stamina", "dribbling"],
    "LMF": ["speed", "acceleration", "dribbling", "ball_control", "tight_possession", "low_pass",
            "curl", "stamina", "offensive_awareness"],
    "RMF": ["speed", "acceleration", "dribbling", "ball_control", "tight_possession", "low_pass",
            "curl", "stamina", "offensive_awareness"],
    "AMF": ["offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
            "lofted_pass", "finishing", "curl"],
    "LWF": ["offensive_awareness", "ball_control", "dribbling", "tight_possession", "speed",
            "acceleration", "finishing", "curl"],
    "RWF": ["offensive_awareness", "ball_control", "dribbling", "tight_possession", "speed",
            "acceleration", "finishing", "curl"],
    "CF":  ["offensive_awareness", "finishing", "ball_control", "dribbling", "heading", "speed",
            "acceleration", "physical_contact", "kicking_power"],
    "SS":  ["offensive_awareness", "finishing", "ball_control", "dribbling", "tight_possession",
            "speed", "acceleration", "low_pass"],
}
OUTFIELD_FALLBACK = ["offensive_awareness", "ball_control", "dribbling", "low_pass", "finishing",
                     "speed", "physical_contact", "stamina", "defensive_awareness", "tackling"]

GK_ATTRS = {"gk_awareness", "gk_catching", "gk_parrying", "gk_reach", "gk_reflexes"}
ABILITIES = ["acceleration", "aggression", "balance", "ball_control", "curl", "defensive_awareness",
             "defensive_engagement", "dribbling", "finishing", "gk_awareness", "gk_catching",
             "gk_parrying", "gk_reach", "gk_reflexes", "heading", "jumping", "kicking_power",
             "lofted_pass", "low_pass", "offensive_awareness", "physical_contact",
             "set_piece_taking", "speed", "stamina", "tackling", "tight_possession"]
# a keeper's non-keeper skills that are still respectable (distribution, not shot-stopping)
GK_OK_OUTFIELD = {"low_pass", "lofted_pass", "kicking_power", "balance", "jumping", "stamina",
                  "physical_contact"}


def jit(pid: int, attr: str, lo: int, hi: int) -> int:
    h = int(hashlib.md5(f"{pid}:{attr}".encode()).hexdigest()[:8], 16)
    return lo + h % (hi - lo + 1)


def synth(pid: int, overall: int, pos: str) -> dict[str, int]:
    pos = (pos or "CMF").upper()
    core = set(POSITION_CORE.get(pos, OUTFIELD_FALLBACK))
    is_gk = pos == "GK"
    out: dict[str, int] = {}
    for a in ABILITIES:
        if is_gk:
            if a in core or a in GK_ATTRS:
                v = overall + jit(pid, a, -4, 4)
            elif a in GK_OK_OUTFIELD:
                v = overall - jit(pid, a, 8, 16)
            else:
                v = 38 + jit(pid, a, 0, 12)                 # keepers can't play outfield
        else:
            if a in GK_ATTRS:
                v = 38 + jit(pid, a, 0, 10)                 # outfielders can't keep
            elif a in core:
                v = overall + jit(pid, a, -5, 4)
            else:
                v = overall - jit(pid, a, 8, 18)            # weaker away from his game
        out[a] = max(1, min(99, v))
    # meta attributes on their own small scales (match existing data)
    out["foot"] = 1 if jit(pid, "foot", 0, 9) < 2 else 0    # ~20% left-footed
    out["weak_foot_usage"] = 1 + (1 if jit(pid, "wf", 0, 9) >= 8 else 0)
    out["form"] = 3
    out["injury_resistance"] = 2
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    rows = con.execute(
        "SELECT DISTINCT s.player_id, p.overall_rating, p.position FROM squad_members s "
        "JOIN players p ON p.id=s.player_id "
        "LEFT JOIN player_attributes a ON a.player_id=s.player_id "
        "WHERE a.player_id IS NULL").fetchall()
    todo = [(pid, ovr or 55, pos or "CMF") for pid, ovr, pos in rows]
    print(f"squad players needing synthesised attributes: {len(todo):,}")
    if dry:
        for pid, ovr, pos in todo[:4]:
            ab = synth(pid, ovr, pos)
            got = round(_overall(ab, pos))
            print(f"  {pid} {pos} target≈{ovr} -> synth overall {got} | "
                  f"{ {k: ab[k] for k in list(ab)[:6]} }")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-presynth")
    con.execute("BEGIN")
    n = 0
    for pid, ovr, pos in todo:
        con.executemany("INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                        [(pid, a, v) for a, v in synth(pid, ovr, pos).items()])
        n += 1
    con.commit()
    print(f"synthesised attributes for {n:,} players.")
    return 0


def _overall(ab: dict, pos: str) -> float:
    core = POSITION_CORE.get((pos or "CMF").upper(), OUTFIELD_FALLBACK)
    vals = sorted((ab[k] for k in core), reverse=True)
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    return 0.55 * mean(vals[:3]) + 0.32 * mean(vals[3:6]) + 0.13 * mean(vals[6:] or vals[3:6])


if __name__ == "__main__":
    raise SystemExit(main())
