#!/usr/bin/env python3
"""
apply_adjudicated_merges.py — merge the unclubbed duplicates an individual adjudication identified.

supersede_rfs_orphans can only merge what a rule can prove, and a surname is not proof: 'El Mala'
rated 82 with no club, 'Ngumoha', 'Karl', 'Schmeichel' — 112 such records sat outside the world
because no rule could tell them from their namesakes. Each was adjudicated one by one, from the
database and from the player's real 2025-26 club, age and position, and every proposed merge was
then re-checked by a second pass whose only job was to refute it. This applies the pairs that
survived; the input is that list, one {"id", "target"} per pair.

The guards are re-checked here against the live database rather than trusted: the record is live
and in no squad; the target is live, not a career copy or the curated overlay; the two agree on
nationality where both carry one, and on keeper-or-not. A pair failing any guard is skipped and
printed. A target without a face takes the record's.

    python tools/apply_adjudicated_merges.py <pairs.json> --dry
    python tools/apply_adjudicated_merges.py <pairs.json>
then: validate_db.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAREER_LO, CAREER_HI = 20_000_000, 700_000_000
CUR_LO, CUR_HI = 45_000_000_000, 46_000_000_000
NATION_SYN = {"holland": "netherlands", "korea republic": "south korea", "turkiye": "turkey",
              "usa": "united states", "czechia": "czech republic", "cote d'ivoire": "ivory coast"}


def nation(s):
    v = unicodedata.normalize("NFKD", (s or "").split("/")[0]).encode("ascii", "ignore")
    v = v.decode().strip().lower()
    return NATION_SYN.get(v, v)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    pairs = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    con = sqlite3.connect(DB, timeout=300)
    squadded = {p for (p,) in con.execute("SELECT player_id FROM squad_members")}

    def row(pid):
        return con.execute("SELECT id, name, nationality, position, superseded_by, "
                           "real_face_path, portrait_path FROM players WHERE id=?",
                           (pid,)).fetchone()

    ok, skipped = [], []
    for pr in pairs:
        src, tgt = row(int(pr["id"])), row(int(pr["target"]))
        why = None
        if src is None or tgt is None:
            why = "record missing"
        elif src[4] is not None:
            why = "already superseded"
        elif src[0] in squadded:
            why = "record is in a squad"
        elif tgt[4] is not None:
            why = "target is superseded"
        elif CAREER_LO <= tgt[0] < CAREER_HI or CUR_LO <= tgt[0] < CUR_HI:
            why = "target is a career copy or curated"
        elif src[2] and tgt[2] and nation(src[2]) != nation(tgt[2]):
            why = f"nationality {src[2]!r} vs {tgt[2]!r}"
        elif (src[3] == "GK") != (tgt[3] == "GK"):
            why = f"keeper vs outfield ({src[3]} / {tgt[3]})"
        if why:
            skipped.append((src[1] if src else pr["id"], tgt[1] if tgt else pr["target"], why))
        else:
            ok.append((src, tgt))

    print(f"adjudicated merges: {len(pairs)} | pass every guard: {len(ok)} | skipped: {len(skipped)}")
    for s, t, why in skipped:
        print(f"   skipped {s!r} -> {t!r}: {why}")
    for s, t in ok[:10]:
        print(f"   {s[1]!r} ({s[0]}) -> {t[1]!r} ({t[0]})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not ok:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preadjudicated")
    cur = con.cursor()
    cur.execute("BEGIN")
    faces = 0
    for s, t in ok:
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (t[0], s[0]))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (t[0], s[0], t[0]))
        if not (t[5] or t[6]) and (s[5] or s[6]):
            cur.execute("UPDATE players SET real_face_path=?, portrait_path=? WHERE id=?",
                        (s[5], s[6], t[0]))
            faces += 1
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(ok)} records superseded behind the player they are | {faces} faces "
          f"handed to the survivor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
