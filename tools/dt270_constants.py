#!/usr/bin/env python3
"""
dt270_constants.py — read (and re-pack) eFootball's match gameplay constants.

The gameplay "feel" of eFootball lives in dt270's `common/match/constant/*.bin` files, a separate
pack from the dt200 roster data. They are WESYS containers, but — unlike the pesdb data files —
the constants are NOT encrypted: whatever the header byte says, the payload is plain zlib. Our
vendored wesys decoder assumed byte0==0xFF meant an encrypted current-format stream and tried a
key nibble it doesn't hold; here we just inflate the zlib payload directly.

Use:
    python tools/dt270_constants.py compare       # diff the same constant across several mods
    from dt270_constants import decode_constant, encode_constant
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys   # noqa: E402


def decode_constant(blob: bytes) -> bytes:
    """Inflate a dt270 constant file to its raw parameter bytes, handling every header variant."""
    if not wesys.is_wesys_container(blob):
        try:
            return zlib.decompress(blob)
        except zlib.error:
            return blob
    comp, orig = struct.unpack_from("<II", blob, 8)
    payload = blob[16:]
    if comp == 0 and orig == 0:
        return b""
    # Constants are unencrypted zlib regardless of the 0xFF/0x00 header byte.
    try:
        un = zlib.decompress(payload)
        if not orig or len(un) == orig:
            return un
    except zlib.error:
        pass
    return wesys.unpack_wesys_payload(blob)   # fall back for any genuinely encrypted file


def encode_constant(payload: bytes, template: bytes, level: int = 9, max_len: int | None = None) -> bytes:
    """Re-pack edited constant bytes into a container matching the original's header shape.

    zlib level 9 reproduces Konami's streams byte-for-byte. When `max_len` is given and the
    level-9 stream would not fit that slot, fall back to zopfli (a ~4% smaller, still
    standard deflate stream the game inflates unchanged) — the headroom that makes in-place
    edits of the small constant files possible. Raises ValueError if nothing fits.
    """
    comp = zlib.compress(payload, level=level)
    if max_len is not None and 16 + len(comp) > max_len:
        try:
            import zopfli.zlib as _zz
        except ImportError:
            raise ValueError(f"level-9 stream too large for the slot ({16 + len(comp)} > {max_len}); "
                             "pip install zopfli for ~4% more headroom")
        for iters in (15, 100, 500):
            comp = _zz.compress(payload, numiterations=iters)
            if 16 + len(comp) <= max_len:
                break
        else:
            raise ValueError(f"edited pack does not fit its slot even with zopfli ({16 + len(comp)} > {max_len})")
        assert zlib.decompress(comp) == payload
    header = bytearray(template[:16])
    struct.pack_into("<II", header, 8, len(comp), len(payload))
    return bytes(header) + comp


def _cpk_constant(path: str, filename: str) -> bytes | None:
    from cricodecs import cpk
    c = cpk.load(path)
    for i, e in enumerate(c.files):
        if e.full_path.endswith(filename):
            return decode_constant(c.file_bytes(i))
    return None


def compare() -> int:
    mods = {
        "GabeLogan": "build/gabelogan/dt270_console_all.cpk",
        "EVO_HEAVY": "EVO_GP_HEAVY/EVO GP HEAVY/dt270_console_all.cpk",
        "BromiV21":  "BromiV21/dt270_console_all.cpk",
        "raw_dt270": "dt270_console_all.cpk",
    }
    for filename in ("constant_team.bin", "constant_match.bin", "constant_player.bin"):
        print(f"\n=== {filename} ===")
        payloads = {}
        for name, path in mods.items():
            try:
                p = _cpk_constant(path, filename)
                if p is not None:
                    payloads[name] = p
                    print(f"  {name:10} decoded {len(p):>6} bytes")
            except Exception as ex:
                print(f"  {name:10} ERR {ex}")
        # pairwise: how many 4-byte words differ vs the first mod as reference
        names = list(payloads)
        if len(names) >= 2:
            ref = payloads[names[0]]
            for other in names[1:]:
                o = payloads[other]
                n = min(len(ref), len(o))
                diffs = [i for i in range(0, n - 3, 4)
                         if ref[i:i+4] != o[i:i+4]]
                print(f"  {names[0]} vs {other}: {len(diffs)} of {n//4} words differ"
                      + (f"  (len {len(ref)} vs {len(o)})" if len(ref) != len(o) else ""))
                # show first few differing words as float32 pairs (gameplay params are floats)
                for off in diffs[:6]:
                    a = struct.unpack_from("<f", ref, off)[0]
                    b = struct.unpack_from("<f", o, off)[0]
                    print(f"      @{off:<5} {a:>12.4g} -> {b:<12.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(compare())
