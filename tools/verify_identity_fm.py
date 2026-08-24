#!/usr/bin/env python3
"""
verify_identity_fm.py — re-verify every team_identity.fm_club_id against the FM export CSV,
THE membership source of truth (owner ruling 2026-08-23, memory fm-export-provenance).

Why this exists: build_identity.py linked teams before club consolidation and by fm_clubs
names, which let nickname clubs land on dead fragments — our catalog Wolverhampton Wanderers
(3000110) carried FM 223692 'Wanderers F.C.' (a club with ZERO rows in the export) while the
real Wolves (FM 740) sat on the 4M-band shadow team its imported players were parked in.
sync_membership_fm.py routes real squads by these links; a wrong link is a wrong transfer.

The registry is built from the export itself: Club ID -> name (mode of Club), nation (mode of
Based — the club's country, NOT the players' Nation), senior roster (Squad without a U15-U23
suffix). fm_clubs keeps only an alias role.

Evidence order (established rules, build_identity.py precedent):
  1  UID SQUAD VOTES  — a team's members vote by player_identity.fm_uid -> export Club ID
     (n >= 5, >= 60% majority, senior/reserve guard). CATALOG teams claim first: the catalog
     record is the canonical club and must be the destination membership sync fills.
  2  ROSTER-SURNAME VOTES — catalog teams whose squads carry no FM-linked players (RFS-only
     squads) are matched by squad surnames against club senior rosters. This is still squad
     content, just by name: catalog Wolves' RFS 'Bellegarde/Mosquera/Sá' squad IS FM 740's
     roster. Thresholds: >= 6 matched players, >= 2x the runner-up, >= 40% of the squad.
  3  NAME+NATION VERIFY — every remaining existing link to a LIVE club (present in the export)
     must still score >= 0.55 against the registry name or the fm_clubs alias with a
     compatible nation, else it is nulled and sent to review. Links to DEAD clubs (no export
     rows) are inert for membership sync and left in place, counted.

Hard rules:
  - career band teams (800k-1M) and career-copy players are never touched
  - one FM club -> one team, globally exclusive; a team a catalog club out-claims loses its
    link (its squad drains into the canonical record on the next membership sync — that mass
    move is intended, not a bug)
  - national-team rows (named like a country / U-age sides) never claim or keep a club link
  - corrections land in build/identity_fm_corrections.csv, ambiguity in
    build/identity_fm_review.csv; team_identity.method records 'vote2' / 'roster'

    python tools/verify_identity_fm.py --dry
    python tools/verify_identity_fm.py
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
CSVP = REPO / "allavailable columns players.csv"

STOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de", "club",
        "the", "afc", "rcd", "sd", "cp", "und", "sv", "vfl", "vfb", "tsg", "fsv", "us", "acf",
        "ca", "kf", "fk", "nk", "if", "bk", "sk", "ks"}
YOUTH = re.compile(r"U\s?-?(1[5-9]|2[0-3])", re.IGNORECASE)
RESV = re.compile(r"\b(ii|iii|b|reserves?|u\d\d?|acad|youth)\b")
RESV_NUM = re.compile(r"\s[2-4]$")            # 'FC Metz 2', 'Bryne 2' — reserve, not senior


def resv(s: str) -> bool:
    n = norm(s)
    return bool(RESV.search(n)) or bool(RESV_NUM.search(n.strip()))


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s: str) -> frozenset[str]:
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split()
                     if len(w) > 1 and w not in STOP)


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(s))


def cnorm(x: str) -> str:
    x = norm(x).strip()
    return {"holland": "netherlands", "korea republic": "south korea", "china pr": "china",
            "usa": "united states", "u.s.a.": "united states", "turkiye": "turkey",
            "republic of ireland": "ireland", "bosnia & herzegovina": "bosnia",
            "bosnia and herzegovina": "bosnia"}.get(x, x)


_XB = [{"england", "wales", "scotland", "northern ireland"}, {"france", "monaco"},
       {"switzerland", "liechtenstein"}, {"united states", "canada"},
       {"spain", "andorra"}, {"italy", "san marino"}]


def compatible(a, b):
    return a == b or any(a in g and b in g for g in _XB)


def tok_eq(x, y):
    return x == y or (len(x) >= 4 and len(y) >= 4 and abs(len(x) - len(y)) <= 2
                      and (x.startswith(y) or y.startswith(x)))


def name_score(want: frozenset, tk: frozenset) -> float:
    if not want or not tk:
        return 0.0
    m = sum(1 for x in want if any(tok_eq(x, y) for y in tk))
    if m == 0:
        return 0.0
    if m == len(want) == len(tk):
        return 1.0
    if m == len(want) or m == len(tk):
        return 0.8
    return 0.6 * m / (len(want) + len(tk) - m)


def sig_words(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", norm(s)).split()
            if len(w) > 1 and w not in STOP]


def initials(s: str) -> str:
    ws = sig_words(s)
    return "".join(w[0] for w in ws) if len(ws) >= 2 else ""


def abbrev_match(short: str, long: str) -> bool:
    """'West Brom' abbreviates 'West Bromwich Albion': every significant token of the short
    form (>= 2 of them — a single 'United' would match half of England) matches a distinct
    token of the long form in order, exactly or as a >= 4-char prefix."""
    st, lt = sig_words(short), sig_words(long)
    if len(st) < 2 or len(st) > len(lt):
        return False
    i = 0
    for w in st:
        while i < len(lt) and not (lt[i] == w or (len(w) >= 4 and lt[i].startswith(w))):
            i += 1
        if i >= len(lt):
            return False
        i += 1
    return True


def name_evidence(club_nm: str, team_nm: str) -> bool:
    return (abbrev_match(club_nm, team_nm) or abbrev_match(team_nm, club_nm)
            or (lkey(club_nm) != "" and lkey(club_nm) == initials(team_nm))
            or (lkey(team_nm) != "" and lkey(team_nm) == initials(club_nm)))


def surname_keys(fm_name: str) -> set[str]:
    """FM names are 'Surname, First' (or a bare display name). Index the compound surname AND
    its final word so 'van Dijk' meets our 'Virgil van Dijk' -> 'dijk' last-token key."""
    part = fm_name.split(",")[0] if "," in fm_name else fm_name
    keys = {lkey(part)}
    ws = norm(part).split()
    if ws:
        keys.add(lkey(ws[-1]))
    return {k for k in keys if len(k) >= 3}


def player_keys(db_name: str) -> set[str]:
    ws = norm(db_name).split()
    keys = {lkey(db_name)}
    if ws:
        keys.add(lkey(ws[-1]))
    return {k for k in keys if len(k) >= 3}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=120)

    # ---------- registry from the export ----------
    names_c: dict[int, Counter] = defaultdict(Counter)
    based_c: dict[int, Counter] = defaultdict(Counter)
    senior_uids: dict[int, set] = defaultdict(set)
    surname_of_club: dict[int, set] = defaultdict(set)
    fullname_of_club: dict[int, set] = defaultdict(set)
    uid2club: dict[int, int] = {}
    with open(CSVP, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            c = (r.get("Club ID") or "").strip()
            if not c.lstrip("-").isdigit() or int(c) <= 0:
                continue
            cid = int(c)
            names_c[cid][(r.get("Club") or "").strip()] += 1
            based_c[cid][cnorm(r.get("Based") or "")] += 1
            u = (r.get("Unique ID") or "").strip()
            uid = int(u) if u.lstrip("-").isdigit() else None
            if uid is not None:
                uid2club[uid] = cid
            squad = (r.get("Squad") or "").strip().strip('"')
            if not YOUTH.search(squad):
                if uid is not None:
                    senior_uids[cid].add(uid)
                fm_nm = (r.get("Name") or "").strip()
                surname_of_club[cid] |= surname_keys(fm_nm)
                ft = frozenset(re.sub(r"[^a-z ]", " ", norm(fm_nm.replace(",", " "))).split())
                if len(ft) >= 2:
                    fullname_of_club[cid].add(ft)
    reg_name = {cid: nc.most_common(1)[0][0] for cid, nc in names_c.items()}
    reg_nation = {cid: bc.most_common(1)[0][0] for cid, bc in based_c.items()}
    print(f"registry: {len(reg_name):,} live clubs from the export")

    fm_alias = {}
    for uid, nm in con.execute("SELECT uid, name FROM fm_clubs WHERE name IS NOT NULL"):
        fm_alias[uid] = nm

    # surname index: key -> clubs (for roster votes)
    sur_index: dict[str, set[int]] = defaultdict(set)
    for cid, keys in surname_of_club.items():
        for k in keys:
            sur_index[k].add(cid)

    # ---------- world state ----------
    teams = {tid: nm for tid, nm in con.execute(
        "SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''")
        if not (800_000 <= tid < 1_000_000)}
    tshort = {tid: sn for tid, sn in con.execute(
        "SELECT id, short_name FROM teams WHERE short_name IS NOT NULL AND short_name<>''")}
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    cat_country, league_country, country_names = {}, {}, set()
    for co in cat["countries"]:
        cn = cnorm(co["name"])
        country_names.add(cn)
        for lg in co["leagues"]:
            if lg.get("league_id"):
                league_country[lg["league_id"]] = cn
            for t in lg["teams"]:
                cat_country[t["team_id"]] = cn
    country_names |= set(reg_nation.values())
    tleague = dict(con.execute("SELECT id, league_id FROM teams"))
    cc: dict[int, Counter] = defaultdict(Counter)
    for tid, nat in con.execute("SELECT s.team_id, p.nationality FROM squad_members s "
                                "JOIN players p ON p.id=s.player_id WHERE p.nationality IS NOT NULL"):
        cc[tid][cnorm(nat.split("/")[0])] += 1
    squad_country = {t: c.most_common(1)[0][0] for t, c in cc.items()}

    def country_of(tid):
        return cat_country.get(tid) or league_country.get(tleague.get(tid)) or squad_country.get(tid)

    def country_firm(tid):          # catalog/league says so — strong; squad-dominant is weak
        return tid in cat_country or tleague.get(tid) in league_country

    def is_national(tid) -> bool:
        nmn = norm(teams[tid]).strip()
        base = re.sub(r"\s+u\d\d?$", "", nmn)
        return base in country_names or bool(re.search(r"\bu\d\d\b", nmn))

    uid_of = dict(con.execute(
        "SELECT player_id, fm_uid FROM player_identity WHERE fm_uid IS NOT NULL"))
    for (pid,) in con.execute(
            "SELECT id FROM players WHERE id >= 10000000000 AND id < 45000000000"):
        uid_of.setdefault(pid, pid - 10_000_000_000)

    squads: dict[int, list[int]] = defaultdict(list)
    for pid, tid in con.execute("SELECT player_id, team_id FROM squad_members"):
        if tid in teams:
            squads[tid].append(pid)
    pname = dict(con.execute("SELECT id, name FROM players WHERE name IS NOT NULL"))

    current = {tid: fc for tid, fc in con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL")
        if tid in teams}

    # ---------- pass 1: uid squad votes ----------
    conf_votes: dict[int, tuple[int, int, int]] = {}
    for tid, pids in squads.items():
        if is_national(tid):
            continue
        c = Counter()
        for pid in pids:
            fu = uid_of.get(pid)
            if fu is not None and fu in uid2club:
                c[uid2club[fu]] += 1
        if not c:
            continue
        (club, n), total = c.most_common(1)[0], sum(c.values())
        if n >= 5 and n / total >= 0.6 and club in reg_name:
            if resv(teams[tid]) == resv(reg_name[club]):
                conf_votes[tid] = (club, n, total)

    # Claim order matters: the catalog record is the canonical club, so catalog teams claim
    # first — by uid votes, then by roster surnames — and only then may shadow teams claim
    # what is left. (First cut let shadow 'Wolves' take FM 740 by uid votes before catalog
    # Wolverhampton Wanderers' roster pass could see it.)
    assign: dict[int, tuple[int, str, float, str]] = {}   # tid -> (club, method, conf, evidence)
    used: dict[int, int] = {}                              # club -> tid
    for tid, (club, n, total) in sorted(
            ((t, v) for t, v in conf_votes.items() if t in cat_country),
            key=lambda kv: kv[1][1], reverse=True):
        if tid in assign or club in used:
            continue
        assign[tid] = (club, "vote2", 0.95, f"votes {n}/{total}")
        used[club] = tid
    print(f"uid votes (catalog): {len(assign):,} teams claimed")

    # ---------- pass 2: roster votes for unresolved catalog teams ----------
    # Squad content by NAME: only non-generated members count (generated filler can never be
    # in FM and drowned the first cut's denominators). Surname hit = 1 point, full-name hit =
    # 2, a club-name abbreviation/initials fit ('West Brom' ~ 'West Bromwich Albion', 'QPR')
    # adds 4. Strongest evidence claims first across ALL unresolved teams.
    roster_review = []
    unresolved_cat = [t for t in cat_country if t in teams and t not in assign
                      and not is_national(t)]
    proposals = []
    for tid in unresolved_cat:
        pids = [p for p in squads.get(tid, []) if p < 50_000_000_000]
        if len(pids) < 6:
            continue
        hits, points = Counter(), Counter()
        for pid in pids:
            nm = pname.get(pid, "")
            cand_clubs = set()
            for k in player_keys(nm):
                cand_clubs |= sur_index.get(k, set())
            ft = frozenset(re.sub(r"[^a-z ]", " ", norm(nm)).split())
            for cid in cand_clubs:
                hits[cid] += 1
                points[cid] += 2 if len(ft) >= 2 and ft in fullname_of_club[cid] else 1
        tc = country_of(tid)
        team_aliases = [teams[tid]] + ([tshort[tid]] if tid in tshort else [])
        cand = []
        for cid, h in hits.items():
            if h < 3 or len(senior_uids.get(cid, ())) < 8:
                continue
            if tc and reg_nation.get(cid) and not compatible(tc, reg_nation[cid]):
                continue
            if resv(teams[tid]) != resv(reg_name[cid]):
                continue
            nev = any(name_evidence(reg_name[cid], a)
                      or name_score(toks(reg_name[cid]), toks(a)) >= 0.75
                      for a in team_aliases)
            cand.append((points[cid] + (4 if nev else 0), h, nev, cid))
        cand.sort(reverse=True)
        if not cand:
            continue
        total, h, nev, cid = cand[0]
        second = cand[1][0] if len(cand) > 1 else 0
        strong = h >= 5 and total >= 2 * second and h >= 0.5 * len(pids)
        named = nev and h >= 3 and h >= 0.3 * len(pids) and total >= 1.7 * second
        plain = h >= 5 and total >= 2.5 * second and h >= 0.55 * len(pids)
        if strong or named or plain:
            proposals.append((total, second, tid, cid,
                              f"roster {h}/{len(pids)} pts {total} (runner-up {second})"
                              + (" +name" if nev else "")))
        elif total >= 4:
            roster_review.append((tid, teams[tid], tc or "?", current.get(tid),
                                  "; ".join(f"pts {s} hits {hh} {c} {reg_name[c]}"
                                            for s, hh, _e, c in cand[:3])))
    roster_n = 0
    for total, _second, tid, cid, ev in sorted(proposals, reverse=True):
        if tid in assign or cid in used:
            continue
        assign[tid] = (cid, "roster", 0.9, ev)
        used[cid] = tid
        roster_n += 1
    print(f"roster votes: {roster_n:,} catalog teams claimed, "
          f"{len(roster_review):,} near-misses to review")

    # ---------- pass 2a: low-vote + name corroboration for unresolved catalog teams ----------
    # Gimcheon Sangmu had only 2 FM-linked squad players (Korean transliteration beat the
    # roster pass) but both voted for FM 'Gimcheon' and the names agree — two independent weak
    # signals on the CANONICAL record beat a shadow's strong claim, because the shadow's squad
    # drains into the catalog team on sync anyway.
    lowvote_n = 0
    for tid in cat_country:
        if tid not in teams or tid in assign or is_national(tid):
            continue
        c = Counter()
        for pid in squads.get(tid, []):
            fu = uid_of.get(pid)
            if fu is not None and fu in uid2club:
                c[uid2club[fu]] += 1
        if not c:
            continue
        (club, n), total = c.most_common(1)[0], sum(c.values())
        if n < 2 or n / total < 0.6 or club not in reg_name or club in used:
            continue
        if resv(teams[tid]) != resv(reg_name[club]):
            continue
        tc, cn = country_of(tid), reg_nation.get(club)
        if tc and cn and not compatible(tc, cn):
            continue
        aliases = [teams[tid]] + ([tshort[tid]] if tid in tshort else [])
        if not any(name_evidence(reg_name[club], a)
                   or name_score(toks(reg_name[club]), toks(a)) >= 0.75 for a in aliases):
            continue
        assign[tid] = (club, "vote-name", 0.85, f"votes {n}/{total} + name agrees")
        used[club] = tid
        lowvote_n += 1
    print(f"low-vote+name (catalog): {lowvote_n:,} teams claimed")

    review: list = []

    # ---------- pass 2c: name+nation claim for still-unlinked CATALOG clubs ----------
    # Squad evidence cannot reach a club whose world squad is all academy/filler with no FM
    # identities — catalog Arsenal FC held NO fm_club_id at all, so FM's Arsenal roster had
    # nowhere to go and the club fielded its youth team. For a canonical catalog record a
    # confident name+nation match to an UNCLAIMED live club is better evidence than nothing,
    # under the guards that name matching needs (this is exactly how 'Wanderers F.C.' got on
    # Wolves): both nations known and compatible, senior roster present, reserve/senior
    # agreement, near-perfect name, and a clear margin over the runner-up.
    by_nation: dict[str, list[int]] = defaultdict(list)
    for cid, nm in reg_name.items():
        by_nation[reg_nation.get(cid, "")].append(cid)
    name_n = 0
    for tid in sorted(cat_country):
        if tid not in teams or tid in assign or is_national(tid) or current.get(tid):
            continue
        tc = country_of(tid)
        if not tc:
            continue
        aliases = [teams[tid]] + ([tshort[tid]] if tid in tshort else [])
        pool = [c for nat, ids in by_nation.items() if nat and compatible(tc, nat) for c in ids]
        scored = []
        for cid in pool:
            if cid in used or len(senior_uids.get(cid, ())) < 8:
                continue
            if resv(teams[tid]) != resv(reg_name[cid]):
                continue
            s = max(name_score(toks(a), toks(reg_name[cid])) for a in aliases)
            if s >= 0.75:
                scored.append((s, len(senior_uids[cid]), cid))
        if not scored:
            continue
        scored.sort(reverse=True)
        s0, _sz, c0 = scored[0]
        rivals = [x for x in scored[1:] if x[0] >= s0 - 0.05]
        if s0 < 0.99 or rivals:
            review.append((tid, teams[tid], tc, current.get(tid),
                           "name-claim ambiguous: "
                           + "; ".join(f"{round(s, 2)} {c} {reg_name[c]}"
                                       for s, _z, c in scored[:3])))
            continue
        assign[tid] = (c0, "name", 0.8, f"name+nation '{reg_name[c0]}' ({tc}) exact, "
                                        f"{len(senior_uids[c0])} senior rows")
        used[c0] = tid
        name_n += 1
    print(f"name+nation (unlinked catalog): {name_n:,} teams claimed")

    # ---------- pass 2b: shadow teams claim what is left ----------
    n_shadow = 0
    for tid, (club, n, total) in sorted(
            ((t, v) for t, v in conf_votes.items() if t not in cat_country),
            key=lambda kv: kv[1][1], reverse=True):
        if tid in assign or club in used:
            continue
        assign[tid] = (club, "vote2", 0.95, f"votes {n}/{total}")
        used[club] = tid
        n_shadow += 1
    print(f"uid votes (rest of world): {n_shadow:,} teams claimed")

    # ---------- pass 3: verify remaining existing links ----------
    corrections, kept_live, kept_dead, nulled = [], 0, 0, []
    review += roster_review
    for tid, club in sorted(current.items()):
        if tid in assign:
            continue
        tname = teams[tid]
        if is_national(tid):
            if club in reg_name:
                nulled.append((tid, club, "national-team row must not hold a club"))
            continue
        holder = used.get(club)
        if holder is not None and holder != tid:
            nulled.append((tid, club, f"claimed by {holder} {teams.get(holder, '?')}"))
            continue
        if tid in conf_votes and conf_votes[tid][0] != club:
            nulled.append((tid, club,
                           f"own squad votes for {conf_votes[tid][0]} "
                           f"{reg_name.get(conf_votes[tid][0], '?')} ({conf_votes[tid][1]}/{conf_votes[tid][2]})"))
            continue
        if club not in reg_name:
            kept_dead += 1                       # no export rows: inert for membership sync
            continue
        tc, cn = country_of(tid), reg_nation.get(club)
        if tc and cn and not compatible(tc, cn) and country_firm(tid):
            nulled.append((tid, club, f"nation mismatch: team {tc} vs club {cn}"))
            review.append((tid, tname, tc, club, f"nation mismatch vs {reg_name[club]} ({cn})"))
            continue
        want = toks(tname) | (toks(tshort[tid]) if tid in tshort else frozenset())
        best = max(name_score(toks(tname), toks(reg_name[club])),
                   name_score(want, toks(reg_name[club])),
                   name_score(toks(tname), toks(fm_alias.get(club, ""))),
                   name_score(want, toks(fm_alias.get(club, ""))))
        if best >= 0.55:
            kept_live += 1
            used.setdefault(club, tid)
        else:
            nulled.append((tid, club, f"name mismatch: '{tname}' vs '{reg_name[club]}' ({best:.2f})"))
            review.append((tid, tname, tc or "?", club,
                           f"name mismatch vs export '{reg_name[club]}' / alias '{fm_alias.get(club, '')}'"))
    print(f"existing links: {kept_live:,} live verified | {kept_dead:,} dead (inert) kept | "
          f"{len(nulled):,} nulled")

    # ---------- corrections ----------
    for tid, (club, method, confv, ev) in sorted(assign.items()):
        old = current.get(tid)
        if old != club:
            corrections.append((tid, teams[tid], 1 if tid in cat_country else 0,
                                old, fm_alias.get(old, "") if old else "",
                                club, reg_name[club], method, ev,
                                "relink" if old else "link"))
    for tid, club, why in nulled:
        corrections.append((tid, teams.get(tid, "?"), 1 if tid in cat_country else 0,
                            club, fm_alias.get(club, reg_name.get(club, "")),
                            None, "", "null", why, "unlink"))
    print(f"corrections: {len(corrections):,} "
          f"(relink/link {sum(1 for c in corrections if c[9] != 'unlink'):,}, "
          f"unlink {len(nulled):,}) | review rows: {len(review):,}")

    with open(REPO / "build" / "identity_fm_corrections.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team_id", "team", "catalog", "old_fm", "old_fm_name",
                    "new_fm", "new_fm_name", "method", "evidence", "action"])
        w.writerows(corrections)
    with open(REPO / "build" / "identity_fm_review.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team_id", "team", "country", "current_fm", "reason_or_candidates"])
        w.writerows(review)

    for row in corrections[:15]:
        print("  ", row[9].upper(), row[0], row[1], "|", row[3], row[4], "->", row[5], row[6],
              "|", row[8])

    if dry:
        print("--dry: nothing written.")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-preverify")
    cur = con.cursor()
    for tid, (club, method, confv, _ev) in assign.items():
        if current.get(tid) == club:
            continue
        if cur.execute("SELECT 1 FROM team_identity WHERE team_id=?", (tid,)).fetchone():
            cur.execute("UPDATE team_identity SET fm_club_id=?, method=?, confidence=? "
                        "WHERE team_id=?", (club, method, confv, tid))
        else:
            cur.execute("INSERT INTO team_identity(team_id, fm_club_id, method, confidence) "
                        "VALUES(?,?,?,?)", (tid, club, method, confv))
    for tid, _club, _why in nulled:
        cur.execute("UPDATE team_identity SET fm_club_id=NULL, method=NULL WHERE team_id=?",
                    (tid,))
    con.commit()
    dup = con.execute("""SELECT COUNT(*) FROM (SELECT fm_club_id FROM team_identity
        WHERE fm_club_id IS NOT NULL AND NOT (team_id>=800000 AND team_id<1000000)
        GROUP BY fm_club_id HAVING COUNT(*)>1)""").fetchone()[0]
    print(f"applied. duplicate fm_club claims after write: {dup} (must be 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
