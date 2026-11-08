# Running on Linux (Steam + Proton)

eFootball has no Linux build. Steam runs the Windows game through Proton, from an ordinary Steam
library, so the game folder looks exactly as it does on Windows. Everything the app does to the
game is file I/O on that folder (world build, faces, crests, Play Match's dt200 patch, the stats
host's `dxgi.dll`), and all of it works natively on Linux. Nothing runs inside Wine except the game.

Verified 2026-11-07 on Arch Linux with Proton Experimental and eFootball build 25359256:
world build, faces, crests, a Play Match compile with the byte-exact gates, the app's UI, and the
test suite.

## Setup

```bash
./setup-linux.sh          # once: Python venv (.venv/) with the tools' packages, builds the app
./play-master-league.sh   # every time: the Linux counterpart of "Play Master League.bat"
```

Needs `python3` (3.11+) and the .NET SDK (8 or newer). The app targets `net8.0` but rolls forward
to a newer runtime when 8 is not installed, which is the normal case on rolling distros.

**Install an emoji font.** The UI's icons are emoji, which Windows draws with Segoe UI Emoji.
Without one, every icon is an empty box. The setup script warns you if one is missing:

| Distro | Package |
|---|---|
| Arch | `noto-fonts-emoji` |
| Debian / Ubuntu | `fonts-noto-color-emoji` |
| Fedora | `google-noto-color-emoji-fonts` |

## Where things are

`tools/steam_paths.py` finds the game. Run it to see what it found:

```bash
.venv/bin/python tools/steam_paths.py
```

| | Path |
|---|---|
| Steam (native) | `~/.local/share/Steam` (also `~/.steam/steam`, the Flatpak and the Snap) |
| eFootball | `<library>/steamapps/common/eFootball` |
| Proton prefix (the game's `C:`) | `<library>/steamapps/compatdata/1665460/pfx` |
| Match exports | `<library>/steamapps/common/eFootball/ml_stats/match_*.json` |

Steam's `libraryfolders.vdf` does not always list appid 1665460 under the library that holds it,
so the resolver also accepts any library where `steamapps/common/eFootball` exists. To point it
somewhere else, set `ML_EFOOTBALL_DIR`, or choose the folder in New Career; the choice is
remembered in `build/efootball_dir.txt`.

The app uses `.venv/bin/python` automatically. Set `ML_PYTHON` to use another interpreter.

## The match-stats host under Proton

Settings → Install stats host puts the same Windows `dxgi.dll` beside `eFootball.exe`. This works
under Proton because:

- Proton already loads `dxgi` as a native DLL (DXVK's), and native DLLs are searched in the exe's
  folder first, so ours loads.
- The host chains to `C:\Windows\System32\dxgi.dll`, which in the prefix is DXVK's.
- The host finds `ml_stats` from the exe's own path. Wine maps that path back to the real game
  folder, which is where the app watches.

If no `ml_stats` folder appears after you finish a match, set the game's Steam launch options to

```
WINEDLLOVERRIDES="dxgi=n,b" %command%
```

and don't set `PROTON_USE_WINED3D=1`, which replaces DXVK's dxgi with Wine's built-in one.

## Close the game before Play Match: Linux will not stop you

On Windows, the running game holds `dt200_console_all.cpk` and `eFootball.exe` open, so a write
fails with "locked". Linux has no mandatory locks. The write would succeed under the running game,
and the game would then read an archive that changed beneath it. So every tool that writes into
the game folder (`play_match.py --install`, `ml_deploy.py`, `gameplay_tune.py`, `exe_patch.py`,
`install_stats_host.py`) checks for a running `eFootball.exe` first and refuses
(`steam_paths.refuse_if_game_running`). Quit the game completely, so that Steam shows it as
stopped, before you press Play Match.

## What stays Windows-only

The reverse-engineering tools that attach to the live process (`live_patch.py`, `live_inject.py`,
`find_aes_key_live.py`, `fm_mem.py`) use Win32 `ReadProcessMemory`. They are research tools that
the app never calls. On Linux they would have to run inside the game's prefix, for example
`protontricks-launch --appid 1665460 python.exe …` with a Windows Python. Several other research
scripts pin paths from the owner's Windows machine (`C:\Users\…`) and are not portable as written.
Rebuilding the stats host from source needs a Windows Rust target. The prebuilt
`tools/vendor/efootball-re/bin/dxgi.dll` does not.

## The offline exe

`tools/exe_patch.py` patches `eFootball.exe` with plain file I/O, so it works the same on Linux.
Run it with `.venv/bin/python` and the game closed (it refuses otherwise). The offline spec finds
its string by search, so game updates that move the string no longer break it. See "Playing
offline" in the [README](../README.md#playing-offline).
