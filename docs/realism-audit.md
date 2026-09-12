# eFootball realism audit — what's moddable, and what to change

A full accounting of eFootball 2027's gameplay-moddable surface (dt270 data + eFootball.exe) and
a prioritised plan for making it play as close to real football as possible. Grounded in the
session's reverse-engineering; every lever cites its surface, status, and confidence.

## The two surfaces

| Surface | What it is | How you change it | Risk |
|---|---|---|---|
| **dt270** | `dt270_console_all.cpk` gameplay data — 12 files, 245 objects, ~893 gameplay-relevant fields | `gameplay_tune.py set/apply` (edit by name, re-pack) | None — data only, reversible, patch-proof |
| **eFootball.exe** | The engine — 221 mapped levers across 14 subsystems | `exe_patch.py` on-disk hex, or code caves | Denuvo may reject a modified exe (crash/no-launch, offline, no ban); reversible via pristine backup |

**Rule of thumb:** prefer dt270. It's safe, reversible, and survives Konami patches. Reach for the
exe only when the behaviour genuinely isn't in the data (kick error, AI thresholds, difficulty).

Coverage: 8 of 14 exe subsystems well-mapped, 6 partial. dt270 is fully decoded (every field named).

---

## What makes eFootball feel un-real (the core diagnosis)

Reverse-engineering surfaced five structural reasons the stock game feels arcade, each with a fix:

1. **Nobody makes technique mistakes.** In ordinary play the kick-error ceiling computes to
   *exactly 0.000°* — identically for a 45- and a 99-rated player — because ability only ever
   multiplies a *situational* difficulty term (`term = (0.1 + 0.6·(1−ability)) · difficulty`), and
   in a routine pass the difficulty is zero. Poor technique literally cannot cause an error.
2. **The ball is magnetised to players.** First touch corrals almost anything; loose balls snap
   back to feet. Real football lives on the loose ball.
3. **The CPU is perfectly deterministic.** Its decision scoring contains no randomness — same
   inputs, same choice, every time. Robotic, predictable, never a moment of madness.
4. **Ratings are compressed.** Base rating has only 5 discrete steps (5.0–7.0), so everyone
   clusters at ~6.5 regardless of performance.
5. **Fouls are free.** Fouls carry zero rating weight and injuries only trigger on specific
   tackle animations.

The realism project is, in essence, undoing these five.

---

## Priority tiers (what to change, in order)

### TIER 1 — the biggest realism wins (mostly proven, low risk)

**1a. Everyday technique error** *(exe, proven, APPLIED — `technique-realism.json`)*
The stock kick-error model only ever computes error as `term = (0.1 + 0.6·(1−ability))·D`, where
`D` is a *situational* difficulty; on a routine pass every `D` is zero, so error is exactly 0.000°
for a 45- and a 99-rated alike. The fix is **not** to force error onto stationary balls (an early
NOP at `0x14401c1fc` did that and over-taxed simple square passes) but to **lower the difficulty
thresholds** so ordinary on-the-move match passes cross into the error zone, scaled by both ability
and how hard the pass is — while a settled/standing ball still gives `D=0` and stays clean. Six
surgical constant-repoints, all verified end-to-end against their constant cells:

| Site | Lever | Change | Effect |
|---|---|---|---|
| `0x143eb867d` | sprint-exertion meter fill gate | 17.5 → 11 km/h | meter fills from jogging pace, feeding the run ramp |
| `0x14401c15a` | run/turn difficulty ramp low bound | 22 → 15 km/h | a running pass now carries `D_run` |
| `0x14401c1dc` | ability slope on the run penalty | 0.6 → 0.75 | widens 60- vs 90-rated spread |
| `0x14401f2a6` | first-time / incoming-ball-speed window | 60 → 40 km/h | a first-time strike on a normal pass now has risk |
| `0x14401f29d` | max cleanliness lost to ball speed | 0.37 → 0.5 | (ability gate W=0.95f preserved) |
| `0x14401cf37` | ability slope, kick-type/bounce/speed | 0.2 → 0.5 | difficulty of strike separates good from bad |

