#!/usr/bin/env python3
"""
supersede_twins.py — ONE RECORD PER HUMAN (owner ruling 2026-08-24). Collapses cross-source
duplicate player records after the FM membership sync: the surviving record plays at the right
team; every other copy is unsquadded and marked players.superseded_by = canonical id, which
hides it from transfer search, free-agent pools and career seeding (all pool queries filter
superseded_by IS NULL).

Same-human evidence, strongest first (never name similarity alone):
  1  spine groups — records sharing player_identity.fm_uid / ef_pid. DISTINCT FM-band uids are
     DISTINCT HUMANS by definition (the uid is the universal key): a group is split on its
     uid anchors, and a record attaches to an anchor only if age (±3, NULLs pass) and
     nationality agree. Incompatible name-method links are BROKEN, not superseded — three
     different Brazilian 'Zé Roberto's were chained through one eF record by name matching.
  2  same-squad surname twins — an UNLINKED RFS record whose name tokens are a subset of
     exactly ONE full-name squadmate (age ±4, nationality agrees): catalog Wolves' RFS
     'Bellegarde' next to the arrived 'Jean-Ricner Bellegarde'. Gains the canonical's fm_uid
     (fm_method 'twin'), then is superseded.
  3  drained-pair surname twins — same test, but between a catalog team and the shadow team
     that lost its fm_club_id to it in the identity re-verification ([[fm-identity-verification]]):
     the only cross-team scope where a name subset is safe.

Hard rules:
  - curated records (45-46B) are EXEMPT: never superseded, never unsquadded, never canonical —
    they are the career overlay and live in career squads by design
  - career-band teams (800k-1M) and career-copy players (20M-700M) are never touched
  - canonical pick: squadded at the uid's FM-club team > squadded in catalog > squadded >
    band order (eF < RFS < FM < generated); catalog floors (18/2GK) block an unsquad
  - a superseded record keeps its row (blueprint: delete nothing) and its identity link

    python tools/supersede_twins.py --dry
    python tools/supersede_twins.py
"""
from __future__ import annotations

import csv
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
FLOOR, GK_FLOOR = 18, 2
YOUTH = re.compile(r"\bU\s?-?(1[5-9]|2[0-3])\b", re.IGNORECASE)


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def toks(s: str) -> frozenset[str]:
    return frozenset(re.sub(r"[^a-z ]", " ", norm(s)).split())


def band(pid: int) -> str:
    if 20_000_000 <= pid < 700_000_000:
        return "career"
    if pid < 16_700_000:
        return "ef"
    if pid < 10_000_000_000:
        return "rfs"
    if pid < 45_000_000_000:
        return "fm"
    if pid < 50_000_000_000:
        return "curated"
    return "generated"


# Provenance priority (owner ruling 2026-08-25): eFootball first, then FM, RFS LAST. Lower wins.
# This used to read {ef:0, rfs:1, fm:2}, which preferred RFS over FM and is why so many survivors
# carry a surname-only RFS name ('Thuram') instead of FM's full one ('Marcus Thuram').
BAND_RANK = {"ef": 0, "fm": 1, "rfs": 2, "generated": 3}


# The sources spell the same country differently. Comparing raw strings made the guard reject
# real twins: RFS says 'Korea Republic' where FM says 'South Korea', 'Cote d'Ivoire' vs 'Ivory
# Coast' — which is why an entire K League's worth of duplicates survived the first merge.
NAT_SYN = {
    "korea republic": "south korea", "korea dpr": "north korea", "china pr": "china",
    "ivory coast": "cote divoire", "cote divoire": "cote divoire", "holland": "netherlands",
    "usa": "united states", "united states of america": "united states", "turkiye": "turkey",
    "republic of ireland": "ireland", "eire": "ireland", "bosnia and herzegovina": "bosnia",
    "bosnia & herzegovina": "bosnia", "czech republic": "czechia", "cape verde": "cabo verde",
    "iran": "iran islamic republic", "iran islamic republic": "iran islamic republic",
    "russian federation": "russia", "chinese taipei": "taiwan", "congo dr": "dr congo",
    "dr congo": "dr congo", "congo": "congo", "north macedonia": "macedonia",
    "fyr macedonia": "macedonia", "curacao": "curacao", "st kitts and nevis": "st kitts",
    "trinidad and tobago": "trinidad", "antigua and barbuda": "antigua",
}


