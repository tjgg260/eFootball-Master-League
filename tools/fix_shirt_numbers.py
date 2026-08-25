#!/usr/bin/env python3
"""
fix_shirt_numbers.py — two players in one squad wearing the same number.

141 catalog clubs field a duplicate shirt: Manchester United and Manchester City each have two
number 1s, Rennes has four clashes of its own. It comes from every writer that appends to a squad
picking a number independently — the membership sync, fill_squads, the missing-player import — so
two arrivals in the same run can choose the same free number, and a club whose roster changed
hands keeps whatever the old records wore.

Squad numbers are user-visible data, so this changes as little as possible: within a clash the
player highest up the squad order (slot) keeps the number, and everyone else takes the lowest
number nobody at the club is wearing. Nothing else about the squad moves — slots, roles and
membership are untouched.

    python tools/fix_shirt_numbers.py --dry
    python tools/fix_shirt_numbers.py
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    tname = dict(con.execute("SELECT id, name FROM teams"))

    squads = defaultdict(list)
    for tid, pid, num, slot in con.execute(
            "SELECT team_id, player_id, squad_number, slot FROM squad_members ORDER BY team_id, slot"):
        squads[tid].append((pid, num, slot))

    fixes = []
    for tid, members in squads.items():
        by_num = defaultdict(list)
        for pid, num, slot in members:
            if num is not None:
                by_num[num].append((slot, pid))
        clash = {n: v for n, v in by_num.items() if len(v) > 1}
        if not clash:
            continue
        used = {n for n in by_num}
        for num, v in sorted(clash.items()):
            for _slot, pid in sorted(v)[1:]:          # the deepest in the order keeps it
                nxt = next(x for x in range(1, 1000) if x not in used)
                used.add(nxt)
                fixes.append((nxt, tid, pid, num))

    clubs = {f[1] for f in fixes}
    print(f"squads with a duplicated shirt: {len(clubs):,} | numbers to reissue: {len(fixes):,}")
    for nxt, tid, _pid, num in fixes[:8]:
        print(f"   {tname.get(tid)!r}: a second #{num} becomes #{nxt}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fixes:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preshirts")
    con.executemany("UPDATE squad_members SET squad_number=? WHERE team_id=? AND player_id=?",
                    [(n, t, p) for n, t, p, _o in fixes])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    left = con.execute("SELECT COUNT(*) FROM (SELECT team_id FROM squad_members "
                       "WHERE squad_number IS NOT NULL GROUP BY team_id, squad_number "
                       "HAVING COUNT(*)>1)").fetchone()[0]
    print(f"applied. {len(fixes):,} shirts reissued | clashes left anywhere: {left}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