Quantified (Monte-Carlo of the exact Gaussian): jog-and-pass ab60 E[dev] 0.74° / P90 1.5° (26–53 cm
off at 20 m) vs ab90 0.30° / 0.64° (10–22 cm); running pass ab60 4.1° / 1.44 m vs ab90 1.23° / 43 cm
(3.3× spread); first-time on a 60 km/h pass ab60 errMax 4.7° vs ab90 1.2° (5.9× spread). Standing/
walking stays 0.00 for everyone. Note the ceiling is already biased sideways not vertical
(`errMax_XZ = (1−c)·60°` via sideways-fix, `errMax_Y = (1−c)·20°`), so error reads as horizontal
spray. The two remaining factor functions (`0x14401ca10` kick-type flat-base 0.4→0.3, height ramp
top 0.435→0.25 m, speed ramp 50→40; `0x14401f770` skills 0.75→1.0) can compound further — staged,
not yet applied.

**1b. Guaranteed error floor** *(exe, proven, ready)*
Normal kicks have a "weight" of 0, so error is *purely* Gaussian — most kicks land near-perfect.
Forcing that weight above 0 gives every kick a non-zero minimum error, so nothing is ever
pristine. The Gaussian also concentrates near zero; widening its sigma (`0x14401b3a7`) spreads
outcomes toward the ceiling.

**1c. Steeper ability gradient** *(exe, proven)*
The accuracy curve (`0x143ed72ba` slope, `0x143ed72f2` base) sets how fast error falls with
ability. Steepen the low end so a 60-rated is clearly worse than an 85-rated. (Earlier I
*flattened* this — wrong instinct; realism wants a bigger spread, not a smaller one.)

**1d. Pass/shot power error** *(exe, proven, APPLIED)*
Speed error `(1−ability)·0.4` at `0x14401b3d6` — over- and under-hit weight of pass, the single
biggest real-life differentiator between passers. Already the most convincing lever in testing.

**1e. Worse first touch / freer ball** *(dt270, proven, APPLIED)*
`trap.ballControlRate` (0.65) widens the first-touch error; `trap.reachOut.reach` (0.6) cuts
magnetic stretching; `ball.grounderFrictionRate` / `frictionRollRateStop` let loose balls run
into space; `ballplayer.touch0` carry distance de-magnetises close control.

### TIER 2 — AI realism (mixed status)

**2a. Non-deterministic CPU decisions** *(exe cave, designed + verified, not built)*
The CPU's candidate-action scores (`0x143df127b`) are deterministic. A verified code-cave design
multiplies each score by a random ±20% (own seed buffer, seeded per match from
QueryPerformanceCounter) so marginal decisions flip — the CPU stops always picking the optimal
move and occasionally does something human. Highest-impact single AI change.

**2b. Difficulty table** *(exe, proven — all 44 rows named)*
Table B at `0x146c06f40` (GetParam `0x1442e48f0`): 44 rows × per-level columns. Row 0 = reaction
delay frames, row 18 = attacking-action probability, plus commit%, marking, line control. This is
the richest single dial for CPU sharpness — e.g. give Superstar realistic reaction latency instead
of frame-perfect. There's a hidden LEGEND column and empty sub-levels to fill.

**2c. CPU shot/cross selection** *(exe, proven)*
Shot-range gate at 38 m (`1444 = 38²`), cross gate at 18 m. Lower them so the CPU works the ball
closer instead of shooting/crossing from anywhere. Shot desirability is weighted by the kicking
attribute — good for realism, keep.

**2d. Team shape to tactics** *(dt270 + exe, well-mapped, partially APPLIED)*
`basePosition` (13 confirmed-live fields): defensive line, compactness, width, pressing/retreat
distances, marking persistence, `lineControl`/`adjustGapDfLine`. Make lines hold shape, forwards
track back, pressing situational rather than constant. (Note: several `basePosition` fields are
*inert* — no reader in this build; the live set is documented.)

### TIER 3 — physicality, fouls, discipline

**3a. Fouls cost rating** *(dt270 formula, proven, APPLIED)*
Fouls weighed 0 in the rating formula; set to −8 (= cancels a successful tackle). The foul row
(`0x3c`) already tracks mistimed tackles/slides — no cave needed.

