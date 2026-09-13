#!/usr/bin/env python3
"""
sanitize_release_db.py — turn a COPY of the owner's world into the world we ship.

    python tools/sanitize_release_db.py <package>/build/master.db <package> [--dry]

The release used to ship the owner's database as it stood: his Chelsea career still loaded on
first launch, his manager name on the touchline, his skin and transfer difficulty, and 149
player portraits pointing at C:\\Users\\tjgg2\\OneDrive. A downloader unzipped the release and
landed in someone else's save. This strips all of it, so the first launch opens on the continent
picker with nothing in the file but the world.

It only ever touches the copy inside the package directory. It refuses a path outside that
directory, and refuses the source that copy came from — this checkout's build/master.db,
$ML_WORLD_ROOT's, or $ML_DB. That source is the owner's live save and is never written.

What it does, in one transaction:
  1. career_seed.clear_career(con)   — every row in the career and youth id bands
  2. meta: drop current_team_id / current_season_id, keep only career_seed.CARRY_OVER_META,
     and (unless ML_KEEP_OWNER_SETTINGS=1) drop the owner's preferences and machine paths
  3. players.portrait_path = NULL wherever it is an absolute Windows path
  4. assert no text anywhere in meta/players/teams/staff_people still names the owner
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import sqlite3
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))

# A leak report names players, and the first Đorđe killed the report itself: the Windows console
# encodes cp1252 and raised UnicodeEncodeError instead of printing the row we refused over.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):                 # a pipe that cannot be reconfigured
        pass

# Which meta survives a reseed is the seeder's ruling, not ours — we apply its allowlist rather
# than keep a second copy here that would drift out of step with it. CARRY_OVER_CAREER is the
# seeder's second, currently empty set (the open manager_rep question); union it in so a key the
# owner later decides to carry is not silently dropped from the release instead.
CARRY_OVER_META_NAME = "CARRY_OVER_META"
CARRY_OVER_CAREER_NAME = "CARRY_OVER_CAREER"

# On top of the seeder's allowlist: the owner's own settings. Every one of these is a meta key
# (the app's SetSetting is SetMeta), every one is personal rather than world data, and every one
# has an app default when the key is absent — ui_skin falls back to Midnight, transfer_difficulty
# to Normal, world_seed rolls a fresh universe on first launch. ffmpeg_path was the single meta
# row that carried C:\Users\tjgg2 into the zip.
OWNER_SETTINGS = (
    # look and feel
    "ui_skin", "attr_fm_mode", "real_names",
    # realism dials
    "mask_strict", "transfer_difficulty", "injury_freq", "sack_leniency",
    # matchday and capture, plus the machine paths behind them
    "auto_boot", "record_matches", "obs_url", "obs_password", "ffmpeg_path", "video_dir",
    "steam_root", "steam_user_id",
    # the owner on the touchline, and the dice his universe was rolled with
    "manager_name", "manager_nat", "manager_rep", "world_seed",
)

# The two strings that must not reach a downloader's disk. Both come from the owner's home
# directory, so either one in any text column means a path or a name leaked through.
LEAK_PATTERNS = ("%tjgg2%", "%OneDrive%")
LEAK_TABLES = ("meta", "players", "teams", "staff_people")


def _same_path(a: Path, b: Path) -> bool:
    """Windows compares paths case-insensitively, and one side may not exist yet."""
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


MARKER = ".release-package"     # written by make_release.sh into the package it is building


def _refuse_unless_a_copy(db: Path, pkg: Path) -> None:
    """Only ever the database inside a package that make_release.sh is building.

    WHAT THE BUG WAS. This used to accept any db under any ancestor directory, and skipped the
    checkout guard exactly when the package dir WAS the checkout — so `python
    tools/sanitize_release_db.py build/master.db .` from the owner's repo root sailed through and
    wiped his live career, with no vault copy, because this tool never takes one. Now the target
    must be precisely <pkg>/build/master.db, <pkg> must carry the marker file only make_release.sh
    writes (and the zip step strips it, so an extracted download never qualifies), and <pkg> must
    not look like a source checkout. Every other path is refused before anything is opened.
    """
    if not (pkg / MARKER).is_file():
        sys.exit(f"refusing: {pkg} is not a package make_release.sh is building "
                 f"(no {MARKER} marker) — this tool sanitises the release COPY only")
    for tell in (".git", "src/ML.App", "tests"):
        if (pkg / tell).exists():
            sys.exit(f"refusing: {pkg} looks like a source checkout ({tell} is present)")
    if not _same_path(db, pkg / "build" / "master.db"):
        sys.exit(f"refusing: the only database this tool touches is <package>/build/master.db, "
                 f"not {db}")
    guards = []
    # The shipped copy of this script lives inside the package, so "this checkout" is the
    # package itself there — recognisable by the marker. Anywhere else, REPO is a real checkout
    # whose build/master.db is somebody's live world.
    if not (REPO / MARKER).is_file():
        guards.append(("this checkout", REPO / "build" / "master.db"))
    world = os.environ.get("ML_WORLD_ROOT")
    if world:
        guards.append(("ML_WORLD_ROOT", Path(world) / "build" / "master.db"))
    if os.environ.get("ML_DB"):
        guards.append(("ML_DB", Path(os.environ["ML_DB"])))
    for label, guarded in guards:
        if _same_path(db, guarded):
            sys.exit(f"refusing: {db} is {label}'s live world — sanitise the package copy, "
                     "never the source")


def _keep_meta_key(key: str, allow) -> bool:
    """CARRY_OVER_META entries are exact keys; an entry carrying % is a LIKE-style family, since
    the app writes per-club families (tactics_custom_800001, xi_manual_800003)."""
    for a in allow:
        a = str(a)
        if "%" in a or "*" in a:
            if fnmatch.fnmatchcase(key, a.replace("%", "*")):
                return True
        elif key == a:
            return True
    return False


def _leak_rows(con: sqlite3.Connection, table: str) -> list[str]:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    if not cols:
        return []
    pred = " OR ".join(f'CAST("{c}" AS TEXT) LIKE ?' for c in cols for _ in LEAK_PATTERNS)
    params = [p for _ in cols for p in LEAK_PATTERNS]
    out = []
    for row in con.execute(f'SELECT * FROM "{table}" WHERE {pred} LIMIT 20', params):
        out.append(next((f"{c}={v!r}" for c, v in zip(cols, row)
                         if isinstance(v, str) and ("tjgg2" in v or "OneDrive" in v)), repr(row)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="the COPY to sanitise, inside the package")
    ap.add_argument("package", help="the package directory that copy must live under")
    ap.add_argument("--dry", action="store_true", help="do the work, roll it back, report")
    args = ap.parse_args()

    db = Path(args.db).resolve()
    pkg = Path(args.package).resolve()
    _refuse_unless_a_copy(db, pkg)
    if not db.exists():
        sys.exit(f"no such database: {db}")

    try:
        import career_seed
        clear_career = career_seed.clear_career
        allow = set(getattr(career_seed, CARRY_OVER_META_NAME)) | \
            set(getattr(career_seed, CARRY_OVER_CAREER_NAME, ()))
    except (ImportError, AttributeError) as e:
        sys.exit(f"career_seed must expose clear_career(con) and {CARRY_OVER_META_NAME}: {e}")

    keep_settings = os.environ.get("ML_KEEP_OWNER_SETTINGS") == "1"
    con = sqlite3.connect(str(db), timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.execute("PRAGMA foreign_keys=OFF")
    con.isolation_level = None                           # we drive the transaction by hand
    con.execute("BEGIN IMMEDIATE")
    # clear_career opens no transaction and commits nothing (its published contract, tested
    # by the build); it runs inside the one opened above.
    counts = clear_career(con)
    counts = dict(counts or {})

    before = con.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
    # No inherited career: with no current team the app opens on the continent picker instead of
    # loading the owner's save.
    con.execute("DELETE FROM meta WHERE key IN ('current_team_id','current_season_id')")
    dropped_career = [k for (k,) in con.execute("SELECT key FROM meta")
                      if not _keep_meta_key(k, allow)]
    for k in dropped_career:
        con.execute("DELETE FROM meta WHERE key=?", (k,))
    dropped_settings = []
    if not keep_settings:
        for k in OWNER_SETTINGS:
            if con.execute("DELETE FROM meta WHERE key=?", (k,)).rowcount:
                dropped_settings.append(k)
    after = con.execute("SELECT COUNT(*) FROM meta").fetchone()[0]

    # 149 portraits pointed straight at the owner's RFS folder. An absolute path cannot resolve
    # on anyone else's machine, so the card showed a broken image instead of falling back to the
    # generated avatar.
    portraits = con.execute(
        "UPDATE players SET portrait_path=NULL WHERE portrait_path LIKE '_:%'").rowcount

    leaks = {t: rows for t in LEAK_TABLES if (rows := _leak_rows(con, t))}
    if leaks:
        con.execute("ROLLBACK")
        con.close()
        print("REFUSING to ship: the owner's paths are still in the database", file=sys.stderr)
        for t, rows in leaks.items():
            for r in rows:
                print(f"  {t}: {r}", file=sys.stderr)
        if keep_settings:
            print("  (ML_KEEP_OWNER_SETTINGS=1 kept the settings rows — unset it to drop them)",
                  file=sys.stderr)
        return 1

    if args.dry:
        con.execute("ROLLBACK")
    else:
        con.execute("COMMIT")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    print(f"sanitised {db}{' (DRY — rolled back)' if args.dry else ''}")
    for tbl, n in sorted(counts.items(), key=lambda kv: -kv[1] if isinstance(kv[1], int) else 0):
        if n:
            print(f"  career cleared: {tbl:<24} {n}")
    print(f"  meta rows: {before} -> {after}")
    print(f"  meta dropped (career): {len(dropped_career)}"
          + (f" — {', '.join(sorted(dropped_career)[:8])}" if dropped_career else ""))
    if keep_settings:
        print("  meta kept (owner settings): ML_KEEP_OWNER_SETTINGS=1")
    else:
        print(f"  meta dropped (owner settings): {len(dropped_settings)}"
              + (f" — {', '.join(dropped_settings)}" if dropped_settings else ""))
    print(f"  portraits unpinned from absolute paths: {portraits}")
    print("  owner-path scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
