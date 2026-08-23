#!/usr/bin/env python3
"""
sync_membership_fm.py — club membership from the FM export, THE source of truth (owner ruling
2026-08-23: the CSV is FM24 maintained by humans with the real 2026 windows — not a played save).

For every SENIOR FM row (the Squad column marks U21/U18 rows, whose Club ID is the parent club —
youth rows never drive senior membership), place the spine-linked player at his real club.
eFootball remains attribute authority — this moves memberships only.

Hard-learned rules (first apply broke the gate; every one of these exists for a reason):
  - SENIOR FM rows only (Squad empty) — youth rows would promote whole academies
  - only players currently in a CANONICAL squad move; career bands (800k) are never touched and
    career-only players are never placed into the world (double-membership)
  - a uid with several squad claimants = the same human as cross-club ghosts: the claimant at
    the FM club (or best source band) keeps his place, the others are UNSQUADDED
  - an unsquadded player may be placed only with >= 20 attribute rows (compilable)
  - catalog clubs (catalog.json) never drop below 18 players / 2 GKs — excess exits are blocked

    python tools/sync_membership_fm.py --dry
    python tools/sync_membership_fm.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
import sqlite3

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CSV = REPO / "allavailable columns players.csv"
FLOOR, GK_FLOOR = 18, 2


def band_rank(pid: int) -> int:
    if pid < 16_700_000: return 0                       # eF-native
    if 45_000_000_000 <= pid < 47_000_000_000: return 1  # curated
    if 700_000_000 <= pid < 10_000_000_000: return 2     # RFS
    if pid >= 50_000_000_000: return 4                   # generated
    return 3                                             # FM


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)

    # FM SENIOR rows: uid -> club id
    fm_club = {}
    youth_rows = 0
    with open(CSV, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            if not u.lstrip("-").isdigit():
                continue
            squad = (r.get("Squad") or "").strip().strip('"')
            # Squad is the club's display name; YOUTH squads carry a U15..U23 suffix
            # ("Sporting CP U19") — those rows' Club ID is the parent and must not drive
            # senior membership.
            import re as _re
            if _re.search(r"U\s?-?(1[5-9]|2[0-3])", squad, _re.IGNORECASE):
                youth_rows += 1
                continue
            c = (r.get("Club ID") or "").strip()
            fm_club[int(u)] = int(c) if c.lstrip("-").isdigit() else 0
    print(f"FM senior rows: {len(fm_club):,} (skipped {youth_rows:,} youth rows)")

    team_of_fmclub, fmclub_of_team = {}, {}
    for tid, fmcid in con.execute(
            "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"):
        if not (800_000 <= tid < 1_000_000):
            team_of_fmclub.setdefault(fmcid, tid)
            fmclub_of_team[tid] = fmcid

    uid_of = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    for (pid,) in con.execute(
            "SELECT id FROM players WHERE id >= 10000000000 AND id < 45000000000"):
        uid_of.setdefault(pid, pid - 10_000_000_000)

    cur_team, squad_size = {}, defaultdict(int)
    for pid, tid in con.execute("SELECT player_id, team_id FROM squad_members"):
        if not (800_000 <= tid < 1_000_000):
            cur_team[pid] = tid
            squad_size[tid] += 1

    attr_ok = {r[0] for r in con.execute(
        "SELECT player_id FROM player_attributes GROUP BY player_id HAVING COUNT(*) >= 20")}
    gk_count, gk_pid = defaultdict(int), set()
    for pid, tid in con.execute(
            "SELECT s.player_id, s.team_id FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE p.position='GK'"):
        if not (800_000 <= tid < 1_000_000):
            gk_count[tid] += 1
        gk_pid.add(pid)

    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    catalog_teams = {t["team_id"] for co in cat["countries"]
                     for lg in co["leagues"] for t in lg["teams"]}

    def exit_ok(tid, pid):
        """May this player leave this club without breaking the catalog floor?"""
        if tid is None or tid not in catalog_teams:
            return True
        if squad_size[tid] <= FLOOR:
            return False
        if pid in gk_pid and gk_count[tid] <= GK_FLOOR:
            return False
        return True

    def do_exit(tid, pid):
        squad_size[tid] -= 1
        if pid in gk_pid:
            gk_count[tid] -= 1

    def do_enter(tid, pid):
        squad_size[tid] += 1
        if pid in gk_pid:
            gk_count[tid] += 1

    # uid -> squad claimants (canonical only)
    claimants = defaultdict(list)
    for pid, uid in uid_of.items():
        if pid in cur_team:
            claimants[uid].append(pid)

    moves, frees, ghosts = [], [], []
    blocked = 0
    for uid, club in fm_club.items():
        ps = claimants.get(uid, [])
        want = team_of_fmclub.get(club) if club > 0 else None

        if not ps:
            # nobody in a squad wears this uid; an unsquadded spine twin may be placed
            if want is None:
                continue
            fp = [p for p, u in uid_of.items() if u == uid and p not in cur_team]
            fp = [p for p in fp if p in attr_ok]
            if fp:
                p = min(fp, key=band_rank)
                moves.append((p, None, want))
                do_enter(want, p)
            continue

        # keeper: the claimant already at the right club, else best band
        keeper = next((p for p in ps if cur_team[p] == want), None) \
            or (min(ps, key=band_rank) if want is not None or club <= 0 else None)
        if keeper is None:
            continue

        # ghosts: every other claimant of this human leaves his squad
        for p in ps:
            if p == keeper:
                continue
            t = cur_team[p]
            if exit_ok(t, p):
                ghosts.append((p, t))
                do_exit(t, p)
            else:
                blocked += 1

        if club <= 0:
            t = cur_team[keeper]
            if exit_ok(t, keeper):
                frees.append((keeper, t))
                do_exit(t, keeper)
            else:
                blocked += 1
        elif want is not None and cur_team[keeper] != want \
                and fmclub_of_team.get(cur_team[keeper]) != club:
            t = cur_team[keeper]
            if exit_ok(t, keeper):
                moves.append((keeper, t, want))
                do_exit(t, keeper)
                do_enter(want, keeper)
            else:
                blocked += 1

    print(f"moves: {len(moves):,} | to free agency: {len(frees):,} | "
          f"cross-club ghosts unsquadded: {len(ghosts):,} | blocked by floors: {blocked:,}")

    def name(pid):
        r = con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()
        return r[0] if r else "?"

    def tname(tid):
        if tid is None:
            return "free agency"
        r = con.execute("SELECT name FROM teams WHERE id=?", (tid,)).fetchone()
        return r[0] if r else str(tid)

    for pid, now, want in moves[:12]:
        print(f"  MOVE  {name(pid)}: {tname(now)} -> {tname(want)}")
    for pid, t in ghosts[:6]:
        print(f"  GHOST {name(pid)} unsquadded from {tname(t)}")
    if dry:
        print("--dry: nothing written.")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-presync")
    cur = con.cursor()
    for pid, now, want in moves:
        if now is not None:
            cur.execute("DELETE FROM squad_members WHERE player_id=? AND team_id=?", (pid, now))
        nums = {r[0] for r in cur.execute(
            "SELECT squad_number FROM squad_members WHERE team_id=?", (want,))}
        num = next(n for n in range(1, 200) if n not in nums)
        slot = cur.execute("SELECT COALESCE(MAX(slot),10)+1 FROM squad_members WHERE team_id=?",
                           (want,)).fetchone()[0]
        cur.execute("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot,role) "
                    "VALUES(?,?,?,?,0)", (want, pid, num, slot))
    for pid, t in frees + ghosts:
        cur.execute("DELETE FROM squad_members WHERE player_id=? AND team_id=?", (pid, t))
    con.commit()
    print("applied. Run tools/validate_db.py next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
