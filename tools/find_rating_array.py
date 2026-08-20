"""Locate eFootball's per-player rating array — FAST, anchored on the unique 7.5.

7.5 is Cucuta's last-listed player, so instead of scanning all memory for sequences we only look
BACKWARDS from each known 7.5 address for the 10 preceding Cucuta ratings at some regular stride.
That's a few thousand tiny checks. A hit gives the array base + stride (per-player struct size).

Read-only. eFootball paused on the full-time ratings screen.
Usage: python tools/find_rating_array.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid, _open, _regions, _read, k32

# Cucuta on-screen order (top→bottom); 7.5 is the last element and is unique.
CUCUTA = [5.0, 6.0, 6.0, 6.5, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 7.5]
STRIDES = list(range(1, 129))     # float elements (×4 bytes)


def codes(f):
    c = np.full(len(f), -1, np.int32)
    valid = (f >= 3.0) & (f <= 9.5)
    sub = f[valid]
    r = np.rint(sub * 2)
    half = np.abs(sub * 2 - r) < 1e-3
    idx = np.nonzero(valid)[0][half]
    c[idx] = r[half].astype(np.int32)
    return c


def main():
    pid = find_pid() or sys.exit("eFootball not running.")
    pat = np.array([int(round(v * 2)) for v in CUCUTA])   # length 11, pat[-1]=15 (7.5)
    L = len(pat)
    hits = []
    h = _open(pid)
    try:
        for base, size in _regions(h):
            data = _read(h, base, size)
            n = len(data) - (len(data) % 4)
            if n < 44:
                continue
            c = codes(np.frombuffer(data[:n], dtype="<f4"))
            sevens = np.nonzero(c == 15)[0]
            if len(sevens) == 0:
                continue
            for i in sevens:
                for s in STRIDES:
                    lo = i - s * (L - 1)
                    if lo < 0:
                        break
                    if np.array_equal(c[lo:i + 1:s], pat):
                        hits.append((base + lo * 4, s * 4))
    finally:
        k32.CloseHandle(h)

    if not hits:
        print("No Cucuta sequence found (array reversed / non-screen order / scaled ints). "
              "Fallback: scaled-int scan.")
        return 1
    print(f"{len(hits)} rating-array match(es) (base = Cucuta player[0]):\n")
    for addr, stride_b in hits[:20]:
        print(f"  base 0x{addr:x}  stride {stride_b}B  "
              f"({'contiguous floats' if stride_b == 4 else 'per-player struct'})")
    addr, stride_b = hits[0]
    print(f"\n--- struct dump around Cucuta player[0] @0x{addr:x}, one stride ({stride_b}B) ---")
    _dump(pid, addr - 32, stride_b + 64)
    print("\nSave these: rating field at struct offset 0, stride =", stride_b, "bytes.")
    return 0


def _dump(pid, start, length):
    start, length = int(start), int(length)
    h = _open(pid)
    data = _read(h, start, length)
    k32.CloseHandle(h)
    n = len(data) - (len(data) % 4)
    fi = np.frombuffer(data[:n], dtype="<i4")
    ff = np.frombuffer(data[:n], dtype="<f4")
    for i in range(len(fi)):
        fv = float(ff[i])
        fs = f"{fv:8.2f}" if -1e6 < fv < 1e6 and not np.isnan(fv) else "       ."
        print(f"  0x{start + i*4:x}  i32={int(fi[i]):>11}  f32={fs}")


if __name__ == "__main__":
    raise SystemExit(main())
