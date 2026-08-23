#!/usr/bin/env python3
"""
import_dvx_meta.py — country FLAGS and COMPETITION LOGOS from the DVX pack, matched by id.

Flags: dvx24/flags/primary/<id>_<region>_<trigram>.png -> assets/dvx_flags/<trigram>.webp, then
each catalog country gets a "flag" via its FIFA trigram.
Competition logos: catalog league -> its clubs -> team_identity.fm_club_id ->
fm_clubs.division_id (majority vote) -> dvx24/competitions/primary/<division_id>_*.png ->
assets/dvx_comps/<league_id>.webp, stored on the league as "comp_logo". Pure id joins, no name
guessing.

    python tools/import_dvx_meta.py --dry
    python tools/import_dvx_meta.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CAT = REPO / "build" / "catalog.json"
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
PACKS = [REPO / "dvx_logos_2024.01.rar", REPO / "dvxlogos_fm2024_v2_changes.rar",
         REPO / "dvxlogos_fm2024_v3_changes.rar"]
FLAGS_OUT = REPO / "assets" / "dvx_flags"
COMPS_OUT = REPO / "assets" / "dvx_comps"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assign_uran_faces import NAT2CODE  # noqa: E402  (country name -> FIFA trigram)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    import unicodedata

    def key(s):
        s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
        return s.replace("'", " ").strip()

    # index both asset families across packs (later packs override)
    flag_by_tri, comp_by_id = {}, {}
    fpat = re.compile(r"dvx24/flags/primary/(\d+)_[a-z]+_([a-z]{3})\.png$")
    cpat = re.compile(r"dvx24/competitions/primary/(\d+)_[a-z_]+\.png$")
    for pack in PACKS:
        if not pack.exists():
            continue
        lst = subprocess.run([SEVENZIP, "l", str(pack)], capture_output=True,
                             text=True).stdout.replace("\\", "/")
        for line in lst.splitlines():
            if "/small" in line or "@2x" in line:
                continue
            if m := fpat.search(line):
                flag_by_tri[m.group(2).upper()] = (pack, m.group(0))
            elif m := cpat.search(line):
                comp_by_id[int(m.group(1))] = (pack, m.group(0))
    print(f"flags indexed: {len(flag_by_tri)} | competition logos indexed: {len(comp_by_id)}")

    con = sqlite3.connect(DB, timeout=60)
    cat = json.loads(CAT.read_text(encoding="utf-8"))

    # league -> comp id: the Genie clubs export's Division ID is junk ('1' for everyone), so the
    # only trustworthy source is the pack's OWN alternative config.xml (39 name-slug -> comp-id
    # records: La Liga=67, UCL, K League...). Leagues without one fall back to the country flag
    # in the UI. A Genie COMPETITIONS export (name + uid) would unlock all 2,231 logos later.
    slug_to_id = {}
    cfg = REPO / "build" / "dvxmeta2" / "dvx24" / "competitions" / "alternative" / "config.xml"
    if cfg.exists():
        for slug, cid in re.findall(r'from="([^"]+)" to="graphics/pictures/comp/(\d+)/logo"',
                                    cfg.read_text(encoding="utf-8", errors="replace")):
            slug_to_id.setdefault(re.sub(r"_alt-?\d*$", "", slug), int(cid))

    def lgkey(s):
        s = key(s)
        s = re.sub(r"(reg\.?season|\(simulated\))", " ", s)
        # keep digit tokens: they distinguish La Liga from La Liga 2
        return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split()
                         if len(w) > 1 or w.isdigit())

    want_flags, want_comps = {}, {}      # trigram -> country names / league_id -> comp_id
    for co in cat["countries"]:
        tri = NAT2CODE.get(key(co["name"]))
        if tri and tri in flag_by_tri:
            want_flags.setdefault(tri, []).append(co["name"])
        ctri = (tri or "").lower()
        for lg in co["leagues"]:
            if not lg.get("league_id"):
                continue
            want = lgkey(lg["name"])
            # STRICT matching (the loose token-overlap version handed the Champions League
            # logo to every domestic league named "... League"). A nationless slug is a
            # continental/tournament logo: only an exact name match may take it. A
            # nation-scoped slug must be for THIS country, and may tolerate at most one
            # missing token — never an extra one.
            best = None                                # (score, cid): exact=2 beats loose=1
            for slug, cid in slug_to_id.items():
                if cid not in comp_by_id:
                    continue
                parts = slug.split("_")
                nation = parts[1] if len(parts) > 2 and len(parts[1]) == 3 else None
                stoks = frozenset(w for w in parts[2 if nation else 1:]
                                  if len(w) > 1 or w.isdigit())
                if not stoks:
                    continue
                if nation:
                    if not (ctri and nation == ctri):
                        continue
                    if stoks == want:
                        score = 2
                    elif stoks <= want and len(want - stoks) <= 1:
                        score = 1
                    else:
                        continue
                else:
                    if stoks != want:
                        continue
                    score = 2
                if best is None or score > best[0]:
                    best = (score, cid)
            if best is not None:
                want_comps[lg["league_id"]] = best[1]
    print(f"countries with a flag: {sum(len(v) for v in want_flags.values())} | "
          f"leagues with a competition logo: {len(want_comps)}")
    if dry:
        return 0

    from PIL import Image
    FLAGS_OUT.mkdir(parents=True, exist_ok=True)
    COMPS_OUT.mkdir(parents=True, exist_ok=True)
    by_pack = defaultdict(list)
    for tri in want_flags:
        pack, internal = flag_by_tri[tri]
        by_pack[pack].append(internal)
    for lid, div in want_comps.items():
        pack, internal = comp_by_id[div]
        by_pack[pack].append(internal)
    extracted = {}
    with tempfile.TemporaryDirectory(dir=str(REPO / "build")) as tmp:
        for pack, names in by_pack.items():
            lst = Path(tmp) / "l.txt"
            lst.write_text("\n".join(n.replace("/", "\\") for n in set(names)), encoding="utf-8")
            subprocess.run([SEVENZIP, "e", str(pack), f"-o{tmp}", f"@{lst}", "-y"],
                           capture_output=True)
        def conv(internal, dest, size):
            src = Path(tmp) / Path(internal).name
            if not src.exists() or dest.exists():
                return dest.exists()
            im = Image.open(src)
            im.thumbnail((size, size), Image.LANCZOS)
            im.save(dest, "WEBP", quality=86)
            return True
        for tri in want_flags:
            if conv(flag_by_tri[tri][1], FLAGS_OUT / f"{tri}.webp", 96):
                extracted[tri] = f"assets/dvx_flags/{tri}.webp"
        for lid, div in want_comps.items():
            if conv(comp_by_id[div][1], COMPS_OUT / f"{lid}.webp", 128):
                extracted[lid] = f"assets/dvx_comps/{lid}.webp"

    shutil.copy2(CAT, str(CAT) + ".bak-premeta")
    nf = nc = 0
    for co in cat["countries"]:
        tri = NAT2CODE.get(key(co["name"]))
        if tri and tri in extracted:
            co["flag"] = extracted[tri]
            nf += 1
        for lg in co["leagues"]:
            lid = lg.get("league_id")
            if lid in extracted:
                lg["comp_logo"] = extracted[lid]
                nc += 1
            else:
                # a league that no longer earns a logo must LOSE its old (possibly wrong) one
                lg.pop("comp_logo", None)
    CAT.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    print(f"catalog patched: {nf} country flags, {nc} league competition logos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
