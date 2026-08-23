#!/usr/bin/env python3
"""
fill_squads.py — top up catalog clubs that don't have a playable squad. Any catalog team with fewer
than FLOOR (18) players is filled up to TARGET (20) with generated players: names drawn from real
players of the club's nationality (so a Belarusian club gets Belarusian names), a balanced position
plan that guarantees goalkeeper cover, a rating near the club's own level (filler sits just below
the first XI), and a full synthesised attribute set so they're immediately playable. Only catalog
teams (the ones a career actually uses) are filled; re-running skips clubs already at size.

    python tools/fill_squads.py --dry
    python tools/fill_squads.py
"""
from __future__ import annotations

import json
import random
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth_attributes import synth  # noqa: E402  (reuse the exact attribute synthesiser)

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"

FLOOR, TARGET = 18, 20
FAKE_BASE = 50_000_000_000          # well above every real id (max ~12B)
# balanced outfield rotation used after goalkeeper cover is guaranteed
OUTFIELD = ["CB", "CB", "LB", "RB", "DMF", "CMF", "CMF", "AMF", "CF", "LWF", "RWF", "SS",
            "CB", "CMF", "DMF", "LB", "RB", "CF"]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    rng = random.Random(20260823)          # fixed seed: a given run is reproducible
    con = sqlite3.connect(DB, timeout=60)

    catalog = json.loads(CAT.read_text(encoding="utf-8"))
    team_country, team_rating = {}, {}
    for co in catalog["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                team_country[t["team_id"]] = co["name"]
                team_rating[t["team_id"]] = t.get("rating") or 0

    # name pools by nationality: forenames + surnames from real multi-word names
    fore, sur = defaultdict(list), defaultdict(list)
    for nm, nat in con.execute("SELECT name, nationality FROM players WHERE name LIKE '% %'"):
        nat = (nat or "").split("/")[0].strip()
        if not nat:
            continue
        toks = _norm(nm).split()
        if len(toks) >= 2:
            fore[nat].append(toks[0])
            sur[nat].append(toks[-1])
    all_fore = [x for v in fore.values() for x in v]
    all_sur = [x for v in sur.values() for x in v]

    # per-team existing squad: size, positions, dominant nationality, avg overall
    squad_pos = defaultdict(list)
    squad_ovr = defaultdict(list)
    squad_nat = defaultdict(Counter)
    for tid, pos, ovr, nat in con.execute(
            "SELECT s.team_id, p.position, p.overall_rating, p.nationality FROM squad_members s "
            "JOIN players p ON p.id=s.player_id"):
        squad_pos[tid].append(pos)
        if ovr:
            squad_ovr[tid].append(ovr)
        if nat:
            squad_nat[tid][nat.split("/")[0].strip()] += 1

    def name_for(nat: str) -> str:
        f = fore.get(nat) or all_fore
        s = sur.get(nat) or all_sur
        return f"{rng.choice(f)} {rng.choice(s)}"

    def plan(existing: list[str], n: int) -> list[str]:
        out = []
        gk = existing.count("GK")
        while gk + out.count("GK") < 2 and len(out) < n:
            out.append("GK")
        i = 0
        while len(out) < n:
            out.append(OUTFIELD[i % len(OUTFIELD)])
            i += 1
        return out

    nid = (con.execute("SELECT MAX(id) FROM players WHERE id>=?", (FAKE_BASE,)).fetchone()[0]
           or FAKE_BASE) + 1
    to_fill = [(tid, len(squad_pos.get(tid, [])), TARGET - len(squad_pos.get(tid, [])))
               for tid in team_country if len(squad_pos.get(tid, [])) < FLOOR]
    # a club at full size but with fewer than TWO goalkeepers still isn't playable — top up cover
    gkless = [(tid, 2 - squad_pos[tid].count("GK")) for tid in team_country
              if len(squad_pos.get(tid, [])) >= FLOOR and squad_pos[tid].count("GK") < 2]
    to_fill += [(tid, len(squad_pos.get(tid, [])), n) for tid, n in gkless]
    total_new = sum(need for _, _, need in to_fill)
    print(f"catalog clubs to fill (<{FLOOR}): {len(to_fill) - len(gkless):,} | keeperless at size: "
          f"{len(gkless):,} | players to generate: {total_new:,}")

    if not dry:
        shutil.copy2(DB, str(DB) + ".bak-prefill")
        con.execute("BEGIN")
    made = 0
    for tid, cur, need in to_fill:
        nat = (squad_nat[tid].most_common(1)[0][0] if squad_nat.get(tid)
               else team_country.get(tid, "")) or ""
        ovrs = squad_ovr.get(tid, [])
        base = round(sum(ovrs) / len(ovrs)) if ovrs else (team_rating.get(tid) or 55)
        base = max(46, min(82, base))
        start_slot = len(squad_pos.get(tid, []))
        for k, pos in enumerate(plan(squad_pos.get(tid, []), need)):
            pid = nid
            nid += 1
            ovr = max(42, min(90, base + rng.randint(-8, 1)))
            age = rng.randint(18, 33)
            name = name_for(nat)
            if not dry:
                con.execute(
                    "INSERT INTO players(id,game_pid,is_custom,name,position,overall_rating,age,nationality) "
                    "VALUES(?,?,1,?,?,?,?,?)", (pid, pid, name, pos, ovr, age, nat or None))
                con.executemany(
                    "INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                    [(pid, a, v) for a, v in synth(pid, ovr, pos).items()])
                con.execute(
                    "INSERT INTO squad_members(team_id,player_id,squad_number,slot) VALUES(?,?,?,?)",
                    (tid, pid, start_slot + k + 1, start_slot + k))
            made += 1
        if dry and made <= 12:
            ex = [(name_for(nat), p) for p in plan(squad_pos.get(tid, []), need)[:4]]
            print(f"  team {tid} ({nat}) {cur}->{TARGET}, base~{base}: {ex}")
    if not dry:
        con.commit()
    print(f"{'would generate' if dry else 'generated'} {made:,} filler players across "
          f"{len(to_fill):,} clubs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
