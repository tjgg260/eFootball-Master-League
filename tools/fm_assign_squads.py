#!/usr/bin/env python3
"""
fm_assign_squads.py — rebuild squad membership from FM's authoritative Club field. This is THE
database sort: every player goes to the club FM says he plays for, so thin/fragmented records
(Celta with 10 players) get their real full roster and youth players land in U21/U18.

INPUT: an FM export (HTML from Print->Web Page, or a semicolon CSV) carrying at least
    Unique ID (or UID) + Club   (and ideally Squad: First Team / U21 / U18 / ...).
The FM attribute HTML views don't include Club — add the Club (+ Squad) column to the view, or do
a light Name/UID/Club/Squad export of every player. Genie's allplayers.csv also works but is
incomplete (missing some clubs).

    python tools/fm_assign_squads.py <fm_clubs_export.html|.csv> --dry     # show the plan
    python tools/fm_assign_squads.py <fm_clubs_export.html|.csv>           # apply (makes a backup)

Join: FM UID -> our player id (net-new 10_000_000_000+uid, or overlap via face_<uid>). FM Club name
-> our DB team (token-similarity + largest squad, the same matcher reconcile_all uses).
"""
from __future__ import annotations

import html
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"

STOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de", "club",
        "the", "afc", "rcd", "sd", "cp", "und", "sv", "vfl", "vfb", "tsg", "fsv", "us", "acf"}


def toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w and w not in STOP}


def rows_of(path: Path):
    """Yield dict rows from an FM HTML table or a semicolon CSV."""
    if path.suffix.lower() in (".html", ".htm"):
        text = path.read_bytes().decode("utf-8", "replace")
        body = re.split(r"<table[^>]*>", text, maxsplit=1)[-1]
        header = None
        for tr in re.split(r"<tr[^>]*>", body):
            cells = [html.unescape(re.sub(r"<.*?>", "", c)).strip()
                     for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            if not cells:
                continue
            if header is None:
                header = cells
            else:
                yield dict(zip(header, cells))
    else:
        import csv
        import io
        text = path.read_bytes().decode("cp1252", "replace")
        yield from csv.DictReader(io.StringIO(text), delimiter=";")


def youth_level(squad: str) -> str | None:
    s = (squad or "").lower()
    if "18" in s or "u16" in s or "u17" in s:
        return "u18"
    if "21" in s or "23" in s or "19" in s or "reserv" in s or "youth" in s:
        return "u21"
    return None   # first team


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if not args:
        sys.exit("usage: python tools/fm_assign_squads.py <fm_clubs_export.html|.csv> [--dry]")
    src = Path(args[0])
    con = sqlite3.connect(DB)

    # DB player id lookup: uid -> pid
    net = {pid - 10_000_000_000: pid for (pid,) in
           con.execute("SELECT id FROM players WHERE id>=10000000000")}
    overlap = {}
    for pid, face in con.execute("SELECT id, real_face_path FROM players "
                                 "WHERE real_face_path LIKE '%face_%' AND id<10000000000"):
        m = re.search(r"face_(\d+)", face or "")
        if m:
            overlap[int(m.group(1))] = pid

    # DB team index with an inverted token index so matching only scores teams that share a token.
    squad = dict(con.execute("SELECT team_id, COUNT(*) FROM squad_members GROUP BY team_id"))
    teaminfo: dict[int, tuple[set[str], int]] = {}
    tok_index: dict[str, list[int]] = defaultdict(list)
    for tid, nm in con.execute("SELECT id, name FROM teams WHERE name IS NOT NULL AND name<>''"):
        if re.search(r"\b(u\d+|ii|reserve|academy|women|fem)\b", nm, re.I):
            continue
        tk = toks(nm)
        teaminfo[tid] = (tk, squad.get(tid, 0))
        for w in tk:
            tok_index[w].append(tid)

    club_cache: dict[str, int | None] = {}

    def club_to_team(name: str) -> int | None:
        if name in club_cache:
            return club_cache[name]
        want = toks(name)
        cand = {t for w in want for t in tok_index.get(w, ())}
        best, bestscore, bestsq = None, 0.0, -1
        for tid in cand:
            tk, sq = teaminfo[tid]
            inter = len(want & tk)
            if not inter:
                continue
            j = inter / len(want | tk)
            if j > bestscore or (j == bestscore and sq > bestsq):
                best, bestscore, bestsq = tid, j, sq
        club_cache[name] = best if bestscore >= 0.5 else None
        return club_cache[name]

    # read FM: uid -> (club, level)
    ucol = ccol = scol = None
    assign: dict[int, list[int]] = defaultdict(list)   # team_id -> [player_id]
    seen_clubs, unmatched_club, unmatched_player, placed = set(), Counter(), 0, 0
    for r in rows_of(src):
        if ucol is None:
            ucol = "Unique ID" if "Unique ID" in r else "UID" if "UID" in r else None
            ccol = "Club" if "Club" in r else None
            scol = "Squad" if "Squad" in r else None
            if not ucol or not ccol:
                sys.exit(f"export needs a UID and a Club column; got {list(r)[:8]}")
        uid = (r.get(ucol) or "").strip()
        club = (r.get(ccol) or "").strip()
        if not uid.isdigit() or not club or club == "-":
            continue
        pid = net.get(int(uid)) or overlap.get(int(uid))
        if pid is None:
            unmatched_player += 1
            continue
        seen_clubs.add(club)
        tid = club_to_team(club)
        if tid is None:
            unmatched_club[club] += 1
            continue
        # youth level would route to the club's U21/U18 team here; first-team default for now
        assign[tid].append(pid)
        placed += 1

    print(f"FM clubs seen: {len(seen_clubs):,} | matched to a DB team: "
          f"{len(seen_clubs) - len(unmatched_club):,}")
    print(f"players placed: {placed:,} | UID not in DB: {unmatched_player:,} | "
          f"club unmatched: {sum(unmatched_club.values()):,}")
    if unmatched_club:
        print("  top unmatched clubs:", dict(unmatched_club.most_common(8)))
    if dry:
        big = sorted(assign.items(), key=lambda kv: -len(kv[1]))[:8]
        names = dict(con.execute("SELECT id, name FROM teams"))
        print("  sample rebuilt squads:", {names.get(t, t): len(p) for t, p in big})
        return 0

    shutil.copy2(DB, str(DB) + ".bak-preassign")
    con.execute("BEGIN")
    for tid, pids in assign.items():
        con.execute("DELETE FROM squad_members WHERE team_id=?", (tid,))
        con.executemany(
            "INSERT OR REPLACE INTO squad_members(team_id,player_id,squad_number,slot) "
            "VALUES(?,?,?,?)",
            [(tid, pid, i + 1, i) for i, pid in enumerate(pids)])
    con.commit()
    print(f"rebuilt {len(assign):,} club squads from FM ({placed:,} players placed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
