# Input → power, and the rest of `match::pad` — probe `input-to-power-and-remaining-classes` (2026-09-20)

Companion to [registry-pad-command-channel.md](registry-pad-command-channel.md), which is **GIVEN AS
FACT** here and is not re-derived. This file closes items from that chapter's §14.13 and adds the
surfaces it never touched: **how a held button becomes kick power**, **whether the human is given an
accuracy edge over the CPU**, **the classes outside the 72 ThinkUnits**, **cursor switching**, and
**what is honestly tunable**.

Evidence levels **a-emulated / b-disassembly / c-inferred**. All addresses are VAs at base
`0x140000000`, read from `eFootball.exe.PRISTINE`. Nothing was written to the game.

---

## 1. The chain, in one paragraph

Holding the shoot button does **not** measure held frames anywhere. Each `ThinkUnit` owns a float
**gauge at `unit+0x20`** which `0x1440d8070` advances by `1/(FPS × T)` on every frame the unit's
press machine is in state 2, `T` being a per-command-id fill time from a 16-entry table. When the
button is released — **or the moment the gauge reaches 1.0, whichever comes first** — the unit goes
to state 3 and emits its command id. `0x1440db720` then packs `clamp(gauge,0,1)` together with the
left-stick angle (rotated into camera space) into a 20-byte block at `CommandPlayer+0x1a4c`, which
`0x144318700` bit-packs into the 16-byte `UCommandOutput` record — **power as 7 bits,
`floor(g×127)`** — and `0x144317cd0` unpacks it for the `match::player` executors. Power is
therefore **linear in held frames, hard-clamped at 1.0, frame-rate-independent in time but not in
resolution**.

```
pad ring (64-B frames)                                          [given, §14.2]
   |  0x144310750 level / 0x14430f9b0 edge / 0x14430f360 angle / 0x14430f750 mag / 0x14430f700 trigger
   v
ThinkUnitBase::vf8  0x1440d7bd0    press machine, unit+0x1c = 0..3
   |  state 2 -> vf12 -> vf13 -> 0x1440d8070    gauge += 1/(FPS*T),  gauge = min(gauge, 1.0)
   |  state 3 -> vf14 -> command id
   v
0x1440db720   build {aimAngle, stickMag, POWER=clamp(gauge,0,1), guideAngle, guideMag, flags}
   v
0x1440dcd20   store into CommandPlayer+0x1a4c .. +0x1a60   (20 B + flag byte)
   v
0x1440dab90 -> 0x144318700   bit-pack the 16-byte UCommandOutput record
   v
0x144317cd0   unpack  ->  match::player::ActionShortPass::vf2, ActionKickFeint/Kickoff::vf4,
                          ActionKeeperPuntKick::vf4, ActionKeeperThrow::vf4, 0x14414b950,
                          0x144162070, 0x14415f660, 0x1442b6760, 0x14422d570
```

---

## 2. The pad predicate library, completed [b]

§14.5–14.6 gave the edge and the pattern engine. The rest of the leaf library, all taking
`(unitCtx+0x08 -> &padBlock, index, k)` and all bounded by `k < 0x64`:

| VA | call sites | what it returns |
|---|---|---|
| `0x14430f9b0` | 56 | rising edge at `k` (given) |
| `0x144310750` | 60 | **level** — `bt frame[0], btn` |
| `0x14430f360` | 20 | stick **angle**, `frame[idx*8 + 0x08]` (idx 0 = left, 1 = right) |
| `0x14430f750` | 54 | stick **magnitude**, `frame[idx*8 + 0x0c]` |
| `0x14430f700` | 14 | **analog trigger pressure**, `frame[0x18 + btn] / 255.0`, guarded `btn < 0x21` |
| `0x1443106a0` | 4 | scans back for a run of `r8b` consecutive down-frames |
| `0x14430f940` | 2 | stick-magnitude delta between frames `k` and `k+1` |
| `0x14430fa30` | 2 | analog pressure crossed `xmm2` between frame 1 and frame 0 |
| `0x144310790` | 2 | stick magnitude `> xmm2` at frame `r9d` |

**Every call site of all five raw getters lives in `match::pad` or `match::Command`** except two —
`0x143cd9550` (896 B, single caller `0x143cd8180`) and `0x1449c72b0` (187 B, vtable-reached). No
`match::player`, `match::ai` or `match::anime` function reads the pad ring. [b]

`0x1440de840`, the only heavy consumer of the pressure getter (12 of its 14 sites), is **not** a
power path: it compares the two sticks and six trigger/button pressures between frames 0 and 1 and
counts frames of no change against `FPS×10` / `FPS×20` — an **idle/AFK detector**. [b]

