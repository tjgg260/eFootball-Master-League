"""Locate + read eFootball's live team-stats struct every match (no hardcoded address).

The struct (mapped from the full-time Team Stats screen) is home/away pairs at 8-byte stride,
led by a possession pair of float32s that sum to ~1.0. We locate it by that signature — two
adjacent in-(0,1) floats summing to 1.0, followed by a run of small non-negative int pairs —
then read all 13 stats for both teams. Read-only.

Usage: python tools/read_team_stats.py            # print the current match's team stats
       python tools/read_team_stats.py --json      # machine-readable (for the app)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid, _open, _regions, _read, k32

# stat order from the possession pair onward; each is a home/away int pair 8 bytes apart
STATS = ["possession", "shots", "shots_on_target", "fouls", "offsides", "corner_kicks",
         "free_kicks", "passes", "successful_passes", "crosses", "interceptions",
         "tackles", "saves"]


def _read_struct(f, ints, i):
    out = {}
    for s, k in enumerate(STATS):
        hi = i + s * 2
        if s == 0:
            out[k] = (round(float(f[hi]) * 100), round(float(f[hi + 1]) * 100))
        else:
            out[k] = (int(ints[hi]), int(ints[hi + 1]))
    return out


def locate_candidates(h):
    """All addresses that look like a real team-stats struct (possession + realistic ints)."""
    cands = []                                          # absolute address of possession-home float
    for base, size in _regions(h):
        data = _read(h, base, size)
        n = len(data) - (len(data) % 4)
        if n < 4 * (len(STATS) * 2):
            continue
        f = np.frombuffer(data[:n], dtype="<f4")
        ints = np.frombuffer(data[:n], dtype="<i4")
        with np.errstate(invalid="ignore", over="ignore"):
            a, b = f[:-1], f[1:]
            finite = np.isfinite(a) & np.isfinite(b)
            cand = np.nonzero(finite & (a > 0.05) & (a < 0.95) & (b > 0.05) & (b < 0.95)
                              & (np.abs(a + b - 1.0) < 0.004))[0]
        for i in cand:
            need = i + len(STATS) * 2
            if need >= len(ints):
                continue
            pairs = ints[i + 2: need]                   # the 24 int stats after possession
            # REAL match: modest values, and several zeros (garbage structs have neither)
            if pairs.min() < 0 or pairs.max() > 300:
                continue
            if int((pairs == 0).sum()) < 4:
                continue
            cands.append(int(base + i * 4))
    return cands


def locate_by_passes(h, home, away):
    """Find the team-stats struct by its exact current passes pair (works while paused)."""
    for base, size in _regions(h):
        data = _read(h, base, size)
        n = len(data) - (len(data) % 4)
        if n < 4 * (len(STATS) * 2):
            continue
        f = np.frombuffer(data[:n], dtype="<f4")
        ints = np.frombuffer(data[:n], dtype="<i4")
        with np.errstate(invalid="ignore", over="ignore"):
            a, b = f[:-1], f[1:]
            finite = np.isfinite(a) & np.isfinite(b)
            cand = np.nonzero(finite & (a > 0.02) & (a < 0.98) & (b > 0.02) & (b < 0.98)
                              & (np.abs(a + b - 1.0) < 0.02))[0]
        ph = 7 * 2                                       # passes home index from possession home
        for i in cand:
            if i + ph + 1 >= len(ints):
                continue
            if int(ints[i + ph]) == home and int(ints[i + ph + 1]) == away:
                return int(base + i * 4)
    return None


def _read_u32(h, addr):
    d = _read(h, addr, 4)
    return int.from_bytes(d, "little") if len(d) == 4 else -1


def locate_live(h):
    """Pick the struct whose PASSES are changing right now — that's the live match, not a corpse."""
    import time as _t
    cands = locate_candidates(h)
    if not cands:
        return None
    passes_off = 7 * 8                                   # passes home offset from possession home
    first = {a: (_read_u32(h, a + passes_off), _read_u32(h, a + passes_off + 4)) for a in cands}
    _t.sleep(1.5)
    changed = [a for a in cands
               if (_read_u32(h, a + passes_off), _read_u32(h, a + passes_off + 4)) != first[a]]
    return (changed or cands)[0]


def locate_and_read(h):
    """Best single struct: the live (changing) one if any, else the first realistic candidate."""
    addr = locate_live(h)
    if addr is None:
        return None, None
    data = _read(h, addr - 0, 4 * (len(STATS) * 2) + 8)
    n = len(data) - (len(data) % 4)
    f = np.frombuffer(data[:n], dtype="<f4")
    ints = np.frombuffer(data[:n], dtype="<i4")
    return addr, _read_struct(f, ints, 0)


def main():
    pid = find_pid() or sys.exit("eFootball not running.")
    h = _open(pid)
    try:
        addr, stats = locate_and_read(h)
    finally:
        k32.CloseHandle(h)
    if stats is None:
        print("No team-stats struct found. Be on the full-time Team Stats screen.")
        return 1
    if "--json" in sys.argv:
        print(json.dumps({"addr": hex(addr), "home": {k: v[0] for k, v in stats.items()},
                          "away": {k: v[1] for k, v in stats.items()}}, indent=2))
        return 0
    print(f"team-stats struct @ {hex(addr)}\n")
    print(f"  {'stat':<20} {'HOME':>6} {'AWAY':>6}")
    for k, (hv, av) in stats.items():
        unit = "%" if k == "possession" else ""
        print(f"  {k:<20} {str(hv)+unit:>6} {str(av)+unit:>6}")
    pc_h = stats['successful_passes'][0] / stats['passes'][0] * 100 if stats['passes'][0] else 0
    pc_a = stats['successful_passes'][1] / stats['passes'][1] * 100 if stats['passes'][1] else 0
    print(f"\n  pass completion:  home {pc_h:.0f}%   away {pc_a:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
