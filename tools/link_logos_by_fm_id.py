#!/usr/bin/env python3
"""
link_logos_by_fm_id.py — a club's crest is the one filed under its own FM id, not under its name.

import_dvx_logos indexes the megapack by FM club id — the filenames carry it — and then assigns by
walking FM's club NAMES and matching them against teams.name. That last step is where crests go
wrong, because a name is not an identity:

    Liverpool FC  ->  assets/dvx_logos/29036085.webp  ->  which is AFC LIVERPOOL,
                                                          a fan-owned non-league club
    Liverpool's actual FM club id is 676, and 676.webp had never been extracted.

team_identity.fm_club_id is the same number the pack is keyed by, already verified against squad
content by verify_identity_fm. So use it directly, in both directions:

  - the crest under the club's own id is missing from disk -> extract it from the megapack
  - the club wears a crest keyed to a DIFFERENT id -> replace it with its own

Guards. A hand-reconciled crest in assets/badges is never touched — those were checked by a human
and outrank the pack. A generated placeholder in assets/gen_badges IS replaced, because a real
crest beats a drawn one. And nothing is assigned unless the file exists on disk afterwards.

    python tools/link_logos_by_fm_id.py --dry
    python tools/link_logos_by_fm_id.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
LOGOS = REPO / "assets" / "dvx_logos"
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
PACKS = [REPO / "dvx_logos_2024.01.rar",
         REPO / "dvxlogos_fm2024_v2_changes.rar",
         REPO / "dvxlogos_fm2024_v3_changes.rar"]
KEEP = ("assets/badges/",)          # hand-reconciled, outranks the pack


def index_packs():
    """FM club id -> (pack, path inside it). Later packs override earlier ones."""
    pat = re.compile(r"(dvx24\\clubs\\primary\\(\d+)_[a-z]+_[a-z0-9]+\.png)$", re.I)
    dvx = {}
    for pack in PACKS:
        if not pack.exists():
            print(f"   note: {pack.name} missing — skipped")
            continue
        listing = subprocess.run([SEVENZIP, "l", str(pack)],
                                 capture_output=True, text=True).stdout
        for line in listing.splitlines():
            m = pat.search(line.replace("/", "\\"))
            if m and "\\small\\" not in m.group(1).lower():
                dvx[int(m.group(2))] = (pack, m.group(1))
    return dvx


def extract(ids, dvx):
    """Pull these club ids out of the packs and write 128px webp. Returns the ids now on disk."""
    from PIL import Image
    LOGOS.mkdir(parents=True, exist_ok=True)
    by_pack = defaultdict(list)
    for f in ids:
        if f in dvx:
            by_pack[dvx[f][0]].append(dvx[f][1])
    made = set()
    if not by_pack:
        return made
    with tempfile.TemporaryDirectory(dir=str(REPO / "build")) as tmp:
        for pack, names in by_pack.items():
            lst = Path(tmp) / "list.txt"
            lst.write_text("\n".join(names), encoding="utf-8")
            subprocess.run([SEVENZIP, "e", str(pack), f"-o{tmp}", f"@{lst}", "-y"],
                           capture_output=True)
            print(f"   extracted {len(names):,} crest(s) from {pack.name}")
        for f in sorted(ids):
            if f not in dvx:
                continue
            src = Path(tmp) / Path(dvx[f][1]).name
            if not src.exists():
                continue
            try:
                im = Image.open(src)
                im.thumbnail((128, 128), Image.LANCZOS)
                im.save(LOGOS / f"{f}.webp", "WEBP", quality=88)
                made.add(f)
            except Exception:                                  # noqa: BLE001 — skip a bad file
                continue
    return made


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    have = {int(p.stem) for p in LOGOS.glob("*.webp") if p.stem.isdigit()}
    rows = list(con.execute(
        "SELECT t.id, t.name, t.logo_path, ti.fm_club_id FROM teams t "
        "JOIN team_identity ti ON ti.team_id=t.id WHERE ti.fm_club_id IS NOT NULL"))

    why = Counter()
    todo, missing_file = [], set()
    for tid, name, logo, fc in rows:
        if logo and logo.startswith(KEEP):
            continue
        want = f"assets/dvx_logos/{fc}.webp"
        if logo == want:
            continue
        if not logo or not (REPO / logo).exists():
            why["had no crest on disk"] += 1
        elif logo.startswith("assets/gen_badges/"):
            why["was wearing a drawn placeholder"] += 1
        else:
            why["was wearing another club's crest"] += 1
        todo.append((want, tid, name, fc))
        if fc not in have:
            missing_file.add(fc)

    print(f"clubs whose crest is not the one filed under their own FM id: {len(todo):,}")
    for k, n in why.most_common():
        print(f"   {k}: {n:,}")
    print(f"   of these, {len(missing_file):,} need extracting from the megapack first")
    for want, tid, name, fc in todo[:6]:
        print(f"   {name[:28]:28} (team {tid}) -> {want}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not todo:
        return 0

    if missing_file:
        print("indexing the megapack...")
        dvx = index_packs()
        got = extract(missing_file, dvx)
        have |= got
        print(f"   {len(got):,} extracted, {len(missing_file - got):,} not in the pack at all")

    fix = [(w, t) for w, t, _n, fc in todo if fc in have]
    print(f"crests to assign: {len(fix):,}")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-precrest")
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", fix)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    by_tid = dict((t, w) for w, t in fix)
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    n = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                if t["team_id"] in by_tid:
                    t["logo"] = by_tid[t["team_id"]]
                    n += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied. {len(fix):,} clubs | {n} catalog entries patched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
