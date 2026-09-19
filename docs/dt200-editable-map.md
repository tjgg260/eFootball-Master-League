# dt200 — what we can change and have reflected in eFootball

Everything in `dt200_console_all.cpk` is WESYS-wrapped data the game loads at boot. Our proven
pipeline (`play_match.rebuild_and_install` → `tools/cpk_patch.py` changed-file patch, sha guard, `.bak`) can write
**any** of it back — the only work per file is: (1) locate the field, (2) prove round-trip, (3) UI.
So this is a menu of "what could the app edit," ranked by value ÷ effort.

## Tier 0 — already wired (reflected in-game today)

| File | What we drive | Via |
|---|---|---|
| `Player.bin` | player names | `ml_author` / `playstyle_bits` |
| `PlayerAssignment.bin` | which player occupies each club slot (transfers) | `ml_swap` (positional) |
| `Team.bin` | team names (@396, 48-byte English field) | `dt200_rename` |
| `CategoryTeamList.bin` | league membership + alphabetical order | `dt200_rename` |
| `Tactics.bin` + `TacticsFormation.bin` | formation + team style (u8@8) | `play_match.write_style` |
| `Coach.bin` | coach names | derby/coach tooling |
| `Derby.bin` | rivalries (team_rivals) | `derby_import` |

## Tier 1 — the full player editor (BIGGEST WIN, write path already proven)

`Player.bin` is a 400-byte record, **fully decoded** (doc §2). We already write it, so exposing the
rest is UI + a bitfield writer — every edit shows up in-game. Fields, all bit-packed in the record:

| Field | Location | Notes |
|---|---|---|
| 26 abilities (pace, shooting, passing, defending, GK…) | bits 368–556, 6 bits each, **+40 bias** | stored 63 → shows 103 |
| 65 player skills (1-bit flags) | bits 223–680 | e.g. Trickster, Long Ranger toggles |
| **Playing style — attacking (in possession)** | **bit 374, 5 bits** (purity 1.000) | 19 styles + Basic; value is the GLOBAL `Playstyle.bin` catalog index, NOT position-scoped (corrected 2026-09-15) |
| **Playing style — defending (out of possession)** | **bit 440, 6 bits** (confirmed) | The Destroyer, GK styles (Attacking/Defensive/Sweeper/Build-up/High Line GK), 13 v6.0.0 defensive styles — also the GLOBAL catalog index, direct (not raw×4) |
| AI playing styles (7) | bits 614–680 | COM behaviour flags |
| Position (14) + 12 aptitudes | bit 556 (4b); aptitudes 576–599 (+LB@318, CMF@510) | |
| Nationality (192) | bytes 41–42, u16 & 0x3FF | |
| Height / Weight / Age | bits 248 / 280 / 536 | |
| Preferred foot / weak-foot use & accuracy | bits 654 / 478 / 578 | |
| Form (3) / Injury resistance (3) | byte 72 b6-7 / byte 67 b6-7 | |

**This is the answer to "in and out of possession playstyles"** — both fields are located and
provable. A player-edit screen (attributes + both styles + skills + position) is the natural next
build, and it reuses the write path we already trust.

**All 36 catalog roles are now wired end to end (2026-09-19):** `tools/playstyle_catalog.py` is
the single source of truth for the full `Playstyle.bin` decode; `playstyle_bits.py` (primary) and
`playstyle_secondary.py` (secondary) both write straight from it — no runtime dependency on
`samples/editor-bundled-players.csv` or `build/tree_base` any more. ML.Core's `RoleCatalog`, ML.App's
`TacticsViewModel`, ML.Web's `Tactics.razor.cs` and `tools/assign_roles.py` are kept in sync by
hand (all four lists must match). **Fixed a real bug in the same pass:** indices 9/16/17 (The
Destroyer, Attacking GK, Defensive GK) render as "Basic" when written to the *primary* field —
confirmed against every matching record in Konami's own export — so a goalkeeper has no meaningful
primary style at all. The three apps used to offer "Offensive/Defensive Goalkeeper" as a primary
pick for GKs; selecting it looked like it worked but never reached the game. Removed from all
Primary catalogs; a goalkeeper's one real style choice is now only the secondary/out-of-possession
picker (Attacking GK / Defensive GK / Sweeper GK / Build-up GK / High Line GK — the last of which
was also missing from every app's role list and has been added).

## Tier 2 — new tables, structurally simple, high value

- **Coach.bin (47KB) + CoachTactics / CoachTacticsFormation / CoachLink** — assign *managers* to
  clubs and set their formation/tactics (names already done; assignment + tactics next).
- **Stadium.bin / StadiumOrder / StadiumWeight** — which stadium each club plays in.
- **Ball.bin / Weather.bin / BallCondition.bin** — match ball & weather.
- **Country.bin (30KB) / City.bin** — nationality & city catalog labels.
- **PlayerSkill.bin / Playstyle.bin (872B)** — the skill/style *catalog* (the enum definitions
  themselves) — read to build authoritative name↔code tables for the Tier-1 editor.

## Tier 3 — cosmetic / visual (bigger RE, partly mapped)

- **PlayerAppearance.bin (746KB)** — faces, hair, skin, build.
- **TeamColor.bin + uniform/team/** — kits & colours (`realUni` partly mapped; write gate failed
  once — see [[derby-kit-formats]]).
- **BootsList (69KB) / GloveList + Boots / Glove** — boots & gloves assignment.

## Tier 4 — competition structure (risky; cross-referenced tables)

- **CompetitionTournament\* / CompetitionEntry / CompetitionUnit / CompetitionBerth** — reshape
  leagues & cups (add teams, change formats). Multiple tables reference each other by index; high
  corruption risk — round-trip proof mandatory and structural rebuild forbidden.

## Recommended order

1. **Tier 1 player editor** — highest ROI, write path proven, all fields decoded (this includes the
   in/out-of-possession playstyles just located). Ship a `player_edit.py` bitfield writer + a Squad
   card edit screen.
2. **Tier 2 coach assignment + stadium** — small tables, big "it's a real league" payoff.
3. **Tier 3 visuals** — only after the appearance/kit write gates pass round-trip.
