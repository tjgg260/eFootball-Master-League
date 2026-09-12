# dt270 gameplay constants — FULLY DECODED (2026-08-23)

The gameplay "feel" of eFootball lives in `dt270_console_all.cpk` → `common/match/constant/*.bin`,
a separate pack from the dt200 roster data (a gameplay mod and our Master League roster/tactics
coexist). As of 2026-08-23 every byte of it is understood and every parameter is addressable
**by its real Konami field name**. Field catalogue: [dt270-fields.md](dt270-fields.md).

> The earlier theory in this file ("Q2.14 fixed-point multiplier tables", "word 131 is tempo")
> was wrong. The tables are ordinary IEEE floats / int32 / bools in a structured object format.
> The "sentinel ±52428" values were floats like 0.4 read as integers. Nothing from the old
> word-index probes should be trusted; the per-patch "calibration" approach is obsolete.

## Format

```
constant_*.bin   WESYS container: 16-byte header, then PLAIN zlib (level 9 reproduces Konami's
                 bytes exactly — no encryption, whatever the header byte says)
  payload        PACK: u32 count, u32 8, count × { u32 data_off, u32 data_size, u32 name_off },
                 then NUL-terminated names "<object>.o", then the object blobs
  object (.o)    compiled JSON document (the exe still lists the source paths, e.g.
                 DevelopData/common/match/constant/match/rating.json):
                   record   = fields in the loader's key order, C-like natural alignment
                   float/int = 4 bytes inline, bool = 1 byte inline (packed)
                   nested object / array / string = u32 OFFSET (from object start) to a block
                   array block = N inline elements (scalars, or inline records whose own
                                 object/array/string members are again u32 offsets)
                   strings = NUL-terminated, deduplicated (two fields may share one slot)
                   blocks are emitted depth-first (children before parent), 16-byte aligned
```

12 files, 245 objects, 36 object types, ~30,000 named leaf parameters. `ballplayer.o` alone
(75 KB) is 18,772 of them (turn/touch motion-matching tables).

### How the names were recovered (and how to redo it after a Konami patch)

The `.o` blobs carry no names, but `eFootball.exe` does: every object type has a **JSON
loader** (dev path — walks keys by name with JsonCpp) and a **binary loader** (release path —
copies `.o` bytes into the same C++ struct), both reachable from a registration table
`{json path, factory}` → factory → vtable `[dtor, loadJson, loadBin]`.

`tools/dt270_schema_gen.py` finds all of that by shape (no hard-coded addresses) and
**emulates both loaders with Unicorn**: the JSON loader against a synthetic DOM whose accessors
return sentinels (→ key path ↦ struct offset + type), the binary loader on the real `.o` bytes
(→ struct offset ↦ `.o` offset, pointer slots, array strides). The join is the schema
(`tools/data/dt270_schema.json`), validated by a pure-Python reader against every object in the
installed pack (245/245 byte-exact). Re-run it after each patch — ~40 s, needs
`pip install capstone unicorn`.

Known Konami data quirk: `PathToGlory10/12.playerData` has 40 emitted elements but the loader
reads 88 — the game reads garbage past the object's end there. The reader caps arrays to the
emitted count and refuses to write beyond it.

## Tooling

```bash
python tools/dt270_objects.py list                          # files / objects / types
python tools/dt270_objects.py fields basePosition --depth 2 # browse a field tree
python tools/dt270_objects.py get ball magnusRate            # read by dotted path
python tools/dt270_objects.py dump --out build/dt270_json    # every object -> JSON
python tools/dt270_objects.py verify                         # byte-exact round-trip gate

python tools/gameplay_tune.py get shoot normalShootGageMax99
python tools/gameplay_tune.py set ball magnusRate=0.05 basePosition.dfLine=12   # edit + install
python tools/gameplay_tune.py apply my_tuning.json           # batch of {object,path,value}
python tools/gameplay_tune.py scale --object ball --factor 0.9 --match bound    # float probe
python tools/gameplay_tune.py diff                           # installed vs pristine, by name
python tools/gameplay_tune.py restore
```

