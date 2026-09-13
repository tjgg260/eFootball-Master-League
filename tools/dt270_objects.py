#!/usr/bin/env python3
"""
dt270_objects.py — read and edit eFootball's match-constant objects BY NAME.

dt270's `common/match/constant/constant_*.bin` files are WESYS containers (plain zlib, level 9)
around a PACK of named objects. Each object (`rating.o`, `ballplayer.o`, …) is a compiled JSON
document: a C-struct-like record of float / int / bool fields, where nested objects, arrays and
strings are u32 offsets (from the object start) to blocks. The field names, types and layouts
were recovered from the game's own JSON loaders (see dt270_schema_gen.py) and live in
tools/data/dt270_schema.json — regenerate that file after every Konami patch.

    python tools/dt270_objects.py list                         # objects in the installed pack
    python tools/dt270_objects.py fields ballplayer --depth 2  # browse the field tree
    python tools/dt270_objects.py get ballplayer dribble       # read values by dotted path
    python tools/dt270_objects.py dump --out build/dt270_json  # every object -> JSON
    python tools/dt270_objects.py verify                       # byte-exact round-trip gate

Library use:
    pack = Pack.from_payload(decode_constant(blob))     # blob = container bytes from the CPK
    obj  = pack.object("rating")                         # ObjectView (schema-bound)
    obj.get("baseRatingMax") ; obj.set("baseRatingMax", 7.5)
    payload2 = pack.payload()                            # rebuilt, byte-identical if unchanged

Hard rules baked in:
  * Edits are IN PLACE. An object never changes size; blocks never move. Strings may only be
    replaced by strings of the same or shorter length (NUL-padded). This keeps every other byte
    of the pack untouched, so the CPK can be patched in its original slot.
  * Arrays are read up to their EFFECTIVE count — Konami's generator emits only as many
    elements as the source JSON had (e.g. PathToGlory10.playerData has 40 of the 88 the loader
    reads). Elements past the object's data are reported as None and refuse to be written.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "tools" / "data" / "dt270_schema.json"
GAME_DT270 = Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball\cpk\dt270_console_all.cpk")

SCALAR_FMT = {"float": "<f", "int": "<i", "bool": "<?", "int8": "<b", "int16": "<h",
              "double": "<d", "int64": "<q"}
SCALAR_SIZE = {k: struct.calcsize(v) for k, v in SCALAR_FMT.items()}


# ----------------------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------------------

class Schema:
    def __init__(self, data: dict):
        self.meta = data.get("meta", {})
        self.types = data["types"]                       # type name -> {members, template, ...}
        self.by_object = {}
        for tname, t in self.types.items():
            for m in t["members"]:
                self.by_object[m] = tname

    @classmethod
    def load(cls, path: Path = SCHEMA_PATH) -> "Schema":
        if not path.exists():
            sys.exit(f"schema not found: {path}\nrun: python tools/dt270_schema_gen.py")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def template_for(self, object_name: str) -> dict | None:
        t = self.by_object.get(object_name)
        return self.types[t]["template"] if t else None


# ----------------------------------------------------------------------------------------
# Pack: the decoded constant_*.bin payload
# ----------------------------------------------------------------------------------------

class Pack:
    """header: u32 count, u32 8, then count x (u32 data_off, u32 data_size, u32 name_off);
    names are NUL-terminated '<name>.o'. Objects are raw byte slices we edit in place."""

    def __init__(self, payload: bytes, schema: Schema | None = None):
        self.raw = bytearray(payload)
        self.schema = schema
        n, hdr = struct.unpack_from("<II", payload, 0)
        if hdr != 8 or n > 10000:
            raise ValueError("not a dt270 constant pack")
        self.entries = []                                # (name, off, size)
        for i in range(n):
            off, size, noff = struct.unpack_from("<III", payload, 8 + 12 * i)
            end = payload.index(b"\0", noff)
            name = payload[noff:end].decode("ascii")
            if name.endswith(".o"):
                name = name[:-2]
            self.entries.append((name, off, size))
        self._views: dict[str, ObjectView] = {}

    @classmethod
    def from_payload(cls, payload: bytes, schema: Schema | None = None) -> "Pack":
        return cls(payload, schema or Schema.load())

    def names(self) -> list[str]:
        return [e[0] for e in self.entries]

    def entry(self, name: str):
        for e in self.entries:
            if e[0] == name:
                return e
        raise KeyError(name)

    def object_bytes(self, name: str) -> bytes:
        _, off, size = self.entry(name)
        return bytes(self.raw[off:off + size])

    def object(self, name: str) -> "ObjectView":
        if name not in self._views:
            _, off, size = self.entry(name)
            tmpl = self.schema.template_for(name) if self.schema else None
            if tmpl is None:
                raise KeyError(f"no schema for object {name!r} (regenerate dt270_schema.json?)")
            self._views[name] = ObjectView(name, self.raw, off, size, tmpl)
        return self._views[name]

    def payload(self) -> bytes:
        return bytes(self.raw)


# ----------------------------------------------------------------------------------------
# ObjectView: schema-bound access to one object's bytes (in place inside the pack buffer)
# ----------------------------------------------------------------------------------------

class Leaf:
    __slots__ = ("path", "off", "kind", "writable", "note")

    def __init__(self, path, off, kind, writable=True, note=""):
        self.path, self.off, self.kind, self.writable, self.note = path, off, kind, writable, note

    @property
    def dotted(self) -> str:
        return ".".join(str(p) for p in self.path)


class ObjectView:
    def __init__(self, name: str, buf: bytearray, base: int, size: int, template: dict):
        self.name, self.buf, self.base, self.size, self.template = name, buf, base, size, template
        self._leaves: list[Leaf] | None = None
        self._block_starts: list[int] | None = None

    # -- raw helpers (offsets are object-relative) --
    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.buf, self.base + off)[0]

    def _in_bounds(self, off: int, n: int) -> bool:
        return 0 <= off and off + n <= self.size

    def _block_starts_list(self) -> list[int]:
        """Every block start (pointer target, string target) — used to cap array counts to the
        elements the generator actually emitted."""
        if self._block_starts is None:
            starts = set()

            def walk(node, base):
                k = node["kind"]
                if k == "record":
                    for f in node["fields"]:
                        if f["off"] is None:
                            continue
                        off = base + f["off"]
                        if f.get("ptr"):
                            if not self._in_bounds(off, 4):
                                continue
                            p = self._u32(off)
                            if p:
                                starts.add(p)
                                if f["kind"] in ("record", "array"):
                                    walk(f, p)
                        elif f["kind"] in ("record", "array"):
                            walk(f, off)
                elif k == "array":
                    stride = node.get("stride") or 0
                    for i in range(node["count"]):
                        eoff = base + i * stride
                        if not self._in_bounds(eoff, 1):
                            break
                        e = node["elem"]
                        if e["kind"] == "string":
                            if self._in_bounds(eoff, 4):
                                p = self._u32(eoff)
                                if p:
                                    starts.add(p)
                        elif e["kind"] in ("record", "array"):
                            walk(e, eoff)
            walk(self.template, 0)
            self._block_starts = sorted(starts)
        return self._block_starts

    def effective_count(self, node: dict, base: int) -> int:
        """Elements that physically fit before the next block / end of object."""
        count, stride = node["count"], node.get("stride")
        if count <= 1 or not stride:
            return count if self._in_bounds(base, 1) else 0
        limit = self.size
        for s in self._block_starts_list():
            if s > base:
                limit = min(limit, s)
                break
        fit = max(0, (limit - base) // stride)
        return min(count, fit)

    # -- leaf enumeration --
    def leaves(self) -> list[Leaf]:
        if self._leaves is None:
            out: list[Leaf] = []

            def walk(node, base, path):
                k = node["kind"]
                if k == "record":
                    for f in node["fields"]:
                        if f["off"] is None:
                            out.append(Leaf(path + (f["name"],), -1, f["kind"], False, "unlocated"))
                            continue
                        off = base + f["off"]
                        fk = f["kind"]
                        if fk == "string":
                            out.append(Leaf(path + (f["name"],), off, "string", self._in_bounds(off, 4)))
                        elif f.get("ptr"):
                            if not self._in_bounds(off, 4):
                                out.append(Leaf(path + (f["name"],), off, fk, False, "pointer out of range"))
                                continue
                            p = self._u32(off)
                            if p:
                                walk(f, p, path + (f["name"],))
                        elif fk in ("record", "array"):
                            walk(f, off, path + (f["name"],))
                        else:
                            ok = self._in_bounds(off, SCALAR_SIZE[fk])
                            out.append(Leaf(path + (f["name"],), off, fk, ok, "" if ok else "out of range"))
                elif k == "array":
                    stride = node.get("stride") or 0
                    n_eff = self.effective_count(node, base)
                    e = node["elem"]
                    for i in range(node["count"]):
                        eoff = base + i * stride
                        if i >= n_eff:
                            out.append(Leaf(path + (i,), eoff, e["kind"], False, "beyond emitted data"))
                            continue
                        if e["kind"] == "string":
                            out.append(Leaf(path + (i,), eoff, "string", True))
                        elif e["kind"] in ("record", "array"):
                            walk(e, eoff, path + (i,))
                        else:
                            out.append(Leaf(path + (i,), eoff, e["kind"], True))
            walk(self.template, 0, ())
            self._leaves = out
        return self._leaves

    def leaf(self, path) -> Leaf:
        key = tuple(path)
        for lf in self.leaves():
            if lf.path == key:
                return lf
        raise KeyError(".".join(map(str, key)))

    # -- values --
    def read_leaf(self, lf: Leaf):
        if not lf.writable and lf.note in ("unlocated", "pointer out of range", "out of range", "beyond emitted data"):
            return None
        if lf.kind == "string":
            p = self._u32(lf.off)
            if p == 0 or p >= self.size:
                return None
            end = self.buf.index(b"\0", self.base + p, self.base + self.size)
            return bytes(self.buf[self.base + p:end]).decode("utf-8", "replace")
        return struct.unpack_from(SCALAR_FMT[lf.kind], self.buf, self.base + lf.off)[0]

    def string_capacity(self, lf: Leaf) -> int:
        p = self._u32(lf.off)
        end = self.buf.index(b"\0", self.base + p, self.base + self.size)
        return end - (self.base + p)

    def string_slot_shared(self, lf: Leaf) -> bool:
        p = self._u32(lf.off)
        return sum(1 for o in self.leaves() if o.kind == "string" and o.writable and self._u32(o.off) == p) > 1

    def write_leaf(self, lf: Leaf, value) -> None:
        if not lf.writable:
            raise ValueError(f"{lf.dotted}: not writable ({lf.note})")
        if lf.kind == "string":
            if not isinstance(value, str):
                raise TypeError(f"{lf.dotted}: expected string")
            p = self._u32(lf.off)
            if p == 0:
                raise ValueError(f"{lf.dotted}: null string cannot be set in place")
            cap = self.string_capacity(lf)
            data = value.encode("utf-8")
            if len(data) > cap:
                raise ValueError(f"{lf.dotted}: string too long ({len(data)} > {cap} bytes available)")
            self.buf[self.base + p:self.base + p + cap] = data + b"\0" * (cap - len(data))
            return
        fmt = SCALAR_FMT[lf.kind]
        if lf.kind == "bool":
            value = bool(value)
        elif lf.kind in ("float", "double"):
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{lf.dotted}: non-finite float")
        else:
            if isinstance(value, float) and not value.is_integer():
                raise TypeError(f"{lf.dotted}: expected integer")
            value = int(value)
        struct.pack_into(fmt, self.buf, self.base + lf.off, value)

    def get(self, path: str | tuple):
        """Dotted path -> scalar, or a subtree (dict/list) when the path names a container."""
        key = _parse_path(path)
        exact = [lf for lf in self.leaves() if lf.path == key]
        if exact:
            return self.read_leaf(exact[0])
        sub = [lf for lf in self.leaves() if lf.path[:len(key)] == key]
        if not sub:
            raise KeyError(".".join(map(str, key)))
        return _tree(sub, len(key), self.read_leaf)

    def set(self, path: str | tuple, value) -> None:
        self.write_leaf(self.leaf(_parse_path(path)), value)

    def to_dict(self) -> dict:
        return _tree(self.leaves(), 0, self.read_leaf)

    def apply_dict(self, data: dict, *, strict: bool = True) -> int:
        """Write every leaf whose value differs from the current bytes. Returns #changed."""
        changed = 0
        for lf in self.leaves():
            try:
                v = _dig(data, lf.path)
            except (KeyError, IndexError, TypeError):
                if strict:
                    raise KeyError(f"{self.name}: missing {lf.dotted} in supplied data")
                continue
            if v is None:
                continue
            cur = self.read_leaf(lf)
            if cur == v or (isinstance(cur, float) and isinstance(v, (int, float))
                            and struct.unpack("<f", struct.pack("<f", float(v)))[0] == cur):
                continue
            self.write_leaf(lf, v)
            changed += 1
        return changed


