"""Import Konami's rivalry data (Derby.bin) into master.db `team_rivals`.

Format (cracked 2026-08-20, round-trip verified): WESYS container, plain payload of
12-byte records `(team_id u32, group u32, row_id u16, intensity u16)`. Records sharing
`group` form one rivalry set; the first member is the anchor, the rest are its rivals.
Intensity: 0/4 anchor marker, 1 fierce, 5 moderate, 6 mild.

Usage: python tools/derby_import.py
"""
from __future__ import annotations

import sqlite3
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from vendor.sider.wesys import unpack_wesys_payload  # noqa: E402

DERBY = ROOT / "build/tree_base/common/etc/pesdb/Derby.bin"
DB = ROOT / "build/master.db"


def main() -> None:
    payload = unpack_wesys_payload(DERBY.read_bytes())
    assert len(payload) % 12 == 0, f"payload {len(payload)} not 12-aligned"

    groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for i in range(len(payload) // 12):
        team, group, packed = struct.unpack_from("<III", payload, i * 12)
        groups[group].append((team, packed >> 16))

    pairs: set[tuple[int, int, int]] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        anchor = members[0][0]
        for team, intensity in members[1:]:
            if team == anchor:
                continue
            # Store both directions so lookups never care who anchored the group.
            pairs.add((anchor, team, intensity or 1))
            pairs.add((team, anchor, intensity or 1))

    db = sqlite3.connect(DB)
    db.execute(
        "CREATE TABLE IF NOT EXISTS team_rivals ("
        " team_id INTEGER NOT NULL, rival_id INTEGER NOT NULL,"
        " intensity INTEGER NOT NULL DEFAULT 5,"
        " PRIMARY KEY (team_id, rival_id))"
    )
    db.execute("DELETE FROM team_rivals")
    db.executemany(
        "INSERT OR REPLACE INTO team_rivals(team_id, rival_id, intensity) VALUES (?,?,?)",
        sorted(pairs),
    )
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM team_rivals").fetchone()[0]
    print(f"team_rivals: {n} directed pairs from {len(groups)} groups")


if __name__ == "__main__":
    main()
