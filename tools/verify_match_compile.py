#!/usr/bin/env python3
"""
verify_match_compile.py — prove the match compile carries the CAREER into the game.

Works on a COPY of the world, never the save. In the copy it develops one starter, runs another
into the ground, injures a third and suspends a fourth; compiles the manager's next fixture with
--compile-only (the working tree is staged, no CPK is built, nothing is installed); then reads the
staged Player.bin and PlayerAssignment.bin back and checks the game files say what the career says:

  - the developed player shows his new abilities, the exhausted one his shaved ones
  - nobody injured or suspended is in the starting XI, and both sit at the back of the squad
  - every Player.bin record OUTSIDE the two squads is byte-identical to the base tree
  - inside the squads, nothing but ability and playstyle fields moved

    python tools/verify_match_compile.py            # build/game_world.db
    python tools/verify_match_compile.py --db <file>
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys  # noqa: E402
import pesdb  # noqa: E402
import match_condition  # noqa: E402

PLAYER = "common/etc/pesdb/Player.bin"
ASSIGN = "common/etc/pesdb/PlayerAssignment.bin"
PASSED = FAILED = 0


def check(what: str, ok: bool, extra: str = "") -> None:
    global PASSED, FAILED
    print(f"  [{'PASS' if ok else 'FAIL'}] {what}{('  - ' + extra) if extra else ''}")
    if ok:
        PASSED += 1
    else:
        FAILED += 1


def records(tree: Path) -> dict[int, bytes]:
    payload = wesys.unpack_wesys_payload((tree / PLAYER).read_bytes())
    return {struct.unpack_from("<Q", payload, i + 8)[0]: payload[i:i + 400] for i in range(0, len(payload), 400)}


def club_order(tree: Path, slot: int) -> list[int]:
    payload = wesys.unpack_wesys_payload((tree / ASSIGN).read_bytes())
    recs = [r for r in pesdb.parse_player_assignment_bin(payload) if r["team_id"] == slot]
    return [r["player_id"] for r in sorted(recs, key=lambda r: r["sort_key"])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(REPO / "build" / "game_world.db"))
    args = ap.parse_args()

    work = Path(tempfile.gettempdir()) / "ml_verify_compile.db"
    shutil.copy2(args.db, work)
    con = sqlite3.connect(work)
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    meta = dict(q("SELECT key, value FROM meta WHERE key IN ('current_team_id','current_season_id')"))
    me, season = int(meta["current_team_id"]), int(meta["current_season_id"])
    fx = q("SELECT matchday, home_team_id, away_team_id FROM fixtures WHERE season_id=? AND played=0 "
           "AND (home_team_id=? OR away_team_id=?) ORDER BY matchday LIMIT 1", season, me, me)[0]
    matchday, home, away = fx
    slot = q("SELECT base_team_id FROM teams WHERE id=?", me)[0][0]
    print(f"fixture: MD{matchday}  {home} v {away}   (managed club {me} -> eFootball team {slot})")

    xi = q("SELECT s.player_id, p.name, p.base_pid, p.position FROM squad_members s JOIN players p ON p.id=s.player_id "
           "WHERE s.team_id=? AND s.slot BETWEEN 0 AND 10 AND p.position<>'GK' ORDER BY s.slot", me)
    grown, tired, hurt, banned = xi[0], xi[1], xi[2], xi[3]
    names = lambda row: f"{row[1]} (pid {row[2]})"
    print(f"  developed: {names(grown)}\n  exhausted: {names(tired)}\n  injured:   {names(hurt)}\n  suspended: {names(banned)}\n")

    # --- the career moves on, in the copy
    base_of = lambda pid: dict(q("SELECT attribute, value FROM player_attributes WHERE player_id=?", pid))
    before_grown = base_of(grown[0])
    con.execute("UPDATE player_attributes SET value=MIN(99, value+5) WHERE player_id=? AND attribute='finishing'", (grown[0],))
    con.execute("UPDATE player_attributes SET value=MAX(40, value-3) WHERE player_id=? AND attribute='speed'", (grown[0],))
    con.execute("INSERT OR REPLACE INTO player_condition(player_id,fatigue,injured_until_md,form) VALUES(?,?,NULL,?)",
                (tired[0], 60, 4.0))
    con.execute("INSERT OR REPLACE INTO morale(player_id,value) VALUES(?,10)", (tired[0],))
    con.execute("INSERT OR REPLACE INTO player_condition(player_id,fatigue,injured_until_md,form) VALUES(?,0,?,6.5)",
                (hurt[0], matchday + 2))
    con.execute("CREATE TABLE IF NOT EXISTS suspensions(player_id INTEGER PRIMARY KEY, matches INTEGER NOT NULL, "
                "reason TEXT NOT NULL, season_id INTEGER NOT NULL)")
    con.execute("INSERT OR REPLACE INTO suspensions VALUES(?,1,'red card',?)", (banned[0], season))
    con.commit()
    want_grown = base_of(grown[0])
    writer = match_condition.AbilityWriter(400)
    ability = lambda d: {k: v for k, v in d.items() if k in writer.offsets}
    want_tired = match_condition.for_the_match(ability(base_of(tired[0])), 60, 4.0, 10)
    con.close()

    # --- compile (staged tree only)
    run = subprocess.run([sys.executable, str(REPO / "tools" / "play_match.py"), "--home-id", str(home),
                          "--away-id", str(away), "--db", str(work), "--compile-only"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    print("\n".join("    | " + line for line in run.stdout.splitlines()))
    if run.returncode != 0:
        print(run.stderr[-2000:])
        check("the compile ran", False, f"exit {run.returncode}")
        return 1
    staged = REPO / "build" / "tree_match"
    base, now = records(REPO / "build" / "tree_base"), records(staged)

    print("\nabilities")
    g = writer.read(now[grown[2]], grown[2])
    check("the developed player's finishing went UP in the game file",
          g["finishing"] == want_grown["finishing"] and g["finishing"] == min(99, before_grown["finishing"] + 5),
          f"{before_grown['finishing']} -> {g['finishing']}")
    check("...and his speed went down", g["speed"] == want_grown["speed"], f"{before_grown['speed']} -> {g['speed']}")
    t = writer.read(now[tired[2]], tired[2])
    t0 = writer.read(base[tired[2]], tired[2])
    check("the exhausted player carries exactly the shaved abilities", t == {**t, **want_tired},
          f"stamina {t0['stamina']} -> {t['stamina']}, speed {t0['speed']} -> {t['speed']}, "
          f"finishing {t0['finishing']} -> {t['finishing']}")
    check("his legs went further than his touch",
          (t0["stamina"] - t["stamina"]) >= (t0["ball_control"] - t["ball_control"]))
    check("nobody sank below the floor of the scale", min(t.values()) >= 40)

    print("\navailability")
    order = club_order(staged, slot)
    check("the injured player is not in the starting XI", hurt[2] not in order[:11])
    check("the suspended player is not in the starting XI", banned[2] not in order[:11])
    squad_size = len([1 for _ in order])
    tail = order[-2:]
    in_club = [p for p in (hurt[2], banned[2]) if p in order]
    check("both are at the very back of the squad order", set(in_club) <= set(order[-len(in_club):]) if in_club else True,
          f"last two of {squad_size}: {tail}")
    check("the XI still has eleven men", len(set(order[:11])) == 11)

    print("\nnothing else moved")
    con = sqlite3.connect(work)
    squads = {r[0] for r in con.execute(
        "SELECT p.base_pid FROM squad_members s JOIN players p ON p.id=s.player_id WHERE s.team_id IN (?,?)",
        (home, away)) if r[0] is not None}
    con.close()
    outside = [pid for pid in base if pid not in squads and base[pid] != now.get(pid)]
    check("every record outside the two squads is byte-identical to the base tree", not outside,
          f"{len(outside)} changed" if outside else f"{len(base) - len(squads):,} records untouched")
    # inside the squads: only ability fields and the playstyle bytes (46-47, 55) may differ
    style_mask = 0
    for byte in (46, 47, 54, 55, 56):
        style_mask |= 0xFF << (byte * 8)
    allowed = writer.mask | style_mask
    strayed = [pid for pid in squads if pid in base and pid in now and
               (int.from_bytes(base[pid], "little") ^ int.from_bytes(now[pid], "little")) & ~allowed]
    check("inside the squads only ability and role fields changed", not strayed,
          f"{len(strayed)} strayed: {strayed[:5]}" if strayed else "")
    check("the file still holds the same number of players", len(base) == len(now))

    work.unlink(missing_ok=True)
    print(f"\n{PASSED} passed, {FAILED} failed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
