# CLAUDE.md

Companion app that restores a persistent Master League to eFootball 2027 (PC / Steam).
Matches are played in-game offline; results come in by screenshot; transfers and progression
are written back into the game database.

See [efootball-master-league-plan.md](efootball-master-league-plan.md) for the full build plan.

## Core architecture decision

**The app's SQLite database is the single source of truth. The game's files are a render
target.** Never read game state back in as authority after the initial seed.

## Standing instructions

- **Never write a binary parser for `Player.bin`.** All game I/O goes through the RBsGameLab
  editor's CSV import/export. If a task seems to need direct binary access, stop and ask.
- **Never guess CSV column names or attribute field names.** Read them from a real export file
  in `/samples`. If the file isn't there, ask for it.
- SQLite is the source of truth. No code path may treat a game file as authoritative state.
- Every writeback is a diff against `applied_state`, never a blind full write.
- `ML.Core` has no I/O dependencies and must stay unit-testable.
- Validate squad legality before emitting any CSV. A corrupt DB costs an evening.
- Commit `/samples` with anonymised real exports so tests run without the game installed.

## Operational rules (surface these in the app)

- Install order after any Konami update: **Konami patch → EvoMod → your CSV.** Always.
- Back up `Player.bin` before every apply. The editor writes a `.bak` on first save only; we
  take our own every time.
- Keep modified databases to offline play. Don't take an edited local DB near Dream Team.

## Solution layout

| Project | Role | Phase |
|---|---|---|
| `src/ML.Core` | League engine. Pure C#, **no I/O, no packages** | 2 |
| `src/ML.Data` | SQLite + Dapper persistence | 1 |
| `src/ML.Ingest` | Steam screenshot watcher, region calibration, Tesseract OCR | 3 |
| `src/ML.Sync` | CSV diff and writeback against `applied_state` | 4 |
| `src/ML.App` | Avalonia UI | 1 |
| `tests/ML.Core.Tests` | Engine tests | 2 |

`ML.Core` must never gain a package reference. That constraint is what keeps the engine
testable without the game installed.

## Build and test

```bash
dotnet build
dotnet test
```

## Environment (this machine)

Recorded so paths don't have to be rediscovered. Verify before relying on them.

- Steam: `C:\Program Files (x86)\Steam`
- eFootball appid: `1665460` — install dir `steamapps\common\eFootball`
- Steam user id: `1253972527`
- Screenshot dir (Phase 3 watcher target, created on first F12):
  `C:\Program Files (x86)\Steam\userdata\1253972527\760\remote\1665460\screenshots`
- Tesseract model: `tools/tessdata/eng.traineddata`

## Phase status

- **Phase 0** — manual proof. See [docs/phase0-checklist.md](docs/phase0-checklist.md). **Gate: not yet passed.**
- **Phase 1** — blocked on Phase 0 producing real CSV exports into `/samples`.
- **Phase 2** — league engine. Built and tested.
- **Phase 3–5** — not started.
