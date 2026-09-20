#!/usr/bin/env python3
"""
gameplay_catalog.py — the gameplay catalogue, SUBSYSTEM-FIRST.

Rebuilt 2026-09-20 on top of the eight finished gameplay chapters in docs/. The 2026-08-23
catalogue was field-first — a list of dt270 constant names with hand-typed verdicts — so a
reader arriving with "why does my centre-back stand off" had no entry point, and several of
its rows had since been disproved. This version answers the football question first and keeps
the field table as a secondary view.

What it merges
  1. docs/*.md, the eight chapters — parsed by tools/catalog_chapters.py. Their "What this
     enables", "Tunables", "Negatives"/"Refuted", "Corrections" and "Open questions" sections
     become the Questions, Subsystems, Levers and Negatives views, VERBATIM, with the chapter's
     own a-emulated / b-disassembly / c-inferred tags and its own hedging intact.
  2. tools/data/catalog_questions.json — the chapters re-keyed onto the question a reader
     actually arrives with. Every row cites chapter + section + addresses.
  3. tools/data/catalog_corrections.json — what the old catalogue got wrong and now says
     correctly, plus the read-but-INERT overrides (a field can have a reader and still do
     nothing) and the objects no chapter owns.
  4. build/dt270_liveness.json — per-FIELD status and reader list for 245 objects / 21,977
     fields. The old generator never opened this file; its 18 prefix-matched verdict tuples
     are gone.
  5. The installed dt270 CPK — every value is read at build time, never hard-coded.
  6. eFootball.exe — MEASURED: sha1 of installed / PRISTINE / STOCK, a byte-compare of every
     patch spec against the live image, and a fresh dump of the 44-row CPU difficulty table
     out of PRISTINE (the old catalogue's dump was stock and is the corrective source for a
     chapter that dumped it from our patched image).

    python tools/gameplay_catalog.py build   # -> build/gameplay_catalog.json
    python tools/gameplay_catalog.py html    # -> build/gameplay-catalog.html (self-contained)
    python tools/gameplay_catalog.py search curl
    python tools/gameplay_catalog.py state   # just the measured install state, to the terminal

Patch specs, tunings and the patch journal live in tools/data/patches, tools/data/tunings and
build/exe_patch_state.json. If this worktree does not carry them, point --toolrepo (or
$EF_TOOLREPO) at a checkout that does; nothing is ever written there.

READ-ONLY. This tool never writes to the game, the exe or the CPK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
CATALOG = REPO / "build" / "gameplay_catalog.json"
HTML = REPO / "build" / "gameplay-catalog.html"

EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64\eFootball.exe")
BACKUPS = Path.home() / "Backups" / "eFootball"
PRISTINE = BACKUPS / "eFootball.exe.PRISTINE"
STOCK = BACKUPS / "eFootball.exe.STOCK"
IMAGE_BASE = 0x140000000
DIFFICULTY_TABLE_VA = 0x146C06F40
DIFFICULTY_ROWS, DIFFICULTY_STRIDE, DIFFICULTY_COLS = 44, 0x2C, 10
ADDR_RE = re.compile(r"0x1[0-9a-fA-F]{7,}")

# Gameplay-relevant dt270 objects (skip stadium/demo/tutorial/sugoroku/pathToGlory scenery).
GAMEPLAY_OBJECTS = {
    "ball": ("constant_match.bin", "Ball physics — drag, Magnus curl, bounce, spin decay, roll friction"),
    "shoot": ("constant_player.bin", "Shot power/height — launch-speed gauges (km/h) and elevation curves"),
    "trap": ("constant_player.bin", "First touch — control quality, reaction traps, loose-ball behaviour"),
    "grounderpass": ("constant_player.bin", "Ground pass — speed, receive, lob, assist blend"),
    "flypass": ("constant_player.bin", "Lofted pass — trajectory height, assist blend"),
    "throughpass": ("constant_player.bin", "Through ball — run timing, target search, speed"),
    "centering": ("constant_player.bin", "Crossing — curve, speed, search"),
    "passget": ("constant_player.bin", "Receiving & interception — read at DEPTH 0 inside PassGetRoute* itself"),
    "moveMatching": ("constant_player.bin", "Locomotion — acceleration, deceleration, turn speed per route"),
    "basePosition": ("constant_team.bin", "Team-shape AI — defensive line, compactness, width, pressing, marking"),
    "rating": ("constant_match.bin", "Match rating formula — per-action weights, bonuses, position rates"),
    "ballplayer": ("constant_player.bin", "Player locomotion tables — turn/touch motion matching (fetch site UNSOUND)"),
    "cameraInplay": ("constant_match.bin", "In-play camera rig"),
    "positionPK_2": ("constant_team.bin", "Penalty standing arrangement, defending back THREE (fetched by name)"),
    "positionPK_3": ("constant_team.bin", "Penalty standing arrangement, defending back THREE (fetched by name)"),
    "positionPK_4": ("constant_team.bin", "Penalty standing arrangement, defending back FOUR (fetched by name)"),
    "positionPK_5": ("constant_team.bin", "Penalty standing arrangement, defending back FIVE (fetched by name)"),
    "setplayGuideCornerKick": ("constant_player.bin", "Corner delivery guide — 100% 'read', NO chapter owns it"),
    "setplayGuideFreeKickNear": ("constant_player.bin", "Near free-kick guide — 100% 'read', NO chapter owns it"),
    "setplayGuideFreeKickMiddle": ("constant_player.bin", "Mid free-kick guide — 100% 'read', NO chapter owns it"),
    "setplayGuideFreeKickFar": ("constant_player.bin", "Far free-kick guide — 100% 'read', NO chapter owns it"),
    "setplayGuideGoalKick": ("constant_player.bin", "Goal-kick guide — 100% 'read', NO chapter owns it"),
}

# Legacy 2026-08-23 curated systems. KEPT — the kick-error, attribute-model and difficulty blocks
# are the best-evidenced things in the old catalogue and two chapters independently corroborate
# them. Every lever is re-tagged below with the chapter that now owns it, and the rows the
# chapters disproved carry a superseded note instead of being deleted.
FEATURED_SYSTEMS = [
    {
        "system": "Kick error model",
        "subsystem": "anime",
        "blurb": "How every pass and shot deviates from its intended direction and power. There is no such field in dt270 — the whole model is in the exe. Builder 0x14401a900 sets per-axis max error, then one of three randomisers applies it; a per-player ability factor (0x143ed71d0) suppresses it. TWO chapters corroborate the block: pad-input.md § 8.4 proves it has NO human/CPU branch (482-function closure), and set-pieces.md proves NO dead ball reaches it — so these levers are global to OPEN PLAY and do nothing for free kicks.",
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
        "subsystem": "anime",
        "blurb": "A mishit changes direction and power, but its spin AXIS just follows the (wrong) travel direction — so a shank curls like a clean kick, not a slice. NOTE, 2026-09-20: this block predates the chapters and NONE of the eight re-derives it, while the project's own 2026-09-17 note records 0x144018c10 as a VELOCITY RE-CLAMP rather than a spin builder, and the ball frame as Y-up not Z-up. Re-derive before trusting these four rows.",
        "levers": [
            {"name": "Sidespin lean cap (the slice lever)", "va": "0x144018df0", "current": "45°", "knob": "clamp(travel − facing) before building the spin axis", "effect": "Raise to 90° so a shanked/sliced kick's sidespin grows with the horizontal miss. 180° = near-unclamped.", "pack": "mishit-spin (P1)", "confidence": "likely"},
            {"name": "Assisted-kick spin scale", "va": "0x14401914c", "current": "50", "knob": "spin magnitude scale on the assisted branch (manual = 80)", "effect": "Raise to 80 so assisted passes/shots build the same spin as manual.", "pack": "mishit-spin (P2b)", "confidence": "likely"},
            {"name": "Spin-magnitude cap", "va": "0x144019177", "current": "0.9", "knob": "min-cap on built spin magnitude", "effect": "Raise to 1.0 for a mild overall curl/dip increase on all kicks.", "pack": "mishit-spin (P2)", "confidence": "likely"},
            {"name": "Magnus curl amplifier", "va": "ball.magnusRate (dt270)", "current": "read from the installed pack", "knob": "Magnus acceleration coefficient", "effect": "Amplifies whatever spin the ball has — scales all curl. See the dt270 tab for the value actually installed.", "pack": "dt270 tuning", "confidence": "proven"},
        ],
    },
    {
        "system": "CPU difficulty",
        "subsystem": "bp",
        "blurb": "Not in dt270 — a hard-coded 44×10 float table in the exe (0x146c06f40, stride 0x2c, value at +4+col*4), one column per level, read via GetParam 0x1442e48f0. The CARRIER reaction-delay rows are 0x17 (pass/clear), 0x18 (dribble) and 0x19 (dribble move) — NOT row 0, as the 2026-08-23 entry said; an earlier emulation indexed at stride 40 and read the table inverted. Rows 0x13–0x16 gate which RUN TYPES exist at each level. The full table below is re-dumped from PRISTINE at every build.",
        "levers": [
            {"name": "Carrier reaction delay (pass/clear)", "va": "0x146c06f40 + 0x17*0x2c + 4", "current": "see the dumped table", "knob": "row 0x17, per-level ticks", "effect": "Raise the c6/c8 columns so the CPU dwells on the ball; stock Superstar is 6 ticks, Legend 2, Beginner 60.", "pack": "(manual)", "confidence": "proven"},
            {"name": "Whole level table", "va": "0x146c06f40", "current": "44 rows × 10 cols", "knob": "every per-level gameplay parameter", "effect": "Copy any column into another to make one level behave like a different one; a hidden LEGEND column exists.", "pack": "(manual)", "confidence": "proven"},
            {"name": "Runtime CPU level", "va": "TmpDb+0x94/+0x9c", "current": "as set in menu", "knob": "match level value (XOR-obfuscated)", "effect": "Force LEGEND (6) + strongest sub-column before kickoff.", "pack": "(runtime, live_patch)", "confidence": "proven"},
        ],
    },
    {
        "system": "Human power gauge",
        "subsystem": "pad",
        "blurb": "Kept from the 2026-08-23 map and UPGRADED by pad-input.md § 8: the 16-entry fill-time table is built by 0x1440d8070; the shoot cell is 0x1478501fc loaded at 0x1440d824a, reached only by ids 0x3d/0x3e, so it is genuinely isolable. The open-play PASS gauge is NOT — its load is the shared default arm. The real fill is 8 frames = 0.267 s at 60 fps, not 0.250 s.",
        "levers": [
            {"name": "Shoot gauge fill time", "va": "0x1440d824a", "current": "0.25 s (8 frames)", "knob": "time to full power gauge, shoot ids only", "effect": "0.40 s = 24 frames and 24 power levels — shooting takes commitment. TIER 3: a write to the .xcode page, an experiment, not a setting.", "pack": "(manual)", "confidence": "proven"},
            {"name": "Set-piece shot / pass fill", "va": "0x146b31dd4", "current": "0.38 / 0.42 s", "knob": "set-piece arms of the same table", "effect": "Separate from open play — editing these does not touch a normal shot.", "pack": "(manual)", "confidence": "proven"},
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
AREA_SUBSYSTEM = {
    "cpu-attacking-decisions": "match-ai", "cpu-defending": "match-ai", "goalkeeper": "gk",
    "shooting-behaviour": "bp", "passing-behaviour": "bp", "dribbling-skills": "bp",
    "physical-locomotion": "anime", "stamina-condition": "anime",
    "defending-tackle-foul": "setpieces", "set-pieces": "setpieces",
    "ball-physics-exe": "anime", "rng-and-globals": "registry",
    "difficulty-rows": "bp", "attribute-model": "",
}
MAX_ARRAY_ROWS = 6
# Objects whose record arrays are shown IN FULL rather than elided: the penalty arrangements are
# set-pieces.md's flagship data lever ("move the twenty-two bodies at a penalty"), and a view that
# shows two of twenty-two answers the wrong question.
ARRAY_SHOW_ALL = ("positionPK_2", "positionPK_3", "positionPK_4", "positionPK_5")


# ---------------------------------------------------------------- side data

def toolrepo(a=None) -> Path:
    """Where patch specs / tunings / the patch journal live (default: this repo)."""
    p = getattr(a, "toolrepo", None) or os.environ.get("EF_TOOLREPO")
    return Path(p) if p else REPO


def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def pe_sections(exe: Path):
    with open(exe, "rb") as f:
        d = f.read(0x1000)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    secs = []
    for i in range(nsec):
        s = d[pe + 24 + opt + 40 * i: pe + 24 + opt + 40 * (i + 1)]
        vsize, va, rsize, raw = struct.unpack_from("<IIII", s, 8)
        secs.append((s[:8].rstrip(b"\0").decode(), va, vsize, raw, rsize))
    return secs


def rva_to_file(secs, rva: int):
    for _name, va, vsize, raw, rsize in secs:
        if va <= rva < va + vsize:
            o = rva - va
            return raw + o if o < rsize else None
    return None


def first_diffs(a: Path, b: Path, limit=8):
    """Byte offsets where two images differ (up to `limit`), plus the total count."""
    out, total, pos = [], 0, 0
    with open(a, "rb") as f1, open(b, "rb") as f2:
        while True:
            b1, b2 = f1.read(1 << 22), f2.read(1 << 22)
            if not b1 and not b2:
                break
            if b1 != b2:
                for i in range(max(len(b1), len(b2))):
                    x = b1[i] if i < len(b1) else None
                    y = b2[i] if i < len(b2) else None
                    if x != y:
                        total += 1
                        if len(out) < limit:
                            out.append(dict(off=hex(pos + i), a=x, b=y))
            pos += max(len(b1), len(b2))
    return out, total


def difficulty_table(exe: Path):
    if not exe.exists():
        return None
    secs = pe_sections(exe)
    off = rva_to_file(secs, DIFFICULTY_TABLE_VA - IMAGE_BASE)
    if off is None:
        return None
    with open(exe, "rb") as f:
        f.seek(off)
        blob = f.read(DIFFICULTY_ROWS * DIFFICULTY_STRIDE)
    rows = []
    for r in range(DIFFICULTY_ROWS):
        rec = blob[r * DIFFICULTY_STRIDE:(r + 1) * DIFFICULTY_STRIDE]
        if len(rec) < DIFFICULTY_STRIDE:
            break
        flag = struct.unpack_from("<I", rec, 0)[0]
        vals = [round(struct.unpack_from("<f", rec, 4 + 4 * c)[0], 4) for c in range(DIFFICULTY_COLS)]
        rows.append(dict(row=r, va=hex(DIFFICULTY_TABLE_VA + r * DIFFICULTY_STRIDE), flag=flag, vals=vals))
    return rows


DT270_CPK = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk\dt270_console_all.cpk")


def image_state(tr: Path = None):
    st = dict(exe_path=str(EXE), pristine_path=str(PRISTINE), stock_path=str(STOCK))
    st["exe_present"] = EXE.exists()
    st["installed_sha1"] = sha1(EXE) if EXE.exists() else None
    st["installed_size"] = EXE.stat().st_size if EXE.exists() else None
    st["pristine_sha1"] = sha1(PRISTINE) if PRISTINE.exists() else None
    st["stock_sha1"] = sha1(STOCK) if STOCK.exists() else None
    st["installed_is_pristine"] = bool(st["installed_sha1"] and st["installed_sha1"] == st["pristine_sha1"])
    st["pristine_is_stock"] = bool(st["pristine_sha1"] and st["pristine_sha1"] == st["stock_sha1"])
    st["pristine_vs_stock"] = None
    if PRISTINE.exists() and STOCK.exists() and not st["pristine_is_stock"]:
        diffs, total = first_diffs(PRISTINE, STOCK)
        st["pristine_vs_stock"] = dict(
            n=total, first=diffs,
            note="PRISTINE is NOT stock: it carries a hostname edit (pes22-game.cs.ko → pes99-game.cs.ko) "
                 "that severs matchmaking and touches no gameplay code. eFootball.exe.STOCK is the true original.")

    # The dt270 pack is a SEPARATE install state from the exe, and it is the one the old
    # catalogue had no way to express.
    st["dt270_path"] = str(DT270_CPK)
    st["dt270_installed_sha1"] = sha1(DT270_CPK) if DT270_CPK.exists() else None
    ref = (tr or REPO) / "build" / "dt270_pristine.sha1"
    last = (tr or REPO) / "build" / "dt270_last_install.sha1"
    st["dt270_pristine_sha1"] = ref.read_text().strip() if ref.exists() else None
    st["dt270_last_install_sha1"] = last.read_text().strip() if last.exists() else None
    st["dt270_is_pristine"] = bool(st["dt270_installed_sha1"] and st["dt270_pristine_sha1"]
                                   and st["dt270_installed_sha1"] == st["dt270_pristine_sha1"])
    return st


def patch_packs(tr: Path):
    """Every spec in tools/data/patches, verdict MEASURED against the live exe.

    Three states per entry — applied / pristine / OTHER (expect bytes match nothing in this
    image, so the spec was built against a different base) — plus `noop_on_stock`, which flags
    a REVERT-shaped spec whose patch bytes ARE the stock bytes. Those read "applied" against a
    pristine exe and mean nothing.
    """
    pdir = tr / "tools" / "data" / "patches"
    journal = load_json(tr / "build" / "exe_patch_state.json", {}) or {}
    listed = set(journal.get("applied", []))
    out = []
    secs = pe_sections(EXE) if EXE.exists() else None
    pf = open(PRISTINE, "rb") if PRISTINE.exists() else None
    ef = open(EXE, "rb") if EXE.exists() else None
    try:
        for spec in sorted(pdir.glob("*.json")) if pdir.exists() else []:
            d = load_json(spec, {}) or {}
            desc = d.get("description", "") if isinstance(d, dict) else ""
            entries = d.get("patches", d) if isinstance(d, dict) else d
            entries = entries if isinstance(entries, list) else [entries]
            states, noop = [], 0
            for s in entries:
                try:
                    rva = (int(s["module_offset"], 16) if "module_offset" in s
                           else int(s["va"], 16) - IMAGE_BASE)
                    exp = bytes.fromhex(s["expect"].replace(" ", "").replace("_", ""))
                    pat = bytes.fromhex(s["patch"].replace(" ", "").replace("_", ""))
                except Exception:
                    states.append("unreadable")
                    continue
                off = rva_to_file(secs, rva) if secs else None
                if off is None or not ef:
                    states.append("unreadable")
                    continue
                ef.seek(off)
                cur = ef.read(len(exp))
                states.append("applied" if cur == pat else "pristine" if cur == exp else "OTHER")
                if pf:
                    pf.seek(off)
                    if pf.read(len(pat)) == pat:
                        noop += 1
            verdict = ("unknown" if not states else
                       "on" if all(x == "applied" for x in states) else
                       "off" if all(x == "pristine" for x in states) else
                       "not-applicable" if all(x == "OTHER" for x in states) else "mixed")
            out.append(dict(name=spec.name, description=desc, count=len(entries),
                            states=states, verdict=verdict, noop_on_stock=noop,
                            journal_says_applied=spec.name in listed))
    finally:
        if pf:
            pf.close()
        if ef:
            ef.close()
    return out, sorted(listed)


def tunings(tr: Path, value_of):
    """Every dt270 tuning, with how many of its edits the INSTALLED pack actually matches."""
    tdir = tr / "tools" / "data" / "tunings"
    out = []
    for f in sorted(tdir.glob("*.json")) if tdir.exists() else []:
        d = load_json(f, {}) or {}
        edits = d.get("edits", [])
        match = miss = unknown = 0
        for e in edits:
            obj, path, want = e.get("object"), e.get("path") or e.get("field"), e.get("value")
            cur = value_of(obj, path) if obj and path else None
            if cur is None:
                unknown += 1
            elif isinstance(cur, float) and isinstance(want, (int, float)):
                match += 1 if abs(cur - float(want)) <= 1e-4 else 0
                miss += 0 if abs(cur - float(want)) <= 1e-4 else 1
            elif cur == want:
                match += 1
            else:
                miss += 1
        # `unknown` = an edit whose field could not be read back at all. A verdict computed as if
        # those edits did not exist is a confident answer to "is my preset installed?" drawn from
        # a fifth of the data: loose-realism-v1 read "off" on 34 measured edits out of 155.
        if not edits:
            verdict = "unknown"
        elif unknown and unknown > (match + miss):
            verdict = "indeterminate"
        elif miss == 0 and match:
            verdict = "on"
        elif match:
            verdict = "partial"
        else:
            verdict = "off"
        out.append(dict(name=f.stem, count=len(edits),
                        inert=sum(1 for e in edits if e.get("inert")),
                        match=match, miss=miss, unknown=unknown, verdict=verdict,
                        description=d.get("description", "")))
    return out


# ---------------------------------------------------------------- dt270 join

def liveness_index():
    """(object, path-without-array-indices) -> {status, readers[], n_readers, unread_confidence}."""
    lv = load_json(REPO / "build" / "dt270_liveness.json")
    if not lv:
        return {}, {}
    objs = lv.get("objects", {})
    idx, meta = {}, {}
    for name, o in objs.items():
        meta[name] = dict(idx=o.get("idx"), located=o.get("located"),
                          unread_confidence=o.get("unread_confidence"),
                          stats=o.get("stats", {}), json=o.get("json"),
                          n_get_sites=o.get("stats", {}).get("n_get_sites"))
        for f in o.get("fields", []):
            key = (name, f.get("path", ""))
            rs = f.get("readers", []) or []
            idx[key] = dict(status=f.get("status"), n_readers=len(rs),
                            readers=[r.get("va") for r in rs[:4]],
                            soff=f.get("soff"), kind=f.get("kind"))
    return idx, meta


STATUS_ORDER = ["live", "read", "inert", "unread", "unlocated", "unresolved", "unknown"]


def build_dt270(cpk_path, corrections):
    from dt270_objects import Schema, load_game_packs
    schema = Schema.load()
    packs = load_game_packs(Path(cpk_path)) if cpk_path else load_game_packs()
    by_name = {n: (fname, pack) for fname, (_b, pack) in packs.items() for n in pack.names()}
    lidx, lmeta = liveness_index()

    eff = {}
    for row in corrections.get("dt270_effective", []):
        eff[(row["object"], row["path"])] = row
    orphan_objs = {o for grp in corrections.get("dt270_orphans", []) for o in grp["objects"]}
    orphan_note = {o: grp["note"] for grp in corrections.get("dt270_orphans", []) for o in grp["objects"]}

    def base_path(p):
        """Catalogue path -> the liveness file's spelling: array indices blanked to `[]`."""
        out, depth = [], 0
        for ch in p:
            if ch == "[":
                depth += 1
                out.append("[")
            elif ch == "]":
                depth -= 1
                out.append("]")
            elif depth == 0:
                out.append(ch)
        return "".join(out)

    def lookup(obj, path):
        for key in (base_path(path), path, base_path(path) + "[]", path + "[]"):
            rec = lidx.get((obj, key))
            if rec:
                return rec
        return None

    def classify(obj, path):
        ov = (eff.get((obj, base_path(path)))
              or eff.get((obj, base_path(path).replace("[]", "")))
              or eff.get((obj, "")))          # whole-object override, e.g. ballplayer
        rec = lookup(obj, path)
        readers = rec["readers"] if rec else []
        n = rec["n_readers"] if rec else 0
        if ov:
            e = ov["effective"]
            st = {"inert": "inert", "live": "live", "unresolved": "unresolved"}.get(e, e)
            return st, ov["why"], ov.get("source", ""), (readers, n)
        if not rec:
            return "unknown", "", "", (readers, n)
        s = rec["status"]
        if s == "read":
            return "read", f"{n} reader site(s) — a reader is proven; EFFECT is not.", "", (readers, n)
        if s == "cached":
            return "read", "reached only through a cached pointer — offset collisions possible (medium confidence).", "", (readers, n)
        if s == "unread":
            conf = (lmeta.get(obj) or {}).get("unread_confidence", "?")
            return "unread", f"no reader found; object unread-confidence '{conf}'.", "", (readers, n)
        if s == "unlocated":
            return "unlocated", "no get() site for this object was found at all — NOT evidence of anything.", "", (readers, n)
        return "unknown", "", "", (readers, n)

    objects = []
    for name, (fallback_file, blurb) in GAMEPLAY_OBJECTS.items():
        if name not in by_name:
            continue
        fname, pack = by_name[name]
        fields = []

        def walk(val, path):
            if isinstance(val, dict):
                for k, v in val.items():
                    walk(v, f"{path}.{k}" if path else k)
            elif isinstance(val, list):
                scalars = [v for v in val if not isinstance(v, (dict, list))]
                if val and len(scalars) == len(val) and len(val) <= MAX_ARRAY_ROWS:
                    add(path, val, "float[]" if any(isinstance(v, float) for v in val) else "int[]")
                elif val and len(scalars) == len(val):
                    add(f"{path}[{len(val)}]", val[:3] + ["…"],
                        "float[]" if any(isinstance(v, float) for v in val) else "int[]",
                        extra=f"{len(val)}-element array")
                else:
                    # The elision note used to assert "N more identical records" unconditionally,
                    # without ever comparing them. Every family it was applied to was in fact
                    # distinct (positionPK playerData 22/22, TurnData 1298/1440), which hid the
                    # penalty arrangement — the safest data lever in the set-piece chapter —
                    # behind a claim that the other twenty bodies were copies. Measure instead.
                    shown = len(val) if name in ARRAY_SHOW_ALL else min(len(val), 2)
                    for i in range(shown):
                        walk(val[i], f"{path}[{i}]")
                    if len(val) > shown:
                        keys = [json.dumps(v, sort_keys=True, default=str) for v in val]
                        rest = keys[shown:]
                        ndist = len(set(rest))
                        same_as_head = ndist == 1 and rest[0] in keys[:shown]
                        n_more = f"{len(rest)} further record" + ("" if len(rest) == 1 else "s")
                        tail = ("and it DIFFERS from the record(s) shown" if len(rest) == 1
                                else f"{ndist} DISTINCT among them")
                        note = (f"{n_more}, every one identical to the record(s) shown "
                                f"— compared field-for-field at build time"
                                if same_as_head else
                                f"{n_more}, {tail} — compared field-for-field at build time, not "
                                f"shown here. Read them with gameplay_tune.py get, or edit by index.")
                        fields.append(dict(path=f"{path}[{shown}…{len(val)-1}]", type="record[]", value=None,
                                           status="", note=note, readers=[], n_readers=0, source=""))
            else:
                t = ("bool" if isinstance(val, bool) else "int" if isinstance(val, int)
                     else "float" if isinstance(val, float) else "string")
                add(path, val, t)

        def add(path, value, typ, extra=""):
            st, why, src, rr = classify(name, path)
            readers, n = rr if rr else ([], 0)
            note = " ".join(x for x in (extra, why) if x)
            fields.append(dict(path=path, type=typ, value=value, status=st, note=note,
                               readers=readers, n_readers=n, source=src))

        walk(pack.object(name).to_dict(), "")
        counts = {}
        for f in fields:
            counts[f["status"] or "sub"] = counts.get(f["status"] or "sub", 0) + 1
        m = lmeta.get(name, {})
        objects.append(dict(name=name, file=fname, blurb=blurb, field_count=len(fields),
                            counts=counts, fields=fields,
                            liveness=dict(idx=m.get("idx"), located=m.get("located"),
                                          unread_confidence=m.get("unread_confidence"),
                                          get_sites=m.get("n_get_sites"), json=m.get("json")),
                            orphan=name in orphan_objs,
                            orphan_note=orphan_note.get(name, "")))

    def value_of(obj, path):
        if obj not in by_name or not path:
            return None
        cur = by_name[obj][1].object(obj).to_dict()
        try:
            for k in path.split("."):
                if "[" in k:
                    nm, i = k[:k.index("[")], int(k[k.index("[") + 1:k.index("]")])
                    cur = cur[nm][i]
                else:
                    cur = cur[k]
        except Exception:
            return None
        return cur if not isinstance(cur, (dict, list)) else None

    return objects, schema.meta, value_of, lmeta


