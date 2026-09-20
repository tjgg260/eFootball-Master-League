# Gameplay Modding Guide

A synthesis of everything this project currently knows about modding eFootball 2027's *gameplay* —
as opposed to its roster/squad data, which is the Master League app's own domain. This document
compiles and cross-references the existing decode chapters under `docs/`; it does not re-derive or
guess anything new. Every claim below traces back to one of the source chapters named in its
section, and every caveat, correction and "do not do this" from those chapters is preserved. Where
sources disagree or a question is still open, that is stated explicitly rather than smoothed over —
this project has been burned before by treating half-verified findings as settled fact.

Source chapters compiled here: `docs/dt270-gameplay.md`, `docs/dt270-fields.md`,
`docs/dt270-residue.md`, `docs/exe-gameplay-map.md`, `docs/exe-gameplay-full.md`,
`docs/match-ai-decoded.md`, `docs/player-executors.md`, `docs/ball-carrier-brain.md`,
`docs/goalkeeper.md`, `docs/goalkeeping.md`, `docs/set-pieces.md`, `docs/pad-input.md`,
`docs/pad-node-kinds-and-unit-modes.md`, `docs/pad-power-and-cursor.md`,
`docs/registry-blackboard.md`, `docs/registry-pad-command-channel.md`, `docs/anime-actions.md`,
`docs/anime-keeper-and-first-touch.md`, `docs/control-source-and-human-vs-cpu.md`,
`docs/realism-audit.md`, `docs/realism-todo.md`, `docs/catalogue-notes.md`.

---

## 1. Overview

eFootball's gameplay lives in two moddable surfaces, and they are not symmetric:

| Surface | What it is | How big | How you change it | Risk |
|---|---|---|---|---|
| **dt270** (`dt270_console_all.cpk → common/match/constant/*.bin`) | The engine's own **data**: team-shape AI, ball physics, kick gauges, first-touch behaviour, pass models, locomotion, ratings, camera, set-piece guide targets, etc. | 12 files, 245 objects, ~30,000 named leaf parameters (~112,336 counting every stadium/tutorial/mode object) | `tools/gameplay_tune.py` / `tools/dt270_objects.py` — edit by real Konami field name, re-pack into the CPK | None — data only, reversible, survives Konami patches |
| **eFootball.exe** | The engine's **code and inline constants**: kick error model, CPU difficulty tables, AI decision selectors, executors, animation cancel gates, pad input | 352 MB, RTTI intact, 221+ levers catalogued across 14+ subsystems | `tools/exe_patch.py` (on-disk hex), `tools/live_patch.py` (runtime), or code caves via `tools/cave_scan.py` / `tools/cave_alloc.py` | Denuvo may reject a modified exe; see § 3 for the current, corrected policy |

**How they relate.** dt270 supplies *parameters* the engine's code reads (ball drag, defensive
line height, shot gauge tables, first-touch reaction...). The exe supplies *everything dt270 has no
field for* — the kick error/accuracy model, the CPU difficulty ladder, the off-ball AI's scoring
formulas, the animation cancel/lockout rules, the pad's tap/hold discrimination. Neither surface is
optional: `docs/exe-gameplay-map.md` states plainly that "no dt270 constant feeds the kick error"
and that CPU difficulty "is NOT driven by dt270 JSON constants; it is hard-coded in the exe as a
44-row x 10-column float table." Conversely, most of what "shape and feel" means — defensive line,
ball drag, pass assist, first-touch looseness — is dt270 data with no exe patch required.

**The golden rule, and how it applies here.** The project's core architecture decision
(`CLAUDE.md`) is that the app's SQLite database is the single source of truth for *squad and
career* data — the game's own files are a render target, never read back as authority. **Gameplay
tuning has no such database.** There is no SQLite equivalent for "how far the defensive line sits"
or "how much kick error exists" — dt270 and the exe *are* the target for that domain, and the
project's tuning packs (`tools/data/tunings/*.json`, `tools/data/patches/*.json`) are the closest
thing to a source of truth for what is currently applied. Treat those pack files, not "what looks
right in a match," as the record of intent, and always verify what is actually installed rather
than assuming a pack applied earlier is still in effect (see § 8 on the exe/dt270 install-state
trap the catalogue tool had to fix).

**Read the mandatory sections first.** `docs/match-ai-decoded.md` opens with: "Read § Corrections
... and § Refuted ... before proposing any off-ball change. Between them they cover roughly a year
of misdirected tuning." Every other chapter that inherits from it repeats the instruction. This
guide reproduces both sections in full in § 4 below — do not skip them.

---

## 2. dt270 gameplay constants

### 2.1 What it is, and where it lives

The gameplay "feel" of eFootball lives in `dt270_console_all.cpk → common/match/constant/*.bin`, a
separate pack from the dt200 roster data (a gameplay mod and the Master League roster/tactics
writeback coexist without conflict). As of 2026-08-23 every byte of it is understood and every
parameter is addressable **by its real Konami field name**.

An earlier theory — "Q2.14 fixed-point multiplier tables", "word 131 is tempo", "sentinel ±52428
values" — was wrong and is dead. The tables are ordinary IEEE floats / int32 / bools in a structured
compiled-JSON object format; nothing from the old word-index probes should be trusted, and the
per-patch "calibration" approach it implied is obsolete.

### 2.2 Format

```
constant_*.bin   WESYS container: 16-byte header, then PLAIN zlib (level 9 reproduces Konami's
                 bytes exactly — no encryption, whatever the header byte claims)
  payload        PACK: u32 count, u32 8, count × { u32 data_off, u32 data_size, u32 name_off },
                 then NUL-terminated names "<object>.o", then the object blobs
  object (.o)    compiled JSON document (the exe still lists the source paths, e.g.
                 DevelopData/common/match/constant/match/rating.json):
                   record   = fields in the loader's key order, C-like natural alignment
                   float/int = 4 bytes inline, bool = 1 byte inline (packed)
                   nested object / array / string = u32 OFFSET (from object start) to a block
                   array block = N inline elements (scalars, or inline records)
                   strings = NUL-terminated, deduplicated
                   blocks are emitted depth-first (children before parent), 16-byte aligned
```

12 files, 245 objects, 36 object types, ~30,000 named leaf parameters. `ballplayer.o` alone
(75 KB) is 18,772 of them — turn/touch motion-matching tables (see § 2.6, this object is
NOT-SAFELY-TUNABLE, its fetch path is unresolved).

### 2.3 How the field names were recovered — and how to redo it after a Konami patch

The `.o` blobs carry no names, but `eFootball.exe` does: every object type has a **JSON loader**
(dev path — walks keys by name with JsonCpp) and a **binary loader** (release path — copies `.o`
bytes into the same C++ struct), both reachable from a registration table `{json path, factory}` →
factory → vtable `[dtor, loadJson, loadBin]`.

`tools/dt270_schema_gen.py` finds all of that by shape (no hard-coded addresses) and **emulates
both loaders with Unicorn**: the JSON loader against a synthetic DOM whose accessors return
sentinels (→ key path ↦ struct offset + type), the binary loader on the real `.o` bytes (→ struct
offset ↦ `.o` offset, pointer slots, array strides). The join is the schema
(`tools/data/dt270_schema.json`), validated by a pure-Python reader against every object in the
installed pack (245/245 byte-exact). **Re-run it after each Konami patch** — about 40 seconds, needs
`pip install capstone unicorn`.

Known Konami data quirk: `PathToGlory10/12.playerData` has 40 emitted elements but the loader reads
88 — the game reads garbage past the object's end there. The reader caps arrays to the emitted
count and refuses to write beyond it.

### 2.4 Tool chain

```bash
python tools/dt270_objects.py list                          # files / objects / types
python tools/dt270_objects.py fields basePosition --depth 2 # browse a field tree
python tools/dt270_objects.py get ball magnusRate            # read by dotted path
python tools/dt270_objects.py dump --out build/dt270_json    # every object -> JSON
python tools/dt270_objects.py verify                         # byte-exact round-trip gate
python tools/dt270_objects.py catalogue                      # field catalogue -> dt270-fields.md source

python tools/gameplay_tune.py get shoot normalShootGageMax99
python tools/gameplay_tune.py set ball magnusRate=0.05 basePosition.dfLine=12   # edit + install
python tools/gameplay_tune.py apply my_tuning.json           # batch of {object,path,value}
python tools/gameplay_tune.py scale --object ball --factor 0.9 --match bound    # float probe
python tools/gameplay_tune.py diff                           # installed vs pristine, by name
python tools/gameplay_tune.py restore

python tools/dt270_liveness.py build --exe <image> --no-cache-pass   # per-field liveness catalogue
```

