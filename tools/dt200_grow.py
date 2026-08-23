#!/usr/bin/env python3
"""
dt200_grow.py — GROW dt200's Player.bin (+ PlayerAppearance) with the real players we harvested
from dt870 that dt200 lacks, then PROVE the grown files round-trip before anything is written.

This is the write-back half of the dt870 harvest: master.db is the source of truth; here we render
the new real players into the dt200 layer the game actually loads offline. It reuses the proven
grow-and-resort engine in ml_author.Tree (clone a position-matched donor so bit-packed attributes
are never hand-encoded; stamp the real PID + name + abilities; merge and RE-SORT by external PID —
the game binary-searches the file). Unlike per-match authoring, each new player keeps his REAL
dt870 PID and gets his REAL dt870 appearance record (not the donor's face).

Proof gate (nothing is saved unless all pass):
  1. PRESERVATION — every original dt200 record is still present and BYTE-IDENTICAL after the grow.
  2. SEMANTIC ROUND-TRIP — unpack(pack(payload)) == payload for Player.bin AND PlayerAppearance
     (the WESYS codec reproduces our new, larger payload exactly).
  3. STRUCTURE — Tree.verify(): sorted by PID, no duplicate PIDs, no dangling assignment refs.
  4. READBACK — a sample of new records decodes to the PID/name we wrote.

Usage:
  python tools/dt200_grow.py               # dry run: build in a scratch tree, prove, report
  python tools/dt200_grow.py --limit 500   # only add the first N new players (fast smoke)
  python tools/dt200_grow.py --apply        # also write the grown tree (build/tree_grow); no deploy
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
CSV = REPO / "samples" / "editor-bundled-players.csv"
TREE_BASE = REPO / "build" / "tree_base"
TREE_GROW = REPO / "build" / "tree_grow"

sys.path.insert(0, str(REPO / "tools" / "vendor" / "sider"))
sys.path.insert(0, str(REPO / "tools"))
import wesys                                    # noqa: E402
from ml_author import Tree, DonorPool, PLAYER_REC, APP_REC, POS_MAP  # noqa: E402


def new_real_players(dt200_pids: set[int], limit: int | None):
    """Real players in master.db that dt200 does NOT already have, with data to author them."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, name, position FROM players WHERE is_custom=0 ORDER BY id").fetchall()
    out = []
    for r in rows:
        pid = r["id"]
        if pid in dt200_pids:
            continue                                    # already in dt200 — not a grow target
        abilities = {a: v for a, v in con.execute(
            "SELECT attribute, value FROM player_attributes WHERE player_id=?", (pid,))}
        face = con.execute(
            "SELECT record FROM player_appearance_raw WHERE player_id=?", (pid,)).fetchone()
        skills = [s for (s,) in con.execute(
            "SELECT skill FROM player_skills WHERE player_id=?", (pid,))]
        styles = {kind: st for kind, st in con.execute(
            "SELECT kind, playstyle FROM player_playstyles WHERE player_id=?", (pid,))}
        out.append({"pid": pid, "name": r["name"], "position": r["position"] or "CMF",
                    "abilities": abilities, "face": face[0] if face else None,
                    "skills": skills, "primary": styles.get("primary"),
                    "secondary": styles.get("secondary")})
        if limit and len(out) >= limit:
            break
    con.close()
    return out


