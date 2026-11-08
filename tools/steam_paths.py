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

LINUX (Steam + Proton). The game is the same Windows build, run by Proton from an ordinary Steam
library, so the layout under steamapps/common/eFootball is identical. Only the Steam roots differ:
~/.local/share/Steam (native), ~/.steam/steam and ~/.steam/root (symlinks to it), the Flatpak and
the Snap. The game's Wine prefix — its C: drive, where the save data lives — is
<library>/steamapps/compatdata/1665460/pfx (proton_prefix()).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APPID = "1665460"                      # eFootball on Steam
IS_WINDOWS = sys.platform == "win32"
DEFAULT_STEAM = (Path(r"C:\Program Files (x86)\Steam") if IS_WINDOWS
                 else Path.home() / ".local" / "share" / "Steam")
# Where Linux Steam keeps itself, most common first. ~/.steam/* are symlinks Steam maintains to
# whichever of the others is real; the dedupe below resolves them so each is read once.
_LINUX_STEAM = (
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steam" / "steam",
    Path.home() / ".steam" / "root",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    Path.home() / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
)
_GAME_SUBDIR = Path("steamapps") / "common" / "eFootball"


def steam_roots() -> list[Path]:
    """Candidate Steam installs, most trustworthy first. Never raises."""
    roots: list[Path] = []
    if not IS_WINDOWS:
        roots.extend(r for r in _LINUX_STEAM if (r / "steamapps").is_dir())
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
        if IS_WINDOWS:
            key = str(r).lower().rstrip("\\/")
        else:
            try:
                key = str(r.resolve())
            except OSError:
                key = str(r)
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


def proton_prefix() -> Path | None:
    """Linux only: the Wine prefix Proton runs eFootball in (…/compatdata/1665460/pfx), or None.
    It sits in the same library as the game; Steam creates it on the first launch."""
    if IS_WINDOWS:
        return None
    game = efootball_dir()
    # <library>/steamapps/common/eFootball -> <library>/steamapps/compatdata/1665460/pfx
    candidates = [game.parent.parent / "compatdata" / APPID / "pfx"]
    candidates += [root / "steamapps" / "compatdata" / APPID / "pfx" for root in steam_roots()]
    for c in candidates:
        if (c / "drive_c").is_dir():
            return c
    return None


def game_running() -> bool:
    """Is eFootball.exe running right now? Never raises; False when it cannot tell.

    Windows: tasklist. Linux: the Wine process Proton starts carries the exe as its argv[0]
    (S:\\steamapps\\common\\eFootball\\…\\eFootball.exe). Only argv[0] is matched, so a tool
    that was merely handed the exe's path as an argument is not mistaken for the game."""
    if IS_WINDOWS:
        import subprocess
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq eFootball.exe"],
                                 capture_output=True, text=True).stdout
        except OSError:
            return False
        return "efootball.exe" in out.lower()
    try:
        procs = list(Path("/proc").iterdir())
    except OSError:
        return False
    for proc in procs:
        if not proc.name.isdigit():
            continue
        try:
            argv0 = (proc / "cmdline").read_bytes().split(b"\0", 1)[0]
        except OSError:
            continue
        name = argv0.replace(b"\\", b"/").rsplit(b"/", 1)[-1].lower()
        if name == b"efootball.exe":
            return True
    return False


def refuse_if_game_running(what: str) -> None:
    """Exit before writing into the game folder while the game is up.

    On Windows the game's open handle makes such a write fail with PermissionError, which the
    tools already turn into "close eFootball". Linux has no mandatory locks: the write SUCCEEDS
    under the running game, which then reads a CPK that changed beneath it. So the check that
    Windows does for us is done here, by hand, before anything is touched."""
    if not IS_WINDOWS and game_running():
        sys.exit(f"\n{what}: eFootball is running. Quit the game completely (Steam shows it "
                 "as stopped), then run again.")


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
    print(f"running:   {'yes' if game_running() else 'no'}")
    if not IS_WINDOWS:
        pfx = proton_prefix()
        print(f"proton:    {pfx if pfx else 'no prefix yet (launch the game once from Steam)'}")
