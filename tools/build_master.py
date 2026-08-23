#!/usr/bin/env python3
"""
build_master.py — the blueprint's one-command world build (docs/database-blueprint.md). Runs the
pipeline stages in order and STOPS on the first failure; the validation gate at the end decides
whether the world is fit to play. Every stage is an idempotent tool that can also be run alone.

    python tools/build_master.py                 # full pipeline
    python tools/build_master.py --from derive   # resume from a stage
    python tools/build_master.py --list          # show the stages

Stages (blueprint build order — ingest happens before this, via the individual importers):
  identity   build_identity.py            the cross-source spine (exact keys forever)
  merge      merge_passes.py --apply      field priorities: eF names, DVX-first logos
             link_real_faces.py           real faces to every copy of a real player
             assign_uran_faces.py         generated portraits for everyone else
  derive     synth_attributes.py          attributes for rating-only players
             fill_squads.py               every club to 18+ with 2 GKs
             assign_staff.py --apply      staff placed at their FM clubs
             build_stadiums.py --apply    grounds + capacities
             build_competitions.py --apply  pyramid links + cups
  clean      cleanup_db.py                ghosts, ages, memberships, collisions
             dedup_players.py             orphaned cross-source duplicates
  validate   validate_db.py               THE GATE — non-zero exit fails the build
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

STAGES: list[tuple[str, list[list[str]]]] = [
    ("identity", [["build_identity.py"]]),
    ("merge", [["merge_passes.py", "--apply"],
               ["link_real_faces.py"],
               ["assign_uran_faces.py"]]),
    ("derive", [["synth_attributes.py"],
                ["fill_squads.py"],
                ["assign_staff.py", "--apply"],
                ["build_stadiums.py", "--apply"],
                ["build_competitions.py", "--apply"]]),
    ("clean", [["cleanup_db.py"],
               ["dedup_players.py"]]),
    ("validate", [["validate_db.py"]]),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--list" in sys.argv:
        for name, cmds in STAGES:
            print(f"{name}: " + " ; ".join(" ".join(c) for c in cmds))
        return 0
    start = 0
    if "--from" in sys.argv:
        want = sys.argv[sys.argv.index("--from") + 1]
        start = next((i for i, (n, _) in enumerate(STAGES) if n == want), 0)
    for name, cmds in STAGES[start:]:
        print(f"\n━━━ stage: {name} ━━━")
        for cmd in cmds:
            script = TOOLS / cmd[0]
            if not script.exists():
                print(f"  !! {cmd[0]} missing — stage incomplete, stopping")
                return 1
            print(f"  ▶ {' '.join(cmd)}")
            r = subprocess.run([sys.executable, str(script), *cmd[1:]],
                               env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"})
            if r.returncode != 0:
                print(f"  ✖ {cmd[0]} failed (exit {r.returncode}) — build stopped")
                return r.returncode
    print("\n✔ world built and validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
