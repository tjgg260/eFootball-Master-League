# eFootball Master League — Build Plan

A companion app that restores a persistent Master League to eFootball 2027 (PC / Steam).
Matches are played in-game offline. Results are imported by screenshot. Transfers and player
progression are written back into the game database so the squads you manage are the squads
you actually play with.

---

## 0. Core architecture decision (read this before anything else)

**The app's SQLite database is the single source of truth. The game's files are a render
target.**

Never read game state back in as authority after the initial seed. The app knows the true
state of the world; the game is something we push a projection into. This matters because:

- eFootball v6.0.0 relocated every ability/skill bitmap and wrapped the database in an
  encrypted WESYS container. Konami will do something like this again.
- Konami merges live updates into the offline database, which will silently revert edits.
- EvoMod replaces whole `cpk` / `pak` folders on every reinstall.

If the career save lives in the game files, any of those three events kills it. If it lives in
SQLite, each one costs a re-export and a re-apply.

**We never parse Player.bin ourselves.** RBsGameLab's eFootball 2027 Player.bin Editor already
decrypts WESYS, handles the 400-byte record layout, supports `PlayerAssignment.bin` (team
membership + squad numbers), and does CSV export/import with *sparse import* — writing back
only changed fields. That CSV interface is our API. Do not reimplement it.

> **Superseded.** Since 2026-08-19 we read and write the tables directly through vendored Sider
> code. Since 2026-09-14 we also read and patch the CPK through the editor's own `cpk.py`
> (`tools/vendor/efootball-player-tool/`). The editor is the eFootball Player Editor, which
> earlier notes called "RBsGameLab's Player.bin Editor". It is now optional, for hand edits and CSV exports.

---

## Phase 0 — Proof of concept (manual, no code)

**Gate. Do not start Phase 1 until this passes.**

1. Back up the eFootball install folder.
2. Install EvoMod 6.0 (optional but do it now if at all, so ordering is established).
3. Download RBsGameLab's Player.bin Editor. Point it at the game's `Player.bin`.
4. Load `PlayerAssignment.bin` alongside it.
5. Move one recognisable player between clubs — Wirtz to Chelsea. Set a free squad number.
   Move a Chelsea player the other way to keep squad sizes legal.
6. Save (the editor writes a `.bak` on first save — verify it exists).
7. Launch eFootball, start an offline match vs the CPU, open the Chelsea squad list.

**Pass condition:** Wirtz is in the squad, with his own face, playable.

Record while doing this:
- Exact path to `Player.bin`, `PlayerAssignment.bin`, `PlayerAppearance.bin`
- Whether they live inside a `cpk`/`pak` that EvoMod overwrites
- The CSV export column headers, verbatim, for all three files
- Roster size limits before the game complains

If it fails, stop and diagnose before building anything.

---

## Phase 1 — Data foundation

**Goal:** a SQLite DB seeded from the game, with a verified round-trip.

### Stack
- .NET 8, C#
- SQLite + Dapper (not EF Core — we want visible SQL here)
- Solution layout: `ML.Core` (engine), `ML.Data` (persistence), `ML.Ingest` (OCR/capture),
  `ML.Sync` (CSV writeback), `ML.App` (Avalonia UI)

### Tasks
1. Export full CSVs from the editor: players, assignments, appearances.
2. **Derive the schema from the actual export files. Do not guess column names.**
3. Build the SQLite schema. Everything keys on PID.
4. Importer: CSV → SQLite.
5. **`applied_state` table** — a snapshot of what we believe is currently in the game.
   This is what makes sparse writeback possible.
6. Round-trip test: import → export unchanged → diff should be empty.

### Schema sketch

```
players        pid PK, name, dob, nationality, positions, attributes..., current_team_id
teams          team_id PK, name, league_id, budget, wage_bill
assignments    pid FK, team_id FK, squad_number
applied_state  pid, field, value, applied_at   -- what the game currently holds
seasons        season_id, year, is_current
fixtures       fixture_id, season_id, home_team_id, away_team_id, matchday, played
results        fixture_id FK, home_goals, away_goals, stats_json, screenshot_path
match_events   fixture_id FK, pid FK, event_type, minute
transfers      pid, from_team_id, to_team_id, fee, window, season_id
contracts      pid, team_id, wage, expires_season
```

**Milestone:** app opens, shows every club and squad correctly, exports an empty diff.

---

## Phase 2 — League engine

Pure C#, no I/O, fully unit-testable. This is where Master League actually lives.

- Season creation, league selection, chosen club
- Round-robin fixture generation (home/away, no team twice on a matchday)
- League table with correct tiebreakers (points → GD → GF → h2h)
- Advance-matchday state machine
- CPU-vs-CPU result simulation for every fixture the user isn't playing
  - Weight by squad strength with meaningful variance — a good sim is what makes the
    league feel alive rather than deterministic
