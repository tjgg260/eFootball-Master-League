#!/usr/bin/env python3
r"""
derive_strength.py — fit tools/data/strength_coeffs.json, the internal player strength.

A DEVELOPER tool. eFootball's Player.bin stores no overall rating, but the app's simulator, AI
selection, market and valuation all need one number per player. This fits it ourselves: for each
position, the export's overall_rating as a linear function of the 26 abilities (as the game shows
them) plus height, rounded, floored at 40 — the functional form the eFootball Player Editor
documents. The export (Konami data) is only the training target; the coefficients are ours.

It is scored on a HELD-OUT half (every other PID), so the accuracy printed is what the game world
will see, not what the fit memorised. The app never displays this number — the owner's ruling is
stars, not an overall — it only feeds the engine.

Usage
    python tools/derive_strength.py --csv samples/editor-bundled-players.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "data" / "strength_coeffs.json"
ABILITIES = [
    "offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
    "lofted_pass", "finishing", "heading", "set_piece_taking", "curl", "speed", "acceleration",
    "kicking_power", "jumping", "physical_contact", "balance", "stamina", "defensive_awareness",
    "tackling", "aggression", "defensive_engagement", "gk_awareness", "gk_catching", "gk_parrying",
    "gk_reflexes", "gk_reach",
]
FLOOR = 40


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    rows = list(csv.DictReader(io.StringIO(Path(args.csv).read_bytes().decode("utf-8-sig"))))
    # The two placeholder rows (every ability 95, overall 116) are not players; nothing should learn
    # from them. Real overalls top out below 110.
    rows = [r for r in rows if r.get("player_id", "").isdigit() and r.get("overall_rating", "").isdigit()
            and 40 <= int(r["overall_rating"]) <= 110 and r.get("height", "").isdigit()]
    out = {"generated_by": "tools/derive_strength.py", "form": "max(40, round(sum(w*ability) + h*height_cm + c))",
           "abilities": ABILITIES, "positions": {}}
    total_exact = total_n = total_pm1 = 0
    for pos in sorted({r["position"] for r in rows}):
        rs = [r for r in rows if r["position"] == pos]
        X = np.array([[int(r[a]) for a in ABILITIES] + [int(r["height"]), 1] for r in rs], dtype=float)
        y = np.array([int(r["overall_rating"]) for r in rs], dtype=float)
        pid = np.array([int(r["player_id"]) for r in rs])
        train, test = pid % 2 == 0, pid % 2 == 1
        if train.sum() < 60 or test.sum() < 30:
            continue
        coef, *_ = np.linalg.lstsq(X[train], y[train], rcond=None)
        pred = np.maximum(FLOOR, np.floor(X[test] @ coef + 0.5))
        exact = float((pred == y[test]).mean())
        pm1 = float((np.abs(pred - y[test]) <= 1).mean())
        # Refit on everything for the shipped coefficients; the held-out score stays the claim.
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        out["positions"][pos] = {"w": [round(float(c), 5) for c in coef[:-2]],
                                 "height": round(float(coef[-2]), 5), "const": round(float(coef[-1]), 4),
                                 "held_out_exact": round(exact, 4), "held_out_within_1": round(pm1, 4),
                                 "n": len(rs)}
        total_exact += exact * test.sum(); total_pm1 += pm1 * test.sum(); total_n += test.sum()
        print(f"  {pos:4s} n={len(rs):5d}  held-out exact {exact:.3f}  within 1 {pm1:.3f}")
    out["held_out_exact"] = round(total_exact / total_n, 4)
    out["held_out_within_1"] = round(total_pm1 / total_n, 4)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"all positions: held-out exact {out['held_out_exact']:.3f}, within 1 {out['held_out_within_1']:.3f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
