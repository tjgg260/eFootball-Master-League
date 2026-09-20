# The goalkeeper — one machine, two subsystems (2026-09-20)

Everything a keeper does in a match, from where he stands before the shot to how long he lies on the
floor after it, read as **one machine**. There is no goalkeeping subsystem in the exe: the keeper is
split across **subsystem 2** (`match::player::ActionKeeper*`, 25 executor classes) and **subsystem 3**
(`match::anime::action::goal_keeper::*`, 15 vtables), plus one on-ball brain that lives in neither.
This chapter stitches those together and answers the question the other chapters keep handing back
and forth: **what does a goalkeeper's rating actually buy?**

**This is a synthesis chapter. It re-derives only what is load-bearing and cites the rest.** The
derivations live in:

| source | what it owns |
|---|---|
| [player-executors.md](player-executors.md) | the 25 `ActionKeeper*` classes, their slots, subobject offsets, closures and class-status rows |
| [anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md) | the 50-slot `SavingBase` contract, `0x144032870`, `0x143f31470`, the RNG closure work |
| [anime-actions.md](anime-actions.md) | `MbInfo` record layout, the `CancelData` frame decode, the 7,883-entry name table |
| [goalkeeping.md](goalkeeping.md) | the 2026-09-20 probe decode of positioning, distribution, one-on-ones, set pieces and the motion tables |
| [ball-carrier-brain.md](ball-carrier-brain.md) | the ThinkUnit list and the GK-unit negative this chapter explains |

**Evidence levels:** **a-emulated** (the game's own bytes run under Unicorn with controlled inputs
*for this write-up*), **a-quoted** (a measurement carried over from a probe, not re-run here),
**a-measured** (recomputed here from a shipped data file, not from the exe),
**b-disassembly** (followed instruction by instruction, extents from the *chained-unwind* `.pdata`
walk — `func_chunks`, never `func_range`), **c-inferred** (structural reasoning only). Addresses are
VAs at base `0x140000000`, no ASLR, decoded from `eFootball.exe.PRISTINE`. (PRISTINE is *not* stock —
it differs from the untouched binary by two bytes of hostname at `0x146e6fae3`, irrelevant here. The
installed image currently equals PRISTINE, and all 12 address ranges quoted below were byte-compared
between the two: **0 differing bytes**. [b])

**Re-derived for this write-up**, not taken on a probe's word: the save-quality selector
(a-emulated here from its own bytes, full 40..99 sweep, table in § 3), the two attribute floors
(`lea ebx,[rax+0x41]` @ `0x1440329b0`, `add ebx,0x34` @ `0x1440329d9`), the easy-catch remap
(`add ebx,0x49` @ `0x144032940`), the `Deflect::vf35` Reach gate (`cmp eax,0x55` @ `0x143f4ae10`),
the standing-error draw (`mov edx,6` @ `0x144228863`) and four animation-id resolutions through
`tools/data/ef_anime_names.json`. [a + b]

> **Read § Corrections before leaning on the two parent chapters.** Three of their keeper statements
> are wrong in ways that change what you would edit: *"the 0.5 m standing error is the whole GK
> Awareness model"* (it is the smallest of three terms), *"`ActionKeeperPress::vf5` is the come-out
> decision"* (it is `vf6`), and *"whether `ActionKeeperCoaching` organises a wall is not
> established"* (it does not; it is the goal-kick arm-wave).

> **And read Corrections 25–36 before quoting this chapter's own earlier revisions.** Adversarial
> review of the 2026-09-20 draft found four load-bearing defects in it, all repaired below and all
> re-derived from the bytes first: the save-quality integer has **four** consumers and the draft
> bounded only one (§ 3.1); the vf30 "no RNG at any depth" negative was **bounded at depth 4** one
> step short of an LCG (§ 4); § 8's seconds were printed under the **superseded** `CancelData` frame
> rule while quoting the proven one (§ 8); and `SavingBase::vf47` is **inherited by three subclasses**,
> so its motion id is not a dead placeholder (§ 9).

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| **make a bad keeper actually look bad** | **on the one route that has been followed end to end, you cannot**: the displacement multiplier in `0x143f31470` spans only **0.900 → 1.295**, worst-to-best **77–92 %** per save type (§ 3). But that is **one of four** consumers of the save-quality integer. A second, `0x14402a630`, uses a wider transfer whose measured arm runs **0.500 → 0.959 (52 %)**. **The block-wide range is NOT BOUNDED** (§ 3.1) | player data — capped by design *on the documented route only* | a-emulated, full 40..99 sweep; the other three routes b-disassembly |
| the one real behavioural cliff | `goal_keeper::Deflect::vf35` `0x143f4add0` returns **false unless GK Reach ≥ 0x55 = 85**. Below 85 a keeper loses a diving-parry *behaviour*, not a few percent of quality. Uncompressed, one byte, one referrer, one caller | exe code (`cmp eax,0x55` @ `0x143f4ae10`) **or** player data (author keepers either side of 85) | b, re-read from PRISTINE here |
| the second real cliff | **GK Awareness below 44 is dead.** The anticipation branch needs `BUDGET = floor(fps·0.25·norm) ≥ 1`, i.e. `attr ≥ 43.93`. Any keeper authored at 40–43 loses the behaviour entirely | player data — **never author a keeper at GK Awareness 40–43** | b ([goalkeeping.md § 1.4](goalkeeping.md)) |
| restore the bottom of the GK scale | the selector floors **Reach at an output 50** and **Reflexes at 63** (inline 52 / 65, then ×0.98 below 90). 23 points of the Reflexes scale are unreachable | exe code, instruction-local immediates `0x1440329b0` / `0x1440329d9` | a-emulated |
| make routine catches discriminate | on a ball **under 50 km/h** action `0x44` takes `max(Catching, Reflexes, Reach)` and remaps 40..90 into **73..89**. A single-attribute nerf is invisible; the floor immediate is `add ebx,0x49` @ `0x144032940` | exe code (cheapest single byte in the chapter) | a-emulated |
| move the keeper's starting depth | **team data, not a patch.** The base x is the formation's own GK slot coordinate (`teamAI + slot·20 + 0x40`), clamped ±10 m of `team+0x799c` and capped 4 / 15 / 20 / 42 m by state — and all four caps are shared cells | player/team data (formation editor) | b arithmetic, c on the array identity |
| a sweeper keeper | the private **16.42 m** engagement radius `0x146bdfd90` (stored squared, 269.6164, **refcount 1**) and the 15 m / 7 m come-out gate in `ActionKeeperPress::vf6` | exe constant (the radius is genuinely private) / exe code (the gates are shared cells) | b |
| ability-scale coming out | **not possible.** The only attribute anywhere in the Press family is HEIGHT `0x32`, and it feeds a steering parameter, not a decision | — | b |
| ability-scale distribution | **not possible.** The keeper's on-ball brain `0x145655430` reads HEIGHT and two flag bits; no passing, vision or technique attribute appears | — | b |
| make the penalty dive a guess | it already is not one. `ActionKeeperMovePenaltyKick::vf16` steps **±5.0 m** in z on a single `< 90.0` test of a **9-bit field (raw 0..511, units unproven)** unpacked from a descriptor reached through a pointer at `rec+0x20`. No RNG, no attribute, no difficulty | exe code — but the ±5.0 cells are among the most shared floats in the image | b |
| shorten the dive commitment | `CancelData.bin`: a `gkdeflect` is locked a median **0.850 s** and `gkrise` a median **1.083 s** (under the **proven** frame rule — § 8, and the earlier draft's halved figures); **41 % of gk animations have no cancel record at all** | motion asset — subject to the anime chapter's write gate (LOCATE solved, PACK unbuilt) | a |
| tune any of it through dt270 | **no.** `basePosition` has exactly 20 `gk*` fields, **6 read, 14 dead**, and all six readers are in the *outfield* goal-kick shape layer. Zero dt270 readers in the keeper executor band `0x144215000..0x144243000`; zero `get()` sites in any `goal_keeper::` body | — | b |
| CPU difficulty scaling the keeper | **none reaches a save.** Saves are identical on Beginner and Legend | — | b (anime chapter, re-checked not re-derived) |
| bind a save to a button | **impossible.** There is no `match::pad::ThinkUnit` for Catch, Punch, Deflect, ScoopOut or SnapUnder. Saves are engine-automatic | — | b |

---

## The keeper in one paragraph

Nothing about a goalkeeper is decided in one place. **Where he stands** is `ActionKeeperBasePosition`
in subsystem 2: his formation slot's own x, mirrored by attack direction, clamped ±10 m of a team
reference and capped by match state, with a ≤ 0.5 m random standing error and — the part the finished
chapters missed — a **GK-Awareness-scaled anticipation window** that lets a good keeper stop adjusting
and set himself up to a quarter of a second earlier. **Whether he comes out** is
`ActionKeeperPress::vf6`: a 15 m (or 7 m) squared-distance gate, an angle sector across him, a
10 km/h ball-speed floor and a requirement that the attacker already be committed to an animation —
six gates, **not one of them ability-scaled**. **What he does with the ball** is neither the carrier
brain nor any ThinkUnit but a private **2,461-byte** function `0x145655430` (4 chained chunks),
selected by a role-code fork on the same `teamObj+0x42b8` array the brain uses, which scores the
eleven team-mates by **height** and splits short from long at 30 m. **Whether the shot is saved** is
subsystem 3: the executor publishes an intercept and an action id, and the anime save classes ask
`0x144032870` for a **save-quality integer**, which picks exactly one of the four goalkeeping
attributes by action id and compresses it hard. That integer then goes to **four** different
consumers. The one that has been followed end to end, `0x143f31470`, turns it into a **multiplier
between 0.900 and 1.295** that scales an animation-authored displacement — but a second,
`0x14402a630`, applies a wider transfer (span 90, cap 130) whose measured arm runs **0.500 → 0.959**,
a third scales a 3-vector by 0.4..1.0, and a fourth converts it into a **frame delay** `(120−q)/16`.
**The block-wide effect of a keeper's rating is therefore not bounded by this chapter** (§ 3.1).
Almost nothing rolls a die: no RNG reaches the quality selector, the transfer, `canStart` or any
save-permission gate, but the save body `0x143f46370` does draw a random displacement of up to
~0.2 m into `player+0x442c`, which is read inside the undecoded `0x143f35ed0`. And **how long he is
then out of the game** is not code at all but the motion tables: a dive is committed for a median
0.850 s and getting up for another 1.083 s, making a dive-and-recover cycle roughly 2.3 s of median
motion with ~1.9 s hard-locked — about **6 %** longer than a slide tackle and ~27 % longer than a
standing tackle.

---

## 1. Positioning — where he stands

Owner: `ActionKeeperBasePosition`, vftable `0x146bbfae8`, 23-slot movement contract, subobject
`+0x13550`. Overridden slots **0, 3, 4, 6, 8, 9, 13, 15, 18, 20**. Full slot table and body sizes in
[goalkeeping.md § 1.1](goalkeeping.md); the corrected slot reading (**slot 4 is the destination, slot
20 is a fixed-radius steering direction**) is [player-executors.md](player-executors.md)'s headline
and it holds here.

**Depth.** In `0x144228170`: the base x is `teamAI + slot·20 + 0x40` (the formation slot's own
coordinate, [c] on the array identity) multiplied by the attack-direction sign, clamped to within
**10 m** of `team+0x799c`, plus a state term `25.0 + t·15.0`, then capped at **4 / 15 / 20 / 42 m**
depending on match state (`0x1442285ce..0x1442285f9`) and floored. **The route to a higher or deeper
keeper is the formation, not a patch** — every one of the four caps is a shared cell (42.0 at
`0x145ec9ef0` alone has refcount 26 across six unrelated classes). [b]

**The 0.5 m standing error.** Every `2·T` ticks: `RandInt(0..5) · 0.1 · (1 − clamp01((attr 0x16 −
40)/59))` metres, applied at 90° to his facing. `mov edx, 6` @ `0x144228863` (re-read from PRISTINE
here — a plain range bound, *not* an RNG stream index), `call 0x144345e50` @ `0x14422886f`,
`mulss xmm0,[0x145a8dd68]` (= 0.1). 40-rated → up to 0.500 m; 70 → 0.246 m; 99 → exactly 0.000 m.
[a-emulated, player-executors.md]

**What GK Awareness actually buys — the correction.** Attribute `0x16` (`DATA_PARAMETER_GK_DECISION`,
UI **GK Awareness**) is read at **three** sites, not one. Besides the standing error, `0x1442254c2`
(inside the vf4 helper `0x1442246d0`) and `0x14422aba3` (inside `vf18`) build **frame budgets**:

```
norm   = clamp01((attr − 40) / 59)
BUDGET = floor(fps · 0.25 · norm)          ; frames of animation the threat may have LEFT
ONSET  = fps · (0.5 − 0.33 · norm)         ; frames that must already have ELAPSED
gate   : REMAINING <= BUDGET               ; cmp ecx,eax ; jg  @0x144225565
      && ELAPSED   >  ONSET                ; cmp dx,ax   ; jbe @0x14422557e
      && |Δbearing| > 40.0                 ; @0x1442255b2 comiss 40.0 ; ja 0x144225a29
      -> return immediately (0x144225a29 is the epilogue): stop adjusting, set yourself
```

**All three terms are required** — the earlier draft printed a two-term gate and so overstated how
often the anticipation behaviour fires. The bearing term compares `teamAI + idx·4 + 0x25b64`
(index bounded `cmp eax,0x15`, else 0.0) against `rec+0x1cc` through `0x143c6ff30`, absolute value
via `0x140a22910`. Re-read from PRISTINE for this repair. [b]

At 60 fps: [b, arithmetic over the disassembly]

| GK Awareness | norm | BUDGET (fr) | ONSET (fr) | ONSET (s) | branch reachable? |
|---|---|---|---|---|---|
| 40 | 0.000 | **0** | 30 | 0.500 | **no** |
| 43 | 0.051 | **0** | 29 | 0.483 | **no** |
| **44** | 0.068 | 1 | 28 | 0.467 | yes |
| 50 | 0.169 | 2 | 26 | 0.433 | yes |
| 60 | 0.339 | 5 | 23 | 0.383 | yes |
| 70 | 0.508 | 7 | 19 | 0.317 | yes |
| 80 | 0.678 | 10 | 16 | 0.267 | yes |
| 90 | 0.847 | 12 | 13 | 0.217 | yes |
| 99 | 1.000 | **15** (0.250 s) | 10 | 0.170 | yes |

`vf18` reads the same attribute at `0x14422aba3` and lerps a **ball look-ahead** frame index with it,
capped at 20 frames. (Note for anyone hooking that function: `mulss xmm6,xmm9` @ `0x14422abf9` and
`divss xmm6,xmm9` @ `0x14422ac22` **cancel exactly** — `xmm9` is a dead multiply.) [b]

**A per-player boolean nobody had found.** `0x1442c0000(rec, idx)` is a 73-entry bit table
(`bit idx of dword[rec + 0xc0 + (idx>>5)·4]`, bound `cmp edx,0x49`). **Bit `0x46`** is read at
`0x1442223a7` (`vf20`) and `0x144226c64` (the vf4 helper `0x1442260f0`), in both cases as the
precondition for an *"is the ball outside this rectangle"* test — the shape of a sweeper-keeper
enable. **Its name is not established** (§ Open 1). [b]

**The private 16.42 m gate, consumer decoded.** `0x146bdfd90 = 269.6164 = 16.42²`, census
`status=private, refcount=1, classes=[ActionKeeperBasePosition]`, sole referrer `0x144224d1d`. Inside
that radius the keeper is allowed to **classify the nearest opponent's current action** through five
action-id bit predicates (`0x144311e40` bit 21, `0x144311bf0` bit 10, `0x1443122e0` bit 25,
`0x144311c90` bit 23, `0x144311cb0`), then either a 144.0 (= 12 m) squared test or an
animation duration/elapsed window against `fps·0.3` / `fps·0.5`, producing 1.5 (engage) vs 0.5
(hold). It is a *notice* radius, not a move distance. [b]

---

## 2. The shot arrives — the hand-off from subsystem 2 to subsystem 3

Three executors do the shot-stopping arithmetic and none of them reads a goalkeeping attribute:

* `ActionKeeperPreSaveOperation::slot4` (`0x14422e6a0`) **arms** the save: it watches the shooter's
  action record (`byte[rec]==0x41`, elapsed `u16[rec+0x1a]`, duration `u16[rec+0x1e]`) and fires only
  when the shot animation has at most `(T·14)/30` ticks left — roughly the last 0.47 s.
* `ActionKeeperCatching::slot6` (`0x14421d3a0`) and `ActionKeeperPKSaving::slot6` (`0x14422cc00`)
  walk the 250-entry trajectory prediction (`dword[0x148080f50]` = 250, and that cell has **3
  writers** — it is not a constant), gate each sample on a **flat 3.5 m reach** (`12.25`, cell
  `0x146b01d80`, 40 referrers) with a 0.1 m tolerance, and publish an intercept point plus a
  requested action id into `match::Player+0x8bc`. **There is no attribute term in the reach
  envelope** — a League Two keeper and the best in the world both reach 3.5 m. [b]

**Warning for anyone reading class names as bindings.** A scan of every immediate write to
`player+0x8bc` image-wide (74 sites, `c7 /r [reg+0x8bc] imm32`) finds the save family only three
times: **`0x46` twice, both inside `ActionKeeperCatching::vf6`** (`0x14421d4c7`, `0x14421d8c9`) and
`0x44` once (`0x14422dce1`). `0x46` is `goal_keeper::Deflect` (proven from its ctor `0x143f4ad20
mov edx,0x46`), so **`ActionKeeperCatching` requests a Deflect, not a Catch.** `0x45`, `0x47`, `0x48`
and `0x49` are never written as immediates anywhere in the image — they must arrive by a register
write or another channel (§ Open 9). The `ActionKeeper*` names do **not** map one-to-one onto the six
anime save classes. [b]

The id space is shared between the two subsystems: the 113-entry per-action flag table at
`0x146c14e80` has exactly `{0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x51}` in **bit 9**, `{0x4d}` in
bit 10 and `{0x3f}` in bit 23. Bit 9 *is* "keeper save family". [b]

Action id → anime class, from each class's constructor: [b, anime chapter]

| id | class | attribute the selector reads | slot-29 frame budget |
|---|---|---|---|
| `0x44` | `goal_keeper::Catch` | GK Catching `0x23` | 60 |
| `0x45` | `goal_keeper::Punch` | GK Parrying `0x24` (`CLEARANCES`) | 60 |
| `0x46` | `goal_keeper::Deflect` | GK Reflexes `0x25` when `sub ∈ {1,4,5}`, else GK Reach `0x26` | 90 / 48 / 60 by `sub` |
| `0x47` | `goal_keeper::SnapUnder` | GK Catching `0x23` (shares the jump arm with `0x44`) | 15 |
| `0x48` | `goal_keeper::ScoopOut` | GK Reach `0x26` | 30 / 60 |
| `0x49` | `goal_keeper::Block` | GK Reach `0x26`, **raw** | 60 |

`sub` is the save object's own sub-type field at `saving+0x54` (`0x143f3c438 mov edi,[rbx+0x54]` then
`call 0x143f31470`; the same field is tested in `SavingBase::vf30` at `0x14403247f` and by Deflect's
frame budget). Emulated sweep of `sub` 0..7: **1, 4 and 5 take the Reflexes arm; 0, 2, 3, 6 and 7
take the Reach arm.** [a]