# ---------------------------------------------------------------- exe systems (legacy block)

_SECTION_CACHE = {}


def section_of(va: int):
    """Which PE section a VA lives in, measured from PRISTINE. Used to tell an instruction
    (.text -> exe-code) from a pooled constant or table (.rdata/.data -> exe-constant), instead
    of filing all 242 sweep rows under exe-code by fiat."""
    if not PRISTINE.exists():
        return None
    if "secs" not in _SECTION_CACHE:
        _SECTION_CACHE["secs"] = pe_sections(PRISTINE)
    rva = va - IMAGE_BASE
    for name, sva, vsize, _raw, _rsize in _SECTION_CACHE["secs"]:
        if sva <= rva < sva + vsize:
            return name
    return None


DT270_OBJECT_NAMES = tuple(sorted(GAMEPLAY_OBJECTS)) + ("grounderpass", "flypass", "throughpass",
                                                        "centering", "passget", "moveMatching",
                                                        "ballplayer", "basePosition", "ball",
                                                        "shoot", "trap", "rating")


def exe_lever_route(l) -> tuple:
    """(route, route_text) for a 2026-08-23 sweep row, derived from its OWN site string.

    Fourteen of these rows name a dt270 field as their site and one is a runtime write; filing
    them under "exe code" put the cheapest, no-memory-write levers in the scariest risk tier.
    """
    name = str(l.get("name", ""))
    va = str(l.get("va", ""))
    blob = f"{name} {va}".lower()
    if "dt270" in blob or "constant_player.bin" in blob or "constant_team.bin" in blob \
            or "constant_match.bin" in blob \
            or any(name.startswith(o + ".") for o in DT270_OBJECT_NAMES):
        return "dt270-data", "dt270 data file (named field — no memory write)"
    if "tmpdb" in blob or "live_patch" in blob or "runtime" in blob:
        return "runtime-data", "runtime write into the running process"
    if name.lower().startswith(("weak-foot", "stronger-foot", "skill/playstyle", "match ability")) \
            or "player+0x" in va or "skillstruct+0x" in va:
        return "player-data", "per-player data the app already writes"
    if "dead (no consumer)" in name.lower():
        return "none", "dead row — no consumer was found"
    m = ADDR_RE.search(va)
    if not m:
        return "unclassified", "the sweep records no address for this row"
    sec = section_of(int(m.group(0), 16))
    if sec in (".rdata", ".data", ".xdata"):
        return "exe-constant", f"pooled constant / table in {sec} (measured)"
    if sec:
        return "exe-code", f"instruction in {sec} (measured)"
    return "unclassified", "the sweep's address falls outside every PE section"


