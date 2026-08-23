#!/usr/bin/env python3
"""
playstyle_secondary.py — write the SECONDARY (defending / out-of-possession) playing style into a
400-byte Player.bin record. Companion to playstyle_bits.py (primary/attacking style).

Cracked via the game's own catalog (common/etc/pesdb/Playstyle.bin — 36 entries at 168-byte
stride, internal names PS_*): the secondary field at bit 440 (6 bits) stores the GLOBAL catalog
INDEX directly. Confirmed exactly on every style present in the roster:
    The Destroyer=9 (PS_ATTK_PREVENTER), Attacking GK=16 (PS_LIBERO_GK),
    Defensive GK=17 (PS_CLASSICAL_GK), Attack Outlet=26 (PS_OUTLET_FORWARD).
The remaining defensive/GK styles have no player in any extractable Player.bin (≈30 special-card
players total), so their index comes from the catalog's internal name — name-exact for
Covering Role / Sweeper GK, semantic for the rest. NOT position-scoped: a style's index is the
same regardless of position.
"""
from __future__ import annotations

SEC_BIT = 440
SEC_WIDTH = 6

# display style name -> global Playstyle.bin catalog index.
#
# The rare defensive/GK indices (23..35) are Konami's OWN authoritative English names, read verbatim
# from a contiguous catalog-order string array in the decrypted eng/string/all.str
# (dt261_eng_console_win.cpk), pinned by data + name-exact anchors (Attack Outlet=26 confirmed from
# Player.bin, Covering Role=29, Sweeper GK=33, Build-up GK=34). Order: index 23+position.
STYLE_INDEX = {
    # --- data-confirmed against Player.bin (bit 440) ---
    "The Destroyer": 9,          # PS_ATTK_PREVENTER  (n=1404)
    "Attacking GK": 16,          # PS_LIBERO_GK       (n=1255)
    "Offensive GK": 16,          # UI alias of Attacking GK
    "Defensive GK": 17,          # PS_CLASSICAL_GK    (n=930)
    "Attack Outlet": 26,         # PS_OUTLET_FORWARD  (confirmed)
    # --- from Konami's own all.str, contiguous catalog-order array (indices 23..35) ---
    "Press Back": 23,            # PS_PRESS_BACK
    "Front Line Pressure": 24,   # PS_FIRST_DEFENDER
    "Front Line Poacher": 25,    # PS_COVER_SHADOW
    "All-action Defender": 27,   # PS_HARD_WORKER
    "Pass Disruptor": 28,        # PS_LANE_BLOCKER
    "Covering Role": 29,         # PS_COVERING
    "High Line Master": 30,      # PS_LINE_CONTROLLER
    "Tough Marker": 31,          # PS_HARD_MARKER
    "Deep Defender": 32,         # PS_DEEP_LINE_DEFENDER
    "Sweeper GK": 33,            # PS_SWEEPER_GK
    "Build-up GK": 34,           # PS_BUILD_UP_GK
    "High Line GK": 35,          # PS_ADVANCED_GK
    "Advanced GK": 35,           # alias
}


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
    print(f"{len(STYLE_INDEX)} secondary styles mapped to catalog indices (field bit {SEC_BIT} w{SEC_WIDTH})")
    for s, i in sorted(STYLE_INDEX.items(), key=lambda kv: kv[1]):
        print(f"  {i:2d}  {s}")
    # round-trip
    rec = bytearray(400)
    write_secondary(rec, "DEF", "Pass Disruptor")
    assert read_field(rec) == 28, read_field(rec)
    print("round-trip OK (Pass Disruptor -> 28)")
