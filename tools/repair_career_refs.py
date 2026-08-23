#!/usr/bin/env python3
"""
repair_career_refs.py — re-link or remove squad rows whose player row is missing.

A career DB (build/master.db or a /careers snapshot) must never hold a squad_members row whose
player_id has no players row: the join silently empties every per-squad query for that club.
Snapshots taken before 2026-08-23 have exactly this defect for the curated 2026/27 overlay
(players 45-46bn, tools/update_career_squad.py): the old snapshot predicate carried the career
band only, so the overlay memberships were saved without their players.

For every dangling reference, in this order:

  * player found in --source (default build/master.db) in a NON-world band (career 20M-700M,
    curated 45-46bn, or a band-gap id): RE-LINK — copy the players row plus every satellite row
    (player_attributes, player_market, player_identity, ...) from the source into the target.
  * player found in --source in a WORLD band (eF < 2^24, RFS 700M-10B, FM 10-13B, generated
    >= 50bn): KEEP the membership untouched. World rows never live inside a snapshot by
    design; the reference resolves against the target DB at restore time
    (career_snapshot.restore verifies exactly this before committing).
  * player found nowhere: DELETE the membership rows — they reference a player that no longer
    exists anywhere.

Dry-run by default; --apply writes, taking a byte-for-byte <target>.pre-repair.bak first.
If the target is a snapshot, its _snapshot_manifest row counts are refreshed for every table
the repair touched, so `career_snapshot.py list` totals stay honest.

    python tools/repair_career_refs.py careers/Foo.db                # report only
    python tools/repair_career_refs.py careers/Foo.db --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from career_snapshot import career_predicate  # noqa: E402  (keeps manifest preds canonical)

EF_MAX = 1 << 24
CAREER_LO, CAREER_HI = 20_000_000, 700_000_000
RFS_LO, RFS_HI = 700_000_000, 10_000_000_000
FM_LO, FM_HI = 10_000_000_000, 13_000_000_000
CUR_LO, CUR_HI = 45_000_000_000, 46_000_000_000
GEN_LO = 50_000_000_000

WORLD_BANDS = {"ef", "rfs", "fm", "generated"}   # stable ids that live in master.db, not saves


def band(pid: int) -> str:
    if pid < EF_MAX:
        return "ef"
    if CAREER_LO <= pid < CAREER_HI:
        return "career"
    if RFS_LO <= pid < RFS_HI:
        return "rfs"
    if FM_LO <= pid < FM_HI:
        return "fm"
    if CUR_LO <= pid < CUR_HI:
        return "curated"
    if pid >= GEN_LO:
        return "generated"
    return "gap"


def columns(con: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA {schema}.table_info("{table}")')]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("target", help="career DB to repair (a /careers snapshot or build/master.db)")
    ap.add_argument("--source", default=str(REPO / "build" / "master.db"),
                    help="DB to re-link missing players from (default: build/master.db)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run report)")
    args = ap.parse_args()

    target, source = Path(args.target), Path(args.source)
    if not target.exists():
        sys.exit(f"target not found: {target}")
    same = source.exists() and target.resolve() == source.resolve()

    if args.apply:
        bak = target.with_name(target.name + ".pre-repair.bak")
        if not bak.exists():
            shutil.copy2(target, bak)
            print(f"backup: {bak}")

    con = sqlite3.connect(target, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("PRAGMA foreign_keys=OFF")
    if not same:
        if not source.exists():
            sys.exit(f"source not found: {source}")
        con.execute("ATTACH ? AS src", (str(source),))
    src = "main" if same else "src"

    dangling = con.execute(
        "SELECT DISTINCT sm.player_id FROM squad_members sm "
        "WHERE NOT EXISTS (SELECT 1 FROM main.players p WHERE p.id = sm.player_id) "
        "ORDER BY sm.player_id").fetchall()
    if not dangling:
        print(f"{target}: no dangling squad references — nothing to do")
        con.close()
        return 0

    # players + every player_id-bearing satellite present in BOTH DBs. squad_members is the
    # table being repaired, never a copy source; snapshot-internal tables are never touched.
    tgt_tables = {n for (n,) in con.execute(
        "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    src_tables = {n for (n,) in con.execute(
        f"SELECT name FROM {src}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    sat_tables = sorted(t for t in tgt_tables & src_tables
                        if t not in ("players", "squad_members")
                        and not t.startswith("_snapshot")
                        and "player_id" in columns(con, t))

    relinked, kept, deleted = [], [], []
    touched = {"squad_members"}
    con.execute("BEGIN")
    for (pid,) in dangling:
        b = band(pid)
        in_src = con.execute(f"SELECT 1 FROM {src}.players WHERE id=?", (pid,)).fetchone()
        teams = [t for (t,) in con.execute(
            "SELECT team_id FROM squad_members WHERE player_id=?", (pid,))]
        if in_src and b in WORLD_BANDS:
            kept.append((pid, b, teams))
            continue
        if in_src:                                                   # career/curated/gap: re-link
            pcols = [c for c in columns(con, "players", src) if c in columns(con, "players")]
            cl = ",".join(f'"{c}"' for c in pcols)
            con.execute("DELETE FROM main.players WHERE id=?", (pid,))
            con.execute(f'INSERT INTO main.players ({cl}) '
                        f'SELECT {cl} FROM {src}.players WHERE id=?', (pid,))
            copied = {"players": 1}
            for t in sat_tables:
                scols = [c for c in columns(con, t, src) if c in columns(con, t)]
                cl = ",".join(f'"{c}"' for c in scols)
                con.execute(f'DELETE FROM main."{t}" WHERE player_id=?', (pid,))
                con.execute(f'INSERT INTO main."{t}" ({cl}) '
                            f'SELECT {cl} FROM {src}."{t}" WHERE player_id=?', (pid,))
                n = con.execute("SELECT changes()").fetchone()[0]
                if n:
                    copied[t] = n
                    touched.add(t)
            touched.add("players")
            relinked.append((pid, b, teams, copied))
        else:                                                        # exists nowhere: remove
            con.execute("DELETE FROM main.squad_members WHERE player_id=?", (pid,))
            deleted.append((pid, b, teams))

    # a repaired snapshot keeps an honest manifest (list totals, restore bookkeeping)
    if "_snapshot_manifest" in tgt_tables and args.apply:
        for t in sorted(touched):
            n = con.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
            pred = career_predicate(t, columns(con, t)) or "1=1"
            con.execute("INSERT OR REPLACE INTO _snapshot_manifest VALUES (?,?,?)", (t, n, pred))

    if args.apply:
        con.commit()
    else:
        con.execute("ROLLBACK")

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes; re-run with --apply)"
    print(f"{target} — {len(dangling)} dangling player ids — {mode}")
    for pid, b, teams, copied in relinked:
        extra = ", ".join(f"{t} x{n}" for t, n in sorted(copied.items()) if t != "players")
        print(f"  RE-LINKED  {pid}  ({b}, teams {teams}) copied players row + {extra}")
    for pid, b, teams in kept:
        print(f"  KEPT       {pid}  ({b} world id, teams {teams}) — resolves against the "
              "world DB at restore time")
    for pid, b, teams in deleted:
        print(f"  DELETED    {pid}  ({b}, teams {teams}) — player exists in neither DB")
    print(f"summary: {len(relinked)} re-linked, {len(kept)} kept (world), "
          f"{len(deleted)} membership(s) deleted")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