---

## 3. `ThinkUnitBase::vf8` = the press machine (`unit+0x1c`) [b]

`0x1440d7bd0`. Extends the 4-state sketch already in `docs/exe-gameplay-map.md` with the exit that
matters:

```
state 0  idle      : vf17 (§14.5 rising edge) -> state 1
state 1  pressed   : btn == 0x21 (none)              -> state 3
                     level(btn) still down           -> state 2
                     otherwise                       -> state 3
state 2  held      : btn == 0x21                     -> state 3
                     level(btn) down AND gauge < 1.0 -> stay in 2
                     otherwise -> state 3, and stamp unit+0x38 = matchSettings+0x3318
state 3  released  : vf14 -> command id; +0x1c reset to 0 at the top of the next frame
```

Dispatch after the transition (`0x1440d7c42`): state 1 → `0x1440d7e8b`; **state 2 → `0x1440d7d30`,
which calls `vf13` (the charge tick) and, if `unit+0x2c == 0 && unit+0x10 == 4 && vf13 == 0 &&
gauge > 0`, feeds `0x143e9df80(ctx, playerIdx, xmm2 = gauge, xmm3 = stickAngle, …)` — the on-screen
aim guide**; state 3 → `0x1440d7ce5` (`vf14`); state 4 → `vf15`.

Two consequences worth stating plainly:

* **Holding past full fires the kick by itself.** `0x1440d7c99 movss xmm0,[rdi+0x20]; comiss xmm0,
  1.0; jb stay` — the only way to remain in state 2 is a gauge strictly below 1.0. You never have to
  release. [b]
* **`unit+0x10 == 4` is the "kick" class.** It is tested here (`0x1440d7d48`) and again at
  `0x1440dd10e`. The five values of `+0x10` that §14.13.2 left undecoded are a **unit class**, and
  `4` is exactly the set ShortPass / LongPass / ThroughPass / Shoot / Clear / KickFeint / Kickoff /
  Penaltykick / KeeperAutoPuntkick / AutoRestart / BlockTestAutoRestart. [b for the test, a for the
  membership, from the §14.4 factory table]

`ThinkUnitBase::vf1` (`0x1440d7b30`) is the reset and zeroes `+0x20` (gauge) next to `+0x19`
(flags), `+0x28`/`+0x29`, `+0x2c..+0x33`, `+0x38`, and conditionally `+0x1c`, `+0x24`, `+0x34`.
`vf2..vf7` are six one-line thunks that call it with reasons 1..6. **That is what proves `+0x20` is
a per-press gauge and not a persistent setting.** [b]

### The stick units have their own machine

Class-0/1 units (`unit+0x0c ∈ {0,1}`, the `ThinkUnitStickKind` family) use **`vf16`** instead, base
`0x1440d7ef0`. `ThinkUnitCursorChangeManual::vf16` (`0x1440e7500`) and
`ThinkUnitTeammateSwitch::vf16` (`0x1440e76a0`) drive the same `+0x1c` 0→1→2→3 ladder off
**stick magnitude crossing 0.8** (`0x145b2a694`) on stick index `unit+0x0c` — i.e. **the right
stick**. [b]

---

## 4. The gauge: `0x1440d8070` [b for the code, a for the numbers]

```
if (1.0 <= unit[0x20]) return;                 // already full: no tick
T = table(cmdId);                              // 16-entry jump table at 0x1440d82c4, index cmdId-0x30
g = unit[0x20] + 1.0f / (FPS * T);             // FPS from 0x14533ea80
if (g > 1.0f) g = 1.0f;
unit[0x20] = g;
unit[0x38] = matchSettings[0x3318];            // frame stamp
```

| command ids | handler | `T` when `matchSettings+0x3308 == 3` | `T` otherwise |
|---|---|---|---|
| `0x3d`, `0x3e` (**Shoot**) | `0x1440d823b` | **0.38 s** (`0x146b31dd4`) | **0.25 s** (`0x1478501fc`) |
| `0x38`, `0x3a`, `0x3b`, `0x3c` (**Long / Short / Through pass**) | `0x1440d822c` | **0.42 s** (`0x1466af68c`) | **0.30 s** (`0x145b28a88`) |
| `0x30`, `0x37` | `0x1440d8254` | **1.00 s** (`0x1478502b8`) | **0.60 s** (`0x147850258`) |
| everything else | `0x1440d8268` | 0.30 s | 0.30 s |

