#!/usr/bin/env python3
"""
supersede_rfs_orphans.py — 'Mbappe', rated 93, was a free agent you could sign.

RFS records carry surnames only and no FM uid, so the identity passes could not pair them and
rfs_demote only replaced the ones holding a squad place. What is left sits unsquadded in the world
band, which is exactly the pool the Market and Scouting screens draw from: a 93-rated 'Mbappe', an
89-rated 'Rodri' and an 85-rated 'van Dijk' all offering themselves for nothing while the real
players play for Real Madrid, Manchester City and Liverpool.

A surname alone is not identity, so the pairing needs more than a name. A twin is accepted only
when all of it agrees:

  - same surname (last token), and the twin has a fuller name than the bare surname
  - same first nationality
  - ages within 3 (RFS and FM disagree by a year or two, never by a career)
  - ratings within 8 (different sources, same player)
  - both keep goal or neither does
  - EXACTLY ONE record fits; several means the surname is common and we do not guess

The RFS record is kept and marked superseded_by, per the blueprint: it leaves every pool, keeps its
row, and hands its face to the survivor if the survivor has none.

    python tools/supersede_rfs_orphans.py --dry
    python tools/supersede_rfs_orphans.py
then: validate_db.py
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
RFS_LO, RFS_HI = 700_000_000, 10_000_000_000


def toks(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).split()


def nat1(s):
    return (s or "").split("/")[0].strip().lower()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    squadded = {p for (p,) in con.execute("SELECT player_id FROM squad_members")}
    rows = list(con.execute(
        "SELECT id, name, overall_rating, age, nationality, position, real_face_path, "
        "portrait_path FROM players WHERE superseded_by IS NULL"))
    by_last = defaultdict(list)
    for r in rows:
        t = toks(r[1])
        if t:
            by_last[t[-1]].append(r)

    pairs, ambiguous = [], 0
    for pid, name, rat, age, nat, pos, face, port in rows:
        if pid in squadded or not (RFS_LO <= pid < RFS_HI):
            continue
        t = toks(name)
        if len(t) != 1:
            continue
        cands = [x for x in by_last.get(t[0], [])
                 if x[0] != pid and x[0] in squadded and len(toks(x[1])) > 1
                 and nat1(x[4]) == nat1(nat)
                 and x[3] is not None and age is not None and abs(x[3] - age) <= 3
                 and x[2] is not None and rat is not None and abs(x[2] - rat) <= 8
                 and (x[5] == "GK") == (pos == "GK")]
        if len(cands) == 1:
            pairs.append((pid, name, rat, cands[0]))
        elif cands:
            ambiguous += 1

    pool = sum(1 for r in rows
               if r[0] not in squadded and RFS_LO <= r[0] < RFS_HI and len(toks(r[1])) == 1)
    print(f"RFS surname-only records sitting in the signable pool: {pool:,}")
    print(f"  paired to exactly one real player: {len(pairs):,} | left alone as ambiguous: "
          f"{ambiguous:,}")
    for pid, name, rat, c in sorted(pairs, key=lambda p: -(p[2] or 0))[:8]:
        print(f"   {name!r} ({rat}) -> {c[1]!r} ({c[2]})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not pairs:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prerfsorphan")
    faces = 0
    cur.execute("BEGIN")
    for pid, _name, _rat, c in pairs:
        keep = c[0]
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (keep, pid))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (keep, pid, keep))
        if (c[6] or c[7]) is None:
            src = con.execute(
                "SELECT real_face_path, portrait_path FROM players WHERE id=?", (pid,)).fetchone()
            if src and (src[0] or src[1]):
                cur.execute("UPDATE players SET real_face_path=COALESCE(real_face_path,?), "
                            "portrait_path=COALESCE(portrait_path,?) WHERE id=?",
                            (src[0], src[1], keep))
                faces += 1
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(pairs):,} records superseded, {faces} faces handed to the survivor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
