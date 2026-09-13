#!/usr/bin/env python3
r"""
game_world.py — build a career world from the player's OWN eFootball install.

THE MVP'S FIRST RUN (ruling 2026-09-13): the download ships no world. On first launch this reads the
game's dt200 and dt870 archives — Player.bin, PlayerAssignment.bin, Team.bin, Country.bin,
CompetitionUnit.bin, CategoryTeamList.bin — and writes a small, separate world database. The owner's
curated build/master.db is a different file and is never opened by this tool.

What it reads, and how
  * Containers through tools/cpk_patch.py (the Player Editor's CPK code; no cpkmakec, no cricodecs).
  * WESYS through vendored Sider. Stdlib only: runs under the embedded Python the release ships.
  * Player fields through tools/data/player_layouts.json (built and scored by
    derive_player_layouts.py). A field that map marks "unverified" is left empty, never guessed.
  * Abilities are stored as the game SHOWS them: base cards (PID < 2^32) keep them scaled x25/24
    in the file, and the map carries the rule that undoes it.

Which archive wins
  dt200 is the one the game reads for offline play (Phase 0 proved a dt200 squad edit renders; the
  Player Editor calls it "the cpk the game actually reads"). So a club takes its squad from dt200
  when dt200 has one, else from dt870; its players come from that SAME archive, whose squads never
  point outside their own Player.bin. The two are never filtered against each other, and nothing is
  filtered by PID band — both of those have emptied real clubs before.

Identity
  Every player is stored under the PID that exists in Player.bin (players.id = game_pid = PID), and
  every club under its Team.bin id. Real PIDs reach into the 20M-700M range that careers seeded in
  the curated world use for their copies, so this world records its own career range in meta
  (career_player_band) — well above every PID the game uses — for the seeder to honour.

Safety
  Writes a temporary file and swaps it in. Refuses to overwrite any database this tool did not build
  (meta world_source = 'game'), so pointing --out at the curated master.db fails before a byte moves.

Usage
    python tools/game_world.py [--out build/game_world.db] [--game-dir <eFootball>]
                               [--dt200 <cpk>] [--dt870 <cpk>] [--replace]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "vendor" / "sider"))
import cpk_patch  # noqa: E402
import pesdb  # noqa: E402
import wesys  # noqa: E402

READER_VERSION = 1
LAYOUTS = TOOLS / "data" / "player_layouts.json"
SCHEMA = REPO / "src" / "ML.Data" / "schema.sql"
DEFAULT_OUT = REPO / "build" / "game_world.db"
PESDB = "common/etc/pesdb/"

# Careers seeded into THIS world copy players into [LO, HI): above every PID the game uses (base
# cards < 2^31, variant cards from ~2^44 up would be 17.6 trillion — the band sits far below that
# and far above 2^31), and clear of the curated world's 10B FM band and 45-46B overlay.
CAREER_PLAYER_BAND = (50_000_000_000, 51_000_000_000)

# master.db's categorical codes (dt870_harvest.py's tables), keyed by the export's labels.
WEAK_FOOT = {"Rarely": 1, "Occasionally": 2, "Regularly": 3, "Frequently": 4}
FORM = {"Inconsistent": 1, "Unstable": 2, "Standard": 3, "Wavering": 3, "Steady": 4,
        "Consistent": 5, "Unwavering": 6}
INJURY = {"Low": 1, "Medium": 2, "High": 3}
FOOT = {"Right foot": 0, "Left foot": 1}

# Teams that are not clubs a career can meet: Konami's event / collab / placeholder sides.
SPECIAL_TEAM_WORDS = ("dream team", "event team", "konoha", "uchiha", "dummy", "free agent",
                      "legend", "classic", "all star", "all-star", "selection", "efootball")
MIN_SQUAD = 11
MIN_LEAGUE_CLUBS = 8
MIN_LEAGUE_ONE_COUNTRY = 0.6


class WorldError(Exception):
    pass


# ============================================================================ reading the archives

def _text(raw: bytes) -> str:
    raw = raw.split(b"\0", 1)[0]
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        # Some competition names carry Windows-1252 bytes ("McDonald's" with a 0x92 apostrophe).
        return raw.decode("cp1252", errors="replace").strip()


class Archive:
    """One CPK's pesdb tables, decoded."""

    def __init__(self, label: str, path: Path):
        self.label, self.path = label, path
        self.cpk = cpk_patch.load(path)

    def table(self, name: str) -> bytes | None:
        blob = cpk_patch.read(self.cpk, PESDB + name)
        return None if blob is None else wesys.unpack_wesys_payload(blob)

    def fingerprint(self) -> dict:
        data = self.path.read_bytes()
        return {"path": str(self.path), "size": len(data), "sha1": hashlib.sha1(data).hexdigest()}


