# The executors — `match::player` (2026-09-19)

What actually happens once a brain has chosen: where a runner goes, how a marker moves, how a kick
is struck, how a receiver runs onto a pass, and everything a goalkeeper does. **109 RTTI classes**
(113 vtables in `build/exe_map.json` — the extra four are the nested
`PassGetRouteBallAdjust::*` sub-classes, which is exactly the 113 − 4 = 109 reconciliation). [b]

Produced by one hand-written architecture pass (which stands, and is kept below) plus four workflow
probes — run geometry and cross-role, defensive executors, kicks and receivers, goalkeepers — over
`tools/exe_map.py`, `tools/exe_census.py`, `tools/exe_funcs_chained.py` and purpose-built Unicorn
harnesses. **Every load-bearing contradiction in this chapter was re-derived from the PRISTINE bytes
for this write-up**, not taken on a probe's word; where a probe and the re-read disagree, the
re-read wins and the probe's error is named (§ Corrections).

Evidence levels: **a-emulated** (the game's own bytes executed under Unicorn with controlled inputs),
**b-disassembly** (followed instruction by instruction; extents from the *chained-unwind* `.pdata`
walk — never the touching-range merge), **c-inferred** (structural reasoning only). Addresses are
VAs at base `0x140000000`, no ASLR, decoded from `eFootball.exe.PRISTINE`.

**Our own patches — the real inventory (CORRECTED 2026-09-19).** The previous header said "five
sites"; that was an undercount and it is the honesty guarantee the chapter rests on, so here is the
diff. A full byte compare of `eFootball.exe.PRISTINE` against the installed image gives **909
differing bytes in 105 contiguous runs image-wide** (the brief's "~306 bytes" is also wrong).
Mapping every run through chained-unwind extents, **13 runs fall in seven `match::player`
functions**:

| function | runs | what the chapter says about it |
|---|---|---|
| `0x1441a1e50` `ActionMark::vf20` | `0x1441a247a` | flagged (45.0 → 90.0 steering cap) |
| `0x1441a4280` `ActionMark::vf6` | `0x1441a43b9`, `0x1441a43cf`, `0x1441a58be`, `0x1441a58d9` | flagged |
| `0x1441a27c0` `ActionMark::vf22` | `0x1441a29fd` | **was not flagged** — the class table called vf22 "not read" |
| `0x1441a7fa0` (tackle chain, sole caller `0x1441a6365`; holds the `0x143da79a0` handoff site `0x1441a81cc`) | `0x1441a82ec`, `0x1441a844c`, `0x1441a84a2` | **was not flagged** — § Kicks, tackles and set pieces decodes this chain |
| `0x1441a8a70` (`ActionTackle` slots 4/6 tail-jump target) | `0x1441a8c2e` | **was not flagged** |
| `0x144202c20` (called once, from `0x144202947`) | `0x1442031c4` | not discussed |
| `0x144310ea0` (action-flag band, callers incl. `match::Human::vf8`) | `0x144311572`, `0x14431157a` | not discussed |

Two more quoted-as-stock functions differ outside `match::player`: the kick error model
`0x14401a900` (5 runs) and its sole caller `0x144016a70` (1 run). Many other runs image-wide are
8–16 byte hook stubs written over epilogue padding (e.g. immediately before the marking LERP, at
`0x143e1bfa0`). **Everything quoted in this chapter was decoded from PRISTINE regardless**, but a
reader A/B-ing the Mark patches or tuning tackling should know they are looking at modified bytes on
the installed image. [b, full image diff re-run for this repair]

Companion chapters: [match-ai-decoded.md](match-ai-decoded.md) (who chooses off-ball movement),
[ball-carrier-brain.md](ball-carrier-brain.md) (who chooses on-ball actions). **Both are corrected
by this chapter** — see § Corrections before leaning on either.

> **Read [§ Corrections](#corrections) first.** The single most repeated belief about this
> subsystem — "slot 20 is the movement-target emitter, every *where does this player go* question
> resolves to a slot-20 body" — is **wrong**, and it was stated as fact in the previous version of
> *this* file and in every briefing built from it. Slot 20 usually emits a *steering direction at a
> fixed radius* (17 of 30 distinct bodies call the polar emitter directly, 22 within one hop, and 8
> bodies covering 11 classes write an absolute point or nothing at all); **the destination is slot
> 4's, or slot 18's for the classes that override it**, and that part holds for all 55.

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| stop defenders standing off — **the CB standoff** | it is **not** a radius and **not** in `ActionMark::vf20`. `ActionMark::vf4 0x1441a2a80` → `0x143e1c9d0` → `0x143e1bfb0`: the target is the player's formation-slot vec3 LERPed toward the team's marking target by X/Z weights, and **both** weights are killed by a **10 m ball-position ramp** at `0x143e1c1b8..0x143e1c214` | exe code (re-aim `0x143e1c1e1`/`0x143e1c1e9`) **or, cleanly, player data** (out-of-possession style category 9 = +50 to both weights) | a-emulated: 6.08 m off the man → 0.30 m off him when the ramp is open |
| make runs start later / hold the line | **nothing to tune at this layer.** The run target's X is *assigned* to `rawOpponentLine + attackDir·10.0` every frame (`0x143d222e0`), with **no timing term anywhere in the executor** | exe code: cell `0x145a8dd7c` = 10.0 at 14 call sites — re-aim the disp32, the cell has 1,832 referrers | a-emulated: line 30 → target x = 40.000; line 20 → 30.000 |
| widen which players may be given which run | **safe for what was tested, and one kind is provably NOT.** Run geometry is role-blind across the 15 level-1 path builders and the 14 slot-20 emitters tested (2,820 emulated comparisons, byte-identical targets) — that is 15 of the 25 handler entries and 14 of the 30 distinct slot-20 bodies. The **seven second-level handlers were never emulated**, and sub-mode id 3 (= ChanceSpaceRun **kind 1**) branches on the role code: `0x144268754`/`0x144268764` read `teamAI+0x42b8+role*4` and pick **−5.0** (`0x145b1d940`) for role codes 3–4 versus **−6.0** (`0x145ace398`) for every other role | selector eligibility (upstream, `match-ai-decoded.md`) | a-emulated for the tested set; b for the kind-1 counter-example (§ Open 6, § Open 21) |
| make weak goalkeepers actually mis-position | the only random number in the entire GK family: `RandInt(0..5) · 0.1 · (1 − (GKAwareness−40)/59)` m, re-rolled every `2·T` ticks | exe code: the **plain** range immediate `mov edx, 6` at `0x144228863` (verified: **not** an RNG stream index, unlike the carrier's plan rolls) | a-emulated: 0.50 m max at 40, 0.00 m at 99 |
| make weak goalkeepers actually concede | the save-quality selector `0x144032870` **floors Reach at an output 50 and Reflexes at 63** (the inline constants are 52 and 65, then anything below 90 is scaled ×0.98 at `0x1440329ed..0x1440329fe`), and remaps an easy catch into 73..89 across the whole roster | exe code (inline immediates) — but the function is in the **animation** layer, subsystem 3 | a-emulated |
| per-player control of marking tightness | out-of-possession playing-style categories **9** (+50 to both marking weights) and **0xb** (zero them) at `0x143e1c166` / `0x143e1c151` | **player data the app already writes** | a-emulated; the category→catalog-name map is not in this chapter |
| change how the offside trap steps up | `ActionOffsideTrap::vf4 0x1442067f0` returns `player.x + attackDir·10.0` — **relative and recomputed every frame**, so the line marches while the executor is active | exe code (`0x1442068f3`, cell `0x145a8dd7c`) | b |
| ability-scale a run, a mark or a save at this layer | **not possible.** Zero attribute reads in the run builders' 528-function closure, zero in the 61-function marking-target chain, and the four goalkeeping attributes are read only in the anime layer | — | b, with positive controls |
| tune any of this through dt270 | **yes — for pass reception and base position, at depth 0** (CORRECTED; the old row said dt270 only reached depth 3). `passget` (idx `0x6c`) is read by 15 `get()` calls **inside `PassGetRoute*` vtable methods themselves**, and `basePosition` (idx `0xe2`) by `ActionBasePosition::vf4` at `0x1441832db`. Still true: **no dt270 field reaches a goalkeeper executor**, and the `basePosition.gk*` family is the *outfield* goal-kick shape | **dt270 data file — no exe patch, no shared cell: the safest levers in this chapter** (§ Tunables, dt270 block) | b, from `build/dt270_liveness.json` + a re-disassembly of every `match::player` vtable-method body |
| pressing intensity | **not parameterised** anywhere reachable. `ActionPress::vf20` targets the ball outright; the 3 m "step in front" correction has non-zero weight only inside 0.5 m | — | b (NOT PROVEN absent — the team object was not swept) |

---

## The machine in one paragraph

The two brains choose; **nothing here chooses**. One parent object (`0x144141500`) holds every
executor as a fixed subobject (101 funclet-registered subobjects plus the inlined `+0x28` base and
the nothrow-leaf `PassGetRoute` work object at `+0xfa00` = the 103 rows of the map below), so selecting one is a pointer lookup, never an allocation. Two
vtable contracts split the family: a **23-slot movement contract** (55 classes) and a **7-slot kick
contract** (34 classes). A movement executor is driven by `match::ai::ActionMove::vf2`
(`0x145620a00`), which seeds a position accumulator with the player's own position, lets slots 16
and 19 overwrite it, then calls **slot 20** and **slot 21** to write two *steering points* into
separate fields of a per-frame move request (`+0x14`, `+0x2c`); separately the packager
`ActionMove::vf18` (`0x145625830`) calls **slot 4** for the destination, **slot 5** to move toward
it, **slot 6** as a predicate and **slots 13 and 12** for two integer tags. **Most** slot-20 bodies
end in the polar emitter `0x144347c20(out, &bearingDeg, r)` with `r` a literal (10.0, 3.0, 100.0) —
17 of the 30 distinct bodies call it or its wrapper `0x143d1b7e0` directly and 5 more reach it in
one hop (22 bodies, 44 of the 55 classes); the remaining 8 bodies (11 classes) write an **absolute
point** or are stubs, so "steering, never a position" is the rule and not a universal (§ Why
`ActionMark::vf20` is not the standoff). That is why "the marker never closes radially" is true and
vacuous *for `ActionMark`* — its own `r` is the literal 10.0. Twenty-one of the 55 movement
classes override slot 18 and take the destination into their own hands: `ActionSpaceRun`'s
(`0x1441f3010`) is a **path compiler** that runs a per-frame run-phase state machine, dispatches
through a two-level jump table to one of 25 distinct handlers, compiles a 2-D waypoint polyline
into a `0x4ec`-byte path object and returns `(target, gait, movement-class, path)`. A kick executor
is driven by the shared `slot 2` (`0x14561fe20`, in 33 of 34 vtables), which stamps the action id
into `kickWork+0` and then tries **slots 5 → 4 → 6**, stopping at the first that returns true; slot
6 is always "read what the carrier brain published", fetched by player index out of a global
22-entry pointer table (`0x1486bfbc0`) into which `BallPlayer` registered its own result record at
construction. The executor's whole output is a value tuple — a destination, two steering points, a
gait, a path, a filled kick-work block — and **it never calls the animation layer**: two independent
closures (592 and 528 functions) reach zero functions that are exclusively `match::anime::*`. The
one place the boundary is a call is the tackle, which hands off through `0x143da79a0` (four call
sites image-wide). Everything downstream of the tuple — which save a keeper plays, how a kick is
mishit, which animation runs — is subsystem 3.

---

## The two vtable contracts

### The 23-slot movement contract — `match::ai::ActionMove` (vftable `0x14771e708`)

Slot roles come from `ActionMove::vf18`'s own indirect calls, re-read from PRISTINE for this
chapter: `0x145625868 call [rax+0x20]` (slot 4), `0x145625890 call [rax+0x28]` (slot 5),
`0x1456258bc call [rax+0x30]` (slot 6), `0x1456258cf call [rax+0x68]` (slot 13),
`0x1456258e2 call [rax+0x60]` (slot 12). And from the slot-2 driver `0x145620a00`:
`0x145620b2a [r10+0x88]` (17), `0x145620bc9 [rax+0x58]` (11), `0x145620d07`/`0x145620d8c [rax+0x98]`
(19, twice), `0x145620e99 [rax+0x78]` (15), `0x145620eb5 [rax+0x38]` (7),
`0x145620f11 [rax+0xa0]` (**20**), `0x145620f28 [rax+0xa8]` (21), plus — **added 2026-09-19, the
list was short** — `0x145620f6a [rax+0xb0]` (22), `0x145620f99 [rax+0x40]` (8),
`0x145621035 [rax+0x50]` (10), and slot 14 (`mov r8,[rcx+0x70]` at `0x145620a9d`, called at
`0x145620aa4`) and slot 16 (`mov r10,[rcx+0x80]` at `0x145620ac3`, called at `0x145620ae8`), both
taking the same four stack arguments as slot 17. **Slot 18 is not called by the driver at all**: the
driver calls slot 16, then slot 17 if 16 returns false, and **slot 17's base body `0x1456257e0` is
what calls slot 18** (`mov rax,[rcx]; mov r10,[rax+0x90]; … call r10`, then stores −1.0f through the
caller's fourth stack pointer). That is the missing link that makes `ActionSpaceRun::vf18` run.
[b, all re-derived here]

The "universal / base default" columns below are a **census over all 55 classes**, not over the 14
originally differenced — which is why several of the original chapter's "universal" labels narrow.

| slot | name | base body | how universal (of 55) |
|---|---|---|---|
| 0 | destructor | per-class | 21 distinct |
| **1** | **reset** | `0x1456219f0` | **55/55 — genuinely universal** |
| 2 | driver / `canStart` | `0x145620a00` | 51/55 (override: `ActionDelay 0x1441981d0`, `ActionPassGet 0x1441754d0`, `ActionPress 0x144190270`, `ActionWaitTimer 0x144210b90`) |
| 3 | — | stub `0x140c83910` (`ret 0`) in 29/55 | 26 distinct |
| **4** | **getTargetPosition — THE DESTINATION** | `0x1442060f0` = "my own current position" | only 17/55 keep the base; **36 distinct bodies** |
| 5 | move toward the target (fills the path) | stub `0x140c853c0` in 35/55 | 21 distinct |
| 6 | predicate consumed by `vf18` | stub `0x140c853c0` in 34/55 | 22 distinct |
| 7 | zero-vec stub | `0x143d520d0` (`xor eax,eax; [rdx]=0; [rdx+8]=0; return rdx`) | 54/55 — the one override is `ActionKeeperSeenOff 0x14422f260` |
| 8–11, 14 | stubs | `0x140c853c0` / `0x140c83810` / `0x140c837d0` | 45/44/54/51/52 of 55 |
| 12 | int tag (action id) | `0x144114300` = `mov eax,0x71; ret` | 32/55 |
| 13 | int tag (gait) | `0x14140d670` = `mov eax,3; ret` | 24/55 |
| 15 | bool | `0x140c83810` | 30/55 |
| 16, 17 | accumulator overriders | `0x145626100` / `0x1456257e0` | 44/55, 49/55 |
| **18** | **packager** — and, when overridden, the real geometry | `0x145625830` | 34/55 keep it; **21 override**, incl. `SpaceRun 0x1441f3010`, `DiagonalRun 0x144201d60` |
| 19 | accumulator overrider | `0x145623100` | 52/55 |
| **20** | **steering point → moveRequest+0x14** | `0x1456220d0` | only **23/55** keep it; **32 override**, 30 distinct |
| 21 | steering point → moveRequest+0x2c | `0x145624620` | 52/55 |
| 22 | int | `0x140e35f40` = `mov eax,8; ret` | 31/55 |

Slots **12 and 13 carry no logic**: the four constants that fill them across the family are
`0x144114300` → `0x71`, `0x14140d670` → `3`, `0x140eeb6d0` → `2` and `0x14172cb30` → `5`, all
`mov eax,imm; ret` (disassembled here). The long-standing lead that "`ActionMark` and `ActionPress`
share slot 13, so marking and pressing run identical logic" resolves to a shared two-instruction
`return 3` used by at least six classes. [b]

### The 7-slot kick contract (34 classes)

| slot | name | body | census |
|---|---|---|---|
| 0 | destructor | per-class | 7 distinct |
| 1 | reset | `0x1456219d0` (zeroes `this+8/+0xc`, clears `work+0x918`, tail-jumps to slot 3) | **34/34** |
| **2** | **the driver** | `0x14561fe20` | **33/34** — sole exception `ActionKickFeint 0x144175ca0` |
| 3 | stub | `0x140c83910` (`ret 0`) | 33/34 — exception `ActionThroughPass 0x144144070` |
| 4 | generic target resolver | `0x145625a20` (9 direct + 7 via the thunk `0x1441ad530 = jmp 0x145625a20`) | modal in only 9/34, 15 distinct |
| 5 | pre-resolver | stub `0x140c853c0` in 33/34 — **only `ActionKickoff 0x1441c4880` has a body** | 2 distinct |
| 6 | **read what the brain published** | per-class | 29 distinct |

The driver `0x14561fe20` stamps `work+0x8b8 = *(int*)r9` (the action id) and `work+0x8bc`, then
tries **slot 5, then slot 4, then slot 6**, stopping at the first `true`; if all three refuse it
calls `0x144339120(kickWork)` and bails. Call order proven by emulation with an instrumented
synthetic vtable: returns `{}` → `[5,4,6]`; `{5:1}` → `[5]`; `{4:1}` → `[5,4]`; `{4:1,6:1}` →
`[5,4]`. Dispatch sites `0x14561fe77` (`call [rax+0x28]`), `0x14561fe8a` (`[rax+0x20]`),
`0x14561fe9d` (`[rax+0x30]`). [a-emulated]

The generic slot-4 resolver `0x145625a20` decodes the action record's tagged target descriptor at
`rec+0x20` via `0x144318200`, a 14-way jump table, and writes the aim vec3 to
`kickWork+0x5bc/0x5c0/0x5c4`, the target index to `+0x5d0` and flag bits at `+0x740/+0x744`. [b]

---

## The architecture — one parent, every executor a fixed subobject

*(Hand-decoded 2026-09-19; unchanged except where marked. It survived all four probes.)*

`0x144141500` is **not** a factory that dispatches on an action id. It is a constructor that builds
**every executor as a fixed subobject of one parent**, inlining the simple classes' vtable writes and
calling out to the complex ones (`Press 0x14418edf0`, `Shoot 0x1441b3520`, `SpaceRun 0x1441405d0`,
`DiagonalRun 0x144200d90`, `OverlapCB 0x1441db540`, `OverlapSB 0x1441d7e40`). [b]

That is the **third** subsystem built to this exact shape — the off-ball `ActionSelectorManager`
holds its 10 selectors at fixed offsets, the carrier brain holds 25 ThinkUnits at `BP+0x54d0` and 16
ImageUnits at `BP+0x4230`, and `match::player` holds its executors the same way. Selecting an
executor is therefore a **lookup of a fixed subobject**, not an allocation.

### Executor subobject map — 101 funclet-registered subobjects, plus two amendments = 103 rows [b]

Recovered from the constructor's own **MSVC unwind funclets** at **`0x145810110..0x145810d97`**:
one 16-byte funclet per subobject, each `mov rcx,[rdx+0x60]; add rcx,<offset>; jmp <dtor>`, which is
the compiler's own list of what the constructor has built so far. Names come from the vtable each
subobject is given, resolved through `build/exe_map.json`, bounded by **chained-unwind extents** —
an unbounded window over-runs `0x144140a70` into its neighbour and mis-attributes four classes.
**98 of the 102 funclet offsets are named** (the unnamed four are `+0x00010`, `+0x06d48`,
`+0x0c7e8`, `+0x0d180`); the table below has **103 rows** = 101 funclet-registered subobjects of this
constructor + `+0x28` (inlined base, no funclet) + `+0xfa00` (nothrow leaf, see the amendment).

> **CORRECTED 2026-09-19 — the funclet range, and one funclet that is not ours.** Parsing 0x20-stride
> funclets from `0x1458100f0` yields exactly **102**. The **first** of them is not this
> constructor's: `0x1458100f0` reads `mov rcx,[rdx+0x50]` (a *different* frame slot from the other
> 101, which all use `[rdx+0x60]`), adds **`+0x190e8`** and jumps to dtor `0x144099cd0`. That
> subobject is built by the **neighbouring** function: its vtable store is
> `0x14414136b mov [rdi+0x190e8],rax`, whose chained-unwind root is `0x144140fd0`
> (`0x144140fd0..0x1441414f2`), i.e. immediately *before* the executor constructor
> `0x144141500..0x14414268d` — and a capstone scan of the constructor's whole extent finds **zero**
> instructions referencing `0x190e8`. Its destruction is likewise elsewhere
> (`0x1441435bc lea rcx,[rbx+0x190e8]; call 0x144099b20`, inside root `0x144143530`, not the main
> dtor `0x1441427d0`), and its vtable — **`0x146b95450`, corrected 2026-09-19; `0x146b95430` is the
> neighbouring `Pointer`/`ReferenceMobile` template vtable for the same record, not the one stored
> here (`0x144141364 lea rax,[rip+0x2a540e5]` → `0x14414136b + 0x2a540e5 = 0x146b95450`)** — is
> `match::registry::CameraTargetInfoRef`, a `common::Registry` accessor for
> `match::registry::UCameraTargetInfo` — a camera-info registry handle, not an executor. The entry
> at `0x1458100c0` quoted by the old range is not a funclet at all (`mov r8d,2; mov edx,0x58;
> call 0x144f7e6bc; ret`).
>
> **"Exhaustive by construction" is withdrawn.** After the `+0xfa00` amendment below, the funclet
> list is exhaustive over *funclet-registered* subobjects only, which is a weaker claim and the one
> the evidence supports. [b, funclets re-parsed for this repair]

> **AMENDED 2026-09-19.** This enumeration is exhaustive over **funclet-registered** subobjects, not
> over subobjects. A nothrow leaf constructor gets no unwind funclet and is therefore invisible to
> it — and exactly one such subobject exists and matters: the `PassGetRoute` work object, built at
> `0x1441418d0 lea rcx,[rbx+0x70]; 0x1441418d4 call 0x144140b90` with `rbx = r14+0xf990`, i.e. at
> **`ActionPassGet+0x70` = parent `+0xfa00`**. `0x144140b90` has exactly one caller image-wide, and
> it is that site. The corroboration is the map itself: `ActionPassGet`'s last field write in the
> constructor is `+0x11ac` (`0x1441418e1`), i.e. parent `+0x10b3c`, which fits exactly under the
> next mapped subobject `+0x10b48`. The previous version of this file said the `PassGetRoute*`
> family "is not a subobject of this parent"; that is **wrong**. [b, re-derived here]

The contract a class follows is readable off the constructor call: **`0x14561eee0` is the 23-slot
movement base ctor and `0x14561ee70` is the 7-slot kick base ctor** (both are 6-instruction
vtable-write-and-zero stubs, neither takes an id nor registers anything). Classes with their own
ctor still inherit one of the two. Slot counts across the 109 classes, re-counted from
`exe_map.json` for this chapter: **55 at 23 slots, 34 at 7, 5 at 14 (the Demo family), 3 at 4, 11 at
15 and 1 at 16 (the `PassGetRoute*` family), plus 4 at 3 (the nested `BallAdjust` strategies).** [b]

| offset | class | slots | built by |
|---|---|---|---|
| `+0x00010` | `(no lea in ctor extent)` | - | `inline` |
| `+0x00028` | `ai::PlayerDefence` | 1 | `0x14562c970` |
| `+0x06d48` | `?` | - | `0x14415cf00` |
| `+0x0c7e8` | `?` | - | `0x144338e40` |
| `+0x0d0a0` | `ai::AvoidPlayer` | 2 | `0x1456277a0` |
| `+0x0d0e8` | `ai::AvoidArea` | 2 | `0x1456277a0` |
| `+0x0d180` | `?` | - | `0x144140a70` |
| `+0x0f400` | `ActionBasePosition` | 23 | `0x14561eee0` |
| `+0x0f990` | `ActionPassGet` | 23 | `0x14561eee0` |
| `+0x0fa00` | *(`PassGetRoute` work object, ≈0x1130 B — **added**, not funclet-registered)* | — | `0x144140b90` |
| `+0x10b48` | `ActionFreeMove` | 23 | `0x144176b80` |
| `+0x10b90` | `ActionDive` | 23 | `0x14561eee0` |
| `+0x10bc0` | `ActionDribble` | 23 | `0x14561eee0` |
| `+0x10c30` | `ActionPress` | 23 | `0x14418edf0` |
| `+0x10cd0` | `ActionDelay` | 23 | `0x1441947c0` |
| `+0x10e48` | `ActionDelayMark` | 23 | `0x1441a1120` |
| `+0x10e78` | `ActionMark` | 23 | `0x14561eee0` |
| `+0x10ed0` | `ActionOffsideTrap` | 23 | `0x14561eee0` |
| `+0x10f00` | `ActionShortPass` | 7 | `0x14561ee70` |
| `+0x10f10` | `ActionThroughPass` | 7 | `0x14561ee70` |
| `+0x10f28` | `ActionLongPass` | 7 | `0x1441afa00` |
| `+0x10f38` | `ActionSwitchPass` | 7 | `0x14561ee70` |
| `+0x10f48` | `ActionShoot` | 7 | `0x1441b3520` |
| `+0x10f58` | `ActionGoalKickLong` | 7 | `0x1441b2cf0` |
| `+0x10f68` | `ActionClear` | 7 | `0x1441b7810` |
| `+0x10f78` | `ActionTackle` | 7 | `0x14561ee70` |
| `+0x10f88` | `ActionSliding` | 7 | `0x1441a8e00` |
| `+0x10f98` | `ActionCentering` | 7 | `0x1441bc1a0` |
| `+0x10fa8` | `ActionKickoff` | 7 | `0x14561ee70` |
| `+0x10fb8` | `ActionFreeKick` | 7 | `0x1441c42f0` |
| `+0x10fc8` | `ActionFreeKickLong` | 7 | `0x1441c43b0` |
| `+0x10fd8` | `ActionFreeKick2ndPass` | 7 | `0x1441c4540` |
| `+0x10fe8` | `ActionFreeKickCede` | 23 | `0x1441c46c0` |
| `+0x11018` | `ActionThrowin` | 7 | `0x144203d20` |
| `+0x11028` | `ActionThrowInRotate` | 4 | `0x14561ee70` |
| `+0x11038` | `ActionCornerKick` | 7 | `0x144205390` |
| `+0x11048` | `ActionPenaltyKick` | 7 | `0x1442059d0` |
| `+0x110b0` | `ActionKeeperDropBall` | 7 | `0x144218a30` |
| `+0x110c0` | `ActionKeeperPuntKick` | 7 | `0x14561ee70` |
| `+0x110f0` | `ActionKeeperThrow` | 7 | `0x14561ee70` |
| `+0x11120` | `ActionKeeperThroughThrow` | 7 | `0x14561ee70` |
| `+0x11150` | `ActionMoveKeep` | 23 | `0x14561eee0` |
| `+0x11180` | `ActionStopThink` | 23 | `0x14561eee0` |
| `+0x111b0` | `ActionStopFront` | 23 | `0x14561eee0` |
| `+0x111e0` | `ActionStopGoal` | 23 | `0x14561eee0` |
| `+0x11210` | `ActionPassAndGo` | 23 | `0x14561eee0` |
| `+0x11768` | `ActionCenteringGet` | 23 | `0x14561eee0` |
| `+0x11e18` | `ActionOverlapSB` | 23 | `0x1441d7e40` |
| `+0x12348` | `ActionOverlapCB` | 23 | `0x1441db540` |
| `+0x12870` | `ActionGoalGet` | 23 | `0x14561eee0` |
| `+0x128b0` | `ActionPassSupport` | 23 | `0x1441dcf50` |
| `+0x128f8` | `ActionPassSupportThrowIn` | 23 | `0x14561eee0` |
| `+0x12e68` | `ActionSpaceRun` | 23 | `0x1441405d0` |
| `+0x13450` | `ActionLineBreak` | 23 | `0x14561eee0` |
| `+0x13490` | `ActionDiagonalRun` | 23 | `0x144200d90` |
| `+0x134f0` | `ActionKeeperPress` | 23 | `0x144218d00` |
| `+0x13550` | `ActionKeeperBasePosition` | 23 | `0x14561eee0` |
| `+0x135e0` | `ActionKeeperSavingMove` | 23 | `0x14561eee0` |
| `+0x13618` | `ActionKeeperAfterCatchMove` | 23 | `0x14561eee0` |
| `+0x13650` | `ActionKeeperCatching` | 7 | `0x14561ee70` |
| `+0x13678` | `ActionKeeperPunching` | 7 | `0x14561ee70` |
| `+0x13698` | `ActionKeeperDeflect` | 7 | `0x14561ee70` |
| `+0x136c0` | `ActionKeeperBlock` | 7 | `0x14561ee70` |
| `+0x13700` | `ActionKeeperBlockLate` | 7 | `0x14561ee70` |
| `+0x13720` | `ActionKeeperTackle` | 7 | `0x14561ee70` |
| `+0x13740` | `ActionKeeperScoopOut` | 7 | `0x14561ee70` |
| `+0x13760` | `ActionKeeperSnapUnder` | 7 | `0x14561ee70` |
| `+0x13780` | `ActionKeeperMakeshift` | 7 | `0x144220f00` |
| `+0x13790` | `ActionKeeperMoveFreeKick` | 23 | `0x14422c3e0` |
| `+0x137f8` | `ActionKeeperMovePenaltyKick` | 23 | `0x14422ca40` |
| `+0x13828` | `ActionKeeperPKSaving` | 7 | `0x14561ee70` |
| `+0x13868` | `ActionKickFeint` | 7 | `0x14561ee70` |
| `+0x13878` | `ActionFeint` | 4 | `0x14561ee70` |
| `+0x13888` | `ActionWallJump` | 4 | `0x14561ee70` |
| `+0x13898` | `ActionWallPress` | 23 | `0x14561eee0` |
| `+0x138c8` | `ActionPullAway` | 23 | `0x14561eee0` |
| `+0x13908` | `ActionTeammateMoving` | 23 | `0x144206130` |
| `+0x13940` | `ActionShortCornerMove` | 23 | `0x14561eee0` |
| `+0x13980` | `ActionKeeperCoaching` | 23 | `0x14561eee0` |
| `+0x139b8` | `ActionKeeperPreSaveOperation` | 7 | `0x14561ee70` |
| `+0x139e8` | `ActionKeeperBodyFeint` | 23 | `0x14561eee0` |
| `+0x13a18` | `ActionPostMan` | 23 | `0x14561eee0` |
| `+0x13a48` | `ActionGoalCover` | 23 | `0x144206e60` |
| `+0x13aa0` | `ActionKeeperPickupBall` | 7 | `0x14561ee70` |
| `+0x13ab0` | `ActionGkCoachingRun` | 23 | `0x14561eee0` |
| `+0x13ae0` | `ActionKeeperSeenOff` | 23 | `0x14561eee0` |
| `+0x13b10` | `ActionPassCourseCut` | 23 | `0x14420a530` |
| `+0x13b48` | `ActionCover` | 23 | `0x14561eee0` |
| `+0x13b78` | `ActionSand` | 23 | `0x14561eee0` |
| `+0x13bb0` | `ActionDemo` | 23 | `0x144232140` |
| `+0x143e0` | `ActionDemoNormal` | 14 | `0x14423c280` |
| `+0x14418` | `ActionDemoFollow` | 14 | `0x14423c280` |
| `+0x14450` | `ActionDemoCursorPlayer` | 14 | `0x14423c280` |
| `+0x14488` | `ActionGoalPlayer` | 14 | `0x14423ead0` |
| `+0x144c8` | `ActionFreeTrainingBreak` | 23 | `0x14561eee0` |
| `+0x144f8` | `ActionPkMatchNextKeeper` | 23 | `0x14561eee0` |
| `+0x14528` | `ActionMoveOnPass` | 23 | `0x14561eee0` |
| `+0x14a68` | `ActionSeamlessThrowInMove` | 23 | `0x14561eee0` |
| `+0x14a98` | `ActionWaitTimer` | 23 | `0x14561eee0` |
| `+0x14b08` | `ActionPenaltyKickAfter` | 23 | `0x14561eee0` |
| `+0x14b38` | `ActionRealData` | 23 | `0x144241530` |
| `+0x14b68` | `ActionTrainingMoveRoute` | 23 | `0x14561eee0` |
| `+0x14ba0` | `ActionPostPlay` | 23 | `0x14561eee0` |

Three subobjects resist naming because their constructors write no vtable within their own extent:
`+0x06d48` (ctor `0x14415cf00`, 0x7c bytes), `+0x0c7e8` (ctor `0x144338e40`, 0x2d3 bytes) and
`+0x0d180` (ctor `0x144140a70`, 0x11a bytes). `+0x00010` has no `lea` in the constructor at all — it
is built by an inlined base.

**One 23-slot `match::player` class is built somewhere else entirely: `ActionRL`** (vftable
`0x146be8370`). Its vtable is written at exactly one site image-wide, `0x1442418ae`, which is
outside the executor constructor's extent (`0x144141500..0x14414268d`). Whose object owns it is
**unresolved**. [b for the single write site, found by an image-wide `lea rip`-relative scan for
this chapter; c for what it means]

The parent also holds the off-ball AI: `+0x28` = `match::ai::PlayerDefence`, `+0xd0a0` =
`match::ai::AvoidPlayer`, `+0xd0e8` = `match::ai::AvoidArea`. The executors and the off-ball brain
are members of the **same** object. [b]

### The action-id → executor dispatch is NOT a table [b, three controls]

Still open, and still narrowed rather than answered. Three independent searches come back empty:

1. **No u32 offset table.** Scanning the whole 352 MB image for any window of 32 dwords containing
   ≥6 of the 102 subobject offsets: **0 windows**. No run of ≥3 consecutive offsets anywhere.
2. **No u16 offset table.** Every offset fits in 16 bits; the same scan over u16 gives **0 windows**.
3. **Nothing computes `parent + executorOffset` outside construction.** Decoding every instruction
   in `.xcode` whose disp32 equals one of the 102 offsets and classifying by zone: all fall in the
   constructor, the destructor or the 102 unwind funclets, except **four** one-off accessor sites —
   `0x145430be2`, `0x1454317ca`, `0x144144365`, `0x1441446f3`.

The constructor also rules out self-registration: it stores each subobject pointer only to `rbp+0x48`
(the unwind frame slot the funclets read back as `[rdx+0x60]`) and passes **no** subobject pointer in
`rdx`/`r8`/`r9` to any call — 0 sites. So the executor for an action id is reached through a
**stored pointer**. The remaining lead is the writer of the action manager's current-action pointer
(`work+0xd30`; accessor `0x143eee720`). None of the four probes chased it; **still open.**

**Related but not the answer, and not to be confused with it.** A leaf initialiser at
`0x1441442f5..0x1441446f3` fills a **130-slot pointer table** at `<base>+0x15a38..+0x15e40` whose
~83 targets are *not* built by `0x144141500`. Whose object `rdx` is remains unresolved [c].

**What the probes *did* find is a different, real seam:** the *carrier brain → kick executor*
channel is a global 22-entry pointer table at `0x1486bfbc0`, written once by `0x1443395e0` (one
caller: `0x14565083e`, inside `BallPlayer`'s ctor wrapper) and read by `0x1443395a0(playerIdx)` at
**30 call sites**, 15 of which are slot 6 of a kick executor. That is how the executor finds the
*decision*; it is not how the manager finds the *executor*. Both caller counts re-derived by an
independent rel32 scan for this chapter. [b]

---

## The carrier handoff — what is published, what the executor computes

`docs/ball-carrier-brain.md` is authoritative for what the carrier decides. The seam is:

* **Registration.** `BallPlayer`'s ctor wrapper `0x145650800` stores its player index at `BP+0x6998`
  (`0x145650824`) and registers `&BP+0x5350` — the brain's **result record** — with `0x1443395e0`
  at `0x14565083e`. The record is never copied; the executor reads it in place. [b]
* **Fetch.** `0x1443395a0(idx)`: `cmp ecx,0x15`, table `0x1486bfbc0`, falling back to a shared empty
  record at `0x1486bfc70`. [b]
* **Translation.** The carrier's answer record → result record is `0x145651cb0` (class jump table
  `0x145651fb0`), whose pass arm `0x145652260` copies `answer+0x24 → result+0x20`,
  `answer+0x25 → result+0x21`, `answer+0x26/27/28/29/2b → result+0x23` bits 1/2/8/0x10/0x20 and
  `answer+0x2a → result+0x22`. **This closes ball-carrier-brain.md open question 15.** [b]
* **Consumption.** `ActionShortPass::slot6` (`0x1441ad450`) is the canonical body and the only one
  emulated end to end, on both images with identical rows: published target ≤ `0x15` →
  `work+0xe88 = target`, return true; `result+0x20 != 0` → `work+0xffc |= 0x10`;
  `result+0x23 & 0x20` → `work+0xffa = 1`; target > `0x15` → fall back to
  `0x1442dee30(match, teamIdx, 0)` and return false if that fails too.
  Rows: `(7,0,0)→(1,7,0,0)`; `(7,2,0)→(1,7,0,16)`; `(7,0,0x20)→(1,7,1,0)`; `(0xff,0,0)→(0,0,0,0)`.
  [a-emulated]

**Fields the executors actually read off the result record:** `+0x1c` target player (18 sites),
`+0x20` preamble flag (**one** real consumer, `ActionShortPass`), `+0x22`, `+0x23` bit-flags (12
sites), `+0xc..+0x14` shot aim and `+0x8` shot type (`ActionShoot`, `ActionPenaltyKick`), `+0x18`
clear power (`ActionClear`), `+0x34..+0x46` (dribble/feint executors). **Never read anywhere:
`+0x21`** — see § Negatives. [b]

**The executor computes, the brain does not:** the aim heading (resolved in the shared slot 2 from
the team attack direction at `teamAI+0x28c` through `0x14563d3e0` / `0x144345ae0` / `0x144347c20`),
the kick-work power scalars (`work+0xe74/0xe78/0xe7c`), the delivery-kind byte (`work+0xff9`), the
set-piece target when the brain named none, and — for `ActionThroughPass`, `ActionLongPass`,
`ActionShoot`, `ActionCentering` — the geometry that consumes the published target.

### What `0x145644700` actually changes

`0x145648f30` builds a 0x60-byte request (`+0x20 = 0xff` result, `+0x24 = passer index`,
`+0x2c/0x30/0x34 = aim floats`) and calls `0x145644700` up to three times with a relaxation mode
0/1/2, returning the chosen receiver index. `0x1441aecd0` is the executor-side resolver: it uses the
brain's named receiver when there is one (`0x143db2170`, result ≤ `0x15`) and only otherwise runs
the search. **This closes ball-carrier-brain.md open question 20** — the chain
`0x144249dbf → 0x1441af000 → 0x1441aecd0 → 0x145648f30 → 0x145644700` is "resolve the pass
receiver". [b]

Inside the search, the reads of the off-ball runner's action id at `teamAI+0x8f4c+slot*4` are a
**score weight and a boolean predicate — not a target override, not a technique, not a lead**:

* `0x145646b27..0x145646b9a`: a candidate mate whose action id is `0x1d`/`0x1e`/`0x1f` **and** whose
  run record (`teamAI+0x2c4+slot*0x44`) is valid with sub-mode **13 (0xd, ChanceSpaceRun kind 3)**
  takes weight **−80.0**; every other id, every other sub-mode and an invalid record take **−50.0**.
  Emulated over ten (id, sub-mode) pairs, all as stated. [a-emulated]
* The weights are written unconditionally at `0x145645bb3` / `0x145645bc3` from the shared cells
  `0x14670f5b0` (−80.0, **23** referrers) and `0x146415e44` (−50.0, **37** referrers) — both values
  and refcounts verified here against `build/exe_constant_census.json`. [b]
* `0x145645dc3`: a boolean predicate keyed on sub-mode `0x17` (ChanceSpaceRun kind 15). [b]
* Three `== 0x26` (CenteringGet) tests at `0x145645458`, `0x145646281`, `0x145647fbb` are
  eligibility *exemptions*, paired with `0x144301850(entity) == 0xf`. [b]

---

## The run executors

### `ActionSpaceRun::vf18` (`0x1441f3010`) is a path compiler, not "the movement code"

Once per decision it fills a `0x4ec`-byte path object at `pathOwner+0x920` (reset `0x1443264a0`,
add-waypoint `0x1443252d0`, finalise `0x144325340`) and memcpy's it into `action+0x8c`. Waypoints
are **2-D**: `0x1443252d0` copies x and z, writes 0.0 over y (`0x1443252f9`) and stamps a
hard-coded 16.0f radius per waypoint (`mov dword [rbx+rax*4+0x3f0], 0x41800000`). Its `xmm2` float
and `r9d` flag arguments are **never read**, so every caller passing −1.0f there is passing a dead
argument. [b]

Its real signature is `vf18(this, work, pathOwner, arg4, vec3* outTarget, int* outGait,
int* outMoveClass)`. The shared tail at `0x1441f3961` writes the target to `*arg5`, mirrors it into
`action+0x30` when `byte[action+0x57c]==0`, then calls slot 6, slot **13** (→ `*outGait`) and slot
**12** (→ `*outMoveClass`), and forces `*outMoveClass = 3` when the gait is ≤ 1
(`0x1441f39d7`/`0x1441f39ea`/`0x1441f39fb`/`0x1441f3a0f`). The executor's whole output to the layer
below is **(target vec3, gait int, movement-class int, 0x4ec-byte path)**. [b; a-emulated for
gait = 2 / class = 0 on `ActionSpaceRun`]

### The dispatch key is not the selector's tag

Immediately before the jump table, `vf18` calls `0x144261f10(this, work)` at `0x1441f3286`, and that
function **overwrites `action+0x54`** through its own 27-entry jump table at `0x1442628cc`. It is a
per-frame run-phase state machine. In the harness a seeded sub-mode of 15 came out of it as 8.
So the id the ChanceSpaceRun kind map writes is a **seed**, not the dispatch key — and the standing
belief that "kind 6 is never tagged, therefore handler `0x1441f360b` never runs" is **unproven in
both directions**. [a-emulated + b]

### The two-level dispatcher — corrected twice

*(Hand-decoded; the L1/L2 tables and the seven fall-through handlers stand. The count does not.)*

```
mov  ecx,[rdi+0x54]                    ; sub-mode id (already rewritten, see above)
lea  eax,[rcx-1] ; cmp eax,0x19 ; ja default
mov  eax,[base + rax*4 + 0x41f3b20]    ; L1: 26 image-relative dwords
jmp  base+eax
```

Seven ids (3, 7, 17, 19, 20, 22, 23) land on `0x1441f37c6`, a **second-level dispatcher** re-indexing
the same id through a 21-entry table at `0x1441f3b88`, and all seven resolve to seven **different**
handlers (`0x1441f37e0`, `…f4`, `…08`, `…1c`, `…30`, `…44`, `…58`).

> **CORRECTION to [match-ai-decoded.md](match-ai-decoded.md), narrowed 2026-09-19.** That chapter
> concludes kinds 1, 4, 12, 13, 15 "look alike" because they share the fall-through. They do **not**
> share a handler: the second level gives each its own handler and its own helper. But this chapter
> never emulated any of the seven, and they all fall into the same tail `0x1441f386a`, so the honest
> statement is **"each has its own sub-state machine; whether their emitted geometry differs was not
> established"** — not "those kinds produce distinct movement". One of them is *known* to differ
> from the rest in a way that matters: id 3's helper `0x144268630` branches on the role code
> (§ The cross-role answer). [b]
>
> **CORRECTION to the 2026-09-19 version of this file.** It said "26 distinct run-path handlers, one
> per sub-mode id". There are **25**: both tables were dumped from PRISTINE for this chapter —
> L1 (`0x1441f3b20`) has 19 distinct entries of which one is the L2 dispatcher, so **18** real L1
> handlers, and L1 entries 7 and 20 (**sub-mode ids 8 and 21**) hold the *same* address
> `0x1441f32b7`. L2 (`0x1441f3b88`) has 8 distinct entries of which one is the shared tail
> `0x1441f386a`, so **7** real handlers. 18 + 7 = **25 distinct handler entries for 26 ids**. [b]

Fifteen of the L1 entries are a uniform 5-instruction thunk into a dedicated path builder in the
contiguous band `0x1441fa400..0x144200acc`; three (ids 1, 6, 14) are inlined in `vf18`. The seven L2
handlers are **not path builders**: each takes `lea rcx,[this+0x5ac/0x5b4/0x5bc/0x5bd/0x5c0/0x5cc/
0x5d8]`, calls a helper in the `0x14425x`–`0x14426x` band and falls into the shared tail
`0x1441f386a`, which only copies the path's current point (or the player's own position) into the
out vec. They are sub-state machines. Note `+0x5bc` and `+0x5bd` are one byte apart, so those are
flags, not subobjects. **The seven, named at last** (dumped from L2 `0x1441f3b88` and disassembled
here — the previous version gave no helper address, which made the gap unlookupable):

| sub-mode id | ChanceSpaceRun kind | handler | `this+` | helper | geometry |
|---|---|---|---|---|---|
| 3 | kind 1 | `0x1441f37e0` | `+0x5cc` | `0x144268630` | **NOT emulated**; *is* role-sensitive (−5.0 / −6.0) |
| 7 | — | `0x1441f3858` | `+0x5d8` | `0x144255a70` | NOT emulated |
| 17 | — | `0x1441f3844` | `+0x5b4` | `0x144265bb0` | NOT emulated |
| 19 | kind 12 | `0x1441f3830` | `+0x5ac` | `0x144265680` | NOT emulated; reaches a role read at depth 3 (`0x143d33643` in `0x143d33480`) |
| 20 | kind 13 | `0x1441f381c` | `+0x5c0` | `0x144268190` | NOT emulated |
| 22 | kind 4 | `0x1441f3808` | `+0x5bd` | `0x144267100` | NOT emulated |
| 23 | kind 15 | `0x1441f37f4` | `+0x5bc` | `0x1442668a0` | NOT emulated |

[b for the table; the "NOT emulated" column is the scope statement the chapter previously lacked —
see § Open 21]

### The shared geometry core — where a run actually points

Three builders (ids 8/21, 11, 15) route through `0x143d222e0`, emulated to closed form:

1. reject unless `(dst.x − src.x)·attackDir ≥ 1.0`;
2. `heading = rotateToward(bearing(src→dst), teamAttackAngle, |Δ|·w)`, using the game's own degree
   helpers `0x143c6fd80` (bearing), `0x144345690` (rotate-toward), `0x144345ae0` (normalise),
   `0x144347c20` (advance). **Angle convention proved by emulation: 0° = +Z, 90° = +X;**
3. `w` = 1.0 normally; a 0.7 floor plus a 0.3 term fading from 7 m to 18 m of lateral ball distance;
   and **0.0** when the player already holds action id `0x1d`/`0x1e`/`0x1f` and his per-slot
   record's `[+8] == 2` (branch at `0x143d22539`);
4. cast a 1000 m ray from `dst` along that heading and **project** it onto the plane
   `x = rawOpponentLineX + attackDir·10.0`; either branch ends with `out.x == planeX` **exactly**;
5. clamp into the pitch rectangle (`0x1442ffc30`; pitch `+0x00` = half-length, `+0x04` = half-width).

So for the whole AIM family the run target's **X is pinned every frame to a plane 10 m beyond the
opponent's defensive line**; only the Z is negotiable, and the Z is a straightening of "point at the
middle of the line" toward "straight down the pitch". Emulated: runner (8,0,−5) with line at +30 →
w = 1.0, target **(40.0, 0.0, 0.000)**; runner (10,0,−15) → w = 0.700, **(40.0, 0.0, 1.955)** (which
matches `10·cot(53.130+25.809) = 1.965` to 0.01 m); line moved to +20 → **(30.0, 0.0, 0.000)**.
[a-emulated]

The 10.0 m break distance is the sixth argument at **all 14** call sites of `0x143d222e0` — the same
cell `0x145a8dd7c`, whose value (10.0f) and 1,832 referrers were verified here. The caller count of
14 was re-derived by an independent rel32 scan. [b]

### The offside answer

There are two line functions and the executors use **both, differently**:

* `0x143d24d60(mgr, side)` — the **raw** opponent defensive-line X from `matchInfo + 0x44 + opp*0x14`,
  optionally replaced by the ball X or a predicted holder X. **51 call sites** (re-derived). [b]
* `0x143d24e70(mgr, side, entIdx, flag)` — the **full offside line**: the max, in attack-direction
  terms, of {raw line, ball X at `matchInfo+0x25bbc`, two predicted defender X's via `0x143d3c6d0`
  + `0x143d22ce0`}, then **clamped to 0.0 — you cannot be offside in your own half**
  (`0x143d24fbf comiss / jbe / xorps`). **53 call sites** (re-derived). [b]

The offside line becomes the *mid* waypoint (`action+0x3c`); the *final* target plane uses the
**raw** line + 10 m. Emulated endpoint-to-line relations: ids 8/21, 11, 15, 9 → line + 10.0 m;
id 16 → +2.0; id 12 → −2.0; id 10 → +8.18; `ActionDiagonalRun::vf18` → +5.0. **So runs are neither
clamped behind the line nor ignoring it: the target is pinned to a fixed offset beyond it, with no
timing term anywhere in the executor.** Timing lives upstream (the selector's 0.2 s commitment) and
in `0x144200ad0`, which aborts sub-mode 8 after `fps·1.5` frames using the per-slot timing ring.
[a-emulated for the relations, b for the plumbing]

### The cross-role answer

**Run geometry is role-blind across everything that was tested — which is 15 of the 25 handler
entries and 14 of the 30 distinct slot-20 bodies.** 15 level-1 path builders × 11 role codes × 4
players (660 runs), plus 15 builders × 144 scenarios (ball × line depth × holder) × 3 players × 3
role codes (2,160 runs), plus 14 slot-20 emitters × 11 roles: **not one emitted target or waypoint
list differed**. [a-emulated]

> **SCOPE CORRECTION 2026-09-19, and a counter-example.** The seven **second-level** handlers were
> never in the emulation set, and at least one of them is role-sensitive. Sub-mode **id 3** (=
> ChanceSpaceRun **kind 1**) calls helper `0x144268630`, which reads the role array in its **own
> body**: `0x144268754 mov eax,[r14+0x42b8]` / `0x144268764 mov eax,[r14+rax*4+0x42b8]` (index =
> slot % 11, the `mul`/`shr 3`/`imul 0xb` sequence at `0x144268740..0x14426874d`), then
> `0x14426876c add eax,-3 ; cmp eax,1 ; jbe` selects **−5.0** (cell `0x145b1d940`, at `0x14426877f`)
> for role codes 3–4 and **−6.0** (cell `0x145ace398`, at `0x144268774`) for every other role, and
> feeds it as an offset into the offside-line call `0x1442687a4 call 0x143d24e70`. A second helper,
> id 19's `0x144265680`, reaches a role read at depth 3 (`0x143d33643`/`0x143d3364d` inside
> `0x143d33480`). The other five show **no** role read at depth 3
> (`0x1442668a0`, `0x144267100`, `0x144268190`, `0x144265bb0`, `0x144255a70`). So the practical
> answer below holds for the kinds tested and **must not be extended to kind 1**. [b]

This is **not** "the code never touches it": the role array at `teamAI + 0x42b8 + slot*4` *is* read
at four sites inside builder 8/21's closure (caught live at `TEAM0+0x42c4` for slot 3, RIPs
`0x143d1cc84`, `0x143d340b8`, `0x143d35318`, `0x143d38563`), and `0x143d1ca10` contains a genuine
`cmp eax,7 ; jl` attacking-role gate. No configuration was found in which that gate moved the
target. The two Overlap classes are the proof by construction: Konami wrote two classes for the same
idea and made them differ by **constants** — `ActionOverlapSB::vf20` (`0x1441d9220`) caps the
heading blend at 45.0° (`0x145b1d910`), `ActionOverlapCB::vf20` (`0x1441db5d0`) at 30.0°
(`0x145a8dd80`) with a state-`==5` blend flip — and by nothing else; their slot-20 closures (30 and
19 functions) contain **zero** role reads.

**Practical answer for the owner: for every run tested, a midfielder handed ChanceSpaceRun runs
exactly the striker's path, so widening the selectors' eligibility gates is geometrically safe** —
what you get is a correctly-shaped run made by the wrong body, not a broken one. Confidence **high
for the tested set** (15 builders, 14 emitters), **none for the seven L2 sub-modes**, and
**kind 1 is provably role-sensitive**: a non-attacking role runs it 1 m deeper. Residuals are
Open 6 and Open 21.

### Kind 6 — the run that does not exist in this build

Sub-mode id 15, handler `0x1441f360b`, builder `0x1441fff70`. Emulated on a synthetic pitch (attack
+X, opponent line +30, ball (−5,0,0)): `action+0x3c ← (30,0,dst.z)` and the emitted target ←
**(40.0, 0.0, 0.0)**; line at +20 → (30.0, 0.0, 0.0); runner (10,0,−15) → (40, 0, +1.955); runner
(12,0,+15) → (40, 0, −2.115); runner (0,0,+5) → (40, 0, −0.496). Three waypoints: own position, the
line point, the point beyond it. In football terms: **a straight in-behind sprint to a point ten
metres past the last defender, aimed between your own channel and the centre of the defensive
line** — no check-back, no curve, no hold. [a-emulated]

### Per-sub-mode endpoint geometry (one fixed world: runner (8,0,−5), attack +X, line +30, ball (−5,0,0))

**Scope, stated because the table was previously silent about it: this covers 18 of the 26 sub-mode
ids and 10 of the 16 ChanceSpaceRun kinds.** Missing are id 1 (inlined arm, kind 0) and the seven
second-level ids 3, 7, 17, 19, 20, 22, 23 — i.e. kinds 1, 4, 12, 13 and 15 have **no emitted
geometry in this chapter**. Their handler and helper addresses are tabulated in § The two-level
dispatcher so the gap is at least a lookup; emulating them is Open 21.

| id | endpoint | shape | re-run at line 20 |
|---|---|---|---|
| 2 | (5.88, 0, −3.675) | short re-position behind the runner | — |
| 5 | 3 waypoints, (−9.81,0,0) → (30,0,12) | check-back then a wide swing | — |
| 8 / 21 | line + 10 | AIM family (shared builder `0x1441fdf50`) | → 30.0 |
| 9 | line + 10, 2 points | straight in-behind | → 30.0 |
| 10 | (38.18, 0, 1.57) = line + 8.18 via a mid point | — | → 28.18 |
| 11 | line + 10, 3 points | AIM family | → 30.0 |
| 12 | (28,0,0) = line − 2 via (22.5,0,−2.5) | stays onside | → 18.0 |
| 13 | (16,0,−5) | straight 8 m step, line-independent here | — |
| 14 | the selector's run-target vec3, **verbatim** | 2-waypoint path from a 0.2 s velocity extrapolation | — |
| 15 | line + 10, 3 points | **kind 6** | → 30.0 |
| 16 | (32,0,0) = line + 2 via (32,0,−2) | kind 9 | → 22.0 |
| 18 | (−0.48, 0, 0.3) | run back toward the ball | — |
| 24 | (8,0,−20) | pure lateral pull to the touchline | — |
| 25 | (10,0,0) via (0,0,0) | — | — |
| 6 | player pos + 1.0 m along attackDir | inline handler `0x1441f3637` | — [b] |
| 4, 26 | **no path built in any of 144 scenarios** | bail on an unmet precondition; shapes **UNKNOWN** | — |

[a-emulated except where marked. `0x1441fbc40` (id 26) is the largest builder in the band
(0x1576 bytes) and is almost certainly the most interesting one — Open.]

### `ActionDiagonalRun`

`vf20` (`0x144200e10`) is a `0x53`-byte stub: writes the ball position and tail-jumps to the shared
`0x143d3b5c0`. All the geometry is in `vf18` (`0x144201d60`), a **single builder, not a dispatcher**,
reading the raw line directly (`0x144201f81 movss xmm6,[rax+rdx*4+0x44]`). Emulated: line 30 →
[(8,0,−5),(35,0,2.4625)]; line 20 → [(8,0,−5),(25,0,0.5951)]; line 45 → [(8,0,−5),(50,0,8.5071)] —
i.e. **endpoint = line + 5.0 m**, with a Z that swings across the pitch, and for some starts a mid
waypoint that makes the shape "out wide, then straight". Identical for all 11 role codes.
The +5.0 constant **does not appear as a rip-relative float literal** anywhere in
`0x144201d60..0x14420235e`, so the diagonal's depth is **not actionable** (Open 3). [a-emulated]

### The other attacking executors, at slot-20 level

`ActionPostPlay::vf20` (`0x1442135b0`) is `0x2d` bytes and is literally `out = ball position` (its
real geometry, `vf18 0x1442149d0`, was **not** examined). `ActionPassAndGo::vf20` (`0x1441bad20`)
and `ActionPassSupport::vf20` (`0x1441dcf90`) both start from the ball position and branch on the
per-slot record; **neither reads pad state**, and `ActionPassAndGo`'s slot 2 is the unmodified base
`0x145620a00` (confirmed by the 55-class census), so **the give-and-go must arrive as an action-id
assignment from above** — its slot-4/5 bodies (`0x1441badd0`/`0x1441baef0`) were not read, so the
precise trigger is **not established**. `ActionMoveOnPass::vf20` (`0x14420e2e0`) takes the ball's
predicted point from `0x144307180(0x1442d6c50(mgr))`. `ActionPostMan::vf20` (`0x144206a30`) tests
both teams' holder indices through the action-class predicate `0x144311e20`. **`ActionGoalGet` and
`ActionOffsideTrap` do not override slot 20** (both `0x1456220d0`) — but under the corrected reading
this is *not* "they emit no target": both have real slot-4 destinations
(`ActionGoalGet::vf4 = 0x144212530`, `ActionOffsideTrap::vf4 = 0x1442067f0`). [b, vtable entries
re-read from PRISTINE here]

### Inputs that shape a run

The player's own position and (for id 14) his 0.2 s velocity extrapolation; the opponent's
defensive-line X; the ball position; the team's attack angle at `teamAI+0x288` and sign byte at
`+0x28c`; the pitch rectangle; the per-slot ActionParam record at `teamAI + 0x2c4 + slot*0x44`;
and **the selector's run-target vec3 at `teamAI + 0x2a4 + slot*0x44`** (writer `0x1442f1ba0`;
consumed verbatim by sub-mode 14 at `0x1441f35ef`). The per-slot timing ring at
`teamAI + 0x8f78 + slot*0x34` (4 entries of 12 bytes, head index `+0x30`, accessor `0x1442eda20`)
carries **timing, not geometry**. [b]

---

## The defensive executors

### Where the standoff comes from — and it is not a radius

`ActionMark::vf4` (`0x1441a2a80`) caches the marked man's id into `this+0x38/+0x3c` and tail-calls
**`0x143e1c9d0`**, which is also the *entire body* of `ActionPassCourseCut::vf4` (`0x14420a9a0`) —
so lane-blocking and marking compute the same destination. Three callers image-wide
(`0x1441a2b60`, `0x14420a9af`, `0x14421176e`), re-derived here. [b]

`0x143e1c9d0` loads the player's **formation-slot position** from `teamObj + (idx%11)*0x44 + 0x2a4`
and adjusts it toward the marked man only if three gates pass:

* `0x1442e48a0(0x1442ee570(teamObj)) >= 2` (`0x143e1ca8e`) — **probably** CPU difficulty: the
  accessor is the same `[+4]^[+0]` that `AiLevelUnit::GetParam` uses to index its table. **NOT
  PROVEN** (Open 4);
* `teamObj + slot*0x44 + 0x2b0 == 0x32` (`0x143e1ca93`) — the master switch for man-marking;
* the slot's marked-man id `teamObj + 0x5bc + slot*4 <= 0x15` (`0x143e1caa3`).

Then `0x143e1bfb0` ends with, literally:

```
out.x += (markTarget.x - out.x) * wX / 100      ; 0x143e1c27f..0x143e1c2ac
out.z += (markTarget.z - out.z) * wZ / 100      ; 0x143e1c2b2..0x143e1c2d7
```

where `markTarget` is a second vec3 in the **same** formation-slot record
(`teamObj + slot*0x44 + 0x2b4` / `+0x2bc`) and 100.0 is the shared cell `0x145a8aa4c`
(1,701 referrers, verified). **There is no radius anywhere in the chain.** [b]

**The weights are killed by ball position — BOTH of them.** Inside `0x143e1bfb0`
(`0x143e1c1b8..0x143e1c214`): `u = attackDir·ball.x`; `thr = attackDir·[matchWork + team*20 + 0x44]`;
`t = clamp((u − (thr+10))/10, 0, 1)`; then **`wX = wX_base·(1 − t)` AND `wZ = wZ_base·(1 − t)`**.
Constants: 10.0 (`0x145a8dd7c`) at `0x143e1c1e1`, 20.0 (`0x145a8aa44`) at `0x143e1c1e9`.

> **CORRECTED 2026-09-19.** The previous text ramped only the X weight, which would have meant the
> marker keeps tracking his man laterally once the ramp opens. He does not — **he goes fully zonal
> in both axes**, which is what the emulated table below already showed (ball ≥ −10 → target =
> the zonal slot exactly). The two arms are symmetric: X is `xmm7·(1 − t)` built at
> `0x143e1c219 xorps xmm2,xmm2` / `0x143e1c21c subss xmm2,xmm7` / `0x143e1c220 mulss xmm2,xmm3` /
> `0x143e1c224 divss xmm2,xmm9` / `0x143e1c229 addss xmm2,xmm7`, applied to out.x at
> `0x143e1c298`; Z is `xmm8·(1 − t)` built at `0x143e1c275 subss xmm6,xmm8` (xmm6 is zeroed at
> `0x143e1bfdd` and never rewritten) / `0x143e1c28f mulss xmm6,xmm3` / `0x143e1c293 divss xmm6,xmm9`
> / `0x143e1c29c addss xmm6,xmm8`, applied to out.z at `0x143e1c2c2`. The **only** X-only switch in
> the chain is the per-slot byte at `teamObj+0xb478+slot`. [b]

Emulated with a CB at x = −30 marking a
striker 6.083 m away, `thr` = −30, attackDir +1:

| ball.x | emitted target | distance to the man | moved from the zonal slot |
|---|---|---|---|
| ≤ −20 | (−24.000, 0.700) | **0.300 m** | 6.041 m |
| −15 | (−27.000, 0.350) | 3.070 m | — |
| −12 | (−28.800, 0.140) | — | — |
| ≥ −10 | (−30.000, 0.000) | **6.083 m** | **0.000 m** |

That 10-metre window **is** the owner's "stand off and wait", and it is a property of where the ball
is relative to the team's line field — not of any distance to the striker.

**And that line field is one the chapter already decodes elsewhere** (cross-reference added
2026-09-19): the ramp threshold `[matchWork + team*20 + 0x44]` is **the same per-team defensive-line
table that `0x143d24d60` reads** in § The offside answer. Both go through the same accessor
`0x140efd260` and then index the same base with the same stride — the ramp at
`0x143e1c1c1 lea rdx,[rcx+rcx*4]` / `0x143e1c1d5 mulss xmm1,[rax+rdx*4+0x44]` (indexed by the
marker's **own** side), the raw-line reader at `0x143d24d9a lea rax,[r8+r8*4]` /
`0x143d24d9e movss xmm6,[rcx+rax*4+0x44]` (indexed by the **opponent's** side, `sete r8b` at
`0x143d24d96`). So "find the writer of `matchWork+team*20+0x44`" is **one** open question, not two,
and `0x143d24e70` (the 0.0-clamped offside variant) is its consumer on the offside side. [b] When the ramp is open the
marker marks **tight**: sweeping the man from 1 m to 20 m upfield, the target stays a constant
0.300 m from him at every separation. The residual 0.300 m is a product of the harness's base
weights (`wX = 100`, `wZ = 70` from the undecoded `0x143e1c310`), **not** a stock constant (Open 5).
[a-emulated]

**Two earlier kill-switches, added 2026-09-19** — they run *before* the style tests and either one
zeroes **both** weights, so any list of "what defeats marking" that omits them is incomplete:
`0x143e1c121 call 0x1442e1200` with `r8d = 0xf` and `r9d` = the marked man's id (or `0xff` when the
slot has none, `0x143e1c10d`), and `0x143e1c13c call 0x1442e1200` with `r8d = 0xe`, `r9d = 0xff`;
each is followed by `test al,al ; jne 0x143e1c18c`, and `0x143e1c18c` is
`xorps xmm7,xmm7 / xorps xmm8,xmm8`. **What `0x1442e1200(_, playerIdx, queryId, otherIdx)` queries
is not identified** — it is the same query helper the executors use elsewhere with ids `0xd`/`0xe`/
`0xf`/`0x10`. Only if both fail do the style tests below run. [b]

Three more switches, all emulated:

* out-of-possession playing-style category **0xb** (`0x143e1c151`) zeroes both weights → target =
  the zonal slot, 6.083 m off the man;
* category **9** (`0x143e1c166`) adds +50 to both, clamped at 100 → **0.000 m** off the man. Both go
  through `0x1442e0510`, which is **role-gated** (it reads `teamObj+0x42b8+slot*4` and calls
  `0x1442bfdc0(rec, styleId, role)`);
* the per-slot byte `teamObj + 0xb478 + slot` (`0x143e1c233`) zeroes the **X** weight only — the
  defender slides across in Z with his man and **never steps up** (6.007 m off a man 6.083 m away).

### Why `ActionMark::vf20` is not the standoff

`0x144347c20(vec3* p, float* bearingDeg, float r)` is the universal steering-point emitter:
`p += (r·sin θ, 0, r·cos θ)`, with `|delta|` exactly `r` (emulated at r = 10: θ = 0 → (0,0,+10.000),
45 → (+7.0711,0,+7.0711), 90 → (+10.000,0,0), 180 → (0,0,−10.000), 270 → (−10.000,0,0)).
**1,121 direct rel32 callers** image-wide plus the wrapper `0x143d1b7e0` (count re-derived here).

**Most — not all — slot-20 bodies end there with a literal radius (CORRECTED 2026-09-19).** The
earlier "every slot-20 body" was false as a universal and contradicted this chapter's own readings
three sections later. Census over the 55 twenty-three-slot classes (30 distinct slot-20 bodies,
each walked over its chained-unwind chunks):

| | bodies | classes |
|---|---|---|
| call `0x144347c20` or its wrapper `0x143d1b7e0` **directly** | **17** | 39 (incl. the shared base `0x1456220d0`, 23 classes, three emitter calls at `0x14562234d`/`0x14562303d`/`0x1456230ee`) |
| reach it in **one further hop** | 5 | 5 (`ActionFreeMove`, `ActionPassAndGo`, `ActionPassSupport`, `ActionDiagonalRun`, `ActionPenaltyKickAfter`) |
| **no path at depth 2** | **8** | **11** |

The eight that never reach it: `0x140c83910` (`ActionLineBreak`, `ActionPullAway` — the `ret 0`
stub), `0x144175890` (`ActionPassGet` — picks between two **stored destinations**), `0x1441dec00`
(`ActionPassSupportThrowIn`, `ActionShortCornerMove`, `ActionFreeTrainingBreak`), `0x144206a30`
(`ActionPostMan`), `0x14420e2e0` (`ActionMoveOnPass`), `0x144210ce0` (`ActionWaitTimer`),
`0x1442135b0` (`ActionPostPlay` — literally `out = ball position`), `0x144241490`
(`ActionPkMatchNextKeeper`). At least three of those write an **absolute point**, which is exactly
what a "steering direction at a fixed radius" is not.

Literal radii where the emitter *is* reached: `ActionMark::vf20` 10.0 (`0x1441a22e2`),
`ActionCenteringGet::vf20` 10.0 ×4, `ActionPress::vf20` **3.0** (`0x1441903e3`), `ActionDelay`'s
`0x144199470` 100.0 ×2. **`ActionBasePosition::vf20` (`0x144181f80`) makes no direct call to
`0x144347c20` at all** — it reaches it only through the wrapper `0x143d1b7e0` at `0x144182325` and
`0x1441824a6`, so the old line crediting "10.0 ×2" to that body *and* again to `0x144189400`
double-counted the same emissions.

**The headline conclusion does not rest on this and is unaffected**: the destination is slot 4's
because `ActionMove::vf18` calls `[rax+0x20]` at `0x145625868` and copies the returned vec3 into the
caller's out vec at `0x14562587f..0x14562588a`, while the driver writes slot 20's and slot 21's
points into *different* fields (`+0x14`, `+0x2c`). And "radial closing is exactly 0.000 m" is still
true and vacuous **for `ActionMark`**, whose own radius is the literal 10.0. [b, census re-run for
this repair; a-emulated for `0x144347c20`]

`ActionMark::vf20` (`0x1441a1e50`) has two regimes. **Goal-side of the ball**
(`attackDir·ball.x > attackDir·self.x`, test at `0x1441a204f`) it **discards its inputs**:
`out = (self.x + attackDir·(2·w1 + 2·w2), 0, markedMan.z or ball.z)` — an x that is the player's
**own** x plus at most 4.0 m and that never references the marked man's x. Emulated with the base
emitter stubbed to four wildly different proposals ((−28,0,5.5), (0,0,0), (40,0,−30), (−99,0,99)),
the goal-side output was **(−28.000, 0.000, 1.000) for all four**; not goal-side, the output equalled
the proposal exactly for all four. `w1` is a bearing ramp (1 below 30°, 0 above 90°), `w2` a
ball-depth ramp between `5 − [pitch+0x18]` and `15 − [pitch+0x18]`. [a-emulated]

### Pressing

`ActionPress::vf20` (`0x1441902d0`): `out = matchWork+0x25bbc` (the ball) outright; if a carrier
exists, `out` is blended toward `carrier.pos + polar(carrier.facing, 3.0)` with weight `1 − 2d`,
where `d` is the predicted separation `int(fps·0.1+0.5)` frames from now — so the 3 m "step in front
instead of into his back" correction is **invisible beyond half a metre** (band cell `0x147850248`
= 0.5, slope `0x145b52fb0` = −2.0, both verified). A later branch resets `out` to the ball.
**Pressing intensity is not parameterised anywhere reachable**: the Press path's only non-geometric
inputs are one CPU-difficulty `GetParam` (`0x144193a21`, row in a register) and attributes `0x15`
(×2, in `0x144193150`) and `0x20` (in `vf6`, `0x144194210`). [b]