**Which save is chosen is still NOT LOCATED — and the search is bounded.** It is not in the attribute
reads, not in `PreSaving`, not in `0x14403cc60` (whose `cmp dword [rdi+0x30], 0x44/0x45/…` are on
`this->actionId`, i.e. *after* the class is running), and not in the pad layer. The trap that cost a
probe half a day is recorded in § Negatives: `0x143f2b590` looks exactly like the chooser and is not.

---

## 3. The save QUALITY decision end to end — `0x144032870` as numbers

> The **quality** half of the save is decoded. The **executor** half is not: every `ActionKeeper*`
> class that runs a save body is gate-only or listed-only (§ 14.1), and three of the four consumers
> of the quality integer are undecoded (§ 3.1).

`int SaveQuality(matchPlayer* rcx, int actionId edx, int sub r8d)`, chained-unwind extents
`0x144032870..0x1440328a8`, `..0x1440328f2`, `..0x144032a90`. Six-entry jump table at `0x144032a78`;
**entries 0 and 3 are byte-identical**, which is why Catch and SnapUnder both read GK Catching. Full
arithmetic in [anime-keeper-and-first-touch.md § 2](anime-keeper-and-first-touch.md); the shape is:

```
if actionId == 0x44 and ballSpeed < 50.0 km/h:
    v = max(Catching, Reflexes, Reach)
    q = (40 <= v <= 90) ? (v-40)/3 + 73 : v          ; add ebx,0x49 @0x144032940 — SKIPS the tail
else switch(actionId): one attribute, then
    0x46 sub{1,4,5}:  q = (40<=r<=90) ? (r-40)/2 + 65 : r     ; lea ebx,[rax+0x41] @0x1440329b0
    0x46 other, 0x48: q = (40<=r<=90) ? (3*(r-40))/4 + 52 : r ; add ebx,0x34      @0x1440329d9
if q < 90:   q = floor(q * 98 / 100)                 ; imul ecx,ebx,0x62 @0x1440329f2
if q > 100:  q = 100 + (q-100)/2
if flagQuery(player,0x1e) && situation[+0x1c] == 6: q += 5
q = clamp(q, 40, 120)
```

**Emulated, this write-up's own harness** (`tools/emu_gk_quality_indep.py`, PRISTINE bytes under
Unicorn, all four GK attributes set equal): [a]

| attribute → | 40 | 50 | 60 | 70 | 80 | 85 | 89 | 90 | **91** | 95 | 99 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `0x44` Catch, fast ball | 40 | 49 | 58 | 68 | 78 | 83 | 87 | 90 | 91 | 95 | 99 |
| `0x44` Catch, **slow ball < 50 km/h** | **73** | 76 | 79 | 83 | 86 | 88 | 89 | 89 | 91 | 95 | 99 |
| `0x45` Punch | 40 | 49 | 58 | 68 | 78 | 83 | 87 | 90 | 91 | 95 | 99 |
| `0x46` Deflect, Reach arm | **50** | 57 | 65 | 72 | 80 | 83 | 86 | 87 | 91 | 95 | 99 |
| `0x46` Deflect, Reflexes arm | **63** | 68 | 73 | 78 | 83 | 85 | 87 | 90 | 91 | 95 | 99 |
| `0x47` SnapUnder | 40 | 49 | 58 | 68 | 78 | 83 | 87 | 90 | 91 | 95 | 99 |
| `0x48` ScoopOut | **50** | 57 | 65 | 72 | 80 | 83 | 86 | 87 | 91 | 95 | 99 |
| `0x49` Block | 40 | 49 | 58 | 68 | 78 | 83 | 87 | 90 | 91 | 95 | 99 |

Two things to read off it. **The floors are outputs of 50 (Reach) and 63 (Reflexes)**, not the inline
52 and 65 — every arm *except the easy-catch remap* passes the ×98/100 stage. (The easy-catch arm's
`cmp ebx,0x78 ; jle 0x144032a54` at `0x144032945` jumps straight to the **lower clamp**, skipping
×98/100, the >100 halving **and** the `+5` situational bonus alike; that is why its floor is 73 and
not 71. The earlier draft's "everything below 90" contradicted its own pseudocode.)

And **the discontinuity is per-arm, not a single cliff at 91.** The `cmp ebx,0x5a ; jge` at
`0x1440329ed` tests the *post-remap* `q`, not the attribute, so each arm jumps where its own remap
crosses 90:

| arm | 89 → | 90 → | 91 → | jump sits between |
|---|---|---|---|---|
| Reach (`3·(r−40)/4 + 52`) | 86 | **87** | **91** | **90 and 91** |
| Reflexes (`(r−40)/2 + 65`) | 87 | **90** | 91 | **89 and 90** |
| raw (Catch-fast, Punch, SnapUnder, Block) | 87 | **90** | 91 | **89 and 90** |

So "91 is a cliff" is true of the **Reach** arm only. The commonly repeated "73..89 across the whole
roster" is right for 40..90 and wrong for the top nine points. [a + b, re-derived from
`0x1440329ed`..`0x1440329f2` for this repair]

**The transfer function — one of four.** `0x143f31470(saving, player, sub)` reads `saving+0x30` for
the action id, calls the selector, and returns `clamp01((q − lo)/span) · C + BASE` with: [b, all
constants read out of the image]. **Read § 3.1 before quoting its range as the block's range.**

| action | BASE | C | lo | span |
|---|---|---|---|---|
| `0x49` Block | 1.00 | 0.40 | 40 | 80 |
| `0x44` Catch | 0.95 | 0.30 | 40 | 80 |
| `0x46` Deflect, `sub == 1` | 0.90 | 0.32 | 20 | 110 |
| everything else | 0.90 | 0.30 | 40 | 80 |

**Composed — `0x143f31470`'s own output**, across the whole attribute range
(q a-emulated here, transfer b-disassembly, composition arithmetic). Note this is the value *before*
the downstream terms in `0x143f3c1f0`, and it is one of four routes (§ 3.1):

| save | 40 | 50 | 60 | 70 | 80 | 85 | 90 | 95 | 99 | **worst/best** |
|---|---|---|---|---|---|---|---|---|---|---|
| Catch, fast ball | 0.950 | 0.984 | 1.018 | 1.055 | 1.093 | 1.111 | 1.137 | 1.156 | 1.171 | **81 %** |
| **Catch, slow ball** | **1.074** | 1.085 | 1.096 | 1.111 | 1.123 | 1.130 | 1.134 | 1.156 | 1.171 | **92 %** |
| Punch | 0.900 | 0.934 | 0.968 | 1.005 | 1.042 | 1.061 | 1.087 | 1.106 | 1.121 | 80 % |
| Deflect, Reach arm | 0.938 | 0.964 | 0.994 | 1.020 | 1.050 | 1.061 | 1.076 | 1.106 | 1.121 | 84 % |
| Deflect, Reflexes arm, **`sub == 1`** | 1.025 | 1.040 | 1.054 | 1.069 | 1.083 | 1.089 | 1.104 | 1.118 | 1.130 | 91 % |
| Deflect, Reflexes arm, **`sub ∈ {4,5}`** | 0.986 | 1.005 | 1.024 | 1.043 | 1.061 | 1.069 | 1.088 | 1.106 | 1.121 | 88 % |
| SnapUnder | 0.900 | 0.934 | 0.968 | 1.005 | 1.042 | 1.061 | 1.087 | 1.106 | 1.121 | 80 % |
| ScoopOut | 0.938 | 0.964 | 0.994 | 1.020 | 1.050 | 1.061 | 1.076 | 1.106 | 1.121 | 84 % |
| **Block** | 1.000 | 1.045 | 1.090 | 1.140 | 1.190 | 1.215 | 1.250 | 1.275 | 1.295 | **77 %** |

**That table is the headline of this chapter — for this route.** Across the entire 40..99 attribute
scale `0x143f31470`'s multiplier moves from 0.900 to 1.295; on that route the worst keeper in the
game is 77–92 % of the best, and on a routine catch he is **92 %**. It is **not** a bound on the
goalkeeping block: see § 3.1.

**The consumer, with the register flow corrected.** `0x143f3c1f0` calls the transfer at
`0x143f3c44a`, parks the result in `xmm8` (`0x143f3c453`) and copies it to **`xmm6`**. The
0.85 (`0x1462bbed4`), 0.95 (`0x145e8788c`) and 0.80 (`0x145b2a694`) constants that the earlier draft
called "per-action ceilings" are loaded into **`xmm7`, a separate situational factor** — 0.85 is the
default (`0x143f3c457`), overwritten with 0.95 at `0x143f3c494`/`0x143f3c51e`/`0x143f3c541` and with
0.80 at `0x143f3c4ff`/`0x143f3c554`, each on a different situation or motion-id test. `xmm6` and
`xmm7` then travel down **separate** paths and are stored to two different fields, `[rsi+0x58]` and
`[rsi+0x5c]` (`0x143f3c98a` / `0x143f3c9a3`). The **only** cap on the multiplier itself is
`minss xmm6, 1.19` (`0x146b58b0c`) at `0x143f3c580`, reached only after `cmp eax,0x44 / 0x47`
(`0x143f3c463`/`0x143f3c46c`) **and** `and ecx,0xfc000 ; cmp ecx,0x24000 ; jne`
(`0x143f3c572`..`0x143f3c57e`) on the motion class from `0x144043e40(0x1440327e0(player, motionId))`.
Downstream `xmm6` also picks up `+xmm9`/`+xmm11` terms and is clamped by 1.4 (`0x146b01d78`) and 1.5.
**So the multiplier scales an animation-authored displacement: diving reach is an asset, not a
constant** — but the 0.900–1.295 figure is the value *before* those terms, not the number that
reaches the renderer. [b, re-disassembled from PRISTINE for this repair]

### 3.1 The save-quality integer has FOUR consumers, not one

The draft this section replaces bounded the goalkeeping block at 0.900–1.295 from a single transfer.
**`0x144032870` has four direct callers, and all four sit inside the save family.** Re-derived here.
[b]

| call site | root | what it does with `q` | range it implies |
|---|---|---|---|
| `0x143f3149e` | **`0x143f31470`** — the documented transfer | `clamp01((q−lo)/span)·C + BASE`, lo 40 span 80 cap 120 (sub==1: lo 20 span 110 cap 130) | **0.900 → 1.295** |
| `0x14402a68c` | **`0x14402a630`** (1,778 B, 7 chunks) | `t = clamp((q−40)/90)`, **cap 130**, then one of ≥ 8 `C·t + BASE` arms | one measured arm **0.500 → 0.959 = 52 %** |
| `0x143f36f32` | **`0x143f35ed0`** (7,433 B, 6 chunks) | `t = clamp((q−40)/80)` cap 120, `·0.2 + BASE`, then `max 0.4`, `min 1.0` | **0.4 → 1.0**, applied to a 3-vector at `[rsp+0x40..0x48]` |
| `0x144037bed` | **`0x1440374b0`** (2,988 B, 10 chunks) | `q` is used as an **integer frame count**, not a multiplier | see below |

