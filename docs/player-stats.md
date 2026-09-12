# Player match stats — what the engine tracks, and how to read it

Recovered from `eFootball.exe` and dt270 (2026-08-24). Two separate systems are involved and it
matters not to conflate them:

| | Where it lives | Editable? | What it is |
|---|---|---|---|
| **Rating formula** | dt270 `constant_match.bin` -> `rating.o` | YES — plain data | Weights that turn counters into a 0-10 rating |
| **Raw stat counters** | Process memory, per player, during a match | Read-only | The actual events: passes, shots, tackles, touches |

Pass completion %, shots on target, duels etc. all come from the **counters**. The rating is a
*derived* number computed from them.

---

## 1. The rating formula is live, editable data

`rating.o` carries four formula STRINGS — `df_rate`, `mf_rate`, `fw_rate`, `gk_rate`. These are
**not documentation**: a compiler at match init (`0x1442a45d0` -> `0x1456cd0b0`) turns each into a
0xC04-byte program inside the match record, and `0x1442a0f90` -> evaluator `0x1456cc690` runs the
one matching the player's position (jump table `0x1442a11f8`: 0=GK, 1-2=DF, 3-6=MF, 7-9=FW). The
result is the raw score that the scorer `0x14429ea40` normalises into the 0-10 rating.

Stat names inside the strings resolve through the game's own registry at `0x147735d00` (89 entries
of `{const char* name; accessor}`); every `StatsPlayer*` accessor is a thunk
`mov edx,<ROW>; call 0x1456d1050`, which reads that row with **mode 5**.

**Fail-safe to respect:** an unparseable formula compiles to zero instructions and the evaluator
returns 0.0 — flat-lining every rating. Only use stat names already present in the shipped formulas.

Tool: `python tools/rating_weights.py show | set <pos>.<Stat>=<w> --apply | restore`. Strings are
patched in place, so a replacement must be **same-or-shorter**; the tool minifies first, freeing
~170 bytes per formula.

### Current weights (per position)

| Stat | DF | MF | FW | GK |
|---|--:|--:|--:|--:|
| Goal | +80 | +75 | +75 | +60 |
| OwnGoal | -60 | -50 | -40 | -60 |
| Assist | +40 | +40 | +40 | +50 |
| CardRed | -40 | -40 | -50 | -40 |
| TeamMyScore | +5 | +10 | +20 | +5 |
| GKShootPA | · | · | · | +20 |
| PKGoal | -18 | -18 | -18 | -15 |
| Clear | +3 | +4 | +4 | +15 |
| SnatchedDuringDribble | -10 | -5 | -1 | -15 |
| SnatchedDuringPass | -10 | -5 | -1 | -15 |
| GKSave | · | · | · | +15 |
| TeamEnemyScore | · | · | · | -15 |
| PassLongSuccess | +12 | +7 | +5 | · |
| FKGoal | -10 | -10 | -10 | -10 |
| TackleSuccess | +8 | +8 | +10 | · |
| CardYellow | -5 | -5 | -10 | -5 |
| SnatchByPassCut | +10 | +10 | +10 | +3 |
| SnatchByTackle | +10 | +10 | +10 | +3 |
| SnatchByBlock | +10 | +10 | +10 | +3 |
| SnatchByWedge | +10 | +10 | +10 | +3 |
| UnqDribbleAttack | +10 | +10 | +8 | · |
| TeamWin | +10 | +10 | +10 | +10 |
| Shoot | · | · | · | +10 |
| Foul-OffSide (fouls, offsides excluded) | -8 | -8 | -8 | · |
| CenteringSuccess | +7 | +7 | +7 | · |
| UnqShootShort | +6 | +6 | +5 | · |
| PassShort-PassShortSuccess (misplaced short pass) | -6 | -4 | -4 | · |
| CutPass | · | · | · | +5 |
| UnqShootMiddle | +4 | +4 | +4 | · |
| ShootInFrame | +3 | +3 | +3 | · |
| PassThrouhSuccess | +3 | +3 | +3 | · |
| DispossessDelay | +3 | +3 | +3 | · |
| DispossessPress | +3 | +3 | +3 | · |
| UnqShootLong | +2 | +2 | +2 | · |
| PassShortSuccess | +0 | +1.5 | +1.5 | · |
| BallTouch | +0.2 | +0.3 | +0.7 | · |

Notes worth knowing:

- **`Foul-OffSide`** is one term: fouls *minus* offsides. An offside increments BOTH the foul row
  and the offside row, so Konami subtracts one from the other to recover "real fouls".
- Penalty and free-kick goals are **discounts** applied on top of the plain `Goal` weight, not
  separate credits — a penalty is worth less than an open-play goal.
- `BallTouch` is a per-touch trickle (a FW gains ~3.5x what a DF does per touch).

### How the raw score becomes 0-10

