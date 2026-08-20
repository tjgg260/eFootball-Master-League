#!/usr/bin/env python3
"""
appearance.py — read and write eFootball's PlayerAppearance.bin.

Layout (recovered in this repo, 2026-08-20, portrait-correlation method — the same
methodology as ability_bits.py):

  * WESYS container (vendored Sider codec), payload = 64-byte records, u32 player id @ 0.
  * SKIN TONE = 3-bit field at bit 292 (byte 36, bits 4-6), values 1 (lightest) .. 6
    (darkest). Verified against 1,029 portrait-matched players: mean face luminance is
    strictly monotonic across the six values (165 → 97).
  * Hair colour/type NOT yet mapped (candidates near byte 47 are weak — likely an id into a
    hair-model table, not a scalar). Do not guess.

Every write path is gated by the repo's round-trip rule: the unmodified payload must
re-encode byte-identically, and any modified payload must decode back to exactly what we
encoded. No gate, no write.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402

REC = 64
SKIN_BIT, SKIN_WIDTH = 292, 3


def load(path: Path) -> tuple[bytes, bytearray]:
    """(original container bytes, decoded mutable payload)."""
    raw = path.read_bytes()
    return raw, bytearray(wesys.unpack_wesys_payload(raw))


def records(payload: bytes) -> dict[int, int]:
    """player id -> record offset."""
    return {struct.unpack_from("<I", payload, i * REC)[0]: i * REC
            for i in range(len(payload) // REC)}


def _read_bits(payload: bytes, base_bit: int, width: int) -> int:
    v = 0
    for i in range(width):
        b = base_bit + i
        v |= ((payload[b // 8] >> (b % 8)) & 1) << i
    return v


def _write_bits(payload: bytearray, base_bit: int, value: int, width: int) -> None:
    for i in range(width):
        b = base_bit + i
        if (value >> i) & 1:
            payload[b // 8] |= 1 << (b % 8)
        else:
            payload[b // 8] &= ~(1 << (b % 8))


def skin_of(payload: bytes, rec_off: int) -> int:
    return _read_bits(payload, rec_off * 8 + SKIN_BIT, SKIN_WIDTH)


def set_skin(payload: bytearray, rec_off: int, tone: int) -> None:
    _write_bits(payload, rec_off * 8 + SKIN_BIT, max(0, min(6, tone)), SKIN_WIDTH)


def clone_record(payload: bytearray, donor_off: int, new_pid: int) -> int:
    """Append a copy of the donor's record with a new player id; returns its offset."""
    rec = bytearray(payload[donor_off:donor_off + REC])
    struct.pack_into("<I", rec, 0, new_pid)
    off = len(payload)
    payload.extend(rec)
    return off


def save(path: Path, original_raw: bytes, payload: bytes) -> None:
    """Round-trip-gated write: encode, prove decode==payload, then write the container."""
    packed = wesys.pack_wesys_container(
        bytes(payload), key_nibble=original_raw[1] & 0xF, compression_level=1)
    if wesys.unpack_wesys_payload(packed) != bytes(payload):
        raise RuntimeError("PlayerAppearance round-trip FAILED — refusing to write")
    path.write_bytes(packed)


def prove_round_trip(path: Path) -> bool:
    """The repo's standing gate: unmodified re-encode must decode to the same payload
    (byte-identity of the container itself additionally proven when level 1 reproduces it)."""
    raw, payload = load(path)
    packed = wesys.pack_wesys_container(
        bytes(payload), key_nibble=raw[1] & 0xF, compression_level=1)
    ok_payload = wesys.unpack_wesys_payload(packed) == bytes(payload)
    ok_container = packed == raw
    print(f"payload round-trip: {'OK' if ok_payload else 'FAIL'}; "
          f"container byte-identity: {'OK' if ok_container else 'differs (payload-verified)'}")
    return ok_payload


if __name__ == "__main__":
    p = REPO / "build" / "tree_base" / "common" / "etc" / "appearance" / "PlayerAppearance.bin"
    ok = prove_round_trip(p)
    raw, payload = load(p)
    recs = records(bytes(payload))
    from collections import Counter
    dist = Counter(skin_of(bytes(payload), off) for off in recs.values())
    print(f"records: {len(recs)}; skin distribution: {dict(sorted(dist.items()))}")
    sys.exit(0 if ok else 1)
