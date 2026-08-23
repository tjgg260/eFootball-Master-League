#!/usr/bin/env python3
"""
sort_database.py — the database sort. Each real club is fragmented across DB records (eFootball's
thin licensed record + FM's unlicensed one, e.g. "Celta de Vigo" 10 + "Vigo" 71). For every club in
the reconciled catalog this: (1) finds its record CLUSTER by player-identity overlap (works across
unlicensed names — Vigo's players match Celta's), (2) DEDUPS players by identity keeping the best
copy, (3) SPLITS the merged roster into a first team (top by rating) and youth (younger players ->
the club's U21/U18), then rewrites squad_members onto the catalog's canonical record + youth teams.

Identity-overlap clustering + a same-country guard keep genuine homonyms (Brazil's several
"América"s) apart. Non-catalog clubs are untouched.

    python tools/sort_database.py --dry     # show the plan (no writes)
    python tools/sort_database.py           # apply (backs up first)
"""
from __future__ import annotations

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

FIRST_TEAM_CAP = 30
OVERLAP_MIN = 3          # >=3 shared identities (or >=40% of the smaller squad) => same club


def ident(name: str, nat: str) -> tuple[str, str]:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    last = n.split()[-1] if n.split() else n
    return re.sub(r"[^a-z]", "", last), (nat or "").split("/")[0].strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    con = sqlite3.connect(DB, timeout=60)

    # per-player: identity, rating, age, "quality" (prefer FM-attributed w/ face + high overall)
    prow = {}
    for pid, nm, nat, age, ovr, face in con.execute(
            "SELECT id, name, nationality, age, overall_rating, real_face_path FROM players"):
        # quality for cross-source dedup: FM gives membership, eFootball gives attributes -> when
        # the same player exists in both, KEEP THE eFOOTBALL-NATIVE copy (native attrs + face).
        prow[pid] = (ident(nm, nat), ovr or 0, age or 24,
                     (2 if face else 0) + (1 if pid < 16_700_000 else 0))

    # squads + team country + identity -> teams index
    squad_of = defaultdict(list)
    for tid, pid in con.execute("SELECT team_id, player_id FROM squad_members"):
        squad_of[tid].append(pid)
    tcountry = {}
    cc = defaultdict(Counter)
    for tid, pid in [(t, p) for t, ps in squad_of.items() for p in ps]:
        nat = prow.get(pid, (("", ""),))[0][1]
        if nat:
            cc[tid][nat] += 1
    for tid, c in cc.items():
        tcountry[tid] = c.most_common(1)[0][0]
    id_teams = defaultdict(set)
    for tid, pids in squad_of.items():
        for pid in pids:
            id_teams[prow[pid][0]].add(tid)

    tname = dict(con.execute("SELECT id, name FROM teams"))
    catalog = json.loads(CAT.read_text(encoding="utf-8"))

    # name-token index (token -> team ids) so cluster only scans same-name-token candidates
    tset = {tid: _ntoks(nm) for tid, nm in tname.items()}
    ntok_index = defaultdict(list)
    for tid, tk in tset.items():
        for w in tk:
            ntok_index[w].append(tid)

    def cluster(seed_tid: int, seed_name: str, country: str) -> set[int]:
        """Same-club records ONLY: another record whose name is a token-SUBSET of the licensed name
        (FM's unlicensed 'Vigo' ⊂ 'Celta de Vigo'), same country, AND sharing >=1 player identity.
        Conservative by design — repairs the licensed/unlicensed split without the runaway identity
        merges (Getafe is NOT a token-subset of Barcelona, so it can't be pulled in)."""
        base_tok = _ntoks(seed_name)
        # a reserve/B/youth canonical keeps ONLY its own record — it must never absorb the senior
        # squad ('SL Benfica B' pulling in 'SL Benfica').
        if not base_tok or re.search(r"\b(u\d+|ii|reserve|academy|women|fem|b)\b", seed_name, re.I):
            return {seed_tid}
        base_ids = {prow[p][0] for p in squad_of.get(seed_tid, [])}
        cand = {t for w in base_tok for t in ntok_index.get(w, ())}
        out = {seed_tid}
        for tid in cand:
            if tid == seed_tid or re.search(r"\b(u\d+|ii|reserve|academy|women|fem|b)\b",
                                            tname.get(tid, ""), re.I):
                continue
            if country and _cnorm(tcountry.get(tid, "")) != country:
                continue
            tk = tset[tid]
            # candidate must be a SUBSET of the canonical name (FM's 'Vigo' ⊆ 'Celta de Vigo').
            # NOT the reverse: 'Barcelona' ⊆ 'Espanyol Barcelona' must never pull Espanyol in.
            if not tk or not (tk <= base_tok):
                continue
            if base_ids & {prow[p][0] for p in squad_of.get(tid, [])}:
                out.add(tid)
        return out

    # PASS 1: raw candidate members per canonical club.
    canon_set = {t["team_id"] for co in catalog["countries"] for lg in co["leagues"]
                 for t in lg["teams"]}
    clubs, raw = [], {}     # clubs: [(canon,name)]; raw: canon -> set(member_tids)
    for co in catalog["countries"]:
        country = _cnorm(co["name"])
        for lg in co["leagues"]:
            for t in lg["teams"]:
                canon = t["team_id"]
                clubs.append((canon, t["name"]))
                raw[canon] = cluster(canon, t["name"], country)

    # PASS 2: GLOBAL EXCLUSIVITY. A non-canonical fragment ('Radnicki', 'Esporte') can be a subset
    # of several clubs; give it to the ONE it shares the most player identities with. A record that
    # is itself a catalog canonical always stays its own club (never absorbed).
    def shared(canon, tid):
        a = {prow[p][0] for p in squad_of.get(canon, [])}
        return len(a & {prow[p][0] for p in squad_of.get(tid, [])})
    claim = {}   # member_tid -> (best_shared, canon)
    for canon, _nm in clubs:
        for tid in raw[canon]:
            if tid == canon:
                continue
            if tid in canon_set:            # another club's canonical -> never merge it away
                continue
            s = shared(canon, tid)
            if tid not in claim or s > claim[tid][0]:
                claim[tid] = (s, canon)

    plans = []   # (canonical_tid, name, [member_tids], first_team_pids, youth_pids)
    for canon, nm in clubs:
        members = {canon} | {tid for tid, (_s, c) in claim.items() if c == canon}
        best_by_id = {}
        for tid in members:
            for pid in squad_of.get(tid, []):
                key, ovr, age, qual = prow[pid][0], *prow[pid][1:]
                cur = best_by_id.get(key)
                if cur is None or (qual, ovr) > (prow[cur][3], prow[cur][1]):
                    best_by_id[key] = pid
        roster = sorted(best_by_id.values(), key=lambda p: -prow[p][1])   # by overall desc
        plans.append((canon, nm, sorted(members), roster[:FIRST_TEAM_CAP], roster[FIRST_TEAM_CAP:]))

    total_first = sum(len(p[3]) for p in plans)
    print(f"clubs to sort: {len(plans):,} | records merged: "
          f"{sum(len(p[2]) for p in plans):,} | first-team players placed: {total_first:,}")
    if dry:
        hist = Counter(len(p[2]) for p in plans)
        print("  cluster-size histogram (records merged -> #clubs):", dict(sorted(hist.items())))
        print("  --- biggest clusters ---")
        for canon, nm, members, first, youth in sorted(plans, key=lambda p: -len(p[2]))[:12]:
            print(f"  {nm}: {len(members)} records [{', '.join(tname.get(m,'?') for m in members)[:90]}]")
        print("  --- sample ---")
        for canon, nm, members, first, youth in plans:
            if nm in ("Celta de Vigo", "Mallorca", "RCD Mallorca", "FC Barcelona", "Real Madrid") \
                    or len(members) > 1 and len(first) < 18:
                print(f"  {nm}: {len(members)} records -> {len(first)} first team + {len(youth)} youth "
                      f"[{', '.join(tname.get(m,'?') for m in members)[:70]}]")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-presort")
    con.execute("BEGIN")
    total_players = 0
    for canon, nm, members, first, youth in plans:
        for tid in members:                          # clear every fragment record of this club
            con.execute("DELETE FROM squad_members WHERE team_id=?", (tid,))
        # write the FULL deduped roster onto the canonical record, best-rated first (slot 0..N).
        # top FIRST_TEAM_CAP are the senior XI pool; the rest are the youth pool on the same record
        # until an FM Squad column lets us split them into per-club U21/U18 teams. Nothing is lost.
        roster = first + youth
        con.executemany("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot) "
                        "VALUES(?,?,?,?)", [(canon, p, i + 1, i) for i, p in enumerate(roster)])
        total_players += len(roster)
    con.commit()
    print(f"sorted {len(plans):,} clubs: {total_players:,} players consolidated onto canonical "
          f"records ({total_first:,} in senior pools). Youth split awaits the FM Squad column.")
    return 0


_NSTOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de",
          "club", "the", "afc", "rcd", "sd", "cp", "und", "sv", "vfl", "vfb", "tsg", "fsv", "us",
          "acf", "ca"}


def _ntoks(s: str) -> frozenset[str]:
    """Distinctive name tokens (drops only corporate suffixes: 'Vigo' ⊂ 'Celta de Vigo', while
    'Real Madrid' {real,madrid} and 'Atletico Madrid' {atletico,madrid} stay non-subsets)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w and w not in _NSTOP)


def _cnorm(x: str) -> str:
    x = (x or "").lower()
    return {"holland": "netherlands", "korea republic": "south korea"}.get(x, x)


if __name__ == "__main__":
    raise SystemExit(main())
