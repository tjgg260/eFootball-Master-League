#!/usr/bin/env python3
"""
fm_import.py (v2) — layer the Football Manager export (allplayers.csv) onto the deduped world,
country- and squad-aware, matching clubs by canonical-player overlap (identity), not fuzzy name.

Priority model (unchanged):
  * player identity + data : eFootball (dt870>dt200) > RFS > FM   (FM only fills net-new players)
  * club / squad membership: FM > eFootball > RFS                 (FM rebuilds squads authoritatively)

What v2 fixes vs v1:
  * DIVISION is garbage in this export (every row = "Jupiler Pro League") -> we use `Based`
    (the club's country) to disambiguate same-named clubs (English "Liverpool" vs Uruguayan
    "Liverpool F.C."). Country-from-name mistakes are what created false-merges before.
  * `Squad` column carries the sub-team: "Liverpool U21" / "Liverpool U18" become their OWN
    teams (base_team_id -> parent senior), so youth no longer stack onto the first team.
  * Senior FM teams match an existing eF/RFS team by CANONICAL PLAYER OVERLAP (shared real
    players), claim-once. Man City(FM) overlaps Manchester City(eF) -> merge, no duplicate.
    English Everton overlaps English Everton, Chilean overlaps Chilean -> each its own, no fuse.
  * Every FM-placed player has ALL prior memberships deleted before FM membership is inserted,
    so no player is ever left in two clubs (the 16.8k multi-homing bug).

Post-step: merge pre-existing duplicate EXISTING teams only when they share >=3 real members
(identity-confirmed) — folds eF-vs-RFS dupes like "Everton FC" x2 without touching genuinely
distinct same-name clubs (Botafogo-RJ vs Botafogo-PB share nobody).

Writes master.db (back it up first).
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import unicodedata
from collections import defaultdict, Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CSV_PATH = REPO / "allplayers.csv"
FACE_DIR = r"C:\Users\tjgg2\Downloads\eFootball Master League\facepack\sortitoutsi\faces"
FACES_ON_DISK = REPO / "facepack" / "sortitoutsi" / "faces"

FM_PLAYER_BASE = 10_000_000_000
FM_TEAM_BASE = 4_000_000
CURRENT_YEAR = 2026
OVERLAP_MIN = 2          # shared canonical players to auto-match a senior team to an existing one
DUP_MERGE_MIN = 3        # shared members to merge two pre-existing duplicate teams

CLUB_STOP = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "club", "de", "the", "fk", "if", "bk",
             "us", "as", "rc", "1", "1899", "1900"}
YOUTH_RE = re.compile(r"\b(u\d{2}|under\s?\d{2}|reserves?|youth|academy|acad|ii|b team|beta)\b", re.I)
FM_POS = {"GK": "GK", "D C": "CB", "D R": "RB", "D L": "LB", "D RC": "CB", "D LC": "CB",
          "D RLC": "CB", "WB R": "RB", "WB L": "LB", "DM": "DMF", "M C": "CMF", "M R": "RMF",
          "M L": "LMF", "M RC": "CMF", "M LC": "CMF", "AM C": "AMF", "AM R": "RMF", "AM L": "LMF",
          "AM RC": "AMF", "AM LC": "AMF", "AM RLC": "AMF", "ST": "CF", "ST C": "CF"}

# country alias -> canonical, so `Based` and stored nationality compare cleanly
COUNTRY_ALIAS = {
    "england": "england", "english": "england", "uk": "england",
    "scotland": "scotland", "wales": "wales", "n.ireland": "n.ireland",
    "usa": "usa", "united states": "usa", "korea republic": "south korea",
    "china pr": "china", "ivory coast": "cote divoire", "cote d'ivoire": "cote divoire",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def club_key(s: str) -> str:
    return " ".join(t for t in norm(s).split() if t not in CLUB_STOP)


def ccountry(s: str) -> str:
    n = norm(s)
    return COUNTRY_ALIAS.get(n, n)


def ef_pos(fm: str) -> str:
    first = fm.split(",")[0].strip()
    if first in FM_POS:
        return FM_POS[first]
    for k, v in FM_POS.items():
        if first.startswith(k.split()[0]):
            return v
    return "CMF"


def overall_from_rating(best: str) -> int | None:
    m = re.match(r"([\d.]+)%", (best or "").strip())
    if not m:
        return None
    return max(40, min(99, round(40 + float(m.group(1)) / 100 * 59)))


def year(dob: str) -> int | None:
    m = re.search(r"(\d{4})", dob or "")
    return int(m.group(1)) if m else None


def main() -> int:
    con = sqlite3.connect(DB)

    # UID -> canonical player id (from real_face_path we already stamped during facepack matching)
    uid2canon = {}
    for pid, face in con.execute("SELECT id, real_face_path FROM players WHERE real_face_path IS NOT NULL"):
        m = re.search(r"face_(\d+)\.png$", face or "")
        if m:
            uid2canon[int(m.group(1))] = pid

    # existing teams: id, name, ck; members set; modal-nationality country proxy
    existing = {}   # tid -> {name, ck, members:set, country}
    for tid, name in con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''"):
        existing[tid] = {"name": name, "ck": club_key(name), "members": set(), "country": None}
    for tid, pid in con.execute("SELECT team_id, player_id FROM squad_members"):
        if tid in existing:
            existing[tid]["members"].add(pid)
    natof = dict(con.execute("SELECT id, nationality FROM players WHERE nationality IS NOT NULL"))
    for tid, e in existing.items():
        nats = [natof[p] for p in e["members"] if p in natof and natof[p]]
        if nats:
            e["country"] = ccountry(Counter(nats).most_common(1)[0][0])
    ck_index = defaultdict(list)     # ck -> [tid,...] existing candidates (senior)
    for tid, e in existing.items():
        ck_index[e["ck"]].append(tid)

    faces = {int(p.stem.split("_")[1]) for p in FACES_ON_DISK.glob("face_*.png")} if FACES_ON_DISK.exists() else set()

    # ---- parse CSV, group rows into FM teams keyed by (country, team-name) ----
    text = CSV_PATH.read_bytes().decode("cp1252", "replace")
    rows = csv.reader(io.StringIO(text), delimiter=";")
    header = next(rows)
    c = {n: i for i, n in enumerate(header)}

    fm_teams = {}   # key -> {name, country, senior:bool, parent_key, rows:[rowdict]}
    stats = Counter()

    def get(r, col):
        return r[c[col]].strip() if col in c and len(r) > c[col] else ""

    for r in rows:
        if len(r) <= c["Unique ID"] or not get(r, "Unique ID").isdigit():
            continue
        club = get(r, "Club")
        if not club or club.lower() in ("free agent", "-", ""):
            stats["no_club"] += 1
            continue
        country = ccountry(get(r, "Based")) or ccountry(get(r, "Nation").split("/")[0])
        squad = get(r, "Squad")
        sub = squad if squad not in ("", "-") else ""
        if not sub or norm(sub) == norm(club):
            teamname, senior, parent_key = club, True, None
        else:
            teamname, senior, parent_key = sub, False, (country, norm(club))
            if not YOUTH_RE.search(sub) and norm(club) not in norm(sub):
                # a `Squad` that's neither youth nor a variant of the club: treat as its own senior side
                senior, parent_key = True, None
        key = (country, norm(teamname))
        t = fm_teams.get(key)
        if t is None:
            t = fm_teams[key] = {"name": teamname, "country": country, "senior": senior,
                                 "parent_key": parent_key, "rows": []}
        t["rows"].append({
            "uid": int(get(r, "Unique ID")),
            "name_raw": get(r, "Name"),
            "pos": ef_pos(get(r, "Position")),
            "ovr": overall_from_rating(get(r, "Best Rating")),
            "nat": get(r, "Nation"),
            "age": (CURRENT_YEAR - year(get(r, "Date Of Birth"))) if year(get(r, "Date Of Birth")) else None,
        })

    # ---- resolve each FM team to an existing tid or a new one ----
    claimed = set()
    resolved = {}        # key -> tid
    new_teams = {}       # tid -> (name, base_team_id)
    next_team = FM_TEAM_BASE

    def canon_pids(rows):
        return {uid2canon[rw["uid"]] for rw in rows if rw["uid"] in uid2canon}

    # seniors first (so youth can point base_team_id at a resolved parent)
    seniors = [(k, t) for k, t in fm_teams.items() if t["senior"]]
    youths = [(k, t) for k, t in fm_teams.items() if not t["senior"]]

    for key, t in seniors:
        country, ckey = t["country"], club_key(t["name"])
        overlap_pids = canon_pids(t["rows"])
        cands = [tid for tid in ck_index.get(ckey, []) if tid not in claimed]
        best, best_score = None, 0
        for tid in cands:
            score = len(existing[tid]["members"] & overlap_pids)
            if score > best_score:
                best, best_score = tid, score
        if best is not None and best_score >= OVERLAP_MIN:
            resolved[key] = best; claimed.add(best); stats["match_overlap"] += 1
        else:
            # thin/no overlap -> name+country fallback, but only if unambiguous & country-compatible
            compat = [tid for tid in cands
                      if existing[tid]["country"] is None or country == "" or existing[tid]["country"] == country]
            if len(compat) == 1:
                resolved[key] = compat[0]; claimed.add(compat[0]); stats["match_name"] += 1
            else:
                resolved[key] = next_team; new_teams[next_team] = (t["name"], None)
                next_team += 1; stats["new_senior"] += 1

    for key, t in youths:
        parent_tid = resolved.get(t["parent_key"])
        resolved[key] = next_team
        new_teams[next_team] = (t["name"], parent_tid)
        next_team += 1; stats["new_youth"] += 1

    # ---- build player records + squad membership ----
    new_players = []
    squads = []          # (tid, pid)
    for key, t in fm_teams.items():
        tid = resolved[key]
        for rw in t["rows"]:
            uid = rw["uid"]
            if uid in uid2canon:
                pid = uid2canon[uid]; stats["overlap_player"] += 1
            else:
                pid = FM_PLAYER_BASE + uid
                raw = rw["name_raw"]
                sur, first = (p.strip() for p in raw.split(",", 1)) if "," in raw else (raw, "")
                name = f"{first} {sur}".strip()
                face_path = str(Path(FACE_DIR) / f"face_{uid}.png") if uid in faces else None
                new_players.append((pid, pid, 1, name, rw["pos"], rw["ovr"], rw["nat"], rw["age"], face_path))
                stats["net_new"] += 1
            squads.append((tid, pid))

    print(f"FM rows -> overlap(canonical): {stats['overlap_player']:,}  net-new: {stats['net_new']:,}  "
          f"skipped(no club): {stats['no_club']:,}")
    print(f"teams: matched by overlap {stats['match_overlap']:,}, by name {stats['match_name']:,}; "
          f"new senior {stats['new_senior']:,}, new youth/B {stats['new_youth']:,}")

    con.execute("BEGIN")
    con.executemany("INSERT OR REPLACE INTO teams(id,game_team_id,base_team_id,is_custom,name) VALUES(?,?,?,1,?)",
                    [(tid, tid, base, name) for tid, (name, base) in new_teams.items()])
    con.executemany("INSERT OR REPLACE INTO players"
                    "(id,game_pid,is_custom,name,position,overall_rating,nationality,age,real_face_path) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", new_players)

    # AUTHORITATIVE squads: clear FM-covered teams AND every FM-placed player's other memberships
    fm_tids = {tid for tid, _ in squads}
    fm_pids = {pid for _, pid in squads}

    def del_in(col, ids):
        ids = list(ids)
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            con.execute(f"DELETE FROM squad_members WHERE {col} IN ({','.join('?'*len(chunk))})", chunk)

    del_in("team_id", fm_tids)
    del_in("player_id", fm_pids)

    seen, sm, slot = set(), [], defaultdict(int)
    for tid, pid in squads:
        if (tid, pid) in seen:
            continue
        seen.add((tid, pid))
        sm.append((tid, pid, slot[tid], slot[tid]))
        slot[tid] += 1
    con.executemany("INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot) VALUES(?,?,?,?)", sm)
    con.commit()
    print(f"wrote {len(new_players):,} net-new players, {len(new_teams):,} teams, {len(sm):,} FM memberships.")

    # ---- post-step: merge pre-existing duplicate teams (identity-confirmed) ----
    merges = merge_existing_dupes(con)
    print(f"merged {merges:,} pre-existing duplicate teams (>= {DUP_MERGE_MIN} shared members).")

    # ---- report ----
    multi = con.execute("SELECT COUNT(*) FROM (SELECT player_id FROM squad_members "
                        "GROUP BY player_id HAVING COUNT(DISTINCT team_id)>1)").fetchone()[0]
    print(f"\nDB totals: players {con.execute('SELECT COUNT(*) FROM players').fetchone()[0]:,}, "
          f"teams {con.execute('SELECT COUNT(*) FROM teams').fetchone()[0]:,}, "
          f"squad rows {con.execute('SELECT COUNT(*) FROM squad_members').fetchone()[0]:,}")
    print(f"players in >1 club now: {multi:,}  (want 0)")
    con.close()
    return 0


def merge_existing_dupes(con) -> int:
    """Merge teams with the same club_key that share >= DUP_MERGE_MIN members into the larger one."""
    sizes = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    members = defaultdict(set)
    for tid, pid in con.execute("SELECT team_id, player_id FROM squad_members"):
        members[tid].add(pid)
    byck = defaultdict(list)
    for tid, name in con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''"):
        byck[club_key(name)].append(tid)
    merged = 0
    for ckey, tids in byck.items():
        if len(tids) < 2:
            continue
        tids = sorted(tids, key=lambda t: -sizes.get(t, 0))
        keep = tids[0]
        for other in tids[1:]:
            if sizes.get(other, 0) == 0:
                shared = 1  # empty stub of same club -> safe to drop/fold
            else:
                shared = len(members.get(keep, set()) & members.get(other, set()))
            if shared >= 1 and (sizes.get(other, 0) == 0 or shared >= DUP_MERGE_MIN):
                # move any members not already in keep, then delete the duplicate team
                con.execute("UPDATE OR IGNORE squad_members SET team_id=? WHERE team_id=?", (keep, other))
                con.execute("DELETE FROM squad_members WHERE team_id=?", (other,))
                con.execute("UPDATE teams SET base_team_id=? WHERE base_team_id=?", (keep, other))
                con.execute("DELETE FROM teams WHERE id=?", (other,))
                members[keep] |= members.get(other, set())
                merged += 1
    con.commit()
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
