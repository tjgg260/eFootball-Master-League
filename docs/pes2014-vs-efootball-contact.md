# Physical contact: PES 2014 vs eFootball (2026-09-19)

Why PES 2014's collisions and fouls read as physical, what eFootball kept, what it threw away,
and how much of the difference is reachable. Produced by decoding both games directly.

Sources: `C:\Program Files (x86)\KONAMI\Pro Evolution Soccer 2014` and the installed eFootball.
Decoder: [`tools/mbinfo.py`](../tools/mbinfo.py) (`verify` re-proves every layout below).

## TL;DR

- PES 2014's quality is **hand-authored craft**, not physics. Contact is one choreographed
  two-person animation, layered over the run, resolved by a contest that takes ~50 frames.
- eFootball runs **the same engine lineage and the same animation pipeline**, and its contact
  metadata is **3–7x richer** than PES 2014's. The art infrastructure got better, not worse.
- The `Jostle*` classes, `PairAnime` and every `*RetryWork` class are gone from the executable —
  but the jostle **animations** are not: eFootball has **259** of them to PES 2014's 124.
  The contest was **restructured, not deleted**. See the revision section: true two-actor pairs
  fell from **26% to 2%**, and single-actor shielding rose to **87%**. eFootball models contact
  as something the ball carrier *does*; PES 2014 modelled it as something two players *do to
  each other*.
- One number explains the loss of individuality: `PersonalizedData` went from 24,972 bytes to
  **236** — 1% of what it was.

## How PES 2014 does it

Seven mechanisms stack. None dominates, which is why it reads as physical rather than scripted.

1. **Paired animation.** Jostles are authored as `_main` / `_sub` halves bound by
   `constant::PairAnime` — one two-person move, like a film stunt. Nobody reacts to anybody.
2. **Contact is an additive layer.** `layer_jostle_*`, graded `far` / `middle` / `near`, applies
   over the run instead of replacing it. You keep running while being shoved.
3. **The contest takes time.** From `match/ai/team/pairAnime.json` (Konami's own Japanese
   comments): resolves over **50 frames moving / 90 stationary**; win share = stat gap (capped
   at `paramDiffMax` 20) x **0.25**, plus positional advantage x **0.2**; settled instantly if
   the gap at first contact clears `firstContactMargin` 10.
4. **The library is indexed, not blended.** Names encode `speed_in _ speed_out _ angle`
   (`stagger_lowbody_2_3_045`). Staggers split by body region (`upbody` / `lowbody` / `headj`),
   angle, and severity (`_hard`, `_small`). Losing the ball has its own family by *how*
   (`lose_nutmeg_*`, `lose_feint_*`, `lose_dribble_deprived_*`).
5. **Bodies stay glued.** `HoldData` marks contact windows with a bone and an offset, repeated
   through the jostle loop.
6. **Falls chain into get-ups.** `DemoConnectData` records which of 14 body postures an
   animation ends in (`facedown`, `allfours`, `knee_l`, …) and the frame the next one connects.
7. **Interrupt windows.** `CancelData` gives per-animation cancel frames — weight without
   losing the controller. Plus per-animation face and hand tracks (`FHSequence`), and
   `PersonalizedData` giving named players their own spine and arm styling.

Contact is IK-warped onto the real ball: `HitData` stores a *canonical* ball position plus
`ik_start` / `ik_end`, so the authored motion bends to reality rather than snapping the ball.

Fouls are decoupled. A separate referee agent (`match::referee::RefereeChief`, `RefereeLinesman`)
*observes* contact and judges it via script predicates (`CheckFoulKind`, `CheckFoulSituation`,
`CheckIsAdvantage`) → `CMD_ADD_FOUL`. Injury is a 0-255 damage scalar mapped independently to a
severity and a symptom (`match/ai/judge/injury.json`).

## What eFootball kept and lost

Same codebase lineage — `collision::Human`, `match::referee::RefereeChief`, `CmdAddFoul` are
**identical class names** in both. So the diff is like-for-like.

### Gone from the executable