Call chains, so nobody has to re-find them: `0x14402a630 ← 0x144028ec0 ← {0x143f46370, SavingBase::vf13 0x143f32880}`;
`0x1440374b0 ← 0x144036730 ← 0x144035be0 ← 0x14403cc60 ← 0x14403c070 ← {vf13, the save body}`;
`0x143f35ed0 ← 0x143f34e90 ← SavingBase::vf4 0x143f305c0`. [b]

**The second transfer, `0x14402a630`, is the one that breaks the bound.** From PRISTINE:
`comiss xmm11(=40.0), xmm1(q) ; jb` @ `0x14402a6ae`; `comiss xmm1,[0x146b18f78]=130.0` @ `0x14402a6b9`;
`divss xmm7,[0x145b52b90]=90.0` @ `0x14402a6cd` — **span 90, cap 130**, not the documented 80/120.
It then selects among at least eight `BASE`/`C` pairs on the action id, on `word[rdi]`, on
`byte[rdi+0x17]` bits 1 and 2 and on `byte[rdi+0x16]` bit 4:

| arm | site | at `q = 40` | at `q = 99` |
|---|---|---|---|
| `0.5·t + 0.7` | `0x14402a729` | 0.700 | 1.028 |
| **`0.7·t + 0.5`** | `0x14402a73a` | **0.500** | **0.959** |
| `0.3·t + 0.8` | `0x14402a776` | 0.800 | 0.997 |
| `0.4·t + 0.8` | `0x14402a77c` | 0.800 | 1.062 |
| `0.2·t + 0.6` | `0x14402a7af` | 0.600 | 0.731 |
| `0.4·t + 0.7` | `0x14402a7c5` | 0.700 | 0.962 |
| `+0.5` / `+0.2` add-ons | `0x14402a7f8` / `0x14402a80a` | — | — |

With the raw arms of the selector (Catch-fast, Punch, SnapUnder, Block) giving `q = attr`, attribute
40 → `t = 0` and attribute 99 → `t = 59/90 = 0.656`. **On the `0.7·t + 0.5` arm the worst keeper is
52 % of the best, not 77–92 %.** [b on the instructions, arithmetic composed here]

**The fourth consumer is not a multiplier at all.** In `0x1440374b0` the quality lands in `r14d`
(`0x144037bfa`) and is consumed at `0x144037f25` as `eax = 0x78 − q`, `sar eax,4` — i.e.
**`(120 − q)/16`** — multiplied by a frame count from `0x14533eb20` and divided by 48, then
`cmovne bp, dx` on `cmp dword[rax+0x30], 0x49`: **Block is exempt, everything else gets a delay that
grows as quality falls.** At 60 fps that is ≈ 6 frames at `q = 40` against ≈ 1 frame at `q = 99`,
capped by `min(·, trunc(fps·0.07 + xmm6))`, and the result is added into a frame index returned
through three out-params. A worse keeper **reacts later**; this is a real per-keeper differentiator
the earlier draft did not have. [b; the exact net frame count is **c** because `xmm6` on that path
is not pinned]

**Status: the block-wide range is NOT BOUNDED.** `0x14402a630`, `0x1440374b0` and `0x143f35ed0` are
all **NOT DECODED** to the point where their outputs can be composed into a single end-to-end figure.
What is proven is that at least one of them is materially wider than the documented route. Anyone
quoting "0.900–1.295" must say **which route**.

---

**The one uncompressed per-keeper gate.** `goal_keeper::Deflect::vf35` (`0x143f4add0`) — the **only**
slot-35 override in the family; the other five carry the `0x140c853c0` stub — is a hard boolean:

```
0x143f4add4  d2  = r8.x² + r8.z²
0x143f4adee  lim = [player+0x48a0] * 0.90          ; 0.90 @0x145b56e08
0x143f4adfe  comiss xmm1,xmm0 ; ja fail
0x143f4ae03  mov edx, 0x26 ; call 0x143ea8cb0      ; GK Reach
0x143f4ae10  cmp eax, 0x55 ; jl fail               ; >= 85
0x143f4ae15  mov al, 1
```

(re-disassembled from PRISTINE for this chapter.) One referrer image-wide, called from one site
(`0x144038820`, inside `0x1440381b0`). **Below GK Reach 85 a keeper loses a diving-parry variant
outright.** What the caller does with the boolean is § Open 7. Note `player+0x48a0` is **not** a
keeper field — ~190 read sites across `Trap::vf24`, `Dribble::vf13`, `PassGetRoute*`, `GoalEvent::vf4`
and `SeamlessThrowin::vf13`, one writer at `0x143eae99d` storing `x/180.0`; do not assume it is a
reach. [b]

**A second, separately-coded ability computation.** `PreSaving::vf4` (`0x143f27fb0`) dispatches on a
keeper-mode byte at `player+0x2bdc`; mode 1 is `0x143f28c10`, which reads **GK Reach** (`0x143f28c6c`,
the same `(3·(r−40))/4 + 52` remap but over 40..89 and with **no ×0.98**), **GK Reflexes**
(`0x143f28d4e`) and **Balance `0x2a`** (`0x143f28d95`), normalising Reach by 120.0 and Reflexes by
80.0 — both deliberately failing to saturate (**Reach 99 → 0.825, Reflexes 99 → 0.7375**) — and walks
the 250-frame prediction. Its downstream ~0x16xx bytes are not decoded (§ Open 2), and it is the most
promising remaining place for real per-keeper differentiation. [b]

---

## 4. Is any of it random?

**Partly, and the negative is SCOPED, not general.** No roll reaches the quality path or any
save-permission gate **that this chapter searched** — the selector, the multiplier, `canStart`,
`Deflect::vf35` and the six `vf30` overrides, each run to exhaustion with both controls. The save
body `0x143f46370` **does** draw one, and where it lands is undecoded; and the save-type chooser
itself was never located (§6), so it could not be searched at all. Do not restate this as "no
randomness in goalkeeping". The earlier draft's flat "the save outcome is deterministic
given the shot" is withdrawn; what survives is narrower and is set out below. Two methodological
warnings first, because each one has produced a wrong answer in this project.

**(i) The forward closure saturates.** Run to exhaustion, the *negative* control
`ChanceSpaceRun::vf5` (`0x143df5950`) explores **33,123 functions and reaches all five LCG entry
points**, first at depth 12 (re-measured here; the earlier draft printed 33,504). Bounded to depth
≤ 4 it explores **107 and reaches none**; at depth 5 and 6 it is still clean at 143 and 166.
Unbounded closure results in this band are artefacts of a merged SCC and must not be reported.
**Every row of the table below states its bound.**

**(ii) Four of the five RNG entry points have no `.pdata` record.** A call graph keyed on function
roots silently drops every edge into them. Scanning for the LCG multiplier bytes `e3 b2 22 2d`:
`0x144345dbe`, `0x144345e13`, `0x144345e5d`, `0x1443461ae` all return `func_root == None`; only
`0x144345f3b`/`0x144345f64` resolve. The true entry points are `0x144345d90`, `0x144345e00`,
`0x144345e50`, `0x144345eb0`, `0x1443461a0`. This produced a false negative on a first pass. [b]

**Both controls, then the measurements** (bounded BFS over direct `E8`/`E9` edges keyed on
chained-unwind roots):

| root | bound | explored | true RNG reached |
|---|---|---|---|
| **POSITIVE** kick error builder `0x14401a900` | depth ≤ 2 | 117 | **`0x144345d90` at depth 2** |
| — the same root | **unbounded** | **33,116** | all five LCG entries (first at depth 2) |
| **POSITIVE** keeper standing error `0x144228170` | depth ≤ 1 | 34 | **`0x144345e50` at depth 1** |
| **NEGATIVE** `ChanceSpaceRun::vf5` | depth ≤ 4 | 107 | none |
| — the same root | **unbounded** | **33,123** | all five (first at depth 12) |
| **NEGATIVE** attribute getter `0x143ea8cb0` | exhaustion | 5 | none |
| save-quality selector `0x144032870` | **exhaustion** | 19 | **none** |
| transfer `0x143f31470` | **exhaustion** | 20 | **none** |
| 2nd transfer `0x14402a630` (§ 3.1) | **exhaustion** | 28 | **none** |
| 3rd consumer `0x143f35ed0` (§ 3.1) | **exhaustion** | 89 | **none** |
| 4th consumer `0x1440374b0` (§ 3.1) | **exhaustion** | 34 | **none** |
| `SavingBase::vf2` `canStart` `0x143f34320` | **exhaustion** | 15 | **none** |
| `Deflect::vf35` `0x143f4add0` | **exhaustion** | 6 | **none** |
| `Block::vf30` `0x143f4a5d0` | **exhaustion** | 1 | **none** |
| `Catch::vf30` `0x143f4a890` | depth ≤ 4 / ≤ 5 | 56 / 82 | none |
| — the same root | **depth ≤ 6** | **96** | **`0x144345d90` at depth 6** |
| `SavingBase`/`Deflect`/`SnapUnder` vf30 `0x144032400`; `Punch::vf30`; `ScoopOut::vf30` | depth ≤ 4 | 76 | none |
| — the same three roots | **depth ≤ 5** | **90** | **`0x144345d90` at depth 5** |
| **the save body `0x143f46370`** | unbounded | 33,187 | **all five; `0x144345d90` at depth 2** — and it draws in its own body, see below |
| `ActionKeeperCatching::vf6` | depth ≤ 4 | 65 | **none** |
| `ActionKeeperBlockLate::vf6` (saturates) | depth ≤ 3 | 18 | **none** |
| `ActionKeeperPKSaving::vf6` | depth ≤ 4 | 67 | **none** |

**The vf30 rows are the correction.** The earlier draft printed the depth-4 figures and concluded
"no LCG **at any depth**". That is false for five of the six vf30 bodies: one more step reaches
`0x144345d90` by
`vf30 → 0x144033a90 → 0x144096500 → 0x14408ac90 → 0x144098d70 → 0x144345d90`. 90–96 functions is not
a saturated SCC — the negative control is still clean at 143 and 166 at the same depths — so this is
a real edge, not an artefact. **Whether that RNG is effective on the save permission is NOT PROVEN**;
what is proven is that the "at any depth" phrasing was wrong. Only `Block::vf30` (1 function), the
selector, the transfers, `canStart` and `vf35` are clean **to exhaustion**. [b, both controls re-run
on the same harness]

In-body RNG call sites: `goal_keeper::` (15 classes, 114 method bodies) **0**;
`match::player::ActionKeeper*` (93 bodies) **0**; the distribution brain `0x145655430` and its three
private target-finders **0**; `ActionKeeperMovePenaltyKick` **0**. **That census covers vtable method
bodies only** — the save body `0x143f46370` is a private helper reached from `SavingBase::vf4`, not a
method body, and it *does* draw (three sites, below). The two results do not contradict; the census
simply does not cover the function that matters. [b]

**The complete list of dice a goalkeeper rolls:**

1. the ≤ 0.5 m standing error (`0x144228170`, GK-Awareness-scaled, re-rolled every `2·T` ticks);
2. **one** random displacement on the save's target point inside the save body `0x143f46370`, drawn
   three different ways and written to **one float, `player+0x442c`**:
   `mov edx,0xa` @ `0x143f47be6` → `−0.00..−0.09 m`; `mov edx,5` @ `0x143f47c0d`, gated on
   `cmp dword[r13+0x30], 0x46` @ `0x143f47c06`, i.e. **Deflect only**; `mov edx,0x15` @ `0x143f47c1e`
   → a **0.20 m** span. All three scale by `[0x145aacd38] = 0.01` and all three store at
   `0x143f47c3e` `movss [rsi+0x442c], xmm0`. The stored value is then re-scaled in time bands
   (`×0.9` @ `0x143f47cb5`, `×0.6` @ `0x143f47cc7`, `×xmm7` @ `0x143f47ce8`).

**Where it lands — the gap the draft papered over.** The draft called these "three centimetre-scale
offsets" and used that to assert determinism. A displacement scan for `0x442c` across the image
returns **exactly two roots**: the writer `0x143f46370` and the reader **`0x143f35ed0`**, at
`0x143f3648b` `addss xmm0,[rdi+0x442c]` and `0x143f37166` `movss xmm9,[rdi+0x442c]` — in both cases
alongside `[rdi+0x441c]` / `[rdi+0x4420]` / `[rdi+0x4424]`, i.e. **a 3-vector being displaced**. And
`0x143f35ed0` is the same undecoded function that holds the unexplained GK Reach read `0x143f368da`
(§ Open 8) and one of the four quality consumers (§ 3.1). **The random term and an attribute read
meet in a function nobody has followed.** The largest draw is a 0.20 m span, not centimetre-scale.

**What is actually proven:** no LCG reaches the save-quality selector, any of the four transfers,
`SavingBase::vf2 canStart` or `Deflect::vf35` — **each verified to exhaustion**, and `0x143f35ed0`
itself contains no RNG at any depth (89 functions to exhaustion). **Whether the ≤ 0.2 m displacement
can flip save-versus-goal is NOT PROVEN.** [b + a]

---

## 5. One-on-ones — when he comes out

Owner: `ActionKeeperPress`, vftable `0x146bdc420`, subobject `+0x134f0`, overrides **0, 4, 5, 6, 15,
18, 20**. The decision is split across **vf4 and vf6**; `vf5` is the path half and opens with a
0.316 m "already there" early-out (`comiss 0.1, d²; ja exit` @ `0x14421b2e9`).

**The trigger (vf6, `0x14421c0c0`):**

```
0x14421c9a7  d2 = 0x143c71ee0(teamAI + 0x25a9c, opponentIdx)   ; cached squared distance
0x14421c9ac  comiss xmm0, 49.0   [0x146a6fa18]                 ; 7.0 m²
0x14421c9ba  cmp byte [team + 0xb3bd], 0   ; je -> mode 2 (hold)
0x14421c9d7  comiss xmm0, 225.0  [0x146a0476c]                 ; 15.0 m²
0x14421c9e0  [r15] = 2                                          ; hold
```

Beyond 15 m — or beyond 7 m while `team+0xb3bd == 0` — he does not engage. Inside it he additionally
requires the threat to be **already inside a committing animation** (`0x1442d6ba0` for the record,
`0x144311e20(actionId)`, `actionId == 4`, duration/elapsed against `fps·0.4`). [b]

**The geometry (vf4, `0x14421ac34..0x14421aca6`)**, all angles in degrees (`0x143c6fd80` is
`atan2deg`, `0x143c65890` is m/frame → km/h, both confirmed):

```
bearing magnitude in (5, 90)
|pos.x| > [pitchDim + 0x18]                      ; he is deep enough
threat bearing in (45,135) or (225,315)          ; ACROSS him, +/-45 deg of 90/270
ball speed > 10.0 km/h
  -> 0x1442dd650(team, idx, 0x32) = HEIGHT, /180.0 -> a steering parameter
```

**Six gates, none ability-scaled:** distance, the team flag, the threat's animation state, ball speed,
the bearing sector, and `0x144218d40` (undecoded, § Open 8) — plus the depth cap of § 1. The only
attribute anywhere in the Press family is HEIGHT, and it parameterises steering, not the decision.
No RNG. [b]