1. `rate = rawScore / minutes played` (minutes floored to 45)
2. min/max/mean taken across **all 80 slots of both teams** — no position grouping
3. `base = baseRatingMin + 0.5*floor(2*(baseRatingMax-baseRatingMin)*norm)`
4. minus a **`subValue` percentile penalty** (SUBTRACTIVE; entries <= 0 are discarded)
5. plus flat `addPoint` bonuses (brace, hat-trick, many saves, repeatedly dispossessed...)
6. clamped to `[ratingMin, ratingMax]`

**The binding constraint is `baseRating*`, not the clamp.** Shipped 5.0/7.0 gives only five
discrete steps {5.0, 5.5, 6.0, 6.5, 7.0} — the real reason every player clusters near 6.5.
Players with under 5 minutes are forced to 0.0. `baseRatingMedian` and `addPoint.assist_over4` are
dead fields — never read by the game.

---

## 2. Where the raw counters live in memory

```
RecordSlot                                    (~1.3 MB match record object)
  + 0x1c4 + (team*0x28 + player)*0x10         -> float32 final rating (0-10)
  + 0x1c0 + (team*0x28 + player)*0x10         -> float32 raw score (pre-normalisation)
  + 0x78118                                   -> statsContainer
  + 0x106440                                  -> int32[0x867] team/match aggregate totals

record = statsContainer + 0x65C0 + team*0x38238 + player*0x13E8    (accessor 0x1442e6640)
  record + 0x10 + row*0x24 + col*4            -> int32[0x77 rows][9 cols]  (getter 0x1443378c0)
  record + 0x10cc                             -> uint8 min ability; 0xFF = DID NOT PLAY
  record + 0x10cd                             -> uint8 max ability
  record + 0x10e0                             -> int32[13] per-position play counters
```

**Columns are time buckets, not made/attempted.** The column is chosen by match period: first half
-> col 0/1/2 (minute <=15 / <=30 / >30), second half -> col 3/4/5, ET1 -> col 6, ET2 -> col 7,
penalty shootout -> col 8. **Mode 5 = c0+c1+...+c7** (eight columns) and is what every rating term
reads — so regulation and extra time count; shootout events do not.

### Pointer chain at runtime

```
singleton     = *(u64*)0x1486bd888
RecordControl = singleton + <offset not pinned statically>
RecordSlot    = *(u64*)(RecordControl + 0x6288)
```

The last hop is not pinned, so `stats_read.py` **signature-scans instead**: the rating array is 40
float32 per team at stride 0x10, all inside the clamp range. Find that run, subtract 0x1c4, and you
have RecordSlot — no pointer chain needed. (The scan math is unit-tested against a synthetic
planted array.)

---

## 3. Attempts and completions are SEPARATE ROWS

This is the key insight for completion percentages. `StatsPlayerPassShort` and
`StatsPlayerPassShortSuccess` are two different accessors reading two different rows:

```
pass completion % = row 0x1b (pass_short_success).total / row 0x1a (pass_short).total * 100
```

### Proven rows (from the game's own name registry)

| Row | Stat | | Row | Stat |
|---|---|---|---|---|
| `0x00` | StatsPlayerGoal | | `0x3a` | StatsPlayerClear |
| `0x01` | StatsPlayerOwnGoal | | `0x3c` | StatsPlayerFoul |
| `0x02` | StatsPlayerFKGoal | | `0x3d` | StatsPlayerOffSide |
| `0x03` | StatsPlayerPKGoal | | `0x3e` | StatsPlayerCardYellow |
| `0x04` | StatsPlayerAssist | | `0x3f` | StatsPlayerCardRed |
| `0x06` | StatsPlayerShoot | | `0x42` | StatsPlayerFK |
| `0x10` | StatsPlayerShootPK | | `0x43` | StatsPlayerIndirectFK |
| `0x11` | StatsPlayerShootSuccess | | `0x44` | StatsPlayerCK |
| `0x16` | StatsPlayerShootInFrame | | `0x46` | StatsPlayerDribble |
| `0x18` | StatsPlayerPass | | `0x47` | StatsPlayerDribbleSuccess |
| `0x19` | StatsPlayerPassSuccess | | `0x48` | StatsPlayerBallTouch |
| `0x1a` | StatsPlayerPassShort | | `0x4f` | StatsPlayerSnatchTotal |
| `0x1b` | StatsPlayerPassShortSuccess | | `0x50` | StatsPlayerCutPass |
| `0x1c` | StatsPlayerPassThrouh | | `0x57` | StatsPlayerSnatchByTackle |
| `0x1d` | StatsPlayerPassThrouhSuccess | | `0x58` | StatsPlayerSnatchByBlock |
| `0x1e` | StatsPlayerPassLong | | `0x5a` | StatsPlayerSnatchByWedge |
| `0x1f` | StatsPlayerPassLongSuccess | | `0x61` | StatsPlayerSnatchedTotal |
| `0x20` | StatsPlayerCentering | | `0x63` | StatsPlayerSnatchedDuringDribble |
| `0x21` | StatsPlayerCenteringSuccess | | `0x66` | StatsPlayerSnatchedDuringPass |
| `0x34` | StatsPlayerTackle | | `0x6d` | StatsPlayerGKShootFaced |
| `0x35` | StatsPlayerTackleSuccess | | `0x6e` | StatsPlayerGKInframeShootFaced |
| `0x36` | StatsPlayerDispossessDelay | | `0x6f` | StatsPlayerGKSave |
| `0x37` | StatsPlayerDispossessPress | | `0x70` | StatsPlayerGKShootPA |

