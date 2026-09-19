#!/usr/bin/env python3
r"""
game_emblems.py — club crests from eFootball's own paks, with installed mods (EvoMod) on top.

Where the game keeps them
    ui/Data/Symbol/Emblem/e_<Team.bin id, 6 digits>_<r|f>[_<variant letter>][_l|_ll].uasset
    BC7 Texture2D: no suffix 128px, _l 256px, _ll 512px. Vanilla ships them in pak\pc1000_console_win.
    A club has a REAL crest (_r) and/or a FAKE one (_f); Team.bin byte 115 says which the game shows:
    bit 0 or bit 2 set -> _r, otherwise _f. Checked against every club in dt200 (981 records): the
    flag and the suffixes that exist agree for all 954 that carry any crest.
    Some clubs (e.g. Manchester United, id 100) ship ONLY variant-lettered crests — b/e/w/s seen so
    far, presumably different kit/background colourways — never a bare e_<id>_r.uasset. The variant
    letter is ignored: any one of them is an acceptable crest, so the size choice alone still picks
    the biggest available regardless of which variant it came from.

Mods
    PesConsole\Content\Paks\~mods\*.utoc load over the vanilla paks and replace assets by path.
    EvoMod_BASE_P ships 1,201 crest files for 452 clubs — real crests put into the fake (_f) slots of
    unlicensed clubs, and national FA crests in place of flags. Its containers are IoStore v3 whose
    directory index is stored in plain text although the header flags the container as encrypted;
    the data blocks ARE encrypted with the game's key. ModContainer reads both kinds.
    Precedence follows the game: mods beat vanilla, and among mods the later name wins.

How a crest is chosen for one club
    1. the suffix the game shows (Team.bin byte 115); the other suffix only if that one exists nowhere
    2. the highest-precedence container that has that suffix at any size
    3. the largest size in THAT container (a mod's 256px beats vanilla's 512px of a different picture)
    Written as PNG, downscaled to at most 256px (the app never shows a crest bigger).

What it writes
    build/game_emblems/<Team.bin id>.png   Konami's or the mod author's art: build/ is gitignored
                                           and the release does not ship it.
    build/game_emblems/manifest.json       which container/asset each PNG came from; a club whose
                                           source changed (a mod installed or removed) is decoded again.
    teams.logo_path                        'build/game_emblems/<id>.png' for every club that resolves:
                                           world clubs by their own id, career copies by base_team_id,
                                           U21/U18 sides by their parent. A logo_path that points
                                           anywhere else (set by hand, or by another tool) is kept.
    build/game_catalog.json                the New Career picker's 'logo', same rule.

    python tools/game_emblems.py --dry            # resolve and report; decode nothing, write nothing
    python tools/game_emblems.py                  # decode, write paths
    python tools/game_emblems.py --game-dir <eFootball>

Idempotent. Close the app first — it holds the database open.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from game_faces import AES_BACKEND, HAVE_PIL, iostore   # noqa: E402  (AES shim + vendored reader)

DB = REPO / "build" / "game_world.db"
CATALOG = REPO / "build" / "game_catalog.json"
BASE_CPK = REPO / "dt200_console_all.cpk"
OUT = REPO / "build" / "game_emblems"
REL = "build/game_emblems"
MAX_PX = 256
EMBLEM = re.compile(r"/ui/Data/Symbol/Emblem/e_(\d{6})_([rf])(?:_[a-z])?(_l{1,2})?\.uasset$")
SIZE_RANK = {"": 0, "_l": 1, "_ll": 2}


class ModContainer(iostore.Container):
    """iostore.Container for mod-built IoStore files: the directory index may be plaintext even when
    the container flags say encrypted (EvoMod's v3 containers). The data blocks stay encrypted."""

    def __init__(self, utoc: str):
        real = iostore._dec

        def maybe_plain(d):
            n = struct.unpack_from("<i", d, 0)[0] if len(d) >= 4 else -1
            return bytes(d) if 0 < n < 1024 and bytes(d[4:7]) == b"../" else real(d)

        iostore._dec = maybe_plain
        try:
            super().__init__(utoc)
        finally:
            iostore._dec = real


def default_game_dir() -> Path:
    from steam_paths import efootball_dir
    return efootball_dir()


def containers(game: Path) -> list[tuple[str, iostore.Container]]:
    """Every readable container that carries crests, highest precedence first:
    ~mods (later name wins), then vanilla."""
    out = []
    mods = sorted((game / "PesConsole" / "Content" / "Paks" / "~mods").glob("*.utoc"), reverse=True)
    vanilla = sorted((game / "pak").glob("*.utoc"), reverse=True)
    for utoc in mods + vanilla:
        try:
            c = ModContainer(str(utoc))
        except Exception as ex:  # noqa: BLE001 — an unreadable mod never stops the rest
            print(f"   skipped {utoc.name}: {ex.__class__.__name__}")
            continue
        if any(EMBLEM.search(p) for p in c.paths):
            label = ("~mods/" if utoc.parent.name == "~mods" else "pak/") + utoc.stem
            out.append((label, c))
    return out


def crest_index(found: list[tuple[str, iostore.Container]]):
    """team id -> suffix -> [(precedence, label, container, size rank, path)]"""
    idx: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for prec, (label, c) in enumerate(found):
        for path in c.paths:
            m = EMBLEM.search(path)
            if m:
                idx[int(m.group(1))][m.group(2)].append((prec, label, c, SIZE_RANK[m.group(3) or ""], path))  # group(3) is now the size suffix
    return idx


def team_flags(cpk: Path) -> dict[int, int]:
    """Team.bin id -> byte 115 (which crest the game shows)."""
    import game_world
    data = game_world.Archive("dt200", cpk).table("Team.bin")
    if data is None:
        raise SystemExit(f"{cpk}: no Team.bin")
    return {struct.unpack_from("<I", data, r * 1600 + 12)[0]: data[r * 1600 + 115]
            for r in range(len(data) // 1600)}


def choose(idx, tid: int, flag: int | None):
    """(label, container, path) of the crest the game would show for this club, or None."""
    per = idx.get(tid)
    if not per:
        return None
    want = "r" if flag is not None and flag & 0b101 else "f"
    options = per.get(want) or per.get("f" if want == "r" else "r")
    if not options:
        return None
    best_prec = min(o[0] for o in options)
    _p, label, c, _rank, path = max((o for o in options if o[0] == best_prec), key=lambda o: o[3])
    return label, c, path


def decode(c: iostore.Container, path: str, out: Path) -> bool:
    pkg = c.read(path)
    bulk = path[:-len(".uasset")] + ".ubulk"
    ubulk = c.read(bulk) if c.resolve(bulk) is not None else None
    img, _info = iostore.texture_to_image(pkg, ubulk)
    if img is None:
        return False
    if max(img.size) > MAX_PX:
        from PIL import Image
        img = img.resize((MAX_PX, MAX_PX * img.size[1] // img.size[0]), Image.LANCZOS)
    tmp = out.with_suffix(".tmp.png")
    img.save(tmp)
    tmp.replace(out)
    return True


def ours(path: str | None) -> bool:
    """A logo_path this tool may overwrite: empty, or one it wrote."""
    return not path or path.replace("\\", "/").startswith(REL + "/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--game-dir", default=None, help="the eFootball install folder (default: found via Steam)")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--catalog", default=str(CATALOG))
    ap.add_argument("--dt200", default=str(BASE_CPK), help="the dt200 the world was read from (for Team.bin)")
    args = ap.parse_args()
    if not HAVE_PIL:
        sys.exit("Pillow is needed to decode crests (BC7)")

    game = Path(args.game_dir) if args.game_dir else default_game_dir()
    t0 = time.time()
    found = containers(game)
    if not found:
        sys.exit(f"no crests found under {game}\\pak or its ~mods — pass --game-dir <eFootball>")
    idx = crest_index(found)
    per_source: dict[str, int] = defaultdict(int)
    for per in idx.values():
        for opts in per.values():
            for o in opts:
                per_source[o[1]] += 1
    print(f"crest assets: {', '.join(f'{k} {v:,}' for k, v in per_source.items())}; "
          f"{len(idx):,} clubs ({time.time() - t0:.1f}s, AES via {AES_BACKEND})")

    flags = team_flags(Path(args.dt200))
    con = sqlite3.connect(args.db)
    teams = con.execute("SELECT id, game_team_id, base_team_id, parent_team_id, logo_path FROM teams").fetchall()
    by_id = {t[0]: t for t in teams}

    def game_id(tid: int, depth: int = 0) -> int | None:
        _i, g, b, parent, _l = by_id[tid]
        for x in (g, b, tid):
            if x in flags:
                return x
        if parent and parent in by_id and depth < 3:
            return game_id(parent, depth + 1)
        return None

    resolved: dict[int, int] = {}                     # world team id -> Team.bin id with a crest
    picks: dict[int, tuple] = {}                      # Team.bin id -> (label, container, path)
    no_game_id = no_crest = 0
    for tid, *_ in teams:
        gid = game_id(tid)
        if gid is None:
            no_game_id += 1
            continue
        if gid not in picks:
            pick = choose(idx, gid, flags.get(gid))
            if pick is None:
                no_crest += 1
                continue
            picks[gid] = pick
        resolved[tid] = gid
    from_mods = sum(1 for p in picks.values() if p[0].startswith("~mods/"))
    print(f"world clubs {len(teams):,}: {len(resolved):,} get a crest "
          f"({len(picks):,} distinct, {from_mods} from mods), {no_crest} have none in the game, "
          f"{no_game_id} have no eFootball club to take one from")

    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    todo = [gid for gid, (label, _c, path) in picks.items()
            if manifest.get(str(gid)) != f"{label}|{path}" or not (OUT / f"{gid}.png").exists()]
    updates = [(f"{REL}/{resolved[t[0]]}.png", t[0]) for t in teams
               if t[0] in resolved and ours(t[4]) and t[4] != f"{REL}/{resolved[t[0]]}.png"]
    kept = sum(1 for t in teams if t[0] in resolved and not ours(t[4]))
    print(f"crests to decode {len(todo):,}; team rows to update {len(updates):,}"
          + (f"; {kept} clubs keep a logo set elsewhere" if kept else ""))
    if args.dry:
        print("--dry: nothing decoded, nothing written.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    failed: set[int] = set()
    t0 = time.time()
    for gid in todo:
        label, c, path = picks[gid]
        try:
            if decode(c, path, OUT / f"{gid}.png"):
                manifest[str(gid)] = f"{label}|{path}"
            else:
                failed.add(gid)
        except Exception as ex:  # noqa: BLE001 — one bad texture never stops the rest
            failed.add(gid)
            if len(failed) <= 5:
                print(f"   {gid}: {ex!r}")
    manifest_path.write_text(json.dumps(manifest, indent=0, sort_keys=True), encoding="utf-8")
    print(f"decoded {len(todo) - len(failed):,} PNGs into {REL} ({time.time() - t0:.0f}s), "
          f"{len(failed)} could not be decoded")

    updates = [(p, t) for p, t in updates if resolved[t] not in failed]
    con.executemany("UPDATE teams SET logo_path=? WHERE id=?", updates)
    con.commit()
    con.close()
    print(f"teams.logo_path written for {len(updates):,} clubs")

    cat_path = Path(args.catalog)
    if cat_path.exists():
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        n = 0
        for country in cat.get("countries", []):
            for league in country.get("leagues", []):
                for team in league.get("teams", []):
                    gid = resolved.get(team.get("team_id"))
                    if gid is not None and gid not in failed and ours(team.get("logo")):
                        path = f"{REL}/{gid}.png"
                        if team.get("logo") != path:
                            team["logo"] = path
                            n += 1
        if n:
            tmp = cat_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(cat_path)
        print(f"catalog: {n:,} clubs given a crest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
