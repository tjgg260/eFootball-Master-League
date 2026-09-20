# The animation layer — `match::anime` (2026-09-20)

What actually moves the body once an executor has said "go here, at this gait, along this path".
**131 RTTI classes**, of which **106 are `match::anime::action::*`**, plus the three `match::MbInfo*`
classes that are this subsystem's data store and — added by the 2026-09-20 repair pass —
**`match::AnimeCollision`**, the per-player collision body, all four of which sit outside the
namespace: **135 rows** in the class table below.

Produced by the hand-decoded skeleton of 2026-09-19 (which is kept, and whose central correction —
*the motion assets are not hashed* — stands) plus four workflow probes: motion assets and cancel
data, the mover and the action contract, contact/stagger/falling, and the goalkeeper save family
with first touch. **Every load-bearing claim in this chapter was re-derived from the PRISTINE bytes
or from the shipped data files for this write-up.** The three probes that touched `CancelData.bin`
produced **three different decode rules**; § The decode rule settles it from the game's own getter
and the losing readings are named.

Evidence levels: **a-emulated** (the game's own bytes executed, or the shipped data decoded and
counted), **b-disassembly** (followed instruction by instruction), **c-inferred** (structural
reasoning only). Addresses are VAs at base `0x140000000`, no ASLR, decoded from
`eFootball.exe.PRISTINE`.

**Our own patches — REPAIRED 2026-09-20, and the earlier version of this paragraph was wrong.**
As of this pass **the installed image is byte-identical to PRISTINE**: both are 352,409,088 B,
sha1 `d2b84d1c506ab09d62035b7889a57452479b73a8`, and a full numpy byte compare gives **0 differing
bytes**. `build/exe_patch_state.json` still lists 27 specs as "applied" and is **stale**;
`exe_patch.py status` reports `phys-whistle-threshold.json` as `pristine`. **Every constant quoted
in this chapter is therefore both stock and installed.** [a]

The 909-byte diff is real but it is against an **archived** build,
`C:/Users/tjgg2/Backups/eFootball/eFootball.exe.patched-20260920-001042` (sha1
`eaaa7ffada4f20f1a15e835d8556b01da8cdcd49`, mtime 2026-09-20 00:10:42; `eFootball.exe.STOCK` is
dated 00:05:05 and the installed exe 00:10:53, i.e. the patched build was archived and stock put back
at 00:10 — before this chapter was first written at 00:46, which is why it described the patched
state in the present tense when the patches were already gone). Against PRISTINE that archive carries **909 differing bytes in 105 contiguous runs**,
of which **24 — not four — fall in the anime address band `0x143e90000..0x144090000`**:
`0x143eb8681`, `0x143f060ca`/`0d5`/`0d8`, `0x143f56e3d`, `0x143f56e68`, `0x1440187b4`, `0x144019a55`,
`0x144019ec8`, `0x14401a130`, `0x14401a175`, `0x14401a17a`, `0x14401b3a7`, `0x14401b3db`,
`0x14401b3e4`, `0x14401b428`, `0x14401b7dc`, `0x14401c15e`, `0x14401c1e0`, `0x14401cf3c`,
`0x14401f2a2`, `0x14401f2aa`, `0x14407a17a`, `0x14407a1a4`. Most of that band is the kick/ball
builder cluster at `0x14401****`; the last two sit inside the trap reader range this chapter uses for
realism item 3. **None is in a contact gate** — that part of the original claim survives. [a]

The referee-band edits in that archive, with the **instruction** addresses (the earlier version of
this paragraph quoted containing-function addresses, which is why they did not check out): the
outside-the-box threshold byte at `0x143d862a0` `0x28` -> `0x24` (40 -> 36, spec
`phys-whistle-threshold.json`); `0x143d868fe mulss` re-aimed `0x145a8aa44` 20.0 -> `0x145da7de0`
25.0; `0x143d86bcd mulss` re-aimed `0x145c8d614` 35.0 -> `0x145d58ec8` 40.0; `0x143d88659 movss`
re-aimed `0x1466af9f0` 0.06 -> `0x145b5588c` 0.05; `0x143d51a90` `mov dl,1` -> `mov dl,2`. **None of
these is in the image today**, and `0x143d8629f` reads `b9 28 00 00 00` = `mov ecx,0x28` = **40** in
PRISTINE *and* in the installed exe. See Correction 20, which is withdrawn. [a]

Companion chapters: [player-executors.md](player-executors.md) (what hands this layer its orders —
**its OPEN 7 closes here**), [anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md)
(the long form of the keeper and trap families, written by the same probe round),
[pes2014-vs-efootball-contact.md](pes2014-vs-efootball-contact.md) (the format ground truth —
**and three of its counts are corrected here**), [registry-blackboard.md](registry-blackboard.md).

> **Read [§ Corrections to finished chapters](#corrections-to-finished-chapters) first.** The single
> most consequential belief about this subsystem — "the post-contact lockout cannot be measured
> because the keyframes are out of reach" — is dead. The keyframes are read, named, in seconds, and
> reachable by this project's own proven write path. And the number every earlier spec was built on,
> *"10 of 11 stagger motions have <=1 cancel key, so the obvious fix is a placebo"*, is wrong in
> both directions: there are **69** stagger motions, **all 69** have at least one cancel key, and the
> 44 that have exactly one are precisely **why the obvious fix is not a placebo**.

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| **know how long a player is actually stuck after being shoved** | `Mbinfo/bin/CancelData.bin`, joined to the exe's own 7,883-entry animation-name table at `0x148027310` and to the end-frame table on channel 3. It is not the animation length: the gate is the **first cancel key** | read-only today; editing = motion-asset route (below) | **a** — in-play staggers: first key min/median/max **0.200 / 0.450 / 4.033 s** inside a median 0.98 s motion. `stagger_upbody_0_0_090` is a 0.53 s motion cancellable at **0.267 s** |
| **make contact stick to the ball carrier** | `Stagger::vf14 0x143f00de0` routes request **kind 4 (Dribble)** to the channel-3 **animation END** whenever the motion has <=1 cancel key — which is 44 of 69 staggers. The carrier is locked for the whole animation; everybody else is not | exe code, one byte (`jne` -> `jmp` at `0x143f00efa`), **or** per-motion in CancelData | **a** — carrier stock median **1.000 s**, generic median **0.600 s**; median saving 0.333 s, worst case 0.700 s |
| **make a mistimed slide cost something** | `Sliding::vf14 0x143f70360` is `FallDown::vf14` with one compare constant changed. It answers "yes, interrupt me" from the **LAST** cancel key whenever `byte[anime+0x2bdc] != 4` — a median **1.367 s of a 1.63 s** slide, i.e. **86 %** of it; on the other branch it is the FIRST key, a median 0.800 s | exe code (3 bytes at `0x143f7037d`) — this is `falls-slide-tackle-contact.json` and it is sound | **a** for both branch medians; **c** for which branch runs, because `+0x2bdc` is unidentified (§ Open) |
| **halve the time on the floor** | `FallDown::vf14 0x143f00d00` takes the LAST key when `byte[anime+0x2bdc] != 2`; **75 of 87 `fall_*` motions have two keys**, so that branch costs a median **2.800 s** against the FIRST key's **1.400 s** (animation 3.13 s) | exe code (`0x143f00d71`), and **only useful paired with the `Dribble::vf2` table byte** — Dribble and Move are refused outright while a FallDown runs | **a** for the medians, **c** for the branch |
| **per-animation control with no exe patch at all** | 12-byte records in `Mbinfo/bin/CancelData.bin`: `idx = v & 0x1FFF`, `frame = (((v>>13) & 0x3FF) + 2) * 2` | **motion-asset** — the WESYS container is stored **verbatim** in `dt230_console_win.cpk` at one unique `0x800`-aligned offset, so an in-place byte overwrite reaches it. **The LOCATE half is solved; the PACK half is NOT** — no existing tool can produce these containers (key nibble 0, flag `0x81`, unencrypted, zopfli) and `ml_deploy.py` is hardcoded to dt200 and does use a CPK reader | **a** (located and byte-matched, read-only) — headroom is 5–19 bytes **and changes sign with the record set and the delta** (§ The write gate) |
| **heavier players and realistic turning** | dt270 `moveMatching` object `0x6b`, `RouteParameter[14]` stride 56, indexed `imul reg, idx, 0x38`. `acc`/`dec` are **multiplied**, not merely copied; `rotSpeed`, `decRotSpeed` and `accRateDif60/120/180` are compiled into a 0x3c-byte per-frame block by `0x143ec3ed0` | **dt270 data file** — no exe patch, no shared cell | **b** — live, **11 of the 14 fields read** (`accacc`, `poseWeight`, `routeWeight` have zero readers). **Global, and narrower than it looks**: nothing indexes it by player/attribute/style, `0x143ec3ed0` is pinned to element **5** by its only call site and `0x143fef370` to element **0**, and the shipped data has `rotSpeed` = 7.0 in all 14 rows and `decRotSpeed` = **0.0** in all 14 |
| **per-player weight** | **not possible from data.** The motion-matching parameters are one global dt270 blob; `PersonalizedData.bin` — the per-player individuality table — collapsed from 24,972 B in PES 2014 to **236 B** | a runtime hook on `0x143ec3ed0`'s output block is the only route | b |
| **more fouls out of more contact** | contact reaches the referee as **event kind `0xe`** on the match event bus (`match::ai::Judge 0x143c917b0`, referee handler `0x143d18570`); the payload is two player handles at `event+0x14` / `+0x20` and the **severity is computed wholly inside the referee** | referee constants (already partly ours) | **b downstream of the event; the POSTER of kind-0xe was NOT found** — so "more contact => more fouls" is unproven at the step that matters |
| **stop keepers saving like 63-rated when they are 40** | `0x144032870` picks the attribute by action id and remaps it; its consumer `0x143f31470` turns the 40..120 result into a **multiplier between 0.90 and 1.40** | exe code (inline immediates in the selector; the curve constants are pooled) | **a** — end to end, a 40-rated keeper and a 99-rated keeper differ by **9 % on an easy catch, 20–25 % on most saves, 30 % on a leg block** |
| **looser first touches, conditionally** | `trap.ballControlRate` (dt270 `trap`, **stock 1.0** — read live from both the installed and the PRISTINE dt270 pack), gating `clamp01((TightPossession_eff - 40)/59) * rate`; weak foot via `trap.ballControlWeekFootDownLimit` (20.0) | **dt270 data file** | **a/b** — at the shipped 1.0 a TP99 player's term saturates at exactly 1.0, i.e. the owner's ruling is **violated as shipped**. And the attribute is Tight Possession `0x19`, **not** Ball Control `0x18`, which has no reader in the trap family at all |
| **ricochets off non-tackling players** | **no route found from the ball side — a one-sided negative.** The ball integrator `0x14408d0f0` has a 15-function forward closure reaching no collision system, no attribute and no dt270; every dt270 bounce array has 6 ground-surface entries and no body entry. **But `collision::Human` is NOT dead** (see § First touch): it is heap-allocated per player inside `match::AnimeCollision` and attached at `AnimePlayer+0x47a8`, and that object was not followed | — | **b** — every ball/player contact *found* is initiated by a player-side action, but the player-side collision body is an open lead, not a proven absence |
| **difficulty-scale any of this** | **not possible.** 0 of 24 `AiLevelUnit::GetParam` sites, 0 of 46 `Team::GetCurrentLevel`, 0 of 20 `IsEnabled` are anywhere in the anime band | — | b — saves and first touches are identical on Beginner and Legend |
| **add a new motion** | **no.** Every MbInfo table is a fixed row count indexed by a 13-bit animation id bounded at `cmp edx,0x1ecb` = 7,883, and the CPK slot length is fixed | — | b. The 660 `enum_dummy*` reserved ids are the only conceivable hole and nothing references them (§ Open) |

---

## The machine in one paragraph

**Nothing in this layer decides what a player is trying to do; it decides what his body does about
it.** One object per player, `match::AnimePlayer`, holds an `ActionManager` at `+0xd30` in which all
113 action objects are embedded inline, plus a flat **113-entry pointer table at `ActionManager+0x1b20`**
— and the whole dispatch is `0x143eee720`: `id < 0x71 && table[id] ? table[id] : table[1]`, with
`table[1]` = `ResetIdle` as the fallback. There is no tree and no search. The current action id is a
signed byte at `AnimePlayer+0xad0` (previous at `+0xad1`), the current **motion** id is a u16 at
`AnimePlayer+0xae8`, and the transition `0x143eb4fd0(anime, newId)` calls the old handler's slot 5
(exit) then the new one's slot 3 (enter) — **171 of its 172 direct `E8` call sites are inside
`match::anime`** (re-counted for this repair; the earlier 184/185 does not reproduce by direct-call
scan, and the counting method was never stated), so
the animation layer picks its own state and reads everything else as data. Seventy-four of the
classes share a 29-slot contract whose meat is slot 4 (per-frame update, 69 distinct bodies of 74),
slot 2 (`canStart`), slot 14 (`canCancel`) and slot 13 (`wantsToStart`); the Contact family extends
it to 35 and the goalkeeper save family to 50. The seam upward is **not a call**: `match::ai::ActionMove::vf2`
(`0x145620a00`, shared by 52 `match::player` executor classes) assembles the executor's output into
**one command struct at `playerWork+0x8b8`** — action id, tag, target vec3 at `+0x20`, movement-class
ints at `+0x54`/`+0x58`, **gait at `+0x5c`**, the 0x4ec-byte compiled path embedded at `+0x68`, and a
**speed float at `+0x560`** that gait and speed are two views of (converters `0x144326290`
gait->speed `{1:5.0, 2:11.0, 3:16.0, 4:22.0, 5:28.0}` and `0x144326230` back) — and a *pointer* to
that struct is handed down as the **third argument** of the anime action contract, which is why two
call-graph closures from the executor side could never find it. `Move::vf4` (`0x143f68740`) polls two
demo take-overs and then tail-calls into `0x143ee47c0`, a 30 KB motion-matching search that reads
dt270's `moveMatching.RouteParameter[]` for acceleration, deceleration and turn rate. Everything
about *timing* — how long you are stuck after a shove, when a slide can be interrupted, when you may
start getting up — is not in the code at all: it is in a per-animation record of **21
`std::vector<Event*>` channels**, one per the 21 `Mbinfo/bin/*.bin` files the exe names, held in an
array of 7,883 records of 0x1f8 bytes at `MbInfoManager+8`, and `canCancel` is literally
`currentFrame >= keyFrame`.

---

## The 29-slot `action::` contract

Named by differencing all 74 29-slot vtables against `match::anime::action::Base` (vftable
`0x146b52860`), and by reading the callers. `Base`'s object is 0x30 bytes and carries **no action-id
field** — a class reports its own id through slot 29. [b]

| slot | name | base body | notes |
|---|---|---|---|
| 0 | destructor | per-class | — |
| **2** | **`canStart(anime)`** | `0x140c83810` (`mov al,1`) | 62 distinct impls. The eligibility layer. Contact/Stagger/FallDown/Dive share **one** body, `0x143f010b0`, indexed by `currentKind - 4` — note the base: every other class uses `currentKind - 2` |
| **3** | **`onEnter`** | `0x140c83910` (`ret`) | called on the NEW handler by the transition `0x143eb4fd0` (`call [r8+0x18]` at `0x143eb5113`) |
| **4** | **per-frame update** | — | **69 distinct impls of 74 — the meat.** `Move::vf4 0x143f68740`, `Dribble::vf4 0x143f98890`, `Contact::vf4 0x143efef70`, `Trap::vf4 0x143f86d50` |
| **5** | **`onExit`** | — | called on the OLD handler (`call [r8+0x28]` at `0x143eb5085`) |
| 6, 10, 16, **17**, 21, 27, 28 | — | `0x140c853c0` (`xor al,al`) | predicates defaulting false. **Seven slots, not six** — 17 was missed. Slot 14 (`canCancel`) has the same base body and is listed on its own row below, so `0x140c853c0` occupies eight of the 29 |
| 9 | debug name | `0x143ef5e70` | — |
| 12 | copy vec3 out | `0x143ef5ea0` (`mov rax,[rsp+0x28]; movsd xmm0,[rax]`) | a **real accessor**, not a stub. The earlier version of this table gave slot 12 the body `0x14143aec0`, which is slot 22 |
| **13** | **`wantsToStart`** | — | tail-called by the request helper `0x143e9df30` (`add rcx,0xd30; call 0x143eee720; … jmp [rdx+0x68]`) |
| **14** | **`canCancel(anime, requestedKind)`** | `0x140c853c0` (`xor al,al` — *never* cancellable) | the keyframe gate. Real bodies: `Move 0x143f68800`, `Trap 0x143f88840`, `Stagger 0x143f00de0`, `FallDown/Dive 0x143f00d00`, `Sliding 0x143f70360`, `Jostle 0x143f5d6d0`, `Block 0x143efad30`, `Dodge 0x143f19ad0`, `Tackle 0x143f7ba80` |
| 18 | per-frame body | — | dispatched by `AnimePlayer::vf1` (`call [r9+0x90]` at `0x143eb8be8`) |
| 19, 20 | — | `0x140c837d0` (`xor eax,eax`) | — |
| 22 | — | `0x14143aec0` (`xorps xmm0,xmm0; ret`) | the dead stub that was misfiled under slot 12 |
| **24** | the third motion slot | `0x143ef5ec0` | **shared by 63 of 74, overridden by 11** — and the overriders are the classes this chapter cares about: `Block 0x143efa300`, `Sliding 0x143f700d0`, `Tackle 0x143f7b5e0`, `Trap 0x143f88250`, `Kick 0x143edf150`, `Feint 0x143fa85b0`, `SeamlessThrowin`/`RecieveBall 0x143f813d0`, `SeamlessCornerKickReady`/`QuickRestartReady 0x143f09450`, `SeamlessGoalKickReady 0x140c853c0`. A patch to `0x143ef5ec0` would miss every one of them. The earlier version of this table said "one impl each across all 74" for 24 as well, which is false |
| **25 / 26** | **the shared motion machinery** | `0x143ef6190` / `0x143ef5610` | **one impl each across all 74** (and across all 97 classes with >=29 slots). These are the command-block consumers — see § The seam |

`Base` has exactly **29 methods, indices 0..28** — there is no slot 29 in this contract. The rows
below belong to the **35-slot Contact extension** and the **50-slot goalkeeper save extension**, and
were previously printed inside the 29-slot table:

| slot | name | base body | notes |
|---|---|---|---|
| **29** (Contact, 35 slots) | **`kind()`** | pure (thunk `0x144f83074`) on `Contact` itself | a literal self-report: `Stagger 0x140e35f50` = `mov eax,0x10; ret`; `FallDown 0x143eff070` = `mov eax,0x11; ret` |
| 30, 31, 33 (Contact, 35) | Contact-family extensions | — | **slot 30 is the motion SELECTOR**: `Stagger 0x143effd70` (512 ins), `FallDown 0x143effa40` (711 ins). Undecoded, and it is the other half of "players properly falling over". `Contact`'s own slot 30 is the same pure thunk as slot 29 |
| 32 (Contact, 35) | `isFinished` | `0x143f00600` (Contact/FallDown/Dive) | `Stagger::vf32 0x143f007b0` adds a Balance term |
| 29 (SavingBase, 50 slots) | **save lead time, in frames** | pure | per save type: Catch/Punch/Block 60, Deflect 90/48/60, ScoopOut 30/60, **SnapUnder 15** |

**The registry.** `0x143eee750` fills the table with 109 `lea rax,[rcx+off]; mov [rcx+0x1b20+i*8],rax`
pairs; ids `0x59`, `0x5a`, `0x6d`, `0x6e` are absent and `0x00`/`0x05`/`0x06`/`0x43` point at
sentinels. 105 of the 109 were resolved to classes by walking the constructor `0x143e9eb00` and
taking the **last** vtable store in each sub-constructor (MSVC writes the base vtable first). The
ids are in the class table below. [b]

---

## THE MOVER, and the executor -> anime seam

`player-executors.md` **OPEN 7** — *what consumes the executor's output* — **closes here, and its
framing inverts.** That chapter concluded "executors do not call the animation layer" from two
closures (592 and 528 functions) that reached zero exclusively-anime functions, and offered the
tackle's `0x143da79a0` as the only call-shaped handoff. The first half is right. The conclusion is
wrong, because **the boundary is a pointer argument, not a call**. A closure from the executor side
was structurally incapable of finding it. [b]

### The command struct at `playerWork+0x8b8`

The executor's four outputs are not four loose values. `match::ai::ActionMove::vf2` (`0x145620a00`)
— the slot-2 body 52 executor classes share — assembles them into one struct, and the "0x4ec-byte
path object at `playerWork+0x920`" is a **member of it at `+0x68`** (`0x68 + 0x4ec = 0x554`, exactly
where the next field lands). [b]