def _parse_path(path) -> tuple:
    if isinstance(path, tuple):
        return path
    out = []
    for part in str(path).replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        out.append(int(part) if part.lstrip("-").isdigit() else part)
    return tuple(out)


def _dig(data, path):
    cur = data
    for p in path:
        cur = cur[p]
    return cur


def _tree(leaves: list[Leaf], depth: int, reader):
    """Assemble leaves (sharing a prefix of length `depth`) into nested dict/list values."""
    root: dict | list | None = None

    def ensure(container, key, make):
        if isinstance(container, list):
            while len(container) <= key:
                container.append(None)
            if container[key] is None:
                container[key] = make()
            return container[key]
        if key not in container:
            container[key] = make()
        return container[key]

    for lf in leaves:
        rel = lf.path[depth:]
        if not rel:
            return reader(lf)
        if root is None:
            root = [] if isinstance(rel[0], int) else {}
        node = root
        for i, k in enumerate(rel[:-1]):
            nxt_is_list = isinstance(rel[i + 1], int)
            node = ensure(node, k, (list if nxt_is_list else dict))
        if isinstance(node, list):
            while len(node) <= rel[-1]:
                node.append(None)
            node[rel[-1]] = reader(lf)
        else:
            node[rel[-1]] = reader(lf)
    return root