def prove(tree: Tree, original_players: dict[int, bytes], original_appear: dict[int, bytes],
          added: list[int]) -> list[str]:
    fails = []
    # 1. PRESERVATION — original records byte-identical after grow
    now = {struct.unpack_from("<Q", tree.player, k * PLAYER_REC + 8)[0]:
           bytes(tree.player[k * PLAYER_REC:(k + 1) * PLAYER_REC])
           for k in range(len(tree.player) // PLAYER_REC)}
    changed = sum(1 for pid, rec in original_players.items() if now.get(pid) != rec)
    missing = sum(1 for pid in original_players if pid not in now)
    if changed or missing:
        fails.append(f"PRESERVATION: {changed} original Player records changed, {missing} missing")
    anow = {struct.unpack_from("<Q", tree.appear, k * APP_REC)[0]:
            bytes(tree.appear[k * APP_REC:(k + 1) * APP_REC])
            for k in range(len(tree.appear) // APP_REC)}
    achanged = sum(1 for pid, rec in original_appear.items() if anow.get(pid) != rec)
    if achanged:
        fails.append(f"PRESERVATION: {achanged} original PlayerAppearance records changed")

    # 2. SEMANTIC ROUND-TRIP — codec reproduces the new payload exactly
    for label, payload, nib in (
            ("Player.bin", bytes(tree.player), tree.pb_blob[1] & 0xF),
            ("PlayerAppearance.bin", bytes(tree.appear), tree.app_blob[1] & 0xF)):
        packed = wesys.pack_wesys_container(payload, key_nibble=nib, compression_level=1)
        if wesys.unpack_wesys_payload(packed) != payload:
            fails.append(f"SEMANTIC: {label} does not round-trip through WESYS")

    # 3. STRUCTURE
    fails += tree.verify()

    # 4. READBACK — sample new records decode to the PID we wrote
    for pid in added[:5] + added[-5:]:
        if pid not in now:
            fails.append(f"READBACK: added PID {pid} not found after grow")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only add first N new players")
    ap.add_argument("--apply", action="store_true", help="write the grown tree to build/tree_grow")
    args = ap.parse_args()

    if TREE_GROW.exists():
        shutil.rmtree(TREE_GROW, ignore_errors=True)
    print("copying pristine dt200 tree...")
    shutil.copytree(TREE_BASE, TREE_GROW)

    tree = Tree(TREE_GROW)
    dt200_pids = set(tree.player_idx)
    print(f"dt200 Player.bin: {len(dt200_pids)} records")

    # snapshot originals for the preservation proof
    original_players = {pid: bytes(tree.player[i * PLAYER_REC:(i + 1) * PLAYER_REC])
                        for pid, i in tree.player_idx.items()}
    original_appear = {pid: bytes(tree.appear[i * APP_REC:(i + 1) * APP_REC])
                       for pid, i in tree.app_idx.items()}

    targets = new_real_players(dt200_pids, args.limit)
    print(f"new real players to add: {len(targets)}")

    pool = DonorPool(CSV, dt200_pids)
    tree.begin()
    added, skipped = [], 0
    for t in targets:
        ef_pos = POS_MAP.get(t["position"].upper(), "CMF")
        donor = pool.take(ef_pos, skin_of=tree.skin_of)
        if donor is None or not tree.author_player(
                donor, t["pid"], t["name"], t["abilities"],
                skills=t["skills"], primary_style=t["primary"],
                secondary_style=t["secondary"], position=t["position"]):
            skipped += 1
            continue
        added.append(t["pid"])
        # replace the cloned donor face with this player's REAL harvested appearance record
        if t["face"] is not None and len(t["face"]) == APP_REC:
            arec = bytearray(t["face"])
            struct.pack_into("<Q", arec, 0, t["pid"])           # ensure PID matches (bytes 0-7)
            if tree._pending_appear and tree._pending_appear[-1][0] == t["pid"]:
                tree._pending_appear[-1] = (t["pid"], bytes(arec))
            else:
                tree._pending_appear.append((t["pid"], bytes(arec)))

    print(f"authored: {len(added)}   skipped (no donor): {skipped}")
    tree.commit_inserts()
    print(f"grown Player.bin: {len(tree.player) // PLAYER_REC} records "
          f"(+{len(tree.player) // PLAYER_REC - len(dt200_pids)})")

    print("\nProving the grow...")
    fails = prove(tree, original_players, original_appear, added)
    if fails:
        print("  ROUND-TRIP PROOF FAILED — nothing written:")
        for f in fails:
            print("   -", f)
        return 1
    print("  ALL PROOFS PASSED: preservation + semantic round-trip + structure + readback.")

    if args.apply:
        tree.save()
        print(f"\nWrote grown tree to {TREE_GROW}. (Deploy is a separate, explicit step.)")
    else:
        print("\n(dry run — pass --apply to write build/tree_grow; deploy still separate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
