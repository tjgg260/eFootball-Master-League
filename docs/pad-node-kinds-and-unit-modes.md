# The pad pattern engine, finished — probe `node-kinds-and-unit-modes` (2026-09-20)

Companion to [registry-pad-command-channel.md](registry-pad-command-channel.md), which is **given
as fact** here. That chapter decoded `UPadInput`, the button-id space, the 72 `ThinkUnit`s, the tap
law and the hook point, and closed with eight open items in its § 14.13. **This chapter closes six
of them and corrects three claims the old chapter got wrong.** Nothing here re-derives what it
already established.

Evidence levels: **a-emulated** / **b-disassembly** / **c-inferred**. All addresses are VAs at base
`0x140000000`, read and emulated from `eFootball.exe.PRISTINE`. Nothing was written to the game, to
either image, or to `tools/`.

---

## 0. Executive summary

1. **All eleven node kinds are named and emulated.** Kinds 0, 3, 5, 6, 7 and 10 were not proven
   before. Kind 10 *is* vacuously true — confirmed — but it consumes one frame and **only exists in
   dispatch table C**; a kind-10 node with a stick constraint calls a null pointer.
2. **The old chapter has kinds 1 and 3 swapped.** Kind 1 is the **press** edge, kind 3 the
   **release** edge. Its own correction paragraph had it right; the prose label did not.
3. **The per-unit `+0x10` is decoded.** It is not a trigger mode — it is the unit's **command
   lifecycle class**, and the switch the old chapter could not find is at `0x1440dd691`
   (`mov ecx,[r14+0x10]; sub ecx,2; je …; sub ecx,1; je …; cmp ecx,1; jne …`), naming cases 2, 3
   and 4, with cases 1 and 0 handled by separate compares. The real press/hold/release machine is a
   *different* field, `+0x1c`, driven by `ThinkUnitBase::vf8` at `0x1440d7bd0`.
4. **The gesture table is 16 rows, not 5, and it is three tables, not one.** `0x1440d8b20` has **no
   conditional branches at all** — the old "5 rows, lower bound" was an emulation artefact, not a
   branch. All three tables are consumed by **`match::pad::ThinkUnitFeint::vf8` (`0x1440d8480`)`**,
   i.e. this is the **skill-move / feint** table.
5. **Kinds 11, 12 and 13 exist and are not predicates.** They are stick-group accumulators handled
   *before* dispatch by a **second evaluator, `0x14430fcc0`** (wrapper `0x14430fac0`), which the
   feint table uses instead of `0x14430fb40`. In a `ThinkUnit` chain they would call a null pointer.
6. **The scheduler is found.** It is `cobra::game::ListenerManager` broadcasting **event id 1** to
   `cobra::game::Listener::vf1`. Both endpoints hang off event 1. Their **relative order is runtime
   registration order and cannot be settled from the image** — stated with what that costs.
7. **`ScopedWAndC` on `UPadInput` is a no-op**, emulated: `UPadInput` registers as a `Pointer`
   record (`xor r9d,r9d` at `0x143c62a35`) and the commit `0x145340a10` early-outs on
   `cmp dword [rax],1`. **A runtime write into a pad structure needs no commit.**
8. **The trigger-run hook: the feature the brief wants already ships.** `ThinkUnitPassAndGo`'s
   chain A *is* "tap RB while RT is not held", emulated end to end. A precise byte-level spec for
   three candidate edits is in § 6. **Nothing was written.**

---

## 1. The node kinds — all eleven, emulated

### 1.1 Method and controls

Harness: `scratchpad/pademu.py` + `scratchpad/kinds.py`. A synthetic `0x1908` pad-slot block with
cursor = 50 and one button (logical 21 = RB) driven; the node built as a 40-byte record; **the
game's own handler called directly** with the signature the evaluator uses.

> **Handler signature, corrected.** Table-A/B/C handlers take **`rcx = the pad-slot block`**, not
> the wrapper. The evaluator does `mov rsi,[rcx]` first (`0x14430fb69`) and passes `rsi`. Passing
> the wrapper makes every handler read a garbage cursor and return the same value for every input —
> the saturation the brief warns about. My first run did exactly that; every row read `0` or `-1`.
> The corrected run is below. [a]

**Positive control** — a hand-written node must equal the game builder's own output byte for byte,
with the three padding bytes at `+0x11..+0x13` left untouched (the builders never write them):

```
0x14430edb0 kind1(node,btn,B)      builder 0000200001000000000000000700000000cccccc…000080bf000080bf
                                   hand    0000200001000000000000000700000000cccccc…000080bf000080bf   MATCH
0x14430edf0 kind8(node,btn)        MATCH        0x14430ee30 kind2(node,btn,A,B)   MATCH
0x14430ee80 kind9(node,btn)        MATCH        0x14430eec0 kind4(node,btn,B)     MATCH
```

**Negative control** — three of the eleven kinds must *fail*: kind 10 in tables B and A is a null
pointer, and a kind-10 node steered to either table faults:

```
table C @0x148081710: entry[10] = 0x14430d760   entry[11] = 0x0
table B @0x148081770: entry[10] = 0x0           entry[11] = 0x0
table A @0x1480817d0: entry[10] = 0x0           entry[11] = 0x0
kind 10 with +0x10 = 1     (table A) -> FAULT: UC_ERR_FETCH_UNMAPPED
kind 10 with +0x20 = +0.5  (table B) -> FAULT: UC_ERR_FETCH_UNMAPPED
```

Both tables are file-backed (raw offsets `0x8081710`/`0x80817d0` exist), and there is **no writer
anywhere** to `0x148081820`, `0x148081828` or `0x148081838`. The nulls are permanent. [b]

### 1.2 The raw matrix

`h(block, node, start = 0, window = 100)` → frame index, `-1` = no match. Ring patterns are written
frames-ago, index 0 = now.

```
scenarios:   0 never  1 always  2 down1f  3 down3f  4 down8f  5 tap2/rel1  6 tap2/rel3  7 press8/rel1  8 hold40/rel1  9 burst f20..f25

