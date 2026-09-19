# Gameplay realism — the queue (owner's list, 2026-09-18)

**Work one item at a time.** Running five in parallel produced results that each needed corrections
to three others, and cost more than it bought. Each item below is finished (spec applied, tested in
play, verdict recorded) before the next starts.

Background for all of it: [docs/match-ai-decoded.md](match-ai-decoded.md). Its *Corrections* and
*Refuted* sections are mandatory reading before proposing anything off-ball — between them they
cover roughly a year of misdirected tuning.

## The five, in the owner's order

### 1. More randomness in AI decisions + varied off-ball movement from all players — IN PROGRESS
The decision layer is provably deterministic: `ChanceSpaceRun::vf5` = `100 + attackDir*player.x +
roleBonus` (whoever is furthest up the pitch), `DiagonalRun::vf5` = depth behind the line, and **no
RNG is reachable from any selector** (943k-edge call-graph closure, positive control at depth 4 on
the kick builder). So this cannot be tuned — it needs code.

Two independent routes, and they compose:
- **score term** — add heterogeneity + genuine per-decision variation to `vf5`. First attempt
  (`score-heterogeneity.json`) is **defective**: it made the winner *less* varied than stock, and its
  "noise" was a static spatial field, i.e. a near-constant DC offset per player rather than
  arbitrariness. Hook site `0x143df5d6a` is sound and re-usable (the 0.0 sentinel path bypasses it
  structurally).
- **run kind 6** — a fully implemented movement pattern (`vf6` geometry `0x143df1cc5`, executor
  handler `0x1441f360b`) that is **never tagged** in this build. Adds a run type that does not
  currently exist, rather than re-shuffling who makes the existing ones. Unclaimed.

Also here: `linebreak-1/2/3.json` are written but **defective** — the score hands the run to the
goalkeeper (`runway = (offsideLine - player.x)*attackDir` ranks the team backwards) and the borrowed
eligibility builder has no role filter. The memory-safety work behind them is sound and reusable.

