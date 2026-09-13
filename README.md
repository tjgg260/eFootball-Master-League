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
| 3 | Screenshot / video capture and OCR | Experimental |
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
| `src/ML.Ingest` | Steam screenshot watcher, region calibration, Tesseract OCR, OBS capture |
| `src/ML.Sync` | Diff and writeback against the last applied state |
| `src/ML.App` | Avalonia desktop app. **This is the app.** |
| `src/ML.Web` | Older Blazor UI. Frozen and deprecated; do not record results there |
| `tests/ML.Core.Tests` | Engine tests |
| `tools/` | Python pipeline: world build, imports, format decoders, and the proven writeback (`ml_swap.py`, `ml_deploy.py`) |
| `tools/vendor/sider/` | Vendored Sider file-format code (see below) |
| `tools/data/` | Decoded `dt270` gameplay schema and the named realism tunings and patches it drives |
| `data/` | Hand-made identity rulings and adjudicated merges, re-applied on every world rebuild |
| `docs/` | Format notes, decisions, specs, the exe gameplay map and the per-player stats runbook |
| `samples/` | Schema notes derived from real exports. Real exports are not committed |
| `assets/` | Competition and club artwork used by the app |

## Download and play

The [Releases page](https://github.com/tjgg260/eFootball-Master-League/releases) carries a
zip with the built app and the world database. Unzip it anywhere, double-click
`Play Master League.bat`, and start a new career. Nothing else is needed to run a career by
entering results yourself. Player photos are not included, so portraits are generated
avatars; club crests and flags are.

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
`numpy` and `pycryptodome`, and optionally OBS Studio and ffmpeg for match-video capture.
See [PLAYTESTING.md](PLAYTESTING.md) for the step-by-step setup.

## What you must supply yourself

These are used by the tools but are **not in this repository**. They are third-party or
game data and are not ours to redistribute. Each location is gitignored, so dropping them in
place will not dirty your checkout.

| Item | Where it goes | Used by |
|---|---|---|
| eFootball install (Steam appid 1665460) | Wherever Steam put it | Everything in Phase 3 and 4 |
| CRI File System Tools (`cpkmakec.exe`) | `CRI_File_System_Tools_v2.40.13.0/crifilesystem v2.40.13.0/` at the repo root | `tools/ml_apply.py`, `tools/play_match.py`, `ML.Sync` |
| eFootball WESYS Unzlib Tool | Repo root | Extracting game tables (see the Phase 0 checklist) |
| RBsGameLab eFootball Player Editor | Repo root | Manual editing and CSV export |
| EvoMod | Installed into the game as its author documents | The install order rule below |
| Tesseract `eng.traineddata` | `tools/tessdata/` | OCR. Fetch from tesseract-ocr/tessdata_best |
| Your own game exports, FM exports, face packs | Repo root or `samples/` | The `tools/` import pipeline |

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
- Never rebuild or re-serialise the CPK. The deploy is a pure in-place byte patch.

## Licence

GPL-3.0. See [LICENSE](LICENSE).

This is deliberate: `tools/vendor/sider/` carries file-format and WESYS cipher code from
[Efootball-Sider](https://github.com/Master-Antonio/Efootball-Sider) (GPL-3.0), and
`tools/ml_apply.py` links against it, which makes this project a derivative work. Details in
[tools/vendor/sider/VENDOR.md](tools/vendor/sider/VENDOR.md). Do not add code under an
incompatible licence.

Sider's `dxgi.dll` runtime is not redistributed here. eFootball is a Konami product; this
project is not affiliated with or endorsed by Konami.
