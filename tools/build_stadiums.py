#!/usr/bin/env python3
"""
build_stadiums.py — give every catalog club a home ground: stadiums(id, name, capacity, team_id).

Sources, in priority order (every field carries provenance, per the blueprint):

  NAME      1. teams.home_stadium               (source 'teams' — empty today, honoured if filled)
            2. RFS teamstadiumlinks             (source 'rfs' — real names, joined by the FIXED id
               offset from rfs_full_import.py: master team id = 3,000,000 + rfs_team_id. This is
               the preserved-id mapping, NOT name matching.)
            3. generated                        (source 'gen' — deterministic, country-styled:
               "Estadio X" / "Stadio X" / "X Stadium"..., suffix picked by md5(team_id))

  CAPACITY  1. fm_clubs.stadium_cap             (source 'fm' — all zero in the current export,
               honoured if a future export carries it) via team_identity.fm_club_id
            2. from fm_clubs.av_att             (source 'est_att' — real average attendance
               divided by a reputation-scaled utilisation; estimate, deterministic)
            3. from fm_clubs.reputation         (source 'est_rep' — FM-linked but no attendance)
            4. from catalog squad rating        (source 'est' — no FM link at all)
            All est* values are deterministic estimates, clamped to [800, 110000] and rounded.

Scope is the catalog (build/catalog.json — the clubs a career can actually use). The stadiums
table is rebuilt from scratch on every apply (compiled-artifact rule: rebuild, don't patch);
nothing else in the database is touched. The FM join goes through team_identity only.

    python tools/build_stadiums.py            # dry report (default): coverage counts, samples
    python tools/build_stadiums.py --apply    # back up master.db, rebuild the stadiums table
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"

RFS_TEAM_OFFSET = 3_000_000     # rfs_full_import.py: teams = 3,000,000 + rfs_team_id (fixed)
CAP_MIN, CAP_MAX = 800, 110_000

# leading/trailing club-form tokens stripped before generating a stadium name
CLUB_STOP = {"fc", "cf", "afc", "ac", "sc", "cd", "ud", "sd", "ca", "kf", "fk", "sk", "nk",
             "if", "bk", "us", "as", "rc", "sv", "vfb", "vfl", "tsv", "fsv", "spvgg", "ks",
             "pfc", "cfr", "csa", "aek", "club", "de", "1", "1899", "1900", "ec", "aa"}

# country -> deterministic name pattern for generated grounds; anything else gets the
# English-style "<core> <Stadium|Arena|Park>" picked by md5(team_id)
NAME_PATTERNS = {
    "spain": "Estadio {n}", "argentina": "Estadio {n}", "mexico": "Estadio {n}",
    "chile": "Estadio {n}", "colombia": "Estadio {n}", "peru": "Estadio {n}",
    "uruguay": "Estadio {n}", "ecuador": "Estadio {n}", "venezuela": "Estadio {n}",
    "bolivia": "Estadio {n}", "paraguay": "Estadio {n}",
    "portugal": "Estádio {n}", "brazil": "Estádio {n}",
    "italy": "Stadio {n}", "france": "Stade {n}", "germany": "{n}-Stadion",
    "austria": "{n}-Stadion", "switzerland": "{n}-Stadion",
    "netherlands": "{n} Stadion", "holland": "{n} Stadion", "belgium": "{n} Stadion",
    "denmark": "{n} Stadion", "norway": "{n} Stadion", "sweden": "{n} Stadion",
    "poland": "Stadion {n}", "croatia": "Stadion {n}", "serbia": "Stadion {n}",
    "bosnia": "Stadion {n}", "bulgaria": "Stadion {n}", "romania": "Stadionul {n}",
    "turkey": "{n} Stadyumu", "greece": "Stadio {n}",
}
GENERIC_SUFFIXES = ["Stadium", "Stadium", "Arena", "Park"]   # Stadium weighted 2x


def load_rfs_stadium_names() -> dict[int, str]:
    """rfs_team_id -> stadium name from RFS teamstadiumlinks (u32 team id at 0, then a
    30-byte null-padded UTF-8 name — same fixed-width record style rfs_import.py reads).
    Empty dict when the RFS database isn't reachable; the build degrades to generated names."""
    if not RFS_DB.exists():
        return {}
    try:
        from rfs_import import RfsDb
        db = RfsDb(RFS_DB)
        t = db.tables.get("teamstadiumlinks")
        if t is None:
            return {}
        out = {}
        for i in range(t.rows):
            rec = db.record("teamstadiumlinks", i)
            tid = struct.unpack_from("<I", rec, 0)[0]
            name = rec[4:34].split(b"\0")[0].decode("utf-8", "replace").strip()
            if name:
                out[tid] = name
        return out
    except Exception as e:                          # unreachable / foreign format: degrade, don't die
        print(f"note: RFS stadium names unavailable ({e})")
        return {}


