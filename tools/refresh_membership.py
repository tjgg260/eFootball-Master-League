#!/usr/bin/env python3
"""
refresh_membership.py — the FM membership REFRESH pipeline (blueprint hard rule 1: FM is the
truth for WHERE players play, refreshable). Takes a NEW FM export, diffs it against current
squad_members, and (only with --apply) executes the moves as recorded transfers.

This is the keyed successor to fm_assign_squads.py's one-shot rebuild: every join goes through
the identity spine — never fuzzy name matching.

    uid  -> player_identity.fm_uid -> player_id            (exact)
    club -> fm_clubs.name -> uid -> team_identity.fm_club_id -> team_id   (exact)

INPUT: an FM export (HTML from Print->Web Page, or a semicolon CSV, e.g. Genie allplayers.csv)
carrying at least  Unique ID (or UID) + Club.  Same formats fm_assign_squads.py parses.

    python tools/refresh_membership.py <export.html|.csv>          # --dry is the default
    python tools/refresh_membership.py <export.html|.csv> --apply  # backup, move, record

Rules baked in:
- Clubs that don't exact-match fm_clubs, or match an fm club with no team in our DB, are LISTED
  and their players stay put. Ambiguous club names (several fm clubs, several DB teams) likewise.
- Duplicate spine keys are resolved deterministically, never by name:
  * one fm_uid on several player rows (undeduped cross-source copies): if ANY copy already sits
    at the FM club, that's agreement — no move. Otherwise the copy moved is picked by kind
    priority ef > rfs > fm > curated (then confidence, then id). generated and career copies
    are never moved.
  * one fm_club_id on several team rows: the row with the larger current squad is canonical
    (tie: lower id). "Already at the FM club" is judged at fm_club_id level, so players are
    never ping-ponged between duplicate team rows of the same club.
- Never touches career teams (800000-899999), career players (20M-700M) or generated players
  (>= 50B). Membership rows are only ever moved, never deleted outright: a player FM lists
  without a club, or at a club we don't have, keeps his current squad.
- --apply: backs the DB up first, deletes the old membership, inserts at the end slot of the
  new team (old shirt number if free, else lowest free), renumbers slots of every affected
  team contiguously, and records each move in transfers(window='fm-refresh').
"""
from __future__ import annotations

import html
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

CAREER_TEAM = range(800_000, 900_000)          # never touch
CAREER_PID = range(20_000_000, 700_000_000)    # ephemeral render copies — never touch
GENERATED_PID = 50_000_000_000                 # >= this: filler players — never touch
KIND_PRIORITY = {"ef": 0, "rfs": 1, "fm": 2, "curated": 3}   # movable kinds, best first


