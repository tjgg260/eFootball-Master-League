# -*- coding: utf-8 -*-
"""
catalog_chapters.py — harvest the eight finished gameplay chapters in docs/ into structured rows.

The chapters are the source of truth for the subsystem-first catalogue. Nothing in here
re-authors them: every row is lifted verbatim out of a named section of a named file, so a
reader can check any row against the chapter in under a minute, and a chapter that hedges
still hedges in the catalogue.

Sections harvested per chapter:
  * title + date            — the H1
  * "…in one paragraph"     — the machine, verbatim (match-ai-decoded.md has no such section)
  * "What this enables"      — table: want | where | route | state   (match-ai: want | where | how)
  * "Tunables"               — table: what | site | route | effect | evidence | sharers
  * "Negatives" / "Refuted"  — bullet list, proven-absent / proven-placebo
  * "Corrections"            — bullet list or table, what this project believed that is wrong
  * "Open questions"         — bullet / numbered list

Used by tools/gameplay_catalog.py. Standalone:  python tools/catalog_chapters.py [--json]
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

# id -> (file, display title, one-line role). Order is the order the catalogue shows them in.
CHAPTERS = [
    ("match-ai", "match-ai-decoded.md", "match::ai — off-ball movement",
     "Which player is told to make which run, the team-shape/base-position layer, and the contact lockout."),
    ("bp", "ball-carrier-brain.md", "match::ai::bp — the on-ball brain",
     "What the player with the ball decides to do: plans, ThinkUnits, pass targets, dribble moves, Personality."),
    ("executors", "player-executors.md", "match::player — the executors",
     "What a chosen action actually does: run paths, marking destinations, pressing, the offside trap, reception."),
    ("registry", "registry-blackboard.md", "match::registry — the blackboard",
     "The shared match state both brains read: who publishes it, which buffer a write lands in, what an app can reach."),
    ("anime", "anime-actions.md", "match::anime — animation & contact",
     "Staggers, falls, cancel frames, the motion tables, first touch, and what the animation layer tells the referee."),
    ("pad", "pad-input.md", "match::pad — the pad→command channel",
     "How a button becomes a command, the tap law, the power gauge, who the pad can and cannot reach."),
    ("gk", "goalkeeper.md", "Goalkeeping — stitched across two subsystems",
     "Positioning, the save-quality decision, coming out, distribution, and what a keeper's attributes buy."),
    ("setpieces", "set-pieces.md", "Set pieces — the dead ball, end to end",
     "Corners, free kicks, throw-ins, kick-offs, goal kicks, penalties, the wall, and the anti-penalty bias."),
]

ADDR_RE = re.compile(r"0x1[0-9a-fA-F]{7,}")


# ---------------------------------------------------------------- markdown helpers

def md_inline(s: str) -> str:
    """Markdown inline -> safe HTML. Escapes first, so document text can never inject markup."""
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)          # chapter-internal links: keep the text
    return s


def plain(s: str) -> str:
    """Strip markdown emphasis/backticks — for search haystacks."""
    return re.sub(r"[`*_]", "", s)


def split_row(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    # tables in these chapters never contain an escaped pipe inside a cell
    return [c.strip() for c in line.split("|")]


def parse_tables(lines):
    """Every markdown table in `lines` -> [(header[], rows[[]], meta)], in document order.

    A cell that wraps onto the next physical line leaves its row without a closing `|`, and the
    next line does not start with one. Folding that continuation back in is not cosmetic: before
    2026-09-20 the scan simply STOPPED there, which silently truncated one row of
    player-executors.md's Tunables table to two cells and dropped the 23 rows after it — the
    per-slot marking mode, the per-team line field, the offside-trap rows, the GK floors and the
    honest "not reachable" verdicts among them.

    `meta` carries `pipe_lines` (physical row lines seen) and `folded` so verify() can prove no
    row was lost rather than assuming it.
    """
    out, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            header = [h.lower() for h in split_row(lines[i])]
            rows, j, pipe_lines, folded = [], i + 2, 0, 0
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                raw = lines[j].rstrip()
                pipe_lines += 1
                j += 1
                while (not raw.endswith("|")) and j < len(lines) and lines[j].strip() \
                        and not lines[j].lstrip().startswith(("|", "#", "---")):
                    raw = raw + " " + lines[j].strip()
                    folded += 1
                    j += 1
                cells = split_row(raw)
                if len(cells) < len(header):
                    cells += [""] * (len(header) - len(cells))
                rows.append(cells[:len(header)])
            out.append((header, rows, dict(pipe_lines=pipe_lines, folded=folded, line=i + 1)))
            i = j
        else:
            i += 1
    return out


def parse_table(lines):
    """First markdown table found in `lines` -> (header[], rows[[]])."""
    ts = parse_tables(lines)
    return (ts[0][0], ts[0][1]) if ts else ([], [])


def parse_list(lines):
    """Top-level bullets / numbered items -> list of strings (continuation lines folded in)."""
    items, cur = [], None
    for ln in lines:
        m = re.match(r"^\s{0,3}(?:[-*+]|\d+\.)\s+(.*)$", ln)
        if m:
            if cur is not None:
                items.append(" ".join(cur).strip())
            cur = [m.group(1)]
        elif cur is not None:
            if ln.strip() == "":
                items.append(" ".join(cur).strip())
                cur = None
            elif ln.startswith((" ", "\t")):
                cur.append(ln.strip())
            else:
                items.append(" ".join(cur).strip())
                cur = None
    if cur is not None:
        items.append(" ".join(cur).strip())
    return [i for i in items if i]


# ---------------------------------------------------------------- section index

def sections(text: str):
    """[(level, heading_text, body_lines, heading_line_no)] for every ## / ### heading.

    A section's body runs to the next heading of the SAME OR HIGHER level, so a `##` section
    carries its `###` subsections with it — several chapters put their Tunables table and their
    Corrections items one level down.
    """
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2).strip())
             for i, ln in enumerate(lines) if (m := re.match(r"^(#{1,3})\s+(.*)$", ln))]
    out = []
    for k, (i, lvl, htxt) in enumerate(heads):
        end = len(lines)
        for j, lv, _t in heads[k + 1:]:
            if lv <= lvl:
                end = j
                break
        if lvl >= 2:
            out.append((lvl, htxt, lines[i + 1:end], i + 1))
    return out


def find(secs, *needles, level=None, exclude=()):
    """First section whose heading contains any needle (case-insensitive)."""
    for lvl, htxt, body, ln in secs:
        h = htxt.lower()
        if level and lvl != level:
            continue
        if any(x in h for x in exclude):
            continue
        if any(n in h for n in needles):
            return htxt, body, ln
    return None, [], None


# ---------------------------------------------------------------- route vocabulary

# Order = the order the Levers view shows the cards in, AND the priority used to pick a row's
# primary class when its own words support more than one. The four "you cannot act on this"
# classes come first deliberately: a reader who skims the top of the page should meet the
# non-levers before the levers, and a row that says "nothing to tune; needs a cave" is filed
# under nothing-to-tune rather than under the cave.
ROUTE_ORDER = ["NOT-SAFELY-TUNABLE", "withdrawn", "not-reachable", "none", "dt270-data",
               "player-data", "motion-asset", "runtime-data", "exe-constant", "exe-code",
               "unclassified"]

ROUTE_LABEL = {
    "dt270-data": "dt270 data file",
    "player-data": "player / team data",
    "motion-asset": "motion asset",
    "runtime-data": "runtime write",
    "exe-constant": "exe constant",
    "exe-code": "exe code",
    "not-reachable": "not reachable",
    "NOT-SAFELY-TUNABLE": "NOT SAFELY TUNABLE",
    "withdrawn": "WITHDRAWN by its own chapter",
    "none": "nothing to tune",
    "unclassified": "route not stated",
}

ROUTE_NOTE = {
    "dt270-data": "A named field in the dt270 CPK. No memory write at all — the cheapest and most reversible route, and it survives a Konami patch once the schema is regenerated.",
    "player-data": "Something the companion app already writes: an attribute, a playing-style bit, a skill card, a formation slot. No patch of any kind.",
    "motion-asset": "A .bin inside a WESYS container inside the CPK, edited in place at identical length. Per-animation granularity — but the WESYS packer for dt230 does not exist yet, so this route is READ-ONLY today.",
    "runtime-data": "A write into the running process's data pages (live_patch.py). Nothing on disk changes; it must be re-done every launch, and timing against the game's own writers matters.",
    "exe-constant": "A pooled float/int cell in the exe. Safe to edit IN PLACE only when the cell is private (sharer count 1); otherwise re-aim the instruction's disp32 at a private cell.",
    "exe-code": "An instruction-local immediate, a branch, or a re-aimed rip-displacement. Denuvo makes the on-disk image risky — some of these are runtime-only, and .xcode writes are an experiment, not a setting.",
    "not-reachable": "A real, decoded mechanism with no authoring path found. Listed so nobody re-derives it hoping for one.",
    "NOT-SAFELY-TUNABLE": "Looks like a lever and will hurt you: constants that double as RNG stream indices or loop bounds, cells multiplied by a just-zeroed register, values the game rewrites every frame, shared pool cells that must never be written in place.",
    "withdrawn": "The chapter that offered this row has since withdrawn it. Kept visible, because deleting a wrong entry teaches nobody — but do not act on it.",
    "none": "There is nothing to change here. The row exists so the question has an answer.",
    "unclassified": "The chapter states no route for these, and nothing in the row resolves to one. They are NOT known to be tunable — this bucket exists so a missing route can never be mistaken for a verdict.",
}

# Keyword -> route. Order matters: the first class that matches a route cell wins for grouping,
# but EVERY match is kept (a chapter that says "exe code … or player data" gets both badges).
ROUTE_RULES = [
    ("withdrawn", ("withdrawn", "verdict is withdrawn")),
    ("none", ("nothing to tune", "no lever", "nothing to change")),
    ("not-reachable", ("not reachable", "not-reachable", "cannot be executed", "no static route",
                       "no isolating edit", "not located", "origin not traced", "writer unknown",
                       "no writer", "nowhere to write", "not actionable", "no located base",
                       "no located writer", "no disp32 writer", "same unknown base",
                       "fix not yet", "no writer was found")),
    # plain() strips ` * _ for the search haystack, so a route cell that names gameplay_tune
    # arrives here spelled "gameplaytune". Match both.
    ("dt270-data", ("dt270", "gameplay_tune", "gameplaytune", "constant_player.bin",
                    "constant_team.bin", "constant_match.bin", "data file")),
    ("player-data", ("player data", "player-data", "player.bin", "master.db", "formation",
                     "playing-style", "playing style", "skill card", "attribute", "app already writes",
                     "out-of-possession mask", "style bit")),
    ("motion-asset", ("motion-asset", "motion asset", "mbinfo", "dt230")),
    ("runtime-data", ("runtime", "live_patch", "livepatch", "writeprocessmemory")),
    ("exe-constant", ("exe constant", "exe-constant", "private cell", "data page")),
    ("exe-code", ("exe code", "exe-code", "cave", "re-aim", "immediate", "inline", ".xcode",
                  "instruction-local", "branch")),
]


def classify_routes(route_cell: str, what_cell: str = "") -> list:
    """Every route class a row's own words support, in ROUTE_ORDER. Never empty."""
    blob = plain(f"{what_cell} {route_cell}").lower()
    r = plain(route_cell).lower().strip()
    hits = set()
    if "not safely tunable" in blob or "not-safely-tunable" in blob:
        hits.add("NOT-SAFELY-TUNABLE")
    for cls, needles in ROUTE_RULES:
        if any(n in r for n in needles):
            hits.add(cls)
    if not hits:
        if r in ("", "—", "-", "none", "n/a"):
            hits.add("none")
        else:
            # NEVER fall through to exe-code. A default that names a tunable route turns "we do
            # not know" into a verdict — which is how "cannot be executed" rows ended up filed
            # under exe code in the 2026-09-20 first cut.
            hits.add("unclassified")
    return [x for x in ROUTE_ORDER if x in hits]


