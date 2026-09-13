#!/usr/bin/env python3
r"""
install_stats_host.py — put the match-stats host into eFootball, or take it out.

The host (tools/vendor/efootball-re, GPL-3.0, built from source) is a dxgi.dll the game loads from
the folder beside eFootball.exe. It hooks the game's own stat counters and writes every finished
match to <eFootball>\ml_stats\match_<kick-off>.json, which the app imports (ML.Ingest). It INJECTS
INTO THE RUNNING GAME: keep it to offline play, like every other change this project makes.

  python tools/install_stats_host.py            # install (backs up a dxgi.dll it would replace)
  python tools/install_stats_host.py --remove   # uninstall (puts that backup back)
  python tools/install_stats_host.py --status

What install does, and nothing else
  * copies dxgi.dll into <eFootball>\eFootball\Binaries\Win64\ — the folder next to the exe is the
    one Windows loads from; a copy in the game root is never loaded
  * creates the empty switch files statshook.on and attrhook.on in the game root AND in Win64 (the
    host reads them from both; the game changes its working directory after start)
  * an attrhook.mode file would make the host REWRITE abilities; if one is there it is renamed to
    attrhook.mode.disabled rather than left to act, and said so
Refuses while eFootball.exe is running (the game holds dxgi.dll open).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
HOST = TOOLS / "vendor" / "efootball-re"
SOURCES = [HOST / "bin" / "dxgi.dll",                                   # what the release ships
           HOST / "memprobe" / "host" / "target" / "release" / "dxgi.dll"]  # a local cargo build
BACKUPS = REPO / "build" / "backups" / "dxgi"
SWITCHES = ("statshook.on", "attrhook.on")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def game_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq eFootball.exe"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return "efootball.exe" in out.lower()


def paths() -> tuple[Path, Path]:
    sys.path.insert(0, str(TOOLS))
    from steam_paths import efootball_dir
    game = efootball_dir()
    return game, game / "eFootball" / "Binaries" / "Win64"


def status() -> int:
    game, win64 = paths()
    src = next((s for s in SOURCES if s.exists()), None)
    dst = win64 / "dxgi.dll"
    print(f"eFootball:     {game}{'' if game.exists() else '  (NOT FOUND)'}")
    print(f"host to ship:  {src or 'none built — cargo build --release in memprobe/host'}")
    if dst.exists():
        ours = src is not None and sha(dst) == sha(src)
        print(f"installed:     {dst}  ({'this build' if ours else 'a DIFFERENT dxgi.dll'})")
    else:
        print("installed:     no")
    for d in (game, win64):
        print(f"switches in {d.name}: " + ", ".join(f"{s}={'on' if (d / s).exists() else 'off'}" for s in SWITCHES))
    stats = game / "ml_stats"
    n = len(list(stats.glob("match_*.json"))) if stats.exists() else 0
    print(f"exports:       {n} finished match(es) in {stats}")
    return 0


def install() -> int:
    game, win64 = paths()
    if not win64.exists():
        print(f"REFUSED: {win64} not found — is eFootball installed there?")
        return 1
    if game_running():
        print("REFUSED: eFootball is running — it holds dxgi.dll open. Quit the game completely first.")
        return 1
    src = next((s for s in SOURCES if s.exists()), None)
    if src is None:
        print("REFUSED: no dxgi.dll to install — build it: cargo build --release in "
              "tools/vendor/efootball-re/memprobe/host")
        return 1
    dst = win64 / "dxgi.dll"
    if dst.exists() and sha(dst) != sha(src):
        BACKUPS.mkdir(parents=True, exist_ok=True)
        original = BACKUPS / "dxgi.dll.original"
        keep = original if not original.exists() else BACKUPS / f"dxgi.dll.replaced_{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(dst, keep)
        print(f"backed up the dxgi.dll it replaces -> {keep}")
    shutil.copy2(src, dst)
    print(f"installed {dst}")
    for d in (game, win64):
        for s in SWITCHES:
            (d / s).touch()
        mode = d / "attrhook.mode"
        if mode.exists():
            mode.rename(d / "attrhook.mode.disabled")
            print(f"renamed {mode} -> attrhook.mode.disabled (it would make the host rewrite abilities)")
    print("switches statshook.on + attrhook.on set in the game root and Win64")
    print("Play a match offline; it is exported ~15 s after you return to the main menu.")
    return 0


def remove() -> int:
    game, win64 = paths()
    if game_running():
        print("REFUSED: eFootball is running — quit it completely first.")
        return 1
    dst = win64 / "dxgi.dll"
    original = BACKUPS / "dxgi.dll.original"
    if dst.exists():
        dst.unlink()
        print(f"removed {dst}")
    if original.exists():
        shutil.copy2(original, dst)
        print(f"put back the dxgi.dll that was there before -> {dst}")
    for d in (game, win64):
        for s in SWITCHES:
            if (d / s).exists():
                (d / s).unlink()
    print("switch files removed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--remove", action="store_true")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--game-dir", default=None,
                    help="the eFootball folder (default: the one the first run found, else Steam's lists)")
    args = ap.parse_args()
    if args.game_dir:
        import os
        os.environ["ML_EFOOTBALL_DIR"] = args.game_dir     # steam_paths honours it first
    return status() if args.status else remove() if args.remove else install()


if __name__ == "__main__":
    raise SystemExit(main())
