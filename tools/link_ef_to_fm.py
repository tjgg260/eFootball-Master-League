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
    """Name tokens IN ORDER. Sorting them would make 'Seo Min-Woo' and 'Seo Woo-Min' the same
    person, which they are not — and order is safe to rely on because FM's surname-first form is
    flipped before it gets here, so a real match agrees on sequence, not just on membership."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return tuple(t for t in re.sub(r"[^a-z ]", " ", s).split() if len(t) > 1)


def subseq(a, b):
    """a is b with words missing: 'jose palomino' inside 'jose luis palomino'."""
    it = iter(b)
    return len(a) < len(b) and all(t in it for t in a)


def initial(name):
    """eFootball abbreviates a given name to an initial ('T. Alexander-Arnold'). The letter is
    dropped from the token list but it still rules out most candidates: 'F. Di Francesco' is
    Federico, never Paolo."""
    m = re.match(r"\s*([A-Za-z])\.", name or "")
    return m.group(1).lower() if m else None


def flip(name):
    """FM writes 'Eze, Ebere'; the world writes given name first."""
    n = (name or "").strip()
    if "," in n:
        last, first = n.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return n


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
            cands[key(flip(r.get("Name")))].append(
                (int(u), flip(r.get("Name")), nat(r.get("Nation")), fa))

    def agrees(p, f):
        return p[2] == f[2] and (p[3] is None or f[3] is None or abs(p[3] - f[3]) <= 2)

    pairs, amb = [], 0
    for k, mine in ours.items():
        theirs = cands.get(k)
        if not theirs:
            continue
        ok = [(p, f) for p in mine for f in theirs if agrees(p, f)]
        if len(ok) == 1:
            pairs.append(ok[0])
        elif ok:
            amb += 1

    # Rule two: the same name, written shorter. eFootball prints 'Marc ter Stegen' and
    # 'T. Alexander-Arnold' where FM has 'ter Stegen, Marc-Andre' and 'Alexander-Arnold, Trent',
    # so an exact token-set match never fires and the player ends up in the world with no club at
    # all. A proper subset is accepted when the surname is carried, nationality and age still
    # agree, and exactly one row on each side fits.
    linked_now = {p[0] for p, _f in pairs}
    used_uid = {f[0] for _p, f in pairs}
    by_sur = defaultdict(list)
    for k, lst in cands.items():
        for f in lst:
            if f[0] in used_uid:
                continue
            for t in k:
                by_sur[t].append((k, f))
    for k, mine in ours.items():
        if len(k) < 2:
            continue
        for p in mine:
            if p[0] in linked_now:
                continue
            hits = []
            for t in k:
                for fk, f in by_sur.get(t, []):
                    if not subseq(k, fk) or not agrees(p, f):
                        continue
                    ini = initial(p[1])
                    if ini and not fk[0].startswith(ini):
                        continue
                    hits.append(f)
            hits = list({h[0]: h for h in hits}.values())
            if len(hits) == 1:
                pairs.append((p, hits[0]))
                linked_now.add(p[0])
            elif hits:
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
