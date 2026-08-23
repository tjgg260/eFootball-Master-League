#!/usr/bin/env python3
"""
regen_faces.py — assign Uran Megapack faces to career regens (newgens), NewGAN-style.

The pack (facepack/uran/players/male/<ethnicity 0-10>/@2x/<IOC><n>.png, 76k faces) organizes
faces by FM ethnicity bucket and the nationality the face was generated to resemble:
  0 Northern European   1 Mediterranean/Latin   2 MENA          3 African/Caribbean
  4 South Asian         5 SE Asian              6 Central Asian 7 Andean/Indigenous SA
  8 Pacific             9 Mixed                 10 East Asian
Matching rule ("database description -> picture"): a regen's nationality picks the face pool
with the same IOC code; if that country has no pool (or it's exhausted), fall back to another
pool in the SAME ethnicity bucket; last resort any pool. Assignments are persisted in
regen_face_assignments so a face is never used twice and survives re-runs.

Usage:
  python tools/regen_faces.py --test                # demo: sample assignments, no writes
  python tools/regen_faces.py --assign              # assign faces to career players (20M-700M id)
                                                    # that have no real_face_path yet
"""
from __future__ import annotations

import argparse
import random
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
PACK = REPO / "facepack" / "uran" / "players" / "male"

CAREER_LO, CAREER_HI = 20_000_000, 700_000_000  # career/regen player id range

# nationality display name -> IOC code used by the pack (covers the DB's top nations;
# unmatched names fall through to ethnicity-bucket fallback)
N2C = {
    "italy": "ITA", "brazil": "BRA", "england": "ENG", "argentina": "ARG", "portugal": "POR",
    "austria": "AUT", "spain": "ESP", "germany": "GER", "france": "FRA", "norway": "NOR",
    "netherlands": "NED", "australia": "AUS", "wales": "WAL", "romania": "ROU", "japan": "JPN",
    "poland": "POL", "belgium": "BEL", "sweden": "SWE", "denmark": "DEN", "serbia": "SRB",
    "turkiye": "TUR", "turkey": "TUR", "scotland": "SCO", "russia": "RUS", "czechia": "CZE",
    "czech republic": "CZE", "croatia": "CRO", "colombia": "COL", "china": "CHN",
    "ukraine": "UKR", "hungary": "HUN", "nigeria": "NGA", "uruguay": "URU",
    "switzerland": "SUI", "greece": "GRE", "thailand": "THA", "estonia": "EST",
    "ireland": "IRL", "israel": "ISR", "chile": "CHI", "finland": "FIN", "mexico": "MEX",
    "usa": "USA", "united states": "USA", "canada": "CAN", "ghana": "GHA", "senegal": "SEN",
    "morocco": "MAR", "algeria": "ALG", "tunisia": "TUN", "egypt": "EGY", "cameroon": "CMR",
    "ivory coast": "CIV", "cote divoire": "CIV", "mali": "MLI", "south africa": "RSA",
    "jamaica": "JAM", "ecuador": "ECU", "peru": "PER", "paraguay": "PAR", "bolivia": "BOL",
    "venezuela": "VEN", "south korea": "KOR", "korea republic": "KOR", "iran": "IRN",
    "saudi arabia": "KSA", "qatar": "QAT", "iceland": "ISL", "slovakia": "SVK",
    "slovenia": "SVN", "bulgaria": "BUL", "bosnia": "BIH", "bosnia and herzegovina": "BIH",
    "north macedonia": "MKD", "albania": "ALB", "kosovo": "KOS", "montenegro": "MNE",
    "n.ireland": "NIR", "northern ireland": "NIR", "india": "IND", "indonesia": "IDN",
    "malaysia": "MAS", "vietnam": "VIE", "philippines": "PHI", "uzbekistan": "UZB",
    "kazakhstan": "KAZ", "georgia": "GEO", "armenia": "ARM", "azerbaijan": "AZE",
    "belarus": "BLR", "lithuania": "LTU", "latvia": "LVA", "faroe islands": "FRO",
    "new zealand": "NZL", "cyprus": "CYP", "malta": "MLT", "luxembourg": "LUX",
    "angola": "ANG", "mozambique": "MOZ", "guinea": "GUI", "burkina faso": "BFA",
    "dr congo": "COD", "congo dr": "COD", "gabon": "GAB", "zambia": "ZAM", "kenya": "KEN",
}


