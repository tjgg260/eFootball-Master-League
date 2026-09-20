# Control source, and human vs CPU — probe `control-source-and-human-vs-cpu` (2026-09-20)

Closes §14.13 items 4 and 5 of [registry-pad-command-channel.md](registry-pad-command-channel.md)
and OPEN 8 / OPEN 14 of [ball-carrier-brain.md](ball-carrier-brain.md).

Evidence levels: **a-emulated** / **b-disassembly** / **c-inferred**. All addresses are VAs at base
`0x140000000`, decoded and emulated from `eFootball.exe.PRISTINE`. Nothing was written to the game,
to `tools/`, or to the installed image.

---

## 1. The headline, in five sentences

1. The "15-way jump table" is **not 15 ways**. `0x1440d4a08` has 15 entries pointing at **three**
   addresses: code 0 and 14 to a no-op, codes **1..11** to the full pad branch, codes **12..13** to
   a reduced pad branch. [b]
2. The whole dispatch runs inside a loop over the **8 hardware pad slots**, not over the 24 players.
   A player with no pad bound never reaches it. [b]
3. The code is a **ControlMode**, produced by `0x1440d31a0` and latched in a 32-byte per-player
   record at `match::Command + 0x2b4dc + idx*32` by `0x1440d6e00`. Its top-level branch is a single
   byte: `UMatchInfo + 0x41f6 + onPitchIdx`. [b]
4. That byte means **"this on-pitch player is inside his side's human-control allocation"**. It is
   computed as `positionRank[idx] <= controlCount[team]`, with the cursor player forced to rank 0.
   [a-emulated]
5. **`match::ai::bp` (BallPlayer) activation requires that same byte.** So the human's carrier does
   run the carrier brain — he is the one player guaranteed to satisfy the gate. [b]

---

## 2. `match::Command::update` (`0x1440d4180`) — the real shape

```
rdi  = 0x1442d6cc0()            -> 24 controller entries, stride 0xd0      (a global: [g+0x3c8])
rbp' = 0x1442d6de0()            -> UMatchInfo                              (a global: [g+0x580])
reset 24 x 0xb4 command slots at this+0x40 via 0x1443081e0(slot, 0xb)
flags[24] = 0                   (local byte array at rbp-0x10)

FOR padIdx = 0 .. 7:                                  <-- 0x1440d472c..0x1440d4739, `cmp al, 8`
    ebx = first entry e in 0..23 with e->[+8] == padIdx        ; else next padIdx
    onPitch = e->[+0x10] if <= 0x15                            ; else e->[+0x14] if <= 0x15
                                                               ; else 0xff
    0x1440d6e00(this, ebx, onPitch)                            ; ControlMode state machine
    rec  = this + 0x2b4dc + ebx*32
    mode = *(int*)rec
    if (mode != 0 && mode < 15) flags[ebx] = 1
    padBase = 0x140eaece0(this+0x2b900)                        ; UPadInput
    if (mode > 14) goto tail
    switch (mode) via table 0x1440d4a08

FOR i = 0 .. 23:  if (flags[i] == 0)  CommandPlayer[i]->vf2()  ; <-- CLEAR, see section 6.4
0x1440d5480 / 0x1440d6a00 / 0x1440d51c0
UCommandOutput::ScopedWrite ... 0x1440deb90
```

**The jump table, dumped from the image** (`0x1440d4a08`, 15 x u32 rva): [b]

| ControlMode | target | what it is |
|---|---|---|
| 0 | `0x1440d46e7` | nothing — falls straight to the per-pad tail |
| 1,2,3,4,5,6,7,8,9,10,11 | `0x1440d4356` | **FULL PAD branch** |
| 12,13 | `0x1440d460c` | **REDUCED PAD branch** |
| 14 | `0x1440d46e7` | nothing |

### The FULL PAD branch, `0x1440d4356`

* `padBlock = UPadInput + padIdx*0x1908` (`0x1440d435b`) — the pad chapter's one traced branch.
* `ctx->+0x31` ("is primary") `= (0x1442ca070(entries, class) == ebx)`, where the class comes from
  `entry[0]`: 0 to class 0, 2 to class 1, anything else means not primary. [b]
