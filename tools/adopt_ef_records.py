#!/usr/bin/env python3
"""
adopt_ef_records.py — where a player exists twice, the eFootball record is the player.

ter Stegen is in the database twice: eFootball's record, rated 80 with Konami's own attributes and
no club at all, and an FM record 'Marc-Andre ter Stegen' rated 71, playing for Ajax. Same for
Alexander-Arnold, Bruno Guimaraes, Bernardo Silva, Joao Neves. The identity spine never joined the
pair because the names are spelled differently, and link_ef_to_fm cannot fix it either: the FM row
it would link to is already claimed — by the FM record itself.

So merge rather than link. The eFootball record is the survivor, which is the standing ruling on
data (a player who exists in eFootball keeps eFootball's attributes) and the reason the pair is
worth resolving at all: the better-attributed copy is the one sitting outside the world. It takes
the FM record's club, shirt and squad slot, and its fm_uid, so the next membership sync keeps
moving him. The FM record is superseded behind him, kept but dormant.

A pair is accepted only when the eFootball record has no FM link and no club, the FM record has
both, one name is the other with words missing or spelled out in full, nationality agrees, ages
are within 2, and exactly one FM record fits.

    python tools/adopt_ef_records.py --dry
    python tools/adopt_ef_records.py
then: rerank_slots.py, validate_db.py
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
EF_HI = 20_000_000
FM_LO, FM_HI = 10_000_000_000, 13_000_000_000
NAT_SYN = {"u s a": "united states", "usa": "united states", "turkiye": "turkey",
           "korea republic": "south korea", "china pr": "china", "czechia": "czech republic"}


def key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return tuple(t for t in re.sub(r"[^a-z ]", " ", s).split() if len(t) > 1)


def subseq(a, b):
    it = iter(b)
    return all(t in it for t in a)


def initial(name):
    m = re.match(r"\s*([A-Za-z])\.", name or "")
    return m.group(1).lower() if m else None


def nat(s):
    v = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (s or "").split("/")[0].strip().lower())).strip()
    return NAT_SYN.get(v, v)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    squadded = {p for (p,) in con.execute("SELECT player_id FROM squad_members")}
    fm_side = []
    for pid, name, natn, age, uid in con.execute(
            "SELECT p.id, p.name, p.nationality, p.age, pi.fm_uid FROM players p "
            "JOIN player_identity pi ON pi.player_id=p.id "
            "WHERE p.superseded_by IS NULL AND pi.fm_uid IS NOT NULL AND p.id>=? AND p.id<?",
            (FM_LO, FM_HI)):
        if pid in squadded:
            fm_side.append((pid, name, nat(natn), age, uid, key(name)))
    by_tok = defaultdict(list)
    for f in fm_side:
        for t in f[5]:
            by_tok[t].append(f)

    pairs, amb = [], 0
    for pid, name, natn, age, face, port in con.execute(
            "SELECT p.id, p.name, p.nationality, p.age, p.real_face_path, p.portrait_path "
            "FROM players p LEFT JOIN player_identity pi ON pi.player_id=p.id "
            "WHERE p.superseded_by IS NULL AND pi.fm_uid IS NULL AND p.id<?", (EF_HI,)):
        if pid in squadded:
            continue
        k = key(name)
        if len(k) < 2:
            continue                                   # a bare surname is not enough to adopt on
        seen, hits = set(), []
        ini = initial(name)
        for t in k:
            for f in by_tok.get(t, []):
                if f[0] in seen:
                    continue
                seen.add(f[0])
                if f[2] != nat(natn) or age is None or f[3] is None or abs(f[3] - age) > 2:
                    continue
                if not (k == f[5] or subseq(k, f[5]) or subseq(f[5], k)):
                    continue
                if ini and not f[5][0].startswith(ini):
                    continue
                hits.append(f)
        if len(hits) == 1:
            pairs.append(((pid, name, face, port), hits[0]))
        elif hits:
            amb += 1

    print(f"eFootball records with no club whose player IS in the world as an FM record: "
          f"{len(pairs):,} (ambiguous, left alone: {amb:,})")
    for (pid, name, _f, _p), f in pairs[:10]:
        print(f"   {name[:26]:26} (id {pid}) adopts {f[1][:26]!r} at his club")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not pairs:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preadopt")
    cur.execute("BEGIN")
    for (pid, _name, face, port), f in pairs:
        fm_pid, _fn, _fnat, _fage, uid, _fk = f
        row = cur.execute(
            "SELECT team_id, squad_number, slot, role FROM squad_members WHERE player_id=?",
            (fm_pid,)).fetchone()
        if row is None:
            continue
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (fm_pid,))
        cur.execute("INSERT INTO squad_members(team_id, player_id, squad_number, slot, role) "
                    "VALUES(?,?,?,?,?)", (row[0], pid, row[1], row[2], row[3]))
        cur.execute("INSERT OR IGNORE INTO player_identity(player_id, kind, confidence) "
                    "VALUES(?, 'ef', 0.9)", (pid,))
        cur.execute("UPDATE player_identity SET fm_uid=?, fm_method='adopted' WHERE player_id=?",
                    (uid, pid))
        cur.execute("UPDATE player_identity SET fm_uid=NULL WHERE player_id=?", (fm_pid,))
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (pid, fm_pid))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (pid, fm_pid, pid))
        if not (face or port):
            src = cur.execute("SELECT real_face_path, portrait_path FROM players WHERE id=?",
                              (fm_pid,)).fetchone()
            if src and (src[0] or src[1]):
                cur.execute("UPDATE players SET real_face_path=COALESCE(real_face_path,?), "
                            "portrait_path=COALESCE(portrait_path,?) WHERE id=?",
                            (src[0], src[1], pid))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(pairs):,} eFootball records took their own place in the world.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
