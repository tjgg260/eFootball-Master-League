# The pad → command channel — probe `pad-to-command-channel` (2026-09-19)

> **FOLDED IN 2026-09-19 — this file is now the working notes, not the chapter.**
> Its results live in [registry-blackboard.md](registry-blackboard.md) § 7 (the channel, the button
> map, the tap law and the hook point), § 5.5 (`UPadInput` and the `ThinkUnit`/node layouts), § 5.6
> (`UCommandOutput` and `match::Command`) and § 12.6 (the correction to realism item 2). Where this
> file and the chapter differ, **the chapter wins** — it was re-verified against PRISTINE and it
> carries the census sharer counts this file lacks. One claim here is superseded outright:
> § 14.13.3 returns `ScopedWAndC` undecoded; it is **Write-And-Commit**, decoded in § 2 of the
> chapter.

**This file is a section for [registry-blackboard.md](registry-blackboard.md), not a standalone
chapter.** It closes that chapter's open item *"the pad→command channel"* and is written to be
folded in as **§14**. It was produced while another probe was editing `registry-blackboard.md`, so
it was kept separate deliberately rather than risk clobbering that edit.

Evidence levels: **a-emulated** / **b-disassembly** / **c-inferred**. All addresses are VAs at base
`0x140000000`, decoded and emulated from `eFootball.exe.PRISTINE`.

> **Patch hygiene.** The installed image differs from PRISTINE in 909 bytes / 90 groups. Exactly one
> of those groups lands in the pad band: **two re-aimed `disp32` constant references at
> `0x144311572` and `0x144311579`**, inside function `0x144310ea0` (an analog/stick helper). Nothing
> decoded below touches that function. Everything here is PRISTINE. [a — byte diff of both images]

---

## 14.1 The shape of the channel, in one paragraph

There is no "pad → command" translation step in the registry at all. `UPadInput` is a **100-frame
ring buffer of raw controller state, per pad slot** — it is the only thing the hardware writes.
Everything above it is a **query language**: 72 `match::pad::ThinkUnit*` objects, one set per
player, each holding a button id and a mode, each asking the ring "did this pattern occur?" through
a small library of temporal predicates. The winners are marshalled into `UCommandOutput`
(80,672 B, `Copy`) once per frame by `match::Command::update`, and `match::player` executors read
`UCommandOutput` back out. `UCommandInfo` is **not** in this path at all — it is the netcode's
channel. [b, with [a] where noted below]

```
hardware pads (8)
   |  0x1453e7130   (UPadInputRef::ScopedWAndC user, per frame)
   |  -> 0x14431a6f0 -> 0x144316620        per-pad assignment descriptor
   |  -> 0x14431a760                       per-pad FRAME BUILDER  (writes one 64-byte frame)
   v
UPadInput   0x25960 = 153,952 B  (Pointer)   24 slots x 0x1908, each = 100 x 64-byte frames
   |
   |  frame accessor 0x14431a5b0(block, k)   k = "k frames ago", 0 = now
   v
match::Command::update   0x1440d4180   (UCommandOutput ScopedWrite)
   |   per player 0..23: pick control source (15-way jump table), bind pad slot,
   |   build ThinkContext (0x1440d7010), run that player's match::CommandPlayer
   |
   |-> match::CommandPlayer::vf3   0x1440de590 -> 0x1440ddd40 -> 0x1440db1c0  (0x51 = 81 slots)
   |        -> per unit 0x1440dcf60 -> ThinkUnit::vf17 (condition) / vf12 (command id)
   v
UCommandOutput   0x13b20 = 80,672 B  (Copy, Write)
   |
   +-> match::player      0x144261bd0 (<- 0x144263f60 <- 0x144261f10, the run-phase machine)
   +-> match::player      0x144140fd0 / 0x144141500 / 0x1442059d0 (set-piece band)
   +-> match::player      0x144285920 (PassGetRoute* band)
   +-> CPU side           0x1442d0050 / 0x1442d12d0
   +-> observer / replay  0x144288360
   +-> MatchOnline        0x145415a90

UCommandInfo 0x1188 = 4,488 B (Pointer, Write) -- writers are all OnlineCommandControllerImpl
```

---

## 14.2 `UPadInput` layout — 153,952 bytes, fully accounted for [b, sizes [a]]

Descriptor `0x143c62a20`, `mov r8d, 0x25960` at `0x143c62a49`, `xor r9d,r9d` (Pointer). The
allocation splits exactly:

| offset | size | contents | proof |
|---|---|---|---|
| `+0x00000` | `24 × 0x1908` = `0x258c0` | **24 pad-slot blocks** | `imul rcx, rcx, 0x1908; add rcx, base` at `0x14431a742`; `imul rdx, rcx, 0x1908` at `0x1440d435b` in `match::Command::update`; 24 × 6408 = 153,792 = `0x258c0` exactly |
| `+0x258c0` | 8 | **per-pad "slot in use" bytes** | `cmp byte [rcx + r9 + 0x258c0], 0` (`0x14431a72c`); `mov byte [rax+rsi+0x258c0], 1` (`0x1453e725e`, `rax < 8`) |
| `+0x258c8` | `8 × 18` = `0x90` | **per-pad 18-byte assignment descriptors** | `lea rdx,[rax+rax*8]; lea rcx,[rcx+rdx*2]; add rcx, 0x258c8` (`0x14431a6f7`–`0x14431a702`) |
| `+0x25958` | 1 | gate flag A (whole-record disable) | `cmp byte [rcx+0x25958], 0; jne ret` (`0x14431a710`) |
| `+0x25959` | 1 | gate flag B | `cmp byte [rcx+0x25959], 0; jne ret` (`0x14431a71c`) |
| `+0x2595a` | 6 | padding to `0x25960` | — |

### The pad-slot block — `0x1908` bytes = a 100-frame ring [b]

