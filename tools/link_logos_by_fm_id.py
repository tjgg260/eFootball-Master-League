#!/usr/bin/env python3
"""
link_logos_by_fm_id.py — if the badge file is already on disk under the club's FM id, use it.

import_dvx_logos extracts to assets/dvx_logos/<fm club id>.webp, but assigns by walking FM's
club NAMES and matching them against teams.name. FM stores short forms, so the join misses
exactly the clubs whose display name we corrected: Paris Saint-Germain's badge (868.webp) sat
extracted and unassigned because fm_clubs calls the club 'PSG'.

team_identity.fm_club_id is the same number, already verified against squad content by
verify_identity_fm. Use it directly: for any team whose logo is missing and whose FM id has an
extracted badge, point at that badge. No new files, no name guessing.

    python tools/link_logos_by_fm_id.py --dry
    python tools/link_logos_by_fm_id.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
LOGOS = REPO / "assets" / "dvx_logos"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    have = {p.stem for p in LOGOS.glob("*.webp")}
    fix = []
    for tid, name, logo, fc in con.execute(
            "SELECT t.id, t.name, t.logo_path, ti.fm_club_id FROM teams t "
            "JOIN team_identity ti ON ti.team_id=t.id WHERE ti.fm_club_id IS NOT NULL"):
        if logo and (REPO / logo).exists():
            continue
        if str(fc) in have:
            fix.append((f"assets/dvx_logos/{fc}.webp", tid, name))

    print(f"teams with no usable badge whose FM id already has one on disk: {len(fix):,}")
    for path, tid, name in fix[:8]:
        print(f"   {tid} {name[:28]:28} -> {path}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fix:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prelogos")
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", [(p, t) for p, t, _n in fix])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    by_tid = {t: p for p, t, _n in fix}
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    n = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                if t["team_id"] in by_tid:
                    t["logo"] = by_tid[t["team_id"]]
                    n += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied. {len(fix):,} teams | {n} catalog entries patched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
