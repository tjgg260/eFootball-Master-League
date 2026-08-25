#!/usr/bin/env python3
"""
fix_fullback_shortage.py — 'D RC' means he plays right back OR centre back, and we kept only the C.

fix_positions_from_fm reads FM's grammar properly but has to choose ONE eFootball position, and
when a defender is listed for the centre as well as a flank ('D RC', 'D LC') it takes the centre.
That is the safe default for a player who already has a club full of full-backs, and it is why 271
catalog XIs still line up without one: Qingdao Hainiu carry seven centre-backs, three left backs
and no right back at all.

So ask the shortage, not the default. For a club whose eleven is missing a flank, look through the
squad for someone FM actually lists on that flank — including the centre-backs whose second role
we dropped — and give him the position his own FM row grants him. Nothing is invented: a player is
only moved to right back if FM says he plays right back.

Two guards. The club must keep two centre-backs, so a side with a thin middle is not stripped to
fix its width. And the best available is chosen by rating, so the club gets its actual full-back
rather than the first row returned.

    python tools/fix_fullback_shortage.py --dry
    python tools/fix_fullback_shortage.py
then: rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
MEMBER = REPO / "allavailable columns players.csv"
MOVABLE = ("CB", "DMF", "CMF", "LMF", "RMF")
MIN_CB = 2


def flanks(fm: str) -> set[str]:
    """Every flank FM lists for this player's defensive roles — the centre does not cancel them."""
    out: set[str] = set()
    for part in (fm or "").upper().split(","):
        m = re.match(r"\s*([A-Z/]+)\s*([RLC]+)?\s*$", part)
        if not m:
            continue
        roles, fl = m.group(1).split("/"), (m.group(2) or "")
        if "D" in roles or "WB" in roles:
            if "L" in fl:
                out.add("LB")
            if "R" in fl:
                out.add("RB")
            if "WB" in roles and not fl:
                out |= {"LB", "RB"}
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    incat = [t["team_id"] for co in cat["countries"] for lg in co["leagues"] for t in lg["teams"]]
    tname = dict(con.execute("SELECT id, name FROM teams"))

    fmpos = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            if u.isdigit():
                fmpos[int(u)] = (r.get("Position") or "").strip()
    uid = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))

    moves = []
    for tid in incat:
        xi = [r[0] for r in con.execute(
            "SELECT p.position FROM squad_members s JOIN players p ON p.id=s.player_id "
            "WHERE s.team_id=? AND s.slot<=10", (tid,))]
        if len(xi) < 11:
            continue
        need = [p for p in ("LB", "RB") if p not in xi]
        if not need:
            continue
        squad = list(con.execute(
            "SELECT p.id, p.name, p.position, COALESCE(p.overall_rating,0) FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE s.team_id=? ORDER BY p.overall_rating DESC",
            (tid,)))
        cbs = sum(1 for _p, _n, pos, _r in squad if pos == "CB")
        taken = set()
        for want in need:
            for pid, name, pos, _rat in squad:
                if pid in taken or pos not in MOVABLE:
                    continue
                if want not in flanks(fmpos.get(uid.get(pid), "")):
                    continue
                if pos == "CB" and cbs - 1 < MIN_CB:
                    continue
                if pos == "CB":
                    cbs -= 1
                taken.add(pid)
                moves.append((want, pid, tid, name, pos))
                break

    clubs = {m[2] for m in moves}
    print(f"clubs given a full-back FM already listed there: {len(clubs)} "
          f"({len(moves)} players)")
    for want, _pid, tid, name, pos in moves[:8]:
        print(f"   {tname.get(tid)[:26]:26} {name[:22]:22} {pos} -> {want}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not moves:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prefullback")
    con.executemany("UPDATE players SET position=? WHERE id=?",
                    [(w, p) for w, p, _t, _n, _o in moves])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(moves)} players moved onto the flank FM gives them.")
    print("next: rerank_slots.py, then refresh_roles_for_position.py + assign_roles.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