def core_name(club: str) -> str:
    """Club name minus club-form furniture: 'KF Egnatia' -> 'Egnatia', 'Arsenal FC' -> 'Arsenal'."""
    words = (club or "").replace(".", "").split()
    while len(words) > 1 and words[0].lower() in CLUB_STOP:
        words = words[1:]
    while len(words) > 1 and words[-1].lower() in CLUB_STOP:
        words = words[:-1]
    return " ".join(words) or (club or "Unknown")


def gen_name(club: str, country: str, team_id: int) -> str:
    n = core_name(club)
    pat = NAME_PATTERNS.get((country or "").strip().lower())
    if pat:
        return pat.format(n=n)
    pick = hashlib.md5(str(team_id).encode()).digest()[0] % len(GENERIC_SUFFIXES)
    return f"{n} {GENERIC_SUFFIXES[pick]}"


def nice(cap: float) -> int:
    """Clamp to sane bounds and round the way real published capacities read."""
    cap = max(CAP_MIN, min(CAP_MAX, cap))
    step = 500 if cap >= 10_000 else 100
    return int(round(cap / step) * step)


def cap_from_att(av_att: int, rep: int) -> int:
    """Real average attendance / reputation-scaled utilisation (big clubs sell out, small don't)."""
    util = min(0.96, max(0.45, 0.42 + 0.055 * (rep or 0) / 1000))
    return nice(av_att / util)


def cap_from_rep(rep: int) -> int:
    return nice(1200 * 2 ** ((rep or 0) / 1750))


# catalog squad rating -> capacity, log-linear between anchors calibrated on clubs whose real
# capacity is known: rating 59 ≈ Scunthorpe (9k), 70 ≈ PAOK (29k), 74 ≈ Man Utd (74k)
RATING_ANCHORS = [(36, 800), (50, 1_500), (56, 4_000), (60, 9_000), (65, 18_000),
                  (70, 32_000), (75, 55_000), (81, 85_000)]


