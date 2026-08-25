#!/usr/bin/env python3
"""
ef_import_missing.py — import the eFootball-native players the harvest never took.

dt870_harvest.py only imports a CSV row whose PID is present in the INSTALLED game's
Player.bin (dt200 ∪ dt870). Anyone Konami delivers by live update is therefore dropped: the
editor export carries 25,460 base players and master.db held 24,002. The 1,458 missing were
not random — they were whole squads, including all of Liverpool and Arsenal (Van Dijk, Saka,
Rice, Isak, Raya, Saliba, Rodri, Cristiano Ronaldo). That gap is why those two clubs needed a
hand-typed curated overlay, why the records minted from it had no playstyles, and why their
attributes were FM approximations instead of Konami's own numbers.

samples/editor-bundled-players.csv IS the editor's bundled roster, so it is authoritative for
eFootball attributes regardless of which CPK version is installed. This imports every base-band
row (id < 2^24, the eF namespace — CSV ids in 20M-700M are the career band and are never taken)
using dt870_harvest's own column list and enum maps, never a re-typed copy of them.

It also LINKS the new records into the identity spine: player_identity(kind='ef') for each, plus
ef_pid on an existing FM/RFS/curated record of the same human (exact name tokens + compatible
nationality + age within 3, unique on both sides). supersede_twins.py then merges the pair and,
because eFootball is the attribute authority, the surviving squadded record inherits these
attributes, playstyles and skills.

    python tools/ef_import_missing.py --dry
    python tools/ef_import_missing.py
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from dt870_harvest import ABILITIES, FOOT, FORM, INJURY, WEAK_FOOT  # noqa: E402

DB = REPO / "build" / "master.db"
CSVP = REPO / "samples" / "editor-bundled-players.csv"
EF_MAX = 1 << 24                       # the eF id namespace (docs/database-blueprint.md)

NAT_SYN = {"korea republic": "south korea", "china pr": "china", "ivory coast": "cote divoire",
           "holland": "netherlands", "usa": "united states", "turkiye": "turkey",
           "republic of ireland": "ireland", "czech republic": "czechia",
           "bosnia and herzegovina": "bosnia", "north macedonia": "macedonia"}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def ntoks(s: str) -> frozenset[str]:
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def nat_key(nat: str | None) -> frozenset[str]:
    out = set()
    for x in (nat or "").split("/"):
        k = re.sub(r"[^a-z ]", "", norm(x)).strip()
        if k:
            out.add(NAT_SYN.get(k, k))
    return frozenset(out)


def _int(v, default=None):
    try:
        return int((v or "").strip())
    except (ValueError, AttributeError):
        return default


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cur = con.cursor()

    rows = list(csv.DictReader(io.StringIO(CSVP.read_bytes().decode("utf-8-sig"))))
    by_pid = {int(r["player_id"]): r for r in rows
              if (r.get("player_id") or "").isdigit() and int(r["player_id"]) < EF_MAX}
    have = {r[0] for r in cur.execute("SELECT id FROM players")}
    todo = sorted(set(by_pid) - have)
    print(f"editor export: {len(by_pid):,} base-band players | already in master.db: "
          f"{len(set(by_pid) & have):,} | MISSING: {len(todo):,}")
    if not todo:
        return 0
    for pid in todo[:8]:
        r = by_pid[pid]
        print(f"   {pid:>8} {r['player_name'][:26]:26} {r['position']:4} "
              f"{r['team'][:22]:22} ovr {r['overall_rating']}")

    # ---------- rows, exactly as dt870_harvest writes them ----------
    pl, attr, skill, style = [], [], [], []
    for pid in todo:
        r = by_pid[pid]
        nm = (r.get("player_name") or "").strip()
        pl.append((pid, pid, pid, 0, nm, nm, (r.get("position") or "").strip(),
                   _int(r.get("age")), (r.get("nationality") or "").strip(),
                   _int(r.get("height")), _int(r.get("weight")), _int(r.get("overall_rating"))))
        for a in ABILITIES:
            v = _int(r.get(a))
            if v is not None:
                attr.append((pid, a, v))
        for name, table, col in (("weak_foot_usage", WEAK_FOOT, "weak_foot_usage"),
                                 ("weak_foot_accuracy", WEAK_FOOT, "weak_foot_accuracy"),
                                 ("form", FORM, "form"),
                                 ("injury_resistance", INJURY, "injury_resistance"),
                                 ("foot", FOOT, "foot")):
            code = table.get((r.get(col) or "").strip())
            if code is not None:
                attr.append((pid, name, code))
        for kind, col in (("primary", "primary_playing_style"),
                          ("secondary", "secondary_playing_style")):
            s = (r.get(col) or "").strip()
            if s:
                style.append((pid, s, kind))
        for sk in (r.get("player_skills") or "").split(";"):
            sk = sk.strip()
            if sk:
                skill.append((pid, sk, "csv"))
    print(f"to write: {len(pl):,} players | {len(attr):,} attributes | {len(style):,} playstyles "
          f"| {len(skill):,} skills")

    # ---------- spine links: which existing record is this same human? ----------
    existing = defaultdict(list)                      # (name tokens, nat) -> [(pid, age)]
    for pid, nm, age, nat, sup in cur.execute(
            "SELECT id, name, age, nationality, superseded_by FROM players "
            "WHERE NOT (id >= 20000000 AND id < 700000000)"):
        if sup is not None or pid < EF_MAX or 45_000_000_000 <= pid < 46_000_000_000:
            continue      # hidden rows, eF itself, and the curated CAREER overlay — its copy of
                          # Van Dijk would otherwise tie with the world record and make the one
                          # link we actually need look ambiguous
        existing[ntoks(nm)].append((pid, age, nat_key(nat)))

    linked, ambiguous = [], 0
    for pid in todo:
        r = by_pid[pid]
        t, age, nat = ntoks(r.get("player_name") or ""), _int(r.get("age")), \
            nat_key(r.get("nationality"))
        if len(t) < 2:
            continue                                  # a single token is not an identity
        cands = [p for p, a, n in existing.get(t, ())
                 if (age is None or a is None or abs(a - age) <= 3)
                 and (not nat or not n or nat & n)]
        if len(cands) == 1:
            linked.append((cands[0], pid))
        elif len(cands) > 1:
            ambiguous += 1
    print(f"spine links to existing records: {len(linked):,} (ambiguous, left alone: {ambiguous:,})")

    if dry:
        print("--dry: nothing written.")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-preefimport")
    cur.execute("BEGIN")
    cur.executemany(
        "INSERT OR REPLACE INTO players (id,game_pid,base_pid,is_custom,name,short_name,"
        "position,age,nationality,height_cm,weight_kg,overall_rating) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", pl)
    cur.executemany("INSERT INTO player_attributes (player_id,attribute,value) VALUES (?,?,?)",
                    attr)
    cur.executemany("INSERT INTO player_skills (player_id,skill,source) VALUES (?,?,?)", skill)
    cur.executemany("INSERT OR REPLACE INTO player_playstyles (player_id,playstyle,kind) "
                    "VALUES (?,?,?)", style)
    cur.executemany("INSERT OR REPLACE INTO player_identity "
                    "(player_id,kind,ef_pid,ef_method,confidence) VALUES (?,'ef',?,'id',1.0)",
                    [(p, p) for p in todo])
    for owner, ef in linked:
        cur.execute("UPDATE player_identity SET ef_pid=?, ef_method='name', "
                    "confidence=MIN(confidence, 0.85) WHERE player_id=? AND ef_pid IS NULL",
                    (ef, owner))
    con.commit()
    print(f"imported {len(pl):,} eFootball-native players.")
    print("next: supersede_twins.py --allow-floor (merges them, eF attributes win), "
          "sync_membership_fm.py, rerank_slots.py, validate_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