kind  0  A=1 B=0  |    0   -1    1   -1   -1    0    0    0    0    0
kind  0  A=3 B=0  |    0   -1    1   -1   -1   -1    0   -1   -1    0
kind  0  A=3 B=8  |    0   -1    1    3   -1    0    0   -1   -1    0
kind  0  A=8 B=8  |    0   -1    1   -1   -1   -1   -1   -1   -1    0
kind  1  A=0 B=0  |   -1   -1    1   -1   -1   -1   -1   -1   -1   -1
kind  1  A=0 B=5  |   -1   -1    1    3   -1    3    5   -1   -1   -1
kind  1  A=0 B=40 |   -1   -1    1    3    8    3    5    9   41   26
kind  2  A=1 B=0  |   -1    1    1    1    1    2   -1    2    2   -1
kind  2  A=3 B=0  |   -1    3   -1    3    3   -1   -1    4    4   -1
kind  2  A=8 B=8  |   -1    8   -1   -1    8   -1   -1    9    9   -1
kind  3  A=0 B=0  |   -1   -1   -1   -1   -1    1   -1    1    1   -1
kind  3  A=0 B=40 |   -1   -1   -1   -1   -1    1    3    1    1   20
kind  4  A=0 B=5  |   -1   -1   -1   -1   -1    3    5   -1   -1   -1
kind  4  A=0 B=12 |   -1   -1   -1   -1   -1    3    5    9   -1   -1
kind  5  A=0 B=0  |   -1   -1    0   -1   -1   -1   -1   -1   -1   -1
kind  5  A=0 B=40 |   -1   -1    0    0    0    0    0    0    0    0
kind  6  A=1 B=0  |   -1    0    0    0    0    0   -1    0    0   -1
kind  6  A=3 B=0  |   -1    0   -1    0    0   -1   -1    0    0   -1
kind  7  A=0 B=0  |   -1   -1   -1   -1   -1    0   -1    0    0   -1
kind  7  A=0 B=40 |   -1   -1   -1   -1   -1    0    0    0    0    0
kind  8  A=0 B=0  |    0   -1    0   -1   -1    0    0    0    0    0
kind  9  A=0 B=0  |   -1    0    0    0    0    0   -1    0    0   -1
kind 10  A=0 B=0  |    0    0    0    0    0    0    0    0    0    0
```

and, because kinds 8/9/10 ignore `A`/`B` and key off `start` instead, a second sweep over `start`:

```
kind 8   never down            start=0..8 ->  0  1  2  3  4  5  6  7  8
         always down           start=0..8 -> -1 -1 -1 -1 -1 -1 -1 -1 -1
         up f0..f4, down after start=0..8 ->  0  1  2  3  4 -1 -1 -1 -1
kind 9   always down           start=0..8 ->  0  1  2  3  4  5  6  7  8
         down f0..f4 only      start=0..8 ->  0  1  2  3  4 -1 -1 -1 -1
