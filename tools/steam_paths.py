r"""
steam_paths.py — where eFootball actually is on THIS machine.

THE BUG THIS REPLACES. Three tools hard-coded C:\Program Files (x86)\Steam\...: play_match.py's
install target, rebaseline.py's source archive and exe_patch.py's executable. Steam keeps games in
whichever library the user chose — this very machine has a second one on D: — and a game there
could not be compiled to, extracted from, or patched at all. The failure surfaced as a raw
traceback that the app reported as "dt200 is locked".

Steam records its libraries in <steam>/steamapps/libraryfolders.vdf, each with the appids it
holds; that is the truth we read. Order of trust:
  1. ML_EFOOTBALL_DIR — an explicit override (the folder holding eFootball.exe's tree).
  2. the Steam library whose apps block lists appid 1665460.
  3. any library whose steamapps/common/eFootball exists.
  4. the classic default, so nothing that worked before stops working.
No third-party module; standard library only, so it runs under the embedded Python.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

APPID = "1665460"                      # eFootball on Steam
DEFAULT_STEAM = Path(r"C:\Program Files (x86)\Steam")
_GAME_SUBDIR = Path("steamapps") / "common" / "eFootball"


def steam_roots() -> list[Path]:
    """Candidate Steam installs, most trustworthy first. Never raises."""
    roots: list[Path] = []
    try:
        import winreg                                    # Windows only; fine, so is the game
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            v, _ = winreg.QueryValueEx(k, name)
                            if v:
                                roots.append(Path(str(v)))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    roots.append(DEFAULT_STEAM)
    seen, out = set(), []
    for r in roots:
        key = str(r).lower().rstrip("\\/")
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _libraries(vdf: Path) -> list[tuple[Path, set[str]]]:
    """(library path, appids it holds) for every entry in a libraryfolders.vdf. Tolerant of
    Steam's quirks: escaped backslashes, blocks with no apps section, files we cannot parse."""
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    libs: list[tuple[Path, set[str]]] = []
    # Each library is a numbered block: "0" { "path" "..."  "apps" { "appid" "size" ... } }
    for block in re.split(r'\n\s*"\d+"\s*\n\s*\{', text)[1:]:
        m = re.search(r'"path"\s+"((?:[^"\\]|\\.)*)"', block)
        if not m:
            continue
        path = Path(m.group(1).replace("\\\\", "\\"))
        apps = set()
        am = re.search(r'"apps"\s*\{(.*?)\}', block, re.S)
        if am:
            apps = set(re.findall(r'"(\d+)"\s+"\d+"', am.group(1)))
        libs.append((path, apps))
    return libs


def efootball_dir() -> Path:
    r"""The folder Steam installed eFootball into (…\steamapps\common\eFootball)."""
    override = os.environ.get("ML_EFOOTBALL_DIR")
    if override:
        return Path(override)
    # The folder the first run found, or the one the player showed it (tools/first_run.py writes
    # it). Every tool reads it here, so a game outside Steam's lists is chosen once, not per tool.
    chosen = Path(__file__).resolve().parent.parent / "build" / "efootball_dir.txt"
    if chosen.exists():
        picked = Path(chosen.read_text(encoding="utf-8").strip())
        if picked.is_dir():
            return picked
    fallback: Path | None = None
    for root in steam_roots():
        for lib, apps in _libraries(root / "steamapps" / "libraryfolders.vdf"):
            game = lib / _GAME_SUBDIR
            if APPID in apps and game.is_dir():
                return game
            if fallback is None and game.is_dir():
                fallback = game
    if fallback is not None:
        return fallback
    return DEFAULT_STEAM / _GAME_SUBDIR


def game_cpk_dir() -> Path:
    return efootball_dir() / "cpk"


def game_exe() -> Path:
    return efootball_dir() / "eFootball" / "Binaries" / "Win64" / "eFootball.exe"


if __name__ == "__main__":
    d = efootball_dir()
    print(f"eFootball: {d}  ({'found' if d.is_dir() else 'NOT FOUND'})")
    print(f"exe:       {game_exe()}  ({'found' if game_exe().is_file() else 'not found'})")
    for root in steam_roots():
        for lib, apps in _libraries(root / "steamapps" / "libraryfolders.vdf"):
            print(f"library:   {lib}  {'holds eFootball' if APPID in apps else ''}")