def read_bits(rec: bytes, off: int, width: int) -> int:
    return (int.from_bytes(rec, "little") >> off) & ((1 << width) - 1)


class PlayerDecoder:
    """Decode Player.bin records of one layout, using the verified field map."""

    def __init__(self, layout: dict):
        self.L = layout
        self.size = layout["record_size"]
        self.bad = set(layout.get("unverified", []))
        disp = layout["ability_display"]
        self.unscaled_from, self.num, self.den, self.floor = (
            disp["unscaled_from_pid"], disp["num"], disp["den"], disp["floor"])

    def _ability(self, stored: int, pid: int) -> int:
        if pid >= self.unscaled_from:
            return stored
        return max(self.floor, int(stored * self.num / self.den + 0.5))

    def decode(self, rec: bytes) -> dict:
        L = self.L
        v = int.from_bytes(rec, "little")
        bits = lambda off, w: (v >> off) & ((1 << w) - 1)
        pid = struct.unpack_from("<Q", rec, 8)[0]
        names = [_text(rec[L["name_offset"] + i * 61:L["name_offset"] + i * 61 + 61]) for i in range(5)]
        full, shirt = names[L["name_fields"]["full"]], names[L["name_fields"]["shirt"]]
        d = {"pid": pid, "name": full or shirt or next((n for n in names if n), f"Player {pid}"),
             "short_name": shirt or None,
             "nat_id": struct.unpack_from("<H", rec, 41)[0] & 0x3FF}
        for name, (off, w, bias) in L["scalars"].items():
            d[name] = None if name in self.bad else bits(off, w) + bias
        for name, (off, w) in L["codes"].items():
            d[name] = None if name in self.bad else L["tables"][name].get(str(bits(off, w)))
        d["abilities"] = {k: self._ability(bits(off, 6) + 40, pid) for k, off in L["abilities"].items()
                          if k not in self.bad}
        att_id = bits(*L["styles"]["att"]) // 4
        def_raw = bits(*L["styles"]["def"])
        d["primary_style"] = None if "primary_style" in self.bad else L["styles"]["att_table"].get(str(att_id))
        d["secondary_style"] = (None if "secondary_style" in self.bad
                                else L["styles"]["def_table"].get(f"{att_id}:{def_raw}"))
        d["skills"] = sorted(k for k, b in L["skills"].items() if bits(b, 1))
        d["ai_styles"] = sorted(k for k, b in L.get("ai_styles", {}).items() if bits(b, 1))
        return d


def decode_players(arch: Archive, layouts: dict) -> tuple[dict[int, dict], str]:
    data = arch.table("Player.bin")
    if data is None:
        raise WorldError(f"{arch.label}: no Player.bin in {arch.path.name}")
    stride, _ = pesdb.detect_player_layout(data)
    layout = layouts.get(str(stride))
    if layout is None:
        raise WorldError(f"{arch.label}: Player.bin uses a {stride}-byte record this reader has no map for. "
                         f"A game update changed the format — the reader needs a new field map.")
    dec = PlayerDecoder(layout)
    players = {}
    for i in range(0, len(data), stride):
        p = dec.decode(data[i:i + stride])
        players[p["pid"]] = p
    return players, f"{stride}-byte"