---

## 6. Distribution — the keeper has his own brain, and it is not a ThinkUnit

`team+0x275c` is the distribution target entity index, read by `ActionKeeperPuntKick::vf6`
(`0x14421553b`), `ActionKeeperThrow::vf6` (`0x14421780b`) and `ActionKeeperThroughThrow::vf6`
(`0x1442184a5`). A displacement scan finds **eight writers, all inside one function `0x145655430`**
— **2,461 bytes in 4 chained chunks** `0x145655430..0x145655527`, `..0x14565587b`, `..0x14565591d`,
`..0x145655dcd` (the "1,200 bytes" of the earlier draft and of goalkeeping.md was a
**root-chunk-only** read, the project's own named gotcha; the eighth writer at `0x145655d04` and the
role-0 early-out target `0x145655d65` both sit outside a 1,200-byte extent) — which has exactly one
caller (`0x14562cbb1`, in `0x14562cad0`), which itself has
exactly one caller (`0x144156ae4`). [b]

`0x14562cad0` forks on `teamObj+0x42b8` — **the same formation role-code array the ball-carrier brain
uses, role 0 = goalkeeper** — sending role-0 traffic to `0x145655430` (`bp+0x6ce8`) and everything
else to `0x145655dd0` (`bp+0x6d00`). And `0x145655430`'s first substantive test is
`test ebx,ebx ; jne 0x145655d65` on that same role code: **the whole body is goalkeeper-only.** [b]

The decision, in order: [b]

1. a **candidate loop over the eleven team-mates** (`cmp esi,0xb ; jl` @ `0x145655a72`), scoring each
   by `0x1442dd650(team, idx, 0x32)` — **HEIGHT** — and keeping the maximum;
