#!/usr/bin/env python3
"""
assign_uran_faces.py — give every player WITHOUT a real face a generated portrait from the Uran
Faces Megapack (facepack/uran/players/male/<bucket>/<FIFA-code><n>.png). The pack is organised by
nationality, so a Belarusian gets a Belarusian-looking generated face — nationality is our
appearance signal (player_appearance only covers ~20k eFootball natives, nearly all of whom already
have real photos). Writes portrait_path, which is TIER 2 of the app's face resolution
(real_face_path → portrait_path → coloured disc) — a real facepack photo always still wins.

Deterministic (face = hash(player_id) % pool), idempotent (only fills NULL portrait_path), and a
later real-face match simply out-ranks the generated one. ~168k players, ~55k faces → a face may
repeat across the world; never within the same hash slot.

    python tools/assign_uran_faces.py --dry
    python tools/assign_uran_faces.py
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
PACK = REPO / "facepack" / "uran" / "players" / "male"

# nationality (players.nationality, first segment) -> FIFA trigram used by the pack's filenames
NAT2CODE = {
    "afghanistan": "AFG", "albania": "ALB", "algeria": "ALG", "andorra": "AND", "angola": "ANG",
    "argentina": "ARG", "armenia": "ARM", "australia": "AUS", "austria": "AUT", "azerbaijan": "AZE",
    "bahrain": "BHR", "bangladesh": "BAN", "barbados": "BRB", "belarus": "BLR", "belgium": "BEL",
    "belize": "BLZ", "benin": "BEN", "bermuda": "BER", "bhutan": "BHU", "bolivia": "BOL",
    "bosnia": "BIH", "bosnia and herzegovina": "BIH", "bosnia-herzegovina": "BIH",
    "botswana": "BOT", "brazil": "BRA", "brunei": "BRU", "bulgaria": "BUL", "burkina faso": "BFA",
    "burundi": "BDI", "cambodia": "CAM", "cameroon": "CMR", "canada": "CAN", "cape verde": "CPV",
    "chad": "CHA", "chile": "CHI", "china": "CHN", "china pr": "CHN", "chinese taipei": "TPE",
    "colombia": "COL", "comoros": "COM", "congo": "CGO", "dr congo": "COD", "congo dr": "COD",
    "costa rica": "CRC", "croatia": "CRO", "cuba": "CUB", "curacao": "CUW", "cyprus": "CYP",
    "czech republic": "CZE", "czechia": "CZE", "denmark": "DEN", "djibouti": "DJI",
    "dominican republic": "DOM", "ecuador": "ECU", "egypt": "EGY", "el salvador": "SLV",
    "england": "ENG", "equatorial guinea": "EQG", "eritrea": "ERI", "estonia": "EST",
    "eswatini": "SWZ", "ethiopia": "ETH", "faroe islands": "FRO", "fiji": "FIJ", "finland": "FIN",
    "france": "FRA", "gabon": "GAB", "gambia": "GAM", "georgia": "GEO", "germany": "GER",
    "ghana": "GHA", "gibraltar": "GIB", "greece": "GRE", "grenada": "GRN", "guatemala": "GUA",
    "guinea": "GUI", "guinea-bissau": "GNB", "guyana": "GUY", "haiti": "HAI", "honduras": "HON",
    "hong kong": "HKG", "hungary": "HUN", "iceland": "ISL", "india": "IND", "indonesia": "IDN",
    "iran": "IRN", "iraq": "IRQ", "ireland": "IRL", "republic of ireland": "IRL",
    "israel": "ISR", "italy": "ITA", "ivory coast": "CIV", "cote d'ivoire": "CIV",
    "jamaica": "JAM", "japan": "JPN", "jordan": "JOR", "kazakhstan": "KAZ", "kenya": "KEN",
    "korea republic": "KOR", "south korea": "KOR", "korea dpr": "PRK", "north korea": "PRK",
    "kosovo": "KOS", "kuwait": "KUW", "kyrgyzstan": "KGZ", "laos": "LAO", "latvia": "LVA",
    "lebanon": "LBN", "lesotho": "LES", "liberia": "LBR", "libya": "LBY", "liechtenstein": "LIE",
    "lithuania": "LTU", "luxembourg": "LUX", "macedonia": "MKD", "north macedonia": "MKD",
    "madagascar": "MAD", "malawi": "MWI", "malaysia": "MAS", "maldives": "MDV", "mali": "MLI",
    "malta": "MLT", "mauritania": "MTN", "mauritius": "MRI", "mexico": "MEX", "moldova": "MDA",
    "mongolia": "MNG", "montenegro": "MNE", "morocco": "MAR", "mozambique": "MOZ",
    "myanmar": "MYA", "namibia": "NAM", "nepal": "NEP", "netherlands": "NED", "holland": "NED",
    "new caledonia": "NCL", "new zealand": "NZL", "nicaragua": "NCA", "niger": "NIG",
    "nigeria": "NGA", "northern ireland": "NIR", "norway": "NOR", "oman": "OMA",
    "pakistan": "PAK", "palestine": "PLE", "panama": "PAN", "papua new guinea": "PNG",
    "paraguay": "PAR", "peru": "PER", "philippines": "PHI", "poland": "POL", "portugal": "POR",
    "puerto rico": "PUR", "qatar": "QAT", "romania": "ROU", "russia": "RUS", "rwanda": "RWA",
    "san marino": "SMR", "saudi arabia": "KSA", "scotland": "SCO", "senegal": "SEN",
    "serbia": "SRB", "seychelles": "SEY", "sierra leone": "SLE", "singapore": "SIN",
    "slovakia": "SVK", "slovenia": "SVN", "somalia": "SOM", "south africa": "RSA",
    "south sudan": "SSD", "spain": "ESP", "sri lanka": "SRI", "sudan": "SDN", "suriname": "SUR",
    "sweden": "SWE", "switzerland": "SUI", "syria": "SYR", "tahiti": "TAH", "tajikistan": "TJK",
    "tanzania": "TAN", "thailand": "THA", "timor-leste": "TLS", "togo": "TOG",
    "trinidad and tobago": "TRI", "trinidad & tobago": "TRI", "tunisia": "TUN", "turkey": "TUR",
    "turkmenistan": "TKM", "uganda": "UGA", "ukraine": "UKR", "united arab emirates": "UAE",
    "uae": "UAE", "united states": "USA", "usa": "USA", "uruguay": "URU", "uzbekistan": "UZB",
    "venezuela": "VEN", "vietnam": "VIE", "wales": "WAL", "yemen": "YEM", "zambia": "ZAM",
    "zimbabwe": "ZIM",
    # export-specific aliases
    "turkiye": "TUR", "n.ireland": "NIR", "bosnia & herzegovina": "BIH", "the gambia": "GAM",
    "u.s.a.": "USA", "cote divoire": "CIV", "vanuatu": "VAN", "solomon islands": "SOL",
    "st kitts and nevis": "SKN", "st lucia": "LCA", "st vincent": "VIN", "american samoa": "ASA",
    "antigua and barbuda": "ATG", "cayman islands": "CAY", "cook islands": "COK",
    "central african republic": "CTA", "macao": "MAC", "montserrat": "MSR", "samoa": "SAM",
    "tonga": "TGA", "aruba": "ARU", "anguilla": "AIA", "bahamas": "BAH", "dominica": "DMA",
    "korea": "KOR", "russia federation": "RUS", "moldova republic": "MDA",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    if not PACK.exists():
        sys.exit(f"Uran pack not found at {PACK}")

    # index the pack: FIFA code -> sorted list of face paths
    pool = defaultdict(list)
    pat = re.compile(r"^(?:@2x )?([A-Z]{3})(\d+)\.png$")
    for f in PACK.rglob("*.png"):
        m = pat.match(f.name)
        if m:
            # store repo-relative forward-slash paths; the app resolves them against the repo root
            pool[m.group(1)].append(f.relative_to(REPO).as_posix())
    for v in pool.values():
        v.sort()
    everything = [p for v in pool.values() for p in v]
    print(f"Uran pack indexed: {len(pool)} nations, {len(everything):,} faces")

    con = sqlite3.connect(DB, timeout=60)
    rows = con.execute("SELECT id, nationality FROM players "
                       "WHERE real_face_path IS NULL AND portrait_path IS NULL").fetchall()
    print(f"players without any face: {len(rows):,}")

    import unicodedata
    updates, unmatched = [], defaultdict(int)
    for pid, nat in rows:
        key = (nat or "").split("/")[0].strip().lower()
        key = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode()
        key = key.replace("'", " ").replace("  ", " ").strip()
        code = NAT2CODE.get(key)
        if code is None and len(key) >= 3 and key[:3].upper() in pool:
            code = key[:3].upper()
        faces = pool.get(code) or everything
        if code is None:
            unmatched[key or "(none)"] += 1
        updates.append((faces[hash_pid(pid) % len(faces)], pid))
    matched = len(updates) - sum(unmatched.values())
    print(f"nationality-matched: {matched:,} | fallback (global pool): {sum(unmatched.values()):,}")
    if unmatched:
        top = sorted(unmatched.items(), key=lambda kv: -kv[1])[:8]
        print("  top unmatched nationalities:", dict(top))
    if dry:
        for path, pid in updates[:5]:
            print(f"  {pid} -> {Path(path).name}")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-preuran")
    con.execute("BEGIN")
    con.executemany("UPDATE players SET portrait_path=? WHERE id=?", updates)
    con.commit()
    print(f"assigned {len(updates):,} generated portraits.")
    return 0


def hash_pid(pid: int) -> int:
    h = (pid * 2654435761) & 0xFFFFFFFF
    return h ^ (h >> 16)


if __name__ == "__main__":
    raise SystemExit(main())
