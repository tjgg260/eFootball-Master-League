# The gameplay catalogue — what it is, how to rebuild it, what it does not cover (2026-09-20, repaired same day)

`build/gameplay-catalog.html` is the lookup surface for the realism mod. It was rebuilt on
2026-09-20 from **subsystem-first** principles, on top of the eight finished gameplay chapters.

The old catalogue (2026-08-23) was **field-first**: a list of dt270 constant names with
eighteen hand-typed verdicts. A reader arriving with *"why does my centre-back stand off"* had
no entry point at all, and thirty of its statements had since been disproved. That is fixed
here, and the disproved statements are listed rather than quietly deleted — see § What was
wrong.

---

## What it contains

Seven views behind one search box. Row counts are from the 2026-09-20 build.

| View | Rows | What it is |
|---|---|---|
| **Questions** | 86 | The football question a reader actually arrives with, answered in a paragraph. Each row carries the chapter, the section, the addresses it was proved from, its route and its evidence level. Authored in `tools/data/catalog_questions.json`. |
| **Subsystems** | 8 chapters · 90 "enables" rows | Each chapter's own *machine in one paragraph* and its *What this enables* table, lifted **verbatim**, plus its negatives (153), corrections (287) and open questions (151), collapsed. |
| **Levers** | 469 (227 chapter-verified, 242 from the pre-chapter exe map) | **Every lever the map names** — not all of them changeable. Grouped by route, with the *you cannot act on this* cards first: **NOT-SAFELY-TUNABLE** (38), *not reachable* (16) and *nothing to tune* (9) — 63 rows in all. (A fourth such class, *withdrawn*, exists in the vocabulary and holds no lever row today; one `What this enables` row uses it.) Each row keeps the chapter's site, effect, evidence and pool-cell sharer count, and 16 carry a computed `superseded` badge. Filter by subsystem or by route. |
| **Negatives** | 153 negatives + 287 corrections | Proven absent, proven placebo, proven mis-attributed. As valuable as the levers: it is how the same wrong lever stops being tuned twice. |
| **dt270 fields** | 1,363 fields across 22 objects, plus the 61-row attribute-id table | The old field table, kept — but joined **per field** to `build/dt270_liveness.json` and re-read from the **installed** CPK at build time. |
| **Exe map** | 242 levers across 18 systems | The 2026-08-23 sweep, kept with superseded rows marked in place. Its value column is headed **Sweep 2026-08-23**, because those numbers are the sweep's snapshot and are *not* re-measured at build time (only the difficulty table and the dt270 pack are). |
| **State** | 119 packs · 25 tunings · 44 difficulty rows · 30 fixes · 18 gaps | What is *measured* to be installed right now, and what the old catalogue got wrong. |

### The route vocabulary

`dt270-data` · `player-data` · `motion-asset` · `runtime-data` · `exe-constant` · `exe-code` ·
`not-reachable` · `NOT-SAFELY-TUNABLE` · `withdrawn` · `none` · `unclassified`.

A row is classified from its own route cell, and **every** class its words support is kept: a
chapter that says *"exe code … or player data"* gets both badges and is filed under the cheaper
one. There is **no default**. A row whose route cannot be resolved lands in `unclassified`, never
in `exe-code` — a fallback that names a tunable route turns *"we do not know"* into a verdict.

Three of these were forced by the chapters and did not exist in the old catalogue:

* **`NOT-SAFELY-TUNABLE`** — looks like a lever and will hurt you. Constants that double as RNG
  stream indices or jump-table bounds, cells multiplied by a just-zeroed register, values the
  game rewrites every frame, shared pool cells that must never be written in place.
* **`not-reachable`** — a real, decoded mechanism with no authoring path found. Listed so nobody
  re-derives it hoping for one. A table literally headed *"why it cannot be executed"* lands here
  wholesale.
* **`withdrawn`** — the chapter that offered the row has since withdrawn it. Kept visible, because
  deleting a wrong entry teaches nobody.

### The evidence vocabulary

The chapters' own `a-emulated` / `b-disassembly` / `c-inferred`, plus **`unstated`** for a table
cell that claims no level. Nothing is ever upgraded to a level a chapter did not claim; where a
chapter says NOT PROVEN or WITHDRAWN, the catalogue says so in the same words.

Two rules make that true rather than aspirational:

* **The LEADING tag wins.** Evidence cells are often mixed and they are ordered: *"**c** (bytes
  are b)"* claims **c**, and *"b for the predicate, a for the emulated rows, b for the
  arithmetic"* claims **b**. Taking any occurrence upgraded both of those rows a level.
