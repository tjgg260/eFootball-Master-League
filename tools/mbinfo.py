#!/usr/bin/env python3
"""
mbinfo.py — read the Fox animation metadata tables (`common/anime/Mbinfo/bin/*.bin`).

Both eFootball and PES 2014 drive physical contact from the same family of per-animation
tables: when a body part touches the ball (HitData), when two players are gripping each other
(HoldData), which frames an animation may be interrupted on (CancelData), and which body
posture it ends in so the get-up can continue from there (DemoConnectData).

Why this file can be trusted
    PES 2014 ships BOTH the binary tables and `Mbinfo/Json/anim_infos.json`, a 7.1 MB plain-text
    dump of the same data. That JSON is ground truth: every layout here was derived by decoding
    the PES 2014 binary and checking it against the JSON field by field, and `verify` re-runs
    that check. eFootball ships no JSON, so its tables are read with the layouts proven there.

    Proven against the JSON (exact float match on record 0, and on the geometry of every
    Animation.bin record checked):
      Animation.bin  PES 2014  28-byte records: u32 packed, u32, blend_z, blend_x,
                                                first_x, first_z, end_move_angle
      HoldData.bin   PES 2014  16-byte records: u32 packed, offset_z, offset_y, offset_x
      HoldData.bin   eFootball 20-byte records: u32 packed, u32 bone, offset_z, offset_y, offset_x
      CancelData.bin both      4-byte  records: frame = v >> 12, anim_index = (v & 0xFFF) + 5

The packed word in Animation.bin (fields carry a BIAS, which is why a naive bitfield search
misses them):
      anim_index  =  v & 0xFFF                 unique across all 2,671 records
      end_frame   = ((v >> 12) & 0x1FF) + 8    67/67 against the JSON, 2512/2512 after the join
      blend_start =  (v >> 21) + 6             65/67 — see "Not fully settled" below

Record -> animation name
    Animation.bin record order is NOT the JSON key order (it holds for the first 67 records
    only). Records are instead joined to animations by their geometry, which is effectively
    unique: 2,512 of 2,671 records join to exactly one animation, and `end_frame` decoded from
    the packed word then agrees with the joined animation on 2512/2512 — two independent
    derivations confirming each other.

    CancelData's index is the same space offset by five: `anim_index = (v & 0xFFF) + 5`.
    Verified at **1,636 animations agreeing, 0 disagreeing** (89 unresolved only because their
    Animation.bin record did not join by geometry).

Not fully settled (do not build a writer on this yet):
    - `blend_start` misses on 2 of 67, and its decoded range runs past `end_frame` on 263
      records, so the 11-bit width is probably bleeding into a neighbouring field.
    - The `bone` field in eFootball's HoldData is NOT the render-skeleton index: 378 records use
      only three values (11 x193, 7 x184, 0 x1). It is a separate, smaller enum, unidentified.
    - eFootball `Animation.bin` record size is unconfirmed, so no eFootball join exists yet and
      its indices cannot be resolved to names.
    Nothing here writes.

Container
    eFootball wraps each table in WESYS + zlib (`ff2081` + "WESYS" + u32 csize + u32 dsize +
    zlib stream). PES 2014 stores them raw. `unwrap()` handles both.

Usage
    python tools/mbinfo.py sizes   <dir> [<dir2>]     # table inventory, or A-vs-B comparison
    python tools/mbinfo.py hold    <dir> [--limit N]  # decode HoldData records
    python tools/mbinfo.py cancel  <dir> [--limit N]  # decode CancelData records
    python tools/mbinfo.py verify  <pes2014_mbinfo_dir>   # re-prove layouts against anim_infos.json

    <dir> is a `.../common/anime/Mbinfo` directory (it reads `bin/` beneath it, and `Json/`
    for verify).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

WESYS = b"WESYS"


def unwrap(blob: bytes) -> bytes:
    """Return the table payload, decompressing a WESYS+zlib wrapper if present."""
    i = blob.find(WESYS)
    if i < 0:
        return blob                      # PES 2014 stores these raw
    csize, dsize = struct.unpack_from("<II", blob, i + 5)
    out = zlib.decompress(blob[i + 13:])
    if len(out) != dsize:
        raise ValueError(f"WESYS size mismatch: header says {dsize}, got {len(out)}")
    return out


def load(mbinfo_dir: Path, name: str) -> bytes:
    return unwrap((mbinfo_dir / "bin" / name).read_bytes())


def tables(mbinfo_dir: Path) -> dict[str, int]:
    out = {}
    for p in sorted((mbinfo_dir / "bin").glob("*.bin")):
        try:
            out[p.name] = len(unwrap(p.read_bytes()))
        except Exception as exc:                      # a table we cannot open is worth seeing
            out[p.name] = -1
            print(f"  ! {p.name}: {exc}", file=sys.stderr)
    return out


def hold_records(data: bytes):
    """Yield HoldData records. 20-byte (eFootball, explicit bone) or 16-byte (PES 2014)."""
    rec = 20 if len(data) % 20 == 0 and len(data) % 16 else 16
    if len(data) % rec:
        raise ValueError(f"HoldData size {len(data)} is not a multiple of {rec}")
    for o in range(0, len(data), rec):
        packed = struct.unpack_from("<I", data, o)[0]
        if rec == 20:
            bone = struct.unpack_from("<I", data, o + 4)[0]
            z, y, x = struct.unpack_from("<fff", data, o + 8)
        else:
            bone = None
            z, y, x = struct.unpack_from("<fff", data, o + 4)
        yield {"packed": packed, "bone": bone,
               "offset_x": round(x, 5), "offset_y": round(y, 5), "offset_z": round(z, 5)}


CANCEL_INDEX_BIAS = 5      # proven: 1636 animations agree, 0 disagree


def anim_records(data: bytes, rec_size: int = 28):
    """Yield Animation.bin records: the packed word plus the root-motion geometry."""
    if len(data) % rec_size:
        raise ValueError(f"Animation.bin size {len(data)} is not a multiple of {rec_size}")
    for o in range(0, len(data), rec_size):
        v = struct.unpack_from("<I", data, o)[0]
        bz, bx, fx, fz, ang = struct.unpack_from("<fffff", data, o + 8)
        yield {"anim_index": v & 0xFFF,
               "end_frame": ((v >> 12) & 0x1FF) + 8,
               "blend_start": (v >> 21) + 6,          # width not fully settled, see module docs
               "geometry": tuple(round(x, 3) for x in (bz, bx, fx, fz, ang))}


def cancel_records(data: bytes):
    """Yield CancelData records: frame in the high bits, animation index in the low 12 (+bias)."""
    n = len(data) // 4
    for v in struct.unpack(f"<{n}I", data[: n * 4]):
        yield {"anim_index": (v & 0xFFF) + CANCEL_INDEX_BIAS, "frame": v >> 12}


def index_to_name(mbinfo_dir: Path) -> dict[int, str]:
    """Map anim_index -> animation file name, by joining Animation.bin records to anim_infos.json
    on their (effectively unique) root-motion geometry. PES 2014 only — eFootball ships no JSON."""
    anims = json.loads((mbinfo_dir / "Json" / "anim_infos.json").read_text(encoding="utf-8"))["animations"]
    by_geom: dict[tuple, list[str]] = {}
    for k, v in anims.items():
        g = tuple(round(v[f], 3) for f in ("root_pos_blend_z", "root_pos_blend_x",
                                           "root_pos_first_x", "root_pos_first_z", "end_move_angle"))
        by_geom.setdefault(g, []).append(k)
    out = {}
    for r in anim_records(load(mbinfo_dir, "Animation.bin")):
        cand = by_geom.get(r["geometry"])
        if cand and len(cand) == 1:
            out[r["anim_index"]] = anims[cand[0]]["file_name"]
    return out


def cmd_sizes(args):
    a = tables(Path(args.dir))
    if not args.dir2:
        print(f"{'table':<30}{'bytes':>12}")
        for k, v in a.items():
            print(f"{k:<30}{v:>12,}")
        return
    b = tables(Path(args.dir2))
    print(f"{'table':<30}{'A':>12}{'B':>12}{'ratio':>9}")
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k), b.get(k)
        ratio = f"{vb/va:.2f}x" if va and vb and va > 0 else ("new" if vb else "gone")
        print(f"{k:<30}{va if va is not None else '-':>12}{vb if vb is not None else '-':>12}{ratio:>9}")


def cmd_hold(args):
    data = load(Path(args.dir), "HoldData.bin")
    recs = list(hold_records(data))
    rec_size = len(data) // len(recs)
    print(f"HoldData.bin: {len(data):,} bytes, {len(recs)} records of {rec_size} bytes")
    for r in recs[: args.limit]:
        bone = "-" if r["bone"] is None else r["bone"]
        print(f"  packed={r['packed']:08x} bone={bone:>3} "
              f"offset=({r['offset_x']:9.4f},{r['offset_y']:9.4f},{r['offset_z']:9.4f})")


def cmd_cancel(args):
    d = Path(args.dir)
    data = load(d, "CancelData.bin")
    recs = list(cancel_records(data))
    names = {}
    if (d / "Json" / "anim_infos.json").exists():
        names = index_to_name(d)
    print(f"CancelData.bin: {len(data):,} bytes, {len(recs)} records"
          + (f", {len(names)} indices resolved to names" if names else ""))
    grouped: dict[int, list[int]] = {}
    for r in recs:
        grouped.setdefault(r["anim_index"], []).append(r["frame"])
    for i, (idx, frames) in enumerate(grouped.items()):
        if i >= args.limit:
            break
        nm = names.get(idx, "")
        print(f"  anim_index={idx:<5} cancel_frames={sorted(frames)} {nm}")


def cmd_names(args):
    d = Path(args.dir)
    names = index_to_name(d)
    print(f"{len(names)} anim_index -> name")
    pat = (args.grep or "").lower()
    shown = 0
    for idx in sorted(names):
        if pat and pat not in names[idx].lower():
            continue
        print(f"  {idx:<6} {names[idx]}")
        shown += 1
        if shown >= args.limit:
            break


def cmd_verify(args):
    """Re-prove the layouts against PES 2014's own anim_infos.json."""
    d = Path(args.dir)
    js = json.loads((d / "Json" / "anim_infos.json").read_text(encoding="utf-8"))
    anims = js["animations"]
    ok = True

    # Animation.bin: 28-byte records; check geometry against the first animations in key order.
    data = load(d, "Animation.bin")
    if len(data) % 28:
        print(f"FAIL Animation.bin {len(data)} not a multiple of 28"); ok = False
    else:
        keys = sorted(anims, key=lambda s: int(s))
        checked = matched = 0
        for rec in range(min(64, len(data) // 28)):
            o = rec * 28
            bz, bx, fx, fz, ang = struct.unpack_from("<fffff", data, o + 8)
            v = anims[keys[rec]]
            checked += 1
            if all(abs(g - w) < 1e-3 for g, w in (
                    (bz, v["root_pos_blend_z"]), (bx, v["root_pos_blend_x"]),
                    (fx, v["root_pos_first_x"]), (fz, v["root_pos_first_z"]),
                    (ang, v["end_move_angle"]))):
                matched += 1
        print(f"Animation.bin  28B x {len(data)//28} records; geometry matched {matched}/{checked}")
        ok &= matched == checked

    # HoldData.bin: record 0 must reproduce the first hold entry exactly.
    data = load(d, "HoldData.bin")
    first = next(hold_records(data))
    want = None
    for k in sorted(anims, key=lambda s: int(s)):
        hd = anims[k].get("hold_data")
        if hd:
            want = hd[0]; break
    got = all(abs(first[f] - want[f.replace("offset", "hold_offset")]) < 1e-3
              for f in ("offset_x", "offset_y", "offset_z"))
    print(f"HoldData.bin   16B records; record 0 offsets reproduce JSON: {got}")
    ok &= got

    # The join: records -> names by geometry, cross-checked by the independently decoded end_frame.
    names = index_to_name(d)
    by_name = {v["file_name"]: v for v in anims.values()}
    agree = sum(1 for r in anim_records(load(d, "Animation.bin"))
                if r["anim_index"] in names
                and by_name[names[r["anim_index"]]]["end_frame"] == r["end_frame"])
    print(f"Animation.bin  geometry join resolved {len(names)} indices; "
          f"decoded end_frame agrees on {agree}/{len(names)}")
    ok &= agree == len(names)

    # CancelData.bin: with the +5 index bias, every resolvable animation's frames must match.
    idx_to_frames: dict[int, list[int]] = {}
    for r in cancel_records(load(d, "CancelData.bin")):
        idx_to_frames.setdefault(r["anim_index"], []).append(r["frame"])
    ag = dis = unresolved = 0
    for idx, frames in idx_to_frames.items():
        nm = names.get(idx)
        if nm is None:
            unresolved += 1
            continue
        want = sorted(e["cancel_frame"] for e in (by_name[nm].get("cancel_data") or []))
        if sorted(frames) == want:
            ag += 1
        else:
            dis += 1
    print(f"CancelData.bin anim_index=(v&0xFFF)+{CANCEL_INDEX_BIAS}: "
          f"agree={ag} disagree={dis} unresolved={unresolved}")
    ok &= dis == 0 and ag > 1000

    print("\nVERIFY", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("sizes", cmd_sizes), ("hold", cmd_hold), ("cancel", cmd_cancel),
                     ("names", cmd_names), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("dir")
        if name == "sizes":
            p.add_argument("dir2", nargs="?")
        if name in ("hold", "cancel", "names"):
            p.add_argument("--limit", type=int, default=20)
        if name == "names":
            p.add_argument("--grep", help="only show names containing this substring")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
