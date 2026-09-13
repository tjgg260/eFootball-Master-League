# /samples

Real CSV exports from the eFootball Player Editor. **Phase 1 is blocked until these
exist.**

The build plan forbids guessing column names or attribute field names — the schema is derived
from these files, not from assumptions about what the editor emits. If a task seems to need a
column name and there is no export here to read it from, that task stops and asks.

## Expected files

| File | Source | Carries |
|---|---|---|
| `players.csv` | `Player.bin` | PID, name, dob, nationality, positions, attributes |
| `assignments.csv` | `PlayerAssignment.bin` | PID → team, squad number |
| `appearances.csv` | `PlayerAppearance.bin` | face/appearance data keyed by PID |

Export **full** files, not filtered subsets. A subset silently teaches the importer that
columns are optional when they are not.

## Anonymising

These get committed so tests run without the game installed. Before committing, replace real
player names with generated ones — keep PIDs, ratings, positions and every structural column
exactly as exported. The tests care about shape and key relationships, not identities.

Keep at least one club's worth of rows intact so squad-legality tests have something realistic
to work with.

## Also worth keeping here

- `ml-stats/`: real match exports from efootball-re's stats host (2026-09-13; raw roster record
  bytes stripped), each with `*.expected-ratings.json`, which is efootball-re's `rating.py` output
  for that export. `MatchExportTests` pins the C# rating port to those files, player by player.
