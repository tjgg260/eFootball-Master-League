# dt200 / dt870 — the database format, and how much of it is actually decoded

`dt200_console_all.cpk` carries the game's base database; `dt870_console_win.cpk` is the live
update layer that supersedes it. Both hold the same ~50 WESYS-wrapped tables under
`common/etc/pesdb/` and `common/etc/appearance/`. This document is the decode of record.

Decoding here had always been field-at-a-time: guess a bit window, correlate it against the
editor's 42,369-player export, declare it solved. That works, but it can never answer *how much
is left*, because nothing ever counted the bits no field claims. Everything below is built on
doing that count.

## Summary

### What was built

Decoding here had no way to measure itself, so the first move was three tools, not more guesses:
`pesdb_census.py` (buckets every bit as named / constant / unknown), `pesdb_locate.py` (brute-force
field finder, ranked by lift over baseline so a dominant class cannot fake a match) and
`tools/data/pesdb_schema.json` (one bit-indexed schema, consolidating four sources that had never
agreed on a format). "Fully decoded" now means `UNKNOWN == 0` and is checkable in one command.

### Where it got to

`Player.bin` 92.5% / 93.3% named; `Team.bin` **94.1%**, up from 3.2%; `PlayerAssignment` (both
layouts), `Tactics`, `TacticsFormation`, `City`, `TeamColor`, `Derby`, `CategoryTeamList`,
`CompetitionEntry`, `BootsList` and `GloveList` at 100%; `Country`, `Stadium`, `Coach`,
`CompetitionUnit`, `Playstyle`, `PlayerSkill` and the small catalogs cracked structurally.
`PlayerAppearance` remains the weak spot at 13.7% named.

### Things that were documented or assumed, and are wrong

The reason to read this document rather than the older ones:

| # | Believed | Actually |
|---|---|---|
| 1 | 12 position aptitudes, a clean 2-bit run at 576–599 | **10** aptitudes in that run — slots 578 and 582 are weak-foot accuracy and form. **13** aptitudes total, one per position |
| 2 | one date field (`loan_end`) | **two** — `contract_end` at bit 160 was undocumented |
| 3 | bytes 0–7 are a u64 "native PID" (Sider) | **two u32 club fields** (the Player Editor was right); and all four club/loan fields exist in dt870 at identical offsets |
| 4 | nationality = `u16@41 & 0x3FF` | **9 bits at bit 329**, not 10 at 328. Sider's read fails *silently*: Salah → El Salvador |
| 5 | `max_level` / `rating_grade` live in `Player.bin` | **not stored there** — nor are `squad_number_national` or `overall_rating` |
| 6 | WESYS flag `0x02` means "empty table" | a **third** shape: `comp == orig != 0` is *stored* — XOR, no zlib |
| 7 | catalog tables reference strings by id or hash | **plain inline UTF-8**, fixed-width, NUL-padded |
| 8 | 52 (export) or 66 (our map) player skills | `PlayerSkill.bin` declares **72** |
| 9 | `Team.bin` = one 48-byte English name at 396 | **bit-packed** record; name array starts at **116** — 21 language slots of **70** bytes |
| 10 | `TacticsFormation` stride 264 or 2,640 | **12**, with exactly 11 rows per formation; coordinates on a **21×21 grid** (depth odd, width ×4) |
| 11 | `CompetitionUnit` is mixed-size (75×2472 + 21×115) | **uniform** 2,472 — the "21×115" is the language array *inside* each record |
| 12 | `Country.bin` ≈ 107 records | **1,488 × 214** |
| 13 | `TeamColor.bin` = 64-byte records (vendored parser) | **20 × 3,179** — 63,580 is not divisible by 64 |
| 14 | `Coach.bin` 352 × 491 | **176 × 982** — 352 was two coaches per block |
| 15 | `CategoryTeamList` stride 24 | **12** — stride 24 showed two identical halves |
| 16 | `PlayerAppearance` holds build/height data | **height and weight are not in it**; `Player.bin` is the sole store |
| 17 | `Team.bin` has no stadium FK *(a negative found in this very session)* | it is at **byte 90** — a subset test over a 37-value id space was never reliable |

New things with no prior claim to correct: `City.bin` is a **latitude/longitude geolocation table**
(Oslo reads 59.91 N, 10.75 E); `CompetitionUnit`'s header encodes a competition **tree** plus the
**promotion/relegation pyramid** (6 reciprocal pairs, 0 broken); `GloveList.bin` is **exactly the
goalkeepers**; `Team.bin` **caches squad composition** as three age-band percentages that sum to
exactly 100; and `SpecialPlayerAssignmentKind.bin` holds the game's own **Master League regen
buckets** (`ML_NEWFACE_EUR`, `JAPAN_RESERVE`, …).

### Defects this surfaced in our own code

1. ~~**`tools/dt200_rename.py`** wrote a 48-byte team name into a 70-byte slot and left the other
   twenty language slots stale, so a renamed club read right in English and wrong in Japanese and
   Chinese.~~ **Fixed in `85b38bf`**, which also caught a second bug: `name_of()` tested `if o`, so
   the record at offset 0 sorted as an empty name.
2. **`tools/vendor/sider/pesdb.py`** nationality mask (item 4). `tools/game_world.py:151` inherits
   it, but reads `Country.bin`'s id the same doubled way, so the errors cancel and only **69 of
   23,519 players** fall through. Any *new* consumer gets double the true id.
3. **`tools/vendor/sider/pesdb.py`'s `parse_team_color_bin`** assumes 64-byte records for a file
   whose length is not divisible by 64 (item 13).

### Unresolved, and flagged rather than guessed

- **Match ability index `0x17`** now has three competing readings across three sessions. The note
  that "corrected" it to Dribbling cites `tools/data/attr_index_map.json` as proven — **that file
  does not exist anywhere on disk**. Needs an in-game decider before anyone spreads attributes.
- **`Playstyle.bin` bit 6** marks secondary-only styles but is *clear* on indices 34/35, which the
  repo treats as secondary-only. Open conflict.
- **`Tactics.bin` byte 8** diverges by phase for 184 dt870 teams and for none in dt200. Whether
  that means a team defends with a different style, or the byte means something else in the
  defensive row, is not established.
