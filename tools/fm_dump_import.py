#!/usr/bin/env python3
"""
fm_dump_import.py — land ANY FM "Print -> Web Page (.html)" or text export into master.db,
losslessly, into a staging table. FM's export carries every column in the active view, so this
is the full-fidelity dump route (players, staff, clubs, competitions).

Entity is auto-detected from the columns:
  * players       -> has UID + attribute columns (Fin/Pas/Acc…)   -> fm_players_raw + fm_attributes
  * staff         -> has UID + staff attrs (Judging/Working…) or no player attrs but a role
  * teams (clubs) -> has a club identifier, no UID per row of players
  * competitions  -> league/reputation columns

Every export also lands verbatim in fm_raw_<entity>(key, col, val) so nothing is ever lost; the
curated tables (fm_attributes, fm_staff_attributes) are cherry-picked from it.

    python tools/fm_dump_import.py <export.html> [more.html ...]
    python tools/fm_dump_import.py --entity staff staff_export.html   # force entity
"""
from __future__ import annotations

import html
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

from fm_attributes_import import FM_ATTRS  # reuse the player-attribute label map  # noqa: E402

# staff (coach/scout) 1-20 attributes FM exports
STAFF_ATTRS = {
    "Adaptability": "adaptability", "Ambition": "ambition", "Controversy": "controversy",
    "Loyalty": "loyalty", "Pressure": "handling_pressure", "Professionalism": "professionalism",
    "Sportsmanship": "sportsmanship", "Temperament": "temperament",
    "Determination": "determination", "Attacking": "attacking", "Defending": "defending",
    "Fitness": "fitness_coaching", "Mental": "mental_coaching", "Tactical": "tactical",
    "Technical": "technical_coaching", "Working With Youngsters": "working_with_youngsters",
    "Discipline": "discipline", "Motivating": "motivating", "Man Management": "man_management",
    "Judging Player Ability": "judging_ability", "Judging Player Potential": "judging_potential",
    "Judging Team Data": "judging_team_data", "Tactical Knowledge": "tactical_knowledge",
    "Negotiating": "negotiating", "Level of Discipline": "discipline",
}


def rows_of(path: Path):
    if path.suffix.lower() in (".html", ".htm"):
        text = path.read_bytes().decode("utf-8", "replace")
        body = re.split(r"<table[^>]*>", text, maxsplit=1)[-1]
        for tr in re.split(r"<tr[^>]*>", body):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
            if cells:
                yield [html.unescape(re.sub(r"<.*?>", "", c)).strip() for c in cells]
    else:
        import csv
        import io
        text = path.read_bytes().decode("cp1252", "replace")
        yield from csv.reader(io.StringIO(text), delimiter=";")


def detect(cols: set[str]) -> str:
    has_uid = "UID" in cols or "Unique ID" in cols
    player_attrs = sum(1 for c in cols if c in FM_ATTRS)
    staff_attrs = sum(1 for c in cols if c in STAFF_ATTRS)
    if player_attrs >= 6 and has_uid:
        return "players"
    if staff_attrs >= 4:
        return "staff"
    if any(c in cols for c in ("Reputation", "Rep", "Stadium", "Capacity", "Balance",
                               "Founded", "Nickname")) and not has_uid:
        return "teams"
    if any(c in cols for c in ("Competition", "Nation", "Reputation")) and "Team" not in cols:
        return "competitions"
    return "unknown"


def ingest(path: Path, con: sqlite3.Connection, force: str | None) -> tuple[str, int]:
    it = rows_of(path)
    header = [h.strip().strip('"') for h in next(it)]
    cols = {n: i for i, n in enumerate(header)}
    entity = force or detect(set(cols))
    key_col = ("UID" if "UID" in cols else "Unique ID" if "Unique ID" in cols
               else "Name" if "Name" in cols else header[0])
    key_ix = cols[key_col]

    raw_tbl = f"fm_raw_{entity}"
    con.execute(f"CREATE TABLE IF NOT EXISTS {raw_tbl}(key TEXT, col TEXT, val TEXT, "
                "PRIMARY KEY(key, col))")
    attr_map = FM_ATTRS if entity == "players" else STAFF_ATTRS if entity == "staff" else {}
    attr_tbl = ("fm_attributes" if entity == "players"
                else "fm_staff_attributes" if entity == "staff" else None)
    if attr_tbl:
        con.execute(f"CREATE TABLE IF NOT EXISTS {attr_tbl}("
                    "uid INTEGER, attr TEXT, value INTEGER, PRIMARY KEY(uid, attr))")

    n = 0
    raw_batch, attr_batch = [], []
    for r in it:
        if len(r) <= key_ix or not r[key_ix].strip():
            continue
        key = r[key_ix].strip()
        n += 1
        for name, ix in cols.items():
            if ix < len(r) and r[ix].strip():
                raw_batch.append((key, name, r[ix].strip()))
        if attr_tbl and key.isdigit():
            uid = int(key)
            for name, akey in attr_map.items():
                ix = cols.get(name)
                if ix is not None and ix < len(r):
                    v = r[ix].strip()
                    if v.isdigit() and 1 <= int(v) <= 20:
                        attr_batch.append((uid, akey, int(v)))
        if len(raw_batch) >= 40_000:
            con.executemany(f"INSERT OR REPLACE INTO {raw_tbl}(key,col,val) VALUES(?,?,?)", raw_batch)
            raw_batch.clear()
    if raw_batch:
        con.executemany(f"INSERT OR REPLACE INTO {raw_tbl}(key,col,val) VALUES(?,?,?)", raw_batch)
    if attr_batch:
        con.executemany(f"INSERT OR REPLACE INTO {attr_tbl}(uid,attr,value) VALUES(?,?,?)", attr_batch)
    print(f"{path.name}: {entity} — {n:,} rows, {len(header)} cols"
          + (f", {len(set(a for _,a,_ in attr_batch))} attrs -> {attr_tbl}" if attr_tbl else ""))
    return entity, n


def main() -> int:
    args = sys.argv[1:]
    force = None
    if args and args[0] == "--entity":
        force = args[1]
        args = args[2:]
    files = [Path(a) for a in args] or sorted(REPO.glob("fm_dump_*.html"))
    if not files:
        sys.exit("usage: python tools/fm_dump_import.py <export.html> [...]")
    con = sqlite3.connect(DB)
    for f in files:
        ingest(f, con, force)
    con.commit()
    print("\nstaging tables:")
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fm_%'"):
        c = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {c:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