# ----------------------------------------------------------------------------------------
# Field catalogue (for docs / browsing)
# ----------------------------------------------------------------------------------------

def describe(template: dict, depth: int | None = None, _indent: int = 0, _out=None) -> list[str]:
    """Human-readable field tree, arrays collapsed to `name[count]`."""
    out = [] if _out is None else _out
    pad = "  " * _indent

    def line(name, node):
        k = node["kind"]
        if k == "record":
            return f"{pad}{name}: {{…{len(node['fields'])} fields}}"
        if k == "array":
            inner = node["elem"]["kind"]
            return f"{pad}{name}[{node['count']}]: {inner}"
        return f"{pad}{name}: {k}"

    if template["kind"] == "record":
        for f in template["fields"]:
            out.append(line(f["name"], f))
            if depth is None or _indent + 1 < depth:
                if f["kind"] == "record":
                    describe(f, depth, _indent + 1, out)
                elif f["kind"] == "array" and f["elem"]["kind"] in ("record", "array"):
                    describe(f["elem"], depth, _indent + 1, out)
    elif template["kind"] == "array":
        e = template["elem"]
        if e["kind"] == "record":
            describe(e, depth, _indent, out)
    return out


# ----------------------------------------------------------------------------------------
# CLI helpers
# ----------------------------------------------------------------------------------------