| | PES 2014 | eFootball |
|---|---|---|
| `Jostle*` action classes | **9** | **0** |
| `*RetryWork` classes | ~22 | **0** |
| `constant::` namespace | 107 | 38 |
| dt270 contact-contest fields | n/a | none |

`RetryWork` is the quiet one: in PES 2014 an action that could not start this frame was queued
and retried, which is what made contact *persistent* rather than occasional.

### Intact

`collision::Human` / `Manager` / `Object`, `match::anime::action::Contact`, `Stagger`,
`CStaggerAnimeInfo`, `match::RagdollManager`, and the **entire referee stack** — `RefereeChief`,
`RefereeLinesman`, `CmdAddFoul`, `match::demo::FoulDemo`, `ObserverFoul`, `match::ai::Judge`,
`ObserverFallDownOrStagger`.

### What it spent the budget on instead

New actions are all presentation: `SeamlessPass`, `SeamlessDribble`, `SeamlessCornerKick`,
`SeamlessGoalKick`, `InplayDemo*`, `CarryBall`, ball persons, camera persons, coach.

## Where the animation actually lives

The paks split cleanly, which is easy to get wrong (I did, twice, before checking):

- **Cutscene/demo motion → Unreal paks.** A top-level `Animation/` root, 19,095 assets, all
  named `A_dml_*`: Goal 6120, Enter 2649, Ending 2326, ML 2302, **Foul 876**, PK 413.
- **In-play gameplay body motion → Fox pipeline**, `dt230_console_win.cpk` →
  `common/anime/FoxAnim/Body/body_anime_file0-9.mtar` (~99 MB).

Worth noting: the foul **cutscenes** are still multi-actor and synchronised —
`A_dml_foul_pk_card_w01` ships with `_judge` plus `_sub1.._sub4`, one locked clip per
surrounding player. eFootball still authors and plays bound multi-body animation. It just no
longer does it for *live* contact.

## The contact metadata is richer, not poorer

Decompressed sizes (eFootball wraps each table in WESYS + zlib; PES 2014 stores them raw):

| table | PES 2014 | eFootball | ratio |
|---|---|---|---|
| `HitData.bin` | 189,504 | 1,061,316 | **5.60x** |
| `CancelData.bin` | 9,904 | 68,952 | **6.96x** |
| `HoldData.bin` | 2,352 | 7,560 | **3.21x** |
| `RotData.bin` | 21,368 | 56,584 | 2.65x |
| `Animation.bin` | 74,788 | 156,420 | 2.09x |
| `DemoConnectData.bin` | 2,708 | 4,164 | 1.54x |
| **`PersonalizedData.bin`** | **24,972** | **236** | **0.01x** |

eFootball also *adds* `NoballFootprintInfo` (1.24 MB), `NoballFrameInfo` (677 KB),
`AnimationData` (254 KB), `BallData`, `FootType`, `PivotInfo`, `PivothitInfo`, `SubHitData`,
`JointPosInfo`, `KickData`, `CategoryData`, `DangerData`, plus a `Matching/` directory of 19
motion-matching tables and a `Parametricblendtable`.

Hand-gluing and cancel windows are **2.5x and 6x larger**. The machinery to show convincing
contact is all there and better than the game we are comparing against.

## Skeletons are near-identical

eFootball `FoxAnim/Body/CharacterAssets/body_anim_skel.ask` (WESYS+zlib), 22 bones. Arms and
legs match PES 2014 **bone-for-bone by name**: `sk_thigh/leg/foot_{l,r}`,
`sk_shoulder/upperarm/forearm/hand_{l,r}`. Only the spine differs — PES 2014
`sk_belly` / `sk_chest` / `sk_neck` vs eFootball `sk_spine_01..03` + `sk_cervicalspine_01..02`,
and the hip split into `sk_root_hip` + `dsk_hip`.

Redistributing 3 spine joints onto 5 is a routine retarget. As cross-game animation ports go,
this is about as favourable as it gets.

## Formats decoded (all verified)

PES 2014 ships both the binaries **and** `Mbinfo/Json/anim_infos.json`, a 7.1 MB plain-text dump
of the same data. That JSON is ground truth: every layout was derived from the binary and checked
against it. `python tools/mbinfo.py verify <pes2014 Mbinfo dir>` re-runs the proof.

