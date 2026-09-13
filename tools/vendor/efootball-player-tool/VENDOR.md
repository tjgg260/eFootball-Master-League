# Vendored: eFootball Player Editor (container code)

Source: the eFootball Player Editor's repository (`cpk.py` last changed there 2026-09-07). The
file hashes below identify exactly what was copied.
Licence here: GPL-3.0, granted by the editor's author (upstream carries no licence file)
Vendored: 2026-09-14

## Files

| File | Why |
|---|---|
| `cpk.py` | CRI CPK reader and in-place patcher: `@UTF` de-obfuscation, TOC parsing, CRILAYLA decompression, `Cpk.patch` (in place, else into a gap, else appended; only that file's TOC row changes). |
| `iostore.py` | UE IoStore (`.utoc`/`.ucas`, TOC v2, Zlib, AES) reader and Texture2D decoder. Used by `tools/game_faces.py` for the player thumbnails in `pak\pc1000_console_win`. Copied from the editor's `scratch/iostore.py` (untracked upstream, file dated 2026-09-13), sha256 `b6f96bbe08530210706c838c78808f63140e94bdc2a1b0a53f26f96188529427`. Needs Pillow and pycryptodome. The container map is upstream `docs/PAK_MAP_ZH.md`. |

Copied verbatim, unmodified (sha256 `512280d9454dc0b521737774523187554a7e9b4eab6c6c05215c18cfd1e8da34`
as copied, CRLF). Do not edit it in place: fix it in the editor and re-pull, so the diff stays
visible. Its comments are in Chinese, as upstream.

The repo talks to it only through `tools/cpk_patch.py`, which adds the gates this project
requires (TOC round-trip proof before an edit, full read-back verification after it).

## What it replaced

- **CRI File System Tools (`cpkmakec.exe`)**: every deploy used to rebuild the whole dt200 from
  an extracted tree. A patch keeps the base archive's header, alignment and untouched files
  byte-identical, so the wrong-alignment failure cannot happen.
- **cricodecs** (pip): every CPK read.
- **eFootball WESYS Unzlib Tool**: extracting tables. `python tools/cpk_patch.py extract` does
  it straight from the archive.

The editor's own `wesys.py` is not vendored: WESYS decrypt/encrypt stays with Sider
(`tools/vendor/sider/`), whose round-trip proof the writeback already rests on.

## Optional speed-up

`cpk.py` tries `import efootball_native` (the editor's Rust extension, built from its
`native/` directory) and falls back to the pure-Python reference code it carries. Nothing here
needs it. Dropping `efootball_native.pyd` into this directory makes CRILAYLA decompression and
TOC de-obfuscation faster; do not commit the binary.
