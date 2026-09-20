# Goalkeeping — where he stands, what he does with the ball, and when he comes out (2026-09-20)

Probe **positioning-distribution-and-one-on-ones**. This is the stitching chapter: goalkeeping was
never its own subsystem in the exe, it is split between **subsystem 2 (`match::player` executors)**
and **subsystem 3 (`match::anime::action::goal_keeper`)**, both already decoded. Everything here is
either new work in the gaps the plan left open (positioning / distribution / one-on-ones / set
pieces / the dive lockout) or a re-check of a claim that turned out to need correcting.

Decoded from `C:\Users\tjgg2\Backups\eFootball\eFootball.exe.PRISTINE`, base `0x140000000`, no ASLR.
Animation tables read from an extracted `common/anime/{Mbinfo,AnimeTable}/bin` tree with
`tools/mbinfo_ef.py` and `tools/data/ef_anime_names.json` (7,883 names).

Evidence labels: **[a]** evaluated numerically on the game's own bytes/tables, **[b]** disassembly,
**[c]** inferred.

What this chapter does **not** redo: the six save classes and their action ids, the `0x144032870`
save-quality selector and its 0.90–1.30 multiplier, the ~25 executor subobject offsets, the 0.5 m
GK-Awareness standing error, the 3.5 m reach gate, the `PreSaveOperation` arming window. Those are
in [player-executors.md](player-executors.md) and
[anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md) and they all survived re-check.

---

## TL;DR

1. **The goalkeeper has his own on-ball brain and it is not a ThinkUnit.** `0x145655430` is a
   1,200-byte function whose first real test is `role code != 0 → leave`. It is reached through
   exactly one call site, and it is the **only** writer of `team+0x275c`, the distribution target
   that `ActionKeeperThrow`, `ActionKeeperThroughThrow` and `ActionKeeperPuntKick` read. That is
   why `GKDribble` / `GKPassShort` / `GKPassLong` are registered and never run — keeper
   distribution never enters the ThinkUnit list at all. [b]