```
Animation.bin  28B x 2671 records; geometry matched 64/64
HoldData.bin   16B records; record 0 offsets reproduce JSON: True
CancelData.bin frame=v>>12; first run [49, 108] vs JSON [49, 108]: True
VERIFY PASS
```

| table | PES 2014 | eFootball |
|---|---|---|
| `Animation.bin` | 28B: `u32 packed`, `u32`, `blend_z`, `blend_x`, `first_x`, `first_z`, `end_move_angle` | 36B (record size not yet pinned) |
| `HoldData.bin` | 16B: `u32 packed`, `offset_z/y/x` | **20B**: `u32 packed`, `u32 bone`, `offset_z/y/x` — 378 records |
| `CancelData.bin` | 4B: `frame = v >> 12`, low 12 bits = animation index | same rule applies |

Container: `ff2081` + `"WESYS"` + `u32 csize` + `u32 dsize` + zlib (eFootball); raw (PES 2014).

## The record → animation mapping (SOLVED 2026-09-19)

The packed word in `Animation.bin` carries **biased** bitfields, which is why a naive bitfield
search finds nothing:

```
anim_index  =  v & 0xFFF                  unique across all 2,671 records
end_frame   = ((v >> 12) & 0x1FF) + 8     67/67 positionally, then 2512/2512 after the join
blend_start =  (v >> 21) + 6              65/67 — width not fully settled
```

Record order is **not** JSON-key order (it holds for the first 67 records only). Records are
instead joined to animations **by their root-motion geometry**, which is effectively unique:
2,512 of 2,671 join to exactly one animation. The check that makes this trustworthy is that
`end_frame`, decoded independently from the packed word, then agrees with the joined animation
on **2512/2512** — two derivations confirming each other.

`CancelData` uses the same index space **offset by five**:

```
anim_index = (v & 0xFFF) + 5
frame      =  v >> 12
```

Verified at **1,636 animations agreeing, 0 disagreeing** (89 unresolved only because their
`Animation.bin` record did not join by geometry). Found by isolating animations with three or
more cancel frames — distinctive enough to be unambiguous — which gave a constant delta of
exactly 5 on 126 of 129 pairs.

`python tools/mbinfo.py names <dir> --grep js_` now resolves indices to names, and
`cancel` prints named cancel windows:

```
anim_index=2321  cancel_frames=[18, 32, 40]  stagger_headj_0_0_180
anim_index=1518  cancel_frames=[60]          js_highball_stagger_sub
```

## REVISION 2026-09-19: the contest was restructured, not deleted

The earlier reading — "Konami deleted the contest" — was too blunt. The `Jostle*` RTTI classes
really are gone, but **the jostle animations are not**. eFootball's exe carries **259 distinct
`js_` animation names**, more than twice PES 2014's 124.

What actually changed is the *shape* of the system, and it is measurable:

| | PES 2014 | eFootball |
|---|---|---|
| `js_` animations | 124 | **259** |
| `_main` (role-carrying) | 51 (41%) | 18 (7%) |
| `_sub` (role-carrying) | 49 (40%) | 16 (6%) |
| **both halves present (a true pair)** | **32 (26%)** | **6 (2%)** |
| single-actor (no role suffix) | 26 | **225 (87%)** |

And the families tell the same story:

- **PES 2014**: `highball` 43, `move` 42, `idle` 39 — evenly spread across aerial, running and
  standing *contests*.
- **eFootball**: `run` 101, `idle` 41, `slide` 17, `slant` 12, `dribbleslant` 10, `dribblerun` 6,
  `dribblestop` 5 — organised around **what the ball carrier is doing**.

The names make the new model explicit:
`js_dribblerun_1_1_000_sole_guard_back_main_act064`. Jostling is now a *variant of the dribble
animation set*, selected with `guard_back` (shielding) and an `act` id — which is exactly why the
separate `Jostle*` action classes and `PairAnime` are unnecessary, why the `Matching/`
motion-matching tables appeared, and why `HitData`/`CancelData` grew 5-7x.