**3b. More bookings + earlier whistle** *(exe, proven, APPLIED)*
Card-escalation roll 30% → 40% (`0x143c84d2e`); advantage window shortened so the ref whistles
sooner. Harder shoulder/tackle contact via the post-contact speed clamp (35 → 42 km/h).

**3c. Injuries** *(exe, proven — but capped)*
Deterministic: an injury only fires when the tackle animation is "injury-tagged" (no probability
roll, and durability does *not* gate it). Two levers maximise them *within that ceiling* (NOP the
severity filter `0x143fbfa51`; widen the window `0x143fbf973`). Going beyond needs editing the
animation event tables (CPK/anime data), not the exe.

### TIER 4 — ball feel and set pieces

**4a. Ball physics** *(dt270, proven)*
`ball` object: Magnus curl, drag, bounce (`boundRate[6]` per pitch condition), spin decay, roll
friction. **Caution: raising `magnusRate` amplifies backspin into gravity-cancelling LIFT — balls
balloon.** Keep it near stock (0.035). The engine is Unreal Z-up (X fwd, Y right, Z up): spin
about Y = lift, spin about Z = horizontal curl — relevant for any spin work.

**4b. Knuckle / wobble on mishits** *(exe + dt270, proven, APPLIED — `knuckle-mishit.json`)*
The engine has a full knuckleball system (a 6-keyframe spin-vector table it snaps between
mid-flight). The kick code *stripped* knuckle off every mis-struck ball (`0x144017656`, forcing
normal spin kind 7 on every non-type-4 kick); the applied 7-byte edit sets nonSpin flag=1, kind=0
and falls through to the engine's own knuckle route, so shanks/scuffs now wobble and jink laterally
and dip. Kind 0 = wide random lateral + dip-biased vertical (mean −9.4 rad/s), so it cannot
reintroduce ballooning (kind 2 = pure lift — never used). Still gated at 45 km/h by
`ball.nonSpinMin`; `loose-realism-v2` already lowered it to 25 so slow mishit passes qualify.

**4c. Shooting** *(dt270 + exe, well-mapped)*
Shot launch-speed gauge tables (km/h, by attribute × distance band), launch-elevation curves, and
the CPU aim-scatter sigma (widens for weaker CPU / worse angles). Tune shot power realism here;
keep launch elevation near stock (raising it also causes ballooning).

### TIER 5 — new causes of error not in the engine (need caves)

Real football error sources eFootball doesn't model at all — each addable via a cave at the
kick-factor fold (offending player is in scope there):

- **Fatigue** — error growing as stamina drains late in matches.
- **Sprint speed at contact** — striking at full pelt is harder.
- **First-time strikes** — no settling touch = far more risk.
- **Under genuine pressure** — proximity of a closing defender degrading the strike.

Stamina is confirmed to exist as a live per-player value; wiring it into kick error is the
cleanest new-cause cave.

### TIER 6 — match authenticity

- **Per-match RNG reseed** *(cave, designed)* — the match LCG zero-inits, so runs can repeat;
  reseed from a timer so games differ.
- **Rating spread** *(dt270, proven, APPLIED)* — base band 5.0–7.0 → 3.0–9.0 (13 steps), percentile
  penalty ladder re-spread, clamp 0.5–10, fouls −8. Ratings now use the full range.
- **Goalkeeper realism** *(exe, partial)* — save reach, rush-out trigger distance, parry-vs-catch,
  distribution. GK decisions gate on the `gk_decision` attribute; no dt270 GK object exists, so
  this is exe-side and only partially mapped.

---

### TIER 7 — game feel & tactical flow *(dt270, audit 2026-08-25; two packs APPLIED)*

A dedicated 8-way sweep for *feel* (tempo, weight, responsiveness, ball roll) and *flow* (pressing,
runs, transitions, lines) found that the highest-value levers here are almost all **dt270** — safe,
reversible, patch-proof — not the exe. Two coherent packs were assembled and installed
(`tools/data/tunings/game-feel.json`, `tools/data/tunings/tactical-flow.json`), stacked on
loose-realism-v2.

