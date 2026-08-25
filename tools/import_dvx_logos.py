#!/usr/bin/env python3
"""
import_dvx_logos.py — real club logos from the DVX Logos megapack (FM2024 + v2/v3 change packs).

Assignment is BY VERIFIED ID FIRST. The pack is keyed by FM club id and so is team_identity, so any
club whose id we have verified takes its own crest before the name matcher runs. The name matcher
only ever sees what is left, which is what it is for — it once handed Liverpool the crest of AFC
Liverpool because 'afc' was being thrown away as noise.
DVX filenames carry the FM club id (dvx24\\clubs\\primary\\<fmid>_<confed>_<nation>.png), and
fm_clubs (Genie export) maps fmid -> name + nation, so logos join to our teams BY DATA, not
guesswork. Space-efficient: only logos that actually match a DB team are extracted, downscaled to
128px WebP (~8KB) in assets/dvx_logos/<fmid>.webp. Later packs override earlier (v3 > v2 > base).

Assignment: a team gets a DVX logo when its current logo_path is NULL, points at a missing file,
or is an RFS 'T_*.png' stand-in. Hand-reconciled API crests (assets/badges) are kept. catalog.json
entries are patched the same way.

    python tools/import_dvx_logos.py --dry     # match + coverage report, no extraction
    python tools/import_dvx_logos.py           # extract, convert, assign (backs up DB + catalog)
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
OUT = REPO / "assets" / "dvx_logos"
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
PACKS = [REPO / "dvx_logos_2024.01.rar",            # base
         REPO / "dvxlogos_fm2024_v2_changes.rar",   # then v2 overrides
         REPO / "dvxlogos_fm2024_v3_changes.rar"]   # then v3 overrides

# 'afc' is NOT in here. It is the only token separating AFC Liverpool (fm id 29036085, a fan-owned
# non-league club) from Liverpool FC (676), and dropping it put a stranger's crest on Liverpool —
# and, through the career seed, on the user's own club.
STOP = {"fc", "cf", "cd", "rc", "ud", "sc", "sad", "calcio", "ssd", "ac", "as", "ss", "de", "club",
        "the", "rcd", "sd", "cp", "und", "sv", "vfl", "vfb", "tsg", "fsv", "us", "acf",
        "ca", "kf", "fk", "nk", "if", "bk", "sk", "ks"}


def toks(s: str) -> frozenset[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w and w not in STOP)


def lkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "",
                  unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def cnorm(x: str) -> str:
    x = (x or "").lower().strip()
    return {"holland": "netherlands", "korea republic": "south korea", "korea (south)": "south korea",
            "usa": "united states", "u.s.a.": "united states", "china pr": "china",
            "republic of ireland": "ireland", "turkiye": "turkey"}.get(x, x)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv

    # 1) index the packs: fmid -> (pack, internal path); later packs override
    pat = re.compile(r"(dvx24\\clubs\\primary\\(\d+)_[a-z]+_[a-z0-9]+\.png)$", re.I)
    dvx: dict[int, tuple[Path, str]] = {}
    for pack in PACKS:
        if not pack.exists():
            print(f"note: {pack.name} missing — skipped")
            continue
        listing = subprocess.run([SEVENZIP, "l", str(pack)], capture_output=True, text=True).stdout
        n = 0
        for line in listing.splitlines():
            m = pat.search(line.replace("/", "\\"))
            if m and "\\small\\" not in m.group(1).lower():
                dvx[int(m.group(2))] = (pack, m.group(1))
                n += 1
        print(f"{pack.name}: {n:,} club logos indexed")
    print(f"unique DVX club ids: {len(dvx):,}")

    con = sqlite3.connect(DB, timeout=60)
    fm = {uid: (nm, cnorm(nat)) for uid, nm, nat in
          con.execute("SELECT uid, name, nation FROM fm_clubs WHERE name IS NOT NULL")}

    # team country = dominant squad nationality (same signal reconcile uses)
    cc: dict[int, Counter] = defaultdict(Counter)
    for tid, nat in con.execute(
            "SELECT s.team_id, p.nationality FROM squad_members s JOIN players p ON p.id=s.player_id "
            "WHERE p.nationality IS NOT NULL"):
        cc[tid][cnorm(nat.split("/")[0])] += 1
    tcountry = {tid: c.most_common(1)[0][0] for tid, c in cc.items()}

    teams, by_lkey, tok_index = {}, defaultdict(list), defaultdict(list)
    for tid, nm, logo in con.execute("SELECT id, name, logo_path FROM teams "
                                     "WHERE name IS NOT NULL AND name<>''"):
        teams[tid] = (nm, logo)
        by_lkey[lkey(nm)].append(tid)
        for w in toks(nm):
            tok_index[w].append(tid)

    def needs_logo(tid: int) -> bool:
        logo = teams[tid][1]
        if not logo:
            return True
        if re.search(r"T_\d+\.(png|webp)$", logo):
            return True
        lp = Path(logo)
        return not (lp if lp.is_absolute() else REPO / lp).exists()

    # 2) match every DVX club (that has an fm_clubs row) to a DB team
    assign: dict[int, int] = {}      # team_id -> fmid
    claimed: set[int] = set()
    exact = fuzzy = 0

    # A VERIFIED ID BEATS ANY NAME. team_identity.fm_club_id was established from squad content by
    # verify_identity_fm, and the megapack is keyed by that same number, so those clubs are settled
    # before the name matcher runs and neither the team nor the crest is available to it afterwards.
    by_id = 0
    for tid, fc in con.execute(
            "SELECT team_id, fm_club_id FROM team_identity WHERE fm_club_id IS NOT NULL"):
        if fc in dvx and tid in teams and tid not in claimed:
            assign[tid] = fc
            claimed.add(tid)
            by_id += 1
    taken_ids = set(assign.values())
    print(f"settled by verified FM club id before any name matching: {by_id:,}")
    for fmid, (pack_ref) in dvx.items():
        if fmid not in fm:
            continue
        nm, nation = fm[fmid]
        cand = by_lkey.get(lkey(nm), [])
        pick = None
        good = [t for t in cand if not tcountry.get(t) or not nation or tcountry[t] == nation]
        if len(good) >= 1:
            pick = max(good, key=lambda t: 0 if needs_logo(t) else -1)
            exact += 1
        else:
            want = toks(nm)
            pool = {t for w in want for t in tok_index.get(w, ())}
            best, bestj = None, 0.0
            for t in pool:
                if nation and tcountry.get(t) and tcountry[t] != nation:
                    continue
                tk = toks(teams[t][0])
                inter = len(want & tk)
                if not inter:
                    continue
                j = inter / len(want | tk)
                if j > bestj:
                    best, bestj = t, j
            if best is not None and bestj >= 0.62:
                pick = best
                fuzzy += 1
        if fmid in taken_ids:
            continue                 # this crest already went to the club whose id it is
        if pick is not None and pick not in claimed:
            assign[pick] = fmid
            claimed.add(pick)

    fillable = {t: f for t, f in assign.items() if needs_logo(t)}
    print(f"matched to DB teams: {len(assign):,} (exact {exact:,}, fuzzy {fuzzy:,}) | "
          f"teams that NEED a logo and got one: {len(fillable):,}")
    if dry:
        return 0

    # 3) extract just the needed logos, convert to 128px webp
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)
    need_ids = {f for f in fillable.values()
                if not (OUT / f"{f}.webp").exists()}
    by_pack: dict[Path, list[str]] = defaultdict(list)
    for f in need_ids:
        pack, internal = dvx[f]
        by_pack[pack].append(internal)
    with tempfile.TemporaryDirectory(dir=str(REPO / "build")) as tmp:
        for pack, names in by_pack.items():
            lst = Path(tmp) / "list.txt"
            lst.write_text("\n".join(names), encoding="utf-8")
            subprocess.run([SEVENZIP, "e", str(pack), f"-o{tmp}", f"@{lst}", "-y"],
                           capture_output=True)
            print(f"extracted {len(names):,} from {pack.name}")
        for f in sorted(need_ids):
            src = Path(tmp) / Path(dvx[f][1]).name
            if not src.exists():
                continue
            try:
                im = Image.open(src)
                im.thumbnail((128, 128), Image.LANCZOS)
                im.save(OUT / f"{f}.webp", "WEBP", quality=88)
            except Exception:
                continue
    made = len(list(OUT.glob("*.webp")))
    print(f"assets/dvx_logos now holds {made:,} logos")

    # 4) assign: teams.logo_path + catalog.json
    shutil.copy2(DB, str(DB) + ".bak-predvx")
    shutil.copy2(CAT, str(CAT) + ".bak-predvx")
    con.execute("BEGIN")
    n = 0
    for tid, fmid in fillable.items():
        p = OUT / f"{fmid}.webp"
        if p.exists():
            # store repo-relative forward-slash paths; the app resolves them against the repo root
            con.execute("UPDATE teams SET logo_path=? WHERE id=?",
                        (p.relative_to(REPO).as_posix(), tid))
            n += 1
    con.commit()
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    patched = 0
    for co in cat["countries"]:
        for lg in co["leagues"]:
            for t in lg["teams"]:
                cur = t.get("logo")
                cp = Path(cur) if cur else None
                stale = (not cur or re.search(r"T_\d+\.(png|webp)$", cur or "")
                         or not (cp if cp.is_absolute() else REPO / cp).exists())
                fmid = assign.get(t["team_id"])
                if stale and fmid and (OUT / f"{fmid}.webp").exists():
                    t["logo"] = (OUT / f"{fmid}.webp").relative_to(REPO).as_posix()
                    patched += 1
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"teams.logo_path updated: {n:,} | catalog entries patched: {patched:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
