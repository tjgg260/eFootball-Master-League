# -*- coding: utf-8 -*-
"""UE4.26/4.27 IoStore (.utoc/.ucas, TOC v2) 只读访问 + Texture2D 解码。

实测 eFootball: 23 个容器全是 TOC v2、Zlib、除 pc7000 外都加密 (社区 AES 密钥)。
    c = Container(r"...\\pak\\pc1000_console_win.utoc")
    raw = c.read("ui/Data/Thumbnail/Player/100012_.uasset")   # 路径可省略 mount 前缀
    img = texture_to_image(raw)                                  # -> PIL.Image
"""
import re
import struct
import zlib

from Crypto.Cipher import AES

KEY = bytes.fromhex("4552D45005DFE94964893F4925EC747D3D591401E060ED8B3D58BE5721C81295")
INV = 0xFFFFFFFF
PREFIX = "../../../PesConsole/Content/Assets/"


def _dec(b):
    n = len(b) - len(b) % 16
    return AES.new(KEY, AES.MODE_ECB).decrypt(bytes(b[:n]))


def _fstr(b, o):
    n = struct.unpack_from("<i", b, o)[0]
    o += 4
    if n == 0:
        return "", o
    if n > 0:
        return b[o:o + n - 1].decode("latin-1"), o + n
    n = -n
    return b[o:o + (n - 1) * 2].decode("utf-16-le"), o + n * 2


class Container:
    def __init__(self, utoc):
        b = open(utoc, "rb").read()
        assert b[:16] == b"-==--==--==--==-"
        self.ver = b[16]
        (hsz, cnt, cbc, _cbsz, mnc, mnl, self.blk, disz, _parts) = struct.unpack_from("<9I", b, 20)
        self.flags = b[80]
        self.encrypted = bool(self.flags & 2)
        o = hsz
        self.chunk_ids = b[o:o + cnt * 12]
        o += cnt * 12
        self.offlen = b[o:o + cnt * 10]
        o += cnt * 10
        if self.ver >= 4:
            o += struct.unpack_from("<I", b, 84)[0] * 4
        if self.ver >= 5:
            o += struct.unpack_from("<I", b, 96)[0] * 4
        self.blocks = b[o:o + cbc * 12]
        o += cbc * 12
        self.methods = [b[o + i * mnl:o + (i + 1) * mnl].rstrip(b"\0").decode() for i in range(mnc)]
        o += mnc * mnl
        if self.flags & 4:
            hs, = struct.unpack_from("<i", b, o)
            o += 4 + hs * 2 + cbc * 20
        self.paths = {}
        if self.flags & 8 and disz:
            self._index(_dec(b[o:o + disz]) if self.encrypted else b[o:o + disz])
        self.ucas = open(utoc[:-5] + ".ucas", "rb")

    def _index(self, d):
        mount, q = _fstr(d, 0)
        nd, = struct.unpack_from("<I", d, q)
        dirs = [struct.unpack_from("<4I", d, q + 4 + i * 16) for i in range(nd)]
        q += 4 + nd * 16
        nf, = struct.unpack_from("<I", d, q)
        fe = [struct.unpack_from("<3I", d, q + 4 + i * 12) for i in range(nf)]
        q += 4 + nf * 12
        ns, = struct.unpack_from("<I", d, q)
        q += 4
        strings = []
        for _ in range(ns):
            s, q = _fstr(d, q)
            strings.append(s)
        stack = [(0, mount)]
        while stack:
            di, pre = stack.pop()
            _n, child, _sib, f = dirs[di]
            while f != INV:
                fn, nxt, ud = fe[f]
                self.paths[pre + strings[fn]] = ud
                f = nxt
            ch = child
            while ch != INV:
                stack.append((ch, pre + strings[dirs[ch][0]] + "/"))
                ch = dirs[ch][2]

    def resolve(self, path):
        if path in self.paths:
            return self.paths[path]
        return self.paths.get(PREFIX + path)

    def size(self, path):
        i = self.resolve(path)
        return int.from_bytes(self.offlen[i * 10 + 5:i * 10 + 10], "big")

    def read(self, path):
        i = self.resolve(path)
        if i is None:
            raise KeyError(path)
        off = int.from_bytes(self.offlen[i * 10:i * 10 + 5], "big")
        ln = int.from_bytes(self.offlen[i * 10 + 5:i * 10 + 10], "big")
        first, last = off // self.blk, (off + ln - 1) // self.blk
        out = bytearray()
        for bi in range(first, last + 1):
            e = self.blocks[bi * 12:(bi + 1) * 12]
            boff = int.from_bytes(e[0:5], "little")
            csz = int.from_bytes(e[5:8], "little")
            usz = int.from_bytes(e[8:11], "little")
            m = e[11]
            self.ucas.seek(boff)
            raw = self.ucas.read((csz + 15) & ~15 if self.encrypted else csz)
            if self.encrypted:
                raw = _dec(raw)
            raw = raw[:csz]
            out += raw[:usz] if m == 0 else zlib.decompress(raw)
        s = off - first * self.blk
        return bytes(out[s:s + ln])


