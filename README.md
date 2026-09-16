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

The full plan is in [efootball-master-league-plan.md](efootball-master-league-plan.md).
Engineering rules and hard-won format knowledge live in [CLAUDE.md](CLAUDE.md).
Testers should start with [PLAYTESTING.md](PLAYTESTING.md).

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
zip with the built app and the world database. Unzip it anywhere, double-click
`Play Master League.bat`, and start a new career. Nothing else is needed to run a career by
entering results yourself. Player photos are not included in the package: with eFootball
installed, `python tools/game_faces.py` decodes the game's own player thumbnails into
`build/game_faces/` and links them by PID. Without that, portraits are generated avatars.
`python tools/game_emblems.py` does the same for club crests: it decodes them from the game's paks
into `build/game_emblems/`, with installed mods such as EvoMod taking precedence, so unlicensed
clubs show the real crests the mod ships. The first run does both.

`tools/make_release.sh <version>` builds that package from a checkout.

## Building and running

Requirements:

- Windows 10/11
- .NET 8 SDK (a newer SDK builds the `net8.0` targets fine)
- To play a career by entering results yourself, nothing else is needed

```bash
dotnet build
dotnet test
```

`Play Master League.bat` builds `ML.App` on first run and launches it from the repo root.

For the full eFootball integration you also need eFootball on Steam, Python 3.11+ with
`numpy` and `pycryptodome`, and, to capture results automatically, a Rust toolchain to build
the stats host in `tools/vendor/efootball-re/` and install it into the game.
See [PLAYTESTING.md](PLAYTESTING.md) for the step-by-step setup.

## What you must supply yourself

These are used by the tools but are **not in this repository**. They are third-party or
game data and are not ours to redistribute. Each location is gitignored, so dropping them in
place will not dirty your checkout.

| Item | Where it goes | Used by |
|---|---|---|
| eFootball install (Steam appid 1665460) | Wherever Steam put it | Everything in Phase 3 and 4 |
| EvoMod | Installed into the game as its author documents | The install order rule below |
| Stats host build (Rust toolchain) | `bash tools/vendor/efootball-re/memprobe/deploy_host.sh` builds it and installs `dxgi.dll` into the game; it writes `<eFootball>\ml_stats\match_*.json` | Result capture (Dashboard pre-fill, Settings → Match data) |
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
```

`python tools/exe_patch.py remove <same spec>` reverses it, and so does Steam's "verify
integrity of game files". The first apply keeps a byte-exact pristine backup.

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