Write path (unchanged rules): edits are in place inside the object (no size change, no block
moves), the edited `constant_*.bin` is re-deflated and dropped into its original CPK slot
(zero-padded), every other byte of the CPK untouched, round-trip re-decoded before install.
Small files have little slack (`constant_match.bin`'s slot is 2,582 B); if level-9 zlib no
longer fits, `encode_constant` falls back to zopfli (~4% smaller, standard deflate) —
`pip install zopfli`. Strings may only be replaced by same-or-shorter strings.

**In-game verification status:** the patched CPK is proven structurally (reloads through the
CPK parser, edits read back, 10/12 entries byte-identical). It has NOT yet been booted in-game
through this path — the first `set` is the live test; keep it to one obvious parameter
(e.g. `ball.magnusRate` 0.035 → 0.1 makes curl absurd) and `restore` afterwards.

## What is controllable (see dt270-fields.md for every field)

| object | leaf params | lever |
|---|---|---|
| `basePosition` | 220 | **team shape AI**: `dfLine`, `dfLineWidth_3/4/5`, `adjustDefenceLine_Retreat/ForeCheck`, `closeRate_DF_FW`, `forceDashDistDefence/Offence`, `defenceCompact`, `attackLevel`, corner/free-kick/goal-kick shapes (`gkl*`, `cornerKick*`, `freekick*`) |
| `ball` | 186 | **ball physics**: `magnusRate`, `curve`, `airRegistNormal`, `boundRate[6]`, `frictionRoll*[6]`, `dragSpeedMin/Max`, top/back/non-spin decay, `grounderSpeed` (the `[6]` arrays are per pitch condition) |
| `shoot` | 124 | **shot power/height gauges** (km/h): `normal/control/powerfullShootGage{Min,Mid,Max}{40,99}[6]` — `[6]` = 5 m distance-to-goal band, 40/99 = attribute; `*_dy` = launch-elevation curve (°), `loop`, `advanceLoop` |
| `trap` | 126 | first touch: `ballControlRate`, `reachOut`, `reactionTrapBall`, `defenseTrap`, `busyTrapControl`, cancel/blend frames, `trapLoss` |
| `grounderpass` / `flypass` / `throughpass` / `centering` | 46–118 | pass models: `receiveSpeed[6]`, `passAssistLevel`, `angleY`, `lob`, manual-blend gauges, search/selection |
| `passget` | 56 | receiving & interception: `manualPassGetRate`, `naturalPassget`, `defence`, `inputMove*`, `trapStopThink*` |
| `moveMatching` | 220 | **locomotion**: `RouteParameter[14].{acc, dec, rotSpeed, decRotSpeed, accRateDif60/120/180}` + animation `WeightParameter[3]` |
| `ballplayer` | 18,772 | turn/touch motion-matching tables (`TurnData[1440]`, `touch0[7]`) + `Feint.rate` |
| `rating` | 133 | match-rating formula: `coef_*[10]` per action, `addPoint.*` bonuses, `df/mf/fw/gk_rate`, `ratingMin/Max` |
| `cameraInplay` | 60 | in-play camera: move area, margins, `newWideCamera`, drop-point display |
| `animeAging*` | 6–16 | animation-aging test harness (dev) |
| `setplayGuide*` | 6–24 | set-piece guide distances / targets |
| `positionNone`, `positionPK_2..5` | 88 | penalty shoot-out positioning |
| `ballPersonData`, `ball_person_st###` (73) | 790 | ball-boy / bench / coach / camera-person placement per stadium |
| `demoarea_*` (104) | 83 | pre-match demo camera areas per stadium & competition billboard set |
| `modeMatchup`, `userPlayTendencyTest`, `mlScreenShot` | | mode rules / tendency test / internal capture |
| `PathToGlory*`, `Sugoroku*`, `tutorial*` | | training-mode scenarios |

Player **attributes** (speed, stats) are NOT here — they are dt200 (roster) data; dt270 is the
engine's behaviour model that those attributes feed into.

## Version families (now explained)

`constant_match.bin` decoded size fingerprints the exe build a pack targets (10622 = v6-era
mods, 11904/11912 = GabeLogan/Bromi, **9968 = installed game**). The reason is structural: the
C++ structs change between patches, so old packs' objects have different field sets. The legacy
`install --mod` path still refuses family mismatches; **named edits are patch-proof** — after a
Konami update, run `dt270_schema_gen.py` and re-apply your `tuning.json`.

## History

- 2026-08-19: container + zlib mapped; tables mistaken for Q2.14 words; per-word A/B plan.
- 2026-08-20: cross-pack diff study under the wrong model (superseded; old notes removed).
- 2026-08-23: full decode — binary-DOM format, names from the exe's loaders via emulation,
  36 types / 245 objects / 245 byte-exact, name-based `get/set/apply/diff/scale`.

## Tuning packs

- `tools/data/tunings/loose-realism-v1.json` — **installed 2026-08-23, in-game verdict pending.**
  155 edits (49 distinct levers + uniform ×0.95 shot-speed tables), produced by four analysts
  and four skeptics over the decoded dumps (build/dt270_proposals.json has every kept/rejected
  item with reasoning). Goals: looser first touch (trap.ballControlRate 0.8, trapLossDashOnly
  off, slower/earlier reaction traps, shorter reachOut, heavier moving touches, livelier bounce),
  more wayward shooting (higher launch elevation, −5% speed, more drag/curl/knuckle), less
  assisted/slower passing (PA2/PA3 assist arrays, weak-passer speed/loft, defender reaction
  spread 0.5→0.3 s), slower/less perfect team shape (forceDashDistDefence 12, pressRate 0.4,
  spaceCoverRate 0.35, moveStartDist 1.0, transitionSec 6, matchUp continue +10, jog threshold 60,
  lengthDf_Retreat 32). Honest limits: no explicit error/accuracy term exists in dt270; CPU
  pass *selection* lives in the exe; assist-array edits affect human passing only.
  Rollback: `python tools/gameplay_tune.py restore`.
  **exe-confirmed (docs/exe-gameplay-map.md):** `trap.ballControlRate` multiplies normalised Ball
  Control into the trap's controllable-speed/error-angle model; `shoot.*_dy.gageMax` is launch
  elevation; the gauge tables are km/h by attribute × distance band; `ball.magnusRate /
  airRegistNormal / boundRate` are the Magnus, drag and restitution coefficients — all moved in
  the intended direction. **Inert** (no reader in this build): `basePosition.pressRate`,
  `basePosition.forceDashDistDefence` (dead load; only `forceDashDistOffence` is live),
  `passget.defence.secMin/secMax`. `spaceCoverRate` is likely live. The kick *error* itself is
  exe-side (`(1−f)·22.5°`, see the map) — `tools/data/patches/kick-error-x2.json`.