- Season rollover: champions, promotion/relegation, ageing, contract expiry

**Milestone:** simulate ten full seasons end-to-end in tests. Table is always valid,
no negative budgets, no orphaned players.

---

## Phase 3 — Result capture

> **Superseded 2026-09-14.** The screenshot/OCR plan below was built and then deleted. Results
> now come from efootball-re's stats host, which runs inside the game and exports every finished
> match (`ml_stats\match_*.json`). `ML.Ingest` links the export to the fixture by PID and
> pre-fills the confirm screen. See `docs/decisions.md`, 2026-09-14.

**Steam screenshot pipeline. No memory reading, no injection.**

eFootball connects to Konami even for offline play. Attaching a debugger or injecting a DLL
risks the account for a marginal gain over a three-second screenshot. Not worth it.

1. `FileSystemWatcher` on the Steam screenshot directory
   (`steamapps/userdata/<userid>/760/remote/<appid>/screenshots`).
2. On new file: match it to the pending fixture.
3. **Region calibration UI** — user drags boxes over one sample screenshot per resolution,
   labelling each field (home score, away score, possession, shots, on target, fouls,
   scorer list). Store as *normalised* coordinates so it survives resolution changes.
4. Crop each region and OCR it in isolation (Tesseract, `--psm 7`, digit whitelist on
   numeric fields). Never OCR the full frame — accuracy collapses.
5. **Always show a confirm-and-correct screen.** Pre-filled, editable, one keystroke to
   accept. Goalscorer names with minutes are the field OCR will get wrong most often; make
   that row easy to fix with autocomplete against the match squads.
6. On confirm: write `results` + `match_events`, advance the matchday.

**Milestone:** play a match, hit F12, confirm the pre-filled result, see the table update.

---

## Phase 4 — Writeback

The payoff. Squad changes in the app become squad changes in the game.

1. Transfer/release/promote actions update the desired state in SQLite.
2. **Validate before emitting**: roster size limits, squad number collisions, no player at
   two clubs, GK count sane. Fail loudly here rather than corrupting the DB.
3. `Diff(desired_state, applied_state)` → sparse CSV in the editor's exact import format.
4. User imports the CSV via the editor. Update `applied_state` on success.
5. **Recovery path**: a "game was patched" button that clears `applied_state` and emits a
   full diff, rebuilding the entire world in one import.

### Operational rules — put these in the app as reminders

- Install order after any Konami update: **Konami patch → EvoMod → your CSV.** Always.
- Back up `Player.bin` before every apply (editor does `.bak` once; do our own too).
- Keep modified databases to offline play. Don't take an edited local DB near Dream Team.

**Milestone:** buy Wirtz for Chelsea in the app, apply, launch the game, play a match with
him in the side.

---

## Phase 5 — Depth

Once the loop is closed, this is what turns it into a career:

- Attribute progression and decline driven by minutes played, age, and performance
- Injuries and suspensions that block selection
- Transfer budgets, wage bills, contract negotiation and expiry
- CPU clubs conducting their own transfers between seasons
- Youth academy: generate players, insert as new PIDs, write into the game
- Cup competitions alongside the league
- Season history, records, honours board

---

## Standing instructions for Claude Code

Put this in `CLAUDE.md` at the repo root:

- **Never write a binary parser for Player.bin.** All game I/O goes through the editor's
  CSV import/export. If a task seems to need direct binary access, stop and ask.
- **Never guess CSV column names or attribute field names.** Read them from a real export
  file in `/samples`. If the file isn't there, ask for it.
- SQLite is the source of truth. No code path may treat a game file as authoritative state.
- Every writeback is a diff against `applied_state`, never a blind full write.
- `ML.Core` has no I/O dependencies and must stay unit-testable.
- Validate squad legality before emitting any CSV. A corrupt DB costs an evening.
- Commit `/samples` with anonymised real exports so tests run without the game installed.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Konami patch changes record layout | Wait for editor update; our CSV layer absorbs it |
| Live update reverts edits | Full re-apply from `applied_state` reset |
| EvoMod reinstall wipes transfers | Documented install order; re-apply |
| OCR misreads a result | Mandatory confirm screen; results are editable after the fact |
| Roster limits corrupt the DB | Pre-emit validation, hard fail |
| Editor abandoned by author | CSV exports are archived; worst case the schema is already decoded publicly |

---

## Build order summary

```
Phase 0  Manual proof              — one evening, gates everything
Phase 1  Data foundation           — schema, seed, round-trip
Phase 2  League engine             — fixtures, table, sim, seasons
Phase 3  Capture                   — watcher, calibration, OCR, confirm
Phase 4  Writeback                 — diff, validate, apply
Phase 5  Depth                     — progression, youth, cups, CPU transfers
```

Ship Phase 4 before touching Phase 5. A shallow league you can actually play beats a deep
one that never closes the loop.
