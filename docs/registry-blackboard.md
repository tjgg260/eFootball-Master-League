# The blackboard — `match::registry` (2026-09-19)

Where every subsystem's shared state lives, who publishes it, and who reads it. **218 RTTI names
resolve to exactly 45 data records** wrapped in `Ref` / `ArrayRef` / `ScopedRead` / `ScopedWrite` /
`ScopedWAndC` accessor templates. Nothing in here decides anything: this chapter is a **struct
catalogue**, a **per-match tactics landing map**, and the **pad→command channel** the trigger-run
feature needs.

Produced by one hand-decoded skeleton (the registrar, the size proof, the Copy-vs-Pointer
discipline, the array dimensions and the `UTeamAIInfo` identification — all kept below) plus four
workflow probes run the same day: `tactics-landing-map`, `inventory-completion-and-seams`,
`random-bundle-and-lifecycle` and `pad-to-command-channel`. Where two probes disagreed, or where a
probe contradicted the skeleton, **the disputed bytes were re-read with capstone from PRISTINE for
this write-up** and the resolution is stated inline (§ 15). Every constant in § Tunables was put
through `tools/exe_census.py cell <va> --all` **for this write-up** — no probe had run it, and the
answers are in the table.

Evidence levels: **a-emulated** (the game's own bytes executed under Unicorn with controlled
inputs), **b-disassembly** (followed instruction by instruction; function extents from the
*chained-unwind* `.pdata` walk via `funcs.func_chunks`, never `func_range` and never the
touching-range merge), **c-inferred** (structural reasoning only). Addresses are VAs at base
`0x140000000`, no ASLR, decoded from `eFootball.exe.PRISTINE`.

**Patch hygiene.** The installed image differs from PRISTINE in **909 bytes across 105 runs** — our
own patches, landing in **28** distinct chained-unwind roots (48 of the 105 runs; the other 57 fall
outside `.pdata` altogether). **Three functions cited by address in this chapter contain patched bytes in the
installed image** — re-diffed for this repair pass:

| function | patched runs (installed) | cited where |
|---|---|---|
| `0x144310ea0` | `0x144311572` (3 B), `0x14431157a` (3 B) — two re-aimed `disp32` constant loads at `0x14431156e` / `0x144311576` | an analog/stick helper; **nothing decoded here calls it** (its only callers are `0x143ea5734`, `0x1441098f0`, `0x14410c5b5`) |
| `0x1441a4280` | `0x1441a43b9` (2), `0x1441a43cf` (2), `0x1441a58be` (3), `0x1441a58d9` (4) | § 5.3, as one of the instruction-query call sites (executor band) |
| `0x143df6010` | `0x143df6f12` (3) | § 5.3, as one of the instruction-query call sites (`ChanceSpaceRun` band) |

None of those bytes is load-bearing for any claim below — everything here was read from PRISTINE —
but **do not re-verify those three against an installed exe**. (The earlier text said "exactly one
run group lands anywhere near this subsystem" and gave the second `disp32` as `0x144311579`; both
were wrong. [b, full image diff re-run]) Everything below is PRISTINE. [b]

