# The ball-carrier brain — `match::ai::bp` (2026-09-19)

How the AI decides what to do when it has the ball: pass, dribble, shoot, feint — and to whom.
65 RTTI classes — of which roughly half are decoded and the rest are catalogued only to the level
stated in § Class status. Produced by one hand-written pass plus five workflow probes (architecture,
think-units, image/dribble layer, personality-and-randomness, decision inputs) over
`tools/exe_map.py`, `tools/exe_census.py` and purpose-built Unicorn harnesses
(`tools/emu_bp_harness.py`, `tools/emu_bp_personality.py`, `tools/emu_bp_image_dribble.py`,
`tools/bpx.py`, `tools/exe_funcs_chained.py`). Where two probes disagreed, the disputed bytes were
re-read for this write-up and the resolution is stated inline.

Evidence levels: **a-emulated** (the game's own bytes executed under Unicorn with controlled inputs),
**b-disassembly** (followed instruction by instruction; function extents from the *chained-unwind*
`.pdata` walk, see the note under § Corrections), **c-inferred** (structural reasoning only).
Addresses are VAs at base `0x140000000`, PRISTINE image; the whole carrier band
`0x145640000..0x1456e0000` and every out-of-band helper named here are byte-identical in the
INSTALLED image. Companion chapter: [match-ai-decoded.md](match-ai-decoded.md) (off-ball movement).

> Read [§ Corrections](#corrections) before proposing any on-ball change. Several claims handed
> down in this project's notes — including three in the briefing that produced this chapter —
> do not survive the bytes.

## What this enables

| want | where | route | state |
|---|---|---|---|
| change *what the CPU prefers* on the ball (pass before shot, cross before through-ball…) | candidate order in `0x14566b980` (per held Image) and `0x14566b7f0` — `mov edx, kind` before each `call 0x143e8fdb0` | exe code | a-emulated: the arbiter is first-valid-in-list-order, so the order *is* the policy |
| make the CPU carrier hesitate / snap-decide | CPU level table `0x146c06f40` rows `0x17` (pass/clear), `0x18` (dribble), `0x19` (dribble move) via `0x1456526a0` | exe table | a-emulated (60/40/22/12/8/6/2 frames Beginner→Legend) |
| how often the CPU *plans* a cross / long shot / curled shot / long ball | the four rolled `canStart`s: Cross `0x14567af10`, MiddleShot `0x145678b30`, CurveShot `0x1456786c0`, Long `0x14567b670` — the roll is a **gate**, not the whole test; MiddleShot/CurveShot clamp the score to 90; the `0x64` range immediates double as the RNG stream index (§ Tunables before touching them) | exe code (inline immediates) **or** player data (cards, COM flags, attributes that feed the score) **or** the per-match team fields `team+0xb3c4` / `+0xb44d` | a-emulated for the Cross roll segment, b for the rest |
| per-player variety in carrier decisions | `Personality::update 0x145663920` — 8 floats from 11 attributes, 5 cards, 12 style bits, 7 COM flags, role | **player data the app already writes** | closed form a-emulated, 0 mismatches |
| which skill moves a CPU player attempts | dribble pool `0x1456ab3b0` (card-gated) + weights (attribute-scaled) | player data (cards `0x28,2,0x29,1,3,0x43,0x42`, COM bit 0) | a-emulated |
| which forward pass carries the receiver-style tag `rec+0x25` | receiver predicate `0x145695690` (in-possession style of the *receiver*), run **after** the target is chosen; the tag's consumer is untraced | player data (Player.bin bit 374) | a-emulated truth table; gameplay effect **c** — it does not choose the receiver |
| force cross / long-ball plans, kill the Safety plan | per-match team dword `team+0xb3c4` (Cross `0x14567b586` accept, Long `0x14567b8f6` score := 100, Safety `0x1456770eb` disabled) and byte `team+0xb44d` (Cross `0x14567b286` skips score and roll) — name and writer unknown | per-match team field | b — the largest single on-ball lever found; identify it before use |
| a genuinely random carrier decision | `ThinkUnitPassRandomTest` (kind `0x17`) | **not reachable** — never in any candidate list | dead; would need one push site |
| tune carrier behaviour through dt270 | — | **no dt270 field reaches this subsystem** | b, exhaustive |

## The machine in one paragraph

Every simulation tick, for **one `BallPlayer` object per team-slot** (it lives inline in the
per-player AI container, one per team × slot), the brain (1) decides whether this player is *the
carrier* at all, (2) recomputes a `Personality` (8 floats from attributes, playing-style bits, skill
cards and COM-style flags), (3) classifies the *situation* (`Intention`, class 0–4 — read back as a
branch condition by some thirty carrier functions, § Intention), (4) lets the
**Image** layer pick a *plan* — first-match-wins over a situation-keyed list, held across frames,
with a literal percentage roll in four of the sixteen entry tests — and (5) from the held Image
builds an **ordered candidate list of think-unit kinds**, runs every listed `ThinkUnit::think` into
a results table, and takes **the first unit in list order that produced an answer**. No score is
compared anywhere. A shoot, pass or clear answer is then *held* and re-applied each tick without
re-thinking until it executes or the carrier state resets; dribbles are re-decided every tick. The
CPU additionally sits on an answer for a difficulty-dependent number of ticks (60 at Beginner, 2 at
Legend) before it is allowed out — and while it sits, that answer is absent from the table, so a
lower-priority unit with a shorter delay can win instead. Every live random *draw* is a freshly
seeded LCG (the plan rolls, the aim perturbation, the dribble-move shortlist), but the per-possession
random `r` those rolls are seeded from is also read **as a threshold inside the ThinkUnits** —
Shoot, PassForward, PassOneTwo, Dribble, PassSafety, PassLong, PassSpecial and the arbiter — so the
pass/shoot/dribble choice is deterministic only *given* `r`, and `r` changes every possession spell.
The one unit that draws a free-running random number is never consulted. One branch sits in front
of all of this: a byte on the entity snapshot (`entity+0x41`, copied from `Player+0x7f49`, writer
not located) diverts the carrier to a move-only output that bypasses the candidate loop (only the
PassBackSpace kind-0xa re-run on that function's common tail can still overwrite it; § decision
loop, step 3).

## Where it lives, and how it is ticked

`BallPlayer` (ctor `0x145650860`, wrapper `0x145650800`, size `0x6ce8`) is embedded at `+0x940`
inside a `0x19178`-byte per-player AI container (`0x144143700` → `0x144140fd0`) that the factory
`0x143c47c60` allocates for team 0..1 × slot 0..10 (`cmp 2` / `cmp 0xb` loop counters). The
container also holds a 0x18-byte sub-object at `+0x7628`, `match::ai::PlayerDefence` at `+0x7640`
and `match::CommandPlayer` at `+0x7658`; the per-entity ctor is `0x14562c970`. [b]

> An earlier version of this chapter said "one object per team, no per-player copy". The factory
> loop is 2 × 11; there is one `BallPlayer` per squad slot. The brain still only *acts* for the slot
> that holds the ball, because the activation test gates everything.

Tick chain (all direct calls, no virtual hop after `Player::vf1`): [b]

```
match::Player::vf1  0x14414a2a0   (this, ctx, float dt in xmm2)  — inc [Player+0x10] every call
  └ 0x144149ea0 → 0x14414e810 → TICKER 0x14414a340 (single caller 0x14414ed58)
        if match->0x41cc ∈ {0, 0xe, 0x14, 0x1b}:           (in-play situations; else the set-piece path)
            0x145653b90  PRE-PASS   (thunk 0x14562cac0)      activation → level rows → Personality → Intention → Image loop → pass-course build
            0x14414f340 → 0x14414fcc0 → 0x144156440 → 0x14562cad0 → 0x145654060  DECIDE
            0x145653850  PUBLISH    (thunk 0x14562cab0)      copy the result record to Player+0x2760 / +0x1158
```

`0x145653850` ends at `0x145653b5b` (followed by a jump table); the function that reads the
difficulty rows, calls `Personality::update` at `0x145653e94` and runs the Image loop is the
*separate* `0x145653b90`. Two probes labelled `0x145653850` "BallPlayer::think" because a
touching-range `.pdata` merge glued the two; the chained-unwind merge separates them. [b]

`Player::vf1` is invoked as `entity->vf1(ctx, dt)` from the generic entity loop `0x144344e50`
(`for each entity in vector: call [vt+8]`), whose only caller `0x143c67fe0` computes
`dt = 0x1442c79f0(..) / fps`. Signature match only. [c]

**Rate: every tick, no frame-parity guard.** The chain from `Player::vf1` down to `DECIDE` contains
no read of the frame counter used as a guard (the two `[match+0x3318]` reads in `0x14414e810` /
`0x14414f340` are stored into the context as timestamps). The off-ball manager's alternate-frame
guard has **no equivalent here**; all timing inside the brain is done with frame stamps against
`match+0x3318`, and every seconds→frames conversion uses the platform tick accessor
`0x14533eb20` / `0x14533ea80` (`[0x148c22ac0]` / `[0x148c22abc]`, runtime globals outside the file
image — [exe-gameplay-map.md](exe-gameplay-map.md) row 75 records them as 54 on PC; the harnesses
below stubbed them to 60 where stated). [b for the reads, c for the runtime value]

`Player::vf1` skips the whole update when `0x1442d70e0(match)` + `0x141997fc0` + `0x144117270` all
pass (a replay/pause-style gate) or when `0x1442c5190(match)` is true. [b]

## Layout of `BallPlayer` (offsets from the object)

| offset | what | evidence |
|---|---|---|
| `+0x10` | **active** byte — "I am the carrier this tick" (set by the activation test `0x1456516d0`, debug `" status(%s) "`) | b |
| `+0x14` | float `r ∈ [0,1)` latched from the match random bundle `*(*0x1486bd888+0x790)+8` on the second active frame of each possession spell (`+0x8ac == 1`) or when negative; the **per-possession roll seed** for the four rolling Images (× 1500 / 1200 / 1300 / 1600, see § Image layer) **and a threshold read inside eight decision functions** — Shoot, PassForward, PassOneTwo, Dribble, PassSafety, PassLong, PassSpecial, the arbiter (§ Where the possession random `r` is consumed) | b |
| `+0x18` | `BallPlayerRetryWork` sub-object: `+0` player index, `+0x18` **role code** (mirrors `team+0x42b8[slot%11]`), `+0x58` **ball-relation state** (see below) | b |
| `+0xb0`, `+0x4ac` | own-team / opponent situational tables (built per tick by `0x143e355f0` over both 11-slot lists) | b |
| `+0x8a8` | possession block: `+0` frame stamp (the *age origin* of every answer, `rec+0x50 = *(ctx+0x30)`), `+4` ticks since reset (`0x143e352e0` increments), `+8` frames in control; zeroed by the full reset `0x145651b90` | b |
| `+0x8bc` | pass-course work (`0x145661e80`); the **route table** at `+0x8bc+0xb78` (11 × 0x2a0: `+0` rank 0..5, `+4` state, `0xb` = receivable, `+0x130/+0x134/+0x138` distances); the 0xff-list at `+0x8bc+0x2894` | b |
| `+0x41f8` | **`Personality`** — vtable + 8 floats at `+8 … +0x24` (object size 0x28) | b |
| `+0x4220` | **`Intention`** — vtable + `+8` = situation class 0..4 (getter `0x143b85440`); handed to every unit as `ctx+0x40` and read by ~30 carrier functions (§ Intention) | b |
| `+0x4230` | **ImageMgr** (ctor `0x14566a3e0`): 16 ImageUnits, pointer array `mgr+0x718`, held image `mgr+0x530`, frame counter `mgr+0x534`, output `{kind,target}` `mgr+0x538/0x53c`, sub-struct `mgr+0x540`, heading `mgr+0x5e8`, cooldown records `mgr+0x5f4+idx*8`, **candidate kind list `mgr+0x678` (count) / `mgr+0x67c` (30 ints, dedup flags at `+0x7c`)** = `BP+0x48a8/+0x48ac` | b |
| `+0x49c8` | **results table**: 30 × 0x50-byte answer records, one per kind (`0x14566bd50` ctor, `0x14566bfe0` store, `0x14566bf40` fetch; out-of-range kinds return the constant empty record `0x148272430`) | b |
| `+0x5328` | 30 "not evaluated this tick" flags | b |
| `+0x534c` | lockout countdown (frames) after a super-cancel; `+0x5348` its stamp | b |
| `+0x5350` | **result record** (0xc4 bytes): `+0` valid, `+4` action id, `+0x3c` sub-mode, published to the executor | b |
| `+0x539c..+0x53a4` | published Image `{class, heading, target}` → copied to `PlayerAI+0x1158/+0x115c/+0x1160` | b |
| `+0x5420` | current kind (`0x1e` = none); `+0x5424` kind chosen this tick | b |
| `+0x5428` | **pending decision record** (0x50 bytes) — the commitment mechanism | b |
| `+0x5478` | **fallback record** — the answer of `DribbleChallenge` (kind 3) or `Dribble` (kind 2) | b |
| `+0x54c8` | **lock** byte set when the adopted answer has class `0xd` (Shoot's lock, § decision loop step 8); short-circuits DECIDE until cleared | b (re-read for this chapter) |
| `+0x54d0` | **ThinkUnit registry** (ctor `0x14566f2e0` → unit ctors `0x14566eec0`): 26 units as fixed sub-objects, `std::map<int kind, ThinkUnitBase*>` root at `registry+0x14b8` | a-emulated |
| `+0x6998` | player index this object currently serves | b |
| `+0x699c…+0x69a8` | four floats from the CPU level table rows `0x1b`,`0x1c`,`0x1d`,`0x1e`, refreshed every tick (`0x145653d7c..0x145653db3`) and passed by pointer to every unit through the context (their consumer inside the units is not traced) | b |
| `+0x69b0` | post-image work (`0x145669a00`) | b |

**Ball-relation state** `[+0x18+0x58]`: predicates over it are `0x143e34030` (true for 1, 2 — "has
the ball"), `0x143e34040` (10–13), `0x143e34060` (a 3..9 subset, "abort"); the candidate builder
switches on 10, 11–13, 14. Names are not recovered. [b]

## The think context

`0x14566be60` builds a 0x70-byte context passed to every unit: [b]

```
ctx+0x00 &playerIdx (BP+0x18)   +0x08 own-team table (BP+0xb0)   +0x10 opp table (BP+0x4ac)
ctx+0x18 match holder           +0x20 possession block (BP+0x8a8) +0x28 teamObj
ctx+0x30 &frameStamp (BP+0x8a8) +0x38 pass work (BP+0x8bc)        +0x40 Intention*
ctx+0x48 ImageMgr*              +0x50 &BP+0x14 (the possession random) +0x58 &levelParams (BP+0x699c)
ctx+0x60 Personality*           +0x68 post-image work (BP+0x69b0)
```

The Image loop builds its own context with the Personality **copied inline** at `+0x60/+0x68..`
(`0x14566ac00`), so ImageUnits see the same floats.

## The ThinkUnit contract (3 slots)

`ThinkUnitBase` vftable `0x147723dd0`: slot 0 = dtor; slots 1 and 2 = `0x144f83074`, an import thunk
(`jmp [rip+…]` into the IAT — MSVC's `_purecall`). Both are **pure virtual** in the base. [b]

| slot | signature | what | evidence |
|---|---|---|---|
| 1 | `void reset(this)` | writes the constructor's initial values back into the unit's private state (`+0x78…`); many units share the `ret 0` stub `0x140c83910` | b (all 26 read) |
| 2 | `void think(this, AnswerRecord* out = this+0xc, Ctx* ctx)` | the evaluation; fills an **answer record** or leaves it empty | b (`0x14566bee0` is the only caller: `call [vt+0x10](unit, unit+0xc, ctx)`) |

There is **no "am I applicable" slot and no score slot**. Applicability is whether `think` fills the
record (`rec+0 != 0`, tested by `0x144a17130`); eligibility is decided *outside* the unit by the
pre-think gate `0x145654820`. `0x14566bee0` has exactly one caller (`0x1456525db` in the unit runner
`0x145652570`), and `0x145652570` has five call sites — four in DECIDE (kinds 3, 2, the list) and one
in the super-cancel path (kind `0xa`). No `vf2` is ever called directly (E8 scan of `.xcode`). [b]

Per-unit bookkeeping lives in the base part: `unit+0xc` = the answer record (0x50 bytes), `unit+0x5c`
= age stamp (`-1` = never answered), `unit+0x6c` = state (`0` disabled, `1` armed, `2` answered).
`0x14566bfa0` = arm (state←1, reset record); `0x14566bee0` = run (if state==1 call `think`, stamp,
state←2). A unit in state 2 is **not re-thought**: its old record is resubmitted each tick until the
reaction-delay filter accepts it or the kind drops off the list (then it is re-armed). [b]

### The answer record (0x50 bytes)

`rec+0` = **answer class**, `rec+4` = kind (`0x1e` none), `rec+8` shot type, `+0xc..+0x14` shot aim,
`+0x1c` = target player (`0xff` none), `+0x20` = pass type (0 ground, 1, 2 lofted/cross, 3; 4 = unset),
`+0x24..+0x2b` pass flags, `+0x2c` dribble sub-type (`+0x30` heading), `+0x3c` special-dribble
sub-type (`0x25` none), `+0x40` heading, `+0x44/+0x46` bytes, `+0x48` clear power (−1 unset),
`+0x50` stamp (−1 = no decision), `+0x58` a float −1.0 that **nothing compares**. Reset by
`0x14566a200`. The class decides what the executor gets (apply function `0x145651cb0`, jump table
`0x145651fb0`): [b — re-read for this chapter; the earlier version of this table had 2/7 and 3 wrong]

| class | meaning | written by | action id |
|---|---|---|---|
| 0 | no answer | — | 0 `NOTHING` |
| 1 | **shoot** | `ThinkUnitShoot` | `0x19 SHOOT` (or `0x68 PENALTY_KICK` when `match+0x3308==3 && +0x34a0==6`) |
| 2 | **pass** to `rec+0x1c` with type `rec+0x20` | every pass unit, `PassTarget`, `PassRandomTest` | `0x145652260(rec)` → pass command |
| 3 | **dribble / carry** with sub-type `rec+0x2c` (0 plan, 1, 2 "move to heading", 3) | `ThinkUnitDribble`, the fallback | kick/move builder `0x145651ff0` |
| 4 | **feint / special dribble** (`rec+0x3c` = `0xd`, `0x17`, move id) | `Dribble`, `DribbleChallenge` | if `0x144311c90` → kick builder with mode; else `0x1b FEINT` (`0x1a KICK_FEINT` when `+0x3308==3`) |
| 5 | **clear** with power `rec+0x48` | `ThinkUnitClear` | `0x15 CLEAR` |
| 6, 0xd | GK pick-up / **lock** | `Shoot` writes `0xd` | `0x57 KP_PICKUP_BALL`; `0xd` also sets `BP+0x54c8` |
| 7 | **pass on request** (target from the request matrix) | `PassRespondRequest` | as class 2 |
| 8 | ? | — | `0x66` (table name `THROWIN_ROTATE`; GK path, not verified) |
| 0xa | **"shooting situation, not yet"** — replaced by the fallback dribble record in DECIDE | `Shoot` at `0x1456866fd` | — |
| 0xb, 0xc | GK coaching flags | — | `0x54 KP_COACHING` |
| 9 | no-op | — | — |

Action ids are the match action enum whose 131-entry name table is at `0x148082f80`
(`0x144338af0(id)`: `NOTHING, BASE_POSITION, FREE_RUN, DRIBBLE, TRAP, … SHOOT=0x19, KICK_FEINT=0x1a,
FEINT=0x1b, SWITCH_PASS=0x1c, SPACE_RUN_* = 0x1d..0x21 …`). The off-ball chapter's run ids are the
same enum. [b]

## The registry and the kinds

The 26 units are fixed sub-objects constructed by `0x14566eec0` in one sequence, then
`0x14566f2e0` inserts 25 of them into a red-black tree keyed by **kind** (insert `0x14566edc0`).
Emulated build + lookup (`0x14566ff10(registry, kind)`) for every key 0..0x1f, with sub-object
offsets from the registry: [a]

```
 0 Shoot +0x720       1 Clear +0x7a0        2 Dribble +0x0        3 DribbleChallenge +0xf0 (nested in Dribble)
 4 Feint +0xf78       9 PassGoalFront +0xb90 a PassBackSpace +0x898 b PassForward +0x818   c PassSideChange +0xc08
 d PassSafety +0xa18  e PassCross +0x9a0    f PassEarlyCross +0xb18 10 PassLong +0x918   11 PassExpand +0xa98
12 PassOneTwo +0xc80 13 PassDirectHighBall +0xcf8  14 PassSpecial +0xd70  15 PassTarget +0xdf0
16 PassRespondRequest +0xe68  17 PassRandomTest +0xee0  18 GKClear +0x12c0  19 GKDribble +0x1048
1a GKPassShort +0x11c0  1b GKPassLong +0x1240  1c Force +0x1338  1d SetPlay +0x13b8   (5,6,7,8 and 0x1e+ → not found)
```

**`ThinkUnitHoge` (`+0x1440`) is the not-found sentinel**: it is constructed last, never inserted,
and `0x14566ff10` returns `lea rax,[registry+0x1440]` for any absent key; its slots 1 and 2 are the
image's 3-byte `ret 0` stub `0x140c83910`. It is a null object, not a placeholder. [a]

`0x1e` (30) is "no kind" everywhere (list capacity, table size, `+0x5420` sentinel).

Construction order is **not** consultation order, and the map's in-order walk (`0x1456700a0`, used
only for reset-all) is key order. Consultation order comes from the candidate list below.

## THE DECISION LOOP — `0x145654060` ("Set action[%s] to output buff")

Quoted from the function, in execution order: [b]

1. Bail if the player index > 0x15 or `BP+0x10` (active) is clear → result stays invalid.
2. Build the context. Clear the lock `+0x54c8` unless `0x143e34040(state)` and
   `match+0x3308 != 2`. Decrement the lockout `+0x534c`. If the lock is set → **skip to the
   epilogue** (the previous result stands).
3. If `0x144311e20(currentAction)` or `0x144311e20(ctx[0x2c])` or **`byte[entity+0x41] != 0`**
   (`0x145654257`; entity = `0x1442d6ef0(match, idx)`): the full decide continues **only** when the
   lockout counter `+0x534c` is **non-zero** (`cmp [r14+0x534c],0; jbe 0x145654798`), the frames
   since its stamp `+0x5348` exceed `int(fps·C+0.5)`, no kind is current (`+0x5420 == 0x1e`) and
   `match+0x34a0 == 5`; in every other case control goes to `0x145651100` ("Kick Action Decided
   action[%s] by %s", "super cancel request [%s]") and **the candidate loop is not run this tick**.
   (The previous version of this chapter had the lockout sign inverted — § Corrections.)
   `0x144311e20(id)` is `id < 0x71 && (table[0x146c14e80][id] & 0x30000)` — an **action-class test
   on the current action id** (re-read for this chapter), read here as "a kick action is already in
   flight" [c on the class name]. It is *not* a human-control test.

   **What `0x145651100` does** [b]: if `byte[entity+0x41]` is set (`0x1456511a2`) it writes the
   result record directly — `+0x5350 valid = 1`, `+0x5354 action = 3 DRIBBLE`, sub-fields zeroed,
   target = the entity's own position `playerRef+0x34..0x3c`, or, when `0x143e33fd0(playerRef)` is
   false, that position advanced by the velocity `playerRef+0x50c..` over `int(fps·k+0.5)` frames
   (`0x1456511ad..0x1456512e9`) — a **move-only output written without the candidate loop**. If the
   byte is clear it runs the super-cancel decision `0x145652960` only while `+0x534c == 0` and, on
   success, arms the lockout `+0x534c = int(fps·0.2+0.5) + int((1 − 0.6·ctx[0x58]->+4)·…)`. **Both
   paths then join a common tail at `0x14565151a`** (`0x1456512e9 jmp 0x14565151a` from the set
   path; `0x1456512f5 jne` / `0x145651308 je` from the clear path): when `retryWork+0x40 > 0`
   (`0x145651520`), ctrl byte 8 (`0x14565152e cmp byte [r12],8` or `0x145651535 cmp [entity+0x2c],8`)
   and the last kind ∈ {0xe, 0x10} (`0x145651540`), the **PassBackSpace kind-0xa re-run**
   `0x14565156e call 0x145652570` executes and, on an accepted class-2 answer (`0x145651585 cmp
   [rsp+0x20],2`; `0x145651590 cmp [rsp+0x40],3`), copies the record to `+0x5428`, sets
   `+0x5420 = 0xa`, `+0x5350 = 1` and applies it through `0x145651cb0` (`0x1456515e8..0x145651650`) —
   **overwriting the move-only result** written at `0x1456511ad`. So the `+0x41` divert bypasses
   the candidate loop *except* for that re-run, which is reachable on both sides of the test.
   `entity+0x41` is copied every tick from **`match::Player+0x7f49`** by the entity-snapshot function
   `0x144157270` (`0x1441574bc: movzx eax, byte [r14+0x7f49]; mov [rsi+0x41], al`, next to
   `Player+0xec0c → entity+0x2c`, the action id tested in this same step). No disp32 writer of
   `Player+0x7f49` exists in the image (it is set through a sub-object pointer), so **its meaning is
   undetermined** — "pad-controlled" is the obvious candidate and nothing more (§ human vs CPU,
   § Open questions).
4. **Commitment check.** `0x14566a2d0(pending)` — true when the pending record's class is 1, 2, 5
   or 7 (shoot, pass, clear, pass-on-request; jump table `0x14566a2f4`) → apply it (`0x145651cb0`)
   and **return without thinking**. Otherwise `+0x5424 ← 0x1e` and reset the pending record.
5. **Fallback.** If `0x143e34030(state)` (has the ball):
   - not a goalkeeper (`!0x1442e1050(match, idx)`, see § Goalkeeper): within `int(fps*0.5+0.5)`
     frames of a recent move (`BP+0x8d`, `BP+0x90`) reuse the fallback record with kind 3; else run
     **`DribbleChallenge` (kind 3)** directly; if it gives no answer run **`Dribble` (kind 2)**.
   - goalkeeper: run **`Dribble` (kind 2)** only.
   The fallback is copied to the pending record. **Dribble and DribbleChallenge are never in a
   candidate list; they are the always-evaluated floor.**
6. **Evaluate the candidates in list order** (`mgr+0x678/0x67c`): for each kind → `0x14566ff10`
   lookup → `0x145652570(BP, kind, ctx, &rec)` (pre-think gate `0x145654820`; if the unit is armed run
   `think`; if it answered and `0x143e34030(state)`, apply the **reaction-delay filter**
   `0x145653450`; copy the answer or, for kind 3 only, the fallback) → store in the results table.
   Kinds not in the list get the empty record; units in state 2 that are not listed and are not
   kinds 2/3 are re-armed (`0x145654591..`).
7. **Select** `0x145650cf0` → `"\tAdopt Answer from [%s]"` (the kind-name getter `0x143e8fe10`
   returns a constant empty string — there is no kind name table).
8. If a kind was chosen: pending ← results[kind]; then `mov eax,[pending]` (the **answer class**):
   **if class == 0xa the pending record is replaced by the fallback dribble record** (`0x14565468d`);
   **if class == 0xd set the lock `+0x54c8`** (`0x1456546d7`). Apply the pending record to the
   result, `+0x5420 ← kind`. If `match+0x41cc == 0x1f` and `0x143e8ff30(rec+4)` → force
   `0x18 THROUGH_PASS`.
9. Epilogue: `Player+0x8 ← action id`; return `result.valid`.

Step 8 is the mechanism behind a visible behaviour: `ThinkUnitShoot` answers class `0xa` ("in a
shooting situation, not shooting yet") when its carry test passes (`0x1456866f6`, `this+0x78` from
attribute `0x32` × 0.8/100 vs `player+0x60`, and `P4 > 0.3·r`). Because Shoot is ahead of every pass
unit in the list, that answer **wins the arbitration and is then swapped for the dribble** — the
striker carries and every pass unit loses. [b] (The previous version of this chapter read the two
compares as unit ids `0xa` PassBackSpace / `0xd` PassSafety; the compared value is `[pending+0]`,
the class.)

### The selector `0x145650cf0` — first valid answer in list order [a]

```
for kind in candidateList (in order):
    rec = results[kind]; if rec.class == 0: continue
    if match+0x3308 == 2:  situation 0x41cc ∈ {3,9,10}: skip if rec.class ∈ {2,5}
                           0x41cc == 0xd: skip rec.class ∈ {1,2} while 0x1442eb950() < fps*3 AND 0x1442de630(match) == 0xa   (0x145650dcb..0x145650e10)
    if match+0x3308 == 1:  the veto block below, else RETURN kind
    RETURN kind
RETURN 0x1e
```

Emulated with synthetic answer tables by two independent harnesses (list = the CPU default list
`Force, PassRespondRequest, PassSpecial, Shoot, PassBackSpace, PassForward, PassCross, PassOneTwo,
PassSafety, PassDirectHighBall`):

| valid answers | chosen |
|---|---|
| PassSafety, PassForward | **PassForward** (earlier in the list) |
| PassCross, Shoot | **Shoot** |
| PassForward, PassSpecial, Force | **Force** |
| PassBackSpace, PassOneTwo | PassBackSpace |
| (none) | NONE (0x1e) |
| same two valid, list reversed | the other one |
| last candidate given class 999 | still the earlier one |
| `0x3308=2, 0x41cc=3`: PassSafety(class 2) before PassForward(class 3) | PassForward (class 2/5 skipped) |

**Selection is a priority chain: the list order is the whole policy.** There is no score, no
comparison between answers, no attribute and no RNG in the selector. [a]

The `0x3308 == 1` veto block is a **switch on the fallback record's class** (`BP+0x5478`), and the
inner tests are nested under it, not independent [b, re-read instruction by instruction for this
repair; a for the outcomes emulated earlier]:

```
fallback class 4 (special dribble 0xd/0x17):  every candidate loses, unconditionally
        (+0x54be set → walks the veto chain with sil=0; either way ends at 0x145650f2e: cmp [BP+0x5478],4 ; je NONE)
fallback class 3 AND byte +0x54b2 == 1:       the veto chain (sil=1) —
        kinds 0xb/0xd/0x12 (PassForward, PassSafety, PassOneTwo) lose      (bt 0x42800)
        a current action 0x12 LONG_PASS loses                                (0x145650eab)
        PassBackSpace (0xa) loses when *ctx[0x50] > ctx[0x58]->+4 and BP+0x74, or when
            P4 > *ctx[0x50] with held image 1 (Dribble) and *ctx[0x50] > 2·P2  (0x145650eb9..0x145650f01)
        PassExpand (0x11) loses when Intention byte +0x311                   (0x145650f0b)
        finally byte +0x54b0 == 1 → lose                                     (0x145650f21)
        else the candidate wins
fallback class 3 without +0x54b2, or any other class (0, 1, 2, …):  the candidate wins immediately
```

So the P2/P4 read in the arbiter and the `LONG_PASS` veto fire **only** when the fallback is a
class-3 record carrying byte `+0x3a`; for a plain dribble fallback (class 3 with `+0x3a` clear — the
common case) none of them fire and any valid pass or shot beats plain dribbling. `+0x54b0/+0x54b2/
+0x54be` are fallback-record fields `+0x38/+0x3a/+0x46`; `+0x2c..+0x3b` of a class-3 record is a
16-byte copy from the plan (`0x14566a330: mov [rcx],3; movups [rcx+0x2c],xmm0`), so "feint in
progress" for `+0x3a` is a guess and the bytes are best called **unnamed plan-record bytes** [c].
This is still the only place the selector reads a Personality value, but only on that branch.
`match+0x3308 == 1` is taken as open play (the double-tap gate and the shoot-in-own-half gate key on
it too) but no writer was found. [c on the state's meaning]

### Who is in the list, and in what order

The list is rebuilt every tick by the Image loop (`0x14566aa10` → `0x14566b7f0` at `0x14566b301` →
`0x14566b980`), **after** the Image is chosen, keyed on the ball-relation state and then on the
held Image. The push helper `0x143e8fdb0` ignores duplicates (30 flags at `list+0x7c`). All push
sites in the image are in these two functions (32–33 depending on how one counts the shared tail);
the only other writer is the clear `0x143e8fde0`. Both builders were **executed** for all 16 images
and every state with the push helper stubbed as a recorder, and the recorded lists match the
tables below. [a]

`0x14566b7f0` (state first; `esi = dword[team+0x778+0x3b40 + (slot%11)*4]` = the **role code**):

| condition | list |
|---|---|
| state 10 | `Shoot, PassForward, PassBackSpace` |
| state 11, 12, 13 | `SetPlay` |
| state 14 | `PassRespondRequest` |
| `0x143e34060(state)` true | `PassRespondRequest, SetPlay` |
| `0x1442de630(match) != idx` (tested only when the value is ≤ 0x15; the function returns `dword [g+0x28780]`, read here as the holder's slot — but the arbiter compares the **same dword** against `0xa` in sub-state 0xd, so its meaning is not settled, § Open questions) | *empty* → NONE |
| **role code 0 (goalkeeper)** | `PassRespondRequest, PassForward, PassLong, PassSafety, GKClear` |
| otherwise (outfield) | `0x14566b980` below |

`0x14566b980` (keyed on the held Image `mgr+0x530`, jump table `0x14566bd0c`): always `Force,
PassRespondRequest, PassSpecial` first, then

| held Image | appended |
|---|---|
| 0 None, 1 Dribble, 2 Lilux, 6 ShotPassFromGoal | `Shoot, PassBackSpace, PassForward, PassCross` |
| 3 ShotShort, 4 MiddleShot, 5 CurveShot | `Shoot, PassCross, PassBackSpace` |
| 7 PassThrough | `[Shoot if 0x1456747a0 && 0x1456746c0 on team+0x9d4], PassBackSpace, [PassForward unless player+0x7c ∉ {1,2} and 0x145660c50(team+0x2894)->+0x10 ≥ 2]` |
| 8 PassForward | `[Shoot cond.], PassForward, PassBackSpace` |
| 9 Cross | `[Shoot cond.], PassCross, PassEarlyCross, PassBackSpace` |
| 10 Long | `PassLong`, then `PassForward, PassBackSpace` unless the ball has been held longer than `int(fps*3+0.5)` (`ctx[0x20]->+8`; a second `fps*5` test on `+0xc` when `mgr+0x4c4 > 0x15`) and `0x145660c50(..)->+0x10 > 1` |
| 11 SideChange | `PassSideChange` |
| 12 BackDFLine | `PassTarget` |
| 13 Expand | `PassExpand, PassSideChange, PassBackSpace` |
| 14 Safety | *(nothing extra)* |
| 15 CBOverlap | `PassForward` unless `mgr+0x508` |

then the common tail: `PassOneTwo`; if `mgr+0x714 > 0` **or** the held image is 10/14 **or** (image 1
and held longer than `fps*3`): unless `0x145674e70(team+0x9d4)`: `[PassLong, Clear if
team+0x3931]`, `PassSafety`; then `PassSafety` again if `0x143e31cb0(match, player)`; and always
`PassDirectHighBall` last. Recorded example, image 1 with `team+0x3931` set: `Force → PassRespondRequest
→ PassSpecial → Shoot → PassBackSpace → PassForward → PassCross → PassOneTwo → PassLong → Clear →
PassSafety → PassDirectHighBall`. [a]

So on the ball **`Force` and `PassRespondRequest` outrank everything**, and **`Shoot` outranks every
pass** wherever it is listed: a shot the shoot unit is willing to take is never out-voted by a pass.

### The gate before think — `0x145654820`

Per candidate, before `think` runs: the unit is disabled (never armed) when the CPU level table
rejects it — `0x1442e4c00(row)` on row `0x29` for **Feint (kind 4)**, `0x27` for **PassBackSpace
(0xa)**, `0x28` for **PassSafety (0xd)**. Stock rows (read from the table for this chapter; the
previous version had them wrong by a row stride — see § Corrections), columns
`c0 Beginner, c1 Amateur, c2 Regular, c3 Professional, c4 Top Player, c6 Superstar, c8 Legend`:

```
row 0x27 (PassBackSpace): 0 0 1 1 1 1 1 1 1 1   → off at Beginner and Amateur
row 0x28 (PassSafety):    1 1 1 1 1 1 1 1 1 1   → always on
row 0x29 (Feint):         0 0 0 1 1 1 1 1 1 1   → off below Professional (inert: Feint is never listed)
```

When `match+0x3308 == 1` a block of kick-timing tests (`0x143e8ff10/20/30/80` kind classifiers,
`fps*0.25` / `fps*0.2` windows) can veto the pass kinds. The function is 3 KB and not fully
decoded. [b]

### The reaction delay — `0x145653450` + `0x1456526a0` [a]

An answer from a player who has the ball (`0x143e34030`) is accepted only when
`frame − rec.stamp ≥ delay`:

```
delay_frames = int( GetParam(row) / 54 * tick )    row 0x17 for class 2/5 (pass, clear), 0x18 for class 3 (dribble),
                                                    0x19 for class 3 answered by kind 3 (DribbleChallenge); other classes 0
```

`AiLevelUnit::GetParam 0x1442e48f0(ctx, row)` reads `0x146c06f40 + row*0x2c + 4 + col*4`
(`0x146c067b0` in the online mode selected by `0x14533eb60`), a row being `{u32 step-flag, 10
floats}`; the decoded level `[ctx+4]^[ctx]` 0..6 selects column 0,1,2,3,4,6,8 in mode `[ctx+8]=0`
(modes 1/2 use the odd columns / midpoints; level ≥ 7 clamps to Legend). [a — emulated for rows
0x17, 0x1a, 0x1b..0x1e, 0x20, 0x21, 0x2a × levels 0..7 × modes 0..2 on both images]

Stock rows and the resulting delay **in ticks** — the raw table value when the runtime tick global
equals 54 (exe-gameplay-map row 75); the harness stubbed the tick to 60, which gives the bracketed
values. Wall-clock seconds depend on that runtime global, which has not been read while the game
runs [c for any seconds figure]:

| answer | row | Beginner | Amateur | Regular | Professional | Top Player | Superstar | Legend |
|---|---|---|---|---|---|---|---|---|
| pass / clear (class 2, 5) | `0x17` = 60 40 22 12 8 8 6 4 2 0 | 60 (66) | 40 (44) | 22 (24) | 12 (13) | 8 | 6 | 2 |
| dribble (class 3, kind 2) | `0x18` = 60 35 30 16 8 8 6 4 0 0 | 60 (66) | 35 (38) | 30 (33) | 16 (17) | 8 | 6 | 0 |
| dribble move (class 3, kind 3) | `0x19` = 60 35 25 20 12 10 10 10 10 0 | 60 (66) | 35 (38) | 25 (27) | 20 (22) | 12 (13) | 10 (11) | 10 (11) |

So a Beginner CPU sits on a decided pass for 60 ticks and a Legend CPU for 2 — about 1.1 s versus
~40 ms *if* the tick is 54 Hz — and "the CPU passes faster on Superstar" is literally true in this
subsystem. Remember that while a unit waits, its answer is not in the table (§ Commitment). The filter then modifies the delay per
kind (a 28-way jump table on `kind−2`: PassSafety ×0.7 plus vetoes; PassBackSpace/PassForward/
PassLong ×(1 − 0.5·f(team tempo `+0x3934/+0x3938`)); Dribble halved when the Intention class is 0
or by 0.6·g(tempo); kinds 0x13/0x18/0x1c/0x1d accepted outright; match state 8 accepted outright)
and refuses while a `LONG_PASS` is in progress. Shots (class 1) are not delayed by this mechanism.
[b for the filter] The per-team level struct comes from `0x1442ee570` (copies `team+0x8f2c`
attack / `+0x8f38` defence by `team+0x28d`) and is forced to level 0 through `0x1442e47f0` when the
disable byte `team+0x8f48` (written at `0x1442f0179`) is set. [b]

### Commitment / hysteresis — how long a decision holds

- **Shoot, pass and clear (classes 1, 2, 5, 7) are sticky**: step 4 re-applies the pending record
  every tick without thinking, until the record is reset — which happens when the player stops
  being the carrier (`0x145653b90` tail-calls the full reset `0x145651b90` the moment the activation
  test fails) or on the super-cancel path. [b]
- **Dribbles are re-decided every tick** (class 3/4 pending records fail `0x14566a2d0`).
- After a super-cancel the lockout `+0x534c = int(fps*0.2+0.5) + int((1 − 0.6·ctx[0x58]->+4)·…)`
  blocks a new decision (`0x145651100`). [b]
- A class-`0xd` answer sets the lock `+0x54c8`, which freezes the result until state/situation change.
- The Image layer has its own hysteresis: the held Image is kept while its `shouldEnd` is false,
  and a just-ended Image is on cooldown for `0x14533eb20()` ticks (54 on PC).
- A unit in state 2 is not re-thought while it waits for the delay filter — but its record is
  **absent from the results table** on every tick the filter refuses it (`0x145652612`: only kind 3
  gets the fallback copied; every other kind exits with the output untouched, i.e. empty). A delayed
  answer is therefore invisible to the selector, and a *lower-priority* unit whose own delay has
  already elapsed (PassSafety at ×0.7, for one) wins the arbitration instead. The priority chain
  runs over **delay-accepted** answers: the delay changes *which* unit wins, not only when the answer
  leaves. [b]

### Goalkeeper vs outfield; human vs CPU

Two different distinctions, and the earlier version of this chapter conflated them.

**Goalkeeper.** The list builder's branch at `0x14566b8eb` tests
`dword[team+0x778+0x3b40+(slot%11)*4] == 0`. `0x778+0x3b40 = 0x42b8`, and `team+0x42b8[slot]` is the
**formation role code** array (probe evidence: role 1 gates the CB-overlap image, roles 7/9 unlock
Personality `P3`, `Personality::update` reads it as `playerRef+0x18`). Role 0 is the goalkeeper: the
list it selects ends in `GKClear`, `0x1442e1050(match, idx)` (re-read for this chapter) returns
exactly `on-pitch && team+0x42b8[slot%11] == 0` and is what DECIDE uses to give the GK a
Dribble-only fallback and what `ThinkUnitClear` uses to allow a clear. [b for the bytes, c for
the name "role code 0 = GK" — inferred from `GKClear`, the CB-overlap role-1 test and the
GK-only fallback]

| | outfield carrier | goalkeeper carrier |
|---|---|---|
| candidate list | `Force, PassRespondRequest, PassSpecial, …` per Image | `PassRespondRequest, PassForward, PassLong, PassSafety, GKClear` |
| fallback | `DribbleChallenge` then `Dribble` | `Dribble` only |

**Human.** Nothing *named* pad-control is tested in the decision chain: the activation test
`0x1456516d0` requires only that the player is on the ball (`byte[match+0x41f6+idx]`, the retry-work
state, `0x1442e1170`, side checks); the list builder branches on role; step 3's `0x144311e20` is an
action-class test. But step 3 has a **third condition that was not examined until this repair**:
`byte[entity+0x41]`, copied every tick from `match::Player+0x7f49`, whose writer is not located.
When it is set the carrier is routed to `0x145651100`, which does **not** run the candidate loop —
it emits a move-only result (action 3, target from the entity's own position/velocity) and then
falls into the function's common tail `0x14565151a`, where the PassBackSpace kind-0xa re-run
(`0x14565156e`; ctrl byte 8, last kind ∈ {0xe, 0x10}) can still overwrite that result before it
returns. So there are two possible worlds and the bytes do not yet pick one: if `Player+0x7f49`
is "pad-controlled", the human's carrier is diverted onto the move-only path and never sees the CPU
list; if it is something else, the machine runs for the human's carrier with the outfield CPU list
and publishes an answer to `Player+0x2760`/`+0x1158` whose execution for a pad-controlled player is
not established (the human's commands come from `match::CommandPlayer` and the
`match::pad::ThinkUnit*` interpreter, see [exe-gameplay-map.md](exe-gameplay-map.md); the assist
re-run of PassBackSpace after a cross/long pass sits on the common tail `0x14565151a` of
`0x145651100`, reached from both the `+0x41`-set and `+0x41`-clear paths).
**"Runs for the human with the outfield list" is untested, not structural**; identifying the writer
of `Player+0x7f49` decides it (§ Open questions). One probe's earlier claim that "the human carrier
is throttled onto `0x145651100`" rested on reading `0x144311e20` as a pad-bit test; that reading
was wrong, but the conclusion may yet be right for the reason above.

## The Image layer — the plan

An **Image is a plan held across frames**, not a per-frame score and not a filter. The ImageMgr at
`BallPlayer+0x4230` holds 16 `ImageUnit`s as fixed sub-objects, indexed 0..15 through the pointer
array at `mgr+0x718`: `0 None · 1 Dribble · 2 Lilux · 3 ShotShort · 4 MiddleShot · 5 CurveShot ·
6 ShotPassFromGoal · 7 PassThrough · 8 PassForward · 9 Cross · 10 Long · 11 SideChange ·
12 BackDFLine · 13 Expand · 14 Safety · 15 CBOverlap`. The loop `0x14566aa10` was executed under
Unicorn with 16 instrumented fake units recording `(frame, unit, slot)`; every statement about the
contract and the walk below is what the game's own bytes did. [a]

### The 6-slot contract

| slot | what | evidence |
|---|---|---|
| 0 | reset | a |
| 1 | **evaluate** — runs every frame on every *candidate*; refreshes the unit's target and enable byte | a |
| 2 | **canStart** → bool | a |
| 3 | **shouldEnd** → bool — asked only of the held image | a |
| 4 | onEnd | a |
| 5 | **execute** — every frame on the held image; writes the intention `{kind, target}` to `mgr+0x538/+0x53c` | a |

`ImageUnitNone`: slot 2 = `xor al,al` (never starts), slot 3 = `mov al,1` (always ends), slot 5 zeroes
the kind. `ImageUnitDribble`: slot 2 = `mov al,1`, slot 3 = `xor al,al` (never self-ends), slot 5 =
`0x145677470`. Dribble is appended **last** to every candidate list, so after the first frame the
manager is never empty. [a]

### How one Image is chosen — `0x14566aa10`, once per frame from PRE-PASS

(a) If the abort predicate `0x143e34060` is true the held image is reset (its slot 0) and
`current = 0`. (b) A candidate list is built: `[ShotShort, MiddleShot, CurveShot]` are prepended when
the shot gates allow (seeded unless `(0x144300990 && 0x144300a40) || 0x143e31cb0`), then a fixed
ordered set keyed by the **situation class** (`Intention+8`, computed just before by
`0x145662ed0`): [a — the slot-1 call order recorded per class matches exactly]

| class | list (before the trailing Dribble) |
|---|---|
| 4 | PassThrough, Cross, ShotPassFromGoal, PassForward |
| 3 | CBOverlap, ShotPassFromGoal, Cross, PassThrough, Expand, PassForward, SideChange |
| 2 | ShotPassFromGoal, Long, SideChange, Cross, PassThrough, Expand, PassForward, CBOverlap |
| 1 | Lilux, [Safety if `mgr+0x714 > 0`], Long, SideChange, CBOverlap, PassThrough, PassForward, Expand (the last two swap when `input+0x84 == 1` and the possession float exceeds a threshold), Cross |
| 0 | Safety alone — unless `mgr+0x714 == 0` **and** the 0xff-list at `BP+0x8bc+0x2894` has ≥ 2 entries, in which case the class-1 list without Safety |

(c) Slot 1 on every candidate. (d) If an image is held, its slot 3; if true, a cooldown record
`{1, now}` is written at `mgr+0x5f4+idx*8`, `current = 0`, slot 4 is called, and that image is
excluded from re-entry *this* frame. (e) Walk the list **in order**: skip the just-ended one; **stop
when reaching the held image** (keep it); skip an image whose cooldown record is set and
`now − endFrame < 0x14533eb20()` ticks (54 on PC; index 3 ShotShort is exempt); otherwise call slot 2
and **the first `true` wins**, resetting `{kind=0, target=0xff}` and the sub-struct at `mgr+0x540`.
(f) `mgr+0x534++`, slot 5 on the held image.

Consequences proven by execution: selection is a priority chain; an image **earlier** in the list
can preempt the held one on any later frame (Cross held, Expand startable next frame → Expand held);
an image **later** in the list can never displace it (Cross held, Dribble startable → walk stopped at
Cross); a finished image cannot restart for 54 ticks (ended frame 2, re-held frame 56; ShotShort
ended frame 2, re-held frame 3). This is the opposite of the off-ball layer's sorted-by-score
bidding. [a]

### What the chosen Image changes downstream

1. **It selects the ThinkUnit candidate order** (`0x14566b980`, above), and the pass units are gated
   by the held index: PassCross needs Cross(9), PassLong needs Long(10), PassSideChange needs
   SideChange(11), PassExpand needs Expand(13), PassSafety needs Safety(14), PassTarget needs
   BackDFLine(12), PassBackSpace needs PassThrough(7) (`0x14569b340`). PassOneTwo's entry gate is
   *not a shot image* (3–5 rejected at `0x14569e21e`) **and** Intention class < 3 (`0x14569e234`);
   image 5 and image 7 only select inner sub-paths (`0x14569e394`, `0x14569e499`).
   **`ThinkUnitShoot` does not require a shot image.** The test at `0x145685c88` (`sub ecx,3;
   cmp ecx,ebx; ja 0x145685d01`) skips only the call to `0x14565f000` and the store
   `mov byte [r15+0x7a],1`; execution falls into the shot acceptance `call 0x1456838c0`
   (`0x145685d15`) and the class-1 write at `0x145685d23` **under any held image**. `0x1456838c0`
   (119 instructions, `0x1456834d0..0x145683a98` merged) reads neither `+0x7a`, `mgr+0x530` nor
   `ctx+0x48`; the `+0x7a` flag is consumed later at `0x14568626d`, only under image 4
   (`cmp ecx,4` at `0x145686264`). A second class-1 write at `0x145685e4a` sits behind level row
   `0x20` (Professional up, `0x145685d3f`), `r14b` (`0x145685df7`), `P4 > k·r` (`0x145685e0d..0x145685e15`)
   and `0x1456841c0`; the two `r` compares at `0x145685da9/0x145685dba` only select which of three
   `xmm6` values is computed and gate nothing. So the CPU can answer "shoot" under any
   plan; the MiddleShot/CurveShot images change the *plan roll*, not Shoot's permission to fire
   (an earlier version of this chapter said "refuses unless" — § Corrections). `mgr+0x530` is read
   at 141 sites in ~40 bp functions. [b]
2. **Six pass units read the Image's target** (`mgr+0x53c`) and compare it against their own
   candidates — *the Image picks the man, the ThinkUnit decides the ball.* [b]
3. The `{kind, target}` is converted by `0x1456762e0` into a heading at `mgr+0x5e8` (kind 5: atan2
   toward the target's velocity-predicted position; kinds 1–4 via four helpers dispatched through
   `call r10` at `0x14567650b`), and `0x145669a00` uses that heading (for kinds 1..4; else the carrier
   facing) as the reference direction of the per-candidate pass table it builds at
   `registry+0x10+playerNo*0x28` before `0x1456671c0`. [b]
4. It is **exported**: PUBLISH writes `{class ∈ {2,3,4}, heading, target}` to `BP+0x539c..` and copies
   them into the PlayerAI output object at `+0x1158/+0x115c/+0x1160` (images 3–5 → class 2; 6–8,
   12, 13, 15 → 3 + target; 9–11 → 4 + target). Every reader of those cells in the `match::ai` region
   (`0x143c4fd50`, `0x143c62ac0`, `0x143ea0ec0`, `0x144147530`; 43 + 41 sites checked image-wide) is a
   struct copy or a `0xff` reset. **No off-ball selector reads the carrier's plan.** [b]

### The four rolling entry tests — where the plan gets its dice

Cross, MiddleShot, CurveShot and Long `canStart` are the only ImageUnit methods that call the LCG.
Each builds an integer percentage from player data and accepts iff `score >= RandInt(0..99)`.

**Cross `0x14567af10`** (segment `0x14567b3c0..0x14567b548` run on the real bytes with only the entity
lookup stubbed; the LCG executed for real): [a]

```
score = int(10 + 50·clamp((A[Heading 0x1d] − 60)/30, 0, 1))
      + 30 if COM flag bit 3 (Early Cross) or raw in-possession bit 8 (Cross Specialist)
      + 40 if skill card 0xe (Pinpoint Crossing)
then ×0.6 (no designated target, this+0x14 > 0x15) or ×0.8 (target set) in state 0 (input+0x7c == 0),
     ×1.2 in state 4, (score+10)×1.2 when the 'early' flag is set; min(score, 100)
roll:  reject unless score >= RandInt(100)                  (0x14567b546: cmp ebx,eax ; jb reject)
then, 0x14567b54e..0x14567b666, an ANY-OF accept chain: every test below jumps straight to
     accept (0x14567b664: mov al,1) when it fires; only falling through ALL of them reaches the
     reject (0x14567b65e: je 0x14567b162). Accept if any of:
       designated target == own index (ImageMgr+0x14)             0x14567b55e je
       0x143e30e10(input+0x80)                                      0x14567b580 jne
       team+0xb3c4 != 0                                             0x14567b58e jne
       team+0xb44d != 0                                             0x14567b59b jne
       skill card 0xe Pinpoint Crossing (0x143e31b10)               0x14567b5b7 jne
       team+0xb50 <= 0  and  team+0xb4c != 0                        0x14567b5c8 jg (skip) / 0x14567b5d1 jne
       input+0x1c > f(playerRef+0x4fc)  and  team+0xb4c != 3        0x14567b5ef jbe (skip) / 0x14567b5fc jne
       pass-work +0x34 > int(fps·5.0 + xmm15)   (5.0 @0x145a8dd78)   0x14567b621 ja
       pass-work +0x30 > int(fps·10.0 + xmm15)  (10.0 @0x145a8dd7c)  0x14567b63c ja
       COM bit 3 Early Cross (0x143e31970)                           0x14567b654 jne
       byte[team+2] != 0                                             0x14567b65e je → reject only when 0
     (an earlier repair rendered the middle tests as fall-through REQUIREMENTS — wrong, § Corrections)
bypass: team+0xb44d != 0 jumps from 0x14567b286 straight to 0x14567b54e (no score, no roll)
```

The roll is a **gate**, not the plan's entry test: it is necessary (except under the `team+0xb44d`
bypass) and not sufficient on its own — after it, at least one of the eleven any-of tests must
fire, and the plan is rejected only when every one of them fails. [a for the roll segment
`0x14567b3c0..0x14567b548`, b for the post-roll chain and the bypass]

Measured: attr 40/60 → 6, 70 → 15, 75 → 21, 80 → 25, 85 → 30, 90/99 → 36; attr 80 + card → 49,
+ style → 43, + both → 67; state 4 → 51; early → 63; target set → 34. Pass rate of the **roll
segment** over 1,500 seeds = `(score+1)/100` (25 → 0.255, 49 → 0.498, 67 → 0.673) — the segment's
pass rate, **not** the plan's entry probability, which the post-roll any-of chain above further
gates (it rejects only when all eleven tests fall through). The draw is uniform (100 distinct values over 3,000 seeds). Cross also accepts **outright**, before the roll, when the designated target holds
Extra Frontman (category 15) as a role-legal style (`0x14567b09a`, via `0x1442e21c0`). [b]

**MiddleShot `0x145678b30`**: base 60 if COM bit 5 (Long Ranger), else 50 if card `0x2a`
(Long-range Shooting), else 40 if card 8 / `0x21` / `0x22` (Knuckle / Dipping / Rising) — first match
wins (`0x145678f17..0x145678f9b`); then a **three-way bonus** (`0x145678fa4..0x145678fca`): **+40**
(`0x145678fc7`) when the Intention class == 2 (`0x145678fac je`) **or** `team+0xb44d != 0`
(`0x145678fb6 jne`); **+70** (`0x145678fc2`) when class ≠ 2, `team+0xb44d == 0` **and** `team+0x204 == 3`
(`0x145678fb8`); **+0** when class ≠ 2, `+0xb44d == 0` and `+0x204 != 3` (`0x145678fc0 jne 0x145678fca`
lands after both adds — there is no "always +40"); then attribute terms gated on
`B[KickPower 0x2b] ≥ 70` and `B[LowPass 0x1b] ≥ 70` (`0x145679035`); **the score is clamped to 90
before the roll** (`0x1456790c7: mov eax,0x5a; cmova ebx,eax`), so the entry chance never exceeds
91 %. **CurveShot `0x1456786c0`**: base 35 if COM bit 4 (Incisive Run) (`0x145678956`); the same
≥ 70 gates (`0x14567897f`); a Mazing Run branch; **clamped to 90 with a floor** (`0x145678a7c: cmp
ebx,0x5a; jbe …; mov ebx,0x5a` / `cmovb ebx,r15d`) — max 91 %; after the roll, Control Curve (card 7)
**or** Incisive Run is required. **Long `0x14567b670`**: +10 for Weighted Pass (`0xd`) / Low Lofted
Pass (`0x11`) in one branch, +50 for Long Ball Expert (COM bit 6) / Weighted / Low Lofted in the
other (`0x14567b8cf..0x14567b988`); `A[Heading] ≥ 70` term (`0x14567b9e2`); **`team+0xb3c4 != 0`
forces the score to 100** (`0x14567b8f6 → mov ebx,0x64`), and there is no cap before the roll.
Only Cross caps at 100. Their full formulas were read but not emulated. [b]

**The `RandInt` range immediate is also the RNG stream index — in all four.** Each tail does
`mov edx,0x64` (the range) and derives the stream from it: `lea r8d,[rdx-0x62]` = 2 (MiddleShot
`0x145679103`, CurveShot `0x145678ad5`, Long `0x14567ba76`); Cross keeps the value in `esi` and uses
it three ways — `cmova ebx,esi` (cap), `lea edx,[rsi-0x62]` (seeder stream), `lea r8d,[rsi-0x62]`
(RandInt stream) and `mov edx,esi` (range) (`0x14567b504..0x14567b541`). MiddleShot's cap `mov
eax,0x5a` likewise feeds the seeder's stream through `lea edx,[rax-0x58]` (`0x1456790eb`). The
local RNG state is four u32s on the stack, so any range outside 98..101 (or a MiddleShot cap
outside 88..91) indexes **outside the state** — a stack write out of bounds — and 99 silently
switches the draw to stream 1. None of these immediates is a frequency lever (§ Tunables). [b]

### The roll is fixed for the whole possession

All four seed a fresh local LCG state from `r = ctx+0x48 = BP+0x14` — with **four different
multipliers from four different pool cells**: Cross `int(r × 1500)` (`0x14567b4fc`, cell
`0x146401b78`, 5 referrers — the other four are `goal_keeper::PreSaving`, `goal_keeper::SnapUnder`,
a `match::anime` function and non-gameplay code), MiddleShot `× 1200` (`0x1456790bf`, `0x145bd7fc4`,
11 referrers), CurveShot `× 1300` (`0x145678a99`, `0x146b9b29c`, 2 referrers), Long `× 1600`
(`0x14567ba3a`, `0x1466c54f0`, 28 referrers). `BP+0x14` is refreshed (`0x145653e47..0x145653e62`) only
when negative or on the frame where the possession counter `BP+0x8ac == 1`, from
`*(0x1442d6fc0()+8)` = `*(*0x1486bd888+0x790)+8`, the **match random bundle**: its word `+0` seeds
15 other generators in the image and is taken modulo 1000 at `0x143d70d70`; `Safety::canStart`
compares `r` against `clamp((level−1)·0.5, 0, 1)`; `0x145658a03` uses `r` as a fraction of a
duration. So `r` is a random number in `[0, 1)`, latched once per possession spell, and **each
rolling image computes the same draw on every frame of the spell** — the roll behaves as a
per-possession threshold, not per-frame noise. The four images do **not** share a draw: their seeds
differ (× 1500 / 1200 / 1300 / 1600), so on one spell Cross and Long roll different fixed numbers. Replays are exact. [b; the bundle's *updater* was not
located, so "random in [0,1)" rests on convergent usage at five sites. One probe read `BP+0x14` as a
match-clock float; the Safety comparison against a 0..1 level fraction and the modulo-1000 use of
the sibling word make the random reading the better one.]

The only per-frame randomness in the layer is `0x145668ec0` (reached from PRE-PASS via
`0x145669a00 → 0x1456671c0`): it seeds from the frame counter `[match+0x3318]` (`0x14566901d`) and
draws `rand(100)/100` to perturb an aim/target coordinate for the held images CurveShot (5),
SideChange (11) and Expand (13) (cells 2.5, 16, 3, 4, 5, 2, −10). Emulated `rand(100)` with seed = frame
gives the sawtooth `0, 64, 29, 94, 58, 23, 88, …` (+64.7 mod 100), all 100 values over 3,600 frames. [a
for the draw sequence, b for the site]

### CBOverlap, Lilux, Safety

**CBOverlap** (15): `vf1` (`0x145677a70`'s sibling `0x1456778c1`) enables the unit only if the
role-gated style query `0x1442e2130(playerNo, category 15 = Extra Frontman, teamObj, teamAI)` is
true **and** `team+0x42b8[playerNo%11] == 1` (role code 1, a centre-back); `canStart` (`0x145676a00`)
re-tests the gate and also requires **attack level ≥ 2** (`0x145676b42`, `cmp [team+0xb450], 2`);
`execute` writes kind 2 with no target. It is first in the class-3 list, so with the style, the role
and the attack level it preempts every other plan. "Extra Frontman unlocks the CB overlap" is
correct: without the style the unit never enables. Category 15 = Extra Frontman via the catalogue
tables `0x1471bc0c0` (index→id) and `0x14825b2f4` (id→offCat/defCat). [b]

**Lilux** (2): `vf1 0x145677a70` enables when `team+0x204 ≤ 0` and the 0xff-list at
`BP+0x8bc+0x2894` has ≥ 3 entries; `canStart 0x145676c30` only while `this+0x10 == 0` and the carrier
is ≥ 5.0 m behind the reference line (`input+0x40 − f(…)·attackDir ≤ −5.0`); `execute 0x145677530`
increments `+0x10` only while `input+0x71` is set and emits kind 5 toward `this+0xc` (or kind 2);
`shouldEnd 0x145676830` after `tick·3 + 0.5` frames (~3 s; `tick + 0.5` when `team+0x204 != 0`).
Nothing but a manager reset clears `+0x10`, so Lilux fires **once per possession spell**, and as first
in the class-1 list it preempts everything while it runs. The name is almost certainly the
romanised Japanese リラックス ("relax"): a calm-possession plan taken once, deep, with three or more
safe options. [b; name c]

**Safety** (14): `canStart 0x145676c90` rejects when `r > clamp((level − 1)·0.5, 0, 1)` — never at
Beginner/Amateur, on half of possession spells at Regular, always from Professional up (and only
while `input+0x71 == 0`); it also demands a per-list age ≥ `tick·2 + 0.5` when `ctx+0x5c == 3`. [b]

### The other Images

PassThrough `vf1` (`0x14567c260`) tests Through Passing (`0x2b`) and One-touch Pass (`0xc`);
SideChange `vf1` (`0x145680900`) tests Creative Playmaker / Orchestrator / Build Up raw bits and
COM bit 6; `ImageUnitPassForward::vf1` reaches `0x145674ec0`, which seeds two LCG states from the
**receiver's** `B[BallControl 0x18]` and `B[Curl 0x22]` bytes and draws three times — a fixed
per-player pseudo-percentile, non-monotonic in the attribute (emulated: 51 → 1, 54 → 95, 68 → 2,
71 → 96, 99 → 9), i.e. not randomness at all. The `vf1` target-selection bodies of
PassThrough/PassForward/Expand/Long/SideChange/BackDFLine were not decoded. [b]

## The dribble moves — `ThinkUnitDribbleChallenge` and the 15 `DribbleImage`s

`ThinkUnitDribble+0xf0` holds `ChallengeDribbleWork` with the 15 moves as sub-objects and a
16-pointer table at `work+0x5b0` (slot 0 NULL; 1 NoFeint, 2 Burst, 3 Roulette, 4 BodyFake,
5 DoubleTouch, 6 EdgeTurn, 7 Eracico, 8 KickFeint, 9 DrawOpen, 10 Chapeu, 11 Humiliating,
12 TrapThrough, 13 Shielding, 14 SharpCut, 15 TapTrick). `DribbleImageBase`'s 10 slots: 0 dtor;
1 **execute** (pure virtual — a per-move phase machine on `this+8` that writes a class-4 command
`{+0x3c = move id, +0x40 angle, +0x44 dir, +0x45 = 0x100}`); 2 **weight** → float (pure virtual);
3 reset; 4, 5 return 0.0 in the base; 6 empty; 7 base helper scanning the opponent record list
(`ctx+0x68`: count at `+0x1b8`, 0x54-byte records) for the closing defender; 8 returns false; 9 base
phase-advance. This is the **only ThinkUnit body with indirect calls** (5 dispatches into the
DribbleImage vtables). [b]

**Stage A — the shortlist (`0x1456a9570`, from `DribbleChallenge::vf2`)** [a — executed end to end]:

- The **pool** is filled by `0x1456ab3b0` from skill cards only: always Burst, KickFeint, BodyFake,
  DrawOpen, TrapThrough; DoubleTouch needs card `0x28`, Roulette card 2 (Marseille Turn), EdgeTurn
  card `0x29`, Eracico card 1 (Flip Flap) **and** COM bit 0 (Trickster), Chapeu card 3 (Sombrero),
  SharpCut card `0x43`, TapTrick card `0x42`, Humiliating COM bit 0 via the team block. NoFeint (1)
  and Shielding (13) are never pooled. Attribute bytes were zero throughout and the pool was
  unaffected: **cards gate availability, attributes only scale weights.**
- Each pooled move's slot 2 returns a weight; ×1.2 at **Legend** (`0x1442e48d0(unit, 6)` = decoded
  level ≥ 6, `0x1456a96dd`); × ctx float B when ctx float A > B; the `(weight, id)` pairs are sorted
  descending (`0x1456a7ed0`); a fresh LCG is seeded from the live match tick word
  (`[0x1442d6fc0()+0]`, `0x1456a983d`) and every entry survives iff `weight > RandInt(0..99)` and
  `weight > FLT_EPSILON`. Measured over 500 seeds: 90 → 0.900, 80 → 0.796, 50 → 0.500, 10 → 0.100,
  100 → always, 0 → never; Legend lifts 50 → 0.61 and 80 → 0.96; identical seed → identical shortlist,
  +1 ms → different.

**Stage B — execution (`0x1456aac80`)** [b]: an active move (`work+0x2c8`) runs its slot 1 every frame
until its phase reaches 5 or 6 (then slot 3, removal from the shortlist, touch counter latched at
`work+0x274`); a new move can start only when `touchCounter − work+0x274 ≥ int(tick·0.5+0.5) + 54·f`
(`f = 1.0`, or **`1.0 − P4`** for Trickster players — `0x1456ab111: mov rax,[ctx+0x60]; subss
xmm7,[rax+0x18]` reads the *Personality* dribble-propensity float through `ctx+0x60`, not a level
fraction through `ctx+0x58`; so Ball Control / Speed / Acceleration and the four COM flags shorten
feint chaining, and difficulty does not); then the
**shortlist is walked in order (highest weight first)** and the first move whose slot 1 yields a
valid command becomes active; if none does, the plain dribble rolls level-table row `0x1a`
(60/35/18/13/4/0/0 % at Beginner..Legend, `0x1456ab267`) for a mistake. So the highest-weighted
surviving move nearly always wins; randomness enters only through the per-move survival rolls.

**Weights** (real functions executed with only the entity lookup stubbed; `n(v) = clamp((v−70)/20,
0, 1)` on the **effective** array `B = R[0x3d+idx]`): [a]

```
Roulette 0x1456bb810 = 25·n(BallControl 0x18) + 25·n(Finishing 0x1a) + 20·n(Acceleration 0x2c) + 10·n(Balance 0x2a)
                       [+20 if COM bit 0 Trickster] [×0.6 without card 2 — unreachable, the pool requires card 2]
                       all-70 → 0, all-80 → 40, all-90 → 80, +Trickster → 100 (always shortlisted)
BodyFake 0x1456bcb10 = 15·n(BallControl) + 10·n(Speed 0x28) + 10·n(Acceleration) + 15·n(TightPossession 0x19)
                       card 0 (Scissors) present: (+50 if Trickster) ×0.9   → all-90: 45; with Trickster 90
                       card 0 absent: (+10 if COM2 Speeding Bullet, +10 if COM4 Incisive Run, −20 if Trickster) ×0.81 → all-90: 40.5; with Trickster 24.3
```

Burst is gated by COM bits 1/2 (Mazing Run / Speeding Bullet) and card `0x37` (Accel Burst);
NoFeint/TrapThrough/KickFeint by Mazing Run / Speeding Bullet; Roulette's slot 1 draws `RandInt(10)`
in phase 3 to parametrise the move (`0x1456bc4af`), TapTrick likewise. A player with 40s in
everything still has BodyFake/KickFeint/Burst/DrawOpen/TrapThrough in his pool, but their weights
are 0 so they never survive the roll — he plain-dribbles. **Dribbling (attribute `0x17`) is read
nowhere in the carrier brain.** [b]

## Pass-target selection — who gets the ball

There is no single target routine. The **route table** at `ctx[0x38]+0xb78` (11 records × 0x2a0:
`+0` rank 0..5, `+4` state, `0xb` = receivable, `+0x130/+0x134/+0x138` distances) is computed outside
`bp` (the lane/interceptor evaluation — candidates `0x145655430` / `0x145655dd0` in the pre-decide
path and the `match::player::PassGetRoute*` family; not traced), and each pass unit chooses from the
Image plan's candidate array (`plan+0x9c`, 0x58-byte entries, count at `+0x98`) against it. Three
helpers are shared by most pass units and account for most of the "reads" attributed to any one
unit: the **pass preamble** `0x145699510` — a *flag computer* at four of its five callers and a
**hard gate** at the fifth. It returns a bool; at DirectHighBall, PassForward, PassSafety and
PassSpecial a true return sets the answer-record byte **`rec+0x24 = 1`** while a false return does
nothing (DirectHighBall `0x14569ca8b → je +6; mov byte [rbx+0x24],1`; PassForward `0x14569d639` after
class 2 is already written at `0x14569d5bc`; Safety `0x14569f343` after class 2 at `0x14569f323` /
`[r12+0x1c] = target`; PassSpecial body `0x1456a0b7c` after class 2 at `0x1456a0a14`) — there the
pass itself is emitted independently. At **PassOneTwo** (`0x14569e592`) a false return exits with the
record untouched (`0x14569e5a8 test al,al; je 0x14569e716` = the epilogue): the unit's **only**
class-2 write `0x14569e6fa mov dword [r12],2` (+`0x1c` target at `0x14569e702`, `+0x20 = 0`,
`+0x24 = 1` at `0x14569e710`; those four are every store to the record in the function) lies behind
the preamble's true branch, so every one-two the CPU plays carries `+0x24 = 1` and a false preamble
means no one-two at all. It returns false below Regular (`0x1456996cd: mov edx,2; call
0x1442e48b0; jne 0x145699617 → xor al,al`) and when the *carrier* has Defensive Full-back as a
role-legal style (`0x145699662`); it branches at Top Player / Superstar / Legend, on attack level
≥ 3 (`0x145699a12`) and on the Intention class (`0x1456996e6`, `0x145699a28 cmp 2`, `0x145699a36
cmp 3`), and reads the Classic No.10 / Anchor Man / Creative Playmaker / Orchestrator raw bits
(`0x145699aa8..`). So a Beginner/Amateur CPU (or a Defensive Full-back carrier at any level) never
gets the `+0x24` flag on its DirectHighBall / Forward / Safety / Special passes **and never plays a
one-two**; **the preamble rejects nothing at four callers and everything at PassOneTwo** (the
original chapter said "rejects everything below Regular", the first repair said "rejects nothing" —
both wrong, § Corrections). [b]
What the executor does with `+0x24` is untraced. Then the **receiver predicate** `0x145695690`
(below; writes `rec+0x25`, likewise after the pass is chosen); and the **kick-feasibility** helper
`0x145673930` (Blitz Curler card `0x33` gate at `0x145673ac9`; used by Cross::vf1 and seven pass
helpers). [b]

**PassForward (`0x14569d240`)** [a for the scorer, b for the loop and everything after it]: loop
`0x14569d320..0x14569d3d1` over the plan's candidates (`plan+0x9c`, `0x58`-byte entries);
eligibility filter `0x145690200` (reads `P0`, `P2`, `P3` and card `0xc` One-touch Pass at
`0x145690c75`); two vetoes `0x145697250` (`P1`, `P2`, `P4`) and `0x145696cd0` (`P2`, `P4`); a mate
whose in-possession **category 9 (Classic No.10) is legal for his squad role**
(`0x143e31a10(match, slot, 9)` → `0x1442bfe00(params+0x10, 9, role)`) is taken **outright**
(`0x14569d391 jne → 0x14569d3d9`, loop abandoned). Otherwise the scorer `0x145689570` is called —
**but the loop is not an argmax**:

```
ebp = 0xff (no choice);  xmm6 = 0
for cand in plan order:
    if !filter(cand) or veto1 or veto2: continue
    if ClassicNo10(cand): ebp = cand; break                       # 0x14569d391
    if ebp > 0x15:  ebp = cand; xmm6 = score(cand)                # first eligible: 0x14569d3b3..0x14569d3c7
    elif score(cand) > xmm6:  ebp = cand                          # 0x14569d3a2 comiss ; jbe — xmm6 is NEVER raised
```

The reference `xmm6` is written only on the first-eligible path (`0x14569d3c7 movaps xmm6,xmm0`);
every later eligible candidate is compared against the **first** candidate's score, never against
the current best. The receiver is therefore **the last candidate in plan-array order whose score
beats the first eligible candidate's score, or the first eligible candidate if none does** — not
the best-scoring mate. This is a genuine quirk with gameplay consequences: with three eligible
mates scoring 0.2, 0.9, 0.5 the ball goes to the 0.5 mate; who gets passed to depends on the order
the plan filled its candidate array (`ImageUnit::vf1`, undecoded) as much as on the score. [b]

```
score = w·clamp01((attackDir·(mateX − carrierX) − 10)/15) + (1−w)·clamp01((rank − 1)/3)
        w = 0.8 in situations 1–3, 0.3 in 0/4, 0.5 otherwise; rank term zeroed when *ctx50 > ctx58[1]
```

0 mismatches over 144 `(carrierX, mateX, rank, situation)` cases, identical on both images — this
validates the **scorer function only**, not the selection loop. The mate object was all-zero in
every run: **the receiver's attributes are not read by the scorer** — receiver quality enters only
through the route rank.

**After a target is chosen the answer is still not guaranteed** (`0x14569d3ef..0x14569d5bc`). A
"fast" flag `bl` is set only when `0x143e31920(idx)`, the retry-work state is not `0xa`, **`r ≤
levelParams[1]`** (`0x14569d461..0x14569d471` — a direct read of the possession random), Intention
byte `+0x325` is clear, either `0x143e33fd0(playerRef)` or frames-since-receipt `[playerRef+0x68] ≥
int(fps·(1 − c·levelParams[1]) + 0.5)`, the route-rank / post-image tests at `0x14569d4c8..0x14569d542`
pass, and `P2·k + c > route +0x134, +0x130` (`0x14569d55d/0x14569d567`), `route +0x138 > 16.0`
(`0x14569d571 movss xmm0,[r14+0x138]`; `0x14569d57a comiss` vs cell `0x145b56e28` = 16.0f) and the
carrier's **role code** `retryWork+0x18 != 0` (`0x14569d583 mov rax,[rsi]` = `ctx+0` = `&BP+0x18`;
`0x14569d586 cmp [rax+0x18], r15d`, r15d zeroed at `0x14569d3f3` — the layout table's role-code
field, not a route field). Without
`bl`, the record is written only if `0x143e33fd0(playerRef)` is true **or** `[playerRef+0x68] ≤
int(fps·0.5+0.5)` (`0x14569d590..0x14569d5b6`, `ja 0x14569d964` = return with no answer). Then
`class 2, target ebp, type 0` (`0x14569d5bc..0x14569d5c8`), `+0x2b = bl`, and the preamble (`+0x24`)
or, failing that, the receiver predicate (`+0x25`) tags the record.

**When the loop picks nobody (`ebp == 0xff`) a second search runs** (`0x14569d66b..0x14569d95c`),
gated on `0x143c71ee0(0x144304ff0(match, input+0x1c), idx) > 40.0` (cell `0x145d58ec8`) and
Intention class ∈ {1, 2} (`0x14569d6a0/0x14569d6ae`). It walks the same plan candidates and takes a
mate with route state `0xb`, route distance `+0x138` in [15, 25] m, `route+8 == 0`, `route+4 != 1`,
rank `+0 == 0`, 0xff-list byte `+0x3c` set, `+0x4c > (5·clamp((d−15)/10, 0, 1) + 10)²` and
`+0x10 ≥ 3` (plus a direction-agreement test when `mgr+0x5ec == 3`). The first qualifying mate is
kept unless a later qualifying mate lies further up the pitch, in which case the choice is cleared
and the next qualifier takes it (`0x14569d8c0..0x14569d902`). It emits **class 2 with pass type 1
(lofted)** — `mov [r13],2; mov [r13+0x1c],r14d; mov [r13+0x20],1` at `0x14569d950..0x14569d95c`. The
earlier version of this chapter said PassForward emits type 0 only. [b]

**The receiver predicate `0x145695690`** (`0x145695a2d..0x145695d0b`) is where the briefing's "22
in-possession style reads inside PassSpecial" actually live: 22 raw un-role-gated tests
(`0x1442bfdf0`) plus one out-of-possession test of The Destroyer (`0x1442bfdb0`), all on the
**candidate receiver's** record, interleaved with geometry (forward offset `dx·attackDir`, lateral
offset against 8.0 m at cell `0x145b52fbc`, an angle at `ctx+0x160` normalised around 90/180°, a
distance at `ctx+0x168`). Reached from `PassForward::vf2` (`0x14569d654`), `PassExpand::vf2`
(`0x14569d203`) and PassSpecial's body `0x14569fc30` (`0x1456a0b9a`). Emulated truth table (24
geometry regimes × 21 in-possession bits + Destroyer + none, PRISTINE): [a]

- receiver **behind** the carrier (`dx < 0`, angle < 90): default **reject**; eligible only if the
  receiver is Goal Poacher, Fox in the Box, Creative Playmaker or Hole Player;
- receiver **ahead**: default **accept**; always vetoed for Target Man, Anchor Man, Build Up,
  Defensive Full-back and The Destroyer; under the far/high flag (`dil = 1`) also vetoed for Roaming
  Flank, Classic No.10 and Orchestrator;
- at angle ≥ 90 the Dummy Runner / Fox-in-the-Box accepts flip to vetoes and Deep-Lying Forward,
  Prolific Winger, Roaming Flank, Cross Specialist, Box-to-Box, Extra Frontman and the full-backs
  become accepted.

**What this truth table does *not* do is choose the receiver.** At all three call sites the
predicate runs *after* the pass has been decided and its result only sets the answer-record byte
`rec+0x25`: PassForward writes class 2 + target at `0x14569d5bc` and calls the predicate once, on
that target, at `0x14569d654` (`je 0x14569d964` → return with the pass intact; else `mov byte
[r13+0x25],1`); PassExpand stores the return value straight into `[rsi+0x25]` (`0x14569d208`); the
PassSpecial body sets `[r15+0x25] = 1` (`0x1456a0ba3`). The pass is emitted either way. What the
executor does with `+0x25` (a pass-type or technique modifier is the natural guess) is **untraced**,
so "Target Man never receives a forward pass" and "only Goal Poacher / Fox in the Box / Creative
Playmaker / Hole Player are passed to behind the carrier" — which an earlier version of this chapter
and its Tunables table stated as a-emulated facts — are **not established**: they describe the
*tag*, not the *choice* (§ Corrections, § Open questions). [b for the call sites; the gameplay
consequence is c]

**Other units, decoded to the level stated:** [b]

- **Shoot (`0x1456853f0`, 1,191 instructions, 0 indirect calls)**: class `0xd` (lock) when player
  state 10, `env+0x334a` set and ≥ 5 s elapsed (`0x1456855bc`, 5.0 @ `0x145a8dd78`); **class 1 at
  two sites** — `0x145685d23` when `0x1456838c0` accepts (after a 25/75 m window; under **any** held
  image, any level), and `0x145685e4a` behind level row `0x20` (Professional up, `0x145685d3f`), `r14b`
  (`0x145685df7`), `P4 > k·r` (`0x145685e0d..0x145685e15`) and `0x1456841c0` — the `comiss
  xmm7/xmm8, r` at `0x145685da9/0x145685dba` are a three-way select of `xmm6`, not gates; class `0xa` "carry" as described under step 8. The possession random `r` is read
  at seven sites in the body (`0x145685da1`, `0x145685ffc`, `0x145686067`, `0x1456863b6`,
  `0x1456866d7`, `0x145686799`, `0x1456867e8`). Reads `P4`, `P5`, raw attribute `0x32` (height) via `0x1441172b0`, `B[WeakFootAcc 0x27]
  == 1 / == 3` (`0x145686436`, `0x145681c8c`), level rows `0x20` (step, on from Professional) and `0x21`
  (on from Regular) unlocking two shot branches (`0x145685d3f`, `0x145685e6b`), attack level > 2 for
  an extra gate (`0x145686696`), styles via `0x1442e2a60`, and cards Chip Shot Control `0x1f`, Control
  Curve 7, One-touch Shot `0xb`, Outside Curler `0xf`, Long-range `0x2a`, Dipping/Rising in its
  shot-type helpers (`0x1456841c0`, `0x145683aa0`, `0x145686860`, `0x145687b80`). Aim-point logic not
  decoded.
- **Dribble (`0x1456a6f70`)**: heading from `plan+0x5e8`, optionally replaced by `Intention+0x320` when
  `Intention+0x324` and the angle to it < `15·tempo + 30`; emits (a) the stored plan record (class 3)
  when just received/pressed (threat frames ≤ 0.35 s @ `0x145c7ec6c`, angle ≤ 30°, threat < 16 m…),
  (b) class 4 sub-type `0xd` when `0x1456a6450` says so (reads `P0`, `P1`, `P2`), (c) class 3 sub-type 2
  "move to heading" when `*ctx50 ≤ *ctx58`, angle ≤ 0.3, no Intention 311/312, body angle ≤ 90°,
  threat ≤ 16 m, tempo ≥ 0.25, (d) class 4 sub-type `0x17` with heading `±(20·*ctx50 + 15)` when
  `0x1456a68c0` says so, else class 3 sub-type 3. Scales a term by `ctx[0x58]` only at level ≤ 3 and
  zeroes it below Regular. No RNG.
- **Force (`0x1456acf10`, first on every outfield list)**: after prep `0x1456adad0` tries three
  sub-deciders in order — `0x1456ad520`, `0x1456ad240`, `0x1456acf90` — stopping at the first that
  writes a record; `0x1456acf90` compares `4·fps` against a frame counter (a forced release after
  ~4 s). What the first two force is not decoded.
- **PassRespondRequest (`0x14569ea20`, second on every list)**: reads a match-level **request
  matrix** at `match+0x24114 + mySlot·0xc8 + i·8` (i in 0..10); a listed slot counts if its route
  state is `0xb` (or, at set pieces, `0x1442e2a60` and state 3/4/6) and the entity record's byte `+4`
  is set; emits class 7 to the **first** listed slot with type `entity+8` (type 4 recomputed by
  `0x1456930c0`). 34 code references to `0x24114` in 16 functions (`0x143e26900` in the off-ball
  region only reads it; `Reaction::vf13`, `ActionDive::vf20`, `0x144303b30`, `0x1442b52c0`); **no
  writer of the matrix or of `[ent+4]/[ent+8]` was found.**
- **PassOneTwo (`0x14569e1d0`)**: entry gate = not a shot image (`0x14569e21e`) **and** Intention
  class < 3 (`0x14569e234`), with further class compares against 4 and 2 (`0x14569e33a`,
  `0x14569e4a6`, `0x14569e5bc..0x14569e5d8`); reads Intention flags (`+0x1b8`, `+0x30c` direction,
  `+0x310/311/312/325`), `P4` against `r` (`P4 > 0.3·r` / `0.7·r`; `r` at `0x14569e293`,
  `0x14569e314`, `0x14569e39d`, `0x14569e60c`), plus `0x145689f70` under image 7. The pass
  preamble `0x145699510` (called at `0x14569e592`) is a **hard gate** here: false → `0x14569e5a8 je
  0x14569e716` (epilogue, no record); the unit's only class-2 write is `0x14569e6fa` and every
  emitted one-two carries `+0x24 = 1`. Below Regular, or with a Defensive Full-back carrier, the
  CPU never plays a one-two. [b]
- **PassSpecial (`0x14569fa80`)**: tiny driver — requires (state 1 and `player+0x73 == 0` and ctrl
  byte ≠ `0x15`) or (not state 1 and `player+0x68 ≤ 0.3 s`); tries `0x1456a0c50` then `0x14569fc30`
  (bails below Professional at `0x14569fc6a` and when **`r > levelParams[1]`** at
  `0x14569fc77..0x14569fc87`; five more `r` reads inside; tags `+0x24` via the preamble at
  `0x1456a0b7c` and `+0x25` via the predicate at `0x1456a0b9a`).
- **PassTarget (`0x14569fb30`)**: only under BackDFLine (12): passes to the image's target
  `plan+0x53c` if not self, route state `0xb`, route rank ≥ 3; class 2 type 0.
- **PassLong (`0x14569db30`)**: reads `P2` and `r` (`0x14569e129`, against `P2`); its helper
  `0x14568ac30` picks long-ball targets on `B[Speed] ≥ 85/99`, `B[Height 0x32] ≥ 185/190`,
  `B[Jumping]`/`B[PhysContact]` vs 99. Reads no card, style or flag of its own.
- **PassSafety (`0x14569ed80`)**: image gate Safety(14); reads `r` against the level fractions
  (`0x14569edb9`, `0x14569ee44`) and exits when the Intention class > 2 (`0x14569efa5`) or
  `player+0x73`; target then preamble tag (`0x14569f343`). Body beyond that: profile level only.
- **Clear (`0x143e8fca0`)**: if (`!0x144300990(env)` or goalkeeper) and `team+0x3931` → class 5 with
  power `0x143e8d8b0(match, slot, 0)`. Reaches a list only via the tail behind PassLong.
- **SetPlay (`0x1456b0ad0`)**: `B[SetPiece 0x21] ≥ 85`, `B[Curl 0x22] ≥ 80`, cards Long Throw `0x13`,
  Control Curve 7, Knuckle 8, level row `0x2a` (on from Professional, `0x1456b0ea1`); 8 role-gated
  style queries in its closure.
- **PassRandomTest (`0x14569e740`)** — decoded, dead: gates on `r < 0.5` or `0x143e33fd0(playerRef)`;
  for each of the 11 slots (table `0x146c274c0`) other than self, on-pitch and route state `0xb`,
  `score = {60, 40, 30, −20, −40, −60}[route rank] + RandInt(this+0x7c, 10000, 2)/100` from a
  **persistent per-unit RNG stream** seeded `0x2F3CF` at construction (`0x14566f19e`) and never
  reseeded; sorted; best slot latched in `this+0x78`; class 2, type 0. Its direct closure reaches the
  LCG at depth 1.

## Personality — per-player variety, decoded [a]

`match::ai::bp::Personality` (`vft 0x147723dc0`, 0x28 bytes at `BP+0x41f8`) is **recomputed every
tick** by `0x145663920(Personality*, match, &retryWork, BP+0xb0)` — exactly one caller, `0x145653e94`
in PRE-PASS — from the player's data record `R = playerData+0x394`. With
`n(a, lo, hi) = clamp01((a−lo)/(hi−lo))`, `i = 1 − n`, base attributes `A[idx] = R[idx]` (getter
`0x1442dd650` → `0x1441172b0`), effective attributes `B[idx] = R[0x3d+idx]` (getter `0x1442dd5b0` →
`0x1442bfa70`), raw in-possession bits `S_in` (`R+0xCC`), out-of-possession `S_out` (`R+0xD0`), COM
flags (`R+0xD4`), cards (`R+0xC0`), role code `playerRef+0x18`:

```
P0 +0x08 = [S_in ∈ {0 DLF, 5 Creative Playmaker, 9 Classic No.10, 10 Hole Player, 12 Anchor Man, 13 Orchestrator} or S_out bit 8 The Destroyer]
           ? 0.5·n(Finishing 0x1a, 75,85) + 0.1·i(Speed 0x28, 65,85) + 0.4·n(TightPossession 0x19, 75,85) : 0
P1 +0x0c = 0.3·n(Acceleration 0x2c, 75,85) + 0.2·n(Acceleration − Speed, 0,8) + 0.4·n(BallControl 0x18, 75,85) + 0.1·n(TightPossession, 75,85)
P2 +0x10 = 0.25·n(LoftedPass 0x1c, 70,90) + 0.25·n(Heading 0x1d, 70,90) + 0.1·#{cards 0xc One-touch Pass, 0xd Weighted Pass, 0xe Pinpoint Crossing, 0x11 Low Lofted Pass, 0x2b Through Passing}
P3 +0x14 = [role ∈ {7, 9}] ? 0.5·[S_in ∈ {3 Fox in the Box, 9 Classic No.10, 4 Target Man, 0 DLF}] + 0.3·n(PhysicalContact 0x29, 70,90) + 0.2·n(OffensiveAwareness 0x14, 60,80) : 0
P4 +0x18 = max(0, ( 15·(n(A[BallControl],70,90) + n(B[BallControl],70,90)) + 7.5·(n(A[Speed]) + n(B[Speed])) + 7.5·(n(A[Accel]) + n(B[Accel]))
                   + 10·(COM0 Trickster + COM1 Mazing Run + COM2 Speeding Bullet + COM4 Incisive Run) − 10·COM6 Long Ball Expert ) / 100)
P5 +0x1c = 0.7·i(B[0x36], 0,3) + 0.3·i(B[WeakFootAccuracy 0x27], 0,3)
P6 +0x20   never written (0 from the ctor)
P7 +0x24 = 0.6·n(PhysicalContact, 70,90) + 0.3·i(Finishing, 60,80) + 0.1·COM1 — and nothing reads it
```

Validated three times over: 300 random players (max error 9.5e-8), 30 and 40 random worlds × 8
fields (0 mismatches) on both images (`tools/emu_bp_personality.py model p|i N`). No RNG, no indirect
call, no per-match seed; the style tests are the **raw** category bits, not the role-gated oracle
`0x1442e2130`, so position legality is not applied here.

Readers (register-walk over `ctx+0x60` loads and the inline image-ctx copy, helpers mapped back to
units by reverse BFS): [b]

| field | read by |
|---|---|
| `P0` finisher | Dribble helpers, PassSafety, PassForward filter, NoFeint, BodyFake/Burst helper, ImageUnitSafety::vf2, DrawOpen::vf7 |
| `P1` take-on | Dribble helpers, Shoot helpers (`0x1456828a0`, `0x145687b80`), PassCross::vf2, PassForward veto, NoFeint::vf1/vf5, KickFeint::vf7, ImageUnitSafety::vf2, SideChange::vf3 |
| `P2` long/aerial | the **arbiter** (PassBackSpace veto — only under a class-3 fallback with `+0x3a`), PassForward/PassLong/PassSideChange::vf2, PassBackSpace/Expand/Safety/Cross/RespondRequest/Special helpers, KickFeint, ImageUnit Cross::vf1/vf2, Long::vf1, MiddleShot::vf2, PassForward::vf1, PassThrough::vf5, Safety::vf1, SideChange::vf1 — ~30 functions |
| `P3` hold-up | PassSafety, PassForward, PassBackSpace helpers, Dribble helper |
| `P4` dribble propensity | the **arbiter** (same branch), Shoot::vf2 + 5 helpers, PassCross::vf2, PassOneTwo::vf2, DribbleChallenge::vf2 + helpers (incl. the stage-B refractory `0x1456ab116`, Tricksters only), PassSpecial/Forward/Cross/Expand/BackSpace helpers, Burst::vf7/vf9, NoFeint, ImageUnit Cross::vf1/vf2, CurveShot::vf3, Safety::vf2/vf3, SideChange::vf1 |
| `P5` weak-foot handicap | Shoot::vf2 + helpers, PassSideChange::vf2, PassBackSpace/Cross/Expand/Forward/Special helpers, KickFeint, ImageUnitCurveShot::vf2 |

So `Personality` gives **per-player variety, deterministically, from data the companion app already
writes** — and it is gated hard: a striker without one of the listed styles has `P0 = 0` whatever
his Finishing, and `P3` is 0 off roles 7/9. `P6`/`P7` are dead.

## Intention — the situation class, and who reads it

`match::ai::bp::Intention` (`vft 0x147723db0`, 0x10 bytes at `BP+0x4220`, ctor `0x145662a80` sets
`+8 = 1`). `0x145662ed0` (601 instructions) recomputes a class **0..4** every tick from ball position
relative to the goal and the opponent lines, counter-attack state (`team+0x9d4` predicates
`0x1456747a0`/`0x1456746c0`/`0x145674e70`), possession time (`0x1442eb950` against `fps·3`), two raw
style reads (Creative Playmaker / Classic No.10 → class 2), with class 4 handled by `0x145662aa0`
and class 3 sticky through `0x145662c90`; the class is written only at `0x145663479` (`mov [rax+8],
edi`, `edi ∈ {0,1,2,3,4}`). Geometry thresholds are not decoded. [b]

**The class is a live input, not a latch.** DECIDE stores `lea r11,[r14+0x4220]` into the stack
args and `0x14566be60` copies it to `ctx+0x40` (the chapter's own ctx table); the Image loop's ctx
carries it at `+0x30`. A sweep of every chained-unwind function in the band (595 roots,
`0x145640000..0x1456d0000`) for `mov rcx,[reg+0x40|0x30]` feeding `call 0x143b85440` finds the
getter at **~60 sites in ~30 carrier functions**, most followed by a compare against 1–4 that
gates a branch. An earlier version of this chapter said "no ThinkUnit, ImageUnit, DribbleImage, the
arbiter, PRE-PASS or DECIDE reads it" and called it dead; that scan missed the register-indirect
getter and the claim is withdrawn (§ Corrections). Readers, with the compares [b]:

| reader | sites (`cmp eax, N` after the getter) |
|---|---|
| ThinkUnitPassForward::vf2 `0x14569d240` | `0x14569d6a0` == 1, `0x14569d6ae` == 2 — the lofted second search needs class 1 or 2 |
| ThinkUnitPassOneTwo::vf2 `0x14569e1d0` | `0x14569e234` ≥ 3 → exit; `0x14569e33a` 4; `0x14569e4a6` 2; `0x14569e5bc/5ca/5d8` 3/4/2 |
| ThinkUnitPassSafety::vf2 `0x14569ed80` | `0x14569efa5` > 2 → exit |
| ThinkUnitFeint::vf2 `0x1456a25e0` (never listed) | `0x1456a263b` 3, `0x1456a266f` 4 |
| ThinkUnitDribble::vf2 `0x1456a6f70` | `0x1456a724c` == 1 |
| pass preamble `0x145699510` | `0x1456996e6`, `0x1456996f7` 4, `0x145699a28` 2, `0x145699a36` 3 |
| PassForward filter `0x145690200` | `0x145690377`, `0x1456906da`, `0x1456909a9`, `0x1456909b6` 1, `0x145690a22` |
| PassForward veto `0x145696cd0` | 6 sites: `0x145696eda` 4, `0x145696fe6` 4, `0x145697058` 2, `0x1456971f9` 1, … |
| pass helpers `0x145691c10` (7), `0x1456917a0` (4), `0x14569a690` (2), `0x145699cd0` (2), `0x14568b740` (9), `0x14568c4d0` (5), `0x145688f10`, `0x14566c3d0` | classes 1–4 throughout |
| dribble helpers `0x1456a9910` (9 sites), `0x1456a55e0` (3), `0x1456a6450` (`0x1456a653e` 4), `0x1456a68c0` (1), `0x1456a6b10` (1), `0x1456a3ad0`, `0x1456a2da0` | classes 1–4 |
| ImageUnit canStart/vf1 bodies via the image ctx `+0x30`: MiddleShot `0x145678d18`, `0x145678fa4` (== 2 → +40 outright; ≠ 2 → +40 / +70 / +0 by `team+0xb44d` and `team+0x204`); CurveShot `0x145678733` 3; Long `0x14567b6fc` 3, `0x14567b70e` 4; PassThrough `0x14567c7f0/0x14567c820`; Expand/BackDFLine/SideChange helpers `0x14567a880` (4/3/2), `0x14567aa50`, `0x14567d0e0`, `0x14567d270`, `0x14567da80` 1, `0x14567e090`, `0x14567f230`, `0x14567fa60`, `0x145677ae0` (Safety::vf1) | |
| the delay filter `0x145653450` (`0x14565350e`, `0x14565362c`: class 0 halves the dribble delay), the super-cancel decision `0x145652960`, PRE-PASS `0x145653b90`, the Image loop `0x14566aa10` (list switch), the list builder `0x14566b7f0` | |

So the class drives the Image list, a delay halving, PassOneTwo's and PassSafety's entry, the
lofted second pass in PassForward, and dozens of inner branches in the pass and dribble helpers.
The Intention byte-flags at `+0x311/+0x312/+0x325` and the vector at `+0x320` are read by
PassOneTwo, PassExpand, PassForward and Dribble. What each threshold *means* for play is not
decoded beyond the entries above. [b]

### Where the possession random `r` is consumed

`r = BP+0x14` (§ Layout) is not only the seed of the four plan rolls. It is passed to every unit as
`*ctx[0x50]` and compared as a threshold — usually against a level fraction `ctx[0x58]->+N` or a
Personality float — inside: [b, every site re-read]

- **Shoot** `0x145685da1`, `0x145685ffc`, `0x145686067`, `0x1456863b6`, `0x1456866d7`,
  `0x145686799`, `0x1456867e8` (the row-0x20 shot branch, the carry test `P4 > 0.3·r`, …);
- **PassForward** `0x14569d461..0x14569d471` (`comiss r,[levelParams+4]; ja` → loses the fast path);
- **PassOneTwo** `0x14569e293`, `0x14569e314`, `0x14569e39d`, `0x14569e60c`;
- **Dribble** `0x1456a73d8`, `0x1456a753c` (`*ctx50 ≤ *ctx58` for the "move to heading" branch);
- **PassSafety** `0x14569edb9`, `0x14569ee44`; **PassLong** `0x14569e129`;
- **PassSpecial body** `0x14569fc77..0x14569fc87` (`r > levelParams[1]` → bail) and five more sites;
- the **arbiter** `0x145650eb9` (PassBackSpace veto branch);
- `Safety::canStart` (`r > clamp((level−1)·0.5, 0, 1)`), `0x145658a03`.

Every one of these makes the unit-level pass/shoot/dribble answer a function of `(state, frame, r)`,
and `r` is re-latched every possession spell. Two spells with identical geometry can therefore
produce different answers — not just different plans. The earlier statement "randomness never enters
the pass/shoot/dribble choice itself" was wrong (§ Corrections).

## What the carrier reads — the input census

Module = every function reachable by direct call from the 242 non-stub `bp` vtable methods plus the
entry points, expanding inside `0x145650000..0x1456cb000` (519 in-band functions, 291–396
out-of-band helpers to depth 2); every accessor call site enumerated with its constant argument
recovered by a backward register walk. [b unless marked]

**Ability arrays.** The record `R` holds three parallel byte arrays: `A` at `R+0` (what `ATTR_get
0x143ea8cb0` and the kick model read), `B` at `R+0x3d`, `C` at `R+0x7a`. All three are written by one
setter `0x1442c0060(R, idx, A, B, C)` from the record builder `0x1454406a0`, which reads the same DB
parameter through two accessors (`0x144a2a300` → A, `0x144a0d7c0` → B, both clamped by
`0x1442bfae0`) and derives `C = 0x144a509d0(…) − B` (setting `R+0xea` when any `C ≠ 0`); the simple
setter `0x1442c0090` writes `A = B`. **The carrier reads `B` more often than `A`** (88 vs 65 sites);
`C` never. Which of A/B is the progressed/current value and whether condition is applied in place is
not established [c]. `ATTR_get 0x143ea8cb0` has **zero** call sites in the carrier band.

Index names (`DATA_PARAMETER` enum + 7, registrar emulated by `tools/emu_enum_names.py`; the three
non-40..99 anchors `0x27 [0,3]`, `0x2f [0,7]`, `0x30 [0,2]` line up under +7 and not under the older
"+0x15" rule): `0x14 OFFENSE_DECISION, 0x15 DEFENSE_DECISION, 0x16 GK_DECISION, 0x17 DRIBBLE,
0x18 TRAP (Ball Control), 0x19 BALL_TOUCH (Tight Possession), 0x1a SHOT, 0x1b SHORT_PASS, 0x1c LONG_PASS,
0x1d HEADING, 0x1e INTERCEPT, 0x1f AGGRESSIVENESS, 0x20 CONSCIOUS_DEFENSE, 0x21 PLACE_KICKING,
0x22 BALL_SPIN_CONTROL (Curl), 0x23..0x26 GK, 0x27 R_FOOT_ACC (0..3), 0x28 SPEED, 0x29 BODY_BALANCE
(Physical Contact), 0x2a BODY_CONTROL (Balance), 0x2b KICK_POWER, 0x2c AGILITY (Acceleration),
0x2d JUMP, 0x2e STAMINA, 0x2f STABILITY, 0x30 DURABILITY, 0x32 height, 0x35 stronger foot, 0x36 (0..3,
unnamed)`. [a] Most-read in the carrier: `B[BallControl]` 13 sites, `B/A[Height]` 12/10,
`B[TightPossession]` 11, `A/B[Speed]` 10/9, `B[WeakFootAcc]` 9, `B[LowPass]` 9, `B[Finishing]` 9.
**Never read anywhere in the closure:** Dribbling `0x17`, Defensive Awareness, GK Awareness,
Aggression, Defensive Engagement, the four GK abilities, Stamina, Form/Condition, Injury Resistance,
Age, Weight.

**Playing styles.** 55 in-possession + 2 out-of-possession reads. Only **two** categories are ever
queried through the role-gated gate `0x1442e2130` inside the carrier's own code — Extra Frontman
(15) in CBOverlap/Cross/None — plus Defensive Full-back (17) via `0x1442e21c0` in the preamble,
Cross Specialist (8) in the PassCross helper `0x145695d40` (`0x14569677b`; sole caller
`PassCross::vf2 0x14569b540` — the chained extent of the receiver predicate `0x145695690` ends at
`0x145695d40`, so this read is *not* in the predicate) and Classic No.10 (9) in PassForward, the
dribble helper `0x1456ab580` and GKPassShort/SetPlay through `0x143e31a10`. Every other style read is the
**raw un-role-gated bit** (`0x1442bfdf0` / `0x1442bfdb0`) — so the off-ball rule "play a man off his
slot and his style stops firing" does **not** apply to most on-ball style effects. The style→category
tables: catalogue index → internal id `0x1471bc0c0`, id → `{offCat, defCat}` `0x14825b2f4`.

**COM/AI playing-style flags** (`R+0xD4`, 7 bits). The builder `0x145440e10` fills them from the
7-entry `{bit, dbKey}` table at `0x14825cba0` = `(0,63)(1,65)(2,64)(3,68)(4,66)(5,69)(6,67)`; DB key =
`DATA_PARAMETER` enum + 1 (cross-checked on `PLAYSTYLE 0x3c / PLAYSTYLE2 0x3d` ↔ keys `0x3d/0x3e`):
**bit 0 PS_FEINT_STAR (Trickster), 1 PS_DARTING_RUN (Mazing Run), 2 PS_QUICK_STAR (Speeding Bullet),
3 PS_EARLY_CROSSER (Early Cross), 4 PS_INSIDE_CUTTER (Incisive Run), 5 PS_MIDDLE_SHOOTER (Long
Ranger), 6 PS_LONG_PASSER (Long Ball Expert)** [a for the table and enum names; English names are
the community mapping, c, but the read sites confirm them: bit 3 → +30 on the *cross* roll, bit 6 →
+50 on the *long-ball* roll, bit 5 → the *middle-shot* base]. 30 carrier functions read them
(`0x1442bfda0` = `bt [R+0xD4], idx`; wrappers `0x1442e0420`, `0x143e31970`).

**Skill cards** (`R+0xC0`, 73 bits). The writer `0x145440380` loops 72 `{bit, skillIndex}` entries at
`0x14825cc00`, maps skillIndex → DB key through `0x1471bc6e0` and sets `bit = (DB value == 1)` via
`0x1442c0160`; enum + 1 names every bit: `0 SCISSORS, 1 ELASTICO, 2 MARSEILLE, 3 CHAPEAU, 4 QUICK_TOUCH,
5 PIVOT_FOOT_TOUCH, 6 HEADER, 7 CONTROL_CURVE, 8 NON_ROTATING_SHOT (Knuckle), 9 ACROBATIC_SHOT,
0xa HEEL_TRICK, 0xb ONE_TOUCH_SHOT, 0xc DIRECT_PASS (One-touch Pass), 0xd BACK_SPIN_LOB (Weighted
Pass), 0xe PIN_POINT_CROSS, 0xf OUT_SIDE_LONG (Outside Curler), 0x10 RABONA, 0x11 LOW_LOB (Low Lofted
Pass), 0x12 LOW_PUNT_KICK, 0x13 LONGTHROW, 0x14 GK_LONGTHROW, 0x15 MALICIA, 0x16 MAN_MARK,
0x17 CHASING, 0x18 ACROBATIC_CLEAR, 0x19 CAPTAINCY, 0x1a SUPERSUB, 0x1b COMBATIVE_SPIRIT,
0x1c NO_LOOK_PASS, 0x1d PK_KICKER, 0x1e PK_STOPPER, 0x1f CONTROL_LOOP_SHOT (Chip), 0x20 SOLE_CONTROL,
0x21 DROP_SHOT (Dipping), 0x22 RISING_SHOT, 0x23 HIGH_PUNT_KICK, 0x24 INTERCEPT, 0x25 BLOCKER,
0x26 AIR_BATTLE, 0x27 SLIDING, 0x28 DOUBLE_TOUCH, 0x29 EDGE_TURN, 0x2a MIDDLE_SHOT (Long-range
Shooting), 0x2b THROUGH_PASS, 0x2c IMPROVISER, 0x2d unassigned, 0x2e FORTRESS, 0x2f MOMENTUM_DRIBBLING,
0x30 GAME_CHANGING_PASS, 0x31 VISIONARY_PASS, 0x32 BLITZ_CROSSING, 0x33 BLITZ_CURLER,
0x34 PHENOMENAL_PASS, 0x35 BULLET_HEADER, 0x36 DF_SKY_HIGH, 0x37 ACCEL_BURST, 0x38 PHYSICAL_TACKLE,
0x39 GK_COACHING, 0x3a LOW_IMPACT_SHOT, 0x3b AGGRESSIVE_SHOOTER, 0x3c GK_ALERT,
0x3d BREAKTHROUGH_DRIBBLE, 0x3e MAESTRO_SIGNAL, 0x3f SHADOW_GUARDIAN, 0x40 BREAK_SPRINT,
0x41 QUICK_IMPACT, 0x42 TAP_FAKE, 0x43 SPRING_CUT, 0x44 POWER_TACKLE, 0x45 GK_RUSH_OUT,
0x46 GK_AERIAL_CLAIM, 0x47 BEAST_DRIVE, 0x48 DECISIVE_PASS`. [a for the tables; names via enum+1, b,
validated by semantics at the read sites]. **68 card reads in ~35 carrier functions** (the 73-bit test
`0x1442c0000` / wrapper `0x143e31b10`) — the standing "all 287 card sites are in
`match::anime::action`" census is wrong for this subsystem.

**Team tactics and other per-match team fields.** The carrier never calls the off-ball quota
reader `0x1442f9a90` (0 callers in the closure); it compares the **attack level** dword
`team+0xb450` directly at six sites: CBOverlap::canStart `0x145676b42` (≥ 2), Shoot::vf2
`0x145686696` (> 2), the preamble `0x145699a12` and the PassSafety helper `0x1456926c0` (≥ 3),
dribble-challenge helpers `0x1456a8e56` / `0x1456a9c6d` (> 2). `+0xb454` (AUTO) is never read. But
the attack level is **not** the only per-match team input — an earlier version of this chapter said
so and was wrong (§ Corrections). A per-function sweep of the band (chained-unwind extents) finds
five more team-object fields read as decision inputs, none of them named and none with a located
writer [b, every site re-read]:

| field | sites | what it does |
|---|---|---|
| `team+0xb3c4` (dword) | 8 sites in 7 fns: Cross::canStart `0x14567b586` (≠ 0 → accept outright), Long::canStart `0x14567b8f6` (≠ 0 → score := 100), Safety::canStart `0x1456770eb` (≠ 0 → plan disabled), `0x14568db11/0x14568dc40` (pass helper `0x14568c4d0`), `0x1456aa192` (dribble helper `0x1456a9910`), `0x1456c784e` / `0x1456c7c32` (Humiliating) | **forces cross and long-ball plans and kills the Safety plan** — the largest single on-ball lever found; sits next to the attack-level block, so a team-instruction toggle is the likely identity |
| `team+0xb44d` (byte) | 10 sites in 8 fns: Cross `0x14567b286` (≠ 0 → skip score **and** roll) and `0x14567b594` (post-roll accept), MiddleShot `0x145678fae` (set → +40 regardless of `team+0x204`; clear, with Intention ≠ 2 → +70 if `team+0x204 == 3`, else **+0**), CurveShot `0x145678780/0x145678ae6`, Long `0x14567b8a5`, EarlyCross `0x14569ce38`, `0x145655b8b`, `0x14568fabe`, `0x14569546c` | bypasses the cross roll; guarantees MiddleShot's +40 (clear → +70 or +0 by `team+0x204`) |
| `team+0xb3bd` (byte) | 4 sites in 2 fns: `0x145659209`, `0x14565aaee/0x14565ab6f/0x14565abb6` (pre-decide helpers `0x1456590d0` / `0x145659c20`) | not decoded |
| `team+0x204` (dword) | `cmp dword` at 7 sites in 5 bp fns (`0x145652960`, Lilux::shouldEnd `0x145676830`, Lilux::vf1 `0x145677a70`, MiddleShot `0x145678fb8` (== 3), PassForward filter `0x145690200` ×3); 14 sites in 12 fns across the wider band | already known to gate Lilux (≤ 0) and Lilux's duration; also the MiddleShot +70 and three PassForward-filter branches |
| `team+0xb4c` / `+0xb50` (dwords, via `ctx+0x28`) | Cross post-roll `0x14567b5c1..0x14567b5fc` (`+0xb50 <= 0 ∧ +0xb4c != 0` → accept; `input+0x1c > f ∧ +0xb4c != 3` → accept; both are any-of accept tests, not requirements), MiddleShot `0x145678bb8/0x145678d26`, `0x1456841c0` (`+0xb50 == 1`), `0x145684c9d`, `0x1456938aa/0x145693b9f`, preamble `0x145699bca` (`+0xb50 == 2`), `0x14568ce28`, `0x145678576`, `0x145679208`, `0x14567bf7b` | not decoded; small-enum compares (0/1/2/3) |

Route for all of these: **per-match team field, name unknown, writer not located.** Identify
`team+0xb3c4` before touching anything else in this table.

**CPU difficulty** is a strong input, unlike the shape layer: 3 `GetParam` sites (rows `0x17/0x18/0x19`
delays, `0x1a` dribble refractory, `0x1b..0x1e` fractions), 5 nonzero-row gates (`0x20`, `0x21` shot
branches; `0x2a` set-play; `0x27..0x29` unit enables), 17 level compares (the preamble returns false
below Regular — which withholds the pass flag `+0x24` at four callers and **kills PassOneTwo
outright** (its only class-2 write `0x14569e6fa` is behind the preamble, `0x14569e5a8 je 0x14569e716`) — and branches at
Top Player/Superstar/Legend; the PassSpecial body bails below Professional (`0x14569fc6a`, verified)
and when `r > levelParams[1]`; the shortlist ×1.2 at Legend; DribbleChallenge counts differently
below Regular and at Superstar+ online) and 14 raw-level ramps (`ImageUnitSafety::vf2`,
PassThrough/PassForward/Expand::vf1, DoubleTouch::vf7, eight shot/pass helpers convert the level to
a float clamped between two constants). The CPU on Superstar decides faster [a] and unlocks more
branches [b]; whether the 14 ramps make it *score higher* was not read — neither the ramp direction
nor what the clamped float multiplies was examined for any of the 14 [c]. The dribble refractory is
**not** a difficulty input (it subtracts `P4`, § dribble moves).

**dt270: none.** No field of any of the 105 located dt270 objects has a reader in the closure or its
helpers to depth 3; the ConstantManager get `0x145348d70`, wrapper `0x145349560` and global
`0x148c22b98` are never referenced (the 140 unlocated objects are tutorial/demo/PathToGlory/ballPerson
data). The carrier brain is driven by exe constants, player data and difficulty rows. [b, exhaustive]

## The owner's questions, answered

Each answer is marked **answered**, **partly** (with what is missing and where it is tracked) or
**not**.

**How does the AI make decisions when it has the ball?** — **answered** for the loop, **partly**
for the targets. Plan first, then a fixed priority list. The Image layer picks a plan by walking a
situation-keyed list and taking the first `canStart` that says yes (four of them roll a percentage
built from cards, COM flags and one attribute against a threshold fixed for the possession — and
then still have to pass a post-roll chain). The plan fixes the order in which the ThinkUnits are
asked; every listed unit thinks into a table; the first one in list order with a *delay-accepted*
answer wins. `Force` and `PassRespondRequest` always come first, `Shoot` beats every pass wherever
listed, `PassDirectHighBall` is always last. Dribbling is the floor, evaluated before the list and
used when nothing else answers — or when Shoot answers "carry" (class `0xa`). Before any of this,
`byte[entity+0x41]` can divert the carrier to a move-only output that skips the loop (bar the
PassBackSpace re-run on `0x145651100`'s common tail).
*Who to pass to* is decoded for **PassForward's first pass only**: not an argmax but "the last
candidate in plan order whose score beats the first eligible candidate's", with a role-legal
Classic No.10 winning outright, and a lofted second search when nobody qualifies. Missing: who
fills the route table the units rank by (open 1); the Image `vf1` target choice that fills
`plan+0x9c` and therefore the candidate *order* the quirk depends on (open 11, 18); the target choice
of Cross / Long / Safety / SideChange / Expand / DirectHighBall / EarlyCross / BackSpace / OneTwo /
RespondRequest (open 4, 19); and what the receiver-style tag `+0x25` does (open 15).

**What makes it shoot from distance?** — **partly.** `ThinkUnitShoot` can fire under **any** held
plan (the image test at `0x145685c88` only sets a sub-flag); the MiddleShot/CurveShot images change
how often the *plan* says "long shot" (bases 60/50/40 and 35, both capped at 90 → max 91 %), and
the level rows `0x20/0x21` unlock two shot branches, one of them `r`- and `P4`-thresholded. Missing:
the shot acceptance `0x1456838c0` and the aim point (open 4); MiddleShot/CurveShot full formulas
(open 11, read but not emulated).

**Can I make one player take more risks than another?** — **partly.** Yes through `Personality`
(data-driven, per player, deterministic; P0 needs one of six styles, P3 needs role 7/9, P4 is the
dribble-propensity that also shortens a Trickster's feint chaining) and through the four rolling
images' card/COM inputs. Missing: what each Personality threshold changes *inside* a unit beyond the
arbiter, PassForward, Shoot and the refractory (open 9) — so "risk" maps to "style bit → P0 ≠ 0",
"Trickster → shorter refractory", "Pinpoint/Early Cross → cross plan" and little more today.

**Does difficulty change passing?** — **partly, and one earlier reading was inverted.** Verified
levers: the reaction delays (a: 60/40/22/12/8/6/2 ticks for a pass), the unit enables (rows
`0x27..0x29`: PassBackSpace off below Regular), the shot-branch rows `0x20/0x21`, the PassSpecial
body's bail below Professional (`0x14569fc6a`), the Legend ×1.2 on trick weights, and `r`-vs-level-
fraction thresholds inside PassForward/PassSafety/PassSpecial. The preamble "rejects below
Regular" **only at PassOneTwo** — its sole class-2 write `0x14569e6fa` sits behind the preamble's
true branch, so Beginner/Amateur CPUs never play a one-two; at the other four callers it only
withholds the pass flag `+0x24`, whose effect is untraced, as is `+0x25` (open 15). The 14 level ramps' direction is unread (c).

**Why does the CPU keep playing the same ball?** — **answered, with the `r` caveat.** Plans are
held across frames, a finished plan is on cooldown, a decided shot/pass/clear is sticky until it
executes, and the plan rolls use a threshold fixed for the possession spell — so the same shape on
the same frame gives the same ball. A *different* spell re-latches `r`, which is also a threshold
inside eight decision functions, so identical geometry can produce a different answer next spell.

**Is it as deterministic as off-ball movement?** — **answered: almost, and differently.** No
ThinkUnit reaches the LCG except the dead `PassRandomTest` and `DribbleChallenge`'s shortlist roll;
the think bodies contain no virtual dispatch (0 indirect calls in all 26 `vf2` bodies except
DribbleChallenge's 5 DribbleImage dispatches); a whole-image reverse closure from the LCG (793
functions, 162 vtable methods) touches exactly 9 in `match::ai::bp`, and a callback-augmented
closure adds only `0x145674ec0` (attribute-seeded, fixed per player). The *plan* and the *skill
move* are rolled — but every live draw is the **first output of a freshly seeded local LCG** whose
seed is the frame counter, the match tick word, the per-possession `r` or an attribute byte. There
is **no free-running RNG stream in the live carrier brain**: the same shape on the same frame always
gives the same ball, the same shape on a different frame or a different possession spell can roll
differently, and replays are exact. The unit-level choice is deterministic **given `r`** (§ Intention
and randomness lists every site that consumes it). Closure method: direct calls over merged `.pdata`
(253,886 ranges) plus taken function pointers, depth 12–14; positive controls (kick builder depth 2,
kick randomiser depth 1) reached, negative controls (ChanceSpaceRun 210 fns, DiagonalRun 286 fns)
explored and not reached.

**Does `Personality` give per-player variety?** — **answered: yes** — real, per player, data-driven
and gated. Six of its eight floats are read by 60+ carrier functions including the arbiter (on one
branch); the inputs are attributes (A and B arrays), the two style indices, five cards, seven COM
flags and the formation role, all of which the app already writes. There is no random or per-match
term in it.

**Does `ThinkUnitPassRandomTest` mean the carrier consumes randomness?** — **answered: no.** It is
live code with the subsystem's only persistent RNG stream, and it is never consulted: kind `0x17` is
pushed by no list builder, `vf2` has no direct caller, and the dispatcher is the sole `vf2` entry.
Reviving it needs one push site.

**Do the two brains talk?** — **partly.** From the carrier side, no `match::ai::bp` function reads
the off-ball action ids at `teamAI+0x8f4c`. The five `0x8f4c` reads below `0x1456d0000` all lie in
`0x145644700` (tests `0x1d/0x1e/0x1f` SpaceRun ids and `0x26 CENTERING_GET`), which is in the
*band* but not in the bp module; its callers are three sites in `0x145648f30`, reached from
`0x145625170` ← `0x14561fe20` (a function in **no vtable** of `build/exe_map.json`; an earlier
version called it "the shared vf2 of every `match::player::Action*` kick executor" — that identity is
**c** at best) and from `0x1441aecd0` ← `0x1441af000`, which has **no direct caller** and a single
tail-jump entry at `0x144249dbf` (in a function without a `.pdata` chain root) — an unresolved
indirect entry that could be the route-table filler the pass units rank by (open 1). So: the
**decision** never reads the runner ids; whether the **route table** they rank by does is open.
(ii) `PassForward`'s "flag 9" override is a style-legal-for-role test, not a run-state read. (iii)
The one channel into the carrier from elsewhere is the request matrix at `match+0x24114` read by
`PassRespondRequest`, whose writer was not found — it may be the human "call for pass", an off-ball
selector, or the keeper. (iv) No off-ball selector reads the carrier's published plan. So the
off-ball chapter's "the two brains never talk" stands **for the bp decision**, with the route table
and the request path as the open caveats. [b for the sites; c for the executor identity; an earlier
version of this chapter claimed the opposite from mis-attributed site addresses — § Corrections]

**Which of this is tunable, and by what route?** See the table — and read its first two rows about
what is *not* safely tunable before anything else.

## Tunables

Pool-cell sharer counts are from `build/exe_constant_census.json`; "re-aim" means repoint the
instruction's `disp32` at a private cell — **never write a shared cell in place**, whatever its
count. Two immediates in this subsystem look like levers and are not; they come first.

| what | site | route | effect | evidence | sharers |
|---|---|---|---|---|---|
| **NOT SAFELY TUNABLE — the plan-roll range immediates** | Cross `0x14567b504 mov esi,0x64`; MiddleShot `0x1456790f9`, CurveShot `0x145678acb`, Long `0x14567ba6c` `mov edx,0x64`; MiddleShot's cap `0x1456790c7 mov eax,0x5a` | — | the value is also the **RNG stream index** (`lea r8d,[rdx-0x62]`, and for Cross `lea edx,[rsi-0x62]` for the seeder too; MiddleShot's cap feeds `lea edx,[rax-0x58]`): the local RNG state is four u32s on the stack, so any range outside 98..101 (cap outside 88..91) **writes outside the state**, and 99 silently switches the draw to stream 1. To change a draw range, re-write the tail in a cave (seed on stream 2, `RandInt(N, 2)`) and leave the immediates alone | b | — |
| **shared pool cells listed below** (0.35, 60.0, 90.0, 5.0, 3.0, the Personality windows, …) | as listed | **re-aim only** | every cell in this table with a sharer count is shared with unrelated code (the 0.35 cell's other 86 referrers include seven more bp sites plus `ActionDelay` — the census's default 15-row listing hides them, use `--all`); writing one in place changes those sites | census | as listed |
| force cross / long-ball plans, disable Safety | `team+0xb3c4` (Cross `0x14567b586`, Long `0x14567b8f6`, Safety `0x1456770eb`), `team+0xb44d` (Cross `0x14567b286`) | per-match team field (name unknown, writer not located) | `+0xb3c4 ≠ 0` accepts every cross plan outright, forces the long-ball score to 100 and disables the Safety plan; `+0xb44d ≠ 0` skips the cross score and roll — identify these before tuning any plan immediates | b | — |
| CPU on-ball priority per held Image and state | `0x14566b980` (jump table `0x14566bd0c`; e.g. `0x14566ba41` pushes 0 Shoot, `0x14566ba4e` pushes 0xb PassForward) and `0x14566b7f0` | exe-code | swapping two pushes swaps the CPU's choice when both are viable (PassForward before Shoot → lay-offs instead of shots); removing a push removes that option for that plan | a | immediates |
| CPU reaction time on the ball | `0x146c06f40 + row*0x2c + 4 + col*4`, rows `0x17` pass/clear, `0x18` dribble, `0x19` dribble move; cols 0,1,2,3,4,6,8 = Beginner..Legend; consumer `0x1456526a0` | exe-constant | stock Superstar pass delay 6 ticks, Legend 2, Beginner 60; raising c6/c8 makes the CPU dwell and get closed down — and, because a waiting answer is absent from the table, hands the arbitration to lower-priority units with shorter delays | a | table cells, private to GetParam (single `lea` at `0x1442e491a`; the online table `0x146c067b0` has its own at `0x1442e4910`) |
| unit enables by level | rows `0x27` PassBackSpace, `0x28` PassSafety, `0x29` Feint (step rows) read by `0x1442e4c00` in `0x145654820`; rows `0x20/0x21` Shoot branches, `0x2a` SetPlay | exe-constant | PassBackSpace is off below Regular in stock; `0x29` is inert (Feint never listed) | b (rows), a (values) | table cells |
| difficulty fractions | rows `0x1b..0x1e` → `BP+0x699c..` (consumer inside the units untraced) | exe-constant | 0..1 factors handed to every unit | b | table cells |
| Cross plan frequency | `0x14567b44e add ebx,0x1e` (+30 Early Cross / Cross Specialist); `0x14567b462 add ebx,0x28` (+40 Pinpoint Crossing). **Not** `0x14567b504 mov esi,0x64` — see the first row: `esi` is the cap, the RandInt range **and** the stream index (`esi−0x62`), so it must stay 100 | exe-code | how readily the CPU passes the cross **roll** — the post-roll **any-of** chain (designated target / `0x143e30e10` / `team+0xb3c4` / `team+0xb44d` / Pinpoint / `+0xb50 <= 0 ∧ +0xb4c != 0` / `input+0x1c > f ∧ +0xb4c != 3` / pass-work `+0x34`, `+0x30` **above** their tick windows / Early Cross / `byte[team+2]`; any one firing jumps to accept `0x14567b664`, reject only on full fall-through) must still fire at least once | a (roll segment), b (chain) | immediates |
| Cross attribute mapping 10 + 50·(Heading−60)/30 | `0x14567b3d9` (60.0 @`0x145a8dd84`), `0x14567b3f9` (90.0 @`0x145b52b90`), `0x14567b40f` (30.0 @`0x145a8dd80`), `0x14567b417` (50.0 @`0x145ae7580`), `0x14567b427` (10.0 @`0x145a8dd7c`) | exe-code (re-aim) | spread of cross-eagerness across the rating ladder (today ≤60 → 6, ≥90 → 36) | a | 1512 / 1535 / 1078 / 503 / 1832 |
| Cross situational factors 0.6 / 0.8 / 1.2 | `0x14567b48d` (`0x147850258`), `0x14567b49c` (`0x145b2a694`), `0x14567b469` (`0x145c7e410`) | exe-code (re-aim) | discount on a cross without a designated target | a | 438 / 622 / 237 |
| MiddleShot / CurveShot / Long bases and bonuses | `0x145678f17 mov ebx,0x3c` (60 Long Ranger), `0x145678f39` (50 Long-range card), `0x145678f58/f77/f94` (40 Knuckle/Dipping/Rising), `0x145678fc7` (+40 when Intention == 2 **or** `team+0xb44d != 0`) / `0x145678fc2` (+70 when Intention ≠ 2, `team+0xb44d == 0`, `team+0x204 == 3`) / **+0** when Intention ≠ 2, `+0xb44d == 0`, `+0x204 != 3` (`0x145678fc0 jne 0x145678fca`), `0x145678956` (35 Incisive Run), `0x14567b960/b974/b988 add ebx,0x32` (+50 Long Ball Expert / Weighted / Low Lofted), `0x14567b8cf/b8ee` (+10) | exe-code | how often the CPU tries long shots, curlers and long balls (score vs RandInt 0..99). Caps: Cross 100, **MiddleShot 90 and CurveShot 90 (with a floor) → max 91 %, 100 is unreachable**; Long has no cap but `team+0xb3c4` forces 100. The `0x5a` cap in MiddleShot is itself a stream index (first row) | b | immediates |
| Image cooldown (54 ticks) and every seconds→frames scale in the layer | runtime globals `0x148c22ac0` / `0x148c22abc` via `0x14533eb20` / `0x14533ea80` | exe-code (hook the getter or patch the site) | how soon an abandoned plan can be retaken; ShotShort exempt | a (mechanism), c (value) | platform-class companions, used across the AI |
| per-possession roll seed | `BP+0x14` refresh `0x145653e56..0x145653e62`; multipliers ×1500 Cross `0x14567b4fc` (cell `0x146401b78`), ×1200 MiddleShot `0x1456790bf` (`0x145bd7fc4`), ×1300 CurveShot `0x145678a99` (`0x146b9b29c`), ×1600 Long `0x14567ba3a` (`0x1466c54f0`) | exe-code (re-aim only for the four cells) | re-seeding per frame would make plans flicker; per player would make carriers differ on the same frame; each image's draw is fixed for the spell but the four images do not share a draw | b | 5 (the other 4 are GK animation + non-gameplay) / 11 / 2 / 28 |
| per-frame aim perturbation | `0x145668ec0`, seed at `0x14566901d` = `[match+0x3318]`; cells 2.5/16/3/4/5/2/−10 | exe-code | the only per-frame variation in the carrier; a per-player seed (entity ⊕ frame>>6, as the off-ball cave does) would decorrelate carriers | b | not censused |
| Shoot's "carry instead" (class `0xa`) | branch `0x1456866f6 cmp byte [r15+0x78],0` in `ThinkUnitShoot::vf2` | exe-code | nop-ing the class-0xa write lets pass units compete when the striker is in range but not yet shooting (more lay-offs) | b | — |
| Shoot lock timer 5 s | 5.0 @`0x145a8dd78` at `0x1456855a1` | exe-constant (re-aim) | — | b | 1885 |
| arbiter no-kick window after sub-state 0xd | 3.0 @`0x1478504e8` at `0x145650d3c` | exe-constant (re-aim) | — | a | 1761 |
| dribble commit window 0.35 s | `0x145c7ec6c` at `0x1456a720e` | exe-code (**re-aim the disp32**; the cell is shared) | how recent a closing defender must be for the carrier to keep the pre-planned dribble | b | 87 — the other 86 include **seven more `match::ai::bp` sites** (ThinkUnitDribble helpers `0x1456a27cf` / `0x1456a34cc`, DribbleImageNoFeint `0x1456b551f` / `0x1456b6261`, DribbleImageBodyFake `0x1456bdcbf` / `0x1456be10e`, DribbleImageTrapThrough `0x1456c84cb`), the bp-region helper `0x14568c68a`, `match::player::ActionDelay` `0x14563839d` and ~77 unrelated readers (anime, camera, Analyze, …) — `exe_census.py cell 0x145c7ec6c --all`; never write in place |
| PassForward receiver weights 0.8/0.3/0.5, 10 m offset, 15 m span | `0x145689570` reads 0.8 @`0x145b2a694`, 0.3 @`0x145b28a88`, 0.5 @`0x147850248`, 10 @`0x145a8dd7c`, 15 @`0x145c0b000` | exe-constant (re-aim) | more gain weight → the furthest-forward mate more often; the rank term is the only safety input | a | 622 / 895 / 7052 / 1832 / 943 |
| Classic No.10 outright win in PassForward | `jnz 0x14569d391` after `0x143e31a10(match, slot, 9)`; or the receiver's style | exe-code / player-data | a role-legal Classic No.10 is force-fed forward passes; remove the style or nop the branch | b | — |
| receiver-style tag on a forward pass (`rec+0x25`) | receiver predicate `0x145695690` (truth table a-emulated); Player.bin bit 374 | player-data | sets the pass-flag byte `+0x25` on a pass that is **already chosen** — it does not decide who receives; consumer untraced (open 15). The earlier "Target Man never receives a forward pass / only four styles are passed to behind" rows are withdrawn as gameplay claims; a Defensive Full-back carrier likewise only loses the `+0x24` flag | a (table), c (effect) | — |
| PassForward receiver order quirk | the loop `0x14569d393..0x14569d3d1` (`comiss xmm0,xmm6; jbe` with `xmm6` never raised) | exe-code | replacing the compare reference with the running best (`movaps xmm6,xmm0` after `mov ebp,eax` at `0x14569d3af`) would turn "last to beat the first" into a true argmax — today the receiver depends on plan-array order | b | — |
| Extra Frontman → CB overlap plan | `0x1456778c1` (`0x1442e2130` cat 15) + role 1 + attack level ≥ 2 | player-data / per-match-tactic | without the style the plan never enables | b | — |
| attack-level thresholds | `0x145676b42` (2), `0x145686696` (2), `0x145699a12` (3), `0x1456926c0` (3), `0x1456a9c6d` (2) | per-match-tactic / exe-code | ≥ 2 lets CBs overlap; ≥ 3 changes the preamble's branches (which only decide the `+0x24` pass flag); > 2 adds a shooting gate and a dribble option | b | immediates |
| Personality inputs | attributes `0x14,0x18,0x19,0x1a,0x1c,0x1d,0x28,0x29,0x2c` (A), `0x18,0x28,0x2c` (B, in P4 alongside the A reads: `0x145663f5b/f6f/f84`), `0x27,0x36` (B); styles `R+0xCC` bits 0,3,4,5,9,10,12,13, `R+0xD0` bit 8; COM `R+0xD4` bits 0,1,2,4 (+), 6 (−); cards `0xc,0xd,0xe,0x11,0x2b`; role 7/9 | player-data | P2 (long/aerial) read by ~30 functions, P4 (dribble propensity) by 15+; players below the 70–75 floors have P ≈ 0 and behave generically; the cheapest way to give two identical-rating forwards different on-ball behaviour is the style bit | a | — |
| Personality windows (75..85, 70..90, 60..80, 65..85) and weights | float cells in `0x145663920..0x145664234` (e.g. 75.0 @`0x145e9c05c`, 85.0 @`0x1469e6cf8`, 70.0 @`0x145b711c0`, 90.0 @`0x145b52b90`, 60.0 @`0x145a8dd84`, 80.0 @`0x145a8aa48`, 65.0 @`0x146affd34`) | exe-constant (re-aim) | would spread P0/P1 across the whole ladder instead of saturating | b | 75.0: 180, 85.0: 92, 70.0: 305, 90.0: 1535, 60.0: 1512, 80.0: 353, 65.0: 173 — all shared |
| dribble pool gates | `0x1456ab418` (0x28 DoubleTouch), `0x1456ab46a` (2 Roulette), `0x1456ab489` (0x29 EdgeTurn), `0x1456ab4a8` (1 Eracico), `0x1456ab4e8` (3 Chapeu), `0x1456ab523` (0x43 SharpCut), `0x1456ab542` (0x42 TapTrick) | exe-code / player-data (cards `R+0xC0`, COM bit 0) | a player's visible skill repertoire | a | immediates |
| dribble weights window 70..90 and coefficients | Roulette `0x1456bba23` (70 @`0x145b711c0`), `0x1456bba2e` (90 @`0x145b52b90`), `0x1456bba3e` (20 @`0x145a8aa44`), `0x1456bba6c` (25 @`0x145da7de0`), `0x1456bbaf4` (10 @`0x145a8dd7c`); BodyFake `0x1456bcd73/ce02` (15 @`0x145c0b000`), `0x1456bcda3` (10), `0x1456bce1a` (0.9 @`0x145b56e08`), `0x1456bce37` (50 @`0x145ae7580`), `0x1456bce7a` (−20 @`0x146affd44`) | exe-constant (re-aim) | whether an 80-rated dribbler tries tricks at all (all-80: Roulette 40 %, BodyFake 22 %) | a | 305 / 1535 / 1099 / 659 / 1832 / 943 / 299 / 503 / 118 |
| Legend-only ×1.2 on move weights | `0x1456a96d8 mov edx,6`; factor 1.2 @`0x145c7e410` | exe-code | lower `edx` to 3 to give Professional+ the Legend trick rate | a | imm / 237 |
| dribble refractory | `0x1456ab136/0x1456ab144` (0.5), `0x1456ab156` tick, `0x1456ab116` (`subss xmm7,[Personality+0x18]` = **1 − P4** for Tricksters — player data, not difficulty) | exe-code / player-data | how quickly a trickster chains feints: Ball Control / Speed / Acceleration and the four COM flags shorten it through P4 | b | shared 0.5 cells |
| plain-dribble mistake rate by level | row `0x1a` (60/35/18/13/4/0…) at `0x1456ab267` | exe-constant | — | b | table |
| skill cards as decision levers | Player.bin skill flags → `R+0xC0`: Pinpoint Crossing (+40 cross roll, hard gate in `0x145695690`/EarlyCross), Long-range/Knuckle/Dipping/Rising (middle-shot base), Weighted/Low Lofted (long ball), Through Passing/One-touch Pass (through-ball image), Blitz Curler (common pass gate `0x145673930`), Chip/Control Curve/One-touch Shot/Outside Curler (shot type), Accel Burst (Burst move), Marseille/Sombrero/Flip Flap/Double Touch/Edge Turn/Tap Fake/Spring Cut (moves), Long Throw/Control Curve/Knuckle (set plays), the five pass cards (+0.1 each to P2) | player-data | — | b (a for P2 and the pool) | — |
| COM/AI flags as decision levers | Player.bin bits 614–680 → DB keys 63..69 → `R+0xD4`: Early Cross +30 cross roll; Long Ranger middle-shot base 60; Incisive Run curve-shot base 35 + MiddleShot/CurveShot gates; Long Ball Expert +50 long ball, −10 P4; Trickster/Mazing Run/Speeding Bullet unlock feint families and +10 P4 each | player-data | — | b | — |
| attributes the carrier actually consults | Ball Control, Tight Possession, Low Pass, Lofted Pass, Finishing, Heading, Speed, Acceleration, Kicking Power, Curl, Set Piece, Jumping, Physical Contact, Balance, Weak Foot Accuracy, Height, Offensive Awareness — thresholds e.g. `B[KickPower] ≥ 70`, `B[LowPass] ≥ 70` (`0x145679035`), `A[Heading] ≥ 70` (`0x14567b9e2`), `B[Speed] ≥ 99` (`0x14567f651`), `B[BallControl]+B[TightPoss] ≥ 160/170` | player-data | Kicking Power / Low Pass under 70 remove long shots and curlers; Heading under 70 removes long balls; Ball Control + Tight Possession sums unlock dribble options; **Dribbling does nothing here** | b | threshold cells shared (60.0: 1512, 70.0: 305, 8.0 @`0x145b52fbc`: 829) |
| enable the random pass unit | push `0x17` in `0x14566b980` (e.g. a cave after the PassOneTwo push at `0x14566bc41`), near the tail | exe-code | genuinely random receivers (rank-0 beats rank-2 only ~80 %) with a persistent RNG stream — the only true entropy source in the subsystem; must still survive first-valid-wins | b | — |
| dt270 | — | **not reachable** | no dt270 field changes pass/shoot/dribble choice | b | — |

## Corrections

Things this project's standing notes, the briefing for this job, or the earlier versions of this
chapter said, that the bytes refute.

| belief | reality |
|---|---|
| ThinkUnits are "consulted", order = construction order | evaluated **in bulk** into a table; the **first valid in list order** is adopted; the list is rebuilt every tick from the ball-state and the **held Image** (`0x14566b7f0/0x14566b980`). Construction order is irrelevant. [a] |
| slot 1 is an applicability test; `+0x78` is the result (`0xff` = none) | slot 1 is `reset`; the result is `unit+0xc` (class at `+0`, stamp at `+0x50`); `+0x78..` is private state (PassRandomTest keeps its chosen slot and RNG there). [b] |
| `BP+0x49c8` is the ThinkUnit registry | it is the 30-slot **results table**; the registry is at `BP+0x54d0`. [a] |
| `ThinkUnitSetPlay` is constructed "elsewhere" (`0x1456aecb1`) | constructed by `0x1456aeca0`, called from the registry ctor, at `registry+0x13b8`, kind `0x1d`. [b] |
| "the carrier brain contains a genuine randomiser" (`PassRandomTest`) | true of the code, **false of the game** — never listed, never called. [b] |
| "not reached" for Shoot/Dribble/PassForward is weak because the subsystem is virtual | the `vf2` bodies contain **zero** indirect calls (except DribbleChallenge's 5 DribbleImage dispatches); every bp virtual was itself a closure root; the reverse closure from the LCG and the callback-augmented closure close the gap. [b] |
| **"the carrier reads the runner's action ids at `teamAI+0x8f4c` in five pass units (`0x145699510`, `0x145690f60`, `0x145644700`)"** — the previous version of this chapter | the carrier band contains **no** `0x8f4c` read; the five sites are all in `0x145644700`, whose callers are the shared `vf2` of the `match::player::Action*` kick executors and the PassGetRoute region. The **executor** sees the runner; the **decision** does not. [b, re-read for this chapter] |
| the "user-controlled" list `PassRespondRequest, PassForward, PassLong, PassSafety, GKClear` keyed on `team+0x778+0x3b40+(idx%11)*4 == 0`; the brain "branches on user control" | `0x778+0x3b40 = 0x42b8` is the **formation role code** array; role 0 is the **goalkeeper** (the list ends in `GKClear`; role 1 gates the CB overlap; roles 7/9 unlock P3). `0x1442e1050(match, idx)` = on-pitch ∧ role 0. No function in the decision chain tests pad control *by name*; the unexplained `entity+0x41` byte (row below, added 2026-09-19) is the open candidate. [b, re-read] |
| "the human carrier is throttled onto the assist path because `0x144311e20` is a pad-bit test" (one probe) | `0x144311e20(id)` = `id < 0x71 && table[0x146c14e80][id] & 0x30000`, an **action-class** test on the current action id. [b, re-read] |
| step 8: "kind `0xa` PassBackSpace is a trigger replaced by the fallback; kind `0xd` PassSafety sets the hold flag" (previous version) | the compares are on the pending record's **class**: class `0xa` (Shoot's "carry") is swapped for the dribble record; class `0xd` (Shoot's lock) sets `+0x54c8`. [b, re-read: `mov eax,[r13]` at `0x145654689`] |
| answer classes 2/7 = clear, 3 = "generic kick, pass or dribble push" (previous version) | 2 = **pass**, 7 = pass-on-request, 5 = clear, 3 = dribble/carry, 4 = feint. Pass units and PassRandomTest write class 2 with a target at `+0x1c`. [b] |
| reaction delay is 0–1 frame everywhere except row `0x19` = 66/44/24/13/8/8 at "levels 4..9" (previous version) | that emulation indexed the table at stride 40 instead of `0x2c`. Real rows: pass/clear 60/40/22/12/8/6/2, dribble 60/35/30/16/8/6/0, dribble-move 60/35/25/20/12/10/10 at Beginner..Legend (columns 0,1,2,3,4,6,8). [a] |
| level gate rows `0x27/0x28/0x29` = `{1,1,1,1,1,1,1,1,0,1}` etc., "the higher levels lose them" (previous version) | same stride error. `0x27` = `0 0 1 1 1 1 1 1 1 1` (PassBackSpace off at Beginner/Amateur), `0x28` all ones, `0x29` = `0 0 0 1 …` (Feint off below Professional). [a] |
| "non-CPU players get delay 0 because `0x143e34030` is a CPU test" (previous version) | `0x143e34030` is the ball-state predicate (1, 2 = has the ball). [b] |
| "one `BallPlayer` per team, no per-player copy" (previous version) | the factory allocates 2 × 11 containers, one `BallPlayer` per squad slot. [b] |
| Image cooldown "= fps, i.e. 1 s" (previous version) | `0x14533eb20()` = the platform AI-tick global (54 on PC per exe-gameplay-map row 75), not the frame rate. [b] |
| `BP+0x14` is "a match-clock float" (one probe) | latched from the match random bundle's float; a `[0,1)` random per possession spell (convergent usage at five sites; updater not located). [b] |
| "the in-possession style bit is read 22 times inside `ThinkUnitPassSpecial`" (briefing) | the 22 reads are in one shared **receiver-eligibility** helper `0x145695690`, reached from PassForward, PassExpand and PassSpecial, testing the **receiver's** styles. [b] |
| "skill cards do not drive decisions — all 287 card sites are in `match::anime::action`" (off-ball chapter, standing note) | **wrong for the carrier**: 68 card reads in ~35 bp functions change entry chances, gates and Personality P2 (Pinpoint Crossing +40 on the cross roll, etc.). [b] |
| "`match::ai::Judge 0x143d114b0` is a shared decision oracle" (briefing) | it has **no direct caller anywhere in the image**; the carrier does not use it. Virtual dispatch to it is not excluded. [b] |
| "playing styles reach match code as role-gated category bits via `0x1442e2130`" (off-ball chapter, as the general rule) | on the ball the gate is called at **two** sites (CBOverlap); 50+ style reads are the raw bits. The off-ball "play him off his slot" rule does not carry over. [b] |
| `ATTR_get 0x143ea8cb0(player, idx)` is "the general getter" | zero call sites in the carrier band; the carrier uses the by-entity getters for arrays A (`0x1442dd650`) and B (`0x1442dd5b0`), and reads B more. [b] |
| "off-ball chapter: no human/CPU test is the pattern, the carrier differs" (previous version) | withdrawn — the carrier's list branch is on role, not control; but see the `entity+0x41` row added 2026-09-19. |
| `.pdata` "touching" merge is the right function-extent model (method note) | it glues 10,753 adjacent functions image-wide (e.g. `0x145653850` onto `0x145653b90`, `0x145695690` onto `0x145695d40`); use the **chained-unwind** merge (`tools/exe_funcs_chained.py`, 264,639 ranges) for per-function attribution. Closures for reachability still work with either. |

The rows below were added on 2026-09-19 after three adversarial reviews of the first version of
this chapter (central claims, inputs-and-tunables, completeness). Every claim was re-derived from
the PRISTINE bytes for this repair before the text was changed; the reviewers were right on every
point checked, and two of their findings were found to be *larger* than stated (the range/stream
coupling exists in all four rolling images, not only Cross; `0x1441af000` has one tail-jump entry).

| belief (first version of this chapter) | reality |
|---|---|
| "`ThinkUnitShoot` refuses unless the held image is one of {3, 4, 5} (`0x145685c88`)" | the `ja 0x145685d01` **skips only** `call 0x14565f000` and `mov byte [r15+0x7a],1`; execution falls into the shot acceptance `0x1456838c0` and the class-1 write at `0x145685d23` under any held image, and a second class-1 write at `0x145685e4a` sits behind row `0x20`, `r` and `P4`. `0x1456838c0` reads neither `+0x7a`, `mgr+0x530` nor `ctx+0x48`. [b] |
| "`Intention` is a dead latch — no ThinkUnit, ImageUnit, DribbleImage, the arbiter, PRE-PASS or DECIDE reads it through `ctx+0x40`" | `ctx+0x40` **is** the Intention pointer and the class getter `0x143b85440` is called on it at ~60 sites in ~30 carrier functions (PassForward, PassOneTwo, PassSafety, Feint, Dribble, the preamble, the PassForward filter and vetoes, the dribble helpers, and via the image ctx `+0x30` in MiddleShot/CurveShot/Long/PassThrough and the Expand/SideChange/BackDFLine helpers). The earlier scan missed the register-indirect getter. [b, band sweep] |
| "the receiver of a forward pass is the **argmax** of a two-term score" (a-emulated) | the a-emulation validated the **scorer** only. The loop (`0x14569d393..0x14569d3d1`) fixes its reference at the **first eligible** candidate's score and never raises it, so the winner is the **last candidate in plan-array order whose score beats the first eligible candidate's**, or the first eligible if none does. Two further terms were missing: a post-selection emission gate (`0x14569d590..0x14569d5b6` can return with no answer) and a second, lofted (**type 1**) search when the loop picks nobody (`0x14569d66b..0x14569d95c`). [b] |
| "Styles decide who qualifies as a forward-pass receiver; Target Man / Anchor Man / Build Up / Defensive Full-back / Destroyer never receive forward passes; only four styles are passed to behind the carrier" (a) | the predicate `0x145695690` runs **after** the target is chosen and only sets `rec+0x25` (PassForward `0x14569d654..0x14569d661`, PassExpand `0x14569d208`, PassSpecial `0x1456a0ba3`); the pass is emitted either way. The truth table is a-emulated; its gameplay consequence is **c** and open. |
| "the pass preamble `0x145699510` … rejects everything below Regular" | it returns false below Regular (`0x1456996cd → 0x145699617 xor al,al`); at **four** of its five callers (DirectHighBall, PassForward, PassSafety, PassSpecial) a false return does **nothing** while a true return sets `rec+0x24 = 1`, the pass record being written independently. At **PassOneTwo** (`0x14569e592`) a false return exits with no record (`0x14569e5a8 je 0x14569e716`); its only class-2 write `0x14569e6fa` is behind the true branch. Beginner/Amateur CPUs and Defensive Full-back carriers never get the flag and never play a one-two. Consumer of `+0x24` untraced. [b] |
| "the pass preamble rejects nothing; at every one of its five callers a false return does nothing" (first repair, 2026-09-19) | true for four callers; **false for PassOneTwo** — enumerating every `[r12..]` store in `0x14569e1d0` (r12 = the record, `0x14569e1df mov r12,rdx`) gives exactly `0x14569e6fa/702/707/710`, all behind `0x14569e5a8`. [b] |
| "randomness enters only through the plan rolls and the dribble shortlist — never through the pass/shoot/dribble choice itself" | the per-possession random `r` (`ctx+0x50`) is read **as a threshold** inside Shoot (7 sites), PassForward, PassOneTwo (4), Dribble (2), PassSafety (2), PassLong, the PassSpecial body (6) and the arbiter. The choice is deterministic only given `r`, which changes every possession spell. [b] |
| step 3: "`[entity+0x41]` … only continue when the lockout has expired"; "the machine runs for the human's carrier too, with the outfield CPU list" (c-structural) | `byte[entity+0x41]` (= `Player+0x7f49`, copied by `0x144157270`; writer not located) routes the carrier to `0x145651100`, which **bypasses the candidate loop** and emits a move-only output when the byte is set — except that the PassBackSpace kind-0xa re-run (`0x14565152e..0x145651655`) sits on the common tail `0x14565151a` reached from **both** the set and clear paths and can overwrite that output. The full decide continues only while `+0x534c` is **non-zero** (`cmp [r14+0x534c],0; jbe 0x145654798`) plus the stamp, no-current-kind and `0x34a0 == 5` tests — the sign was inverted. "Runs for the human with the outfield list" is **untested**, not structural. [b] |
| the `0x3308 == 1` veto block as a list of independent tests; "`+0x54b2` is the feint-in-progress byte" | it is a **switch on the fallback record's class**: class 4 → NONE unconditionally (`0x145650f2e`); class 3 **with** `+0x54b2` → the veto chain (kinds 0xb/0xd/0x12, `LONG_PASS`, the P2/P4 PassBackSpace test, PassExpand `+0x311`, then `+0x54b0`); otherwise the candidate wins. `+0x54b0/+0x54b2/+0x54be` are unnamed plan-record bytes `+0x38/+0x3a/+0x46` (16-byte plan copy at `0x14566a330`). [b] |
| "a unit in state 2 keeps resubmitting its old record until the delay filter lets it out" | while the filter refuses, the runner leaves the output **empty** (`0x145652612`; only kind 3 gets the fallback copied), so the answer is invisible to the selector that tick and a lower-priority unit with a shorter delay wins instead. [b] |
| "`0x14567b504 mov esi,0x64` is the cap and the RandInt range — lowering N below 100 makes every cross likelier" (tunable) | `esi` is also the **RNG stream index** (`lea edx,[rsi-0x62]` for the seeder, `lea r8d,[rsi-0x62]` for RandInt); the same coupling exists in MiddleShot (`0x1456790f9`, and its cap `0x5a` via `lea edx,[rax-0x58]`), CurveShot (`0x145678acb`) and Long (`0x14567ba6c`). Values outside 98..101 index outside the four-u32 stack state. **Not safely tunable.** [b] |
| "all four [rolling images] seed from `int(r × 1500)` (cell `0x146401b78`, 5 referrers)"; "every rolling image computes the identical draw" | Cross ×1500 (`0x146401b78`, 5 — shared with GK animation and non-gameplay code), MiddleShot ×1200 (`0x145bd7fc4`, 11), CurveShot ×1300 (`0x146b9b29c`, 2), Long ×1600 (`0x1466c54f0`, 28). Each image's draw is fixed for the spell; the four do not share one. All four cells re-aim only. [b + census] |
| "accept iff score ≥ RandInt(100)"; "acceptance = (score+1)/100" | the roll is a **gate**: after it passes, ~110 bytes of further conditions run (`0x14567b54e..0x14567b666`) as an **any-of** chain — designated target, `0x143e30e10`, `team+0xb3c4`, `team+0xb44d`, Pinpoint, `+0xb50 <= 0 ∧ +0xb4c != 0`, `input+0x1c > f ∧ +0xb4c != 3`, pass-work `+0x34`/`+0x30` above their tick windows, Early Cross, `byte[team+2]` — each of which jumps straight to accept (`0x14567b664`); the plan is rejected only when all of them fall through (`0x14567b65e je 0x14567b162`). `team+0xb44d ≠ 0` bypasses score and roll. `(score+1)/100` is the roll segment's pass rate only. [a segment, b chain] |
| "MiddleShot / CurveShot / Long … score vs RandInt 0..99: 100 = always" | MiddleShot clamps the score to 90 (`0x1456790c7`), CurveShot to 90 with a floor (`0x145678a7c`) — max 91 %; only Cross caps at 100; Long has no cap and is forced to 100 by `team+0xb3c4`. [b] |
| "No tactical-instruction channel and no other per-match setting is read" beyond the attack level | `team+0xb3c4` (8 sites: forces cross/long plans, disables Safety), `team+0xb44d` (10 sites: bypasses the cross roll, guarantees MiddleShot's +40 where clear would give +70 or +0), `team+0xb3bd` (4), `team+0x204` (7 `cmp dword` sites in bp) and `team+0xb4c/+0xb50` (14) are read as decision inputs. Names and writers unknown. [b, band sweep] |
| "dribble refractory: `1.0 − levelParam[+0x18]` for Trickster players" | the load is through `ctx+0x60` (Personality), not `ctx+0x58`: the factor is **1 − P4** — a player-data input, not difficulty. [b] |
| "dribble commit window 0.35 s … 87 (near-private) so a direct edit is less risky" | 87 referrers is a **shared** cell by the census's own definition; route is re-aim, never in place. [census] |
| "none of the other 86 referrers is a bp function" (first repair, 2026-09-19, read off the census's default 15-row listing) | `exe_census.py cell 0x145c7ec6c --all` lists seven other `match::ai::bp` readers (`0x1456a27cf`, `0x1456a34cc`, `0x1456b551f`, `0x1456b6261`, `0x1456bdcbf`, `0x1456be10e`, `0x1456c84cb`), the bp-region helper `0x14568c68a` and `match::player::ActionDelay` `0x14563839d`. The re-aim-only conclusion is unchanged (an in-place write would move those seven dribble sites too). [census] |
| "Cross Specialist (cat 8) is read in the receiver predicate `0x145695690` (`0x14569677b`)" | `0x14569677b` is inside the neighbouring `0x145695d40` (chained extent of `0x145695690` ends at `0x145695d40`), called only from `PassCross::vf2 0x14569b540`. The same glue error the method note warns about. [b] |
| "Personality windows: 70.0: 305, 90.0: 1535, 60.0: 1512; others not censused — assume hundreds" | 75.0 @`0x145e9c05c` = 180, 85.0 @`0x1469e6cf8` = 92, 80.0 @`0x145a8aa48` = 353, 65.0 @`0x146affd34` = 173 — all shared. [census] |
| Personality inputs row: `0x27,0x36` as the only B-array reads | P4 also reads `B[0x18]`, `B[0x28]`, `B[0x2c]` (`0x145663f5b/f6f/f84`) alongside the A reads. [b] |
| "CPU reaction-time table cells … single xref `0x1442e491d`" | the `lea` is at `0x1442e491a` (offline table) and `0x1442e4910` (online table `0x146c067b0`). [b] |
| Cross post-roll chain rendered as fall-through requirements — "else require (`+0xb50 > 0` or `+0xb4c == 0`), (`input+0x1c <= f` or `+0xb4c == 3`), `+0x34`/`+0x30` inside two windows, then Early Cross or `byte[team+2]`" (first repair, 2026-09-19) | `0x14567b5c1..0x14567b666`: every one of those tests **jumps to accept** (`0x14567b664 mov al,1`) when it fires — `jg`/`jne`/`jbe`/`jne`/`ja`/`ja`/`jne` — and only the full fall-through reaches `0x14567b65e je 0x14567b162` (reject). So `+0xb50 <= 0 ∧ +0xb4c != 0` accepts, `input+0x1c > f ∧ +0xb4c != 3` accepts, being **above** either tick window accepts. The chain is any-of. [b] |
| MiddleShot "then always +40 (`0x145678fc7`), replaced by +70 only when …" (first repair) | `0x145678fa4..0x145678fca`: class == 2 → +40; else `team+0xb44d != 0` → +40; else `team+0x204 == 3` → +70; else `0x145678fc0 jne 0x145678fca` lands **after both adds** → +0. There is no "always +40". [b] |
| "the PassBackSpace re-run lives on the `+0x41 == 0` side of `0x145651100`"; "a move-only output that bypasses every ThinkUnit" (first repair) | the re-run `0x14565152e..0x145651655` is on the common tail `0x14565151a`, reached by `0x1456512e9 jmp` from the `+0x41`-set path and by `0x1456512f5`/`0x145651308` from the clear path; on an accepted class-2 answer it copies to `+0x5428`, sets `+0x5420 = 0xa`, `+0x5350 = 1` and applies via `0x145651cb0`, overwriting the move-only result. The divert bypasses the candidate loop *except* that re-run. [b] |
| fast flag: "`route +0x138 > 25 m`, `route +0x18 != 0`" (first repair) | `0x14569d57a` compares `route+0x138` against cell `0x145b56e28` = **16.0** (25.0 @`0x145da7de0` belongs to the lofted second search at `0x14569d71f`); `0x14569d583 mov rax,[rsi]` loads `ctx+0` = `&BP+0x18` (the retry work) and `0x14569d586 cmp [rax+0x18],r15d` tests the **role code** `retryWork+0x18 != 0`, not a route field. [b] |
| Shoot's second class-1 write "behind two `r` thresholds" (first repair) | the `comiss xmm7/xmm8, r` at `0x145685da9/0x145685dba` only choose which of three `xmm6` values is computed; the gates on `0x145685e4a` are the row-`0x20` test (`0x145685d3f`), `r14b` (`0x145685df7`), `P4 > k·r` (`0x145685e0d..e15`) and `0x1456841c0`. Minor overstatement. [b] |
| "PassBackSpace and PassOneTwo need PassThrough(7)" | true for PassBackSpace (`0x14569b340`); PassOneTwo's gate is *not a shot image* and Intention class < 3, with images 5/7 as inner sub-paths. [b] |
| "sub-state 0xd: no shots/passes for fps·3 frames" | additionally requires `0x1442de630(match) == 0xa` (`0x145650dfa`); the same dword is compared against the player index in the list builder, so its meaning ("holder slot"?) is unsettled. [b] |
| reaction-delay table in "frames", "~1.1 s / ~33 ms" | the table values are **ticks** (raw table value at tick 54; the harness stubbed 60); seconds depend on the unread runtime global. [c for seconds] |
| "the CPU on Superstar … scores higher" (unlabelled) | inferred only; the 14 ramps' direction and multiplicand were not read. [c] |
| "the carrier band contains no read of `teamAI+0x8f4c`" | the five reads lie **inside** the band as the header defines it (`0x145644700`); the negative is true of the bp module `0x145650000..0x1456cb000` / of every bp function. |
| "`0x14561fe20` = the shared vf2 of every `match::player::Action*` kick executor"; "`0x1441af000` has no callers" | `0x14561fe20` is in no vtable (reached via thunk `0x144113740` and one call from `0x144175ca0`); `0x1441af000` has one tail-jump entry at `0x144249dbf`. Executor identity is c; the route-table question stays open. [b] **↳ THIS ROW IS ITSELF WRONG — corrected 2026-09-19 by [player-executors.md](player-executors.md):** `0x14561fe20` **IS** kick-contract slot 2, in **33 of the 34** kick vtables (raw qword reads for ShortPass, Shoot, Tackle, Sliding and KeeperCatching all match). So the original claim this row "corrected" was right, and the correction was the error. The executor-identity downgrade to `c` is withdrawn. [b] |

Unresolved between two of this project's own notes: the emulated `DATA_PARAMETER` enum names match
index `0x17` **DRIBBLE**, while the memory `attr-0x17-defending` (and the off-ball chapter) calls it
a defensive-positioning attribute. One of the two is wrong; this job did not adjudicate. The carrier
never reads `0x17` either way.

## Class status — what was decoded and what was only listed

All 65 `match::ai::bp` classes in `build/exe_map.json`, so a reader can tell "looked up" from "never
examined". **decoded** = behaviour read (a or b) to the level stated elsewhere in this chapter;
**gates/inputs** = only the entry gate, image gate or input profile is known, the body is not;
**listed** = the class appears in a list-membership or pool-gate statement and nothing else was
read; **dead** = never runs (no push site / never pooled); **not examined** = no statement in this
chapter rests on its bytes. Addresses: ThinkUnit `vf2` (think), ImageUnit slot 2 (`canStart`) and
slot 1 (`vf1`), DribbleImage slot 2 (weight).

| class | key address | status | what is known |
|---|---|---|---|
| BallPlayer | ctor `0x145650860` | decoded | layout, tick chain, DECIDE, PRE-PASS, PUBLISH, super-cancel path |
| BallPlayerRetryWork | — | gates/inputs | fields `+0`, `+0x18` role, `+0x58` ball-relation state; names not recovered |
| ChallengeDribbleWork | `0x1456a9570` | decoded | pool, weights, shortlist roll (a), stage-B walk (b) |
| DribbleImageBase | vft `0x147723df0` | decoded (base) | slots 0–3, 7, 9 read; **slot 4–9 overrides in the 15 moves not examined** |
| Intention | `0x145662ed0` | gates/inputs | update inputs at profile level, class 0..4, all readers listed; geometry thresholds not decoded |
| Personality | `0x145663920` | decoded (a) | closed form, 0 mismatches; readers per field |
| ThinkUnitBase | vft `0x147723dd0` | decoded | 3-slot contract, registry, lifecycle |
| ThinkUnitShoot | `0x1456853f0` | decoded (partial) | lock / class-1 (two sites) / carry branches, `r` and `P4` reads; aim point and `0x1456838c0` not decoded |
| ThinkUnitClear | `0x143e8fca0` | decoded | one gate, power from `0x143e8d8b0` |
| ThinkUnitDribble | `0x1456a6f70` | decoded | four output branches, `r`/Intention/P reads |
| ThinkUnitDribbleChallenge | `0x1456aac80` | decoded | stage A (a) + stage B (b) |
| ThinkUnitFeint | `0x1456a25e0` | dead | never listed (row `0x29` inert); only two Intention compares read |
| ThinkUnitForce | `0x1456acf10` | gates/inputs | three sub-deciders in order; only the third (`4·fps` release) read |
| ThinkUnitGKClear | `0x1456ac340` | **listed** | GK list tail; body never read |
| ThinkUnitGKDribble | `0x1456ac6e0` | dead, not examined | never pushed, no direct caller |
| ThinkUnitGKPassShort | `0x1456ace40` | dead, not examined | idem (one `0x143e31a10` category-9 read noted) |
| ThinkUnitGKPassLong | `0x1456acad0` | dead, not examined | idem |
| ThinkUnitHoge | `0x140c83910` stubs | decoded | the map's not-found null object |
| ThinkUnitPassBackSpace | `0x14569b300` | gates/inputs | image-7 gate `0x14569b340`, row `0x27` enable, arbiter veto, super-cancel re-run; body not read |
| ThinkUnitPassCross | `0x14569b540` | gates/inputs | image-9 gate `0x14569b615`, reads P1/P4, helper `0x145695d40` (Cross Specialist); body not read |
| ThinkUnitPassDirectHighBall | `0x14569bfa0` | gates/inputs | always last; preamble caller; 3,330-function closure with LCG reach — body not read |
| ThinkUnitPassEarlyCross | `0x14569cb20` | gates/inputs | Pinpoint gate `0x14569ce73`, `team+0xb44d` at `0x14569ce38`; body not read |
| ThinkUnitPassExpand | `0x14569cf30` | gates/inputs | image-13 gate `0x14569cf4a`, predicate caller (`+0x25`), Intention `+0x311`; body not read |
| ThinkUnitPassForward | `0x14569d240` | decoded | filter/vetoes at profile, selection loop, emission gate, lofted second search |
| ThinkUnitPassGoalFront | `0x14569d9a0` | dead, not examined | never pushed |
| ThinkUnitPassLong | `0x14569db30` | gates/inputs | image-10 gate, P2 and `r`, target helper `0x14568ac30` thresholds |
| ThinkUnitPassOneTwo | `0x14569e1d0` | gates/inputs | entry gate, Intention/`r`/P4 compares, image 5/7 sub-paths, preamble `0x145699510` as a hard gate before the only class-2 write `0x14569e6fa`; body logic not read |
| ThinkUnitPassRandomTest | `0x14569e740` | decoded, dead | full formula; never consulted |
| ThinkUnitPassRespondRequest | `0x14569ea20` | decoded | request matrix walk; matrix writer unknown |
| ThinkUnitPassSafety | `0x14569ed80` | gates/inputs | image-14 gate, `r` and Intention exits, preamble tag; body not read |
| ThinkUnitPassSideChange | `0x14569f390` | gates/inputs | image-11 gate `0x14569f3b2`, reads P2/P5; body not read |
| ThinkUnitPassSpecial | `0x14569fa80` / body `0x14569fc30` | gates/inputs | driver decoded; body: level bail, `r` bail, tags `+0x24/+0x25`; rest of the 947 instructions not read |
| ThinkUnitPassTarget | `0x14569fb30` | decoded | image-12 gate, route state/rank test, class 2 type 0 |
| ThinkUnitSetPlay | `0x1456b0060` | gates/inputs | attribute/card/row `0x2a` inputs, 8 style queries; body not read |
| ImageUnitNone | slot 2 `xor al,al` | decoded | never starts |
| ImageUnitDribble | slot 2 `mov al,1` | decoded | never self-ends; execute `0x145677470` |
| ImageUnitLilux | `0x145676c30` / vf1 `0x145677a70` | decoded | once-per-spell relax plan |
| ImageUnitShotShort | slot 2 `0x140e702a0` (shared stub) / vf1 `0x1456791e0` | **listed** | cooldown-exempt; the three shot-image gates `0x144300990/0x144300a40/0x143e31cb0` not examined |
| ImageUnitMiddleShot | `0x145678b30` | decoded (b) | base/bonus/cap formula read, not emulated |
| ImageUnitCurveShot | `0x1456786c0` | decoded (b) | idem |
| ImageUnitShotPassFromGoal | `0x14567bb10` / vf1 `0x140c83910` | **listed** | list membership only |
| ImageUnitPassThrough | `0x14567af00` (shared canStart) / vf1 `0x14567c260` | gates/inputs | vf1 card tests; target selection not decoded |
| ImageUnitPassForward | `0x14567af00` / vf1 `0x14567fa60` | gates/inputs | vf1 reaches the attribute-seeded `0x145674ec0`; target selection not decoded |
| ImageUnitCross | `0x14567af10` / vf1 `0x14567e4e0` | decoded (a) | roll segment emulated, post-roll chain read |
| ImageUnitLong | `0x14567b670` / vf1 `0x14567f230` | decoded (b) | formula read; vf1 target selection not decoded |
| ImageUnitSideChange | `0x14567bb30` / vf1 `0x145680900` | gates/inputs | vf1 style/COM tests; body not read |
| ImageUnitBackDFLine | `0x14567af00` / vf1 `0x14567e3e0` | **listed** | list membership; vf1 not read |
| ImageUnitExpand | `0x14567af00` / vf1 `0x14567ef80` | **listed** | list membership; vf1 not read |
| ImageUnitSafety | `0x145676c90` / vf1 `0x145677ae0` | decoded (b) | `r` vs level fraction, age test, `team+0xb3c4` kill |
| ImageUnitCBOverlap | `0x145676a00` / vf1 `0x1456778c1` | decoded (b) | Extra Frontman + role 1 + attack level ≥ 2 |
| DribbleImageNoFeint | weight `0x143e02700` | gates/inputs | never pooled; COM gates; reads P0/P1/P4 |
| DribbleImageBurst | `0x1456ba370` | gates/inputs | COM bits 1/2, card `0x37`; weight formula not read |
| DribbleImageRoulette | `0x1456bb810` | decoded (a) | weight; execute draws `RandInt(10)` in phase 3 (the rest of slot 1 not read) |
| DribbleImageBodyFake | `0x1456bcb10` | decoded (a) | weight |
| DribbleImageDoubleTouch | `0x1456be660` | listed (pool gate) | card `0x28`; vf7 level ramp noted; weight not read |
| DribbleImageEdgeTurn | `0x1456bf440` | listed (pool gate) | card `0x29` |
| DribbleImageEracico | `0x1456c07b0` | listed (pool gate) | card 1 + COM bit 0 |
| DribbleImageKickFeint | `0x1456c2fa0` | gates/inputs | COM gates; reads P1/P2/P5; weight not read |
| DribbleImageDrawOpen | `0x1456c41c0` | gates/inputs | always pooled; vf7 reads P0; weight not read |
| DribbleImageChapeu | `0x1456c52f0` | listed (pool gate) | card 3 |
| DribbleImageHumiliating | `0x1456c6500` | listed (pool gate) | COM bit 0 via the team block; reads `team+0xb3c4` |
| DribbleImageTrapThrough | `0x1456c7f90` | gates/inputs | always pooled; COM gates; weight not read |
| DribbleImageShielding | `0x1456c8c90` | not examined | never pooled; entry path not found |
| DribbleImageSharpCut | `0x1456c9ab0` | listed (pool gate) | card `0x43` (shares its weight function with TapTrick) |
| DribbleImageTapTrick | `0x1456c9ab0` | listed (pool gate) | card `0x42`; execute draws `RandInt` |

Of the 15 move classes, **3 weight functions are decoded, 12 are not; all 15 execute state machines
are unread.** Of the 26 ThinkUnits, 9 are decoded, 12 are gates/inputs only, 1 is listed only and 4
are dead-and-unread. Of the 16 ImageUnits, 9 are decoded, 3 are gates/inputs only, 4 are listed
only. Nothing in this table was decoded during the 2026-09-19 repair; it records what the earlier
work did and did not look at.

## Negatives — proven absent, do not spend a week on these

- **Six registered units never run:** Feint (4), PassGoalFront (9), PassRandomTest (0x17), GKDribble
  (0x19), GKPassShort (0x1a), GKPassLong (0x1b). No list-builder branch pushes them, no direct `vf2`
  call exists, the dispatcher is the sole entry, and the only direct evaluations are kinds 2, 3 and
  `0xa`. The GK list uses the outfield pass units plus GKClear. [b, exhaustive]
- **No scoring across units.** No `vf2` returns a score; `rec+0x58` is never compared; the arbiter
  compares only "has an answer" (adversarial class values change nothing). [a]
- **No attribute** is read by the arbiter, the list builders, the pre-think gate or the delay
  function; attributes enter through `Personality` and inside think bodies. [b]
- **No frame-parity or rate guard** anywhere between `Player::vf1` and the decision loop. [b]
- **The receiver predicate `0x145695690` and the pass preamble `0x145699510` never veto a pass at
  seven of their eight call sites**: there their result only sets `rec+0x25` / `rec+0x24`. The one
  exception is the preamble at PassOneTwo (`0x14569e592`): a false return exits (`0x14569e5a8 je
  0x14569e716`) before the unit's only class-2 write (`0x14569e6fa`). [b]
- **Kinds 5–8 do not exist**; `ThinkUnitHoge` is the map's not-found null object with `ret` stubs. [a]
- **`Personality` P6 is never written, P7 is never read**; the update has no RNG, no indirect call, no
  role-gated style query. [a]
- **No free-running RNG in the live brain**; the only persistent stream (`PassRandomTest+0x7c`) is
  idle. LCG entries `0x144345d90/e50/eb0/1a0` have 0 sites in the band; only `0x144345e00` is used,
  at 13 sites in 11 functions. [b]
- **`0x145674ec0`'s attribute-seeded draws are not randomness** — a fixed per-player percentile,
  non-monotonic in the attribute. [a]
- **Dribbling (`0x17`)** is read nowhere in the carrier (131 getter sites, neither getter passed
  `0x17`); nor are Defensive Awareness, GK Awareness, Aggression, Defensive Engagement, Stamina,
  Form/Condition, Injury Resistance, Age, Weight, the C array. Dribbling does not influence whether
  the CPU dribbles; form does not influence any on-ball choice. [b]
- **The dribble pool depends on no attribute**; Ball Control unlocks nothing. NoFeint and Shielding
  are never pooled (their entry path, if any, was not found). Roulette's "no card 2" branch is
  unreachable. [a]
- **The PassForward scorer never reads the receiver's attributes**; receiver quality enters only
  through the route rank computed elsewhere. [a] (The *selection loop* around it is not an argmax —
  § Pass-target selection.)
- **dt270 has no reader in the carrier** (105 located objects, depth 3, no ConstantManager call). [b]
- **The off-ball quota reader `0x1442f9a90` and `team+0xb454` (AUTO)** are never read by the
  carrier. [b]
- **No off-ball selector reads the carrier's published plan** (`PlayerAI+0x1158/+0x1160`: 84 sites
  checked, all copies/resets). [b]
- **No `match::ai::bp` function reads `teamAI+0x8f4c`** (runner action ids); the five reads below
  `0x1456d0000` are all in `0x145644700`, outside the bp module `0x145650000..0x1456cb000`. [b]
- **`match::ai::Judge`** has no direct caller in the image. [b]
- **The out-of-possession mask** reaches the carrier at exactly two sites (The Destroyer as a
  receiver veto and in Personality); no role-gated out-of-possession query is made. [b]
- **`ImageUnitNone` can never be entered; `ImageUnitDribble` can never self-end.** [a]
- **Card bit `0x2d`** is assigned to no skill (72 entries for 73 bits). [b]
- **The published image cells `BP+0x539c..`** have no reader outside PUBLISH. [b]
- **The kind-name getter `0x143e8fe10`** returns a constant empty string; there is no kind name table.
  [b]

## Open questions

1. **Who fills the route table** (`ctx[0x38]+0xb78`: rank 0..5, state `0xb`, distances) — the real
   lane/interceptor evaluation the pass units rank by. Candidates: `0x145655430` / `0x145655dd0` in the
   pre-decide path, the `match::player::PassGetRoute*` family. Until it is decoded, "receiver quality"
   is a black box, and whether it (rather than the brain) consumes runner action ids is unknown.
2. **Who writes the pass-request matrix** `match+0x24114` and `[ent+4]/[ent+8]` read by
   `PassRespondRequest` — the human "call for pass", an off-ball selector, or the keeper. This is the
   only candidate channel for the two brains talking.
3. **`ThinkUnitForce`**: what its first two sub-deciders (`0x1456ad520`, `0x1456ad240`) force, and how
   often; it is first on every outfield list.
4. **`ThinkUnitShoot`** aim point and the kind-1 acceptance `0x1456838c0`; **`PassDirectHighBall`**
   (last on every list; a 3,330-function closure with LCG, style and card reach — the one pass unit
   that may be random); **PassSpecial**'s two 0x1f0-frame helpers; PassSafety/PassLong/PassCross bodies
   beyond profile level; the conditions inside `0x1456a6450` (class 4/`0xd`) and `0x1456a68c0`
   (class 4/`0x17`) that make a dribble unpassable in open play.
5. What the **four difficulty fractions** `BP+0x699c..+0x69a8` (rows `0x1b..0x1e`) scale inside the
   units, and the full per-kind modifier table in the delay filter `0x145653450` and the rest of the
   3 KB pre-think gate `0x145654820`.
6. **Ability arrays A vs B vs C**: which is progressed/current and whether condition/form is applied
   in place at match time (the DB accessors `0x144a2a300` / `0x144a0d7c0` were not followed).
7. **Names**: the ball-relation state enum at `+0x18+0x58`; role codes 7 and 9 (attacking roles);
   attribute `0x36` (0..3, weak-foot usage is the natural guess); the meaning of `match+0x3308 == 1`
   (open play, by two consistent uses, no writer found); `ctx[0x50]`/`ctx[0x58]` semantics beyond
   "possession random" and "level fractions".
8. **The human carrier**: whether the machine runs for him at all now hinges on `entity+0x41`
   (open 14); if it does, whether its published answer is executed or only consumed by assist
   features (the pad layer is the command source) is not established. Also the meaning of
   `byte[entry+0xe]` in the `0x1442d6cc0` table that co-gates PRE-PASS with `BP+0x10`.
9. The exact use of each Personality read inside the units beyond the arbiter, PassForward, Shoot
   and the dribble refractory (readers are known, thresholds mostly are not). (The window-cell
   sharer counts are now all censused — § Tunables.)
10. The **match random bundle's updater** (the function writing `*(g+0x790)+8`) and what `+0` holds
    (tick counter, by usage).
11. **ImageUnit `vf1` target selection** for PassThrough/PassForward/Expand/Long/SideChange/
    BackDFLine; the intention-kind helpers behind `0x1456762e0`'s `call r10`; the three shot-image
    gates `0x144300990 / 0x144300a40 / 0x143e31cb0`; MiddleShot/CurveShot/Long full formulas.
12. Which of the two claims about attribute `0x17` (DRIBBLE vs defensive positioning) is right.
13. The exact caller of `match::Player::vf1` (identified by signature only) and whether anything
    above it skips ticks.
14. **Who writes `match::Player+0x7f49`** (→ `entity+0x41`, the step-3 divert to the move-only path
    `0x145651100`). No disp32 writer exists in the image; it is set through a sub-object pointer. Its
    meaning decides whether the human's carrier ever runs the CPU list. (§ human vs CPU)
15. **What consumes the pass flags `rec+0x24`** (preamble) **and `rec+0x25`** (receiver predicate) in
    the executor. Until then every style-based "who gets passed to" statement is about a tag, not a
    choice.
16. **The per-match team fields `team+0xb3c4`, `+0xb44d`, `+0xb3bd`, `+0xb4c/+0xb50`**: names and
    writers. `+0xb3c4` forces cross/long-ball plans and kills Safety — the strongest on-ball lever
    seen, and unusable until identified.
    **PARTIALLY ANSWERED 2026-09-19, pending adversarial verification** — see
    [registry-blackboard.md](registry-blackboard.md) § `team+...`, `teamAI+...` and `UTeamAIInfo` are
    ONE object. The base is `match::registry::UTeamAIInfo` (0xbd8c = 48,524 bytes, one per team),
    proven by its copy-assign `0x143c43370` walking 646 offsets to exactly `size-4` = `0xbd88`, with
    three callers in this band. `+0xb44d` has real writers (`0x143d02f07`, `0x1442efeef`, both
    off-ball AI); `+0xb3c4` has **none** — it arrives by whole-record copy, so the open question is
    now what fills the source record, not what writes the field. Names still unknown. [b]
17. **`0x1442de630(match)` = `dword [g+0x28780]`**: compared against the player index in the list
    builder and against `0xa` in the arbiter's sub-state-0xd branch; one reading is wrong.
18. **The plan-array order** each `ImageUnit::vf1` writes into `plan+0x9c` — because PassForward's
    "last to beat the first" loop makes the receiver depend on that order.
19. **Never-examined bodies** (§ Class status): `ThinkUnitGKClear`, `ThinkUnitPassGoalFront` /
    `GKDribble` / `GKPassShort` / `GKPassLong` (dead but unread), `ImageUnitShotShort` /
    `ShotPassFromGoal` / `BackDFLine` / `Expand` bodies, the PassBackSpace / PassEarlyCross /
    PassSideChange / PassExpand / PassCross / PassDirectHighBall bodies beyond their gates, 12 of the
    15 `DribbleImage` weight functions, all 15 execute state machines and the `DribbleImageBase`
    slot 4–9 overrides.
20. The `0x144249dbf → 0x1441af000 → 0x1441aecd0 → 0x145648f30 → 0x145644700` chain (the one
    reader of the runner ids below `0x1456d0000`): what enters at `0x144249dbf`, and whether that
    path is the route-table filler (open 1).

## Harnesses

`tools/emu_bp_harness.py` (selector, registry, delay, Personality — first pass),
`tools/emu_bp_personality.py` (`model p|i N`, `probe`, `rng`: Personality closed form on both images,
the LCG API), `tools/emu_bp_image_dribble.py` (sections A Cross roll, B move weights, C stage A
shortlist and pool, D the Image loop with instrumented units), `tools/bpx.py`,
`tools/exe_funcs_chained.py` (chained-unwind function extents), `tools/emu_enum_names.py` (the
`DATA_PARAMETER` registrar). Scratch scans (receiver predicate truth table, GetParam level map,
input census, reverse/callback closures) live in the session scratchpad under `di/`, `tu2/`, `pr/`,
`bp/` and are not shipped.
