# The executors — `match::player` (2026-09-19) — **PARTIAL**

What actually happens once a brain has chosen: where a runner goes, how a marker moves, how a kick
is struck, how a receiver runs onto a pass, and everything a goalkeeper does. 109 RTTI classes.

> **STATUS: PARTIAL, AND DELIBERATELY MARKED SO.** The multi-agent job for this subsystem
> (5 probes + chapter + 3 adversarial verifiers + repair + re-verify) has now died **three times**
> on the account spend limit, each time before any probe returned. What follows was decoded by hand
> in the gaps and covers the ARCHITECTURE only: the parent-object layout, the **complete 102-entry
> executor subobject map** (2026-09-19, from the constructor's unwind funclets), the proof that the
> action-id dispatch is not an offset table, and the 23-slot movement contract. It does **not** cover: run-path geometry and the
> cross-role question, where the CB standoff radius originates, offside handling, the kick and
> pass-reception families, or the ~30 goalkeeper executors. Nothing here has been through
> adversarial verification. Resume: `decode-player-executors.js`, run id `wf_d1fc80ce-b63`.
>
> Since first writing: the run-path dispatcher is decoded (below) and it **corrects** a claim in
> [match-ai-decoded.md](match-ai-decoded.md) about kinds looking alike.

Evidence levels: **a-emulated** / **b-disassembly** / **c-inferred**. Addresses are VAs at base
`0x140000000` (no ASLR), decoded from `eFootball.exe.PRISTINE`.
Companion chapters: [match-ai-decoded.md](match-ai-decoded.md) (who chooses off-ball movement),
[ball-carrier-brain.md](ball-carrier-brain.md) (who chooses on-ball actions).

## The architecture — one parent, every executor a fixed subobject

`0x144141500` is **not** a factory that dispatches on an action id. It is a constructor that builds
**every executor as a fixed subobject of one parent**, inlining the simple classes' vtable writes and
calling out to the complex ones (`Press 0x14418edf0`, `Shoot 0x1441b3520`, `SpaceRun 0x1441405d0`,
`DiagonalRun 0x144200d90`, `OverlapCB 0x1441db540`, `OverlapSB 0x1441d7e40`). [b]

That is the **third** subsystem built to this exact shape — the off-ball `ActionSelectorManager`
holds its 10 selectors at fixed offsets, the carrier brain holds 25 ThinkUnits at `BP+0x54d0` and 16
ImageUnits at `BP+0x4230`, and `match::player` holds its executors the same way. Selecting an
executor is therefore a **lookup of a fixed subobject**, not an allocation. The carrier brain's
equivalent turned out to be a `std::map<int, ThinkUnitBase*>` at `registry+0x14b8`; here there is no
such table — see *The action-id → executor dispatch is NOT a table* below. **Still OPEN, but
narrowed to a stored pointer.**

### Executor subobject map — all 102, complete [b]

Recovered from the constructor's own **MSVC unwind funclets** at `0x1458100c0..0x145810d97`: one
16-byte funclet per subobject, each `mov rcx,[rdx+0x60]; add rcx,<offset>; jmp <dtor>`, which is the
compiler's own list of what the constructor has built so far — so this enumeration is exhaustive by
construction, not by scanning. Names come from the vtable each subobject is given, resolved through
`build/exe_map.json`, bounded by **chained-unwind extents** (`tools/exe_funcs_chained.py`) — an
unbounded window over-runs `0x144140a70` into its neighbour and mis-attributes four classes. **99 of
102 are named.** [b]

The contract a class follows is readable off the constructor call: **`0x14561eee0` is the 23-slot
movement base ctor and `0x14561ee70` is the 7-slot kick base ctor** (both are 6-instruction
vtable-write-and-zero stubs, neither takes an id or registers anything). Classes with their own
ctor still inherit one of the two. Slot counts: **54 classes at 23 slots, 34 at 7, 4 at 14 (the
Demo family), 3 at 4**. [b]

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
is built by an inlined base. The `PassGetRoute*` family is **not** in this list, so it is not a
subobject of this parent; its vtables are written around `0x144140c46..0x144140dd6`, in the function
*after* `0x144140a70`. Finding that function's owner is the entry point for the receiver probe. [b]

Note that the parent also holds the off-ball AI: `+0x28` = `match::ai::PlayerDefence`, `+0xd0a0` =
`match::ai::AvoidPlayer`, `+0xd0e8` = `match::ai::AvoidArea`. The executors and the off-ball brain
are members of the **same** object. [b]

### The action-id → executor dispatch is NOT a table [b, three controls]

Open question 1 is narrowed, not answered. Three independent searches come back empty:

1. **No u32 offset table.** Scanning the whole 352 MB image for any window of 32 dwords containing
   ≥6 of the 102 subobject offsets: **0 windows**. No run of ≥3 consecutive offsets anywhere.
2. **No u16 offset table.** Every offset fits in 16 bits; the same scan over u16 gives **0 windows**.
3. **Nothing computes `parent + executorOffset` outside construction.** Decoding every instruction
   in `.xcode` whose disp32 equals one of the 102 offsets and classifying by zone: all of them fall
   in the constructor (`0x144141500..0x14414268d`), the destructor (`0x1441426xx..0x144142axx`) or
   the 102 unwind funclets, except **four** one-off sites — `0x145430be2` (`+0x13450` LineBreak),
   `0x1454317ca` (`+0x138c8` PullAway), `0x144144365` (`+0x13780` KeeperMakeshift), `0x1441446f3`
   (`+0x144c8` FreeTrainingBreak) — and a handful of `rsp`-relative coincidences in unrelated code.

So the executor for an action id is reached through a **stored pointer**, not a computed offset. The
probe should hunt the writer of the action manager's current-action pointer (`work+0xd30`, with the
"get current action" accessor `0x143eee720` from the contact-lockout work), not a dispatch table.

