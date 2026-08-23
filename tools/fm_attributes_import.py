#!/usr/bin/env python3
"""
fm_attributes_import.py — ingest FM's real 1-20 attributes from in-game view exports.

Feed it one or more FM print-exports (semicolon CSV, cp1252 — the allplayers.csv format) that
contain `Unique ID` plus any attribute columns (Technical/Mental/Physical/Goalkeeping). Multiple
files are joined on Unique ID, so a two-pass export (column-count limits) works fine.

Raw FM attributes land in their own table (they're 1-20 scale, NOT eFootball 40-99):

    fm_attributes(uid INTEGER, attr TEXT, value INTEGER, PRIMARY KEY(uid, attr))

The eFootball-scale conversion happens in the data pass (position-aware curves), not here —
this importer just gets the truth into the DB losslessly.

    python tools/fm_attributes_import.py attributes_full.csv [attributes_full2.csv ...]
"""
from __future__ import annotations

import csv
import io
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

# FM column label -> canonical attribute key (lowercase snake). Every 1-20 attribute FM shows.
FM_ATTRS = {
    # technical
    "Cor": "corners", "Cro": "crossing", "Dri": "dribbling", "Fin": "finishing",
    "Fir": "first_touch", "Fre": "free_kick_taking", "Hea": "heading", "Lon": "long_shots",
    "L Th": "long_throws", "Mar": "marking", "Pas": "passing", "Pen": "penalty_taking",
    "Tck": "tackling", "Tec": "technique",
    # mental
    "Agg": "aggression", "Ant": "anticipation", "Bra": "bravery", "Cmp": "composure",
    "Cnt": "concentration", "Dec": "decisions", "Det": "determination", "Fla": "flair",
    "Ldr": "leadership", "OtB": "off_the_ball", "Pos": "positioning", "Tea": "teamwork",
    "Vis": "vision", "Wor": "work_rate",
    # physical
    "Acc": "acceleration", "Agi": "agility", "Bal": "balance", "Jum": "jumping_reach",
    "Nat": "natural_fitness", "Pac": "pace", "Sta": "stamina", "Str": "strength",
    # goalkeeping
    "Aer": "aerial_reach", "Cmd": "command_of_area", "Com": "communication",
    "Ecc": "eccentricity", "Han": "handling", "Kic": "kicking", "1v1": "one_on_ones",
    "Pun": "punching", "Ref": "reflexes", "TRO": "rushing_out", "Thr": "throwing",
    # long-form labels (FM sometimes prints full names)
    "Corners": "corners", "Crossing": "crossing", "Dribbling": "dribbling",
    "Finishing": "finishing", "First Touch": "first_touch", "Free Kick Taking": "free_kick_taking",
    "Heading": "heading", "Long Shots": "long_shots", "Long Throws": "long_throws",
    "Marking": "marking", "Passing": "passing", "Penalty Taking": "penalty_taking",
    "Tackling": "tackling", "Technique": "technique", "Aggression": "aggression",
    "Anticipation": "anticipation", "Bravery": "bravery", "Composure": "composure",
    "Concentration": "concentration", "Decisions": "decisions", "Determination": "determination",
    "Flair": "flair", "Leadership": "leadership", "Off The Ball": "off_the_ball",
    "Positioning": "positioning", "Teamwork": "teamwork", "Vision": "vision",
    "Work Rate": "work_rate", "Acceleration": "acceleration", "Agility": "agility",
    "Balance": "balance", "Jumping Reach": "jumping_reach", "Natural Fitness": "natural_fitness",
    "Pace": "pace", "Stamina": "stamina", "Strength": "strength", "Aerial Reach": "aerial_reach",
    "Command Of Area": "command_of_area", "Communication": "communication",
    "Eccentricity": "eccentricity", "Handling": "handling", "Kicking": "kicking",
    "One On Ones": "one_on_ones", "Punching": "punching", "Reflexes": "reflexes",
    "Rushing Out": "rushing_out", "Throwing": "throwing",
}


def _html_rows(text: str):
    """FM's 'Print → Web Page' export: one <table>, header <th>, cells <td>. Yields lists."""
    import html
    import re
    body = re.split(r"<table[^>]*>", text, 1)[-1]
    for tr in re.split(r"<tr[^>]*>", body):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
        if cells:
            yield [html.unescape(re.sub(r"<.*?>", "", c)).strip() for c in cells]


def ingest(path: Path, con: sqlite3.Connection) -> tuple[int, int]:
    if path.suffix.lower() in (".html", ".htm"):
        text = path.read_bytes().decode("utf-8", "replace")
        rows = iter(list(_html_rows(text)))
    else:
        text = path.read_bytes().decode("cp1252", "replace")
        rows = csv.reader(io.StringIO(text), delimiter=";")
    header = next(rows)
    cols = {n.strip().strip('"'): i for i, n in enumerate(header)}
    uid_key = "Unique ID" if "Unique ID" in cols else ("UID" if "UID" in cols else None)
    if uid_key is None:
        sys.exit(f"{path.name}: no 'Unique ID' column — add it to the FM view and re-export")
    uid_ix = cols[uid_key]
    attr_cols = [(ix, FM_ATTRS[name]) for name, ix in cols.items() if name in FM_ATTRS]
    if not attr_cols:
        sys.exit(f"{path.name}: no recognised attribute columns. Header: {header[:20]}")
    print(f"{path.name}: {len(attr_cols)} attribute columns "
          f"({', '.join(sorted(set(a for _, a in attr_cols))[:8])}…)")
    n = wrote = 0
    batch = []
    for r in rows:
        if len(r) <= uid_ix or not r[uid_ix].strip().isdigit():
            continue
        uid = int(r[uid_ix])
        n += 1
        for ix, key in attr_cols:
            if ix < len(r):
                v = r[ix].strip()
                if v.isdigit() and 1 <= int(v) <= 20:
                    batch.append((uid, key, int(v)))
                    wrote += 1
        if len(batch) >= 50_000:
            con.executemany(
                "INSERT OR REPLACE INTO fm_attributes(uid,attr,value) VALUES(?,?,?)", batch)
            batch.clear()
    if batch:
        con.executemany("INSERT OR REPLACE INTO fm_attributes(uid,attr,value) VALUES(?,?,?)", batch)
    return n, wrote


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        # default: any attributes_full*.csv in the repo root
        files = sorted(REPO.glob("attributes_full*.csv"))
    if not files:
        sys.exit("usage: python tools/fm_attributes_import.py <fm-export.csv> [...]")
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS fm_attributes("
                "uid INTEGER, attr TEXT, value INTEGER, PRIMARY KEY(uid, attr))")
    total_rows = total_vals = 0
    for f in files:
        r, w = ingest(f, con)
        total_rows += r
        total_vals += w
    con.commit()
    uids = con.execute("SELECT COUNT(DISTINCT uid) FROM fm_attributes").fetchone()[0]
    print(f"\nfm_attributes now covers {uids:,} players "
          f"({con.execute('SELECT COUNT(*) FROM fm_attributes').fetchone()[0]:,} values).")
    print("Next: the data pass maps these onto eFootball-scale abilities position-aware.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