def sanity(label: str, players: dict[int, dict], pids: set[int]) -> dict:
    """Gate a whole archive: if its squad players do not decode like footballers, the field map does
    not fit this file and nothing from it may be trusted."""
    sample = [players[p] for p in pids if p in players]
    if not sample:
        raise WorldError(f"{label}: no squad player decodes")
    ok = lambda f: sum(1 for p in sample if f(p)) / len(sample)
    stats = {
        "height 150-210": ok(lambda p: p.get("height_cm") is None or 150 <= p["height_cm"] <= 210),
        "age 15-45": ok(lambda p: p.get("age") is None or 15 <= p["age"] <= 45),
        "position known": ok(lambda p: p.get("position") is not None),
        "abilities 40-99": ok(lambda p: all(40 <= a <= 99 for a in p["abilities"].values())),
    }
    failed = {k: round(v, 4) for k, v in stats.items() if v < 0.98}
    if failed:
        raise WorldError(f"{label}: the field map does not fit this archive — {failed}. "
                         f"Refusing to build a world from it.")
    return {k: round(v, 4) for k, v in stats.items()}


def decode_assignments(arch: Archive) -> dict[int, list[dict]]:
    data = arch.table("PlayerAssignment.bin")
    if data is None:
        raise WorldError(f"{arch.label}: no PlayerAssignment.bin")
    blocks: dict[int, list[dict]] = defaultdict(list)
    for r in pesdb.parse_player_assignment_bin(data):   # vendored Sider; v1 and v2 layouts
        blocks[r["team_id"]].append(r)
    return blocks