Companion chapters: [match-ai-decoded.md](match-ai-decoded.md) (off-ball movement),
[ball-carrier-brain.md](ball-carrier-brain.md) (the carrier's brain),
[player-executors.md](player-executors.md) (the executors). **All three are corrected by this
chapter** — see § 12 before leaning on any of them.

> **Read § 12 first if you are about to tune something.** The headline result is a *subtraction*:
> `team+0xb3c4`, which `ball-carrier-brain.md` calls "the largest single on-ball lever found", is
> not a persistent setting — it is a transient CPU directive **re-evaluated every think tick**, held
> while the match mode is 1 and `teamAI+0x28d != 0` and a frame-counter timer has not expired, and it
> **has** writers, which the skeleton said it did not. Its companion
> `team+0xb44d` is not an independent field either; it is `(attackLevel >= 4)`. The one genuinely
> new channel found is `UAnalyzeInfo`'s instruction tables (271 read sites) — and **its writer is
> still not located**, so it is a named target, not yet a lever.

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| force the CPU to cross / go long / stop playing safe | `team+0xb3c4` — **NAMED**: the CPU's transient *direct-play directive*, set by `0x143d7c7f0` from `0x143d7b650`, force-cleared by `0x143d7c7d6` when the mode gate or the 7 s/14 s timer test fails, both inside `0x143d7c5b0`, called once per tick from the team-AI think `0x143d02c80` at `0x143d03150` | **no file and no table** — but a runtime write **survives** while `modeSettings+0x3308 == 1` and `teamAI+0x28d != 0` and the timer test passes (§ 6.1) | b — a removal from the *authorable* list, **not** from the runtime one (§ 6, § 12) |
| bypass the cross roll / guarantee MiddleShot's +40 | `team+0xb44d` = `(team+0xb450 >= 4)`, recomputed at `0x143d02ef0` / `0x143d02f07` every tick | **not reachable, and must not be tuned separately** — move the attack level instead | b, re-verified with capstone for this write-up |
| pin the CPU's attack level instead of letting it drift | the **setting** `team+0xb454` (0–4 fixed, **5 = AI-driven**, default 5) → converter `0x143d04830` → live level `team+0xb450` (default 2) | exe code at the reset default `0x1442eff0a`; the match-setup writer was **not** found, so the route is **unproven** | a for the defaults, b for the chain |
| a per-team tactical-instruction channel | **two of them, and neither is authorable yet.** (1) `UTeamAIInfo+0x8078`: two sets, a 0–5 approach code at `B+0xd64+set`, seven instruction bytes, two `[2][11][3]` tables. (2) `UAnalyzeInfo+0x273e8` / `+0x27490`: four `(kind, value)` slots per team, queried by `0x1442e1200` at **271 sites** | **origin not traced for either** — the only `+0x8078` writer found stores 0 or 1; the instruction tables have **no `disp32` writer at all** | b — § 6, § 5.3; the subsystem's highest-value open item |
| trigger a run from a shoulder tap (realism item 2) | the pad layer **already has an exact tap primitive**: pattern-node kind 4, matching iff **the press edge is no more than `B` frames back** (`B > pressIdx − bound − 1`, i.e. press duration **plus** release age ≤ B) with `B = (int)(0.08·FPS + 0.5)` = **5 at 60 fps** | **runtime-only**: a live-process data write to the pattern nodes at `0x1486b88d0` / `0x1486b8930`. No instruction patched, **and no file-side path exists** | a-emulated (78 evaluations) + b for the predicate; § 7 |
| bind "tap LB" to anything | **dead as specified.** `ThinkUnitCursorChange` is logical button 18 = LB, overrides only vtable slot 12 (`0x1440e20b0` = `mov eax,0x37; ret`) and therefore triggers on the inherited `ThinkUnitBase::vf17`, a **one-frame rising edge**. An LB tap fires Cursor Change on frame 0 | — | b, verified end to end for this write-up |
| a shoulder button that *is* free on the ball | **RB (logical 21).** No attack-bank `ThinkUnit` uses it; its only consumers are chains that also require RT state or a stick | as above | a + b, § 7 |
| make the match's randomness reproducible | `URandomInfo+0x18`, the match master seed, drawn once at `0x1453dea17` from a clock-seeded LCG | **not reachable** — the entropy is the clock (`0x143b37540` / `0x143b374c0`) | b, § 8 |
| write any registry record from an app or data file | **nothing in this subsystem is app-writable.** dt270 does not enter the blackboard at all: 0 of 268 dt270 getter sites in the registry band, and the intersection of registry-acquiring and dt270-calling functions is **2**, in both of which the values never meet | — | b, exhaustive, § 13 |
| know which record a `team+0x…` or `matchInfo+0x…` note refers to | `team` == `teamAI` == **`UTeamAIInfo`**, reached through the `Ref` embedded in `UModeInfo` whose read cache is at `+team*0x58+0x3450` — **the registry record's front buffer**, via `0x1442d7090`; `matchInfo` == `matchWork` == **`UAnalyzeInfo`** (`[mgr+0x48]` via `0x140efd260`) — and that is also the object § 6.1 once called "the constant table" | notation only | a for the first, b for the second — § 4.1, § 10 |
| patch a `Copy` record at runtime and have anyone see it | you must write the **back** buffer (`entry+0x20`, via `0x1453415d0`) and then commit (`0x145340a10`); a write to the front buffer is overwritten by the next commit, a write to the back buffer without a commit is invisible | runtime patch only | b — § 2, the single most important operational fact in the chapter |

---

## The machine in one paragraph

The registry is a `std::map<std::string, shared_ptr<URegistryData>>` at the global `0x148c22ad0`,
keyed `"GROUP:LEAF"` (`RANDOM:INFO`, `MATCH:ENV`, `COMMAND:OUTPUT`, …). Each value is a 0x40-byte
slot holding **one or two** full-size allocations of the record: one for a `Pointer` record, two for
a `Copy` record — and that `Copy`/`Pointer` bit is literally the registrar's fourth argument.
Readers resolve through `0x145340c80` and always get the **front** buffer; writers resolve through
`0x1453415d0` and get the **back** buffer on a `Copy` record, the single buffer on a `Pointer` one;
`ScopedWAndC`'s destructor — and nothing else — calls the commit `0x145340a10`, which tail-jumps the
record's own copy-assign to publish back over front. There is **no lock anywhere**: `ScopedRead` and
`ScopedWrite` "release" through `0x140c83910`, which is a single `ret`. Owners bind their `Ref`s
**once per match** (`0x1442d0050` builds 27 of them inline in `UModeInfo`'s data block; teardown is
`0x1442d62c0`), cache the raw pointer, and from then on the gameplay code works on raw pointers —
which is why **not one** of the 1,431 registry entry-point call sites lies inside any `match::ai`,
`match::ai::bp` or `match::player` vtable method. **That is an absence of API calls, not an absence
of the records.** The pointer those chapters work on *is* the registry record's front buffer:
`0x1442d7090` / `0x1442d6e20` return `[UModeInfo + team*0x58 + 0x3450]` / `+0x3500`, which the
teardown `0x1442d5500` releases with the byte-exact `ScopedRead`-destructor shape (token at
`Ref+0x48`, accessor at token−`0x38`), so those slots are the **read caches of long-lived
`ScopedRead`s on `TeamAIInfo`/`OrderInfo` `ArrayRef`s** bound once per match (§ 4.1). So the
blackboard is **on the gameplay hot path**; what is downstream is only the *publication* of
snapshots for replay and network serialisation by the stager/publisher pair (`0x1456f1ff0` →
`0x1456ea6d0`) — and that publisher is also how a value from outside the record reaches gameplay,
by committing the back buffer over the front one. `UAnalyzeInfo` (a `Pointer` record,
single-buffered, read live) carries the defensive line, the ball X and the instruction tables, and
`UPadInput` (also `Pointer`) is where every human input physically lands.
---

## 1. How a record is registered, and where records physically live

### 1.1 The registrar, and why the sizes are trustworthy [b]

Every record type has a **descriptor function** — the second method of its `?$Copy` or `?$Pointer`
accessor vtable — and every one of them calls the same registrar, **`0x145340ca0`**, with the
record's byte size in `r8d` and the Copy flag in `r9d`. `r8d` is a genuine `sizeof`, not a tag: the
registrar spills it to `[rsp+0x20]` and then uses it as the **allocation length**
(`0x1453411fa → 0x143b344d0`, result stored to `entry+0x10`) and as the **`memset` length**
(`0x1453412f8 → 0x144f8306e`). Sizes are therefore allocation-accurate. That is the skeleton's
original proof and it stands unchanged.

**One methodological correction, and it cost the skeleton four rows.** MSVC encodes a small size as
`lea r8d,[r9+imm]` when `r9` already holds 0 or 1, so a scan that matches only `mov r8d, imm` skips
it and — if it carries forward — attributes a *neighbouring* descriptor's size to the record. Two
probes found this independently; re-read from PRISTINE for this write-up:

```
0x143c4e070  UFieldInfo::?$Pointer descriptor
0x143c4e085    xor  r9d, r9d
0x143c4e0a8    lea  r8d, [r9 + 0x50]      <- 80 bytes, NOT 1,435,944
0x143c4e0b1    call 0x145340ca0
```

| skeleton said | truth | proofs |
|---|---|---|
| `UFieldInfo` = `0x15e928` (1,435,944 B) | **`UFieldInfo` = `0x50` (80 B)**. The 1.4 MB record is **`URecordInfo`** (`VRecordInfo::?$Pointer`, descriptor `0x143c4e1b0`, `mov r8d, 0x15e928` at `0x143c4e1d9`) | [b] descriptor, re-read here; [b] copy thunk `0x143c4d810` = five `movups` pairs = exactly `0x50`; **[a]** emulated — the thunk writes 80 bytes, max offset `0x4f`. Found independently by two probes |
| `URandomInfo` = `0xc0` (192 B) | **`0x1c` (28 B)** — `0x143c6a860`: `mov r9d,1` + `lea r8d,[r9+0x1b]` | [b] descriptor; [b] copy thunk `0x143c6a830`; [b] constructor `0x144322fd0` zeroes exactly `0x00..0x1b`; **[a]** emulated. **Four** independent proofs |
| `UCameraSettings` = `0x2e4` (740 B) | **`0x10` (16 B)** — `0x143c91da0`: `mov r9d,1` + `lea r8d,[r9+0xf]` | [b] ×2 probes |
| `UDemoControl` = `0x2e4` (740 B) | **`0x30` (48 B)** — `0x143c91e40`: `lea r8d,[r9+0x2f]` | [b] ×2 probes |

No record in the image has size `0xc0`, and `0x2e4` occurs exactly once — for `UDemoInfo`, whose 740
**is** correct (`0x143c91f0c mov r8d, 0x2e4`). So the three 740s were never the same value. The rest
of the skeleton's table held; `UTeamAIInfo = 0xbd8c` and `UOrderInfo = 0x4090` are now confirmed a
third way by emulating their copy functions (§ 5.1, § 5.4). [b]

### 1.2 The container: one string-keyed map [b]

The registrar is a `std::map` insert. Its `rdx` argument is the accessor object, whose `std::string`
at `+0x08` is the key; the map itself is the global **`0x148c22ad0`** (loaded at `0x145340d6e`,
`0x145340f6d`, `0x145341553`; the shared-pointer control block is
`std::…common::Registry::URegistryData::?$_Ref_count`, allocated at `0x145340edb`). Keys are built
by `0x143c4e430(accessor, group, leaf)` as `group + ":" + leaf` (the `":"` literal is
`0x145be1e54`), with **`Ref::vf1` returning the group string and `Ref::vf2` the leaf**, each a
`lea rax,[rip+d]; ret` stub. Scanning every such stub pair recovers **35 literal keys**:

`RANDOM:INFO`, `FIELD:INFO`, `MATCH:ENV`, `MATCH:INFO`, `COMMAND:OUTPUT`, `COMMAND:PLAYER`,
`PADINPUT:INFO`, `MODE:INFO`, `RECORD:INFO`, `ANALYZE:INFO`, `CURSOR:INFO`, `TRAINING:WORK`,
`PKMATCH:WORK`, `PLAYDATA:WORK`, `REPLAY:INFO`, `SCREEN2D:INFO`, `CAMERA:INFO`, `GOAL_POST:INFO`,
`CORNER_FLAG:INFO`, `CONCEPT_ARRANGE_RELEASE:INFO`, `HIGHLIGHT_RESERVE:INFO`,
`VANISHING_SPRAY:WORK`, `BALL_PERSON:INFO`, `RAGDOLL:INFO`, `SUGOROKU:WORK`, `ESPORTS:WORK`,
`PATH_TO_GLORY:WORK`, `STEPUP_TUTORIAL:WORK`, `FIXDEMO:INFO`, `MATCH:DEMO_INFO`,
`MATCH:DEMO_CONTROL`, `GENERALSETTINGS:WORK`, `SYSTEMSETTINGS:WORK`, `CAMERASETTINGS:WORK`,
`NO_OPERATION_LEAVE:WORK`.

**The array-backed records are not in that list, and their keys are NOT derivable** — see § 13.
That is a real gap and it is stated as one.

### 1.3 `URegistryData` — the 0x40-byte slot [b]

`new(0x40)` at `0x145340e67` (freed with `mov edx,0x40` at `0x1453409ee`, which fixes the size),
filled at `0x145340e80` and `0x1453411dd`:

| off | type | meaning | proof |
|---|---|---|---|
| `+0x00` | u32 | **mode**: `1` = double-buffered (`Copy`), `0` = single (`Pointer`). This *is* the descriptor's `r9d` | `0x1453411e1 mov [rsi],edi`; tested at `0x14534121c`, `0x145341326`, `0x145340a1e`, `0x1453415e2` |
| `+0x04` | u32 | set from `r12d` at `0x1453411e3`; **source register unresolved, no reader found** | b, open |
| `+0x08` | fn | deleter for buffer A (default `0x143b42f10`) | `0x145341215` |
| `+0x10` | ptr | **buffer A — the FRONT / published buffer** | alloc `0x145341202`, store `0x14534120c`, memset `0x145341316`, ctor `0x145341324` |
| `+0x18` | fn | deleter for buffer B | `0x145341239` |
| `+0x20` | ptr | **buffer B — the BACK / working buffer**, allocated only when mode == 1 | `0x14534121c cmp edi,1 / jne`; alloc `0x145341226`, store `0x145341230`; memset + ctor gated again at `0x145341326` |
| `+0x28` | u8 | "touched" — set by every write-resolve | `0x1453415de` |
| `+0x29` | u8 | buffer B initialised | `0x14534133f` |
| `+0x30` | fn | record **destructor** hook (descriptor arg 6). A no-op (`0x140c83910` or the thunk `0x14127c030`) on 39 of 45 records; real on `UTeamAIInfo` (`0x143c4da00`, destroys an 11 × 0x34 array at `+0x8f78`), `UOrderInfo`, `UAnalyzeInfo`, `VRecordInfo`, `VModeInfo` | `0x1453411eb` |
| `+0x38` | fn | the record's **copy-assign thunk**, called `(rcx = src, rdx = dst)` | `0x1453411f6` |

Argument arithmetic, for anyone re-checking: at the registrar's entry `rbp = RSP_entry − 0x48`, so
`[rbp+0x70]` = arg 5 = the **constructor** (called through `rsi` after the memset), `[rbp+0x78]` =
arg 6 → `entry+0x30`, `[rbp+0x80]` = arg 7 → `entry+0x38`.

**`Copy` vs `Pointer` *is* the double-buffer flag** — machine-checked over all 45 registrar callers:
every one of the **33** `Copy` descriptors passes `r9d = 1`, every one of the **12** `Pointer`
descriptors passes `r9d = 0`, 45 of 45, no exceptions. (The chapter first printed "30 / 15", which
contradicted its own § 3 table; re-derived here by folding `mov r8d,imm` / `lea r8d,[r9+imm]` /
`mov r9d,imm` / `xor r9d,r9d` over all 45 descriptors from PRISTINE: 33 / 12, 0 unresolved.) [b]

### 1.4 The `Ref` (0x58 bytes) and `ArrayRef` [b]

```
+0x00  Ref vtable (match::registry::<Name>Ref);  vf1 = group string, vf2 = leaf string
+0x08  u8 bound          — 0 until first use resolves the name into the accessor
+0x10  the accessor, 0x38 bytes:  +0x10 vtable, +0x18 std::string key, +0x38 URegistryData*, +0x40 ctrl
+0x48  cached READ  pointer (front buffer)  — set by ScopedRead,  cleared by its dtor
+0x50  cached WRITE pointer (back  buffer)  — set by ScopedWrite / ScopedWAndC, cleared by theirs
size   0x58  — TeamAIInfoRef::vf0 deletes with `mov edx,0x58`; ArrayRef strides 0x58
```

The inlined bind-then-acquire, verbatim from `match::RecordReplay` at `0x143caa36f` (`r14` = the
`MatchEnvRef` at `RecordReplay+0x78`):

```
cmp byte [r14+8],0 ; jne skip
  rbx = r14->vf2() ; rax = r14->vf1()
  call [[r14+0x10]+8] (r14+0x10, rax, rbx)     ; resolve record by name into the accessor
  mov byte [r14+8],1
skip:
cmp qword [r14+0x48],0 ; jne done
  lea rcx,[r14+0x10] ; lea rdx,[r14+0x48] ; call 0x145340c80
```

**`ArrayRef<N, base, Enum>` is a flat inline array, not an indirection**: `{ vtable; Ref elem[N] }`
at stride `0x58`. `ArrayRef<2, HomeAway, UTeamAIInfo>` is `0xb8 = 8 + 2*0x58` (deleting destructor
`0x143ca8e90` frees `0xb8`), and the scoped constructors/destructors are literal `add rbx,0x58`
loops with the count baked in (`0x143c642b4` for `UOrderInfo`, `0x143ca8dd6` for `UTeamAIInfo`).
Elements are built by the MSVC vector-constructor iterator `0x144f7eab4` with the index-free element
constructor `0x143c3dee0`. [b]

**The `UPlayerMove` `<22>` / `<31>` double view is explained**: two template instantiations over the
same element `Ref` type, straight from the mangled dimensions `$0BG` = 0x16 = **22**
(`0x1440ec2e0`) and `$0BP` = 0x1F = **31** (`0x143ca8e50`). `UPlayerInfo` and `UAnimeInfo` are
`$0BG` = 22 only; `UTeamAIInfo` and `UOrderInfo` are `$01` = 2 over `HomeAway`. 22 is the on-pitch
set; **why a 31-element view exists is still unexplained**. [b]

---

## 2. The access discipline — `ScopedRead` / `ScopedWrite` / `ScopedWAndC`, decoded

The skeleton returned `ScopedWAndC` undecoded and asked for a name. **It is Write-And-Commit**, and
the mechanism is the double buffer. Two probes reached this independently; the three functions below
were re-disassembled from PRISTINE for this write-up and are quoted in full.

### 2.1 The two resolvers, byte for byte [b]

```
0x145340c80  read-resolve                      0x1453415d0  write-resolve
  test rcx,rcx ; je out                          test rcx,rcx ; je out
  rax = [rcx+0x28]        ; URegistryData*       rcx = [rcx+0x28]
  test rax,rax ; je out                          test rcx,rcx ; je out
  rax = [rax+0x10]        ; FRONT, always        byte [rcx+0x28] = 1          ; "touched"
  [rdx] = rax ; ret                              cmp dword [rcx],0
                                                 jne back
                                                 rax = [rcx+0x10] ; [rdx]=rax ; ret   ; Pointer
                                               back:
                                                 rax = [rcx+0x20] ; [rdx]=rax ; ret   ; Copy -> BACK
```

| fn | returns | call sites |
|---|---|---|
| **`0x145340c80`** read-resolve | the **front** buffer, always | 439 |
| **`0x1453415d0`** write-resolve | the **back** buffer for `Copy`, the single buffer for `Pointer` | 386 |
| `0x143c4db70` write-wrapper | bind-if-needed, then write-resolve, return the pointer | 381 |
| **`0x145340a10`** commit | — (publishes) | 225 |

### 2.2 The commit, byte for byte [b]

```
0x145340a10  test rcx,rcx ; je ret          ; rcx = &accessor
0x145340a15  rax = [rcx+0x28]               ; URegistryData*
0x145340a19  test rax,rax ; je ret
0x145340a1e  cmp dword [rax],1 ; jne ret     ; mode must be 1 (Copy) — Pointer records return here
0x145340a23  rdx = [rax+0x10]                ; dst = FRONT
0x145340a27  rcx = [rax+0x20]                ; src = BACK
0x145340a2b  jmp qword [rax+0x38]            ; the record's copy thunk (rcx = src, rdx = dst)
```

The direction is read off `UMatchEnv`'s thunk `0x143c4d400`, which does `movups xmm0,[rcx]` then
`movups [rdx-0x80],xmm0` — `rcx` is unambiguously the source. So the commit is a **publish**:
back → front. (`UTeamAIInfo`'s thunk `0x143c4d7d0` swaps `rcx`/`rdx` first because `0x143c43370` is
a real MSVC `operator=` with `this` = destination; the net direction is the same.)

**The corroboration that closes it:** `entry+0x38` for `UTeamAIInfo` is `0x143c4d7d0 → 0x143c43370`
— the very copy function § 5.1 emulates, reached here from the opposite direction. For `UMatchEnv`
it is `0x143c4d400`, whose `movups` chain moves `2×0x80 + 0x50 + 8 = 0x158` = its declared size; for
`UFieldInfo` it is `0x143c4d810`, `5 × 0x10 = 0x50` = its declared size. The registrar's size column
and the commit's copy targets agree on every record checked. [b]

### 2.3 The three scopes [b]

| scope | token | resolver | buffer | what its destructor "releases" through |
|---|---|---|---|---|
| `ScopedRead` | `Ref+0x48` | `0x145340c80` | **front** `entry+0x10` | `0x140c83910` = **`ret 0`**, then clear |
| `ScopedWrite` | `Ref+0x50` | `0x1453415d0` | **back** `entry+0x20` (`Copy`) | `0x140c83910` = **`ret 0`**, then clear |
| **`ScopedWAndC`** | `Ref+0x50` | `0x1453415d0` | **back** `entry+0x20` (`Copy`) | **`0x145340a10`** — the commit — then clear |

`UTeamAIInfo`'s three destructors side by side: `ScopedRead` `0x1453e2580`, `ScopedWrite`
`0x1453f1400`, `ScopedWAndC` `0x1453e6970`. They are byte-for-byte the same shape; only the released
callee and the token offset differ. `ScopedWAndC` exists on 15 records — `UTeamAIInfo`, `UOrderInfo`,
`UMatchInfo`, `UMatchEnv`, `UCursorInfo`, `UPkMatch`, `UFixDemoInfo`, `UPadInput`, `UPathToGlory`,
`UStepupTutorial`, `USugoroku`, `UESports`, `UCameraSettings`, `UGeneralSettings`, `UTrainingWork` —
always **alongside** `ScopedWrite`, never instead of it, which is exactly what "an additional write
mode" predicts. The skeleton's observation was right; only the name was missing. [b]

### 2.4 What this means in practice — five consequences, all load-bearing

1. **There is no locking anywhere in the registry.** `0x140c83910` is literally `ret 0`
   (re-verified). No mutex, no refcount, no fence: `basic::RecursiveMutex::ScopedLock` and
   `fox::Mutex::ScopedLock` exist in the image and **no registry accessor touches either**. The
   model is single-threaded by convention and double-buffered by record class. [b]
2. **A `Copy` record written under a plain `ScopedWrite` is invisible to every reader** until
   somebody opens a `ScopedWAndC` — or calls `0x145340a10` directly — on that record. [b]
3. **Nothing ever copies front back into back.** Buffer B is zeroed and constructed once by the
   registrar and is then a persistent accumulator; a commit publishes *all* of it, never a delta, so
   a partial writer republishes its stale neighbours too. [b]
4. **`Pointer` records are written in place** and are visible immediately; the commit is a **no-op**
   on them (the `cmp dword [rax],1` early-out). A `ScopedWAndC` on a `Pointer` record — `UPadInput`
   has one — therefore does nothing. [b]
5. **GIVEN #2 is right.** "Copy = readers get a snapshot, Pointer = readers touch the live object"
   is exactly what the two resolvers implement. One probe's first draft attacked that and withdrew
   it; the cause is recorded in § 15 because the method error is worth more than the claim.
---

## 3. The complete record table — all 49 names

**The count closes at 45 records** by three agreeing counts: 45 callers of the registrar
`0x145340ca0`, 45 `?$ReferenceMobile` instantiations in `build/exe_map.json`, and 45
`match::registry::<Name>Ref` accessor classes. The skeleton's 49 included four names that are not
records; they are listed at the bottom of the table so nobody re-derives them. **All 45 now have a
proven size** — 19 of them new since the skeleton. [b]

Status grades: **layout-partial** = some offsets decoded with readers/writers; **size-only** = size,
access mode and holders only; **(+POD)** = proven flat, no internal structure to find.

| record | bytes | access | array | write templates | status | descriptor |
|---|---|---|---|---|---|---|
| `URecordInfo` | `0x15e928` (1,435,944) **corrected** | Pointer | — | read-only | size-only (+ role [c]) | `0x143c4e1b0` |
| **`UAnalyzeInfo`** | `0xed760` (972,640) | Pointer | — | read-only | **layout-partial** — § 5.3 | `0x143c51750` |
| **`UPadInput`** | `0x25960` (153,952) **new** | Pointer | — | WAndC (no-op), Write | **layout-partial** — § 5.5, fully accounted for | `0x143c62a20` |
| `UPathToGlory` | `0x1cc34` (117,812) **new** | Copy | — | Read, WAndC, Write | size-only (mode-side) | `0x143c628e0` |
| **`UCommandOutput`** | `0x13b20` (80,672) | Copy | — | Write | **size-only — no fields decoded** (§ 5.6); the two offsets previously listed here are `UAnalyzeInfo`'s | `0x143c56d60` |
| **`UModeInfo`** | `0x12c50` (76,880) **new** | Pointer | — | Write | **layout-partial** — § 4 | `0x1442d88f0` |
| `UTrainingWork` | `0xf298` (62,104) | Copy | — | WAndC, Write | size-only | `0x143c56fe0` |
| `USugoroku` | `0xe0fc` (57,596) **new** | Copy | — | WAndC | size-only (mode-side) | `0x143c4df30` |
| `UStepupTutorial` | `0xd7ac` (55,212) **new** | Copy | — | WAndC, Write | size-only (mode-side) | `0x143c6a090` |
| **`UTeamAIInfo`** | `0xbd8c` (48,524) | Copy | `HomeAway[2]` | WAndC, Write | **layout-partial** — § 5.1, § 5.2, § 6 | `0x143c4ddf0` |
| `UBallInfo` | `0x50f8` (20,728) | Copy | — | read-only | size-only | `0x143c68300` |
| `UMatchInfo` | `0x42b0` (17,072) **new** | Copy | — | Read, WAndC, Write | size-only — **36 read acquires, the most-read record in the image** | `0x143c4de90` |
| **`UOrderInfo`** | `0x4090` (16,528) | Copy | `HomeAway[2]` | WAndC, Write | **layout-partial** — § 5.4 | `0x143c4dd50` |
| `UPlayData` | `0x3308` (13,064) | Copy | — | Write | size-only | `0x144287520` |
| `UPlayerInfo` | `0x2a00` (10,752) | Copy | `PlayerNo[22]` | read-only | size-only | `0x143c62700` |
| `UCursorInfo` | `0x19f8` (6,648) **new** | Copy | — | WAndC, Write | size-only | `0x143c53c20` |
| `UScreen2dInfo` | `0x14fc` (5,372) | Copy | — | Write | size-only | `0x143c627a0` |
| `UCommandInfo` | `0x1188` (4,488) **new** | Pointer | — | Write | size-only — **netcode ingress, not the pad path** (§ 7) | `0x143c62980` |
| `UPlayerMove` | `0x670` (1,648) | Copy | `PlayerNo[22]` **and** `[31]` | read-only | size-only | `0x143c683a0` |
| `UFixDemoInfo` | `0x30c` (780) | Copy | — | WAndC, Write | size-only | `0x143c4dc10` |
| `UDemoInfo` | `0x2e4` (740) | Copy | — | Write | size-only | `0x143c91ee0` |
| `UAnimeInfo` | `0x260` (608) | Copy | `PlayerNo[22]` | read-only | size-only | `0x143c62660` |
| `UPkMatch` | `0x1b0` (432) | Copy | — | WAndC, Write | size-only | `0x143c755e0` |
| `UBallExternalForce` | `0x16c` (364) | Pointer | — | Write | size-only | `0x1441105f0` |
| `UMatchEnv` | `0x158` (344) | Copy | — | WAndC, Write | size-only **(+POD proven)** | `0x143c4dcb0` |
| `UHighlightReserveInfo` | `0x140` (320) | Copy | — | Write | size-only | `0x143c66170` |
| `UGoalPostInfo` | `0x11c` (284) | Copy | — | read-only | size-only | `0x143c56f40` |
| `UCornerFlagInfo` | `0xe0` (224) | Copy | — | read-only | size-only | `0x143c56ea0` |
| `UConceptArrangeReleaseInfo` | `0xcc` (204) | Copy | — | Write | size-only | `0x143c56e00` |
| `UReplayInfo` | `0xb8` (184) | Copy | — | read-only | size-only | `0x14410cde0` |
| `UDemoPlayerInfo` | `0x90` (144) | Copy | — | Write | size-only | `0x143cfe480` |
| `UVanishingSprayInfo` | `0x74` (116) **new** | Copy | — | read-only | size-only | `0x143c57080` |
| `URagdollInfo` | `0x58` (88) **new** | Pointer | — | read-only | size-only | `0x143c4e110` |
| `UCameraInfo` | `0x58` (88) **new** | Pointer | — | read-only | size-only | `0x143c5c860` |
| `UNoOperationLeaveInfo` | `0x58` (88) **new** | Copy | — | Write | size-only | `0x143c920c0` |
| `UFieldInfo` | `0x50` (80) **corrected** | Pointer | — | read-only | size-only **(+POD proven)** | `0x143c4e070` |
| `UGeneralSettings` | `0x3c` (60) **new** | Copy | — | WAndC | size-only | `0x143c91f80` |
| `UDemoControl` | `0x30` (48) **corrected** | Copy | — | Write | size-only | `0x143c91e40` |
| `UCameraTargetInfo` | `0x2c` (44) **new** | Pointer | — | Write | size-only | `0x14409efd0` |
| `UBallAttach` | `0x28` (40) **new** | Pointer | — | read-only | size-only | `0x14409ef30` |
| **`URandomInfo`** | `0x1c` (28) **corrected** | Copy | — | Read, Write | **layout-partial — fully field-mapped**, § 8 | `0x143c6a860` |
| `UESports` | `0x14` (20) **new** | Copy | — | WAndC | size-only | `0x143c62840` |
| `USystemSettings` | `0x10` (16) **new** | Copy | — | Write | size-only | `0x143c92020` |
| `UCameraSettings` | `0x10` (16) **corrected** | Copy | — | WAndC | size-only | `0x143c91da0` |
| `UBallPersonInfo` | `0x1` (1) **new** | Pointer | — | read-only | the C++ empty class — its `entry+0x38` copy hook is `0x140c83910` (`ret`), the only record with no real copy | `0x143c4dfd0` |
| `UBallPerson` | — | — | — | — | **NOT A RECORD** — name-parsing alias of `UBallPersonInfo` | — |
| `UBallInfoOne` | — | — | — | — | **NOT A RECORD** — `ArrayRef` element alias of `UBallInfo` | — |
| `UBallAttachOne` | — | — | — | — | **NOT A RECORD** — `ArrayRef` element alias of `UBallAttach` | — |
| `URegistryData` | `0x40` | — | — | — | **NOT A RECORD** — the registry's own slot type (§ 1.3), reached only through `std::_Ref_count<common::Registry::URegistryData>` | — |

Three corroborations of "`r8d` is a real `sizeof`", worth keeping: `UBallPersonInfo` = 1 byte is the
C++ empty class; `UCameraInfo`, `VRagdollInfo` and `VNoOperationLeaveInfo` are all `0x58` and all
three share the constructor `0x143c4d990`, a `0x58`-byte zero-fill; and the staging container's
strides (`0xbd8c`, `0x4090`) are independent witnesses to two of the largest sizes. [b]

**Counts: 0 records fully decoded, 6 layout-partial, 38 size-only, 1 trivially complete
(`UBallPersonInfo`)** — the grades as the table above actually carries them (the earlier "7 / 37"
counted `UCommandOutput`'s two offsets, which are `UAnalyzeInfo`'s). The six layout-partials are
`UAnalyzeInfo`, `UPadInput`, `UModeInfo`, `UTeamAIInfo`, `UOrderInfo` and `URandomInfo`, and
**`UOrderInfo`'s grade covers its addressing only** — not one field offset inside the slot record is
decoded, so do not read that row as a field map. Nothing here has a complete field map, and it would be dishonest to imply
otherwise.

### 3.1 The registry key of every record — `GROUP:LEAF`, 35 recovered, 45 reconciled [b]

The natural primary key of a `std::map<std::string, …>` is its key, and the chapter did not print
one. Recovered by reading `vf1` (group) and `vf2` (leaf) of all 45 `match::registry::<Name>Ref`
classes out of `build/exe_map.json` and dereferencing the `lea rax,[rip+…]; ret` literal:

| record | key | record | key |
|---|---|---|---|
| `UAnalyzeInfo` | `ANALYZE:INFO` | `UMatchEnv` | `MATCH:ENV` |
| `UBallPersonInfo` | `BALL_PERSON:INFO` | `UMatchInfo` | `MATCH:INFO` |
| `UCameraInfo` | `CAMERA:INFO` | `UModeInfo` | `MODE:INFO` |
| `UCameraSettings` | `CAMERASETTINGS:WORK` | `UNoOperationLeaveInfo` | `NO_OPERATION_LEAVE:WORK` |
| `UCommandInfo` | `COMMAND:PLAYER` | `UPadInput` | `PADINPUT:INFO` |
| **`UCommandOutput`** | **`COMMAND:OUTPUT`** | `UPathToGlory` | `PATH_TO_GLORY:WORK` |
| `UConceptArrangeReleaseInfo` | `CONCEPT_ARRANGE_RELEASE:INFO` | `UPkMatch` | `PKMATCH:WORK` |
| `UCornerFlagInfo` | `CORNER_FLAG:INFO` | `UPlayData` | `PLAYDATA:WORK` |
| `UCursorInfo` | `CURSOR:INFO` | `URagdollInfo` | `RAGDOLL:INFO` |
| `UDemoControl` | `MATCH:DEMO_CONTROL` | **`URandomInfo`** | **`RANDOM:INFO`** |
| `UDemoInfo` | `MATCH:DEMO_INFO` | `URecordInfo` | `RECORD:INFO` |
| `UESports` | `ESPORTS:WORK` | `UReplayInfo` | `REPLAY:INFO` |
| `UFieldInfo` | `FIELD:INFO` | `UScreen2dInfo` | `SCREEN2D:INFO` |
| `UFixDemoInfo` | `FIXDEMO:INFO` | `UStepupTutorial` | `STEPUP_TUTORIAL:WORK` |
| `UGeneralSettings` | `GENERALSETTINGS:WORK` | `USugoroku` | `SUGOROKU:WORK` |
| `UGoalPostInfo` | `GOAL_POST:INFO` | `USystemSettings` | `SYSTEMSETTINGS:WORK` |
| `UHighlightReserveInfo` | `HIGHLIGHT_RESERVE:INFO` | `UTrainingWork` | `TRAINING:WORK` |
| | | `UVanishingSprayInfo` | `VANISHING_SPRAY:WORK` |

**The reconciliation is 35 + 9 + 1 = 45**, and it corrects § 13.16 (see there):

* **35** records return a static literal group **and** leaf.
* **9** return a NULL group (`vf1 = 0x140c837d0`, `xor eax,eax; ret`) with a static leaf:
  `UAnimeInfo` (`…:ANIMEINFO`), `UBallAttachOne` (`…:INFO`), **`UBallExternalForce`** (`…:BALL`),
  `UBallInfoOne` (`…:INFO`), `UDemoPlayerInfo` (`…:DEMO_PLAYER_INFO`), `UOrderInfo` (`…:INFO`),
  `UPlayerInfo` (`…:INFO`), `UPlayerMove` (`…:MOVE`), `UTeamAIInfo` (`…:INFO`).
* **1**, `UCameraTargetInfo`, returns an **instance** string: `vf1 = 0x140efd270` =
  `lea rax,[rcx+0x58]; ret`, i.e. the group lives in the `Ref` object itself at `+0x58`.

---

## 4. `UModeInfo` is the blackboard's *source* side, and the publish path

### 4.1 The records `UModeInfo` hands out — the registry's own front buffers [b]

`UModeInfo` is `0x12c50` = 76,880 bytes, **`Pointer`**, and a global caches its data pointer at
**`0x1486bd888`**. It is not a leaf record: it **embeds the registry `Ref`s** for the per-team
records and hands out their cached **front-buffer** pointers.

> **CORRECTION, applied in this repair pass.** This section used to say `UModeInfo` "holds the
> **live, authoritative** per-team records that the registry later publishes snapshots of", and § 10.2
> used to add that "the state those chapters read is mostly not the registry copy at all". **That is
> wrong, and it inverted the chapter's own reasoning.** § 4.3 already argues, correctly, that
> `g+0x790` is a `Ref+0x48` read cache; `+0x3450` and `+0x3500` are the same construct. The proof is
> the teardown loop, `0x1442d5500` (exactly one call site image-wide, `0x1442d1ebd`), which walks them with the
> **`ScopedRead` destructor's exact shape** — token at `Ref+0x48`, released object at token−`0x38`:
> ```
> 0x1442d5896  lea rdi,[rbx+0x3450] ; 0x1442d58a2  mov esi,2          ; the ArrayRef<2> pair
> 0x1442d58a7  cmp [rdi],r15 ; je ; 0x1442d58ac lea rcx,[rdi-0x38] ; call 0x140c83910 ; mov [rdi],r15
> 0x1442d58b8  cmp [rdi+0xb0],r15 ; je ; lea rcx,[rdi+0x78] ; call 0x140c83910 ; mov [rdi+0xb0],r15
> 0x1442d58d1  add rdi,0x58 ; loop      0x1442d58db  lea rdi,[rbx+0x35b0] ; mov esi,0x16  ; the <22> arrays
> ```
> compared with `ScopedRead::~ScopedRead` `0x1453e2580` (`rdi=[rcx+8]`; `cmp [rdi+0x48],0`;
> `lea rcx,[rdi+0x10]`; `call 0x140c83910`; `mov [rdi+0x48],0`) — token `+0x48`, accessor `+0x10`,
> i.e. token−`0x38`. `ScopedWrite`'s dtor `0x1453f1400` uses `+0x50` and token−`0x40` and does **not**
> match. And `0x1442d0050` builds exactly those `Ref`s: `lea rcx,[rdi+0x3408]`, `[rdi+0x34b8]`,
> `[rdi+0x3568]` at `0x1442d09a8` / `0x1442d09cf` / `0x1442d09f6`, and `0x3408+0x48 = 0x3450`,
> `0x34b8+0x48 = 0x3500`, `0x3568+0x48 = 0x35b0`. **So the "live object" and the registry record's
> front buffer are the same memory**, bound once per match through a `ScopedRead` that is released
> only at teardown. (A reviewer reached the same conclusion from the teardown but also asserted that
> `0x1442d0050` "touches nothing in `0x3300–0x3600`" — that half is **false**, those three `lea`s are
> there, and they make the case stronger, not weaker.) [b]
>
> **Two consequences.** (1) The blackboard **is** on the gameplay hot path for team state; § 10.1's
> measurement (no registry *entry-point call* inside those vtable bodies) is correct and reproduces
> exactly — only its interpretation changes, to "the decision code reads the front buffer through a
> pointer cached at bind time". (2) The double-buffer discipline is therefore directly load-bearing
> for tuning: a write to the **front** buffer is what gameplay reads, until the next commit
> republishes the back buffer over it.

| accessor | returns | meaning |
|---|---|---|
| `0x1442d7070(modeInfo, team)` | `[modeInfo + team*0x58 + 0x3450]` | **the `UTeamAIInfo` front buffer for that team**, via the `TeamAIInfoRef ArrayRef<2>`'s read cache |
| `0x1442d7090(team)` | the same, loading the global itself | the form gameplay actually calls — **hundreds of call sites** |
| `0x1442d6e20(modeInfo, team)` | `[modeInfo + team*0x58 + 0x3500]` | the same for `UOrderInfo` |
| `0x1442d6de0()` | `[[0x1486bd888] + 0x580]` | the match-settings object: `+0x3308` mode, `+0x3318` (a proven **frame counter**), `+0x331c`, **`+0x3320` a second frame-scale counter, NOT a difficulty threshold** (§ 6.1), `+0x34a0`/`+0x34a4`, `+0x41cc`/`+0x41d0`, `+0x41f6`, `+0x42b8` |
| `0x1442d6fe0(modeInfo)` | `[modeInfo + 0x200]` | the player/entity container |
| `0x1442d6fc0()` | `[[0x1486bd888] + 0x790]` | the cached `URandomInfo` **front** buffer (§ 8) |
| `0x1442d6d80()` | `[[0x1486bd888] + 0x63d0]` | a constant-table object |
| `0x1442d88d0()` | bool | "is a match live" |

Re-read from PRISTINE for this write-up:

```
0x1442d7070  cmp edx,2 ; jae fallback ; movsxd rax,edx ; imul rax,rax,0x58
             mov rax,[rax+rcx+0x3450] ; ret
0x1442d6fc0  mov rax,[rip+0x43e68c1]  ; = [0x1486bd888]
             mov rax,[rax+0x790] ; ret
```

The `0x58` stride is the `Ref` size (§ 1.4) and `+0x48` of a `Ref` is its cached read pointer, so
`+0x3450` and `+0x3500` are the read caches of `Ref` pairs embedded in `UModeInfo`. **Every
`team+0x…` read in all three finished chapters goes through `0x1442d7090`, i.e. touches the
`UModeInfo`-embedded `Ref`'s cached pointer — which is the registry record's front buffer, not a
separate object.** [b]

### 4.2 The publish path [b]

```
UModeInfo[team].UTeamAIInfo --0x143c43370--> staging+0x1388+team*0xbd8c --0x143c43370--> registry UTeamAIInfo[team]
UModeInfo[team].UOrderInfo  --0x1456e9e20--> staging+0x18ea0+team*0x4090
                       (stager 0x1456f1ff0)                        (publisher 0x1456ea6d0, loop 0x1456eacf0)
```

* **`0x1456f1ff0` — the stager.** `rdi = [0x1486bd888]`; `0x145717f00` memcpys `0x1380` bytes from
  `[modeInfo+0x3c8]` into `staging+0`; then for `team = 0,1`: copy `0x1442d7070(modeInfo,team)` into
  `staging+0x1388+team*0xbd8c` (call at `0x1456f2090`), propagate `byte[staging+0xa8] →
  [staging+0x100]`, and copy `0x1442d6e20(modeInfo,team)` into `staging+0x18ea0+team*0x4090` (call
  at `0x1456f20ad`). The staging container is `{ 0x1380 bytes; UTeamAIInfo[2]; UOrderInfo[2]; … }`.
* **`0x1456ea6d0` — the publisher.** It opens a `VTeamAIInfoRef::ArrayRef<2,HomeAway>` `ScopedWrite`
  and, for each team whose guard dword `[rdi] != 0xff`, copies `staging+0x1388+team*0xbd8c` into the
  live registry record (`0x1456ead04`); strides `r14 += 0xbd8c`, `rsi += 8`, `rdi += 4`, count
  `r13d = 2` set at `0x1456ea7c2`. `0xff` means "skip this team this frame".
* **`0x145709ba0` — replay/rewind**, a jump-table dispatcher (`0x14570a148`) that copies
  `UTeamAIInfo` between two staging containers (`0x145709cad`) and drives the state (de)serialisers
  `0x145706710` and `0x145700570`. Not part of the live path — it is where every `0x1457…` writer of
  `+0xb3c4`, `+0xb44d`, `+0xb450` comes from.

**The (de)serialisers are a free field-order oracle.** `0x145706710` and `0x145700570` walk their
target structure field by field *in declaration order*, reading 24-byte value nodes from `[rdx+8]`
with a cursor at `[r8]`. Anyone decoding `UCommandOutput`, `UMatchEnv` or the tactics block should
look for their serialiser first. [b]

### 4.3 Lifecycle: bound once per match [b]

The object at `*0x1486bd888` **embeds 27 registry `Ref`s inline**, constructed by `0x1442d0050`
(vtable / flag / accessor vtable / empty key string each). The `RandomInfoRef` sits at `+0x748`, so
`g+0x790` is its `Ref+0x48` read cache — which is exactly what `0x1442d6fc0` returns, with no scope
at all. Every per-record getter in that band has the same shape (`0x1442d7000` → `g+0x7e8`, …).
Teardown is **`0x1442d62c0`**, which clears `g+0x268`, `g+0x528`, `g+0x790` and then runs a
`0x58`-stride loop from `g+0x5928`.

`0x1453dc560` is the **match (re)start** routine, not a per-frame publisher: it calls `0x1442d6aa0`
(→ `0x1442d0050`, rebuilding the holder) and then performs write-resolve-then-commit for about
thirty records — **32 write-resolves and 49 commits, the largest such block in the image**.
`0x14543c550` (27 W / 30 C) and `0x1454132f0` (23 C) are the same shape for other phases;
`0x14543eea0` is the mirror-image read pass (27 read-resolves). [b]

**Consequence, and it is the honest answer to "what is the per-frame order":** because records are
bound once and read through cached raw pointers, **there is no per-frame re-resolution**, so frame
order cannot be recovered from resolve sites at all. See § 9.
---

## 5. Record layouts

### 5.1 `UTeamAIInfo` — `team` and `teamAI` are this record [a]

The skeleton established the identification by disassembly (`0x143c43370` walking 646 offsets to
`0xbd88` = size−4). It is now **measured**. `0x143c43370` (chained extent
`0x143c43370..0x143c45487`) was run under Unicorn over PRISTINE, with the source record first built
by its own initialiser `0x1442efda0` so the embedded sub-objects are valid, and the destination
pre-filled with `0xAA`:

```
0x143c43370(dst, src):  wrote 48,287 bytes
                        lowest offset 0x0, highest offset 0xbd8b   ( == 0xbd8c - 1 )
                        every written byte byte-identical to the source
                        zero bytes written past the record end
```

A function that writes exactly up to `size−1` of a structure and nothing beyond is that structure's
copy. **`team`, `teamAI` and `UTeamAIInfo` are the same base across all four chapters.** [a]

> **CORRECTION, and it was a harness bug, not a property of the game.** The first run of this
> emulation reported **13,619** bytes and the chapter concluded "the copy is **selective** — 13,619
> of 48,524 bytes, not a `memcpy`", and from that, that `+0xb4c`, `+0xb50` and the whole `+0x8078`
> tactics block "are not in the copy". **All of that was an artefact.** `0x143c43370` contains two
> unconditional, straight-line `memcpy` calls that the harness silently skipped, because the thunk
> resolves to an unimplemented import:
> ```
> 0x143c44332  lea rdx,[rdi+0x778]   0x143c44340  lea rcx,[rbx+0x778]
> 0x143c4434d  mov r8d,0x7900        0x143c44503  call 0x144f8307a   ; 30,976 B: 0x778 .. 0x8078
> 0x143c44508  lea rcx,[rbx+0x8078]  0x143c4450f  mov r8d,0xe6c
> 0x143c44515  lea rdx,[rdi+0x8078]  0x143c4451c  call 0x144f8307a   ; 3,692 B: 0x8078 .. 0x8ee4
> ```
> `0x144f8307a` is `jmp [rip+0xa7a7a0]` → IAT slot `0x1459fd820` = **`VCRUNTIME140.dll!memcpy`**
> (resolved from the PE import directory; `0x144f8306e` → `0x1459fd750` = `memset`, as § 1.1 says).
> `0xb4c` and `0xb50` lie inside `[0x778, 0x8078)`; `0x8ddc` lies inside `[0x8078, 0x8ee4)`. **Re-run
> with both import thunks hooked** (`emu6`, this repair pass), the copy moves **48,287 bytes**, max
> offset `0xbd8b`, nothing past the record, every byte identical to the source — and `+0xb4c`,
> `+0xb50` and `+0x8ddc` all arrive **SAME**. 13,619 was the scalar-store total alone; 13,619 +
> 30,976 + 3,692 = 48,287 exactly, and a static coverage check confirms the two `memcpy` ranges do
> not overlap any of the 652 non-indexed scalar stores. [a]
>
> **Standing method note, earned here:** a Unicorn harness must fail loudly on an unhooked import
> thunk. This one mapped RET pages on demand, so a missing `memcpy` looked like a *finding*.

So the copy is **essentially the whole record** — 48,287 of 48,524 bytes, 237 untouched (padding and
holes) — by 652 non-indexed scalar store sites plus the record's indexed array loops plus
`memcpy(dst+0x778, src+0x778, 0x7900)` and `memcpy(dst+0x8078, src+0x8078, 0xe6c)`:

| field | in the copy? | evidence |
|---|---|---|
| `+0x204`, `+0xb3bd`, `+0xb3c4`, `+0xb44d`, `+0xb450`, `+0x8f4c`, `+0xbd88` | **yes** | [a] values arrive identical |
| `+0xb4c`, `+0xb50` | **yes** — inside the first `memcpy` | [a] re-run with `memcpy` hooked: `src=3 dst=3`, `src=1 dst=1` |
| the `+0x8078` tactics block (§ 5.2) | **yes** — the second `memcpy` covers it entirely | [a] `+0x8ddc`: `src=3 dst=3` |

> **Method warning, and it nearly produced a confident wrong answer.** With a *pseudorandom* source
> the same call runs off the end of the record — 48,774 bytes touched, max offset `0xbe8b`, i.e.
> **256 bytes past** the record — because the copy walks embedded lists whose counts come from the
> source. With a zeroed source it faults on a null embedded pointer. Build the source with the
> record's own initialiser first. [a]

**`0x1442efda0` is `UTeamAIInfo::reset`, not a second copy.** The skeleton read it as an independent
witness "walking the same object to the same `0xbd88`"; it is a straight-line default initialiser
with **no `rdx` source operand anywhere**, which merely happens to end at
`mov dword [rbx+0xbd88], 6` (`0x1442f01ee`). The conclusion the skeleton drew from it is correct and
is confirmed above by emulation; only that one supporting witness was mis-read — and correcting it
is a gain, because the initialiser is the source of the whole default table. [b]

Emulated on a zeroed buffer (with `0x1442e47f0`, `0x1442c59d0`, `0x144345ae0` stubbed to `ret` and
`0x144f8306e` implemented as `memset`), it writes **nothing past `0xbd8c`** and yields:

| offset | default | offset | default |
|---|---|---|---|
| `+0x204` | **1** | `+0xb44d` | 0 |
| `+0x208` | 0 | `+0xb44e` | 0 |
| `+0x20c` | 2 | **`+0xb450`** | **2** — live attack level |
| `+0xb4c` | 0 | **`+0xb454`** | **5** — attack-level *setting*; 5 = AI-driven |
| `+0xb50` | 0 | `+0xb458` | 1 |
| `+0xb3bd` | 0 | `+0xb45c` | 8 |
| `+0xb3c0` | 0 | `+0xb460` | 4 |
| **`+0xb3c4`** | **0** | `+0xb464` | 2 |
| `+0x8078` block | 0 | `+0xb468` | 7 |
| `+0x8f4c+4i`, i<11 | 0 | `+0xbd88` | 6 |

It also lays out the per-outfielder arrays in one 11-iteration loop at `0x1442eff80`: dword arrays
at `+0x054+4i`, `+0x25c+4i` (= `1.0f`), `+0x590+4i`, `+0x5bc+4i`, `+0x684+4i`, `+0x6b0+4i`,
`+0x6dc+4i`, `+0x714+4i`, `+0x74c+4i`, `+0x91bc+4i` (= 5), `+0xbcbc+4i`, `+0xbcec+4i` and
**`+0x8f4c+4i`** (the off-ball runner action-id array `match-ai-decoded.md` documents); byte arrays
at `+0x080+i`, `+0x244+i`, `+0x66c+i`, `+0x677+i`, `+0x708+i`, **`+0xb442+i`**, `+0xb478+i`; a word
array at `+0xb42c+2i`. `+0xb442..+0xb44c` being an 11-byte per-player array is exactly why `+0xb44d`
sits where it does. [a for the values, b for the loop shape]

**The decoded field table** (readers marked *per chapter* come from the three finished chapters):

| offset | type | meaning | readers | writers |
|---|---|---|---|---|
| `+0x128` | u32 | **not decoded** — output of the sub-analyser at `think+0x1968`. Default 5 | not enumerated | `0x143d02e67` (from `[think+0x1974]` after `0x143d4b990`); `0x1442f00f9` (=5, reset) |
| `+0x204` / `+0x208` | u32 / u32 | **not decoded** — outputs of the sub-analyser at `think+0x6340`, *not* settings. `+0x204` default 1; gates Lilux (≤0), Lilux's duration, MiddleShot's +70 (==3) and three PassForward-filter branches | `0x145652960`, `0x145676830`, `0x145677a70`, `0x145678fb8`, `0x145690200` (×3) — 14 sites in 12 fns | `0x143d02e28` (from `[think+0x6358]`), `0x143d02e41` (`+0x208` from `[think+0x6354]−[think+0x6350]`); `0x1442efe73` writes the qword `{1,0}` in reset |
| `+0x740` | u8, 4/5/6 | derived from the **other** team's attack level (0→4, ≤1→5, else 6), only when `matchSettings+0x34a4 == teamIdx` and `matchSettings+0x34a0−4 ≤ 1` | not enumerated | `0x143d02ecb`; `0x1442f0110` (word `0x0104`, reset) |
| `+0x7bc8` / `+0x7bcb` / `+0x7bce` / `+0x7bd1` | u8[3] each | per-selector tallies of the outfielders' tactics-block values, counted through `0x1442ee600` into four buckets | not enumerated | `0x143d030e9`, `0x143d030f4`, `0x143d030ff`, `0x143d0310a` in the think's loop at `0x143d03030` |
| `+0x8078` | composite ~0xd70 | **THE PER-TEAM TACTICS BLOCK** — § 5.2 | ~120 `lea r,[team+0x8078]` sites | ctor `0x1442c01a0`, defaults `0x1442c0840`, `0x1454023ac`, deserialiser `0x145706710` |
| `+0x8f4c+4i`, i<11 | u32[11] | the off-ball runner action-id array (`match-ai-decoded.md`) | per that chapter | `0x1442effd5` in reset; travels in the copy |
| `+0xb3bd` | u8 | **not decoded.** One byte per think tick, the return of `0x143d0f290(modeInfo, teamIdx)`. Default 0 | `0x145659209`, `0x14565aaee`, `0x14565ab6f`, `0x14565abb6` (the carrier's pre-decide helpers `0x1456590d0` / `0x145659c20`) | `0x143d03561`; `0x143c44ab1` (copy); `0x145700c02` (replay) |
| `+0xb3be` | u8 | "directive active" mirror — set to 1 whenever `+0xb3c4 != 0` at the end of `0x143d7c5b0`; also set/cleared earlier in the same function on its **own frame timer**, the same `int(FPS·secs + 0.5)` vs `modeSettings+0x3320` shape (`0x143d7c640`–`0x143d7c666`, `0x143d7c6a4`–`0x143d7c6bf`), with `secs` defaulting to `5.0f` | `0x143d7c5cb` (its own gate) | `0x143d7c825` (=1), `0x143d7c673` (=0), `0x143d7c70a` (=1); `0x1442efed6` (=0, reset) |
| **`+0xb3c4`** | u32, 0/1/2 | **the CPU's transient DIRECT-PLAY DIRECTIVE** — § 6 | Cross `0x14567b587`, Long `0x14567b8f7`, Safety `0x1456770eb`, pass helpers `0x14568db11`/`0x14568dc41`, dribble helper `0x1456aa193`, Humiliating `0x1456c784e`/`0x1456c7c32`, plus its own tests `0x143d7c625`/`0x143d7c725`/`0x143d7c782`/`0x143d7c80d` | **`0x143d7c7f0`** (SET), **`0x143d7c7d6`** (CLEAR), `0x143c44ad6` (copy), `0x145703bce` (replay), `0x1442efedd` (`mov qword [rbx+0xb3c0], r15` in reset — zeroes it at a *different* displacement) |
| `+0xb3c8` / `+0xb3cc` / `+0xb3d0` | u8 flag; two u32 player indices (`0xff` = unset) | up to two designated players, chosen by scanning the 11 outfielders for `[matchSettings+0x41f6+idx] != 0` and `[team+0x42b8+4i] ∈ {7,9}`, gated on `0x1442d7090(team)+0x7a0d == 2` | not enumerated | `0x143d033c5`, `0x143d033ea`, `0x143d033f4`, `0x143d033fe` — all in the think |
| `+0xb442 .. +0xb44c` | u8[11] | a per-outfielder byte array zeroed by reset — the reason `+0xb44d` sits where it does | not enumerated | `0x1442f0027` in `0x1442efda0` |
| **`+0xb44d`** | u8 bool | **DERIVED: `(attackLevel >= 4)`.** Bypasses the cross score and roll, guarantees MiddleShot's +40. Default 0 | Cross `0x14567b286`, `0x14567b594`; MiddleShot `0x145678fae`; CurveShot `0x145678780`, `0x145678ae6`; Long `0x14567b8a5`; EarlyCross `0x14569ce38`; `0x145655b8b`, `0x14568fabe`, `0x14569546c` | `0x143d02ef0` (clear), `0x143d02f07` (set); `0x143c44d30` (copy); `0x145700c7e` (replay); `0x1442efeee` (**word** store covering `+0xb44d`/`+0xb44e`, reset) |
| `+0xb44e` | u8 bool | **DERIVED: `(attackLevel <= 0)`** — the low-end mirror | not enumerated | `0x143d02f15` (clear), `0x143d02f2c` (set) |
| **`+0xb450`** | **u32**, 0..4 | the **LIVE attack level** — the off-ball run-quota driver. Recomputed every think tick. Default 2 | 101 read sites in the gameplay range, incl. `0x1442f9a90` (quota lookup) and `0x143d02e9c` (feeds `+0x740`) | `0x143d048f4`, `0x143d04a4d`, `0x143d04bb2` (converter `0x143d04830`); `0x143c44d49` (copy); `0x145703c02` (replay); `0x1442efef6` (=2, reset) |
| **`+0xb454`** | u32, 0..4 or 5 | the attack-level **SETTING**. 0–4 pins the level; **5 = "the AI drives it"**, and 5 is the shipped default | `0x1442ee5f0` — literally `mov eax,[rcx+0xb454]; ret` — called at `0x143d048d6` | `0x1442eff0a` (=5, reset). **No other writer located** |
| `+0xb458` / `+0xb45c` / `+0xb460` / `+0xb464` / `+0xb468` | u32 ×5 | **not decoded.** Defaults 1 / 8 / 4 / 2 / 7, adjacent to the attack-level setting | not enumerated | reset |
| `+0xb474` | u32 | a copy of `matchSettings+0x3318`, refreshed in the attack-level converter | not enumerated | `0x143d04a80` |
| `+0xbd38` | u32 | the **previous** attack level, clamped ≤ 4 | not enumerated | `0x143d04a61`; `0x1442eff00` (=2, reset) |
| `+0xbd88` | u32 | last dword of the record; default 6 | — | `0x1442f01ee` (reset), the copy's final store |

**Width note, from my own re-read.** `match-ai-decoded.md` calls the attack level
`byte[team+0xb450]`. The think reads it as a **dword** — `cmp dword ptr [rax + 0xb450], 4` at
`0x143d02efe` and `cmp dword ptr [rax + 0xb450], 0` at `0x143d02f23` — and the reset writes a dword
`2`. The values are 0–4 so nothing behaves differently, but the field is a `u32`. [b]

**`team+0xb4c` / `+0xb50` are probably NOT `UTeamAIInfo` fields.** Three independent signals:
(1) emulating the copy `0x143c43370` leaves both untouched while every neighbouring team field
arrives intact [a]; (2) a `.xcode` displacement sweep finds 15 writers of `+0xb4c` and 42 of `+0xb50`
and **none is in the team-AI band** (`0x143688b80`, `0x143689460`, `0x14474a3f0`, `0x1453915e0`,
`0x1453918e0`, `0x145343720`, `0x14542c810`, `0x145437120`, …); (3) `ball-carrier-brain.md` itself
reaches them through **`ctx+0x28`**, not the team pointer. I am not asserting that chapter is wrong —
`ctx+0x28` was not traced — only that calling them `UTeamAIInfo` members is **unproven and
contradicted by the copy**, and nobody should tune them on the team base. [a + b, § 14 open]

### 5.2 The tactics block — `UTeamAIInfo + 0x8078` [b]

There **is** a per-team tactical-instruction structure inside `UTeamAIInfo`. It is constructed by
`0x1442c01a0` (from `UTeamAIInfo`'s constructor `0x1442edcf0` at `0x1442ede1d`,
`lea rcx,[rdi+0x8078]`) and defaulted by `0x1442c0840`. Call its base `B = team + 0x8078`.

| field | accessor | shape | defaults |
|---|---|---|---|
| `B+0x00` (dword) | passing index `2` to any accessor means "resolve to `*(int*)B`" | **the active set index, 0 or 1** — the block holds **two** tactical sets | 0 |
| `B + set*5 + 4 … +8` | — | 2 sets × 5 small enums | `[5, 2, 5, 5, 2]` — **not decoded** |
| `B + (set+2)*7 + k`, `k ≤ 6` | `0x1442c03f0(B, k, set)` → byte | **2 sets × 7 INSTRUCTION BYTES** | all 0 — **individual meanings not decoded** |
| `B + 0x1c + ((set*11 + player)*3 + j)*4` | `0x1442c0640(B, player, j, set)` → dword (`0xc` when out of range) | **[2][11][3] dwords**, per outfielder, three slots | block writes `0x1442c0a1e..0x1442c0af1` |
| `B + 0x584 + …` same indexing | `0x1442c07c0` | a second **[2][11][3] dword** table | not decoded |
| `B + 0xd40 + i*4`, `i < 3` | `0x1442c0420` | 3 dwords | `0x1442c01f0` |
| `B + 0xd53`, `B + 0xd54 + set` | `0x1442c1080` | a gate byte and a 2-byte per-set value | — |
| `B + 0xd58` / `+0xd5c` / `+0xd60` | u32 ×3 | `+0xd58` from the global `0x148026b44`; `+0xd5c` = that `& 0xffffc000`; `+0xd60` = `+0xd5c + 0x80` | `0x1442c088a`, `0x1442c08ab`, `0x1442c08bd` |
| **`B + 0xd64 + set`** (byte) | **`0x1442c07a0(B, set)` → pointer** | **the team's TACTICAL APPROACH CODE, 0–5** | 0 (`0x1442c0201` writes the word) |

`B + 0xd64 + activeSet` is the field that matters. Two wrappers read it:

* **`0x1442dffb0(modeInfo, team)`** = `*(0x1442c07a0(team+0x8078, 2))` — the raw 0–5 code. **It is
  the switch that drives `team+0xb3c4`** (§ 6, at `0x143d7b7b1`); the think also compares it against
  6 at `0x143d02d28`. Dereference sites: `0x1442dffbf`, `0x1442dd90f`, `0x1442ddaea`, `0x14428fc06`,
  `0x144245bd0`, `0x1442dfded`, `0x1442a5ea7`, `0x1449b175f`, `0x1449be2b5`, `0x145403306`,
  `0x145428460`, `0x1453e3cb6`.
* **`0x1442dd8d0(modeInfo, team, k)`**, `k < 7` — switches on that same 0–5 code through a jump
  table at `0x1442dd9ec`, then returns instruction byte `k` of the active set via `0x1442c03f0`.

The think also queries the block per player: `0x143d03030` opens with `0x1442c1080(team+0x8078)`,
then loops `player = 0..10` calling `0x1442c0640(team+0x8078, player, sel, 2)` and maps the result
(1..0xc) through a jump table at `0x143d03680` into `0x1442ee600`, tallying four counters into
`+0x7bc8` / `+0x7bcb` / `+0x7bce` / `+0x7bd1` for three selectors. [b]

Two tactical sets, each with a 0–5 approach code, seven instruction bytes and per-player three-slot
tables, is the shape of a team-tactics record. **I am deliberately not naming the seven instruction
bytes**: nothing in the exe labels them and community names would be a guess.

#### The half of the landing map that is not finished

**The approach code is written at `0x1454023ac` (`mov byte [rax], sil`) inside `0x145401050`**, the
match-setup routine that also builds the `UMatchEnv` and `UPathToGlory` registry refs and fills
`+0x7bc8…` for both teams; its four callers are `0x1453ea3d0`, `0x14540b780`, `0x1454132f0`,
`0x14541a0e0`, all in the match-entry band. **But at that site `sil` is only 0 or 1**
(`0x1454021e2 mov esi,1` / `0x1454021e9 mov esi,r15d` with `r15 = 0`), so that path **cannot** be
the one that installs a 0–5 code. **The block was not traced back to any file** — not dt270, not
`Team.bin`, not anything. The other writer exists and was not found. That is the deliverable this
subsystem is returning incomplete, and naming a file on a hunch would be worse than saying so.
[b for the structure, **negative** for the route]

The only other writer found image-wide is the replay deserialiser `0x145706710` (`B+0xd50`, `+0xd51`,
`+0xd52`, `+0xd53`, `+0xd54`, `+0xd64`, …) — a field-order oracle, not an authoring route.

**Next probe, concretely:** start from `0x145401050`'s four callers and from the setter helper
`0x1442c0780`, called immediately after `0x1442c07a0` at `0x144142f8b` and `0x144245bf6`.

### 5.3 `UAnalyzeInfo` — the record two finished chapters call `matchInfo` / `matchWork` [b]

**`[mgr+0x48]` is `UAnalyzeInfo`.** `0x140efd260` is a two-byte COMDAT-folded getter
`mov rax,[rcx+0x48]; ret` — *its `grpc`/`protobuf` RTTI label in `exe_map.json` is folding noise;
do not read a name into it.* Both `0x143d24d60` (the raw defensive line, 51 call sites) and
`0x1442e1200` (the instruction query, 271) call it on the same `mgr` and index the same object.
`UAnalyzeInfo` is 972,640 bytes, comfortably above `0x275b8`; **`UMatchInfo` is 17,072 bytes and
therefore cannot be it.** The identification rests on the `AnalyzeDetail` offset chain below, which
is exact to four sizes and three gaps. [b]

| offset | type | meaning | readers | writers |
|---|---|---|---|---|
| `+0x44 + team*0x14` | f32 | the **per-team defensive line X** — `player-executors.md`'s `matchInfo+0x44+opp*0x14` and `matchWork+team*20+0x44` | `0x143d24d9e`, inside `0x143d24d60` (51 call sites) | **not located** |
| `+0x25a9c` | f32 array base | indexed by a player index through the bounds-checked accessor `0x143c71ee0`; also one of the three float rows `0x143d7b650` reads | `0x144261ced` (`lea rcx,[rax+0x25a9c]` after `call 0x140efd260` at `0x144261ce6`) | not located |
| `+0x25bbc` | f32 | ball X | `0x143d24dc4`, `0x143d24de6`, `0x1442e12a6`, `0x143d7ba30` | not located |
| `+0x25bcc` | u32 | a **player index**, rejected by the reader if `> 0x15` | `0x144261c59` (`mov esi,[rax+0x25bcc]` after `call 0x140efd260` at `0x144261c54`) | not located |
| `+0x25bd0`, `+0x25bd4 + team*0x58` | f32 | the other two float rows `0x143d7b650` reads | inside `0x143d7b650` | not located |
| `+0x28780` | u32 | a second player index, fetched through the one-line wrapper `0x1442de630` (`call 0x140efd260; mov eax,[rax+0x28780]`), rejected if `≤ 0x15` at `0x144261c47` | `0x1442de639` | not located |
| `+0x273e8` | `AnalyzeDetailInstruction`, `0xa8` | **instruction set #0**: `u32 kind[2][4]` at `+0x273f0`, `u32 value[2][4]` at `+0x27430` | `0x1442e1357`, `0x1442e1360` | **no `disp32` writer anywhere in `.xcode`** |
| `+0x27490` | `AnalyzeDetailInstruction`, `0xa8` | **instruction set #1**, checked first: `kind` at `+0x27498`, `value` at `+0x274d8` | `0x1442e1327`, `0x1442e1331` | same |
| `+0x27538` | `AnalyzeDetailAICoach`, `0x68` | AI-coach block; `+0x27540`/`+0x27548`/`+0x27550`/`+0x27558`/`+0x2757c`/`+0x27584` read with a dword index | `0x1449baa80`, `0x1449baa88`, `0x1449baaa0`, `0x1449baab3`, `0x1449da56a`, `0x1449da574`, `0x1449da5a1`, `0x1449db873`, `0x1449db87d` | not located |
| `+0x275a0` | `AnalyzeDetailOffenceLinkage`, `0x18` | offence-linkage block | `0x145422c11` | not located |

Sizes from each scalar-deleting destructor (`0x143c51100` frees `0xa8`, `0x143c510d0` `0x68`,
`0x143c51130` `0x18`); the container's vtable stores are at `0x143c51695` (`+0x273e8`), `0x143c5168e`
(`+0x27490`), `0x143c51680` (`+0x27538`), `0x143c51672` (`+0x275a0`) inside `0x143c515f0`, which is
`UAnalyzeInfo`'s registrar argument 6 per the descriptor `0x143c51750`. The gaps are exactly
`0xa8`, `0xa8`, `0x68`. [b]

#### The instruction query — `0x1442e1200`, 271 call sites [b]

Re-disassembled from PRISTINE for this write-up; the two loops are quoted verbatim:

```
0x1442e1221  if (kind >= 0x14 || team >= 2) return false
0x1442e1239  kind == 0x0e : two extra gates (team obj +0x224 and +0x91e8)
0x1442e1277  kind == 0x0d : gated on attack direction x ball X and an elapsed-time ratio
0x1442e1308  call 0x140efd260          ; rax = [mgr+0x48] = UAnalyzeInfo
0x1442e1320  movzx ecx,dx ; lea r8,[rcx+rbp*4]          ; rbp = team  (movsxd rbp,edx @0x1442e1215)
0x1442e1327  cmp dword [rax + r8*4 + 0x27498], edi      ; kind
0x1442e132f  jne next
0x1442e1331  cmp dword [rax + r8*4 + 0x274d8], esi      ; value
0x1442e1339  je  true
0x1442e133b  inc dx ; cmp dx,4 ; jb 0x1442e1320          ; four slots
0x1442e1350  ... same over +0x273f0 / +0x27430           ; the other set
             return false
```

`0x273e8+8 = 0x273f0`, `0x273e8+0x48 = 0x27430`, `0x27490+8 = 0x27498`, `0x27490+0x48 = 0x274d8`.
It is reading the record's own `+0x08` and `+0x48` arrays, as `u32[2][4]` — **two teams × four
active instruction slots**, in two independent sets.

**The vocabulary.** Symbolic evaluation of the last `0x60` bytes before each of the 271 call sites
(`build/registry/instr_sites.json`) folds **18 distinct kinds, 1–18**, and **value 255 is the
wildcard**: 147 of 271 sites pass it.

| kind | sites | kind | sites | kind | sites |
|---|---|---|---|---|---|
| 1 | 9 | 7 | 14 | 13 | 12 |
| 2 | 6 | 8 | 29 | 14 | 41 |
| 3 | 12 | 9 | 6 | 15 | 38 |
| 4 | 19 | 10 | 9 | 16 | 23 |
| 5 | 7 | 11 | 6 | 17 | 4 |
| 6 | 12 | 12 | 8 | 18 | 3 |

258 sites account for the 18 rows; of the remaining 13, eight fold to `value = 255` with a
non-constant `kind` and five fold neither — all thirteen pass at least one argument in a register
the back-scan cannot resolve. 258 + 8 + 5 = 271. ✓

**The callers are the decision code, in all three finished chapters' bands**: `0x1442f9a90` (the
off-ball **quota** builder `match-ai-decoded.md` documents), `0x143da92c0` (the defending-attribute
function that same chapter documents), the `ChanceSpaceRun` band `0x143df6010` / `0x143df7440` /
`0x143df77a0`, executors `0x144182650`, `0x144184490`, `0x1441a4280`, `0x1441d93b0`, and carrier-band
roots `0x145623990`, `0x145624630`, `0x14565bf80`, `0x14568f430`, `0x145699510`, `0x14569cb20`.

**The `0xff` is the hinge, and it was nearly read the wrong way round.** The initialiser
`0x143ce2fd0` builds five parallel `u32[8]` arrays at `+0x08`/`+0x28`/`+0x48`/`+0x68`/`+0x88`
(summing to exactly `0xa8`), four cleared to 0 and one — `+0x48` — to `0xff`. Read as a table that
is *accumulated into*, that looks like counters plus a "last index" sentinel. Read as a table that
is *queried*, `0xff` is precisely the wildcard 147 callers pass, an unset slot has `kind = 0`, and
kind 0 is never queried. **It is a set of switches with an "any value" marker.** § 15 records how the
first reading arose and why the second wins.

### 5.4 `UOrderInfo` — addressing decoded, slot record not [b]

`0x4090` = 16,528 bytes, `Copy`, `ArrayRef<2, HomeAway>`, all three scopes, copy `0x1456e9e20` (a
dword-by-dword member copy — emulated: **15,777 bytes written, max offset `0x4089`, all identical to
source, nothing past the end, 300 alignment holes** [a]). The live source is
`UModeInfo + team*0x58 + 0x3500`, fetched by `0x1442d6e20`, which has only **22 call sites** —
unlike `UTeamAIInfo`, gameplay does not read it everywhere.

All 22 do the same thing (`0x1456d0930`, `0x1456d0a70`, `0x1456d0ba0`, `0x1456d1050`, `0x1456d1130`,
`0x14560ee70`, `0x145612610`, `0x1456147a0`, `0x145611420`, `0x1456090e0`, `0x14560a8d0`,
`0x14561be10`, …):

```
playerNo (0..0x1e) -> team   (0..10 -> 0 ; 11..21 -> 1 ; 0x1b -> 0 ; 0x1c -> playerNo-0x1b ; 0x1d -> 0 ; 0x1e -> flag)
order  = 0x1442d6e20(modeInfo, team)
handle = 0x1442df7f0(order, playerNo)      ; or 0x1442c2d40(order, playerNo)
valid  = 0x1442e4c40(handle)               ; cmp dword[rcx],1 ; ja fail ; cmp dword[rcx+4],0x27 ; ja fail
                                           ; 0x1442e4c60(handle, team, slot) is its setter
```

So **`UOrderInfo` is a per-team table of up to 40 order slots (`slot ≤ 0x27`), addressed by player
number**, and `{u32 team ≤ 1, u32 slot ≤ 0x27}` is the handle type. The callers sit in the cursor /
player-selection band, next to where `UCursorInfo`'s `Ref` is built (`0x1456d30b0`). **The slot
record's own fields are not decoded** — that needs its own probe, and it is the most likely home of
an "order a teammate to run" path.

**Negative, asked for explicitly: the off-ball attack level does NOT live in `UOrderInfo`.** It is
`UTeamAIInfo+0xb450`, setting at `+0xb454` (§ 5.1). [b]
### 5.5 `UPadInput` — 153,952 bytes, fully accounted for [b, two sizes a]

Descriptor `0x143c62a20`, `mov r8d, 0x25960` at `0x143c62a49`, `xor r9d,r9d` (`Pointer`, so writes
are visible immediately and its `ScopedWAndC` is a no-op — § 2.4). The allocation splits **exactly**:

| offset | size | contents | proof |
|---|---|---|---|
| `+0x00000` | `24 × 0x1908` = `0x258c0` | **24 pad-slot blocks** | `imul rcx, rcx, 0x1908; add rcx, base` (`0x14431a742`); `imul rdx, rcx, 0x1908` (`0x1440d435b`); 24 × 6408 = 153,792 = `0x258c0` |
| `+0x258c0` | 8 | per-hardware-pad "slot in use" bytes | `cmp byte [rcx+r9+0x258c0],0` (`0x14431a72c`); `mov byte [rax+rsi+0x258c0],1` (`0x1453e725e`) |
| `+0x258c8` | `8 × 18` = `0x90` | per-pad 18-byte assignment descriptors — **contents not decoded** | `lea rdx,[rax+rax*8]; lea rcx,[rcx+rdx*2]; add rcx,0x258c8` (`0x14431a6f7`–`0x14431a702`); written by `0x144316620` |
| `+0x25958` | 1 | gate flag A — non-zero disables the whole per-pad frame update | `cmp byte [rcx+0x25958],0; jne ret` (`0x14431a710`). **Writer not located** |
| `+0x25959` | 1 | gate flag B, same effect | `0x14431a71c`. Writer not located |
| `+0x2595a` | 6 | padding | — |

**The pad-slot block is a 100-frame ring.**

```
+0x0000   100 x 64 bytes   frame ring   (6400 = 0x1900)
+0x1900   u32              write cursor, wraps at 100
+0x1904   4 bytes          unaccounted
```

`inc dword [rcx+0x1900]`, then `cmp eax,0x64; jl; mov [rcx+0x1900],0` at `0x14431a780`–`0x14431a79c`
is the wrap; `shl rbx,6; add rbx,rcx` (`0x14431a7a4`) is the 64-byte stride, and the four
`movups [rbx+0x00..0x30], xmm0` that follow zero exactly 64 bytes. **100 frames at 60 fps = 1.67 s
of input history.** [b]

**Frame addressing**, the whole function, re-read for this write-up:

```
0x14431a5b0(block, k):
  mov eax,[rcx+0x1900] ; sub eax,edx ; jns + ; add eax,0x64
  cdqe ; shl rax,6 ; add rax,rcx ; ret
```

`k` counts **frames into the past**; `k = 0` is the current frame.

**The 64-byte frame:**

| offset | type | meaning |
|---|---|---|
| `+0x00` | u64 | **button bitmask**, logical ids 0..32 (`bts rax, r15` for `r15 = 0..0x20` at `0x14431a93f`, bound `cmp edi,0x21`). **Bits 4..7 are cleared** (`and rax, 0xffffffffffffff0f`, `0x14431aac6`) and rewritten from the left-stick angle, so **the D-pad and the left stick share one 8-way direction field**. **Bit 32 is not a button** — it is a frame-validity / discontinuity flag, tested before every edge comparison (`0x14430f9e1`) |
| `+0x08` / `+0x0C` | f32, f32 | left-stick angle (degrees) and magnitude after deadzone |
| `+0x10` / `+0x14` | f32, f32 | right-stick angle and magnitude |
| `+0x18` | u8[33] | **per-button analog pressure**; `0xff` for a digital button (`0x14431a8ce`), computed for the two analog triggers (`0x14431a923`). **No reader located** — so "read ≠ effective" is unresolved for the analog channel |
| `+0x39` | 7 bytes | unaccounted |

**Stick conditioning is three interlocked constants** (`0x14431aa26`–`0x14431aa47`): dead zone
**0.20** (`0x1478501c0`), saturation **0.95** (`0x145e8788c`), divisor **0.75** (`0x145a8dd6c`), i.e.
`m' = clamp((m − 0.20) / 0.75, 0, 1)`, which reaches exactly 1.0 at m = 0.95. The angle is snapped
into the direction bits on a 45° grid with a 22.5° offset (`0x14431abd8`, `0x14431abf0`). [b]

**The logical→hardware button map** (emulated over `0x1443164e0` for inputs 0..33; the user-remap
path `0x144316130` only handles logical `0x12..0x1f`, `lea eax,[r9-0x12]; cmp eax,0xd; ja default`
at `0x14431615d`, so **only the in-match bank is rebindable**):

| logical | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hw | 4 | 8 | 5 | 7 | 3 | 1 | 0 | 2 | 5 | 7 | 3 | 1 | 0 | 2 |
| **button** | **LB** | **RT** | **LT** | **RB** | X | B | A | Y | LT | RB | X | B | A | Y |
| bank | attack | attack | attack | attack | attack | attack | attack | attack | defence | defence | defence | defence | defence | defence |

Four independent anchors pin it: (1) the frame builder treats **hw 5 and hw 8 as analog** — `cmp
eax,8 / cmp eax,5` then `sete dl; add edx,4` selecting axis 4 or 5 (`0x14431a8b6`–`0x14431a8e4`)
while the sticks use axes 0/1 and 2/3 — which is XInput order, so hw 5 = LT and hw 8 = RT; (2)
`TacticsNext/Back` = logical 4/6 and `LineControlFront/Back` = 5/7, i.e. the D-pad; (3) `ShortPass` =
24 → hw 0 and `LongPass` = 23 → hw 1 against the game's own control screen (A = Low Pass, B = Lofted
Pass); (4) `CursorChange` = 18 → hw 4 against "LB = Cursor Change", cross-checked by `FriendPress` =
27 → hw 7 (RB = second-man press). Logical 4..7 are the D-pad; logical 32 is the pseudo-button
discontinuity bit and maps to itself. [a for the map, b + c for the anchors]

