#!/usr/bin/env python3
"""
rfs_translate.py — translate an RFS player row into an eFootball player.

RFS (FIFA-lineage) and eFootball (PES-lineage) measure attributes differently, so there is no
perfect 1:1. The ability offsets below were found empirically: 4,083 players matched by name
across both databases, then every RFS byte correlated against every eFootball ability; each
ability takes its best-correlating RFS byte. Some eFootball abilities share an RFS source
(FIFA's one "dribbling" feeds eFootball's ball_control / dribbling / tight_possession; the GK
sub-stats cluster) — that is the reality of the two rating systems, not a bug.

Overall and position translate cleanly (both are eFootball-native concepts in RFS), so a
translated player has the right rating and slot; the per-ability spread is a best-effort map.
"""
from __future__ import annotations

import struct

# FIFA position code (0-27) -> FIFA position (from the user's rfs18 FIFA_POS)
FIFA_POS = {
    0: "GK", 1: "CB", 2: "RB", 3: "RB", 4: "CB", 5: "CB", 6: "CB", 7: "LB", 8: "LB",
    9: "CDM", 10: "CDM", 11: "CDM", 12: "RM", 13: "CM", 14: "CM", 15: "CM", 16: "LM",
    17: "CAM", 18: "CAM", 19: "CAM", 20: "ST", 21: "ST", 22: "ST", 23: "RW",
    24: "ST", 25: "ST", 26: "ST", 27: "LW",
}

# FIFA position -> eFootball position code
FIFA_TO_EF = {
    "GK": "GK", "CB": "CB", "RB": "RB", "LB": "LB", "CDM": "DMF", "CM": "CMF",
    "RM": "RMF", "LM": "LMF", "CAM": "AMF", "ST": "CF", "RW": "RWF", "LW": "LWF",
}

# eFootball ability -> RFS row byte offset (empirical, cross-DB correlation)
ABILITY_OFFSETS = {
    "offensive_awareness": 189, "ball_control": 174, "dribbling": 174, "tight_possession": 174,
    "low_pass": 192, "lofted_pass": 185, "finishing": 175, "heading": 182, "set_piece_taking": 176,
    "curl": 173, "speed": 195, "acceleration": 167, "kicking_power": 193, "jumping": 198,
    "physical_contact": 198, "balance": 170, "stamina": 171, "defensive_awareness": 194,
    "tackling": 194, "aggression": 197, "defensive_engagement": 183, "gk_awareness": 181,
    "gk_catching": 181, "gk_parrying": 181, "gk_reflexes": 181, "gk_reach": 181,
}

# RFS row byte offsets (verified)
OFF_ID, OFF_FIRST, OFF_LAST, OFF_FULL, OFF_POS, OFF_OVERALL = 0, 4, 28, 76, 148, 196
# characteristics (verified by distribution + known players: Bruno Fernandes PT/179cm/1994 etc.)
OFF_BIRTHYEAR, OFF_NATION, OFF_HEIGHT, OFF_WEIGHT = 100, 104, 105, 106
CURRENT_YEAR = 2026


def _clamp(v: int) -> int:
    return max(40, min(99, v))


def translate(rec: bytes) -> dict:
    """RFS player row bytes -> eFootball player dict."""
    pid = struct.unpack_from("<I", rec, OFF_ID)[0]
    first = rec[OFF_FIRST:OFF_FIRST + 24].split(b"\0")[0].decode("utf-8", "replace")
    last = rec[OFF_LAST:OFF_LAST + 24].split(b"\0")[0].decode("utf-8", "replace")
    full = rec[OFF_FULL:OFF_FULL + 24].split(b"\0")[0].decode("utf-8", "replace") or f"{first} {last}".strip()
    fifa_pos = FIFA_POS.get(rec[OFF_POS], "CM")
    position = FIFA_TO_EF.get(fifa_pos, "CMF")
    overall = _clamp(rec[OFF_OVERALL])

    abilities = {}
    for ability, off in ABILITY_OFFSETS.items():
        abilities[ability] = _clamp(rec[off]) if 0 <= off < len(rec) else 40

    # GK/outfield sanity: don't leave a keeper with 40 finishing dominating, or vice versa —
    # zero out the irrelevant family so the in-game overall reads correctly by position.
    gk = position == "GK"
    for a in ("gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach"):
        if not gk:
            abilities[a] = 40
    if gk:
        for a in ("finishing", "dribbling", "tackling"):
            abilities[a] = min(abilities[a], 50)

    birth_year = struct.unpack_from("<H", rec, OFF_BIRTHYEAR)[0]
    age = CURRENT_YEAR - birth_year if 1950 <= birth_year <= CURRENT_YEAR else None
    height = rec[OFF_HEIGHT] if 140 <= rec[OFF_HEIGHT] <= 215 else None
    weight = rec[OFF_WEIGHT] if 45 <= rec[OFF_WEIGHT] <= 120 else None
    return {
        "rfs_id": pid, "name": full, "first": first, "last": last,
        "position": position, "overall": overall, "abilities": abilities,
        "nation_code": rec[OFF_NATION], "birth_year": birth_year, "age": age,
        "height": height, "weight": weight,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"C:\Users\tjgg2\Downloads\eFootball Master League\tools")
    from rfs_import import RfsDb
    from pathlib import Path
    db = RfsDb(Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB")
    t = db.tables["players"]
    # translate the top few by overall and show the result
    best = sorted(range(t.rows), key=lambda i: db.record("players", i)[OFF_OVERALL], reverse=True)[:6]
    for i in best:
        p = translate(db.record("players", i))
        top5 = sorted(p["abilities"].items(), key=lambda kv: -kv[1])[:5]
        print(f"{p['overall']} {p['position']:<4} {p['name']:<22} "
              + "  ".join(f"{k}={v}" for k, v in top5))