**Write path (unchanged rules).** Edits are made in place inside the object — no size change, no
block moves. The edited `constant_*.bin` is re-deflated and dropped into its original CPK slot
(zero-padded); every other byte of the CPK stays untouched; the round trip is re-decoded before
install. Small files have little slack (`constant_match.bin`'s slot is 2,582 bytes); if level-9 zlib
no longer fits, `encode_constant` falls back to zopfli (~4% smaller, standard deflate — needs
`pip install zopfli`). Strings may only be replaced by same-or-shorter strings.

**In-game verification status (as of the 2026-08-23 decode):** the patched CPK is proven
structurally (reloads through the CPK parser, edits read back, byte-identical entries). Any first
`set` after a long idle period should still be treated as a live test — keep it to one obvious
parameter and `restore` afterwards until you have re-confirmed it in-game.

### 2.5 The field catalogue

`docs/dt270-fields.md` is generated by `python tools/dt270_objects.py catalogue` from the schema.
It lists every object's field tree to depth 2 for all 245 objects (112,336 leaf parameters total).
The gameplay-relevant object families, by category:

| object(s) | leaf params | category |
|---|---|---|
| `basePosition` | 220 | **team shape AI**: `dfLine`, `dfLineWidth_3/4/5`, `adjustDefenceLine_Retreat/ForeCheck`, `closeRate_DF_FW`, `forceDashDistDefence/Offence`, `defenceCompact`, `attackLevel`, corner/free-kick/goal-kick shapes (`gkl*`, `cornerKick*`, `freekick*`) |
| `ball` | 186 | **ball physics**: `magnusRate`, `curve`, `airRegistNormal`, `boundRate[6]`, `frictionRoll*[6]`, `dragSpeedMin/Max`, top/back/non-spin decay, `grounderSpeed` (the `[6]` arrays are per pitch condition) |
| `shoot` | 124 | **shot power/height gauges** (km/h): `normal/control/powerfullShootGage{Min,Mid,Max}{40,99}[6]` — `[6]` = 5 m distance-to-goal band, 40/99 = attribute; `*_dy` = launch-elevation curve (°); `loop`, `advanceLoop` |
| `trap` | 126 | **first touch**: `ballControlRate`, `reachOut`, `reactionTrapBall`, `defenseTrap`, `busyTrapControl`, cancel/blend frames, `trapLoss` |
| `grounderpass` / `flypass` / `throughpass` / `centering` | 46–118 | **pass models**: `receiveSpeed[6]`, `passAssistLevel`, `angleY`, `lob`, manual-blend gauges, search/selection |
| `passget` | 56 | **receiving & interception**: `manualPassGetRate`, `naturalPassget`, `defence`, `inputMove*`, `trapStopThink*` |
| `moveMatching` | 220 | **locomotion**: `RouteParameter[14].{acc, dec, rotSpeed, decRotSpeed, accRateDif60/120/180}` + animation `WeightParameter[3]` |
| `ballplayer` | 18,772 | dribble turn/touch motion-matching tables (`TurnData[1440]`, `touch0[7]`) + `Feint.rate` — **NOT-SAFELY-TUNABLE**, see § 2.6 |
| `rating` | 133 | **match-rating formula**: `coef_*[10]` per action, `addPoint.*` bonuses, `df/mf/fw/gk_rate`, `ratingMin/Max` |
| `cameraInplay` | 60 | in-play camera: move area, margins, `newWideCamera`, drop-point display |
| `positionNone`, `positionPK_2..5` | 88 | **penalty shoot-out positioning** — live, decoded end to end (§ 5.4, set pieces) |
| `ballPersonData`, `ball_person_st###` (73), `demoarea_*` (102), `animeAging*`, `userPlayTendencyTest`, `mlScreenShot` | ~4,300 | stadium dressing, camera/mic rigs, developer test harnesses, dead capture tooling — **not gameplay**, see § 2.7 |
| `PathToGlory*`, `Sugoroku*`, `tutorial*` | ~3,000 | training-mode scenarios — mode-only, not the main match |

Player **attributes** (speed, stats, ability) are NOT here — they are dt200 (roster) data; dt270 is
the engine's *behaviour model* that those attributes feed into.

**Version families.** `constant_match.bin` decoded size fingerprints the exe build a pack targets
(10622 = v6-era mods, 11904/11912 = GabeLogan/Bromi builds, 9968 = the installed game as of the
2026-08-23 decode). The reason is structural: the C++ structs change between patches, so old packs'
objects have different field sets. The legacy `install --mod` path still refuses family mismatches;
**named edits are patch-proof** — after a Konami update, re-run `dt270_schema_gen.py` and re-apply
your `tuning.json`.

### 2.6 The residue pass — closing the constant map (2026-09-20)

`docs/dt270-residue.md` is a dedicated pass that classified all 245 objects / 21,977 fields by *how
the game fetches the object they belong to*, resolving the ~5,362 fields the original liveness
catalogue called "unlocated." This is the single most important correction chapter for anyone
about to trust the dt270 liveness catalogue, and its headline needs to be stated precisely — earlier
drafts of the chapter itself got the headline wrong twice (see its own § Corrections):

- **`unlocated` never meant "dead."** It meant only that the `get()` call site's index was not a
  compile-time constant the tool's simple pattern could see. After this pass, **5,265 of the 5,362
  unlocated fields (98.2%) are now bound to a fetch route** — a name table, a static (modeId→index)
  table, or an index cached in a runtime object member. The other 97 are truly unbound (§ below).
- **"Bound" is not "measured."** Only the original constant-index route (16,429 of 21,977 fields,
  74.8%) was ever put through the tool's actual pointer-flow liveness check. **5,548 fields have
  never had their liveness computed at all** — binding an index to an object is not the same as
  seeding the pointer flow and re-running it. Nothing in the residue chapter should be read as "these
  fields are dead"; for the newly-bound routes the honest status is *unmeasured*.
- **Of the ~115 fields the project's plan had reserved as "genuine gameplay residue," none turned
  out to be a *new* mechanic.** `animeAging{Kick,Trap,Dribble,FreeMove}` (47 fields) is a developer
  QA soak-test rig with no fetch site anywhere — nothing to tune. `userPlayTendencyTest` (22 fields,
  a real 21-category weighted taxonomy of "how the user plays") has no fetch site either — whether a
  live counterpart of this model exists elsewhere is **NOT PROVEN, in either direction**.
  `studiumPositionData` / `demoarea_*` (102+ objects) are stadium dressing, bound and read by
  `match::anime::action`, but that binding constrains *animation placement*, not confirmed to
  constrain where players stand. `positionPK_2..5` / `positionNone` (20+4 fields) are a **live
  gameplay lever** — but they were already decoded and owned by `docs/set-pieces.md`; the residue
  pass only re-verified the chain and corrected the resolver address (§ 5.4).
- **One object is genuinely unresolved and worth follow-up: `ballplayer`.** Its `TurnData[1440]` +
  `touch0[7]` + `Feint` tables are exactly the richest dribble-turn/first-touch surface in the whole
  pack, and it looks like exactly what a realism mod would want. **It has no sound fetch site.** Its
  only listed `get()` call site provably produces the index for `grounderpass`, not for `ballplayer`
  — a tool defect (the `0x143fef479` defect, see below) that misattributed reads. **Do not tune it,
  and do not trust an observed in-game effect if you do** — an effect would mean a sixth,
  undiscovered fetch mechanism exists.
- **The `0x143fef479` defect.** One `get()` call site's index was widened by the liveness tool's
  emulator into an incorrect range across 8 objects (`0x64..0x6b`). Manual re-derivation from the
  bytes shows the true index is `0x6a` (`grounderpass`) only; `PathToGlory9`, `pathToGloryNone`,
  `pathToGlorySetting` and `ballplayer` are **fully withdrawn** from "located" status (they have no
  other fetch site), and `centering.adjustGageFarZ`/`adjustGageNearZ` flip from `read` to `unread`
  because their only cited reader was this misattribution. Corrected totals: **101 objects located
  by constant index, 11,998 genuine `read` fields, 4,431 genuine `unread` fields** (of which 4,302 at
  high confidence, 129 at reduced confidence).
- **`cached: 0` in the liveness catalogue is not a finding — the cached-pointer pass was never run.**
  It reaches 21 GB resident and dies with `MemoryError` on a real attempt. Its whole exposure is
  bounded: only **3 objects in the entire catalogue ever have their `get()` pointer stored anywhere**
  (`ball`, `throughpass`, `basePosition`), so at most 211 `unread` fields could ever be reclassified
  by that route, and the other 4,396 unread fields are not exposed to it at all.
- **`read` does not mean "the value matters."** Only about 3% of `read` fields are consumed by an
  instruction that actually uses the value (a `subss`/`cmp`/`mulss`/etc.); the other ~97% are reached
  only by a plain load. Correlated-branch inertness is real: `basePosition.forceDashDistDefence` is
  loaded on one path and then, on a *different* branch of the same flag test, silently overwritten
  before its only compare — so it reads as "touched" but is dead in practice, while
  `forceDashDistOffence` is fully live. This shape is **not detectable by any automated dead-load
  scan built so far** (see § 4's Corrections table — this exact finding recurs there too).
- **`confidence: low` in the catalogue is almost always a false alarm**, not doubt. 828 of 835
  low-confidence `read` fields are `movsd` packed loads of two adjacent floats (a genuine read of
  both fields at once) — including `basePosition.dfLine`, whose declared `int` type and byte-width
  read trip a width-mismatch flag while the value is genuinely, correctly consumed.

**Practical upshot for a modder:** the tunable dt270 gameplay surface was already found by the
subsystem chapters before this pass — `passget`, `basePosition`, `trap`, `moveMatching`,
`grounderpass`, `throughpass`, the kick families and `positionPK`. The residue pass added **no new
tunable field**; what it added was closing out where the other ~98% of the catalogue's "unlocated"
fields actually come from (tutorial drills, PathToGlory chapters, Sugoroku, stadium dressing, camera
rigs), so nobody keeps re-investigating them hoping for a hidden lever.

### 2.7 Rules

- **Edit in place only.** No size change, no block moves.
- **Verify byte-exact** before trusting a write: `tools/dt270_objects.py verify` must pass 245/245.
- **zlib level 9, with zopfli fallback** for tight slots.
- **Re-run `dt270_schema_gen.py` after every Konami patch** — field offsets and struct layouts move
  with the build.
- **Do not treat `unlocated` as "safe to ignore" or "safe to tune."** It means "no compile-time
  index found," nothing about whether the field does anything if it *is* fetched by some other
  route.
- **Do not tune `ballplayer`.** No proven fetch path exists; treat any observed in-game effect from
  editing it as unexplained, and open a fresh probe rather than trusting it.

---

## 3. eFootball.exe modding

### 3.1 Scope of the RTTI map

Static reverse-engineering map of `eFootball.exe` (352 MB, MSVC x64, **RTTI intact**, Denuvo
Anti-Tamper; no anti-cheat module shipped). Produced over `tools/exe_map.py` (RTTI → vftables →
**64,158 virtual methods**, disassembly, xrefs), with **5,791 classes total, 782 in the `match::`
namespace**. All addresses are virtual addresses at the preferred base `0x140000000` — the PE has no
dynamic-base flag, so RVA == VA in the common case; `tools/live_patch.py probe` verifies the runtime
base and slide regardless.

**The baseline is not quite "stock."** `eFootball.exe.PRISTINE` (the project's reference image)
differs from the genuinely untouched Konami binary (`eFootballonlinevanilla.exe`) by exactly 2
bytes: a hostname edit (`pes22-game.cs.konami.net` → `pes99-`) at `0x146e6fae3` that severs
matchmaking but touches no gameplay code and no chapter's claim. When a truly clean reference is
needed, use `eFootballonlinevanilla.exe`, not PRISTINE — and never call PRISTINE "stock" in a
write-up.

### 3.2 `tools/exe_map.py` capabilities

```bash
python tools/exe_map.py build                       # RTTI -> vftables -> methods (build/exe_map.json)
python tools/exe_map.py grep 'ActionSelector'        # find classes
python tools/exe_map.py class ActionSelectorScore    # vftable + methods
python tools/exe_map.py disasm 0x14401a900           # annotated disassembly
python tools/exe_map.py xrefs 0x144345eb0            # callers (slow)
python tools/exe_census.py cell <va> --all           # census a constant cell's sharers
python tools/exe_funcs_chained.py                    # function extents via chained-unwind .pdata walk
```

### 3.3 Key decoded landmarks

**Kick error / accuracy model — fully in the exe, no dt270 field feeds it.** A single kick-execution
function `0x144016a70` converts the intended kick velocity into `(angleXZ, angleY, speed)`, calls
`0x14401a900` to build a 0x3c-byte "kick miss parameter" struct (per-axis max error, sign
probability, Gaussian sigma, miss type), then applies the deviation with one of three randomizers.
The kick miss-parameter builder computes:

```
angleXZ error max = (1 − combinedFactor) × 22.5°
angleY  error max = (1 − combinedFactor) × 22.5°
speed   error rate = (1 − combinedFactor) × 30%
Gaussian sigma     = max(0.1, 0.75 + 4.25 × signProb × (1 − combinedFactor))
```

Player ability enters via `0x143ed71d0 → 0x143ed7440`: effective ability is the SHOT/SHORT_PASS/
LONG_PASS/HEADING attribute byte (plus skill-card bonuses, minus a weak-foot penalty when the
kicking foot isn't the stronger foot), piecewise-mapped to a 0..1 factor (`<60: 0..0.1`,
`60–90: 0.1..0.9`, `>90: 0.9..1.0`). Randomness comes from an LCG `RandInt` at `0x144345e00`
(`seed = (0x4513 − seed*0x2d22b2e3) & 0x7fffffff`) and a Box-Muller Gaussian at `0x144345eb0`.
`docs/exe-gameplay-map.md` names the best runtime-patch lever as the two `22.5f` multiplies in
`0x14401a900` (repoint the disp32 read of the shared `.tls$` constant to a different existing float
cell — do not edit the shared `22.5f` cell itself, it has dozens of unrelated referrers), or the
`4.25f` sigma scale at `0x146b3cfb0` (only 4 xrefs).

**CPU difficulty (match level) — a 44-row × 10-column exe table, not dt270 data.**
`AiLevelUnit::GetParam` (`0x1442e48f0`) is the single chokepoint: it reads the level table (default
`0x146c06f40` on PC — table B, platform-class 3), each of 44 rows a per-mechanism parameter, each of
10 columns a difficulty level from BEGINNER through LEGEND (plus half-step "sub-level" interpolation
between adjacent columns). Levels: BEGINNER=0, AMATEUR=1, REGULAR=2, PROFESSIONAL=3, TOPPLAYER=4,
SUPERSTAR=5, and a hidden **LEGEND=6** that exists at runtime (menu enum `EMenuCpuLevel` has 7
entries) though it is not normally selectable. The runtime level is stored as an XOR-obfuscated
12-byte `AiLevelUnit {enc, key, sub}` reachable from `[0x1486bd888]+0x528`; the simplest robust
patch is writing plain integers into the tmpdb match record (`TmpDbMatch+0x94/+0x98/+0x9c/+0xa0`)
before kickoff — everything downstream derives from those plain ints. `docs/exe-gameplay-map.md`
gives per-row semantics for as many of the 44 rows as have been traced to a consumer (reaction-delay
frames, press-timing multipliers, probabilities, distance/time offsets, and boolean "ability
enabled" flag rows).

**`ConstantManager`.** `0x148c22b98` → `get(idx)` at `0x145348d70` is the single chokepoint for
every dt270 object fetch — see § 2.6's "the map in one paragraph" for the full routing picture
(constant index, name table, static mode tables, cached runtime index, name-supplied-by-data). The
kick error model and the CPU difficulty tables are proven to make **zero** calls into this path —
confirmed as a negative result in `docs/exe-gameplay-map.md`.

### 3.4 The Denuvo constraint — CORRECTED, and where the discrepancy lives

This is the single point where the project's own documentation openly disagrees with itself across
chapters, and this guide surfaces that rather than picking a side silently (see also § 8).

- **The original framing** (as written into `docs/exe-gameplay-map.md`'s early sections and once
  echoed in `CLAUDE.md`) was: *"exe on disk is sacred; every patch is an in-memory write."*
  `tools/live_patch.py` (external-process ReadProcessMemory/WriteProcessMemory, no injection, no
  Cheat Engine) was built as the only sanctioned write path, gated behind
  `--i-understand-denuvo`, with `probe`/`info` read-only by default and writes journaled for
  `restore`.
- **That framing was directly contradicted by the installed image itself, and the correction is
  dated 2026-09-19.** A byte diff of the installed exe against `eFootball.exe.PRISTINE` found **909
  differing bytes in 105 contiguous runs** at an unchanged file size — this project had already been
  shipping on-disk code patches (via `tools/exe_patch.py`) for some time, and the game ran with them
  without the feared integrity trip being observed.
- **Owner ruling, 2026-09-19, quoted verbatim in `docs/exe-gameplay-map.md`:** *"I don't mind
  changing the exe"* — **on-disk patching is now the default route, not a last resort.**
  `tools/live_patch.py` remains available for cases where a runtime-only write is genuinely
  preferable (e.g. testing something before committing to a persistent on-disk change).
- **What the ruling does NOT change: the physical limits.** Permission was never the binding
  constraint on the code-cave allocator's limits (§ 3.6) or on Denuvo's actual integrity-CRC
  behaviour under a code-page write — those are still real risks, just no longer *disqualifying*
  ones by owner decision.
- **`tools/exe_patch.py`** is the on-disk tool: first apply copies a byte-exact pristine exe to a
  backup location and records its sha1; `restore` puts it back; a patch writes only if every
  `expect` byte still matches (so a spec built for another game version cannot corrupt anything);
  `status`/`diff` show what is currently applied. **Steam's "verify integrity of game files" reverts
  the exe** — keep the game closed while patching, and re-apply after any verify.
- **Named discrepancy for § 8:** several chapters written *before* 2026-09-19 (and portions of older
  guidance) still describe on-disk exe patching as forbidden or last-resort. Treat any pre-2026-09-19
  statement to that effect as **superseded** by the owner ruling; anything written after that date,
  including this guide, treats on-disk patching as the default and `live_patch.py` as the
  alternative for cases that call for a live-only test.

Practical constraints that remain regardless of the ruling:

- `.xcode` (plaintext, holds all `match::` code) is where every gameplay function lives; `.impdata`
  (183 MB) is the Denuvo blob and holds no gameplay code — never patch there.
- Many float constants are **shared `.tls$` cells** (e.g. `0.5f`, `22.5f`) referenced from hundreds
  or thousands of call sites. **Never change the cell's value directly.** Change the instruction's
  `disp32` operand to point at a *different* existing cell with the wanted value (or allocate a
  private cell), so only the one intended read site changes.
- Denuvo's anti-tamper/anti-debug import surface (`VirtualProtect`, `IsDebuggerPresent`,
  `AddVectoredExceptionHandler`, `NtProtectVirtualMemory`, etc.) is present and the real integrity
  checks are virtualized inside the 183 MB `.impdata` blob — not statically enumerable as a fixed
  "CRC over section X" function. Data-page writes are the safer first test; code-page writes may
  trip an integrity CRC and crash (offline, no ban observed).

### 3.5 `tools/live_patch.py` — runtime patch path

```bash
python tools/live_patch.py probe                                   # READ-ONLY attach + relocation proof
python tools/live_patch.py info                                    # pid/base/slide + Denuvo survey
python tools/live_patch.py apply spec.json --i-understand-denuvo   # journaled in-memory patch
python tools/live_patch.py restore                                  # undo from journal
python tools/live_patch.py wait                                     # poll for launch, optional auto-apply
```

`probe` reads a live qword at a known vtable slot and asserts it equals the expected method address,
proving attach and relocation for any ASLR slide before any write is attempted — **run it before any
write, every session.** A mismatch means the map is stale or memory is masked; do not patch. Writes
are `VirtualProtectEx(PAGE_EXECUTE_READWRITE) → WriteProcessMemory → FlushInstructionCache → restore
original protection`, and every applied byte is journaled so `restore` can reverse it while the
process still lives. **Cheat Engine is explicitly blocked by this build's anti-cheat surface; plain
external `ReadProcessMemory` works (proven, used throughout this project's read-only tooling);
`WriteProcessMemory` is untested against the live game** — treat every code write as "may crash," and
validate empirically with a small, reversible data write first, watching for a delayed crash that
would indicate a periodic integrity sweep rather than a load-time-only check.

### 3.6 The code-cave allocator — new code, not just byte edits

`tools/cave_scan.py scan` → `build/caves.json` finds usable padding; `tools/cave_alloc.py` chains a
payload across many small `int3` runs (each ending in a 5-byte `jmp rel32`) and emits an ordinary
`exe_patch` spec whose every chunk carries the original `0xCC` bytes as its `expect`, so `remove`
restores padding byte-exactly. `tools/cave_alloc_test.py` is the verification suite.

**The safety oracle is `.pdata`** — the EXCEPTION directory *is* the whole `.trace` section:
410,113 `RUNTIME_FUNCTION` entries merging to 253,886 ranges covering 84.3% of `.xcode`. A run that
starts exactly at one function's `EndAddress` and ends exactly at the next's 16-byte-aligned
`BeginAddress` is provably padding, not misread code.

| | value |
|---|---|
| int3 runs in `.xcode` | 547,254 (3,101,315 bytes) |
| inside a `RUNTIME_FUNCTION` (rejected) | 106,874 |
| **tier-A pool** | **97,590 caves / 553,583 payload bytes** |
| largest tier-A cave | **21 bytes** (mean 10.67) |
| tier-A caves ≥ 24 bytes | **zero** |
| in the match band (`0x143000000`–`0x144800000`) | 24,290 caves / 133,021 payload bytes |

MSVC aligns function entries to 16, so genuine inter-function padding caps at 15 bytes. Chaining
is mandatory for any payload over ~16 bytes; a 70-byte payload needs 8–10 chunks. A 5-byte
`jmp rel32` reaches anywhere in `.xcode`. The pool is **edit-invariant** — scanning PRISTINE yields
the same 97,590 VAs and lengths, so specs allocate to the same addresses against either image — but
**re-scan after every Konami patch**, since chunk addresses move with the build.

**Known constraint:** cave code is covered by no `RUNTIME_FUNCTION`, so it is **unwind-hostile** — a
`call` from inside a cave puts a return address the OS cannot resolve on the live stack. Survivable
for code that never faults, but a conscious choice, not a free lunch.

**Open allocator defects** (found by adversarial review, not yet fixed): `verify_layout` falsely
passes when a chain jump collapses to `rel8` and leaves a `nop` as the last decoded instruction;
`hook_patch` has no reference gate and no upper bound on `stolen_len`; `cave_pool` declares a
`pristine` parameter it never reads, so call sites read as a two-image gate that does not exist; a
spec cannot be regenerated at the same addresses.

### 3.7 Top exe levers (ranked, cross-subsystem, from the 2026-08-23 full sweep)

`docs/exe-gameplay-full.md` is a whole-`match::`-surface sweep (14 subsystems, 221 levers,
parallel-agent mapped and spot-checked). Its top-ranked levers, condensed:

| # | lever | address | area | conf |
|--:|---|---|---|---|
| 1 | CPU difficulty table `GetParam` / whole-column overwrite | `0x1442e48f0` (fn) / `0x146c06f40` (table) | difficulty | proven |
| 2 | Row 18 — attacking action commit probability (30% Beginner → 100% Superstar+) | `0x143e12c68` | cpu-attacking | proven |
| 3 | Attribute normalization range table A | `0x146c00860` | attribute-model | proven |
| 4 | Shot-range gate (38 m squared) | `0x143e0ef1d` | cpu-attacking | proven |
| 5 | Shot aim-scatter sigma base + CPU-level curve | `0x1441b534f` / `0x1441b532d` | shooting | proven |
| 6 | Gaussian sigma global divisor | `0x146c35734` | rng | proven |
| 7 | Card/booking probability roll (30%) | `0x143c84d2e` | fouls | proven |
| 8 | km/h → per-frame displacement divisor (1000f) | `0x143c65890` / `0x145a8dd88` | locomotion | proven |
| 9 | Collision post-contact speed clamp (35 km/h) | `0x146b946b4` / `0x146b7c2d4` | ball physics | proven |
| 10 | LCG multiplier / seed base | `0x144345e13` / `0x144345e08` | rng | proven |
| 11 | Platform-class global (table A/B + AI tick rate) | `0x148c22ab8` | rng/difficulty | proven |
| 12 | `basePosition.lineControl` / `adjustGapDfLine` | dt270 idx `0xe2` +0x234/+0x40 | cpu-defending | proven — **CPK-editable, no Denuvo risk** |

Subsystem coverage as of that sweep: 8 of 14 well-mapped (cpu-attacking, cpu-defending,
shooting-behaviour, physical-locomotion, defending-tackle-foul, ball-physics-exe, rng-and-globals,
difficulty-rows, attribute-model), 6 partial (goalkeeper, passing-behaviour, dribbling-skills,
stamina-condition, set-pieces). The later subsystem chapters (player-executors, ball-carrier-brain,
goalkeeper, goalkeeping, set-pieces, pad, registry, anime) substantially deepen several of the
"partial" areas — see § 5.

---

## 4. Match AI decode

`docs/match-ai-decoded.md` is the decode of the off-ball attacking AI: the selector/job-board
model, the score formulas, attack-level quotas, playing styles, the contact lockout, and the
code-cave allocator (already covered in § 3.6). Produced by four multi-agent workflows (26 agents,
~7.7M subagent tokens) with every numeric claim emulated against both the installed image and
PRISTINE unless marked otherwise.

> **This section's Corrections and Refuted tables (§ 4.6–4.7) are mandatory reading before
> proposing any off-ball or defensive-shape change.** They are reproduced here in full, not
> summarized, per the source chapter's own instruction and per this project's standing rule.

### 4.1 The selector / job-board model

`match::ai::ActionSelectorManager::update` (`0x143d52470`) has exactly one caller, with **no
human/CPU test** — it drives the CPU team and the human's ten AI team-mates identically. Its guard
is frame parity (`[match+0x3318] & 1`), **not** a possession flag — an earlier project note read
this wrong. Each team re-decides all of its off-ball movement on alternate frames (~30 Hz at 60
fps).

Each player holds exactly one action id at a time, so a selector earlier in the bidding order takes
a player and every later selector never sees him. Bidding order (a-emulated, corrects an earlier
note that had CenteringGet and PullAway ahead of GoalGet and PostPlay):

```
Overlap > ChanceSpaceRun > CounterSpaceRun > SecondLineSpaceRun
  > LineBreak > DiagonalRun > GoalGet > PostPlay
  > PullAway > CenteringGet
```

Per selector, the shared dispatcher (`0x143df1080`) builds an 11-bit eligibility mask, computes a
run-target vector and a **score** for each eligible slot, sorts descending, and hands out slots
top-down — stopping at the first score `≤ 0` and at `min(quota, maxSlots)`. **`score == 0.0` is the
"not a candidate" sentinel** — any modification to the score must never lift a 0.0 above zero or
push a legitimate candidate to ≤0, or it will silently truncate every lower-ranked runner that
frame.

### 4.2 The scores — the root cause of "the AI always does the same thing"

```
ChanceSpaceRun::vf5  :  score = 100.0 + attackDir * player.x + roleBonus
DiagonalRun::vf5     :  score = (opponentLineX - player.x) * attackDir
```

No space term, no defender-distance term, no pass-likelihood term, no attribute, in either formula.
Chance takes the players furthest forward and Diagonal the players furthest back, on the **same**
scalar with opposite slope — the two selectors never compete for the same player, which is why
*reordering* them is a placebo (§ 4.7). 15 of the 16 run kinds leave the score at a flat 100.0; only
kind 3 computes a situational penalty (never a bonus).

### 4.3 There is no randomness in the decision layer

The match RNG (Lehmer LCG) lives only in a small cluster of addresses. A direct-call closure of
`ChanceSpaceRun::vf5` to depth 10 (2,741 functions) reaches it **zero** times, with no indirect
calls in `vf5` to make the closure incomplete. The same negative holds for Counter/SecondLine/
Diagonal/PostPlay scorers, the dispatcher, the manager update and the quota builder. A positive
control (the kick builder reaches the LCG at depth 4) confirms the method works. **Identical
geometry produces identical scores, identical ranking, identical runs, every time.**

### 4.4 Quotas, caps, priority, and the run kinds

Quotas are a 5-byte-per-action inline table indexed by attack level 0–4 (clamped) and action id —
e.g. ChanceSpaceRun goes `1,2,2,3,3` across levels 0–4. **No preemption exists**: a later selector
can never poach a player an earlier one holds; a won run is protected for 12 frames (0.2 s), and
turnover happens *only* when that protection expires and the slot is re-bid.

There are 16 "run kinds", the lowest-index bit set in a per-kind mask, dispatched to 19 distinct
movement handlers. **Never tagged in this build: kinds 6, 11, 12, 13.** Kind 6 is the cheapest route
to a genuinely new movement pattern in the whole subsystem — it already has a complete `vf6`
geometry path and its own executor handler, just never tagged by any selector.

`ActionSelectorLineBreak` and `ActionSelectorPullAway` are **dead at both layers** — eligibility
mask always zero, executor bodies stubbed. Reviving either means writing roughly 2,500 instructions
across both layers (explicitly refuted as a project, § 4.7).

CPU difficulty gates *whether a run kind is eligible at all* (rows in the 44×10 table), but does
not touch the scoring formula — "CPU difficulty is not the bottleneck" for AI variety.

### 4.5 Data inputs: playing styles, skill cards, formation, the one ability-scaled term

**Playing styles are booleans, gated by formation role.** Each style is a single bit in a 21-bit
(in-possession) or 16-bit (out-of-possession) mask; a query returns *player has style X* **AND**
*X is legal for the role of his current squad slot*. Play a man off his slot and his style silently
stops firing. Off the ball, style barely matters (three space-run selectors contain six style gates,
five of which are pure vetoes; style never selects a *different* target). On the ball it matters a
great deal. Cosmetic in this build (zero AI call sites): Covering Role, High Line Master, Deep
Defender.

**Skill cards do not drive decisions** — the 73-bit card array is tested only inside
`match::anime::action::*` (execution quality, which animation plays), never in `match::ai::`.

**Formation** contributes geometry and group membership (13 position codes collapse to 10
mirror-symmetric groups) — there is no formation-keyed decision table anywhere.

**The one ability-scaled defensive term** — SETTLED 2026-09-20, see § 4.9: in the shared
base-position runner, out of possession only, a gait threshold, sprint-back gate and recovery
distance all scale with one attribute, and that attribute is `0x17` = **Defensive Engagement**
(not Defensive Awareness `0x15`, and not Dribbling — both were earlier, wrong readings). The
mechanism itself (gait threshold falling from 19.0 at attribute 40 to sprinting at 50+; sprint-back
trigger distance from 15.0 m at 40 to 7.26 m at 99) is real and unaffected by any of the naming
churn — only the attribute's identity was ever in question. **Spreading this in `master.db` is a
live, ready plan** — elite CBs 90+ Defensive Engagement, lower-league CBs 45–55 — confirmed in-game
against real players (§ 4.9). **The decision layer itself never reads an attribute** — ability
enters at *execution*, not choice.

### 4.6 Corrections: things this project believed that are wrong

Reproduced in full from `docs/match-ai-decoded.md`:

| belief | reality |
|---|---|
| dt270 `basePosition` line fields are inert | **Wrong, and it misdirected months of tuning.** `dfLine`, `dfLineRate`, `dfLineCloseRate`, `lastLineCloseMaxRate`, `keepDfTargetLineX`, `backOffsideLine`, `lengthOf`, `minWidth`, `adjustZCompact`, `lineControl`, `spaceCoverRate` all have readers. Genuinely unread: `pressRate`, `defenceCompact`, `lengthDf`, `dfLineWidth_3/4/5`, `wideRate`, `attackLevel`, `attackLevelAdjustX`. |
| `0x1442ed7c0` is a role gate; role id `0x20dc4` rejects midfielders from late runs | It is an **action-priority rank compare**. `0x1d` is the SecondLineSpaceRun action id. `0x20dc4` is a separate, still-unidentified 128-bit token compare. |
| stock `marginPredictionFrameBase` is 6 | It is **0**. |
| `marginPredictionFrameAdjust` tunes defensive anticipation | It is **inert** — multiplied by a `-0.0f` cell and truncated, always 0. Its containing function is a pass-timing/slow-down horizon; nothing in the marking path reads it. |
| the selector `& 1` guard is a possession test | It is **frame parity**. |
| bidding order ends `... CenteringGet > PullAway` | It ends `... GoalGet > PostPlay > PullAway > CenteringGet`. |
| stock `roleBonus` is 100.0 and was re-aimed to 20.0 | `100.0f` is the score **base**; `20.0f` is a **separate** role bonus. Two different cells, two different roles. |
| `Stagger::vf32` is the post-contact lock | It is `isFinished()`, capped at 5 frames (83 ms). The lock is `canStart` (vtable slot 2) + `canCancel` (slot 14). |
| ball physics is Z-up | It is **Y-up** (gravity −9.80665 on component [1]). |
| `forceDashDistDefence` is a live lever | Loaded, then **unconditionally overwritten** before the only compare. Dead in practice — "read" is not "effective". |

**Self-inflicted regressions found and reversed (2026-09-18).** Five of the project's own dt270
edits were pushing the CB cushion the wrong way, and one exe edit made every defender lazier at
every ability level: `spaceCoverRate` and `adjustSpaceCoverRate` raises saturated the 1.0 clamp
(making a defender who believes he covers the gap never step onto his man); `lastLineCloseMaxRate`
and `dfLineCloseRate` cuts reduced the back line's closing effort; `marginPredictionFrameBase`
0→12 handed every shape runner 0.2 s of assumed free time; a gait constant edit
(`19.0f → 15.0f`) made every defender react ~4 m later at every ability level with no ability slope
— a flat laziness shift, not a tuning knob. All six were reversed by
`tools/data/tunings/compact-and-tight.json` and `tools/data/patches/gait-revert.json`.

### 4.7 Refuted — do not rebuild these

Reproduced in full from `docs/match-ai-decoded.md`. Each was built, emulated and killed by
adversarial verification — they look reasonable and they do not work:

- **Reordering selectors to get variety.** Placebo. Chance and Diagonal score by the same scalar
  with opposite slope and never compete for the same player.
- **Lengthening the 0.2 s commitment window.** Directionally anti-variety — turnover only happens
  when the protection expires and the slot is re-bid, so a longer hold means *fewer* different
  runners.
- **Capping ChanceSpaceRun's `maxSlots`.** Inert — its quota never exceeds 3, so `min(quota, 11)`
  never sees the 11.
- **Reversing or rotating the lowest-index run-kind scan.** The masks are one-hot, and the one real
  overlap (kind 3 → kind 2) is a deliberate override. Reversing breaks it and makes the AI *less*
  responsive.
- **Reviving LineBreak or PullAway.** Dead at both layers; ~2,500 instructions to restore.
- **Raising attack level to get varied runs.** Raises the quota, so you get the deepest *and*
  second-deepest man — more bodies, same determinism.
- **The `marginPredictionFrameAdjust` anticipation cave.** Wrong target function (pass timing, not
  marking) *and* mis-calibrated.
- **Widening off-ball eligibility gates** (depth gate, diagonal cone, leash, run-target plane — six
  shipped packs). Widening a pool that is then ranked "furthest forward" and truncated changes
  nothing visible.

### 4.8 The contact lockout

Two stacked locks, not one. **Lock 1 — eligibility (`canStart`, vtable slot 2).** While in a
stagger, the game refuses outright — before any timing check — nearly every action; only Dribble
and Trap are even considered. In a fall, only Trap. In a dive, nothing. **Lock 2 — the cancel gate
(`canCancel`, vtable slot 14).** Reduces to `currentFrame >= cancelKeyframe`, where the keyframe is
baked into the animation asset itself. `Stagger::vf32`, which project notes once called "the
post-contact lock," is neither of these — it is `isFinished()`, capped at 5 frames.

**The asymmetry.** Every stagger request kind uses the *first* cancel key except Dribble (running
with the ball), which uses the *last* — the thing you most want after being barged (push the ball
on) is what the engine makes you wait longest for. This is **not CPU favoritism** — the gate reads
only motion id, current frame, contact sub-kind and requested kind, no controlled-player flag; the
asymmetry is structural because a staggered player is usually the carrier.

**Not proven, and it blocks every fix here:** the real keyframe numbers live in runtime-loaded
motion assets, not the exe, so the lockout's length in seconds is unknown and all frame figures came
from a synthetic table. Adversarial verification found 10 of 11 stagger motions have ≤1 cancel key,
which makes the special Dribble case collapse to the same key anyway — the obvious one-byte fix is
**probably a placebo**. Seven patch specs were written and **none should be applied** until the
motion assets are decoded.

### 4.9 Attribute `0x17` — SETTLED 2026-09-20: Defensive Engagement

Three earlier passes of this project disagreed on `0x17`'s identity (Defensive Awareness, Dribbling,
Defensive Engagement) and the "proven" `DATA_PARAMETER + 7` alignment cited above was never actually
proven — the `+7` was hard-coded into a print statement in `tools/emu_enum_names.py`
(`dp = match_idx - 7`) and never derived from anything. It is refuted at match index `0x36`, where
it predicts `DATA_PARAMETER_WEIGHT` (range 30–129) against the game's own range table reading 0–3
(`weak_foot_usage`).

**The real mapping is a data table the game carries itself**: a `{matchAbilityIdx, compactIdx}` pair
table at `0x14825CAA0`, walked by the roster→match copy loop `0x1454406a0`. `compactIdx` is the
0-based ordinal of the editor/CSV attribute columns. Reading it off gives **`0x17` = Defensive
Engagement, `0x18` = Dribbling, `0x19` = Ball Control** — a contiguous **off-by-one shift across the
whole `0x17`–`0x20` band** (ten labels, not one) is what made `+7` look right everywhere except the
one window where the two orderings diverge. `0x21` onward was already correct under either rule.

Validated eight ways (four small-range slots against the game's own range table, the three anchors
every prior reading already agreed on, and the age/height/weight ranges), then **confirmed live
in-game 2026-09-20**: 22 player ability arrays read from a real match, correlated across the 20 real
outfield players (bench zero-rows excluded). `0x17` tracks tackling at **+0.938** and defensive
awareness at +0.872; it tracks dribbling at **−0.083** and ball control at −0.015. In every one of
the 10 players where tackling and dribbling differ by ≥10 points — including four players who are
better dribblers than tacklers — `0x17` follows tackling, not dribbling.

**`master.db` spreading is unblocked and ready**: elite CBs 90+ Defensive Engagement, lower-league
CBs 45–55, exactly the plan the mechanism always supported. Full account, including the ten-label
correction table: `attr-0x17-defending.md`.

### 4.10 Open questions (from match-ai-decoded.md)

- The real cancel keyframes (motion assets — filenames likely hashed). Blocks every contact-lockout
  fix.
- What the two 2-second latch arrays at `mgr+0x220` / `mgr+0x24c` gate, and what the human-player
  exemption means.
- The two predicates behind the +20 role bonus.
- Whether the same positioning mechanism reads Defensive Awareness (`0x15`) anywhere, separate from
  the now-identified Defensive Engagement (`0x17`) term.
- Whether the ball deflects off non-tackling players (limb collision parts exist; consequence for
  loose balls untested).

---

## 5. Supporting subsystems

Each of these is a decoded chapter in its own right; this section gives what is decoded and the
practical lever it hands a modder. All are corrected-and-cross-referenced against each other —
several explicitly correct claims made in the chapters they build on, and those corrections are
noted.

### 5.1 Player executors (`docs/player-executors.md`)

What actually happens once a brain has chosen: where a runner goes, how a marker moves, how a kick
is struck, how a receiver runs onto a pass, and everything a goalkeeper does mechanically — **109
RTTI classes**. The chapter's own headline correction: the long-standing belief that "vtable slot 20
is the movement-target emitter for everything" is **wrong** — slot 20 usually emits a *steering
direction at a fixed radius*; the actual destination comes from slot 4, or slot 18 for classes that
override it. Key levers: the CB standoff is **not** a radius in `ActionMark::vf20` as long believed
— it is a formation-slot-vs-marking-target LERP whose weights are killed by a 10 m ball-position
ramp, and per-player it can be tuned via out-of-possession playing-style categories 9 (+50 to both
weights) and 0xb (zero them) — **player data, not an exe patch**. Run-target X assignment has *no
timing term anywhere in the executor* — "make runs start later" cannot be tuned at this layer.
`passget` (dt270 idx `0x6c`) and `basePosition` (idx `0xe2`) are read at **depth 0** inside the
executor vtable methods themselves — "the safest levers in this chapter," per the chapter's own
words — but **no dt270 field reaches a goalkeeper executor at all**. Zero attribute reads anywhere
in the run/marking-target closures examined; ability enters only at the animation layer.

### 5.2 Ball-carrier brain (`docs/ball-carrier-brain.md`)

How the AI decides what to do *with* the ball: pass, dribble, shoot, feint, and to whom — **65 RTTI
classes**, roughly half fully decoded. One `BallPlayer` object exists **per team-slot** (an earlier
project belief that there was one object per team, no per-player copy, is corrected here). Decision
flow: activation test → `Personality` recompute (8 floats from attributes/style bits/cards/COM
flags) → situation classification (`Intention`) → the **Image** layer picks a plan by first-match
over a situation-keyed list (four of sixteen entries roll a literal percentage) → an ordered
candidate list of `ThinkUnit` kinds is tried in list order and **the first one that produces an
answer wins — no score is ever compared**. The CPU additionally sits on an answer for a
difficulty-dependent number of ticks before it is allowed out. **The single largest on-ball lever
found is a per-match team field (`team+0xb3c4`/`team+0xb44d`) whose name and writer are unknown** —
it forces cross/long-ball plans and disables the Safety plan; `registry-blackboard.md` later
**retires this as NOT-SAFELY-TUNABLE**, calling it "a transient AI directive with no file, no table
and no persistent setting behind it" (see § 8). **No dt270 field reaches this subsystem at all** —
exhaustively checked.

### 5.3 Goalkeeper / goalkeeping (`docs/goalkeeper.md`, `docs/goalkeeping.md`)

There is no single goalkeeping subsystem in the exe — the keeper is split across `match::player`
executors (25 `ActionKeeper*` classes) and `match::anime::action::goal_keeper::*` (15 vtables),
plus an on-ball brain that lives in neither (`0x145655430`, reached through exactly one call site,
the sole writer of the distribution target — this is why `GKDribble`/`GKPassShort`/`GKPassLong`
ThinkUnits are registered and never run). Key findings:

- **A bad keeper cannot be made to look bad through the one fully-followed route** — the
  save-quality multiplier there spans only 0.900–1.295 (77–92% worst-to-best). But that route is
  **one of four consumers** of the save-quality integer, and the block-wide range across all four
  is **NOT BOUNDED** — a genuinely open question, not a closed one.
- **Two real behavioural cliffs exist.** GK Reach below 85 loses a diving-parry behaviour outright
  (not a quality reduction — a missing behaviour). GK Awareness below 44 loses the anticipation
  branch entirely (the budget calculation floors to 0 frames) — **never author a keeper at GK
  Awareness 40–43**.
- **GK Awareness is a real anticipation window** (0 frames at 40, 15 frames/0.25 s at 99), not "the
  0.5 m standing error" that earlier chapters treated as the whole model — that standing error is
  in fact the *smallest* of three terms.
- **Coming out is a 15 m decision with no ability term** (7 m in some team states); only HEIGHT
  matters anywhere in the Press family.
- **Penalty dive side is a pre-commitment read, not a coin flip** — a single comparison of the
  action record's angle descriptor against 90.0, no RNG, no attribute. **Once a dive starts it
  cannot be stopped.**
- **CPU difficulty never reaches `match::anime`** — 0 of 90 difficulty-table call sites lie in any
  `match::anime` method body; saves and first touches are level-independent.
- `trap.ballControlRate` — a widely-cited dt270 lever — is **1.0 in stock**, not 0.8 (0.8 was this
  project's own `loose-realism-v1.json` value, mistakenly read from a stale dump as if it were
  Konami's default), and it scales **Tight Possession and Aggression, not Ball Control**.

### 5.4 Set pieces (`docs/set-pieces.md`)

There is no `match::setpiece` namespace — set pieces are stitched from the six already-decoded
subsystems. **The decision side (who takes it, whether it's shot or passed, penalty aim, whether a
wall player jumps, whether a foul is even given) reaches no RNG anywhere in its transitive closure.
The launch side is the opposite** — `Restart::vf8` makes ten stochastic draws, and on one narrow
path gates a re-draw on the **Set Piece Taking** attribute through a logistic (midpoint at rating
72, 50% re-draw rate at rating 63) — but that path only fires for a specific forward-simulated
near-post solution and only for two specific kick-mode bytes; most restart types never reach it.

**`positionPK_2..5` / `positionNone`** (the penalty-shootout standing positions, dt270 objects) are
**bound by name**, not by constant index — a distinct fifth fetch mechanism, the only one of its
kind in the whole image: a 5-entry name table at `0x1475d1850`, resolver `0x145349470` (a prior
chapter had misidentified the resolver address as `0x1453494e0`, which is a *different* function
returning a discarded boolean — corrected by the residue pass, § 2.6). This is a genuinely live,
safely-tunable gameplay lever: editing the 22 `{enable, playerNo, startPosX, startPosZ}` rows per
back-line-count variant moves where the twenty-two bodies stand at a penalty. `positionNone` is the
resolver's not-found default (all rows disabled) and is reached if a back-line count outside
{2,3,4,5} occurs — not literally unreachable as an earlier draft claimed.

### 5.5 Pad input model (`docs/pad-input.md`, `docs/pad-node-kinds-and-unit-modes.md`,
`docs/pad-power-and-cursor.md`)

Everything between the controller and a command: the raw input ring, **72 `ThinkUnit` query
objects** (`match::pad` namespace, 73 RTTI classes including the base), a temporal pattern engine
that decides what counts as a *tap* versus a *hold*, and how a held button becomes kick power.

- **Tap/hold discrimination is exact and frame-rate-derived**: a tap is `≤ (int)(0.08×FPS + 0.5)`
  frames (5 at 60 fps, ~67 ms), computed live from the frame rate — nothing new needs to be built to
  *detect* a tap.
- **Kick power is not a held-frame counter.** Each `ThinkUnit` owns a float gauge that advances by
  `1/(FPS×T)` every frame its press machine is in state 2 (`T` from a 16-entry fill-time table); on
  release, or the moment the gauge hits 1.0 (whichever first), the unit emits its command with
  `power = floor(gauge × 127)` packed into 7 bits — linear in held time, hard-clamped, frame-rate
  independent in time but not in resolution.
- **Eleven pattern-node kinds are now all named and emulated** — the node-kinds chapter corrects
  three claims from the original pad chapter: kinds 1 and 3 were swapped (kind 1 is the *press*
  edge, kind 3 the *release* edge); the per-unit `+0x10` field is not a trigger mode but the unit's
  **command lifecycle class**; the "5-row gesture table" is actually **three separate 16-row
  tables**, all feeding the skill-move/feint `ThinkUnit`.
- **The trigger-run request this project's realism queue wanted already ships, on a different
  button than assumed.** `ThinkUnitPassAndGo` is gated on RT+RB, not L1+A/R1+A as originally
  believed; an "LB = trigger a run" binding is impossible because LB-alone fires
  `ThinkUnitCursorChange` on the raw *press* edge, before a tap could ever be distinguished — that
  collides unconditionally. **RB-alone is free** (no `ThinkUnit` in the attack bank claims it without
  also requiring a stick or RT state), so the shovel-ready build-it-on target is RB, not LB. The
  hook for retargeting a gesture is **not code** — the two `PassAndGo` pattern chains sit in
  zero-at-load data filled once by a TLS-guarded static initialiser; after the first evaluation
  they are plain writable memory, retargetable via `tools/live_patch.py` with no instruction
  patched and no new Denuvo surface, subject to preserving certain sentinel field values (documented
  in the pad chapter's own §14.12).

### 5.6 Registry / blackboard (`docs/registry-blackboard.md`, `docs/registry-pad-command-channel.md`)

Where every subsystem's shared state lives. **218 RTTI names resolve to exactly 45 data records**
wrapped in `Ref`/`ArrayRef`/`ScopedRead`/`ScopedWrite`/`ScopedWAndC` accessor templates — a struct
catalogue, a per-match tactics landing map, and the pad→command channel. `UPadInput` is a 100-frame
ring buffer of raw controller state per pad slot — the *only* thing the hardware writes; everything
above it (the 72 `ThinkUnit`s) is a query language, marshalled once per frame into `UCommandOutput`
(80,672 bytes, `Copy`), which `match::player` executors read back out. `UCommandInfo` is **not** in
this path — it is the netcode's own channel, a separate thing. This chapter is also where the
**`team+0xb3c4` on-ball directive lever gets retired** (§ 8) — its own § 11 table is headed "NOT
SAFELY TUNABLE — the rows that were earned the hard way."

### 5.7 Animation actions / contact (`docs/anime-actions.md`, `docs/anime-keeper-and-first-touch.md`)

What actually moves the body once an executor has said "go here." **135 rows total: 131 RTTI
classes (106 `match::anime::action::*`) plus the three `MbInfo*` data-store classes and
`AnimeCollision`.** This is where the animation *cancel* keyframes live (§ 4.8's contact lockout),
where the six goalkeeper save classes each hard-code a different action id reading a different GK
attribute, and where the save-quality multiplier (0.90–1.40 across the whole system, not just the
0.90–1.295 range of the one traced route — see § 5.3) is computed. The save is very nearly
deterministic: zero RNG call sites inside any of the 114 `goal_keeper::` method bodies; the only
randomness anywhere in the save family is a centimetre-scale positional jitter. **CPU difficulty
never reaches this layer** (0 of 90 difficulty-table call sites land here). **The ball never
collides with a body** — its integrator's 15-function forward closure reaches no collision system,
no attribute getter, no RNG, and no dt270 read; its bounce table has six *surface* entries and no
body entry.

### 5.8 Control source and human vs. CPU (`docs/control-source-and-human-vs-cpu.md`)

The "15-way jump table" controlling human vs. CPU command dispatch is **not 15 ways** — 15 table
entries point at only three distinct code addresses (a no-op, a full pad branch for codes 1–11, a
reduced pad branch for 12–13). Dispatch runs over the 8 hardware pad slots, not over the 24 on-pitch
players — a player with no pad bound never reaches it. The `ControlMode` for a given on-pitch player
reduces to a single byte meaning "this player is inside his side's human-control allocation"
(computed as `positionRank[idx] <= controlCount[team]`, cursor player forced to rank 0). Critically:
**`match::ai::bp` (the BallPlayer carrier brain) activation requires that same byte** — so the
human's own controlled carrier does still run the carrier brain; he is simply the one player
guaranteed to satisfy the gate.

---

## 6. The gameplay catalogue tool

`build/gameplay-catalog.html`, generated by `tools/gameplay_catalog.py`, is the intended starting
point for any tuning session — a **subsystem-first** browsable index (rebuilt 2026-09-20; the older
2026-08-23 version was field-first and had accumulated thirty disproved statements, all listed and
corrected rather than silently deleted). It has seven views behind one search box:

| View | Rows (2026-09-20 build) | What it is |
|---|---|---|
| **Questions** | 86 | Football questions ("why does my centre-back stand off") each answered in a paragraph, with chapter/section/address citations |
| **Subsystems** | 8 chapters, 90 "enables" rows | Each chapter's "machine in one paragraph" and "What this enables" table, verbatim, plus negatives/corrections/open questions |
| **Levers** | 469 (227 chapter-verified, 242 from the pre-chapter exe sweep) | Every named lever, grouped by route, with NOT-SAFELY-TUNABLE / not-reachable / nothing-to-tune cards surfaced first |
| **Negatives** | 153 negatives + 287 corrections | Proven absent, proven placebo, proven mis-attributed — as valuable as the levers, so the same wrong idea doesn't get re-tried |
| **dt270 fields** | 1,363 fields across 22 gameplay objects, plus the 61-row attribute-id table | Joined per field to the liveness catalogue and re-read from the installed CPK at build time |
| **Exe map** | 242 levers across 18 systems | The 2026-08-23 sweep, with superseded rows marked in place |
| **State** | 119 packs, 25 tunings, 44 difficulty rows, 30 fixes, 18 open holes | What is *measured* to be installed right now — see § 8 for why this view exists and what it corrected |

```bash
python tools/gameplay_catalog.py --toolrepo "<checkout with tools/data/patches>" build    # build/gameplay_catalog.json
python tools/gameplay_catalog.py --toolrepo "<checkout with tools/data/patches>" html     # build/gameplay-catalog.html
python tools/gameplay_catalog.py --toolrepo "<checkout with tools/data/patches>" state    # measured install state to terminal
python tools/gameplay_catalog.py search "standoff"                                        # grep all views at once
```

Re-run after every Konami patch (`dt270_schema_gen.py` and `exe_map.py` first — addresses and
offsets move). Route vocabulary used throughout: `dt270-data` · `player-data` · `motion-asset` ·
`runtime-data` · `exe-constant` · `exe-code` · `not-reachable` · `NOT-SAFELY-TUNABLE` · `withdrawn` ·
`none` · `unclassified` — with **no default bucket**: an unresolvable route lands in
`unclassified`, never silently in `exe-code`. dt270-view status badges distinguish `live` (effect
proven) from `read` (reader proven, effect not) from `inert` (provably does nothing, cited) from
`unread`/`unlocated`/`unresolved` — **`read` is explicitly not `effective`** throughout.

---

## 7. Practical workflow for making a gameplay mod

1. **Identify the lever via the catalogue.** Open `build/gameplay-catalog.html` (rebuild it first if
   stale — check the State view's timestamp), search the Questions or Levers view for what you want
   to change. Note its route (`dt270-data` vs `exe-code`/`exe-constant`) and its evidence level.
   **Skip anything tagged `NOT-SAFELY-TUNABLE`, `not-reachable`, or `unresolved` — those are not
   levers, they are documented dead ends.**
2. **Read current value and confirm it is really installed, not assumed.** For dt270:
   `python tools/dt270_objects.py get <object> <path>` or `python tools/gameplay_tune.py diff` (shows
   installed vs. pristine, by name). For the exe: `python tools/exe_patch.py status` /
   `python tools/exe_patch.py diff`. **Do not trust a previous session's memory of "what's applied" —
   the catalogue's own State view exists because bookkeeping journals drifted from reality** (§ 8).
3. **Decide dt270 edit vs. exe patch.** Prefer dt270 whenever the lever lives there — it is data
   only, reversible, and survives Konami patches. Reach for the exe only when the behaviour genuinely
   is not in the data (kick error, CPU difficulty thresholds, AI decision-layer code, contact
   lockout keyframes).
4. **For a dt270 edit:**
   ```bash
   python tools/gameplay_tune.py get <object> <path>          # read
   python tools/gameplay_tune.py set <object>.<path>=<value>  # edit + install
   python tools/gameplay_tune.py apply my_tuning.json          # batch, preferred for anything >1 field
   python tools/dt270_objects.py verify                        # byte-exact round-trip gate — MUST pass
   python tools/gameplay_tune.py diff                           # confirm what's now installed
   python tools/gameplay_tune.py restore                        # rollback if needed
   ```
5. **For an exe patch:**
   - Prefer on-disk (`tools/exe_patch.py`) per the 2026-09-19 owner ruling (§ 3.4), unless you
     specifically want a live-only test before committing.
   - `tools/exe_patch.py` backs up the pristine exe automatically on first apply; it writes only if
     every `expect` byte still matches the current image.
   - For a runtime-only test: `python tools/live_patch.py probe` first, every session, before any
     write — a mismatch means the map is stale, do not patch. Then
     `python tools/live_patch.py apply spec.json --i-understand-denuvo`, and keep the journal so
     `restore` can undo it while the process still lives.
   - If the payload needs more space than the target instruction's own bytes, use the code-cave
     allocator (`tools/cave_scan.py scan` then `tools/cave_alloc.py`) rather than hand-picking
     padding — it already validates against `.pdata` and chains across small caves automatically.
   - Never write into `.impdata` (Denuvo blob, no gameplay code there) and never overwrite a shared
     `.tls$` constant cell in place — repoint the instruction's `disp32` to a different cell instead.
6. **Test in-game.** Keep changes to one obvious parameter/patch per test cycle where possible, so a
   regression is attributable. Remember Steam's "verify integrity of game files" reverts on-disk exe
   patches — re-apply afterward if needed.
7. **The two gates, both mandatory:**
   - **Byte-exact verify** before trusting any write reached disk correctly — `dt270_objects.py
     verify` for dt270, `exe_patch.py diff`/`status` for the exe.
   - **In-game confirmation** that the change did what was intended — static analysis proves a
     reader exists and what it does with the value; it does not prove the *experience* changed the
     way you wanted, and several "proven" levers in this project's history turned out to be placebos
     once actually tested (§ 4.7 and § 8).
8. **Record what you did, where the catalogue can find it.** Add a spec/tuning file under
   `tools/data/patches/` or `tools/data/tunings/` rather than a one-off manual edit, so the State
   view and future sessions can measure it back out of the installed image.

---

## 8. Known unknowns, open questions, and hazards

This section is intentionally not smoothed over — several of these are places where the project's
own documents disagree with each other, or where a chapter's confidence turned out to be
overstated. Anyone about to make a gameplay change should read this section, not just the tables
above.

**The disk-vs-runtime exe patching discrepancy (see § 3.4).** Multiple chapters predate the
2026-09-19 owner ruling and still frame on-disk exe patching as forbidden or last-resort, while
`docs/exe-gameplay-map.md` itself documents that the game had already been running with 909 bytes
of on-disk patches across 105 runs without the feared Denuvo integrity trip. The ruling ("I don't
mind changing the exe") makes on-disk patching the default going forward, but does **not** retroactively
validate every prior statement in every chapter — treat any pre-2026-09-19 "runtime-only" framing as
superseded, and treat the physical constraints (cave sizes, unwind-hostility, Denuvo's actual
integrity behaviour under a code-page write, which has genuinely never been observed live) as still
real and still binding regardless of what is "allowed."

**Attribute `0x17`'s identity — RESOLVED 2026-09-20 (see § 4.9), no longer a hazard.** It is
Defensive Engagement, settled by the game's own `{matchIdx, compactIdx}` pair table and then
confirmed live in-game (`corr(0x17, tackling) = +0.938`, `corr(0x17, dribbling) = −0.083` across a
real match's outfield XI). The earlier "proven `DATA_PARAMETER + 7`" claim this guide previously
carried was never actually proven — kept here as a record of what this section used to say, since
several other tools (`emu_bp_personality.py`, `emu_anticipation.py`, `emu_runscore.py`) still print
the old, wrong labels in their output and have not yet been updated.

**dt270's installed baseline carries old tunings while the exe is pristine, or vice versa — and this
has already caused a real documentation failure.** The gameplay catalogue's 2026-09-20 rebuild found
that its *previous* version had been silently displaying this project's own August tuning values
(`ball.magnusRate` 0.06, `trap.ballControlRate` 0.8, `marginPredictionFrameBase` 6, and others)
labelled as "what's installed right now" — when the actual installed values were meaningfully
different (0.035, 1.0, 0 respectively). **The exe and the dt270 pack are two independent install
states that can each be pristine or patched independently of the other, and neither install-state
journal (`build/exe_patch_state.json`) can be trusted without a byte comparison against the current
image.** Always measure (`gameplay_tune.py diff`, `exe_patch.py status`/`diff`) rather than trust a
prior session's memory or a tuning pack's filename.

**`team+0xb3c4` / `team+0xb44d` — the largest single on-ball lever `ball-carrier-brain.md` found —
was subsequently retired.** `docs/registry-blackboard.md` explains why: it is a transient per-match
AI directive with no backing file, no table and no persistent setting — there is nothing to *author*
into it as a mod, only to observe or momentarily poke at runtime. Anyone reading only
`ball-carrier-brain.md` would come away thinking this is a real, actionable lever; it is not, per the
later chapter.

**`ballplayer`'s fetch mechanism is genuinely unresolved** (§ 2.6). It is the one object in the
entire dt270 residue that looks gameplay-shaped and has no proven route to being read by the engine
at all. Do not tune it; do not trust an in-game effect if you try.

**The contact lockout's real timing is unknown**, because the cancel keyframes live in runtime motion
assets that have not been decoded (§ 4.8). Every "fix" written against it so far is either a probable
placebo (10 of 11 stagger motions collapse to the same cancel key regardless of the special-case
branch) or untested against an unknown floor value. None of the seven written patch specs should be
applied.

**`URandomInfo+0x08` — CONFIRMED WRITTEN 2026-09-20, nothing downstream collapses.** A live memory
read during a real match found it taking 1,245 distinct values across [0.002, 0.9997) over 150
seconds of play — not constant, not latched. The carrier's per-possession random `r` is genuinely
live and its tunables stand as documented. The CPU's penalty-aim index (`URandomInfo+0x00 % 7`) was
checked in the same pass and also varies — all seven aim indices 0–6 were observed, so the CPU does
not aim at one spot all match either. The writer for `+0x00`/`+0x04`/`+0x08` is still not located
(a decoded candidate, `match::RandomControl`, turned out to write different, adjacent fields —
`+0x0c`/`+0x10`/`+0x11`/`+0x14` — not these three), so *where* the writer lives is still open, but
*whether* one exists is no longer in question.

**Which action id runs which run-kind executor is proven *not* to be a simple table** — so "if I tag
a player with run kind 6, what code actually moves him?" does not yet have a definitive answer, and
whether kind 6 genuinely never runs in practice is unproven in both directions.

**The demoarea/stadium bounding-box question is open, not closed.** `docs/dt270-residue.md` proves
the box is read by `match::anime::action` (four classes, including the set-piece-relevant
`CornerKickLoop`), and calls it presentation-only "on the evidence available" — but explicitly states
"whether it also constrains player standing positions at a corner is NOT PROVEN." The residue
chapter's original triage method (labelling by source-folder name) is separately flagged as unsafe
and known to have gone wrong once already.

**The dt270 liveness catalogue's `cached` route was never actually run** (§ 2.6) — `cached: 0` is an
artifact of a `MemoryError`, not a measurement, and cannot currently be closed for the two largest
candidate K values even on a successful run.

**None of the exe-side kick miss-type or CPU-level correction work in `docs/exe-gameplay-map.md`'s
"CPU difficulty is not the bottleneck" section in § 4.4 should be trusted at face value** — the
match-ai-decoded chapter itself flags that the difficulty-table row values it quotes were dumped
from the **patched**, not the pristine, image, and that its own row numbering is off by one from the
raw table. Re-deriving the correct stock values for every row from PRISTINE is explicitly named as
"owed work, not done here."

**General hazard, stated once for the whole document:** several "proven" claims in earlier drafts of
these chapters were later found wrong by adversarial re-review from the bytes — correlated-branch
inertness, mis-widened index ranges, swapped resolver addresses, off-by-one attribute alignments. The
project's own working method — hand-decode the skeleton, delegate behaviour work with it as fact,
then always adversarially verify — is why these corrections exist and are documented rather than
silently fixed. Treat any single chapter's claim with the confidence level it states (`a-emulated` >
`b-disassembly` > `c-inferred`), and treat a claim with no stated confidence level as unverified.
