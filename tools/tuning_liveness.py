#!/usr/bin/env python3
"""
tuning_liveness.py - check a dt270 tuning pack against the liveness map, and split it into the
edits that touch fields the game PROVABLY READS and the ones it does not.

    python tools/tuning_liveness.py check tools/data/tunings/game-feel.json
    python tools/tuning_liveness.py split tools/data/tunings/game-feel.json      # -> tunings/proven/
    python tools/tuning_liveness.py split-all                                    # every pack

Why: a dt270 field being parsed by the loader does not mean anything reads it. We tuned several
dead fields for weeks (shoot.control_dy.gageMax, basePosition.pressRate, ...). The liveness map
(tools/dt270_liveness.py -> build/dt270_liveness.json) says, per field, whether an instruction in
eFootball.exe reads it. This tool keeps a pack honest against that map.

Statuses (from the map, plus one hand-proven override):
    read / cached   an instruction reads the field                  -> KEPT
    dead-load       read, but hand-proven overwritten before use    -> DROPPED
    unread          the object's pointer flow was followed, no reader found -> DROPPED (held)
    unlocated       no pointer source found for the object; says nothing    -> DROPPED (held)
    not-found       path does not exist in the map                  -> DROPPED (check the path)
'read' is necessary, not sufficient: it does not prove the value changes gameplay.
Re-run dt270_liveness.py build after every Konami patch, then split-all again.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAP = REPO / "build" / "dt270_liveness.json"
TUNINGS = REPO / "tools" / "data" / "tunings"
OUT = TUNINGS / "proven"

# Read by an instruction but hand-proven to have no effect (docs/exe-gameplay-map.md).
DEAD_LOADS = {
    ("basePosition", "forceDashDistDefence"): "load at 0x143da9420 is overwritten by 19-0.1*attr before use",
}
KEEP = {"read", "cached"}


def norm(path: str) -> str:
    """RouteParameter[7].acc / receiveSpeed.0 -> RouteParameter[].acc / receiveSpeed[]"""
    path = re.sub(r"\[\d+\]", "[]", path)
    return re.sub(r"\.(\d+)(?=\.|$)", "[]", path)


def load_map():
    if not MAP.exists():
        sys.exit(f"{MAP} missing - run: python tools/dt270_liveness.py build")
    return json.loads(MAP.read_text(encoding="utf-8"))["objects"]


def status_of(objects, obj: str, path: str):
    """-> (status, n_readers, note)"""
    n = norm(path)
    if (obj, n) in DEAD_LOADS:
        return "dead-load", 0, DEAD_LOADS[(obj, n)]
    o = objects.get(obj)
    if o is None:
        return "not-found", 0, f"no object {obj!r} in the map"
    bare = n.replace("[]", "")
    hits = [f for f in o["fields"]
            if f["path"] in (n, n + "[]") or f["path"].startswith((n + ".", n + "[]."))
            or f["path"].replace("[]", "") == bare]
    if not hits:
        return "not-found", 0, f"no field {n!r} in {obj}"
    sts = {f["status"] for f in hits}
    readers = {r.get("va") for f in hits for r in f.get("readers", [])}
    for s in ("read", "cached", "unread", "unlocated"):
        if s in sts:
            return s, len(readers), ""
    return sorted(sts)[0], len(readers), ""


def load_pack(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    comment = data.get("_comment", "") if isinstance(data, dict) else ""
    edits = data.get("edits", data) if isinstance(data, dict) else data
    return comment, [e for e in edits if isinstance(e, dict) and "object" in e and "path" in e]


def classify(objects, edits):
    rows = []
    for e in edits:
        st, n, note = status_of(objects, e["object"], e["path"])
        rows.append((e, st, n, note))
    return rows


def cmd_check(a) -> int:
    objects = load_map()
    _c, edits = load_pack(Path(a.pack))
    rows = classify(objects, edits)
    seen = {}
    for e, st, n, note in rows:
        seen.setdefault((e["object"], norm(e["path"])), (st, n, note))
    for (obj, p), (st, n, note) in sorted(seen.items(), key=lambda kv: (kv[1][0] not in KEEP, kv[0])):
        print(f"  {st:10} {obj}.{p}" + (f"   readers={n}" if n else "") + (f"   [{note}]" if note else ""))
    c = collections.Counter(v[0] for v in seen.values())
    print(f"\n{len(seen)} distinct fields: " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    return 0


def split_pack(objects, pack: Path, out: Path):
    comment, edits = load_pack(pack)
    rows = classify(objects, edits)
    kept = [dict(e, _liveness=st) for e, st, _n, _note in rows if st in KEEP]
    dropped = [dict(e, _liveness=st, _why=note or st) for e, st, _n, note in rows if st not in KEEP]
    out.mkdir(parents=True, exist_ok=True)
    head = f"PROVEN-READ subset of {pack.name}: only edits to fields an instruction in eFootball.exe reads. "
    (out / pack.name).write_text(json.dumps({"_comment": head + comment, "edits": kept}, indent=1), encoding="utf-8")
    if dropped:
        (out / (pack.stem + ".dropped.json")).write_text(json.dumps(
            {"_comment": f"Edits from {pack.name} NOT in the proven pack, with the reason. 'unread'/'unlocated' "
                         "are held, not condemned - re-check after the liveness map improves.",
             "edits": dropped}, indent=1), encoding="utf-8")
    return len(kept), collections.Counter(d["_liveness"] for d in dropped)


def cmd_split(a) -> int:
    objects = load_map()
    k, d = split_pack(objects, Path(a.pack), Path(a.out))
    print(f"{Path(a.pack).name}: kept {k}, dropped {dict(d)} -> {a.out}")
    return 0


def cmd_split_all(a) -> int:
    objects = load_map()
    tk = 0
    td = collections.Counter()
    for pack in sorted(TUNINGS.glob("*.json")):
        k, d = split_pack(objects, pack, Path(a.out))
        tk += k
        td.update(d)
        print(f"  {pack.name:28} kept {k:>3}   dropped {sum(d.values()):>3}  {dict(d) if d else ''}")
    print(f"\nTOTAL kept {tk}, dropped {sum(td.values())} {dict(td)}  ->  {a.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check"); p.add_argument("pack")
    p = sub.add_parser("split"); p.add_argument("pack"); p.add_argument("--out", default=str(OUT))
    p = sub.add_parser("split-all"); p.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    return {"check": cmd_check, "split": cmd_split, "split-all": cmd_split_all}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
