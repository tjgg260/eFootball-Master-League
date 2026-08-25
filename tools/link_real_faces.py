#!/usr/bin/env python3
"""
link_real_faces.py — connect faceless copies of REAL players to the real face another record of the
same player already carries. RFS/career records are often surname-only with stale ages ('Cozier-
Duberry, 21' vs FM's 'Amario Cozier-Duberry, 24'), so the old surname+nationality+age-within-2
backfill missed them and they fell back to generated Uran portraits.

LAST RESORT ONLY. A player who carries an fm_uid is served by tools/link_faces_by_fm_id.py, which
joins his own uid to his own file and cannot be wrong about who he is; this tool never sees him.
What is left are records with no identity at all, and for those a surname is the only handle there
is — so the uniqueness guard below is doing real work, and a miss here costs nothing but a
generic face.

Match rule (conservative, uniqueness-guarded):
  key = normalized surname (accents/hyphens stripped) + nationality.
  - If every faced candidate under that key shares ONE face file -> link it (a unique
    surname+nation is the same person; common surnames like Smith/England have many distinct
    faces and stay ambiguous -> skipped).
  - Else if age within ±4 narrows the candidates to one face -> link that.
Writes real_face_path only (tier 1) — the Uran portrait stays behind it as fallback. Idempotent.

    python tools/link_real_faces.py --dry
    python tools/link_real_faces.py
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


def surname(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    toks = n.replace("-", " ").split()
    # hyphenated surnames collapse to their joined form; take the LAST TWO tokens if the original
    # last token was hyphenated, else the last token
    raw_last = (name or "").split()[-1] if (name or "").split() else ""
    if "-" in raw_last:
        return re.sub(r"[^a-z]", "", "".join(toks[-raw_last.count('-') - 1:]))
    return re.sub(r"[^a-z]", "", toks[-1] if toks else "")


def nat_of(nat: str) -> str:
    return (nat or "").split("/")[0].strip().lower()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=60)

    faced = defaultdict(list)     # (surname, nat) -> [(face_path, age)]
    for nm, nat, age, face in con.execute(
            "SELECT name, nationality, age, real_face_path FROM players "
            "WHERE real_face_path IS NOT NULL"):
        key = (surname(nm), nat_of(nat))
        if key[0]:
            faced[key].append((face, age))

    updates, ambiguous = [], 0
    for pid, nm, nat, age in con.execute(
            "SELECT p.id, p.name, p.nationality, p.age FROM players p "
            "LEFT JOIN player_identity pi ON pi.player_id=p.id "
            "WHERE p.real_face_path IS NULL AND pi.fm_uid IS NULL"):
        key = (surname(nm), nat_of(nat))
        cands = faced.get(key)
        if not cands:
            continue
        distinct = {f for f, _ in cands}
        if len(distinct) == 1:
            updates.append((next(iter(distinct)), pid))
            continue
        if age is not None:
            near = {f for f, a in cands if a is not None and abs(a - age) <= 4}
            if len(near) == 1:
                updates.append((next(iter(near)), pid))
                continue
        ambiguous += 1

    print(f"faceless players linkable to a real face: {len(updates):,} "
          f"(ambiguous same-surname cases skipped: {ambiguous:,})")
    if dry:
        for f, pid in updates[:6]:
            nm = con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()[0]
            print(f"  {pid} {nm} -> {Path(f).name}")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-prelink")
    con.execute("BEGIN")
    con.executemany("UPDATE players SET real_face_path=? WHERE id=?", updates)
    con.commit()
    print(f"linked {len(updates):,} players to their real face.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