The constructor also rules out self-registration: it stores each subobject pointer only to `rbp+0x48`
(the unwind frame slot the funclets read back as `[rdx+0x60]`) and passes **no** subobject pointer in
`rdx`/`r8`/`r9` to any call — 0 sites. [b]

**One lead, deliberately not over-claimed.** A leaf initialiser at `0x1441442f5..0x1441446f3` — same
translation unit as the executor constructor — fills a **130-slot pointer table** at
`<base>+0x15a38..+0x15e40` (90 slots written, gaps at 2, 3, 6–14, …) with `lea rax,[rdx+<off>]`
targets in the range `+0x0fd18..+0x159f8`. It has the exact shape the executor lookup should have,
**but it is not it**: of its 83 distinct targets only 2 coincide with an executor subobject
(`+0x13780`, `+0x144c8`) and those two are offset collisions, since none of the other 81 is
constructed by `0x144141500`. Whose object `rdx` is, is **unresolved** [c] — worth one probe
question, and the anime layer is the obvious candidate.


## The 23-slot movement contract [b]

Derived by differencing 14 movement classes (BasePosition, Mark, SpaceRun, DiagonalRun, OverlapCB,
OverlapSB, PostPlay, OffsideTrap, Delay, PassCourseCut, GoalGet, Cover, Press, Dribble).

| slot | status | implementation |
|---|---|---|
| 0 | per-class | 13 of 14 differ |
| **1** | **universal** | `0x1456219f0` |
| 2 | base default | `0x145620a00` (Press, Delay override) |
| 3 | per-class | stub `0x140c83910` for 4 of them |
| 4, 5, 6 | per-class | — |
| **7** | **universal** | `0x143d520d0` |
| 8, 9, 10, 11 | mostly stubs | `0x140c853c0` / `0x140c83810` |
| 12 | base default | `0x144114300` |
| 13 | per-class | Mark and Press **share** `0x14140d670` |
| 14 | stub for 13 of 14 | `0x140c837d0` |
| 15 | per-class | — |
| 16, 17 | base default | `0x145626100` / `0x1456257e0` |
| 18 | per-class | base `0x145625830`; SpaceRun's is the run-path dispatcher `0x1441f3010` |
| **19** | **universal** | `0x145623100` |
| **20** | **per-class — THE TARGET EMITTER** | base `0x1456220d0`; Mark's is `0x1441a1e50` |
| **21** | **universal** | `0x145624620` |
| 22 | per-class | — |

**Slot 20 is the per-frame movement-target emitter**, and the most important slot in the subsystem:
11 of 14 classes override it, and `ActionMark`'s override is `0x1441a1e50` — the function already
proven to re-emit its destination at the *same radius* it was handed (radial closing exactly
0.000 m). Every "where does this player actually go" question resolves to a slot-20 body. [b]

The slot numbering is cross-checked against the known `ActionSpaceRun` addresses: its slot 13 =
`0x1441eb5d0`, slot 18 = `0x1441f3010`, slot 20 = `0x1441ea8c0`, exactly matching the vf13 / vf18 /
vf20 recorded in [match-ai-decoded.md](match-ai-decoded.md). [b]

