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

### Source data — where every export actually lives

**Check this table before concluding that data does not exist.** These are the owner's own
exports and they are NOT all inside the repo; a missing DB table means the import has not been
run, never that the source is gone.

| Data | Path | Carries |
|---|---|---|
| FM **attributes (1-20)** | `C:\Users\tjgg2\OneDrive\Documents\Sports Interactive\Football Manager 2024\{B,c,d,…,z}.html` | 25 HTML exports, ~490k rows, 69 columns — the full technical/mental/physical/GK ladder, plus UID, **DoB**, Height, Weight, Preferred Foot, Personality, Ability, Potential |
| FM **membership/bio** | `allavailable columns players.csv` (repo root) | Club, Club ID, Squad, Based, DoB, Unique ID — THE membership truth |
| FM bio (older dumps) | `allplayers.csv`, `test.csv.html.csv` (repo root) | bio + Best Rating / Best Pot Rating; no attributes |
| FM fitness | `attributes.csv`, `test.csv` (repo root) | Fitness / Con / Happiness only — despite the filename, **not** the attribute ladder |
| FM clubs / staff | `clubs.csv`, `staff.csv` (repo root) | club finances and reputation; staff coaching 1-20 |
| eFootball players | `samples/editor-bundled-players.csv` | 25,460 base players — real eF attributes on the 40-99 scale, playstyles, skills |
| FM editor data | `…\Sports Interactive\Editor 26\editor data\` | sortitoutsi FM26 live data update |
| **Owner identity rulings** | `data/identity_overrides.json` | hand-made player/club identity decisions, re-applied by `apply_identity_overrides.py` — `build_identity.py` DELETEs the spine, so rulings live here or not at all |

### Traps in the source data (verified, not guessed)

- **Every FM date of birth is exactly three years early.** Day and month are right, the year is
  short by three: Saka reads 05.09.1998 and Haaland 21.07.1997. The database knew before we did —
  for the 14,367 players who also exist in eFootball, our age sat three below what FM's date
  implied. Anything deriving an age from FM must add the three back (`fix_fm_age_shift.py`).
- **FM's Position field is a grammar, not a label.** `D/WB L` is a left back, `AM RL` is either
  wing, `D RC` is a right back OR a centre back. A `startswith` on the first token turns all of
  them into centre backs — which is what emptied hundreds of clubs of full-backs. Parse the flank
  first (`fix_positions_from_fm.ef_positions`, `fix_fullback_shortage.flanks`).
- **FM regenerates its youth.** An FM-band id IS 10B + uid, so a record whose stored name matches
  nobody in its FM row is not mis-linked: the save refilled that slot with a new person. Take the
  export's identity, keep the record.
- **RFS's top percentile overshoots the game's scale.** Its body sits below eFootball's, but its
  last 1% runs to 99 where eFootball's own maximum is 86 (`compress_rfs_tail.py`).
- **The two placeholder rows in eFootball's export** (every ability 95, overall 116) are not
  players. Leave them; do not let a rating model learn from them.

### Rebuilding the world (the order matters)

`build_catalog.py` rewrites `build/catalog.json` from scratch, so everything that patches the
catalog has to run again behind it, in this order:

```
build_catalog -> fix_catalog_dupes -> fix_catalog_geo -> merge_split_club -> fix_slot_wrong_club
  -> fix_club_display_names -> sync_team_leagues -> link_logos_by_fm_id -> gen_club_badges
  -> fill_squads (+ spine rows for generated ids) -> fix_fullback_shortage
  -> refresh_roles_for_position -> assign_roles -> rerank_slots -> fix_shirt_numbers
  -> validate_db -> audit_world
```

Membership and attributes hang off the same chain: `verify_identity_fm` -> `link_ef_to_fm` ->
`adopt_ef_records` -> `sync_membership_fm` -> `fm_derive_attributes --career` ->
`synth_attributes` -> `fix_overalls` -> `restore_ef_overalls`. Every one of them is idempotent and
takes `--dry`.

### Two gates, not one

- `tools/validate_db.py` — the build gate: nine assertions, exit 1 if any fails. Never writes.
- `tools/audit_world.py` — the standing quirk sweep beside it: what is not structurally invalid
  but still reads wrong (a squad wearing one number twice, a keeper with a striker's finishing,
  a club fielding another country's namesake). It separates *fixable* from *residue the sources
  cannot settle* from *not a fault*, so a clean run means something.

**Career bands are never the world.** Teams 800k-1M and players 20M-700M / 45-46B belong to a
save. `build_catalog` once resolved league slots onto them — a career copy holds the club's full
roster, so it is always the biggest record of its club and always won the tie-break, and 37 career
teams (Chelsea, Manchester United) ended up in the browsable catalog. The band is excluded at the
index now, and assertion 7 fails the build if one gets back in.

**The .bak files will fill the disk.** Every tool copies master.db before writing (~2 GB each).
118 of them reached 107 GB mid-session and the disk hit 100%. Prune to one restore point per day.

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

## Phase status

- **Phase 0** — PASSED 2026-08-19. Writeback proven in-game. See [docs/phase0-checklist.md](docs/phase0-checklist.md).
- **Phase 1** — data foundation. Real schemas recovered in `/samples`; SQLite seed not built.
- **Phase 2** — league engine. Built and tested.
- **Phase 3** — capture. Not started.
- **Phase 4** — writeback. Core mechanism proven early (tools/ml_*.py); needs the `applied_state`
  diff model and the ML.Sync integration.
- **Phase 5** — not started.