* **Unrecognised means `unstated`.** There is no `c-inferred` fallback, so a cell reading
  "census" or "dead; would need one push site" acquires no level at all.

The 2026-08-23 exe sweep gets its **own** words — `sweep-proven` / `sweep-likely` / `sweep-guess`,
rendered dashed. Its "proven" was hand-typed a year before the chapters existed and is not the
chapters' `b-disassembly`; mapping one onto the other put pre-chapter guesswork and
chapter-verified disassembly in the same visual class. A row that any correction supersedes loses
its evidence badge entirely and shows `superseded` instead.

### Supersession is computed, not hand-listed

A row can be wrong because a *different* chapter retired it. `registry-blackboard.md § 11` has a
table headed *"NOT SAFELY TUNABLE — the rows that were earned the hard way"*, and its first row
retires `team+0xb3c4`, which `ball-carrier-brain.md` calls "the largest single on-ball lever
found": it is a transient AI directive with no file, no table and no persistent setting behind it.
Three sources now drive the `superseded` badge automatically —

1. `dt270_effective` overrides whose verdict is `inert` or `unresolved`,
2. every entry in the `fixed` list (matched on its quoted subject and on any address it names),
3. the chapters' own retirement tables, matched on the field token they retire,

— on top of the hand list in `exe_lever_notes`. The retirement only fires when the retired field
is the row's **own subject**, not merely mentioned in its effect text.

### Statuses in the dt270 view — `read` is not `effective`

| Badge | Meaning |
|---|---|
| `live` | a chapter proved the **effect**, not just the read |
| `read` | a reader is proven; the effect is **not** |
| `inert` | provably does nothing, with a citation — either the read was traced and the value shown to be discarded (`marginPredictionFrameAdjust`), or a chapter checked and found **no reader at all** (`trap.trapLoss`). The badge deliberately does not say "read": half these rows are not read, and the 2026-08-23 badge that did say it overstated the evidence. |
| `unread` | no reader found; trust bounded by the object's own `unread_confidence` |
| `unlocated` | no `get()` site found at all — **not evidence of anything** |
| `unresolved` | the object's fetch site is unsound (`ballplayer`); treat as not tunable |

---

## How to regenerate

From this worktree. Both commands are read-only: nothing is written to the game, the exe or the
CPK.

```bash
# the JSON (build/gameplay_catalog.json)
python tools/gameplay_catalog.py --toolrepo "<checkout with tools/data/patches>" build

# the page (build/gameplay-catalog.html, self-contained)
python tools/gameplay_catalog.py --toolrepo "<checkout with tools/data/patches>" html

# the measured install state alone, to the terminal
python tools/gameplay_catalog.py --toolrepo "<checkout with tools/data/patches>" state

# grep questions, levers, dt270 fields and negatives at once (the page's search box filters
# ONE view at a time, and the tabs show the hit count in the others)
python tools/gameplay_catalog.py search "standoff"
```

`--toolrepo` (or `$EF_TOOLREPO`) only matters when this checkout does not carry
`tools/data/patches`, `tools/data/tunings` and `build/exe_patch_state.json`; it defaults to this
repo. Nothing is ever written there.

Re-run after a Konami patch — `dt270_schema_gen.py` and `exe_map.py` first, because addresses
and field offsets move.

### The moving parts

| File | Role |
|---|---|
| `tools/gameplay_catalog.py` | the generator: merges, measures, emits |
| `tools/catalog_chapters.py` | parses the eight chapters out of `docs/*.md` |
| `tools/catalog_html.py` | the page template, one `/*DATA*/{}` placeholder |
| `tools/data/catalog_questions.json` | the 86 curated question rows |
| `tools/data/attr_index_map.json` | the attribute id ↔ UI-name table, rendered in the dt270 view |
| `tools/data/catalog_corrections.json` | stale-entry fixes, read-but-inert overrides, orphan objects, gaps |
| `build/dt270_liveness.json` | per-field status + readers for 245 objects / 21,977 fields |
| `build/exe_full_map.json` | the 2026-08-23 exe sweep |

The generator prints a **WARN** line for any chapter whose sections it failed to parse, **and for
any table that harvested fewer rows than it has row lines**. An empty harvest is a silent
catalogue bug, so treat any warning as a build failure. The one expected line today is
`match-ai-decoded.md: no Tunables table in this chapter` — that chapter genuinely has no such
section, which is why the warning says so instead of reporting zero rows.

