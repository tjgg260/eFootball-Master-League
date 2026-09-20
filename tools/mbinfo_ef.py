#!/usr/bin/env python3
"""
mbinfo_ef.py - eFootball-corrected reader for the Fox animation metadata tables
(common/anime/{Mbinfo,AnimeTable}/bin/*.bin).  Companion to mbinfo.py, which
stays correct for PES 2014 and is WRONG for eFootball on three points:

  1. eFootball CancelData.bin records are 12 bytes, not 4.
  2. The animation index widened from 12 to 13 bits, so the frame is v >> 13,
     not v >> 12.  Reading it the PES way DOUBLES every frame number.
  3. There is no +5 index bias in eFootball.  Bias 0.

Proof of (2), from eFootball.exe.PRISTINE (VAs at base 0x140000000):

    0x143e95e30  mov   eax, r15d               ; record i
    0x143e95e33  lea   rcx, [rax + rax*2]      ; i*3
    0x143e95e37  lea   rdi, [rcx*4]            ;   *4  -> 12-byte stride
    0x143e95e3f  add   rdi, r13
    0x143e95e42  movzx r8d, word ptr [rdi]     ; first u16 of the record
    0x143e95e46  and   r8d, 0x1fff             ; <- animation id is 13 bits
    ...
    0x143e95e80  imul  rdx, rax, 0x1f8         ; per-animation record, 504 bytes

The same routine at 0x143e958d0 does the 20-byte (HoldData) case, and the id
bound check in every accessor is "cmp edx, 0x1ecb" (= 7883) - exactly the length
of the animation-name pointer table at VA 0x148027310, which
tools/data/ef_anime_names.json carries.  So anim_id is a direct array index and
the name lookup needs no geometry join, unlike PES 2014.

Frame unit: 1/60 s.  Anchored on gait.  walk_1_1 is 72 frames and run_4_4 is 28
- 1.20 s and 0.47 s at 60 fps, which are correct human walk and sprint stride
cycles; at 30 fps they would be 2.4 s and 0.93 s, which are impossible.  The same
two animations in PES 2014 are 36 and 13 frames, i.e. PES authored on a 1/30 s
grid and eFootball doubled it.

Container: "ff 20 <flag> WESYS u32 csize u32 dsize", flag 0x81 = zlib,
flag 0x00 = stored (csize == dsize).  MatchAnimeDefinedatatable.bin is the only
stored file in the tree, which is why a zlib-only unwrap called it broken.

Nothing here writes.

Usage
    python tools/mbinfo_ef.py sizes   <anime_dir>
    python tools/mbinfo_ef.py cancel  <anime_dir> [--grep stagger_] [--limit N]
    python tools/mbinfo_ef.py hold    <anime_dir> [--limit N]
    python tools/mbinfo_ef.py connect <anime_dir> [--grep fall_]
    python tools/mbinfo_ef.py lockout <anime_dir>     # the contact report, in seconds
<anime_dir> is a .../common/anime directory.
"""
from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
import zlib
from collections import defaultdict
from pathlib import Path

FPS = 60.0
ANIM_ID_BITS = 13
ANIM_ID_MASK = (1 << ANIM_ID_BITS) - 1
ANIM_ID_COUNT = 0x1ecb          # 7883, from the exe's own bound check
NAMES_JSON = Path(__file__).with_name("data") / "ef_anime_names.json"


def unwrap(blob: bytes) -> bytes:
    """Return the payload. Handles WESYS zlib (flag 0x81) and stored (flag 0x00)."""
    i = blob.find(b"WESYS")
    if i < 0:
        return blob
    csize, dsize = struct.unpack_from("<II", blob, i + 5)
    body = blob[i + 13:]
    out = body[:csize] if csize == dsize else zlib.decompress(body)
    if len(out) != dsize:
        raise ValueError("WESYS size mismatch: header says %d, got %d" % (dsize, len(out)))
    return out


def load(anime_dir: Path, rel: str) -> bytes:
    return unwrap((anime_dir / rel).read_bytes())


def names() -> list:
    return json.loads(NAMES_JSON.read_text(encoding="utf-8"))["body"]


# ---- record layouts -------------------------------------------------------
# Every layout below was chosen by a test the wrong answer cannot pass: with the
# right record size and key, no record's id lands on one of the 660 enum_dummy*
# placeholder slots (chance rate 8.37%) AND no id reappears after its run ends
# (the exe's loader counts *consecutive* records with an equal key, so the table
# has to be grouped).  Sizes marked (b) are also confirmed by the loader's own
# stride in the disassembly.