**`match::pad::ThinkUnit`** — all 72 built by one factory, `0x1440e0c70` (emulated over a zeroed
buffer; 72 vtable hits at offsets `0x1a0`–`0x1760`):

| offset | meaning | evidence |
|---|---|---|
| `+0x08` | **logical button id** (33 = *none*) | [a]; consumed by `vf17` as `mov edx,[rcx+8]` |
| `+0x0c` | input class: 0/1 = stick unit, 2 = button unit | [a]; matches RTTI exactly — every `+0x0c ∈ {0,1}` unit derives from `ThinkUnitStickKind`, every `+0x0c = 2` from `ThinkUnitPadId`, 72/72 |
| `+0x10` | a mode selector 0..4 — **semantics NOT proven**; only consumer found is `cmp dword [rsi+0x10],3` at `0x1440dcff8` | [a] values, [b] use |
| `+0x14` | command variant; `== 2` enables the multi-press path in `vf17` | [a] value, [b] use at `0x1440d800a` |
| `+0x18` | 1 (enabled) | [a] |
| `+0x29` | runtime press count; `> 1` with `+0x14 == 2` routes to the multi-press detector | [b] `0x1440d8016` |
| `+0x34` | priority, compared during slot selection | [b] `0x1440db37f` |

**The input-pattern node — 40 bytes**, the vocabulary of the richer predicate engine (§ 7):