| off | field | written at |
|---|---|---|
| `+0x00` | action id | — |
| `+0x04` | tag (seeded `0x71`, resolved by `0x143da8e50`) | — |
| `+0x14` | vec (slot 20's output) | — |
| **`+0x20`** | **TARGET vec3** (x,y packed; z at `+0x28`) | `0x145620ed7 movsd [rbx+0x20],xmm0`, `0x145620edc mov [rbx+0x28],eax` |
| `+0x2c` | slot 21's output | — |
| `+0x3c` | second vec3 | — |
| `+0x50` | sub-object "MoveOrder" (`lea rcx,[rbx+0x50]`): `+0x54`, `+0x58` class ints, **`+0x5c` GAIT** | `+0x50` at `0x145620ea3`, `+0x54` at `0x145620f78` (`mov …,0`), `+0x58` at `0x145620f70`/`0x145620f7f` (`mov …,3`). **The driver never writes `+0x5c`** — gait is written by the sub-object's own setter, below; `+0x5c` is only *read* in the driver, at `0x145621115` |
| **`+0x68`** | **the 0x4ec path** (== `playerWork+0x920`) | reset/push/finalise `0x1443264a0` / `0x1443252d0` / `0x144325340` |
| `+0x554`, `+0x555`, `+0x55c` | flags ("speed was set explicitly") | — |
| **`+0x560`** | **SPEED float** (== `playerWork+0xE18`) | setter `0x1443393b0` |

Gait and speed are one quantity with two converters, and the driver seeds gait 3 (= 16.0) every
frame at `0x145620a7f` and re-derives the speed after every slot that moves it:

* `0x144326290` **gait -> speed**: `1:5.0, 2:11.0, 3:16.0, 4:22.0, 5:28.0`, else 0.0 — a five-arm
  `sub ecx,1; je` ladder, verified from PRISTINE (`0x1443262a9` loads 28.0 from `0x146a7cf1c`). [b]
* `0x144326230` **speed -> gait**: cut points 0.05 / 8.0 / 13.5 / 19.0 / 25.0. [b]

### The crossing

The struct crosses **by pointer, as argument 3** of the anime contract. The base bodies of slots 25
and 26 read that pointer at four offsets. **Correction (2026-09-20): the earlier claim that "all five
are exactly the ones the driver writes" is false for the one field that matters most.** A full
rbx-relative listing of `0x145620a00` from PRISTINE gives writes at `[rbx]`, `+0x04`, `+0x20`,
`+0x28`, `+0x3c`, `+0x44`, `+0x50`, `+0x54`, `+0x58` and `+0x554` — and **no write to `+0x5c`
anywhere in the function**. The two instructions previously cited as the proof,
`0x145620f78 mov [rbx+0x54],0` and `0x145620f7f mov [rbx+0x58],3`, say the opposite of the
annotation they carried.

**The real proof that `+0x5c` is gait** is the MoveOrder sub-object's own setters, which the driver
reaches with `lea rcx,[rbx+0x50]` at `0x14562114d` (`mov edx,[rbp+0x6f]; call 0x1443393e0`):

```
0x1443393e0  mov   [rcx+0x0c], edx        ; gait in            -> struct +0x5c
0x1443393ee  call  0x144326290            ; gait -> speed
0x1443393f3  movss [rbx+0x510], xmm0      ; speed              -> struct +0x560
0x1443393fb  mov   byte [rbx+0x50c], 1    ; "speed was derived"-> struct +0x55c

0x1443393b0  movss [rcx+0x510], xmm1      ; speed in           (the inverse)
0x1443393c4  call  0x144326230            ; speed -> gait
0x1443393c9  mov   [rbx+0x0c], eax        ; gait out
0x1443393cc  mov   byte [rbx+0x50c], 0
```

Sub-object offset `+0x0c` on a base of `+0x50` is struct `+0x5c`, and `+0x510` is struct `+0x560`.
That, not `mov [rbx+0x58],3`, is why the gait field is where this chapter says it is. The four reads
in slot 25, verified in PRISTINE:

```
0x143ef6200  movsd  xmm0, qword ptr [r8 + 0x20]   ; target x,y
0x143ef6209  mov    eax,  dword ptr [r8 + 0x28]   ; target z
0x143ef6214  mov    r15d, dword ptr [r8 + 0x54]   ; movement class
0x143ef6218  mov    r13d, dword ptr [r8 + 0x5c]   ; GAIT
```

`Contact::vf4` loads it (`mov rsi,[r8]`) and hands it to slot 26 at `0x143efefaa`; `Kick::vf4`
(`0x143ed390f`), `Stagger`/`Dive`/`FallDown::vf4`, `Injury::vf4` (`0x143fbf3be`), `OutofPlay::vf4`
(`0x143faee1f`) and `InplayDemoContact::vf4` all pass it to slot 25 or 26. [b]

On the `match::player` side the per-frame consumer is **`0x1456272c0`**: it reads id (`+0x8b8`), tag
(`+0x8bc`), target (`+0x8d8`/`+0x8e0`), gait (`+0x914`) and speed (`+0xe18`), samples the path
through `0x144326420`/`0x1443084d0`, packs a local request and calls **`0x143ec8d20`** — one of the
five dt270 `moveMatching` readers — with the `AnimePlayer` as its second argument. That is the
bridge into motion matching. [b]

### The locomotion surface — realism item 4 has a home

`Move::vf4` (`0x143f68740`) polls action ids `0x5e` (`InplayDemoFatigueInjury`) and `0x5f`
(`InplayDemoMove`) through the request helper, then tail-calls `0x143eebdf0` -> **`0x143ee47c0`**, a
0x7628-byte (30 KB) motion-matching search. `Dribble::vf4` reaches the same family through
`0x143f93b90`. Five functions read dt270 object `0x6b` = `moveMatching`, all in the anime band:
`0x143ec3ed0`, `0x143ec8b10`, `0x143ec8d20`, `0x143ec8fd0`, `0x143ec93f0`. [b]

`RouteParameter[]` is a **14-entry array of stride 56**, and the code indexes it with literally
`imul reg, idx, 0x38`. **11 of the 14 fields are read**; `acc` and `dec` are **multiplicands**, not
copies. **Offsets below are OBJECT-relative**, as `build/dt270_liveness.json` reports them (the
earlier version of this table did not say which basis it used, which matters because `+0x38` is out
of range for a 0x38-byte element). The array element base is object`+0x08`, so element-relative the
14 fields run `+0x00`..`+0x34` inside a 56-byte row, and `0x143ec3ed0` reads them as
`[rax + r8 + 0x08]`…`[rax + r8 + 0x38]` after `imul r8, rbx, 0x38`:

| field | off (object-rel) | read at |
|---|---|---|
| `acc` | `+0x08` | `0x143ec3f46 mulss xmm3,[rax+r8+8]`, `0x143ec9115`, `0x143ec959a`, `0x143fefb48`, `0x143fefe77`, `0x143ff017f` — **six sites, not two** |
| `dec` | `+0x1c` | `0x143ec3f9d`, `0x143ec8cb5`, `0x143ec8ee1`, `0x143ec911c`, `0x143ec9627` |
| `rotSpeed` | `+0x38` | copied to params`+0x20` at `0x143ec3fcd`; read `0x143ec965c`. **Shipped value is 7.0 in all 14 rows** |
| `decRotSpeed` | `+0x30` | params`+0x24` at `0x143ec3fd5`; read `0x143ec966c`. **Shipped value is 0.0 in all 14 rows** |
| `accRateDif60/120/180` | `+0x14`/`+0x0c`/`+0x10` | params`+0x30`/`+0x34`/`+0x38` at `0x143ec3fed`/`f5`/`fd`; read `0x143ec968d`/`98`/`a3` |
| `decMinSpeedA/R`, `decMaxSpeedA/R` | `+0x28`/`+0x2c`, `+0x20`/`+0x24` | two sites each (`0x143ec3fb5`/`dd`/`c5`/`e5`, `0x143ec963c`/`77`/`4c`/`82`) |
| **`accacc` `+0x18`, `poseWeight` `+0x34`, `routeWeight` `+0x3c`** | — | **NO READERS ANYWHERE.** Three dead fields. This is a second, independent reason there is no mass term: the two `*Weight` fields are not pose-matching costs that get read, they are simply inert |

`0x143ec3ed0` is the locomotion-parameter **compile**: `f(out, xmm1, routeIdx, xmm3, scale)` writes a
0x3c-byte block, stamping two **hard-coded immediates** into it — `0x143ec3f4d mov dword [rdi+0xc],0x41700000`
(= 15.0f) and `0x143ec3f5c mov dword [rdi+0x10],0x41b40000` (= 22.5f). It is reached only from
`Dribble::vf4`. **Correction 2026-09-20: neither float is a gait speed.** The verified ladder at
`0x144326290` is 1:5.0, 2:11.0, 3:**16.0**, 4:22.0, 5:28.0, so 15.0 is not gait-3 and the midpoint of
gaits 4 and 5 is 25.0, not 22.5. The earlier "cleanest single exe-constant edit in the subsystem"
verdict is **withdrawn**: no consumer of `block+0xc` / `block+0x10` has been located, and on the high
branch of the same function (`0x143ec400e comiss …; jbe skip`) both are rescaled —
`0x143ec4035 mulss xmm0,[rdi+0xc]` / `0x143ec403a mulss xmm8,[rdi+0x10]`, written back — while
`[rdi+4]` and `[rdi+8]` are **overwritten with 1.0f**, discarding the dt270-derived values on that
path. The sole caller reads only `[rbp+0x2e8]` = block`+0` after the call. Safe to edit, **effect
unquantified**. [b for the bytes; **c-inferred** for any claim that they are caps]

**The limits, stated plainly, and they are tighter than the earlier version said.** dt270 is one
global blob, and nothing in the read path indexes `RouteParameter[]` by player, by attribute or by
playing style. Worse, the 14 route classes are not all reachable through the three consuming
functions: `0x143ec3ed0` has **exactly one** call site, `0x144082f25`, and it is preceded by
`0x144082f15 mov r8d, 5` — **route index literal 5**; `0x143fef370` reads element **0** at all three
of its `acc` sites. Only `0x143ec8fd0` and `0x143ec93f0` index at runtime, and what drives that index
**was not traced**. So today the editable surface is two named elements plus one unaimed indexed
path — not 14 classes. The shipped data narrows it further: only **5 distinct rows** among the 14,
`rotSpeed` uniform at 7.0 and `decRotSpeed` **zero everywhere**, so per-route turning
differentiation does not exist in stock data and `decRotSpeed`'s consumer must be checked for the
multiply-by-zero case before it is called a lever. [a for the data, b for the code]

---

## The motion assets

### The skeleton's correction stands: they are named, not hashed

The image carries **68 distinct plaintext asset paths** under `cpk_dat/common/anime/` — re-counted
from PRISTINE for this write-up with a regex over the whole image: **exactly 68**. [a] The table
from the skeleton is unchanged and kept:

| directory | files | contents |
|---|---|---|
| `AnimeTable` | 18 | `Animetable.bin`, `CategorizedMoveTable{,Init,Status}.bin`, `DribbleMachingPivotHitInfo.bin`, `DribbleMatching.bin`, `DribbleMotionData.bin`, `FootData.bin`, `Idletable.bin`, `Kickinfo.bin`, `LoopMoveMotion.bin`, `Movetable.bin`, `NewDribbleInfo.bin`, `OOPDemoData.bin`, `Parametricblendtable.bin`, `RiseTypeFrameData.bin`, `SeamlessDemoData.bin`, `oopDemoAnime.bin` |
| `EyesTarget` | 1 | `Eyestarget.bin` |
| `FHSequence` | 6 | `Faceadd.bin`, `Facebase.bin`, `Handlbase.bin`, `Handrbase.bin`, `Hitframes.bin`, `Sequenceinfo.bin` |
| `FoxAnim` | 18 | skeletons (`body_anim_skel.ask`, `body_high_skel.ask`, `body_render_skel.ask`, `face_*`, `hand_*`), `*.frig`, `*.mtar`, `goal_l.geom`, `goal_r.geom` |
| `Matching` | 2 | `MoveMatching`, `dribbleMatching` |
| **`Mbinfo`** | **21** | `AnimationData.bin`, `BallData.bin`, `CameraPickupInfo.bin`, `CancelData.bin`, `CategoryData.bin`, `DangerData.bin`, `DemoConnectData.bin`, `FootType.bin`, `HitData.bin`, `HoldData.bin`, `JointPosInfo.bin`, `JumpData.bin`, `KickData.bin`, `NoballFootprintInfo.bin`, `NoballFrameInfo.bin`, `NoballMotionInfo.bin`, `PersonalizedData.bin`, `PivotInfo.bin`, `PivothitInfo.bin`, `RotData.bin`, `SubHitData.bin` |
| `playerID` | 2 | `Definedatatable.bin`, `Derivationdatatable.bin` |

### They are fixed-size binary records, not compiled JSON

The skeleton guessed compiled JSON from the 17 `ParsedJson*` class names. That guess was wrong, and
it is now settled from **both** ends. The PES 2014 comparison showed fixed-size structs; the exe
settles it too — the MbInfo loader is a fixed-stride record walker, with a divide-by-36 magic
multiply at `0x143e95565` and explicit 12-byte and 20-byte strides at `0x143e95e33`
(`lea rcx,[rax+rax*2]; lea rdi,[rcx*4]`) and `0x143e958d3` (`lea rcx,[rax+rax*4]`). There is no JSON
parser anywhere on this path. **The `ParsedJson*` classes belong to the `AnimeTable/` side, which is
a different loader and was not opened.** [b]

### The runtime shape: 21 channels per animation

`match::MbInfoManager` (namespace `match::`, **not** `match::anime::`) is a lazily built singleton at
`0x14868a900` (`0x143e940a0`, 1,005 callers). At `manager+8` sits an array of **7,883 records of
`0x1f8` bytes**. `0x1f8 = 21 x 0x18`: each record is **21 `std::vector<Event*>`**, channel `c`
beginning at `record + 0x18*c`. The count helper `0x143e9a390` computes
`imul rcx, rax, 0x1f8; add rcx, r9` and tail-jumps to `0x143e9a1a0`, a **21-arm switch**
(`cmp edx,0x14; ja`) whose arms are `[rcx+0x18*c+8] - [rcx+0x18*c]` then `sar rax,3`. Every accessor
bounds-checks with `cmp edx,0x1ecb` = **7,883**. [b]

**The 21 channels are the 21 `Mbinfo/bin/*.bin` paths in literal-pool order.** Read from PRISTINE at
`0x146b45470`..`0x146b458c0`, contiguous, in this order: [a]

| ch | file | ch | file | ch | file |
|---|---|---|---|---|---|
| 0 | `FootType.bin` | 7 | `DemoConnectData.bin` | 14 | `HitData.bin` |
| 1 | `BallData.bin` | 8 | `CategoryData.bin` | 15 | `SubHitData.bin` |
| 2 | `KickData.bin` | 9 | `PersonalizedData.bin` | 16 | `PivothitInfo.bin` |
| **3** | **`AnimationData.bin`** | 10 | `NoballMotionInfo.bin` | 17 | `HoldData.bin` |
| 4 | `RotData.bin` | 11 | `NoballFrameInfo.bin` | 18 | `JointPosInfo.bin` |
| **5** | **`CancelData.bin`** | 12 | `NoballFootprintInfo.bin` | 19 | `DangerData.bin` |
| 6 | `JumpData.bin` | 13 | `PivotInfo.bin` | 20 | `CameraPickupInfo.bin` |

The channel -> file binding is **[c-inferred from pool order]**, but it has two independent
corroborations, both of which would have to be coincidences: channel 5 is the one every contact
gate asks for and it decodes as cancel keys; and channel 7's getter uses a **9-bit** field, which is
exactly the width an independent data-side decode of `DemoConnectData.bin` arrived at from the
records alone. The three getters that matter are hard-coded to their offsets:
`0x143e99b70` -> `+0x48` (ch 3), `0x143e99e20` -> `+0x78` (ch 5), `0x143e9b220` -> `+0x90` (ch 6),
`0x143e9a3d0` -> `+0xa8` (ch 7). [b]

### THE DECODE RULE — three probes, three answers, one settled

This is the load-bearing number in the chapter and it was got wrong three different ways. The
game's own channel-5 getter, `0x143e99e20`, disassembled from PRISTINE for this write-up:

```
0x143e99e7b  mov     ebx, dword ptr [rax]          ; the packed u32
0x143e99e86  shr     ebx, 0xd                      ; >> 13
0x143e99ea0  divss   xmm0, [0x145a8dd84]           ; arg / 60.0   (arg defaults to the global rate)
0x143e99ea8  and     ebx, 0x3ff                    ; 10-bit field
0x143e99eae  add     ebx, 2                        ; +2 bias
0x143e99eb5  cvtdq2ps xmm1, xmm1
0x143e99eb8  addss   xmm1, xmm1                    ; x2   <-- the step two probes missed
0x143e99ebc  divss   xmm1, xmm6                    ; the caller's divisor (1.0 unless overridden)
0x143e99ec5  mulss   xmm1, xmm0
0x143e99ec9  addss   xmm1, [0x147850248]           ; +0.5
0x143e99ed1  cvttss2si eax, xmm1
```

**The rule: `idx = v & 0x1FFF` (13 bits); `frame = (((v >> 13) & 0x3FF) + 2) * 2`, in units of
1/60 s.** [b for the rule, a for the data check]

Verified against the shipped file, independently, for this chapter: `CancelData.bin` unwraps to
68,952 B = **5,746 records of 12 bytes exactly**; max index **7,872** — just under the exe's own
7,883 bound, which a 12-bit index (max 4,095) could not reach; **4,295** distinct indices; frames
4..1,160; and **no record sets any bit above bit 22**, so 13 + 10 = 23 bits accounts for the entire
word. [a]

Where the probes landed, and why each is wrong:

| reading | source | verdict |
|---|---|---|
| `frame = v >> 12`, 12-bit index, "+5 offset" | GIVEN #3 / `tools/mbinfo.py` | **the PES 2014 rule.** Under it 79 % of cancel windows fall *after* their animation ends (2,642 violations of 3,332), and the index cannot address the motion table |
| `frame = v >> 13` raw | probe 1 | right bit boundary, **but no bias and no doubling**: these are the *stored* half-frames. Its seconds are 2x too short |
| `frame = ((v>>13)&0x3FF) + 2` | probe 2 | correct field, **missed `addss xmm1,xmm1`**. 2x too short |
| `frame = (((v>>13)&0x3FF)+2) * 2` | probe 3 | **correct** — and reproduced here from the bytes and from the data |

GIVEN #3's worked example, "`frame=52 idx=878`, `frame=94 idx=878`", is really
**`fall_air_upbody_0_0_000`, cancel frames 56 and 98**.

### Everything is stored halved — and that reconciles the frame-rate argument

The doubling is not special to CancelData. Channel 3's getter reads a **u16**, masks `& 0x1FFF` and
doubles; channel 7's masks 9 bits and doubles (`0x143e9a468 addss xmm1,xmm1`, verified). So **every
MbInfo frame field is stored on a 30 fps grid and doubled on read onto the 60 Hz runtime counter.**

That settles the disagreement probe 1 honestly flagged and could not resolve: it found
`RiseTypeFrameData`'s float times quantised to exact 1/30 s multiples with 1,950 odd numerators, and
Animation.bin lengths even on 98.5 % of records, while gait timing forced 1/60 s for the counters
(`walk_1_1` = 72 frames = 1.20 s and `run_4_4` = 28 frames = 0.467 s are correct human stride cycles
at 60 fps and impossible at 30). Both are true: **authored at 30, counted at 60, stored halved.**
[a — the gait anchors reproduce from the decoded tables: `idle` 84, `walk_1_1` 72, `run_2_2` 44,
`run_3_3` 42, `run_4_4` 28, against PES 2014's 42/36/22/20/13]

Residual honesty: the *consumer* of the decoded frame (as opposed to the getter and the current-frame
function `0x143ea9040`, which returns `R * t` in the same unit) was never located, and the getters'
`mulss` by `R/60` means everything scales with a runtime global at `0x148c22abc` that is zero on
disk. Gate and key are in the same unit, so **every ratio in this chapter is exact**; the conversion
to seconds assumes `R = 60`. [b / c]

### The end-frame table is `AnimationData.bin`, not `Animation.bin`

Channel 3 carries the per-animation END frame: `movzx ebx, word ptr [rax]; and bx,0x1fff`, then
`x2`, with the **index in the high bits** (`v >> 13`) rather than the low ones — a different pack
order from CancelData, which is exactly the trap the brief warned about. `AnimationData.bin` is
36 B x **7,073** and its path **is** one of the exe's 68. [a/b]

`Animation.bin` (36 B x 4,345) is a different file, its path appears **zero** times in the image
(verified), and an exhaustive field scan found nothing in `AnimationData.bin` correlating with its
length field. The two agree on every gait anchor, so the lengths quoted here are right either way —
but **read `AnimationData.bin`; `Animation.bin` looks legacy.** [a]

### The index -> name table

`0x148027310`: **7,883 consecutive qword pointers**, one per motion id, in motion-id order, every
string distinct. Found by scanning PRISTINE for the longest run of pointers into the animation-name
pool (next longest run: 2,972). Two further tables exist — `0x148036a60` (646 face/add names) and
`0x14806b750` (2,972 aux names); the PES chapter's "11,096 names" conflates all three, and the body
id space the MbInfo tables use is **7,883**. [a]

Two call sites prove the use directly: `0x143eb6e48 lea rax,[rip -> 0x148027310]; mov r8,[rax+rdi*8]`
feeding `"Reserve SetLyaer: %s m(%d), duration(%.2f) layerMaskType(%d)\n"`, and `0x143fc373c` the
same with `"connect=%d anime=%s\n"`. `0x143b8450c` loads `mov edi,0x1ecb` immediately before the
table address. [b]

Three independent proofs that **position is the id**: `EyesTarget/bin/Eyestarget.bin` is 31,532 B =
**exactly 7,883 u32s**; the 660 `enum_dummy*` placeholder slots (8.37 % of the table) are hit
**zero** times in 7,272 records across CancelData, HoldData, KickData, JumpData, DemoConnectData and
DangerData where chance predicts ~608; and the semantics land (`HoldData`, the hand-gripping table,
is dominated by `gkcatch` 69, `gkblockcover` 21, `gkprejump` 14). A fourth, found in the code:
`Stagger::vf14`'s hard-coded motion ids 3255 and 3259 resolve to `stagger_upbody_3_3_090_pulled` and
`stagger_upbody_4_4_090_pulled` — **the two shirt-pull staggers**, in the one branch that lets a
kick start during a stagger. [a]

Artefacts: `build/anime_names.json` (7,883 names in id order), `build/anime_motion_tables.json`
(7,061 motions with name + end frame + cancel frames), regenerator `tools/anime_motion_tables.py`,
plus `tools/data/ef_anime_names.json` and `tools/mbinfo_ef.py` (`lockout`, `cancel --grep`,
`connect --grep`). `tools/mbinfo.py` is left untouched and **remains correct for PES 2014 only** —
its eFootball `cancel` output is garbage and it must not be used for this game.

### Record sizes, solved and unsolved

Solved by a test a wrong answer cannot pass — **zero `enum_dummy` hits and zero key re-appearances
after a run ends** (the second condition is required because the loader counts *consecutive* equal
keys): `AnimationData` 36 (id at bits 13..25), `CancelData` 12, `HoldData` 20, `DangerData` 20,
`DemoConnectData` 4, `JumpData` 4, `KickData` 4, `CategoryData` 4, `BallData` 20, `Eyestarget` 4,
`Risetypeframedata` 12, `Risetypedata` 12, plus the AnimeTable copies. [a]

**`HitData.bin` is NOT solved.** At 1,061,316 B it is the largest contact table (5.6x PES 2014) and
no divisor from 4 to 80 under four key extractions produces a grouped, dummy-free key; at 36 B it
gives 24,819 key re-appearances and a 3.24 % dummy rate. It is the IK ball-contact geometry and it is
the remaining piece of "contact is warped onto the real ball rather than snapping it". Not guessed at.

One container gotcha: `MatchAnimeDefinedatatable.bin` is **not broken** — it is WESYS **stored**, not
WESYS+zlib. The third magic byte is a compression flag: `0x81` = zlib (93 files in the tree), `0x00`
= stored (this one, `csize == dsize == 132`). A zlib-only unwrap mislabels it. [a]

### THE DECOY — `dt230` ships two `CancelData.bin`

`AnimeTable/bin/CancelData.bin` holds the same animations with the same float lanes and **every
decoded frame +4** — the *stored* 10-bit field is +2, and every MbInfo frame field is doubled on
read, so the delta in seconds is 0.067 s, not 0.033 s (exactly +2 stored on 4,259 of 4,753 matched
keys; 2,839 pairs byte-identical in the float lanes; an independent re-decode for this repair gives
+4 frames on 4,273 of 5,249 matched keys, the spread coming from how repeated frames within an index
are paired). This is the one place the chapter compares two files and it is the one place the
doubling was forgotten. It is **not one of the 68 paths the exe names** — the byte string
`AnimeTable/bin/CancelData` appears **zero** times in the image, verified. Eleven more AnimeTable
files are in the same category (`DemoConnectData`, `KickData`, `CategoryData`, `JumpData`,
`RotData`, `BallData`, `AnimationData`, `PersonalizedData`, `FootType`, `PivotInfo`,
`NoballFrameInfo`). **Editing one of them changes nothing and reads as a failed experiment.** Edit
`Mbinfo/bin/CancelData.bin`. [a]

### The write gate

**The LOCATE half is solved; the PACK half is not.** Each WESYS container is stored **verbatim** in
`dt230_console_win.cpk` at a unique `0x800`-aligned offset. Verified read-only for this chapter and
re-verified for this repair: `Mbinfo/bin/CancelData.bin` (61,449 B on disk = 16 + csize 61,433)
occurs at **`0xb5bf800`, exactly once**, full byte match, `0x800`-aligned; the archive holds **128**
WESYS containers, all `0x800`-aligned. Four more were located the same way by probe 1:
`HoldData @0xb670000`, `DemoConnectData @0xb5d2800`, `Risetypeframedata @0xa72000`,
`Animation @0xb56e000`. So **the overwrite step is sound**. [a]

**Correction 2026-09-20: "`ml_deploy.py`'s existing path reaches it; no general CPK reader is
required" was wrong on both halves.** `ml_deploy.py` does `from cricodecs import cpk` and calls
`cpk.load()` for the blob and the alignment check, and it hardcodes
`ARCHIVE_PATH = "common/etc/pesdb/PlayerAssignment.bin"` with `--base dt200_console_all.cpk`. And
the project's proven WESYS packer **cannot produce these containers at all** — three named blockers
this chapter previously omitted: [a/b, from the tool source and the shipped bytes]

1. **Key nibble.** `tools/vendor/sider/wesys.py` has `CURRENT_WESYS_KEYS = {1: …, 2: …}` and
   `pack_wesys_container` raises `WesysError` for anything else. All **128** dt230 containers have
   byte[1] = `0x20` -> **nibble 0**, which is unsupported.
2. **Flag byte and encryption.** The packer always writes flag `0x83` and always encrypts. The
   shipped dt230 containers are **`0x81` and plain** (127 of 128; the 128th is `0x00`, stored) —
   `zlib.decompress(blob[16:16+csize])` succeeds directly on every one.
3. **Compression.** The packer takes only a zlib level. On this payload level 1 gives **61,992**
   (559 over the slot), level 6 **61,543**, level 9 **61,542**. The proven `ml_deploy.py` level-1
   trick does **not** transfer to dt230; zopfli is required.

A writer for this route is new code: nibble 0, flag `0x81`, no encryption, zopfli.

**The second blocker is compression.** The CPK slot length is fixed, so the edited
container must be byte-for-byte the same total length — and **Konami's deflate beats stock zlib**.
Measured here on the *unedited* payload: shipped `csize` **61,433**; `zlib.compress(payload, 9)`
**61,542** (109 bytes OVER); `zopfli.zlib.compress(payload, numiterations=15)` **61,414** (19 under).
So the repack must use zopfli, and the headroom is single digits to low double digits and depends on
the edit — and on the delta:

**Correction 2026-09-20 — the deltas in this table were mislabelled by a factor of two, and it flips
one verdict.** The earlier rows applied `+6` to the **stored** 10-bit field, which under this
chapter's own verified rule `frame = (stored+2)*2` is **+12 frames**, not +6. Re-measured for this
repair, both deltas, with the record set stated explicitly (zopfli `numiterations=15`, slot = 61,433):

| edit | records | frames | zopfli size | headroom |
|---|---|---|---|---|
| unedited CancelData | — | — | 61,414 | +19 |
| stagger (`stagger_*`) | 98 | **+12** | 61,421 | **+12 (fits)** |
| stagger (`stagger_*`) | 98 | **+6** | 61,422 | **+11 (fits)** |
| contact family `stagger\|tackle\|sliding\|fall_\|dodge\|js_` | 723 | **+12** | 61,425 | **+8 (fits)** |
| contact family, same set | 723 | **+6** | 61,446 | **-13 (DOES NOT FIT)** |
| narrow set `stagger\|tackle\|sliding\|fall_` | 490 | **+12** | 61,427 | +6 (fits) |
| narrow set, same | 490 | **+6** | 61,441 | **-8 (does not fit)** |
| `Risetypeframedata`, all times +0.1 s | all | — | 15,098 | +5 (fits) |
| `Risetypeframedata`, 1 time in 20 +0.1 s | — | — | — | **-36 (does not fit)** |
| `Animation.bin`, length +10 on 69 staggers | 69 | — | 118,120 | **-12 (does not fit)** |

Two lessons, one of them new. Partial edits compress *worse* than uniform ones — counter-intuitive,
and exactly why the tool must **measure and refuse** rather than assume. And **a uniform +12 frames
compresses better than a uniform +6**: the bigger edit fits where the smaller one overflows, because
+12 in frames is +6 in the stored field and that keeps more of the byte histogram intact. The margin
also **changes sign with the record set**, so a tool must be told which prefixes it is moving. [a]

**The residual untested question is narrower than the earlier version claimed, and the plan does not
rest on it.** There are two ways to handle a shorter compressed stream, and the safe one is entirely
under the tool's control: **lower the header's `csize` to the true stream length and leave the CPK
slot padded** — the header is fixed-size (16 B: `ff 20 81` + `WESYS` + u32 csize + u32 dsize), so
not one byte moves and the reader hands inflate exactly `csize` bytes and never sees the tail. The
one thing that is genuinely untested is whether anything cross-checks `csize + 16` against the CPK
entry size. The alternative — leaving trailing bytes *inside* the declared stream — has **no
precedent in the shipped data**: all 128 dt230 containers decode with `zlib.decompressobj()` leaving
**0** `unused_data`, i.e. every shipped `csize` is exact. Avoid it. [a]

---

## The post-contact lockout, in seconds

All figures recomputed for this chapter from `build/anime_motion_tables.json` under the verified
decode rule, at 60 fps. "first" is the first cancel key, "last" the last. [a]

| family | motions | key counts | end (median) | first key min/med/max | last key median |
|---|---|---|---|---|---|
| `stagger_*` | **69** | **all 69 have >=1**: 44 one, 21 two, 4 three | 1.07 s | **0.200 / 0.600 / 4.033 s** | 0.733 s |
| `stagger_upbody_*` + `stagger_lowbody_*` (in play) | 46 | — | 0.98 s | **0.200 / 0.450 / 4.033 s** | — |
| `tackle*` | 117 | 92 one, 23 two, 2 three | 1.07 s | 0.267 / **0.667** / 1.400 s | 0.733 s |
| `sliding*` | 33 | **30 of 33 have two** | 1.63 s | 0.200 / 0.800 / 1.700 s | **1.367 s (86 % of the slide)** |
| `fall_*` | 87 | **75 of 87 have two** | 3.13 s | 0.533 / **1.400** / 5.400 s | **2.800 s** |
| `js_*` (jostle) | 223 | **51 have none at all** | 1.00 s | 0.133 / 0.600 / 1.867 s | 0.700 s |
| `block*` | 116 | 104 one | 1.00 s | 0.433 / 0.683 / 3.667 s | 0.700 s |
| `dodge*` | 16 | all one | 0.87 s | 0.400 / 0.600 / 0.867 s | — |
| `trap_*` / `traprun_*` | 147 / 158 | 137 / 119 one | 0.73 / 0.87 s | 0.333 / 0.500 / 0.900 s | — |
| `kick_*` | 621 | 602 exactly one | 1.10 s | 0.300 / 0.733 / 4.200 s | — |
| `rise*` / `gkrise*` | 18 / 100 | 17 of 18 two | 1.00 / 1.38 s | 0.333 / 0.633 / 1.000 s | 0.833 s |
| `dm_injury_*` | 10 | **zero keys, all of them** | 0.03–5.50 s | — | — |

Worked examples, with names, so the effect size is not a guess:

* `stagger_upbody_0_0_090` — end **32 fr (0.53 s)**, one cancel key at **16 fr (0.267 s)**.
* `stagger_upbody_3_3_090` — end 64, keys **20, 32, 48**.
* `stagger_lowbody_3_3_000` — end 60, keys **16, 36, 44**.
* `stagger_upbody_3_3_090_pulled` (the shirt pull) — end 28, one key at 16.
* `sliding_0_0_000` — end 104, keys **44, 88**: stock the slider cannot be knocked over until
  frame 88 of 104.
* `fall_lowbody_0_0_000` — end 174, keys **72, 156**.
* `fall_air_upbody_0_0_000` — keys **56, 98** (GIVEN #3's mis-decoded example).

**The no-key default is frame 4, not 0.** An out-of-range event index returns a static zero global
(`0x143e99e6b lea rax,[0x14868add8]`), and `((0 & 0x3FF) + 2) * 2 = 4`. This matters: `Stagger::vf14`
ends `cmp esi,eax; jg refuse; test esi,esi; cmovg edi,1`, so a **keyless** motion returns *true from
frame 4*, not "locked forever". Any spec premised on "keyless = permanent lock" is wrong on both
halves. [a/b]

---

## Contact, stagger and falling

### Two layers, and the eligibility layer is the bigger lock

Getting through a stagger needs **two** yeses: the incoming action's `canStart` (slot 2) must not
refuse outright, and then the *current* action's `canCancel` (slot 14) must say the keyframe has
passed. Almost every "why can't I react" complaint is the first, not the second.

`Contact`, `Stagger`, `FallDown` and `Dive` share **one** `canStart`, `0x143f010b0`, indexed by
`currentKind - 4` (note the base — every other class uses `- 2`), through a 5-entry jump table at
`0x143f011f8` with case-index bytes at `0x143f0120c`: [b]

| current state | case | meaning |
|---|---|---|
| kind 4 (Dribble) | 0 | **ALLOW outright** — a dribbling player can always be hit |
| kinds 8,9,0xa,0xb,0xc,0xe,0x44–0x46,0x48,0x49 | 1 | delegate to that class's own gate |
| **kind 0xf (Dive) / 0x11 (FallDown)** | **2** | **REFUSE.** Once you are on the floor, no further contact of any kind reaches you |
| **kind 0x10 (Stagger)** | 3 | `mov rax,[r14]; call [rax+0xe8]` — asks the INCOMING action its own kind via slot 29 and **allows only `0x11` (FallDown)**. You cannot be staggered twice, but you *can* be put down out of a stagger |
| 55 other kinds | 4 | two property-bit gates |

There is a **global per-action-kind property table at `0x146c14e80`**, 113 x u32, read through ~23
one-bit accessors in `0x144311c00`..`0x144312400`; e.g. `0x1443120f0` is bit 9
(`shr eax,9; and al,1`, kinds `0x44`–`0x49` and `0x51`) and `0x144311e40` is bit 16 (kinds 8, 9,
0xa). Both appear in `Stagger::vf14`'s routing. [a]

### `Stagger::vf14` — the gate in full, and why the carrier is the victim

Verified from PRISTINE, and **expanded for the 2026-09-20 repair**: the earlier version of this block
opened at `cmp r14d,4` and was labelled "the whole gate", which it is not. `cmp r14d,4` is only
reached when a property-bit test on the *requested* kind fails, and the block also dropped
`mov r14d, eax`, without which `lea r9d,[r14-1]` reads as the constant 3 rather than count-1. The
full control flow:

```
                                          ; esi = channel-5 key 0 (FIRST cancel key)
                                          ; r15d = channel-3 key 0 (animation END)
0x143f00e5e  call  0x1443120f0            ; property BIT 9 of the REQUESTED kind
0x143f00e63  test  al, al
0x143f00e65  je    0x143f00ef6            ; bit clear -> the kind-4 arm, below
  ; --- bit-9 arm (kinds 0x44-0x49, 0x51) ---
0x143f00e74  sub   ecx, 0x805             ; motion id 0x805 / 0x806 / 0x807 ?
0x143f00e86  mov   r8d, 6                 ;   -> CHANNEL 6 (JumpData) key replaces esi
0x143f00e9f  call  0x143e9b220
0x143f00eb8  mov   esi, eax
  ; --- the kind-4 (Dribble) arm ---
0x143f00ef6  cmp   r14d, 4                ; requested kind == 4 (Dribble)?
0x143f00efa  jne   0x143f00f40            ; no -> bit-16 test, then generic path (esi = FIRST key)
0x143f00f03  lea   r8d, [r14 + 1]         ; channel 5  (note: NOT 'mov r8d,5')
0x143f00f0a  call  0x143e9a390            ; how many cancel keys?
0x143f00f0f  mov   r14d, eax              ; <-- the count, which the earlier excerpt dropped
0x143f00f12  mov   esi, r15d              ; <-- default to the animation END
0x143f00f15  cmp   eax, 1
0x143f00f18  jle   0x143f00eba            ; <=1 key -> KEEP THE END
0x143f00f26  lea   r9d, [r14 - 1]         ; else take the LAST key (count-1)
  ; --- the generic tail ---
0x143f00f40  mov   ecx, r14d  /  call 0x144311e40   ; property BIT 16 (kinds 8, 9, 0xa = Kick)
0x143f00f4a  je    0x143f00eba                      ; bit clear -> generic FIRST-key path
0x143f00f57  mov   ecx, 0xcb7 / sub ax,cx / test cx,ax  ; bit set -> only motions 3255 / 3259
0x143f00eba  call  0x143ea9040            ; current frame
0x143f00ec2  cmp   esi, eax  /  jg refuse
0x143f00ec6  test  esi, esi  /  cmovg edi, 1   ; return (key <= now) && (key > 0)
```

The one-byte fix at `0x143f00efa` (`75 44` -> `EB 44`) lands on the bit-16 test, which does not
select kind 4 either, so it reaches the generic FIRST-key path as intended.

**44 of 69 stagger motions have exactly one cancel key, so for the ball carrier the gate is the end
of the animation.** Measured: carrier stock median **1.000 s** vs generic **0.600 s** — a median
**0.333 s** and worst case **0.700 s** of extra helplessness that only the man on the ball suffers.
That is the mechanism behind "you get bullied off the ball and then stand there". [a]

The `lea r8d,[r14+1]` form is worth noting on its own: a pattern search for `mov r8d, 5` finds
nothing here. This is the encoding trap the brief warns about, live.

### `FallDown::vf14` and `Sliding::vf14` are the same function

`FallDown::vf14` (`0x143f00d00`) has the same shape but is **kind-blind**: FIRST key when
`byte[anime+0x2bdc] == 2`, LAST key otherwise — and it has **no `key > 0` guard**. `Sliding::vf14`
(`0x143f70360`) is byte-for-byte the same with the compare constant **4** instead of 2
(`0x143f703ca` vs `0x143f00d6a`); a byte compare over 0xC0 bytes gives that immediate as the only
non-relocation difference. A fix to one is a fix to the other's shape. [b]

**Which key you get is a RUNTIME decision, not a property of the motion — state it that way.**
`0x143f00d6a cmp byte [rbx+0x2bdc], 2` / `jne`: **equal** takes `xor r9d,r9d` = index 0 = the FIRST
key; **not equal** takes `lea r9d,[rbp-1]` = count-1 = the LAST key. `Sliding::vf14` is the same
bytes with the immediate `4` (`0x143f703ca`). `+0x2bdc` is **not identified** (see § Open), so
"stock the gate is the LAST key" is an assumption about an unknown byte, and both branches must be
quoted:

| class | FIRST-key branch (byte == 2 / 4) | LAST-key branch (otherwise) |
|---|---|---|
| `Sliding` (33 motions, 30 with two keys, median end 1.63 s) | median **0.800 s** | median **1.367 s** = 86 % of the slide |
| `FallDown` (87 `fall_*`, 75 with two keys, median end 3.13 s) | median **1.400 s** | median **2.800 s** |

So the honest statement of the slide lever is: **if** `byte[anime+0x2bdc] != 4` at the moment of the
query, the tackler is untouchable for a median 86 % of his own slide, and
`falls-slide-tackle-contact.json` removes that veto. On the other branch it removes a 0.800 s one.
Likewise "75 of 87 fall_* motions use the LAST key" conflated the gate choice with the count of
motions that happen to have two keys: what is true is that **75 of 87 have two keys, so the LAST-key
branch costs a median 1.400 s more than the FIRST-key branch**. The 86 % / 2.800 s figures are
**[a] measurements of the branch, [c] as descriptions of what the game does at runtime.**

### Injury is not tunable

`Injury` is **not** a Contact subclass (bases `InjuryRetryWork < Base`, 29 slots), its `vf14` is the
shared `xor al,al; ret` stub, and **all ten `dm_injury_*` motions carry zero cancel keys**. An injury
animation runs to completion by construction and there is nothing here to tune. The same stub is
`Reaction::vf14`, `ComeBack::vf14`, `CarryBall::vf14` and base `Contact::vf14` — none of those can
ever be interrupted once started. Note the consequence for
`contact-fight-back-from-stagger.json`: its Reaction row buys eligibility for an action that, once
running, nothing can stop. [b]

### The fall -> get-up chain

`DemoConnectData.bin` (channel 7) is **4-byte** records: `{id:13, connect_frame:9 at bits 13..21,
end_state at bits 22+}`, and — per the getter — the connect frame is **doubled on read** like every
other. Its `end_state` histogram reproduces PES 2014's fourteen-posture enum shape
(eFootball `{7:772, 2:105, 4:91, 3:47, 12:16, 5:6, 11:2, 0:2}` against PES's JSON ground truth
`{7:561, 12:145, 3:10, 2:8, 4:7, 1:6, 0:3}`), and `connect_frame <= animation length` on 879 of 984
records. So `fall_lowbody_0_0_000` hands off to the get-up partway through its 174-frame fall in
posture 2, and `fall_lowbody_0_0_000_allfours` later, in posture 4. **The fall's cancel keys and its
connect frame must move together** or the player cancels out of the fall before the get-up connects.
[a]

`AnimeTable/bin/Risetypeframedata.bin` is 12-byte `{u32 packed, f32, f32}` where **both floats are
times in seconds** on a 1/30 grid — directly readable and directly editable. But **its key field is
not solved**: 69 of 2,565 keys (2.7 %) land on `enum_dummy` placeholder slots where the correct key
gives zero, and no bias in -3..+5 cleans it up. Do not target individual animations in it yet. [a]

### Fouls: the animation layer reports, the referee decides

Contact reaches the referee as an **event on the match event bus**. `match::MatchControl::vf1`
(`0x143c56a90`) passes events to `match::ai::Judge` (`0x143c917b0`), which switches on `dword[event+0]`
across 0..0x22; the referee's own handler `0x143d18570` switches the same kind. **Kind `0xe` is the
foul-candidate contact event**, and its entire payload is two player handles at `event+0x14` and
`event+0x20`, resolved to slot indices by `0x1442df590` and handed to the scorer `0x143d88fe0`,
which stores them at `referee+0xa8`/`+0xa4` and reads the players' own records. **No
animation-supplied severity is passed.** The level function `0x143d861f0` is
`threshold = inBox ? 60 : 40` (ours: 36 outside), no foul below it, 1 or 2 below 80, yellow 80..109,
red >=110. [b]

**What could not be proven: who posts a kind-0xe event.** A constant scan for `mov dword[..],0xe` in
the match band returns 67 functions, so 0xe is far too common to triangulate that way. Consequence,
stated plainly: opening the cancel gates changes what happens *after* a contact; **whether it causes
more contacts, and therefore more fouls, is not shown.**

---

## The goalkeeper save family

Long form in [anime-keeper-and-first-touch.md](anime-keeper-and-first-touch.md); the load-bearing
result in brief. The family is **15 classes**, not the 14 the class inventory has said since the
skeleton (`SavingBase` + 6 saves + `AfterCatchBase` + `PuntKick` + `Throw` + `SeeOff` + `DropBall` +
`PickupBall` + `BodyFeint` + `PreSaving`). Seven of them carry the 50-slot contract. [b]

**The action-id binding is proved, not paired by attribute.** Each save's constructor passes a
compile-time id to `SavingBase::SavingBase` (`0x143f2ec90`), which stores it at `saving+0x30`:
Catch `0x44` (`0x143f4a7c0`), Punch `0x45`, Deflect `0x46`, SnapUnder `0x47`, ScoopOut `0x48`,
Block `0x49`. The save-quality selector reads it straight back from `[rcx+0x30]`. [b]

**`0x144032870`, emulated end to end** (`tools/emu_gk_save_quality.py`, the game's own bytes under
Unicorn): pick an attribute by action id, remap it, scale everything under 90 by 0.98, halve
anything over 100, add +5 only when a player flag **and** a situation byte are both set, clamp to
40..120.

| id | attribute | remap | effective range | per-point gain 40->99 |
|---|---|---|---|---|
| `0x44` Catch, `0x47` SnapUnder | GK Catching `0x23` | raw | 40..99 | +59 |
| `0x45` Punch | GK Parrying `0x24` | raw | 40..99 | +59 |
| `0x46` Deflect, sub in {1,4,5} | GK Reflexes `0x25` | `(r-40)/2 + 65` over 40..90 | **63..99** | +36 |
| `0x46` other subs, `0x48` ScoopOut | GK Reach `0x26` | `3(r-40)/4 + 52` over 40..90 | **50..99** | +49 |
| `0x49` Block | GK Reach `0x26` | **raw** | 40..99 | +59 |
| `0x44` with ball < 50 km/h | **max**(Catching, Reflexes, Reach) | 40..90 -> 73..89 | 73..89 | +26 |

**The missing half, which `player-executors.md` stops short of:** the consumer is `0x143f31470`, and
it turns that 40..120 integer into a multiplier. Block -> `1.00 + 0.40t`; Catch -> `0.95 + 0.30t`;
Deflect sub 1 -> `0.90 + 0.32t'`; everything else -> `0.90 + 0.30t`, with `t = clamp01((q-40)/80)`
and `t' = clamp01((q-20)/110)`. **The entire goalkeeping-attribute system, end to end, is a
multiplier between 0.90 and 1.40.** A 40-rated keeper and a 99-rated keeper differ by 9 % on an easy
catch, 10 % on a diving parry, 20–25 % on most saves, 30 % on a leg block. [a]

**For `master.db` editing**, three traps: (1) attributes above 90 **bypass the remap**
(`lea ecx,[rbx-0x28]; cmp ecx,0x32; ja` — an unsigned test), so GK Reach 90 gives 87 but 91 gives 91;
keep Reflexes and Reach at or below 90 for a smooth roster. (2) On any ball under 50 km/h the game
takes the **max** of all three shot-stopping attributes, so a single-attribute nerf is invisible.
(3) GK Reach is compressed on Deflect/ScoopOut and linear on Block — the same attribute behaves
differently per save. [a]

**Randomness: essentially none.** Zero RNG call sites inside any of the 114 `goal_keeper::` method
bodies. A depth-bounded BFS from `vf4`+`vf13` reaches exactly one RNG at depth 3, through
`0x143f46370` -> `0x143ea9260` = `RandInt(player+0x3bb4, stream 2) % N`, used three times for a
**centimetre-scale** offset on the save target (up to -0.09 m, up to -0.04 m on a Deflect, a 0.20 m
span on a third branch). **No dice roll decides save-versus-goal.** [b]

**Two dead terms.** `Deflect::vf37` (`0x143f4ad50`) and `SnapUnder::vf37` (`0x143f4fb50`) begin
`movss xmm2,[rsp+0x28]; xorps xmm0,xmm0; mulss xmm2,xmm0` — the float argument is multiplied by a
freshly-zeroed register and the comparison degenerates. Contrast `Punch::vf37` (x1.5) and
`ScoopOut::vf37` (x-0.5), which use real constants. A hook on slot 37 to tune parrying would be
tuning nothing on two of the six saves. This is the brief's "read is not effective" gotcha, live.
[b]

`Stagger::vf32`'s Balance term has the same disease: it reads attribute `0x2a` **twice**, and the
second read (`0x143f00b29`, ramp 99 -> 120, divisor 21.0) sits behind
`movss xmm1, 99.0; comiss xmm1,xmm0; jae skip` — **unreachable for any player on the 40..99 scale**.
Also note the first term's upper knee is **100, not 99** as the spec files state, and the divisor is
`xmm7 = 60.0` loaded at `0x143f00a3a`. [b]

---

## First touch, and whether loose balls are contested off non-tacklers

**Ball Control (`0x18`, `DATA_PARAMETER_TRAP`) is not the first-touch attribute**, despite the name.
All 25 of its read sites image-wide are in the dribble/carry band and **not one is in the trap
family**. The trap family reads **Tight Possession (`0x19`, `BALL_TOUCH`)** — `Trap::vf22`
`0x143f876a6`, `Trap::vf19` `0x143f87851`, the four trap-info builders `0x143f83522`/`0x143f83b32`/
`0x143f8414c`/`0x143f845ac`. [b]

The owner's `ballControlRate` is **`trap.ballControlRate`**: dt270 object `trap`
(`DevelopData/common/match/constant/player/trap.json`), float, three `mulss` readers
(`0x144079c38`, `0x144079dc3`, `0x14407aab5`), all under `Trap::vf4`.

> **CORRECTION 2026-09-20, and it inverts the ruling's answer. Stock is `1.0`, not `0.80`.**
> `python tools/dt270_objects.py get trap ballControlRate` returns **1** against the installed
> `dt270_console_all.cpk` *and* against `Backups/eFootball/dt270_console_all.PRISTINE.cpk` (two
> files, different sha256). `gameplay_tune diff` reports 7 differing params, **all `basePosition.*`**
> — no `trap.*` — so installed == pristine for this field. The `0.80` came from a stale
> `build/dt270_json/constant_player/trap.json` dump (mtime Aug 23, an older dt270 patch family).
> `0.80` is **our own** value: `tools/data/tunings/loose-realism-v1.json` contains verbatim
> `{"object":"trap","path":"ballControlRate","value":0.8,"was":1}` — it records stock as 1. This is
> the exact error class the brief warns about, and this chapter committed it. **Never read a dt270
> value from `build/dt270_json/`; read it from the installed pack.** [a]
>
> Field addressing: `build/dt270_liveness.json` gives `soff` **56**, which is the runtime struct
> offset the readers use (`mulss xmm12, [rax+0x38]`, `0x38` = 56). `tools/data/dt270_schema.json`
> gives `off` **16** for the same field — a *different basis* (the object's top-level 4-byte-stride
> field table, where offset 56 is `reactionTrapBall`). Quote the field by **name** and set it with
> `dt270_objects.py`; if you must use a number, say which basis it is on. [a]

The term is `clamp01((TightPossession_eff - 40) / 59) * ballControlRate`, where
`TightPossession_eff` is TP (+6 on a ball condition) minus a weak-foot reduction that returns 0 on
the strong foot. **At the shipped rate of 1.0 a TP99 player's term is exactly 1.0 — the saturation
the owner's ruling forbids is what the game ships.** So the lever is to **lower** this one field,
not to protect it; 0.80 and 0.65 are the values this project has already tried, and
`docs/realism-todo.md` argues (correctly) for "below 1.0, because at exactly 1.0 a BC99 player is
mathematically incapable of a bad touch". On the *contested* branch the same function scores from
**Aggression (`0x1f`)** instead. The weak-foot cap (`0x144079020`) reads Stronger Foot `0x35` and
Weak Foot Accuracy `0x27`, scaled by `trap.ballControlWeekFootDownLimit` = **20.0** (value confirmed
against the installed pack). [a/b]

The trap **candidate builder** is `0x143f834b0`, which passes Tight Possession as an int into
`0x143f87ad0` and constructs `CTrapAnimeInfo` x4, `CFastTrapAnimeInfo`, `CCancelTrapAnimeInfo`,
`CStaggerAnimeInfo` and `CTrapAnimePlayer` x2. It is also the function that reaches
`match::MbInfoManager` — the link from the trap code to the motion tables. `CTrapAnimePlayer` has
**one slot** and no behaviour: it is a data holder, and anyone looking for trap logic in it will find
none. **What this does NOT show is selection**: nothing here scores or compares the eight
`CTrap*AnimeInfo` variants, so "how is a trap type chosen" is unanswered — it is now Open item 22.
[b]

**Ricochets: a ONE-SIDED negative, not a settled one. Corrected 2026-09-20.** Two of the three legs
hold. The ball's own integrator `0x14408d0f0` (49 call sites, re-counted) has a forward closure of
**15 functions** and reaches no attribute getter, no collision system, no RNG and no dt270 read.
Every dt270 ball bounce array has exactly **6** entries, all read in that one function, and all are
ground-surface variants with no body entry (`boundRate = [0.77, 0.77, 0.77, 0.55, 0.77, 0.77]`).
`0x144fa58d0` is a ragdoll physics-group setter called from `Human::vf9`/`Player::vf9`, not a ball
query.

**The third leg fails outright.** "`collision::Human` (vftable `0x147484f80`) has zero callers
image-wide, and so does its constructor" is **false**, and a headline negative was resting on an
xref that had not been run. What the bytes say (controls on the same scan: the name table
`0x148027310` = 12 rip-relative referrers including the two this chapter cites;
`match::anime::action::Jostle` vft `0x146b4a3b8` = 5 including `0x143e9f657`; direct-call controls
`0x143e940a0` = **1,005** and `0x14408d0f0` = **49**, both exactly as this chapter states elsewhere):

* vftable `0x147484f80` has two code referrers, `0x1451305f3` and `0x145130640` — the ctor/dtor pair.
* `0x1451305f0` **is** the constructor (`lea rax,[rip+0x2354989]; mov [rcx+8],edx; mov [rcx],rax;
  … mov [rcx+0xc],r8d; ret`) and it has **one** direct caller, `0x143ff224d`.
* Its containing function `0x143ff2210` is a **factory**: it stamps vftable `0x146b6fb48` =
  **`match::AnimeCollision`** (a `match::`-namespace class this chapter did not list), does
  `mov ecx,0x28; call 0x140e999a0` (operator new, 0x28 bytes), calls the ctor, and stores the result
  at `[this+8]`.
* `0x143ff2210` has **three** call sites: `0x14410ba5d`, `0x14410bb37`, `0x14410bbe7`. At
  `0x14410ba3d..0x14410bac9` the caller news 0x10 bytes, calls the factory with `r8d = 4`, stores it
  at `[rbx+0x7b8]`, then `mov rcx,[rbx+0x7a8]; mov [rcx+0x47a8], rax` and `call 0x143eb4ed0` in the
  anime band — i.e. **a per-player collision body, attached at `AnimePlayer+0x47a8`.** [b]

So the honest answer is: **no ricochet path was found from the ball side** — the integrator's
closure reaches no attribute, RNG or dt270, and the bounce table is ground-only — **but a per-player
`collision::Human` exists inside `match::AnimeCollision` and was not followed.** Every ball/player
contact *that was found* is initiated by a player-side action; whether any action can auto-fire on
proximity still lives in the action selector in `match::player`/`match::ai`, not here. Downgraded
from "proven" to "one-sided", and `match::AnimeCollision` is added to the class table and to
§ Open. [b]

Two dt270 fields that sound perfect and are not: **`trap.trapLoss` and `trap.trapLossDashOnly` have
no readers anywhere** (`status: unread`, `readers: []`, soff 492/493). **Both are stock `true`** —
the earlier "true/false respectively" was wrong; `dt270_objects.py get trap trapLossDashOnly`
returns `true` against the installed pack. Either way, "let players lose the ball on a trap" cannot
be switched on in data. `trap.reachOut.ballSpeed` and `.reachOut.reach` are likewise unread, though
`.reachOut.use` is read. [a/b, from the installed dt270 pack and `build/dt270_liveness.json`]

---

## The input census

| input | reaches `match::anime`? | where |
|---|---|---|
| **motion assets** | **YES — and this is the layer's real input.** 21 channels per animation, 7,883 animations, read through `MbInfoManager` | ch 3 `AnimationData` (end frames), ch 5 `CancelData` (the lockout), ch 6 `JumpData` (Trap's gate), ch 7 `DemoConnectData` (fall -> get-up) |
| **dt270** | **YES, but as parameters, with two exceptions.** **9 get-sites sit inside actual `match::anime` class method bodies**; 83–90 sites across 60–69 functions in the anime *address band* `0x143e90000..0x144090000`, depending on how the band is drawn | class bodies: `Trap::vf14 0x143f889df`/`0x143f88ae8` (`trap`), `CTrapAnimeInfo::vf5 0x14404e36c` (`trap`), `0x143f0522b` (`ball`), `0x143fbd332`, `0x143fbdbe7`, `0x143f091f8`, `0x143fce329`, `0x143fc84fb`. **The two that are decisions**: `Trap::vf14`'s cancel gate and the five `moveMatching` readers |
| **attributes** | **YES**, and only here for keepers: GK Catching `0x23`, Parrying `0x24`, Reflexes `0x25`, Reach `0x26` in `0x144032870`; GK Awareness `0x16` at five further anime-band sites (`0x143f2c5a9`, `0x143f4238a`, `0x143f4a224`, `0x143e4140d`, `0x143e43855`), undecoded. Outfield: Tight Possession `0x19` and Aggression `0x1f` in the trap family, Stronger Foot `0x35` + Weak Foot Accuracy `0x27` in the weak-foot cap, Balance `0x2a` in `Stagger::vf32`, Ball Control `0x18` in the dribble band | as listed |
| **skill cards** | **YES, heavily — 287 sites.** The accessor `0x143eadbe0(AnimePlayer, cardId)` has **287 call sites in 98 functions, every one in the anime band**; only 8 of those 98 are RTTI-named classes (25 sites). A second accessor `0x1442c0000` adds 20 sites in 11 functions | `player-executors.md`'s "the one card-shaped query found is in the anime layer" was the tip of this |
| **CPU difficulty** | **ZERO.** 0 of 24 `AiLevelUnit::GetParam` sites, 0 of 46 `Team::GetCurrentLevel`, 0 of 20 `IsEnabled` anywhere in the band | — |
| **RNG — class bodies** | **ZERO** in all 593 `match::anime::action::` method bodies and all 114 `goal_keeper::` bodies. Controls pass: `match::player` has 12 (all `ActionShoot::vf6`), `match::ai::bp` has 8 | — |
| **RNG — one hop down** | **but the layer is not deterministic.** Two helpers on the player's own stream at `AnimePlayer+0x3bb4`: `0x143ea9260(player,n)` = `rand()%n` (**218 sites**) and `0x143eafd30(player,pct)` = `rand()%100 < pct` (**77 sites**), in unnamed anime-band helpers. LCG core `0x144345d90` | the motion-matching search `0x143ee47c0` uses the first three times, all **variant selection**: a uniform pick in a candidate range, `rand()%3` into `{3990, 4038, 3989}` at `0x146b4f9f0`, `rand()%10` into `{1783..1790, 83, 84}` at `0x146b4f9c8` — all motion ids |
| **the registry / blackboard** | not swept here | — |

**Where the randomness is not.** `AnimePlayer::vf1` (564 functions explored), `vf2` (536), `vf3`
(573), the transition `0x143eb4fd0` (504), the executor driver `0x145620a00` (521), the command
consumer `0x1456272c0` (535), `Move::vf14` (15), `Trap::vf14` (38), `0x143ec3ed0` (4) and
`0x143ec93f0` (19) reach **zero** LCG calls. Animation playback, state transition, the cancel gates
and the whole locomotion-parameter path are deterministic. Positive control: the kick builder
`0x14401a900` reaches the LCG at depth 2 (664 explored). Negative control: `ChanceSpaceRun::vf5`
explores 239 and reaches nothing. No closure saturated — cap 20,000, largest 2,457, and the explored
counts differ per root. [b]

**Two disclosures the brief demanded, both triggered.**
(1) A plain forward closure from the save family **saturates**: all seven vtables 33,354 functions,
`SavingBase::vf4` 33,267, and the kick-builder positive control 33,116 — the same answer for almost
any root, a merged-SCC artefact, **not a finding**. The RNG numbers above come from
depth-bounded/in-body counting instead.
(2) An earlier run reported the *negative* control hitting the LCG because mapping cluster addresses
back through `func_root` pulled in `0x144345c10`. **`0x144345c10` is not RNG** — it is a float math
helper (sqrt call, polynomial, atan/smoothstep shape), and its 7,563-caller neighbour `0x144345ae0`
is an angle wrap into [0, 2pi). Reported rather than quietly fixed.

---

## Tunables

Pool-cell sharer counts from `build/exe_constant_census.json`. **"Re-aim" means repoint the
instruction's `disp32` at a private cell — never write a shared cell in place.** The
**`motion-asset`** route means editing a `.bin` inside a WESYS container inside the CPK, in place, at
identical length: no exe patch, no shared cell, per-animation granularity — but subject to the write
gate above, **including its three unbuilt packer requirements** (key nibble 0, flag `0x81`, no
encryption, zopfli). **Delivery for the `exe code` rows is not stated by the table**: `exe_patch.py`
writes the file on disk, `live_patch.py` writes the running process, and the project note for this
title is that the disk is Denuvo-protected with the runtime path as the live route. Note also that
`build/exe_patch_state.json` currently lists 27 specs as applied while the image is byte-identical to
PRISTINE — the state file is stale, trust `exe_patch.py status`. Not-safely-tunable rows come first.

| what | site | route | effect | evidence | sharers |
|---|---|---|---|---|---|
| **NOT SAFELY TUNABLE — the AnimePlayer RNG helpers** | `0x143ea9260` (`rand()%n`, 218 sites), `0x143eafd30` (`rand()%100 < pct`, 77 sites) | — | forcing either to a constant de-randomises **295 decision sites at once**, most of them far outside the motion layer. Listed so nobody tries it | b | 295 sites / 108 functions |
| **NOT SAFELY TUNABLE — animation length** (`AnimationData.bin` ch 3 / `Animation.bin`) | 36-byte records | — | two independent reasons. (1) **It does not fit**: lengthening 69 stagger animations overflows the compressed slot by 12 bytes and a CPK entry cannot grow. (2) `Animation.bin`'s path is not one of the 68 the exe names, so it may not even be live. **Read it, do not write it** | a | n/a |
| **NOT SAFELY TUNABLE — `AnimeTable/bin/CancelData.bin`** | 83,556 B, 6,963 records | not reachable | the **decoy**: same data at **+4 decoded frames** (stored +2, doubled on read), and the exe never names the path. Editing it changes nothing and reads as a failed experiment | a | n/a |
| **NOT SAFELY TUNABLE — `Stagger::vf32`'s second Balance term** | `0x143f00b29`, ramp 99 -> 120, divisor 21.0 at `0x1462aa554` | — | **unreachable**: `comiss 99.0, balance; jae skip` means any player at or below the 99 cap skips it. Tuning the 21.0 does nothing until the 99.0 knee moves | b | n/a |
| **NOT SAFELY TUNABLE — `trap.trapLoss` / `.trapLossDashOnly`** | dt270 `trap`, liveness `soff` 492/493 (schema `off` 80/81 — different basis, see § First touch) | not reachable | **no readers anywhere**, and **both are stock `true`** (the earlier "true/false" was wrong). The only fields named for losing the ball on a trap are dead. Do not write a spec around them | a/b | n/a |
| **NOT SAFELY TUNABLE — `Deflect::vf37` / `SnapUnder::vf37`'s argument** | `0x143f4ad50`, `0x143f4fb50` | not reachable | multiplied by a freshly-zeroed register. A hook here tunes nothing on two of six saves | b | n/a |
| **NOT SAFELY TUNABLE — `SavingBase::vf29` lead times** | Catch/Punch/Block `0x143f4a5c0` (60.0 @ `0x145a8dd84`), Deflect `0x143f4ad80` (90.0/48.0), ScoopOut `0x143f4b1d0` (30.0), SnapUnder `0x143f4fb70` (15.0) | — | would directly change how early a keeper commits, which is a real realism lever. But **every cell is a generic pooled float** — 60.0 at `0x145a8dd84` is the same cell the save selector's km/h conversion uses twice. Only a disp32 re-aim is safe, and this chapter does not propose one | b | pooled image-wide |
| **NOT SAFELY TUNABLE — the 50 km/h slow-ball gate** | cell `0x145ae7580` = 50.0, loaded at `0x1440328cc` | — | lowering it would shrink the near-uniform 73..89 easy-catch band and let ability decide more saves — but the cell has **503 referrers**. Re-aim only | b | **503** |
| **the carrier's stagger gate** — stop routing Dribble to the animation END | `0x143f00efa`, `jne` `75` -> `EB` (`contact-dribble-cancel-early.json`) | exe code | **the headline fix.** The carrier may act a median **0.333 s** earlier, worst case **0.700 s**; for the 44 of 69 single-key staggers it replaces the whole animation with the first key. Every other requester is unaffected. One byte, same length, no pool cell | **a** | none — a branch opcode inside `Stagger::vf14` |
| **a sliding tackler's immunity** | `0x143f7037d`, `xor r14b,r14b` (`4532F6`) -> `mov r14b,1` (`41B601`) (`falls-slide-tackle-contact.json`) | exe code | `Sliding::vf14` answers yes for the whole slide instead of only after the LAST key, which covers a median **86 %** (1.367 of 1.63 s). Sliders become knockable-over at any point. Raises no foul odds by itself | **a** | none — 3 bytes |
| **the floor lockout** | `0x143f00d71`, `jne` `750A` -> `6690` (`contact-falldown-cancel-early.json`) | exe code | 75 of 87 falls have two keys; LAST-key gate median **2.800 s** vs FIRST-key **1.400 s**. Halves the grounded lockout. **Only useful paired with the `Dribble::vf2` table byte** — Dribble and Move are refused outright while FallDown runs | **a** | shared by FallDown and Dive (one body) |
| **a fallen player may ask for the ball** | `Dribble::vf2` case table `0x143f99f60`, entries `+0x0f` (FallDown) and `+0x0d` (Dive), `03` -> `02` | exe code | moves both off the refuse handler onto case 2 — the same delegate Stagger already uses — so the request is gated by `FallDown::vf14` rather than dropped. Stock values verified `03`/`03` in both images | **a** | one byte each, in a table that is Dribble's alone |
| **a staggering player may contest** | `Tackle::vf2` `0x143f7caee` `03` -> `01`; `Sliding::vf2` `0x143f7059e` `02` -> `01`; `Feint::vf2` `0x143fabb52` `01` -> `00` | exe code | each moves the Stagger entry onto that class's own vf14-delegate case, so the request is then gated by `Stagger::vf14`'s generic FIRST-key path — median **0.600 s**. This is "fight back after ~0.6 s", not "immediately". **Do NOT use Tackle case 2**, which is ALLOW outright and fires at frame 0 | **a** | one table byte each |
| **per-animation cancel frames** | `Mbinfo/bin/CancelData.bin`, 12 B, `frame = (((v>>13)&0x3FF)+2)*2` at bits 13..22, `idx` at bits 0..12. 69 staggers / 98 stagger records; 117 `tackle*`; 33 `sliding*`; 87 `fall_*` | **motion-asset** | the only route with **per-animation** granularity: move `stagger_upbody_3_3_090`'s keys without touching the other 68. +6 frames on every stagger key moves the generic median from 0.600 s to 0.700 s and fits with **11** bytes to spare — but **the same +6 on the whole contact family (723 records) OVERFLOWS by 13 bytes**; a uniform **+12** fits everywhere (staggers +12 spare, contact family +8). The earlier row's "+6" was +6 on the *stored* field = +12 frames. Measure the set you are actually moving. Subject to the write gate | **a** | per-motion; **no per-player scaling exists** — individuality died with `PersonalizedData` (24,972 B -> 236 B) |
| **time on the floor before the get-up starts** | `Mbinfo/bin/DemoConnectData.bin`, 4 B, `connect_frame` at bits 13..21 (doubled on read), `end_state` at bits 22+ | motion-asset | must move **together with** the fall's cancel keys or the player cancels out before the get-up connects | **a** | per-motion |
| **get-up timing** | `AnimeTable/bin/Risetypeframedata.bin`, 12 B `{u32, f32, f32}`, both floats **times in seconds** | motion-asset | directly editable and in seconds; a **uniform** +0.1 s on every time fits (+5 bytes). **But a selective edit (1 in 20) overflows by 36 bytes, and the key field is not solved** (2.7 % of keys hit `enum_dummy`). Do not target individual animations yet | a | per-motion |
| **`trap.ballControlRate`** | dt270 `trap`, **stock 1.0** (read live from installed *and* PRISTINE packs; `0.80` was OUR value from `loose-realism-v1.json`). Liveness `soff` 56 = the readers' `[rax+0x38]`; schema `off` 16 — set it by NAME. Readers `0x144079c38`, `0x144079dc3`, `0x14407aab5` | **dt270 data** | scales the whole first-touch reach/time budget proportionally at every ability level. **The realism item 3 lever, and it must be LOWERED** — at the shipped 1.0 a TP99 player saturates, which is what the ruling forbids. Needs no patch | **a** | one field, three readers |
| **`trap.ballControlWeekFootDownLimit`** | dt270 `trap`, stock **20.0** (confirmed against the installed pack); liveness `soff` 60, schema `off` 20; sole reader `0x144079163` | **dt270 data** | deepens the weak-foot first-touch penalty only, leaving strong-foot touches alone — exactly the "create the conditions, do not produce indiscriminate bad touches" shape | b | one field, one reader |
| **`trap.animeCancelFrame.use`** (`cmp byte [rax+0x28],0`) and **`trap.cancel.hitBefore.jumpStartFrame`** (`mov ecx,[rax+0xec]`) | read at **`0x143f88af0`** / **`0x143f889e4`** inside `Trap::vf14` `0x143f88840` (VAs re-taken from `dt270_liveness.json`; the earlier `0x143f88ae8`/`0x143f889df` are a few bytes short of the instruction) | **dt270 data** | master switch and frame offset on the trap cancel gate. Cheap, and needs no CPK write | b | global blob |
| **`moveMatching.RouteParameter[].acc` / `.dec`** | acc: `0x143ec3f46`, `0x143ec9115`, `0x143ec959a`, `0x143fefb48`, `0x143fefe77`, `0x143ff017f` (**six**); dec: `0x143ec3f9d`, `0x143ec8cb5`, `0x143ec8ee1`, `0x143ec911c`, `0x143ec9627` | **dt270 data** | the surface for "heavier players" — how long a player takes to reach the commanded speed and to stop. **But NOT "14 route classes":** `0x143ec3ed0` is pinned to element **5** by `mov r8d,5` at its only call site `0x144082f15`, and `0x143fef370` reads element **0**; only `0x143ec8fd0`/`0x143ec93f0` index at runtime and what drives that index is untraced. Two named elements plus one unaimed indexed path | b | global: one blob, all players, both teams |
| **`.rotSpeed` / `.decRotSpeed`** | copied `0x143ec3fcd` / `0x143ec3fd5`; read `0x143ec965c` / `0x143ec966c` | **dt270 data** | "realistic turning". **Check the shipped data first:** `rotSpeed` is **7.0 in all 14 rows** and `decRotSpeed` is **0.0 in all 14** — so per-route turning differentiation does not exist in stock, and `decRotSpeed`'s consumer must be checked for the multiply-by-zero case before it is called a lever | a/b | global |
| **`.accRateDif60/120/180`** | copied `0x143ec3fed`/`f5`/`fd`; read `0x143ec968d`/`98`/`a3` | **dt270 data** | how much a player loses by changing direction — the field that makes a 180 cost something. **It is read, so the old worry that it was inert is refuted** | b | global |
| **the two hard-coded floats in the locomotion compile** | `0x143ec3f4d mov dword [rdi+0xc],0x41700000` (15.0f) and `0x143ec3f5c mov dword [rdi+0x10],0x41b40000` (22.5f) | **exe constant (inline, private)** | two private immediates in the Dribble locomotion block. **The earlier glosses were wrong** — gait 3 is **16.0** and the midpoint of gaits 4/5 is 25.0, so neither float is a gait speed — and **the "cleanest edit" verdict is withdrawn**: no consumer of `block+0xc`/`+0x10` was located, and on the high branch both are rescaled (`0x143ec4035` / `0x143ec403a mulss …, xmm8`) while `[rdi+4]`/`[rdi+8]` are overwritten with 1.0f. Safe to edit, **effect unquantified** | **c** (bytes are b) | **none** |
| **the gait->speed table** (5 / 11 / 16 / 22 / 28) | `0x1443262a9` (28.0), `0x1443262b6` (22.0), `0x1443262bf` (16.0), `0x1443262c8` (11.0), `0x1443262d1` (5.0) | exe code — **re-aim only** | global top speed and the spacing between gaits; every executor's gait passes through it. Compressing the top end slows every sprint | b | **do not write the cells** (re-run against the current census): 28.0 has 179 referrers, 22.0 303, 16.0 419, 11.0 258, **5.0 1,885** |
| **the speed->gait cut points** (0.05 / 8.0 / 13.5 / 19.0 / 25.0) | `0x144326240`, `0x14432624f`, `0x144326230`, `0x144326260`, `0x144326273` | exe code — re-aim only | which gait *animation family* a commanded speed is classified into — changes when players switch from jog to run without changing how fast they move | b | 8.0 **829**, 25.0 659, 13.5 156, 0.05 257, 19.0 63 |
| **the driver's seeded gait** (3 = 16.0) | `0x145620a7a mov ecx,3` and `0x145620a7f mov dword [rbp+0x77],3` | exe constant (inline, private) | the default for any executor whose slot 13 does not override the gait — per `player-executors.md`, **31 of 55 movement classes**. Moves the baseline off-ball tempo of the whole match. High blast radius by design | b | **none** — two immediates in one function |
| **halve every cancel gate inside a stagger at once** | `0x143f00e13 movss xmm6,[1.0f]` re-aimed at a private 2.0f (`contact-cancel-window-x2.json`) | exe code | `xmm6` is the divisor every keyframe getter applies, **including the channel-3 END path**, so it halves the generic gate (0.600 -> 0.300 s) and the carrier gate (1.000 -> 0.500 s) together. Blunter alternative to the headline fix; the two collide, apply one. Note `FallDown::vf14` loads its 1.0f at **two** sites (`0x143f00d4e`, `0x143f00d86`) and `Sliding::vf14` at `0x143f703ae`, so the same trick there is three edits | b | disp32 re-aim, no cell written |
| **open the stagger gate entirely** | `0x143f00e03 xor dil,dil` (`4032FF`) -> `mov dil,1` (`40B701`) | exe code | returns 1 from frame 0 for every requester. Real, but larger than the complaint needs, **and its filed rationale is wrong** (the keyless default is frame 4, not a permanent lock). Prefer the Dribble-only fix | b | 3 bytes |
| **open the fall gate entirely** | `0x143f00d1d xor r14b,r14b` -> `mov r14b,1` | exe code | the largest single effect available here — removes a median 2.8 s gate. **Riskiest of the set; test alone** | b | shared by FallDown and Dive |
| **Move out of a stumble** | `Move::vf2` `0x143f688de`, `sub ecx,7` imm8 `07` -> `BA` (`contact-move-out-of-stagger.json`) | exe code | `Move::vf2` is a **compare chain, not a table** (span 1), so the three delegate slots move as a block from current kinds `0x5d`/`0x5e`/`0x5f` to `0x10`/`0x11`/`0x12`. Works — but it **removes the three demo kinds from the delegate path**, and the spec does not say so | b | one immediate |
| **`HoldData` hand-contact geometry** | `Mbinfo/bin/HoldData.bin`, 20 B, 378 records, `bone` in {7, 11} = a **mirrored left/right pair** (matching X and Y, opposite Z) | motion-asset | scaling all 378 offsets by 1.1 fits with 21 bytes spare. Dominated by GK catch/block animations, so it is a **goalkeeper-hands** lever more than an outfield-contact one | a | per-motion |
| **`Stagger::vf32` Balance curve K** | `0x143f00af8 movss xmm1,[6.0f]` (`contact-stagger-lock-shorter.json`) | exe code — re-aim | garnish, as both spec files admit: the term is 1–5 frames (17–83 ms). Two corrections to the filed formula: the upper knee is **100**, not 99, and the divisor is `xmm7 = 60.0` at `0x143f00a3a` | b | disp32 re-aim |
| **the motion-id variety tables** | `0x146b4f9f0` = `{3990, 4038, 3989}` (picked `rand()%3` at `0x143eeab90`); `0x146b4f9c8` = `{1783..1790, 83, 84}` (`rand()%10` at `0x143eeac19`) | exe constant | which animation variants may be chosen. Narrowing removes variety; it changes no timing and no speed. Low risk, low value | b | one function each |
| **the outside-the-box foul threshold** | `0x143d8629f` `mov ecx, imm8` (the imm byte is at `0x143d862a0`): **`0x28` = 40 in PRISTINE *and* in the installed image** | exe code | **stock is 40.** Our `phys-whistle-threshold.json` overlays 36; `exe_patch.py status` reports it `pristine` today. The in-box `0x3c` = 60 at `0x143d862a4` and the card knees `0x50` = 80 and `0x6e` = 110 are the other levers. **Diff before quoting any of them as stock — and diff against the image that is actually installed** | **a** | immediates |
| **the two constants in `0x143f56dd0` that one of OUR archived builds re-aims** | `0x143f56e39` 4000.0 (`0x145e851d0`) -> 5000.0 (`0x145be1e80`) and `0x143f56e64` 30.0 -> 20.0, **in `eFootball.exe.patched-20260920-001042` only; both are stock in the installed image** | not reachable | **NOT IDENTIFIED.** The brief calls this `Jostle::vf4`; `0x143f56dd0` is **in no vtable** and is called only from `0x143f57930` and `0x143f58790`, neither of which is a vtable method either. Do not describe its effect until someone traces the consumer | b | disp32 re-aims |

---

## The owner's five realism items, answered

### 1. More randomness in AI decisions, varied off-ball movement — *unchanged here, one nuance added*
This layer does not choose. The state transition (504 functions explored), the per-frame drivers and
the cancel gates reach **zero** randomness. The randomness that does exist is **variant selection**:
295 sites of `rand()%n` / `rand()%100 < pct` in anime-band helpers, three of them inside the
motion-matching search picking between motion ids. Making the *body* more varied is available;
making the *decision* more varied is still subsystems 1–2. **[b]**

### 2. Trigger runs on a pad gesture — *not this subsystem*
Settled in `registry-pad-command-channel.md`. Nothing here bears on it.

### 3. A freer ball — *two answers, and BOTH were stated wrongly before this repair*
**Ricochets off non-tacklers: no route found from the ball side, but the negative is ONE-SIDED.**
The ball integrator consults no player body, and the bounce table has six ground surfaces and no
body entry — those two legs hold. The third leg, "`collision::Human` has zero callers image-wide",
is **false**: it is heap-allocated per player by the factory `0x143ff2210` (3 call sites) inside
`match::AnimeCollision` and attached at `AnimePlayer+0x47a8`, and that object was never followed.
See § First touch for the byte trail. The answer is "not found", not "proven absent". **[b]**
**Poor touches: YES, in data — and the ruling is VIOLATED as shipped, not satisfied.**
`trap.ballControlRate` **stock is 1.0**, not 0.80; the 0.80 this chapter quoted is our own
`loose-realism-v1.json` value read out of a stale Aug-23 dump. At exactly 1.0 a TP99 player's
first-touch term is exactly 1.0 — mathematically incapable of a bad touch, which is the saturation
the owner's ruling forbids. **Lowering this one field is the lever** (0.80 and 0.65 are values this
project has already tried; at 0.80 a TP99 term tops out at 0.80 and a TP40 term stays at 0). The
attribute it gates is **Tight Possession `0x19`**, not Ball Control `0x18`, which the trap family
never reads. `trap.ballControlWeekFootDownLimit` (20.0) is the per-player differentiator. And
`trap.trapLoss` — the field that sounds like the answer — **is inert** (and stock `true`, not
`false`). **[a/b]**

### 4. Heavier players and realistic turning — *the surface is confirmed and it is the one that was suspected*
dt270 `moveMatching.RouteParameter[14]`, stride 56, indexed `imul reg, idx, 0x38`, **11 of the 14
fields live-read** (`accacc`, `poseWeight`, `routeWeight` have zero readers — the earlier "all 14"
was wrong), with `acc`/`dec` as multiplicands and `rotSpeed`/`decRotSpeed`/`accRateDif60/120/180`
compiled into a per-frame block by `0x143ec3ed0`. The skeleton's 2026-09-20 lead was correct,
including its conclusion that **there is no mass term** — and the reason is stronger than stated:
the two `*Weight` fields are not pose-matching costs that get read, they are **dead**.
**What is new, and limiting.** dt270 is one global blob: nothing indexes it by player, attribute or
style. Worse, the route index is mostly not aimable — `0x143ec3ed0` is pinned to element **5** by
`mov r8d,5` at its only call site, `0x143fef370` reads element **0**, and only `0x143ec8fd0` /
`0x143ec93f0` index at runtime with an untraced driver. And the shipped data has only **5 distinct
rows** of 14, `rotSpeed` uniform 7.0 and `decRotSpeed` **0.0 everywhere**. So "heavier players"
cannot be expressed in data, and even "heavier route classes" is today two named elements.
The per-player version needs a runtime hook on `0x143ec3ed0`'s 0x3c-byte output block, whose layout
is fully named above — noting that on that function's high branch `[rdi+4]`/`[rdi+8]` are
overwritten with 1.0f, discarding the dt270-derived values. **No longer claimed:** that the two
hard-coded floats (15.0f, 22.5f) are gait speeds or the safest exe constant here; neither is a gait
speed and neither has a traced consumer. **[a/b]**

### 5. More fouls and physicality; players properly falling over — *unblocked, with one honest gap*
**The blocker is gone.** The keyframes are read, named and in seconds; the tables are extracted; the
containers are stored verbatim in the CPK at located offsets and `ml_deploy.py` reaches them. What
replaces it is a narrower, measurable gate with **four** parts: a WESYS writer that does not yet
exist (key nibble 0, flag `0x81`, no encryption), **zopfli**, and **5–19 bytes of headroom that must
be measured per record-set and per delta, not assumed** — `Animation.bin` overflows, and so does a
uniform **+6 frames** across the contact family (−13 bytes) even though **+12** across the same set
fits (+8).
**The seven contact specs become computed.** Effect sizes for all of them are in § Tunables, and the
premise that killed them — "10 of 11 staggers have <=1 key, so it is a placebo" — is inverted: the
single-key staggers are exactly why `contact-dribble-cancel-early.json` buys the whole tail of the
animation on 44 of 69 motions. `falls-slide-tackle-contact.json` is sound and removes a veto
covering 86 % of every slide. `contact-stagger-interrupt-open.json`'s filed rationale is wrong
(keyless = frame 4, not locked forever) even though the edit works.
**The honest gap: more fouls is not proven.** Everything downstream of contact event kind `0xe` is
decoded — payload, scorer, thresholds, cards — but **the poster of the event was not found**, so
"more contact produces more fouls with no referee constant touched" holds only if the extra contact
raises more kind-0xe events, and that step is unshown. If fouls are the goal *today*, the targeted
lever is the referee's own thresholds — all of them stock in the installed image: outside the box
**40** (`0x143d8629f`, imm byte `0x143d862a0`), in-box **60** (`0x143d862a4`), card knees **80** and
**110**. Our `phys-whistle-threshold.json` would take the 40 to 36 but is **not applied**.
**"Properly falling over, not stumbling" is half answered.** The cancel data says how long each fall
lasts and when it can be broken; **which** fall plays is `FallDown::vf30` (`0x143effa40`, 711 ins)
and `Stagger::vf30` (`0x143effd70`, 512 ins), the motion selectors, and neither was decoded. **[a/b]**

---

## Corrections to finished chapters

**`docs/player-executors.md`**

1. **OPEN 7 — CLOSED, and its conclusion inverts.** The consumer is the command struct at
   `playerWork+0x8b8`, assembled by `0x145620a00` and passed **by pointer as argument 3** of the anime
   action contract (proven at base slots 25 and 26, which read it at `+0x20`/`+0x28`/`+0x54`/`+0x5c`;
   of those the driver writes `+0x20`, `+0x28` and `+0x54` directly, while `+0x5c` gait and `+0x560`
   speed are written by the MoveOrder sub-object's setters `0x1443393e0` / `0x1443393b0` — see the
   corrected § The crossing). "Executors do not call the animation layer" is true; "the one place the boundary is a
   call is the tackle" is the wrong conclusion from it. **Call closures from the executor side were
   structurally incapable of finding this.** Add the struct layout from § The seam. [b]
2. **The output tuple has a fourth scalar the chapter missed.** Not `(target, gait, movement-class,
   path)` but one struct with a **SPEED float at `+0x560`** (= `playerWork+0xE18`), and the path is a
   **member at `+0x68`**, not a separate object. Gait and speed are never independently authored —
   the driver derives one from the other through `0x144326290`/`0x144326230`. So "no speed crosses
   here" is wrong. [b]
3. **`ActionSpaceRun::vf18`'s signature.** The driver passes **four** out-params on the stack:
   `rsp+0x20` = &target vec3, `rsp+0x28` = &gait, `rsp+0x30` = **&speed float**, `rsp+0x38` = &tag
   (seeded `0x71`). The third is a float, not an int, and the fourth is the action tag rather than a
   "movement class". [b]
4. **The contact-lockout paragraph.** "10 of 11 stagger motions have <=1 cancel key — which is why
   the obvious fix looked like a placebo" is wrong in both directions: **69** stagger motions, **all
   69** with at least one key (44/21/4 with one/two/three). And the key *count* was never the
   lockout — the **first key** is, at a median 0.450 s for in-play staggers inside a ~0.98 s
   animation. The chapter's conclusion that CancelData decides it is right and now actionable. [a]
5. **The GK save-quality row needs its second half.** The chapter stops at the 40..120 integer. Its
   consumer `0x143f31470` turns it into a **0.90–1.40 multiplier**; the roster spread is 9–30 %
   depending on the save. Add the discontinuity at 91 (attributes above 90 bypass the remap, so Reach
   90 -> 87 but 91 -> 91) and the fact that "they all converge on `0x144032870`" is too strong —
   Reach is also read in `Deflect::vf35` (`0x143f4ae0b`), outside the selector, and Parrying at
   `0x143fe3056`/`0x143fe314a`/`0x143fe372b`. [a/b]
6. **`ActionMark::vf22`'s patch value**, recorded as patched but not quantified: `0x1441a29f9` is a
   disp32 re-aim **18.0 -> 25.0** (`0x1462aa550` -> `0x145da7de0`), **verified in the archived build
   `eFootball.exe.patched-20260920-001042`**. It is *not* in the installed image, which is stock —
   the earlier "INSTALLED" label was wrong, the value pair is right. [a]
7. Anything built on `0x1440374b0` having `fox::nio::impl::TcpSocketImpl::vf13` as a depth-1 caller
   is an identical-code-folding artefact of the call graph, not a real call. [b]

**`docs/anime-actions.md` (this file, superseding its own skeleton)**

8. **GIVEN #3's packing rule is replaced** by the exe's: `idx = v & 0x1FFF`,
   `frame = (((v>>13) & 0x3FF) + 2) * 2`. The 12-byte record size **stands and is confirmed**
   (5,746 records exactly). Its worked example decodes as `fall_air_upbody_0_0_000` frames 56 and 98.
   "Paired cancel windows" is not the rule — **one key is, by a wide margin**. Recomputed for the
   2026-09-20 repair under *this* chapter's 13-bit index (the earlier figures 1,890 / 905 / 303 were
   computed under GIVEN #3's refuted **12-bit** grouping, i.e. the correction quoted the packing it
   exists to kill): of 7,061 named motions, **4,295 carry at least one key — 3,287 have one, 726
   two, 181 three, 51 four, 44 five, and a tail 6/7/9 — and 2,766 have none.** That is exactly the
   distribution in this chapter's own `build/anime_motion_tables.json`.
   **What matters is the FIRST key, not the window**, and the single-key majority is *why* the
   headline fix is not a placebo. [a/b]
