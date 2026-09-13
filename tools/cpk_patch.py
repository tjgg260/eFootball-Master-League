#!/usr/bin/env python3
"""
cpk_patch.py — read eFootball's CRI CPK archives and patch files into them, without a rebuild.

This replaces both external CPK dependencies the pipeline used to have:
  - cpkmakec.exe (CRI File System Tools), which rebuilt the whole dt200 from an extracted tree
  - cricodecs (pip), which read files out of an archive
The container code is the eFootball Player Editor's own `cpk.py`, vendored verbatim in
tools/vendor/efootball-player-tool/ (see VENDOR.md). WESYS decrypt/encrypt stays with Sider.

Why patch instead of rebuild
    `Cpk.patch` replaces ONE file and leaves every other byte of the archive alone:
      1. the new bytes fit the old slot (plus slack before the next file) -> overwritten in place
      2. they fit a gap elsewhere (e.g. a slot an earlier patch vacated) -> moved there
      3. neither                                                          -> appended at the end
    In cases 2 and 3 only the file's TOC row (FileOffset / FileSize / ExtractSize) changes; the
    header, the alignment and every other file keep their bytes. Case 3 is proven in-game by the
    editor (2026-09-07): Player.bin repacked at zlib 6 no longer fits, moves to the end, dt200
    grows once from 19.7 to 24.2 MB, and the game boots and reads it.

    What it cannot do is ADD a file: the TOC has a fixed row count. A tree file that the archive
    does not already carry is refused, never silently dropped.

Gates (nothing is written unless both pass)
    - before: the TOC must re-serialise byte-exact from its parsed form (prove_toc_round_trip).
      If it cannot, we do not understand this archive well enough to edit its TOC.
    - after: the output is re-parsed; every patched file reads back as the bytes we meant, every
      other file's stored bytes are identical to the base, and the alignment is unchanged.

Usage
    python tools/cpk_patch.py list    <cpk> [--grep pesdb]
    python tools/cpk_patch.py extract <cpk> <out_dir>
    python tools/cpk_patch.py build   --base <cpk> --tree <dir> --out <cpk>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor" / "efootball-player-tool"
sys.path.insert(0, str(VENDOR))
import cpk as _cpk  # noqa: E402


class CpkPatchError(Exception):
    pass


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").lower()


def load(path: Path | str) -> _cpk.Cpk:
    return _cpk.open_cpk(str(path))


def find(archive: _cpk.Cpk, suffix: str) -> _cpk.CpkFile | None:
    """The first entry whose path ends with `suffix` at a path boundary. Case-insensitive,
    either slash direction: "Player.bin" and "common/etc/pesdb/Player.bin" both match."""
    want = _norm(suffix)
    for f in archive.files:
        p = _norm(f.path)
        if p == want or p.endswith("/" + want):
            return f
    return None


def read(archive: _cpk.Cpk, suffix: str) -> bytes | None:
    """A file's content (CRILAYLA-decompressed when a third-party repack compressed it)."""
    f = find(archive, suffix)
    return None if f is None else archive.read(f.path)


def extract(cpk_path: Path | str, out_dir: Path | str) -> int:
    archive = load(cpk_path)
    out_dir = Path(out_dir)
    for f in archive.files:
        target = out_dir / f.path.replace("\\", "/").lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(f.path))
    return len(archive.files)


def prove_toc_round_trip(archive: _cpk.Cpk) -> None:
    # Reaches into the vendored parser's private fields on purpose: this is the one question we
    # need answered before a TOC edit, and the parser keeps the answer there.
    original = bytes(archive.data[archive._toc_off:archive._toc_off + archive._toc_len])
    if archive._toc_tbl.to_bytes() != original:
        raise CpkPatchError("TOC does not re-serialise byte-exact - refusing to edit this archive")


