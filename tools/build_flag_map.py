#!/usr/bin/env python3
"""build_flag_map.py — emit assets/flag_map.json: lowercase nationality name ->
"assets/dvx_flags/<TRI>.webp".

The nationality->FIFA-trigram knowledge lives in ONE place (NAT2CODE in
tools/assign_uran_faces.py) and is imported, never copied. Only nationalities whose
flag file actually exists in assets/dvx_flags/ are emitted, so the app can treat any
hit in the map as a loadable image (no per-row File.Exists probing).

Keys are stored exactly as NAT2CODE keys them: lowercase, ascii-folded, apostrophes
already spaced ("cote divoire"). The app normalises the same way before lookup.

    python tools/build_flag_map.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from assign_uran_faces import NAT2CODE  # noqa: E402  (single source of truth)

FLAGS = REPO / "assets" / "dvx_flags"
OUT = REPO / "assets" / "flag_map.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not FLAGS.is_dir():
        sys.exit(f"flag dir not found: {FLAGS}")

    mapping: dict[str, str] = {}
    missing: set[str] = set()
    for nat, code in NAT2CODE.items():
        if (FLAGS / f"{code}.webp").is_file():
            mapping[nat] = f"assets/dvx_flags/{code}.webp"
        else:
            missing.add(code)

    OUT.write_text(
        json.dumps(mapping, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(REPO).as_posix()}: "
          f"{len(mapping)} nationalities -> {len(set(mapping.values()))} flag files; "
          f"{len(missing)} trigrams have no flag in assets/dvx_flags "
          f"({', '.join(sorted(missing)[:12])}{'…' if len(missing) > 12 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
