#!/usr/bin/env python3
"""
flow_patch.py — rewire eFootball's menu flow so the game boots straight into a match.

The menu flow is DATA: 1,134 JSON nodes in cpk/dt250_console_all.cpk and dt251_console_all.cpk,
one file per node, named sha256(upper("common/script/flow/<Node>.json")), each a WESYS-zlib
container holding {"events": {<event>: {"to": <Node>, "go": "forward|backward", ...}}, "data":
{"type": "menu|process|group", ...}}. A menu node waits for the player; a process node fires
"proceed" by itself; a group node runs its "inner" flow and fires "end" when it finishes. The
game reads a node's file when it enters the node, so changing an event's "to" is all it takes
to skip a screen — no code is touched (mapped 2026-09-15; see docs/menu-flow.md).

    python tools/flow_patch.py show  Intro/IntroEnd Exhibition/ExhibiFlowInit   # a node's events
    python tools/flow_patch.py build [--spec tools/data/flow/autoplay.json] [--out build/flow_patch]
    python tools/flow_patch.py install [--out build/flow_patch]      # copy into the game (game closed)
    python tools/flow_patch.py restore                               # put the originals back
    python tools/flow_patch.py status                                # which copy is installed

A spec is a list of edits: {"node": "Intro/IntroEnd", "event": "proceed", "to": "Exhibition/..."},
optionally "go". Every edit names an existing node and event; the target must be a node that
exists. Writes go through cpk_patch.build (TOC round-trip gate, byte-identical untouched files)
and the WESYS container comes from the vendored Sider packer. Originals are kept in
build/backups/cpk/*.orig before the first install; `restore` copies them back.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import cpk_patch  # noqa: E402
import kit_codec  # noqa: E402
import steam_paths  # noqa: E402

ARCHIVES = ("dt250_console_all.cpk", "dt251_console_all.cpk")
DEFAULT_SPEC = REPO / "tools" / "data" / "flow" / "autoplay.json"
DEFAULT_OUT = REPO / "build" / "flow_patch"
BACKUPS = REPO / "build" / "backups" / "cpk"


def node_hash(name: str) -> str:
    return hashlib.sha256(f"common/script/flow/{name}.json".upper().encode()).hexdigest()


def game_cpk_dir() -> Path:
    game = steam_paths.efootball_dir()
    if not game:
        sys.exit("eFootball folder not found — set ML_EFOOTBALL_DIR or build/efootball_dir.txt")
    return Path(game) / "cpk"


class Flow:
    """Every node of both archives, decoded, plus where each came from."""

    def __init__(self, cpk_dir: Path):
        self.cpk_dir = cpk_dir
        self.raw: dict[str, tuple[str, bytes]] = {}       # hash -> (archive, container bytes)
        for arc in ARCHIVES:
            # a build folder only holds the archives it changed; the rest are the game's
            path = cpk_dir / arc if (cpk_dir / arc).exists() else game_cpk_dir() / arc
            archive = cpk_patch.load(path)
            for f in archive.files:
                self.raw[f.path.lower()] = (arc, archive.read(f.path))
        self.nodes: dict[str, dict] = {}                    # hash -> json
        for h, (arc, data) in self.raw.items():
            try:
                _, payload = kit_codec.decode_container(data)
                self.nodes[h] = json.loads(payload.decode("utf-8"))
            except Exception:
                pass
        # name every node that some edge points at (the hash is one-way; names come from edges)
        self.names: dict[str, str] = {}
        for j in self.nodes.values():
            for v in j.get("events", {}).values():
                if isinstance(v, dict) and v.get("to"):
                    self.names[node_hash(v["to"])] = v["to"]
        self.names[node_hash("ProcRoot")] = "ProcRoot"

    def get(self, name: str) -> dict:
        h = node_hash(name)
        if h not in self.nodes:
            raise SystemExit(f"no such flow node: {name}")
        return self.nodes[h]

    def show(self, name: str) -> None:
        j = self.get(name)
        arc = self.raw[node_hash(name)][0]
        print(f"{name}  [{arc}]  {json.dumps(j.get('data'))}")
        for e, v in j.get("events", {}).items():
            if isinstance(v, dict):
                print(f"    {e:32s} -> {v.get('to') or '(end of group)'}  ({v.get('go')})")


def apply_spec(flow: Flow, spec: list[dict]) -> dict[str, tuple[str, bytes]]:
    """Return {hash: (archive, new container bytes)} for every node the spec changes."""
    changed: dict[str, dict] = {}
    for edit in spec:
        node, event, to = edit["node"], edit["event"], edit["to"]
        h = node_hash(node)
        j = changed.get(h) or json.loads(json.dumps(flow.get(node)))
        ev = j.get("events", {})
        if event not in ev or not isinstance(ev[event], dict):
            raise SystemExit(f"{node} has no event '{event}' (has {list(ev)})")
        if to and node_hash(to) not in flow.nodes:
            raise SystemExit(f"{node}[{event}] -> {to}: target node does not exist")
        before = ev[event].get("to")
        ev[event]["to"] = to
        if "go" in edit:
            ev[event]["go"] = edit["go"]
        changed[h] = j
        print(f"  {node}[{event}]: {before} -> {to}" + (f" ({edit['go']})" if "go" in edit else ""))
    out = {}
    for h, j in changed.items():
        arc, original = flow.raw[h]
        key_nibble = original[1] & 0x0F if original[:1] == b"\xff" else 2
        payload = json.dumps(j, indent=1).encode("utf-8")
        container = kit_codec._wesys.pack_wesys_container(payload, key_nibble=key_nibble, compression_level=6)
        # the vendored unpacker must read back exactly what we meant, or nothing is written
        if kit_codec._wesys.unpack_wesys_payload(container) != payload:
            raise SystemExit(f"WESYS round-trip failed for {flow.names.get(h, h)}")
        out[h] = (arc, container)
    return out


def build(cpk_dir: Path, spec_path: Path, out_dir: Path) -> list[Path]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    flow = Flow(cpk_dir)
    print(f"{len(flow.nodes)} flow nodes; applying {len(spec)} edits from {spec_path.name}:")
    changed = apply_spec(flow, spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for arc in ARCHIVES:
        mine = {h: c for h, (a, c) in changed.items() if a == arc}
        if not mine:
            continue
        tree = out_dir / "tree" / arc
        shutil.rmtree(tree, ignore_errors=True)
        tree.mkdir(parents=True)
        for h, container in mine.items():
            (tree / h).write_bytes(container)
        out = out_dir / arc
        r = cpk_patch.build(cpk_dir / arc, tree, out)
        print(f"built {out.name}: {r['patched']} of {r['files']} files patched, {r['base_size']:,} -> {r['out_size']:,} bytes")
        built.append(out)
    return built


def game_running() -> bool:
    import subprocess
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq eFootball.exe", "/NH"], capture_output=True, text=True)
    return "eFootball.exe" in r.stdout


def install(cpk_dir: Path, out_dir: Path) -> None:
    if game_running():
        sys.exit("eFootball is running — close it first (the archives are locked while it runs)")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    for arc in ARCHIVES:
        src = out_dir / arc
        if not src.exists():
            continue
        orig = BACKUPS / f"{arc}.orig"
        if not orig.exists():
            shutil.copy2(cpk_dir / arc, orig)
            print(f"backed up {arc} -> {orig}")
        shutil.copy2(src, cpk_dir / arc)
        print(f"installed {arc}")


def restore(cpk_dir: Path) -> None:
    if game_running():
        sys.exit("eFootball is running — close it first")
    for arc in ARCHIVES:
        orig = BACKUPS / f"{arc}.orig"
        if orig.exists():
            shutil.copy2(orig, cpk_dir / arc)
            print(f"restored {arc}")
        else:
            print(f"no backup for {arc}; nothing to restore")


def status(cpk_dir: Path, out_dir: Path) -> None:
    for arc in ARCHIVES:
        live = hashlib.sha256((cpk_dir / arc).read_bytes()).hexdigest()
        orig = BACKUPS / f"{arc}.orig"
        patched = out_dir / arc
        what = "unknown"
        if orig.exists() and hashlib.sha256(orig.read_bytes()).hexdigest() == live:
            what = "ORIGINAL"
        elif patched.exists() and hashlib.sha256(patched.read_bytes()).hexdigest() == live:
            what = "PATCHED (this build)"
        elif not orig.exists():
            what = "original (no backup taken yet)"
        print(f"{arc}: {what}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpk-dir", default=None, help="eFootball\\cpk (default: the installed game)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show"); p.add_argument("nodes", nargs="+")
    p = sub.add_parser("build"); p.add_argument("--spec", default=str(DEFAULT_SPEC)); p.add_argument("--out", default=str(DEFAULT_OUT))
    p = sub.add_parser("install"); p.add_argument("--out", default=str(DEFAULT_OUT))
    sub.add_parser("restore")
    p = sub.add_parser("status"); p.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    cpk_dir = Path(a.cpk_dir) if a.cpk_dir else game_cpk_dir()
    if a.cmd == "show":
        flow = Flow(cpk_dir)
        for n in a.nodes:
            flow.show(n)
    elif a.cmd == "build":
        build(cpk_dir, Path(a.spec), Path(a.out))
    elif a.cmd == "install":
        install(cpk_dir, Path(a.out))
    elif a.cmd == "restore":
        restore(cpk_dir)
    else:
        status(cpk_dir, Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