kind 10  (any ring)            start=0..8 ->  0  0  1  2  3  4  5  6  7
```

### 1.3 The table — every kind named [a for behaviour, b for the code]

| kind | handler (table C) | name | reads | returns on match | consumes? |
|---|---|---|---|---|---|
| **0** | `0x14430d770` | **UP for `A` consecutive frames**, searched forward from `start` | `A` = `byte[node+8]`, scan span = `max(A,B)+1` | index of the newest up-frame seen | yes |
| **1** | `0x14430d830` | **PRESS EDGE** — down at `i`, up at `i+1` | `B` = `byte[node+0xc]` = max pairs scanned − 1 | `i+1` (the up frame) | yes |
| **2** | `0x14430d8e0` | **DOWN for `A` consecutive frames** | `A`, span `max(A,B)+1` | oldest frame of the run + 1 | yes |
| **3** | `0x14430d980` | **RELEASE EDGE** — up at `i`, down at `i+1` | `B` | `i+1` (the down frame) | yes |
| **4** | `0x14430da30` | **TAP** — kind 3 then kind 1, gap-bounded | `B` | the press index | yes |
| **5** | `0x14430dab0` | kind 1, **non-consuming** ("peek") | `B` | `start` unchanged | no |
| **6** | `0x14430dad0` | kind 2, **non-consuming** | `A`, `B` | `start` unchanged | no |
| **7** | `0x14430daf0` | kind 3, **non-consuming** | `B` | `start` unchanged | no |
| **8** | `0x14430db10` | **LEVEL: button UP across `[0, start]`**, ≤ 1 down frame of slack | `start` only | `start` unchanged | no |
| **9** | `0x14430dbd0` | **LEVEL: button DOWN across `[0, start]`**, ≤ 1 up frame of slack | `start` only | `start` unchanged | no |
| **10** | `0x14430d760` | **ALWAYS TRUE** | nothing | `start > 0 ? start−1 : start` | one frame |

Kinds 5/6/7 are `push rbx; mov ebx,r8d; call <1/2/3>; test eax,eax; mov ecx,-1; cmovns ecx,ebx;
mov eax,ecx; ret` — literally "run the predicate, then throw away the index and hand back the
caller's". They are how a chain asks *"did this also happen?"* without moving the search window. [b]

Kind 10 in full is four instructions:

```
0x14430d760  test r8d, r8d
0x14430d763  lea  eax, [r8-1]
0x14430d767  cmovle eax, r8d
0x14430d76b  ret
```

It cannot return `-1`, so **it is vacuously true — confirmed**, and § 14.12's advice on shortening a
chain by making a node vacuously true is sound, *with the two caveats in § 1.5*. [b + a]

### 1.4 The tap law, restated exactly [b + a]

`0x14430da30` calls kind 3 from `start`, gets `releaseIdx`; calls kind 1 from `releaseIdx`, gets
`pressIdx`; then

```
0x14430da78  mov ecx,eax ; sub ecx,ebx ; dec ecx ; cmp esi,ecx ; jg MATCH
```

where `ebx` is the handler's **`start`** argument (not a "bound"):

> **A tap matches iff `B > pressIdx − start − 1`, i.e. `pressDuration + releaseAge ≤ B + start`.**

At the head of a chain `start = 0` and `B = (int)(0.08·FPS + 0.5) = 5` at 60 fps, so
**press-duration plus release-age must be at most 5 frames (~83 ms)**. Verified: a 2-frame press
released 1 frame ago matches (3 ≤ 5), released 3 frames ago matches (5 ≤ 5), released 5 frames ago
does not (7 > 5). [a]

### 1.5 Three properties of the engine that constrain any edit [b, kind-10 fault [a]]

* **The mask is 32 bits.** Every handler loads it with `mov r13d/r14d/ebp, dword [node]`, so
  **logical buttons 32 and 33 can never be matched by a pattern node.** Bit 32 is the frame-validity
  flag and is tested separately.
* **The discontinuity guard is not universal.** Only the edge kinds (1, 3, and therefore 4, 5, 7)
  test `frame[0] & (1<<32)` and skip such a frame *without charging a miss*. The level and run kinds
  (0, 2, 6, 8, 9) and kind 10 do not test it at all.
* **`A` and `B` are read as bytes everywhere in table C** (`movzx …, byte [rdx+8]` /
  `byte [rdx+0xc]`), although the builders store dwords. Any value ≥ 256 wraps mod 256, and the
  window is fixed at `0x64` = 100 frames at every call site, so anything > 100 is inert.

### 1.6 Which kinds the shipped game actually builds [b]

Scanning all sixteen node builders for the constant they write to `node+4`:

| builder | kind | stick? | call sites |
|---|---|---|---|
| `0x14430edb0` | 1 | no | 9 |
| `0x14430edf0` | 8 | no | 11 |
| `0x14430ee30` | 2 | no | 5 |
| `0x14430ee80` | 9 | no | 2 |
| `0x14430eec0` | 4 | no | 2 |
| `0x14430ef00` | 1 | yes | 10 |
| `0x14430ef80` | 2 | yes | 1 |
| `0x14430f000` | 9 | yes | 4 |
| `0x14430f080` | 6 | yes | 2 |
| `0x14430f100` | 7 | yes | 2 |
| `0x14430f180` | 4 | yes | 3 |
| `0x14430f1d0` | **11** | yes | 2 |
| `0x14430f250` | **13** | yes | 2 |
| `0x14430f2d0` | 1 | yes | 6 |
| `0x14430f300` | 9 | yes | 2 |
| `0x14430f330` | 4 | yes | 1 |

**Kinds 0, 3, 5, 10 and 12 have no builder anywhere.** Kind 3 is only ever reached from inside kinds
4 and 7; kinds 0, 5, 10 and 12 are unreachable from shipped data and can only be produced by writing
a node by hand. The 42 call sites the old chapter counted are exactly the 42 inside `0x1440d8b20`
(2+2+2+1+2+2+9+1+4+2+6+6+2+1). [b]

---

## 2. Kinds 11 / 12 / 13 and the SECOND evaluator

`0x14430f1d0` (kind 11) and `0x14430f250` (kind 13) unconditionally write `byte [node+0x10] = 1`,
which selects dispatch table **A** — and `A[11]` and `A[13]` are **null**. That looks like a latent
crash until you notice that the feint table is not evaluated by `0x14430fb40` at all.

`match::pad::ThinkUnitFeint::vf8` calls **`0x14430fac0`**, a thin wrapper over **`0x14430fcc0`**, a
*second* evaluator with the same node walk plus a pre-dispatch switch:

```
0x14430fdc0  movsxd r8, dword [rbx+4]          ; kind
0x14430fdc4  mov ecx, r8d
0x14430fdc7  sub ecx, 0xb ; je 0x14430fea8      ; kind 11 -> push node, then EVALUATE the group
0x14430fdd0  sub ecx, 1   ; je 0x14430fe6d      ; kind 12 -> push node, continue
0x14430fdd9  cmp ecx, 1   ; je 0x14430fe6d      ; kind 13 -> push node, continue
              …otherwise dispatch through A / B / C exactly as 0x14430fb40 does