**So the honest statement is:** eFootball models contact as something the **ball carrier does**
(shield, protect, guard back), where PES 2014 modelled it as something **two players do to each
other**. It has more contact animation than PES 2014 and almost none of it is two-sided. That,
not a missing animation library, is the difference being felt.

## eFootball `Animation.bin` — record size solved

`R = 36 bytes, 4,345 records` (PES 2014: 28 bytes, 2,671 records). Chosen over the other
divisors of 156,420 on three independent signals: highest index uniqueness, 3,998/4,000 rows
whose trailing words are plausible coordinate floats, and a sane `end_frame` range.

The index field **widened from 12 to 13 bits** — necessary, since 4,345 animations no longer fit
in 4,096. At 13 bits it yields **4,344 distinct values across 4,345 records**.

## Still not solved — do not build a writer yet

- **`blend_start` misses on 2 of 67**, and its decoded range runs past `end_frame` on 263
  records. The 11-bit width is probably bleeding into a neighbouring field.
- **The `bone` field is not the render skeleton index.** eFootball's 378 hold records use only
  three values (11 x193, 7 x184, 0 x1). Against the 22-bone list that reads "cervicalspine" and
  "foot_r", which is implausible for gripping. It is a separate, smaller enum — unidentified.
- **eFootball index -> name is still open.** The names exist — the exe holds a pool of 11,096
  null-terminated animation names (span `0x6a7a4e4..0x6bb3510`) — but the pool is **not** in
  index order: inter-string gaps vary (0-6 bytes, no dominant stride) and body, GK, face and mob
  names are interleaved. Position is therefore not the index. Mapping them needs the name-pointer
  table the exe indexes by animation id, which means disassembly (`tools/exe_map.py`), not
  pattern matching. Nothing in `dt230` carries the names: the Mbinfo and AnimeTable binaries hold
  only bone names, and `body_anime_file0.mtar` yields 4 junk strings.
- `MatchAnimeDefinedatatable.bin` does not unwrap as WESYS+zlib.
- The shipped `match/ai/*.json` sit at a different path than the source path the exe records for
  the compiled constants, and some values disagree with the compiled `.o`. Treat the JSON as
  authoritative for **field names and semantics**, the compiled section for **live values**.

## What this means for feasibility

Ranked by what the evidence actually supports:

1. **Tune existing contact metadata — achievable now.** `HoldData`, `HitData`, `CancelData`,
   `DemoConnectData` are all live and readable. Longer hold windows, different cancel frames,
   changed contact geometry — no animation authoring, no exe patching. Blocked only on solving
   the record→animation mapping above.
2. **The foul/referee layer — achievable, and the best fit for the original goal.** Architecture
   is unchanged from PES 2014. The referee still observes and judges rather than being triggered.
3. **Replace existing animations — plausible.** Same engine family, same format, near-identical
   skeleton. Needs the `.mtar` archive format cracked.
4. **Add new animations — hard.** Fixed-row tables the exe indexes; growing them is the same
   class of constraint that stops CPK patching from adding files.
5. **Re-add the contest — the wall.** New code in a Denuvo-protected binary to detect a contest,
   pick a matched pair, bind them, resolve over N frames. Eased slightly by the fact that bound
   multi-actor playback demonstrably still works (the foul cutscenes use it) — so it is wiring,
   not invention.

The blunt summary: **eFootball kept every tool for showing contact and threw away the part that
decides it.** It is not a system that cannot do this. It is a system that has been told not to.

## Corrections made while producing this

Recorded because each one changed the conclusion:

- "eFootball's animations are in Unreal IoStore with no hit/hold/cancel equivalent" — **wrong**.
  Gameplay motion is Fox, and the metadata tables exist and are larger.
- "192 animation assets, all crowd" — **wrong**; that was one asset root, grepped from a file
  still being written. There are 19,095, and they are cutscene motion.
- PES 2014 `hold_bone` was read as dominated by hands under the 19-bone list; eFootball's
  distribution shows the field is a separate enum, so neither reading should be asserted.
