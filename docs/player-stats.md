# Player and match stats — what we can read, and how

eFootball computes a full match sheet and a rating for every player, then throws it away when
you leave the results screen. Nothing is written to a file and nothing is exposed to a mod.
This is how we keep it: read it out of the running game's memory, read-only, at full time.

Status: **team stats and player ratings work** and are proven in-game. **Per-player counters are
now mapped and built** — `tools/stats_read.py` — but have never been run against a live match;
see [the runbook](player-stats-runbook.md) for the one-match validation.
The mapping work behind this is in [live-stats-extraction.md](live-stats-extraction.md).

## Reading stats after a match

1. Play the match in eFootball. At full time, **stay on the results screen** — the game must
   still be running. Once you back out to the menu the numbers are gone.
2. Alt-tab to ML.App → Dashboard → **📊 Read stats from game**.
3. You get a log line like `📊 team stats stored — pass completion 87% / 79% · 22 player
   ratings stored`, and the ratings box is prefilled with `Name 7.5` pairs zipped onto your XI
   in slot order (the recorder wants names, bare numbers land in its no-match bin).
4. Enter the score yourself — the reader does **not** read the score. Record.

Team stats come off the full-time **Team Stats** page and ratings off the **player ratings**
page; they're different screens. The reader takes whatever it can find in one pass, so a run
from the wrong page returns partial data rather than failing — check the log line says both.

From the CLI, with the game up on the same screen:

```bash
python tools/read_team_stats.py
```

That prints the whole sheet plus pass completion for both sides; `--json` for machine output.
[read_match_memory.py](../tools/read_match_memory.py) is the same thing plus ratings, JSON
only — that's what the app shells out to.

If reads come back empty, try an elevated terminal. `ReadProcessMemory` against another
process often needs it, and [mem_scan.py](../tools/mem_scan.py) documents elevation as a
requirement for its own scans.

## What gets stored

| Table | Contents |
|---|---|
| `match_team_stats` | 13 stats per side, per fixture: possession, shots, shots_on_target, fouls, offsides, corner_kicks, free_kicks, **passes**, **successful_passes**, crosses, interceptions, tackles, saves |
| `match_player_ratings` | One rating per player per side, ordered by results-screen slot |

Pass completion is derived, not stored: `successful_passes / passes`, per team.

**The stats are not on screen anywhere in the app yet.** `TeamStatsFor()` exists in
[SessionMatchMemory.cs](../src/ML.App/SessionMatchMemory.cs) and returns the sheet ready to
render, but no view binds it — after the capture log line scrolls away, the only way to see
the numbers is the database:

```bash
sqlite3 build/master.db "SELECT stat, MAX(CASE WHEN side='home' THEN value END) h, MAX(CASE WHEN side='away' THEN value END) a FROM match_team_stats WHERE fixture_id=? GROUP BY stat"
```

## How the reading works

Read-only `ReadProcessMemory` on writable data pages. No debugger, no injection, no DLL, and
nothing is ever written back to the game. Both structs are found by **signature every run** —
no address is hardcoded, so the reader survives restarts and relocation.

- **Team stats** — home/away pairs at 8-byte stride, led by a possession pair of float32s
  that sum to ~1.0, followed by a run of small non-negative int pairs. Candidates are filtered
  for realism (values ≤ 300, several zeros), and the one whose `passes` field is *changing* is
  preferred — that's the live match rather than a stale copy left in memory.
- **Ratings** — 24-byte per-player struct, rating float32 at +0, a `-1` sentinel at +12.
  A run of ≥8 consecutive valid ratings (0.5–10.0, rounding to a clean 0.5) identifies the
  array; the first 11 are the home XI, the rest away.

**Cheat Engine does not work on this game** and isn't the tool here — eFootball's anti-tamper
recognises CE specifically and every scan returns zero. A plain external process reading the
same memory is not blocked, which is why the whole toolchain is our own Python.

## Per-player counters — built, unvalidated

`tools/stats_read.py` reads the engine's per-player match record: 119 counter rows × 9 time
buckets per player, plus the rating, the pre-normalisation raw score, and the ability bytes.
Pass completion for one player is a row *pair* — `row 0x1b / row 0x1a` — not a column split.
It runs automatically as part of **📊 Read stats from game** and lands in `match_player_stats`.

The offsets came from static RE of the exe, and one correction was made against the original
hand-off: the rating array sits on **RecordControl**, while the stats container sits under
`*(RecordControl + 0x6288)`. Reading the container without that dereference returns plausible
garbage. Verified in the rating driver at `0x1442a0f90`, where the same register serves both.

Nothing here has touched a live match yet — follow [the runbook](player-stats-runbook.md).

## Not built yet

- **A stats screen.** The data is captured and stored; nothing renders it.
- **Score capture.** Separate path — 📷 Import score (screenshot OCR) or 🎞 Analyse recording
  ([video-capture.md](video-capture.md)). The memory reader deliberately doesn't do scores.

## Honest limits

- Offsets are signature-matched, not hardcoded, so restarts are fine — but a **game patch can
  still move or resize the structs**, and then the signatures need re-tuning.
- Ratings are rounded to the nearest 0.5, which is what the game displays.
- Read-only and offline-only. Never take this, or anything else in the repo, near Dream Team.

## Timeline

Mapped over two days, 2026-08-20 → 21: plan and `mem_scan.py` (c4cdaf6), the CE-vs-RPM finding
(df9242b), team stats working (b8566bd, hardened in 20afcaf), rating array located (8dd7e12),
wired into the app (b45ca73). Per-player counter mapping was scoped on the 20th and never
started.
