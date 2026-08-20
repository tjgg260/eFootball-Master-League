"""Re-baseline dt200 after the game's copy legitimately changed (Konami patch or EvoMod).

The patch guard in play_match.py refuses to install over a dt200 it doesn't recognise.
When the change is LEGITIMATE (you ran the Konami updater and/or EvoMod and the game boots
clean), this tool makes the game's current file our new base:

  1. back up the old repo base + tree_base
  2. copy the game's dt200_console_all.cpk over the repo copy
  3. re-extract build/tree_base from it
  4. sanity-check the tree (key pesdb files present, file count plausible)

Run ONLY after you've confirmed the game boots clean with its current dt200.

Usage: python tools/rebaseline.py
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAME_DT200 = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk\dt200_console_all.cpk")
REPO_BASE = REPO / "dt200_console_all.cpk"
TREE_BASE = REPO / "build" / "tree_base"
BACKUPS = REPO / "build" / "backups"

MUST_EXIST = [
    "common/etc/pesdb/Player.bin",
    "common/etc/pesdb/Team.bin",
    "common/etc/pesdb/PlayerAssignment.bin",
    "common/etc/pesdb/Derby.bin",
    "common/etc/appearance/PlayerAppearance.bin",
]


def main() -> int:
    if not GAME_DT200.exists():
        sys.exit(f"game file not found: {GAME_DT200}")

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    BACKUPS.mkdir(parents=True, exist_ok=True)

    if REPO_BASE.exists():
        keep = BACKUPS / f"dt200_base.{stamp}.cpk"
        shutil.copy2(REPO_BASE, keep)
        print(f"backed up old base -> {keep.name}")
    if TREE_BASE.exists():
        keep_tree = TREE_BASE.with_name(f"tree_base.{stamp}.old")
        TREE_BASE.rename(keep_tree)
        print(f"kept old tree     -> {keep_tree.name}")

    shutil.copy2(GAME_DT200, REPO_BASE)
    print(f"new base: {REPO_BASE.name} ({REPO_BASE.stat().st_size:,} bytes, from the game dir)")

    from cricodecs import cpk
    c = cpk.load(str(REPO_BASE))
    n = 0
    for i, e in enumerate(c.files):
        rel = e.full_path.lstrip("/")
        out = TREE_BASE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(c.file_bytes(i))
        n += 1
    print(f"extracted {n} files into {TREE_BASE.relative_to(REPO)}")

    missing = [f for f in MUST_EXIST if not (TREE_BASE / f).exists()]
    if missing:
        sys.exit("SANITY FAIL — missing from the new tree: " + ", ".join(missing) +
                 "\nThe old tree was kept beside it; nothing else was touched.")
    if n < 100:
        sys.exit(f"SANITY FAIL — only {n} files extracted; that is not a full dt200.")
    print("sanity OK — key pesdb files present.")
    print("Re-baseline complete. Compile again from the app (Play Match).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
