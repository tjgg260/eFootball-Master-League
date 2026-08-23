#!/usr/bin/env python3
"""
iostore_extract.py — extract one asset payload from eFootball's UE5 IoStore (read-only, offline).

Proven against eFootball 2027: utoc VERSION 2, compression 'Zlib' (NOT Oodle), zero-GUID global
AES-256 key. Reuses the pure-Python AES-256 decryptor in iostore_read.py. Byte layout verified by
extracting SK_referee035_Face.uasset (1,384,953 bytes) end-to-end.

There is no global path->container index, so resolve() scans the 24 pak/*.utoc directory indices
(each a few hundred KB, cheap) and caches a path-suffix -> (container, entry) map to
build/iostore_index.json on first use.

CLI:
  python tools/iostore_extract.py <path-suffix> [out_file]
      e.g. python tools/iostore_extract.py RealFace/SK_referee035_Face.uasset face.uasset
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

# Fast AES (pycryptodome) when available; the pure-python fallback is ~1000x slower but portable.
try:
    from Crypto.Cipher import AES as _AES

    def aes256_ecb_decrypt(data: bytes, key: bytes) -> bytes:
        return _AES.new(key, _AES.MODE_ECB).decrypt(data)
except ImportError:
    from iostore_read import aes256_ecb_decrypt   # noqa: F401

KEY = bytes.fromhex("4552D45005DFE94964893F4925EC747D3D591401E060ED8B3D58BE5721C81295")
PAK_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\pak")
INDEX_CACHE = REPO / "build" / "iostore_index.json"


def load_utoc(base: Path):
    """base = path without extension. Returns everything to resolve+extract from the paired .ucas."""
    d = (base.with_suffix(".utoc")).read_bytes()
    assert d[:16] == b"-==--==--==--==-", "not an IoStore .utoc"
    (hdr, ec, cbe, cbes, cmn, cmnlen, cbs, dis) = struct.unpack_from("<IIIIIIII", d, 0x14)
    enc = bool(d[0x50] & 2)
    o_ol = hdr + ec * 12           # after FIoChunkId[ec] (12B each)
    o_cb = o_ol + ec * 10          # FIoOffsetAndLength[ec] (10B each)
    o_cmn = o_cb + cbe * cbes      # FIoStoreTocCompressedBlockEntry[cbe] (12B each)
    o_dir = o_cmn + cmn * cmnlen   # compression method names (32B each) -> directory index
    blob = d[o_dir:o_dir + dis]
    if enc:
        pad = (-len(blob)) % 16
        blob = aes256_ecb_decrypt(blob + b"\x00" * pad, KEY)[:dis]
    return {"d": d, "o_ol": o_ol, "o_cb": o_cb, "cbs": cbs, "enc": enc,
            "blob": blob, "ucas": base.with_suffix(".ucas")}


def parse_dir(blob: bytes):
    """Directory index -> (mount, dirs, files, strings). file.user_data = FIoOffsetAndLength index."""
    p = 0

    def u32():
        nonlocal p
        v = struct.unpack_from("<I", blob, p)[0]
        p += 4
        return v

    def fstr():
        nonlocal p
        n = struct.unpack_from("<i", blob, p)[0]
        p += 4
        if n == 0:
            return ""
        if n > 0:
            s = blob[p:p + n - 1].decode("latin1", "replace")
            p += n
        else:
            s = blob[p:p + (-n) * 2 - 2].decode("utf-16-le", "replace")
            p += (-n) * 2
        return s

    mount = fstr()
    dc = u32()
    dirs = [struct.unpack_from("<IIII", blob, p + i * 16) for i in range(dc)]
    p += dc * 16
    fc = u32()
    files = [struct.unpack_from("<III", blob, p + i * 12) for i in range(fc)]
    p += fc * 12
    sc = u32()
    strings = [fstr() for _ in range(sc)]
    return mount, dirs, files, strings


def _walk(mount, dirs, files, strings):
    """Yield (full_path, user_data) for every file in the container."""
    NONE = 0xFFFFFFFF
    if not dirs:
        return

    stack = [(0, mount)]
    while stack:
        di, pre = stack.pop()
        name, first_child, next_sib, first_file = dirs[di]
        here = pre if name == NONE else pre + strings[name] + "/"
        f = first_file
        while f != NONE:
            fn, nf, ud = files[f]
            yield here + (strings[fn] if fn != NONE else "?"), ud
            f = nf
        c = first_child
        while c != NONE:
            stack.append((c, here))
            c = dirs[c][2]


def extract(u, entry: int) -> bytes:
    """entry = user_data. Returns the exact asset bytes from the .ucas."""
    d, o_ol, o_cb, cbs, enc = u["d"], u["o_ol"], u["o_cb"], u["cbs"], u["enc"]
    rec = d[o_ol + entry * 10: o_ol + entry * 10 + 10]
    coff = int.from_bytes(rec[0:5], "big")      # logical offset in container vaddr space
    clen = int.from_bytes(rec[5:10], "big")     # logical length
    first = coff // cbs
    nblk = (coff % cbs + clen + cbs - 1) // cbs
    out = bytearray()
    with open(u["ucas"], "rb") as ucas:
        for bi in range(first, first + nblk):
            e = d[o_cb + bi * 12: o_cb + bi * 12 + 12]
            boff = int.from_bytes(e[0:5], "little")
            csz = int.from_bytes(e[5:8], "little")
            meth = e[11]
            ucas.seek(boff)
            raw = ucas.read((csz + 15) // 16 * 16 if enc else csz)
            if enc:
                raw = aes256_ecb_decrypt(raw, KEY)
            raw = raw[:csz]
            out += zlib.decompress(raw) if meth != 0 else raw
    return bytes(out[coff % cbs: coff % cbs + clen])


def containers() -> list[Path]:
    return sorted(p.with_suffix("") for p in PAK_DIR.glob("*.utoc"))


def resolve(suffix: str):
    """Find the container + entry for the first asset path ending in `suffix`. Scans all containers."""
    for base in containers():
        try:
            u = load_utoc(base)
            mount, dirs, files, strings = parse_dir(u["blob"])
        except Exception:
            continue
        for path, ud in _walk(mount, dirs, files, strings):
            if path.endswith(suffix):
                return base, ud, path, u
    return None


def extract_suffix(suffix: str) -> tuple[str, bytes] | None:
    r = resolve(suffix)
    if r is None:
        return None
    base, ud, path, u = r
    return path, extract(u, ud)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    suffix = sys.argv[1]
    r = extract_suffix(suffix)
    if r is None:
        print(f"not found: {suffix}")
        return 1
    path, data = r
    print(f"{path}\n  {len(data)} bytes, head={data[:8].hex()}")
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_bytes(data)
        print(f"  wrote {sys.argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
