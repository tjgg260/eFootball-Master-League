# eFootball Game Plan menu → data map

How we "see" the game's tactics journeys without running it: the menu **text tree** is fully
present in the extracted English string table (`build/all.str.bin`, from
`dt261_eng_console_win.cpk :: eng/string/all.str`), and the **data side** of each journey is in
the pesdb bins. UI layouts themselves are UE5 pak content (not readable, not needed).

Legend: ✅ = writable team data, covered in the app · 🔒 = per-user Game Plan / save-side
setting — not team data, the player sets it in-game · 🧪 = writable, bit meanings pending
in-game calibration.

| Game Plan item (game's own label) | Where it lives | Status |
|---|---|---|
| Set Formation (drag positions) | TacticsFormation.bin — 11 rows/fid: role u32@0, y@8, x@9 | ✅ Formation tab (drag board) |
| Fluid Formation (Attacking / Defensive formations) | The team's fid PAIR in Tactics.bin (phase 0/1) | ✅ two shape tabs (game wording) |
| Team Playstyle (6 styles) | Tactics.bin style byte @8 (0–5) | ✅ Tactics tab, verbatim movement pages |
| Playing Style per player (Goal Poacher…) | Player.bin 5-bit field @46 | ✅ Player Roles tab, verbatim + compatible-position gating |
| Captain | PlayerAssignment role flags — v1 byte22 bit 0x20, v2 u16@18 bit 9 (vendored semantics) | ✅ NEW: app captain compiles to the in-game armband |
| Set-piece takers (FK / CK / PK) | PlayerAssignment role-flag bits 0x01–0x10 (6-bit field, per-team sets like {15,16,32} fit taker roles) | 🧪 plan item A4: calibrate bit meanings in-game, then a Takers picker |
| Preset Tactics 1/2/3 (Main / Sub / Sub-Attacking) | Team DB ships TWO records per club (our pair); the third is user Game Plan | ✅ two presets / 🔒 third |
| Individual Instructions (4 slots, e.g. Counter Target) | User Game Plan (save data), not pesdb | 🔒 |
| Substitutions (auto subs, slots) | User Game Plan | 🔒 |
| Offside Trap (auto) | User Game Plan | 🔒 |
| Preset Tactics auto-switching | User Game Plan | 🔒 |
| Set Piece Strategies (FK/CK routines) | User Game Plan | 🔒 |
| Attacking/Defensive Playing Style (per-player pressing behaviours) | Dream-Team-side player data; no pesdb field located | 🔒 for now |

Dead ends confirmed (research closed):
- `CoachTactics.bin` is empty (0 bytes) in the current build.
- **Fluid Formation ON/OFF is NOT in the team data.** Triple-verified: Tactics.bin bytes 10-11
  are zero across all 1,780 records (and an in-game write test changed nothing); no Team.bin
  byte distinguishes El Jadida VB (id 6261) — the ONLY club of 890 that ships different
  attacking/defensive geometry — beyond continuous-value coincidences. The toggle lives in the
  user's own Game Plan save. We ship the two shapes; the player flicks the switch in-game.

The 🔒 rows are the honest boundary: they're the player's own in-game Game Plan, saved per
user — exactly the settings you'd expect to touch on the sofa, not in the front office.
