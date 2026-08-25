#!/usr/bin/env python3
"""
crest_from_rfs.py — the third crest source, for the clubs the megapack does not carry.

The DVX megapack is keyed by FM club id and covers 22,828 clubs, but not all of them: it has
Liverpool (676) and no Manchester United (680), which is why the Premier League's most recognisable
club was wearing a drawn placeholder. RFS ships its own crest store — 4,053 files at
OneDrive/Documents/RFS/Teams/T_<rfs id>.png — and Manchester United is in it, correctly.

Two jobs, both about making the picture actually render:

  1. 230 teams already point at that store by ABSOLUTE path. The validation gate allows it (the
     store lives outside the repo by design) but nothing else in the world does, and an absolute
     path is one moved folder away from a blank crest. Copy the file into assets/rfs_crests and
     point at it the way every other crest is pointed at.
  2. A catalog club still on a drawn placeholder takes an RFS crest when exactly ONE RFS team of
     that name has a crest on disk. Not "the best match" — one, or nothing. RFS's team record does
     carry a country, but its offset is not documented anywhere we trust, and guessing a binary
     layout is precisely what this repo forbids; uniqueness is the guard instead.

Never overwrites a real DVX crest: this only touches absolute paths and drawn placeholders.

    python tools/crest_from_rfs.py --dry
    python tools/crest_from_rfs.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import struct
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
STORE = Path.home() / "OneDrive/Documents/RFS/Teams"
OUT = REPO / "assets" / "rfs_crests"
RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"

sys.path.insert(0, str(REPO / "tools"))
from build_catalog import club_key            # noqa: E402  (the catalog's own normalisation)


def convert(src: Path, dst: Path) -> bool:
    from PIL import Image
    try:
        im = Image.open(src)
        im.thumbnail((128, 128), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "WEBP", quality=88)
        return True
    except Exception:                                          # noqa: BLE001 — skip a bad file
        return False


def rfs_teams():
    """RFS team id -> name."""
    from rfs_import import RfsDb
    db = RfsDb(RFS_DB)
    tt = db.tables["teams"]
    out = {}
    for i in range(tt.rows):
        r = db.record("teams", i)
        tid = struct.unpack_from("<I", r, 0)[0]
        out[tid] = r[36:36 + 32].split(b"\0")[0].decode("utf-8", "replace").strip()
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    where = {t["team_id"]: co["name"] for co in cat["countries"] for lg in co["leagues"]
             for t in lg["teams"]}

    # ---- 1: absolute RFS paths -> repo-relative copies
    moves = []
    for tid, name, logo in con.execute(
            "SELECT id, name, logo_path FROM teams WHERE logo_path IS NOT NULL"):
        if "OneDrive" not in logo and not (len(logo) > 2 and logo[1] == ":"):
            continue
        m = re.search(r"T_(\d+)\.png$", logo.replace("/", "\\"), re.I)
        if not m:
            continue
        moves.append((int(m.group(1)), tid, name))

    # ---- 2: catalog clubs still on a drawn placeholder
    drawn = [(tid, name) for tid, name, logo in con.execute(
        "SELECT id, name, logo_path FROM teams WHERE logo_path LIKE 'assets/gen_badges/%'")
        if tid in where]
    fills = []
    if drawn:
        rfs = rfs_teams()
        by_key = defaultdict(list)
        for rid, nm in rfs.items():
            if nm and (STORE / f"T_{rid}.png").exists():
                by_key[club_key(nm)].append((rid, nm))
        for tid, name in drawn:
            cands = by_key.get(club_key(name), [])
            if len(cands) == 1:
                fills.append((cands[0][0], tid, name))

    print(f"teams pointing at the RFS store by absolute path: {len(moves)}")
    print(f"catalog clubs on a drawn placeholder that RFS can dress: {len(fills)}")
    for rid, tid, name in fills[:8]:
        print(f"   {name[:28]:28} (team {tid}) -> RFS T_{rid}.png")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not (moves or fills):
        return 0

    assign = []
    for rid, tid, _name in moves + fills:
        dst = OUT / f"{rid}.webp"
        if not dst.exists() and not convert(STORE / f"T_{rid}.png", dst):
            continue
        assign.append((f"assets/rfs_crests/{rid}.webp", tid))

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prerfscrest")
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", assign)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    by_tid = dict((t, p) for p, t in assign)
    n = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                if t["team_id"] in by_tid:
                    t["logo"] = by_tid[t["team_id"]]
                    n += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied. {len(assign)} crests brought into the repo | {n} catalog entries patched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
