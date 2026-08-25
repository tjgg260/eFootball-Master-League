#!/usr/bin/env python3
"""
fm_import_missing.py — the players FM lists at our clubs that the world never got.

167,209 FM senior rows have no record in the database, and almost all of them belong to clubs we
do not field in any league — amateur and lower-tier sides that are outside the rendered world by
design. 396 are not: they play for clubs that ARE in a catalog league, so their absence is a hole
in a squad we actually put on the pitch. Al-Nassr is missing ten men, Shabab Al-Ahli eight,
Arsenal had Eze nowhere in the database at all.

Import exactly those. Everything comes from the export itself, nothing is invented:

  id           10B + FM uid, the same encoding every FM-band record already uses
  name         'Eze, Ebere' is written surname-first; flip it
  age          from the date of birth, plus the three-year shift correction
               (fix_fm_age_shift: FM's dates are three years early, every one of them)
  position     parsed with fix_positions_from_fm's reader of FM's real grammar, not a prefix guess
  club         the catalog team its FM club id maps to, appended at the end of the squad on a
               shirt number nobody there is wearing

Attributes are NOT written here. 297 of the 396 have real 1-20 ladders on file, so
fm_derive_attributes gives them their own numbers; the rest fall to synth_attributes like any
other player without a ladder. Run those next, then the overalls, or the new players sit at zero.

    python tools/fm_import_missing.py --dry
    python tools/fm_import_missing.py
then: fm_derive_attributes.py, synth_attributes.py, fix_overalls.py, assign_roles.py,
      rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
MEMBER = REPO / "allavailable columns players.csv"

sys.path.insert(0, str(REPO / "tools"))
from fix_positions_from_fm import ef_positions   # noqa: E402

FM_BASE = 10_000_000_000
SHIFT, SEASON = 3, 2026
YOUTH = re.compile(r"\bU\s?-?(1[5-9]|2[0-3])\b")
MIN_AGE, MAX_AGE = 15, 45


def flip(name: str) -> str:
    """FM writes 'Eze, Ebere'; mononyms ('Rafinha') have no comma and are left alone."""
    n = (name or "").strip()
    if "," in n:
        last, first = n.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return n


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    incat = {t["team_id"] for co in cat["countries"] for lg in co["leagues"] for t in lg["teams"]}
    club_of = {fc: tid for tid, fc in con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL")}
    linked = {u for (u,) in con.execute(
        "SELECT fm_uid FROM player_identity WHERE fm_uid IS NOT NULL")}
    exists = {i for (i,) in con.execute("SELECT id FROM players")}
    tname = dict(con.execute("SELECT id, name FROM teams"))

    # The player may already BE at the club under a record FM was never joined to — five of the
    # first 396 were, and importing them again put the same man in the squad twice. Index the
    # squads by normalised name so an unlinked twin blocks the import.
    def nkey(s2):
        s2 = unicodedata.normalize("NFKD", s2 or "").encode("ascii", "ignore").decode().lower()
        return " ".join(sorted(re.sub(r"[^a-z ]", " ", s2).split()))

    at_club = set()
    for tid2, nm2 in con.execute(
            "SELECT s.team_id, p.name FROM squad_members s JOIN players p ON p.id=s.player_id "
            "WHERE p.superseded_by IS NULL"):
        at_club.add((tid2, nkey(nm2)))

    add = []
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            c = (r.get("Club ID") or "").strip()
            if not u.isdigit() or int(u) in linked or YOUTH.search(r.get("Squad") or ""):
                continue
            tid = club_of.get(int(c)) if c.isdigit() else None
            if tid not in incat:
                continue
            pid = FM_BASE + int(u)
            if pid in exists:
                continue
            d = (r.get("Date Of Birth") or "").strip()
            age = SEASON - int(d[-4:]) - SHIFT if len(d) >= 4 and d[-4:].isdigit() else None
            if age is not None and not (MIN_AGE <= age <= MAX_AGE):
                age = None
            if (tid, nkey(flip(r.get("Name")))) in at_club:
                continue                                  # already there, under another record
            pos = ef_positions(r.get("Position") or "")[0] or "CMF"
            add.append((pid, int(u), flip(r.get("Name")), age, (r.get("Nation") or "").strip(),
                        pos, tid))

    print(f"FM players at catalog clubs with no record in the world: {len(add)}")
    for a in add[:8]:
        print(f"   {a[2][:26]:26} {a[5]:4} age {a[3]} -> {tname.get(a[6])!r}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not add:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prefmmissing")
    cur.execute("BEGIN")
    for pid, uid, name, age, nat, pos, tid in add:
        # every FM-band row carries game_pid = its own id and is_custom 1, the way fm_import
        # wrote them; game_pid is NOT NULL
        cur.execute("INSERT INTO players(id, game_pid, name, position, age, nationality, "
                    "is_custom) VALUES(?,?,?,?,?,?,1)", (pid, pid, name, pos, age, nat))
        cur.execute("INSERT OR IGNORE INTO player_identity(player_id, kind, fm_uid, fm_method, "
                    "confidence) VALUES(?, 'fm', ?, 'id', 1.0)", (pid, uid))
        used = {n for (n,) in cur.execute(
            "SELECT squad_number FROM squad_members WHERE team_id=?", (tid,)) if n}
        # a few academy-heavy squads have all 99 shirts taken; the game only renders the
        # top 18, so a deep-bench number above 99 harms nothing and beats failing
        num = next(n for n in range(1, 1000) if n not in used)
        slot = cur.execute("SELECT COALESCE(MAX(slot),-1)+1 FROM squad_members WHERE team_id=?",
                           (tid,)).fetchone()[0]
        cur.execute("INSERT INTO squad_members(team_id, player_id, squad_number, slot) "
                    "VALUES(?,?,?,?)", (tid, pid, num, slot))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(add)} players imported into their clubs.")
    print("next: fm_derive_attributes.py, synth_attributes.py, fix_overalls.py — they have no "
          "attributes yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
