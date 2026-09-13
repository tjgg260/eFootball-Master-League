#!/usr/bin/env python3
"""
rating_weights.py — retune eFootball's match-rating formula, by name.

The rating formula is NOT compiled into the exe: dt270 `constant_match.bin -> rating.o` carries
four formula STRINGS (df_rate / mf_rate / fw_rate / gk_rate) which the game COMPILES at match
init (compiler 0x1442a45d0 -> 0x1456cd0b0) and evaluates per player (0x1442a0f90 -> 0x1456cc690).
The evaluated result is the raw score that the rating scorer (0x14429ea40) normalises into the
0-10 rating. So editing these strings retunes ratings for real — no exe patch, and it survives
Konami patches.

    python tools/rating_weights.py show                       # every stat's weight per position
    python tools/rating_weights.py show --pos fw
    python tools/rating_weights.py set fw.Goal=100 df.TackleSuccess=12 --apply
    python tools/rating_weights.py set all.Foul=-3 --apply     # fouls currently count ZERO
    python tools/rating_weights.py restore                     # stock formulas back

Positions: df, mf, fw, gk, or `all`. Stat names are the game's own accessor names with the
`StatsPlayer` / `StatsTeam` / `UnqStatsPlayer` prefix optional (Goal, Assist, PassShortSuccess,
CardYellow, TeamWin, ...). Only names already present in the shipped formulas are accepted —
an unknown name would fail to compile and the evaluator returns 0.0, flat-lining every rating.

Space: each string may only be replaced by one of the SAME OR SHORTER length (the pack is patched
in place). The shipped strings are generously spaced, so `write` minifies (single spaces) first,
which frees ~170 bytes per formula — enough to change weights and add terms.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

POSITIONS = ("df", "mf", "fw", "gk")
FIELD = {p: f"{p}_rate" for p in POSITIONS}
TERM_RE = re.compile(r"([+-]?)\s*([\d.]+)\s*\*\s*(\([^()]*(?:\([^()]*\)[^()]*)*\)|\w+\(\))")


def load_object():
    from dt270_objects import load_game_packs
    packs = load_game_packs()
    return packs, packs["constant_match.bin"][1].object("rating")


def parse(formula: str):
    """-> [(weight_float, expr_str)] in source order."""
    out = []
    for m in TERM_RE.finditer(re.sub(r"\s+", " ", formula)):
        sign, w, expr = m.group(1) or "+", float(m.group(2)), re.sub(r"\s+", "", m.group(3))
        out.append(((-w if sign == "-" else w), expr))
    return out


def stat_key(expr: str) -> str:
    """'StatsPlayerGoal()' -> 'Goal'; a compound '(A()-B())' -> 'A-B' (shortened)."""
    names = re.findall(r"(\w+)\(\)", expr)
    short = [n.replace("UnqStatsPlayer", "Unq").replace("StatsPlayer", "").replace("StatsTeam", "Team") for n in names]
    return "-".join(short)


def render(terms) -> str:
    """Minified formula text: '80*StatsPlayerGoal()-60*StatsPlayerOwnGoal()...'."""
    parts = []
    for i, (w, expr) in enumerate(terms):
        num = f"{w:g}"
        if i == 0:
            parts.append(f"{num}*{expr}" if w >= 0 else f"-{abs(w):g}*{expr}")
        else:
            parts.append(("+" if w >= 0 else "-") + f"{abs(w):g}*{expr}")
    return "".join(parts)


def read_all(obj):
    return {p: parse(obj.get(FIELD[p])) for p in POSITIONS}


def cmd_show(a):
    _packs, obj = load_object()
    forms = read_all(obj)
    cols = [a.pos] if a.pos else list(POSITIONS)
    keys, seen = [], set()
    for p in cols:
        for _w, e in forms[p]:
            k = stat_key(e)
            if k not in seen:
                seen.add(k); keys.append(k)
    keys.sort(key=lambda k: -max(abs(w) for p in cols for w, e in forms[p] if stat_key(e) == k))
    print(f"{'STAT':34}" + "".join(f"{p.upper():>9}" for p in cols))
    print("-" * (34 + 9 * len(cols)))
    for k in keys:
        row = ""
        for p in cols:
            v = [w for w, e in forms[p] if stat_key(e) == k]
            row += f"{v[0]:>+9g}" if v else f"{'·':>9}"
        print(f"{k[:34]:34}{row}")
    print()
    for p in cols:
        cur = obj.get(FIELD[p])
        print(f"  {p}_rate: {len(cur)} bytes used of {len(cur)} capacity; "
              f"{len(cur) - len(render(forms[p]))} free after minify")
    return 0


def apply_edits(obj, edits):
    """edits: [(pos|'all', statkey, newweight)] -> {pos: new_formula_text}"""
    forms = read_all(obj)
    valid = {stat_key(e) for p in POSITIONS for _w, e in forms[p]}
    out, changed = {}, []
    for pos, key, val in edits:
        if key not in valid:
            sys.exit(f"unknown stat {key!r}. Known: {', '.join(sorted(valid))}")
        targets = POSITIONS if pos == "all" else (pos,)
        for p in targets:
            hit = [i for i, (_w, e) in enumerate(forms[p]) if stat_key(e) == key]
            if not hit:
                print(f"  note: {p} has no {key} term — skipped (add it manually if wanted)")
                continue
            old = forms[p][hit[0]][0]
            forms[p][hit[0]] = (val, forms[p][hit[0]][1])
            changed.append(f"  {p}.{key}: {old:+g} -> {val:+g}")
    for p in POSITIONS:
        txt = render(forms[p])
        cap = len(obj.get(FIELD[p]))
        if len(txt) > cap:
            sys.exit(f"{p}_rate too long: {len(txt)} > {cap} capacity")
        out[p] = txt
    return out, changed


def cmd_set(a):
    edits = []
    for item in a.items:
        if "=" not in item or "." not in item.split("=")[0]:
            sys.exit(f"expected pos.Stat=value, got {item!r}")
        lhs, rhs = item.split("=", 1)
        pos, key = lhs.split(".", 1)
        if pos not in POSITIONS and pos != "all":
            sys.exit(f"position must be one of {POSITIONS} or 'all', got {pos!r}")
        edits.append((pos, key, float(rhs)))
    _packs, obj = load_object()
    new, changed = apply_edits(obj, edits)
    print("\n".join(changed) if changed else "  nothing matched")
    for p in POSITIONS:
        print(f"  {p}_rate -> {len(new[p])}/{len(obj.get(FIELD[p]))} bytes")
    if not a.apply:
        print("\n(dry run — pass --apply to install)")
        return 0
    import gameplay_tune as gt
    from dt270_objects import _parse_path
    cmd = [f"{FIELD[p]}={new[p]}" for p in POSITIONS]
    print("\ninstalling…")
    pristine = gt.ensure_pristine_backup()
    gt._guard()
    _schema, packs = gt._schema_packs(gt.game_dt270())     # stack on the current pack
    fname, _blob, pack = gt._find(packs, "rating")
    view = pack.object("rating")
    for p in POSITIONS:
        view.write_leaf(view.leaf(_parse_path(FIELD[p])), new[p])
    gt._patch_and_install(gt.game_dt270(), packs, {fname}, f"rating formula: {len(changed)} weight change(s)")
    return 0


def cmd_restore(_a):
    """Put the four formula strings back to the pristine pack's text (leaves other edits alone)."""
    import gameplay_tune as gt
    from dt270_objects import _parse_path, Pack, Schema
    from dt270_constants import decode_constant
    pristine = gt.BACKUPS / "dt270_console_all.PRISTINE.cpk"
    if not pristine.exists():
        sys.exit("no pristine dt270 backup")
    import cpk_patch
    blob = cpk_patch.read(cpk_patch.load(pristine), "constant_match.bin")
    stock = None if blob is None else Pack(decode_constant(blob), Schema.load()).object("rating")
    _schema, packs = gt._schema_packs(gt.game_dt270())
    fname, _blob, pack = gt._find(packs, "rating")
    view = pack.object("rating")
    for p in POSITIONS:
        view.write_leaf(view.leaf(_parse_path(FIELD[p])), stock.get(FIELD[p]))
    gt._patch_and_install(gt.game_dt270(), packs, {fname}, "rating formulas restored to stock")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show"); p.add_argument("--pos", choices=POSITIONS)
    p = sub.add_parser("set"); p.add_argument("items", nargs="+"); p.add_argument("--apply", action="store_true")
    sub.add_parser("restore")
    a = ap.parse_args()
    return {"show": cmd_show, "set": cmd_set, "restore": cmd_restore}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