def load_game_packs(cpk_path: Path = GAME_DT270, schema: Schema | None = None) -> dict[str, tuple[bytes, Pack]]:
    """filename -> (container blob, Pack) for every constant_*.bin in a dt270 CPK."""
    sys.path.insert(0, str(REPO / "tools"))
    import cpk_patch                                # noqa: E402
    from dt270_constants import decode_constant     # noqa: E402
    schema = schema or Schema.load()
    c = cpk_patch.load(cpk_path)
    out = {}
    for f in c.files:
        name = f.path.split("/")[-1]
        if name.startswith("constant_") and name.endswith(".bin"):
            blob = c.read(f.path)
            out[name] = (blob, Pack(decode_constant(blob), schema))
    return out


def find_object(packs: dict, obj: str) -> tuple[str, Pack]:
    for fname, (_blob, pack) in packs.items():
        if obj in pack.names():
            return fname, pack
    sys.exit(f"object {obj!r} not found in any constant file")


def _fmt(v):
    if isinstance(v, float):
        return f"{v:g}"
    return json.dumps(v)


def cmd_list(a) -> int:
    packs = load_game_packs(Path(a.cpk))
    for fname, (blob, pack) in packs.items():
        print(f"{fname}  ({len(pack.raw):,} B, {len(pack.entries)} objects)")
        for name, off, size in pack.entries:
            t = pack.schema.by_object.get(name, "?")
            print(f"    {name:34} {size:6} B  type={t}")
    return 0