```
+0x0000   100 x 64 bytes   frame ring          (6400 = 0x1900)
+0x1900   u32              write cursor, wraps at 100
+0x1904   4 bytes          unaccounted
```

`inc dword [rcx+0x1900]` then `cmp eax, 0x64 ; jl ; mov [rcx+0x1900], 0` at
`0x14431a780`–`0x14431a79c` is the wrap. `shl rbx, 6 ; add rbx, rcx` (`0x14431a7a4`) is the 64-byte
stride, and the four `movups [rbx+0x00..0x30], xmm0` that follow zero exactly 64 bytes.
**100 frames at 60 fps = 1.67 s of input history is retained.** [b]

### The 64-byte frame [b]

| offset | type | meaning |
|---|---|---|
| `+0x00` | u64 | **button bitmask**, bits 0..32 (`bts rax, r15` for `r15 = 0..0x20` at `0x14431a93f`). Bits 4..7 are cleared (`and rax, 0xffffffffffffff0f`, `0x14431aac6`) and rewritten from the left-stick angle, so **the D-pad and the left stick share one 8-way direction field**. **Bit 32 is not a button** — it is a *frame-validity / discontinuity* flag, tested as `test [rsi], 0x100000000` before every edge comparison (`0x14430f9e1`). |
| `+0x08` | f32 | left-stick angle, degrees |
| `+0x0C` | f32 | left-stick magnitude, 0..1 after deadzone |
| `+0x10` | f32 | right-stick angle, degrees |
| `+0x14` | f32 | right-stick magnitude |
| `+0x18` | u8 × 33 | **per-button analog pressure**, `0xff` for a digital button, computed for the two analog triggers (`mov byte [r14+rbx+0x18], 0xff` at `0x14431a8ce`; computed path at `0x14431a923`) |
| `+0x39` | 7 bytes | unaccounted |

**Stick conditioning is three constants** (`0x14431aa26`–`0x14431aa47`): dead zone **0.20**
(`0x1478501c0`), saturation **0.95** (`0x145e8788c`), divisor **0.75** (`0x145a8dd6c`) — i.e.
`m' = clamp((m − 0.20) / 0.75, 0, 1)`, which reaches exactly 1.0 at m = 0.95. The angle is snapped
into the direction bits on a 45° grid with a 22.5° offset (`0x14431abd8`, `0x14431abf0`). [b]

### Frame addressing [b]

```
0x14431a5b0(block, k):
    i = block->cursor - k ;  if (i < 0) i += 100
    return block + i*64
```

`k` counts **frames into the past**; `k = 0` is the current frame. Every predicate below is written
in terms of `k`.

---

## 14.3 The button-id space, and the map to real buttons [a-emulated + b]

`match::pad` uses a **logical** id 0..32 (the bit index in the frame mask). `0x1443164e0` is the
default logical→hardware map; `0x144316130` is the user-remap path and only handles logical
`0x12..0x1f` (`lea eax,[r9-0x12]; cmp eax,0xd; ja default` at `0x14431615d`), i.e. **only the
in-match bank is rebindable**.

Emulating `0x1443164e0` for every input (PRISTINE, no other state):

| logical | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hw | 15 | 14 | 25 | 24 | 10 | 13 | 11 | 12 | 4 | 5 | 6 | 7 | 8 | 9 | 3 | 1 | 0 | 2 |

| logical | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 | 32 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hw | 4 | 8 | 5 | 7 | 3 | 1 | 0 | 2 | 5 | 7 | 3 | 1 | 0 | 2 | 32 |

Three independent facts pin the hardware codes:

1. **hw 5 and hw 8 are the analog triggers.** The frame builder branches `cmp eax,8 / cmp eax,5` and,
   only for those, reads an **axis** (`sete dl; add edx,4` → axis 4 or 5) instead of a digital
   button (`0x14431a8b6`–`0x14431a8e4`). Sticks use axes 0/1 and 2/3 in the same call
   (`0x14431a990`–`0x14431a9b6`). That is XInput axis order: **4 = LT, 5 = RT**, hence
   **hw 5 = LT, hw 8 = RT**. [b]
2. **The D-pad is logical 4..7 (hw 10..13).** `ThinkUnitTacticsNext = 4`, `TacticsBack = 6`,
   `LineControlFront = 5`, `LineControlBack = 7`, `TacticsAttackLevelUp = 4`, `Down = 6` — tactics
   and line control are on the D-pad in this game. [a — factory emulation, §14.4]
3. **The face buttons fall out of the units.** `ShortPass = 24 → hw 0`, `LongPass = 23 → hw 1`,
   `ThroughPass = 22 → hw 3`, `Shoot = 25 → hw 2`, against the game's own control screen
   (A = Low Pass, B = Lofted Pass). So **hw 0 = A, 1 = B, 2 = Y, 3 = X**. [a + c]

That leaves hw 4 and hw 7 as the two digital shoulders, and
**`ThinkUnitCursorChange` has logical 18 → hw 4**, which the game's control screen labels
**LB = Cursor Change**. So **hw 4 = LB and hw 7 = RB**, cross-checked by
`ThinkUnitFriendPress = 27 → hw 7` (RB is second-man press) and `ThinkUnitSliding = 29 → hw 1 = B`.
[b + c]

**The working map:**

| logical | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| button | **LB** | **RT** | **LT** | **RB** | X | B | A | Y | LT | RB | X | B | A | Y |
| bank | attack | attack | attack | attack | attack | attack | attack | attack | defence | defence | defence | defence | defence | defence |

Logical 32 is a pseudo-button: it is the bit-32 discontinuity flag, and `0x1443164e0` maps it to
itself.

---

## 14.4 The 72 `ThinkUnit`s and their bindings [a-emulated]

