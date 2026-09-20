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

### 2. The ability to trigger runs (tap LB = run, tap RB = overlap/underlap) — ANSWERED 2026-09-19
**Both open risks are now settled, and one of them kills the LB half of the plan.** Full decode in
[registry-pad-command-channel.md](registry-pad-command-channel.md) (683 lines).

- **Tap/hold discrimination EXISTS and is exact.** Pattern-node kind 4, window `B = (int)(0.08*FPS+0.5)`
  — 5 at 60 fps, i.e. a tap is **≤4 frames / ~67 ms**, computed from the live frame rate. Nothing new
  has to be written to *detect* a tap.
- **LB IS NOT FREE — this corrects the premise above.** LB-alone is `ThinkUnitCursorChange` and it
  fires on the **press edge**, not as a hold. An LB tap fires a cursor change on frame 0, before a tap
  could possibly be distinguished. "Tap LB = trigger run" **collides unconditionally**.
- **RB IS free on the ball.** No ThinkUnit in the attack bank uses logical 21; the only consumers are
  chains that also require a stick or RT state. An RB-alone tap is unclaimed.
- **`ThinkUnitPassAndGo::vf17` is gated on RT + RB**, not L1+A / R1+A as this item said, and it is a
  *condition*, not a behaviour producer.
- **The hook is NOT code.** `PassAndGo`'s two pattern chains sit at `0x1486b88d0` (2 x 40 B) and
  `0x1486b8930` (3 x 40 B) in zero-at-load data, filled once by a TLS-guarded static initialiser.
  After the first evaluation they are plain writable memory: retarget the gesture by changing
  `node[0].mask` or `node[1].kind` — **no instruction patched, no cave, no new Denuvo surface**,
  through the existing `tools/live_patch.py` runtime-write path. Constraints to preserve are listed
  in that chapter's §14.12 (write only after the first `vf17`; keep `+0x20`/`+0x24 = -1.0` and
  `+0x10 = 0`; `count` is a caller literal and cannot be shortened by data alone).

**So: build it on RB, not LB.** That is the single most shovel-ready item in this file.