def cmd_fields(a) -> int:
    schema = Schema.load()
    tmpl = schema.template_for(a.object)
    if tmpl is None:
        sys.exit(f"unknown object {a.object}")
    for ln in describe(tmpl, a.depth):
        print(ln)
    return 0


def cmd_get(a) -> int:
    packs = load_game_packs(Path(a.cpk))
    _fname, pack = find_object(packs, a.object)
    obj = pack.object(a.object)
    v = obj.get(a.path) if a.path else obj.to_dict()
    print(json.dumps(v, indent=1) if isinstance(v, (dict, list)) else _fmt(v))
    return 0


def cmd_dump(a) -> int:
    packs = load_game_packs(Path(a.cpk))
    out = Path(a.out)
    n = 0
    for fname, (_blob, pack) in packs.items():
        d = out / fname.replace(".bin", "")
        d.mkdir(parents=True, exist_ok=True)
        for name in pack.names():
            if name not in pack.schema.by_object:
                print(f"  skip {name} (no schema)")
                continue
            (d / f"{name}.json").write_text(json.dumps(pack.object(name).to_dict(), indent=1), encoding="utf-8")
            n += 1
    print(f"wrote {n} objects under {out}")
    return 0


def cmd_verify(a) -> int:
    """Round-trip gate: every object parses, to_dict -> apply_dict changes nothing, and the
    pack re-encodes to Konami's exact container bytes."""
    sys.path.insert(0, str(REPO / "tools"))
    from dt270_constants import encode_constant    # noqa: E402
    packs = load_game_packs(Path(a.cpk))
    bad = 0
    total = 0
    for fname, (blob, pack) in packs.items():
        before = pack.payload()
        for name in pack.names():
            if name not in pack.schema.by_object:
                print(f"  {fname}/{name}: NO SCHEMA"); bad += 1; continue
            obj = pack.object(name)
            d = obj.to_dict()
            changed = obj.apply_dict(d)
            unreadable = sum(1 for lf in obj.leaves() if not lf.writable)
            total += 1
            if changed:
                print(f"  {fname}/{name}: apply_dict changed {changed} leaves — NOT idempotent"); bad += 1
            if unreadable and a.verbose:
                print(f"  {fname}/{name}: {unreadable} leaves outside emitted data (expected for truncated arrays)")
        if pack.payload() != before:
            print(f"  {fname}: payload mutated by read/apply round trip"); bad += 1
        if encode_constant(pack.payload(), blob, level=9) != blob:
            print(f"  {fname}: re-encode is not byte-identical to Konami's container"); bad += 1
    print(f"verified {total} objects in {len(packs)} files: {'OK' if not bad else f'{bad} PROBLEMS'}")
    return 1 if bad else 0


