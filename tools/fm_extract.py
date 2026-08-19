#!/usr/bin/env python3
"""
fm_extract.py — decompress a Football Manager .dat database file.

FM26 stores its database as zstd-compressed .dat files behind a 12-byte FM header:
  bytes 0-1   : format/version marker (03 01)
  bytes 2-5   : ".dat" marker, byte-reversed ("tad.")
  bytes 6-11  : sizes
  bytes 12+   : a zstd frame (magic 28 b5 2f fd)

`people_db.dat` (~76 MB compressed) decompresses to ~451 MB and holds the 100k+ players and
staff with their attributes. This tool gets the raw bytes; parsing the FM record format is the
next phase (tools/fm_parse.py).

Usage:
    python tools/fm_extract.py "<path to people_db.dat>" out.raw
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

try:
    import zstandard as zstd
except ImportError:
    sys.exit("pip install zstandard")

ZSTD_MAGIC = bytes.fromhex("28b52ffd")


def decompress(path: Path) -> bytes:
    blob = path.read_bytes()
    off = blob.find(ZSTD_MAGIC)
    if off < 0:
        raise ValueError(f"no zstd frame in {path}")
    dctx = zstd.ZstdDecompressor()
    try:
        return dctx.decompress(blob[off:], max_output_size=1_000_000_000)
    except zstd.ZstdError:
        # frame without a declared content size — stream it
        return dctx.stream_reader(io.BytesIO(blob[off:])).read()


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    raw = decompress(src)
    dst.write_bytes(raw)
    print(f"{src.name}: {src.stat().st_size:,} -> {len(raw):,} bytes -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
