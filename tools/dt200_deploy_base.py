"""Deploy the modified build/tree_base into the game's dt200 CPK — a permanent base edit.

After dt200_rename.py has written corrected team names + league order into build/tree_base,
this patches every file of the tree that differs from the base dt200 into a copy of it
(tools/cpk_patch.py — no full rebuild, the base's header and alignment are kept) and installs it,
so the names are right in eFootball's own menus without running our app.
Reuses play_match's proven rebuild_and_install (patch guard + backup + sha tracking).

Close eFootball first. Usage: python tools/dt200_deploy_base.py [--build-only]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import play_match as pm


def main() -> int:
    install = "--build-only" not in sys.argv
    out = pm.REPO / "build" / "dt200_console_all.cpk"
    if not (pm.TREE_BASE / "common/etc/pesdb/Team.bin").exists():
        sys.exit("build/tree_base not found — run the rebaseline + dt200_rename first.")
    print(f"patching dt200 from {pm.TREE_BASE} (install={install})")
    pm.rebuild_and_install(pm.TREE_BASE, out, install)
    if install:
        print("done — team names are now corrected in the game's own menus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
