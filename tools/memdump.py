"""Targeted read-only dump of a live-memory region as int32/float32 rows (instant, one RPM).

Usage: python tools/memdump.py <hexaddr> <length_bytes> [--cols i32,f32]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem_scan import find_pid, _open, _read, k32


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    addr = int(sys.argv[1], 16)
    length = int(sys.argv[2])
    pid = find_pid() or sys.exit("eFootball not running.")
    h = _open(pid)
    data = _read(h, addr, length)
    k32.CloseHandle(h)
    n = len(data) - (len(data) % 4)
    fi = np.frombuffer(data[:n], dtype="<i4")
    ff = np.frombuffer(data[:n], dtype="<f4")
    for i in range(len(fi)):
        fv = float(ff[i])
        fs = f"{fv:9.2f}" if -1e7 < fv < 1e7 and not np.isnan(fv) else "        ."
        rate = "  <== RATING" if (3.0 <= fv <= 9.5 and round(fv * 2) == fv * 2) else ""
        print(f"  0x{addr + i*4:x}  +{i*4:>4}  i32={int(fi[i]):>12}  f32={fs}{rate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
