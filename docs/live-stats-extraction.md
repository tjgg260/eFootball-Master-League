# Live per-player match stats — extraction plan

eFootball computes a per-player match rating, so the raw counters that feed it (passes
attempted/completed, tackles, shots, duels, distance…) **exist in memory during the match** —
they're just never written to a file or shown. This is how we read them out. Read-only
(ReadProcessMemory only — we never write to the game), same mechanism as `find_aes_key_live.py`.

## Why this works (and the exe route doesn't help here)

- The rating is derived from counters → the counters are live game state in RAM.
- We don't need to understand the engine C++ to READ that state — just locate the struct.
- The rating value itself is on screen, which gives us a known anchor to search for.

## Phase 1 — locate the stats struct (one-time mapping, a few test matches)

1. **Anchor on a value we can see.** At full time a player shows a rating, e.g. `7.5`.
   Stored as a 32-bit float (`7.5f = 0x40F00000`) or fixed-point — we test both.
2. **First scan:** `mem_scan.py find 7.5 --type f32` records every address holding that value.
   Thousands of hits at first.
3. **Next scan:** play again (or a different player), rating changes to e.g. `6.5`;
   `mem_scan.py filter 6.5` keeps only addresses that moved to the new value. Two or three
   iterations collapse it to the real rating fields.
4. **Find the array.** All 22 players are almost certainly an array of identical structs.
   Once two players' rating addresses are known, the delta between them = the struct **stride**;
   the lower address ≈ the array **base**.
5. **Map the offsets.** Within one struct, the counters sit near the rating. Cause a known
   event (e.g. deliberately complete ~10 passes with one player) and see which offset
   increments by ~10 → that's `passes_completed`; repeat for attempts, tackles, shots, etc.
   A couple of matches maps the whole struct layout.
6. **Anchor it stably.** Convert the absolute address to either a pointer chain from the module
   base or an AOB (array-of-bytes) signature, so it survives restarts. Save the map to
   `build/stats_map.json`.

## Phase 2 — live read (every match, automatic)

- A read-only helper resolves the anchor, reads all 22 structs at (or just after) full time,
  and writes per-player rows into a new `match_player_stats` table
  `(fixture_id, player_id, passes_att, passes_cmp, tackles, shots, shots_on, duels, distance, rating)`.
- The app then shows **real** pass completion %, tackle success, shot accuracy per player —
  no OCR, no typing. Team aggregates cross-check the OCR'd stats screen.

## Honest limits

- Phase 1 is real reverse-engineering and needs the game running + several correlation matches.
- Struct offsets can shift on a game patch; the AOB signature reduces (not eliminates) re-mapping.
- Read-only and non-injecting → safe, offline-only, no game files touched.
- This is the ONLY route to per-player pass completion: it is never in a file and never on screen.

## Tooling

- `tools/mem_scan.py` — read-only Cheat-Engine-style scanner: `find <value>`, then `filter
  <value>` to narrow, `dump <addr>` to inspect a struct region. Phase-1 workhorse.
- (later) `tools/stats_read.py` — resolves `build/stats_map.json` and dumps all 22 structs to
  the DB each match. Phase-2, built once the map exists.