def decode_teams(arch: Archive) -> dict[int, dict]:
    data = arch.table("Team.bin")
    if data is None:
        raise WorldError(f"{arch.label}: no Team.bin")
    teams = {}
    for r in range(len(data) // 1600):
        rec = data[r * 1600:(r + 1) * 1600]
        tid = struct.unpack_from("<I", rec, 12)[0]
        teams[tid] = {"id": tid, "name": _text(rec[396:444]), "short_name": _text(rec[886:894]) or None}
    return teams


def decode_countries(arch: Archive) -> dict[int, str]:
    """Player nationality id -> English country name, from the game's own Country.bin
    (bits 9-18 of the 8-byte header; the English name is the fifth string)."""
    import re
    data = arch.table("Country.bin")
    if data is None:
        return {}
    out = {}
    for r in range(len(data) // 1488):
        rec = data[r * 1488:(r + 1) * 1488]
        strings = [s for s in re.split(b"\0+", rec[8:]) if len(s) > 1]
        if len(strings) > 4:
            out[(int.from_bytes(rec[:8], "little") >> 9) & 0x3FF] = _text(strings[4])
    return out


def decode_competitions(arch: Archive) -> tuple[dict[int, dict], dict[int, list[int]]]:
    comps = {}
    cu = arch.table("CompetitionUnit.bin")
    if cu is not None:
        for r in range(len(cu) // 2472):
            b = cu[r * 2472:(r + 1) * 2472]
            cid = struct.unpack_from("<H", b, 10)[0]
            names = [_text(b[56 + i * 115:56 + (i + 1) * 115]) for i in range(21)]
            comps.setdefault(cid, {"id": cid, "name": names[15] or names[19] or names[0],
                                   "lower": struct.unpack_from("<H", b, 4)[0],
                                   "parent": struct.unpack_from("<H", b, 6)[0]})
    members: dict[int, list[int]] = defaultdict(list)
    ctl = arch.table("CategoryTeamList.bin")
    if ctl is not None:
        rows = sorted(struct.unpack_from("<III", ctl, i * 12) for i in range(len(ctl) // 12))
        for team, cat, order in sorted(rows, key=lambda t: (t[1], t[2])):
            members[cat].append(team)
    return comps, members


# ============================================================================ building the world

def is_special(name: str) -> bool:
    low = (name or "").lower()
    return any(w in low for w in SPECIAL_TEAM_WORDS)


def build(archives: list[Archive], layouts: dict, log=print) -> dict:
    """Decode every archive and merge them into one world, in memory."""
    per = {}
    for arch in archives:
        players, layout = decode_players(arch, layouts)
        blocks = decode_assignments(arch)
        squad_pids = {r["player_id"] for rows in blocks.values() for r in rows}
        gate = sanity(arch.label, players, squad_pids)
        per[arch.label] = {"arch": arch, "players": players, "blocks": blocks, "layout": layout,
                           "teams": decode_teams(arch), "countries": decode_countries(arch),
                           "competitions": decode_competitions(arch), "gate": gate}
        log(f"  {arch.label}: {len(players):,} players ({layout}), {len(blocks):,} squads — gate {gate}")

    order = [a.label for a in archives]                     # primary first
    countries: dict[int, str] = {}
    for label in reversed(order):
        countries.update(per[label]["countries"])
    country_names = set(countries.values())

    # ---- clubs: take each team's squad block from the first archive (in priority order) that has one
    team_names: dict[int, dict] = {}
    for label in reversed(order):                            # primary's names win
        team_names.update(per[label]["teams"])
    clubs: dict[int, dict] = {}
    skipped = Counter()
    for label in order:
        for tid, rows in per[label]["blocks"].items():
            if tid in clubs:
                continue
            t = team_names.get(tid, {"name": f"Team {tid}", "short_name": None})
            if t["name"] in country_names:
                skipped["national team"] += 1
                continue
            if is_special(t["name"]):
                skipped["event/placeholder side"] += 1
                continue
            if len(rows) < MIN_SQUAD:
                skipped["fewer than 11 players"] += 1
                continue
            clubs[tid] = {"id": tid, "name": t["name"], "short_name": t["short_name"], "source": label,
                          "squad": [(r["player_id"], r["shirt_number"], i, r["role_mask"])
                                    for i, r in enumerate(rows)]}

    # ---- players: from the archive their club's squad came from; national-team-only players (their
    # club is not in the game) join as unattached, from the first archive that has them.
    players: dict[int, dict] = {}
    for c in clubs.values():
        src = per[c["source"]]["players"]
        for pid, *_ in c["squad"]:
            if pid not in players and pid in src:
                players[pid] = dict(src[pid], source=c["source"])
    unattached = 0
    for label in order:
        for tid, rows in per[label]["blocks"].items():
            if team_names.get(tid, {}).get("name") in country_names:
                for r in rows:
                    pid = r["player_id"]
                    if pid not in players and pid in per[label]["players"]:
                        players[pid] = dict(per[label]["players"][pid], source=label)
                        unattached += 1
    for p in players.values():
        p["nationality"] = countries.get(p["nat_id"])

    # ---- club country = the nationality most of its squad shares
    for c in clubs.values():
        nat = Counter(players[pid]["nationality"] for pid, *_ in c["squad"]
                      if pid in players and players[pid]["nationality"])
        c["country"] = nat.most_common(1)[0][0] if nat else None

    # ---- leagues: a category is a domestic league when enough of our clubs sit in it and most of
    # them share one country. Continental cups (many countries), national-team tournaments (no
    # clubs) and empty prefecture lists all fail that test without a hand-kept list of ids.
    comps: dict[int, dict] = {}
    members: dict[int, list[int]] = {}
    for label in order:
        c_map, m_map = per[label]["competitions"]
        for cid, comp in c_map.items():
            if cid not in comps:
                comps[cid] = comp
                members[cid] = m_map.get(cid, [])
    leagues: dict[int, dict] = {}
    for cid, comp in comps.items():
        if cid >= 65536:
            continue
        mem = [t for t in members.get(cid, []) if t in clubs]
        if len(mem) < MIN_LEAGUE_CLUBS:
            continue
        cc = Counter(clubs[t]["country"] for t in mem if clubs[t]["country"])
        if not cc:
            continue
        country, n = cc.most_common(1)[0]
        if n / len(mem) < MIN_LEAGUE_ONE_COUNTRY:
            continue
        leagues[cid] = {"id": cid, "name": comp["name"], "country": country, "clubs": mem,
                        "parent": comp["parent"], "tier": 1}
    for lg in leagues.values():                              # tier from the parent chain
        depth, seen, cur = 1, set(), lg
        while cur["parent"] in leagues and cur["parent"] not in seen and cur["parent"] != cur["id"]:
            seen.add(cur["id"])
            cur = leagues[cur["parent"]]
            depth += 1
        lg["tier"] = depth
    for lg in sorted(leagues.values(), key=lambda x: (x["tier"], x["id"])):
        for t in lg["clubs"]:
            clubs[t].setdefault("league_id", lg["id"])

    return {"per": per, "order": order, "clubs": clubs, "players": players, "leagues": leagues,
            "skipped": dict(skipped), "unattached": unattached}


# ============================================================================ writing the database

def refuse_foreign(out: Path) -> None:
    if not out.exists():
        return
    try:
        con = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
        row = con.execute("SELECT value FROM meta WHERE key='world_source'").fetchone()
        con.close()
    except sqlite3.Error:
        row = None
    if not row or row[0] != "game":
        raise WorldError(f"{out} exists and was not built by game_world.py — refusing to replace it. "
                         f"(This tool never writes over the curated master.db.)")


def write(world: dict, out: Path, replace: bool) -> dict:
    refuse_foreign(out)
    if out.exists() and not replace:
        raise WorldError(f"{out} already exists; pass --replace to rebuild it")
    if not SCHEMA.exists():
        raise WorldError(f"schema not found: {SCHEMA}")
    tmp = out.with_name(out.name + ".building")
    if tmp.exists():
        tmp.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("CREATE TABLE IF NOT EXISTS world_leagues (league_id INTEGER PRIMARY KEY, "
                "country TEXT NOT NULL, source TEXT)")
    con.execute("BEGIN")
    leagues, clubs, players = world["leagues"], world["clubs"], world["players"]
    con.executemany("INSERT INTO leagues(id,name,tier,competition_slot) VALUES(?,?,?,?)",
                    [(l["id"], l["name"], l["tier"], l["id"]) for l in leagues.values()])
    con.executemany("INSERT INTO world_leagues(league_id,country,source) VALUES(?,?,?)",
                    [(l["id"], l["country"], "game") for l in leagues.values()])
    con.executemany(
        "INSERT INTO teams(id,game_team_id,base_team_id,is_custom,name,short_name,league_id,budget,team_kind) "
        "VALUES(?,?,?,0,?,?,?,0,'first')",
        [(c["id"], c["id"], c["id"], c["name"], c["short_name"], c.get("league_id")) for c in clubs.values()])
    prow, arow, srow, krow = [], [], [], []
    for p in players.values():
        prow.append((p["pid"], p["pid"], p["pid"], p["name"], p["short_name"], p.get("position") or "CMF",
                     p.get("age"), p.get("nationality"), p.get("height_cm"), p.get("weight_kg")))
        arow += [(p["pid"], k, v) for k, v in p["abilities"].items()]
        for col, table in (("foot", FOOT), ("weak_foot_usage", WEAK_FOOT), ("weak_foot_accuracy", WEAK_FOOT),
                           ("form", FORM), ("injury_resistance", INJURY)):
            code = table.get(p.get(col) or "")
            if code is not None:
                arow.append((p["pid"], col, code))
        if p.get("primary_style"):
            srow.append((p["pid"], p["primary_style"], "primary"))
        if p.get("secondary_style"):
            srow.append((p["pid"], p["secondary_style"], "secondary"))
        krow += [(p["pid"], s, "innate") for s in p["skills"]]
    con.executemany("INSERT INTO players(id,game_pid,base_pid,is_custom,name,short_name,position,age,"
                    "nationality,height_cm,weight_kg) VALUES(?,?,?,0,?,?,?,?,?,?,?)", prow)
    con.executemany("INSERT INTO player_attributes(player_id,attribute,value) VALUES(?,?,?)", arow)
    con.executemany("INSERT INTO player_playstyles(player_id,playstyle,kind) VALUES(?,?,?)", srow)
    con.executemany("INSERT INTO player_skills(player_id,skill,source) VALUES(?,?,?)", krow)
    sm = []
    for c in clubs.values():
        seen = set()
        for pid, shirt, slot, role in c["squad"]:
            if pid in players and pid not in seen:
                seen.add(pid)
                sm.append((c["id"], pid, shirt if 1 <= shirt <= 99 else 99, slot, role))
    con.executemany("INSERT INTO squad_members(team_id,player_id,squad_number,slot,role) VALUES(?,?,?,?,?)", sm)
    meta = {
        "world_source": "game",
        "world_reader_version": str(READER_VERSION),
        "world_built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "career_player_band": f"{CAREER_PLAYER_BAND[0]},{CAREER_PLAYER_BAND[1]}",
        "world_archives": json.dumps({lab: world["per"][lab]["arch"].fingerprint() for lab in world["order"]}),
    }
    con.executemany("INSERT INTO meta(key,value) VALUES(?,?)", list(meta.items()))
    con.commit()
    con.close()
    os.replace(tmp, out)
    return {"players": len(prow), "attribute_rows": len(arow), "playstyle_rows": len(srow),
            "skill_rows": len(krow), "squad_rows": len(sm), "clubs": len(clubs), "leagues": len(leagues)}


# ============================================================================ command line

def find_archives(args) -> list[Archive]:
    if args.dt200 or args.dt870:
        pairs = [("dt200", args.dt200), ("dt870", args.dt870)]
    else:
        if args.game_dir:
            os.environ["ML_EFOOTBALL_DIR"] = args.game_dir
        from steam_paths import game_cpk_dir
        cpk = game_cpk_dir()
        pairs = [("dt200", cpk / "dt200_console_all.cpk"), ("dt870", cpk / "dt870_console_win.cpk")]
    out = []
    for label, p in pairs:
        if p and Path(p).exists():
            out.append(Archive(label, Path(p)))
    if not out or out[0].label != "dt200":
        raise WorldError("dt200_console_all.cpk not found — it is the archive the game reads, and the "
                         "world is built from it first. Point --game-dir at your eFootball folder.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--game-dir", default=None, help="the eFootball install folder (default: found via Steam)")
    ap.add_argument("--dt200", default=None)
    ap.add_argument("--dt870", default=None)
    ap.add_argument("--layouts", default=str(LAYOUTS))
    ap.add_argument("--replace", action="store_true", help="rebuild a world this tool built before")
    ap.add_argument("--dry", action="store_true", help="decode and report; write nothing")
    args = ap.parse_args()
    t0 = time.time()
    try:
        layouts = json.loads(Path(args.layouts).read_text(encoding="utf-8"))["layouts"]
        archives = find_archives(args)
        print("reading " + ", ".join(f"{a.label} ({a.path.name})" for a in archives))
        world = build(archives, layouts)
        clubs, leagues, players = world["clubs"], world["leagues"], world["players"]
        in_league = sum(1 for c in clubs.values() if c.get("league_id"))
        print(f"clubs {len(clubs):,} ({in_league:,} in a league, {len(clubs) - in_league:,} unaffiliated); "
              f"players {len(players):,} ({world['unattached']:,} unattached national-team players); "
              f"skipped squads {world['skipped']}")
        by_country = defaultdict(list)
        for lg in leagues.values():
            by_country[lg["country"]].append(lg)
        print(f"leagues {len(leagues)} in {len(by_country)} countries:")
        for country in sorted(by_country):
            print("  " + country + ": " + "; ".join(f"{l['name']} (tier {l['tier']}, {len(l['clubs'])} clubs)"
                                                     for l in sorted(by_country[country], key=lambda x: x['tier'])))
        if args.dry:
            print(f"dry run — nothing written ({time.time() - t0:.1f}s)")
            return 0
        counts = write(world, Path(args.out), args.replace)
        print(f"wrote {args.out}: {counts} ({time.time() - t0:.1f}s)")
        return 0
    except WorldError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
