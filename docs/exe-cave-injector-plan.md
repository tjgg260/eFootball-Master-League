# Code caves for the three "chaos" items — real state, and what's actually left (2026-09-20)

Three of the four chaos items from the realism audit — CPU non-determinism (2a), per-match RNG
reseed (Tier 6), fatigue→kick-error (Tier 5) — are written up there as "cave, designed" or
"designed + verified". That language overstates them: it describes a *hook site and an intent*,
not a patch. No bytes exist for any of the three.

**But the hard part is not the injector.** A first pass at this doc claimed nothing in `tools/`
could place new code. That was wrong, and worth correcting loudly: **`tools/live_inject.py` and
`tools/cave_alloc.py` already exist on `master`** (and on `claude/dt270-full-decode-12718b`) —
just not on `claude/ux-plus-world-merge`, which is why a check against this branch alone found
nothing.

## What already exists

**`tools/live_inject.py`** (route: runtime allocation, no PE surgery). Hooks a site with a 5-byte
`jmp rel32` into a `VirtualAllocEx`'d RWX block placed within ±2 GB of the module, laid out as
`[payload | relocated stolen bytes | jmp back]`. Nothing on disk is touched and PE headers are
untouched, so Denuvo's file-integrity surface is not involved at all. Three safety gates that
`cave_alloc.py` lacks, and per `[[exe-changes-in-scope]]` all three were proven to *fire*, not
merely pass: whole-instruction stealing, refusal to relocate RIP-relative instructions, and a
reference gate scanning `.xcode` for branches landing inside the stolen range. Reach is proven in
both directions rather than assumed. The allocation round trip (alloc near the module → write →
read back → free) passed against the live game on 2026-09-19, with the module at its preferred
base and ASLR slide 0.

Implemented: `plan` (fully offline, against PRISTINE — the reviewable artefact) and `alloc-probe`
(read-only). **`install` / `uninstall` are deliberately not implemented**, by the standing rule
that no exe change is applied without asking. Measured ceiling: keep blocks ≤ 64 KB (4 MB found
no free region within rel32 range). That is still ~3,000× the 21-byte scavenging cave.

**`tools/cave_alloc.py`** (route: on-disk padding scavenging). Capped at 21 bytes per chunk, and
carries **four unfixed defects** listed in `[[exe-changes-in-scope]]` — the "installs wrong without
telling you" class. Prefer `live_inject.py` until those are fixed.

For contrast, the two patchers used for everything shipped so far — `exe_patch.py` (on-disk) and
`live_patch.py` (live process) — are same-length `expect`→`patch` byte swappers only. Every
applied patch to date is a constant, a threshold, a table cell or an existing jump target. That is
why the difficulty-table change shipped today and the three chaos items did not.

## So what is actually left, per item

The blocker is **payload content and unanswered research**, not placement.

**CPU non-determinism (2a)** — hook site known (`0x143df127b`, the per-candidate-action score).
Open: (1) which register/xmm slot holds the score at that exact instruction — needs a fresh
disassembly read, not an assumption; (2) the random source. Reusing the game's own LCG
(`0x144345e13` / `0x144345e08`, fully characterized) is the honest choice over inventing a PRNG,
**but calling it here consumes extra draws from the same stream**, shifting every other consumer
that frame — kick error and CPU shot aim both share it. That interaction has to be checked in an
emulator, not assumed benign. This is the item most likely to have surprising cross-effects.

**Per-match RNG reseed (Tier 6)** — the seed cell is known (`0x144345e08`, constant `0x4513`,
zero-init, no clock reseed, so matches can repeat). What is missing is **the hook: no match-init
call site has been located** where a one-time write could land. `QueryPerformanceCounter` is
already an import (Denuvo uses it for timing checks). Finding that call site is the whole task —
after which this is the smallest, most self-contained of the three: one write, no register juggling
inside a hot per-frame function.

**Fatigue → kick error (Tier 5)** — least ready, and the audit's "design-complete, not byte-ready
— needs the match-long stamina offset located" is itself too generous. **The match-long stamina
value has never been located.** The only isolated per-player meter is the exertion counter
`player+0x30f4`, which `[[kick-ball-physics-emulated]]` explicitly rules out as fatigue: it rises
only during on-ball sprint-dribble, decays in under a second, and already feeds a *different*
accuracy penalty at `0x14401bdb0`. The displayed 0–100 stamina byte lives at
`uiData + slot*0x1c + 0x14c` but its match-side writer was never found. This is not a cave-design
problem yet — it is a find-the-data problem, needing a memory diff across a played match.

## CORRECTION (same day): most of this may not need a cave at all

The three items above were framed from `realism-audit.md`, which **predates the subsystem
chapters**. Read against `docs/ball-carrier-brain.md` the picture is much better, and the audit's
`0x143df127b` is not even the best hook.

