#!/usr/bin/env python3
"""
career_snapshot.py — save / restore the career as a standalone SQLite file (roadmap item 7).

build/master.db is both the compiled world AND the irreplaceable career save. A reseed or a
world rebuild rewrites career id ranges in place with no undo. This tool separates the two:

    python tools/career_snapshot.py save                      # -> careers/<club>_<yyyymmdd-HHMM>.db
    python tools/career_snapshot.py list                      # show snapshots
    python tools/career_snapshot.py restore careers/Foo.db    # put that career back into master.db

It also exports guard_reseed(db_path, action), used by career_seed.py and build_master.py:
refuse to run while a played career exists, unless ML_CONFIRM_RESEED=1 — and when the user
does confirm, snapshot the career automatically before proceeding (any career, played or not:
the app's New Career sets that variable and promises the vault a copy of whatever is on file).

How rows are classified (dynamic — the table list comes from sqlite_master, the decision from
column inspection, so new tables are picked up automatically):

  * Career id ranges (mirrors career_seed.py constants + ML.App/SessionYouth.cs):
      players     20,000,000 - 699,999,999    (world RFS players start at 700M)
                  plus the curated overlay 45-46bn (tools/update_career_squad.py): those
                  players are attached to CAREER squads only, so they must travel with the
                  save. A snapshot carrying the memberships without the players left 53
                  dangling squad rows (found 2026-08-23).
      teams          800,000 -     899,999    plus U21/U18 youth sides 9,000,000 - 9,199,999
      fixtures     9,000,000+
      seasons          9,000+
      leagues          9,000 - 9,999          (9000/9001 divisions, 9002-9004 career cups;
                                               simulated world leagues start at 35,000)
      formations     910,000+                 (career FORMATION_BASE)
    A row is career-range when ANY of its recognised id columns falls in a career range —
    union, not intersection, because career state can reference world ids (a signed world
    player's contract carries a sub-20M player_id but a career team_id).
  * WHOLE tables: career-only features whose rows may reference only world ids (a negotiation
    for a world player, a scout job on a world target, the staff-people pool whose hire state
    is career state) and the meta table, where career state hides in loose keys. These are
    snapshotted and restored in full.
  * Tables with no career-bearing columns (fm_clubs, coach_names, competitions, ...) are
    world data and never touched.

restore deletes the target's current career-range rows first (including tables the snapshot
doesn't know about, so a newer schema can't keep half a career), then inserts the snapshot's
rows. A manifest table inside every snapshot records per-table counts and predicates.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "build" / "master.db"
CAREERS_DIR = REPO / "careers"

# ── career id ranges ────────────────────────────────────────────────────────────────────────
PLAYER_LO, PLAYER_HI = 20_000_000, 700_000_000
CURATED_LO, CURATED_HI = 45_000_000_000, 46_000_000_000   # update_career_squad.py overlay
TEAM_LO, TEAM_HI = 800_000, 900_000
YOUTH_LO, YOUTH_HI = 9_000_000, 9_200_000      # ML.App SessionYouth: 9M + (parent-800k)*2
FIXTURE_LO = 9_000_000
SEASON_LO = 9_000
LEAGUE_LO, LEAGUE_HI = 9_000, 10_000
FORMATION_LO = 910_000

# Column name -> id kind. Any table carrying one of these is checked row-by-row.
COL_KIND = {
    "player_id": "player",
    "team_id": "team", "home_team_id": "team", "away_team_id": "team",
    "owner_team": "team", "host_team": "team", "seller_id": "team",
    "from_team_id": "team", "to_team_id": "team", "rival_id": "team",
    "fixture_id": "fixture",
    "season_id": "season",
    "league_id": "league", "upper_league_id": "league", "lower_league_id": "league",
    "formation_id": "formation",
}

# Tables whose bare "id" column IS one of the career id kinds.
ID_TABLE_KIND = {
    "players": "player", "teams": "team", "fixtures": "fixture",
    "formations": "formation", "leagues": "league", "seasons": "season",
}

# Career-only features: snapshot/restore the ENTIRE table (see module docstring).
WHOLE_TABLES = {
    "meta",            # career state hides in loose keys (current_team_id, tactics_*, fin_*)
    "inbox", "negotiations", "scout_jobs", "promises", "loans",
    "staff_people",    # hireable pool; team_id/contract_until = career hire state
    "morale", "player_condition", "training_focus", "skill_training",
}

INTERNAL_TABLES = ("_snapshot_info", "_snapshot_manifest")


# ── classification ──────────────────────────────────────────────────────────────────────────
def _pred_for(kind: str, col: str) -> str:
    c = f'"{col}"'
    if kind == "player":
        return (f"(({c} >= {PLAYER_LO} AND {c} < {PLAYER_HI}) "
                f"OR ({c} >= {CURATED_LO} AND {c} < {CURATED_HI}))")
    if kind == "team":
        return (f"(({c} >= {TEAM_LO} AND {c} < {TEAM_HI}) "
                f"OR ({c} >= {YOUTH_LO} AND {c} < {YOUTH_HI}))")
    if kind == "fixture":
        return f"({c} >= {FIXTURE_LO})"
    if kind == "season":
        return f"({c} >= {SEASON_LO})"
    if kind == "league":
        return f"({c} >= {LEAGUE_LO} AND {c} < {LEAGUE_HI})"
    if kind == "formation":
        return f"({c} >= {FORMATION_LO})"
    raise ValueError(kind)


def career_predicate(table: str, cols: list[str]) -> str | None:
    """SQL WHERE clause selecting this table's career rows, or None if the table carries no
    career-identifying column (pure world data — never saved, never deleted)."""
    if table in WHOLE_TABLES:
        return "1=1"
    parts = []
    for col in cols:
        if col == "id" and table in ID_TABLE_KIND:
            parts.append(_pred_for(ID_TABLE_KIND[table], col))
        elif col in COL_KIND:
            parts.append(_pred_for(COL_KIND[col], col))
    if table == "teams" and "team_kind" in cols:
        parts.append("\"team_kind\" IN ('u21','u18')")   # belt-and-braces for youth sides
    return " OR ".join(parts) if parts else None


def _columns(con: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _tables(con: sqlite3.Connection, schema: str = "main") -> list[tuple[str, str]]:
    """(name, create_sql) for every real table, snapshot-internal ones excluded."""
    rows = con.execute(
        f"SELECT name, sql FROM {schema}.sqlite_master "
        f"WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [(n, s) for n, s in rows if n not in INTERNAL_TABLES]


def ro_connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(Path(path).resolve()).replace("\\", "/"), safe="/:")
    return sqlite3.connect(uri + "?mode=ro", uri=True, timeout=60)


def career_info(con: sqlite3.Connection) -> dict | None:
    """The live career's identity, or None when the DB holds no career."""
    try:
        row = con.execute("SELECT value FROM meta WHERE key='current_team_id'").fetchone()
    except sqlite3.Error:
        return None
    if not row or row[0] in (None, ""):
        return None
    tid = int(row[0])
    club = None
    try:
        r = con.execute("SELECT name FROM teams WHERE id=?", (tid,)).fetchone()
        club = r[0] if r else None
    except sqlite3.Error:
        pass
    year = played = None
    try:
        r = con.execute("SELECT year FROM seasons WHERE id>=? AND is_current=1",
                        (SEASON_LO,)).fetchone() \
            or con.execute("SELECT year FROM seasons WHERE id>=?", (SEASON_LO,)).fetchone()
        year = r[0] if r else None
        played = con.execute("SELECT COUNT(*) FROM fixtures WHERE id>=? AND played=1",
                             (FIXTURE_LO,)).fetchone()[0]
    except sqlite3.Error:
        pass
    return {"team_id": tid, "club": club or f"team {tid}", "season_year": year,
            "played": played or 0}