---

## "Applied right now" is measured, not looked up

The old generator read `build/exe_patch_state.json` — a bookkeeping journal — and would today
render **27 false "applied" chips**. This one compares bytes.

* **exe**: installed `sha1 d2b84d1c…` is **byte-identical to `eFootball.exe.PRISTINE`**. Nothing
  is patched. PRISTINE itself is **not stock**: 2 bytes differ from `eFootball.exe.STOCK` at
  `0x6e6eee3`/`0x6e6eee4` — a hostname (`pes22-game.cs.ko` → `pes99-game.cs.ko`) that severs
  matchmaking and touches no gameplay code.
* **per pack**: three states — `on` / `off` / `not-applicable` (the expect bytes match nothing in
  this image, so the spec was built against a different base) — plus **`revert-shaped`**, which
  flags a spec whose *patch* bytes **are** the stock bytes. Those read "applied" on a pristine
  exe and mean nothing: `balloon-fix`, `cave-remove`, `gait-revert`, `knuckle-off`,
  `sideways-fix`. Of 119 packs: 105 off, 6 not-applicable, 5 mixed, 3 "on" — and all three of
  those are revert-shaped.
* **dt270 is a separate install state, and it is NOT pristine.** Installed
  `sha1 ebdfce5a…` vs pristine `501f9880…`. The exe being stock says nothing about the data
  pack. This asymmetry is the single most important thing on the page's first screen, and the
  old catalogue had no way to express it — which is exactly how it printed our own August values
  as the game's.
* **per tuning**: each tuning's `edits[]` are read back out of the installed pack.
  `compact-and-tight` (8/8) and `faster-ball` (6/6) match. **Same caveat as the exe packs**: a
  tuning whose edits restore stock values reads "on" for that reason alone (`faster-ball`'s own
  notes say "back to stock"), and no pristine dt270 pack is available to this tool to tell a
  revert from a change.
* **the CPU difficulty table** is re-dumped from PRISTINE at every build — 44 rows × 10 columns
  at `0x146c06f40`, stride `0x2c`, value at `+4+col*4`. The installed image matches it byte for
  byte. This is the corrective source for a chapter that dumped row `0x14` from our patched
  image and says so.

---

## What it deliberately does NOT cover

* **It is not a patch tool.** It never writes to the game. Applying anything is still
  `exe_patch.py`, `gameplay_tune.py` and `live_patch.py`, and the risk tiers in
  `pad-input.md § 12` still apply: a `.text` RW write is tier 1, `.tls$` needs `VirtualProtect`,
  an `.xcode` write is integrity-checked and is an experiment rather than a setting.
* **It does not re-derive anything.** Every row is traceable to a chapter section or to a tool
  output taken at build time. Where the chapters are silent, the catalogue is silent — it does
  not fill gaps with plausible reasoning.
* **It does not carry the whole dt270 surface.** 22 gameplay-relevant objects out of 245. The
  other 223 (stadium, demo, tutorial, sugoroku, pathToGlory scenery, and the 5,548 bound-but-
  never-measured fields) are in `build/dt270_liveness.json` and `docs/dt270-residue.md`.
* **It does not own the exe sweep's attribute names.** Four areas were re-checked address by
  address for this rebuild — Physical & locomotion, Goalkeeper, Attribute model, Tackling/fouls.
  Shooting, Passing, Set pieces, Dribbling, Stamina, Match RNG and Ball physics were checked by
  lever **name** only. Treat their attribute names with the same suspicion until re-derived.
* **It does not claim the six `setplayGuide*` objects work.** They are 100 % "read" in the
  liveness file and **no chapter mentions them**. They are carried with an explicit
  *no chapter owns this* banner rather than promoted.
* **It does not distinguish a dt270 revert from a dt270 change** (see above).
* **It is not a runtime debugger.** Anything needing a live read — above all whether
  `URandomInfo+0x08` is ever written — stays an open question here.

---

## What was wrong, and is now fixed

Thirty entries, all visible in the State view. The ones that cost the most:

1. **Every displayed dt270 value was our August build, labelled "what's installed right now".**
   Sampled drift: `ball.magnusRate` 0.06 → **0.035**, `ball.nonSpinRate` 1.35 → **1**,
   `trap.ballControlRate` 0.8 → **1.0**, `basePosition.spaceCoverRate` 0.45 → **0.33**,
   `lengthOf` 35 → **28**, `dfLineCloseRate` 0.55 → **0.7**, `lastLineCloseMaxRate` 0.8 →
   **0.95**, `marginPredictionFrameBase` 6 → **0**. Values are now read from the installed CPK at
   every build.