Two structural leads worth keeping:

* **`ActionOffsideTrap` does not override slot 20.** It overrides only 4, 5, 12, 13 and 15 — so it
  never emits its own movement target and must influence the back line through another slot. That
  is a lead on how the line steps up, and it is **not yet decoded**.
* **`ActionMark` and `ActionPress` share slot 13** (`0x14140d670`), so marking and pressing run
  identical logic in at least one respect. **Not yet decoded.**

## The run-path dispatcher — `ActionSpaceRun` slot 18 (`0x1441f3010`) [b]

Its first instruction reads the sub-mode id at `[action+0x54]` and copies it to `+0x58`. The
dispatch is a **two-level jump table**:

```
mov  ecx,[rdi+0x54]                    ; sub-mode id
lea  eax,[rcx-1] ; cmp eax,0x19 ; ja default
mov  eax,[base + rax*4 + 0x41f3b20]    ; L1: 26 image-relative dwords
jmp  base+eax
```

Seven ids (3, 7, 17, 19, 20, 22, 23) land on `0x1441f37c6`, which is **not a shared handler** — it
is a *second-level dispatcher* re-indexing the same id:

```
lea  eax,[rcx-3] ; cmp eax,0x14 ; ja default
mov  ecx,[base + rax*4 + 0x41f3b88]    ; L2: 21 entries
jmp  base+ecx
```

and all seven resolve to **seven different** handlers (`0x1441f37e0`, `0x1441f37f4`, `0x1441f3808`,
`0x1441f381c`, `0x1441f3830`, `0x1441f3844`, `0x1441f3858`).

> **CORRECTION to [match-ai-decoded.md](match-ai-decoded.md).** That chapter records "ids 3, 7, 17,
> 19, 20, 22, 23 fall through to a shared second-level switch at `0x1441f37c6`" and concludes that
> **kinds 1, 4, 12, 13, 15 "look alike"**. The fall-through is real but the conclusion is wrong:
> the second level gives each of those ids its own handler, so those kinds produce **distinct**
> movement. Likewise "19 distinct handlers" counts only the first level — following both levels
> there are **26 distinct run-path handlers**, one per sub-mode id. [b]

**Kind 6 (sub-mode id 15) has its own dedicated handler** at `0x1441f360b`, which tail-calls the
path builder `0x1441fff70` — the same shape as every tagged kind (e.g. kind 9 / id 16 calls
`0x1441fa820`). So the never-tagged kind 6 is a **fully-wired, genuinely distinct run path**, not a
stub: only the selector's tagging chain withholds it. [b]

**Ten of the 26 sub-mode ids are never tagged by ChanceSpaceRun** (6, 7, 8, 9, 10, 15, 17, 21, 24,
25, 26 minus those the kind map covers), and several have dedicated handlers. `ActionSpaceRun` is
the executor for *several* off-ball action ids (ChanceSpaceRun `0x1e`, CounterSpaceRun `0x1f`,
SecondLineSpaceRun `0x1d`), so the untagged sub-modes are most likely the other selectors' kinds —
**unconfirmed** [c], and worth settling because it changes what "adding a new run" would cost.

## Open — everything the probes were commissioned to answer

1. **The action-id to executor lookup.** The subobjects are now all located and named, and the
   dispatch is proven **not** to be an offset table (three controls, above). What remains is to find
   who writes the action manager's current-action pointer — start at `work+0xd30` and the accessor
   `0x143eee720`. Also unresolved: whose object owns the 130-slot pointer table at `+0x15a38`.
2. **Slot names.** The 23 slots are mapped by *shape* (universal / base-default / per-class) but only
   slot 20 is named by function. The universal four (1, 7, 19, 21) are undecoded.
   `0x14561eee0` and `0x14561ee70` (the two base ctors) zero fields at `+0x08..+0x2c` and `+0x08..+0x0c`
   respectively — the base-class field layout is therefore small and the per-class state starts at `+0x30`.
3. **Run geometry and the cross-role question** — is a midfielder handed a chance-space run given a
   striker's path? This decides whether widening the selectors' eligibility gates is safe.
4. **Where the CB standoff radius originates** — `ActionMark` can only aim; the proposed destination
   it rotates comes from upstream and is unidentified.
5. **Offside handling** in the run executors and in the receiver family.
6. **The kick family, the 15 `PassGetRoute*` receiver classes, and the ~30 `ActionKeeper*` classes** —
   untouched.