# ── save ────────────────────────────────────────────────────────────────────────────────────
def save(db_path: Path, out_path: Path | None = None, quiet: bool = False) -> Path:
    con = ro_connect(db_path)
    info = career_info(con)
    if info is None:
        raise SystemExit(f"no career in {db_path} (meta.current_team_id missing) — "
                         "nothing to snapshot")
    if out_path is None:
        CAREERS_DIR.mkdir(exist_ok=True)
        club = re.sub(r"[^A-Za-z0-9]+", "_", info["club"]).strip("_") or "career"
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = CAREERS_DIR / f"{club}_{stamp}.db"
        n = 1
        while out_path.exists():
            out_path = CAREERS_DIR / f"{club}_{stamp}-{n}.db"
            n += 1
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        raise SystemExit(f"refusing to overwrite existing snapshot {out_path}")

    snap = sqlite3.connect(out_path)
    snap.execute("PRAGMA journal_mode=OFF")
    snap.execute("CREATE TABLE _snapshot_info (key TEXT PRIMARY KEY, value TEXT)")
    snap.execute("CREATE TABLE _snapshot_manifest ("
                 "table_name TEXT PRIMARY KEY, rows INTEGER NOT NULL, predicate TEXT NOT NULL)")
    total = 0
    manifest: list[tuple[str, int, str]] = []
    for table, create_sql in _tables(con):
        cols = _columns(con, table)
        pred = career_predicate(table, cols)
        if pred is None or not create_sql:
            continue                                   # pure world data
        snap.execute(create_sql)
        rows = con.execute(f'SELECT * FROM "{table}" WHERE {pred}').fetchall()
        if rows:
            ph = ",".join("?" * len(cols))
            snap.executemany(f'INSERT INTO "{table}" VALUES ({ph})', rows)
        manifest.append((table, len(rows), pred))
        total += len(rows)
    snap.executemany("INSERT INTO _snapshot_manifest VALUES (?,?,?)", manifest)
    snap.executemany("INSERT INTO _snapshot_info VALUES (?,?)", [
        ("format", "1"),
        ("created", datetime.datetime.now().isoformat(timespec="seconds")),
        ("source_db", str(Path(db_path).resolve())),
        ("club", info["club"]),
        ("team_id", str(info["team_id"])),
        ("season_year", str(info["season_year"])),
        ("played", str(info["played"])),
    ])
    snap.commit()
    snap.close()
    con.close()
    if not quiet:
        print(f"career snapshot: {info['club']} (season {info['season_year']}, "
              f"{info['played']} played) -> {out_path}")
        for table, n, _ in manifest:
            if n:
                print(f"  {table:24s} {n:7,d}")
        print(f"  {'TOTAL':24s} {total:7,d} rows in {len(manifest)} tables")
    return out_path