2. **`marginPredictionFrameBase = 6` was OUR edit.** Stock is **0**.
3. **`trap.ballControlRate` is not Ball Control.** It gates **Tight Possession (0x19)**; Ball
   Control (0x18) has no reader in the trap family at all. And it ships at **1.0**, at which a
   TP-99 player's term saturates and he is mathematically incapable of a bad touch.
4. **`marginPredictionFrameAdjust` was listed "proven".** It is **read but INERT** — multiplied
   by the `−0.0f` cell `0x147850538` and truncated. The anticipation cave built on it is refuted.
5. **`forceDashDistDefence`'s inertness had the wrong reason.** Not an unconditional overwrite: a
   correlated branch tests `byte[r14+0x28d]` twice with the same sense. `forceDashDistOffence` is
   fully live. That shape is invisible to every dead-load detector this project has.
6. **Ten defensive-line fields rendered "unverified"** (`dfLine`, `dfLineRate`, `dfLineCloseRate`,
   `lastLineCloseMaxRate`, `keepDfTargetLineX`, `backOffsideLine`, `lengthOf`, `minWidth`,
   `adjustZCompact`, `lineControl`). All have proven readers. The catalogue showed doubt where the
   chapters show proof — that silence misdirected months of tuning.
7. **`passget` was listed 52 unverified / 4 inert — effectively dead.** 26 of its fields are read
   at **depth 0**, inside `PassGetRoute*` vtable methods themselves. They are the safest levers in
   the executor subsystem. The single most consequential omission in the old catalogue.
8. **Attribute indices were on the superseded `+0x15` alignment.** `0x16` is GK Awareness, not
   Speed (`0x28`); `0x2a` is Balance, not Acceleration (`0x2c`); `0x17` is **Dribbling**, not
   Defensive Awareness (`0x15`); `0x18` is Ball Control and `0x22` is Curl, not "gk_decision" and
   "catching".
9. **`0x145663b52` was filed under the goalkeeper.** It is inside
   `match::ai::bp::Personality::update` — the ball-carrier personality recompute.
10. **"The single highest-impact goalkeeper lever, `0x143f0f2e1`"** appears in **none** of the
    eight chapters. The decoded high-impact GK levers are the save-quality output floors
    (`0x1440329b0`, `0x1440329d9`, `0x144032940`) and the `Deflect::vf35` GK-Reach-≥-85 cliff.
11. **`ActionMark::vf20` was listed as marking tightness.** It is a fixed-radius steering point,
    not the destination — which makes our shipped 45°→90° patch a likely placebo.
12. **The booking model was a "30 % RandInt".** No chapter corroborates it; the decoded model is a
    deterministic severity ladder (40 outside the box, **60 inside**, yellow 80, red 110), and all
    six bytes are identical in PRISTINE, INSTALLED and STOCK.
13. **The difficulty entry named row 0 as the reaction delay.** The carrier reaction rows are
    `0x17`/`0x18`/`0x19` at stride `0x2c`; an earlier emulation used stride 40 and read the table
    inverted.
14. **"Where CPU decisions live" listed `ActionSelectorScore::vf2` as an unmapped guess** and named
    `match::ai::Judge` as a decision oracle. Judge has no direct caller anywhere in the image, and
    both brains are now fully decoded across two chapters.
15. **`shoot.control_dy` was marked live across the subtree** by prefix matching; `gageMax` has
    **zero** readers. Prefix matching is gone — the join is per field.
16. **`ballplayer` was "proven".** It has no sound fetch site; the four "read" fields' readers are
    `[r14+K]` loads where `r14` holds `grounderpass`. Flipped to `unresolved`, layout kept as
    documentation.
17. **`gksPenaltyLineRateX_DF` and the `gks*` set were offered as set-piece levers.** 14 of the 20
    `gk*`/`gkl*` fields have no reader, and the six that do are the **outfield** goal-kick shape.
18. **`positionPK_*` would have rendered "unlocated"** from the liveness file. That is an artefact
    of a by-name fetch, not evidence: they are located, live, and the safest lever in the set-piece
    chapter. Overridden with the citation.
19. **The mishit-spin block is flagged, not fixed.** No chapter re-derives `0x144018c10`, and the
    project's own note records it as a velocity re-clamp, not a spin builder, with the ball frame
    Y-up rather than Z-up. Re-derive before trusting those four levers.