SWEEP_EVIDENCE = {"proven": "sweep-proven", "likely": "sweep-likely", "guess": "sweep-guess"}


def attribute_table():
    """The attribute id <-> UI-name table, straight out of tools/data/attr_index_map.json.

    Four of the thirty recorded corrections turn on attribute identity (0x17 is Dribbling, not
    Defensive Awareness; 0x16 is GK Awareness, not Speed), and dozens of rows are written as
    `attr(0x17)`. Sending the reader to a JSON file for the key to their own catalogue was the
    gap; the generator already had the file open.
    """
    d = load_json(REPO / "tools" / "data" / "attr_index_map.json", {}) or {}
    rows = []
    for k, v in sorted((d.get("entries") or {}).items(), key=lambda kv: int(kv[0], 16)):
        rows.append(dict(id=k, data_parameter=v.get("data_parameter", ""),
                         ui_name=v.get("ui_name", "") or v.get("guess", ""),
                         named=bool(v.get("ui_name")),
                         lo=v.get("min"), hi=v.get("max"), levelup=v.get("max_levelup"),
                         confidence=v.get("confidence", "?"),
                         hay=f"{k} {v.get('data_parameter','')} {v.get('ui_name','') or v.get('guess','')}".lower()))
    return dict(source="tools/data/attr_index_map.json",
                accessor=d.get("_accessor", {}), rule=d.get("_mapping_rule", ""),
                origin=d.get("_source", ""), rows=rows)