* `ctx->+0x30 = (byte[0x14431a5d0(padBase, padIdx)] == 1)` — the **18-byte per-pad assignment
  descriptor** at `UPadInput+0x258c8+padIdx*18` (pad chapter §14.2), its byte 0. So a hardware
  property of the pad assignment reaches every ThinkUnit. [b, new]
* builds the ThinkContext (`0x1440d7010`) and calls `CommandPlayer::vf3` (`vt+0x18`).
* then, only on this branch, the **post-processing block** `0x1440d44df..0x1440d45d3`: the
  `Screen2dInfo` read (`this+0x2f670`), the `UMatchInfo+0x34a0 ∈ {3,4,5}` set-piece test, two pad
  predicates on logical buttons `0x15` and `0x14`, and `0x144308420`.

### The REDUCED PAD branch, `0x1440d460c` (modes 12, 13)

Byte for byte the same pad binding (`padIdx*0x1908`, `0x14431a5d0`, `0x1440d7010`,
`CommandPlayer::vf3`), with exactly three differences: [b]

1. an entry gate — `[0x14807ffe0]->vf1()` and, if that is true, `0x1442c8f20(entry, 0)` must also
   be true (it consults `[0x14807ffe0]->vf17` against `byte[entry+2]` when `entry[+4] & 0x10`);
2. `ctx->+0x31` ("is primary") is hard-coded **0**;
3. the whole post-processing block is skipped.

### The post-loop fallback — the only place a ControlMode is written by hand

`0x1440d47d6: mov dword [rdx], 0xc`. When no pad-bound entry produced a command this frame
(`esi == 0`) and `[0x148080e20]->vf2()` is true, `match::Command::update` picks the entry bound to
the **primary hardware pad** (`0x1449fa550` wrapping `0x143b3e120()`, clamped to 0 when >= 8),
force-writes its ControlMode to **12**, and runs `CommandPlayer::vf3` with `padIdx = 0xff`. [b]

---

## 3. The ControlMode record — 32 bytes at `match::Command + 0x2b4dc + idx*32` [b]

Written by `0x1440d6e00(this, idx, onPitchIdx)`:

| off | meaning |
|---|---|
| `+0x00` | **current ControlMode** |
| `+0x04` | the raw mode just returned by `0x1440d31a0` (before the gauge override) |
| `+0x08` | the previous ControlMode (copied here on every change) |
| `+0x0c` | frames in the current mode (`inc`, zeroed on change) |
| `+0x10` | frames-in-mode counted only while `0x1440d70c0(rec)` |
| `+0x14` | frames-in-mode counted only while `0x1440d70a0(rec)` |
| `+0x18` | frames-in-mode counted only while `0x1440d70c0(rec)` (second counter, zeroed if false) |
| `+0x1c` | frames-in-mode counted only while `0x1440d7080(rec)` |

**The three class predicates over `rec[0]`** (each is `mov edx,[rcx]` then a chain of `sub`): [b]

| fn | true for ControlMode |
|---|---|
| `0x1440d7080` | **1, 2, 3** |
| `0x1440d70c0` | **1, 2, 3, 4, 6** |
| `0x1440d70a0` | **5, 7, 8** |

`0x1440d7070` (`mode-1 <= 8`, i.e. 1..9) is the "a real player is being driven" test used elsewhere.

`0x1440d6e00` also contains the one surviving debug call in this band:
`"[Command] Change ControlMode by gage used [%s] (gage used %s)"` (`0x146b9df58`), fired when the
mode is forced to **2** because `[playerObj+0x1a78] < 0x51` while `UMatchInfo+0x3308 == 1`; three
further tests on `[playerObj+0x37c]`, `+0xd8c`, `+0x40c` force the mode to **5**. Modes 2 and 5 are
therefore the "a command gauge is being used" states. [b]

---

## 4. `0x1440d31a0` — where the ControlMode comes from