2. **GK Awareness is a real anticipation window, not a 0.5 m wobble.** `0x1442246d0` (in
   `ActionKeeperBasePosition::vf4`'s chain) reads attribute `0x16` and builds **two** frame numbers
   from it. The keeper may only react to an opponent's wind-up when that animation has at most
   `fps·0.25·norm` frames left and has already run for more than `fps·(0.5 − 0.33·norm)` frames,
   `norm = clamp01((attr−40)/59)`. At 60 fps that is **0 frames of anticipation at 40 and 15 frames
   (0.25 s) at 99**, starting **0.50 s into the animation at 40 and 0.17 s at 99**. [b]
3. **There is a hard cliff at GK Awareness 44.** Below it the first budget rounds to 0 frames, the
   `remaining <= budget` test can never pass (the branch above it already demanded
   `elapsed < duration`, so `remaining >= 1`), and **the keeper never takes the anticipation branch
   at all**. 44 = 40 + ceil(59/15). [b, arithmetic shown below]
4. **Keeper positioning reads a per-player boolean the finished chapters missed.** Bit `0x46` of a
   73-entry per-player flag table (`0x1442c0000(rec, idx)` over `rec+0xc0`) gates a branch in
   `ActionKeeperBasePosition::vf20` (`0x1442223a7`) and in the vf4 helper `0x1442260f0`
   (`0x144226c64`). In both, passing the bit is the precondition for an "is the ball outside this
   box" test — the shape of a sweeper-keeper enable. **The bit's NAME is not established.** [b]
5. **Coming out is a 15 m decision with no ability term.** `ActionKeeperPress::vf6` gates on a
   cached squared distance against **225.0 (15.0 m)**, or **49.0 (7.0 m)** when `team+0xb3bd == 0`.
   Inside that, he only commits if the attacker is in a committing animation. Outside it he is
   parked. No attribute anywhere in the Press family except HEIGHT. [b]
6. **`ActionKeeperPress::vf4`'s engage block is an angle-sector filter plus a ball-speed floor.**
   The bearing to the threat must be within **±45° of 90° or 270°** (i.e. across him), a second
   angle must be in **(5°, 90°)**, and the ball must be travelling **faster than 10 km/h**
   (`0x143c65890` = m/frame → km/h, confirmed). [b]
7. **The penalty dive side is a pre-commitment read off the action record's aim descriptor, not a
   coin flip.** `ActionKeeperMovePenaltyKick::vf16` pins him to his own goal line and steps him
   ±5.0 m in z on a **single comparison of the descriptor's 9-bit angle field against 90.0**. There
   is no RNG and no attribute in the class. The save itself (`PKSaving`) is the ordinary
   deterministic trajectory scan. [b]
8. **Once a keeper starts a penalty dive he cannot stop.** Every one of the 15
   `gkprejump_0_0_pk_*` animations (plus the two `gkmovemid_pk` stances) has **zero** cancel
   records: 0.33 s to 1.43 s of full lockout. The family is (far / front / Otherside) × (high /
   low) plus `_cancel` and `_moveOtherside` scramble variants. [a]
9. **The keeper's dive lockout, measured for the first time.** Across 1,250 `gk*` animations:
   `gkdeflect` first cancel **0.150 / 0.392 / 1.050 s** inside a 1.233 s median motion; `gkcatch`
   **0.167 / 0.392 / 0.867 s**; getting up (`gkrise`) **0.133 / 0.508 / 2.633 s** inside 1.100 s.
   **518 of the 1,250 (41 %) have no cancel record at all** and are locked for their whole length
   (median 0.833 s, max 7.067 s). For scale, the outfield post-tackle lockout median is 0.300 s.
   [a]
10. **`ActionKeeperCoaching` is not the wall.** Its two bodies compute one integer and write it to
    `work+0x1050`; it has no destination and no steering point; its entire animation set is
    `gkcoaching_high_0_0_lower_goalkick` and `gkcoaching_high_0_0_up_goalkick`. It is the keeper's
    **goal-kick arm-wave (push up / drop back)**. The wall is `wall_*`, twelve outfield animations.
    [b + a]
11. **Keeper depth is a formation number, not a dt270 number.** Nothing in `basePosition.gk*`
    reaches a keeper executor (re-confirmed: 20 fields, 6 read, all six inside the *outfield*
    goal-kick shape layer). The base x comes from `teamAI + slot·20 + 0x40` and `team+0x799c`, is
    clamped to ±10 m of that reference, and is then capped at **4.0 / 15.0 / 20.0 / 42.0 m** by
    state. All four caps are shared cells. [b]

---

## Provenance

Everything below was read from PRISTINE. The finished chapters state that PRISTINE == INSTALLED
over the keeper ranges. This probe made **no** writes of any kind — no `exe_patch.py apply`, no
`gameplay_tune`, nothing under the Steam tree, no git commits.

---

## 1. Positioning

### 1.1 The chain, under the corrected slot reading

`ActionKeeperBasePosition`, vftable `0x146bbfae8`, 23 slots, subobject `+0x13550`. Overridden slots
(diffed against `match::ai::ActionMove`): **0, 3, 4, 6, 8, 9, 13, 15, 18, 20**. [b]

| slot | body | size | what |
|---|---|---|---|
| 4 | `0x144223580` | 4,421 B | **the destination**. Calls `0x1442246d0` and `0x1442260f0` |
| 6 | `0x14422c240` | — | predicate |
| 13 | `0x144228fd0` | — | int tag; reads `team+0xb3bd` at `0x14422908e` |
| 18 | `0x14422a680` | 7,104 B | the class's own packager — the largest body in the family |
| 20 | `0x144221e10` | 3,561 B | steering point (turn-capped heading), already decoded |
| — | `0x1442246d0` | 5,039 B | vf4 helper A — the threat model |
| — | `0x1442260f0` | 4,261 B | vf4 helper B |
| — | `0x144228170` | 2,102 B | the standing-error / depth-clamp helper |

The executors chapter's correction holds: **slot 4 supplies the destination, slot 20 emits a
steering direction at a fixed radius.** Everything in this section is about slot 4's chain and slot
18, not slot 20.

### 1.2 Depth — where the base spot comes from, and whether you can move it

In `0x144228170` (the same function that holds the 0.5 m standing error): [b]

```
0x1442284f3  movss xmm7, [rbx + 0x799c]                  ; team-level reference x
0x144228502  mulss xmm6, [r15 + rcx*4 + 0x40]            ; rcx = 5*slot  ->  stride 20 bytes
             ; xmm6 was xmm12 = the attack-direction sign (+1 / -1)
0x144228509  subss xmm0, xmm6 ; call fabsf
0x144228512  comiss xmm0, 10.0     [0x145a8dd7c]
0x14422851d  jbe  ...                                    ; within 10 m -> keep it
0x14422851f  subss xmm6, xmm7
0x144228523  comiss xmm8(0.0), xmm6
0x144228529/2f  xmm6 = xmm10 or xmm11                    ; the -1 / +1 pair
0x144228533  mulss xmm6, 10.0
0x144228537  addss xmm6, xmm7                            ; = reference +/- 10 m
```

Then the **advance cap**: [b]

```
0x1442285ce..0x1442285f9
  [rsp+0x170] != 0          -> xmm9 = 4.0    [0x145ab1b48]
  else if (r12b || sil)     -> xmm9 = 20.0   [0x145a8aa44]
  else                      -> xmm9 = 15.0   [0x145c0b000]
  then if (sil && !bpl)     -> xmm9 = 42.0   [0x145ec9ef0]
0x144228612  minss xmm6, xmm1     ; cap
0x144228616  maxss xmm6, xmm14    ; floor
```

plus a state-dependent additive term `25.0 + t·15.0` (`t` a clamp01 over `teamAI+0x25bbc` against
two pitch bounds) at `0x14422853b..0x144228595`.

**Reading.** The keeper's base x is the **per-slot formation coordinate** (`teamAI + slot·20 +
0x40`) mirrored by attack direction, clamped to within **10 m** of the team-level reference
`team+0x799c`, then capped at 4 / 15 / 20 / 42 m by match state. Identifying the 20-byte-stride
array as the formation slot position is **[c]**; the arithmetic is **[b]**.

**Is the starting depth tunable?**

* **Through dt270: no.** Re-confirmed from `build/dt270_liveness.json` — no keeper executor reads
  any dt270 field (§ 1.6).
* **Through an exe constant: not safely.** `0x145a8dd7c` (10.0) has 1,832 referrers, `0x145c0b000`
  (15.0) and `0x145a8aa44` (20.0) are image-wide shared, and **42.0 (`0x145ec9ef0`) has refcount 26
  across six unrelated classes** — the census calls all four `shared, private=False`.
* **Through team data: yes, and this is the route.** The base spot is the formation's own GK slot
  coordinate. Moving the GK marker in the team's formation moves his depth one-for-one, up to the
  ±10 m clamp. That is a **team-data** route, no patching at all.

### 1.3 The 16.42 m gate — its consumer, decoded

`0x146bdfd90 = 269.6164 = 16.42²`, census `status=private, refcount=1,
classes=[ActionKeeperBasePosition]`, sole referrer `0x144224d1d`. The finished chapter located it
but left the consumer "only partly read". It is: [b]

```
0x144224cfc  cmp r12d, 0x15 ; ja skip              ; a valid entity index (the threat)
0x144224d06  comiss xmm7, xmm0 ; jbe skip          ; xmm7 = 1.1 or 2.6, xmm0 = |ball - spot|
0x144224d1d  movss xmm0, 269.6164
0x144224d25  xmm1 = (spot.x - other.x)^2 + [rsp+0x78]
0x144224d33  comiss xmm0, xmm1 ; jbe skip          ; need d^2 < 269.6164  ->  d < 16.42 m
0x144224d3c  |xmm12| vs [pitchDim + 0x1c]
0x144224d5e  rec = 0x1442d6ba0(match, r12d)        ; the threat's CURRENT action record
0x144224d6b  0x144311e40(id)  bit 21   -> 0x144224df0
0x144224d76  0x144311bf0(id)  bit 10   -> 0x144224dc9
0x144224d81  0x1443122e0(id)  bit 25   -> 0x144224dc9
0x144224d8c  0x144311c90(id)  bit 23   -> 0x144224dc9
0x144224d97  0x144311cb0(id)           -> else skip
0x144224dc9  a 144.0 (= 12 m) squared-distance test
0x144224df0  a duration/elapsed window against fps*0.3 or fps*0.5
   pass  -> xmm7 = 1.5, xmm12 = 1.5
   fail  -> xmm7 = 0.5, xmm12 = 1.5
```

So the private 16.42 m cell is **the radius inside which the keeper is allowed to notice an
opponent's action at all**. Raising it makes him start reacting to threats further out; lowering it
pins him. It really is private (refcount 1) and it really is stored squared. What is new is that
the gate leads to an **action-class test on the threat** and an **animation-timing window**, not to
a distance-based move.

### 1.4 GK Awareness is an anticipation window (new)

Two sites in `0x1442246d0` read the attribute through `0x1442dd650(match, playerIdx, attrIdx)` —
which this probe identifies as the by-index attribute getter (it is `0x1442d6ef0` → `0x144301840` →
`0x1441172b0`, with `r8d` the index). The keeper sites pass `r8d = 0x16` =
`DATA_PARAMETER_GK_DECISION` = **GK Awareness**. The same helper with `r8d = 0x32` is the HEIGHT
read the existing chapter attributes to the Press family. [b]

```
0x14422549d  ax = rec->duration  (u16 [r14+0x1e]);  if 0 -> skip
0x1442254b2  if (rec->elapsed (u16 [r14+0x1a]) >= ax) -> skip      ; must still be running
0x1442254c2  mov r8d, 0x16 ; call 0x1442dd650                      ; GK Awareness
0x1442254d0  xmm0 = 40.0
0x1442254e2  if (40 > attr) norm = 0
0x1442254ec  else if (attr >= 99) norm = 1
0x1442254fb  else norm = (attr - 40) / 59.0
0x144225507  xmm11 = 100.0 ; norm *= 100
0x144225515  call fps() ; xmm0 = fps * 0.25
0x144225522  xmm0 -= xmm8            ; xmm8 == 0.0 for the whole function (xorps @0x1442247d4)
0x144225527  xmm0 *= norm ; /= 100 ; += 0
0x144225535  ebx = (int)xmm0                         ;  BUDGET
0x144225541  xmm7 = fps * 0.17
0x144225558  xmm0 = fps * 0.5
0x144225560  ecx = duration - elapsed                ;  REMAINING
0x144225565  cmp ecx, (u16)ebx ; jg skip             ;  REMAINING <= BUDGET
0x144225569  xmm7 = (xmm7 - xmm0) * norm/100 + xmm0
0x14422557a  eax = (int)xmm7                         ;  ONSET
0x14422557e  cmp dx, ax ; jbe skip                   ;  ELAPSED > ONSET
```

At 60 fps (`fps` from the `.bss` getter `0x14533ea80`): [b, arithmetic]

| GK Awareness | norm | BUDGET (frames) | ONSET (frames) | ONSET (s) | branch reachable? |
|---|---|---|---|---|---|
| 40 | 0.000 | 0 | 30 | 0.500 | **no** |
| 43 | 0.051 | 0 | 29 | 0.483 | **no** |
| **44** | 0.068 | **1** | 28 | 0.467 | yes |
| 50 | 0.169 | 2 | 26 | 0.433 | yes |
| 60 | 0.339 | 5 | 23 | 0.383 | yes |
| 70 | 0.508 | 7 | 19 | 0.317 | yes |
| 80 | 0.678 | 10 | 16 | 0.267 | yes |
| 90 | 0.847 | 12 | 13 | 0.217 | yes |
| 99 | 1.000 | 15 | 10 | 0.170 | yes |

**The cliff at 44 is real and checkable.** `BUDGET = floor(15·norm)`, so `BUDGET >= 1` needs
`norm >= 1/15`, i.e. `attr >= 40 + 59/15 = 43.93`. Below that, `REMAINING >= 1 > 0 = BUDGET`
always and the branch is dead. **Any keeper you author at GK Awareness 40–43 loses this behaviour
entirely** — the first three points of the attribute scale are a step, not a slope.

The consumer: if the gate passes and a further angle test (`|Δbearing| > 40.0` between
`teamAI + idx·4 + 0x25b64` and `rec+0x1cc`) holds, the function **returns immediately**
(`0x144225a29`), skipping the whole later adjustment chain — the keeper **stops adjusting and sets
himself** as the shot comes. [b]

`ActionKeeperBasePosition::vf18` (`0x14422a680`) has the same shape at `0x14422aba3`: `r8d = 0x16`,
the same `(attr−40)/59` normalise, then `r15 = lerp(xmm12, fps/3, norm)` used as a **frame index
into the ball trajectory** (`0x144300f00`). So the keeper's *look-ahead on the ball* is also
GK-Awareness-scaled, capped at 20 frames (0.333 s). Note the `mulss xmm6,xmm9` at `0x14422abf9` and
`divss xmm6,xmm9` at `0x14422ac22` **cancel** — `xmm9` has no effect on this term. [b]

**This, not the 0.5 m standing error, is what GK Awareness actually buys.** The error is ≤ 0.5 m and
invisible; the anticipation window is up to a quarter of a second of head start plus a third of a
second of earlier onset, and it is switched off completely below 44.

### 1.5 A per-player boolean gates keeper positioning (new)

`0x1442c0000(rec, idx)` is a **73-entry bit table**: `bit idx of dword[rec + 0xc0 + (idx>>5)*4]`,
bound `cmp edx, 0x49`. `0x1442e2610(slotIdx, idx, teamRec)` is the by-slot wrapper
(`0x1442c3050` then a tail-jump into `0x1442c0000`). [b]

Census of the 141 direct call sites and 18 wrapper call sites (my own scan; the `edx`-immediate
recovery misses a handful, so the per-bit counts are a lower bound):

| bit | read in |
|---|---|
| `0x46` | **`ActionKeeperBasePosition::vf20` `0x1442223a7`** and **`0x1442260f0` `0x144226c64`** (the vf4 helper) |
| `0x12`, `0x14` | **the goalkeeper's distribution brain `0x145655430`** (5 sites, § 2) |
| `0x04, 0x06..0x2b, 0x33` | outfield: `DribbleImageKickFeint`, `ThinkUnitShoot`, `ImageUnitLong`, `ImageUnitCross`, `KickoffOther`, … |
| `0x2e, 0x2f, 0x30, 0x36, 0x39, 0x3e, 0x3f, 0x40, 0x48` | all inside one function, `0x144151280` |

Both `0x46` sites have the same shape: [b]

```
0x1442223a7  al = bit 0x46
0x1442223af  test al,al ; je  <fallback>
0x1442223b3  if (byte[thing+0x48] == 0x0a) -> <fallback>
0x1442223cc  |p.x| vs [pitchDim+0x18]            ; must exceed
0x1442223ec  |p.z| vs [pitchDim+0x1c]            ; must exceed
0x144222400  bl = 1                              ; the enabled path
```

i.e. **the bit is the precondition for a "the ball is outside this rectangle" test** inside the
keeper's own positioning. That is the shape of a sweeper-keeper / "come off your line" enable.

**The bit's name is NOT established.** `src/ML.Core/Development/PlayerSkillCatalog.cs` says its 57
skill names come from `dt261 all.str [66105..66178]` — 74 strings against this table's 73 entries —
but the catalog array is grouped thematically, not in string-table order, so it cannot be indexed.
Naming `0x46`, `0x12` and `0x14` needs an `all.str` dump in original order. See Open.

### 1.6 The dt270 `gk*` family — full enumeration

Re-read from `build/dt270_liveness.json`. `basePosition` (idx 226,
`DevelopData/common/match/constant/team/basePosition.json`, 872 B, 220 fields) has exactly **20**
`gk*` fields; **6 are read, 14 have no reader at all**: [b]

| field | offset | status | reader(s) |
|---|---|---|---|
| `gklAdjustRateX` | `0x1b4` | read | `0x143de2568` |
| `gklAdjustRateZ_DF` | `0x1b8` | **unread** | — |
| `gklAdjustRateZ_FW` | `0x1bc` | **unread** | — |
| `gklAdjustRateZ_MF` | `0x1c0` | **unread** | — |
| `gklBaseX` | `0x1c4` | read | `0x143de23d3`, `0x143de8a89` |
| `gklBaseZRate` | `0x1c8` | read | `0x143de23fc`, `0x143de8aae` |
| `gklDefenceBackRate` | `0x1cc` | **unread** | — |
| `gklSupportRate` | `0x1d0` | read | `0x143de2635` |
| `gklWidthZ` | `0x1d4` | read | `0x143e7f745` |
| `gksAdjustRateX` | `0x1d8` | **unread** | — |
| `gksAdjustRateZ_DF` | `0x1dc` | **unread** | — |
| `gksAdjustRateZ_FW` | `0x1e0` | **unread** | — |
| `gksAdjustRateZ_MF` | `0x1e4` | **unread** | — |
| `gksBaseX` | `0x1e8` | **unread** | — |
| `gksBaseZRate` | `0x1ec` | **unread** | — |
| `gksDefenceBackRate` | `0x1f0` | **unread** | — |
| `gksHalfLineRateX_SB` | `0x1f4` | **unread** | — |
| `gksPenaltyLineRateX_DF` | `0x1f8` | **unread** | — |
| `gksSideLineRateZ_SB` | `0x1fc` | **unread** | — |
| `gksWidthZ` | `0x200` | read | `0x143e7f73a` |

All six readers live in `0x143de2350`, `0x143de8520` and `0x143e7f4c0` — the **outfield** shape
layer. `gks`/`gkl` = **goal-kick-short / goal-kick-long team shape**, not the keeper's own spot.
Across all 245 dt270 objects the only other `gk`-named fields are `modeMatchup.gk_entry` and
`rating.gk_rate` / `rating.coef_gk[]`, which are match-rating, not gameplay. [b]

**Negative, restated with a full enumeration behind it: dt270 contains no goalkeeper-behaviour
tunable of any kind.**

---

## 2. Distribution — the keeper has his own brain

### 2.1 Finding it

`team+0x275c` is the distribution target entity index. A displacement scan over
`0x143c00000..0x145700000` (fixed after an off-by-one in the instruction-boundary walk that
initially hid two of the readers — see Negatives) finds **12 sites**: [b]

| site | what |
|---|---|
| `0x14421553b` | `ActionKeeperPuntKick::vf6` — read |
| `0x14421780b` | `ActionKeeperThrow::vf6` — read |
| `0x1442184a5` | `ActionKeeperThroughThrow::vf6` — read |
| `0x14470dcd9` | unrelated (a byte read at the same displacement in another object) |
| `0x145655519`, `0x145655ac9`, `0x145655b45`, `0x145655b7b`, `0x145655bb5`, `0x145655c24`, `0x145655c6c`, `0x145655d04` | **all eight writes, all inside `0x145655430`** |

The call chain is a single thread, from a `call rel32` scan of `0x143000000..0x1458f0000`: [b]

```
0x144156ae4  ->  0x14562cad0  --(0x14562cbb1)-->  0x145655430   (1,200 B)
                             \-(0x14562cbbf)-->  0x145655dd0   (416 B, the other branch)
```

`0x145655430` has **one** caller; `0x14562cad0` has **one** caller.

### 2.2 `0x14562cad0` — the role-code fork

```
0x14562cae4  mov byte [rcx+0x6d19], r8b            ; caller-supplied flag
0x14562caee..0x14562cb34                           ; entity index -> side
0x14562cb42  r8 = teamObj + 0x778
0x14562cb49  idx = entityIdx % 11  (capped)
0x14562cb70  eax = [r8 + idx*4 + 0x3b40]           ; 0x778 + 0x3b40 = 0x42b8
0x14562cb78  test eax,eax ; jne 0x14562cb9b        ; only role 0 recomputes the flag
0x14562cb8f  byte[rdi+0x6d19] = (mySide == 0x1442eaba0(record,0)->[+4])
0x14562cb9b  if (byte[rdi+0x6d19]) 0x145655430(bp+0x6ce8, action, r9)
             else                  0x145655dd0(bp+0x6d00, action)
```

`teamObj+0x42b8` is exactly the **formation role-code array** the carrier-brain chapter identified
(`0x778 + 0x3b40`), where **role 0 = goalkeeper**. [b]

### 2.3 `0x145655430` — the goalkeeper's on-ball brain

Its first substantive test after fetching the role code is: [b]

```
0x1456554e0  ebx = teamObj[slot] role code  (0x42b8)
0x145655542  test ebx, ebx
0x145655544  jne 0x145655d65        ; NOT a keeper -> copy teamAI+0x8f4c+slot*4 into [rdi+8], leave
0x14565554d  call 0x143d0f920(team, side) ; if true -> same exit
```

So the whole 1,200-byte body is **goalkeeper-only**. What it writes:

| what | where | value |
|---|---|---|
| requested action | `[rdi+0x10]` (`bp+0x6ce8+0x10`) | `0x40`, `0x41`, `0x42` |
| second action id | `[rdi+8]` | `0x4e`, `0x3f`, `0x76`, `0x7d`, `1` |
| **distribution target** | `team+0x275c` | an entity index ≤ 0x15, or `0xff` = none |
| flags | `team+0x2751`, `team+0x2752` | `1` |

The decision structure, in order: [b]

1. **A candidate loop over the 11 team-mates** (`cmp esi, 0xb ; jl` at `0x145655a72`), scoring each
   with `0x1442dd650(team, idx, 0x32)` — the by-index attribute getter, index `0x32` = HEIGHT —
   keeping the maximum in `xmm11` and its index in `[rsp+0x108]`. Only candidates whose
   `0x1442d6ef0(match, idx)->[+4]` byte is zero are considered.
2. **A timing gate**: `ebx = 0x1442eb950(rec, 0)`, which indexes a `0x340`-byte event ring at
   `rec+0x1a08` and returns `dword[event+0x14]` (or 0 when `dword[event]==0x37`); the code demands
   `ebx >= 2·fps` (120 frames at 60 fps) before it will pick a target at `0x145655ab3`. Reading
   that field as "frames since the restart" is **[c]**; the comparison is **[b]**.
3. **A short/long split.** `xmm12 = 30.0` by default (`0x145655595`), raised to **40.0**
   (`0x145655aed`) when per-player flag bit **`0x14`** is set. Then
   `mulss xmm12,xmm12 ; comiss xmm12, 0x143c71ee0(rec+0x1840, idx)`:
   * inside the radius → `[rdi+0x10] = 0x41`, `[rdi+8] = 0x4e`, target = the candidate;
   * outside → `[rdi+0x10] = 0x40`, `[rdi+8] = 0x4e`, and if flag bit **`0x12`** is set,
     `team+0x2751 = 1` as well.
4. **Three private target-finders**, each called from nowhere else in the image:
   `0x143d104b0` (911 B, two call sites, → action `0x41`), `0x143d0ff40` (722 B, → action `0x42`),
   `0x143d10220` (646 B, → action `0x40` plus `team+0x2751 = 1`). A fourth, `0x143d10840` (702 B),
   feeds the second `0x143d104b0` site's comparison.
5. **The give-up path**: `team+0x275c = 0xff`, `[rdi+0x10] = 0x40`, `[rdi+8] = 0x4e`
   (`0x145655cf5..0x145655d0e`).

It also branches on `matchState+0x3308` (== 1 / == 2), `+0x3304` (== 9), `+0x34c0` (== 5) and calls
`0x1443120f0` — the **bit-9 keeper-action-family predicate** the executors chapter found. [b]

### 2.4 What this settles

* **Distribution is not chosen by the carrier brain.** The carrier-brain chapter's negative —
  `GKDribble` (0x19), `GKPassShort` (0x1a), `GKPassLong` (0x1b) registered and never pushed — is now
  *explained* rather than merely observed: keeper on-ball decisions run in `0x145655430`, a sibling
  object at `bp+0x6ce8`, and never enter the ThinkUnit list. The GK think list
  (`PassRespondRequest, PassForward, PassLong, PassSafety, GKClear`) is what the keeper uses when he
  is treated as an ordinary carrier; his *restart* distribution is this function. [b]
* **Is it scripted?** Not scripted in the fixed-sequence sense — it is a candidate scan with a
  distance split and several state gates — but it is **fully deterministic**: no RNG call site
  anywhere in `0x145655430` or in the three target-finders, and the only per-player inputs are
  HEIGHT (`0x32`) and two boolean flags. A keeper's passing, vision or technique attributes do not
  appear at all. [b]

---

## 3. One-on-ones — when the keeper comes out

`ActionKeeperPress`, vftable `0x146bdc420`, subobject `+0x134f0`. Overrides **0, 4, 5, 6, 15, 18,
20**. vf4 is 6,946 B (nine chunks), vf6 4,739 B, vf5 3,131 B. The engage logic is split across
**vf4 and vf6** — not vf5, as the existing class-status row assumes. [b]

### 3.1 The trigger distance: 15 m, or 7 m

In `vf6` (`0x14421c0c0`): [b]

```
0x14421c999  rcx = teamAI + 0x25a9c            ; a cached per-slot squared-distance array
0x14421c9a7  call 0x143c71ee0(rcx, opponentIdx)
0x14421c9ac  comiss xmm0, 49.0   [0x146a6fa18] ; 7.0 m squared
0x14421c9b3  jbe  -> the 225 test
0x14421c9ba  cmp byte [team + 0xb3bd], 0
0x14421c9c1  je   -> 0x14421c9e0  (mode 2)
0x14421c9d2  call 0x143c71ee0(teamAI + 0x25a9c, opponentIdx)
0x14421c9d7  comiss xmm0, 225.0  [0x146a0476c] ; 15.0 m squared
0x14421c9de  jbe  -> 0x14421ca3d  (examine the opponent's action record)
0x14421c9e0  [r15] = 2                         ; the "hold" mode
```

**Beyond 15 m — or beyond 7 m while `team+0xb3bd == 0` — the keeper takes mode 2 and does not
engage.** Inside it, the code reads the threat's action record `0x1442d6ba0(match, idx)`, tests
`0x144311e20(actionId)`, checks `actionId == 4`, and compares the animation's
`duration` / `elapsed` / `byte[rec+0x42]` against `fps·0.4` — i.e. **he only commits when the
attacker is already inside a committing animation**. [b]

`vf6` writes two ints, `[r15] ∈ {2,3}` and `[rsi] ∈ {2,3,4,5}` (a mode/gait pair) and a
`byte[r14+0x3d] = 7` tag. The approach-speed term is
`min(5.0, (13500/(fps·xmm13) + speed·0.2778) · xmm7 · xmm8)` at `0x14421c7b1..0x14421c805` — capped
at **5.0**. [b]

### 3.2 The engage block in vf4

`vf4`'s engage block at `0x14421ac34..0x14421aca6` is an **angle-and-speed filter**, all angles in
degrees. `0x143c6fd80(a,b)` is `atan2deg(b.z−a.z, b.x−a.x)` (confirmed by disassembly: the
`0x143ba63a0` tail with a `1.19209e-07` degenerate guard), and `0x143c65890(x)` is
`x · fps · 3600/1000` = **m/frame → km/h** (confirmed; same conversion the save-quality speed gate
uses). [b]

```
xmm7 > 5.0                                  ; a bearing magnitude, > 5 deg
|pos.x| > [pitchDim + 0x18]                 ; the keeper is deep enough
90.0 > xmm7                                 ; ... and < 90 deg
(45 < xmm6 < 135) or (225 < xmm6 < 315)     ; the threat bearing is ACROSS him, +/-45 deg of 90/270
xmm8 > 10.0                                 ; ball speed > 10 km/h
   -> 0x1442dd650(team, idx, 0x32)  (HEIGHT) -> /180.0 -> a steering parameter
   -> [action+0x3c] = 1, [action+0x3f] = 1, [matchWork+0x1a74] = 1
0x14421aeb0  if ([action+0x3c]) al = 0x144218d40(...)  ; a second gate
```

An earlier block at `0x14421a8ec..0x14421a916` picks the aim point: if the bearing is in
**(40°,140°)** or **(220°,320°)** he aims at the ball `fps/3` ticks ahead, otherwise at the
`fps/12` point. Constants 40.0 `0x145d58ec8`, 140.0 `0x146300e48`, 220.0 `0x145eaf8c4`, 320.0
`0x146bdc4d8` (refcount **3**; referrers `0x14421a90b`, `0x1442264f4`, `0x1456ac1d0`). [b]

`vf5` (`0x14421b1e0`) opens with `comiss 0.1, d² ; ja exit` — **if the target is within 0.316 m he
does nothing** — and is the path/steering half, not the decision.

### 3.3 Is it ability-gated? What stops him?

* **No.** The only attribute anywhere in the Press family is HEIGHT (`0x32`), and it feeds a
  steering parameter, not a decision. No RNG. This re-confirms the finished chapter and extends it
  to vf5 and vf6, which it had not read. [b]
* **What stops him**, in order: distance > 15 m (or > 7 m on a team flag); the threat not being in a
  committing animation; ball speed ≤ 10 km/h; the threat bearing not being across him;
  `0x144218d40` refusing; and the depth cap of § 1.2 (4 / 15 / 20 / 42 m). **None of these six is
  ability-scaled.**

---

## 4. Set pieces

### 4.1 The penalty — the dive side is read, not rolled

`ActionKeeperMovePenaltyKick` (vftable `0x146be09a8`) overrides **exactly one slot, vf16**
(`0x14422ca70`, 390 B). Fully decoded: [b]

```
0x14422cad1  kind = 0x144318200(tag(rec+0x20)) ; must be 2
0x14422caee  raw tag & 0x7f must not be 0x55
0x14422cafc  *out_int  = 1
0x14422cb02  *out_flt  = 0x144326290(1)          ; a 5-way constant switch (28.0 in one arm)
0x14422cb0c  *out_int2 = 3
0x14422cb30  dest = player position (x,y,z) from player+0x4f4 / +0x4fc
0x14422cb49  desc = 0x144317ec0(rec+0x20)        ; unpacks u32[rec+0x24]:
                                                 ;   [0]   = (v & 0x1ff) as float -> an ANGLE in deg
                                                 ;   [4]   = ((v>>9)&7)/7
                                                 ;   [8]   = ((v>>12)&7)/7
                                                 ;   [0xc] = (v>>15) as a byte
0x14422cb4e  if (90.0 > desc.angle)  dz = +5.0   [0x145a8dd78]
             else                    dz = -5.0   [0x145b1d940]
0x14422cb6d  dest.z = dest.z + dz
0x14422cb77  clamp dest.z to +/- ([pitchDim+8] - 1.5)
0x14422cba7  dest.x = sign(dest.x) * [pitchDim+0]   ; his OWN goal line
```

**The only decision in the whole class is `desc.angle < 90.0`.** No RNG, no attribute, no
difficulty. The descriptor is the tagged target on the keeper's own action record and it carries a
9-bit aim angle. **Whether that angle is the penalty taker's published aim or a keeper-side
instruction is NOT established** — the writer of that descriptor was not traced. [c on the
provenance, b on everything else.]

`ActionKeeperPKSaving` (7-slot, `+0x13828`): vf4 `0x14422d4d0` (147 B) calls the generic resolver
`0x145625a20`, requires target kind **3**, then `0x14421d350` (shared with `ActionKeeperCatching`)
and `0x14422d570`. vf6 `0x14422cc00` is the 250-frame trajectory scan with the flat 3.5 m reach
gate. **No left/right branch, no RNG, no attribute beyond HEIGHT** — re-confirmed. [b]

**Answer to "is the penalty dive random, read from the kicker, or guessed?"** The *side* is a single
half-plane read of an aim angle held on the action record before the ball is struck; the *save* is
then a deterministic trajectory intercept. **It is not random.** Whether the angle is honestly the
kicker's aim is the open half; the `_moveOtherside` animation variants exist precisely for the case
where the commitment was wrong, which is consistent either way.

The penalty animation family, from `ef_anime_names.json` joined to `CancelData.bin`: [a]

| id | name | len (fr) | len (s) | cancel keys |
|---|---|---|---|---|
| 851 | `gkprejump_0_0_pk_far_high` | 20 | 0.33 | **none** |
| 852 | `gkprejump_0_0_pk_far_high_moveOtherside` | 36 | 0.60 | **none** |
| 858 | `gkprejump_0_0_pk_far_low` | 52 | 0.87 | **none** |
| 872 | `gkprejump_0_0_pk_far_low_moveOtherside` | 58 | 0.97 | **none** |
| 934 | `gkprejump_0_0_pk_front_high` | 78 | 1.30 | **none** |
| 935 | `gkprejump_0_0_pk_front_high_moveOtherside` | 86 | 1.43 | **none** |
| 944 | `gkprejump_0_0_pk_front_low` | 58 | 0.97 | **none** |
| 945 | `gkprejump_0_0_pk_front_low_moveOtherside` | 65 | 1.08 | **none** |
| 948 | `gkprejump_0_0_pk_Otherside` | 52 | 0.87 | **none** |
| 952 | `gkprejump_0_0_pk_cancel` | 30 | 0.50 | **none** |
| 953 | `gkprejump_0_0_pk_high_movefront` | 40 | 0.67 | **none** |
| 1024 | `gkprejump_0_0_pk_low_movefront` | 86 | 1.43 | **none** |
| 1025 | `gkprejump_0_0_pk_Otherside_moveOtherside` | 64 | 1.07 | **none** |
| 1027 | `gkprejump_0_0_pk_cancel_moveOtherside` | 62 | 1.03 | **none** |
| 1028 | `gkprejump_0_0_pk_front_movefront` | 72 | 1.20 | **none** |
| 83 / 84 | `gkmovemid_pk_0_0_ver16` / `_ver17` | 80 / 90 | 1.33 / 1.50 | **none** |

Structure: **(far / front / Otherside) × (high / low)**, with `_moveOtherside` / `_movefront`
recovery variants and an explicit `_cancel` (stand still). **Not one of them can be interrupted.**

### 4.2 Coaching is the goal kick, not the wall

`ActionKeeperCoaching` (vftable `0x146bbfbe8`, `+0x13980`) overrides **0, 16, 18** only. vf4 is the
base ("my own position") and vf20 is the base — **it never moves the keeper and never emits a
steering point**. Both real bodies compute one integer and store it in the same place: [b]

```
vf18 0x14422e410:
  call the base packager 0x145625830
  side from entity index
  if (0x1442cad30(teamObj, side))            return false
  if (0x1442e2a60(match, entityIdx))         return false
  rec = 0x1443395a0(entityIdx)
  if (byte[rec+0xc3] != 0)
      work+0x1050 = (env->[0x33e4] != 1)     ; 0 or 1
  return true

vf16 0x14422e510:
  call the base 0x145626100
  if (player+0x568 == 0x54) return false
  for i in 0..0x17:
     skip if (flagbyte & 8) or entityIdx > 0x15 or side mismatch
     r = 0x144308140(x, i) ; c = byte[r+0x10] else byte[r] ; c &= 0x7f
     if (c == 0x1b)  work+0x1050 = (env->[0x33e4] != 1)
  return false
```

And its entire animation set is two entries: [a]

```
1452  gkcoaching_high_0_0_lower_goalkick   140 fr (2.33 s)  no cancel
1453  gkcoaching_high_0_0_up_goalkick      160 fr (2.67 s)  no cancel
```

`lower` / `up`, both suffixed `_goalkick`. **`work+0x1050` selects which of the two gestures**, and
the selector is `env+0x33e4 != 1`. Meanwhile the defensive wall is `wall_idle`, `wall_idle2/3`,
`wall_runup`, `wall_runup_cancel`, `wall_jump_high` ×4, `wall_jump_cancel` ×3 — **twelve non-`gk`
animations** — so the wall is outfield players and nothing in `ActionKeeperCoaching` touches it. The
open question "whether it organises a wall" is **answered: no.** [b + a]

### 4.3 MoveFreeKick

`ActionKeeperMoveFreeKick` (vftable `0x146be0348`, `+0x13790`) overrides **0, 3, 4, 12, 13, 16, 17,
20**. Its vf4 (`0x144176d70`) and vf3 (`0x14422c6d0`) have **no `.pdata` chunks**, i.e. they are
leaf/thunk bodies — which is why a chunk-based dump of them comes back empty. The existing
chapter's "requests id 3 twice" resolves: **vf12 is the shared two-instruction `mov eax,3; ret`
(`0x14140d670`)**, the constant that normally occupies vf13; vf13 here holds a real body. [b]

vf13 `0x14422c600` is a small distance classifier — `|keeper − point|` against `0.1` and `1.0` by
default, or `0.09` and `1.01`/`0.99` depending on `0x144325d80`'s 3-way return — returning 0, 1 or
2. `0x146485b08` (1.01) has refcount 11 and is attributed only to `ActionKeeperMoveFreeKick` plus
unattributed sites. vf17 `0x14422c6e0` calls the base packager, writes `-1.0f` through the caller's
out-pointer, and copies `this+0x58..0x60` as the point. [b]

### 4.4 Makeshift

Unchanged and re-confirmed by a fresh dump: `ActionKeeperMakeshift::slot6` (`0x144220f30`) is 12
instructions — copy facing to `work+0xe74`, `+0xe7c = 1.0f`, `+0xe88 = 0xff`, `+0x1047 = 1`, return
true. **An outfield player in goal gets no keeper behaviour from this class.** [b]

---

## 5. The motion side — how long a keeper is committed

Measured with `tools/mbinfo_ef.py` (12-byte `CancelData` records, 13-bit ids,
`frame = (((v>>13)&0x3FF)+2)*2`, 60 fps) over the shipped tables. **1,250 animations whose name
starts `gk`.** The "first cancel key" is the earliest frame at which `canCancel` (action slot 14)
can let a queued action through; before it the keeper cannot act. [a]

| family | n | with a cancel key | first cancel s (min / med / max) | motion length s (min / med / max) |
|---|---|---|---|---|
| `gkcatch` | 156 | 126 | 0.167 / **0.392** / 0.867 | 0.400 / 1.100 / 4.500 |
| `gkdeflect` | 132 | 92 | 0.150 / **0.392** / 1.050 | 0.433 / 1.233 / 4.200 |
| `gkrise` | 100 | 94 | 0.133 / **0.508** / 2.633 | 0.367 / 1.100 / 5.067 |
| `gkmovenear` | 82 | 13 | 0.133 / 0.217 / 0.550 | 0.233 / 0.650 / 3.000 |
| `gkprejump` | 73 | **9** | 0.117 / 0.250 / 0.383 | 0.133 / 0.600 / 1.533 |
| `gkcollapsing` | 55 | 22 | 0.133 / 0.342 / 0.550 | 0.633 / 1.067 / 1.900 |
| `gklying` | 48 | 31 | 0.183 / 0.383 / 0.900 | 0.467 / 0.767 / 1.200 |
| `gkdeflectscoop` | 46 | 21 | 0.250 / 0.400 / 0.733 | 0.400 / 0.967 / 2.300 |
| `gkgoalkick` | 44 | 27 | 0.717 / **1.283** / 1.633 | 0.333 / 0.967 / 4.067 |
| `gkmoveSeriesA` | 44 | 3 | 0.150 / 0.250 / 0.283 | 0.367 / 0.600 / 1.067 |
| `gkblockcover` | 41 | 29 | 0.183 / 0.300 / 0.817 | 0.567 / 1.000 / 2.600 |
| `gkdeflectlate` | 38 | 31 | 0.233 / 0.383 / 0.550 | 0.567 / 1.100 / 5.867 |
| `gkdeflectClear` | 31 | 26 | 0.217 / 0.383 / 0.517 | 0.400 / 1.100 / 3.067 |
| `gkpunch` | 30 | 26 | 0.367 / 0.433 / 0.717 | 0.467 / 1.333 / 2.767 |
| `gkunderthrow` | 29 | 23 | 0.050 / 0.700 / 0.867 | 0.333 / 1.267 / 2.900 |
| `gkmoveSeriesB` | 27 | 1 | 0.233 | 0.333 / 0.633 / 1.267 |
| `gkseeoff` | 22 | 15 | 0.250 / 0.567 / 1.033 | 0.167 / 1.467 / 7.000 |
| `gkmovemid` | 20 | **0** | — | 0.600 / 4.067 / 7.067 |
| `gkEmagencyMove` | 18 | 7 | 0.200 / 0.383 / 0.600 | 1.100 / 1.300 / 1.500 |
| `gkoverthrow` | 18 | 18 | 0.150 / 0.867 / 1.333 | 0.533 / 2.183 / 3.400 |
| `gknearmovestep` | 17 | **0** | — | 1.000 / 2.500 / 2.733 |
| `gksavingCancel` | 17 | 16 | 0.167 / 0.267 / 0.517 | 0.700 / 1.383 / 2.533 |
| `gkblock` | 16 | 8 | 0.300 / 0.542 / 0.933 | 0.867 / 1.333 / 5.467 |
| `gkpuntkick` | 15 | 15 | 0.417 / 0.917 / 1.117 | 0.400 / 3.233 / 4.233 |
| `gkcollapsingnear` | 15 | 10 | 0.117 / 0.267 / 0.383 | 0.467 / 1.200 / 1.667 |
| `gkscoopout` | 13 | 9 | 0.283 / 0.433 / 0.700 | 0.767 / 1.333 / 1.967 |
| `gkmovehigh` | 12 | 10 | 0.167 / 0.425 / 0.517 | 0.567 / 1.167 / 3.667 |
| `gkfall` | 8 | 2 | 0.700 / 0.950 / 1.200 | 1.433 / 1.933 / 3.267 |
| `gkmovelow` | 8 | 5 | 0.083 / 0.117 / 0.133 | 0.533 / 0.967 / 3.500 |
| `gkpickupball` | 6 | 6 | 0.217 / 0.542 / 0.833 | 0.467 / 1.300 / 2.067 |
| `gkdropball` | 6 | 2 | 0.217 / 0.475 / 0.733 | 0.500 / 0.733 / 1.867 |
| `gkstagger` | 6 | 6 | 0.467 / 0.592 / 0.983 | 1.533 / 1.867 / 2.667 |
| `gkclear` | 5 | 2 | 0.417 / 0.492 / 0.567 | 1.167 / 1.883 / 2.400 |
| `gkcoaching` | 2 | **0** | — | 2.333 / 2.500 / 2.667 |

(the smaller of the 49 families are omitted; the full table came from the same command)

**The keeper equivalent of the post-tackle lockout.**

* A **dive is committed for a median 0.392 s** before it can be cancelled, inside a 1.233 s motion.
  The fastest abortable dive is 0.150 s, the slowest 1.050 s.
* The real cost is **getting up**: `gkrise` cannot be cancelled for a median 0.508 s and the motions
  run 1.100 s. **A dive-and-recover cycle is ~2.3 s of median motion with ~0.9 s hard-locked.**
* **518 of 1,250 gk animations (41 %) have no cancel record at all** — locked for the whole motion,
  median 0.833 s, max 7.067 s. All but 9 of the 73 `gkprejump` entries are in this set, and every
  penalty pre-jump is.
* **37 of the 640 gk animations that have both a length and a cancel key have their first key at or
  past the motion end** — e.g. `gkpickupball_0_0` is 28 frames long with its first key at frame 47;
  `gkpuntkick_side_3_0` 24 frames with a key at 50. Those are effectively uncancellable too, and it
  is a data oddity worth knowing before anyone edits `CancelData`.
* For scale, from the same tool on the same tables: the tackler's own animation first-cancels at a
  median **0.300 s**, slides at **0.367 s**, staggers at **0.267 s**. **Keeper dives are ~30 %
  longer commitments than a slide tackle, and the recovery is longer again.**

`HoldData.bin` is dominated by `gkcatch` / `gkblockcover` / `gkprejump` hand geometry (378 records,
bones 7 and 11, a mirrored pair) — already noted in the anime chapter as a goalkeeper-hands lever.

---

## 6. Class status

Vtable addresses and slot counts from `build/exe_map.json`, cross-checked against raw PRISTINE
qwords for every class this chapter changes.

### 6.1 `match::player` — 25 `ActionKeeper*` plus 2 keeper-adjacent

| class | vftable | slots | best body | status | note (this chapter) |
|---|---|---|---|---|---|
| `ActionKeeperAfterCatchMove` | `0x146bc0028` | 23 | vf20 `0x144230d10` | gate-only | unchanged; six private bearing cells `0x146be3d10..` (`90.1` refcount 1) |
| `ActionKeeperBasePosition` | `0x146bbfae8` | 23 | vf4 `0x144223580` | **decoded further** | depth chain, the 16.42 m consumer, the GK-Awareness window, the `0x46` flag. **vf18 (7 KB) still only partly read** |
| `ActionKeeperBlock` | `0x146bbf9a8` | 7 | s6 `0x14421f8c0` | gate-only | unchanged |
| `ActionKeeperBlockLate` | `0x146bbf9e8` | 7 | s6 `0x14421fee0` | gate-only | unchanged; the only GK save-attribute read in the executor layer (`0x25` @ `0x14421ff95`), consumer still untraced |
| `ActionKeeperBodyFeint` | `0x146bbfce8` | 23 | vf4 `0x14422f110` | gate-only | unchanged; requests id `0x52` |
| `ActionKeeperCatching` | `0x146bbf8e8` | 7 | s6 `0x14421d3a0` | decoded | unchanged |
| `ActionKeeperCoaching` | `0x146bbfbe8` | 23 | vf18 `0x14422e410`, vf16 `0x14422e510` | **decoded** | writes only `work+0x1050`; the goal-kick up/down gesture, **not** the wall |
| `ActionKeeperDeflect` | `0x146bbf968` | 7 | s6 `0x14421e600` | gate-only | unchanged |
| `ActionKeeperDropBall` | `0x146bdbe38` | 7 | s6 `0x144218a60` | listed-only | unchanged |
| `ActionKeeperMakeshift` | `0x146bdf7b8` | 7 | s6 `0x144220f30` | decoded | re-confirmed near-stub |
| `ActionKeeperMoveFreeKick` | `0x146be0348` | 23 | vf16 `0x14422c740`, vf20 `0x14422c460` | **partly decoded** | vf12 is the shared `return 3`; vf13 `0x14422c600` is a 3-way distance classifier; vf3/vf4 are leaf bodies with no pdata |
| `ActionKeeperMovePenaltyKick` | `0x146be09a8` | 23 | vf16 `0x14422ca70` | **decoded** | goal-line pin + ±5 m z step from one `angle < 90.0` test |
| `ActionKeeperPKSaving` | `0x146bbfba8` | 7 | s6 `0x14422cc00`, s4 `0x14422d4d0` | decoded | vf4 added: generic resolver, target kind 3, shares `0x14421d350` with Catching |
| `ActionKeeperPickupBall` | `0x146bbfda8` | 7 | — | stub | re-confirmed: no own body |
| `ActionKeeperPreSaveOperation` | `0x146bbfca8` | 7 | s4 `0x14422e6a0` | decoded | unchanged |
| `ActionKeeperPress` | `0x146bdc420` | 23 | vf4 `0x1442196b0`, vf6 `0x14421c0c0`, vf20 `0x144218f10` | **decoded further** | 15 m / 7 m trigger, angle-sector + 10 km/h engage filter. **vf5 is the path half, not the decision** |
| `ActionKeeperPunching` | `0x146bbf928` | 7 | s6 `0x14421e1f0` | listed-only | unchanged |
| `ActionKeeperPuntKick` | `0x146bbf828` | 7 | s6 `0x144215220` | gate-only | its `team+0x275c` read is at `0x14421553b`; the writer is now known (§ 2) |
| `ActionKeeperSavingMove` | `0x146bbff68` | 23 | vf20 `0x14422f660` | gate-only | unchanged |
| `ActionKeeperScoopOut` | `0x146bbfa68` | 7 | s6 `0x144220c50` | listed-only | unchanged |
| `ActionKeeperSeenOff` | `0x146bbfde8` | 23 | slot7 `0x14422f260` | listed-only | unchanged; the only class in 55 that overrides slot 7 |
| `ActionKeeperSnapUnder` | `0x146bbfaa8` | 7 | s6 `0x144220e30` | listed-only | unchanged |
| `ActionKeeperTackle` | `0x146bbfa28` | 7 | s6 `0x1442202c0` | listed-only | unchanged; 68-fn closure, HEIGHT only, no RNG |
| `ActionKeeperThroughThrow` | `0x146bbf8a8` | 7 | s6 `0x144218450` | gate-only | reads `team+0x275c` at `0x1442184a5` |
| `ActionKeeperThrow` | `0x146bbf868` | 7 | s6 `0x1442176b0` | gate-only | reads `team+0x275c` at `0x14421780b`; private cells `0x146bdb2dc/e0` (16.6667 / 133.3333, refcount 1 each) |
| `ActionGkCoachingRun` | `0x146bbf1e8` | 23 | vf4 `0x14420a340` | listed-only | unchanged |
| `match::ai::PlayerGKAuto` | `0x146bbe008` | 1 | — | stub | re-confirmed: destructor only |

### 6.2 `match::anime::action::goal_keeper::` — **15 vtables, not 14**

| class | vftable | slots | status |
|---|---|---|---|
| `SavingBase` | `0x146b58840` | 50 | decoded (anime chapter) |
| `Block` | `0x146b59148` | 50 | decoded — id `0x49`, Reach, 60-frame budget |
| `Catch` | `0x146b598e0` | 50 | decoded — id `0x44`, Catching, 60-frame budget |
| `Deflect` | `0x146b5a018` | 50 | decoded — id `0x46`, Reflexes/Reach, 90/48/60-frame budget; **vf37 multiplies by zero** |
| `Punch` | `0x146b5aea0` | 50 | decoded — id `0x45`, Clearances |
| `ScoopOut` | `0x146b5a758` | 50 | decoded — id `0x48`, Reach, 30/60-frame budget |
| `SnapUnder` | `0x146b5c370` | 50 | decoded — id `0x47`, Catching, 15-frame budget; **vf37 multiplies by zero** |
| `AfterCatchBase` | `0x146b49ad0` | 33 | listed |
| `PuntKick` | `0x146b49be0` | 33 | listed |
| `Throw` | `0x146b49de0` | 33 | listed |
| `BodyFeint` | `0x146b49710` | 29 | listed |
| `DropBall` | `0x146b49800` | 29 | listed |
| `PickupBall` | `0x146b498f0` | 29 | listed |
| `PreSaving` | `0x146b499e0` | 29 | listed |
| `SeeOff` | `0x146b49cf0` | 29 | listed |

Three distinct contracts: **50 slots** (the seven save classes), **33 slots** (the three
distribution / after-catch classes) and **29 slots** (the five miscellaneous ones, = `action::Base`
exactly).

---

## 7. Tunables

| what | site | route | effect | evidence | sharers |
|---|---|---|---|---|---|
| **GK-Awareness anticipation** — the biggest keeper lever found | attribute `0x16`, per player | **player data (`master.db` → Player.bin)** | BUDGET `floor(fps·0.25·norm)` frames, ONSET `fps·(0.5 − 0.33·norm)` frames. **Never author a keeper at 40–43**: the branch is dead below 44 | b | per-player |
| **GK engagement radius** 269.6164 = 16.42 m, stored squared | `0x146bdfd90`, sole referrer `0x144224d1d` | **exe constant — private, refcount 1, in-place edit is safe** | the radius inside which the keeper notices an opponent's action at all. Write R², not R | b + census | **1** |
| **keeper base depth** | the formation GK slot coordinate at `teamAI + slot·20 + 0x40` | **team/formation data — no patch at all** | moves the base spot one-for-one, up to the ±10 m clamp against `team+0x799c` | b (arithmetic), c (array identity) | per-team |
| **come-out trigger 15.0 m** | `0x146a0476c` = 225.0, tested at `0x14421c9d7` | exe code — **NOT a private cell** (refcount 118) | lowering keeps him home; raising makes him a sweeper. Needs a cave or an instruction-local rewrite | b + census | 118 |
| **come-out trigger 7.0 m** (the `team+0xb3bd == 0` branch) | `0x146a6fa18` = 49.0, tested at `0x14421c9ac` | exe code — **NOT private** (refcount 73) | as above | b + census | 73 |
| **distribution short/long split 30 m / 40 m** | `0x145a8dd80` (30.0) @ `0x145655595`; `0x145d58ec8` (40.0) @ `0x145655aed` | exe code — both heavily shared | which distribution action the keeper requests (`0x41` vs `0x40`) | b | shared |
| **`ActionKeeperThrow` private constants** 16.6667 / 133.3333 | `0x146bdb2dc` / `0x146bdb2e0`, refcount 1 each | exe constant — private, safe to experiment | bounds on the throw solution; roles still not fully read | c | 1 / 1 |
| **`ActionKeeperAfterCatchMove` bearing quadrants** 90.1 / 179.9 / 180.1 / 269.9 / 359.9 / 360.1 | `0x146be3d10..0x146be3d28`, refcount 1 each | exe constant — private | a bearing classifier; consumer not read | c | 1 each |
| **keeper dive lockout** | `Mbinfo/bin/CancelData.bin`, the 732 `gk*` records that have keys | **motion asset** — LOCATE solved, PACK not (anime chapter's write gate) | the only per-animation route; e.g. move `gkdeflect`'s median 0.392 s without touching outfield contact | a (read-only) | per-motion |
| **penalty dive commitment** | the 15 `gkprejump_0_0_pk_*` records have **no** cancel keys | motion asset — same gate | adding a key would let a keeper abort a PK dive; today he cannot | a | per-motion |
| **the per-player flags `0x46` (positioning) and `0x12` / `0x14` (distribution)** | `playerRec+0xc0` bitfield, read via `0x1442c0000` | **player data** — *if* the index→skill map is recovered | switches the sweeper branch and the throw/punt variants on and off per keeper | b (the reads); **names not established** | per-player |
| **NOT SAFELY TUNABLE — the depth caps 4 / 15 / 20 / 42 m** | `0x145ab1b48`, `0x145c0b000`, `0x145a8aa44`, `0x145ec9ef0` | — | all four shared (63 / image-wide / image-wide / 26 across six classes). Editing 42.0 alone touches `ActionSelectorDiagonalRun`, `Team`, `ThinkUnitShoot`, `ActionBasePosition` | b + census | 26+ |
| **NOT SAFELY TUNABLE — the penalty ±5.0 m** | `0x145a8dd78` / `0x145b1d940` at `0x14422cb5b` / `0x14422cb65` | — | 5.0 and −5.0 are among the most shared floats in the image | b | very high |
| **NOT REACHABLE — dt270 `basePosition.gk*`** | 20 fields, 6 readers, all outfield | — | no keeper executor reads dt270 at all (§ 1.6) | b | — |

---

## 8. Negatives

* **dt270 has no goalkeeper tunable.** 20 `gk*` fields in `basePosition`, 6 read, all six inside the
  outfield goal-kick shape layer; 0 dt270 reader sites anywhere in the keeper executor band. Across
  all 245 dt270 objects the only other `gk` fields are match-rating fields. [b]
* **No ability gates the keeper coming out.** The only attribute in the entire `ActionKeeperPress`
  family (vf4, vf5, vf6, vf18, vf20) is HEIGHT (`0x32`), and it feeds a steering parameter. [b]
* **No RNG in the distribution brain.** Zero RNG call sites in `0x145655430` or in its three private
  target-finders `0x143d104b0` / `0x143d0ff40` / `0x143d10220`. [b]
* **No RNG and no attribute in `ActionKeeperMovePenaltyKick`.** One class, one overridden slot, one
  comparison. [b]
* **`ActionKeeperCoaching` does not organise the wall.** Two bodies, one output field, two
  animations, both named `_goalkick`. The wall animations are twelve `wall_*` entries with no `gk`
  prefix. [b + a]
* **The PK animation ids are not in a table in the exe.** A u16/u32 scan for the fifteen
  `gkprejump_0_0_pk_*` ids finds no cluster (851 and 934 never appear within 64 bytes of each other
  anywhere in the image), so the concrete animation is resolved through the `AnimeTable` layer from
  a direction/height request, not from a hard-coded id list. **Negative control**: the same scan
  finds 2,101 and 2,135 scattered u16 hits for those two ids, so the scan was not simply empty. [b]
* **A pattern-search bug, reported because it nearly became a wrong answer.** My first
  `team+0x275c` scan reported only **one** executor reader (`ActionKeeperThrow`) and I was about to
  conclude the other two used a different field. The cause was an off-by-one in the
  instruction-boundary walk (`range(3,12)` instead of `range(1,13)`), which cannot decode
  `8b 88 5c 27 00 00` — the displacement starts 2 bytes into the instruction. Fixed, the scan finds
  all three readers, matching the finished chapter. This is the third time in this project that a
  single-encoding assumption produced a confident wrong negative.
* **Not proven: what `0x1442eb950`'s `dword[event+0x14]` is.** The `>= 2·fps` comparison is in the
  bytes; reading the field as "frames since the restart" is inference, so "the keeper holds the ball
  for two seconds" is **not** claimed here.
* **Not proven: who writes the penalty aim descriptor.** The keeper reads a 9-bit angle from his own
  action record's target descriptor. That it is the kicker's aim is plausible and unproven.
* **Not proven: the names of flag bits `0x46`, `0x12`, `0x14`.** The reads are solid; the mapping
  from bit index to a named skill or playstyle is not.
* **Not proven: `ActionKeeperPress::vf6`'s mode/gait ints.** `[r15] ∈ {2,3}` and `[rsi] ∈ {2..5}`
  are written; their consumer was not traced, so "mode 2 = hold" is a label, not a proof.

---

## 9. contradicts_given

* **"the 14-class `match::anime::action::goal_keeper::` save family"** — `exe_map.json` holds **15**
  `goal_keeper::` vtables (`SavingBase`, `AfterCatchBase`, `Block`, `BodyFeint`, `Catch`, `Deflect`,
  `DropBall`, `PickupBall`, `PreSaving`, `Punch`, `PuntKick`, `ScoopOut`, `SeeOff`, `SnapUnder`,
  `Throw`), and the brief's own list names all 15. They fall into three contracts — 50 / 33 / 29
  slots — not one. [b]
* **"the ~30 ActionKeeper* executors … 23-slot movement contract or 7-slot kick contract per
  class"** — the count of `ActionKeeper*` classes is **25**; with `ActionGkCoachingRun` and
  `match::ai::PlayerGKAuto` the keeper-adjacent total is **27**, and `PlayerGKAuto` (1 slot,
  destructor only) fits neither contract. [b]
* **"at the executor layer almost no keeper ability matters — only GK Awareness, through a ≤ 0.5 m
  standing error … the ONLY RNG in the keeper executors"** — the RNG half is right and "only GK
  Awareness (as an attribute)" is right, but **the ≤ 0.5 m error is the least of what GK Awareness
  does**. Two further `0x16` reads (`0x1442254c2`, `0x14422aba3`) build an anticipation window and a
  trajectory look-ahead, with a hard cliff at 44. And **GK Awareness is not the only per-player
  input**: flag bit `0x46` gates two keeper-positioning branches. [b]
* **"`0x144032870` … floors Reach at 52 and Reflexes at 65"** — the finished chapters already
  corrected this to **output** 50 and 63 (the inline immediates are 52 and 65, then a ×0.98 pass
  below 90). The brief still carries the uncorrected numbers. [b, per
  anime-keeper-and-first-touch.md]

---

## 10. Corrections to the finished chapters

**To [player-executors.md](player-executors.md):**

1. **§ The goalkeeper → "The one random number"** — "That is the whole 'does a bad keeper get caught
   out of position' model" is wrong. `0x1442246d0` at `0x1442254c2` and
   `ActionKeeperBasePosition::vf18` at `0x14422aba3` each read attribute `0x16` and build frame
   budgets from it (§ 1.4). The 0.5 m error is one of three GK-Awareness terms and the least
   consequential.
2. **§ The input census → "attributes — keepers"** — the row lists GK_DECISION `0x16` as read
   "BasePosition ×3" without saying what the other two do, and it **omits the per-player flag table
   entirely**. Bit `0x46` of `playerRec+0xc0` is read at `0x1442223a7`
   (`ActionKeeperBasePosition::vf20`) and `0x144226c64` (the vf4 helper `0x1442260f0`) via
   `0x1442c0000`. There is per-player individuality in keeper positioning beyond one attribute.
3. **Class status → `ActionKeeperPress`** — "vf5 (0xc3b bytes, the come-out decision) NOT decoded".
   **vf5 is not the come-out decision.** It opens with a 0.316 m "already there" early-out and is
   the path/steering half. The come-out decision is in **vf6** (`0x14421c0c0`, 4,739 B) with the
   15 m / 7 m gate, and the engage geometry is in **vf4**. vf5 remains undecoded but should be
   re-labelled.
4. **Class status → `ActionKeeperCoaching`** — "Whether it organises a wall is not established"
   becomes **"decoded: it does not. It writes one int to `work+0x1050` selecting between two
   goal-kick gestures."**
5. **Class status → `ActionKeeperMoveFreeKick`** — "requests id 3 twice" is a misreading: **vf12** is
   the shared two-instruction `mov eax,3; ret` at `0x14140d670` (the constant that normally occupies
   vf13), and vf13 holds a real body `0x14422c600`. Also its vf3 (`0x14422c6d0`) and vf4
   (`0x144176d70`) have **no `.pdata` chunks**, which is why a chunk-based dump of them comes back
   empty.
6. **Class status → `ActionKeeperMovePenaltyKick`** — "overrides one slot; no own vf4, no vf20 — the
   penalty stance is inherited" is right about the slots and wrong about the conclusion. **The one
   override, vf16, IS the penalty stance**, and it contains the entire left/right commitment.
7. **§ Tunables → "GK engagement radius"** — "Its exact consumer condition inside `0x1442246d0` is
   only partly read" can be closed: § 1.3 gives the full gate.
8. **§ Open 12 and the `ActionKeeperBasePosition::vf18` row in § Open** — vf18's GK-Awareness
   look-ahead term is now read (§ 1.4); the rest of its 7 KB is still unread.

**To [ball-carrier-brain.md](ball-carrier-brain.md):**

9. **§ "Six registered units never run"** — the negative on `GKDribble` (0x19), `GKPassShort` (0x1a)
   and `GKPassLong` (0x1b) is correct and can now be **explained**: the goalkeeper's on-ball
   decisions run in `0x145655430`, a separate object at `bp+0x6ce8` selected by `0x14562cad0` on the
   same `teamObj+0x42b8` role-code array the brain uses. The three units are dead because keeper
   distribution never enters the ThinkUnit list, not because the list builder happens to omit them.

**To [anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md):**

10. **§ 1 "Seven classes share it" and the "(14 classes)" row in § 3** — the namespace holds **15**
    vtables in three contracts (50 / 33 / 29 slots). The 114-method figure is a count of distinct
    method bodies, not of classes, and should say so.

---

## 11. Open

1. **Name the per-player flag bits.** `0x1442c0000` indexes a 73-entry bitfield at `playerRec+0xc0`.
   Bit `0x46` gates keeper positioning; `0x12` and `0x14` gate distribution.
   `src/ML.Core/Development/PlayerSkillCatalog.cs` says the names live in
   `dt261 all.str [66105..66178]` (74 strings), but its array is thematically grouped. **Route: dump
   `all.str` in original order, index it, and check whether index 0x46 is a GK-only skill.** That
   would turn three `[b]` reads into three named, editable player-data levers.
2. **Who writes the penalty aim descriptor** — the u32 at `rec+0x24` that `0x144317ec0` unpacks. If
   it is the kicker's aim, the keeper reads the penalty; if it is a keeper-side instruction, he is
   being told. This decides whether "the CPU keeper cheats on penalties" is true.
3. **`ActionKeeperBasePosition::vf18`** — 7,104 B, one term read. It holds `13.0`, `13.5`, `28000.0`,
   `85.0` and the `0.694444` (= 25/36) cell that also appears in `0x144228170`.
4. **`0x143d104b0` / `0x143d0ff40` / `0x143d10220` / `0x143d10840`** — the four private distribution
   target-finders (911 / 722 / 646 / 702 B). Not opened. They are where "who does the keeper throw
   to" actually lives.
5. **`0x145655dd0`** — the 416-byte sibling of the keeper brain taken when `bp+0x6d19` is false. Not
   read.
6. **`ActionKeeperPress::vf5`** (3,131 B) and **vf6** past `0x14421ca8b` — the mode/gait ints are
   written but their consumer was not traced.
7. **`team+0x799c`** — the team-level x reference the keeper's depth is clamped against. Writers not
   found.
8. **`0x144218d40`** — the final gate on `ActionKeeperPress::vf4`'s engage path. Not read.
9. **The 37 `gk*` animations whose first cancel key sits at or past the motion end.** Either the
   frame decode has an exception for short motions, or these are authoring errors that make the
   motions uncancellable. Worth settling before anyone edits `CancelData.bin`.