### How `ActionOffsideTrap` moves the line

It overrides exactly **four** slots against the `match::ai::ActionMove` base — **4** (`0x1442067f0`),
**5** (`0x144206970`), **12** (`0x140eeb6d0` = `mov eax,2; ret`) and **13** (`0x14172cb30` =
`mov eax,5; ret`) — of which 12 and 13 are the two-instruction constants. **Slot 15 is the shared
base `0x140c83810` (`mov al,1`), not an override**, so GIVEN #3's list of "4, 5, 12, 13, 15" was
itself wrong by one, and the earlier "overrides only vf4 and vf5" was wrong by two (diff re-run
against the base vtable for this repair). Its slot 20 is the unmodified base `0x1456220d0`. So the
GIVEN structural lead is closed, but the conclusion inverts under the corrected slot reading: the
trap moves the line **through slot 4, the destination**.

`vf4` returns `(player.x + attackDir·10.0, formationSlot.y, formationSlot.z)`
(`0x1442068eb..0x144206908`, cell `0x145a8dd7c`), replaced wholesale by the entity vec3 at
`entity+0x2838` when `|entity[0x2840] − player.z| < 7.0` (cell `0x145c36ac0`, verified = 7.0).
**Because the x term is relative to the player's CURRENT x and is recomputed every frame, the line
marches forward continuously while the executor is active — it never aims at an absolute line.**
`vf5` pushes exactly two waypoints (own position, that target) into the path builder at
`playerWork+0x920` and calls `0x145625720`. A depth-6 closure over both bodies (133 functions,
positive controls passing) reaches **no** attribute, playing style, skill card, CPU-difficulty
parameter or RNG: the trap is pure geometry, ungated at the executor layer. [b]

