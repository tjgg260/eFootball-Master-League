#!/usr/bin/env python3
"""
cleanup_db.py — one pass over every defect the 2026-08-23 six-dimension audit confirmed. Each step
is idempotent and prints what it removed/repaired; one backup up front. Order matters: ghosts are
swept before dedup logic relies on squad membership being meaningful.

  1  satellite rows for players that no longer exist (skills/playstyles/traits/market/…)
  2  rows referencing teams that no longer exist (tactics/coaches/rivals/staff/contracts/objectives)
  3  match data + meta keys for fixtures/teams a career reset deleted
  4  stale U21/U18 team layer from previous careers
  5  dangling league_rules + team_tactics with dead formation ids
  6  age repair (toddlers, 46+, NULL) + weight clamps + the one empty name
  7  filler name clones inside one club made unique
  8  multi-squad players cut to one membership; shirt-number collisions renumbered
  9  loan ghosts: same identity in 2+ reference squads -> FM's placement wins (membership rule)
 10  curated career-range players in REFERENCE squads migrated to the stable 45B curated namespace
 11  squad players with zero attributes -> copy from identity twin, else synthesise
 12  drop the two unused FM staging giants + the five redundant indexes  (then VACUUM separately)

    python tools/cleanup_db.py --dry      # counts only, no writes
    python tools/cleanup_db.py
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth_attributes import synth  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CURATED_BASE = 45_000_000_000        # curated overlay players: above FM (≤~12B), below fakes (50B)

PID_TABLES = ["player_attributes", "player_skills", "player_playstyles", "player_traits",
              "player_appearance", "player_appearance_raw", "player_market", "player_potential",
              "player_condition", "player_knowledge", "player_positions", "player_status",
              "morale", "promises", "training_focus", "skill_training", "academy", "contracts",
              "negotiations", "loans", "squad_members"]
TID_TABLES = ["team_tactics", "coaches", "staff", "contracts", "objectives", "board_confidence"]


def ident(nm, nat, age):
    n = unicodedata.normalize("NFKD", nm or "").encode("ascii", "ignore").decode().lower()
    return (tuple(sorted(re.sub(r"[^a-z ]", " ", n).split())), (nat or "").split("/")[0].strip().lower())


def hash_pid(pid: int) -> int:
    h = (pid * 2654435761) & 0xFFFFFFFF
    return h ^ (h >> 16)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    if not dry:
        shutil.copy2(DB, str(DB) + ".bak-precleanup")
        con.execute("PRAGMA foreign_keys=OFF")

    def run(sql, args=()):
        if dry:
            probe = "SELECT COUNT(*) " + sql[sql.upper().index("FROM"):] if sql.upper().startswith("DELETE") else None
            if probe:
                try:
                    return con.execute(probe, args).fetchone()[0]
                except sqlite3.Error:
                    return -1
            return 0
        return con.execute(sql, args).rowcount

    # 1 ─ satellites of dead players
    total = 0
    for t in PID_TABLES:
        try:
            n = run(f"DELETE FROM {t} WHERE player_id NOT IN (SELECT id FROM players)")
            if n:
                print(f"  1 {t}: {n} dead-player rows")
            total += max(n, 0)
        except sqlite3.OperationalError:
            pass
    print(f"step 1 (dead-player satellites): {total}")

    # 2 ─ rows referencing dead teams
    total = 0
    for t in TID_TABLES:
        try:
            n = run(f"DELETE FROM {t} WHERE team_id IS NOT NULL AND team_id NOT IN (SELECT id FROM teams)")
            if n:
                print(f"  2 {t}: {n}")
            total += max(n, 0)
        except sqlite3.OperationalError:
            pass
    total += max(run("DELETE FROM team_rivals WHERE team_id NOT IN (SELECT id FROM teams) "
                     "OR rival_id NOT IN (SELECT id FROM teams)"), 0)
    total += max(run("DELETE FROM transfers WHERE to_team_id NOT IN (SELECT id FROM teams) "
                     "OR player_id NOT IN (SELECT id FROM players)"), 0)
    print(f"step 2 (dead-team rows): {total}")

    # 3 ─ match data + meta for dead fixtures/teams
    total = 0
    for t in ("match_events", "match_team_stats", "match_player_ratings"):
        try:
            total += max(run(f"DELETE FROM {t} WHERE fixture_id NOT IN (SELECT id FROM fixtures)"), 0)
        except sqlite3.OperationalError:
            pass
    stale_meta = [k for (k,) in con.execute(
        "SELECT key FROM meta WHERE key LIKE 'chairman_%' OR key LIKE 'mgrname_%' OR key LIKE 'ttalk_pre_%'")
        if (m := re.search(r"_(\d+)$", k)) and (
            (k.startswith("ttalk") and not con.execute("SELECT 1 FROM fixtures WHERE id=?", (int(m.group(1)),)).fetchone())
            or (not k.startswith("ttalk") and not con.execute("SELECT 1 FROM teams WHERE id=?", (int(m.group(1)),)).fetchone()))]
    for k in stale_meta:
        total += max(run("DELETE FROM meta WHERE key=?", (k,)), 0) if not dry else 1
    print(f"step 3 (dead fixture/meta): {total} (+{len(stale_meta)} meta keys)")

    # 4 ─ stale youth-team layer
    yt = [r[0] for r in con.execute("SELECT id FROM teams WHERE team_kind IN ('u21','u18')")]
    if yt:
        q = ",".join("?" * len(yt))
        run(f"DELETE FROM squad_members WHERE team_id IN ({q})", yt)
        run(f"DELETE FROM team_tactics WHERE team_id IN ({q})", yt)
        run(f"DELETE FROM teams WHERE id IN ({q})", yt)
    print(f"step 4 (stale youth teams): {len(yt)}")

    # 5 ─ dangling league_rules + tactics with dead formations
    a = max(run("DELETE FROM league_rules WHERE league_id NOT IN (SELECT id FROM leagues)"), 0)
    b = max(run("DELETE FROM team_tactics WHERE formation_id IS NOT NULL "
                "AND formation_id NOT IN (SELECT id FROM formations)"), 0)
    print(f"step 5 (league_rules {a}, dead-formation tactics {b})")

    # 6 ─ age/weight/name repair (squad players only)
    insquad = "(SELECT DISTINCT player_id FROM squad_members)"
    fixes = 0
    for pid, age, dob in con.execute(
            f"SELECT id, age, dob FROM players WHERE id IN {insquad} "
            "AND (age IS NULL OR age < 15 OR age > 45)").fetchall():
        new = None
        if dob:
            m = re.search(r"(19|20)\d\d", str(dob))
            if m:
                new = max(15, min(45, 2026 - int(m.group(0))))
        if new is None:
            new = (19 + hash_pid(pid) % 15) if (age is None or age < 15) else (31 + hash_pid(pid) % 8)
        if not dry:
            con.execute("UPDATE players SET age=? WHERE id=?", (new, pid))
        fixes += 1
    w = max(run("UPDATE players SET weight_kg=NULL WHERE weight_kg IS NOT NULL AND (weight_kg<50 OR weight_kg>120)"), 0) if not dry else \
        con.execute("SELECT COUNT(*) FROM players WHERE weight_kg<50 OR weight_kg>120").fetchone()[0]
    noname = con.execute(f"SELECT id, nationality FROM players WHERE id IN {insquad} "
                         "AND (name IS NULL OR TRIM(name)='')").fetchall()
    for pid, nat in noname:
        pool = con.execute("SELECT name FROM players WHERE nationality=? AND name LIKE '% %' "
                           "AND id<16700000 LIMIT 200", (nat,)).fetchall() or \
               con.execute("SELECT name FROM players WHERE name LIKE '% %' LIMIT 200").fetchall()
        f = pool[hash_pid(pid) % len(pool)][0].split()[0]
        s = pool[hash_pid(pid + 1) % len(pool)][0].split()[-1]
        if not dry:
            con.execute("UPDATE players SET name=? WHERE id=?", (f"{f} {s}", pid))
    print(f"step 6 (age fixed {fixes}, weight cleared {w}, names given {len(noname)})")

    # 7 ─ fake-filler duplicate names within one club -> make unique
    dupes = con.execute(
        "SELECT s.team_id, p.name FROM squad_members s JOIN players p ON p.id=s.player_id "
        "WHERE p.id>=50000000000 GROUP BY s.team_id, p.name HAVING COUNT(*)>1").fetchall()
    renamed = 0
    for tid, nm in dupes:
        rows = con.execute("SELECT p.id, p.nationality FROM squad_members s JOIN players p ON p.id=s.player_id "
                           "WHERE s.team_id=? AND p.name=? ORDER BY p.id", (tid, nm)).fetchall()
        for pid, nat in rows[1:]:
            pool = con.execute("SELECT name FROM players WHERE nationality=? AND name LIKE '% %' "
                               "AND id<50000000000 LIMIT 300", (nat,)).fetchall()
            if not pool:
                continue
            f = pool[hash_pid(pid) % len(pool)][0].split()[0]
            s2 = pool[hash_pid(pid + 7) % len(pool)][0].split()[-1]
            if not dry:
                con.execute("UPDATE players SET name=? WHERE id=?", (f"{f} {s2}", pid))
            renamed += 1
    print(f"step 7 (filler clone names regenerated): {renamed}")

    # 8 ─ one membership per player + shirt-number collisions
    multi = con.execute("SELECT player_id FROM squad_members GROUP BY player_id "
                        "HAVING COUNT(DISTINCT team_id)>1").fetchall()
    import json
    cat_ids = set()
    catp = REPO / "build" / "catalog.json"
    if catp.exists():
        c = json.loads(catp.read_text(encoding="utf-8"))
        cat_ids = {t["team_id"] for co in c["countries"] for lg in co["leagues"] for t in lg["teams"]}
    cut = 0
    for (pid,) in multi:
        rows = con.execute("SELECT team_id FROM squad_members WHERE player_id=?", (pid,)).fetchall()
        keep = sorted((t for (t,) in rows), key=lambda t: (t not in cat_ids, t))[0]
        if not dry:
            con.execute("DELETE FROM squad_members WHERE player_id=? AND team_id<>?", (pid, keep))
        cut += len(rows) - 1
    coll = con.execute("SELECT DISTINCT team_id FROM squad_members GROUP BY team_id, squad_number "
                       "HAVING COUNT(*)>1").fetchall()
    for (tid,) in coll:
        if dry:
            continue
        members = con.execute("SELECT player_id FROM squad_members WHERE team_id=? ORDER BY slot", (tid,)).fetchall()
        for i, (mp,) in enumerate(members):
            con.execute("UPDATE squad_members SET squad_number=?, slot=? WHERE team_id=? AND player_id=?",
                        (i + 1, i, tid, mp))
    print(f"step 8 (extra memberships cut {cut}, teams renumbered {len(coll)})")

    # 9 ─ loan ghosts across reference squads: FM's placement wins
    where_ref = "s.team_id>=3000000"
    by_ident = defaultdict(list)
    for pid, nm, nat, age, tid in con.execute(
            f"SELECT p.id, p.name, p.nationality, p.age, s.team_id FROM squad_members s "
            f"JOIN players p ON p.id=s.player_id WHERE {where_ref} AND p.id<50000000000"):
        key = ident(nm, nat, age)
        if key[0]:
            by_ident[key].append((pid, age, tid))
    def source(pid):
        return 0 if pid < 16_700_000 else 1 if pid < 700_000_000 else 2 if pid < 10_000_000_000 else 3

    ghosts = 0
    for key, rows in by_ident.items():
        teams = {t for _, _, t in rows}
        if len(teams) < 2:
            continue
        # CROSS-SOURCE only: one source never duplicates a real person, so two same-name records
        # from the SAME source at different clubs are two different people — leave them alone.
        if len({source(p) for p, _, _ in rows}) < 2:
            continue
        ages = [a for _, a, _ in rows if a is not None]
        if ages and max(ages) - min(ages) > 3:
            continue                    # probably two different people
        fm = [r for r in rows if r[0] >= 10_000_000_000]
        keep_rows = fm or [max(rows, key=lambda r: r[0] < 16_700_000)]   # FM wins, else eF-native
        keep_teams = {t for _, _, t in keep_rows[:1]}
        for pid, _a, tid in rows:
            if tid not in keep_teams:
                if not dry:
                    con.execute("DELETE FROM squad_members WHERE player_id=? AND team_id=?", (pid, tid))
                ghosts += 1
    print(f"step 9 (loan-ghost memberships removed): {ghosts}")

    # 10 ─ curated overlay players (career range) inside REFERENCE squads -> 45B namespace
    cur = con.execute("SELECT DISTINCT s.player_id FROM squad_members s "
                      "WHERE s.team_id>=3000000 AND s.player_id>=20000000 AND s.player_id<700000000").fetchall()
    moved = 0
    for (old,) in cur:
        new = CURATED_BASE + old
        if dry:
            moved += 1
            continue
        con.execute("UPDATE players SET id=?, game_pid=? WHERE id=?", (new, new, old))
        for t in PID_TABLES:
            try:
                con.execute(f"UPDATE {t} SET player_id=? WHERE player_id=?", (new, old))
            except sqlite3.OperationalError:
                pass
        moved += 1
    print(f"step 10 (curated players -> 45B namespace): {moved}")

    # 11 ─ squad players with zero attributes: identity twin else synth
    fixed = 0
    for pid, nm, nat, age, pos, ovr in con.execute(
            "SELECT p.id, p.name, p.nationality, p.age, p.position, p.overall_rating FROM players p "
            f"WHERE p.id IN {insquad} AND NOT EXISTS "
            "(SELECT 1 FROM player_attributes a WHERE a.player_id=p.id)").fetchall():
        twin = None
        for tp, in con.execute("SELECT id FROM players WHERE name=? AND id<>? LIMIT 5", (nm, pid)):
            if con.execute("SELECT 1 FROM player_attributes WHERE player_id=? LIMIT 1", (tp,)).fetchone():
                twin = tp
                break
        rows = (con.execute("SELECT attribute, value FROM player_attributes WHERE player_id=?", (twin,)).fetchall()
                if twin else list(synth(pid, ovr or 55, pos or "CMF").items()))
        if not dry:
            con.executemany("INSERT OR IGNORE INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)",
                            [(pid, a, v) for a, v in rows])
        fixed += 1
    print(f"step 11 (attribute-less squad players filled): {fixed}")

    if not dry:
        con.commit()

    # 12 ─ storage: unused staging giants + redundant PK-prefix indexes
    if not dry:
        for t in ("fm_raw_players", "fm_attributes"):
            try:
                con.execute(f"DROP TABLE IF EXISTS {t}")
                print(f"step 12 dropped {t}")
            except sqlite3.OperationalError as e:
                print(f"step 12 could not drop {t}: {e}")
        for ix in ("ix_attr_pid", "ix_style_pid", "ix_market_pid", "ix_appear_pid", "ix_squad_team"):
            con.execute(f"DROP INDEX IF EXISTS {ix}")
        print("step 12 dropped 5 redundant indexes")
        con.commit()
    else:
        print("step 12 (would drop fm_raw_players, fm_attributes, 5 redundant indexes)")
    print("done." if not dry else "(dry run — no writes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
