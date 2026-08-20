# Driving Cheat Engine agentically — protocol + research playbook

The goal: let an agent do all the memory reverse-engineering (map the per-player stats struct,
grab the runtime AES key, hunt the rating fields) **without clicking around Cheat Engine's GUI**.
We do that by running CE's Lua engine as a file-driven command server.

## Architecture

```
   agent  ──writes──▶  build/ce/cmd.txt   ──polled by──▶  ce_bridge.lua (inside Cheat Engine)
   agent  ◀──reads───  build/ce/result.json ◀──written──   (executes op, JSON reply)
```

- CE does the heavy lifting (C-speed value scans, AOB scans, struct reads) — far better than
  our pure-Python `mem_scan.py` for the correlation grind.
- The agent only reads/writes two files. No screenshots, no GUI automation, deterministic.
- READ-ONLY by default (`ALLOW_WRITES=false` in the Lua) — the stats research never writes.

## Setup (once)

1. Launch eFootball; get to a match / the point where the value you want exists.
2. Open Cheat Engine (already running as admin via the desktop app).
3. Table → **Show Cheat Table Lua Script** → paste `tools/ce_bridge.lua` → **Execute Script**.
   It prints `CE bridge running… Attached pid=…` and writes a `startup` result. Done — leave it.
4. The agent now issues commands via `python tools/ce_cmd.py <op> key=value …` (one round-trip
   each) or by writing `build/ce/cmd.txt` directly.

## Command reference

| op | args | returns |
|---|---|---|
| `ping` | — | attached?, pid |
| `open` | — | (re)attach to eFootball.exe |
| `modules` | — | module bases + sizes (to express addrs as module+offset) |
| `firstscan` | `type=float\|i32\|…` `value=` | candidate count for that value |
| `nextscan` | `value=` | count after filtering survivors to the new value |
| `list` | `max=` | the surviving addresses |
| `read` | `addr=` `type=` | one value |
| `readstruct` | `addr=` `size=` | region dumped as (offset, i32, f32) rows — the struct dissector |
| `aob` | `pattern=48 8B 05 ?? ??` | addresses matching the byte signature |
| `snapshot` | `addrs=a,b,c` `type=` | current values at those addresses (watch over time) |
| `write` | `addr=` `value=` `type=` | disabled unless ALLOW_WRITES=true |

## Playbook A — map the per-player match-stats struct (the main prize)

The rating shown at full time proves the counters exist in memory. Correlate on it.

1. **Attach & confirm:** `ping` → expect `attached:true`. If not, `open`.
2. **Anchor on a rating.** At (or near) full time a player shows e.g. `7.5`.
   `firstscan type=float value=7.5` → expect thousands of hits.
3. **Narrow.** Pick a player whose rating differs, or start a new match and read a different
   rating, then `nextscan value=6.5`. Repeat 2–3×. Survivors collapse to the rating fields.
   `list max=40` to see them.
4. **Find the array stride.** The 22 players are almost certainly an array of identical structs.
   Among survivors, look for addresses spaced by a constant delta — that delta is the **stride**
   and the lowest is near the **base**. `readstruct addr=<base> size=<stride>` dumps one player.
5. **Label the offsets.** With `readstruct`, note which offsets hold plausible counters
   (small ints that grow). To confirm `passes_completed`: deliberately complete ~10 passes with
   that player, `readstruct` again, and see which offset jumped by ~10. Repeat for attempts,
   tackles, shots, distance. Record offset→stat in `build/stats_map.json`.
6. **Stabilise.** Absolute addresses move each launch. Either (a) `aob` a signature of the bytes
   just before the array and store base = signature±delta, or (b) express base as
   module+offset via `modules`. Save that anchor to `build/stats_map.json`.
7. Hand the map to `tools/stats_read.py` (Phase 2, built next) which reads all 22 structs into
   `match_player_stats` every match — real pass completion, tackle %, shot accuracy per player.

## Playbook B — runtime AES key (already recovered, kept as a CE self-test)

The global IoStore key is known (`iostore_read.py` verified it). To re-derive at runtime as a
bridge sanity check: `aob` the first 16 bytes of the known key; a single hit confirms the bridge
reads memory correctly. Not needed for research, useful to validate the setup.

## Playbook C — find where the rating is computed (stretch, needs the debugger)

To learn WHICH stats feed the rating and their weights (not just the values), you'd set a
"find what writes this address" breakpoint on a rating field and read the disassembly. That is
debugger territory (CE's `debug_setBreakpoint` / "Find out what writes") and anti-debug on the
protected exe may interfere — attempt only after Playbook A works, and expect it to be the
hardest step. Reading the values (Playbook A) does not need this.

## Safety

- Read-only: the bridge refuses writes unless explicitly enabled. The research needs no writes.
- Your own offline install; nothing is uploaded; no game files are modified.
- If a game patch shifts offsets, re-run Playbook A step 6 (the signature anchor minimises this).