```
r15 = entry[+0x10] if <= 0x15 else entry[+0x14] if <= 0x15 else 0xff     ; the cursor player
bl  = (byte[UMatchInfo + 0x41f6 + r15] != 0)                             ; THE discriminator

if 0x1442e2010(UMatchInfo)                       -> 14     ; [UMatchInfo+0x429c] in {3,4}
else if (bl == 0):
        if r15 <= 0x15                           -> 10
        else if entry[+4] & 8                    -> 11
        else if entry[+4] & 4                    -> 13
        else if 0x1442ca830(entry)               -> 12
        else                                     ->  0
else:  the cursor/situation analysis             -> 1..9   (6 for the set-piece kicker paths)
```

The `bl != 0` half is ~880 instructions of cursor logic. It is **not** decoded here; what is decoded
is that it only ever yields modes **1..9**, and that the reasons are named by 93 dead debug strings
surviving in `.xcode` at `0x146b9d3c0..0x146b9e5e0`, e.g.
`"[Command] ControlMode [%s] (freekick & main kicker)"`, `"...(team ai is defence)"`,
`"...(my dribble(or trap) touch after)"`, `"...(fix or semiFix cursor & gk & team offence)"`,
`"...(cross & pass get)"`, `"...(next keep is myside GK)"`. **None of them is referenced by code** —
the calls were compiled out — so they name the *reasons*, not the codes, and no `%s` name table was
found. Mapping reason to code needs the full 880-instruction trace and is **not done**.
[b for the strings; not-proven for the mapping]

Related surviving strings in the same band name three ControlMode *families* by word —
`KEEP MODE`, `FOLLOW MODE`, `DEFENCE MODE` (`0x146ba2318..0x146ba2b90`) — and three continuation
messages, `"continue [PRESS] input"`, `"continue [KEEPER PRESS] input"`, `"continue [MATCHUP]
input"` (`0x146b9e530..0x146b9e5e0`). Matching those three families onto the predicate classes
{1,2,3} / {5,7,8} / {4,6} is **tempting and unproven** — recorded as a lead, not a finding. [c]

---

## 5. `UMatchInfo + 0x41f6[idx]` — the human/CPU byte, decoded

### 5.1 962 readers, exactly one writer [b]

An instruction-aware `disp32` sweep of `.xcode` for displacement `0x41f6` returns **962
instructions in 669 functions**; **961 are reads** (`cmp byte [base + idx + 0x41f6], 0`, inlined all
over the match code) and exactly one is a write:

```
0x1442c5360:  cmp edx, 0x16
              jge  ret
              movsxd rax, edx
0x1442c5368:  mov byte ptr [rax + rcx + 0x41f6], r8b      ; setControlFlag(UMatchInfo, idx, val)
              ret
```

22 entries (`idx <= 0x15`), one per on-pitch player. A second, parallel 22-byte array sits
immediately after it at `+0x420c`, computed the same way by `0x1443088a0`.

### 5.2 The per-match initialiser proves what it holds [b]

`0x1442cb020` (called from the `MatchOnline` band: `0x14540b780` twice and `0x145408e20`):

```
for team = 0..1:
    for slot = 0..10:
        idx = 0x144300ba0(team, slot)          ;  = team*11 + slot
        val = (0x144308db0(X, idx, UMatchInfo) != 0)
        0x1442c5360(UMatchInfo, idx, val)      ;  0x41f6[idx] = val
```

and `0x144308db0` is:

```
if (byte[X + 0xf297]) return byte[X + 0xf26b + idx];         ; per-player override array
count = (idx <= 10) ? [X+0x3c] : [X+0x40];                   ; per-TEAM control count
rank  = table[sel][ orderPosition(idx) ];                    ; 1..11, from one of three tables
if (UMatchInfo+0x3308 in {2,3})                              ; only in those match states
    if (idx == [UMatchInfo+0x41d8] || idx == [UMatchInfo+0x41dc]) rank = 0;  ; the cursor players
return rank <= count;
```

The three rank tables (22 x i32 each), read straight out of the image: [b]

| table | team 0 (idx 0..10) | team 1 (idx 11..21) |
|---|---|---|
| `0x146c11eb0` | 11,10,9,8,7,6,5,4,3,2,1 | 1,2,3,4,5,6,7,8,9,10,11 |
| `0x146c11f10` | 1,2,3,4,5,6,7,8,9,10,11 | 11,10,9,8,7,6,5,4,3,2,1 |
| `0x146c11f70` | 1,11,10,9,8,7,6,5,4,3,2 | 1,2,3,4,5,6,7,8,9,10,11 |

