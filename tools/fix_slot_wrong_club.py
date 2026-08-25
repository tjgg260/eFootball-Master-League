#!/usr/bin/env python3
"""
fix_slot_wrong_club.py — the Premier League's Arsenal was FK Arsenal Tivat of Montenegro.

build_catalog resolves an RFS club name onto a master.db record and checks the country, but its
country check has a hole: a candidate whose country actively disagrees is dropped only when there
is ANOTHER candidate to fall back on. A lone wrong-country record is accepted. So the Premier
League slot named 'Arsenal FC' took team 3000001 — eighteen Montenegrins, Bozinovic in goal — while
the real Arsenal (Saka, Saliba, Rice, Raya) sat at team 3131037 in no league at all. The same hole
put a Syrian Al-Hilal in the Saudi Pro League ahead of the record holding Theo Hernandez and
Darwin Nunez.

Nationality alone cannot decide this: Wellington Phoenix really is a New Zealand club in Australia's
A-League, and Swansea and Newport really do play in England. The squad's FM CLUB does decide it —
ask which club each player belongs to in the FM export, take the majority, and read that club's
nation. A slot is wrong only when its squad belongs to a club in another country AND a same-named
record whose squad belongs to a club in the RIGHT country exists outside the catalog. Both
conditions together leave no room for a judgement call.

The displaced record keeps its players and its data; it loses the league slot and takes the name FM
gives the club its squad actually plays for, so it stops advertising itself as someone else.

    python tools/fix_slot_wrong_club.py --dry
    python tools/fix_slot_wrong_club.py
then: rerank_slots.py, validate_db.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
MEMBER = REPO / "allavailable columns players.csv"

sys.path.insert(0, str(REPO / "tools"))
from build_catalog import club_key, cnorm, is_youth   # noqa: E402

MIN_SQUAD = 18                       # a replacement must be able to field a legal catalog club


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=300)
    cur = con.cursor()
    cat = json.loads(CAT.read_text(encoding="utf-8"))

    fmc = {u: (n, nat) for u, n, nat in con.execute("SELECT uid, name, nation FROM fm_clubs")}
    uid2club = {}
    with open(MEMBER, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u, c = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip()
            if u.isdigit() and c.isdigit():
                uid2club[int(u)] = int(c)
    pl2uid = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    names = dict(con.execute("SELECT id, name FROM teams"))
    logo = dict(con.execute("SELECT id, logo_path FROM teams"))
    stats = {t: (n, a) for t, n, a in con.execute(
        "SELECT s.team_id, COUNT(*), AVG(COALESCE(p.overall_rating,55)) FROM squad_members s "
        "JOIN players p ON p.id=s.player_id GROUP BY s.team_id")}
    faces = dict(con.execute(
        "SELECT s.team_id, SUM(COALESCE(p.real_face_path, p.portrait_path) IS NOT NULL) "
        "FROM squad_members s JOIN players p ON p.id=s.player_id GROUP BY s.team_id"))
    gks = dict(con.execute(
        "SELECT s.team_id, SUM(p.position='GK') FROM squad_members s JOIN players p "
        "ON p.id=s.player_id GROUP BY s.team_id"))

    def vote(tid):
        c = Counter()
        for (p,) in con.execute("SELECT player_id FROM squad_members WHERE team_id=?", (tid,)):
            cl = uid2club.get(pl2uid.get(p))
            if cl:
                c[cl] += 1
        if not c:
            return None
        top, n = c.most_common(1)[0]
        return top if n >= 5 and n >= 0.4 * sum(c.values()) else None

    incat = {t["team_id"] for co in cat["countries"] for lg in co["leagues"] for t in lg["teams"]}
    pool = defaultdict(list)
    for t, n in names.items():
        if not n or is_youth(n):
            continue
        if 800_000 <= t < 1_000_000 or 9_000_000 <= t < 9_200_000:
            continue                                  # career bands are never world clubs
        if stats.get(t, (0,))[0] < MIN_SQUAD or (gks.get(t) or 0) < 2 or t in incat:
            continue
        pool[club_key(n)].append(t)

    fixes = []
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                tid = t["team_id"]
                v = vote(tid)
                if v is None or cnorm(fmc.get(v, ("", ""))[1]) == cnorm(co["name"]):
                    continue
                key = club_key(names.get(tid, ""))
                cands = []
                for k, ts in pool.items():
                    if not (k == key or k.startswith(key + " ") or key.startswith(k + " ")):
                        continue
                    for a in ts:
                        av = vote(a)
                        if av is not None and cnorm(fmc.get(av, ("", ""))[1]) == cnorm(co["name"]):
                            cands.append(a)
                if len(cands) == 1:
                    fixes.append((co["name"], lg, t, tid, cands[0], v))

    print(f"catalog slots holding a club from another country, with one clear replacement: "
          f"{len(fixes)}")
    for cname, lg, _t, old, new, v in fixes:
        print(f"   {cname} / {lg['name']}: {names.get(old)!r} ({old}, really "
              f"{fmc.get(v, ('?',))[0]!r}) -> {names.get(new)!r} ({new}, "
              f"squad {stats.get(new, (0,))[0]})")
    if dry:
        print("--dry: nothing written.")
        return 0
    if not fixes:
        return 0

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(DB, str(DB) + ".bak-preslot")
    shutil.copy2(CAT, str(CAT) + ".bak-preslot")
    cur.execute("BEGIN")
    for _cname, lg, t, old, new, v in fixes:
        t["team_id"] = new
        t["name"] = names.get(new)
        t["squad"] = stats.get(new, (0, 55))[0]
        t["rating"] = round(stats.get(new, (0, 55))[1], 1)
        t["faces"] = int(faces.get(new) or 0)
        t["logo"] = logo.get(new)
        cur.execute("UPDATE teams SET league_id=? WHERE id=?", (lg["league_id"], new))
        # The displaced record is usually a real club somewhere else — team 3000001 is
        # Montenegro's Arsenal and is listed in the 1.CFL. Only cut its league loose if no
        # catalog league still lists it.
        still = [x for co2 in cat["countries"] for lg2 in co2["leagues"]
                 for x in lg2["teams"] if x["team_id"] == old]
        if not still:
            cur.execute("UPDATE teams SET league_id=NULL WHERE id=?", (old,))
        real = fmc.get(v, (None,))[0]
        if real and real != names.get(old):
            cur.execute("UPDATE teams SET name=? WHERE id=?", (real, old))
            for x in still:
                x["name"] = real          # its other league must not keep advertising the old name
    con.commit()
    CAT.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"applied. {len(fixes)} league slot(s) now hold the right club.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