9. **"So each `.bin` is a compiled JSON object" is wrong** — already flagged, now settled from the
   exe side too: the MbInfo loader is a fixed-stride record walker (divide-by-36 magic at
   `0x143e95565`, 12- and 20-byte strides at `0x143e95e33` / `0x143e958d3`). The `ParsedJson*`
   classes belong to the `AnimeTable/` side. [b]
10. **"We need a CPK reader" — no longer true for edits.** `dt230_console_win.cpk` stores each WESYS
    container **verbatim** at a unique `0x800`-aligned offset; `CancelData.bin` was located at
    `0xb5bf800` with a full byte match and exactly one occurrence. The real blocker is that Konami's
    deflate beats zlib -9, so the repack needs zopfli and the headroom is **5–19 bytes, measured per
    record-set and per delta** (see the corrected § The write gate). **But the PACK half is still
    unbuilt** — `pack_wesys_container` cannot emit key nibble 0 / flag `0x81` / unencrypted, and
    `ml_deploy.py` uses `cricodecs.cpk.load()` and is hardcoded to dt200. Retire the *reader*
    blocker, not the whole gate. [a]
11. **The `goal_keeper::` family is 15 classes, not 14** — seven carry the 50-slot contract, the
    other eight are 29- or 33-slot. The rest of the slot histogram reproduces exactly: 29x74, 50x7,
    24x8, 30x8, 35x4, 33x3, 31x1, 26 small loaders. [b]