def tree_changes(archive: _cpk.Cpk, tree: Path) -> dict[str, bytes]:
    """Every file under `tree` whose bytes differ from the archive's copy, keyed by archive path.

    Stray `.bak` files are skipped. Any other file the archive does not carry is an error: the
    TOC cannot grow, and dropping it silently would ship a build missing an edit."""
    by_norm = {_norm(f.path): f.path for f in archive.files}
    changes: dict[str, bytes] = {}
    unknown: list[str] = []
    for p in sorted(tree.rglob("*")):
        if not p.is_file() or p.suffix.lower() == ".bak":
            continue
        rel = p.relative_to(tree).as_posix()
        path = by_norm.get(_norm(rel))
        if path is None:
            unknown.append(rel)
            continue
        data = p.read_bytes()
        if data != archive.read(path):
            changes[path] = data
    if unknown:
        shown = "\n  ".join(unknown[:20])
        more = f"\n  ... and {len(unknown) - 20} more" if len(unknown) > 20 else ""
        raise CpkPatchError(f"{len(unknown)} file(s) in {tree} are not in the base archive, and a "
                            f"CPK patch cannot add files:\n  {shown}{more}")
    return changes


def patch_bytes(base: bytes, changes: dict[str, bytes]) -> bytes:
    """Apply `changes` to the archive bytes `base`, then verify. Returns the new archive bytes."""
    archive = _cpk.Cpk(base)
    prove_toc_round_trip(archive)
    missing = [p for p in changes if archive.get(p) is None]
    if missing:
        raise CpkPatchError(f"not in the archive: {', '.join(missing)}")

    data = bytes(base)
    for path in sorted(changes):
        # Re-parse every time: patch() returns new bytes but does not update the object it
        # was called on, and a move shifts where the next gap is.
        data, _offset = _cpk.Cpk(data).patch(path, changes[path])
    verify(base, data, changes)
    return data


def verify(base: bytes, out: bytes, changes: dict[str, bytes]) -> None:
    before, after = _cpk.Cpk(base), _cpk.Cpk(out)
    if [f.path for f in before.files] != [f.path for f in after.files]:
        raise CpkPatchError("file list changed")
    if before.align != after.align:
        raise CpkPatchError(f"alignment changed {before.align} -> {after.align}")
    for f in after.files:
        if f.path in changes:
            if after.read(f.path) != changes[f.path]:
                raise CpkPatchError(f"{f.path} does not read back as written")
        elif after.read_raw(f.path) != before.read_raw(f.path):
            raise CpkPatchError(f"{f.path} was not patched but its bytes changed")


def build(base_cpk: Path, tree: Path, out_cpk: Path) -> dict[str, int]:
    """Render `tree` into a copy of `base_cpk` by patching only the files that differ."""
    base = base_cpk.read_bytes()
    archive = _cpk.Cpk(base)
    prove_toc_round_trip(archive)
    changes = tree_changes(archive, tree)
    out = patch_bytes(base, changes) if changes else base
    out_cpk.parent.mkdir(parents=True, exist_ok=True)
    out_cpk.write_bytes(out)
    return {"files": len(archive.files), "patched": len(changes),
            "base_size": len(base), "out_size": len(out)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="list the files in an archive")
    p.add_argument("cpk")
    p.add_argument("--grep", default="")
    p = sub.add_parser("extract", help="extract every file into a directory tree")
    p.add_argument("cpk")
    p.add_argument("out_dir")
    p = sub.add_parser("build", help="patch the files that differ between a tree and a base archive")
    p.add_argument("--base", required=True)
    p.add_argument("--tree", required=True)
    p.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        if args.cmd == "list":
            archive = load(args.cpk)
            for f in archive.files:
                if args.grep.lower() in f.path.lower():
                    flag = " [CRILAYLA]" if f.compressed else ""
                    print(f"{f.offset:>12,}  {f.size:>12,}  {f.path}{flag}")
            print(f"{len(archive.files)} files, align={archive.align}")
        elif args.cmd == "extract":
            n = extract(args.cpk, args.out_dir)
            print(f"extracted {n} files into {args.out_dir}")
        else:
            r = build(Path(args.base), Path(args.tree), Path(args.out))
            print(f"built {args.out}: {r['patched']} of {r['files']} files patched, "
                  f"{r['base_size']:,} -> {r['out_size']:,} bytes")
    except CpkPatchError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