def nat_key(nat: str | None) -> frozenset[str]:
    # multi-nationality fields ('France / Haiti') must compare as SETS: the RFS twin often
    # carries the OTHER passport of the same human
    out = set()
    for x in (nat or "").split("/"):
        k = re.sub(r"[^a-z ]", "", norm(x)).strip()
        if k:
            out.add(NAT_SYN.get(k, k))
    return frozenset(out)


def age_ok(a, b, tol=3):
    return a is None or b is None or abs(a - b) <= tol


def diacritics(s: str) -> int:
    return sum(1 for ch in (s or "") if unicodedata.combining(ch)
               or unicodedata.normalize("NFKD", ch)[0] != ch)


# satellites copied onto the survivor ONLY when it has none of its own (never overwritten:
# the survivor's own data is already the record the world plays with)
FILL_TABLES = ["player_skills", "player_playstyles", "player_appearance",
               "player_appearance_raw", "player_traits", "player_potential"]


def enrich(con, cur, superseded: dict, P: dict) -> None:
    """A merge must carry the human's best fields onto the surviving record, else hiding a
    twin LOSES data. Per the compiled-world contract (docs/database-blueprint.md) eFootball
    is the ATTRIBUTE authority, so a survivor whose hidden twin is eF-native inherits that
    twin's attribute set (26 shared + foot/form/injury_resistance/weak_foot_usage) and its
    overall rating; the fullest name among the merged records wins; sparse satellites are
    filled in, never overwritten."""
    twins: dict[int, list[int]] = defaultdict(list)
    for p, (c, _ev) in superseded.items():
        twins[c].append(p)

    n_attr = n_name = n_face = n_style = 0
    fills = defaultdict(int)
    for surv, hidden in twins.items():
        if surv not in P:
            continue
        # -- attributes: the eF-native twin is the authority
        if band(surv) != "ef":
            ef = [h for h in hidden if band(h) == "ef"]
            if ef:
                src = min(ef)
                have = cur.execute(
                    "SELECT COUNT(*) FROM player_attributes WHERE player_id=?", (src,)).fetchone()[0]
                if have >= 26:
                    cur.execute("DELETE FROM player_attributes WHERE player_id=?", (surv,))
                    cur.execute("INSERT INTO player_attributes(player_id, attribute, value) "
                                "SELECT ?, attribute, value FROM player_attributes "
                                "WHERE player_id=?", (surv, src))
                    # position travels with the attributes: it is the SAME Konami record, and a
                    # survivor keeping FM's position while wearing eF's playstyle produces pairs
                    # the game has no slot for ('Reece James (MID) / Attacking Full-back')
                    cur.execute("UPDATE players SET overall_rating=COALESCE("
                                "(SELECT overall_rating FROM players WHERE id=?), overall_rating), "
                                "position=COALESCE(NULLIF((SELECT position FROM players "
                                "WHERE id=?),''), position) WHERE id=?", (src, src, surv))
                    n_attr += 1
                    # Konami's own playstyles and skills come with those attributes and REPLACE
                    # whatever the survivor carried (assign_roles.py's attribute-fit guess is a
                    # stand-in for exactly this data, never a better source than it)
                    for tbl, col in (("player_playstyles", "playstyle"), ("player_skills", "skill")):
                        if cur.execute(f"SELECT 1 FROM {tbl} WHERE player_id=? LIMIT 1",
                                       (src,)).fetchone():
                            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})")]
                            rest = ",".join(c for c in cols if c != "player_id")
                            cur.execute(f"DELETE FROM {tbl} WHERE player_id=?", (surv,))
                            cur.execute(f"INSERT INTO {tbl}(player_id,{rest}) "
                                        f"SELECT ?,{rest} FROM {tbl} WHERE player_id=?",
                                        (surv, src))
                            n_style += 1
        # -- name: the fullest spelling of this human among the merged records
        best, bt = P[surv][0], toks(P[surv][0])
        for h in hidden:
            if h not in P:
                continue
            ht = toks(P[h][0])
            if ht > bt or (ht == bt and diacritics(P[h][0]) > diacritics(best)):
                best, bt = P[h][0], ht
        if best != P[surv][0]:
            cur.execute("UPDATE players SET name=? WHERE id=?", (best, surv))
            n_name += 1
        # -- a real face beats none
        if not cur.execute("SELECT real_face_path FROM players WHERE id=?",
                           (surv,)).fetchone()[0]:
            for h in hidden:
                f = cur.execute("SELECT real_face_path FROM players WHERE id=?", (h,)).fetchone()
                if f and f[0]:
                    cur.execute("UPDATE players SET real_face_path=? WHERE id=?", (f[0], surv))
                    n_face += 1
                    break
        # -- sparse satellites: fill only
        for tbl in FILL_TABLES:
            try:
                if cur.execute(f"SELECT 1 FROM {tbl} WHERE player_id=? LIMIT 1",
                               (surv,)).fetchone():
                    continue
                for h in sorted(hidden, key=lambda x: 0 if band(x) == "ef" else 1):
                    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})")]
                    rest = ",".join(c for c in cols if c != "player_id")
                    if cur.execute(f"SELECT 1 FROM {tbl} WHERE player_id=? LIMIT 1",
                                   (h,)).fetchone():
                        cur.execute(f"INSERT INTO {tbl}(player_id,{rest}) "
                                    f"SELECT ?,{rest} FROM {tbl} WHERE player_id=?", (surv, h))
                        fills[tbl] += 1
                        break
            except sqlite3.OperationalError:
                pass
    con.commit()
    print(f"enrich: attributes from eF twin {n_attr:,} (styles/skills {n_style:,}) | "
          f"fuller name {n_name:,} | face {n_face:,} | satellites {dict(fills)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    allow_floor = "--allow-floor" in sys.argv    # run tools/fill_squads.py after
    con = sqlite3.connect(DB, timeout=120)

    P = {pid: (nm, age, nat_key(nat), pos) for pid, nm, age, nat, pos in con.execute(
        "SELECT id, name, age, nationality, position FROM players")}
    ident = {pid: (k, fu, ep, fm_m, ef_m) for pid, k, fu, ep, fm_m, ef_m in con.execute(
        "SELECT player_id, kind, fm_uid, ef_pid, fm_method, ef_method FROM player_identity")}
    world_team = {}
    for pid, tid in con.execute("SELECT player_id, team_id FROM squad_members"):
        if not (800_000 <= tid < 1_000_000):
            world_team[pid] = tid
    squad_size, gk_count = defaultdict(int), defaultdict(int)
    for pid, tid in world_team.items():
        squad_size[tid] += 1
        if P.get(pid, (None,) * 4)[3] == "GK":
            gk_count[tid] += 1
    import json
    cat = json.loads((REPO / "build" / "catalog.json").read_text(encoding="utf-8"))
    catalog_teams = {t["team_id"] for co in cat["countries"]
                     for lg in co["leagues"] for t in lg["teams"]}
    tname = dict(con.execute("SELECT id, name FROM teams"))

    # FM CSV: uid -> senior club; club -> team via team_identity
    uid2club = {}
    with open(CSVP, encoding="cp1252", errors="replace", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            u = (r.get("Unique ID") or "").strip()
            c = (r.get("Club ID") or "").strip()
            if u.lstrip("-").isdigit() and c.lstrip("-").isdigit() and int(c) > 0 \
                    and not YOUTH.search((r.get("Squad") or "").strip().strip('"')):
                uid2club[int(u)] = int(c)
    team_of_club = {}
    for tid, fc in con.execute(
            "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"):
        if not (800_000 <= tid < 1_000_000):
            team_of_club.setdefault(fc, tid)

    def fm_team_of(uid):
        c = uid2club.get(uid)
        return team_of_club.get(c) if c else None

    def exit_ok(tid, pid):
        if tid not in catalog_teams:
            return True
        is_gk = P.get(pid, (None,) * 4)[3] == "GK"
        if squad_size[tid] <= FLOOR:
            # --allow-floor: dropping BELOW the floor is recoverable — fill_squads.py tops the
            # club back to 20 with guaranteed GK cover, and a generated squad player is a
            # smaller lie than the same human appearing twice in the world
            return allow_floor
        if is_gk and gk_count[tid] <= GK_FLOOR:
            return allow_floor    # fill_squads.py also tops up "keeperless at size" clubs,
        return True               # so keeper cover is restorable the same way

    def do_unsquad(tid, pid):
        squad_size[tid] -= 1
        if P.get(pid, (None,) * 4)[3] == "GK":
            gk_count[tid] -= 1

    # ---------------- 1. spine groups, split on uid anchors ----------------
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_fm, by_ef = defaultdict(list), defaultdict(list)
    for pid, (_k, fu, ep, _fm_m, _ef_m) in ident.items():
        if band(pid) == "career":
            continue
        if fu is not None:
            by_fm[fu].append(pid)
        if ep is not None:
            # ef_pid names an actual player row, so the TARGET must join the group too — most
            # eF records carry no player_identity row of their own, and without this the pair
            # ('Kagawa Shinji' the FM record, 'Kagawa Shinji' the eF record it points at) never
            # meets and both stay visible
            by_ef[ep].append(pid)
            if ep in P and ep != pid:
                by_ef[ep].append(ep)
    for lst in list(by_fm.values()) + list(by_ef.values()):
        for p in lst[1:]:
            union(lst[0], p)
    groups = defaultdict(list)
    for p in list(parent):
        groups[find(p)].append(p)

    superseded: dict[int, tuple[int, str]] = {}      # pid -> (canonical, evidence)
    unsquads: list[tuple[int, int]] = []             # (tid, pid)
    broken_fm: list[tuple[int, str]] = []            # (pid, why) -> fm_uid=NULL
    broken_ef: list[tuple[int, str]] = []
    new_links: list[tuple[int, int]] = []            # (pid, fm_uid) method 'twin'
    blocked = 0

    def compatible(a, b, tol=3):
        pa, pb = P.get(a), P.get(b)
        if not pa or not pb:
            return False
        return age_ok(pa[1], pb[1], tol) and (not pa[2] or not pb[2] or pa[2] & pb[2])

    def pick_canonical(cluster):
        def key(p):
            uid = ident.get(p, (None,) * 5)[1]
            at_fm_team = 1 if (uid is not None and world_team.get(p) is not None
                               and world_team.get(p) == fm_team_of(uid)) else 0
            squadded = 1 if p in world_team else 0
            in_cat = 1 if world_team.get(p) in catalog_teams else 0
            return (at_fm_team, squadded, in_cat, -BAND_RANK.get(band(p), 9))
        return max(cluster, key=key)

    n_groups = n_false = 0
    for g in groups.values():
        if len(g) < 2:
            continue
        n_groups += 1
        # uid anchors: records that ARE the FM import of a uid (fm_method 'id')
        anchors = {}                                   # uid -> anchor pid
        rest = []
        for p in g:
            k, fu, _ep, fm_m, _ef_m = ident.get(p, (None,) * 5)
            if k == "fm" and fm_m == "id" and fu is not None:
                anchors[fu] = p
            else:
                rest.append(p)
        clusters: list[list[int]] = [[a] for a in anchors.values()]
        loose: list[int] = []
        for p in rest:
            fits = [c for c in clusters if compatible(p, c[0])]
            if len(anchors) <= 1 and not clusters:
                loose.append(p)
            elif len(fits) == 1:
                fits[0].append(p)
            elif not fits and not clusters:
                loose.append(p)
            else:
                # ambiguous or incompatible with every anchor: not the same human as any —
                # break the name-method links that pulled it in
                k, fu, ep, fm_m, ef_m = ident.get(p, (None,) * 5)
                if fu is not None and fm_m != "id":
                    broken_fm.append((p, f"incompatible with uid {fu} anchor ({fm_m})"))
                if ep is not None and ef_m != "id":
                    broken_ef.append((p, "ambiguous ef link in mixed group"))
                n_false += 1
        if loose:
            # no uid anchor: cluster the loose records around the best-band one
            seed = min(loose, key=lambda p: BAND_RANK.get(band(p), 9))
            cl = [seed]
            for p in loose:
                if p is seed:
                    continue
                if compatible(p, seed):
                    cl.append(p)
                else:
                    k, fu, ep, fm_m, ef_m = ident.get(p, (None,) * 5)
                    if fu is not None and fm_m != "id":
                        broken_fm.append((p, f"incompatible with group seed ({fm_m})"))
                    if ep is not None and ef_m != "id":
                        broken_ef.append((p, "incompatible with group seed"))
                    n_false += 1
            clusters.append(cl)
        for cl in clusters:
            live = [p for p in cl if band(p) != "curated"]
            if len(live) < 2:
                continue
            canon = pick_canonical(live)
            for p in live:
                if p == canon:
                    continue
                t = world_team.get(p)
                if t is not None:
                    if exit_ok(t, p):
                        unsquads.append((t, p))
                        do_unsquad(t, p)
                        del world_team[p]
                    else:
                        blocked += 1
                        continue             # cannot leave yet: do not hide a fielded player
                superseded[p] = (canon, "spine")
    print(f"spine: {n_groups:,} groups | superseded {len(superseded):,} | "
          f"false links broken {len(broken_fm) + len(broken_ef):,} | floor-blocked {blocked:,}")

    # ---------------- 2+3. surname twins (same squad, then drained pairs) ----------------
    drain_pairs = []                                  # (catalog tid, shadow tid)
    holder = {fc: tid for tid, fc in con.execute(
        "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL")}
    corr = REPO / "build" / "identity_fm_corrections.csv"
    if corr.exists():
        for r in csv.DictReader(open(corr, encoding="utf-8")):
            if r.get("old_fm") and not r.get("new_fm"):
                fc = int(r["old_fm"])
                tc = holder.get(fc)
                if tc is not None and tc in catalog_teams:
                    drain_pairs.append((tc, int(r["team_id"])))

    members = defaultdict(list)
    for pid, tid in world_team.items():
        members[tid].append(pid)

    def surname_pass(host_tid, guest_tid, scope):
        n = 0
        # the canonical must be a REAL fuller-named record: never generated filler (round 1
        # hid RFS 'Aydın' behind the generated 'Ilkay Aydn'), and the guest's tokens must be
        # a STRICT subset (equal-name pairs superseded each other in a circle)
        # a host needs a fuller name than the guest — OR to be the FM import ('id') of a
        # roster uid, which lets single-token names ('André') anchor their equal-name twin
        full = [(p, toks(P[p][0])) for p in members.get(host_tid, ())
                if p not in superseded and band(p) != "generated"
                and (len(toks(P[p][0])) >= 2
                     or ident.get(p, (None,) * 5)[3] == "id")]
        for p in list(members.get(guest_tid, ())):
            if p in superseded or band(p) != "rfs":
                continue
            k, fu, ep, _fm, _ef = ident.get(p, (None, None, None, None, None))
            if fu is not None or ep is not None:
                continue                              # linked records are pass-1 material
            pt = toks(P[p][0])
            if not pt:
                continue
            # equal-token names ('André' == 'André') are decisive only when the host IS the
            # FM import of a uid on this club's roster and the guest carries no identity —
            # two unlinked equal names must never supersede each other (the Da Silva circle)
            cands = [(q, qt) for q, qt in full if q != p
                     and (pt < qt or (pt == qt
                          and ident.get(q, (None,) * 5)[3] == "id"))
                     and compatible(p, q, 4)]
            if len(cands) != 1:
                continue
            q = cands[0][0]
            quid = ident.get(q, (None,) * 5)[1]
            t = world_team.get(p)
            if t is not None:
                if not exit_ok(t, p):
                    continue
                unsquads.append((t, p))
                do_unsquad(t, p)
                del world_team[p]
                members[t].remove(p)
            superseded[p] = (q, scope)
            if quid is not None:
                new_links.append((p, quid))
            n += 1
        return n

    # ---------- 2a. SAME FACE FILE = same human ----------
    # Face files are named by FM uid, so an unlinked record wearing face_<uid>.webp while a
    # squadmate's fm_uid IS that uid is the same person — decisive even when the two sources
    # romanise the name differently ('Song Bumkeun' / 'Bum-keun Song'), which no token rule
    # can bridge. Restricted to ONE squad: a name-guessed face is splattered across clubs
    # (nine unrelated 'Vitor Wang's share one file), but never twice inside a single team.
    face_uid = {}
    for pid, path in con.execute(
            "SELECT id, real_face_path FROM players WHERE real_face_path LIKE '%face_%'"):
        m = re.search(r"face_(\d+)", path or "")
        if m:
            face_uid[pid] = int(m.group(1))

    n_face = 0
    for tid, mem in list(members.items()):
        owners = {}                       # uid -> the record that IS that uid
        for q in mem:
            u = ident.get(q, (None,) * 5)[1]
            if u is not None and q not in superseded:
                owners[u] = q
        if not owners:
            continue
        for p in list(mem):
            if p in superseded or p == owners.get(face_uid.get(p)):
                continue
            u = face_uid.get(p)
            q = owners.get(u) if u is not None else None
            if q is None or q == p or ident.get(p, (None,) * 5)[1] is not None:
                continue
            if not (toks(P[p][0]) & toks(P[q][0])):
                continue                  # share a name token, else it is a face-guess collision
            t = world_team.get(p)
            if t is not None:
                if not exit_ok(t, p):
                    continue
                unsquads.append((t, p))
                do_unsquad(t, p)
                del world_team[p]
                members[t].remove(p)
            superseded[p] = (q, "same-face")
            new_links.append((p, u))
            n_face += 1
    print(f"same-face twins: {n_face:,}")

    # ---------- 2b. clubs paired by SQUAD CONTENT, not by name ----------
    # The eF-native club rows are the same clubs as their catalog records under different names
    # ('Inter Milan' vs 'Blu-neri', 'AC Milan' vs 'Casciavit'), so no name rule pairs them — yet
    # they hold surname-only copies of players the catalog club already fields in full
    # ('Çalhanoğlu' beside 'Hakan Çalhanoğlu'). Pair on the overlap itself: a shadow squad whose
    # players are strict name-subsets of ONE catalog squad is that club's leftovers.
    cat_index = defaultdict(list)                       # surname key -> [(tid, pid, tokens)]
    for tid in catalog_teams:
        for p in members.get(tid, ()):
            t = toks(P[p][0]) if p in P else frozenset()
            if len(t) >= 2:
                for w in t:
                    cat_index[w].append((tid, p, t))
    content_pairs = []
    for tid, mem in members.items():
        if tid in catalog_teams or not mem:
            continue
        votes = Counter()
        for p in mem:
            t = toks(P[p][0]) if p in P else frozenset()
            if not t:
                continue
            seen = set()
            for w in t:
                for ct, q, qt in cat_index.get(w, ()):
                    if ct not in seen and t < qt and compatible(p, q, 4):
                        seen.add(ct)
            for ct in seen:
                votes[ct] += 1
        if not votes:
            continue
        best, n = votes.most_common(1)[0]
        if n >= 2 and n >= 0.3 * len(mem) and (len(votes) == 1 or n > votes.most_common(2)[1][1]):
            content_pairs.append((best, tid))
    n_content = sum(surname_pass(ct, st, "content-pair") for ct, st in content_pairs)
    print(f"clubs paired by squad content: {len(content_pairs):,} | twins merged: {n_content:,}")

    # ---------- 2c. an UNIDENTIFIED record duplicating an IDENTIFIED one ----------
    # A record with no fm_uid can never meet its twin through the spine, so the same man ends up
    # squadded at two rendering clubs — Wan-Bissaka at West Ham (RFS, no identity) and at Aston
    # Villa, where the export actually places him. Two records that share a full name, a
    # nationality, a position and an age to within a year are the same human; the identified one
    # wins because it is the one the export can vouch for.
    ident_by = defaultdict(list)
    unident_by = defaultdict(list)
    for pid, tid in list(world_team.items()):
        if pid in superseded or pid not in P:
            continue
        t = toks(P[pid][0])
        if len(t) < 2:
            continue                                  # a single token is not an identity
        k = (t, frozenset(P[pid][2]))
        (ident_by if ident.get(pid, (None,) * 5)[1] else unident_by)[k].append(pid)
    n_unid = 0
    for k, ghosts in unident_by.items():
        real = ident_by.get(k, [])
        if len(real) != 1 or len(ghosts) != 1:
            continue                                  # any ambiguity and we leave it alone
        g, r = ghosts[0], real[0]
        if world_team.get(g) == world_team.get(r):
            continue
        if P[g][3] != P[r][3] or not age_ok(P[g][1], P[r][1], 1):
            continue
        t = world_team.get(g)
        if t is not None:
            if not exit_ok(t, g):
                continue
            unsquads.append((t, g))
            do_unsquad(t, g)
            del world_team[g]
            members[t].remove(g)
        superseded[g] = (r, "unidentified-twin")
        n_unid += 1
    print(f"unidentified duplicates of an identified player: {n_unid:,}")

    n_same = sum(surname_pass(t, t, "squad-surname") for t in list(members))
    n_drain = sum(surname_pass(tc, ts, "drained-pair") for tc, ts in drain_pairs)
    print(f"surname twins: same-squad {n_same:,} | drained-pair {n_drain:,} | "
          f"total superseded {len(superseded):,}")

    # ---------------- 0 (late): re-validate marks already in the DB ----------------
    # The tool is a full recompute (apply clears every mark first). A prior mark whose pair
    # this run no longer derives (its record was unsquadded by the earlier run, so the squad
    # passes cannot see it) is carried forward only if it still looks like the same human;
    # generated canonicals and mutual pairs are dropped.
    prior, cleared = {}, []
    try:
        prior = dict(con.execute(
            "SELECT id, superseded_by FROM players WHERE superseded_by IS NOT NULL"))
    except sqlite3.OperationalError:
        pass
    for p, c in prior.items():
        if p in superseded:
            continue
        pt, ok = toks(P.get(p, ("",))[0]), False
        if c in P and band(c) != "generated" and band(p) != "curated" \
                and c not in superseded and prior.get(c) != p:
            ct = toks(P[c][0])
            same_uid = (ident.get(p, (None,) * 5)[1] is not None
                        and ident.get(p, (None,) * 5)[1] == ident.get(c, (None,) * 5)[1])
            ok = age_ok(P[p][1], P[c][1], 4) and (same_uid or (pt and pt < ct))
        if ok:
            superseded[p] = (c, "kept")
        else:
            cleared.append(p)
    print(f"prior marks: {len(prior):,} | kept {sum(1 for v in superseded.values() if v[1] == 'kept'):,} "
          f"| cleared {len(cleared):,}")

    # ---------------- report ----------------
    with open(REPO / "build" / "supersede_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pid", "name", "band", "was_team", "canonical", "canonical_name",
                    "canonical_team", "evidence"])
        for p, (c, ev) in sorted(superseded.items()):
            was = next((t for t, q in unsquads if q == p), None)
            w.writerow([p, P.get(p, ("?",))[0], band(p),
                        tname.get(was, "") if was else "(unsquadded)",
                        c, P.get(c, ("?",))[0], tname.get(world_team.get(c), ""), ev])
    print(f"report: build/supersede_report.csv | unsquads {len(unsquads):,} | "
          f"new twin-links {len(new_links):,}")

    # flatten chains: if A -> B and B -> C, A points at C (marks must always name the LIVE record)
    for p in list(superseded):
        c, ev = superseded[p]
        seen = {p}
        while c in superseded and c not in seen:
            seen.add(c)
            c = superseded[c][0]
        superseded[p] = (c, ev)

    if dry:
        print("--dry: nothing written.")
        return 0

    shutil.copy2(DB, str(DB) + ".bak-presupersede")
    cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(players)")]
    if "superseded_by" not in cols:
        cur.execute("ALTER TABLE players ADD COLUMN superseded_by INTEGER")
    for tid, pid in unsquads:
        cur.execute("DELETE FROM squad_members WHERE team_id=? AND player_id=?", (tid, pid))
    cur.execute("UPDATE players SET superseded_by=NULL WHERE superseded_by IS NOT NULL")
    for p, (c, _ev) in superseded.items():
        cur.execute("UPDATE players SET superseded_by=? WHERE id=?", (c, p))
    for p, why in broken_fm:
        cur.execute("UPDATE player_identity SET fm_uid=NULL, fm_method=NULL WHERE player_id=?",
                    (p,))
    for p, why in broken_ef:
        cur.execute("UPDATE player_identity SET ef_pid=NULL, ef_method=NULL WHERE player_id=?",
                    (p,))
    for p, uid in new_links:
        cur.execute("UPDATE player_identity SET fm_uid=?, fm_method='twin', confidence=0.8 "
                    "WHERE player_id=?", (uid, p))
        cur.execute("INSERT OR IGNORE INTO player_identity"
                    "(player_id, kind, fm_uid, fm_method, confidence) VALUES(?,?,?,'twin',0.8)",
                    (p, band(p), uid))
    con.commit()
    enrich(con, cur, superseded, P)
    # invariants
    v1 = cur.execute("""SELECT COUNT(*) FROM squad_members s JOIN players p ON p.id=s.player_id
        WHERE p.superseded_by IS NOT NULL AND NOT (s.team_id>=800000 AND s.team_id<1000000)
        """).fetchone()[0]
    v2 = cur.execute("""SELECT COUNT(*) FROM (
        SELECT pi.fm_uid FROM squad_members s JOIN player_identity pi ON pi.player_id=s.player_id
        WHERE pi.fm_uid IS NOT NULL AND NOT (s.team_id>=800000 AND s.team_id<1000000)
        GROUP BY pi.fm_uid HAVING COUNT(*)>1)""").fetchone()[0]
    print(f"applied. superseded-yet-squadded: {v1} (must be 0) | "
          f"world squads sharing one fm_uid: {v2} (should be ~0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
