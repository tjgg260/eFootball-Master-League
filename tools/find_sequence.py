"""Find an ordered int32 sequence in live memory, anchored on its rarest element (fast).

Used to locate a per-player struct by a displayed key sequence (e.g. shirt numbers). Anchors on
the rarest value so the candidate set is tiny, then verifies the full ordered sequence at each
stride. A hit gives the array base + stride (struct size).

Usage:
  python tools/find_sequence.py 13,23,5,21,22,8,29,81,25,15,20 --anchor 81
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid, _open, _regions, _read, k32

STRIDES = list(range(1, 257))     # elements ×4 bytes → structs up to 1KB


def main():
    seq = [int(x) for x in sys.argv[1].split(",")]
    anchor = int(sys.argv[sys.argv.index("--anchor") + 1]) if "--anchor" in sys.argv else \
        max(seq, key=seq.count and (lambda v: -seq.count(v)))
    ai = seq.index(anchor)          # anchor's position in the sequence
    pat = np.array(seq, dtype=np.int64)
    L = len(pat)
    pid = find_pid() or sys.exit("eFootball not running.")
    hits = []
    h = _open(pid)
    try:
        for base, size in _regions(h):
            data = _read(h, base, size)
            n = len(data) - (len(data) % 4)
            if n < 4 * L:
                continue
            a = np.frombuffer(data[:n], dtype="<i4").astype(np.int64)
            anchors = np.nonzero(a == anchor)[0]
            if len(anchors) == 0:
                continue
            for i in anchors:
                for s in STRIDES:
                    start = i - s * ai
                    if start < 0 or start + s * (L - 1) >= len(a):
                        continue
                    if np.array_equal(a[start:start + s * L:s], pat):
                        hits.append((base + start * 4, s * 4))
    finally:
        k32.CloseHandle(h)

    if not hits:
        print(f"No match for {seq} (anchor {anchor}). Try the other team, or a different key.")
        return 1
    print(f"{len(hits)} match(es):")
    for addr, stride_b in hits[:20]:
        print(f"  base 0x{addr:x}  stride {stride_b}B")
    print(f"\nDump one struct:  python tools/memdump.py 0x{hits[0][0]:x} {hits[0][1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