### Transition and cover

`ActionStopThink` is a **null executor**: `vf18` (`0x144203c20`) never calls vf4 or vf5 — it writes
`outPos = the player's own current position`, tag 0, action id `0x71`, returns true, and its call
closure is one function. A player on StopThink is commanded to stand exactly where he is, every
frame. `ActionCover::vf4` (`0x14420a340`) returns the formation-slot position verbatim with **no
cover geometry at all**, and its `vf20` (`0x14420c4d0`) is a lateral 10 m shuffle toward the ball's
side. `ActionTeammateMoving::vf4` (`0x1442064a0`) returns the formation-slot position.
`ActionDelay` is the difficulty-scaled jockey: `vf4` (`0x14419aa50`) returns a cached vec3 from
`this+0x8c`, `vf3` resets a half-second timer into `this+0xc0` and gait 3, and its `vf17` chain
(`0x14419d740`, confirmed as the slot-17 override in the census) reaches difficulty rows `0x0d`
(gate), `0x0f` (×2), `0x10` (gate) and `0x11`. [b]

What marking and pressing genuinely share is not slot 13 but their **slot-5 movers** `0x145623990`
and `0x143e8c5c0`. `0x145623990` is the widest shared defensive mover (Delay, Press, Cover, Mark,
PassCourseCut, BasePosition) and it bails on pitch bounds read from `0x1442d6d80(match)`. [b]

### The movement/animation seam

