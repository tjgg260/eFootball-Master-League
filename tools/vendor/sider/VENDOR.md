# Vendored: eFootball Sider

Source: https://github.com/Master-Antonio/Efootball-Sider
Licence: GPL-3.0
Vendored: 2026-08-19

## Files

| File | Why |
|---|---|
| `wesys.py` | WESYS container decrypt/encrypt. The xorshift stream cipher Konami added in v6.0.0. |
| `pesdb.py` | Record layouts for Player.bin, PlayerAssignment.bin, Team.bin. |
| `PESDB_DATABASE_FORMAT.md` | Author's format notes. |
| `LICENSE` | GPL-3.0, as distributed. |

Downloaded verbatim, unmodified. Do not edit these in place — if a game patch rotates the
keys, re-pull from upstream so the diff stays visible.

## Why this makes the whole repository GPL-3.0

`wesys.py` is linked into `tools/ml_apply.py`, which makes this project a derivative work.
That is a deliberate, informed choice: without this cipher there is no automated writeback at
all, only a manual GUI step in the middle of every apply.

## What we deliberately did NOT take

Sider's `dxgi.dll` proxy runtime. It injects into the game process, and the build plan rules
that out — the account risk is not worth it when a screenshot does the job. Only the offline
file-format code is used here; nothing from this vendor directory runs while the game does.

## Fragility

The keys are hardcoded and Konami rotates them — that is what broke the older PES-era tooling.
When a patch lands, expect `prove_round_trip()` in `ml_apply.py` to fail loudly rather than
write a corrupt file. That failure is the designed behaviour, not a bug.
