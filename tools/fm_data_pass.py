#!/usr/bin/env python3
"""
fm_data_pass.py — turn the imported real FM attributes (fm_attributes, 1-20) into eFootball-scale
player_attributes (40-99) for every world-DB player we can map, plus height/weight and a derived
overall. This is what makes FM net-new players stop showing flat-40 radars.

Mapping: each of eFootball's 26 abilities is a weighted blend of the FM attributes that drive it,
then scaled 1-20 -> 40-99. GK abilities come from the FM keeping attributes. The player's overall
is a position-weighted average of the resulting abilities (so it's tied to the real values, not
FM's hidden CA). Height/weight come from the raw export.

Join: FM net-new player id = 10_000_000_000 + uid; overlap (canonical) via real_face_path
`face_<uid>.png`. Idempotent (INSERT OR REPLACE); safe to re-run after each new export.

    python tools/fm_data_pass.py            # convert everything in fm_attributes
    python tools/fm_data_pass.py --dry      # show a few conversions, write nothing
"""
from __future__ import annotations

import argparse
import math
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

# eFootball ability <- weighted FM attributes. Weights are relative within each ability.
EF_FROM_FM = {
    "offensive_awareness": {"off_the_ball": 3, "anticipation": 1},
    "ball_control": {"first_touch": 2, "technique": 2},
    "dribbling": {"dribbling": 3, "agility": 1},
    "tight_possession": {"first_touch": 2, "balance": 1, "technique": 1},
    "low_pass": {"passing": 3, "technique": 1},
    "lofted_pass": {"passing": 2, "vision": 1, "technique": 1},
    "finishing": {"finishing": 3, "composure": 1},
    "heading": {"heading": 4},
    "set_piece_taking": {"free_kick_taking": 2, "corners": 1, "penalty_taking": 1},
    "curl": {"free_kick_taking": 1, "crossing": 2, "technique": 1},
    "speed": {"pace": 4},
    "acceleration": {"acceleration": 4},
    "kicking_power": {"long_shots": 2, "strength": 1},
    "jumping": {"jumping_reach": 4},
    "physical_contact": {"strength": 2, "balance": 1, "aggression": 1},
    "balance": {"balance": 3, "agility": 1},
    "stamina": {"stamina": 3, "natural_fitness": 1},
    "defensive_awareness": {"positioning": 2, "marking": 1, "anticipation": 1},
    "tackling": {"tackling": 4},
    "aggression": {"aggression": 3, "bravery": 1},
    "defensive_engagement": {"work_rate": 2, "tackling": 1, "aggression": 1},
    "gk_awareness": {"command_of_area": 2, "positioning": 1, "decisions": 1},
    "gk_catching": {"handling": 3, "aerial_reach": 1},
    "gk_parrying": {"handling": 2, "one_on_ones": 2},
    "gk_reflexes": {"reflexes": 4},
    "gk_reach": {"aerial_reach": 2, "agility": 1, "command_of_area": 1},
}

