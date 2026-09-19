#!/usr/bin/env python3
"""
playstyle_bits.py — read and write a player's primary (in-possession) playing style in Player.bin.

Located empirically against eFootball's own export (primary_playing_style column, matched by PID):
the style is a 5-bit field at bit offset 374 — byte 46 bits 6-7 + byte 47 bits 0-2. Purity 1.000
across 23,498 players.

The raw value is the GLOBAL `common/etc/pesdb/Playstyle.bin` catalog index (playstyle_catalog.py),
not position-scoped — confirmed 2026-09-15 by pooling all positions and finding a unique raw->style
mapping (purity ~1.0). An older version of this file paired (position, style) -> value at runtime
against samples/editor-bundled-players.csv + build/tree_base; that dependency is gone now that the
static catalog is proven, which also matters for the shipped app (no CSV/tree_base at runtime — see
memory "release-external-tools"). `build_style_table()`/`value_for()` keep their old (position
category, style) -> value shape for the existing call sites (play_match.py, ml_author.py,
validate_db.py) but the value no longer depends on position at all.
"""
from __future__ import annotations

from playstyle_catalog import PRIMARY

STYLE_BIT = 374   # little-endian bit offset within the 400-byte record

_POS_CATS = ("GK", "DEF", "MID", "FWD")


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


def build_style_table() -> dict[tuple[str, str], int]:
    """(position category, style name) -> raw catalog index. Position-independent (kept as a
    dict keyed by category for API compatibility with existing call sites); GK carries no primary
    entries because indices 9/16/17 render as Basic when written to the primary field — a
    goalkeeper's real style lives in the secondary field (playstyle_secondary.py)."""
    return {
        (cat, name): idx
        for cat in _POS_CATS
        for name, idx in PRIMARY.items()
        if not (cat == "GK" and name != "Basic")
    }


def value_for(to_value: dict, position: str, style: str) -> int | None:
    """The 5-bit value that gives `style` for a player in `position` (None if unknown)."""
    return to_value.get((_pos_cat(position), style))


def _prove() -> int:
    import sys
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo / "tools" / "vendor" / "sider"))
    import wesys  # noqa: E402
    pb = bytearray(wesys.unpack_wesys_payload(
        (repo / "build" / "tree_base" / "common/etc/pesdb/Player.bin").read_bytes()))
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
    print(f"(position, style) -> value table: {len(tbl)} entries (static catalog, no CSV needed)")
    for key in [("MID", "Box-to-Box"), ("FWD", "Goal Poacher"), ("DEF", "Attacking Full-back"),
                ("MID", "Creative Playmaker"), ("FWD", "Target Man"), ("GK", "Basic")]:
        print(f"   {key} -> value {tbl.get(key)}")
    assert ("GK", "Attacking GK") not in tbl, "GK primary must stay empty (inert in-game)"
    return 0


if __name__ == "__main__":
    raise SystemExit(_prove())