| offset | type | meaning |
|---|---|---|
| `+0x00` | u32 | button mask (`1 << logicalId`, or a multi-bit mask from the gesture table) |
| `+0x04` | u32 | **kind** (predicate index 0..10) — **2 = held ≥ A frames, 4 = TAP, 8 = not held, 9 = held** [a] |
| `+0x08` | u32 | parameter A (minimum frames, kind 2) |
| `+0x0c` | u32 | parameter B (the tap window, kind 4) |
| `+0x10` | u8 | stick-constraint present → selects dispatch table A |
| `+0x14` / `+0x18` | f32, f32 | stick angle range |
| `+0x20` / `+0x24` | f32, f32 | magnitude thresholds; **`−1.0` = no stick constraint** → table C |

**The `ThinkContext`** built per player by `0x1440d7010`, 0x34 bytes: `+0x00` pad-system pointer
(`match::Command+0x2b900`), **`+0x08` address of the bound pad block — the single dereference every
predicate makes**, `+0x10` per-player command entry (stride `0xd0`), `+0x18` per-player
control-source record, `+0x20` player index, `+0x24` pad index or `0xff`, `+0x28` f32, `+0x2c` u32,
`+0x30..0x32` three bytes. [b]

### 5.6 `UCommandOutput` and `match::Command` [b]

`UCommandOutput` is `0x13b20` = 80,672 bytes, **`Copy`** — so a writer's bytes are invisible until a
commit, unlike `UPadInput`. **No field of it is decoded.** That is the honest state, and it is a
correction: this section used to list `+0x25bcc` and `+0x25a9c` as `UCommandOutput` fields.

> **CORRECTION, applied in this repair pass.** `+0x25bcc` (154,572) and `+0x25a9c` (154,268) lie far
> outside a 0x13b20 = 80,672-byte allocation — § 1.1's own size proof refutes them. Both reads are
> taken off `0x140efd260(x)` = `[x+0x48]`, which § 5.3 establishes is **`UAnalyzeInfo`** (972,640 B,
> so the offsets fit, and ball X at `+0x25bbc` sits 16 bytes from `+0x25bcc`):
> ```
> 0x144261c50 mov rcx,[rdi+0x30] ; 0x144261c54 call 0x140efd260 ; 0x144261c59 mov esi,[rax+0x25bcc]
> 0x144261ce2 mov rcx,[rdi+0x30] ; 0x144261ce6 call 0x140efd260 ; 0x144261ced lea rcx,[rax+0x25a9c]
> ```
> Both have been moved into the § 5.3 `UAnalyzeInfo` table. Worse, the consumer they came from
> (`0x144261bd0`) **touches no registry record at all**: its full call-target set is 16 functions and
> contains none of `0x145340c80`, `0x1453415d0`, `0x143c4db70`, `0x145340a10`, and none of
> `0x144287790` — which is in any case a `Scoped*` **destructor** (stores a vtable to `[rcx]`,
> releases through `0x140c83910`, clears the read token `[rbx+0x48]`), not a `ScopedRead`
> constructor. There is also no instruction at `0x144261cf0` (the instructions are at `0x144261ced`
> and `0x144261cf4`). See § 10.3 and § 12.5, where the correction is carried through. [b]

`match::Command` itself (ctor `0x1440d2970`, vtable `0x146b9e7d8`) holds `CameraInfoRef` at
`+0x2b8a8`, the pad sub-system at `+0x2b900`, the per-player control-source array at `+0x2b4dc`
(stride 32), 24 × `0xb4`-byte command slots at `+0x40`, 24 `match::CommandPlayer` pointers at
`+0x2b7e0`, `MatchInfoRef` at `+0x2f568`, **`PadInputRef` at `+0x2f5c0`**, `CursorInfoRef` at
`+0x2f618`, `Screen2dInfoRef` at `+0x2f670` and **`CommandOutputRef` at `+0x2f6c8`**.
`match::CommandPlayer` (ctor `0x1440dd750`, vtable `0x146ba0620`) is the per-player brain:
`+0x1a38`/`+0x1a3c` = `0x51` (81 unit slots holding the 72 `ThinkUnit`s), `+0x1ab0`
`CommandOutputRef`, `+0x1b08` `Screen2dInfoRef`, `+0x1b60` `CommandInfoRef`, `+0x1bb8`
`StepupTutorialRef`. [b]

### 5.7 The size-only records, and who holds a `Ref` to what [b]

**`UMatchEnv`, 344 B, `Copy`** — its copy-assign `0x143c4d400` is a pure `movups` bulk move of
`2×0x80 + 0x50 + 8 = 0x158` bytes with **no field structure, no pointers, no vtable**: a flat POD.
Ctor `0x143c4d920 → 0x1442c7080`. It is the most widely held small record — 30 `Ref`-store sites,
27 `ScopedRead`, 5 `ScopedWrite`, 5 `ScopedWAndC`, and `match::Player` carries one at `+0x18f30`.
**Its internal layout is NOT decoded**, and I will not guess half/clock/score/weather offsets from
the name.

**`UMatchInfo`, 17,072 B, `Copy`, all three scopes** — **36 tagged read acquires, the most of any
record in the image**, plus 14 `ScopedWrite` and 7 `ScopedWAndC`. Layout not decoded. It is **not**
the object two chapters call `matchInfo` (§ 5.3).

**`UFieldInfo`, 80 B, `Pointer`, read-only** — copy `0x143c4d810` moves exactly `5 × 0x10`; 19
`Ref`-store sites, 6 read acquires, **no write template at all**. The "1.4 MB pitch model" the
skeleton implied does not exist; 80 bytes is the right order of magnitude for pitch geometry.

**`URecordInfo`, 1,435,944 B, `Pointer`, read-only** — 28 read acquires, no write template; ctor
`0x143c4d9c0` and dtor `0x143c4da30` build arrays at `+0x1388e0` and `+0x119620`; holders are
`match::record::Record`, `match::RecordReplay`, `match::Replay`, `match::PlaybackController` and the
replay cameras. Engine bookkeeping for replay/highlights. [b for size, access and holders;
**c** for the "replay buffer" label]

**Who holds a `Ref`, and to what** — every `<Name>Ref` vtable store attributed to its containing
chained-unwind root:

| owner | records |
|---|---|
| **`match::Player`** `0x144140fd0` | `UPlayerInfo` `+0x18d10`, `UPlayerMove` `+0x18d68`, `UBallExternalForce` `+0x18dc0`, `UMatchEnv` `+0x18f30`, `URecordInfo` `+0x18f88`, `UPadInput` `+0x18fe0`, `UCameraTargetInfo` `+0x190e8` — **seven, not nine** (§ 12) |
| `match::Match` `0x143c3cb90` | `UBallPersonInfo`, `UFieldInfo`, `UFixDemoInfo`, `UMatchEnv`, `UMatchInfo`, `URagdollInfo`, `URecordInfo`, `USugoroku` |
| `match::MatchControl` `0x143c53cc0` | `UCommandOutput`, `UConceptArrangeReleaseInfo`, `UCornerFlagInfo`, `UCursorInfo`, `UFixDemoInfo`, `UGoalPostInfo`, `UMatchInfo`, `UTrainingWork`, `UVanishingSprayInfo` |
| `match::MatchCommandObject` `0x143c5c940` | `UCameraInfo`, `UCommandInfo`, `UCursorInfo`, `UESports`, `UMatchEnv`, `UMatchInfo`, `UPadInput`, `UPathToGlory`, `URecordInfo`, `UScreen2dInfo`, `USugoroku` |
| `match::Command` `0x1440d2970` | `UCameraInfo`, `UCommandOutput`, `UCursorInfo`, `UMatchInfo`, `UPadInput`, `UScreen2dInfo` |
| `match::CommandPlayer` `0x1440dd750` | `UCommandInfo`, `UCommandOutput`, `UScreen2dInfo`, `UStepupTutorial` |
| `match::record::Record` `0x144285920` | `UCommandOutput`, `UESports`, `UMatchEnv`, `UPlayData`, `URecordInfo` |
| `match::RecordReplay` `0x143ca8870` | `UMatchEnv` `+0x78`, `UMatchInfo`, `URecordInfo`, `UScreen2dInfo`, `UOrderInfo` `ArrayRef` `+0x128`/`+0x138` |
| `match::PlaybackController` `0x1455fa9b0` | `UCursorInfo`, `UESports`, `UFieldInfo`, `UMatchEnv`, `UMatchInfo`, `UReplayInfo`, `UScreen2dInfo` |
| `match::CommitRegistryListener` `0x143c66cd0` | `UCornerFlagInfo`, `UFixDemoInfo`, `UGoalPostInfo`, `UMatchEnv`, `UMatchInfo`, `UVanishingSprayInfo` |
| `game_mode::MatchListener` `0x1453da1d0` | 26 records — the largest single holder |
| the match-wide hubs `0x1442d0050`, `0x1442d12d0` (27 each), `0x1442d0ca0` (15), `0x143c76c10` (24) | owner class not named by a vtable store |
| `match::camera::plugin::*`, `match2D::Model::Manager`, `match::mob::Listener`, `match::demo::DemoBase`, `match::Replay`, `match::StepupTutorialBase`, `match::PathToGloryBase`, `match::SugorokuBase`, `match::HighlightManager`, `match::RagdollManager`, `match::ReplayHuman`, `onlinesystem::*` | the rest — full grouping in `build/registry/refsites.json` |

---

## 6. The per-match tactics landing map

### 6.1 `team+0xb3c4` NAMED — the CPU's **direct-play directive** [b]

`0x143d7c5b0`, called from the team-AI think at `0x143d03150`, is the field's whole life cycle:

```
if (team.0xb3c4 == 0)                                    ; 0x143d7c725
    v = 0x143d7b650(think, teamIdx)                      ; 0x143d7c7e0
    if (v != 0) team.0xb3c4 = v                          ; 0x143d7c7f0   <-- SET   (v in {1,2})
else
    ; deterministic TIMER release, evaluated every think tick
    if (modeSettings+0x3308 != 1)  goto CLEAR             ; 0x143d7c737 / jne 0x143d7c7cd
    if (teamAI+0x28d == 0)         goto CLEAR             ; 0x143d7c751 / je  0x143d7c7cd
    secs = 5.0f                                          ; xmm6 preset at 0x143d7c5eb ([0x145a8dd78])
    if (0x1442dd8d0(mode,team,0) == 0) {                  ; 0x143d7c762 / jne keeps 5.0
        secs = 7.0f                                      ; 0x143d7c76b [0x145c36ac0]
        if (0x1442dffb0(mode,team) == 2 && this.0xb3c4 == 2)
            secs = 14.0f                                 ; 0x143d7c78a [0x145c38ba8]
    }
    frames = int(FPS*secs + 0.5)                         ; 0x143d7c792 call 0x14533ea80 (FPS getter)
                                                         ; mulss / addss 0.5 / cvttss2si  -> rbx
    if (frames >= modeSettings+0x3320)  keep              ; 0x143d7c7ad cmp ebx,[rax+0x3320] / jb CLEAR
    else  team.0xb3c4 = 0                                ; 0x143d7c7d6   <-- CLEAR
if (team.0xb3c4 != 0) team.0xb3be = 1                    ; 0x143d7c825
```

> **CORRECTION, applied in this repair pass: there is no random number here.** The chapter used to
> write the release test as `int(rand01()*p + 0.5) >= modeSettings+0x3320` and called the field
> "probabilistically cleared". `0x14533ea80` is **not** `rand01()` — it is the **frame-rate getter**
> that § 7.2 and § 11 already name as such: two instructions, `movss xmm0,[rip+0x38e4034]; ret`,
> returning the single global float at `0x148c22abc`, whose only writer image-wide is
> `0x140a14d90` (`mov eax,[rip+0x7842b5a]; cvtsi2ss xmm0,rax; movss [rip+0x820dd16],xmm0` →
> `0x148c22abc`) — `float(int global)`, not a stream. It takes no argument. The same
> `call 0x14533ea80 ; mulss k ; addss 0.5 ; cvttss2si` idiom is read *correctly* elsewhere in this
> chapter as a seconds→frames conversion (the 0.4 s gate at `0x144261c1c`, the one-second timer at
> `0x1440e53e3`, `B = int(0.08·FPS+0.5)` at `0x1440e5519`). There is **no RNG call anywhere in
> `0x143d7c5b0`**. So the six floats are **durations in seconds**, the test is a frame-count compare,
> and the release is **deterministic**. [b]
>
> **And `+0x3320` is not a difficulty threshold.** It is compared against `int(FPS·secs+0.5)` — 420
> frames at `7.0 s`, 840 at `14.0 s` on a 60 fps clock — and it is zeroed, as a qword pair with the
> proven frame counter `+0x3318`, in the match-work initialisers: `0x1442c3b4a mov [rbx+0x3318],rdi`
> / `0x1442c3b51 mov [rbx+0x3320],rdi` (and again at `0x1442c4af1` / `0x1442c4af8`), immediately
> after a float clock is stored at `+0x3314`. **`+0x3320` is a frame-scale quantity** [b]; *which*
> elapsed span it counts is **[c]** and is not claimed here. The argument that it is **not** a
> difficulty setting is this: the left-hand side of every one of these compares is 300–840 at 60 fps,
> so if the right-hand side held a 0–4 difficulty value the `jb` at `0x143d7c7b3` would never be
> taken and the CLEAR store would be unreachable dead code — and the same for the four compares in
> `0x143d7b650`. A sibling site does `cmp dword [rax+0x3320], 5 ; jb` (`0x143df6148`), i.e. "at least
> five frames", which is the shape of a counter, not of a setting. 36 read sites follow a
> `0x1442d6de0` call; a `.xcode` disp32 store scan finds no other writer inside the match band —
> though such a scan cannot see a wider overlapping store, exactly the trap this section documents
> for `+0xb3c4`, so that half is a **weak** negative.
>
> **Four smaller fixes in the same block, from re-reading it instruction by instruction.**
> (1) The `14.0f` arm tests **this** team's `+0xb3c4`, not the other team's: `rbx` comes from
> `0x143d7c749 call 0x1442d7090(rdi, esi)` with `esi = [rbp+8]`, and the *opposite* index is computed
> explicitly elsewhere in the same function (`0x143d7c7b5–0x143d7c7be`: `esi>1 ? 0 : esi==0`), which
> is how we know `esi` is this team. The earlier text said `other.0xb3c4 == 2`.
> (2) The `xmm6` default is `5.0f`, not `7.0f`: when `0x1442dd8d0` returns non-zero the 7.0 store is
> jumped over and the register keeps the value loaded at `0x143d7c5eb` (`[0x145a8dd78]`).
> (3) `modeSettings+0x3308 != 1` and `teamAI+0x28d == 0` are **not gates that skip the release** —
> both `j*` straight to the CLEAR store, so the directive is force-cleared in any mode but 1. The
> earlier text called them a "gate:".
> (4) There is a **dead computation on the keep path**: `0x143d7c7c6` fetches the *other* team's
> record through `0x1442d7090` and `0x143d7c7cb jmp 0x143d7c7f6` discards it. Do not chase it.

Re-disassembled from PRISTINE for this write-up, both writers quoted:

```
0x143d7c7cd  mov rax,[rbp+0x63a8]      ; the live UTeamAIInfo, stashed by the think
0x143d7c7d4  xor ecx,ecx
0x143d7c7d6  mov dword [rax+0xb3c4], ecx        <-- CLEAR
...
0x143d7c7e0  call 0x143d7b650
0x143d7c7e5  test eax,eax ; je skip
0x143d7c7e9  mov rcx,[rbp+0x63a8]
0x143d7c7f0  mov dword [rcx+0xb3c4], eax        <-- SET
```

