#!/usr/bin/env python3
"""
playstyle_secondary.py — write the SECONDARY (defending / out-of-possession) playing style into a
400-byte Player.bin record. Companion to playstyle_bits.py (primary/attacking style).

Cracked via the game's own catalog (common/etc/pesdb/Playstyle.bin — 36 entries at 168-byte
stride, internal names PS_*): the secondary field at bit 440 (6 bits) stores the GLOBAL catalog
INDEX directly — see playstyle_catalog.py for the full decode + how the value was confirmed
against every player in Konami's own export. Confirmed exactly on every style present in the
roster: The Destroyer=9 (PS_ATTK_PREVENTER), Attacking GK=16 (PS_LIBERO_GK), Defensive GK=17
(PS_CLASSICAL_GK), Attack Outlet=26 (PS_OUTLET_FORWARD).
"""
from __future__ import annotations

from playstyle_catalog import SECONDARY as STYLE_INDEX

SEC_BIT = 440
SEC_WIDTH = 6


def read_field(rec) -> int:
    v = 0
    for i in range(SEC_WIDTH):
        b = SEC_BIT + i
        v |= ((rec[b >> 3] >> (b & 7)) & 1) << i
    return v


def write_field(rec, value: int) -> None:
    for i in range(SEC_WIDTH):
        b = SEC_BIT + i
        if (value >> i) & 1:
            rec[b >> 3] |= 1 << (b & 7)
        else:
            rec[b >> 3] &= ~(1 << (b & 7))


def value_for(style: str) -> int | None:
    """Global catalog index for a defensive/GK secondary style, or None if not a real one."""
    return STYLE_INDEX.get(style)


def write_secondary(rec: bytearray, position: str, style: str) -> bool:
    """
    Write the secondary style. `position` is unused (the index is global) but kept for call-site
    compatibility. Offensive styles that merely mirror the primary (Box-to-Box, Anchor Man, Basic)
    are not real secondary styles -> field left at 0/Basic. Returns True if a code was written.
    """
    idx = value_for(style) if style else None
    if idx is None:
        # not a defensive/GK style -> secondary is Basic; clear the field
        write_field(rec, 0)
        return False
    write_field(rec, idx)
    return True


if __name__ == "__main__":
    print(f"{len(STYLE_INDEX)} secondary names mapped to catalog indices (field bit {SEC_BIT} w{SEC_WIDTH})")
    for s, i in sorted(STYLE_INDEX.items(), key=lambda kv: kv[1]):
        print(f"  {i:2d}  {s}")
    # round-trip
    rec = bytearray(400)
    write_secondary(rec, "DEF", "Pass Disruptor")
    assert read_field(rec) == 28, read_field(rec)
    print("round-trip OK (Pass Disruptor -> 28)")
    assert value_for("High Line GK") == 35
    print("High Line GK -> 35 OK")