- **Fluid formation**: the two-formations-per-team mechanism is real and addressable, but shipped
  geometry is identical in 889 of 890 dt200 teams and all 881 dt870 teams.
- Where `max_level` and `rating_grade` actually live.

## The coverage contract

For a table with a fixed record stride, every bit lands in exactly one bucket:

| bucket | meaning |
|---|---|
| **named** | a field in `tools/data/pesdb_schema.json` claims it |
| **constant** | never changes across the whole table — padding, a format tag, or a field this build does not exercise. Carries no information, and is **not** counted as decoded |
| **UNKNOWN** | it varies across records and nothing claims it. This is the work remaining |

named + constant + unknown = 100%, so a table is fully decoded only when UNKNOWN hits zero.
Constant bits are reported separately on purpose: "always 0 in this build" is an observation,
not an explanation.

Measure any table with:

```bash
python tools/pesdb_census.py coverage <file> --table "Player.bin/400" --show-unknown
```

## Status

| table | stride × records (dt200) | stride × records (dt870) | named | constant | UNKNOWN |
|---|---|---|---|---|---|
| `Player.bin` /400 | 400 × 23,519 | — | **92.5%** | 3.8% | 3.6% |
| `Player.bin` /392 | — | 392 × 34,303 | **93.3%** | 1.9% | 4.8% |
| `PlayerAssignment.bin` v1 | 24 × 23,687 | — | **100%** | 0% | 0% |
| `PlayerAssignment.bin` v2 | — | 24 × 23,163 | **100%** | 0% | 0% |
| `Team.bin` | 1,600 × 981 | 1,600 × 975 | **94.1%** | 3.9% | 2.0% |
| `BootsList.bin` | 16 × 23,519 | 16 × 34,303 | **100%** | — | 0% |
| `GloveList.bin` | 16 × 394 | 16 × 1,013 | **100%** | — | 0% |
| `PlayerAppearance.bin` | 64 × 23,519 | 64 × 34,303 | 13.7% named | 11.7% | 35.5% (+37% encoding-only) |
| `Playstyle.bin` | 168 × 36 | 168 × 36 | layout cracked | | byte 0x01 unexplained |
| `PlayerSkill.bin` | 104 × 72 | 104 × 72 | layout cracked | | bit 7 + pair key unexplained |
| `Tactics.bin` | 12 × 1,780 | 12 × 1,762 | **100%** | — | 0% |
| `TacticsFormation.bin` | 12 × 19,580 | 12 × 19,382 | **100%** | — | 0% |
| `CompetitionUnit.bin` | 2,472 × 75 | 2,472 × 60 | header + all 21 names | | bytes 34–52 |
| `CompetitionEntry.bin` | 12 × 712 | 12 × 693 | **100%** | — | 0% |
| `CompetitionTournamentDetail.bin` | 8 × 1,405 | identical | keys cracked | | `@6` payload |
| `PlayerVariationDetail.bin` | 168 × 1,375 | 168 × 11,558 | id + name | | header bits |
| `Country.bin` | 1,488 × 214 | identical | layout cracked | | bits 19–30 |
| `City.bin` | 8 × 923 | 8 × 888 | **100%** | — | 0% |
| `Stadium.bin` | 1,096 × 37 | 1,096 × 40 | layout cracked | | bytes 0–3 |
| `Coach.bin` | 176 × 982 | 176 × 1,082 | names + nationality | | header |
| `TeamColor.bin` | 20 × 3,179 | — | **100%** | — | 0% |
| `Derby.bin` | 12 × 1,795 | 12 × 1,746 | **100%** | — | 0% |
| `CategoryTeamList.bin` | 12 × 2,538 | 12 × 2,438 | **100%** | — | 0% |
| `Ball.bin` | 188 × 20 | 188 × 22 | layout cracked | | — |
| `BallCondition.bin` | 8 × 57 | 8 × 55 | layout cracked | | — |
| `Boots.bin` | 304 × 53 | 304 × 53 | layout cracked | | — |
| `Glove.bin` | 204 × 11 | 204 × 11 | layout cracked | | — |
| `GameDefine.bin` | 8 × 517 | 8 × 517 | structure only | | semantics unknown |
| `StadiumWeight.bin` | 8 × 30 | 8 × 30 | structure only | | id space unknown |
| `CompetitionSlots.bin` | 8 × 10 | 8 × 10 | structure only | | — |
| `CompetitionTournament.bin` | 8 × 17 | 8 × 17 | structure only | | — |

Tables not yet in this table are undecoded or in progress.

## The container has three shapes, not two

Sider's doc describes flag byte 2 as "bit 0 = payload present", with `0x83` a normal table and
`0x02` an empty one, and notes nine 16-byte tables with `comp = orig = 0`. That generalises wrongly.
A `0x02` container with **`comp == orig != 0`** is a *stored* payload: XOR keystream, no zlib.

| flag byte 2 | comp / orig | payload |
|---|---|---|
| `0x83` | comp < orig | XOR keystream, then zlib |
| `0x02` | comp == orig == 0 | genuinely empty |
| `0x02` | comp == orig != 0 | **stored — XOR keystream, no zlib** |

The vendored Sider codec only implements the zlib path, so a handful of files fail to decode
through it entirely: `appearance/BootsHighCut.bin`, `etc/data_st_list.bin`, every
`uniform/team/*/*_DEF_*.bin` kit descriptor, and dt870's `CompetitionTournamentAssignment.bin`.
`tools/kit_codec.py` already classifies all three shapes, so `pesdb_census.py` defers to it rather
than adding a fourth opinion about the format. All of the above now read.

## The tools