### 3. A freer ball — ricochets, poor touches, realistic pass and shot error
Partly built already (kick-error model, `bobble-pitch`, first-touch work). The owner's standing
ruling: **do not produce indiscriminate bad touches — create the conditions for looseness.** Keep
`ballControlRate` below 1.0, because at exactly 1.0 a BC99 player is mathematically incapable of a
bad touch. **CONFIRMED FROM THE GAME 2026-09-20: the field is `trap.ballControlRate` and stock is
exactly `1.0`** (`dt270_objects.py get trap ballControlRate` = 1 on the installed *and* the PRISTINE
pack), so the shipped game sits on the saturation this ruling forbids and **lowering the field is
the action**, not protecting it. The attribute it scales is **Tight Possession `0x19`**, not Ball
Control `0x18`, which the trap family never reads. `anime-actions.md` and
`anime-keeper-and-first-touch.md` both said "stock 0.80" — that was *our* `loose-realism-v1.json`
value read from a stale dump; both are corrected.
**Open and unproven, and it gates "ricochets":** does the ball deflect off *non-tackling* players at
all? The ball's own integrator `0x14408d0f0` reaches no collision system and every dt270 bounce
array is ground-only — but that is a **one-sided** negative. Limb collision parts exist (21-slot
array at `player+0x2f18`, per-frame physics filter groups via `0x144fa58d0`) and, found 2026-09-20,
so does a **per-player `collision::Human` inside `match::AnimeCollision`** (vftable `0x146b6fb48`,
factory `0x143ff2210`, 3 call sites, attached at `AnimePlayer+0x47a8`). `anime-actions.md` claimed
`collision::Human` had zero callers image-wide; it does not, and that object is the next thing to
open.

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
**Blocker to clear first — RESTATED 2026-09-19, and it is much smaller than this said.** The motion
assets are **not hashed**. The image carries **68 plaintext asset paths** under
`cpk_dat/common/anime/`, and the file this item needs is named: **`Mbinfo/bin/CancelData.bin`** (the
plan's probe was commissioned to "locate MbInfoManager's keyframe table" — `Mbinfo` *is* MbInfo).
Alongside it: `AnimeTable/bin/RiseTypeFrameData.bin` (getting up, by frame),
`FHSequence/bin/Hitframes.bin`, `Mbinfo/bin/HitData.bin` / `SubHitData.bin` / `HoldData.bin` /
`DangerData.bin`. The 17 `ParsedJson*` classes say each `.bin` is a **compiled JSON object** — the
same shape as dt270, which we have already fully decoded with real field names.
The **actual** blocker is that none of the 68 paths appears in plaintext in any of the 22 CPKs on
disk, so reading them needs a **CPK reader — and ours was removed in the collaborator merge**
(`cpkmakec` and `cricodecs` are gone). See [anime-actions.md](anime-actions.md).
So: get a CPK reader, not break a hash. That turns every spec here from guessed to computed and
gives the lockout's actual length in seconds.

> **CLOSED 2026-09-20 — [anime-actions.md](anime-actions.md).** No CPK reader is needed either. The
> tables are extracted, decoded and named: `idx = v & 0x1FFF`, `frame = (((v>>13)&0x3FF)+2)*2` at
> 1/60 s, joined to the exe's 7,883-entry name table at `0x148027310`. Every effect size in the seven
> contact specs is now computed — see that chapter's § Tunables. `dt230_console_win.cpk` stores each
> WESYS container **verbatim** at a unique offset (CancelData at `0xb5bf800`), so `ml_deploy.py`'s
> in-place byte patch reaches them. Two things replace the old blocker: the repack must use **zopfli**
> (Konami's deflate beats zlib -9) with only 5–19 bytes of headroom — which changes sign with the
> record set and the delta — that a tool must *measure and
> refuse*, and it is **untested** whether the WESYS reader tolerates trailing bytes after the deflate
> final block. Also: the premise that killed these specs is inverted — there are **69** stagger
> motions, **all** with at least one cancel key, and the 44 single-key ones are precisely why
> `contact-dribble-cancel-early.json` is not a placebo. And `.bin` files are fixed-size binary
> records, **not** compiled JSON.
`falls-slide-tackle-contact.json` is the one unapplied falls pack that genuinely puts more bodies on
the floor and touches no lockout — safe to test alongside anything.

---

## The subsystem map — **COMPLETE (2026-09-20)**

**Every row below is DONE.** Set pieces, the last one, closed on 2026-09-20 with
[set-pieces.md](set-pieces.md), and nothing in this table is outstanding. The map is **eight
chapters — `match-ai-decoded.md`, `ball-carrier-brain.md`, `player-executors.md`,
`registry-blackboard.md`, `anime-actions.md`, `pad-input.md`, `goalkeeper.md`, `set-pieces.md` —
12,249 lines** (plus the probe chapters they consolidate). From here the project is tuning and
building, not mapping. **Item 7 (the dt270 residue) also closed on 2026-09-20** —
[dt270-residue.md](dt270-residue.md) — so the only map-shaped work left is the catalogue
regeneration noted under the table.

Each subsystem produced a chapter in the shape of [match-ai-decoded.md](match-ai-decoded.md): the
machine as prose with addresses, a tunables table with route and pool-cell sharer counts, plus
explicit *Corrections* and *Negatives* sections.

| # | subsystem | classes | state |
|---|---|---|---|
| - | `match::ai` — off-ball movement | 26 | DONE — [match-ai-decoded.md](match-ai-decoded.md) |
| - | `match::referee` — fouls | 5 | DONE (in the same chapter) |
| 1 | `match::ai::bp` — the ball carrier | 65 | **DONE** — [ball-carrier-brain.md](ball-carrier-brain.md) (1,658 lines). 9 probes/verifiers + 2 repair rounds; re-verify clean of critical/major. 65-row class-status table; Corrections section records every wrong turn. |
| 2 | `match::player` — the executors (run geometry, marking, kicks, pass reception, ~30 keeper actions) | 109 | **DONE** — [player-executors.md](player-executors.md). Architecture pass + 4 behaviour probes (runs/cross-role, defence, kicks/receivers, keepers), every load-bearing contradiction re-derived from PRISTINE for the write-up. Full **113-row** class-status table (109 top-level classes + 4 nested `PassGetRouteBallAdjust::*`). **Headline correction: slot 20 is NOT the movement-target emitter** — it is a fixed-radius *steering point*; the destination is slot 4's (or slot 18's for the 21 classes that override it), which relocates the CB standoff to a ball-position ramp in `0x143e1bfb0` and makes our `ActionMark::vf20` 45°→90° patch a likely placebo. Answers: run geometry is **role-blind across the 15 path builders and 14 slot-20 emitters tested** (2,820 emulated comparisons) so widening selector gates is safe **for those** — the seven second-level handlers were never emulated and ChanceSpaceRun **kind 1 is provably role-sensitive** (−5.0 vs −6.0 in `0x144268630`); runs are pinned to `line + 10 m` with **no timing term**; the offside trap steps up through `vf4` relative to the player's own x; a loose ball **is** contested with **no priority term**; GK save quality lives in the anime layer with Reach's **output** floored at 50 and Reflexes' at 63 (inline 52/65, then ×0.98 below 90); and **dt270 reaches the executors at depth 0** through `passget` (idx `0x6c`, 26 read fields in the `PassGetRoute*` methods) and `basePosition` — a data-file tuning surface with no exe patch. Also corrects match-ai-decoded.md (attr `0x17` = 11+ sites not 3; difficulty row `0x14` quoted from our own patched image) and ball-carrier-brain.md (`0x14561fe20` **is** kick slot 2 in 33/34 vtables; the bp band **does** read `teamAI+0x8f4c`). Repaired 2026-09-19 after three adversarial reviews (patch inventory, slot-20 census, marking ramp, funclet range, dt270 census, attribute names, RNG in `ActionShoot`, several Tunables sites) — see § Corrections → Repair pass. Still open: the action-id → executor binding, the seven L2 run sub-modes, `0x144261f10`'s run-phase state machine, the marking-mode writer, and who consumes the output tuple (the real animation seam). |
| 3 | `match::registry` — the shared-state BLACKBOARD (218 RTTI names = **45 data records** × accessor templates: UTeamAIInfo, UOrderInfo, UAnalyzeInfo, UPlayerInfo/Move, URandomInfo, UPadInput→UCommandOutput, UMatchEnv…) | 45 records | **DONE** — [registry-blackboard.md](registry-blackboard.md) (1,800 lines). Skeleton + 4 probes (tactics landing map, inventory/seams, random bundle & lifecycle, pad→command), every load-bearing claim re-read from PRISTINE with capstone for the write-up and all 12 tunable constants put through `exe_census.py cell --all` (all shared, counts in the chapter). **Complete record table: all 45 records sized, 4 skeleton names shown to be non-records.** Access discipline fully decoded — `Copy`/`Pointer` **is** a double buffer, `ScopedWAndC` = **Write-And-Commit** (`0x145340a10` publishes back→front), and there is **no lock anywhere** (`ScopedRead`/`Write` release through `0x140c83910` = `ret`). **Headline result is a subtraction:** `team+0xb3c4` — the carrier chapter's "largest single on-ball lever" — is the CPU's **transient direct-play directive**, set/cleared every think tick by `0x143d7c5b0` (and it *does* have writers, contra the skeleton), while `team+0xb44d` is merely `(attackLevel >= 4)`; **both come off the tunable list.** The attack level itself is AI-driven by default (setting `+0xb454` = 5, converter `0x143d04830`). **Corrects ball-carrier-brain.md's "no tactical-instruction channel exists"**: `0x1442e1200` reads `UAnalyzeInfo+0x273e8`/`+0x27490` as 4 `(kind,value)` slots per team at **271 sites**, six of them in the carrier band — but **no writer exists**, so it is a named target, not yet a lever; the second channel, `UTeamAIInfo+0x8078` (two sets, a 0–5 approach code, seven instruction bytes), is **not traced to any file** and that is the half returned unfinished. Also: `matchInfo`/`matchWork` = **UAnalyzeInfo**, not UMatchInfo; **no registry access anywhere in `match::ai`/`bp`/`player`** (0 of 1,431 sites, both controls) because everything reads cached raw pointers off the live `UModeInfo`-owned records; **dt270 never enters the blackboard**; `URandomInfo` is 28 B, the **seed store**, updater `0x1453dea17` — with a flagged risk that `+0x08`, the carrier's per-possession random, may have **no writer at all** (one live read at `0x145653e5f` settles it). **pad→command decoded**: `UPadInput` = 24 pad slots × a 100-frame ring, `UCommandInfo` is netcode-only, and for realism item 2 — **tap/hold discrimination exists and is exact** (kind-4 node, ≤4 frames ≈ 67 ms at 60 fps), **LB is NOT free** (Cursor Change fires on the press edge), **RB is**, and the hook is a runtime write to the pattern nodes at `0x1486b88d0`/`0x1486b8930` with no code patch. Still open: the instruction-table writer, the `+0x8078` origin, the `UOrderInfo` slot record, who calls the commit, and per-frame order (**not recoverable from the registry** — records bind once per match). |
| 4 | `match::anime` — animation gating, contact, technique, first touch, GK saves | 131 (106 `action::`) | **DONE** — [anime-actions.md](anime-actions.md) (1,559 lines). Skeleton + 4 probes (motion assets & cancel data, the mover & the 29-slot contract, contact/stagger/falling, GK saves & first touch), every load-bearing claim re-derived from PRISTINE or from the shipped `dt230` data for the write-up. Full **135-row** class-status table (131 `match::anime` + the three `match::MbInfo*` classes and `match::AnimeCollision`, all of which sit in `match::`). **Headline: the post-tackle lockout is measured, in seconds.** `MbInfoManager` holds 7,883 records of `0x1f8` bytes = **21 `std::vector<Event*>` channels**, one per the 21 `Mbinfo/bin/*.bin` paths in literal-pool order (ch 3 `AnimationData` = end frames, ch 5 `CancelData` = the cancel keys), and `canCancel` is literally `currentFrame >= keyFrame`. **Three probes produced three decode rules and the exe settles it** (`0x143e99e20`: `shr 0xd / and 0x3ff / add 2 / cvtdq2ps / addss xmm1,xmm1`): `idx = v & 0x1FFF`, `frame = (((v>>13)&0x3FF)+2)*2` at 1/60 s — **every MbInfo frame field is stored on a 30 fps grid and doubled on read**, which reconciles the frame-rate argument. Joined to the exe's own **7,883-entry animation-name table at `0x148027310`**, every stagger, tackle, slide, fall and jostle now has a name, an end frame and its cancel frames (`build/anime_motion_tables.json`). In-play staggers: first cancel key **0.200 / 0.450 / 4.033 s** inside a ~0.98 s motion. **Corrects `player-executors.md`'s "10 of 11 staggers have <=1 cancel key, so the obvious fix is a placebo"**: there are **69**, **all 69** have a key, and the 44 single-key ones are exactly *why* the fix works — `Stagger::vf14 0x143f00de0` routes request kind 4 (Dribble) to the animation **END** when a motion has <=1 key, so the ball carrier alone is locked a median **1.000 s** against everyone else's 0.600 s. A slide tackler is un-knockable for **86 %** of his own slide; a fallen player for a median 2.800 s. **`player-executors.md` OPEN 7 CLOSES and inverts**: the executor's output is one struct at `playerWork+0x8b8` (target `+0x20`, gait `+0x5c`, the `0x4ec` path embedded at `+0x68`, **plus a speed float at `+0x560` the chapter missed**) and it crosses **by pointer as argument 3** of the anime contract (base slots 25/26 `0x143ef6190`/`0x143ef5610`) — which is why two call closures from the executor side found nothing. Realism item 4's surface confirmed: dt270 `moveMatching.RouteParameter[14]`, stride 56, **11 of 14 fields live-read** (`accacc`/`poseWeight`/`routeWeight` are dead), `acc`/`dec` as multiplicands — **but one global blob, no per-player term, and only two aimable elements**: `0x143ec3ed0` is pinned to element 5 by its only call site and `0x143fef370` to element 0; shipped `rotSpeed` is 7.0 in all 14 rows and `decRotSpeed` 0.0 in all 14. **Item 5's CPK-reader blocker is RETIRED**: `dt230_console_win.cpk` stores each WESYS container verbatim (CancelData located at `0xb5bf800`, one occurrence, full byte match), so an in-place byte overwrite reaches them — **but the PACK half is unbuilt**: `pack_wesys_container` supports only key nibbles 1/2 (dt230 is 0), always writes flag `0x83` and encrypts (dt230 is `0x81`, plain), and takes only a zlib level; and `ml_deploy.py` itself uses `cricodecs.cpk.load()` and is hardcoded to dt200/`PlayerAssignment.bin`. Konami's deflate also beats zlib -9 (61,433 shipped vs 61,542) so the repack needs **zopfli**, and 5–19 bytes of headroom that must be measured **per record-set and per delta** — a uniform +12 frames across the contact family fits (+8) while +6 across the same set overflows (−13). Also corrects `pes2014-vs-efootball-contact.md` (`Jostle` 9→**1**, not 0; `*RetryWork` 52→**78**, not 0 — they are `struct`s with `.?AU` RTTI and no vftable; index→name **solved**) and `pes2014-vs-efootball-contact.md`'s `CancelData` row. **(Its claimed correction to `match-ai-decoded.md` — "the 40 outside-the-box foul threshold is our own patch at 36" — is WITHDRAWN: `0x143d8629f` is `mov ecx,0x28` = 40 in PRISTINE and in the installed image, `phys-whistle-threshold.json` reports `pristine`, and 40 is the game's.)** Negatives: zero CPU difficulty, zero dt270 and zero in-body RNG in the whole `goal_keeper::` family; **no ricochet path was found from the ball side, but that negative is one-sided** — `collision::Human` is NOT dead, it is newed per player by `0x143ff2210` (`match::AnimeCollision`, 3 call sites) and attached at `AnimePlayer+0x47a8`, and that object was never opened. Still open: the poster of contact event kind `0xe` (so "more contact ⇒ more fouls" is unproven at the event), the `vf30` motion selectors that decide *which* fall plays, `Jostle`'s body, `HitData.bin`'s record size, and a WESYS **writer** for dt230 (key nibble 0, flag `0x81`, unencrypted, zopfli), which no existing tool can produce. **Repaired 2026-09-20 after adversarial review** — see that chapter's R1–R19 corrections table. |
| - | `match::pad` — the input channel (pad ring, button map, ThinkUnits, the pattern engine, control source, input→power, cursor) | 73 | **DONE** — [pad-input.md](pad-input.md). Consolidates the four probe outputs ([registry-pad-command-channel.md](registry-pad-command-channel.md), [pad-node-kinds-and-unit-modes.md](pad-node-kinds-and-unit-modes.md), [pad-power-and-cursor.md](pad-power-and-cursor.md), [control-source-and-human-vs-cpu.md](control-source-and-human-vs-cpu.md)) into one chapter; full **73-row** class-status table (72 factory-built `ThinkUnit`s + `ThinkUnitBase`), Tunables with `exe_census` sharer counts, Corrections and Negatives. **Headline for item 2: the trigger-run binding already ships** — `ThinkUnitPassAndGo` chain A fires on a ≤5-frame tap of **logical 21** while **logical 19** is not held (emulated end to end on the game's own evaluator) and `vf12` emits command **`0x47`**; *"logical 21 = RB, 19 = RT"* is the hardware map in that chapter's § 2 and is **[c]**, pinned by the in-game control screen and XInput axis order rather than by disassembly, so one in-game press would upgrade the whole spec. The open question is whether `0x47`'s *effect* is the wanted run, answerable only in-game; three data-only retunes are specified byte-for-byte and **not applied**. **Headline correction: `byte[UMatchInfo+0x41f6+idx]` is the human-control-allocation byte** (`rank ≤ perTeamCount`, cursor player forced to rank 0 **but only while `UMatchInfo+0x3308 ∈ {2,3}`**, emulated on `0x144308db0`), not "the player is on the ball" — and `match::ai::bp` activation reads it, so **bp runs only for players inside that allocation** [b]. *"…and the human's cursor player is therefore always one of them"* is **[c]**, not proven: in open play the cursor override does not fire, so coverage falls back to `rank ≤ count` and a low-ranked cursor player may be driving a carrier whose bp is off. That is `ball-carrier-brain.md` OPEN 8's mechanism half closed, not the whole question. **And the pad layer is NOT dt270-free** (an earlier draft of the chapter said it was): `trap.stopTrap.use` / `.inputTime` gate and size `ThinkUnitTrapStop::vf8` (`0x1440e884b`, `0x1440e887c`) and `grounderpass.search.searchMinDist` is read at `0x1440d64b7` — a **tier-0 tuning surface with no memory write and no exe patch at all**. Also: the "15-way control-source jump table" has **three** targets, not fifteen; node kinds **1 and 3 were swapped** in every prior write-up (1 = press, 3 = release) and kinds 8/9 are run tests, not level tests — they need `start+1` consecutive contrary-free frames starting at index 0 **or index 1**, so only the newest frame may be contrary and the scan reaches index `start+1`; the gesture table is **16 rows in three tables**, is the **feint/skill-move** table, and needs a **second evaluator** (`0x14430fcc0`) for kinds 11/12/13; `+0x10` is the command **lifecycle class** (0 free-running … 4 latched-cancellable/charged-kick), the press machine is `+0x1c`; power is a float gauge at `unit+0x20` filling in 15 frames (shot) / 18 (pass) at 60 fps and crossing the wire as **7 bits**, so *time* to full is frame-rate independent but *resolution* is not; and the pad→executor hand-off is the record decoder **`0x144317cd0`** (closes `player-executors.md`'s open item). Negatives: **the CPU gets no pad input at all** (`CommandPlayer::vf2` is a pure clear), so every pad lever reaches only players on a hardware pad; **no assistance setting reaches the command layer**; **no human/CPU asymmetry in the kick-error model** (depth-4 raw-target closure, **482** functions, three positive + one negative control; the old "139" did not reproduce and is withdrawn) — `f` is a pure curve on the kicker's own attribute, 0.10 at 60 → 0.90 at 90. Still open: the runtime per-team control counts `X+0x3c`/`X+0x40` (the one link between "bp is gated on that byte" [b] and "bp never runs for the CPU" [c] — highest-value item in the map), how much the sub-0.10-stick aim assist corrects, which player LB picks, where the assist settings land, the individual meaning of ControlModes 1..9, the second (undecoded) acceptance path into the human-control allocation (`0x1442c4430`), and whether any other pad unit reads dt270. **Repaired 2026-09-20 after three adversarial reviews** — 24 corrections in that chapter's § 14.A, including two that would have produced a broken write (the power-quantisation re-aim address was one instruction too high; the prescribed pass-gauge re-aim names an instruction with no memory operand) and a rewritten Tunables route legend with **three risk tiers** (`.text` RW / `.tls$` R / `.xcode` RX — the last being the class this project's own `live_patch.py` warns crashes the game). |
| 5 | goalkeepers | 25 + 15 | **DONE** — [goalkeeper.md](goalkeeper.md), the synthesis chapter stitching subsystem 2 (**25** `ActionKeeper*` executors, not ~30) and subsystem 3 (**15** `goal_keeper::` vtables in three contracts — 50 / 33 / 29 slots — not 14), plus the probe decode in [goalkeeping.md](goalkeeping.md) (positioning, distribution, one-on-ones, set pieces, motion tables). Full class-status tables for both halves, Tunables with sharer counts, **36 corrections** (12 of them repairs to its own first draft), 18 negatives. **Headline, as repaired: on the ONE route that has been followed end to end you cannot author a bad goalkeeper — block-wide it is NOT YET KNOWN.** `0x144032870` picks exactly one of the four GK attributes, floors Reach at an **output 50** and Reflexes at **63** (inline 52/65, then ×0.98 below 90) and remaps an easy catch (< 50 km/h, `max(Catching,Reflexes,Reach)`) into 73..89. That integer then goes to **four** consumers, not one: `0x143f31470` turns it into a multiplier of **0.900–1.295** (worst keeper **77–92 %** of the best, **92 % on a routine catch**, full 40..99 table a-emulated from PRISTINE), but `0x14402a630` applies a **wider** transfer (span 90, cap 130, ≥ 8 arms — one measured at **52 %** worst-to-best), `0x143f35ed0` a 0.4..1.0 vector scale, and `0x1440374b0` a **reaction-frame delay** `(120−q)/16` from which Block is exempt; the last three are undecoded. **Almost nothing rolls a die**: no LCG reaches the selector, any of the four consumers, `canStart` or `vf35` (all verified **to exhaustion**) — but the save body `0x143f46370` writes a random displacement of up to **0.20 m** into `player+0x442c`, read only inside the undecoded `0x143f35ed0`, and five of six `vf30` gates reach an LCG at **depth 5–6** (the draft's "no RNG at any depth" was bounded at depth 4). Controls shown on every row (positive fires at depth 2 in 117 fns, 33,116 unbounded; the negative is valid **only bounded** — unbounded it explores 33,123 and reaches all five LCG entries at depth 12, and four of those five have **no `.pdata` record**, which silently breaks root-keyed call graphs). **Two real per-keeper cliffs, both new**: `goal_keeper::Deflect::vf35` returns false unless **GK Reach ≥ 85** (the only slot-35 override, uncompressed, one caller) and **GK Awareness below 44 is dead** — it buys an anticipation window of 0 → 15 frames with onset 0.500 s → 0.170 s, which is what that attribute actually does, not the 0.5 m error. **Keeper distribution is not the carrier brain**: it runs in `0x145655430`, selected by the `teamObj+0x42b8` role-code fork, which *explains* ball-carrier-brain.md's dead `GKDribble`/`GKPassShort`/`GKPassLong`. The penalty dive is a half-plane read of a 9-bit aim field (raw 0..511, units unproven) on a descriptor reached **through a pointer at `rec+0x20`** — ±5 m z step, **not** a coin flip — though who allocates and writes that descriptor is untraced, and that is what decides whether the CPU keeper "cheats". Dive lockout measured in seconds for the first time and then **corrected**: under the **proven** `CancelData` rule `(((v>>13)&0x3FF)+2)·2` a `gkdeflect` first-cancels at a median **0.850 s** and `gkrise` at **1.083 s** (the draft printed 0.392 / 0.508 — raw-rule seconds, half the true value, because `tools/mbinfo_ef.py::cancel_records()` still drops the mask, bias and doubling); 41 % of 1,250 gk animations are uncancellable, and under the proven rule **133 of 640 (21 %)** have their first key at or past the motion end. A dive commits ~**6 %** longer than a **slide** tackle (the draft's "~30 %" divided by the *standing* tackle median while naming the slide). Negatives: **zero dt270** (20 `gk*` fields in `basePosition`, 6 read, all six readers in the *outfield* goal-kick shape layer), zero CPU difficulty, no attribute in the flat 3.5 m catch envelope, no ability gate on coming out or distributing, and **no pad ThinkUnit for any save** — saves are unbindable. Corrects player-executors.md ×10 (incl. `ActionKeeperPress`'s come-out decision is **vf6**, not vf5; `ActionKeeperCoaching` is the goal-kick gesture, **not** the wall; `ActionKeeperCatching` requests `0x46` = **Deflect**) and anime-keeper-and-first-touch.md ×6 (slot 30 is inherited by Deflect and SnapUnder — five distinct bodies across the six classes — while slot 29 *is* overridden by all six but is only four distinct bodies; `0x1ecb` is an exclusive bound, so the id-space caveat retires; and **`SavingBase::vf47`'s `0xb9c` = `referee_game_end_…` is NOT a proven dead placeholder** — Deflect, Punch and SnapUnder all **inherit** that slot, so it is their live default; that chapter's "every class overrides" is the source of the error). Still open: **name flag bits `0x46`/`0x12`/`0x14`** from `all.str` in original order (highest value — three proven reads become three named player-data levers), the downstream of `PreSaving` mode 1 (`0x143f28c10`, the best remaining shot at real per-keeper differentiation), who writes the penalty aim descriptor, the four private distribution target-finders, **the three undecoded save-quality consumers** (`0x14402a630`, `0x143f35ed0` — which also holds the unexplained GK Reach read *and* the reader of the random `player+0x442c`, and `0x1440374b0`), **whether `vf47` is called for the three classes that inherit it**, and **where the save type is chosen — NOT LOCATED and bounded** (the `0x143f2b590` look-alike is the set-and-shuffle footwork chooser, recorded in full so the next pass does not repeat it). |
| 6 | set pieces | spread across all six | **DONE** — [set-pieces.md](set-pieces.md), the stitching chapter: `ThinkUnitSetPlay` is a **six-way jump table on `UMatchInfo+0x34a0`** (`vf2 = 0x1456b0060`, table `0x1456b058c`), not the one arm `ball-carrier-brain.md` labelled "SetPlay"; the wall is two consumer executors and a pre-written command cell; the referee's placement is a standoff provider/enforcer pair; `positionPK_{2,3,4,5}` is **located and live**, fetched by name via `sprintf("positionPK_%d", backLineCount)`. **Headline: the decision side reaches ZERO RNG but the LAUNCH side does not** — no dead ball touches the open-play kick builder `0x14401a900` (one caller, `Kick::vf8`); every Restart class runs `Restart::vf8 0x143f05150` instead, which makes ten stochastic draws and gates a re-draw on **Set Piece Taking** (50 % re-draw at rating 63, 0.58 % at 99, emulated). Two probe headlines were overturned in the write-up: the 9.15 m lever is pool cell `0x146b18170` read at `0x143d48c26`, **not** the inline `0x1442ec757` (which feeds only the pitch-zone classifier), and "positionPK is unlocated" was an artefact of a constant-index liveness sweep missing a name-built fetch. Corrects five finished chapters. |

Then **regenerate `build/gameplay-catalog.html` subsystem-first** rather than field-first, so
"can a striker make a diagonal run" is a lookup. The current catalogue is dated 2026-08-23 and
predates everything learned since.

### 7. After all six: resolve the 5,362 UNLOCATED dt270 fields — **DONE 2026-09-20**

> **CLOSED 2026-09-20 — [dt270-residue.md](dt270-residue.md).** All 245 objects / 21,977 fields are
> accounted for, and **nothing in the residue is a gameplay lever**.
>
> | | objects | fields |
> |---|---|---|
> | **object-level bound** — index→object binding proven | **128** | **18,154** |
> | **family-level bound** — fetch site, reader and struct type pinned; which object an index selects is not | **106** | **3,700** |
> | **unbound** — no fetch path found | **11** | **123** |
>
> **The shrink this item predicted did not happen, and could not have.** A re-run of
> `tools/dt270_liveness.py` against PRISTINE is *bit-identical* to the 2026-09-17 catalogue — 0 of
> 21,977 field statuses changed — because the tool's only input is the exe. Chapters are prose. The
> shrink came from this pass, by hand: **5,265 of the 5,362 "unlocated" fields (97.7 %) are now bound**
> to one of five fetch mechanisms the tool does not model (a name table `0x1475d1850`; three static
> (modeId→index) tables `0x148081340` / `0x148081460` / `0x148080860`; an index cached in a runtime
> object member; a guarded `lea edx,[reg+K]`; and — the hard floor — a name supplied by game data
> through `0x145348e50`, which no static method can reach).
>
> **Corrected headline numbers.** Four objects the catalogue calls *located* are not: get site
> `0x143fef479` is `lea edx,[rcx+0x6a]` with `rcx` provably 0 (`mov ecx,2` + a loop exiting on 0), so
> its index is `0x6a` = `grounderpass` alone, yet eight objects at `0x64..0x6b` claim it.
> `PathToGlory9`, `pathToGloryNone`, `pathToGlorySetting` and `ballplayer` have no other site, so
> **subtract 8 `read` and 178 `unread` before quoting the catalogue**: 101 objects located by constant
> index, **12,000 genuine reads, 4,429 genuine unreads**.
>
> **What the four categories mean — the caveat sheet is § *What the four liveness categories actually
> mean*, and it is the most useful part of that chapter.** In short: `read` means a load happens, not
> that the value matters (only **3.1 %** of read fields are consumed in place; the
> `forceDashDist` pair is a *correlated-branch* case, not an unconditional overwrite, and
> **`forceDashDistOffence` is fully live**). `unread` survived an independent completeness audit —
> 663 candidate misses generated, **199 fields at 343 sites hand-traced, zero overturned** — and
> 4,478 of 4,607 sit in objects where nothing escaped the analysis. **`cached: 0` means the pass was
> never run** (`cached_offsets: []`); re-running it reaches 21 GB and dies. `unlocated` never was a
> liveness verdict. And `confidence: low` is almost always an artefact: **828 of 835** such fields are
> `movsd` packed loads of two adjacent floats.
>
> **The ~11 gameplay objects this item reserved: the count survives, the membership does not, and none
> is a mechanic.** `animeAging{Kick,Trap,Dribble,FreeMove}` (47 fields) is a QA **aging/soak-test
> rig** — `enableOutputCsv`, `retryMax 128`, Start/Add/Num angle grids, `zz_dummy` — almost certainly
> the offline tool that generates the animation-matching tables; **"ageing" is not animation ageing**
> and it does not belong with the anime chapter. `userPlayTendencyTest` (22) is a versioned fixture
> (`version "v4.0"`) that nothing fetches — but its 21 weighted categories (`setPlayGoal 2000`,
> `border 1000`, `offSidetrap 1000`, `earyCross 600`, `teamMateMoving 600` …) are the best evidence
> yet that a live user-play model was designed; **whether one exists is NOT PROVEN either way**.
> `studiumPositionData` (28) is the `demoarea` family's null entry and `stadiumCustomParameterData` (3)
> is six PK-demo pitchside props — **stadium furniture, and the pitch dimensions are NOT dt270** (they
> are registry record `[[0x1486bd888]+0x63d0]`). `positionPK_2..5` + `positionNone` (20) were already
> decoded in [set-pieces.md](set-pieces.md) and are **live** — they leave this list. Joining it:
> `mlScreenShot` (19, a Master-League leftover, and **not useful to Phase 3**), the three developer
> mode-launcher `*Setting` singletons (9), and **`ballplayer` (23)**.
>
> **The one follow-up worth doing:** `ballplayer` (`constant/player/ballplayer.json`, `TurnData[1440]`
> + `Feint` + `touch0[7]`) is a gameplay-shaped dribble-turn table with **no fetch path**, and its
> four catalogued `read` fields come from the defective site above. Do not tune it; probe it.
>
> That chapter also corrects **set-pieces.md** (the positionPK name resolver is `0x145349470`, not
> `0x1453494e0`, whose bool return is discarded; and `positionNone` **is** reachable — it is the
> resolver's not-found default, though its "inert, don't bother" data verdict stands),
> **player-executors.md** (the `forceDashDist` mechanism), and **anime-actions.md** (`CornerKickLoop`,
> `GoalEvent`, `RecieveBall` and `SeamlessPassReady` read per-stadium `demoarea` `BoardPosition[8]` as
> an animation bounding box).

<details>
<summary>Original scoping note, 2026-09-20 (superseded by the close-out above)</summary>

> **SCOPED 2026-09-20, and it is ~98% smaller than this item assumes.** Triaging the 140 unlocated
> objects by name and by their `DevelopData/...` source path:
>
> | | objects | fields |
> |---|---|---|
> | clearly **non-gameplay** (ball persons, PathToGlory, Sugoroku, demo, camera, tutorial, training, mobile, esports, replay, crowd, UI) | 120 | **4,698** |
> | possibly gameplay | 20 | 664 |
>
> And 7 of those 20 — `Dribbling`, `Shooting`, `Passing`, `Tackling`, `Through_ball`,
> `Switch_sides`, `Beginner_Crossing`, 75 fields each = **525 fields** — resolve to
> `constant/tutorialConsole/*.json`. They are **tutorial drills**, not gameplay.
>
> What is genuinely left is roughly **90–120 fields in ~11 objects**:
> `animeAgingFreeMove/Trap/Dribble/Kick` (47 fields, `constant/match/`) — animation ageing, and it
> belongs with the **anime** chapter; `userPlayTendencyTest` (22, `constant/match/`) — name suggests
> the game models how the *user* plays, worth a look on its own; `positionPK_2..5` + `positionNone`
> (~20, `constant/positionPK/`) — these belong with the **set-piece** work, not here;
> `studiumPositionData` (28) and `stadiumCustomParameterData` (3), `constant/stadium/`, marginal.
>
> **Consequence for the plan:** this should not be a multi-probe raid. Fold `animeAging*` into anime,
> `positionPK_*` into set pieces, and what remains is a short focused pass — mostly
> `userPlayTendencyTest` and the stadium pair. The "hard residue worth a dedicated pass" framing
> below was written before anyone counted what was actually in it.

`build/dt270_liveness.json` classifies 21,977 fields: **12,008 read**, **4,607 unread**,
**5,362 unlocated**. The distinction matters:
- *unread* — we searched and found no reader. Probably genuinely dead.
- *unlocated* — we could not resolve where the field sits, so **no search was possible**. These are
  UNKNOWN, not known-dead, and some are live levers we simply cannot see yet.

Deliberately scheduled LAST, and that ordering is doing real work: every subsystem chapter locates
dt270 readers as a side effect, so the 5,362 will shrink on its own as 1-6 complete. Attacking it
now would mean re-deriving by hand what the chapters are about to hand over for free. What remains
afterwards is the genuinely hard residue, and worth a dedicated pass.

One thing stays out of reach even then and should not be promised: anything computed at runtime from
the save, the squad or the match state rather than stored as a constant.

~~animation motion assets (the contact cancel keyframes live in runtime-loaded CPK data...)~~
**WITHDRAWN 2026-09-19.** They live in CPK data, yes, but at *named, unhashed* paths — see the
restated blocker under item 5. They are reachable with a CPK reader.

</details>

## Gaps the owner's list does not cover

These came out of this session's decoding and are not on the list. Flagged, not started.

- **Penalties are systematically suppressed.** The foul model is fully mapped and deterministic (no
  RNG): scorer `0x143d88fe0`, level fn `0x143d861f0` with threshold **40 outside the box and 60
  inside**, cards at 80 and 110, and a veto that only lets a foul stand if the tackler won **less
  than 70% of the ball — 40% inside the box**. That is a deliberate anti-penalty bias in two places.
  If item 5 is about realistic fouls, this is the most targeted lever in the game and it is two
  constants.
  > **SITED 2026-09-20 — [set-pieces.md](set-pieces.md) § The anti-penalty bias**, and it is **four**
  > sites in two routes, not two constants. The two thresholds are **private inline immediates**:
  > `mov eax,0x3c` at `0x143d862a4` (in-box 60) and `mov ecx,0x28` at `0x143d8629f` (out 40), one
  > instruction each. The two vetoes are **shared pool cells**: the 0.7 arrives by disp32 at
  > `0x143d874a7` (cell `0x145bbe200`, **461** referrers — re-aim) and the 0.4 arrives in `xmm8` from
  > `0x143d86ffe` (cell `0x145b2a690`, **623**) and is moved in by a 3-byte `movaps xmm6,xmm8` at
  > `0x143d874c1` — so the in-box veto is the **only** one of the four that needs a cave, because
  > `xmm8` is reused by an unrelated block at `0x143d871d8`/`0x143d8723c`. Cards: 80 at `0x143d862b5`
  > **and** `0x143d862bb` (both must move), 110 at `0x143d862d6`. All six verified byte-identical in
  > PRISTINE, INSTALLED and STOCK, and **none of them was applied** — `match-ai-decoded.md`'s
  > "(ours: 36 outside)" note is stale; the installed image is byte-identical to PRISTINE (SHA-1
  > checked). Caveat: `byte[player+0x4a8]` cancels the in-box downgrade when non-zero and nobody
  > knows what that field is.
- ~~**Goalkeepers — entirely unexamined.** No GK positioning, error, distribution or shot-stopping
  work has been done at any point. Probably the largest untouched realism surface.~~ **CLOSED —
  [goalkeeper.md](goalkeeper.md) + [goalkeeping.md](goalkeeping.md)** (subsystem 5 above). Set
  pieces added one correction to it: the keeper's penalty step is **±2.160 m**, not ±5.0 m, and the
  half-plane he reads is **his own side's stick in degrees**, not the kicker's aim.
- ~~**Set pieces — unexamined.** Corners, free kicks, throw-ins.~~ **CLOSED 2026-09-20 —
  [set-pieces.md](set-pieces.md).** The levers that came out of it, best first: the
  **dead-ball accuracy logistic** (four cells at `0x143f0540b`/`0x143f05413`/`0x143f0541b`/
  `0x143f05423` — it crosses 50 % re-draw at Set Piece Taking **63** and is flat above ~85, so the
  whole top of the roster is currently undifferentiated); the **restart standoff 9.15 m** (re-aim
  the disp32 at `0x143d48c26`, cell `0x146b18170`, only **6** referrers — **not** the inline
  `0x1442ec757`, which a probe nominated and which the standoff provider does not read); the
  **free-kick distance ladder** 23/26/30/40 m, whose cells are the least-shared floats in the
  chapter (529.0 has **6** referrers, 676.0 has 10, 1600.0 has 28); the **curl gate** (`cmp al,0x55`
  / `cmp al,0x50`, private inline bytes); **short-corner frequency** (`cmp r8d,0xa`, one private
  byte); and **`positionPK_{2,3,4,5}`**, which is plain dt270 data and therefore patch-proof.
  Two negatives worth keeping: corner/free-kick/penalty **receiver and aim selection is entirely
  ability-free** (twelve functions, zero getter hits — "the wrong player attacks my corners" is a
  formation problem), and the **wall's jump decision reads no attribute at all**.
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

## Owner ruling 2026-09-19 — changing the exe is IN SCOPE

"I don't mind changing the exe." On-disk code patching is the default route from here, not a last
resort, and new code via caves is an accepted tool rather than something to be argued for each time.
The old "exe on disk is sacred, Denuvo would break it" premise in `docs/exe-gameplay-map.md` is both
superseded by this ruling and contradicted by a build we shipped and ran: **909 differing bytes in
105 contiguous runs**, 100 of them in the match band, at unchanged file size, with the game running.
(Dated 2026-09-20: that build is archived at `Backups/eFootball/eFootball.exe.patched-20260920-001042`,
sha1 `eaaa7ffa…`. The **installed** image has since been restored and is byte-identical to PRISTINE,
sha1 `d2b84d1c…`, 0 differing bytes, while `build/exe_patch_state.json` still lists 27 specs as
applied — that state file is stale. Diff the image that is actually installed before writing
"ours".)

**What this unblocks:** redrawing the per-possession random per decision (the single biggest lever on
on-ball predictability, § 1); enabling `ThinkUnitPassRandomTest`, the carrier brain's fully-built
randomiser that is registered but never listed; enabling run kind 6; re-ordering the on-ball priority
lists; and the LineBreak approach, which needed a cave as a vtable entry point.

**What it does NOT change — permission was never the binding constraint on any of these:**

- **Cave size — but only for the existing-padding approach.** Inter-function padding caps at 15 bytes
  because MSVC aligns entries to 16; the largest single cave is **21 bytes, zero at 24+**, ~553 KB of
  pool fragmented across ~97,600 holes. **CORRECTED 2026-09-19: this is NOT a limit on the exe, only
  on the cave-scavenging route, and an earlier version of this section wrongly said "new subsystems,
  no".** Three routes give arbitrary space: (a) **add a PE section** — the section table ends at file
  offset `0x3b8` and the first section's data starts at `0x400`, so there are 72 bytes of header
  slack = **exactly one free section-header slot**; the file has no trailing slack so data is
  appended and `SizeOfImage` / `NumberOfSections` bumped; (b) **allocate at runtime** with
  `VirtualAllocEx` and hook into it — unlimited, no file surgery, and `tools/live_patch.py` already
  has the attach/protect/write/journal machinery; (c) the **Sider-derived hooking DLL** from the
  collaborator merge (ban-risk call, owner's). Adding a section also lets us register exception
  records for our own code, which would remove the unwind hostility below and unblock LineBreak.
  **Untested risk:** Denuvo tolerates 909 changed bytes inside `.xcode`, but PE *header* changes are
  a different and more visible surface. Prototype the runtime route first — it proves the code works
  without touching headers.
- **Unwind hostility.** Cave code is covered by no `RUNTIME_FUNCTION`, so a `call` out of a cave puts
  an unresolvable return address on the live stack, and a cave installed as a **vtable entry point**
  for a non-leaf frame function is an x64 ABI violation. Fine for hook caves that never fault.
- **The four open `cave_alloc.py` defects** (below). These are the "installs wrong without telling
  you" class and should be fixed before the next cave ships.
- **Animation motion assets.** Not in the exe at all — runtime-loaded CPK data, filenames probably
  hashed. No exe permission reaches them. This is still the ceiling on item 5.
- **Fixed structure.** 22 players, 2 teams are array shapes in the registry records, not constants.
- **Shared / index-doubling cells.** Some constants double as RNG stream selectors or loop bounds
  (the `mov esi,0x64` case accepts only 98..101 before indexing off the end of a stack structure).
  Still NOT-SAFELY-TUNABLE; re-aim a disp32, never write a shared cell.

## Housekeeping

- Two applied packs work by the route the owner rejected (adding runners):
  `offball-counter-early.json` (CounterSpaceRun maxSlots 1→2, binds at *every* attack level) and
  `offball-run-variety.json`. Remove before judging item 1.
- `cave_alloc.py` has no concept of exception unwinding. A cave installed as a **vtable entry point**
  that is a non-leaf frame function is an x64 ABI violation. Fine for hook caves that never fault;
  not fine for entry points. Needed for the LineBreak approach.

## Subsystem map

- **Ball carrier (`match::ai::bp`)** — [docs/ball-carrier-brain.md](ball-carrier-brain.md): plan (Image) first-match-wins, then a fixed ThinkUnit priority list (Force > RespondRequest > Special > Shoot > passes); no scoring, no dt270, randomness only in four plan rolls and the feint shortlist; Personality is per-player data the app writes. Read its Corrections before touching on-ball behaviour.
- **Goalkeeper** — [docs/goalkeeper.md](goalkeeper.md): one machine across subsystems 2 and 3. The save **quality** is heavily compressed — `0x144032870` picks one attribute per action id, floors Reach at 50 and Reflexes at 63, remaps easy catches into 73..89 — and on the one route followed end to end (`0x143f31470`) it ends as a **0.900–1.295 multiplier** (worst keeper = 77–92 % of the best). **That is one of four consumers; the block-wide range is NOT bounded.** Two real cliffs: **GK Reach ≥ 85** unlocks `Deflect::vf35`, and **GK Awareness below 44 is dead**. Distribution is its own brain (`0x145655430`, 2,461 B in 4 chunks), not a ThinkUnit; the penalty dive is a read of a pointed-to aim descriptor, not a roll; dive lockout is a median **0.850 s** with recovery **1.083 s** under the proven frame rule. No dt270, no difficulty, no pad binding. The probe decode of positioning, distribution and one-on-ones is [docs/goalkeeping.md](goalkeeping.md).
