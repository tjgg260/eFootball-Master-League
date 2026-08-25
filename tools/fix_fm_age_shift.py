#!/usr/bin/env python3
"""
fix_fm_age_shift.py — every date of birth in the FM export is exactly three years early.

Not an estimate. Day and month are right and the year is short by three, in every case checked:

    Saka        FM 05.09.1998   really 2001-09-05
    Haaland     FM 21.07.1997   really 2000-07-21
    Bellingham  FM 29.06.2000   really 2003-06-29
    Odegaard    FM 17.12.1995   really 1998-12-17

The database already knew. For the 14,367 players who also exist in eFootball, our age sits three
below the FM date of birth (12,758 of them exactly), and RFS agrees; only the FM-band records —
players who exist in no other source, so nothing contradicted the import — took the date at face
value. 270,219 of them are three years too old, which is why the world holds 18,841 players in
their forties and only 2,521 teenagers.

Correct the ones that were derived from the shifted date: FM-band record, an FM date of birth on
file, and a stored age that still equals what that date implies. Records already carrying a
different age were sourced elsewhere and are left alone, which also makes this safe to re-run —
after the fix the age no longer matches the date, so nothing is subtracted twice.

fm_bio.dob is a faithful copy of the export and stays as it is; the shift is recorded in CLAUDE.md
so nothing else derives an age from it.

    python tools/fix_fm_age_shift.py --dry
    python tools/fix_fm_age_shift.py
then: validate_db.py
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
SHIFT = 3
SEASON = 2026
FM_LO, FM_HI = 10_000_000_000, 13_000_000_000
RFS_LO, RFS_HI = 700_000_000, 10_000_000_000
MIN_AGE = 15


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    dob_age = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            d = (r.get("Date Of Birth") or "").strip()
            if u.isdigit() and len(d) >= 4 and d[-4:].isdigit():
                dob_age[int(u)] = SEASON - int(d[-4:])

    fix, floor, rfs = [], 0, 0
    for pid, age, uid in con.execute(
            "SELECT p.id, p.age, pi.fm_uid FROM players p JOIN player_identity pi "
            "ON pi.player_id=p.id WHERE pi.fm_uid IS NOT NULL AND p.age IS NOT NULL "
            "AND p.id>=? AND p.id<?", (FM_LO, FM_HI)):
        fa = dob_age.get(uid)
        if fa is None or age != fa:
            continue
        new = age - SHIFT
        if new < MIN_AGE:
            floor += 1
            continue
        fix.append((new, pid))

    # RFS ages are the source's own guesses and RFS is last priority, so where FM knows the
    # player, its (unshifted) date decides. Al-Quwa Al-Jawiya really does field two Mohammed
    # Salehs — an attacker born 1995 and a keeper born 1994 — and RFS had the attacker a year old
    # too many, which read as one man listed twice.
    for pid, age, uid in con.execute(
            "SELECT p.id, p.age, pi.fm_uid FROM players p JOIN player_identity pi "
            "ON pi.player_id=p.id WHERE pi.fm_uid IS NOT NULL AND p.age IS NOT NULL "
            "AND p.id>=? AND p.id<? AND p.superseded_by IS NULL", (RFS_LO, RFS_HI)):
        fa = dob_age.get(uid)
        if fa is None:
            continue
        want = fa - SHIFT
        if want >= MIN_AGE and want != age:
            fix.append((want, pid))
            rfs += 1

    print(f"FM-band players whose age came from the shifted date of birth: {len(fix) - rfs:,} "
          f"(too young to shift, left alone: {floor}) | RFS ages FM can date properly: {rfs:,}")
    before = Counter(a // 5 * 5 for (a,) in con.execute(
        "SELECT age FROM players WHERE id>=? AND id<? AND superseded_by IS NULL AND age IS NOT NULL",
        (FM_LO, FM_HI)))
    after = Counter(before)
    for new, _pid in fix:
        after[(new + SHIFT) // 5 * 5] -= 1
        after[new // 5 * 5] += 1
    print("   age band     now      after")
    for band in sorted(before):
        print(f"   {band:>2}-{band + 4:<3} {before[band]:>8,} {after[band]:>10,}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fix:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preage")
    con.executemany("UPDATE players SET age=? WHERE id=?", fix)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(fix):,} ages corrected by -{SHIFT}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
