#!/usr/bin/env python3
"""
fix_market_values.py — every player gets a REAL transfer value, and "not for sale" becomes an
explicit status instead of a junk £300M price.

What FM gave us stays untouched (genuine values). Repaired/derived:
  - value = 0 / NULL           -> computed (the export writes 0 for youth/obscure players)
  - value = £300,000,000 exact -> computed, and transfer_status = 'not-for-sale' (that cap IS
                                  FM's not-for-sale flag — all 4,826 rows had NULL status)
  - squad players with NO market row at all -> row inserted with computed value
  - wage = 0 / NULL            -> derived from value (~0.3%% weekly, floor £200)
  - status normalised: 'not-for-sale' | 'listed' (FM 'Transfer Listed By Club') |
                       'loan-listed' (FM 'Listed For Loan') | NULL = open to offers

Valuation model (calibrated to the real market curve):
  base   £1M at overall 60, doubling roughly every 4.3 points  (90 -> ~£120M, 80 -> ~£25M,
         70 -> ~£5M, 50 -> ~£200k, 40 -> ~£40k)
  age    peak 24-27 (x1.3), youth slightly under peak, steep decline past 30 (36+ x0.1)
  youth  age<=23 with potential above current ability: +4%% per point of headroom (cap x2)
  role   forwards x1.15, wide/attacking mids x1.1, defenders x0.9, keepers x0.75
  rounded to money-like figures (£25k / £100k / £500k steps by magnitude)

    python tools/fix_market_values.py --dry
    python tools/fix_market_values.py
"""
from __future__ import annotations

import math
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

CAP = 300_000_000
AGE_MULT = [(18, 1.15), (21, 1.2), (23, 1.25), (27, 1.3), (29, 1.0), (31, 0.65),
            (33, 0.4), (35, 0.22), (99, 0.1)]
POS_MULT = {"CF": 1.15, "SS": 1.15, "LWF": 1.1, "RWF": 1.1, "AMF": 1.1,
            "LMF": 1.0, "RMF": 1.0, "CMF": 1.0, "DMF": 0.95,
            "CB": 0.9, "LB": 0.9, "RB": 0.9, "GK": 0.75}


def age_mult(age: int | None) -> float:
    a = age if age is not None else 26
    for hi, m in AGE_MULT:
        if a <= hi:
            return m
    return 0.1


def pretty(v: float) -> int:
    v = max(5_000, v)
    step = 5_000 if v < 100_000 else 25_000 if v < 1_000_000 else \
        100_000 if v < 10_000_000 else 500_000
    return int(round(v / step) * step)


def value_of(ovr: int, age: int | None, pos: str | None, pot: int | None) -> int:
    v = 1_000_000 * math.exp(0.16 * ((ovr or 55) - 60))
    v *= age_mult(age)
    if age is not None and age <= 23 and pot and ovr and pot > ovr:
        v *= min(2.0, 1 + 0.04 * (pot - ovr))
    v *= POS_MULT.get((pos or "").upper(), 1.0)
    return pretty(v)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    pot = dict(con.execute("SELECT player_id, potential FROM player_potential"))
    players = {pid: (ovr or 55, age, ppos) for pid, ovr, age, ppos in con.execute(
        "SELECT id, overall_rating, age, position FROM players")}

    fixes, nfs, inserts = [], [], []
    for pid, val, status in con.execute(
            "SELECT player_id, value, transfer_status FROM player_market"):
        if pid not in players:
            continue
        ovr, age, ppos = players[pid]
        if val == CAP:
            nfs.append(pid)
            fixes.append((value_of(ovr, age, ppos, pot.get(pid)), pid))
        elif not val:
            fixes.append((value_of(ovr, age, ppos, pot.get(pid)), pid))
    have = {r[0] for r in con.execute("SELECT player_id FROM player_market")}
    for (pid,) in con.execute("SELECT DISTINCT player_id FROM squad_members"):
        if pid not in have and pid in players:
            ovr, age, ppos = players[pid]
            inserts.append((pid, value_of(ovr, age, ppos, pot.get(pid))))

    print(f"values computed for zero/NULL rows : {len(fixes) - len(nfs):,}")
    print(f"£300M cap -> real value + not-for-sale flag : {len(nfs):,}")
    print(f"market rows inserted for squad players lacking one : {len(inserts):,}")
    if dry:
        import random
        random.seed(1)
        for v, pid in random.sample(fixes, 6):
            nm = con.execute("SELECT name, overall_rating, age FROM players WHERE id=?", (pid,)).fetchone()
            print(f"  {nm[0]} (ovr {nm[1]}, age {nm[2]}) -> £{v:,}")
        for pid in nfs[:4]:
            nm = con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()[0]
            v = next(v for v, p in fixes if p == pid)
            print(f"  NOT FOR SALE: {nm} -> £{v:,}")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-premarket")
    con.execute("BEGIN")
    con.executemany("UPDATE player_market SET value=? WHERE player_id=?", fixes)
    con.executemany("UPDATE player_market SET transfer_status='not-for-sale' WHERE player_id=?",
                    [(p,) for p in nfs])
    con.execute("UPDATE player_market SET transfer_status='listed' "
                "WHERE transfer_status='Transfer Listed By Club'")
    con.execute("UPDATE player_market SET transfer_status='loan-listed' "
                "WHERE transfer_status='Listed For Loan'")
    con.executemany(
        "INSERT INTO player_market(player_id, value, sale_value, wage, contract_end, contract_type,"
        " joined_club, min_fee, relegation_fee, non_promo_fee, squad_status, perceived_status,"
        " transfer_status, squad_rep, int_caps, int_goals) "
        "VALUES(?,?,NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)", inserts)
    # wages: ~0.3% of value weekly, floor £200 — only where FM gave none
    con.execute("UPDATE player_market SET wage=MAX(200, CAST(value*0.003/100 AS INT)*100) "
                "WHERE (wage IS NULL OR wage=0) AND value>0")
    con.commit()
    z = con.execute("SELECT COUNT(*) FROM player_market WHERE value=0 OR value IS NULL").fetchone()[0]
    c = con.execute("SELECT COUNT(*) FROM player_market WHERE value=?", (CAP,)).fetchone()[0]
    s = dict(con.execute("SELECT COALESCE(transfer_status,'open'), COUNT(*) FROM player_market "
                         "GROUP BY transfer_status"))
    print(f"done. remaining zero-values: {z} | remaining £300M: {c} | statuses: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