def classify_route(route_cell: str, what_cell: str = "") -> str:
    return classify_routes(route_cell, what_cell)[0]


WITHDRAWN_RE = re.compile(r"withdrawn|not proven|unproven|unquantified|not actionable|very likely a placebo",
                          re.I)

EV_LEAD_RE = re.compile(r"^[\s\*_(\[—-]*([abc])(?![a-z])")
EV_NAME = {"a": "a-emulated", "b": "b-disassembly", "c": "c-inferred"}


def evidence_of(cell: str) -> str:
    """The chapters' own a / b / c tag, taken from the LEADING tag of an evidence cell.

    Mixed cells are common and they are ordered: "b for the predicate, a for the emulated rows,
    b for the arithmetic" claims b, and "**c** (bytes are b)" claims c. Taking any occurrence
    (the pre-2026-09-20 behaviour) upgraded both of those rows a level.

    An empty or unrecognised cell is reported as **unstated** — never silently upgraded to a
    level the chapter did not claim. There is no c-inferred fallback.
    """
    c = plain(cell).lower().strip()
    if not c or c in ("-", "—", "n/a", "as listed"):
        return "unstated"
    m = EV_LEAD_RE.match(c)
    if m:
        return EV_NAME[m.group(1)]
    if c.startswith("emulat"):
        return "a-emulated"
    if c.startswith(("disassembl", "static read", "bytes")):
        return "b-disassembly"
    if c.startswith(("inferred", "not proven", "unproven")):
        return "c-inferred"
    return "unstated"


