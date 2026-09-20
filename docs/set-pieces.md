# Set pieces — the dead ball, end to end (2026-09-20)

Every restart in the game: who takes it, how long the ceremony lasts, what the CPU decides to do
with it, how the ball is actually struck, where the twenty-two bodies stand, how far the defenders
have to retreat, and why penalties are so rare. **Set pieces were never a subsystem.** There is no
`match::setpiece` namespace and no set-piece class hierarchy. The work is spread across the six
subsystems already decoded, and this chapter stitches them together rather than re-deriving them.

**The one-line verdict, and it has two halves that must not be collapsed into one.** The *decision*
side of a dead ball — who is allowed to take it, how long the CPU waits, whether a free kick is
shot or passed, where the CPU aims a penalty, whether a wall player jumps, whether the referee gives
the foul at all — reaches **no random number generator on any call edge in its transitive closure**
(virtual dispatch excepted — see § Both controls for the exact scope). The *launch* side is the
opposite: `match::anime::action::Restart::vf8` and its solver make **ten stochastic draws**, and on
**one narrow path** they gate a re-draw on **Set Piece Taking** through a logistic whose own midpoint
sits at rating **72** and which crosses a **50 % re-draw rate at rating 63**.
**That path is narrow and the narrowing is load-bearing**: the roll fires only for a *forward-
simulated solution that the goal-mouth test classifies 2* — the ball entering the goal within 1.0 m
of a post — and only while the kick-mode byte `player+0xad0` is `0x26` or `0x2c`. A corner cross, a
throw-in, a kick-off, a goal kick and any free kick played as a pass never produce a class-2 step, so
Set Piece Taking has **no effect on them at this site**.
Anyone who reads "set pieces are deterministic" and then goes looking for the free-kick accuracy
model in `ThinkUnitSetPlay` will find nothing, because it is in the animation layer.

Produced by two workflow probes plus a verification pass, then an adversarial repair pass (2026-09-20)
whose findings are all listed in § Corrections. **Every contested claim and every number quoted as a
lever was re-derived from the PRISTINE bytes** — with **one stated exception**: the quick-restart
gate row in § Tunables is carried from a probe and is marked **[c]** there. Where the two probes
disagreed, the re-read decides and the loser is named in § Corrections. **Two of the probes' own
headline claims did not survive it** — the 9.15 m tunable site, and "positionPK is unlocated" — and
one of the probes' framings ("set pieces are the most deterministic subsystem in the game") is true
only of the half of the subsystem it looked at.

**Carried from the probes and NOT independently re-derived here**, so treat these at one remove:
the line-group counter loop `0x143d03030..0x143d0310a` and its jump table `0x143d03680`; the
command packer family `0x144318660`/`700`/`820`/`8f0`/`990` and the 0/180 snap at `0x1440dae02`;
the `match::Command::update` 8-pad-slot loop and the command-writer sweep; the advantage block
`0x143d88643..0x143d889e3`; the `EMatchFlowTask` / `match::Match::vf1` state chain; the
`ThinkUnitAutoRestart` command-id table `0x1440e51e8`; the `0x1442e0180` predicate; and the
`ActionKeeperCoaching` vf16/vf18 bodies. Everything in § The anti-penalty bias, § Penalties,
§ positionPK, § Referee placement, § Corners, § Free kicks, § Throw-ins and § Delivery **was**.

Evidence levels: **a-emulated** (the game's own bytes executed under Unicorn with controlled
inputs), **b-disassembly** (followed instruction by instruction; extents from the *chained-unwind*
`.pdata` walk via `exe_funcs_chained.func_chunks` — never `func_range`), **c-inferred** (structural
reasoning only). Addresses are VAs at base `0x140000000`, no ASLR.

**Image provenance, verified here.** SHA-1 of `eFootball.exe.PRISTINE` and of the installed
`…/Binaries/Win64/eFootball.exe` are **identical** (`d2b84d1c506ab09d62035b7889a57452479b73a8`,
352,409,088 bytes each); `eFootball.exe.STOCK` differs (`5e72a16e…`, the two hostname bytes).
**Nothing in this chapter is patched on the installed game today**, and nothing in this chapter was
applied. This is an analysis-only pass: no game file was written, no `exe_patch` ran, no commit was
made.

Companion chapters, cited throughout and not duplicated:
[player-executors.md](player-executors.md) (`match::player`),
[ball-carrier-brain.md](ball-carrier-brain.md) (`match::ai::bp`),
[anime-actions.md](anime-actions.md) (`match::anime`),
[goalkeeper.md](goalkeeper.md), [match-ai-decoded.md](match-ai-decoded.md) (referee),
[registry-blackboard.md](registry-blackboard.md), [pad-input.md](pad-input.md).
**Five of them are corrected by this chapter** — see § Corrections before leaning on any of them.

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| **more penalties** — undo the anti-penalty bias | two halves, four inline immediates. The in-box **severity threshold 60** (`mov eax,0x3c` at `0x143d862a4`) versus 40 outside (`mov ecx,0x28` at `0x143d8629f`); and the in-box **ball-contest veto 0.4** versus 0.7 outside (`0x143d874a7` / the `movaps xmm6,xmm8` at `0x143d874c1`) | exe code. The two thresholds are **private inline immediates**, one instruction each. The two vetoes are shared pool cells (0.7 = 461 referrers, 0.4 = 623) and must be re-aimed, and the in-box one needs a cave because it arrives via a **4-byte** `movaps` (`41 0f 28 f0`) — the detour has to swallow the following `comiss` too | b, re-derived here; **not applied** (§ The anti-penalty bias) |
| dead-ball accuracy that separates a 95 free-kick taker from a 60 **on near-post strikes only** | the logistic in `match::anime::action::Restart::vf8`: four cells at `0x143f0540b`/`0x143f05413`/`0x143f0541b`/`0x143f05423` set the midpoint and steepness of P(re-draw the kick solution). **SCOPE**: the roll is reached only from `call 0x143f06210 ; cmp al,2 ; je 0x143f0567a` at `0x143f05575`–`0x143f0557c` — a simulated step entering the goal within 1.0 m of a post — inside a loop gated on `player+0xad0 ∈ {0x26, 0x2c}` at `0x143f054b5`. It does **not** touch corner delivery, throw-ins, kick-offs, goal kicks or any restart played as a pass | exe constants — re-aim; **99.0** has 90 referrers, **−59.0** has 8, **5.5** has 64, **2.5** has 477 | a-emulated for the curve: 40 → 90.74 %, 72 → 25.43 %, 85 → 5.40 %, 99 → 0.58 %. b for the scope |
| stop the CPU taking corners and free kicks instantly | the delivery clock in `ThinkUnitSetPlay`'s per-kind arms: CPU corner `fps×3.0`, human `fps×7.0`, etc. | exe constants — **all generic floats** (3.0 = 1,761 referrers, 7.0 = 398), re-aim only | b |
| more (or no) short corners | `cmp r8d,0xa` at `0x1456b0634` — a **private inline immediate**, one byte | exe code | b. NOTE the word it compares is a live match value mod 100 whose provenance was **not traced**, so "10 % of corners" is the code's shape, not a measured rate |
| change how far out the CPU tries a direct free kick | the squared-distance ladder 529 / 676 / 900 / 1600 at `0x1456b0f37`, `0x1456b0eec`, `0x1456b0e7c`, `0x1456b0f59` | exe constants — and these are **near-private**: 529.0 has **6** referrers, 676.0 has **10**, 1600.0 has **28**, 900.0 has 60 | b |
| make the curled free kick a specialist trait | `cmp al,0x55` (Set Piece Taking ≥ 85) at `0x1456b0f1a` and `cmp al,0x50` (Curl ≥ 80) at `0x1456b0f30` | exe code — **private inline immediates**, the safest edits in this chapter | b |
| change the restart retreat distance — and, probably, where the wall stands | **the 9.15 m the restart standoff uses is pool cell `0x146b18170`, read by the `movss xmm6,[rip+0x2dcf543]` whose opcode starts at `0x143d48c25` and whose disp32 field is `0x143d48c29..0x143d48c2c`** — *not* the inline `0x1442ec757` a probe nominated, which writes a different copy consumed only by the pitch-zone classifier | exe constant — re-aim; the cell has **6 referrers**, one of which is the standoff provider | b, re-derived here. **"Probably" is load-bearing**: the provider/enforcer pair is proven, but that `EMatchFlowTask::FkWallSet` places wall members with the same radius is **not** (§ Open 12) |
| choose who is in the wall, or make jumping ability-dependent | **not reachable.** `ActionWallJump` is a relay: it reads a pre-written per-slot command cell `teamAI+0x8f4c+slot*4` holding `0x69 WALL_JUMP` / `0x6a WALL_NOT_JUMP` and emits it. No attribute, card or playstyle on the path. The writer of that cell was not found | — | b |
| move the twenty-two bodies at a penalty | `positionPK_{2,3,4,5}` — **located and live**: fetched **by name** via `sprintf("positionPK_%d", backLineCount)` at `0x143c4c43d`, read by `0x143c685a0`, applied by `0x143c4f5f0` | **dt270 data file** — no exe patch, no shared cell, survives Konami updates. The safest lever in this chapter | b for the path, a for the values (§ positionPK) |
| ability-scale *who receives* a corner or free kick | **not possible.** **Twelve functions** scanned end to end for **seven different getters**: zero attribute, card, playstyle, level-row or difficulty reads. The **long throw** is the single exception | — | b, with positive controls |
| stop the CPU keeper diving before the kick | he almost certainly never does. `ActionKeeperMovePenaltyKick::vf16` needs a **command record of kind 2 on the keeper's own index**, and the only writers of command records in the image are the human/online marshalling chain | — | b for the gate; **c** for "the CPU keeper's record is empty" (§ Open 2) |
| vary CPU penalty aim | the 7-entry jump table at `0x1456aeefc`, indexed by `dword[URandomInfo_front + 0] % 7` | exe code (a `.rdata` table) — **but read § Open 1 first**: `registry-blackboard.md` § 8.1 records that word as having **ten readers and no writer found**. If it is never written, the index is **always 0** and the CPU aims at one spot all match | b for the table; the frozen-index risk is **c** and is the highest-value live read in this chapter |

---

## Set pieces in one paragraph

A restart begins when `UMatchInfo+0x34a0` becomes non-zero: **1 kick-off, 2 throw-in, 3 goal kick,
4 corner, 5 free kick, 6 penalty**. The match flow machine (`match::Match::vf1`, a 110-state switch
on `match+8`) runs a fixed chain of `EMatchFlowTask`s — `SetplayStart → MemberChange → FkWallSet →
WaitQuick → SetplayWhistle → WaitInplay → Inplay` — with `PositionWarp` loading the penalty tableau
out of dt270 when the kind is 6. Meanwhile every player on the pitch is pushed outside a retreat
radius by a per-frame enforcer, and one player — **his side's cursor player, `UMatchInfo+0x41d8`** —
is admitted to `match::ai::bp::ThinkUnitSetPlay`, a **six-way jump table on the restart kind** that
decides *what the delivery is*: shoot, pass, throw-in rotate. **Five of the six arms carry that
cursor gate; the FREE_KICK arm has none**, which is exactly why it is the arm that also reasons about
the defending side. The unit does not choose the taker; it only checks that the caller is him. Its
answer record is picked up by **most** of the `match::player` kick executors (`ActionCornerKick`,
`ActionFreeKickLong`, `ActionThrowin`, `ActionPenaltyKick`, `ActionGoalKickLong`) through the same
published-result table every open-play kick uses — **but not all of them: `ActionFreeKick`'s slot 6
is an unconditional `mov al,1 ; ret` (`0x140c83810`) and has no published-decision reader at all, and
`ActionKickoff` resolves its target in a slot-5 body (`0x1441c4880`) before any published decision is
consulted.** The executor fills a kick-work block. Then — and this is the part nobody had traced —
the animation layer takes over through **`match::anime::action::Restart::vf8` (`0x143f05150`)**,
which is a *different function from the open-play kicker's* `Kick::vf8`. In kick modes `0x26`/`0x2c`
it forward-simulates the flight up to 250 steps, and **on the one class of step where the ball is
heading into the goal inside a 1 m band of the post** it rolls the taker's **Set Piece Taking**
against a logistic and, on a pass, throws the solution away and draws another. Everything before
that roll is deterministic; the roll and the solver behind it are not.

---

## `ThinkUnitSetPlay`'s body

`ball-carrier-brain.md` lists `ThinkUnitSetPlay` (registry ctor `registry+0x13b8`, kind `0x1d`,
constructed by `0x1456aeca0`, listed for ball states 11/12/13) with its body unread. It is read now.

**vftable `0x14772f3e8` = `{0x14566feb0, 0x1456b0050, 0x1456b0060}`. `vf2 = 0x1456b0060`**, 1,348
bytes (`0x1456b0060..0x1456b05a4` across seven chained-unwind chunks). It opens by latching the
restart clock — `unit+0x78 = matchEnv+0x3318 − rec+8`, in **frames** — and then dispatches:

```
0x1456b031b  mov  eax,[r14+0x34a0]   ; the restart kind
             dec  eax
             cmp  eax,5
             ja   0x1456b0552        ; kind 0 or >=7 -> the kick-off arm
             lea  rdx,[rip-0x56b0334]
             mov  ecx,[rdx+rax*4+0x56b058c]
             add  rcx,rdx
             jmp  rcx
```

Jump table read from PRISTINE at `0x1456b058c`: `52 05 6b 05 | a7 03 6b 05 | d3 03 6b 05 |
ff 03 6b 05 | 2b 04 6b 05 | 40 04 6b 05`. [b]

| `+0x34a0` | kind | arm | handler | cursor-gated? |
|---|---|---|---|---|
| 1 | KICK_OFF | `0x1456b0552` | `0x1456b1f10` (582 B) | yes |
| 2 | THROW_IN | `0x1456b03a7` | `0x1456b2160` (1,006 B) | yes |
| 3 | GOAL_KICK | `0x1456b03d3` | `0x1456b1b80` (904 B) | yes |
| 4 | CORNER_KICK | `0x1456b03ff` | `0x1456b05b0` (1,303 B) | yes |
| 5 | FREE_KICK | `0x1456b042b` | `0x1456b0ad0` (4,268 B) | **no** |
| 6 | PENALTY_KICK | `0x1456b0440` | inline, calls the aim builder `0x1456aecd0` | yes |
| 0, ≥7 | — | falls to the KICK_OFF arm | | |

**`0x1456b0ad0` is only the FREE_KICK arm.** `ball-carrier-brain.md` labels that address "SetPlay"
and attributes the unit's whole gate list to it; anyone auditing set pieces there sees a fifth of
the unit and none of the corner, throw-in, goal-kick, kick-off or penalty behaviour. [b]

Every arm but FREE_KICK begins `mov ebx,[r14+0x41d8]; call 0x14173d320; cmp eax,ebx; jne <exit>` —
the acting player must **be** his side's cursor player. FREE_KICK has no such compare, which is
exactly why it is the arm that also has to reason about the defending side. [b]

The unit writes answer classes **1** (SHOOT, with shot type and a full aim triple), **2** (PASS,
with a target slot and a pass type), **8** (`THROWIN_ROTATE`), and `0xb`/`0xd`.

---

## Who takes it

**The taker is `UMatchInfo+0x41d8`, and `ThinkUnitSetPlay` does not choose it — it only verifies
it.** Nothing in `0x1456b0060`'s seven chunks writes that field. `control-source-and-human-vs-cpu.md`
§ 5 establishes `+0x41d8`/`+0x41dc` as the two cursor player indices.

The human path exists: the pad command enum carries `KICKERSELECT_DECIDE`, `FREE_KICK_CHANGE`,
`GOAL_KICK_CHANGE`, `KICK_OFF_CHANGE` and `FREE_KICK_POSITION_CHANGE` (string run near VA
`0x146c2bd50`). **The CPU-side writer of `+0x41d8` for a restart was not located.** That is the
honest residue, and it is the literal subject of the owner's complaint that the wrong player takes
corners. See § Open 3. [b for the negative; the writer is unfound, not proven absent]

---

## Delivery — and dead balls do **not** use the open-play kick-error model

This inverts the premise the job was commissioned with, and it is the most important structural
finding in the chapter. **Two scope facts to carry through the whole section**: (a) the launcher
`0x143f05150` is shared by every Restart-family class except four — the two *ceremonial* goal kicks
plus `PkWait` and `PKDemo` — so "the goal kick is launched elsewhere" is true only of those two
ceremonial classes; and (b) the Set Piece Taking roll inside the launcher fires on **one narrow
path** (class-2 step, kick modes `0x26`/`0x2c`), not on every dead ball.

The open-play kick-error builder is `0x14401a900`. Re-derived here from PRISTINE:

* `0x14401a900` has **exactly one caller**, `0x144016d3d`, inside `0x144016a70`.
* `0x144016a70` has **exactly one caller**, `0x143ed10f1`, inside `0x143ed0f80`.
* `0x143ed0f80` is **`match::anime::action::Kick::vf8`** (`exe_map.json`).

And vtable slot 8 across the anime Restart family, read out of `build/exe_map.json`:

| class | vf8 | | class | vf8 |
|---|---|---|---|---|
| `Restart` | `0x143f05150` | | `KickoffKicker` | `0x143f05150` |
| `FreeKick` / `FreeKickLoop` | `0x143f05150` | | `KickoffOther` / `KickoffReceiver` | `0x143f05150` |
| `CornerKick` / `SeamlessCornerKick` | `0x143f05150` | | `QuickRestartKick` | `0x143f05150` |
| `ThrowinNormal` / `ThrowinLong` / `ThrowinLoop` / `SeamlessThrowin` | `0x143f05150` | | `WallJump` / `WallLoop` / `WallNotJump` / `WallRunOut` / `WallNotRunOut` | `0x143f05150` |
| `PenaltyKick` / `PenaltyKickLoop` | `0x143f05150` | | `GoalKickStandby` / **`SeamlessGoalKick`(+`Ready`)** | `0x143f05150` |
| `SeamlessCornerKick`(+`Ready`) / `SeamlessPass`(+`Ready`) | `0x143f05150` | | **`GoalKickLongPass` / `GoalKickShortPass` / `PkWait` / `PKDemo`** | **`0x140c83910` (`ret 0`)** |
| `Kick` (open play) | **`0x143ed0f80`** | | | |

**Only four classes stub slot 8**, and two of them are the ceremonial goal kicks. Every other class
in the family — including all five wall classes, both seamless goal-kick classes, `GoalKickStandby`,
`SeamlessCornerKickReady` and the `FreeKick2nd*`, `*Loop` and `QuickRestartReady` classes — carries
`0x143f05150`. [b, read from `build/exe_map.json`]

**No dead ball reaches `0x14401a900`.** The dead-ball accuracy model is a separate model, not a
different set of arguments to the same one. [b]

### What `Restart::vf8` actually does

`0x143f05150` (1,503 B). **The function is entered unconditionally** — corrected here; an earlier
draft said it was entered only in kick modes `0x26`/`0x2c`. What those modes gate is the *work*:

