# The dt270 residue — closing the constant map (2026-09-20)

The last item on the subsystem plan. `build/dt270_liveness.json` classifies **245 constant objects /
21,977 fields** and reported **5,362 of them "unlocated"**; the plan scheduled a dedicated pass to
resolve them. This chapter is that pass. It does four things: re-measures the catalogue against
PRISTINE, audits the method that produced each of its four verdicts, accounts for every one of the
21,977 fields by **how the game fetches the object it belongs to**, and decodes the handful of
objects the plan had reserved as genuine gameplay.

Produced from three workflow probes (re-measure + category audit, locate-the-gameplay-objects,
bulk-locate-everything-else). **The three probes disagreed on six load-bearing points**, and every
one of those was re-derived from the PRISTINE bytes for this write-up; where a probe and the re-read
disagree, the re-read wins and the probe's error is named (§ Corrections → *Between the probes*).

Evidence levels: **a-emulated** (the game's own bytes executed under Unicorn, or a tool run whose
output is the evidence), **b-disassembly** (followed instruction by instruction), **c-inferred**
(structural reasoning only). Addresses are VAs at base `0x140000000`, no ASLR, decoded from
`eFootball.exe.PRISTINE` (sha1 `d2b84d1c…`, byte-identical to the installed image).

Companion chapters: [set-pieces.md](set-pieces.md) (which owns `positionPK`), [anime-actions.md](anime-actions.md)
(which owns the animation tables the dev rig below was built to generate), [player-executors.md](player-executors.md)
(`passget` / `basePosition` at depth 0). **This chapter corrects all three** — see § Corrections.

> **The headline, stated so it matches its own evidence.** The 5,362 is not a pile of hidden levers
> and never was. **5,265 of those fields (98.2 %) belong to objects that are fetched by a mechanism
> the tool does not model** — a name table, three static key tables, or an index cached in a runtime
> object — and every one of those objects is a tutorial drill, a PathToGlory chapter, a Sugoroku
> board, a stadium dressing set or a touchline camera rig. **123 fields in 11 objects have no fetch
> path at all.** Of the ~115 fields the plan called the genuine gameplay residue, **none is a *new*
> gameplay mechanic**: 47 are a developer animation-sweep harness, 22 are a versioned test fixture,
> 31 are stadium furniture, and the 20 `positionPK` fields are a **live gameplay lever that
> [set-pieces.md](set-pieces.md) already owns** — decoded there, re-verified here, not new. One
> object in the residue, **`ballplayer`**, is gameplay-shaped and genuinely unexplained; it is the
> only thing in this chapter that deserves follow-up work.
>
> **Two holes stay open and are named everywhere they bear on a verdict**: the cached-pointer pass
> has never been run (it can only affect 211 `unread` fields, in `ball`, `throughpass` and
> `basePosition` — the only three objects whose pointer is ever stored), and **5,548 of the 21,977
> fields are *bound but never measured*** — binding an index is not seeding it and re-running.

---

## What this enables

| want | where | route | state |
|---|---|---|---|
| know whether a dt270 field you are about to edit does anything | `build/dt270_liveness.json`, **read with the caveat sheet below** — `read` means a load happens, not that the value matters; `unread` survived an independent audit; `cached` was **never measured**; `unlocated` means the *index* was not a compile-time constant and says nothing about liveness | — | a + b (§ What the four categories actually mean) |
| trust the `unread` verdict | **you can for statically reachable direct-and-followed-call paths, with three named holes.** The audit that backs it is a *within-function* consistency check — 663 candidate misses across 91 objects, 199 fields at 343 sites hand-traced across 10 gameplay objects, **zero genuine misses** — but its universe is only the functions where the tool had already attributed a read of that object, so it cannot cover functions the tool entered and attributed nothing in, functions it never reached, or the 230 unread fields in the 3 located objects with **no recorded reader at all** (`PathToGlory1`, `MobileShooting`, `MobileThroughPass`). Hole 2: the cached-pointer pass was never run, which can only touch 211 unread fields (`ball` 11, `throughpass` 82, `basePosition` 118). Hole 3: 129 fields sit behind 4 unfollowed indirect calls. ~4,302 of 4,431 corrected unread fields sit in objects where nothing escaped | — | b (§ `unread`) |
| find the remaining tunable dt270 data | **there is almost none left.** Everything newly located is tutorial, PathToGlory, Sugoroku, stadium dressing or a camera rig. The one live-and-unexploited surface is the per-stadium `demoarea` bounding box read by `match::anime::action` — and it bounds *animation placement*, not play | dt270 data file | b (§ Tunables) |
| tune penalty standing positions | `positionPK_{2,3,4,5}` — **already decoded in [set-pieces.md](set-pieces.md)** and confirmed here end to end: name table `0x1475d1850` → resolver `0x145349470` → `Loader+0x6ee0` → reader `0x143c685a0` | dt270 data file, no exe patch | b, re-verified here |
| model how the user plays | **`userPlayTendencyTest` is not that model** — it is a versioned fixture that nothing fetches. Its 21 weighted category names are real evidence that such a model was designed; whether one is wired up anywhere is **NOT PROVEN** | — | b (§ userPlayTendencyTest) |
| tune "animation ageing" | **nothing to tune.** `animeAging{Kick,Trap,Dribble,FreeMove}` is a QA sweep rig (`enableOutputCsv`, `retryMax`, Start/Add/Num angle grids, `zz_dummy`) with no fetch site anywhere | — | b (§ animeAging) |
| tune dribble turn tables | `ballplayer` (`TurnData[1440]`, `Feint`) looks exactly like that surface — but it has **no sound fetch site**, and the four fields the catalogue calls `read` come from a site that provably cannot produce its index | **NOT-SAFELY-TUNABLE, unresolved** | b (§ ballplayer) |
| re-run the catalogue yourself | `python tools/dt270_liveness.py build --exe <image> --no-cache-pass` (~70–100 s). The re-run is bit-identical to `build/dt270_liveness.json` in all 21,977 per-field statuses. **Pass the flag**: the cached pass is on by default, reaches 21 GB resident and dies with `MemoryError` before writing the catalogue — after it has already overwritten `tools/data/dt270_struct_offsets.json`. Note `build/` is **gitignored**, so the catalogue is a local artifact, not a committed one — rebuild it before quoting it | — | a |

---

## The map in one paragraph

A dt270 constant object is obtained from exactly one place: `ConstantManager::get` at `0x145348D70`,
or its one-line wrapper `0x145349560`. There are **268 direct call/jmp sites to those two and no
indirect route** — **no 8-aligned 64-bit pointer to either exists anywhere in the image** (the four
byte-coincidences for `0x145348D70` are unaligned bytes inside `lea esi,[rax*2+1]` instruction
streams; the wrapper has none at all), so no vtable and no function-pointer table dispatches to them
[b, § Negatives]. What varies is where the **index** in
`edx` comes from, and that is the whole story of this chapter. **234 of the 268 sites produced an
object binding and 34 are `unknown_idx_sites`.** Of the 234, **227 are a plain `mov edx, imm`**,
**4 are a `lea edx,[reg+K]` the tool also folds** (`0x143f8ad8f`, `0x143fef479`, `0x144078ca1`,
`0x14424bb6f` — this is where it over-reaches, § the `0x143fef479` defect) and 3 have no `edx`
producer within 64 bytes backward. That is what located 105 objects. [a, measured here by decoding
back from each of the 234 sites and taking the last writer of `edx`/`rdx`/`dl`]

Five other shapes exist: a **name table** (`0x1475d1850`, five entries, resolver
`0x145349470`, default `0x70`), three **static (modeId → index) tables** in `.text`
(`0x148081340` tutorial / 17 entries, `0x148081460` PathToGlory / 13, `0x148080860` Sugoroku / 3,
each with a linear-search helper and a fall-through default), an index **cached in a runtime object
member** (`[this+0x520]`, `[this+0x530]`, `[Loader+0x6ee0]`, and `[matchEnv+0x3c]` / `[matchEnv+0x40]`
where `matchEnv = [[0x1486bd888]+0x630]`), a **guarded or loop-derived constant** built with
`lea edx,[reg+K]`, and — the one shape no static method can reach — a **name supplied by game data**
through the generic resolver `0x145348e50`. Follow the first five and 234 of the 245 objects are
accounted for.

---

## The before/after measurement

The plan predicted the 5,362 would shrink on its own, because "every subsystem chapter locates dt270
readers as a side effect". **It did not shrink, and it could not have.**

`tools/dt270_liveness.py build` was re-run against PRISTINE and diffed field-by-field against
`build/dt270_liveness.json` of 2026-09-17:

| metric | 2026-09-17 | 2026-09-20 re-run | Δ |
|---|---|---|---|
| objects / located / unlocated | 245 / 105 / 140 | 245 / 105 / 140 | 0 |
| fields | 21,977 | 21,977 | 0 |
| read / cached / unread / unlocated | 12,008 / 0 / 4,607 / 5,362 | 12,008 / 0 / 4,607 / 5,362 | 0 |
| get sites / unknown-index sites | 268 / 33 | 268 / 33 | 0 |
| pointer escapes / unfollowed | 6,118 / 4 | 6,118 / 4 | 0 |

**0 of 21,977 fields changed status and 0 changed reader count**; the tool's own 25-test acceptance
suite passes 25/25 on the re-run. [a]

The prediction was a category error. `build(args)` takes exactly one input, `Image(args.exe)`; the
only other file it opens is `build/exe_map.json`, and that supplies `labels` which are attached as
`fn_name` and never touch classification (the source says so: *"labels are cosmetic"*). Chapters are
prose. The number moves when the tool changes or the exe changes, and neither happened. [b]