REC_SIZE = {
    "Mbinfo/bin/Animation.bin":             36,   # 1 row/animation, id in low 13 bits
    "Mbinfo/bin/CancelData.bin":            12,   # (b)
    "Mbinfo/bin/HoldData.bin":              20,   # (b)
    "Mbinfo/bin/DangerData.bin":            20,
    "Mbinfo/bin/DemoConnectData.bin":        4,
    "Mbinfo/bin/JumpData.bin":               4,
    "Mbinfo/bin/KickData.bin":               4,
    "Mbinfo/bin/CategoryData.bin":           4,
    "Mbinfo/bin/AnimationData.bin":         36,   # id at bits 13..25, NOT 0..12
    "Mbinfo/bin/BallData.bin":              20,
    "EyesTarget/bin/Eyestarget.bin":         4,   # exactly 7883 rows: one per animation
    "AnimeTable/bin/CancelData.bin":        12,
    "AnimeTable/bin/DemoConnectData.bin":    4,
    "AnimeTable/bin/Risetypeframedata.bin": 12,
    "AnimeTable/bin/Risetypedata.bin":      12,
}


def anim_records(data: bytes):
    """Mbinfo/Animation.bin, 36 B.  `length` is the animation's frame count."""
    for o in range(0, len(data), 36):
        v, w2 = struct.unpack_from("<II", data, o)
        bz, bx, _y, fx, fz, f5, ang = struct.unpack_from("<7f", data, o + 8)
        yield {"anim_id": v & ANIM_ID_MASK,
               "length": (w2 >> 9) & 0x3FF,          # frames @60 fps
               "field_b": ((v >> 13) & 0x1FF) + 8,   # frame-like, ~0.75*length, UNIDENTIFIED
               "turn_deg": w2 & 0x1FF,               # multiples of 45; 360 = free
               "geometry": (round(bz, 3), round(bx, 3), round(fx, 3), round(fz, 3), round(ang, 3)),
               "f5": round(f5, 3)}


def cancel_records(data: bytes):
    """CancelData, 12 B: {u32 packed, f32, f32}.  The two floats are in the same
    units and range as Animation.bin's root-motion geometry (-480..1282 and
    -689..606, i.e. centimetres) and |lane a| is non-decreasing with the frame on
    789 of the 1008 multi-key animations - consistent with a root offset at the
    cancel frame, but NOT PROVEN: at the last key the median lane_a/blend_z is
    0.75 while the median frame/length is 0.33, so it is not a plain lerp."""
    for o in range(0, len(data), 12):
        v, a, b = struct.unpack_from("<Iff", data, o)
        yield {"anim_id": v & ANIM_ID_MASK, "frame": v >> ANIM_ID_BITS,
               "root_a": round(a, 3), "root_b": round(b, 3)}


def hold_records(data: bytes):
    """HoldData, 20 B: {u32 packed, u32 bone, f32 z, f32 y, f32 x}.
    `bone` takes only 7 and 11.  The three animations that carry both give the
    two records mirrored Z with matching X and Y, so 7/11 are a left/right pair
    (the hands).  It is NOT an index into the 22-bone anim or render skeleton."""
    for o in range(0, len(data), 20):
        v, bone = struct.unpack_from("<II", data, o)
        z, y, x = struct.unpack_from("<fff", data, o + 8)
        yield {"anim_id": v & ANIM_ID_MASK, "window": v >> ANIM_ID_BITS, "bone": bone,
               "offset_x": round(x, 3), "offset_y": round(y, 3), "offset_z": round(z, 3)}


def connect_records(data: bytes):
    """DemoConnectData, 4 B: {id:13, connect_frame:9, end_state:>=22}.
    end_state reproduces PES 2014's posture histogram (7 dominant, then 12/2/3/4)."""
    for o in range(0, len(data), 4):
        v = struct.unpack_from("<I", data, o)[0]
        yield {"anim_id": v & ANIM_ID_MASK, "connect_frame": (v >> 13) & 0x1FF,
               "end_state": v >> 22}


# ---- commands -------------------------------------------------------------

def _grouped_cancel(anime: Path, rel="Mbinfo/bin/CancelData.bin"):
    g = defaultdict(list)
    for r in cancel_records(load(anime, rel)):
        g[r["anim_id"]].append(r["frame"])
    return dict((k, sorted(v)) for k, v in g.items())


