#!/usr/bin/env python3
"""
import_rfs_comp_logos.py — LEAGUE badges from the RFS pack, joined by id. No name guessing.

RFS ships 314 competition logos as Competitions/Logos/L_<comp_id>.png (256x256 RGBA), and
catalog.json's league_id IS the RFS competition id (build_catalog.py reads it from the RFS DB's
competitions table at offset 0 — verified 2026-08-23). So the join is exact:

    catalog league_id  ==  <id>  in  L_<id>.png        (~96 of 145 catalog leagues hit directly)

Output mirrors import_dvx_meta.py's convention: assets/rfs_comps/<league_id>.webp at 128 px,
stored on the league as "comp_logo". An existing comp_logo (the three DVX ones) is only
replaced when RFS has a direct hit; leagues with neither keep their tier-number badge in the
UI. Filename case varies in the pack (L_ / l_) — the index is case-insensitive.

    python tools/import_rfs_comp_logos.py --dry
    python tools/import_rfs_comp_logos.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAT = REPO / "build" / "catalog.json"
RFS_LOGOS = Path.home() / "OneDrive" / "Documents" / "RFS" / "Competitions" / "Logos"
OUT = REPO / "assets" / "rfs_comps"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    if not RFS_LOGOS.is_dir():
        print(f"RFS logo dir not found: {RFS_LOGOS}")
        return 1

    # id -> file, case-insensitive stem, numeric ids only ('338a' is a known stray)
    by_id: dict[int, Path] = {}
    for f in RFS_LOGOS.glob("*.png"):
        stem = f.stem.lower()
        if stem.startswith("l_") and stem[2:].isdigit():
            by_id[int(stem[2:])] = f
    print(f"RFS league logos indexed: {len(by_id)}")

    cat = json.loads(CAT.read_text(encoding="utf-8"))
    hits: list[tuple[dict, Path]] = []
    misses = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            lid = lg.get("league_id")
            if lid in by_id:
                hits.append((lg, by_id[lid]))
            elif lid:
                misses += 1
    print(f"direct hits: {len(hits)} leagues | without a logo: {misses}")
    if dry:
        for lg, f in hits[:10]:
            print(f"  {lg['name']} -> {f.name}")
        return 0

    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CAT, str(CAT) + ".bak-rfscomps")
    n = 0
    for lg, src in hits:
        dest = OUT / f"{lg['league_id']}.webp"
        if not dest.exists():
            im = Image.open(src)
            im.thumbnail((128, 128), Image.LANCZOS)
            im.save(dest, "WEBP", quality=86)
        lg["comp_logo"] = f"assets/rfs_comps/{lg['league_id']}.webp"
        n += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"catalog patched: {n} league badges from RFS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