Two differences did show up, and both are about the tool rather than the game. The shipped JSON was
generated at **2026-09-17 22:03** and the tool file was last edited at **2026-09-17 22:17 — fourteen
minutes later**; 2026-09-19 is merely the date that already-edited file was first *committed*. That
14-minute gap is why the shipped file lacks the candidate-reader keys the current tool emits: it
reports `unlocated_with_candidate_reader: 0` where the current tool reports **2,639** (and 429 for
`unread`). And `cached_offsets: []` means the published catalogue was built with the **cached-pointer
pass switched off** — see the `cached` row of the caveat sheet. Note also that **`build/` is
gitignored**: the catalogue is not committed, so a fresh clone has no `dt270_liveness.json` and must
rebuild it. [a; timestamps and `git check-ignore -v build/` re-checked here]

**The shrink is real, but it came from this pass, by hand.** Applying the five index-production
routes above:

| bucket | objects | fields | what it means |
|---|---|---|---|
| **object-level bound** — the index→object binding is proven | **128** | **18,154** | constant index (101 / 16,429), name table (5 / 20), tutorial table (8 / 600), PathToGlory table (11 / 880), Sugoroku table (3 / 225) |
| **family-level bound** — fetch site, reader and struct type are pinned; *which* object a given index selects is not | **106** | **3,700** | `demoarea` 102 / 2,856 via `[matchEnv+0x40]`; `ballPerson` 4 / 844 via `[matchEnv+0x3c]` |
| **unbound** — no fetch path found by any of the six mechanisms | **11** | **123** | § The eleven |
| | **245** | **21,977** | |

So of the 5,362 "unlocated" fields, **5,265 (98.2 %) are now bound** and 97 are not; the other 26
unbound fields are ones the catalogue wrongly called *located* (§ The `0x143fef479` defect). [a, from
the routing script; each route [b] individually. The routing script was a one-off in a session temp
directory and was **not retained** — the bucket totals reproduce from `build/dt270_liveness.json`
plus the named tables, the script itself does not]

**Bound is not measured.** Only route A's **16,429 fields (74.8 %)** were ever put through the tool's
pointer-flow. The other **5,548 fields have never had their liveness computed at all** — binding an
index is not the same as seeding it and re-running. Nothing in this chapter should be read as
"these fields are dead"; for routes B–G the honest status is *unmeasured*.

---

## What the four liveness categories actually mean

This is the section to act on. Each category is a different kind of claim with a different error bar.

### `read` — 12,008 fields (11,998 after correction)

**Means:** on some statically reachable path, an instruction with a memory operand whose base or
index register holds a pointer returned by `get()` touches this field's byte range.

**Does not mean the value matters.** Only **369 of 12,008 (3.07 %)** are read by an instruction that
consumes the value in place — `subss` 226, `cmp` 79, `mulss` 39, `addss` 24, `comiss` 8, `cvtsi2ss`,
`divss`, `idiv` 1 each. The other **96.9 % are reached only by a plain load**, which on its own
proves nothing. [a, recomputed here; the load set counted as "plain" is
`mov/movss/movsd/movzx/movsx/movsxd/movups/movaps/movdqu/movdqa/movq/movd/lea/nop`. An earlier pass
quoted 368/3.1 % from a slightly different load set]

A forward CFG liveness walk over 120 sampled read fields across 17 objects found **120/120 with a use
of the loaded value on some path and 0 structurally dead loads** [a, probe 1's walk, **not re-derived
for this chapter**; scope 120 fields / 17 objects, artifacts not retained] — but that walk is
path-insensitive, and the project's known inert cells are exactly what it cannot see. The calibration
case is `basePosition.forceDashDistDefence`, and **the standing description of it is wrong**
(§ Corrections): the flag `byte[r14+0x28d]` is tested **twice with the same sense**, the first test
picks which of the pair is loaded, and the second lets the *other* path skip the overwrite.

```
0x143da9401  cmp   byte ptr [r14+0x28d], 0
0x143da9412  je    0x143da9420
0x143da9414  movss xmm7, [r12+0x188]     ; forceDashDistOffence   (byte != 0)
0x143da941e  jmp   0x143da942a
0x143da9420  movss xmm7, [r12+0x184]     ; forceDashDistDefence   (byte == 0)
...
0x143da9540  cmp   byte ptr [r14+0x28d], 0
0x143da9551  jne   0x143da95a3           ; the OFFENCE path jumps past the overwrite
0x143da9553  movss xmm7, [rip+0x2516aa5] ; <- kills xmm7 on the DEFENCE path only
0x143da95a3  comiss xmm9, xmm7
```

So **`forceDashDistOffence` (+0x188) is fully live** and **`forceDashDistDefence` (+0x184) is dead on
its own path**. Correlated-branch inertness is real, it is rare, and **it is not machine-detectable
with anything built so far**. [b, re-derived from PRISTINE for this chapter]

**The `confidence: low` flag is almost always a false alarm.** 835 read fields have every reader
flagged width/kind-misfit; **828 of the 835 are `movsd xmm, qword[obj+K]`** — a packed load of the
field *and its neighbour*, i.e. a genuine read of both. `basePosition.dfLine` (+0x13c) is the same
artefact in the other direction: declared `int`, read as `movzx eax, byte [rbx+0x13c]` at
`0x143ddb9a0`, `cvtdq2ps`'d and normalised into a 0..1 rate. **Do not read `confidence: low` as
"probably not a real reader".** [a for the 828, b for `dfLine`]

### `unread` — 4,607 fields (4,431 after correction)

**Means:** the analysis visited the functions that can hold a pointer to this object and found no
instruction touching this field's range.

**The brief's premise about how this verdict is produced is wrong, and it matters.** The warning was
that it "rests on a pattern search". It does not. `dt270_liveness.py` is an abstract interpreter over
the decoded CFG: `step()` emits a read event for **any** instruction with a memory operand whose base
*or index* register holds a tracked pointer, excluding only `lea` and `nop` (`tools/dt270_liveness.py:786-799`,
`mem_ptrs` at 741-761). It decodes; it never matches bytes. The single byte pattern in the file is
`find_k_candidates` (1414-1427), a pre-filter for the cached pass — and that pass was off. [b]

Two independent tests, both built from a fresh full disassembly that shares none of the tool's
assumptions (20,286,920 instructions over all 253,886 merged `.pdata` ranges; 5,480,800 memory
operands indexed by displacement, width, access and base register):

- **Could a displacement search decide this? No.** Of 4,607 unread fields, only **7 (0.15 %)** have
  no read operand anywhere in the image whose byte range covers their offset. Median 324 covering
  sites; p90 7,715. Displacements are shared across the whole program, so **pointer provenance is not
  optional — it is the only thing that can answer the question.** Any future "is offset K read?" scan
  built on displacements alone will produce noise. [a]
- **Is the tool complete *inside the functions where it already found a reader of this object*?**
  That, precisely, is the question the audit answers — and stating it loosely as "the functions it
  visited" overclaims. For every located object, every read at a displacement that is a leaf of that
  object's type, with matching width, that the tool nevertheless called unread: **663 candidate
  misses across 91 objects**. 199 of them, at 343 sites across **10** gameplay objects
  (`throughpass` 97, `basePosition` 80, `cameraInplay` 40, `passget` 29, `rating` 24, `trap` 23,
  `centering` 20, `grounderpass` 17, `ball` 8, `moveMatching` 5), were hand-traced back to their base
  register. **Genuine misses: zero.** 246 sites read off the function's own `this`/argument (a
  different object with a member at the same displacement), 43 off a pointer loaded from memory, 44
  off a register written by non-`mov` arithmetic, 5 off a call's return, 3 global or other. The two
  that looked like hits (`0x14564d69b` / `0x14564d69f` in `centering`) are epilogue register restores
  after `lea r11,[rsp+0x80]` — a false positive of the audit walker, and the tool was right to
  exclude them. `shoot` produced **no candidates at all** and so is not one of the traced objects.
  [b, probe 1's audit, **not re-derived for this chapter**; its scripts (`within.py`, `prov.py`,
  `build_dispindex.py`) and artifacts lived in a session temp directory and were not retained, so
  these counts are *measured once, not re-checkable from the repository*]

  **What that audit does NOT cover, said plainly.** By construction its universe is the set of
  functions in which the tool had already attributed a read of that object. Outside it: every
  function the tool entered and attributed nothing in; every function it never reached (the depth-12
  cut, the 4 unfollowed indirect calls, the >60,000-instruction skips); the cached-pointer route; and
  **the 230 unread fields in the 3 located objects with no recorded reader at all** — `PathToGlory1`
  (80), `MobileShooting` (75), `MobileThroughPass` (75), which have literally zero audit coverage
  [a, re-derived here from the catalogue]. "Zero overturns" is therefore an internal-consistency
  result, **not an error bar on the whole `unread` class**.

  An independent adversarial re-hunt for this review took 8 unread fields
  (`trap` +0x1ed, `basePosition` +0x334 and +0x135, `throughpass` +0xf7/+0xf6/+0x19b/+0xf5,
  `passget` +0xab) and walked the base register of **all 93 of their image-wide read sites** back
  through every `func_chunk` of the enclosing function: **0 of 93 traced to a `get()` pointer**
  (42 entry-argument, 13 stack/`lea`-stack, 12 unrelated struct member, 11 arithmetic, 1 global, rest
  calls) — and all 93 sit *outside* the audit's universe. The `unread` verdict survives a genuinely
  independent second sample. It is still a sample, not a bound. [b]