def supersession_index(corrections, chapters):
    """Every reason a pre-chapter row is now wrong, built from the chapters' OWN data.

    Three sources, none of them hand-maintained:
      1. dt270_effective overrides whose verdict is inert/unresolved — a lever that recommends
         editing a field the chapters proved inert is the worst kind of stale row.
      2. the `fixed` list — each entry's quoted subject and any addresses it names.
      3. the chapters' retirement tables (registry-blackboard's "rows that were earned the hard
         way"), matched on the field token they retire.
    The hand list `exe_lever_notes` still applies on top; it is no longer the only mechanism.
    """
    rules = []
    for row in corrections.get("dt270_effective", []):
        if row.get("effective") not in ("inert", "unresolved"):
            continue
        obj = row["object"].lower()
        leaf = (row.get("path") or "").split(".")[-1].lower()
        rules.append(dict(kind="dt270", need=[x for x in (obj, leaf) if x],
                          verdict=f"dt270: {row['effective']}", note=row["why"],
                          source=row.get("source", "")))
    for f in corrections.get("fixed", []):
        was = f.get("was", "")
        subj = re.findall(r"[\"“]([^\"”]{8,90})[\"”]", was)
        addrs = ADDR_RE.findall(was)
        for s in subj:
            rules.append(dict(kind="fixed", need=[s.lower()], verdict="superseded",
                              note=f.get("now", ""), source=f.get("source", "")))
        for a in addrs:
            rules.append(dict(kind="fixed", need=[a.lower()], verdict="superseded",
                              note=f.get("now", ""), source=f.get("source", "")))
    import catalog_chapters as cc
    for r in cc.retirements(chapters):
        for tok in r["tokens"]:
            rules.append(dict(kind="retired", need=[tok.lower()], verdict="RETIRED by another chapter",
                              note=r["plain_why"], source=f"{r['doc']} § NOT SAFELY TUNABLE"))
    return rules


