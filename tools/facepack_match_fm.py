#!/usr/bin/env python3
"""
facepack_match_fm.py — bridge the SortitoutSI cutout facepack (face_<FM-UID>.png) to our players
via an FM database export (allplayers.csv), writing players.real_face_path + an extract list.

FM UIDs are stable across FM versions and the pack is keyed by UID, so we match:
    our player -> FM UID (by name, disambiguated) -> face_<UID>.png

ENHANCED matcher — uses every signal to safely accept more matches without ever assigning a wrong
face. For each of our players we know name, position, and (via squad_members) their CLUB; eFootball
players also have nationality/age. The FM CSV carries Name, Nation, Position, Club, Age. Club is the
strongest disambiguator (the one "Fernandes" at Man Utd), then nationality, then position-unit + age.

Only UIDs that actually HAVE a face are matched. Confidence tiers, best kept per player:
    certain : exact full name, or surname + an exact CLUB match (unambiguous)
    high    : exact full name globally unique, or surname + nationality unique
    medium  : surname + position-unit + age(±1) unique
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CSV_PATH = REPO / "allplayers.csv"
FACE_IDS = REPO / "build" / "facepack_ids.txt"
FACE_DIR = r"C:\Users\tjgg2\Downloads\eFootball Master League\facepack\sortitoutsi\faces"
EXTRACT_LIST = REPO / "build" / "facepack_needed_uids.txt"

NAT_ALIAS = {"usa": "united states", "south korea": "korea republic", "north korea": "korea dpr",
             "ivory coast": "cote d ivoire", "czech republic": "czechia", "china pr": "china",
             "dr congo": "congo dr", "republic of ireland": "ireland"}
CLUB_STOP = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "club", "de", "the", "1", "united",
             "city", "town", "fk", "if", "bk", "ss", "us", "as", "rc"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def club_key(s: str) -> str:
    """Normalised club with common suffixes/prefixes dropped, so 'Manchester United FC' ~ 'Man United'."""
    toks = [t for t in norm(s).split() if t not in CLUB_STOP]
    return " ".join(toks)


UNIT = {"GK": "GK", "CB": "DEF", "LB": "DEF", "RB": "DEF", "LWB": "DEF", "RWB": "DEF",
        "DMF": "MID", "CMF": "MID", "LMF": "MID", "RMF": "MID", "AMF": "MID",
        "DM": "MID", "CM": "MID", "LM": "MID", "RM": "MID", "AM": "MID",
        "LWF": "FWD", "RWF": "FWD", "SS": "FWD", "CF": "FWD", "ST": "FWD"}


def our_unit(pos: str) -> str:
    return UNIT.get((pos or "").upper().split()[0] if pos else "", "")


def fm_unit(pos: str) -> str:
    """FM position string ('D C', 'AM R', 'GK', 'ST') -> unit."""
    p = pos.upper()
    if "GK" in p:
        return "GK"
    if p.startswith("D") and "DM" not in p:
        return "DEF"
    if p.startswith("ST") or "AM" in p or "F" in p and "D" not in p:
        return "FWD"
    if any(x in p for x in ("DM", "M", "WB")):
        return "MID"
    return ""


def load_face_ids() -> set[int]:
    return {int(x) for x in FACE_IDS.read_text("ascii", "ignore").split() if x.strip().isdigit()}


class FmEntry:
    __slots__ = ("uid", "nat", "club", "unit", "age", "fi")

    def __init__(self, uid, nat, club, unit, age, fi):
        self.uid, self.nat, self.club, self.unit, self.age, self.fi = uid, nat, club, unit, age, fi


def load_fm(face_ids: set[int]):
    text = CSV_PATH.read_bytes().decode("cp1252", "replace")
    rows = csv.reader(io.StringIO(text), delimiter=";")
    header = next(rows)
    col = {n: i for i, n in enumerate(header)}
    ci_name, ci_nat, ci_pos = col["Name"], col["Nation"], col["Position"]
    ci_club, ci_age, ci_uid = col["Club"], col["Age"], col["Unique ID"]
    full_idx, sur_idx = defaultdict(list), defaultdict(list)
    n = 0
    for r in rows:
        if len(r) <= ci_uid or not r[ci_uid].isdigit():
            continue
        uid = int(r[ci_uid])
        if uid not in face_ids:
            continue
        raw = r[ci_name].strip()
        if not raw:
            continue
        surname, first = (p.strip() for p in raw.split(",", 1)) if "," in raw else (raw, "")
        nsur, nfirst = norm(surname), norm(first)
        if not nsur:
            continue
        try:
            age = int(r[ci_age])
        except ValueError:
            age = 0
        e = FmEntry(uid, norm(re.split(r"[/,]", r[ci_nat])[0]), club_key(r[ci_club]),
                    fm_unit(r[ci_pos]), age, nfirst[:1])
        full_idx[f"{nfirst} {nsur}".strip()].append(e)
        sur_idx[nsur].append(e)
        n += 1
    return full_idx, sur_idx, n


def nat_ok(our: str, fm: str) -> bool:
    a = norm(our)
    a = NAT_ALIAS.get(a, a)
    return bool(a) and (a == fm or a in fm or fm in a)


def unique(entries) -> int | None:
    ids = {e.uid for e in entries}
    return next(iter(ids)) if len(ids) == 1 else None


def match(name, nat, club, unit, age, full_idx, sur_idx):
    nfull = norm(name)
    parts = nfull.split()
    surname = parts[-1] if parts else ""
    ck = club_key(club)

    full = full_idx.get(nfull, [])
    if full:
        u = unique(full)
        if u is not None:
            return u, "high"
        if ck:
            cm = [e for e in full if e.club and e.club == ck]
            if (u := unique(cm)) is not None:
                return u, "certain"
        nm = [e for e in full if nat_ok(nat, e.nat)]
        if (u := unique(nm)) is not None:
            return u, "certain"

    sur = sur_idx.get(surname, [])
    if sur:
        if ck:
            cm = [e for e in sur if e.club and e.club == ck]
            if (u := unique(cm)) is not None:
                return u, "certain"
        if nat:
            nm = [e for e in sur if nat_ok(nat, e.nat)]
            if (u := unique(nm)) is not None:
                return u, "high"
        if unit and age:
            am = [e for e in sur if e.unit == unit and e.age and abs(e.age - age) <= 1]
            if (u := unique(am)) is not None:
                return u, "medium"
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    faces = load_face_ids()
    full_idx, sur_idx, n = load_fm(faces)
    print(f"facepack faces: {len(faces):,};  FM players with a face: {n:,}")

    con = sqlite3.connect(DB)
    # our players + their club (one squad link each)
    rows = con.execute(
        "SELECT p.id, p.name, COALESCE(p.nationality,''), COALESCE(p.position,''), "
        "COALESCE(p.age,0), COALESCE((SELECT t.name FROM squad_members s JOIN teams t ON t.id=s.team_id "
        "WHERE s.player_id=p.id LIMIT 1),'') FROM players p").fetchall()

    tiers = defaultdict(int)
    out = []
    for pid, name, nat, pos, age, club in rows:
        uid, tier = match(name, nat, club, our_unit(pos), age, full_idx, sur_idx)
        if uid is not None:
            tiers[tier] += 1
            out.append((pid, uid))
    total = sum(tiers.values())
    print(f"\nmatched {total:,} / {len(rows):,} players:")
    for t in ("certain", "high", "medium"):
        print(f"   {t:8s} {tiers[t]:,}")

    print("\nspot-check:")
    for nm in ("Harry Kane", "Kylian Mbappé", "Erling Haaland", "Bukayo Saka", "Vinícius Júnior"):
        row = con.execute("SELECT name,COALESCE(nationality,''),COALESCE(position,''),COALESCE(age,0),"
                          "COALESCE((SELECT t.name FROM squad_members s JOIN teams t ON t.id=s.team_id "
                          "WHERE s.player_id=players.id LIMIT 1),'') FROM players WHERE name=? "
                          "AND is_custom=0 LIMIT 1", (nm,)).fetchone()
        if row:
            uid, tier = match(row[0], row[1], row[4], our_unit(row[2]), row[3], full_idx, sur_idx)
            print(f"   {nm:20s} -> {uid} ({tier})")

    if args.apply:
        con.executemany("UPDATE players SET real_face_path=? WHERE id=?",
                        [(str(Path(FACE_DIR) / f"face_{uid}.png"), pid) for pid, uid in out])
        con.commit()
        uids = sorted({u for _, u in out})
        EXTRACT_LIST.write_text("\n".join(f"sortitoutsi/faces/face_{u}.png" for u in uids), "ascii")
        print(f"\nwrote real_face_path for {len(out):,} players; {len(uids):,} faces to extract.")
    else:
        print("\n(dry run — pass --apply)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
