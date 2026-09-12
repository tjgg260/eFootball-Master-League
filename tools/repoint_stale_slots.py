#!/usr/bin/env python3
"""
repoint_stale_slots.py — a league slot must point at the record that actually holds the club.

A club can exist twice in the world: the record a catalog league slot points at, and another record
that FM's own roster was synced into. When those differ, the league shows the stale one. Leicester
City's slot pointed at 3000095 — Vestergaard, Daka, Ayew and nine generated fillers — while FM's
Leicester (club 673), with its real roster, was linked to 4005759, a record in no league at all.
The identity verifier would then have made it worse: seeing a stronger claimant, it planned to
UNLINK 25 more league clubs (1860 Munich, Westerlo, Huesca, Excelsior...), each one becoming another
Leicester.

The squads decide which record is the club. For each league slot, find the FM club it stands for —
its own link, or else the one FM club of its nation whose name it contains, distinctively, with a
senior roster — then count how many players of each candidate record FM lists at that club. The
slot moves to another record when that record carries FM's roster (at least 8 of it) and the slot's
own record carries under half as many. The opposite case — the slot's record HAS the roster and a
duplicate holds the link, as with Nottingham Forest — is the verifier's job and is left to it.

Guards: a reserve side never stands for its parent ('Juventus Next Gen' is not Juventus); the new
record must not be a career copy or already hold another league slot; and a name containment only
counts when the shared words are distinctive ('Esporte' is not a club, 'Leicester' is) AND the two
squads share at least two surnames — a stale squad of the right club always does, while 'True
Bangkok United' and 'Bangkok FC' share a word and nothing else. The link
moves with the slot, and career clubs that recorded the stale record as their original follow it.

    python tools/repoint_stale_slots.py --dry
    python tools/repoint_stale_slots.py
then: verify_identity_fm, fix_club_display_names, sync_team_leagues, link_logos_by_fm_id,
      crest_from_rfs, gen_club_badges, fill_squads, and the rest of the post-build chain
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
MEMBER = REPO / "allavailable columns players.csv"
CAREER_TEAM_LO, CAREER_TEAM_HI = 800_000, 1_000_000
MIN_ROSTER = 8

GENERIC = {"fc", "afc", "cf", "club", "sc", "ac", "cd", "fk", "sk", "the", "de", "ec", "fbc", "cfc",
           "sv", "sd", "ud", "ca", "cs", "as", "us", "ss", "if", "bk", "nk", "kf", "ks"}
# Words that name a KIND of club rather than a club: sharing one of these proves nothing.
WEAK = {"central", "esporte", "united", "city", "sporting", "atletico", "athletic", "real",
        "deportivo", "sport", "sports", "town", "rovers", "wanderers", "football", "clube", "social",
        "union", "racing", "olympic", "olympique", "dynamo", "dinamo", "spartak", "lokomotiv",
        "academy", "university", "metropolitan", "calcio", "futebol", "futbol"}
RESERVE = re.compile(r"(\s(II|B|2|III)|\bU-?1[5-9]\b|\bU-?2[0-3]\b|\bReserves?\b|\bAcademy\b"
                     r"|\bNext Gen\b|\bPromesas\b|\bUniversity\b|\(T\))\s*$", re.I)
NATION_SYN = {"turkiye": "turkey", "korea republic": "south korea", "usa": "united states",
              "holland": "netherlands", "czechia": "czech republic", "bosnia": "bosnia and herzegovina"}


def toks(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.sub("[^a-z0-9 ]", " ", s).split() if w not in GENERIC)


def nation(s):
    v = (s or "").strip().lower()
    return NATION_SYN.get(v, v)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    slot_country = {t["team_id"]: co["name"] for co in cat["countries"] for lg in co["leagues"]
                    for t in lg["teams"]}
    tname = dict(con.execute("SELECT id, name FROM teams"))
    link = dict(con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
    holder = {fc: t for t, fc in link.items()}

    # FM's roster, club by club, and which of our records its players sit in
    club_of_uid, senior = {}, Counter()
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            u, c = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip()
            if u.isdigit() and c.isdigit():
                club_of_uid[int(u)] = int(c)
                senior[int(c)] += 1
    votes = Counter()                       # (team, fm club) -> players FM lists at that club
    for tid, uid in con.execute(
            "SELECT s.team_id, pi.fm_uid FROM squad_members s "
            "JOIN player_identity pi ON pi.player_id=s.player_id WHERE pi.fm_uid IS NOT NULL"):
        c = club_of_uid.get(uid)
        if c is not None:
            votes[(tid, c)] += 1
    teams_voting = defaultdict(list)
    for (tid, c), n in votes.items():
        teams_voting[c].append((n, tid))

    fm_by_nation = defaultdict(list)
    for uid, nm, nat in con.execute("SELECT uid, name, nation FROM fm_clubs"):
        fm_by_nation[nation(nat)].append((uid, nm, toks(nm)))

    def stands_for(tid):
        """The FM club a league slot stands for: its own link, else one distinctive name match."""
        if tid in link:
            return link[tid], "its own link"
        mine = toks(tname.get(tid))
        if not mine:
            return None, None
        hits = []
        for uid, nm, tk in fm_by_nation.get(nation(slot_country[tid]), []):
            if not tk or not (tk <= mine or mine <= tk) or not ((tk & mine) - WEAK):
                continue
            if bool(RESERVE.search(tname.get(tid) or "")) != bool(RESERVE.search(nm or "")):
                continue
            if senior.get(uid, 0) >= MIN_ROSTER:
                hits.append((uid, nm))
        if len(hits) == 1:
            return hits[0][0], f"name ('{hits[0][1]}')"
        return None, None

    def surnames(team):
        out = set()
        for (nm,) in con.execute("SELECT p.name FROM squad_members s JOIN players p "
                                 "ON p.id=s.player_id WHERE s.team_id=?", (team,)):
            w = unicodedata.normalize("NFKD", nm or "").encode("ascii", "ignore").decode().lower()
            w = re.sub("[^a-z ]", " ", w).split()
            if w:
                out.add(w[-1])
        return out

    moves, refused = [], []
    taken = set(slot_country)
    for tid in slot_country:
        fc, how = stands_for(tid)
        if fc is None:
            continue
        mine = votes.get((tid, fc), 0)
        rivals = sorted((n, t) for n, t in teams_voting.get(fc, []) if t != tid
                        and not (CAREER_TEAM_LO <= t < CAREER_TEAM_HI) and t not in taken)
        if not rivals:
            continue
        n_best, best = rivals[-1]
        if n_best < MIN_ROSTER or mine * 2 >= n_best:
            continue
        if RESERVE.search(tname.get(best) or "") and not RESERVE.search(tname.get(tid) or ""):
            continue
        if how.startswith("name") and len(surnames(tid) & surnames(best)) < 2:
            refused.append((tid, best, how))
            continue
        moves.append((tid, best, fc, how, mine, n_best))
        taken.add(best)

    print(f"league slots pointing at a stale record while another holds FM's roster: {len(moves)}")
    for tid, best, how in refused:
        print(f"   refused (name only, squads share no surnames): {tname.get(tid)!r} -> "
              f"{tname.get(best)!r} via {how}")
    for tid, best, fc, how, mine, n in moves:
        print(f"   {slot_country[tid][:12]:12} {tname.get(tid)[:28]:28} ({tid}, {mine:>2} of FM's players)"
              f" -> {tname.get(best)[:22]!r} ({best}, {n} of them) | FM {fc} via {how}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not moves:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prerepoint")
    shutil.copy2(CAT, str(CAT) + ".bak-prerepoint")
    cur = con.cursor()
    cur.execute("BEGIN")
    for tid, best, fc, _how, _m, _n in moves:
        # the link travels with the club: exclusive, so the old holder lets go first
        cur.execute("UPDATE team_identity SET fm_club_id=NULL WHERE fm_club_id=?", (fc,))
        cur.execute("INSERT OR IGNORE INTO team_identity(team_id, method, confidence) "
                    "VALUES(?, 'repoint', 0.9)", (best,))
        cur.execute("UPDATE team_identity SET fm_club_id=?, method='repoint', confidence=0.9 "
                    "WHERE team_id=?", (fc, best))
        cur.execute("UPDATE teams SET league_id=(SELECT league_id FROM teams WHERE id=?) "
                    "WHERE id=?", (tid, best))
        cur.execute("UPDATE teams SET base_team_id=? WHERE base_team_id=? AND id>=? AND id<?",
                    (best, tid, CAREER_TEAM_LO, CAREER_TEAM_HI))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    to = {tid: best for tid, best, *_ in moves}
    logo = dict(con.execute("SELECT id, logo_path FROM teams"))
    n = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                if t["team_id"] in to:
                    new = to[t["team_id"]]
                    t["team_id"] = new
                    lp = logo.get(new)
                    if lp and (REPO / lp).exists():
                        t["logo"] = lp
                    t["squad"] = con.execute(
                        "SELECT COUNT(*) FROM squad_members WHERE team_id=?", (new,)).fetchone()[0]
                    n += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"applied. {n} league slots now point at the record holding the club.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