**One factory builds all of them: `0x1440e0c70`** (referenced by every `ThinkUnit*` vtable — e.g.
`CursorChange` at `0x1440e1152`, `Shoot` at `0x1440e0e94`). Emulating it against a zeroed buffer and
scanning for known vtables recovers **72 units** and their construction-time fields.

Per-unit fields written by the factory:

| offset | meaning | evidence |
|---|---|---|
| `+0x00` | vtable | [a] |
| `+0x08` | **logical button id** (33 = *none*) | [a]; consumed by `vf17` as `mov edx,[rcx+8]` → `0x14430f9b0` |
| `+0x0c` | input class: **0/1 = stick unit, 2 = button unit** | [a]; matches the RTTI bases exactly — every `+0x0c ∈ {0,1}` unit derives from `ThinkUnitStickKind`, every `+0x0c = 2` unit from `ThinkUnitPadId` |
| `+0x10` | a mode selector, values 0..4 | [a] for the values; **semantics NOT proven** — the only consumer found is `cmp dword [rsi+0x10], 3` at `0x1440dcff8` |
| `+0x14` | command variant; `== 2` enables the multi-press path in `vf17` | [a] value, [b] use at `0x1440d800a` |
| `+0x18` | 1 (enabled) | [a] |

The full table (button shown as the mapped name):

| unit | btn | name | +0c | +10 | +14 |
|---|---|---|---|---|---|
| ShortPass | 24 | A | 2 | 4 | 1 |
| LongPass | 23 | B | 2 | 4 | 2 |
| ThroughPass | 22 | X | 2 | 4 | 1 |
| Shoot | 25 | Y | 2 | 4 | 2 |
| Clear | 25 | Y | 2 | 4 | 4 |
| Press | 33 | *none* | 2 | 1 | 0 |
| PressGK | 28 | X (def) | 2 | 1 | 0 |
| Delay | 33 | *none* | 2 | 1 | 0 |
| Tackle | 33 | *none* | 2 | 2 | 0 |
| Shoulder | 31 | Y (def) | 2 | 2 | 0 |
| Sliding | 29 | B (def) | 2 | 2 | 0 |
| FriendPress | 27 | RB (def) | 2 | 1 | 0 |
| Dribble | 33 | *none* | 0 | 0 | 0 |
| FreeMove | 33 | *none* | 0 | 0 | 0 |
| **CursorChange** | **18** | **LB** | **2** | **2** | **0** |
| CursorChangeManual | 33 | *none* | 1 | 2 | 1 |
| CursorChangeKeeper | 13 | menu bank | 2 | 2 | 0 |
| TeammateSwitch | 33 | *none* | 1 | 2 | 1 |
| TacticsNext / TacticsBack | 4 / 6 | D-pad | 2 | 1 | 0 |
| LineControlFront / Back | 5 / 7 | D-pad | 2 | 1 | 0 |
| KickFeint | 24 | A | 2 | 4 | 4 |
| KickCancel / SuperCancel | 19 | **RT** | 2 | 1 | 0 |
| Feint | 33 | *none* | 1 | 2 | 0 |
| SetplayGuide / PenaltykickGuide | 33 | *none* | 0 | 0 | 0 |
| DemoSkip / OutofPlaySkip | 2 / 1 | system | 2 | 2 | 0 |
| FreekickWallJump / NotJump / Press | 29 / 30 / 31 | B / A / Y (def) | 2 | 2 / 1 / 2 | 0 |
| FreekickKeeperMove | 28 | X (def) | 2 | 1 | 0 |
| FreekickTypeChange | 4 | D-pad | 2 | 2 | 0 |
| Kickoff | 24 | A | 2 | 4 | 0 |
| Penaltykick | 25 | Y | 2 | 4 | 1 |
| KeeperAutoMove | 26 | LT (def) | 2 | 2 | 0 |
| KeeperPress | 28 | X (def) | 2 | 2 | 0 |
| KeeperTrapMove / TrapLift / TrapStop | 13 | menu bank | 2 | 0 | 0 |
| KeeperTackle | 31 | Y (def) | 2 | 0 | 0 |
| KeeperBlock | 29 | B (def) | 2 | 0 | 0 |
| KeeperAutoPuntkick | 23 | B | 2 | 4 | 4 |
| KeeperPenaltykickMove / Action / Layer | 33 | *none* | 0 / 0 / 1 | 0 / 3 / 3 | 0 |
| MoveStopGoal / KeeperPickupBall / KeeperDropBall | 19 | **RT** | 2 | 0 | 0 |
| **TrapThrough** | **18** | **LB** | 2 | 0 | 0 |
| PassRequest | 24 | A | 2 | 2 | 0 |
| CameraTarget / KickerSelect | 0 | system | 2 | 2 | 0 |
| Pause / Chat | 1 | system | 2 | 2 | 0 |
| AutoRestart / BlockTestAutoRestart | 24 / 25 | A / Y | 2 | 4 | 4 |
| ThrowinBodyAngleRotation | 33 | *none* | 0 | 0 | 0 |
| **GoalkickPassSupport** | **18** | **LB** | 2 | 0 | 0 |
| **ShortCorner** | **18** | **LB** | 2 | 2 | 0 |
| TacticsAttackLevelUp / Down | 4 / 6 | D-pad | 2 | 1 | 0 |
| CornerKickTactics / DefenceType / FreeKickTactics | 1 | system | 2 | 2 | 0 |
| InteractiveGoalDemo | 33 | *none* | 1 | 2 | 0 |
| KickOffChange | 4 | D-pad | 2 | 2 | 0 |
| **FreeKickPositionChange** | **18** | **LB** | 2 | 2 | 0 |
| QucikMemberChange | 2 | system | 2 | 2 | 0 |
| **PassAndGo** | **33** | ***none*** | 2 | 2 | 0 |

Two things to read off this table immediately:

