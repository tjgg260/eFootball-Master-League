#!/usr/bin/env python3
"""
ml_tactics.py — edit a team's formation shapes for genuinely fluid formations.

Every team has two formation_ids in Tactics.bin: phase 0 (in-possession) and phase 1
(out-of-possession). 889 of 890 teams point both at the SAME shape, so nothing morphs. This
tool rewrites the 11 slots of a formation_id in TacticsFormation.bin, so a team can defend in
one shape and attack in another.

Record layout (verified): TacticsFormation.bin is 12-byte records, no header —
  role u32 @0 (0 GK..12 CF) | formation_id u32 @4 | Y u8 @8 (depth 3-43) | X u8 @9 (width 12-92,
  centre 52) | slot u8 @10 (0-10). A formation_id owns exactly 11 records; they belong to one
  team-phase only, so editing them affects just that team.

Usage:
    python tools/ml_tactics.py show --team 1219
    python tools/ml_tactics.py set-shape --formation 16383 --preset attack
    python tools/ml_tactics.py set-shape --formation 16384 --preset defend
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402

TF = REPO / "bins" / "common" / "etc" / "pesdb" / "TacticsFormation.bin"
TAC = REPO / "bins" / "common" / "etc" / "pesdb" / "Tactics.bin"
POS = {0: "GK", 1: "CB", 2: "LB", 3: "RB", 4: "DMF", 5: "CMF", 6: "LMF", 7: "RMF",
       8: "AMF", 9: "LWF", 10: "RWF", 11: "SS", 12: "CF"}

# (role, x, y) per slot 0..10. x width 12-92 centre 52, y depth from own goal 3-43.
PRESETS = {
    # compact low block: deep flat back four, banked midfield four, two strikers dropped to
    # halfway. Everyone sits — the out-of-possession shape.
    "defend": [
        (0, 52, 3),                                        # GK
        (2, 18, 9), (1, 40, 8), (1, 64, 8), (3, 86, 9),    # LB CB CB RB (deep)
        (6, 20, 18), (5, 44, 17), (5, 60, 17), (7, 80, 18),# LMF CMF CMF RMF (banked)
        (12, 44, 27), (12, 60, 27),                        # CF CF (dropped)
    ],
    # attacking overload: back three, double pivot, front five with wingers high and wide.
    # The in-possession shape — a clear morph from the block above.
    "attack": [
        (0, 52, 3),                                        # GK
        (1, 34, 12), (1, 52, 13), (1, 70, 12),             # CB CB CB
        (4, 42, 23), (4, 62, 23),                          # DMF DMF pivot
        (9, 15, 39), (8, 38, 37), (12, 52, 43), (8, 66, 37), (10, 89, 39),  # LWF AMF CF AMF RWF
    ],
}


def load(path):
    blob = path.read_bytes()
    return blob, bytearray(wesys.unpack_wesys_payload(blob)), blob[1] & 0x0F


def team_formations(team_id):
    _, tac, _ = load(TAC)
    out = []
    for i in range(len(tac) // 12):
        if struct.unpack_from("<I", tac, i * 12)[0] == team_id:
            out.append((tac[i * 12 + 9], struct.unpack_from("<I", tac, i * 12 + 4)[0]))  # (phase, fid)
    return out


def show_formation(payload, fid):
    for i in range(len(payload) // 12):
        if struct.unpack_from("<I", payload, i * 12 + 4)[0] == fid:
            role = struct.unpack_from("<I", payload, i * 12)[0]
            y, x, s = payload[i * 12 + 8], payload[i * 12 + 9], payload[i * 12 + 10]
            print(f"  slot {s:>2} {POS.get(role, '?'):>4}  x={x:>3} y={y:>3}")


def set_shape(payload, fid, preset):
    shape = PRESETS[preset]
    for i in range(len(payload) // 12):
        if struct.unpack_from("<I", payload, i * 12 + 4)[0] == fid:
            slot = payload[i * 12 + 10]
            role, x, y = shape[slot]
            struct.pack_into("<I", payload, i * 12, role)
            payload[i * 12 + 8] = y
            payload[i * 12 + 9] = x


def save(path, payload, nibble):
    packed = wesys.pack_wesys_container(bytes(payload), key_nibble=nibble, compression_level=1)
    assert wesys.unpack_wesys_payload(packed) == bytes(payload)
    path.write_bytes(packed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("--team", type=int, required=True)
    e = sub.add_parser("set-shape")
    e.add_argument("--formation", type=int, required=True)
    e.add_argument("--preset", choices=list(PRESETS), required=True)
    args = ap.parse_args()

    if args.cmd == "show":
        _, tf, _ = load(TF)
        for phase, fid in sorted(team_formations(args.team)):
            print(f"phase {phase} ({'in-possession' if phase == 0 else 'out-of-possession'}), formation {fid}:")
            show_formation(tf, fid)
            print()
        return 0

    blob, tf, nib = load(TF)
    set_shape(tf, args.formation, args.preset)
    save(TF, tf, nib)
    print(f"formation {args.formation} set to '{args.preset}' preset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
