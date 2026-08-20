#!/usr/bin/env python3
"""
verify_match_build.py — prove a play_match real-slot build is surgical.

Loads a built dt200 CPK next to the pristine base CPK and asserts, payload byte for payload
byte, that the compile touched ONLY what it is allowed to touch:

  a. TacticsFormation.bin — the home club's OWN fid pair carries the DB geometry
     (role/x/y per slot), including any hand-tuned slot; the write actually changed bytes.
  b. TacticsFormation.bin — every OTHER formation's rows are byte-identical to base
     (CORRUPTION GUARD: no other team's shape may ever move).
  c. Tactics.bin — zero formation_id u32 changes anywhere; only the two fixture teams'
     style bytes may differ; every other byte identical.
  d. Player.bin — diffs limited to bytes 46-47 (the 5-bit playstyle field) of squad members
     that have a saved role in the DB, with the correct encoded value.
  e. PlayerAssignment.bin — per-team record counts unchanged; the home team's first 11
     records by sort_key are the DB slots 0-10 resolved pids; sort_key/flag bytes untouched.

    python tools/verify_match_build.py \
        --built build/dt200_verify.cpk --base dt200_console_all.cpk \
        --home-id 800000 --away-id 800001

Exit code 0 iff every assert passes.
"""
from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
import wesys                                        # noqa: E402
import pesdb                                        # noqa: E402
from play_match import _norm_club, _name_matches, _pnorm, _pos_cat, _style_table  # noqa: E402

PESDB = "common/etc/pesdb/"
FILES = ("Tactics.bin", "TacticsFormation.bin", "Player.bin", "PlayerAssignment.bin")

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return ok


def cpk_payloads(path: Path) -> dict[str, bytes]:
    """filename -> decoded WESYS payload for the pesdb files we verify."""
    from cricodecs import cpk
    c = cpk.load(str(path))
    out: dict[str, bytes] = {}
    for i, e in enumerate(c.files):
        fp = e.full_path.replace("\\", "/")
        for fn in FILES:
            if fp.endswith(PESDB + fn):
                out[fn] = wesys.unpack_wesys_payload(c.file_bytes(i))
    missing = [fn for fn in FILES if fn not in out]
    if missing:
        sys.exit(f"{path}: missing {missing} — not a dt200 CPK?")
    return out


