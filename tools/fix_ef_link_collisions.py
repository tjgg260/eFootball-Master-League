#!/usr/bin/env python3
"""
fix_ef_link_collisions.py — one eFootball record belongs to one human.

player_identity.ef_pid was populated in part by NAME matching (ef_method='name'), and a name is
not an identity: 230 eFootball records are claimed by two or more live squadded players at once.
Because eFootball is the attribute authority, every claimant inherited the same 40-99 vector, so
at most one of them can be right — and the wrong ones are badly wrong:

  Real Madrid's Álvaro Fernández (CB) carries gk_reflexes 72 and finishing 40, because his link
  points at a DIFFERENT Álvaro Fernández who keeps goal. The mirror image: Palmeiras' keeper
  'Alex' and Corinthians' keeper 'Kauê' sit at gk_reflexes 40 — the absolute representable floor —
  because their links point at a centre-forward and a midfielder.

Two rules, both mechanical:
  1  a link whose two records disagree on GK versus outfield is WRONG, whatever the names say
  2  when several live squadded players claim one eFootball record, keep at most the single best
     claimant (position family agrees, then closest age, then band priority eF > FM > RFS) and
     clear the rest

Clearing a link does not remove data: the player simply falls back to his FM ladder on the next
derivation, which is the correct source for him.

    python tools/fix_ef_link_collisions.py --dry
    python tools/fix_ef_link_collisions.py
then: fm_derive_attributes.py, rerank_slots.py, validate_db.py
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


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s):
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def band_rank(pid):
    if pid < 16_777_216:
        return 0
    if pid < 10_000_000_000:
        return 2                                   # RFS last (owner ruling)
    if pid < 45_000_000_000:
        return 1
    return 3


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    P = {pid: (nm, age, (pos or "").upper()) for pid, nm, age, pos in
         con.execute("SELECT id, name, age, position FROM players")}
    live = {pid for pid, sup in con.execute("SELECT id, superseded_by FROM players") if sup is None}
    squadded = {p for (p,) in con.execute(
        "SELECT player_id FROM squad_members WHERE NOT (team_id>=800000 AND team_id<1000000)")}

    links = [(pid, ep, m) for pid, ep, m in con.execute(
        "SELECT player_id, ef_pid, ef_method FROM player_identity WHERE ef_pid IS NOT NULL")]
    print(f"ef_pid links: {len(links):,}")

    def is_gk(pid):
        return P.get(pid, ("", None, ""))[2] == "GK"

    # ---- rule 1: GK vs outfield disagreement is always wrong
    bad_pos = [(pid, ep) for pid, ep, _m in links
               if pid != ep and pid in P and ep in P and is_gk(pid) != is_gk(ep)]
    print(f"links where one record keeps goal and the other does not: {len(bad_pos):,}")
    for pid, ep in bad_pos[:6]:
        print(f"   {P[pid][0][:22]:22} ({P[pid][2]:3}) -> eF {P[ep][0][:22]:22} ({P[ep][2]})")

    drop = {pid for pid, _ep in bad_pos}

    # ---- rule 2: one eFootball record, one claimant
    claims = defaultdict(list)
    for pid, ep, _m in links:
        if pid != ep and pid in live and pid in squadded and pid not in drop:
            claims[ep].append(pid)
    contested = {e: c for e, c in claims.items() if len(c) > 1}
    print(f"eFootball records claimed by 2+ live squadded players: {len(contested):,} "
          f"({sum(len(c) for c in contested.values()):,} claimants)")

    def score(pid, ep):
        s = 0.0
        if ep in P and pid in P:
            if is_gk(pid) == is_gk(ep):
                s += 4.0
            if toks(P[pid][0]) == toks(P[ep][0]):
                s += 2.0
            a, b = P[pid][1], P[ep][1]
            if a is not None and b is not None:
                s += max(0.0, 3.0 - abs(a - b) * 0.5)
        return s - band_rank(pid) * 0.1

    for ep, cs in contested.items():
        best = max(cs, key=lambda p: score(p, ep))
        for p in cs:
            if p != best:
                drop.add(p)
    print(f"links to clear in total: {len(drop):,}")

    if dry:
        print("--dry: nothing written.")
        return 0
    if not drop:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preeffix")
    cur.execute("BEGIN")
    cur.executemany("UPDATE player_identity SET ef_pid=NULL, ef_method=NULL WHERE player_id=?",
                    [(p,) for p in sorted(drop)])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    left = cur.execute("""SELECT COUNT(*) FROM (SELECT pi.ef_pid FROM player_identity pi
        JOIN players p ON p.id=pi.player_id JOIN squad_members s ON s.player_id=p.id
        WHERE pi.ef_pid IS NOT NULL AND p.superseded_by IS NULL
        AND NOT (s.team_id>=800000 AND s.team_id<1000000)
        GROUP BY pi.ef_pid HAVING COUNT(*)>1)""").fetchone()[0]
    print(f"applied. cleared {len(drop):,} links | contested eFootball records left: {left}")
    print("next: fm_derive_attributes.py to re-source the affected players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