**The possession random `r` is the real lever.** `BP+0x14`, a float in `[0,1)`, latched from the
match random bundle `*(*0x1486bd888+0x790)+8`, and read **as a threshold at ~25 enumerated sites**:
Shoot (`0x145685da1`, `0x145685ffc`, `0x145686067`, `0x1456863b6`, `0x1456866d7`, `0x145686799`,
`0x1456867e8`), PassForward (`0x14569d461..471`), PassOneTwo (`0x14569e293`, `0x14569e314`,
`0x14569e39d`, `0x14569e60c`), Dribble (`0x1456a73d8`, `0x1456a753c`), PassSafety (`0x14569edb9`,
`0x14569ee44`), PassLong (`0x14569e129`), PassSpecial (`0x14569fc77..c87` + five more), the arbiter
(`0x145650eb9`), `Safety::canStart`, `0x145658a03`.

`r` is **latched once per possession spell** — refreshed at `0x145653e47..0x145653e62` only when
negative or on the frame `BP+0x8ac == 1`. Every decision in a possession is therefore locked to a
single draw. **Widening that refresh gate re-draws `r` and all ~25 threshold sites see fresh
randomness** — a branch-condition edit, i.e. potentially within `exe_patch.py`'s same-length swap,
no cave and no payload assembly.

**Verify these two first, offline, before building anything:**
1. ~~The bundle's updater was never located.~~ **SUPERSEDED — it is located.**
   `ball-carrier-brain.md`'s open-questions list is out of date; `registry-blackboard.md` decoded
   the record: **`URandomInfo` is 28 bytes, the seed store, updater `0x1453dea17`** — and it flags
   the sharper version of the same worry: **`+0x08`, the carrier's per-possession random, may have
   no writer at all**, which **one live read at `0x145653e5f` settles**. That single read is the
   gating experiment, not a search. If `+0x08` has no writer, widening the refresh gate re-latches
   the same stale value and the cheap edit is inert — in which case the redraw must be injected.
2. The chapter rates `r` **[b], not [a]**: "random in [0,1)" rests on convergent usage at five
   sites, and one probe read `BP+0x14` as a match-clock float. Confirm the semantics.

**And there may be no need to write a randomiser at all.** `realism-todo.md` records
**`ThinkUnitPassRandomTest` — "the carrier brain's fully-built randomiser that is registered but
never listed"**. A complete, shipped randomiser sitting unlisted is a far cheaper route than new
code: listing it is a table edit. Check this before designing any payload.

**RNG reseed** likewise is not a blank search: the bundle's word `+0` seeds 15 other generators and
is taken modulo 1000 at `0x143d70d70` — a located distribution point to work back from.

**Fatigue** is the one item where the pessimism holds: `exe-gameplay-full.md` still rates
`stamina-condition` **partial**, and the per-frame drain is explicitly "not a single isolated named
float constant (computed in engine movement/time accumulation code)". Workaround available though:
`playerData+0x48a0` is a per-player effectiveness scalar (init 1.0 in ctor `0x1443013e0`, multiplied
and clamped into reach/range checks across 257 refs, written only in setup/serialization paths, not
decremented per-frame). Decrementing that over match time is synthetic fatigue that works without
finding Konami's real drain.

## Suggested order

1. **Read `0x145653e5f` live** — settles whether `URandomInfo+0x08` has a writer. One read, no
   write, game running. It decides everything below.
2. **Check `ThinkUnitPassRandomTest`** — if the shipped-but-unlisted randomiser can simply be
   listed, that is the whole feature for a table edit and no payload at all.
3. **Possession random `r`** — widen the refresh gate if (1) allows; otherwise a small
   `live_inject.py` payload that redraws it. Biggest on-ball unpredictability win either way.
4. **RNG reseed** — `URandomInfo` updater `0x1453dea17` is the handle; bundle word `+0` seeds 15
   generators, taken mod 1000 at `0x143d70d70`.
5. **Fatigue** — either memory-diff a match for real stamina, or drive `playerData+0x48a0` and
   accept synthetic fatigue.

**Method note, learned the hard way twice in one session:** this doc's first two versions were both
wrong because they reasoned from `realism-audit.md` instead of the chapters. The audits predate the
decode. **Search `ball-carrier-brain.md`, `registry-blackboard.md`, `match-ai-decoded.md`,
`player-executors.md`, `anime-actions.md`, `goalkeeper.md`, `pad-input.md`, `set-pieces.md`,
`dt270-residue.md` and `realism-todo.md` before concluding anything is unknown.**

Cross-cutting, before any of them ships: `live_inject.py` needs `install`/`uninstall` written (an
explicit owner decision, not a silent addition), and the standing rule from the kick/ball work
applies — *never* reason about behaviour from disassembly alone. Two static reads were confidently
wrong in one session (Y-up vs Z-up; lift vs curl). Emulate each payload with controlled inputs, the
way `tools/emu_spin.py` / `tools/emu_kickerror.py` do, before it goes anywhere near the game.

Meanwhile the working lever for CPU-difficulty realism is the **difficulty table** (see
`docs/exe-gameplay-full.md` § difficulty-rows): same-length data cells, no new code. Two reaction
rows shipped today in `tools/data/patches/difficulty-reaction-variance.json`.