* **`ThinkUnitShoulder` is not a shoulder button.** It is the shoulder *barge*: its `vf12`
  (`0x1440e8fa0`) is a proximity test — `0x1440e90a0` with `xmm1 = 3.0`, squared and compared
  against a distance (`0x1440e9119`). Its button is 31 = Y in the defence bank. Anyone searching for
  "the shoulder button unit" will find this and be wrong. [b]
* **`PassAndGo` has no button id at all** (33). It does not use the base test; it overrides `vf17`
  and drives the pattern engine directly (§14.7).

---

## 14.5 The default trigger: `ThinkUnitBase::vf17` is a **rising edge** [b]

`0x1440d8000`, 0x6f bytes, is the condition every button unit inherits:

```
if (this->+0x14 == 2 && this->+0x29 > 1)
      if (0x144310490(ctx->pad, this->buttonId, 2, 6, 0,0,0)) return true;   // multi-press
return 0x14430f9b0(ctx->pad, this->buttonId, 0);
```

and `0x14430f9b0` is, exactly:

```
bool Pressed(block, btn, k):
    if (k >= 0x63) return false
    prev = frame(block, k+1)
    if (prev[0] & (1<<32)) return false          // discontinuity guard
    cur  = frame(block, k)
    return (cur[0] & (~prev[0]) & (1<<btn)) != 0
```

It is a one-frame **rising edge at `k`**, and `vf17` always passes `k = 0`. There is no hold, no
repeat and no dwell in the default path. `0x144310490` is the multi-press variant: it finds one
press edge and then scans backwards for another within a bounded number of misses — reached only by
`LongPass` and `Shoot` (`+0x14 == 2`).

**Consequence, and this is the answer to the feature's open risk (c): `ThinkUnitCursorChange`
overrides *only* vtable slot 12** (`0x1440e20b0`, a one-instruction `mov eax, 0x37 ; ret` that
returns its command id). Its trigger is therefore the inherited `vf17`, i.e. **Cursor Change fires
on the press edge of LB, on the very first frame LB goes down.** [b, end to end]

---

## 14.6 The pattern engine — where tap/hold discrimination actually lives [b + a]

A second, richer mechanism exists alongside `vf17`. It is used by only **7 functions image-wide**
(`0x1440d8b20`, `ThinkUnitPassAndGo::vf17` `0x1440e5280`, `0x1440e5d50`, `0x1440e5e90`,
`0x1440e8520`, `ThinkUnitTrapThrough::vf8` `0x1440e88f0`, `ThinkUnitFriendPress::vf8`
`0x1440e9240`), so it is the exception, not the rule.

### The node — 40 bytes [b]

| offset | type | meaning |
|---|---|---|
| `+0x00` | u32 | **button mask** (`1 << buttonId`; the master table passes a multi-bit mask directly) |
| `+0x04` | u32 | **kind** (the predicate, 0..10) |
| `+0x08` | u32 | parameter A |
| `+0x0c` | u32 | parameter B |
| `+0x10` | u8 | stick-constraint present |
| `+0x14`, `+0x18` | f32 | stick angle range (e.g. −180..180, −90..90) |
| `+0x1c` | f32 | — |
| `+0x20`, `+0x24` | f32 | magnitude thresholds; **`−1.0` = no stick constraint** |

Simple builders (no stick): `0x14430edb0` → kind 1, `0x14430edf0` → kind 8, `0x14430ee30` → kind 2,
`0x14430ee80` → kind 9, `0x14430eec0` → kind 4. Stick-capable builders live at `0x14430ef00`,
`0x14430ef80`, `0x14430f000`, `0x14430f080`, `0x14430f100`, `0x14430f180`, `0x14430f1d0`,
`0x14430f250`, `0x14430f2d0`, `0x14430f300`, `0x14430f330`.

### The evaluator — `0x14430fb40` [b]

```
bool Match(ctx, node[], count, xmm3, start /*[rsp+0x20]*/, flag, window /*[rsp+0x30]*/, out)
```

It walks the chain **backwards** — `rbx = node + (count−1)*0x28`, then `sub rbx, 0x28` — dispatching
each node through one of three tables selected by the node's stick fields:

| table | selected when | VA |
|---|---|---|
| C | `+0x10 == 0` and `+0x20 < 0` (no stick) | `0x148081710` |
| B | `+0x10 == 0` and `+0x20 >= 0` | `0x148081770` |
| A | `+0x10 != 0` | `0x1480817d0` |

Each handler returns a **frame index** or `−1`; that index becomes the search bound for the
*previous* node. So **node[0] is the earliest event and node[count−1] the most recent**, and the
whole chain must fit inside `window` frames (always `0x64 = 100`, the full ring, at every call site
found). Table C's handlers: kind 0 `0x14430d770`, 1 `0x14430d830`, 2 `0x14430d8e0`, 3 `0x14430d980`,
4 `0x14430da30`, 5 `0x14430dab0`, 6 `0x14430dad0`, 7 `0x14430daf0`, 8 `0x14430db10`, 9 `0x14430dbd0`,
10 `0x14430d760`.

### What the kinds mean — emulated against a synthetic ring [a]

Harness: a fake `0x1908` block with cursor = 50, one button (21) driven, `window = 100`, one node
per run, nodes built by the game's own builders, evaluator called as the game calls it.

| scenario → | never down | always down | down f3..f2 (2-frame tap) | down f8..f1 (8f, released) | down f0..f3 (still down) | down f40..f1 (40f hold, released) |
|---|---|---|---|---|---|---|
| **kind 8** | MATCH | . | MATCH | MATCH | . | MATCH |
| **kind 9** | . | MATCH | . | MATCH | MATCH | MATCH |
| **kind 1** (A=0) | . | . | . | . | . | . |
| **kind 2** (A=5) | . | MATCH | . | MATCH | . | MATCH |
| **kind 4** (B=5) | . | . | **MATCH** | . | . | . |

