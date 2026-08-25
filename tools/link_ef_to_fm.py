#!/usr/bin/env python3
"""
link_ef_to_fm.py — Odegaard, Cancelo and Gabriel Jesus were in the database, and in no squad.

The identity spine links a player to FM by id, by face file, or by a unique name match, and for
1,947 eFootball records all three missed. Nothing then connects them to FM's membership rows, so
sync_membership_fm cannot see them: Arsenal fielded 21 players while FM listed 30, and Odegaard,
Eze and Gabriel Jesus sat unsquadded and signable while their club played without them.

Match what the spine missed, with the age guard finally usable: FM's dates were three years early
(fix_fm_age_shift), so the comparable age is dob_year + 3. A link is written only when the full
name matches token-for-token, nationality agrees, ages are within 2, and the pairing is unique in
BOTH directions — one record, one uid, no shortlists.

    python tools/link_ef_to_fm.py --dry
    python tools/link_ef_to_fm.py
then: sync_membership_fm.py --dry (the new links place the players), rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
SHIFT, SEASON, EF_HI = 3, 2026, 20_000_000
YOUTH = re.compile(r"\bU\s?-?(1[5-9]|2[0-3])\b")
NAT_SYN = {"u s a": "united states", "usa": "united states", "turkiye": "turkey",
           "korea republic": "south korea", "china pr": "china", "czechia": "czech republic",
           "ivory coast": "cote d ivoire", "n ireland": "northern ireland"}


def key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return tuple(sorted(t for t in re.sub(r"[^a-z ]", " ", s).split() if len(t) > 1))


def nat(s):
    v = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (s or "").split("/")[0].strip().lower())).strip()
    return NAT_SYN.get(v, v)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    linked = {u for (u,) in con.execute(
        "SELECT fm_uid FROM player_identity WHERE fm_uid IS NOT NULL")}
    ours = defaultdict(list)
    for pid, name, natn, age in con.execute(
            "SELECT p.id, p.name, p.nationality, p.age FROM players p "
            "LEFT JOIN player_identity pi ON pi.player_id=p.id "
            "WHERE p.superseded_by IS NULL AND pi.fm_uid IS NULL AND p.id<?", (EF_HI,)):
        ours[key(name)].append((pid, name, nat(natn), age))

    cands = defaultdict(list)
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            if not u.isdigit() or int(u) in linked or YOUTH.search(r.get("Squad") or ""):
                continue
            d = (r.get("Date Of Birth") or "").strip()
            fa = SEASON - int(d[-4:]) - SHIFT if len(d) >= 4 and d[-4:].isdigit() else None
            cands[key(r.get("Name"))].append((int(u), r.get("Name"), nat(r.get("Nation")), fa))

    pairs, amb = [], 0
    for k, mine in ours.items():
        theirs = cands.get(k)
        if not theirs:
            continue
        ok = [(p, f) for p in mine for f in theirs
              if p[2] == f[2] and (p[3] is None or f[3] is None or abs(p[3] - f[3]) <= 2)]
        if len(ok) == 1:
            pairs.append(ok[0])
        elif ok:
            amb += 1

    seen = defaultdict(int)
    for p, f in pairs:
        seen[f[0]] += 1
    pairs = [(p, f) for p, f in pairs if seen[f[0]] == 1]

    print(f"eFootball records with no FM link that FM does carry: {len(pairs):,} "
          f"(ambiguous, left alone: {amb:,})")
    for p, f in pairs[:8]:
        print(f"   {p[1][:26]:26} age {p[3]} -> FM uid {f[0]} ({f[1]})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not pairs:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preeflink")
    cur.execute("BEGIN")
    for p, f in pairs:
        cur.execute("INSERT OR IGNORE INTO player_identity(player_id, kind, confidence) "
                    "VALUES(?, 'ef', 0.9)", (p[0],))
        cur.execute("UPDATE player_identity SET fm_uid=?, fm_method='name-ef' "
                    "WHERE player_id=? AND fm_uid IS NULL", (f[0], p[0]))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(pairs):,} players joined to their FM row.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