**Residual risk is bounded and concentrated, in three named places.** (1) Only 2 of 105 located
objects carry `reduced` confidence: `ball` (11 unread fields; 3 unfollowed indirect calls in
`0x144088f90`) and `basePosition` (118 unread fields; 1 at `0x143e63937`) — **129 of 4,607 (2.8 %)**;
the other 4,478 sit in objects where nothing escaped (4,302 of the corrected 4,431, § the
`0x143fef479` defect). (2) The **cached-pointer route is unmeasured**,
and it can only reach an object whose `get()` result is stored into memory. Exactly **three objects in
the whole catalogue have a pointer store**: `ball` (`K=0x8`, `0x144072b3e`), `throughpass` (`K=0x8`,
`0x143dabdb8` / `0x143dabc21`) and `basePosition` (`K=0x38` / `K=0xf0`, `0x143dcc109` /
`0x143ddb2ba`). Their **211 unread fields** (11 + 82 + 118) are the entire exposure; the other 4,396
unread fields are unexposed to that route because nothing ever caches their pointer. (3) The 230
zero-reader fields above. [a, pointer-store census re-derived here from the catalogue]

### `cached` — 0 fields, and **this number is not a finding**

`cached_offsets: []`, `cached_globals: []`, `n_cached_reads_accepted: 0`, `n_cached_groups_rejected: 0`
is only possible if the cached-pointer map was empty — the published catalogue was built with the
pass **off**. `cached: 0` therefore means **not measured**, not "none exist". Running the pass now
reaches **21 GB resident** and dies with `MemoryError` in `do_call` at roughly 2,000 of 3,232
candidate functions; even when it runs, `K=0x8` (36,099 candidate functions) and `K=0x38` (46,813) are
skipped as over the 6,000 limit. **Nobody should cite `cached: 0` as evidence of anything.** [a]

**But the hole it leaves is bounded, and small.** The pass reclassifies `unread` → `cached` only for
fields of an object whose `get()` result was *stored* somewhere
(`tools/dt270_liveness.py:1787-1789`). The catalogue records exactly **5 pointer stores across 3
objects**: `ball` (`K=0x8`), `throughpass` (`K=0x8`) and `basePosition` (`K=0x38`, `K=0xf0`). So the
unmeasured route can touch **211 unread fields and no others** — `ball` 11, `throughpass` 82,
`basePosition` 118 — of which `throughpass`'s 82 carry `unread_confidence: high` and are inside the
corrected 4,302. Worse, two of the three K values (`0x8`, `0x38`) are over the tool's candidate limit
and **cannot be closed by the current tool even on a successful run**, so `ball`'s and
`throughpass`'s unread fields stay unmeasured against this route regardless. The remaining **4,396
unread fields are not exposed to it at all.** [a, pointer-store census re-derived here; b for the
reclassification rule]

### `unlocated` — 5,362 fields

