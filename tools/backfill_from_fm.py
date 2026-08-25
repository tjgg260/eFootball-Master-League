#!/usr/bin/env python3
"""
backfill_from_fm.py — fill the fields we left blank or short, from the row FM already gives us.

Two small tails the sweep keeps finding, both on players whose FM row is sitting right there:

  AGE     15 squadded players have no age at all, or one outside 15-45 (Tadic, Anderson Lopes,
          a 55-year-old at B68 Toftir, a 46-year-old at At. Tomelloso). FM's date of birth is
          three years early — the shift fix established that beyond doubt — so the age is
          season year minus (birth year + 3).

  NAME    a player shown by surname alone while the export carries his full name ('Espigares'
          for 'Espigares, Antonio'). Written the way the world writes names: given name first.

  REGENS  1,158 FM-band records carry a name belonging to nobody in their FM row. They are not
          mis-linked — an FM-band id IS 10B plus the uid — they are FM's generated youth, and a
          regenerated save fills the same slot with a new person. Ours has 'Alex Cardines', a
          20-year-old English keeper at Barnet; the current export has uid 16021434 as 'Jack
          Jackson', an English keeper at Barnet born 2007. Same club, same position, same year:
          the slot survived, the identity was rolled again. Everything else about the record
          already follows the current export, so the name and nationality should too.

Only ever fills or lengthens for real players: an age we already have is not overwritten, and a
name is only replaced when the export's version has strictly more of it — or, for those FM-band
regens, when it shares no word with ours at all. eFootball's own records are never touched here:
a name that disagrees on an eFootball record means the LINK is wrong, not the name, and that is
fix_ef_link_collisions' business.

    python tools/backfill_from_fm.py --dry
    python tools/backfill_from_fm.py
"""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
SHIFT, SEASON = 3, 2026
MIN_AGE, MAX_AGE = 15, 45
FM_BASE = 10_000_000_000      # an FM-band id IS the base plus the uid, which is what makes the
FM_HI = 13_000_000_000        # regen case safe: the record's identity is not in doubt, only its name


# 'van Dijk' and 'de Jong' are surnames, not full names — the particle travels with the surname,
# so counting words would call them identified when they are not.
PARTICLES = {"van", "von", "de", "del", "della", "der", "den", "di", "da", "dos", "das", "du",
             "la", "le", "el", "al", "bin", "ibn", "mac", "mc", "ter", "ten", "op", "st"}


def toks(s):
    """Name words: split on spaces, so 'Saint-Maximin' stays ONE name; particles and bare
    initials are not given names of their own."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [w for w in (w.strip("-") for w in re.sub(r"[^a-z -]", " ", s).split())
            if len(w) > 1 and w not in PARTICLES]


def flip(name: str) -> str:
    n = (name or "").strip()
    if "," in n:
        last, first = n.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return n


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)

    fm = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            if u.isdigit():
                d = (r.get("Date Of Birth") or "").strip()
                age = SEASON - int(d[-4:]) - SHIFT if len(d) >= 4 and d[-4:].isdigit() else None
                fm[int(u)] = (flip(r.get("Name")), age, (r.get("Nation") or "").strip())

    ages, names, regens = [], [], []
    for pid, name, age, uid in con.execute(
            "SELECT p.id, p.name, p.age, pi.fm_uid FROM players p "
            "JOIN player_identity pi ON pi.player_id=p.id JOIN squad_members s ON s.player_id=p.id "
            "WHERE pi.fm_uid IS NOT NULL AND p.superseded_by IS NULL"):
        fname, fage, fnat = fm.get(uid, (None, None, None))
        if fage is not None and MIN_AGE <= fage <= MAX_AGE:
            if age is None or not (MIN_AGE <= age <= MAX_AGE):
                ages.append((fage, pid))
        if not fname:
            continue
        a, b = set(toks(name)), set(toks(fname))
        if len(toks(name)) < 2 and len(b) > len(a):
            names.append((fname, pid, name))
        elif a and b and not (a & b) and pid < FM_HI and pid - FM_BASE == uid:
            regens.append((fname, fnat, pid, name))

    print(f"squadded players to give an age: {len(ages)} | names to lengthen: {len(names)} | "
          f"FM regen slots to re-identify: {len(regens)}")
    for a, pid in ages[:6]:
        print(f"   id {pid} -> age {a}")
    for n, pid, old in names[:6]:
        print(f"   id {pid}: {old!r} -> {n!r}")
    for n, nat, pid, old in regens[:6]:
        print(f"   regen {pid}: {old!r} -> {n!r} ({nat})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not ages and not names and not regens:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prebackfill")
    con.executemany("UPDATE players SET age=? WHERE id=?", ages)
    con.executemany("UPDATE players SET name=? WHERE id=?", [(n, p) for n, p, _o in names])
    con.executemany("UPDATE players SET name=?, nationality=? WHERE id=?",
                    [(n, nat, p) for n, nat, p, _o in regens])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(ages)} ages, {len(names)} names, {len(regens)} regens re-identified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