def evidence_bracket(text: str) -> str:
    """`[a]` / `[b]` / `[c]` as the chapters tag a prose row. Unstated when absent."""
    m = re.search(r"\[([abc])\]", plain(text))
    return EV_NAME[m.group(1)] if m else "unstated"


# ---------------------------------------------------------------- per-chapter harvest

def parse_chapter(cid: str, fname: str, title: str, role: str) -> dict:
    path = DOCS / fname
    text = path.read_text(encoding="utf-8")
    secs = sections(text)
    h1 = next((ln for ln in text.splitlines() if ln.startswith("# ")), "# ?")[2:].strip()
    m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", h1)
    date = m.group(1) if m else ""

    # the machine in one paragraph (match-ai-decoded.md has no such heading — fall back to its
    # architecture section's opening paragraph, and say so in the catalogue)
    ph, pbody, pline = find(secs, "in one paragraph")
    para_is_fallback = False
    if ph is None:
        ph, pbody, pline = find(secs, "the attacking-ai machine")
        para_is_fallback = True
    para = []
    for ln in pbody:
        if ln.strip() == "---":
            break
        if ln.startswith("|") or ln.startswith("#"):
            break
        para.append(ln.strip())
        if len(" ".join(para)) > 2600:
            break
    paragraph = md_inline(re.sub(r"\s+", " ", " ".join(para)).strip())

    eh, ebody, _ = find(secs, "what this enables")
    ehead, erows = parse_table(ebody)
    enables = []
    for r in erows:
        cells = dict(zip(ehead, r))
        route_cell = cells.get("route") or cells.get("how") or ""
        # match-ai-decoded.md's table is `want | where | how` — it states no evidence level at
        # all, so the row reports "unstated" rather than borrowing one from the prose.
        state_cell = cells.get("state", "")
        routes = classify_routes(route_cell, cells.get("want", ""))
        enables.append(dict(
            want=md_inline(cells.get("want", "")),
            where=md_inline(cells.get("where", "")),
            route_text=md_inline(route_cell),
            state=md_inline(state_cell),
            route=routes[0], routes=routes,
            evidence=evidence_of(state_cell),
            withdrawn=bool(WITHDRAWN_RE.search(plain(" ".join(r)))),
            addrs=sorted(set(ADDR_RE.findall(" ".join(r))))[:8],
            hay=plain(" ".join(r)).lower(),
        ))

    th, tbody, _ = find(secs, "tunables")
    tunables, table_meta, retires = [], [], []
    for thead, trows, tmeta in parse_tables(tbody):
        # A chapter may retire another chapter's lever in a table of its own. registry-blackboard's
        # "NOT SAFELY TUNABLE — the rows that were earned the hard way" is exactly that, and it
        # retires the strongest-looking on-ball lever in the whole catalogue. Harvest it as levers
        # AND as retirement records, so the row it kills can be badged wherever it is shown.
        if thead and thead[0].startswith("what the project believed"):
            table_meta.append(dict(tmeta, head=thead, rows=len(trows), kind="retirement"))
            for r in trows:
                cells = dict(zip(thead, r))
                what = cells.get("what the project believed", "")
                truth = cells.get("the truth", "")
                why = cells.get("why it must come off the list", "")
                rowtext = " ".join(r)
                toks = [t for t in re.findall(r"`([^`]+)`", what)
                        if re.fullmatch(r"[A-Za-z_][\w:]*\+0x[0-9a-fA-F]+|0x1[0-9a-fA-F]{7,}", t)]
                retires.append(dict(tokens=toks, what=md_inline(what),
                                    truth=md_inline(truth), why=md_inline(why),
                                    plain_why=plain(f"{truth} — {why}")))
                tunables.append(dict(
                    what=md_inline("RETIRED — " + what), site=md_inline(truth),
                    route_text="NOT SAFELY TUNABLE (retired by this chapter)",
                    effect=md_inline(why), evidence_text=md_inline(""),
                    sharers="", route="NOT-SAFELY-TUNABLE", routes=["NOT-SAFELY-TUNABLE"],
                    evidence=evidence_bracket(rowtext), withdrawn=True,
                    addrs=sorted(set(ADDR_RE.findall(rowtext)))[:8],
                    hay=plain(rowtext).lower()))
            continue
        if not thead or thead[0] not in ("what", "field", "private cell", "edit"):
            continue                      # route legends, risk-tier tables, prose tables: not levers
        table_meta.append(dict(tmeta, head=thead, rows=len(trows), kind="tunables"))
        for r in trows:
            cells = dict(zip(thead, r))
            rowtext = " ".join(r)
            what = cells.get("what") or cells.get("field") or cells.get("private cell") or cells.get("edit") or ""
            site = (cells.get("site") or cells.get("sole referrer") or cells.get("address")
                    or cells.get("reader (one of)") or "")
            effect = (cells.get("effect") or cells.get("what it gates") or cells.get("what it parameterises")
                      or cells.get("why it cannot be executed") or cells.get("notes") or "")
            if thead[0] == "field":       # the dt270 block inside a Tunables section
                what = f"{what}  ({cells.get('object', '')} {cells.get('off', '')} {cells.get('kind', '')})".strip()
                route_cell = "dt270 data file"
            elif thead[0] == "private cell":
                route_cell = "exe constant (private cell — safe in place)"
            elif thead[0] == "edit":
                route_cell = cells.get("risk", "") or "runtime"
                effect = effect + (f"  ·  {cells.get('current', '')} → {cells.get('proposed', '')}"
                                   if cells.get("proposed") else "")
            elif "object" in thead and "field" in thead:
                route_cell = "dt270 data file"
            else:
                route_cell = cells.get("route", "")
            stated = bool(route_cell)
            if not route_cell:
                route_cell = rowtext      # no route column: classify off the whole row
            routes = classify_routes(route_cell, what)
            # A table literally headed "why it cannot be executed" is the chapter's not-actionable
            # list. Its rows are not levers of any route, whatever their prose happens to mention.
            if "why it cannot be executed" in thead:
                routes = ["not-reachable"]
            if not stated:
                routes = routes[:1]       # inferred off prose: claim one class, not four
            tunables.append(dict(
                what=md_inline(what),
                site=md_inline(site),
                route_text=md_inline(cells.get("route", "") or ROUTE_LABEL.get(routes[0], "")),
                effect=md_inline(effect),
                evidence_text=md_inline(cells.get("evidence", "") or cells.get("risk", "")),
                sharers=md_inline(cells.get("sharers", "")),
                route=routes[0], routes=routes,
                evidence=evidence_of(cells.get("evidence", "") or cells.get("state", "")),
                withdrawn=bool(WITHDRAWN_RE.search(plain(f"{what} {effect}"))),
                addrs=sorted(set(ADDR_RE.findall(rowtext)))[:8],
                hay=plain(rowtext).lower(),
            ))

    nh, nbody, _ = find(secs, "negatives", "refuted")
    negatives = [dict(text=md_inline(i), hay=plain(i).lower(),
                      addrs=sorted(set(ADDR_RE.findall(i)))[:6]) for i in parse_list(nbody)]

    ch, cbody, _ = find(secs, "corrections", exclude=("to this chapter",))
    corrections = []
    for _chead, crows, _cmeta in parse_tables(cbody):
        for r in crows:
            corrections.append(dict(text=md_inline(" → ".join(x for x in r if x)),
                                    hay=plain(" ".join(r)).lower(),
                                    addrs=sorted(set(ADDR_RE.findall(" ".join(r))))[:6]))
    corrections += [dict(text=md_inline(i), hay=plain(i).lower(),
                         addrs=sorted(set(ADDR_RE.findall(i)))[:6]) for i in parse_list(cbody)]

    oh, obody, _ = find(secs, "open question")
    opens = [dict(text=md_inline(i), hay=plain(i).lower()) for i in parse_list(obody)]

    return dict(
        id=cid, doc=f"docs/{fname}", file=fname, title=title, role=role,
        h1=h1, date=date,
        paragraph=paragraph, paragraph_section=ph or "", paragraph_is_fallback=para_is_fallback,
        enables=enables, enables_section=eh or "",
        tunables=tunables, tunables_section=th or "", tunables_tables=table_meta,
        tunables_has_table=bool(table_meta), retires=retires,
        negatives=negatives, negatives_section=nh or "",
        corrections=corrections, corrections_section=ch or "",
        opens=opens, opens_section=oh or "",
        counts=dict(enables=len(enables), tunables=len(tunables), negatives=len(negatives),
                    corrections=len(corrections), opens=len(opens)),
    )


