#!/usr/bin/env python3
"""
fm_ingest_staff.py — lean, crash-safe ingest of an FM "Print -> Web Page" STAFF export. FM uses
short attribute codes (Det, Mgm, Judge A...); this maps the clear ones to canonical names into
fm_staff_attributes(uid, attr, value) and lands EVERY column losslessly in fm_raw_staff(key,col,val)
so identity / role / tactical-preference fields are never dropped. WAL + per-file commits.

    python tools/fm_ingest_staff.py "stafffull.html" [...]
"""
from __future__ import annotations

import html
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

# FM staff short code -> canonical 1-20 attribute.
STAFF_SHORT = {
    "Det": "determination", "Ada": "adaptability", "Mgm": "man_management", "Mot": "motivating",
    "Dis": "discipline", "Negotiating": "negotiating", "Men": "coaching_mental",
    "Att": "coaching_attacking", "Def": "coaching_defending", "Tec": "coaching_technical",
    "TCo": "coaching_technique", "Fit": "coaching_fitness", "Tac Knw": "tactical_knowledge",
    "Jud SA": "judging_staff_ability", "Judge P": "judging_player_potential",
    "Judge A": "judging_player_ability", "GkS": "coaching_gk_shot_stopping",
    "GkH": "coaching_gk_handling", "GkD": "coaching_gk_distribution",
    "Phy": "physiotherapy", "SpS": "sports_science", "Ana D": "analysing_data",
    "Youth": "working_with_youngsters",
}


def rows_of(path: Path):
    text = path.read_bytes().decode("utf-8", "replace")
    body = re.split(r"<table[^>]*>", text, maxsplit=1)[-1]
    for tr in re.split(r"<tr[^>]*>", body):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
        if cells:
            yield [html.unescape(re.sub(r"<.*?>", "", c)).strip() for c in cells]


def ingest(path: Path, con: sqlite3.Connection) -> int:
    it = rows_of(path)
    header = next(it)
    ix = {}
    for i, n in enumerate(header):
        ix.setdefault(n, i)          # first occurrence wins (UID appears twice)
    if "UID" not in ix:
        print(f"  {path.name}: no UID, skipped"); return 0
    ui = ix["UID"]
    attr_ix = {ix[c]: k for c, k in STAFF_SHORT.items() if c in ix}
    keep = [(i, n) for n, i in ix.items() if n]   # all named columns -> raw

    attr_rows, raw_rows, n = [], [], 0
    for r in it:
        if len(r) <= ui or not r[ui].strip().isdigit():
            continue
        uid = int(r[ui].strip()); n += 1
        for j, k in attr_ix.items():
            if j < len(r) and r[j].strip().lstrip("-").isdigit():
                v = int(r[j].strip())
                if 1 <= v <= 20:
                    attr_rows.append((uid, k, v))
        for j, name in keep:
            if j < len(r) and r[j].strip():
                raw_rows.append((str(uid), name, r[j].strip()))
    con.executemany("INSERT OR REPLACE INTO fm_staff_attributes(uid,attr,value) VALUES(?,?,?)", attr_rows)
    con.executemany("INSERT OR REPLACE INTO fm_raw_staff(key,col,val) VALUES(?,?,?)", raw_rows)
    print(f"  {path.name}: {n:,} staff -> {len(attr_rows):,} attrs, {len(raw_rows):,} raw fields")
    return n


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        sys.exit("usage: python tools/fm_ingest_staff.py <stafffull.html> [...]")
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("CREATE TABLE IF NOT EXISTS fm_staff_attributes(uid INTEGER, attr TEXT, "
                "value INTEGER, PRIMARY KEY(uid,attr))")
    con.execute("CREATE TABLE IF NOT EXISTS fm_raw_staff(key TEXT, col TEXT, val TEXT, "
                "PRIMARY KEY(key,col))")
    total = 0
    for f in files:
        con.execute("BEGIN"); total += ingest(f, con); con.commit()
    print(f"done: {total:,} staff ingested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
