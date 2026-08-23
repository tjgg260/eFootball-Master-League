#!/usr/bin/env python3
"""
fm_ingest_lean.py — fast FM HTML ingest for the data pass. The full fm_dump_import writes all 69
columns x every row into fm_raw_players (millions of rows, one giant transaction — the 1.5h job).
The data pass only needs the 47 attributes (-> fm_attributes) and three raw fields (Personality,
Height, Weight -> fm_raw_players), so this writes ONLY those, with bulk PRAGMAs. Minutes, not hours.

    python tools/fm_ingest_lean.py "PlayersA.html" "B.html" [...]

Idempotent (INSERT OR REPLACE keyed on uid). Run the data pass afterwards:
    python tools/fm_data_pass.py
"""
from __future__ import annotations

import html
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
sys.path.insert(0, str(REPO / "tools"))
from fm_attributes_import import FM_ATTRS  # noqa: E402

RAW_KEEP = ("Personality", "Height", "Weight", "Position")


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
    ix = {n: i for i, n in enumerate(header)}
    uid_col = "UID" if "UID" in ix else "Unique ID"
    if uid_col not in ix:
        print(f"  {path.name}: no UID column, skipped")
        return 0
    ui = ix[uid_col]
    attr_ix = {ix[c]: k for c, k in FM_ATTRS.items() if c in ix}
    raw_ix = {ix[c]: c for c in RAW_KEEP if c in ix}

    attr_rows, raw_rows, n = [], [], 0
    for r in it:
        if len(r) <= ui or not r[ui].strip().isdigit():
            continue
        uid = int(r[ui].strip())
        n += 1
        for j, k in attr_ix.items():
            if j < len(r) and r[j].strip().isdigit():
                v = int(r[j].strip())
                if 1 <= v <= 20:
                    attr_rows.append((uid, k, v))
        for j, c in raw_ix.items():
            if j < len(r) and r[j].strip():
                raw_rows.append((str(uid), c, r[j].strip()))

    con.executemany("INSERT OR REPLACE INTO fm_attributes(uid,attr,value) VALUES(?,?,?)", attr_rows)
    con.executemany("INSERT OR REPLACE INTO fm_raw_players(key,col,val) VALUES(?,?,?)", raw_rows)
    print(f"  {path.name}: {n:,} players -> {len(attr_rows):,} attrs, {len(raw_rows):,} raw fields")
    return n


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        sys.exit("usage: python tools/fm_ingest_lean.py <export.html> [...]")
    con = sqlite3.connect(DB)
    # WAL is crash-safe (a killed process can't corrupt) AND fast; NORMAL sync is the safe default.
    # NEVER journal_mode=MEMORY here — a mid-write kill corrupts the DB (learned the hard way).
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("CREATE TABLE IF NOT EXISTS fm_attributes(uid INTEGER, attr TEXT, value INTEGER, "
                "PRIMARY KEY(uid,attr))")
    con.execute("CREATE TABLE IF NOT EXISTS fm_raw_players(key TEXT, col TEXT, val TEXT, "
                "PRIMARY KEY(key,col))")
    total = 0
    for f in files:
        con.execute("BEGIN")
        total += ingest(f, con)
        con.commit()        # commit per file so partial progress survives an interruption
    print(f"done: {total:,} player-rows ingested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
