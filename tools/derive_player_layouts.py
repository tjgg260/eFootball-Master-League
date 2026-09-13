#!/usr/bin/env python3
r"""
derive_player_layouts.py — build tools/data/player_layouts.json, the field map game_world.py reads.

A DEVELOPER tool. It needs the editor's bundled export (samples/editor-bundled-players.csv — Konami
data, never shipped) purely as ground truth: to name raw codes and to score every field. What it
writes is ours: bit offsets, raw-code -> label tables, and the score each one earned.

Where the offsets come from
  400 bytes (dt200, "the cpk the game actually reads"): Sider's PESDB_DATABASE_FORMAT.md §2, the
      repo's own verified maps (ability_bits.py, build/skill_bits.json), and the eFootball Player
      Editor 2.0's core module (efootball_core; exe sha256 09d06ebe…eebc58, read statically, never
      run): the extra 2027 skills, the 7 AI styles, the club fields at bytes 0/4/16, loan end.
  392 bytes (dt870, the live update): only the names are documented upstream. The rest were found
      by matching each field of the SAME player across the two layouts, and are re-scored here.

Three rules this tool proves rather than assumes (all measured on 2026-09-13):
  * ABILITY DISPLAY SCALE. Base cards (PID < 2^32) store abilities scaled x25/24: the value the game
    shows is floor(stored*24/25 + 0.5), floored at 40. Without it only ~20% match the export; with
    it 99.9% do. (The editor documents the rule; the export confirms it.)
  * IN-POSSESSION STYLE = the 8-bit window at bit 372, floored to a multiple of 4. No position key.
  * OUT-OF-POSSESSION STYLE depends on BOTH styles: key (att id, 6-bit def raw at 440).
A field below its threshold is written to "unverified", and game_world.py leaves it empty.

Usage
    python tools/derive_player_layouts.py --csv <export.csv> --dt200 <cpk> --dt870 <cpk> \
        --skill-bits <build/skill_bits.json>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "vendor" / "sider"))
import cpk_patch  # noqa: E402
import pesdb  # noqa: E402  (vendored Sider: the layout detector is upstream's, not ours)
import wesys  # noqa: E402
from ability_bits import ABILITY_BITS  # noqa: E402

OUT = TOOLS / "data" / "player_layouts.json"
VARIANT = 2 ** 31
UNSCALED_FROM = 2 ** 32          # PIDs at or above this store abilities at display scale

# ---------------------------------------------------------------- 400-byte layout (dt200)
L400_SCALARS = {"height_cm": (248, 8, 100), "weight_kg": (280, 7, 30), "age": (536, 6, 10)}
L400_CODES = {"position": (556, 4), "foot": (654, 1), "weak_foot_usage": (478, 2),
              "weak_foot_accuracy": (578, 2), "form": (582, 2), "injury_resistance": (542, 2)}
L400_ATT, L400_DEF = (372, 8), (440, 6)
# eFootball Player Editor 2.0, efootball_core.SKILL_BITS: the skills the export does not carry.
EDITOR_EXTRA_SKILLS = {
    "Low Screamer": 626, "Phenomenal Pass": 637, "Acceleration Burst": 632, "Long-reach Tackle": 351,
    "Aerial Fort": 609, "Fortress": 670, "Tap Trick": 628, "Attacking Surge": 634,
    "Attack Trigger": 624, "GK Spirit Roar": 631, "Shadow Hunt": 656, "Magnetic Feet": 608,
    "Willpower": 627, "Snap Strike": 639,
}
# efootball_core.AI_PLAYING_STYLES
EDITOR_AI_STYLES = {"Trickster": 616, "Mazing Run": 680, "Speeding Bullet": 674, "Incisive Run": 649,
                    "Early Cross": 614, "Long Ranger": 647, "Long Ball Expert": 678}
# efootball_core: YOUTH_CLUB / OWNER_CLUB / CLUB as u32 byte offsets (bit_owner_map claims 0/32/128),
# and LOAN_END as a yyyymmdd field. Club@16 matches the player's club squad for 92.2% of club
# players; owner@4 is non-zero for exactly the 1,129 players with a loan-end date.
U32_FIELDS = {"youth_club": 0, "loan_parent_club": 4, "club": 16}
LOAN_END = (192, 25)

# ---------------------------------------------------------------- 392-byte layout (dt870)
L392_SCALARS = {"height_cm": (248, 8, 100), "weight_kg": (280, 7, 30), "age": (524, 6, None)}
L392_CODES = {"position": (548, 4), "foot": (644, 1), "weak_foot_usage": (510, 2),
              "weak_foot_accuracy": (571, 2), "form": (576, 2), "injury_resistance": (567, 2)}
L392_ABILITIES = {
    "offensive_awareness": 480, "ball_control": 390, "dribbling": 472, "tight_possession": 536,
    "low_pass": 504, "lofted_pass": 518, "finishing": 512, "heading": 396, "set_piece_taking": 368,
    "curl": 454, "speed": 422, "acceleration": 466, "kicking_power": 374, "jumping": 402,
    "physical_contact": 498, "balance": 486, "stamina": 460, "defensive_awareness": 384,
    "tackling": 428, "aggression": 492, "defensive_engagement": 530, "gk_awareness": 448,
    "gk_catching": 408, "gk_parrying": 440, "gk_reflexes": 434, "gk_reach": 416,
}

NAME_OFFSET = {400: 88, 392: 84}
# The five 61-byte name fields are in a different order in each layout (measured 2026-09-13):
#   400: Japanese, Chinese, SHIRT, Full Name, SHIRT      392: Japanese, SHIRT, Chinese, SHIRT, Full Name
NAME_FIELDS = {400: {"full": 3, "shirt": 2}, 392: {"full": 4, "shirt": 1}}
CODE_COLUMNS = {"position": "position", "foot": "foot", "weak_foot_usage": "weak_foot_usage",
                "weak_foot_accuracy": "weak_foot_accuracy", "form": "form",
                "injury_resistance": "injury_resistance"}

MIN_PURITY = 0.95
MIN_AGREE = 0.90
MIN_R = 0.90
MIN_ABILITY_EXACT = 0.95
MIN_SKILL_F1 = 0.95


def load_players(cpk: str) -> tuple[int, dict[int, bytes]]:
    payload = wesys.unpack_wesys_payload(cpk_patch.read(cpk_patch.load(cpk), "common/etc/pesdb/Player.bin"))
    stride, _ = pesdb.detect_player_layout(payload)
    return stride, {struct.unpack_from("<Q", payload, i + 8)[0]: payload[i:i + stride]
                    for i in range(0, len(payload), stride)}


def bits_of(recs: list[bytes], stride: int) -> np.ndarray:
    arr = np.frombuffer(b"".join(recs), np.uint8).reshape(len(recs), stride)
    return np.unpackbits(arr, axis=1, bitorder="little").astype(np.int64)


def field(B: np.ndarray, off: int, width: int) -> np.ndarray:
    return sum(B[:, off + i] << i for i in range(width))


def display(stored: np.ndarray, pids: np.ndarray) -> np.ndarray:
    """What the game shows for a stored 6-bit ability (+40 already added)."""
    scaled = np.maximum(40, np.floor(stored * 24 / 25 + 0.5)).astype(np.int64)
    return np.where(pids >= UNSCALED_FROM, stored, scaled)


def purity(keys, labels):
    ct: dict = defaultdict(Counter)
    for k, lab in zip(keys, labels):
        if lab:
            ct[k][lab] += 1
    n = sum(sum(c.values()) for c in ct.values())
    table = {k: c.most_common(1)[0][0] for k, c in ct.items()}
    return (sum(c.most_common(1)[0][1] for c in ct.values()) / n if n else 0.0), table


def f1(got: np.ndarray, truth: np.ndarray) -> float:
    denom = got.sum() + truth.sum()
    return float(2 * (got & truth).sum() / denom) if denom else 1.0


def listcol(row: dict, col: str) -> set[str]:
    return {s.strip() for s in (row.get(col) or "").split(";") if s.strip()}


def layout_common(B, rows, pids, codes, scalars, abilities, att, dfn):
    """Score everything both layouts share. Returns (layout dict fragment, scores)."""
    lay = {"scalars": {}, "codes": {k: list(v) for k, v in codes.items()}, "tables": {},
           "abilities": dict(abilities),
           "ability_display": {"unscaled_from_pid": UNSCALED_FROM, "num": 24, "den": 25, "floor": 40},
           "styles": {"att": list(att), "def": list(dfn)}}
    scores = {}
    for name, (off, w) in codes.items():
        pur, tbl = purity(field(B, off, w).tolist(), [r[CODE_COLUMNS[name]].strip() for r in rows])
        lay["tables"][name] = {str(k): v for k, v in sorted(tbl.items())}
        scores[name] = {"purity_vs_export": round(pur, 4)}
    for name, (off, w, bias) in scalars.items():
        if bias is None:
            continue
        col = {"height_cm": "height", "weight_kg": "weight", "age": "age"}[name]
        v, t = field(B, off, w) + bias, np.array([int(r[col]) for r in rows])
        lay["scalars"][name] = [off, w, bias]
        scores[name] = {"exact_vs_export": round(float((v == t).mean()), 4)}
    for name, off in abilities.items():
        stored = field(B, off, 6) + 40
        t = np.array([int(r[name]) for r in rows])
        scores[name] = {"exact_raw": round(float((stored == t).mean()), 4),
                        "exact_display": round(float((display(stored, pids) == t).mean()), 4),
                        "r_display": round(float(np.corrcoef(display(stored, pids), t)[0, 1]), 4)}
    att_id = field(B, att[0], att[1]) // 4
    def_raw = field(B, dfn[0], dfn[1])
    p_pur, p_tbl = purity(att_id.tolist(), [r["primary_playing_style"].strip() for r in rows])
    s_pur, s_tbl = purity([f"{a}:{d}" for a, d in zip(att_id.tolist(), def_raw.tolist())],
                          [r["secondary_playing_style"].strip() for r in rows])
    lay["styles"]["att_table"] = {str(k): v for k, v in sorted(p_tbl.items())}
    lay["styles"]["def_table"] = dict(sorted(s_tbl.items()))
    scores["primary_style"] = {"purity_vs_export": round(p_pur, 4), "keys": len(p_tbl)}
    scores["secondary_style"] = {"purity_vs_export": round(s_pur, 4), "keys": len(s_tbl)}
    return lay, scores


def mark_unverified(lay, scores):
    bad = []
    for k, s in scores.items():
        if "purity_vs_export" in s and s["purity_vs_export"] < MIN_PURITY:
            bad.append(k)
        elif "exact_vs_export" in s and s["exact_vs_export"] < MIN_AGREE:
            bad.append(k)
        elif "agree_vs_400" in s and s["agree_vs_400"] < MIN_AGREE:
            bad.append(k)
        elif "r_display" in s and s["r_display"] < MIN_R:
            bad.append(k)
    lay["unverified"] = sorted(set(bad))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--dt200", required=True, help="a 400-byte-layout archive (the Aug 13 vanilla copy)")
    ap.add_argument("--dt870", required=True, help="a 392-byte-layout archive (the live update)")
    ap.add_argument("--skill-bits", required=True, help="the repo's verified 400-layout skill map")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    rows = list(csv.DictReader(io.StringIO(Path(args.csv).read_bytes().decode("utf-8-sig"))))
    CSV = {int(r["player_id"]): r for r in rows if r.get("player_id", "").isdigit()}
    export_skills = set().union(*(listcol(r, "player_skills") for r in rows))
    skill400 = json.loads(Path(args.skill_bits).read_text(encoding="utf-8"))
    for name, bit in EDITOR_EXTRA_SKILLS.items():
        if name in skill400 and skill400[name] != bit:
            sys.exit(f"editor and repo disagree on {name}: {bit} vs {skill400[name]}")
        skill400.setdefault(name, bit)

    s400, R400 = load_players(args.dt200)
    s392, R392 = load_players(args.dt870)
    if (s400, s392) != (400, 392):
        sys.exit(f"expected a 400-byte and a 392-byte archive, got {s400} and {s392}")

    out = {"generated_by": "tools/derive_player_layouts.py",
           "thresholds": {"min_purity": MIN_PURITY, "min_agree_392_vs_400": MIN_AGREE, "min_r": MIN_R,
                          "min_skill_f1": MIN_SKILL_F1},
           "layouts": {}}

    # ================================================================ 400
    p4 = sorted(p for p in R400 if p in CSV and p < VARIANT)
    B4, c4 = bits_of([R400[p] for p in p4], 400), [CSV[p] for p in p4]
    pid4 = np.array(p4, dtype=np.int64)
    lay4, sc4 = layout_common(B4, c4, pid4, L400_CODES, L400_SCALARS, ABILITY_BITS, L400_ATT, L400_DEF)
    lay4.update({"record_size": 400, "name_offset": NAME_OFFSET[400], "name_fields": NAME_FIELDS[400],
                 "u32": dict(U32_FIELDS), "loan_end": list(LOAN_END), "skills": {}, "skill_source": {},
                 "ai_styles": {}})
    for skill, bit in sorted(skill400.items()):
        got = B4[:, bit].astype(bool)
        if skill in export_skills:
            score = f1(got, np.array([skill in listcol(r, "player_skills") for r in c4]))
            sc4[f"skill:{skill}"] = {"f1_vs_export": round(score, 4)}
            if score >= MIN_SKILL_F1:
                lay4["skills"][skill], lay4["skill_source"][skill] = bit, "export-verified"
        else:
            # A 2027 skill the export predates: the editor's claim, found in-game (its AS Hunter tab
            # exists to do exactly this). Kept, and labelled as such.
            sc4[f"skill:{skill}"] = {"holders": int(got.sum()), "source": "editor"}
            lay4["skills"][skill], lay4["skill_source"][skill] = bit, "editor"
    for style, bit in EDITOR_AI_STYLES.items():
        score = f1(B4[:, bit].astype(bool), np.array([style in listcol(r, "ai_playing_styles") for r in c4]))
        sc4[f"ai:{style}"] = {"f1_vs_export": round(score, 4)}
        if score >= MIN_SKILL_F1:
            lay4["ai_styles"][style] = bit
    lay4["scores"] = sc4
    mark_unverified(lay4, sc4)
    out["layouts"]["400"] = lay4

    # ================================================================ 392
    p8 = sorted(p for p in R392 if p in CSV and p < VARIANT)
    B8, c8 = bits_of([R392[p] for p in p8], 392), [CSV[p] for p in p8]
    pid8 = np.array(p8, dtype=np.int64)
    shared = sorted(p for p in set(R392) & set(R400) if p < VARIANT)
    S8, S4 = bits_of([R392[p] for p in shared], 392), bits_of([R400[p] for p in shared], 400)

    # Style offsets: search a small window around the cross-layout position for the best purity.
    best = None
    for a_off in range(180, 196):
        a_id = field(B8, a_off, 8) // 4
        pur, _ = purity(a_id.tolist(), [r["primary_playing_style"].strip() for r in c8])
        if best is None or pur > best[0]:
            best = (pur, a_off)
    att8 = (best[1], 8)
    best = None
    a_id = field(B8, att8[0], 8) // 4
    for d_off in range(432, 450):
        d_raw = field(B8, d_off, 6)
        pur, _ = purity([f"{a}:{d}" for a, d in zip(a_id.tolist(), d_raw.tolist())],
                        [r["secondary_playing_style"].strip() for r in c8])
        if best is None or pur > best[0]:
            best = (pur, d_off)
    def8 = (best[1], 6)

    lay8, sc8 = layout_common(B8, c8, pid8, L392_CODES, L392_SCALARS, L392_ABILITIES, att8, def8)
    lay8.update({"record_size": 392, "name_offset": NAME_OFFSET[392], "name_fields": NAME_FIELDS[392],
                 "skills": {}, "skill_source": {}, "ai_styles": {}})
    for name, (off, w) in L392_CODES.items():
        o4, w4 = L400_CODES[name]
        sc8[name]["raw_agree_vs_400"] = round(float((field(S8, off, w) == field(S4, o4, w4)).mean()), 4)
    for name, (off, w, bias) in L392_SCALARS.items():
        o4, w4, b4 = L400_SCALARS[name]
        raw8, ref = field(S8, off, w), field(S4, o4, w4) + b4
        if bias is None:
            # Age: the archives are different vintages, so the export (dt200's vintage) cannot fix the
            # bias on its own. Take the bias that makes most shared players read the SAME age in both.
            diffs = Counter((ref - raw8).tolist())
            bias = diffs.most_common(1)[0][0]
            sc8[name] = {"bias_chosen": int(bias),
                         "shared_diff_top4": {int(k): int(v) for k, v in diffs.most_common(4)}}
        lay8["scalars"][name] = [off, w, int(bias)]
        sc8.setdefault(name, {})["agree_vs_400"] = round(float(((raw8 + bias) == ref).mean()), 4)
    # Skills and AI styles: for each 400 bit, the 392 bit that best reproduces it on the same players.
    got_all = S8.astype(bool)
    for kind, table, dest in (("skill", skill400, "skills"), ("ai", EDITOR_AI_STYLES, "ai_styles")):
        for name, bit4 in sorted(table.items()):
            ref = S4[:, bit4].astype(bool)
            if not ref.any():
                sc8[f"{kind}:{name}"] = {"f1_vs_400": None, "note": "nobody holds it in dt200"}
                continue
            tp = (got_all & ref[:, None]).sum(0)
            scores = 2 * tp / (got_all.sum(0) + ref.sum() + 1e-9)
            b = int(np.argmax(scores))
            sc8[f"{kind}:{name}"] = {"f1_vs_400": round(float(scores[b]), 4), "bit": b}
            if scores[b] >= MIN_SKILL_F1:
                lay8[dest][name] = b
                if kind == "skill":
                    lay8["skill_source"][name] = "cross-layout"
    lay8["scores"] = sc8
    mark_unverified(lay8, sc8)
    out["layouts"]["392"] = lay8

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    for lay, d in out["layouts"].items():
        print(f"== {lay}-byte layout  (styles: att {d['styles']['att']}, def {d['styles']['def']})")
        for k, v in d["scores"].items():
            if not k.startswith(("skill:", "ai:")):
                print(f"   {k:22s} {v}")
        print(f"   skills kept {len(d['skills'])}; AI styles kept {len(d['ai_styles'])}/7")
        weak = {k: v for k, v in d["scores"].items() if k.startswith(("skill:", "ai:"))
                and isinstance(v.get("f1_vs_export", v.get("f1_vs_400")), float)
                and v.get("f1_vs_export", v.get("f1_vs_400")) < MIN_SKILL_F1}
        if weak:
            print(f"   dropped (F1 below {MIN_SKILL_F1}): {weak}")
        if d["unverified"]:
            print(f"   UNVERIFIED (the reader leaves these empty): {d['unverified']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
