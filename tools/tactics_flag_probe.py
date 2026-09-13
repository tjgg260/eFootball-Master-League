#!/usr/bin/env python3
"""
tactics_flag_probe.py — calibration experiment: set the two UNKNOWN bytes (10, 11) of a team's
Tactics.bin records to 1 and see what the game does with them. They are zero across every record
of both dt200 and dt870, so they're either padding or a dormant flag (fluid formation is the
prime suspect — the game's own data expresses fluidness only as divergent pair geometry).

Method: a one-file patch of an already-built match CPK (the ml_deploy discipline): read the
Tactics.bin WESYS blob, flip the bytes in the payload, re-pack (the exact original length when
some zlib level gives it), and patch it back with tools/cpk_patch.py. Every other byte of the
CPK is verified untouched.

    python tools/tactics_flag_probe.py --team 106                # build build/dt200_flagprobe.cpk
    python tools/tactics_flag_probe.py --team 106 --install      # + install into the game (backup taken)

Observe in-game: open the team's Game Plan / play an exhibition with them. If nothing changes,
the bytes are padding and the question is closed.
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys                        # noqa: E402
import cpk_patch                    # noqa: E402

ARCHIVE_PATH = "common/etc/pesdb/Tactics.bin"
GAME_CPK = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk\dt200_console_all.cpk")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(REPO / "build" / "dt200_verify.cpk"),
                    help="built match CPK to patch (default: the last verify build)")
    ap.add_argument("--out", default=str(REPO / "build" / "dt200_flagprobe.cpk"))
    ap.add_argument("--team", type=int, required=True, help="in-game team id (e.g. 106 Newcastle)")
    ap.add_argument("--b10", type=int, default=1)
    ap.add_argument("--b11", type=int, default=1)
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    base_cpk = Path(args.base)
    base = base_cpk.read_bytes()
    archive = cpk_patch.load(base_cpk)
    entry = cpk_patch.find(archive, ARCHIVE_PATH)
    if entry is None:
        sys.exit(f"{ARCHIVE_PATH} is not in {base_cpk.name}")
    blob = archive.read(entry.path)
    nibble = blob[1] & 0x0F
    slot = len(blob)

    payload = bytearray(wesys.unpack_wesys_payload(blob))
    hits = 0
    for i in range(len(payload) // 12):
        tid = struct.unpack_from("<I", payload, i * 12)[0]
        if tid == args.team:
            payload[i * 12 + 10] = args.b10 & 0xFF
            payload[i * 12 + 11] = args.b11 & 0xFF
            hits += 1
    if hits == 0:
        sys.exit(f"team {args.team} has no records in this build's Tactics.bin")
    print(f"flipped bytes 10={args.b10} 11={args.b11} on {hits} record(s) of team {args.team}")

    # Prefer a repack that lands in the original slot; any other length still patches cleanly.
    packed = None
    for level in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0):
        cand = wesys.pack_wesys_container(bytes(payload), key_nibble=nibble, compression_level=level)
        if wesys.unpack_wesys_payload(cand) != bytes(payload):
            continue
        if len(cand) == slot:
            packed = cand
            print(f"exact-length repack at zlib level {level} ({slot:,} bytes)")
            break
        packed = packed or cand
    if packed is None:
        sys.exit("no zlib level round-trips the edited payload - nothing written")

    try:
        out = cpk_patch.patch_bytes(base, {entry.path: packed})
    except cpk_patch.CpkPatchError as exc:
        sys.exit(f"CPK patch refused - nothing written: {exc}")
    Path(args.out).write_bytes(out)
    print(f"wrote {args.out} ({len(out):,} bytes; Tactics.bin {slot:,} -> {len(packed):,} bytes; "
          "every other file verified untouched)")

    if args.install:
        backup = GAME_CPK.with_suffix(f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(GAME_CPK, backup)
        shutil.copy2(args.out, GAME_CPK)
        print(f"installed into the game (backup: {backup.name}). Boot eFootball and inspect "
              f"team {args.team}'s Game Plan / play an exhibition with them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
