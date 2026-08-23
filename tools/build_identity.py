#!/usr/bin/env python3
"""
build_identity.py — the IDENTITY SPINE (docs/database-blueprint.md). Every persistent player and
team is resolved across sources ONCE, here, and the mapping is persisted — every later join
(faces, logos, market, staff, membership refresh) is then EXACT by key, never fuzzy again.

player_identity: player_id -> kind + fm_uid + ef_pid, with method/confidence per link.
  fm_uid comes from, in order of certainty:
    'id'    the row IS the FM import (id = 10B + uid)
    'face'  the row wears a sortitoutsi face (face_<uid>.webp is NAMED by FM uid)
    'name'  unique full-name + nationality match against the FM rows (age ±4 guard)
  ef_pid likewise: 'id' for native rows, 'name' for a unique match to a native record.
team_identity: team_id -> fm_club_id (via fm_clubs name+country), sportsdb_id / footballdata_id
  (via the fetched API snapshots in build/).

Career copies (20M-700M) are ephemeral render material and are EXCLUDED. Rebuildable at any time:
    python tools/build_identity.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

STOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de", "club",
        "the", "afc", "rcd", "sd", "cp", "und", "sv", "vfl", "vfb", "tsg", "fsv", "us", "acf",
        "ca", "kf", "fk", "nk", "if", "bk", "sk", "ks"}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s: str) -> frozenset[str]:
    # single-letter fragments ('A.C.' -> 'a','c') are noise that sinks real matches
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split()
                     if len(w) > 1 and w not in STOP)


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(s))


def pident(nm, nat) -> tuple:
    return (tuple(sorted(re.sub(r"[^a-z ]", " ", norm(nm)).split())),
            (nat or "").split("/")[0].strip().lower())


def kind_of(pid: int) -> str | None:
    if 20_000_000 <= pid < 700_000_000:
        return None                          # career copy — ephemeral, not spine material
    if pid < 16_700_000:
        return "ef"
    if pid < 10_000_000_000:
        return "rfs"
    if pid < 45_000_000_000:
        return "fm"
    if pid < 50_000_000_000:
        return "curated"
    return "generated"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS player_identity(
            player_id  INTEGER PRIMARY KEY,
            kind       TEXT NOT NULL,           -- ef | rfs | fm | curated | generated
            fm_uid     INTEGER,                 -- the ecosystem's universal key
            ef_pid     INTEGER,                 -- the native record for eFootball-truth fields
            fm_method  TEXT, ef_method TEXT,    -- id | face | name
            confidence REAL NOT NULL DEFAULT 1.0);
        CREATE INDEX IF NOT EXISTS ix_pident_fm ON player_identity(fm_uid);
        CREATE INDEX IF NOT EXISTS ix_pident_ef ON player_identity(ef_pid);
        CREATE TABLE IF NOT EXISTS team_identity(
            team_id          INTEGER PRIMARY KEY,
            fm_club_id       INTEGER,
            sportsdb_id      INTEGER,
            footballdata_id  INTEGER,
            method           TEXT,
            confidence       REAL NOT NULL DEFAULT 1.0);
        CREATE INDEX IF NOT EXISTS ix_tident_fm ON team_identity(fm_club_id);
        DELETE FROM player_identity;
        DELETE FROM team_identity;
    """)

    # ---------------- players ----------------
    rows = con.execute("SELECT id, name, nationality, age, real_face_path FROM players").fetchall()
    face_pat = re.compile(r"face_(\d+)\.webp$", re.I)

    fm_by_ident: dict[tuple, list[tuple[int, int | None]]] = defaultdict(list)  # ident -> [(uid, age)]
    ef_by_ident: dict[tuple, list[tuple[int, int | None]]] = defaultdict(list)  # ident -> [(pid, age)]
    for pid, nm, nat, age, _f in rows:
        k = kind_of(pid)
        if k == "fm":
            fm_by_ident[pident(nm, nat)].append((pid - 10_000_000_000, age))
        elif k == "ef":
            ef_by_ident[pident(nm, nat)].append((pid, age))

    out, stats = [], Counter()
    for pid, nm, nat, age, face in rows:
        k = kind_of(pid)
        if k is None:
            continue
        fm_uid = ef_pid = None
        fm_m = ef_m = None
        conf = 1.0
        if k == "fm":
            fm_uid, fm_m = pid - 10_000_000_000, "id"
        elif face and (m := face_pat.search(face)):
            fm_uid, fm_m = int(m.group(1)), "face"
        if k == "ef":
            ef_pid, ef_m = pid, "id"
        key = pident(nm, nat)
        if fm_uid is None and k in ("ef", "rfs", "curated"):
            cands = fm_by_ident.get(key, [])
            near = {u for u, a in cands
                    if age is None or a is None or abs(a - age) <= 4}
            if len(near) == 1:
                fm_uid, fm_m, conf = next(iter(near)), "name", 0.85
        if ef_pid is None and k in ("fm", "rfs", "curated"):
            cands = ef_by_ident.get(key, [])
            near = {p for p, a in cands
                    if age is None or a is None or abs(a - age) <= 4}
            if len(near) == 1:
                ef_pid, ef_m, conf = next(iter(near)), "name", min(conf, 0.85)
        out.append((pid, k, fm_uid, ef_pid, fm_m, ef_m, conf))
        stats[k] += 1
        if fm_uid is not None:
            stats[f"fm:{fm_m}"] += 1
        if ef_pid is not None:
            stats[f"ef:{ef_m}"] += 1
    con.executemany("INSERT OR REPLACE INTO player_identity VALUES(?,?,?,?,?,?,?)", out)

    # ---------------- teams ----------------
    fm_clubs, fm_rep = {}, {}
    try:
        for uid, nm, nat, rep in con.execute(
                "SELECT uid, name, nation, COALESCE(reputation,0) FROM fm_clubs WHERE name IS NOT NULL"):
            fm_clubs[uid] = (nm, (nat or "").lower())
            fm_rep[uid] = rep
    except sqlite3.OperationalError:
        pass
    # -- team country: catalog (authoritative) -> team's league -> squad-dominant nationality.
    # Squad nationality ALONE poisoned the first build (Liverpool's multinational squad made its
    # "country" not-England, so FM's Liverpool couldn't claim it).
    def cnorm(x: str) -> str:
        x = (x or "").strip().lower()
        return {"holland": "netherlands", "korea republic": "south korea", "china pr": "china",
                "usa": "united states", "u.s.a.": "united states", "turkiye": "turkey",
                "republic of ireland": "ireland", "bosnia & herzegovina": "bosnia",
                "bosnia and herzegovina": "bosnia"}.get(x, x)

    cat_country, league_country, country_names = {}, {}, set()
    catp = REPO / "build" / "catalog.json"
    if catp.exists():
        cat = json.loads(catp.read_text(encoding="utf-8"))
        for co in cat["countries"]:
            cn = cnorm(co["name"])
            country_names.add(cn)
            for lg in co["leagues"]:
                if lg.get("league_id"):
                    league_country[lg["league_id"]] = cn
                for t in lg["teams"]:
                    cat_country[t["team_id"]] = cn
    tleague = dict(con.execute("SELECT id, league_id FROM teams"))
    cc: dict[int, Counter] = defaultdict(Counter)
    for tid, nat in con.execute("SELECT s.team_id, p.nationality FROM squad_members s "
                                "JOIN players p ON p.id=s.player_id WHERE p.nationality IS NOT NULL"):
        cc[tid][cnorm(nat.split("/")[0])] += 1
    squad_country = {t: c.most_common(1)[0][0] for t, c in cc.items()}

    def country_of(tid):
        return cat_country.get(tid) or league_country.get(tleague.get(tid)) or squad_country.get(tid)

    teams = dict(con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''"))
    squad_sz = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    for uid, (nm, nation) in list(fm_clubs.items()):
        fm_clubs[uid] = (nm, cnorm(nation))
        if nation:
            country_names.add(cnorm(nation))

    # -- national-team guard: a row NAMED like a country (or U-age side) never links to a club.
    # ('Malta' <- Austria's 'SV Malta' was a real poisoning.)
    def is_national(tid) -> bool:
        nmn = norm(teams[tid]).strip().lower()
        base = re.sub(r"\s+u\d\d?$", "", nmn)
        return base in country_names or bool(re.search(r"\bu\d\d\b", nmn))

    by_lkey = defaultdict(list)
    tok_index = defaultdict(set)
    pre_index = defaultdict(set)             # 4-char prefix -> teams (Inter finds Internazionale)
    for tid, nm in teams.items():
        if is_national(tid) or 800_000 <= tid < 900_000:   # career copies are ephemeral render
            continue                                        # material — never spine-matched
        by_lkey[lkey(nm)].append(tid)
        for w in toks(nm):
            tok_index[w].add(tid)
            if len(w) >= 4:
                pre_index[w[:4]].add(tid)

    # -- prefix-aware token match, extension capped at 4 chars: Milan~Milano, Hamburg~Hamburger,
    # Lyon~Lyonnais — but NOT Inter~Intercampania (an unbounded prefix rule scored two Italian
    # amateur clubs a perfect 1.0 against FM's 'Inter' and the ambiguity guard killed the match).
    def tok_eq(x, y):
        # extension capped at TWO chars: Milan~Milano, Hamburg~Hamburger — but never
        # Milan~Milanese (+3) or Inter~Intercampania, which are different clubs entirely.
        return x == y or (len(x) >= 4 and len(y) >= 4 and abs(len(x) - len(y)) <= 2
                          and (x.startswith(y) or y.startswith(x)))

    # cross-border clubs: FM records the club's NATION (Cardiff/Swansea = Wales) while they play in
    # another country's pyramid (England). Compatibility groups instead of a hard reject.
    _XB = [{"england", "wales", "scotland", "northern ireland"}, {"france", "monaco"},
           {"switzerland", "liechtenstein"}, {"united states", "canada"},
           {"spain", "andorra"}, {"italy", "san marino"}]

    def compatible(a, b):
        return a == b or any(a in g and b in g for g in _XB)

    def name_score(want: frozenset, have_key: str, tk: frozenset) -> float:
        if not want or not tk:
            return 0.0
        m = sum(1 for x in want if any(tok_eq(x, y) for y in tk))
        if m == 0:
            return 0.0
        if m == len(want) == len(tk):
            return 1.0                       # token-equal (incl. exact lkey)
        if m == len(want) or m == len(tk):
            return 0.8                       # one side subset (TSG Hoffenheim ⊆ TSG 1899 Hoffenheim)
        return 0.6 * m / (len(want) + len(tk) - m)

    # -- API ids FIRST (authoritative league snapshots): they anchor the fm matching below —
    # a candidate the APIs recognise outranks a same-named fragment (the catalog itself proved
    # poisonable: Serie A carried 'FC Milanese' where AC Milan belongs).
    api: dict[int, dict] = defaultdict(dict)
    sdb = REPO / "build" / "sportsdb_data.json"
    fdj = REPO / "build" / "league_data.json"

    def match_api(name, country, id_val, field):
        cand = [t for t in by_lkey.get(lkey(name), [])
                if not country_of(t) or not country or compatible(country_of(t), cnorm(country))]
        if len(cand) == 1:
            api[cand[0]][field] = id_val
    if sdb.exists():
        for k, comp in json.loads(sdb.read_text(encoding="utf-8")).items():
            country = k.split("|", 1)[0]
            for t in comp.get("teams", []):
                if t.get("name") and t.get("badge_id"):
                    match_api(t["name"], country, int(t["badge_id"]), "sportsdb_id")
    if fdj.exists():
        for comp in json.loads(fdj.read_text(encoding="utf-8")).values():
            for t in comp.get("teams", []):
                if t.get("name") and t.get("crest_id"):
                    try:
                        match_api(t["name"], comp.get("country", ""), int(t["crest_id"]), "footballdata_id")
                    except (TypeError, ValueError):
                        pass

    # -- global greedy: score every plausible (fm club, team) pair, best pairs claim first.
    pairs, review = [], []
    for uid, (nm, nation) in fm_clubs.items():
        want = toks(nm)
        cand = set(by_lkey.get(lkey(nm), ()))
        for w in want:
            cand |= tok_index.get(w, set())
            if len(w) >= 4:
                cand |= pre_index.get(w[:4], set())
        scored = []
        fm_reserve = bool(re.search(r"\b(ii|iii|b|reserves?|u\d\d?|acad)\b", norm(nm)))
        for t in cand:
            tc = country_of(t)
            if nation and tc and not compatible(tc, nation):
                continue                     # country disagreement is a hard reject
            # a senior FM club never links a reserve/B/youth row, and vice versa
            # ('TSG Hoffenheim' was tying with 'TSG 1899 Hoffenheim II' into a dead review)
            if bool(re.search(r"\b(ii|iii|b|reserves?|u\d\d?|acad)\b", norm(teams[t]))) != fm_reserve:
                continue
            s = name_score(want, lkey(nm), toks(teams[t]))
            if s < 0.55:
                continue
            if not tc or not nation:
                # Unknown team country: only a NAME-PERFECT match may cross without country
                # confirmation ('Rivers FC' Canada reached Paraguay's River Plate on 0.65 fuzzy).
                if s < 0.99:
                    continue
                s -= 0.15                    # allowed, but never beats a country-confirmed pair
            # the CATALOG record is the canonical club — it outranks its eF/RFS twins on a tie
            if t in api:
                s += 0.1                     # authoritative league data recognises this record
            scored.append((s, 1 if t in cat_country else 0, squad_sz.get(t, 0), t))
        scored.sort(reverse=True)
        import os
        if str(uid) in os.environ.get("ML_DEBUG_FM_UID", "").split(","):
            print(f"DEBUG fm {uid} '{nm}' nation={nation!r} want={sorted(want)} "
                  f"cand={len(cand)} scored={[(round(s,2),c,t,teams[t]) for s,c,_z,t in scored[:5]]}")
        if not scored:
            continue
        top = scored[0]
        # the CANONICAL (catalog) record wins over a same-country fragment scoring slightly higher:
        # FM 'Swansea' must land on catalog 'Swansea City', not the leftover 'Swansea' split.
        if top[1] == 0:
            for alt in scored[1:4]:
                tc_a, tc_t = country_of(alt[3]), country_of(top[3])
                if alt[1] == 1 and top[0] - alt[0] <= 0.2 and (
                        not tc_a or not tc_t or compatible(tc_a, tc_t)):
                    top = alt
                    break
        # ambiguity: a same-country rival within a hair, same catalog standing, and a squad of
        # comparable size -> review, no claim. A rival with a far smaller squad is just a fragment
        # of the same club — the fuller record wins (River Plate's duplicate rows).
        rivals = [x for x in scored if x[3] != top[3]]
        if rivals:
            r0 = rivals[0]
            if (top[0] - r0[0] < 0.05 and country_of(r0[3]) == country_of(top[3])
                    and r0[1] == top[1] and r0[2] * 1.5 + 2 > top[2]):
                review.append((uid, nm, nation,
                               [(round(s, 2), t, teams[t]) for s, _c, _z, t in scored[:3]]))
                continue
        # claim order: match quality, then the FM club's REPUTATION — so when two same-country FM
        # clubs both fit a record perfectly ('Liverpool' vs 'AFC Liverpool'), the real one wins it.
        # Each club bids its top THREE candidates: the loser of a contested record falls through to
        # its own (AFC Liverpool ends up on the real AFC Liverpool row, not linkless).
        for s, _c, sz, t in scored[:3]:
            pairs.append((s, fm_rep.get(uid, 0), sz, uid, t))
    pairs.sort(reverse=True)

    # -- SQUAD-CONTENT VOTES trump every name heuristic. The Genie per-player export carries the
    # FM CLUB ID, so a team's already-identified players vote for their club by pure id — this is
    # how unlicensed FM names finally resolve ('Casciavit' IS A.C. Milan because Leão and Maignan
    # say so), immune to every name trap above.
    tid_fm: dict[int, tuple[int, str, float]] = {}
    used_fm: set[int] = set()
    votes_src = REPO / "allavailable columns players.csv"
    if votes_src.exists():
        import csv as _csv
        import io
        uid2club = {}
        with open(votes_src, encoding="cp1252", errors="replace", newline="") as f:
            for r in _csv.DictReader(f, delimiter=";"):
                u, c = (r.get("Unique ID") or "").strip(), (r.get("Club ID") or "").strip()
                if u.lstrip("-").isdigit() and c.lstrip("-").isdigit() and int(c) > 0:
                    uid2club[int(u)] = int(c)
        pid_fm = {pid: fu for pid, _k, fu, _e, _fm, _em, _c in out if fu is not None}
        team_votes: dict[int, Counter] = defaultdict(Counter)
        for tid, pid in con.execute("SELECT team_id, player_id FROM squad_members"):
            if tid not in teams:
                continue
            fu = pid_fm.get(pid)
            if fu is not None and fu in uid2club:
                team_votes[tid][uid2club[fu]] += 1
        voted = []
        for tid, c in team_votes.items():
            (club, n), total = c.most_common(1)[0], sum(c.values())
            if n >= 5 and n / total >= 0.6 and club in fm_clubs and club not in used_fm:
                voted.append((n, tid, club))
        voted.sort(reverse=True)             # strongest evidence claims first
        def _resv(s):
            return bool(re.search(r"\b(ii|iii|b|reserves?|u\d\d?|acad|youth)\b", norm(s)))
        for _n, tid, club in voted:
            if tid in tid_fm or club in used_fm:
                continue
            if _resv(teams[tid]) != _resv(fm_clubs[club][0]):
                continue                     # a senior fm club never claims a U20/B row by votes
            tid_fm[tid] = (club, "squad", 0.95)
            used_fm.add(club)
        print(f"squad-content votes: {len(tid_fm):,} teams linked by their players' club ids")
    for s, _rep, _sz, uid, tid in pairs:
        if uid in used_fm or tid in tid_fm:
            continue
        tid_fm[tid] = (uid, "exact" if s >= 0.99 else "subset" if s >= 0.75 else "fuzzy", round(s, 2))
        used_fm.add(uid)
    if review:
        import csv
        with open(REPO / "build" / "identity_team_review.csv", "w", newline="",
                  encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["fm_uid", "fm_name", "fm_nation", "candidates"])
            for uid, nm, nation, cands in review:
                w.writerow([uid, nm, nation, "; ".join(f"{s} {t} {n}" for s, t, n in cands)])
        print(f"ambiguous fm clubs -> build/identity_team_review.csv: {len(review):,}")

    trows = []
    for tid in teams:
        fm = tid_fm.get(tid)
        a = api.get(tid, {})
        if fm or a:
            trows.append((tid, fm[0] if fm else None, a.get("sportsdb_id"),
                          a.get("footballdata_id"), fm[1] if fm else "api",
                          fm[2] if fm else 0.9))
    con.executemany("INSERT OR REPLACE INTO team_identity VALUES(?,?,?,?,?,?)", trows)
    con.commit()

    print("player_identity:", dict(stats))
    linked = con.execute("SELECT COUNT(*) FROM player_identity WHERE fm_uid IS NOT NULL").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM player_identity").fetchone()[0]
    print(f"players in spine: {tot:,} | with FM identity: {linked:,}")
    print(f"teams in spine: {len(trows):,} | with fm_club_id: {len(tid_fm):,} | "
          f"with API id: {len(api):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
