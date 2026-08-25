#!/usr/bin/env python3
"""
merge_passes.py — two field-priority passes from docs/database-blueprint.md, joined ONLY
through the identity spine (player_identity / team_identity), never by name.

Pass A — NAMES, eFootball-first (blueprint: player names | 1st eF licensed | 2nd FM | 3rd RFS):
    every squad player whose player_identity.ef_pid is set and whose row is NOT the native eF
    record (kind fm/rfs/curated) adopts the eF record's players.name when it differs.
    Guard: the eF name must be non-empty and >= 3 chars, or the row is skipped.

Pass B — LOGOS, DVX-first (owner decision 2026-08: DVX outranks API crests):
    every teams row and catalog.json club whose team_identity.fm_club_id has a file
    assets/dvx_logos/<fm_club_id>.webp points its logo at that file, EVEN IF an
    assets/badges API crest is currently set. API crests survive only where no DVX
    file exists. Ends with a coverage report: dvx vs badges vs RFS vs none.

    python tools/merge_passes.py           # --dry is the default: report only, DB opened read-only
    python tools/merge_passes.py --apply   # backs up build/master.db + build/catalog.json, then writes
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
DVX = REPO / "assets" / "dvx_logos"

RFS_LOGO = re.compile(r"T_\d+\.(png|webp)$")


def logo_bucket(path: str | None) -> str:
    if not path:
        return "none"
    if path.startswith("assets/dvx_logos/"):
        return "dvx"
    if path.startswith("assets/badges"):
        return "badges"
    if RFS_LOGO.search(path):
        return "rfs"
    return "other"


def pass_a_names(con: sqlite3.Connection, apply: bool) -> None:
    """eF-first names for squad players resolved to a native eF record."""
    rows = con.execute(
        "SELECT pi.player_id, pi.kind, pi.ef_pid, p.name, e.name "
        "FROM player_identity pi "
        "JOIN (SELECT DISTINCT player_id FROM squad_members) s ON s.player_id = pi.player_id "
        "JOIN players p ON p.id = pi.player_id "
        "JOIN players e ON e.id = pi.ef_pid "
        "WHERE pi.ef_pid IS NOT NULL AND pi.kind IN ('fm','rfs','curated')").fetchall()

    adopt: list[tuple[int, str, str, str]] = []   # (player_id, kind, old, new)
    guarded = 0
    for pid, kind, _ef_pid, cur_name, ef_name in rows:
        if not ef_name or len(ef_name.strip()) < 3:
            guarded += 1                          # eF name unusable — keep current
            continue
        if ef_name != cur_name:
            adopt.append((pid, kind, cur_name, ef_name))

    by_kind = Counter(k for _, k, _, _ in adopt)
    print(f"[A] NAMES eF-first — squad players with a linked eF record: {len(rows):,}")
    print(f"[A] adopt eF name: {len(adopt):,} ({dict(by_kind)}) | already identical: "
          f"{len(rows) - len(adopt) - guarded:,} | guarded (eF name empty/<3 chars): {guarded}")
    for pid, kind, old, new in adopt[:20]:
        print(f"[A]   {kind:>3} {pid:>12}  {old!r} -> {new!r}")

    if apply:
        con.executemany("UPDATE players SET name = ? WHERE id = ?",
                        [(new, pid) for pid, _, _, new in adopt])
        print(f"[A] applied: {len(adopt):,} players renamed")


def pass_b_logos(con: sqlite3.Connection, apply: bool) -> None:
    """DVX-first logos on teams.logo_path and catalog.json, keyed by fm_club_id."""
    have = {int(p.stem) for p in DVX.glob("*.webp") if p.stem.isdigit()}
    fm_of = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
    print(f"[B] LOGOS DVX-first — dvx files: {len(have):,} | teams with fm_club_id: {len(fm_of):,}")

    def dvx_path(team_id: int) -> str | None:
        fmid = fm_of.get(team_id)
        return f"assets/dvx_logos/{fmid}.webp" if fmid in have else None

    # teams table
    t_updates: list[tuple[str, int]] = []
    flipped = Counter()
    dist = Counter()
    for tid, logo in con.execute("SELECT id, logo_path FROM teams"):
        want = dvx_path(tid)
        # Two stores outrank the pack and must not be flipped: assets/badges is hand-reconciled,
        # and assets/rfs_crests is where the clubs the pack does not carry get their crest —
        # Manchester United among them, whose fm id 680 has no art in DVX at all. This tool is
        # keyed on fm_club_id, so it is right about WHICH crest; it just must not overwrite a
        # better source with one the pack happens to have.
        if logo and logo.startswith(("assets/badges/", "assets/rfs_crests/")):
            dist[logo_bucket(logo)] += 1
            continue
        if want and logo != want:
            t_updates.append((want, tid))
            flipped[logo_bucket(logo)] += 1
            logo = want
        dist[logo_bucket(logo)] += 1
    print(f"[B] teams.logo_path updates: {len(t_updates):,} (from: {dict(flipped)})")
    print(f"[B] teams end state: " + " | ".join(
        f"{k}={dist.get(k, 0):,}" for k in ("dvx", "badges", "rfs", "other", "none")))

    # catalog.json
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    c_updates = 0
    c_flipped = Counter()
    c_dist = Counter()
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                want = dvx_path(t.get("team_id"))
                logo = t.get("logo")
                if want and logo != want:
                    c_flipped[logo_bucket(logo)] += 1
                    t["logo"] = want
                    c_updates += 1
                    logo = want
                c_dist[logo_bucket(logo)] += 1
    print(f"[B] catalog logo updates: {c_updates:,} (from: {dict(c_flipped)})")
    print(f"[B] catalog end state: " + " | ".join(
        f"{k}={c_dist.get(k, 0):,}" for k in ("dvx", "badges", "rfs", "other", "none")))

    if apply:
        con.executemany("UPDATE teams SET logo_path = ? WHERE id = ?", t_updates)
        CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
        print(f"[B] applied: {len(t_updates):,} teams rows + {c_updates:,} catalog entries")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apply = "--apply" in sys.argv

    if apply:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for f in (DB, CAT):
            bak = f.with_name(f.name + f".bak-mergepasses-{stamp}")
            shutil.copy2(f, bak)
            print(f"backup: {bak.relative_to(REPO).as_posix()}")
        con = sqlite3.connect(DB, timeout=60)
        con.execute("BEGIN")
    else:
        print("DRY RUN — no writes (pass --apply to write; backups are taken first)")
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)

    pass_a_names(con, apply)
    pass_b_logos(con, apply)

    if apply:
        con.commit()
        print("committed.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
