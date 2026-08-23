#!/usr/bin/env python3
"""
skill_bits.py — read/write a player's 52 skill flags in a 400-byte Player.bin record.

Each eFootball player skill is a single bit in the record. The skill -> bit map was located by a
purity scan against the game's own export (samples/editor-bundled-players.csv, player_skills
column): for each skill, the bit whose value equals "has this skill" across 23,555 players, every
one at >0.999 accuracy. The map lives in build/skill_bits.json (regenerate with tools/locate, see
git history). Bits are little-endian within the record (bit b = byte b//8, bit b%8).

This lets authored/harvested players carry their REAL skills into the game instead of inheriting a
cloned donor's — closing the skills half of the writeback gap (playstyles are the other half).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_MAP_PATH = REPO / "build" / "skill_bits.json"
_SKILL_BIT: dict[str, int] | None = None


def skill_bits() -> dict[str, int]:
    """skill name -> bit offset within the 400-byte record."""
    global _SKILL_BIT
    if _SKILL_BIT is None:
        _SKILL_BIT = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    return _SKILL_BIT


def _get(rec, b: int) -> int:
    return (rec[b >> 3] >> (b & 7)) & 1


def _set(rec, b: int, on: bool) -> None:
    if on:
        rec[b >> 3] |= 1 << (b & 7)
    else:
        rec[b >> 3] &= ~(1 << (b & 7))


def read_skills(rec: bytes) -> set[str]:
    """The set of skills whose bit is set in this record."""
    return {name for name, b in skill_bits().items() if _get(rec, b)}


def write_skills(rec: bytearray, skills) -> int:
    """
    Set exactly `skills` (an iterable of skill names) on the record: every known skill bit is
    written — 1 for skills in the set, 0 for the rest — so the result is the player's real skill
    list, not a merge with the donor's. Unknown skill names are ignored. Returns the count written.
    """
    want = {s for s in skills if s in skill_bits()}
    for name, b in skill_bits().items():
        _set(rec, b, name in want)
    return len(want)


def _selftest() -> int:
    """Round-trip: set a skill set on a blank record and read it back."""
    m = skill_bits()
    sample = set(list(m)[:5])
    rec = bytearray(400)
    write_skills(rec, sample)
    got = read_skills(rec)
    ok = got == sample
    print(f"{len(m)} skills mapped; round-trip {'OK' if ok else 'FAILED'}: {sorted(sample)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
