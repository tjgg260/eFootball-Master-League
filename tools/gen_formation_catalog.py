#!/usr/bin/env python3
r"""
gen_formation_catalog.py — the app's built-in formation catalogue, taken from eFootball's own shapes.

WHY THIS EXISTS. The Tactics screen offered whatever distinct shapes happened to sit in the world's
formation_slots table. In a world built from the player's install that was four, because
game_world.py read no formations at all — dt200 carries them (Tactics.bin, TacticsFormation.bin)
and nothing ever looked — so every career club fell back to career_seed's four rotating shapes and
a Premier League side could pick from 4-4-2, 4-2-3-1, 4-1-2-3 and 3-1-4-2 and nothing else.
game_world.py now loads the real tables, but the catalogue still earns its place twice over: it
NAMES the shapes (the depth clustering reads a back five as "3-2-1-2-2"), and it gives the picker a
full list in a world built before that fix, without asking anyone to rebuild a world that holds
their careers.

WHERE THE GEOMETRY COMES FROM. Not invented: the 1,584 real eFootball team formations in the
curated world (build/master.db, loaded by tools/tactics_load.py from a dt200 that still carried
Tactics.bin). For each shape we take the MODAL layout — the exact 11 slots the largest number of
real clubs use — so every template here is a shape Konami actually ships.

NAMING. Formations.ShapeOf clusters slots by depth, which over-splits a staggered line
(3-2-2-2-1 is a 3-4-2-1 whose wide midfielders sit four units deeper than the central pair).
CANON below maps each derived shape onto the name football uses for it, one template per name,
most-used geometry wins.

    python tools/gen_formation_catalog.py            # rewrite both outputs from build/master.db
    python tools/gen_formation_catalog.py --dry      # print what it would write

Outputs (both committed, so the release needs neither master.db nor a Python step):
    tools/data/formations.json        career_seed.py reads it for CPU-club variety
    src/ML.App/FormationCatalog.cs    the app's Set Formation list — generated, do not hand-edit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "build" / "master.db"
JSON_OUT = REPO / "tools" / "data" / "formations.json"
CS_OUT = REPO / "src" / "ML.App" / "FormationCatalog.cs"

# Career-band formation ids are a seeded career's own copies, not the game's.
CAREER_BASE = 900_000

ROLE = {0: "GK", 1: "CB", 2: "LB", 3: "RB", 4: "DMF", 5: "CMF", 6: "LMF",
        7: "RMF", 8: "AMF", 9: "LWF", 10: "RWF", 11: "SS", 12: "CF"}

# derived shape (Formations.ShapeOf) -> the name the formation is actually known by.
# A name appears once: the first (most-used) derived shape that maps to it wins, later ones are
# near-duplicates of the same shape with one line nudged a unit or two.
CANON = {
    "4-2-3-1":     "4-2-3-1",
    "3-2-2-2-1":   "3-4-2-1",
    "4-4-2":       "4-4-2",
    "4-2-1-2-1":   "4-2-1-3",
    "4-1-2-2-1":   "4-3-3",
    "3-2-1-2-2":   "5-3-2",
    "3-2-2-1-2":   "3-4-1-2",
    "4-3-2-1":     "4-3-2-1",
    "4-1-4-1":     "4-1-4-1",
    "3-3-2-2":     "3-5-2",
    "4-2-2-2":     "4-2-2-2",
    "3-1-4-2":     "3-1-4-2",
    "4-1-2-1-2":   "4-1-2-1-2",
    "4-4-1-1":     "4-4-1-1",
    "4-3-1-2":     "4-3-1-2",
    "3-2-3-1-1":   "5-3-1-1",
    "3-2-4-1":     "5-4-1",
    "3-3-2-1-1":   "3-5-1-1",
    "4-2-2-1-1":   "4-2-2-1-1",
    "3-1-2-1-2-1": "3-4-3",
}


def shape_of(ys: list[int]) -> str:
    """ML.App.Formations.ShapeOf, in Python — the same clustering, so CANON's keys are its keys."""
    outfield = sorted(y for y in ys if y >= 9)
    if not outfield:
        return "-"
    lines, count, prev = [], 0, None
    for y in outfield:
        if prev is not None and y - prev > 3:
            lines.append(count)
            count = 0
        count += 1
        prev = y
    lines.append(count)
    return "-".join(str(n) for n in lines)


def sort_key(name: str) -> tuple:
    """Back three first, then four, then five; within a line, fewest parts first."""
    parts = [int(p) for p in name.split("-")]
    return (parts[0], len(parts), parts)


