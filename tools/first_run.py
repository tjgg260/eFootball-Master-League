#!/usr/bin/env python3
r"""
first_run.py — everything a download needs before its first career, from the player's own eFootball.

  1. find eFootball: --game-dir, else the folder chosen last time (build/efootball_dir.txt), else
     Steam's own library list (steam_paths.py)
  2. keep a copy of the dt200 AS INSTALLED — the base every Play Match patches from, taken before the
     app changes anything. Ruling 2026-09-13: it does not have to be untouched by Konami or EvoMod;
     it has to be the state before OUR changes, so a later match can always be built from it.
  3. build the world:   build/game_world.db + build/game_catalog.json   (tools/game_world.py)
  4. the faces:         build/game_faces/<PID>.png                      (tools/game_faces.py)

Nothing already there is rebuilt unless asked: a world holds your careers, so --rebuild-world is
the only way this replaces one; --rebase takes a fresh copy of the installed dt200 (after a Konami
update) and re-unpacks it.

Exit codes: 0 ready · 3 eFootball not found (the app then asks for the folder) · 1 anything else.
The app reads the lines this prints as its progress.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
BUILD = REPO / "build"
BASE_CPK = REPO / "dt200_console_all.cpk"       # play_match.BASE_CPK
TREE_BASE = BUILD / "tree_base"                  # play_match.TREE_BASE
WORLD = BUILD / "game_world.db"
DIR_FILE = BUILD / "efootball_dir.txt"           # steam_paths reads it too
NOT_FOUND = 3


def say(msg: str) -> None:
    print(msg, flush=True)


def game_root(candidate: Path) -> Path | None:
    """The eFootball folder, accepting a pick one level off: the cpk folder, or the exe's folder."""
    for g in [candidate, *list(candidate.parents)[:3]]:
        if (g / "cpk" / "dt200_console_all.cpk").exists():
            return g
    return None


def find_game(arg: str | None) -> Path | None:
    candidates: list[Path] = []
    if arg:
        candidates.append(Path(arg))
    if os.environ.get("ML_EFOOTBALL_DIR"):
        candidates.append(Path(os.environ["ML_EFOOTBALL_DIR"]))
    if DIR_FILE.exists():
        candidates.append(Path(DIR_FILE.read_text(encoding="utf-8").strip()))
    sys.path.insert(0, str(TOOLS))
    from steam_paths import efootball_dir
    candidates.append(efootball_dir())
    for c in candidates:
        g = game_root(c)
        if g is not None:
            return g
    return None


def run(script: str, *args: str) -> int:
    return subprocess.run([sys.executable, str(TOOLS / script), *args]).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game-dir", default=None, help="the folder eFootball is installed in")
    ap.add_argument("--rebase", action="store_true", help="take a fresh copy of the installed dt200")
    ap.add_argument("--rebuild-world", action="store_true", help="rebuild game_world.db (its careers are lost)")
    ap.add_argument("--skip-faces", action="store_true")
    args = ap.parse_args()

    game = find_game(args.game_dir)
    if game is None:
        say("NEED_GAME_DIR: couldn't find eFootball — choose the folder it is installed in.")
        return NOT_FOUND
    BUILD.mkdir(exist_ok=True)
    DIR_FILE.write_text(str(game), encoding="utf-8")
    os.environ["ML_EFOOTBALL_DIR"] = str(game)
    say(f"eFootball: {game}")

    installed = game / "cpk" / "dt200_console_all.cpk"
    if args.rebase or not BASE_CPK.exists():
        say("Keeping a copy of your dt200 — every match is built from it…")
        tmp = BASE_CPK.with_suffix(".cpk.copying")
        shutil.copy2(installed, tmp)
        os.replace(tmp, BASE_CPK)
        if TREE_BASE.exists():
            shutil.rmtree(TREE_BASE)
    if not TREE_BASE.exists():
        say("Unpacking it…")
        sys.path.insert(0, str(TOOLS))
        import cpk_patch
        tmp = BUILD / "tree_base.unpacking"
        if tmp.exists():
            shutil.rmtree(tmp)
        n = cpk_patch.extract(BASE_CPK, tmp)
        os.replace(tmp, TREE_BASE)
        say(f"  {n:,} game files")

    if args.rebuild_world or not WORLD.exists():
        say("Reading your players, clubs and leagues…")
        if run("game_world.py", "--dt200", str(BASE_CPK), "--out", str(WORLD), "--replace") != 0:
            say("ERROR: the world could not be built from this eFootball — see the lines above.")
            return 1
    else:
        say("World already built — keeping it (and its careers).")

    if not args.skip_faces:
        say("Taking the player faces from the game…")
        if run("game_faces.py", "--db", str(WORLD), "--pak", str(game / "pak")) != 0:
            say("Faces could not be read this time — the careers work without them.")

    say("WORLD_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