def load_chapters() -> list:
    out = []
    for cid, fname, title, role in CHAPTERS:
        if (DOCS / fname).exists():
            out.append(parse_chapter(cid, fname, title, role))
    return out


def verify(chs) -> list:
    """Loud warnings, printed by the generator — an empty harvest is a silent catalogue bug.

    The row-count rule is the one that matters: every physical `|` line under a harvested table
    header must survive into a row. A shortfall means a cell wrapped, a pipe was escaped, or the
    scan stopped early — the failure that cost this catalogue 24 lever rows without a peep.
    """
    warn = []
    have = {c["id"] for c in chs}
    for cid, fname, *_ in CHAPTERS:
        if cid not in have:
            warn.append(f"MISSING CHAPTER: docs/{fname}")
    for c in chs:
        if not c["paragraph"]:
            warn.append(f"{c['file']}: no 'in one paragraph' section found")
        if not c["enables"]:
            warn.append(f"{c['file']}: 'What this enables' table parsed to 0 rows")
        if not c["tunables_has_table"]:
            warn.append(f"{c['file']}: no Tunables table in this chapter "
                        f"(not a parse failure — the section does not exist)")
        elif not c["tunables"]:
            warn.append(f"{c['file']}: 'Tunables' tables are present but parsed to 0 rows")
        for t in c.get("tunables_tables", []):
            if t["rows"] != t["pipe_lines"]:
                warn.append(f"{c['file']}:{t['line']}: table harvested {t['rows']} rows from "
                            f"{t['pipe_lines']} row lines — {t['pipe_lines'] - t['rows']} LOST")
        if not c["negatives"]:
            warn.append(f"{c['file']}: no Negatives/Refuted items parsed")
    return warn


def retirements(chs) -> list:
    """Every retirement record, tagged with the chapter that issued it."""
    out = []
    for c in chs:
        for r in c.get("retires", []):
            out.append(dict(r, by=c["id"], by_title=c["title"], doc=c["doc"]))
    return out


if __name__ == "__main__":
    import sys
    chs = load_chapters()
    if "--json" in sys.argv:
        print(json.dumps(chs, indent=1)[:4000])
    else:
        for c in chs:
            print(f"{c['id']:10} {c['file']:26} {c['date']}  "
                  f"enables={c['counts']['enables']:3} tunables={c['counts']['tunables']:3} "
                  f"neg={c['counts']['negatives']:3} corr={c['counts']['corrections']:3} "
                  f"open={c['counts']['opens']:3}  para={len(c['paragraph'])}B")
        for w in verify(chs):
            print("WARN:", w)