20. **`(ours: 36 outside)` on the foul threshold** is stale — stock is 40 and nothing is applied.
    A correction that tried to change this was itself withdrawn on 2026-09-20; recorded as a
    near-miss.

---

## What the 2026-09-20 FIRST CUT got wrong, and is now fixed

Two adversarial reviews of the rebuilt catalogue found nine defects. All nine are fixed in the
generator, not in the emitted HTML.

1. **24 of the 33 rows in `player-executors.md`'s Tunables table were silently missing.** One
   row's cell wraps onto a second physical line, which leaves it without a closing `|`; the table
   scanner stopped there, truncating that row to two cells and dropping the 23 after it. The lost
   rows were disproportionately the honest ones — the per-slot marking mode (`teamObj+slot*0x44+0x2b0`,
   "no writer was found"), the per-team line field, `ActionDiagonalRun`'s unlocated +5 m depth, the
   offside-trap rows, the Overlap heading caps, the GK save-quality floors, the −80.0 receiver
   penalty, the attribute `0x19` correction — in the subsystem that answers *"why does my
   centre-back stand off"*. `parse_tables` now folds continuations, and `verify()` compares
   harvested rows against row lines and warns on any shortfall.
2. **`team+0xb3c4` was still rendered as a live lever, twice.** The registry chapter's retirement
   table was skipped because its header does not begin with `what`. It is now harvested, and the
   supersession pass described above marks both the Levers row and the Subsystems "enables" row.
3. **`basePosition.marginPredictionFrameAdjust` said INERT in one tab and "proven, patch it up to
   5-15" in another.** Supersession is no longer driven by a five-entry hand list; the same
   `dt270_effective` override that badges the field `inert` now strikes the exe-map row.
4. **Evidence levels were being upgraded.** `"**c** (bytes are b)"` was badged `b-disassembly`;
   unrecognised cells fell through to `c-inferred`; the sweep's hand-typed "proven" was mapped onto
   `b-disassembly`. Leading-tag rule, `unstated` fallback and the `sweep-*` vocabulary, above.
5. **Route classification defaulted to `exe-code`.** Rows from a table headed *"why it cannot be
   executed"* were being filed as exe-code levers, and `"app already writes them (Player.bin bits
   374/440)"` was too. New keyword set, no default, `unclassified` bucket.
6. **`"N more identical records"` was asserted without ever comparing them,** and was false in all
   eight families it was applied to (`positionPK_*.playerData` 22 records, 22 distinct;
   `ballplayer.TurnData` 1,440 records, 1,298 distinct). The note is now measured, and the four
   `positionPK_*` objects render all 22 penalty positions — the set-piece chapter's flagship lever.
7. **The State view's pack descriptions were unreadable.** They were clamped to four lines with an
   unclamp rule that expected a `<details>` wrapper nothing emitted, so the payload of the view
   existed only as a 2,700-character tooltip. Wrapped.
8. **Tuning verdicts ignored the edits they could not read.** `loose-realism-v1` read **off** on 34
   measured edits out of 155, with 121 never read at all. A tuning whose unreadable edits outnumber
   its readable ones is now **indeterminate**, and the unread count is on the badge.
9. **Smaller things:** the dt270 pack's install state is now a chip on the first screen next to the
   exe chip; the exe-map value column is headed *Sweep 2026-08-23* rather than *Now*; Q55's two
   addresses are cited to the chapter that actually holds them; the dead `.tag\.NOT` selector is
   gone; the Levers view has subsystem filter chips; the tabs carry per-view hit counts and the
   empty state says which view holds the hits; two curated questions were added — *"What should I
   NOT bother trying?"* and *"Which of the patches we already shipped are placebos?"*; and the
   attribute id ↔ UI-name table is rendered in the page instead of being a pointer to a JSON file.

---

## The holes that block the most questions

Eighteen are listed in the State view. The three that matter most:

1. **Is `URandomInfo+0x08` ever written?** If it is not, the carrier's per-possession random `r`
   is constant 0.0 all match, four carrier tunables collapse, and the CPU penalty-aim index never
   leaves 0. **One live read at `0x145653e5f` settles it**, and nothing downstream should be
   touched first.
2. **Which action id runs which executor.** Proven *not* to be a table. Until it closes, "if I tag
   a player with run kind X, what code moves him?" has no answer, and "kind 6 never runs" is
   unproven in both directions.
3. **Who posts contact event kind `0xe`.** Everything downstream is decoded, so "more contact →
   more fouls" is unproven at exactly the step that matters.