def collect(db: Path) -> list[dict]:
    # as_uri(), not an f-string: the world lives under "eFootball Master League" and SQLite needs
    # those spaces percent-encoded to see the path at all. Read-only — this tool never writes a DB.
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    rows = con.execute(
        "SELECT formation_id, slot_index, position, x, y FROM formation_slots "
        "WHERE formation_id < ? ORDER BY formation_id, slot_index", (CAREER_BASE,)).fetchall()
    con.close()

    by_fid: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)
    for fid, si, pos, x, y in rows:
        by_fid[fid].append((si, pos, x, y))

    # derived shape -> exact 11-slot layout -> how many real clubs field it
    geometries: dict[str, Counter] = defaultdict(Counter)
    for fid, slots in by_fid.items():
        if len(slots) != 11:
            continue
        geometries[shape_of([y for _, _, _, y in slots])][tuple(slots)] += 1

    out, seen = [], set()
    for derived, canon in CANON.items():
        if canon in seen:
            continue
        if derived not in geometries:
            print(f"  WARNING: {derived} ({canon}) is not in this database — skipped")
            continue
        layout, n = geometries[derived].most_common(1)[0]
        total = sum(geometries[derived].values())
        seen.add(canon)
        out.append({
            "name": canon,
            "derived": derived,
            "clubs": total,
            "modal": n,
            "slots": [{"slot": si, "role": pos, "role_name": ROLE.get(pos, str(pos)), "x": x, "y": y}
                      for si, pos, x, y in layout],
        })
    out.sort(key=lambda f: sort_key(f["name"]))
    return out


def write_json(formations: list[dict], dry: bool) -> None:
    doc = {
        "_generated_by": "tools/gen_formation_catalog.py",
        "_source": "modal geometry of the real eFootball team formations in build/master.db",
        "_coords": "x 12-92 across the pitch (52 = centre), y 3-43 from own goal; slot 0 is the GK",
        "formations": formations,
    }
    text = json.dumps(doc, indent=2) + "\n"
    print(f"{'would write' if dry else 'wrote'} {JSON_OUT} ({len(formations)} formations)")
    if not dry:
        JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(text, encoding="utf-8")


def write_cs(formations: list[dict], dry: bool) -> None:
    lines = [
        "// <auto-generated>",
        "//   tools/gen_formation_catalog.py wrote this from the modal geometry of the real",
        "//   eFootball team formations in build/master.db. Do not hand-edit: re-run the tool.",
        "// </auto-generated>",
        "using System.Collections.Generic;",
        "",
        "namespace ML.App;",
        "",
        "/// <summary>",
        "/// The formations the Tactics screen offers, independent of what this world's",
        "/// formation_slots happens to hold — and the name for each shape the geometry reads as.",
        "///",
        "/// A world built from the player's own install used to carry no formation geometry at all:",
        "/// dt200 has it, game_world.py just never read it, so the Set Formation list was whatever",
        "/// four shapes career_seed rotated through. game_world.py reads the real tables now; this",
        "/// catalogue still names them, and still fills the list in a world built before that fix.",
        "/// </summary>",
        "public static class FormationCatalog",
        "{",
        "    /// <summary>One slot of a template: the game's role code, and its place on the pitch",
        "    /// in formation_slots coordinates (x 12-92 across, y 3-43 up).</summary>",
        "    public readonly record struct Slot(int Role, int X, int Y);",
        "",
        "    /// <summary>A named shape and its eleven slots, in slot_index order (0 is the GK).</summary>",
        "    public sealed record Template(string Name, IReadOnlyList<Slot> Slots);",
        "",
        "    /// <summary>Every template, back three first, then four, then five.</summary>",
        "    public static IReadOnlyList<Template> All { get; } = new Template[]",
        "    {",
    ]
    tail = [
        "    };",
        "",
        "    // Formations.ShapeOf clusters slots by depth, which over-splits a staggered line: a",
        "    // 3-4-2-1 whose wide midfielders sit four units behind the central pair reads as",
        "    // \"3-2-2-2-1\". This is the name each of those readings belongs to, so the shape the",
        "    // screen prints matches the template the list offered.",
        "    private static readonly Dictionary<string, string> Names = new()",
        "    {",
    ]
    for f in formations:
        tail.append(f'        ["{f["derived"]}"] = "{f["name"]}",')
    tail += [
        "    };",
        "",
        "    /// <summary>The formation name for a derived line reading, or null if nothing names it.</summary>",
        "    public static string? NameFor(string derived) =>",
        "        Names.TryGetValue(derived, out var name) ? name : null;",
        "",
        "    /// <summary>True when this is one of the catalogue's own formation names.</summary>",
        "    public static bool IsNamed(string name) => Names.ContainsValue(name);",
        "}",
        "",
    ]
    for f in formations:
        roles = " ".join(s["role_name"] for s in f["slots"][1:])
        lines.append(f'        // {f["name"]}: {roles}   ({f["clubs"]} real clubs)')
        lines.append(f'        new("{f["name"]}", new Slot[]')
        lines.append("        {")
        for s in f["slots"]:
            lines.append(f'            new({s["role"]}, {s["x"]}, {s["y"]}),   // {s["role_name"]}')
        lines.append("        }),")
    text = "\n".join(lines + tail)
    print(f"{'would write' if dry else 'wrote'} {CS_OUT} ({len(text):,} chars)")
    if not dry:
        CS_OUT.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DB), help="a world carrying the game's own formations")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    formations = collect(Path(args.db))
    if not formations:
        raise SystemExit(f"{args.db}: no real formation geometry below id {CAREER_BASE:,} — "
                         "this database has never had tactics_load.py run against it")
    for f in formations:
        print(f"  {f['name']:<10} from {f['derived']:<12} {f['clubs']:>5} clubs "
              f"({f['modal']} share the exact layout)")
    write_json(formations, args.dry)
    write_cs(formations, args.dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
