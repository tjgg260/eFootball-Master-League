#!/usr/bin/env python3
"""
gen_club_badges.py — a drawn badge for the clubs no pack has one for.

Every catalog club needs a crest the app can render; the gate insists on it. import_dvx_logos
covers anything the DVX megapack knows, link_logos_by_fm_id covers anything already extracted under
the club's FM id, and after both there is a short tail of clubs whose FM ids simply are not in the
pack — San Antonio Bulo Bulo in Bolivia, Cacahuatique in El Salvador. They get a generated crest in
assets/gen_badges, the same place the nine earlier ones live: 128x128 RGBA WebP, colours derived
from the team id so a club always draws the same badge, initials taken from its name.

    python tools/gen_club_badges.py --dry
    python tools/gen_club_badges.py
"""
from __future__ import annotations

import colorsys
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
OUT = REPO / "assets" / "gen_badges"
SIZE = 128


def initials(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]
    skip = {"fc", "cf", "sc", "ac", "cd", "club", "de", "la", "el", "the", "atletico", "atl"}
    keep = [w for w in words if w.lower() not in skip] or words
    if len(keep) == 1:
        return keep[0][:2].upper()
    return (keep[0][0] + keep[1][0]).upper()


def colours(tid: int):
    h = (tid * 2654435761 % 2 ** 32) / 2 ** 32
    r1, g1, b1 = colorsys.hsv_to_rgb(h, 0.62, 0.55)
    r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.5) % 1.0, 0.45, 0.88)
    return tuple(int(c * 255) for c in (r1, g1, b1)), tuple(int(c * 255) for c in (r2, g2, b2))


def draw(tid: int, name: str, path: Path) -> None:
    base, accent = colours(tid)
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((4, 4, SIZE - 4, SIZE - 4), fill=base + (255,), outline=accent + (255,), width=5)
    d.ellipse((16, 16, SIZE - 16, SIZE - 16), outline=accent + (120,), width=2)
    txt = initials(name)
    try:
        font = ImageFont.truetype("arialbd.ttf", 52)
    except OSError:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), txt, font=font)
    d.text(((SIZE - box[2] + box[0]) / 2, (SIZE - box[3] + box[1]) / 2 - 2), txt,
           font=font, fill=(255, 255, 255, 235))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "WEBP", quality=92, method=6)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    logo = dict(con.execute("SELECT id, logo_path FROM teams"))
    names = dict(con.execute("SELECT id, name FROM teams"))

    # A club's crest is recorded twice — teams.logo_path and the catalog entry — and either can
    # be the one that is filled in. Draw only when NEITHER resolves to a file on disk; when just
    # one does, copy it across instead of inventing a badge over a real crest.
    need, synced = [], []
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                tid = t["team_id"]
                db_p, cat_p = logo.get(tid), t.get("logo")
                db_ok = bool(db_p) and (REPO / db_p).exists()
                cat_ok = bool(cat_p) and (REPO / cat_p).exists()
                if db_ok and cat_ok:
                    if db_p != cat_p:
                        synced.append((tid, db_p, t))
                elif db_ok:
                    synced.append((tid, db_p, t))
                elif cat_ok:
                    synced.append((tid, cat_p, t))
                else:
                    need.append(tid)
    need = sorted(set(need))
    print(f"catalog clubs with no badge file anywhere: {len(need)} | "
          f"crests to copy between the two records: {len(synced)}")
    for tid in need:
        print(f"   {tid} {names.get(tid)!r} -> initials {initials(names.get(tid) or '')!r}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not need and not synced:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prebadges")
    for tid in need:
        rel = f"assets/gen_badges/{tid}.webp"
        draw(tid, names.get(tid) or str(tid), REPO / rel)
        con.execute("UPDATE teams SET logo_path=? WHERE id=?", (rel, tid))
        for co in cat["countries"]:
            for lg in co["leagues"]:
                for t in lg["teams"]:
                    if t["team_id"] == tid:
                        t["logo"] = rel
    for tid, path, entry in synced:
        entry["logo"] = path
        con.execute("UPDATE teams SET logo_path=? WHERE id=?", (path, tid))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied. {len(need)} badges drawn, {len(synced)} crests copied across.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
