#!/usr/bin/env python3
"""
play_match.py — compile ONE match into a playable dt200.

The payoff loop: pick two real clubs, and this authors both squads (real identities + translated
abilities) into two host team slots, rebuilds dt200, and installs it. You then play the fixture
in eFootball's Exhibition mode as those two clubs.

    python tools/play_match.py --home "Red Star Belgrade" --away "FK Partizan Belgrade" --install

Where the squads come from
    RFS.DB is the seed. teamplayerlinks (teamid u32@0, playerid u32@4, slot u8@8) gives each club's
    roster; rfs_translate turns each player into an eFootball position + overall + bit-packed
    abilities. We author the EXACT roster rather than resolving through the name-dedup to a possibly
    wrong eFootball player — an authored Serbian squad is more faithful than a mis-matched licensed
    one. Faces are a separate asset job; every authored player still inherits a real donor's face.

Why host slots
    eFootball can only play team ids that already exist. So we borrow two existing lower-tier team
    slots (the proven 5776-6091 host block), rename them to the two clubs, and reassign their squad
    slots to the authored players. Headcount per slot is unchanged, so every squad invariant holds.

Deploy
    A new-player author changes Player.bin's length, so this is NOT the in-place PlayerAssignment
    patch — it is a full cpkmakec rebuild at align=512 (proven to boot; align 2048 is silently
    ignored). We rebuild from a fresh copy of the pristine build/tree_base every time, so matches
    never accumulate edits.

Kits
    Host placeholders wear generic US kits, so each compile also authors the fixture clubs' own
    colors (median-cut palette from master.db teams.logo_path, else a deterministic id-hash pair)
    as raw plaintext kit descriptors into the working tree's uniform/team/<slot>/ via
    tools/kit_author.py. On by default; --no-kits skips it. Real eFootball slots keep their
    shipped kit configs. --compile-only stops after the tree is staged (before cpkmakec) so the
    result can be inspected without building or installing anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
from rfs_import import RfsDb          # noqa: E402
from rfs_translate import translate    # noqa: E402
import wesys                           # noqa: E402
import pesdb                           # noqa: E402
import kit_author                      # noqa: E402

RFS_DB = Path.home() / "OneDrive/Documents/RFS/DB/RFS.DB"
TREE_BASE = REPO / "build" / "tree_base"
CPKMAKEC = REPO / "CRI_File_System_Tools_v2.40.13.0" / "crifilesystem v2.40.13.0" / "cpkmakec.exe"
from steam_paths import game_cpk_dir  # noqa: E402  (tools/ is on sys.path above)
GAME_CPK = game_cpk_dir()           # Steam's own library list, not a hard-coded C: path
BACKUPS = Path.home() / "Backups" / "eFootball"

# Host slots: eFootball's generic US placeholder teams (city + colour-code names like "Monterey
# BB"). They are filler sides meant to be overwritten, they all sit in ONE in-game league, and the
# National League build proved them selectable and playable. Using the same league for both clubs
# is what makes "where are my teams" answerable. Squads are trimmed to a host's slot count (~23),
# which still leaves a full XI plus subs. Picked roomiest-first to minimise trimming.
HOST_IDS = [
    5833, 5971, 5798, 5788, 5800, 5783, 5787, 5793, 5802, 5804, 5835, 6091,
    5786, 5795, 5801, 5803, 5776, 5779, 5785, 5780, 5794, 5972, 5782, 5778,
]


# eFootball's unlicensed clubs ship under kit-colour fake names ('Manchester B' is Man City,
# 'Leeds W' is Leeds United). Maps OUR normalised club name -> the normalised fake name, so the
# match compiler and career_seed both find the real in-game counterpart. Keys are norms that do
# not exist among eFootball's own team names, so applying the map to both sides is collision-free.
# Data table for the pinned game build — re-check after a Konami licence shuffle.
_CLUB_ALIASES = {
    "manchestercity": "manchester",            # Manchester B
    "tottenhamhotspur": "tottenham",           # Tottenham WB
    "newcastleunited": "newcastle",            # Newcastle WB
    "leedsunited": "leedsw",                   # Leeds W
    "westhamunited": "westhamrb",              # West Ham RB
    "wolverhamptonwanderers": "wolverhamptonyb",  # Wolverhampton YB
    "brightonhovealbion": "brighton",          # Brighton WB
    "sunderland": "sunderlandrwb",             # Sunderland RWB ('AFC' already stripped)
    "crystalpalace": "crystalpalacerb",        # Crystal Palace RB
    "burnley": "burnleyrb",                    # Burnley RB
    "fulham": "fulhamw",                       # Fulham W
    "astonvilla": "astonrb",                   # Aston RB
    "nottinghamforest": "nottinghamrw",        # Nottingham RW
    "middlesbrough": "middlesbroughrw",        # Middlesbrough RW
    "coventrycity": "coventry",                # Coventry B
    "birminghamcity": "birmingham",            # Birmingham B
    "hullcity": "hullob",                      # Hull OB
    "ipswichtown": "ipswichbw",                # Ipswich BW
    "derbycounty": "derby",                    # Derby WB
    "bournemouth": "bournemouthrb",            # Bournemouth RB
    "brentford": "brentfordrw",                # Brentford RW
}


def _norm_club(s: str) -> str:
    """Normalise a club name so 'Liverpool FC' matches eFootball's 'Liverpool R'."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    for w in ("fc", "cf", "fk", "ofk", "sc", "ac", "afc", "club", "futbol", "football", "r", "b", "wb"):
        s = re.sub(rf"\b{w}\b", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return _CLUB_ALIASES.get(s, s)


def real_team_slots() -> dict[str, tuple[int, str]]:
    """eFootball's own club team slots by normalised name -> (team_id, real name). These already
    carry real faces, portraits, kits, badges and leagues, so we prefer them over placeholder hosts."""
    team = wesys.unpack_wesys_payload((TREE_BASE / "common/etc/pesdb/Team.bin").read_bytes())
    slots: dict[str, tuple[int, str]] = {}
    for off in range(0, len(team), 1600):
        tid = struct.unpack_from("<I", team, off + 12)[0]
        nm = team[off + 396:off + 396 + 48].split(b"\0")[0].decode("utf-8", "replace").strip()
        if nm:
            slots.setdefault(_norm_club(nm), (tid, nm))
    return slots


def rfs_team_id(db: RfsDb, name: str) -> tuple[int, str]:
    """Resolve a club name (substring, case-insensitive) to its RFS team id + canonical name."""
    tt = db.tables["teams"]
    exact = None
    for i in range(tt.rows):
        r = db.record("teams", i)
        nm = r[36:36 + 32].split(b"\0")[0].decode("utf-8", "replace")
        if nm.lower() == name.lower():
            return struct.unpack_from("<I", r, 0)[0], nm
        if exact is None and name.lower() in nm.lower():
            exact = (struct.unpack_from("<I", r, 0)[0], nm)
    if exact is None:
        sys.exit(f"club not found in RFS: {name!r}")
    return exact


def squad(db: RfsDb, links_by_team: dict[int, list], pidx: dict[int, int], team_id: int) -> list[dict]:
    """The club's roster as author-spec player dicts, ordered by RFS squad slot (GK/starters first)."""
    players = []
    for slot, pid in sorted(links_by_team.get(team_id, [])):
        if pid not in pidx:
            continue
        p = translate(db.record("players", pidx[pid]))
        players.append({
            "name": p["name"],
            "position": p["position"],
            "shirt": slot if 1 <= slot <= 99 else (len(players) + 1),
            "abilities": p["abilities"],
        })
    return players


def host_capacities() -> dict[int, int]:
    """squad-slot count for each curated host team, read from the pristine tree's PlayerAssignment."""
    pa = TREE_BASE / "common/etc/pesdb/PlayerAssignment.bin"
    recs = pesdb.parse_player_assignment_bin(wesys.unpack_wesys_payload(pa.read_bytes()))
    caps: dict[int, int] = defaultdict(int)
    for r in recs:
        if r["team_id"] in set(HOST_IDS):
            caps[r["team_id"]] += 1
    return caps


def pick_hosts(caps: dict[int, int]) -> tuple[int, int]:
    """The two roomiest host slots (same league). Squads trim to each host's slot count."""
    ranked = sorted((tid for tid in HOST_IDS if caps.get(tid, 0) > 0), key=lambda t: -caps[t])
    if len(ranked) < 2:
        sys.exit("fewer than two usable host slots found in the base tree")
    return ranked[0], ranked[1]


def team_fid_pair(tree: Path, team_id: int) -> tuple[int, int] | None:
    """
    A team's OWN (main, sub) formation ids from the tree's Tactics.bin (12 B/record: team_id@0,
    formation_id@4, style@8, phase@9). Every eFootball team owns its two formation records —
    1,780 distinct formation_ids across 890 teams, zero shared — so geometry edits always target
    THESE ids. The formation_id field is never repointed at another team's records: doing so was
    the old (corrupting) model, because "repointed" geometry is another team's property.
    """
    payload = wesys.unpack_wesys_payload((tree / "common/etc/pesdb/Tactics.bin").read_bytes())
    fids: dict[int, int] = {}
    for i in range(len(payload) // 12):
        if struct.unpack_from("<I", payload, i * 12)[0] == team_id:
            fids[payload[i * 12 + 9]] = struct.unpack_from("<I", payload, i * 12 + 4)[0]
    if 0 not in fids or 1 not in fids:
        return None
    return fids[0], fids[1]


def write_formation_geometry(tree: Path, fid: int, slots: dict[int, tuple[int, int, int]]) -> int:
    """
    Rewrite ONE formation's 11 geometry records in place in TacticsFormation.bin (12 B/record:
    role u32@0, formation_id u32@4, y u8@8, x u8@9, slot u8@10). slots maps slot_index ->
    (role_code, x, y). Only the role/x/y bytes of the matched fid's records change; every other
    record — and the fid and slot bytes themselves — stay exactly as shipped. In-place WESYS
    repack at level 1, key nibble preserved.
    """
    p = tree / "common/etc/pesdb/TacticsFormation.bin"
    blob = p.read_bytes()
    tf = bytearray(wesys.unpack_wesys_payload(blob))
    changed = 0
    for i in range(len(tf) // 12):
        if struct.unpack_from("<I", tf, i * 12 + 4)[0] == fid:
            sl = tf[i * 12 + 10]
            if sl in slots:
                role, x, y = slots[sl]
                struct.pack_into("<I", tf, i * 12, role & 0xFFFFFFFF)
                tf[i * 12 + 8] = max(0, min(255, y))
                tf[i * 12 + 9] = max(0, min(255, x))
                changed += 1
    if changed:
        p.write_bytes(wesys.pack_wesys_container(bytes(tf), key_nibble=blob[1] & 0x0F,
                                                 compression_level=1))
    return changed


def write_style(tree: Path, team_id: int, style: int) -> int:
    """
    Set the team's attacking-style byte (u8@8) on BOTH of its Tactics.bin records. The
    formation_id u32@4 is NEVER written — standing rule: geometry is rewritten on the owner's
    own fids (write_formation_geometry); the pointer stays untouched.
    """
    p = tree / "common/etc/pesdb/Tactics.bin"
    blob = p.read_bytes()
    payload = bytearray(wesys.unpack_wesys_payload(blob))
    changed = 0
    for i in range(len(payload) // 12):
        if struct.unpack_from("<I", payload, i * 12)[0] == team_id:
            payload[i * 12 + 8] = max(0, min(255, style))
            changed += 1
    if changed:
        p.write_bytes(wesys.pack_wesys_container(bytes(payload), key_nibble=blob[1] & 0x0F,
                                                 compression_level=1))
    return changed


def squad_from_db(db_path: str, team_id: int):
    """
    A club's squad straight from the master DB (the source of truth) — ordered by squad slot, so
    the in-app starting XI (slots 0..10) lands in the host's starting positions. Abilities come
    from player_attributes, same shape the RFS path produces.
    """
    import sqlite3
    con = sqlite3.connect(db_path)
    row = con.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
    if not row:
        con.close()
        return None, []
    name = row[0]
    cap = con.execute("SELECT value FROM meta WHERE key=?", (f"captain_{team_id}",)).fetchone()
    captain_id = int(cap[0]) if cap and str(cap[0]).isdigit() else None
    # Set-piece takers (bits calibrated against shipped data: fk=8, pk=16, ckl=4, ckr=1).
    taker_bits = {}
    for kind, bit in (("fk", 8), ("pk", 16), ("ckl", 4), ("ckr", 1)):
        t = con.execute("SELECT value FROM meta WHERE key=?", (f"taker_{kind}_{team_id}",)).fetchone()
        if t and str(t[0]).isdigit():
            taker_bits[int(t[0])] = taker_bits.get(int(t[0]), 0) | bit
    players = []
    for pid, shirt in con.execute(
            "SELECT player_id, squad_number FROM squad_members WHERE team_id=? ORDER BY slot",
            (team_id,)).fetchall():
        p = con.execute("SELECT name, position FROM players WHERE id=?", (pid,)).fetchone()
        if not p:
            continue
        abilities = dict(con.execute(
            "SELECT attribute, value FROM player_attributes WHERE player_id=?", (pid,)).fetchall())
        role = con.execute(
            "SELECT playstyle FROM player_playstyles WHERE player_id=? AND kind='primary' LIMIT 1",
            (pid,)).fetchone()
        srole = con.execute(
            "SELECT playstyle FROM player_playstyles WHERE player_id=? AND kind='secondary' LIMIT 1",
            (pid,)).fetchone()
        # Skin tone (portrait-correlated field): the authored clone gets the player's own
        # face colour instead of the donor's (tools/appearance.py for the layout).
        skin = con.execute(
            "SELECT skin_tone FROM player_appearance WHERE player_id=?", (pid,)).fetchone()
        players.append({"name": p[0], "position": p[1],
                        "shirt": shirt if 1 <= shirt <= 99 else len(players) + 1,
                        "abilities": abilities, "role": role[0] if role else None,
                        "secondary_role": srole[0] if srole else None,
                        "captain": pid == captain_id,
                        "taker_bits": taker_bits.get(pid, 0),
                        "skin_tone": skin[0] if skin else None})
    con.close()
    return name, players


def _db_formation_geometry(con, fid: int) -> dict[int, tuple[int, int, int]]:
    """slot_index -> (role_code, x, y) for one DB formation."""
    return {sl: (role, x, y) for sl, role, x, y in con.execute(
        "SELECT slot_index, position, x, y FROM formation_slots WHERE formation_id=?", (fid,)).fetchall()}


def apply_custom_formation(tree: Path, slot_id: int, db_path: str, team_id: int,
                           always: bool = False) -> bool:
    """
    Render the club's OWN formation (the per-team fid pair the app maintains in the DB) onto the
    in-game team occupying `slot_id`: geometry + role codes are rewritten in place on the target
    team's own fid pair (via team_fid_pair), and the style byte is set on both Tactics.bin
    records. formation_id is never repointed. Not fluid: the main shape goes into BOTH target
    fids (Sub mirrors Main). Fluid: main -> fid0, sub -> fid1 (in-game "Use Sub-Tactic" shows it).

    By default only clubs flagged `tactics_custom_{id}` in meta are touched (untouched clubs keep
    eFootball's own shape); `always=True` applies the DB shape unconditionally — used for authored
    host slots, whose shipped placeholder shape is unrelated to the club.
    """
    import sqlite3
    con = sqlite3.connect(db_path)
    flag = con.execute("SELECT value FROM meta WHERE key=?", (f"tactics_custom_{team_id}",)).fetchone()
    # The flag is "1" now; legacy careers stored the chosen fid — any non-empty value means saved.
    if not (always or (flag and flag[0])):
        con.close()
        return False
    fluid_row = con.execute("SELECT value FROM meta WHERE key=?", (f"tactics_fluid_{team_id}",)).fetchone()
    fluid = bool(fluid_row and fluid_row[0] == "1")
    tt = dict(con.execute(
        "SELECT phase, formation_id FROM team_tactics WHERE team_id=?", (team_id,)).fetchall())
    style_row = con.execute(
        "SELECT style FROM team_tactics WHERE team_id=? AND phase=0", (team_id,)).fetchone()
    style = style_row[0] if style_row else 0
    if 0 not in tt:
        con.close()
        return False
    main = _db_formation_geometry(con, tt[0])
    sub = _db_formation_geometry(con, tt[1]) if fluid and 1 in tt else main
    con.close()

    if len(main) != 11:
        print(f"  tactics: team {team_id} has {len(main)} DB slots (need 11) — left untouched")
        return False
    if len(sub) != 11:
        sub = main

    pair = team_fid_pair(tree, slot_id)
    if pair is None:
        print(f"  tactics: in-game team {slot_id} owns no Tactics.bin fid pair — left untouched")
        return False
    fid0, fid1 = pair
    write_formation_geometry(tree, fid0, main)
    write_formation_geometry(tree, fid1, sub if fluid else main)
    write_style(tree, slot_id, style)
    return True


def fresh_tree() -> Path:
    """A clean copy of the pristine base tree, resilient to transient Windows file locks."""
    tree = REPO / "build" / "tree_match"
    for _ in range(5):
        if not tree.exists():
            break
        shutil.rmtree(tree, ignore_errors=True)
        if not tree.exists():
            break
        time.sleep(0.6)
    else:
        tree = REPO / "build" / f"tree_match_{os.getpid()}"
        shutil.rmtree(tree, ignore_errors=True)
    print("  copying pristine tree...")
    shutil.copytree(TREE_BASE, tree)
    return tree


def _meta(db_path: str, key: str) -> str | None:
    """One meta value from the master DB (settings the compile honours)."""
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def rename_slot(tree: Path, slot_id: int, real_name: str) -> bool:
    """
    Give the in-game team its REAL name (eFootball ships unlicensed fakes: 'Manchester B',
    'Leeds W'). Team.bin: 1600-byte records, team_id u32@12, name field @396 (490 bytes, zero
    padded). Full-rebuild path, so the WESYS repack may change size freely.
    """
    team_path = tree / "common/etc/pesdb/Team.bin"
    blob = team_path.read_bytes()
    payload = bytearray(wesys.unpack_wesys_payload(blob))
    for off in range(0, len(payload), 1600):
        if struct.unpack_from("<I", payload, off + 12)[0] == slot_id:
            ns = off + 396
            payload[ns:ns + 490] = b"\x00" * 490
            enc = real_name.encode("utf-8")[:480]
            payload[ns:ns + len(enc)] = enc
            team_path.write_bytes(wesys.pack_wesys_container(
                bytes(payload), key_nibble=blob[1] & 0x0F, compression_level=1))
            return True
    return False


def _club_kit_colors(db_path: str, team_id: int) -> tuple[kit_author.Kit, str]:
    """The club's five kit colors + a note about where they came from.

    Logo-first: teams.logo_path in master.db (repo-relative) feeds kit_author's
    --from-logo median-cut palette (shirt = dominant, trim = second, ...). No
    usable logo file -> kit_author.colors_from_seed: two deterministic colors
    hashed from the DB team id, so a club always renders the same pair.
    """
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT logo_path FROM teams WHERE id=?", (team_id,)).fetchone()
    finally:
        con.close()
    logo = None
    if row and row[0]:
        p = Path(row[0])
        if not p.is_absolute():
            p = REPO / p
        if p.exists():
            logo = p
    if logo is not None:
        try:
            return kit_author.expand_colors(kit_author.colors_from_logo(logo)), f"logo {logo.name}"
        except Exception as exc:
            print(f"  kit: palette from {logo.name} failed ({exc}) — using id-hash colors")
    return kit_author.expand_colors(kit_author.colors_from_seed(team_id)), "id-hash colors"


def author_fixture_kits(tree: Path, db_path: str, clubs) -> None:
    """Stage per-fixture kit descriptors for the two clubs of THIS fixture.

    clubs: (slot_id, db_team_id | None, club_name) per side. Runs after the
    working tree is populated and before the CPK rebuild. Each slot's
    DEF_1st/2nd/GK1st trio in the WORKING tree's uniform/team/<slot>/ is
    replaced (force semantics — slots are reused between fixtures, so
    clobbering the previous occupant's kit is the point) with raw plaintext
    descriptors in the club's colors, pointing at the donor texture refs
    kit_author embeds (u6058p1/p2/g1, guaranteed pak-side). 2nd and GK kits
    are auto-derived by kit_author. A club without a DB id (pure RFS-name
    compile) has no color source of truth and keeps the slot's shipped kit.
    """
    for slot_id, tid, label in clubs:
        if tid is None:
            print(f"  kit: slot {slot_id} ({label}) keeps shipped colors — no DB club id to source from")
            continue
        first, src = _club_kit_colors(db_path, tid)
        kit_author.author_team_kits(slot_id, first, None, None, None, None, tree,
                                    force=True, quiet=True)
        cols = "/".join(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" for c in first)
        print(f"  kit: slot {slot_id} <- {label} colors {cols} ({src})")


def _sha1(path: Path) -> str:
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _patch_guard(target: Path) -> None:
    """
    Refuse to install over a dt200 we don't recognise. The game file should be either Konami's
    base (matching our pristine copy) or our own last install. Anything else means a Konami
    patch or another mod landed since — installing blind would target a stale base and the
    symptom would be the silent 'my edit didn't apply'. Re-extract build/tree_base instead.
    """
    if not target.exists():
        return
    actual = _sha1(target)
    known = set()
    base = REPO / "dt200_console_all.cpk"
    if base.exists():
        known.add(_sha1(base))
    marker = REPO / "build" / "last_install.sha1"
    if marker.exists():
        known.add(marker.read_text().strip())
    if actual not in known:
        sys.exit(
            "PATCH GUARD: the game's dt200_console_all.cpk is not the base we built from and not "
            "our last install — a Konami update (or another mod) has replaced it.\n"
            "Re-baseline first:  1) verify the game runs clean,  2) copy the game's dt200 over "
            "the repo copy,  3) re-extract build/tree_base from it. Then compile again.")


def rebuild_and_install(tree: Path, out: Path, install: bool) -> None:
    print(f"  rebuilding {out.name} (cpkmakec, align=512)...")
    r = subprocess.run([str(CPKMAKEC), str(tree), str(out), "-mode=FILENAME", "-align=512"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit("cpkmakec rebuild failed")
    print(f"  built {out} ({out.stat().st_size:,} bytes)")
    if install:
        target = GAME_CPK / "dt200_console_all.cpk"
        _patch_guard(target)
        BACKUPS.mkdir(parents=True, exist_ok=True)
        if target.exists():
            keep = BACKUPS / f"dt200_console_all.{datetime.now():%Y%m%d-%H%M%S}.cpk"
            shutil.copy2(target, keep)
            print(f"  backup {keep.name}")
        try:
            shutil.copy2(out, target)
        except PermissionError:
            sys.exit(f"\n{target.name} is locked. Close eFootball and run again.")
        (REPO / "build" / "last_install.sha1").write_text(_sha1(target))
        print(f"INSTALLED {target}")


def _pnorm(s: str) -> str:
    """Normalise a player name for matching: Ø->o, accents stripped, punctuation dropped."""
    s = (s.replace("ø", "o").replace("Ø", "o").replace("æ", "ae").replace("Æ", "ae")
          .replace("ß", "ss").replace("ł", "l").replace("Ł", "l").replace("đ", "d").replace("Đ", "d"))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def _name_matches(ours: str, theirs: str) -> bool:
    """'Alisson' ~ 'Alisson Becker', 'Wataru Endo' ~ 'Endo Wataru', 'Gabriel' ~ 'Gabriel Magalhaes'."""
    a, b = set(_pnorm(ours).split()), set(_pnorm(theirs).split())
    if not a or not b:
        return False
    return a <= b or b <= a


def _pos_cat(pos: str) -> str:
    pos = (pos or "").upper()
    if pos == "GK":
        return "GK"
    if pos in ("CB", "LB", "RB", "LWB", "RWB", "DF"):
        return "DEF"
    if pos in ("DMF", "CMF", "LMF", "RMF", "AMF", "MF"):
        return "MID"
    return "FWD"


_STYLE_TABLE = None


def _style_table():
    global _STYLE_TABLE
    if _STYLE_TABLE is None:
        from playstyle_bits import build_style_table
        _STYLE_TABLE = build_style_table()
    return _STYLE_TABLE


def _apply_playstyles(pb: bytearray, pid2offset: dict, resolved, sec_by_pid: dict | None = None) -> int:
    """Write each squad player's roles into Player.bin: the PRIMARY (in-possession) style in the
    5-bit field at byte 46.6, and the SECONDARY (out-of-possession/defending) style at bit 440
    (playstyle_secondary). Both come from the app's player_playstyles."""
    import playstyle_secondary
    table = _style_table()
    sec_by_pid = sec_by_pid or {}
    written = 0
    for pid, _shirt, position, role in resolved:
        if pid not in pid2offset:
            continue
        off = pid2offset[pid]
        rec = bytearray(pb[off:off + 400])
        changed = False
        if role:
            val = table.get((_pos_cat(position), role))
            if val is not None:
                val &= 0x1F
                rec[46] = (rec[46] & 0x3F) | ((val & 0x03) << 6)
                rec[47] = (rec[47] & 0xF8) | ((val >> 2) & 0x07)
                changed = True
        srole = sec_by_pid.get(pid)
        if srole and playstyle_secondary.write_secondary(rec, position, srole):
            changed = True
        if changed:
            pb[off:off + 400] = rec
            written += 1
    return written


def reconcile_real_slot(tree: Path, slot_id: int, squad) -> tuple[int, int, list]:
    """
    Make a real eFootball team's roster match our DB squad by REUSING real player records (real
    faces + real ratings), then rewrite the OCCUPANT ORDER so the game's starting XI is the XI the
    app's AI managers picked. The first 11 PA records by sort_key ARE the starting XI (proven), in
    formation-slot order, so records 0..10 get DB slots 0..10's resolved pids (unresolved slots
    skipped, next resolved player promoted), the bench follows, and the club's surplus players
    fill the remaining records. Only pid + shirt bytes are touched (v2: pid@0 shirt@16; v1: pid@8
    shirt@20) — sort_key and role flags are never written and the headcount never changes.
    squad is a list of dicts {name, position, shirt, ...} in DB slot order (slots 0..10 = XI).
    """
    pa_path = tree / "common/etc/pesdb/PlayerAssignment.bin"
    pb_path = tree / "common/etc/pesdb/Player.bin"
    pa_blob = pa_path.read_bytes()
    pb_blob = pb_path.read_bytes()
    pb = bytearray(wesys.unpack_wesys_payload(pb_blob))
    pa = bytearray(wesys.unpack_wesys_payload(pa_blob))

    pid2name = {}
    pid2offset = {}
    global_index: dict[str, int] = {}
    for k in range(len(pb) // 400):
        pid = struct.unpack_from("<Q", pb, k * 400 + 8)[0]
        nm = pb[k * 400 + 271:k * 400 + 271 + 61].split(b"\0")[0].decode("utf-8", "replace")
        pid2name[pid] = nm
        pid2offset[pid] = k * 400
        n = _pnorm(nm)
        if n:
            global_index.setdefault(n, pid)
            global_index.setdefault(n.split()[-1], pid)

    recs = pesdb.parse_player_assignment_bin(bytes(pa))
    v2 = pesdb.detect_assignment_layout(bytes(pa)).endswith("/v2")
    pid_off, shirt_off = (0, 16) if v2 else (8, 20)
    slot_recs = sorted((r for r in recs if r["team_id"] == slot_id), key=lambda r: r["sort_key"])
    slot_pids = [r["player_id"] for r in slot_recs]

    # Resolve each squad member to an eFootball pid: prefer the player already in THIS slot
    # (disambiguates 'Gabriel'), then anyone in eFootball, else unmatched. Matching runs
    # specific-names-first but results are kept in DB slot order for the XI rewrite below.
    used = set()
    by_ix: dict[int, tuple[int, int, str, str | None]] = {}   # squad index -> (pid, shirt, pos, role)
    captain_pid: int | None = None
    taker_by_pid: dict[int, int] = {}                          # resolved pid -> taker bits (fk8/pk16/ckl4/ckr1)
    sec_by_pid: dict[int, str] = {}                            # resolved pid -> out-of-possession role
    unmatched_ix: list[tuple[int, str]] = []
    for ix in sorted(range(len(squad)), key=lambda i: -len(squad[i]["name"].split())):
        p = squad[ix]
        pid = None
        for r in slot_recs:
            if r["player_id"] not in used and _name_matches(p["name"], pid2name.get(r["player_id"], "")):
                pid = r["player_id"]; break
        if pid is None:
            n = _pnorm(p["name"])
            cand = global_index.get(n) or global_index.get(n.split()[-1] if n else n)
            if cand is not None and cand not in used:
                pid = cand
        if pid is None:
            unmatched_ix.append((ix, p["name"]))
        else:
            used.add(pid)
            by_ix[ix] = (pid, p["shirt"], p["position"], p.get("role"))
            if p.get("captain"):
                captain_pid = pid
            if p.get("taker_bits"):
                taker_by_pid[pid] = p["taker_bits"]
            if p.get("secondary_role"):
                sec_by_pid[pid] = p["secondary_role"]
    resolved = [by_ix[ix] for ix in sorted(by_ix)]            # DB slot order

    # Write each player's in- AND out-of-possession role into their Player.bin record.
    styles_written = _apply_playstyles(pb, pid2offset, resolved, sec_by_pid)
    if styles_written:
        pb_path.write_bytes(wesys.pack_wesys_container(bytes(pb), key_nibble=pb_blob[1] & 0x0F,
                                                       compression_level=1))

    our = {pid for pid, _, _, _ in resolved}
    present = sum(1 for pid in slot_pids if pid in our)

    # Desired occupant order over the club's existing records (sort_key order): our squad in DB
    # slot order (XI first), then the club's surplus players keeping their current relative order.
    # Trimmed to the club's record count, so the headcount is untouched by construction.
    occupants = [(pid, max(0, min(98, shirt - 1))) for pid, shirt, _, _ in resolved]
    occupants += [(r["player_id"], r["shirt_number_raw"])
                  for r in slot_recs if r["player_id"] not in our]
    occupants = occupants[:len(slot_recs)]

    rewritten = 0
    for rec, (pid, shirt_raw) in zip(slot_recs, occupants):
        base = rec["index"] * 24
        if struct.unpack_from("<Q", pa, base + pid_off)[0] != pid or pa[base + shirt_off] != shirt_raw:
            struct.pack_into("<Q", pa, base + pid_off, pid)
            pa[base + shirt_off] = shirt_raw
            rewritten += 1

    # The armband + set-piece duties. Captain: vendored semantics (v1 byte22 0x20 / v2 bit9@18).
    # Takers (calibrated vs shipped data): fk=8, pk=16, ckl=4, ckr=1; bit 2 (secondary FK) is
    # preserved. Taker bits are rewritten only when the club has takers SET in the app —
    # otherwise the shipped duties stand.
    if captain_pid is not None or taker_by_pid:
        for rec in slot_recs:
            base = rec["index"] * 24
            now_pid = struct.unpack_from("<Q", pa, base + pid_off)[0]
            if v2:
                flags = struct.unpack_from("<H", pa, base + 18)[0]
                if captain_pid is not None:
                    flags = (flags | (1 << 9)) if now_pid == captain_pid else (flags & ~(1 << 9))
                # v2 taker sub-bits live in role_mask (>>4); left untouched pending v2 calibration.
                struct.pack_into("<H", pa, base + 18, flags)
            else:
                b = pa[base + 22]
                if captain_pid is not None:
                    b = (b | 0x20) if now_pid == captain_pid else (b & ~0x20)
                if taker_by_pid:
                    b = (b & ~0x1D) | taker_by_pid.get(now_pid, 0)   # rewrite fk/pk/ckl/ckr, keep 0x02+0x20
                pa[base + 22] = b
        if captain_pid is not None:
            print(f"  armband: {pid2name.get(captain_pid, captain_pid)} wears it in-game")
        if taker_by_pid:
            duty = ", ".join(pid2name.get(p, str(p)) for p in taker_by_pid)
            print(f"  set pieces: duties written for {duty}")

    missing_xi = [nm for ix, nm in sorted(unmatched_ix) if ix < 11]
    if missing_xi:
        print(f"  WARNING: XI names not in eFootball (next resolved player promoted): {missing_xi}")

    pa_path.write_bytes(wesys.pack_wesys_container(bytes(pa), key_nibble=pa_blob[1] & 0x0F,
                                                   compression_level=1))
    return present, rewritten, [nm for _, nm in sorted(unmatched_ix)]


def real_slot_match(home_real, away_real, home_name, away_name, args) -> int:
    """
    Both clubs exist in eFootball, so we reuse the real teams (real faces, portraits, kits, badges)
    and reconcile their rosters to our DB squads — real player records give real ratings too, so
    eFootball's data drives ratings, not RFS. Then we push our tactics. No cloned players.
    """
    print("REAL TEAMS (reusing eFootball records — real faces, kits, badges, ratings)")
    print(f"  HOME  {home_name} -> eFootball '{home_real[1]}' (team {home_real[0]})")
    print(f"  AWAY  {away_name} -> eFootball '{away_real[1]}' (team {away_real[0]})")
    tree = fresh_tree()
    if args.home_id and args.away_id:
        for slot, tid, label, ingame in ((home_real[0], args.home_id, home_name, home_real[1]),
                                         (away_real[0], args.away_id, away_name, away_real[1])):
            _, squad = squad_from_db(args.db, tid)
            if squad:
                present, rewritten, unmatched = reconcile_real_slot(tree, slot, squad)
                note = f", {len(unmatched)} not in eFootball: {unmatched}" if unmatched else ""
                print(f"  squad {label}: {present} already at club, "
                      f"{rewritten} record(s) rewritten for the XI order{note}")
            # REAL NAME in-game: 'Manchester B' becomes 'Manchester City' on the team select.
            # Settings toggle (meta real_names='0' turns it off, default on).
            if _meta(args.db, "real_names") != "0" and ingame != label and rename_slot(tree, slot, label):
                print(f"  renamed in-game: '{ingame}' -> '{label}'")
            # Apply hand-tuned tactics (geometry rewritten on the target team's OWN fid pair)
            # only if the club has them saved; otherwise eFootball's own shape stays untouched.
            if apply_custom_formation(tree, slot, args.db, tid):
                print(f"  tactics {label}: own-formation geometry + style applied")
    # No kit authoring here: a real eFootball slot already carries the club's own shipped kit
    # config, which is strictly more real than a logo-palette guess would be.
    print("  kit: real eFootball slots keep their shipped kit configs")
    if args.compile_only:
        print(f"COMPILE-ONLY: working tree staged at {tree} — stopped before cpkmakec (no CPK, no install)")
        return 0
    rebuild_and_install(tree, Path(args.out), args.install)
    print(f"\nPlay it:  eFootball -> Exhibition/League -> {home_name}  vs  {away_name}")
    print("          real names, your 26/27 squads, real faces, kits and badges — tactics applied.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="home club name (RFS lookup)")
    ap.add_argument("--away", help="away club name (RFS lookup)")
    ap.add_argument("--home-id", type=int, dest="home_id", help="home team id in master.db (career)")
    ap.add_argument("--away-id", type=int, dest="away_id", help="away team id in master.db (career)")
    ap.add_argument("--db", default=str(REPO / "build" / "master.db"), help="master DB for --home-id/--away-id")
    ap.add_argument("--install", action="store_true", help="copy the rebuilt dt200 into the game")
    ap.add_argument("--out", default=str(REPO / "build" / "dt200_console_all.cpk"))
    ap.add_argument("--no-kits", dest="no_kits", action="store_true",
                    help="skip per-fixture kit authoring (host slots keep their placeholder kits)")
    ap.add_argument("--compile-only", dest="compile_only", action="store_true",
                    help="stop after the working tree is staged: no cpkmakec rebuild, no install")
    args = ap.parse_args()

    if not TREE_BASE.exists():
        sys.exit(f"pristine base tree missing: {TREE_BASE}\nExtract it from dt200 first.")

    if args.home_id and args.away_id:
        # Source of truth: compile the two clubs straight from the career DB (respects the app XI).
        home_name, home_sq = squad_from_db(args.db, args.home_id)
        away_name, away_sq = squad_from_db(args.db, args.away_id)
        if not home_name or not away_name:
            sys.exit(f"team id not found in {args.db}")
    elif args.home and args.away:
        db = RfsDb(RFS_DB)
        pt = db.tables["players"]
        pidx = {struct.unpack_from("<I", db.record("players", i), 0)[0]: i for i in range(pt.rows)}
        tpl = db.tables["teamplayerlinks"]
        links: dict[int, list] = defaultdict(list)
        for i in range(tpl.rows):
            r = db.record("teamplayerlinks", i)
            links[struct.unpack_from("<I", r, 0)[0]].append((r[8], struct.unpack_from("<I", r, 4)[0]))
        home_id, home_name = rfs_team_id(db, args.home)
        away_id, away_name = rfs_team_id(db, args.away)
        home_sq = squad(db, links, pidx, home_id)
        away_sq = squad(db, links, pidx, away_id)
    else:
        sys.exit("give --home/--away (RFS names) or --home-id/--away-id (career DB)")

    # If eFootball already has both clubs, use its real teams (real faces, kits, badges) — no
    # authoring. Only clubs eFootball lacks get authored into placeholder hosts below.
    slots = real_team_slots()
    home_real = slots.get(_norm_club(home_name))
    away_real = slots.get(_norm_club(away_name))
    if home_real and away_real:
        return real_slot_match(home_real, away_real, home_name, away_name, args)

    if not home_sq or not away_sq:
        sys.exit(f"empty squad ({home_name}: {len(home_sq)}, {away_name}: {len(away_sq)})")

    caps = host_capacities()
    host_home, host_away = pick_hosts(caps)
    home_trim = "" if len(home_sq) <= caps[host_home] else f"  (trimmed to {caps[host_home]})"
    away_trim = "" if len(away_sq) <= caps[host_away] else f"  (trimmed to {caps[host_away]})"
    print(f"HOME  {home_name:<28} {len(home_sq):>2} players -> host slot {host_home} (cap {caps[host_home]}){home_trim}")
    print(f"AWAY  {away_name:<28} {len(away_sq):>2} players -> host slot {host_away} (cap {caps[host_away]}){away_trim}")

    spec = {"clubs": [
        {"club": home_name, "host_team_id": host_home, "players": home_sq},
        {"club": away_name, "host_team_id": host_away, "players": away_sq},
    ]}
    spec_path = REPO / "build" / "match_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")

    tree = fresh_tree()

    print("  authoring squads...")
    r = subprocess.run([sys.executable, str(REPO / "tools" / "ml_author.py"),
                        "--tree", str(tree), "--spec", str(spec_path)])
    if r.returncode != 0:
        return r.returncode

    # Render each club's own DB formation onto its host team's own fid pair (career DB compiles
    # only). always=True: a placeholder host's shipped shape is unrelated to the club, so the DB
    # shape applies whether or not the user hand-tuned it.
    if args.home_id and args.away_id:
        for host, tid in ((host_home, args.home_id), (host_away, args.away_id)):
            if apply_custom_formation(tree, host, args.db, tid, always=True):
                print(f"  tactics: host {host} <- team {tid}'s own formation geometry + style")

    # Per-fixture kit authoring (on by default, --no-kits to skip): a host placeholder's kit
    # config is unrelated to the club occupying it, so both slots get descriptors in the
    # clubs' own colors, straight into the working tree before the rebuild.
    if not args.no_kits:
        author_fixture_kits(tree, args.db, [
            (host_home, args.home_id, home_name),
            (host_away, args.away_id, away_name),
        ])

    if args.compile_only:
        print(f"COMPILE-ONLY: working tree staged at {tree} — stopped before cpkmakec (no CPK, no install)")
        return 0

    rebuild_and_install(tree, Path(args.out), args.install)
    print("\nPlay it:  eFootball -> Exhibition / Match -> find the host league (American League 2)")
    print(f"          {home_name}  vs  {away_name}   (they replace two of the host clubs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
