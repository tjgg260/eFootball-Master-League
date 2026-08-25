#!/usr/bin/env python3
"""
rfs_demote.py — RFS is the LAST source (owner ruling 2026-08-25: "players should first come from
efootball, then fm, THEN RFS"). Wherever a squadded RFS record can be replaced by the same human
sourced from eFootball or FM, it is — and where it cannot, at least its name is fixed.

Three fates per squadded RFS player:
  PROMOTE  a twin the merge already hid (eFootball- or FM-sourced) exists: it takes the squad
           place and the RFS record is superseded behind it.
  MINT     no record exists, but the FM ladder does: an FM-band record (10e9 + uid) is created
           with FM's full name, the ladder attributes through the calibrated 40-99 curve
           ([[attribute-scale-40-99]]), fm_bio physique, and the megapack face — then it takes
           the squad place.
  KEEP     no eFootball/FM source at all. The record stays exactly where it is; if it has an FM
           uid its surname-only name is replaced with FM's full name, which needs no ladder data.

FACES ARE NOT AT RISK: facepack/webp/face_<FM uid>.webp is keyed by the HUMAN, so a replacement
carrying the same uid wears the identical file (202,737 of them on disk). The only exception is a
record wearing a face with no uid, whose path is copied across verbatim.

Nothing is deleted — replaced records are marked players.superseded_by, so the whole pass is
reversible and stays inside the delete-nothing contract.

    python tools/rfs_demote.py --dry
    python tools/rfs_demote.py
then: assign_roles.py, rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from dt870_harvest import ABILITIES                       # noqa: E402
from fm_data_pass import EF_FROM_FM, overall_of, scale    # noqa: E402
from fm_derive_attributes import FM_CODE                  # noqa: E402

DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
PACK = REPO / "facepack" / "webp"
FM_BASE = 10_000_000_000
RFS_LO, RFS_HI = 700_000_000, 10_000_000_000


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s):
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def display(fm_name: str) -> str:
    """FM writes 'Surname, First'; the world shows 'First Surname'."""
    if "," in fm_name:
        sur, giv = fm_name.split(",", 1)
        return f"{giv.strip()} {sur.strip()}".strip()
    return fm_name.strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    uid_of = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    hidden = defaultdict(list)
    for pid, sup in con.execute("SELECT id, superseded_by FROM players WHERE superseded_by IS NOT NULL"):
        hidden[sup].append(pid)
    ladder = defaultdict(dict)
    for uid, a, v in con.execute("SELECT uid, attr, value FROM fm_attributes"):
        n = FM_CODE.get(a)
        if n:
            ladder[uid][n] = v
    bio = {u: (h, w) for u, h, w in con.execute("SELECT uid, height, weight FROM fm_bio")}
    fm_name = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            if u.isdigit():
                fm_name[int(u)] = (r.get("Name") or "").strip()
    pack = {int(m.group(1)) for fn in (os.listdir(PACK) if PACK.is_dir() else [])
            if (m := re.match(r"face_(\d+)\.webp$", fn))}
    exists = {r[0] for r in con.execute("SELECT id FROM players")}
    print(f"ladder {len(ladder):,} | fm names {len(fm_name):,} | faces {len(pack):,}")

    promote, mint, rename, keep = [], [], [], 0
    for pid, tid, slot, num, nm, pos, age, nat, face in con.execute("""
            SELECT s.player_id, s.team_id, s.slot, s.squad_number, p.name, p.position, p.age,
                   p.nationality, p.real_face_path
            FROM squad_members s JOIN players p ON p.id = s.player_id
            WHERE s.player_id >= ? AND s.player_id < ?
              AND NOT (s.team_id >= 800000 AND s.team_id < 1000000)""", (RFS_LO, RFS_HI)):
        uid = uid_of.get(pid)
        tw = [t for t in hidden.get(pid, ()) if not (RFS_LO <= t < RFS_HI)]
        if tw:
            tw.sort(key=lambda t: 0 if t < 16_777_216 else 1)      # eFootball twin first
            promote.append((pid, tw[0], tid, slot, num, face))
            continue
        if uid and uid in ladder and len(ladder[uid]) >= 12 and uid in fm_name:
            mint.append((pid, uid, tid, slot, num, nm, pos, age, nat, face))
            continue
        keep += 1
        if uid and uid in fm_name:
            want = display(fm_name[uid])
            if want and toks(nm) < toks(want):
                rename.append((want, pid))
    print(f"promote {len(promote):,} | mint {len(mint):,} | keep {keep:,} "
          f"(of which renamed from FM: {len(rename):,})")
    for w, p in rename[:5]:
        print(f"   rename {p}: -> '{w}'")
    for pid, uid, *_r in mint[:5]:
        print(f"   mint {FM_BASE + uid} '{display(fm_name[uid])}' replacing RFS {pid}")
    if dry:
        print("--dry: nothing written.")
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prerfsdemote")
    cur.execute("BEGIN")
    cur.executemany("UPDATE players SET name=? WHERE id=?", rename)

    # A twin with no attributes cannot be compiled into a match, so it is not a replacement:
    # gate 3 and gate 8 both reject it. Verify before handing over the squad place.
    ok = {r[0] for r in cur.execute(
        "SELECT player_id FROM player_attributes GROUP BY player_id HAVING COUNT(*) >= 20")}
    skipped = [x for x in promote if x[1] not in ok]
    promote = [x for x in promote if x[1] in ok]
    if skipped:
        print(f"  {len(skipped):,} promotions skipped — the twin has no attribute set")

    # ---- promote hidden twins into the squad place
    for pid, tw, tid, slot, num, face in promote:
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (tw,))
        cur.execute("DELETE FROM squad_members WHERE team_id=? AND player_id=?", (tid, pid))
        cur.execute("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot,role)"
                    " VALUES(?,?,?,?,0)", (tid, tw, num, slot))
        cur.execute("UPDATE players SET superseded_by=NULL WHERE id=?", (tw,))
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (tw, pid))
        # anything that pointed at the record we just superseded must follow it, or the marks
        # form a chain and gate 9 rejects them
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (tw, pid, tw))
        # a promoted eFootball record usually has no spine row of its own; gate 7 needs one
        cur.execute("INSERT OR IGNORE INTO player_identity(player_id,kind,ef_pid,ef_method,"
                    "confidence) SELECT ?, 'ef', ?, 'id', 1.0 WHERE ? < 16777216", (tw, tw, tw))
        if face:
            cur.execute("UPDATE players SET real_face_path=COALESCE(NULLIF(real_face_path,''),?) "
                        "WHERE id=?", (face, tw))

    # ---- mint FM records
    n_new = n_attr = 0
    for pid, uid, tid, slot, num, nm, pos, age, nat, face in mint:
        nid = FM_BASE + uid
        fm = ladder[uid]
        vals = {}
        for ef, srcs in EF_FROM_FM.items():
            tot = den = 0
            for k, w in srcs.items():
                if k in fm:
                    tot += fm[k] * w
                    den += w
            if den:
                vals[ef] = scale(tot / den)
        if len(vals) < 20:
            continue
        h, w = bio.get(uid, (None, None))
        facepath = (f"facepack/webp/face_{uid}.webp" if uid in pack else face) or None
        ov = overall_of({**{a: 40 for a in ABILITIES}, **vals}, pos or "CMF")
        if nid in exists:
            cur.execute("UPDATE players SET superseded_by=NULL, name=?, position=COALESCE(position,?),"
                        " age=COALESCE(age,?), nationality=COALESCE(nationality,?),"
                        " overall_rating=?, real_face_path=COALESCE(NULLIF(real_face_path,''),?)"
                        " WHERE id=?",
                        (display(fm_name[uid]), pos, age, nat, ov, facepath, nid))
        else:
            cur.execute("INSERT INTO players(id,game_pid,is_custom,name,short_name,position,age,"
                        "nationality,height_cm,weight_kg,overall_rating,real_face_path) "
                        "VALUES(?,?,1,?,?,?,?,?,?,?,?,?)",
                        (nid, nid, display(fm_name[uid]), display(fm_name[uid]), pos, age, nat,
                         h, w, ov, facepath))
            n_new += 1
        cur.execute("INSERT OR REPLACE INTO player_identity"
                    "(player_id,kind,fm_uid,fm_method,confidence) VALUES(?,'fm',?, 'id',1.0)",
                    (nid, uid))
        cur.execute("DELETE FROM player_attributes WHERE player_id=?", (nid,))
        cur.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                        [(nid, a, v) for a, v in vals.items()])
        n_attr += len(vals)
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (nid,))
        cur.execute("DELETE FROM squad_members WHERE team_id=? AND player_id=?", (tid, pid))
        cur.execute("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot,role)"
                    " VALUES(?,?,?,?,0)", (tid, nid, num, slot))
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (nid, pid))
        cur.execute("UPDATE players SET superseded_by=? WHERE superseded_by=? AND id<>?",
                    (nid, pid, nid))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. promoted {len(promote):,} | minted {n_new:,} new FM records "
          f"({n_attr:,} attribute values) | renamed {len(rename):,}")
    print("next: assign_roles.py, rerank_slots.py, validate_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