def cap_from_rating(rating: float) -> int:
    r = rating or 55.0
    if r <= RATING_ANCHORS[0][0]:
        return nice(RATING_ANCHORS[0][1])
    if r >= RATING_ANCHORS[-1][0]:
        return nice(RATING_ANCHORS[-1][1])
    for (r0, c0), (r1, c1) in zip(RATING_ANCHORS, RATING_ANCHORS[1:]):
        if r0 <= r <= r1:
            t = (r - r0) / (r1 - r0)
            return nice(math.exp(math.log(c0) + t * (math.log(c1) - math.log(c0))))
    return nice(9_000)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="build the stadiums table for catalog clubs")
    ap.add_argument("--apply", action="store_true",
                    help="write to master.db (default is a dry coverage report)")
    ap.add_argument("--db", type=Path, default=DB)
    args = ap.parse_args()

    catalog = json.loads(CAT.read_text(encoding="utf-8"))
    club = {}                                        # team_id -> (name, country, rating)
    for co in catalog["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                club.setdefault(t["team_id"], (t["name"], co["name"], t.get("rating") or 0.0))
    ids = sorted(club)
    if not ids:
        print("catalog is empty — nothing to build")
        return 1

    uri = f"file:{args.db.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    qm = ",".join("?" * len(ids))
    home = {tid: hs for tid, hs in con.execute(
        f"SELECT id, home_stadium FROM teams WHERE id IN ({qm})", ids) if hs and hs.strip()}
    fm = {tid: (cap or 0, att or 0, rep or 0) for tid, cap, att, rep in con.execute(
        f"""SELECT ti.team_id, f.stadium_cap, f.av_att, f.reputation
              FROM team_identity ti JOIN fm_clubs f ON f.uid = ti.fm_club_id
             WHERE ti.team_id IN ({qm})""", ids)}
    in_teams = {tid for (tid,) in con.execute(f"SELECT id FROM teams WHERE id IN ({qm})", ids)}
    con.close()

    rfs_names = load_rfs_stadium_names()

    rows = []                                        # (id, name, capacity, team_id, name_src, cap_src)
    n_src, c_src = {}, {}
    for i, tid in enumerate(t for t in ids if t in in_teams):
        cname, country, rating = club[tid]
        rfs_name = rfs_names.get(tid - RFS_TEAM_OFFSET) if tid >= RFS_TEAM_OFFSET else None
        if tid in home:
            name, ns = home[tid], "teams"
        elif rfs_name:
            name, ns = rfs_name, "rfs"
        else:
            name, ns = gen_name(cname, country, tid), "gen"

        fcap, fatt, frep = fm.get(tid, (0, 0, 0))
        if fcap > 0:
            cap, cs = nice(fcap), "fm"
        elif fatt > 0:
            cap, cs = cap_from_att(fatt, frep), "est_att"
        elif frep > 0:
            cap, cs = cap_from_rep(frep), "est_rep"
        else:
            cap, cs = cap_from_rating(rating), "est"

        rows.append((i + 1, name, cap, tid, ns, cs))
        n_src[ns] = n_src.get(ns, 0) + 1
        c_src[cs] = c_src.get(cs, 0) + 1

    dropped = len(ids) - len(rows)
    print(f"catalog clubs: {len(ids)}  ->  stadium rows: {len(rows)}"
          + (f"  (skipped {dropped} not present in teams)" if dropped else ""))
    print("name coverage:     "
          + "  ".join(f"{k}={n_src.get(k, 0)}" for k in ("teams", "rfs", "gen")))
    print("capacity coverage: "
          + "  ".join(f"{k}={c_src.get(k, 0)}" for k in ("fm", "est_att", "est_rep", "est")))
    caps = sorted(r[2] for r in rows)
    print(f"capacity range: min {caps[0]:,}  median {caps[len(caps) // 2]:,}  max {caps[-1]:,}")
    print("\nsample:")
    for r in rows[:6] + rows[len(rows) // 2: len(rows) // 2 + 3] + rows[-3:]:
        print(f"  #{r[0]:<5} team {r[3]:<9} {club[r[3]][0][:28]:<28} -> "
              f"{r[1][:34]:<34} {r[2]:>7,}  [{r[4]}/{r[5]}]")

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to build the stadiums table.")
        return 0

    bak = str(args.db) + ".bak-stadiums"
    shutil.copy2(args.db, bak)
    print(f"\nbacked up -> {bak}")
    wcon = sqlite3.connect(args.db, timeout=60)
    with wcon:                                       # rebuild wholesale: compiled artifact, not a patch
        wcon.execute("DROP TABLE IF EXISTS stadiums")
        wcon.execute("""CREATE TABLE stadiums(
                            id INTEGER PRIMARY KEY,
                            name TEXT NOT NULL,
                            capacity INTEGER NOT NULL,
                            team_id INTEGER NOT NULL UNIQUE REFERENCES teams(id),
                            name_source TEXT NOT NULL,
                            capacity_source TEXT NOT NULL)""")
        wcon.executemany("INSERT INTO stadiums(id,name,capacity,team_id,name_source,"
                         "capacity_source) VALUES(?,?,?,?,?,?)", rows)
    wcon.close()
    print(f"stadiums table rebuilt: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