Executors do **not** call the animation layer. Slot 5 fills the path builder at `playerWork+0x920`
(reset `0x1443264a0`, push `0x1443252d0`, finalise `0x144325340`) either from an explicit waypoint
list (`ActionOffsideTrap::vf5`) or from a route array at `playerWork+0x1aa0` (`0x145625720`), and
the animation layer consumes it. What crosses is a polyline of 12-byte `{x, y=0, z}` waypoints plus
a per-waypoint weight. **No animation id and no speed cross here**; gait travels separately as the
int the slot-2 driver keeps at `[rbp+0x77]` and the slot-12/13 tags. A depth-4 closure of 592
functions rooted at `vf18`, `vf20`, `vf6`, `vf13`, `0x144200ad0` and `0x144268ba0` reaches **zero**
functions that are exclusively `match::anime::*`. An earlier apparent hit was `0x140c853c0`
(`xor al,al; ret`), a stub in dozens of vtables including anime ones — reported here as the false
positive it is. **The one place the boundary is a call is the tackle** (below). [b]

---

## Kicks, tackles and set pieces

* **`ActionShortPass`** is decoded (above). **`ActionThroughPass`** is the only class whose slot 3 is
  not the `ret 0` stub (`0x144144070`).
* **`ActionSwitchPass`** resolves *no target of its own*: slots 4 and 5 are both the false stub and
  slot 6 (`0x144212a80`) is three instructions that zero `work+0xe7c` and return true. Vtable
  re-read from PRISTINE. [b]
* **`ActionFreeKick`**'s slot 6 is the bare `mov al,1; ret` (`0x140c83810`). Both take their aim
  entirely from the slot-2 tail's heading computation. [b]
* **`ActionFreeKickLong` and `ActionLongPass` have byte-identical vtables in all seven slots**
  (`0x14410f3d0`, `0x1456219d0`, `0x14561fe20`, `0x140c83910`, `0x1441ad530`, `0x140c853c0`,
  `0x1441b1500`) — so a long free kick does not merely *share* a body with a long pass, it **is** the
  same executor under two names. That body `0x1441b1500` is **3,654 bytes over seven chunks and was
  not decoded** (it does read attribute `0x35` three times, at `0x1441b1ed4`, `0x1441b210f`,
  `0x1441b21a6`, and uses the first result to flip the sign of an emitted float at `0x1441b1ee5`).
  Both classes are therefore **gate-only** in the class table; the earlier table marked
  `ActionFreeKickLong` "decoded" and `ActionLongPass` "gate-only" for the *same function*. [b, vtable
  + chained extents]
* **`ActionKickoff`** is the only class in the family with a real slot 5 (`0x1441c4880`): it reads
  the kick-off assignment table at `matchEnv+0x228d4+0x1840+idx*0xc8` into `work+0xe88`. [b]
* **`ActionCornerKick`** slot 6 (`0x1442057f0`): published `+0x1c`, fallback `0x1442053c0`,
  `work+0xe88`, `work+0xff9 = 2`. **`ActionFreeKick2ndPass`** slot 6 (`0x1441c4570`):
  `work+0x8bc = 0x29`, `work+0xe74` from a per-player float table `matchEnv+0x25b64+idx*4`,
  `work+0xe78 = 1.0f`. **`ActionPenaltyKick`** slot 6 (`0x144205ad0`) reads the shot-aim fields like
  `ActionShoot`. [b]
* **`ActionFreeKickCede`** is, as the map says, a 23-slot *movement* class, not a kick class: slot 20
  = base, slot 13 = `0x14140d670`, slot 12 = `0x140eeb6d0`. [b]
