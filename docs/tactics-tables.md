# Tactics / formation / coach tables — decoded

Reverse-engineered 2026-08-19 by a parallel recon pass. Full raw findings (all clusters +
synthesis, ~80KB) archived at the workflow output; this is the curated record.

## The chain

```
Team.bin (981 teams, id @+12)  <--  Tactics.bin (keyed BY team_id)  -->  TacticsFormation.bin
```

Team.bin has **no** formation pointer. `Tactics.bin` is keyed by team id, and points at a
formation shape in `TacticsFormation.bin`. Coach.bin does **not** reference formations.
`CoachTactics.bin` / `CoachTacticsFormation.bin` decode to 0 bytes — schema present, unpopulated.

## TacticsFormation.bin — the pitch geometry

12 bytes/record, no header, 19,580 records = **1,780 formations × 11 slots**.

| Offset | Type | Meaning |
|---|---|---|
| 0 | u32 | Role code for the slot. 0 GK,1 CB,2 LB,3 RB,4 DMF,5 CMF,6 LMF,7 RMF,8 AMF,9 LWF,10 RWF,11 SS,12 CF |
| 4 | u32 | `formation_id` — groups 11 consecutive records into one shape; the join key Tactics.bin uses |
| 8 | u8 | **Y** = depth from own goal, 3–43 (GK=3, forwards ~39–43) |
| 9 | u8 | **X** = pitch width, 12–92, centre 52 (left ~16, right ~88) |
| 10 | u8 | slot index 0–10 (slot 0 always GK) |
| 11 | u8 | always 0 |

Validated: England/Arsenal/Liverpool/Benfica all resolve to correct real-world shapes. **This is
literally FM's tactics board** — 11 dots, each with an (x,y) and a position label. Editing these
repositions players or invents custom shapes.

## Tactics.bin — the phase link + style

12 bytes/record, no header, 1,780 records. Each team has **exactly two** records.

| Offset | Type | Meaning |
|---|---|---|
| 0 | u32 | `team_id` (owner) — matches Team.bin +12 |
| 4 | u32 | `formation_id` → TacticsFormation.bin |
| 8 | u8 | team attacking-style enum, 6 values 0–5 (build-up/mentality preset; labels unconfirmed) |
| 9 | u8 | **phase bit 0x100**: one record clear, one set → in-possession vs out-of-possession shape |

**Headline:** the two-shapes-per-team (fluid formation) mechanism is **native and almost
entirely unused** — 889 of 890 teams point both phases at the *same* formation_id; only team 6261
actually morphs (4-3-3 → 4-2-3-1). Authoring two distinct formation_ids per team gives real fluid
formations. Rich sliders (pressing, line height, width, tempo) are **not** here — the flags word
uses only 4 bits — and likely live in Team.bin's 1600-byte record (still to decode).

## Coach.bin — coach philosophy

176 bytes/record, 982 coaches, **1:1 with teams** (Team.bin +0 references coach id).

| Offset | Type | Meaning |
|---|---|---|
| 0 | u32 | Coach ID (primary key, referenced by Team.bin +0) |
| 21 | u8 ×4 | **preferred formation id** (stored ×4; 57 distinct; id 16 dominant) |
| 22 | u8 | **team playstyle / attacking philosophy**, 5 values — matches eFootball's 5 team styles (Possession / Quick Counter / Long Ball Counter / Long Ball / Out Wide) |

Offsets 21–22 are the "tactics reflect the coach" levers.

## How this maps to the original three goals

1. **Multiple tactics/formations per match** — the table holds 2 shapes/team; >2 needs rewriting
   records between matches (app-driven). 2 phase-shapes is free.
2. **Fluid formations** — VERIFIED moddable now: point a team's two Tactics records at two
   different, genuinely distinct formation_ids. This is the strongest, lowest-risk win.
3. **Coach philosophy** — set Coach.bin +21 (formation) and +22 (playstyle) per coach.

All three are in-place edits on tables we can already decrypt/encrypt — no headcount change — so
they ride the same proven pipeline as squad edits.
