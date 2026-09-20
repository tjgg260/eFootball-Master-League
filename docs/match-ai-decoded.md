# Match AI decoded — attacking movement, its data inputs, and the contact lockout (2026-09-18)

Produced by four multi-agent workflows (26 agents, ~7.7 M subagent tokens) over `tools/exe_map.py`,
`tools/exe_census.py`, `build/dt270_liveness.json` and purpose-built Unicorn harnesses. Every
numeric claim below was emulated against the game's own bytes on **both** the INSTALLED image and
`eFootball.exe.PRISTINE` unless marked otherwise. Addresses are VAs at base `0x140000000` (no ASLR).

Evidence levels used throughout: **a-emulated** = the game's own code was executed under Unicorn
with controlled inputs; **b-disassembly** = followed instruction by instruction; **c-inferred** =
structural reasoning only. Every section ends with what is *not* proven.

> Read [§ Corrections](#corrections-things-this-project-believed-that-are-wrong) and
> [§ Refuted](#refuted--do-not-rebuild-these) before proposing any off-ball change. Between them
> they cover roughly a year of misdirected tuning.

## What this enables

| want | where | how |
|---|---|---|
| understand why off-ball runs repeat | `ChanceSpaceRun::vf5` `0x143df5950` — score is `100 + attackDir·player.x + roleBonus` | nothing to tune; needs a cave adding a second term |
| a genuinely unused run type | run **kind 6** — full `vf6` geometry `0x143df1cc5` + own executor handler `0x1441f360b`, never tagged | cave in `vf6`'s tagging chain |
| ability-dependent defending | `attr(0x17)` in `0x143da92c0` — already scaled three ways | ⚠️ **WITHDRAWN 2026-09-19: `0x17` is DRIBBLING, not Defensive Awareness** (see § The one ability-scaled defensive term). The mechanism is real; the attribute is not the one this row assumed. `0x15` is the candidate to check |
| tighter block / compactness | dt270 `basePosition.lengthOf`, `adjustZCompact`, `adjustXCompactFW` | `gameplay_tune`; all were stock until 2026-09-18 |
| per-player AI variety from data | playing-style category bits `R+0xCC` / `R+0xD0` | app already writes them (Player.bin bits 374/440) |
| stop contact eating your input | `canStart` (vtable slot 2) + `canCancel` (slot 14) on `match::anime::action::Contact` | see [§ Contact](#the-contact-lockout) — mechanism proven, fix not yet |
| inject new code | `tools/cave_scan.py` + `tools/cave_alloc.py` | 97,590 `.pdata`-validated caves, chained |

---

## The attacking-AI machine

`match::ai::ActionSelectorManager::update` (`0x143d52470`) has exactly one caller, `0x143d03493`,
with **no human/CPU test** — it drives the CPU team and the human's ten AI team-mates identically.
Its guard is `mov ecx,[match+0x3318] ; and ecx,1 ; cmp ecx,[teamAI+8]`, i.e. **frame parity**, so
each team re-decides all of its off-ball movement on alternate frames (~30 Hz at 60 fps). [b]

> `[match+0x3318]` is the match frame counter, not a possession flag. An earlier note in this
> project read the `& 1` as "the side in possession". It is not.

Each player holds exactly **one** action id at `teamAI + 0x8f4c + slot*4`, so a selector earlier in
the bidding order takes a player and every later selector never sees him.

**Bidding order** (a-emulated by two independent harnesses, both images — this *corrects* an earlier
note that had CenteringGet and PullAway ahead of GoalGet and PostPlay):

```
Overlap(0x27) > ChanceSpaceRun(0x1e) > CounterSpaceRun(0x1f) > SecondLineSpaceRun(0x1d)
  > LineBreak(0x20) > DiagonalRun(0x21) > GoalGet(0x29) > PostPlay(0x2a)
  > PullAway(0x2e) > CenteringGet(0x26)
```

Registration is `0x143d520e0`; the array is at `mgr+0x1720` (16-byte entries `{id, ptr}`, count at
`mgr+0x218`, capacity `0x83`). The bidding loop `0x143d52794` reads the id from `[rbx]` to fetch the
quota and the pointer from `[rbx+8]` to call `vf2`, so id and pointer must be swapped together.

### The shared dispatcher `0x143df1080`

Per selector: `vf4` builds an 11-bit eligibility mask → per eligible slot `vf6` writes a run-target
vec3 to `sel+0x60+12*slot` and tags a run **kind** bit in the masks at `sel+0x2c8` → `vf5` returns a
float score to `sel+0xc+8*slot` → the 11 records are sorted descending (`0x143b45ce0`, comparator
`0x143df1060`) → slots are handed out top-down, stopping at the first score `<= 0` (`0x143df1384`)
and at `min(quota, maxSlots)` (`0x143df1651` / `0x143df165b`). [b]

**`score == 0.0` is the "not a candidate" sentinel.** Any cave that perturbs the score must not lift
a 0.0 above zero, and must not push a legitimate candidate to `<= 0` — that would truncate the
sorted walk and silently cancel every lower-ranked runner in the frame.

### The scores — this is the root cause

```
ChanceSpaceRun::vf5  0x143df5950 :  score = 100.0 + attackDir * player.x + roleBonus
DiagonalRun::vf5     0x143e036e0 :  score = (opponentLineX - player.x) * attackDir
```

`attackDir` = signed byte `[teamAI+0x28c]` (±1); `player.x` = `[playerObj+0x4f4]` in metres.
28 emulated rows per image, matching the closed form to 1e-3. **No space term, no defender-distance
term, no pass-likelihood term, no attribute, in either.** [a]

Chance takes the *u*-maximal players and Diagonal the *u*-minimal, on the **same** scalar
`u = attackDir·player.x` with opposite slope — so the two selectors never compete for the same
player. (This is why reordering them is a placebo; see [§ Refuted](#refuted--do-not-rebuild-these).)

15 of the 16 run kinds leave the base at a flat `100.0`. Only **kind 3** computes a situational
value (`0x143df5de0`, reached via table entry `0x143df5c79`):
`100 - 10·A - 5·B - 5·C - 5·D - 3·(role>=7) - 5·(positionClass)`, observed range 72–100 over 60
rows. It is a **penalty band, never a bonus** — a kind-3 runner is always 0–33 below a flat runner
standing in the same place. [a]

Cell note: `0x145a8aa4c = 100.0f` is the score **base** (read at `0x143df59d4` / `0x143df5a03`);
`0x145a8aa44 = 20.0f` is a **separate** role bonus applied at `0x143df5d62` behind two undecoded
predicates (`0x143d37f30`, `0x143d32a90`). These are distinct — do not conflate them. Both cells are
heavily shared (1,701 and 1,099 referrers), so they must be **re-aimed, never written in place**.

### There is no randomness

The match RNG is a Lehmer LCG `s = 0x4513 - s*0x2d22b2e3`, living only in
`0x144345d80..0x1443461d0` (entries `0x144345d90`, `e00`, `e50`, `eb0`, `0x1443461a0`). A whole-image
scan for the multiplier finds six sites, all in that cluster. A direct-call closure of
`ChanceSpaceRun::vf5` to depth 10 (2,741 functions) reaches it **zero** times, and `vf5` contains no
indirect calls, so the closure is complete. Same negative for Counter / SecondLine / Diagonal /
PostPlay scorers, the dispatcher, the manager update and the quota builder. [b]

**Positive control:** the identical scan reaches the LCG from the kick builder `0x14401a900` at
depth 4 and from the kick randomiser `0x14401a060` at depth 3. The method works.

So: identical geometry → identical scores → identical ranking → identical runs, every time.

### Quotas, caps and priority

`0x1442f9a90(match, teamIdx, actionId, flag)` reads the attack level at `byte[team+0xb450]`
(0–4; setting at `+0xb454`, 5 = AUTO), clamps to 4, and indexes a 5-byte table of inline immediates
(switch index = `actionId - 0x1d`, jump table `0x1442f9ca4`): [a]

| action | id | L0 | L1 | L2 | L3 | L4 |
|---|---|---|---|---|---|---|
| SecondLineSpaceRun | `0x1d` | 0 | 1 | 1 | 1 | 1 |
| ChanceSpaceRun | `0x1e` | 1 | 2 | 2 | 3 | 3 |
| CounterSpaceRun | `0x1f` | 2 | 3 | 4 | 4 | 4 |
| LineBreak | `0x20` | 0 | 1 | 1 | 2 | 2 |
| DiagonalRun | `0x21` | 1 | 1 | 1 | 2 | 2 |
| Overlap | `0x27` | 0 | 1 | 2 | 2 | 2 |
| PullAway | `0x2e` | 0 | 0 | 1 | 1 | 1 |
| PostPlay | `0x2a` | 1 | 1 | 1 | 1 | 1 |

`maxSlots` is the `dl` argument to the shared ctor `0x143d51c40`, stored at `sel+0xe4`
(`0x143d51cb0`); the action id goes to `sel+0x128`. Immediates: ChanceSpaceRun `0x0b` @`0x143d51a3d`,
CounterSpaceRun @`0x143d51a90`, SecondLine / LineBreak / PullAway / PostPlay `01`.
**DiagonalRun does not use the shared ctor** — it has its own at `0x143e02710`, with
`mov byte [rbx+0xe4], imm8` at `0x143e02781` (imm byte `0x143e02787`), immediately followed by the
`0x21` write to `+0x128`, which confirms identity. [b]

ChanceSpaceRun's `maxSlots = 11` is effectively **inert**: its quota never exceeds 3, so
`min(quota, maxSlots)` never sees the 11.

**No preemption.** `0x1442ed7c0` is two calls to `0x1442ed8d0` then `cmp eax,ebx / setl al`. The rank
jump table (`0x1442ed9c0`, handlers `0x1442ed9ac`) sends **all eight** run action ids to
`mov eax,2; ret` — an unconditional immediate with no context dependence. `2 < 2` is false, so a
later selector can never poach a player an earlier one holds. Idle (id 0) falls out of range to rank
5 and is visible to everyone. [b]

**Commitment window.** A won run is protected by each selector's `vf3` for
`int(fps*0.2 + 0.5)` = 12 frames = 0.2 s (built `0x143df73a8` / `0x143e051b2`, compared
`0x143df73bd` / `0x143e051c7` against `elapsed = [rec+8]-[rec+4]` of the per-slot record at
`teamAI + 0x8f78 + slot*0x34`). Turnover happens **only** when `vf3` aborts and the freed slot is
re-bid — a held slot is never reassigned. [b]

Two 11-entry latch arrays at `mgr+0x220` and `mgr+0x24c` are set to `int(fps*2.0+0.5)` = 2 s by
predicates `0x143d32990` / `0x143d32850` and decremented in loop `0x143d525c1..0x143d52669`; the
first is **cleared instantly for the human-controlled player** (`0x143d215c0`, compare
`0x143d5260c`). What they gate is still undecoded.

### The 16 run kinds

The kind is the **lowest-index bit set** in the per-kind masks at `sel+0x2c8` (16 masks over 11
slots, `0x2c8..0x307`), scanned by loop `0x143df59e0` and dispatched through the 16-way table at
`0x143df5d94`. Each handler writes a sub-mode id into `record+4` of the 36-byte ActionParam at
`sel+0x12c+slot*0x24` (record initialised by `0x1443376f0`, `record+0` = action id). [b]

kind→id: `0:1, 1:3, 2:4, 3:13, 4:22, 5:11, 6:15, 7:12, 8:14, 9:16, 10:2, 11:18, 12:19, 13:20,
14:5, 15:23`; "no kind found" also emits 22.

**The kinds are not cosmetic.** `match::player::ActionSpaceRun::vf18` (`0x1441f3010`) reads that id
at `action+0x54` and dispatches through a 26-entry table at `0x1441f3b20` to **19 distinct
handlers**, each calling a different run-path builder. Ids 3, 7, 17, 19, 20, 22, 23 fall through to a
shared second-level switch at `0x1441f37c6` and look alike; kinds 0, 2, 3, 5, 6, 7, 8, 9, 10, 11, 14
have their own movement.

**Never tagged in this build: kinds 6, 11, 12, 13.** Kind **6** is a genuinely complete free slot —
it has a full `vf6` geometry path at `0x143df1cc5` *and* its own executor handler at `0x1441f360b`.
It is the cheapest route to a new movement pattern in the whole subsystem.

The masks are effectively **one-hot**. An exhaustive control-flow walk of all 1,046 reachable
instructions of `vf4` (both images) shows no path from one kind-write to another before the loop
latch; `vf6`'s tagging chain is the same shape. The one deliberate overlap is kind 3 → kind 2: `vf6`
reads the kind-3 tag at `0x143df1d5e` and sets kind 2 on top when its finer test `0x143d32690`
fails. "Lowest index wins" is Konami's **priority ladder**, not an accident.

### Dead selectors

`ActionSelectorLineBreak` and `ActionSelectorPullAway` are dead at **both** layers:
- selector: `vf4 = 0x140c837d0` (`xor eax,eax; ret` — eligibility mask always zero),
  `vf3 = 0x140c853c0`, PullAway `vf5 = 0x14143aec0` (`xorps xmm0,xmm0`), LineBreak `vf5 = 0x143e02700`
  (returns a constant 100.0f).
- executor: `match::player::ActionLineBreak` / `ActionPullAway` stub every override that
  `ActionSpaceRun` implements in 600–970 instructions (`vf6 0x1441f3be0`, `vf13 0x1441eb5d0`,
  `vf18 0x1441f3010`, `vf20 0x1441ea8c0`).

Konami still ships their quota rows and difficulty gate (row `0x15`), which is why earlier sessions
believed they were live. Reviving either means writing ~2,500 instructions across both layers.

### CPU difficulty is not the bottleneck

Inside the cap builder `0x143df0080`, row `0x13` gates SecondLine **and** Chance, `0x14` gates
Counter, `0x15` gates LineBreak **and** PullAway, `0x16` gates Diagonal, via
`0x1442e4c00(row) = |GetParam(row)| > FLT_EPSILON` on table `0x146c06f40`.

> **CORRECTION 2026-09-19 — the row values below came from the PATCHED image, and the
> "dumped from both images" claim is false.** A byte diff of INSTALLED against
> `eFootball.exe.PRISTINE` finds the two images differ *inside this table*, at exactly
> **`0x146c072b8` and `0x146c072bc`: `0.0f` in stock, `1.0f` installed** (the only 4-byte runs that
> differ in the whole 44x10 window). In the raw table those are row 22 (`0x16`), columns 2 and 3,
> so stock reads `{~0, 0, 0, 0, 1,1,1,1,1,1}` there and our image reads `{~0, 0, 1, 1, 1,1,1,1,1,1}`
> — two more difficulty columns switched ON by us. (Column 0 holds a denormal `1.4e-45`, which fails
> `> FLT_EPSILON` and therefore gates as zero.)
>
> Note also that the chapter's row numbering is offset by one from the raw table: the values quoted
> below for row `0x15` match raw row `0x16`. Re-deriving the correct mapping and the stock values for
> every row is **owed work**, not done here — what is established is that at least one quoted row is
> our patch rather than the game, so **no conclusion in this section should be trusted until it is
> re-dumped from PRISTINE.** [b, verified by direct diff]

Dumped (FROM THE INSTALLED IMAGE — see above): rows `0x13`/`0x14`/`0x16` read
`{0,1,1,1,1,1,1,1,1,1}` and `0x15` reads `{0,0,0,1,1,1,1,1,1,1}`, which read as
"only the lowest difficulty loses run types" — **a conclusion that rests on our own edit.** [b]

Nothing in the base-position code consults the difficulty table at all: all 24 call sites of
`AiLevelUnit::GetParam` (`0x1442e48f0`) were enumerated and none is in the shape/positioning ranges.

---

## The data inputs: styles, roles, formation

### Playing styles are booleans, gated by formation role

Each player's match record is `R = paramBlock + variant*0x198 + 0xE8`, reached via
`0x1442c3050(paramBlock, posGroup)`. Layout (cross-checked against the record checksum
`0x1442c2110`, which touches every field): [b]

| offset | contents |
|---|---|
| `R+0x3d` | 61 ability bytes (getter `0x1442bfa70`) |
| `R+0x7a` | a second parallel ability array (`0x1442bfa80`) |
| `R+0xC0..CB` | 73 skill-card bits (test `0x1442c0000`) |
| `R+0xCC` | **21-bit in-possession playing-style category mask** |
| `R+0xD0` | **16-bit out-of-possession category mask** |
| `R+0xD4` | 7 COM/AI playing-style flags |
| `R+0xD8` / `R+0xDC` | raw catalog indices 0–35 (HUD/replay only) |

Builder `0x145440e10` reads DB param keys `0x3d` / `0x3e` — the global `Playstyle.bin` index the
companion app already writes at Player.bin bits 374/440 — maps index → internal id (table
`0x1471bc0c0`, 36×8) → category (`0x1453e5230` offensive / `0x1453e5210` defensive, table
`0x14825b2f4`, 36×12) and **sets exactly one bit**. There is no numeric weight anywhere: to the AI a
style is a boolean. [a, emulated for all 36 ids]

Every AI query goes through `0x1442e2130` (in-possession, 297 call sites in 107 functions) or
`0x1442e0480` (out-of-possession, 36 sites), which return
*player has style X* **AND** *X is legal for the ROLE of the squad slot he occupies*, where
`role = dword[teamObj + 0x42B8 + (playerNo % 11)*4]`. **Play a man off his slot and his style
silently stops firing.** Emulating the gate over the whole 21×10 grid reproduces eFootball's own
published position scoping exactly, which is itself the proof the category map is right.

**Off the ball, style barely matters.** The three space-run selectors contain six style gates
between them and **five are pure vetoes** (DiagonalRun bails outright on Classic No.10, Anchor Man,
Orchestrator; SecondLineSpaceRun rejects Orchestrator; Hole Player skips a pitch-X requirement).
Style never selects a *different* run target. On the ball it matters a great deal — the
in-possession bit is read 22 times inside `ThinkUnitPassSpecial` alone, plus `ImageUnitCross`,
`ImageUnitSideChange`, `ImageUnitCBOverlap` (Extra Frontman genuinely unlocks the CB overlap) and
`DribbleImageShielding`.

**Cosmetic in this build — zero AI call sites:** Covering Role (29), High Line Master (30), Deep
Defender (32). The out-of-possession style with real reach is **The Destroyer** (defCat 8), read in
`ActionMark` and `ActionTackle`; the GK styles drive keeper depth.

### Skill cards do not drive decisions

The 73-bit card array at `R+0xC0` is tested by `0x143eadbe0` / `0x1442c0000`, which takes **no
position argument**. All 287 test sites are in `match::anime::action::*`; none in `match::ai::`.
26 sites assign an animation id outright, and 14 card tests in `0x143ed7440` award +5/+6/+7 to
effective ability before the error curve. Cards change **execution quality and which animation
plays**, never choice. [b]

### Formation

2 presets × 11 players × 3 phases of `{position code, role code, x, z}` at `teamAiInfo+0x8078`,
seeded **verbatim, no scaling** by `0x143d49f40` from what the app's `TacticsFormation.bin` writer
already produces. The 13 position codes collapse to 10 mirror-symmetric groups, so LMF and RMF are
the same thing to the AI. That group decides line membership, marking/cover eligibility and style
legality. **There is no formation-keyed decision table anywhere** — 4-3-3 vs 4-4-2 changes geometry
and group membership, nothing else. [b]

### The one ability-scaled defensive term

In the shared base-position runner `0x143da92c0`, out of possession only: [a]

```
gait threshold   = 19.0 - 0.1 * attr(0x17)          (19.0 is stock; see § Corrections)
sprint-back gate = lineX + 8 - 12 * clamp01((attr-45)/35)
recoveryDist     = 15.0 - 10.5 * clamp01((attr-40)/80)
```

Emulated at identical geometry: attr 40 jogs (gait 2), attr 50+ sprints (gait 5); the sprint trigger
distance falls from **15.0 m at attr 40 to 7.26 m at attr 99**.

> **CORRECTION 2026-09-19 — the attribute is DRIBBLING, and it is read far more widely than stated.**
> [player-executors.md](player-executors.md) (adversarially reviewed, repair applied) settles the
> name this section left inferred: `0x17` is `DRIBBLE`, `0x15` is Defensive Awareness, `0x16` is
> GK Awareness, under the **proven** `DATA_PARAMETER + 7` alignment in
> `tools/data/attr_index_map.json`; `docs/exe-gameplay-map.md` row 47 marks the older `+0x15`
> alignment this section rests on as "WRONG — off by one, superseded 2026-09-18".
> And `0x17` is read at **11–12 sites image-wide, not three**: the three below are the direct
> `0x1441172b0` calls; the rest pass `0x17` through the wrapper `0x1442dd650`, which tail-jumps to
> the same getter — including `ActionPassCourseCut::vf13` at `0x14420ac35`.
> **The mechanism above is unaffected and still real** — the gait threshold, sprint-back gate and
> recovery distance are genuine ability-scaled positioning terms. They scale with **Dribbling**.
> The consequence is that the "spread it in `master.db`" advice in the *What this enables* table at
> the top of this chapter would spread Dribbling, and is **withdrawn pending the owner's call**. [b]

Attribute index `0x17` is read at three sites *directly* — `0x143da943a`, `0x143daa779`,
`0x144181101` — all inside the base-position/movement system.

**The decision layer never reads an attribute.** Not one quota, rank compare, run selector or
difficulty row. Four of the five run selectors make zero calls to any ability getter; ChanceSpaceRun
makes exactly one (`0x143df63e0`). Ability enters at *execution*, not choice.

### The CB cushion

`ActionMark::vf20` (`0x1441a1e50`) computes `R = |self - proposedDestination|` and re-emits the
destination at **the same radius R**, rotated toward the marked man:

```
w   = 1 if R < 8 m ; 0 if R >= 30 m ; (R-30)/-22 between
ang = rotate(bearing-to-base -> bearing-to-man, by at most (1-w) * CAP)
out = self + polar(ang, R)
```

**Radial closing is exactly 0.000 m in every emulated case.** The marker can only aim, never close;
whatever gap the shape layer hands it is the gap it keeps. And the fade runs backwards for tight
marking: `w = 1` below 8 m means that inside 8 m he stops steering toward his man entirely and points
at his zonal slot. [a]

So the cushion is set upstream in the base-position/shape layer, which is where dt270's
`lastLineCloseMaxRate`, `dfLineCloseRate` and `spaceCoverRate` act.

---

## The contact lockout

Two locks stacked. `Stagger::vf32` — which this project's notes described as "how many extra frames
a stagger is locked" — is **neither of them**; it is `isFinished()` ("may this stagger end"), and its
Balance term is clamped to 5 frames (83 ms). [b]

**Lock 1 — eligibility.** Every action has `canStart` at vtable slot 2. Emulated for all ~100 action
classes with the current action forced to Stagger / FallDown / Dive: while in a **stagger** the game
refuses outright — before any timing check — Move, Tackle, Sliding, Block, Feint, Jostle, StepMove,
Reaction and every kick/pass/shoot. Exactly **two** outfield actions are even considered: Dribble and
Trap. In a **fall**, only Trap. In a **dive**, nothing. [a]

**Lock 2 — the cancel gate**, vtable slot 14, `canCancel(Work*, requestedKind)`. `Sliding::vf14`
(`0x143f70360`), `FallDown/Dive::vf14` (`0x143f00d00`) and `Stagger::vf14` (`0x143f00de0`) all reduce
to `return currentFrame >= cancelKeyframe`. `Base::vf14` is `xor al,al; ret` — the default for every
action is "I cannot be interrupted". The keyframe is **baked into the animation asset**, read from
the MbInfoManager motion table (7,883 motions × `0x1F8` bytes = 21 keyframe channels × 24 bytes;
channel 5 = cancel keys, channel 3 = "action is over"). [b]

Keyframe arithmetic, exact: channel 5 gives `frame = round((((raw>>13)&0x3ff)+2)*2 / scale * speed/60)`;
channel 3 gives `frame = round((word&0x1fff)*2 / scale * speed/60)`. `scale` is always 1.0f from the
pool cell `0x1478502b8`; `speed` is the global float at `0x148c22abc`. [a]

**The asymmetry.** In `Stagger::vf14` every request kind uses the **first** channel-5 cancel key —
except kind 4, Dribble (running with the ball), which has its own branch using the **last** cancel
key, or the channel-3 END key when the motion has only one. The one thing you want after being
barged — push the ball on, turn back into the man — is the thing the engine makes you wait longest
for. [b]

**This is not the CPU cheating.** The gate reads only motion id, current frame, contact sub-kind and
requested kind — no controlled-player flag, no team, no attribute. The asymmetry is structural: a
staggered player is usually the carrier, so his request is Dribble (late gate), while the defender
arriving requests Move or Tackle (early gate).

**Not proven, and it blocks every fix here:** the real keyframe numbers live in runtime-loaded motion
assets, not the exe, so the lockout's length in seconds is unknown and all frame figures came from a
synthetic table. Adversarial verification also found that **10 of the 11 stagger motions have ≤1
cancel key**, which makes the kind-4 special case collapse to the END key anyway — so the obvious
one-byte fix is probably a placebo. Four stagger motions have *no* cancel key, where a patched gate
falls to an out-of-range floor of frame 4 (67 ms). Seven specs were written (`tools/data/patches/contact-*.json`)
and **none should be applied** until the motion assets are decoded.

---

## The cave allocator

`tools/cave_scan.py` → `build/caves.json`; `tools/cave_alloc.py` lays a keystone payload across many
small int3 runs, each chunk ending in a 5-byte `jmp rel32`, and emits an ordinary `exe_patch` spec
whose every chunk carries the original `0xCC` bytes as its `expect` (so `remove` restores padding
byte-exactly). `tools/cave_alloc_test.py` is the suite.

**The safety oracle is `.pdata`.** The EXCEPTION directory (RVA `0x154ac000`, size `0x4b180c`) *is*
the whole `.trace` section: 410,113 `RUNTIME_FUNCTION` entries merging to 253,886 ranges covering
84.3% of `.xcode`. A run that starts exactly at one function's `EndAddress` and ends exactly at the
next's 16-byte-aligned `BeginAddress` is provably padding. [b]

| | value |
|---|---|
| int3 runs in `.xcode` | 547,254 (3,101,315 bytes) |
| **inside** a `RUNTIME_FUNCTION` — rejected | 106,874 |
| tier-A pool | **97,590 caves / 553,583 payload bytes** |
| largest tier-A cave | **21 bytes** (mean 10.67) |
| tier-A caves ≥ 24 bytes | **zero** |
| in the match band `0x143000000`–`0x144800000` | 24,290 caves / 133,021 payload bytes |

MSVC aligns function entries to 16, so genuine inter-function padding **caps at 15 bytes**. Chaining
is mandatory for any payload over ~16 bytes; a 70-byte payload needs 8–10 chunks. A 5-byte
`jmp rel32` reaches anywhere in `.xcode` (worst-case displacement `0x59faffa`, 22.8× headroom).

The pool is **edit-invariant** — scanning PRISTINE yields the same 97,590 VAs and lengths — so specs
allocate to the same addresses against either image. Re-check after every Konami patch.

Two methodological results worth keeping: a naive "does any u32 in the image equal this RVA"
jump-table test produced 514,886 false hits and vetoed the entire pool until it was made
table-aware (requiring ≥3 consecutive 4-aligned u32s pointing into `.xcode` within 64 KB drops it to
55). And the rel32 branch scan found only 9,437 target bytes landing inside runs against ~89,000
predicted by a uniform-random model — good evidence real code never branches into padding.

**Known constraint:** cave code is covered by no `RUNTIME_FUNCTION`, so it is unwind-hostile. A
`call` from inside a cave puts a return address the OS cannot resolve on the live stack. Survivable
for code that never faults, but it must be a conscious choice.

Open allocator defects (found by adversarial review, not yet fixed): `verify_layout` falsely passes
when a chain jump collapses to rel8 and leaves a nop as the last decoded instruction; `hook_patch`
has no reference gate and no upper bound on `stolen_len`; `cave_pool` declares a `pristine` parameter
it never reads, so call sites read as a two-image gate that does not exist; a spec cannot be
regenerated at the same addresses.

---

## Corrections: things this project believed that are wrong

| belief | reality |
|---|---|
| dt270 `basePosition` line fields are inert | **Wrong, and it misdirected months of tuning.** `dfLine` (byte read at `0x143ddb9a0` → `clamp01(v/20)`), `dfLineRate`, `dfLineCloseRate`, `lastLineCloseMaxRate`, `keepDfTargetLineX`, `backOffsideLine`, `lengthOf`, `minWidth`, `adjustZCompact`, `lineControl`, `spaceCoverRate` all have readers. Genuinely unread: `pressRate`, `defenceCompact`, `lengthDf`, `dfLineWidth_3/4/5`, `wideRate`, `attackLevel`, `attackLevelAdjustX`. |
| `0x1442ed7c0` is a role gate; role id `0x20dc4` rejects midfielders from late runs | It is an **action-priority rank compare**. `0x1d` is the SecondLineSpaceRun action id. `0x20dc4` is a separate, still-unidentified 128-bit token compare at `record+0x30`. |
| stock `marginPredictionFrameBase` is 6 | It is **0**. |
| `marginPredictionFrameAdjust` tunes defensive anticipation | It is **inert** — multiplied by the `-0.0f` cell `0x147850538` and truncated, always 0. Its containing function is a **pass-timing / slow-down horizon**; nothing in the marking path reads it. |
| the selector `& 1` guard is a possession test | It is **frame parity**. |
| bidding order ends `... CenteringGet > PullAway` | It ends `... GoalGet > PostPlay > PullAway > CenteringGet`. |
| stock `roleBonus` is 100.0 and was re-aimed to 20.0 | `0x145a8aa4c = 100.0f` is the score **base**; `0x145a8aa44 = 20.0f` is a **separate** role bonus. Two different cells, two different roles. |
| `Stagger::vf32` is the post-contact lock | It is `isFinished()`, capped at 5 frames (83 ms). The lock is `canStart` (slot 2) + `canCancel` (slot 14). |
| ball physics is Z-up | It is **Y-up** (gravity −9.80665 on component [1]). |
| `forceDashDistDefence` is a live lever | Loaded at `0x143da9420`, then **unconditionally overwritten** at `0x143da9553` before the only compare. Dead in practice — "read" is not "effective". |

### Self-inflicted regressions found and reversed on 2026-09-18

Five of our own dt270 edits were pushing the CB cushion the wrong way, and one exe edit made every
defender lazier at every ability level:

| edit | was | effect |
|---|---|---|
| `spaceCoverRate` 0.43 → 0.55 | ours | cover radius +21–24%, **saturated on the 1.0 clamp**; a defender who believes he covers the gap does not step onto his man |
| `adjustSpaceCoverRate` 0.23 → 0.30 | ours | pushed cover onto the clamp |
| `lastLineCloseMaxRate` 0.80 → 0.62 | ours | back line's maximum closing effort cut 22% |
| `dfLineCloseRate` 0.55 → 0.42 | ours | same direction |
| `marginPredictionFrameBase` 0 → 12 | ours | 0.2 s of assumed free time handed to every shape runner |
| gait constant `19.0f → 15.0f` @`0x143da9553` | ours (`marking-tight.json`) | every defender reacts ~4 m later, at **every** ability level — a flat laziness shift with no ability slope |

All six are reversed by `tools/data/tunings/compact-and-tight.json` and
`tools/data/patches/gait-revert.json` (both applied 2026-09-18). The same pack also reaches three
compaction fields that had **never** been touched: `lengthOf` 35 → 28 (the team's front-to-back
length in metres, read at `0x143deaa33`), `adjustZCompact` 2.5 → 4.0, `adjustXCompactFW` 0.5 → 1.0.

---

## Refuted — do not rebuild these

Each of these was built, emulated, and killed by adversarial verification. They look reasonable and
they do not work.

- **Reordering selectors to get variety.** Placebo. Chance and Diagonal score by the same scalar
  with opposite slope and never compete for the same player. The one regime where a swap changes the
  outcome is count-*increasing*.
- **Lengthening the 0.2 s commitment window.** Directionally anti-variety: turnover only happens when
  `vf3` aborts and the slot is re-bid, so a longer hold means *fewer* different runners.
- **Capping ChanceSpaceRun's `maxSlots`.** Inert — its quota never exceeds 3, so `min(quota, 11)`
  never sees the 11.
- **Reversing or rotating the lowest-index run-kind scan.** The masks are one-hot, and the one real
  overlap (kind 3 → kind 2) is a deliberate override. Reversing breaks it and makes the AI *less*
  responsive.
- **Reviving LineBreak or PullAway.** Dead at both layers; ~2,500 instructions to restore.
- **Raising attack level to get varied runs.** Raises the quota, so you get the deepest *and*
  second-deepest man — more bodies, same determinism — and it makes a deep block play like it is
  chasing a game.
- **The `marginPredictionFrameAdjust` anticipation cave.** Wrong target function (pass timing, not
  marking) *and* mis-calibrated: pivot 70 against a roster mean of 57.4 would have made almost
  everyone lazier.
- **Widening off-ball eligibility gates** (depth gate, diagonal cone, leash, run-target plane — six
  shipped packs). Widening a pool that is then ranked "furthest forward" and truncated at 2 changes
  nothing visible.

---

## Current applied state (2026-09-18)

Live: `compact-and-tight.json` (dt270, 8 edits) and `gait-revert.json` (exe, 1 instruction).

Applied but working by the rejected "add runners" route, and candidates for removal:
`offball-counter-early.json` (CounterSpaceRun `maxSlots` 1→2, and the quota row `{2,3,4,4,4}` means
it binds at **every** attack level including 0) and `offball-run-variety.json`.

## Open questions

- The real cancel keyframes (motion assets — filenames likely hashed, as the dt250/dt251 menu JSON
  was). Blocks every contact-lockout fix.
- What the two 2-second latch arrays at `mgr+0x220` / `mgr+0x24c` gate, and what the human-player
  exemption means.
- The two predicates behind the +20 role bonus (`0x143d37f30`, `0x143d32a90`).
- ~~Confirmation that attribute `0x17` is Defensive Awareness.~~ **ANSWERED 2026-09-19: it is
  `DRIBBLE`.** The open question is now whether the same positioning mechanism reads Defensive
  Awareness (`0x15`) anywhere, and what — if anything — should be spread in `master.db` instead.
- Whether the ball deflects off non-tackling players (limb collision parts exist — a 21-slot array at
  `player+0x2f18` with per-frame physics filter groups via `0x144fa58d0` — but the consequence for
  loose balls is untested).
