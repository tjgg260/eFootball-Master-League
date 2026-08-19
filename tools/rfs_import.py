#!/usr/bin/env python3
"""
rfs_import.py — parse Rinaldo's RFS.DB (RFS_MAIN2.00) into structured records.

RFS.DB is a complete football world in one 24 MB file: 78,973 players, 3,989 teams, 439
competitions, plus countries/stadiums/managers/referees/formations/kits/calendars. Far better
sourced than FM (proprietary binary) — the format is a simple fixed-width table archive.

Container: magic 'RFS_MAIN2.00'; table count u32 @0x14; a 28-byte directory entry per table at
0x18 [name[16], dataOffset u32 @0x10, rows u32 @0x14, cols u32 @0x18]. Each table is `rows`
fixed-width records; the row width is the gap to the next table's data.

Player row (v2.00, ~207 B, verified against current stars):
  id            u32   @0
  firstname     char  @4   (24 B UTF-8, NUL-terminated)
  lastname      char  @28
  fullname      char  @76
  overall       u8    @196  (already eFootball's 40-99 scale — Bruno Fernandes = 96)
The other ~96 columns hold the FIFA attribute set (finishing, passing, pace, …), decoded next.

Ratings map to eFootball almost 1:1, which is why RFS beats FM for this — no 1-20→40-99 rescale.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"RFS_MAIN2.00"


@dataclass
class Table:
    offset: int
    rows: int
    cols: int
    width: int


class RfsDb:
    def __init__(self, path: Path):
        self.b = path.read_bytes()
        if self.b[:12] != MAGIC:
            raise ValueError(f"not RFS_MAIN2.00: {self.b[:12]!r}")
        self.tables = self._directory()

    def _directory(self) -> dict[str, Table]:
        count = struct.unpack_from("<I", self.b, 0x14)[0]
        raw = {}
        for i in range(count):
            o = 0x18 + i * 28
            name = self.b[o:o + 16].split(b"\0")[0].decode("ascii", "replace")
            offset = struct.unpack_from("<I", self.b, o + 16)[0]
            rows = struct.unpack_from("<I", self.b, o + 20)[0]
            cols = struct.unpack_from("<I", self.b, o + 24)[0]
            raw[name] = (offset, rows, cols)
        starts = sorted(off for off, rows, _ in raw.values() if rows > 0)
        tables = {}
        for name, (offset, rows, cols) in raw.items():
            if rows <= 0:
                continue
            nxt = min([s for s in starts if s > offset], default=len(self.b))
            tables[name] = Table(offset, rows, cols, (nxt - offset) // rows)
        return tables

    def record(self, table: str, i: int) -> bytes:
        t = self.tables[table]
        base = t.offset + i * t.width
        return self.b[base:base + t.width]

    @staticmethod
    def _str(rec: bytes, off: int, length: int = 24) -> str:
        return rec[off:off + length].split(b"\0")[0].decode("utf-8", "replace")

    def players(self):
        t = self.tables["players"]
        for i in range(t.rows):
            r = self.record("players", i)
            pid = struct.unpack_from("<I", r, 0)[0]
            first = self._str(r, 4)
            last = self._str(r, 28)
            full = self._str(r, 76) or f"{first} {last}".strip()
            overall = r[196]
            yield {"id": pid, "first": first, "last": last, "name": full, "overall": overall}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
    db = RfsDb(path)
    print(f"RFS.DB: {len(db.tables)} populated tables")
    for name in ("players", "teams", "competitions", "countries", "teamplayerlinks"):
        if name in db.tables:
            t = db.tables[name]
            print(f"  {name:<18} {t.rows:>8,} rows x {t.cols} cols ({t.width} B/row)")
    print("\ntop 10 players by overall:")
    top = sorted(db.players(), key=lambda p: -p["overall"])[:10]
    for p in top:
        print(f"  {p['overall']:>3}  {p['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
