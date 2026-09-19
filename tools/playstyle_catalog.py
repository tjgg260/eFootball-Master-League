#!/usr/bin/env python3
"""
playstyle_catalog.py — the single source of truth for all 36 entries of the game's own
`common/etc/pesdb/Playstyle.bin` catalog, and which of the two Player.bin fields each one is
valid in.

Decoded 2026-09-15 straight from Playstyle.bin (36 x 168-byte records: 4-byte header whose low
byte is the catalog index, a Japanese display name, and a `PS_` internal key) and cross-checked
against Konami's own editor export (23,555 Player.bin records paired to
samples/editor-bundled-players.csv by player_id, purity ~1.0 for every value that occurs).

BOTH Player.bin style fields — primary/in-possession (playstyle_bits.py, bit 374, 5 bits) and
secondary/out-of-possession (playstyle_secondary.py, bit 440, 6 bits) — store this SAME global
catalog index. It is NOT position-scoped: a given index means the same style regardless of the
player's position. Older code paired (position, style) -> value at runtime against the editor CSV;
that only ever reproduced this static table (plus a runtime dependency on
samples/editor-bundled-players.csv + build/tree_base that the shipped app must not carry — see
memory "release-external-tools").

CONFIRMED BUG (fixed alongside this catalog): indices 9 (The Destroyer), 16 (Attacking GK) and 17
(Defensive GK) are SECONDARY-ONLY. Every Player.bin record in Konami's own data that carries one of
those three values in the PRIMARY field is displayed by the editor as "Basic" — the game does not
recognise them there. Goalkeepers therefore have no meaningful *primary* playing style at all: their
one real style pick is the secondary/out-of-possession field (Attacking GK / Defensive GK / Sweeper
GK / Build-up GK / High Line GK). PRIMARY below intentionally excludes GK styles for this reason.
"""
from __future__ import annotations

# index -> (English name, PS_ internal key)
CATALOG: dict[int, tuple[str, str]] = {
    0: ("Basic", None),
    1: ("Goal Poacher", "PS_LINE_BREAKER"),
    2: ("Dummy Runner", "PS_DECOY_RUN"),
    3: ("Fox in the Box", "PS_BOX_STRIKER"),
    4: ("Prolific Winger", "PS_WING_STRIKER"),
    5: ("Classic No. 10", "PS_NUMBER_10"),
    6: ("Hole Player", "PS_CHANCE_GETTER"),
    7: ("Box-to-Box", "PS_BOX_TO_BOX"),
    8: ("Anchor Man", "PS_ANCHOR"),
    9: ("The Destroyer", "PS_ATTK_PREVENTER"),          # secondary-only
    10: ("Extra Frontman", "PS_OVERLAP"),
    11: ("Attacking Full-back", "PS_OFFENSIVE_SB"),
    12: ("Defensive Full-back", "PS_DEFENSIVE_SB"),
    13: ("Deep-Lying Forward", "PS_POST_PLAYER"),
    14: ("Creative Playmaker", "PS_CHANCE_MAKER"),
    15: ("Build Up", "PS_BUILD_UP"),
    16: ("Attacking GK", "PS_LIBERO_GK"),                # secondary-only
    17: ("Defensive GK", "PS_CLASSICAL_GK"),             # secondary-only
    18: ("Roaming Flank", "PS_INSIDE_PLAYER"),
    19: ("Cross Specialist", "PS_CROSSER"),
    20: ("Orchestrator", "PS_PLAYMAKER"),
    21: ("Full-back Finisher", "PS_INNERLAP_SB"),
    22: ("Target Man", "PS_TARGET_MAN"),
    23: ("Press Back", "PS_PRESS_BACK"),
    24: ("Front Line Pressure", "PS_FIRST_DEFENDER"),
    25: ("Front Line Poacher", "PS_COVER_SHADOW"),
    26: ("Attack Outlet", "PS_OUTLET_FORWARD"),
    27: ("All-action Defender", "PS_HARD_WORKER"),
    28: ("Pass Disruptor", "PS_LANE_BLOCKER"),
    29: ("Covering Role", "PS_COVERING"),
    30: ("High Line Master", "PS_LINE_CONTROLLER"),
    31: ("Tough Marker", "PS_HARD_MARKER"),
    32: ("Deep Defender", "PS_DEEP_LINE_DEFENDER"),
    33: ("Sweeper GK", "PS_SWEEPER_GK"),
    34: ("Build-up GK", "PS_BUILD_UP_GK"),
    35: ("High Line GK", "PS_ADVANCED_GK"),
}

# The 20 names valid in the PRIMARY (in-possession) field, plus "Basic" to clear it. Excludes
# 9/16/17 (secondary-only: The Destroyer, Attacking GK, Defensive GK — render as Basic if written
# to the primary field) and 23-35 (the thirteen v6.0.0 out-of-possession-only styles). Confirmed:
# scanning every Player.bin in build/, the primary field never carries any value above 22.
_SECONDARY_ONLY = {9, 16, 17} | set(range(23, 36))
PRIMARY: dict[str, int] = {"Basic": 0, **{
    name: idx for idx, (name, _key) in CATALOG.items()
    if idx != 0 and idx not in _SECONDARY_ONLY
}}

# The 16 names valid in the SECONDARY (out-of-possession) field: the destroyer/GK indices plus
# the 13 defensive/GK styles from v6.0.0. "Basic" (0) clears it.
SECONDARY: dict[str, int] = {"Basic": 0, "The Destroyer": 9, "Attacking GK": 16,
                             "Offensive GK": 16,   # UI alias of Attacking GK
                             "Defensive GK": 17,
                             **{name: idx for idx in range(23, 36) for name, _key in [CATALOG[idx]]}}
SECONDARY["Advanced GK"] = 35   # alias
SECONDARY["High Line GK"] = 35


def name_for(index: int) -> str | None:
    entry = CATALOG.get(index)
    return entry[0] if entry else None


if __name__ == "__main__":
    print(f"{len(CATALOG)} catalog entries, {len(PRIMARY)} primary names, "
          f"{len(SECONDARY)} secondary names (incl. aliases)")
    for idx in sorted(CATALOG):
        name, key = CATALOG[idx]
        slot = "primary" if name in PRIMARY else ("secondary" if idx in (9, 16, 17) or idx >= 23 else "-")
        print(f"  {idx:2d}  {name:22s} {key or '':22s} {slot}")