def team_fid_pair(tactics: bytes, team_id: int) -> tuple[int, int]:
    fids = {}
    for i in range(len(tactics) // 12):
        if struct.unpack_from("<I", tactics, i * 12)[0] == team_id:
            fids[tactics[i * 12 + 9]] = struct.unpack_from("<I", tactics, i * 12 + 4)[0]
    if 0 not in fids or 1 not in fids:
        sys.exit(f"team {team_id} owns no Tactics.bin fid pair")
    return fids[0], fids[1]


def tf_rows(tf: bytes, fid: int) -> dict[int, tuple[int, int, int]]:
    """slot -> (role, x, y) for one formation in TacticsFormation.bin."""
    out = {}
    for i in range(len(tf) // 12):
        if struct.unpack_from("<I", tf, i * 12 + 4)[0] == fid:
            out[tf[i * 12 + 10]] = (struct.unpack_from("<I", tf, i * 12)[0],
                                    tf[i * 12 + 9], tf[i * 12 + 8])
    return out


def db_geometry(con, fid: int) -> dict[int, tuple[int, int, int]]:
    return {sl: (role, x, y) for sl, role, x, y in con.execute(
        "SELECT slot_index, position, x, y FROM formation_slots WHERE formation_id=?", (fid,))}


def db_squad(con, team_id: int) -> list[dict]:
    """Squad in DB slot order with saved role — same view play_match compiles from."""
    rows = []
    for pid, shirt, name, pos in con.execute(
            "SELECT sm.player_id, sm.squad_number, p.name, p.position FROM squad_members sm "
            "JOIN players p ON p.id=sm.player_id WHERE sm.team_id=? ORDER BY sm.slot", (team_id,)):
        role = con.execute("SELECT playstyle FROM player_playstyles WHERE player_id=? LIMIT 1",
                           (pid,)).fetchone()
        rows.append({"db_pid": pid, "name": name, "position": pos,
                     "shirt": shirt if 1 <= shirt <= 99 else len(rows) + 1,
                     "role": role[0] if role else None})
    return rows


def player_index(pb: bytes) -> tuple[dict[int, str], dict[int, int], dict[str, int]]:
    """pid->name, pid->record offset, normalised-name->pid (same index reconcile builds)."""
    pid2name, pid2off, global_index = {}, {}, {}
    for k in range(len(pb) // 400):
        pid = struct.unpack_from("<Q", pb, k * 400 + 8)[0]
        nm = pb[k * 400 + 271:k * 400 + 271 + 61].split(b"\0")[0].decode("utf-8", "replace")
        pid2name[pid] = nm
        pid2off[pid] = k * 400
        n = _pnorm(nm)
        if n:
            global_index.setdefault(n, pid)
            global_index.setdefault(n.split()[-1], pid)
    return pid2name, pid2off, global_index


def resolve_squad(base_pa: bytes, pid2name: dict, global_index: dict,
                  slot_id: int, squad: list[dict]):
    """
    Re-run reconcile_real_slot's name resolution against the BASE tree (the state it ran on):
    squad index -> resolved eFootball pid. Independent oracle for asserts d/e.
    """
    recs = pesdb.parse_player_assignment_bin(base_pa)
    slot_recs = sorted((r for r in recs if r["team_id"] == slot_id), key=lambda r: r["sort_key"])
    used, by_ix = set(), {}
    for ix in sorted(range(len(squad)), key=lambda i: -len(squad[i]["name"].split())):
        p = squad[ix]
        pid = None
        for r in slot_recs:
            if r["player_id"] not in used and _name_matches(p["name"], pid2name.get(r["player_id"], "")):
                pid = r["player_id"]; break
        if pid is None:
            n = _pnorm(p["name"])
            cand = global_index.get(n) or global_index.get(n.split()[-1] if n else n)
            if cand is not None and cand not in used:
                pid = cand
        if pid is not None:
            used.add(pid)
            by_ix[ix] = pid
    return by_ix, slot_recs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--built", default=str(REPO / "build" / "dt200_verify.cpk"))
    ap.add_argument("--base", default=str(REPO / "dt200_console_all.cpk"))
    ap.add_argument("--db", default=str(REPO / "build" / "master.db"))
    ap.add_argument("--home-id", type=int, default=800000)
    ap.add_argument("--away-id", type=int, default=800001)
    args = ap.parse_args()

    base = cpk_payloads(Path(args.base))
    built = cpk_payloads(Path(args.built))
    con = sqlite3.connect(args.db)

    # ---- resolve the two clubs to their in-game team slots (same matching as play_match) ----
    def slot_of(db_team: int) -> tuple[int, str]:
        name = con.execute("SELECT name FROM teams WHERE id=?", (db_team,)).fetchone()[0]
        team = base["Tactics.bin"]  # team ids come from Tactics.bin; names need Team.bin — use the
        del team                    # built tree's Team.bin path via the base CPK instead:
        from cricodecs import cpk
        c = cpk.load(args.base)
        for i, e in enumerate(c.files):
            if e.full_path.replace("\\", "/").endswith(PESDB + "Team.bin"):
                tb = wesys.unpack_wesys_payload(c.file_bytes(i))
                break
        else:
            sys.exit("Team.bin not in base CPK")
        for off in range(0, len(tb), 1600):
            tid = struct.unpack_from("<I", tb, off + 12)[0]
            nm = tb[off + 396:off + 396 + 48].split(b"\0")[0].decode("utf-8", "replace").strip()
            if nm and _norm_club(nm) == _norm_club(name):
                return tid, nm
        sys.exit(f"no in-game slot for {name!r}")

    home_slot, home_game_name = slot_of(args.home_id)
    away_slot, away_game_name = slot_of(args.away_id)
    print(f"home {args.home_id} -> in-game {home_game_name} ({home_slot});"
          f"  away {args.away_id} -> in-game {away_game_name} ({away_slot})\n")

    fluid = (con.execute("SELECT value FROM meta WHERE key=?",
                         (f"tactics_fluid_{args.home_id}",)).fetchone() or ["0"])[0] == "1"
    tt = dict(con.execute("SELECT phase, formation_id FROM team_tactics WHERE team_id=?",
                          (args.home_id,)))
    db_main = db_geometry(con, tt[0])
    db_sub = db_geometry(con, tt[1]) if fluid and 1 in tt else db_main

    # ================= a. own-fid geometry reflects the DB =================
    fid0, fid1 = team_fid_pair(base["Tactics.bin"], home_slot)
    got0 = tf_rows(built["TacticsFormation.bin"], fid0)
    got1 = tf_rows(built["TacticsFormation.bin"], fid1)
    base0 = tf_rows(base["TacticsFormation.bin"], fid0)
    check("a1. home fid0 geometry == DB main (role/x/y, 11 slots)",
          got0 == db_main, f"fid {fid0}; slot10 built={got0.get(10)} db={db_main.get(10)}")
    check("a2. home fid1 geometry == DB " + ("sub (fluid)" if fluid else "main (mirrored)"),
          got1 == db_sub, f"fid {fid1}")
    check("a3. geometry write actually changed bytes vs base",
          got0 != base0, f"base slot10={base0.get(10)} -> built slot10={got0.get(10)}")

    # ================= b. corruption guard: every other fid untouched =================
    tf_b, tf_v = base["TacticsFormation.bin"], built["TacticsFormation.bin"]
    ok = check("b1. TacticsFormation.bin length unchanged", len(tf_b) == len(tf_v),
               f"{len(tf_b)} vs {len(tf_v)}")
    own = {fid0, fid1}
    bad = []
    if ok:
        for i in range(len(tf_b) // 12):
            if struct.unpack_from("<I", tf_b, i * 12 + 4)[0] in own:
                # even for the own pair, fid + slot + trailing byte must be as shipped
                if (tf_b[i * 12 + 4:i * 12 + 8] != tf_v[i * 12 + 4:i * 12 + 8]
                        or tf_b[i * 12 + 10:i * 12 + 12] != tf_v[i * 12 + 10:i * 12 + 12]):
                    bad.append((i, "own-fid record: fid/slot bytes moved"))
            elif tf_b[i * 12:i * 12 + 12] != tf_v[i * 12:i * 12 + 12]:
                bad.append((i, struct.unpack_from("<I", tf_b, i * 12 + 4)[0]))
    check("b2. every OTHER formation byte-identical to base (corruption guard)",
          ok and not bad, f"{len(tf_b)//12} records; violations: {bad[:5]}")

    # ================= c. Tactics.bin: styles only, formation_id never =================
    tc_b, tc_v = base["Tactics.bin"], built["Tactics.bin"]
    ok = check("c1. Tactics.bin length unchanged", len(tc_b) == len(tc_v))
    fid_moved, foreign, style_diffs = [], [], []
    if ok:
        for i in range(len(tc_b) // 12):
            o = i * 12
            tid = struct.unpack_from("<I", tc_b, o)[0]
            if tc_b[o:o + 4] != tc_v[o:o + 4] or tc_b[o + 4:o + 8] != tc_v[o + 4:o + 8]:
                fid_moved.append((i, tid))
            if tc_b[o + 9:o + 12] != tc_v[o + 9:o + 12]:
                foreign.append((i, tid, "phase/tail bytes"))
            if tc_b[o + 8] != tc_v[o + 8]:
                if tid in (home_slot, away_slot):
                    style_diffs.append((tid, tc_b[o + 8], tc_v[o + 8]))
                else:
                    foreign.append((i, tid, "style"))
    check("c2. zero formation_id (and team_id) u32 changes", ok and not fid_moved,
          f"moved: {fid_moved[:5]}")
    check("c3. only the two fixture teams' style bytes differ", ok and not foreign,
          f"style diffs on fixture teams: {style_diffs}; foreign diffs: {foreign[:5]}")

    # ================= d. Player.bin: playstyle bytes only, correct values =================
    pb_b, pb_v = base["Player.bin"], built["Player.bin"]
    ok = check("d1. Player.bin length unchanged (no authoring on real slots)",
               len(pb_b) == len(pb_v), f"{len(pb_b)} vs {len(pb_v)}")
    pid2name, pid2off, gidx = player_index(pb_b)
    home_sq = db_squad(con, args.home_id)
    away_sq = db_squad(con, args.away_id)
    res_home, home_slot_recs = resolve_squad(base["PlayerAssignment.bin"], pid2name, gidx,
                                             home_slot, home_sq)
    res_away, _ = resolve_squad(base["PlayerAssignment.bin"], pid2name, gidx, away_slot, away_sq)

    table = _style_table()
    expected: dict[int, int] = {}   # eF pid -> expected 5-bit value
    for sq, res in ((home_sq, res_home), (away_sq, res_away)):
        for ix, p in enumerate(sq):
            if p["role"] and ix in res:
                val = table.get((_pos_cat(p["position"]), p["role"]))
                if val is not None:
                    expected[res[ix]] = val & 0x1F

    stray, wrong = [], []
    if ok:
        for k in range(len(pb_b) // 400):
            o = k * 400
            if pb_b[o:o + 400] == pb_v[o:o + 400]:
                continue
            pid = struct.unpack_from("<Q", pb_b, o + 8)[0]
            outside = (pb_b[o:o + 46] != pb_v[o:o + 46]
                       or pb_b[o + 48:o + 400] != pb_v[o + 48:o + 400])
            if outside or pid not in expected:
                stray.append((pid, pid2name.get(pid, "?"),
                              "outside 46-47" if outside else "no role in DB"))
                continue
            got = ((pb_v[o + 46] >> 6) & 0x03) | ((pb_v[o + 47] & 0x07) << 2)
            if got != expected[pid]:
                wrong.append((pid, pid2name.get(pid, "?"), got, expected[pid]))
    check("d2. Player.bin diffs limited to bytes 46-47 of squad members with roles",
          ok and not stray, f"stray: {stray[:5]}")
    b2b = [(pid, v) for pid, v in expected.items() if v == 7]
    detail = "; ".join(f"{pid2name.get(pid, pid)}=7(Box-to-Box)" for pid, _ in b2b)
    check("d3. every written playstyle encodes its table value (Box-to-Box == 7)",
          ok and not wrong and any(v == 7 for v in expected.values()),
          detail + (f"; wrong: {wrong[:5]}" if wrong else ""))

    # ================= e. PlayerAssignment.bin: occupants only =================
    pa_b, pa_v = base["PlayerAssignment.bin"], built["PlayerAssignment.bin"]
    ok = check("e1. PlayerAssignment.bin length unchanged", len(pa_b) == len(pa_v))
    v2 = pesdb.detect_assignment_layout(pa_b).endswith("/v2")
    pid_off, shirt_off = (0, 16) if v2 else (8, 20)

    recs_b = pesdb.parse_player_assignment_bin(pa_b)
    recs_v = pesdb.parse_player_assignment_bin(pa_v)
    cnt_b = Counter(r["team_id"] for r in recs_b)
    cnt_v = Counter(r["team_id"] for r in recs_v)
    check("e2. per-team record counts unchanged", cnt_b == cnt_v,
          f"changed: {[t for t in cnt_b.keys() | cnt_v.keys() if cnt_b[t] != cnt_v[t]][:5]}")

    # sort_key / flags / team_id untouched everywhere; pid+shirt only on the two teams
    fixture = {home_slot, away_slot}
    stray = []
    for i in range(len(pa_b) // 24):
        o = i * 24
        if pa_b[o:o + 24] == pa_v[o:o + 24]:
            continue
        tid = recs_b[i]["team_id"]
        mb, mv = bytearray(pa_b[o:o + 24]), bytearray(pa_v[o:o + 24])
        for m in (mb, mv):
            m[pid_off:pid_off + 8] = b"\0" * 8
            m[shirt_off] = 0
        if tid not in fixture or mb != mv:
            stray.append((i, tid, "non-pid/shirt bytes" if mb != mv else "foreign team"))
    check("e3. only fixture teams' pid+shirt bytes touched (sort_key/flags intact)",
          not stray, f"violations: {stray[:5]}")

    # first 11 by sort_key == DB slots 0-10 resolved (unresolved skipped, next promoted)
    exp_order = [res_home[ix] for ix in sorted(res_home)]
    surplus = [r["player_id"] for r in home_slot_recs if r["player_id"] not in set(res_home.values())]
    exp_first11 = (exp_order + surplus)[:11]
    built_home = sorted((r for r in recs_v if r["team_id"] == home_slot),
                        key=lambda r: r["sort_key"])
    got_first11 = [r["player_id"] for r in built_home[:11]]
    xi_named = [pid2name.get(p, str(p)) for p in got_first11]
    unresolved_xi = [home_sq[ix]["name"] for ix in range(min(11, len(home_sq)))
                     if ix not in res_home]
    check("e4. home first 11 by sort_key == DB slots 0-10 resolved pids",
          got_first11 == exp_first11,
          f"XI: {xi_named}" + (f"; unresolved XI names: {unresolved_xi}" if unresolved_xi else ""))

    con.close()
    fails = [n for n, ok_, _ in _results if not ok_]
    print()
    print("ALL PASS" if not fails else f"FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