```

The pushed nodes go into a **10-slot local buffer** at `[rsp+0x60]` (count) / `[rsp+0x64]` (nodes),
and kind 11 hands the whole buffer to **`0x14430ffa0`** (1,254 bytes across 7 chunks, itself calling
`0x14430f390`) — a multi-node stick-sequence matcher. Because the chain walks newest-first, **kind
11 is the oldest node of the group and 12/13 the later ones**. [b]

Consequences:

* **Kinds 11, 12 and 13 are legal only in a feint-table row.** Put one in a `ThinkUnit` chain
  (`0x14430fb40`) and it calls a null pointer — the same fault the kind-10 negative control produced.
* The three table-A nulls are not a bug; they are slots the second evaluator never reaches.
* I did **not** decode `0x14430ffa0`'s predicate. "It is the stick-group matcher" is [b] by call
  site and buffer shape; what it computes is **not proven**.

---

## 3. The complete special-controls (feint) gesture table — 16 rows, three tables

`0x1440d8b20` is one straight-line function: a single `ret` at `0x1440daa6c`, and **no conditional
branch except the three `movups` copy loops**. It writes **three** tables:

| table | count | rows | rows built | consumer |
|---|---|---|---|---|
| **T1** | `0x1486adff0` | `0x1486adff4` | 5 | `ThinkUnitFeint::vf8`, always |
| **T2** | `0x148698e50` | `0x148698e54` | 3 | `ThinkUnitFeint::vf8`, **or** T3 |
| **T3** | `0x1486a3720` | `0x1486a3724` | 8 | `ThinkUnitFeint::vf8`, **or** T2 |

`vf8` builds a two-entry list `{T1, T2-or-T3}` at `[rbp-0x39]`/`[rbp-0x31]` and walks T1 first; the
second entry is chosen by `0x144118530(player+0x5c)` at `0x1440d87ce` — `0` selects **T2**, non-zero
selects **T3**. That call is a per-player property I did not decode; "assisted vs advanced control
scheme" is [c]. Row stride `0x1b0`; layout `+0x00` command id, `+0x04` flag, `+0x08` node count,
`+0x0c` nodes (`0x28` each), `+0x19c` gate mask, `+0x1a0` two floats, `+0x1a8` masked `& 0x1ff`,
`+0x1ac` a flag.

**The `+0x19c` gate mask, decoded** (`0x1440d8802`–`0x1440d8871`) — a row is skipped unless:

| bit | requirement |
|---|---|
| `0x01` | this player is the one the camera/cursor follows (`[rsp+0x4e]`) |
| `0x02` | `[rsp+0x48]` — a ball/stance precondition |
| `0x04` | `[rsp+0x44]` — an anime-class precondition |
| `0x08` | `[rsp+0x4c]` — a second anime-class precondition |
| `0x10` | `rdx == 1` |
| `0x20` | `rdx == 0` |
| `0x40000000` | **always skip** |
| `0x80000000` | **always skip** |

So **T2[1] (`+0x19c = 0x40000000`) and T2[2] (`0x80000000`) are dead rows** — they are built and
never evaluated. T2 has one live row. [b]

### 3.1 The rows, emulated at 60 fps [a]

Buttons are logical ids (18 = LB, 19 = RT, 21 = RB; 0/1/2/13 are the system/menu bank).

**T1 — always evaluated**

| row | cmd | nodes, newest last |
|---|---|---|
| T1[0] | `0x17` | `RB kind 9 HELD` ; `bit0 kind 1 PRESS + stick 0…−90°, mag 0.8` — gate `0x04` |
| T1[1] | `0x0f` | `RB kind 8 NOT-HELD` ; `mask 0x13 kind 1 PRESS, B=12, mag 0.9` ; same again ; `stick kind 6 DOWN-for-A/peek, ±180°, mag 0.2` — gate `0x20` |
| T1[2] | `0x0f` | `RB kind 8` ; `mask 0x13 kind 4 TAP, B=12` ; `stick kind 6, ±180°, mag 0.2` — gate `0x10` |
| T1[3] | `0x1b` | `bit13 kind 1, B=24` ; `stick kind 9 HELD ±180° mag 0.2` ; `bit13 kind 1, B=0` |
| T1[4] | `0x1b` | `bit13 kind 1, B=24` ; `bit13 kind 1, B=0` |

**T2 — the "second entry" when `0x144118530` returns 0**

| row | cmd | gate | nodes |
|---|---|---|---|
| T2[0] | `0x00` | `0x20000000` | `RB kind 8 NOT-HELD` ; `bit0 kind 1 PRESS + stick ±180°, mag 0.8` |
| T2[1] | `0x00` | `0x40000000` **DEAD** | `bit13 kind 1` |
| T2[2] | `0x00` | `0x80000000` **DEAD** | `RB kind 1 PRESS` |

**T3 — the rich gesture set, the "second entry" when it returns non-zero**

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

**All `B` values scale with the frame rate**: the same dump at 30 fps gives 12 → 6, 24 → 12, 18 → 9,
60 → 30. The gesture windows are therefore ~200 ms (12 @ 60), ~400 ms (24), ~300 ms (18) and 1.0 s
(60), computed live, never stored. [a]

---

## 4. The per-unit `+0x10` — it is a command **lifecycle class**

### 4.1 First, what it is *not*

The press/hold/release machine is **`ThinkUnitBase::vf8` (`0x1440d7bd0`)** driving **`unit+0x1c`**,
which the old chapter never reached:

```
if (!unit->+0x18) return 0                          ; enabled
if (unit->+0x0c != 2) { esi = vf16(unit) }          ; stick units
else switch (unit->+0x1c) {                          ; PHASE
  case 0: goto TRY
  case 1: if (btn==33) phase=3 ; else if (isDown(btn)) phase=2 ; else phase=3 ; recheck
  case 2: if (btn==33) phase=3
          else if (!isDown(btn) || unit->+0x20 >= 1.0f) { phase=3 ; unit->+0x38 = matchClock }
          recheck
  case 3: phase = 0 ; goto TRY
}
TRY: if (vf17(unit)) phase = 1
switch (unit->+0x1c) {
  case 1: if (unit->+0x14) ++unit->+0x29 ;  esi = vf12(unit, ctx)      ; the PRESS command
          if (unit->+0x10 == 4 && (r8d==0x51||r8d==0x19) && esi==0) esi = 9
  case 2: esi = vf13(unit, ctx)                                        ; the HOLD command
          if (unit->+0x2c==0 && unit->+0x10 == 4 && esi==0 && unit->+0x20 > 0) { …charge… esi = vf14 }
  case 3: esi = vf14(unit, ctx)                                        ; the RELEASE command
  case 4: esi = vf15(unit, ctx)
}
```

`+0x1c` is the phase; `+0x20` is the accumulated charge, capped at **1.0** (`0x1478502b8`); `+0x29`
is the multi-press counter. `+0x10` appears here **only twice, both `== 4`** (`0x1440d7d48`,
`0x1440d7ea9`) — the charge block and a command substitution. [b]

### 4.2 The switch the old chapter asked for

`0x1440dcf60` is the per-unit driver called from `0x1440db1c0`. It reads `[unit+0x10]` at exactly
four sites, and one of them is a real switch:

| site | test | what it gates |
|---|---|---|
| `0x1440dcff8` | `cmp dword [rsi+0x10], 3` | mode 3's *acknowledge* path |
| `0x1440dd10e` | `cmp dword [rsi+0x10], 4` | mode 4's whole *cancel* block |
| **`0x1440dd691`** | `mov ecx,[r14+0x10]; sub ecx,2; je; sub ecx,1; je; cmp ecx,1; jne` | **cases 2 / 3 / 4** |
| `0x1440dd700` | `cmp dword [rsi+0x10], 1` | mode 1's *released* hook |

`r14` at `0x1440dd691` is the unit, fetched by `0x1440e2200(player, idx)` at `0x1440dd5d3`. A sweep
of every function that can hold a `ThinkUnit*` (the eight callers of `0x1440e2200`, plus
`0x1440d7bd0` which receives `this`) finds **no other reader of `+0x10` in the image**. [b]

The switch is reached only after `0x1440dab90(...)` returned true — i.e. **the command was accepted
and emitted this frame**:

```
case 2:      call vtable+0x18 (vf3)  ;  0x1440dbdf0(player, idx, …)     -- reset now, drop the lock
case 3, 4:   if (cmd != 9 && cmd != 0x2e && unit->+0x2c == 0) {
                 unit->+0x2c = 1 ;  unit->+0x30 = cmd                   -- LATCH, stay armed
             }
