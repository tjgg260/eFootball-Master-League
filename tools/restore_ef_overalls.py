#!/usr/bin/env python3
"""
restore_ef_overalls.py — eFootball's own players keep eFootball's own rating.

The owner ruling on attributes is that a player who exists in eFootball is not re-derived; the
export is his data. fix_overalls recomputes overall_rating from the abilities with a model fitted
on those same native players, which is exactly right for everyone the model has to guess at — and
wrong for the ones whose real answer is sitting in the CSV. 9,516 drifted, and the model's weakest
spot is goalkeepers, whose rating leans on abilities an outfield-shaped fit barely sees:

    Donnarumma  export 83  ->  74        Onana    export 77  ->  69
    Forster     export 74  ->  66        Perri    export 75  ->  67

Copy the export's value back for every eFootball record it covers. Two rows are left alone: the
placeholder pair that carries 116 (every attribute 95 — fix_overalls' own note), which is above
the game's 99 ceiling and is not a rating at all.

    python tools/restore_ef_overalls.py --dry
    python tools/restore_ef_overalls.py
"""
from __future__ import annotations

import csv
import io
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
EFCSV = REPO / "samples" / "editor-bundled-players.csv"
CEILING = 99


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    rows = list(csv.DictReader(io.StringIO(EFCSV.read_bytes().decode("utf-8-sig"))))
    exp = {int(r["player_id"]): int(r["overall_rating"]) for r in rows
           if (r.get("player_id") or "").isdigit() and (r.get("overall_rating") or "").isdigit()}
    ours = dict(con.execute("SELECT id, overall_rating FROM players"))

    fix, skipped = [], 0
    for pid, want in exp.items():
        have = ours.get(pid)
        if have is None or have == want:
            continue
        if want > CEILING:
            skipped += 1                            # placeholder rows, not ratings
            continue
        fix.append((want, pid))

    print(f"eFootball players whose stored overall drifted from the export: {len(fix):,} "
          f"(placeholder rows above {CEILING} left alone: {skipped})")
    d = Counter(ours[p] - w for w, p in fix)
    print(f"   drift (ours - export): {d.most_common(5)}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fix:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preefoverall")
    con.executemany("UPDATE players SET overall_rating=? WHERE id=?", fix)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(fix):,} ratings restored from eFootball's export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
