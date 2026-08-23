# Game Plan screen — recreate-exactly brief

Source: screen recording of eFootball 2026's Game Plan (2:53, `Recording 2026-08-22 110846.mp4`,
Hull City away). This is the game's own pre-match management surface. Target: recreate it
functionally exactly in ML.Web (Floodlit skin, mouse instead of pad), replacing/extending the
current Tactics screen. Engine mapping noted per feature — everything listed has a verb already.

---

## Shell (constant across all three tabs)

- **Tab bar, centred**: `Lineup | Tactics | Team` + a settings gear. Active tab = filled pill.
- **Top-right**: `Done` (B) — exits back to the hub, saving.
- **Right rail — the OPPONENT**: club crest, name, and their full **Substitutes list**
  (position code + name, position-coloured code). Persistent on every tab: you always plan
  *against* someone. → engine: opponent from `NextFixture()`, their XI/subs from their squad
  slots, crest via `TeamLogoPath`.
- **Pitch, centre**: one full HORIZONTAL pitch. **Your XI occupies the left half**, the
  **opponent's XI mirrored on the right half** with their formation label (e.g. `5-2-3`)
  bottom-right; yours (e.g. `4-2-2-2`) bottom-left. Opponent tokens are read-only.
- **Player tokens**: face photo above a black plate — `POS  rating` on the top line, name
  beneath; green condition-arrow strip on the plate edge; captain shows a `C` badge.
  Ratings colour: white normal; position code coloured by unit.
- **Phase toggle**: `Switch ATK/DEF` (we: a segmented Attack/Defence switch). The pitch header
  flips between a magenta **Attack** banner and a teal **Defence** banner; your formation label
  AND token positions change per phase (attack shape vs defensive shape — e.g. 4-2-2-2 in
  attack, 4-2-1-3 in defence). → engine: fid0/fid1 (`OwnFormationIds`), fluid formations.
- **Bottom action bar** (context-sensitive): `Condition` (X), `Player Details` (Y) /
  `Basic Info` (X), `Recommended` (Y, Team tab).
- **Left rail — hover card**: whichever player is focused shows: face, POS + big rating, name,
  hexagon radar (SHO/PAS/DRI/SPD/DEF/STR), Height / Weight / Age / Condition arrow /
  Stronger Foot. Updates on hover of ANY token or bench row.

## 1 · Lineup tab

- **Your bench row under the pitch**: substitute tokens (kit-shirt image where no face, rating,
  name, condition arrow) in a horizontal strip.
- **Drag & drop**: hold a token to lift it (card enlarges, name highlights blue); a centred toast
  states the edit context (`Attacking Formation`); drop on a pitch spot to move, drop on another
  player (pitch OR bench) to swap the two. Swapping a bench player in = substitution into the XI.
  → engine: `SaveSquadOrder(order, manual)` + formation slot write (already live in our Tactics).
- **Player Details overlay** (Y on a focused player): left panel slides over —
  name, big `rating + POS`, **playstyle name** (e.g. Roaming Flank) + card tier, face,
  radar, **position heat-map** (mini vertical pitch, green cells = playable zones),
  Height/Weight/Age/Condition/Stronger Foot, then the **full ability list** in two columns
  with values coloured (red <65-ish, yellow 65-79, green 80+; exact game colouring: red for
  low, orange/yellow mid, white/green high). Footer actions: `Done`, **`Change to <POS>`** —
  one-tap swap of the player's registered position for this plan when he has a learnable
  alternative. → engine: `Db.Attributes`, `RoleOf`, `LearnedPositions`, appearance data.

## 2 · Tactics tab (left-rail menu with 4 entries)

Menu: **Set Formation · Team Playstyle · Individual Instructions · Sub-Tactic**.
All sub-screens keep the pitch + opponent visible on the right.

### 2a Set Formation
- Sub-toggle: **Base Team | Defensive Formation** (the two phases; LS switches too).
- **Template list**: `4-4-2, 4-3-3, 4-3-2-1, 4-3-1-2, 4-2-3-1, 4-2-1-3, 4-1-4-1, 4-1-2-3,
  3-4-3, …` — highlighting one live-previews token positions on the pitch; selecting applies it
  (players re-slot position-aware). Caption: "Set the formation when attacking."
  → engine: `FormationOptions()` templates + `SaveCustomFormation` per phase.

### 2b Team Playstyle
- List: `Possession Game, Quick Counter, Long Ball Counter, Out Wide, Long Ball, Overload`,
  active one check-marked.
- Detail pane: **"Player Movement: N" pages** — a paged (RS / dots) set of behaviour cards, each
  a heading (`When Defending`, `When Attacking`, …), Konami's description text, and a **mini
  pitch diagram of dots** showing the block shape/zone for that page (green zone rectangle +
  ball). → engine: style index 0-5 (`SaveCustomFormation` styleIndex); texts are in our
  TacticsViewModel StyleCatalog (all.str verbatim); diagrams = static per style+page.

### 2c Individual Instructions
- Left list = **your XI as face cards** (name + POS); selecting a player shows his available
  **instruction slots**: `Attack1, Attack2, Defence1, Defence2`, each set to an instruction or
  `Off` (seen: Anchoring, Counter Target, Defensive, Off).
- Detail pane per instruction: name, description ("The instructed player will refrain from
  pushing forward in attack."), and the dot-diagram mini pitch with the player's cell
  highlighted green. → engine: `InstructionOf/SetInstruction` (slots exist as meta;
  the compile writes them in-game).

### 2d Sub-Tactic — secondary tactic toggled in-match (we can stub v1 behind the same menu).

## 3 · Team tab (left-rail menu)

### 3a In-Match Roles
- List: **Captain**, **Long FK Taker**, **Short FK Taker**, **FK Taker 2**, **Left CK Taker**,
  **Right CK Taker** — each row shows the current holder's name; selecting opens a picker from
  the XI. Bottom action: **`Recommended`** — auto-assign sensible takers.
  → engine: `Captain`, `SetTaker(fk/pk/ckl/ckr…)`, recommend = highest set_piece_taking/curl.
- (PK taker follows the same pattern — include it.)

### 3b Substitutions (auto-sub behaviour)
- Options: `Off · Very Late · Flexible · Very Early`; caption "Choose how frequently
  Substitutions are automatically performed during matches."
  → engine: store as meta `autosub_<team>`; feeds the matchday sim/compile later.

---

## Parity checklist vs our current Tactics screen

Already live: drag/swap/reposition, position auto-from-zone, per-player position + both
playstyles, 6 team playstyles, captain + takers, fluid two-phase save, bench swap-in.

To reach exact parity, ADD:
1. The **three-tab shell** with the opponent rail + opponent XI mirrored on the pitch
   (`NextFixture` + their tactics via `team_tactics`/`PickBestXi` for CPU).
2. **Phase toggle** (Attack/Defence) editing fid0/fid1 separately, with banner + label flip.
3. **Formation template list** with live preview (`FormationOptions`).
4. **Hover card** (left rail) + **Player Details overlay** with ability list, heat-map,
   `Change to POS` quick-swap.
5. **Playstyle detail pages** (movement text pages + dot diagrams).
6. **Individual Instructions** (4 slots per player, description + diagram).
7. **In-Match Roles picker UI** with `Recommended`; **auto-sub frequency** setting.
8. **Condition arrows** on tokens/bench (from `player_condition` fatigue/injury).

Design language: keep Floodlit (our skin), but layout/interaction geometry copies the game:
centred tab pills, left detail rail, right opponent rail, horizontal two-team pitch, black
name-plates under faces, phase banners (magenta Attack / teal Defence).