**7a. The ice-skater fix — momentum on direction change** *(dt270 `moveMatching`, APPLIED)*
The single biggest arcade tell: the seven sprint rows (`RouteParameter[7..13]`) had
`accRateDif60 = accRateDif120 = accRateDif180 = 1.0` — a flat-out sprinter could reverse 180° at
*full* acceleration with zero momentum penalty (walk rows 0–3 correctly carry 0.8/0.6/0.4).
`rotSpeed` was a flat **7.0 across all 14 routes**, so a sprinter pivoted as tightly as a walker.
Applied on sprint rows only: `accRateDif180 1.0→0.4`, `accRateDif120 1.0→0.65`, `accRateDif60
1.0→0.85` (a real turn-cost curve), `rotSpeed 7.0→4.5` (speed-dependent turn radius), `acc 0.8→0.7`
(earned top pace), `decMaxSpeedR/A 7/16→5.5/11` (no dead-stops from full pace); `accacc 0.3→0.2` on
all routes (softer jerk / heavier first step). `accRateDif180` and `decMaxSpeedR` have **proven**
consumers (`+0x8 @0x143ec959a`, `+0x1c @0x143ec8ee1`); the turn/accel siblings are loader-filled
(likely-live) — A/B in-game.

**7b. Organised, situational pressing & compact lines** *(dt270 `basePosition`, APPLIED)*
The earlier "13 live fields" count was an **undercount** — disassembling the zone-cover consumer
(`0x143e85de0`) proved a whole compactness cluster is read live through the cached BasePosition
pointer `[ctx+0xf0]`: `minWidth (+0x284)`, `minWidth_stratagy_defensive (+0x28c)`,
`dfLineCloseRate (+0x154)`, `lastLineCloseMaxRate (+0x218)`. Applied: `spaceCoverRate 0.45→0.55` +
`adjustSpaceCoverRate 0.23→0.30` (hold zones, don't chase), `minWidth 9→7` / `_defensive 7→6`
(compact block), `dfLineCloseRate 0.55→0.42` + `lastLineCloseMaxRate 0.8→0.62` (calmer last-line
step, no teleport-correcting), `slowDownFw false→true` (**forwards hold shape** — the single biggest
anti-swarm switch; fewer bodies press), `slowDownPassFrame 1→4` (settle around passing lanes),
`marginPredictionFrameBase 6→12` (anticipate, intercept in position rather than chase). Net: a
settled team that presses in triggers instead of swarming. **Confirmed inert — do not tune:**
`pressRate` (no reader), `forceDashDistDefence` (dead load), and the classic line-*height* fields
(`dfLine`, `defenceCompact`, `backOffsideLine`, `keepDfTargetLineX`, `dfLineWidth_*`, `lengthDf`,
`numericalRelationDefenceLine`, `slowDownDefenceLine`) — these *look* like the line dials but true
line height comes from per-match tactics + the difficulty table.

**7c. Deliberate build-up tempo** *(dt270 `grounderpass`/`throughpass`/`passget`, APPLIED)*
The pass model splits into a **shared** build stage (search cone + speed tables) affecting CPU *and*
human, and a manual-only assist stage behind `[player+0x362c]&1`. Slowing the shared stage makes
passing deliberate for both. Applied: `grounderpass.receiveSpeed ×0.82` ([36,34,32,32,34,34]→
[30,28,26,26,28,28] — slower balls are interceptable, tempo reads as build-up), `search.searchMaxDist
30→22` + `angleRate 0.4→0.6` (shorter, more lateral link play), `paraMinSpeedRate 0.8→0.65` (weak
sides build up *visibly* slower than elite — tempo varies by team quality); `throughpass`
`adjustFrameSpaceRun 15→8` + `marginFrame_min 0→18` (runs timed to the ball, with a patience floor),
`allowAngleWidth`/`searchAngleWidth`/`searchMaxDist` widened-then-shortened for run/pass angle
variety with fewer speculative line-splitters; `passget.autoFrontMove.pressure.circleDist 9→13`
(receivers check to the ball under pressure).

**Held out** (compounds the already-applied technique-error axis; apply only after the current error
level is felt in-game): `trap.ballControlRate 0.65→0.58` (looser first touch). **Guard:** `magnusRate`
0.035 and all launch-elevation/spin fields left untouched (the ballooning path). `ballForceDirect.use`
stays `true` (flipping it off removes forced control → uncontrollably loose).

**Exe levers found but not applied** (runtime-only under Denuvo; WriteProcessMemory untested): a
global km/h→frame locomotion converter (`0x143c65890`, the closest thing to a true game-speed knob),
the CPU AI decision cadence (`0x148c22ac0`, 54→27 Hz for a less frantic CPU), the off-ball-run
acceptance gate (`0x143df1384`, `score>0` — raising it makes the CPU offer fewer, better runs), and
the ActionPress engage radius (`0x146b22a4c`, 6.5 m). The **54.0f float** (`0x148c22abc`) *looks* like
a game-speed slider but is a frame-rate reference — a documented trap, leaving it alone.

### TIER 8 — frontier audit: shooting, aerial, set-pieces, GK, duels, dribble, stamina, referee *(2026-08-25)*

A 13-agent audit (8 explorers + a live-patch spec builder → 3 adversarial verifiers → synthesis)
swept the remaining realism surfaces. Headline: the biggest *safe* wins are **dt270**; almost every
**exe** constant edit turned out to reference a **coalesced `.tls$` literal** shared by hundreds–
thousands of sites, so an in-place edit is catastrophic collateral — every exe lever must be an
inline immediate, an indexed-table entry, or a **disp32 repoint to a private cell**, and all are
**blocked on proving `WriteProcessMemory`** first.

**8a. Shooting pace & loft** *(dt270 `shoot`, PROVEN-live, APPLIED — `shoot-realism.json`)*
Weak finishers shot as hard as elites. Cut ONLY the `*40` (weak-attribute) gauge anchors,
distance-ramped (`powerfull ×0.95→0.84`, `normal ×0.96→0.88`, `control ×0.97→0.92` across the 6
bands); every `*99` elite anchor is untouched so top lethality is preserved. **Mandatory anti-balloon
partner shipped together**: `normal_dy.gageMax 28→25`, `control_dy 26.5→24`, both
`interpolateRate 0.5→0.8` — because `asin(dy/speed)` *raises* launch angle when speed alone drops, a
pace cut without the loft cut would balloon shots.

**8b. Aerial flight — drag window** *(dt270 `ball`, PROVEN-live integrator, APPLIED — `aerial-drag.json`)*
`dragSpeedMin 57→66`, `dragSpeedMax 97→106`: floated crosses/long balls now bleed pace and drop
into the box while driven balls keep zip. Magnus 0.035 untouched.

**8c. Set-piece curl** *(dt270 `setplayGuide*`, PROVEN-live loader, APPLIED — `setpiece-curl.json`)*
All curl on `sideSpin` (the safe Z/horizontal axis): corner + near/mid FK `base ↓, paraRate ↑`
(3.5/4.5) so specialists whip it and journeymen deliver flat — an ability-gated swing. Long-FK and
goal-kick `backSpin` **cut** (5.0→3.5, 4.0→3.0) as anti-balloon. `topSpin` deliberately left alone
(Y-axis caution). `cornerkickDefenceMFWidth 10→8` tightens the box.

**8d. Staged dt270 (apply-and-observe, one at a time)** — built, not yet applied:
`aerial-pitch-spread.json` (the `ball` `[6]` bounce/roll-per-pitch spread — confirm which index a
default match uses first), `duels-firsttouch.json` (heavier receptions on dropping/contested balls;
`trap.reactionTrapBall` leaves are likely-live), `dribble-feel.json` (`Feint.rate 0.9→0.72`,
`reachOut.reach 0.6→0.42`, no-90°-spin — note on-ball dribbling is attribute-*uniform* in the
constants; elite-dribbler separation must come from roster attrs + skill-cards, not these),
`referee-slides.json` (low confidence — sibling `pressRate`/`forceDashDistDefence` are dead loads).

**8e. Exe plan — GATED behind the WPM canary** *(runtime-only, Denuvo; nothing applied)*
Adversarial verification turned an ambitious list into a safe, ordered plan:
- **order 0 — canary**: `ActionFeint` lateral-aim cell `0x146bc6b14` 44.5f→30f — verified **exactly 1
  referrer** (genuinely private), a `.tls$` **data page**. Materialised as
  `tools/data/patches/live-canary-actionfeint.json`. Its whole purpose: prove `WriteProcessMemory`
  works on this build (probe → `--dry-run` → guarded write → observe → `restore`). **Everything else
  is blocked on this.**
- **Write-ready once the canary passes** (inline immediates / indexed table, no repoint): deflecting
  parry-placement base (`add …,0x49 → 0x30`, makes rebounds go to danger for poor keepers vs safety
  for good), the CPU dribble-command difficulty-table row, card-rate re-tune.
- **Repoint family** (need a private cell allocated per site): GK save-read spread (0.9+0.3·x →
  wider), clean-catch reach 6.5→5.5 (restore rebounds), CarryBall burst 1.3→1.13, keeper depth/PK
  sector/distribution, and the **off-foot header penalty 6.0f — which shares its cell with the
  kick-error sigma**, so it *must* be repointed.
- **Runtime globals / cave** (last): stamina timescale/onset globals (read-live-first), and the
  fatigue→kick-error **code cave** (design-complete, not byte-ready — needs the match-long stamina
  offset located and an emulated dry-run).

**Adversarial safety catches (dropped/corrected):** severity-differentiated bookings (jump tables are
already collapsed — would need new code), weak-foot shot penalty (wrong semantic + shared cell),
contact-foul sensitivity tables (no consumer), the `t@0x1` placeholder canary (faults). Cross-lever
shared-cell aliases flagged: `11f`/`20f`/`135f`/`6.0f`/`0.3f` cells each back **two** different
levers — in-place editing one silently corrupts the other.

**Still unmapped (next frontiers):** GK save-QUALITY state codes `0x40a..0x40e` (clean vs spill vs
parry — blocks attribute-linked rebounds, the biggest GK fix); the catch-vs-parry-vs-punch selector;
mid-match **fatigue consumers** (fatigue is near-cosmetic until wired — needs the `+0x30f4` xref and
the `+0xb38` speed clamp); momentum-on-contact (`VelocityRagdollReflector` reads velocity from
pointers, scalar is registry-sourced — no code immediate); offside precision; an on-ball
dribbler-vs-tackler contest roll (doesn't exist — would have to be injected); and the **WPM
prerequisite** gating the entire exe program.

## Reading the results back (closing the loop)

Not a gameplay change, but essential for a realistic career: `stats_read.py` reads every player's
match rating + raw counters (passes attempted/completed, tackles, dribbles, touches, cards, balls
won/lost) from memory, read-only. Pass completion % etc. fall straight out. See
[player-stats.md](player-stats.md).

---

## Recommended "hyper-realism" build order

1. **Kick error** (1a all four gates + 1b floor + 1c gradient + 1d power) — the foundation; makes
   ability and difficulty matter on every touch.
2. **Free ball + first touch** (1e) — de-magnetise; create loose balls.
3. **CPU non-determinism** (2a cave) + **difficulty table** (2b) — human, fallible CPU.
4. **Team shape to tactics** (2d) — coherent, tactical AI movement.
5. **Fouls + physicality + injuries** (3a–3c) — consequence for mistimed challenges.
6. **Knuckle/wobble** (4b) — mishits look mis-hit.
7. **New error causes** (5, caves) — fatigue, sprint, first-time, pressure.
8. **RNG reseed** (6) — every match different.

Tiers 1–3 are almost entirely proven and low-risk (dt270 + verified in-place exe edits). Tiers 5
and the caves are where the real research remains.

## Hard-won cautions

- **Verify axes and directions in-game.** Static analysis was confidently wrong twice this
  session (lift-vs-curl inversion; Y-up vs Z-up). The game is the oracle — test one change at a
  time.
- **`gameplay_tune.py apply` rebuilds from pristine**, discarding formula-string edits stacked by
  `rating_weights.py`. Apply numeric tunings first, formula strings last.
- **Some `basePosition` fields are inert** (no reader). Don't tune dead levers — the live/inert
  split is in `docs/exe-gameplay-map.md`.
- **`magnusRate`/launch-elevation cause ballooning** past small increases. Keep near stock.
- Everything is reversible: `exe_patch.py restore` + `gameplay_tune.py restore`.
