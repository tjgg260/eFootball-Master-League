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


def locate_and_read(h):
    best = None            # (activity, addr, stats)
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
            # possession pair: two fractions summing to EXACTLY 1.0 (percentages of 100)
            cand = np.nonzero(finite & (a > 0.05) & (a < 0.95) & (b > 0.05) & (b < 0.95)
                              & (np.abs(a + b - 1.0) < 0.006))[0]
        for i in cand:
            need = i + len(STATS) * 2
            if need >= len(ints):
                continue
            pairs = ints[i + 2: need]                  # int stats after possession
            if pairs.min() < 0 or pairs.max() > 5000:
                continue
            activity = int(pairs.sum())                # real full-time match has activity
            if activity < 20:                          # reject near-empty false pairs
                continue
            if best is None or activity > best[0]:
                best = (activity, base + i * 4, _read_struct(f, ints, i))
    return (best[1], best[2]) if best else (None, None)


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
