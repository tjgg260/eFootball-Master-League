# The pad — `match::pad` (2026-09-20)

Everything between the controller and a command: the raw input ring, the logical button space, the
72 `ThinkUnit` query objects, the temporal pattern engine that decides what a *tap* is, how a held
button becomes kick power, which players the pad can reach at all, and what a data-only edit can
change. **73 RTTI classes** in the namespace — 72 concrete units plus `ThinkUnitBase` — plus the
`match::Command` band that drives them. [b]

This chapter **consolidates** four documents: the probe output
[registry-pad-command-channel.md](registry-pad-command-channel.md) (683 lines, given as fact by the
three probes that followed it), [pad-node-kinds-and-unit-modes.md](pad-node-kinds-and-unit-modes.md),
[pad-power-and-cursor.md](pad-power-and-cursor.md) and
[control-source-and-human-vs-cpu.md](control-source-and-human-vs-cpu.md). Where they disagree, the
disagreement is named and resolved here rather than averaged; every such case is listed in
[§ 14 Corrections](#14-corrections-to-finished-chapters). Two load-bearing facts were re-derived
from PRISTINE **for this write-up** and are marked *(verified 2026-09-20 for this chapter)*.

> **It does NOT supersede them as an address-level reference.** An earlier draft said "supersedes",
> and that was wrong: a set-difference of hex tokens shows **82 of the 197 addresses** in
> `registry-pad-command-channel.md` appear nowhere here (and 21 / 36 / 57 of the other three's).
> The load-bearing ones have been re-imported — `ThinkUnitFriendPress`'s `vf8` and its three chains
> (§ 13.4), the `match::Command` / `match::CommandPlayer` registry-ref field map (§ 16.1), the
> `UCommandOutput` read census (§ 8.3) and chain B's TLS guard (§ 13.3) — but the four probe files
> **stay in the tree and stay authoritative for anything this chapter does not repeat.**
> *(Repair pass 2026-09-20.)*

Evidence levels: **a-emulated** (the game's own bytes executed under Unicorn with controlled
inputs), **b-disassembly** (followed instruction by instruction; extents from the *chained-unwind*
`.pdata` walk, never the touching-range merge), **c-inferred** (structural reasoning only).
Addresses are VAs at base `0x140000000`, no ASLR, decoded from `eFootball.exe.PRISTINE`.

**Image hygiene — re-measured for this chapter.** The older pad probe carried a warning that the
installed image differed from PRISTINE in 909 bytes / 90 groups, one of which (`0x144311572` /
`0x144311579`, two re-aimed `disp32` constant references inside the analog helper `0x144310ea0`)
landed in the pad band. **That is no longer true.** A full SHA-256 of both images today:

```
INSTALLED  cf0a0406fa77461256b1c53454d1b37ff7ccc8ca8a185621ca327594d96a6fd5
PRISTINE   cf0a0406fa77461256b1c53454d1b37ff7ccc8ca8a185621ca327594d96a6fd5   <- identical
STOCK      a6911e9613750df33d10598d6493db629b03195c3ec1d011704cd1e853d8c6e4
```

The installed exe has been reverted and is now **byte-identical to PRISTINE**, so nothing in this
chapter is reading modified bytes and no A/B caveat applies. PRISTINE is *not* stock: a byte diff
against `eFootball.exe.STOCK` returns **exactly two bytes**, file offset `0x6e6eee3`/`0x6e6eee4`,
`pes22-game.cs.ko…` → `pes99-game.cs.ko…` — a hostname edit that severs matchmaking and touches no
gameplay code. Do not call PRISTINE "stock". *(verified 2026-09-20 for this chapter)* [b]

Companion chapters: [player-executors.md](player-executors.md) (what happens to a command once it
lands), [ball-carrier-brain.md](ball-carrier-brain.md) (`match::ai::bp` — **corrected by § 7 here**),
[registry-blackboard.md](registry-blackboard.md) (the record store this rides on),
[anime-actions.md](anime-actions.md) (what the animation layer does with the result).

> **Read [§ 14 Corrections](#14-corrections-to-finished-chapters) before leaning on anything
> written about this subsystem before today.** Four widely-repeated beliefs are wrong:
> node kinds 1 and 3 are **swapped** in every prior write-up; the "15-way control-source jump table"
> has **three** targets, not fifteen; the gesture table is **16 rows in three tables**, not five in
> one; and `byte[UMatchInfo+0x41f6+idx]` — glossed in `ball-carrier-brain.md` as "the player is on
> the ball" — is the **human-control-allocation** byte, which is what answers the *mechanism* half
> of whether a human's carrier runs the AI brain. (The *"and the cursor player is always inside
> that allocation"* half is **[c]**, not [b] — see § 7.5 and § 14.A item 11.)
>
> **Then read [§ 14.A](#14a-corrections-to-this-chapter--repair-pass-2026-09-20), the corrections to
> this chapter's own first draft.** Twenty-four of them, including two that would have produced a
> broken write: the power-quantisation re-aim address was one instruction too high, and the
> "re-aim the `0x1440d822c` arm" for the pass gauge names an instruction with no memory operand.

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| **trigger runs — "tap RB while not sprinting"** | **it already ships.** `ThinkUnitPassAndGo::vf17` chain A at `0x1486b88d0` *is* `logical 19 not held` + `logical 21 tap`, and `vf12` emits command **`0x47`** | nothing to build; three data-only retunes specified in § 13 | **[a]** for the logical ids: a ≤5-frame tap of logical 21 with logical 19 up fires, with 19 held it does not. **[c]** for `19 = RT, 21 = RB` — that step is the § 2 hardware map, pinned by the in-game control screen and XInput axis convention, **not** by disassembly (§ 2, Open 21) |
| change what counts as a tap | pattern node kind 4's `B`, computed live as `(int)(0.08·FPS+0.5)` = 5 at 60 fps | runtime-data (`0x1486b8904` for PassAndGo) — **not** the shared `0.08` cell, which has 44 referrers across **36** functions | a-emulated (law + sweep) |
| **"tap LB = run"** | **impossible as stated.** `ThinkUnitCursorChange` is bound to LB and fires on the **press edge**, frame 0, before a tap can be distinguished | — | b, end to end |
| make shooting require commitment | the power gauge fill time: Shoot **0.25 s**, passes **0.30 s** (`0x1440d8070`'s 16-entry table) | exe-code re-aim (`0x1440d824a`); the set-piece variants `0.38`/`0.42` are near-private **exe-constant** edits | a-emulated: 15 frames to full at 60 fps, 24 at 0.40 s |
| coarsen power so it cannot be pixel-perfect | power crosses the wire as **7 bits**, `floor(g·127)` | exe-code re-aim at the **one** quantiser `0x144317860` (`mulss`, `disp32` at `0x144317864`) **and** the dequantiser `0x144317d43`. Three further `divss` sites read the same cell into other record fields and were not followed (§ 12) | a-emulated round-trip |
| **make aiming manual** | below **0.10** left-stick magnitude the aim angle is replaced by an assist source (`0x1440db845..0x1440db891`) | exe-code re-aim of `0x145a8dd68` at `0x1440db7f0` | b for the branch; **the size of the correction is not measured** |
| give the CPU a different feel through its input | **not possible at this layer.** The CPU never enters the pad channel; every non-pad-bound entry gets `CommandPlayer::vf2`, a pure clear | — | b |
| handicap the human's shooting accuracy | **there is nothing to remove.** The kick-error model has **no human/CPU branch**: `f` is a pure function of the kicker's own attribute | player data (the attribute), or the error model itself (subsystem 3) | a-emulated curve + a **482**-function raw-target closure with three positive and one negative control (§ 8.4) |
| stop the cursor "fighting me" when possession flips | `0x1453f0610` snaps `UCursorInfo+0x1928` to the ball holder's slot **every frame**, suppressed only while command `0x37` is live | runtime-data / exe-code; unexplored | b |
| choose **which** players are human-assignable | per-team count `X+0x3c` / `X+0x40`, or the per-player override array `X+0xf26b[22]` behind `X+0xf297` | runtime-data | a-emulated (`rank ≤ count`), with the **runtime values not located** |
| decide whether a player runs the carrier brain | the same byte: `match::ai::bp` activation reads `byte[UMatchInfo+0x41f6+idx]` and fails on zero | runtime-data, via the row above | b for the gate |
| retune skill moves / feints | the 16-row, three-table gesture set built by `0x1440d8b20`, consumed by `ThinkUnitFeint::vf8` | runtime-data (rows are zero at load, written once) | a-emulated, dumped at 60 and 30 fps |
| rebind any unit to any button | the factory `0x1440e0c70` writes `unit+0x08` (button) and `unit+0x10` (lifecycle class) | runtime-data | a-emulated |
| **tune part of it through dt270** | **YES — and it is the only route here that needs no memory write at all.** `trap.stopTrap.use` and `trap.stopTrap.inputTime` gate and size `ThinkUnitTrapStop::vf8`; `grounderpass.search.searchMinDist` is read in the Command band. **`stopTrap.use` ships `false`, so that unit currently does nothing.** See § 12's dt270 block | **dt270** (the project's existing CPK pipeline) | b for the code path, data read from both PRISTINE and installed CPKs |

---

## The channel in one paragraph

There is no "pad → command" translation step in the registry at all. `UPadInput` is a **100-frame
ring buffer of raw controller state, per pad slot** — the only thing the hardware writes. Everything
above it is a **query language**: 72 `match::pad::ThinkUnit*` objects, one set per
`match::CommandPlayer`, each holding a logical button id and a lifecycle class, each asking the ring
*"did this pattern occur?"* through a library of temporal predicates. `match::Command::update`
(`0x1440d4180`) runs once per frame, loops over the **eight hardware pad slots** (not the 24
players), finds the controller entry bound to each pad, picks a **ControlMode** for it, binds
`padBlock = UPadInput + padIdx·0x1908`, builds a context and runs that player's `CommandPlayer::vf3`
over its 0x51 unit slots; the winners are marshalled into `UCommandOutput` (80,672 B, `Copy`) as
16-byte bit-packed records, and `match::player` executors unpack them with `0x144317cd0`. Every
entry that did **not** get a pad — the CPU team, and your own ten off-ball players — is cleared
outright. `UCommandInfo` is **not** in this path: it is the netcode's parallel ingress, written only
by `OnlineCommandControllerImpl`. [b, with [a] where noted below]

```
hardware pads (8)
   |  cobra::game::ListenerManager -> event id 1
   |  game_mode::MatchListener::vf1 0x1453f21d0 -> 0x14541f1d0 -> 0x1453e76f0 -> 0x1453e7130
   |                                                   (the UPadInput frame writer, ScopedWAndC)
   |  -> 0x14431a6f0 -> 0x144316620        per-pad 18-byte assignment descriptor
   |  -> 0x14431a760                       per-pad FRAME BUILDER (writes one 64-byte frame)
   v
UPadInput   0x25960 = 153,952 B  (Pointer)   24 slots x 0x1908, each = 100 x 64-byte frames
   |
   |  frame accessor 0x14431a5b0(block, k)   k = "k frames ago", 0 = now
   v
match::Command::update  0x1440d4180   (UCommandOutput ScopedWrite)
   |   <- match::CommandListener::vf1 0x143c630a0 -> vf5 0x143c63090 -> 0x143c62220   (event id 1)
   |   for padIdx 0..7: find entry with [+8]==padIdx; 0x1440d6e00 latches a ControlMode;
   |   dispatch through the 15-entry / 3-target table 0x1440d4a08; bind padBlock;
   |   ThinkContext 0x1440d7010 -> unit context 0x1440d70f0 -> CommandPlayer::vf3
   |
   |-> match::CommandPlayer::vf3  0x1440de590 -> 0x1440ddd40 -> 0x1440db1c0   (0x51 = 81 slots)
   |        -> per unit 0x1440dcf60 -> ThinkUnitBase::vf8 0x1440d7bd0 (press machine, unit+0x1c)
   |        -> vf17 (condition) / vf12,vf13 (charge) / vf14 (command id)
   |   0x1440db720 builds {aimAngle, stickMag, POWER, guideAngle, guideMag, flags}
   |   0x1440dcd20 stores it at CommandPlayer+0x1a4c ; 0x144318700 bit-packs it
   v
UCommandOutput   0x13b20 = 80,672 B  (Copy, Write)   24 x 0xb4 slots at this+0x40
   |
   +-> 0x144317cd0  (the decoder)  -> match::player::ActionShortPass::vf2,
   |                                  ActionKickFeint/Kickoff::vf4, ActionKeeperPuntKick::vf4,
   |                                  ActionKeeperThrow::vf4, + 5 unnamed
   +-> observer / replay  0x144288360        +-> MatchOnline  0x145415a90

UCommandInfo 0x1188 = 4,488 B (Pointer, Write) -- every writer is OnlineCommandControllerImpl
```

---

## 1. `UPadInput` — 153,952 bytes, fully accounted for [b, sizes a]

Descriptor `0x143c62a20`: `mov r8d, 0x25960` at `0x143c62a49`, `xor r9d, r9d` at `0x143c62a35`
(**mode 0 = `Pointer`** — this matters in § 11). The allocation splits exactly:

| offset | size | contents | proof |
|---|---|---|---|
| `+0x00000` | `24 × 0x1908` = `0x258c0` | **24 pad-slot blocks** | `imul rcx, rcx, 0x1908; add rcx, base` (`0x14431a742`); `imul rdx, rcx, 0x1908` (`0x1440d435b`); 24 × 6408 = 153,792 exactly |
| `+0x258c0` | 8 | per-pad "slot in use" bytes | `cmp byte [rcx+r9+0x258c0], 0` (`0x14431a72c`); `mov byte [rax+rsi+0x258c0], 1` (`0x1453e725e`, `rax < 8`) |
| `+0x258c8` | `8 × 18` = `0x90` | per-pad **18-byte assignment descriptors** | `lea rdx,[rax+rax*8]; lea rcx,[rcx+rdx*2]; add rcx, 0x258c8` (`0x14431a6f7`) |
| `+0x25958` | 1 | gate flag A (whole-record disable) | `cmp byte [rcx+0x25958], 0; jne ret` (`0x14431a710`) |
| `+0x25959` | 1 | gate flag B | `cmp byte [rcx+0x25959], 0; jne ret` (`0x14431a71c`) |
| `+0x2595a` | 6 | padding | — |

Byte 0 of the 18-byte descriptor reaches every `ThinkUnit`: the full pad branch sets
`ctx->+0x30 = (byte[0x14431a5d0(padBase, padIdx)] == 1)`, so a hardware property of the pad
assignment is visible to unit code. [b]

### The pad-slot block — `0x1908` bytes = a 100-frame ring [b]

```
+0x0000   100 x 64 bytes   frame ring          (6400 = 0x1900)
+0x1900   u32              write cursor, wraps at 100
+0x1904   4 bytes          unaccounted
```

`inc dword [rcx+0x1900]` then `cmp eax, 0x64; jl; mov [rcx+0x1900], 0` (`0x14431a780`–`0x14431a79c`)
is the wrap; `shl rbx, 6; add rbx, rcx` (`0x14431a7a4`) is the 64-byte stride and the four
`movups [rbx+0x00..0x30], xmm0` that follow zero exactly 64 bytes. **100 frames at 60 fps = 1.67 s
of input history.**

### The 64-byte frame [b]

| offset | type | meaning |
|---|---|---|
| `+0x00` | u64 | **button bitmask**, bits 0..32 (`bts rax, r15`, `r15 = 0..0x20`, `0x14431a93f`). Bits 4..7 are cleared (`and rax, …ff0f`, `0x14431aac6`) and rewritten from the left-stick angle, so **the D-pad and the left stick share one 8-way direction field**. **Bit 32 is not a button** — it is a frame-validity / discontinuity flag, tested before every *edge* comparison (`0x14430f9e1`) |
| `+0x08` | f32 | left-stick angle, degrees |
| `+0x0C` | f32 | left-stick magnitude, 0..1 after conditioning |
| `+0x10` | f32 | right-stick angle |
| `+0x14` | f32 | right-stick magnitude |
| `+0x18` | u8 × 33 | **per-button analog pressure**, `0xff` for a digital button, computed for the two analog triggers (`0x14431a8ce` / `0x14431a923`) |
| `+0x39` | 7 | unaccounted |

**Stick conditioning is three constants** (`0x14431aa26`–`0x14431aa47`): dead zone **0.20**
(`0x1478501c0`), saturation **0.95** (`0x145e8788c`), divisor **0.75** (`0x145a8dd6c`) —
`m' = clamp((m − 0.20)/0.75, 0, 1)`, reaching exactly 1.0 at m = 0.95. The angle is snapped onto a
45° grid with a 22.5° offset (`0x14431abd8`, `0x14431abf0`).

### Frame addressing [b]

```
0x14431a5b0(block, k):   i = block->cursor - k ;  if (i < 0) i += 100 ;  return block + i*64
```

`k` counts **frames into the past**; `k = 0` is now. Every predicate in § 5 is written in terms
of `k`, which is why the frame-order question in § 11 costs so little.

### The full predicate leaf library [b]

All take `(unitCtx+0x08 → &padBlock, index, k)` and all bound `k < 0x64`:

| VA | call sites | returns |
|---|---|---|
| `0x14430f9b0` | 56 | **rising edge at `k`** — the default trigger (§ 4) |
| `0x144310750` | 60 | **level** — `bt frame[0], btn` |
| `0x14430f360` | 20 | stick **angle**, `frame[idx·8 + 0x08]` (idx 0 = left, 1 = right) |
| `0x14430f750` | 54 | stick **magnitude**, `frame[idx·8 + 0x0c]` |
| `0x14430f700` | 14 | **analog trigger pressure**, `frame[0x18 + btn] / 255.0`, guarded `btn < 0x21` |
| `0x1443106a0` | 4 | scans back for a run of `r8b` consecutive down-frames |
| `0x14430f940` | 2 | stick-magnitude delta between frames `k` and `k+1` |
| `0x14430fa30` | 2 | analog pressure crossed `xmm2` between frame 1 and frame 0 |
| `0x144310790` | 2 | stick magnitude `> xmm2` at frame `r9d` |

**Every call site of all five raw getters is inside `match::pad` or `match::Command`** except two
functions — `0x143cd9550` (896 B, single caller `0x143cd8180`) and `0x1449c72b0` (187 B,
vtable-reached). No `match::player`, `match::ai` or `match::anime` function reads the ring: input
reaches the executors **only** as a decoded 16-byte command record. [b]

`0x1440de840` owns 12 of the 14 pressure-getter sites and is **not** a power path — it compares both
sticks and six trigger/button pressures between frames 0 and 1 and counts no-change frames against
`FPS×10` / `FPS×20`. It is an **idle/AFK detector**. [b]

---

## 2. The button-id space, and the map to real buttons [a + b]

`match::pad` uses a **logical** id 0..33 (the bit index in the frame mask; 33 = *no button*).
`0x1443164e0` is the default logical→hardware map; `0x144316130` is the user-remap path and handles
only logical `0x12..0x1f` (`lea eax,[r9-0x12]; cmp eax,0xd; ja default`), i.e. **only the in-match
bank is rebindable**. Emulating `0x1443164e0` over every input:

| logical | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hw | 15 | 14 | 25 | 24 | 10 | 13 | 11 | 12 | 4 | 5 | 6 | 7 | 8 | 9 | 3 | 1 | 0 | 2 |

| logical | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 | 32 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hw | 4 | 8 | 5 | 7 | 3 | 1 | 0 | 2 | 5 | 7 | 3 | 1 | 0 | 2 | 32 |

Three independent facts pin the hardware codes:

1. **hw 5 and hw 8 are the analog triggers.** The frame builder branches `cmp eax,8` / `cmp eax,5`
   and, only for those, reads an **axis** (`sete dl; add edx,4` → axis 4 or 5) instead of a digital
   button (`0x14431a8b6`–`0x14431a8e4`); sticks use axes 0/1 and 2/3 in the same call. That is
   XInput axis order: **4 = LT, 5 = RT**, hence **hw 5 = LT, hw 8 = RT**. [b]
2. **The D-pad is logical 4..7 (hw 10..13)** — `TacticsNext = 4`, `TacticsBack = 6`,
   `LineControlFront = 5`, `LineControlBack = 7`. Tactics and line control are on the D-pad. [a]
3. **The face buttons fall out of the units**: `ShortPass = 24 → hw 0`, `LongPass = 23 → hw 1`,
   `ThroughPass = 22 → hw 3`, `Shoot = 25 → hw 2`, against the game's own control screen
   (A = Low Pass, B = Lofted Pass) ⇒ **hw 0 = A, 1 = B, 2 = Y, 3 = X**. [a + c]

That leaves hw 4 and hw 7 as the digital shoulders, and `ThinkUnitCursorChange` has logical 18 → hw
4, which the control screen labels **LB = Cursor Change** ⇒ **hw 4 = LB, hw 7 = RB**, cross-checked
by `FriendPress = 27 → hw 7` (RB = second-man press) and `Sliding = 29 → hw 1 = B`. [b + c]

**The working map — [b + c], and the `c` half is load-bearing:**

| logical | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| button | **LB** | **RT** | **LT** | **RB** | X | B | A | Y | LT | RB | X | B | A | Y |
| bank | attack | attack | attack | attack | attack | attack | attack | attack | defence | defence | defence | defence | defence | defence |

> **This table is not disassembly.** What the bytes prove is the *logical* id space and the
> logical→hardware-code map (`0x1443164e0`, emulated). The last step — hardware code → the label
> printed on a pad — rests on XInput axis order (fact 1) and on reading the game's own control
> screen (facts 2 and 3). It is **[c]**, and everything in §§ 12–13 that says "RB" or "RT" inherits
> that. If logical 19 is LT rather than RT, § 13's gate reads *"tap RB while the left trigger is
> up"* and every edit there is aimed at the wrong condition. **A one-shot in-game falsification —
> press RB with a logging probe on `0x1486b88d0` — would upgrade the whole of § 13 to [a]**
> (Open 21). *(Repair pass 2026-09-20: the previous draft carried this table unlabelled and let
> § 13's `[a]` badge cover it.)*

Logical 32 is the bit-32 discontinuity flag and maps to itself. **Logical 32 and 33 can never be
matched by a pattern node** — every node handler loads the mask as a 32-bit dword (§ 5.4).

---

## 3. The 72 `ThinkUnit`s and their bindings [a-emulated]

**One factory builds all of them: `0x1440e0c70`**, referenced by every `ThinkUnit*` vtable.
Emulating it against a zeroed buffer and scanning for known vtables recovers 72 units and their
construction-time fields:

| offset | meaning |
|---|---|
| `+0x00` | vtable |
| `+0x08` | **logical button id** (33 = none); consumed by `vf17` as `mov edx,[rcx+8]` → `0x14430f9b0` |
| `+0x0c` | input class: **0/1 = stick unit** (→ `vf16`), **2 = button unit** (→ the `vf8` press machine). Matches the RTTI bases exactly: every `{0,1}` derives from `ThinkUnitStickKind`, every `2` from `ThinkUnitPadId` |
| `+0x10` | **command lifecycle class**, 0..4 — decoded in § 6 |
| `+0x14` | command variant; `== 2` enables the multi-press path in `vf17` |
| `+0x18` | 1 (enabled) |

The per-unit runtime fields, from `ThinkUnitBase::vf1`/`vf8`: `+0x19` flags (overloaded),
`+0x1c` **press phase** (§ 4), `+0x20` **charge gauge** (§ 8), `+0x24` a second float (undecoded),
`+0x28`/`+0x29` press counters, `+0x2c` latch flag, `+0x30` latched command, `+0x34` unknown,
`+0x38` frame stamp.

Per-class bindings are in the [class status table](#16-class-status--all-73-classes). Two things to
read off it immediately:

* **`ThinkUnitShoulder` is not a shoulder button.** It is the shoulder *barge*: `vf12`
  (`0x1440e8fa0`) is a proximity test (`0x1440e90a0` with `xmm1 = 3.0`, squared, compared against a
  distance at `0x1440e9119`), and its button is logical 31 = Y in the **defence** bank. Anyone
  searching for "the shoulder button unit" finds this and is wrong. [b]
* **`PassAndGo` has no button of its own** (33). It overrides `vf17` and drives the pattern engine
  directly (§ 13).

---

## 4. The default trigger, and the press machine

### `ThinkUnitBase::vf17` is a one-frame rising edge, unconditionally [b]

`0x1440d8000`, 0x6f bytes, is the condition every button unit inherits:

```
if (this->+0x14 == 2 && this->+0x29 > 1)
      if (0x144310490(ctx->pad, this->buttonId, 2, 6, 0,0,0)) return true;   // multi-press
return 0x14430f9b0(ctx->pad, this->buttonId, 0);
```

and `0x14430f9b0` is exactly:

```
bool Pressed(block, btn, k):
    if (k >= 0x63) return false
    prev = frame(block, k+1)
    if (prev[0] & (1<<32)) return false          // discontinuity guard
    cur  = frame(block, k)
    return (cur[0] & (~prev[0]) & (1<<btn)) != 0
```

`vf17` always passes `k = 0`. **There is no hold, no repeat and no dwell in the default path.**
`0x144310490` is the multi-press variant, reached only by `LongPass` and `Shoot` (`+0x14 == 2`).

**Consequence, and it kills a feature request: `ThinkUnitCursorChange` overrides only slot 12**
(`0x1440e20b0`, a one-instruction `mov eax, 0x37; ret`). Its trigger is the inherited `vf17`, so
**Cursor Change fires on the press edge of LB, on the very first frame LB goes down**, before any
tap/hold discrimination could run. [b, end to end]

### `ThinkUnitBase::vf8` (`0x1440d7bd0`) is the real press/hold/release machine, on `unit+0x1c` [b]

```
if (!unit->+0x18) return 0                              ; enabled
if (unit->+0x0c != 2) { esi = vf16(unit) }              ; stick units take their own machine
else switch (unit->+0x1c) {                             ; PHASE
  case 0 idle    : goto TRY
  case 1 pressed : btn == 33 -> 3 ; level(btn) down -> 2 ; else -> 3 ; recheck
  case 2 held    : btn == 33 -> 3
                   level(btn) down AND gauge < 1.0 -> stay in 2
                   else -> 3, and stamp unit+0x38 = matchSettings+0x3318
  case 3 released: phase = 0 ; goto TRY
}
TRY: if (vf17(unit)) phase = 1
switch (unit->+0x1c) {
  case 1: if (unit->+0x14) ++unit->+0x29 ; esi = vf12(unit, ctx)     ; PRESS
          if (unit->+0x10 == 4 && (r8d==0x51||r8d==0x19) && esi==0) esi = 9
  case 2: esi = vf13(unit, ctx)                                      ; HOLD — the charge tick
          if (+0x2c==0 && +0x10==4 && esi==0 && gauge>0) { …aim guide… esi = vf14 }
  case 3: esi = vf14(unit, ctx)                                      ; RELEASE — the command id
  case 4: esi = vf15(unit, ctx)                                      ; no entry path found
}
```

**Holding past full fires the kick by itself** — `0x1440d7c99 movss xmm0,[rdi+0x20]; comiss xmm0,
1.0; jb stay` means the only way to *remain* in phase 2 is a gauge strictly below 1.0. You never
have to release. [b]

### Vtable slot roles — so nobody reads `vf12` as "the command id" [b]

| slot | role |
|---|---|
| `vf1` `0x1440d7b30` | **reset.** Clears `+0x28`/`+0x29`, the latch `+0x2c`/`+0x30`, `+0x38`, the gauge `+0x20`, the flags `+0x19`; clears `+0x24`/`+0x34` unless evt == 7; clears the **phase** `+0x1c` only when evt is 7 or 0. Overridden by **18 of the 73** classes, some branching on the event code |
| `vf2..vf7` | three-instruction thunks into `vf1` with event codes **1..6** (`0x1440de580/570/560/530/540/550`). Never overridden except `SetplayGuide`'s `vf5` |
| `vf8` `0x1440d7bd0` | the press machine above |
| `vf9`/`vf10` | set the modifier bits in `unit+0x19` (Shoot, LongPass, ShortPass, ThroughPass, Clear, Penaltykick, Dribble) |
| `vf12` | **press-phase** callback. Base (`0x1440ddd30`) is a bare `mov rax,[rcx]; jmp [rax+0x68]` — a tail-call **into vf13**. Only the units that override it directly return an id from slot 12 (`CursorChange` → `0x37`, `PassAndGo` → `0x47`, `Clear` → 0) |
| `vf13` | **hold / charge tick** — e.g. `ThinkUnitShoot::vf13` `0x1440e5cb0` → `0x1440d8070(this, ctx, 0x3d)` |
| `vf14` | **the command id** on release — `ThinkUnitShoot::vf14` `0x1440e2070` = `mov eax, 0x3d` |
| `vf16` `0x1440d7ef0` | the **stick** units' state machine (threshold 0.8, § 9) |
| `vf17` `0x1440d8000` | the rising-edge condition above |

---

## 5. The pattern engine — every node kind named

A second, richer mechanism exists alongside `vf17`, used by nine `ThinkUnit` methods and the
gesture-table builder. It is where tap/hold discrimination actually lives.

### 5.1 The node — 40 bytes [b]

| offset | type | meaning |
|---|---|---|
| `+0x00` | u32 | **button mask** (`1 << buttonId`; the gesture table passes multi-bit masks) |
| `+0x04` | u32 | **kind** (the predicate, **0..13**) |
| `+0x08` | u32 | parameter `A` (**read as a byte** in table C) |
| `+0x0c` | u32 | parameter `B` (**read as a byte** in table C) |
| `+0x10` | u8 | stick-constraint present → dispatch table **A** |
| `+0x14`, `+0x18` | f32 | stick angle range |
| `+0x1c` | f32 | — |
| `+0x20`, `+0x24` | f32 | magnitude thresholds; **`−1.0` = no stick constraint** (→ table **C**); `≥ 0` → table **B** |

### 5.2 The evaluator — `0x14430fb40` [b]

```
bool Match(ctx, node[], count, xmm3, start /*[rsp+0x20]*/, flag, window /*[rsp+0x30]*/, out)
```

It walks the chain **backwards** (`rbx = node + (count−1)·0x28`, then `sub rbx, 0x28`), dispatching
each node through one of three tables: **C** `0x148081710` (no stick), **B** `0x148081770`
(`+0x10 == 0`, `+0x20 ≥ 0`), **A** `0x1480817d0` (`+0x10 != 0`). Each handler returns a **frame
index** or `−1`, and that index becomes the search bound (`start`) for the *previous* node. So
**node[0] is the earliest event and node[count−1] the most recent**, and the whole chain must fit
inside `window` — always `0x64` = 100, the full ring, at every call site found.

**The handlers take the pad-slot BLOCK in `rcx`, not the context wrapper** — the evaluator does
`mov rsi,[rcx]` first (`0x14430fb69`). Passing the wrapper makes every handler read a garbage cursor
and **return the same value for every input**; that saturation artefact is recorded here as a method
warning because it cost the node-kinds probe its first full run. [a]

### 5.3 Every kind, emulated [a for behaviour, b for the code]

Harness: a synthetic `0x1908` block, cursor 50, logical button 21 driven, one node per run, the
game's own handler called directly. Positive control: hand-written 40-byte nodes are byte-identical
to the output of builders `0x14430edb0`/`edf0`/`ee30`/`ee80`/`eec0` (all five MATCH, with the three
padding bytes at `+0x11..+0x13` left as the builders leave them). Negative control: kind 10 steered
to table A or B faults with `UC_ERR_FETCH_UNMAPPED`, because those entries are null.

| kind | handler (table C) | name | reads | returns on match | consumes? |
|---|---|---|---|---|---|
| **0** | `0x14430d770` | **UP for `A` consecutive frames**, searched forward from `start` | `A`, span `max(A,B)+1` | index of the newest up-frame seen | yes |
| **1** | `0x14430d830` | **PRESS EDGE** — down at `i`, up at `i+1` | `B` = max pairs scanned − 1 | `i+1` | yes |
| **2** | `0x14430d8e0` | **DOWN for `A` consecutive frames** | `A`, span `max(A,B)+1` | oldest frame of the run + 1 | yes |
| **3** | `0x14430d980` | **RELEASE EDGE** — up at `i`, down at `i+1` | `B` | `i+1` | yes |
| **4** | `0x14430da30` | **TAP** — kind 3 then kind 1, gap-bounded | `B` | the press index | yes |
| **5** | `0x14430dab0` | kind 1, **non-consuming** ("peek") | `B` | `start` unchanged | no |
| **6** | `0x14430dad0` | kind 2, **non-consuming** | `A`, `B` | `start` unchanged | no |
| **7** | `0x14430daf0` | kind 3, **non-consuming** | `B` | `start` unchanged | no |
| **8** | `0x14430db10` | **LEVEL: a run of `start+1` consecutive UP frames starting at index 0 *or* index 1** — see below | `start` only | `start` unchanged | no |
| **9** | `0x14430dbd0` | the mirror: a run of `start+1` consecutive **DOWN** frames starting at index 0 or 1 | `start` only | `start` unchanged | no |
| **10** | `0x14430d760` | **ALWAYS TRUE** | nothing | `start > 0 ? start−1 : start` | one frame |
| **11 / 12 / 13** | *(11 = null slot; 12/13 have no slot at all — § 5.5)* | **stick-group accumulators**, § 5.6 | — | — | — |

> **Kinds 8 and 9 — the slack is POSITIONAL, not a budget.** *(Corrected 2026-09-20; the previous
> draft said "≤ 1 contrary frame of slack" anywhere in the region, which is wrong, and cited two
> instructions that implement nothing.)* Disassembled from `0x14430db10`: `r13d = (byte)(start+1)`
> is the run length required; an UP frame does `inc ebx` and `cmp r13d,ebx; jg continue`; a DOWN
> frame falls to `0x14430dba4 test ebx,ebx ; mov eax,0 ; cmovg ebx,eax` — **the run counter is
> reset only when it is already non-zero**, so a contrary frame is harmless *only* while the run
> has not started. The loop budget is a separate counter `esi` bounded by the same `start+1`
> (`0x14430dbae inc esi ; 0x14430dbb0 cmp r15d,esi ; jl → −1`), and it ticks on **every**
> non-matching iteration, so any contrary frame after index 0 exhausts it. Net effect: **only the
> newest frame (index 0) may be contrary, and when it is, the scan runs on to index `start+1`.**
> Kind 9 is byte-for-byte the mirror (reset at `0x14430dc66`, budget at `0x14430dc6b`).
>
> Re-emulated on the game's own bytes for this repair
> (**`tools/pad/emu_node_kind89.py`, which this pass committed** — see § 18 — `start = 8`, window 100,
> logical button 21, one contrary frame at a time):
>
> ```
> kind 8 (UP test)                       kind 9 (DOWN test, mirror)
>    nothing down        ->  8              all down            ->  8
>    down at age 0 only  ->  8   MATCH      up at age 0 only    ->  8   MATCH
>    down at age 1 only  -> -1              up at age 1 only    -> -1
>    down at age 2 only  -> -1              up at age 2 only    -> -1
>    down at age 8 only  -> -1              up at ages 0,1      -> -1
>    down at ages 0,1    -> -1              up at age 9 only    ->  8
>    down at age 9 only  ->  8
>    down at age 10 only ->  8
> ```
>
> **Positive control:** the same harness reproduces § 5.3's published `start` sweep verbatim —
> never down → `0 1 2 3 4 5 6 7 8`, up f0..f4 then down → `0 1 2 3 4 −1 −1 −1 −1`. [a + b]
>
> So *"RT not held"* means **"RT was up for the whole gesture except possibly the current frame"**,
> not "RT was up with one frame of slack somewhere".

The raw matrix, `h(block, node, start=0, window=100)` → frame index, `−1` = no match:

```
scenarios:  0 never  1 always  2 down1f  3 down3f  4 down8f  5 tap2/rel1  6 tap2/rel3
            7 press8/rel1  8 hold40/rel1  9 burst f20..f25

kind  0  A=1 B=0  |    0   -1    1   -1   -1    0    0    0    0    0
kind  0  A=3 B=8  |    0   -1    1    3   -1    0    0   -1   -1    0
kind  1  A=0 B=5  |   -1   -1    1    3   -1    3    5   -1   -1   -1
kind  1  A=0 B=40 |   -1   -1    1    3    8    3    5    9   41   26
kind  2  A=3 B=0  |   -1    3   -1    3    3   -1   -1    4    4   -1
kind  3  A=0 B=40 |   -1   -1   -1   -1   -1    1    3    1    1   20
kind  4  A=0 B=5  |   -1   -1   -1   -1   -1    3    5   -1   -1   -1
kind  4  A=0 B=12 |   -1   -1   -1   -1   -1    3    5    9   -1   -1
kind  5  A=0 B=40 |   -1   -1    0    0    0    0    0    0    0    0
kind  6  A=3 B=0  |   -1    0   -1    0    0   -1   -1    0    0   -1
kind  7  A=0 B=40 |   -1   -1   -1   -1   -1    0    0    0    0    0
kind  8  A=0 B=0  |    0   -1    0   -1   -1    0    0    0    0    0
kind  9  A=0 B=0  |   -1    0    0    0    0    0   -1    0    0   -1
kind 10  A=0 B=0  |    0    0    0    0    0    0    0    0    0    0

kinds 8/9/10 ignore A and B and key off `start`:
kind 8   never down             start=0..8 ->  0  1  2  3  4  5  6  7  8
         up f0..f4, down after  start=0..8 ->  0  1  2  3  4 -1 -1 -1 -1
kind 9   down f0..f4 only       start=0..8 ->  0  1  2  3  4 -1 -1 -1 -1
kind 10  (any ring)             start=0..8 ->  0  0  1  2  3  4  5  6  7
```

Kinds 5/6/7 are literally `push rbx; mov ebx,r8d; call <1/2/3>; test eax,eax; mov ecx,-1;
cmovns ecx,ebx; mov eax,ecx; ret` — "run the predicate, then throw away the index and hand back the
caller's". They are how a chain asks *"did this also happen?"* without moving the search window.

Kind 10 in full is four instructions and **cannot return −1**:

```
0x14430d760  test r8d, r8d ; lea eax,[r8-1] ; cmovle eax, r8d ; ret
```

### 5.4 The tap law, exactly [b + a]

`0x14430da30` calls kind 3 from `start` (→ `releaseIdx`), then kind 1 from `releaseIdx`
(→ `pressIdx`), then

```
0x14430da78  mov ecx,eax ; sub ecx,ebx ; dec ecx ; cmp esi,ecx ; jg MATCH
```

where `ebx` is the handler's **`start`** argument:

> **A tap matches iff `B > pressIdx − start − 1`, i.e. `pressDuration + releaseAge ≤ B + start`.**

`B` is **computed at runtime, never stored**: every call site builds it as
`B = (int)(0.08f·FPS + 0.5f)` — `call 0x14533ea80` (frame rate), `mulss 0.08` (`0x145e87854`),
`addss 0.5`, `cvttss2si` (e.g. `0x1440e54b0`–`0x1440e54c5`). At the head of a chain `start = 0` and
`B = 5` at 60 fps, so **press-duration plus release-age must be at most 5 frames (~83 ms)**.
Verified: a 2-frame press released 1 frame ago matches (3 ≤ 5), released 3 frames ago matches
(5 ≤ 5), released 5 frames ago does not (7 > 5). [a]

### 5.5 Five engine properties that constrain any edit [b, kind-10 fault a]

* **The mask is 32 bits.** Every handler loads it with `mov r13d/r14d/ebp, dword [node]` — logical
  32 and 33 can never be matched.
* **The discontinuity guard is not universal.** Only the edge kinds (1, 3, and therefore 4, 5, 7)
  test `frame[0] & (1<<32)`. Kinds 0, 2, 6, 8, 9, 10 do not.
* **`A` and `B` are read as bytes in table C** although the builders store dwords: `≥ 256` wraps mod
  256, and the window is fixed at 100 frames, so anything `> 100` is inert.
* **Each dispatch table is exactly 12 entries (kinds 0..11), and the evaluator bounds-checks
  nothing** — see the table geometry below.
* **There is no slot for kinds 12 or 13.** `0x14430fb40` does `movsxd rax,[rbx+4]`
  (`0x14430fbd4`) then `mov rax,[r15+rax*8+0x80817d0 / +0x8081770 / +0x8081710]` with **no
  `cmp`/`ja` on the kind**, so a kind ≥ 12 indexes past the end of its table into the next one.

**The table geometry** *(corrected 2026-09-20 — the previous draft implied 14-entry tables and named
the wrong null slots).* The three bases are `0x60 = 12 × 8` apart: **C** `0x148081710`, **B**
`0x148081770`, **A** `0x1480817d0`. Dumped from PRISTINE:

| table | kinds 0..9 | kind 10 | kind 11 |
|---|---|---|---|
| **C** (no stick) | `0x14430d770` … `0x14430dbd0` | `0x14430d760` — the always-true handler | **0** at `0x148081768` |
| **B** (`+0x20 ≥ 0`) | `0x14430dc80` … `0x14430e280` | **0** at `0x1480817c0` | **0** at `0x1480817c8` |
| **A** (`+0x10 != 0`) | `0x14430e360` … `0x14430d690` | **0** at `0x148081820` | **0** at `0x148081828` |

All three tables are inside `.text`'s raw size (`0x148081710 − 0x147e41000 = 0x240710 < 0x4b5000`),
i.e. **file-backed**, and `exe_census` finds no writer, so the nulls are permanent.

Because the tables abut, a **kind-12** node reaching the first evaluator reads `C[12] ≡ B[0] =
0x14430dc80` and a **kind-13** node reads `C[13] ≡ B[1] = 0x14430dd60` — **real stick-aware
handlers, called with a node that has no stick constraints: silent misbehaviour, not a clean
fault.** Via table A, kind 12 reads `0x148081830 = 0x07f7ffffffffffff` (a float constant) and jumps
non-canonical.

> **Kind 10 exists only in table C, and is the only safe neutering value.** A node neutered with
> kind 10 **must** keep `+0x10 = 0` and `+0x20 < 0`, or it dispatches through a null pointer in A
> or B. Do **not** reach for 11 (null everywhere), 12 or 13 (no slot).

### 5.6 Kinds 11/12/13 and the SECOND evaluator [b]

`0x14430f1d0` (kind 11) and `0x14430f250` (kind 13) unconditionally write `byte[node+0x10] = 1`,
selecting table A — whose `[11]` is null and whose `[13]` does not exist. That looks like a latent crash until you
notice the feint table is not evaluated by `0x14430fb40` at all. `ThinkUnitFeint::vf8` calls
**`0x14430fac0`**, a thin wrapper over **`0x14430fcc0`**, a second evaluator with the same node walk
plus a pre-dispatch switch:

```
0x14430fdc0  movsxd r8, dword [rbx+4]                 ; kind
0x14430fdc7  sub ecx, 0xb ; je 0x14430fea8            ; 11 -> push node, then EVALUATE the group
0x14430fdd0  sub ecx, 1   ; je 0x14430fe6d            ; 12 -> push node, continue
0x14430fdd9  cmp ecx, 1   ; je 0x14430fe6d            ; 13 -> push node, continue
             …otherwise dispatch through A/B/C exactly as 0x14430fb40 does
```

Pushed nodes go into a 10-slot local buffer (`[rsp+0x60]` count / `[rsp+0x64]` nodes) and kind 11
hands the whole buffer to **`0x14430ffa0`** (1,254 B, 7 chunks, calling `0x14430f390`) — a multi-node
stick-sequence matcher. Because the chain walks newest-first, **kind 11 is the oldest node of the
group**. Consequences: kinds 11/12/13 are legal **only** in a feint-table row. In a `ThinkUnit`
chain evaluated by `0x14430fb40` they fail in **three different ways**, and only one of them is a
clean fault (*corrected 2026-09-20 — the previous draft said all three "call a null pointer"*):

| kind in a `0x14430fb40` chain | what happens |
|---|---|
| **11** | genuine null: `C[11] = B[11] = A[11] = 0`. **Faults.** |
| **12** | no slot. Table C reads `C[12] ≡ B[0] = 0x14430dc80`, a real stick handler run on a stick-less node → **wrong behaviour, no fault**. Table A reads `0x148081830 = 0x07f7ffffffffffff` → non-canonical jump |
| **13** | no slot. Table C reads `C[13] ≡ B[1] = 0x14430dd60`, likewise a real handler |

`0x14430ffa0`'s predicate is **not decoded**.

### 5.7 Which kinds the shipped game builds [b]

| builder | kind | stick? | sites | | builder | kind | stick? | sites |
|---|---|---|---|---|---|---|---|---|
| `0x14430edb0` | 1 | no | 9 | | `0x14430ef80` | 2 | yes | 1 |
| `0x14430edf0` | 8 | no | 11 | | `0x14430f000` | 9 | yes | 4 |
| `0x14430ee30` | 2 | no | 5 | | `0x14430f080` | 6 | yes | 2 |
| `0x14430ee80` | 9 | no | 2 | | `0x14430f100` | 7 | yes | 2 |
| `0x14430eec0` | 4 | no | 2 | | `0x14430f180` | 4 | yes | 3 |
| `0x14430ef00` | 1 | yes | 10 | | `0x14430f1d0` | **11** | yes | 2 |
| `0x14430f2d0` | 1 | yes | 6 | | `0x14430f250` | **13** | yes | 2 |
| `0x14430f300` | 9 | yes | 2 | | `0x14430f330` | 4 | yes | 1 |

**Kinds 0, 3, 5, 10 and 12 have no builder anywhere.** Kind 3 is only reached from inside kinds 4
and 7; 0, 5, 10 and 12 are unreachable from shipped data and can only be produced by writing a node
by hand — which is exactly what the trigger-run spec in § 13 does with kind 10.

---

## 6. The per-unit `+0x10` — a command **lifecycle class**, not a trigger mode [b]

The switch earlier work could not find is in the per-unit driver `0x1440dcf60`, and it is reached
**only after `0x1440dab90` accepted and emitted a command this frame**:

| site | test | gates |
|---|---|---|
| `0x1440dcff8` | `cmp dword [rsi+0x10], 3` | mode 3's *acknowledge* path |
| `0x1440dd10e` | `cmp dword [rsi+0x10], 4` | mode 4's whole *cancel* block |
| **`0x1440dd691`** | `mov ecx,[r14+0x10]; sub ecx,2; je; sub ecx,1; je; cmp ecx,1; jne` | **cases 2 / 3 / 4** |
| `0x1440dd700` | `cmp dword [rsi+0x10], 1` | mode 1's *released* hook |

A sweep of every function that can hold a `ThinkUnit*` (the eight callers of the unit accessor
`0x1440e2200`, plus `0x1440d7bd0` which receives `this`) finds **no other reader of `+0x10` in the
image**.

| `+0x10` | name | behaviour, and where it is proven |
|---|---|---|
| **0** | **free-running** | No lifecycle hook at all; the unit re-emits while its trigger holds and the driver never resets it nor releases the active-unit lock on its behalf. `TrapThrough`, `KeeperTackle`, `KeeperBlock`, `MoveStopGoal`, `GoalkickPassSupport`, `Dribble`, `FreeMove`, `SetplayGuide`, the Keeper trap/pickup family |
| **1** | **self-clearing on idle** | `0x1440dd700`: the driver snapshots `+0x1c` before `vf8` (`0x1440dd437`) and, if the phase **changed and is now 0**, calls **vf2** + `0x1440dbdf0`. `Press`, `PressGK`, `Delay`, `FriendPress`, `TacticsNext/Back`, `LineControl*`, `KickCancel`, `SuperCancel`, `FreekickKeeperMove`, `TacticsAttackLevel*` |
| **2** | **one-shot** | `0x1440dd6c3`: **vf3** + `0x1440dbdf0` on the same frame the command is accepted. The default for simple press commands — including **`CursorChange`** and **`PassAndGo`** |
| **3** | **latched, reset on acknowledge** | Latches, then `0x1440dcff8`: when the player's action table at `player+0x2924` shows the latched command `+0x30` running, set `+0x2c = 2` and call **vf4** + drop the lock. `KeeperPenaltykickAction`, `KeeperPenaltykickLayer` |
| **4** | **latched, cancellable — the charged-kick class** | Latches, owns the whole `0x1440dd10e` cancel block (four paths, each calling **vf6** + dropping the lock), and is the **only** mode that accumulates charge in phase 2 (`0x1440d7d48`). `ShortPass`, `LongPass`, `ThroughPass`, `Shoot`, `Clear`, `KickFeint`, `Kickoff`, `Penaltykick`, `KeeperAutoPuntkick`, `AutoRestart`, `BlockTestAutoRestart` |

The latch itself, for modes 3 and 4: `if (cmd != 9 && cmd != 0x2e && unit->+0x2c == 0)
{ unit->+0x2c = 1; unit->+0x30 = cmd; }`.

> **`+0x10` selects *when a unit's transient state is torn down and the per-player active-unit lock
> (`player+0x1a38`/`+0x1a3c`) is released*.** It has nothing to do with edge versus hold — that is
> `+0x1c`. Do not read the class table as "2 = press edge".

---

## 7. The control-source table, and who the pad can reach

### 7.1 `match::Command::update` — the real shape [b]

```
rdi  = 0x1442d6cc0()   -> 24 controller entries, stride 0xd0    (a global: [g+0x3c8])
rbp' = 0x1442d6de0()   -> UMatchInfo                            (a global: [g+0x580])
reset 24 x 0xb4 command slots at this+0x40 via 0x1443081e0(slot, 0xb)
flags[24] = 0

FOR padIdx = 0 .. 7:                                  <-- 0x1440d472c, `cmp al, 8`
    ebx = first entry e in 0..23 with e->[+8] == padIdx        ; else next padIdx
    onPitch = e->[+0x10] if <= 0x15 else e->[+0x14] if <= 0x15 else 0xff
    0x1440d6e00(this, ebx, onPitch)                            ; ControlMode state machine
    mode = *(int*)(this + 0x2b4dc + ebx*32)
    if (mode != 0 && mode < 15) flags[ebx] = 1
    if (mode > 14) goto tail
    switch (mode) via table 0x1440d4a08

FOR i = 0 .. 23:                                      <-- 0x1440d4865 .. 0x1440d48c9
    if (flags[i] != 0) continue                                ; pad-driven: already handled
    if (entry[i][+0x10] <= 0x15                                ; 0x1440d487a
     || (entry[i][+4] & 8)                                     ; 0x1440d4891
     || 0x1442ca830(entry[i]))                                 ; 0x1440d48ab
        CommandPlayer[i]->vf2()                                ; 0x1440d48ba  call [vtable+0x10]
    ; ...otherwise the entry is SKIPPED entirely — neither driven nor cleared
UCommandOutput::ScopedWrite … 0x1440deb90
```

*(Corrected 2026-09-20: the previous draft wrote this tail as an unconditional
`if (flags[i] == 0) vf2()`. The three gates are real and an entry failing all three gets nothing.
The substantive negative is untouched — **no entry in this loop ever receives input**; pad-bound
entries are driven, participating non-pad entries are cleared, and the rest are skipped.)*

**The dispatch loop iterates the eight hardware pad slots, not the 24 players.** For each pad it
linearly searches the 24 entries for the one whose `+8` equals that pad index
(`0x1440d4290..0x1440d42b7`). A player with no pad bound never enters the switch.

### 7.2 The "15-way jump table" is three ways [b]

Dumped from PRISTINE at `0x1440d4a08` (15 × u32 rva, + `0x140000000`):

| ControlMode | target | what it is |
|---|---|---|
| 0 | `0x1440d46e7` | nothing — straight to the per-pad tail |
| **1..11** | `0x1440d4356` | **FULL PAD branch** |
| **12, 13** | `0x1440d460c` | **REDUCED PAD branch** |
| 14 | `0x1440d46e7` | nothing |

Dispatch: `0x1440d4339 cmp esi,0xe; ja 0x1440d46e7` then
`lea r8,[rip-0x40d4349]; mov edx,[r8+rsi*4+0x40d4a08]; add rdx,r8; jmp rdx`.

**Both live branches bind a pad block, byte for byte the same way** (`imul …, 0x1908` on the
`UPadInput` base, the 18-byte descriptor via `0x14431a5d0`, the ThinkContext via `0x1440d7010`,
`CommandPlayer::vf3`). The reduced branch differs in exactly three things: an entry gate
(`[0x14807ffe0]->vf1()` and `0x1442c8f20(entry, 0)`), `ctx->+0x31` ("is primary") hard-coded to
**0**, and the post-processing block `0x1440d44df..0x1440d45d3` skipped. There is one hand-written
ControlMode in the whole function: `0x1440d47d6 mov dword [rdx], 0xc`, the no-pad fallback that
binds the primary hardware pad with `padIdx = 0xff`.

### 7.3 The ControlMode record — 32 bytes at `match::Command + 0x2b4dc + idx*32` [b]

Written by `0x1440d6e00(this, idx, onPitchIdx)`: `+0x00` current mode, `+0x04` the raw mode from
`0x1440d31a0` before the gauge override, `+0x08` previous mode, `+0x0c` frames in mode, and
`+0x10`/`+0x14`/`+0x18`/`+0x1c` three further class-gated frame counters. Three predicates classify
the mode, and the `ThinkUnit`s themselves read them:

| fn | true for ControlMode |
|---|---|
| `0x1440d7080` | **1, 2, 3** |
| `0x1440d70c0` | **1, 2, 3, 4, 6** |
| `0x1440d70a0` | **5, 7, 8** |
| `0x1440d7070` | 1..9 ("a real player is being driven") |

The one surviving debug call in the band — `"[Command] Change ControlMode by gage used [%s]…"`
(`0x146b9df58`, fired at `0x1440d6f2c`) — forces mode **2** when `[playerObj+0x1a78] < 0x51` while
`UMatchInfo+0x3308 == 1`; three further tests force mode **5**. Modes 2 and 5 are therefore the
"a command gauge is being used" states.

### 7.4 The discriminator is a single byte: `UMatchInfo + 0x41f6 + onPitchIdx`

`0x1440d31a0` branches on it at the top:

```
bl = (byte[UMatchInfo + 0x41f6 + cursorPlayerIdx] != 0)
if 0x1442e2010(UMatchInfo)                 -> 14      ; [UMatchInfo+0x429c] in {3,4}
else if (bl == 0):  cursorIdx <= 0x15      -> 10
                    entry[+4] & 8          -> 11
                    entry[+4] & 4          -> 13
                    0x1442ca830(entry)     -> 12
                    else                   ->  0
else:  ~880 instructions of cursor/situation analysis  -> 1..9
```

An instruction-aware `disp32` sweep of `.xcode` for displacement `0x41f6` returns **962 instructions
in 669 functions**: **961 reads** and **exactly one writer**, the setter

```
0x1442c5360:  cmp    edx, 0x15
0x1442c5363:  ja     0x1442c5370                          ; idx > 0x15 -> ret
0x1442c5365:  movsxd rax, edx
0x1442c5368:  mov    byte ptr [rax + rcx + 0x41f6], r8b   ; setControlFlag(UMatchInfo, idx, val)
0x1442c5370:  ret
```

*(Re-decoded 2026-09-20 from a known boundary. An earlier draft printed `cmp edx, 0x16 ; jge` —
same bound, but the wrong opcodes and the wrong condition class. The census numbers below reproduce
under an independent sweep and are unchanged.)*

22 entries, one per on-pitch player. The per-match initialiser `0x1442cb020` (called only from the
`MatchOnline` band) computes all 22 as `0x144308db0(X, idx, UMatchInfo)`, which is:

```
if (byte[X + 0xf297] && 0 <= idx < 0x16)                 ; 0x144308db0 / 0x144308dc0
    return byte[X + 0xf26b + idx];                       ; per-player override array
count = (idx <= 10) ? [X+0x3c] : [X+0x40];               ; 0x144308dd6 / 0x144308de7
rank  = table[sel][ orderPosition(idx) ];                ; 1..11, selector 0x144308bda
if ([UMatchInfo+0x3308] == 2 || == 3) {                  ; 0x144308c05 .. 0x144308c13
    if (idx == [UMatchInfo+0x41d8] || idx == [UMatchInfo+0x41dc]) rank = 0;   ; the cursor players
    ; --- SECOND ACCEPTANCE PATH, reachable only inside this arm ---   0x144308d4a .. 0x144308d7a
    if (teamHalfOf(idx) matches r10d                     ; 0x144308d4f / 0x144308d57
     && [UMatchInfo+0x34a0] == 5                         ; 0x144308d5c
     && byte[UMatchInfo+0x33a6] != 0                     ; 0x144308d65
     && 0x1442c4430(UMatchInfo, idx) != 0xff)            ; 0x144308d73 / 0x144308d78
        return true;                                     ; 0x144308d80 — SKIPS the rank test
}
return rank <= count;                                    ; 0x144308d7c cmp edi,ebp ; jg -> false
```

> **Two things the earlier draft left out, both re-derived from PRISTINE 2026-09-20.**
> (1) The cursor override is **gated on `UMatchInfo+0x3308 ∈ {2,3}`** — when 3308 is anything else,
> `0x144308c13 jne 0x144308d7c` jumps straight to the rank test and the cursor player gets **no**
> special treatment. (2) There is a **second way to return true** that bypasses `rank ≤ count`
> entirely. A branch-target scan of `0x144308a90 .. 0x144308d86` shows `0x144308d4a` is reached only
> from `0x144308cc0` and `0x144308d41`, both inside the 3308∈{2,3} arm, so the bypass is scoped to
> match states 2 and 3 — but inside them it is live, and `0x1442c4430`, `UMatchInfo+0x34a0` and
> `+0x33a6` are **not decoded** (Open 22). The emulation below stubbed `0x1442c4430`, so its rows
> are the `rank ≤ count` rule only. [b]

The three rank tables, read straight out of the image — note the third puts the **goalkeeper**
first, i.e. a "play as the keeper" ordering:

| table | team 0 (idx 0..10) | team 1 (idx 11..21) |
|---|---|---|
| `0x146c11eb0` | 11,10,9,8,7,6,5,4,3,2,1 | 1,2,3,4,5,6,7,8,9,10,11 |
| `0x146c11f10` | 1,2,3,4,5,6,7,8,9,10,11 | 11,10,9,8,7,6,5,4,3,2,1 |
| `0x146c11f70` | **1**,11,10,9,8,7,6,5,4,3,2 | 1,2,3,4,5,6,7,8,9,10,11 |

Selected at `0x144308bda`–`0x144308bfb` by `[X+0x14]` and `byte[X+0x18]`. Emulated with the game's
own bytes (stubbing only the squad-order accessor and `0x1442c4430`): [a]

```
c0= 11   team0 idx0-10 [1,1,1,1,1,1,1,1,1,1,1]        cursor override, counts 0/0, 0x3308 = 2:
c0=  3   team0 idx0-10 [1,1,1,0,0,0,0,0,0,0,0]          [0x41d8]= 0 -> idx0  alone flagged
c0=  1   team0 idx0-10 [1,0,0,0,0,0,0,0,0,0,0]          [0x41d8]= 5 -> idx5  alone flagged
c0=  0   team0 idx0-10 [0,0,0,0,0,0,0,0,0,0,0]          [0x41d8]=10 -> idx10 alone flagged
c0= -1   team0 idx0-10 [0,0,0,0,0,0,0,0,0,0,0]          [0x41d8]=13 -> nothing in team 0
```

> **`byte[UMatchInfo+0x41f6+idx] != 0` means "this on-pitch player is inside his side's
> human-control allocation"** — plus, **only in match states 2 and 3**, the cursor player. A byte
> that is *forced true* for the player under the user's cursor in those states cannot mean "CPU".

### 7.5 Does a human-controlled carrier run the `match::ai::bp` brain? — **YES for an allocated player; "always" is NOT proven**

`BallPlayer`'s activation test `0x1456516d0` — whose only caller is the pre-pass `0x145653b90`
(`0x145653cc1`), and whose result is the **only** place `BP+0x10` (the "active" byte the decision
loop requires) is set to 1 (`0x145653cca`) — reads that exact byte:

```
0x145651814: call 0x14173d320                       ; the player index
0x145651819: cmp  eax, 0x15 ; ja fail
0x145651824: cmp  byte ptr [rax + rsi + 0x41f6], bl ; rsi = UMatchInfo, bl = 0
0x14565182b: je   fail
```

So **`match::ai::bp` activates only for players whose human-control-allocation byte is non-zero.**
That much is **[b]** and it closes the mechanism half of `ball-carrier-brain.md` OPEN 8: the gate is
not "is on the ball", and its gloss of this byte is wrong.

> **The second step — "and the human's cursor player is therefore always covered" — is [c] and an
> earlier draft asserted it as [b].** *(Corrected 2026-09-20.)* The only thing that would make the
> cursor player unconditionally covered is the cursor override in § 7.4, and that override is gated
> on `UMatchInfo+0x3308 ∈ {2,3}` (`0x144308c05 mov ecx,[rsi+0x3308]`, `0x144308c13 jne` → straight
> to the rank test). 3308's open-play value is **itself unknown** (Open 8: "1 = open play" is [c]).
> If open play is 3308 == 1, then in open play the cursor player is covered only when
> `rank ≤ count`, which at `count = 1` with table `0x146c11eb0` is **exactly one squad slot** — so a
> human who switches his cursor to a low-ranked player may be driving a carrier whose `bp` is off.
> This is the same unknown as the `X+0x3c` / `X+0x40` item below; the two are one question
> (Open 2).

The mirror claim is the uncomfortable one and is **not** proven: *"the CPU team's carrier therefore
never runs bp"* follows only if that team's count (`X+0x3c` / `X+0x40`) is 0 or −1 at runtime, and
**no writer of those two fields was located** (`89 51 3c` / `89 51 40` appear nowhere in
`0x144300000..0x144320000`; they arrive by whole-record copy or from the menu band). That step is
**[c]**, and it is the single highest-value open item in this map.

Recorded honestly: `BP+0x10` is **sticky**. When activation fails it is cleared only if
`0x1442c7f30(0x1442d6dc0(match))` and `BP+0x30 == 0` and a player-record bit is set
(`0x145653cd0..0x145653d0d`); otherwise the previous value stands.

### 7.6 Is CPU input synthesised through the pad? — **NO** [b]

Two independent facts. (1) The loop only ever dispatches pad-bound entries. (2) **Nothing in the
post-loop sweep `0x1440d4854..0x1440d48c9` supplies input to anybody** — the only call it can make
is `match::CommandPlayer::vf2` (`0x1440de4f0`, vtable slot 2 of `0x146ba0620`), and `vf2` is a
**pure clear**. An unflagged entry that passes one of the three gates in § 7.1 is cleared; one that
passes none is skipped and gets nothing at all. Either way it receives no command:

```
0x1440de4f0: xor eax,eax ; mov dword [rcx+8], 0xff ; mov dword [rcx+0x24], 0xbf800000  (-1.0f)
             mov qword [rcx+0x10],0 ; byte [rcx+0x18],0 ; qword [rcx+0x2c],0 ; qword [rcx+0x34],0
             dword [rcx+0x3c],0 ; qword [rcx+0x1c],0 ; add rcx,0x40 ; jmp 0x1440dbcc0  (wipe 0x51 units)
```

**Scope limit for the whole chapter: every pad-level lever — ThinkUnit bindings, `+0x10`, the tap
law, the PassAndGo chains, the feint rows — reaches only players bound to one of the 8 hardware pad
slots. Not the CPU team, and not your own ten off-ball players.** There is also no `match::Cpu*`
class anywhere in the RTTI.

### 7.7 The two contexts — the flagged contradiction, resolved *(verified 2026-09-20 for this chapter)*

Two prior write-ups gave incompatible field tables for "the ThinkContext" and one of them explicitly
left the conflict unresolved. **There are two structs, and both readings are right.** Disassembled
from PRISTINE today:

`0x1440d7010(out, padsys, entryIdx, playerNo, arg5, arg6, arg7, arg8, arg9, …)` builds a **0x34-byte
ThinkContext**:

```
+0x00 = rdx  pad system         +0x20 = r8d  entry/slot index
+0x08 = arg5 CONTROL RECORD ptr +0x24 = r9d  player number 0..21, or 0xff
+0x10 = arg7 command entry      +0x28 = arg9 camera yaw (f32)
+0x18 = arg6 &padBlock holder   +0x2c = arg8 camera type (u32)
+0x30/+0x31/+0x32 = three bytes (+0x31 = "is primary")
```

`0x1440d70f0(out, thinkCtx, commandPlayer)` then **re-packs it into the 0x4c-byte context every
`ThinkUnit` actually receives**:

```
0x1440d70f9  out+0x00 = [ctx+0x00]          pad system
0x1440d70ff  out+0x08 = [ctx+0x18]          &padBlock          <- what every predicate derefs
0x1440d7107  out+0x10 = [ctx+0x10]          command entry
0x1440d710f  out+0x18 = [ctx+0x20]          slot index
0x1440d7115  out+0x1c = [ctx+0x24]          player number
0x1440d711b  rax = [ctx+0x08] ; movups xmm0,[rax] ; movups [rbx+0x20],xmm0
0x1440d7126                     movups xmm1,[rax+0x10] ; movups [rbx+0x30],xmm1
             out+0x20..+0x3f = a 32-BYTE COPY OF THE CONTROL RECORD
0x1440d712e  out+0x40 = [ctx+0x2c]  camera type      0x1440d7134  out+0x44 = [ctx+0x28]  camera yaw
0x1440d713a  out+0x48 = byte[ctx+0x31]  "is primary" 0x1440d7145  out+0x4a = byte[ctx+0x32]
0x1440d714c  out+0x4b = byte[commandPlayer+0x1a6d]
0x1440d7157  out+0x49 = [0x1442d7090(0|1)+0x28c]     (from the entry's class byte)
```

The control record is exactly 32 bytes (§ 7.3) and its dword 0 is the **current ControlMode** —
which is why `ThinkUnitSuperCancel::vf13` (`0x1440e564b lea rcx,[rbx+0x20]; call 0x1440d7080`) and
`ThinkUnitCursorChangeManual::vf16` read `[ctx+0x20]` as an int and compare it to 1 and 5. **Both
labelings were correct; they described different structs.** The contradiction is closed, no field
table needs to be chosen over the other, and the repack site is named. [b]

### 7.8 Assistance settings — a clean negative, and an honest gap [b]

eFootball 2027 has no numeric assist level. The reflection enum `EKeyConfigAdvancedOptionsChoice`
(strings at `0x146177430..0x146177768`) is: `CONTROL_STYLE, CURSOR_CHANGE, CURSOR_NAME,
MANUAL_CURSOR_CHANGE_TYPE, PASS_SEARCH, TACKLE_TYPE, SHOOT_TYPE, CHOP_TOUCH_TYPE, BALL_COURCE,
CURSOR_CHANGE_TARGET, PASS_SEARCH_GUIDE, TARGET_GUIDE, POSITIONNING, FEINT_TYPE`, plus
`EKeyConfigPlayerMoveType::{STICK, KEY}`; Control Style is a first-class online matchmaking filter
(`EMatchingOptionControlStyleFilter`, `m_isLimitControlStyle`).

**Proven:** nothing in `match::Command::update`, `0x1440d31a0` or `0x1440d6e00` reads any of them —
full annotated dumps of all three (574 / 933 / 141 lines) contain no settings read; the only
per-user inputs are `entry[0]`, `entry[+4]` bits, `entry[+0x10]`/`[+0x14]` and the 18-byte pad
descriptor. **Assistance does not change the ControlMode and does not change which ThinkUnit
fires.** Where it *does* land is **not established** — the candidates are the per-entry settings
sub-record at `entry+0x5c` (`0x144317460` reads `byte[+0x5c+0xe]`; `0x141993aa0(entry+0x5c, 4)`
writes `byte[+0x5c]`) and the `UCommandOutput` side-arrays at `+0x10e0`/`+0x10f8`/`+0x1110`/`+0x1128`.
**"Assist edits the COMMAND or the EXECUTION" stays unanswered.**

---

## 8. Input → power, and whether humans get an accuracy edge

### 8.1 Nothing counts held frames — there is a float gauge [b, numbers a]

Each unit owns a gauge at **`unit+0x20`**, advanced by `0x1440d8070` on every frame the press
machine sits in phase 2:

```
if (1.0 <= unit[0x20]) return;                 // already full: no tick
T = table(cmdId);                              // 16-entry jump table at 0x1440d82c4, index cmdId-0x30
g = unit[0x20] + 1.0f / (FPS * T);             // FPS from 0x14533ea80
if (g > 1.0f) g = 1.0f;
unit[0x20] = g;  unit[0x38] = matchSettings[0x3318];
```

| command ids | handler | `T` when `matchSettings+0x3308 == 3` | `T` otherwise |
|---|---|---|---|
| `0x3d`, `0x3e` (**Shoot**) | `0x1440d823b` | **0.38 s** (`0x146b31dd4`) | **0.25 s** (`0x1478501fc`) |
| `0x38`, `0x3a`, `0x3b`, `0x3c` (**passes**) | `0x1440d822c` | **0.42 s** (`0x1466af68c`) | **0.30 s** (`0x145b28a88`) |
| `0x30`, `0x37` | `0x1440d8254` | **1.00 s** (`0x1478502b8`) | **0.60 s** (`0x147850258`) |
| everything else | `0x1440d8268` | 0.30 s | 0.30 s |

Float32 accumulation with the game's own arithmetic: [a]

| id class | 30 fps | 60 fps | 120 fps | `3308 == 3`, 60 fps |
|---|---|---|---|---|
| Shoot | 8 frames / 0.267 s | **15 frames / 0.250 s** | 30 / 0.250 s | 23 / 0.383 s |
| Pass | 9 / 0.300 s | **18 frames / 0.300 s** | 36 / 0.300 s | 26 / 0.433 s |
| `0x30`/`0x37` | 18 / 0.600 s | 36 / 0.600 s | 72 / 0.600 s | 61 / 1.017 s |

> **Time to full is frame-rate independent *to within one frame of quantisation*; the number of
> distinct power levels is not.** A shot has 15 reachable power values at 60 fps and 30 at 120 fps —
> a real, measurable difference in shooting precision between frame rates. *(Corrected 2026-09-20:
> the flat claim "frame-rate independent" is contradicted by the table above it. At 30 fps the shot
> gauge fills in 8 frames = **0.267 s**, not 0.250 s — a 6.7 % error; the `0x30`/`0x37` gauge at
> 60 fps with `3308 == 3` takes 61 frames = **1.017 s**, not 1.000 s.)*

`ThinkUnitBase::vf1` zeroes `+0x20` next to the flags byte `+0x19`, which is what proves the field is
a **per-press gauge** and not a persistent setting.

### 8.2 `0x1440db720` — where power and direction become numbers [b]

Output is a 20-byte block + flag byte, copied by `0x1440dcd20` to `CommandPlayer+0x1a4c..+0x1a60`:

| out | dest | contents |
|---|---|---|
| `+0x00` | `+0x1a4c` | **aim angle, degrees** |
| `+0x04` | `+0x1a50` | left-stick magnitude at frame 0 |
| `+0x08` | `+0x1a54` | **POWER** = `min(1.0, max(0.0, gauge))`, and the clamped value is written **back** into `unit+0x20` (`0x1440dbc27`) |
| `+0x0c` | `+0x1a58` | guide angle (`0x143c9b520` over the 2-vector at `CommandPlayer+0x9a0`) |
| `+0x10` | `+0x1a5c` | guide magnitude, `sqrt(x²+z²)` of the same vector |
| `+0x14` | `+0x1a60` | flags, seeded from `unit+0x19`, `\|= 4` on RT + `0x1440dfe00 >= 2` |

`0x1440dcd20` re-stores only on a material change: flags changed, power **decreased**, the angle
moved while the unit's stamp is younger than `FPS×0.05` frames **and** stick magnitude > 0.9, the
guide angle moved > 5°, or the guide magnitude crossed 0.20. Special cases: `Clear` (index 4) gets a
flat **1.0** — clearances are always full power; `cmdId 0x2c`/`0x3b` while `3308 == 3` force
magnitude 1.0 and take the angle from `unit+0x24`; `ebp == 0x43` pulls power from the unit named by
`CommandPlayer+0x1a38`/`+0x1a3c`.

**Direction.** If left-stick magnitude is **below 0.10** (`0x145a8dd68`, compared at `0x1440db840`)
the aim angle comes from an **assist source**, not the stick (`0x1440de060(…)` when `3308 == 2` and
`3378 ∈ {1,2,4}`, else `[teamCtx+0x4f0]` when `34a0 == 2`, else `[teamCtx+0x4ec]`). Otherwise
`0x1440d7230` → `0x1440d7270`:

```
out[0] = stickAngle(stickIdx, 0) ;  out[4] = stickMag(stickIdx, 0)
if (cameraType-8 <= 9 || cameraType in {3,6,18,26})      // bitmask 0x4080048 at 0x1440d72c4
    if (mag > 0)  out[0] = wrapAngle(stickAngle + cameraYaw - 180.0)
```

`cameraType` is `unitCtx+0x40` and `cameraYaw` is `unitCtx+0x44`, traced to source:
`match::Command::update(this, xmm1, r8d)` is called at `0x143c622d5` with **`xmm1 = UCameraInfo[+0x00]`
and `r8d = UCameraInfo[+0x54]`** (the registry record at `MatchControl+0x1f8`), flowing through
ThinkContext `+0x28`/`+0x2c` into the unit context. **So aiming is camera-relative — but only for
camera types 3, 6, 8–17, 18 and 26; every other camera type uses the raw pad angle.** [b end to end]

### 8.3 The wire format — 16 bytes, power as 7 bits [b, round-trip a]

`0x144318200(cmdId)` reads field `+0x04` of a **98-entry, 20-byte-stride command descriptor table at
`0x146c19000`** (ids `0x00..0x61`; entry `0x62` onward is ASCII garbage, so 98 is exact). The value
is a *category* 0..13 selecting the packer through the jump table at `0x1440db188`. Kick ids are
category **3** (`0x38`, `0x3a`, `0x3b`, `0x3d`, `0x3f`–`0x41`, `0x43`) or **4** (`0x39`, `0x3c`,
`0x3e`). Category-3 packer `0x144318700` / decoder `0x144317cd0`:

| record bits | field | scale |
|---|---|---|
| `rec[0] & 0x7f` | command id (`>= 0xf8` = empty slot) | — |
| `rec+4` bits 0–8 | aim angle | raw degrees |
| `rec+4` bits 9–11 | stick magnitude | `clamp((int)(m×7),0,7)`, decoded `/7` |
| `rec+4` bits 12–19 | **POWER** | `clamp((int)(p×127),0,127)`, decoded `/127` |
| `rec+4` bits 20–23 | a 4-bit tag | — |
| `rec+4` bits 28–31 + `rec+8` bits 0–4 | guide angle (9 bits) | raw degrees |
| `rec+8` bits 5–7 | guide magnitude | `/7` |

```
gauge 0.050 -> 6   -> 0.04724     mag 0.14 -> 0 -> 0.0000  (below 1/7 collapses to zero)
gauge 0.250 -> 31  -> 0.24409     mag 0.15 -> 1 -> 0.1429
gauge 0.500 -> 63  -> 0.49606     mag 0.50 -> 3 -> 0.4286
gauge 1.000 -> 127 -> 1.00000     mag 1.00 -> 7 -> 1.0000
```

**This is the pad → executor hand-off** that `registry-pad-command-channel.md` § 14.11 and
`player-executors.md` both left open: it is the per-command record decoder `0x144317cd0`, called
directly from `match::player::ActionShortPass::vf2` (`0x14561ff8b`), `ActionKickFeint::vf4` /
`ActionKickoff::vf4` (`0x145625ba8`), `ActionKeeperPuntKick::vf4` (`0x144215b25`, `0x144215b39`),
`ActionKeeperThrow::vf4` (`0x144217fb5`, `0x144217fc9`), plus `0x14414b950`, `0x144162070`,
`0x14415f660`, `0x1442b6760`, `0x14422d570`, `0x143c60dd0`. It is **not** a
`UCommandOutput::ScopedRead` inside `0x144261bd0` — that separate correction stands. [b]

**The `UCommandOutput` read census** *(re-imported 2026-09-20 from
`registry-pad-command-channel.md`, which this chapter had dropped)*: the record store's readers are
`0x146bf9e28`, `0x144287790`, `0x1442059d0`, `0x144285920`, `0x1456052a0`, `0x143c53cc0` and
`0x14540b040`. The `UPadInput` writer `0x1453e7130` has three further `MatchOnline` callers —
`0x14540b780`, `0x14540d8f0`, `0x1454132f0` — and the raw-device read is `0x1454002b0`
(confirmed here at `0x1453e727c`). `UPadInputRef::ScopedWAndC`'s vtable is `0x147612470`; the one
`PreRetryListener` `ScopedWrite` user is `0x143c638f0`. The three `UCommandInfo` writers are
`0x1456e42c0` / `0x1456e4640` / `0x1456e4ee0`, all `OnlineCommandControllerImpl`. [b, carried over]

### 8.4 Does the human get a kick-accuracy discount? — **No** [a + b]

`f` in the kick-error model (`(1−f)×22.5°`, `σ = max(0.1, 0.75 + K(1−s)²)`) is the return of
`0x143ed71d0`, a pure three-segment piecewise-linear function of the kicker's own **effective kick
attribute** (`0x143ed7440` picks the attribute index by kick class, reads it through ATTR_get
`0x143ea8cb0`, subtracts weak-foot / playing-style / `teamCtx+0x5098` / condition penalties):

```
attr 40 -> 0.00000    attr 65 -> 0.23333    attr 85 -> 0.76667    attr 99  -> 1.00000
attr 50 -> 0.05000    attr 70 -> 0.36667    attr 90 -> 0.90000    attr 105 -> 1.06667 (no upper clamp)
attr 60 -> 0.10000    attr 75 -> 0.50000    attr 95 -> 0.95556
```

i.e. `f = (a−40)·0.005` below 60, `0.1 + (a−60)·0.8/30` from 60 to 89, `0.9 + (a−90)/90` at 90+.
**Almost the whole dynamic range sits between 60 and 89** — that is the interval the realism mod
should think in. *(Methodology: the first emulation of this fragment returned a flat 0.1 across
60–89 because the page holding the `0.8` multiplier was unmapped. The table above is the run with
every constant page mapped and a positive control printing `0x145b2a694 == 0.8`.)* [a]

**And there is no human/CPU branch anywhere in the model.** *(Re-run 2026-09-20 with the
normalisation rule stated, because the earlier "139 functions" is not reproducible under any rule
and the count was the one thing that could not be checked.)*

**Normalisation: RAW direct call/jmp targets, not normalised to `.pdata` roots.** Extents from
`exe_funcs_chained.func_chunks` (never `func_range`). Under that rule the depth-4 closure of the
kick-miss builder `0x14401a900` is **482 functions**. Under root-normalisation it is **73** — and
that rule is a **trap**: `func_root(0x144345d90)` returns `None`, because the RNG is a leaf with no
`.pdata` record, so a root-normalised closure **silently deletes one of this section's own positive
controls**. Neither number is 139; the old figure is withdrawn.

The negative survives the larger closure. Contents of the 482:

| probe | in closure? | role |
|---|---|---|
| `0x143ed71d0` (the `f` curve) | **yes**, depth 1 | positive control |
| `0x143ea8cb0` ATTR_get | **yes** | positive control |
| `0x144345d90` RNG | **yes** | positive control |
| `0x1442e48f0` `AiLevelUnit::GetParam` | **no** | the CPU-difficulty read |
| `0x1442ee570` `Team::GetCurrentLevel` | **no** | the other difficulty read |
| `0x144317cd0` (command-record decoder) | **no** | no decoded pad command reaches it |
| memory operands with disp `0x2b4dc` / `0x2b900` / `0x2f5c0` | **zero** | no `match::Command` field reached |

Positive control for the displacement scan: the same scanner over `match::Command::update`
(`0x1440d4180`) finds **11** hits, e.g. `lea rcx,[r13+0x2b900]`. Negative control: the walker on
stub `0x140c837d0` returns **1** function. `0x14401a900` has one caller —
`match::anime::action::Kick::vf8` — shared by both sides.

> **A human-struck ball and a CPU-struck ball get the same error distribution, keyed only on the
> kicker's attributes and the physical situation.** [b for direct calls; virtual dispatch inside the
> closure was not followed, so "nowhere below" is [c] beyond that]

**Where a human edge could still live, unmeasured:** the *aim* the error is applied to. Below 0.10
stick the game supplies the angle (§ 8.2), and the CPU never enters that code at all. Quantifying
`0x1440de060`, `teamCtx+0x4ec` and `teamCtx+0x4f0` is the obvious next probe and the realism mod's
most likely "the game plays for me" complaint.

---

## 9. Cursor switching

**Proven [b]:**

* `ThinkUnitCursorChange` is bound to **LB on the press edge** (§ 4); its only override is `vf12`
  `0x1440e20b0` = `mov eax, 0x37`. Command **`0x37`**, descriptor `{0, cat 2, 2, 255, 0x010101}`.
* `ThinkUnitCursorChangeManual` and `ThinkUnitTeammateSwitch` are **right-stick** units
  (`unit+0x0c == 1`) whose `vf16` machines advance on **magnitude crossing 0.8** (`0x145b2a694`).
  So a stick-directed manual switch exists, and its threshold is **0.8, not the 0.20 dead zone**.
  *(Site list corrected 2026-09-20 — the previous draft named comparison addresses, not load
  addresses: `0x1440e757c` is `comiss xmm0,xmm6`, and the `movss` that feeds it starts at
  `0x1440e7574`.)* The cell is read at **seven** instructions in these two units —
  `ThinkUnitCursorChangeManual` (`0x1440e7500`) at `0x1440e7574`, `0x1440e7601`, `0x1440e763d`,
  `0x1440e767f`; `ThinkUnitTeammateSwitch` (`0x1440e76a0`) at `0x1440e76e3`, `0x1440e772d`,
  `0x1440e776b`. (`0x1440e767f` and `0x1440e776b` are fused `comiss xmm0,[rip+…]`, i.e. load and
  compare in one instruction; the others are separate `movss` loads.)
* `ThinkUnitCursorChangeKeeper` is on logical 13 (the menu bank), `+0x10 = 2`.
* Two consumers of command `0x37` were found and **both are suppressors, not choosers**:
  * `0x1440db1c0` reads command slot `0x11`; if it is **not** `0x37` and its `+0x14` differs from
    `matchInfo+0x41d8`, it sets `CommandPlayer+0x1a6d = 1` (`0x1440db2c6`), which lands in every unit
    context at `+0x4b`.
  * `0x1453f0610` reads command slot 7; if it is **not** `0x37` (and `+0x45 != 0`, `+0x30 == 5`) it
    scans the 24 command slots for the one whose `+0x10` equals `matchInfo+0x41d8` (the ball
    holder's player number) and writes that slot index to **`UCursorInfo+0x1928`** — an **auto-snap
    of the cursor to the ball holder, every frame**, gated off only while a cursor-change command is
    live, and only while `matchSettings+0x3308 == 1`.

**Not proven, and not guessed: *which* player LB picks.** No function scoring the ten outfield
candidates was found. `UCursorInfo+0x1928`'s other writers (`0x1442c8710`, `0x1442ca1d0`) only store
the sentinel `0x18` = "none", so they are initialisers. Three leads for the next probe:
(a) `match2D::Screen::ModelCursorNextTarget` (vft `0x14771a1f8`) — the HUD renders a "next player"
indicator, so a choice *is* computed somewhere; (b) `0x143c71e90`, which returns a slot index
`< 0x18` and is called from the cursor record receiver `0x143c75420`; (c) the rest of `UCursorInfo`.
`match::cursor::CursorManager` has only two virtuals and `vf1` (`0x143c75420`) is a
`match::record::Receiver` callback for replay events, **not** the chooser.

---

## 10. The gesture table — 16 rows in three tables, and it is the **feint** table

`0x1440d8b20` is one straight-line function: a single `ret` at `0x1440daa6c` and **no conditional
branch except three `movups` copy loops**. It always writes 16 rows into three tables.

> **Each array is 100 rows, not 16** *(added 2026-09-20 — the earlier draft gave no extent, and a
> modder writing rows by index had no stated bound)*. Each table has an `atexit` array-destructor
> thunk that states its element size and count literally: `0x1459a7d10 mov edx,0x1b0 ; mov r8d,0x64
> ; lea rcx,[0x1486adff4]`, and identically `0x1459a7d40` → `0x148698e54` and `0x1459a7d70` →
> `0x1486a3724`. So **300 slots of `0x1b0` bytes exist; the builder populates 16**. Rows 16..99 are
> zero at load and were not surveyed — write only inside a row the builder populated, or establish
> first what `ThinkUnitFeint::vf8` does with a zero row.

| table | count | rows | rows built | consumer |
|---|---|---|---|---|
| **T1** | `0x1486adff0` | `0x1486adff4` | 5 | `ThinkUnitFeint::vf8`, always |
| **T2** | `0x148698e50` | `0x148698e54` | 3 | `ThinkUnitFeint::vf8`, **or** T3 |
| **T3** | `0x1486a3720` | `0x1486a3724` | 8 | `ThinkUnitFeint::vf8`, **or** T2 |

`ThinkUnitFeint::vf8` (`0x1440d8480`) builds a two-entry list `{T1, T2-or-T3}` and walks T1 first;
the second entry is chosen by `0x144118530(player+0x5c)` at `0x1440d87ce` — `0` selects T2, non-zero
selects T3. That selector is **not decoded** ("assisted vs advanced control scheme" is [c]). Row
stride `0x1b0`: `+0x00` command id, `+0x04` flag, `+0x08` node count, `+0x0c` nodes (`0x28` each),
`+0x19c` gate mask, `+0x1a0` two floats, `+0x1a8` masked `& 0x1ff`, `+0x1ac` a flag.

**The `+0x19c` gate mask** (`0x1440d8802`–`0x1440d8871`) — a row is skipped unless:

| bit | requirement |
|---|---|
| `0x01` | this player is the one the camera/cursor follows |
| `0x02` | a ball/stance precondition (`[rsp+0x48]`) |
| `0x04` | an anime-class precondition (`[rsp+0x44]`) |
| `0x08` | a second anime-class precondition (`[rsp+0x4c]`) |
| `0x10` / `0x20` | `rdx == 1` / `rdx == 0` |
| `0x40000000`, `0x80000000` | **always skip** (`bt ecx,0x1e; jb skip` / `test ecx,ecx; js skip`) |

so **T2[1] and T2[2] are dead rows** — built, never evaluated. T2 has one live row.

### The rows, emulated at 60 fps [a]

**T1 — always evaluated**

| row | cmd | gate | nodes, newest last |
|---|---|---|---|
| T1[0] | `0x17` | `0x04` | `RB kind 9 HELD` ; `bit0 kind 1 PRESS + stick 0…−90°, mag 0.8` |
| T1[1] | `0x0f` | `0x20` | `RB kind 8 NOT-HELD` ; `mask 0x13 kind 1 PRESS, B=12, mag 0.9` ; same again ; `stick kind 6, ±180°, mag 0.2` |
| T1[2] | `0x0f` | `0x10` | `RB kind 8` ; `mask 0x13 kind 4 TAP, B=12` ; `stick kind 6, ±180°, mag 0.2` |
| T1[3] | `0x1b` | `0x00` | `bit13 kind 1, B=24` ; `stick kind 9 HELD ±180° mag 0.2` ; `bit13 kind 1, B=0` |
| T1[4] | `0x1b` | `0x00` | `bit13 kind 1, B=24` ; `bit13 kind 1, B=0` |

**T2 — when `0x144118530` returns 0**

| row | cmd | gate | nodes |
|---|---|---|---|
| T2[0] | `0x00` | `0x20000000` | `RB kind 8 NOT-HELD` ; `bit0 kind 1 PRESS + stick ±180°, mag 0.8` |
| T2[1] | `0x00` | `0x40000000` **DEAD** | `bit13 kind 1` |
| T2[2] | `0x00` | `0x80000000` **DEAD** | `RB kind 1 PRESS` |

**T3 — the rich gesture set**

| row | cmd | flag | gate | nodes, newest last |
|---|---|---|---|---|
| T3[0] | `0x0c` | 1 | `0x09` | `RB kind 8` ; `LB kind 8` ; `bit0 kind 4 TAP B=12 @ −90°` ; `bit0 kind 7 RELEASE/peek @ −90°, mag 0.8` |
| T3[1] | `0x0a` | 1 | `0x09` | `bit0 kind 11 @ 0…−15°, span 135°, mag 0.8` ; `bit0 kind 13 @ −45…0°, B=60, mag 0.8` — **stick group** |
| T3[2] | `0x08` | 1 | `0x09` | `LB kind 8` ; `bit0 kind 11 @ 180…−90°, span 90°` ; `bit0 kind 13 @ 60…0°, B=60` — **stick group** |
| T3[3] | `0x1d` | 1 | `0x00` | `LB kind 2 DOWN-for-A` ; `bit0 kind 2 @ 45…−45°, mag 0.8` ; `stick kind 1 @ −45…−90°, mag 0.2` |
| T3[4] | `0x15` | 1 | `0x00` | `bit0 kind 1 B=18 @ 0…−30°` ; `bit0 kind 9 HELD @ 0…−45°` ; `stick kind 1 @ −90°, mag 0.2` |
| T3[5] | `0x1c` | 1 | `0x00` | `LB kind 2` ; `bit0 kind 4 TAP B=18 @ 45…−45°` ; `bit0 kind 7 RELEASE/peek, mag 0.8` |
| T3[6] | `0x12` | 1 | `0x00` | `bit0 kind 1 B=18 @ 90…−60°` ; `bit0 kind 9 @ 90…−82.5°` ; `stick kind 1 ±180°, mag 0.2` |
| T3[7] | `0x19` | 0 | `0x00` | `bit0 kind 1 B=18 @ −180…−52.5°` ; `bit0 kind 9 @ −180…−52.5°` ; `stick kind 1 ±180°, mag 0.2` |

**Every `B` scales with the live frame rate** — the same dump at 30 fps gives 12 → 6, 24 → 12,
18 → 9, 60 → 30. The gesture windows are ~200 ms (12 @ 60), ~400 ms (24), ~300 ms (18) and 1.0 s
(60), computed live, never stored. The 11 command ids (`0x08`, `0x0a`, `0x0c`, `0x0f`, `0x12`,
`0x15`, `0x17`, `0x19`, `0x1b`, `0x1c`, `0x1d`) are **not mapped to named skill moves**.

This also confirms the control screen's "RB = Special Controls": bit 21 is the modifier on T1[0..2].

---

## 11. Frame order, and whether a runtime write needs a commit

### The scheduler is found: `cobra::game::ListenerManager`, **event id 1** [b]

```
   +-> game_mode::MatchListener::vf1   0x1453f21d0
   |      0x1453f2272  sub eax,1 ; je 0x1453f2421      <-- EVENT ID 1
   |      0x1453f2430  call 0x14541f1d0 -> 0x14540ca60 -> 0x1453e76f0 -> 0x1453e7130
   |                                                     (the UPadInput frame writer)
   +-> match::CommandListener::vf1     0x143c630a0
          0x143c630f6  sub eax,1 ; je 0x143c63178      <-- EVENT ID 1
          0x143c631f8  call qword [rax+0x28] = vf5 = 0x143c63090
          0x143c63090  mov rcx,[rcx+0x3e30] ; jmp 0x143c62220 -> 0x1440d4180
```

The `UPadInput` writer `0x1453e7130` is the only non-ctor/dtor user of `UPadInputRef::ScopedWAndC`:
it polls 8 hardware pads, copies 24 bytes of slot→pad assignment from `src+0x7f8`, clears
`[record+0x258c0]` (**one `mov qword …, 0` at `0x1453e7236` — eight bytes, not 24**), and then runs
a 24-iteration loop (`0x1453e724b mov ebp, 0x18`): for each of the 24 slots it reads that slot's
**assigned pad** (`0x1453e7250 movzx eax, byte [rdi]`), skips it unless `pad < 8`
(`0x1453e7253 cmp al,8 ; jae`), and sets the in-use byte **at that pad's index**
(`0x1453e725e mov byte [rax + rsi + 0x258c0], 1`), then reads the raw device (`0x1454002b0`) and
calls `0x14431a6f0` → `0x144316620` (descriptor) / `0x14431a760` (frame builder) — all with the
**pad** index in `edx`/`ecx`, never the slot index.

> **16 of the 24 pad-slot blocks are dead.** *(Added 2026-09-20; the earlier wording "for each of
> 24 slots … sets the in-use byte" reads as 24 in-use bytes, which would run 16 bytes into the
> 18-byte descriptors at `+0x258c8`.)* The allocation sizes 24 blocks of `0x1908` (§ 1), but only
> blocks **0..7** are ever written here, and the consumer side is bounded the same way
> (`0x1440d4737 cmp al, 8`). **A runtime write into the ring must use the PAD index, never the
> player or slot index.**

**What is still not proven.** `cobra::game::Listener`'s base ctor `0x14510f070` sets
`[this+0x108] = −1`, a priority slot — and **neither concrete ctor writes it** (`match::CommandListener`
`0x143c62cb0`, `game_mode::MatchListener` `0x1453da1d0`, `PostCommandListener` `0x143c63410`,
`ExecListener` `0x143c673a0`: zero hits on `+0x108`/`+0x10c`/`+0x110` in every chunk). The relative
order is **runtime registration data**. [b for the absence, c for the consequence]

**What that costs, precisely.** Less than it looks. The ring is a 100-frame history and every
predicate is expressed as *frames ago from the cursor*; if `Command::update` ran before the pad
write, every predicate would read the previous frame as "now" — a uniform **one-frame input
latency, not a semantic change**. No law in § 5 depends on the order. It **does** matter for
**injection**: whether a synthetic frame written from outside is seen this tick or next is exactly
this unresolved ordering, so write and then **verify by observation**.

### `ScopedWAndC` on `UPadInput` is a no-op — emulated [a]

```
A. commit 0x145340a10 against a synthetic registry entry
   mode=0 Pointer (UPadInput's class)  front after commit = aaaaaaaaaaaaaaaa  UNCHANGED -> NO-OP
   mode=1 Copy                         front after commit = bbbbbbbbbbbbbbbb  PUBLISHED from back
B. write resolver 0x1453415d0   mode=0 -> FRONT ;  mode=1 -> BACK   (both set entry+0x28 'touched')
C. read  resolver 0x145340c80   mode=0 -> FRONT ;  mode=1 -> FRONT
D. UPadInput's registrar        0x143c62a35 xor r9d,r9d -> mode 0 = Pointer
```

**A runtime write into any pad structure — the ring, the cursor, the in-use bytes, the per-pad
descriptors — takes effect immediately for every reader and needs no commit**, because writer and
reader resolve to the same buffer. The only skipped side effect is `entry+0x28 = 1` ("touched"),
whose readers were **not traced**. And the pattern chains themselves are **not registry records at
all** — `0x1486b88d0`/`0x1486b8930` are plain memory past the PE's raw size.

---

## 12. Tunables

Sharer counts from `tools/exe_census.py cell --all` over PRISTINE. Denuvo makes the on-disk image
untouchable, so every exe route here is a runtime write.

### Route legend — **three risk tiers, not one** *(rewritten 2026-09-20)*

The earlier draft treated all three routes as one class "because every route here is a runtime
write". They are not one class: they land on **three different pages with three different
protections**, read straight off PRISTINE's section table.

| tier | route | lands in | page | what it costs |
|---|---|---|---|---|
| **0 — safest** | **dt270** | a CPK data file | *(not in the process at all)* | the project's existing `dt270_objects.py` pipeline. No memory write, no protection change, no code-page exposure. **Three fields proven so far** (the band was not swept — Open 23), but they cost nothing |
| **1 — low** | **runtime-data** | `.text` VA `0x147e41000`, vsz `0xdfa000`, **rsz `0x4b5000`** | `0xc0000040` = **READ \| WRITE** | plain `WriteProcessMemory`. Every address in § 13 and the feint tables sit **past the raw size**, i.e. loader-committed zero pages: writable with no `VirtualProtect` and not in any executable-page hash |
| **2 — medium** | **exe-constant** (edit a float cell in place) | `.tls$` VA `0x1459fc000` | `0x40000040` = **READ only** | needs `VirtualProtectEx`. Not executable, so outside a code-integrity hash — but every other reader of the cell moves with it |
| **3 — experiment** | **exe-code re-aim** (repoint a `disp32`) | `.xcode` VA `0x140001000` | `0x60000020` = **EXECUTE \| READ**, no WRITE | needs `VirtualProtectEx` **and** is a write to an executable page. This project's own `tools/live_patch.py` `DENUVO_NOTES` singles `.xcode` out as integrity-checked and warns that a mismatch **crashes the game**. Treat every tier-3 row as an experiment, not a setting |

**Eleven of the rows below are tier 3** (ten marked `3`, one marked `3+` because it needs a code
rewrite rather than a re-aim) — including every headline knob: shot gauge, power 127, aim-assist
0.10, cursor 0.8, stick conditioning. Try tier 0 and tier 1 first.

Note also that **Denuvo has shuffled the section names**: the section called `.text` here is
`READ|WRITE` *data*, and the real code is `.xcode` plus the ~183 MB executable `.impdata` blob
(the protection VM). That is why the tier-1 addresses in `.text` are safe and the tier-3 addresses
in `.xcode` are not — the names say the opposite of what they usually mean.

### dt270 rows — the only ones that need no memory write *(new 2026-09-20)*

**The chapter previously said "no dt270 field reaches `match::pad`". That was wrong, and the method
behind it could not have supported it** — a census of RIP-relative *constant loads* cannot see a
dt270 value, which arrives through a `GetParam` call and a pointer deref and is never a literal.
Proven from the bytes, with the object identity read out of the game's own registration table
(`0x1475d2ba0`, 0xf5 entries of `{const char *json, factory}`, reached from `0x145349a40`):

| what | object | field | site | evidence |
|---|---|---|---|---|
| **`ThinkUnitTrapStop` on/off** | `trap` (idx **`0x6f`** = `DevelopData/common/match/constant/player/trap.json`) | **`stopTrap.use`**, runtime `+0x1c8`, bool | `0x1440e883f mov edx,0x6f` ; `0x1440e8844 mov rcx,[0x148c22b98]` ; `0x1440e884b call 0x145348d70` ; `0x1440e8853 cmp byte [rax+0x1c8],0 ; je 0x1440e88a9` — **a dt270 flag gates the whole unit** | b |
| **`ThinkUnitTrapStop`'s scan window** | `trap` | **`stopTrap.inputTime`**, runtime `+0x1c4`, float (seconds) | `0x1440e8877 call 0x14533ea80` (live FPS) ; `0x1440e887c mulss xmm0,[rbx+0x1c4]` ; `0x1440e8886 cvttss2si edi` — **a dt270 float × FPS becomes the unit's frame window**, the exact shape § 5.4's `0.08` cell produces for taps, but on the data route | b |
| **pass search min distance** | `grounderpass` (idx **`0x6a`** = `.../player/grounderpass.json`) | **`search.searchMinDist`**, runtime `+0xbc`, float | `0x1440d6499 mov rcx,[0x148c22b98]` ; `0x1440d64a0 mov edx,0x6a` ; `0x1440d64a5 call 0x145348d70` ; `0x1440d64b7 movss xmm6,[rax+0xbc]` — in the **Command** band | b |

Runtime offsets resolved through `tools/data/dt270_struct_offsets.json` (`trap` struct `0x1f0`,
`grounderpass` `0xc0`); `0x145348d70` is `ConstantManager::get(mgr, idx)`.

> **And the "read ≠ effective" check pays off immediately: `trap.stopTrap.use` ships as `false`.**
> Read out of **both** `dt270_console_all.PRISTINE.cpk` (sha1 `501f9880…`) and the installed CPK
> (sha1 `ebdfce5a…`, which is one of *our* installs, not stock — so both were checked and they
> agree):
>
> ```
> PRISTINE    stopTrap.use = False   stopTrap.inputTime = 0.5   search.searchMinDist = 2.25
> INSTALLED   stopTrap.use = False   stopTrap.inputTime = 0.5   search.searchMinDist = 2.25
> ```
>
> So in the shipped game `0x1440e885a je 0x1440e88a9` fires every frame and
> **`ThinkUnitTrapStop::vf8` does nothing at all** — the unit is present, bound to logical 13, and
> switched off by data. `inputTime = 0.5 s` would be a **30-frame** window at 60 fps if it were
> enabled. Flipping one boolean in a CPK is the cheapest experiment in this whole chapter, and
> what the unit then *does* is unknown, so it is an experiment, not a recommendation. [b + data]

**What is still NOT established:** whether any *other* pad unit takes dt270. The exe-constant census
cannot answer it — the right instrument is a scan for `call 0x145348d70` with a recovered `edx`
across `0x1440d0000..0x144320000`. Two sites are proven; the band was not swept (Open 23).

### The table

`tier` is the risk tier from the legend above. `page` is the PE section the write lands in.

| what | site | route | tier / page | sharers | evidence | notes |
|---|---|---|---|---|---|---|
| **PassAndGo tap window** (`B`) | `0x1486b8904` (chain A node[1] `+0x0c`), currently `05 00 00 00` | runtime-data | **1** / `.text` RW | private | a | `press + releaseAge ≤ B`. `>100` inert, `≥256` wraps mod 256. Recomputed by the TLS initialiser — write **after** the first `vf17`. **The safest edit in the subsystem** |
| **PassAndGo "RT not held" gate** | `0x1486b88d4` (chain A node[0] `+0x04`), `08` → `0a` (kind 10) | runtime-data | **1** / `.text` RW | private | a | Fires while sprinting. **Must** keep `+0x10 = 00` and `+0x20 = bf 80 00 00`, or kind 10 dispatches through a null in table A or B. **Do not substitute 12 or 13** — those have no slot and run the next table's handler instead (§ 5.5) |
| **PassAndGo button** | `0x1486b88f8` (mask), `00 00 20 00` = 1<<21 | runtime-data | **1** / `.text` RW | private | b | **High risk for LB** (`1<<18`): collides with `CursorChange`'s press edge. Bits 32/33 can never match. Retargeting also needs chain B's masks at `0x1486b8958` / `0x1486b8980` |
| **PassAndGo chain-B hold threshold** | `0x1486b8988` (chain B node[2] `+0x08`), `05` | runtime-data | **1** / `.text` RW | private | a | Chain B fires on exactly the (A+1)th frame of a hold |
| **Feint / skill-move rows** | T1 `0x1486adff4`, T2 `0x148698e54`, T3 `0x1486a3724`; **each array is 100 rows × `0x1b0` B** (from its own array-destructor thunk `0x1459a7d10` / `d40` / `d70`), of which the builder populates 16 | runtime-data | **1** / `.text` RW | private | a | Retunes gesture windows (12/18/24/60 frames) and preconditions; `+0x19c` bit 30/31 kills a row outright. Rows 16..99 are zero and unsurveyed — stay inside a populated row. Do **not** convert a kind-11/12/13 node — those belong to the second evaluator |
| **Per-unit button rebinding / lifecycle class** | factory `0x1440e0c70` → `unit+0x08`, `unit+0x10` | runtime-data | **1** / heap | per-instance | a/b | Class 4 also enables the charge accumulator, so moving a non-kick unit to 4 exposes it to kick code |
| **Open-play shot gauge 0.25 s** | `0x1478501fc`, loaded at `0x1440d824a` | exe-code re-aim | **3** / `.xcode` RX | 657 | a | The biggest shooting-feel knob, and **genuinely isolable**: `0x1440d824a` is reached only by ids `0x3d`/`0x3e` via `0x1440d823b`. 0.40 s ⇒ 24 frames / 24 power levels at 60 fps |
| **Set-piece pass gauge 0.42 s** | `0x1466af68c`, loaded **only** at `0x1440d8231` in this band | exe-code re-aim | **3** / `.xcode` RX | **10** | b | *(Rerouted 2026-09-20 — "effectively private, the safest edit in the subsystem" was wrong.)* Nine of the ten referrers are not the gauge and several are live match code: `match::anime::action::ThrowinLoop` `0x143f7f417`, `0x144037872` (`match::anime`), `0x143ca5f35`, `0x143d5695b`, `0x143d56f49`, `0x143d5a6f7`, `0x143e3dd99`, `0x143ebf896`, `0x142f16381`. **Re-aim the one instruction; do not edit the cell** |
| **Set-piece shot gauge 0.38 s** | `0x146b31dd4`, loaded **only** at `0x1440d8240` in this band | exe-code re-aim | **3** / `.xcode` RX | **6** | b | Same correction. The other five: `0x144098713` (a `match::registry` method), `0x143e3e3c7`, `0x143e3e404`, `0x143db8bf7`, `0x144a5db6a` |
| **Open-play pass gauge 0.30 s** | `0x145b28a88` — **one load in the whole function, at `0x1440d8268`, and that is the SHARED DEFAULT arm** | **no isolating edit exists** | **3+** / `.xcode` RX | 895 | a | *(Corrected 2026-09-20 — the prescribed "re-aim the `0x1440d822c` arm" does not exist: `0x1440d822c` is `cmp edx,3`, no memory operand.)* `0x1440d8268` serves ids `0x31`–`0x36`, `0x39`, `0x3f`, everything outside `0x30..0x3f`, **and by fall-through from `0x1440d822f jne`** the pass ids `0x38`/`0x3a`/`0x3b`/`0x3c` whenever `3308 != 3`. Isolating open-play pass needs the `jne` redirected to a cave with its own load — a **code rewrite**, a different risk class from every other row here |
| `0x30`/`0x37` gauge 0.60 s | `0x147850258` at `0x1440d825e` | exe-code re-aim | **3** / `.xcode` RX | 438 | b | Isolable (`0x1440d825e` is reached only by ids `0x30`/`0x37`), but the commands are unidentified; leave alone |
| **Power quantisation 127** | `0x145b4c548`: quantiser **`0x144317860`** (`mulss`, `disp32` at `0x144317864`) + dequantiser `0x144317d43` | exe-code re-aim | **3** / `.xcode` RX | 88 image-wide, **5 in the command band** | a | *(Address corrected 2026-09-20: `0x144317868` is `cvttss2si eax,xmm0` — a four-byte re-aim written there corrupts the quantiser every packed command passes through.)* `0x144317860` is a shared leaf, so re-aiming it covers **both** packers `0x144318700` and `0x144318a90`. There are **four** `divss` readers, not one: `0x144317d43` (proven to decode power), plus `0x144317db5`, `0x144318006`, `0x1443180f0`, which write different record offsets and were **not followed** — whether they must move too is NOT PROVEN. The inline clamp `cmp eax,0x7f ; mov eax,0x7f` at `0x144317870`/`0x144317875` does **not** follow a re-aim, so this knob can only coarsen |
| Stick magnitude quantisation 7 | `0x145c36ac0` — **12 sites** in the pack/unpack band | exe-code re-aim | **3** / `.xcode` RX | 398 | b | *(Count corrected 2026-09-20 from "3 sites".)* Quantiser `0x144317840`, plus `0x144317cb6`, `0x144317d28`, `0x144317d7c`, `0x144317e69`, `0x144317eaf`, `0x144317f01`, `0x144317f18`, `0x144317f69`, `0x144317f91`, `0x144318111`, `0x144318134` (fns `0x144317c40`, `0x144317cd0`, `0x144317e30`, `0x144317ec0`, `0x144317f30`, `0x1443180a0`), plus one in `match::camera::plugin::InplayCamera` at `0x1440d027c`. Not recommended |
| **Aim-assist threshold 0.10** | `0x145a8dd68` at `0x1440db7f0` (`movss xmm6,[rip+0x19b2570]`; consumed at `0x1440db840 comiss xmm6,xmm0`) | exe-code re-aim | **3** / `.xcode` RX | 1186 | b | The line between "the stick aims" and "the game aims". Highest-leverage pad-layer realism knob, **completely untested, and a write to an executable page** |
| Cursor-switch stick threshold 0.8 | `0x145b2a694` — **7 sites**, 4 in `ThinkUnitCursorChangeManual` (`0x1440e7574`, `0x1440e7601`, `0x1440e763d`, `0x1440e767f`) and 3 in `ThinkUnitTeammateSwitch` (`0x1440e76e3`, `0x1440e772d`, `0x1440e776b`) | exe-code re-aim | **3** / `.xcode` RX | 622 | b | *(Corrected 2026-09-20: the old row named `0x1440e757c`, which is `comiss xmm0,xmm6` — the load is at `0x1440e7574` — and said "two load sites".)* **All sites within a unit must be re-aimed together** or that unit's own comparisons disagree. Five further pad-band readers (`SetplayGuide` ×2, `Clear`, `TacticsBack`, `TrapThrough`) are untouched by a per-site re-aim |
| Dead zone 0.20 / saturation 0.95 / divisor 0.75 | `0x1478501c0` at `0x14431a964` / `0x145e8788c` at `0x14431a970` / `0x145a8dd6c` at `0x14431a97f` | exe-code re-aim | **3** / `.xcode` RX | 1165 / **77** / 229 | **b** | Loaded into loop-invariant registers (xmm10/xmm14/xmm15) inside the 64-byte frame builder `0x14431a760`, so this changes *every* stick read in the match. The 0.95 cell is by far the least shared. *(Upgraded from [c] to [b] 2026-09-20 — the consumers were traced.)* |
| Camera-relative aim on/off | `cmp eax,9` at `0x1440d72ba` + `mov eax,0x4080048` at `0x1440d72c4` | exe-code (private immediates) | **3** / `.xcode` RX | — | b | Genuinely private: both are inline immediates, no shared cell. Forcing the raw-stick branch makes aiming pitch-absolute — and changes set-piece aiming too |
| **Control rank tables** `0x146c11eb0` / `f10` / `f70` | — | **NOT-SAFELY-TUNABLE (index table)** | `.tls$` R | 1 referrer each, all `lea` in `0x144308a90` | b | *(Reclassified 2026-09-20 — previously "exe-constant".)* The **values are array indices 1..11** used to index a squad array. `exe_census` returns `STATUS=table` and vetoes them: `['address_taken_by_lea','imgbase_table_base','table']`. The index bound at `0x144308a3e`/`47`/`50` was not analysed, so an out-of-range value is an out-of-bounds read. **Reorder within 1..11 only, or not at all** |
| Tap constant 0.08 s | `0x145e87854` | **NOT-SAFELY-TUNABLE** | `.tls$` R | 44 refs / **36** functions | b | Readers span unrelated systems (`match::anime::action::Kick` ×3, `goal_keeper::SavingBase` ×5, `Dribble`, `RagdollManager`, `camera`, `ActionPress`, `ThinkUnitPassAndGo` ×2, `ThinkUnitMoveStopGoal`, `ThinkUnitFriendPress` ×4). Would move every window computed as `round(0.08·FPS)` at once. Edit per-node `B` instead |
| Kick-charge cap 1.0 | `0x1478502b8` at `0x1440d7c9e` | **NOT-SAFELY-TUNABLE** | `.tls$` R | **13,240 refs / 8,003 functions** | b | *(Counts corrected 2026-09-20 from "11,969 / 7,522".)* The image's generic `1.0f`. And the gauge's own ceiling at `0x1440d8291` is an **inline `mov dword [r14+0x20], 0x3f800000`**, so even a re-aim would not move the clamp |
| The gauge itself | `unit+0x20` | **NOT-SAFELY-TUNABLE** | heap | — | b | Rewritten every frame by `0x1440d8070` (unconditional store at `0x1440d8289`) and re-clamped by `0x1440db720`; a poke survives < 1 frame |
| A player's ControlMode | `match::Command+0x2b4dc+idx*32` | **NOT-SAFELY-TUNABLE** | heap | — | b | Recomputed every frame by `0x1440d6e00` |
| `match::Player+0x7f49` | `(Player+0x7660)+0x8e9` | **NOT-SAFELY-TUNABLE** | heap | — | b | Rewritten every tick by `0x14415b850` on the ungated ticker chain; to change it, patch the set/clear condition |
| `matchSettings+0x3308` | — | **NOT-SAFELY-TUNABLE** | heap | — | b | A play-state, not a setting: forcing it moves the gauge rate, the guide, the cursor snap and several unit branches together |

### Not yet actionable — named so they are not mistaken for settings

*(Split out 2026-09-20. These were listed beside writable rows, which flattened a real distinction:
a `runtime-data` route needs an address, and the base object `X` has none.)*

| what | why it cannot be executed |
|---|---|
| **Per-team human-control count** `X+0x3c` (team 0) / `X+0x40` (team 1) | This is the single highest-value lever in the subsystem — it sets `UMatchInfo+0x41f6[idx]` at setup, which gates the degenerate ControlModes **and** `match::ai::bp` activation. But **the object `X` has no located base and the two fields have no located writer** (Open 2, Open 9). The often-quoted "961 readers in 669 functions" is a count of readers of the *displacement* `0x41f6` on `UMatchInfo`, **not** of a data cell, and is not comparable with the refcounts in the table above; it is context, not a sharer count |
| **Per-player human-control override** `byte[X+0xf297] = 1`, then `byte[X+0xf26b+idx]` | Same unknown base. Mechanically it is the cleanest switch in the subsystem for "does this player run the carrier brain" — `0x144308db0` returns the override byte directly and skips the rank/count rule entirely (§ 7.4) — but there is nowhere to write it yet |
| **Control rank ordering** (incl. the GK-first table) — selector `[X+0x14]` / `byte[X+0x18]` | Same unknown base. It decides which squad slots a partial count covers; the three tables it selects are separately NOT tunable (index table, in the table above) |

---

## 13. The trigger-run spec — reviewable, **NOT APPLIED**

> **Nothing in this section was written, applied or tested in the game. It is a description of
> bytes, produced so the owner can review it before anything runs.**

### 13.1 The headline: the feature already ships

`ThinkUnitPassAndGo::vf17` (`0x1440e5280`) ORs two chains, both built lazily behind MSVC
magic-statics TLS guards. Running the game's own initialisers with the frame rate stubbed to 60,
then the game's own evaluator over a synthetic ring: [a]

```
chain A @0x1486b88d0  (2 nodes, count from `lea r8d,[rbp+2]` at 0x1440e52f6)
   A[0] @0x1486b88d0  mask 0x00080000 (LOGICAL 19)  kind 8 NOT-HELD  +0x10=0 +0x20=-1.0 +0x24=-1.0
   A[1] @0x1486b88f8  mask 0x00200000 (LOGICAL 21)  kind 4 TAP  B=5  +0x10=0 +0x20=-1.0 +0x24=-1.0

chain B @0x1486b8930  (3 nodes)
   B[0] @0x1486b8930 logical 19, kind 8 NOT-HELD
   B[1] @0x1486b8958 logical 21, kind 1 PRESS, B=0
   B[2] @0x1486b8980 logical 21, kind 2, A=5

(logical 19 = RT and logical 21 = RB come from the § 2 hardware map, which is [c], NOT from
 these bytes.  Everything the emulator drives is the LOGICAL bit.)

case:              0 never 1 tap1f/rel1 2 tap2f/rel1 3 tap2f/rel3 4 tap2f/rel5
                   5 tap4f/rel1 6 tap6f/rel1 7 held6f 8 held20f 9 held20f/rel1
SHIPPED, RT up         0   1   1   1   0   1   1   1   0   0
SHIPPED, RT HELD       0   0   0   0   0   0   0   0   0   0
```

**A tap of RB with RT up already fires `ThinkUnitPassAndGo`**, whose `vf12` (`0x1440e5270`) is
`mov eax, 0x47; ret` — command id **`0x47`**. Chain B additionally fires on the *sixth* frame of an
RB hold and then stops. The unit is index 71 of 72, `+0x08 = 33` (no button of its own),
`+0x0c = 2`, `+0x10 = 2` (one-shot), `+0x18 = 1`, and **no other `ThinkUnit` binds logical 21**, so
RB-alone really is unclaimed.

> **Before patching anything, confirm in-game what command `0x47` actually makes the player and his
> team-mate do.** If PassAndGo's *effect* is wrong rather than its *trigger*, none of the edits
> below help.

On success `vf17` also stores a **target player index** to `[this+0x19]` (`0x1440e546b`
`41 88 5e 19`, `r14 = rcx = this`), taken from `[ctx+0x1c]` when the third argument is 0 or 2, else
from a pass-route path with a 1.0 s window (`0x1440e53e3`). `+0x19` is **overloaded** — `vf1` clears
it and `vf8` reads bit 1 at `0x1440d7e57` — so writing a player index there is PassAndGo-specific.

### 13.2 The three candidate edits, each measured on the real chain bytes [a]

```
                                                      0  1  2  3  4  5  6  7  8  9
SHIPPED, RT up                                        0  1  1  1  0  1  1  1  0  0
SHIPPED, RT HELD                                      0  0  0  0  0  0  0  0  0  0
EDIT 1: chainA node[1].B  5 -> 8     (RT up)          0  1  1  1  1  1  1  1  0  0
EDIT 2: chainA node[0].kind 8 -> 10  (RT HELD)        0  1  1  1  0  1  0  0  0  0
EDIT 3: chainA node[1].mask RB -> LB (ring drives RB) 0  0  0  0  0  0  1  1  0  0
```

> **The two `1`s under EDIT 3 are chain B, not a partial failure.** *(Footnote added 2026-09-20 —
> it is the one row in the matrix whose result does not explain itself.)* `vf17` **ORs** the two
> chains. Once chain A's tap node no longer matches the driven button, chain A can never fire, so
> everything under EDIT 3 comes from chain B — which this edit does not touch and which is still
> keyed to logical 21. Cases 6 (`tap6f/rel1`) and 7 (`held6f`) are exactly the two where chain B
> fires on the sixth frame of a hold (`6 + 1 = 7 > B = 5`, so chain A was never the source there
> either). **Retargeting the button properly means editing chain B's masks at `0x1486b8958`
> (node[1]) and `0x1486b8980` (node[2]) as well**, or chain B keeps firing on a six-frame hold of
> the old button.

| edit | address | current | proposed | effect | risk |
|---|---|---|---|---|---|
| **1 — widen the tap window** | `0x1486b8904` | `05 00 00 00` | `08 00 00 00` (1..100) | accepts `press+releaseAge ≤ B`; `B=8` adds a 2-frame tap released 5 frames ago | low |
| **2 — drop the "RT not held" gate** | `0x1486b88d4` | `08 00 00 00` | `0a 00 00 00` (kind 10) | chain A fires while sprinting. Chain B keeps its own gate unless `0x1486b8934` gets the same | medium — `+0x10` must stay `00`, `+0x20` must stay `bf 80 00 00`, or kind 10 dispatches through a **null pointer** |
| **3 — retarget the button** | `0x1486b88f8` | `00 00 20 00` | any `1<<n`, `n ≤ 31` | moves the tap to another button | **high for LB** — `1<<18` collides with `CursorChange`'s press edge |

### 13.3 Write order and preconditions

1. The process must already have evaluated `PassAndGo::vf17` at least once (be in a match with a
   pad-driven player) so **both** TLS guards have run — chain A's at `0x1440e52c0 39 05 5a 36 5d 04`
   = `cmp [0x1486b8920], eax`, and **chain B's at `0x1440e52cf 39 05 d3 36 5d 04` =
   `cmp [0x1486b89a8], eax`** *(the second guard's address is now resolved; the earlier draft gave
   only its bytes while telling you to wait for it)*, with `eax = TLS[_Tss_index][0x6d0]`,
   `_Init_thread_header 0x144f7e278` / `_Init_thread_footer 0x144f7e218`. **Writing earlier is
   overwritten.** The initialiser bodies are `0x1440e548c..0x1440e54d8` (chain B) and
   `0x1440e5508..0x1440e553f` (chain A); each ends `call 0x14533ea80 ; mulss [0x145e87854] ;
   addss [0x147850248] ; cvttss2si` — that is where the runtime `B` comes from.
   *(Guard values after initialisation were not emulated — [b] from the MSVC epoch pattern only.)*
2. Write only the four bytes named; leave `+0x10`, `+0x20`, `+0x24` alone.
3. Do **not** touch the node counts at `0x1440e52f9` / `0x1440e5334` — those are displacement bytes
   inside `lea r8d,[rbp+2]` / `[rbp+3]` (`44 8d 45 02` / `44 8d 45 03`), i.e. an instruction patch.
   To **shorten** a chain, overwrite the unwanted node's kind with 10 (proven). There is **no
   data-only way to lengthen** one.
4. No registry commit is needed (§ 11) — these bytes are not a registry record.
5. There is no static way to verify the result. **Test in-game and be ready to restart.**
   `tools/live_patch.py`'s `probe` is the existing runtime write path.
6. **Scope limit (§ 7.6): this reaches only a player on a hardware pad.** It cannot give the CPU or
   your off-ball team-mates a trigger run.

### 13.4 `ThinkUnitFriendPress` — the shipped "one button, two meanings" shoulder [b]

*(Re-imported 2026-09-20 from `registry-pad-command-channel.md` § 14.8. The § 16 class table still
called FriendPress "the template for one button, two meanings", but the addresses that make that
sentence actionable had been dropped, which left the one shipped example of the feature the owner
wants unusable.)*

`vf8` at **`0x1440e9240`** opens `mov rcx,[rdx] ; call 0x1442d6de0` (the `UMatchInfo` accessor),
then `cmp byte [rax+0x4222], bpl`, then gates on another button's **level**:

```
0x1440e928c  lea edx,[r15+0x13]          ; r15d = 0 (xor at 0x1440e9269) -> logical 19
0x1440e9294  call 0x144310750(pad, 19 /*= RT per § 2, which is [c]*/, 0)   ; LEVEL, not an edge
   held  ->  0x1440e92e0 mov r8d,3 ; 0x1440e92e6 lea rdx,[0x1486b89b0] ; call 0x14430fb40
   else  ->  0x1440e9309 lea edx,[r8+0x13] ; call 0x144310750  (re-tested)
             0x1440e937a lea rdx,[0x1486b8a90] ; call 0x14430fb40   (3 nodes)
             0x1440e93ad lea rdx,[0x1486b8a30] ; call 0x14430fb40   (2 nodes)
```

Note the button id and both node counts arrive as **`lea` forms** (`lea edx,[r15+0x13]`,
`mov r8d,3` / `lea r8d,[rbp+N]` in PassAndGo) — the encoding trap that made an earlier probe report
"count is the caller's literal" (§ 14 item 10). A scan for `mov edx, imm` finds none of this.

All three chains are zero-at-load `.text` memory built once behind their own TLS guards
(`0x1486b8a28`, `0x1486b8a80`, `0x1486b8b08`, each with the `_Init_thread_header 0x144f7e278` /
`_Init_thread_footer 0x144f7e218` pair) by the same five node builders as PassAndGo
(`0x14430edb0` kind 1, `0x14430edf0` kind 8, `0x14430ee30` kind 2, `0x14430ee80` kind 9), and all
use the same 100-frame window. **Second-man press behaves differently while sprint is held.** That
is the shape a trigger-run feature should copy: a shoulder with two meanings separated by another
button's *level*, not by a timer. Same tier-1 write route as § 13.2.

---

## 14. Corrections to finished chapters

**To `registry-pad-command-channel.md`** (now superseded by this file; corrections listed so older
briefings built from it can be audited):

1. **§ 14.6 — kinds 1 and 3 are swapped.** Kind 1 = **PRESS** edge (`0x14430d830`,
   `~older & newer & mask`), kind 3 = **RELEASE** edge (`0x14430d980`, `~newer & older & mask`). The
   section's own correction paragraph had it right and contradicted its prose label. [a + b]
2. **§ 14.6 — kinds 8/9 are not "level tests at the anchor frame".** They require a **run of
   `start+1` consecutive contrary-free frames beginning at index 0 or index 1**; the scan reaches
   index `start+1`. The slack is **positional, not a budget**: the run counter is reset by
   `0x14430dba4 test ebx,ebx ; mov eax,0 ; cmovg ebx,eax` (kind 9: `0x14430dc66`), which only bites
   once the run has started, and the iteration budget `0x14430dbb0 cmp r15d,esi ; jl` (kind 9:
   `0x14430dc6b`) is exhausted by any later contrary frame. "RT not held" means *RT was up for the
   whole gesture except possibly the current frame*. [a + b]
   *(This item itself was wrong in the 2026-09-20 first draft, which said "≤ 1 contrary frame of
   slack" anywhere in the region and cited `xor r8d,r8d` at `0x14430db34` / `0x14430dbf6` as the
   mechanism. Both of those are plain counter initialisation and implement nothing. See § 5.3.)*
3. **§ 14.6 — the kind-4 "bound" is the handler's `start`.** Law: `pressDuration + releaseAge ≤ B +
   start`. [b]
4. **§ 14.6 — the kind space is 0..13, not 0..10**, and `0x14430fb40` is not the only evaluator:
   `0x14430fcc0` (wrapper `0x14430fac0`) handles 11/12/13 as stick-group accumulators. **But the
   dispatch tables are only 12 entries each** (kinds 0..11, the three bases `0x60` apart), and
   `0x14430fb40` bounds-checks nothing, so kinds 12/13 arriving at the *first* evaluator index into
   the next table rather than faulting (§ 5.5). [b]
5. **§ 14.9 / § 14.13 item 6 — "5 rows, a lower bound, branches not taken" is wrong about the
   cause.** `0x1440d8b20` is branch-free and always writes **16 rows into three tables**; it is the
   **feint / skill-move** table, consumed by `ThinkUnitFeint::vf8`; T2[1] and T2[2] are permanently
   gated off. [a + b]
6. **§ 14.1 / § 14.10 — "a 15-entry jump table … only one branch binds a pad block; the other 14
   were not traced".** Three targets, two of which bind a pad block identically; codes 0 and 14 bind
   nothing. [b]
7. **§ 14.10 — the ThinkContext table describes the *unit* context, not the struct `0x1440d7010`
   builds.** Both are now correct and reconciled in § 7.7; `+0x24` is a **player number 0..21**, not
   the pad index. [b, verified for this chapter]
8. **§ 14.11 — "CPU side `0x1442d0050` / `0x1442d12d0`, nearest `CpuDynamicObject`" is not evidence
   of a CPU command path.** `CpuDynamicObject` is `Enlighten::CpuDynamicObject`, a global-illumination
   class (vftable `0x1473404a0`); there is no `match::Cpu*` RTTI at all. The CPU receives **no**
   pad-channel input (§ 7.6). [b]
9. **§ 14.11 — "the pad → executor hand-off is NOT established" is closed.** It is the command-record
   decoder `0x144317cd0` (§ 8.3). The separate correction about `0x144261bd0` opening no
   `UCommandOutput::ScopedRead` stands. [b]
10. **§ 14.12 — "`count` is the caller's literal (`mov r8d, 2` / `3`)" is the wrong encoding**
    (`lea r8d,[rbp+N]`), and **"`vf17` returns a target index in `[behaviour+0x19]`"** is
    `[this+0x19]`. Add the kind-10 table-C constraint and the § 7.6 scope limit. [b]
11. **§ 14.13 item 2 — CLOSED.** `+0x10` is the command **lifecycle class**; the switch is at
    `0x1440dd691` (§ 6). The section's warning not to read it as "press edge" was right.
12. **§ 14.13 item 3 — CLOSED and emulated.** `ScopedWAndC` on `UPadInput` is a no-op (§ 11). [a]
13. **§ 14.13 item 4 — CLOSED.** `match::Player+0x7f49` is `(Player+0x7660)+0x8e9`; writers
    `0x14415bb9c` (=0) and `0x14415bbef` (=1) inside `0x14415b850`. "No writer on any base in
    `0x7f00..0x7f60`" was right from the wrong frame. [b]
14. **§ 14.13 item 5 — CLOSED.** A pad-driven carrier **does** run `match::ai::bp` (§ 7.5). [b]
15. **§ 14.13 item 7 — CLOSED.** All eleven table-C kinds named and emulated (§ 5.3).
16. **§ 14.13 item 8 — PARTIALLY CLOSED.** The scheduler is `cobra::game::ListenerManager`, event id
    1; the ordering between its two event-1 handlers remains runtime data and stays [c] (§ 11).
17. **The patch-hygiene note is obsolete**: the installed image is now byte-identical to PRISTINE
    (header), so the pad-band difference at `0x144311572`/`0x144311579` no longer exists.

**To `ball-carrier-brain.md`:**

18. **The activation paragraph and THE DECISION LOOP step 1** gloss `byte[match+0x41f6+idx]` as "the
    player is on the ball". It is the **human-control-allocation** byte:
    `flag[idx] = (positionRank[idx] ≤ controlCount[team])`, cursor player forced to rank 0. With that
    relabel, **OPEN 8's first half is answered**: the carrier brain activates only for
    human-assigned players, so the human's carrier does run it. [b for the gate, a for the rule]
19. **OPEN 14 and the "two possible worlds" paragraph** — `match::Player+0x7f49` is an **action/command
    latch**, written every tick for every player by `0x14415b850` on the ungated ticker chain
    `0x14414a340` → `0x1442457c0` (set when `0x144311e20` passes on the current action, inside its
    `+0x1e ≤ +0x1a` window, bit 17 of `+8` clear, and the pending command id `& 0x7f == 0x44` or
    `0x1442e2a60(match, idx)`; cleared on action `0x22` or when `UMatchInfo+0x3308 != 1`). It is
    **not** "pad-controlled", so the first of the two worlds is eliminated. [b]
20. **"Where it lives"** lists `match::CommandPlayer at +0x7658` inside the per-player AI container.
    `match::CommandPlayer` is heap-allocated 24 times (`0x1c10` bytes each, `0x1440d4a80`) into
    `match::Command+0x2b7e0`; it is **not** embedded in `match::Player`. What sits at container
    `+0x7660` is a distinct `0x900`-byte object reset by `0x14415cf00`. [b]

**To `player-executors.md`:** the run-phase chapter's open "pad → executor hand-off" item is closed
by § 8.3 — `0x144317cd0`. Its five unnamed callers (`0x14414b950`, `0x144162070`, `0x14415f660`,
`0x1442b6760`, `0x14422d570`) are the next functions to identify; one is probably the `ActionShoot`
parameter read.

**To `docs/exe-gameplay-map.md`:** line 172's pad-unit summary is confirmed independently (four-state
machine on `+0x1c`, fill rates 0.25/0.30/0.60 with mode-3 variants 0.38/0.42/1.00, no RNG, no
difficulty read); add that the gauge is `unit+0x20`, that it **is** the kick power, and that the
machine also leaves the held state when the gauge fills. Line 98's open question — "Where does CPU
difficulty enter `0x14401a900`'s tree?" — can be upgraded from "nothing obvious" to a **checked
negative** (§ 8.4).

**To `docs/realism-todo.md` item 2:** beyond the correction already applied there, **the binding is
not missing.** PassAndGo chain A already fires on a tap of logical 21 while logical 19 is up
(= "RB tap, RT not held" *if* the § 2 hardware map is right, which is [c]) and emits command `0x47`.
The open question is whether `0x47`'s *effect* is the wanted trigger run, which can only be answered
in-game.

### 14.A Corrections to THIS chapter — repair pass 2026-09-20

Three adversarial reviews of the 2026-09-20 first draft. Every row below was re-checked against
PRISTINE's bytes before the text was changed; nothing under any reviewer's "holds" list was touched.

| # | what was wrong | what the bytes say | where fixed |
|---|---|---|---|
| **1** | **"No dt270 field reaches `match::pad`"** — asserted as a negative, evidenced by "a census of the constant loads in this band" | **Refuted.** A constant-load census cannot see a dt270 value (it arrives via `GetParam` + a deref, never as a literal). `ThinkUnitTrapStop::vf8` fetches object `0x6f` at `0x1440e884b` and gates itself on `byte [rax+0x1c8]`, then multiplies `[rbx+0x1c4]` by the live frame rate at `0x1440e887c`. `0x1440d64a5` fetches object `0x6a` and reads `[rax+0xbc]`. Object names read from the game's own registration table `0x1475d2ba0`: **`trap.json`** and **`grounderpass.json`**; runtime offsets → `stopTrap.use`, `stopTrap.inputTime`, `search.searchMinDist`. Bonus negative from the data side: **`stopTrap.use` ships `false` in PRISTINE and installed alike**, so the unit is inert as shipped | "What this enables"; § 12 dt270 block |
| **2** | **Power-127 re-aim address `0x144317868`** | `0x144317860` is the `mulss` (disp32 at `0x144317864`); `0x144317868` is `f3 0f 2c c0 = cvttss2si eax,xmm0`. **A four-byte re-aim at the quoted address corrupts the quantiser.** And the cell has **5** command-band referrers, not 2 | "What this enables"; § 12 |
| **3** | **Cursor 0.8 "two load sites", `0x1440e757c`** | `0x1440e757c` is `0f 2f c6 = comiss xmm0,xmm6`; the `movss` starts at `0x1440e7574`. There are **7** sites, 4 + 3 across the two units — re-aiming one leaves three comparisons in the same function on the old value | § 9; § 12 |
| **4** | **0.42 / 0.38 "effectively private — the safest edit in the subsystem"** | 9 of 0.42's 10 referrers and 5 of 0.38's 6 are unrelated live match code (`ThrowinLoop`, a `match::registry` method, several `match::anime`). An in-place cell edit retimes all of them. Rerouted to a single-instruction re-aim; the "safest edit" label moved to the tier-1 PassAndGo node fields | § 12 |
| **5** | **"Re-aim the `0x1440d822c` arm only"** for the 0.30 pass gauge | `0x1440d822c` is `cmp edx,3` — no memory operand. 0.30 has **one** load in the function, `0x1440d8268`, and that *is* the shared default; the pass ids reach it by fall-through from `0x1440d822f jne`. **No re-aim isolates open-play pass**; it needs a code rewrite | § 12 |
| **6** | **Route legend treated all routes as one risk class** | They land on three pages with three protections: `.text` `0xc0000040` RW, `.tls$` `0x40000040` R, `.xcode` `0x60000020` RX. Twelve rows were `.xcode` writes presented with no risk note — the class this project's own `live_patch.py` `DENUVO_NOTES` says crashes the game | § 12 legend (new tier table) |
| **7** | **Kinds 8/9 "≤ 1 contrary frame of slack"**, cited to `xor r8d,r8d` | The slack is **positional** — only index 0 may be contrary — and the two cited instructions are counter initialisation. Mechanism is `cmovg ebx,0` at `0x14430dba4` + the `esi` budget at `0x14430dbb0`. Scan reaches index `start+1` | § 5.3; § 14 item 2 |
| **8** | **Dispatch tables implied 14 entries; nulls cited at `0x148081820`/`828`/`838`** | Each table is **12** entries, bases `0x60` apart. `0x148081838` is past the end of A. Real nulls: C[11] `0x148081768`, B[10]/[11] `0x1480817c0`/`0x1480817c8`, A[10]/[11] `0x148081820`/`0x148081828`. **Kinds 12/13 have no slot and no bounds check** — they alias `C[12] ≡ B[0]`, `C[13] ≡ B[1]`, real handlers, so they misbehave rather than fault | § 5.5; § 5.6; § 15 Negative 12 |
| **9** | **§ 7.1 post-loop written as unconditional `if (flags[i]==0) vf2()`** | Three further gates at `0x1440d487a` / `0x1440d4891` / `0x1440d48ab`; an entry failing all three is skipped and gets neither input nor a clear. The substantive negative is unaffected | § 7.1; § 7.6; § 15 Negative 1 |
| **10** | **§ 7.4 pseudocode missing an acceptance path**, and the cursor override shown ungated | The override is gated on `[UMatchInfo+0x3308] ∈ {2,3}` (`0x144308c05`), and inside that arm `0x144308d4a..0x144308d7a` can `return true` **skipping `rank ≤ count`** via `0x1442c4430`. A branch-target scan confirms the bypass is reachable only from inside that arm | § 7.4 |
| **11** | **§ 7.5 "the player under the human's cursor is always covered … guaranteed"** labelled [b] | The "guaranteed" half rests entirely on that gated override. In open play (if 3308 == 1, itself [c]) a low-ranked cursor player is **not** covered. Downgraded to [c] and folded into Open 2 | § 7.5; header; "What this enables" |
| **12** | **§ 7.4's quoted writer `cmp edx,0x16 ; jge`** | Real: `cmp edx,0x15 ; ja 0x1442c5370`. Same bound, different opcodes and condition class. Census numbers unchanged | § 7.4 |
| **13** | **§ 8.1 "Time to full is frame-rate independent"** | Contradicted by its own table: 30 fps shot = 8 frames = 0.267 s; `3308==3` `0x30`/`0x37` at 60 fps = 61 frames = 1.017 s. Qualified to "within one frame of quantisation" | § 8.1 |
| **14** | **"a 139-function closure"** with no normalisation rule | Not reproducible under any rule. Raw direct call/jmp targets, depth 4, `func_chunks` extents: **482**. Root-normalised: **73** — and that rule **deletes the RNG positive control**, because `func_root(0x144345d90)` is `None` (a leaf with no `.pdata`). Negative unaffected; three positive controls and one negative control restated | § 8.4; § 15 Negative 3 |
| **15** | **Feint tables given no extent** | Each array is **100** rows × `0x1b0`, from its own array-destructor thunk (`0x1459a7d10` / `d40` / `d70`, `mov edx,0x1b0 ; mov r8d,0x64`). 16 populated, 84 zero and unsurveyed | § 10; § 12 |
| **16** | **§ 11 "for each of 24 slots … sets the in-use byte"** | The clear is one `mov qword` = 8 bytes; the byte is indexed by the **pad** (`< 8`), not the slot. Added: **blocks 8..23 of `UPadInput` are dead** | § 11; § 1 |
| **17** | **1.0f "11,969 refs / 7,522 functions"; 0.08 "35 functions"** | `exe_census` on PRISTINE: 1.0f `refcount=13240`; 0.08 = 44 refs / **36** functions. Also added: the gauge's own ceiling is an **inline** `0x3f800000` at `0x1440d8291`, which no re-aim would move | § 12 |
| **18** | **Rank tables routed "exe-constant"** | `exe_census` returns `STATUS=table` and vetoes them (`table`, `imgbase_table_base`, `address_taken_by_lea`); the **values are indices 1..11** and the index bound was not analysed. Reclassified NOT-SAFELY-TUNABLE | § 12 |
| **19** | **Stick quantisation "3 sites"** | **12** in the pack/unpack band plus one in `InplayCamera` | § 12 |
| **20** | **`X+0x3c`/`X+0x40` listed as an executable `runtime-data` row** with a "961 readers" sharer count | The base `X` has no located address, so the route cannot be executed; and 961 counts readers of a **struct displacement**, not of a cell, so it is not comparable with the other refcounts. Moved to a separate "not yet actionable" block | § 12 |
| **21** | **"consolidates and supersedes"** | 82 of `registry-pad-command-channel.md`'s 197 addresses appear nowhere here. "Supersedes" withdrawn; `FriendPress` (§ 13.4), the `match::Command` field map (§ 16.1), the `UCommandOutput` census (§ 8.3) and chain B's guard + the chain builders (§ 13.3) re-imported | header; § 8.3; § 13.3; § 13.4; § 16.1 |
| **22** | **§ 18 read as a reproduction manifest** | 13 of the 15 harnesses are scratchpad files that no longer exist, so every `[a]` result is currently un-re-derivable from the repo. Said so in place | § 18 |
| **23** | **"chain A *is* `RT not held` + `RB tap`" badged [a] end to end** | The emulator drives **logical 19 / 21**. Logical → physical is § 2's map, which is **[c]** (XInput axis convention + the in-game control screen, not disassembly). Split the badge; added a one-shot in-game falsification as Open 21 | "What this enables"; § 2; § 13.1 |
| **24** | **§ 13.2 EDIT 3's two residual `1`s unexplained** | They are chain B, which the edit does not touch. Footnoted, with the two chain-B mask addresses a real retarget would also need | § 13.2 |

---

## 15. Negatives — proven absent, do not spend a week on these

1. **The CPU does not receive synthesised pad input.** **No entry in the post-loop sweep ever
   receives input** — pad-bound entries are driven by the main loop, participating non-pad entries
   get `CommandPlayer::vf2` = `0x1440de4f0` (a pure clear), and entries failing all three gates at
   `0x1440d487a`/`0x1440d4891`/`0x1440d48ab` are skipped entirely. No pad-level change can reach a
   CPU team or your own off-ball players. [b] *(Wording corrected 2026-09-20: the earlier "every
   entry with `flags[i]==0` gets `vf2`" overstated what was proven, without weakening the negative.)*
2. **No assistance setting reaches the command layer.** Nothing in `match::Command::update`,
   `0x1440d31a0` or `0x1440d6e00` reads Control Style / Pass Search / Shoot Type / Ball Cource;
   assistance changes neither the ControlMode nor which ThinkUnit fires. Where it *does* land is not
   proven. [b for the negative]
3. **No human/CPU asymmetry in the kick-error model.** Depth-4 closure over **raw direct call/jmp
   targets** (`func_chunks` extents) = **482 functions**; three positive controls in
   (`0x143ed71d0` at depth 1, ATTR_get, the RNG), two difficulty reads and the command decoder out,
   zero `0x2b4dc`/`0x2b900`/`0x2f5c0` operands, displacement scan with its own positive control (11
   hits in `Command::update`), negative control returns 1. Direct calls only; virtual dispatch
   inside the closure was not followed. [b/c] *(The old "139 functions" is withdrawn — it does not
   reproduce; and a root-normalised walk, which gives 73, silently loses the RNG control because
   `func_root(0x144345d90)` is `None`.)*
4. **Nothing outside `match::pad` / `match::Command` reads the pad ring** — 164 call sites of the
   five raw getters, all in the pad band but two functions. Input reaches the executors only as a
   decoded 16-byte record. [b]
5. **There is no held-frame counter anywhere in the pad layer.** Power is an accumulating float; a
   search for "frames held" finds nothing. [b]
6. **`match::Player+0x7f49` is not a pad-control flag** (§ 14 item 19). [b]
7. **There is no `match::Cpu*` class in the RTTI.** [b]
8. **`0x41f6` has exactly one writer** (`0x1442c5368`) against 961 read sites — there is no second,
   per-frame writer. [b]
9. **ControlModes 1..9 are not individually named.** The 93 surviving debug strings at
   `0x146b9d3c0..0x146b9e5e0` name the *reasons*, every one is unreferenced (the printfs were
   compiled out), and no `%s` name table survives. `0x1440d7b20`, which looked like a name lookup,
   returns one fixed pointer regardless of `ecx`. [b]
10. **`0x1440de840` is not a power path** despite owning 12 of the 14 analog-pressure call sites — it
    is an idle/AFK detector. [b]
11. **The shipped game never builds node kinds 0, 3, 5, 10 or 12**; kind 3 is reached only from
    inside kinds 4 and 7. [b]
12. **Kind 10 cannot return −1 (vacuously true) but consumes one frame, and exists only in dispatch
    table C.** The permanent nulls are `A[10]` `0x148081820`, `A[11]` `0x148081828`, `B[10]`
    `0x1480817c0`, `B[11]` `0x1480817c8` and `C[11]` `0x148081768`; kind 10 or 11 through A or B
    faults. **Kinds 12 and 13 do NOT fault** — each table is only 12 entries and `0x14430fb40`
    bounds-checks nothing, so `C[12] ≡ B[0] = 0x14430dc80` and `C[13] ≡ B[1] = 0x14430dd60` are
    real handlers run on a node with no stick constraints. Kind 10 is the only safe neutering
    value. [a for the fault, b for the table geometry] *(Corrected 2026-09-20 — the earlier item
    named `0x148081838`, which is past the end of table A, and promised a fault for 12/13.)*
13. **The LB cursor chooser is NOT located.** Only two consumers of command `0x37` were found and
    both are suppressors. [b for the absence of a chooser in what was searched]
14. **The relative order of the pad write and `match::Command::update` inside one tick is still not
    proven** — the scheduler is identified but `Listener+0x108` is left at its ctor default by both
    concrete ctors. Cost is bounded to a uniform one-frame latency (§ 11).
15. **A saturation artefact, recorded rather than hidden:** the first node-kind sweep passed the pad
    *wrapper* where the handlers want the pad-slot *block*, and every scenario returned the same
    value. It is kept here as the method warning it is (§ 5.2).
16. **A stub artefact, likewise:** the control-flag emulation's team-1 column is constant 0 for every
    input because the squad-order stub returned a team-0 order for both teams. **Only the team-0
    column is evidence** (§ 7.4).
17. **`ThinkUnitTrapStop` does nothing in the shipped game.** Its `vf8` (`0x1440e8820`) fetches
    dt270 object `0x6f` (`trap.json`) and returns immediately unless `stopTrap.use` is set;
    `stopTrap.use` is **`false`** in `dt270_console_all.PRISTINE.cpk` and in the installed CPK.
    Anyone hunting a trap-stop behaviour in the pad layer is looking at dead code until that
    boolean is flipped. [b + data] *(Added by the repair pass.)*
18. **The exe-constant census is blind to dt270.** The negative "no dt270 field reaches
    `match::pad`" was produced by a census of RIP-relative constant loads, which structurally
    cannot see a value that arrives through `GetParam` and a pointer deref. **Recorded here as a
    method warning, not a finding**: a negative is only as strong as the instrument's reach, and
    this instrument could not have found what it claimed was absent. *(Added by the repair pass.)*

---

## 16. Class status — all 73 classes

`btn` is the logical button id from the factory (33 = none, and see § 2 for the map); `cls` is
`+0x0c` (0/1 = stick unit, 2 = button unit); `life` is `+0x10` (§ 6); `ovr` lists the vtable slots
each class overrides relative to `ThinkUnitBase`. Bindings [a-emulated from `0x1440e0c70`]; vftables
and overrides [b, from `build/exe_map.json`].

| class | vftable | btn | cls | life | ovr | notes |
|---|---|---|---|---|---|---|
| `ThinkUnitBase` | `0x146ba0588` | — | — | — | — | the shared machine: `vf1` reset, `vf8` press machine, `vf17` rising edge |
| `ThinkUnitShortPass` | `0x146ba34d0` | 24 A | 2 | 4 | 9,10,13,14 | charged; `vf14` = id `0x38` class |
| `ThinkUnitLongPass` | `0x146ba3568` | 23 B | 2 | 4 | 0,1,9,10,13,14,17 | charged; `+0x14 = 2` ⇒ multi-press path |
| `ThinkUnitThroughPass` | `0x146ba3600` | 22 X | 2 | 4 | 0,1,8,9,10,13,14 | charged |
| `ThinkUnitShoot` | `0x146ba33a0` | 25 Y | 2 | 4 | 0,9,10,13,14,17 | `vf13` = charge tick `0x1440e5cb0`; `vf14` = `0x3d` |
| `ThinkUnitClear` | `0x146ba3438` | 25 Y | 2 | 4 | 9,12,13,14,17 | **always full power** (flat 1.0 in `0x1440db720`) |
| `ThinkUnitKickFeint` | `0x146ba30a8` | 24 A | 2 | 4 | 0,1,12,17 | charged |
| `ThinkUnitKickoff` | `0x146ba4998` | 24 A | 2 | 4 | 12,17 | charged |
| `ThinkUnitPenaltykick` | `0x146ba75d0` | 25 Y | 2 | 4 | 0,10,13,14 | charged |
| `ThinkUnitKeeperAutoPuntkick` | `0x146ba4440` | 23 B | 2 | 4 | 1,12,17 | charged |
| `ThinkUnitAutoRestart` | `0x146ba53b0` | 24 A | 2 | 4 | 0,1,12,17 | charged |
| `ThinkUnitBlockTestAutoRestart` | `0x146ba5448` | 25 Y | 2 | 4 | 12,17 | charged |
| `ThinkUnitCursorChange` | `0x146ba3db8` | **18 LB** | 2 | 2 | 12 | `vf12` = `mov eax,0x37`. **Press edge — blocks any "tap LB" binding** |
| `ThinkUnitCursorChangeManual` | `0x146ba3e50` | 33 | 1 | 2 | 13,14,16 | right-stick, threshold 0.8 |
| `ThinkUnitCursorChangeKeeper` | `0x146ba3ee8` | 13 menu | 2 | 2 | 12 | |
| `ThinkUnitTeammateSwitch` | `0x146ba3f80` | 33 | 1 | 2 | 11,13,14,16 | right-stick, threshold 0.8 |
| `ThinkUnitPassAndGo` | `0x146ba6450` | 33 | 2 | 2 | 12,17 | **the trigger-run unit**; `vf17` = the two chains, `vf12` = `0x47` |
| `ThinkUnitFeint` | `0x146ba3010` | 33 | 1 | 2 | 0,1,8 | `vf8` walks the 16-row gesture table (§ 10) |
| `ThinkUnitDribble` | `0x146ba31d8` | 33 | 0 | 0 | 10,12,13,16 | |
| `ThinkUnitFreeMove` | `0x146ba3140` | 33 | 0 | 0 | 13,16 | also a base of two other units |
| `ThinkUnitPress` | `0x146ba4e58` | 33 | 2 | 1 | 8 | |
| `ThinkUnitPressGK` | `0x146ba4f88` | 28 X-def | 2 | 1 | 8 | |
| `ThinkUnitDelay` | `0x146ba4ef0` | 33 | 2 | 1 | 8 | |
| `ThinkUnitTackle` | `0x146ba4c90` | 33 | 2 | 2 | 8 | |
| `ThinkUnitShoulder` | `0x146ba4d28` | 31 Y-def | 2 | 2 | 12 | **not a shoulder button** — the barge, a 3.0 m proximity test |
| `ThinkUnitSliding` | `0x146ba4dc0` | 29 B-def | 2 | 2 | 12 | |
| `ThinkUnitFriendPress` | `0x146ba5020` | 27 RB-def | 2 | 1 | 0,1,8 | `vf8` picks a different chain when RT is held — the template for "one button, two meanings" |
| `ThinkUnitKickCancel` | `0x146ba3698` | 19 RT | 2 | 1 | 8,12,17 | |
| `ThinkUnitSuperCancel` | `0x146ba3308` | 19 RT | 2 | 1 | 0,13,17 | reads the ControlMode at unit-ctx `+0x20` |
| `ThinkUnitTacticsNext` | `0x146ba4608` | 4 D-pad | 2 | 1 | 0,1,8,12,17 | |
| `ThinkUnitTacticsBack` | `0x146ba46a0` | 6 D-pad | 2 | 1 | 0,1,8,12,17 | |
| `ThinkUnitTacticsAttackLevelUp` | `0x146ba4738` | 4 D-pad | 2 | 1 | 0,8,12,17 | |
| `ThinkUnitTacticsAttackLevelDown` | `0x146ba47d0` | 6 D-pad | 2 | 1 | 0,8,12,17 | |
| `ThinkUnitLineControlFront` | `0x146ba44d8` | 5 D-pad | 2 | 1 | 0,1,8,12,13,17 | |
| `ThinkUnitLineControlBack` | `0x146ba4570` | 7 D-pad | 2 | 1 | 8,13,17 | |
| `ThinkUnitTrapThrough` | `0x146ba8d18` | **18 LB** | 2 | 0 | 0,8 | `vf8` uses the pattern engine |
| `ThinkUnitTrapLift` | `0x146ba4868` | 13 menu | 2 | 0 | 8 | |
| `ThinkUnitTrapStop` | `0x146ba4900` | 13 menu | 2 | 0 | 8 | **INERT AS SHIPPED** — `vf8` (`0x1440e8820`) reads dt270 `trap.stopTrap.use`, which is `false` in PRISTINE, so `0x1440e885a je` skips the whole body. Its window is `trap.stopTrap.inputTime` (0.5 s) × live FPS (§ 12) |
| `ThinkUnitMoveStopGoal` | `0x146ba3270` | 19 RT | 2 | 0 | 8 | |
| `ThinkUnitPassRequest` | `0x146ba5150` | 24 A | 2 | 2 | 0,1,12,17 | |
| `ThinkUnitGoalkickPassSupport` | `0x146ba5578` | **18 LB** | 2 | 0 | 0,1,8,14,17 | |
| `ThinkUnitShortCorner` | `0x146ba5610` | **18 LB** | 2 | 2 | 14,17 | |
| `ThinkUnitFreeKickPositionChange` | `0x146ba3c88` | **18 LB** | 2 | 2 | 14,17 | |
| `ThinkUnitFreekickWallJump` | `0x146ba3a28` | 29 B-def | 2 | 2 | 12 | |
| `ThinkUnitFreekickWallNotJump` | `0x146ba3ac0` | 30 A-def | 2 | 1 | 13 | |
| `ThinkUnitFreekickWallPress` | `0x146ba3b58` | 31 Y-def | 2 | 2 | 12 | |
| `ThinkUnitFreekickKeeperMove` | `0x146ba3bf0` | 28 X-def | 2 | 1 | 13 | |
| `ThinkUnitFreekickTypeChange` | `0x146ba3990` | 4 D-pad | 2 | 2 | 12,17 | |
| `ThinkUnitFreeKickTactics` | `0x146ba3d20` | 1 system | 2 | 2 | 0,1,8 | |
| `ThinkUnitCornerKickTactics` | `0x146ba56a8` | 1 system | 2 | 2 | 0,1,8 | |
| `ThinkUnitCornerKickDefenceType` | `0x146ba5740` | 1 system | 2 | 2 | 0,1,8 | |
| `ThinkUnitKickOffChange` | `0x146ba4a30` | 4 D-pad | 2 | 2 | 12,17 | |
| `ThinkUnitSetplayGuide` | `0x146ba57d8` | 33 | 0 | 0 | 0,1,5,8 | the only class overriding `vf5` |
| `ThinkUnitPenaltykickGuide` | `0x146ba38f8` | 33 | 0 | 0 | 0,1,8 | second base `ThinkUnitGoalMouseTarget` — genuine multiple inheritance |
| `ThinkUnitKeeperAutoMove` | `0x146ba4018` | 26 LT-def | 2 | 2 | 13,17 | |
| `ThinkUnitKeeperPress` | `0x146ba40b0` | 28 X-def | 2 | 2 | 13,17 | |
| `ThinkUnitKeeperTrapMove` | `0x146ba4148` | 13 menu | 2 | 0 | 13 | |
| `ThinkUnitKeeperBlock` | `0x146ba41e0` | 29 B-def | 2 | 0 | 12 | |
| `ThinkUnitKeeperTackle` | `0x146ba4278` | 31 Y-def | 2 | 0 | 13,17 | |
| `ThinkUnitKeeperPickupBall` | `0x146ba4310` | 19 RT | 2 | 0 | 12,17 | |
| `ThinkUnitKeeperDropBall` | `0x146ba43a8` | 19 RT | 2 | 0 | 12,17 | |
| `ThinkUnitKeeperPenaltykickMove` | `0x146ba3730` | 33 | 0 | 0 | 13,16 | derives from `ThinkUnitFreeMove` |
| `ThinkUnitKeeperPenaltykickAction` | `0x146ba37c8` | 33 | 0 | 3 | 13,16 | one of only two latched-on-acknowledge units |
| `ThinkUnitKeeperPenaltykickLayer` | `0x146ba3860` | 33 | 1 | 3 | 13,16 | the other |
| `ThinkUnitCameraTarget` | `0x146ba50b8` | 0 system | 2 | 2 | 12,17 | |
| `ThinkUnitKickerSelect` | `0x146ba5318` | 0 system | 2 | 2 | 0,1,8 | |
| `ThinkUnitPause` | `0x146ba51e8` | 1 system | 2 | 2 | 0,12,17 | |
| `ThinkUnitChat` | `0x146ba5280` | 1 system | 2 | 2 | 12,17 | |
| `ThinkUnitDemoSkip` | `0x146ba4ac8` | 2 system | 2 | 2 | 12,17 | |
| `ThinkUnitOutofPlaySkip` | `0x146ba4b60` | 1 system | 2 | 2 | 12,17 | extra base `ThinkUnitSkip` |
| `ThinkUnitQucikMemberChange` | `0x146ba5870` | 2 system | 2 | 2 | 0,8 | Konami's spelling |
| `ThinkUnitInteractiveGoalDemo` | `0x146ba4bf8` | 33 | 1 | 2 | 8 | |
| `ThinkUnitThrowinBodyAngleRotation` | `0x146ba54e0` | 33 | 0 | 0 | 13,16 | derives from `ThinkUnitFreeMove` |

**Four further names exist only as class-hierarchy descriptors, with no vftable of their own:**
`ThinkUnitPadId` (base of every button unit), `ThinkUnitStickKind` (base of every stick unit),
`ThinkUnitSkip` and `ThinkUnitGoalMouseTarget`. [b]

**Pad-adjacent classes outside the namespace:** [b]

| class | vftable | what it is |
|---|---|---|
| `match::Command` | `0x146b9e7d8` | 20 vtable slots, **17 of them the `ret 0` stub**; the per-frame work is the non-virtual `update` `0x1440d4180` |
| `match::CommandPlayer` / `CommandPlayerBase` | `0x146ba0620` / `0x146ba0558` | the per-player unit host; `vf2` = clear, `vf3` = think. 24 heap-allocated `0x1c10`-byte instances at `match::Command+0x2b7e0` |
| `match::CommandListener` | `0x146afbd18` | the match-loop hook; `vf1` handles event id 1 → `vf5` → `Command::update` |
| `match::PostCommandListener` | `0x146afc320` | the after-commands hook |
| `match::MatchCommandObject` | `0x146afb6f8` | `0x5358` bytes; owns the listeners |
| `match::ParameterGameCommandPriority` | `0x147740750` | `0x320` bytes; the command-priority parameter block |
| `match_system::pad_action::{ActionResolver, TriggerPress, TriggerClick}` + `match::ReplayPadActionResolver` | `0x147714878`, `0x147746a30`, `0x147746a50`, `0x1477148c8` | the **replay/highlight** input layer — dispatch an action id through a vector of 24-byte handler entries. **Not the live pad** |
| `cobra::game::PadInputAssign` | `0x146a77bc8` | `0x58` bytes; the platform-side pad→slot assignment feeding `0x1453e7130` |
| `match::OnlineCommandController` / `…Impl` + the Online listener/binary/sender family | `0x14773b808` / `0x14773b900` | the network ingress that owns `UCommandInfo` |
| `match2D::Screen::{ModelCursor, ModelCursorName, ModelCursorNextTarget}` | `0x147719508`, `0x147719b90`, `0x14771a1f8` | the cursor HUD models; `ModelCursorNextTarget` existing means a next-player choice **is** computed somewhere (§ 9) |
| `match::cursor::CursorManager` | `0x146affcf0` | only 2 virtuals; `vf1` is a replay-record receiver, **not** the chooser |

### 16.1 The `match::Command` / `match::CommandPlayer` registry-ref field map [b, carried over]

*(Re-imported 2026-09-20 from `registry-pad-command-channel.md`, which this chapter had dropped.
Without it there is no way to find `UPadInput` or `UCommandOutput` from a live `match::Command`
pointer, which is the first thing any runtime probe needs.)*

**`match::Command`** — ctor `0x1440d2970`, vtable `0x146b9e7d8`:

| offset | ref |
|---|---|
| `+0x2b8a8` | `CameraInfoRef` |
| `+0x2b900` | the pad sub-system |
| `+0x2b4dc` | the 32-byte ControlMode records, stride 32 (§ 7.3) |
| `+0x2b7e0` | the 24 heap `match::CommandPlayer` pointers |
| `+0x2f568` | `MatchInfoRef` |
| **`+0x2f5c0`** | **`PadInputRef`** |
| `+0x2f618` | `CursorInfoRef` |
| `+0x2f670` | `Screen2dInfoRef` |
| **`+0x2f6c8`** | **`CommandOutputRef`** |

**`match::CommandPlayer`** — ctor `0x1440dd750`, vtable `0x146ba0620`, `0x1c10` bytes:
`+0x1a38`/`+0x1a3c` the active-unit lock (`0x51` = 81 unit slots), `+0x1a4c..+0x1a60` the 20-byte
direction/power block (§ 8.2), `+0x1a6d` the cursor-suppression byte (§ 9), `+0x1ab0`
`CommandOutputRef`, `+0x1b08` `Screen2dInfoRef`, `+0x1b60` `CommandInfoRef`, `+0x1bb8`
`StepupTutorialRef`.

---

## 17. Open questions

1. **What does command `0x47` actually do in a match?** Everything in § 13 assumes the trigger is
   the interesting part; if the effect is wrong, no data edit helps. **Answerable only in-game.**
2. **The runtime values of `X+0x3c` / `X+0x40`** (the per-team human-control counts), and the base
   of `X` itself. No writer located in `0x144300000..0x144320000` under any `mov [reg+disp8], r32`
   encoding. This is now **two** links, not one: between "bp is gated on the human-control byte"
   [b] and "bp never runs for the CPU team" [c], **and** between that gate and "the human's own
   cursor player always runs bp" [c] (§ 7.5) — because in open play the cursor override does not
   fire and coverage falls back to `rank ≤ count`. **The highest-value open item in the whole
   subsystem map.** Suggest a `live_patch.py` probe, not more static work.
3. **How much correction does the sub-0.10-stick aim assist apply?** `0x1440de060`,
   `teamCtx+0x4ec`, `teamCtx+0x4f0` were not emulated. The only place a human could be given an
   advantage the CPU does not have.
4. **Which player does LB pick?** No scoring function found (§ 9).
5. **ControlModes 1..9 individually**, and the mapping of the 93 reason strings onto them. The
   strings are in source order, so tracing `0x1440d31a0`'s 880-instruction `bl != 0` half
   (`0x1440d32bb..0x1440d3b33`, `0x1440d3b7b..0x1440d40aa`) should label cheaply.
6. **Where the assistance settings land**, and whether they edit the COMMAND or the EXECUTION
   (§ 7.8). Candidates named; nothing verified.
7. **`UMatchInfo+0x420c[22]`**, the sibling of the human-control array, computed by `0x1443088a0`
   from the same counts with override array `X+0xf281`, read together with `+0x41f6` in `0x1442cabe0`.
8. **`UMatchInfo+0x3308`** (values 1, 2, 3). It gates the cursor override in the control-flag rule,
   the `Player+0x7f49` clear path, the slow gauge variants (`== 3`) and the cursor auto-snap
   (`== 1`). "1 = open play" and "3 = set piece" are both [c].
9. **The object `X`** (fields `+0x14`, `+0x18`, `+0x3c`, `+0x40`, `+0xf24c[2]`, `+0xf26a`,
   `+0xf26b[22]`, `+0xf281[22]`, `+0xf297`) has no name, nor does its complement array `+0xd634`
   (written alongside `0x41f6` by `0x14430a020` / `0x14430b320` / `0x1442f3a70`).
10. **The gate on the reduced pad branch** — what `[0x14807ffe0]->vf1` and `[0x148080e20]->vf2` are,
    and therefore what distinguishes ControlModes 12/13 in practice (replay? coach mode? a spectated
    cursor?).
11. **`0x14430ffa0`**, the stick-group matcher for kinds 11/12/13. Undecoded; blocks confident
    tuning of the feint rows.
12. **`0x144118530`**, the T2-vs-T3 selector in `ThinkUnitFeint::vf8`.
13. **The 11 feint command ids** are unmapped to named skill moves; the `+0x19c` gate bits `0x02` /
    `0x04` / `0x08` are named by stack slot only (classifier chains `0x1443122e0`, `0x144312240`,
    `0x144311c90`, `0x1443084d0` not followed).
14. **How `ListenerManager` orders its event-1 broadcast** (`Listener+0x108`, default −1).
15. **Who reads `URegistryData entry+0x28`** ("touched"), which a raw external write skips.
16. **What sets `ThinkUnit +0x1c = 4`** (phase 4, `vf15`). No transition path in `vf8` reaches it.
17. **`unit+0x29`** (gates the multi-press path and the Shoot/LongPass `vf9`/`vf10` branches) has no
    located writer; "press count" is [c]. **`unit+0x24`**, a second float read as the aim angle at
    `0x1440dae30` / `0x1440db977`, is undecoded.
18. **Category 4** of the command table (`0x39`, `0x3c`, `0x3e`) — packer/decoder not followed; and
    fields `+0x08`/`+0x0c` of the 98-entry descriptor table (`+0x0c` looks like a 0–255 priority
    with 255 = none).
19. **The `esi → command-id` map at `0x1440daeb2`** (unit index 0..4 → `0x3a`/`0x38`/`0x3b`/`0x40`/
    `0x3d`) does not line up with the factory order at indices 3 and 4. Not resolved, not emulated.
20. **Whether `BP+0x10`'s stickiness** can leave a player active after his control flag drops
    (§ 7.5).
21. **Confirm the logical→physical button map in-game** (§ 2). One press of RB in a match with a
    logging probe on `0x1486b88d0` would upgrade the whole of § 13 from "[a] for logical 19/21,
    [c] for RT/RB" to [a] end to end. It is the cheapest open item here and it gates every
    button-named claim in §§ 12–13. *(Added by the repair pass.)*
22. **The second acceptance path in `0x144308a90`** — `0x1442c4430`, `UMatchInfo+0x34a0` (tested
    against 5) and `+0x33a6`. It returns human-control **true** while skipping `rank ≤ count`,
    inside match states 2/3 only. Undecoded, and it is a second route into the same allocation that
    Open 2 is about. *(Added by the repair pass.)*
23. **Does any other `match::pad` unit read dt270?** Two sites are proven (§ 12). The exe-constant
    census cannot answer it; the instrument is a scan for `call 0x145348d70` with `edx` recovered by
    dataflow across `0x1440d0000..0x144320000`. Worth doing — dt270 is the only tier-0 route in the
    subsystem. *(Added by the repair pass.)*
24. **The three unfollowed `divss` readers of `0x145b4c548`** (`0x144317db5`, `0x144318006`,
    `0x1443180f0`) — they decode a `127.0`-scaled field into record offsets `+0x00` and `+0x04`
    rather than the power field, and whether a power re-aim must move with them is not proven
    (§ 12). *(Added by the repair pass.)*

---

## 18. Harnesses and reproduction

All read-only over `eFootball.exe.PRISTINE`. Nothing in this chapter wrote to the game or to either
image. The repair pass added `tools/pad/` to this worktree; nothing else under `tools/` was touched.

> **Read this table as a memoir, not a manifest.** *(Corrected 2026-09-20.)* Only the two `tools/`
> rows are files that exist. **The thirteen bare basenames below were session scratch and are
> gone** — a `find` over both worktrees returns nothing for any of them. That means **every `[a]`
> result in this chapter** (the 11-kind matrix, the `start` sweep, the three-edit trigger-run
> matrix, the 16 gesture rows at 60 and 30 fps, the `ScopedWAndC` no-op, the factory dump, the
> quantiser round-trip, the `f` curve, the gauge-fill table) **is currently un-re-derivable from
> this repo: the numbers are the record, the script is not.** Re-deriving any of them means
> re-writing the harness. Note also that `tools/exe_map.py` and `tools/exe_census.py` live in the
> **read-only TOOLREPO worktree**, not beside this chapter.

| harness | exists? | what it produces |
|---|---|---|
| `tools/emu_control_flag.py` | **yes** | the Unicorn proof of § 7.4 — the real `0x144308db0` bytes over a synthetic world |
| `pademu.py` + `kinds.py` | **gone** | the shared ring/node harness, the builder positive control, the 11-kind matrix and the `start` sweep (§ 5.3) |
| `chain.py` | **gone** | PassAndGo's real chains through `0x14430fb40`, the kind-10 substitution test, the table-A/B null-dispatch negative control |
| `gesture.py` | **gone** | all 16 feint rows from all three tables, at 60 and 30 fps (§ 10) |
| `wandc.py` | **gone** | the commit / write-resolve / read-resolve emulation (§ 11) |
| `hook.py` | **gone** | the constraint check and the three-edit matrix (§ 13) |
| `factory.py` / `tu.py` | **gone** | the `0x1440e0c70` factory re-run — all 72 units and their fields (§ 3, § 16) |
| `scan10.py` | **gone** | every reader of `[unit+0x10]` and every node builder's call-site count |
| `emu2.py` | **gone** | the `0x144317840` / `0x144317860` quantiser sweeps and the `0x144317cd0` round trip (§ 8.3) |
| `emu4.py` | **gone** | the `f` curve with all constant pages mapped (+ the `0.8` positive control) and the float32 gauge-fill table (§ 8) |
| `dscan.py` / `fscan.py` | **gone** | instruction-aware `disp32` sweeps. **`fscan.py` prefers the longest back-off so REX prefixes are not dropped** — the first version reported `lea ecx,[rdi+0x7f60]` and nearly hid the sub-object that cracked `Player+0x7f49` |
| `tools/exe_map.py disasm` | **yes, in TOOLREPO** | § 7.7's re-derivation of `0x1440d7010` and `0x1440d70f0` *(this chapter)* |
| `tools/exe_census.py cell --all` | **yes, in TOOLREPO** | every sharer count in § 12 |
| `tools/exe_funcs_chained.py` (`func_chunks`) | **yes, in TOOLREPO** | the closure extents in § 8.4 *(repair pass)* |
| `tools/dt270_liveness.py` + `tools/data/dt270_struct_offsets.json` | **yes, in TOOLREPO** | the runtime-offset → field-name resolution for § 12's dt270 block *(repair pass)* |
| **`tools/pad/emu_node_kind89.py`** + `tools/pad/padimg.py` | **yes — committed by this repair pass** | the kinds 8/9 contrary-frame sweep and the § 5.3 `start`-sweep positive control. The first harness written back into the tree rather than left in scratch; the rest of the `[a]` results still need re-writing |

**Two method notes worth carrying forward.** (1) A backward decode from a bad start address produced
`mov byte [rax+rcx+0x41f6], al` at `0x1442c5369`; the real instruction is
`mov byte [rax+rcx+0x41f6], r8b` at `0x1442c5368` — the REX byte had been dropped. Always decode from
a known boundary. (2) Two saturation/stub artefacts are recorded in § 15 (items 15 and 16) rather
than reported as findings, which is the only honest thing to do with them.
