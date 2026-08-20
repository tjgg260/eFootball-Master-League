#!/usr/bin/env python3
"""
enrich_media.py — backfill portrait_path / logo_path across the WHOLE master DB.

The career seeder wires images for the clubs it seeds; this closes the gap for the other ~58k
players and ~5k teams so every screen (Market above all) shows real art wherever source art
exists. Players match to RFS face photos (p<rfs_id>.png) by name; teams match to club crests
(T_<rfs_id>.png) via the catalog. Unmatched rows keep NULL and render generated avatars/badges.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from rfs_import import RfsDb   # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
RFS_PLAYERS = Path.home() / "OneDrive/Documents/RFS/Players"
RFS_TEAMS = Path.home() / "OneDrive/Documents/RFS/Teams"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("ø", "o").replace("Ø", "o"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def main() -> int:
    con = sqlite3.connect(REPO / "build" / "master.db")
    rfs = RfsDb(RFS_DB)

    # name -> portrait path (only names that are unambiguous in RFS, so we never misassign a face)
    pt = rfs.tables["players"]
    name_count: dict[str, int] = {}
    name_img: dict[str, str] = {}
    for i in range(pt.rows):
        rec = rfs.record("players", i)
        pid = struct.unpack_from("<I", rec, 0)[0]
        full = norm(rec[76:100].split(b"\0")[0].decode("utf-8", "replace"))
        if not full:
            continue
        name_count[full] = name_count.get(full, 0) + 1
        img = RFS_PLAYERS / f"p{pid}.png"
        if img.exists():
            name_img[full] = str(img)
    unique_img = {n: p for n, p in name_img.items() if name_count.get(n) == 1}

    players = con.execute("SELECT id, name FROM players WHERE portrait_path IS NULL").fetchall()
    hits = [(unique_img[norm(nm)], pid) for pid, nm in players if norm(nm) in unique_img]
    con.executemany("UPDATE players SET portrait_path=? WHERE id=?", hits)

    # club crests via the catalog (has rfs_id + verified logo path per club)
    catalog = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    club_logo = {norm(t["name"]): t["logo"] for lg in catalog["leagues"] for t in lg["teams"] if t.get("logo")}
    teams = con.execute("SELECT id, name FROM teams WHERE logo_path IS NULL").fetchall()
    thits = [(club_logo[norm(nm)], tid) for tid, nm in teams if norm(nm) in club_logo]
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", thits)

    con.commit()
    tp = con.execute("SELECT COUNT(*) FROM players WHERE portrait_path IS NOT NULL").fetchone()[0]
    tl = con.execute("SELECT COUNT(*) FROM teams WHERE logo_path IS NOT NULL").fetchone()[0]
    print(f"portraits: +{len(hits):,} backfilled -> {tp:,} players with real face photos")
    print(f"logos:     +{len(thits):,} backfilled -> {tl:,} teams with real crests")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