2. a timing gate demanding `0x1442eb950(rec,0) >= 2·fps` before a target may be picked (the
   comparison is [b]; reading that field as "frames since the restart" is **[c]**, so *"he holds the
   ball for two seconds"* is deliberately **not claimed**);
3. a **short/long split at 30 m**, raised to **40 m** when per-player flag bit `0x14` is set —
   inside → action `0x41`, outside → action `0x40` (and, on flag bit `0x12`, `team+0x2751 = 1`);
4. three **private** target-finders — `0x143d104b0` (911 B, two sites), `0x143d0ff40` (722 B),
   `0x143d10220` (646 B) — each called from nowhere else in the image (§ Open 4);
5. a give-up path writing `team+0x275c = 0xff`.

**The negative this explains.** [ball-carrier-brain.md](ball-carrier-brain.md) proved exhaustively
that `GKDribble` (`0x19`), `GKPassShort` (`0x1a`) and `GKPassLong` (`0x1b`) are **registered and never
run**. They are dead not because the list builder forgets them but because **keeper distribution never
enters the ThinkUnit list at all** — it runs in a sibling object selected by role code before any
list is built. The GK list that *is* used (`PassRespondRequest`, `PassForward`, `PassLong`,
`PassSafety`, `GKClear`) is what the keeper gets when he is treated as an ordinary carrier; his
*restart* distribution is `0x145655430`. [b]

**No RNG, and no passing, vision or technique attribute anywhere in it.** The only per-player inputs
are HEIGHT and two flag bits. [b]

---

## 7. Set pieces and the penalty dive

**The penalty.** `ActionKeeperMovePenaltyKick` (vftable `0x146be09a8`) overrides **exactly one slot,
vf16** (`0x14422ca70`, 390 B) — and that slot *is* the penalty stance, which is why the finished
chapter's "the stance is inherited" reads the slot count right and the conclusion wrong:

```
0x14422cb45  mov rcx, [rdi + 0x20]              ; POINTER LOAD: rec+0x20 holds a POINTER
0x14422cb49  desc = 0x144317ec0(rcx)            ; unpacks the u32 at *(rec+0x20) + 4:
                                                ;   bits 0..8  -> float  (raw 0..511)   -> desc[0]
                                                ;   bits 9..11 -> float / const         -> desc[4]
                                                ;   bits 12..14-> float / const         -> desc[8]
                                                ;   bit  15+   -> byte                  -> desc[0xc]
0x14422cb56  if (90.0 > desc[0]) dz = +5.0 else dz = -5.0
0x14422cb6d  dest.z += dz ; clamp to +/-([pitchDim+8] - 1.5)
0x14422cba7  dest.x = sign(own.x) * [pitchDim+0]   ; his OWN goal line
```

**The descriptor is not a field at `rec+0x24`.** The earlier draft read
`0x144317ec0(rec+0x20)` as an address computation; it is `mov rcx, qword ptr [rdi+0x20]`, and the
unpacker's own first instruction is `movzx eax, word ptr [rcx+4]`. Anyone hunting the writer must
look for whoever allocates and fills **the object `rec+0x20` points at**, not for stores to
`rec+0x24` — that scan would come back empty and manufacture a false negative on the chapter's
highest-stakes open item. Also: the compared field is a **raw 0..511 integer converted to float**.
Calling it "an angle in degrees" is **[c]** — nothing in the code proves units. [b, re-read from
PRISTINE for this repair]

**The entire left/right commitment is one float comparison.** No RNG, no attribute, no difficulty.
The save that follows is the ordinary deterministic trajectory intercept (`ActionKeeperPKSaving::vf6`
= the 250-frame scan with the flat 3.5 m reach; no left/right branch, no attribute beyond HEIGHT).
**So: the penalty dive is neither a coin flip nor a guess — it is a half-plane read of an aim
descriptor reached through a pointer on the keeper's own action record before the ball is struck.**
The honest caveat: **who allocates and writes that descriptor object was not traced** (§ Open 3). If it is the kicker's published aim the
keeper legitimately reads the penalty; if it is a keeper-side instruction he is being told. That
distinction decides whether "the CPU keeper cheats on penalties" is true, and it is not yet decided.
[b on the mechanism, c on the provenance]

The animation family agrees with the mechanism: **(far / front / Otherside) × (high / low)** plus
`_moveOtherside` and `_movefront` scramble variants and an explicit `_cancel` — and **not one of the
15 `gkprejump_0_0_pk_*` entries has a cancel key**, so once committed he is locked for 0.33 s to
1.43 s. [a] The concrete ids are **not** in a table in the exe: a u16/u32 scan finds 851 and 934 never
within 64 bytes of each other anywhere in the image (negative control: the same scan finds 2,101 and
2,135 scattered hits, so it was not simply empty), so the animation is resolved through the
`AnimeTable` layer from a direction/height request. [b]

**Coaching is the goal kick, not the wall — answered, not merely unestablished.**
`ActionKeeperCoaching` (vftable `0x146bbfbe8`) overrides **0, 16, 18** only; vf4 and vf20 are the base
bodies, so it never moves the keeper and never emits a steering point. Both real bodies compute one
integer and store it in `work+0x1050`, and the class's entire animation set is two entries — 1452
`gkcoaching_high_0_0_lower_goalkick` and 1453 `gkcoaching_high_0_0_up_goalkick` (resolved here through
`ef_anime_names.json`). The defensive wall is twelve `wall_*` outfield animations (ids 3637–3648),
none `gk`-prefixed. [b + a]

**MoveFreeKick.** `ActionKeeperMoveFreeKick` (vftable `0x146be0348`): its "requests id 3 twice" is a
misreading — **vf12 is the shared two-instruction `mov eax,3; ret` at `0x14140d670`**, the constant
that normally occupies vf13, while vf13 here holds a real body (`0x14422c600`, a 3-way distance
classifier over 0.1 / 1.0 or 0.09 / 1.01 / 0.99). Its vf3 and vf4 have **no `.pdata` chunks**, which
is why a chunk-based dump of them comes back empty. [b]

**Makeshift.** `ActionKeeperMakeshift::slot6` (`0x144220f30`) is 12 instructions. **An outfield player
in goal gets no keeper behaviour from this class.** [b]

---

## 8. How long he is committed — the motion tables, in seconds

From the shipped `Mbinfo/bin` tables (12-byte `CancelData` records: `idx = v & 0x1FFF`,
**`frame = (((v>>13) & 0x3FF) + 2) · 2`**, 60 fps), joined to the 7,883-entry name index. **1,250
animations whose name begins `gk`**, carrying **876 cancel records across 732 animations**. "First
cancel key" is the earliest frame at which a queued action can get through; before it the keeper
cannot act. Families are exact first-token matches on the animation name. [a-measured]

> **CORRECTION — every second in this section used to be half its true value.** The draft quoted the
> proven frame rule above and then published numbers computed under the **superseded** raw rule
> `frame = v >> 13`, which is what `tools/mbinfo_ef.py::cancel_records()` still returns (`"frame":
> v >> ANIM_ID_BITS`, with no `0x3FF` mask, no `+2` bias and no doubling) and which
> [anime-actions.md](anime-actions.md) explicitly retired — *"right bit boundary, but no bias and no
> doubling: its seconds are 2× too short"*. Arithmetic proof that the old table was raw-rule: under
> the proven rule every frame is **even**, so the draft's 0.150 s (9 fr), 1.050 s (63 fr), 0.717 s
> (43 fr) and 1.283 s (77 fr) are all impossible. Re-extracted here from
> `Mbinfo/bin/CancelData.bin` (61,449 B on disk, unwrapping to 68,952 B = **5,746 records**, 0
> records with bits above 22 set) under both decodes; the raw rule reproduces the draft's table cell
> for cell, and the table below is the proven rule. **`tools/mbinfo_ef.py` is the stale artefact and
> was not edited here — the tool repo is read-only for this pass. Fix `cancel_records()` before
> re-running it.** [a-measured, both rules]

| family | n | with a key | first cancel s (min / **med** / max) | motion length s (min / med / max) |
|---|---|---|---|---|
| `gkcatch` | 156 | 126 | 0.400 / **0.850** / 1.800 | 0.400 / 1.100 / 4.500 |
| `gkdeflect` | 132 | 92 | 0.367 / **0.850** / 2.167 | 0.433 / 1.233 / 4.200 |
| `gkrise` (recovery) | 100 | 94 | 0.333 / **1.083** / 5.333 | 0.367 / 1.100 / 5.067 |
| `gkprejump` | 73 | **9** | 0.300 / 0.567 / 0.833 | 0.133 / 0.600 / 1.533 |
| `gkcollapsing` | 55 | 22 | 0.333 / 0.750 / 1.167 | 0.633 / 1.067 / 1.900 |
| `gkdeflectscoop` | 46 | 21 | 0.567 / 0.867 / 1.533 | 0.400 / 0.967 / 2.300 |
| `gkgoalkick` | 44 | 27 | 1.500 / **2.633** / 3.333 | 0.333 / 0.967 / 4.067 |
| `gkblockcover` | 41 | 29 | 0.433 / 0.667 / 1.700 | 0.567 / 1.000 / 2.600 |
| `gkpunch` | 30 | 26 | 0.800 / 0.933 / 1.500 | 0.467 / 1.333 / 2.767 |
| `gkmovemid` | 20 | **0** | — | 0.600 / 4.067 / 7.067 |
| `gkpuntkick` | 15 | 15 | 0.900 / 1.900 / 2.300 | 0.400 / 3.233 / 4.233 |
| `gkcoaching` | 2 | **0** | — | 2.333 / 2.500 / 2.667 |

(the full 33-row family table is in [goalkeeping.md § 5](goalkeeping.md) — **its first-cancel
seconds are raw-rule as well; double them**. Motion-length columns there are correct as printed.)

* **A dive is committed for a median 0.850 s** inside a 1.233 s motion; fastest abortable dive
  0.367 s, slowest 2.167 s.
* **The real cost is getting up**: `gkrise` locks a median 1.083 s inside 1.100 s motions. A
  dive-and-recover cycle is **~2.3 s of median motion with ~1.9 s hard-locked**.
* **518 of the 1,250 (41 %) have no cancel record at all** — locked for the whole motion, median
  0.833 s, max 7.067 s. Every penalty pre-jump is in this set. (Motion lengths come from
  `Animation.bin` and are unaffected by the frame rule.)
* **For scale**, from the same tables: a standing `tackle*` first-cancels at a median **0.667 s** and
  a `sliding*` at **0.800 s** (prefix match, `n` = 117 and 33). So **a keeper dive commits ~6 %
  longer than a slide tackle** and ~27 % longer than a standing tackle — the draft's "~30 % longer
  than a slide tackle" divided the dive by the *standing tackle* median while naming the slide.
  Under the superseded raw rule the same three medians are 0.392 / 0.367 / 0.300, i.e. **+7 %** and
  **+31 %**: whichever frame rule is settled on, the ratio to the **slide** is single-digit.
* **Data hazard before anyone edits `CancelData.bin`:** **133 of the 640** `gk*` animations that have
  both a length and a key (**21 %**) have their **first key at or past the motion end**. Under the
  superseded raw rule that figure was 37 (6 %); it is the proven rule that makes the anomaly large,
  which is itself evidence worth settling. Those records are uncancellable in practice, and it is
  unresolved whether they are authoring errors or a decode exception for short motions (§ Open 9).

`HoldData.bin` is dominated by `gkcatch` / `gkblockcover` / `gkprejump` hand geometry (378 records,
bones 7 and 11, a mirrored pair) — the goalkeeper-hands lever already noted in the anime chapter.

---

## 9. The input census

### Attributes

Enumerated from every caller of the attribute getter `0x143ea8cb0` (282 call sites image-wide, 28
with computed indices), plus the by-entity getter `0x1442dd650`. **Caveat: the three selector jump
arms share the call at `0x1440329e6`, so a naive backward scan mis-attributes it** — the selector's
reads below are taken from the disassembly instead. **Caveat 2: this census covers those two getters;
other wrappers exist (e.g. `0x1442dd650` → `0x1442d6ef0` → `0x144301840` → `0x1441172b0`) and a
register-indexed read would not be seen.** [b]

| attribute | idx | read at | what it buys |
|---|---|---|---|
| **GK Awareness** | `0x16` | `0x143f2c5a9` (footwork chooser), `0x143f4238a`, `0x143f4a224`, `0x1442254c2` (vf4 helper), `0x14422aba3` (vf18), `0x144228863`-adjacent scale | the **anticipation window** (0 → 15 frames), the ball look-ahead, and the ≤ 0.5 m standing error. **Dead below 44.** |
| **GK Catching** | `0x23` | `0x144032891` (selector) | Catch `0x44` and SnapUnder `0x47` quality; linear ×0.98 |
| **GK Parrying** | `0x24` | `0x1440420ac` (in `0x144040730`, undecoded), selector arm | Punch `0x45` quality; linear ×0.98 |
| **GK Reflexes** | `0x25` | `0x144032907`, `0x14403299c` (selector), `0x143f28d4e` (PreSaving mode 1), `0x14421ff95` (`ActionKeeperBlockLate::vf6` — the **only** save-attribute read in the executor layer, consumer untraced) | Deflect `sub ∈ {1,4,5}`; **compressed to 63..99** |
| **GK Reach** | `0x26` | `0x144032916`, `0x1440329bd`, `0x1440329e6` (selector), **`0x143f4ae0b` (`Deflect::vf35` — the 85 gate)**, `0x143f28c6c` (PreSaving mode 1), `0x143f368da` (in `0x143f35ed0` — **also one of the four save-quality consumers and the sole reader of the random `player+0x442c`**, § 3.1 / § 4; undecoded) | Deflect Reach arm, ScoopOut, Block (raw); **compressed to 50..99 except on Block**; **binary gate at 85** |
| **Balance** | `0x2a` | `0x143f28d95` (PreSaving mode 1) + nine outfield sites | one term in PreSaving mode 1; consumer undecoded |
| **HEIGHT** | `0x32` | widely — `ActionKeeperPress::vf4` `0x14421acc1` (÷180.0), the distribution brain `0x145655a35`, several others | steering parameters and the distribution candidate score. **Never a decision.** |
| everything else | — | — | **no other attribute reaches a keeper at all** |

### dt270

**Zero.** No `get()` site in any `goal_keeper::` method body; zero dt270 readers in the keeper
executor band `0x144215000..0x144243000`. `basePosition` holds exactly **20** `gk*` fields, of which
**6 are read** (`gklAdjustRateX`, `gklBaseX`, `gklBaseZRate`, `gklSupportRate`, `gklWidthZ`,
`gksWidthZ`) and **14 have no reader at all** — and all six readers live in `0x143de2350`,
`0x143de8520`, `0x143e7f4c0`, the **outfield** shape layer. `gks`/`gkl` reads as
*goal-kick-short / goal-kick-long team shape*, not the keeper's own spot. Across all 245 dt270 objects
the only other `gk`-named fields are `modeMatchup.gk_entry` and `rating.gk_rate` / `rating.coef_gk[]`,
both match-rating. Per-field table in [goalkeeping.md § 1.6](goalkeeping.md). [b]

### CPU difficulty

**Zero reaches a save.** Saves are identical on Beginner and on Legend. [b, anime chapter — re-checked
here, not re-derived]

### Motion assets

The per-keeper *magnitude* of a save is a multiplier applied to an **animation-authored
displacement**, capped per motion class in `0x143f3c1f0`. **Through the `0x143f31470` route that
multiplier spans 0.900–1.295; the block-wide range is NOT BOUNDED** — `0x14402a630`, `0x1440374b0`
and `0x143f35ed0` are not decoded far enough to compose, and at least one is materially wider (§3).
Per this chapter's own rule, the figure is quoted here **with its route** and must not be restated
as "the whole magnitude". Dive **speed** is a
global per-save-type frame budget (Catch / Punch / Block 60, Deflect 90 / 48 / 60 by `sub`, ScoopOut
30 / 60, SnapUnder 15) with **no attribute getter in any of the slot-29 bodies**. Dive **distance** is
therefore an asset question, not a constant question.

**`SavingBase::vf47` — the "dead placeholder" is withdrawn.** `0x143f30f90` is
`mov eax, 0xb9c ; ret`, and `0xb9c` does resolve to `referee_game_end_1_0_hand_up_whistle`. But the
reason the draft gave for calling it dead — *"consistent with every subclass overriding slot 47"* —
is **false**. From `build/exe_map.json`, slot 47 across the seven 50-slot classes:

| class | vf47 | |
|---|---|---|
| `SavingBase` | `0x143f30f90` | `mov eax,0xb9c` |
| `Block` | `0x143f4a620` | overrides |
| `Catch` | `0x143f4a9d0` | overrides |
| `ScoopOut` | `0x143f4b7f0` | overrides |
| **`Deflect`** | **`0x143f30f90`** | **inherits** |
| **`Punch`** | **`0x143f30f90`** | **inherits** |
| **`SnapUnder`** | **`0x143f30f90`** | **inherits** |

Three of the six subclasses inherit it, so for them `0xb9c` is the **live** default. Either slot 47
is not called for those three, or `0xb9c` is not a motion id in this slot — **not proven either way**
(§ Open 12). The claim was inherited verbatim from
[anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md) line 70 and presented as a
verified negative without running the slot check the chapter itself cites two corrections earlier.
The slots on which *nobody* overrides are 32, 33, 34, 38 and 40; on slot 35 five of six inherit the
`0x140c853c0` stub. Every other keeper id quoted here does resolve cleanly, e.g. `0x799`
`gkpunch_f03_3_0_y11`, `0x227` `gkcatch_s01_0_3_y04_stand`. [b + a, re-checked for this repair]

---

## 10. Tunables

Route legend as in the parent chapters: **player-data** (the app already writes it), **exe-constant**
(a private pooled cell, safe in place), **exe-code** (instruction-local immediate or a re-aimed
rip-displacement — never edit the shared cell), **motion-asset** (`Mbinfo/bin`, subject to the anime
chapter's unbuilt WESYS writer), **not-reachable**, **NOT-SAFELY-TUNABLE**.

| what | site | route | effect | evidence | sharers |
|---|---|---|---|---|---|
| **GK Reflexes floor** (inline 65, output 63) | `lea ebx,[rax+0x41]` @ `0x1440329b0` | exe-code | the single biggest quality lever. Today a 40-Reflexes keeper parries at 63 — 23 points of the scale are unreachable | a | instruction-local |
| **GK Reach floor** (inline 52, output 50) | `add ebx,0x34` @ `0x1440329d9` | exe-code | restores the bottom 12 points of Reach for Deflect and ScoopOut | a | instruction-local |
| **Easy-catch floor 73** | `add ebx,0x49` @ `0x144032940` (divisor: `mov eax,0x55555556` @ `0x144032934`) | exe-code | the cheapest single byte in the chapter — restores roster spread on routine catches, which is where conceded goals feel most unearned | a | instruction-local |
| GK Reach slope `3·(r−40)/4` | `lea eax,[rax+rax*2]` @ `0x1440329cc`, `sar ebx,2` @ `0x1440329d6` | exe-code | steepen toward 1:1 *after* dropping the floor, else the band just shifts | a | instruction-local |
| GK Reflexes slope `(r−40)/2` | `sar eax,1` @ `0x1440329ae` | exe-code | same for the Reflexes arm | a | instruction-local |
| the ×98/100 pass below 90 | `imul ecx,ebx,0x62` @ `0x1440329f2` | exe-code | what turns inline 52/65 into output 50/63. Leave alone unless you want a global shift | a | instruction-local |
| the `+5` situational bonus | `add ebx,5` @ `0x144032a45` | exe-code | fires only when `flagQuery(player,0x1e)` **and** `situation[+0x1c]==6`; all four combinations emulated, neither alone does anything. Flag `0x1e` unidentified | a | instruction-local |
| **`Deflect::vf35` Reach gate at 85** | `cmp eax,0x55` @ `0x143f4ae10` | exe-code | **the sharpest behavioural keeper lever found.** Raise and almost nobody gets the extended diving parry; lower and everyone does. Entirely uncompressed | b | **unique** — only slot-35 override, one caller (`0x144038820`) |
| **GK engagement radius 16.42 m** | cell `0x146bdfd90` = 269.6164, sole referrer `0x144224d1d` | **exe-constant** | the radius inside which he may notice an opponent's action at all. Raise for a sweeper, lower to pin him. **Write R², not R** | b | **1** |
| **GK positional-error range** | `mov edx, 6` @ `0x144228863` | exe-code | the only RNG in the family. `6 → 18` gives a 1.7 m maximum standing error at GK Awareness 40. Verified a plain bound, not a stream index | a | instruction-local |
| **keeper base depth** | formation GK slot x at `teamAI + slot·20 + 0x40`, clamped ±10 m of `team+0x799c` | **player-data** | moves the base spot one-for-one to the clamp. The safe route — no patch at all | b (c on the array identity) | per-team |
| **GK Awareness anticipation** | attribute `0x16`; `0x1442254c2`, `0x14422aba3` | **player-data** | 0 → 15 frames of head start, onset 0.500 s → 0.170 s. **Never author 40–43**: the branch is dead below 44 | b | per-player |
| **per-player flag bits `0x46` / `0x12` / `0x14`** | 73-entry bitfield at `playerRec+0xc0`, read via `0x1442c0000` / `0x1442e2610` | player-data *(conditional)* | `0x46` switches the keeper's off-his-line branch; `0x12` / `0x14` switch distribution variants. **The reads are proven; the names are not** (§ Open 1) | b | per-player |
| come-out trigger **15 m** (225.0) | cell `0x146a0476c`, tested @ `0x14421c9d7` | exe-code | beyond it he refuses to engage. Cell is **not** private | b | **118** |
| come-out trigger **7 m** (49.0) | cell `0x146a6fa18`, tested @ `0x14421c9ac` | exe-code | the tighter of the two radii | b | **73** |
| distribution short/long split 30 m / 40 m | `0x145655595` (30.0), `0x145655aed` (40.0), compared squared @ `0x145655b2b` | exe-code | chooses action `0x41` (short) vs `0x40` (long) | b | shared cells |
| `ActionKeeperThrow` private constants 16.6667 / 133.3333 | cells `0x146bdb2dc` / `0x146bdb2e0` | exe-constant | bounds on the throw solution; roles **not** read. Listed because they are provably private | c | **1 / 1** |
| `ActionKeeperAfterCatchMove` bearing quadrants 90.1 / 179.9 / 180.1 / 269.9 / 359.9 / 360.1 | cells `0x146be3d10..0x146be3d28` | exe-constant | a bearing quadrant classifier in vf16; consumer not read | c | **1 each** |
| **dive / recovery lockout** | `Mbinfo/bin/CancelData.bin`, the **876 cancel records across the 732 `gk*` animations** that carry keys | motion-asset | the only route with per-animation granularity: move `gkdeflect`'s **0.850 s** commitment or `gkrise`'s **1.083 s** recovery without touching outfield contact. Seconds under the **proven** frame rule (§ 8) | a-measured | per-motion |
| **penalty dive commitment** | the 15 `gkprejump_0_0_pk_*` records + `gkmovemid_pk_0_0_ver16/17`, all with **no** keys | motion-asset | adding a cancel key would let a keeper adjust a penalty dive; today he is locked 0.33–1.43 s (a *motion length*, so unaffected by the frame rule) | a-measured | per-motion |
| **the save multiplier's hard cap 1.19** | cell `0x146b58b0c`, `minss xmm6` @ `0x143f3c580` | **exe-constant** | the ceiling on `0x143f31470`'s output for actions `0x44`/`0x47` in motion class `0x24000`. Census: **refcount 1**, `private_unproven`, sole class `goal_keeper::SavingBase` — one of the few genuinely private cells in the family | b | **1** |
| keeper footwork bearing ladder 135 / 45 / 15° | `0x146a04768`, `0x145b1d910`, `0x145c0b000`, compared in `0x143f2b590` arm 2 | exe-code | changes *which* sidestep plays as the shot is struck — cosmetic/positional, not quality | b | shared |
| **NOT SAFELY TUNABLE** — the 50 km/h easy-catch gate | cell `0x145ae7580`, read @ `0x1440328cc` | — | **503 referrers.** This is the generic 50.0f. Re-aim the instruction's displacement at a private cell if you must move it | b | **503** |
| **NOT SAFELY TUNABLE** — the transfer BASE/C constants (0.90, 0.95, 1.00, 0.30, 0.32, 0.40) | `0x145b56e08`, `0x145e8788c`, `0x1478502b8`, `0x145b28a88`, `0x145e8786c`, `0x145b2a690` | — | lowering the BASEs is the *direct* way to widen the felt gap. **Five are heavily pooled** — 0.90 `0x145b56e08` 299 refs, 0.95 `0x145e8788c` 77, 1.00 `0x1478502b8` 13,240, 0.30 `0x145b28a88` 895, 0.40 `0x145b2a690` 623 — but **0.32 `0x145e8786c` has only 7** (`match::anime::action::FreeKickLoop` + unattributed) and is the one cell that could plausibly be edited in place after a referrer check. Re-aim the loads for the other five | b | 299 / 77 / 13240 / 895 / 623 / **7** |
| **NOT SAFELY TUNABLE** — the keeper advance caps 4 / 15 / 20 / 42 m | `0x145ab1b48`, `0x145c0b000`, `0x145a8aa44`, `0x145ec9ef0` | — | the four are **not** comparable: 4.0 `0x145ab1b48` has **1086** referrers, 15.0 `0x145c0b000` **943**, 20.0 `0x145a8aa44` **1099**, and only 42.0 `0x145ec9ef0` is as low as **26** (`ActionSelectorDiagonalRun`, `ActionSelectorSecondLineSpaceRun`, `Team`, `ThinkUnitShoot`, `ActionBasePosition`). The draft quoted the smallest of the four as if it were typical | b | **1086 / 943 / 1099 / 26** |
| **NOT SAFELY TUNABLE** — the penalty ±5.0 m step | `0x145a8dd78` / `0x145b1d940`, loaded @ `0x14422cb5b` / `0x14422cb65` | — | among the most shared floats in the image. Change the instruction, never the cell | b | very high |
| **NOT SAFELY TUNABLE** — the 3.5 m catch envelope | cell `0x146b01d80` = 12.25, read @ `0x14421d638`, `0x14422cdbb` | — | **40 referrers**, and there is no attribute term in the envelope at all: making it scale with GK Reach needs a code cave, not a constant edit | b | 40 |
| **NOT a constant** — the 250-frame prediction length | `0x148080f50` | — | 337 readers **and 3 writers** (`0x1443071f0`, `0x144307405`, `0x144307433`). A file edit is overwritten at run time | b | 337 / 3 |
| **NOT REACHABLE** — dt270 `basePosition.gk*` | 20 fields at `0x1b4..0x200` | — | 6 read, all six readers in the outfield shape layer; 14 dead. Editing them changes the **outfield** goal-kick shape, never the keeper | b | — |

---

## 11. So what does editing a keeper's attributes in master.db actually change?

A straight answer, because the UI implies far more than the code delivers.

**GK Awareness `0x16` — the one that matters most, and it is not the one the name suggests.** It buys
**anticipation**: up to 15 frames (0.25 s) of head start on a threat's wind-up and an onset moving
from 0.500 s to 0.170 s, plus a ball look-ahead, plus the vanishing ≤ 0.5 m standing error. **Never
author a keeper at 40–43** — the anticipation branch is unreachable below 44, so the first three
points of the scale are a step, not a slope. Spread your keepers across **44–99** and you get a
visible gradient; author them at 40 and you get a discontinuity.

**GK Reach `0x26` — the only attribute with a binary behavioural threshold.** At **85** the
`Deflect::vf35` gate opens and the keeper gains a diving-parry variant. That is worth more than any
amount of quality arithmetic. On Deflect and ScoopOut the **output** band below 50 is unreachable —
but the attribute points 40–50 are **not** wasted: the arm still moves the output by ~0.75 points per
attribute point across 40..90 (Reach 40 → 50, 50 → 57, 60 → 65, 70 → 72). On Block it is linear.
(The draft said "points 40–50 are wasted", which contradicts its own § 3 table and would be acted on
literally.)

**GK Reflexes `0x25` — compressed to 63..99.** Dropping a keeper from 70 to 40 buys you fifteen
quality points, not thirty. The bottom 23 points of the **output** scale do not exist. And note the
payoff depends on which Deflect sub-type the engine picks: the wide `0.32 / lo 20 / span 110`
transfer fires **only for `sub == 1`**, while the Reflexes *quality* arm fires for `sub ∈ {1,4,5}`.
For `sub ∈ {4,5}` the generic transfer applies and the curve is 0.986 → 1.121 instead of
1.025 → 1.130 (§ 3). Since the **save-type chooser is NOT LOCATED** (§ 13), which of the three you
get is itself unknown.

**GK Catching `0x23` and GK Parrying `0x24` — linear and honest**, ×0.98 below 90. These two do what
you expect.

**On any ball under 50 km/h the game takes `max(Catching, Reflexes, Reach)`** and remaps 40..90 into
73..89. **A single-attribute nerf is invisible there** — lower all three together or the `max()` picks
up whichever you left high.

**There is a cliff, and it is not at 91 on every arm.** The `< 90` test is on the *post-remap* value,
so the **Reach** arm jumps between **90 and 91** (90 → 87, 91 → 91) while the **Reflexes** arm and
every raw arm (Catching, Parrying, Block) jump between **89 and 90** (89 → 87, 90 → 90). For a smooth
roster keep **Reach ≤ 90** and **Reflexes / Catching / Parrying ≤ 89**. Capping Reflexes at 90 does
*not* avoid its jump.

**And the ceiling on all of it — with the caveat the draft dropped.** *Through the quality selector
and its transfer `0x143f31470`, which is everything that has been followed end to end*, the block is
a multiplier of **0.900 to 1.295** and the worst keeper is **77–92 %** of the best — **92 % on a
routine catch**. Add the flat 3.5 m catch envelope, the global dive-speed budgets and the entirely
unscaled come-out, distribution and penalty logic, and on that route you cannot author a bad
goalkeeper in master.db.

**That is a statement about one of four routes, and it is no longer a statement about the block.**
The same quality integer also feeds `0x14402a630` (span 90, cap 130, ≥ 8 arms, one of them measured
at **52 %** worst-to-best), `0x143f35ed0` (a 0.4..1.0 vector scale) and `0x1440374b0` (a
**reaction-frame delay** `(120−q)/16` from which Block is exempt) — all three undecoded (§ 3.1).
Four further attribute consumers are undecoded on top of that (`PreSaving` mode 1's Reach/Reflexes/
Balance, `0x143f368da`, `0x1440420ac`, `ActionKeeperBlockLate`'s `0x14421ff95`; § Open 2, § Open 8).
**The honest form of the headline is: on the documented route you cannot author a bad goalkeeper;
block-wide, it is not yet known.**

A realism mod that wants League Two keepers to look like League Two keepers has **exactly four**
levers proven to bite today — the two selector floors, the easy-catch floor, and the `Deflect::vf35`
threshold — and all four are exe-code edits, not data. `0x1440374b0`'s reaction delay is the most
promising *fifth*, and it is already attribute-scaled; it needs decoding, not patching.

---

## 12. Corrections to finished chapters

### To [player-executors.md](player-executors.md)

1. **§ The goalkeeper → "The one random number".** *"That is the whole 'does a bad keeper get caught
   out of position' model, and 0.5 m at its worst is far too small to see"* is wrong **as a statement
   about GK Awareness**. It is right about the error and wrong about the attribute: `0x16` is read at
   two further sites (`0x1442254c2` in the vf4 helper, `0x14422aba3` in vf18), each building a frame
   budget, **with a hard cliff at 44 below which the anticipation branch is unreachable**. The 0.5 m
   error is the least consequential of three GK-Awareness terms. [b]
2. **§ The input census → "attributes — keepers".** The row lists `GK_DECISION 0x16` as read
   "BasePosition ×3" without saying what the other two reads do, **and omits the per-player flag table
   entirely**: bit `0x46` of `playerRec+0xc0` is read at `0x1442223a7` and `0x144226c64` via
   `0x1442c0000`. There **is** per-player individuality in keeper positioning beyond one attribute.
   [b]
3. **Class row `ActionKeeperPress`.** *"vf5 (0xc3b bytes, the come-out decision) NOT decoded"* names
   the wrong slot. vf5 (`0x14421b1e0`) is the path/steering half and opens with a 0.316 m early-out;
   **the come-out decision is vf6** (`0x14421c0c0`, 4,739 B, the 15 m / 7 m gate at
   `0x14421c9ac`/`0x14421c9d7`) with the engage geometry in vf4. vf5 is still undecoded — the label
   should move, not disappear. [b]
4. **Class row `ActionKeeperCoaching`.** *"Whether it organises a wall is not established"* → **it
   does not.** It writes one int to `work+0x1050` selecting between two goal-kick gestures
   (`gkcoaching_high_0_0_lower_goalkick` / `_up_goalkick`); the wall is twelve `wall_*` outfield
   animations. [b + a]
5. **Class row `ActionKeeperMovePenaltyKick`.** *"overrides ONE slot; no own vf4, no vf20 — the
   penalty stance is inherited"* is right about the slots and wrong about the conclusion. **The single
   override, vf16 (`0x14422ca70`), IS the penalty stance** and contains the entire left/right
   commitment. [b]
6. **Class row `ActionKeeperMoveFreeKick`.** *"requests id 3 twice"* is a misreading: **vf12 is the
   shared `mov eax,3; ret` (`0x14140d670`)** and vf13 holds a real body (`0x14422c600`). Its vf3/vf4
   have no `.pdata` chunks. [b]
7. **Class row `ActionKeeperCatching`** (*"publishes intercept + requests id `0x46`"*) needs a warning
   label: **`0x46` is `goal_keeper::Deflect`**, so no reader should infer
   `ActionKeeperCatching → goal_keeper::Catch`. [b]
8. **§ Tunables, "GK engagement radius".** *"Its exact consumer condition inside `0x1442246d0` is only
   partly read"* **closes**: the full gate is decoded at `0x144224d3c..0x144224e4c` (five action-id
   bit predicates, a 144.0 = 12 m squared test, an animation window against `fps·0.3` / `fps·0.5`,
   producing 1.5 vs 0.5). [b]
9. **§ Tunables, "make weak goalkeepers actually concede".** *"floors Reach at an output 50 and
   Reflexes at 63 (the inline constants are 52 and 65 …)"* is **confirmed verbatim** by an independent
   emulation from the PRISTINE bytes. Upgrade its confidence; note that the shorthand "52 and 65"
   refers to the **inline** constants only. [a]
10. **§ Open, `ActionKeeperBasePosition::vf18`.** Narrow, do not close: the GK-Awareness look-ahead
    term at `0x14422aba3` is now read; the rest of the 7,104 bytes is not.

### To [anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md)

11. **§ 2 in full — CONFIRMED end to end** by an independent Unicorn harness written from scratch
    against the same bytes: the quality table, the attribute-isolation table, the `sub` sweep, the
    49.9 / 50.0 km/h gate and the four-way `+5` test all reproduce exactly. **Upgrade from
    single-source to corroborated.** [a]
12. **§ 1 slot table — "slot 29 / slot 30: pure, all six override" is half right, and this chapter's
    own first correction of it over-corrected.** Slot by slot, from `build/exe_map.json`:
    **Slot 29** — all six subclasses *do* override `SavingBase`'s `0x144f83074`, so the parent
    chapter's wording is literally true; what is false is that they are six distinct bodies. Block,
    Catch and Punch share `0x143f4a5c0`; Deflect is `0x143f4ad80`, ScoopOut `0x143f4b1d0`, SnapUnder
    `0x143f4fb70`. **Four distinct bodies.**
    **Slot 30** — only four override: Block `0x143f4a5d0`, Catch `0x143f4a890`, ScoopOut
    `0x143f4b1f0`, Punch `0x143f4b850`. **Deflect and SnapUnder inherit `SavingBase`'s
    `0x144032400`.** Counting the inherited body, that is **five distinct bodies across the six
    classes**, not four. (The draft applied the "four distinct bodies" count to both slots.) [b]
13. **§ "Motion assets" caveat — retire it.** The claim that `0x1ecb = 7883` *"exceeds Animation.bin's
    4,345 records, so do not assume one id space"* is resolved: `ef_anime_names.json`'s body table is
    exactly 7,883 entries and the accessor bound is `cmp edx, 0x1ecb`, i.e. an **exclusive upper
    bound**, not a row. `0xb9c` → `referee_game_end_1_0_hand_up_whistle` remains an oddity, but
    it is **NOT a proven dead placeholder** — Deflect, Punch and SnapUnder all inherit
    `SavingBase::vf47 = mov eax,0xb9c`, so for three of the six subclasses it is the **live**
    default (§ 9). **This correction lands on anime-keeper-and-first-touch.md line 70's "every class
    overrides" as well** — that line is the source of the error. Not proven either way. [b + a]
14. **§ 3 closure table — add the `.pdata` warning.** Four of the five RNG entry points
    (`0x144345d90`, `0x144345e00`, `0x144345e50`, `0x1443461a0`) have **no unwind record**, so a call
    graph keyed on function roots drops every edge into them and reports a false negative. Only
    `0x144345eb0` resolves. [b]
15. **§ 3 — the negative control needs its bound stated.** `ChanceSpaceRun::vf5` is clean **only when
    bounded**: at depth ≤ 4 it explores 107 and reaches nothing (still clean at 143 and 166 at depths
    5 and 6); run to exhaustion it explores **33,123** and reaches all five LCG entries, first at
    depth 12. Quoted without a depth bound the control fails. (Re-measured here; this chapter's own
    draft printed 33,504 — the harness, not the image, differs.) [b]
16. **§ 1 and the "(14 classes) | 114" row — the namespace has FIFTEEN vtables**, in three contracts
    (50 / 33 / 29 slots). 114 is a count of distinct **method bodies**, not of classes, and the text
    should say so. [b]

### To [anime-actions.md](anime-actions.md)

17. **§ Tunables, "stop keepers saving like 63-rated when they are 40"** — correct, and now
    quantified **on one route**: through `0x143f31470` the multiplier spans **0.900–1.295** and the
    worst-to-best ratio is **77–92 %** by save type (§ 3). The save-quality integer has three other
    consumers, one of them measured at 52 % worst-to-best, so this is **not** a block-wide bound
    (§ 3.1). [a on the route, b on the other three]

### To [ball-carrier-brain.md](ball-carrier-brain.md)

18. **§ "Six registered units never run"** — the negative on `GKDribble` (`0x19`), `GKPassShort`
    (`0x1a`) and `GKPassLong` (`0x1b`) is correct and can now be **explained rather than merely
    observed**: keeper on-ball decisions run in `0x145655430`, a sibling object at `bp+0x6ce8`
    selected by `0x14562cad0` on the **same `teamObj+0x42b8` role-code array the brain itself uses**.
    They are dead because keeper distribution never enters the ThinkUnit list, not because the list
    builder omits them. [b]

### Where the brief that commissioned this chapter is imprecise

19. *"the **14-class** `goal_keeper::` save family"* — there are **fifteen** vtables, in three
    contracts: 50 slots (SavingBase, Block, Catch, Deflect, Punch, ScoopOut, SnapUnder), 33 slots
    (AfterCatchBase, PuntKick, Throw) and 29 slots — `action::Base` exactly — (BodyFeint, DropBall,
    PickupBall, PreSaving, SeeOff). [b]
20. *"the **~30** `ActionKeeper*` executors … 23-slot or 7-slot contract per class"* — the count is
    **25** (exactly the 25 subobject offsets the brief itself lists). With `ActionGkCoachingRun` and
    `match::ai::PlayerGKAuto` the keeper-adjacent total is 27, and **`PlayerGKAuto` has ONE slot** (a
    destructor), so it fits neither contract. [b]
21. *"`0x144032870` … floors Reach at 52 and Reflexes at 65"* — **52 and 65 are the inline constants**;
    the values the save code sees at attribute 40 are **50 and 63**. Anyone patching "52 → 40" should
    expect an output of 39 clamped to 40. [a]
22. *"remaps an easy catch into 73..89 across the whole roster"* — 73..89 is the band for **40..90
    only**; 91..99 skip the remap. Right in spirit, wrong at the top nine points. [a]
23. *"Catching / Clearing / Reflexes / Reach are consumed ONE LAYER DOWN in `0x144032870`"* —
    **incomplete**. GK Reach is *also* consumed at `0x143f4ae0b` as a hard binary gate at 85, and
    Reach + Reflexes + Balance again at `0x143f28c6c` / `0x143f28d4e` / `0x143f28d95` inside PreSaving
    mode 1 with **different** normalisations (÷120 and ÷80). The selector is the main consumer of
    *quality*, not the only consumer of *ability* — and the `vf35` gate is the more actionable of the
    two because it is uncompressed. [b]
24. *"at the executor layer almost no keeper ability matters — only GK Awareness, through a ≤ 0.5 m
    standing error"* — the RNG half is right; the ability half understates it badly (see correction 1),
    and GK Awareness is **not** the only per-player input to the executor layer (flag bit `0x46`). [b]

### To the 2026-09-20 draft of THIS chapter (adversarial review, repaired in place)

Each row states what the draft said, what the bytes say, and where the fix landed. All re-derived
from `eFootball.exe.PRISTINE` and the shipped `Mbinfo` tables before editing.

25. **CRITICAL — "the anime save classes ask `0x144032870` … and hand it to `0x143f31470`" treats one
    consumer as the block.** `bpx.callers(0x144032870)` returns **four**: `0x143f3149e`
    (root `0x143f31470`, the documented one), `0x14402a68c` (root `0x14402a630`), `0x144037bed`
    (root `0x1440374b0`) and `0x143f36f32` (root `0x143f35ed0`). All four are inside the save family.
    `0x14402a630` uses `t = clamp((q−40)/90)` with a **130** cap (`divss xmm7,[0x145b52b90]=90.0`
    @ `0x14402a6cd`, `comiss xmm1,[0x146b18f78]=130.0` @ `0x14402a6b9`) and ≥ 8 `C·t + BASE` arms,
    one of which (`0.7·t + 0.5` @ `0x14402a73a`) runs **0.500 → 0.959 = 52 %** worst/best.
    **Fixed in § 3.1 (new), § What-this-enables, the summary paragraph, § 3 and § 11.** The
    "0.900–1.295" figure is now labelled as one route, and the block-wide range is stated
    **NOT BOUNDED**. [b]
26. **CRITICAL — "`SavingBase::vf47`'s `0xb9c` is a dead placeholder, consistent with every subclass
    overriding slot 47".** `exe_map.json` slot 47: Block `0x143f4a620`, Catch `0x143f4a9d0`,
    ScoopOut `0x143f4b7f0` override; **Deflect, Punch and SnapUnder are all `0x143f30f90` =
    `SavingBase`'s own `mov eax,0xb9c ; ret`**. Half the family inherits it, so it is the live
    default for them. **Negative withdrawn in § 9, § 13 and correction 13; carried back to
    anime-keeper-and-first-touch.md line 70.** New Open 13. [b]
27. **CRITICAL/MAJOR — "No roll decides save-versus-goal … reach no LCG function at any depth".**
    Two defects. (a) Five of six vf30 bodies reach `0x144345d90` at depth **5–6** (90–96 functions)
    via `0x144033a90 → 0x144096500 → 0x14408ac90 → 0x144098d70`; the draft's table was bounded at
    depth 4, one step short, while the negative control is still clean at 143/166 at those depths.
    (b) The draft's "three centimetre-scale offsets" are **one float**, `player+0x442c`
    (`movss [rsi+0x442c],xmm0` @ `0x143f47c3e`, from `mov edx,0xa/5/0x15` draws), spanning up to
    **0.20 m**, and its only readers are at `0x143f3648b` and `0x143f37166` inside the **undecoded**
    `0x143f35ed0`, which also holds the unexplained GK Reach read. **Fixed in § 4 and § 13**; the
    determinism claim is now scoped to the quality path, each closure row states its bound, and the
    save body and `0x143f35ed0` are added to the table. [b]
28. **MAJOR — § 8's seconds were computed under the SUPERSEDED frame rule.** The draft printed
    `frame = (((v>>13)&0x3FF)+2)·2` and then published numbers from `frame = v >> 13`, which is what
    `tools/mbinfo_ef.py::cancel_records()` still returns. Proof from the data: under the proven rule
    every frame is even, so the draft's 0.150 / 0.717 / 1.050 / 1.283 s are arithmetically
    impossible. Re-extracted both ways from `Mbinfo/bin/CancelData.bin` (5,746 records): the raw rule
    reproduces the draft cell for cell. **§ 8 recomputed, plus the § 10 lockout row, the
    What-this-enables row and the summary paragraph. `tools/mbinfo_ef.py` is the stale artefact and
    is flagged, not edited — the tool repo is read-only for this pass.** [a-measured]
29. **MAJOR — "Keeper dives are ~30 % longer commitments than a slide tackle".** The draft divided
    the dive median by the **standing tackle** median while naming the slide. From the same tables:
    raw rule gkdeflect 0.392 / sliding 0.367 / tackle 0.300 → **+7 %** and +31 %; proven rule
    0.850 / 0.800 / 0.667 → **+6 %** and +27 %. **Under either rule the ratio to the slide is
    single-digit, not 30 %.**
    Fixed in § 8 and the summary paragraph. [a-measured]
30. **MAJOR — the `0x143f3c1f0` register flow was misread.** 0.85 / 0.95 / 0.80 load into **`xmm7`**,
    a separate situational factor stored to `[rsi+0x5c]`; the transfer's result lands in `xmm8` and
    is copied to **`xmm6`**, stored to `[rsi+0x58]`. They are two outputs, not a value and its
    ceilings. The only cap on the multiplier is the conditional `minss xmm6,[0x146b58b0c]=1.19`
    @ `0x143f3c580`, gated on actions `0x44`/`0x47` **and** motion class `0x24000`. **Rewritten in
    § 3**, and `0x146b58b0c` (refcount **1**, `private_unproven`, sole class `SavingBase`) added to
    § 10 Tunables as a genuinely private cell. [b]
31. **MAJOR — the "Deflect, Reflexes arm" row merged two different conditions.** The Reflexes
    *quality* arm fires for `sub ∈ {1,4,5}` (`cmp esi,1 ; je` @ `0x144032987`, `lea eax,[rsi-4] ;
    cmp eax,1 ; ja` @ `0x14403298c`), but the `0.32 / lo 20 / span 110` *transfer* is gated on
    `sub == 1` alone (`cmp ecx,0x46 ; jne` @ `0x143f314ee`, `cmp edi,1 ; jne` @ `0x143f314f3`).
    For `sub ∈ {4,5}` the generic transfer gives **0.986 → 1.121 (88 %)**, not 1.025 → 1.130 (91 %).
    **Row split in § 3, consequence added to § 11.** [b + arithmetic]
32. **MAJOR — "a private 1,200-byte function `0x145655430`".** `exe_funcs_chained` gives
    `func_root == 0x145655430`, **4 chunks, 2,461 bytes**. The draft's own citations fall outside a
    1,200-byte extent (the eighth `team+0x275c` writer at `0x145655d04`, the role-0 early-out target
    `0x145655d65`). It is the project's named `func_range` gotcha, inherited from goalkeeping.md
    line 350. **Fixed in § 6 and the summary paragraph.** [b]
33. **MAJOR — "the u32 at `rec+0x24` that `0x144317ec0` unpacks".** `0x14422cb45` is
    `mov rcx, qword ptr [rdi+0x20]` — a **pointer load** — and the unpacker opens
    `movzx eax, word ptr [rcx+4]`. The packed u32 lives at **descriptor+4**, and no field exists at
    `rec+0x24`. As written, Open 3 would have sent the next probe hunting writers of a non-existent
    field. **Fixed in § 7 and Open 3**; "an ANGLE in degrees" relabelled **[c]** (the field is a raw
    0..511 integer converted to float). [b]
34. **MAJOR — the class-status tables never stated what they add up to.** 9 of 25 executors decoded
    or partly decoded, 9 gate-only, 6 listed-only, 1 stub — **and every executor that runs a save
    body is in the undecoded groups**. `Punch` / `Block` / `ScoopOut` / `SnapUnder` were marked
    "decoded" on the strength of the *selector's* view of them. **Summary sentences added to § 14.1
    and § 14.2; those four rows demoted to "quality path decoded, body not read".** [b]
35. **MAJOR — "you cannot author a bad goalkeeper in master.db" / "exactly three levers … all four".**
    The absolute claim ignored the chapter's own Open 2 and Open 8, and the sentence said three then
    listed four. **§ 11 and § What-this-enables rescoped to the documented route; the count fixed to
    four; `0x1440374b0`'s reaction delay named as the most promising fifth.**
36. **MINORS, all one-line, all verified before editing.**
    (a) "everything below 90 passes ×98/100" — the easy-catch arm's `cmp ebx,0x78 ; jle 0x144032a54`
    @ `0x144032945` skips ×98, the >100 halving **and** the `+5` bonus; that is why its floor is 73
    and not 71 (§ 3).
    (b) "91 is a cliff … keep Reflexes and Reach ≤ 90" — the `cmp ebx,0x5a` test is on `q`, so only
    the **Reach** arm jumps at 91; Reflexes and every raw arm jump at 90 (§ 3 table, § 11).
    (c) "points 40–50 are wasted" — the *output* band below 50 is unreachable, but the attribute
    still moves the output ~0.75 points per point (§ 11).
    (d) the positive control row now states its bound (depth ≤ 2, 117) beside the unbounded figure
    (33,116), as the negative control's row does (§ 4).
    (e) "the 732 `gk*` records that carry keys" → **876 records across 732 animations** (§ 10).
    (f) the keeper-advance-cap refcounts are **1086 / 943 / 1099 / 26**, not "26+ each"; and of the
    six transfer constants, **0.32 `0x145e8786c` has refcount 7**, not "every one heavily shared"
    (§ 10).
    (g) the GK Awareness early return needs a **third** term, `|Δbearing| > 40.0` @ `0x1442255b2`
    with the return at `0x144225a29` (§ 1).
    (h) correction 12 over-corrected slot 29 (all six *do* override; four distinct bodies) and
    under-counted slot 30 (**five** distinct bodies across six classes).
    (i) the negative control's unbounded figure re-measured at **33,123** (draft: 33,504).
    (j) the evidence legend now separates **a-emulated** (run here), **a-quoted** (carried from a
    probe) and **a-measured** (recomputed from a shipped file), and § 8 names the directory it was
    run against.

---

## 13. Negatives

* **No RNG reaches the save-QUALITY path — and this is narrower than the draft claimed.** Clean
  **to exhaustion**: the selector `0x144032870` (19 functions), all four of its consumers
  (`0x143f31470` 20, `0x14402a630` 28, `0x143f35ed0` 89, `0x1440374b0` 34), `SavingBase::vf2`
  `canStart` (15), `Deflect::vf35` (6) and `Block::vf30` (1). **The draft's "and all six vf30
  overrides reach no LCG function at any depth" is WITHDRAWN**: five of the six are clean only to
  depth 4 (56–76 functions) and reach `0x144345d90` at depth 5–6 (90–96 functions) via
  `0x144033a90 → 0x144096500 → 0x14408ac90 → 0x144098d70`. The bound the draft chose stopped one
  step short. Whether that RNG is effective on the save is **NOT PROVEN**. Controls on the same
  harness: positive `0x14401a900` fires at depth 2 with 117 explored (33,116 unbounded); negative
  `ChanceSpaceRun::vf5` clean at 107 / 143 / 166 for depths 4 / 5 / 6, 33,123 unbounded. [b]
* **A per-save random displacement DOES exist, and its consumer is undecoded.** `0x143f46370` draws
  `RandInt % {10, 5, 21} × 0.01` into the single float `player+0x442c` (up to a **0.20 m** span, not
  "centimetre-scale"), and the only reader is `0x143f35ed0` — the same undecoded function that holds
  the unexplained GK Reach read `0x143f368da`. **"The save outcome is deterministic given the shot"
  is WITHDRAWN** and replaced by the scoped claim above. [b]
* **`0x143f2b590` is NOT the save-type chooser**, despite carrying every marker of one (10-arm jump
  table, reached only from `PreSaving::vf4`, writes `0x44`/`0x45`/`0x46`/`0x48` from float compares,
  reads GK Awareness). Its tail is
  `movsx ebx, word [rcx + rax*2 + 0x6b572e0]`: those values index a **keeper-footwork motion table**
  at `0x146b572e0`, where `0x44` = `gkmovehigh_sidestep_3_3_f090_ReverseMove` and `0x46` =
  `gkEmagencyMove_back_0_3`. It is the **set-and-shuffle chooser**. Recorded in full so the next pass
  does not repeat it. [b]
* **`0x14403cc60` is not the chooser either** — all its save-id comparisons are on `this->actionId` at
  `[rdi+0x30]`, i.e. after the class is already running. [b]
* **The save-type chooser is NOT LOCATED.** Bounded: not in the attribute reads, not in `PreSaving`,
  not in `0x14403cc60`, not in the pad layer. `byte[plan+0x789]` has exactly one reader in the keeper
  band (`0x143f2bad1`) and no locatable writer. **A precise "not proven".**
* **There is no `match::pad::ThinkUnit` for Catch, Punch, Deflect, ScoopOut or SnapUnder** — the map
  lists keeper units for Block, Tackle, PickupBall, DropBall, AutoPuntkick, Press, TrapMove, AutoMove,
  CursorChangeKeeper, FreekickKeeperMove and three Penaltykick units, and none for the five saves.
  **Saves are engine-automatic and unbindable.** [b]
* **No goalkeeping attribute is read anywhere in the catch envelope** — a flat 3.5 m for everyone. [b]
* **Dive speed has no per-keeper term at all**: every slot-29 frame budget is a global float, varying
  only by save type and by `saving+0x54`. [b]
* **No dt270 field reaches any `goal_keeper::` method body**, and no dt270 reader exists anywhere in
  the keeper executor band. [b]
* **No CPU-difficulty term reaches a save.** [b]
* **No ability gates the keeper coming out**, and none gates distribution — HEIGHT only, as a steering
  and scoring parameter. [b]
* **No RNG and no attribute in `ActionKeeperMovePenaltyKick`** — one class, one overridden slot, one
  float comparison. [b]
* **The PK animation ids are not in a table in the exe.** Negative control: the same u16 scan that
  finds no 851/934 cluster does find 2,101 and 2,135 scattered hits for those ids, so the search was
  not vacuously empty. [b]
* **`player+0x48a0` is not a keeper field** — ~190 read sites across unrelated classes, one writer
  storing `x/180.0`. Its identity is not established; do not assume it is a reach. [b]
* **`SavingBase::vf47`'s `0xb9c` is NOT a proven dead placeholder — negative WITHDRAWN.** It
  resolves to `referee_game_end_1_0_hand_up_whistle`, but Deflect, Punch and SnapUnder **inherit**
  the slot (`0x143f30f90`), so for half the save family it is the live default. Either vf47 is not
  called for those three, or `0xb9c` is not a motion id in this slot — **not proven either way**
  (§ 9, § Open 12). [b + a]
* **`ActionKeeperCoaching` does not organise the wall** — answered, not merely unestablished. [b + a]
* **A tooling bug worth publishing.** A first `team+0x275c` displacement scan reported only **one**
  executor reader and nearly published "the other two use a different field". The cause was an
  off-by-one in the instruction-boundary walk (`range(3,12)` instead of `range(1,13)`), which cannot
  decode `8b 88 5c 27 00 00` — the displacement starts two bytes in. **This is the third
  single-encoding assumption in this project to produce a confident wrong negative.** The same class
  of error explains why a bad disassembly start address yields plausible nonsense: two of the
  verification dumps taken for this chapter began mid-instruction and printed `stc` and
  `xor dh, byte ptr [rdi+0x42]` before converging — those lines are artefacts and nothing was quoted
  from them.
* **NOT PROVEN, deliberately:** that `dword[event+0x14]` in the distribution brain is "frames since
  the restart" (so *"the keeper holds the ball for two seconds"* is **not** claimed); who writes the
  penalty aim descriptor; the names of flag bits `0x46`, `0x12`, `0x14`; and the consumers of
  `ActionKeeperPress::vf6`'s mode/gait ints (so *"mode 2 = hold"* is a label, not a proof).

---

## 14. Class status

### 14.1 `match::player` — 25 `ActionKeeper*` plus 2 keeper-adjacent

Vtables and slot counts from `build/exe_map.json`, cross-checked against raw PRISTINE qwords for every
class this chapter changes.

> **What the status column adds up to, stated plainly because the draft never did: 9 of the 25
> executors are decoded or partly decoded, 9 are gate-only, 6 are listed-only and 1 is a stub — and
> every executor that actually *runs a save body* (`Block`, `Deflect`, `Punching`, `ScoopOut`,
> `SnapUnder`, `SavingMove`) is in the gate-only or listed-only group.** Two of the bolded
> **decoded** rows carry large unread bodies: `BasePosition`'s vf18 is 7,104 B and `Press`'s vf5 is
> 3,131 B, plus the undecoded engage gate `0x144218d40` and vf6 past `0x14421ca8b` (vf6 is 4,739 B
> in 3 chunks). **The executor half of the save is unopened.**

| class | vftable | subobj | slots | best body | status | note |
|---|---|---|---|---|---|---|
| `ActionKeeperAfterCatchMove` | `0x146bc0028` | `+0x13618` | 23 | vf20 `0x144230d10`, vf16 `0x144231560` | gate-only | six **private** bearing cells `0x146be3d10..0x146be3d28`; vf20 not decoded |
| `ActionKeeperBasePosition` | `0x146bbfae8` | `+0x13550` | 23 | vf4 `0x144223580`, vf20 `0x144221e10`, vf18 `0x14422a680` | **decoded** | depth chain, the 16.42 m consumer, the GK-Awareness window, flag bit `0x46`. **vf18 (7 KB) still only partly read** |
| `ActionKeeperBlock` | `0x146bbf9a8` | `+0x136c0` | 7 | s6 `0x14421f8c0` | gate-only | calls the shared reach model `0x143e41310`; 641 B body not followed |
| `ActionKeeperBlockLate` | `0x146bbf9e8` | `+0x13700` | 7 | s6 `0x14421fee0` | gate-only | the **only** GK save-attribute read in the executor layer (`0x25` @ `0x14421ff95`); consumer untraced |
| `ActionKeeperBodyFeint` | `0x146bbfce8` | `+0x139e8` | 23 | vf4 `0x14422f110` | gate-only | requests id `0x52`; no slot 20 |
| `ActionKeeperCatching` | `0x146bbf8e8` | `+0x13650` | 7 | s6 `0x14421d3a0`, s4 `0x14421db50` | decoded | 250-frame scan, flat 3.5 m gate — **requests id `0x46` = Deflect**, not Catch |
| `ActionKeeperCoaching` | `0x146bbfbe8` | `+0x13980` | 23 | vf18 `0x14422e410`, vf16 `0x14422e510` | **decoded** | writes only `work+0x1050`; the goal-kick gesture, **not** the wall |
| `ActionKeeperDeflect` | `0x146bbf968` | `+0x13698` | 7 | s6 `0x14421e600` | gate-only | writes qword `0x53` to `work+0x8bc`; HEIGHT only |
| `ActionKeeperDropBall` | `0x146bdbe38` | `+0x110b0` | 7 | s6 `0x144218a60` | listed-only | 13-function closure |
| `ActionKeeperMakeshift` | `0x146bdf7b8` | `+0x13780` | 7 | s6 `0x144220f30` | decoded | 12-instruction near-stub |
| `ActionKeeperMoveFreeKick` | `0x146be0348` | `+0x13790` | 23 | vf16 `0x14422c740`, vf13 `0x14422c600` | **partly decoded** | vf12 is the shared `return 3`; vf3/vf4 have no `.pdata` |
| `ActionKeeperMovePenaltyKick` | `0x146be09a8` | `+0x137f8` | 23 | vf16 `0x14422ca70` | **decoded** | goal-line pin + ±5 m z step from one `angle < 90.0` test |
| `ActionKeeperPKSaving` | `0x146bbfba8` | `+0x13828` | 7 | s6 `0x14422cc00`, s4 `0x14422d4d0` | decoded | target kind 3; shares `0x14421d350` with Catching. No dive branch |
| `ActionKeeperPickupBall` | `0x146bbfda8` | `+0x13aa0` | 7 | — | stub | proven: **no own body at all** |
| `ActionKeeperPreSaveOperation` | `0x146bbfca8` | `+0x139b8` | 7 | s4 `0x14422e6a0` | decoded | the save-arming gate (`≤ (T·14)/30` ticks left); reads no attribute |
| `ActionKeeperPress` | `0x146bdc420` | `+0x134f0` | 23 | vf4 `0x1442196b0`, vf6 `0x14421c0c0`, vf20 `0x144218f10` | **decoded** | 15 m / 7 m trigger, angle sector, 10 km/h floor. **vf5 (3,131 B) is the path half and is undecoded** |
| `ActionKeeperPunching` | `0x146bbf928` | `+0x13678` | 7 | s6 `0x14421e1f0` | listed-only | 23-function closure; no attribute, no RNG |
| `ActionKeeperPuntKick` | `0x146bbf828` | `+0x110c0` | 7 | s6 `0x144215220` | gate-only | `team+0xb44d` gates a designated target; reads `team+0x275c` @ `0x14421553b` |
| `ActionKeeperSavingMove` | `0x146bbff68` | `+0x135e0` | 23 | vf20 `0x14422f660`, vf4 `0x14422fa10` | gate-only | it **does** override slot 20 (an earlier probe said otherwise); HEIGHT only |
| `ActionKeeperScoopOut` | `0x146bbfa68` | `+0x13740` | 7 | s6 `0x144220c50` | listed-only | 11-function closure |
| `ActionKeeperSeenOff` | `0x146bbfde8` | `+0x13ae0` | 23 | slot7 `0x14422f260` | listed-only | **the only class in 55 that overrides slot 7**; effectively a marker |
| `ActionKeeperSnapUnder` | `0x146bbfaa8` | `+0x13760` | 7 | s6 `0x144220e30` | listed-only | 4-function closure; the anime twin consumes the attributes |
| `ActionKeeperTackle` | `0x146bbfa28` | `+0x13720` | 7 | s6 `0x1442202c0` | listed-only | 68-function closure, HEIGHT only, no RNG |
| `ActionKeeperThroughThrow` | `0x146bbf8a8` | `+0x11120` | 7 | s6 `0x144218450` | gate-only | largest keeper closure (278 fns), no constant-index attribute read; reads `team+0x275c` |
| `ActionKeeperThrow` | `0x146bbf868` | `+0x110f0` | 7 | s6 `0x1442176b0` | gate-only | target from `team+0x275c`; two **private** cells `0x146bdb2dc/e0` |
| `ActionGkCoachingRun` | `0x146bbf1e8` | — | 23 | vf4 `0x14420a340` | listed-only | keeper-adjacent, not an `ActionKeeper*` |
| `match::ai::PlayerGKAuto` | `0x146bbe008` | — | **1** | — | stub | destructor only — **there is no CPU-goalkeeper brain class** |

### 14.2 `match::anime::action::goal_keeper::` — **15 vtables in three contracts**

| class | vftable | slots | id | attribute | status |
|---|---|---|---|---|---|
| `SavingBase` | `0x146b58840` | 50 | — | — | decoded (anime chapter): the 50-method contract |
| `Block` | `0x146b59148` | 50 | `0x49` | GK Reach, raw | **quality path decoded, body not read** — 60-frame budget; BASE 1.00, C 0.40; exempt from `0x1440374b0`'s reaction delay |
| `Catch` | `0x146b598e0` | 50 | `0x44` | GK Catching | decoded — 60-frame budget; BASE 0.95, C 0.30; the slow-ball `max()` path |
| `Deflect` | `0x146b5a018` | 50 | `0x46` | Reflexes (`sub ∈{1,4,5}`) / Reach | decoded — 90/48/60 by `sub`; **the only slot-35 override: Reach ≥ 85 gate**; vf37 multiplies by zero |
| `Punch` | `0x146b5aea0` | 50 | `0x45` | GK Parrying | **quality path decoded, body not read** — 60-frame budget; inherits `SavingBase::vf30` and `vf47` |
| `ScoopOut` | `0x146b5a758` | 50 | `0x48` | GK Reach | **quality path decoded, body not read** — 30/60-frame budget |
| `SnapUnder` | `0x146b5c370` | 50 | `0x47` | GK Catching (shares Catch's jump arm) | **quality path decoded, body not read** — 15-frame budget; vf37 multiplies by zero; inherits `SavingBase::vf30` and `vf47` |
| `AfterCatchBase` | `0x146b49ad0` | 33 | — | — | listed |
| `PuntKick` | `0x146b49be0` | 33 | — | — | listed |
| `Throw` | `0x146b49de0` | 33 | — | — | listed |
| `BodyFeint` | `0x146b49710` | 29 | — | — | listed (= `action::Base` exactly) |
| `DropBall` | `0x146b49800` | 29 | — | — | listed |
| `PickupBall` | `0x146b498f0` | 29 | — | — | listed |
| `PreSaving` | `0x146b499e0` | 29 | — | Reach + Reflexes + Balance in **mode 1** | **partly decoded** — vf4 `0x143f27fb0` dispatches on `player+0x2bdc`; mode 1 `0x143f28c10` reads three attributes with un-saturating normalisations; its downstream is not decoded |
| `SeeOff` | `0x146b49cf0` | 29 | — | — | listed |

**7 of the 15 anime classes have their quality path decoded; 8 are listed with no behaviour at all.**

Shared bodies worth knowing:
**Slot 30** is `0x144032400` for SavingBase, Deflect **and** SnapUnder — only Block
(`0x143f4a5d0`), Catch (`0x143f4a890`), ScoopOut (`0x143f4b1f0`) and Punch (`0x143f4b850`)
override, giving **five distinct bodies across the six subclasses**, two of them inherited.
**Slot 29** is overridden by all six, but Block, Catch and Punch share `0x143f4a5c0` (Deflect
`0x143f4ad80`, ScoopOut `0x143f4b1d0`, SnapUnder `0x143f4fb70`) — **four distinct bodies**.
**Slot 47** is overridden by Block, Catch and ScoopOut only; Deflect, Punch and SnapUnder inherit
`SavingBase`'s `0x143f30f90` (§ 9). The counts differ per slot; do not carry one to another. [b]

---

## 15. Open questions

1. **Name the per-player flag bits.** `0x1442c0000` indexes a 73-entry bitfield at `playerRec+0xc0`;
   bit `0x46` gates keeper positioning, `0x12` and `0x14` gate distribution.
   `src/ML.Core/Development/PlayerSkillCatalog.cs` says the names live in `dt261` `all.str`
   [66105..66178] (74 strings against 73 entries) but its array is grouped thematically, not in
   string-table order. **Route: dump `all.str` in original order, index it, check whether `0x46` is a
   GK-only skill.** That converts three proven reads into three named, editable player-data levers —
   the highest-value item here.
2. **The consumers of `reachN`, `reflN` and `Balance` inside `0x143f28c10`** (PreSaving mode 1). The
   three reads and their normalisations are decoded; the ~0x16xx bytes downstream across three chunks
   are not. **The most promising remaining place for real per-keeper differentiation.**
3. **Who allocates and writes the penalty aim descriptor.** `rec+0x20` holds a **pointer** to a
   descriptor object; `0x144317ec0` unpacks the u32 at **descriptor+4** into `(v & 0x1ff)` plus two
   3-bit fields and a flag byte. **Do not scan for writers of `rec+0x24` — that field does not
   exist**, and the earlier draft sent the next probe there. If the descriptor is the kicker's aim
   the keeper reads the penalty; if it is a keeper-side instruction he is being told. **This decides
   whether "the CPU keeper cheats on penalties" is true.**
4. **The four private distribution target-finders** `0x143d104b0` (911 B), `0x143d0ff40` (722 B),
   `0x143d10220` (646 B), `0x143d10840` (702 B). Unopened. This is where *who the keeper actually
   throws to* lives. Also `0x145655dd0`, the 416-byte sibling taken when `bp+0x6d19` is false.
5. **Where `byte[plan+0x789]` is written** — and therefore where the save type is chosen. One reader
   in the keeper band (`0x143f2bad1`); byte/word/dword store scans return only generic struct helpers
   (`0x144338e40`, `0x144339120`) with a dozen unrelated callers each.
6. **How the other four save types are requested.** `0x45`, `0x47`, `0x48` and `0x49` are never
   written as immediates to `player+0x8bc` anywhere in the image, so they arrive by a register write
   or a different channel entirely.
7. **What `0x1440381b0`, the sole caller of `Deflect::vf35`, does with the boolean** — i.e. exactly
   which behaviour a sub-85 GK Reach keeper loses.
8. **Undecoded attribute sites:** `0x143f368da` (GK Reach inside `0x143f35ed0`, under
   `SavingBase::vf4`), `0x1440420ac` (GK Parrying inside `0x144040730`, outside the selector), and the
   two GK Awareness sites `0x143f4238a` (in `0x143f41b80`) and `0x143f4a224` (in `0x143f49550`). Plus
   `ActionKeeperBlockLate`'s Reflexes read at `0x14421ff95`, whose closure saturates at 18 functions
   by depth 3 — inherited unresolved from `player-executors.md` Open 12.
9. **The 133 of 640 `gk*` animations (21 %) whose first cancel key sits at or past the motion end**
   under the proven frame rule — 37 (6 %) under the superseded raw rule. Either the frame decode has
   an exception for short motions, or the `+2`/doubling does not apply uniformly, or these are
   authoring errors. **The size of this anomaly is itself the best available test of the frame rule.
   Settle it before anyone edits `CancelData.bin`.**
10. **Flag `0x1e`** in `0x143eadbe0(player, 0x1e)` — the gate on the selector's `+5` bonus. Still
    unidentified.
11. **`ActionKeeperBasePosition::vf18`** (`0x14422a680`, 7,104 B) — one term read. It still holds
    13.0, 13.5, 28000.0, 85.0 and the 0.694444 (= 25/36) cell that also appears in `0x144228170`. Also
    `ActionKeeperPress::vf5` (3,131 B), `vf6` past `0x14421ca8b`, `0x144218d40` (the final engage
    gate), and `team+0x799c` (the depth reference — **no writers found**).
12. **The three undocumented consumers of the save-quality integer** (§ 3.1): `0x14402a630`
    (1,778 B / 7 chunks — which of its ≥ 8 arms runs when, and what its output scales),
    `0x143f35ed0` (7,433 B / 6 chunks — the 0.4..1.0 vector scale, the GK Reach read `0x143f368da`
    **and** the reader of the random `player+0x442c`, all in one body: **the single highest-value
    remaining target in this chapter**) and `0x1440374b0` (2,988 B / 10 chunks — the reaction-frame
    delay; pin `xmm6` on that path to convert `(120−q)/16` into real milliseconds).
13. **Is `SavingBase::vf47` called for Deflect, Punch and SnapUnder?** If it is, `0xb9c` is a live
    motion id resolving to a referee animation, which would be a shipped bug worth reporting; if it
    is not, the slot is vestigial. Find the call site of slot 47 in the 50-slot contract (§ 9).

---

## Provenance

Decoded from `C:/Users/tjgg2/Backups/eFootball/eFootball.exe.PRISTINE`; the installed image equals it
and the twelve quoted ranges were byte-compared (0 differing). Tools: `tools/exe_map.py`,
`build/exe_map.json`, `tools/exe_census.py`, `build/exe_constant_census.json`, `tools/bpx.py`,
`tools/exe_funcs_chained.py` (chunk-aware — `func_chunks`, never `func_range`),
`build/dt270_liveness.json`, `tools/mbinfo_ef.py` with `tools/data/ef_anime_names.json` (7,883
entries), `tools/data/attr_index_map.json` (attribute names under the **proven**
`DATA_PARAMETER + 7` alignment), and `tools/emu_gk_quality_indep.py` — a Unicorn harness that runs
`0x144032870`'s own bytes with stubbed getters, written independently of the earlier probe and
reproducing it exactly.

**Reproducing § 8.** The motion tables were read from the already-extracted
`ef230/common/anime/Mbinfo/bin/` in this session's scratchpad — `CancelData.bin` (61,449 B on disk,
unwrapping to 68,952 B = 5,746 × 12) and `Animation.bin` — through `mbinfo_ef.load()` /
`anim_records()`. **The frame decode was applied on top, not taken from the tool**:
`tools/mbinfo_ef.py::cancel_records()` still returns the superseded `v >> ANIM_ID_BITS`, with no
`0x3FF` mask, no `+2` bias and no doubling. Apply `(((v>>13) & 0x3FF) + 2) * 2` yourself until that
function is fixed. The tool repo was read-only for this pass, so it was not edited here.

**Which corrections are new.** Items 1–10, 18–22 and 24 restate, in substance, findings already in
[goalkeeping.md](goalkeeping.md) § 9 / § 10; items 11–17 and 23 are new to this chapter; items
25–36 are repairs to this chapter's own 2026-09-20 draft following adversarial review. **Analysis only: no game file was modified, nothing was written
under the Steam install, no `exe_patch`/`gameplay_tune` mutation was run, and no commit was made.**