`0x143d7b650` returns **0, 1 or 2** and is gated on: the match mode (`modeSettings+0x3308 == 1`),
`teamAI+0x28d`, **three more of the same `int(FPS·secs + 0.5)` vs `modeSettings+0x3320` frame tests**
(`0x143d7b6b4`/`0x143d7b81f`, `0x143d7b9a5`/`0x143d7b9c8`, `0x143d7ba82`/`0x143d7ba9d`, plus a fourth
at `0x143d7bbbb`), a designated player index from `0x1442dfc70` (≤ `0x15`), three float rows in
**`UAnalyzeInfo`** (`0x140efd260()`) at `+0x25a9c`, `+0x25bd0` and `+0x25bd4 + team*0x58`, and above
all a **switch on `0x1442dffb0(mode, team)`** at `0x143d7b7b1` — the tactics block's 0–5 approach
code (§ 5.2). Return value `2` is reachable only through the `== 2` arm
(`0x143d7b9a5 … 0x143d7ba44 mov eax,2`). (The object behind `0x140efd260` was called "the constant
table" here; it is `UAnalyzeInfo` — the same record as § 5.3, § 5.6 and § 10.2. One name, everywhere.)

So `team+0xb3c4` is a **transient, per-team, AI-only directive**: set from the team's tactical
approach plus game state plus a set of frame-counter timers, released when a 7 s (or 14 s) timer
test fails or either mode gate fails, mirrored into `+0xb3be`.
The carrier chapter's observed effects — accept every cross plan outright (`0x14567b586`), force the
long-ball score to 100 (`0x14567b8f6`), disable Safety (`0x1456770eb`) — are exactly "the CPU has
decided to go direct". **It is not a setting anybody can author** — but, correcting the chapter's own
earlier headline, it is **not** "overwritten within one tick" either: the tick that follows an
external non-zero write takes the `else` branch and *keeps* the value while
`modeSettings+0x3308 == 1`, `teamAI+0x28d != 0` and `int(FPS·secs+0.5) >= modeSettings+0x3320`. As a
**runtime** lever it is plausible; as an authorable one it is dead. Nothing was written or tested.

#### GIVEN #5's premise is false, and saying so changes the search

The skeleton stated "there is no `mov [reg+0xb3c4], …` anywhere in `.xcode`", and reasoned from that
to "the field arrives only by whole-record copy, so the question is what fills the *source* record".
A capstone-verified `.xcode` displacement sweep finds **four** writers — `0x143c44ad6` (inside the
copy), `0x143d7c7d6`, `0x143d7c7f0`, `0x145703bce` (replay deserialiser) — plus `0x1442efedd`
`mov qword [rbx+0xb3c0], r15` in the initialiser, which covers `+0xb3c4` **at a different
displacement**, exactly the case a disp-literal search is blind to. The skeleton's inference pointed
in a plausible direction, but the answer came from the writer sitting in the think's own call list,
not from chasing a source record. **The lesson worth keeping**: a displacement search must consider
wider stores that overlap the field.

> The second lesson previously stated here — "the commit copies a record's back buffer onto its own
> front buffer and *can never introduce a value from outside the record*" — is **withdrawn**. It is
> true of the commit's own two arguments and false as a statement about the record's contents:
> whatever the publisher `0x1456ea6d0` stages into the back buffer *is* a value from outside, and
> § 4.1 shows the front buffer is exactly what gameplay reads. The copy discipline is a route in, not
> a wall. [b]

### 6.2 The attack-level chain — `+0xb454 → +0xb450 → +0xb44d/+0xb44e` [a for the defaults, b for the chain]

```
team+0xb454   the attack-level SETTING: 0..4 fixed, or 5 = "let the AI drive it"   (default 5)
                └ 0x1442ee5f0 is literally `mov eax,[rcx+0xb454]; ret`
              ↓  0x143d04830   (called from the think at 0x143d02e70)
team+0xb450   the LIVE attack level, clamped 0..4                                   (default 2)
                setting != 5 :  cmp eax,4 ; cmovg eax,4      0x143d048ed / store 0x143d048f4
                setting == 5 :  the AI adjusts it by +/-1 WHEN 0x14533eb60 allows, bounded [0,4];
                                otherwise it assigns ebx clamped to 4 (cmova eax,r14d @0x143d04a49)
                                0x143d049f2 call 0x14533eb60 / test al,al / je 0x143d04a35
                                0x143d04a10 dec / 0x143d04a2e inc / 0x143d04a4d store
                                previous value mirrored to +0xbd38   0x143d04a61
                                modeSettings+0x3318 copied to +0xb474 0x143d04a80
              ↓  0x143d02c80   (the team-AI think)
team+0xb44d = (team+0xb450 >= 4)     0x143d02ef0 clears, 0x143d02f07 sets
team+0xb44e = (team+0xb450 <= 0)     0x143d02f15 clears, 0x143d02f2c sets
```

So the carrier chapter's "`+0xb44d ≠ 0` bypasses the cross roll and guarantees MiddleShot's +40"
reads, in plain English: **at attack level 4 (all-out attack) the CPU stops rolling for crosses and
always takes the long-shot bonus; at level 0 the mirror flag `+0xb44e` fires instead.** `+0xb44d` is
**a view of the attack level**, and tuning it separately would desynchronise it from every other
attack-level consumer — including the off-ball run-quota tables `match-ai-decoded.md` documents.

**And the level is AI-driven out of the box.** The shipped default of the *setting* is 5, which means
the converter may move the level ±1 within [0,4] — **when `0x14533eb60` allows**, not unconditionally
every tick (`0x143d049f2 call 0x14533eb60 ; test al,al ; je 0x143d04a35`; on the `je` path the level
is assigned from `ebx` with `cmova eax,4`). Any quota tuning premised on a stable per-team attack
level needs that caveat.

### 6.3 The think, and the frame in which all of this happens [b]

`0x143d02c80`: `rcx` = think object, `rdx` = `UModeInfo` (stored to `think+0x63a0`), `r8` = **the
team's live `UTeamAIInfo`** (stored to `think+0x63a8`, cleared on exit at `0x143d03661`). Abridged
order:

`0x143d0b940`, `0x143d02770`, `0x143d036b0`, `0x143d795b0`, `0x143d093b0`, `0x143d09960`,
`0x143d6eea0`→`+0x204`/`+0x208`, `0x143d4b990`→`+0x128`, **`0x143d04830`→`+0xb450`**, `0x143d06fc0`,
`0x143d06e10`, `0x143d07510`, **`+0xb44d`/`+0xb44e`**, `0x143d0ace0`, `0x143d0a3f0`, `0x143d03f30`,
`0x143d07ea0`, `0x143d6e8c0`, `0x143d09090`, `0x143d0b530`, the `+0xb3cc`/`+0xb3d0` scan,
`0x143d4b580`, `0x143d84f30`, **`0x143d7c5b0`→`+0xb3c4`**, `0x143d7e1e0`, `0x143d7ef50`,
`0x143d809f0`, `0x143d062d0`, `0x143d7fe90`, `0x143d76510`, `0x143d05090`, `0x143d0b3a0`,
`0x143d07bf0`, `0x143d52470`→`+0xb3c0`, **`0x143d0f290`→`+0xb3bd`**, `0x143d07920`, `0x143d83d70`.

**This is the only per-tick ordering fact the subsystem yields** — see § 9.
---

## 7. The pad → command channel

### 7.1 There is no "translation step", and `UCommandInfo` is not in the path [b]

```
hardware pads (8)
   |  0x1453e7130   (the only non-ctor/dtor UPadInputRef::ScopedWAndC user)
   |  -> 0x14431a6f0 -> 0x144316620        per-pad assignment descriptor
   |  -> 0x14431a760                       per-pad FRAME BUILDER (writes one 64-byte frame)
   v
UPadInput   0x25960 = 153,952 B  (Pointer)   24 slots x 0x1908, each = 100 x 64-byte frames
   |         frame accessor 0x14431a5b0(block, k)   k = "k frames ago", 0 = now
   v
match::Command::update   0x1440d4180   (binds the CommandOutputRef at this+0x2f6c8: 0x1440d4927
                                        lea rbx,[r13+0x2f6c8]; write-resolve 0x1453415d0 @0x1440d497d)
   |   per player 0..23 (stride 0xd0): read a control-source code from this+0x2b4dc+idx*32,
   |   dispatch through a 15-entry jump table (0x140d4a08+base, bound `cmp esi,0xe`),
   |   in the pad branch bind padBlock = UPadInput + padIdx*0x1908 (0x1440d435b),
   |   build a 0x34-byte ThinkContext (0x1440d7010), call the player's CommandPlayer vf+0x18
   |
   |-> match::CommandPlayer::vf3 0x1440de590 -> 0x1440ddd40 -> 0x1440db1c0 (0x51 = 81 slots)
   |        -> per unit 0x1440dcf60 -> ThinkUnit::vf17 (condition) / vf12 (command id)
   v
UCommandOutput   0x13b20 = 80,672 B  (Copy)     <-- WRITTEN HERE.  NO READER TRACED. NO COMMIT FOUND.
   |
   +-? CommandOutputRef is CONSTRUCTED in: match::MatchControl, match::Command 0x1440d2970,
       match::CommandPlayer 0x1440dd750, match::record::Record 0x144285920, the CPU-side hubs
       0x1442d0050 / 0x1442d12d0, observer/replay 0x144288360, MatchOnline 0x145415a90
       -- these are Ref VTABLE-STORE sites, i.e. constructors, NOT proven consumers.  [c]
       (Only 0x144288360 contains registry resolve calls at all -- two, 0x1442883dd and
        0x14428844d -- and neither is attributed to a record.)

UCommandInfo 0x1188 = 4,488 B (Pointer) -- ALL THREE ScopedWrite users are OnlineCommandControllerImpl
```

> **CORRECTION, applied in this repair pass — two holes this diagram used to hide.**
> **(1) No consumer is established.** The one arrow previously "followed all the way in" was
> `match::player 0x144261bd0`, and that function **touches no registry record at all** (§ 5.6): its
> 16 call targets contain no registry entry point and no `Scoped*` constructor, and the offsets it
> reads are `UAnalyzeInfo`'s. The arrow is **deleted**. The remaining arrows are `CommandOutputRef`
> **vtable-store** sites — exactly the attribution method § 15.1 declares void ("attributing a record
> to a subsystem from its `Ref`/`Scoped*` vtable referrers gives the wrong answer in this codebase"),
> so they are marked [c].
> **(2) No commit exists in this band.** `UCommandOutput` is `Copy` (`r9d = 1`, re-verified) and its
> only RTTI scope instantiations are `VCommandOutputRef::?$ScopedRead` and
> `VCommandOutputRef::?$ScopedWrite` — **no `ScopedWAndC`** — and the commit
> `0x145340a10` has **zero** call sites anywhere in `0x1440d0000–0x1440f0000` (the same band holds 19
> write-resolves, 5 wrapper calls and 1 read-resolve). By § 2's own rule, everything
> `match::Command::update` writes is invisible to every reader until *something* commits it. Either
> the commit lives outside this band and was not found, or the model is incomplete for this record.
> **Both are stated as open (§ 14 open 5a), not papered over.** [b]

`match::Command::update`'s only caller is `0x143c622d6` inside `0x143c62220` (a second `.impdata`
reference is a CFG entry, not a call). Its 24 × `0xb4`-byte per-player command slots at `this+0x40`
are reset each frame by `0x1443081e0(slot, 0xb)`. A second `UCommandOutput::ScopedWrite` user is
`0x14540b040` in the `MatchOnline` band — remote/replay input injected as finished commands. [b]

**`UCommandInfo` is the netcode's ingress, not a stage of the local path.** Its three `ScopedWrite`
users — `0x1456e42c0`, `0x1456e4640`, `0x1456e4ee0` — all sit inside `OnlineCommandControllerImpl`
(nearest RTTI-attributed methods `0x1456e40e0[10]`, `0x1456e4110[16]`), and `CommandInfoRef` is also
built by `match::Online[57]` (`0x1456d5090`). **Nothing in the local pad path touches it.** The
skeleton's `VPadInput → VCommandInfo → UCommandOutput` pipeline picture is **wrong**: the local path
is `UPadInput → UCommandOutput`, and `UCommandInfo` is a parallel network channel. [b]

**A timing asymmetry worth stating once**, because it follows from § 2 and nobody would guess it:
`UPadInput` and `UCommandInfo` are `Pointer` records, so their writes are visible to readers
immediately with no commit; `UCommandOutput` is `Copy`, so a writer's bytes are invisible until
something commits it. That is where this channel's frame timing lives. [b]

### 7.2 The straight answer on tap/hold discrimination

**Yes, the pad layer does tap/hold discrimination — in exactly one place, and it is exact. No, the
default path does none at all.**

**The default path is a one-frame rising edge, for all 72 units.** `ThinkUnitBase::vf17`
(`0x1440d8000`) is:

```
if (this->+0x14 == 2 && this->+0x29 > 1)
      if (0x144310490(ctx->pad, this->buttonId, 2, 6, 0,0,0)) return true;   // multi-press, LongPass/Shoot only
return 0x14430f9b0(ctx->pad, this->buttonId, 0);
```

and `0x14430f9b0`, re-read in full for this write-up, is exactly:

```
bool Pressed(block, btn, k):
    if (k >= 0x63) return false                       ; 0x14430f9cc
    prev = frame(block, k+1)                          ; 0x14430f9d9
    if (prev[0] & (1<<32)) return false               ; 0x14430f9e1  discontinuity guard
    cur  = frame(block, k)                            ; 0x14430f9f5
    return (cur[0] & ~prev[0] & (1<<btn)) != 0
```

One frame, no hold, no dwell, no repeat, and `vf17` always passes `k = 0`. [b, end to end]

**The discrimination lives in a second, richer pattern engine**, used by only **7 functions
image-wide** (`0x1440d8b20`, `ThinkUnitPassAndGo::vf17` `0x1440e5280`, `0x1440e5d50`, `0x1440e5e90`,
`0x1440e8520`, `ThinkUnitTrapThrough::vf8` `0x1440e88f0`, `ThinkUnitFriendPress::vf8` `0x1440e9240`)
— so it is the exception, not the rule. The evaluator `0x14430fb40` walks a 40-byte node chain
**backwards** (`rbx = node + (count−1)*0x28`, then `sub rbx,0x28`), dispatching each node through one
of three tables chosen by its stick fields — C `0x148081710` (no stick), B `0x148081770`, A
`0x1480817d0` — with each handler returning a frame index (or −1) that becomes the search bound for
the previous node. So **node[0] is the earliest event and node[count−1] the most recent**, and the
whole chain must fit inside `window` frames (always `0x64` = the full ring at every call site found).

**The kind semantics, emulated** against a synthetic `0x1908` block (cursor = 50, button 21 driven,
one node per run, nodes built by the game's own builders, evaluator called exactly as the game calls
it):

| scenario → | never down | always down | 2-frame tap | 8 frames, released | still down now | 40-frame hold, released |
|---|---|---|---|---|---|---|
| **kind 8** | MATCH | . | MATCH | MATCH | . | MATCH |
| **kind 9** | . | MATCH | . | MATCH | MATCH | MATCH |
| **kind 1** (B=0) | . | . | . | . | . | . |
| **kind 2** (A=5) | . | MATCH | . | MATCH | . | MATCH |
| **kind 4** (B=5) | . | . | **MATCH** | . | . | . |

**kind 8 = "not held", kind 9 = "held", kind 2 = "held for at least A frames", kind 4 = TAP** — and
kind 4 is the **only** predicate that separates a tap from a hold. (The 8/9 pairing is the reverse of
what the builder ordering suggests, which is exactly why it was emulated rather than asserted.) [a]

**The tap law, exactly — and it is not a duration test.** The kind-4 handler (table C index 4,
`0x14430da30`, table at `0x148081710`) does this, re-read from PRISTINE for this repair pass:

```
0x14430da4a  movzx esi, byte ptr [rdx+0xc]     ; B  -- read as a BYTE
0x14430da51  mov ebx, r8d                      ; bound (the search bound from the next node)
0x14430da5a  call 0x14430d980                  ; RELEASE-edge search  -> eax = release index
0x14430da61  js  fail
0x14430da6f  call 0x14430d830                  ; PRESS-edge search from there -> eax = press index
0x14430da76  js  fail
0x14430da78  mov ecx,eax ; sub ecx,ebx ; dec ecx ; cmp esi,ecx ; jg MATCH
```

so **kind 4 matches iff `B > pressEdgeIndex − bound − 1`**. Indices count frames into the past, so
the quantity tested is **press duration *plus* release age**, not duration alone: with `B = 5` a
1-frame press matches for four frames after release, while a 4-frame press matches only on the single
frame after release. **The window closes on the press edge, not on the release.** The chapter's
earlier "kind 4 matches iff `d ≤ B − 1` … a tap is a press of at most 4 frames ≈ 67 ms" was the
emulation's marginal read of one sweep; its own caveat ("with `B=5, d=2` it matches only while the
release is 1–3 frames old") was the real law all along, and that emulated row stands as the worked
example. [b for the predicate, a for the emulated rows]

**`B` is computed at runtime, not stored**: every call site builds `B = (int)(0.08f · FPS + 0.5f)` —
`call 0x14533ea80` (the frame-rate getter; the same call is used one-second-at-a-time at
`0x1440e53e3`), `mulss [0x145e87854]` = 0.08, `addss [0x147850248]` = 0.5, `cvttss2si`. Verified for
this write-up at `0x1440e5519`–`0x1440e552e`. At 60 fps `B = 5`. **Two ceilings anyone re-aiming
that `0.08` must know**: the builders store `B` as a **dword** (`0x14430eee9 mov dword [r9+0xc],r8d`)
but both search helpers read it as a **byte** (`0x14430d9a3` / `0x14430d853
movzx r15d, byte ptr [rdx+0xc]`, where it doubles as the edge-search iteration cap), so any value
≥ 256 wraps mod 256; and the chain window is fixed at `0x64` = 100 frames at every call site, so
`B > 100` is inert. Useful range 1–100. [b]

### 7.3 What this means for realism item 2 — and the premise that fails [b]

**`ThinkUnitPassAndGo::vf17` is gated on RT-not-held + RB tap-or-hold. It never mentions A or LB.**
Two lazily-built chains, OR'd, re-read from PRISTINE for this write-up. **The node kinds are [a];
the composed chain-level predicate is [c]** — chain B's middle node is kind 1 with `B = 0`, which the
§ 7.2 emulation shows matching in *none* of its six standalone scenarios (kind 1's handler makes
`B = 0` mean "the press edge must fall on the search-bound frame itself",
`0x14430d8a7 inc edi ; cmp r15d,edi ; jl fail`). Inside a chain that reads as "the RB press edge
lands on the bound frame set by the following kind-2 node", i.e. "RB pressed and held ≥ A frames" —
**but the chain was never emulated end to end, so the word "hold" here is inference, not measurement.**

| chain | nodes | built at | guard |
|---|---|---|---|
| A (`0x1486b88d0`) | `[0] kind 8, btn 0x13 (RT)` ; `[1] kind 4, btn 0x15 (RB), B = round(0.08·fps)` | `0x1440e5508`–`0x1440e553f` | `0x1486b8920` |
| B (`0x1486b8930`) | `[0] kind 8, btn 0x13` ; `[1] kind 1, btn 0x15, B = 0` ; `[2] kind 2, btn 0x15, A = round(0.08·fps)` | `0x1440e548c`–`0x1440e54d8` | `0x1486b89a8` |

```
0x1440e5508  mov edx, 0x13 ; lea rcx,[rip+0x45d33bc]  (= 0x1486b88d0) ; call 0x14430edf0   ; kind 8
0x1440e5519  call 0x14533ea80 ; mulss 0.08 ; addss 0.5 ; cvttss2si r8
0x1440e5533  mov edx, 0x15 ; lea rcx,[rip+0x45d33b9]  (= 0x1486b88f8) ; call 0x14430eec0   ; kind 4 (TAP)
```

`vf17` is also **not a behaviour producer**: it returns a bool and stores a target player index to
`[behaviour+0x19]` (`0x1440e546b`); the command id comes from `vf12` (`0x1440e5270`).

**`ThinkUnitCursorChange` fires on the LB press edge.** It overrides **only** vtable slot 12 —
`0x1440e20b0` is `mov eax,0x37; ret`, three bytes and a return, verified — so its trigger is the
inherited `vf17`, the rising edge. Its button id is 18 = LB. **A "tap LB" binding therefore collides
unconditionally**, on frame 0, before a tap could possibly be distinguished.

**RB (logical 21) is genuinely unclaimed on the ball.** No attack-bank `ThinkUnit` uses it; its only
consumers are `PassAndGo`'s chains and the special-controls gesture table, both of which are *chains*
that additionally require RT state or a stick. That matches the game's own control-screen label
"RB = Special Controls". [a for the unit table, b for the chains]

**Two traps for anyone searching this family by name.** `ThinkUnitShoulder` is **not** the shoulder
button — it is the shoulder *barge*: its `vf12` (`0x1440e8fa0`) loads `3.0` from `0x1478504e8` and
calls `0x1440e90a0`, which squares it and compares against a distance (`0x1440e9119`); its button is
31 = Y in the defence bank. And `ThinkUnitPassAndGo` has **no** button id at all (33 = none) — it
bypasses the base test entirely. [b]

**The template to copy, if the feature is built:** `ThinkUnitFriendPress::vf8` (`0x1440e9240`) gates
on RT's *level* first — `if (0x144310750(pad, 19, 0))` → pattern `0x1486b89b0`, else `0x1486b8a90` or
`0x1486b8a30` — i.e. second-man press already means two different things depending on another
button's state, not on a timer. [b]

**The hook point, and it is not code.** `PassAndGo`'s two chains live at `0x1486b88d0` (2 × 40 B) and
`0x1486b8930` (3 × 40 B), in the PE's `.text` beyond its raw size — **uninitialised data, zero at
load, filled once by the TLS-guarded static initialiser inside `0x1440e5280`**. After the first
evaluation they are plain writable memory. Changing `node[i].mask` or `node[i].kind` retargets the
gesture with **no instruction patched and no cave**. Constraints, if anyone does it: write *after*
the first `vf17` call or the initialiser overwrites you; keep `+0x10 = 0` and `+0x20`/`+0x24` = −1.0
to stay on dispatch table C; the node `count` is the caller's literal (`mov r8d,2` at `0x1440e52f6`,
`3` at `0x1440e5331`) so a chain can only be *shortened* by making a node vacuously true (kind 10,
`0x14430d760`); and the `[behaviour+0x19]` target-index path (`0x1440e5463`) must still be reached.
**Nothing was written, applied or tested — this is a description of sites, not a patch.** [b]

A second, coarser site: the factory `0x1440e0c70` writes each unit's button id at `+0x08` and mode at
`+0x10`, so rebinding any unit to any button needs no code patch either — but it acts through `vf17`,
a press edge, so **it cannot express "tap"**. [a]

### 7.4 The "special controls" gesture table [a, with a caveat]

`0x1440d8b20` builds a global table: count at `0x1486adff0`, rows at `0x1486adff4`, stride `0x1b0` =
432 B (`imul rdx, rcx, 0x1b0; add rdx, rsi` at `0x1440d8ca0`). Row layout: `+0x00` command id,
`+0x04` flag, `+0x08` node count, `+0x0c` nodes (`0x28` each), `+0x19c` flags, `+0x1a0` two floats,
`+0x1a8` masked `& 0x1ff`. Emulated with the frame rate stubbed to 60 it produces **5 rows**:

| row | cmd | nodes (newest last) |
|---|---|---|
| 0 | `0x17` | RB kind 9 (held) ; mask `0x1` kind 1 + stick ±90°, mag 0.8 |
| 1 | `0x0f` | RB kind 8 ; mask `0x13` kind 1, B=12 ; mask `0x13` kind 1, B=12 ; stick kind 6, ±180°, mag 0.2 |
| 2 | `0x0f` | RB kind 8 ; mask `0x13` kind 4, B=12 ; stick kind 6, ±180°, mag 0.2 |
| 3 | `0x1b` | bit13 kind 1, B=24 ; stick kind 9 ±180° mag 0.2 ; bit13 kind 1 |
| 4 | `0x1b` | bit13 kind 1, B=24 ; bit13 kind 1 |

RB is the modifier on rows 0–2, and a **12-frame** gesture window is in use alongside the 5-frame tap.
**The builder has 42 static call sites and the emulated path executed 14, so 5 is a lower bound** —
the remaining rows sit behind branches (probably the control-scheme setting) that were not
enumerated. [a with the caveat stated]

---

## 8. The match random bundle — `URandomInfo` is the **seed store**

`0x1c` = 28 bytes, `Copy`, with `ScopedRead` and `ScopedWrite` but **no `ScopedWAndC` class at all**.
The skeleton read its shape off the copy thunk as 16 / 8 / 4; those are the thunk's *move widths*.
The **constructor `0x144322fd0`** (descriptor argument 5, `0x143c6a850` tail-jumps to it) zeroes the
record field by field, which gives the real boundaries and confirms 28 bytes a fourth time:

```
mov dword [rcx+0x00],0   ; 4
mov word  [rcx+0x04],0   ; 2   (+0x06 padding)
mov qword [rcx+0x08],0   ; 8
mov word  [rcx+0x10],0   ; 2   (+0x12 padding)
mov qword [rcx+0x14],0   ; 8   -> covers 0x00..0x1b = 0x1c
```

| off | type | meaning | readers | writers |
|---|---|---|---|---|
| `+0x00` | u32 | **LCG seed word.** Passed as `r8d` to `0x1443461c0(state, i, v)` at nine sites; also taken **mod 1000** at `0x143d70d70` | `0x14429d3f3`, `0x14429d703`, `0x14429da13`, `0x14429dd62`, `0x14429e6f9`, `0x14429b573`, `0x144248f7c`, `0x1441b574b`, `0x1441b5774`, `0x143c936ec`; `0x143d70d70` | **NONE FOUND** |
| `+0x04` | u16, low byte | **rotating index**: `movzx eax,byte[r+4]; div ebx; movzx eax,dl`, then a table index | `0x14426dfa5`, `0x14426dc75`, `0x14426d09d` | **NONE FOUND** |
| `+0x08` | f32 | **the per-possession float** — `0x145653e5f: mov ecx,[r+8]; mov [rdi+0x14],ecx` **is** `ball-carrier-brain.md`'s `BP+0x14` latch. Also `0x145658a03`, as a fraction of a duration | `0x145653e5f`, `0x145658a03` | **NONE FOUND** — see the risk below |
| `+0x0c` | u32 | a second LCG seed word | `0x143d6f56d` | **NONE FOUND** |
| `+0x10` | u16, low byte | a small integer turned into a float scale (`cvtdq2ps; divss; addss`) | `0x143ec039e` | **NONE FOUND** |
| `+0x14` | u32 | **no reader and no writer found** | — | — |
| `+0x18` | u32 | **the match master seed** | `0x140e36ee0` (`mov eax,[rcx+0x18]`), called at `0x143caf0ab` to seed a long-lived state at `obj+0x1a6c` | `0x1453dea71` (match start) and `0x14570a2df` (online record-apply `0x14570a180`) |