def normname(s: str) -> str:
    s = (s or "").split("/")[0].strip()                 # dual nationality -> first
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("�", "u")                        # mojibake T�rkiye -> turkiye
    return re.sub(r"\s+", " ", s.lower()).strip()


def build_index():
    """code -> (bucket, [paths]); bucket -> [codes]"""
    pools: dict[str, tuple[int, list[str]]] = {}
    buckets: dict[int, list[str]] = defaultdict(list)
    for bdir in sorted(PACK.iterdir()):
        if not bdir.is_dir() or not bdir.name.isdigit():
            continue
        bucket = int(bdir.name)
        two_x = bdir / "@2x"
        bycode = defaultdict(list)
        seen_names: set[str] = set()
        # canonical 1x files in the bucket root; use the @2x version when it exists
        for f in bdir.glob("*.png"):
            m = re.match(r"([A-Za-z]+)\d+\.png$", f.name)
            if m:
                best = two_x / f.name if (two_x / f.name).exists() else f
                bycode[m.group(1).upper()].append(str(best))
                seen_names.add(f.name)
        # @2x-only faces with no 1x counterpart
        if two_x.exists():
            for f in two_x.glob("*.png"):
                if f.name in seen_names:
                    continue
                m = re.match(r"([A-Za-z]+)\d+\.png$", f.name)
                if m:
                    bycode[m.group(1).upper()].append(str(f))
        for code, paths in bycode.items():
            pools[code] = (bucket, sorted(paths))
            buckets[bucket].append(code)
    return pools, buckets


def pick(nationality: str, pools, buckets, used: set[str], rng: random.Random) -> str | None:
    code = N2C.get(normname(nationality))
    candidates: list[str] = []
    if code and code in pools:
        candidates = [p for p in pools[code][1] if p not in used]
    if not candidates and code and code in pools:      # exhausted -> same bucket
        bucket = pools[code][0]
        for c in buckets[bucket]:
            candidates += [p for p in pools[c][1] if p not in used]
    if not candidates:                                  # unknown nation -> any
        for _, (_, paths) in pools.items():
            candidates += [p for p in paths if p not in used]
    if not candidates:
        return None
    return rng.choice(candidates)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--assign", action="store_true")
    ap.add_argument("--seed", type=int, default=1897)
    args = ap.parse_args()

    pools, buckets = build_index()
    total = sum(len(p) for _, p in pools.values())
    print(f"index: {len(pools)} nation pools, {total:,} faces, buckets: "
          f"{ {b: len(cs) for b, cs in sorted(buckets.items())} }")

    rng = random.Random(args.seed)

    if args.test:
        used: set[str] = set()
        for nat in ["England", "Brazil", "Türkiye", "Japan", "Nigeria", "Peru", "India",
                    "England / Nigeria", "Ruritania"]:
            f = pick(nat, pools, buckets, used, rng)
            if f:
                used.add(f)
            print(f"  {nat:22} -> {Path(f).parent.parent.name}/{Path(f).name}" if f else f"  {nat}: NONE")
        return 0

    if args.assign:
        con = sqlite3.connect(DB)
        con.execute("CREATE TABLE IF NOT EXISTS regen_face_assignments("
                    "player_id INTEGER PRIMARY KEY, face_path TEXT NOT NULL UNIQUE)")
        used = {p for (p,) in con.execute("SELECT face_path FROM regen_face_assignments")}
        rows = con.execute(
            "SELECT id, COALESCE(nationality,'') FROM players "
            "WHERE id >= ? AND id < ? AND (real_face_path IS NULL OR real_face_path='')",
            (CAREER_LO, CAREER_HI)).fetchall()
        print(f"career players needing faces: {len(rows):,}")
        n = 0
        for pid, nat in rows:
            f = pick(nat, pools, buckets, used, rng)
            if not f:
                break
            used.add(f)
            con.execute("INSERT OR REPLACE INTO regen_face_assignments(player_id, face_path) VALUES(?,?)", (pid, f))
            con.execute("UPDATE players SET real_face_path=? WHERE id=?", (f, pid))
            n += 1
        con.commit()
        print(f"assigned {n:,} regen faces (persisted; no face used twice).")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
