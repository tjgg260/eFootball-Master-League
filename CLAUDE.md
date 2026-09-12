# CLAUDE.md

Companion app that restores a persistent Master League to eFootball 2027 (PC / Steam).
Matches are played in-game offline; results come in by screenshot; transfers and progression
are written back into the game database.

See [efootball-master-league-plan.md](efootball-master-league-plan.md) for the full build plan.

## Core architecture decision

**The app's SQLite database is the single source of truth. The game's files are a render
target.** Never read game state back in as authority after the initial seed.

## Licence: GPL-3.0

This repository is GPL-3.0 because it links vendored Sider code (`tools/vendor/sider/`) for
WESYS decryption. Deliberate, informed choice — see
[VENDOR.md](tools/vendor/sider/VENDOR.md). Do not add code here under an incompatible licence.

## Standing instructions

- **Never hand-roll the binary formats.** Superseded 2026-08-19: we now read and write
  `PlayerAssignment.bin` directly, but *only* through vendored Sider code whose layouts and
  cipher came from upstream. Do not write a new parser from scratch, and do not edit the
  vendored files in place — re-pull from upstream so the diff stays visible.
- **No write happens without a byte-exact round-trip proof first.** `prove_round_trip()` in
  `tools/ml_apply.py` rebuilds the *unmodified* source file and compares byte for byte. If it
  cannot, we do not understand the format well enough to be trusted, and nothing is written.
  Keep that gate on every new file type.
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

## The writeback pipeline (PROVEN — Phase 0 passed 2026-08-19)

A transfer, applied and confirmed in-game (Gyökeres started for Liverpool):

```bash
python tools/ml_swap.py   --csv PlayerAssignment.csv --a <pid-in> --b <pid-out> --apply
python tools/ml_deploy.py --csv PlayerAssignment.csv --install
```

Hard-won rules baked into those tools — change them at your peril:

- **PlayerAssignment is a POSITIONAL format.** A record's club is its physical position in
  the file, not its `TeamID` value. A transfer swaps *which player occupies* a record; it
  never moves a record or edits `TeamID`. Editing `TeamID` put a winger in goal.
- **Never rebuild or re-serialise the CPK.** cpkmakec rebuilds at alignment 2048 and the game
  silently ignores anything but 512. cricodecs `save()` after a size-changing `replace_bytes`
  re-lays-out the archive and the game black-screens. The deploy does a **pure in-place byte
  patch**: the edited payload re-packs at zlib level 1 to the exact original length, so its
  bytes drop into the same slot and every other byte of the CPK is untouched.
- **WESYS payload is encrypted** (v6.0.0), decrypted via vendored Sider code. Level 1 repacks
  Konami's files byte-identically.
- CSV quirks: the editor export truncates `TeamID` to u16; `Slot` is `sort_key // 4` and the
  low bits are flags that must be preserved.

## dt270 gameplay constants (DECODED 2026-08-23)

`dt270_console_all.cpk → common/match/constant/*.bin` = packs of compiled-JSON objects (float /
int / bool scalars, u32 block offsets for nested objects / arrays / strings). Field names come
from the game's own loaders, recovered by emulation: `tools/dt270_schema_gen.py` →
`tools/data/dt270_schema.json` (**re-run after every Konami patch**). Read/edit by name with
`tools/dt270_objects.py` and `tools/gameplay_tune.py get|set|apply|diff|scale`. Docs:
[docs/dt270-gameplay.md](docs/dt270-gameplay.md), catalogue [docs/dt270-fields.md](docs/dt270-fields.md).
Rules: edits in place only (no size change), `dt270_objects.py verify` must stay byte-exact,
zlib level 9 (zopfli fallback) into the original CPK slot. The old "Q2.14 word" model is dead.

## eFootball.exe gameplay map (2026-08-23)

RTTI is intact (5,791 classes, 782 in `match::`). `tools/exe_map.py` (build/grep/class/disasm/
xrefs) maps vftables → methods; [docs/exe-gameplay-map.md](docs/exe-gameplay-map.md) holds the
verified findings: kick error model (`0x14401a900`, `(1−f)·22.5°`), CPU level table
(`0x146c06f40`, 44×10, hidden LEGEND), `ConstantManager` (`0x148c22b98`) and which dt270
fields are live. Denuvo: **never modify the exe on disk**; runtime patches only via
`tools/live_patch.py` (probe first; data-page writes before code-page writes). Cheat Engine is
blocked, our own ReadProcessMemory works, WriteProcessMemory is untested. Patch specs live in
`tools/data/patches/`. A browsable index of every dt270 field and exe lever
(current value + live/inert status): `tools/gameplay_catalog.py` → `build/gameplay-catalog.html`.

## Phase status

- **Phase 0** — PASSED 2026-08-19. Writeback proven in-game. See [docs/phase0-checklist.md](docs/phase0-checklist.md).
- **Phase 1** — data foundation. Real schemas recovered in `/samples`; SQLite seed not built.
- **Phase 2** — league engine. Built and tested.
- **Phase 3** — capture. Not started.
- **Phase 4** — writeback. Core mechanism proven early (tools/ml_*.py); needs the `applied_state`
  diff model and the ML.Sync integration.
- **Phase 5** — not started.