12. **`MbInfoManager` is `match::`, not `match::anime::`** — with `MbInfoManagerBase` and
    `MbInfoLoadThread`. Three classes outside the namespace that belong to this subsystem. [b]

**`docs/pes2014-vs-efootball-contact.md`**

13. **"`Jostle*` action classes: 9 -> 0" is FALSE.** `match::anime::action::Jostle` is live: vftable
    `0x146b4a3b8`, 29 slots, bases `Base` + `JostleRetryWork`, real bodies at vf1/vf2/vf6/vf13/vf14/
    vf18, constructed by the ActionManager ctor at `0x143e9f65b`. The correct row is **9 -> 1**: the
    eight concrete PES variants are gone, the base survives as live code. [b]
14. **"`*RetryWork` classes: ~22 -> 0" is FALSE AND BACKWARDS.** eFootball carries **78** RetryWork
    types to PES 2014's 52 — 45 of them under `match::anime`, including `ContactRetryWork`,
    `TackleRetryWork`, `SlidingRetryWork`, `TrapRetryWork`, `JostleRetryWork`, `InjuryRetryWork`.
    **Cause of the error:** they are declared `struct`, so their RTTI descriptors are `.?AU…@@`, not
    `.?AV…@@`, and they carry no vftable — a class-only scan misses every one. The paragraph
    beginning "RetryWork is the quiet one… which is what made contact persistent" must be withdrawn
    or re-founded. The chapter's overall conclusion (restructured, not deleted) survives and is
    strengthened. (Its `constant::PairAnime` claim does hold: 0 in eFootball, 10 in PES 2014.) [b]
