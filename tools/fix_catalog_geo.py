#!/usr/bin/env python3
"""
fix_catalog_geo.py — one-shot geography fixes for build/catalog.json (in place, with a .bak).

Same pattern as import_rfs_comp_logos.py: back up, patch, rewrite compact UTF-8.

1) Peru sits under Europe in the New Career picker. catalog.json carries no continent at all —
   the app derives it from a name map (Continents.cs) whose fallback is Europe, and Peru is
   missing from the map. The durable data fix is an explicit key the picker honours:
       countries[Peru]["continent"] = "South America"
   (NewCareerViewModel reads "continent" as an override before falling back to the map.)

2) Kosovo has an empty "flag". If assets/dvx_flags has a Kosovo trigram (XKX / KOS, any case,
   any extension), point the flag at it; if none exists, say so and change nothing.

    python tools/fix_catalog_geo.py          # apply
    python tools/fix_catalog_geo.py --dry    # show what would change
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAT = REPO / "build" / "catalog.json"
FLAGS = REPO / "assets" / "dvx_flags"

KOSOVO_TRIGRAMS = ("XKX", "KOS")


def find_country(cat: dict, name: str) -> dict | None:
    for co in cat["countries"]:
        if co.get("name", "").lower() == name.lower():
            return co
    return None


def find_kosovo_flag() -> Path | None:
    if not FLAGS.is_dir():
        return None
    for f in FLAGS.iterdir():
        if f.is_file() and f.stem.upper() in KOSOVO_TRIGRAMS:
            return f
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    if not CAT.is_file():
        print(f"catalog not found: {CAT}")
        return 1

    cat = json.loads(CAT.read_text(encoding="utf-8"))
    changed = False

    # --- 1) Peru → South America -------------------------------------------------
    peru = find_country(cat, "Peru")
    if peru is None:
        print("Peru: not in the catalog — nothing to fix.")
    else:
        before = peru.get("continent") or "(none — app fallback maps it to Europe)"
        if peru.get("continent") == "South America":
            print(f"Peru: continent already 'South America' — no change.")
        else:
            print(f"Peru: continent {before} -> 'South America'")
            peru["continent"] = "South America"
            changed = True

    # --- 2) Kosovo flag ----------------------------------------------------------
    kosovo = find_country(cat, "Kosovo")
    if kosovo is None:
        print("Kosovo: not in the catalog — nothing to fix.")
    else:
        before = kosovo.get("flag") or "(empty)"
        flag = find_kosovo_flag()
        if flag is None:
            checked = ", ".join(KOSOVO_TRIGRAMS)
            print(f"Kosovo: flag stays {before} — no {checked} file in {FLAGS.name}/ "
                  f"(REPORT: no Kosovo trigram exists in assets/dvx_flags)")
        else:
            rel = f"assets/dvx_flags/{flag.name}"
            if kosovo.get("flag") == rel:
                print(f"Kosovo: flag already {rel} — no change.")
            else:
                print(f"Kosovo: flag {before} -> {rel}")
                kosovo["flag"] = rel
                changed = True

    if dry:
        print("(dry run — nothing written)")
        return 0
    if not changed:
        print("Nothing to write.")
        return 0

    shutil.copy2(CAT, str(CAT) + ".bak-geo")
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"catalog patched (backup: {CAT.name}.bak-geo)")

    # verify by reloading
    check = json.loads(CAT.read_text(encoding="utf-8"))
    p = find_country(check, "Peru")
    k = find_country(check, "Kosovo")
    print(f"verify: Peru.continent = {p.get('continent') if p else '?'} | "
          f"Kosovo.flag = {k.get('flag') or '(empty)' if k else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