# FM Personality label -> the hidden mentals FM *won't* export, recovered from the label it
# derives from them. Tuple = (professionalism, ambition, pressure, loyalty) on FM's 1-20 scale.
# Determination is NOT here — we have the real per-player value in fm_attributes; the label only
# fills in the mentals we can't otherwise see. Grounded in FM's documented label logic and the
# determination averages observed in the export (Model Professional/Perfectionist at the top,
# Spineless/Low Determination at the floor).
PERSONALITY = {
    "Model Citizen":       (18, 16, 16, 18),
    "Model Professional":  (20, 17, 15, 14),
    "Perfectionist":       (19, 18, 14, 12),
    "Professional":        (17, 13, 13, 12),
    "Fairly Professional": (14, 11, 11, 11),
    "Very Ambitious":      (12, 19,  12, 8),
    "Ambitious":           (11, 17, 11,  9),
    "Fairly Ambitious":    (10, 14, 10, 10),
    "Driven":              (13, 17, 13, 10),
    "Mercenary":           (11, 17, 11,  3),
    "Determined":          (12, 12, 13, 11),
    "Fairly Determined":   (10, 10, 10, 10),
    "Resolute":            (11, 11, 14, 11),
    "Resilient":           (11, 11, 16, 11),
    "Spirited":            (11, 11, 14, 12),
    "Leader":              (13, 13, 15, 13),
    "Devoted":             (12,  9, 12, 18),
    "Very Loyal":          (10,  8, 11, 18),
    "Loyal":               (10,  8, 11, 16),
    "Fairly Loyal":        (10,  8, 10, 13),
    "Sporting":            (10,  9, 10, 12),
    "Fairly Sporting":     (10,  9, 10, 11),
    "Honest":              (11,  9, 10, 13),
    "Realist":             (11, 10, 12, 11),
    "Jovial":              ( 9,  9,  9, 11),
    "Light-Hearted":       ( 9,  9,  9, 11),
    "Balanced":            ( 9,  9, 10, 10),
    "Temperamental":       ( 8, 10,  5,  8),
    "Fickle":              ( 7, 10,  8,  5),
    "Low Self Belief":     ( 9,  8,  4, 10),
    "Casual":              ( 5,  6,  8,  9),
    "Unambitious":         ( 8,  4,  9, 11),
    "Low Determination":   ( 7,  7,  8, 10),
    "Spineless":           ( 6,  6,  3,  9),
}
PERSONALITY_DEFAULT = (10, 10, 10, 10)  # unknown label -> neutral


def growth_factor(professionalism: int, ambition: int, determination: int) -> float:
    """Development-speed multiplier from the three mentals that drive growth. Centred on ~1.0 for
    an average pro (all ~10); a Model Professional wonderkid (~19/17/18) pushes ~1.4, a Casual/Low
    Determination player (~5/6/5) drops to ~0.6. The dev engine multiplies base growth by this."""
    drive = (professionalism * 0.45 + determination * 0.40 + ambition * 0.15)
    return round(0.55 + drive / 22.0, 3)


# eFootball's overall is a position-weighted rating dominated by the abilities that matter for
# that role — a striker's overall reflects his finishing/pace/awareness, not his tackling. So we
# take the mean of the position's CORE abilities and blend in a little of the all-round mean, which
# lands specialists where eFootball puts them (elite ~90+) instead of a flat average (~76).
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


def overall_of(ab: dict[str, int], pos: str) -> int:
    """eFootball-style overall — top-weighted so a player's STANDOUT abilities define him, the way
    eFootball inflates elite ratings (Haaland's finishing/pace carry him, his tackling doesn't drag
    him). We rank his position-core abilities and lean hard on the best few: elite land ~90-95, good
    pros ~78-86, and genuinely limited players still fall to the 30s-40s (the spread is preserved)."""
    core = POSITION_CORE.get(pos.upper(), OUTFIELD_FALLBACK)
    vals = sorted((ab[k] for k in core), reverse=True)
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    top, mid, rest = vals[:3], vals[3:6], vals[6:]
    ov = 0.55 * mean(top) + 0.32 * mean(mid) + 0.13 * mean(rest or mid)
    return max(1, min(99, round(ov)))


# FM 1-20 -> eFootball, MEASURED on the 12,339 players present in both the FM exports and
# samples/editor-bundled-players.csv (tools/fm_derive_attributes.py fits this at runtime; this
# table is that fit, frozen). Bins 1-16 are medians over >=1,000 samples each; above 16 the
# calibration data thins to tens of rows and wanders, so the measured slope of 2.0 eF per FM
# point is extrapolated instead.
FM_TO_EF = {1: 40, 2: 40, 3: 40, 4: 40, 5: 42, 6: 51, 7: 55, 8: 57, 9: 60, 10: 60,
            11: 62, 12: 64, 13: 66, 14: 68, 15: 70, 16: 72, 17: 74, 18: 76, 19: 78, 20: 80}


