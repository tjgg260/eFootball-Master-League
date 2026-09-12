# Per-player stats — the one-match validation runbook

`tools/stats_read.py` reads every player's raw match counters out of the engine's live match
record. Every offset came from static reverse engineering; **it has never been run against a
live match.** The record is torn down when you leave the full-time screen, so you get one
window per match. This is how to spend it.

Read-only throughout: `open_proc(pid)` requests `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`
only, so the handle physically cannot write to the game — `live_patch.write_mem` would fail on
`VirtualProtectEx` for want of `PROCESS_VM_OPERATION`. No injection, no debugger, no thread
suspend.

## Before kickoff

None of this is possible once the screen is up.

```bash
python tools/stats_read.py selftest
```

12/12 must pass — that is the scan's window arithmetic checked against a synthetic buffer,
including the case where the rating array is the final window (an off-by-one there silently
drops it).

Then:

- Open **one elevated** terminal, `cd` to this worktree, and run `$env:PYTHONIOENCODING="utf-8"`.
- `python -c "import numpy"` to warm the import so the first scan isn't paying for it.
- Look up the fixture id in the app **now**.
- Set the game to borderless windowed so alt-tab is instant.
- Play 90 minutes: **no extra time, no shootout.** That makes `c6`/`c7`/`c8` a free falsifiable
  prediction — they must all be zero.
- Make **one second-half substitution** and note the minute. Note every goal's minute.

## At full time, in this order

Ordered by value-per-second, on the assumption the screen can be lost at any moment.

**1. Press F12 immediately.** Free, instant, and the only ground truth that outlives the
record. Screenshots land in
`C:\Program Files (x86)\Steam\userdata\1253972527\760\remote\1665460\screenshots`.

**2. Capture the raw bytes before interpreting anything.**

```bash
python tools/stats_read.py snapshot --out build/ft_snapshot
```

This writes the whole containing regions plus a `meta.json` holding every candidate, its
`+0x6288` pointer, and all 80 ratings read back. Everything below can be re-derived from these
files offline. If a hypothesis turns out wrong, this is the difference between re-testing it
tonight and waiting for another match.

**3. Run the twelve equations.**

```bash
python tools/stats_read.py verify
```

This sums each per-player row across a team's 40 slots and compares against the team-stats
struct that `tools/read_team_stats.py` already reads and that we already trust:
`0x18`=passes, `0x19`=successful_passes, `0x06`=shots, `0x16`=shots_on_target, `0x20`=crosses,
`0x34`=tackles, `0x50`=interceptions, `0x3c`=fouls, `0x3d`=offsides, `0x44`=corner_kicks,
`0x42`+`0x43`=free_kicks, `0x6f`=saves.

If all twelve hold, then in one shot you have confirmed the RecordControl base, the `+0x6288`
dereference, the `+0x78118` container, `+0x65C0`, both strides (`0x13E8` / `0x38238`), the row
indices, and the mode-5 eight-column sum. If none hold, the container is wrong.

**4. Dump and save.**

```bash
python tools/stats_read.py dump --raw > build/ft_snapshot/dump_raw.txt
python tools/stats_read.py correlate --side home --slot-no 0 > build/ft_snapshot/corr_h0.txt
python tools/stats_read.py save --fixture <ID>
```

**5. Only now navigate** to the other full-time tabs and F12 each one. Navigation is what tears
the record down, so it goes last.

## What the numbers should say

- **Rating agreement.** `scan` and `verify` both report `agree=N/M`: players whose rating read
  through the container path (`record + 0x1184`, where the driver copies it in at `0x1442a1153`)
  matches the rating array at `ctl + 0x1c4`. This is the cheapest possible proof the whole
  dereference chain is right. It should be M/M.
- **Squad shape.** `played=[N, N]` should be 11–18 per side, everything else `0xFF`. Slots are
  not zeroed, so a garbage container shows a nonsense spread instead.
- **Time buckets.** Columns are 1st half `c0`/`c1`/`c2` (minute ≤15/≤30/>30), 2nd half
  `c3`/`c4`/`c5`, ET1 `c6`, ET2 `c7`, shootout `c8`. Your half-time substitute must show
  `c0=c1=c2=0`; the player they replaced must show `c3=c4=c5=0`; every `c6`/`c7`/`c8` must be
  zero in a 90-minute game.
- **Scoreline.** Σ row `0x00` for a team, plus Σ row `0x01` for the other, must equal that
  team's goals.

## The stride question

`tools/read_match_memory.py` finds ratings at **24-byte stride with an int `-1` sentinel at
+12**. The engine record uses **16-byte stride** with the raw pre-normalisation score at
`+0x1c0`. Both readers now run against the same live record, and step 1's screenshot gives the
on-screen values. If both match the screen they are two different arrays — the compute-side
record and the results-screen UI array — and `meta.json` says which one the scanner landed on.

## What this match cannot settle

- `c6`/`c7` need a tie that goes to extra time; `c8` needs a shootout. Two more matches.
- Naming the remaining `row_NN` rows needs deliberate in-match actions across several matches;
  `correlate` is the tool for it.
- The `0x867` team-total ints at `RecordSlot + 0x106440` are unmapped. Start by searching the
  snapshot for the values in `read_team_stats.py`'s output, but disambiguating collisions needs
  two or three matches with different scorelines.
- Whether the record survives the transitions between full-time sub-screens is unknown — which
  is the whole reason the snapshot runs before you touch a menu.