So, with the parameters the game actually uses:

* **kind 8 = "not held"**, **kind 9 = "held"** (level tests, evaluated at the anchor frame) — the
  pair is the reverse of what the builder ordering suggests, which is exactly why it is emulated
  here rather than asserted from the disassembly.
* **kind 2 = held for at least A frames.**
* **kind 4 = TAP**, and it is the *only* predicate that distinguishes a tap from a hold.
* kind 1 (release edge) and kind 3 (press edge) are the primitives kind 4 is built from
  (`0x14430da30` calls `0x14430d980` then `0x14430d830` and range-checks the gap) but did not fire
  standalone with `B = 0`, so their standalone parameterisation is **not proven**.

### The tap law, exactly [a]

Sweeping press duration `d` against the node's `B`:

```
       B: 0  1  2  3  4  5  6  7  8  9 10 11 12
 d = 1     .  .  Y  Y  Y  Y  Y  Y  Y  Y  Y  Y  Y
 d = 2     .  .  .  Y  Y  Y  Y  Y  Y  Y  Y  Y  Y
 d = 3     .  .  .  .  Y  Y  Y  Y  Y  Y  Y  Y  Y
 d = 4     .  .  .  .  .  Y  Y  Y  Y  Y  Y  Y  Y
 ...
 d = 11    .  .  .  .  .  .  .  .  .  .  .  .  Y
 d = 12    .  .  .  .  .  .  .  .  .  .  .  .  .
```

**CORRECTED 2026-09-19** (see `registry-blackboard.md` § 7.2 / § 12.7 R5). The predicate is **not** a
duration test. The kind-4 handler `0x14430da30` finds the **release** edge (`0x14430d980`), then the
**press** edge before it (`0x14430d830`), and tests

```
0x14430da78  mov ecx,eax ; sub ecx,ebx ; dec ecx ; cmp esi,ecx ; jg MATCH
             -> match iff  B > pressEdgeIndex - bound - 1
```

i.e. **press duration *plus* release age ≤ B** — the window closes on the press edge, not on the
release. The sweep above is still the right picture of the *event* behaviour (with `B = 5, d = 2` it
matches only while the release is 1–3 frames old), but "matches iff `d ≤ B − 1`" is wrong as a law:
a 1-frame press matches for four frames, a 4-frame press for one. Also: `B` is written as a **dword**
by the builders but **read as a byte** by both edge searches (`movzx …, byte ptr [rdx+0xc]` at
`0x14430d9a3` / `0x14430d853`), so any value ≥ 256 wraps mod 256, and the chain window is fixed at
`0x64` = 100 frames, so `B > 100` is inert.

**`B` is computed at runtime, not stored.** Every call site builds it as
`B = (int)(0.08f * FPS + 0.5f)` — `call 0x14533ea80` (returns the frame rate; the same call is used
one-second-at-a-time at `0x1440e53e3`), `mulss 0.08` (`0x145e87854`), `addss 0.5`, `cvttss2si`
(e.g. `0x1440e54b0`–`0x1440e54c5`). **At 60 fps, `B = 5` — meaning the press edge must be no more
than 5 frames back**, not "a press of at most 4 frames ≈ 67 ms" (corrected above).
[b for the predicate, a for the emulated rows, b for the arithmetic]

---

## 14.7 `ThinkUnitPassAndGo` — what it actually tests, and it is not L1+A [b + a]

`0x1440e5280` (`vf17`) evaluates **two chains, OR'd**, both lazily built behind TLS static guards:

| chain | nodes | built at | guard |
|---|---|---|---|
| A (`0x1486b88d0`) | `[0] kind 8, btn 0x13` ; `[1] kind 4, btn 0x15, B = round(0.08·fps)` | `0x1440e5508`–`0x1440e553f` | `0x1486b8920` |
| B (`0x1486b8930`) | `[0] kind 8, btn 0x13` ; `[1] kind 1, btn 0x15, B = 0` ; `[2] kind 2, btn 0x15, A = round(0.08·fps)` | `0x1440e548c`–`0x1440e54d8` | `0x1486b89a8` |

Both are called with `window = 0x64`, `start = 0`, `xmm3 = 0`, `out = null`
(`0x1440e52db`–`0x1440e5305` and `0x1440e5318`–`0x1440e5340`).

Buttons `0x13 = 19 = `**RT** and `0x15 = 21 = `**RB**. Reading the chains newest-first, and applying
the emulated kind semantics: **RB is tapped (chain A) or held past the threshold (chain B), while RT
is *not* held.** On success `vf17` stores a player index to `[behaviour+0x19]` and returns 1
(`0x1440e546b`).

> **This contradicts `docs/realism-todo.md` item 2 and the probe brief**, which state that
> `ThinkUnitPassAndGo` slot 17 produces "the L1+A 'go' and R1+A 'overlap' behaviours". Neither chain
> references A (logical 24) or LB (logical 18). Both reference RT and RB only. `vf17` is also not a
> behaviour *producer* — it is a boolean condition plus a target-player selection; the command id
> comes from `vf12` (`0x1440e5270`). [b for the node contents, a for the button map]

---

## 14.8 `ThinkUnitFriendPress` — the one place a shoulder is genuinely mode-switched [b]

`vf8` at `0x1440e9240` gates on RT first:

```
if (0x144310750(pad, 19 /*RT*/, 0))  -> pattern 0x1486b89b0 (3 nodes)
else                                 -> pattern 0x1486b8a90 (3 nodes)  or  0x1486b8a30 (2 nodes)
```

i.e. **second-man press behaves differently while sprint is held**, and all three patterns use the
same 100-frame window. This is the template the trigger-run feature should copy: a shoulder button
with two meanings separated by another button's level, not by a timer.

---

## 14.9 The "special controls" gesture table [a-emulated]