The fill times reproduce the independent reading already in `docs/exe-gameplay-map.md` §"pad" — this
is a second derivation, not a new claim. What is new is what the gauge *becomes*.

**Float32 accumulation, emulated with the game's own arithmetic** [a]:

| id class | 30 fps | 60 fps | 120 fps | `3308 == 3`, 60 fps |
|---|---|---|---|---|
| Shoot | 8 frames / 0.267 s | **15 frames / 0.250 s** | 30 / 0.250 s | 23 / 0.383 s |
| Pass | 9 / 0.300 s | **18 frames / 0.300 s** | 36 / 0.300 s | 26 / 0.433 s |
| `0x30`/`0x37` | 18 / 0.600 s | 36 / 0.600 s | 72 / 0.600 s | 61 / 1.017 s |

**Time to full is frame-rate independent; the number of distinct power values is not.** At 60 fps a
shot has 15 reachable power levels, at 120 fps it has 30. That is a real, measurable difference in
shooting precision between frame rates. [a]

`matchSettings+0x3308` is not decoded here. `== 1` is the state in which the cursor logic and the
ball-holder snap run (§9), `== 3` is the state in which every gauge fills ~50 % slower and extra
guide code runs — most plausibly the set-piece band, **not proven**. [c]

---

## 5. `0x1440db720` — where power and direction become numbers [b]

Output is a 20-byte block + flag byte, copied by `0x1440dcd20` to `CommandPlayer+0x1a4c..+0x1a60`:

| out | dest | contents |
|---|---|---|
| `+0x00` xmm8 | `+0x1a4c` | **aim angle, degrees** |
| `+0x04` xmm11 | `+0x1a50` | left-stick magnitude at frame 0 |
| `+0x08` xmm7 | `+0x1a54` | **POWER** = `min(1.0, max(0.0, gauge))`, and the clamped value is written **back** into `unit+0x20` at `0x1440dbc27` |
| `+0x0c` xmm12 | `+0x1a58` | guide angle, `0x143c9b520` over the 2-vector at `CommandPlayer+0x9a0` (or `+0x9b4` when `+0x9ad` is set) |
| `+0x10` xmm13 | `+0x1a5c` | guide magnitude, `sqrt(x² + z²)` of the same vector |
| `+0x14` r12b | `+0x1a60` | flags, seeded from `unit+0x19`, `\|= 4` on RT + `0x1440dfe00 >= 2` |

**Direction.** `xmm11 = stickMag(left, k=0)`. Then

* `stickMag < 0.10` (`0x145a8dd68`, compared at `0x1440db840`) → the angle comes from an **assist
  source**, not the stick: `0x1440de060(...)` when `3308 == 2` and `3378 ∈ {1,2,4}`, else
  `[teamCtx+0x4f0]` when `34a0 == 2`, else `[teamCtx+0x4ec]`;
* otherwise `0x1440d7230` → **`0x1440d7270`**:

```
out[0] = stickAngle(stickIdx, 0)
out[4] = stickMag  (stickIdx, 0)
if (cameraType-8 <= 9 || cameraType in {3,6,18,26})   // bitmask 0x4080048 at 0x1440d72c4
    if (mag > 0)  out[0] = wrapAngle(stickAngle + cameraYaw - 180.0)
```

`cameraType` is `unitCtx+0x40`, `cameraYaw` is `unitCtx+0x44`, and both are traced to source:
`match::Command::update(this, xmm1, r8d)` is called at `0x143c622d5` with
**`xmm1 = UCameraInfo[+0x00]` and `r8d = UCameraInfo[+0x54]`** — the registry record at
`MatchControl+0x1f8`, whose ctor `0x143c5c300` stores the `UCameraInfo::Pointer` vtable. They flow
`xmm8 → ThinkContext+0x28 → unitCtx+0x44` and `[rsp+0x6c] → ThinkContext+0x2c → unitCtx+0x40`.
**So the aim stick is camera-relative, but only for camera types 3, 6, 8–17, 18 and 26 — for every
other camera type the raw pad angle is used.** [b end to end]

Special cases: for `cmdId 0x2c` or `0x3b` while `3308 == 3`, `xmm11` is forced to 1.0 and the angle
is taken from `unit+0x24`; for `ebp == 0x43` the power is pulled from a *different* unit (the one
named by `CommandPlayer+0x1a38`/`+0x1a3c`), and index 4 gets a flat 1.0 — **`Clear` is always full
power**. [b]