### Attempt/success pairs (-> percentages)

| Metric | Attempts row | Success row |
|---|---|---|
| pass (all) | `0x18` | `0x19` |
| short pass | `0x1a` | `0x1b` |
| through ball | `0x1c` | `0x1d` |
| long pass | `0x1e` | `0x1f` |
| cross | `0x20` | `0x21` |
| tackle | `0x34` | `0x35` |
| dribble | `0x46` | `0x47` |
| shot -> goal | `0x06` | `0x11` |
| GK shots faced -> saves | `0x6d` | `0x6f` |

A further **30 rows** are named with lower confidence (shot sub-types, pass-direction buckets,
ball-won/lost causes) — see `build/rating_weights_rows.json`. Unnamed rows are still dumped as
`row_NN`, so no data is lost.

---

## 4. Reading it out

```bash
python tools/stats_read.py scan                 # locate the match record block
python tools/stats_read.py dump                 # every player: rating + named stats + %
python tools/stats_read.py dump --raw           # include unnamed rows and raw columns
python tools/stats_read.py save --fixture 123   # write into the app DB
python tools/stats_read.py correlate --side home --slot 0   # one player, to name unknown rows
```

Writes `match_player_stats(fixture_id, side, slot, stat, value)` including derived `*_pct`
completion rates, alongside the existing `match_player_ratings` and `match_team_stats` tables.

### Is reading memory safe?

Yes. The process is opened **read-only** (`PROCESS_VM_READ`, deliberately not `VM_WRITE` /
`VM_OPERATION`). No injection, no debugger, no thread suspend. `ReadProcessMemory` has the kernel
copy pages out; the game is neither modified nor paused. It is the same read-only path
`mem_probe.py` / `mem_scan.py` proved on this game and that `read_match_memory.py` already uses.

Timing matters: run it while the game is still on the full-time / results screen. Once you leave
the match the record is torn down.

---

## 5. Automation status

| Piece | State |
|---|---|
| Team stats + player ratings | **Automatic** — `ML.App/SessionMatchMemory.cs` invokes `tools/read_match_memory.py` at full time |
| Deep per-player counters | **Manual** — `stats_read.py`, and **not yet validated against a live match** |

To make the deep stats automatic: (1) validate `stats_read.py dump` on one real match — every
offset above came from static analysis and needs one empirical confirmation; (2) merge it into
`read_match_memory.py` so the app's existing auto-invoke picks it up, needing no new plumbing.

**Known discrepancy to settle during validation:** `read_match_memory.py` locates ratings with a
**24-byte stride** and a `-1` marker, while the map above has the engine's rating array at a
**16-byte stride**. These are probably two different arrays (results-screen UI vs engine record).
One live match settles it.

---

## 6. Gotchas

- `record+0x10cc == 0xFF` means **did not play** — skip the slot; unused slots are not zeroed.
- Mode 5 sums **eight** columns (c0..c7), excluding c8 — penalty-shootout events are invisible to
  the rating and to any mode-5 total.
- `ratingMax` sits at a **lower** struct offset than `ratingMin`; the schema names and the code
  agree, but the ordering is counter-intuitive.
- The rating-array scan range must track the dt270 clamp (`rating.ratingMin`/`ratingMax`) — widen
  the clamp and you must widen `RATING_LO`/`RATING_HI` in `stats_read.py` to match.
- 40 slots per team are allocated; only ~11-18 are ever populated.

## Source files

- `build/ratings_stats_map.json` — memory-layout trace
- `build/rating_weights_rows.json` — full row map with per-row evidence
- `build/rating_formula_table.json` — parsed per-position weights
- `tools/stats_read.py`, `tools/rating_weights.py`
## 7. Ordering trap when editing

`gameplay_tune.py apply <tuning>` rebuilds the pack **from pristine**, which discards any formula
string edit `rating_weights.py` has stacked on top. So always apply in this order:

```bash
python tools/gameplay_tune.py apply tools/data/tunings/loose-realism-v2.json   # numeric fields first
python tools/rating_weights.py set all.Foul-OffSide=-8 --apply                 # formula strings last
```

Re-run `rating_weights.py show` after any tuning apply to confirm your weights survived — this
document was generated from the live pack and caught exactly that regression once.