`0x1440d8b20` builds a global table: count at **`0x1486adff0`**, rows at **`0x1486adff4`**, stride
**`0x1b0` = 432 B**. Row layout: `+0x00` command id, `+0x04` flag, `+0x08` node count, `+0x0c` nodes
(0x28 each), `+0x19c` flags, `+0x1a0` two floats, `+0x1a8` masked `& 0x1ff`.

Emulated with the frame rate stubbed to 60, the builder produces **5 rows**:

| row | cmd | nodes (newest last) |
|---|---|---|
| 0 | `0x17` | `RB kind 9 (held)` ; `mask 0x1 kind 1 + stick ±90°, mag 0.8` |
| 1 | `0x0f` | `RB kind 8` ; `mask 0x13 kind 1, B=12` ; `mask 0x13 kind 1, B=12` ; `stick kind 6, ±180°, mag 0.2` |
| 2 | `0x0f` | `RB kind 8` ; `mask 0x13 kind 4, B=12` ; `stick kind 6, ±180°, mag 0.2` |
| 3 | `0x1b` | `bit13 kind 1, B=24` ; `stick kind 9 ±180° mag 0.2` ; `bit13 kind 1` |
| 4 | `0x1b` | `bit13 kind 1, B=24` ; `bit13 kind 1` |

This confirms the game's own control screen label **"RB = Special Controls"**: bit 21 (RB) is the
modifier on rows 0–2. It also shows a **12-frame** gesture window in use alongside the 5-frame tap.
The builder has 42 static call sites but only 14 executed on this path, so **more rows exist behind
branches this emulation did not take** — treat 5 as a lower bound. [a with an explicit caveat]

---

## 14.10 Who writes what, in frame order [b]

**`UPadInput` writer.** `0x1453e7130` is the only non-ctor/dtor user of `UPadInputRef::ScopedWAndC`
(vtable `0x147612470`, referenced at `0x1453e6159` (ctor), `0x1453e67c7` (dtor), `0x1453e71ce`
(here)). It:

1. polls 8 hardware pads (`0x143b3e290` / `0x143b3e660`) into 8 presence bytes;
2. copies **24 bytes** of slot→pad assignment from `src+0x7f8`;
3. opens the WAndC scope on `UPadInput`, clears `[record+0x258c0] = 0`;
4. for each of **24 slots** whose assigned pad index is `< 8`, sets `[record+0x258c0+idx] = 1`, reads
   the raw device (`0x1454002b0`) and calls `0x14431a6f0(record, idx, src)` → `0x144316620`, which is
   the per-pad descriptor write; the frame builder proper is `0x14431a760`.

Its only caller is `0x1453e76f0`, itself called from four sites in the **`MatchOnline` band**
(`0x14540b780`, `0x14540ca60`, `0x14540d8f0`, `0x1454132f0`). The `ScopedWrite` (non-WAndC) path on
`UPadInput` has exactly one real user, `match::PreRetryListener` method 1 (`0x143c638f0`).

**`UCommandOutput` writer.** `match::Command::update` = **`0x1440d4180`** (only caller `0x143c622d6`,
inside `0x143c62220`; a second `.impdata` reference is a CFG entry, not a call). It takes the
`UCommandOutput::ScopedWrite` at `0x1440d491e`. Per frame it:

* resets 24 × `0xb4`-byte per-player command slots at `this+0x40` (`0x1443081e0(slot, 0xb)`);
* for each of 24 entries (stride `0xd0`) reads a **control-source code** from
  `this+0x2b4dc + idx*32` and dispatches through a **15-entry jump table** at `0x140d4a08 + base`;
* in the pad branch, binds `padBlock = UPadInput + padIdx*0x1908` (`0x1440d435b`), builds a
  ThinkContext with `0x1440d7010` and calls the player's `match::CommandPlayer` virtual `+0x18`.

A second `UCommandOutput::ScopedWrite` user is `0x14540b040`, in the **`MatchOnline`** band —
consistent with remote/replay input being injected as finished commands.

**`UCommandInfo` is the netcode's record, not the pad's.** All three `ScopedWrite` users —
`0x1456e42c0`, `0x1456e4640`, `0x1456e4ee0` — sit inside **`OnlineCommandControllerImpl`** (nearest
vtable methods `0x1456e40e0[10]`, `0x1456e4110[16]`), and `CommandInfoRef` is also built by
`match::Online[57]` (`0x1456d5090`). **Nothing in the local pad path touches it.** [b]

**The ThinkContext** (`0x1440d7010`, 0x34 bytes):

```
+0x00  pad-system pointer (match::Command + 0x2b900)
+0x08  &padBlock            <-- every predicate dereferences this
+0x10  per-player command entry (stride 0xd0)
+0x18  per-player control-source record (this+0x2b4dc + idx*32)
+0x20  player index
+0x24  pad index, or 0xff
+0x28  f32   +0x2c u32   +0x30..0x32  three bytes
```

**`match::CommandPlayer`** (ctor `0x1440dd750`, vtable `0x146ba0620`) is the per-player brain:
`+0x1a38`/`+0x1a3c` = `0x51` (81 unit slots), `+0x1ab0` `CommandOutputRef`, `+0x1b08`
`Screen2dInfoRef`, `+0x1b60` `CommandInfoRef`, `+0x1bb8` `StepupTutorialRef`. Its `vf3`
(`0x1440de590`) runs `0x1440ddd40` → `0x1440db1c0`, which iterates all `0x51` slots
(`0x1440e2200(this, idx)` fetches a unit, `[unit+0x34]` is a priority) and evaluates each through
`0x1440dcf60`.

`match::Command` itself (ctor `0x1440d2970`, vtable `0x146b9e7d8`) holds `CameraInfoRef` at
`+0x2b8a8`, the pad sub-system at `+0x2b900`, `MatchInfoRef` at `+0x2f568`, **`PadInputRef` at
`+0x2f5c0`**, `CursorInfoRef` at `+0x2f618`, `Screen2dInfoRef` at `+0x2f670` and
**`CommandOutputRef` at `+0x2f6c8`**.

