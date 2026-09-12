#!/usr/bin/env python3
"""
stats_read.py — read per-player match stats out of eFootball's live memory (READ-ONLY).

At full time the engine holds, for every player, the raw counters that feed the match rating
(touches, shots, passes attempted/completed, tackles, clearances, balls won/lost, cards, saves…)
plus the final 0-10 rating. This pulls them out with ReadProcessMemory — the same read-only path
tools/mem_probe.py and tools/mem_scan.py already proved works on this game. Nothing is written to
the game; the only writes are to our own SQLite.

    python tools/stats_read.py scan                  # locate the match record block
    python tools/stats_read.py dump                  # all players: rating + non-zero stat rows
    python tools/stats_read.py dump --raw            # include unnamed rows (row_NN) and columns
    python tools/stats_read.py save --fixture 123    # write into the app DB
    python tools/stats_read.py correlate --side home --slot 0   # one player, for naming rows

Memory layout (mapped from eFootball.exe — see docs/exe-gameplay-map.md, build/ratings_stats_map.json):

    RecordSlot                                  (~1.3 MB match record object)
      + 0x1c4 + (team*0x28 + player)*0x10       -> float32 final rating (0-10)
      + 0x78118                                 -> statsContainer
    record = statsContainer + 0x65C0 + team*0x38238 + player*0x13E8      (accessor 0x1442e6640)
      record + 0x10 + row*0x24 + col*4          -> int32[0x77 rows][9 cols]  (getter 0x1443378c0)
          TOTAL     = col0..col7 summed  (getter mode 5) <- what every rating term reads
          (modes 0/1 = col0-2 / col3-5 sub-buckets; modes 2/3/4 = c6 / c7 / c8)
      Attempts and completions are SEPARATE ROWS (0x1a pass_short vs 0x1b pass_short_success),
      so completion% = row(..._success).total / row(...).total — see DERIVED below.
      record + 0x10cc                           -> uint8 min-ability, 0xFF = did not play
      record + 0x10e0                           -> int32[13] per-position play counters

RecordSlot is found by signature scan (no live-only pointer needed): the rating array is 40
float32 per team at stride 0x10, all within the game's rating clamp. NOTE the clamp is a dt270
field we edit (`rating.ratingMin/ratingMax`, currently 0.5/10.0) — RATING_LO/HI below must stay
in step with it.
"""
from __future__ import annotations

import argparse
import ctypes
import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from live_patch import find_pid, open_proc, module_base, read_mem, query, k32   # noqa: E402

# ---- layout constants (see module docstring) ----
RATING_OFF = 0x1C4
RATING_STRIDE = 0x10
TEAM_RATING_STRIDE = 0x28 * RATING_STRIDE      # 0x280
CONTAINER_OFF = 0x78118
REC_BASE = 0x65C0
TEAM_STRIDE = 0x38238
PLAYER_STRIDE = 0x13E8
STATS_OFF = 0x10
ROW_STRIDE = 0x24
N_ROWS = 0x77
N_COLS = 9
DNP_OFF = 0x10CC
POS_COUNTERS_OFF = 0x10E0
SLOTS_PER_TEAM = 40

RATING_LO, RATING_HI = 0.5, 10.0    # keep in step with dt270 rating.ratingMin/ratingMax