### 2. The ability to trigger runs (tap LB = run, tap RB = overlap/underlap)
Investigation running. The feature **already exists** and is merely gated on the pass button:
`ThinkUnitPassAndGo` slot 17 (`0x1440e5280`) produces both the L1+A "go" and R1+A "overlap"
behaviours — there is no `ThinkUnitOverlap` anywhere in the ~74-class pad family. Control map
(from the game's own config screen): RT=Dash, RB=Special Controls, LB=Cursor Change, LT=Finesse
Dribble; A=Low Pass, B=Lofted Pass. Both shoulder-alone functions are holds, so a **tap** is free.
Open risk: whether Cursor Change fires on the press edge (a collision), and whether the pad layer
does tap/hold discrimination at all.

### 3. A freer ball — ricochets, poor touches, realistic pass and shot error
Partly built already (kick-error model, `bobble-pitch`, first-touch work). The owner's standing
ruling: **do not produce indiscriminate bad touches — create the conditions for looseness.** Keep
`ballControlRate` below 1.0, because at exactly 1.0 a BC99 player is mathematically incapable of a
bad touch.
**Open and unproven, and it gates "ricochets":** does the ball deflect off *non-tackling* players at
all? Limb collision parts exist (21-slot array at `player+0x2f18`, per-frame physics filter groups
via `0x144fa58d0`) but the consequence for loose balls has never been tested.

### 4. Heavier players and realistic turning
Largely untouched this session. `moveMatching` (accRateDif180, rotSpeed) is the right surface and
nothing found contradicts the existing edits. Note the finding that **turning is NOT the cause of
the CB cushion** — the defender picks a stand-off target before any locomotion happens, so agility
only decides how fast he reaches a target he already chose.

### 5. More fouls and physicality; players properly falling over, not stumbling
Contact lockout is **decoded** (see the doc): `canStart` slot 2 refuses almost everything outright
during a stagger; `canCancel` slot 14 gates the survivors on a keyframe baked into the animation.
Seven specs written, **none shippable** — the real keyframes live in runtime-loaded motion assets,
so effect sizes were guessed, and 10 of 11 stagger motions have ≤1 cancel key which makes the
obvious fix a probable placebo.
**Blocker to clear first:** decode the motion assets (filenames likely hashed, as the dt250/dt251
menu JSON was). That turns every spec here from guessed to computed, and would give the lockout's
actual length in seconds.
`falls-slide-tackle-contact.json` is the one unapplied falls pack that genuinely puts more bodies on
the floor and touches no lockout — safe to test alongside anything.

---

## The subsystem map (in progress)

Finishing the map before more feature work, one subsystem at a time. Each produces a chapter in the
shape of [match-ai-decoded.md](match-ai-decoded.md): the machine as prose with addresses, a tunables
table with route and pool-cell sharer counts, plus explicit *Corrections* and *Negatives* sections.

| # | subsystem | classes | state |
|---|---|---|---|
| - | `match::ai` — off-ball movement | 26 | DONE — [match-ai-decoded.md](match-ai-decoded.md) |
| - | `match::referee` — fouls | 5 | DONE (in the same chapter) |
| 1 | `match::ai::bp` — the ball carrier | 65 | **DONE** — [ball-carrier-brain.md](ball-carrier-brain.md) (1,658 lines). 9 probes/verifiers + 2 repair rounds; re-verify clean of critical/major. 65-row class-status table; Corrections section records every wrong turn. |
| 2 | `match::player` — the executors (run geometry, marking, kicks, pass reception, ~30 keeper actions) | 109 | **PARTIAL — architecture COMPLETE, behaviour OPEN** — [player-executors.md](player-executors.md). Hand-decoded after the workflow died 4x on the spend limit: the full **102-entry subobject map** (99 named, from the constructor's own unwind funclets, bounded by chained-unwind extents), the two base ctors that classify each class's contract, the 23-slot contract (slot 20 = the movement-target emitter), the two-level run dispatcher, and a three-control proof that the action-id dispatch is **not** an offset table. Still OPEN: run geometry + cross-role, standoff origin, offside, kicks, the PassGetRoute receivers, the keepers. The job was rewritten behaviour-only (4 probes) and is ready to launch — do **not** resume `wf_d1fc80ce-b63`, that script is superseded. |
| 3 | `match::registry` — the shared-state BLACKBOARD (216 RTTI names = ~45 data records x accessor templates: UTeamAIInfo, UOrderInfo, UPlayerInfo/Move, URandomInfo, VPadInput->VCommandInfo, UMatchEnv...) | ~45 records | staged (`decode-registry-blackboard.js`). Chapter is a STRUCT CATALOGUE not a decision machine: layouts + writers/readers, the per-match TACTICS landing map, the live LCG state, the pad->command channel (trigger-run hook point). `AnalyzeDetailInstruction` may be the tactical-instruction channel the carrier chapter concluded did not exist. **PROMOTED ahead of anime 2026-09-19 (owner):** it is the blackboard every other subsystem reads, and it alone unblocks `team+0xb3c4` (the strongest on-ball lever found, unusable until named), the pad->command channel the trigger-run feature needs, and a possible correction to the finished carrier chapter. **Skeleton DONE 2026-09-19** — [registry-blackboard.md](registry-blackboard.md): 49 record names, 26 proven byte sizes via the registrar `0x145340ca0` (size is the alloc + memset length, so allocation-accurate), Copy-vs-Pointer access discipline, array dimensions, and the finding that all five of the carrier chapter's unidentified `team+0x...` fields fit inside the 48,524-byte per-team `UTeamAIInfo`. |
| 4 | `match::anime::action` — animation gating, contact, technique, first touch, GK saves | 106 | staged (`decode-anime-actions.js`); includes a dedicated MOTION-ASSET probe to locate MbInfoManager's keyframe table and give the post-tackle lockout in real seconds (unblocks item 5's seven contact specs) |
| 5 | goalkeepers | — | **collapses into 2 + 3**: ~30 `ActionKeeper*` executors are probed in subsystem 2, the 50-method `goal_keeper::SavingBase` save family in subsystem 3. Remaining work = one short synthesis chapter (`docs/goalkeeper.md`) stitching both, no new decode. |
| 6 | set pieces | spread | classified by 2 (`ActionCornerKick/FreeKick*/PenaltyKick/Throwin/Kickoff/GoalKickLong`) and 3 (the 17-class anime Restart family, Wall* jump decision and PK decoded there). Remaining decode: `match::ai::bp::ThinkUnitSetPlay` (constructed separately at 0x1456aecb1), the pad set-piece ThinkUnits, and the referee's set-piece placement. Smaller than originally planned. |

Then **regenerate `build/gameplay-catalog.html` subsystem-first** rather than field-first, so
"can a striker make a diagonal run" is a lookup. The current catalogue is dated 2026-08-23 and
predates everything learned since.

### 7. After all six: resolve the 5,362 UNLOCATED dt270 fields (owner's call, 2026-09-18)

`build/dt270_liveness.json` classifies 21,977 fields: **12,008 read**, **4,607 unread**,
**5,362 unlocated**. The distinction matters:
- *unread* — we searched and found no reader. Probably genuinely dead.
- *unlocated* — we could not resolve where the field sits, so **no search was possible**. These are
  UNKNOWN, not known-dead, and some are live levers we simply cannot see yet.

Deliberately scheduled LAST, and that ordering is doing real work: every subsystem chapter locates
dt270 readers as a side effect, so the 5,362 will shrink on its own as 1-6 complete. Attacking it
now would mean re-deriving by hand what the chapters are about to hand over for free. What remains
afterwards is the genuinely hard residue, and worth a dedicated pass.

Two things stay out of reach even then, and should not be promised: animation motion assets (the
contact cancel keyframes live in runtime-loaded CPK data, not the exe — which is why none of the
seven `contact-*.json` specs are shippable), and anything computed at runtime from the save, the
squad or the match state rather than stored as a constant.

## Gaps the owner's list does not cover

These came out of this session's decoding and are not on the list. Flagged, not started.

- **Penalties are systematically suppressed.** The foul model is fully mapped and deterministic (no
  RNG): scorer `0x143d88fe0`, level fn `0x143d861f0` with threshold **40 outside the box and 60
  inside**, cards at 80 and 110, and a veto that only lets a foul stand if the tackler won **less
  than 70% of the ball — 40% inside the box**. That is a deliberate anti-penalty bias in two places.
  If item 5 is about realistic fouls, this is the most targeted lever in the game and it is two
  constants.
- **Goalkeepers — entirely unexamined.** No GK positioning, error, distribution or shot-stopping
  work has been done at any point. Probably the largest untouched realism surface.
- **Set pieces — unexamined.** Corners, free kicks, throw-ins.
- **Ability barely reaches decisions.** Not one quota, rank compare, run selector or difficulty row
  reads an attribute; four of five run selectors call no ability getter at all. The one real
  ability-scaled defensive term is `attr(0x17)` in `0x143da92c0` (sprint trigger 15.0 m at attr 40 →
  7.26 m at 99). Spreading it across `master.db` is the highest-value patch-proof realism lever
  available — but it is database work, which the owner has deprioritised for now.
- **Condition / form per match.** Already a decided ruling in this project and never built. Form,
  fatigue and morale modulating attributes in the per-match compile is the cheapest route to
  match-to-match variance, needs no exe work, and survives every Konami patch.
- **Tight marking is structurally capped.** `ActionMark::vf20` re-emits the marker's destination at
  the *same radius* it was handed — radial closing is exactly 0.000 m. The marker can only aim,
  never close. Any "tighter marking" work must act on the upstream shape layer, not on ActionMark.

## Housekeeping

- Two applied packs work by the route the owner rejected (adding runners):
  `offball-counter-early.json` (CounterSpaceRun maxSlots 1→2, binds at *every* attack level) and
  `offball-run-variety.json`. Remove before judging item 1.
- `cave_alloc.py` has no concept of exception unwinding. A cave installed as a **vtable entry point**
  that is a non-leaf frame function is an x64 ABI violation. Fine for hook caves that never fault;
  not fine for entry points. Needed for the LineBreak approach.

## Subsystem map

- **Ball carrier (`match::ai::bp`)** — [docs/ball-carrier-brain.md](ball-carrier-brain.md): plan (Image) first-match-wins, then a fixed ThinkUnit priority list (Force > RespondRequest > Special > Shoot > passes); no scoring, no dt270, randomness only in four plan rolls and the feint shortlist; Personality is per-player data the app writes. Read its Corrections before touching on-ball behaviour.
