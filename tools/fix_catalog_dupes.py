#!/usr/bin/env python3
"""
fix_catalog_dupes.py — one club record must not occupy league slots in several COUNTRIES.

England's Premier League listed "Arsenal FC" as team 3000001 — whose squad is twenty
Montenegrins, because 3000001 is Montenegro's Arsenal (teams.league_id 1103 = 1.CFL). The same
record also filled Argentina's Primera B and Belarus's Vyšėjšaja Liha. The world therefore had
NO senior English Arsenal at all, so FM's Arsenal roster (Saka, Rice, Raya...) had nowhere to
be placed and the Premier League fielded a Montenegrin amateur side.

A team's true country is its squad's dominant nationality — evidence, not naming. Every slot in
another country is repaired:
  1  REPOINT to a local club: a team whose name matches the slot, whose squad is dominated by
     the slot country's nationality, that no catalog slot already uses, and that beats the
     runner-up 2:1 on squad size (Argentina -> Arsenal (Sarandí), Belarus -> Arsenal Dz.)
  2  MINT the missing club when the slot's crest is a DVX logo NAMED BY AN FM CLUB ID
     (assets/dvx_logos/602.webp IS FM's Arsenal) whose nation matches the slot country and
     which no team holds — the catalog already knew the right club, only team_id was wrong
  3  otherwise REPORT and change nothing

Continental competitions (AFC CL and friends) are legitimately multi-country and are skipped.
After a repair run: sync_membership_fm.py (fills the club from FM), fill_squads.py,
rerank_slots.py, validate_db.py.

    python tools/fix_catalog_dupes.py --dry
    python tools/fix_catalog_dupes.py
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
CSVP = REPO / "allavailable columns players.csv"
CONTINENTAL = re.compile(r"\b(afc|caf|concacaf|uefa|conmebol|cl|champions|libertadores|"
                         r"sudamericana|europa|conference)\b", re.IGNORECASE)


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s: str) -> frozenset[str]:
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split() if len(w) > 1)


def cnorm(x: str) -> str:
    x = norm(x).strip()
    return {"holland": "netherlands", "korea republic": "south korea", "china pr": "china",
            "usa": "united states", "turkiye": "turkey"}.get(x, x)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)
    cat = json.loads(CAT.read_text(encoding="utf-8"))

    slots = defaultdict(list)                   # team_id -> [(country, league, slot dict)]
    used_teams = set()
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                slots[t["team_id"]].append((cnorm(co["name"]), lg, t))
                used_teams.add(t["team_id"])

    nat_of = {}
    for tid, nat, n in con.execute(
            "SELECT s.team_id, p.nationality, COUNT(*) FROM squad_members s "
            "JOIN players p ON p.id=s.player_id WHERE p.nationality IS NOT NULL "
            "GROUP BY s.team_id, p.nationality"):
        c = nat_of.setdefault(tid, Counter())
        c[cnorm(nat.split("/")[0])] += n
    home = {t: c.most_common(1)[0][0] for t, c in nat_of.items()}
    size = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    teams = dict(con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL"))

    # FM registry: club id -> (name, nation, senior rows)
    reg_name, reg_nat, reg_n = {}, {}, Counter()
    nc, bc = defaultdict(Counter), defaultdict(Counter)
    with open(CSVP, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            c = (r.get("Club ID") or "").strip()
            if c.lstrip("-").isdigit() and int(c) > 0:
                cid = int(c)
                nc[cid][(r.get("Club") or "").strip()] += 1
                bc[cid][cnorm(r.get("Based") or "")] += 1
                reg_n[cid] += 1
    for cid in nc:
        reg_name[cid] = nc[cid].most_common(1)[0][0]
        reg_nat[cid] = bc[cid].most_common(1)[0][0]
    held = {fc for (fc,) in con.execute(
        "SELECT fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL")}

    repoints, mints, unresolved = [], [], []
    for tid, places in slots.items():
        if len({c for c, _lg, _t in places}) < 2:
            continue
        true_home = home.get(tid)
        for country, lg, slot in places:
            if country == true_home or CONTINENTAL.search(lg["name"]):
                continue
            # 1: a local club of that name
            # the local club must really be THIS club, not merely share a word: its name has
            # to contain every significant token of the slot ('Arsenal' in 'Arsenal (Sarandí)')
            # — one shared token put Denmark's 'BK Union' onto Italy's 'Union Pro'
            want = frozenset(w for w in toks(slot.get("name") or teams.get(tid, ""))
                             if w not in {"fc", "bk", "sc", "ac", "cf", "cd", "sk", "if"})
            cands = [(size.get(t, 0), t) for t, nm in teams.items()
                     if t != tid and t not in used_teams and home.get(t) == country
                     and size.get(t, 0) >= 8 and want and want <= toks(nm)]
            cands.sort(reverse=True)
            if cands and (len(cands) == 1 or cands[0][0] >= 2 * cands[1][0]):
                repoints.append((tid, country, lg, slot, cands[0][1]))
                used_teams.add(cands[0][1])
                continue
            # 2: the crest names an FM club (assets/dvx_logos/<fm club id>.webp)
            m = re.search(r"dvx_logos[\\/](\d+)\.webp$", str(slot.get("logo") or ""))
            fc = int(m.group(1)) if m else None
            if fc and fc in reg_name and cnorm(reg_nat.get(fc, "")) == country \
                    and fc not in held and reg_n[fc] >= 12:
                mints.append((tid, country, lg, slot, fc))
                continue
            unresolved.append((tid, country, lg["name"], slot.get("name"),
                               f"true home {true_home}"))

    print(f"cross-country slots: repoint {len(repoints)} | mint {len(mints)} | "
          f"unresolved {len(unresolved)}")
    for tid, country, lg, slot, new in repoints:
        print(f"  REPOINT {country}/{lg['name']}: '{slot['name']}' {tid} -> {new} "
              f"'{teams[new]}' (squad {size.get(new, 0)})")
    for tid, country, lg, slot, fc in mints:
        print(f"  MINT    {country}/{lg['name']}: '{slot['name']}' was {tid} -> new team for "
              f"FM {fc} '{reg_name[fc]}' ({reg_n[fc]} rows)")
    for tid, country, lgn, nm, why in unresolved:
        print(f"  MANUAL  {country}/{lgn}: '{nm}' stays {tid} ({why})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not (repoints or mints):
        return 0

    shutil.copy2(DB, str(DB) + ".bak-precatfix")
    shutil.copy2(CAT, str(CAT) + ".bak-precatfix")
    cur = con.cursor()
    nxt = cur.execute("SELECT MAX(id) FROM teams WHERE id>=3000000 AND id<4000000").fetchone()[0]
    for tid, country, lg, slot, new in repoints:
        slot["team_id"] = new
        slot["name"] = teams[new]
        # a promoted shadow record carries no league_id; gate 4 requires every catalog club to
        # sit in a league that exists
        if lg.get("league_id"):
            cur.execute("UPDATE teams SET league_id=? WHERE id=? AND (league_id IS NULL "
                        "OR league_id NOT IN (SELECT id FROM leagues))", (lg["league_id"], new))
    for tid, country, lg, slot, fc in mints:
        nxt += 1
        cur.execute("INSERT INTO teams(id, game_team_id, is_custom, name, short_name, league_id,"
                    " budget, logo_path, team_kind) VALUES(?,?,1,?,?,?,0,?, 'first')",
                    (nxt, nxt, reg_name[fc], reg_name[fc][:20], lg.get("league_id"),
                     slot.get("logo")))
        cur.execute("INSERT OR REPLACE INTO team_identity"
                    "(team_id, fm_club_id, method, confidence) VALUES(?,?,'catalog-repair',0.95)",
                    (nxt, fc))
        slot["team_id"] = nxt
        slot["name"] = reg_name[fc]
        print(f"  minted team {nxt} '{reg_name[fc]}' in league {lg.get('league_id')}")
    con.commit()
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print("applied. Run sync_membership_fm.py, fill_squads.py, rerank_slots.py, validate_db.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
