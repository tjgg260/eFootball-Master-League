#!/usr/bin/env python3
"""Kit descriptor codec for eFootball dt200 uniform config bins.

Handles ``common/etc/uniform/team/<teamId>/<teamId>_*_1st|2nd|GK1st[_realUni].bin``.

Two payload species exist inside three container variants:

* 92-byte texture-ref descriptor (fully decoded here as :class:`KitDescriptor`)
* 96-byte parametric editor-config (opaque passthrough -- container decode only)

Container variants (byte 2 of the ``ff 2x`` WESYS header):

* ``0x83`` -- WESYS zlib: XOR keystream over a zlib stream. Decoded via the
  vendored Sider ``wesys.py`` (tools/vendor/sider).
* ``0x02`` -- WESYS stored: XOR keystream only, NO zlib (flag bit 0x80 clear).
  The vendored ``unpack_wesys_payload`` raises on these (it insists the
  current-format payload must inflate), so this module carries its own
  keystream implementation (same xorshift cipher, studied from the vendored
  file -- the vendored file itself is untouched).
* raw plaintext -- 51 vanilla teams ship bare 92-byte payloads; the game
  accepts them, which is why :func:`write_plain` emits plaintext.

THE GATE: ``python tools/kit_codec.py --prove`` decodes every shipped team
descriptor and asserts ``serialize(parse(payload)) == payload`` byte-exact for
every 92-byte payload. No write tooling is to be trusted until it prints
PROVEN (see CLAUDE.md round-trip rule; payload-level proof per the
kits-logos-evomod memory note -- Konami's deflate is not reproducible, the
payload bytes are).
"""

from __future__ import annotations

import argparse
import importlib.util
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEAM_ROOT = REPO_ROOT / "bins-evomod-full" / "common" / "etc" / "uniform" / "team"

PAYLOAD_TEXREF = 92    # decoded descriptor
PAYLOAD_EDITCFG = 96   # parametric editor config, opaque passthrough


class KitFormatError(ValueError):
    """Raised when a kit bin does not match the proven format."""


# --------------------------------------------------------------------------
# Vendored Sider wesys module (zlib containers only -- do not edit in place)
# --------------------------------------------------------------------------