# ── restore ─────────────────────────────────────────────────────────────────────────────────
def restore(snap_path: Path, db_path: Path, backup: bool = True) -> None:
    snap_path, db_path = Path(snap_path), Path(db_path)
    if not snap_path.exists():
        raise SystemExit(f"snapshot not found: {snap_path}")
    if not db_path.exists():
        raise SystemExit(f"target DB not found: {db_path}")

    probe = ro_connect(snap_path)
    try:
        meta = dict(probe.execute("SELECT key, value FROM _snapshot_info"))
        manifest = probe.execute(
            "SELECT table_name, rows, predicate FROM _snapshot_manifest ORDER BY table_name"
        ).fetchall()
    except sqlite3.Error:
        raise SystemExit(f"{snap_path} is not a career snapshot (no manifest)")
    finally:
        probe.close()

    # The restore overwrites the target's current career — keep a copy of it first.
    if backup:
        pre = ro_connect(db_path)
        cur = career_info(pre)
        pre.close()
        if cur is not None:
            path = save(db_path, quiet=True)
            print(f"current career backed up first: {path}")

    con = sqlite3.connect(db_path, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("ATTACH ? AS snap", (str(snap_path),))
    con.execute("BEGIN")
    snap_tables = {n for n, _ in _tables(con, "snap")}
    deleted = inserted = 0
    print(f"restoring {meta.get('club')} (season {meta.get('season_year')}, "
          f"{meta.get('played')} played, taken {meta.get('created')}) into {db_path}")
    for table, snap_rows, saved_pred in manifest:
        if table not in snap_tables:
            continue
        exists = con.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?",
                             (table,)).fetchone()
        if not exists:
            create_sql = con.execute("SELECT sql FROM snap.sqlite_master WHERE name=?",
                                     (table,)).fetchone()[0]
            con.execute(create_sql)
            print(f"  {table}: created (absent from target schema)")
        tcols = _columns(con, table)
        pred = career_predicate(table, tcols) or saved_pred
        con.execute(f'DELETE FROM main."{table}" WHERE {pred}')
        ndel = con.execute("SELECT changes()").fetchone()[0]
        scols = _columns(con, table, "snap")
        common = [c for c in scols if c in tcols]
        dropped = [c for c in scols if c not in tcols]
        if dropped:
            print(f"  {table}: WARNING — snapshot columns not in target, dropped: "
                  + ", ".join(dropped))
        collist = ",".join(f'"{c}"' for c in common)
        con.execute(f'INSERT OR REPLACE INTO main."{table}" ({collist}) '
                    f'SELECT {collist} FROM snap."{table}"')
        nins = con.execute("SELECT changes()").fetchone()[0]
        deleted += ndel
        inserted += nins
        if ndel or nins:
            print(f"  {table:24s} -{ndel:,d} +{nins:,d}")
    # Career tables the snapshot predates (newer schema): clear their career rows too, so the
    # restored career is exactly the snapshot, not a blend of two careers.
    known = {t for t, _, _ in manifest}
    for table, _sql in _tables(con):
        if table in known:
            continue
        pred = career_predicate(table, _columns(con, table))
        if pred is None:
            continue
        con.execute(f'DELETE FROM main."{table}" WHERE {pred}')
        n = con.execute("SELECT changes()").fetchone()[0]
        if n:
            deleted += n
            print(f"  {table:24s} -{n:,d} (career rows cleared — table unknown to snapshot)")
    # Integrity gate: never commit a career whose squad rows reference players that exist in
    # neither the snapshot nor the target's world. World signings (eF/RFS/FM ids) resolve
    # against the target; career-band and curated-band players travel inside the snapshot.
    # Snapshots taken before 2026-08-23 dropped the curated 45-46bn overlay, and restoring one
    # would silently empty its clubs' squads, so refuse and point at the repair tool.
    orphans = con.execute(
        "SELECT COUNT(*) FROM main.squad_members sm WHERE ((sm.team_id >= ? AND sm.team_id < ?)"
        " OR (sm.team_id >= ? AND sm.team_id < ?)) AND NOT EXISTS "
        "(SELECT 1 FROM main.players p WHERE p.id = sm.player_id)",
        (TEAM_LO, TEAM_HI, YOUTH_LO, YOUTH_HI)).fetchone()[0]
    if orphans:
        con.execute("ROLLBACK")
        con.close()
        raise SystemExit(
            f"RESTORE ABORTED (rolled back): it would leave {orphans:,} squad rows referencing "
            f"players present in neither the snapshot nor {db_path}. Pre-2026-08-23 snapshots "
            "lack the curated 45-46bn overlay players; repair the snapshot first: "
            f"python tools/repair_career_refs.py '{snap_path}' --apply")
    con.commit()
    con.execute("DETACH snap")
    con.close()
    print(f"restore complete: {deleted:,d} rows removed, {inserted:,d} rows restored.")