# Row index -> stat name. Filled in as rows are tied to code (increment sites) or correlated
# against the in-game full-time stats screen. Unnamed rows are still dumped as row_NN, so the
# data is never lost — run `correlate` to name them.
ROW_NAMES: dict[int, str] = {
    0x00: 'goal',                               # proven
    0x01: 'own_goal',                           # proven
    0x02: 'fk_goal',                            # proven
    0x03: 'pk_goal',                            # proven
    0x04: 'assist',                             # proven
    0x06: 'shoot',                              # proven
    0x07: 'shot_from_open_play',                # likely
    0x0e: 'shot_from_inside_the_penalty_area',  # likely
    0x10: 'shoot_pk',                           # proven
    0x11: 'shoot_success',                      # proven
    0x16: 'shoot_in_frame',                     # proven
    0x18: 'pass',                               # proven
    0x19: 'pass_success',                       # proven
    0x1a: 'pass_short',                         # proven
    0x1b: 'pass_short_success',                 # proven
    0x1c: 'pass_through',                       # proven
    0x1d: 'pass_through_success',               # proven
    0x1e: 'pass_long',                          # proven
    0x1f: 'pass_long_success',                  # proven
    0x20: 'centering',                          # proven
    0x21: 'centering_success',                  # proven
    0x22: 'grounder_pass_attempted',            # likely
    0x23: 'grounder_pass_success',              # likely
    0x24: 'lofted',                             # likely
    0x25: 'lofted',                             # likely
    0x26: 'through_ball_grounder_variant',      # likely
    0x27: 'through_ball_grounder_variant_success',# likely
    0x28: 'through_ball_lofted_variant',        # likely
    0x29: 'through_ball_lofted_variant_success',# likely
    0x2a: 'forward_pass_attempted',             # likely
    0x2c: 'forward_pass_success',               # likely
    0x2d: 'sideways_pass_attempted',            # likely
    0x2f: 'sideways_pass_success',              # likely
    0x30: 'backward_pass_attempted',            # likely
    0x32: 'backward_pass_success',              # likely
    0x34: 'tackle',                             # proven
    0x35: 'tackle_success',                     # proven
    0x36: 'dispossess_delay',                   # proven
    0x37: 'dispossess_press',                   # proven
    0x3a: 'clear',                              # proven
    0x3c: 'foul',                               # proven
    0x3d: 'off_side',                           # proven
    0x3e: 'card_yellow',                        # proven
    0x3f: 'card_red',                           # proven
    0x40: 'foul_suffered',                      # likely
    0x42: 'fk',                                 # proven
    0x43: 'indirect_fk',                        # proven
    0x44: 'corner',                             # proven
    0x45: 'penalty_kick_taken',                 # likely
    0x46: 'dribble',                            # proven
    0x47: 'dribble_success',                    # proven
    0x48: 'ball_touch',                         # proven
    0x4d: 'dispossessed_a_dribbler_event',      # likely
    0x4f: 'snatch_total',                       # proven
    0x50: 'cut_pass',                           # proven
    0x51: 'ball_won_cause_type_1',              # likely
    0x52: 'ball_won_cause_type_3',              # likely
    0x53: 'ball_won_cause_receiver_position_3', # likely
    0x54: 'ball_won_cause_type_2',              # likely
    0x55: 'ball_won_cause_type_0x10',           # likely
    0x57: 'snatch_by_tackle',                   # proven
    0x58: 'snatch_by_block',                    # proven
    0x5a: 'snatch_by_wedge',                    # proven
    0x61: 'snatched_total',                     # proven
    0x63: 'snatched_during_dribble',            # proven
    0x66: 'snatched_during_pass',               # proven
    0x67: 'ball_lost_cause_type_1',             # likely
    0x68: 'ball_lost_cause_type_3',             # likely
    0x69: 'ball_lost_cause_receiver_position_3',# likely
    0x6a: 'ball_lost_cause_type_2',             # likely
    0x6b: 'ball_lost_cause_type_0x10',          # likely
    0x6d: 'gk_shoot_faced',                     # proven
    0x6e: 'gk_inframe_shoot_faced',             # proven
    0x6f: 'gk_save',                            # proven
    0x70: 'gk_shoot_p_a',                       # proven
    0x72: 'gk_save_from_a_penalty_kick',        # likely
}

# Rows the rating compute was observed reading (0x14429ea40) — these are the ones that matter.
RATING_ROWS = [0x00, 0x04, 0x1A, 0x46, 0x62, 0x63, 0x64, 0x65, 0x67, 0x6E, 0x6F]

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01


def _readable_regions(h, lo=0x10000, hi=0x7FFFFFFFFFFF, min_size=0x100000):
    """Walk committed, readable, non-guard regions big enough to hold the record object."""
    addr = lo
    while addr < hi:
        mbi = query(h, addr)
        if mbi is None:
            addr += 0x10000
            continue
        base, size, state, prot = mbi.BaseAddress, mbi.RegionSize, mbi.State, mbi.Protect
        if not size:
            break
        if state == MEM_COMMIT and size >= min_size and not (prot & (PAGE_GUARD | PAGE_NOACCESS)):
            yield base, size
        addr = base + size


