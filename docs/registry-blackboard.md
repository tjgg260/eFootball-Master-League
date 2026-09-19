# The blackboard — `match::registry` (2026-09-19) — **SKELETON**

Where every subsystem's shared state lives. Not a decision machine: 218 RTTI names resolve to
**49 record names** wrapped in `Ref` / `ScopedRead` / `ScopedWrite` / `ScopedWAndC` accessor
templates. This chapter is a **struct catalogue**, and the behaviour job has not run yet.

Two honest caveats on that 49. **Sizes were recovered for 26 of them** — the rest have no `?$Copy`
or `?$Pointer` accessor in `build/exe_map.json`, so no descriptor function and no size. And a few
rows are probably the *same* record split by name-parsing (`UBallPerson` / `UBallPersonInfo`,
`UBallInfoOne`, `UBallAttachOne` — the `*One` suffix looks like an `ArrayRef` element alias, not a
distinct record). The plan's earlier estimate of "~45 records" is consistent with that. Treat 49 as
an upper bound on distinct records, not a count. [b for the names, c for the de-duplication]

> **STATUS: SKELETON, hand-decoded 2026-09-19.** Covers the record inventory, the byte size of the
> 26 records that have one, the access discipline (who may write what), the array dimensions, and the allocator that
> proves the sizes. It does **not** cover field layouts inside any record, the writers, the
> per-match tactics landing map, the live LCG state, or the pad→command channel. Nothing here has
> been through adversarial verification.

Evidence levels: **a-emulated** / **b-disassembly** / **c-inferred**. Addresses are VAs at base
`0x140000000` (no ASLR), decoded from `eFootball.exe.PRISTINE`.
Companion chapters: [match-ai-decoded.md](match-ai-decoded.md), [ball-carrier-brain.md](ball-carrier-brain.md),
[player-executors.md](player-executors.md).

## How a record is registered [b]

Every record type has a **descriptor function** — the second method of its `?$Copy` or `?$Pointer`
accessor vtable — which calls one registrar, `0x145340ca0`, with the record's byte size in `r8d`.
That `r8d` is a genuine size, not a tag: the registrar spills it to `[rsp+0x20]` and uses it twice,
once as the allocation length (`0x1453411fa → 0x143b344d0`, result stored to `record+0x10` with the
old pointer released through the deleter at `record+0x8`) and once as the `memset` length
(`0x1453412f8 → 0x144f8306e`). So the table below is allocation-accurate. [b]

Each record is exactly one of **`Copy`** (readers get a snapshot) or **`Pointer`** (readers touch the
live object) — never both. That distinction is the blackboard's concurrency discipline and is worth
respecting before anyone proposes writing into one. [b]

## The records — 49 names, 26 with proven sizes [b]

