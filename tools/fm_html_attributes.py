#!/usr/bin/env python3
"""
fm_html_attributes.py — import the owner's real FM 1-20 attributes from the batched HTML exports.

Source (see the "Source data" table in CLAUDE.md — check it before assuming data is missing):
    C:\\Users\\tjgg2\\OneDrive\\Documents\\Sports Interactive\\Football Manager 2024\\{B,c..z}.html
25 files, ~490k rows, 69 columns. Repo-root attributes.csv is Fitness/Con/Happiness and is NOT
this data; allplayers.csv carries bio + Best Rating only.

Lands the ladder in fm_attributes(uid, attr, value) — the table tools/fm_attributes_import.py
defines — plus the bio fields the same export carries and the DB is missing: DoB (players.dob is
NULL for all 376k rows), height, weight and preferred foot.

Which columns are attributes is decided FROM THE DATA, not from a hand-typed list: a column whose
non-empty values are overwhelmingly integers in 1..20 is an attribute. That keeps GK codes
(Han/Ref/Cmd/1v1/TRO), the foot ratings and Natural Fitness without guessing at FM's shorthand.

    python tools/fm_html_attributes.py --dry
    python tools/fm_html_attributes.py
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
SRC = Path(r"C:\Users\tjgg2\OneDrive\Documents\Sports Interactive\Football Manager 2024")

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
# columns that are numeric but are NOT the 1-20 ladder
NOT_ATTR = {"uid", "age", "height", "weight", "wage", "ability", "potential", "rec", "inf",
            "won", "clear", "transfer value", "expires", "dob", "name", "position",
            "personality", "preferred foot", "nat"}


def num(s: str):
    """'195 cm' -> 195, '84 kg' -> 84, '' -> None."""
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else None


def cells(block: str) -> list[str]:
    return [TAG.sub("", c).replace("&nbsp;", " ").strip() for c in CELL.findall(block)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    files = sorted([p for p in SRC.glob("*.html")
                    if len(p.stem) == 1 and p.stem.isalpha()], key=lambda p: p.stem.lower())
    if not files:
        sys.exit(f"no batch exports found in {SRC}")
    print(f"{len(files)} FM exports: {', '.join(p.name for p in files)}")

    attrs: dict[int, dict[str, int]] = {}
    bio: dict[int, tuple] = {}
    colstats: dict[str, Counter] = defaultdict(Counter)
    total = 0
    for p in files:
        raw = p.read_text(encoding="utf-8", errors="replace")
        blocks = ROW.findall(raw)
        if not blocks:
            print(f"  {p.name}: no table rows")
            continue
        head = cells(blocks[0])
        idx = {name: i for i, name in enumerate(head)}
        if "UID" not in idx:
            print(f"  {p.name}: no UID column, skipped")
            continue
        n = 0
        for b in blocks[1:]:
            c = cells(b)
            if len(c) < len(head):
                continue
            u = c[idx["UID"]].replace(",", "")
            if not u.isdigit():
                continue
            uid = int(u)
            row = {}
            for name, i in idx.items():
                v = c[i].replace(",", "").strip()
                if v.lstrip("-").isdigit():
                    iv = int(v)
                    colstats[name][1 <= iv <= 20] += 1
                    row[name] = iv
            attrs[uid] = row
            # these three are not plain integers: '195 cm', '84 kg', '27/10/2001 (21 years old)'
            raw_dob = c[idx["DoB"]] if "DoB" in idx else ""
            dob = raw_dob.split("(")[0].strip()
            bio[uid] = (dob, num(c[idx["Height"]]) if "Height" in idx else None,
                        num(c[idx["Weight"]]) if "Weight" in idx else None,
                        c[idx["Preferred Foot"]] if "Preferred Foot" in idx else "")
            n += 1
        total += n
        print(f"  {p.name}: {n:,} players")

    # a column is the ladder if its numeric values are almost entirely 1..20
    ladder = sorted(name for name, c in colstats.items()
                    if name.lower() not in NOT_ATTR and sum(c.values()) > 1000
                    and c[True] / max(1, sum(c.values())) >= 0.97)
    print(f"\nplayers parsed: {total:,} | distinct UIDs: {len(attrs):,}")
    print(f"attribute columns detected ({len(ladder)}): {', '.join(ladder)}")
    rows = [(uid, a, r[a]) for uid, r in attrs.items() for a in ladder if a in r]
    print(f"attribute values to store: {len(rows):,}")
    if dry:
        print("--dry: nothing written.")
        return 0

    con = sqlite3.connect(DB, timeout=180)
    con.execute("""CREATE TABLE IF NOT EXISTS fm_attributes(
        uid INTEGER NOT NULL, attr TEXT NOT NULL, value INTEGER NOT NULL,
        PRIMARY KEY(uid, attr))""")
    con.execute("""CREATE TABLE IF NOT EXISTS fm_bio(
        uid INTEGER PRIMARY KEY, dob TEXT, height INTEGER, weight INTEGER, foot TEXT)""")
    con.execute("BEGIN")
    con.executemany("INSERT OR REPLACE INTO fm_attributes(uid,attr,value) VALUES(?,?,?)", rows)
    con.executemany("INSERT OR REPLACE INTO fm_bio(uid,dob,height,weight,foot) VALUES(?,?,?,?,?)",
                    [(u, b[0] or None, b[1], b[2], b[3] or None) for u, b in bio.items()])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"stored {len(rows):,} attribute values for {len(attrs):,} FM players, "
          f"plus {len(bio):,} bio rows (dob/height/weight/foot).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
