#!/usr/bin/env python3
"""
gameplay_catalog.py — one place to see everything you can mod, gameplay-wise.

Merges four sources into a single catalogue:
  * dt270 constant fields (name, type, CURRENT value) from tools/data/dt270_schema.json + the
    installed CPK — the safe, name-based, data-file mods (tools/gameplay_tune.py).
  * which of those fields the exe analysis proved actually DO something (live / likely / inert),
    so you don't waste an evening on a dead lever.
  * eFootball.exe hex/runtime levers (kick-error model, difficulty tables, …) from the mapped
    findings, each with address, current value, effect and risk.
  * the ready-made patch packs in tools/data/patches/ and whether each is applied right now.

    python tools/gameplay_catalog.py build      # -> build/gameplay_catalog.json
    python tools/gameplay_catalog.py html       # -> build/gameplay-catalog.html (self-contained)
    python tools/gameplay_catalog.py search curl # grep names/effects across both surfaces

Re-run after a Konami patch (dt270_schema_gen.py + exe_map.py first) to refresh values/addresses.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
CATALOG = REPO / "build" / "gameplay_catalog.json"
HTML = REPO / "build" / "gameplay-catalog.html"

# Gameplay-relevant dt270 objects (skip stadium/demo/tutorial/sugoroku/pathToGlory scenery).
GAMEPLAY_OBJECTS = {
    "ball": ("constant_match.bin", "Ball physics — drag, Magnus curl, bounce, spin decay, roll friction"),
    "shoot": ("constant_player.bin", "Shot power/height — launch-speed gauges (km/h) and elevation curves"),
    "trap": ("constant_player.bin", "First touch — control quality, reaction traps, loose-ball behaviour"),
    "grounderpass": ("constant_player.bin", "Ground pass — speed, receive, lob, assist blend"),
    "flypass": ("constant_player.bin", "Lofted pass — trajectory height, assist blend"),
    "throughpass": ("constant_player.bin", "Through ball — run timing, target search, speed"),
    "centering": ("constant_player.bin", "Crossing — curve, speed, search"),
    "passget": ("constant_player.bin", "Receiving & interception — auto-move, defender reaction"),
    "moveMatching": ("constant_player.bin", "Locomotion — acceleration, deceleration, turn speed per route"),
    "basePosition": ("constant_team.bin", "Team-shape AI — defensive line, compactness, width, pressing, marking"),
    "rating": ("constant_match.bin", "Match rating formula — per-action weights, bonuses, position rates"),
    "ballplayer": ("constant_player.bin", "Player locomotion tables — turn/touch motion matching (bulk data)"),
    "cameraInplay": ("constant_match.bin", "In-play camera rig"),
}

# What the exe consumer analysis proved (docs/exe-gameplay-map.md). Prefix match on dotted path.
# status: live = a consumer reads it and moves in the expected direction; likely = strong evidence,
#         one link unconfirmed; inert = no reader found in this build (changing it does nothing).
DT270_VERDICTS = [
    ("trap", "ballControlRate", "live", "Multiplies normalised Ball Control into the trap's controllable-speed / error-angle model (0x144079a70). Lower = worse first touch for everyone."),
    ("trap", "ballControlWeekFootDownLimit", "live", "Weak-foot deduction from Ball Control (0x144079020)."),
    ("shoot", "normal_dy", "live", "Launch elevation curve; gageMax is the full-power vertical angle (0x143fdf0c0)."),
    ("shoot", "control_dy", "live", "Launch elevation curve for controlled shots (0x143fdf0c0)."),
    ("shoot", "normalShootGage", "live", "Shot launch speed km/h, interpolated by attribute and 5 m distance band (0x143eeed40)."),
    ("shoot", "controlShootGage", "live", "Controlled-shot launch speed km/h (0x143eeed40)."),
    ("shoot", "powerfullShootGage", "live", "Powerful-shot launch speed km/h (0x143eeed40)."),
    ("ball", "magnusRate", "live", "Magnus (curl/dip) acceleration coefficient (0x144089620)."),
    ("ball", "airRegistNormal", "live", "Air drag multiplier (0x144089620)."),
    ("ball", "nonSpinRate", "live", "Knuckle/no-spin wobble coefficient (0x144089620)."),
    ("ball", "boundRate", "live", "Restitution per pitch condition — bounce liveliness (0x14408d0f0)."),
    ("ball", "dragSpeedMin", "live", "Drag-crisis speed window (0x144089620)."),
    ("ball", "dragSpeedMax", "live", "Drag-crisis speed window (0x144089620)."),
    ("basePosition", "spaceCoverRate", "likely", "Space-cover weighting in the team-shape model ([ctx+0xf0]+0x318, 0x143e85de0); the cache pointer is unconfirmed."),
    ("basePosition", "adjustSpaceCoverRate", "likely", "Companion to spaceCoverRate."),
    ("basePosition", "forceDashDistOffence", "live", "Distance from base position that forces a dash, attacking (0x143da92c0)."),
    ("basePosition", "forceDashDistDefence", "inert", "Dead load in 0x143da92c0 — the defence branch uses 19-0.1*attr instead. Changing it does nothing."),
    ("basePosition", "pressRate", "inert", "No reader found anywhere in this build."),
    ("passget", "defence", "inert", "passget.defence.paraMin/paraMax/secMin/secMax have no consumer in this build."),
]

FEATURED_SYSTEMS = [
    {
        "system": "Kick error model",
        "blurb": "How every pass and shot deviates from its intended direction and power. There is no such field in dt270 — the whole model is in the exe. Builder 0x14401a900 sets per-axis max error, then one of three randomisers applies it; a per-player ability factor (0x143ed71d0) suppresses it.",
        "levers": [
            {"name": "Horizontal shank magnitude", "va": "0x14401b3df", "current": "22.5°", "knob": "angle error = (1−ability)·22.5°", "effect": "Bigger = wider left/right misses on passes and shots.", "pack": "slices-scuffs (C)", "confidence": "proven"},
            {"name": "Elevation / slice error", "va": "0x14401b423", "current": "22.5°", "knob": "vertical angle error = (1−ability)·22.5°", "effect": "Bigger = more ballooned or scuffed-along-the-ground kicks.", "pack": "slices-scuffs (F)", "confidence": "proven"},
            {"name": "Scuffed-power error", "va": "0x14401b3d6", "current": "0.3 (30%)", "knob": "speed error fraction", "effect": "Bigger = more under- and over-hit power.", "pack": "slices-scuffs (B)", "confidence": "proven"},
            {"name": "Error spread (Gaussian σ)", "va": "0x14401b3a7", "current": "4.25", "knob": "σ = 0.75 + k·(1−ability)²", "effect": "Bigger = error lands near the max more often, fewer clean kicks.", "pack": "slices-scuffs (E)", "confidence": "proven"},
            {"name": "Slice floor (types 1/3)", "va": "0x144019ec3", "current": "8°", "knob": "minimum shank for awkward / behind-body kicks", "effect": "Bigger = even elite players shank awkward kicks.", "pack": "slices-scuffs (D)", "confidence": "proven"},
            {"name": "Mis-kick frequency — shank types", "va": "0x14401b7d8", "current": "×1.0", "knob": "roll scale for awkward-angle & behind-body misses", "effect": "Higher = those mis-kicks fire more often.", "pack": "slices-scuffs (A)", "confidence": "proven"},
            {"name": "Mis-kick frequency — over-hit/closed-down", "va": "0x144019a50", "current": "×1.0", "knob": "roll scale for over-hit & closed-down misses", "effect": "Higher = those mis-kicks fire more often. (Separate gate from the shank types.)", "pack": "slices-scuffs (A2)", "confidence": "proven"},
            {"name": "Slice shape", "va": "0x144019eae", "current": "cos(90°+x)", "knob": "deviation curve for awkward/behind-body kicks", "effect": "Shift to cos(135°+x) = those kicks are always visible shanks, never mild.", "pack": "aggressive (H)", "confidence": "proven"},
            {"name": "Over-hit thresholds (category 0)", "va": "0x14401e846", "current": "65 / 75 km/h", "knob": "speed at which ordinary ground kicks are 'too hard'", "effect": "Lower = ordinary hard kicks over-hit sooner.", "pack": "aggressive (I)", "confidence": "likely"},
            {"name": "Assisted-pass error exemption", "va": "0x14401a175", "current": "on (je)", "knob": "locked-on assisted passes are spared kick error", "effect": "Force the je to jmp so even assisted passes take the error path — makes mishit passes near-universal.", "pack": "max (K)", "confidence": "proven"},
            {"name": "Ability curve — slope", "va": "0x143ed72ba", "current": "0.8/30", "knob": "60–90 rating → accuracy factor slope", "effect": "Flatter = mid players kick like worse players.", "pack": "slices-scuffs (G1)", "confidence": "proven"},
            {"name": "Ability curve — top base", "va": "0x143ed72f2", "current": "0.9", "knob": "90+ rating accuracy floor", "effect": "Lower = elite players lose their near-perfect accuracy.", "pack": "slices-scuffs (G2)", "confidence": "proven"},
        ],
    },
    {
        "system": "Mishit spin (slices / shanks / scuffs)",
        "blurb": "A mishit changes direction and power, but its spin AXIS just follows the (wrong) travel direction — so a shank curls like a clean kick, not a slice. Spin is built in 0x144018c10 after the kick; the only sideways-lean coupling (spin axis vs player facing) is clamped at 45 deg. Unclamping it makes sidespin scale with the size of the horizontal miss. Pairs with dt270 ball.magnusRate (the amplifier).",
        "levers": [
            {"name": "Sidespin lean cap (the slice lever)", "va": "0x144018df0", "current": "45°", "knob": "clamp(travel − facing) before building the spin axis", "effect": "Raise to 90° so a shanked/sliced kick's sidespin grows with the horizontal miss — mishits curl away like real slices. 180° = near-unclamped (over-curls wide passes).", "pack": "mishit-spin (P1)", "confidence": "proven"},
            {"name": "Assisted-kick spin scale", "va": "0x14401914c", "current": "50", "knob": "spin magnitude scale on the assisted branch (manual = 80)", "effect": "Raise to 80 so assisted passes/shots build the same spin as manual — their mishits curl too instead of drifting flat.", "pack": "mishit-spin (P2b)", "confidence": "likely"},
            {"name": "Spin-magnitude cap", "va": "0x144019177", "current": "0.9", "knob": "min-cap on built spin magnitude", "effect": "Raise to 1.0 for a mild overall curl/dip increase on all kicks.", "pack": "mishit-spin (P2)", "confidence": "likely"},
            {"name": "Magnus curl amplifier", "va": "ball.magnusRate (dt270)", "current": "0.07 (stock 0.035)", "knob": "Magnus acceleration coefficient", "effect": "Amplifies whatever spin the ball has — scales all curl including the now-sideways-leaning mishit spin. gameplay_tune set ball magnusRate=...", "pack": "loose-realism / dt270", "confidence": "proven"},
        ],
    },
    {
        "system": "CPU difficulty",
        "blurb": "Not in dt270 — a hard-coded 44×10 float table in the exe (0x146c06f40), one column per level BEGINNER…SUPERSTAR plus a hidden LEGEND and half-steps, read via GetParam 0x1442e48f0. Row 0 is reaction-delay frames.",
        "levers": [
            {"name": "SUPERSTAR reaction delay", "va": "0x146c06f5c", "current": "4 frames", "knob": "row 0, SUPERSTAR column", "effect": "Raise toward the PROFESSIONAL value (16) to blunt the CPU's instant reactions.", "pack": "superstar-reaction-professional", "confidence": "proven"},
            {"name": "Whole level table", "va": "0x146c06f40", "current": "44 rows × 10 cols", "knob": "every per-level gameplay parameter", "effect": "Copy any column into another to make one level behave like a different one; a hidden LEGEND column exists.", "pack": "(manual)", "confidence": "proven"},
            {"name": "Runtime CPU level", "va": "TmpDb+0x94/+0x9c", "current": "as set in menu", "knob": "match level value (XOR-obfuscated)", "effect": "Force LEGEND (6) + strongest sub-column before kickoff.", "pack": "(runtime, live_patch)", "confidence": "proven"},
        ],
    },
    {
        "system": "Where CPU decisions live",
        "blurb": "The CPU's choice of whether to shoot/pass/press is match::ai::ActionSelector* / Judge / PlayerOffence — not yet traced to specific thresholds. match::pad::ThinkUnit* are the HUMAN controller interpreters (gauge fill rates, dead-zones), not CPU AI.",
        "levers": [
            {"name": "ActionSelectorScore::vf2", "va": "0x143df1080", "current": "—", "knob": "CPU shooting/scoring decision (410 instructions)", "effect": "Next reverse-engineering target; thresholds not yet mapped.", "pack": "(research)", "confidence": "guess"},
            {"name": "Human shot gauge fill rate", "va": "0x1440d8070", "current": "0.25 s shoot / 0.3 s pass", "knob": "time to full power gauge", "effect": "Faster/slower power build-up for the human player only.", "pack": "(manual)", "confidence": "proven"},
        ],
    },
]


AREA_TITLES = {
    "cpu-attacking-decisions": "CPU attacking decisions",
    "cpu-defending": "CPU defending & team shape",
    "goalkeeper": "Goalkeeper",
    "shooting-behaviour": "Shooting behaviour",
    "passing-behaviour": "Passing behaviour & target selection",
    "dribbling-skills": "Dribbling, feints & skills",
    "physical-locomotion": "Physical & locomotion",
    "stamina-condition": "Stamina, fatigue & condition",
    "defending-tackle-foul": "Tackling, fouls & referee",
    "set-pieces": "Set pieces",
    "ball-physics-exe": "Ball physics (exe collision/deflection)",
    "rng-and-globals": "Match RNG & global tunables",
    "difficulty-rows": "CPU difficulty table (44 rows)",
    "attribute-model": "Attribute model",
}
# Map areas already covered by the featured curated systems (skip to avoid duplication).
FEATURED_AREAS = {"difficulty-rows"}   # difficulty featured entry stays; map version folded below with full rows

def exe_systems():
    import json as _j
    full = REPO / "build" / "exe_full_map.json"
    systems = list(FEATURED_SYSTEMS)
    if not full.exists():
        return systems
    m = _j.loads(full.read_text(encoding="utf-8"))
    for area, r in m.get("sweeps", {}).items():
        levers = []
        for l in r.get("levers", []):
            eff = l.get("effect", "")
            if l.get("patch_idea"):
                eff = eff + "  ·  patch: " + l["patch_idea"]
            levers.append(dict(name=l.get("name", "?"), va=l.get("va", "—"),
                               current=l.get("current", "—"), knob=l.get("reads", ""),
                               effect=eff, pack="(hex/runtime)", confidence=l.get("confidence", "guess")))
        systems.append(dict(system=AREA_TITLES.get(area, area), blurb=r.get("summary", ""), levers=levers))
    return systems

MAX_ARRAY_ROWS = 6   # arrays longer than this are shown as one summary row


def verdict_for(obj, path):
    best = None
    for o, prefix, status, note in DT270_VERDICTS:
        if o == obj and (path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[")):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, status, note)
    return (best[1], best[2]) if best else ("unverified", "")


def flatten(obj_name, tree_value, fields):
    """Walk a to_dict() value into catalogue rows, collapsing long arrays."""
    def walk(val, path):
        if isinstance(val, dict):
            for k, v in val.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(val, list):
            scalars = [v for v in val if not isinstance(v, (dict, list))]
            if val and len(scalars) == len(val) and len(val) <= MAX_ARRAY_ROWS:
                status, note = verdict_for(obj_name, path)
                fields.append(dict(path=path, type="float[]" if any(isinstance(v, float) for v in val) else "int[]",
                                   value=val, status=status, note=note))
            elif val and len(scalars) == len(val):
                status, note = verdict_for(obj_name, path)
                fields.append(dict(path=f"{path}[{len(val)}]", type=("float[]" if any(isinstance(v, float) for v in val) else "int[]"),
                                   value=val[:3] + ["…"], status=status, note=(note or f"{len(val)}-element array")))
            else:
                shown = min(len(val), 2)
                for i in range(shown):
                    walk(val[i], f"{path}[{i}]")
                if len(val) > shown:
                    fields.append(dict(path=f"{path}[{shown}…{len(val) - 1}]", type="record[]", value=None,
                                       status="", note=f"{len(val) - shown} more identical records"))
        else:
            status, note = verdict_for(obj_name, path)
            t = "bool" if isinstance(val, bool) else "int" if isinstance(val, int) else "float" if isinstance(val, float) else "string"
            fields.append(dict(path=path, type=t, value=val, status=status, note=note))
    walk(tree_value, "")


def build_catalog(cpk_path=None):
    from dt270_objects import Schema, load_game_packs
    schema = Schema.load()
    packs = load_game_packs(Path(cpk_path)) if cpk_path else load_game_packs()
    by_name = {n: (fname, pack) for fname, (_b, pack) in packs.items() for n in pack.names()}

    objects = []
    for name, (fallback_file, blurb) in GAMEPLAY_OBJECTS.items():
        if name not in by_name:
            continue
        fname, pack = by_name[name]
        fields = []
        flatten(name, pack.object(name).to_dict(), fields)
        counts = {}
        for f in fields:
            counts[f["status"] or "sub"] = counts.get(f["status"] or "sub", 0) + 1
        objects.append(dict(name=name, file=fname, blurb=blurb, field_count=len(fields),
                            counts=counts, fields=fields))

    # patch packs + applied state
    packs_dir = REPO / "tools" / "data" / "patches"
    applied_state = {}
    state_file = REPO / "build" / "exe_patch_state.json"
    if state_file.exists():
        applied_state = json.loads(state_file.read_text())
    packlist = []
    for spec in sorted(packs_dir.glob("*.json")):
        d = json.loads(spec.read_text())
        packlist.append(dict(name=spec.name, description=d.get("description", ""),
                             count=len(d.get("patches", [])),
                             applied=spec.name in applied_state.get("applied", [])))

    tuning = None
    tfile = REPO / "tools" / "data" / "tunings" / "loose-realism-v2.json"
    if tfile.exists():
        td = json.loads(tfile.read_text())
        tuning = dict(name="loose-realism-v2", count=len(td.get("edits", [])),
                      inert=sum(1 for e in td.get("edits", []) if e.get("inert")))

    meta = schema.meta
    return dict(
        generated=meta.get("generated", "?"),
        objects=objects,
        exe_systems=exe_systems(),
        patch_packs=packlist,
        tuning=tuning,
        totals=dict(
            dt270_objects=len(objects),
            dt270_fields=sum(o["field_count"] for o in objects),
            exe_levers=sum(len(x["levers"]) for x in exe_systems()),
        ),
    )


def cmd_build(a):
    cat = build_catalog(a.cpk)
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(cat, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {CATALOG} — {cat['totals']['dt270_objects']} objects, "
          f"{cat['totals']['dt270_fields']} fields, {cat['totals']['exe_levers']} exe levers")
    return 0


def cmd_search(a):
    cat = build_catalog(a.cpk)
    q = a.term.lower()
    for o in cat["objects"]:
        for f in o["fields"]:
            if q in f["path"].lower() or q in (f["note"] or "").lower():
                print(f"dt270  {o['name']}.{f['path']:40} {f['type']:8} = {f['value']}  [{f['status']}] {f['note'][:60]}")
    for s in cat["exe_systems"]:
        for l in s["levers"]:
            if q in l["name"].lower() or q in l["effect"].lower() or q in l["knob"].lower():
                print(f"exe    {s['system']}: {l['name']:38} {l['va']:14} {l['current']:12} — {l['effect'][:60]}")
    return 0


def cmd_html(a):
    cat = build_catalog(a.cpk)
    HTML.parent.mkdir(parents=True, exist_ok=True)
    HTML.write_text(render_html(cat), encoding="utf-8")
    print(f"wrote {HTML} ({HTML.stat().st_size:,} B)")
    return 0


def render_html(cat: dict) -> str:
    from catalog_html import PAGE   # template kept next to this tool
    return PAGE.replace("/*DATA*/{}", json.dumps(cat))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpk", default=None, help="dt270 CPK to read values from (default: installed game)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("html")
    p = sub.add_parser("search"); p.add_argument("term")
    a = ap.parse_args()
    return {"build": cmd_build, "html": cmd_html, "search": cmd_search}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
