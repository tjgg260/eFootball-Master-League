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

## The `dxgi.dll` proxy runtime — now permitted (2026-08-21)

Originally we vendored only Sider's offline file-format code and deliberately left out its
`dxgi.dll` proxy runtime, on account-risk grounds. That restriction is **lifted** by the owner's
informed decision: this is offline single-player on an owned copy, the owner is not playing
online, and accepts the ban risk. Sider runtime injection — LiveCPK file serving and lua hooks —
is now allowed, and can replace CPK repacking as the delivery path.

Note the runtime is still **not committed to this repo**: it is obtained from the upstream Sider
distribution and run locally. Only the offline file-format files above are vendored here (their
GPL-3.0 is why the repo is GPL-3.0); the runtime is used, not redistributed by us.

## Fragility

The keys are hardcoded and Konami rotates them — that is what broke the older PES-era tooling.
When a patch lands, expect `prove_round_trip()` in `ml_apply.py` to fail loudly rather than
write a corrupt file. That failure is the designed behaviour, not a bug.
