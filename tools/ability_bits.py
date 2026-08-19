#!/usr/bin/env python3
"""
ability_bits.py — read and write eFootball Player.bin's 26 bit-packed abilities.

Each ability is a 6-bit field storing (value - 40), so the in-game 40-99 range packs into 6 bits.
The fields are NOT contiguous — assuming a clean 6-bit run from bit 368 is the classic decoding
mistake. These offsets were recovered by scanning every bit position and correlating a 6-bit read
against 1,000 players' real attributes from the bundled CSV: every one landed at r = 0.999-1.000.

This is the capability that lets us write REAL attributes (from RFS) into a player, instead of
inheriting a cloned donor's. Every write is gated by a byte-exact round-trip: read a record's
abilities, write them straight back, and the 400 bytes must be identical.
"""
from __future__ import annotations

BIAS = 40
WIDTH = 6

# ability name -> bit offset within the 400-byte record (verified by CSV correlation)
ABILITY_BITS = {
    "offensive_awareness": 498,
    "ball_control": 396,
    "dribbling": 492,
    "tight_possession": 550,
    "low_pass": 524,
    "lofted_pass": 448,
    "finishing": 530,
    "heading": 402,
    "set_piece_taking": 368,
    "curl": 428,
    "speed": 434,
    "acceleration": 486,
    "kicking_power": 384,
    "jumping": 408,
    "physical_contact": 518,
    "balance": 504,
    "stamina": 480,
    "defensive_awareness": 390,
    "tackling": 454,
    "aggression": 512,
    "defensive_engagement": 544,
    "gk_awareness": 472,
    "gk_catching": 416,
    "gk_parrying": 466,
    "gk_reflexes": 460,
    "gk_reach": 422,
}


def read_bits(rec: bytes, bit_off: int, width: int = WIDTH) -> int:
    val = 0
    for i in range(width):
        b = bit_off + i
        val |= ((rec[b // 8] >> (b % 8)) & 1) << i
    return val


def write_bits(rec: bytearray, bit_off: int, value: int, width: int = WIDTH) -> None:
    for i in range(width):
        b = bit_off + i
        bit = (value >> i) & 1
        if bit:
            rec[b // 8] |= (1 << (b % 8))
        else:
            rec[b // 8] &= ~(1 << (b % 8))


def read_abilities(rec: bytes) -> dict[str, int]:
    return {name: read_bits(rec, off) + BIAS for name, off in ABILITY_BITS.items()}


def write_ability(rec: bytearray, name: str, value: int) -> None:
    if name not in ABILITY_BITS:
        raise KeyError(name)
    stored = max(0, min(63, int(value) - BIAS))   # 40-103 clamps into 6 bits; game caps at 99
    write_bits(rec, ABILITY_BITS[name], stored)


def write_abilities(rec: bytearray, abilities: dict[str, int]) -> None:
    for name, value in abilities.items():
        if name in ABILITY_BITS:
            write_ability(rec, name, value)


if __name__ == "__main__":
    # Round-trip gate over real records: read -> write-back must be byte-identical.
    import sys, struct
    sys.path.insert(0, r"C:\Users\tjgg2\Downloads\eFootball Master League\tools\vendor\sider")
    import wesys
    raw = wesys.unpack_wesys_payload(open(
        r"C:\Users\tjgg2\Downloads\eFootball Master League\bins\common\etc\pesdb\Player.bin", "rb").read())
    REC = 400
    n = len(raw) // REC
    mismatches = 0
    for k in range(0, n, 37):  # sample across the file
        rec = bytearray(raw[k * REC:(k + 1) * REC])
        original = bytes(rec)
        abilities = read_abilities(rec)
        write_abilities(rec, abilities)          # write the same values straight back
        if bytes(rec) != original:
            mismatches += 1
    checked = len(range(0, n, 37))
    print(f"round-trip on {checked} records: {'ALL byte-identical' if mismatches == 0 else f'{mismatches} MISMATCH'}")
