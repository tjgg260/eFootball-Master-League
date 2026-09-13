#!/usr/bin/env python3
"""
game_faces.py — player portraits from eFootball's own UI thumbnails.

The game ships a 180x180 head shot for its players inside pak\\pc1000_console_win (UE IoStore,
Zlib, AES): ui/Data/Thumbnail/Player/<PID>_.uasset, and Variation2022/<VID>_.uasset for variant
cards, named by the external PID (Player.bin bytes 8-15). The container reader and the texture
decoder are the eFootball Player Editor's iostore.py, vendored in tools/vendor/efootball-player-tool/.

What it writes
    build/game_faces/<PID>.png   one per PID some player resolves to. Konami's art: build/ is
                                 gitignored and the release does not ship it.
    players.game_face_path       'build/game_faces/<PID>.png'. The app shows it before every other
                                 portrait except the owner's own custom_faces/.

How a player resolves to a PID (first hit wins)
    1. its own record: players.game_pid, then players.base_pid, then player_identity.ef_pid
    2. career-band copies only. A save's squad is copied by name and carries no PID of its own,
       so it takes the one world player with a thumbnail whose accent-folded name and nationality
       match, and whose age is within 2 where both are known. Two candidates (Arsenal's 'Gabriel')
       is ambiguous and left without a face rather than guessed.

    python tools/game_faces.py --dry          # resolve and report; decode nothing, write nothing
    python tools/game_faces.py                # decode missing PNGs, back up master.db, write paths
    python tools/game_faces.py --pak <dir>    # another eFootball\\pak folder

Idempotent: PNGs already on disk are not decoded again, and a player whose path is already right is
not rewritten. Close the app first — it holds the database open.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "efootball-player-tool"))
import iostore  # noqa: E402

DB = REPO / "build" / "master.db"
OUT = REPO / "build" / "game_faces"
DEFAULT_PAK = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\pak")
CONTAINER = "pc1000_console_win.utoc"
HEAD = re.compile(r"/ui/Data/Thumbnail/Player/(Variation\d+/)?(\d+)_\.uasset$")


def is_career_band(pid: int) -> bool:
    # CLAUDE.md: players 20M-700M and 45-46B belong to a save, never to the world.
    return 20_000_000 <= pid < 700_000_000 or 45_000_000_000 <= pid < 47_000_000_000


def fold(name: str | None) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = s.replace("ø", "o").replace("Ø", "O").replace("ß", "ss").replace("đ", "d").replace("ł", "l")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def head_paths(container: iostore.Container) -> dict[int, str]:
    """PID -> head thumbnail path; the base card's head beats a variation's."""
    heads: dict[int, str] = {}
    for path in container.paths:
        m = HEAD.search(path)
        if m and (m.group(1) is None or int(m.group(2)) not in heads):
            heads[int(m.group(2))] = path
    return heads


def decode(container: iostore.Container, path: str, out: Path) -> bool:
    pkg = container.read(path)
    bulk = path[:-len(".uasset")] + ".ubulk"
    ubulk = container.read(bulk) if container.resolve(bulk) is not None else None
    img, _info = iostore.texture_to_image(pkg, ubulk)
    if img is None:
        return False
    tmp = out.with_suffix(".tmp.png")
    img.save(tmp)
    tmp.replace(out)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--pak", default=str(DEFAULT_PAK))
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    utoc = Path(args.pak) / CONTAINER
    if not utoc.exists():
        sys.exit(f"{utoc} not found — pass --pak <eFootball>\\pak")
    t0 = time.time()
    container = iostore.Container(str(utoc))
    heads = head_paths(container)
    print(f"{CONTAINER}: {len(heads):,} player head thumbnails ({time.time() - t0:.1f}s)")

    con = sqlite3.connect(args.db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(players)")}
    has_col = "game_face_path" in cols
    players = con.execute(
        "SELECT id, game_pid, base_pid, name, nationality, age, "
        + ("game_face_path" if has_col else "NULL") + " FROM players").fetchall()
    ef_pid = dict(con.execute("SELECT player_id, ef_pid FROM player_identity WHERE ef_pid IS NOT NULL"))

    # 1. a record's own PID
    resolved: dict[int, int] = {}
    for pid, game_pid, base_pid, *_ in players:
        for candidate in (game_pid, base_pid, ef_pid.get(pid)):
            if candidate in heads:
                resolved[pid] = candidate
                break

    # 2. career copies by name + nationality (+ age) against world players that resolved
    world = defaultdict(set)
    for pid, game_pid, _b, name, nat, age, _f in players:
        if pid in resolved and not is_career_band(game_pid):
            world[(fold(name), nat)].add((resolved[pid], age))
    by_name, ambiguous, unmatched = 0, [], 0
    for pid, game_pid, _b, name, nat, age, _f in players:
        if pid in resolved or not is_career_band(game_pid):
            continue
        fits = {p for p, a in world.get((fold(name), nat), ())
                if age is None or a is None or abs(age - a) <= 2}
        if len(fits) == 1:
            resolved[pid] = fits.pop()
            by_name += 1
        elif fits:
            ambiguous.append((name, sorted(fits)))
        else:
            unmatched += 1

    career = sum(1 for _p, g, *_ in players if is_career_band(g))
    print(f"players {len(players):,}: {len(resolved):,} resolve to a thumbnail "
          f"({len(resolved) - by_name:,} by their own PID, {by_name} career copies by name)")
    print(f"career-band players {career}: {by_name} matched, {len(ambiguous)} ambiguous, {unmatched} with no thumbnail")
    for name, pids in ambiguous[:10]:
        print(f"   ambiguous: {name} -> {pids}")

    wanted = sorted(set(resolved.values()))
    missing = [p for p in wanted if not (OUT / f"{p}.png").exists()]
    updates = [(f"build/game_faces/{resolved[pid]}.png" if pid in resolved else None, pid)
               for pid, *_rest, current in players
               if (f"build/game_faces/{resolved[pid]}.png" if pid in resolved else None) != current]
    print(f"thumbnails needed {len(wanted):,}, to decode {len(missing):,}; player rows to update {len(updates):,}")
    if args.dry:
        print("--dry: nothing decoded, nothing written.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    t0 = time.time()
    for i, pid in enumerate(missing, 1):
        try:
            if not decode(container, heads[pid], OUT / f"{pid}.png"):
                failed.append(pid)
        except Exception as ex:  # noqa: BLE001 — one bad texture never stops the rest
            failed.append(pid)
            print(f"   {pid}: {ex!r}")
        if i % 2000 == 0:
            print(f"   decoded {i:,}/{len(missing):,} ({time.time() - t0:.0f}s)")
    print(f"decoded {len(missing) - len(failed):,} PNGs into {OUT.relative_to(REPO)} "
          f"({time.time() - t0:.0f}s), {len(failed)} failed")
    if failed:
        bad = set(failed)
        updates = [(None if path and int(Path(path).stem) in bad else path, pid) for path, pid in updates]

    if not updates and has_col:
        print("database already up to date.")
        return 0
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    backup = Path(f"{args.db}.bak-gamefaces-{datetime.now():%Y%m%d}")
    if not backup.exists():                     # one restore point per day (CLAUDE.md: .bak fills the disk)
        shutil.copy2(args.db, backup)
        print(f"backup {backup.name}")
    if not has_col:
        con.execute("ALTER TABLE players ADD COLUMN game_face_path TEXT")
    con.executemany("UPDATE players SET game_face_path=? WHERE id=?", updates)
    con.commit()
    print(f"wrote game_face_path for {len(updates):,} players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
