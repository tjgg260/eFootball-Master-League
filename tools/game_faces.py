#!/usr/bin/env python3
r"""
game_faces.py — player portraits from eFootball's own UI thumbnails.

The game ships a 180x180 head shot for its players inside pak\pc1000_console_win (UE IoStore,
Zlib, AES): ui/Data/Thumbnail/Player/<PID>_.uasset, and Variation2022/<VID>_.uasset for variant
cards, named by the external PID (Player.bin bytes 8-15). The container reader and the texture
decoder are the eFootball Player Editor's iostore.py, vendored in tools/vendor/efootball-player-tool/.

RUNS FROM THE DOWNLOAD WITH NOTHING INSTALLED (MVP ruling 2026-09-13: faces are in the MVP).
iostore needs two third-party packages the embedded Python does not carry, so:
  * AES-ECB — without pycryptodome, Windows' own CNG (bcrypt.dll, via ctypes) does it. Proven
    byte-identical to pycryptodome on the game's data, 2026-09-13.
  * Texture decode — without Pillow, DXT5 (every base card's head) is decoded with numpy and written
    as PNG with zlib; within 1/255 of Pillow on 200 cards. BC7 (variant-card art) still needs
    Pillow and is skipped without it — the release bundles Pillow for exactly that.

What it writes
    build/game_faces/<PID>.png   one per PID some player resolves to. Konami's art: build/ is
                                 gitignored and the release does not ship it.
    players.game_face_path       'build/game_faces/<PID>.png'. The app shows it before every other
                                 portrait except the owner's own custom_faces/.

How a player resolves to a PID (first hit wins)
    1. its own record: players.game_pid, then players.base_pid (every career copy in a world read
       from the game carries its real PID there), then player_identity.ef_pid where that exists
    2. career copies without one (the curated world's): the one world player with a thumbnail whose
       accent-folded name and nationality match, and whose age is within 2. Two candidates is
       ambiguous and left without a face rather than guessed.

    python tools/game_faces.py --dry          # resolve and report; decode nothing, write nothing
    python tools/game_faces.py                # decode missing PNGs, write paths
    python tools/game_faces.py --pak <dir>    # another eFootball\pak folder

Idempotent: PNGs already on disk are not decoded again, and a player whose path is already right is
not rewritten. Close the app first — it holds the database open.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import struct
import sys
import time
import types
import unicodedata
import zlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "efootball-player-tool"))


def _install_cng_aes() -> None:
    """Stand in for pycryptodome's AES.new(key, MODE_ECB).decrypt — the only call iostore makes —
    with Windows CNG. One key handle per key: iostore asks for a cipher on every block it reads,
    and a fresh CNG key each time would leak a handle per block across twenty thousand faces."""
    import ctypes
    import ctypes.wintypes as wt
    bc = ctypes.WinDLL("bcrypt.dll")

    class _Ecb:
        def __init__(self, key: bytes):
            self.h, self.k = ctypes.c_void_p(), ctypes.c_void_p()
            self._key = ctypes.create_string_buffer(bytes(key), len(key))
            if bc.BCryptOpenAlgorithmProvider(ctypes.byref(self.h), "AES", None, 0):
                raise OSError("BCryptOpenAlgorithmProvider(AES) failed")
            mode = ctypes.create_unicode_buffer("ChainingModeECB")
            if bc.BCryptSetProperty(self.h, "ChainingMode", mode, ctypes.sizeof(mode), 0):
                raise OSError("BCryptSetProperty(ChainingModeECB) failed")
            if bc.BCryptGenerateSymmetricKey(self.h, ctypes.byref(self.k), None, 0,
                                             self._key, len(key), 0):
                raise OSError("BCryptGenerateSymmetricKey failed")

        def decrypt(self, data: bytes) -> bytes:
            buf = ctypes.create_string_buffer(bytes(data), len(data))
            out = ctypes.create_string_buffer(len(data))
            n = wt.ULONG()
            if bc.BCryptDecrypt(self.k, buf, len(data), None, None, 0, out, len(data), ctypes.byref(n), 0):
                raise OSError("BCryptDecrypt failed")
            return out.raw[:n.value]

    cache: dict[bytes, _Ecb] = {}

    def new(key, mode):
        k = bytes(key)
        if k not in cache:
            cache[k] = _Ecb(k)
        return cache[k]

    aes = types.ModuleType("Crypto.Cipher.AES")
    aes.MODE_ECB = 1
    aes.new = new
    cipher = types.ModuleType("Crypto.Cipher")
    cipher.AES = aes
    crypto = types.ModuleType("Crypto")
    crypto.Cipher = cipher
    sys.modules.update({"Crypto": crypto, "Crypto.Cipher": cipher, "Crypto.Cipher.AES": aes})


try:
    from Crypto.Cipher import AES as _AES  # noqa: F401  (pycryptodome, when it is there)
    AES_BACKEND = "pycryptodome"
except ImportError:
    _install_cng_aes()
    AES_BACKEND = "Windows CNG"
import iostore  # noqa: E402

try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

DB = REPO / "build" / "game_world.db"
OUT = REPO / "build" / "game_faces"
CONTAINER = "pc1000_console_win.utoc"
HEAD = re.compile(r"/ui/Data/Thumbnail/Player/(Variation\d+/)?(\d+)_\.uasset$")


def default_pak() -> Path:
    from steam_paths import efootball_dir
    return efootball_dir() / "pak"


def fold(name: str | None) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = s.replace("ø", "o").replace("Ø", "O").replace("ß", "ss").replace("đ", "d").replace("ł", "l")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def head_paths(container: iostore.Container) -> dict[int, str]:
    """PID -> head thumbnail path; the base card's head beats a variation's."""
    heads: dict[int, str] = {}
    for path in container.paths:
        m = HEAD.search(path)
        if m and (m.group(1) is None or int(m.group(2)) not in heads):
            heads[int(m.group(2))] = path
    return heads


# ---------------------------------------------------------------- decoding without Pillow

def _dxt5(data: bytes, w: int, h: int):
    import numpy as np
    b = np.frombuffer(data, np.uint8).reshape(-1, 16)
    n = len(b)
    a0 = b[:, 0].astype(np.int32)
    a1 = b[:, 1].astype(np.int32)
    ab = np.zeros(n, np.uint64)
    for i in range(6):
        ab |= b[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    aidx = ((ab[:, None] >> (np.arange(16, dtype=np.uint64) * 3)) & np.uint64(7)).astype(np.int32)
    k = np.arange(8)
    hi = np.where(k[None] == 0, a0[:, None], np.where(k[None] == 1, a1[:, None],
                  ((8 - k[None]) * a0[:, None] + (k[None] - 1) * a1[:, None]) // 7))
    lo = np.where(k[None] == 0, a0[:, None], np.where(k[None] == 1, a1[:, None],
                  np.where(k[None] == 6, 0, np.where(k[None] == 7, 255,
                           ((6 - k[None]) * a0[:, None] + (k[None] - 1) * a1[:, None]) // 5))))
    alpha = np.take_along_axis(np.where((a0 > a1)[:, None], hi, lo), aidx, 1)
    c0 = b[:, 8].astype(np.int32) | (b[:, 9].astype(np.int32) << 8)
    c1 = b[:, 10].astype(np.int32) | (b[:, 11].astype(np.int32) << 8)

    def rgb(c):
        return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31], -1)

    p0, p1 = rgb(c0), rgb(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], 1)
    ci = (b[:, 12].astype(np.uint32) | (b[:, 13].astype(np.uint32) << 8)
          | (b[:, 14].astype(np.uint32) << 16) | (b[:, 15].astype(np.uint32) << 24))
    cidx = ((ci[:, None] >> (np.arange(16, dtype=np.uint32) * 2)) & 3).astype(np.int64)
    col = np.take_along_axis(pal, cidx[:, :, None].repeat(3, 2), 1)
    px = np.concatenate([col, alpha[:, :, None]], 2).astype(np.uint8)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:h, :w])


def _to_rgba(fmt: str, mip: dict):
    import numpy as np
    w, h, data = mip["w"], mip["h"], mip["data"]
    if fmt == "PF_DXT5":
        return _dxt5(data, w, h)
    if fmt == "PF_B8G8R8A8":
        return np.ascontiguousarray(np.frombuffer(data, np.uint8)[:w * h * 4].reshape(h, w, 4)[..., [2, 1, 0, 3]])
    return None   # BC7 and the rest: Pillow only


def _write_png(path: Path, rgba) -> None:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def decode(container: iostore.Container, path: str, out: Path) -> bool:
    pkg = container.read(path)
    bulk = path[:-len(".uasset")] + ".ubulk"
    ubulk = container.read(bulk) if container.resolve(bulk) is not None else None
    tmp = out.with_suffix(".tmp.png")
    if HAVE_PIL:
        img, _info = iostore.texture_to_image(pkg, ubulk)
        if img is None:
            return False
        img.save(tmp)
    else:
        t = iostore.parse_texture(pkg, ubulk)
        mip = next((m for m in (t or {}).get("mips", []) if m["data"]), None)
        rgba = _to_rgba(t["fmt"], mip) if mip is not None else None
        if rgba is None:
            return False
        _write_png(tmp, rgba)
    tmp.replace(out)
    return True


# ---------------------------------------------------------------- the database

def career_band_of(con: sqlite3.Connection):
    """A predicate for 'this id is one of a save's own copies'. A world read from the game keeps
    real PIDs in 20M-700M and records its own career range (meta career_player_band)."""
    lo, hi = 20_000_000, 700_000_000
    try:
        row = con.execute("SELECT value FROM meta WHERE key='career_player_band'").fetchone()
        if row and row[0]:
            lo, hi = (int(x) for x in str(row[0]).split(","))
    except (sqlite3.Error, ValueError):
        pass
    return lambda pid: lo <= pid < hi or 45_000_000_000 <= pid < 47_000_000_000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--pak", default=None, help="eFootball\\pak (default: found via Steam)")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    pak = Path(args.pak) if args.pak else default_pak()
    utoc = pak / CONTAINER
    if not utoc.exists():
        sys.exit(f"{utoc} not found — pass --pak <eFootball>\\pak")
    t0 = time.time()
    container = iostore.Container(str(utoc))
    heads = head_paths(container)
    print(f"{CONTAINER}: {len(heads):,} player head thumbnails ({time.time() - t0:.1f}s; "
          f"AES via {AES_BACKEND}, images via {'Pillow' if HAVE_PIL else 'numpy (DXT5 only)'})")

    con = sqlite3.connect(args.db)
    is_career = career_band_of(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(players)")}
    has_col = "game_face_path" in cols
    players = con.execute(
        "SELECT id, game_pid, base_pid, name, nationality, age, "
        + ("game_face_path" if has_col else "NULL") + " FROM players").fetchall()
    try:
        ef_pid = dict(con.execute("SELECT player_id, ef_pid FROM player_identity WHERE ef_pid IS NOT NULL"))
    except sqlite3.Error:
        ef_pid = {}                      # a world read from the game has no identity spine

    # 1. a record's own PID
    resolved: dict[int, int] = {}
    for pid, game_pid, base_pid, *_ in players:
        for candidate in (game_pid, base_pid, ef_pid.get(pid)):
            if candidate in heads:
                resolved[pid] = candidate
                break

    # 2. career copies by name + nationality (+ age) against world players that resolved
    world = defaultdict(set)
    for pid, game_pid, _b, name, nat, age, _f in players:
        if pid in resolved and not is_career(game_pid):
            world[(fold(name), nat)].add((resolved[pid], age))
    by_name, ambiguous, unmatched = 0, [], 0
    for pid, game_pid, _b, name, nat, age, _f in players:
        if pid in resolved or not is_career(game_pid):
            continue
        fits = {p for p, a in world.get((fold(name), nat), ())
                if age is None or a is None or abs(age - a) <= 2}
        if len(fits) == 1:
            resolved[pid] = fits.pop()
            by_name += 1
        elif fits:
            ambiguous.append((name, sorted(fits)))
        else:
            unmatched += 1

    career = sum(1 for _p, g, *_ in players if is_career(g))
    print(f"players {len(players):,}: {len(resolved):,} resolve to a thumbnail "
          f"({len(resolved) - by_name:,} by their own PID, {by_name} career copies by name)")
    print(f"career players {career}: {by_name} matched by name, {len(ambiguous)} ambiguous, {unmatched} with no thumbnail")

    wanted = sorted(set(resolved.values()))
    missing = [p for p in wanted if not (OUT / f"{p}.png").exists()]
    updates = [(f"build/game_faces/{resolved[pid]}.png" if pid in resolved else None, pid)
               for pid, *_rest, current in players
               if (f"build/game_faces/{resolved[pid]}.png" if pid in resolved else None) != current]
    print(f"thumbnails needed {len(wanted):,}, to decode {len(missing):,}; player rows to update {len(updates):,}")
    if args.dry:
        print("--dry: nothing decoded, nothing written.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    t0 = time.time()
    for i, pid in enumerate(missing, 1):
        try:
            if not decode(container, heads[pid], OUT / f"{pid}.png"):
                failed.append(pid)
        except Exception as ex:  # noqa: BLE001 — one bad texture never stops the rest
            failed.append(pid)
            if len(failed) <= 5:
                print(f"   {pid}: {ex!r}")
        if i % 2000 == 0:
            print(f"   decoded {i:,}/{len(missing):,} ({time.time() - t0:.0f}s)", flush=True)
    print(f"decoded {len(missing) - len(failed):,} PNGs into build/game_faces "
          f"({time.time() - t0:.0f}s), {len(failed)} could not be decoded"
          + ("" if HAVE_PIL or not failed else " (variant-card art needs Pillow)"))
    if failed:
        bad = set(failed)
        updates = [(None if path and int(Path(path).stem) in bad else path, pid) for path, pid in updates]

    if not updates and has_col:
        print("database already up to date.")
        return 0
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    backup = Path(f"{args.db}.bak-gamefaces-{datetime.now():%Y%m%d}")
    if not backup.exists():                     # one restore point per day (CLAUDE.md: .bak fills the disk)
        shutil.copy2(args.db, backup)
        print(f"backup {backup.name}")
    if not has_col:
        con.execute("ALTER TABLE players ADD COLUMN game_face_path TEXT")
    con.executemany("UPDATE players SET game_face_path=? WHERE id=?", updates)
    con.commit()
    print(f"wrote game_face_path for {len(updates):,} players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
