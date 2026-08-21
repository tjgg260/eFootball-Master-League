"""Extract every dt200 team: current name, league membership, and squad (Latin player names).

The base game gives unlicensed clubs placeholder names ("Manchester B") but their SQUADS are
real, so a club is identifiable from its players. This dumps the data we identify clubs from
and later rename against. Read-only.

Outputs build/dt200_teams.json: {team_id: {name, category, order, players: [...]}}.
Usage: python tools/dt200_extract_teams.py [--league CATEGORY]
"""
from __future__ import annotations

import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from vendor.sider.wesys import unpack_wesys_payload

PESDB = ROOT / "build/tree_base/common/etc/pesdb"


def load(fn):
    return unpack_wesys_payload((PESDB / fn).read_bytes())


def main():
    team = load("Team.bin")
    pl = load("Player.bin")
    pa = load("PlayerAssignment.bin")
    ctl = load("CategoryTeamList.bin")

    names = {}                                    # team id -> english placeholder name
    for r in range(len(team) // 1600):
        tid = struct.unpack_from("<I", team, r * 1600 + 12)[0]
        names[tid] = team[r * 1600 + 396:r * 1600 + 396 + 48].split(b"\0")[0].decode("utf-8", "replace")

    pname = {}                                    # card id -> latin full name (field 3 @271)
    prate = {}                                    # card id -> overall (byte 68, best-effort)
    for r in range(len(pl) // 400):
        cid = struct.unpack_from("<Q", pl, r * 400 + 8)[0]
        pname[cid] = pl[r * 400 + 271:r * 400 + 271 + 61].split(b"\0")[0].decode("utf-8", "replace")

    squad = defaultdict(list)
    for i in range(len(pa) // 24):
        cid = struct.unpack_from("<Q", pa, i * 24 + 8)[0]
        tid = struct.unpack_from("<I", pa, i * 24 + 16)[0]
        squad[tid].append(cid)

    cat_of, order_of = {}, {}
    cats = defaultdict(list)
    for i in range(len(ctl) // 12):
        t, c, idx = struct.unpack_from("<III", ctl, i * 12)
        cat_of[t] = c
        order_of[t] = idx
        cats[c].append(t)

    out = {}
    for tid, nm in names.items():
        out[tid] = {
            "name": nm,
            "category": cat_of.get(tid),
            "order": order_of.get(tid),
            "players": [pname.get(c, "?") for c in squad.get(tid, [])[:8]],
        }
    dest = ROOT / "build" / "dt200_teams.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {dest} ({len(out)} teams, {len(cats)} categories)")

    # print one league (club-sized) for identification, or the requested one
    want = None
    if "--league" in sys.argv:
        want = int(sys.argv[sys.argv.index("--league") + 1])
    for c, ts in cats.items():
        if want is not None and c != want:
            continue
        if want is None and not (16 <= len(ts) <= 24):
            continue
        print(f"\n=== category {c} ({len(ts)} teams) ===")
        for tid in sorted(ts, key=lambda t: order_of.get(t, 0)):
            stars = ", ".join(out[tid]["players"][:5])
            print(f"  {tid:6} {out[tid]['name']:26} | {stars}")
        if want is None:
            break


if __name__ == "__main__":
    raise SystemExit(main())
