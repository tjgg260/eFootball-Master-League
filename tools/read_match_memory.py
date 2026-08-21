"""Read a finished match's TEAM STATS + PLAYER RATINGS from eFootball's live memory (read-only).

Run at the full-time results screen. No debugger, no injection — plain ReadProcessMemory, the
safe path. Emits JSON the app consumes:
  { "team_stats": {"home": {...}, "away": {...}}, "ratings": {"home": [...], "away": [...]} }

Usage: python tools/read_match_memory.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid, _open, _read, _regions, k32
from read_team_stats import STATS, _read_struct


def locate_best_team(h):
    """Most realistic team-stats struct: possession pair ~1.0 + populated modest int stats."""
    best = None                                   # (score, stats)
    for base, size in _regions(h):
        data = _read(h, base, size)
        n = len(data) - (len(data) % 4)
        if n < 4 * len(STATS) * 2:
            continue
        f = np.frombuffer(data[:n], dtype="<f4")
        ints = np.frombuffer(data[:n], dtype="<i4")
        with np.errstate(invalid="ignore", over="ignore"):
            a, b = f[:-1], f[1:]
            fin = np.isfinite(a) & np.isfinite(b)
            cand = np.nonzero(fin & (a > 0.05) & (a < 0.95) & (b > 0.05) & (b < 0.95)
                              & (np.abs(a + b - 1.0) < 0.004))[0]
        for i in cand:
            need = i + len(STATS) * 2
            if need >= len(ints):
                continue
            pairs = ints[i + 2:need]
            if pairs.min() < 0 or pairs.max() > 300 or int((pairs == 0).sum()) < 4:
                continue
            score = int((pairs > 0).sum()) * 100 - abs(int(pairs.sum()))  # populated but modest
            score = int((pairs > 0).sum())
            if best is None or score > best[0]:
                best = (score, _read_struct(f, ints, i))
    return best[1] if best else None


def read_ratings(h):
    """Locate the rating array (rating float @+0, -1 @+12, stride 24) and read every rating."""
    for base, size in _regions(h):
        data = _read(h, base, size)
        n = len(data) - (len(data) % 4)
        if n < 4 * 6 * 8:
            continue
        a = np.frombuffer(data[:n], dtype="<i4")
        af = np.frombuffer(data[:n], dtype="<f4")
        m1 = (a == -1)
        L = len(a) - 3
        with np.errstate(invalid="ignore"):
            rok = np.isfinite(af[:L]) & (af[:L] > 0.5) & (af[:L] < 10.0)
        valid = rok & m1[3:3 + L]
        for k in np.nonzero(valid)[0]:
            run = 0
            while k + run * 6 < len(valid) and valid[k + run * 6]:
                run += 1
            if run >= 8:
                # read every rating in the run (stride 6 ints = 24 bytes), rounded to 0.5
                out = []
                j = 0
                while k + j * 6 < len(af) and (j < run + 30):
                    v = float(af[k + j * 6])
                    if not (0.5 < v < 10.0) or a[k + j * 6 + 3] != -1:
                        break
                    out.append(round(v * 2) / 2)
                    j += 1
                return out
    return []


def main():
    pid = find_pid()
    if pid is None:
        print(json.dumps({"error": "eFootball not running"}))
        return 1
    h = _open(pid)
    try:
        team = locate_best_team(h)
        ratings = read_ratings(h)
    finally:
        k32.CloseHandle(h)

    result = {}
    if team:
        result["team_stats"] = {
            "home": {k: v[0] for k, v in team.items()},
            "away": {k: v[1] for k, v in team.items()},
        }
    if ratings:
        # first half = home XI (11), rest = away — the results page lists home then away
        half = 11 if len(ratings) >= 22 else len(ratings) // 2
        result["ratings"] = {"home": ratings[:half], "away": ratings[half:]}
    if not result:
        result["error"] = "no match data in memory — be on the full-time results screen"
    print(json.dumps(result, indent=2))
    return 0 if result.get("team_stats") or result.get("ratings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