def apply_supersession(rules, blob: str):
    """First matching rule for a row's searchable text, or None."""
    b = blob.lower()
    for r in rules:
        if all(n in b for n in r["need"]):
            return r
    return None


def exe_systems(corrections, chapters):
    notes = corrections.get("exe_lever_notes", [])
    rules = supersession_index(corrections, chapters)
    systems = [dict(s) for s in FEATURED_SYSTEMS]
    full = load_json(REPO / "build" / "exe_full_map.json")
    if full:
        for area, r in (full.get("sweeps") or {}).items():
            levers = []
            for l in r.get("levers", []):
                eff = l.get("effect", "")
                if l.get("patch_idea"):
                    eff = eff + "  ·  patch: " + l["patch_idea"]
                levers.append(dict(name=l.get("name", "?"), va=l.get("va", "—"),
                                   current=l.get("current", "—"), knob=l.get("reads", ""),
                                   effect=eff, pack="(hex/runtime)", confidence=l.get("confidence", "guess")))
            systems.append(dict(system=AREA_TITLES.get(area, area), blurb=r.get("summary", ""),
                                subsystem=AREA_SUBSYSTEM.get(area, ""), levers=levers,
                                source="build/exe_full_map.json (2026-08-23 sweep)"))
    for s in systems:
        s.setdefault("source", "curated 2026-08-23, re-checked 2026-09-20")
        s.setdefault("subsystem", "")
        for l in s["levers"]:
            l["route"], l["route_text"] = exe_lever_route(l)
            l["evidence"] = SWEEP_EVIDENCE.get(l.get("confidence"), "sweep-unstated")
            l["addrs"] = sorted(set(ADDR_RE.findall(str(l.get("va", "")))))[:8]
            hits = [n for n in notes if n["match"] in (l.get("va", "") + " " + l.get("name", ""))]
            if hits:
                l["superseded"] = hits[0]["verdict"]
                l["superseded_note"] = hits[0]["note"]
                l["superseded_source"] = hits[0]["source"]
            else:
                hit = apply_supersession(rules, f"{l.get('name','')} {l.get('va','')}")
                if hit:
                    l["superseded"] = hit["verdict"]
                    l["superseded_note"] = hit["note"]
                    l["superseded_source"] = hit["source"]
            if l.get("superseded"):
                # A row the chapters have disproved keeps its address and its history, but it
                # must not keep an evidence grade that invites the edit.
                l["evidence"] = "superseded"
    return systems


