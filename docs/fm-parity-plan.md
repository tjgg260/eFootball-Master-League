# FM-parity plan — as close to Football Manager as the eFootball boundary allows

The target: the deepest FM-style management layer we can build, accepting one hard truth —
**once eFootball launches, the match belongs to Konami.**

## The boundary (everything here is settled fact, not to be relitigated)

**What we control BEFORE kickoff (proven writeback):** both squads' XI order, every player's
26 abilities, playstyles (except GK styles/The Destroyer — no reference bits), formation
geometry for both phases (per-team owned fids), team style byte (0–5), real team names,
real slots' faces/kits/badges.

**What we can NEVER do in-match:** touchline shouts, live subs, tactic switches from the app
(the player can use the game's own UI), reading live events. The in-game "Use Sub-Tactic"
toggle and fluid-formation-ON for AI are not data-reachable (tested).

**What comes back:** final score (OCR) + whatever the post-match screens show, entered or
OCR'd: goals, assists, cards, ratings. Possession/shots exist on the game's stats screen —
richer OCR is item C4. In-match injuries to your players persist only if you report them.

**Simulation honesty:** every match not played in eFootball is OUR Poisson sim + attribution.
Career injuries/fatigue/form are OUR model, not the game's.

## The pillars, in build order (checkbox = done; each item ends with build+tests green, smoke launch, entry in docs/overnight-log.md)

### Phase A — Staff & Scouting (FM's backroom)
- [x] (2026-08-19) A1. Staff system: `staff` table (assistant, coach, scout, physio; quality 1–5, weekly wage
      into the wage bill). Staff screen: hire from generated candidates / fire. Effects wired:
      coach quality accelerates training cadence; physio shortens injury duration; assistant
      annotates Suggest XI with reasons; scout unlocks A2 depth.
- [x] (2026-08-19) A2. Scouting: assign scout to a club → report ready in 2 matchdays → inbox + Scouting
      screen: opponent's likely XI (their squad slots 0–10), shape, style, top-3 threats.
      Assign to a player → full ability card + "fit vs your squad" verdict. Depth scales with
      scout quality (1★ = ratings only … 5★ = full abilities + condition).
- [x] (2026-08-20) A2b. Set-piece takers: calibrate PlayerAssignment role-flag bits 0x01-0x10 (FK/CK/PK
      taker roles — see docs/tactics-menu-map.md; captain bit already proven and wired). Then a
      Takers picker on the Tactics Selection tab, compiled into the game like the armband.
- [x] (2026-08-20) A3. Assistant debrief: post-match inbox analysis (where the goals came from — scorers/
      assists data), plus pre-match "assistant suggests" panel with named reasons (form/fatigue/fit).

### Phase B — The person layer (FM's morale & contracts)
- [x] (2026-08-20) B1. Per-player morale: driven by playing time (apps vs expectation), results, being
      transfer-listed, promises. Feeds the XI selector's form term; sustained low morale →
      transfer request in the inbox.
- [x] (2026-08-20) B2. Player talks & promises v1: praise/criticise after matches (bounded morale effect);
      promise "more starts" / "new contract" — tracked; broken promises hit morale hard.
- [x] (2026-08-20) B3. Contract negotiation v2: wage demands from rating/age/morale; agent counters over
      multiple rounds; squad-status promise (Star/First-team/Rotation) that B1 tracks.

### Phase C — Matchday ritual (FM's week, inside the boundary)
- [x] (2026-08-20) C1. Real calendar: matchdays get dates (league Sat, cup midweek), Calendar becomes a
      month grid; season runs Aug–May; inbox items date-stamped.
- [x] (2026-08-20) C2. Team talks: pre-match (calm / encourage / demand) and post-match choices, bounded
      effects on morale + next-match form. Assistant hints which tone fits.
- [x] (2026-08-20) C3. Opposition briefing: scout report (A2) surfaces on the dashboard before Play Match
      with a suggested counter-shape/style ("they overload the left — consider a 3-5-2").
      HONEST: suggestions configure YOUR compile only; the opponent AI in-game is untouched.
- [x] (2026-08-20) C4. Richer OCR: parse the post-match STATS screen (possession, shots, shots on target)
      into results.stats_json; show in a match report view; Stats screen aggregates.

### Phase D — The living world (FM's career gravity)
- [x] D1. League Cup: second knockout on midweek dates alongside the National Cup; continental
      qualification flags for top league finishers + prize money at rollover. *(2026-08-20 —
      generalized CupSpec machinery: two cups on distinct midweek tracks (mds 5/11/19/26/31 vs
      8/15/22/29/33), per-cup winner meta, PayPrizesAndFlagEurope at rollover, Cups screen shows
      both brackets, dashboard/inbox label the right competition.)*
- [x] D2. Manager career: reputation points from results/trophies; board patience model that
      can actually SACK you (game over screen with career summary + restart options); AI club
      job offers arriving by inbox when your rep exceeds theirs. *(2026-08-20 — pure
      ML.Core.Management.ManagerCareer (rep per result/season, ShouldSack patience rule,
      ClubWouldOffer prestige rule, ExpectationFor/TargetPosition) + 10 tests; SessionCareer.cs
      persists rep/board confidence/threat streak in meta; board expectation now derived from
      squad strength rank; sacking darkens the dashboard with a career summary and the Board
      screen grows rep/career tiles + job offers with Accept-and-reload; rollover rep swing +
      seasonal suitors.)*
- [x] D3. History & records: per-season archive (final tables, honours, top scorers) browsable
      by season; player career-history rows on the card (club/season/apps/goals); club records
      (biggest win, longest streak, record signing). *(2026-08-20 — SessionHistory.cs derives
      everything from existing tables (no schema change): ArchiveSeasons/TableForSeason (league
      membership from who actually played that season, so pro/rel years render right),
      HonoursIn, LeadersIn, PlayerCareerHistory (club per season reconstructed from the
      transfer log), ClubRecords (biggest win, heaviest defeat, longest winning run, record
      signing/sale, all-time top scorer). New History nav screen with a season picker; Squad
      card gains season-by-season career lines.)*

### Phase E — continuous (every night, no checkbox)
Keep 113+ tests green, add tests for each new ML.Core system, screenshot changed screens,
fix any bug found before starting a new item.

## Overnight protocol (for the scheduled builder)
1. Read this file. Pick the FIRST unchecked item. Implement it COMPLETELY (schema → Session →
   VM/View → wiring), following existing patterns (partial Session files, guarded bindings,
   CREATE TABLE IF NOT EXISTS migrations).
2. Gates before checking off: `dotnet build` 0 errors; `dotnet test` green; app smoke-launch
   with ML_RESUME=1 (no crash). NEVER run play_match with --install; NEVER touch the Steam
   folder or build/tree_base; master.db schema changes must be additive only.
3. Check the box with a date, append a short entry to docs/overnight-log.md (what/files/verify).
4. If an item can't be finished, do NOT check it — log the blocker and stop (don't half-land).
5. When every box is checked: delete the overnight cron job (CronList → CronDelete) and write
   a completion summary at the top of the log.