default:     nothing
```

### 4.3 The five values [b]

| `+0x10` | name | behaviour, and where it is proven |
|---|---|---|
| **0** | **free-running** | No lifecycle hook of any kind; the unit re-emits while its trigger holds and the driver never resets it or releases the active-unit lock on its behalf. `TrapThrough`, `KeeperTackle`, `KeeperBlock`, `MoveStopGoal`, `GoalkickPassSupport`, `Dribble`, `FreeMove`, `SetplayGuide`. |
| **1** | **self-clearing on idle** | `0x1440dd700`: the driver snapshots `unit->+0x1c` before `vf8` (`0x1440dd437`) and, if the phase **changed and is now 0**, calls **vf2** + `0x1440dbdf0`. `Press`, `Delay`, `FriendPress`, `TacticsNext/Back`, `LineControlFront/Back`, `KickCancel`, `SuperCancel`, `FreekickKeeperMove`, `TacticsAttackLevelUp/Down`. |
| **2** | **one-shot** | `0x1440dd6c3`: **vf3** + `0x1440dbdf0` on the same frame the command is accepted. The default for simple press commands — including **`CursorChange`** and **`PassAndGo`**. |
| **3** | **latched, reset on acknowledge** | Latches like mode 4, then `0x1440dcff8`: when the player's action table at `player+0x2924` shows the latched command `unit->+0x30` running, set `+0x2c = 2` and call **vf4** + drop the lock. `KeeperPenaltykickAction`, `KeeperPenaltykickLayer`. |
| **4** | **latched, cancellable — the charged-kick class** | Latches, and owns the whole `0x1440dd10e` block: four separate paths (`+0x2c==2` with anime gates; this unit owning `player+0x1a38`; `+0x2c==1` with `player+0x1a40`; `+0x2c==0` with a live byte) each call **vf6** + drop the lock. It is also the **only** mode that accumulates charge in phase 2 (`0x1440d7d48`). `ShortPass`, `LongPass`, `ThroughPass`, `Shoot`, `Clear`, `KickFeint`, `Kickoff`, `Penaltykick`, `KeeperAutoPuntkick`, `AutoRestart`. |

### 4.4 What vf2..vf7 actually do [b]

All six base implementations are three instructions that funnel into **`vf1`** with a distinct event
code — `vf2→1, vf3→2, vf4→3, vf5→4, vf6→5, vf7→6`:

```
0x1440de580 (vf2)  mov rax,[rcx] ; mov edx,1 ; jmp qword [rax+8]
```

and `ThinkUnitBase::vf1 = 0x1440d7b30` is the reset:

```
[this+0x28] = 1 (word: also clears +0x29) ; [this+0x2c] = 0 (qword: clears the latch AND +0x30)
[this+0x38] = 0 ; [this+0x20] = 0 (the charge) ; [this+0x19] = 0
if (evt != 7) { [this+0x24] = 0 ; [this+0x34] = 0 }
if (evt == 7 || evt == 0) [this+0x1c] = 0           ; only these two clear the PHASE
```

**vf1 is overridden by 18 of the 73 classes**, and some branch on the event code — e.g.
`0x1440e22c0` does `cmp ebx,1 ; jne skip ; mov byte [rdi+0x48], 0`. So the six codes are not
interchangeable. `vf2..vf7` themselves are never overridden (only `ThinkUnitSetplayGuide` replaces
`vf5`). [b]

> **This settles § 14.13 item 2.** `+0x10` selects *when a unit's transient state is torn down and
> the per-player active-unit lock (`player+0x1a38`/`+0x1a3c`) is released* — nothing to do with edge
> versus hold. The old chapter's warning was right for the right reason.

---

## 5. Frame order — the scheduler, found, and what is still [c]

**Both endpoints are `cobra::game::Listener` virtuals dispatched on the same event id.** [b]

```
cobra::game::ListenerManager  (with ListenerWorker / ListenerWorkerThreadGroup)
   |  broadcasts an event record; *(int*)event = the event id
   |
   +-> game_mode::MatchListener::vf1   0x1453f21d0
   |      0x1453f2272  sub eax,1 ; je 0x1453f2421      <-- EVENT ID 1
   |      0x1453f2430  call 0x14541f1d0 -> 0x14540ca60 -> 0x1453e76f0 -> 0x1453e7130
   |                                                     (the UPadInput frame writer)
   |
   +-> match::CommandListener::vf1     0x143c630a0
          0x143c630f6  sub eax,1 ; je 0x143c63178      <-- EVENT ID 1
          0x143c631f8  call qword [rax+0x28] = vf5 = 0x143c63090
          0x143c63090  mov rcx,[rcx+0x3e30] ; jmp 0x143c62220 -> 0x1440d4180
                                                        (match::Command::update)
