#!/usr/bin/env python3
"""
link_career_copies.py — a career squad is made of copies, and the copies came without faces or crests.

The app seeds a career club by copying players into the career band, and the copy carries the name
and the numbers but not always the picture, the age or the nationality. On the squad screen that
reads as coloured initials where a face should be, and as 'Ag 0' with no flag beside it — Wataru
Endo at Liverpool had both.

The originals are still in the world and still hold all of it. Match the copy back to its original
and inherit what the copy is missing: the face, the age, the nationality, and — if the copy
arrived with no abilities at all — his numbers, which are the same man's. Nothing that the copy
already has is overwritten — a career save owns its own squad, and this only fills blanks.

Clubs are copies too, and they inherit the same way. The career Liverpool was still wearing the
crest of AFC Liverpool because that is what the world's Liverpool wore on the day it was copied;
fixing the world does not reach into a save. A career club takes its original's crest whenever the
original has a real file and the copy does not agree with it.

A last resort for the ones no world record matches: the club he actually plays for. 'Alisson' is a
mononym FM lists thirty-nine times, so no name rule can pick him out — but FM lists exactly one
Alisson at Liverpool, and that is who Liverpool's keeper is. Same name AND same club, resolving to
one player with a photograph, is evidence enough.

The match is by name with the accents folded (the copy says 'Martin Odegaard' where the world says
'Martin Ødegaard'), with nationality and age agreeing where both sides know them, and only when
exactly one world player fits. No identity rows are written: the validation gate requires a
career-band player to have none, and a face does not need one.

    python tools/link_career_copies.py --dry
    python tools/link_career_copies.py
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
CAREER_TEAM_LO, CAREER_TEAM_HI = 800_000, 1_000_000
CAREER_LO, CAREER_HI = 20_000_000, 700_000_000     # a save's player copies
CUR_LO, CUR_HI = 45_000_000_000, 46_000_000_000    # the curated overlay
# A reserve or youth side is not the club: 'Arsenal (T)', 'Schalke 04 II', 'Orlando City B'.
# Anchored to the END of the name and to whole words: an unanchored 'B' matches Brighton.
RESERVE = re.compile(r"(\s(II|B|2)|\bU-?1[5-9]\b|\bU-?2[0-3]\b|\bReserves?\b|\bAcademy\b|\(T\))\s*$", re.I)
PARTICLES = {"van", "von", "de", "del", "della", "der", "den", "di", "da", "dos", "das", "du",
             "la", "le", "el", "al", "bin", "ibn", "mac", "mc", "ter", "ten", "op", "st"}


# NFKD decomposes an accent off its letter, but these letters ARE letters, not accented ones:
# 'Odegaard' would never match 'Ødegaard' because the O is simply dropped. Same for Danish ae,
# Icelandic eth and thorn, Polish l-stroke, Croatian d-stroke, German sharp s.
FOLD = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "å": "a", "Å": "a",
                      "đ": "d", "Đ": "d", "ð": "d", "Ð": "d", "ł": "l", "Ł": "l",
                      "ß": "ss", "þ": "th", "Þ": "th", "ı": "i", "ʼ": "'"})


def key(s):
    s = unicodedata.normalize("NFKD", (s or "").translate(FOLD))
    s = s.encode("ascii", "ignore").decode().lower()
    return tuple(w for w in (w.strip("-") for w in re.sub(r"[^a-z -]", " ", s).split())
                 if len(w) > 1 and w not in PARTICLES)


def rotation(a, b):
    """The same name written the other way round: the world files Liverpool's midfielder as
    'Endo Wataru', the career copy as 'Wataru Endo'. A rotation, not any permutation — 'Seo Min-Woo'
    and 'Seo Woo-Min' are two people."""
    return len(a) > 1 and (a == b[1:] + b[:1] or a == b[-1:] + b[:-1])


def shorter(a, b):
    """One name is the other with words missing: the copy says 'Alisson', the world 'Alisson Becker'."""
    if not a or not b or len(a) == len(b):
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    it = iter(long_)
    return all(t in it for t in short)


def nat(s):
    return re.sub(r"[^a-z]", "", (s or "").split("/")[0].strip().lower())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    career_team = {p: t for p, t in con.execute("SELECT player_id, team_id FROM squad_members")
                   if CAREER_TEAM_LO <= t < CAREER_TEAM_HI}

    world = defaultdict(list)
    for pid, name, age, natn, rf, pf in con.execute(
            "SELECT p.id, p.name, p.age, p.nationality, p.real_face_path, p.portrait_path "
            "FROM players p WHERE p.superseded_by IS NULL"):
        # The original has to be a WORLD record. Earlier career seeds leave their copies behind
        # unsquadded, and those copies are exactly as blank or as wrong as the one being repaired —
        # a second 'Martin Odegaard' wearing a face keyed to somebody else's uid. Judging a copy
        # against another copy is how a wrong face spreads.
        if pid in career_team or CAREER_LO <= pid < CAREER_HI or CUR_LO <= pid < CUR_HI:
            continue
        world[key(name)].append((pid, name, age, nat(natn), natn, rf, pf))

    no_attrs = {p for (p,) in con.execute(
        "SELECT s.player_id FROM squad_members s LEFT JOIN player_attributes a "
        "ON a.player_id=s.player_id WHERE a.player_id IS NULL")}
    faces, ages, nats, attrs, amb = [], [], [], [], 0
    for pid, name, age, natn, rf, pf in con.execute(
            "SELECT p.id, p.name, p.age, p.nationality, p.real_face_path, p.portrait_path "
            "FROM players p WHERE p.superseded_by IS NULL"):
        if pid not in career_team:
            continue
        if (rf or pf) and age is not None and natn and pid not in no_attrs:
            continue          # nothing missing that the original could supply
        k = key(name)
        pool = list(world.get(k, []))
        if not pool:
            # the name may be written the other way round, or spelled out in full
            for wk, ws in world.items():
                if rotation(k, wk) or shorter(k, wk):
                    pool += ws
        cands = [w for w in pool
                 if (not natn or not w[3] or nat(natn) == w[3])
                 and (age is None or w[2] is None or abs(w[2] - age) <= 2)]
        best = [w for w in cands if w[5] or w[6]] or cands
        if len(best) > 1:
            uniq = {(w[5] or w[6], w[2], w[3]) for w in best}
            if len(uniq) > 1:
                amb += 1
                continue
        if not best:
            continue
        w = best[0]
        if not (rf or pf) and (w[5] or w[6]):
            faces.append((w[5], w[6], pid))
        if age is None and w[2] is not None:
            ages.append((w[2], pid))
        if not natn and w[4]:
            nats.append((w[4], pid))
        if pid in no_attrs:
            attrs.append((pid, w[0]))

    # ---- last resort: the club he plays for ----
    # Only for copies still without a picture, and only when the career club resolves to exactly one
    # FM club and the name resolves to exactly one player inside it.
    still = [(pid, nm, tid) for pid, nm, tid in con.execute(
        "SELECT p.id, p.name, s.team_id FROM squad_members s JOIN players p ON p.id=s.player_id "
        "WHERE s.team_id>=? AND s.team_id<? AND COALESCE(p.real_face_path,p.portrait_path) IS NULL",
        (CAREER_TEAM_LO, CAREER_TEAM_HI))]
    if still:
        faces_dir = REPO / "facepack" / "webp"
        on_disk = {f.stem[5:] for f in faces_dir.glob("face_*.webp")}
        fmclub = dict(con.execute(
            "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"))
        tname = dict(con.execute("SELECT id, name FROM teams"))
        world_club = defaultdict(set)
        for tid, nm in tname.items():
            if not (CAREER_TEAM_LO <= tid < CAREER_TEAM_HI) and nm and tid in fmclub:
                world_club[key(nm)].add(fmclub[tid])
        career_fm = {tid: next(iter(ids)) for tid, nm in tname.items()
                     if CAREER_TEAM_LO <= tid < CAREER_TEAM_HI and nm
                     for ids in [world_club.get(key(nm), set())] if len(ids) == 1}
        byclub = defaultdict(list)
        with open(MEMBER, encoding="cp1252", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                u, c = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip()
                if u.isdigit() and c.isdigit():
                    byclub[(int(c), key(r.get("Name")))].append(int(u))
        for pid, nm, tid in still:
            fc = career_fm.get(tid)
            if not fc:
                continue
            uids = [u for u in byclub.get((fc, key(nm)), []) if str(u) in on_disk]
            if len(uids) == 1:
                faces.append((f"facepack/webp/face_{uids[0]}.webp", None, pid))

    # ---- the back-pointer the live save never got ----
    # career_seed now records base_team_id when it copies a club, but the save in the database
    # predates that, so 44 career clubs and 2,508 copied players have no way back to the original.
    # Without it every id-keyed repair stops at the world and the save keeps yesterday's crest.
    sizes = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    world_team = defaultdict(list)
    world_team_ids = defaultdict(list)
    for tid, name, logo in con.execute("SELECT id, name, logo_path FROM teams"):
        if CAREER_TEAM_LO <= tid < CAREER_TEAM_HI or not name:
            continue
        if sizes.get(tid, 0) >= 11:
            world_team_ids[key(name)].append(tid)
        if logo and (REPO / logo).exists():
            world_team[key(name)].append((tid, name, logo))

    adopt_teams = []
    for tid, nm, base in con.execute(
            "SELECT id, name, base_team_id FROM teams WHERE id>=? AND id<?",
            (CAREER_TEAM_LO, CAREER_TEAM_HI)):
        if base is not None or not nm:
            continue
        cands = world_team_ids.get(key(nm), [])
        if len(cands) == 1:
            adopt_teams.append((cands[0], tid))

    # ---- the clubs themselves ----
    logo_of = dict(con.execute("SELECT id, logo_path FROM teams"))
    base_now = dict(con.execute(
        "SELECT id, base_team_id FROM teams WHERE id>=? AND id<? AND base_team_id IS NOT NULL",
        (CAREER_TEAM_LO, CAREER_TEAM_HI)))
    base_now.update({t: b for b, t in adopt_teams})
    crests = []
    for tid, name, logo in con.execute(
            "SELECT id, name, logo_path FROM teams WHERE id>=? AND id<?",
            (CAREER_TEAM_LO, CAREER_TEAM_HI)):
        # Follow the recorded original where there is one. The name fallback below is a shortlist
        # of one, which is not the same thing: career Arsenal shares a folded name with Arsenal
        # Tivat, and the day the real Arsenal's crest file goes missing that shortlist collapses to
        # the wrong club. base_team_id cannot collapse.
        base = base_now.get(tid)
        if base is not None:
            w = logo_of.get(base)
            if w and (REPO / w).exists() and logo != w:
                crests.append((w, tid, name, logo))
            continue
        cands = world_team.get(key(name), [])
        want = {c[2] for c in cands}
        if len(want) == 1 and not any(RESERVE.search(c[1]) for c in cands):
            w = cands[0][2]
            if logo != w:
                crests.append((w, tid, name, logo))

    print(f"career copies missing something their original has: faces {len(faces)}, "
          f"ages {len(ages)}, nationalities {len(nats)} (ambiguous, left alone: {amb})")
    print(f"career copies with no abilities at all, inheriting their original's: {len(attrs)}")
    print(f"career clubs with no recorded original, resolving to exactly one: {len(adopt_teams)}")
    print(f"career clubs wearing a different crest from their original: {len(crests)}")
    for w, tid, name, old_logo in crests[:6]:
        print(f"   {name[:26]:26} {(old_logo or 'none')[-28:]:28} -> {w[-28:]}")
    for rf, pf, pid in faces[:6]:
        nm = con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()[0]
        print(f"   {nm[:24]:24} -> {(rf or pf)[:44]}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not (faces or ages or nats or crests or attrs or adopt_teams):
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-precareercopy")
    con.executemany("UPDATE players SET real_face_path=COALESCE(real_face_path,?), "
                    "portrait_path=COALESCE(portrait_path,?) WHERE id=?", faces)
    con.executemany("UPDATE players SET age=? WHERE id=? AND age IS NULL", ages)
    con.executemany("UPDATE players SET nationality=? WHERE id=? AND nationality IS NULL", nats)
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", [(w, t) for w, t, _n, _o in crests])
    con.executemany("UPDATE teams SET base_team_id=? WHERE id=? AND base_team_id IS NULL",
                    adopt_teams)
    for pid, src in attrs:
        con.execute("INSERT OR REPLACE INTO player_attributes(player_id, attribute, value) "
                    "SELECT ?, attribute, value FROM player_attributes WHERE player_id=?",
                    (pid, src))
        con.execute("INSERT OR IGNORE INTO player_playstyles(player_id, playstyle, kind) "
                    "SELECT ?, playstyle, kind FROM player_playstyles WHERE player_id=?",
                    (pid, src))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(faces)} faces, {len(ages)} ages, {len(nats)} nationalities, "
          f"{len(crests)} crests, {len(attrs)} ability sets inherited | "
          f"{len(adopt_teams)} clubs now record their original.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
