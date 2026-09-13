#!/usr/bin/env python3
"""
dt870_faces.py — harvest player FACES from dt870 into master.db.

A face has two layers:
  1. PlayerAppearance.bin — a 64-byte parametric record per PID (hair id, face type, skin, features,
     build). This IS the face for generic/parametric players, and it is fully portable: we store the
     whole 64-byte record verbatim so the dt200 writeback can reproduce it byte-for-byte.
  2. Dedicated "scanned" face MODELS — separate 3D asset files for star players, keyed by PID, that
     live outside PlayerAppearance.bin. Importing the 64-byte record does NOT bring a scanned model;
     that asset must be located and carried separately. This tool REPORTS how many of our new players
     look like they rely on a scanned model vs. a parametric face, so we know the real face coverage.

Writes ONLY master.db (new table player_appearance_raw). Idempotent for the target set.
"""
from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk")
REC = 64

sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402
sys.path.insert(0, str(REPO / "tools"))
from dt870_harvest import target_set, player_pids  # noqa: E402


def appearance_records(cpk: Path) -> dict[int, bytes]:
    """pid -> 64-byte PlayerAppearance record."""
    import cpk_patch
    blob = cpk_patch.read(cpk_patch.load(cpk), "common/etc/appearance/PlayerAppearance.bin")
    if blob is None:
        raise SystemExit(f"PlayerAppearance.bin not in {cpk.name}")
    payload = wesys.unpack_wesys_payload(blob)
    out = {}
    for i in range(len(payload) // REC):
        base = i * REC
        pid = struct.unpack_from("<I", payload, base)[0]
        out[pid] = payload[base:base + REC]
    return out


def harvest(apply: bool) -> int:
    real, _ = target_set()
    s200 = player_pids(GAME / "dt200_console_all.cpk")
    new_real = sorted(p for p in real if p not in s200)     # players we must ADD to dt200

    ap870 = appearance_records(GAME / "dt870_console_win.cpk")
    ap200 = appearance_records(GAME / "dt200_console_all.cpk")

    have_face = [p for p in new_real if p in ap870]
    no_face = [p for p in new_real if p not in ap870]
    print(f"New real players to add to dt200:      {len(new_real)}")
    print(f"  have a dt870 appearance record:      {len(have_face)}")
    print(f"  NO appearance record (default face): {len(no_face)}")

    # Heuristic for "scanned model" reliance: the record carries a face-id/face-type field. If a
    # player's record is byte-identical to a large shared 'generic' cluster, he's parametric; a
    # unique record usually means a bespoke/scanned face whose MODEL lives outside this file.
    # Signature must EXCLUDE the PID (bytes 0-3) — it is unique per player by construction.
    from collections import Counter
    sig = Counter(bytes(ap870[p][4:]) for p in have_face)
    unique_face = sum(1 for p in have_face if sig[bytes(ap870[p][4:])] == 1)
    print(f"  individualized face params (unique ex-PID): {unique_face}")
    print(f"  shared/generic parametric record:           {len(have_face) - unique_face}")

    if not apply:
        print("\n(dry run — pass --apply to write master.db)")
        return 0

    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS player_appearance_raw "
                "(player_id INTEGER PRIMARY KEY, record BLOB, source TEXT)")
    # store for the WHOLE real set (prefer dt870's fresher record, fall back to dt200's own)
    rows = []
    for p in sorted(real):
        rec = ap870.get(p) or ap200.get(p)
        if rec is not None:
            rows.append((p, rec, "dt870" if p in ap870 else "dt200"))
    con.executemany("INSERT OR REPLACE INTO player_appearance_raw (player_id,record,source) "
                    "VALUES (?,?,?)", rows)
    con.commit()
    print(f"\nStored {len(rows)} appearance records "
          f"({sum(1 for r in rows if r[2]=='dt870')} from dt870).")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    raise SystemExit(harvest(ap.parse_args().apply))
