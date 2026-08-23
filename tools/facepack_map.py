#!/usr/bin/env python3
"""
facepack_map.py — figure out how the SortitoutSI cutout facepack (face_<FM-UID>.png) maps onto our
players, then (with --apply) populate players.real_face_path so the portrait resolver uses the real
cutouts. The pack is keyed by FM player UID; RFS.DB is FM-derived, so RFS ids likely == FM UIDs.

Run tools/facepack_map.py after build/facepack_ids.txt exists (produced by 7z listing).
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
IDS = REPO / "build" / "facepack_ids.txt"
RFS_PLAYER_BASE = 700_000_000
# where the extracted faces will live (set to the real extract dir when we extract)
FACE_DIR_DEFAULT = r"C:\Users\tjgg2\Downloads\eFootball Master League\facepack\sortitoutsi\faces"


def load_face_ids() -> set[int]:
    ids = set()
    for line in IDS.read_text(encoding="ascii", errors="ignore").splitlines():
        line = line.strip()
        if line.isdigit():
            ids.add(int(line))
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write real_face_path for matched players")
    ap.add_argument("--face-dir", default=FACE_DIR_DEFAULT, help="dir holding face_<id>.png")
    args = ap.parse_args()

    faces = load_face_ids()
    print(f"facepack face ids: {len(faces):,}  (range {min(faces)}..{max(faces)})")
    con = sqlite3.connect(DB)

    # candidate 1: RFS players by original rfs_id (id - 700,000,000)
    rfs = {r[0] - RFS_PLAYER_BASE: r[0] for r in
           con.execute("SELECT id FROM players WHERE id >= ?", (RFS_PLAYER_BASE,))}
    rfs_hit = set(rfs) & faces
    # candidate 2: eFootball base players by raw external PID
    ef = {r[0]: r[0] for r in
          con.execute("SELECT id FROM players WHERE is_custom=0 AND id < ?", (RFS_PLAYER_BASE,))}
    ef_hit = set(ef) & faces

    print(f"\nRFS players (by original rfs_id): {len(rfs):,} total, "
          f"{len(rfs_hit):,} have a facepack image  ({100*len(rfs_hit)//max(len(rfs),1)}%)")
    print(f"eFootball base players (by PID):  {len(ef):,} total, "
          f"{len(ef_hit):,} have a facepack image  ({100*len(ef_hit)//max(len(ef),1)}%)")

    total_players = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    matched = len(rfs_hit) + len(ef_hit)
    print(f"\nTOTAL players with a real cutout: {matched:,} / {total_players:,}")

    if not args.apply:
        print("\n(dry run — pass --apply to write players.real_face_path)")
        con.close()
        return 0

    face_dir = Path(args.face_dir)
    rows = []
    for rfs_id, pid in rfs.items():
        if rfs_id in faces:
            rows.append((str(face_dir / f"face_{rfs_id}.png"), pid))
    for efid, pid in ef.items():
        if efid in faces:
            rows.append((str(face_dir / f"face_{efid}.png"), pid))
    con.executemany("UPDATE players SET real_face_path=? WHERE id=?", rows)
    con.commit()
    print(f"\nWrote real_face_path for {len(rows):,} players -> {face_dir}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
