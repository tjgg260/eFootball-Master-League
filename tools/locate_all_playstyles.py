#!/usr/bin/env python3
"""
locate_all_playstyles.py — locate ALL THREE playstyle fields in Player.bin by purity scan.

eFootball 2027 gives every player up to three style dimensions, all present in the game's own
editor export (samples/editor-bundled-players.csv):
  * primary_playing_style   — the in-possession role   (Goal Poacher, Build Up, ...)
  * secondary_playing_style — the second/defensive role (The Destroyer, Attacking GK, ...)
  * ai_playing_styles       — COM behaviour flags, multi-valued (Long Ranger, Trickster, ...)

We locate each single-value field the same way playstyle_bits.py proved the primary: scan a window
of little-endian bit offsets x widths, pair each record to its CSV row by PID, and score PURITY =
fraction of players whose (position-category, raw-value) maps to the majority style for that key.
The winning (offset,width) with purity ~1.0 IS the field. We print the winner + its value tables.
"""
from __future__ import annotations

import csv
import io
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EF_CSV = REPO / "samples" / "editor-bundled-players.csv"
PLAYER_BIN = REPO / "build" / "tree_base" / "common/etc/pesdb/Player.bin"
REC = 400

sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402


def pos_cat(pos: str) -> str:
    pos = (pos or "").upper()
    if pos == "GK":
        return "GK"
    if pos in ("CB", "LB", "RB", "LWB", "RWB"):
        return "DEF"
    if pos in ("DMF", "CMF", "LMF", "RMF", "AMF"):
        return "MID"
    return "FWD"


def read_bits(rec: bytes, bit_off: int, width: int) -> int:
    """Little-endian bit field: bit_off is the LSB position counting from byte0 bit0."""
    val = 0
    for i in range(width):
        b = bit_off + i
        val |= ((rec[b >> 3] >> (b & 7)) & 1) << i
    return val


def load():
    pb = wesys.unpack_wesys_payload(PLAYER_BIN.read_bytes())
    recs = {}
    for k in range(len(pb) // REC):
        base = k * REC
        pid = struct.unpack_from("<Q", pb, base + 8)[0]
        recs[pid] = pb[base:base + REC]
    rows = list(csv.DictReader(io.StringIO(EF_CSV.read_bytes().decode("utf-8-sig"))))
    return recs, rows


def scan(recs, rows, column, lo=340, hi=470, widths=range(4, 9)):
    """Return (best_off, best_width, purity, table) for a single-value style column."""
    # pair (poscat, style) truth per pid
    truth = {}
    for r in rows:
        style = (r.get(column) or "").strip()
        pid = r.get("player_id", "")
        if style and pid.isdigit() and int(pid) in recs:
            truth[int(pid)] = (pos_cat(r.get("position", "")), style)
    best = None
    for width in widths:
        for off in range(lo, hi):
            votes = defaultdict(Counter)                 # (poscat, rawval) -> Counter(style)
            for pid, (cat, style) in truth.items():
                raw = read_bits(recs[pid], off, width)
                votes[(cat, raw)][style] += 1
            # purity = players agreeing with the majority style of their (cat,raw) bucket
            hit = tot = 0
            for key, c in votes.items():
                tot += sum(c.values())
                hit += c.most_common(1)[0][1]
            purity = hit / tot if tot else 0
            if best is None or purity > best[2]:
                best = (off, width, purity, votes)
    off, width, purity, votes = best
    table = {key: c.most_common(1)[0][0] for key, c in votes.items()}
    return off, width, purity, table


def main():
    recs, rows = load()
    print(f"Player.bin records: {len(recs)}   CSV rows: {len(rows)}\n")
    for col in ("primary_playing_style", "secondary_playing_style"):
        off, width, purity, table = scan(recs, rows, col)
        print(f"== {col} ==")
        print(f"   best field: bit {off}, width {width}  ->  purity {purity:.4f}")
        # show the (cat,raw)->style table compactly
        by_cat = defaultdict(list)
        for (cat, raw), style in sorted(table.items()):
            by_cat[cat].append((raw, style))
        for cat in ("GK", "DEF", "MID", "FWD"):
            if cat in by_cat:
                pairs = ", ".join(f"{raw}:{style}" for raw, style in by_cat[cat])
                print(f"     {cat}: {pairs}")
        print()


if __name__ == "__main__":
    main()
