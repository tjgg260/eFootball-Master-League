#!/usr/bin/env python3
r"""
game_crests.py — club crests from eFootball's own UI symbols.

The game ships every club's emblem inside pak\pc1000_console_win (the same UE IoStore container
the player heads come from): ui/Data/Symbol/Emblem/e_<team id>_<variant>.uasset, named by the
Team.bin id the world already stores as teams.base_team_id. 2,934 files, 952 clubs, BC7 at up to
512x512. Licensed clubs carry the real crest (variant `_r`); the rest carry the crest the game
invented for them (`_f`) — Albacete BN's castle shield is Konami's, not a placeholder of ours.
Mono cut-outs (`_r_b`, `_r_w`) are never chosen: they are one-colour stencils for dark and light
backgrounds, not the crest.

    e_000101_r_ll   Arsenal, licensed, 512x512     <- preferred
    e_004302_f_ll   Albacete BN, unlicensed, 512x512

BC7 needs Pillow — unlike the DXT5 player heads, there is no numpy fallback for it, so without
Pillow this writes nothing and says so (the release bundles Pillow for exactly this).

What it writes
    build/game_crests/<team id>.png   Konami's art: build/ is gitignored, the release ships none of it
    teams.logo_path                   'build/game_crests/<id>.png', for every row of that club,
                                      career copies included (they carry base_team_id)
    game_catalog.json  "logo"         the same path, which is where the New Career picker reads it

    python tools/game_crests.py --dry     # resolve and report; decode nothing, write nothing
    python tools/game_crests.py           # decode what is missing, write the paths
    python tools/game_crests.py --pak <dir> --db <file> --catalog <file>

Idempotent: a PNG already on disk is not decoded again, and a row whose path is already right is
not rewritten. Close the app first — it holds the database open.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "efootball-player-tool"))

import game_faces  # the CNG AES shim, the texture decoder and the Steam paths, already proven
import iostore  # noqa: E402

CONTAINER = "pc1000_console_win.utoc"
EMBLEM = re.compile(r"/Symbol/Emblem/e_(\d+)(_[a-z_]+)\.uasset$")
# Real crest first, then the game's invented one, largest size first within each.
VARIANTS = ("_r_ll", "_r_l", "_r", "_f_ll", "_f_l", "_f")
OUT = REPO / "build" / "game_crests"
DB = REPO / "build" / "game_world.db"
CATALOG = REPO / "build" / "game_catalog.json"


def emblem_paths(container: iostore.Container) -> dict[int, str]:
    """Team id -> the best emblem asset for it."""
    by_id: dict[int, dict[str, str]] = {}
    for path in container.paths:
        m = EMBLEM.search(path)
        if m:
            by_id.setdefault(int(m.group(1)), {})[m.group(2)] = path
    best = {}
    for team_id, variants in by_id.items():
        pick = next((variants[v] for v in VARIANTS if v in variants), None)
        if pick is not None:
            best[team_id] = pick
    return best


def catalog_teams(catalog: dict):
    """Every team entry of a v3 catalog, so the picker's logo can be set on it."""
    for country in catalog.get("countries", []):
        for league in country.get("leagues", []):
            yield from league.get("teams", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--pak", default=None, help="eFootball\\pak (default: found via Steam)")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--catalog", default=None, help="default: game_catalog.json beside --db")
    args = ap.parse_args()

    pak = Path(args.pak) if args.pak else game_faces.default_pak()
    utoc = pak / CONTAINER
    if not utoc.exists():
        sys.exit(f"{utoc} not found — pass --pak <eFootball>\\pak")

    t0 = time.time()
    container = iostore.Container(str(utoc))
    emblems = emblem_paths(container)
    print(f"{CONTAINER}: {len(emblems):,} club emblems ({time.time() - t0:.1f}s; "
          f"AES via {game_faces.AES_BACKEND}, images via {'Pillow' if game_faces.HAVE_PIL else 'numpy'})")
    if not game_faces.HAVE_PIL:
        print("Club crests are BC7, which needs Pillow (pip install pillow); nothing decoded.")
        return 2

    db = Path(args.db)
    catalog_path = Path(args.catalog) if args.catalog else db.parent / CATALOG.name
    con = sqlite3.connect(db)
    teams = con.execute("SELECT id, game_team_id, base_team_id, name, logo_path FROM teams").fetchall()

    # base_team_id is the Team.bin id a career copy was made from; game_team_id is it for the world's own.
    resolved: dict[int, int] = {}
    for row_id, game_team_id, base_team_id, _name, _logo in teams:
        for candidate in (base_team_id, game_team_id):
            if candidate in emblems:
                resolved[row_id] = candidate
                break
    clubs = set(resolved.values())
    print(f"teams {len(teams):,}: {len(resolved):,} rows resolve to {len(clubs):,} club crests")

    missing = sorted(c for c in clubs if not (OUT / f"{c}.png").exists())
    updates = [(f"build/game_crests/{resolved[row_id]}.png" if row_id in resolved else None, row_id)
               for row_id, _g, _b, _n, logo in teams
               if (f"build/game_crests/{resolved[row_id]}.png" if row_id in resolved else None) != logo]
    print(f"crests to decode {len(missing):,}; team rows to update {len(updates):,}")
    if args.dry:
        print("--dry: nothing decoded, nothing written.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    t0 = time.time()
    for i, team_id in enumerate(missing, 1):
        try:
            if not game_faces.decode(container, emblems[team_id], OUT / f"{team_id}.png"):
                failed.append(team_id)
        except Exception as ex:  # noqa: BLE001 — one bad texture never stops the rest
            failed.append(team_id)
            if len(failed) <= 5:
                print(f"   {team_id}: {ex!r}")
        if i % 200 == 0:
            print(f"   decoded {i:,}/{len(missing):,} ({time.time() - t0:.0f}s)", flush=True)
    print(f"decoded {len(missing) - len(failed):,} PNGs into build/game_crests "
          f"({time.time() - t0:.0f}s), {len(failed)} could not be decoded")

    if failed:
        bad = set(failed)
        updates = [(None if path and int(Path(path).stem) in bad else path, row_id) for path, row_id in updates]
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", updates)
    con.commit()
    print(f"teams.logo_path written for {sum(1 for p, _ in updates if p):,} rows")

    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        bad = set(failed)
        wrote = 0
        for team in catalog_teams(catalog):
            team_id = team.get("team_id")
            if team_id in clubs and team_id not in bad:
                path = f"build/game_crests/{team_id}.png"
                if team.get("logo") != path:
                    team["logo"] = path
                    wrote += 1
        if wrote:
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{catalog_path.name}: logo set on {wrote:,} clubs (the New Career picker reads it)")
    else:
        print(f"{catalog_path} not found — picker logos unchanged")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
