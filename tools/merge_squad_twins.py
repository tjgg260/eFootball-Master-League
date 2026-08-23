#!/usr/bin/env python3
"""
merge_squad_twins.py — merge cross-source DUPLICATE PEOPLE who are both IN squads.

dedup_players.py reaps orphan twins; this handles the worse case the P7 audit surfaced: the same
human twice in ONE squad ("Xavi Simons" eF-native 137000 + "Simons" RFS 700245367, both at
Tottenham). Sources spell names differently (RFS uses surnames) and nationalities differently
(Holland/Netherlands), which is why earlier passes missed them.

A pair of same-team members is a TWIN when:
  - one name's token set is a subset of the other's (simons ⊂ xavi simons), tokens nonempty
  - ages equal (or one unknown)
  - nationalities equal under the alias map, or one unknown
  - AND the two ids come from DIFFERENT source bands (eF <16.7M · RFS 700M-10B · FM 10B+ ·
    curated 45-46B · generated >=50B) — two brothers imported from ONE source stay untouched.
    Exception: the career band (20M-700M) mirrors canonical dupes pair-internally; those pairs
    are allowed same-band and resolved by fuller-name.

Survivor: the eFootball-native record (standing rule: eF is attribute authority for real
players), else curated, else RFS (real portraits), else FM. Career-band pairs: fuller name.
The loser: unsquadded everywhere, references repointed (transfers, match_events, academy),
then the player row + satellites removed — exactly dedup_players.py's cleanup list.
Anything not meeting every test lands in build/twin_review.csv, untouched.

    python tools/merge_squad_twins.py --dry
    python tools/merge_squad_twins.py
    python tools/merge_squad_twins.py --db careers/<name>.db   # career-side sync (same rules)
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
if "--db" in sys.argv:
    DB = REPO / sys.argv[sys.argv.index("--db") + 1]

PID_TABLES = [
    "player_attributes", "player_market", "player_playstyles", "player_appearance",
    "player_appearance_raw", "player_traits", "player_skills", "player_potential",
    "player_positions", "player_condition", "player_knowledge", "player_status",
]
REPOINT = [("transfers", "player_id"), ("match_events", "player_id"), ("academy", "player_id"),
           ("contracts", "player_id")]

NAT_ALIAS = {
    "holland": "netherlands", "n.ireland": "northern ireland", "nireland": "northern ireland",
    "usa": "united states", "u.s.a.": "united states", "ivory coast": "cote divoire",
    "cote d'ivoire": "cote divoire", "korea republic": "south korea", "china pr": "china",
    "cape verde islands": "cape verde", "bosnia-herzegovina": "bosnia", "czechia": "czech republic",
    "republic of ireland": "ireland", "eire": "ireland",
}


def band(pid: int) -> str:
    if pid < 16_700_000: return "ef"
    if pid < 700_000_000: return "career"
    if pid < 10_000_000_000: return "rfs"
    if 45_000_000_000 <= pid < 47_000_000_000: return "curated"
    if pid >= 50_000_000_000: return "generated"
    return "fm"


BAND_RANK = {"ef": 0, "curated": 1, "rfs": 2, "fm": 3, "generated": 4, "career": 5}


def toks(name: str) -> frozenset:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return frozenset(t for t in re.sub(r"[^a-z ]", " ", n).split() if t)


def nat(s: str | None) -> str:
    n = (s or "").split("/")[0].strip().lower()
    return NAT_ALIAS.get(n, n)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)

    has_appearance = {r[0] for r in con.execute("SELECT DISTINCT player_id FROM player_appearance")}
    squads = defaultdict(list)
    for tid, pid, nm, natl, age in con.execute(
            "SELECT s.team_id, p.id, p.name, p.nationality, p.age "
            "FROM squad_members s JOIN players p ON p.id=s.player_id"):
        squads[tid].append((pid, nm, nat(natl), age))

    def survivor(a, b):
        """Pick (winner, loser) or None if the pair can't be auto-resolved."""
        ba, bb = band(a[0]), band(b[0])
        if ba == bb == "career":
            # mirror of a canonical dupe: fuller name wins, tie -> lower id
            ka = (-len(toks(a[1])), a[0])
            kb = (-len(toks(b[1])), b[0])
            return (a, b) if ka <= kb else (b, a)
        if ba == bb:
            return None                                   # same source: could be brothers
        return (a, b) if BAND_RANK[ba] < BAND_RANK[bb] else (b, a)

    auto, review = [], []
    for tid, members in squads.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                ta, tb = toks(a[1]), toks(b[1])
                if not ta or not tb or not (ta <= tb or tb <= ta) or ta == tb == frozenset():
                    continue
                same_age = a[3] == b[3] and a[3] is not None
                one_age = a[3] is None or b[3] is None
                same_nat = a[2] and a[2] == b[2]
                one_nat = not a[2] or not b[2]
                if not (same_age or one_age):
                    continue
                if not (same_nat or one_nat):
                    continue
                pick = survivor(a, b)
                strong = same_age and same_nat
                if pick and (strong or (same_age and one_nat) or (same_nat and one_age)):
                    auto.append((tid, pick[0], pick[1]))
                else:
                    review.append((tid, a, b))

    print(f"auto-merge pairs: {len(auto)}  |  review pairs: {len(review)}")
    with open(REPO / "build" / "twin_review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team_id", "pid_a", "name_a", "pid_b", "name_b", "why"])
        for tid, a, b in review:
            w.writerow([tid, a[0], a[1], b[0], b[1], "same band or weak evidence"])
    print(f"review CSV: build/twin_review.csv ({len(review)} rows)")

    # A loser might appear in several teams' pairs (canonical + career mirrors of the same
    # human). Collapse to one winner per loser id; refuse conflicting winners.
    merges = {}
    for tid, win, lose in auto:
        if lose[0] in merges and merges[lose[0]] != win[0]:
            print(f"  ! conflicting winners for {lose[0]} — sent to review")
            review.append((tid, win, lose))
            continue
        merges[lose[0]] = win[0]
    # never let a winner also be a loser (chain) — drop those from auto
    chained = [l for l in merges if l in set(merges.values())]
    for l in chained:
        print(f"  ! {l} is both winner and loser — sent to review")
        del merges[l]
    print(f"final merge count: {len(merges)} losers removed in favour of their twins")

    if dry:
        for l, w_ in list(merges.items())[:15]:
            ln = con.execute("SELECT name FROM players WHERE id=?", (l,)).fetchone()
            wn = con.execute("SELECT name FROM players WHERE id=?", (w_,)).fetchone()
            print(f"  {l} '{ln[0] if ln else '?'}'  ->  {w_} '{wn[0] if wn else '?'}'")
        print("--dry: nothing written.")
        return 0

    cur = con.cursor()
    for lose, win in merges.items():
        cur.execute("DELETE FROM squad_members WHERE player_id=?", (lose,))
        for tbl, col in REPOINT:
            try:
                cur.execute(f"UPDATE {tbl} SET {col}=? WHERE {col}=?", (win, lose))
            except sqlite3.OperationalError:
                pass
        for tbl in PID_TABLES:
            try:
                cur.execute(f"DELETE FROM {tbl} WHERE player_id=?", (lose,))
            except sqlite3.OperationalError:
                pass
        # Identity spine: the loser's row carries source links (fm_uid/ef_pid) the winner may
        # lack — repoint it onto the winner unless the winner already has a spine row.
        try:
            has_win = cur.execute("SELECT 1 FROM player_identity WHERE player_id=?", (win,)).fetchone()
            if has_win:
                cur.execute("DELETE FROM player_identity WHERE player_id=?", (lose,))
            else:
                cur.execute("UPDATE player_identity SET player_id=? WHERE player_id=?", (win, lose))
        except sqlite3.OperationalError:
            pass
        cur.execute("DELETE FROM players WHERE id=?", (lose,))
    con.commit()
    print(f"merged {len(merges)} twins. Run tools/dedup_players.py next, then tools/validate_db.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
