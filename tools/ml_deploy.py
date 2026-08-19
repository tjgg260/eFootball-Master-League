#!/usr/bin/env python3
"""
ml_deploy.py — CSV to installed CPK, in one command.

    python tools/ml_deploy.py --csv PlayerAssignment.csv --install

Pipeline:  CSV -> PlayerAssignment.bin payload -> WESYS encrypt -> inject into CPK -> install

Two hard-won rules are enforced here rather than trusted:

1. POSITIONAL FORMAT. A record's club is its physical position in the file, not its TeamID
   value. CSV row N must map to record N. That correspondence is proved by checking every
   row's RowNum against the record's own id before a single byte is written — if the CSV has
   been re-sorted (Excel loves doing this), the check fails loudly instead of silently
   scrambling every squad in the game.

2. NEVER REBUILD OR RE-SERIALISE THE CPK. Two failures proved this the hard way:
     - cpkmakec rebuilds at alignment 2048; the game silently ignores anything but 512.
     - cricodecs replace_bytes()+save() re-lays-out the whole archive. Even at the right
       alignment it shed 60 KB and the game black-screened on boot.
   So we do a PURE IN-PLACE BYTE PATCH: locate the file's exact bytes inside the CPK and
   overwrite only them, leaving every other byte identical. This works because the modified
   PlayerAssignment payload re-packs at zlib level 1 to the exact same length as the original
   (the record count is unchanged), so nothing downstream has to move. If a future edit ever
   changes the length, we refuse rather than relayout.
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
import struct
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))

import wesys  # noqa: E402
import pesdb  # noqa: E402

try:
    from cricodecs import cpk
except ImportError:
    sys.exit("cricodecs is required:  pip install cricodecs")

GAME_CPK = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk")
ARCHIVE_PATH = "common/etc/pesdb/PlayerAssignment.bin"
BACKUPS = Path.home() / "Backups" / "eFootball"
REC = 24
LAYOUTS = {"v1": {"pid": 8, "team": 16, "shirt": 20, "sort": 21},
           "v2": {"pid": 0, "team": 8, "shirt": 16, "sort": 17}}


def build_payload(csv_path: Path, base: bytes) -> bytes:
    """Apply the CSV onto the existing decrypted payload, record by record."""
    rows = list(csv.DictReader(io.StringIO(csv_path.read_bytes().decode("utf-8-sig"))))
    recs = pesdb.parse_player_assignment_bin(base)
    layout = "v2" if pesdb.detect_assignment_layout(base).endswith("/v2") else "v1"
    off = LAYOUTS[layout]

    if len(rows) != len(recs):
        sys.exit(f"CSV has {len(rows):,} rows but the bin has {len(recs):,} records")

    # Prove row N really is record N before writing anything.
    for i, (row, rec) in enumerate(zip(rows, recs)):
        if int(row["RowNum"]) != rec["record_id"]:
            sys.exit(f"CSV row {i+2} RowNum {row['RowNum']} != record id {rec['record_id']}.\n"
                     "The CSV has been re-ordered. Re-export it and do not sort in Excel.")

    out = bytearray(base)
    changed = 0
    for i, (row, rec) in enumerate(zip(rows, recs)):
        # TeamID is compared on its low 16 bits: the editor's CSV export truncates team ids to
        # u16, so 665 high-id (national/legacy) teams read e.g. 16416 for a real 81952. TeamID
        # is never written anyway, so the truncation is cosmetic — but a genuine attempt to
        # move a record between two normal clubs still trips this, because their low16 differ.
        # Slot is sort_key // 4: ten records carry non-zero low bits (flags) that we preserve
        # by never recomputing or writing sort_key.
        if (int(row["TeamID"]) & 0xFFFF) != (rec["team_id"] & 0xFFFF) \
                or int(row["Slot"]) != rec["sort_key"] // 4:
            sys.exit(
                f"CSV row {i+2} changes TeamID or Slot. This format is positional - a transfer "
                "must swap which player OCCUPIES a record, never move the record. Use ml_swap.py.")
        pid, shirt = int(row["PlayerID"]), int(row["SquadNumber"])
        if pid != rec["player_id"] or shirt != rec["shirt_number"]:
            struct.pack_into("<Q", out, i * REC + off["pid"], pid)
            out[i * REC + off["shirt"]] = shirt - 1
            changed += 1

    # Read it back and demand it matches the CSV exactly.
    for row, rec in zip(rows, pesdb.parse_player_assignment_bin(bytes(out))):
        assert int(row["PlayerID"]) == rec["player_id"], "readback mismatch on player id"
        assert int(row["SquadNumber"]) == rec["shirt_number"], "readback mismatch on shirt"

    print(f"  layout {layout}, {len(recs):,} records, {changed} changed")
    return bytes(out)


def validate(payload: bytes) -> None:
    recs = pesdb.parse_player_assignment_bin(payload)
    by = {}
    for i, r in enumerate(recs):
        by.setdefault(r["team_id"], []).append((i, r))
    bad = []
    for team, entries in by.items():
        slots = sorted(r["sort_key"] // 4 for _, r in entries)
        shirts = [r["shirt_number"] for _, r in entries]
        idx = [i for i, _ in entries]
        if slots != list(range(len(entries))):
            bad.append(f"team {team}: slots not 0..{len(entries)-1}")
        if len(set(shirts)) != len(shirts):
            bad.append(f"team {team}: duplicate shirt numbers")
        if idx != list(range(idx[0], idx[0] + len(idx))):
            bad.append(f"team {team}: records not physically contiguous")
    if bad:
        print("\nVALIDATION FAILED - nothing written:")
        for b in bad[:12]:
            print(f"  - {b}")
        sys.exit(1)
    print(f"  validated {len(by)} squads: slots contiguous, shirts unique, blocks intact")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="PlayerAssignment.csv")
    ap.add_argument("--base", default=str(REPO / "dt200_console_all.cpk"),
                    help="known-good CPK to inject into (never rebuilt from scratch)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--install", action="store_true", help="copy into the game's cpk folder")
    args = ap.parse_args()

    base_cpk = Path(args.base)
    if not base_cpk.exists():
        sys.exit(f"base CPK not found: {base_cpk}")
    out_cpk = Path(args.out) if args.out else REPO / "build" / base_cpk.name
    out_cpk.parent.mkdir(parents=True, exist_ok=True)

    print(f"base   {base_cpk.name} ({base_cpk.stat().st_size:,} bytes)")
    raw = bytearray(base_cpk.read_bytes())
    archive = cpk.load(base_cpk)
    idx = next(i for i, e in enumerate(archive.files) if e.full_path == ARCHIVE_PATH)

    blob = archive.file_bytes(idx)
    nibble = blob[1] & 0x0F
    slot = len(blob)

    # Find the file's exact bytes inside the CPK. The 24-byte WESYS+record prefix is unique.
    offset = raw.find(blob[:24])
    if offset < 0 or bytes(raw[offset:offset + slot]) != blob:
        sys.exit("could not locate PlayerAssignment.bin bytes in the CPK for in-place patch")

    payload = build_payload(Path(args.csv), wesys.unpack_wesys_payload(blob))
    validate(payload)

    packed = wesys.pack_wesys_container(payload, key_nibble=nibble, compression_level=1)
    if wesys.unpack_wesys_payload(packed) != payload:
        sys.exit("WESYS round-trip failed - nothing written")
    if len(packed) != slot:
        sys.exit(f"re-packed blob is {len(packed):,} bytes, slot is {slot:,}. In-place patch needs "
                 "an exact fit; a length change would require a relayout, which the game rejects.")

    # Pure in-place overwrite. Every other byte of the CPK is untouched.
    original = bytes(raw)
    raw[offset:offset + slot] = packed
    out_cpk.write_bytes(bytes(raw))

    delta = sum(1 for o, n in zip(original[offset:offset + slot], packed) if o != n)
    rebuilt = cpk.load(out_cpk)
    if rebuilt.alignment != archive.alignment or out_cpk.stat().st_size != base_cpk.stat().st_size:
        sys.exit("structural drift from base; refusing to install")
    print(f"built  {out_cpk} ({out_cpk.stat().st_size:,} bytes, {delta} bytes changed vs base, "
          f"align={rebuilt.alignment}, tver={rebuilt.tver!r})")

    if not args.install:
        print("not installed (pass --install)")
        return 0

    target = GAME_CPK / base_cpk.name
    BACKUPS.mkdir(parents=True, exist_ok=True)
    if target.exists():
        keep = BACKUPS / f"{target.stem}.{datetime.now():%Y%m%d-%H%M%S}.cpk"
        shutil.copy2(target, keep)
        print(f"  backup {keep.name}")
    try:
        shutil.copy2(out_cpk, target)
    except PermissionError:
        sys.exit(f"\n{target.name} is locked. Close eFootball and run again.")
    print(f"INSTALLED {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
