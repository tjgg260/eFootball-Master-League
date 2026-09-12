#!/usr/bin/env python3
"""
stats_read.py - read per-player match stats out of eFootball's live memory (READ-ONLY).

At full time the engine holds, for every player, the raw counters that feed the match rating
(touches, shots, passes attempted/completed, tackles, clearances, balls won/lost, cards, saves)
plus the final 0-10 rating. This pulls them out with ReadProcessMemory - the same read-only path
tools/mem_probe.py and tools/mem_scan.py already proved works on this game. Nothing is written to
the game; the only writes are to our own SQLite and to snapshot files.

    python tools/stats_read.py snapshot --out DIR   # FIRST at full time: regions to disk
    python tools/stats_read.py scan                 # locate the match record block
    python tools/stats_read.py dump                 # all players: rating + non-zero stat rows
    python tools/stats_read.py dump --raw           # include unnamed rows (row_NN) and columns
    python tools/stats_read.py verify               # cross-check vs the PROVEN team-stats reader
    python tools/stats_read.py save --fixture 123   # write into the app DB
    python tools/stats_read.py correlate --side home --slot-no 0   # one player, for naming rows
    python tools/stats_read.py selftest             # synthetic scan test, no game needed

MEMORY LAYOUT - corrected 2026-08-25 by direct disassembly of the installed exe.

The earlier hand-off spec put the rating array and the stats container on ONE object. They are
on TWO, one pointer apart. Verified in the rating driver 0x1442a0f90, where the SAME register
serves both:

    0x1442a0fbe  mov rcx, qword ptr [r15 + 0x6288]         ; r15+0x6288 -> RecordSlot
    0x1442a114b  mov ecx, dword ptr [r15 + rcx*8 + 0x1c4]  ; rating read off THE SAME r15

and confirmed from the other side in the aggregation 0x144288c40, where the team totals need
the load first (`mov rax,[r13+0x6288]` then `[rax + idx*4 + 0x106440]`).

    ctl = RecordControl          <- what the rating-array signature scan finds (hit - 0x1c4)
      + 0x1c0   float32 raw score (pre-normalisation), stride 0x10, (team*0x28 + player)
      + 0x1c4   float32 final rating 0-10,             stride 0x10, (team*0x28 + player)
      + 0x6288  uint64 POINTER -> RecordSlot                        <- THE DEREFERENCE

    slot = RecordSlot = *(uint64*)(ctl + 0x6288)
      + 0x78118   statsContainer (no further deref)
      + 0x106440  int32[0x867] team/match aggregate totals

    record = slot + 0x78118 + 0x65C0 + team*0x38238 + player*0x13E8   (accessor 0x1442e6640)
      record + 0x10 + row*0x24 + col*4   -> int32[0x77 rows][9 cols]  (getter 0x1443378c0)
      record + 0x10cc  uint8 min ability; 0xFF = DID NOT PLAY (slots are NOT zeroed)
      record + 0x10cd  uint8 max ability
      record + 0x10e0  int32[13] per-position play counters
      record + 0x1184  float32 final rating - the driver copies it in at 0x1442a1153.
                       Reading it through the container path and comparing against the array
                       proves the whole chain (deref, +0x78118, +0x65C0, both strides) at once.

COLUMNS ARE TIME BUCKETS, not made/attempted: 1st half -> c0/c1/c2 (minute <=15/<=30/>30),
2nd half -> c3/c4/c5, ET1 -> c6, ET2 -> c7, shootout -> c8. Attempts and completions are
SEPARATE ROWS, so completion% = row(..._success).total / row(...).total - see DERIVED.

"mode 5", the aggregate every rating term reads, is c0..c7 - eight of the nine columns,
excluding the shootout. Confirmed at 0x144337943, which sums +0x10..+0x2c and omits +0x30.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from live_patch import find_pid, open_proc, module_base, read_mem, query, k32   # noqa: E402


def default_db():
    """The app's database. Worktrees have no build/master.db of their own - the real one lives in
    the main checkout - so walk up until we find an existing file rather than silently creating
    an orphan next to whichever checkout this copy of the tool happens to sit in."""
    for d in [REPO, *REPO.parents]:
        cand = d / "build" / "master.db"
        if cand.is_file():
            return str(cand)
    return str(REPO / "build" / "master.db")

# ---- layout constants (see module docstring; all verified against the exe) ----
RATING_OFF = 0x1C4
RAW_SCORE_OFF = 0x1C0
RATING_STRIDE = 0x10
TEAM_RATING_STRIDE = 0x28 * RATING_STRIDE      # 0x280
RECORD_PTR_OFF = 0x6288                        # ctl + this -> POINTER to RecordSlot
CONTAINER_OFF = 0x78118
TOTALS_OFF = 0x106440
REC_BASE = 0x65C0
TEAM_STRIDE = 0x38238
PLAYER_STRIDE = 0x13E8
STATS_OFF = 0x10
ROW_STRIDE = 0x24
N_ROWS = 0x77
N_COLS = 9
DNP_OFF = 0x10CC
MAX_ABILITY_OFF = 0x10CD
POS_COUNTERS_OFF = 0x10E0
REC_RATING_OFF = 0x1184                        # driver's copy of the rating, inside the record
REC_READ = 0x1200                              # must cover 0x1184+4 and 0x10E0+52
SLOTS_PER_TEAM = 40

# The clamp the game applies. NOTE the dt270 field names are SWAPPED relative to the offsets:
# rating.o +0x260 is the MAX clamp and +0x264 the MIN. If you retune by name, re-check these.
RATING_LO, RATING_HI = 0.5, 10.0

# The SCAN floor is deliberately higher than the clamp. 1.0 is inside the clamp, and this process
# is full of 1.0-filled arrays (weights, scales, alphas) that otherwise match the signature 40
# slots at a time and bury the real record. A player who took the pitch does not score below 3.0.
# Distinct-value spread is the second filter: a window of identical values is not a rating array.
SCAN_LO = 3.0
MIN_DISTINCT = 3

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
WRITABLE = 0x04 | 0x08 | 0x40 | 0x80           # the record is a heap object
MAX_REGION = 512 * 1024 * 1024                 # live_patch.read_mem allocates size bytes flat

# Row index -> stat name. "proven" = tied to an increment site in the exe; the rest are dumped
# as row_NN so nothing is lost - run `correlate` to name them.
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
    0x11: 'shoot_scored',                       # proven
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
    0x24: 'lofted_pass',                        # likely  (was a duplicate name - see 0x25)
    0x25: 'lofted_pass_success',                # likely
    0x26: 'through_ball_grounder_variant',      # likely
    0x27: 'through_ball_grounder_variant_success',   # likely
    0x28: 'through_ball_lofted_variant',        # likely
    0x29: 'through_ball_lofted_variant_success',     # likely
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
    0x53: 'ball_won_cause_receiver_position_3',  # likely
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
    0x69: 'ball_lost_cause_receiver_position_3',  # likely
    0x6a: 'ball_lost_cause_type_2',             # likely
    0x6b: 'ball_lost_cause_type_0x10',          # likely
    0x6d: 'gk_shoot_faced',                     # proven - EVERY shot, unconditional
    0x6e: 'gk_inframe_shoot_faced',             # proven - guarded by on-target
    0x6f: 'gk_save',                            # proven
    0x70: 'gk_shoot_p_a',                       # proven
    0x72: 'gk_save_from_a_penalty_kick',        # likely
}

# Rows the rating compute was observed reading (0x14429ea40) - these are the ones that matter.
RATING_ROWS = [0x00, 0x04, 0x1A, 0x46, 0x62, 0x63, 0x64, 0x65, 0x67, 0x6E, 0x6F]

# (attempts_row, completions_row, derived name). Completion% falls straight out of the pair.
# gk_save divides by 0x6e (on-target shots faced), NOT 0x6d: row 0x6d increments for every shot
# faced unconditionally (increment site 0x1442af459), so it would understate save%.
DERIVED = [(0x18, 0x19, "pass"), (0x1A, 0x1B, "pass_short"), (0x1C, 0x1D, "pass_through"),
           (0x1E, 0x1F, "pass_long"), (0x20, 0x21, "centering"), (0x34, 0x35, "tackle"),
           (0x46, 0x47, "dribble"), (0x06, 0x11, "goal_conversion"),
           (0x06, 0x16, "shot_accuracy"), (0x6E, 0x6F, "gk_save")]

# Per-player rows that must sum, across a team's 40 slots, to the team-stats struct that
# tools/read_team_stats.py already reads and that we already trust. Twelve free equations.
TEAM_CHECK = {"passes": [0x18], "successful_passes": [0x19], "shots": [0x06],
              "shots_on_target": [0x16], "crosses": [0x20], "tackles": [0x34],
              "interceptions": [0x50], "fouls": [0x3C], "offsides": [0x3D],
              "corner_kicks": [0x44], "free_kicks": [0x42, 0x43], "saves": [0x6F]}


def _readable_regions(h, lo=0x10000, hi=0x7FFFFFFFFFFF, min_size=0x100000, writable_only=True):
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
        ok = (state == MEM_COMMIT and min_size <= size <= MAX_REGION
              and not (prot & (PAGE_GUARD | PAGE_NOACCESS)))
        if ok and writable_only and not (prot & WRITABLE):
            ok = False
        if ok:
            yield base, size
        addr = base + size


CHUNK = 32 * 1024 * 1024                        # cap one allocation; big regions are chunked
CHUNK_OVERLAP = 4096                            # > one 40-wide window (40*0x10 = 640 bytes)


def _scan_floats(f, base, loose=False):
    """Candidate RecordControl addresses from a float32 view of memory starting at `base`."""
    import numpy as np
    hits = []
    if f.size < SLOTS_PER_TEAM * (RATING_STRIDE // 4):
        return hits
    # One cheap pass first: a region with fewer than 11 in-band floats anywhere cannot hold a
    # window with 11 real ratings. This rejects the texture and audio blobs outright.
    lo = RATING_LO if loose else SCAN_LO
    with np.errstate(invalid="ignore"):
        in_band = (f >= lo) & (f <= RATING_HI)
    if int(np.count_nonzero(in_band)) < 11:
        return hits
    nz = f != 0.0
    for phase in range(RATING_STRIDE // 4):          # 16-byte stride = every 4th float32
        g = f[phase::RATING_STRIDE // 4]
        g_ok = (in_band & nz)[phase::RATING_STRIDE // 4]
        g_zero = (~nz)[phase::RATING_STRIDE // 4]
        if g_ok.size <= SLOTS_PER_TEAM:
            continue
        w = SLOTS_PER_TEAM
        nwin = g_ok.size - w + 1                     # windows 0 .. g.size-w inclusive
        if nwin <= 0:
            continue
        cs_ok = np.concatenate(([0], np.cumsum(g_ok, dtype=np.int32)))
        win_ok = cs_ok[w:w + nwin] - cs_ok[:nwin]
        sel = win_ok >= 11
        if not loose:
            cs_va = np.concatenate(([0], np.cumsum(g_ok | g_zero, dtype=np.int32)))
            sel &= (cs_va[w:w + nwin] - cs_va[:nwin]) == w
        for i in np.nonzero(sel)[0]:
            i = int(i)
            vals = g[i:i + w][g_ok[i:i + w]]         # the in-band entries of this window
            if np.unique(vals).size < MIN_DISTINCT:  # a flat run is not a rating array
                continue
            hits.append(base + phase * 4 + i * RATING_STRIDE - RATING_OFF)
    return hits


def scan_rating_arrays(data, base, loose=False):
    """Bytes-in wrapper around _scan_floats — used by `selftest`."""
    import numpy as np
    n = len(data) - (len(data) % 4)
    return _scan_floats(np.frombuffer(data[:n], dtype="<f4"), base, loose=loose)


def _read_floats(h, base, size):
    """ReadProcessMemory straight into a numpy float32 view — no intermediate bytes() copy.

    The copy matters: this process exposes ~5.6 GB of candidate regions, and `bytes(buf[:n])`
    doubles both the allocation and the memcpy for every one of them.
    """
    import ctypes
    import numpy as np
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
        return None
    n = got.value - (got.value % 4)
    if n <= 0:
        return None
    return np.frombuffer(buf, dtype="<f4", count=n // 4)


def find_record_slots(h, limit=64, loose=False, min_region=0x100000, verify=None, progress=False):
    """Signature-scan for candidate RecordControls. READ-ONLY.

    Regions are tried SMALLEST FIRST: the match record is an ordinary heap object, while the
    multi-hundred-MB regions are asset blobs. With `verify` supplied the scan stops at the first
    candidate that passes, so the big blobs are usually never read at all.
    """
    regions = sorted(_readable_regions(h, min_size=min_region), key=lambda r: r[1])
    total = sum(r[1] for r in regions)
    hits, scanned = [], 0
    for base, size in regions:
        off = 0
        while off < size:
            take = min(CHUNK, size - off)
            f = _read_floats(h, base + off, take)
            if f is not None:
                for c in _scan_floats(f, base + off, loose=loose):
                    if verify is not None:
                        # A junk candidate usually costs ONE read: container_of rejects it on an
                        # implausible +0x6288 pointer before the 80-slot squad check runs.
                        v = verify(c)
                        if v is not None and v["score"] > 0:
                            if progress:
                                print("", file=sys.stderr)
                            return [c]
                    # Junk must never end the scan early: keep only `limit` fallbacks, but go on
                    # looking for one that verifies.
                    if len(hits) < limit:
                        hits.append(c)
                    elif verify is None:
                        return hits[:limit]
            off += take - CHUNK_OVERLAP if take == CHUNK else take
        scanned += size
        if progress and total:
            pct = 100.0 * scanned / total
            print(f"\r  scanned {scanned / 2**30:5.2f}/{total / 2**30:.2f} GB ({pct:4.1f}%) "
                  f"{len(hits)} candidate(s)", end="", file=sys.stderr, flush=True)
    if progress:
        print("", file=sys.stderr)
    return hits


def read_u64(h, addr):
    b = read_mem(h, addr, 8)
    return struct.unpack("<Q", b)[0] if len(b) == 8 else None


def rating_of(h, ctl, team, player, off=RATING_OFF):
    b = read_mem(h, ctl + off + (team * SLOTS_PER_TEAM + player) * RATING_STRIDE, 4)
    return struct.unpack("<f", b)[0] if len(b) == 4 else None


def container_of(h, ctl, deref=True):
    """statsContainer for a candidate RecordControl.

    deref=True is the disassembly-proven path: RecordSlot = *(ctl + 0x6288), container =
    RecordSlot + 0x78118. deref=False is the older (refuted) hand-off reading, kept only so
    `verify` can show the difference on live data.
    """
    if not deref:
        return ctl + CONTAINER_OFF, ctl
    slot = read_u64(h, ctl + RECORD_PTR_OFF)
    if not slot or slot < 0x10000 or slot > 0x7FFFFFFFFFFF:
        return None, None
    return slot + CONTAINER_OFF, slot


def player_record(container, team, player):
    return container + REC_BASE + team * TEAM_STRIDE + player * PLAYER_STRIDE


def squad_shape(h, container):
    """(played_per_team, agreement) - how much this container looks like two real squads.

    played = slots whose DNP byte is not 0xFF and whose ability byte is plausible.
    agreement = players whose in-record rating copy (+0x1184) matches the ctl rating array.
    Garbage containers score near zero on both.
    """
    played = [0, 0]
    for team in (0, 1):
        for p in range(SLOTS_PER_TEAM):
            b = read_mem(h, player_record(container, team, p) + DNP_OFF, 2)
            if len(b) != 2:
                continue
            lo, hi = b[0], b[1]
            if lo != 0xFF and lo <= 99 and hi <= 99 and hi >= lo:
                played[team] += 1
    return played


def verify_chain(h, ctl, deref=True):
    """Score a candidate: squad shape + rating agreement between the array and the record copy."""
    container, slot = container_of(h, ctl, deref=deref)
    if container is None:
        return None
    played = squad_shape(h, container)
    agree = tot = 0
    for team in (0, 1):
        for p in range(SLOTS_PER_TEAM):
            rec = player_record(container, team, p)
            b = read_mem(h, rec + DNP_OFF, 1)
            if len(b) != 1 or b[0] == 0xFF:
                continue
            rb = read_mem(h, rec + REC_RATING_OFF, 4)
            ra = rating_of(h, ctl, team, p)
            if len(rb) == 4 and ra is not None:
                rr = struct.unpack("<f", rb)[0]
                tot += 1
                if abs(rr - ra) < 1e-4:
                    agree += 1
    plausible = all(6 <= n <= 25 for n in played)
    return dict(ctl=ctl, slot=slot, container=container, played=played, agree=agree, total=tot,
                score=(agree * 10) + (50 if plausible else 0))


def read_player(h, ctl, container, team, player):
    """-> dict(rating, raw, rec_rating, played, ability, rows{idx:(total,cols)}, positions)."""
    rec = player_record(container, team, player)
    blob = read_mem(h, rec, REC_READ)
    if not blob or len(blob) < REC_READ:
        return None
    rating = rating_of(h, ctl, team, player)
    raw = rating_of(h, ctl, team, player, off=RAW_SCORE_OFF)
    if blob[DNP_OFF] == 0xFF:
        return dict(rating=rating, raw=raw, rec_rating=None, played=False, ability=None,
                    rows={}, positions=[])
    rows = {}
    for r in range(N_ROWS):
        c = struct.unpack_from("<9i", blob, STATS_OFF + r * ROW_STRIDE)
        if any(c):
            rows[r] = (sum(c[0:8]), c)          # mode 5 total (c0..c7) + the raw columns
    return dict(rating=rating, raw=raw,
                rec_rating=struct.unpack_from("<f", blob, REC_RATING_OFF)[0],
                played=True, ability=(blob[DNP_OFF], blob[MAX_ABILITY_OFF]),
                rows=rows, positions=list(struct.unpack_from("<13i", blob, POS_COUNTERS_OFF)))


def open_game():
    pid = find_pid()
    if not pid:
        sys.exit("eFootball.exe is not running - start a match (or sit on the full-time screen) first.")
    h = open_proc(pid)                           # read-only: no PROCESS_VM_WRITE/VM_OPERATION
    if not h:
        sys.exit("could not open the process (try an elevated terminal)")
    base, _size = module_base(h)
    return h, pid, base


def resolve(h, a):
    """-> (ctl, container). Honours --slot; otherwise scans and picks the best-verified candidate."""
    deref = not getattr(a, "no_deref", False)
    if getattr(a, "slot", None):
        ctl = int(a.slot, 16)
    else:
        print("scanning for the match record block...", flush=True)
        hits = find_record_slots(h, limit=getattr(a, "limit", 64), loose=getattr(a, "loose", False),
                                 verify=lambda c: verify_chain(h, c, deref=deref), progress=True)
        if not hits:
            sys.exit("no record block found. Be in a match (or at full time), then retry.")
        scored = [v for v in (verify_chain(h, c, deref=deref) for c in hits) if v]
        scored.sort(key=lambda v: -v["score"])
        if not scored or scored[0]["score"] == 0:
            print(f"  {len(hits)} candidates, none verified; using the first ({hits[0]:#x})")
            ctl = hits[0]
        else:
            best = scored[0]
            print(f"  {len(hits)} candidates -> RecordControl {best['ctl']:#x} "
                  f"RecordSlot {best['slot']:#x} played={best['played']} "
                  f"rating-agreement {best['agree']}/{best['total']}")
            ctl = best["ctl"]
    container, slot = container_of(h, ctl, deref=deref)
    if container is None:
        sys.exit(f"RecordControl {ctl:#x} has no usable RecordSlot pointer at +{RECORD_PTR_OFF:#x}")
    if not deref:
        print(f"  !! --no-deref: reading container at ctl+{CONTAINER_OFF:#x} directly. This is the "
              f"REFUTED hand-off layout, for comparison only — expect garbage.")
    return ctl, container


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
        extra = ""
        if raw:
            extra = "   " + " ".join(f"c{i}={v}" for i, v in enumerate(cols) if v)
        out.append(f"      {star}{label:28} {total}{extra}")
    return out


def cmd_scan(a):
    h, pid, base = open_game()
    try:
        print(f"eFootball.exe pid={pid} base={base:#x}")
        deref = not getattr(a, "no_deref", False)
        hits = find_record_slots(h, limit=a.limit, loose=a.loose, progress=True,
                                 verify=lambda c: verify_chain(h, c, deref=deref))
        if not hits:
            print("no candidate record block found (are you in/after a match?)")
            return 1
        print(f"{len(hits)} candidate(s):")
        for c in hits:
            r0 = [rating_of(h, c, 0, p) for p in range(5)]
            r1 = [rating_of(h, c, 1, p) for p in range(5)]
            fmt = lambda xs: [None if x is None else round(x, 2) for x in xs]   # noqa: E731
            v = verify_chain(h, c)
            tag = ("  " + f"slot={v['slot']:#x} played={v['played']} "
                   f"agree={v['agree']}/{v['total']} score={v['score']}") if v else "  (no RecordSlot ptr)"
            print(f"  RecordControl {c:#x}  home[0:5]={fmt(r0)}  away[0:5]={fmt(r1)}")
            print(f"      {tag}")
        return 0
    finally:
        k32.CloseHandle(h)


def cmd_snapshot(a):
    """Capture the raw regions to disk BEFORE anything is interpreted. Do this first at full time:
    everything else can be re-derived offline from these bytes, and the record dies with the screen."""
    h, pid, base = open_game()
    try:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        hits = find_record_slots(h, limit=a.limit, loose=a.loose, min_region=int(str(a.min_region), 0))
        meta = dict(pid=pid, module_base=hex(base), rating_lo=RATING_LO, rating_hi=RATING_HI,
                    candidates=[], regions=[])
        seen = set()
        for c in hits:
            v = verify_chain(h, c)
            ptr = read_u64(h, c + RECORD_PTR_OFF)
            meta["candidates"].append(dict(
                ctl=hex(c), ptr_6288=(hex(ptr) if ptr else None),
                slot=(hex(v["slot"]) if v and v["slot"] else None),
                played=(v["played"] if v else None), agree=(v["agree"] if v else None),
                total=(v["total"] if v else None), score=(v["score"] if v else None),
                ratings=[[rating_of(h, c, t, p) for p in range(SLOTS_PER_TEAM)] for t in (0, 1)]))
            for addr in (c, ptr):
                if not addr:
                    continue
                mbi = query(h, addr)
                if mbi is None or mbi.BaseAddress in seen:
                    continue
                seen.add(mbi.BaseAddress)
                size = min(mbi.RegionSize, MAX_REGION)
                data = read_mem(h, mbi.BaseAddress, size)
                if not data:
                    continue
                name = f"region_{mbi.BaseAddress:x}_{len(data):x}.bin"
                (out / name).write_bytes(data)
                meta["regions"].append(dict(file=name, base=hex(mbi.BaseAddress), size=len(data)))
                print(f"  wrote {name}  ({len(data) / 1048576:.1f} MB)")
        best = max((c for c in meta["candidates"] if c["score"] is not None),
                   key=lambda c: c["score"], default=None)
        meta["best"] = best["ctl"] if best else (hex(hits[0]) if hits else None)
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"snapshot -> {out}  ({len(meta['regions'])} region(s), "
              f"{len(meta['candidates'])} candidate(s), best={meta['best']})")
        return 0 if hits else 1
    finally:
        k32.CloseHandle(h)


def cmd_dump(a):
    h, _pid, _base = open_game()
    try:
        ctl, container = resolve(h, a)
        print(f"RecordControl {ctl:#x}  container {container:#x}   (* = row the rating formula reads)\n")
        for team, side in ((0, "HOME"), (1, "AWAY")):
            print(f"== {side}")
            for p in range(SLOTS_PER_TEAM):
                d = read_player(h, ctl, container, team, p)
                if not d or not d["played"]:
                    continue
                rt = "  ".join(x for x in (
                    f"rating {d['rating']:.2f}" if d["rating"] is not None else "",
                    f"(rec {d['rec_rating']:.2f})" if d["rec_rating"] is not None else "",
                    f"raw {d['raw']:.3f}" if d["raw"] is not None else "",
                    f"ability {d['ability'][0]}-{d['ability'][1]}" if d["ability"] else "") if x)
                print(f"  slot {p:2}  {rt}")
                for ln in _fmt_rows(d["rows"], a.raw):
                    print(ln)
        return 0
    finally:
        k32.CloseHandle(h)


def cmd_verify(a):
    """Sum each row over a team's 40 slots and compare against the PROVEN team-stats reader.

    Twelve independent equations. If they hold, the RecordControl base, the +0x6288 deref, the
    0x13E8/0x38238 strides, the row indices and the mode-5 eight-column sum are all confirmed.
    """
    h, _pid, _base = open_game()
    try:
        ctl, container = resolve(h, a)
        sums = [{}, {}]
        for team in (0, 1):
            for p in range(SLOTS_PER_TEAM):
                d = read_player(h, ctl, container, team, p)
                if not d or not d["played"]:
                    continue
                for r, (total, _c) in d["rows"].items():
                    sums[team][r] = sums[team].get(r, 0) + total
        try:
            sys.path.insert(0, str(REPO / "tools"))
            from read_team_stats import locate_and_read
            _addr, team_stats = locate_and_read(h)
        except Exception as ex:                                  # noqa: BLE001
            print(f"could not read the proven team-stats struct ({ex}); printing our sums only")
            team_stats = None
        print(f"\n  {'stat':<20} {'ours H':>8} {'ours A':>8}" +
              (f" {'theirs H':>9} {'theirs A':>9}  ok" if team_stats else ""))
        agree = checked = 0
        for stat, rowlist in TEAM_CHECK.items():
            ours = [sum(sums[t].get(r, 0) for r in rowlist) for t in (0, 1)]
            line = f"  {stat:<20} {ours[0]:>8} {ours[1]:>8}"
            if team_stats and stat in team_stats:
                th, ta = team_stats[stat]
                ok = (ours[0] == th and ours[1] == ta)
                checked += 1
                agree += 1 if ok else 0
                line += f" {th:>9} {ta:>9}  {'OK' if ok else 'MISMATCH'}"
            print(line)
        if checked:
            print(f"\n  {agree}/{checked} equations hold.")
            if agree == checked:
                print("  => base, +0x6288 deref, strides, row indices and mode-5 all CONFIRMED.")
            elif agree == 0:
                print("  => nothing matches: the container is almost certainly wrong. Try "
                      "`--no-deref` to compare against the old (refuted) reading.")
        return 0
    finally:
        k32.CloseHandle(h)


def cmd_correlate(a):
    """Dump one player's every non-zero row and column, so rows can be named against the game's
    stats screen. Columns are TIME BUCKETS: c0-c2 = 1st half (<=15/<=30/>30), c3-c5 = 2nd half,
    c6 = ET1, c7 = ET2, c8 = shootout. Completion% is never within a row - it is a row PAIR."""
    h, _pid, _base = open_game()
    try:
        ctl, container = resolve(h, a)
        team = 0 if a.side == "home" else 1
        rec = player_record(container, team, a.slot_no)
        blob = read_mem(h, rec, REC_READ)
        if len(blob) < REC_READ:
            sys.exit(f"short read at {rec:#x}")
        rt = rating_of(h, ctl, team, a.slot_no)
        print(f"{a.side} slot {a.slot_no}  record {rec:#x}  "
              f"rating {'?' if rt is None else format(rt, '.2f')}")
        print(f"  {'row':>5}  " + "".join(f"{'c' + str(i):>5}" for i in range(N_COLS)) +
              f"   {'1H':>5}{'2H':>5}  {'tot':>5}  name")
        for r in range(N_ROWS):
            c = struct.unpack_from("<9i", blob, STATS_OFF + r * ROW_STRIDE)
            if not any(c):
                continue
            print(f"  {r:#5x}  " + "".join(f"{x:5}" for x in c) +
                  f"   {sum(c[0:3]):5}{sum(c[3:6]):5}  {sum(c[0:8]):5}  {ROW_NAMES.get(r, '')}")
        return 0
    finally:
        k32.CloseHandle(h)


DDL = """
CREATE TABLE IF NOT EXISTS match_player_stats (
    fixture_id INTEGER NOT NULL,
    side       TEXT    NOT NULL,           -- 'home' | 'away'
    slot       INTEGER NOT NULL,           -- ENGINE slot 0..39, NOT match_player_ratings.slot
    stat       TEXT    NOT NULL,           -- 'pass_short' / 'pass_short_pct' / 'row_62'
    value      REAL    NOT NULL,
    PRIMARY KEY (fixture_id, side, slot, stat)
);
"""


def cmd_save(a):
    h, _pid, _base = open_game()
    try:
        ctl, container = resolve(h, a)
        db = sqlite3.connect(a.db)
        db.executescript(DDL)
        n = 0
        for team, side in ((0, "home"), (1, "away")):
            for p in range(SLOTS_PER_TEAM):
                d = read_player(h, ctl, container, team, p)
                if not d or not d["played"]:
                    continue
                rows = []
                if d["rating"] is not None:
                    rows.append((a.fixture, side, p, "rating", float(d["rating"])))
                if d["raw"] is not None:
                    rows.append((a.fixture, side, p, "raw_score", float(d["raw"])))
                if d["ability"]:
                    rows.append((a.fixture, side, p, "ability_min", float(d["ability"][0])))
                    rows.append((a.fixture, side, p, "ability_max", float(d["ability"][1])))
                for r, (total, cols) in d["rows"].items():
                    name = ROW_NAMES.get(r, f"row_{r:02x}")
                    rows.append((a.fixture, side, p, name, float(total)))
                    if cols[8]:            # shootout column, excluded from the mode-5 total
                        rows.append((a.fixture, side, p, f"{name}_c8", float(cols[8])))
                for name, (ok, att, pct) in derived(d["rows"]).items():
                    rows.append((a.fixture, side, p, f"{name}_pct", round(pct, 1)))
                db.executemany("INSERT OR REPLACE INTO match_player_stats VALUES (?,?,?,?,?)", rows)
                n += len(rows)
        db.commit()
        print(f"wrote {n} stat rows for fixture {a.fixture} -> {a.db}")
        return 0
    finally:
        k32.CloseHandle(h)


def cmd_selftest(_a):
    """Scan math against a synthetic buffer - no game needed.

    Covers all four phase alignments and three tail shapes. `last` is the one that matters most:
    the rating array is the FINAL 40-wide window in the buffer, which an off-by-one in the window
    count silently drops. A test that does not include that case passes with the bug present.
    """
    import numpy as np
    base = 0x200000000
    cases, fails = 0, []

    def home_block(with_away):
        ratings = [7.5, 6.0, 6.5, 8.0, 5.5, 6.0, 7.0, 6.5, 6.0, 7.5, 6.0] + [0.0] * 29
        slots = SLOTS_PER_TEAM * (2 if with_away else 1)
        arr = np.zeros(slots * (RATING_STRIDE // 4), dtype="<f4")
        for i, v in enumerate(ratings):
            arr[i * 4] = v
        if with_away:
            for i in range(SLOTS_PER_TEAM):        # away block, so +0x280 reads back
                arr[(SLOTS_PER_TEAM + i) * 4] = 6.0 if i < 11 else 0.0
        return arr.tobytes()

    decoy = np.linspace(1e6, 2e6, 400).astype("<f4").tobytes()
    for phase in range(4):
        for tail in ("decoy", "away_end", "last"):
            pad = b"\x00" * (RATING_OFF + phase * 4)
            if tail == "last":
                data = pad + home_block(False)     # home array IS the final window
            elif tail == "away_end":
                data = pad + home_block(True)
            else:
                data = pad + home_block(True) + decoy
            cases += 1
            want = base + len(pad) - RATING_OFF
            hits = scan_rating_arrays(data, base)
            if want not in hits:
                fails.append(f"phase={phase} tail={tail}: {want:#x} not found "
                             f"(hits={[hex(x) for x in hits]})")
                continue
            if tail != "last":
                off = want + RATING_OFF + TEAM_RATING_STRIDE - base
                away = struct.unpack_from("<f", data, off)[0]
                if abs(away - 6.0) > 1e-6:
                    fails.append(f"phase={phase} tail={tail}: away block read {away}, want 6.0")
    for f in fails:
        print("FAIL " + f)
    print(f"selftest: {cases - len(fails)}/{cases} cases passed")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slot", help="RecordControl VA in hex (skip the scan)")
    ap.add_argument("--limit", type=int, default=64, help="max scan candidates")
    ap.add_argument("--loose", action="store_true",
                    help="drop the all-slots-valid rule (use if the clamp was retuned)")
    ap.add_argument("--no-deref", action="store_true", dest="no_deref",
                    help="read the container at ctl+0x78118 without the +0x6288 deref — the old, "
                         "refuted hand-off layout. Diagnostic comparison only.")
    ap.add_argument("--db", default=default_db(),
                    help="app database (defaults to the nearest existing build/master.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    p = sub.add_parser("snapshot")
    p.add_argument("--out", required=True)
    p.add_argument("--min-region", default="0x100000", dest="min_region")
    p = sub.add_parser("dump")
    p.add_argument("--raw", action="store_true")
    sub.add_parser("verify")
    p = sub.add_parser("save")
    p.add_argument("--fixture", type=int, required=True)
    p = sub.add_parser("correlate")
    p.add_argument("--side", choices=("home", "away"), default="home")
    p.add_argument("--slot-no", type=int, default=0, dest="slot_no")
    sub.add_parser("selftest")
    a = ap.parse_args()
    return {"scan": cmd_scan, "snapshot": cmd_snapshot, "dump": cmd_dump, "verify": cmd_verify,
            "save": cmd_save, "correlate": cmd_correlate, "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
