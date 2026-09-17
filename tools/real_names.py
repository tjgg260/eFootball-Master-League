#!/usr/bin/env python3
"""
real_names.py — real club and competition names, written into OUR dt200 and read back from it.

eFootball ships the clubs it has no licence for under invented names ("Albacete BN") and a few
competitions under generic ones. tools/data/real_names.json holds the real names (how each was
identified is in its _about). This tool makes the dt200 we build from the single source of them:

  1. resolve the list against the snapshot (dt200_console_all.cpk): every entry must name exactly
     one Team.bin record, or nothing is written
  2. write build/dt200_renames.json + build/dt200_comp_renames.json and run tools/dt200_rename.py,
     which edits build/tree_base under its round-trip gates (Team.bin @396, all 21 language slots of
     CompetitionUnit.bin, the league lists re-sorted)
  3. patch the snapshot archive from that tree through cpk_patch's gates, so the dt200 the world is
     built from — and every Play Match starts from — carries the names
  4. read the names BACK out of the patched snapshot and bring the world (teams, leagues) and the
     New Career catalog into line IN PLACE: careers live in the same database, so it is never
     rebuilt for this

    python tools/real_names.py --dry      # resolve and report, write nothing
    python tools/real_names.py            # apply (close the app first)
    python tools/real_names.py --sync     # step 4 only: the world follows whatever our dt200 says
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import cpk_patch  # noqa: E402
import game_world as gw  # noqa: E402

NAMES = REPO / "tools" / "data" / "real_names.json"
SNAPSHOT = REPO / "dt200_console_all.cpk"
TREE = REPO / "build" / "tree_base"
WORLD = REPO / "build" / "game_world.db"
CATALOG = REPO / "build" / "game_catalog.json"
BACKUPS = REPO / "build" / "backups"


def resolve(spec: dict, teams: dict[int, dict]) -> dict[int, str]:
    """{team id: real name}. A current name that matches no record, or more than one, stops the run."""
    by_name: dict[str, list[int]] = {}
    for tid, t in teams.items():
        by_name.setdefault(t["name"], []).append(tid)
    out: dict[int, str] = {}
    problems = []
    for current, real in spec.get("teams_by_current_name", {}).items():
        ids = by_name.get(current, [])
        if len(ids) == 1:
            out[ids[0]] = real
        elif not ids:
            already = [tid for tid, t in teams.items() if t["name"] == real]
            if not already:                      # not applied earlier either: a genuine miss
                problems.append(f"'{current}' is not in Team.bin")
        else:
            problems.append(f"'{current}' names {len(ids)} records {ids} — list them by id instead")
    for tid, real in spec.get("teams_by_id", {}).items():
        if int(tid) not in teams:
            problems.append(f"team id {tid} is not in Team.bin")
        else:
            out[int(tid)] = real
    for tid, real in out.items():
        if len(real.encode("utf-8")) > 47:
            problems.append(f"{real!r} is longer than Team.bin's 47-byte name field")
    if problems:
        raise SystemExit("real_names.json does not fit this dt200:\n  " + "\n  ".join(problems))
    return {tid: real for tid, real in out.items() if teams[tid]["name"] != real}


def sync_world(dry: bool) -> None:
    """The world and the catalog take their names from the snapshot — the app shows our dt200."""
    arch = gw.Archive("dt200", SNAPSHOT)
    teams = gw.decode_teams(arch)
    comps, _members = gw.decode_competitions(arch)
    con = sqlite3.connect(WORLD)
    rows = con.execute("SELECT id, base_team_id, name FROM teams").fetchall()
    team_updates = []
    for row_id, base_id, name in rows:
        src = teams.get(base_id if base_id is not None else row_id) or teams.get(row_id)
        if src and src["name"] and src["name"] != name:
            team_updates.append((src["name"], row_id))
    league_updates = [(comps[lid]["name"], lid) for lid, name in con.execute("SELECT id, name FROM leagues")
                      if lid in comps and comps[lid]["name"] and comps[lid]["name"] != name]
    print(f"world: {len(team_updates)} team rows and {len(league_updates)} leagues differ from our dt200")
    if dry:
        con.close()
        return
    con.executemany("UPDATE teams SET name=? WHERE id=?", team_updates)
    con.executemany("UPDATE leagues SET name=? WHERE id=?", league_updates)
    data = SNAPSHOT.read_bytes()
    meta = json.dumps({"dt200": {"path": str(SNAPSHOT), "size": len(data), "sha1": hashlib.sha1(data).hexdigest()}})
    con.execute("UPDATE meta SET value=? WHERE key='world_archives'", (meta,))
    con.commit()
    con.close()

    if CATALOG.exists():
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        wrote = 0
        for country in catalog.get("countries", []):
            for league in country.get("leagues", []):
                lid = league.get("league_id")
                if lid in comps and comps[lid]["name"] and league.get("name") != comps[lid]["name"]:
                    league["name"] = comps[lid]["name"]
                    wrote += 1
                for team in league.get("teams", []):
                    src = teams.get(team.get("team_id"))
                    if src and src["name"] and team.get("name") != src["name"]:
                        team["name"] = src["name"]
                        wrote += 1
                league.get("teams", []).sort(key=lambda t: t.get("name", ""))
        CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{CATALOG.name}: {wrote} names brought into line")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--sync", action="store_true", help="only bring the world into line with our dt200")
    args = ap.parse_args()
    if not SNAPSHOT.exists() or not TREE.exists():
        sys.exit("no dt200 snapshot / tree_base yet — run tools/first_run.py first")

    if not args.sync:
        spec = json.loads(NAMES.read_text(encoding="utf-8"))
        teams = gw.decode_teams(gw.Archive("dt200", SNAPSHOT))
        renames = resolve(spec, teams)
        comps = {int(k): v for k, v in spec.get("competitions", {}).items()}
        print(f"{len(renames)} club names and {len(comps)} competition names to write into our dt200")
        for tid, real in list(renames.items())[:8]:
            print(f"   {tid:6d}  {teams[tid]['name']:26s} -> {real}")
        if args.dry:
            sync_world(dry=True)
            print("--dry: nothing written.")
            return 0

        (REPO / "build" / "dt200_renames.json").write_text(
            json.dumps({str(k): v for k, v in sorted(renames.items())}, ensure_ascii=False, indent=1), encoding="utf-8")
        comp_file = REPO / "build" / "dt200_comp_renames.json"
        merged = json.loads(comp_file.read_text(encoding="utf-8")) if comp_file.exists() else {}
        merged.update({str(k): v for k, v in comps.items()})
        comp_file.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

        env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
        if subprocess.run([sys.executable, str(REPO / "tools" / "dt200_rename.py")], cwd=REPO, env=env).returncode != 0:
            sys.exit("dt200_rename.py refused — nothing further written")

        BACKUPS.mkdir(parents=True, exist_ok=True)
        keep = BACKUPS / f"dt200_console_all.{datetime.now():%Y%m%d-%H%M%S}.cpk"
        shutil.copy2(SNAPSHOT, keep)
        patched = SNAPSHOT.with_suffix(".cpk.patching")
        r = cpk_patch.build(SNAPSHOT, TREE, patched)
        patched.replace(SNAPSHOT)
        print(f"snapshot patched: {r['patched']} of {r['files']} files ({r['base_size']:,} -> {r['out_size']:,} B); "
              f"the one before is {keep.name}")

    sync_world(dry=args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
