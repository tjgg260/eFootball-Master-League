#!/usr/bin/env python3
"""
link_players_by_roster.py — give an unlinked squadded player his FM identity by looking him up in
HIS OWN CLUB'S roster, a candidate pool of ~30 instead of half a million.

16,197 squadded world players carry no fm_uid, which is why they still read as bare surnames
('Boniface', 'Ezzalzouli') and why nothing can source their attributes. 6,741 of them sit at a
club that IS linked to FM, and for those the answer is already in the export.

Matching is deliberately narrow, because a wrong link hands a player another man's attributes:
  - the FM surname must appear IN FULL inside the DB name, compound surnames included
    ('De Bruyne' is a token pair, never just 'Bruyne')
  - score: surname 2, given name also present 2, nationality intersects 1,
    height within 3cm 1, position group agrees 0.5
  - accept only at score >= 4.0 AND a margin of >= 1.5 over the runner-up in the same roster
  - never take a uid another live squadded record already holds, which would mint a duplicate
Anything short of that is left alone and counted.

Where FM's name is strictly fuller than ours the name is upgraded too — the visible half of the fix.

    python tools/link_players_by_roster.py --dry
    python tools/link_players_by_roster.py
"""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
YOUTH = re.compile(r"\bU\s?-?(1[5-9]|2[0-3])\b", re.I)

NAT_SYN = {"korea republic": "south korea", "china pr": "china", "ivory coast": "cote divoire",
           "holland": "netherlands", "usa": "united states", "turkiye": "turkey",
           "republic of ireland": "ireland", "czech republic": "czechia",
           "bosnia and herzegovina": "bosnia", "north macedonia": "macedonia"}
DEFP = {"CB", "LB", "RB"}
MIDP = {"DMF", "CMF", "AMF", "LMF", "RMF"}
FWDP = {"CF", "SS", "LWF", "RWF"}


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s):
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def nat(s):
    out = set()
    for x in (s or "").split("/"):
        k = re.sub(r"[^a-z ]", "", norm(x)).strip()
        if k:
            out.add(NAT_SYN.get(k, k))
    return out


def group(pos):
    p = (pos or "").upper()
    if p == "GK":
        return "GK"
    if p in DEFP:
        return "DEF"
    if p in MIDP:
        return "MID"
    if p in FWDP:
        return "FWD"
    return ""


def fm_group(pos):
    """FM writes 'D C, DM' / 'AM R' / 'ST'. Return the groups that covers."""
    p = (pos or "").upper()
    out = set()
    if "GK" in p:
        out.add("GK")
    if re.search(r"\bD\b|\bWB\b", p):
        out.add("DEF")
    if re.search(r"\bDM\b|\bM\b|\bAM\b", p):
        out.add("MID")
    if re.search(r"\bST\b|\bF\b", p):
        out.add("FWD")
    return out


def display(fm_name):
    if "," in fm_name:
        sur, giv = fm_name.split(",", 1)
        return (giv.strip() + " " + sur.strip()).strip()
    return fm_name.strip()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    uid_of = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    squadded = {p for (p,) in con.execute(
        "SELECT player_id FROM squad_members WHERE NOT (team_id>=800000 AND team_id<1000000)")}
    taken = {u for p, u in uid_of.items() if p in squadded}
    fm_of = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
    bio = {u: h for u, h in con.execute("SELECT uid, height FROM fm_bio")}

    roster = defaultdict(list)
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            c, u = (r.get("Club ID") or "").strip(), (r.get("Unique ID") or "").strip()
            if not (c.lstrip("-").isdigit() and int(c) > 0 and u.isdigit()):
                continue
            if YOUTH.search(r.get("Squad") or ""):
                continue
            nm = (r.get("Name") or "").strip()
            if "," in nm:
                sur, giv = nm.split(",", 1)
            else:
                parts = nm.split()
                sur, giv = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (nm, "")
            roster[int(c)].append((int(u), nm, toks(sur), toks(giv),
                                   nat(r.get("Nation")), fm_group(r.get("Position") or "")))

    links, renames, stats = [], [], Counter()
    for pid, tid, nm, age, nation, ht, pos in con.execute(
            "SELECT s.player_id, s.team_id, p.name, p.age, p.nationality, p.height_cm, "
            "COALESCE(p.position,'') FROM squad_members s JOIN players p ON p.id = s.player_id "
            "WHERE NOT (s.team_id >= 800000 AND s.team_id < 1000000)"):
        if uid_of.get(pid):
            stats["already linked"] += 1
            continue
        fc = fm_of.get(tid)
        if not fc or fc not in roster:
            stats["club not linked to FM"] += 1
            continue
        pt, pn, pg = toks(nm), nat(nation), group(pos)
        if not pt:
            stats["no usable name"] += 1
            continue
        scored = []
        for uid, fnm, sur, giv, fnat, fgrp in roster[fc]:
            if uid in taken or not sur or not sur <= pt:
                continue
            s = 2.0
            if giv and giv <= pt:
                s += 2.0
            if pn and fnat and (pn & fnat):
                s += 1.0
            h = bio.get(uid)
            if ht and h and abs(ht - h) <= 3:
                s += 1.0
            if pg and fgrp and pg in fgrp:
                s += 0.5
            scored.append((s, uid, fnm))
        scored.sort(reverse=True)
        if not scored:
            stats["surname not in that roster"] += 1
            continue
        best = scored[0]
        runner = scored[1][0] if len(scored) > 1 else 0.0
        if best[0] >= 4.0 and best[0] - runner >= 1.5:
            links.append((pid, best[1], nm, best[2]))
            taken.add(best[1])
            stats["LINKED"] += 1
            d = display(best[2])
            if toks(nm) < toks(d):
                renames.append((d, pid))
        else:
            stats["too weak or ambiguous"] += 1

    for k, v in stats.most_common():
        print("  %7d  %s" % (v, k))
    print("")
    print("names upgraded from FM: %d" % len(renames))
    for _p, _u, a, b in links[:10]:
        print("   %s -> FM %s" % (a, b))
    if dry:
        print("--dry: nothing written.")
        return 0
    if not links:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prelinkroster")
    cur.execute("BEGIN")
    for pid, uid, _a, _b in links:
        kind = ("ef" if pid < 16777216 else "rfs" if pid < 10000000000
                else "fm" if pid < 45000000000 else "generated")
        cur.execute("INSERT OR IGNORE INTO player_identity(player_id, kind, confidence) "
                    "VALUES(?,?,0.9)", (pid, kind))
        cur.execute("UPDATE player_identity SET fm_uid=?, fm_method='roster', "
                    "confidence=MIN(confidence,0.9) WHERE player_id=?", (uid, pid))
    cur.executemany("UPDATE players SET name=? WHERE id=?", renames)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print("applied. linked %d players, renamed %d." % (len(links), len(renames)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
