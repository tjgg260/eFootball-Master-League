#!/usr/bin/env python3
"""
playstyle_bits.py — read and write a player's primary playing style in Player.bin.

Located empirically against eFootball's own export (primary_playing_style column, matched by PID):
the style is a 5-bit field at bit offset 374 — byte 46 bits 6-7 + byte 47 bits 0-2. Purity 1.000
across 23,498 players. The raw 5-bit value is scoped BY POSITION (the same value reads as different
styles depending on the player's position), exactly as eFootball presents playstyles, so we keep a
(position, style) -> value table built from the game's own data.
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

STYLE_BIT = 374   # little-endian bit offset within the 400-byte record


def read_playstyle(rec: bytes) -> int:
    """The raw 5-bit playstyle value at byte 46.6."""
    return ((rec[46] >> 6) & 0x03) | ((rec[47] & 0x07) << 2)


def write_playstyle(rec: bytearray, value: int) -> None:
    """Set the 5-bit playstyle value, touching only those 5 bits."""
    value &= 0x1F
    rec[46] = (rec[46] & 0x3F) | ((value & 0x03) << 6)
    rec[47] = (rec[47] & 0xF8) | ((value >> 2) & 0x07)


def _pos_cat(pos: str) -> str:
    pos = (pos or "").upper()
    if pos == "GK":
        return "GK"
    if pos in ("CB", "LB", "RB", "LWB", "RWB"):
        return "DEF"
    if pos in ("DMF", "CMF", "LMF", "RMF", "AMF"):
        return "MID"
    return "FWD"


def build_style_table():
    """(position category, style name) -> value  and  (category, value) -> style, from the export."""
    rows = list(csv.DictReader(io.StringIO(EF_CSV.read_bytes().decode("utf-8-sig"))))
    # We only have the CSV's style + position; the value comes from Player.bin, so pair them by PID.
    sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
    import wesys  # noqa: E402
    pb = wesys.unpack_wesys_payload((REPO / "build" / "tree_base" / "common/etc/pesdb/Player.bin").read_bytes())
    pid_value = {}
    for k in range(len(pb) // 400):
        pid = struct.unpack_from("<Q", pb, k * 400 + 8)[0]
        pid_value[pid] = read_playstyle(pb[k * 400:k * 400 + 400])

    votes = defaultdict(Counter)     # (cat, style) -> Counter(value)
    for r in rows:
        style = r.get("primary_playing_style", "").strip()
        pos = r.get("position", "").strip()
        if not style or not r.get("player_id", "").isdigit():
            continue
        pid = int(r["player_id"])
        if pid in pid_value:
            votes[(_pos_cat(pos), style)][pid_value[pid]] += 1

    to_value = {key: c.most_common(1)[0][0] for key, c in votes.items()}
    return to_value


def value_for(to_value: dict, position: str, style: str) -> int | None:
    """The 5-bit value that gives `style` for a player in `position` (None if unknown)."""
    return to_value.get((_pos_cat(position), style))


def _prove() -> int:
    sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
    import wesys  # noqa: E402
    pb = bytearray(wesys.unpack_wesys_payload(
        (REPO / "build" / "tree_base" / "common/etc/pesdb/Player.bin").read_bytes()))
    rec = bytearray(pb[:400])
    original = bytes(rec)
    before = read_playstyle(rec)
    # round-trip: writing back the same value must be byte-identical
    write_playstyle(rec, before)
    assert bytes(rec) == original, "same-value write changed bytes"
    # write a different value, read it back, then restore
    write_playstyle(rec, (before + 7) & 0x1F)
    assert read_playstyle(rec) == (before + 7) & 0x1F, "readback mismatch"
    changed = sum(1 for a, b in zip(original, rec) if a != b)
    write_playstyle(rec, before)
    assert bytes(rec) == original, "restore failed"
    tbl = build_style_table()
    print(f"round-trip OK (same-value write byte-identical; a change touches {changed} byte(s))")
    print(f"(position, style) -> value table: {len(tbl)} entries")
    for key in [("MID", "Box-to-Box"), ("FWD", "Goal Poacher"), ("DEF", "Attacking Full-back"),
                ("MID", "Creative Playmaker"), ("FWD", "Target Man")]:
        print(f"   {key} -> value {tbl.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_prove())