`0x1440dcd20` does not store unconditionally: it re-stores only when the flags byte changed, or the
power **decreased**, or the angle moved while the unit's stamp is younger than `FPS×0.05` frames
(`0x145b5588c`) and the stick magnitude is above 0.9 (`0x145b56e08`), or the guide angle moved more
than 5° (`0x145a8dd78`), or the guide magnitude crossed 0.20 (`0x1478501c0`). [b]

---

## 6. The wire format: a 16-byte command record [b, round-trip a-emulated]

`0x144318200(cmdId)` reads field `+0x04` of a **98-entry, 20-byte-stride command descriptor table at
`0x146c19000`** (ids `0x00..0x61`); the value is a *category* 0..13 that selects the packer through
the jump table at `0x1440db188`. The kick ids are category **3** (`0x38`, `0x3a`, `0x3b`, `0x3d`,
`0x3f`–`0x41`, `0x43`) or **4** (`0x39`, `0x3c`, `0x3e`).

Category-3 packer `0x144318700` / decoder `0x144317cd0`:

| record bits | field | scale |
|---|---|---|
| `rec[0] & 0x7f` | command id (`>= 0xf8` = empty slot) | — |
| `rec+4` bits 0–8 | aim angle | raw degrees, wrapped if `> 360` |
| `rec+4` bits 9–11 | stick magnitude | `0x144317840`: `clamp((int)(m×7),0,7)`, decoded `/7` |
| `rec+4` bits 12–19 | **POWER** | `0x144317860`: `clamp((int)(p×127),0,127)`, decoded `/127` |
| `rec+4` bits 20–23 | a 4-bit tag | — |
| `rec+4` bits 28–31 + `rec+8` bits 0–4 | guide angle (9 bits) | raw degrees |
| `rec+8` bits 5–7 | guide magnitude | `/7` |
| `rec+8` bits 8–15, 16–23 | two bytes | — |

Emulated over the game's own bytes [a]:

```
gauge 0.000 -> 0    -> 0.00000      mag 0.00 -> 0 -> 0.0000
gauge 0.050 -> 6    -> 0.04724      mag 0.14 -> 0 -> 0.0000   (below 1/7 collapses to zero)
gauge 0.250 -> 31   -> 0.24409      mag 0.15 -> 1 -> 0.1429
gauge 0.500 -> 63   -> 0.49606      mag 0.50 -> 3 -> 0.4286
gauge 0.900 -> 114  -> 0.89764      mag 1.00 -> 7 -> 1.0000
gauge 1.000 -> 127  -> 1.00000
```

and a full pack → `0x144317cd0` round trip is exact for angle, magnitude, power, guide angle and
guide magnitude. [a]

Quirk, harmless: `0x144317860` on a negative input takes the `js` path which does `xor al,al` only,
leaving `eax = 0xFFFFFF00`; every caller does `movzx ecx, al`, so it reads 0. The gauge is clamped
`>= 0` upstream anyway. [a]

**This closes the open item in `registry-pad-command-channel.md` §14.11 / `player-executors.md`: the
pad → executor hand-off is `0x144317cd0`.** It is *not* a `UCommandOutput::ScopedRead` inside
`0x144261bd0` (that correction stands), it is the per-command record decoder, and its callers
include `match::player::ActionShortPass::vf2`, `ActionKickFeint::vf4` / `ActionKickoff::vf4`,
`ActionKeeperPuntKick::vf4` and `ActionKeeperThrow::vf4`. [b]

---

## 7. Does the human get a kick-error discount? No. [a + b]

`f` in `(1-f)×22.5°` / `σ = max(0.1, 0.75 + K(1-s)²)` is the return of **`0x143ed71d0`**, and it is a
pure function of the kicker's own effective kick attribute. `0x143ed7440` picks the attribute index
by kick class (`0x1b`, `0x1c`, `0x1d`, `0x1e` …), reads it through `0x143ea8cb0` (ATTR_get), and
subtracts penalties for weak foot, playing style, `teamCtx+0x5098` and condition. The tail is a
three-segment piecewise-linear curve, **emulated** [a]:

```
attr  40 -> f 0.00000       attr  75 -> f 0.50000
attr  50 -> f 0.05000       attr  85 -> f 0.76667
attr  60 -> f 0.10000       attr  90 -> f 0.90000
attr  65 -> f 0.23333       attr  95 -> f 0.95556
attr  70 -> f 0.36667       attr  99 -> f 1.00000
                            attr 105 -> f 1.06667   (no upper clamp)
```

i.e. `f = (a-40)·0.005` below 60, `0.1 + (a-60)·0.8/30` from 60 to 89, `0.9 + (a-90)/90` at 90+.
**Almost the whole dynamic range sits between 60 and 89.** A 60-rated finisher is at 0.10 and an
89-rated one at 0.87 — that is the interval the realism mod should think in.