15. **"eFootball index -> name is still open" — SOLVED.** The table is at `0x148027310`, 7,883
    entries in motion-id order, bounded by `cmp edx,0x1ecb`. The chapter's advice (it needs the
    name-pointer table, which means disassembly) was right. Its "11,096 names" conflates three
    tables: 7,883 body + 2,972 aux + 646 face. [a]
16. **The `CancelData.bin` row "same rule applies" is the specific cell that is wrong.** eFootball is
    12 B `{u32 packed, f32, f32}` with the rule in correction 8, not 4 B with the PES rule. Update
    the eFootball column with `AnimationData` 36 B x 7,073 (index in the **high** bits),
    `DemoConnectData` 4 B, `HoldData` 20 B, `DangerData` 20 B. [a]
17. **`MatchAnimeDefinedatatable.bin` "does not unwrap as WESYS+zlib" — REFUTED.** It unwraps fine;
    the third magic byte is a compression flag (`0x81` zlib, 93 files; `0x00` stored, this one,
    `csize == dsize == 132`). [a]
18. **PES 2014's `blend_start` width, flagged as probably wrong, is exactly fixable:**
    `blend_start = ((v >> 21) & 0x1FF) + 6` gives **2512/2512**, not 65/67. Nine bits, not eleven.
    PES word layout is `{idx:12, end_frame-8:9, blend_start-6:9, 2 spare}`. That closes the item. [a]