```

`match::Command::update` is additionally gated inside CommandListener's event-1 branch: if
`0x143c5b800(cmd+0x190)` is false and a global system flag is clear it calls `0x1440d40b0` instead,
and a second flag path can skip the update entirely.

**What is still not proven.** `cobra::game::Listener`'s base ctor `0x14510f070` sets
`[this+0x108] = -1` — a priority/ordering slot, default −1 — and **neither `match::CommandListener`'s
ctor (`0x143c62cb0`) nor `game_mode::MatchListener`'s (`0x1453da1d0`) writes it**. No static
constant orders the two listeners. Their relative position in the event-1 broadcast is **runtime
registration data**, and I could not settle it from the image. [b for the absence, c for the
consequence]

**What that costs, precisely.** Less than it looks:

* The ring is a 100-frame history and every predicate is expressed as *frames ago from the cursor*.
  If `Command::update` ran before the pad write, every predicate would simply read the previous
  frame as "now" — a uniform one-frame input latency, **not a semantic change**. No law in § 1
  depends on the order.
* It *does* matter for **injection**: if you write a synthetic frame into a pad-slot block from
  outside (e.g. `tools/live_patch.py`), whether the ThinkUnits see it this tick or next tick is
  exactly this unresolved ordering. Anyone doing that should write **and then verify by observation**,
  not assume.
* It also means "UPadInput updates before match::Command::update in the same tick" stays **[c]**,
  upgraded only from "no scheduler found" to "the scheduler is `cobra::game::ListenerManager`,
  event id 1, order is runtime data".

---

## 6. `ScopedWAndC` on `UPadInput` — confirmed a no-op

The registry chapter's § 2 decoded `ScopedWAndC` as Write-And-Commit generally and predicted the
commit is a no-op on `Pointer` records. **Confirmed for this specific user, by running the game's
own commit.** [a]

```
A. commit 0x145340a10 against a synthetic registry entry
   mode=0 Pointer  (UPadInput's class)  front after commit = aaaaaaaaaaaaaaaa   UNCHANGED -> NO-OP
   mode=1 Copy                          front after commit = bbbbbbbbbbbbbbbb   PUBLISHED from back
B. write resolver 0x1453415d0   mode=0 Pointer -> FRONT (entry+0x28 'touched' = 1)
                                mode=1 Copy    -> BACK  (entry+0x28 'touched' = 1)
C. read  resolver 0x145340c80   mode=0 Pointer -> FRONT ;  mode=1 Copy -> FRONT
D. UPadInput's registrar call   0x143c62a35  xor r9d, r9d   -> mode 0 = Pointer
                                0x143c62a49  mov r8d, 0x25960 (153,952 B)
```

**Answers to the brief's question.** A runtime write into `UPadInput` — the ring, the cursor, the
slot-in-use bytes, the per-pad descriptors — **takes effect immediately for every reader and needs
no commit**, because writer and reader resolve to the same buffer. `UPadInputRef::ScopedWAndC`
(`0x1453e6150` ctor, `0x1453e67b0` dtor, commit at `0x1453e72a9`) is Write-And-Commit whose commit
degenerates to `ret`. The only side effect a raw external write skips is `entry+0x28 = 1`
("touched"); I did **not** trace who reads that flag, so "skipping it is harmless" is **not proven**.

And the pattern chains themselves are **not registry records at all** — `0x1486b88d0` /
`0x1486b8930` are plain memory past the PE's raw size — so the registry discipline does not apply to
them in either direction.

---

## 7. The trigger-run hook, verified against the bytes — **NOT BUILT, NOT WRITTEN**

> **Nothing in this section was applied. No file was written. This is a description of bytes.**

### 7.1 The headline: the binding the brief wants already ships

`ThinkUnitPassAndGo::vf17` (`0x1440e5280`) ORs two chains. Running the game's own static
initialisers with the frame rate stubbed to 60 and then the game's own evaluator over a synthetic
ring:

```
chain A @0x1486b88d0  (2 nodes)
   A[0] @0x1486b88d0  0000080008000000 000000000000000000000000…000080bf000080bf
        mask 0x00080000 (bit 19 = RT)  kind 8 NOT-HELD   +0x10=0  +0x20=-1.0  +0x24=-1.0  -> table C
   A[1] @0x1486b88f8  0000200004000000 000000000500000000000000…000080bf000080bf
        mask 0x00200000 (bit 21 = RB)  kind 4 TAP  B=5    +0x10=0  +0x20=-1.0  +0x24=-1.0  -> table C

chain B @0x1486b8930  (3 nodes)
   B[0] @0x1486b8930  bit 19 RT, kind 8 NOT-HELD
   B[1] @0x1486b8958  bit 21 RB, kind 1 PRESS-EDGE, B=0
   B[2] @0x1486b8980  bit 21 RB, kind 2 DOWN-for-A, A=5
```

```
case:                          0 never  1 tap1f/rel1  2 tap2f/rel1  3 tap2f/rel3  4 tap2f/rel5
                               5 tap4f/rel1  6 tap6f/rel1  7 held6f  8 held20f  9 held20f/rel1

SHIPPED, RT up                     0  1  1  1  0  1  1  1  0  0
SHIPPED, RT HELD                   0  0  0  0  0  0  0  0  0  0
```

**A tap of RB with RT up already fires `ThinkUnitPassAndGo`**, whose `vf12` (`0x1440e5270`) is
`mov eax, 0x47 ; ret` — **command id `0x47` = 71**. Chain B additionally fires on the *sixth* frame
of an RB hold and then stops (case 7 yes, case 8 no) because `B[1]` is a press edge with `B = 0`
searched from the index `B[2]` returned. The unit is index **71** of the 72 the factory builds,
`+0x08 = 33` (no button of its own), `+0x0c = 2`, `+0x10 = 2` (one-shot), `+0x18 = 1` (enabled), and
**no other `ThinkUnit` binds logical 21**, so RB-alone really is unclaimed. [a]

> **Before patching anything, confirm in-game that command `0x47` is not already doing what you
> want.** If PassAndGo's *effect* is wrong rather than its *trigger*, none of the edits below help.

### 7.2 Every § 14.12 constraint, checked against PRISTINE

| constraint | verdict | bytes |
|---|---|---|
| guards at `0x1486b8920` / `0x1486b89a8` | **correct** — MSVC magic-statics epoch guards | `0x1440e52c0` `39 05 5a 36 5d 04` (`cmp [0x1486b8920], eax`), `0x1440e52cf` `39 05 d3 36 5d 04`. `eax = TLS[_Tss_index][0x6d0]`; `jg` → `_Init_thread_header 0x144f7e278`, build, `_Init_thread_footer 0x144f7e218`. Write **after** the first evaluation or the initialiser overwrites you. |
| `+0x20 = +0x24 = −1.0` and `+0x10 = 0` keep the node on table C | **correct, and now load-bearing** | all five nodes carry `000080bf 000080bf` at `+0x20`/`+0x24` and `00` at `+0x10`. Setting `+0x10 ≠ 0` moves to table A; setting `+0x20 ≥ 0` moves to table B. For kind 10 **both alternatives are null pointers** (§ 1.1). |
| "count is the caller's literal (`mov r8d, 2` / `3`)" | **WRONG ENCODING** | `0x1440e52f6` is `44 8d 45 02` = **`lea r8d,[rbp+2]`**, `0x1440e5331` is `44 8d 45 03` = **`lea r8d,[rbp+3]`** (`rbp` is zeroed at `0x1440e52db`). The counts are **displacement bytes at `0x1440e52f9` and `0x1440e5334`**, not imm32s. A `mov r8d, imm` search finds nothing here — the exact gotcha in the brief. |
| target-index path `0x1440e5463` must still be reached | **correct, but the destination is misdescribed** | `0x1440e5463` `8b 5f 1c` = `mov ebx,[rdi+0x1c]` (ctx→player index), then `0x1440e546b` `41 88 5e 19` = **`mov byte [r14+0x19], bl`** where **`r14` = `rcx` = `this`, the ThinkUnit** — not a "behaviour" object. `[rdi+0x1c]` is taken only when `esi ∈ {0,2}`; otherwise a longer pass-route path (a 1.0 s window at `0x1440e53e3`, `fps + 0.5` frames) produces the index. `ThinkUnitBase::vf1` clears `+0x19`, and `vf8` reads bit 1 of it — **`+0x19` is overloaded**, so writing a player index there is PassAndGo-specific. |

### 7.3 The three candidate edits, each measured on the real chain bytes

All are **data writes into already-initialised memory**; none patches an instruction; none touches
the installed image on disk.

```
                                                     0  1  2  3  4  5  6  7  8  9
SHIPPED, RT up                                       0  1  1  1  0  1  1  1  0  0
SHIPPED, RT HELD                                     0  0  0  0  0  0  0  0  0  0
EDIT 1: chainA node[1].B  5 -> 8    (RT up)          0  1  1  1  1  1  1  1  0  0
EDIT 1: chainA node[1].B  5 -> 12   (RT up)          0  1  1  1  1  1  1  1  0  0
EDIT 2: chainA node[0].kind 8 -> 10 (RT HELD)        0  1  1  1  0  1  0  0  0  0
EDIT 2: chainA node[0].kind 8 -> 10 (RT up)          0  1  1  1  0  1  1  1  0  0
EDIT 3: chainA node[1].mask RB -> LB (ring drives RB) 0 0  0  0  0  0  1  1  0  0
```

| edit | address | current bytes | proposed bytes | effect (emulated) | risk |
|---|---|---|---|---|---|
| **1 — widen the tap window** | `0x1486b88f8 + 0x0c` = **`0x1486b8904`** | `05 00 00 00` | `08 00 00 00` (or any 1..100) | tap accepted up to `press+releaseAge ≤ B`. `B = 8` adds case 4 (2-frame tap, released 5 frames ago). `B > 100` is inert; `B ≥ 256` wraps mod 256 | low. The `0.08` constant at `0x145e87854` is read by **35 functions** — do **not** tune it instead |
| **2 — drop the "RT not held" gate** | `0x1486b88d0 + 0x04` = **`0x1486b88d4`** | `08 00 00 00` | `0a 00 00 00` (kind 10) | chain A fires while sprint is held. Chain B keeps its own RT gate unless you do the same at `0x1486b8934` | medium. `+0x10` must stay `00` and `+0x20` must stay `bf 80 00 00` (−1.0f) or kind 10 dispatches through a **null pointer** |
| **3 — retarget the button** | `0x1486b88f8 + 0x00` = **`0x1486b88f8`** | `00 00 20 00` (1<<21, RB) | any `1<<n`, `n ≤ 31` | moves the tap to another button | **high for LB.** `1<<18 = 0x00040000` collides with `ThinkUnitCursorChange`, which fires on LB's **press edge** via the inherited `vf17` — the cursor changes on frame 0, before a tap can be distinguished. Bits 32/33 can never match (§ 1.5) |

**Write order and preconditions for any of the three:**

1. The target process must already have evaluated `PassAndGo::vf17` at least once, i.e. be in a
   match with a pad-driven player, so both TLS guards have run. Writing earlier is overwritten.
2. Write only the four bytes named. Leave `+0x10`, `+0x20`, `+0x24` alone.
3. Do **not** change the node counts at `0x1440e52f9` / `0x1440e5334` — that is an instruction
   patch, and Denuvo makes the on-disk image untouchable. To *shorten* a chain, overwrite the
   unwanted node's kind with **10** (proven to work, § 1.3 and EDIT 2 above); to *lengthen* one
   there is no data-only route.
4. No commit is needed (§ 6) — these bytes are not a registry record.
5. There is no known way to verify this statically. **Test it in-game and be ready to restart**;
   `tools/live_patch.py`'s `probe` is the existing runtime write path.

---

## 8. Corrections to `registry-pad-command-channel.md`

1. **§ 14.6 — kinds 1 and 3 are swapped in the prose.** "kind 1 (release edge) and kind 3 (press
   edge)" is wrong: **kind 1 = press edge** (`0x14430d830`), **kind 3 = release edge**
   (`0x14430d980`). The correction paragraph immediately below it, which says kind 4 calls
   `0x14430d980` for the release then `0x14430d830` for the press, is right — the two statements
   contradict each other in the same section. [a + b]
2. **§ 14.6 — kinds 8 and 9 are not "level tests evaluated at the anchor frame".** They are region
   tests over **`[0, start]`** — the whole span the chain has already consumed — tolerating **at
   most one** contrary frame. "RT not held" in PassAndGo means *RT was up for the entire gesture*,
   not *RT is up right now*. [a]
3. **§ 14.6 — the evaluator's `start` is the search origin, and § 14.6's "bound" in the kind-4
   formula is that same `start`.** The law is `B > pressIdx − start − 1`. [b]
4. **§ 14.9 — "5 rows, more exist behind branches this emulation did not take" is wrong about the
   cause.** `0x1440d8b20` has **no conditional branches**; it always writes **16 rows into three
   tables**. The missing 11 were in two tables the old emulation never looked at
   (`0x148698e50`, `0x1486a3720`). Also: this is the **feint / skill-move** table, consumed by
   `ThinkUnitFeint::vf8`, and two of its rows (`T2[1]`, `T2[2]`) are gated permanently off. [a + b]
5. **§ 14.6 — the node `kind` field ranges 0..13, not 0..10.** Kinds 11/12/13 exist, have builders,
   and are handled by a **second evaluator** (`0x14430fcc0`). The claim that `0x14430fb40` is the
   pattern engine is incomplete. [b]
6. **§ 14.12 — "`count` is the caller's literal (`mov r8d, 2` at `0x1440e52f6` / `3` at
   `0x1440e5331`)".** The addresses are right; the encoding is `lea r8d,[rbp+N]`
   (`44 8d 45 02` / `44 8d 45 03`). [b]
7. **§ 14.12 — "`vf17` returns a target player index in `[behaviour+0x19]`".** It is
   **`[this+0x19]`** — `r14` is the `ThinkUnit` itself (`mov r14, rcx` at `0x1440e529e`). [b]
8. **§ 14.13 item 3 — `ScopedWAndC` is no longer "suggestive, not proof"** for `UPadInput`: it is
   emulated as a no-op (§ 6). (The registry chapter had already superseded this; § 6 supplies the
   numbers.) [a]

---

## 9. Negatives and honest not-proven

1. **The relative order of the pad write and `match::Command::update` within one tick is still not
   proven.** The scheduler is identified (`cobra::game::ListenerManager`, event id 1) and the
   priority slot is `Listener+0x108`, default −1, but **no listener ctor writes it**. The ordering is
   runtime data. § 5 says what that costs.
2. **`0x14430ffa0`, the stick-group matcher for kinds 11/12/13, is not decoded.** Its role is [b] by
   call site and buffer shape; its predicate is unknown.
3. **`0x144118530` — the T2-vs-T3 selector in `ThinkUnitFeint::vf8` — is not decoded.** "Assisted
   versus advanced control scheme" is [c].
4. **The feint gesture table's command ids (`0x08`, `0x0a`, `0x0c`, `0x0f`, `0x12`, `0x15`, `0x17`,
   `0x19`, `0x1b`, `0x1c`, `0x1d`) are not mapped to named skill moves.** Only PassAndGo's `0x47` is
   pinned, from `vf12`.
5. **The `+0x19c` gate bits `0x02`, `0x04`, `0x08` are named by their stack slots, not decoded.**
   Each is set by an anime/ball classifier call chain I did not follow (`0x1443122e0`,
   `0x144312240`, `0x144311c90`, `0x1443084d0`).
6. **`entry+0x28` ("touched"), set by the write resolver, has no traced reader.** Whether skipping it
   with a raw external write into `UPadInput` matters is **not proven**.
7. **Phase 4 of the `+0x1c` machine (`vf15`) has no entry path** in `ThinkUnitBase::vf8`'s transition
   code. Something else must set `+0x1c = 4`; I did not find it.
8. **Guard values after initialisation are not emulated.** § 7.2's guard claim is [b] from the
   disassembly of the MSVC epoch pattern only; my runs called the two builder blocks directly and
   never executed the `gs:[0x58]` TLS read.
9. **I did not test any edit in § 7.3 in the running game.** Every row in that matrix is the game's
   own evaluator over a synthetic ring, not observed behaviour.

---

## 10. Reproduction

All scripts are read-only over `eFootball.exe.PRISTINE`, in this probe's scratchpad.

| script | what it produces |
|---|---|
| `pademu.py` | the shared Unicorn harness (ring builder, node writer, stubs for `0x14533ea80` and the security cookie) |
| `kinds.py` | the builder control, the 11-kind matrix, the `start` sweep (§ 1.2) |
| `chain.py` | PassAndGo's real chains through `0x14430fb40`, the kind-10 substitution test, the table-A/B null-dispatch negative control (§ 1.1) |
| `gesture.py` | all 16 feint rows from all three tables, at 60 and 30 fps (§ 3.1) |
| `wandc.py` | the commit / write-resolve / read-resolve emulation (§ 6) |
| `hook.py` | the § 14.12 constraint check and the three-edit matrix (§ 7) |
| `factory.py` | the ThinkUnit factory re-run, used only for PassAndGo's slot/mode and the "nobody binds 21" check |
| `scan10.py` | every reader of `[unit+0x10]`, and every builder's call-site count |
