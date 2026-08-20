#!/usr/bin/env python3
"""
fix_overalls.py — repair the RFS-imported overall ratings in build/master.db.

The bug: rfs_translate read a single byte (OFF_OVERALL) as the player's overall. That byte is
NOT on eFootball's 40-99 scale for every record — lower-league players landed at 88-95 and two
junk placeholder rows (every attribute 95) came in at 116. The per-ability offsets, by
contrast, verify well against known players (Obermair: acceleration 86, avg 68 — a plausible
lower-league winger carrying a nonsense 91 overall).

The fix: recompute overall FROM the abilities, with a linear model calibrated on eFootball's
own 21,570 native players (whose overalls are ground truth from the editor CSV):

    overall ~= a * mean(top-6 relevant abilities) + b     (outfield and GK fitted separately)

Then:
  * every imported player (id > 9,000,000, is_custom=1) gets the recomputed overall
  * any player with an impossible overall (>99) gets recomputed + clamped
  * flat placeholder rows (>=20 identical attributes >=90, on no squad) are deleted outright

A timestamped backup of master.db is taken first. Career squads (players already seeded into
the 800000+ teams) are NOT touched — their overalls came through career_seed's own path.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

GK_ATTRS = {"gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach"}
PID_RFS = 9_000_000   # imported block starts above here


def top6_mean(attrs: dict[str, int], gk: bool) -> float | None:
    rel = [v for k, v in attrs.items() if (k in GK_ATTRS) == gk]
    if gk:  # keepers: the 5 GK abilities + their best physical one
        rel += sorted((v for k, v in attrs.items() if k not in GK_ATTRS), reverse=True)[:1]
    rel.sort(reverse=True)
    return sum(rel[:6]) / min(6, len(rel)) if rel else None


def fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var = sum((x - mx) ** 2 for x in xs)
    a = cov / var if var else 1.0
    return a, my - a * mx


def main() -> int:
    con = sqlite3.connect(DB)
    c = con.cursor()

    backup = REPO / "build" / "backups" / f"master-pre-overall-fix-{int(time.time())}.db"
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(DB, backup)
    print(f"backup: {backup.name}")

    # ---- load every player's attributes in one pass -------------------------------
    attrs: dict[int, dict[str, int]] = {}
    for pid, name, val in c.execute("SELECT player_id, attribute, value FROM player_attributes"):
        attrs.setdefault(pid, {})[name] = val

    # ---- calibrate on eFootball natives ------------------------------------------
    fits: dict[bool, tuple[float, float]] = {}
    for gk in (False, True):
        xs, ys = [], []
        for pid, pos, ovr in c.execute(
                "SELECT id, position, overall_rating FROM players "
                "WHERE is_custom=0 AND overall_rating BETWEEN 45 AND 99 AND id < ?", (PID_RFS,)):
            if (pos == "GK") != gk or pid not in attrs:
                continue
            x = top6_mean(attrs[pid], gk)
            if x:
                xs.append(x)
                ys.append(ovr)
        fits[gk] = fit(xs, ys)
        pred_err = sum(abs(fits[gk][0] * x + fits[gk][1] - y) for x, y in zip(xs, ys)) / len(xs)
        print(f"{'GK' if gk else 'outfield'}: n={len(xs)} a={fits[gk][0]:.3f} b={fits[gk][1]:.1f} "
              f"mean |err|={pred_err:.2f}")

    # ---- delete flat placeholder rows (all attributes identical & >=90, no squad) --
    junk = []
    for pid, a in attrs.items():
        vals = list(a.values())
        if len(vals) >= 20 and len(set(vals)) == 1 and vals[0] >= 90:
            junk.append(pid)
    if junk:
        marks = ",".join("?" * len(junk))
        on_squad = {r[0] for r in c.execute(
            f"SELECT DISTINCT player_id FROM squad_members WHERE player_id IN ({marks})", junk)}
        junk = [p for p in junk if p not in on_squad]
        for pid in junk:
            c.execute("DELETE FROM player_attributes WHERE player_id=?", (pid,))
            c.execute("DELETE FROM players WHERE id=?", (pid,))
        print(f"deleted {len(junk)} flat placeholder row(s): {junk}")

    # ---- recompute: all imported players + anything impossible ---------------------
    fixed = 0
    for pid, pos, ovr, is_custom in c.execute(
            "SELECT id, position, overall_rating, is_custom FROM players").fetchall():
        if pid not in attrs:
            continue
        needs = (is_custom == 1 and pid > PID_RFS) or (ovr is not None and ovr > 99)
        if not needs:
            continue
        gk = pos == "GK"
        x = top6_mean(attrs[pid], gk)
        if x is None:
            continue
        a, b = fits[gk]
        new = max(40, min(99, round(a * x + b)))
        if new != ovr:
            c.execute("UPDATE players SET overall_rating=? WHERE id=?", (new, pid))
            fixed += 1

    con.commit()
    print(f"recomputed {fixed:,} overalls")
    for row in c.execute(
            "SELECT MIN(overall_rating), MAX(overall_rating), ROUND(AVG(overall_rating),1) "
            "FROM players WHERE is_custom=1 AND id > ?", (PID_RFS,)):
        print("imported block now: min/max/avg =", row)
    for row in c.execute("SELECT COUNT(*) FROM players WHERE overall_rating > 99"):
        print("players above 99:", row[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