**The RNG primitives, re-read for this write-up.** `0x1443461c0` is **not a seeder**, it is
`state[i] = v` (`movsxd rax,edx; mov [rcx+rax*4],r8d; ret`). `0x1443461a0` is the draw:
`x = 0x4513 − x*0x2D22B2E3` with bit 31 cleared, written back in place. `0x1443461d0` folds a state
(`s[3]^s[2]^s[1]^s[0]`). So the stream state is four `u32`s on the caller's stack or inside the
caller's object — for example `r15+0x1a6c` at `0x143caf0b3` — and **`URandomInfo` supplies the words
those states are seeded from.** It is neither the stream state nor a cache of draws. [b]

**The updater `ball-carrier-brain.md` open 10 asked for** is at `0x1453dea17`, inside the match-start
routine `0x1453dc560`:

```
lea rcx,[r14+0x275a0] ; call 0x143c4db70   ; rbx = URandomInfo BACK buffer
call 0x143b37540 ; call 0x143b374c0        ; a clock / tick source -> eax
imul r8d, eax, 0x64                        ; tick * 100
movdqa xmm0,[0x146ad6cf0]                  ; the 4-word initial LCG state constant
movdqu [rbp-0x31], xmm0
mov edx,1 ; lea rcx,[rbp-0x31] ; call 0x1443461c0   ; state[1] = tick*100
mov edx,1 ; lea rcx,[rbp-0x31] ; call 0x1443461a0   ; draw
mov edx,eax ; mov rcx,rbx ; call 0x140eb0b90        ; URandomInfo[0x18] = draw
```

`0x140eb0b90` is `mov dword [rcx+0x18], edx; ret` (verified). A sibling block at `0x1453ddc47` resets
the record (`0x143c4db70` → `0x144322ff0` → commit `0x145340a10`). The same `+0x18` is what the
**online** path writes — `0x14570a180` opens the only `ScopedWrite` on `URandomInfo` in the image and
calls the same setter. That is how two clients agree on a seed. [b]

### 8.1 The negative, and it is a risk flag on a finished chapter

**No writer exists in the image for `+0x00`, `+0x04`, `+0x08`, `+0x0c` or `+0x14`.** Search bounds,
so nobody repeats them: all three referrers of `VRandomInfoRef::?$ScopedWrite` (`0x14773c948`) — two
destructors and the online setter; all eight referrers of the `?$Copy` vtable and all five of
`RandomInfoRef`; the copy thunk `0x143c6a830`, which has **zero direct callers** (it is reached only
through `URegistryData+0x38` by the commit); all 28 callers of `0x1442d6fc0`, every one a read; and
all 381 callers of `0x143c4db70` filtered for a store at displacement ≤ `0x1c` within ten
instructions — 26 hits, all demo/camera records. [b]

Two readings survive and **I am not choosing between them**:

* **(a)** a writer exists on a path not closed. The strongest candidate is **`match::RandomControl`**
  (vtable `0x146aff6c0`, size `0xe0`, embeds its own `RandomInfoRef` at `+0x30` with accessor `+0x40`,
  read token `+0x78`, write token `+0x80`; ctor `0x143c6a230` from `0x143c53410`, deleting dtor
  `0x143c6a5d0`, derives from `match::record::Receiver`). It was not decoded.
* **(b)** those fields really are only ever zeroed — in which case the carrier's per-possession random
  `r` is **constant 0.0 all match**, `int(r*1500)`, `int(r*1200)`, `int(r*1300)` and `int(r*1600)` are
  all 0, and `Safety::canStart`'s `r < clamp((level−1)*0.5, 0, 1)` is always true above level 1.

**(b) would be a major correction to `ball-carrier-brain.md`** § *"The roll is fixed for the whole
possession"*, and to four of its tunables. **It is flagged as a risk, not asserted.** The cheapest way
to settle it is one live read: break at `0x145653e5f` and log `[rax+8]` across two possession spells.

### 8.2 RNG reach closure, with both controls [a]

Built on `funcs.func_chunks` (chained-unwind extents, **never `func_range`**), depth 6, cap 4000, LCG
target set `0x144345d80`–`0x1443461d0`:

| closure root | explored | LCG reached | min depth |
|---|---|---|---|
| **positive** — kick builder `0x14401a900` | 142 | **yes**, 3 edges | **2** (`0x143eafd30 → 0x144345d90`) |
| **negative** — `ChanceSpaceRun::vf5` `0x143df5950` | 144 | **no**, 0 edges | — |

Neither saturated (142 and 144 against a cap of 4000) and they give different answers, so the graph is
alive and this is not the merged-closure artefact that has bitten this project before. [a]

---

## 9. The per-frame order — what is and is not proven

**Honest answer: the registry cannot tell you the frame order, and this chapter does not invent one.**

What **is** established:

* Records are bound **once per match** into cached raw pointers (§ 4.3), so there is **no per-frame
  re-resolution** and the ordering cannot be inferred from resolve sites at all. `0x1453dc560`, which
  holds the image's largest block of write-resolves and commits (32 W / 49 C), is a match (re)start —
  it calls the holder constructor — **not** a per-frame publisher. [b]
* The one per-tick ordering fact recovered is the team-AI think `0x143d02c80` (§ 6.3), which writes
  the `UTeamAIInfo` reached through `0x1442d7090` — **the registry record's own front buffer**
  (§ 4.1); the stager/publisher pair `0x1456f1ff0` / `0x1456ea6d0` stages a copy and republishes it
  over that buffer. [b]
* `match::Command::update` `0x1440d4180` runs once per frame from `0x143c622d6`, and the `UPadInput`
  frame builder runs from `0x1453e7130` ← `0x1453e76f0` ← four sites in the `MatchOnline` band
  (`0x14540b780`, `0x14540ca60`, `0x14540d8f0`, `0x1454132f0`). **No scheduler was found that orders
  the pad update before `match::Command::update` within one tick** — the call chains are [b], the
  ordering between them is **[c]**. [b + c]
* Therefore off-ball selection, carrier decide and executor tick all read the record through
  `0x1442d7090` — i.e. through the `UModeInfo`-embedded `Ref`'s cached pointer, **which is the
  registry record's front buffer**. **CORRECTED:** this section used to end "for team state the
  blackboard is not on the gameplay hot path at all". The opposite is true — it **is** the hot path;
  what those subsystems skip is the registry *API*, not the registry *memory* (§ 4.1, § 10.1). [b]

What is **not** established: the tick order across subsystems. It has to come from the caller above
`match::Player::vf1` and `0x143d02c80`, which is outside this subsystem. Also open: **who calls the
commit `0x145340a10` and when in the frame** — 225 call sites, and `match::CommitRegistryListener`
(`0x143c66cd0`, 5 vtable slots) is the obvious entry point. That question decides when a `Copy`
record's back buffer becomes visible, so any runtime patch of a `Copy` record needs it answered
first.
---

## 10. The seams to the three finished chapters

### 10.1 The headline negative, with both controls [b]

Every `match::ai::*` (26 classes), `match::ai::bp::*` (65) and `match::player::*` (113) class from
`build/exe_map.json`, each vtable method resolved to its **chained-unwind** root and every chunk of
every root expanded (`funcs.func_chunks`, never `func_range`), intersected with the call sites of
**all four** registry entry points — read-resolve `0x145340c80` (439), write-resolve `0x1453415d0`
(386), the write wrapper `0x143c4db70` (381) and the commit `0x145340a10` (225): **1,431 distinct
sites** after de-duplication.

| subsystem | classes | vtable methods | roots | chunks | bytes | read | write | wrapper | commit | **union** |
|---|---|---|---|---|---|---|---|---|---|---|
| `match::ai` (off-ball) | 26 | 74 | 58 | 162 | 68,315 | 0 | 0 | 0 | 0 | **0** |
| `match::ai::bp` (carrier) | 65 | 237 | 187 | 535 | 123,415 | 0 | 0 | 0 | 0 | **0** |
| `match::player` (executors) | 113 | 450 | 370 | 900 | 306,273 | 0 | 0 | 0 | 0 | **0** |

**Positive controls, same method, same 1,431 sites**: `match::Player` (33 chunks, 5,741 B) → **7**;
`match::MatchControl` (44 chunks, 7,308 B) → **11**; `match::Match` (3 chunks, 4,096 B) → **1**.
Three tiny class-method sets find 19 sites between them; three sets 50–90× larger find none, so the
graph is not broken. **Negative controls**: `match::RecordReplay` (1 chunk, 161 B) and `match::Command`
(2 chunks, 375 B) → 0 each, as expected for classes whose registry work lives in their constructors.

> **Two scope limits, stated because they bound the claim.**
> **(1)** This bounds *vtable-method* code only. Free functions in the same bands (`0x1442efda0`,
> `0x1442f9a90`, `0x143d02f07`, …) are in no vtable and are outside the measured set.
> **(2)** The band histogram is only partly clean. The off-ball selector band
> `0x143d50000–0x143e10000` contains exactly **0** sites and the carrier band
> `0x145650000–0x145690000` exactly **0**. But the executor band `0x1441b0000–0x1442c0000` has **9**
> union sites — all accounted for: 3 in `match::Player`'s own methods (root `0x144241990`), 2 in
> `UPlayData`'s accessor thunks (`0x1442874a0`, `0x1442875c0`, adjacent to its descriptor
> `0x144287520`), and 4 in record plumbing (`0x144232950`, `0x144288360`, `0x1442b89e0`). **None is
> an executor**, and the class-bounded count for `match::player` remains 0. Stated this way rather
> than "the band is empty", which is no longer true. [b]

**The rule this establishes, and it is the most useful sentence in the chapter:** owners resolve
**once**, cache the raw pointer, and the decision code then works on that pointer with no registry
API in sight. ***Absence of a registry reference inside a subsystem is therefore not evidence that
the subsystem ignores a record*** — that exact mistake produced a wrong negative in this very file,
retracted in § 15, and a second one in the first draft's § 4.1, retracted in § 12.7 R4.

> **Do not read this table as "the blackboard is off the hot path".** The first draft did, and it was
> wrong: the cached pointer *is* the record's front buffer (§ 4.1). What these three subsystems skip
> is the registry **API**, not the registry **memory**.

### 10.2 The notation unification, with addresses

| chapters' name | actually | how to fetch it | proof |
|---|---|---|---|
| `team+0x…` (ball-carrier-brain.md), `teamAI+0x…` (match-ai-decoded.md) | **`UTeamAIInfo`**, `0xbd8c` = 48,524 B, one per team, reached through the `Ref` **embedded in `UModeInfo`** whose read cache sits at `+team*0x58+0x3450` — i.e. **the registry record's own front buffer** | `0x1442d7090(team)` — hundreds of call sites | [a] copy `0x143c43370` writes exactly `0x0..0xbd8b`, all identical, nothing past the end (§ 5.1); [b] the teardown's `ScopedRead`-dtor shape (§ 4.1) |
| `matchInfo+0x…` (match-ai-decoded.md), `matchWork+team*20+0x44` (player-executors.md), **and the object § 6.1 used to call "the constant table"** | **`UAnalyzeInfo`**, `0xed760` = 972,640 B, `Pointer`, single-buffered. Its decoded offsets are `+0x44+team*0x14`, `+0x25a9c`, `+0x25bbc`, `+0x25bcc`, `+0x25bd0`, `+0x25bd4+team*0x58`, `+0x273e8`, `+0x27490`, `+0x27538`, `+0x275a0`, `+0x28780` | `[mgr+0x48]` via the folded getter `0x140efd260` | [b] the `AnalyzeDetail` offset chain, exact to four sizes and three gaps (§ 5.3) |
| the registry `UTeamAIInfo` | the **same memory** gameplay reads, not a separate downstream copy; `0x1456ea6d0` republishes the staged back buffer over it. The copy `0x143c43370` moves the record **essentially in full** (48,287 of 48,524 B) — the earlier claim that it omits `+0xb4c`, `+0xb50` and the `+0x8078` block was an emulation artefact and is withdrawn | — | [a] § 5.1 re-run with `memcpy` hooked; [b] § 4.1 |

### 10.3 Named seam sites, per chapter

**To `ball-carrier-brain.md`:**

| its open item | status | the addresses |
|---|---|---|
| open 16, `team+0xb3c4` | **CLOSED** — the CPU's transient direct-play directive | writers `0x143d7c7f0` (set) / `0x143d7c7d6` (clear) in `0x143d7c5b0`, value from `0x143d7b650`, called from the think `0x143d02c80` at `0x143d03150` |
| open 16, `team+0xb44d` | **CLOSED** — `(team+0xb450 >= 4)` | `0x143d02ef0` / `0x143d02f07`; mirror `+0xb44e` at `0x143d02f15` / `0x143d02f2c` |
| open 16, `team+0xb3bd` | **partially** — writer found, meaning not | `0x143d03561`, from `0x143d0f290(modeInfo, teamIdx)` |
| open 16, `team+0x204` | **partially** — a sub-analyser output, not a setting | `0x143d02e28` from `[think+0x6358]` after `0x143d6eea0` |
| open 16, `team+0xb4c` / `+0xb50` | **still open, and the reason given for reopening it was wrong.** They **are** in the record's copy (first `memcpy`, § 5.1) | the only surviving signal is that no writer to them was found in the team-AI band, which a displacement sweep on offsets this small cannot settle either way. Start from `ctx+0x28` at the Cross post-roll site `0x14567b5c1` |
| open 10, the match random bundle | **CLOSED for `+0x18`**, and one of its guesses corrected | `*(g+0x790)` is the `URandomInfo` front buffer; `+0x00` is an **LCG seed word, not a tick counter**; the latched float is `+0x08` (`0x145653e5f`); updater `0x1453dea17` in `0x1453dc560` |
| "no tactical-instruction channel exists" | **CORRECTED — see § 12** | `0x1442e1200` over `UAnalyzeInfo+0x273e8`/`+0x27490`, 271 sites; and indirectly `UTeamAIInfo+0x8078` |
| opens 8 / 14, `entity+0x41` | **correctly re-aimed, still open** | `byte[entity+0x41]` is a straight copy of `match::Player+0x7f49`, made at `0x1441574bc`/`0x1441574c4` inside the marshaller `0x144157270` (16 chunks, `0x144157270`–`0x144159228`). **Exactly one `disp32` site exists for `+0x7f49` in all of `.xcode` and it is that read**; a sweep of `0x7f00..0x7f60` on any non-stack base finds no writer. The pad channel does **not** explain it. Next lead: `0x144641700` |

**To `match-ai-decoded.md`:** the attack level `team+0xb450` now has full provenance — setting
`+0xb454` (default **5 = AI-driven**), converter `0x143d04830`, AI walk ±1 bounded [0,4], previous
value mirrored to `+0xbd38`, ceiling `cmovg eax,4` at `0x143d048f0`. And its `matchWork+…+0x44`
defensive line is `UAnalyzeInfo+0x44+team*0x14`, read at `0x143d24d9e` inside `0x143d24d60`
(51 call sites) — **writer still not located**, but now in a named record.

**To `player-executors.md`:**

| its open item | status | the addresses |
|---|---|---|
| "`0x144261f10`'s run-phase state machine" | **RE-OPENED. The "it is pad-driven" claim is WITHDRAWN** (§ 5.6) | `0x144261bd0` (the function immediately preceding `0x144261f10`, reached via `0x144263f60`) opens **no registry scope**: no call to `0x144287790` — itself a `Scoped*` *destructor*, not a ctor — and none to `0x145340c80` / `0x1453415d0` / `0x143c4db70` / `0x145340a10`. What it really does: `elapsed = matchSettings+0x3318 − [this+0x68]` (its **own** timestamp; `0x144261be6 mov r13,rcx`, so `r13` = `this` and `rdi` = arg 2), converted to float, passed through `0x140a22910` (an `and 0x7fffffff` — absolute value), truncated, and compared against `int(FPS·0.4+0.5)` = 24 frames at 60 fps (`0x144261bfb`–`0x144261c38`); then `UAnalyzeInfo+0x28780` (must be `> 0x15`, via `0x1442de630`), `UAnalyzeInfo+0x25bcc` (must be `≤ 0x15`) and `UAnalyzeInfo+0x25a9c[idx]` through `0x143c71ee0`. **The pad→executor link is not established.** |
| "`CommandOutputRef` constructed inside the executor parent" | **confirmed and enumerated** | set-piece band `0x1442059d0` (nearest vtables `ActionPenaltyKick` / `ActionCornerKick`, called from `0x144141500` ← `0x144140fd0`), pass-reception band `0x144285920` (nearest `PassGetRouteBallFollow`), CPU side `0x1442d0050` / `0x1442d12d0`. **Which field each reads is open** — none was emulated |
| the stray `+0x190e8` unwind funclet | **confirmed and refined** | the "neighbouring constructor" is `match::Player`'s own ctor `0x144140fd0`; the executor ctor `0x144141500` is its callee (called at `0x144141003`) |
| its `matchWork+team*20+0x44` tunable | **now in a named record** | `UAnalyzeInfo+0x44+team*0x14` — `Pointer`, single-buffered, no commit; writer not located |

---

## 11. Tunables

Sharer counts are from `tools/exe_census.py cell <va> --all`, **run for this write-up**. Every
constant named below for the directive, pad and executor paths came back **shared**, several of them
enormously — so none of those may be written in place; where a route exists at all it is "re-aim that
one instruction's `disp32` at a private cell". **The gesture builder additionally holds two genuinely
PRIVATE cells**, added in this repair pass because the original sweep never looked there:

| private cell | value | sole referrer | what it parameterises |
|---|---|---|---|
| `0x146b9f990` | `0.204f` | `0x1440d8dd8`, in `0x1440d8b20 >match::Command` | a magnitude row of the special-controls gesture table (§ 7.4) |
| `0x146b9f998` | `-82.5f` | `0x1440da655`, same function | a stick-angle row of the same table |

Both report `STATUS=private refcount=1 private=True same_function_only=True` — **the only
in-place-editable (data-page write) constants found anywhere in this subsystem.** Their near
neighbours are only *nearly* private (`0x146b9f994 = 82.5f` ×2, `0x14624547c = −52.5f` ×2,
`0x146245464 = 52.5f` ×5) and the rest of that function's angle vocabulary (±90 ×71/×1535, ±180
×37/×2256, ±135 ×310, ±45 ×110, ±30 ×96/×1078, ±60 ×58/×1512) is heavily shared. [b + census]

