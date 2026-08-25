#!/usr/bin/env python3
"""
link_faces_by_fm_id.py — if the player's own photograph is on disk, wear it.

The facepack holds two different things and only one of them is a photograph of anybody:

    facepack/webp/face_<fm uid>.webp        202,737 REAL faces, keyed by the player's FM uid
    facepack/uran/players/male/0/@2x/*.png  generic faces picked by nationality (GER1613, NED593)

A generic face is a reasonable fallback for a player nobody photographed. It is not reasonable for
Marc ter Stegen, who was wearing GER1613.png while face_35017428.webp — him — sat unused in the
same pack. That is what "wrong faces" looks like on a squad screen: a famous player rendered as a
stock German, and beside him a team-mate with no picture at all showing coloured initials.

The rule is the one that fixed the club crests: join on the verified id, never on the name. If a
player carries an fm_uid and `face_<that uid>.webp` exists, that file is his face and goes in
real_face_path. Nothing else is touched — the generic portrait stays in portrait_path as the
fallback it was always meant to be, and a player with no uid or no file keeps whatever he has.

Career and curated copies are included deliberately. They are the squads the user actually looks
at, they carry the same uids, and nothing else fills them in.

    python tools/link_faces_by_fm_id.py --dry
    python tools/link_faces_by_fm_id.py
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
FACES = REPO / "facepack" / "webp"


def store(fp: str | None) -> str:
    if not fp:
        return "nothing"
    if fp.startswith("facepack/webp/"):
        return "a real photo"
    if "uran" in fp:
        return "a generic face"
    if "RFS" in fp:
        return "an RFS portrait"
    return "something else"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    have = {p.stem[5:] for p in FACES.glob("face_*.webp")}
    print(f"real faces on disk: {len(have):,}")

    fix, was = [], Counter()
    for pid, name, rf, pf, uid in con.execute(
            "SELECT p.id, p.name, p.real_face_path, p.portrait_path, pi.fm_uid FROM players p "
            "JOIN player_identity pi ON pi.player_id=p.id "
            "WHERE pi.fm_uid IS NOT NULL AND p.superseded_by IS NULL"):
        if str(uid) not in have:
            continue
        want = f"facepack/webp/face_{uid}.webp"
        if rf == want:
            continue
        fix.append((want, pid))
        was[store(rf or pf)] += 1

    squadded = {p for (p,) in con.execute("SELECT player_id FROM squad_members")}
    in_squad = sum(1 for _w, pid in fix if pid in squadded)
    print(f"players to give their own face: {len(fix):,} ({in_squad:,} of them in a squad)")
    for k, n in was.most_common():
        print(f"   wearing {k}: {n:,}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fix:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prefaces")
    con.executemany("UPDATE players SET real_face_path=? WHERE id=?", fix)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(fix):,} players now wear their own photograph.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