# One-line descriptions for the catalogue (hand-written; objects without one show blank).
DESCRIPTIONS = {
    "ballplayer": "player locomotion tables: turn/touch motion-matching data (TurnData[1440], touch0[7]) + Feint",
    "ball": "ball physics: drag, magnus, spin decay, bounce/friction — the [6] arrays are per pitch condition",
    "shoot": "shot power/height gauges per shot type (normal/control/powerful) and distance, loop / advance-loop shots",
    "trap": "first-touch behaviour: reaction, reach, cancel/blend frames, defensive trap, ball-force-direct",
    "grounderpass": "ground pass model: receive speeds, lob, manual-blend gauges, pass assist level",
    "flypass": "lofted pass model", "throughpass": "through-ball model", "centering": "cross model",
    "passget": "pass receiving / interception: natural pass-get, input move, defence, trap-stop thinking",
    "moveMatching": "locomotion: acceleration / deceleration / rotation speed per movement route[14] + animation matching weights",
    "basePosition": "TEAM SHAPE AI: defensive line, compactness, width, pressing/retreat distances, set-piece shapes",
    "rating": "post-match rating formula: per-action coefficients[10], bonuses, position rates, min/max",
    "cameraInplay": "in-play camera rig: move area, margins, wide camera, drop-point display",
    "mlScreenShot": "Konami-internal screenshot capture patterns",
    "modeMatchup": "Match-up mode: player / restart position tables",
    "userPlayTendencyTest": "user play-tendency measurement thresholds",
    "animeAgingDribble": "animation-aging test harness (dribble)", "animeAgingFreeMove": "animation-aging test harness (free move)",
    "animeAgingKick": "animation-aging test harness (kick)", "animeAgingTrap": "animation-aging test harness (trap)",
    "setplayGuideCommon": "set-piece guide (common)", "setplayGuideCornerKick": "corner-kick guide targets",
    "setplayGuideFreeKickFar": "far free-kick guide", "setplayGuideFreeKickMiddle": "mid free-kick guide",
    "setplayGuideFreeKickNear": "near free-kick guide", "setplayGuideGoalKick": "goal-kick guide",
    "ballPersonData": "ball-boy / bench / coach / camera-person placements (default + per stadium st###)",
    "positionNone": "penalty shoot-out positions (positionNone + positionPK_2..5)",
    "demoarea_bill_acl": "pre-match demo / billboard camera areas per stadium and competition",
    "demoarea_custom_st099": "custom-stadium demo area + stadiumCustomParameterData",
    "PathToGlory1": "Path-to-Glory training scenarios", "pathToGlorySetting": "Path-to-Glory tutorial-kind list",
    "SugorokuNone": "Sugoroku mini-game scenarios", "SugorokuSetting": "Sugoroku tutorial-kind list",
    "tutorialNone": "tutorial scenarios (console / mobile lessons)", "tutorialSetting": "tutorial-kind list",
}
CATALOGUE_ORDER = ["basePosition", "ball", "shoot", "trap", "grounderpass", "flypass", "throughpass", "centering",
                   "passget", "moveMatching", "ballplayer", "rating", "cameraInplay", "modeMatchup",
                   "userPlayTendencyTest", "animeAgingDribble", "animeAgingFreeMove", "animeAgingKick",
                   "animeAgingTrap", "setplayGuideCommon", "setplayGuideCornerKick", "setplayGuideFreeKickFar",
                   "setplayGuideFreeKickMiddle", "setplayGuideFreeKickNear", "setplayGuideGoalKick",
                   "ballPersonData", "positionNone", "demoarea_bill_acl", "demoarea_custom_st099", "mlScreenShot",
                   "PathToGlory1", "pathToGlorySetting", "SugorokuNone", "SugorokuSetting", "tutorialNone",
                   "tutorialSetting"]


