#!/usr/bin/env python3
"""
relink_faces_by_uid.py — faces by IDENTITY, not guesswork. The sortitoutsi pack is keyed by FM uid
(face_<uid>.webp) and the spine knows almost every player's fm_uid — so the face lookup is EXACT:

  spine fm_uid + face file exists  -> real_face_path = that file (fixes both 'fake face despite
                                      being famous' and 'wrong person's face' in one stroke)
  spine fm_uid + NO face file      -> if the current face belongs to a DIFFERENT uid, drop it
                                      (an honest generated portrait beats the wrong man's photo)

Career copies (20M-700M) aren't in the spine; they inherited faces at seed time, so they are
re-pointed by matching name+age to their catalog source club's squad.

    python tools/relink_faces_by_uid.py --dry
    python tools/relink_faces_by_uid.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
PACK = REPO / "facepack" / "webp"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    have = {int(m.group(1)) for f in PACK.glob("face_*.webp")
            if (m := re.match(r"face_(\d+)\.webp$", f.name))}
    print(f"facepack files: {len(have):,}")

    fixed = wrong_swapped = dropped = 0
    face_pat = re.compile(r"face_(\d+)\.webp$")
    updates, clears = [], []
    for pid, uid, cur in con.execute(
            "SELECT pi.player_id, pi.fm_uid, p.real_face_path FROM player_identity pi "
            "JOIN players p ON p.id=pi.player_id WHERE pi.fm_uid IS NOT NULL"):
        cur_uid = int(m.group(1)) if cur and (m := face_pat.search(cur)) else None
        if uid in have:
            expect = f"facepack/webp/face_{uid}.webp"
            if cur != expect:
                updates.append((expect, pid))
                if cur_uid is not None and cur_uid != uid:
                    wrong_swapped += 1
                else:
                    fixed += 1
        elif cur_uid is not None and cur_uid != uid:
            clears.append((pid,))
            dropped += 1
    print(f"faces set by exact uid: {fixed:,} | WRONG-PERSON faces corrected: {wrong_swapped:,} | "
          f"wrong faces dropped (no photo for the real uid): {dropped:,}")

    # -- PASS 2: identity closure via the CLUB ROSTER. A stub-named player ('Simons',
    # 'van de Ven') has no spine uid because full-name matching can't see him — but his club's FM
    # roster is tiny, and a surname is unique inside it. Match within the roster, gain the uid,
    # write it back into the spine (method 'roster'), take the uid-exact face.
    import csv
    import unicodedata
    from collections import defaultdict

    def norm(s):
        return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()

    club_roster = defaultdict(list)          # fm_club_id -> [(uid, full name)]
    src_csv = REPO / "allavailable columns players.csv"
    if src_csv.exists():
        with open(src_csv, encoding="cp1252", errors="replace", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                u, c, nm = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip(), \
                    (r.get("Name") or "").strip()
                if u.lstrip("-").isdigit() and c.lstrip("-").isdigit() and int(c) > 0 and nm:
                    club_roster[int(c)].append((int(u), nm))
    team_fm = dict(con.execute("SELECT team_id, fm_club_id FROM team_identity "
                               "WHERE fm_club_id IS NOT NULL"))
    have_uid = {r[0] for r in con.execute(
        "SELECT player_id FROM player_identity WHERE fm_uid IS NOT NULL")}
    roster_hits, spine_adds = 0, []
    for tid, fmcid in team_fm.items():
        roster = club_roster.get(fmcid)
        if not roster or 800_000 <= tid < 900_000:
            continue
        for pid, nm, cur in con.execute(
                "SELECT p.id, p.name, p.real_face_path FROM squad_members s "
                "JOIN players p ON p.id=s.player_id WHERE s.team_id=?", (tid,)):
            if pid in have_uid or pid >= 50_000_000_000:
                continue
            toks = [t for t in re.sub(r"[^a-z ]", " ", norm(nm)).split() if len(t) >= 3]
            if not toks:
                continue
            cands = [u for u, full in roster
                     if all(t in re.sub(r"[^a-z ]", " ", norm(full)).split() for t in toks)]
            if len(set(cands)) != 1:
                continue
            uid = cands[0]
            spine_adds.append((pid, uid))
            if uid in have:
                expect = f"facepack/webp/face_{uid}.webp"
                if cur != expect:
                    updates.append((expect, pid))
                    roster_hits += 1
    print(f"roster-closure: {len(spine_adds):,} stub players gained an FM identity, "
          f"{roster_hits:,} of them a uid-exact face")

    # career copies: re-point from their catalog source club by name+age
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    src_by_name = {}
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                src_by_name.setdefault(t["name"].strip().lower(), t["team_id"])
    cupd = 0
    cupdates = []
    for ctid, cname in con.execute("SELECT id, name FROM teams WHERE id>=800000 AND id<900000"):
        stid = src_by_name.get((cname or "").strip().lower())
        if not stid:
            continue
        # apply updates queued above first when reading the source? handled: read source AFTER
        # main update in apply mode; in dry mode this still estimates from current values.
        srcmap = {(nm, age): (rf, pp) for nm, age, rf, pp in con.execute(
            "SELECT p.name, p.age, p.real_face_path, p.portrait_path FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE s.team_id=?", (stid,))}
        for cpid, nm, age, crf in con.execute(
                "SELECT p.id, p.name, p.age, p.real_face_path FROM squad_members s "
                "JOIN players p ON p.id=s.player_id WHERE s.team_id=?", (ctid,)):
            hit = srcmap.get((nm, age))
            if hit and (hit[0] or hit[1]):
                nf = hit[0] or hit[1]
                if nf != crf:
                    cupdates.append((hit[0], hit[1], cpid))
                    cupd += 1
    print(f"career copies re-pointed to source faces: {cupd:,}")
    if dry:
        return 0

    shutil.copy2(DB, str(DB) + ".bak-prerelink")
    con.executemany("UPDATE players SET real_face_path=? WHERE id=?", updates)
    con.executemany("UPDATE players SET real_face_path=NULL WHERE id=?", clears)
    con.executemany("UPDATE player_identity SET fm_uid=?, fm_method='roster', confidence=0.9 "
                    "WHERE player_id=? AND fm_uid IS NULL",
                    [(u, p) for p, u in spine_adds])
    con.commit()
    # career pass AFTER the reference fix so copies inherit corrected faces
    cupdates = []
    for ctid, cname in con.execute("SELECT id, name FROM teams WHERE id>=800000 AND id<900000"):
        stid = src_by_name.get((cname or "").strip().lower())
        if not stid:
            continue
        srcmap = {(nm, age): (rf, pp) for nm, age, rf, pp in con.execute(
            "SELECT p.name, p.age, p.real_face_path, p.portrait_path FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE s.team_id=?", (stid,))}
        for cpid, nm, age, _crf in con.execute(
                "SELECT p.id, p.name, p.age, p.real_face_path FROM squad_members s "
                "JOIN players p ON p.id=s.player_id WHERE s.team_id=?", (ctid,)):
            hit = srcmap.get((nm, age))
            if hit and (hit[0] or hit[1]):
                cupdates.append((hit[0], hit[1], cpid))
    con.executemany("UPDATE players SET real_face_path=?, portrait_path=COALESCE(?, portrait_path) "
                    "WHERE id=?", cupdates)
    con.commit()
    print(f"applied: {len(updates):,} uid faces, {len(clears):,} wrong faces dropped, "
          f"{len(cupdates):,} career copies synced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