Selected by `[X+0x14]` (non-zero gives `f10`) and `[X+0x18]` (`==1` gives `f70`, else `eb0`).
`f70`'s leading `1` on the goalkeeper slot is a "you play as the keeper" ordering.

### 5.3 Emulated, with the game's own bytes [a-emulated]

`scratchpad/emu_flag.py` runs the real `0x144308db0` under Unicorn against a synthetic `X` and
`UMatchInfo`, stubbing only the squad-order accessor `0x1442ee640` (returns the identity order
0..10) and `0x1442c4430` (returns `0xff`). Selector `[X+0x14] = 1`, i.e. table `0x146c11f10`.

```
c0= 11 c1=  0   team0 idx0-10 [1,1,1,1,1,1,1,1,1,1,1]
c0=  3 c1=  3   team0 idx0-10 [1,1,1,0,0,0,0,0,0,0,0]
c0=  1 c1=  0   team0 idx0-10 [1,0,0,0,0,0,0,0,0,0,0]
c0=  0 c1=  0   team0 idx0-10 [0,0,0,0,0,0,0,0,0,0,0]
c0= -1 c1= -1   team0 idx0-10 [0,0,0,0,0,0,0,0,0,0,0]

cursor override, counts 0/0, UMatchInfo+0x3308 = 2:
  [0x41d8]= 0 -> idx0  alone flagged
  [0x41d8]= 5 -> idx5  alone flagged
  [0x41d8]=10 -> idx10 alone flagged
  [0x41d8]=13 -> nothing flagged in team 0   (side-matched: 13 is a team-1 index)
```

The rule is exactly `rank <= count`; `count = -1` flags nobody at all, `count = 0` flags only the
cursor player. **The team-1 column of that run is an artefact of the stub** (my squad order was
team-0 identity for both teams) and is not a finding.

### 5.4 What it means, and what is *not* proven

`0x41f6[idx] != 0` means **"on-pitch player `idx` is inside his side's human-control allocation"**
(plus the cursor player, in match states 2 and 3). The rank tables, the per-team count, the
"GK first" ordering variant and the cursor override together admit no other reading: a byte that is
forced true for the player under the user's cursor cannot mean "CPU".

**NOT PROVEN:** the runtime values of `[X+0x3c]` / `[X+0x40]` in a real single-player match. No
writer of those two fields was located (`89 51 3c` / `89 51 40` appear nowhere in
`0x144300000..0x144320000`; they arrive by whole-record copy or from outside that band). So
"the CPU team's count is 0 or -1, therefore no CPU player is ever flagged" is **[c], not [b]**.

---

## 6. The answers

### 6.1 Does a human-controlled carrier also run `match::ai::bp`? — **YES** [b]

`BallPlayer`'s activation test `0x1456516d0` — its only caller is the PRE-PASS function
`0x145653b90` at `0x145653cc1`, and its result is the **only** place `BP+0x10` (the "active" byte
the decision loop's step 1 requires) is set to 1 — contains:

```
0x14565180f: lea  rcx, [rsp + 0x50]
0x145651814: call 0x14173d320                       ; the player index
0x145651819: cmp  eax, 0x15 ; ja  fail
0x145651824: cmp  byte ptr [rax + rsi + 0x41f6], bl ; rsi = 0x1442d6de0() = UMatchInfo, bl = 0
0x14565182b: je   fail
```

`match::ai::bp` therefore activates **only** for players the human-control allocation covers, and
the player under the human's cursor is *always* covered (section 5.2: rank forced to 0, or rank 1
with count >= 1). The human's carrier runs the brain. `ball-carrier-brain.md` OPEN 8's first half is
closed.

The mirror of that statement is the uncomfortable one: **`match::ai::bp` does not activate for
players outside the allocation**, which on the [c] reading of 5.4 means the CPU team's carrier never
runs it. This chapter does **not** claim that as proven — it claims the gate, which is [b], and
names the missing link (`[X+0x3c]` / `[X+0x40]` at runtime).

