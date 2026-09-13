# Decisions log

Choices that aren't obvious from the code, and why. Append, don't rewrite.

## 2026-08-18 — Phase 2 built before Phase 1

The plan's build order is 0 → 1 → 2, but Phase 1 is hard-blocked: it derives its schema from
real CSV exports, and `CLAUDE.md` forbids guessing column names. Phase 2 is explicitly "pure
C#, no I/O", so it depends on nothing the game provides and could be built immediately.

Phase 1 still comes before Phase 3 and 4. This only reorders the two steps that are
independent of each other.

## 2026-08-18 — Typed ids in ML.Core

`PlayerId` / `TeamId` / `LeagueId` are `readonly record struct` wrappers rather than bare `int`.
Fixture generation and writeback both shuffle ids between slots constantly, and a home/away or
team/player mixup is silent at runtime. Costs a Dapper type handler each in Phase 1, once.

## 2026-08-18 — `Player.TeamId` is authoritative, `Team` holds no squad list

`World` maintains the squad index and mediates every assignment. Keeping a list on `Team` as
well would be a second copy of the same fact, and the two drift the first time a transfer takes
an unusual path. `WorldInvariants` checks the index and the player agree anyway.

## 2026-08-18 — Budgets floor at zero rather than going negative

`Team.DebitUpTo` pays what it can and returns the shortfall; `Team.Debit` throws. The Phase 2
milestone requires no negative budgets, so the type makes it unrepresentable instead of relying
on every caller checking. Shortfalls are reported in `RolloverReport` so Phase 5 can turn them
into forced sales.

## 2026-08-18 — Head-to-head is a mini-table, ties break by id

The plan specifies points → GD → GF → head-to-head. Head-to-head is resolved over only the
fixtures between the tied clubs. Real competitions sometimes re-apply the whole chain
recursively; this doesn't. Anything still level orders by id, because a table that reorders
itself between two reads of identical data would be worse than an arbitrary but stable tiebreak.

## 2026-08-18 — No goalscorer simulation in Phase 2

`match_events` is in the plan's schema, but Phase 2's milestone doesn't need it and Phase 5
owns progression driven by minutes and performance. The simulator returns a scoreline only.

## 2026-08-18 — No image library in ML.Ingest yet

Phase 3 needs to crop screenshot regions before OCR. ImageSharp 4.x now requires a paid licence
key and 2.1.9 carries a known moderate CVE (GHSA-rxmq-m78w-7wmc), so neither is a good default
to bake in months early. `Tesseract` is referenced; the cropping library gets chosen when Phase
3 is actually written. `System.Drawing.Common` is the likely answer given this is Windows-only,
but it would push `ML.Ingest` and `ML.App` to a `net8.0-windows` target, which is worth deciding
deliberately rather than by accident.

## 2026-08-18 — Tesseract model committed to `tools/`, ignored by git

`eng.traineddata` (15 MB, from `tesseract-ocr/tessdata_best`) lives in `tools/tessdata/` and is
gitignored. It's a build input, not source. Re-fetch with:

```bash
curl -sL -o tools/tessdata/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata
```

## 2026-08-18 — Squad rules are placeholders

`SquadRules` defaults (18–35 players, 2 GK) are guesses. Phase 0 step 6 measures the real
limits. Phase 4 refuses to emit a CSV that violates them, so a wrong value here either blocks a
legal transfer or lets a corrupt squad through.

## 2026-09-14 — Results come from efootball-re's stats host; OCR, video and memory scans deleted

Supersedes the two 2026-08-18 Phase 3 entries above (image library, Tesseract model). Screenshot
OCR, OBS recording analysis and the external ReadProcessMemory readers are gone, along with
Tesseract, ImageSharp and the research scanners behind them. efootball-re's host runs inside the
game and writes each finished match to `ml_stats\match_*.json`: per-player counters keyed by
dt200 PID, and team totals that matched the full-time screen in its recorded match.

- An export belongs to a fixture only if at least 3 players on each side resolve to that club's
  `game_pid`. Team names and the game's home/away never decide it.
- Ratings are a C# port of efootball-re's `mlstats/rating.py`, pinned to its output by
  `samples/ml-stats/*.expected-ratings.json`.
- The export has no possession percentage. `possession` is the share of possession time
  (counter 0x4B), which read 74/26 against the screen's 70/30 in the one match checked. Switch to the
  game's own figure once the host exports it.