def rows_of(path: Path):
    """Yield dict rows from an FM HTML table or a semicolon CSV (fm_assign_squads.py's parser)."""
    if path.suffix.lower() in (".html", ".htm"):
        text = path.read_bytes().decode("utf-8", "replace")
        body = re.split(r"<table[^>]*>", text, maxsplit=1)[-1]
        header = None
        for tr in re.split(r"<tr[^>]*>", body):
            cells = [html.unescape(re.sub(r"<.*?>", "", c)).strip()
                     for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            if not cells:
                continue
            if header is None:
                header = cells
            else:
                yield dict(zip(header, cells))
    else:
        import csv
        import io
        text = path.read_bytes().decode("cp1252", "replace")
        yield from csv.DictReader(io.StringIO(text), delimiter=";")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if not args:
        sys.exit("usage: python tools/refresh_membership.py <fm_export.html|.csv> [--dry|--apply]")
    src = Path(args[0])
    if not src.exists():
        sys.exit(f"no such file: {src}")
    con = sqlite3.connect(DB if apply else f"file:{DB.as_posix()}?mode=ro", uri=not apply)

    # ---- identity spine: fm_uid -> player rows (all copies; movability decided later) ------
    uid_rows: dict[int, list[tuple[int, str, float]]] = defaultdict(list)
    for pid, kind, uid, conf in con.execute(
            "SELECT pi.player_id, pi.kind, pi.fm_uid, pi.confidence FROM player_identity pi "
            "JOIN players p ON p.id = pi.player_id "
            "WHERE pi.fm_uid IS NOT NULL AND p.superseded_by IS NULL"):
        uid_rows[uid].append((pid, kind, conf))

    # ---- current membership ----------------------------------------------------------------
    member: dict[int, tuple[int, int, int, int]] = {}   # pid -> (team, slot, number, role)
    squad_size = Counter()
    for tid, pid, num, slot, role in con.execute(
            "SELECT team_id, player_id, squad_number, slot, role FROM squad_members"):
        member[pid] = (tid, slot, num, role)
        squad_size[tid] += 1

    # ---- identity spine: fm_club_id <-> team ----------------------------------------------
    club_teams: dict[int, list[int]] = defaultdict(list)
    team_club: dict[int, int] = {}
    for tid, fmc in con.execute(
            "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"):
        if tid in CAREER_TEAM:
            continue
        club_teams[fmc].append(tid)
        team_club[tid] = fmc

    def canonical_team(fmc: int) -> int | None:
        tids = club_teams.get(fmc)
        if not tids:
            return None
        return min(tids, key=lambda t: (-squad_size[t], t))   # larger squad wins, tie lower id

    # ---- fm_clubs: exact name -> uid(s) (plus a casefold fallback; never token-fuzzy) ------
    name_uids: dict[str, list[int]] = defaultdict(list)
    fold_uids: dict[str, list[int]] = defaultdict(list)
    for uid, nm in con.execute("SELECT uid, name FROM fm_clubs WHERE name IS NOT NULL"):
        name_uids[nm].append(uid)
        fold_uids[nm.strip().casefold()].append(uid)

    club_cache: dict[str, tuple[str, int | None]] = {}   # name -> (status, fm_club_id|None)

    def resolve_club(name: str) -> tuple[str, int | None]:
        """-> ('ok', fm_club_id) | ('no-fm-club'|'no-db-team'|'ambiguous', None)."""
        if name in club_cache:
            return club_cache[name]
        uids = name_uids.get(name) or fold_uids.get(name.strip().casefold()) or []
        # of the fm clubs bearing this name, keep those that resolve to a team we have
        have = {u for u in uids if club_teams.get(u)}
        if not uids:
            res = ("no-fm-club", None)
        elif not have:
            res = ("no-db-team", None)
        elif len(have) == 1:
            res = ("ok", have.pop())
        else:
            res = ("ambiguous", None)
        club_cache[name] = res
        return res

    # ---- read the export and plan ----------------------------------------------------------
    ucol = ccol = None
    moves: list[tuple[int, int | None, int]] = []       # (player_id, from_team|None, to_team)
    planned_pids: set[int] = set()
    n_rows = n_usable = n_agree = n_uid_missing = n_protected_only = 0
    n_dupe_pick = n_export_dupe = 0
    club_status_players = Counter()                     # status -> players affected
    club_lists: dict[str, Counter] = defaultdict(Counter)   # status -> club name -> players
    seen_uids: set[int] = set()

    for r in rows_of(src):
        n_rows += 1
        if ucol is None:
            ucol = "Unique ID" if "Unique ID" in r else "UID" if "UID" in r else None
            ccol = "Club" if "Club" in r else None
            if not ucol or not ccol:
                sys.exit(f"export needs a UID and a Club column; got {list(r)[:8]}")
        uid_s = (r.get(ucol) or "").strip()
        club = (r.get(ccol) or "").strip()
        if not uid_s.isdigit() or not club or club == "-":
            continue
        n_usable += 1
        uid = int(uid_s)
        if uid in seen_uids:
            n_export_dupe += 1
            continue
        seen_uids.add(uid)

        copies = uid_rows.get(uid)
        if not copies:
            n_uid_missing += 1
            continue
        status, fmc = resolve_club(club)
        if status != "ok":
            club_status_players[status] += 1
            club_lists[status][club] += 1
            continue
        # agreement is judged at fm_club_id level across ALL copies (incl. generated/career)
        if any(team_club.get(member[pid][0]) == fmc
               for pid, _, _ in copies if pid in member):
            n_agree += 1
            continue
        movable = [(pid, kind, conf) for pid, kind, conf in copies
                   if kind in KIND_PRIORITY and pid not in CAREER_PID and pid < GENERATED_PID]
        movable = [(pid, kind, conf) for pid, kind, conf in movable
                   if member.get(pid, (0,))[0] not in CAREER_TEAM]
        if not movable:
            n_protected_only += 1
            continue
        if len(movable) > 1:
            n_dupe_pick += 1
        pid = min(movable, key=lambda c: (KIND_PRIORITY[c[1]], -c[2], c[0]))[0]
        to_team = canonical_team(fmc)
        from_team = member[pid][0] if pid in member else None
        if to_team is None or to_team == from_team or pid in planned_pids:
            continue
        planned_pids.add(pid)
        moves.append((pid, from_team, to_team))

    # ---- report ----------------------------------------------------------------------------
    tname = dict(con.execute("SELECT id, name FROM teams"))
    pname = dict(con.execute(
        "SELECT id, name FROM players WHERE id IN (SELECT player_id FROM squad_members) "
        "OR id IN (SELECT player_id FROM player_identity WHERE fm_uid IS NOT NULL)"))
    transfers = [m for m in moves if m[1] is not None]
    placements = [m for m in moves if m[1] is None]
    affected = {t for _, f, t in moves} | {f for _, f, _ in moves if f is not None}

    print(f"export rows: {n_rows:,} | usable uid+club rows: {n_usable:,} "
          f"(dupe uid rows skipped: {n_export_dupe:,})")
    print(f"uid not in spine: {n_uid_missing:,} | only protected copies (stay put): "
          f"{n_protected_only:,}")
    for status, label in (("no-fm-club", "club name not in fm_clubs"),
                          ("no-db-team", "fm club with no DB team (stay put)"),
                          ("ambiguous", "ambiguous club name (skipped)")):
        cl = club_lists.get(status)
        if cl:
            print(f"{label}: {len(cl):,} clubs / {club_status_players[status]:,} players")
            print("   top:", dict(cl.most_common(8)))
    print(f"already at their FM club: {n_agree:,}")
    print(f"planned moves: {len(moves):,} (transfers: {len(transfers):,}, "
          f"placements of unattached players: {len(placements):,}) "
          f"across {len(affected):,} teams")
    if n_dupe_pick:
        print(f"duplicate-uid players resolved by kind priority: {n_dupe_pick:,}")
    for pid, f, t in sorted(moves, key=lambda m: (m[2], m[0]))[:20]:
        fn = "(unattached)" if f is None else str(tname.get(f, f))
        print(f"   {str(pname.get(pid, pid)):28.28} {fn:>28.28} -> {tname.get(t, t)}")

    if not apply:
        print("--dry: nothing written. Run with --apply to execute.")
        return 0
    if not moves:
        print("nothing to apply.")
        return 0

    # ---- apply -----------------------------------------------------------------------------
    backup = str(DB) + time.strftime(".bak-refresh-%Y%m%d-%H%M%S")
    shutil.copy2(DB, backup)
    print(f"backup: {backup}")

    season = con.execute("SELECT id FROM seasons WHERE is_current=1").fetchone()
    season_id = season[0] if season else None
    next_slot: dict[int, int] = {}
    used_nums: dict[int, set[int]] = {}
    for tid in {t for _, _, t in moves}:
        row = con.execute("SELECT COALESCE(MAX(slot)+1,0) FROM squad_members WHERE team_id=?",
                          (tid,)).fetchone()
        next_slot[tid] = row[0]
        used_nums[tid] = {n for (n,) in con.execute(
            "SELECT squad_number FROM squad_members WHERE team_id=?", (tid,))}

    con.execute("BEGIN")
    for pid, from_team, to_team in sorted(moves, key=lambda m: (m[2], m[0])):
        old = member.get(pid)
        if old is not None:
            con.execute("DELETE FROM squad_members WHERE team_id=? AND player_id=?",
                        (old[0], pid))
        want = old[2] if old else None
        nums = used_nums[to_team]
        num = want if want and want not in nums else \
            next(n for n in range(1, 1000) if n not in nums)
        nums.add(num)
        con.execute("INSERT INTO squad_members(team_id,player_id,squad_number,slot,role) "
                    "VALUES(?,?,?,?,0)", (to_team, pid, num, next_slot[to_team]))
        next_slot[to_team] += 1
        con.execute("INSERT INTO transfers(player_id,from_team_id,to_team_id,fee,window,"
                    "season_id) VALUES(?,?,?,0,'fm-refresh',?)",
                    (pid, from_team, to_team, season_id))
    for tid in affected:   # renumber slots contiguously, preserving order
        rows = con.execute("SELECT player_id FROM squad_members WHERE team_id=? "
                           "ORDER BY slot", (tid,)).fetchall()
        con.executemany("UPDATE squad_members SET slot=? WHERE team_id=? AND player_id=?",
                        [(i, tid, pid) for i, (pid,) in enumerate(rows)])
    con.commit()
    print(f"applied {len(moves):,} moves ({len(transfers):,} transfers, "
          f"{len(placements):,} placements); {len(affected):,} teams renumbered; "
          f"transfers logged window='fm-refresh'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