* **Tackles. ⚠ PATCHED ON THE INSTALLED IMAGE** — `0x1441a8a70` differs at `0x1441a8c2e`, and the
  neighbouring tackle function `0x1441a7fa0` (which holds the `0x143da79a0` handoff site
  `0x1441a81cc`) differs at `0x1441a82ec`, `0x1441a844c` and `0x1441a84a2`. Everything below was read
  from PRISTINE; if you A/B tackling, start from the diff in the header.
  `ActionTackle` slot 4 (`0x1441a8d90`) and slot 6 (`0x1441a8d40`) are the same body
  with different flags; both refuse when `0x1442de630(match) == actingPlayerIdx` ("you cannot tackle
  yourself" — a second independent site supporting "holder index" for that function), then
  tail-jump to `0x1441a8a70`, which writes `kickWork = 0x31` / `work+0x8bc = 0xd`, resolves the
  victim with `0x143e1b430` into `work+0xe88`/`work+0x900`, picks a motion id with
  `0x143e9d690(ctx+0x38, 0xd)` (default `0x11`) and **hands off to the animation layer through
  `0x143da79a0`** — **4 call sites image-wide**, all tackle/sliding (`0x1441a81cc`, `0x1441a8b0b`,
  `0x1441aa625`, `0x1441abc13`; re-derived here). `ActionSliding` slot 4 (`0x1441abb30`) gates on
  `0x143e9e7b0(ctx+0x38, 0xb)` then `0x1441ab9b0`; its slot 6 is the false stub. [b]
* **The foul threshold is NOT found**, and this chapter will not guess. 0.7f and 0.4f are far too
  common to triangulate, and the tackle chain crosses into the anime layer before any percentage is
  computed (Open 8).
* **The kick error model is not reached from the executor.** `0x14401a900` has **exactly one**
  caller (`0x144016d3d`, re-derived), whose own chain has exactly one entry:
  `match::anime::action::Kick` vtable slot 8 (`0x143ed0f80`). Anything that wants to change kick
  error must patch the anime layer. [b]

---

## Pass reception — the `PassGetRoute*` family

**It is a subobject after all** (§ architecture, amended). The work object (~0x1130 bytes) hangs off
`ActionPassGet+0x70` and holds ten strategy subobjects at fixed offsets; the destructor
`0x14416b0f0` confirms the list exactly.

| offset (from route work) | class | live? |
|---|---|---|
| `+0x80` | `PassGetRouteRelay` (owns `+0xc8` MoveStraightTrapRun, `+0x1d8` BallFollow) | live |
| `+0x250` | `PassGetRouteMoveStraightTrapStop` | live |
| `+0x370` | `PassGetRouteMovePositionAdjust` | reset only (Open 9) |
| `+0x3a8` | `PassGetRouteBallAvoid` | live |
| `+0x428` | `PassGetRouteTargetEnemy` | live — **the interception route** |
| `+0x560` | `PassGetRouteTransition` | **DEAD** |
| `+0xa88` | `PassGetRouteBallAdjust` (+ BallWait `+0xac0`, BallStepFollow `+0xae0`, BallRunFollow `+0xb08`) | **DEAD** |
| `+0xb20` | `PassGetRouteInputMove` | live (human) |
| `+0xb58` | `PassGetRouteThrowIn` | live, first in the chain |
| `+0xc44` | a 0x4e8-byte snapshot of the player object | — |

**The 15-method interface.** Slot 2 (`0x14415fd30`) is the base driver:
`active = (active ? !vf9 : vf8)`, and if active it runs `vf10, vf11, vf12, vf13` and then **`vf14`,
the emitter**, which writes through a 7-pointer out-bundle into `ActionPassGet`'s own fields. So
**slot 8 = entry test, slot 9 = exit test, slot 14 = emit**. `ActionPassGet::vf2` (`0x1441754d0` —
one of only four classes that override slot 2) builds the bundle from `&this+0x32/0x34/0x38/0x3c/
0x4c/0x58/0x40`, runs the route engine, classifies a state into `this+0x6c`, publishes seven fields
into the shared work object (`+0xe34/0xe35/0xe38/0xe3c/0xe44/0x1a83/0x1a84`) and chains to the
movement base vf2 `0x145620a00`. `ActionPassGet::vf20` (`0x144175890`) picks between **two** stored
destinations on `this+0x34` (0 → `this+0x40`, else → `this+0x4c`). [b]

**Strategy choice is a fixed priority chain, not a selection.** `0x14416c6c0` re-runs it every
frame: **ThrowIn → BallAvoid → InputMove → TargetEnemy → TrapStop → Relay**, first-true wins.

> **CORRECTED 2026-09-19 — that "pad/input module" is dt270.** `0x145348d70` is the **dt270
> `get(idx)`** (`build/dt270_liveness.json` meta: `get = 0x145348d70`, `wrapper = 0x145349560`) and
> idx `0x6c` is the object **`passget`** =
> `DevelopData/common/match/constant/player/passget.json`. So the bytes are named fields, not an
> input module: `+0x84` = **`naturalPassget.enable`** (read at `0x14416cb8f` and `0x14416cc6b` in
> this very function, 15 reader sites in all) and `+0x86` = **`naturalPassget.moveFreedom`**
> (`0x14416cb9e`, its only reader); the BallAvoid branch's `+0x68` is
> **`inputMovePosition.enable`** (9 readers). The reads *are* the branch operands
> (`cmp byte [r12+0x84],0 / je`, `cmp byte [r12+0x86],0 / je`), so they are effective, not dead
> loads. **This is the safest tuning surface in the subsystem — a data file, no exe patch, no shared
> cell.** Full field list in § Tunables → dt270. [b]

### Is a loose ball contested? — yes, and nothing arbitrates it

Receiver and interceptor run **different** strategies out of **one route-work object per player**
(each player's own `ActionPassGet+0x70` = parent `+0xfa00`; the contest is between two *instances* of
the same class, not two strategies inside one shared object — wording corrected 2026-09-19), selected
by a class field `routeWork+0xbb0` written by `0x144170540`: class **1** = "I am the pass target"
(`+0xbb4 = 0xff`, `0x1441707db`), class **2** = "a specific other player is involved"
(`+0xbb4 = that index`, `0x144170b75`). `PassGetRouteTargetEnemy::vf8` (`0x144168140`) refuses
outright unless `match+0x3308 == 1` (open play) **and**, for a CPU player, `routeWork+0x20 == 2`.

**There is no priority flag, no reservation and no "intended receiver wins" term** in `0x14416c6c0`,
`0x144170540` or `TargetEnemy::vf8`.

**One gate in `0x14416c6c0` does suppress the interception route, and it is not a reservation**
(added 2026-09-19): at `0x14416cc48` the chain calls `0x144163020` with `rcx = rbx+0x250` (the
TrapStop subobject) and `test al,al ; jne 0x14416cc6b` **skips the `TargetEnemy` driver call at
`0x14416cc64`**. `0x144163020` is neither TrapStop's slot 2 (`0x144163130`) nor its slot 8
(`0x144163670`), and it is **not** a receiver-priority term: it is a dt270-driven **air-ball
trap/stop pre-test** — `0x144163049 mov edx,0x6c ; 0x144163051 call 0x145348d70` then
`cmp byte [rax+0x50],0` = **`passget.inputMoveAir.enable`**, `cmp byte [rsi+0x48],0` =
`inputMoveAir.ballBound`, and `movss xmm0,[rsi+0x4c]` = `inputMoveAir.ballHeight` (liveness
confirms all three, confidence high). So a bouncing/airborne ball can take a player out of the
interception race by *route selection*, with no notion of who the pass was for.

Once both routes are live, arrival is decided by geometry and the movement layer. That is the honest
answer to the ricochets question; the race itself was **not** emulated (Open 10). [b]

### What reaches the route engine

Exactly **one** player attribute: index `0x19` = **`BALL_TOUCH`, UI name "Tight Possession"** at a
single call site, `0x14416dc80` (root `0x14416d430`), feeding `0x1443460c0` against
`routeWork+0xbc4`. Zero playing-style queries, zero skill-card tests, zero second attribute — a
call-site scan over the route band for nine known getters returns 0 sites each.

> **CORRECTED 2026-09-19 — the index was right, the name was wrong.** The earlier text called `0x19`
> `DATA_PARAMETER_CONSCIOUS_DEFENSE`. `CONSCIOUS_DEFENSE` is **`0x20`** (UI "Defensive Engagement"),
> which this chapter separately and correctly lists for `ActionPress::vf6`; `0x19` is `BALL_TOUCH`
> (UI "Tight Possession"). Source: `tools/data/attr_index_map.json`, both entries `confidence:
> proven`, mapping rule "match byte-array index = DATA_PARAMETER enum index + 7". An owner editing
> "the one lever on receiving routes" from the old text would have edited the wrong column of
> `master.db`. The follow-on sentence was also misleading and is withdrawn: the correct statement is
> that **no *second* attribute reaches the route** — not Ball Control (`0x18`), not Speed (`0x28`),
> not Offensive Awareness (`0x14`) — while the one that does is itself in the ball-control family.

What `0x1443460c0` *does* with attribute `0x19` is undecoded, so this is a wiring fact with no
magnitude (Open 11). [b]

**No offside constraint was FOUND** in the route engine — stated as *not found*, not *absent*: no
candidate offside function was enumerated and scanned for, so this negative is weaker than the
others in this chapter.

---

## The goalkeeper

The `match::player` keeper executors are almost pure geometry. **One** random number in the whole
family, **one** goalkeeping attribute between them, and every attribute a player would call
"goalkeeping" is consumed one layer down, in `match::anime::action::goal_keeper::*`.

### Positioning

`ActionKeeperBasePosition` (23-slot, `+0x13550`). Slot 4 (`0x144223580` → `0x1442246d0` →
`0x144228170`) computes a target point; **slot 20 (`0x144221e10`) turns it into a per-frame
heading, not a position**: `ownPosition + 10.0 m` at a bearing that is the keeper's current facing
rotated toward the desired bearing by a capped step — **20°** on the opponent-set-play branch
(`0x14422208f`), **45°** in state `0x3308==2` (`0x144222201`), **60°** near the ball
(`0x144222333`). The turn cap, not his pace, is what makes him look slow to reposition. The default
target is the ball's position **half a second ahead** (`0x144300f00(ball, T/2)`); the trajectory
table is 250 entries (`dword[0x148080f50]` = 250, read from PRISTINE here). The opponent-set-play
branch parks him 80 % of the way to his own goal line. [b]

**The one random number.** Every `2·T` ticks the keeper re-rolls a lateral standing error of
`RandInt(0..5) · 0.1 · (1 − clamp01((attr 0x16 − 40)/59))` metres, applied at 90° to his facing.
(**Naming settled 2026-09-19**: attribute index `0x16` is `DATA_PARAMETER_GK_DECISION`, whose UI name
is **"GK Awareness"** — `tools/data/attr_index_map.json`, `confidence: proven`. The chapter used
both names for it; they are the same field, and there is no contradiction to resolve, only a
convention: **`0x16` = GK_DECISION = GK Awareness** throughout.)
Sites re-read here: `0x144228863 mov edx, 6`; `0x14422886f call 0x144345e50`;
`0x144228880 mulss xmm0,[0x145a8dd68]` (= 0.1, verified); `0x144228888 mulss xmm0,xmm11`;
`0x14422888d movss [r14+0x50],xmm0`. Emulated: a 40-rated keeper stands up to **0.500 m** off his
spot (mean 0.250 m), a 70-rated one 0.246 m, a 99-rated one **exactly 0.000 m**. That is the whole
"does a bad keeper get caught out of position" model, and 0.5 m at its worst is far too small to
see. [a-emulated]

**dt270's `gk*` family is not the keeper's position.** `basePosition` has **20** `gks*`/`gkl*`
fields, and **14 of them have no reader at all** (count corrected 2026-09-19 — the earlier "nine"
was wrong, and one of the earlier examples, `gksHalfLineRateX_SB`, is itself an *unread* field).
The six that are read are `gklAdjustRateX` (`0x143de2568`), `gklBaseX`
(`0x143de23d3`/`0x143de8a89`), `gklBaseZRate` (`0x143de23fc`/`0x143de8aae`), `gklSupportRate`
(`0x143de2635`), `gklWidthZ` (`0x143e7f745`) and `gksWidthZ` (`0x143e7f73a`) — i.e. only inside
`0x143de2350`, `0x143de8520` and `0x143e7f4c0`, the *outfield* shape layer; "gks/gkl" reads as
goal-kick-short / goal-kick-long **team** shape. [b, `build/dt270_liveness.json`]

### Shot-stopping

`ActionKeeperPreSaveOperation::slot4` (`0x14422e6a0`) is the trigger: it watches the shooter's
action record (`byte[rec]==0x41` = the shot action, `u16[rec+0x1a]` elapsed, `u16[rec+0x1e]`
duration) and arms the save only when the shot animation has at most `(T·14)/30` ticks left —
roughly the last 0.47 s. `ActionKeeperCatching::slot6` (`0x14421d3a0`) and
`ActionKeeperPKSaving::slot6` (`0x14422cc00`) then walk the 250-frame prediction, gate on a **flat
3.5 m reach** (`12.25` = 3.5², cell `0x146b01d80`, verified; 40 referrers) with a 0.1 m tolerance,
and publish an intercept point plus a requested next action id into `match::Player+0x8bc`. **No
attribute term in the reach.** [b]

**Which save happens is not decided in `match::player`.** The proof is where the attributes are
read: Catching (`0x23`), Clearances (`0x24`), Collapsing/Reflexes (`0x25`) and Deflecting/Reach
(`0x26`) have 4, 5, 5 and 6 read sites image-wide, and **none is in a goalkeeper executor** except a
single Reflexes read in `ActionKeeperBlockLate::slot6` (`0x14421ff95`). They all converge on
`0x144032870`, whose **four** callers (`0x143f3149e`, `0x143f36f32`, `0x14402a68c`, `0x144037bed`
— re-derived here) are all in the anime band. [b]

`0x144032870(player, actionId, sub)` is the **save-quality selector**, emulated end to end. It picks
the attribute by action id (0x44/0x47 → Catching, 0x45 → Clearances, 0x46 → Reflexes when
`sub ∈ {1,4,5}` else Reach, 0x48/0x49 → Reach) and then compresses:

| all attributes | 0x44 | 0x45 | 0x46 sub0 | 0x47 | 0x48 | 0x49 | 0x46 sub1 | slow ball, 0x44 |
|---|---|---|---|---|---|---|---|---|
| 40 | 40 | 40 | **50** | 40 | **50** | 40 | **63** | **73** |
| 60 | 58 | 58 | 65 | 58 | 65 | 58 | 73 | 79 |
| 90 | 90 | 90 | 87 | 90 | 87 | 90 | 90 | 89 |
| 99 | 99 | 99 | 99 | 99 | 99 | 99 | 99 | 99 |

**Reach's output is floored at 50 and Reflexes' at 63** — the inline constants are `add ebx,0x34`
(52, `0x1440329d9`) and `lea ebx,[rax+0x41]` (65, `0x1440329b0`), but every result below 90 then
passes through `cmp ebx,0x5a ; jge ; imul ecx,ebx,0x62 ; …` (×0.98) at `0x1440329ed..0x1440329fe`,
so a 40-rated keeper gets 50 and 63, not 52 and 65 (the table above already prints the true
outputs; prose corrected 2026-09-19). And for a slow ball (< 50 km/h) on action `0x44` the
game takes `max(Catching, Reflexes, Reach)` and remaps it into 73..89 — so an easy catch is near
roster-uniform. That compression is why low-rated keepers do not feel low-rated. A separate +5
applies only when **both** a player flag query `0x143eadbe0(player, 0x1e)` is true **and** the
situation record's `+0x1c == 6` (emulated: neither alone does anything; flag `0x1e` unidentified).
[a-emulated]

### Coming out, distribution, oddities

`ActionKeeperPress::slot20` (`0x144218f10`) aims at the ball `T/3` ticks ahead, or at a stored
per-slot target when `teamAI[slot]+0x714 > 0`, snapping to the live ball inside 0.5 m. **No
attribute gates it** — the only attribute anywhere in the Press closure is HEIGHT. The engagement
envelope that *is* tunable is `0x146bdfd90` = 269.6164 = **16.42 m squared**, with exactly **one
referrer image-wide** (`0x144224d1d`; census `status=private, refcount=1` — verified here): the only
genuinely private, in-place-editable goalkeeping constant found.
`ActionKeeperPuntKick::slot6` reads `team+0xb44d` and, when set, aims the punt at a designated
per-slot target from `matchEnv+0x25b64`; `ActionKeeperThrow::slot6` takes its target entity index
from `team+0x275c`. The goal-kick case is visible in the carrier's own publisher `0x145651cb0`,
which emits action id **0x68** instead of `0x19` when `matchState+0x3308 == 3 && +0x34a0 == 6`. [b]

`ActionKeeperMakeshift::slot6` (`0x144220f30`) is 12 instructions: copy the player's facing into
`work+0xe74`, `+0xe7c = 1.0f`, `+0xe88 = 0xff`, `+0x1047 = 1`, return true — **an outfield player in
goal gets no keeper behaviour from this class**. `ActionKeeperPickupBall` has **no own body at all**:
slots 4/5/6 = `0x140c853c0` / `0x140c853c0` / `0x140c83810` (vtable re-read here). And
`match::ai::PlayerGKAuto` is a **one-slot class** (destructor only, vftable `0x146bbe008`) — there is
no CPU-goalkeeper brain with behaviour. [b]

### Structure found along the way, useful beyond keepers

There is a **113-entry per-action flag table at `0x146c14e80`** (one u32 per action id 0..0x70) with
a family of one-line predicates over it: `0x1443120f0` bit 9, `0x144311bf0` bit 10, `0x144311c90`
bit 23, `0x144311e40` bit 21, `0x1443122e0` bit 25, plus mask forms `0x144312110` (0x1fc0400) and
`0x144312260` (0x11fc0400). **Bit 9 selects the keeper action family `{0x44..0x49, 0x51}`** — the
same ids the save-quality selector switches on. `0x1442d6ba0(_, entityIdx)` returns the per-entity
action record whose `byte[0]` is the **current** action id, `u16[0x1a]` the elapsed frames and
`u16[0x1e]` the duration; `match::Player+0x8bc` is the **requested next** action id, consumed by
`0x14415b850` and fed to the same predicates. Action id `0x41` is the shot, `0x68` the goal kick.
This is a concrete handle on the action-id space — but it does **not** by itself resolve the
id → executor binding. [b]

---

## The input census

| input | reaches the executors? | where |
|---|---|---|
| **dt270** | **YES, at depth 0 — CORRECTED 2026-09-19.** 16 `get()` calls sit in `match::player` vtable-method bodies themselves: **15 with `edx = 0x6c` (`passget`)** in ten `PassGetRoute*` methods — `MovePositionAdjust#9 0x14416269c`, `MoveStraightTrapStop#8 0x14416369d`, `#12 0x14416494c`/`0x144164b53`, `TargetEnemy#8 0x144168169`, `#9 0x1441680c4`, `Relay#2 0x144165fe6`, `MoveStraightTrapRun#2 0x14424b1a4`, `#10 0x14424e97c`, `#11 0x14424d679`/`0x14424d6a1`, `#12 0x14424e3ab`/`0x14424e640`, `#14 0x14424b65e`/`0x14424b98f` — plus **`ActionBasePosition::vf4 0x1441832db` with `edx = 0xe2` (`basePosition`)** through the wrapper `0x145349560`. Nineteen more `passget` get-sites sit in the route family's non-vtable helpers (`0x14415f8c0`, `0x144163020`, `0x14416c6c0`, `0x144170540`, …). Still true and re-checked: **no keeper executor at all** (0 of 18,366 reader sites in `0x144215000..0x144243000`) | as listed; 26 read `passget` fields in § Tunables → dt270 |
| **attributes — runs** | **none.** 4 getter sites in a 528-function closure, both inside deep shared helpers with a register-supplied index. Positive control passes (the same method finds the getter from `0x143da92c0`) | — |
| **attributes — marking** | **none.** 61-function closure: no attribute, no card, no difficulty, no RNG | — |
| **attributes — defensive, elsewhere** | `ActionPress::vf6` **0x20 = `CONSCIOUS_DEFENSE`, "Defensive Engagement"** (`0x144194210`); the Press vf4 helper `0x144193150` **0x15 = `DEFENSE_DECISION`, "Defensive Awareness"** ×2; the `ActionMark::vf6` helper `0x1441a3300` **0x28 = SPEED** ×2; `ActionDelayMark::vf4` 0x15 via `0x143e2faf0` | as listed |
| **attribute `0x17` — NOT a defending attribute** | `ActionPassCourseCut::vf13` reads `0x17` at `0x14420ac35`. **Under the project's proven index alignment `0x17` is `DRIBBLE` ("Dribbling")** — `0x15` is Defensive Awareness, `0x16` GK Awareness (`tools/data/attr_index_map.json`, all `proven`; rule = DATA_PARAMETER + 7). The memory note `attr-0x17-defending` and `match-ai-decoded.md`'s gait threshold `19.0 − 0.1·attr(0x17)` both rest on the **superseded +0x15 alignment** that `docs/exe-gameplay-map.md` row 47 marks "WRONG — off by one, superseded 2026-09-18". So the base-position gait threshold scales with **Dribbling**, and our marking-tight edit re-aimed a Dribbling-scaled constant. Row added 2026-09-19 | `0x143da9432/43a`, `0x143daa771/779`, `0x1441810f9/101` (direct `0x1441172b0`); `0x143d09f06/f11`, `0x143e24da5/dad`, `0x143e27356/35e`, `0x143e2d8a2/8aa`, `0x14417ebdc/be9`, `0x14420ac27/c35` (via `0x1442dd650`) |
| **attributes — kicks and shots** (row added 2026-09-19; the census previously had none, implying a shot's execution was ability-free) | `ActionLongPass::slot6` = `ActionFreeKickLong::slot6` (`0x1441b1500`) reads **`0x35` (STRONGER_FOOT) three times** — `0x1441b1ed4`, `0x1441b210f`, `0x1441b21a6` — and the result is **used**, not discarded (`0x1441b1ed9 test al,al ; je` then `0x1441b1ee5 xorps xmm0,xmm13`, a sign flip on an emitted float). `ActionShoot::slot6` (`0x1441b4f60`) makes two reads with **computed** indices, `lea r8d,[r12+0x21]` (`0x1441b526f`) and `lea r8d,[r12+0x22]` (`0x1441b5283`) — if `r12 = 0` those are PLACE_KICKING and BALL_SPIN_CONTROL, **c-inferred** | as listed |
| **attributes — keepers** | GK_DECISION `0x16` (BasePosition ×3, Block via `0x143e41310`), COLLAPSING `0x25` (`ActionKeeperBlockLate` only), HEIGHT `0x32` (widely), STRONGER_FOOT `0x35` (one site, return discarded) | as listed |
| **attributes — reception** | exactly one: `0x19` = `BALL_TOUCH` ("Tight Possession") at `0x14416dc80` | — |
| **playing styles** | out-of-possession categories 9 and 0xb in the marking chain (`0x1442e0510`, role-gated); `ActionMark::vf5` 0xb, `vf6` 0xa/0xc; `ActionPress::vf5` 1; `ActionDelay::vf22` / `ActionBasePosition::vf22` 3; `ActionPassCourseCut::vf13` 5/2/3 + styleQ 0xe. **Zero in the route engine, zero in the run builders** | as listed |
| **skill cards** | **zero sites** in the run closure (`0x1442c0000`, `0x143eadbe0`), zero in the marking chain, zero in the route band. The one card-shaped query found is `0x143eadbe0(player, 0x1e)` in the **anime-layer** save-quality selector | — |
| **RNG** | **zero** in the run builders (528 fns), **zero** in the marking chain (61 fns), **zero** in `ActionOffsideTrap` (133 fns), **zero** in every keeper class except `ActionKeeperBasePosition` (one draw, reached at depth 3: `vf4 0x144223580` → `0x1442246d0`/`0x1442260f0` → `0x144228170`). **But NOT zero in the kick family — corrected 2026-09-19**: a re-disassembly of every `match::player` vtable-method body finds **12 RNG calls, all in `ActionShoot::slot6`** — five Gaussian draws `0x144345eb0` at `0x1441b5369`, `0x1441b53c3`, `0x1441b540f`, `0x1441b547e`, `0x1441b55ec`, and seven `0x144345e00` at `0x1441b5789`, `0x1441b583a`, `0x1441b58bf`, `0x1441b5a88`, `0x1441b5bc2`, `0x1441b5be5`, `0x1441b5c3e`. A shot's execution is **not** deterministic at this layer. Positive control: `0x14401a900` reaches `0x144345d90` at depth 2 | `0x14422886f` (keeper) **plus the twelve `ActionShoot::slot6` draws** |
| **CPU difficulty** | `ActionDelay` rows `0x0d` (gate), `0x0e`, `0x0f` ×2, `0x10` (gate), `0x11`; `ActionPress::vf4` one `GetParam`; **probably** the man-marking gate `0x143e1ca8e`; `ActionWaitTimer::vf4` row 0; `ActionShoot::vf6` | `0x146c06f40` (offline) / `0x146c067b0` (online), stride `0x2c` |
| **team fields** (re-censused 2026-09-19 over every `match::player` vtable-method body) | **`teamAI+0x8f4c+slot*4` — the off-ball action id — is read at 10 sites inside executor bodies**, which the old row omitted entirely: `ActionMark#6 0x1441a46e7` (`cmp …,0x2a`), `ActionSpaceRun#13 0x1441eb90b` (`cmp …,0x1f`), `ActionWaitTimer#4 0x144211278`/`0x14421164b`, `ActionPostPlay#6 0x144214e8c`/`0x144214f48`, `#18 0x144214c51`, `#22 0x144213707` (all `cmp …,0x2a`), `ActionKeeperPuntKick#6 0x14421536e`/`0x144215724`. **Executors branch on their team-mates' assigned actions.** `team+0xb3bd` at **6** sites (not 4): `0x144219f8a`, `0x14421a5f0`, `0x14421aacb` (`ActionKeeperPress#4`), `0x14421c9ba` (`#6`), `0x144223bf4` (`ActionKeeperBasePosition#4`), `0x14422908e` (`#13`). `team+0xb44d`: `0x14418bd93` (`ActionBasePosition#6`), `0x14421556c` (`ActionKeeperPuntKick#6`). **`team+0x275c`** (keeper distribution target): `0x14421553b`, `0x14421780a`, `0x1442184a5`. `teamObj+slot*0x44+0x2b0/0x2b4/0x2bc` (marking mode and target); `teamObj+0xb478+slot` (**four** readers: `0x1441a2060`, `0x1441a29b8`, `0x1441a4738`, `0x143e1c233`); `matchWork+team*20+0x44` (the line the marking ramp measures against — **the same table `0x143d24d60` reads**) | as listed |

Difficulty rows located in the jockey chain, read from **PRISTINE** for this chapter (offline table
`0x146c06f40`; the online table `0x146c067b0` differs on rows `0x0f` and `0x11`):

| row | offline | online | shape |
|---|---|---|---|
| `0x0d` | 0 1 1 1 1 1 1 1 1 1 | same | gate — off at Beginner |
| `0x0e` | 4 3 2 1.5 1 0.5 0 0 0 0 | same | a shrinking distance |
| `0x0f` | 6.5 4 3 1.5 0.5 0.5 0.5 0.5 −0.5 −1 | 6 4 3 1.5 **0 0 0 0** −0.5 −1 | looks exactly like a standoff distance |
| `0x10` | 0 0 1 1 1 1 1 1 1 1 | same | gate — off at the two lowest |
| `0x11` | 3 1.8 2 1.5 1.5 1.5 1 0.7 0.4 0.2 | 3 2.5 1.8 1.8 1.5 1.5 1 0.7 0.4 0.2 | a shrinking distance |

**The column → level mapping is not one column per level**: `GetParam`'s seven-arm jump table at
`0x140000000+0x42e4bd8` reads `+0x04/+0x08/+0x0c/+0x10/+0x14`, then `+0x18` *or* `+0x1c`, then
`+0x20/+0x24/+0x28`, selected by `[rbx+8]`. Verify which column your level uses before editing. [b]

---

## Tunables

Pool-cell sharer counts are from `build/exe_constant_census.json`, **re-read for this chapter**;
"re-aim" means repoint the instruction's `disp32` at a private cell — **never write a shared cell in
place**, whatever its count. The not-safely-tunable rows come first.

| what | site | route | effect | evidence | sharers |
|---|---|---|---|---|---|
| **NOT SAFELY TUNABLE — the two run jump-table bounds** | `cmp eax,0x19` before `0x1441f3b20` and `cmp eax,0x14` before `0x1441f3b88`; likewise `cmp ecx,0x71` in every `0x146c14e80` predicate and `cmp edi,0x2b` in `GetParam` (`0x1442e4900`) | — | these immediates are **table bounds**, not behaviour. Raising one indexes off the end of a fixed table; lowering one silently routes ids to the default handler. Add handlers in a cave with a new table, never by widening a bound | b | — |
| **NOT SAFELY TUNABLE — the ball-trajectory length `0x148080f50` = 250** | loop bounds in `ActionKeeperCatching::slot6` `0x14421d550..` and `ActionKeeperPKSaving::slot6` `0x14422cce0..` | — | **it is not a constant at all** (reason corrected 2026-09-19): the census shows **340 referrers = 337 reads and 3 WRITES** (`0x1443071f0 mov [rip+…],eax`, `0x144307405`, `0x144307433`), and the cell is absent from the census's constant map. A file-image edit is simply **overwritten at run time**; if it ever stuck, it would change 337 unrelated read sites. Not tunable | b, census + PRISTINE | 337 readers / 3 writers |
| **NOT SAFELY TUNABLE — the per-slot X-suppression byte** `teamObj + 0xb478 + slot` | `0x143e1c233` → `0x143e1c26a xorps xmm2,xmm2`; also read in `ActionMark::vf20` at `0x1441a2060` | — | when set, the marker tracks in Z only and never steps up — the **only** X-only switch in the marking chain. Powerful, but the writer is unknown and it has at least **four independent readers** (`0x1441a2060` Mark::vf20, `0x1441a29b8` Mark::vf22, `0x1441a4738` Mark::vf6, `0x143e1c233` in the LERP; count corrected 2026-09-19 — which strengthens the verdict), so writing it blind is unsafe | a | runtime |
| **role-aware run geometry — ONE real site, the rest absent for what was tested** | `0x144268754` / `0x144268764` (read), `0x14426876f cmp eax,1` (the branch), cells `0x145b1d940` = −5.0 and `0x145ace398` = −6.0 | exe constant — **re-aim only** (both cells are shared; census before touching) | Sub-mode id 3 (ChanceSpaceRun **kind 1**) reads `teamAI+0x42b8+(slot%11)*4`, subtracts 3, and gives role codes **3–4** a −5.0 offset against every other role's −6.0, fed to the offside-line function `0x143d24e70` — a **1.0 m** difference in where that run ends. Everywhere else that was tested, geometry is role-blind (2,820 emulated comparisons over 15 of 25 handler entries and 14 of 30 slot-20 bodies, byte-identical targets); the seven second-level handlers were never emulated, and id 19's helper reaches a role read at depth 3 (`0x143d33643`). So **"role-blind" is an empirical result over the tested set, not a structural guarantee** — do not quote it as one | b for the counter-example (re-derived from PRISTINE 2026-09-19); a for the tested set | both cells shared |
| **the marking ramp window** — the single biggest cause of the standoff | `0x143e1c1e1 addss xmm0,[0x145a8dd7c]` (ramp start, 10.0) and `0x143e1c1e9 addss xmm2,[0x145a8aa44]` (ramp end, 20.0), both relative to `attackDir·[matchWork+team*20+0x44]` | exe code — **re-aim only** | pushing both up keeps man-marking alive with the ball further upfield. Emulated: ball at `thr+5` → 0.300 m off the man; at `thr+10` → 6.083 m off | a | 1,832 / 1,099 |
| **out-of-possession style category 9** on a defender: +50 to **both** marking weights | `0x143e1c166 mov edx,9; call 0x1442e0510` → `0x143e1c16f/77 addss …,[0x145ae7580]=50.0` + `minss` vs 100 | **player data** (the app already writes the out-of-possession mask) | 0.300 m off the man → **0.000 m**. Role-gated: only fires when the slot's role legalises the category. **THE SAFEST LEVER IN THIS SUBSYSTEM** | a | 503 (cell not edited) |
| **out-of-possession style category 0xb**: zeroes both weights | `0x143e1c151` | player data | the marker reverts to his zonal slot. Use deliberately, or avoid on anyone you want marking | a | — |
| **the offside break distance** — how far past the line a run target is pinned | cell `0x145a8dd7c` = 10.0 as the 6th argument of `0x143d222e0` at 14 sites; the run ones are **`0x144200062`** (kind 6, stored at `0x144200087`, call `0x144200092`), **`0x1441fad19`** (id 11, call `0x1441fad49`) and **`0x1441feb0d`** (ids 8/21, stored at `0x1441feb34`, call `0x1441feb45`). **`0x1441feaea` was removed from this row 2026-09-19**: its 10.0 goes to `xmm2` of `0x144347c20` at `0x1441feb03` — a steering radius, not the pin distance | exe code — **re-aim only** | moves the target one-for-one in metres (10 → `out.x` = line + 10 exactly). ~3–4 m makes runners hold the shoulder of the last defender | a | **1,832** |
| **how straight a run is** — the weight `w` | the 0.3 (`0x145b28a88`) is loaded at **four** sites, one per branch of the piecewise weight: **`0x143d22734`** (d ≤ 7 m arm), **`0x143d2274e`** (the **d >= 18 m** arm — and see below), **`0x143d22764`** (the *actual* 7–18 m
ramp) and **`0x143d22776`** (fall-through). Plus `0x143d2277e` (0.7 `0x145bbe200`), `0x143d22720` (7.0 `0x145c36ac0`), `0x143d2273e` (18.0 `0x1462aa550`), `0x143d2275c` (−11.0 `0x146b0f458`). **`0x143d22730` was removed 2026-09-19 — it is `movaps xmm7,xmm8`, not a load** | exe code — re-aim only | cutting the 0.7 floor makes runs cut inside toward goal; raising 18.0 makes far-side runners converge more often. **A coherent change means re-aiming three of the four 0.3 sites — NOT four.** Corrected 2026-09-19 by re-reading the branch from `0x143d22720`: `comiss xmm1,xmm7 / jb 0x143d2273e` splits d<=7 (arm `0x143d22734`) from d>7; at `0x143d2273e` the 18.0 compare `jb 0x143d22758` splits 7<d<18 (the real ramp: `subss` d−18, `divss` −11.0, then the 0.3 at `0x143d22764`) from **d>=18, which is `0x143d2274b xorps xmm7,xmm7` immediately before `0x143d2274e mulss xmm7,0.3` — a multiply of ZERO. `0x143d2274e` is INERT; re-aiming it changes nothing** (and w = 0.7 + 0 = 0.7 there, which is exactly the emulated "0.7 when the runner is >=18 m from the ball"). Re-aiming one live site moves only that branch | a; branch structure b (re-derived 2026-09-19) | 895 / 461 / 398 / 201 / 16 |
| **`ActionOffsideTrap`'s step-up demand** (10.0 m per frame, relative) | `0x1442068f3 mulss xmm0,[0x145a8dd7c]` | exe code — re-aim only | how hard the line marches. It is a *demand*, not a destination — recomputed from the player's current x every frame | b | 1,832 |
| **`ActionOffsideTrap`'s lateral snap radius** (7.0 m) | `0x144206923 movss xmm1,[0x145c36ac0]` | exe code — re-aim only | how wide a band makes the trapping player abandon the step-up and snap to the stored point at `entity+0x2838`. **Consumer not checked for the overwrite failure mode** | b | 398 |
| **Overlap heading caps** — SB 45°, CB 30° | `0x1441d92c4` (`0x145b1d910`), `0x1441db689`/`0x1441db6a5` (`0x145a8dd80`) | exe code — re-aim only | raising makes the overlap curve inward toward the ball earlier. This is the **only** structural difference between the two overlap classes besides the CB's state-`==5` flip | b | 898 / 1,078 |
| **`ActionPress`'s "step in front" offset** (3.0 m) and its 0.5 m activation band | `0x1441903a2` (`0x1478504e8` = 3.0) feeding `0x1441903e3`; the 0.5 band constant is loaded **once**, at **`0x144190408 movss xmm12,[0x147850248]`**, and compared register-to-register at `0x1441904fa comiss xmm0,xmm12`; slope `0x144190508 mulss xmm3,[0x145b52fb0]` = −2.0 | exe code — **the band needs a cave, not a re-aim** | **CORRECTED 2026-09-19: `0x1441904fa` has no `disp32` to re-aim.** The only re-aimable instruction is the single load at `0x144190408`, and that same `xmm12` is also used at `0x144190423` and `0x144190457` (two `addss`) and at `0x144190503` (`subss`), so re-aiming it moves three other things as well. Widening the band alone means a cave. As shipped the correction is invisible beyond half a metre | b | 1,761 / **7,052** / 205 |
| **the sub-mode-8 abort window** (`fps·1.5`) | `0x144200b99`, cell `0x147850340` = 1.5, under `cmp dword [rbp+0x54],8` | exe code — re-aim only | how long a mode-8 run persists before the executor gives up. Interacts with the selector's 0.2 s commitment | b | 806 |
| **the −80.0 receiver penalty** for a ChanceSpaceRun kind-3 runner — **this edit lands in `match::ai::bp`, not here** (`func_root` of both sites = `0x145644700`, whose three callers are all inside the pass-receiver search `0x145648f30`; see [ball-carrier-brain.md](ball-carrier-brain.md)) | `0x145645bb3` (cell `0x14670f5b0`); paired baseline `0x145645bc3` (`0x146415e44` = −50.0) | exe code — re-aim only | raising it toward −50 removes the executor's bias against passing to a kind-3 space runner | a | 23 / 37 |
| **which run kind takes that penalty** (also in `match::ai::bp`, root `0x145644700`) | inline immediate `0xd` at `0x145646b79` (`cmp dword [rax],0xd`) | exe code (inline, private) | re-points the penalty at a different sub-mode. **It really is the sub-mode**: the accessor `0x1443376e0` is five instructions and returns `rcx+4`, so the compared dword is the per-slot record's **`+4`**, and `0x1442f1ae0` fills that record by copying the selector's own 36-byte ActionParam verbatim (`0x1442f1b4f..0x1442f1b71`, three moves of 0x10+0x10+4 bytes into `teamAI+0x2c4+slot*0x44`) — same layout, so `+0` = action id, `+4` = sub-mode. Experimental — no in-game test | a for the weights, **b for the field identity (decoded 2026-09-19)** | inline |
| **GK positional-error range** (0..5 → max 0.5 m at 40 awareness) | inline immediate `mov edx, 6` at `0x144228863` | exe code (inline, private) | linear on the whole GK standing-error model: 18 → max 1.7 m; 1 → no error. **Verified safe to edit as a plain range**: `0x144345e50(rcx = LCG state from [ctx+0x1a88], edx = bound)` takes only two arguments and derives **no stream index** from the bound — unlike the carrier chapter's plan-roll immediates, which do | a | inline |
| **GK positional-error refresh period** (`2·T` ticks) | `add eax,eax` at `0x144228800` (bytes `03 c0`, followed immediately by `3b d8 cmp ebx,eax`) | exe code (instruction-local) — **but only in one direction** | longer holds keep a mis-positioned keeper mis-positioned; shorter averages the error away. **Two-byte budget (noted 2026-09-19)**: halving fits in place (`shr eax,1` = `d1 e8`, 2 bytes); any *lengthening* factor does not (`lea eax,[rax+rax*2]` is 3 bytes and would eat the `cmp`), so longer periods need a cave | b | — |
| **GK positional-error ability slope** | `0x144228823` (40.0 `0x145d58ec8`), `0x14422883a` (99.0 `0x145c36ac4`), `0x144228852` (59.0 `0x146b2b684`) | exe code — re-aim only | where the error dies out. Today exactly zero at 99 | a | 531 / 90 / 51 |
| **GK engagement radius** — 269.6164 = 16.42 m, stored **squared** | cell `0x146bdfd90`, **sole referrer** `0x144224d1d` | **exe constant — in-place edit is safe here** | raising makes the keeper engage further from goal (sweeper-keeper); lowering pins him to his box. Write R², not R. Its exact consumer condition inside `0x1442246d0` is only partly read | b (direction), census verified `private=True refcount=1` | **1** |
| **GK save-quality floors** — **output** Reach 50 / Reflexes 63 (inline constants 52 and 65, then a ×0.98 pass below 90 at `0x1440329ed..0x1440329fe`), and their slopes | inline `0x34` at `0x1440329d9`, `0x41` at `0x1440329b0`, shift/mul forms `0x1440329ac..0x1440329d6` | exe code — but this function is in the **anime layer (subsystem 3)** | the biggest realism lever for keepers: today a 40-Reflexes keeper saves like **63**. Dropping the floors to ~40 restores the full spread | a | inline |
| **GK "easy catch" remap** — `max(C,R,Rh)` → 73 + (v−40)/3 below 50 km/h | floor `0x49` at `0x144032940`, divisor 3 at `0x144032934/39`, gate cell `0x145ae7580` = 50.0 at `0x1440328cc` | exe code (anime layer) | removes almost all roster spread on routine catches | a | 503 |
| **GK catch / PK reach envelope** — flat 3.5 m | cell `0x146b01d80` = 12.25 at `0x14421d630` and `0x14422cdbb` | exe code — re-aim only | flat, with **no** attribute term; making it depend on Reach needs a cave, not a constant edit | b | 40 (incl. `ActionSelectorChanceSpaceRun`, `ActionSelectorDiagonalRun`) |
| **CPU difficulty row `0x0f`** — 6.5/4/3/1.5/0.5/0.5/0.5/0.5/−0.5/−1 | `0x146c06f40 + 0x0f*0x2c` (offline) and `0x146c067b0 + …` (online); read at `0x144197b60` and `0x144197f90` | exe constant (data page, **both** tables) | lowering the low-difficulty entries shortens the jockeying cushion at the settings the owner plays. Same edit shape as the shipped `offball-counter-early.json` | b | private table rows |
| **CPU difficulty rows `0x0e` / `0x11`** | same table | exe constant | unquantified in metres — their consumers were **not** checked for the "loaded then overwritten" failure mode that killed `forceDashDistDefence`. **Candidates, not proven levers** | c | private rows |
| **CPU difficulty gates `0x0d` / `0x10`** | `0x1441a08ad` (row 0x0d), `0x144197b7e` (row 0x10) via `0x1442e4c00` | exe constant | behaviours in the jockey chain that are simply **off** at the lowest one and two settings. Which behaviours, exactly, is undecoded | b | private rows |
| **`ActionMark::vf20`'s steering cap** — stock 45.0, **PATCHED to 90.0 on the installed image** | `0x1441a2475 minss xmm8,[rip+…]`: PRISTINE → `0x145b1d910` = 45.0; INSTALLED → `0x145b52b90` = 90.0 | exe code (already applied) | affects only the **steering point** in the non-goal-side branch, which the controls show does **not** move the destination. Given that slot 20 is not the destination, **this patch is very likely a placebo for the standoff complaint — A/B it or remove it** | b | 898 / 1,535 |
| **`ActionKeeperThrow` private constants** 16.6667 / 133.3333 | cells `0x146bdb2dc` / `0x146bdb2e0`, sole referrers `0x144216e0a` / `0x144217027` | exe constant (private, verified) | bounds on the throw solution; roles **not** fully read. Listed because they are private and therefore safe to experiment with | c | 1 / 1 |
| **the per-slot marking mode** `teamObj+slot*0x44+0x2b0` (must equal `0x32`) and the marking target `+0x2b4/+0x2bc` | `0x143e1ca93`; consumed at `0x143e1c27f` / `0x143e1c2b2` | **not reachable** | with the mode ≠ 0x32 the marker never leaves his zonal slot. This is the master switch for man-marking, but **no writer was found**, so there is no proven path from the tactic UI or dt270 to it | a (effect), writer unknown | runtime |
| **the per-team line field** `matchWork + team*20 + 0x44` | `0x143e1c1d5` | **not reachable** | sweeping it from −50 to 0 with the ball fixed walks the marker from fully zonal to fully man-marking. The natural guess that dt270's `dfLine` family feeds it is **UNVERIFIED and must not be acted on** | a (effect), writer unknown | runtime |
| **`ActionDiagonalRun`'s +5 m endpoint depth** | **not located** — no +5.0f rip-relative literal in `0x144201d60..0x14420235e` | **not reachable** | the relation is solid (line 30 → 35, line 20 → 25, line 45 → 50) but the constant's site is unidentified, so this is **not actionable** | a (relation only) | — |
| **attribute `0x19` = `BALL_TOUCH` / "Tight Possession"** as it reaches the receiver route (**name corrected 2026-09-19** — it is NOT `CONSCIOUS_DEFENSE`, which is `0x20`) | `0x14416dc80`, consumed by `0x1443460c0` | **player data** | the one per-player lever on receiving/chasing routes; needs no patch. The consumer was **not** decoded, so direction and magnitude are unproven | b | n/a |

### dt270 — the safest levers in this chapter (block added 2026-09-19)

These are **data-file** fields: no exe patch, no shared pool cell, no cave. They reach the executors
at **depth 0** (the `get()` call is inside the executor's own vtable method) and every one below is
`status: read, confidence: high` in `build/dt270_liveness.json`, with the read instruction *being*
the branch or the arithmetic operand — checked for the "loaded then overwritten" failure mode on the
two `0x14416c6c0` gates, which are `cmp byte […],0 / je` directly on the loaded byte.

**`passget` (idx `0x6c`, `DevelopData/common/match/constant/player/passget.json`, 56 fields, 26 read):**

| field | off | kind | reader (one of) | what it gates |
|---|---|---|---|---|
| `naturalPassget.enable` | `0x84` | bool | `0x14416cb8f`, `0x14416cc6b`, `TargetEnemy#8 0x14416816e`, `#9 0x1441680c9` (15 sites) | the master switch for the natural-reception path, read in the priority chain **and** in the interception route |
| `naturalPassget.moveFreedom` | `0x86` | bool | `0x14416cb9e` (sole reader) | how free the receiver is to leave the straight line |
| `naturalPassget.commandMode` | `0x7c` | int | `0x14415f907` | mode selector |
| `naturalPassget.angleMoveInputRange` | `0x74` | float | `0x1442506da` | input cone |
| `naturalPassget.distBackMove` / `.speedBackMove` | `0x80` / `0x88` | float | `0x14425070b` / `MoveStraightTrapRun#11 0x14424d67e` | checking back to the ball |
| `naturalPassget.inputMoveNutralVia` | `0x85` | bool | `0x14425059c` | — |
| `inputMovePosition.enable` | `0x68` | bool | `TrapStop#12 0x144164951`/`0x144164b58` (9 sites) | the human-input route |
| `inputMovePosition.passGraund` / `.passOther` / `.passThrough` | `0x69`/`0x6a`/`0x6b` | bool | `0x144170c32` / `0x144170c26` / `0x144170c2c` | per-pass-type enables |
| `inputMovePosition.playerOffence` / `.playerDefence` | `0x6d` / `0x6c` | bool | `0x144170bf8` / `0x144170bfe` | which side gets it |
| `inputMoveAir.enable` / `.ballBound` / `.ballHeight` / `.inputR2` | `0x50`/`0x48`/`0x4c`/`0x51` | bool/float | `0x144163059`, `0x14416306b`, `0x1441630ba`, `MovePositionAdjust#9 0x1441626a1` | **the air-ball gate that can suppress the interception route** (§ Is a loose ball contested?) |
| `ballFollow.eneble` / `.inputR1` | `0x29` / `0x2a` | bool | `0x1441613a8` / `0x1441613ae` | ball-following route |
| `ballFollowNeutral.ballAngle` / `.ballSpeedMin` / `.ballSpeedMax` | `0x2c`/`0x34`/`0x30` | float | `0x14424efb9` / `0x14424efd6` / `0x14424f00c` | when a neutral ball is followed |
| `openBodyMaxValue` | `0x94` | float | `TrapStop#8 0x1441636b0` | body-open cap on the trap |
| `trapRunReceiveMotionFreeMove` / `…StepMove` | `0xa9` / `0xaa` | bool | `0x14424bb82` / `0x14424bb7b` | which receive motion a running trap uses |
| `thinkPressFilterUntilTargetBallThrough` | `0xa8` | bool | `0x14416eece` | press filtering while the ball is in flight |

**`basePosition` (idx `0xe2`)** reaches `ActionBasePosition::vf4` directly at `0x1441832db` (wrapper
`0x145349560`), as well as the shared outfield runner `0x143da92c0`; its proven-reader fields are the
ones already listed in `match-ai-decoded.md` (`lengthOf`, `adjustZCompact`, `adjustXCompactFW`,
`spaceCoverRate`, `lastLineCloseMaxRate`, `dfLine`, `dfLineCloseRate`, `marginPredictionFrameBase`,
`forceDashDistOffence`). Do **not** reach for the `gks*`/`gkl*` family: 14 of its 20 fields have no
reader at all, and the six that do are the outfield goal-kick shape.

---

## The owner's questions, answered

Each answer is marked **answered**, **partly** or **not**, with a confidence.

**Where does a chosen run actually go?** — **answered**, confidence **high**. A run executor is a
path compiler. The target's X is *assigned* every frame to `rawOpponentLine + attackDir·10.0`; only
the Z is negotiable, and it is a blend between "straight up your channel" (when you are level with
the ball laterally) and "converge on the centre of the line" (when you are ≥18 m from it). Output
to the layer below is (target, gait, movement-class, 0x4ec-byte path). 25 distinct handlers serve
the 26 sub-mode ids — **with emitted geometry in this chapter for 18 of them** (10 of the 16
ChanceSpaceRun kinds); the seven second-level ids have handler and helper addresses but no emulated
endpoint (Open 21).

**Would a midfielder given a striker's run run it properly?** — **partly**, confidence **high for
the kinds tested, none for the rest**. 2,820 emulated comparisons over **15 of the 25 handler
entries and 14 of the 30 distinct slot-20 bodies**: every emitted target and waypoint list
byte-identical across role codes. For those, widening the selectors' eligibility gates is
geometrically safe. **The seven second-level handlers were never emulated, and ChanceSpaceRun
kind 1 (sub-mode id 3) is provably role-sensitive**: its helper `0x144268630` reads the role array
at `teamAI+0x42b8` (`0x144268754`/`0x144268764`) and takes −5.0 for role codes 3–4 versus −6.0
otherwise, so a non-attacking role runs it a metre deeper. Residuals: `0x143d1ca10`'s
`cmp eax,7 ; jl` gate, read but never made to move a target (Open 6), and the seven L2 sub-modes
(Open 21).

**Do runs respect offside?** — **answered**, confidence **high**. They are neither clamped behind
the line nor ignoring it: the target is pinned to a fixed offset *beyond* it (+10 for the AIM
family, +2 / −2 / +8.18 / +5 for others), and there is **no timing term anywhere in the executor**.
Timing is upstream. The full offside line (`0x143d24e70`) is the *mid* waypoint; the *final* plane
uses the raw line.

**Where does the CB standoff radius come from?** — **answered, and the premise is wrong**,
confidence **high**. There is no radius. The marker's destination is slot 4's: the formation-slot
position LERPed toward the team's published marking target, with **both** weights killed by a 10 m
ramp on the ball's position relative to a per-team line field (the same field `0x143d24d60` reads as
the raw defensive line) — when the ramp opens he goes fully zonal in X *and* Z. When the ramp is open the marker marks
tight (0.300 m in the harness); the standoff **is** the ramp. `ActionMark::vf20` — where this
project looked, and patched — does not decide it.

**How does the offside trap move the line?** — **answered**, confidence **high**. Through slot 4,
not slot 20. `vf4` demands `player.x + attackDir·10.0` every frame, relative to the player's
*current* x, so the line marches continuously while the executor is active. It never aims at an
absolute line, and it is ungated at the executor layer — no attribute, style, card, difficulty or
RNG in a 133-function closure.

**Is a loose ball contested between the intended receiver and the nearest defender?** — **answered
for the mechanism, not the race**, confidence **medium-high**. Yes: the receiver route and the
interception route (`PassGetRouteTargetEnemy`) are branches of one first-true priority chain run by
**each player over his own route-work object** (`+0xfa00`), discriminated only by a class field
`routeWork+0xbb0`. **No priority flag, no reservation, no "intended receiver wins" term exists** —
the one thing that *can* suppress the interception branch is the dt270-driven air-ball pre-test
`0x144163020` called at `0x14416cc48`, which is a ball-state test, not a claim on the pass. Who
arrives is decided by geometry and the movement layer, and that race was not emulated.

**What does a goalkeeper's ability actually change?** — **answered**, confidence **high**, and the
answer is uncomfortable. At the executor layer: only GK Awareness, and only through a ≤0.5 m
standing error and a shared reach helper. Catching, Clearances, Reflexes and Reach are consumed one
layer down, where **Reach's output is floored at 50 and Reflexes' at 63** (inline 52/65, then ×0.98
below 90), and an easy catch is remapped into
73..89 across the whole roster. Editing those attributes in `master.db` without flattening the
floors buys much less than it looks like.

**Can pressing intensity be tuned?** — **not**, confidence **medium**. `ActionPress::vf20` targets
the ball outright, the 3 m offset lives inside half a metre, and the only non-geometric inputs are
CPU difficulty and two attributes. dt270's `pressRate` has no live equivalent in `ActionPress`. This
is *not proven absent* — the team object was not swept.

**Where is the executor → animation boundary?** — **answered for the shape, not the consumer**,
confidence **high** for the negative, **none** for the consumer. The boundary is **by value, not by
call**: two closures (592 and 528 functions) reach zero exclusively-anime functions, and the kick
error model has exactly one caller, in the anime layer. What crosses is the path at
`playerWork+0x920`, the destination, the steering points, the gait and the kick-work block. The one
call-shaped handoff is the tackle's `0x143da79a0` (4 sites). **Who consumes the tuple was not
identified, and this chapter does not guess** (Open 7).

**Which action id runs which executor?** — **not**, confidence **none**. Still the subsystem's
biggest hole. It is proven not to be an offset table (three controls); the remaining lead is the
writer of `work+0xd30`.

---

## Corrections

Things this project's standing notes, the briefing for this job, or the earlier version of this
chapter said, that the bytes refute. Every row below was re-derived from PRISTINE for this
write-up **except** the one row that says otherwise.

| belief | reality |
|---|---|
| **"Slot 20 is the per-frame movement-target emitter… every *where does this player actually go* question resolves to a slot-20 body"** (GIVEN #3, and the 2026-09-19 version of *this* file) | **Wrong.** `ActionMove::vf18` (`0x145625830`) calls **slot 4** for the destination (`0x145625868 call [rax+0x20]`), slot 5 to move toward it, slot 6 as a predicate, slots 13 and 12 for two int tags. The slot-2 driver `0x145620a00` separately calls slot 20 at `0x145620f11` (`call [rax+0xa0]`) and slot 21 at `0x145620f28`, writing their points into **different fields** of the move request (`+0x14`, `+0x2c`). **Most** slot-20 bodies end in `0x144347c20(out, &bearing, r)` with `r` a *literal* (10.0 / 3.0 / 100.0) — 17 of 30 distinct bodies directly, 22 within one hop, but **8 bodies / 11 classes never reach it** and some of those write an absolute point (census in § Why `ActionMark::vf20` is not the standoff; the universal phrasing was itself corrected 2026-09-19). Slot 20 emits a **steering direction at a fixed radius** as the rule, not by construction. The classes that really own their geometry are the **21 that override slot 18**. Probe 1 read slot-20 outputs as destinations; its numbers stand as steering points, its interpretation does not. [b, all five indirect-call sites disassembled here] |
| **"`ActionMark::vf20` re-emits the destination at the same radius… radial closing is exactly 0.000 m"** (match-ai-decoded.md) | True but **vacuous**, and misleading about where the standoff lives. `0x144347c20` adds exactly `r` metres by construction and `r` is the literal 10.0. Worse: the `R` of the 8 m/30 m fade is `|self − vf20's THIRD argument|`, not `|self − the proposed destination|` (that is the *fourth*); the fade lives only in the **non**-goal-side branch; in the goal-side branch the proposal is **discarded entirely** (four adversarial proposals → identical output); and the rotation target is the **midpoint** between player and man, not the man. [a + b] |
| **"attribute `0x17` is read at exactly three sites image-wide (`0x143da943a`, `0x143daa779`, `0x144181101`)"** (match-ai-decoded.md; the basis of the memory note `attr-0x17-defending`) | **Wrong — it is at least 11.** The three quoted sites call the inner getter `0x1441172b0` directly with `edx = 0x17`. Eight more pass `0x17` as the third argument to the by-index wrapper `0x1442dd650`, which **tail-jumps to the same getter** at `0x1442dd670` (`mov ebx,r8d … mov edx,ebx … jmp 0x1441172b0`, disassembled here): `0x143d09f11`, `0x143d78347`, `0x143e24dad`, `0x143e2735e`, `0x143e2d8aa`, `0x14417ebe9`, `0x144190142` (in `ActionPress::vf6`'s helper) and `0x14420ac35` (**`ActionPassCourseCut::vf13`**). An independent scan of all 783 callers of the four getters, run for this chapter, finds 11; the defensive probe reported 12 (it additionally counted the record checksum `0x1442c2319`). **Either way, the inference that attribute `0x17`'s only consumers are positioning now has eight unexamined consumers.** [b] |
| **"difficulty rows `0x13`/`0x14`/`0x16` read `{0,1,1,…}` and `0x15` reads `{0,0,0,1,…}` — dumped from both tables in both images"** (match-ai-decoded.md) | **Row `0x14` is not stock.** PRISTINE reads `{0,0,0,1,1,1,1,1,1,1}`; the INSTALLED image reads `{0,1,1,1,…}` — that is **our own** `offball-counter-early.json`, whose description states the stock value correctly. Verified here in both tables (`0x146c06f40` and `0x146c067b0`) in both images: row `0x14` is the **only** one of the five that differs. So the chapter records the patched image while claiming both, and "only the lowest difficulty loses run types" **understates it — stock CounterSpaceRun is off at the three lowest settings.** [b] |
| **"`0x14561fe20` … is in no vtable; executor identity is c-inferred"** (ball-carrier-brain.md § Corrections) | **Wrong, and the claim it 'corrected' was right.** Raw PRISTINE qwords at `vftable+0x10`: `ActionShortPass` (`0x146bbe718`), `ActionShoot` (`0x146bcbe98`), `ActionTackle` (`0x146bbe6d8`), `ActionSliding` (`0x146bca180`), `ActionKeeperCatching` (`0x146bbf8e8`) — all `0x14561fe20`, and `exe_map.json` agrees byte for byte. Across all 34 seven-slot classes it is slot 2 in **33**; the sole exception is `ActionKickFeint`, whose slot 2 is `0x144175ca0` — i.e. precisely the "one call from `0x144175ca0`" the correction cited, an *override that calls the base*. **Upgrade to b-disassembly.** [b, two independent reads] |
| **"No `match::ai::bp` function reads `teamAI+0x8f4c`; the five reads below `0x1456d0000` are all in `0x145644700`, outside the bp module"** (ball-carrier-brain.md § Corrections and § Negatives) | **Wrong on both counts.** A disp32 scan that accepts the displacement *anywhere* in the instruction (the earlier scan appears to have required the instruction to end at disp+4, which misses `cmp dword [reg+idx*4+0x8f4c], imm8`) finds **thirteen** reads at five chained-unwind roots: `0x145644700` (5), `0x145655430` (2), `0x145655dd0` (2), `0x145690f60` (3) and the **pass preamble `0x145699510`** (1, at `0x145699988`, comparing against `0x25` = ONE_TWO_PASS_RUN). Three of those roots lie inside the bp module range as that chapter defines it. **The carrier's pass code does see the runners**, and that chapter needs a repair pass. **[b — reported by the kicks probe; this is the ONE Correction row here that was NOT independently re-run for this write-up. Treat it as a strong lead pending a re-scan.]** |
| **"26 distinct run-path handlers, one per sub-mode id"** (GIVEN #4 and the 2026-09-19 version of this file) | **25 for 26 ids.** Both tables dumped from PRISTINE here: L1 `0x1441f3b20` has 19 distinct entries of which one is the L2 dispatcher `0x1441f37c6` → **18** real; entries 7 and 20 (**sub-mode ids 8 and 21**) are the *same* address `0x1441f32b7`. L2 `0x1441f3b88` has 8 distinct of which one is the shared tail → **7** real. Everything else in GIVEN #4 reproduces exactly. [b] |
| **"the selector's run-target vec3 is at `teamAI+0x8f78+slot*0x34`"** (briefing) | It is at **`teamAI + 0x2a4 + slot*0x44`**, written by `0x1442f1ba0` (`imul rdx,rax,0x44 ; movsd [rdx+rcx+0x2a4],xmm0`) and consumed verbatim by sub-mode id 14 at `0x1441f35ef`. `teamAI+0x8f78+slot*0x34` is a different thing: a 4-entry ring of `{?, startFrame, endFrame}` with the head index at `+0x30` (accessor `0x1442eda20`), used **only** for elapsed-time tests. [b] |
| **"`ActionMark` and `ActionPress` share slot 13, so marking and pressing run identical logic in at least one respect"** (GIVEN #3 and this file) | The shared body is `0x14140d670` = `mov eax,3; ret` — a constant tag, disassembled here, used by at least six classes. **The lead is empty.** What Mark and Press genuinely share is their slot-5 movers `0x145623990` and `0x143e8c5c0`. [b] |
| **"the `PassGetRoute*` family is not a subobject of this parent"** (this file, 2026-09-19) | **Wrong.** It is `ActionPassGet+0x70` = parent `+0xfa00`, built by `0x144140b90` whose single caller image-wide is `0x1441418d4` inside the parent constructor. It was invisible because it is a **nothrow leaf with no unwind funclet**. The map is exhaustive over *funclet-registered* subobjects, not over subobjects — and of the 102 funclets one (`+0x190e8`) belongs to the neighbouring constructor, so this parent registers 101. [b, re-derived here] |
| **slots 1 / 7 / 19 / 21 are "universal"** (this file, from 14 differenced classes) | Over all **55** movement classes only **slot 1** is universal (55/55). Slot 7 is 54/55 (`ActionKeeperSeenOff` overrides), slot 19 is 52/55, slot 21 is 52/55. Likewise "base default" at slots 4, 13 and 20 should read "most common": slot 4's base survives in only 17/55, slot 13's in 24/55, **slot 20's in 23/55 — 32 classes override it, not 11 of 14**. And slot 2 is overridden by four classes (`Delay`, `PassGet`, `Press`, `WaitTimer`), not two. [b, census re-run here] |
| **"`ActionKeeperSavingMove` … does NOT override slot 20"** (the goalkeeper probe's own negative) | **Wrong — a probe error caught by re-reading the vtable for this chapter.** `ActionKeeperSavingMove` (vftable `0x146bbff68`) slot 20 = **`0x14422f660`**, a real body beginning `mov rax,rsp; push r14; sub rsp,0x80 … cmp dword [rax+0x3304],9`. Both `exe_map.json` and the raw PRISTINE qword agree. The class's other slot statements in that probe check out. [b] |
| **"`ActionGoalGet` and `ActionOffsideTrap` emit no movement target of their own"** (probe 1, from the fact that neither overrides slot 20) | The *slot* fact is right; the *conclusion* is an artefact of the slot-20 error. Both have real slot-4 destinations (`0x144212530`, `0x1442067f0`), and `ActionOffsideTrap`'s **is** how the line moves. "No slot-20 override" means "no steering point of its own", not "no target". [b] |
| **`ActionLineBreak` / `ActionPullAway` are "2-instruction stubs"** (match-ai-decoded.md) | Correct in substance, **but this file's evidence for it was wrong about `ActionPullAway` and is fixed below.** [b] |

### Repair pass 2026-09-19 — applied after three adversarial reviews

Every row below was re-checked against the PRISTINE bytes before the text was changed; where a
reviewer was wrong, the row says so and gives the settling evidence.

| belief (as this chapter had it) | reality |
|---|---|
| **"Five sites in this subsystem carry our own patches… everything else quoted here is byte-identical between the two images"** (header) | **Undercount.** Full image diff: **909 differing bytes in 105 contiguous runs**, of which **13 runs sit in seven `match::player` functions** — `ActionMark::vf20`, `::vf6` (×4), **`::vf22`**, **`0x1441a7fa0`** (×3) and **`0x1441a8a70`** (the tackle chain this chapter decodes), **`0x144202c20`**, **`0x144310ea0`** (×2) — plus the quoted-as-stock `0x14401a900` (×5) and `0x144016a70`. Full list in the header. Nothing decoded here was affected (all reads were from PRISTINE), but the assurance was not backed by its own number. [b] |
| **"Every slot-20 body ends in the same polar emitter `0x144347c20` with `r` a literal"** (machine paragraph, § Why `ActionMark::vf20` is not the standoff, and the flagship Corrections row) | **False as a universal, and this file contradicted itself three sections later.** Census over 30 distinct slot-20 bodies: **17 call the emitter (or its wrapper `0x143d1b7e0`) directly, 5 more reach it in one hop, 8 bodies covering 11 classes never reach it at depth 2** — `0x140c83910`, `0x144175890`, `0x1441dec00`, `0x144206a30`, `0x14420e2e0`, `0x144210ce0`, `0x1442135b0`, `0x144241490`. Several write an **absolute point** (`ActionPostPlay::vf20` = the ball; `ActionPassGet::vf20` = one of two stored destinations). Also `ActionBasePosition::vf20` reaches it only via the wrapper, so the old "10.0 ×2 here and again in `0x144189400`" double-counted. **The headline (slot 4, or slot 18 where overridden, supplies the destination) is unaffected** — it rests on `0x145625868 call [rax+0x20]` + the copy-out at `0x14562587f..0x14562588a`, and on the driver's separate writes to `moveRequest+0x14` / `+0x2c`. [b] |
| **"`t = clamp(…); wX = w_base·(1 − t)`" — only the X marking weight is ramped** (§ Where the standoff comes from) | **Both weights are ramped.** X: `0x143e1c219 xorps xmm2,xmm2 → subss xmm2,xmm7 → mulss → divss → addss xmm2,xmm7` → out.x at `0x143e1c298`. Z: `0x143e1c275 subss xmm6,xmm8` (xmm6 zeroed at `0x143e1bfdd`, never rewritten) `→ mulss 0x143e1c28f → divss 0x143e1c293 → addss xmm6,xmm8 0x143e1c29c` → out.z at `0x143e1c2c2`. The emulated table already showed it (ball ≥ −10 → exactly the zonal slot). **When the ramp opens the marker goes fully zonal in both axes**; the per-slot `0xb478` byte is the only X-only switch. [b] |
| **"Executor subobject map — all 102, complete… exhaustive by construction. 99 of 102 are named"** | **101 + 2 = 103 rows, and one funclet in the quoted range is not ours.** The 0x20-stride funclets from `0x1458100f0` number 102; the **first** (`+0x190e8`, `mov rcx,[rdx+0x50]`, dtor `0x144099cd0`, vtable `0x146b95430` = a `common::Registry` pointer for `match::registry::UCameraTargetInfo`) belongs to the *neighbouring* constructor — vtable store `0x14414136b`, root `0x144140fd0..0x1441414f2`, and the executor ctor's extent contains **zero** references to `0x190e8`. Correct range: **`0x145810110..0x145810d97`**. Named count is **98 of 102**. "Exhaustive by construction" withdrawn — after the `+0xfa00` amendment the argument no longer supports it. [b] |
| **"`ActionPullAway`… `vf4 = 0x143d520d0` (the zero-vec stub)"** (§ Corrections, § Negatives) | **Wrong for `ActionPullAway`.** `ActionLineBreak` vf4 **is** `0x143d520d0`; `ActionPullAway`'s vf4 is the **unmodified base `0x1442060f0`** ("my own current position"). The conclusion survives on vf18 = `0x140c83810` and vf20 = `0x140c83910`, which are identical in both. [b, vtable] |
| **"`ActionOffsideTrap` overrides only vf4 and vf5"** (and GIVEN #3's "4, 5, 12, 13, 15") | **It overrides 4, 5, 12 and 13.** Diffed against `match::ai::ActionMove`: differing slots = `[4, 5, 12, 13]`; **slot 15 is the shared base `0x140c83810` in both**, so GIVEN #3 was wrong to list it and this file was wrong to call it one of the class's constants. Slot 20 = the unmodified base `0x1456220d0`, so the conclusion (the line moves through slot 4) stands. [b] |
| **"Run geometry is role-blind" stated without scope** (§ The cross-role answer, § What this enables, § The owner's questions, § Negatives) | **Scoped, and one counter-example found.** The emulation covered 15 of the 25 handler entries and 14 of the 30 distinct slot-20 bodies; the **seven second-level handlers were never emulated**. Sub-mode **id 3 = ChanceSpaceRun kind 1** reads the role array in its own helper `0x144268630` (`0x144268754`, `0x144268764`, index = slot % 11) and selects **−5.0** (`0x145b1d940`) for role codes 3–4 versus **−6.0** (`0x145ace398`), fed to `0x143d24e70`. Id 19's helper reaches a role read at depth 3 (`0x143d33643`). The other five show none. [b] |
| **Method trap found while closing this issue (2026-09-19)** | `tools/exe_funcs_chained.py` exposes both `func_range` and `func_chunks`. **`func_range` returns only the ROOT CHUNK**, and MSVC chunks functions: `func_chunks(0x144268630)` gives five chunks spanning `0x144268630..0x144268b94`, while `func_range` gives `..0x144268709` and therefore **misses the role read at `0x144268754` entirely** — `func_range(0x144268754)` returns that same root-chunk range, which does not even contain the address queried. Any call-graph closure built on `func_range` silently under-reports. A closure of `0x144268630` using `func_range` failed its own positive control; switching to `func_chunks` fixed it. The project's standing rule "use chained-unwind extents, not the touching merge" is necessary but **not sufficient** — it must be `func_chunks`. [b] |
| **The seven L2 handlers "give each kind distinct movement"; the endpoint table's scope unstated** | **Narrowed and filled in.** Each of the seven has its own handler *and* helper — now tabulated with addresses (`0x144268630`, `0x144255a70`, `0x144265bb0`, `0x144265680`, `0x144268190`, `0x144267100`, `0x1442668a0`) — but **none was emulated**, and they share the tail `0x1441f386a`, so "distinct movement" is not established. The endpoint table covers **18 of 26 ids and 10 of 16 kinds**; kinds 0, 1, 4, 12, 13, 15 have no geometry here (Open 21). [b] |
| **"no dt270 field reaches… reached at depth 3 only through `0x143da92c0`"** (§ input census, § What this enables) | **Wrong, and it hid the safest levers in the subsystem.** dt270 is read at **depth 0**: 15 `get(0x6c)` = **`passget`** calls inside ten `PassGetRoute*` vtable methods, and `get(0xe2)` = **`basePosition`** inside `ActionBasePosition::vf4` (`0x1441832db`). The chapter had even disassembled one of these and mislabelled it — the "pad/input module from `0x145348d70(g, 0x6c)`" gating InputMove **is** dt270, and its bytes `+0x84`/`+0x86` are `naturalPassget.enable` / `.moveFreedom`. A 26-field tunables block now exists. The keeper negative is unchanged and re-checked (0 reader sites in `0x144215000..0x144243000`). [b] |
| **"index `0x19` (`DATA_PARAMETER_CONSCIOUS_DEFENSE`)… so Ball Control, Speed and Offensive Awareness do not reach the receiver's route"** | **Index right, name wrong.** `0x19` = `BALL_TOUCH` ("Tight Possession"); `CONSCIOUS_DEFENSE` is `0x20`, which this chapter separately lists for `ActionPress::vf6` — the same attribute had two indices in one chapter. The trailing sentence was also misleading (the one attribute that *does* reach the route is in the ball-control family) and is replaced by "no *second* attribute reaches it". Source: `tools/data/attr_index_map.json`, both `proven`. [b] |
| **attribute `0x17` filed under "defensive"** (§ input census; and the memory note `attr-0x17-defending`) | **`0x17` is `DRIBBLE` ("Dribbling")** under the proven DATA_PARAMETER+7 alignment; `0x15` is Defensive Awareness. The `attr-0x17-defending` note and `match-ai-decoded.md`'s gait threshold `19.0 − 0.1·attr(0x17)` both rest on the **superseded +0x15** alignment (`docs/exe-gameplay-map.md` row 47, "WRONG — off by one, superseded 2026-09-18"). Moved to its own census row with the supersession flagged; the site count (11) is unchanged. [b] |
| **the attribute census had no kick/shot row, and the RNG row read "`0x14422886f` only"** | **Both wrong by omission.** `ActionLongPass::slot6` = `ActionFreeKickLong::slot6` reads `0x35` three times and **uses** the first result (`0x1441b1ed9 test al,al ; je` → `0x1441b1ee5 xorps xmm0,xmm13`); `ActionShoot::slot6` makes two computed-index reads and **twelve** RNG calls (five Gaussian `0x144345eb0`, seven `0x144345e00`). A shot's execution is neither ability-free nor deterministic in `match::player`. [b] |
| **team-fields census omitted `teamAI+0x8f4c`** | **Executors branch on their team-mates' assigned actions at 10 sites** (`ActionMark#6`, `ActionSpaceRun#13`, `ActionWaitTimer#4` ×2, `ActionPostPlay#6` ×2/`#18`/`#22`, `ActionKeeperPuntKick#6` ×2), mostly `cmp …,0x2a` (PostPlay) and `cmp …,0x1f` (CounterSpaceRun). Also `team+0xb3bd` is **6** sites not 4, `team+0x275c` was missing, and `teamObj+0xb478+slot` has **four** readers not two. [b] |
| **"band `0x1441904fa` vs `0x147850248`… re-aim only"** (Tunables, `ActionPress`) | **`0x1441904fa` is `comiss xmm0,xmm12` — register-to-register, nothing to re-aim.** The 0.5 is loaded once at `0x144190408`, and that register is also used at `0x144190423`, `0x144190457` and `0x144190503`, so moving the activation band alone needs a cave. [b] |
| **"`0x143d22730/34` (0.3)"** (Tunables, run straightness) | **`0x143d22730` is `movaps xmm7,xmm8`,** and the 0.3 cell is loaded at **four** sites — `0x143d22734`, `0x143d2274e`, `0x143d22764`, `0x143d22776` — one per branch of the piecewise weight. Re-aiming one changes one branch only. [b] |
| **`0x1441feaea` listed as an offside-break-distance site** | **It is not.** Its 10.0 goes to `xmm2` of `0x144347c20` (`0x1441feb03`), a steering radius. The pin-distance sites are `0x144200062`, `0x1441fad19`, `0x1441feb0d`. [b] |
| **"`0x148080f50` = 250 is a loop bound over a fixed-size buffer"** | **It is a runtime-written global**: 340 referrers = **337 reads and 3 writes** (`0x1443071f0`, `0x144307405`, `0x144307433`), and the census does not classify it as a constant. A file-image edit is overwritten before it matters. Verdict (not tunable) unchanged, reason replaced. [b] |
| **"Nine members of the `gks*`/`gkl*` family have no reader"**, with `gksHalfLineRateX_SB` quoted as one that does | **Fourteen of the twenty have no reader**, and `gksHalfLineRateX_SB` is one of them. The six read are `gklAdjustRateX`, `gklBaseX`, `gklBaseZRate`, `gklSupportRate`, `gklWidthZ`, `gksWidthZ`. Conclusion (it is the outfield goal-kick shape) unchanged. [b] |
| **"floors Reach at 52 and Reflexes at 65"** (three places) | **Those are pre-scale intermediates.** Anything below 90 is multiplied by 0.98 (`0x1440329ed..0x1440329fe`), so the shipped floors are **50 and 63** — which is what the chapter's own table printed. [b] |
| **the slot-2 driver's call list, and how slot 18 is reached** | **Three dispatched slots were missing** (22 at `0x145620f6a`, 8 at `0x145620f99`, 10 at `0x145621035`) plus slots 14 and 16 loaded-then-called at `0x145620a9d`/`0x145620ac3`. And **slot 18 is not called by the driver at all**: slot 17's base `0x1456257e0` calls it (`mov r10,[rax+0x90] … call r10`). Without that link the architecture paragraph has no path to `ActionSpaceRun::vf18`. [b] |
| **`ActionFreeKickLong` "decoded" while `ActionLongPass` is "gate-only"** — for the same function | **The two classes have byte-identical vtables in all seven slots**, so they are one executor with two names; the shared body `0x1441b1500` is 3,654 bytes and was **not** decoded. Both are now `gate-only`. Same treatment for `ActionKeeperBlock` (641 B), `ActionKeeperBlockLate` (991 B, its consumer explicitly untraced) and `ActionTeammateMoving` (754 B), which were marked `decoded` on the strength of a single helper call. [b] |
| **"`add eax,eax` at `0x144228800`" offered as a two-way edit** | Only one way fits: the instruction is 2 bytes (`03 c0`) followed immediately by `cmp ebx,eax`, so halving fits in place and lengthening needs a cave. [b] |
| **the −80/−50 rows carried no subsystem label** | Both sites are inside `0x145644700`, a **`match::ai::bp`** function whose three callers are all in the pass-receiver search `0x145648f30` — i.e. the edit lands in [ball-carrier-brain.md](ball-carrier-brain.md)'s territory, not this chapter's. Labelled. [b] |

**Two reviewer findings that the bytes did NOT support** (text left standing, evidence added):

| challenge | settlement |
|---|---|
| *"`cmp dword [rax],0xd` is field +0 of an unidentified record; calling it the sub-mode is c-inferred"* | **The chapter was right, and it is now b.** The accessor `0x1443376e0` is five instructions and returns **`rcx+4`** (`lea rax,[rcx+4]; ret`), so the compared dword is the record's `+4`. And that record is a verbatim copy of the selector's own 36-byte ActionParam: `0x1442f1ae0` writes it with `movups [rbx+0x2c4],xmm0` / `movups [rbx+0x2d4],xmm1` / `mov [rbx+0x2e4],eax` from the source record (`0x1442f1b4f..0x1442f1b71`). Same layout ⇒ `+0` = action id (the `sub edx,0x1d` tests in `0x1443376e0`/`0x1443377f0` confirm), `+4` = sub-mode. So **sub-mode 13 = ChanceSpaceRun kind 3** is proven, not inferred. |
| *"`GK_Awareness` and `GK_DECISION` are two different names for index `0x16`; one must be wrong"* | **Neither is wrong.** `tools/data/attr_index_map.json` gives `0x16 = {data_parameter: GK_DECISION, ui_name: "GK Awareness"}`, `confidence: proven` — they are the enum name and the UI name of one field. The chapter now states the convention once instead of alternating silently. |

---

## Negatives — proven absent, do not spend a week on these

- **Run geometry is role-blind — for the 15 path builders and 14 slot-20 emitters tested** (15 of
  the 25 handler entries, 14 of the 30 distinct slot-20 bodies). 660 + 2,160 emulated comparisons ×
  11 role codes: not one emitted target or waypoint list differed. **This is NOT a subsystem-wide
  negative**: the seven second-level handlers were never emulated and sub-mode id 3 (kind 1)
  provably branches on the role code in `0x144268630`. [a, scope corrected 2026-09-19]
- **`ActionOverlapSB`'s and `ActionOverlapCB`'s slot-20 closures (30 and 19 functions) contain ZERO
  reads of `teamAI+0x42b8`.** The two classes that exist specifically to distinguish a full-back's
  overlap from a centre-back's do not read the role; they differ by two constants. [b]
- **No randomness in the run executors.** A depth-4 closure of 528 functions from all 18 handler
  entries reaches none of the six LCG entries. Positive control passes. [b]
- **No skill-card test** anywhere in that closure (`0x1442c0000`, `0x143eadbe0`: zero sites). [b]
- **Almost no attribute in the runs**: four getter sites in 528 functions, both inside deep shared
  helpers with a register-supplied index. **Run geometry is not ability-scaled.** [b]
- **No attribute, card, difficulty parameter or RNG reaches the marking-target chain**
  (`0x143e1c9d0 → 0x143e1bfb0 → 0x143e1c6c0 → 0x143e1c310`, 61 functions). Only playing-style
  categories 9 and 0xb enter it. Positive controls pass. [b]
- **`ActionOffsideTrap` is not ability-gated, style-gated, difficulty-gated or random.**
  133-function closure, zero hits on ten probe targets, zero indirect calls. [b]
- **`ActionPress` has no standoff**: `vf20` sets the target to the ball outright, and the only
  competing point has non-zero weight solely inside 0.5 m of predicted separation. [b]
- **Vtable slots 12 and 13 carry no logic** — `mov eax,imm; ret` constants, four of them across the
  family. **Slot 7 is a stub** that zeroes its out vec3 and is overridden by one class in 55. [b]
- **`ActionStopThink` never calls vf4 or vf5.** Its `vf18` writes the player's own position and
  returns; closure = one function. [b]
- **`ActionCover` contains no cover geometry** — `vf4` returns the formation slot verbatim. [b]
- **`ActionLineBreak` and `ActionPullAway` are dead at the executor layer**, from the vtable alone:
  both have `vf18 = 0x140c83810` (`mov al,1`) and `vf20 = 0x140c83910` (`ret 0`). Their vf4s differ
  and the old wording was wrong about one — `ActionLineBreak`'s vf4 is the zero-vec stub
  `0x143d520d0`, `ActionPullAway`'s is the **unmodified base** `0x1442060f0`. [b, corrected
  2026-09-19]
- **Five `PassGetRoute` classes are DEAD in this build**: `Transition` (`+0x560`) and `BallAdjust`
  (`+0xa88`) with its three nested strategies and `BallAdjustBase`. Image-wide disp32 scan: `+0xa88`
  is touched by exactly two instructions in the executor band (the ctor `lea` at `0x144140e7e` and
  the dtor `add` at `0x14416b112`); `+0x560` likewise only `0x144140e71` / `0x14416b11e`. Every
  **live** strategy has 10–20 referring sites. The constructor stores no pointer to either, so no
  indirect route exists. [b]
- **`result+0x21` — the destination of the carrier's receiver-style tag `rec+0x25` — has no
  reader.** All 30 owners of a `0x1443395a0` call scanned for a `+0x21]` memory operand: one hit,
  and it is `lea r8d,[r12+0x21]` (integer arithmetic). This **confirms** the carrier chapter's
  suspicion that the receiver-predicate truth table describes a tag with no consumer. [b]
- **The executor layer does not compute the kick.** `0x14401a900` has exactly one caller and the
  chain to it has exactly one entry, `match::anime::action::Kick::vf8`. [b, re-derived]
- **The `PassGetRoute` engine reads no playing style, no skill card and no second attribute.**
  Zero sites for nine getters over the route band; exactly one attribute read (`0x19`). [b]
- **There is no "intended receiver wins" priority** in the route family. [b]
- **`ActionSwitchPass` resolves no target of its own**; **`ActionFreeKick`'s slot 6 is a bare
  `mov al,1`**; **`ActionKeeperPickupBall` has no body at all**. [b, vtables re-read]
- **No exclusively-anime function is reached by direct call from the run executors** (592-function
  closure). An earlier count of anime hits was a false positive caused by the shared stub
  `0x140c853c0`; that claim is **withdrawn**. [b]
- **No dt270 reader in any goalkeeper executor** (0 of 18,366 reader sites in
  `0x144215000..0x144243000`, re-checked), and the `basePosition.gk*` family is the outfield
  goal-kick shape (14 of its 20 fields have no reader at all). **This negative is keeper-only** —
  elsewhere in the subsystem dt270 reaches executor bodies at depth 0 (`passget`, `basePosition`).
  [b]
- **`match::ai::PlayerGKAuto` is a one-slot class** (destructor only) — there is no CPU-goalkeeper
  brain with behaviour. [b]
- **No per-frame rate guard or frame-parity test** in any keeper executor body. [b]
- **`0x1443252d0` (add-waypoint) does not read its `xmm2` float or its `r9d` flag**; every waypoint
  gets the same hard-coded 16.0f radius. Callers passing ±1.0f there pass a dead argument. [b]
- **NOT PROVEN, stated as such:** that `[matchWork + team*20 + 0x44]` is dt270's `dfLine` or any
  other named field (effect emulated, writer untraced) — **but it is now identified as the same
  per-team defensive-line table `0x143d24d60` reads** (same accessor `0x140efd260`, same base `+0x44`,
  same stride 20; ramp at `0x143e1c1d5` indexed by own side, raw line at `0x143d24d9e` by the
  opponent's), so it is one open question, not two; that `0x1442e48a0(0x1442ee570(teamObj)) >= 2`
  is a CPU-difficulty test (mechanism strong, name inferred); that the base marking weights are
  100/70 in a real match (they are a product of the harness); that no offside constraint exists in
  the route engine (not found ≠ absent); that pressing intensity is unparameterised (team object not
  swept); that sub-modes 4 and 26 are inert (they simply never built a path in the harness's world).
- **KNOWN HOLE in every closure above:** they follow **direct** calls only. The 72 keeper own-bodies
  alone contain 17 indirect call sites (`call [obj+0x20/0x28/0x30/0x60/0x68]`, plus `call r9` at
  `0x14422f1ff`). The RNG and dt270 negatives are as strong as that hole allows, and no stronger.

---

## Class status — 113 rows (109 top-level + 4 nested)

`decoded` = behaviour read (a or b) to the level stated above — **the body's control flow followed to
its outputs**, not merely one call named (three rows were downgraded on that test 2026-09-19); `gate-only` = entry gate, inputs or
one slot known, body not; `listed-only` = the class appears in a census or membership statement and
nothing else was read; `stub` = proven to have no behaviour / never runs; `out-of-scope` = the Demo,
replay and training families, deliberately not decoded. The four nested
`PassGetRouteBallAdjust::*` vtables are listed after the 109.

| class | slots | key address | status | what is known |
|---|---|---|---|---|
| ActionBasePosition | 23 | vf20 `0x144181f80`, vf4 `0x144182cb0` | gate-only | positive control for the attribute closure; shares `0x144189400` (two 10 m emissions) with `ActionMark::vf20`; the shared runner `0x143da92c0` is GIVEN and not re-derived |
| ActionCentering | 7 | s6 `0x1441c3c80` | gate-only | reads published `+0x1c` and `+0x23` ×2; body not read |
| ActionCenteringGet | 23 | vf20 `0x1441c7af0`, vf18 `0x1441d0ae0` | listed-only | vf20 emulated to the ball-position fallback, role-invariant over 11 roles; body not read; vf18 is a raw-offside-line caller |
| ActionClear | 7 | s6 `0x1441ba9c0` | gate-only | reads published `+0` (valid) and `+0x18` (clear power) |
| ActionCornerKick | 7 | s6 `0x1442057f0` | decoded | published `+0x1c`, fallback `0x1442053c0`, `work+0xe88`, `work+0xff9 = 2` |
| ActionCover | 23 | vf4 `0x14420a340`, vf20 `0x14420c4d0` | decoded | vf4 = formation slot verbatim; vf20 = lateral 10 m shuffle toward the ball's side; vf13 reaches `0x143da92c0`; vf5/vf6/vf9/vf22 not read |
| ActionDelay | 23 | vf4 `0x14419aa50`, vf20 `0x144199ba0`, vf17 `0x14419d740` | gate-only | vf4 (cached vec3 from `this+0x8c`) and vf3 (half-second timer, gait 3) read in full; **vf20 (708 instrs) and vf17 (590) NOT decoded**; difficulty rows 0x0d/0x0f×2/0x10/0x11 located |
| ActionDelayMark | 23 | vf4 `0x1441a1150` | gate-only | only vf4 (250 instrs) and vf6 are real; slot 20 is the base; reaches attr 0x15 via `0x143e2faf0`; body not read |
| ActionDemo | 23 | vf20 `0x144233db0` | out-of-scope | Demo family, excluded by GIVEN #2 |
| ActionDemoBase | 14 | vft `0x146be4ee8` | out-of-scope | base of the Demo family; **not** one of the 102 subobjects |
| ActionDemoCursorPlayer | 14 | — | out-of-scope | — |
| ActionDemoFollow | 14 | — | out-of-scope | — |
| ActionDemoNormal | 14 | — | out-of-scope | — |
| ActionDiagonalRun | 23 | vf18 `0x144201d60`, vf20 `0x144200e10` | decoded | vf20 fully read (0x53-byte stub → `0x143d3b5c0`); vf18 emulated at three line depths, endpoint = line + 5.0 m, role-invariant; branches past the first 0x270 bytes not read; the +5.0 constant not located |
| ActionDive | 23 | vf18 `0x14415f380` | listed-only | vf18 is one of the 30 published-record readers and calls style query `0x1442e2a60`; noted only |
| ActionDribble | 23 | vf14/15/18 `0x144179f00/f30/f60` | listed-only | reads the published record's dribble fields `+0x2c..+0x46`; listed to document the record layout |
| ActionFeint | 4 | slot2 `0x1441761c0` | listed-only | reads published `+0x3c/+0x40/+0x44/+0x45` (the special-dribble sub-type block) |
| ActionFreeKick | 7 | s6 `0x140c83810` | decoded | **negative**: pure accept, no work written; slot 4 is the universal resolver |
| ActionFreeKick2ndPass | 7 | s6 `0x1441c4570` | decoded | `work+0x8bc = 0x29`; `work+0xe74` from `matchEnv+0x25b64+idx*4`; `+0xe78 = 1.0f` |
| ActionFreeKickCede | 23 | vf4 `0x1441c46f0` | decoded | confirms the GIVEN: a *movement* class, slot 20 = base, slot 13 = `0x14140d670`, slot 12 = `0x140eeb6d0` |
| ActionFreeKickLong | 7 | s6 `0x1441b1500` | gate-only | **byte-identical vtable to `ActionLongPass` in all 7 slots** — one executor, two names. The shared body is 3,654 B over 7 chunks and was NOT decoded (downgraded from "decoded" 2026-09-19: it was the same undecoded function `ActionLongPass` was rightly marked gate-only for) |
| ActionFreeMove | 23 | vf20 `0x144176c00` | listed-only | census only |
| ActionFreeTrainingBreak | 23 | vf20 `0x1441dec00` | out-of-scope | training family |
| ActionGkCoachingRun | 23 | vf4 `0x14420a340` | listed-only | overrides only slots 4 and 13; 3-function closure, the smallest in the family; no slot 20 |
| ActionGoalCover | 23 | vf4 `0x144207810` (1,066 instrs) | gate-only | six real bodies enumerated; slot 20 = base; closure shows no attribute/style/difficulty/RNG. **The largest undecoded defensive executor** |
| ActionGoalGet | 23 | vf4 `0x144212530`, vf13 `0x144212980` | gate-only | slot 20 is the **base** — but vf4 is a real destination body and was **not** read |
| ActionGoalKickLong | 7 | s6 `0x1441b3280` | gate-only | published `+0x1c` then fallback `0x1442dee30` |
| ActionGoalPlayer | 14 | — | out-of-scope | replay family |
| ActionKeeperAfterCatchMove | 23 | vf20 `0x144230d10`, vf16 `0x144231560` | gate-only | vf16 holds six **private** cells `0x146be3d10..0x146be3d28` (90.1/179.9/180.1/269.9/359.9/360.1) — a bearing quadrant classifier; vf20 not decoded |
| ActionKeeperBasePosition | 23 | vf20 `0x144221e10`, vf4 `0x144223580`, vf18 `0x14422a680` | decoded | vf20 read in full; the 0.5 m ability-scaled standing error a-emulated; the private 16.42 m gate located. **vf18 (7 KB, the largest body in the family) NOT decoded** — shape-read only |
| ActionKeeperBlock | 7 | s6 `0x14421f8c0` | gate-only | calls the shared reach model `0x143e41310` (GK_DECISION + HEIGHT) — the same helper the carrier's pass evaluation uses. **Body is 641 B and its control flow was not followed** (downgraded 2026-09-19: one helper call is not "behaviour read") |
| ActionKeeperBlockLate | 7 | s6 `0x14421fee0` | gate-only | holds the **only** GK save-attribute read in the executor layer: COLLAPSING `0x25` at `0x14421ff95`. Its consumer was **not** traced (Open 12), and the 991 B body was not followed to its outputs (downgraded 2026-09-19) |
| ActionKeeperBodyFeint | 23 | vf4 `0x14422f110` | gate-only | requests action id `0x52`; its only attribute read (DRIBBLE) is inherited via `0x143da92c0`; one indirect call at `0x14422f1ff`; no slot 20 |
| ActionKeeperCatching | 7 | s6 `0x14421d3a0`, s4 `0x14421db50` | decoded | 250-frame trajectory scan, 3.5 m reach gate, 0.1 m tolerance, publishes intercept + requests id `0x46` |
| ActionKeeperCoaching | 23 | vf18 `0x14422e410`, vf16 `0x14422e510` | listed-only | no slot 20 — it never moves the keeper. Whether it organises a wall is **not established** |
| ActionKeeperDeflect | 7 | s6 `0x14421e600`, s4 `0x14421ee90` | gate-only | writes a qword `0x53` to `work+0x8bc`; only HEIGHT in its closure; body not decoded |
| ActionKeeperDropBall | 7 | s6 `0x144218a60` | listed-only | slot 4 is the shared resolver; 13-function closure; body not decoded |
| ActionKeeperMakeshift | 7 | s6 `0x144220f30` | decoded | 12-instruction near-stub; an outfield player in goal gets no keeper behaviour here |
| ActionKeeperMoveFreeKick | 23 | vf20 `0x14422c460`, vf16 `0x14422c740` | gate-only | requests id 3 twice; two jump-table dispatches in vf16; bodies not decoded |
| ActionKeeperMovePenaltyKick | 23 | vf16 `0x14422ca70` | listed-only | overrides **one** slot; no own vf4, no vf20 — the penalty stance is inherited |
| ActionKeeperPKSaving | 7 | s6 `0x14422cc00` | decoded | structurally identical to Catching, sharing helper `0x14421d350`. **The dive choice is NOT here**: no left/right branch, no RNG, no attribute beyond HEIGHT |
| ActionKeeperPickupBall | 7 | s4/s5/s6 = `0x140c853c0`/`0x140c853c0`/`0x140c83810` | stub | proven: no own body at all |
| ActionKeeperPreSaveOperation | 7 | s4 `0x14422e6a0` | decoded | the save-arming timing gate (shot id `0x41`, ≤ `(T·14)/30` ticks remaining); slot 6 is the false stub; reads no attribute |
| ActionKeeperPress | 23 | vf20 `0x144218f10`, vf5 `0x14421b1e0` | decoded (vf20) | vf20 decoded; **vf5 (0xc3b bytes, the come-out decision) NOT decoded** — reads `team+0xb3bd` gating a 225.0 test. Whole closure: no RNG, no attribute but HEIGHT |
| ActionKeeperPunching | 7 | s6 `0x14421e1f0` | listed-only | 23-function closure, no attribute, no RNG; body not decoded |
| ActionKeeperPuntKick | 7 | s6 `0x144215220` | gate-only | `team+0xb44d` gates a designated per-slot target from `matchEnv+0x25b64`; requests id 3; rest not decoded |
| ActionKeeperSavingMove | 23 | vf20 `0x14422f660`, vf4 `0x14422fa10`, vf18 `0x1442303b0` | gate-only | **corrected here: it DOES override slot 20** (`0x14422f660`, verified in `exe_map.json` and raw PRISTINE). Bodies not decoded; only HEIGHT in its closure |
| ActionKeeperScoopOut | 7 | s6 `0x144220c50` | listed-only | 11-function closure, no attribute, no RNG |
| ActionKeeperSeenOff | 23 | slot7 `0x14422f260`, slot12 `0x14422f250` | listed-only | **the only class in 55 that overrides slot 7**; no slot 20; 8-function closure; effectively a marker class |
| ActionKeeperSnapUnder | 7 | s6 `0x144220e30` | listed-only | 4-function closure; the anime twin is where the GK attributes are consumed |
| ActionKeeperTackle | 7 | s6 `0x1442202c0`, s4 `0x144220760` | listed-only | 68-function closure, only HEIGHT, no RNG |
| ActionKeeperThroughThrow | 7 | s6 `0x144218450` | listed-only | largest closure of any keeper class (278 fns) yet no constant-index attribute read and no RNG |
| ActionKeeperThrow | 7 | s6 `0x1442176b0` | gate-only | target entity index from `team+0x275c`, gated by `0x1442e2a60`; two **private** constants `0x146bdb2dc/e0`; solution geometry not decoded |
| ActionKickFeint | 7 | slot2 `0x144175ca0` | listed-only | **the single exception to the universal kick slot 2**; not decoded |
| ActionKickoff | 7 | s5 `0x1441c4880` | decoded | the only 7-slot class with a real slot 5: the kick-off assignment table `matchEnv+0x228d4+0x1840+idx*0xc8` |
| ActionLineBreak | 23 | vf4 `0x143d520d0`, vf18 `0x140c83810`, vf20 `0x140c83910` | stub | **dead at the executor layer, proven from the vtable** |
| ActionLongPass | 7 | s6 `0x1441b1500` | gate-only | reads published `+0x1c` ×6 and `+0x23` ×4 plus player x/z, and attribute `0x35` ×3 (`0x1441b1ed4`, `0x1441b210f`, `0x1441b21a6`; the first result flips a sign at `0x1441b1ee5`); **3,654 B body not decoded** — the largest undecoded kick body in the family (Open 15). Vtable identical to `ActionFreeKickLong` |
| ActionMark | 23 | vf4 `0x1441a2a80`, vf5 `0x1441a2b80`, vf20 `0x1441a1e50` | decoded | vf4's target chain emulated with sweeps; vf20 read and emulated on both images. **vf6 (1,901 instrs) NOT decoded** beyond its style reads, its attr-0x28 helper and the four distance bands **our patch edits**; vf15 not read, and **vf22 (`0x1441a27c0`) is PATCHED on the installed image at `0x1441a29fd`** — the old row called it merely "not read" |
| ActionMoveKeep | 23 | vf4 `0x1441d7a30` | listed-only | shares the base slot-20 emitter; not examined |
| ActionMoveOnPass | 23 | vf20 `0x14420e2e0` | gate-only | read to its first branch: out = the ball's predicted point from `0x144307180(0x1442d6c50(mgr))`; the `this+0x30 == 3` branch not followed |
| ActionOffsideTrap | 23 | vf4 `0x1442067f0`, vf5 `0x144206970` | decoded | both real bodies read in full; every other slot confirmed stub or base; closure proves no attribute/style/card/difficulty/RNG |
| ActionOverlapCB | 23 | vf20 `0x1441db5d0` | decoded | read end to end: self + 10 m along attackAngle rotated toward the ball by ≤30°, base/target swapped when a per-player state == 5; zero role reads in a 19-function closure |
| ActionOverlapSB | 23 | vf20 `0x1441d9220` | decoded | same geometry with a 45° cap, gated on `this+0x524` with a chase-the-ball fallback through `0x143d3b5c0`; zero role reads in 30 functions |
| ActionPassAndGo | 23 | vf20 `0x1441bad20` | gate-only | vf20 read to its first branch (out = ball position); slot 2 is the unmodified base, so it imposes no entry condition of its own. **Slots 4/5 (`0x1441badd0`/`0x1441baef0`) NOT examined — the give-and-go trigger is not established** |
| ActionPassCourseCut | 23 | vf4 `0x14420a9a0`, vf13 `0x14420aa40` | decoded (vf4) | vf4 is a one-line tail-call to the same `0x143e1c9d0` `ActionMark::vf4` uses. **vf13 (623 instrs) covered at input level only**: attr `0x17` at `0x14420ac35` with a +20.0/+5.0 bonus, styles 5/2/3, styleQ 0xe |
| ActionPassGet | 23 | vf2 `0x1441754d0`, vf20 `0x144175890` | decoded | THE receiver executor; vf2 decoded end to end; vf4/vf5/vf6/vf20/vf21 decoded; owns the route work at `+0x70`; **overrides slots 17/19/21**, which the old contract called base/universal |
| ActionPassSupport | 23 | vf20 `0x1441dcf90` | gate-only | emits the ball position, then branches on `record[+5]` into a path not followed; vf18 not examined |
| ActionPassSupportThrowIn | 23 | vf20 `0x1441dec00` | listed-only | noted as a caller of `0x145625720` and `0x143da92c0` |
| ActionPenaltyKick | 7 | s6 `0x144205ad0` | gate-only | reads the published shot-aim fields like `ActionShoot`; body not decoded |
| ActionPenaltyKickAfter | 23 | vf20 `0x14422f320` | listed-only | census only |
| ActionPkMatchNextKeeper | 23 | vf20 `0x144241490` | listed-only | shoot-out housekeeping; no attribute, no RNG; not decoded |
| ActionPostMan | 23 | vf20 `0x144206a30` | gate-only | read to its first branch: both sides' holder indices through the action-class predicate `0x144311e20`; the ball-prediction path not followed |
| ActionPostPlay | 23 | vf20 `0x1442135b0`, vf18 `0x1442149d0` | decoded (vf20) | vf20 is 0x2d bytes and emits the ball position verbatim. **vf18 NOT examined — that is where the post-play geometry must live** |
| ActionPress | 23 | vf20 `0x1441902d0`, vf4 `0x1441907d0` | decoded (vf20) | vf20 fully read. vf4/vf5/vf6 at gate-and-input level only (GetParam via `0x144193150`, attrs 0x15 ×2 and 0x20, style 1). **vf22 (674 instrs) not read** |
| ActionPullAway | 23 | vf18 `0x140c83810`, vf20 `0x140c83910` | stub | dead at the executor layer, proven from the vtable |
| ActionRL | 23 | vft `0x146be8370`, written at `0x1442418ae` | listed-only | **not one of the 102 subobjects** — its vtable is written at exactly one site, outside the executor constructor. Owner unresolved |
| ActionRealData | 23 | ctor `0x144241530` | out-of-scope | replay/real-data family |
| ActionSand | 23 | vf4 `0x144231a50` | listed-only | noted only as a fifth caller of the shared mover `0x143e8c5c0` |
| ActionSeamlessThrowInMove | 23 | vf16 `0x144210b50` | listed-only | census only |
| ActionShoot | 7 | s6 `0x1441b4f60` | gate-only | reads the published record's shot fields `+0/+8/+0xc/+0x10/+0x14/+0x38`; aim logic not decoded |
| ActionShortCornerMove | 23 | vf20 `0x1441dec00` | listed-only | census only |
| ActionShortPass | 7 | s6 `0x1441ad450` | decoded | fully decoded **and** a-emulated on both images; the canonical "read what the brain published" body |
| ActionSliding | 7 | s4 `0x1441abb30` | gate-only | slot 4 gates on `0x143e9e7b0(ctx+0x38, 0xb)` then `0x1441ab9b0` (not decoded); slot 6 is the false stub |
| ActionSpaceRun | 23 | vf18 `0x1441f3010`, vf20 `0x1441ea8c0`, vf13 `0x1441eb5d0` | decoded | vf18 fully mapped: both jump tables, all 25 handler entries, 15 builders emulated, output contract read. **vf20 (0xae9 bytes) only partly decoded** (sub-mode 1 and 4 arms); vf13 and vf6 identified, not decoded |
| ActionStopFront | 23 | vf18 `0x144203ba0` | listed-only | reads published `+0x3a` |
| ActionStopGoal | 23 | vf18 `0x144203c70` | listed-only | reads published `+0x3a` |
| ActionStopThink | 23 | vf18 `0x144203c20` | decoded | a **null executor**, fully established: writes the player's own position, tag 0, id 0x71; closure = one function |
| ActionSwitchPass | 7 | s6 `0x144212a80` | decoded | **negative**: slots 4 and 5 are the false stub, slot 6 is three instructions. No target resolution of its own |
| ActionTackle | 7 | s4 `0x1441a8d90`, s6 `0x1441a8d40` | decoded | both slots read; gate on `0x1442de630 != actor`; tail-jump to `0x1441a8a70`, whose first 0x100 bytes (id 0x31, victim resolution, motion id, the `0x143da79a0` anime handoff) are decoded. **The rest of `0x1441a8a70` and the ball-win/foul arithmetic are NOT decoded.** ⚠ **PATCHED on the installed image**: `0x1441a8a70` at `0x1441a8c2e`, and the sibling `0x1441a7fa0` at `0x1441a82ec`/`0x1441a844c`/`0x1441a84a2` — decode from PRISTINE |
| ActionTeammateMoving | 23 | vf4 `0x1442064a0`, vf20 `0x144206160` | gate-only | vf4 read in full (formation slot + a byte from record `+0x2c0`); vf20 read to its structure (ball position, then a bearing blend gated on the vf13 tag and a `\|self.z − ball.z\|` ramp over 10.0) — **754 B, structure only, downgraded from "decoded" 2026-09-19** |
| ActionThroughPass | 7 | s6 `0x1441aedc0` | gate-only | read to the branch on `+0x1c/+0x22/+0x23`; geometry after `0x1441aee73` not followed. The only class whose slot 3 is not the stub |
| ActionThrowInRotate | 4 | slot2 `0x144204a50` | listed-only | calls the published-record getter; not decoded |
| ActionThrowin | 7 | s4 `0x144204420`, s6 `0x144204260` | gate-only | slot 4 wraps the universal resolver; slot 6 reads published `+0/+0x1c/+0x23`; body not decoded |
| ActionTrainingMoveRoute | 23 | vf4 `0x1442415c0` | out-of-scope | training family |
| ActionWaitTimer | 23 | vf4 `0x144210df0`, slot2 `0x144210b90` | listed-only | **the third caller of `0x143e1c9d0`** (at `0x14421176e`), which is unexplained; one of four classes overriding slot 2; appears in the GetParam census (row 0) |
| ActionWallJump | 4 | slot2 `0x144206010` | listed-only | not examined |
| ActionWallPress | 23 | vf4 `0x144206020` | listed-only | census only |
| PassGetRouteInterface | 15 | slot2 `0x14415fd30` | decoded | the abstract base; the 15-method contract (8 = entry, 9 = exit, 14 = emit) comes from here |
| PassGetRouteRelay | 15 | slot2 `0x144165ea0` | decoded | **last** in the priority chain; writes the out-bundle and delegates to its nested TrapRun when a timer at `+0x40` expires |
| PassGetRouteMoveStraightTrapRun | 15 | slot2 `0x14424b060` | gate-only | nested in Relay at `+0x48`; confirmed live (invoked at `0x144166000`); own slots not decoded |
| PassGetRouteBallFollow | 15 | slot2 `0x1442513e0` | listed-only | nested in Relay at `+0x158`; reset at `0x14416611d` but no vf2 call found — **neither proven live nor proven dead** |
| PassGetRouteMoveStraightTrapStop | 15 | slot2 `0x144163130`, gate `0x144163020` | gate-only | live (invoked at `0x14416cc8e`/`0x14416cc9d`); its state bytes drive `ActionPassGet`'s state classifier; body not decoded |
| PassGetRouteMovePositionAdjust | 15 | slot2 `0x1441625b0` | gate-only | reset from four places and its active byte drives state 1, but its vf2 is **never called** from the chain decoded. `0x1441712b0` is the candidate (Open 9) |
| PassGetRouteBallAvoid | 15 | slot2 `0x144166150` | gate-only | live (`0x14416c9b0`); on success copies its `+0x3e0` vec3 and `+0x3ec` int into `routeWork+0x10/0x18/0x1c`; body not decoded |
| PassGetRouteTargetEnemy | 15 | vf8 `0x144168140` | decoded (vf8) | **the interception route**; entry test decoded in full (needs `match+0x3308 == 1` and, for CPU, `routeWork+0x20 == 2`); per-frame bodies and emit not decoded |
| PassGetRouteInputMove | 15 | slot2 `0x14415fd30` (base) | gate-only | the **human** route: gated on the pad module's `+0x84`/`+0x86`; body not decoded |
| PassGetRouteThrowIn | 15 | slot2 `0x14416a6d0` | gate-only | **first** in the priority chain (`0x14416c96d`); body not decoded |
| PassGetRouteTransition | 16 | slot2 `0x144169230` | stub | **DEAD**: referenced only by ctor `0x144140e71` and dtor `0x14416b11e`. The only 16-method class; its extra slot 15 (`0x144169500`) is unreachable |
| PassGetRouteBallAdjust | 15 | slot2 `0x144169cd0` | stub | **DEAD**: `+0xa88` touched only by `0x144140e7e` (ctor) and `0x14416b112` (dtor) |
| PassGetRouteBallAdjust::BallAdjustBase | 3 | — | stub | reachable only through the dead parent |
| PassGetRouteBallAdjust::BallWait | 3 | — | stub | dead with its parent (`BallAdjust+0x38`) |
| PassGetRouteBallAdjust::BallStepFollow | 3 | — | stub | dead with its parent (`BallAdjust+0x58`) |
| PassGetRouteBallAdjust::BallRunFollow | 3 | — | stub | dead with its parent (`BallAdjust+0x80`) |

Classes outside `match::player` that this chapter leans on: `match::ai::ActionMove` (vftable
`0x14771e708`) — **decoded**, the source of the 23-slot contract; `match::ai::ActionInterface`
(`0x146bb5b50`) — listed-only; `match::ai::bp::BallPlayer` — gate-only here (only its registration
of `&BP+0x5350`); `match::ai::PlayerGKAuto` (`0x146bbe008`) — decoded, a one-slot marker;
`match::anime::action::Kick` / `Tackle` / `Sliding` and the 15
`match::anime::action::goal_keeper::*` classes (`SavingBase 0x146b58840`, `Block 0x146b59148`,
`Catch 0x146b598e0`, `Deflect 0x146b5a018`, `Punch 0x146b5aea0`, `ScoopOut 0x146b5a758`,
`SnapUnder 0x146b5c370`, `AfterCatchBase 0x146b49ad0`, `BodyFeint 0x146b49710`,
`DropBall 0x146b49800`, `PickupBall 0x146b498f0`, `PreSaving 0x146b499e0`, `PuntKick 0x146b49be0`,
`SeeOff 0x146b49cf0`, `Throw 0x146b49de0`) — **out-of-scope, subsystem 3**, named and located only
so the executor → anime pairing is one lookup. The 14 `match::pad::ThinkUnitKeeper*` classes were
enumerated and **not** examined (Open 18).

---

## Open questions

1. **The action-id → executor lookup.** Proven not to be an offset table (three controls). Chase the
   writer of the action manager's current-action pointer (`work+0xd30`, accessor `0x143eee720`).
   Also unresolved: whose object owns the 130-slot pointer table at `+0x15a38`, and whose object
   owns `ActionRL`. Note the obvious naming is already suspect: `ActionKeeperCatching` *requests*
   id `0x46`, which the save-quality selector maps to Reflexes/Reach, not Catching — so either
   `+0x8bc` requests the **follow-on** action rather than the class's own id, or the two id spaces
   differ.
2. **What `0x144261f10` actually does.** 0xa28 bytes, a 27-entry jump table at `0x1442628cc`, and it
   rewrites the sub-mode id every frame. Until its transitions are decoded, nobody knows which
   sub-modes a tagged run really passes through, and "kind 6 never runs" is unproven **in both
   directions**. The cheapest test is a live-patch breakpoint on `0x1441f360b`, not more static work.
3. **`ActionDiagonalRun`'s +5.0 m endpoint offset.** Emulated across three line depths; no +5.0f
   literal in `0x144201d60..0x14420235e`, so the constant lives in a callee or is composed. Until
   found, the diagonal's depth is not tunable.
4. **Who writes `teamObj + slot*0x44 + 0x2b0` (the `0x32` marking mode) and `+0x2b4/+0x2bc` (the
   marking target), and who writes `matchWork + team*20 + 0x44` (the line the ramp measures
   against).** These are the master switch, the aim point and the ramp reference for all man-marking,
   and none has a located writer. **Highest-value single follow-up in this subsystem.** Also: is
   `0x1442e48a0(0x1442ee570(teamObj)) >= 2` really CPU difficulty? If it is, man-marking is **off**
   at Beginner and Amateur, which is a headline in its own right.
5. **The closed form of the base marking weights** — `0x143e1c310` (0x3a7 bytes) and the rest of
   `0x143e1c6c0` (0x30b bytes). The harness produced wX = 100, wZ = 70; what drives those in a real
   match is undecoded, and the 0.300 m residual depends on it.
6. **What `0x143d1ca10`'s `cmp eax,7` attacking-role gate changes.** The only genuine role test found
   on a run-executor path, and no configuration moved a target through it. Either it is inert like
   `forceDashDistDefence`, or the harness does not reach its consequent. Settling it closes the
   cross-role question completely.
7. **Who consumes the executor's output tuple** (target, steering points, gait, movement-class,
   path). Not reached by direct call, so it is a vtable- or manager-driven consumer. **This is the
   real animation seam and it is unmapped.** Related: `0x144268ba0` (0x990 bytes, called from
   `vf18`'s tail with the gait as its fourth argument) is the largest thing between the target being
   chosen and the body moving, and is undecoded.
8. **The foul threshold and the ball-win test.** The 70 % / 40 %-in-the-box test was **not found**;
   0.7f and 0.4f are far too common to triangulate. `0x1441a8a70` past `0x1441a8b5c` does a
   distance/angle computation that *looks* like a reach test, not a probability — but it was not
   followed to a decision. Cheap next step: enumerate the reads of `match::record::ObserverFoul`'s
   writer and work backwards, or trace `0x1442fb510` forward.
9. **Where `PassGetRouteMovePositionAdjust` actually runs**, and whether `PassGetRouteBallFollow` is
   live — the one remaining unclassified class in the family.
10. **The receiver-vs-interceptor race.** The mechanism is decoded; who wins was not emulated.
11. **What `0x1443460c0` does with attribute `0x19` and `routeWork+0xbc4`** — the one ability input
    to the receiver route. Until decoded, "Conscious Defense reaches the route" is a wiring fact
    with no magnitude.
12. **What `ActionKeeperBlockLate` does with the Reflexes value at `0x14421ff95`** — the only place
    an executor could be ability-scaled without touching the anime layer.
13. **The rest of `0x145644700`** (0x41cc bytes, three chunks): the full candidate scoring, what the
    three relaxation modes relax, and whether the −80/−50 block has a situational sibling.
14. **Sub-modes 4 (`0x1441fd500`) and 26 (`0x1441fbc40`)**, which built no path in any of 144
    scenarios. `0x1441fbc40` is the largest builder in the band (0x1576 bytes).
15. **The undecoded bodies named in the class table**, in rough value order:
    `ActionKeeperBasePosition::vf18` (7 KB), `ActionMark::vf6` (1,901 instrs — **it carries four of
    our own distance-band patches, so those patches are currently unverifiable**),
    `ActionGoalCover::vf4` (1,066), `ActionDelay::vf20`/`vf17` (708/590),
    `ActionPassCourseCut::vf13` (623), `ActionKeeperPress::vf5` (0xc3b bytes),
    `ActionPostPlay::vf18`, `ActionPassAndGo`'s slots 4/5, and the base bodies `0x145626100` (804)
    and `0x145623100` (460) which decide what slot 20's `arg3` is in the general case.
16. **Whether the installed `ActionMark::vf20` steering-cap patch (45° → 90° at `0x1441a2475`) does
    anything at all**, given that slot 20 turns out not to set the destination. It should be A/B'd
    or removed.
17. **Names**: the pad/input module behind `0x145348d70(g, 0x6c)` (bytes `+0x68`, `+0x84`, `+0x86`);
    `team+0xb3bd` and `team+0xb44d` (unnamed in this chapter *and* in the carrier chapter); the
    flag index `0x1e` in the save-quality bonus; which playing-style catalog entries map to
    out-of-possession categories 9 and 0xb (the mechanism is proven and emulated; naming them needs
    the map `tools/playstyle_catalog.py` already owns).
18. **The 17 indirect call sites** in the keeper own-bodies, which are the one hole in the RNG and
    dt270 negatives. Resolving the object they dispatch on would close both.
19. **Human control.** The `match::pad::ThinkUnitKeeper*` family (14 classes) was enumerated and not
    examined; none of them writes `match::Player+0x8bc` directly, so their route into the executors
    is unestablished. Any statement about "the player's keeper" rather than the CPU's must go
    through them.
20. **Re-run the `teamAI+0x8f4c` disp32 scan** independently. It is the only Corrections row in this
    chapter standing on a single source, and it contradicts a shipped chapter's Negatives section.
21. **Emulate the seven second-level handlers over roles and worlds** — ids 3, 7, 17, 19, 20, 22, 23
    via helpers `0x144268630`, `0x144255a70`, `0x144265bb0`, `0x144265680`, `0x144268190`,
    `0x144267100`, `0x1442668a0`. They are the gap in *both* headline run answers: no emitted
    geometry (so the endpoint table covers 18 of 26 ids) and no role sweep (so "role-blind" is
    scoped) — and id 3 is already known to branch on the role code (−5.0 / −6.0 at
    `0x14426877f`/`0x144268774`), which makes this the most likely place for the next wrong answer.
22. **Who owns `0x1441a7fa0`, `0x144202c20` and `0x144310ea0`?** Three functions we have patched are
    not attributed in this chapter. `0x1441a7fa0` is in the tackle chain (sole caller `0x1441a6365`,
    holds the `0x143da79a0` handoff site); `0x144202c20` has one caller (`0x144202947`);
    `0x144310ea0` sits in the action-flag band with `match::Human::vf8` among its callers. Until they
    are named, our own patch inventory is not fully explained.
23. **What does `0x1442e1200(_, idx, queryId, otherIdx)` query?** Two of its calls (`queryId` `0xf`
    and `0xe`, at `0x143e1c121` / `0x143e1c13c`) switch marking off entirely, ahead of every style
    test, and the same helper appears with ids `0xd`–`0x10` in `ActionMark::vf5`/`vf6`,
    `ActionOverlapSB::vf4`, `ActionBasePosition::vf22` and `ActionPassCourseCut::vf13`.

---

## Harnesses

Unicorn harnesses for this subsystem follow the patterns in `tools/emu_runscore.py` (synthetic world
+ real code), `tools/emu_bp_harness.py` / `tools/bpx.py` and `tools/emu_anticipation.py`. Standing
tools: `tools/exe_map.py` + `build/exe_map.json` (vtables and method lists),
`tools/exe_census.py` (`cell <va> --all`, never the default 15-row listing) and
`build/exe_constant_census.json`, `tools/exe_funcs_chained.py` (chained-unwind extents — never the
touching-range merge), `build/dt270_liveness.json`, `tools/emu_enum_names.py`
(the `DATA_PARAMETER` registrar) and `tools/data/attr_index_map.json` (attribute index → name,
`proven`). The verification scans written for this chapter (the vtable slot census over all 109
classes, both run jump tables, the attribute-`0x17` site enumeration, the difficulty-table image
diff, the `lea rip`-relative vtable-writer scan and the rel32 caller counts) live in the session
scratchpad and are not shipped. The **2026-09-19 repair pass** added five more, same place: a
full-image byte diff mapped to chained-unwind roots (the patch inventory), a slot-20 emitter census
with a depth-2 direct-call closure per body, a 0x20-stride funclet parse of
`0x1458100f0..0x145810d97` diffed against the subobject table, a re-disassembly of all 900
chained chunks of the 370 `match::player` vtable-method roots (attribute getters, RNG, dt270
`get()`, style queries and team-field displacements), and role-read closures over the seven L2
helpers.
