"""Agent-facing client for the Cheat Engine bridge (tools/ce_bridge.lua).

Writes a command to build/ce/cmd.txt, waits for the bridge to produce build/ce/result.json,
and prints it. One call = one round-trip, so an agent (or a human) can drive all the memory
research from the terminal without touching Cheat Engine's GUI.

Examples:
  python tools/ce_cmd.py ping
  python tools/ce_cmd.py open
  python tools/ce_cmd.py firstscan type=float value=7.5
  python tools/ce_cmd.py nextscan value=6.5
  python tools/ce_cmd.py list max=40
  python tools/ce_cmd.py read addr=0x1A2B3C4D type=float
  python tools/ce_cmd.py readstruct addr=0x1A2B3C40 size=256
  python tools/ce_cmd.py aob pattern="48 8B 05 ?? ?? ?? ??"
  python tools/ce_cmd.py snapshot addrs=0x1000,0x1040 type=float
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

CE = Path(__file__).resolve().parent.parent / "build" / "ce"
CMD, RESULT = CE / "cmd.txt", CE / "result.json"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    op = sys.argv[1]
    lines = [f"op={op}"] + [a for a in sys.argv[2:] if "=" in a]
    CE.mkdir(parents=True, exist_ok=True)
    # stamp result staleness by mtime so we don't read a previous reply
    prev = RESULT.stat().st_mtime if RESULT.exists() else 0
    CMD.write_text("\n".join(lines), encoding="utf-8")

    deadline = time.time() + 30
    while time.time() < deadline:
        if RESULT.exists() and RESULT.stat().st_mtime > prev and not CMD.exists():
            try:
                data = json.loads(RESULT.read_text(encoding="utf-8"))
            except Exception:
                time.sleep(0.15)
                continue
            print(json.dumps(data, indent=2))
            return 0 if data.get("ok") else 1
        time.sleep(0.2)
    print('{"ok": false, "error": "timeout waiting for CE bridge — is ce_bridge.lua running '
          'in Cheat Engine and attached to eFootball.exe?"}')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
