#!/usr/bin/env python3
"""
assign_staff.py — place every FM staff member who holds a club job at their club's team.

Builds staff_assignments(staff_uid, team_id, job) from the staff ingest. The chain is the one
the blueprint sanctions: fm_raw_staff 'Club' (a name — the FM staff export carries no club uid)
-> fm_clubs.name -> fm_clubs.uid -> team_identity.fm_club_id -> teams.id. Only the first hop is
by name, and it is name-vs-name inside the SAME FM export generation; everything after it is an
exact spine join. staff_uid is the RAW FM uid, the same key fm_raw_staff / fm_staff_attributes
use (NOT the 10B+ player namespace — staff never enter player_identity).

Name-hop details, learned from the data:
  * fm_clubs names were ascii-folded at ingest ('Besiktas'); the staff export kept diacritics
    ('Beşiktaş'). Both sides are folded with fold() before comparing, which also maps the chars
    NFKD won't decompose (ı ł ø đ ß ...).
  * fm_clubs names are NOT unique (three 'Rangers'). Candidates are filtered to spine-linked
    uids; if several remain, the top one is taken only when its reputation beats every rival by
    a DECISIVE margin (>= 1000); otherwise the staff member is left unplaced and reported.
  * One fm_club_id can map to several team rows (RFS/eF twin records). The canonical team is
    method='exact' first, then the row with the bigger squad, then the lower team id.
  * The spine holds a handful of POISONED fuzzy links: national-team rows matched to obscure
    clubs ('Malta' <- SV Malta of Austria, 'Croatia' <- NK Croatia of Sweden...). Club staff can
    never belong to a national team, so fuzzy spine rows whose team name is exactly a country
    name are rejected here (and reported) — a semantic sanity check, not a name-match join.

Managers (Club Job 'Manager' / 'Player / Manager') additionally write the real name (and 3-letter
nationality) onto the game-facing coaches row of their club, replacing placeholder names like
'Port FC Manager'. The coaches row may hang off a TWIN team record of the same fm club (the spine
maps one fm_club_id to several team rows), so the rename walks every spine sibling — still an
exact join. One manager per club: best tactical attributes wins, then lower uid. Coach rows whose
team has no fm_club_id anywhere in the spine are out of reach and are counted in the report —
that is a spine-coverage gap for build_identity to close, not something to bridge by name here.

staff_assignments is derived output and is rebuilt from scratch every run (the db is a compiled
artifact — rebuild, don't patch).

    python tools/assign_staff.py            # --dry report: counts by job, top unmatched clubs
    python tools/assign_staff.py --apply    # backup, rebuild staff_assignments, update coaches
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

MANAGER_JOBS = {"Manager", "Player / Manager"}

# chars NFKD does not decompose to ascii — mapped by hand before folding
_TRANS = str.maketrans({
    "ı": "i", "Ł": "L", "ł": "l", "Ø": "O", "ø": "o", "Đ": "D", "đ": "d",
    "ß": "ss", "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "Ð": "D", "ð": "d",
    "Þ": "Th", "þ": "th", "･": ".",
})


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.translate(_TRANS))
    return s.encode("ascii", "ignore").decode().lower().strip()


def load_staff(con: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """Pivot fm_raw_staff to {uid: {col: val}} for the columns this tool needs."""
    staff: dict[int, dict[str, str]] = defaultdict(dict)
    q = "SELECT key, col, val FROM fm_raw_staff WHERE col IN ('UID','Name','Nat','Club','Club Job','Job')"
    for key, col, val in con.execute(q):
        if key.isdigit():
            staff[int(key)][col] = val
    return staff


def club_resolver(con: sqlite3.Connection):
    """Build the name -> spine machinery once. Returns (resolve, siblings) where
    resolve(club_name) -> (fm_club_id | None, team_id | None, reason) and
    siblings[fm_club_id] -> every spine team_id of that fm club (canonical first)."""
    # folded fm_clubs name -> [(uid, reputation)]
    by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for uid, name, rep in con.execute("SELECT uid, name, reputation FROM fm_clubs WHERE name IS NOT NULL"):
        by_name[fold(name)].append((uid, rep or 0))

    # a fuzzy spine row that landed on a national team is an upstream mis-link — reject it
    nations = {n for (n,) in con.execute("SELECT DISTINCT nation FROM fm_clubs WHERE nation IS NOT NULL")}

    # fm_club_id -> spine team rows ranked canonical-first (method='exact', bigger squad, lower id)
    ranked: dict[int, list[tuple]] = defaultdict(list)
    poisoned: list[tuple[int, str]] = []           # (team_id, team name) rejected rows
    q = """SELECT ti.fm_club_id, ti.team_id, ti.method, t.name,
                  (SELECT COUNT(*) FROM squad_members sm WHERE sm.team_id = ti.team_id)
           FROM team_identity ti JOIN teams t ON t.id = ti.team_id
           WHERE ti.fm_club_id IS NOT NULL"""
    for fm_id, team_id, method, tname, squad in con.execute(q):
        if method == "fuzzy" and tname in nations:
            poisoned.append((team_id, tname))
            continue
        ranked[fm_id].append((0 if method == "exact" else 1, -squad, team_id))
    siblings = {fm_id: [t for _, _, t in sorted(rows)] for fm_id, rows in ranked.items()}

    # Career copies (800000-899999) live OUTSIDE the spine by design, but their coaches rows are
    # what the app actually shows — bridge each one by NAME to its catalog source's fm club so
    # the visible manager gets the real name too.
    tname_all = dict(con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL"))
    name2fm: dict[str, int] = {}
    for fm_id, sibs in siblings.items():
        for t in sibs:
            nm = (tname_all.get(t) or "").strip().lower()
            if nm:
                name2fm.setdefault(nm, fm_id)
    for ctid, cname in con.execute("SELECT id, name FROM teams WHERE id>=800000 AND id<900000"):
        fmid = name2fm.get((cname or "").strip().lower())
        if fmid:
            siblings[fmid].append(ctid)

    def resolve(club: str) -> tuple[int | None, int | None, str]:
        cands = by_name.get(fold(club))
        if not cands:
            return None, None, "no fm_clubs name"
        linked = [(uid, rep) for uid, rep in cands if uid in siblings]
        if not linked:
            return None, None, "no spine link"
        if len(linked) > 1:
            linked.sort(key=lambda t: -t[1])
            if linked[0][1] < linked[1][1] + 1000:   # no decisive reputation gap
                return None, None, "ambiguous"
        fm_id = linked[0][0]
        return fm_id, siblings[fm_id][0], "ok"

    return resolve, siblings, poisoned


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB if apply else f"file:{DB.as_posix()}?mode=ro", uri=not apply, timeout=60)

    staff = load_staff(con)
    resolve, siblings, poisoned = club_resolver(con)

    rows: list[tuple[int, int, str]] = []          # (staff_uid, team_id, job)
    unmatched: Counter[tuple[str, str]] = Counter()  # (club, reason) -> staff count
    managers: dict[int, list[int]] = defaultdict(list)  # fm_club_id -> [uid]
    with_club = 0
    for uid, f in staff.items():
        club = f.get("Club")
        if not club:
            continue
        with_club += 1
        job = f.get("Club Job") or f.get("Job") or "?"
        if job in ("-", "?"):
            job = f.get("Job", "?")
        fm_id, team_id, reason = resolve(club)
        if team_id is None:
            unmatched[(club, reason)] += 1
            continue
        rows.append((uid, team_id, job))
        if job in MANAGER_JOBS:
            managers[fm_id].append(uid)

    # one manager per club for the coaches-name write: best tactical attrs, then lower uid.
    # The coach row may hang off any spine sibling of the fm club, so walk them all.
    tact: dict[int, int] = defaultdict(int)
    q = """SELECT uid, SUM(value) FROM fm_staff_attributes
           WHERE attr IN ('tactical_knowledge','man_management','motivating') GROUP BY uid"""
    for uid, s in con.execute(q):
        tact[uid] = s or 0
    coach_teams = {t for (t,) in con.execute("SELECT team_id FROM coaches")}
    reachable = {t for sibs in siblings.values() for t in sibs if t in coach_teams}
    coach_updates: list[tuple[str, str | None, int]] = []
    for fm_id, uids in managers.items():
        best = max(uids, key=lambda u: (tact[u], -u))
        f = staff[best]
        for team_id in siblings[fm_id]:
            if team_id in coach_teams:
                coach_updates.append((f.get("Name", f"Staff {best}"), f.get("Nat"), team_id))

    # ---- report ----
    placed_teams = {t for _, t, _ in rows}
    print(f"staff in fm_raw_staff : {len(staff):,}")
    print(f"  with a club         : {with_club:,}")
    print(f"  placed              : {len(rows):,}  (at {len(placed_teams):,} teams)")
    print(f"  unplaced            : {sum(unmatched.values()):,}")
    for reason in ("no fm_clubs name", "no spine link", "ambiguous"):
        n = sum(c for (_, r), c in unmatched.items() if r == reason)
        print(f"      {reason:<17}: {n:,}")

    print("\ncounts by job (top 20):")
    for job, n in Counter(j for _, _, j in rows).most_common(20):
        print(f"  {job:<35} {n:,}")

    print("\ntop unmatched clubs (staff lost):")
    for (club, reason), n in unmatched.most_common(15):
        print(f"  {club:<28} {n:>3}  [{reason}]")

    if poisoned:
        names = ", ".join(sorted({n for _, n in poisoned}))
        print(f"\nrejected {len(poisoned)} poisoned fuzzy spine rows (national teams "
              f"mis-linked to clubs): {names}")

    print(f"\ncoaches to rename     : {len(coach_updates):,} of {len(coach_teams):,} coach rows "
          f"({len(reachable):,} reachable through the spine — the other "
          f"{len(coach_teams) - len(reachable):,} coach teams have no fm_club_id; "
          f"a build_identity coverage gap, not bridged by name here)")
    for name, nat, team_id in coach_updates[:5]:
        old = con.execute("SELECT name FROM coaches WHERE team_id=?", (team_id,)).fetchone()[0]
        print(f"  team {team_id}: '{old}' -> '{name}' ({nat})")

    if not apply:
        print("\ndry run — nothing written. Use --apply to write.")
        return 0

    # ---- write ----
    shutil.copy2(DB, str(DB) + ".bak-prestaff")
    con.execute("CREATE TABLE IF NOT EXISTS staff_assignments("
                "staff_uid INTEGER PRIMARY KEY, "
                "team_id INTEGER NOT NULL REFERENCES teams(id), "
                "job TEXT NOT NULL)")
    con.execute("BEGIN")
    con.execute("DELETE FROM staff_assignments")
    con.executemany("INSERT INTO staff_assignments(staff_uid, team_id, job) VALUES(?,?,?)", rows)
    con.executemany("UPDATE coaches SET name=?, nationality=? WHERE team_id=?", coach_updates)
    con.commit()
    print(f"\napplied: {len(rows):,} assignments, {len(coach_updates):,} coach names. "
          f"Backup: master.db.bak-prestaff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