**Means: the index at the `get()` site was not a compile-time constant.** It says nothing whatsoever
about liveness, and the tool says so itself in every affected record ("*Fields are 'unlocated', which
says NOTHING about liveness*"). After this pass, 5,265 of the 5,362 are bound to a fetch route.

### The access shapes the tool cannot see — the caveat sheet

| # | shape | count | consequence |
|---|---|---|---|
| 1 | **fetch by name** — `0x145349470` resolves a name to an index from the 5-entry table at `0x1475d1850`; the tool seeds only on `VA_GET` | 5 objects | this is how `positionPK` was missed; **there is exactly one such table image-wide** (§ Negatives) |
| 2 | **static (modeId → index) table** — `0x148081340` / `0x148081460` / `0x148080860`, each behind a linear-search helper with a fall-through default | 22 objects | fully statically recoverable; the tool just never looks for them |
| 3 | **index cached in a runtime object member** — `[this+0x520]`, `[this+0x530]`, `[Loader+0x6ee0]`, `[matchEnv+0x3c]`, `[matchEnv+0x40]` | 22 of the 268 sites | the dominant mechanism; hides the whole stadium and camera-rig families |
| 4 | **guarded / loop-derived constant** via `lea edx,[reg+K]` where `reg` is constant only on that path | 4 such sites among the 234 that bind (`0x143f8ad8f`, `0x143fef479`, `0x144078ca1`, `0x14424bb6f`), plus 3 more among the 34 unknown-index sites | **this cuts both ways** — the tool under-reaches at some and *over*-reaches at `0x143fef479` |
| 5 | **name supplied by game data** through `0x145348e50` (strips the extension at `.`, walks all 245 registered paths, strips each at `/`, compares basenames) | unbounded | **the hard floor**: every registered basename occurs exactly once in the image (inside its own path), so these names come from data, not code. No static method can close this |
| 6 | **indirect / virtual call receiving the pointer** | 4 certain, 211 possible-frame, 3 into imports | the only cause of `reduced` confidence; enumerating 4 vtables would make `unread` unqualified |
| 7 | depth-12 call limit; functions over 60,000 instructions skipped; a silent 60-visit-per-block path cap; `norm()` collapses >4 pointer atoms and truncates the non-pointer set to 8 | — | soft limits, none observed to bite in the audit |
| 8 | pointer laundered through a sub-64-bit register, through `and`/`or`/`shr`, or through xmm | — | not observed; not excluded |
| 9 | implicit-operand string ops (`rep movsq` has no explicit memory operand) | — | a bulk copy of an object would not register as reads |

**And one trap the tool already avoids, which a replacement must not walk into.** "The offsets this
site reads fit this struct" is *not* evidence. The 13 offsets read at `0x143c685dd` — the `positionPK`
reader, whose identity is certain from its index provenance — are contained in **26 of the 36 decoded
struct types**. The tool's own fingerprint is stricter and correctly returned *no* fit rather than a
wrong one. Containment discriminates only at 8+ distinct offsets **and** with an independent handle
(an RTTI class name, or the index source). [a, measured here]

---

## The triage: what is noise, and why

The 2026-09-20 triage called 120 of the 140 unlocated objects (4,698 fields) "clearly non-gameplay"
and 7 more (525 fields) tutorial drills. **The conclusion holds. The method that produced it —
labelling by `DevelopData/...` folder name — is not safe, and it went wrong once.**

| group | objects | fields | how it is fetched | verdict |
|---|---|---|---|---|
| **stadium dressing** — 101 `demoarea_*` + `studiumPositionData` | 102 | 2,856 | `[matchEnv+0x40]` | presentation geometry — but its **readers are in `match::anime::action`**, see below |
| **touchline camera / mic rig** — `ballPersonData`, `ball_person_st101/102/103` | 4 | 844 | `[matchEnv+0x3c]` | non-gameplay; 69 siblings are constant-fetched from a 103-case stadium switch at `0x1442c70c0` |
| **tutorial drills** — 7 `tutorialConsole/*` + `tutorialNone` | 8 | 600 | key table `0x148081340`, default `0xe3` | tutorial mode only. **Not dead** — read by `match::StepupTutorialBase::vf4` |
| **PathToGlory chapters** | 11 | 880 | key table `0x148081460`, default `0x65` | mode only; read by `match::PathToGloryBase::vf4` via `[this+0x530]` |
| **Sugoroku board** | 3 | 225 | key table `0x148080860`, default `0xdd` | mode only; read by `match::SugorokuBase::vf4` via `[this+0x520]` |

**The one thing the triage got wrong, and it is a method warning, not a lever.** The `demoarea`
family is fetched and read inside `match::anime::action` — `CornerKickLoop`, `GoalEvent::vf2`/`vf4`,
`RecieveBall`, `SeamlessPassReady` — four classes in a gameplay band. What they do with it, verified
here instruction by instruction at `0x143f091d0`:

```
0x143f091d0  mov   rcx, [rbp+0x47c0]
0x143f091d7  call  0x1442d6dc0          ; -> [[0x1486bd888]+0x630]  = matchEnv
0x143f091dc  mov   rbx, rax             ; <- this is what puts matchEnv in rbx
0x143f091df  lea   rcx, [rsp+0xb8]
0x143f091e7  call  0x143b35b70
0x143f091ed  mov   edx, [rbx+0x40]      ; the cached demoarea index
0x143f091f8  call  0x145349560          ; ConstantManager::get wrapper
0x143f09206  movss xmm0,[rax+0x44] / minss xmm0,[rax+0x50]   ; BoardPosition x[1], x[2]
0x143f09210  movss xmm4,[rax+0x74] / maxss xmm4,[rax+0x80]   ; BoardPosition x[5], x[6]
0x143f0921d  movss xmm2,[rax+0x40] / minss xmm2,[rax+0x94]   ; BoardPosition z[0], z[7]
0x143f0922a  movss xmm3,[rax+0x64] / maxss xmm3,[rax+0x70]   ; BoardPosition z[3], z[4]
```

Those eight offsets are eight of the sixteen scalars of `BoardPosition[8]` (base `0x38`, stride 12,
x at `+0`, z at `+8`) — **four independent two-element min/max pairs over selected corners**, not a
sweep over the array: `min(x[1],x[2])`, `max(x[5],x[6])`, `min(z[0],z[7])`, `max(z[3],z[4])`. It is
a **bounding rectangle over the advertising-board ring**, which a sibling reader
(`0x143ec0dc0`) then forces to contain the pitch ± 2 m. It bounds where a celebration or a corner-loop
animation may roam. It is presentation, and the field names (`AudiencFixationPoint`, `AwaySeatArea`,
`BoardPosition`, `Entrance`, `MedicalArea`, `ProhibitionArea`, `ShiftArea`, `TechnicalArea`) agree —
but **"non-gameplay because of the folder name" was luck, not method**, and whether the box also
constrains where players *stand* at a corner is **NOT PROVEN**. [b]

Two more corrections to the triage's framing, both about the word *dead*:

- **"Located, N readers, dead" is the wrong finished answer for every family located here.** All of
  them have readers, at substantial coverage (tutorial drills 52 of 75 distinct fields touched at the
  reader site, PathToGlory 53/80, Sugoroku 52/75, `demoarea` 24/28 over 23 sites, `ballPerson` 165/211).
  Those are lower bounds from distinct offsets touched, not a re-run of the tool. The finished answer
  is "located, read, confined to subsystem X". [b]
- **The pitch half-extents are not a dt270 constant.** They live at `+0x00`/`+0x04` of
  `0x1442d6d80()` = `[[0x1486bd888]+0x63d0]`, a *registry* record; the demoarea object is a separate
  pointer used to widen a box around them. No dt270 object supplies pitch dimensions anywhere. [b]

---

## The eleven objects the plan reserved for this pass

The plan listed ~11 objects / ~115 fields as the genuine gameplay residue. **The count survives; the
membership does not.** `studiumPositionData` and `stadiumCustomParameterData` turned out to be stadium
furniture, `positionPK_2..5` + `positionNone` were already decoded by the set-piece chapter and are
live, and four objects the plan never mentioned joined the list. Here is every one, located or
honestly not.

### `animeAging{Dribble, FreeMove, Kick, Trap}` — 47 fields, **UNBOUND, and "ageing" means a soak test**

The plan read "ageing" as animation staleness or motion-blend ageing and filed it with the anime
chapter. It is neither. It is a QA **aging test** (エージングテスト — soak / burn-in), and the shipped
values settle it with no ambiguity [b, values read from `build/dt270_json`]:

| object | idx | shipped values |
|---|---|---|
| `animeAgingKick` | `0x4b` | `kickAngleStart 0.0`, `kickAngleAdd 22.5`, `kickAngleNum 16` (= a 360° sweep), `retryMax 128`, **`enableOutputCsv true`**, `zz_dummy 0` |
| `animeAgingTrap` | `0x4c` | ball fed at `ballSpeed 30`, `ballFlyTime 0.6`, 16 horizontal × 3 vertical angles, receiver parked at `playerTrapPos (0, 1.5, 0)`, `retryMax 128`, CSV on |
| `animeAgingDribble` | `0x49` | `turnAngle` 16 × 22.5°, `startTouchAngle 90`, `transitionTouchCount 3`, `repeat true`, `tableChecker 1`, CSV on |
| `animeAgingFreeMove` | `0x4a` | sweeps *player attributes*: `abilitySpeed 99 step −10 × 5`, `abilityHeight 195 step −5 × 5` (cm), `abilityExplosePower 99 step −10 × 5`, over `runningDistance 50`, CSV on |

A grid sweep, a retry count, a CSV dump switch and a `zz_dummy` padding field is a batch capture rig.
Almost certainly **the offline tool that generates the `moveMatching` / animation-matching tables**
the anime chapter decoded. Unbound: each is its own singleton C++ type (so no family selector can
hand it out), no get site has a constant index equal to `0x49..0x4c`, and no `mov edx,imm32` /
`mov dl,imm8` / `lea edx,[reg+imm8]` encoding for those values exists within `0x80` bytes of any of
the 268 sites — positive control `trap` (`0x6f`) has 45 such encodings. **Nothing to tune. Say so and
move on.** [b]

### `userPlayTendencyTest` — 22 fields, **UNBOUND fixture, real taxonomy**

Same four negatives: singleton type, no constant site, key strings referenced only by its own loader
`0x14534d0f0`. The `version` field — a 32-byte string, shipped `"v4.0"` — plus the literal `Test`
suffix make it authoring data, not a model. [b]

The **contents** are the valuable part, because they name a 21-category model of how a user plays,
with weights [b, read from the pack]:

```
setPlayGoal 2000   border 1000   offSidetrap 1000   middleShoot 600   earyCross 600
teamMateMoving 600  sideChange 500  airBattle 450  controlSho 400  cross 360
nearControl 350  feint 300  flyThrough 300  sliding 300  tackle 300  oneTwo 200
intercept 170  kickAndLush 150  grndThrough 60  oneTouchPlay 50  dribble 30
```

**Whether a live counterpart exists is NOT PROVEN, in either direction.** What is proven is that if
one exists it does not use these key names anywhere in the image, and it does not read this object.
"The AI reads how I play" is unresolved, not refuted — and these 21 categories are the best lead
anyone has for finding it.

### `studiumPositionData` (28) + the 101 `demoarea_*` — **family-level bound**, stadium dressing

`studiumPositionData` shares the struct type `demoarea_bill_acl` with the 101 `demoarea_*` objects
and is fetched the same way, through `[matchEnv+0x40]`. Its shipped values are **4 non-zero scalars
out of 83** (three `1.0`s and a `true`): it is the family's null/template entry. [b + a]

### `stadiumCustomParameterData` (3) — **UNBOUND by index, but its reader is known**

Shares the type `demoarea_custom_st099` with the object at `0x85`, which *is* constant-fetched at
`0x1442c78e9` / `0x1442c7929`. **That is a type-sibling argument, and a type sibling tells you who
would read it if it were fetched, not that it is fetched** — so it stays in the unbound column, which
is where the third probe put it and where the second probe wrongly did not. Content:
`PitchsideObjectsData[6].{r, x, z}` — six props of radius 10 at (±60, ±15) and (±20.5, −40.5) [a].
The accessors `0x1442c78d0` (`.x`) and `0x1442c7910` (`.z`) are bounds-checked `cmp edx,6` and are
called only from `match::demo::PkDemo`; **`.r` is read by nothing at all**. [b]

### `positionNone` (4) + `positionPK_2..5` (16) — **BOUND BY NAME, and already decoded**

These belong to [set-pieces.md](set-pieces.md), which located and valued them. Confirmed here end to
end, and with one correction to that chapter (§ Corrections):

```
0x1475d1850  {"positionNone", 0x70}  {"positionPK_2", 0x71}  {"positionPK_3", 0x72}
             {"positionPK_4", 0x73}  {"positionPK_5", 0x74}        (16-byte stride)
0x145349470  5-iteration inlined strcmp over that table;  match -> mov eax,[rbx+rax*8+8]
                                                          miss  -> mov eax, 0x70 ; ret
0x143c6855c  call 0x145349470
0x143c68561  mov  dword ptr [rbx+0x6ee0], eax          <- the Loader caches the index
0x143c685d2  mov  edx, [rsi+0x6ee0]
0x143c685dd  call 0x145349560                          <- the reader's fetch
0x143c685e4  lea  rbx,[rax+0xc] ; cmp byte[rbx-4],1    <- playerData[0].enable at +0x8
```

The read offsets are `0x8,0xc,0x10,0x14 / 0x1c,0x20,0x24 / 0x2c,0x30,0x34 / 0x3c,0x40,0x44` — exactly
`playerData[].{enable, playerNo, startPosX, startPosZ}` at stride 16. [b, all of it re-derived here]

`positionNone` ships with **all 22 rows `enable = 0`** and X = Z = 0 (`playerNo` runs 0..21, which is
the only non-zero content). The "inert, do not bother" verdict stands — but **it is reachable**, as
the resolver's not-found default (§ Corrections).

### `mlScreenShot` — 19 fields, **UNBOUND**

`shotPattern[17].{cameraPos, lookAt, fovY, percent, scene, timing}`, 224 non-zero scalars — a
populated Master-League auto-screenshot camera table, with no fetch path. Almost certainly a PES-era
leftover in a game with no Master League. Flagged here because Phase 3 of this project *is* screenshot
capture: **it is not useful to that work** — it frames the game's own screenshots, and nothing calls
it. [b + a]

### `ballplayer` — 23 fields, **UNBOUND, and the only thing here worth following up**

`constant/player/ballplayer.json`, struct `0x12558` bytes: `Feint.{DataUse, disp_area, rate}` and
**`TurnData[1440]`** (stride 52: `input_angle`, `kind0`, `kind1`, `p0_length_min/max/mle`,
`p0_speed_average`, `p1_angle_left/mle/rigth`, `p1_length_min/max/mle`) and `touch0[7]`
(`frame_min/max/ave`, `length_min/max/ave`, `valid_data`). That is the richest ball-carrier turn and
first-touch table in the whole pack, and it reads like exactly the surface realism item 4 wants.

**It has no sound fetch site.** Its only listed get site is `0x143fef479`, which provably cannot
produce index `0x67` (below), so its `located` status and its four `read` fields are spurious. No key
table contains `0x67`, no constant site produces it, and no dynamic site's access pattern can be
attributed to it once the families are accounted for. **Do not tune it and do not trust a result if
you do** — an effect would mean a sixth fetch mechanism exists. [b]

### `pathToGlorySetting`, `SugorokuSetting`, `tutorialSetting` — 9 fields, **UNBOUND, and they explain themselves**

Three singletons of 3 fields each, all with the same shape: `isTutorialPlay: false`,
`startTutorialKind`, and a 29-entry `tutorialKind[]` enum list. They are the developer's
**boot-straight-into-drill-X switch**, which is exactly why a retail build never fetches them. [a]

Two things fall out that are new:

- **`pathToGlorySetting` ships the tutorial content verbatim** — its 29 enum values are
  `TUTORIAL_KIND_*`, not a PathToGlory enum, while `SugorokuSetting`'s are `SUGOROKU_KIND_*`. Both
  modes are clones of the tutorial system, and one clone was never re-authored. [a]
- The enum list is **not** the key space of the static tables: `tutorialKind[]` runs
  `NONE, BEGINNER_DRIBBLE, …, STANDARD_AUTO_POSITIONING` (29 entries) while table `0x148081340`'s keys
  0..16 map to `Dribbling / Passing / Shooting / Tackling / Through_ball / Switch_sides /
  Beginner_Clearing_the_ball / Beginner_Crossing / Mobile*`. **Different enums; the orders do not
  line up.** Worth recording so nobody assumes they do. [a + b]

### The `0x143fef479` defect — 7 objects the catalogue locates wrongly, 4 of them with no other site

One get site is claimed by **eight** objects at consecutive indices `0x64..0x6b`. Two probes derived
two different true indices; here is the resolution, from the bytes:

```
0x143fef3cc  mov   ecx, 2
0x143fef3d1  ... 128-byte block copy ...
0x143fef426  sub   rcx, 1
0x143fef42a  jne   0x143fef3d1            ; exits with rcx == 0
0x143fef46f  lea   edx, [rcx+0x6a]        ; therefore edx = 0x6a
0x143fef479  call  0x145348d70
```

The loop is entered with `rcx = 2` and exits on `rcx == 0`, so **the index is `0x6a` =
`grounderpass`** — not `0x6c`/`passget` as the second probe read it. The tool's emulator widened `rcx`
over the loop iterations and emitted a *range*. [b, re-derived here; this is the single point on
which the probes flatly contradicted each other]

**Which register carries it settles every read in that function.** The pointer lands in `r14`:

```
0x143fef479  call  0x145348d70          ; edx = 0x6a  -> grounderpass
0x143fef48a  mov   r14, rax             ; the ONLY pointer ever written to r14 here
0x143fef485  mov   edx, 0x69            ; flypass ...
0x143fef48d  call  0x145348d70
0x143fef49e  mov   rbx, rax             ;   ... into rbx
0x143fef499  mov   edx, 0x6e
0x143fef4b2  mov   r13, rax             ;   ... and 0x6e into r13
```

A scan of every instruction in all six `func_chunks` of `0x143fef370` finds exactly four writers of
`r14`: `0x143fef48a mov r14, rax`, `0x143fef901 cvttss2si r14d, xmm0`, `0x143fef918 sub r14d, ebx`
and the epilogue `pop r14`. The last three write an **integer**, not a pointer. So **every
`[r14+K]` read in this function is a `grounderpass` read or nothing at all — it is never a
`centering`, `ballplayer`, `PathToGlory*` or `pathToGlory*` read.** Reads off `rbx` (`flypass`) and
`r13` are genuine. [b, re-derived here with `regs_access()` over all chunks]

Consequence, in two parts. **(1) Four objects are fully withdrawn.** `PathToGlory9` (`0x64`),
`pathToGloryNone` (`0x65`), `pathToGlorySetting` (`0x66`) and `ballplayer` (`0x67`) **have no other
get site**, so all 186 of their field classifications go — 8 `read` and 178 `unread`.
(`PathToGlory9` and `pathToGloryNone` are re-bound by the PathToGlory key table; the other two fall
into the unbound residue.) **(2) Three more objects are contaminated but keep their `located`
status** through other get sites — `centering` (`0x68`, 5 other sites), `flypass` (`0x69`) and
`moveMatching` (`0x6b`). Their reader *lists* contain `grounderpass` sites, and for
**`centering.adjustGageFarZ` (+0x10) and `centering.adjustGageNearZ` (+0x14) the bogus attribution is
the only reader they have** (3 readers each, all `movss xmm,[r14+K]` in `0x143fef370`), so those two
fields **must flip `read` → `unread`**. `moveMatching`'s four polluted fields and `centering`'s other
two each have a reader elsewhere, so their status is unchanged; `flypass`'s two `0x143fef370`-only
fields read off `rbx` and are real.

Filtering the catalogue for "every reader of this field lies in `0x143fef370` off `r14`" returns
exactly 10 fields: `PathToGlory9` 1, `pathToGloryNone` 1, `pathToGlorySetting` 2, `ballplayer` 4,
`centering` 2. So **10 of the 12,008 `read` fields and 178 of the 4,607 `unread` ones are not
measurements at all.** Corrected headline: **101 objects located by constant index, 11,998 genuine
reads, 4,431 genuine unreads** (4,607 − 178 withdrawn + 2 reclassified), of which **4,302 at
`unread_confidence: high`** and 129 `reduced`. [a + b, both re-derived here]

---

## Tunables

Route legend: **dt270-data** = edit the constant pack, no exe patch, no shared pool cell, survives
Konami updates. **not-reachable** = no fetch path exists; editing it is expected to do nothing.
**NOT-SAFELY-TUNABLE** = do not act on it yet.

"Sharers" is *not* an `exe_census` pool-cell count — **none of these objects contributes an exe-side
constant**, so there is no literal-pool cell to census. It is the number of dt270 objects that share
the reader, i.e. how wide an edit's blast radius is.

| what | site | route | effect | sharers | ev |
|---|---|---|---|---|---|
| `positionPK_{2,3,4,5}` — 22 penalty standing positions per variant, `{enable, playerNo, startPosX, startPosZ}` | idx `0x71..0x74`, resolved by name via `0x145349470`, read at `0x143c685dd`, applied by `0x143c4f5f0` | **dt270-data** | moves the twenty-two bodies at a penalty; pick the file by the defending back-line count. **Already the set-piece chapter's lever** — listed here only because it closes the residue | 5 objects share the reader; nothing else in the image reads them | b |
| `demoarea_*.BoardPosition[0..7]` — the rectangle `match::anime::action` clamps against | idx `0x75..0xda` via `[matchEnv+0x40]`; read at `0x143f09206`, `0x143fc8538`, `0x143fbd332`, `0x143fbdbe7`, `0x143fce329`, `0x144089b64`, `0x14408e6a1` | **dt270-data** | widens or narrows the min/max box inside which corner-loop, goal-celebration and receive-ball **animations** may place the actor; a sibling reader forces it to contain pitch ± 2 m. **Presentation, on the evidence available** — whether it also constrains player standing positions at a corner is not proven | 102 objects share the type and the readers; the edit is **per stadium** | b |
| tutorial drill parameters — `floatValue01..10`, `intValue01..10`, `gradeGold/Silver/Bronze`, the `is*End` conditions, `coneData[]` | idx `0xe3`, `0xe5..0xf4`; bound by table `0x148081340`; read by `match::StepupTutorialBase::vf4` `0x143cb2ca0` via `[this+0x520]` | **dt270-data** | drill pass/fail thresholds, cone layout, end conditions. **Tutorial mode only — no match-AI reader** | 17 objects, one reader | b |
| PathToGlory chapter parameters (same 80-field schema) | idx `0x59..0x65`; table `0x148081460`; read by `match::PathToGloryBase::vf4` `0x143cc4470` via `[this+0x530]` | **dt270-data** | chapter objectives and thresholds. Mode only | 13 objects, one reader | b |
| `stadiumCustomParameterData` / `demoarea_custom_st099` `PitchsideObjectsData[6].{r,x,z}` | idx `0xdb` (unbound) and `0x85`; accessors `0x1442c78d0` (`.x`) / `0x1442c7910` (`.z`) | **dt270-data** for `0x85` only | cosmetic, and half dead: **`.r` is read by nothing**, and `.x`/`.z` only by `match::demo::PkDemo`. **Not worth it** | 2 objects, 2 accessors, 4 call sites | b |
| `positionNone` | idx `0x70` | **dt270-data**, but | reachable **as the resolver's not-found default**. All 22 rows `enable = 0`, X = Z = 0 — which is the correct "no repositioning" behaviour. **Not worth it**, and a mistyped `positionPK` name silently lands here | shares the reader with `positionPK_2..5` | b |
| `animeAging{Kick,Trap,Dribble,FreeMove}` — 47 fields | idx `0x49..0x4c`, **no get site anywhere** | **not-reachable** | none. A developer CSV-dumping sweep rig. **Not worth it** | n/a — only its own JSON loader touches these bytes | b |
| `userPlayTendencyTest` — 21 weighted categories + `version "v4.0"` | idx `0x58`, no get site | **not-reachable** | none as data. Worth reading once as documentation of Konami's own user-play taxonomy, then leaving alone. **Not worth tuning** | n/a — loader `0x14534d0f0` only | b |
| `mlScreenShot` — 17 shot patterns | idx `0x4f`, no get site | **not-reachable** | none. **Not worth it**, including for Phase 3 | n/a | b |
| `pathToGlorySetting` / `SugorokuSetting` / `tutorialSetting` — 9 fields | idx `0x66`, `0xde`, `0xe4`, no get site | **not-reachable** | none. Developer mode-launcher switches (`isTutorialPlay: false`). **Not worth it** | n/a | b |
| the **~4,302 unread fields at `unread_confidence: high`** in the 101 constant-index objects (plus 129 at `reduced`; 4,431 corrected unread in total) | `build/dt270_liveness.json`, `status: unread`, `unread_confidence: high`. **A raw filter returns 4,478 — subtract the 178 fields in `PathToGlory9` / `pathToGloryNone` / `pathToGlorySetting` / `ballplayer` first (§ the `0x143fef479` defect), then add `centering` +0x10 and +0x14** | **not-reachable, with three named holes** | expected none: no reader on any *statically reachable direct-or-followed-call* path. Holes: the cached-pointer pass was never run (can only touch 211 fields, in `ball` / `throughpass` / `basePosition`); 129 fields sit behind 4 unfollowed indirect calls; and the completeness audit that found zero overturns bounds only *within-function* misses in functions where a reader was already attributed | n/a | a + b |
| `ballplayer` — `Feint` + `TurnData[1440]` + `touch0[7]` | idx `0x67` | **NOT-SAFELY-TUNABLE** | unresolved. Gameplay-shaped, no fetch path, and its catalogued readers are mis-attributed. **Treat any observed effect as unexplained** and open a probe instead | unknown — its four cited readers are `grounderpass` reads off `r14` in `0x143fef370`, the same misattribution § the `0x143fef479` defect documents; nothing is known to share with it | b |

---

## Corrections to finished chapters

**1. [set-pieces.md](set-pieces.md) § positionPK — the name→index function is `0x145349470`, not `0x1453494e0`.**
The chapter's trace line `0x143c4c458 call 0x1453494e0 ; name -> dt270 index` (and the § Summary row
"*fetched through `0x1453494e0`*") names the wrong function. `0x1453494e0` walks the same table but
ends `cmp eax,0x70 ; setne al` — it returns a **bool** ("resolved to something other than
positionNone"), and its result is **discarded** at its only call site: the next instructions are
`lea rax,[rsp+0x50]` (which destroys `al`), a `strlen`, and `call 0x1410e6d80` (std::string assign),
with nothing testing `eax` or `al`. The real resolver is `0x145349470` (same table, returns the index,
default `0x70`); its **only** caller is `0x143c6855c`, immediately followed by
`0x143c68561 mov dword ptr [rbx+0x6ee0], eax` — precisely the slot the chapter's reader loads at
`0x143c685d2`. Everything else in that section (the `sprintf` path, the reader, the applier, the
values, the back-line binding) stands. [b, re-derived here]

**2. [set-pieces.md](set-pieces.md) — `positionNone` is NOT unreachable.** The chapter says "*the only
name producer is `sprintf("positionPK_%d", …)`, which cannot emit the name*". True, and irrelevant:
`0x70` is the resolver's **not-found default** (`0x1453494c4 mov eax,0x70 ; ret`), and the name is
built from `movzx r9d, byte ptr [rax+0x7bc8]` at `0x143c4c435` with **no range check** before the
`sprintf` at `0x143c4c44e` (`0x143c4c43d` is the `lea r8,[rip+0x2ea885c]` that loads its format
string). Any back-line count outside {2,3,4,5} produces a non-matching name and
therefore selects `positionNone` — all 22 rows disabled. The **data verdict ("inert, do not bother")
is unchanged**; only the reachability claim falls. [b]

**3. [set-pieces.md](set-pieces.md) — add the table, and the general negative.** The chapter never
names the table: `0x1475d1850`, 5 entries of 16 bytes `{const char* name; int idx; int pad}`,
contents `positionNone 0x70`, `positionPK_2..5 0x71..0x74`. And a rip-relative reference sweep of the
whole `.xcode` section finds exactly three targets in the registration-table data region —
`0x1475d1850` (this table), `0x1475d2600` (a **vftable**, not a name table) and `0x1475d2ba0` (the
245-entry registration table itself). **By-name fetching exists for these five objects and no others
in the image**, so no other unlocated object can be hiding behind a name lookup in code. [b]

**4. [player-executors.md](player-executors.md) and the standing project note on inert cells —
restate `forceDashDist` precisely.** "Read and then **unconditionally** overwritten before its only
compare" is the wrong description of a correlated-branch pair, and the difference matters because that
shape is exactly what automated dead-load detection misses. The flag `byte[r14+0x28d]` is tested
twice: the first test picks the load (`je 0x143da9420` → `+0x184` **Defence**, else `0x143da9414` →
`+0x188` **Offence**, both into `xmm7`) and the second (`0x143da9551 jne 0x143da95a3`) lets the
**Offence** path skip the overwrite at `0x143da9553` and reach `comiss xmm9,xmm7`. So
**`basePosition.forceDashDistOffence` is fully live**, and `forceDashDistDefence` is dead on its own
path. [b, re-derived here; the catalogue's per-field readers agree — `+0x184` at `0x143da9420`,
`+0x188` at `0x143da9414`]

**5. [anime-actions.md](anime-actions.md) and [set-pieces.md](set-pieces.md) — `match::anime::action`
bodies read per-stadium dt270 geometry, and neither chapter records it.** `anime-actions.md` lists
`CornerKickLoop` as "classified in the set-piece work, not opened here"; `set-pieces.md` groups
`CornerKickLoop` and `SeamlessPass(+Ready)` under `vf8 0x143f05150` as "bodies not examined here". In
fact `0x143f090c0` fetches a `demoarea` object through `[matchEnv+0x40]` and takes
`min(x[1],x[2])`, `max(x[5],x[6])`, `min(z[0],z[7])` and `max(z[3],z[4])` at
`0x143f09206..0x143f0922f` — **four two-element min/max pairs over selected corners of the board
ring, not a sweep over the array** (eight of the sixteen scalars; six of the eight elements untouched
on one axis or the other); the same pattern is in
`GoalEvent::vf2` (`0x143fbdbe7`), `GoalEvent::vf4` (`0x143fbd332`), `RecieveBall` (`0x143fc84fb`) and
`SeamlessPassReady` (`0x143fce329`). **Animation placement in these actions is bounded by
stadium-dependent data, not by a constant.** [b]

**6. Any chapter citing `basePosition.dfLine` (+0x13c) — it is live, and its `confidence: low` is a
width artefact, not doubt.** Declared `int`, read as `movzx eax, byte ptr [rbx+0x13c]` at
`0x143ddb9a0`, `cvtdq2ps`'d and normalised into a 0..1 rate written to `[rdi+0x44]`. This generalises:
**828 of the 835 read fields whose every reader is flagged misfit are `movsd` packed loads of two
adjacent floats.** [b for `dfLine`, a for the 828]

**7. [realism-todo.md](realism-todo.md) and the catalogue notes — record what `cached: 0` means, and
where the catalogue lives.** The cached-pointer pass was **not run** (`cached_offsets: []`), and
running it now exhausts memory; its unmeasured exposure is **211 unread fields in exactly three
objects** (`ball`, `throughpass`, `basePosition` — the only objects with a pointer store), not the
whole `unread` class. Also: **`build/` is gitignored**, so `build/dt270_liveness.json` is a *local
artifact*, not a committed one — a fresh clone has to rebuild it with
`python tools/dt270_liveness.py build --exe <image> --no-cache-pass`. The shipped numbers were
generated at 2026-09-17 22:03, **fourteen minutes before the last edit to the tool** (mtime
2026-09-17 22:17; first commit 2026-09-19), which is why they carry
`unlocated_with_candidate_reader: 0` where the current tool reports 2,639 (and 429 for `unread`). The
headline numbers are unaffected. [a]

### Corrections to this chapter (adversarial review, 2026-09-20)

Two verifiers reviewed the first draft. Every issue below was **re-checked against the bytes or the
catalogue before being applied**; none of them was wrong, and two of them made the chapter's own
negatives stronger rather than weaker.

| # | what the draft said | what the bytes say | evidence |
|---|---|---|---|
| C1 | the `0x143fef479` defect withdraws **4 objects**, "8 reads / 178 unreads", corrected headline **12,000 / 4,429** | **7 objects are contaminated.** `r14` in `0x143fef370` is provably the `0x6a`/`grounderpass` pointer, so `centering.adjustGageFarZ` (+0x10) and `adjustGageNearZ` (+0x14) — whose *only* readers are that bogus attribution — must flip `read`→`unread`. **10 reads / 178 unreads withdrawn; corrected 11,998 / 4,431** (4,302 high + 129 reduced). `moveMatching`'s 4 and `centering`'s other 2 are also polluted but have readers elsewhere; `flypass`'s two read off `rbx` (the genuine `0x69` fetch) and are real | [b] all four writers of `r14` across the six `func_chunks` of `0x143fef370`: `0x143fef48a mov r14,rax` (the only pointer) then `cvttss2si r14d`, `sub r14d,ebx`, `pop r14`. [a] catalogue filter "all readers in `0x143fef370` off `r14`" returns exactly 10 fields |
| C2 | Tunables: "**4,429 high-confidence** unread ... no reader on any statically reachable path" | 4,429 was the *corrected total*, not the high-confidence count. The raw filter `status:unread, unread_confidence:high` returns **4,478**, which still contains the 178 withdrawn fields. Corrected high-confidence = **4,302**; the row now says so and names the three holes | [a] `summary.unread_high_confidence` = 4478, `unread_reduced_confidence` = 129; 4478 - 178 + 2 = 4302 |
| C3 | "trust the `unread` verdict — you can, with a measured error bar" / "no reader on any statically reachable path" | The **cached-pointer pass was never run**, and the `cached` status exists precisely to reclassify `unread`. Bounded here: only **3 objects** in the catalogue ever have a pointer store, so exactly **211 unread fields** are exposed and **4,396 are not**. Both trust rows now carry it | [a] `pointer_storing` = `{0x143dabb90: throughpass, 0x144072af0: ball}` plus `basePosition`'s two stores; unread counts 11 / 82 / 118. [b] `dt270_liveness.py:1787-1789` |
| C4 | the 663/199/343 audit is "an error bar on `unread`", over "the functions it visited" | Its universe is only the functions where the tool had **already attributed a read of that object**. 3 located objects have **zero recorded readers** (`PathToGlory1` 80, `MobileShooting` 75, `MobileThroughPass` 75 = **230 unread fields with no audit coverage at all**). Restated as an internal-consistency result, with the uncovered set named | [a] catalogue scan for located objects where no field has a reader |
| C5 | "343 sites across **11** gameplay objects", listing `shoot` | **10** — `shoot` produced no candidates, as the draft itself said two sentences later. Per-object rows: throughpass 97, basePosition 80, cameraInplay 40, passget 29, rating 24, trap 23, centering 20, grounderpass 17, ball 8, moveMatching 5 | [b, probe 1's rows] |
| C6 | Tunables: `ballplayer` "sharers ... the cited readers belong to `passget`/`flypass`/`throughpass`" | Wrong three chapters. Its four cited readers are `[r14+K]` reads in `0x143fef370` = **`grounderpass`** (`0x6a`). `passget` is `0x6c` and is not fetched in that function at all; `flypass` (`0x69`) goes to `rbx`; `throughpass` is not involved | [a] all four `ballplayer` `read` fields' readers are `movss xmm,[r14+8/0xc/0x10/0x14]` in `0x143fef370`. [b] the register assignment at `0x143fef48a` / `0x143fef49e` |
| C7 | Negatives: "**There is no undiscovered mechanic hiding in the 5,362** [b]" | Downgraded to a **routing** negative. The draft's own "Bound is not measured" says 5,548 fields have never had liveness computed, and the folder-name triage is called unsafe two sections earlier. The binding evidence is fetch-route only — the key tables bind indices, they do not seed the pointer flow | [b] for the routing; **not proven** for inertness. Same tag applied to "the constant map is closed" |
| C8 | headline: "none is a **gameplay mechanic** ... and the 20 `positionPK` fields were already decoded and are live" | Self-contradictory inside one sentence: a lever that moves all 22 bodies at a penalty *is* a gameplay mechanic. Now "none is a ***new*** gameplay mechanic", with `positionPK` named as a live lever the set-piece chapter owns | [b] name table `0x1475d1850` -> resolver `0x145349470` (sole caller `0x143c6855c`) -> `Loader+0x6ee0` -> reader `0x143c685dd` |
| C9 | "5,265 of those fields (**97.7 %**)", in three places | 5,265 / 5,362 = **98.19 %**. Corrected to 98.2 % in the headline, the routing paragraph and the closing section. The bucket totals themselves were all exact | arithmetic |
| C10 | "an absolute-pointer scan finds **no 64-bit reference** to `0x145348D70` or `0x145349560` in any section" | The test as stated does not reproduce for `get()`: the 8-byte LE value occurs **4 times**. The conclusion holds — all four are unaligned bytes inside `mov [rsp+0x70],rsi ; lea esi,[rax*2+1]` — but the phrasing had to change or a reader repeating it loses confidence | [b] file offsets `0x312e3ee`, `0x343ad0e`, `0x3442b7e`, `0x35f450e`, every one != 0 mod 8; `0x145349560` / `0x145348e50` / `0x145349470` have 0 occurrences |
| C11 | "the published JSON **predates the committed tool by two days**" | Fourteen minutes: JSON `meta.generated` 2026-09-17 **22:03**, tool mtime 2026-09-17 **22:17**; 2026-09-19 is only when that already-edited file was first committed. And **`build/` is gitignored**, so the catalogue is a local artifact, not a published one | [a] `meta.generated`; `ls -l` mtime; `git check-ignore -v build/` -> `.gitignore:54` |
| C12 | re-run command `dt270_liveness.py build --exe <image>` | The cached pass is **on by default** and dies with `MemoryError` before writing anything — after overwriting `tools/data/dt270_struct_offsets.json`. The command now carries **`--no-cache-pass`**, with the warning | [b] `main()` defines `--no-cache-pass` as an opt-out (`tools/dt270_liveness.py:1610`, `:2183`) |
| C13 | Correction 5: "takes min/max over `BoardPosition[0..3]` and `[4..7]`" | Nothing ranges over `[0..3]`/`[4..7]`. It is **four independent two-element pairs**: `min(x[1],x[2])`, `max(x[5],x[6])`, `min(z[0],z[7])`, `max(z[3],z[4])` — 8 of the 16 scalars. Fixed in the correction *and* in the triage body, since that text is about to be pushed into two other chapters | [b] `0x143f09206`..`0x143f0922f`, offsets `0x44/0x50`, `0x74/0x80`, `0x40/0x94`, `0x64/0x70` against base `0x38`, stride 12, x@+0 z@+8 |
| C14 | "At **229 sites** it is a plain `mov edx, imm` — that is the **only shape** the tool recovers" | Unsourced and self-contradicted (the whole `0x143fef479` defect is the tool folding a `lea`). Measured: **234 of 268 sites bind**, of which **227 `mov edx, imm`**, **4 `lea edx,[reg+K]`** (`0x143f8ad8f`, `0x143fef479`, `0x144078ca1`, `0x14424bb6f`) and 3 with no `edx` producer within 64 bytes; the other 34 are `unknown_idx_sites` | [a] decoded backwards from each of the 234 sites, last writer of `edx`/`rdx`/`dl` taken |
| C15 | inline addresses: "the `sprintf` at `0x143c4c43d`"; "`0x143f09215 movss xmm4`"; "**368** of 12,008 (3.1 %)" | `0x143c4c43d` is the format-string `lea`; the `sprintf` call is `0x143c4c44e`. The `movss xmm4` is at `0x143f09210` (`0x143f09215` is the `maxss`). Recomputed in-place consumption: **369 / 12,008 = 3.07 %**, with the load set now stated | [b] disassembly; [a] recount over the catalogue |
| C16 | the 663/199/343 and 120/17 counts tagged bare `[b]` / `[a]` | They are **probe 1's**, not re-derived for this chapter, and their scripts (`within.py`, `prov.py`, `build_dispindex.py`) lived in a session temp directory and were not retained. Re-tagged "measured once, artifacts not retained" so nobody treats them as re-checkable | provenance |
| C17 | the `demoarea` listing jumps from a `call` returning into `rax` straight to a read off `rbx` | `0x143f091dc mov rbx, rax` is the instruction that puts `matchEnv` in `rbx`; without it the `= matchEnv` annotation is unverifiable from the quoted bytes, in a chapter whose thesis is that base-register provenance decides these questions. Added | [b] `0x143f091d7 call 0x1442d6dc0` -> `0x143f091dc mov rbx, rax` -> `0x143f091ed mov edx,[rbx+0x40]` |

**One thing the review did not overturn.** The `unread` verdict itself survived: an independent
8-field / 93-site re-hunt traced 0 of 93 image-wide read sites back to a `get()` pointer. Nothing
under the verifiers' "holds" was touched — the re-run identity, the 25/25 acceptance suite, the
`0x6a` resolution, the `forceDashDist` correction, the `positionPK` chain, the three static key
tables, the five by-name objects, the displacement-universe negative, the containment trap, the 828
`movsd` artefact, the shipped `animeAging` / `userPlayTendencyTest` / `studium*` / `positionNone`
values and the routing arithmetic all stand as written.

### Between the probes

Three probes ran; six load-bearing disagreements were settled from the bytes for this chapter.

| point | resolution |
|---|---|
| index at `0x143fef479` — `0x6a` or `0x6c`? | **`0x6a`** (`grounderpass`). `mov ecx,2` + a loop exiting on `rcx==0`; the `lea` sees `rcx = 0`. [b] |
| is `positionPK` located? | **Yes, by name** — two probes found the table, the third missed it and left the five objects in its residue. The whole chain is re-verified above. [b] |
| what does site `0x143c685dd` read? | **`positionNone`-family `playerData[]`**, from index provenance. The third probe attributed it to `ballPersonData` by struct containment — but **26 of 36 types contain all 13 offsets**, so containment proves nothing here. [a + b] |
| is `stadiumCustomParameterData` located? | **No.** Sharing a struct type with a constant-fetched object identifies the *reader*, not the fetch. It stays unbound. [b] |
| are `ball_person_st101/102/103` bound by a table near `0x14825b8a0`? | **No.** That region is a `(id, byte-offset)` pair table consumed by a flag-serialisation loop at `0x1453f6e90` (`call 0x1442bfa70` / `0x1441172b0`), nothing to do with `ConstantManager`. Its second field matched dt270 indices by coincidence — **the exact trap this project keeps falling into**. Those three stay family-level only. [b] |
| is `studiumPositionData` "entirely zero"? | **4 of its 83 scalars are non-zero** (three `1.0`s and a `true`). "Effectively a null template" is right; "entirely zero" is not. [a] |

---

## Negatives

- **The predicted shrink did not happen and could not have.** The re-run is identical in all four
  categories and in all 21,977 per-field statuses. Eight subsystem chapters moved the human's
  knowledge, not the tool's output: `dt270_liveness.py`'s only input is the exe. [a + b]
- **A whole-image displacement search cannot decide dt270 liveness.** Only 7 of 4,607 unread fields
  (0.15 %) have no covering read operand anywhere in 20.3 M decoded instructions; the median has 324.
  Pointer provenance is the only thing that can answer the question. [a]
- **The brief's premise that the `unread` verdict rests on a pattern search is wrong.** The tool
  decodes and abstractly interprets; the one byte pattern in the file feeds the cached pass, which was
  off. The gotcha is real and well-earned elsewhere in this project; it does not apply here. [b]
- **Zero genuine misses in the `unread` verdict, within the scope the audit actually has.** 663
  independent candidate misses across 91 objects; 199 fields at 343 sites hand-traced across **10**
  gameplay objects; none overturned (`shoot` produced no candidates at all). **Scope**: the audit only
  searched functions in which the tool had *already* attributed a read of that object, so it is an
  internal-consistency result — it cannot see functions the tool entered and attributed nothing in,
  functions it never reached, the cached route, or the 230 unread fields in the 3 located objects with
  no recorded reader (`PathToGlory1`, `MobileShooting`, `MobileThroughPass`). An independent 8-field /
  93-site re-hunt for this review traced 0 of 93 sites to a `get()` pointer, which is a second sample,
  not a bound. [b, probe 1's audit not re-derived here and its scripts not retained; b for the
  re-hunt]
- **Zero structurally dead loads** in a 120-field sample of `read` across 17 objects. The inertness
  risk is not dead loads; it is infeasible paths, and that class is not detectable with a
  path-insensitive walk. [a]
- **The 835 "low confidence" read fields are not doubtful reads.** 828 are packed `movsd` loads of two
  adjacent floats. [a]
- **There is no second by-name fetch path and no indirect route to `get()`.** Exactly three code
  references exist into the registration-table data region — the 5-entry name table, a vftable and the
  registration table itself. And **no 8-aligned 64-bit pointer to `0x145348D70`, `0x145349560`,
  `0x145348e50` or `0x145349470` exists anywhere in the image**: the latter three have zero byte
  occurrences at all, and `0x145348D70` has exactly four byte-coincidences (file offsets `0x312e3ee`,
  `0x343ad0e`, `0x3442b7e`, `0x35f450e`), every one of them ≠ 0 mod 8 and sitting inside the
  instruction stream `48 89 74 24 70 / 8d 34 45 01 00 00 00` = `mov [rsp+0x70],rsi ; lea esi,[rax*2+1]`.
  None is a pointer. All 268 fetches are direct rel32 sites. [b, the scan re-run here — quote it this
  way, because the naive "no occurrences" phrasing returns four hits and loses a reader's confidence]
- **The ~115-field "genuine gameplay residue" contains no *new* mechanic.** `animeAging*` is a
  developer CSV-dumping sweep rig, `userPlayTendencyTest` is a versioned test vector,
  `studiumPositionData` and `demoarea_*` are stadium furniture, and `positionPK_*` is a live lever
  already decoded by and belonging to the set-piece chapter. **This is a *routing* negative, not a
  liveness negative**: every one of the 5,265 newly bound fields belongs to a tutorial drill, a mode
  chapter, stadium dressing or a touchline rig, and each family's readers are confined to one
  subsystem — but their liveness was **never computed**, so "no undiscovered mechanic hiding in the
  5,362" is supported by where they are fetched from and read, not by any instruction-level proof of
  absence. [b for the routing; **not proven** for inertness]
- **`cached: 0` is not a finding — but the hole is bounded.** The mechanism was never run; running it
  now exhausts 21 GB and dies. Exactly 3 objects in the catalogue ever have their `get()` pointer
  stored (`ball` `K=0x8`, `throughpass` `K=0x8`, `basePosition` `K=0x38`/`0xf0`), so the unmeasured
  route can reclassify **211 unread fields and no others**; `K=0x8` and `K=0x38` are over the tool's
  candidate limit and cannot be closed by it at all. The other 4,396 unread fields are unexposed. [a]
- **"Located, 0 readers, dead" is wrong for every family located here.** All five mode/stadium
  families have readers at substantial coverage. Non-gameplay means *confined to a subsystem*, not
  *inert*. [b]
- **Struct-containment fingerprinting is worthless below ~8 distinct offsets, and weak even above it.**
  26 of 36 decoded types contain all 13 offsets of the `positionPK` reader site. The tool's stricter
  fingerprint correctly returned no fit rather than a wrong one; a replacement must not relax it. [a]
- **The pitch half-extents are not dt270 data.** They come from `[[0x1486bd888]+0x63d0]+0x00/+0x04`, a
  registry record. No dt270 object supplies pitch dimensions anywhere in the image. [b]
- **The writer of `[matchEnv+0x3c]` / `[matchEnv+0x40]` was not found.** The family identification
  rests on consumer offset fingerprints plus the index source, not on the setter — which is why those
  106 objects are **family-level** bound and not object-level. Said plainly rather than rounded up. [b]
- **No liveness was recomputed for the 133 newly bound objects.** Binding an index is not seeding it
  and re-running the pointer flow. Their per-family coverage numbers are distinct-offsets-touched — a
  lower bound on `read`, and silent on whether any read is *effective*. [b]

---

## Open questions

1. **`ballplayer` (`0x67`).** A 75,096-byte object of dribble-turn and first-touch tables with no
   fetch path. Either a sixth mechanism exists, or a genuinely dead table ships in the pack. The only
   gameplay-shaped item in the residue, and the one thing here that deserves a dedicated probe.
2. **Does a live user-play-tendency model exist?** `userPlayTendencyTest` gives a 21-category
   taxonomy with weights and nothing reads it. A runtime breakpoint on the generic name resolver
   `0x145348e50` while entering different modes would settle mechanism 5 for the *whole* residue in
   one experiment — and would answer "does the AI read how I play".
3. **The 4 certain unfollowed indirect calls** — `0x14408905d` / `0x1440890bf` / `0x14408919e` in
   `0x144088f90` (`ball`, dispatching `call [rax+8]` / `call [rax+0x10]` over an observer list at
   `[r14+rax*8]`) and `0x143e63937` in `0x143e637e0` (`basePosition`). Enumerating those vtables moves
   129 unread fields from `reduced` to `high` and makes the `unread` verdict unqualified.
4. **The cached-pointer pass has never been measured** — but its whole exposure is 211 unread fields
   in 3 objects (`ball` 11, `throughpass` 82, `basePosition` 118), the only objects whose `get()`
   pointer is ever stored. It needs a memory-bounded rerun (cap events per function, or one K at a
   time) before anyone can say whether any of those 211 is reached through a heap-cached pointer.
   `K=0x8` (36,099 candidates) and `K=0x38` (46,813) are over the 6,000 limit, so **the current tool
   cannot close `ball` or `throughpass` even on a successful run** — only `basePosition`'s `K=0xf0`.
5. **Who writes `[matchEnv+0x3c]` and `[matchEnv+0x40]`?** Pinning it turns the 106 family-level
   objects into per-object bindings and would say exactly which `demoarea` / `ballPerson` entry a given
   stadium selects. Suggested route: the constructor of `[[0x1486bd888]+0x630]`, looking for a call
   into `0x145348e50` or a helper shaped like `0x144309470`.
6. **Correlated-branch inertness is unmeasurable at scale.** A path-sensitive detector — same
   predicate tested twice, register overwritten on exactly the branch that loaded it — would turn this
   project's two anecdotes into a number over all 11,998 read fields.
7. **Does the `demoarea` bounding box constrain anything a player does**, or only where an animation
   may roam? `CornerKickLoop` is a set-piece class, and that is the one place a "presentation only"
   verdict could be wrong.
8. **How many other static (id → index) tables exist?** Three were found by following their resolver
   functions. A systematic sweep for the linear-search helper shape
   (`cmp dword[rax],ecx / add rax,8 / mov eax,DEFAULT ; ret`) would enumerate them all, and is the
   cheapest permanent fix for the tool.
9. **Nothing here was verified in-game** (analysis-only run). Every claim is static: disassembly of
   `eFootball.exe.PRISTINE` plus the decoded pack in `build/dt270_json`.

---

## What is left of dt270

**No *new* gameplay mechanic, and no new tunable gameplay surface.** The **routing** map is closed:
245 objects, 21,977 fields, 234 objects bound to a fetch route and 11 unbound [b]. The tunable dt270
surface for gameplay was already found by the subsystem chapters — `passget`, `basePosition`, `trap`,
`moveMatching`, `grounderpass`, `throughpass`, the kick families and `positionPK` — and this pass
added none. What it added instead is the reason the number was large: **`unlocated` was never a
liveness verdict** [b], only a statement that an index was not a compile-time constant, and 98.2 % of
it was tutorial drills, mode chapters, stadium dressing and a touchline camera rig [a].

**"Closed" means routed, not measured.** Only route A's 16,429 fields were ever put through the
pointer flow; **5,548 of the 21,977 have never had their liveness computed at all** [a]. Nothing here
says those fields are dead — it says where the game fetches the objects they belong to.

The catalogue is trustworthy for what it measures, and now has error bars. `unread` survived a
*within-function* completeness audit with zero overturns out of 199 hand-traced fields — a real
result with a narrow universe (§ `unread`) — and ~97.1 % of the corrected 4,431 unread fields sit in
objects where nothing escaped the analysis [a]. `read` means "a load of the right field happens", not
"the value matters" — 96.9 % of read fields are plain loads [a], and correlated-branch inertness is
real but rare [b]. `cached: 0` is unmeasured, not zero, with a bounded exposure of 211 fields in 3
objects [a]. And seven objects the catalogue calls located are contaminated by one bad seed, four of
them fatally: **subtract 10 reads and 178 unreads, and move `centering` +0x10 / +0x14 into `unread`,
before quoting its headline** [a + b].

**Two standing holes, in one line.** 5,548 fields are bound but never measured; the cached-pointer
pass has never been run and its two largest K values cannot be run by the current tool.

Two things are worth a follow-up and neither is a tuning job: **`ballplayer`**, a gameplay-shaped turn
table nothing appears to fetch, and **the live user-play-tendency model**, which `userPlayTendencyTest`
names but does not contain. Everything else in the residue is a developer's soak-test rig, a mode
launcher, or the furniture around the pitch.