| what | site | route | effect | sharers | evidence |
|---|---|---|---|---|---|
| the tap window for every kind-4 node — the only tap/hold discriminator in the pad layer | `0.08f` at **`0x145e87854`**, read at `0x1440e54b5`, `0x1440e551e`, the gesture builder; `B = (int)(0.08·FPS + 0.5)` | exe code, **re-aim only** | lengthens the window in which a press still counts as a tap — the test is `B > pressIdx − bound − 1` (duration **+** release age), not `d ≤ B−1`. At 60 fps `0.08 → B = 5`. **`B` is stored as a dword but READ AS A BYTE** by both edge searches (`0x14430d9a3`, `0x14430d853`), so ≥ 256 wraps mod 256; and the chain window is fixed at `0x64` = 100 frames, so `B > 100` is inert. Useful range 1–100 | **44 referrers, shared** (`.tls$`) — and the `0.5f` at `0x147850248` has **7,052** | b for the predicate, a for the emulated rows, b for the arithmetic |
| `ThinkUnitPassAndGo`'s trigger gesture — which buttons, which predicate | the static pattern nodes at **`0x1486b88d0`** (2 × 40 B) and **`0x1486b8930`** (3 × 40 B), initialised once behind TLS guards `0x1486b8920` / `0x1486b89a8` | **RUNTIME-ONLY, live-process write. NOT app-writable — there is no file-side path of any kind** (not dt270, not a `.bin` the app writes, not a data table in the image). Needs an injector against a Denuvo-protected process, and the write must land *after* the first `vf17` call. **Untested.** | retargets the pass-and-go / overlap trigger to any button and any predicate. Currently RT-not-held + RB tap [a], or the chain-B form read as RB held ≥ A frames [c] | **none** — private per-pattern data objects in uninitialised `.text`, zero at load (2 referrers each, all four `lea`s inside `0x1440e5280`) | b (the write was **not** performed or tested) |
| any `ThinkUnit`'s button binding | factory `0x1440e0c70` writes `unit+0x08` (button id) and `unit+0x10` (mode) | runtime write into each constructed `match::CommandPlayer` | rebinds a unit to a different physical button with no code patch. **Cannot express "tap"** — the inherited `vf17` is a press edge | per instance: 24 players × 81 slots, all must be patched | a |
| stick dead zone / saturation / gain | `0.20` **`0x1478501c0`**, `0.95` **`0x145e8788c`**, `0.75` **`0x145a8dd6c`**, at `0x14431aa26`–`0x14431aa47` | **NOT SAFELY TUNABLE** | changes the magnitude curve for **both sticks on every pad**, and the three are interlocked: `(0.95−0.20)/0.75 = 1.0` exactly | **1,165 / 77 / 229 referrers**, all shared | b + census |
| the age window the executors' run-phase machine's predecessor applies | `0.4f` **`0x145b2a690`**, read at `0x144261c21`, **inside `0x144261bd0`** (not inside `0x144261f10`; `func_root(0x144261c21) = 0x144261bd0`) | **NOT SAFELY TUNABLE** | how far that function's **own** timestamp `[this+0x68]` may sit from the match frame counter `matchSettings+0x3318` (absolute difference, via the `and 0x7fffffff` helper `0x140a22910`) — 24 frames at 60 fps. **Nothing from `UCommandOutput` enters it** (§ 5.6) | **623 referrers, shared** | b + census |
| the **durations** that time the direct-play directive | `7.0f` **`0x145c36ac0`** and `14.0f` **`0x145c38ba8`** (plus the `5.0f` default `0x145a8dd78`) in `0x143d7c5b0`; `5.0f` `0x145a8dd78`, `8.0f` `0x145b52fbc`, `3.0f` `0x1478504e8`, `6.0f` `0x145ab244c` in `0x143d7b650` | **NOT SAFELY TUNABLE** (shared) — but **not pointless**: these decide how long the CPU stays in direct-play mode | each is the `secs` in `frames = int(FPS·secs + 0.5)`, compared against the frame counter `modeSettings+0x3320`. `0x14533ea80` is the **frame-rate getter**, not `rand01()` — see § 6.1 | **398 / 183 / 1,885 / 829 / 1,761 / 646**, every one shared | b + census |
| the frame counter those timers compare against | `matchSettings+0x3320`, read via `0x1442d6de0()` at `0x143d7c660`, `0x143d7c6bf`, `0x143d7c7ad`, `0x143d7b81f`, `0x143d7b9c8`, `0x143d7ba9d`, `0x143d7bbbb` (36 read sites image-wide) | **not reachable** | a **frame-scale** quantity, sibling of the proven frame counter `+0x3318` and zeroed with it at `0x1442c3b51` / `0x1442c4af8`. **Not a difficulty setting** — it is compared against `int(FPS·secs+0.5)`. Exactly *what* it counts is [c] | n/a — a runtime field, not a constant | b for the shape, c for the semantics |
| the attack-level **setting** `team+0xb454` | `0x1442eff0a` `mov dword [rbx+0xb454], esi` (`89 b3 54 b4 00 00`) with `esi = 5` set at `0x1442efdd7` (`be 05 00 00 00`), inside `UTeamAIInfo::reset` | **NO STATIC ROUTE EXISTS** | pinning 0–4 would take the level out of the AI's hands: 4 makes `+0xb44d` permanently set (every cross plan skips its roll, MiddleShot always takes +40), 0 sets `+0xb44e` | **Re-aiming `0x1442eff0a` cannot do it** — it is a *register* store, so re-aiming only relocates the write and leaves `+0xb454` at its post-`memset` 0, i.e. pinned to the **minimum**. The `5` is an imm32 at `0x1442efdd7` shared with five other consumers — two call arguments (`mov edx,esi` at `0x1442efdf2` / `0x1442efe36`), `0x1442efea5 mov [rbx+0x91b8],esi`, `0x1442f0000 mov [rax-0x221c],esi` (**this is the `+0x91bc+4i` array store**: inside the 11-iteration loop, *after* the mid-loop `lea rax,[rax+4]` at `0x1442effdc`, so `rax = team+0xb3d8+4i` and `rax−0x221c = team+0x91bc+4i`) and `0x1442f00f9 mov [rbx+0x128],esi` — and the 6-byte store has no room for a `mov dword [rbx+disp32], imm32` form. Pinning a chosen 0–4 needs a **runtime write after reset, or a cave** | b for the bytes; the converter and the 0..4 ceiling (`cmovg` at `0x143d048f0`) are b and hold |
| the per-team tactics block `UTeamAIInfo+0x8078` | approach code at `B+0xd64+set`; defaults `0x1442c0840`; setup writer `0x1454023ac` | **origin NOT traced** — listed because a team-tactics record is where a lever *should* live | the approach code selects the `+0xb3c4` behaviour arm; the seven instruction bytes gate through `0x1442dd8d0` | per team, per match | **c** — do not act on it until § 14 open 2 closes |
| `UAnalyzeInfo`'s instruction tables | `+0x273f0`/`+0x27430` and `+0x27498`/`+0x274d8`, read by `0x1442e1200` at **271 sites** | **not reachable yet** — **no `disp32` writer exists** | gates behaviour across the off-ball selectors, the executors and the carrier; 18 kinds; `255` = wildcard | one instance per match, 2 teams × 4 slots × 2 sets | b — the highest-value open item in the subsystem |
| `UAnalyzeInfo+0x44+team*0x14`, the defensive line X `player-executors.md` flags | read at `0x143d24d9e` inside `0x143d24d60` (51 call sites) | **not reachable** | sweeping it walks a marker from fully zonal to fully man-marking (per that chapter's emulation) | per team, one match-wide record | b — the record is now named; the writer is not |
| `URandomInfo+0x18`, the match master seed | `0x1453dea17`–`0x1453dea71` in `0x1453dc560` | **not reachable** | fixing it would make every match's derived RNG identical; it is the single entropy input, and it comes from the clock | `0x146ad6cf0` is a **shared** 16-byte literal (61 raw referrers image-wide, and `exe_census.py` does not classify it as a gameplay constant), copied into a stack RNG state by the single `movdqa` at `0x1453dea43`. **Never edit it in place**; re-aiming that one `movdqa` is the safe form if anyone ever needs to — the table's own rule, which the earlier "do not re-aim it" inverted. Its four consecutive dwords `{0x2f3d0, 0x2f3d1, 0x2f3d2, 0x2f3d3}` look like an initial state vector, but that is **[c]**: the cell abuts a wide string at `+0x10` | b |
| `URandomInfo+0x08`, the carrier's per-possession random | read at `0x145653e5f`; **no writer located** | **not reachable** | if reading (b) in § 8.1 is right, this is constant 0.0 and forcing it non-zero would restore variety to Cross / MiddleShot / CurveShot / Long and re-enable Safety's level gate | n/a | b — **must not be treated as a lever until the live read settles § 8.1** |

### NOT SAFELY TUNABLE — the rows that were earned the hard way

| what the project believed | the truth | why it must come off the list |
|---|---|---|
| `team+0xb3c4` — "force cross / long-ball plans, disable Safety; the largest single on-ball lever found" (`ball-carrier-brain.md` tunables table) | a **transient AI directive**, set by `0x143d7c7f0` from `0x143d7b650` and force-cleared by `0x143d7c7d6` (mode gate or timer test), both inside `0x143d7c5b0`, called once per tick from `0x143d02c80` at `0x143d03150` | there is no file, no table and no persistent setting behind it, so it comes off the **authorable** list. It does **not** come off the runtime list: the earlier "a write from outside is overwritten within one tick" was wrong — a non-zero value **survives** while `modeSettings+0x3308 == 1`, `teamAI+0x28d != 0` and `int(FPS·secs+0.5) >= modeSettings+0x3320` (§ 6.1). Untested. [b] |
| `team+0xb44d` — "bypass the cross roll, guarantee MiddleShot's +40" | exactly `(team+0xb450 >= 4)`, recomputed every think tick | tuning it separately desynchronises it from the off-ball quota tables and every other attack-level consumer, **and the think overwrites it anyway**. If you want the behaviour, move the attack level. [b] |
| `team+0xb450` — the live attack level | rewritten every think tick by `0x143d04830` | writing it has no persistence. The `cmovg eax,4` at `0x143d048f0` is where the 0..4 ceiling lives if anyone ever wants to widen it — untested, and not recommended, since the quota tables are indexed by it. [b] |
| `team+0xb4c` / `+0xb50` | **unproven either way** (§ 5.1). They *are* carried by the record's copy — the "not in the copy" signal was an emulation artefact and is withdrawn | the only surviving signal is that all 57 image-wide `disp32` writers are outside the team-AI band, and a displacement sweep on offsets this small matches every struct in the image, so it cannot attribute them. **Still: nobody should tune them on the team base until `ctx+0x28` is identified** (§ 14 open 8). [b] |
| the `Copy`/`Pointer` flag, or a record's size immediate | `r9d` decides how many buffers exist and whether the commit runs; `r8d` is the allocation *and* `memset` length | flipping either changes the record's entire memory and concurrency contract, and desynchronises every offset in the image. Documented so the numbers can be trusted, never as a lever. [b] |
| any "just write the record at runtime" plan on a `Copy` record | writes must go to the **back** buffer and then be committed | a write to the front buffer is overwritten by the next commit; a write to the back buffer with no commit is never seen. **Decide which buffer before writing anything.** [b] |
---

## 12. CORRECTIONS TO FINISHED CHAPTERS

Six corrections, three of which change what a reader would do. Each names the exact text it corrects.

### 12.1 `ball-carrier-brain.md` — "no tactical-instruction channel exists" is WRONG [b]

The Refuted row reading *"No tactical-instruction channel and no other per-match setting is read
beyond the attack level"* must be rewritten. **A tactical-instruction channel exists, it is read by
the carrier's own band, and the chapter's own functions are among the 271 callers.**

`0x1442e1200(mgr, team, kind, value) → bool` reads `UAnalyzeInfo`'s two `AnalyzeDetailInstruction`
subobjects as `u32 kind[2][4]` / `u32 value[2][4]` (§ 5.3). Six of its call sites are in the carrier
band — **`0x145623990`, `0x145624630`, `0x14565bf80`, `0x14568f430`, `0x145699510`, `0x14569cb20`** —
and one is `0x1442f9a90`, the off-ball quota builder `match-ai-decoded.md` documents. 18 distinct
`kind` values are queried; `value = 255` is the wildcard, passed by 147 of the 271 sites.

**A second, indirect channel also exists**: the per-team tactics block `UTeamAIInfo+0x8078` (§ 5.2).
Here the chapter's *local* observation stands and only its global conclusion fails — a `.xcode`
sweep for displacement `0x8078` finds ~150 sites and **none** in `0x145650000–0x145690000`. The
carrier never reads the block; it reads `+0xb3c4`, `+0xb44d`, `+0x204`, which the team-AI think
**derives** from the block once per tick, `0x1442dffb0`'s 0–5 code being the switch inside
`0x143d7b650`.

**What must NOT be repeated:** the probe brief suspected `AnalyzeDetailInstruction` and one probe
returned it as a clean negative on the strength of its `Ref` referrer list. That reasoning is void
(§ 15.1) — but the *suspicion* was right, for a different reason. Both halves are recorded so the
next reader gets the method as well as the answer.

### 12.2 `ball-carrier-brain.md` — two rows must move from Tunables to NOT-tunable [b]

The row *"force cross / long-ball plans, disable Safety — per-match team dword `team+0xb3c4` … and
byte `team+0xb44d` … name and writer unknown … **the largest single on-ball lever found**"* is
wrong in its conclusion. `+0xb3c4` is the CPU's transient direct-play directive (§ 6.1) and
`+0xb44d` is `(attackLevel >= 4)` (§ 6.2). **Neither is a lever.** The chapter currently tells a
reader that these are the biggest on-ball levers in the game; they are not levers at all, and the
correct rows are in § 11's NOT-SAFELY-TUNABLE table.

Two sub-claims inside its open 16 also need fixing. It says *"`+0xb44d` has real writers
(`0x143d02f07`, `0x1442efeef`, both off-ball AI); `+0xb3c4` has **none**"*:

* the second address is off by one — the instruction is at **`0x1442efeee`**,
  `mov word ptr [rbx+0xb44d], r15w`, a **word** store covering `+0xb44d` and `+0xb44e` together,
  inside `UTeamAIInfo::reset` `0x1442efda0`, which is a **default initialiser**, not "the off-ball AI
  band" in any behavioural sense;
* `+0xb3c4` **does** have writers — `0x143d7c7f0`, `0x143d7c7d6`, plus `0x1442efedd`'s qword zero at
  `+0xb3c0`. Both fields arrive by the same route after all: the team-AI think.

And its `team+0xb4c` / `+0xb50` row, listed under a heading of `UTeamAIInfo` fields, is **unproven
and contradicted by the copy** (§ 5.1). The chapter's own text says they are reached via `ctx+0x28`;
the safest fix is to keep them under `ctx` and stop calling them team fields.

### 12.3 `ball-carrier-brain.md` open 10 — answered, with one of its guesses corrected [b]

> open 10: *"the match random bundle's updater (the function writing `*(g+0x790)+8`) and what `+0`
> holds (tick counter, by usage)."*

`*(g+0x790)` is the `URandomInfo` **front buffer** (the `Ref` at `*0x1486bd888 + 0x748`, read cache
at `+0x790`, returned by `0x1442d6fc0`). **`+0x00` is not a tick counter** — it is an LCG seed word,
fed to `state[i] = v` (`0x1443461c0`) at nine sites and taken mod 1000 at a tenth. The float the
chapter's `BP+0x14` latches is **`+0x08`** (`0x145653e5f: mov ecx,[rax+8]; mov [rdi+0x14],ecx`). The
updater is `0x1453dea17` inside `0x1453dc560`, and it writes `+0x18`, the match master seed. The
record is **28 bytes, not 192**.

**And a risk flag on the same chapter** (§ 8.1): its section *"The roll is fixed for the whole
possession"* rests on `BP+0x14` being a random number in [0,1). `BP+0x14` is latched from
`URandomInfo+0x08`, and **no writer for `+0x08` exists anywhere in the image** after five exhaustive
searches. If none exists, `r` is constant 0.0 all match and four of that chapter's tunables collapse.
**Not asserted** — `match::RandomControl` is undecoded and is the plausible writer. Settle it with
one live read at `0x145653e5f` before touching anything downstream.

### 12.4 `match-ai-decoded.md` — the attack level is AI-driven by default, and it is a `u32` [a + b]

The chapter treats `byte[team+0xb450]` as *the* attack level and stops there. It is the **live** level
(0–4), derived every think tick by `0x143d04830` from the **setting** at `+0xb454`, whose shipped
default is **5 = "let the AI drive it"** — so out of the box the AI walks the level ±1 per tick within
[0,4]. Any quota tuning premised on a stable per-team attack level needs that caveat. Minor: the field
is read as a **dword** (`cmp dword ptr [rax+0xb450], 4` at `0x143d02efe`), not a byte.

Its `matchWork + team*20 + 0x44` defensive line is `UAnalyzeInfo + 0x44 + team*0x14` (§ 5.3) — a
`Pointer` registry record, single-buffered, writer still not located.

### 12.5 `player-executors.md` — SEVEN registry `Ref`s, not nine [b]

The executor parent constructs **seven** registry `Ref`s as fixed subobjects, not nine.
`CommandOutputRef` and `DemoInfoRef` are **not** `match::Player` subobjects. `0x144140fd0` —
`match::Player`'s constructor, entered from `0x144143700`, which calls the executor-building phase
`0x144141500` at `0x144141003` — stores exactly seven `Ref` vtables (§ 5.7), and a capstone scan of
the executor constructor's full chained extent `0x144141500..0x14414268d` finds **zero**
`match::registry` vtable references. `CommandOutputRef` is built by `match::Command` `0x1440d2970`,
`match::CommandPlayer` `0x1440dd750`, `match::record::Record` `0x144285920` and the camera plugins;
`DemoInfoRef` by `match::demo::DemoBase` `0x1440ea5c0` and
`match::camera::plugin::InplayCamera` `0x1440b0560`.

This also confirms and refines that chapter's own 2026-09-19 note: the "neighbouring constructor"
owning the stray `+0x190e8` `UCameraTargetInfo` funclet **is** `match::Player`'s constructor, and the
executor constructor is its callee. The chapter was right to withdraw "exhaustive by construction".

Its open item *"`0x144261f10`'s run-phase state machine"* **stays open.** This chapter previously
told that chapter the machine was "closed at one end — pad-driven, through `0x144263f60` →
`0x144261bd0`, a `UCommandOutput::ScopedRead` with a 0.4-second command-age gate". **That correction
is withdrawn in full** (§ 5.6, § 10.3): `0x144261bd0` opens no registry scope, `0x144287790` is a
`Scoped*` destructor rather than a constructor, `0x144261cf0` is not an instruction boundary, and the
0.4-second test is an age on the function's **own** timestamp `[this+0x68]` against the match frame
counter `matchSettings+0x3318` — and it sits in `0x144261bd0`, the function immediately *preceding*
`0x144261f10`, not inside it. **Nothing from `UCommandOutput` enters it.** The offsets it reads
(`+0x25bcc`, `+0x25a9c`, `+0x28780`) are `UAnalyzeInfo`'s.

### 12.6 `docs/realism-todo.md` item 2 — the plan as written is dead, and the fix is cheap [b + a]

The item states: *"`ThinkUnitPassAndGo` slot 17 (`0x1440e5280`) produces both the L1+A 'go' and R1+A
'overlap' behaviours"* and *"Both shoulder-alone functions are holds, so a **tap** is free"*, with two
stated open risks. All four points need changing:

1. **`PassAndGo::vf17` is gated on RT-not-held + RB tap-or-hold** (logical `0x13` and `0x15`), never
   on A (24) or LB (18), and it produces **no behaviour** — it returns a bool and a target index; the
   command id comes from `vf12` (§ 7.3).
2. **"Both shoulder-alone functions are holds" is false.** LB-alone is `ThinkUnitCursorChange`, which
   overrides only `vf12` and therefore fires on the **press edge**. **A tap of LB is not free.**
3. **Open risk (a), "whether Cursor Change fires on the press edge": ANSWERED YES.** The LB half of
   the feature is dead as specified.
4. **Open risk (b), "whether the pad layer does tap/hold discrimination at all": ANSWERED YES, and
   quantified.** Pattern-node kind 4, matching iff **`B > pressEdgeIndex − bound − 1`** — the press
   edge must be no more than `B` frames back, i.e. press duration **plus** release age ≤ B, with
   `B = (int)(0.08·FPS+0.5)` = 5 at 60 fps. (Not "a press of at most 4 frames"; see § 7.2.) Nothing
   new has to be written to *detect* a tap.

**RB (logical 21) is the button that is actually free on the ball**, and the cleanest hook is a
**live-process** data write to the pattern nodes at `0x1486b88d0` / `0x1486b8930` — no code patch, no
cave, but equally **no file-side route**: this is an injector-against-Denuvo job, not something the
app can ship (§ 7.3, § 11). The item should be rewritten around RB before any work starts.

### 12.7 CORRECTIONS TO **THIS** CHAPTER — repair pass, 2026-09-19

Three adversarial reviews were run against the first draft. Every finding below was **re-checked
against the bytes before being applied**; two of the reviewers' own supporting claims turned out to be
wrong and are recorded as such rather than propagated. Backup of the pre-repair text:
`scratchpad/registry-blackboard.before-repair.md`.

| # | what the chapter said | what the bytes say | evidence | where fixed |
|---|---|---|---|---|
| R1 | "The copy `0x143c43370` is **selective** — 13,619 of 48,524 bytes, not a `memcpy`"; `+0xb4c`, `+0xb50` and the `+0x8078` block "not in the copy" | The function contains **two straight-line `memcpy` calls** the harness silently skipped: `0x143c44503` (`r8d=0x7900`, `0x778..0x8078`) and `0x143c4451c` (`r8d=0xe6c`, `0x8078..0x8ee4`). `0x144f8307a` → IAT `0x1459fd820` = `VCRUNTIME140!memcpy`. Re-run with both thunks hooked: **48,287 bytes**, max `0xbd8b`, nothing past the record, `+0xb4c`/`+0xb50`/`+0x8ddc` all arrive identical | [a] `emu6` re-run; [b] capstone + PE import directory | § 5.1, § 10.2, § 11 (both tables), § 13.6, § 15.6 |
| R2 | The directive's release is a **probability**: `int(rand01()*p + 0.5) >= modeSettings+0x3320`; the six floats are "the probabilities"; `+0x3320` is "the difficulty threshold"; a runtime write is "overwritten within one tick" | `0x14533ea80` is `movss xmm0,[rip+0x38e4034]; ret` → the global float at `0x148c22abc`, written only by `0x140a14d9e` as `float(int global)` — **the frame-rate getter the chapter itself names in § 7.2**. No RNG call exists in `0x143d7c5b0`. The floats are **seconds**; the test is `int(FPS·secs+0.5)` vs a **frame counter**; the release is deterministic, and an injected value survives while the two mode gates and the timer hold | [b] capstone at `0x14533ea80`, `0x140a14d90`, `0x143d7c76b`–`0x143d7c7b3`; `+0x3320` zeroed with `+0x3318` at `0x1442c3b51` / `0x1442c4af8` | § 6.1, § 4.1, § 11 (3 rows), § 13.4, headline, enables table |
| R3 | `+0x25bcc` and `+0x25a9c` are **`UCommandOutput`** fields; `0x144261bd0` "opens a `UCommandOutput::ScopedRead` (ctor `0x144287790` at `0x144261cf0`)"; the run-phase machine is "pad-driven" | Both offsets exceed `UCommandOutput`'s own 0x13b20 allocation and are read off `0x140efd260` = `[x+0x48]` = **`UAnalyzeInfo`**. `0x144261bd0`'s 16 call targets contain **no** registry entry point and **no** `0x144287790` — which is itself a `Scoped*` **destructor**. `0x144261cf0` is not an instruction boundary. The 0.4 s test is `matchSettings+0x3318 − [this+0x68]`, a self-timestamp age | [b] capstone `func_chunks(0x144261bd0)`, full call-target sweep, `0x144287790`, `0x140efd260` | § 5.6 (record now has **no** decoded fields), § 5.3 (offsets moved in), § 3, § 7.1, § 10.3, § 12.5, § 11, § 14 open 12 |
| R4 | `UModeInfo` "holds the **live, authoritative** per-team records that the registry later publishes snapshots of"; for team state "the blackboard is not on the gameplay hot path at all"; the commit "can never introduce a value from outside the record" | `base+0x3450` / `+0x3500` are **`Ref+0x48` read caches**: the teardown `0x1442d5500` walks them with the exact `ScopedRead`-destructor shape (token `+0x48`, object at token−`0x38`; `ScopedWrite`'s `+0x50`/−`0x40` does not match), and `0x1442d0050` builds the `Ref`s at `+0x3408`/`+0x34b8`/`+0x3568`. So the "live object" **is** the registry record's front buffer | [b] capstone `0x1442d5896`–`0x1442d58f8`, `0x1453e2580`, `0x1453f1400`, `0x1442d09a8`–`0x1442d09f6` | § 4.1, § 10.2, "the machine in one paragraph", § 6.1 epilogue, § 13.16 |
| R5 | "kind 4 matches iff `d ≤ B − 1`… **a tap is a press of at most 4 frames ≈ 67 ms**" | The handler finds the **release** edge, then the **press** edge before it, and tests `B > pressIdx − bound − 1` — duration **plus** release age. Also: `B` is written as a dword and **read as a byte** by both searches (wraps at 256), and the chain window is fixed at `0x64` = 100 frames | [b] capstone `0x14430da30`, `0x14430d980`, `0x14430d830`, builders `0x14430eec0`/`edf0`/`edb0`/`ee30` | § 7.2, § 11 row 1, § 12.6 item 4, enables table |
| R6 | "every one of the **30** `Copy` descriptors… every one of the **15** `Pointer`" | **33 / 12**, which is also what § 3's table says. Re-derived over all 45 descriptors | [b] fold of `r8d`/`r9d` at all 45 registrar call sites | § 1.3 |
| R7 | The attack-level setting is reachable by "re-aim the store at `0x1442eff0a`" | `0x1442eff0a` is `89 b3 54 b4 00 00` — a **register** store. Re-aiming relocates the write and leaves `+0xb454` at 0, pinning the **minimum**; the `5` lives in a different instruction shared with five consumers, and the 6-byte store cannot take an imm32 form. **No static route exists** | [b] PRISTINE bytes at `0x1442efdd7` / `0x1442eff0a`; esi consumer sweep | § 11 |
| R8 | The pattern-node row's route is "**app-writable** in the runtime sense only" | There is no file-side path of any kind; it needs an injector against a Denuvo-protected process, and the enables table already says "nothing in this subsystem is app-writable". Contradiction removed | [b] census (2 referrers each, both `lea`s in `0x1440e5280`); § 13.2 | § 11 row 2, § 12.6 |
| R9 | The Tunables preamble: "every count below came back **shared**" — with no private row | True of what was listed, but the sweep never covered the gesture builder `0x1440d8b20`, which holds **two `refcount=1` private cells**: `0x146b9f990` = `0.204f` (sole referrer `0x1440d8dd8`) and `0x146b9f998` = `−82.5f` (sole referrer `0x1440da655`) | census `cell … --all`, run this pass | § 11 preamble |
| R10 | "Exactly one run group lands anywhere near this subsystem"; second `disp32` at `0x144311579` | **Three** cited functions carry patched bytes in the installed image — `0x144310ea0` (runs at `0x144311572` and `0x14431157a`), `0x1441a4280` (4 runs) and `0x143df6010` (1 run) | [b] full PRISTINE↔installed diff, runs mapped to chained-unwind roots | chapter header |
| R11 | § 7.1's channel diagram showed six confident `UCommandOutput` **consumer** arrows | They are `Ref` **vtable-store** (constructor) sites — the method § 15.1 declares void. And **no commit site exists** anywhere in `0x1440d0000–0x1440f0000`, so by § 2's own rule nothing written there is yet shown to be readable | [b] resolver site sets per band: 19 W / 5 wrapper / 1 R / **0 commit** | § 7.1, § 14 open 5a |
| R12 | § 13.16: nine "array-element `Ref` classes" share the NULL group getter, `CameraTargetInfoRef` among them | The NULL set is `{AnimeInfo, BallAttachOne, **BallExternalForce**, BallInfoOne, DemoPlayerInfo, OrderInfo, PlayerInfo, PlayerMove, TeamAIInfo}`; `CameraTargetInfoRef`'s `vf1` is `0x140efd270` = `lea rax,[rcx+0x58]` — an **instance** string, and the lead for the whole question. Only **five** records have `ArrayRef` instantiations, so the "array-element" framing is wrong | [b] `vf1`/`vf2` sweep of all 45 `<Name>Ref` classes; RTTI `ArrayRef` list | § 13.16, § 3.1 (new), § 14 open 11 |
| R13 | Minors, all verified and applied | `+0x3320` "difficulty threshold" → frame counter (§ 4.1 table); `rbp = team*4` → `rbp = team` (`movsxd rbp,edx` at `0x1442e1215`); `UPadInput` row pointed at § 5.6 → § 5.5; `UCommandOutput` row pointed at § 5.7 → § 5.6; counts "7 layout-partial / 37 size-only" → **6 / 38**; the 0.4 s gate attributed to `0x144261f10` → it is in `0x144261bd0`; "the AI walks it ±1 per tick" → conditional on `0x14533eb60`; "gate:" on the release → both conditions jump straight to CLEAR; "do not re-aim" the LCG literal → re-aiming is the *safe* form, editing in place is not; `other.0xb3c4 == 2` → **this** team's; `xmm6` default `7.0f` → `5.0f` | [b] each cited inline | throughout |

**Two reviewer claims that did NOT survive re-checking, and were therefore not applied:**

1. *"`func_chunks(0x1442d0050)` contains zero memory operands with displacement in `[0x3300,0x3600]`,
   so it does not build these `Ref`s."* **False.** It contains three: `0x1442d09a8 lea rcx,[rdi+0x3408]`,
   `0x1442d09cf lea rcx,[rdi+0x34b8]`, `0x1442d09f6 lea rcx,[rdi+0x3568]` — and `+0x48` on each gives
   exactly `0x3450`, `0x3500`, `0x35b0`. The reviewer's *conclusion* (R4) is right and is applied; this
   particular support for it is wrong, and the `lea`s make the case **stronger**. [b]
2. *"`esi = 5` feeds a **single** store at `+0x91b8`, not an indexed `+0x91bc+4i` pattern."* **False.**
   `0x1442f0000 mov [rax-0x221c], esi` sits inside the 11-iteration array loop *after* the mid-loop
   `lea rax,[rax+4]` at `0x1442effdc`, so `rax = team+0xb3d8+4i` and the store lands on
   `team+0x91bc+4i` — the chapter's original offset was right. (There **is** also a separate single
   store at `+0x91b8`, `0x1442efea5`.) Ground truth for the loop cursor: `0x1442effd5
   mov [rax-0x2488], r15d` is the known `+0x8f4c+4i` array, and `0x1442effc1 mov [rax-0xb178],
   0x3f800000` is the known `+0x25c+4i = 1.0f`. [b]

---

## 13. NEGATIVES

Each of these is a result, not an absence of work.

1. **No registry entry-point call exists in any `match::ai`, `match::ai::bp` or `match::player`
   vtable-method body.** 1,597 chunks, 497,993 bytes, 0 of **1,431** union sites across all four
   entry points; three positive controls found 19 between them in code sets 50–90× smaller; two
   negative controls found none. Scope limits in § 10.1. [b]
2. **No registry record is filled from dt270.** Zero dt270 getter calls (`0x145348d70`, 201 callers;
   `0x145349560`, 67) in the registry band `0x145340000..0x145342000`; of 216 functions holding a
   registry acquire and 150 calling a dt270 getter, the intersection is **2** — `0x143d41f00` and
   `0x1453ff220` — and in both the dt270 values and the record pointer never meet (in `0x1453ff220`
   all five dt270 reads precede the acquire at `0x1453ff925` and the acquired `UFieldInfo` is only
   read afterwards; in `0x143d41f00` they are 2.8 KB apart). **dt270 is read directly by its
   consumers; it does not enter shared state.** [b]
3. **There is no locking anywhere in the registry access path.** The only "release" function any
   `Scoped*` destructor calls is `0x140c83910` = `ret 0`. No mutex, no refcount, no fence. [b]
4. **`team+0xb3c4` is not app-writable and is not a setting.** Re-evaluated every think tick and
   force-cleared whenever the mode gate or the 7 s/14 s frame timer fails. Any plan to *author* it —
   in dt270 or anywhere else — is dead. **A runtime write is a different question and is not closed
   by this negative** (§ 6.1). [b]
5. **`team+0xb44d` is not an independent lever.** It is `(attackLevel >= 4)`. [b]
6. **WITHDRAWN as a negative: `team+0xb4c` / `+0xb50`.** This used to read "probably not
   `UTeamAIInfo` members", on two signals. Signal (1), "not written by the record's copy", was an
   **emulation artefact** — they sit inside `memcpy(dst+0x778, src+0x778, 0x7900)`, and the re-run
   with the import hooked carries them (§ 5.1). Signal (2), a raw `.xcode` sweep for displacements
   `0xb4c`/`0xb50`, cannot attribute an offset that small to a record at all. **Status: unproven
   either way**, and still not to be tuned on the team base until `ctx+0x28` is identified (§ 14
   open 8). [a + b]
7. **The tactics block at `UTeamAIInfo+0x8078` was NOT traced to any file.** The one writer found
   (`0x1454023ac` in `0x145401050`) only ever stores 0 or 1, which cannot install a 0–5 approach
   code. The landing map is half finished and says so rather than naming dt270 or `Team.bin` on a
   hunch. [negative]
8. **No `disp32` writer exists for `UAnalyzeInfo`'s instruction tables** (`+0x273f0`, `+0x27430`,
   `+0x27498`, `+0x274d8`). Every write my scan found in that numeric range belongs to
   `game_mode::MatchListener` (root `0x1453da1d0`), a *different* object whose `std::string` members
   land on the same offsets — the `0xf` SSO capacity stores give it away. [b]