def _load_vendored_wesys():
    path = REPO_ROOT / "tools" / "vendor" / "sider" / "wesys.py"
    spec = importlib.util.spec_from_file_location("_sider_wesys", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_wesys = _load_vendored_wesys()


# --------------------------------------------------------------------------
# Own cipher for the stored (0x02) variant.
#
# Same current-format xorshift keystream the vendored code uses for the zlib
# variant; reimplemented here because the vendored unpack refuses a payload
# that does not inflate. Keystream seed folds both sizes from the header:
# w = (original_size << 16) | compressed_size. Symmetric (XOR), so the same
# function encrypts.
# --------------------------------------------------------------------------

_CURRENT_KEYS = {
    1: (0x168EA000, 0x2E2AA6F2, 0x0CC8DCD3),
    2: (0xED5B2960, 0x4A523B4E, 0xF3A31BAD),
}


def crypt_current(payload: bytes, key_nibble: int, compressed_size: int, original_size: int) -> bytes:
    """XOR the current-format WESYS keystream over payload (decrypt == encrypt)."""
    try:
        x, y, z = _CURRENT_KEYS[key_nibble]
    except KeyError as exc:
        raise KitFormatError(f"unsupported WESYS key nibble {key_nibble}") from exc
    out = bytearray(payload)
    w = ((original_size << 16) | compressed_size) & 0xFFFFFFFF
    for off in range(0, len(out) - len(out) % 4, 4):
        t = (x ^ (x << 11)) & 0xFFFFFFFF
        x, y, z = y, z, w
        w = (w ^ (((w >> 11) ^ t) >> 8) ^ t) & 0xFFFFFFFF
        struct.pack_into("<I", out, off, struct.unpack_from("<I", out, off)[0] ^ w)
    return bytes(out)


# --------------------------------------------------------------------------
# Container layer
# --------------------------------------------------------------------------

def classify_container(data: bytes) -> str:
    """'plain', 'zlib' (WESYS 0x83) or 'stored' (WESYS 0x02)."""
    if len(data) >= 16 and data[0] == 0xFF and data[3:8] == b"WESYS":
        return "zlib" if data[2] & 0x80 else "stored"
    return "plain"


def decode_container(data: bytes) -> tuple[str, bytes]:
    """Return (family, payload) for any of the three shipped container variants."""
    family = classify_container(data)
    if family == "plain":
        return family, data
    compressed_size, original_size = struct.unpack_from("<II", data, 8)
    if family == "stored":
        payload = data[16:]
        if not (compressed_size == original_size == len(payload)):
            raise KitFormatError(
                f"stored WESYS size mismatch: header ({compressed_size}, {original_size}) "
                f"vs payload {len(payload)}"
            )
        return family, crypt_current(payload, data[1] & 0x0F, compressed_size, original_size)
    # zlib: vendored Sider path (it verifies decoded size against the header)
    return family, _wesys.unpack_wesys_payload(data)


def read_bin(path: Path | str) -> bytes:
    """Read a kit bin and return its decoded payload, whatever the container."""
    return decode_container(Path(path).read_bytes())[1]


def write_plain(payload: bytes) -> bytes:
    """Container-encode a payload as raw plaintext (the shipped vanilla pattern).

    Identity on bytes by design: 51 vanilla teams ship bare payloads and the
    game accepts them, so plaintext is the write path -- no cipher, no zlib,
    nothing for a round-trip gate to disprove.
    """
    if len(payload) not in (PAYLOAD_TEXREF, PAYLOAD_EDITCFG):
        raise KitFormatError(f"refusing to emit unknown payload size {len(payload)}")
    return bytes(payload)


# --------------------------------------------------------------------------
# 92-byte texture-ref descriptor
# --------------------------------------------------------------------------

Rgb = tuple[int, int, int]

_OPAQUE_START, _OPAQUE_END = 0x16, 0x34   # kept verbatim, meaning unknown
_FLOATS_OFF, _REF_OFF, _TAIL_OFF = 0x34, 0x4C, 0x58
_REF_LEN = 12


@dataclass
class KitDescriptor:
    """Decoded 92-byte kit descriptor payload.

    Field map proven byte-exact over all 1,242 shipped 92-byte payloads
    (see --prove). Regions whose meaning is unknown are carried as raw bytes
    so serialization can never drift.
    """

    header: bytes            # 0x00-0x02 (3 bytes; 01 90 3e|3f|bb, 01 a0 3e observed)
    design_id: int           # 0x03 (1..18 observed)
    shirt_rgb: Rgb           # 0x04-0x06
    trim_rgb: Rgb            # 0x07-0x09
    shorts_rgb: Rgb          # 0x0a-0x0c
    socks_rgb: Rgb           # 0x0d-0x0f
    trim2_rgb: Rgb           # 0x10-0x12
    enum13: int              # 0x13 (2..10 observed)
    pair14: tuple[int, int]  # 0x14-0x15 (usually equal bytes, e.g. 01 01)
    opaque_16_33: bytes      # 0x16-0x33 (30 bytes, verbatim -- undeciphered)
    placement: tuple[float, float, float, float, float, float]
    #                        # 0x34-0x4b six float32: name/number placement
    texture_ref: str         # 0x4c 12-byte NUL-padded ascii ("u0101p1", "...g1")
    tail: bytes              # 0x58-0x5b (4 bytes, all zero in every shipped file)

    @property
    def colors(self) -> tuple[Rgb, Rgb, Rgb, Rgb, Rgb]:
        return (self.shirt_rgb, self.trim_rgb, self.shorts_rgb, self.socks_rgb, self.trim2_rgb)


def _rgb(payload: bytes, off: int) -> Rgb:
    return (payload[off], payload[off + 1], payload[off + 2])


def parse(payload: bytes) -> KitDescriptor:
    """Decode a 92-byte descriptor payload. Raises KitFormatError if any decoded
    field could not re-serialize byte-exactly (never happens on shipped data)."""
    if len(payload) != PAYLOAD_TEXREF:
        raise KitFormatError(f"descriptor payload must be {PAYLOAD_TEXREF} bytes, got {len(payload)}")

    float_raw = payload[_FLOATS_OFF:_REF_OFF]
    placement = struct.unpack("<6f", float_raw)
    if struct.pack("<6f", *placement) != float_raw:
        raise KitFormatError("float32 region does not repack byte-exactly; keep as opaque bytes")

    ref_raw = payload[_REF_OFF:_REF_OFF + _REF_LEN]
    ref = ref_raw.split(b"\x00", 1)[0]
    if not ref.isascii() or ref_raw != ref + b"\x00" * (_REF_LEN - len(ref)):
        raise KitFormatError(f"texture ref field is not cleanly NUL-padded ascii: {ref_raw.hex()}")

    desc = KitDescriptor(
        header=payload[0:3],
        design_id=payload[3],
        shirt_rgb=_rgb(payload, 0x04),
        trim_rgb=_rgb(payload, 0x07),
        shorts_rgb=_rgb(payload, 0x0A),
        socks_rgb=_rgb(payload, 0x0D),
        trim2_rgb=_rgb(payload, 0x10),
        enum13=payload[0x13],
        pair14=(payload[0x14], payload[0x15]),
        opaque_16_33=payload[_OPAQUE_START:_OPAQUE_END],
        placement=placement,
        texture_ref=ref.decode("ascii"),
        tail=payload[_TAIL_OFF:],
    )
    return desc


def serialize(desc: KitDescriptor) -> bytes:
    """Re-emit the 92-byte payload. serialize(parse(p)) == p, byte-exact."""
    if len(desc.header) != 3:
        raise KitFormatError("header must be exactly 3 bytes")
    if len(desc.opaque_16_33) != _OPAQUE_END - _OPAQUE_START:
        raise KitFormatError("opaque_16_33 must be exactly 30 bytes")
    if len(desc.tail) != PAYLOAD_TEXREF - _TAIL_OFF:
        raise KitFormatError("tail must be exactly 4 bytes")
    ref = desc.texture_ref.encode("ascii")
    if len(ref) > _REF_LEN or b"\x00" in ref:
        raise KitFormatError(f"texture ref too long or contains NUL: {desc.texture_ref!r}")

    out = bytearray()
    out += desc.header
    out.append(desc.design_id)
    for rgb in desc.colors:
        out += bytes(rgb)
    out.append(desc.enum13)
    out += bytes(desc.pair14)
    out += desc.opaque_16_33
    out += struct.pack("<6f", *desc.placement)
    out += ref.ljust(_REF_LEN, b"\x00")
    out += desc.tail
    if len(out) != PAYLOAD_TEXREF:
        raise KitFormatError(f"serializer produced {len(out)} bytes")  # pragma: no cover
    return bytes(out)


# --------------------------------------------------------------------------
# THE GATE
# --------------------------------------------------------------------------

def iter_team_bins(root: Path):
    """Every *.bin directly under a numeric <teamId>/ dir. Non-team files
    (UniNameFontPermissions.bin, UniColor.bin, RefereeColor.bin, referee/...)
    are skipped by construction."""
    for team_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if team_dir.is_dir() and team_dir.name.isdigit():
            yield from sorted(team_dir.glob("*.bin"))


def prove(root: Path) -> bool:
    families: Counter = Counter()
    proven = 0
    opaque = 0
    failures: list[str] = []

    files = list(iter_team_bins(root))
    for f in files:
        try:
            family, payload = decode_container(f.read_bytes())
        except Exception as exc:  # container decode itself is part of the gate
            failures.append(f"{f}: container decode failed: {exc}")
            continue
        families[(family, len(payload))] += 1
        if len(payload) == PAYLOAD_TEXREF:
            try:
                if serialize(parse(payload)) == payload:
                    proven += 1
                else:
                    failures.append(f"{f}: round-trip not byte-exact")
            except Exception as exc:
                failures.append(f"{f}: parse failed: {exc}")
        elif len(payload) == PAYLOAD_EDITCFG:
            opaque += 1  # editor-config: opaque passthrough, container proof only
        else:
            failures.append(f"{f}: unexpected payload size {len(payload)}")

    print(f"root: {root}")
    print(f"team descriptor bins: {len(files)}")
    print("families (container, payload bytes):")
    for (family, size), count in sorted(families.items()):
        note = "decoded KitDescriptor" if size == PAYLOAD_TEXREF else "opaque passthrough"
        print(f"  {family:>6} {size:>3}B : {count:>5}  ({note})")
    print(f"92B payloads round-tripped byte-exact : {proven}")
    print(f"96B payloads container-decoded (opaque): {opaque}")
    for line in failures[:20]:
        print("FAIL", line)
    if len(failures) > 20:
        print(f"... and {len(failures) - 20} more failures")

    ok = not failures and proven + opaque == len(files) and len(files) > 0
    tally = ", ".join(f"{fam}/{size}B={n}" for (fam, size), n in sorted(families.items()))
    if ok:
        print(f"PROVEN: {proven} descriptors byte-exact + {opaque} opaque containers decoded ({tally})")
    else:
        print(f"FAILED: {len(failures)} failures over {len(files)} files ({tally})")
    return ok


def _dump(path: Path) -> None:
    family, payload = decode_container(path.read_bytes())
    print(f"{path}  [{family}, {len(payload)}B payload]")
    if len(payload) != PAYLOAD_TEXREF:
        print("  editor-config payload (opaque):", payload.hex())
        return
    d = parse(payload)
    print(f"  header      {d.header.hex()}   design_id {d.design_id}")
    for name, rgb in zip(("shirt", "trim", "shorts", "socks", "trim2"), d.colors):
        print(f"  {name:<6} #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}")
    print(f"  enum13 {d.enum13}  pair14 {d.pair14}")
    print(f"  opaque      {d.opaque_16_33.hex()}")
    print(f"  placement   {[round(v, 3) for v in d.placement]}")
    print(f"  texture_ref {d.texture_ref!r}  tail {d.tail.hex()}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prove", action="store_true", help="run the byte-exact round-trip gate")
    ap.add_argument("--root", type=Path, default=DEFAULT_TEAM_ROOT,
                    help="uniform/team root to prove against (default: bins-evomod-full)")
    ap.add_argument("--dump", type=Path, metavar="BIN", help="decode and pretty-print one kit bin")
    args = ap.parse_args(argv)

    if args.dump:
        _dump(args.dump)
        return 0
    if args.prove:
        return 0 if prove(args.root) else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