| record | bytes | access | array | may write | descriptor |
|---|---|---|---|---|---|
| `UFieldInfo` | `0x15e928` (1435944) | Pointer | — | **read-only** | `0x143c4e070` |
| `UAnalyzeInfo` | `0xed760` (972640) | Pointer | — | **read-only** | `0x143c51750` |
| `UCommandOutput` | `0x13b20` (80672) | Copy | — | Write | `0x143c56d60` |
| `UTrainingWork` | `0xf298` (62104) | Copy | — | WAndC, Write | `0x143c56fe0` |
| `UTeamAIInfo` | `0xbd8c` (48524) | Copy | `HomeAway[2]` | WAndC, Write | `0x143c4ddf0` |
| `UBallInfo` | `0x50f8` (20728) | Copy | — | **read-only** | `0x143c68300` |
| `UOrderInfo` | `0x4090` (16528) | Copy | `HomeAway[2]` | WAndC, Write | `0x143c4dd50` |
| `UPlayData` | `0x3308` (13064) | Copy | — | Write | `0x144287520` |
| `UPlayerInfo` | `0x2a00` (10752) | Copy | `PlayerNo[22]` | **read-only** | `0x143c62700` |
| `UScreen2dInfo` | `0x14fc` (5372) | Copy | — | Write | `0x143c627a0` |
| `UPlayerMove` | `0x670` (1648) | Copy | `PlayerNo[31]` | **read-only** | `0x143c683a0` |
| `UFixDemoInfo` | `0x30c` (780) | Copy | — | WAndC, Write | `0x143c4dc10` |
| `UDemoInfo` | `0x2e4` (740) | Copy | — | Write | `0x143c91ee0` |
| `UCameraSettings` | `0x2e4` (740) | Copy | — | WAndC | `0x143c91da0` |
| `UDemoControl` | `0x2e4` (740) | Copy | — | Write | `0x143c91e40` |
| `UAnimeInfo` | `0x260` (608) | Copy | `PlayerNo[22]` | **read-only** | `0x143c62660` |
| `UPkMatch` | `0x1b0` (432) | Copy | — | WAndC, Write | `0x143c755e0` |
| `UBallExternalForce` | `0x16c` (364) | Pointer | — | Write | `0x1441105f0` |
| `UMatchEnv` | `0x158` (344) | Copy | — | WAndC, Write | `0x143c4dcb0` |
| `UHighlightReserveInfo` | `0x140` (320) | Copy | — | Write | `0x143c66170` |
| `UGoalPostInfo` | `0x11c` (284) | Copy | — | **read-only** | `0x143c56f40` |
| `UCornerFlagInfo` | `0xe0` (224) | Copy | — | **read-only** | `0x143c56ea0` |
| `UConceptArrangeReleaseInfo` | `0xcc` (204) | Copy | — | Write | `0x143c56e00` |
| `URandomInfo` | `0xc0` (192) | Copy | — | Write | `0x143c6a860` |
| `UReplayInfo` | `0xb8` (184) | Copy | — | **read-only** | `0x14410cde0` |
| `UDemoPlayerInfo` | `0x90` (144) | Copy | — | Write | `0x143cfe480` |
| `UMatchInfo` | — | — | — | WAndC, Write | — |
| `URecordInfo` | — | — | — | **read-only** | — |
| `UBallPersonInfo` | — | Pointer | — | **read-only** | — |
| `UBallPerson` | — | — | — | **read-only** | — |
| `USugoroku` | — | — | — | WAndC | — |
| `URagdollInfo` | — | — | — | **read-only** | — |
| `UCursorInfo` | — | — | — | WAndC, Write | — |
| `UVanishingSprayInfo` | — | — | — | **read-only** | — |
| `UCameraInfo` | — | Pointer | — | **read-only** | — |
| `UPadInput` | — | — | — | WAndC, Write | — |
| `UCommandInfo` | — | — | — | Write | — |
| `UESports` | — | — | — | WAndC | — |
| `UPathToGlory` | — | — | — | WAndC, Write | — |
| `UBallInfoOne` | — | — | — | **read-only** | — |
| `UStepupTutorial` | — | — | — | WAndC, Write | — |
| `UGeneralSettings` | — | Copy | — | WAndC | — |
| `USystemSettings` | — | Copy | — | Write | — |
| `UNoOperationLeaveInfo` | — | — | — | Write | — |
| `UBallAttach` | — | Pointer | — | **read-only** | — |
| `UBallAttachOne` | — | — | — | **read-only** | — |
| `UCameraTargetInfo` | — | Pointer | — | Write | — |
| `UModeInfo` | — | — | — | Write | — |
| `URegistryData` | — | — | — | **read-only** | — |

`UPlayerMove` also appears with a second, larger `ArrayRef` dimension of **31** alongside the 22 —
two different array views of the same record. Unexplained. [b]

## `team+...`, `teamAI+...` and `UTeamAIInfo` are ONE object [b]

`UTeamAIInfo` is **0xbd8c = 48,524 bytes, one per team** (`ArrayRef<2, HomeAway>`), allocated and
zeroed by the registrar. Three of this project's chapters have been writing three different base
names for what turns out to be that single record.