# ---------------------------------------------------------------- assembly

def build_catalog(cpk_path=None, tr: Path = None):
    tr = tr or REPO
    import catalog_chapters as cc
    chapters = cc.load_chapters()
    warnings = cc.verify(chapters)

    corrections = load_json(REPO / "tools" / "data" / "catalog_corrections.json", {}) or {}
    qdata = load_json(REPO / "tools" / "data" / "catalog_questions.json", {}) or {}
    questions = qdata.get("questions", [])
    for q in questions:
        q["hay"] = " ".join([q.get("q", ""), q.get("answer", ""), q.get("where", ""),
                             q.get("lever", ""), q.get("subsystem", "")]).lower()

    objects, schema_meta, value_of, _lmeta = build_dt270(cpk_path, corrections)
    packs, journal = patch_packs(tr)
    tunes = tunings(tr, value_of)
    systems = exe_systems(corrections, chapters)
    retired = cc.retirements(chapters)

    # The same retirement has to reach the Subsystems view's "What this enables" rows, or the
    # card keeps promising a lever the Levers view has just struck out.
    for ch in chapters:
        for e in ch["enables"]:
            blob = f"{e['want']} {e['where'][:90]}".lower()
            for r in retired:
                if r["by"] == ch["id"] or not r["tokens"]:
                    continue
                if any(tok.lower() in blob for tok in r["tokens"]):
                    e["superseded"] = f"RETIRED by {r['doc']}"
                    e["superseded_note"] = r["plain_why"]
                    e["route"] = "NOT-SAFELY-TUNABLE"
                    e["routes"] = ["NOT-SAFELY-TUNABLE"]
                    e["withdrawn"] = True
                    e["evidence"] = "superseded"   # the chapter's own words stay in `state`
                    break

    # LEVERS view: every chapter Tunables row, plus the curated exe systems, keyed by route.
    levers = []
    for ch in chapters:
        for t in ch["tunables"]:
            row = dict(t, subsystem=ch["id"], subsystem_title=ch["title"],
                       doc=ch["doc"], section=ch["tunables_section"], origin="chapter",
                       superseded="", superseded_note="", superseded_source="")
            # A chapter's lever can be retired by a LATER chapter. The blackboard chapter retires
            # the strongest-looking on-ball lever in the book (team+0xb3c4, a transient AI mood);
            # before this pass the catalogue still rendered it twice as a live exe-code lever.
            for r in retired:
                if r["by"] == ch["id"] or not r["tokens"]:
                    continue
                # Only when the retired field is the row's OWN SUBJECT. A dozen carrier rows
                # merely mention +0xb3c4 somewhere in their effect text while tuning a different
                # immediate; striking those out would be its own kind of laundering.
                blob = f"{t['what']} {t['site'][:60]}".lower()
                if any(tok.lower() in blob for tok in r["tokens"]):
                    row["superseded"] = f"RETIRED by {r['doc']}"
                    row["superseded_note"] = r["plain_why"]
                    row["superseded_source"] = f"{r['doc']} § NOT SAFELY TUNABLE"
                    row["route"] = "NOT-SAFELY-TUNABLE"
                    row["routes"] = ["NOT-SAFELY-TUNABLE"]
                    # The chapter's evidence cell stays visible in `evidence_text`; the BADGE
                    # must not still read b-disassembly on a row another chapter has retired.
                    row["evidence"] = "superseded"
                    break
            levers.append(row)
    for s in systems:
        for l in s["levers"]:
            levers.append(dict(what=l["name"], site=l.get("va", ""),
                               route_text=l.get("route_text", ""),
                               effect=l.get("effect", ""), evidence_text=l.get("confidence", ""),
                               sharers="", route=l.get("route", "unclassified"),
                               routes=[l.get("route", "unclassified")],
                               evidence=l.get("evidence", "sweep-unstated"),
                               withdrawn=bool(l.get("superseded")),
                               addrs=l.get("addrs", []),
                               hay=(l["name"] + " " + l.get("effect", "") + " " + str(l.get("va", ""))).lower(),
                               subsystem=s.get("subsystem", ""), subsystem_title=s["system"],
                               doc="build/exe_full_map.json" if "exe_full_map" in s.get("source", "") else "",
                               section=s["system"], origin="exe-map",
                               superseded=l.get("superseded", ""),
                               superseded_note=l.get("superseded_note", ""),
                               superseded_source=l.get("superseded_source", "")))

    negatives = []
    for ch in chapters:
        for n in ch["negatives"]:
            negatives.append(dict(n, subsystem=ch["id"], subsystem_title=ch["title"],
                                  doc=ch["doc"], section=ch["negatives_section"], kind="negative"))
        for c in ch["corrections"]:
            negatives.append(dict(c, subsystem=ch["id"], subsystem_title=ch["title"],
                                  doc=ch["doc"], section=ch["corrections_section"], kind="correction"))

    st = image_state(tr)
    diff_pristine = difficulty_table(PRISTINE) if PRISTINE.exists() else None
    diff_installed = difficulty_table(EXE) if EXE.exists() else None
    diff_same = (diff_pristine == diff_installed)

    lv_meta = (load_json(REPO / "build" / "dt270_liveness.json", {}) or {}).get("meta", {})
    lv_sum = (load_json(REPO / "build" / "dt270_liveness.json", {}) or {}).get("summary", {})

    route_counts = {}
    for l in levers:
        route_counts[l["route"]] = route_counts.get(l["route"], 0) + 1

    return dict(
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        schema_generated=schema_meta.get("generated", "?"),
        liveness_generated=lv_meta.get("generated", "?"),
        liveness_summary=lv_sum,
        image_state=st,
        difficulty_table=dict(va=hex(DIFFICULTY_TABLE_VA), stride=hex(DIFFICULTY_STRIDE),
                              cols=DIFFICULTY_COLS, measured_against="eFootball.exe.PRISTINE",
                              installed_matches_pristine=diff_same, rows=diff_pristine or []),
        chapters=chapters,
        questions=questions,
        levers=levers,
        route_counts=route_counts,
        route_label=cc.ROUTE_LABEL,
        route_note=cc.ROUTE_NOTE,
        route_order=cc.ROUTE_ORDER,
        negatives=negatives,
        retired=retired,
        objects=objects,
        attributes=attribute_table(),
        exe_systems=systems,
        patch_packs=packs,
        patch_journal=journal,
        tunings=tunes,
        fixed=corrections.get("fixed", []),
        self_fixes=corrections.get("self_fixes", []),
        gaps=corrections.get("gaps", []),
        warnings=warnings,
        totals=dict(
            questions=len(questions),
            subsystems=len(chapters),
            enables=sum(len(c["enables"]) for c in chapters),
            levers=len(levers),
            chapter_levers=sum(1 for l in levers if l["origin"] == "chapter"),
            negatives=sum(1 for n in negatives if n["kind"] == "negative"),
            corrections=sum(1 for n in negatives if n["kind"] == "correction"),
            opens=sum(len(c["opens"]) for c in chapters),
            dt270_objects=len(objects),
            dt270_fields=sum(o["field_count"] for o in objects),
            exe_levers=sum(len(x["levers"]) for x in systems),
            patch_packs=len(packs),
            tunings=len(tunes),
            fixed=len(corrections.get("fixed", [])),
            gaps=len(corrections.get("gaps", [])),
        ),
    )


