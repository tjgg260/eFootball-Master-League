#!/usr/bin/env python3
"""
fix_positions_from_fm.py — read FM's position grammar properly instead of guessing from a prefix.

tools/fm_import.py's ef_pos() exact-matches the FM position string and otherwise falls back to
`first.startswith(k.split()[0])`. 'D/WB L' therefore starts with 'D', matches the centre-back
entry and loses the L entirely: full-backs and wing-backs became centre-halves in bulk, which is
why hundreds of clubs field a back four with no full-back on either side while natural full-backs
sit on the bench, and why some left-sided players line up on the right.

FM writes ROLE plus flank letters: 'D C', 'D R', 'D/WB L', 'AM RL', 'M C', 'DM', 'ST', 'GK', and
several roles separated by commas ('D C, DM' — the first is the primary). Read the flank FIRST,
then the role, and only then choose the single eFootball position.

eFootball's own players keep Konami's position: the export is the authority for anyone in it.

    python tools/fix_positions_from_fm.py --dry
    python tools/fix_positions_from_fm.py
then: rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
MEMBER = REPO / "allavailable columns players.csv"
EFCSV = REPO / "samples" / "editor-bundled-players.csv"


def ef_positions(fm: str):
    """Return (preferred, acceptable set). 'AM RL' admits BOTH wings, so a player already stored
    as a left winger must stay one — flipping him to the right would be a fresh error, not a fix."""
    first = (fm or "").split(",")[0].strip().upper()
    if not first:
        return None, set()
    if first.startswith("GK"):
        return "GK", {"GK"}
    m = re.match(r"([A-Z/]+)\s*([RLC]+)?$", first)
    if not m:
        return None, set()
    role, flank = m.group(1), (m.group(2) or "")
    roles = role.split("/")
    has = lambda x: x in roles                                   # noqa: E731
    left, right, centre = "L" in flank, "R" in flank, "C" in flank
    ok = set()
    if has("WB") or (has("D") and (left or right) and not centre):
        if left:
            ok.add("LB")
        if right:
            ok.add("RB")
        if not ok:
            ok = {"RB", "LB"}
    elif has("D"):
        ok = {"CB"}
    elif has("DM"):
        ok = {"DMF"}
    elif has("AM"):
        if centre or not (left or right):
            ok = {"AMF"}
        else:
            ok = ({"LWF"} if left else set()) | ({"RWF"} if right else set())
    elif has("M"):
        if centre or not (left or right):
            ok = {"CMF"}
        else:
            ok = ({"LMF"} if left else set()) | ({"RMF"} if right else set())
    elif has("ST") or has("F"):
        ok = {"CF"}
    if not ok:
        return None, set()
    order = ["GK", "CB", "LB", "RB", "DMF", "CMF", "AMF", "LMF", "RMF", "LWF", "RWF", "CF"]
    pref = sorted(ok, key=lambda x: order.index(x) if x in order else 99)[0]
    return pref, ok


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()

    ef_rows = list(csv.DictReader(io.StringIO(EFCSV.read_bytes().decode("utf-8-sig"))))
    export = {int(r["player_id"]) for r in ef_rows if (r.get("player_id") or "").isdigit()}
    protected = set(export)
    for pid, ep in con.execute(
            "SELECT player_id, ef_pid FROM player_identity WHERE ef_pid IS NOT NULL"):
        if ep in export:
            protected.add(pid)

    fm_pos = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            if u.isdigit():
                fm_pos[int(u)] = (r.get("Position") or "").strip()

    changes, moves = [], Counter()
    for pid, uid, cur_pos in con.execute(
            "SELECT s.player_id, pi.fm_uid, COALESCE(p.position,'') "
            "FROM squad_members s JOIN players p ON p.id=s.player_id "
            "JOIN player_identity pi ON pi.player_id=s.player_id "
            "WHERE pi.fm_uid IS NOT NULL "
            "AND NOT (s.team_id>=800000 AND s.team_id<1000000)"):
        if pid in protected:
            continue
        want, ok = ef_positions(fm_pos.get(uid, ""))
        if cur_pos in ok:
            continue                                   # already one of the positions FM allows
        if want and want != cur_pos:
            changes.append((want, pid))
            moves[(cur_pos or "?", want)] += 1

    print(f"squadded players whose FM position disagrees with ours: {len(changes):,}")
    for (a, b), n in moves.most_common(12):
        print(f"   {a:>4} -> {b:<4} {n:,}")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not changes:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-prepos")
    cur.execute("BEGIN")
    cur.executemany("UPDATE players SET position=? WHERE id=?", changes)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(changes):,} positions corrected from FM's own grammar.")
    print("next: rerank_slots.py (the back four changes), validate_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