def find_record_slots(h, limit=8):
    """Signature-scan for the rating array: 40 float32 at stride 0x10, inside the clamp range.

    Vectorised with numpy (same approach as read_match_memory.py) — a pure-Python loop over every
    16-byte candidate would take hours on a process this size. READ-ONLY: this only issues
    ReadProcessMemory, so it cannot affect or crash the game.
    """
    import numpy as np
    hits = []
    for base, size in _readable_regions(h):
        data = read_mem(h, base, size)
        if not data or len(data) < SLOTS_PER_TEAM * RATING_STRIDE:
            continue
        n = len(data) - (len(data) % 4)
        f = np.frombuffer(data[:n], dtype="<f4")
        for phase in range(RATING_STRIDE // 4):          # 16-byte stride = every 4th float32
            g = f[phase::RATING_STRIDE // 4]
            if g.size <= SLOTS_PER_TEAM:
                continue
            with np.errstate(invalid="ignore"):
                ok = np.isfinite(g) & (g >= RATING_LO) & (g <= RATING_HI) & (g != 0.0)
                zero = (g == 0.0)
            valid = ok | zero
            # windows of 40 that are entirely valid and hold >= 11 real ratings
            cs_ok = np.concatenate(([0], np.cumsum(ok, dtype=np.int32)))
            cs_va = np.concatenate(([0], np.cumsum(valid, dtype=np.int32)))
            w = SLOTS_PER_TEAM
            nwin = g.size - w
            if nwin <= 0:
                continue
            win_ok = cs_ok[w:w + nwin] - cs_ok[:nwin]
            win_va = cs_va[w:w + nwin] - cs_va[:nwin]
            for i in np.nonzero((win_va == w) & (win_ok >= 11))[0]:
                slot = base + phase * 4 + int(i) * RATING_STRIDE - RATING_OFF
                hits.append(slot)
                if len(hits) >= limit:
                    return hits
    return hits


def rating_of(h, slot, team, player):
    b = read_mem(h, slot + RATING_OFF + (team * 0x28 + player) * RATING_STRIDE, 4)
    return struct.unpack("<f", b)[0] if b else None


def player_record(slot, team, player):
    return slot + CONTAINER_OFF + REC_BASE + team * TEAM_STRIDE + player * PLAYER_STRIDE


def read_player(h, slot, team, player):
    """-> dict(rating, played, rows{idx:(made,attempted,c6,c7,c8)}, positions[13]) or None."""
    rec = player_record(slot, team, player)
    blob = read_mem(h, rec, 0x1100)
    if not blob or len(blob) < 0x1100:
        return None
    if blob[DNP_OFF] == 0xFF:
        return dict(rating=rating_of(h, slot, team, player), played=False, rows={}, positions=[])
    rows = {}
    for r in range(N_ROWS):
        o = STATS_OFF + r * ROW_STRIDE
        c = struct.unpack_from("<9i", blob, o)
        if any(c):
            rows[r] = (sum(c[0:8]), c)          # total (mode 5) + raw columns
    pos = list(struct.unpack_from("<13i", blob, POS_COUNTERS_OFF))
    return dict(rating=rating_of(h, slot, team, player), played=True, rows=rows, positions=pos)


def open_game():
    pid = find_pid()
    if not pid:
        sys.exit("eFootball.exe is not running — start a match (or sit on the full-time screen) first.")
    h = open_proc(pid)
    if not h:
        sys.exit("could not open the process (try an elevated terminal)")
    base, _size = module_base(h)
    return h, pid, base


def resolve_slot(h, a):
    if getattr(a, "slot", None):
        return int(a.slot, 16)
    print("scanning for the match record block…")
    hits = find_record_slots(h)
    if not hits:
        sys.exit("no record block found. Be at/after full time in a match, then retry.")
    if len(hits) > 1:
        print(f"  {len(hits)} candidates: " + ", ".join(hex(x) for x in hits) + "  (using the first)")
    return hits[0]


def cmd_scan(a):
    h, pid, base = open_game()
    print(f"eFootball.exe pid={pid} base={base:#x}")
    hits = find_record_slots(h)
    if not hits:
        print("no candidate record block found (are you in/after a match?)")
        return 1
    for s in hits:
        r0 = [rating_of(h, s, 0, p) for p in range(5)]
        r1 = [rating_of(h, s, 1, p) for p in range(5)]
        print(f"  RecordSlot {s:#x}  home[0:5]={[round(x,2) for x in r0]}  away[0:5]={[round(x,2) for x in r1]}")
    return 0


# (attempts_row, completions_row, derived name) -> completion% falls straight out
DERIVED = [(0x18, 0x19, "pass"), (0x1A, 0x1B, "pass_short"), (0x1C, 0x1D, "pass_through"),
           (0x1E, 0x1F, "pass_long"), (0x20, 0x21, "centering"), (0x34, 0x35, "tackle"),
           (0x46, 0x47, "dribble"), (0x06, 0x11, "shoot"), (0x6D, 0x6F, "gk_save")]


def derived(rows):
    """-> {name: (made, attempted, pct)} for every attempt/success pair with attempts."""
    out = {}
    for att_r, ok_r, name in DERIVED:
        att = rows.get(att_r, (0, None))[0]
        if att:
            ok = rows.get(ok_r, (0, None))[0]
            out[name] = (ok, att, 100.0 * ok / att)
    return out


def _fmt_rows(rows, raw):
    out = []
    for name, (ok, att, pct) in sorted(derived(rows).items()):
        out.append(f"      {name + ' %':22} {ok}/{att}  = {pct:.0f}%")
    for r, (total, cols) in sorted(rows.items()):
        name = ROW_NAMES.get(r)
        if not name and not raw:
            continue
        label = name or f"row_{r:02x}"
        star = "*" if r in RATING_ROWS else " "
        out.append(f"      {star}{label:28} {total}" + (f"   cols={[c for c in cols if c]}" if raw else ""))
    return out


def cmd_dump(a):
    h, _pid, _base = open_game()
    slot = resolve_slot(h, a)
    print(f"RecordSlot {slot:#x}   (* = row the rating formula reads)\n")
    for team, side in ((0, "HOME"), (1, "AWAY")):
        print(f"== {side}")
        for p in range(SLOTS_PER_TEAM):
            d = read_player(h, slot, team, p)
            if not d or not d["played"]:
                continue
            rt = d["rating"]
            print(f"  slot {p:2}  rating {rt:.2f}" if rt is not None else f"  slot {p:2}")
            for ln in _fmt_rows(d["rows"], a.raw):
                print(ln)
    return 0


def cmd_correlate(a):
    """Dump one player's every non-zero row+column — compare against the game's stats screen
    to name rows, then add them to ROW_NAMES."""
    h, _pid, _base = open_game()
    slot = resolve_slot(h, a)
    team = 0 if a.side == "home" else 1
    rec = player_record(slot, team, a.slot_no)
    blob = read_mem(h, rec, 0x1100)
    print(f"{a.side} slot {a.slot_no}  record {rec:#x}  rating {rating_of(h, slot, team, a.slot_no):.2f}")
    print(f"  {'row':>5}  {'c0':>5}{'c1':>5}{'c2':>5}{'c3':>5}{'c4':>5}{'c5':>5}{'c6':>5}{'c7':>5}{'c8':>5}   made/att")
    for r in range(N_ROWS):
        c = struct.unpack_from("<9i", blob, STATS_OFF + r * ROW_STRIDE)
        if not any(c):
            continue
        made, att = c[0] + c[1] + c[2], c[3] + c[4] + c[5]
        nm = ROW_NAMES.get(r, "")
        print(f"  {r:#5x}  " + "".join(f"{x:5}" for x in c) + f"   {made}/{att}  {nm}")
    return 0


DDL = """
CREATE TABLE IF NOT EXISTS match_player_stats (
    fixture_id INTEGER NOT NULL,
    side       TEXT    NOT NULL,           -- 'home' | 'away'
    slot       INTEGER NOT NULL,           -- squad slot, matches match_player_ratings
    stat       TEXT    NOT NULL,           -- 'pass_short_made' / 'row_62_made' / 'rating'
    value      REAL    NOT NULL,
    PRIMARY KEY (fixture_id, side, slot, stat)
);
"""


def cmd_save(a):
    h, _pid, _base = open_game()
    slot = resolve_slot(h, a)
    db = sqlite3.connect(a.db)
    db.executescript(DDL)
    n = 0
    for team, side in ((0, "home"), (1, "away")):
        for p in range(SLOTS_PER_TEAM):
            d = read_player(h, slot, team, p)
            if not d or not d["played"]:
                continue
            rows = [(a.fixture, side, p, "rating", float(d["rating"] or 0))]
            for r, (total, cols) in d["rows"].items():
                rows.append((a.fixture, side, p, ROW_NAMES.get(r, f"row_{r:02x}"), float(total)))
            for name, (ok, att, pct) in derived(d["rows"]).items():
                rows.append((a.fixture, side, p, f"{name}_pct", round(pct, 1)))
            db.executemany("INSERT OR REPLACE INTO match_player_stats VALUES (?,?,?,?,?)", rows)
            n += len(rows)
    db.commit()
    print(f"wrote {n} stat rows for fixture {a.fixture} -> {a.db}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slot", help="RecordSlot VA in hex (skip the scan)")
    ap.add_argument("--db", default=str(REPO / "build" / "master.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    p = sub.add_parser("dump"); p.add_argument("--raw", action="store_true")
    p = sub.add_parser("save"); p.add_argument("--fixture", type=int, required=True)
    p = sub.add_parser("correlate"); p.add_argument("--side", choices=("home", "away"), default="home")
    p.add_argument("--slot-no", type=int, default=0, dest="slot_no")
    a = ap.parse_args()
    return {"scan": cmd_scan, "dump": cmd_dump, "save": cmd_save, "correlate": cmd_correlate}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
