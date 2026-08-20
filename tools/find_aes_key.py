"""Static AES-256 key-schedule scanner (aeskeyfind algorithm) for the IoStore global key.

UE5 IoStore containers here are Encrypted with a zero key-GUID -> one global AES-256 key.
This looks for that key sitting in a file as an *expanded* schedule (240 bytes, 60 u32 words),
using the AES-256 expansion invariant that for word index i in [8,60) with i%8 not in {0,4}:

    W[i] == W[i-8] XOR W[i-1]

~44 of the 60 words satisfy that pure-XOR relation, so real schedules light up as long runs of
zeros in  A[i] = W[i] ^ W[i-8] ^ W[i-1]  — cheap to vectorise over a whole file with numpy.
Candidates are then fully verified (SubWord/RotWord/Rcon) and the raw 32-byte key printed.

Usage: python tools/find_aes_key.py <file> [<file> ...]
"""
from __future__ import annotations

import sys
import numpy as np

SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
RCON = [0x01000000, 0x02000000, 0x04000000, 0x08000000, 0x10000000,
        0x20000000, 0x40000000, 0x80000000, 0x1b000000, 0x36000000]


def _rotword(w: int) -> int:
    return ((w << 8) | (w >> 24)) & 0xFFFFFFFF


def _subword(w: int) -> int:
    return (SBOX[(w >> 24) & 0xFF] << 24 | SBOX[(w >> 16) & 0xFF] << 16 |
            SBOX[(w >> 8) & 0xFF] << 8 | SBOX[w & 0xFF])


def _verify(words: list[int]) -> bool:
    """Full AES-256 expansion check on 60 big-endian-word schedule candidate."""
    for i in range(8, 60):
        t = words[i - 1]
        if i % 8 == 0:
            t = _subword(_rotword(t)) ^ RCON[i // 8 - 1]
        elif i % 8 == 4:
            t = _subword(t)
        if words[i] != (words[i - 8] ^ t) & 0xFFFFFFFF:
            return False
    return True


def scan(path: str) -> list[tuple[int, bytes]]:
    data = np.fromfile(path, dtype=np.uint8)
    n = len(data) - (len(data) % 4)
    # words as big-endian u32 (AES treats key bytes MSB-first)
    w = data[:n].view(np.dtype(">u4"))
    if len(w) < 60:
        return []
    # A[i] = W[i] ^ W[i-8] ^ W[i-1], valid for i>=8
    a = w[8:] ^ w[:-8] ^ w[7:-1]
    # positions (relative to schedule start) that MUST be zero: i in [8,60), i%8 not in {0,4}
    must = [i for i in range(8, 60) if i % 8 not in (0, 4)]
    zero = (a == 0)                       # index j here corresponds to word i=j+8
    hits = []
    # candidate schedule starts at word s if for every i in must: zero[(s+i)-8] is True
    limit = len(w) - 60
    # cheap prefilter: require the first must-position (i=9 -> zero index 1) etc. Vectorise the
    # full AND across all must offsets.
    cond = np.ones(limit + 1, dtype=bool)
    for i in must:
        idx = i - 8
        cond &= zero[idx: idx + limit + 1]
    for s in np.nonzero(cond)[0]:
        words = [int(x) for x in w[s: s + 60]]
        if _verify(words):
            # raw AES-256 key = first 8 words = 32 bytes, big-endian
            key = b"".join(int(x).to_bytes(4, "big") for x in words[:8])
            hits.append((int(s) * 4, key))
    return hits


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    found = False
    for path in sys.argv[1:]:
        try:
            hits = scan(path)
        except Exception as ex:
            print(f"{path}: ERROR {ex}")
            continue
        if hits:
            found = True
            for off, key in hits:
                print(f"{path} @0x{off:x}: AES-256 key = {key.hex()}")
        else:
            print(f"{path}: no AES-256 schedule found")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