19. **The `bone` field narrows.** The first half stands (7 and 11 are nonsense on the 22-bone
    skeleton). The second half: **7 and 11 are a mirrored left/right pair** — the three animations
    carrying both give matching X and Y and opposite Z (+13.2/-12.3, +13.3/-14.5, +12.3/-13.7).
    Almost certainly the two hands, in an effector enum that is neither published skeleton. [a]

**`docs/match-ai-decoded.md`**

20. **WITHDRAWN 2026-09-20. `match-ai-decoded.md` is right and this correction was wrong.**
    `0x143d8629f` reads `b9 28 00 00 00` = `mov ecx,0x28` = **40** in PRISTINE **and** in the
    installed image (the two are byte-identical, sha1 `d2b84d1c506ab09d62035b7889a57452479b73a8`,
    0 differing bytes), and `tools/data/patches/phys-whistle-threshold.json` itself records
    `"expect": "B928000000"` — the spec author logged 40 as the *pre*-patch value.
    `exe_patch.py status` lists that spec as `pristine`. **40 is the game's.** Had this correction
    been applied it would have replaced a correct fact in a finished chapter with a false one.
    What is true, and is worth recording so the next diff is cheap: the archived build
    `Backups/eFootball/eFootball.exe.patched-20260920-001042` carries our overlay — threshold byte
    `0x143d862a0` `0x28`→`0x24`, `0x143d868fe mulss` re-aimed 20.0→25.0, `0x143d86bcd mulss`
    35.0→40.0, `0x143d88659 movss` 0.06→0.05, `0x143d51a90 mov dl,1`→`mov dl,2` — and the
    installed exe was restored to stock before this chapter was written. **Always `exe_patch.py
    status` and a byte diff of the image that is actually installed before writing "ours".** [a]

**`docs/anime-actions.md` — the 2026-09-20 adversarial-repair pass (this file, correcting itself)**

Three verifiers re-ran this chapter against the bytes. Every claim below was **re-derived from
PRISTINE, from the installed dt270 pack or from the shipped `dt230` data before the edit was made**;
where a verifier was wrong the original text is kept and the settling evidence is added instead.

| # | claim as published | what the bytes say | evidence |
|---|---|---|---|
| R1 | "the installed image differs from PRISTINE by ~909 bytes; four runs in the anime band; the referee 40 is already ours at 36" | **The two images are byte-identical** (352,409,088 B each, sha1 `d2b84d1c506ab09d62035b7889a57452479b73a8`, **0** differing bytes). The 909-byte / 105-run diff belongs to the archived `eFootball.exe.patched-20260920-001042`, and against PRISTINE that archive has **24** anime-band runs, not four. Correction 20 **withdrawn** | a |
| R2 | "`collision::Human` has zero callers image-wide, and so does its constructor" — the clinching leg of "ricochets: settled NO" | **False.** ctor `0x1451305f0` has 1 caller `0x143ff224d`; factory `0x143ff2210` (vftable `0x146b6fb48` = **`match::AnimeCollision`**) news 0x28 B and has 3 call sites `0x14410ba5d` / `0x14410bb37` / `0x14410bbe7`; the object is attached at `AnimePlayer+0x47a8`. Ricochet negative downgraded to **one-sided**; `match::AnimeCollision` added to the class table and to Open | b |
| R3 | "`trap.ballControlRate` stock **0.80**, so the ruling is satisfied as shipped" | **Stock is 1.0** on the installed *and* the PRISTINE dt270 pack. `0.80` is *our* `loose-realism-v1.json` value, read out of a stale Aug-23 `build/dt270_json` dump whose own `"was"` field records 1. The ruling is **violated as shipped** and the field must be lowered. Also `trapLossDashOnly` is stock **`true`**, not false | a |
| R4 | Correction 8's histogram "1,890 one key, 905 two, 303 three" | Computed under GIVEN #3's **refuted 12-bit** grouping — the correction quoted the packing it exists to kill. Under this chapter's own 13-bit rule: **3,287 / 726 / 181 / 51 / 44 / 4 / 1 / 1**, 4,295 keyed of 7,061. Matches `build/anime_motion_tables.json` exactly | a |
| R5 | "the base bodies of slots 25/26 read five offsets and **all five are exactly the ones the driver writes**", citing `0x145620f78` / `0x145620f7f` as the gait write | The driver writes `[rbx]`, `+0x04`, `+0x20`, `+0x28`, `+0x3c`, `+0x44`, `+0x50`, `+0x54`, `+0x58`, `+0x554` — **never `+0x5c`**; `+0x5c` is only read, at `0x145621115`. The two cited bytes are `mov [rbx+0x54],0` and `mov [rbx+0x58],3`. Gait is proved instead by the MoveOrder setters `0x1443393e0` (gait into sub`+0x0c` = struct`+0x5c`) and `0x1443393b0`. Conclusion unchanged, citation fixed | b |
| R6 | write-gate rows "+6 frames on 98 stagger records … +12 (fits)" and "+6 frames on 720 contact-family records … +7 (fits)" | Those were **+6 on the stored field = +12 frames**. At the stated **+6 frames** the contact family (723 records) is **-13 — it does not fit**; staggers are +11. The table now gives both deltas and names the record set | a |
| R7 | "`ml_deploy.py`'s existing path reaches it; **no general CPK reader is required**" | `ml_deploy.py` does `from cricodecs import cpk`, calls `cpk.load()`, and hardcodes dt200 / `PlayerAssignment.bin`. And `pack_wesys_container` supports only key nibbles 1 and 2 (all 128 dt230 containers are nibble **0**), always writes flag `0x83` and encrypts (dt230 is `0x81`, plain), and takes only a zlib level (L1 = 61,992, 559 over the slot). **Three unbuilt requirements**, now named | a/b |
| R8 | "`RouteParameter[]` … **all 14 fields are read**" | **11 of 14.** `accacc`, `poseWeight` and `routeWeight` have zero readers — which strengthens the chapter's own (correct) "no mass term" conclusion | b |
| R9 | "`.acc` / `.dec` are THE surface for heavier players, shapeable across **14 route classes**" | `0x143ec3ed0` has one call site and is pinned to element **5** by `mov r8d,5` at `0x144082f15`; `0x143fef370` reads element **0**; only `0x143ec8fd0` / `0x143ec93f0` index at runtime. `acc` has **6** reader sites, not 2. Shipped data: 5 distinct rows of 14, `rotSpeed` 7.0 everywhere, `decRotSpeed` **0.0** everywhere | a/b |
| R10 | "slots **24 / 25 / 26** … one impl each across all 74" | True for 25 and 26 (and across all 97 classes with >=29 slots). **Slot 24 is overridden by 11** — Block, Sliding, Tackle, Trap, Kick, Feint and four restart classes, i.e. exactly the ones this chapter cares about | b |
| R11 | slot table: "12 → `0x14143aec0` (`xorps xmm0,xmm0`)"; "6, 10, 16, 21, 27, 28 → `xor al,al`"; rows 29–33 inside a 29-slot table | Slot 12 is `0x143ef5ea0`, a real accessor; `0x14143aec0` is **slot 22**. The `xor al,al` set is 6, 10, 14, 16, **17**, 21, 27, 28. `Base` has 29 methods = indices 0..28, so rows 29–33 belong to the **35-slot Contact** and **50-slot save** extensions and are now headed separately | b |
| R12 | "184 of its 185 callers are inside `match::anime`" | **172 direct `E8` call sites, 171 in band**, the single outsider `0x14414b48d` inside `0x14414b2f0` as stated. The counting method is now named | b |
| R13 | "§ `Stagger::vf14` — **the whole gate**" | The excerpt opened at `cmp r14d,4`, which is reached **only** when the bit-9 test `0x1443120f0(requestedKind)` returns false; it also dropped `0x143f00f0f mov r14d, eax` (so `lea r9d,[r14-1]` read as a constant 3) and the whole channel-6 JumpData arm for motion ids `0x805`–`0x807`. Block expanded; the carrier conclusion and the one-byte fix are unchanged | b |
| R14 | "Stock [`Sliding::vf14`] answers yes only from the LAST cancel key … 86 %", labelled [a] | The FIRST/LAST choice is a runtime compare against **`byte[anime+0x2bdc]`** (`== 2` FallDown, `== 4` Sliding), and that byte is in § Open. Both branches and both medians are now given, and the runtime half is relabelled **[c]** | b |
| R15 | decoy "every frame **+2**" | The **stored** field is +2; decoded frames are **+4** (0.067 s), because every MbInfo frame field is doubled on read. The one place this chapter compares two files is the one place it forgot its own rule | a |
| R16 | "15.0f is exactly gait-3 speed, 22.5f is midway between gaits 4 and 5 … the cleanest single exe-constant edit in this subsystem" | Gait 3 is **16.0** and the 4/5 midpoint is 25.0, so neither gloss holds. No consumer of `block+0xc` / `+0x10` was located, and on the high branch both are rescaled at `0x143ec4035` / `0x143ec403a` while `[rdi+4]` / `[rdi+8]` are overwritten with 1.0f. "Cleanest edit" **withdrawn**; the claim is demoted to **c** | b |
| R17 | "UNTESTED and **the whole plan rests on it**: trailing bytes after the deflate block" | It does not. Lowering the header `csize` to the true stream length moves no byte and is entirely under the tool's control; all **128** shipped containers have `csize` exact (0 `unused_data`), so the trailing-byte route has no precedent and should be avoided. Residual risk narrowed to a possible `csize + 16` versus CPK-entry-size check | a |
| R18 | trap dt270 reader VAs `0x143f88ae8` / `0x143f889df`; gait cell sharers 5.0 = 1,884 and 8.0 = 828 | Reader VAs are **`0x143f88af0`** and **`0x143f889e4`**; census refcounts are **1,885** and **829**. Also: this chapter's dt270 "offset" column is `dt270_liveness.json`'s `soff` (the runtime struct offset the readers actually use, e.g. `[rax+0x38]` = 56), a **different basis** from `dt270_schema.json`'s `off`. Both are now named | a/b |
| R19 | "Trap **type** selection happens in `0x143f834b0`" | That function **builds candidates**; nothing in it scores or picks one of the eight `CTrap*AnimeInfo` variants. Retitled "the trap candidate builder" and filed as **Open 22** | b |
| — | **A verifier claimed GK Parrying `0x24` is a computed index `arg2 - 0x21`. It is not** — the text is left unchanged and the settling evidence added | `0x144032980 mov edx, 0x24` is a **literal**, on the `0x45` arm of the six-arm jump table. The `lea edx,[rbp-0x21]` at `0x1440328f2` sits on the slow-ball branch, reached only after `cmp ebp,0x44; jne`, so `ebp == 0x44` there and it always evaluates to **`0x23`** — it is the Catching read of the `max(Catching, Reflexes, Reach)`, written in an obfuscated form. All four GK attribute reads in `0x144032870` are literal | b |

