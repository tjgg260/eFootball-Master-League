# PlayerAssignment schema — VERIFIED

**Source:** real export from our own `PlayerAssignment.bin` via the Player.bin Editor,
2026-08-18. This one satisfies Phase 0 step 5 — it is an actual export, not a bundled reference
table. See [schema-players.md](schema-players.md) for the weaker artefact.

## Header (verbatim)

```
PlayerID,Name,TeamID,SquadNumber,Slot,Role,RowNum
```

Note the file carries a **UTF-8 BOM** before `PlayerID`. Any importer must strip it or the first
column name arrives as `﻿PlayerID`.

23,687 rows.

## Columns

| Column | Meaning |
|---|---|
| `PlayerID` | The PID. Joins to `player_id` in the players export. |
| `Name` | Denormalised convenience copy. Not authoritative — do not key on it. |
| `TeamID` | Numeric club or national-team id. Resolved via `Team.bin`. |
| `SquadNumber` | Shirt number. Unique within a `TeamID`. |
| `Slot` | 0-based position in the squad list. Contiguous per team, `0..squadSize-1`. |
| `Role` | Captain / set-piece flags. Mostly 0. Meaning not yet decoded. |
| `RowNum` | Physical record index in the `.bin`. **Identity — never edit or swap it.** |

## The finding that matters: a player has more than one row

`PlayerID` is **not** unique in this file. A player appears once per squad they belong to —
club *and* national team:

```
137924,Florian Wirtz,14,17,8,0,4424442     <- Germany,   shirt 17
137924,Florian Wirtz,103,7,18,0,4409171    <- Liverpool, shirt 7
```

The primary key is `(PlayerID, TeamID)`, or equivalently `RowNum`.

This breaks the schema sketched in the build plan, which had `assignments(pid FK, team_id FK,
squad_number)` with an implied one club per player. Our `World` enforces exactly one club per
player, which is right for the league engine but means the Phase 1 importer must **filter to
club rows only** and keep national-team rows out of the engine entirely — or squad sizes and
transfers will be nonsense.

Distinguishing club from country is unsolved. `Team.bin` presumably flags it; low TeamIDs look
like national sides (`14` = Germany, `1` = Republic of Ireland) and three-digit ones like clubs
(`102` = Chelsea, `103` = Liverpool), but that is a pattern, not a rule, and must be confirmed
against `Team.bin` before Phase 1 relies on it.

## Player.bin's own team field is the NATIONAL team

The editor's Basic panel shows `Squad TeamID` for a player — for Wirtz it reads `14`, which is
Germany, not Liverpool. So the team id embedded in the `Player.bin` record is the international
side, and **club membership lives only in `PlayerAssignment`**.

Consequence for Phase 4: a transfer writes to `PlayerAssignment`, not to `Player.bin`. Two
different files, and the obvious-looking field in the more obvious file is the wrong one.

## Record layout confirmed

The editor reports the decrypted `Player.bin` as **9,407,600 bytes** and loads **23,519**
records. 9,407,600 ÷ 23,519 = **400 exactly**, which confirms the 400-byte record layout the
build plan cites. The 2,264,622 bytes on disk is the compressed WESYS form.

## Known TeamIDs

| TeamID | Team |
|---|---|
| 1 | Republic of Ireland (national) |
| 14 | Germany (national) |
| 102 | Chelsea |
| 103 | Liverpool |

Populate the rest from `Team.bin`.