def count_leaves(node: dict) -> int:
    k = node["kind"]
    if k == "record":
        return sum(count_leaves(f) for f in node["fields"])
    if k == "array":
        return node["count"] * count_leaves(node["elem"])
    return 1


def cmd_catalogue(a) -> int:
    """Regenerate docs/dt270-fields.md from the schema + installed pack."""
    packs = load_game_packs(Path(a.cpk))
    schema = Schema.load()
    file_of = {n: fname for fname, (_b, pack) in packs.items() for n in pack.names()}
    order = CATALOGUE_ORDER + [t for t in schema.types if t not in CATALOGUE_ORDER]
    order = [t for t in order if t in schema.types]
    gen = schema.meta.get("generated", "?")
    lines = [f"# dt270 field catalogue (generated {gen} from the installed exe/pack)", "",
             "Generated by `python tools/dt270_objects.py catalogue` (schema from `tools/dt270_schema_gen.py`).",
             "Every object in `dt270_console_all.cpk → common/match/constant/*.bin`, with its field tree to",
             "depth 2 (arrays collapsed to `name[count]`, nested records to `{…n fields}`). Use",
             "`python tools/dt270_objects.py fields <object>` for the full tree and",
             "`python tools/dt270_objects.py get <object> <path>` for live values.", "",
             "| file | object(s) | type | leaf params | what it is |", "|---|---|---|---|---|"]
    total_objs = total_leaves = 0
    for tname in order:
        t = schema.types[tname]
        n = count_leaves(t["template"])
        mem = t["members"]
        total_objs += len(mem)
        total_leaves += n * len(mem)
        ms = mem[0] if len(mem) == 1 else f"{mem[0]} (+{len(mem) - 1} more)"
        lines.append(f"| {file_of.get(mem[0], '?')} | {ms} | {tname} | {n:,} | {DESCRIPTIONS.get(tname, '')} |")
    lines += ["", f"Total: {total_objs} objects, {total_leaves:,} leaf parameters.", ""]
    for tname in order:
        t = schema.types[tname]
        mem = t["members"]
        lines.append(f"## {tname}  ({t['group']}, {len(mem)} object{'s' if len(mem) > 1 else ''}: "
                     f"{', '.join(mem[:6])}{'…' if len(mem) > 6 else ''})")
        lines += ["", "```"] + describe(t["template"], 2) + ["```", ""]
    Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {a.out} ({len(lines)} lines, {total_leaves:,} leaf parameters)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpk", default=str(GAME_DT270), help="dt270 CPK to read (default: installed game)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("fields"); p.add_argument("object"); p.add_argument("--depth", type=int, default=None)
    p = sub.add_parser("get"); p.add_argument("object"); p.add_argument("path", nargs="?")
    p = sub.add_parser("dump"); p.add_argument("--out", default=str(REPO / "build" / "dt270_json"))
    p = sub.add_parser("verify"); p.add_argument("--verbose", action="store_true")
    p = sub.add_parser("catalogue"); p.add_argument("--out", default=str(REPO / "docs" / "dt270-fields.md"))
    a = ap.parse_args()
    return {"list": cmd_list, "fields": cmd_fields, "get": cmd_get, "dump": cmd_dump, "verify": cmd_verify,
            "catalogue": cmd_catalogue}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