**`docs/realism-todo.md`**

21. **Item 5's blocker moves, it does not close.** The CPK-reader half is retired (correction 10),
    but the packer half is unbuilt — see the corrected § The write gate: WESYS key nibble 0, flag
    `0x81`, no encryption, zopfli, none of which `tools/vendor/sider/wesys.py` can do, and
    `ml_deploy.py` is hardcoded to dt200/`PlayerAssignment.bin` and does use a CPK reader.
    Item 3's `ballControlRate` gets its real identity **and its real stock value, 1.0 — so the
    ruling is violated as shipped and the field must be lowered**; the ricochet question gets a
    **one-sided no**, not a proven one. Item 4's surface is confirmed **and scoped**: global, not
    per-player, 11 of 14 fields live, and two aimable elements rather than 14. The subsystem-map row
    for subsystem 4 in that file must be corrected on all four points.

---

## Negatives — proven absent, do not spend a week on these

* **No CPU difficulty anywhere in `match::anime`.** 0 of 24 `GetParam` sites, 0 of 46
  `Team::GetCurrentLevel`, 0 of 20 `IsEnabled`. Saves and first touches are identical on Beginner and
  Legend. [b]
* **No dt270 read in any `goal_keeper::` method body** — 0 of 268 get-sites image-wide. The save
  family reads no game-constant data in its own code. [b]
* **No RNG in any class method body**: 0 in all 593 `match::anime::action::` bodies, 0 in all 114
  `goal_keeper::` bodies. The per-frame drivers, the state transition and the cancel gates reach zero
  LCG calls even at depth. **But the layer is not RNG-free** — 295 sites live one hop down in unnamed
  anime-band helpers. [b]
* **No ricochet path was found from the ball side — but this negative is ONE-SIDED.** 15-function
  integrator closure reaching no attribute/RNG/dt270, six ground-surface bounce entries and no body
  entry. **Withdrawn from the negative: "`collision::Human` has zero callers image-wide."** It is
  constructed per player — ctor `0x1451305f0` ← factory `0x143ff2210` (`match::AnimeCollision`,
  vftable `0x146b6fb48`, 3 call sites) — and attached at `AnimePlayer+0x47a8`. That object was not
  followed, so "the ball cannot ricochet off a player as physics" is **not proven**. [b]
* **`match::player` does not command the anime action id.** **171 of the 172 direct `E8` call sites**
  of the transition `0x143eb4fd0` are inside `match::anime`; the sole outsider is `0x14414b48d`,
  inside `0x14414b2f0`. (The earlier 184/185 did not state a counting method and does not reproduce
  by direct-call scan.) [b]
* **The anime layer does not read `playerWork+0x8b8` as a struct.** Every `+0x8b8` site in the anime
  band is a **qword pointer load** on a different object. The offset collision is a coincidence and it
  cost one probe a wrong hypothesis until a linear re-scan (rather than a backward byte scan that was
  dropping REX prefixes) corrected it. [b]
* **`0x143ea0ec0` is not the mover**, despite reading the entire command block. It is a field-by-field
  struct copy reached from `game_mode::MatchListener::vf1` — a snapshot/rewind path. Useful only as
  independent corroboration of the block layout. [b]
* **`0x144345c10` is not part of the LCG cluster.** A float math helper; treating it as RNG made a
  negative control appear to fail. Its 7,563-caller neighbour `0x144345ae0` is an angle wrap. [b]
* **`trap.trapLoss`, `trap.trapLossDashOnly`, `trap.reachOut.ballSpeed`, `trap.reachOut.reach`,
  `trap.autoR2.*` have no readers.** (Both `trapLoss` fields are stock **`true`**.) [a/b]
* **`moveMatching.RouteParameter[].accacc`, `.poseWeight` and `.routeWeight` have no readers
  anywhere** — three dead fields of fourteen, and the second independent reason there is no mass
  term in the locomotion block. [b]
* **Per-route turning differentiation does not exist in the shipped data**: `rotSpeed` is 7.0 in all
  14 `RouteParameter` rows and `decRotSpeed` is **0.0** in all 14, with only 5 distinct rows overall.
  [a]
* **`Deflect::vf37` and `SnapUnder::vf37` are inert** (argument multiplied by zero), and
  `Stagger::vf32`'s second Balance term is unreachable below attribute 100. [b]
* **`Injury` has no cancel gate and no cancel data** — all ten `dm_injury_*` motions carry zero keys.
  Nothing there to tune. Same for `Reaction`, `ComeBack`, `CarryBall` and base `Contact`, whose vf14
  is the ret-0 stub. [b]
* **`Animation.bin` may be dead data.** Its path is not one of the 68, and an exhaustive field scan of
  `AnimationData.bin` found nothing correlating with its length. The lengths are physically correct
  either way (they reproduce real gait timings and are exactly 2x PES on unchanged locomotion
  cycles), but the runtime source is `AnimationData.bin`. [a]
* **`HitData.bin`'s record size is not solved.** Every divisor 4..80 under four key extractions fails
  the grouped-and-dummy-free test; at 36 B it gives 24,819 key re-appearances and a 3.24 % dummy
  rate. Not guessed at. [a]
* **`RiseTypeFrameData`'s key field is not solved** — 2.7 % of keys land on `enum_dummy` slots and no
  bias in -3..+5 cleans it up. The 12-byte record and the two float times in seconds are solid. [a]
* **The cancel record's two float lanes are not identified.** Same units and range as the root-motion
  geometry, and `|lane a|` is non-decreasing with the frame on 789 of 1,008 multi-key animations —
  consistent with "root offset at the cancel frame", but at the last key the median `lane_a/blend_z`
  is 0.75 while the median `frame/length` is 0.33, so it is not a simple interpolation. Stated as
  consistent-with, not proven. [a]
* **The poster of contact event kind `0xe` was not found.** A constant scan is hopeless (67
  candidates). Everything downstream of the event is decoded; the event rate is not. [b]
* **The trailing-bytes question is NOT load-bearing** (corrected). Lowering the header `csize` to the
  true stream length moves no byte and is the primary route; all 128 shipped dt230 containers have
  `csize` exact (0 `unused_data`), so trailing bytes inside the stream have no precedent. What is
  genuinely untested is whether anything cross-checks `csize + 16` against the CPK entry size.
* **The project's WESYS packer cannot write a dt230 container.** `pack_wesys_container` supports key
  nibbles 1 and 2 only (dt230 is **0**), always writes flag `0x83` and encrypts (dt230 is `0x81`,
  plain), and takes only a zlib level (L1 = 61,992 against a 61,433 slot). `ml_deploy.py` also uses
  `cricodecs.cpk.load()` and is hardcoded to dt200 / `PlayerAssignment.bin`. The motion-asset write
  route is **located, not yet writable**. [a/b]
* **Saturation disclosure**: a plain forward closure from the save family merges at ~33,200 functions
  and gives the same answer for almost any root including the positive control. That result was
  discarded, not reported as a finding.
* **No closure that *is* reported saturated**: cap 20,000, largest 2,457, explored counts differ per
  root (4 to 2,457).

---

## Class status — all 131 `match::anime` classes plus the three `match::MbInfo*` and `match::AnimeCollision`

`reg id` is the `ActionManager+0x1b20` index where it was resolved from the constructor walk.
"gate-only" means the class's entry conditions or one gate were read but no body was decoded.
| class | slots | vftable | reg id | status | note |
|---|---|---|---|---|---|
| `match::AnimeCollision` | 1 | `0x146b6fb48` | - | **gate-only, added 2026-09-20** | **Namespace is `match::`.** The per-player collision body, missed by the original class sweep and by the "ricochets: settled NO" negative that rested on it. Factory `0x143ff2210` news 0x28 bytes and calls `collision::Human`'s ctor `0x1451305f0` (vftable `0x147484f80`, 1 method), storing it at `+8`; 3 call sites `0x14410ba5d` / `0x14410bb37` / `0x14410bbe7`, each attaching the result at `AnimePlayer+0x47a8` and then calling `0x143eb4ed0` in the anime band. Setter `0x143ff22d0`, dtor `0x143ff2270`. **Not opened** — Open 23. |
| `match::MbInfoLoadThread` | 2 | `0x146b45128` | - | decoded | Hung off `manager+0xd0`. State machine `0x143e95410`; per-table group-and-store routines `0x143e95530` (36 B stride), `0x143e958d0` (20 B), `0x143e95e30` (12 B). Not a JSON parser - a fixed-stride record walker. |
| `match::MbInfoManager` | 1 | `0x146b45118` | - | decoded | **Namespace is `match::`, not `match::anime::`.** Singleton at `0x14868a900`, built lazily by `0x143e940a0` (1,005 callers). Array of **7,883 records of 0x1f8 bytes** at `+8`; each record = 21 `std::vector<Event*>`, one per the 21 `Mbinfo/bin/*.bin` paths. Count `0x143e9a390` -> `0x143e9a1a0` (21-arm switch); decoders `0x143e99b70` (ch3), `0x143e99e20` (ch5), `0x143e9b220` (ch6), `0x143e9a3d0` (ch7). |
| `match::MbInfoManagerBase` | 1 | `0x146b45ba0` | - | decoded | The accessor family `0x143e99920`/`0x143e99990`/`0x143e99a00`/`0x143e99a70` and ~20 siblings: `cmp edx,0x1ecb; imul rax,rax,0x1f8; add rax,[rcx+8]`. Vectors hold POINTERS into the decompressed blob; fields are decoded at the consumer, not at load. |
| `anime::ActionManager` | 1 | `0x146b4cd08` | - | decoded | Holds all 113 action objects inline; 113-entry id->handler table at `+0x1b20`, lookup `0x143eee720`, table fill `0x143eee750`, ctor `0x143e9eb00`, outer ctor `0x143e9fb40`. Object at `AnimePlayer+0xd30`. |
| `anime::AnimeTableLoadThread` | 2 | `0x146b44b10` | - | out-of-scope | Not opened. **Twelve files in `AnimeTable/bin` duplicate Mbinfo tables whose paths the exe never names**, including the +2-frame CancelData decoy. Which loader, if any, reads them is open. |
| `anime::AnimeTableManager` | 1 | `0x146b44b00` | - | out-of-scope | Not opened. The `Movetable`/`Idletable`/`CategorizedMoveTable`/`ParametricBlendTable` side of animation selection was never reached - the path decoded here goes through MbInfoManager and the `0x143ee47c0` search instead. |
| `anime::AnimeTableManagerBase` | 1 | `0x146b4e098` | - | out-of-scope | Not opened. |
| `anime::DribbleMatchingLoder` | 2 | `0x146b44420` | - | listed-only | Loads `Matching/dribbleMatching`; not opened. |
| `anime::MMDBLoadThread` | 2 | `0x146b443e0` | - | listed-only | Loader thread; not opened. |
| `anime::MoveMatchingLoder` | 2 | `0x146b44408` | - | listed-only | Loads `Matching/MoveMatching`; not opened. Distinct from the dt270 `moveMatching` object. |
| `anime::ParsedEyesTarget` | 2 | `0x146b47400` | - | listed-only | `EyesTarget/bin/Eyestarget.bin` is 31,532 B = **exactly 7,883 u32s**, one per animation - an independent confirmation that table position IS the animation id. |
| `anime::ParsedJsonAnimeTable` | 2 | `0x146b44b40` | - | listed-only | Not opened. |
| `anime::ParsedJsonCategorizedMoveTable` | 3 | `0x146b4e0a8` | - | listed-only | Not opened. |
| `anime::ParsedJsonCategorizedMoveTableInit` | 3 | `0x146b4e0c8` | - | listed-only | Not opened. |
| `anime::ParsedJsonCategorizedMoveTableStatus` | 3 | `0x146b4e0e8` | - | listed-only | Not opened. |
| `anime::ParsedJsonDribbleMachingPivotHitInfo` | 3 | `0x146b4e1a8` | - | listed-only | Not opened. |
| `anime::ParsedJsonDribbleMatching` | 3 | `0x146b4e108` | - | listed-only | Not opened. |
| `anime::ParsedJsonDribbleMotionData` | 3 | `0x146b4e1c8` | - | listed-only | Not opened. |
| `anime::ParsedJsonFootData` | 3 | `0x146b4e1e8` | - | listed-only | Not opened. |
| `anime::ParsedJsonLoopMoveMotion` | 3 | `0x146b4e128` | - | listed-only | Not opened. |
| `anime::ParsedJsonNewDribbleInfo` | 3 | `0x146b4e208` | - | listed-only | Not opened. |
| `anime::ParsedJsonOOPDemoData` | 3 | `0x146b4e168` | - | listed-only | Not opened. |
| `anime::ParsedJsonParametricBlendTable` | 2 | `0x146b46200` | - | listed-only | Not opened. |
| `anime::ParsedJsonPlayerID` | 2 | `0x146b46840` | - | listed-only | Not opened. |
| `anime::ParsedJsonRiseTypeFrameData` | 3 | `0x146b4e228` | - | listed-only | Not opened. |
| `anime::ParsedJsonSeamlessDemoData` | 3 | `0x146b4e188` | - | listed-only | Not opened. |
| `anime::ParsedJsonSuperiorKickTable` | 2 | `0x146b44b58` | - | listed-only | Not opened. |
| `anime::ParsedJsonoopDemoAnime` | 3 | `0x146b4e148` | - | listed-only | Not opened. |
| `BallPersonAction` | 29 | `0x146b6a238` | - | listed-only | Non-gameplay. |
| `BallPersonMove` | 29 | `0x146b6a8c8` | - | listed-only | Non-gameplay. |
| `Base` | 29 | `0x146b52860` | - | decoded | The 29-slot contract, 74 classes. Ctor `0x143ef54a0`, object 0x30 bytes, **no action-id field**. Shared slot 24 `0x143ef5ec0`, 25 `0x143ef6190`, 26 `0x143ef5610` - the command-block consumers. |
| `Block` | 29 | `0x146b47fa8` | 0xe | gate-only | vf2 `0x143efb9a0` delegates to slot 14 at `0x143efb9e6`. vf14 `0x143efad30` not decoded. 116 `block*` motions, first cancel median 0.683 s of a 1.00 s motion. |
| `CCancelTrapAnimeInfo` | 24 | `0x146b7c108` | - | gate-only | Constructed at `0x14404c545`. Overrides slots 2, 3, 5 (`0x14404dd30`), 7, 10, 16, 23 - the most-overridden sibling. |
| `CFastTrapAnimeInfo` | 24 | `0x146b7c040` | - | gate-only | Constructed at `0x14404c575`. Overrides only slot 2 (its destructor) - a data variant, not a distinct algorithm. |
| `CLiftTrapAnimeInfo` | 24 | `0x146b7bd20` | - | gate-only | Overrides slots 2, 5 (`0x14404df90`), 9 (`0x14404f710`), 11, 12, 14. |
| `CSlideTrapAnimeInfo` | 24 | `0x146b7bf78` | - | gate-only | Overrides slots 2, 5 (`0x14404e1c0`), 13. |
| `CStaggerAnimeInfo` | 24 | `0x146b7beb0` | - | gate-only | Constructed at `0x14404c615`; the chooser reads `trap.staggerTrapHeight` at `0x143f83848` in the same function. Overrides only slot 2. |
| `CThroughAnimeInfo` | 24 | `0x146b7bde8` | - | gate-only | Overrides slots 0, 1, 2, 7, 12, 13, 22 - the only sibling with its own destructor pair. |
| `CTrapAnimeInfo` | 24 | `0x146b62118` | - | decoded | 24-slot contract, no base. vf5 `0x14404e290` reads `trap.reactionTrapBall.checkTime`/`.use`. Built x4 in `0x143f834b0` plus `0x143f83ac0`/`0x143f840d0`/`0x143f84530`. The seven siblings differ only at slots 2,3,5,7,9,10,11,12,13,14,16,22,23. |
| `CTrapAnimePlayer` | 1 | `0x146b622a8` | - | decoded | **ONE slot** (destructor `0x143f853d0`). No behaviour at all - a data holder. Constructed twice inside `0x143f834b0`. Anyone looking for trap logic here will find none. |
| `CTrapDistAnimeInfo` | 24 | `0x146b621e0` | - | gate-only | Overrides only slot 2; identical to the base everywhere else. |
| `CameraPersonAction` | 29 | `0x146b6d428` | 0x6f | listed-only | Non-gameplay. |
| `CameraPersonMove` | 29 | `0x146b4cc18` | - | listed-only | Non-gameplay. |
| `CarryBall` | 29 | `0x146b6c250` | - | gate-only | vf14 = the `xor al,al` stub, never cancellable. Constructed at `0x143fc9c20`. No attribute read found. Not decoded. |
| `CoachAction` | 29 | `0x146b6af58` | - | listed-only | Non-gameplay. |
| `CoachMove` | 29 | `0x146b6b5e8` | - | listed-only | Non-gameplay. |
| `ComeBack` | 29 | `0x146b4c678` | 0x64 | gate-only | vf14 = the `xor al,al` stub, never cancellable. vf2 `0x143fc1bb0`, vf4 `0x143fc1a40`. No `comeback*` motion prefix; the get-ups are `rise*`/`gkrise*`. |
| `Contact` | 35 | `0x146b48098` | - | decoded | 35 slots. Shared canStart `0x143f010b0` decoded in full (base `currentKind-4`, 5 cases). vf4 `0x143efef70` hands the command block to slot 26. Own vf14 is the `xor al,al` stub - a base Contact is never cancellable. |
| `CornerKick` | 29 | `0x146b486f8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `CornerKickLoop` | 29 | `0x146b48608` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `DemoAction` | 29 | `0x146b54850` | - | listed-only | Cut-scene presentation. Not opened. |
| `DemoMove` | 29 | `0x146b54ef0` | - | listed-only | Cut-scene presentation. Not opened. |
| `DemoTimeUp` | 29 | `0x146b4c0d8` | - | listed-only | Not opened. |
| `Dive` | 35 | `0x146b483f8` | 0xf | decoded | Derives FallDown; shares its vf10/vf14/vf30. Treated identically to FallDown by every canStart table checked. |
| `Dodge` | 29 | `0x146b48ab8` | 0x15 | gate-only | vf2 `0x143f1b860`, byte table at `0x143f1b994`. vf14 `0x143f19ad0` not decoded. 16 `dodge*` motions, all single-key, first cancel median 0.600 s. |
| `Dribble` | 31 | `0x146b4ba38` | 4 | decoded | vf4 `0x143f98890` -> `0x143f93b90` -> the motion-matching core `0x143ec93f0` and (via `0x144082060`) the locomotion compile `0x143ec3ed0`. vf2 table `0x143f99f60`: FallDown and Dive entries = 3 = REFUSE. 31 slots. |
| `FallDown` | 35 | `0x146b482d8` | 0x11 | decoded | vf14 `0x143f00d00`: kind-blind; FIRST key when `byte[anime+0x2bdc]==2`, LAST otherwise, and **no `key>0` guard** (unlike Stagger). vf29 = `mov eax,0x11; ret`. vf30 `0x143effa40` (711 ins, the motion selector) not decoded. |
| `Feint` | 29 | `0x146b4bb38` | 0x12 | decoded | vf2 `0x143fabac0`, table `0x143fabb44`, 2 cases; Stagger entry = 1 = refuse, stock. vf4 `0x143fa15a0`. |
| `FreeKick` | 29 | `0x146b48c98` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `FreeKick2ndCede` | 29 | `0x146b48e78` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `FreeKick2ndLoop` | 29 | `0x146b48d88` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `FreeKick2ndPassToKicker` | 29 | `0x146b48f68` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `FreeKickLoop` | 29 | `0x146b48ba8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `GoalEvent` | 29 | `0x146b4c1c8` | - | listed-only | Celebration presentation. Not opened. |
| `GoalEventFinishAction` | 29 | `0x146b4c3a8` | - | listed-only | Not opened. |
| `GoalEventRunningAction` | 29 | `0x146b4c2b8` | - | listed-only | Not opened. |
| `GoalKickLongPass` | 30 | `0x146b4a0d8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `GoalKickShortPass` | 30 | `0x146b49fe0` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `GoalKickStandby` | 29 | `0x146b49ef0` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `GoalMove` | 29 | `0x146b4c588` | - | listed-only | Not opened. |
| `Injury` | 29 | `0x146b4c498` | 0x63 | decoded | **Not a Contact subclass** (InjuryRetryWork < Base, 29 slots). vf14 is the `xor al,al` stub and all 10 `dm_injury_*` motions carry zero cancel keys: an injury animation runs to completion by construction. Nothing here is tunable. |
| `InplayDemoContact` | 29 | `0x146b4bd18` | 0x5c | gate-only | vf4 `0x143fb6960` calls **both** slot 25 and slot 26 with the command block. |
| `InplayDemoFatigueInjury` | 29 | `0x146b4bef8` | 0x5e | gate-only | One of the two take-overs `Move::vf4` polls every frame before doing any locomotion work. |
| `InplayDemoKickFailed` | 29 | `0x146b4be08` | - | listed-only | Not opened. |
| `InplayDemoMove` | 29 | `0x146b4bfe8` | 0x5f | gate-only | The second take-over `Move::vf4` polls. |
| `Jostle` | 29 | `0x146b4a3b8` | 0x54 | gate-only | **LIVE, contrary to the PES chapter.** Constructed at `0x143e9f65b` into ActionManager+0x1360. vf1 `0x143f5b4f0`, vf2 `0x143f60240` (238 ins, compare chain), vf6 `0x143f55670`, vf13 `0x143f5e0f0`, vf14 `0x143f5d6d0` (276 ins, a real gate), vf18 `0x143f67240`. **No body read.** 223 `js_*` motions tabulated. |
| `Judge` | 29 | `0x146b4b678` | 0x68 | listed-only | Referee presentation. Non-gameplay; the foul decision is `match::ai::Judge` / the referee, not this. |
| `Kick` | 29 | `0x146b4b948` | 8, 9, 0xa | gate-only | vf2 `0x143ee21b0`; vf4 `0x143ed38a0` hands the command block to slot 26 at `0x143ed390f`; vf8 reaches the kick builder `0x14401a900` (decoded elsewhere, not touched). 621 `kick_*` motions, 602 with exactly one cancel key. |
| `KickoffKicker` | 29 | `0x146b4a598` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `KickoffKickerLoop` | 29 | `0x146b4a4a8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `KickoffOther` | 29 | `0x146b4a778` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `KickoffReceiver` | 29 | `0x146b4a688` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `LinesmanAction` | 29 | `0x146b4b858` | 0x66 | listed-only | Non-gameplay. |
| `LinesmanMove` | 29 | `0x146b4b768` | - | listed-only | Non-gameplay. |
| `Move` | 29 | `0x146b4a868` | 2 | decoded | THE MOVER entry. vf4 `0x143f68740` polls demo take-overs 0x5e/0x5f then tail-calls `0x143eebdf0` -> `0x143ee47c0` (30 KB motion-matching search). vf2 `0x143f688c0` is a compare chain, not a table. vf14 `0x143f68800` = canCancel on channel 5. |
| `OutofPlay` | 29 | `0x146b4bc28` | 0x5b | gate-only | vf4 `0x143fae450` passes the command block to slot 25 at `0x143faee1f`. |
| `PKDemo` | 29 | `0x146b4c768` | - | listed-only | Not opened. |
| `PenaltyKick` | 29 | `0x146b4aa48` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `PenaltyKickLoop` | 29 | `0x146b4a958` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `PkWait` | 29 | `0x146b4ab38` | - | listed-only | Not opened. |
| `PostManLoop` | 29 | `0x146b489c8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `QuickRestartKick` | 29 | `0x146b49620` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `QuickRestartReady` | 29 | `0x146b49530` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `Reaction` | 29 | `0x146b4ac28` | 0x13, 0x14 | gate-only | vf2 `0x143f6d870` delegates to slot 14. **vf14 is the `xor al,al` stub** - once a Reaction starts nothing interrupts it. 19 `reaction*` motions. |
| `RecieveBall` | 29 | `0x146b4c858` | 0x16 | gate-only | vf4 `0x143fc6d30` and vf13 `0x143fc82f0` both reach the ball integrator `0x14408d0f0` at depth 2. vf13 reads dt270. Reads no ball-control attribute. |
| `Referee` | 29 | `0x146b4b588` | - | listed-only | Base of Judge/Linesman*. Non-gameplay. |
| `ResetIdle` | 29 | `0x146b4ad18` | 1 | gate-only | The fallback handler the registry returns for any unwired or out-of-range id. **BOTH vf2 and vf14 are the `xor al,al` stub** - read literally it can never start and can never be interrupted. Flagged, not explained. |
| `Restart` | 29 | `0x146b48518` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `SeamlessCornerKick` | 29 | `0x146b488d8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `SeamlessCornerKickReady` | 29 | `0x146b487e8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `SeamlessDribble` | 29 | `0x146b4cb28` | - | gate-only | One of only three classes that touch `+0x8b8` outside slot 4 (here slot 10). Not decoded. |
| `SeamlessGoalKick` | 30 | `0x146b4a2c0` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `SeamlessGoalKickReady` | 29 | `0x146b4a1d0` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `SeamlessPass` | 29 | `0x146b4ca38` | - | listed-only | Not opened. |
| `SeamlessPassReady` | 29 | `0x146b4c948` | - | gate-only | Touches `+0x8b8` in slot 10. Not decoded. |
| `SeamlessThrowin` | 29 | `0x146b4b3a8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `Sliding` | 29 | `0x146b4ae08` | 0xb, 0xc | decoded | vf14 `0x143f70360` is FallDown::vf14 **with one compare constant changed** (4 instead of 2). vf2 table `0x143f70590`, Stagger entry = 2 = refuse (stock in both images). |
| `Stagger` | 35 | `0x146b481b8` | 0x10 | decoded | vf14 `0x143f00de0` decoded end to end: channel-5 first key; **request kind 4 (Dribble) falls to the channel-3 END when the motion has <=1 cancel key**; channel-6 branch on property bit 9; bit-16 branch for motions 3255/3259 (the two `_pulled` staggers). vf29 = `mov eax,0x10; ret`. vf32 `0x143f007b0` Balance term. |
| `StepMove` | 29 | `0x146b4aef8` | 3 | decoded | vf4 `0x143f72aa0`, same shape as Move::vf4; shares Move's slot-18 body `0x143f68930`. vf2 `0x143f72b30`. |
| `Tackle` | 29 | `0x146b4afe8` | 0xd | decoded | vf2 `0x143f7ca30`, table `0x143f7cae0`, 4 cases; Stagger entry = 3 = REFUSE, stock. vf14 `0x143f7ba80` not decoded. |
| `ThrowinLong` | 29 | `0x146b4b2b8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `ThrowinLoop` | 29 | `0x146b4b0d8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `ThrowinNormal` | 29 | `0x146b4b1c8` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `Trap` | 29 | `0x146b4b498` | - | decoded | vf4 `0x143f86d50` is the first-touch body and the root of the `ballControlRate` path. vf14 `0x143f88840` gates on channel 6 **and** three dt270 `trap` fields. vf19 `0x143f87840` / vf22 `0x143f874d0` read Tight Possession (0x19). |
| `WallJump` | 30 | `0x146b49150` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `WallLoop` | 30 | `0x146b49058` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `WallNotJump` | 30 | `0x146b49248` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `WallNotRunOut` | 30 | `0x146b49438` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `WallRunOut` | 30 | `0x146b49340` | - | listed-only | Restart family - classified in the set-piece work, not opened here. |
| `goal_keeper::AfterCatchBase` | 33 | `0x146b49ad0` | - | listed-only | 33 slots, base of PuntKick and Throw. Not decoded. |
| `goal_keeper::Block` | 50 | `0x146b59148` | 0x49 | decoded | Ctor `0x143f4a520`. Reads GK Reach **RAW** - the only save where Reach is linear, and the widest multiplier in the family, 1.000..1.295. |
| `goal_keeper::BodyFeint` | 29 | `0x146b49710` | - | listed-only | ActionManager+0x1298. Not decoded. |
| `goal_keeper::Catch` | 50 | `0x146b598e0` | 0x44 | decoded | Ctor `0x143f4a7c0`. Reads GK Catching; under 50 km/h switches to `max(Catching,Reflexes,Reach)` remapped into 73..89. Multiplier 0.950..1.171. Lead time 60 frames. |
| `goal_keeper::Deflect` | 50 | `0x146b5a018` | 0x46 | decoded | Ctor `0x143f4ad20`. Reflexes when sub in {1,4,5} (1.025..1.130), else Reach (0.938..1.121). Also reads Reach in vf35 `0x143f4add0`, outside the selector. Lead time 90/48/60 frames. **vf37 `0x143f4ad50` multiplies its argument by ZERO.** |
| `goal_keeper::DropBall` | 29 | `0x146b49800` | - | listed-only | ActionManager+0x1238. Not decoded. |
| `goal_keeper::PickupBall` | 29 | `0x146b498f0` | 0x51 | gate-only | vf4 `0x143f26ea0` loads the command-block pointer. Its match::player counterpart `ActionKeeperPickupBall` has no body at all. |
| `goal_keeper::PreSaving` | 29 | `0x146b499e0` | - | gate-only | The arming state; the trigger is on the executor side (`ActionKeeperPreSaveOperation::slot4 0x14422e6a0`, in player-executors.md). Body not decoded. |
| `goal_keeper::Punch` | 50 | `0x146b5aea0` | 0x45 | decoded | Ctor `0x143f4b800`. Reads GK Parrying (Clearances, 0x24) linearly. Multiplier 0.900..1.121. Lead time 60 frames. vf37 uses a real 1.5 constant. |
| `goal_keeper::PuntKick` | 33 | `0x146b49be0` | - | listed-only | 33 slots, derives AfterCatchBase; ActionManager+0x10f8. Not decoded. |
| `goal_keeper::SavingBase` | 50 | `0x146b58840` | - | decoded | Base's 29 slots + 21 own. Ctor `0x143f2ec90` stores the action id at `saving+0x30`. vf4 `0x143f305c0` save body, vf13 `0x143f32880`, vf2 `0x143f34320`, vf14 `0x143f32410`, vf47 `0x143f30f90` (default motion 0xb9c). Slots 29 and 36 are pure (thunk `0x144f83074`). |
| `goal_keeper::ScoopOut` | 50 | `0x146b5a758` | 0x48 | decoded | Ctor `0x143f4b140`. Reads GK Reach with the 52..89 remap. Lead time 30 or 60 frames. vf37 uses a real -0.5. |
| `goal_keeper::SeeOff` | 29 | `0x146b49cf0` | - | listed-only | ActionManager+0x11d8. Not decoded. |
| `goal_keeper::SnapUnder` | 50 | `0x146b5c370` | 0x47 | decoded | Ctor `0x143f4ec00`. Shares the 0x44 jump-table arm, so it reads GK Catching. Lead time **15 frames (0.25 s)** - the tightest in the family. **vf37 `0x143f4fb50` multiplies its argument by ZERO.** |
| `goal_keeper::Throw` | 33 | `0x146b49de0` | - | listed-only | 33 slots, derives AfterCatchBase; ActionManager+0x1168. Not decoded. |