9. **No writer exists for `URandomInfo` `+0x00`, `+0x04`, `+0x08`, `+0x0c`, `+0x14`**, after five
   exhaustive searches (§ 8.1). `+0x14` has neither a reader nor a writer. The record's copy thunk
   `0x143c6a830` has **zero** direct callers. [b]
10. **`UCommandInfo` is not part of the local pad→command path.** All three `ScopedWrite` users are
    inside `OnlineCommandControllerImpl`. [b]
11. **The default pad path does no tap/hold discrimination at all** — `ThinkUnitBase::vf17` is a
    one-frame rising edge for all 72 units; discrimination exists only in the pattern engine, used by
    7 functions image-wide. [b + a]
12. **LB is not free for the trigger-run feature**; **RB is**. [b]
13. **`ThinkUnitShoulder` has nothing to do with a shoulder button** — it is the shoulder barge, a
    3-metre proximity test (`0x1440e8fa0` → `0x1440e90a0`), on button 31 = Y in the defence bank. [b]
14. **`UFieldInfo` is 80 bytes, a flat POD, `Pointer`, read-only, with no write template.** The
    "1.4 MB pitch model" the skeleton implied does not exist. [b + a]
15. **`URegistryData` is not a `match::registry` record** — it is the registry's own 0x40-byte slot
    type. With `UBallPerson`, `UBallInfoOne` and `UBallAttachOne` it accounts for all four of the
    skeleton's extra names; the count is 45 either way. [b]
16. **The registry key of the nine NULL-group records is NOT derivable** — enumeration corrected in
    this repair pass. A `vf1`/`vf2` sweep of **all 45** `match::registry::<Name>Ref` classes splits
    them **35 / 9 / 1** (§ 3.1). The **9** with the NULL group getter `0x140c837d0`
    (`xor eax,eax; ret`) are `AnimeInfoRef`, `BallAttachOneRef`, **`BallExternalForceRef`**,
    `BallInfoOneRef`, `DemoPlayerInfoRef`, `OrderInfoRef`, `PlayerInfoRef`, `PlayerMoveRef`,
    `TeamAIInfoRef` (raw vtable read: `TeamAIInfoRef` at `0x146af53a0` is
    `[0x143c45b60, 0x140c837d0, 0x143c4aaf0]`). **Three fixes to what this entry used to say.**
    (a) `CameraTargetInfoRef` is **not** among them — its `vf1` is `0x140efd270` =
    `lea rax,[rcx+0x58]; ret`, so the group string is an **instance** member at `Ref+0x58`. That is
    the strongest lead for this whole question, not a dead end (§ 14 open 11).
    (b) `BallExternalForceRef` **is** among them and was missing from the list — and
    `UBallExternalForce` is not array-backed, which kills the framing.
    (c) The "every array-element `Ref` class" framing is wrong: only **five** records have `ArrayRef`
    instantiations in RTTI — `UOrderInfo` / `UTeamAIInfo` (`<2, HomeAway>`) and `UPlayerInfo` /
    `UAnimeInfo` / `UPlayerMove` (`<22, PlayerNo>`, plus `UPlayerMove <31>`). `UBallInfoOne`,
    `UBallAttachOne`, `UCameraTargetInfo` and `UDemoPlayerInfo` are **not** array-element classes, as
    the § 3 table's own `array` column already showed; read those two `UBall*One` rows as `Ref`-class
    name aliases of `UBallInfo` / `UBallAttach` and nothing more.
    The rest of the entry's evidence stands. Emulating `0x143c4e430(this, NULL, "INFO")`
    **faults reading address 0 at `0x143c4e473`** [a]; emulating the `ScopedRead` ctor `0x1453e2350`
    on a freshly built `TeamAIInfoRef` with the key builder hooked captures exactly
    `(rdx = NULL, r8 = "INFO")` [a]; the binder `0x143c4f080` has exactly 45 callers and all are
    descriptors [b]; and no `TEAM`, `AI_INFO`, `ORDER`, `MOVE` or `PLAYER_INFO` group string exists
    among the image's key stubs [b]. **Nobody may state the registry key for `UTeamAIInfo`,
    `UOrderInfo`, `UPlayerInfo`, `UPlayerMove` or `UAnimeInfo` until this is settled.** It does not
    disturb § 4 or § 5.1 — gameplay reaches those records through the `Ref` embedded in `UModeInfo`,
    which was bound once at construction, and never re-derives the key.
17. **Per-frame subsystem order is not recoverable from the registry** (§ 9). Returned unanswered
    rather than invented.
18. **"Read-only" is the absence of a convenience wrapper, not a guarantee.** `UPlayerInfo`,
    `UPlayerMove`, `UAnimeInfo` and `UBallInfo` have no `ScopedWrite`/`ScopedWAndC` template, but the
    free write-resolve `0x1453415d0` (386 sites) and its wrapper `0x143c4db70` (381) can write any
    record without one. **The producer of all four is untraced.** [b]
19. **No record in this subsystem has a complete field map**, and no new *app-writable* lever was
    found anywhere in it. The net result for the realism mod is two removals *from the authorable
    list* (`+0xb3c4`,
    `+0xb44d`), one runtime-only hook (the pad pattern nodes), and two named-but-unreachable targets
    (the `+0x8078` block, the instruction tables).
20. **Not proven, stated as such**: the meaning of any of the 18 instruction kinds; the field layout
    of `UMatchEnv`, `UMatchInfo`, `UCommandOutput`, `UPadInput`'s assignment descriptors,
    `UCommandInfo` or `URecordInfo`; that `URecordInfo` is a replay buffer (its size, access mode and
    holders are [b], the label is **[c]**); node kinds 0, 1, 3, 5, 6, 7, 10 standalone; and the
    `ThinkUnit+0x10` mode.
---

## 14. OPEN QUESTIONS

Ordered by value to the realism mod, not by difficulty.

1. **The writer of `UAnalyzeInfo`'s instruction tables** — the single highest-value item in this
   subsystem, because it is the only thing standing between the owner and an authorable tactical
   lever. Entry points: `0x143d00620` and `0x143d006a0` (off-ball band, virtual, no direct callers),
   both of which do `lea rcx,[[mgr+0x48]+0x273e8]` then call `0x144331a50` / `0x1443317c0`, which
   return an id `≤ 0x15`; plus the `AICoach` readers `0x1449da290`, `0x1449baa20`, `0x1449db850`,
   which index `+0x27540`…`+0x27584`. If the per-match tactic UI lands anywhere, it lands here.
2. **Where the tactics block `UTeamAIInfo+0x8078` comes from.** The 0–5 approach code at `B+0xd64+set`
   and the seven instruction bytes must be installed somewhere between team data and the match-setup
   routine `0x145401050`; the write found at `0x1454023ac` only ever stores 0 or 1. Start from
   `0x145401050`'s four callers (`0x1453ea3d0`, `0x14540b780`, `0x1454132f0`, `0x14541a0e0`) and from
   the setter helper `0x1442c0780` (called right after `0x1442c07a0` at `0x144142f8b` and
   `0x144245bf6`). Closing this decides whether the owner gets an authorable team-tactics lever or a
   documented dead end.
3. **The meaning of the 18 `kind` values** at `0x1442e1200`'s 271 sites. Each site's surrounding
   branch says what the instruction gates; the folded immediates are in
   `build/registry/instr_sites.json`.
4. **Does `URandomInfo+0x08` ever become non-zero?** One live read at `0x145653e5f` across two
   possession spells settles it, and a "no" is a major correction to `ball-carrier-brain.md` (§ 8.1,
   § 12.3). Static alternative: decode `match::RandomControl` (`0x146aff6c0`, ctor `0x143c6a230` from
   `0x143c53410`).
5. **Who calls the commit `0x145340a10`, and when in the frame.** 225 call sites across 73 roots;
   `match::CommitRegistryListener` `0x143c66cd0` (5 vtable slots) is the obvious entry point. Any
   runtime patch of a `Copy` record needs this answered.
5a. **Who commits `UCommandOutput`, and who reads it** — the sharper form of open 5, and a hole in
   § 7.1's channel. `UCommandOutput` is `Copy` with only `ScopedRead` and `ScopedWrite`
   instantiations (**no `ScopedWAndC`**), and there is **not one commit site in
   `0x1440d0000–0x1440f0000`**, the band that contains `match::Command::update`'s write. No reader
   has been traced either — the one candidate followed all the way in, `0x144261bd0`, turned out to
   touch no registry record at all. **Until both are found, the documented pad→command channel ends
   in a write into a buffer nobody has been shown to read.**
6. **The `UOrderInfo` slot record's fields.** Addressing is decoded (40 slots per team, handle
   `{team ≤ 1, slot ≤ 0x27}`, produced by `0x1442df7f0` / `0x1442c2d40`, validated by `0x1442e4c40`);
   the record is not. **This is the likeliest landing place for "order a teammate to run"**, and
   therefore for realism item 2's other half.
7. **The 15-entry control-source jump table** at `0x140d4a08 + base` inside `match::Command::update`
   (bound `cmp esi,0xe` at `0x1440d4339`). Only the pad branch was traced. It decides, per player,
   whether input comes from the pad, the CPU, the network, a replay or a demo — and it is the
   prerequisite for answering whether a pad-driven carrier *also* runs `match::ai::bp`. **That
   question is currently malformed in the project's notes**: there are two unrelated `ThinkUnit`
   families, `match::pad::ThinkUnit*` (72 classes, § 7) and `match::ai::bp::ThinkUnit*` (the carrier
   brain). The pad channel *is* a ThinkUnit machine.
8. **`team+0xb4c` / `+0xb50`: identify `ctx+0x28`.** Start from the Cross post-roll site
   `0x14567b5c1`, not from the team base.
9. **Meanings of `team+0x204`, `+0x208`, `+0x128`, `+0xb3bd`, `+0x740`** and the
   `+0xb458`/`+0xb45c`/`+0xb460`/`+0xb464`/`+0xb468` cluster (defaults 1/8/4/2/7, adjacent to the
   attack-level setting). **All writers are known; none of the semantics are.**
10. **`UMatchEnv`'s 344-byte layout and `UMatchInfo`'s 17,072** — the two most-read small records and
    the obvious homes for half, clock, score and weather. `UMatchEnv` is a proven flat POD, so the
    layout is findable by following the returned pointer from the 25 tagged read acquires in
    `build/registry/seams2.json`. Look for their replay serialiser first (§ 4.2) — it is a free
    field-order oracle.
11. **The registry key of the nine NULL-group records** (§ 13.16). **Start from
    `CameraTargetInfoRef`**: its `vf1` is `0x140efd270` = `lea rax,[rcx+0x58]; ret`, i.e. the group
    string is supplied per instance at `Ref+0x58`. If the nine do the same through some other path,
    that is the answer; if not, either a pre-registration path exists that nothing references, or the
    array scoped path is dead template code.
12. **Which `UCommandOutput` fields anything reads — i.e. any field at all.** The record has **zero**
    decoded offsets (§ 5.6): the two previously listed here belong to `UAnalyzeInfo`, and no consumer
    of `UCommandOutput` has been traced. The construction sites (set-piece `0x1442059d0`,
    pass-reception `0x144285920`, CPU side `0x1442d0050` / `0x1442d12d0`, observer `0x144288360`) are
    `Ref` **vtable-store** sites, which § 15.1 shows is not evidence of consumption. See also open 5a.
13. **`ThinkUnit+0x10`, the mode 0..4.** One consumer found (`cmp` against 3 at `0x1440dcff8`). It
    must **not** be read as "press/hold/tap" — the press edge comes from `vf17` unconditionally.
14. **The gesture table at `0x1486adff4`**: 5 rows emulated from 14 of 42 builder call sites. The
    unexecuted branches (probably gated on the control-scheme setting) hold more rows.
15. **The 8 × 18-byte per-pad assignment descriptors at `UPadInput+0x258c8`** (written by
    `0x144316620`), and the two whole-record gate flags `+0x25958` / `+0x25959` (no writer located).
16. **Pad-frame `+0x18..+0x38`** — 33 analog pressure bytes, written but with **no reader located**,
    so "read ≠ effective" is unresolved for the analog channel. And `+0x39..+0x3F`, unaccounted.
17. **`URegistryData+0x04`** — written from `r12d` at `0x1453411e3`; source register unresolved, no
    reader found.
18. **Producers of the four read-only records** `UPlayerInfo`, `UPlayerMove`, `UAnimeInfo`,
    `UBallInfo` (§ 13.18). The likely shape is the `UTeamAIInfo` one — a live object owned elsewhere
    (the entity container at `UModeInfo+0x200`, via `0x1442d6fe0`) staged and copied in for
    serialisation — but **that is an analogy, not a trace**.
19. **Why `UPlayerMove` needs both a 22-element and a 31-element view.** The dimensions are proven;
    the reason for 31 is not.
20. **The 242 of 439 read-resolve sites that could not be attributed to a record.** 197 were tagged by
    back-scanning `0x160` bytes for a `Scoped*` vtable; the rest construct the scope object too far
    from the acquire. Resolving them needs the `Ref` base offset traced to its owner class.
21. **Who writes the `UModeInfo` per-team record pointers at `+0x3450` / `+0x3500`**, and where
    `UModeInfo` itself is allocated and filled at match start — the layer above everything in this
    chapter. `0x1442d7290` and `0x1442d7ab0` (14 read-resolves each; 35 callers for the latter) are
    the acquire counterparts to the teardown `0x1442d62c0` and were not decoded.
22. **Who writes `match::Player+0x7f49`** (§ 10.3). No `disp32` writer image-wide; it must be written
    through a sub-object pointer with a small displacement. Next lead: `0x144641700`, the only other
    function touching the `0x7f00..0x7f14` region.

---

## 15. Where the probes disagreed, and my reading

Four probes ran in parallel. Three disagreements and three self-corrections are recorded here, with
the resolution and — more usefully — the *method* error behind each, because every one of them was a
scan that was narrower than the thing it was looking for.

### 15.1 The `Analyze` family: "clean negative" vs "271 call sites" — **the second reading wins** [b]

The `tactics-landing-map` probe returned `AnalyzeDetailInstruction` as a clean negative, on the
strength of a referrer list: `UAnalyzeInfo::?$Pointer` (`0x146af5eb8`), `AnalyzeInfoRef`
(`0x146af5ef0`) and `VAnalyzeInfoRef::?$ScopedRead` (`0x146af5f18`) have 16, 12 and 6 referrers and
**not one** is in the carrier or off-ball band.

**That observation is true and the inference from it is void**, for a reason the same day's seam
measurement supplies: **no `match::ai`, `match::ai::bp` or `match::player` code touches a registry
`Ref` for *any* record** (§ 10.1). So "no `AnalyzeInfoRef` referrer in the carrier band" is true of
every record in the image and proves nothing about any of them. Most of those 16 referrers are
out-of-line constructor/destructor bodies emitted in whichever translation unit instantiated the
template — not use sites.

**My reading: the retraction is correct, and I verified its core with capstone for this write-up**
(§ 5.3 quotes the two loops). Everything *factual* in the negative survives — the three sizes, the
five `u32[8]` arrays, the `0xff` initialiser, the three containers — and the `0xff` turns out to be
the key the first reading had in its hand: it is the wildcard 147 callers pass.

**Method warning, and it is the one to remember:** attributing a record to a subsystem from its
`Ref`/`Scoped*` vtable referrers gives the wrong answer in this codebase. Use the **resolver call
sites** (`0x145340c80` / `0x1453415d0` / `0x143c4db70`) instead — and even then, remember § 10.1.

### 15.2 "Readers and writers share one buffer" — **withdrawn by its own author** [b]

One probe's first draft claimed there were exactly two functions touching a registry entry, that
readers and writers both got `entry+0x10`, that nothing read `entry+0x20`, and that `match::Player`
never write-acquires. All four are wrong, and the cause is one byte: the scan matched
`48 8B 41 28` (`mov rax,[rcx+0x28]`) and therefore could not see the write-resolve `0x1453415d0`,
which loads the same field as `48 8B 49 28` (`mov rcx,[rcx+0x28]`). Six of `match::Player`'s seven
entry-point calls are in fact **writes** (`0x14414b8e0`, `0x144241eb1`, `0x144241f51` write-resolve;
`0x1441447f6`, `0x14414b855`, `0x14415091a` wrapper) — which is what one would expect of the owner of
`UPlayerInfo` / `UPlayerMove` / `UBallExternalForce` / `UCameraTargetInfo`.

**My reading: the withdrawal is right and GIVEN #2 stands.** I re-disassembled both resolvers in full
(§ 2.1); they do exactly what the corrected text says. **Method warning:** a byte-pattern scan must
cover *every encoding* of the instruction it is looking for. Prefer a disassembled sweep of callers
over a byte scan whenever the target is a function rather than a constant.

### 15.3 Four record sizes — **the skeleton is wrong, three probes agree, and I re-read the bytes** [b]

`UFieldInfo` = 80 (not 1,435,944), `URandomInfo` = 28 (not 192), `UCameraSettings` = 16 and
`UDemoControl` = 48 (not 740 each). Three probes reached this independently by three routes
(descriptor, copy thunk, constructor) and two of them also emulated the thunks; I re-read
`0x143c4e070` with capstone for this write-up and it is `xor r9d,r9d` + `lea r8d,[r9+0x50]`.
**Root cause: MSVC's `lea r8d,[r9+imm]` idiom** for a small size when `r9` already holds 0 or 1, plus
a carry-forward that mis-attributed a neighbour's size (§ 1.1). Any future scan of this family must
handle that form — and note that for a `Copy` record `r9d` is 1, so the `lea`'s immediate is
**size − 1**.

### 15.4 `ScopedWAndC`: undecoded → decoded, same day [b]

The skeleton and the `pad-to-command-channel` probe both returned it undecoded; the
`random-bundle-and-lifecycle` and `inventory-completion-and-seams` probes decoded it independently
and identically. **My reading: decoded, and verified** — I disassembled `0x145340a10` in full (§ 2.2),
and the pad probe's own "suggestive, not proof" observation (`UPadInput`'s WAndC scope calling
`0x145340a10` at `0x1453e72a9`) is exactly the mechanism. No disagreement survives.

### 15.5 GIVEN #4's witness was mis-read, and the conclusion still holds [b]

GIVEN #4 called `0x1442efda0` "a second, independent function that walks the same object to the same
`0xbd88`". It is `UTeamAIInfo::reset`, a straight-line default initialiser with no source operand,
which merely ends at `mov dword [rbx+0xbd88], 6`. **The conclusion GIVEN #4 drew — that
`team`/`teamAI`/`UTeamAIInfo` are one object — is correct**, and § 5.1 confirms it by emulation. Only
that one supporting witness was wrong, and correcting it is a net gain: the initialiser turned out to
be the source of the whole default table.

### 15.6 Two method warnings that did not come from a disagreement

* **Never emulate a record copy with a pseudorandom source.** `0x143c43370` with garbage reports
  48,774 bytes touched and a max offset **256 bytes past** the record, because the copy walks embedded
  lists whose counts come from the source; with a source built by its own initialiser it gives the
  true **48,287** bytes / max `0xbd8b`. A naive run yields a confident wrong size. [a]
* **A Unicorn harness must FAIL LOUDLY on an unhooked import thunk.** This is the second half of the
  same story and it cost the chapter a headline. The harness mapped RET pages on demand to survive
  stray reads, so `call 0x144f8307a` (→ IAT `0x1459fd820` = `VCRUNTIME140!memcpy`) simply returned,
  and 34,668 bytes of the copy vanished. The result — 13,619 bytes — *looked* like a finding ("the
  copy is selective"), and three separate claims were built on it. **A skipped import is not a
  measurement.** Hook every import the function calls, or abort. [a]
* **`func_chunks`, never `func_range`.** Every closure and every class-method expansion in this
  chapter used chained-unwind extents. `func_range` returns only the root chunk and silently
  under-reports — the trap that cost the previous chapter its one unresolved major.
* **One object, one name.** `0x140efd260(x)` = `[x+0x48]` appeared in this chapter under three names
  — `UAnalyzeInfo`, "the constant table" and `UCommandOutput` — and the third was a straight error
  that a size check would have caught in one line (`0x25bcc` ≫ `0x13b20`). **Before attributing an
  offset to a record, check it against that record's own registrar size.**

---

## 16. Reproduction

All work read-only over `eFootball.exe.PRISTINE`. **Nothing was written to the game, to the installed
image, to `tools/`, or to git.**

| artefact | what it holds |
|---|---|
| `build/registry/reg2.json` | all 45 registrar call sites with size, `Copy` flag and the ctor/dtor/copy hooks |
| `build/registry/refsites.json` | every `Ref` vtable store grouped by owning function |
| `build/registry/scoped.json` | `Scoped*` vtable sites per record and mode |
| `build/registry/seams2.json` | all 439 read-resolve sites with record and mode where taggable |
| `build/registry/resolvers.json` | call sites of all four registry entry points |
| `build/registry/instr_sites.json` | the 271 instruction-query sites with folded `(kind, value)` immediates |

Verification performed for this write-up, beyond the probes' own work: capstone re-reads of
`0x1442e1300`–`0x1442e1357` (the instruction query's two loops), `0x143d7c7cd`–`0x143d7c7f6` (both
`+0xb3c4` writers), `0x143c4e070` (the `lea r8d` size idiom), `0x145340a10` (the commit),
`0x145340c80` / `0x1453415d0` (both resolvers), `0x140c83910` (`ret 0`), `0x143d02ee4`–`0x143d02f33`
(the `+0xb44d`/`+0xb44e` derivation, which also established the field width), `0x1442ee5f0`,
`0x1442d7070`, `0x1442d6fc0`, `0x14430f9b0` (the rising edge), `0x14431a5b0` (frame addressing),
`0x1440e20b0` (`CursorChange::vf12`), `0x1440e5500`–`0x1440e553f` (`PassAndGo` chain A, including the
`0.08`/`0.5` cell addresses and the two node-array addresses), `0x1440d8000` (`vf17`), `0x140eb0b90`,
`0x1443461a0` and `0x1443461c0` (the LCG primitives); plus `tools/exe_census.py cell <va> --all` on
all twelve constants named in § 11.

**Added in the repair pass (§ 12.7), all read-only over PRISTINE unless noted:**

* `emu6` — `0x143c43370` re-emulated with **both** import thunks hooked (`0x144f8306e` = `memset`,
  `0x144f8307a` = `memcpy`), source built by `0x1442efda0`, destination pre-filled `0xAA`:
  **48,287 bytes, max `0xbd8b`, 0 past size, 48,287 identical to source.** [a]
* PE import-directory walk resolving `0x144f8307a` → `0x1459fd820` = `VCRUNTIME140.dll!memcpy` and
  `0x144f8306e` → `0x1459fd750` = `memset`.
* Fold of `r8d` / `r9d` over **all 45** registrar call sites (33 Copy / 12 Pointer, 0 unresolved).
* `vf1` / `vf2` sweep of **all 45** `match::registry::<Name>Ref` classes → the 35 / 9 / 1 key split
  in § 3.1.
* Full call-target sweeps of `0x144261bd0`, and registry-entry-point membership tests for
  `0x1442059d0`, `0x144285920`, `0x1442d0050`, `0x1442d12d0`, `0x144288360`, `0x1440d4180`.
* Capstone re-reads: `0x14533ea80`, `0x140a14d90`, `0x143d7c5b0` in full, `0x143d7b650`'s four timer
  constructs, `0x14430da30` / `0x14430d980` / `0x14430d830` and the four node builders,
  `0x1442d5500`'s teardown loop, `0x1453e2580` / `0x1453f1400` / `0x1453e6970`, `0x1442d0050`'s
  `Ref` builds, `0x1442c3af0` / `0x1442c4ab0` (the `+0x3318`/`+0x3320` zeroing), `0x143d04830`'s
  ±1 walk, `0x1442efda0`'s `esi` consumers and array loop, `0x1442e1205`–`0x1442e1360`,
  `0x140efd260` / `0x140efd270`, `0x144287790`, `0x1442de630`.
* Byte-level diff PRISTINE ↔ installed (909 bytes / 105 runs) with every run mapped to its
  chained-unwind root.
* `tools/exe_census.py cell … --all` on `0x146b9f990`, `0x146b9f998` (both **private**) and
  `0x146ad6cf0` (61 raw referrers, unclassified).