* `0x143f05259 cmp dword[rdi],5 ; jne 0x143f053d2` — and only inside that arm does
  `0x143f05279 movzx eax,byte[r15+0xad0] ; cmp al,0x26 ; je ; cmp al,0x2c ; jne 0x143f053cf` run.
* The **forward-simulation loop is separately gated** by the same byte at
  `0x143f054b5 movzx eax,byte[r15+0xad0] ; cmp al,0x26 ; je 0x143f054c9 ; cmp al,0x2c ;
  jne 0x143f05594` — a non-matching mode jumps clean over the loop to the commit path. Since the
  only entry to the re-draw roll is inside that loop, **the accuracy roll is mode-gated even though
  the function is not**. What `0x26`/`0x2c` mean, and what `[rdi]` counts, were **not established**
  — see § Open 17. [b]

1. Call the **restart launch solver `0x143f05730`** (2,487 B) at `0x143f053f2` — the stochastic kick
   builder for dead balls. Direct RNG census of its chunks, run here: **6 × `RandInt` (`0x143ea9260`)
   at `0x143f05b7d`, `…5bb2`, `…5bd7`, `…5cc0`, `…5d29`, `…5d40`; 3 × Gaussian (`0x144345eb0`) at
   `0x143f05bff`, `…5cd9`, `…5d85`**; 2 × `expf`; and one ATTR read, `edx = 0x21` at `0x143f058a3`.
   It also calls **`0x144345ae0` four times** (`0x143f05f07`, `…5f3d`, `…5f59`, `…5f86`) — **that is
   the 360° angle wrap, not a draw of any kind**, and it is excluded from the count. Disassembled
   from PRISTINE: it takes a `float*` in `rcx`, compares against `0.0` and `[0x145b1d920] = 360.0`,
   stores the value back unchanged when it is already in range, and otherwise calls `fmodf`
   (`0x140a24ed0`) and adds 360 back if negative. **So the solver's stochastic content is nine
   draws, not thirteen.** [b]
2. Read the taker's **Set Piece Taking** (attr `0x21` = `PLACE_KICKING`, `confidence: proven`) at
   `0x143f053f7`/`0x143f053ff` and build a logistic:

```
0x143f05404  movd xmm0,eax ; cvtdq2ps
0x143f0540b  subss xmm0,[0x145c36ac4]   ; 99.0      -> xmm0 = SPT - 99
0x143f05413  divss xmm0,[0x146b368f4]   ; -59.0     -> (99 - SPT)/59
0x143f0541b  mulss xmm0,[0x145d8be98]   ; 5.5
0x143f05423  subss xmm0,[0x145c1dd28]   ; 2.5
0x143f0542b  mulss xmm0,[0x147850560]   ; -1.0
0x143f05433  call 0x140a24cd0           ; expf
0x143f05438  addss xmm0,xmm9 (=1.0) ; xmm7 = 1/xmm0   -> sigma
```

3. Forward-simulate the flight, `dword[0x148080f50]` = **250** steps at `dt = 1/fps`
   (`0x143f054e0..0x143f0558a`), classifying each step with the goal-mouth test `0x143f06210`:
   **0** not in the goal, **1** in the goal, **2** in the goal but within **1.0 m** of the post
   margin (`subss xmm7,[0x1478502b8]` at `0x143f062a7`).
4. **On a class-2 step and on no other path**, roll. The single branch into the roll block is
   `0x143f05575 call 0x143f06210 ; 0x143f0557a cmp al,2 ; 0x143f0557c je 0x143f0567a`, and
   `0x143f05682` is the only `RandInt` in the whole function:

```
0x143f0567a  mov edx,0x64 ; call 0x143ea9260   ; RandInt -> 0..99 (NOT 0..100)
0x143f0568b  mulss xmm7,xmm7                   ; sigma^2
0x143f05696  mulss xmm7,[0x145a8aa4c]          ; x100
0x143f0569e  comiss xmm7,xmm0
0x143f056a1  jbe  0x143f05594                  ; KEEP the first, tighter solution
             ...  0x143f056f6 call 0x143f05730 ; else RE-DRAW
```

**The wrapper returns `0..99`, not `0..100`**: `0x143ea9260` ends
`test ebx,ebx / cdq / cmovne ecx,ebx / idiv ecx / mov eax,edx`, i.e. the remainder modulo the bound,
so `edx = 0x64` yields 0..99. [b]

So **P(re-draw) = P(roll < 100·σ²)**, which with an integer roll is exactly **⌈100·σ²⌉/100**, ≈ σ².
The table below quotes the continuous σ² to four figures; the discretised value is the next
hundredth up. σ is the logistic above. Emulated on the game's own
bytes including its real `expf`, with five literal-pool controls all reading back correct
(`tools/emu_deadball_accuracy.py`, re-run for this chapter):

| Set Piece Taking | 40 | 50 | 60 | 70 | **72** | 75 | 80 | 85 | 90 | 95 | 99 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P(re-draw) | 90.74 % | 78.81 % | 57.29 % | 30.32 % | **25.43 %** | 18.90 % | 10.59 % | 5.40 % | 2.55 % | 1.13 % | 0.58 % |

