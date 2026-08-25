#!/usr/bin/env python3
"""
supersede_squad_twins.py — the same human twice in one squad, when the spine agrees he is one.

Correcting the FM date-of-birth shift moved 270k ages, and two pairs that had been hidden behind a
wrong age landed on top of each other. Only one of them was a duplicate: Real Salt Lake fielded
'Owen Anderson', 19, rated 63, as both an eFootball record and an FM record. The other pair —
two Brazilians called 'Henrique' at Altos — carries two DIFFERENT FM uids, so FM is saying plainly
that these are two people who share a common mononym, and nothing should merge them.

That is the rule here: a name and an age are not an identity, but two distinct fm_uids ARE two
humans. Merge only when the spine does not contradict it — the pair shares a uid, or at most one
of them has one — and nationality agrees. The survivor is the better source (eFootball first, then
FM, then RFS) and inherits the other's fm_uid, ef_pid and face, so nothing about him is lost.

    python tools/supersede_squad_twins.py --dry
    python tools/supersede_squad_twins.py
then: validate_db.py
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
NAT_SYN = {"u s a": "united states", "usa": "united states", "turkiye": "turkey",
           "korea republic": "south korea", "china pr": "china", "czechia": "czech republic"}


def key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(re.sub(r"[^a-z ]", " ", s).split()))


def nat(s):
    v = re.sub(r"[^a-z ]", " ", (s or "").split("/")[0].strip().lower()).strip()
    v = re.sub(r"\s+", " ", v)
    return NAT_SYN.get(v, v)


def band(pid):
    if pid < 20_000_000:
        return 0                                   # eFootball: the attribute authority
    if pid >= 10_000_000_000:
        return 1                                   # FM
    return 2                                       # RFS last (owner ruling)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    ident = {p: (u, e) for p, u, e in con.execute(
        "SELECT player_id, fm_uid, ef_pid FROM player_identity")}

    groups = defaultdict(list)
    for tid, pid, name, age, natn, face, port in con.execute(
            "SELECT s.team_id, p.id, p.name, p.age, p.nationality, p.real_face_path, "
            "p.portrait_path FROM squad_members s JOIN players p ON p.id=s.player_id "
            "WHERE p.superseded_by IS NULL AND p.name IS NOT NULL AND p.age IS NOT NULL"):
        groups[(tid, key(name), age)].append((pid, name, natn, face, port))

    merges, distinct, mixed = [], 0, 0
    for (_tid, _k, _age), v in groups.items():
        if len(v) < 2:
            continue
        uids = [ident.get(x[0], (None, None))[0] for x in v]
        known = [u for u in uids if u]
        if len(set(known)) > 1:
            distinct += 1                          # FM says these are different humans
            continue
        if len({nat(x[2]) for x in v}) > 1:
            mixed += 1
            continue
        v = sorted(v, key=lambda x: band(x[0]))
        merges.append((v[0], v[1:]))

    print(f"same club, same name, same age: {len(merges) + distinct + mixed} groups | "
          f"merge: {len(merges)} | left alone as namesakes (distinct FM uids): {distinct} | "
          f"nationalities disagree: {mixed}")
    for keep, others in merges:
        print(f"   keep {keep[1]!r} id={keep[0]}  <-  " +
              ", ".join(f"id={o[0]}" for o in others))
    if dry:
        print("--dry: nothing written.")
        return 0
    if not merges:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-presquadtwin")
    cur.execute("BEGIN")
    for keep, others in merges:
        kid = keep[0]
        ku, ke = ident.get(kid, (None, None))
        for o in others:
            ou, oe = ident.get(o[0], (None, None))
            cur.execute("DELETE FROM squad_members WHERE player_id=?", (o[0],))
            cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (kid, o[0]))
            cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                        (kid, o[0], kid))
            if (ku is None and ou is not None) or (ke is None and oe is not None):
                cur.execute("INSERT OR IGNORE INTO player_identity(player_id, kind, confidence) "
                            "VALUES(?, 'merged', 0.9)", (kid,))
                cur.execute("UPDATE player_identity SET fm_uid=COALESCE(fm_uid,?), "
                            "ef_pid=COALESCE(ef_pid,?) WHERE player_id=?", (ou, oe, kid))
                ku, ke = ku or ou, ke or oe
            if not (keep[3] or keep[4]) and (o[3] or o[4]):
                cur.execute("UPDATE players SET real_face_path=COALESCE(real_face_path,?), "
                            "portrait_path=COALESCE(portrait_path,?) WHERE id=?", (o[3], o[4], kid))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {sum(len(o) for _k, o in merges)} duplicate records superseded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
