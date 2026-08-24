#!/usr/bin/env python3
"""
fm_bio_apply.py — use the bio the FM exports carry and the database has been missing.

tools/fm_html_attributes.py parked DoB, height, weight and preferred foot for 425,555 players in
fm_bio. players.dob was NULL for all 376k rows, which is why every same-human test this project
runs has had to lean on name spelling and an age tolerance instead of the one field that settles
identity outright.

Priority follows the blueprint: eFootball is the authority for players it has (height, weight and
foot come from samples/editor-bundled-players.csv for them), FM fills everything else.

DoB IS DELIBERATELY NOT WRITTEN TO players.dob. FM's birth dates in this export are shifted —
Neymar reads 05/02/1989 against a real 1992, Haaland and Bellingham likewise land three years
early — so deriving age from them aged 120,115 players wrongly on the first run (Haaland 26 -> 29).
The dates stay in fm_bio, where they are labelled as FM's, and are usable for MATCHING (the shift
is consistent within FM) but never as a displayed fact or an age source. players.age keeps the
value it already had.

    python tools/fm_bio_apply.py --dry
    python tools/fm_bio_apply.py
"""
from __future__ import annotations

import csv
import io
import shutil
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
EFCSV = REPO / "samples" / "editor-bundled-players.csv"
# the squad snapshot the FM exports were taken from; ages are stated against it
SNAPSHOT = date(2026, 8, 22)


def parse_dob(s: str):
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=240)
    cur = con.cursor()

    rows = list(csv.DictReader(io.StringIO(EFCSV.read_bytes().decode("utf-8-sig"))))
    export = {int(r["player_id"]) for r in rows if (r.get("player_id") or "").isdigit()}
    protected = set(export)
    for pid, ep in con.execute(
            "SELECT player_id, ef_pid FROM player_identity WHERE ef_pid IS NOT NULL"):
        if ep in export:
            protected.add(pid)

    bio = {uid: (dob, h, w, f) for uid, dob, h, w, f in
           con.execute("SELECT uid, dob, height, weight, foot FROM fm_bio")}
    print(f"fm_bio rows: {len(bio):,}")

    cur_state = {pid: (dob, h, w) for pid, dob, h, w in
                 con.execute("SELECT id, dob, height_cm, weight_kg FROM players")}
    dob_rows, phys_rows, foot_rows, age_rows = [], [], [], []
    for pid, uid in con.execute(
            "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"):
        b = bio.get(uid)
        if not b or pid not in cur_state:
            continue
        dob_s, h, w, foot = b
        d = parse_dob(dob_s)
        have_dob, have_h, have_w = cur_state[pid]
        _ = d, have_dob        # see the docstring: FM's DoB is shifted, so it stays in fm_bio
        if pid not in protected:                     # eFootball owns its own players' physique
            if h and not have_h:
                phys_rows.append((h, pid, "h"))
            if w and not have_w:
                phys_rows.append((w, pid, "w"))
            if foot:
                foot_rows.append((1 if foot.strip().lower().startswith("left") else 0, pid))
    print(f"dob to fill: {len(dob_rows):,} | ages recomputed from birthday: {len(age_rows):,}")
    print(f"height/weight to fill: {len(phys_rows):,} | preferred foot: {len(foot_rows):,}")
    if dry:
        print("--dry: nothing written.")
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prebio")
    cur.execute("BEGIN")
    cur.executemany("UPDATE players SET dob=? WHERE id=?", dob_rows)
    cur.executemany("UPDATE players SET age=? WHERE id=?", age_rows)
    cur.executemany("UPDATE players SET height_cm=? WHERE id=? AND ?='h'",
                    [(v, p, k) for v, p, k in phys_rows if k == "h"])
    cur.executemany("UPDATE players SET weight_kg=? WHERE id=? AND ?='w'",
                    [(v, p, k) for v, p, k in phys_rows if k == "w"])
    cur.executemany("INSERT OR REPLACE INTO player_attributes(player_id,attribute,value) "
                    "VALUES(?, 'foot', ?)", [(p, v) for v, p in foot_rows])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    n = cur.execute("SELECT COUNT(*) FROM players WHERE dob IS NOT NULL").fetchone()[0]
    print(f"applied. players with a real date of birth: {n:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
