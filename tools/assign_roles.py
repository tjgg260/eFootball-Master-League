#!/usr/bin/env python3
"""
assign_roles.py — the AI assigning BOTH playstyles to every player: an in-possession (primary) role
and an out-of-possession (secondary) role, chosen by best attribute-fit from the same catalogs the
Tactics UI uses (ML.Web RoleCatalog / DefCatalog). Writes player_playstyles(player_id,playstyle,kind).

Only fills a role the player doesn't already have, so manual picks in the UI are never overwritten.
Both roles compile into Player.bin on the next match install (play_match.py reads both kinds).

    python tools/assign_roles.py            # every player missing a role
    python tools/assign_roles.py --team 800000   # just one club's squad
    python tools/assign_roles.py --reassign      # overwrite even existing roles
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

# In-possession roles: (name, compatible positions, the 3 attributes that define fit) — mirrors
# ML.Web Pages/Tactics.razor.cs RoleCatalog exactly.
PRIMARY = [
    ("Goal Poacher", ["CF"], ["offensive_awareness", "finishing", "acceleration"]),
    ("Dummy Runner", ["CF", "SS", "AMF"], ["offensive_awareness", "speed", "balance"]),
    ("Fox in the Box", ["CF"], ["finishing", "offensive_awareness", "jumping"]),
    ("Target Man", ["CF"], ["heading", "physical_contact", "ball_control"]),
    ("Deep-Lying Forward", ["CF", "SS"], ["ball_control", "low_pass", "finishing"]),
    ("Creative Playmaker", ["SS", "RWF", "LWF", "AMF", "RMF", "LMF"], ["low_pass", "dribbling", "offensive_awareness"]),
    ("Prolific Winger", ["RWF", "LWF"], ["finishing", "speed", "dribbling"]),
    ("Roaming Flank", ["RWF", "LWF", "RMF", "LMF"], ["dribbling", "speed", "ball_control"]),
    ("Cross Specialist", ["RWF", "LWF", "RMF", "LMF", "RB", "LB"], ["lofted_pass", "curl", "speed"]),
    ("Classic No. 10", ["SS", "AMF"], ["low_pass", "ball_control", "tight_possession"]),
    ("Hole Player", ["SS", "AMF", "RMF", "LMF", "CMF"], ["offensive_awareness", "finishing", "stamina"]),
    ("Box-to-Box", ["RMF", "LMF", "CMF", "DMF"], ["stamina", "physical_contact", "ball_control"]),
    ("Anchor Man", ["DMF"], ["defensive_awareness", "tackling", "defensive_engagement"]),
    ("Orchestrator", ["CMF", "DMF"], ["low_pass", "lofted_pass", "offensive_awareness"]),
    ("Build Up", ["CB"], ["low_pass", "lofted_pass", "ball_control"]),
    ("Extra Frontman", ["CB"], ["heading", "physical_contact", "finishing"]),
    ("Attacking Full-back", ["RB", "LB"], ["speed", "stamina", "lofted_pass"]),
    ("Defensive Full-back", ["RB", "LB"], ["defensive_awareness", "tackling", "stamina"]),
    ("Full-back Finisher", ["RB", "LB"], ["speed", "finishing", "stamina"]),
    ("Offensive Goalkeeper", ["GK"], ["gk_awareness", "low_pass", "gk_reach"]),
    ("Defensive Goalkeeper", ["GK"], ["gk_reflexes", "gk_catching", "gk_parrying"]),
]

# Out-of-possession roles: ML.Web DefCatalog positions + the attributes that justify each.
SECONDARY = [
    ("The Destroyer", ["CB", "DMF"], ["tackling", "aggression", "defensive_engagement"]),
    ("Press Back", ["AMF", "RMF", "LMF", "SS", "CF", "RWF", "LWF"], ["stamina", "defensive_engagement", "aggression"]),
    ("Front Line Pressure", ["CF", "SS", "RWF", "LWF"], ["defensive_engagement", "stamina", "aggression"]),
    ("Front Line Poacher", ["CF", "SS"], ["offensive_awareness", "finishing", "acceleration"]),
    ("Attack Outlet", ["CF", "SS", "RWF", "LWF"], ["speed", "ball_control", "offensive_awareness"]),
    ("All-action Defender", ["CB", "RB", "LB"], ["stamina", "tackling", "defensive_awareness"]),
    ("Pass Disruptor", ["DMF", "CMF"], ["defensive_awareness", "low_pass", "tackling"]),
    ("Covering Role", ["CB", "RB", "LB"], ["defensive_awareness", "speed", "balance"]),
    ("High Line Master", ["CB"], ["speed", "defensive_awareness", "acceleration"]),
    ("Tough Marker", ["CB", "RB", "LB", "DMF"], ["physical_contact", "tackling", "defensive_awareness"]),
    ("Deep Defender", ["CB"], ["defensive_awareness", "tackling", "heading"]),
    ("Sweeper GK", ["GK"], ["gk_reach", "low_pass", "speed"]),
    ("Build-up GK", ["GK"], ["low_pass", "lofted_pass", "gk_reach"]),
    ("Attacking GK", ["GK"], ["gk_reach", "low_pass", "gk_awareness"]),
    ("Defensive GK", ["GK"], ["gk_reflexes", "gk_catching", "gk_parrying"]),
]


def best_role(catalog, pos: str, ab: dict[str, int]) -> str | None:
    best, best_score = None, -1.0
    for name, positions, needs in catalog:
        if pos not in positions:
            continue
        score = sum(ab.get(k, 0) for k in needs) / len(needs)
        if score > best_score:
            best, best_score = name, score
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", type=int)
    ap.add_argument("--reassign", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    where, params = "position IS NOT NULL AND position<>''", []
    if args.team:
        where += " AND id IN (SELECT player_id FROM squad_members WHERE team_id=?)"
        params.append(args.team)
    players = {pid: pos for pid, pos in
               con.execute(f"SELECT id, position FROM players WHERE {where}", params)}

    ab: dict[int, dict] = {}
    for pid, attr, val in con.execute("SELECT player_id, attribute, value FROM player_attributes"):
        if pid in players:
            ab.setdefault(pid, {})[attr] = val

    have = {}   # pid -> set of kinds already set
    for pid, kind in con.execute("SELECT player_id, kind FROM player_playstyles"):
        have.setdefault(pid, set()).add(kind)

    rows, prim, sec = [], 0, 0
    for pid, pos in players.items():
        a = ab.get(pid, {})
        kinds = have.get(pid, set())
        if args.reassign or "primary" not in kinds:
            r = best_role(PRIMARY, pos.upper(), a)
            if r: rows.append((pid, r, "primary")); prim += 1
        if args.reassign or "secondary" not in kinds:
            r = best_role(SECONDARY, pos.upper(), a)
            if r: rows.append((pid, r, "secondary")); sec += 1

    con.execute("BEGIN")
    if args.reassign:
        con.executemany("DELETE FROM player_playstyles WHERE player_id=? AND kind=?",
                        [(r[0], r[2]) for r in rows])
    con.executemany("INSERT OR IGNORE INTO player_playstyles(player_id,playstyle,kind) VALUES(?,?,?)", rows)
    con.commit()
    print(f"assigned {prim:,} in-possession + {sec:,} out-of-possession roles "
          f"across {len(players):,} players.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
