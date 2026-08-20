"""Sweep every IoStore pak chunk for gameplay-relevant assets (read-only, key required).

Reuses iostore_read to decrypt each pc*.utoc directory index and collect the FULL asset path
list, then buckets paths by keyword so we can see whether AI/tactics/rating/evaluation data
ships as UE DataTables (moddable) or isn't present as data at all (=> it's engine C++).

Usage:
  python tools/iostore_sweep.py <aes_key_hex> [--pakdir DIR] [--out FILE]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from iostore_read import read_utoc

DEFAULT_PAKDIR = r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\pak"

# Buckets that matter for the "AI plays the same / where are ratings" question, plus the
# asset kinds worth knowing about. Order matters: first match wins.
BUCKETS = [
    ("ai/behaviour", ("/ai/", "_ai", "behavior", "behaviour", "brain", "decision")),
    ("tactics/strategy", ("tactic", "strategy", "formation", "mentality", "gameplan",
                          "instruction", "playstyle")),
    ("rating/evaluation", ("rating", "evaluat", "score_", "grade", "performance", "matchrate")),
    ("match/rules", ("/match/", "matchrule", "referee", "foul", "offside")),
    ("stats/params", ("stat", "param", "constant", "balance", "tuning", "curve")),
    ("datatable(other)", ("dt_", "/data/", "datatable")),
    ("player/face", ("face", "head", "hair", "/player/", "portrait", "appearance")),
    ("team/kit", ("kit", "uniform", "/team/", "emblem", "badge")),
    ("stadium", ("stadium", "pitch", "turf", "crowd")),
    ("anim", ("/anim", "montage", "_abp", "skel")),
    ("audio", ("atom", "criware", "/sound", "commentary", "/audio")),
    ("ui/text", ("/ui/", "widget", "wbp_", "stringtable", "/string")),
]


def bucket_of(path: str) -> str:
    lp = path.lower()
    for name, keys in BUCKETS:
        if any(k in lp for k in keys):
            return name
    return "other"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    key_hex = sys.argv[1].removeprefix("0x")
    pakdir = Path(sys.argv[sys.argv.index("--pakdir") + 1]) if "--pakdir" in sys.argv \
        else Path(DEFAULT_PAKDIR)
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else Path("build/iostore_assets.txt")
    key = bytes.fromhex(key_hex)
    if len(key) != 32:
        print("AES-256 needs a 32-byte (64 hex) key")
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    tocs = sorted(pakdir.glob("*.utoc"))
    totals: dict[str, int] = defaultdict(int)
    interesting: dict[str, list[str]] = defaultdict(list)
    grand = 0
    with open(out, "w", encoding="utf-8") as fh:
        for toc in tocs:
            try:
                mount, ec, dc, fc, sc, paths = read_utoc(str(toc), key, limit=10 ** 9)
            except Exception as ex:
                print(f"{toc.name}: ERROR {ex}")
                continue
            grand += len(paths)
            per = defaultdict(int)
            for p in paths:
                b = bucket_of(p)
                per[b] += 1
                totals[b] += 1
                if b in ("ai/behaviour", "tactics/strategy", "rating/evaluation",
                         "match/rules", "stats/params", "datatable(other)"):
                    interesting[b].append(p)
                fh.write(p + "\n")
            top = ", ".join(f"{k}:{v}" for k, v in sorted(per.items(), key=lambda x: -x[1])[:4])
            print(f"{toc.name:34} {len(paths):>6} files | {top}")

    print(f"\n=== {grand:,} assets across {len(tocs)} chunks — bucket totals ===")
    for k, v in sorted(totals.items(), key=lambda x: -x[1]):
        print(f"  {k:22} {v:>7}")

    print("\n=== GAMEPLAY-DATA CANDIDATES (the ones that decide the AI/rating question) ===")
    for b in ("ai/behaviour", "tactics/strategy", "rating/evaluation", "match/rules",
              "stats/params", "datatable(other)"):
        rows = interesting.get(b, [])
        print(f"\n--- {b}: {len(rows)} ---")
        for p in rows[:40]:
            print("  " + p)
        if len(rows) > 40:
            print(f"  … +{len(rows) - 40} more (full list in {out})")
    print(f"\nfull asset list written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
