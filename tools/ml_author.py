#!/usr/bin/env python3
"""
ml_author.py — author real squads into an eFootball CPK tree by clone-and-edit.

Given a squad spec (real clubs + real player names/positions) and a host league of existing
team slots, this:

  1. renames each host team to the real club name (Team.bin, in-place name field),
  2. for each real player, clones a POSITION-MATCHED, LOW-RATED existing player as a donor
     (so the bit-packed attributes and position are inherited, never hand-encoded), stamps a
     fresh PID and the real name into Player.bin, and clones the donor's PlayerAppearance so
     the face isn't a silhouette,
  3. re-sorts Player.bin and PlayerAppearance by external PID (the game binary-searches both),
  4. reassigns the host team's squad slots to the authored players (PlayerAssignment, PID +
     shirt only — headcount unchanged, so every squad invariant is preserved).

Why clone rather than encode from scratch: attributes/position/skills are bit-packed and not
byte-aligned. Cloning a real donor of the right profile sidesteps all of that — we only ever
overwrite byte-aligned fields (PID at 0/8, names at 210/271/332). Proven safe: a cloned +
renamed player boots and plays (Paul Mullin).

The only save-corrupting mistake is a dangling PID (assignment -> missing player); every author
here inserts the Player.bin record first, so that cannot happen.

Deploy is separate: write the tree, then rebuild with cpkmakec -align=512 (see ml_deploy notes).

Usage:
    python tools/ml_author.py --tree build/tree_nl --spec build/nl_squads.json
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
sys.path.insert(0, str(REPO / "tools"))
import wesys   # noqa: E402
import pesdb   # noqa: E402
from ability_bits import write_abilities as _write_abilities   # noqa: E402

PLAYER_REC = 400
APP_REC = 64
PID_BASE = 9_000_000   # fresh block: above the top base card (8.57M), below the 2^24 variants

# Name field offsets inside a 400-byte Player.bin record (dt200 layout).
NAME_SHORT_UP = 210   # "M. SALAH"
NAME_FULL = 271       # "Mohamed Salah"  <- the display name
NAME_SHORT = 332      # "M.SALAH"

# Map source position strings onto the eFootball position codes the donor CSV uses.
POS_MAP = {
    "GK": "GK",
    "DF": "CB", "CB": "CB", "DEF": "CB", "D": "CB",
    "LB": "LB", "LWB": "LB", "RB": "RB", "RWB": "RB",
    "DMF": "DMF", "DM": "DMF", "CDM": "DMF",
    "MF": "CMF", "CM": "CMF", "CMF": "CMF", "M": "CMF",
    "LMF": "LMF", "LM": "LMF", "RMF": "RMF", "RM": "RMF",
    "AMF": "AMF", "AM": "AMF", "CAM": "AMF",
    "LW": "LWF", "LWF": "LWF", "RW": "RWF", "RWF": "RWF", "W": "LWF",
    "SS": "SS", "CF": "CF", "ST": "CF", "FW": "CF", "F": "CF", "STRIKER": "CF",
}


def short_name(full: str) -> str:
    parts = full.split()
    if len(parts) == 1:
        return parts[0].upper()
    return (parts[0][0] + ". " + parts[-1]).upper()


class DonorPool:
    """Existing players indexed by eFootball position, ascending by overall rating."""

    def __init__(self, csv_path: Path, valid_pids: set[int]):
        # The bundled CSV (42k players) is a superset of dt200's Player.bin (23.5k). A donor we
        # cannot actually clone is useless, so keep only donors that exist in this Player.bin.
        rows = list(csv.DictReader(io.StringIO(csv_path.read_bytes().decode("utf-8-sig"))))
        self.by_pos: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for r in rows:
            try:
                pid = int(r["player_id"]); rating = int(r["overall_rating"])
            except (ValueError, KeyError):
                continue
            if pid not in valid_pids:
                continue
            pos = r["position"].strip().upper()
            if pos:
                self.by_pos[pos].append((rating, pid))
        for pos in self.by_pos:
            self.by_pos[pos].sort()
        self._cursor: dict[str, int] = defaultdict(int)

    def take(self, ef_pos: str, lo: int = 58, hi: int = 74) -> int | None:
        """
        A donor of this position in a lower-league rating band. Donors are REUSED round-robin
        rather than consumed — cloning one donor for several authored players is safe (each
        gets its own PID and name), and it guarantees every slot can be filled.
        """
        pool = self.by_pos.get(ef_pos) or self.by_pos.get("CMF") or []
        band = [pid for rating, pid in pool if lo <= rating <= hi] or [pid for _, pid in pool]
        if not band:
            return None
        i = self._cursor[ef_pos] % len(band)
        self._cursor[ef_pos] += 1
        return band[i]


class Tree:
    def __init__(self, tree: Path):
        self.tree = tree
        self.pb = tree / "common/etc/pesdb/Player.bin"
        self.pa = tree / "common/etc/pesdb/PlayerAssignment.bin"
        self.app = tree / "common/etc/appearance/PlayerAppearance.bin"
        self.team = tree / "common/etc/pesdb/Team.bin"
        for f in (self.pb, self.pa, self.app, self.team):
            if not f.exists():
                sys.exit(f"missing {f}")
        self._load()

    def _load(self):
        self.pb_blob = self.pb.read_bytes()
        self.app_blob = self.app.read_bytes()
        self.pa_blob = self.pa.read_bytes()
        self.team_blob = self.team.read_bytes()
        self.player = bytearray(wesys.unpack_wesys_payload(self.pb_blob))
        self.appear = bytearray(wesys.unpack_wesys_payload(self.app_blob))
        self.assign = bytearray(wesys.unpack_wesys_payload(self.pa_blob))
        self.teamp = bytearray(wesys.unpack_wesys_payload(self.team_blob))
        # index Player.bin donor records by PID
        self.player_idx = {}
        for k in range(len(self.player) // PLAYER_REC):
            pid = struct.unpack_from("<Q", self.player, k * PLAYER_REC + 8)[0]
            self.player_idx[pid] = k
        self.app_idx = {}
        for k in range(len(self.appear) // APP_REC):
            pid = struct.unpack_from("<Q", self.appear, k * APP_REC)[0]
            self.app_idx[pid] = k
        alay = pesdb.detect_assignment_layout(bytes(self.assign))
        self.a_v2 = alay.endswith("/v2")
        self.a_pid = 0 if self.a_v2 else 8
        self.a_shirt = 16 if self.a_v2 else 20

    # --- authoring ------------------------------------------------------------

    def author_player(self, donor_pid: int, new_pid: int, full_name: str,
                      abilities: dict[str, int] | None = None) -> bool:
        di = self.player_idx.get(donor_pid)
        if di is None:
            return False
        rec = bytearray(self.player[di * PLAYER_REC:(di + 1) * PLAYER_REC])
        struct.pack_into("<Q", rec, 0, new_pid)   # native PID
        struct.pack_into("<Q", rec, 8, new_pid)   # external PID
        for off, val in ((NAME_FULL, full_name),
                         (NAME_SHORT_UP, short_name(full_name)),
                         (NAME_SHORT, short_name(full_name))):
            b = val.encode("utf-8")[:60]
            rec[off:off + 61] = b + b"\x00" * (61 - len(b))
        # Write the player's REAL (translated) abilities over the donor's, so they play with
        # their own attributes rather than the cloned template's. The bit offsets are verified.
        if abilities:
            _write_abilities(rec, abilities)
        self._pending_players.append((new_pid, bytes(rec)))
        # appearance: clone donor's if present
        ai = self.app_idx.get(donor_pid)
        if ai is not None:
            arec = bytearray(self.appear[ai * APP_REC:(ai + 1) * APP_REC])
            struct.pack_into("<Q", arec, 0, new_pid)
            self._pending_appear.append((new_pid, bytes(arec)))
        return True

    def rename_team(self, team_id: int, name: str):
        for b in range(0, len(self.teamp), 1600):
            if struct.unpack_from("<I", self.teamp, b + 12)[0] == team_id:
                ns = b + 396
                self.teamp[ns:ns + 490] = b"\x00" * 490
                enc = name.encode("utf-8")[:480]
                self.teamp[ns:ns + len(enc)] = enc
                return True
        return False

    def assign_slot(self, team_id: int, slot_index: int, new_pid: int, shirt: int | None):
        """Overwrite an existing squad slot's occupant. Headcount unchanged."""
        recs = pesdb.parse_player_assignment_bin(bytes(self.assign))
        squad = sorted((r for r in recs if r["team_id"] == team_id), key=lambda r: r["sort_key"])
        if slot_index >= len(squad):
            return False
        r = squad[slot_index]
        base = r["index"] * 24
        struct.pack_into("<Q", self.assign, base + self.a_pid, new_pid)
        if shirt:
            self.assign[base + self.a_shirt] = max(0, min(98, shirt - 1))
        return True

    def squad_size(self, team_id: int) -> int:
        recs = pesdb.parse_player_assignment_bin(bytes(self.assign))
        return sum(1 for r in recs if r["team_id"] == team_id)

    # --- commit ---------------------------------------------------------------

    _pending_players: list = []
    _pending_appear: list = []

    def begin(self):
        self._pending_players = []
        self._pending_appear = []

    def commit_inserts(self):
        # merge new records and re-sort by external PID (both files binary-searched)
        recs = [self.player[k * PLAYER_REC:(k + 1) * PLAYER_REC]
                for k in range(len(self.player) // PLAYER_REC)]
        recs += [r for _, r in self._pending_players]
        recs.sort(key=lambda r: struct.unpack_from("<Q", r, 8)[0])
        self.player = bytearray(b"".join(recs))

        arecs = [self.appear[k * APP_REC:(k + 1) * APP_REC]
                 for k in range(len(self.appear) // APP_REC)]
        arecs += [r for _, r in self._pending_appear]
        arecs.sort(key=lambda r: struct.unpack_from("<Q", r, 0)[0])
        self.appear = bytearray(b"".join(arecs))

    def verify(self) -> list[str]:
        problems = []
        pids = [struct.unpack_from("<Q", self.player, k * PLAYER_REC + 8)[0]
                for k in range(len(self.player) // PLAYER_REC)]
        if pids != sorted(pids):
            problems.append("Player.bin not sorted by external PID")
        if len(pids) != len(set(pids)):
            problems.append("Player.bin has duplicate PIDs")
        apids = [struct.unpack_from("<Q", self.appear, k * APP_REC)[0]
                 for k in range(len(self.appear) // APP_REC)]
        if apids != sorted(apids):
            problems.append("PlayerAppearance.bin not sorted")
        # dangling refs: every assignment PID must exist in Player.bin
        player_set = set(pids)
        arecs = pesdb.parse_player_assignment_bin(bytes(self.assign))
        missing = {r["player_id"] for r in arecs if r["player_id"] not in player_set}
        if missing:
            problems.append(f"{len(missing)} assignment PIDs missing from Player.bin (dangling)")
        return problems

    def save(self):
        self.pb.write_bytes(wesys.pack_wesys_container(bytes(self.player), key_nibble=self.pb_blob[1] & 0xF, compression_level=1))
        self.app.write_bytes(wesys.pack_wesys_container(bytes(self.appear), key_nibble=self.app_blob[1] & 0xF, compression_level=1))
        self.pa.write_bytes(wesys.pack_wesys_container(bytes(self.assign), key_nibble=self.pa_blob[1] & 0xF, compression_level=1))
        self.team.write_bytes(wesys.pack_wesys_container(bytes(self.teamp), key_nibble=self.team_blob[1] & 0xF, compression_level=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--spec", required=True, help="JSON: {clubs:[{club, host_team_id, players:[{name,position,shirt}]}]}")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    t = Tree(Path(args.tree))
    donors = DonorPool(REPO / "samples" / "editor-bundled-players.csv", set(t.player_idx))
    t.begin()

    next_pid = PID_BASE + 1
    authored = 0
    for club in spec["clubs"]:
        tid = club["host_team_id"]
        n_slots = t.squad_size(tid)
        t.rename_team(tid, club["club"])
        players = club["players"][:n_slots]   # trim to host slot count
        for i, p in enumerate(players):
            ef_pos = POS_MAP.get(p["position"].strip().upper(), "CMF")
            donor = donors.take(ef_pos)
            if donor is None:
                continue
            if t.author_player(donor, next_pid, p["name"]):
                t.assign_slot(tid, i, next_pid, p.get("shirt") or None)
                next_pid += 1
                authored += 1
        print(f"  {club['club']} (team {tid}): {len(players)}/{n_slots} slots -> authored")

    t.commit_inserts()
    problems = t.verify()
    if problems:
        print("\nVERIFY FAILED - nothing written:")
        for p in problems:
            print("  -", p)
        return 1
    t.save()
    print(f"\nAuthored {authored} players across {len(spec['clubs'])} clubs. Tree written: {args.tree}")
    print("Next: rebuild with cpkmakec -align=512 and install.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