*(Methodology note: my first emulation of this fragment returned a flat 0.1 across 60–89 because the
page holding the 0.8 multiplier was unmapped. The table above is the run with every constant page
mapped and a positive control printing `0x145b2a694 == 0.8`.)*

**And there is no human/CPU branch anywhere in the model.** The depth-4 direct-call closure of the
kick-miss builder `0x14401a900` is 139 functions, and it contains:

* `0x143ed71d0` at depth 1, `0x143ea8cb0` (ATTR_get) and the RNG `0x144345d90` at depth 2 —
  *positive controls, both pass*;
* **no** `AiLevelUnit::GetParam` (`0x1442e48f0`) and **no** `Team::GetCurrentLevel` (`0x1442ee570`)
  — so no CPU-difficulty term;
* **no** pad read (`0x144310750` / `0x14430f9b0` absent) and **no** decoded command record
  (`0x144317cd0` absent);
* **zero** memory operands with displacement `0x2b4dc`, `0x2b900` or `0x2f5c0` — the control-source
  array, the pad sub-system and `PadInputRef` inside `match::Command`. Positive control for that
  scan: `match::Command::update` itself yields `lea rdx,[r13+0x2b4dc]` at `0x1440d47cc` and
  `0x1440d498a`.
* Negative control: the same closure walker on the stub `0x140c837d0` returns 1 function.

`0x14401a900` has exactly one caller and one entry (`match::anime::action::Kick::vf8`, given by
`player-executors.md`), shared by both sides. **Conclusion: a human-struck ball and a CPU-struck
ball get the same error distribution, keyed only on the kicker's attributes and the physical
situation.** [b, with the caveat that this is a *direct-call* closure — virtual dispatch inside it
was not followed, so "no difficulty read anywhere below" is [b] for direct calls and [c] beyond.]

This confirms and strengthens the open question already recorded in `docs/exe-gameplay-map.md` line
98 ("Nothing in 0x14401a900's tree reads an obvious level").

**Where a human advantage could still live, and this probe did not quantify it:** the *aim* the
error is applied to. When the left stick is below **0.10** magnitude, `0x1440db720` replaces the
player's angle with an assisted one (§5). That branch has no CPU counterpart because the CPU never
enters this code path at all. Measuring it is the obvious next probe.

---

## 8. The rest of the namespace [b]

`exe_map.json` lists **73** `match::pad::*` classes. 72 are the concrete units the factory builds;
the 73rd is **`ThinkUnitBase`** itself (vft `0x146ba0588`, no bases). There is nothing else in the
namespace. Four further names appear **only** in class-hierarchy descriptors, with no vftable of
their own — `ThinkUnitPadId`, `ThinkUnitStickKind`, `ThinkUnitSkip` and `ThinkUnitGoalMouseTarget`
(the last is a *second* base of `ThinkUnitPenaltykickGuide`, i.e. genuine multiple inheritance).
`ThinkUnitFreeMove` doubles as a base for `KeeperPenaltykickMove` and `ThrowinBodyAngleRotation`.

Pad-adjacent classes outside `match::pad`:

| class | vftable | what it is |
|---|---|---|
| `match::Command` | `0x146b9e7d8` | 20 vtable slots, **17 of them the `ret 0` stub**; only `vf0` `0x1440d3060`, `vf9` `0x1440d4bc0`, `vf10` `0x1440d4c20` are real. The per-frame work is the non-virtual `update` `0x1440d4180` (given) |
| `match::CommandPlayer` / `CommandPlayerBase` | `0x146ba0620` / `0x146ba0558` | the per-player unit host (given). `Base::vf1` `0x1440ddcd0` |
| `match::CommandListener` | `0x146afbd18` | 7 slots, all in `0x143c62ef0..0x143c633f0` — the match-loop hook that calls `Command::update` (`0x143c622d5`) |
| `match::PostCommandListener` | `0x146afc320` | 4 slots, `0x143c634b0` / `0x143c63540` / `0x143c63530` — the after-commands hook |
| `match::MatchCommandObject` | `0x146afb6f8` | ctor `0x143c60d90`, **0x5358 bytes**; the object that owns the listeners |
| `match::ParameterGameCommandPriority` | `0x147740750` | ctor `0x145714160`, **0x320 bytes**; the command-priority parameter block |
| `match_system::pad_action::ActionResolver` | `0x147714878` | `vf1` `0x14572d460` / `vf2` `0x14572d3d0`: index an action id into a vector of 24-byte handler entries and tail-call its `vf1`/`vf2` |
| `match_system::pad_action::TriggerPress` / `TriggerClick` | `0x147746a30` / `0x147746a50` | one-line `vf1`s (`0x145727770` / `0x145727730`) that fetch `0x144285380()` and tail-jump its vtable slot 5 / slot 6 with `this+8` as the action id. **This is the replay/highlight input layer, not the live pad** |
| `match::ReplayPadActionResolver` (+ `ReplayPadActionMappingTable_Default`, `W4ReplayPadActionKind::MappingTable`) | `0x1477148c8` | `vf1` `0x1457277d0` is a bare `jmp ActionResolver::vf1` — the replay variant |
| `cobra::game::PadInputAssign` | `0x146a77bc8` | ctor `0x143b449e0`, **0x58 bytes**; the platform-side pad→slot assignment that feeds `0x1453e7130`'s 24-byte copy (§14.10) |
| `match::OnlineCommandController` / `…Impl` | `0x14773b808` / `0x14773b900` | 30 slots; the network ingress that owns `UCommandInfo` (given) |
| `match::OnlineCommandListener` / `OnlinePostCommandListener` / `OnlineCommandBinary` / `OnlineCommandSender` | — | the online mirrors of the two listeners plus the wire (de)serialiser |
| `match2D::Screen::ModelCursor`, `ModelCursorName`, `ModelCursorNextTarget` | `0x147719508`, `0x147719b90`, `0x14771a1f8` | the HUD models. **`ModelCursorNextTarget` exists**, i.e. the game renders a "next player" indicator, so a next-player choice *is* computed somewhere |
| `match::cursor::CursorManager` | `0x146affcf0` | only 2 virtuals; `vf1` `0x143c75420` is a `match::record::Receiver` callback for replay events, **not** the chooser |

---

## 9. Cursor switching — what is proven, and what is not

**Proven [b]:**

* `ThinkUnitCursorChange` is bound to **LB on the press edge** (given, §14.5) and its only override
  is `vf12` `0x1440e20b0` = `mov eax, 0x37`. Command **`0x37`**, descriptor
  `{0, cat 2, 2, 255, 0x010101}`.
* `ThinkUnitCursorChangeManual` and `ThinkUnitTeammateSwitch` are **right-stick** units
  (`unit+0x0c == 1`) whose `vf16` machines advance on **magnitude > 0.8**. So the game does have a
  stick-directed manual switch, and its threshold is 0.8, not the 0.2 dead zone.