def scale(v: float) -> int:
    """FM 1-20 -> eFootball 40-99.

    40 IS THE FLOOR OF THE FORMAT, not a preference: an ability is a 6-bit field storing
    (value - 40) (tools/ability_bits.py), so nothing below 40 can be represented and Konami's own
    export contains no such value. This function used to map onto 1-99 ("FM 6 -> ~20, properly
    crap") and 57% of every value it produced fell off the bottom of the scale, where a 12, a 25
    and a 39 all arrive in-game as the same 40."""
    lo = max(1, min(20, int(v)))
    hi = min(20, lo + 1)
    f = v - lo
    return max(40, min(99, round(FM_TO_EF[lo] * (1 - f) + FM_TO_EF[hi] * f)))


def abilities_from_fm(fm: dict[str, int]) -> dict[str, int]:
    out = {}
    for ef, srcs in EF_FROM_FM.items():
        num = den = 0
        for k, w in srcs.items():
            if k in fm:
                num += fm[k] * w
                den += w
        out[ef] = scale(num / den) if den else 45
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(DB)

    # uid -> {fm attr: value}
    fm: dict[int, dict] = {}
    for uid, attr, val in con.execute("SELECT uid, attr, value FROM fm_attributes"):
        fm.setdefault(uid, {})[attr] = val
    print(f"fm_attributes: {len(fm):,} players")

    # uid -> master player id: net-new (10e9+uid) OR overlap (face_<uid>.png)
    net = {pid - 10_000_000_000: pid for (pid,) in
           con.execute("SELECT id FROM players WHERE id>=10000000000")}
    overlap = {}
    for pid, face in con.execute("SELECT id, real_face_path FROM players "
                                 "WHERE real_face_path LIKE '%face_%' AND id<10000000000"):
        m = re.search(r"face_(\d+)\.png$", face or "")
        if m:
            overlap[int(m.group(1))] = pid

    # raw per-uid fields (height/weight/position + personality + potential ceiling)
    RAW_COLS = ("Height", "Weight", "Position", "Personality", "Best Pot Rating", "Potential")
    hw = {}
    ph = ",".join("?" * len(RAW_COLS))
    for uid, col, val in con.execute(
            f"SELECT key, col, val FROM fm_raw_players WHERE col IN ({ph})", RAW_COLS):
        if uid.isdigit():
            hw.setdefault(int(uid), {})[col] = val

    pos_of = dict(con.execute("SELECT id, position FROM players"))

    attr_rows, hw_updates, dev_rows, skill_rows = [], [], [], []
    done = 0
    for uid, fmvals in fm.items():
        pid = net.get(uid) or overlap.get(uid)
        if pid is None:
            continue
        ab = abilities_from_fm(fmvals)
        for k, v in ab.items():
            attr_rows.append((pid, k, v))
        # overall (eFootball-style, position-weighted)
        pos = (pos_of.get(pid) or "").upper()
        overall = overall_of(ab, pos)
        # height/weight
        raw = hw.get(uid, {})
        h = _cm(raw.get("Height"))
        w = _kg(raw.get("Weight"))
        hw_updates.append((overall, h, w, pid))
        # development profile fed straight into the engine's tables. Personality label -> the
        # hidden mentals FM won't export (professionalism/ambition/pressure); determination is
        # the real per-player value; potential ceiling from FM's Best Pot Rating.
        label = raw.get("Personality", "") or ""
        pro, amb, prs, loy = PERSONALITY.get(label, PERSONALITY_DEFAULT)
        det = fmvals.get("determination", 10)
        temperament = prs  # engine's 4th trait = steadiness under pressure
        pot_pct = _pct(raw.get("Best Pot Rating") or raw.get("Potential"))
        # Only trust a real FM ceiling; when absent, leave potential unset so the engine seeds it
        # age-aware from the (now real) determination we store below.
        potential = max(overall, min(99, round(pot_pct))) if pot_pct else None
        gf = growth_factor(pro, amb, det)
        # trait row (det, prof, amb, temperament), potential row, personality label
        dev_rows.append((pid, det, pro, amb, temperament, potential, label))
        # in-game Player Skill flags derived from mentals (intent layer; the dt200 Player.bin
        # writer maps these names -> skill bits after verification against all.str)
        for sk in skills_for(fmvals, label):
            skill_rows.append((pid, sk))
        done += 1
        if args.dry and done <= 6:
            nm = con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()
            print(f"  {(nm[0] if nm else pid):<22} OVR {overall} pot {potential} | "
                  f"{label or '-':<18} det{det} pro{pro} amb{amb} gf {gf} | "
                  f"skills {skills_for(fmvals, label) or '-'}")

    print(f"mappable players: {done:,} (net-new {sum(1 for u in fm if u in net):,}, "
          f"overlap {sum(1 for u in fm if u in overlap and u not in net):,})")
    if args.dry:
        return 0

    # players.personality for display (engine also derives one from the traits)
    try:
        con.execute("ALTER TABLE players ADD COLUMN personality TEXT")
    except sqlite3.OperationalError:
        pass

    con.execute("BEGIN")
    pids = list({r[0] for r in dev_rows})
    for i in range(0, len(pids), 900):
        chunk = pids[i:i + 900]
        q = f"({','.join('?' * len(chunk))})"
        con.execute(f"DELETE FROM player_attributes WHERE player_id IN {q}", chunk)
        con.execute(f"DELETE FROM player_skills WHERE player_id IN {q} AND source='fm'", chunk)
    con.executemany("INSERT OR REPLACE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                    attr_rows)
    con.executemany("UPDATE players SET overall_rating=?, height_cm=COALESCE(?,height_cm), "
                    "weight_kg=COALESCE(?,weight_kg) WHERE id=?", hw_updates)
    # real FM traits + potential straight into the engine's own tables
    con.executemany("INSERT OR REPLACE INTO player_traits"
                    "(player_id,determination,professionalism,ambition,temperament) "
                    "VALUES(?,?,?,?,?)", [(r[0], r[1], r[2], r[3], r[4]) for r in dev_rows])
    con.executemany("INSERT OR REPLACE INTO player_potential(player_id,potential) VALUES(?,?)",
                    [(r[0], r[5]) for r in dev_rows if r[5] is not None])
    con.executemany("UPDATE players SET personality=? WHERE id=?",
                    [(r[6], r[0]) for r in dev_rows if r[6]])
    con.executemany("INSERT OR REPLACE INTO player_skills(player_id,skill,source) VALUES(?,?,'fm')",
                    skill_rows)
    con.commit()
    print(f"wrote {len(attr_rows):,} abilities, {len(dev_rows):,} trait+potential rows, "
          f"{len(skill_rows):,} skill flags for {done:,} players.")
    return 0


# behavioural Player Skills eFootball can render, gated on the FM mentals that justify them.
def skills_for(fm: dict, label: str) -> list[str]:
    g = fm.get
    out = []
    if label in ("Leader", "Model Citizen", "Model Professional") or g("determination", 0) >= 18:
        out.append("Captaincy")
    if g("determination", 0) >= 16 or g("bravery", 0) >= 16:
        out.append("Fighting Spirit")
    if g("natural_fitness", 0) >= 16:
        out.append("Injury Resistance")
    if g("marking", 0) >= 16 and g("concentration", 0) >= 14:
        out.append("Man Marking")
    if g("anticipation", 0) >= 16 and g("positioning", 0) >= 14:
        out.append("Interception")
    if g("work_rate", 0) >= 16 and g("teamwork", 0) >= 14:
        out.append("Track Back")
    if g("aggression", 0) >= 17:
        out.append("Gamesmanship")
    return out


def _pct(v):
    if not v:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", v)
    return float(m.group(1)) if m else None


def _cm(v):
    if not v:
        return None
    m = re.search(r"(\d{2,3})", v)
    return int(m.group(1)) if m else None


def _kg(v):
    if not v:
        return None
    m = re.search(r"(\d{2,3})", v)
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    raise SystemExit(main())