# ── list ────────────────────────────────────────────────────────────────────────────────────
def list_snapshots() -> None:
    files = sorted(CAREERS_DIR.glob("*.db")) if CAREERS_DIR.exists() else []
    if not files:
        print(f"no snapshots in {CAREERS_DIR}")
        return
    for f in files:
        try:
            con = ro_connect(f)
            meta = dict(con.execute("SELECT key, value FROM _snapshot_info"))
            rows = con.execute("SELECT COALESCE(SUM(rows),0) FROM _snapshot_manifest"
                               ).fetchone()[0]
            con.close()
            print(f"{f.name:44s} {meta.get('club','?'):24s} season {meta.get('season_year','?')}"
                  f"  {meta.get('played','?')} played  {rows:,d} rows  ({meta.get('created','?')})")
        except sqlite3.Error:
            print(f"{f.name:44s} (unreadable — not a snapshot?)")


# ── the reseed guard (imported by career_seed.py and build_master.py) ───────────────────────
def guard_reseed(db_path: Path | str, action: str = "rebuild") -> bool:
    """True when the caller may proceed. Refuses (False) while db_path holds a career with at
    least one played match, unless ML_CONFIRM_RESEED=1 — in which case the career is
    snapshotted to /careers automatically before returning True. With that variable set the
    copy is taken for ANY career on file, played or not (see the note below)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return True
    try:
        con = ro_connect(db_path)
        info = career_info(con)
        con.close()
    except sqlite3.Error:
        return True
    if info is None:
        return True                       # no career at all — nothing to lose
    confirmed = os.environ.get("ML_CONFIRM_RESEED") == "1"
    if not confirmed:
        # Nothing played and nobody asked us to keep it: the old, quiet pass-through, so a bare
        # `python tools/career_seed.py ...` at the command line behaves exactly as it always did.
        if not info["played"]:
            return True
        print(f"REFUSING the {action}: {db_path} holds your active career save.", flush=True)
        print(f"  It would DESTROY the {info['club']} career "
              f"(season {info['season_year']}, {info['played']} played match(es)). No undo.")
        print("  To keep the career first:   python tools/career_snapshot.py save")
        print("  To proceed anyway, set ML_CONFIRM_RESEED=1 and re-run:")
        print("      PowerShell:  $env:ML_CONFIRM_RESEED='1'")
        print("      cmd:         set ML_CONFIRM_RESEED=1")
        print("  (with it set, the career is snapshotted to /careers automatically first)")
        return False
    # WHAT THE BUG WAS. The played test used to sit one line higher — "if info is None or not
    # info['played']: return True" — so it answered BEFORE anything looked at ML_CONFIRM_RESEED.
    # The app sets that variable on every New Career (CareerBuilder) and tells the manager that
    # his current save goes to the vault first; for a career with no result recorded yet it went
    # nowhere at all. Picking the club, sorting the squad, naming an XI and setting the season up
    # IS the save — the first result is not what makes it one — and starting a second career
    # wiped it with no copy anywhere. Consent given, it gets vaulted whether or not a ball has
    # been kicked. Without consent nothing changes: an unplayed career still waves the caller
    # through, so the command line behaves as before.
    print(f"ML_CONFIRM_RESEED=1 — snapshotting the {info['club']} career before the {action}…")
    try:
        path = save(db_path, quiet=True)
    except BaseException as e:                       # SystemExit included: never lose a career
        if not info["played"]:
            # Nothing has been played, so there is nothing a copy would save that a fresh seed
            # does not recreate. Refusing here would make every New Career depend on being able
            # to write careers/ — a read-only folder, a locked OneDrive sync or a full disk
            # would then block the release's main path for a save that has no results in it.
            print(f"auto-snapshot FAILED ({e}) — this career has no played match, "
                  f"so the {action} goes ahead without a copy.")
            return True
        print(f"auto-snapshot FAILED ({e}) — refusing the {action}.")
        return False
    print(f"career snapshot saved: {path}")
    return True


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("save", help="export the career to careers/<club>_<stamp>.db")
    sp.add_argument("--db", default=str(DEFAULT_DB))
    sp.add_argument("--out", default=None, help="explicit output file (default: careers/…)")
    rp = sub.add_parser("restore", help="put a snapshot's career back into the DB")
    rp.add_argument("file")
    rp.add_argument("--db", default=str(DEFAULT_DB))
    rp.add_argument("--no-backup", action="store_true",
                    help="skip the automatic pre-restore snapshot of the current career")
    sub.add_parser("list", help="show snapshots in /careers")
    args = ap.parse_args()

    if args.cmd == "save":
        save(Path(args.db), Path(args.out) if args.out else None)
    elif args.cmd == "restore":
        restore(Path(args.file), Path(args.db), backup=not args.no_backup)
    else:
        list_snapshots()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