Recorded honestly: `BP+0x10` is **sticky**. When the activation test fails it is cleared only if
`0x1442c7f30(0x1442d6dc0(match))` and `BP+0x30 == 0` and a player-record bit
(`byte[0x1442d6ba0(match,idx)+8] >> 5 & 1`) is set (`0x145653cd0..0x145653d0d`); otherwise the
previous value stands.

### 6.2 `match::Player + 0x7f49` — **the writer is found**, and it is not a pad flag [b]

`match::Player` is the 0x19178-byte container (`0x144143700` allocates, `0x144140fd0` constructs,
`match::Player` vftable `0x146bc0550` at `+0`). `match::Player::vf9` (`0x144144790`) resets its
sub-objects and names their bases:

```
0x1441447bf: lea rcx, [rdi + 0x7660] ; call 0x14415cf00     <-- 0x900 bytes, ends at 0x7f60
0x1441447cb: lea rcx, [rdi + 0x7f60] ; call 0x144110240     ; three 0x1ab0-byte objects:
0x1441447d7: lea rcx, [rdi + 0x9a10] ; call 0x144110240     ;   0x7f60 / 0x9a10 / 0xb4c0
0x1441447e3: lea rcx, [rdi + 0xb4c0] ; call 0x144110240
```

So `Player + 0x7f49` is **`(Player + 0x7660) + 0x8e9`**. Sweeping displacement `0x8e9` over
`.xcode` gives ten sites; those on this object are:

| site | in | what |
|---|---|---|
| `0x14415cf42` | `0x14415cf00` (the sub-object's reset, called from `Player::vf9`) | init |
| `0x14415bb9c` | `0x14415b850` | `= 0` |
| `0x14415bbef` | `0x14415b850` | `= 1` |
| `0x1441474bd` | `0x144147410` | object-to-object copy |
| `0x14415d2dc` (read) | `0x14415d280` | copies it to `entity+0x1a81` |

`0x14415b850` and `0x14415d280` are called back to back (`0x14424595a`, `0x144245968`) from
`0x1442457c0`, whose only caller is **`0x14414a340`** — the per-player TICKER named in
`ball-carrier-brain.md`. So the byte is recomputed every tick **for every `match::Player`**, with no
control-source gate anywhere in the chain. [b]

The rule inside `0x14415b850` (`rsi` = the `+0x7660` sub-object, `rbx = 0x1442d6ba0(match, idx)` =
the player's current-action record, `r13->+0x20` = the pending command byte, `r12b =
0x1442e2a60(match, idx)`):

```
CLEAR (=0)  when  byte[rbx] == 0x22
            or    (UMatchInfo+0x3308 != 1 and 0x144311e20(byte[rbx]))
SET   (=1)  when  0x144311e20(byte[rbx])                      ; the same action-class test
              and word[rbx+0x1e] <= word[rbx+0x1a]            ; the same window the bp activation uses
              and !((dword[rbx+8] >> 17) & 1)
              and ( (pendingCommand & 0x7f) == 0x44  or  0x1442e2a60(match, idx) )
            ; and then 0x144339120(rsi+0x14)
```

**`Player+0x7f49` is an action/command latch, not "pad-controlled".** `ball-carrier-brain.md`'s
"if `Player+0x7f49` is pad-controlled, the human's carrier never sees the CPU list" world is
therefore **eliminated**, and OPEN 14 closes as a *negative*: the divert to the move-only path
`0x145651100` is not a human/CPU switch, it is "a committed kick action is in flight".

### 6.3 Assistance settings — **partial** [b for the option list, not-proven for the wiring]

eFootball 2027's control assistance is not a numeric "assist level". The reflection enum
`EKeyConfigAdvancedOptionsChoice` (strings at `0x146177430..0x146177768`) lists exactly:

```
CHOICE_CONTROL_STYLE, CHOICE_CURSOR_CHANGE, CHOICE_CURSOR_NAME,
CHOICE_MANUAL_CURSOR_CHANGE_TYPE, CHOICE_PASS_SEARCH, CHOICE_TACKLE_TYPE,
CHOICE_SHOOT_TYPE, CHOICE_CHOP_TOUCH_TYPE, CHOICE_BALL_COURCE,
CHOICE_CURSOR_CHANGE_TARGET, CHOICE_PASS_SEARCH_GUIDE, CHOICE_TARGET_GUIDE,
CHOICE_POSITIONNING, CHOICE_FEINT_TYPE
```

plus `EKeyConfigPlayerMoveType::{PLAYER_MOVE_TYPE_STICK, PLAYER_MOVE_TYPE_KEY}` and
`EKeyConfigCustomType::{CUSTOM_TYPE_ATTACK, CUSTOM_TYPE_DEFENCE}`. Control Style is a first-class
online property (`EMatchingOptionControlStyleFilter`, `m_isLimitControlStyle`,
`m_isEnableControlStyleFiltering`) — i.e. Advanced vs Standard, the game's assistance toggle.

**What is proven about where they enter:** nothing in `match::Command::update`, `0x1440d31a0` or
`0x1440d6e00` reads any of them; the ControlMode and the ThinkUnit evaluation are identical
regardless. The command is produced first; whatever assistance changes must be downstream. The most
likely landing zone, **not verified**, is the per-entry settings sub-record at `entry + 0x5c`
(`0x144317460` reads `byte[entry+0x5c+0xe]`; `0x141993aa0(entry+0x5c, 4)` writes
`byte[entry+0x5c] = 4`) and the `UCommandOutput` side-arrays (section 7). **Assist to COMMAND vs
EXECUTION is therefore NOT answered**; the one concrete negative is that it is **not** the
ControlMode.

### 6.4 Is CPU input synthesised through the pad channel? — **NO** [b]

Two independent facts:

1. The dispatch loop is `for padIdx in 0..7` and only processes an entry whose `+8` equals that pad
   index (`0x1440d42a0..0x1440d42b7`). A player with no hardware pad bound is never dispatched.
2. Every entry that did **not** get a ControlMode in 1..14 has `flags[i] == 0`, and the post-loop
   sweep `0x1440d4854..0x1440d48c9` calls `CommandPlayer::vf2` on it. `vf2` is `0x1440de4f0`, and it
   is a **pure clear**:

```
0x1440de4f0: xor eax, eax
             mov dword [rcx+8],  0xff          ; no player
             mov dword [rcx+0x24], 0xbf800000  ; -1.0f
             mov qword [rcx+0x10], 0 ; byte [rcx+0x18], 0 ; qword [rcx+0x2c], 0
             mov qword [rcx+0x34], 0 ; dword [rcx+0x3c], 0 ; qword [rcx+0x1c], 0
             add rcx, 0x40 ; jmp 0x1440dbcc0   ; clear the 0x51-slot unit array
```

**Consequence for the mod:** every pad-level lever in the pad chapter — ThinkUnit button bindings
(`unit+0x08`), the `+0x10` mode, the pattern-node chains at `0x1486b88d0` / `0x1486b8930`, the tap
law's window B — affects **only players bound to a hardware pad**. It cannot reach a CPU team, and
it cannot reach your own ten off-ball players either.

---

## 7. Layout facts recovered on the way [b]

* `UCommandOutput` interior, relative to `this+0x40`: 24 x `0xb4` command slots (`0x1443081e0`
  resets one, `0x144308140(base, idx)` fetches one) = `0x10e0` bytes, then
  `byte[24] @ +0x10e0` (`0x1443081d0` get / `0x144308420` set),
  `byte[24] @ +0x10f8` (`0x1443081c0` get / `0x1443083f0` set),
  `byte[24] @ +0x1110` (`0x1443083f0`'s second store),
  `dword[24] @ +0x1128` (`0x144308410` set).
* **Command-descriptor table `0x146c19004`, stride 20 bytes**, indexed by command id, field 0 is a
  class code: `0x144318200(id) = *(int*)(0x146c19004 + id*20)`. `match::Command::update` accepts
  classes 3 and 4 at `0x1440d44a8` before recording a target.
* Command ids seen as literals in this band: `0x41` (`0x1440d44c2`) and `0x44` (`0x14415bb77`,
  `0x14415bbe6`); ids carry flags in the top bits (`>= 0xf8` is invalid, `& 0x7f` is the id).
* `0x144300ba0(team, slot) = team*11 + slot`, `0xff` out of range. `0x1442df990(idx)` is the
  inverse side test (`idx < 11` gives 0, `< 22` gives 1).
* `match::CommandPlayer` vtable `0x146ba0620`: `vf0 = 0x143b35b70`, `vf1 = 0x1440ddc50`,
  `vf2 = 0x1440de4f0` (clear), `vf3 = 0x1440de590` (think).
* `match::Player` container sub-objects, from `Player::vf9`: `+0x940` BallPlayer (0x6ce8),
  `+0x7660` (0x900), `+0x7f60` / `+0x9a10` / `+0xb4c0` (three x 0x1ab0, same ctor `0x144110240`),
  `+0x15a30`, `+0x15e48`, `+0x18ad8`, `+0x18d10` PlayerInfoRef.
* **`match::CommandPlayer` is NOT embedded in `match::Player`.** The 24 of them are heap-allocated
  at `0x1440d4a80` (`mov ecx, 0x1c10 ; call 0x140e999a0 ; call 0x1440dd750`) and stored in
  `match::Command + 0x2b7e0`.
* `0x1442d6de0()` returns `[g + 0x580]` and that object **is** `match::registry::UMatchInfo` — the
  same object `0x1442c5360` writes through a `MatchInfoRef`. Its `0x41xx` band is the control block:
  `+0x41cc` situation, `+0x41d8`/`+0x41dc` the two cursor player indices, `+0x41e0..+0x41f0` the
  random seeds written by `0x1442c5380`, `+0x41f6[22]` and `+0x420c[22]` the control arrays.

---

## 8. Corrections this probe forces

1. **To `registry-pad-command-channel.md` §14.1 / §14.10** — "a 15-entry jump table" reads as 15
   behaviours. It is 15 *entries* over **three** targets, and the two live ones differ only in the
   "is primary" flag, an entry gate and the post-processing block. [b]
2. **To `registry-pad-command-channel.md`'s ThinkContext table** — the struct `0x1440d7010` writes
   is `+0x00 padsys, +0x08 controlRecord(arg5), +0x10 entry(arg7), +0x18 &padBlock(arg6),
   +0x20 entryIdx, +0x24 onPitchIdx, +0x28 float(arg9), +0x2c int(arg8), +0x30/+0x31/+0x32 bytes`.
   The chapter has `+0x08 &padBlock`, `+0x10 entry`, `+0x18 record`, `+0x20 player index`. The
   argument-slot arithmetic (caller `[rsp+0x20]` = arg5 = callee `[rsp+0x28]`) gives the first. **But
   the context the ThinkUnits actually see is a different, re-packed struct**: in
   `ThinkUnitSuperCancel::vf13` (`0x1440e5580`), `ThinkUnitCursorChangeManual::vf16` (`0x1440e7500`)
   and `0x1440e4d20`, `[ctx+0x08]` is dereferenced by the pad predicate `0x144310750`
   (`mov rcx,[rcx]` then `0x14431a5b0`), so it is `&padBlock`; and `[ctx+0x20]` is an **int compared
   against 1 and 5 and passed to `0x1440d7080` / `0x1440d70a0`**, so it is the **ControlMode**. The
   repack happens between `CommandPlayer::vf3` (`0x1440de590`) and `0x1440db1c0`, which this probe
   did not trace. **One of the two labelings is wrong and I did not resolve which.**
3. **To `registry-pad-command-channel.md` §14.11** — "CPU side `0x1442d0050` / `0x1442d12d0`,
   nearest `CpuDynamicObject`". `CpuDynamicObject` is `Enlighten::CpuDynamicObject`, a **global
   illumination** class (vftable `0x1473404a0`). "Nearest vtable" picked a lighting symbol; there is
   no `match::Cpu*` class in the RTTI at all. That row must not be read as evidence of a CPU command
   path.
4. **To `registry-pad-command-channel.md` §14.13 item 4 and `ball-carrier-brain.md` OPEN 14** — the
   writer of `Player+0x7f49` is located (6.2). "No writer on any base in 0x7f00..0x7f60" was correct
   and was the right conclusion from the wrong frame: the field is at `+0x8e9` of the sub-object at
   `Player+0x7660`.
5. **To `ball-carrier-brain.md`'s activation paragraph** — `byte[match+0x41f6+idx]` is glossed there
   as "the player is on the ball". It is the **human-control-allocation byte** (section 5). That
   single relabel is what answers OPEN 8.

---

## 9. Negatives and honest not-proven

1. **The CPU does not receive synthesised pad input.** `CommandPlayer::vf2` is a clear. [b]
2. **No assistance setting reaches `match::Command::update`.** Proven by exhaustion over the three
   functions in the chain; where it *does* land is **not** proven. [b for the negative]
3. **ControlMode 1..9 are not individually named.** 93 debug strings name the *reasons*; the `%s`
   name table is gone; the 880-instruction analysis was not traced. [b for the strings]
4. **`[X+0x3c]` / `[X+0x40]` have no located writer.** Everything about "the CPU team's count is 0"
   is [c]. This is the one link between "bp is gated on the human-control byte" [b] and "bp never
   runs for the CPU" [c].
5. **The `+0x420c` sibling array** (computed by `0x1443088a0` from the same counts but override
   array `X+0xf281`) is not decoded. It is read together with `+0x41f6` in at least `0x1442cabe0`.
6. **The unit-level ThinkContext repack** (`0x1440de590` to `0x1440ddd40` to `0x1440db1c0`) was not
   traced; see correction 2.
7. **`0x1449fa550`'s `0x143b3e120()`** is taken as "primary hardware pad index" from its use and its
   `cmp eax, 8` clamp. [c]
8. **`UMatchInfo+0x3308`** takes values 1, 2, 3 and gates the cursor override; "1 = open play" is
   inherited from `ball-carrier-brain.md` and is still [c]. Since the cursor override only applies in
   states 2 and 3, the value of `0x3308` in normal play materially changes 5.4 — worth pinning next.
9. **The `+0xd634` twin.** `0x14430a020` / `0x14430b320` / `0x1442f3a70` each write
   `byte[obj + idx + 0xd634] = v` **and** `0x41f6[idx] = !v` through a `MatchInfoRef`, so `0xd634`
   is the complement of the human-control byte on some team/config object. Its name is not
   established, and `0x143cb74f0`'s mask `0x503ff800` (bits 11..21, plus inert 28 and 30) marking
   indices 11..21 is a setup path I did not follow to its caller.

---

## 10. Reproduction

All read-only over `eFootball.exe.PRISTINE`, in the probe scratchpad:

| script | what it does |
|---|---|
| `bpx.py`, `funcs.py` | copies of the toolrepo helpers (chained-unwind extents, xref index) |
| `dscan.py` | instruction-aware `disp32` sweep, back-decoding to a real boundary |
| `fscan.py` | fast ranged `disp` sweep over a VA window; prefers the **longest** back-off so REX prefixes are not dropped (the first version reported `lea ecx,[rdi+0x7f60]` and hid the sub-object that cracked `+0x7f49`) |
| `ann.py` | annotated function dump with resolved RIP-relative string contents |
| `strfn.py` | strings referenced inside every function in a sweep result |
| `emu_flag.py` | **the Unicorn proof of 5.3** — real `0x144308db0` bytes, synthetic world |

Two method notes worth carrying forward:

* `dscan.py`'s first hit on the `0x41f6` writer decoded as `mov byte [rax+rcx+0x41f6], al` at
  `0x1442c5369`. The real instruction is `mov byte [rax+rcx+0x41f6], r8b` at `0x1442c5368` — the
  backward decode had dropped the REX byte. Exactly the "plausible nonsense from a bad start
  address" failure the brief warns about; it cost one wrong register name and nearly cost the
  `Player+0x7660` sub-object.
* `emu_flag.py`'s team-1 column is constant 0 across every input. That is a **stub artefact**
  (the squad-order stub returned a team-0 order for both teams), not a saturated closure and not a
  finding; only the team-0 column is evidence.