---

## 14.11 Where `UCommandOutput` is read [b]

`UCommandOutput::ScopedRead` (vtable `0x146bf9e28`) has two direct users — `0x144288360`
(observer/replay band) and `0x145415a90` (`MatchOnline` band) — plus one call of the scope ctor
`0x144287790` from **`0x144261bd0`**, which is the interesting one:

```
0x144261f10  (player-executors.md: "the run-phase state machine", still open there)
   -> 0x144263f60
      -> 0x144261bd0     *** NO registry scope at all -- see correction below ***
```

**CORRECTED 2026-09-19 — this hand-off does not exist as described** (see `registry-blackboard.md`
§ 5.6 / § 10.3 / § 12.7 R3). `0x144261bd0` opens **no** `UCommandOutput::ScopedRead`: a full
call-target sweep of its three chunks yields 16 targets, none of them `0x145340c80`, `0x1453415d0`,
`0x143c4db70`, `0x145340a10` or `0x144287790` — and `0x144287790` is a `Scoped*` **destructor**
(vtable store to `[rcx]`, release via `0x140c83910`, clears the read token `[rbx+0x48]`), not a
constructor. And `+0x25bcc` / `+0x25a9c` are **not `UCommandOutput` fields**: 154,572 and 154,268 lie
far outside its 0x13b20 = 80,672-byte allocation, and both are read off `0x140efd260(x)` =
`[x+0x48]` = **`UAnalyzeInfo`** (`0x144261c54` / `0x144261ce6`), 16 bytes from the known ball X at
`+0x25bbc`. The frame-age gate is real but is an age on the function's **own** timestamp:
`|matchSettings+0x3318 − [this+0x68]|` (absolute value via `0x140a22910`) against
`int(FPS·0.4 + 0.5)` = 24 frames at 60 fps, at `0x144261bfb`–`0x144261c38` — **nothing from
`UCommandOutput` enters it**. *The pad → executor hand-off is therefore NOT established, and
`player-executors.md`'s run-phase item stays open.* [b]

`CommandOutputRef` is additionally constructed in the `match::player` set-piece band (`0x1442059d0`,
nearest vtables `ActionPenaltyKick` / `ActionCornerKick`; called from `0x144141500`, reached from
`0x144140fd0` — the same function that builds a `PadInputRef`), in the pass-reception band
(`0x144285920`, nearest vtable `PassGetRouteBallFollow`), on the CPU side (`0x1442d0050`,
`0x1442d12d0`, nearest `CpuDynamicObject`), in `match::Highlight` (`0x1456052a0`) and in
`MatchControl` (`0x143c53cc0`). **I did not emulate any of those, so "reads `UCommandOutput`" is [b]
by construction site, not a claim about which field.**

---

## 14.12 The hook point for trigger-runs, and how invasive it is

**Nothing below was written, applied or tested. This is a description of sites, not a patch.**

The cleanest hook is **not code at all**. `ThinkUnitPassAndGo`'s two chains live at `0x1486b88d0`
(2 × 40 B) and `0x1486b8930` (3 × 40 B). Those addresses are in the PE's `.text` section beyond its
raw size — **uninitialised data, zero at load, filled once by the TLS-guarded static initialiser
inside `0x1440e5280`**. After the first evaluation they are plain writable memory. Changing
`node[0].mask` from `1<<19` (RT) to something else, or `node[1].kind` from 4 (tap) to 9 (held),
retargets the trigger-run gesture **with no instruction patched, no cave, and no Denuvo interaction
beyond the existing runtime-write path** (`tools/live_patch.py`).

What must be preserved if anyone does this:

* the guards `0x1486b8920` / `0x1486b89a8` must already be initialised, i.e. write **after** the
  first time `vf17` runs, or the initialiser will overwrite you;
* `node.+0x20 = node.+0x24 = −1.0` and `node.+0x10 = 0` keep the node on dispatch table C; setting
  `+0x10` non-zero moves it to table A and changes which handler runs;
* `count` is the caller's literal (`mov r8d, 2` at `0x1440e52f6` / `3` at `0x1440e5331`), so a chain
  can only be shortened by making the removed node vacuously true (kind 10, `0x14430d760`), not by
  editing data;
* `vf17` returns a *target player index* in `[behaviour+0x19]` from `[ctx+0x1c]`; that path
  (`0x1440e5463`) must still be reached.

A second, coarser site: the **ThinkUnit factory `0x1440e0c70`** writes each unit's button id at
`unit+0x08` and mode at `unit+0x10`. Rewriting those in a constructed `match::CommandPlayer` rebinds
any unit to any button with no code patch either — but it acts through `vf17`, which is a **press
edge only**, so it cannot express "tap".

**Honest assessment of the feature.** The brief's premise is wrong in a way that matters:

* **LB is not free.** `ThinkUnitCursorChange` is bound to LB and fires on the **press edge**
  (§14.5). Any LB tap fires a cursor change on frame 0, before a tap could possibly be
  distinguished. A "tap LB = trigger run" binding **collides unconditionally**. The ways out are to
  suppress `CursorChange` (it overrides only `vf12`, so it cannot be neutered without touching the
  shared `vf17`), or to pick a different button.
* **RB *is* free on the ball.** No `ThinkUnit` in the attack bank uses logical 21; the only consumers
  are `PassAndGo`'s pattern and the special-controls gesture table, both of which are *chains* that
  also require a stick or RT state. An RB-alone tap is unclaimed.
* **The tap machinery already exists and is exact** — kind 4, 0.08 s, computed from the live frame
  rate (§14.6) — so nothing new has to be written to *detect* a tap.

---

