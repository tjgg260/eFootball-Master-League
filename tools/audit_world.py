#!/usr/bin/env python3
"""
audit_world.py — the standing quirk sweep over build/master.db.

validate_db.py is the GATE: nine assertions that must hold or the build is broken. This is the
weaker, wider net beside it — things that are not structurally invalid but are still wrong to a
human reading the squad list: a Premier League club whose players are all called by surname, one
shirt number worn twice, a keeper with a striker's finishing, an fm_uid claimed by two people.

Nothing here writes. Each check prints a count and a handful of examples, so a run either comes
back quiet or hands you the next thing to fix. Sections are numbered so a fix can cite one.

    python tools/audit_world.py            # everything
    python tools/audit_world.py 3 7        # only those checks
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
sys.path.insert(0, str(REPO / "tools"))

CAREER = (20_000_000, 700_000_000)
TOP_TIER = 1


def toks(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.sub(r"[^a-z ]", " ", s).split() if t]


class Audit:
    def __init__(self, con, cat):
        self.con, self.cat = con, cat
        self.findings = 0
        self.incat = {t["team_id"] for co in cat["countries"] for lg in co["leagues"]
                      for t in lg["teams"]}
        self.top = {t["team_id"] for co in cat["countries"] for lg in co["leagues"]
                    if lg.get("tier") == TOP_TIER for t in lg["teams"]}
        self.tname = dict(con.execute("SELECT id, name FROM teams"))

    def report(self, num, title, bad, unit, examples):
        mark = "ok  " if not bad else "QUIRK"
        print(f"{mark} {num:>2}  {title}: {bad:,} {unit}")
        for e in examples[:6]:
            print(f"        {e}")
        if bad:
            self.findings += 1

    # 1 --------------------------------------------------------------- names
    def names(self):
        rows = [(p, n, t) for p, n, t in self.con.execute(
            "SELECT p.id, p.name, s.team_id FROM players p JOIN squad_members s "
            "ON s.player_id=p.id WHERE p.superseded_by IS NULL")]
        # 'Fabio' and 'Ramalho' at Fluminense are not truncations — Brazilian mononyms are the
        # player's actual name. It is only a quirk when the export has more name than we show.
        fm_name = {}
        with open(REPO / "allavailable columns players.csv", encoding="cp1252",
                  errors="replace", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                u = (r.get("Unique ID") or "").strip()
                if u.isdigit():
                    fm_name[int(u)] = (r.get("Name") or "").strip()
        fuller = {pid: fm_name.get(uid, "") for pid, uid in self.con.execute(
            "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL")}
        bare = [(p, n, t) for p, n, t in rows
                if t in self.top and len(toks(n)) < 2
                and len(toks(fuller.get(p, ""))) > 1]
        self.report(1, "top-division players shown by surname when the export has more",
                    len(bare), "players",
                    [f"{n!r} at {self.tname.get(t)!r} (FM: {fuller.get(p)!r})" for p, n, t in bare])
        junk = [(p, n) for p, n, _t in rows
                if not (n or "").strip() or re.search(r"[0-9]{2,}|\?\?|_", n or "")]
        self.report(2, "squadded players with an unusable name", len(junk), "players",
                    [f"id {p}: {n!r}" for p, n in junk])

    # 3 ------------------------------------------------------------- shirts
    def shirts(self):
        dup = []
        for tid, num, n in self.con.execute(
                "SELECT team_id, squad_number, COUNT(*) FROM squad_members "
                "WHERE squad_number IS NOT NULL GROUP BY team_id, squad_number HAVING COUNT(*)>1"):
            if tid in self.incat:
                dup.append((tid, num, n))
        clubs = {d[0] for d in dup}
        self.report(3, "catalog clubs with a shirt number worn twice", len(clubs), "clubs",
                    [f"{self.tname.get(t)!r} wears #{num} x{n}" for t, num, n in dup])

    # 4 --------------------------------------------------------- squad shape
    def shape(self):
        bad_gk, no_side, thin = [], [], []
        for tid in self.incat:
            xi = self.con.execute(
                "SELECT p.position FROM squad_members s JOIN players p ON p.id=s.player_id "
                "WHERE s.team_id=? AND s.slot<=10 ORDER BY s.slot", (tid,)).fetchall()
            xi = [r[0] for r in xi]
            if len(xi) < 11:
                thin.append(tid)
                continue
            if xi[0] != "GK" or xi.count("GK") != 1:
                bad_gk.append(tid)
            if "LB" not in xi or "RB" not in xi:
                no_side.append(tid)
        self.report(4, "catalog XIs without exactly one keeper in slot 0", len(bad_gk), "clubs",
                    [f"{self.tname.get(t)!r}" for t in bad_gk])
        self.report(5, "catalog XIs missing a left or right back", len(no_side), "clubs",
                    [f"{self.tname.get(t)!r}" for t in no_side])
        self.report(6, "catalog clubs that cannot field eleven", len(thin), "clubs",
                    [f"{self.tname.get(t)!r}" for t in thin])

    # 7 ----------------------------------------------------------- identity
    def identity(self):
        # Career copies and the curated overlay are render material for a save, not world records:
        # the career Arsenal deliberately holds its own Declan Rice beside the world's one.
        live = ("p.superseded_by IS NULL AND NOT (p.id>=20000000 AND p.id<700000000) "
                "AND NOT (p.id>=45000000000 AND p.id<46000000000)")
        dup_uid = list(self.con.execute(
            f"SELECT pi.fm_uid, COUNT(*), MIN(p.name) FROM player_identity pi JOIN players p "
            f"ON p.id=pi.player_id WHERE pi.fm_uid IS NOT NULL AND {live} "
            f"GROUP BY pi.fm_uid HAVING COUNT(*)>1"))
        self.report(7, "one FM uid claimed by several live players", len(dup_uid), "uids",
                    [f"uid {u} x{n} ({nm!r})" for u, n, nm in dup_uid])
        dup_ef = list(self.con.execute(
            f"SELECT pi.ef_pid, COUNT(*), MIN(p.name) FROM player_identity pi JOIN players p "
            f"ON p.id=pi.player_id JOIN squad_members s ON s.player_id=p.id "
            f"WHERE pi.ef_pid IS NOT NULL AND {live} "
            f"GROUP BY pi.ef_pid HAVING COUNT(*)>1"))
        self.report(8, "one eFootball record claimed by several squadded players", len(dup_ef),
                    "records", [f"ef {e} x{n} ({nm!r})" for e, n, nm in dup_ef])

    # 9 --------------------------------------------------------------- ages
    def ages(self):
        # 50, not 45: FM lists the odd playing veteran in a minor league (a 55-year-old at B68
        # Toftir), and those are the source's own numbers, not corruption.
        odd = list(self.con.execute(
            "SELECT p.id, p.name, p.age FROM players p JOIN squad_members s ON s.player_id=p.id "
            "WHERE p.superseded_by IS NULL AND (p.age<15 OR p.age>50 OR p.age IS NULL)"))
        self.report(9, "squadded players with an impossible or missing age", len(odd), "players",
                    [f"{n!r} age {a}" for _p, n, a in odd])

    # 10 ------------------------------------------------------- attributes
    def attributes(self):
        from ability_bits import ABILITY_BITS
        ph = ",".join("?" * len(ABILITY_BITS))
        flat = list(self.con.execute(
            f"SELECT a.player_id, MIN(p.name), COUNT(DISTINCT a.value) FROM player_attributes a "
            f"JOIN players p ON p.id=a.player_id JOIN squad_members s ON s.player_id=p.id "
            f"WHERE a.attribute IN ({ph}) AND p.superseded_by IS NULL "
            f"GROUP BY a.player_id HAVING COUNT(DISTINCT a.value)<=2", tuple(ABILITY_BITS)))
        self.report(10, "squadded players whose abilities are all one or two values", len(flat),
                    "players", [f"{n!r} (id {p})" for p, n, _c in flat])
        keepers = list(self.con.execute(
            "SELECT p.id, p.name, a.value FROM players p JOIN squad_members s ON s.player_id=p.id "
            "JOIN player_attributes a ON a.player_id=p.id AND a.attribute='finishing' "
            "WHERE p.position='GK' AND p.superseded_by IS NULL AND a.value>=70"))
        self.report(11, "keepers with a striker's finishing", len(keepers), "players",
                    [f"{n!r} finishing {v}" for _p, n, v in keepers])

    # 12 ---------------------------------------------------------- ratings
    def ratings(self):
        top = list(self.con.execute(
            "SELECT p.name, p.overall_rating, t.name FROM players p "
            "JOIN squad_members s ON s.player_id=p.id JOIN teams t ON t.id=s.team_id "
            "WHERE p.superseded_by IS NULL AND p.overall_rating>=84 AND NOT (p.id>=? AND p.id<?) "
            "ORDER BY p.overall_rating DESC", CAREER))
        print(f"ok  12  the world's best players ({len(top)} rated 84+, eFootball's own ceiling) — check these read right:")
        for n, r, t in top[:12]:
            print(f"        {r}  {n[:26]:26} {t}")
        # eFootball's export carries two placeholder rows — every ability 95, overall 116, which
        # the game itself clamps to 99. They are not players and there is nothing to repair in
        # them; they are named here so a run does not keep re-reporting them as a fixable quirk.
        placeholders = [f"{n!r} ({r}) — eFootball's own placeholder row" for n, r in
                        self.con.execute("SELECT name, overall_rating FROM players "
                                         "WHERE overall_rating>=99 AND id<20000000")]
        for line in placeholders:
            print(f"        note: {line}")
        free = self.con.execute(
            "SELECT COUNT(*) FROM players p LEFT JOIN squad_members s ON s.player_id=p.id "
            "WHERE s.player_id IS NULL AND p.superseded_by IS NULL AND p.overall_rating>=80 "
            "AND p.overall_rating<99 AND NOT (p.id>=? AND p.id<?)", CAREER).fetchone()[0]
        ex = [f"{n!r} ({r})" for n, r in self.con.execute(
            "SELECT p.name, p.overall_rating FROM players p LEFT JOIN squad_members s "
            "ON s.player_id=p.id WHERE s.player_id IS NULL AND p.superseded_by IS NULL "
            "AND p.overall_rating>=80 AND p.overall_rating<99 AND NOT (p.id>=? AND p.id<?) "
            "ORDER BY p.overall_rating DESC LIMIT 6", CAREER)]
        self.report(13, "players rated 80+ with no club at all", free, "players", ex)

    # 14 ------------------------------------------------------------- clubs
    def clubs(self):
        nolink = [t for t in self.incat if not self.con.execute(
            "SELECT 1 FROM team_identity WHERE team_id=? AND fm_club_id IS NOT NULL",
            (t,)).fetchone()]
        self.report(14, "catalog clubs not linked to an FM club", len(nolink), "clubs",
                    [f"{self.tname.get(t)!r}" for t in nolink])
        sizes = Counter()
        for co in self.cat["countries"]:
            for lg in co["leagues"]:
                if lg.get("tier") == TOP_TIER and not (8 <= len(lg["teams"]) <= 24):
                    sizes[(co["name"], lg["name"])] = len(lg["teams"])
        self.report(15, "top divisions with an implausible club count", len(sizes), "leagues",
                    [f"{c} / {l}: {n}" for (c, l), n in sizes.items()])

    # 16 -------------------------------------------------------------- faces
    def faces(self):
        n, have = self.con.execute(
            "SELECT COUNT(*), SUM(COALESCE(p.real_face_path, p.portrait_path) IS NOT NULL) "
            "FROM players p JOIN squad_members s ON s.player_id=p.id "
            "WHERE s.team_id IN (%s) AND p.superseded_by IS NULL"
            % ",".join(str(t) for t in list(self.top)[:400] or [0])).fetchone()
        pct = 100.0 * (have or 0) / max(n, 1)
        print(f"ok  16  top-division face coverage: {have:,}/{n:,} ({pct:.0f}%)")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    want = {a for a in sys.argv[1:] if a.isdigit()}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    a = Audit(con, json.loads(CAT.read_text(encoding="utf-8")))
    checks = [("1", a.names), ("3", a.shirts), ("4", a.shape), ("7", a.identity),
              ("9", a.ages), ("10", a.attributes), ("12", a.ratings), ("14", a.clubs),
              ("16", a.faces)]
    for num, fn in checks:
        if not want or num in want:
            fn()
    print(f"\n{a.findings} checks found something.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
