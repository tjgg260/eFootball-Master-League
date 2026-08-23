#!/usr/bin/env python3
"""
genie_import.py — the authoritative overall + potential pass, from a Genie Scout export
(allplayers.csv). Genie's `Best Rating` / `Best Pot Rating` (a %-of-best-position rating) correlate
tightly with real-world reputation — Mbappe/Haaland/Yamal at the top, journeymen in the middle,
limited players at the floor — and, crucially, they sit on ONE scale, so a wonderkid's current
rating and his ceiling are directly comparable (the development runway the growth engine needs).

So Genie owns `players.overall_rating` (Best Rating) and `player_potential` (Best Pot Rating);
the FM data pass owns the granular attribute radar + personality + determination. Run order:
    python tools/fm_data_pass.py       # abilities, traits, personality, skills, height/weight
    python tools/genie_import.py        # overall + potential on Genie's calibrated scale (last)

Join: FM/Genie UID -> master player id: net-new (10_000_000_000 + uid) or overlap (face_<uid>.png).
Idempotent. Reads the CSV only; writes overall_rating + player_potential.

    python tools/genie_import.py [allplayers.csv]   # default: repo-root allplayers.csv
    python tools/genie_import.py --dry              # sanity, write nothing
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"


def pct(v):
    if not v:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", v)
    return float(m.group(1)) if m else None


def money(v):
    """FM currency cell -> int. Handles comma-thousands, K/M suffixes, symbols, '-'/blank."""
    if not v or v.strip() in ("-", ""):
        return None
    s = re.sub(r"[^\d.,KMkm]", "", v)
    mult = 1
    if s[-1:] in "Kk":
        mult, s = 1_000, s[:-1]
    elif s[-1:] in "Mm":
        mult, s = 1_000_000, s[:-1]
    s = s.replace(",", "")
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def uid_map(con):
    """uid -> master player id, the same mapping the FM pass uses."""
    net = {pid - 10_000_000_000: pid for (pid,) in
           con.execute("SELECT id FROM players WHERE id>=10000000000")}
    overlap = {}
    for pid, face in con.execute("SELECT id, real_face_path FROM players "
                                 "WHERE real_face_path LIKE '%face_%' AND id<10000000000"):
        m = re.search(r"face_(\d+)\.png$", face or "")
        if m:
            overlap[int(m.group(1))] = pid
    return net, overlap


def import_market(path: Path, con, dry: bool) -> int:
    """Contract + market layer from a Genie export carrying Value/Contract columns."""
    con.execute("""CREATE TABLE IF NOT EXISTS player_market(
        player_id INTEGER PRIMARY KEY, value INTEGER, sale_value INTEGER, wage INTEGER,
        contract_end TEXT, contract_type TEXT, joined_club TEXT, min_fee INTEGER,
        relegation_fee INTEGER, non_promo_fee INTEGER, squad_status TEXT,
        perceived_status TEXT, transfer_status TEXT, squad_rep TEXT,
        int_caps INTEGER, int_goals INTEGER)""")
    net, overlap = uid_map(con)
    rows, seen, matched = [], 0, 0
    with open(path, encoding="cp1252", errors="replace", newline="") as f:
        for d in csv.DictReader(f, delimiter=";"):
            uid = (d.get("Unique ID") or "").strip()
            if not uid.isdigit():
                continue
            seen += 1
            pid = net.get(int(uid)) or overlap.get(int(uid))
            if pid is None:
                continue
            matched += 1
            rows.append((pid, money(d.get("Value")), money(d.get("Sale Value")),
                         money(d.get("Wage")), _txt(d.get("Contract End")),
                         _txt(d.get("Contract Type")), _txt(d.get("Joined Club")),
                         money(d.get("Minimum Fee")), money(d.get("Relegation Fee")),
                         money(d.get("Non Promotion Fee")), _txt(d.get("Squad Status")),
                         _txt(d.get("Perceived Squad Status")), _txt(d.get("Transfer Status")),
                         _txt(d.get("Squad Rep")), _int(d.get("Int Caps")), _int(d.get("Int Goals"))))
    print(f"{path.name}: {seen:,} rows, {matched:,} matched -> player_market")
    if dry:
        for r in rows[:6]:
            print(f"    pid={r[0]} value={r[1]} wage={r[3]} end={r[4]} status={r[10]}")
        return 0
    con.execute("BEGIN")
    con.executemany("INSERT OR REPLACE INTO player_market VALUES(" + ",".join("?" * 16) + ")", rows)
    con.commit()
    print(f"wrote {len(rows):,} market rows.")
    return 0


def _txt(v):
    v = (v or "").strip()
    return v if v and v != "-" else None


def _int(v):
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    path = Path(args[0]) if args else REPO / "allplayers.csv"
    if not path.exists():
        sys.exit(f"not found: {path}")

    # Route by columns: a ratings export (Best Rating) vs a market export (Value/Contract).
    with open(path, encoding="cp1252", errors="replace") as f:
        header = f.readline()
    if "Best Rating" not in header and ("Value" in header or "Contract End" in header):
        con = sqlite3.connect(DB)
        return import_market(path, con, dry)

    con = sqlite3.connect(DB)
    net, overlap = uid_map(con)
    ovr_rows, pot_rows = [], []
    seen = matched = 0
    top = []
    with open(path, encoding="cp1252", errors="replace", newline="") as f:
        for d in csv.DictReader(f, delimiter=";"):
            uid = (d.get("Unique ID") or "").strip()
            if not uid.isdigit():
                continue
            seen += 1
            pid = net.get(int(uid)) or overlap.get(int(uid))
            if pid is None:
                continue
            cur = pct(d.get("Best Rating"))
            pot = pct(d.get("Best Pot Rating"))
            if cur is None and pot is None:
                continue
            matched += 1
            overall = max(1, min(99, round(cur))) if cur is not None else None
            potential = round(pot) if pot is not None else overall
            if overall is not None:
                potential = max(overall, min(99, potential))
                ovr_rows.append((overall, pid))
            if potential is not None:
                pot_rows.append((pid, min(99, potential)))
            if dry and len(top) < 12 and cur and cur >= 88:
                top.append((cur, pot, d.get("Name", ""), d.get("Age", "")))

    print(f"{path.name}: {seen:,} rows, {matched:,} matched to master players "
          f"({sum(1 for u in net if u in net):,} net-new base)")
    print(f"  overall updates: {len(ovr_rows):,}   potential updates: {len(pot_rows):,}")
    if dry:
        for cur, pot, nm, age in sorted(top, reverse=True):
            print(f"    {cur:5.1f} -> pot {pot}  age {age}  {nm}")
        return 0

    con.execute("BEGIN")
    con.executemany("UPDATE players SET overall_rating=? WHERE id=?", ovr_rows)
    con.executemany("INSERT OR REPLACE INTO player_potential(player_id,potential) VALUES(?,?)",
                    pot_rows)
    con.commit()
    print(f"wrote {len(ovr_rows):,} overalls + {len(pot_rows):,} potentials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