**The proof is the copy-assign.** `0x143c43370` (chained extent `0x143c43370..0x143c45487`) is
`UTeamAIInfo`'s copy: it opens with `movups` pairs moving `[rdx] → [rcx]` from offset 0 and walks
**646 distinct offsets, ending at `0xbd88`** — exactly `0xbd8c − 4`, the record's final dword. A
function that walks a structure to precisely `size − 4` is that structure's copy, and this one sits
immediately before the `UTeamAIInfo` accessor methods at `0x143c45550` in the same translation unit.
Its callers are `0x1456ead04`, `0x1456f2090`, `0x145709cad` — all in the carrier band — plus a tail
jump from `0x143c4d7d9`. A second, independent function, `0x1442efda0` in the **off-ball AI** band,
walks the same object to the same `0xbd88`. [b]

So the fields both finished chapters flagged are `UTeamAIInfo` members:

| field | decimal | evidence |
|---|---|---|
| `team+0xb3c4` | 46,020 | forces cross/long-ball plans, disables Safety — 8 read sites, **no disp32 writer** |
| `team+0xb44d` | 46,157 | bypasses the cross roll — written at `0x143d02f07` and `0x1442efeef`, both in the off-ball AI band |
| `team+0xb3bd` | 46,013 | read in the copy at `0x143c44aaa` |
| `team+0xb4c` / `+0xb50` | 2,892 / 2,896 | 14 sites |
| `team+0x204` | 516 | 7 `cmp dword` sites in bp |
| `teamAI+0x8f4c` | 36,684 | the off-ball runner action-id array (off-ball chapter) |

This **upgrades an earlier [c] in this file to [b]** and unifies notation across three chapters:
`team`, `teamAI` and `UTeamAIInfo` may be read as the same base from here on.

### Why `+0xb3c4` has no writer — and what that means [b for the absence, c for the cause]

Twelve sites touch `+0xb3c4` and **every one is a read** (eleven `cmp`, one `mov edx, [r15+0xb3c4]`).
There is no `mov [reg+0xb3c4], …` anywhere in `.xcode`. That is not a dead end, it is the expected
shape: `UTeamAIInfo` is a **`Copy`** record, so a reader receives a whole-record snapshot through
`0x143c43370`. A field populated by the bulk copy needs no field-level writer.

The consequence is precise and it redirects the search. "Who writes `team+0xb3c4`" is the wrong
question; the right one is **what fills the source record the copy reads from** — i.e. the per-match
tactics landing map. That is already commissioned as open item 3 below, and it is now the single
highest-value target in this subsystem, because `+0xb3c4` is the strongest on-ball lever the carrier
chapter found and it is unusable only because nothing has named its source.

## Open — what the behaviour job must still do

1. **Field layouts** inside `UTeamAIInfo`, `UOrderInfo`, `URandomInfo`, `UCommandOutput`, `UMatchEnv`.
2. **Writers.** Which subsystem writes each record, and when in the frame.
3. **The per-match tactics landing map** — where the app's tactical choices arrive.
   `AnalyzeDetailInstruction` / `AnalyzeDetailAICoach` / `AnalyzeDetailOffenceLinkage` may be the
   tactical-instruction channel the carrier chapter concluded did not exist; if so that is a
   **correction to a finished chapter**.
4. **The match random bundle** — `URandomInfo` is only 192 bytes and is `Copy` with `ScopedWrite`.
   The carrier chapter's `BP+0x14` possession random latches from it; its updater was never located.
5. **The pad→command channel** — `VPadInput` (Write, WAndC) → `VCommandInfo` (Write) →
   `UCommandOutput` (80,672 bytes, Copy, Write). This is the trigger-run feature's hook point.
6. Why `UFieldInfo` is 1.4 MB and `UAnalyzeInfo` 973 KB, and whether either is gameplay-relevant.
