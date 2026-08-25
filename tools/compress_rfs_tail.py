#!/usr/bin/env python3
"""
compress_rfs_tail.py — the world's twenty best players were RFS records, and Mbappe was tenth.

Squadded, world-band, sorted by rating, the top of the database read: Ben Said 88 (Esperance
Tunis), Palhinha 87, Boniface 87, Di Maria 87 — and Kylian Mbappe 85, which is what eFootball
itself rates him. That is the tell. eFootball's own export tops out at 85-86 and our eFootball
records are copied from it verbatim, so anything above that came from somewhere else.

The distributions say the same thing precisely. Across squadded players' abilities:

    eFootball   p50 60   p90 70   p99 77   max 86
    RFS         p50 49   p90 64   p99 76   max 99
    FM          p50 57   p90 64   p99 68   max 86

RFS is not inflated as a whole — its body sits BELOW eFootball's, and up to the 99th percentile
the two agree within a point. It is only the last percent that runs away, stretching 23 further
points where eFootball's own scale has 9 left. So only that tail is touched: values above the
crossover are mapped by rank onto the range eFootball actually uses above the same point, and
99% of RFS values are left exactly as they are.

This is not a re-derivation. RFS is the last-priority source (owner ruling) and this only stops
it claiming ratings the game's own data never gives anyone.

    python tools/compress_rfs_tail.py --dry
    python tools/compress_rfs_tail.py
then: fix_overalls.py (the ratings follow the abilities), validate_db.py
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
sys.path.insert(0, str(REPO / "tools"))
from ability_bits import ABILITY_BITS   # noqa: E402

RFS_LO, RFS_HI = 700_000_000, 10_000_000_000
EF_HI = 20_000_000
PCT = 0.99


def spread(con, lo, hi):
    ph = ",".join("?" * len(ABILITY_BITS))
    v = [r[0] for r in con.execute(
        f"SELECT a.value FROM player_attributes a JOIN players p ON p.id=a.player_id "
        f"JOIN squad_members s ON s.player_id=p.id "
        f"WHERE a.attribute IN ({ph}) AND p.id>=? AND p.id<? AND p.superseded_by IS NULL",
        (*ABILITY_BITS, lo, hi))]
    v.sort()
    return v


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    ef = spread(con, 0, EF_HI)
    rfs = spread(con, RFS_LO, RFS_HI)
    if not ef or not rfs:
        print("not enough data to compare the two scales")
        return 1
    ef_p, ef_max = ef[int(len(ef) * PCT)], ef[-1]
    rfs_p, rfs_max = rfs[int(len(rfs) * PCT)], rfs[-1]
    print(f"eFootball p{PCT:.0%} {ef_p}, max {ef_max} | RFS p{PCT:.0%} {rfs_p}, max {rfs_max}")
    if rfs_max <= ef_max:
        print("RFS already sits inside eFootball's range — nothing to compress.")
        return 0

    span_in, span_out = rfs_max - rfs_p, ef_max - ef_p

    def squash(v):
        return int(round(ef_p + (v - rfs_p) * span_out / span_in))

    fix = [(squash(v), pid, attr) for pid, attr, v in con.execute(
        "SELECT player_id, attribute, value FROM player_attributes "
        "WHERE player_id>=? AND player_id<? AND value>?", (RFS_LO, RFS_HI, rfs_p))]
    fix = [f for f in fix if f[0] != 0]
    players = len({f[1] for f in fix})
    print(f"RFS ability values above {rfs_p}: {len(fix):,} across {players:,} players "
          f"-> mapped into {ef_p}..{ef_max}")
    for v_new, pid, attr in fix[:6]:
        old = con.execute("SELECT value FROM player_attributes WHERE player_id=? AND attribute=?",
                          (pid, attr)).fetchone()[0]
        print(f"   id {pid} {attr}: {old} -> {v_new}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fix:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prerfstail")
    con.executemany("UPDATE player_attributes SET value=? WHERE player_id=? AND attribute=?", fix)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(fix):,} values compressed. Run fix_overalls.py — the ratings follow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
