# eFootball Master League

A companion app that restores a persistent Master League to eFootball 2027 (PC / Steam).

You run the club: squad, tactics, transfers, board, staff, youth. The app simulates the rest
of the league and you play only *your* fixture, in eFootball if you want, or by entering the
score. Transfers and player progression are written back into the game database, so the squads
you manage are the squads you actually play with.

**The app's SQLite database is the single source of truth. The game's files are a render
target.** Nothing reads game state back in as authority after the initial seed.

> Early build. The management sim is solid; automatic capture from eFootball is experimental.
> Keep modified game databases to **offline play**. Do not take an edited local database near
> Dream Team or any online mode.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Writeback proven in-game | Passed 2026-08-19 ([docs/phase0-checklist.md](docs/phase0-checklist.md)) |
| 1 | Data foundation (SQLite seed, real schemas) | Schemas recovered; seed tooling in `tools/` |
| 2 | League engine (`ML.Core`) | Built and tested |
| 3 | Result capture from efootball-re's in-game stats host (`ML.Ingest`) | Built; pre-fills score, scorers, ratings and stats |
| 4 | Writeback (`ML.Sync`, diff against applied state) | Core mechanism proven; diff model in progress |
| 5 | Polish | Not started |

## Documentation

| | |
|---|---|
| **[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)** | Install, build your world, take a job, play your first matchday. **Start here.** |
| **[docs/FEATURES.md](docs/FEATURES.md)** | What the app does, at a glance |
| [docs/LINUX.md](docs/LINUX.md) | Running on Linux with Steam + Proton |
| **[docs/MANUAL.md](docs/MANUAL.md)** | The full manual: every screen, every setting, the rules the engine plays by, and troubleshooting |
| [PLAYTESTING.md](PLAYTESTING.md) | What we'd like tested, and how to report it |

The full plan is in [efootball-master-league-plan.md](efootball-master-league-plan.md).
Engineering rules and hard-won format knowledge live in [CLAUDE.md](CLAUDE.md).

## Layout

| Path | Role |
|---|---|
| `src/ML.Core` | League engine. Pure C#, no I/O, no package references, so it stays testable without the game |
| `src/ML.Data` | SQLite + Dapper persistence |
| `src/ML.Ingest` | Match exports from efootball-re's stats host: parser, folder watcher, PID linking to the fixture, player ratings (port of its `rating.py`) |
| `src/ML.Sync` | Diff and writeback against the last applied state |
| `src/ML.App` | Avalonia desktop app. **This is the app.** |
| `src/ML.Web` | Older Blazor UI. Frozen and deprecated; do not record results there |
| `tests/ML.Core.Tests` | Engine tests |
| `tools/` | Python pipeline: world build, imports, format decoders, and the proven writeback (`ml_swap.py`, `ml_deploy.py`) |
| `tools/vendor/sider/` | Vendored Sider file-format code (see below) |
| `tools/vendor/efootball-player-tool/` | Vendored CPK reader/patcher from the eFootball Player Editor, used through `tools/cpk_patch.py` |
| `tools/data/` | Decoded `dt270` gameplay schema and the named realism tunings and patches it drives |
| `data/` | Hand-made identity rulings and adjudicated merges, re-applied on every world rebuild |
| `docs/` | Format notes, decisions, specs, the exe gameplay map and the per-player stats runbook |
| `samples/` | Schema notes derived from real exports. Real exports are not committed |
| `assets/` | Competition and club artwork used by the app |

## Download and play