| tool | what it does |
|---|---|
| `tools/pesdb_census.py` | `stride` ranks candidate record sizes by evidence; `census` gives per-bit / per-byte statistics; `fields` proposes field boundaries from varying-bit runs; `coverage` reports named/constant/unknown against the schema; `xref` tests a column against other tables' id columns to find foreign keys |
| `tools/pesdb_locate.py` | brute-force field finder: every offset × every width, scored against a known column of the export, in numeric (exact-match, auto-bias) or categorical (purity) mode |
| `tools/pesdb_schema_bootstrap.py` | flattens the scattered existing decode (`ability_bits.py`, `build/skill_bits.json`, `tools/data/player_layouts.json`, Sider's prose doc) into one bit-indexed schema |
| `tools/data/pesdb_schema.json` | the schema itself — the thing coverage is measured against |

**Scores are always reported against a baseline.** Purity alone is a trap: 97.6% of players have
`max_level` 1, so *any* window "predicts" it at 0.976. `pesdb_locate.py` ranks by lift over the
majority-class rate, never by the raw score. The locator was validated by re-finding `height` —
bit 248, width 8, bias +100, score 1.0000, lift +0.90 — before being trusted on anything new.

## Player.bin — corrections to the documented format

### The "12 × 2-bit aptitude run" is a worse trap than documented

Sider's `PESDB_DATABASE_FORMAT.md` describes twelve 2-bit position aptitudes at bits 576–599
plus LB at 318 and CMF at 510, and warns that assuming a clean twelve-slot run is the commonest
decoding mistake. It is a worse trap than that. The run at 576–599 really is twelve 2-bit slots,
but **only ten of them are aptitudes**. Slots 578 and 582 are `weak_foot_accuracy` and `form`.
A clean read of the run therefore produces two aptitudes that track nothing at all, and there is
nothing in the values themselves to tell you which two.

The full set is thirteen — one per position, not twelve:

| layout | GK | LB | CMF | RMF | AMF | CB | CF | LMF | LWF | RB | DMF | RWF | SS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **400** (dt200) | 414 | 318 | 510 | 576 | 580 | 584 | 586 | 588 | 590 | 592 | 594 | 596 | 598 |
| **392** (dt870) | 446 | 318 | 542 | 569 | 573 | 578 | 580 | 588* | 582 | 584 | 586 | 588 | 590 |

\* 392's LMF is at 414. In the 392 layout, CB (578), CMF (542) and CF (580) are marked **likely**
rather than proven: 16, 31 and 26 players at those positions respectively read something other
than 2. The other ten meet the strict test exactly.

The export carries no aptitude column, so correlation was impossible. They were found instead
from the one structural property aptitudes have and no other field does: **a player's aptitude
for their own position is always maximal**. Every field above reads exactly 2 for every player
at that position (n = 22,782) and 0 or 1 otherwise. GK is the sharpest — non-zero for exactly
one outfield player in the whole table.

### There are two dates, not one

`loan_end` at bit 192 was known. A sweep of every 25-bit window for one whose non-zero values
are all valid `yyyymmdd` found **exactly two** in the record, in both layouts, at 100%:

| field | bit | width | dt200 | dt870 |
|---|---|---|---|---|
| `contract_end` | 160 | 25 | 4,710 players | 12,166 players |
| `loan_end` | 192 | 25 | 1,129 players | 1,882 players |

`contract_end` was not documented anywhere. Its values cluster hard on 30 June, which is exactly
where real football contracts expire.

### The club fields exist in dt870 too

`derive_player_layouts.py` only ever looked for `youth_club` (byte 0), `loan_parent_club` (byte 4),
`club` (byte 16) and `loan_end` in the 400-byte record, so in the 392-byte record all four read as
unknown. They are at **the same byte offsets in both layouts**:

- `club` @16 equals the player's actual squad team in 95.6% of dt200 records and 95.1% of dt870's.
- `loan_parent_club` @4 is non-zero for exactly the players who carry a `loan_end` date — 1,120 in
  dt200, 1,364 in dt870. That 1:1 correspondence fixes both fields at once.

This also settles a standing disagreement. Sider's doc reads bytes 0–7 as a single u64 "native
PID"; the Player Editor reads two u32 club fields. **The editor is right** — a native PID would
not be non-zero for exactly the loan cohort.

### The vendored nationality read is off by one bit

`tools/vendor/sider/pesdb.py` reads nationality as `struct.unpack_from("<H", chunk, 41)[0] & 0x03FF`
— 10 bits from bit 328. **The real field is 9 bits from bit 329.** Bit 328 is a separate boolean,
set on 69 of 23,519 players, whose meaning is unknown.

The test is decisive. Read 9 bits at 329 and all 177 distinct values are a subset of `Country.bin`'s
214 ids, **zero misses**. Read Sider's way and **114 values match no country at all**. And it fails
*silently*, producing plausible wrong answers rather than errors:

| player | Sider's read | shifted read |
|---|---|---|
| Mohamed Salah | 116 → **El Salvador** | 58 → **Egypt** (EGY) |
| Tran Ngoc Son | 76 → **Morocco** | 38 → **Vietnam** (VIE) |
| Messi / Kane / Haaland / Osimhen | no match | Argentina / England / Norway / Nigeria |

**How much does this actually break?** Less than it looks, for a reason worth understanding.
`tools/game_world.py` reads `Country.bin`'s own id the *same* doubled way — 10 bits at bit 9, where
bit 9 is always zero. So both sides of the join are exactly 2×, and they still match. Measured: the
join succeeds for 23,450 of 23,519 players and **exactly 69 fall through** — precisely the players
with bit 328 set, whose value comes out odd and matches nothing.

So it is a real 0.3% data loss rather than a catastrophe, and it is invisible unless you look. Any
*new* consumer that compares `nationality_id` against a country id obtained any other way will get
garbage, because the value Sider returns is double the true id.

### Four export columns are not in Player.bin at all

Exhaustive scans — every offset, every plausible width — return essentially **zero lift over
baseline** for four of the export's columns. They are not in the player record:

| column | best score | baseline | verdict |
|---|---|---|---|
| `max_level` | 0.976 | 0.976 | **not stored** — card progression |
| `rating_grade` | 0.895 | 0.895 | **not stored** — card progression |
| `squad_number_national` | 0.101 | 0.039 | **not stored** — it is a property of the national-team squad slot, so it lives in that team's `PlayerAssignment` row, not the player |
| `overall_rating` | 0.170 | 0.088 | **not stored** — computed from the abilities at display time |

Where `max_level` and `rating_grade` *do* live is still open. The obvious candidate was
`PlayerVariationDetail.bin`, which grew from 231,000 to 1,941,744 bytes between builds — but its
key at +0 is **not** a player PID (not a subset of `Player.bin`'s PIDs, whole or masked), so its
rows are *variation definitions* ("Manchester United 98-99", "FC Barcelona 08-09"), not per-player
card instances. That weakens the guess rather than confirming it. Settling it needs a per-card
export to correlate against; the table alone will not do it.

With these four ruled out, **the export's columns are exhausted**: every column it carries has
either been located in the record or proven absent from it. Whatever remains unknown in Player.bin
cannot be named from the export, and needs the exe's own decoder or in-game observation.

### dt870's playing-style offsets are broken, not merely unverified

`player_layouts.json` marks `primary_style` and `secondary_style` unverified for the 392 layout.
That is generous: the offset it guessed for the out-of-possession style **overlaps
`ability.gk_parrying`**. The schema therefore omits both rather than claiming them, because
claiming them would hide six real bits behind a field that does not reproduce the export. They
need re-deriving before anything writes them in the dt870 layout.

### The six missing skills are probably five known bits

`PlayerSkill.bin` declares **72** skills. The repo's bit map covers 66, and the export only ever
exposed 52 — so six bits in the record are skills nobody has named.

Profiling the 66 known skill bits gives their shape: holder rates from 0.0000 to 0.1471, median
0.0345. Five of the 116 unknown varying bits sit inside the skill region and fall squarely in that
range:

| bit | holders | rate |
|---|---|---|
| 600 | 2,826 | 0.1202 |
| 601 | 2,169 | 0.0922 |
| 618 | 1,315 | 0.0559 |
| 629 | 19 | 0.0008 |
| 648 | 1,128 | 0.0480 |

This is a **lead, not a result**: the shape matches, but the export predates these skills so there
is no column to confirm them against, and nothing here says *which* skill each bit is. Naming them
needs either the game's own UI or a newer export. The sixth is unaccounted for — it may be constant
in this build, or live outside the region profiled.

## The catalog tables store plain text

A working assumption on this project was that display names live in the localisation file and these
tables reference them by id or hash. That is **wrong**: names are stored inline, UTF-8,
fixed-width, NUL-padded.

### `Playstyle.bin` — 168 × 36

| offset | type | meaning |
|---|---|---|
| 0x00 bits 0–5 | u8 | catalog index, equals the row number 0–35 |
| 0x00 bit 6 | flag | out-of-possession / secondary-only style |
| 0x00 bit 7 | flag | set only on 7 (Box-to-Box) and 8 (Anchor Man) — unexplained |
| 0x01 | u8 | 0 or 1; zero on {23, 29, 31, 32, 33, 34} — **unexplained** |
| 0x04 | char[100] | Japanese display name |
| 0x68 | char[64] | ASCII internal key (`PS_…`) |

The 36 index→key pairs match `tools/playstyle_catalog.py` exactly, independently confirming that
table. Indices 9/16/17 come out as `PS_ATTK_PREVENTER` (The Destroyer), `PS_LIBERO_GK` and
`PS_CLASSICAL_GK` — the three the repo already knew.

**Open conflict.** Bit 6 marks secondary-only styles and is set on {9, 16, 17, 23…33}. The repo's
`_SECONDARY_ONLY` is `{9,16,17} | range(23,36)`. They disagree on **34** (`PS_BUILD_UP_GK`) and
**35** (`PS_ADVANCED_GK`), where bit 6 is *clear*. The repo classified those two as secondary-only
partly because the 5-bit primary field physically cannot hold a value above 31 — not from observed
behaviour. The file may be saying they are in-possession styles. Unresolved.

### `PlayerSkill.bin` — 104 × 72

| offset | type | meaning |
|---|---|---|
| 0x00 bits 0–6 | u8 | skill index, equals the row 0–71 |
| 0x00 bit 7 | flag | set on 14 rows — meaning unknown |
| 0x01 | u8 | pair key: 0 on 45 rows, else 1–14 — meaning unknown |
| 0x04 | char[100] | Japanese name (no ASCII key field, unlike Playstyle) |

**There are 72 skills.** The repo's bit map covers 66, and the export only exposes 52. Each pair
key 1–13 appears on exactly two rows, always one with bit 7 set and one without; what the pairing
means is not established (it is not "similar skill" — Acceleration Burst pairs with Aerial Fort).

### Others

| table | layout |
|---|---|
| `Ball.bin` 188 × 20 | u16 id (ascending), u16 code, `char[184]` product name at +4. **No float32 anywhere** — every byte past +62 is zero in all records, so there is no ball physics in this file |
| `BallCondition.bin` 8 × 57 | u16 ball_id (FK into Ball.bin), u16 key, u32. 17 of 22 ball_ids resolve; 5 dangle in *both* builds |
| `Boots.bin` 304 × 53 | u16 id, u16 code, three 100-byte strings at +4 (colourway), +104 (materials), +204 (model name) |
| `Glove.bin` 204 × 11 | u16 id (1, 101, 201 … 901), u16 model code, 100 reserved bytes, `char[100]` name at +104 |
| `GameDefine.bin` 8 × 517 | u32 value, u16 row_id (contiguous 1…517), u16 group_id. 65 groups, sizes 1–44, values 1…150000. A generic keyed constant store; semantics unknown |
| `StadiumWeight.bin` 8 × 30 | u16, u16, u32 ascending 10450…10677. The u32 matches no id column in Stadium, StadiumOrder, City or Team — opaque |
| `CompetitionSlots.bin` 8 × 10 | u16 = 102 constant, u8 slot 31…40, u8 tier, u32 payload |
| `CompetitionTournament.bin` 8 × 17 | u16 id 1…17, u16 comp_id 46…63, u32 ∈ {2,3,…,44} — *guess:* entrant count |

## Team.bin — bit-packed, which is why it resisted

For years exactly two fields of this 1,600-byte record were known. The reason is simple and was
never spotted: **the record is bit-packed, not byte-aligned.** Only `team_id` and the name slots
sit on byte boundaries. Read as bits, most of it falls out — 94.1% named, 2.0% unknown.

### The name array starts at byte 116, not 396

It is **21 language slots of 70 bytes** plus a 10-byte abbreviation — 1,480 bytes, 92.5% of the
record:

| offset | slots |
|---|---|
| 116 + 70k, k=0…10 | ja(116), es(186), **sv**(256), el(326), **en(396)**, tr(466), fr(536), th(606), ko(676), pt(746), de(816) |
| 886 | 10-byte abbreviation — `ARS`, `ENG`; byte 895 always 0 |
| 896 + 70k, k=0…9 | es-419(896), pt-BR(966), zh-Hans(1036), nl(1106), zh-Hant(1176), it(1246), id(1316), ru(1386), ar(1456), en-2(1526) |

⚠️ **This corrected the write path** (fixed in `85b38bf`). `tools/dt200_rename.py` had
`NAME_OFF, REC = 396, 1600` and wrote `enc + b"\0" * (48 - len(enc))` — a 48-byte field. Byte 396
is simply where slot 4 lands, which is why that appeared to work. Three consequences:

1. The slot is **70 bytes wide, not 48**, so a team name longer than 47 bytes cannot be written
   even though the format allows 69.
2. Bytes 396+48 … 396+69 are never cleared, so a stale tail survives behind the NUL terminator.
3. **The other twenty language slots keep the old name**, so a renamed club reads correctly in
   English and wrongly in Japanese and Chinese — the two other slots that are actually populated
   for clubs.

The same file already did the right thing for competitions: its `CompetitionUnit` pass writes all
21 language slots, noting that Konami repeats the real name in every slot. The Team pass was never
given the same treatment only because `Team.bin`'s 21-slot structure was unknown.

`85b38bf` fixed it against the offsets in this document: all 21 slots written and read back,
over-long names refused rather than truncated mid-UTF-8, and the abbreviation at 886 left alone
rather than guessed (Konami's stub usually still prefixes the new name — Pisa NA → Pisa keeps
`PIS` — but not always, so a renames entry may now carry an explicit `abbr`). It also caught a
second bug this document had not spotted: `name_of()` read a 48-byte window and tested `if o`, so
the record at offset 0 sorted as an empty name.

Only Japanese, English, Chinese-Simplified (947 of 981) and the abbreviation are filled for clubs.
The other 17 slots carry **only the 253 national teams**, which is what made 865 bytes look
permanently zero.

### The header

| bit | width | field | confidence |
|---|---|---|---|
| 22 | 1 | **national team** — set for exactly the 253 records with translations, clear for all 728 clubs | proven |
| 23 | 1 | fully licensed — all 191 clubs with it clear use the real crest; only 73/537 otherwise | likely |
| 25 / 26 | 1 | AFC / CAF national team (CAF: 24 records, ids ≥ 81952 — the known 24 African teams) | likely |
| 96 | 17 | `team_id` | proven |
| 128, 160 | 13 | related-club refs | likely |
| 352…480 | 13 × 5 | **rival / derby refs** — Arsenal→Tottenham, Barça→Real, Real→Barça, Marseille→PSG, Benfica→Porto; 103/137 symmetric | likely |
| 664 | 7 | **% of squad in the young age band** — r = 0.9998, 787/787 within 1 | proven |
| 672 | 21 | club stature / money — ladder 10000…1200000; Man Utd and Real 1.2M > Chelsea/Liverpool 900k > Arsenal 700k > Benfica 300k; 0 for national teams | likely |
| 840 | 10 | **country id** — 159/159 national teams equal their squad's dominant nationality; Arsenal 408 England, Barça 472 Spain, PSG 416 France | proven |
| 850 | 7 | **% of squad of the team's own nationality** — r = 0.958, every national team reads 100 | proven |
| 864 / 871 | 7 | **% of squad in the old / middle age band** — r = 0.9998 / 0.9996 | proven |
| 920 | 3 | crest real/fake flags | proven |

**The three age bands sum to exactly 100 for all 787 teams with a squad, and to 0 for all 194
without.** So Team.bin caches squad composition rather than deriving it. The raw thresholds on
Player.bin's 6-bit age field are `<15 / 15–19 / ≥20`; a +10 bias would make those *under 25 /
25–29 / 30+*, but the bias is inferred, so treat the raw thresholds as proven and the real-world
labels as likely.

### Negative results worth recording

- ~~No stadium foreign key.~~ **Overturned.** The `Team.bin` pass found no field whose values are a
  subset of `Stadium.bin`'s id column and recorded that as a negative. It is at **byte 90**, which
  that pass had listed as an unknown singleton — the subset test missed it because `Stadium.bin`
  has only 37 records, so the id space is tiny and the match looked like coincidence. Confirmed by
  name: England→Wembley, Man Utd→Old Trafford, Barcelona→Camp Nou. *A negative from a subset test
  over a 37-value id space was never going to be worth much; this is the one to distrust.*
- **No league / competition foreign key.** League membership lives in `CategoryTeamList.bin`.
- **No formation or tactics reference.** `Tactics.bin` keys on team id from its own side.

The largest remaining unknowns are all in bytes 0–116: bits 800–825 and 640–661 are the biggest
blocks; bits 694–713 and 784–797 correlate ~0.6–0.75 with the squad's foreign-player count, so
they are probably more cached composition.

## The per-player side tables

`PlayerAppearance.bin`, `BootsList.bin` and `GloveList.bin` all carry a u64 external PID in bytes
0–7, strictly ascending. For the first two the PID column is **elementwise identical to
`Player.bin`'s**, so row *i* is row *i* — join by index, no lookup. `GloveList` is a sparse subset.

| table | dt200 | dt870 | stride |
|---|---|---|---|
| `PlayerAppearance.bin` | 23,519 | 34,303 | 64 |
| `BootsList.bin` | 23,519 | 34,303 | 16 |
| `GloveList.bin` | **394** | 1,013 | 16 |

**`GloveList` is exactly the goalkeepers.** All 394 dt200 glove PIDs have `position == 0`, and no
outfield player has a row — which confirms the position field and the table's meaning at once.

### `BootsList.bin` / `GloveList.bin` — solved

| offset | width | type | meaning |
|---|---|---|---|
| 0 | 8 | u64 | external PID |
| 8 | 2 | u16 | boot / glove model id — FK into `Boots.bin` / `Glove.bin` |
| 10 | 6 | — | always zero in both builds |

27 of 29 observed boot ids and 9 of 11 glove ids resolve exactly. The strays (boots 3061, 5021;
gloves 111, 611) follow the same `brand*1000 + model` convention, so they are models defined in
another CPK's copy of the table, not a decode error.

### `PlayerAppearance.bin` — structure cracked, semantics mostly not

The record is a **4-bit nibble grid with 7 as the neutral value** — the editor's −7…+7 sliders.
545 players share an all-`0x77` default body, which is what exposed it.

| bits | width | meaning | confidence |
|---|---|---|---|
| 0–63 | 64 | external PID | certain |
| 64–119 | 14 × 4 | face-morph block A; several strongly ethnicity-skewed | class only |
| 108–119 | 3 × 4 | triple, inverse to height — *guess:* head/upper-body scale | **guess** |
| 140–291 | 38 × 4 | the face-morph slider block; genuinely individual | encoding only |
| **292–294** | 3 | **skin tone, 1 (lightest) – 6 (darkest)** | **certain** |
| **296–298** | 3 | **face/skin texture group: 3 Caucasian, 4 East Asian, 5 Black** | high |
| 300–454 | ~40 × 4 | ids and default-heavy enums; plausibly hair/beard and kit fit | unknown |
| 455–511 | 55 | always zero (bytes 59–63 entirely) | certain |

Verified on named players: Haaland/Kane/Neuer/De Bruyne/Messi → skin 1 group 3; Son 2, Mitoma 3,
group 4; Osimhen/Koulibaly/Lukaku/Pogba → skin 6 group 5. Identical in dt870. This confirms
`tools/appearance.py`'s existing 3-bits-at-292 claim exactly — **do not widen it to 4 bits.**

**Height and weight are not in this record.** A firm negative: no window of width 6–8 anywhere
reproduces `height−100` or `weight−30` above chance, and the best single predictor of height
explains only 27% of its variance. `Player.bin` is the sole store.

Honest coverage of the 512 bits: 12.5% PID, 11.7% constant zero, **1.2% semantically named**,
36.7% known encoding but unknown individual meaning, 35.5% varying and wholly unexplained. The
third-party "roughly 107 fields" is structurally consistent with 104 nibble slots plus flags, but
it supplies no names and none beyond the two above could be verified.

## Tactics and formations

`TacticsFormation.bin` has exactly **11 × as many records as `Tactics.bin`** at stride 12, in both
builds (dt200 19,580 = 11 × 1,780; dt870 19,382 = 11 × 1,762). No other stride pair reproduces
that, which fixes both tables at once. The strides floated previously for `TacticsFormation`
(264 × 890, 2,640 × 89) are multiples of the real 12-byte record, not the record.

**`Tactics.bin`** — stride 12; team id @0 (u32, exactly 2 rows each), formation id @4 (u32, unique,
the FK target), team style @8 (u8, 0–5), phase @9 (u8, 0/1 — exactly 890 of each, so in- vs
out-of-possession), @10–11 zero.

**`TacticsFormation.bin`** — stride 12; role @0 (u32, 0–12 GK…CF), formation id @4, depth @8,
width @9, slot index @10 (0–10, once per formation), @11 zero.

**Both coordinates are quantised to a 21 × 21 grid** — a detail nothing in the repo records.
Depth takes only **odd** values 3…43; width only **multiples of 4**, 12…92, centred on 52. So
`depth = 2·row + 3` and `width = 4·col + 12`. Anything writing arbitrary coordinates is writing
off-grid values — worth checking before the next write.

`tools/ml_tactics.py` and `tools/tactics_load.py` already assert exactly this layout. It was
re-derived from the bytes without reading them first and matches, so the repo's assumption is now
**confirmed rather than inherited**.

### Fluid formation: the mechanism is here, the divergence is not

Every team has exactly two `Tactics` rows, one per phase, and **each points at a different
formation id** — 890 of 890 in dt200, 881 of 881 in dt870. That pair *is* the fluid-formation
mechanism: an in-possession shape and an out-of-possession shape, held separately. The exe
corroborates the reading — its serialisation member names include `formationOffence` and
`formationDefence`.

But the two formations are almost always the *same shape*. Comparing the 11 `(role, depth, width)`
triples behind each id:

| build | teams with a phase pair | different formation id | **divergent geometry** | different team style |
|---|---|---|---|---|
| dt200 | 890 | 890 | **1** (0.1%) | 0 |
| dt870 | 881 | 881 | **0** | 184 |

So Konami ships every team non-fluid: two formation records per team, identical geometry in both.
The lone dt200 exception is team 6261, whose two shapes differ in 5 of 11 slots.

This matches what was already known from the save-format work — *fluid is divergent pair geometry,
and the toggle lives in the user save*. What this adds is that the dt200 side is not a dead end:
the pair of formation records is real, addressable, and already wired per team. Writing genuinely
different geometry into a team's two formation ids is the data-side half of making a team fluid.

### byte 8 diverges by phase in dt870, and nobody knows what that means

In dt200, byte 8 is simply **duplicated** across a team's two rows: the phase-0 and phase-1 value
distributions are identical to the record (253/188/227/64/147/11), and **zero** of 890 teams differ.
In dt870, **184 of 881 differ**, and the two distributions come apart.

That is a measurement, not an interpretation. Byte 8 is labelled "team style" here because
`play_match.write_style` calls it the attacking-style byte, and the decode marked it *likely*, not
proven. Two things follow that are worth not glossing over:

- The divergence is **unsystematic** — the observed `(phase0, phase1)` pairs run both directions,
  `(0,1)` 38 times but `(4,0)` 3 times, `(4,2)` 40 times and `(2,3)` 25. So it is not a re-encoding,
  an offset, or a one-way migration.
- dt200 uses **six** values (0–5, with 5 on only 11 teams); dt870 uses **five** (0–4). eFootball
  exposes five team playstyles, which fits dt870 and leaves dt200's sixth value unexplained.

So either a dt870 team genuinely attacks with one style and defends with another, or byte 8 does
not mean the same thing in both rows. Nothing here settles it.

**Practical note:** `play_match.write_style` writes byte 8 on **both** of a team's rows, which
matches dt200's shipped pattern exactly, so our write path introduces no inconsistency. But if
dt870's per-phase divergence is meaningful, writing both rows to the same value flattens it.

## Competitions are a tree, and the pyramid is readable

**`CompetitionUnit.bin` is a uniform table, not a mixed-size one.** Stride 2,472 throughout; 75
records in dt200, 60 in dt870. The "21 records of 115 bytes" in the prior notes is really the
**name array inside every record**: `56-byte header + 21 × 115 + 1 pad = 2,472`. The 21 slots are
languages, plain NUL-padded UTF-8 — **English is slot 15** (slot 19 is a second English).

| offset | width | meaning |
|---|---|---|
| 2 | 2 | **parent competition id**, `0xFFFF` = root |
| 4 | 2 | **division below** (relegation link) |
| 6 | 2 | **division above** (promotion link) |
| 10 | 2 | competition id |
| 15 | 1 | group/stage ordinal (0–7, 255 = n/a) |
| 34–52 | — | varies, unexplained |

Two structural findings. `+2` is a **parent pointer** — comps 102 and 111 both point at 101 (AFC
Champions League Elite), 167–173 all point at 165 — so the group-stage rows hang off a root as a
tree. And `+4`/`+6` are a **symmetric promotion/relegation pair**, proven by reciprocal links:
England 113 ↔ 337, Italy 116 ↔ 346, Spain 119 ↔ 340, France 122 ↔ 343, Brazil 149 ↔ 588,
J1 266 ↔ J2 269. The league pyramid is readable straight out of the table.

**`CompetitionEntry.bin`** — stride 12: team id @0, entry ordinal @4, competition id @6 (a subset
of CompetitionUnit's ids), constant 128 @8. `u32@4` is a composite `(competition << 16) | entry`;
its high half equals `u16@6` on every row. Per-competition counts are sane league sizes (PL 20,
J1 20, Argentina 30, AFC CL 24).

**`CompetitionTournamentDetail.bin`** — stride 8, 1,405 records, **byte-identical in both builds**,
so it is a static bracket template rather than live data. Node id @0 (1–281, exactly 5 rows each),
tournament template id @2 (1–17), global row index @4. The packed field at @6 (slot in bits 13–15,
payload in bits 0–12) is **not cracked**.

**`PlayerVariationDetail.bin`** — stride 168 (not 84: at 84 every odd record is empty padding).
Variation id @0 (not unique, and not a player PID), bit-packed flags @2–11, variation name @12 as
NUL-padded UTF-8. Header bits undecoded.

## The world reference tables

Strides here were settled by `gcd(len(dt200), len(dt870))` where the census was ambiguous.

### `Country.bin` — 1,488 × 214 (byte-identical in both builds)

Not 2,976 × 107. 214 records comfortably cover the ~192 nationalities referenced by `Player.bin`.
Same 70-byte name-slot grid as `Team.bin`: 10 slots at `8 + 70i`, a 10-byte **FIFA 3-letter code**
at 708, then 11 more at `718 + 70j`, ending exactly at 1,488. English is slot 4.

| offset | width | meaning |
|---|---|---|
| bits 0–8 | 9 | display sort order (unique; confederation then alphabetical) |
| bits 10–18 | 9 | **country_id** |
| bits 19–30 | 12 | unknown, 112 distinct |
| byte 4 | 8 | geographic continent: 1 Asia, 2 Europe, 3 Africa, 4 N/C America, 5 S America, 6 Oceania |
| byte 5 | 8 | confederation: 2 UEFA, 4 CONMEBOL, 5 CAF, 6 CONCACAF, 7 OFC, 11 AFC-East, 19 AFC-West |
| 708 | 10 | FIFA code (`ENG`, `BRA`) |

The confederation values are self-proving: byte 5 = 5 yields exactly **54** members (CAF's real
count) and byte 5 = 4 exactly **10** (CONMEBOL), with Suriname and Guyana correctly in CONCACAF
while byte 4 still places them in South America. Australia and Guam are AFC by confederation and
Oceania by geography — the real-world split. Unexplained: the four Central Asian republics carry
continent = Europe.

### `City.bin` — 8 × 923: it is a geolocation table

No text at all, and fully solved:

| offset | width | meaning |
|---|---|---|
| 0 | u16 | **latitude = v/100 − 180** |
| 2 | u16 | city_id |
| 4 | u16 | **longitude = v/100 − 180** |
| bits 48–56 | 9 | country_id |

Norway's single city reads 23991 / 19075 → 59.91 N, 10.75 E. Oslo is 59.9139 N, 10.7522 E. Japan's
46 cities average 136.7 E; Brazil's 40 average 46.45 W (São Paulo is 46.6 W). This is the sun and
weather geolocation table.

### `Stadium.bin` — 1,096 × 37 (dt870: 40)

`stadium_id` u16 @4 (strictly increasing 1, 5, 7 … 199); flags @6 where **bit 4 = fictional venue**
— set on every Loot Box / Custom / eFootball™ ground and clear on every licensed one; five 181-byte
name slots from 189 (0 Japanese, 2 Chinese-Simplified, 3 Latin; slots 1 and 4 unused). Bytes 0–3
are an unexplained packed field shared by records that are the same venue (Giuseppe Meazza and
San Siro both `4d713892`).

**The stadium foreign key is `Team.bin` byte 90** — England→Wembley, Man Utd→Old Trafford,
Arsenal→Emirates, Barcelona→Camp Nou, Milan→San Siro, Dortmund→Signal Iduna. No team reads 0. This
resolves a field the `Team.bin` pass had left as an unknown singleton, and overturns its "no
stadium FK" negative.

### The rest

| table | stride × count | layout |
|---|---|---|
| `Coach.bin` | **176 × 982** (dt870 1,082) | the 352 guess was two coaches per block. **Nationality is 9 bits at bit 170**, joining `Country.bin` — Mourinho→Portugal, Flick→Germany, Arteta→Spain. Coach uid u64 @24; names at 32 (Japanese, 46 B), 78 (Latin, 46 B), 124 (Chinese, 52 B) |
| `TeamColor.bin` | **20 × 3,179** | the vendored 64-byte `parse_team_color_bin` is **wrong** — 63,580 is not divisible by 64. team_id u32 @0; **primary RGB at bytes 7, 6, 11** and **secondary at 4, 5, 10**; the other six bytes are fixed duplicates. Verified: Netherlands #FE5901/white, Barça #022674/#A40046, Italy #085CA0/white |
| `Derby.bin` | 12 × 1,795 | team A @0, team B @4, row index (11 bits @64), rivalry type (3 bits @80). **Directed** — every rivalry stored twice, once per side |
| `CategoryTeamList.bin` | **12 × 2,538** | not 24 — stride 24 shows two identical halves. team id @0, category id @4 (54 values in two bands: 101…777 competition-like, and 0x10000+ bulk groupings where 65561 holds 700 teams), row index @8 |

## The remaining small tables

Strides established (dt200), structure only — none of these were decoded field-by-field, because
none of them carry anything this project needs:

| table | stride × count | | table | stride × count |
|---|---|---|---|---|
| `PlayerBooster.bin` | 520 × 15 | | `PlayerWeekly.bin` | 16 × 631 |
| `CoachBooster.bin` | 8 × 26 | | `TeamWeekly.bin` | 8 × 689 |
| `SpecialPlayerAssignment.bin` | 24 × 99 | | `StadiumOrder.bin` | 16 × 64 |
| `SpecialPlayerAssignmentKind.bin` | 272 × 5 | | `StadiumOrderInConfederation.bin` | 8 × 110 |
| `CoachLink.bin` | 58 × 4 | | `PlayerVariationPrSkill.bin` | 16 × 287 |
| `CoachVariationDetail.bin` | 40 × 4 | | `PlayerVariationAdditionalInfo.bin` | 112 × 100 |
| `RefereeAppearance.bin` | 448 × 5 | | | |

**One of them is worth a second look.** `SpecialPlayerAssignmentKind.bin` (272 × 5) holds two
14–15 byte ASCII key fields at +4 and +140, and the keys are Master League regen categories:

```
@4:   ML_NEWFACE_EUR   ML_NEWFACE_ASI   MONTAGE_PRESET
@140: ML_NEWFACE_SAME  ML_NEWFACE_J_LE  JAPAN_RESERVE
```

`ML_` is Master League. These are the game's own newface/regen buckets — regional pools for
generated youth players. Given this project's youth-regen ambitions that is directly relevant, and
`SpecialPlayerAssignment.bin` (24 × 99) is presumably the assignment that uses them. Neither was
chased further here.

## The match-time ability array is a different representation

Worth stating plainly because it has caused repeated confusion: **the ability indices used in
gameplay code are not Player.bin bit offsets, and the record the match reads is not the 400-byte
record.**

The roster→match copy loop is at `0x1454406a0` — the tail of the master builder `0x145440380`.
It walks 30 entries of an `{matchAbilityId, compactIndex}` table at `0x14825CAA0`, clamps each
against a range table, and writes through `0x1442c0060` into the object returned by
`0x144301840`: three parallel 61-byte arrays (effective `+0x00`, base `+0x3d`, match delta
`+0x7a`) followed by a 73-bit skill bitfield at `+0xc0`.

It reads an intermediate **52-byte packed struct**, decoded by `0x144a0d7c0(record, fieldId, &out)`
via a 145-case jump table at `0x144a0e010`. In that struct the 26 abilities are **7-bit and
unbiased** — not the 6-bit, +40-biased form Player.bin uses on disk.

**Two corrections to this repo's own notes**, both from the disassembly:

- **`0x17` is `defensive_engagement`, not Dribbling.** Dribbling is `0x18`. The note in
  `attr-0x17-defending.md` "correcting" 0x17 to Dribbling is itself wrong.
- **`kicking_power` is `0x2b`, not `0x29`.** `0x29` is `physical_contact`. Independent proof: the
  weak-foot penalty at `0x144151126` applies to exactly `{0x1b, 0x1c, 0x1d, 0x2b}` — finishing,
  low pass, lofted pass and kicking power, i.e. the four kick attributes and nothing else.

Both corrections rest on static disassembly and have not been confirmed in-game. Treat as strong
but not final.

## What is left

**Done, to the point where the remaining bits are genuinely hard:** `Player.bin` (both layouts),
`PlayerAssignment.bin` (both), `Team.bin`, `Tactics`/`TacticsFormation`, `CompetitionUnit`/`Entry`,
`Country`, `City`, `Stadium`, `TeamColor`, `Derby`, `CategoryTeamList`, `BootsList`, `GloveList`,
`Playstyle`, `PlayerSkill` and the small catalogs.

**Open, in rough order of value:**

1. **`Player.bin`'s last bits** — 116 unknown in the 400 layout, 150 in the 392. The export's
   columns are exhausted: everything it can name has been named, and four columns were proven
   absent. The next move is the exe's own decoder — `0x144a0d7c0`'s 145-case jump table at
   `0x144a0e010` maps the intermediate 52-byte struct field by field, and back-mapping it to the
   on-disk record would likely close most of the gap in one pass.
2. **`Player.bin/392`'s playing styles** need re-deriving; the current guess overlaps `gk_parrying`.
3. **The six missing skills** — `PlayerSkill.bin` declares 72, the bit map covers 66. Five candidate
   bits are identified (600, 601, 618, 629, 648) but unnamed.
4. **`PlayerAppearance.bin`** — 63% of bits have a known *encoding* (a −7…+7 nibble grid) but only
   1.2% a known *meaning*. Naming individual morph sliders needs the game's editor UI, not more
   statistics.
5. **`PlayerVariationDetail.bin`** header bits, and finding where `max_level` / `rating_grade`
   actually live.
6. Small unexplained regions: `Country` bits 19–30, `Stadium` bytes 0–3, `Coach`'s header,
   `Playstyle` byte 0x01, `PlayerSkill` bit 7 and its pair key,
   `CompetitionTournamentDetail`'s packed payload, `CompetitionUnit` bytes 34–52.

**Deliberately not pursued** — structure established, contents not decoded, because nothing in a
Master League companion app reads them: `PlayerBooster`, `CoachBooster`, `CoachLink`,
`CoachVariationDetail`, `PlayerVariationPrSkill`, `PlayerVariationAdditionalInfo`, `PlayerWeekly`,
`TeamWeekly`, `StadiumOrder`, `StadiumOrderInConfederation`, `RefereeAppearance`, `BadgeData`,
`CompetitionBadge`, `StadiumEditParam`. The exception is `SpecialPlayerAssignment(Kind)`, which
holds the Master League regen buckets and is worth returning to.
