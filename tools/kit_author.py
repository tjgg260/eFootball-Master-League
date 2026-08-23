#!/usr/bin/env python3
"""Author kit descriptor bins for a team as raw plaintext dt200 payloads.

Writes <id>_DEF_1st.bin, <id>_DEF_2nd.bin and <id>_DEF_GK1st.bin into
<out>/common/etc/uniform/team/<id>/ (default out: build/tree_base). Payloads
are RAW PLAINTEXT 92-byte descriptors -- the shipped-and-accepted vanilla
pattern (51 teams ship that way), so no cipher and no zlib are involved and
the kit_codec --prove gate covers everything this tool can emit.

Safe defaults (header bytes, design id, enum/pair, the undeciphered opaque
block, name/number placement floats) are cloned from a donor: team 173's
shipped plaintext trio, embedded below and re-verified through
kit_codec.parse() on every run. Only colors and texture refs are changed.

Colors: --colors RRGGBB[,RRGGBB,RRGGBB,RRGGBB,RRGGBB] in descriptor order
shirt,trim,shorts,socks,trim2 (missing entries auto-filled). The 2nd kit is
auto-derived (darkened for light shirts, inverted for dark ones) unless
--colors2 is given; GK likewise unless --gk-colors. --from-logo derives the
five colors from an image's dominant palette instead of --colors.

Texture refs name pak-side texture sets (T_<ref>_Uni_D/N/M). Cross-team reuse
is a shipped pattern; the default donor refs (u6058p1/p2/g1) always exist.
Pass --ref/--gk-ref only for refs known to exist in the installed paks.

This tool only writes descriptor files into the working tree. It never
rebuilds a CPK and never touches the game install.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_codec
from kit_codec import KitDescriptor, Rgb

# --------------------------------------------------------------------------
# Donor: team 173's shipped plaintext descriptors (bins-evomod-full
# common/etc/uniform/team/173/, byte-identical in build/tree_base).
# Verified against the shipped files 2026-08-23; design 01, u-namespace refs.
# --------------------------------------------------------------------------

DONOR_1ST = bytes.fromhex(
    "01903e017ec3e6e8eaedd3e2ebd3e2eb7ec3e60a8080291ed0b20003224d5c74"
    "c545571e26810002002022222222f2acce0000009a9949416666264114ae8141"
    "5c8f7b4266e6b2429a99814175363035387031000000000000000000"
)
DONOR_2ND = bytes.fromhex(
    "01903e01191919f1d2631919191919191919190a8080291ed0b20003224d5c74"
    "c545571e26810002002022222222f2acce0000009a9949416666264114ae8141"
    "5c8f7b4266e6b2429a99814175363035387032000000000000000000"
)
DONOR_GK = bytes.fromhex(
    "01903e0109c59e065b3a09c59e09c59e09c59e0a0101291ed0b20003224d9c74"
    "ca4da71e27810002002022222222f2acce00000066664641666626410000a041"
    "33337942cdccae429a99a14175363035386731000000000000000000"
)


def _donor(raw: bytes, expect_ref: str) -> KitDescriptor:
    desc = kit_codec.parse(raw)
    if kit_codec.serialize(desc) != raw or desc.texture_ref != expect_ref:
        raise RuntimeError(f"embedded donor bytes corrupt (expected ref {expect_ref})")
    return desc


# --------------------------------------------------------------------------
# Color helpers
# --------------------------------------------------------------------------

def parse_hex_color(text: str) -> Rgb:
    t = text.strip().lstrip("#")
    if len(t) != 6:
        raise ValueError(f"color must be RRGGBB hex, got {text!r}")
    return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))


def _luma(c: Rgb) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _dist(a: Rgb, b: Rgb) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _scale(c: Rgb, f: float) -> Rgb:
    return tuple(max(0, min(255, round(v * f))) for v in c)  # type: ignore[return-value]


def _invert(c: Rgb) -> Rgb:
    return (255 - c[0], 255 - c[1], 255 - c[2])


def _contrast_of(c: Rgb) -> Rgb:
    return (26, 26, 26) if _luma(c) >= 128 else (240, 240, 240)


Kit = tuple[Rgb, Rgb, Rgb, Rgb, Rgb]  # shirt, trim, shorts, socks, trim2


def expand_colors(given: list[Rgb]) -> Kit:
    """Fill a partial color list to the full 5-tuple (shirt,trim,shorts,socks,trim2)."""
    if not 1 <= len(given) <= 5:
        raise ValueError("--colors takes 1 to 5 RRGGBB values")
    shirt = given[0]
    trim = given[1] if len(given) > 1 else _contrast_of(shirt)
    shorts = given[2] if len(given) > 2 else shirt
    socks = given[3] if len(given) > 3 else shirt
    trim2 = given[4] if len(given) > 4 else trim
    return (shirt, trim, shorts, socks, trim2)


def derive_second(first: Kit) -> Kit:
    """Auto 2nd kit: darken a light 1st kit, invert a dark one."""
    if _luma(first[0]) > 96:
        return tuple(_scale(c, 0.35) for c in first)  # type: ignore[return-value]
    return tuple(_invert(c) for c in first)  # type: ignore[return-value]


def derive_gk(first: Kit, second: Kit) -> Kit:
    """Auto GK kit: a shirt visibly distinct from both outfield shirts."""
    gk_shirt = _invert(first[0])
    if min(_dist(gk_shirt, first[0]), _dist(gk_shirt, second[0])) < 90:
        r, g, b = gk_shirt
        gk_shirt = (g, b, r)  # rotate channels to break the clash
    trim = _contrast_of(gk_shirt)
    return (gk_shirt, trim, gk_shirt, gk_shirt, trim)


def colors_from_logo(path: Path, count: int = 5) -> list[Rgb]:
    """Dominant-palette extraction: shirt=dominant, trim=second, rest sensible."""
    from PIL import Image  # optional dependency, only for --from-logo

    img = Image.open(path).convert("RGBA")
    img.thumbnail((256, 256))
    raw = img.tobytes()
    opaque = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 4) if raw[i + 3] >= 128]
    if not opaque:
        raise ValueError(f"{path}: no opaque pixels to sample")
    strip = Image.new("RGB", (len(opaque), 1))
    strip.putdata(opaque)
    quant = strip.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette()
    ranked = sorted(quant.getcolors() or [], reverse=True)  # [(count, index)]
    candidates: list[Rgb] = []
    for n, idx in ranked:
        rgb: Rgb = tuple(palette[idx * 3: idx * 3 + 3])  # type: ignore[assignment]
        if n < len(opaque) * 0.02:
            continue  # noise
        if min(rgb) > 240 and candidates:
            continue  # near-white: background/highlight unless it is all there is
        if all(_dist(rgb, c) > 40 for c in candidates):
            candidates.append(rgb)
    if not candidates:
        candidates = [tuple(palette[ranked[0][1] * 3: ranked[0][1] * 3 + 3])]  # type: ignore[list-item]
    shirt = candidates[0]
    trim = candidates[1] if len(candidates) > 1 else _contrast_of(shirt)
    shorts = candidates[2] if len(candidates) > 2 else _scale(shirt, 0.6)
    return [shirt, trim, shorts, shirt, trim][:count]


def colors_from_seed(seed: int | str) -> list[Rgb]:
    """Deterministic two-color fallback for a club with no usable logo.

    Hashes the club's stable id so the same club always renders the same
    (arbitrary but consistent) pair; the trim is forced to a contrasting
    tone when the hash lands both colors too close to tell apart.
    """
    import hashlib

    h = hashlib.sha1(str(seed).encode("utf-8")).digest()
    shirt: Rgb = (h[0], h[1], h[2])
    trim: Rgb = (h[3], h[4], h[5])
    if _dist(shirt, trim) < 90:
        trim = _contrast_of(shirt)
    return [shirt, trim]


# --------------------------------------------------------------------------
# Authoring
# --------------------------------------------------------------------------

def _make(donor: KitDescriptor, colors: Kit, ref: str) -> bytes:
    desc = KitDescriptor(
        header=donor.header,
        design_id=donor.design_id,
        shirt_rgb=colors[0],
        trim_rgb=colors[1],
        shorts_rgb=colors[2],
        socks_rgb=colors[3],
        trim2_rgb=colors[4],
        enum13=donor.enum13,
        pair14=donor.pair14,
        opaque_16_33=donor.opaque_16_33,
        placement=donor.placement,
        texture_ref=ref,
        tail=donor.tail,
    )
    payload = kit_codec.serialize(desc)
    if kit_codec.serialize(kit_codec.parse(payload)) != payload:
        raise RuntimeError("authored payload failed its own round-trip")  # pragma: no cover
    return kit_codec.write_plain(payload)


def author_team_kits(
    team: int,
    first: Kit,
    second: Kit | None,
    gk: Kit | None,
    ref: str | None,
    gk_ref: str | None,
    out_root: Path,
    force: bool = False,
    quiet: bool = False,
) -> list[Path]:
    d1 = _donor(DONOR_1ST, "u6058p1")
    d2 = _donor(DONOR_2ND, "u6058p2")
    dg = _donor(DONOR_GK, "u6058g1")

    second = second or derive_second(first)
    gk = gk or derive_gk(first, second)

    ref1 = ref or d1.texture_ref
    ref2 = (ref1[:-1] + "2") if ref1.endswith("p1") else (d2.texture_ref if ref is None else ref1)
    refg = gk_ref or ((ref1[:-2] + "g1") if (ref and ref1.endswith("p1")) else dg.texture_ref)

    team_dir = out_root / "common" / "etc" / "uniform" / "team" / str(team)
    team_dir.mkdir(parents=True, exist_ok=True)

    plan = [
        (team_dir / f"{team}_DEF_1st.bin", _make(d1, first, ref1), first, ref1),
        (team_dir / f"{team}_DEF_2nd.bin", _make(d2, second, ref2), second, ref2),
        (team_dir / f"{team}_DEF_GK1st.bin", _make(dg, gk, refg), gk, refg),
    ]
    clobber = [p for p, *_ in plan if p.exists()]
    if clobber and not force:
        names = ", ".join(p.name for p in clobber)
        raise SystemExit(f"refusing to overwrite existing {names} (pass --force to replace)")

    written = []
    for path, data, colors, r in plan:
        path.write_bytes(data)
        if not quiet:
            cols = "/".join(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" for c in colors)
            print(f"wrote {path}  [{len(data)}B plaintext]  ref={r}  {cols}")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--team", type=int, required=True, help="team id (dt200 Team.bin slot)")
    ap.add_argument("--colors", help="1st kit: 1-5 x RRGGBB (shirt,trim,shorts,socks,trim2)")
    ap.add_argument("--colors2", help="2nd kit colors (default: auto-darkened/inverted 1st)")
    ap.add_argument("--gk-colors", help="GK kit colors (default: auto-derived, high contrast)")
    ap.add_argument("--from-logo", type=Path, metavar="IMAGE",
                    help="derive 1st-kit colors from a webp/png logo's dominant palette")
    ap.add_argument("--ref", help="outfield texture-set ref, e.g. u0101p1 (default: donor u6058p1)")
    ap.add_argument("--gk-ref", help="GK texture-set ref, e.g. u0101g1 (default follows --ref)")
    ap.add_argument("--out", type=Path, default=kit_codec.REPO_ROOT / "build" / "tree_base",
                    help="tree root to write into (default: build/tree_base)")
    ap.add_argument("--force", action="store_true", help="overwrite existing descriptor files")
    args = ap.parse_args(argv)

    if bool(args.colors) == bool(args.from_logo):
        ap.error("give exactly one of --colors or --from-logo")

    if args.from_logo:
        given = colors_from_logo(args.from_logo)
        print("palette from", args.from_logo, "->",
              ", ".join(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" for c in given))
    else:
        given = [parse_hex_color(c) for c in args.colors.split(",")]
    first = expand_colors(given)
    second = expand_colors([parse_hex_color(c) for c in args.colors2.split(",")]) if args.colors2 else None
    gk = expand_colors([parse_hex_color(c) for c in args.gk_colors.split(",")]) if args.gk_colors else None

    author_team_kits(args.team, first, second, gk, args.ref, args.gk_ref, args.out, args.force)
    print("done -- descriptors staged in the tree only; no CPK rebuild, no install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