The [Releases page](https://github.com/tjgg260/eFootball-Master-League/releases) carries a
zip with the built app and an embedded Python. Unzip it anywhere, double-click
`Play Master League.bat`, and start a new career.

**No world ships with it.** The first New Career builds one out of your own eFootball install
(`tools/first_run.py`): your clubs, leagues, players and squads from dt200, the club crests from
the game's paks with installed mods such as EvoMod taking precedence, and the player photos from
the game's own thumbnails. It takes about a minute, once, and it never writes to the game. A
player without eFootball gets generated badges and avatars instead.

The world lands in `build/game_world.db` beside the app, and your careers live in it — so keep
that file if you want to keep a save.

`tools/make_release.sh <version>` builds that package from a checkout.

## Building and running

Requirements:

- Windows 10/11, or Linux with eFootball run by Steam's Proton ([docs/LINUX.md](docs/LINUX.md))
- .NET 8 SDK (a newer SDK builds the `net8.0` targets fine)
- To play a career by entering results yourself, nothing else is needed

```bash
dotnet build
dotnet test
```

`Play Master League.bat` builds `ML.App` on first run and launches it from the repo root. On Linux,
run `./setup-linux.sh` once (Python venv + build) and then `./play-master-league.sh`; see
[docs/LINUX.md](docs/LINUX.md).

For the full eFootball integration you also need eFootball on Steam, and — **only if you run from
a source checkout rather than the download** — Python 3.11+ with `Pillow`, `numpy` and
`pycryptodome`. The release brings its own Python and the built stats host, so a downloader
installs nothing. A Rust toolchain is needed only to rebuild that host from
`tools/vendor/efootball-re/memprobe/host/`; the prebuilt `dxgi.dll` ships beside its source and
Settings installs it for you. See [PLAYTESTING.md](PLAYTESTING.md) for the step-by-step setup.

## What you must supply yourself

These are used by the tools but are **not in this repository**. They are third-party or
game data and are not ours to redistribute. Each location is gitignored, so dropping them in
place will not dirty your checkout.

| Item | Where it goes | Used by |
|---|---|---|
| eFootball install (Steam appid 1665460) | Wherever Steam put it | Everything in Phase 3 and 4 |
| EvoMod | Installed into the game as its author documents | The install order rule below |
| Stats host **rebuild** (Rust toolchain) — optional | The built `dxgi.dll` is committed at `tools/vendor/efootball-re/bin/` and ships in the release; Settings → Install stats host puts it in the game. Rebuild only to change it: `bash tools/vendor/efootball-re/memprobe/deploy_host.sh` | Result capture (Dashboard pre-fill, Settings → Match data) |
| Your own game exports, FM exports, face packs | Repo root or `samples/` | The `tools/` import pipeline |

No CPK tooling has to be supplied. The tools read and patch eFootball's `.cpk` archives directly
through the eFootball Player Editor's
container code, vendored in `tools/vendor/efootball-player-tool/`. CRI File System Tools
(`cpkmakec.exe`), the eFootball WESYS Unzlib Tool and `cricodecs` are no longer used. To pull the
game tables out of dt200 into a tree:

```bash
python tools/cpk_patch.py extract "<eFootball>/cpk/dt200_console_all.cpk" bins
```

The Player Editor itself is optional. Use it to edit players by hand, or to export CSVs from it.

## Playing offline

The game must be offline for a modified database to be safe. The "offline exe" used for
Master League play is your own `eFootball.exe` with two bytes changed: the matchmaking host
`pes22-game.cs.konami.net` becomes `pes99-game.cs.konami.net`, so the client cannot reach
Konami and starts straight into offline play. Gameplay code is untouched. We do not
redistribute the executable; apply the change to your own copy, with the game closed:

```bash
python tools/exe_patch.py apply tools/data/patches/offline-no-gameplay-change.json
python tools/exe_patch.py status    # the spec reads "applied"
python tools/exe_patch.py diff      # exactly 2 bytes differ from the pristine copy
```

(On Linux, run these with `.venv/bin/python`. See [Linux](#linux-steam--proton) below.)

`python tools/exe_patch.py remove <same spec>` reverses it, and so does Steam's "verify
integrity of game files". The first apply keeps a byte-exact pristine backup, about 370 MB, at
`~/Backups/eFootball/eFootball.exe.PRISTINE`. `restore` copies it back.

**The patch finds the string; it does not trust an address.** The spec used to pin the string at
a fixed RVA (`0x6e6fae3`). Build 25359256 moved it to `0x6f18853`, so `apply` found other bytes
there and aborted without writing anything. The spec now carries a `"find"` text
(`pes22-game.cs.konami.net`, with `find_offset` 3), and `exe_patch.py` locates it by searching
the exe in its shipped or patched form. It must occur exactly once, or nothing is written. A
Konami update that moves the string no longer breaks the patch. One that removes or duplicates
the string makes it refuse, and then the spec needs a look. Any exe spec may use `find`. Its
`module_offset` is kept, at the current build's address, for the tools that read it directly
(`live_patch.py`, `cave_*`).

Verified 2026-11-07 on build 25359256 under Linux/Proton. On a copy of the exe, `apply` renamed
the host, a second `apply` was a no-op, and `remove` gave back a byte-identical exe. It was then
applied to the installed game, and `diff` showed the 2 bytes. Whether the game starts with it
under Proton has not been checked yet: Denuvo may refuse a modified exe, and if it does, run
`remove` or `restore`.

## Linux (Steam + Proton)

eFootball has no Linux build. Steam runs the Windows game through Proton, from an ordinary Steam
library, so the game folder is laid out exactly as on Windows. Everything the app does to the game
is file I/O on that folder, and all of it runs natively on Linux. The full guide is
[docs/LINUX.md](docs/LINUX.md).

```bash
./setup-linux.sh          # once: Python venv (.venv/) from requirements.txt, builds the app
./play-master-league.sh   # every time: the Linux counterpart of "Play Master League.bat"
```

You need `python3` 3.11+, the .NET SDK 8 or newer, and **an emoji font** (`noto-fonts-emoji` on
Arch, `fonts-noto-color-emoji` on Debian/Ubuntu). The UI's icons are emoji; without the font they
are empty boxes, and the setup script warns about it.

What differs from Windows, and how it is handled:

| | Windows | Linux |
|---|---|---|
| Finding the game | registry + `libraryfolders.vdf` | `~/.local/share/Steam`, `~/.steam`, Flatpak, Snap + `libraryfolders.vdf`, then any library holding `steamapps/common/eFootball` (`tools/steam_paths.py`) |
| Game's `C:` drive | — | Proton prefix `<library>/steamapps/compatdata/1665460/pfx` (`steam_paths.proton_prefix()`) |
| Python the app runs | the download's embedded `python\` | the repo's `.venv/`, else `python3` on PATH; `ML_PYTHON` overrides |
| .NET runtime | 8 | `RollForward=Major`: the newest installed when 8 is missing (Arch ships only 9/10) |
| Writing while the game runs | the game's file locks make it fail | **no locks, so the write would land under the running game.** Every tool that writes into the game folder checks for `eFootball.exe` and refuses (`steam_paths.refuse_if_game_running`). Quit the game before Play Match. |
| Sidebar icons | Segoe MDL2 glyphs | emoji twins (Segoe is Windows-only) |
| Stats host `dxgi.dll` | loads beside the exe | the same file; Proton loads native `dxgi` from the exe's folder first. If no `ml_stats` appears after a match, set launch options to `WINEDLLOVERRIDES="dxgi=n,b" %command%` |

Verified 2026-11-07 on Arch Linux, Proton Experimental, eFootball build 25359256. Tested: the
first-run world build (22,903 players, 666 clubs, 28 leagues), faces and crests, a compile-only
Play Match through the byte-exact gates, the app's UI, the test suite, and the offline patch
above. Then in-game, 2026-11-08: the game starts with the offline patch, Play Match installs
dt200 and the fixture is played, and the stats host loads under Proton with no launch options and
writes `ml_stats/match_*.json`.

**Build 25359256 broke the stats host's squad lookup, and that is fixed.** Its exports carried
scores and counters but no player ids (`teamobj: null`; in `sider_rust.log`:
`[SIG] 问题: team_obj: 0 处字节命中`). Without ids the app cannot link an export to the fixture
("that export has no player ids"). The `team_obj` signature in
`tools/vendor/efootball-re/memprobe/host/signatures.txt` has been updated for the new code shape,
the host's offline signature test was re-pinned to this build and passes, and the rebuilt
`dxgi.dll` is in `tools/vendor/efootball-re/bin/`. Exports written before the fix stay without
ids: enter those results by hand.

Rebuilding the stats host works on Linux too, with no Windows SDK:
`bash tools/vendor/efootball-re/memprobe/build_host_linux.sh [--test <pristine eFootball.exe>]`
(needs `rustup target add x86_64-pc-windows-gnu`, `cargo install cargo-zigbuild` and zig). It
links with zig instead of MSVC, so `memprobe/host/dxgi-gnu.def` pins the export table.

Windows-only still: the research tools that attach to the live process (`live_patch.py`,
`live_inject.py`, `find_aes_key_live.py`, `fm_mem.py`), the research scripts that pin the
original author's `C:\Users\…` paths. The app uses none of them.

## Operational rules

- Install order after any Konami update: **Konami patch, then EvoMod, then your CSV.** Always.
- Back up `Player.bin` before every apply. The tools take their own backup every time.
- No write happens without a byte-exact round-trip proof first. If the tools cannot rebuild
  the unmodified source file byte for byte, nothing is written. That failure is by design.
- `PlayerAssignment.bin` is a positional format. A transfer swaps which player occupies a
  record; it never moves a record or edits `TeamID`.
- Never rebuild or re-serialise the CPK. A deploy patches only the files that changed: in place
  when they fit, otherwise moved with only their TOC row rewritten. Every other byte of the
  archive is verified identical before anything is written.

## Licence

GPL-3.0. See [LICENSE](LICENSE).

This is deliberate: `tools/vendor/sider/` carries file-format and WESYS cipher code from
[Efootball-Sider](https://github.com/Master-Antonio/Efootball-Sider) (GPL-3.0), and
`tools/ml_apply.py` links against it, which makes this project a derivative work. Details in
[tools/vendor/sider/VENDOR.md](tools/vendor/sider/VENDOR.md). Do not add code under an
incompatible licence.

`tools/vendor/efootball-player-tool/` is the eFootball Player Editor's CPK and IoStore code,
included here under GPL-3.0 by its author. Details in
[tools/vendor/efootball-player-tool/VENDOR.md](tools/vendor/efootball-player-tool/VENDOR.md).

`tools/vendor/efootball-re/` is the in-game stats host that writes the match exports. It is built
on `rust_sider` from Efootball-Sider (GPL-3.0). Details and install steps in
[tools/vendor/efootball-re/VENDOR.md](tools/vendor/efootball-re/VENDOR.md).

Sider's `dxgi.dll` runtime is not redistributed here. eFootball is a Konami product; this
project is not affiliated with or endorsed by Konami.
