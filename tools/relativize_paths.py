#!/usr/bin/env python3
"""
relativize_paths.py — one-off migration: rewrite stored asset paths from absolute to repo-relative.

The DB audit found every stored file path (players.real_face_path, players.portrait_path,
teams.logo_path, and the team "logo" fields in build/catalog.json) was absolute, so moving or
renaming the repo broke all of them. This rewrites any path under the repo root to a
forward-slash relative path ("facepack/webp/face_123.webp"); the app and tools resolve those
against the repo root. Paths OUTSIDE the repo (the OneDrive RFS portraits) and values that are
already relative are left untouched.

Backs up build/master.db -> build/master.db.bak-prerel and build/catalog.json ->
build/catalog.json.bak-prerel before writing.

    python tools/relativize_paths.py --dry    # per-column counts, no writes
    python tools/relativize_paths.py          # back up, then rewrite DB + catalog
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"

# Repo-root prefix, normalised to forward slashes with a trailing slash, compared
# case-insensitively so "c:\users\..." and "C:/Users/..." both match.
_ROOT = str(REPO).replace("\\", "/").rstrip("/") + "/"
_ROOT_LOWER = _ROOT.lower()

DB_COLUMNS = [
    ("players", "real_face_path"),
    ("players", "portrait_path"),
    ("teams", "logo_path"),
]


def relativize(value: str | None) -> str | None:
    """Repo-relative forward-slash form of value, or None if it should be left alone
    (empty, already relative, or outside the repo — e.g. the OneDrive RFS paths)."""
    if not value:
        return None
    norm = value.replace("\\", "/")
    if not norm.lower().startswith(_ROOT_LOWER):
        return None
    rel = norm[len(_ROOT):].lstrip("/")
    return rel or None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv

    con = sqlite3.connect(DB, timeout=60)
    db_updates: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for table, col in DB_COLUMNS:
        ups: list[tuple[str, int]] = []
        untouched = 0
        for rowid, val in con.execute(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL"):
            rel = relativize(val)
            if rel is not None:
                ups.append((rel, rowid))
            else:
                untouched += 1
        db_updates[(table, col)] = ups
        print(f"{table}.{col}: {len(ups):,} to relativize | {untouched:,} untouched "
              f"(non-repo or already relative)")

    cat = json.loads(CAT.read_text(encoding="utf-8"))
    cat_hits = cat_untouched = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                cur = t.get("logo")
                if not cur:
                    continue
                rel = relativize(cur)
                if rel is not None:
                    t["logo"] = rel
                    cat_hits += 1
                else:
                    cat_untouched += 1
    print(f"catalog.json team logos: {cat_hits:,} to relativize | {cat_untouched:,} untouched")

    total_db = sum(len(u) for u in db_updates.values())
    if dry:
        print(f"dry run — would rewrite {total_db:,} DB paths + {cat_hits:,} catalog logos. "
              f"Nothing written.")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-prerel")
    shutil.copy2(CAT, str(CAT) + ".bak-prerel")
    con.execute("BEGIN")
    for (table, col), ups in db_updates.items():
        if ups:
            con.executemany(f"UPDATE {table} SET {col}=? WHERE id=?", ups)
    con.commit()
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"done: {total_db:,} DB paths + {cat_hits:,} catalog logos rewritten "
          f"(backups: master.db.bak-prerel, catalog.json.bak-prerel)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