def _lengths(anime: Path):
    return dict((r["anim_id"], r["length"])
                for r in anim_records(load(anime, "Mbinfo/bin/Animation.bin")))


def cmd_sizes(a):
    anime = Path(a.dir)
    for p in sorted(anime.rglob("*.bin")):
        rel = str(p.relative_to(anime)).replace("\\", "/")
        try:
            n = len(unwrap(p.read_bytes()))
        except Exception as exc:
            print("  ! %-42s%s" % (rel, exc))
            continue
        R = REC_SIZE.get(rel)
        note = "%d B x %d" % (R, n // R) if R and n % R == 0 else "record size not solved"
        print("%-44s%10d   %s" % (rel, n, note))


def cmd_cancel(a):
    anime = Path(a.dir)
    nm = names()
    g = _grouped_cancel(anime)
    lens = _lengths(anime)
    shown = 0
    for i in sorted(g):
        name = nm[i] if i < len(nm) else "<%d>" % i
        if a.grep and a.grep.lower() not in name.lower():
            continue
        fr = g[i]
        L = lens.get(i)
        print("  %-5d %-48s len=%5s fr (%.2fs)  cancel %s = %s s"
              % (i, name, L if L else "?", (L / FPS if L else 0.0), fr,
                 [round(f / FPS, 3) for f in fr]))
        shown += 1
        if shown >= a.limit:
            break


def cmd_hold(a):
    anime = Path(a.dir)
    nm = names()
    for i, r in enumerate(hold_records(load(anime, "Mbinfo/bin/HoldData.bin"))):
        if i >= a.limit:
            break
        print("  %-48s bone=%3d offset=(%8.2f,%8.2f,%8.2f)"
              % (nm[r["anim_id"]], r["bone"], r["offset_x"], r["offset_y"], r["offset_z"]))


def cmd_connect(a):
    anime = Path(a.dir)
    nm = names()
    lens = _lengths(anime)
    for r in connect_records(load(anime, "Mbinfo/bin/DemoConnectData.bin")):
        name = nm[r["anim_id"]]
        if a.grep and a.grep.lower() not in name.lower():
            continue
        L = lens.get(r["anim_id"])
        print("  %-48s len=%5s fr  connect@%3d = %.3fs  end_state=%d"
              % (name, L if L else "?", r["connect_frame"], r["connect_frame"] / FPS,
                 r["end_state"]))


def cmd_lockout(a):
    """The number the contact work has been waiting for: how long a player is
    locked out of control by each contact animation, in real seconds."""
    anime = Path(a.dir)
    nm = names()
    g = _grouped_cancel(anime)
    lens = _lengths(anime)
    fams = [("stagger_upbody_", "shoved off the ball (upper body)"),
            ("stagger_lowbody_", "clipped on the legs"),
            ("stagger_", "all staggers"),
            ("tackle", "the tackler's own animation"),
            ("sliding", "slide tackle"),
            ("fall_", "going to ground"),
            ("lose_", "losing the ball"),
            ("js_", "jostle / shielding"),
            ("block", "block"),
            ("dodge", "dodge")]
    print("%-36s%4s%30s%20s" % ("family", "n", "first cancel (s)", "anim length (s)"))
    for pfx, label in fams:
        ids = [i for i, n in enumerate(nm) if n.startswith(pfx) and g.get(i)]
        if not ids:
            continue
        firsts = [min(g[i]) / FPS for i in ids]
        L = [lens[i] / FPS for i in ids if i in lens]
        span = "%.3f / %.3f / %.3f" % (min(firsts), statistics.median(firsts), max(firsts))
        print("%-36s%4d%30s%20s" % (label, len(ids), span,
                                    ("%.2f" % statistics.median(L)) if L else "?"))
    print("\n(min / median / max of the FIRST cancel key. Before it the player cannot act;")
    print(" after it canCancel, action vtable slot 14, can let a queued action through.)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("sizes", cmd_sizes), ("cancel", cmd_cancel), ("hold", cmd_hold),
                     ("connect", cmd_connect), ("lockout", cmd_lockout)):
        p = sub.add_parser(name)
        p.add_argument("dir")
        if name in ("cancel", "hold", "connect"):
            p.add_argument("--limit", type=int, default=40)
            p.add_argument("--grep")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