# ---------------------------------------------------------------- commands

def cmd_build(a):
    cat = build_catalog(a.cpk, toolrepo(a))
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(cat, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    t = cat["totals"]
    print(f"wrote {CATALOG} ({CATALOG.stat().st_size:,} B)")
    print(f"  questions {t['questions']}  subsystems {t['subsystems']}  enables {t['enables']}  "
          f"levers {t['levers']} (chapter {t['chapter_levers']})")
    print(f"  negatives {t['negatives']}  corrections {t['corrections']}  open questions {t['opens']}  "
          f"stale-fixed {t['fixed']}  gaps {t['gaps']}")
    print(f"  dt270 {t['dt270_objects']} objects / {t['dt270_fields']} fields  ·  "
          f"exe levers {t['exe_levers']}  ·  packs {t['patch_packs']}  ·  tunings {t['tunings']}")
    for w in cat["warnings"]:
        print("  WARN:", w)
    return 0


def cmd_state(a):
    cat_tr = toolrepo(a)
    st = image_state(cat_tr)
    print(f"installed exe : {st['installed_sha1']}  ({st['installed_size']:,} B)" if st["exe_present"]
          else "installed exe : NOT FOUND")
    print(f"PRISTINE      : {st['pristine_sha1']}   -> installed == PRISTINE: {st['installed_is_pristine']}")
    print(f"STOCK         : {st['stock_sha1']}")
    if st["pristine_vs_stock"]:
        print(f"  PRISTINE vs STOCK: {st['pristine_vs_stock']['n']} byte(s) differ "
              f"{[d['off'] for d in st['pristine_vs_stock']['first']]}")
    packs, journal = patch_packs(cat_tr)
    from collections import Counter
    c = Counter(p["verdict"] for p in packs)
    print(f"patch specs   : {len(packs)}  {dict(c)}")
    print(f"  journal build/exe_patch_state.json lists {len(journal)} applied "
          f"— {'AGREES' if (not journal and c.get('on', 0) == 0) else 'DISAGREES with the bytes'}")
    for p in packs:
        if p["noop_on_stock"]:
            print(f"    revert-shaped (patch bytes == stock bytes): {p['name']} "
                  f"[{p['noop_on_stock']}/{p['count']}]")
    return 0


def cmd_search(a):
    import html as _h, re as _re
    def flat(x):                      # chapter rows carry inline HTML; the terminal wants text
        return " ".join(_h.unescape(_re.sub(r"<[^>]+>", "", str(x or ""))).split())
    cat = build_catalog(a.cpk, toolrepo(a))
    q = a.term.lower()
    for x in cat["questions"]:
        if q in x["hay"]:
            print(f"Q      {x['q']}\n       {x['answer'][:150]}…\n       [{x['route']} · {x['evidence']}] {x['section']}")
    for l in cat["levers"]:
        if q in l["hay"]:
            print(f"lever  [{l['route']:20}] {flat(l['what'])[:70]:70}  {flat(l['site'])[:52]}")
    for o in cat["objects"]:
        for f in o["fields"]:
            if q in f["path"].lower() or q in (f["note"] or "").lower():
                print(f"dt270  {o['name']}.{f['path']:40} {f['type']:8} = {f['value']}  [{f['status']}]")
    for n in cat["negatives"]:
        if q in n["hay"]:
            print(f"neg    [{n['subsystem']}] {flat(n['text'])[:150]}")
    return 0


def cmd_html(a):
    cat = build_catalog(a.cpk, toolrepo(a))
    HTML.parent.mkdir(parents=True, exist_ok=True)
    HTML.write_text(render_html(cat), encoding="utf-8")
    print(f"wrote {HTML} ({HTML.stat().st_size:,} B)")
    for w in cat["warnings"]:
        print("  WARN:", w)
    return 0


def render_html(cat: dict) -> str:
    from catalog_html import PAGE
    return PAGE.replace("/*DATA*/{}", json.dumps(cat, ensure_ascii=False))


def main():
    # The chapters are full of U+2212, U+00B7 and friends. A Windows console is cp1252, so
    # printing a lever row would raise UnicodeEncodeError and kill `search` mid-listing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpk", default=None, help="dt270 CPK to read values from (default: installed game)")
    ap.add_argument("--toolrepo", default=None,
                    help="checkout holding tools/data/patches, tools/data/tunings and "
                         "build/exe_patch_state.json (default: this repo, or $EF_TOOLREPO)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("html")
    sub.add_parser("state")
    p = sub.add_parser("search"); p.add_argument("term")
    a = ap.parse_args()
    return {"build": cmd_build, "html": cmd_html, "search": cmd_search, "state": cmd_state}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