* `ThinkUnitCursorChangeKeeper` is bound to logical 13 (the menu bank), `+0x10 = 2`.
* Two consumers of command `0x37` were located, and **both are suppressors, not choosers**:
  * `0x1440db1c0` (the 0x51-unit loop) reads command slot `0x11` via `0x1442eb080`; if it is **not**
    `0x37` and its `+0x14` differs from `matchInfo+0x41d8`, it sets `CommandPlayer+0x1a6d = 1`
    (`0x1440db2c6`–`0x1440db2d6`). `+0x1a6d` is copied into every unit context at `+0x4b`
    (`0x1440d714c`).
  * `0x1453f0610` reads command slot `7`; if it is **not** `0x37`, and `+0x45 != 0` and `+0x30 == 5`,
    it scans the 24 command slots for the one whose `+0x10` equals `matchInfo+0x41d8` (the ball
    holder's player number) and writes that slot index to **`UCursorInfo+0x1928`**. That is an
    **auto-snap of the cursor to the ball holder, every frame, gated off while a cursor-change
    command is live** — and it only runs when `matchSettings+0x3308 == 1`.

**Not proven, and I will not guess:** *which* player LB picks. No function was found that scores the
ten outfield candidates. The honest leads for the next probe are (a) `UCursorInfo+0x1928`'s other
writers `0x1442c8710` / `0x1442ca1d0` (both only store the sentinel `0x18` = "none", so they are
initialisers), (b) `match2D::Screen::ModelCursorNextTarget` `0x14771a1f8` — the HUD model must read
the chosen next player from somewhere, and (c) `0x143c71e90`, which returns a slot index `< 0x18`
and is called from the cursor record receiver `0x143c75420`.

So: *"is it stick-directed?"* — **there is a stick-directed variant (right stick, 0.8)**; whether
plain LB is also direction-biased is **not established**. *"Is there an auto-switch?"* — **yes, at
least a per-frame snap to the ball holder** (`0x1453f0610`), which is the classic source of "the game
fights me" when possession flips.

---

## 10. Tunables, honestly

Sharer counts from `tools/exe_census.py cell --all` over PRISTINE.

| what | site | route | sharers | verdict |
|---|---|---|---|---|
| **Set-piece pass gauge 0.42 s** | `0x1466af68c` | exe-constant | **10** | Safe. Effectively private. Raising it lengthens the dead-ball pass bar |
| **Set-piece shot gauge 0.38 s** | `0x146b31dd4` | exe-constant | **6** | Safe. The cleanest single edit in this subsystem |
| Open-play **shot** gauge 0.25 s | `0x1478501fc`, loaded at `0x1440d824a` | **exe-code re-aim only** | 657 | Re-aim the 8-byte `movss xmm6,[rip→0.25]` at a private cell. 0.40 s would make full power take 24 frames at 60 fps — 24 power levels instead of 15, i.e. "you have to commit to a shot" |
| Open-play **pass** gauge 0.30 s | `0x145b28a88`, arms `0x1440d822c` **and** the default `0x1440d8268` | **exe-code re-aim only** | 895 | Re-aim the `0x1440d822c` arm, not the default — the default is shared by every non-kick charging id |
| `0x30`/`0x37` gauge 0.60 s | `0x147850258` at `0x1440d825e` | exe-code re-aim | 438 | Unidentified commands; leave alone |
| **Power quantisation 127** | `0x145b4c548` at `0x144317868` | exe-code re-aim | 88 | Lowering it coarsens power to N+1 levels — a deliberate "no pixel-perfect power" knob. Must be changed in the packer **and** the decoder (`0x144317d43`) or power scales wrong |
| Stick magnitude quantisation 7 | `0x145c36ac0` | exe-code re-aim | 398 | Three sites (`0x144317840`, `0x144317d28`, `0x144317d7c`). Not recommended |
| **Assist threshold 0.10** | `0x145a8dd68` at `0x1440db7f0` | exe-code re-aim | 1186 | The line between "the stick aims" and "the game aims". Lowering it toward 0 makes aiming fully manual; raising it hands more passes to the assist. **The highest-leverage realism knob in the pad layer**, and untested |
| Cursor-switch stick threshold 0.8 | `0x145b2a694` at `0x1440e757c` / `0x1440e76e3` | exe-code re-aim | 622 | Separate load sites, so CursorChangeManual and TeammateSwitch can be re-aimed independently |
| Dead zone 0.20 / saturation 0.95 / divisor 0.75 | `0x1478501c0`, `0x145e8788c`, `0x145a8dd6c` (given, §14.2) | exe-code re-aim | 1165 / 77 / 229 | The 0.95 cell is the least shared. Changing the dead zone changes *every* stick read in the match |
| Tap window 0.08 s | `0x145e87854` (given, §14.6) | exe-code re-aim | 44 | Modest sharing; ~7 call sites multiply it against the live frame rate |
| Camera-relative aim on/off | the bitmask `0x4080048` and `cmp eax,9` at `0x1440d72ba`–`0x1440d72cc` | exe-code (private immediates) | — | Forcing the raw-stick branch makes aiming pitch-absolute regardless of camera. Interesting, untested, and it would change set-piece aiming too |
| Per-unit button rebinding | the factory `0x1440e0c70` writes `unit+0x08` (button) and `unit+0x10` (class) | runtime-data (given, §14.12) | — | Given |
| The gauge itself | `unit+0x20` | runtime-data | — | Writable, but rewritten every frame by `0x1440d8070` and re-clamped by `0x1440db720`. **NOT a stable lever** |
| `matchSettings+0x3308` | — | **NOT SAFELY TUNABLE** | — | A play-state, not a setting; forcing it moves the cursor logic, the guide and the gauge together |

---

## 11. Negatives and honest not-proven

1. **No human/CPU asymmetry in the kick-error model** (§7). Depth-4 direct-call closure, two positive
   controls, one negative control, one displacement scan with its own positive control. Virtual calls
   inside the closure were not followed. [b/c]
2. **Nothing outside `match::pad` / `match::Command` reads the pad ring**, with the two exceptions
   named in §2. A human's input reaches the executors only as a decoded 16-byte command record. [b]
3. **The LB cursor chooser is not located.** Only suppressors and the ball-holder snap were found.
4. **`matchSettings+0x3308 == 3` is not identified.** "Set piece" is [c].
5. **The assist branch was not quantified.** The branch and its 0.10 threshold are [b]; how much
   correction the human gets is unknown — `0x1440de060`, `[teamCtx+0x4ec]` and `[teamCtx+0x4f0]` were
   not emulated.
6. **`unit+0x29`** gates both the multi-press path in `vf17` and the Shoot/LongPass `vf9`/`vf10`
   branches (`cmp byte [rbx+0x29], 1/2`). It is zeroed by `vf1`. Its writer was not found — the
   press-count reading is [c].
7. **The `+0x10` unit class**: `4` is proven to be the kick class (§3) and `3` is compared at
   `0x1440dcff8`; **0, 1, 2 remain unnamed.** A partial close of §14.13.2, not a full one.
8. `unit+0x24` is a second float, read as the aim angle in two special branches (`0x1440dae30`,
   `0x1440db977`) and conditionally zeroed by `vf1`. **Not decoded.**
9. **Category 4** (`0x39`, `0x3c`, `0x3e`) uses a packer path I did not follow. Only category 3 is
   decoded here.
10. The `esi → dil` map in `0x1440daeb2` (unit index 0..4 → `0x3a/0x38/0x3b/0x40/0x3d`) does not line
    up with the §14.4 factory order for indices 3 and 4. **Not resolved**; not emulated.

---

## 12. Corrections to finished chapters

1. **`registry-pad-command-channel.md` §14.10 — "The ThinkContext (`0x1440d7010`, 0x34 bytes)" is two
   objects, and the table describes the wrong one.** `0x1440d7010` builds a ~0x34-byte struct whose
   `+0x08` is the **control-source record** (arg5), `+0x10` the command entry (arg7), `+0x18` the
   **pad-block holder** (arg6), `+0x20` the slot index, `+0x24` the **player number** (0..21, `0xff`
   = none — *not* the pad index), `+0x28` the **camera yaw** (f32) and `+0x2c` the **camera type**
   (u32). Every `ThinkUnit` method instead receives a **0x4c-byte unit context** built from it by
   **`0x1440d70f0(out, thinkCtx, commandPlayer)`**: `+0x00` pad system, **`+0x08` &padBlock** (this is
   the one "every predicate dereferences"), `+0x10` command entry, `+0x18` slot index, `+0x1c` player
   number, `+0x20..+0x3f` a **32-byte copy of the control-source record**, `+0x40` camera type,
   `+0x44` camera yaw, `+0x48`/`+0x4a` two bytes, `+0x49` `[0x1442d7090(…)+0x28c]`, `+0x4b`
   `CommandPlayer+0x1a6d`. Root cause of the original error: the two structs share `+0x00` and both
   are passed as "ctx". [b]
2. **§14.11 / `player-executors.md` open item "the pad → executor hand-off is NOT established" — it
   is now established**, via the command-record decoder `0x144317cd0` (§6), not via a
   `UCommandOutput::ScopedRead`. The existing correction about `0x144261bd0` is untouched. [b]
3. **§14.13.2 "the `+0x10` per-unit mode is not decoded" — partially closed.** `+0x10 == 4` is the
   kick/charge class, tested at `0x1440d7d48` and `0x1440dd10e`. 0/1/2/3 remain open. [b]
4. **§14.4 lists `ThinkUnitShoot`'s overrides at vf9/vf10/vf13/vf14/vf17 without their roles, and
   §14.5's phrasing invites "vf12 returns the command id".** vf13 is the **charge tick**, vf14 the
   **command id**, vf9/vf10 set the modifier bits in `unit+0x19`, and base `vf12` (`0x1440ddd30`) is a
   bare `jmp [vtable+0x68]` into vf13. Only the handful of units that override vf12 directly (e.g.
   `CursorChange` → `0x37`, `Clear` → 0) return an id from slot 12. [b]

---

## 13. Reproduction

Read-only scripts over PRISTINE, in the probe scratchpad:

| script | proves |
|---|---|
| `b.py` / `nm.py` | chunk-correct disassembly (`funcs.func_chunks`, never `func_range`) + vtable naming |
| caller census of `0x14430f360/750/700`, `0x144310750`, `0x14430f9b0` | §2, and the "no pad read outside `match::pad`" negative |
| `emu2.py` | `0x144317840` / `0x144317860` quantiser sweeps and the `0x144317cd0` pack → unpack round trip |
| `emu4.py` | the `f` curve over `0x143ed726a..ret` with all constant pages mapped (+ the `0.8` positive control), and the float32 gauge-fill table |
| the closure walker | the 139-function depth-4 closure of `0x14401a900`, its two positive controls and the stub negative control |
| `exe_census.py cell --all` | every sharer count in §10 |

No script in this probe writes to the game, the installed image or `tools/`.