<!-- rows: 134 -->

---

## Open questions

Ordered by what they unblock.

1. **Does the game's WESYS reader tolerate trailing bytes after the deflate final block, or must the
   header's `csize` be lowered to the true stream length?** The entire same-length write path depends
   on it and it is untested. **One throwaway edit answers it**, and nothing should ship before it.
2. **The poster of contact event kind `0xe`.** Until it is found, "more contact produces more fouls
   without touching a referee constant" is proven downstream of the event and unproven at the event.
   A constant scan returns 67 candidates; the right approach is to walk back from
   `match::MatchControl::vf1` (`0x143c56a90`), or to breakpoint the referee handler `0x143d18570` at
   runtime with `tools/live_patch.py` and read the stack.
3. **`Stagger::vf30` (`0x143effd70`, 512 ins) and `FallDown::vf30` (`0x143effa40`, 711 ins) — the
   motion SELECTORS.** The cancel data says how long each of the 69 staggers and 87 falls lasts; the
   selector says **which one you get**. That is the other half of "players properly falling over, not
   stumbling" and it is the highest-value unread pair in the subsystem.
4. **`match::anime::action::Jostle`'s body.** It is live (contrary to the PES chapter), it has a real
   `canStart` (`0x143f60240`, 238 ins) and a real cancel gate (`0x143f5d6d0`, 276 ins), 223 `js_*`
   motions are tabulated and waiting, and **nobody has read a line of it**. Given the PES chapter's
   conclusion rested on it being absent, this is the highest-value single function in the contact
   story.
5. **What the 0.90–1.40 keeper multiplier physically scales.** It is passed into `0x143f3c1f0` and
   combined with per-motion caps keyed on the save animation id, but it was never followed to a
   distance, a velocity or a playback rate. The *ratio* between keepers is proven; the *units* are
   not.
6. **What selects the `RouteParameter` index 0..13.** Almost certainly the executor's movement-class
   int (`block+0x58`), but the trace from the block to the `imul reg, idx, 0x38` sites was not made.
   **That link is the last step before realism item 4 can be tuned per movement class rather than
   globally.**
7. **`0x143ee47c0` (30 KB) — the motion-matching search.** Only sampled (call histogram plus the three
   RNG sites). The candidate-scoring maths is the last unopened box in the gameplay map.
8. **`Mbinfo/bin/HitData.bin`** — 1,061,316 B, the largest contact table, 5.6x PES, record size
   unsolved. It is the IK ball-contact geometry and the remaining piece of "contact is warped onto
   the real ball rather than snapping it".
9. **`Mbinfo/bin/AnimationData.bin` beyond the end-frame field** — 36 B x 7,073, index at bits
   13..25, path **is** named by the exe. The likely live home of per-animation frame metadata now
   that `Animation.bin` looks legacy.
10. **The shared base slots 24, 25 and 26** (`0x143ef5ec0` / `0x143ef6190` / `0x143ef5610`, 123 / 635
    / 376 instructions) were identified as the command-block consumers by their argument offsets, but
    their bodies were not decoded. **Slot 25 is the single busiest shared function in the contract**
    and deserves its own pass.
11. **`Move::vf4` loads its block pointer as `mov r8,[rsi+0x8b8]` where `Contact::vf4` uses `rsi`
    directly.** Both cannot be the same object. Either arg 3 differs by call path or the struct is
    larger than the 0x564 the driver writes. This does not affect the slot-25/26 offset match, which
    stands on its own.
12. **What object `playerWork` is.** Command struct at `+0x8b8`, sub-objects at `+0x1a90`/`+0x1a98`,
    a route array at `+0x1aa0`, scratch at `+0x1a28..+0x1a3c`. No vtable, no RTTI name recovered.
13. **`AnimePlayer+0x2bd8`, `+0x2bdc`, `+0x2bf5`, `+0xad8`** are read as gates all over the contract
    (`Contact::vf4` branches on `+0x2bdc`; `FallDown::vf14` compares it against 2 and `Sliding::vf14`
    against 4; the skill-card helper gates on `+0x2bd8 <= 0x15`). **None of them was identified**, and
    `+0x2bdc` in particular decides first-key-versus-last-key on every fall in the game.
14. **The 90 unnamed anime-band functions** that make up the bulk of the 287 skill-card sites. Which
    cards affect which motions is the natural follow-up and is entirely unexplored.
15. **The `goal_keeper::` 50-slot contract** beyond the six save bodies, the 33-slot `AfterCatchBase`
    family, and the `sub` argument that flips Deflect between a Reflexes save and a Reach save — the
    single largest branch in the keeper model, and its source is upstream in `match::player`.
16. **What global float `0x14533ea80` returns** (from `.bss` at `0x148c22abc`, read 7,615 times
    image-wide, including inside both frame decoders). If it is a global animation-rate scalar rather
    than the frame rate, it is itself a very large tunable. It cannot be read statically.
17. **Which of the 8 observed `DemoConnectData` `end_state` values maps to which of PES 2014's 14
    named postures.** The histogram shapes match; the label mapping does not exist.
18. **Why `dt230` ships twelve AnimeTable duplicates of Mbinfo tables**, including a CancelData copy
    offset by exactly +2 in the stored field (= **+4 decoded frames**), when the exe names none of their
    paths. If a second loader reads
    them the +2 fork matters; if nothing does, they are ~500 KB of dead weight and a trap.
19. **The 660 `enum_dummy` reserved ids.** They are ids no table references. If any is a hole a new
    animation could be dropped into, that is the **only** conceivable route to *adding* motion rather
    than retiming it — worth ten minutes before item 5 is declared "tune only".
20. **`match::anime::AnimeTableManager` and the 17 `ParsedJson*` loaders** — the `Movetable` /
    `Idletable` / `CategorizedMoveTable` / `ParametricBlendTable` side of animation selection was
    never reached.
21. **The 35-slot Contact/Stagger/FallDown/Dive contract and the 31-slot Dribble contract** are still
    unnamed beyond slots 29/30/32 — the remaining structural gaps in the map.
22. **What SELECTS a trap type.** `0x143f834b0` *builds* eight `CTrap*AnimeInfo` candidates and
    `CTrapAnimePlayer` ×2; nothing decoded scores or compares them. The 24-slot contract's
    overridden slots (2, 3, 5, 7, 9–14, 16, 22, 23) and the builder `0x143f87ad0` were not opened.
    Added by the 2026-09-20 repair pass, which found the chapter had called candidate construction
    "selection".
23. **`match::AnimeCollision` (vftable `0x146b6fb48`, ctor `0x143ff2210`, 3 call sites
    `0x14410ba5d`/`0x14410bb37`/`0x14410bbe7`)** owns a `collision::Human` at `+8` and is attached
    at `AnimePlayer+0x47a8`. It is the per-player collision body and it was never opened. Until it
    is, the ricochet negative is one-sided — this is the highest-value open item for realism item 3.
24. **The consumer of `0x143ec3ed0`'s `block+0xc` / `block+0x10`** (the 15.0f / 22.5f immediates).
    Both are rescaled by `xmm8` on the function's high branch and neither is a gait speed; without a
    consumer their effect size is unknown and they must not be sold as a clean lever.
25. **What drives the `RouteParameter[]` index in `0x143ec8fd0` / `0x143ec93f0`** — the only two
    runtime-indexed readers. The other two consumers are pinned to elements 5 and 0, so this is the
    whole of "aim a route class deliberately".

---

## Harnesses and artefacts

| file | what |
|---|---|
| `build/anime_names.json` | 7,883 animation names in motion-id order, extracted from `0x148027310` |
| `build/anime_motion_tables.json` | 7,061 motions: name + end frame + cancel frames, under the verified decode rule |
| `tools/anime_motion_tables.py` | regenerator — re-runs from the PRISTINE exe plus an extracted `Mbinfo/bin` directory and reproduces both files |
| `tools/mbinfo_ef.py` | `lockout` (the contact table in seconds), `cancel --grep`, `connect --grep` |
| `tools/data/ef_anime_names.json` | 7,883 body + 646 face + 2,972 aux names |
| `tools/emu_gk_save_quality.py` | Unicorn harness over `0x144032870`, stubbing the six external calls |
| `tools/mbinfo.py` | **PES 2014 only.** Its eFootball `cancel` output is garbage — it is still on the 4-byte PES rule |
| `docs/anime-keeper-and-first-touch.md` | long form of the keeper save family and the trap group |

**CPK targets, located byte-exactly and read-only** (all in
`C:/Program Files (x86)/Steam/steamapps/common/eFootball/cpk/dt230_console_win.cpk`, each occurring
exactly once): `Mbinfo/bin/CancelData.bin` **@0xb5bf800**, `Mbinfo/bin/HoldData.bin` @0xb670000,
`Mbinfo/bin/DemoConnectData.bin` @0xb5d2800, `AnimeTable/bin/Risetypeframedata.bin` @0xa72000,
`Mbinfo/bin/Animation.bin` @0xb56e000.
