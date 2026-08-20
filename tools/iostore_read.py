"""Read a UE5 IoStore container's directory index with the global AES-256 key.

Self-contained: includes a small pure-Python AES-256 (decrypt only) so there's no external
crypto dependency — the directory index is a few hundred KB, so speed is a non-issue.

Verifies the key by decrypting a .utoc directory index and reconstructing asset paths. If the
mount point and paths come out as readable UE asset paths, the key is correct and every
pc*.ucas in the install is now readable.

Usage:
  python tools/iostore_read.py <file.utoc> <aes_key_hex> [--limit N]
"""
from __future__ import annotations

import struct
import sys

# ---- pure-python AES-256 (decrypt) ------------------------------------------------------
SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d]


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11b) & 0xff if a & 0x100 else a & 0xff


def _mul(a: int, b: int) -> int:
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r


def _expand_key(key: bytes) -> list[list[int]]:
    nk, nr = 8, 14
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // nk - 1]
        elif i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    # round r's key = its four column-words: rk[r][col][byte]
    return [[w[4 * r + c] for c in range(4)] for r in range(nr + 1)]


def _decrypt_block(block: bytes, rk: list[list[list[int]]]) -> bytes:
    nr = 14
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]

    def add(rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= rk[rnd][c][r]

    add(nr)
    for rnd in range(nr - 1, 0, -1):
        for r in range(1, 4):                        # inv shift rows
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):                           # inv sub bytes
            for c in range(4):
                s[r][c] = INV_SBOX[s[r][c]]
        add(rnd)
        for c in range(4):                           # inv mix columns
            a = [s[r][c] for r in range(4)]
            s[0][c] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
            s[1][c] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
            s[2][c] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
            s[3][c] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
    for r in range(1, 4):
        s[r] = s[r][-r:] + s[r][:-r]
    for r in range(4):
        for c in range(4):
            s[r][c] = INV_SBOX[s[r][c]]
    add(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes256_ecb_decrypt(data: bytes, key: bytes) -> bytes:
    rk = _expand_key(key)
    out = bytearray()
    for off in range(0, len(data), 16):
        out += _decrypt_block(data[off:off + 16], rk)
    return bytes(out)


# ---- IoStore .utoc parse ----------------------------------------------------------------
def read_utoc(path: str, key: bytes, limit: int = 60):
    d = open(path, "rb").read()
    assert d[:16] == b"-==--==--==--==-", "not an IoStore .utoc"
    (hdr_size, entry_count, cbe_count, cbe_size, cmn_count, cmn_len,
     cbs, dir_index_size) = struct.unpack_from("<IIIIIIII", d, 0x14)
    flags = d[0x50]
    encrypted = bool(flags & 2)
    off = hdr_size
    off += entry_count * 12          # FIoChunkId[]
    off += entry_count * 10          # FIoOffsetAndLength[]
    off += cbe_count * cbe_size      # compression blocks
    off += cmn_count * cmn_len       # compression method names
    dir_blob = d[off:off + dir_index_size]
    if encrypted:
        # pad to 16 for the last partial block, decrypt, then use dir_index_size bytes
        pad = (-len(dir_blob)) % 16
        dir_blob = aes256_ecb_decrypt(dir_blob + b"\x00" * pad, key)[:dir_index_size]

    p = 0

    def u32():
        nonlocal p
        v = struct.unpack_from("<I", dir_blob, p)[0]
        p += 4
        return v

    def fstring():
        nonlocal p
        n = struct.unpack_from("<i", dir_blob, p)[0]
        p += 4
        if n == 0:
            return ""
        if n > 0:
            s = dir_blob[p:p + n - 1].decode("latin1", "replace")
            p += n
        else:
            s = dir_blob[p:p + (-n) * 2 - 2].decode("utf-16-le", "replace")
            p += (-n) * 2
        return s

    mount = fstring()
    dir_count = u32()
    dirs = [struct.unpack_from("<IIII", dir_blob, p + i * 16) for i in range(dir_count)]
    p += dir_count * 16
    file_count = u32()
    files = [struct.unpack_from("<III", dir_blob, p + i * 12) for i in range(file_count)]
    p += file_count * 12
    str_count = u32()
    strings = [fstring() for _ in range(str_count)]

    NONE = 0xFFFFFFFF
    paths = []

    def walk(dir_idx, prefix):
        if len(paths) >= limit:
            return
        name, first_child, next_sib, first_file = dirs[dir_idx]
        here = prefix if name == NONE else prefix + strings[name] + "/"
        f = first_file
        while f != NONE and len(paths) < limit:
            fname, next_file, _ = files[f]
            paths.append(here + (strings[fname] if fname != NONE else "?"))
            f = next_file
        c = first_child
        while c != NONE and len(paths) < limit:
            walk(c, here)
            _, _, next_sib_c, _ = dirs[c]
            c = next_sib_c

    if dir_count:
        walk(0, "")
    return mount, entry_count, dir_count, file_count, str_count, paths


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path, key_hex = sys.argv[1], sys.argv[2].removeprefix("0x")
    limit = 60
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    key = bytes.fromhex(key_hex)
    if len(key) != 32:
        print(f"key is {len(key)} bytes; AES-256 needs 32")
        return 2
    mount, ec, dc, fc, sc, paths = read_utoc(path, key, limit)
    print(f"mount point: {mount!r}")
    print(f"entries={ec}  dirs={dc}  files={fc}  strings={sc}")
    ok = mount.startswith("../") or mount.startswith("/")
    print("KEY VERIFIED" if ok and paths else "key looks WRONG (garbage mount/paths)")
    print(f"\nfirst {len(paths)} asset paths:")
    for p in paths:
        print("  " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