**P(re-draw) crosses 50 % at Set Piece Taking ≈ 63** (the logistic σ itself crosses 0.5 at 72 — do
not confuse the two, they are five ratings' worth of argument apart), and the curve is steepest
between **58 and 68**, falling ~13 points of re-draw probability per 5 ratings there. [a-emulated;
the algebra also re-derived by hand from the four disp32s above and it agrees to the digit]

**Read the scope with the curve, always.** This is the only place Set Piece Taking reaches the
strike, and it reaches it *only* for a solution the forward sim shows entering the goal within 1.0 m
of a post, in kick modes `0x26`/`0x2c`. It is a **near-post-accuracy** lever, not a general dead-ball
accuracy lever. Nothing here differentiates a 95 taker from a 60 on a corner cross, a throw-in, a
kick-off, a goal kick or a free kick played as a pass. [b for the scope]

**What the re-draw *does* is not proven.** The roll and its curve are certain. Whether taking the
re-draw branch produces a *worse* kick or merely a *different* one is inferred from the fact that
the discarded solution was the one heading inside the post margin. `0x143f05730` was censused, not
decoded. § Open 5.

**Set Piece Taking never enters the open-play error model.** The open-play kick-class picker
`0x143ed7440` (jump tables `0x143ed7a90` / `0x143ed7aa8` / `0x143ed7af0`) only ever selects
attribute `0x1b` Low Pass, `0x1c` Lofted Pass or `0x1d` Heading; its `0x21`/`0x22` reads go through
the **card** getter `0x143eadbe0`, not `ATTR_get`. [b]

---

## Corners

Handler `0x1456b05b0` (`0x1456b05b0..0x1456b0ac7`).

**Short or normal is decided first, by a modulo — not by an LCG draw:**

```
0x1456b0607  call 0x1442eba80(ring, 0)         ; a ring-buffer record
0x1456b060f  mov  r8d,[rax+8]
0x1456b0613  mul  0x51eb851f ; shr edx,5 ; imul ecx,edx,0x64 ; sub r8d,ecx   ; r8d %= 100
0x1456b0624  cmp  dword[r9+0x84],1
0x1456b062c  jne  0x1456b0634
0x1456b062e  cmp  r8d,0x32                     ; 50 % when playerRef+0x84 == 1
0x1456b0634  cmp  r8d,0xa                      ; 10 % otherwise
0x1456b0638  jae  0x1456b0837                  ; -> normal delivery
```

A **short corner** emits answer class 2 with **pass type 0 (ground)** to the player named at
`matchEnv+0x25a9c` / `+0x25aa4+side*0x58`; a **normal corner** emits class 2 with **pass type 1**
(`mov ecx,1; mov [r14+0x20],ecx` at `0x1456b0a93`).

The short-corner **window** is a second gate, and it is short:

```
0x1456b0654  movss xmm7,[0x147850490] = 2.0            ; the default window
0x1456b064f  call 0x1442e0e80(ctrlTable, idx)          ; pad-bound?
0x1456b065e  jne  0x1456b06c9                          ; if so, SKIP the team-mate scan entirely
0x1456b06ac  cmp  dword[rax+0x568],0x2c ; je 0x1456b073c   ; a mate already running SHORT_CORNER_MOVE
0x1456b073c  movss xmm6,[0x145c36ac0] = 7.0            ; ... stretches the window to 7.0
0x1456b06ce  cmp  dword[rbp+0x78],0 ; jbe -> normal
0x1456b06d8  call 0x14533ea80 ; mulss xmm0,xmm6 ; addss xmm0,0.5 ; cvttss2si
0x1456b06f2  cmp  dword[rbp+0x78],eax ; jae -> normal
```

So a short corner is only available while `0 < clock < fps×2.0 + 0.5` frames — stretched to
`fps×7.0 + 0.5` if a team-mate is **already** running action `0x2c SHORT_CORNER_MOVE` (id from the
action-name pointer table at `0x148082f80`, whose action-name run is ids `0x00..0x81` = **130**
names). **A pad-bound taker never gets the stretch**, because
the branch at `0x1456b065e` skips the whole scan for him. [b, all four constants and both branches
re-derived here]

**The delivery clock:**

```
0x1456b0837  call 0x14533eb20                  ; a global dword (the frame rate)
0x1456b084f  mulss xmm0,[0x1478504e8]          ; x 3.0   -> CPU
0x1456b0866  call 0x1442e0e80(ctrlTable, idx)  ; is this player bound to a hardware pad?
0x1456b087e  mulss xmm0,[0x145c36ac0]          ; x 7.0   -> human
0x1456b088b  cmp  esi,[rbp+0x78] ; ja <wait>
```

So a CPU corner is taken **3.0 s** after the clock starts and a human is given **7.0 s** before the
AI fires it for him. `0x1442e0e80` walks the 24-entry controller table for `entry+0x10 == idx`. [b]

**Nothing in the corner path reads an ability.** The corner target picker `0x1456aef20` (1,002 B,
four chunks) was scanned end to end for `0x1442dd5b0` / `0x1442bfa70` / `0x143ea8cb0` /
`0x143e31b10` / `0x143e31a10` / `0x1442e4c00` / `0x1442ee570`: **zero hits.** Delivery targets are
geometric — the per-player assignment table
`matchEnv+0x228d4 + idx*0xc8 + 0x1840 + (side*11+j)*8`, route state `0xb`, and the
human-control-allocation byte `+0x41f6`. "The wrong player attacks my corners" is a formation and
assignment-table problem, not a scoring one. [b]

---

## Free kicks, and THE WALL

### The delivery clock

Handler `0x1456b0ad0`, and it is the most elaborate of the six. Disassembled here:

```
0x1456b0c0c  xmm11 = [0x1478504e8] = 3.0 ; rdi = (int)(fps * 3.0)      ; the CPU base
0x1456b0c44  xmm15 = [0x145ab1b48] = 4.0
0x1456b0c3c  call 0x1442e0e80    ; pad-bound?
  pad-bound:      0x143e34040(playerRef) ?                              ; ball state in {0xa..0xd}
                    yes -> fps * 4.0
                    no  -> 0 > attackDir*ballX ? fps * 6.0 ([0x145ab244c]) : fps * 8.0 ([0x145b52fbc])
  not pad-bound:  0x143e34040(playerRef) ?
                    yes -> addss xmm0,xmm0 = fps * 2.0
                    no  -> keeps fps * 3.0
```

So a **CPU free kick is taken after 3.0 s**, or 2.0 s when the ball is in one of those four states;
a **human gets 6.0 or 8.0 s** depending on which end of the pitch the ball is, or 4.0 s in those
states. `0x143e34040` tests `dword[playerRef+0x58] ∈ {0xa, 0xb, 0xc, 0xd}`. [b, all five
multipliers resolved from PRISTINE here]

### The direct-shot ladder

Squared distance comes from `0x144304f90(matchEnv, (int)playerRef[0x1c])`
= `matchEnv+0x228e0` or `+0x228ec`, into `xmm9`. The thresholds are exact squares, and all four
cells were read back from PRISTINE for this write-up:

```
0x1456b0e7c  xmm6 = [0x145d8beb0] = 900.0   (30 m)   ; and: xor bl,bl  (knuckle flag cleared)
0x1456b0e86  comiss xmm9,xmm6 ; jbe -> SKIP the knuckle block entirely
0x1456b0ee1  xmm0 = [0x146b22a70] = 676.0   (26 m)   ; the curl window
0x1456b0f37  xmm0 = [0x146b3db1c] = 529.0   (23 m)
0x1456b0f59  xmm0 = [0x1466c54f0] = 1600.0  (40 m)
```

| distance | outcome |
|---|---|
| **d < 23 m** | SHOOT, unconditionally |
| **23–30 m** | SHOOT if the *position window* is open, **or** the curl flag is set |
| **30–40 m** | SHOOT only with the knuckle flag |
| **d ≥ 40 m** | never shot by this unit — the `1600.0` test at `0x1456b0f61` exits to the pass search with no escape |

**The knuckle branch is unreachable inside 23–30 m, and this is now confirmed rather than argued.**
`bl` is cleared at `0x1456b0e84` and the whole knuckle block is skipped by `comiss xmm9,xmm6 ;
jbe 0x1456b0edb` at `0x1456b0e86` whenever d² ≤ 900. So the `test bl,bl` at `0x1456b0f50` inside the
23–30 m arm is always false, and the 23–30 m condition is effectively **(window) OR (curl)**, with
26–30 m being the window alone. [b, re-derived here]

**The two technique flags:**

* **curl (`sil`)**, only within 26 m: card 7 (`0x143e31b10(holder, idx, 7)` at `0x1456b0eff`)
  **OR** effective Set Piece Taking `0x21` ≥ **0x55 = 85** (`0x1456b0f1a`) **OR** effective Curl
  `0x22` ≥ **0x50 = 80** (`0x1456b0f30`).
* **knuckle (`bl`)**, only beyond 30 m: level row `0x2a` must be **off** (`0x1442ee570` →
  `0x1442e4c00(team, 0x2a)`, `jne skip`), card 8 must be set (`0x1456b0eb7`), and
  `byte[…+4] < 0x28` (`0x1456b0ed1`).

**The record** gets `rec+8` = **3** (knuckle, `0x1456b1046`) / **1** (curl) / **0** (plain,
`0x1456b105f`).

**An ability floor is COMPUTED for the direct branch, separately from the ladder — but it is only
CONSULTED on one of two paths.** This is the brief's "read is not effective" trap and an earlier
draft of this chapter walked into it. Re-disassembled from a known boundary:

```
0x1456b0d9c  mov edx,0x21 ; call 0x1442bfa70
0x1456b0da9  xmm1 = [0x145b711c0] = 70.0 ; comiss xmm1,xmm0 ; jb .. else xmm0 = 0
0x1456b0dc5  comiss xmm0,[0x1469e6cf8] = 85.0 ; jb .. else xmm0 = xmm8 (1.0)
0x1456b0dd4  subss xmm0,xmm1(70.0) ; divss xmm0,[0x145c0b000] = 15.0
0x1456b0de0  mov rax,[r15+0x50] ; xor cl,cl ; movzx ebx,cl        ; bl = 0
0x1456b0ded  comiss xmm0,[rax]            ; t vs the difficulty parameter ctx[0x50][0]
0x1456b0df0  mov eax,1 ; cmova ebx,eax    ; bl = 1 iff t > difficulty
0x1456b0dff  call 0x1456747f0 ; cmp al,1 ; jne 0x1456b1075
0x1456b0e0c  mov rax,[r15+0x38]
0x1456b0e10  cmp byte ptr [rax+2],0
0x1456b0e14  je  0x1456b0e1e              ; <-- SKIPS the flag test entirely
0x1456b0e16  test bl,bl
0x1456b0e18  je  0x1456b1075              ; only HERE does the floor refuse
```

`t = clamp((SPT − 70)/15, 0, 1)` — **≤ 70 gives 0, ≥ 85 gives 1**, linear between — is compared
against `ctx[0x50][0]` at `0x1456b0ded`. **But the flag `bl` it produces is load-bearing only when
`byte[[r15+0x38]+2] != 0`.** When that byte is zero, `0x1456b0e14` jumps over `test bl,bl` and a
40-rated taker reaches the ladder exactly like a 99-rated one. **What that byte is was not
established** — § Open 18. So this is a **conditional** gate, not a hard floor, and any tuning built
on it inherits that condition. [b]

**The aim** is mirrored off the **opposing keeper's lateral position**. `edx = side^1`;
`eax = 0x1442de230(holder, edx)`; if `eax ≤ 0x15` then `X = 0x1442d6f60(holder, eax)` and
`v = dword[X+0x4fc]` (the same `+0x4fc` that `ActionMove::vf4` reads as the third component of a
player's position). The sign is flipped through `[0x147850560] = −1.0` and the sign mask
`[0x1478505f0]`, and the magnitude is `PARAM[8] × 0.5` for a knuckle strike (`0x147850248`) or
`× 0.85` otherwise (`0x1462bbed4`, verified 0.85). Written to `rec+0x10` at `0x1456b103b`. [b]

### The wall

Two tiny executors, both pure consumers, and both now decoded in a line each. **What is *not*
decoded is the object behind their gate** — see the `0x143e9e7b0` block at the end of this section,
where the earlier draft's "[b] the CPU wall is not locked out" is downgraded to an open question.

**`ActionWallPress`** (vftable `0x146bbeee8`) is `match::ai::ActionMove` with **three** slots
changed — slot 4, slot 12 and **slot 13**, which a probe missed:

| slot | base | `ActionWallPress` |
|---|---|---|
| 4 (destination) | `0x1442060f0` = `0x1442d6f60(match, idx)` then `+0x4f4/+0x4fc` — *my own position* | `0x144206020` = `0x144307180(0x1442d6c50(match+0x30))` then three floats — **the ball's position** |
| 12 (action id) | `0x144114300` = `mov eax,0x71` | `0x140eeb6d0` = `mov eax,2` |
| 13 (gait) | `0x14140d670` = `mov eax,3` | `0x14172cb30` = `mov eax,5` |

That is the entire class: **charge the ball, at gait 5.** It holds no line and contains no distance
constant. [b, both vf4 bodies disassembled here]

**`ActionWallJump`** is a **4-slot** class whose `vf2` (`0x144206010`, a two-instruction shim into
`0x144205c80`) is a **command relay, not a judgement**:

```
0x144205c9f  call 0x143e9e7b0(this+0x38, 0x32)      ; must return true
0x144205d00  r8d = playerIdx % 11                    ; the 0xba2e8ba3 / imul 0xb idiom
0x144205d2b  ecx = [teamAI + slot*4 + 0x8f4c]
0x144205d33  add ecx,-0x69 ; cmp ecx,1 ; ja -> return false   ; cell must be 0x69 or 0x6a
0x144205d3d  call 0x144206060(this)                  ; must return true
0x144205d46  mov dword[r13+0x8b8],0x69
             ... [r13+0x8bc] = 0x32 (jump) or 0x33 (don't)
```

`0x69 WALL_JUMP`, `0x6a WALL_NOT_JUMP`, `0x6b WALL_PRESS` are names from the action-name pointer
table at `0x148082f80` (its action-name run is ids `0x00..0x81`, **130** names; a *different* enum
starts at `0x82 = RL`). The `0x33` (don't jump) arm is taken when the cell says `0x6a`, or when
neither cursor player passes a timing test. **A full disassembly of `0x144205c80`'s chunks contains
no `ATTR_get`, no card test and no playstyle test: jump-versus-not is not ability-gated.** Bravery,
Jumping and Height play no part *at the executor*. [b]

**`0x143e9e7b0` is a table lookup plus a virtual call, not an inline pad test.** A probe flagged it
as a pad button read, which would mean the CPU wall never jumps. Disassembled here:

```
0x143e9e7b0: mov rbx,rcx ; add rcx,0xd30 ; call 0x143eee720 ; mov rcx,rax ; mov rdx,[rax] ;
             mov r8,[rdx+0x10] ; mov rdx,rbx ; jmp r8
```

and `0x143eee720(base, id)` is `cmp edx,0x71 / jge default / cmp qword[rcx + id*8 + 0x1b20],0 / je
default / mov rax,[rcx + id*8 + 0x1b20] / ret` — a **113-entry pointer table** (ids `0..0x70`) with a
fallback to entry 1. The caller then takes `[rax] → [rdx+0x10]` and tail-jumps: **slot 2** of
whatever object is registered there.

**What this settles, and what it does not. [b] for the shape; [c] for the identity.** The shape is
proven. *Whether the object it reaches consults pad state is not*, and three facts keep the probe's
worry alive rather than killing it:

* **The `+0x1b20` table's writer was not found**, so nothing in it has been identified.
* **The id namespace is NOT the action-name table.** Re-read here: `nameTable[0x32] = COVER` and
  `nameTable[0xb] = GOAL_NET_DODGE` — the ids `ActionWallJump` and `ActionSliding` pass. Neither is a
  plausible name for a wall jump or a sliding tackle, and the dispatch bound (113) does not match the
  action-name run (130). **So "action kind `0x32`" was the wrong gloss and is withdrawn**: the id
  belongs to an unidentified enum. (The one point *for* the executor reading: the fallback is entry
  **1**, and `nameTable[1] = BASE_POSITION`, the natural default action — suggestive, not proof.)
* **`match::pad::ThinkUnitFreekickWallJump` and `match::pad::ThinkUnitFreekickWallPress` exist in the
  image** — exactly the class of object a pad-side manager at `this+0xd30` would hold.

**So: the probe's worry is not confirmed, and not refuted either.** What *is* proven is that
`0x144205c80` itself reads no pad button and no ability. § Open 16. [b for the bytes, c for the
meaning]

**Where the wall stands is not in the wall executors.** Neither class holds a distance at all. The
9.15 m the *defending side as a whole* is pushed back to lives in the referee's standoff provider
(§ Referee placement). Whether the **wall specifically** is positioned by that same radius — the
flow task is named `EMatchFlowTask::FkWallSet` — was **not traced**, and neither was the writer of
the per-slot `0x69`/`0x6a` cells that decide who is in it. § Open 12.

---

## Throw-ins

Handler `0x1456b2160`. Two phases on the restart clock: for the first **`fps×3.0 + 0.5`** frames the
arm writes **answer class 8** (`0x1456b24cf`) — the `0x66 THROWIN_ROTATE` entry in the answer-class
table, which `ball-carrier-brain.md` lists as "GK path, not verified". **It is not a GK path.** It is
the outfield taker rotating on the touchline before the throw. After 3 s the same arm writes class 2
instead (`0x1456b24e3`). [b]

**The long throw is the only ability-driven receiver selection in the entire set-piece family.**
The arm tests card `0x13` (Long Throw) at `0x1456b22c9`; the receiver picker `0x1456af7f0`
(1,413 B, two chunks) tests it again and uses it to widen a range gate:

```
0x1456afa4c  movss xmm6,[0x145c8d614] = 35.0
0x1456afa5d  mov r8d,0x13 ; call 0x143e31b10        ; Long Throw card
0x1456afa6e  movss xmm6,[0x146b4eb00] = 45.5        ; on true
0x1456afa76  comiss xmm7,xmm6 ; jae <bail>
```

and then scores each candidate receiver as a sum of four normalised terms, each clamped between
`xmm8 = 70.0` and `xmm10 = 90.0` and divided by `xmm11 = 20.0` (the height term uses 175.0 and
190.0):

| call site | index | attribute (`attr_index_map.json`, all `proven`) |
|---|---|---|
| `0x1456afbe6` | `0x2d` | `JUMP` — **Jumping** |
| `0x1456afc1e` | `0x1e` | `INTERCEPT` — **Ball Winning** |
| `0x1456afc5a` | `0x29` | `BODY_BALANCE` — **Physical Contact** |
| `0x1456afc96` | `0x32` | **Height** (cm, range 132–220) |

The general throw-in picker `0x1456afd80` (714 B) reads nothing. [b, re-derived here]

---

## Kick-offs

Handler `0x1456b1f10` (582 B), cursor-gated, and the **default arm** for kind 0 and kinds ≥ 7 as
well as kind 1. Scanned end to end for every attribute, card, playstyle, level-row and difficulty
getter used elsewhere in this subsystem: **zero hits.**

**What it outputs** — added in the repair pass, because reporting only what is absent is not an
answer. Disassembled from PRISTINE:

```
0x1456b1f75  call 0x14533eb20 ; mulss xmm0,[0x147850248]=0.5 ; cvttss2si
0x1456b1f91  cmp eax,[r14+0x78] ; ja <exit>        ; a fps x 0.5 delivery clock
0x1456b1fd3  mov dword[rsi],3                      ; ANSWER CLASS 3
0x1456b1fde  mov dword[rsi+0x2c],3
0x1456b1ff4  xmm0 = [rbp + idx*4 + 0x25b64] ; addss [0x145b52b94]=180.0
0x1456b201b  call 0x144345ae0 ; movss [rsi+0x30],xmm0   ; a direction, wrapped into [0,360)
0x1456b20b0..0x1456b2127  nearest-eligible-team-mate scan over slots 0..10
0x1456b2133  cmp r14d,0x15 ; ja ; mov dword[r12],r14d   ; the chosen receiver index
```

So the kick-off arm writes **answer class 3**, a **facing angle** at `rec+0x30` (the taker's own
stored heading plus 180°, wrapped by the same 360° helper), and a **receiver index** chosen purely by
distance: the scan at `0x1456b20b0` walks the eleven-entry role list at `0x146c274c0` (values 0..10),
skips anyone whose control-allocation byte `+0x41f6` is 0, skips himself, requires route state `0xb`
(`0x14565f1d0`), and keeps the nearest inside `[0x145a8e378] = 10000.0`, starting from the sentinel
`0xff`. **Same geometric machinery as the corner picker, and no ability anywhere in it.** [b]

`ActionKickoff` is the one anomaly in the 7-slot kick contract: it is the **only class in all 34
with a slot-5 body** (`0x1441c4880`), and its slot 6 is the false stub `0x140c853c0`. So a kick-off
resolves its target in the pre-resolver and never reads a published decision. [b, `exe_map.json` +
`player-executors.md` § The two vtable contracts]

The kick-off standoff is `9.15 + 1.0 = 10.15 m` — see § Referee placement.

---

## Goal kicks

Handler `0x1456b1b80` (904 B, seven chunks), cursor-gated, **ability-free** (same seven-getter scan,
zero hits). The standoff provider returns **0.0** for kind 3: a goal kick has no retreat radius,
only the "outside the box" rule, which is enforced elsewhere.

**What it outputs** — added in the repair pass. Two answer classes, on two different tests:

```
0x1456b1bdd  cmp dword[rcx+0x58],0xc ; jne        ; ball state 0xc
0x1456b1be3  cmp byte[r12+0x334a],0  ; je
0x1456b1bf3  mulss xmm0,<fps scale> ; cmp [rdi+0x78],eax ; jbe
0x1456b1c09  mov dword[rsi],0xd                   ; ANSWER CLASS 0xd
0x1456b1c2a  cmp eax,5 ; ja      ; else a five-way sub-dispatch on [rdi+0x80]
0x1456b1e0e  cmp dword[r12+0x33e4],1 ; jne
0x1456b1e19  mov dword[rsi],0xc                   ; ANSWER CLASS 0xc
0x1456b1c4c/0x1456b1c89   [rdi+0x7c], [rdi+0x80]  ; sub-phase bookkeeping
0x1456b1da4/0x1456b1e89   mov dword[rsi+0x1c],edi ; the target slot
0x1456b1ebd  mov dword[rsi+0x1c],0xff             ; the no-target sentinel
0x1456b1ec8  mov dword[rsi+0x20],ebp              ; the type field
```

So the goal-kick arm writes **class `0xd`** on the early ball-state-`0xc` path and **class `0xc`**
on the late path when `matchEnv+0x33e4 == 1`, with a target slot at `rec+0x1c` (sentinel `0xff`) and
a type at `rec+0x20`. Those two classes are the `0xb`/`0xd` family the unit summary lists. The
sub-dispatch arms themselves were **not** followed to their targets. [b]

**And the CEREMONIAL goal kick is the one restart whose launch is not `Restart::vf8` — the goal kick
as such is not.** This is a correction to an earlier draft. Read out of `exe_map.json`:
`GoalKickLongPass::vf8` and `GoalKickShortPass::vf8` (both 30-slot) are the stub `0x140c83910`
(`ret 0`), **but `GoalKickStandby::vf8`, `SeamlessGoalKick::vf8` and `SeamlessGoalKickReady::vf8` are
all `0x143f05150`** — the dead-ball launcher. So a *seamless* goal kick does run `Restart::vf8`, and
it is only the two ceremonial long/short classes that get **neither** the open-play kick-error model
**nor** the dead-ball accuracy roll at slot 8. Where a *ceremonial* long goal kick is actually
launched was **not traced** — likely the `GoalKick` base or the keeper's own kick path. § Open 6.
[b for the stubs and for the three non-stubs; the alternative path is unfound]

The executor is `ActionGoalKickLong` (`+0x10f58`, 7-slot, slot 6 = `0x1441b3280`); the keeper's own
goal-kick behaviour, including the `gkcoaching_*_goalkick` animations, is § Penalties/keeper and
[goalkeeper.md](goalkeeper.md).

---

## Penalties — including the keeper's dive, and whether any of it is random

### The aim

`0x1456aecd0`, reached from the kind-6 arm at `0x1456b0440`. It picks **one of seven fixed points**:

```
0x1456aed05  call 0x1442d6fc0            ; = [[0x1486bd888]+0x790]
0x1456aed22  mov  ebx,[rbx]              ; the index word
0x1456aed2c  mov  eax,0x92492493 ; imul ebx ; add edx,ebx ; sar edx,2 ;
             imul eax,edx,7 ; sub ebx,eax      ; ebx = word % 7
0x1456aedb4  cmp  ebx,6 ; ja 0x1456aee07
0x1456aedc3  mov  ecx,[rdx+rax*4+0x56aeefc] ; add rcx,rdx ; jmp rcx
```

Constants, all resolved from PRISTINE here — `lateral = (goalHalfWidth − ballRadius) × 0.75`,
`mid = crossbar × 0.5`, `high = (crossbar − ballRadius) × 0.75`, `low = 0.130423`, with
`ballRadius = 0.1086859330534935` (`0x146af83dc`), `goalHalfWidth = 3.66` and `crossbar = 2.44`:

| idx | arm | height (m) | lateral (m) |
|---|---|---|---|
| **0** | `0x1456aee07` — **also the out-of-range default** | 1.748 | +2.663 |
| 1 | `0x1456aedcf` | 1.220 | +2.663 |
| 2 | `0x1456aedd4` | 0.130 | +2.663 |
| 3 | `0x1456aedde` | 1.220 | 0.000 |
| 4 | `0x1456aede6` | 1.748 | −2.663 |
| 5 | `0x1456aedf0` | 1.220 | −2.663 |
| 6 | `0x1456aedf9` | 0.130 | −2.663 |

Skill-card bits then nudge the point (`0x144309540` bits `0x10`/`0x18`/`0`/`8`, and `0x14430a760`).
`[rdi]` is set separately to `sign(ballX) × pitchDims+0x00` = ±52.56, the goal line. [b, table
entries and all five constants read from the image for this chapter]

### The delivery clock

Added in the repair pass so the § Tunables row has a derivation, matching the treatment corners and
free kicks get. In the kind-6 arm, immediately after the cursor gate:

```
0x1456b045b  call 0x14533eb20 ; cvtsi2ss ; 0x1456b0473 cvttss2si rsi,xmm0   ; rsi = fps x 1.0
0x1456b0482  call 0x1442e0e80(ctrlTable, idx) ; test al,al ; je 0x1456b04a7 ; pad-bound?
0x1456b048b  call 0x14533eb20 ; cvtsi2ss
0x1456b049a  mulss xmm0,[rip+0x401faa]  -> 0x145ab244c = 6.0 ; cvttss2si rsi,xmm0
0x1456b04a7  cmp esi,[r13+0x78] ; ja 0x1456b0575                            ; still waiting
```

So a **CPU penalty is taken 1.0 s** after the restart clock starts and a **human is given 6.0 s**
before the AI fires it for him — the same `0x1442e0e80` controller-table test the corner and
free-kick clocks use. [b, both sites and the cell re-derived here]

**Is the index random? Not answered — and the honest answer matters.** `0x1442d6fc0()` is
`[[0x1486bd888] + 0x790]`, which `registry-blackboard.md` § 8 identifies as **the cached
`URandomInfo` front buffer**, whose `+0x00` it documents as an **LCG seed word, not a tick counter**,
with **ten readers and NO WRITER FOUND ANYWHERE IN THE IMAGE**. § 8.1 of that chapter flags the same
no-writer negative on the sibling field `+0x08` and says plainly that if the fields are only ever
zeroed, the carrier's per-possession random is constant 0.0 all match. **The same risk applies here,
and its consequence is larger**: if `+0x00` is never written, `word % 7` is **0 every time** and the
CPU aims at the top corner on the taker's strong side, every penalty, all match. One live read of
`[*(g+0x790)]` settles it. § Open 1. [b for the expression; **c**, flagged as a risk, for what it
means in play]

### The power

`ActionPenaltyKick::vf6` = `0x144205ad0` (vftable `0x146bd4a08`, slot 6, unique to the class). It is
an **eleven-step ladder indexed by the match tick**, with no attribute and no RNG:

```
0x144205b9d  mov ecx,[r14+0x3318]                ; the match tick
0x144205ba7  mov eax,0xba2e8ba3 ; mul ecx ; shr edx,3 ; imul eax,edx,0xb ; sub ecx,eax  ; % 11
0x144205bc0  divss xmm0,[0x145a8dd7c] = 10.0
0x144205bc8  mulss xmm0,[0x147850248] = 0.5
0x144205bd0  addss xmm0,[0x145b2a690] = 0.4
0x144205bd8  movss [rbx+0xe7c],xmm0
```

`kickWork+0xe7c = 0.4 + 0.5 × ((tick % 11)/10)` → **0.40, 0.45, 0.50 … 0.90**. The same field is
written by `ActionShoot::vf6` with 0.2 / 0.5 / 1.0, so it is the shot-power scalar (the *name* is
[c]; the arithmetic is [b]). The aim defaults to the centre of the attacking goal line and is
overridden by the published aim from `0x1443395a0(playerIdx)` into `kickWork+0xea0/+0xea8`. [b,
re-derived here]

### The keeper's PRE-KICK STEP — and what is, and is not, known about the dive

**The pre-kick step is neither random nor a read of the kicker's aim. It is the keeper side's own
directional input.** That is proven below. **The dive/save itself is a different object
(`ActionKeeperPKSaving`) whose two bodies were NOT read** — it is RNG-free, but whether it is
direction-blind is open; see the end of this section and § Open 19.
`ActionKeeperMovePenaltyKick` (vftable `0x146be09a8`) overrides **exactly one slot of 23**
— slot 16, `0x14422ca70` — confirmed here by differencing the vtable against `match::ai::ActionMove`:

```
0x14422cb45  mov rcx,[rdi+0x20]           ; the action record's tagged command descriptor
0x14422cb49  call 0x144317ec0             ; unpack: first field = bits 0..8 of dword[rec+4]
0x14422cb4e  movss xmm0,[0x145b52b90] = 90.0
0x14422cb56  comiss xmm0,[rax] ; jbe -> -5.0 ([0x145b1d940]) else +5.0 ([0x145a8dd78])
0x14422cb6d  addss xmm0,[rbx+8]           ; the keeper's own z
0x14422cb77  xmm1 = [rsi+8] - [0x147850340]=1.5     ; = 3.66 - 1.5 = 2.160
0x14422cb8e/9a  clamp dest.z to +/- 2.160
```

Four things follow, and the first three are [b]:

1. **`rec+0x20` is the player's own tagged command record** — the same `rec+0x20` that
   `player-executors.md`'s generic slot-4 resolver `0x145625a20` decodes through `0x144318200`. It is
   indexed by the *keeper's* player index, not the kicker's.
2. **The 9-bit field is DEGREES.** The packer family `0x144318660`/`700`/`820`/`8f0`/`990` writes it
   as `cvttss2si eax,xmm2 / cmp eax,0x168 / wrap via 0x144345ae0 / and eax,0x1ff` — `0x168` = 360.
   `goalkeeper.md` § 7 currently calls the units "unproven".
3. **The step is ±2.160 m, not ±5.0 m.** The ±5.0 request is always saturated by the clamp against
   `pitchDims+0x08 = 3.66` minus 1.5. Meanwhile the CPU aims **2.663 m** from centre — so a keeper
   standing at his limit is still half a metre short laterally, before he has moved.
4. **The CPU keeper probably takes no pre-kick step at all**, because there is no CPU-side writer of
   a command record anywhere in the image (see § Negatives), and `ActionKeeperMovePenaltyKick`
   overrides **no vf4**, so when `vf16` refuses, the destination falls back to `ActionMove::vf4` =
   *the keeper's own current position*. He stands still. This is **[c]** — structurally strong,
   not proven, because it needs one live read.

**The save that follows: what is actually established.** An earlier draft said `ActionKeeperPKSaving`
is "a deterministic trajectory intercept … which has no left/right branch", with no evidence label
and against its own `gate-only` status row. Corrected here:

* Slot 4 is `0x14422d4d0`, and it holds **no geometry**. Disassembled in full (one chunk,
  `0x14422d4d0..0x14422d563`): it reads `byte[rcx+0x20]`, calls `0x145625a20`, calls `0x144318200`
  and tests `cmp eax,3`, calls `0x14421d350`, then `call 0x14422d570` and returns. It is a **gate
  that delegates**. [b]
* The worker is **`0x14422d570`**, four chained-unwind chunks `0x14422d570..0x14422dacc`, and **its
  body was not read**. [b for the extent]
* Slot 6 is `0x14422cc00`, which is a five-byte `jmp 0x14422cc10` thunk into a real 2,239-byte body
  (`0x14422cc10..0x14422d4cf`). **That body was not read either.** [b for the thunk and the extent]
* **Zero RNG**, on direct edges *and* under a full transitive closure over chained-unwind chunks:
  slot 4 closes at 41 functions, slot 6's body at 22, both with the frontier exhausted and no edge to
  `0x144345d90`/`e00`/`e50`/`eb0`, `0x1443461a0` or `0x143ea9260`. [b]
* **But "no left/right branch" is NOT established.** Both unread bodies call the **360° angle wrap**
  `0x144345ae0` — the worker at `0x14422d9c9`, the slot-6 body at `0x14422cc7b` — i.e. each of them
  handles a *direction*, which is precisely what that phrase denies.

So: the save is **not random** [b]; whether it is **direction-blind** is **unproven** [c], and the
two bodies that would settle it are named above. § Open 19. [b for 1–3 of the dive list, c for 4]

### Both controls, shown

**Scope, stated once and applied to every row: this is a TRANSITIVE CLOSURE**, not a depth-1 scan.
Each root is expanded over its chained-unwind chunks (`func_chunks`, never `func_range`), every
direct `call`/`jmp` rel32 target is resolved to its own function root, and the frontier is followed
to exhaustion. Targets: `0x144345d90`, `0x144345e00`, `0x144345e50`, `0x144345eb0`, `0x1443461a0`,
and the `RandInt` wrapper `0x143ea9260`. **Virtual dispatch is invisible to it** — a vtable slot
reached only indirectly is not followed — and in a subsystem built on vtable slots that is a real
hole, so the zeros below mean "no RNG on any *statically resolvable* edge", not "no RNG under any
execution". The `RNG` column counts draws; **the `360° wrap` column counts calls to `0x144345ae0`,
which is `fmodf`-into-`[0,360)` and NOT a draw** — it is shown separately precisely so it is never
counted as one again.

| root | what it is | RNG calls | 360° wrap | ATTR reads |
|---|---|---|---|---|
| `0x1456b0060` | `ThinkUnitSetPlay::vf2` (66 fns) | **0** | 18 | 0 |
| `0x1456aecd0` | CPU penalty aim (1 fn) | **0** | 0 | 0 |
| `0x144205ad0` | `ActionPenaltyKick::vf6` (3 fns) | **0** | 0 | 0 |
| `0x14422ca70` | keeper penalty stance (5 fns) | **0** | 0 | 0 |
| `0x144205c80` | `ActionWallJump::vf2` (3 fns) | **0** | 0 | 0 |
| `0x143d861f0` | foul level fn (2 fns) | **0** | 0 | 0 |
| `0x143d86c90` | foul decision fn (39 fns) | **0** | 5 (3 of them direct: `0x143d8763d`, `…7877`, `…7918`) | 0 |
| `0x143c685a0` / `0x143c4f5f0` | positionPK reader / applier (6 / 7 fns) | **0** | 0 | 0 |
| `0x14422d4d0` / `0x14422cc10` | `ActionKeeperPKSaving` slot 4 / slot 6 body (41 / 22 fns) | **0** | 12 / 7 | 0 |
| **`0x143f05150`** | **`Restart::vf8`** (41 fns, includes the solver) | **1 `RandInt`** direct (`0x143f05682`) **+ 9 in the solver = 10 draws** | 8 | **1 × `0x21`** (`0x143f053ff`) |
| **`0x143f05730`** | **the restart launch solver** | **6 `RandInt` + 3 Gaussian** | 4 (`0x143f05f07`, `…5f3d`, `…5f59`, `…5f86`) | **1 × `0x21`** (`0x143f058a3`) |

*Positive control:* the open-play kick builder `0x14401a900` closes at **75 functions with 10 RNG
edges** (`0x143ed9440`, `…9479`, `…94df`, `0x143eda033`, `…a332`, `0x143eafd44`, `0x143eadb2b`,
`…db65`, `…db98`, and `0x143ea9274` inside `RandInt` itself) — so the graph is **not** merged and the
walk really does traverse. `ActionShoot::vf6` (`0x1441b4f60`) — which sits **beside
`ActionPenaltyKick` in the same executor parent** — reaches the LCG with twelve draws of its own
(`player-executors.md` § The input census). *Negative control:* `ChanceSpaceRun::vf5` `0x143df5950`
closes at **91 functions with zero RNG, frontier exhausted rather than truncated**. Both controls
fire, in opposite directions, so the zeros above are real zeros **within the stated scope**. No root
in the table truncated. [a for the emulated curve, b for the census]

**So: "the CPU got lucky with that penalty" is false, and "set pieces have no randomness" is also
false.** The decision is a table, a modulo or a threshold everywhere, on every statically resolvable
edge. The *strike* is stochastic — ten draws per launch, of which **one** is ability-weighted, and
that one only on the near-post path.

---

## The `positionPK_*` dt270 objects — LOCATED, and live

The plan lists these as `UNLOCATED` in `build/dt270_liveness.json` (0 get-sites, 33 unknown-index
sites). **They are located.** They were invisible to the liveness sweep because they are fetched
**by name**, not by a constant index — and the sweep **said so itself**: its note on every one of
these records reads *"UNLOCATED: no constant-idx get() site and no other pointer source was found -
the idx is computed at runtime (or the object is never fetched). Fields are 'unlocated', which says
NOTHING about liveness."* The tool was not wrong and did not need correcting; what follows is the
path it could not see.

The path, re-derived here:

```
0x143c4c3ff  cmp dword[r15+0x34a0],6        ; PENALTY_KICK only
0x143c4c435  movzx r9d,byte[rax+0x7bc8]
0x143c4c43d  lea r8,[0x146af4ca0]           ; the literal "positionPK_%d"  (read: b'positionPK_%d\x00')
0x143c4c444  mov edx,0x80 ; lea rcx,[rsp+0x50] ; call 0x14112dbf0    ; sprintf_s
0x143c4c458  call 0x1453494e0               ; name -> dt270 index
0x143c4c4d1  call 0x143c684a0               ; match::situation::Loader, index stored at Loader+0x6ee0
```

and the reader `0x143c685a0`, disassembled in full here:

```
0x143c685d2  mov edx,[rsi+0x6ee0] ; call 0x145349560        ; the dt270 get wrapper
0x143c685e4  lea rbx,[rax+0xc]
0x143c685fa  cmp byte[rbx-4],1                              ; enable
0x143c68600  xmm0=[rbx+4] (X) ; xmm1=[rbx+8] (Z)
0x143c68610  mov dword[rsp+0x3c],0                          ; Y forced to 0
0x143c68623  movzx ecx,byte[rbx]                            ; playerNo
0x143c68626  ... % 22 ...                                   ; wrapped, not trusted
0x143c68637  imul rcx,rax,0x504 ; sub rcx,-0x80 ; add rcx,rsi
0x143c68650  call 0x144f8307a                               ; memcpy 0x504 bytes
0x143c68657  add rbx,0x10 ; cmp edi,0x16 ; jb               ; 22 entries, stride 16
```

The applier `0x143c4f5f0` reads those records back and multiplies each component by the side sign
`byte[team+0x28c]`, so **the stored coordinates are in a canonical attacking direction and are
mirrored per side**. Both run inside `match::Match::vf1` as the `PositionWarp` sub-state chain
(task ids `0x69 → 0x6a → 0x6b → 0x6c` on `match+8`). [b]

**The schema is `playerData[22]` of `{int enable, int playerNo, float startPosX, float startPosZ}`,
struct 360 bytes** — `n_fields 4` with `dims {stride 16, count 22}` in `build/dt270_liveness.json`,
indices 112–116. The brief's "~20 fields" and a probe's "~4 fields" are both the wrong shape: there
are **88 editable values per object**.

**`_N` is the number of defenders.** `byte[+0x7bc8]` is written at `0x143d030e9` as the first of four
line-group counters built by the loop `0x143d03030..0x143d0310a`: eleven formation slots are read
from the tactics table by `0x1442c0640`, position id 0 (GK) is skipped, ids 1..12 are mapped through
a 12-entry jump table at `0x143d03680` into line ids `{1,3,6,9}` and counted into four buckets;
bucket 0 is the first line group. That `_2.._5` and nothing else exists is exactly what a back
two-to-five predicts. [b for the structure; the id→name binding (1,2,3 = CB/LB/RB) is **c**]

**The values, read from `dt270_console_all.PRISTINE.cpk` for this chapter.** Goal line is 52.56,
the penalty-area line 36.14, the spot 41.56.

| slot | `_2` | `_3` | `_4` | `_5` | reading |
|---|---|---|---|---|---|
| 0 | (−32.22, −0.38) | same | same | same | the **attacking** keeper, in his own half |
| 1–5 | (3.29, 6.34) … (31.15, −6.43) | **all five differ** | **all five differ** | **all five differ** | the bodies that move between variants |
| 6–8 | (31.62, 3.35) … (30.05, 0.47) | same as `_2` | **differ** | **differ** | |
| 9, 10, 12–19 | X 32.30–35.85, \|Z\| ≤ 13.20 | identical | identical | identical | the **ring on the edge of the box** |
| 11 | (51.75, −0.02) | same | same | same | the **defending keeper on his line** |
| 20, 21 | (23.76, −7.09), (17.09, 1.21) | same | same | `_4` moves 21 | |

`_3` differs from `_2` in rows 1–5; `_4` in rows 1–8 and 21; `_5` in rows 1–8. The count of rows
with |X| < 25 — i.e. players kept away from the box — rises **6 / 7 / 7 / 8** from `_2` to `_5`,
which is what "more defenders means more bodies held upfield" looks like. [a, values read from the
PRISTINE pack]

**`positionNone` is dead.** All 22 rows have `enable = 0` and X = Z = 0.0, and the only producer of
a `positionPK` object name in the image is the `"positionPK_%d"` `sprintf`, which cannot emit the
string. Its two occurrences in the image are a dt270 registration-table entry (`0x1475d18a0`) and a
`DevelopData` path literal; neither is a code reference. Do not spend time on it. [b]

---

## Referee placement, and the 9.15 m

### The pitch-dimension table

Fully decoded from its initialiser `0x1442ec6d0`, every value an **inline `mov imm32`** and every
one read back here:

| off | value | meaning | | off | value | meaning |
|---|---|---|---|---|---|---|
| `+0x00` | 52.56 | half length | | `+0x20` | **41.56** | **the penalty spot** (52.56 − 11.0) |
| `+0x04` | 34.06 | half width | | `+0x24` | 2.5 | |
| `+0x08` | **3.66** | goal half-width | | `+0x28`/`+0x2c` | 1.10938 / 2.33984 | |
| `+0x0c` | **2.44** | crossbar | | `+0x30`/`+0x34`/`+0x38` | 51.17 / 54.32 / 54.43 | |
| `+0x10`/`+0x14` | 47.06 / 9.16 | six-yard box | | `+0x3c`/`+0x40` | 0.12 / 0.12 | |
| `+0x18`/`+0x1c` | 36.14 / 20.12 | penalty area | | **`+0x44`** | **9.15** (`0x1442ec757`) | see below |
| | | | | `+0x48`/`+0x4c` | 1000 / 1000 | per-mille scales |

Cross-checks: 52.56 − 11.0 = 41.56; 52.56 − 16.5 + 0.08 = 36.14. `0x1442ec760` is the scale getter
`min(lenScale, widthScale)/1000`. [b]

### The standoff, and the correction that matters

The provider is `0x143d48bc0(match, UMatchInfo, player)`, disassembled in full here:

| `+0x34a0` | radius |
|---|---|
| 1 (kick-off) | 9.15 × scale **+ 1.0** = 10.15 |
| 2 (throw-in) | **6.0** (`0x145ab244c`), returned immediately, no scale, no +1 |
| 3 (goal kick) | **0.0** |
| 4 (corner) | 9.15 × scale |
| 5 (free kick) | 9.15 × scale, or 6.0 on `byte[player+0x28d]` |
| 6 (penalty) | 9.15 × scale **+ 1.0** = 10.15 |
| anything else | 0.0 |

**And the 9.15 it uses is `movss xmm6,[rip+0x2dcf543]` at `0x143d48c25` → pool cell `0x146b18170`,
value 9.149999618530273, refcount 6.** It is **not** `pitchDims+0x44`. A probe nominated the inline
immediate at `0x1442ec757` as "the cleanest lever in this chapter — one private instruction, one
site … it feeds every restart standoff through `0x143d48bc0`". **It does not.** `pitchDims+0x44` has
one consumer I could find — `movss xmm0,[rbx+0x44]` at `0x1443237f9` inside the pitch-zone classifier
`0x1443236e0`, feeding **bit 14** (the centre circle). Editing `0x1442ec757` would move the
centre-circle zone test and leave the wall exactly where it is. **Two independent copies of 9.15
exist in this game and they do different jobs.** [b, both sites disassembled here]

The enforcer is `0x143d48cb0`, whose single caller `0x14414f23c` sits in the `match::player` band, so
it runs **per player per frame**. It subtracts **3.0** (`0x145da91c8`, refcount 137) from the radius
for the designated taker in state 2, **exempts the two cursor players outright** (`UMatchInfo+0x41d8`
and `+0x41dc`), exempts anyone standing inside a penalty area (`bt eax,0xa` at `0x143d48d74` — note
this is bit **10**, the *other* box bit from the one the foul path uses), and otherwise calls the
push-out `0x143d48e90`. [b]

### Ball placement — NOT LOCATED

The penalty spot exists as a named constant (`pitchDims+0x20` = 41.56) and has a consumer at
`0x143db2aec` inside `0x143db2970` that combines it with the side sign. **The instruction that
actually writes the ball onto a restart spot was not isolated.** Do not assume it is in the referee
band — `0x143c4f5f0`, the positionPK applier, writes only players. [honest negative]

---

## Seamless versus ceremonial restarts

The UE reflection tables name the whole flow: `EMatchFlowTask` = `SetplayStart`, `MemberChange`,
**`FkWallSet`**, `WaitQuick`, `SetplayWhistle`, `WaitInplay`, `Inplay`, plus `PositionWarp`,
`MoveCheck`, and `SeamlessThrowin` / `SeamlessCornerKick` / `SeamlessGoalKick` as separate tasks
alongside `EPesGameState::SeamlessDemo`.

The exe-side gate is **`0x1442e0180(match)`**:

```
UMatchInfo+0x3308 == 3
AND byte[UMatchInfo+0x3333] != 0
AND ( an online/mode object accepts early
      OR ( (UMatchInfo+0x41d0 - 1) > 2
           AND !0x1442c8090(...)
           AND UMatchInfo+0x34c0 != 0 AND != 0xb
           AND if +0x34c0 == 6 then UMatchInfo+0x3304 not in {0,2,4,6} ) )
```

`ThinkUnitAutoRestart::vf17` (`0x1440e50f0`) adds `0x1442dd680(match) <= 1` (which reads
`UMatchInfo+0x332c`) and logical button `0x51`, then emits command id **`0x3a`** for kinds 1/2/5,
**`0x38`** for 3/4 and **`0x42`** for 6 — **yes, there is a quick restart for a penalty.** [b]

Two dead things here:

* **`ThinkUnitBlockTestAutoRestart::vf17` (`0x1440e5200`) is `xor al,al; ret`.** The unit is inert
  despite its `vf12` (`0x1440e2070`) faithfully returning command id `0x3d`, which can never be
  emitted. Do not build on it.
* **A dead read inside `ThinkUnitAutoRestart::vf17`**: `esi = 0x1442c3f80()` (a config × 20) at
  `0x1440e511d` is unconditionally overwritten at `0x1440e5138` by `0x1442dd680(match)`, because the
  predicate that lets control reach the first call is the same one that forces the override. This is
  the brief's "read is not effective" trap, live. [b]

So pushing the game toward quick restarts means relaxing `cmp esi,1` at `0x1440e513a` or the
`+0x34c0`/`+0x3304` exclusions in `0x1442e0180` — not touching animations. **Unverified in game:**
what `+0x332c` counts was not established, so treat that as a lead. [c]

### Advantage is modelled, and it is not a subsystem

`EMatchFlowTask::DemoAdvantageFoulTrans` and `EMatchFlowTask::ReplayAdvantageYellow` are real flow
tasks; the referee has `referee_advantage_1_1_jog`, `judge_advantage_1` and `judge_advantage_3`; the
commentary API exposes `CheckAdvantageData` and `AdvantageVariousData`. In code it is the block at
`0x143d88643..0x143d889e3` **inside the foul decision function** — after the level has been computed,
it walks recent offence-event records (`0x1442eaba0`), resolves each event's pass receiver
(`0x1442df5d0`), and accepts or rejects on time windows scaled by 0.06 / 0.05 / 0.2 from a global
config, plus a 135.0 speed test and a 30.0 angle test, writing the threshold band
(`0x28` / `0x50` / `0x6e`) to `referee+0xd48`. **That this block is advantage is [c]** — its
position, its shape and the flow-task names all agree, but nothing in it is labelled.

---

## Restart animation timings, in seconds

From `AnimationData.bin` / `CancelData.bin` with the exe's own record rules (36-byte animation
records, `end_frame = (packed & 0x1FFF) × 2`, `id = packed >> 13`; 12-byte cancel records,
`id = packed & 0x1FFF`, `frame = (((packed>>13) & 0x3FF) + 2) × 2`), joined to the 7,883-entry name
index, at **1/60 s**. Re-run for this chapter via `tools/setpiece_anime_timing.py`.

| motion | length | first cancel key | committed for |
|---|---|---|---|
| `fk_runup` | 1.767 s | 1.400 s | 1.400 s |
| `fk_runup_beckham` | 1.300 s | 0.933 s | 0.933 s |
| `fk_runup_robecal` (Roberto Carlos) | 3.333 s | 2.967 s | 2.967 s |
| `fk_runup_pass` | 1.700 s | 1.333 s | 1.333 s |
| `Freekick_stepback_0_2` | 3.000 s | 0.533 s (then 1.067 / 1.633 / 2.333) | 0.533 s |
| `fk_idle` / `fk_idle2` | 4.933 / 9.133 s | **none** | the whole clip |
| `pk_runup` | 4.367 s | 4.000 s | 4.000 s |
| `pk_runup_dummy_8` (shortest) | 2.600 s | 2.300 s | 2.300 s |
| `pk_runup_pogba` (longest) | 4.567 s | 4.200 s | 4.200 s |
| `pk_idle*` (all 10, incl. signature) | 1.267–9.133 s | **none** | the whole clip |
| `wall_runup` | 1.000 s | 0.567 s | 0.567 s |
| `wall_jump_high` … `high4` | 1.167 s each | 1.000 / 1.100 / 1.033 / 1.033 s | ≈1.0–1.1 s of 1.167 s |
| `wall_idle` / `_idle2` / `_idle3` | 5.500 / 5.967 / 5.233 s | **none** | the whole clip |
| `Throwin_BallCatchToSetup_*` (11 clips) | 1.000–1.800 s | **none** | the whole clip |
| `throwin_pickupball_180` | 1.033 s | 1.033 s | the whole clip in practice |
| `quick_restart0` … `quick_restart315` (8) | 1.267–2.067 s | 0.967–1.300 s | ≈1 s |
| `quick_restart_step*` (9) | 0.400–1.300 s | **none** | the whole clip |
| `kickoff_kicker_pass` | 1.100 s | 0.867 s | 0.867 s |
| `kickoff_loop_*` (12) | 1.067–13.233 s | **none** | the whole clip |
| `gkgoalkick_inside_0_0_000` | 4.367 s | 2.533 s | 2.533 s |
| `assistant_flag_up_0_flag_ck` (the linesman's corner flag) | 3.800 s | 3.600 s | 3.600 s |

**Reading:** a free-kick taker is locked for ~1.4 s once the run-up starts and a penalty taker for
~4 s; a wall jumper is committed for ~1.0 s of a 1.167 s clip; **a throw-in taker cannot be
interrupted at all** once the set-up clip begins, and neither can a quick-restart *step*. [b]

---

## THE ANTI-PENALTY BIAS

**This is the most targeted realism lever found anywhere in this project, it is two mechanisms in two
places, and NOTHING BELOW WAS APPLIED.** The installed image is byte-identical to PRISTINE
(SHA-1 verified above), so everything here is stock today. `match-ai-decoded.md`'s parenthetical
"(ours: 36 outside)" is **stale** — nothing is patched at that site.

### Mechanism 1 — the severity threshold is raised inside the box

`0x143d861f0`, the foul level function. Tail, disassembled from PRISTINE for this chapter:

```
0x143d86296  call 0x1443236e0              ; the pitch-zone classifier
0x143d8629b  bt   eax,0xb                  ; bit 11 = "in a penalty area"
0x143d8629f  mov  ecx,0x28                 ; 40
0x143d862a4  mov  eax,0x3c                 ; 60
0x143d862a9  cmovae eax,ecx                ; CF==0 (bit clear) -> 40 ; set -> 60
0x143d862ac  cmp  al,sil ; jbe .. else return 0
```

`jbe` taken means threshold ≤ severity, so **severity must reach the threshold for a foul to exist
at all**. Inside the box that bar is **60**; outside it is **40**. Below 80 the level is 1 or 2 split
at `thr + (80 − thr)/2`; 80–109 is level 3 (yellow, `cmp sil,0x50` at `0x143d862b5`); ≥110 is level 4
(red, `cmp sil,0x6e` at `0x143d862d6`). Severity itself is the sum of `0x143d86300 + 0x143d86ab0 +
0x143d86580`, stored as a float at `referee+0xac`.

The classifier `0x1443236e0` emits **two** penalty-area bits — bit **10** for the end where
`side × x ≤ 0` and bit **11** for the other, selected by `cmovbe` at `0x1443237c8..0x1443237cc`.
**The foul path tests only bit 11**; the standoff enforcer tests only bit 10.

### Mechanism 2 — the ball-contest veto is lowered inside the box

`0x143d86c90`, the foul decision function, immediately after the level is computed:

```
0x143d87494  call 0x143d861f0              ; -> r15d = the level
0x143d8749c  cmp  byte[rsp+0x51],r12b ; je 0x143d8758f     ; the whole veto is skipped unless this flag is set
0x143d874a7  movss xmm6,[rip+0x1e36d51]    ; -> 0x145bbe200 = 0.7
0x143d874af  test dil,dil ; je 0x143d874c5 ; dil = the in-box flag (bt ebx,0xb, OR byte[player+0x28d8]==2)
0x143d874b4  call 0x144301a90              ; = movzx eax, byte[rcx+0x4a8] ; ret
0x143d874bf  jne  0x143d874c5              ; a non-zero +0x4a8 KEEPS 0.7 even in the box
0x143d874c1  movaps xmm6,xmm8              ; 41 0f 28 f0 -- FOUR bytes, not three (REX.B for xmm8)
                                           ; xmm8 loaded at 0x143d86ffe from 0x145b2a690 = 0.4
0x143d874c5  comiss xmm6,xmm9 ; jbe 0x143d87587   ; 41 0f 2f f1, also 4 -> level 0 = NO FOUL
```

`xmm9` is `float[referee+0xb4]`, the ball-contest score, produced either by copying
`[playerB+0x29f0]` or, on the recompute path, by the geometric scorer `0x1442f55c0`. **A foul stands
only if the tackler's contest score is BELOW the threshold — 0.7 outside the box, 0.4 inside.**
Inside the box the bar is lower, so more contests are excused.

### The four sites, with sharer counts from `build/exe_constant_census.json`

| # | what | stock | site | route | sharers | what a change does |
|---|---|---|---|---|---|---|
| 1 | in-box severity threshold | **60** | `mov eax,0x3c` at `0x143d862a4` | exe code, **private inline immediate**, one instruction | — | setting it to `0x28` judges a challenge in the box on the same scale as one outside. **The single most targeted "more penalties" edit in the game, and it is one byte** |
| 2 | out-of-box severity threshold | **40** | `mov ecx,0x28` at `0x143d8629f` | exe code, **private inline immediate** | — | lowering it turns marginal contact into free kicks everywhere. It also moves the level-1/2 split, which is `thr + (80−thr)/2` |
| 3 | in-box contest veto | **0.4** | value reaches `xmm8` from `movss xmm8,[rip]` at `0x143d86ffe` (cell `0x145b2a690`); moved into `xmm6` by the **4-byte** `movaps xmm6,xmm8` at `0x143d874c1` (`41 0f 28 f0` — addressing `xmm8` costs a REX.B prefix) | exe code — **needs a cave** | cell 0.4f: **623** referrers; its neighbour 0.8f at `0x145b2a694`: 622 | making it equal to 0.7 removes the in-box discount. **Do not re-aim `0x143d86ffe`**: the same `xmm8` is reused by an unrelated flag block at `0x143d871d8`/`0x143d8723c`. **Cave arithmetic, spelled out** (an earlier draft said 3 bytes and the follow-on sizing was wrong): a `jmp rel32` is 5 bytes and fits in neither 3 nor 4, so the detour must consume `0x143d874c1..0x143d874c8` — the 4-byte `movaps` **plus** the 4-byte `comiss xmm6,xmm9` at `0x143d874c5` (`41 0f 2f f1`) — as `jmp rel32` + 3 bytes of padding. The cave loads the replacement threshold from a private cell into `xmm6`, **re-executes `comiss xmm6,xmm9`**, and returns to `0x143d874c9`, the `jbe` |
| 4 | out-of-box contest veto | **0.7** | the disp32 of `movss xmm6,[rip+0x1e36d51]` at `0x143d874a7` → cell `0x145bbe200` | exe code — **re-aim the disp32, never write the cell** | **461** referrers | raising it toward 1.0 makes almost any contact a foul regardless of how much ball was won |

Two more, same function, same policy:

| card thresholds | stock | site | sharers |
|---|---|---|---|
| yellow | **80** | `cmp sil,0x50` at `0x143d862b5` **and** `mov ecx,0x50` at `0x143d862bb` — **both must move together**, the second is the level-1/2 split point | private inline |
| red | **110** | `cmp sil,0x6e` at `0x143d862d6` | private inline |

**All six bytes verified identical in PRISTINE, INSTALLED and STOCK. None of them was changed.**
The two threshold edits (#1, #2) are the cheapest and safest in this chapter; the two veto edits
(#3, #4) are the ones that actually decide how many contests survive, and #3 is the only one here
that cannot be done without a cave.

**Caveat worth carrying into any experiment:** `byte[player+0x4a8]` (read by the two-instruction leaf
`0x144301a90`) cancels the in-box downgrade when non-zero, and its meaning is **not established** —
so mechanism 2's strength in play depends on a field nobody has identified. § Open 7.

---

## The input census

| input | reaches set pieces? | where |
|---|---|---|
| **attributes — the delivery decision** | **`0x21 PLACE_KICKING` (Set Piece Taking)** and **`0x22 BALL_SPIN_CONTROL` (Curl)**, both **only in the FREE_KICK arm** `0x1456b0ad0`. **One of the three is a CONDITIONAL gate, not a gate** — see the note below the table | `0x1456b0d9c` (the `70→85` floor, via `0x1442bfa70` — **compared at `0x1456b0ded` but only enforced when `byte[[r15+0x38]+2] != 0`, `0x1456b0e10`**), `0x1456b0f15` (`≥85`), `0x1456b0f2b` (`≥80`), both via `0x1442dd5b0` |
| **attributes — the receiver choice** | **exactly one picker**: the long throw `0x1456af7f0` reads `0x2d` Jumping, `0x1e` Ball Winning, `0x29` Physical Contact, `0x32` Height | `0x1456afbe6`, `0x1456afc1e`, `0x1456afc5a`, `0x1456afc96`, all `0x1442bfa70` |
| **attributes — the strike** | **`0x21` twice, in the animation layer**: `Restart::vf8` `0x143f053ff` and the solver `0x143f058a3`, both `0x143ea8cb0`. **The `Restart::vf8` read only reaches an outcome on the class-2 near-post path** (`0x143f05575`–`0x143f0557c`), inside the `player+0xad0 ∈ {0x26,0x2c}` loop | as listed |
| **attributes — the long free kick** | **`0x35 STRONGER_FOOT` ×3.** `ActionFreeKickLong::slot6` **is the same body as `ActionLongPass::slot6`** (`0x1441b1500`), and `player-executors.md` proves the reads are *used*, not discarded (`0x1441b1ed9 test al,al ; je` then `0x1441b1ee5 xorps xmm0,xmm13` — a sign flip on an emitted float) | `0x1441b1ed4`, `0x1441b210f`, `0x1441b21a6` |
| **attributes — anywhere else** | **none.** `0x1456aef20` (corner target), `0x1456af310` / `0x1456af5f0` (free-kick pickers), `0x1456aecd0` (PK aim), `0x1456afd80` (throw-in picker), `0x1456b1b80` (goal kick), `0x1456b1f10` (kick-off), `0x144205c80` (wall jump), `0x14422ca70` (keeper PK stance), `0x143d861f0` / `0x143d86c90` (the referee), `0x143c685a0` / `0x143c4f5f0` (positionPK): all scanned end to end for `0x1442dd5b0` / `0x1442bfa70` / `0x143ea8cb0` / `0x143e31b10` / `0x143e31a10` / `0x1442e4c00` / `0x1442ee570` — **zero hits in all twelve** | — |
| **skill cards** | **card 7** (free-kick curl) at `0x1456b0eff`; **card 8** (knuckle) at `0x1456b0eb7`; **card `0x13` Long Throw** at `0x1456b22c9` and `0x1456afa5d`; and the PK-aim nudges via `0x144309540` / `0x14430a760`. That is the complete list | as listed |
| **level / difficulty rows** | **row `0x2a`** gates the knuckle branch (`0x1442ee570` → `0x1442e4c00(team, 0x2a)`, `0x1456b0e99`); the free-kick ability floor compares against `ctx[0x50][0]`, a difficulty parameter — **but see the conditional note below** | as listed |
| **playing styles** | **zero sites** in every function listed above | — |
| **dt270** | **`positionPK_{2,3,4,5}`, by name** — indices 112–116, fetched through `0x1453494e0` from a runtime `sprintf`, read at `0x143c685a0`. No other dt270 object was found on a set-piece path | § positionPK |
| **RNG** | **zero** on the decision side, under a **transitive closure** with the frontier exhausted and both controls firing (virtual dispatch out of scope); **ten draws** on the launch side — 1 `RandInt` in `0x143f05150` plus 6 `RandInt` + 3 Gaussian in `0x143f05730`. The seven calls to `0x144345ae0` on these two roots are the **360° angle wrap, not draws** | § Penalties, both controls |
| **team / runtime fields** | `teamAI+0x8f4c+slot*4` (the wall command cells, `0x144205d2b`); `UMatchInfo+0x41d8`/`+0x41dc` (cursor players, the taker check and the standoff exemption); `UMatchInfo+0x34a0` (restart kind), `+0x34c0` (restart cause), `+0x3304`, `+0x332c`, `+0x3308`, `+0x3333` (the seamless gate); `matchEnv+0x3318` (the match tick, the restart clock **and** the penalty power index); `sideObj+0x7bc8` (the back-line count); `playerRef+0x84` (the short-corner flag); `player+0x4a8` (the veto cancel); `referee+0xac`/`+0xb4`/`+0xd48` | as listed |

**The conditional note, and it belongs on the census rather than buried in § Free kicks.** Of the
three attribute gates on the decision side, **only two are unconditional.** The `70→85` floor at
`0x1456b0d9c` computes `t = clamp((SPT−70)/15, 0, 1)`, compares it to the difficulty parameter at
`0x1456b0ded` and sets `bl` — but `0x1456b0e10 cmp byte[[r15+0x38]+2],0 ; je 0x1456b0e1e` skips the
`test bl,bl` that would act on it. **On that path Set Piece Taking does not gate anything.** The two
inline immediates — `cmp al,0x55` (SPT ≥ 85) and `cmp al,0x50` (Curl ≥ 80) — are not affected, and
they remain the safest ability edits in the chapter. § Open 18. [b]

---

## Tunables

Pool-cell sharer counts are from `build/exe_constant_census.json`, **read for this chapter**.
"Re-aim" means repoint the instruction's `disp32` at a private cell — **never write a shared cell in
place**, whatever its count. **Address convention for this table: the address given is the address of
the INSTRUCTION**, even where the word "disp32" appears; where the disp32 *field* address is wanted
it is given separately and said so. Not-safely-tunable rows come first.

| what | site | route | effect | evidence | sharers |
|---|---|---|---|---|---|
| **NOT SAFELY TUNABLE — the keeper's ±5.0 m penalty step** | disp32 at `0x14422cb5b` → `0x145a8dd78` (5.0) and `0x14422cb65` → `0x145b1d940` (−5.0) | — | **changing them does nothing**: the step is saturated by the clamp to ±(3.66 − 1.5) = ±2.160 m at `0x14422cb7c`. The real handle is the **1.5 m inset**, which is also shared. And 5.0f carries `raw_unexplained = 1` in the census | b | **1,885** / 212 |
| **NOT SAFELY TUNABLE — `pitchDims+0x44` as "the wall distance"** | inline `mov dword[rcx+0x44],0x41126666` at `0x1442ec757` | — | it is private and it is 9.15, but **the restart standoff does not read it**. Its one located consumer is the pitch-zone classifier's centre-circle bit at `0x1443237f9`. Editing it will not move a wall | b | private (and irrelevant) |
| **NOT SAFELY TUNABLE — the open-play kick-error model, for set pieces** | `0x14401a900`, `0x143ed71d0` | — | **there is nothing to tune**: no dead ball is on that path. Editing it to "fix free kicks" changes open play only | b | — |
| **NOT SAFELY TUNABLE — the wall command cells** | `teamAI + 0x8f4c + slot*4`, values `0x69` / `0x6a` | runtime data | this *is* the wall's control surface, but it is runtime state written by something upstream that was **not located**. A live-patch experiment, not a file or exe edit | b | per-team runtime array |
| **the in-box severity threshold (60 → 40)** | `mov eax,0x3c` at `0x143d862a4` | exe code, inline | § The anti-penalty bias #1. The best single byte in the chapter | b | private |
| **the out-of-box severity threshold (40)** | `mov ecx,0x28` at `0x143d8629f` | exe code, inline | § The anti-penalty bias #2 | b | private |
| **the in-box contest veto (0.4)** | the **4-byte** `movaps xmm6,xmm8` (`41 0f 28 f0`) at `0x143d874c1`, value from `0x145b2a690` | exe code — **cave required**; the detour consumes `0x143d874c1..c8` (movaps + the 4-byte `comiss` at `0x143d874c5`) and returns to `0x143d874c9` | § The anti-penalty bias #3 | b | 623 (and 622 on the adjacent 0.8f) |
| **the out-of-box contest veto (0.7)** | disp32 at `0x143d874a7` → `0x145bbe200` | exe code — re-aim | § The anti-penalty bias #4 | b | 461 |
| **yellow / red card thresholds (80 / 110)** | `0x143d862b5` **and** `0x143d862bb` (both); `0x143d862d6` | exe code, inline | a card-happier referee. Moving only one of the two 80s changes two unrelated behaviours | b | private |
| **near-post dead-ball accuracy curve** — the Set Piece Taking logistic | `0x143f0540b` → 99.0, `0x143f05413` → −59.0, `0x143f0541b` → 5.5, `0x143f05423` → 2.5 | exe constants — re-aim | the midpoint and steepness of P(re-draw). Today it crosses 50 % at rating **63** and is steepest across **58–68**, which means the whole ratings band above ~85 is already flat and undifferentiated. Raising **2.5** shifts everyone toward "good taker"; raising **5.5** steepens the transition and narrows the band it happens in. **SCOPE, and it must travel with the row**: the roll these cells feed fires only on a simulated step the goal-mouth test classifies **2** (in the goal, within 1.0 m of a post) inside a loop gated on `player+0xad0 ∈ {0x26, 0x2c}`. It is the most targeted **near-post** dead-ball lever in the game; it does **nothing** for corner delivery, throw-ins, kick-offs, goal kicks or restarts played as passes | **a-emulated** for the curve, **b** for the scope | 90 / **8** / 64 / 477 |
| **the post-margin band that triggers the accuracy roll at all** (1.0 m) | disp32 at `0x143f062a7` → `0x1478502b8` | exe code — **re-aim only, never in place** | widens or narrows how often the curve above is consulted | b | **13,240** (the image-wide 1.0f, `raw_unexplained = 5`) |
| **the free-kick distance ladder** — 23 / 26 / 30 / 40 m | `0x146b3db1c` = 529.0 (`0x1456b0f37`), `0x146b22a70` = 676.0 (`0x1456b0eec`), `0x145d8beb0` = 900.0 (`0x1456b0e7c` and `0x1456b0f45`), `0x1466c54f0` = 1600.0 (`0x1456b0f59`) | exe constants — re-aim, but these are the **least shared floats in the chapter** | 1600 → 1225 stops 40 m knuckle attempts; 529 → 400 makes 20–23 m free kicks require the window or curl instead of being automatic | b | **6** / **10** / 60 / **28** |
| **the free-kick curl gate** — Set Piece Taking ≥ 85, Curl ≥ 80 | `cmp al,0x55` at `0x1456b0f1a`, `cmp al,0x50` at `0x1456b0f30` | exe code, **private inline immediates** | the safest class of edit here: one instruction each, no cell. Pairs naturally with the 26 m band | b | private |
| **the CONDITIONAL floor on attempting a direct free kick** — 70 → 85 | `0x145b711c0` = 70.0 at `0x1456b0da9`, `0x1469e6cf8` = 85.0 at `0x1456b0dc5`, divisor `0x145c0b000` = 15.0 at `0x1456b0dd8`, compared at `0x1456b0ded` | exe constants — re-aim | raising 70 removes free-kick shooting from the middling-set-piece population — **but only on the path where the floor is enforced**. `cmp byte[[r15+0x38]+2],0 ; je 0x1456b0e1e` at `0x1456b0e10` **jumps over the `test bl,bl`** at `0x1456b0e16`, so when that byte is zero the ladder alone decides and these three cells do nothing. What the byte is was not established (§ Open 18). **70.0 is also the long-throw scoring floor** read at `0x1456af929` — treat as shared | b for the arithmetic **and** for the bypass | **305** / 92 / 943 |
| **short-corner frequency** — 10 %, or 50 % under `playerRef+0x84` | `cmp r8d,0xa` at `0x1456b0634`, `cmp r8d,0x32` at `0x1456b062e` | exe code, **private inline immediates** | `0x0a → 0x14` doubles short corners, `→ 0x00` removes them. The cleanest single-byte variety lever in the chapter. **But see § Open 4**: the word it compares was not traced | b | private |
| **restart delivery delays** — CPU 3.0 s corner, human 7.0 s; **CPU penalty 1.0 s (bare `fps`, no multiply), human 6.0 s** (§ Penalties → The delivery clock); CPU kick-off 0.5 s; CPU free kick 3.0 s (2.0 s in ball states `0xa`–`0xd`), human 6.0 or 8.0 s (4.0 s in those states) | 3.0 = `0x1478504e8` (`0x1456b084f`, `0x1456b0c0c`); 7.0 = `0x145c36ac0` (`0x1456b087e`); 6.0 = `0x145ab244c` (`0x1456b049a`, `0x1456b0c9d`); 4.0 = `0x145ab1b48` (`0x1456b0c44`); 8.0 = `0x145b52fbc` (`0x1456b0cb6`); kick-off 0.5 = `0x147850248` (`0x1456b1f84`) | exe constants — **all generic, re-aim only** | sets the whole pace of dead-ball play: the CPU's "instant" corner, and how long a human gets before the AI fires it for him. Note the CPU penalty has **no cell at all** — it is `fps × 1`, so shortening it means changing the compare at `0x1456b04a7`, not a float | b, all sites re-derived here | 1,761 / 398 / **646** / 1,086 / 829 / 7,052 |
| **the short-corner window** — 2.0 s, or 7.0 s when a mate is already making the run | `0x147850490` = 2.0 at `0x1456b0654`; `0x145c36ac0` = 7.0 at `0x1456b073c` | exe constants — re-aim only | how long the short option stays on the table. Note a **pad-bound taker never gets the 7.0 s stretch** (`jne 0x1456b065e` skips the team-mate scan), so widening 2.0 is the only way to give a human more of a short-corner window | b | 2,014 / 398 |
| **the restart standoff (9.15 m)** | **instruction `0x143d48c25`** (`f3 0f 10 35 43 f5 dc 02` = `movss xmm6,[rip+0x2dcf543]`); its **disp32 field is `0x143d48c29..0x143d48c2c`** → cell `0x146b18170` | exe constant — **re-aim** (the provider reads it at exactly one instruction, so a private cell costs one disp32) | drives the corner, free-kick, kick-off and penalty retreat through `0x143d48bc0 → 0x143d48cb0 → 0x143d48e90`. **This is the restart-retreat lever, not `0x1442ec757`.** The cell's full referrer list, pasted verbatim from `build/exe_constant_census.json`, is `0x143ce0ad5`, `0x143d48c25`, `0x143d52946`, `0x143e46174`, `0x1440111e7`, `0x1442ec8d6` — the other five are outside the referee band, so do not edit in place, but a re-aim touches nothing else. Whether the wall *itself* is placed with this radius by `EMatchFlowTask::FkWallSet` was **not traced** (§ Open 12) | b | **6** |
| **the +1.0 m extra margin at kick-off and penalty (→ 10.15 m)** | disp32 at `0x143d48c5d` → `0x1478502b8` | exe code — re-aim only | removing it puts the ring at the legal 9.15 m instead of a metre back | b | **13,240** |
| **the throw-in standoff (6.0 m) and the taker's −3.0 m discount** | disp32 at `0x143d48c0d` → `0x145ab244c`; disp32 at `0x143d48e56` → `0x145da91c8` | exe constants — re-aim | 6 m is far more than the laws' 2 m and is why throw-ins feel unpressed | b | 646 / 137 |
| **CPU penalty aim distribution** | the 7-entry rel32 table at `0x1456aeefc`, consumed at `0x1456aedc3` | exe code (`.rdata`), referenced by exactly one instruction | re-weighting it spreads CPU penalties without touching a float. **Two cautions**: entry 0 points at `0x1456aee07`, which is *also* the out-of-range default, so changing entry 0 changes both; and if § Open 1 resolves badly the index never leaves 0 and the table is decorative | b | private to this switch |
| **CPU penalty lateral inset (0.75 of the goal half-width = 2.663 m)** | disp32 at `0x1456aed55` and `0x1456aed62` → `0x145a8dd6c` | exe constant — re-aim | toward 0.9 pushes CPU penalties nearer the posts. Note the keeper's own step caps at 2.16 m, so anything above ≈0.61 is already outside where he can stand | b | 229 |
| **the "low" CPU penalty target height (0.130423 m)** | disp32 at `0x1456aedd4` and `0x1456aedf9` → `0x146b20528` | exe constant — re-aim (near-private) | stops the CPU rolling penalties along the ground | b | **4** |
| **penalty power base 0.4 and span ×0.5 (→ 0.40–0.90)** | disp32 at `0x144205bd0` → `0x145b2a690`; `0x144205bc8` → `0x147850248`; `0x144205bc0` → `0x145a8dd7c` | exe constants — re-aim only | this is the **whole** of penalty power: no attribute term, no RNG. Narrowing the span removes the weak ones | b | 623 / **7,052** / 1,832 |
| **penalty power ladder length (11 steps)** | `mov eax,0xba2e8ba3` at `0x144205ba7` and `imul eax,edx,0xb` at `0x144205bb1` | exe code, inline | both must move together and the reciprocal recomputed; getting one right silently produces garbage indices. Usually not worth it — use the base and span | b | private |
| **long-throw reach 35.0 → 45.5 m, and the receiver profile** | `0x145c8d614` (`0x1456afa4c`), `0x146b4eb00` (`0x1456afa6e`); band cells `0x145b711c0` = 70.0, `0x145b52b90` = 90.0, `0x145a8aa44` = 20.0, `0x146b31240` = 175.0, `0x145e8f8a4` = 190.0 | exe constants — re-aim; 45.5, 175.0 and 190.0 are all **near-private** | the only ability-driven receiver choice in the family. Raising 175/190 makes the long throw actually seek tall players; narrowing 70/90 sharpens the aerial-specialist preference | b | 35.0: 316 · 45.5: **3** · 70.0: 305 · 90.0: 1,535 · 20.0: 1,099 · 175.0: **6** · 190.0: **14** |
| **penalty standing positions (22 slots, four arrangements)** | `positionPK_{2,3,4,5}`, fields `playerData[0..21].{enable, playerNo, startPosX, startPosZ}` | **dt270 data** — no exe patch, no shared cell, survives Konami updates | tighten the ring on the box, move the attacking keeper, stop midfielders standing in silly places. Pick the file by the **defending back line**: a back four edits `positionPK_4`. Coordinates are canonical-attacking and mirrored per side; Y is forced to 0; `playerNo` is wrapped mod 22 by the reader. **`positionNone` is inert — do not bother** | a for the values, b for the path | per object; nothing else reads these five |
| **how often a quick restart is allowed** | `cmp esi,1` at `0x1440e513a`; the `+0x34c0 != 0xb` and `+0x34c0 == 6 → +0x3304 ∉ {0,2,4,6}` exclusions in `0x1442e0180` | exe code, inline | a genuine "fewer ceremonies" feel lever. **UNVERIFIED IN GAME** — what `+0x332c` counts was not established | **c** | private |
| **the 9.15 m as a *wall* distance specifically** | **not isolated** | — | the standoff provider covers corner/FK/kick-off/penalty retreat; whether the `FkWallSet` flow task places wall members using the same radius was **not traced**. Change the standoff and test | c | — |

---

## Corrections to finished chapters

| chapter and claim | reality |
|---|---|
| **`ball-carrier-brain.md`**, ThinkUnit table: *"ThinkUnitSetPlay \| 0x1456b0060 \| gates/inputs \| … body not read"*, and the § body line *"SetPlay (0x1456b0ad0): B[SetPiece 0x21] ≥ 85, B[Curl 0x22] ≥ 80, cards Long Throw 0x13, Control Curve 7, Knuckle 8, level row 0x2a"* | **The body is now read, and the gate list is five different restart kinds' gates, not one unit's.** `vf2` is `0x1456b0060`, a six-way jump table at `0x1456b058c`; `0x1456b0ad0` is **only the FREE_KICK arm**. The `0x21`/`0x22`/card-7/card-8/row-`0x2a` reads are all inside that arm; the Long Throw card `0x13` is in the **THROW_IN** arm `0x1456b2160` (at `0x1456b22c9`) and in the receiver picker `0x1456af7f0`. Anyone auditing "the SetPlay unit" at `0x1456b0ad0` sees a fifth of it. [b] |
| **`ball-carrier-brain.md`**, answer-class table row *"8 \| ? \| — \| 0x66 (table name THROWIN_ROTATE; GK path, not verified)"* | **Verified, and it is NOT a GK path.** Class 8 is written at `0x1456b24cf` by the THROW_IN arm for the **outfield taker** while the restart clock is under `fps×3.0 + 0.5`; after 3 s the same arm writes class 2 instead (`0x1456b24e3`). [b] |
| **`ball-carrier-brain.md`**, ThinkUnit list rows *"state 11, 12, 13 → SetPlay"* | Correct, but incomplete: **which of the six arms runs is decided inside the unit by `UMatchInfo+0x34a0`, not by the ball state.** The ball state (`playerRef+0x58` via `0x143e34040`, values `{0xa,0xb,0xc,0xd}`) only **shortens** the FREE_KICK and corner delivery timers. [b] |
| **`player-executors.md`**, class row *"ActionKeeperCoaching \| 23 \| vf18 0x14422e410, vf16 0x14422e510 \| listed-only \| **no slot 20 — it never moves the keeper**. Whether it organises a wall is not established"* | **Two corrections.** (a) **It HAS slot 20** — `0x1456220d0`, the `ActionMove` base mover. Differencing its vtable (`0x146bbfbe8`) against `match::ai::ActionMove` here gives diffs at slots **0, 16 and 18 only**. What it lacks is a **vf4 destination override**, so the base mover is handed the keeper's own current position and he goes nowhere. Right conclusion, wrong mechanism. (b) **The wall question is settled NO**: vf16 and vf18 write exactly one field, `action+0x1050 = (UMatchInfo+0x33e4 != 1)`, triggered by a team-mate's decoded command byte `0x1b` or by `byte[0x1443395a0(idx)+0xc3]`; its action id is `0x54 KP_COACHING` and its four animations are `gkcoaching_high_0_0_lower_goalkick`, `…_up_goalkick`, `layer_gkcoaching_high_shout`, `layer_gkcoaching_mid_point`. **It is line-height coaching, mostly at a goal kick.** Status: `listed-only` → `decoded`. [b] |
| **`player-executors.md`**, rows *"ActionWallPress \| 23 \| vf4 0x144206020 \| listed-only \| census only"* and *"ActionWallJump \| 4 \| slot2 0x144206010 \| listed-only \| not examined"* | Both decodable in a line. **`ActionWallPress`** = `ActionMove` with slots **4, 12 and 13** changed (a probe said 4 and 12; slot 13 is `0x14172cb30` = gait **5**, not the base's 3): vf4 returns the **ball's** position, so the class is "charge the ball at gait 5". **`ActionWallJump::vf2`** → `0x144205c80` = a relay on `teamAI+0x8f4c+(idx%11)*4` holding `0x69`/`0x6a`, emitting `player+0x8b8 = 0x69` and `+0x8bc = 0x32`/`0x33`. Neither reads any ability. [b] |
| **`player-executors.md`**, row *"ActionPenaltyKick \| 7 \| s6 0x144205ad0 \| gate-only \| reads the published shot-aim fields like ActionShoot; body not decoded"* | **Decoded.** It writes `kickWork+0xe7c = 0.4 + 0.5×((UMatchInfo+0x3318 % 11)/10)`, an eleven-step power ladder 0.40–0.90 driven by the match tick; it defaults the aim to the centre of the attacking goal line and overrides it with the published aim from `0x1443395a0(playerIdx)` into `kickWork+0xea0/+0xea8`. It reaches **no RNG**, while its neighbour `ActionShoot::vf6` makes twelve draws. Status → `decoded`. [b] |
| **`player-executors.md`**, § *The action-id → executor dispatch is NOT a table* (Open 1) | **The three controls searched for the wrong encoding.** `0x143eee720(base, id)` is `cmp edx,0x71 / jge default / cmp qword[rcx + id*8 + 0x1b20],0 / je default / mov rax,[rcx + id*8 + 0x1b20]` — a **113-entry POINTER table**, which is why scans for u32/u16 *offset* windows and for `parent + executorOffset` arithmetic all returned zero. Its wrapper `0x143e9e7b0(mgr, id)` then calls the entry's **slot 2** — the driver/`canStart` in both contracts — and is used at `0x144205c9f` (`ActionWallJump`, id `0x32`) and `0x1441abb30` (`ActionSliding`, id `0xb`). 113 matches this chapter's 113 vtables. **Caveat, hardened in the repair pass:** the accessor's shape is [b]; *that the pointers are the executors* is **[c]** and now looks weaker, not stronger. The writer was not located; the 130-slot table at `+0x15a38` has a different bound; and **the ids are demonstrably not action-name ids** — re-read here, `nameTable[0x32] = COVER` and `nameTable[0xb] = GOAL_NET_DODGE`, neither of which is a plausible name for a wall jump or a sliding tackle, and the action-name run is 130 entries (`0x00..0x81`, a different enum starting at `0x82 = RL`) against a 113 bound. The one point in favour: the fallback is entry **1** and `nameTable[1] = BASE_POSITION`. [b for the bytes, c for the meaning] |
| **`goalkeeper.md`**, Open 3 *"Who allocates and writes the penalty aim descriptor"* | **CLOSED, and the answer matters.** The object at `rec+0x20` is the keeper's **own** tagged command record — the same `rec+0x20` that `player-executors.md`'s slot-4 resolver `0x145625a20` decodes — indexed by the keeper's own player index, and the only writers of such records in the image are `match::CommandPlayer`'s marshalling chain plus the netcode. **It is NOT the kicker's published aim.** "The CPU keeper cheats on penalties" is not supported at this site: the half-plane read is the keeper side's own directional input, produced by `match::pad::ThinkUnitKeeperPenaltykickMove` / `…Action` / `…Layer`. [b] |
| **`goalkeeper.md`** § 7, *"a 9-bit field (raw 0..511, units unproven)"*, with "an angle in degrees" marked [c] | **It is [b], and the units are DEGREES.** The packers `0x144318660`/`700`/`820`/`8f0`/`990` write it as `cvttss2si eax,xmm2 / cmp eax,0x168 (=360) / wrap via 0x144345ae0 / and eax,0x1ff`. And the missing half: for command ids `0x19` and `0x2d` (both kind 2) the marshaller `0x1440dab90` **snaps** the angle to exactly 0.0 or 180.0 at `0x1440dae02` on its own `comiss 90.0` test — so the keeper's `90.0 > angle` split is a symmetric left/right, not the lopsided quadrant test a raw 0–360 range would imply. [b] |
| **`goalkeeper.md`** § 7 and its tunables, *"the ±5.0 m penalty step"* | **The step is never 5 m.** The clamp the chapter correctly wrote as `±([pitchDim+8] − 1.5)` evaluates to **±2.160 m**, because `pitchDims+0x08 = 3.66` (inline immediate at `0x1442ec6ee`). The ±5.0 request is always saturated, so the row should say that tuning those cells would change nothing **even if they were private** — the real handle is the 1.5 m inset at `0x14422cb7c`. Also worth adding: `ActionKeeperMovePenaltyKick` overrides **no vf4** (verified against vftable `0x146be09a8`), so when vf16 refuses, the keeper's destination is simply where he already is. [b] |
| **`anime-actions.md`**, the 17-class Restart family section | Add that **every one of those classes shares vtable slot 8 = `0x143f05150` (`Restart::vf8`)**, the dead-ball launcher, which is a *different* function from `Kick::vf8` = `0x143ed0f80`, and that **exactly four classes stub it with `0x140c83910` — `GoalKickLongPass`, `GoalKickShortPass`, `PkWait` and `PKDemo`**. In particular `GoalKickStandby`, `SeamlessGoalKick`, `SeamlessGoalKickReady`, `SeamlessCornerKickReady`, all five `Wall*` classes and every `*Loop` / `FreeKick2nd*` / `SeamlessPass*` class **do** carry the launcher, so "the goal kick is launched somewhere else" is true only of the two ceremonial classes. The chapter's `Kick` row already notes "vf8 reaches the kick builder `0x14401a900`"; the `Restart` row needs the same treatment with the different target. [b] |
| **`anime-actions.md`**, § *Fouls: the animation layer reports, the referee decides* | Add that the level function's 40-vs-60 selection is `bt eax,0xb` on the return of the **pitch-zone classifier** `0x1443236e0`; that the classifier emits **two** penalty-area bits (bit 10 for the end where `side×x ≤ 0`, bit 11 for the other); and that the foul path tests **only bit 11** while the standoff enforcer `0x143d48cb0` tests **only bit 10**. Also that the veto sits in `0x143d86c90` at `0x143d874a7..0x143d874c9` and is skipped entirely unless the flag at `rsp+0x51` is set. [b] |
| **`pad-input.md`** § 8.4 and **`pad-power-and-cursor.md`** § 7, *"Does the human get a kick-error discount? No"* | The finding stands; **the scope needs stating.** "f is a pure function of the kicker's own effective kick attribute" is true of `match::anime::action::Kick::vf8 → 0x14401a900`, which is **open play**. Dead balls run `Restart::vf8` (`0x143f05150`) and its solver `0x143f05730`, which **do** read Set Piece Taking and **are** stochastic. Neither chapter's closure work touched that function, so nothing there is contradicted — but **"the kick-error model" should read "the open-play kick-error model" throughout**, or readers will conclude free kicks are covered. [b] |
| **`match-ai-decoded.md`**, the parenthetical *"(ours: 36 outside)"* on the foul threshold | **Stale.** The installed image is byte-identical to PRISTINE (SHA-1 verified here) and the immediate at `0x143d8629f` is `0x28` = 40 in PRISTINE, INSTALLED and STOCK alike. Nothing is patched there today. [b] |
| **The brief**, *"positionPK_2..5 and positionNone (~20 fields), UNLOCATED"* | Wrong on both counts. They have **four fields repeated over 22 rows** (88 values, struct 360 B), and they are **located and live** — fetched by name, which is why a constant-index liveness sweep could not see them. **Credit where it is due, corrected in the repair pass:** the "general lesson" is not a new finding — `build/dt270_liveness.json` says it itself, in the very record being corrected: *"UNLOCATED: no constant-idx get() site and no other pointer source was found - the idx is computed at runtime (or the object is never fetched). Fields are 'unlocated', which says NOTHING about liveness."* The tool was right and flagged its own limit; what is new here is the `sprintf` path, the reader, the applier and the values. [b] |

### Corrections to THIS chapter — the adversarial repair pass, 2026-09-20

Two verifiers re-read the chapter against PRISTINE. Every issue below was re-checked here against
the bytes before it was applied, and the summaries, headlines and § Tunables rows that restated each
claim were fixed with the body. Where a verifier was wrong, that is said too.

| # | what the chapter said | what the bytes say | evidence | where it was fixed |
|---|---|---|---|---|
| R1 | *"A hard ability floor gates the direct branch at all … ≤ 70 never, ≥ 85 always"*, listed in § Input census as one of only three attribute gates | **The floor is CONDITIONAL.** The flag `bl` it produces is only consulted when `byte[[r15+0x38]+2] != 0`: `0x1456b0e10 cmp byte[rax+2],0 ; 0x1456b0e14 je 0x1456b0e1e` **jumps over** `0x1456b0e16 test bl,bl ; je 0x1456b1075`. When that byte is zero a 40-rated taker reaches the ladder like a 99-rated one. The arithmetic itself is unchanged — `0x1456b0dd4 subss/divss`, `0x1456b0de6 movzx ebx,cl`, `0x1456b0ded comiss xmm0,[rax]` (rax = `[r15+0x50]`), `0x1456b0df5 cmova ebx,eax` | **b**, disassembled from the boundary `0x1456b0d9c` | § Free kicks (rewritten), § Input census, § Tunables (row retitled "CONDITIONAL floor"), new § Open 18 |
| R2 | *"4 × the percent-roll wrapper `0x144345ae0`"* in the solver's RNG census; *"6 RandInt + 3 Gaussian + 4 percent rolls"* in the controls table and Open 5 | **`0x144345ae0` is not a draw.** It is a 360° wrap: `movss xmm0,[rcx]` / `xorps xmm7,xmm7` / `comiss` against `[0x145b1d920] = 360.0` / store back unchanged if in range / else `fmodf` `0x140a24ed0` and `+360` if negative. The chapter named it correctly twice elsewhere and contradicted itself. Draw count is **10** (1 + 6 + 3), not 13 | **b**, `0x144345ae0` disassembled in full; cell read back as 360.0 | § Delivery step 1, § Both controls (new dedicated column), Open 5, § Penalties |
| R3 | *"the **3-byte** `movaps xmm6,xmm8` at `0x143d874c1`"*, sizing the anti-penalty cave | **4 bytes**: `41 0f 28 f0` — addressing `xmm8` needs REX.B. The next instruction, `comiss xmm6,xmm9` at `0x143d874c5`, is also 4 (`41 0f 2f f1`). A `jmp rel32` is 5, so the detour must take `0x143d874c1..c8` and the cave must replay the `comiss` and return to `0x143d874c9` | **b**, bytes read from PRISTINE | § The anti-penalty bias #3 (cave spelled out), § Tunables |
| R4 | the 9.15 m lever given as *"disp32 at `0x143d48c26`"* in two places and `0x143d48c25` in a third, with a referrer list five of whose six entries were +1 | `0x143d48c26` is one byte **into the opcode**. The instruction starts at **`0x143d48c25`** (`f3 0f 10 35 43 f5 dc 02`) and its disp32 field is `0x143d48c29..0x143d48c2c`. Census referrers, pasted verbatim: `0x143ce0ad5`, `0x143d48c25`, `0x143d52946`, `0x143e46174`, `0x1440111e7`, `0x1442ec8d6` | **b** + `build/exe_constant_census.json` | § What this enables, § Tunables (+ a stated address convention), § Negatives |
| R5 | *"the call means 'look up the object registered for **action kind `0x32`**' … The CPU wall is not structurally prevented from jumping. **[b]**"* | The **[b]** overreached. Shape is proven; **identity is [c]**. And the gloss is wrong: the ids are not action-name ids — `nameTable[0x32] = COVER`, `nameTable[0xb] = GOAL_NET_DODGE` (the id `ActionSliding` passes), and the dispatch bound 113 does not match the 130-name run (`0x00..0x81`; a different enum starts at `0x82 = RL`). `match::pad::ThinkUnitFreekickWallJump` exists in the image. **The probe's worry is neither confirmed nor refuted** | **b** for both tables; `nameTable` entries read through the pointer array at `0x148082f80` | § The wall (rewritten), § Negatives, § Corrections (player-executors row), Open 16 |
| R6 | *"`RandInt(0..100)`"* and *"P(re-draw) ≈ σ²"* | `0x143ea9260` ends `test ebx,ebx / cdq / cmovne ecx,ebx / idiv ecx / mov eax,edx` — a **remainder**, so `edx = 0x64` returns **0..99**. With an integer roll the probability is exactly **⌈100σ²⌉/100** | **b** | § Delivery step 4 |
| R7 | headline and three tables: *"gate a re-draw on Set Piece Taking"*, *"dead-ball accuracy that separates a 95 taker from a 60"*, *"the single most targeted dead-ball realism lever"* | **Far too broad.** The only branch into the roll block is `0x143f05575 call 0x143f06210 ; cmp al,2 ; je 0x143f0567a`, and that loop is gated at `0x143f054b5` on `player+0xad0 ∈ {0x26,0x2c}`. Corner crosses, throw-ins, kick-offs, goal kicks and passes never reach it. **This was the chapter's biggest scope defect and it was in the headline, the summary, § What this enables and § Tunables — all four are fixed** | **b**, branch census over all six chunks of `0x143f05150` | header, § Set pieces in one paragraph, § What this enables, § Delivery (new scope paragraph), § Tunables, § Class status |
| R8 | *"the goal kick is the one restart whose launch is not `Restart::vf8`"* | True only of the **two ceremonial classes**. `GoalKickStandby::vf8`, `SeamlessGoalKick::vf8` and `SeamlessGoalKickReady::vf8` are all `0x143f05150`. Thirteen further classes the chapter filed under "vf8 —" also carry it | **b**, `build/exe_map.json` | § Goal kicks, § Delivery vf8 table, § Class status, Open 6, § Corrections (`anime-actions.md` row) |
| R9 | *"`ActionKeeperPKSaving`'s deterministic trajectory intercept … which has no left/right branch"*, unlabelled, against its own `gate-only` row | Three defects. `0x14422d4d0` holds **no geometry** — it gates and calls the **unread** `0x14422d570` (4 chunks). Slot 6 `0x14422cc00` is a `jmp 0x14422cc10` thunk into an **unread** 2,239-B body. **Both unread bodies call the 360° angle wrap** (`0x14422d9c9`, `0x14422cc7b`), so "no left/right branch" is withdrawn. What survives: **zero RNG** under full closure (41 and 22 functions, frontier exhausted). *The verifier also called the slot-6 citation "unanchored" because `func_chunks` returns `[]` for it — that part is wrong: it is a real 5-byte thunk with no `.pdata` entry of its own, and its target does have chunks* | **b** | § Penalties → the keeper's dive, § Class status, new § Open 19 |
| R10 | § Set pieces in one paragraph: *"one player … is admitted to `ThinkUnitSetPlay`"* and *"picked up by the `match::player` kick executors (… `ActionFreeKick`, … `ActionKickoff` …) through the same published-result table"* | Both withdrawn by the chapter's own body two sections later and left standing in the summary. **Five of six arms carry the cursor gate**; `0x1456b042b` (FREE_KICK) is four instructions with no compare. **`ActionFreeKick` slot 6 is `0x140c83810` = `mov al,1 ; ret`** and `ActionKickoff` slot 6 is `0x140c853c0` = `xor al,al ; ret` with a slot-5 body at `0x1441c4880` | **b**, all six arms disassembled; `exe_map.json` slot tables | § Set pieces in one paragraph (rewritten) |
| R11 | header: *"reaches no random number generator **anywhere**"* vs the section's own disclosure that the census counted only direct edges | The zeros are **stronger** than the chapter claimed, not weaker — but the scope word had to be made honest. Re-run here as a **transitive closure** over `func_chunks`, frontier exhausted: `ThinkUnitSetPlay` 66 fns / 0 RNG, foul decision 39 / 0, PK aim 1 / 0, `ActionPenaltyKick::vf6` 3 / 0, keeper stance 5 / 0, `ActionWallJump::vf2` 3 / 0, positionPK reader 6 / 0 and applier 7 / 0, PKSaving 41 and 22 / 0. **Positive control** `0x14401a900`: 75 fns, **10 RNG edges**. **Negative control** `ChanceSpaceRun::vf5`: 91 fns, 0 RNG, exhausted. Virtual dispatch remains out of scope and is now stated once, in the section header | **b** | header, § Both controls (scope paragraph replaces the disclosure) |
| R12 | header: *"Every contested claim, every tunable site … was re-derived"*, one sentence above a list of things that were not | The quick-restart gate row in § Tunables is built on the probe-carried `0x1442e0180` predicate and `ThinkUnitAutoRestart` material. It is marked **[c]** and "UNVERIFIED IN GAME" in the table, so the row is honest; the header's universal was not | — | header (exception stated) |
| R13 | § Kick-offs and § Goal kicks reported only what is **absent** in those two arms | Outputs now stated. **Kick-off**: `fps × 0.5` clock (`0x1456b1f84`), **answer class 3** (`0x1456b1fd3`), a heading `+180°` wrapped into `[0,360)` at `rec+0x30`, and a nearest-eligible-team-mate index written at `0x1456b2139` after a scan over the eleven-entry role list at `0x146c274c0` (control byte `+0x41f6`, route state `0xb`, cap `[0x145a8e378] = 10000.0`, sentinel `0xff`). **Goal kick**: **class `0xd`** at `0x1456b1c09` on ball state `0xc`, **class `0xc`** at `0x1456b1e19` when `matchEnv+0x33e4 == 1`, target at `rec+0x1c` (sentinel `0xff`), type at `rec+0x20` | **b** | § Kick-offs, § Goal kicks, § Class status |
| R14 | *"`Restart::vf8` … Entered only when the kick-mode byte `player+0xad0` is `0x26` or `0x2c`"* | The **function** is entered unconditionally. `0x143f05279` sits inside a `cmp dword[rdi],5` arm, and a non-matching mode at `0x143f054b5` jumps past the **simulation loop** to the commit path. So the mode gates the sim (and hence the roll), not the call | **b** | § What `Restart::vf8` actually does, new § Open 17 |
| R15 | § What this enables: *"Seven target/aim pickers scanned"* vs "twelve" in two other sections; *"131-entry action-name table"* | **Twelve functions, seven getters** — the row had collapsed the getter count into the picker count. And the action-name run is **130** entries (`0x00..0x81`), measured here by walking the pointer array | **b** | § What this enables, § Corners, § The wall |
| R16 | § Tunables offered *"CPU penalty 1.0 s, human 6.0 s"* with no derivation anywhere in the chapter | Derivation added. `0x1456b045b call 0x14533eb20` → `0x1456b0473 cvttss2si rsi,xmm0` gives `fps × 1`; `0x1456b0482 call 0x1442e0e80` selects the pad path, which multiplies by `[0x145ab244c] = 6.0` at `0x1456b049a`; compared at `0x1456b04a7 cmp esi,[r13+0x78] ; ja`. **There is no cell for the CPU value** | **b** | new § Penalties → The delivery clock, § Tunables |
| R17 | § Corrections presented *"unlocated must not be read as probably dead"* as a probe headline that did not survive | The lesson is the liveness tool's **own note**, verbatim, on the very records being corrected. Credited to it; the genuinely new material (the `sprintf` path, the reader, the applier, the values) is unaffected | `build/dt270_liveness.json` | § positionPK, § Corrections |

---

## Negatives — proven absent, do not spend a week on these

- **No dead ball goes through the open-play kick-error builder `0x14401a900`.** It has exactly one
  caller (`0x144016d3d` in `0x144016a70`), whose only caller is `Kick::vf8` = `0x143ed0f80`. Every
  Restart-family class carries slot 8 = `0x143f05150` instead. The brief's framing — "what f and p
  does a dead ball supply to the kick builder" — has no answer because a dead ball supplies neither.
  [b, all three caller edges re-derived here]
- **Set Piece Taking and Curl are never read as *attributes* by the open-play kick-error model.** All
  arms of `0x143ed7440`'s class switch select `0x1b`, `0x1c` or `0x1d`; its `0x21`/`0x22` reads are
  card ids through `0x143eadbe0`. [b]
- **Corner, free-kick, goal-kick, kick-off, throw-in and penalty target/aim selection is
  ability-free.** Twelve functions scanned end to end for seven different getters: zero hits. Only
  the long-throw picker `0x1456af7f0` reads anything. So "the wrong player gets on the end of my
  corners" is a formation/assignment-table issue, not a scoring one. [b]
- **`ThinkUnitSetPlay` does not choose the taker.** It compares its own player index against
  `UMatchInfo+0x41d8` and bails on mismatch; nothing in its seven chunks writes that field. [b]
- **Free kicks beyond 40 m are never shot directly by this unit** — the `1600.0` test at
  `0x1456b0f61` exits to the pass search with no escape. [b]
- **The knuckle branch is unreachable inside 23–30 m.** `bl` is cleared at `0x143d…` — precisely,
  `xor bl,bl` at `0x1456b0e84` — and the whole knuckle block is skipped by `comiss xmm9,xmm6 ; jbe`
  at `0x1456b0e86` whenever d² ≤ 900. The 23–30 m condition is effectively **(window) OR (curl)**.
  [b, re-derived here]
- **The wall's jump/not-jump decision is not ability-gated.** A full disassembly of `0x144205c80`
  contains no `ATTR_get`, no card test and no playstyle test. [b]
- **`ActionWallPress` holds no wall line.** Its vf4 returns the ball position; the class is "run at
  the ball". No distance constant exists in it. [b]
- **`ActionKeeperCoaching` does not organise the wall** (see § Corrections). It has no vf4 override,
  so its destination is the keeper's own position; it writes exactly one int. [b]
- **`0x143e9e7b0` is not an inline pad test.** It is a **table lookup plus a virtual call**: a
  113-entry pointer table at `base+0x1b20` (bound `cmp edx,0x71`, fallback entry 1), then slot 2 of
  whatever object is registered. [b] **Whether the object it reaches consults pad state is NOT
  established [c]** — the table's writer was not found, the id namespace is not the action-name table
  (`nameTable[0x32] = COVER`, `nameTable[0xb] = GOAL_NET_DODGE`; bound 113 vs a 130-name run), and
  `match::pad::ThinkUnitFreekickWallJump` exists in the image. So **"the CPU wall is not structurally
  prevented from jumping" is not proven and not refuted.** What *is* proven: `0x144205c80` itself
  contains no pad read and no ability read. § Open 16.
- **`ThinkUnitBlockTestAutoRestart` is dead.** Its `vf17` (`0x1440e5200`) is `xor al,al; ret`; its
  `vf12` faithfully returns command id `0x3d`, which can never be emitted. [b]
- **A dead read inside `ThinkUnitAutoRestart::vf17`:** `0x1442c3f80()`'s result at `0x1440e511d` is
  unconditionally overwritten at `0x1440e5138`. The "config × 20" value never reaches the
  comparison. [b]
- **A dead guard in the keeper's penalty stance:** `cmp cl,0x55 / je fail` at `0x14422caee` is
  unreachable, because control only arrives after `0x144318200(id) == 2` and the descriptor row for
  id `0x55` has kind 1. [b]
- **`positionNone` is unreachable.** The only name producer is `sprintf("positionPK_%d", …)`, which
  cannot emit that string; its two occurrences in the image are a registration-table entry and a
  path literal. Its data is all-zero with every `enable = 0`. [b]
- **No CPU-side command-record writer exists in the image.** Every writer is the `CommandPlayer`
  chain (`0x1440dab90`, `0x1440dcf60`, `0x1440db1c0`, `CommandPlayer::vf3 0x1440de590`),
  `OnlineCommandControllerImpl::vf17`, or `0x145716310`. Established two independent ways: the call
  sites of the setters `0x144318290`/`0x1443182a0`, and the call sites of the kind→slot mapper
  `0x144307fb0`. **Limitation, stated plainly:** a writer that stored the id and the packed dword
  with plain `mov` immediates would be invisible to both sweeps. [b, with the stated hole]
- **No direct writer of `UMatchInfo+0x34a0` exists in `.xcode`.** An instruction-aware disp32 sweep
  over `0x140000000..0x146000000` returns 42 accesses in the match band and every one is a read. The
  restart-kind enum therefore cannot be named from its writer; it arrives through a struct copy or a
  computed base. [b]
- **The foul scorer passes no animation-supplied severity** (confirming `anime-actions.md`): its
  entire input is two player indices at `event+0x14`/`+0x20` plus the two players' own records.
  Severity is the sum of three sub-scorers stored as a float at `referee+0xac`. [b]
- **Not one attribute is read** in the level function, the veto, the standoff provider, the
  enforcer, the CPU aim builder, the penalty power ladder or the keeper's penalty stance. **Penalty
  quality in eFootball does not depend on who is taking it at any of those sites** — it depends on
  the match tick and a seven-entry table. [b]
- **Ball placement for a restart was NOT located.** The named constants are in hand (spot 41.56,
  goal-area line 47.06, pitch bounds); the writer is not. *Not found*, not *absent*. [honest negative]
- **The 9.15 m is not absent from the wall code because it is absent from the image** — a probe
  reported that negative after a byte search for `9.15f`, `9.144f`, `915.0f` and `83.7225f`, and it
  was wrong twice over: the standoff provider reads the pool cell `0x146b18170` that the search
  itself found (`0x143d48c25` was in its own referrer list), and there is a *second* 9.15 as an
  inline `mov imm32` at `0x1442ec757` that no float-pattern search can see. **This is the brief's
  "one encoding" gotcha costing a wrong answer, again.** [b]

---

## Class status

Every set-piece class named in the brief, plus the ones this chapter added. `decoded` = body's
control flow followed to its outputs; `gate-only` = entry gate, inputs or one slot known;
`listed-only` = named in a census and nothing else; `stub` = proven to have no behaviour.

### `match::player` executors

| class | offset | slots | key addresses | status | what is known |
|---|---|---|---|---|---|
| `ActionCornerKick` | `+0x11038` | 7 | s4 `0x145625a20`, s6 `0x1442057f0` | decoded | published `+0x1c`, fallback `0x1442053c0`, `work+0xe88`, `work+0xff9 = 2` (`player-executors.md`) |
| `ActionThrowin` | `+0x11018` | 7 | s4 `0x144204420` (own), s6 `0x144204260` | gate-only | one of two kick classes with its own slot-4 resolver; body not read |
| `ActionThrowInRotate` | `+0x11028` | **4** | s2 `0x144204a50` | listed-only | the executor behind answer class 8; body not read |
| `ActionKickoff` | `+0x10fa8` | 7 | **s5 `0x1441c4880`**, s6 = stub | gate-only | **the only class in all 34 with a slot-5 body**; resolves its target before the published decision is consulted |
| `ActionFreeKick` | `+0x10fb8` | 7 | s4 `0x145625a20`, **s6 = `0x140c83810` (`mov al,1; ret`)** | decoded (by exhaustion) | it has **no published-decision reader at all**: slot 5 refuses, slot 4 resolves the tagged descriptor, slot 6 returns true unconditionally |
| `ActionFreeKickLong` | `+0x10fc8` | 7 | s4 `0x1441ad530` (thunk), s6 **`0x1441b1500`** | decoded | **shares its whole slot-6 body with `ActionLongPass`**, so a long free kick reads `0x35 STRONGER_FOOT` three times and the result flips the sign of an emitted float |
| `ActionFreeKick2ndPass` | `+0x10fd8` | 7 | s4 `0x145625a20`, s6 `0x1441c4570` | listed-only | — |
| `ActionFreeKickCede` | `+0x10fe8` | **23** | vf4 `0x1441c46f0`, vf9 stub, vf12 → 2 | listed-only | a **movement** class sitting among the kick actions; only three slots differ from `ActionMove` |
| `ActionPenaltyKick` | `+0x11048` | 7 | s4 `0x1441ad530`, **s6 `0x144205ad0`** | **decoded** | the eleven-step power ladder; aim default + published override; **zero RNG** |
| `ActionPenaltyKickAfter` | `+0x14b08` | 23 | vf4 `0x14422f3b0`, vf6 `0x14422f640`, vf20 `0x14422f320`, vf22 `0x14140d670` | gate-only | five slots differ from `ActionMove`; **zero RNG**; bodies not read |
| `ActionGoalKickLong` | `+0x10f58` | 7 | s4 `0x145625a20`, s6 `0x1441b3280` | listed-only | its **ceremonial** anime counterparts (`GoalKickLongPass`/`ShortPass`) stub vf8, so *that* launch path is elsewhere (§ Open 6) — but `GoalKickStandby` and both `SeamlessGoalKick` classes carry `0x143f05150` |
| `ActionShortCornerMove` | `+0x13940` | 23 | vf4 `0x14420a3e0`, vf13 `0x14420a4b0`, vf20 `0x1441dec00`, vf12 → 2 | gate-only | **action id `0x2c`**, which the corner arm scans team-mates for to extend the short-corner window to 7 s; body not read |
| `ActionSeamlessThrowInMove` | `+0x14a68` | 23 | **vf16 `0x144210b50` — its only override** | listed-only | `ActionMove` with a single accumulator override; destination is the base's |
| `ActionPassSupportThrowIn` | `+0x128f8` | 23 | 13 overrides incl. vf18 `0x1441e0c90`, vf20 `0x1441dec00`, vf4 = base | gate-only | the most heavily overridden set-piece movement class; **keeps `ActionMove`'s vf4**, so its geometry is in vf18 |
| `ActionWallPress` | `+0x13898` | 23 | **vf4 `0x144206020`, vf12 `0x140eeb6d0`, vf13 `0x14172cb30`** | **decoded** | "charge the ball at gait 5". No line, no distance, no ability |
| `ActionWallJump` | `+0x13888` | **4** | s2 `0x144206010` → **`0x144205c80`** | **decoded** | a relay on `teamAI+0x8f4c+(idx%11)*4`; gated by `0x143e9e7b0(…, 0x32)` and `0x144206060`; emits `0x69` + sub-mode `0x32`/`0x33`. No ability |
| `ActionPkMatchNextKeeper` | `+0x144f8` | 23 | vf4 `0x1442414e0`, vf19 `0x144240c50`, vf20 `0x144241490` | listed-only | six overrides; the shoot-out keeper-rotation mover; body not read |
| `ActionKeeperMoveFreeKick` | `+0x13790` | 23 | vf4 `0x144176d70`, vf20 `0x14422c460`, vf3/12/13/16/17 | gate-only | **eight overrides — real geometry**, unlike `ActionKeeperCoaching`. Action id `0x51 KP_MOVE_FREE_KICK`. Body not read |
| `ActionKeeperMovePenaltyKick` | `+0x137f8` | 23 | **vf16 `0x14422ca70` — its only override** | **decoded** | the command-driven ±2.16 m pre-kick step; **no vf4**, so a refusal leaves him where he stands |
| `ActionKeeperPKSaving` | `+0x13828` | 7 | s4 `0x14422d4d0` (a gate that delegates to the **unread** worker `0x14422d570`, 4 chunks), s6 `0x14422cc00` = `jmp 0x14422cc10` into an **unread** 2,239-B body | gate-only | **zero RNG** under full closure (41 / 22 fns, frontier exhausted) [b]. **"No left/right branch" is WITHDRAWN**: both unread bodies call the 360° angle wrap (`0x14422d9c9`, `0x14422cc7b`), so each handles a direction. § Open 19 |
| `ActionKeeperCoaching` | `+0x13980` | 23 | vf16 `0x14422e510`, vf18 `0x14422e410`, **vf20 = base `0x1456220d0`** | **decoded** | **NOT wall organisation.** Writes one field, `action+0x1050`; no vf4; four `gkcoaching_*` animations; id `0x54 KP_COACHING` |

### `match::ai::bp`

| class | key addresses | status | what is known |
|---|---|---|---|
| `ThinkUnitSetPlay` | vftable `0x14772f3e8`, vf2 `0x1456b0060`, table `0x1456b058c` | **decoded** | six-way dispatcher; arms `0x1456b1f10` (class 3 + angle + nearest receiver) / `0x1456b2160` (class 8 then 2) / `0x1456b1b80` (classes `0xd` and `0xc`) / `0x1456b05b0` (class 2, pass type 0 or 1) / `0x1456b0ad0` (class 1 or 2) / inline (PK aim); **five of six cursor-gated — FREE_KICK is not**; zero RNG under full closure (66 fns) |
| `ThinkUnitAutoRestart` | vf17 `0x1440e50f0`, vf12 table `0x1440e51e8` | decoded | gate = `0x1442e0180` + `+0x332c ≤ 1` + button `0x51`; emits `0x3a`/`0x38`/`0x42` by kind; contains one dead read |
| `ThinkUnitBlockTestAutoRestart` | vf17 `0x1440e5200`, vf12 `0x1440e2070` | **stub** | `xor al,al; ret` — inert. Its `0x3d` can never be emitted |

### `match::anime::action` (Restart family — 29-slot contract unless noted)

| class(es) | vf8 | status |
|---|---|---|
| `Restart` | **`0x143f05150`** | **decoded** — the dead-ball launcher: 250-step sim (gated on `player+0xad0 ∈ {0x26, 0x2c}`), goal-mouth test `0x143f06210`, Set Piece Taking logistic, and a re-draw roll reached **only on a class-2 step** |
| `FreeKick`, `FreeKickLoop`, `CornerKick`, `SeamlessCornerKick`, `ThrowinNormal`, `ThrowinLong`, `ThrowinLoop`, `SeamlessThrowin`, `PenaltyKick`, `KickoffKicker`, `KickoffOther`, `KickoffReceiver`, `QuickRestartKick` | `0x143f05150` (shared) | decoded **by inheritance** — same launcher, no own body |
| `WallJump`, `WallLoop`, `WallNotJump`, `WallRunOut`, `WallNotRunOut` (30 slots) | `0x143f05150` | listed-only — they carry the launcher slot but their own role was not read |
| **`GoalKickLongPass`, `GoalKickShortPass`** (30 slots) | **`0x140c83910` (`ret 0`)** | **stub at slot 8** — these two **CEREMONIAL** classes are launched elsewhere (§ Open 6). The goal kick *as such* is not: see the row below |
| `PkWait`, `PKDemo` | `0x140c83910` | stub at slot 8 — waiting/demo classes, no launch |
| `GoalKickStandby`, **`SeamlessGoalKick`** (30 slots), **`SeamlessGoalKickReady`** | **`0x143f05150`** | listed-only for their own bodies, **but they DO carry the dead-ball launcher** — so a seamless goal kick runs `Restart::vf8` |
| `FreeKick2ndCede`, `FreeKick2ndLoop`, `FreeKick2ndPassToKicker`, `CornerKickLoop`, `KickoffKickerLoop`, `PenaltyKickLoop`, `QuickRestartReady`, `SeamlessCornerKickReady`, `SeamlessPass(+Ready)` | **`0x143f05150`** (all of them, read from `exe_map.json`) | listed-only — enumerated in `anime-actions.md`, their own bodies not examined here. **The vf8 column is filled in**: an earlier draft printed "—" and understated what was known |

### Referee and flow

| thing | address | status |
|---|---|---|
| foul level fn | `0x143d861f0` | **decoded** — 40/60 threshold, 80/110 cards |
| foul decision fn | `0x143d86c90` | decoded for the veto (`0x143d874a7..c9`); the advantage block `0x143d88643..0x143d889e3` is **[c]** |
| foul scorer | `0x143d88fe0` | gate-only (`match-ai-decoded.md`) |
| pitch-zone classifier | `0x1443236e0` | decoded for bits 10, 11 and 14 |
| pitch-dimension init | `0x1442ec6d0` / scaled `0x1442ec780` | **decoded** — all 20 fields |
| standoff provider | `0x143d48bc0` | **decoded** — six-way by restart kind |
| standoff enforcer | `0x143d48cb0` | **decoded** — taker discount, cursor exemptions, box exemption |
| push-out | `0x143d48e90` | listed-only |
| seamless gate | `0x1442e0180` | **decoded** |
| `match::situation::Loader` | ctor `0x143c684a0`, reader `0x143c685a0`, applier `0x143c4f5f0` | **decoded** |

---

## Open questions

1. **Is `dword[*(g+0x790)]` — the CPU penalty aim index — ever non-zero?** `registry-blackboard.md`
   § 8 records that word (`URandomInfo+0x00`) as having **ten readers and no writer found anywhere in
   the image**, and § 8.1 flags exactly this failure mode on the sibling field `+0x08`. If it is
   never written, the CPU aims at aim-point **0** — high, on one side — for **every penalty in every
   match**, and the seven-entry table is decorative. This is the single highest-value live read in
   the chapter: break on `0x1456aed22` and log `ebx` across two penalties. It also decides whether
   the § Tunables row for the jump table is a lever or a no-op.
2. **Is a CPU keeper's command record ever non-empty at runtime?** The structural case that it is not
   is strong (`match::Command::update` loops over 8 hardware pad slots only; unflagged players get
   `CommandPlayer::vf2` = clear; no CPU-side command writer exists). If it holds, then
   `ActionKeeperMovePenaltyKick::vf16` always refuses for a CPU keeper and he takes **no pre-kick
   step at all**. One live read of the keeper's command byte during a CPU penalty settles it.
3. **Who writes `UMatchInfo+0x41d8` for a restart** — i.e. how the CPU actually picks the
   corner/free-kick taker. This is the literal subject of the owner's complaint and
   `ThinkUnitSetPlay` only verifies the choice. The human path exists in the pad command enum; the
   CPU chooser was not located. **Highest-value remaining static item.**
4. **What the short-corner word is.** `dword[0x1442eba80(ring, 0) + 8]` mod 100 decides it. The
   accessor is generic (55 callers image-wide, a ring over `0x348`-stride records with `+0x340`
   count and `+0x344` head), and the word's identity was **not traced**. Until it is, "10 % of
   corners are short" is the code's shape, not a measured rate — and if that word is as static as
   `URandomInfo+0x00` may be, it is not 10 % of anything.
5. **The direction of the dead-ball re-draw.** The roll and its curve are emulated and certain;
   whether the re-draw branch produces a **worse** kick or merely a **different** one is inferred
   from the fact that the discarded solution was the one heading inside the post margin.
   `0x143f05730` (2,487 B, **6 `RandInt` + 3 Gaussian = 9 draws**, plus 4 calls to the 360° wrap
   `0x144345ae0` which are **not** draws) was censused, not decoded. Decoding it turns the headline
   from "ability decides whether the near-post shot is kept" into a quantified error distribution —
   and it is what the owner's realism mod actually wants.
6. **Where a CEREMONIAL goal kick is launched.** `GoalKickLongPass::vf8` and
   `GoalKickShortPass::vf8` are `ret 0` stubs. This is **not** the goal kick in general:
   `GoalKickStandby`, `SeamlessGoalKick` and `SeamlessGoalKickReady` all carry `0x143f05150`. Likely
   the `GoalKick` base or the keeper's own kick path; not checked.
7. **The meaning of `byte[player+0x4a8]`** (read by `0x144301a90`), which cancels the in-box
   downgrade of the contest veto from 0.7 to 0.4 — and of `byte[player+0x28d8] == 2`, which is OR'd
   with the in-box bit to form the flag. Mechanism 2 of the anti-penalty bias is only as strong as
   this field allows, and nobody knows what it is.
8. **Why the foul scorer copies `int[playerB+0x29f0]` into the FLOAT field `referee+0xb4`** at
   `0x143d8913c` when `byte[playerB+0x28cd] != 0`, bypassing the `0x1442f55c0` recompute. If `+0x29f0`
   is genuinely an int, the reinterpreted float is a denormal near zero and the veto can **never**
   fire on that path — which would mean a whole class of contacts is always a foul. Worth one
   emulated check.
9. **The full decode of `0x1442f55c0`**, the geometric producer of the ball-contest score. The
   threshold it is compared against is proven; what a score of 0.7 *physically means* is not, so
   "won 70 % of the ball" is this project's phrasing and not the bytes'.
10. **The free-kick "position window" flag** (`dil`, set at `0x1456b0e74`): `|V − C| < 20` on one
    axis and a second coordinate strictly between **−12.0** (`0x146b01d90`) and **+12.0**
    (`0x145c0863c`), where V and C come from `0x144307180` and a PARAM block. The axes and units
    were not pinned, so the "20" cannot yet be quoted in metres — and this flag is what makes 26–30 m
    free kicks shootable.
11. **The free-kick pass-target scorer** (`0x1456b11a0..0x1456b168c`, plus a second pass at
    `0x1456b18f2`). Its structure is read — it walks
    `matchEnv+0x228d4 + idx*0xc8 + 0x1840 + (side*11+j)*8`, requires route state `0xb` and the
    control-allocation byte `+0x41f6`, and accumulates clamped normalised terms into `xmm6` before
    keeping the best — but the individual terms were not extracted. **This is where "who the free
    kick is played to" actually lives.**
12. **Who writes the wall command cells** `teamAI + 0x8f4c + slot*4`, and who decides wall
    membership and the stand-off *for the wall specifically*. `ActionWallPress` and `ActionWallJump`
    are both pure consumers. `EMatchFlowTask::FkWallSet` is the named place to look.
13. **What selects between the four `positionPK` variants beyond the back-line count**, and whether
    the other eleven bytes of the line-group counters at `+0x7bc8`/`+3`/`+6`/`+9` are ever read.
    Only `counters[0]` has a located consumer; the rest are computed every frame and, as far as this
    chapter found, never used.
14. **Where the ball is placed for each restart kind.** Named constants in hand; the writer is not.
15. **Naming the six restart states.** Kind 6 = penalty is [b] (it gates the positionPK load). The
    rest rests on the standoff table matching the laws of the game — 9.15 for a corner, 9.15+1 for a
    kick-off and a penalty, 6.0 with a taker discount for a throw-in, 0.0 for a goal kick — which is
    persuasive but **[c]**, and cannot be confirmed from a writer because none exists in `.xcode`.
16. **Whether `0x143eee720`'s 113-entry pointer table is the action-id → executor dispatch**
    `player-executors.md` Open 1 is looking for. The accessor's shape is proven; the identity of the
    pointers is not, and the 130-slot table at `+0x15a38` has a different bound. **Sharpened in the
    repair pass, and it cuts both ways**: the ids passed to it are *not* action-name ids
    (`nameTable[0x32] = COVER` for `ActionWallJump`, `nameTable[0xb] = GOAL_NET_DODGE` for
    `ActionSliding` — both nonsense), and the bound 113 does not match the 130-name run, which argues
    the two index spaces are different; but the fallback is entry **1** and `nameTable[1] =
    BASE_POSITION`, the natural default action, which argues the other way. Until the `+0x1b20`
    writer is found, `ActionWallJump`'s gate could equally reach
    `match::pad::ThinkUnitFreekickWallJump`, which exists in the image. **One live read of
    `[base+0x1b20 + 0x32*8]` during a free kick settles both this and the CPU-wall question.**
17. **What kick modes `0x26` and `0x2c` are**, and what `dword[rdi]` at `0x143f05259` (tested against
    5) counts. Together they gate everything stochastic in `Restart::vf8`: the forward sim runs only
    in those two modes, and the accuracy roll lives inside it. Naming them turns "the near-post
    accuracy curve applies to *some* dead balls" into a list of which ones.
18. **What `byte[[r15+0x38]+2]` is** (tested at `0x1456b0e10` in the FREE_KICK arm). When it is zero
    the free-kick ability floor's flag `bl` is never consulted and a 40-rated taker shoots like a
    99-rated one. This is one of only two ability reads on the entire decision side, and whether it
    fires at all depends on an unidentified byte. Sits beside Open 7 (`byte[player+0x4a8]`) as the
    two "an unnamed byte decides whether the lever exists" holes in this chapter.
19. **`ActionKeeperPKSaving`'s two unread bodies** — the slot-4 worker `0x14422d570` (4 chunks,
    `0x14422d570..0x14422dacc`) and the slot-6 body `0x14422cc10` (`0x14422cc10..0x14422d4cf`).
    Both are RNG-free under full closure, so the save is **not** random; but both call the 360° angle
    wrap, so whether the keeper's dive is direction-blind is open. This is the question "does the CPU
    keeper guess, or does he read the kick?" and it is one function-read away.

---

## Harnesses

Two read-only tools, both in `WORKREPO/tools`, both re-run for this chapter:

* `tools/emu_deadball_accuracy.py` — runs `0x143f05404..0x143f05445` and `0x143f0568b..0x143f0569e`
  under Unicorn on PRISTINE, including the image's real `expf` at `0x140a24cd0`, with `xmm9` seeded
  1.0. Prints the σ / P(re-draw) table and **five literal-pool controls** (99.0, −59.0, 5.5, 2.5,
  100.0), all of which read back correct on this run. The saturation control matters here: an
  earlier run returned a flat 0 across the whole input range because `xmm9` was uninitialised, which
  is exactly what the "closures saturate" rule is for.
* `tools/setpiece_anime_timing.py` — reads the extracted `Mbinfo/bin` tables with the exe's own
  record rules (13-bit index, 1/60 s) and joins them to the 7,883-entry name index.

Nothing was written to the game, no `exe_patch` or `gameplay_tune` mutation ran, and no commit was
made.