# ---------------------------------------------------------------- Texture2D
_PF = re.compile(rb"PF_[A-Za-z0-9_]{2,24}\x00")


def parse_texture(pkg, ubulk=None):
    """扫 FTexturePlatformData (FString 'PF_xxx' 前后是固定布局), 不解析属性表。"""
    for m in _PF.finditer(pkg):
        s = m.start()
        if s < 16 or struct.unpack_from("<i", pkg, s - 4)[0] != len(m.group()):
            continue
        sx, sy, packed = struct.unpack_from("<iiI", pkg, s - 16)
        o = m.end()
        if packed & (1 << 30):
            o += 8
        first, nmips = struct.unpack_from("<ii", pkg, o)
        o += 8
        if not (0 < nmips < 20 and 0 < sx <= 16384 and 0 < sy <= 16384):
            continue
        mips = []
        for _ in range(nmips):
            _cooked, fl = struct.unpack_from("<II", pkg, o)
            o += 8
            if fl & 0x2000:
                cnt, sod = struct.unpack_from("<qq", pkg, o)
                o += 16
            else:
                cnt, sod = struct.unpack_from("<ii", pkg, o)
                o += 8
            boff, = struct.unpack_from("<q", pkg, o)
            o += 8
            if fl & 0x8000:
                o += 2
            data = None
            if not fl & 0x101:
                data = pkg[o:o + sod]
                o += sod
            elif fl & 0x100 and ubulk is not None:
                data = ubulk[boff:boff + sod]
            mw, mh, _mz = struct.unpack_from("<iii", pkg, o)
            o += 12
            mips.append(dict(flags=fl, size=sod, off=boff, w=mw, h=mh, data=data))
        return dict(fmt=m.group()[:-1].decode(), w=sx, h=sy, packed=packed,
                    first=first, mips=mips)
    return None


_BCN = {"PF_DXT1": (1, "RGBA"), "PF_DXT3": (2, "RGBA"), "PF_DXT5": (3, "RGBA"),
        "PF_BC4": (4, "L"), "PF_BC5": (5, "RGB"), "PF_BC7": (7, "RGBA")}


def mip_to_image(fmt, mip):
    from PIL import Image
    w, h, data = mip["w"], mip["h"], mip["data"]
    if fmt == "PF_B8G8R8A8":
        return Image.frombytes("RGBA", (w, h), data, "raw", "BGRA")
    if fmt == "PF_G8":
        return Image.frombytes("L", (w, h), data)
    if fmt in _BCN:
        n, mode = _BCN[fmt]
        pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
        return Image.frombytes(mode, (pw, ph), data, "bcn", n).crop((0, 0, w, h))
    raise NotImplementedError(fmt)


def texture_to_image(pkg, ubulk=None):
    t = parse_texture(pkg, ubulk)
    if t is None:
        return None, None
    for mip in t["mips"]:
        if mip["data"]:
            return mip_to_image(t["fmt"], mip), t
    return None, t
