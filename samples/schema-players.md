# Player CSV schema — editor's bundled database

**Source:** `efootball_players.csv`, recovered on 2026-08-18 from the Player.bin Editor's
PyInstaller extraction directory (`%LOCALAPPDATA%\Temp\_MEI395362\`) while the editor was
running. Copied to `samples/editor-bundled-players.csv` — 42,369 players, 50 columns, 13 MB.

The raw file is gitignored: it is third-party data, not ours to redistribute, and it is large.
This document is the committed record of its shape.

## Status: reference, not yet authoritative

This is the editor's **bundled reference database**, not an export from our own `Player.bin`.
Treat it as a strong hint about the schema, not as proof of the import/export contract.

`CLAUDE.md` forbids guessing column names. This file does not lift that rule — it narrows it.
Before Phase 1 commits to this schema, Phase 0 step 5 must still export a real CSV from the
actual game files and confirm the header matches, because:

- The bundled DB flattens `Player.bin` and `PlayerAssignment.bin` into one table. It carries
  `team` as a **name string**, with no team id. A real `PlayerAssignment.bin` export almost
  certainly keys on a numeric team id — that is the column the writeback actually needs.
- There is no appearance data here at all, so `PlayerAppearance.bin` remains completely unknown.
- An editor's internal reference table and its import parser are not obliged to agree.

## Columns (verbatim, in order)

```
player_id,squad_number,squad_number_national,position,player_name,team,league,region,
nationality,height,weight,age,foot,rating_grade,max_level,overall_rating,offensive_awareness,
ball_control,dribbling,tight_possession,low_pass,lofted_pass,finishing,heading,
set_piece_taking,curl,speed,acceleration,kicking_power,jumping,physical_contact,balance,
stamina,defensive_awareness,tackling,aggression,defensive_engagement,gk_awareness,gk_catching,
gk_parrying,gk_reflexes,gk_reach,weak_foot_usage,weak_foot_accuracy,form,injury_resistance,
primary_playing_style,secondary_playing_style,player_skills,ai_playing_styles
```

Wrapped for reading only — the real header is one line with no spaces.

## Notes on the data

- `player_id` is the PID. This is the key everything in our schema hangs off.
- `squad_number` is blank for free agents; `squad_number_national` is blank for most players.
- 10,121 of 42,369 rows are `Free Agent` — about a quarter of the database has no club.
- Attributes run on a 40–99 scale, matching the engine's `Player.MinRating` / `MaxRating`.
- `player_skills` and `ai_playing_styles` are `; `-separated lists inside a single field, so the
  file stays comma-safe.
- `form`, `weak_foot_usage`, `weak_foot_accuracy` and `injury_resistance` are **words**, not
  numbers (`Occasionally`, `Rarely`, `High`, `Medium`, `Standard`, `Unwavering`). Any importer
  needs a lookup, not a parse.
- `rating_grade` is a letter (`C`), `max_level` an integer — these are eFootball progression
  concepts with no equivalent in the engine yet.

## What this unblocks

Nothing yet, formally. But it means Phase 1's schema work is no longer blind: the attribute
column set is known, and the free-agent share and rating scale confirm the engine's existing
assumptions were reasonable.