## 14.13 Negatives and honest not-proven

1. **`UCommandInfo` is not part of the local pad→command path.** Every `ScopedWrite` user is in
   `OnlineCommandControllerImpl`. The skeleton's picture of `VPadInput → VCommandInfo →
   UCommandOutput` as one pipeline is **wrong**: `UPadInput → UCommandOutput` is the local path and
   `UCommandInfo` is a parallel network ingress. [b]
2. **The `+0x10` per-unit mode is not decoded.** Its five values are recovered by emulation, and
   `cmp dword [rsi+0x10], 3` at `0x1440dcff8` proves it is compared against literals, but no switch
   naming 0/1/2/3/4 was found. Do **not** read the table in §14.4 as "2 = press edge" — the press
   edge comes from `vf17`, unconditionally, for every button unit.
3. **`ScopedWAndC` is still undecoded** — this probe added nothing. `UPadInput`'s WAndC scope
   (`0x1453e6150` ctor, `0x1453e67b0` dtor) is used by the one writer and behaves, from the outside,
   exactly like `ScopedWrite` plus a commit at scope exit (`0x145340a10` at `0x1453e72a9`). That is
   suggestive, not proof.
4. **`match::Player + 0x7f49` — the writer is still not located, and the pad channel does not explain
   it.** There is exactly **one** `disp32` site for `+0x7f49` in all of `.xcode`, and it is a
   **read**: `movzx eax, byte [r14+0x7f49] ; mov byte [rsi+0x41], al` at
   `0x1441574bc` / `0x1441574c4`, inside the player→AI-entity marshaller `0x144157270` (16 chained
   chunks, `0x144157270`–`0x144159228`), which also copies `+0x766c → entity+0x42` and
   `+0xe354`/`+0xe350 → entity+0x1d0`/`+0x1d4`. A sweep of every displacement in `0x7f00..0x7f60`
   finds no writer on any base. So `ball-carrier-brain.md`'s `byte[entity+0x41]` is confirmed to be a
   **copy of `match::Player+0x7f49`** [b], but the field itself must be written through a sub-object
   pointer with a small displacement, and **no evidence connects it to the pad**. Opens 8 and 14 stay
   open.
5. **"Is the human's carrier driven through this channel rather than the ThinkUnit machine?" is a
   malformed question, and that is worth recording.** There are **two unrelated `ThinkUnit`
   families**: `match::pad::ThinkUnit*` (72 classes, this chapter) and `match::ai::bp::ThinkUnit*`
   (the carrier brain in `ball-carrier-brain.md`). The pad channel *is* a ThinkUnit machine. What is
   shown here is that `match::Command::update` picks a per-player **control source** through a 15-way
   jump table (`0x1440d4342`–`0x1440d4354`) and only one branch binds a pad block; what is not shown,
   because the other 14 branches were not traced, is whether a pad-driven carrier also runs
   `match::ai::bp`. **Not proven either way.**
6. **The gesture table row count is a lower bound.** `0x1440d8b20` has 42 static builder call sites;
   the emulated path executed 14 and produced 5 rows. Branches were not enumerated.
7. **kind 1, 3, 5, 6, 7, 10 standalone semantics are not proven.** Only 2, 4, 8, 9 were exercised
   with the parameters the game supplies.
8. **Frame-order within the tick is partly inferred.** The writer, the consumer and the call chains
   are all [b], but no scheduler was found listing `UPadInput` update before
   `match::Command::update` in the same tick; that ordering is [c].

---

## 14.14 Corrections this probe forces

* **To `docs/realism-todo.md` item 2 and the probe brief:** `ThinkUnitPassAndGo::vf17` is gated on
  **RT + RB**, not on L1+A / R1+A. Its `vf17` is a condition, not a behaviour producer. (§14.7)
* **To `docs/realism-todo.md` item 2's stated premise "both shoulder-alone functions are HOLDS, so a
  tap is free":** LB-alone is `ThinkUnitCursorChange` and it is a **press edge**, not a hold. A tap
  of LB is *not* free. RB-alone is free on the ball. (§14.5, §14.4)
* **To the skeleton's record table (already corrected independently by the tactics probe — this is a
  second, independent confirmation):** `UPadInput` = `0x25960` (153,952 B), `UCommandInfo` = `0x1188`
  (4,488 B), both `Pointer`; `UFieldInfo` = `0x50` (80 B) and the 1,435,944-byte record is
  `URecordInfo`; `URandomInfo` = `0x1c` (28 B); `UCameraSettings` = `0x10`; `UDemoControl` = `0x30`.
  Root cause of the original error: four descriptors build `r8d` as `lea r8d,[r9+imm]` after setting
  `r9d`, which a `mov r8d, imm` scan silently skips and a carry-forward scan mis-attributes.
  Descriptors affected: `0x143c4e070`, `0x143c6a860`, `0x143c91da0`, `0x143c91e40`. [b]

---

## 14.15 Reproduction

Scripts used, all read-only over PRISTINE, in the probe scratchpad:

| script | what it proves |
|---|---|
| `desc2.py` | every registry descriptor's `r8d`, handling `lea r8d,[r9+imm]` — the size corrections |
| `tu.py` | emulates `0x1440e0c70`, dumps all 72 ThinkUnits and their fields |
| the `0x1443164e0` sweep | logical → hardware button map, ids 0..33 |
| `tap2.py` | node-kind semantics matrix (kinds 1, 2, 4, 8, 9) |
| `tap3.py` | the kind-4 sweep and the release-recency window (read as `d ≤ B−1`; the real predicate is `B > pressIdx − bound − 1` — see the correction in § 14.6) |
| `emu.py` | emulates `0x1440d8b20`, dumps the special-controls gesture table |
| `xref.py` | RIP-relative reference scanner over PRISTINE's executable sections |

No script in this probe writes to the game, the installed image or `tools/`.
