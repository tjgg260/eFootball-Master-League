# dt270 gameplay constants — format map and tuning pipeline

The gameplay "feel" of eFootball lives in `dt270_console_all.cpk` → `common/match/constant/*.bin`,
a separate pack from the dt200 roster data (no overlap — a gameplay mod and our Master League
roster/tactics can coexist).

## Format (mapped, tooling proven)

- Each `constant_*.bin` is a WESYS container holding **plain zlib** — no encryption, regardless of
  the `0xFF` header byte. `tools/dt270_constants.py` decodes and re-packs every variant.
- Tables are **Q2.14 fixed-point multipliers** (`16384` = ×1.0, `81920` = ×5.0).
- `constant_team.bin` (mod-era: 817 words) — team-behaviour scalars: tempo, line height,
  pressing, physicality. EVO_GP_HEAVY's signature is a param block at offsets **820–832** that is
  `0` (disabled) in every other pack and ×1.0 (enabled) in EVO.
- `constant_match.bin` — global match rules; `constant_player.bin` — per-behaviour scalars;
  `constant_ballPerson.bin` — ball physics; `constant_shootAging.bin` — shooting/aging.
- `mob_anime_control.txt` — plain CSV of crowd/bench reaction animations, trivially editable.

## Version families (critical)

`constant_match.bin` decoded size fingerprints the game patch a pack targets:

| pack | family | notes |
|---|---|---|
| EVO_GP_HEAVY, raw dt270 sample | 10622 | v6-era |
| GabeLogan, BromiV21 | 11904/11912 | adjacent patch |
| **installed game (2026-08-19)** | **9968** | newer patch; `constant_team` restructured 3270 → **912** |

**A family mismatch installs cleanly and misbehaves silently.** The current Konami patch
restructured the tables (team 3270→912, ballPerson ~300K→349K), so **none of the older mod packs
are safe on it** — only `constant_positionPK.bin` kept its layout. Gameplay mods must be rebuilt
per patch by their authors; the same is true of any custom tuning we author.

## Tooling: `tools/gameplay_tune.py`

    python tools/gameplay_tune.py status                 # family check: what's safe to install
    python tools/gameplay_tune.py install --mod evo      # install (refuses family mismatch)
    python tools/gameplay_tune.py blend --mod evo --amount 0.5   # mod at half strength
    python tools/gameplay_tune.py restore                # back to the pristine original

`blend` interpolates every changed word between your original constants and the mod's — a
strength dial no mod pack offers. First install keeps a `PRISTINE` backup for `restore`.

## Open research

Semantic labels for individual words (which offset = sprint speed, which = pressing radius) are
version-specific and only recoverable by A/B testing in-game per patch. The structure, encoding,
fixed-point format, and family detection above are stable knowledge; the per-word map churns with
every Konami patch and is deliberately not hard-coded anywhere.

## Family-9968 self-calibration protocol (P4, 2026-08-20)

The bundled mods (EVO/GabeLogan/Bromi) target older layouts and are family-blocked. The path
to gameplay control on the CURRENT patch is A/B testing our own pack:

1. `python tools/gameplay_tune.py selftest` — installs a byte-identical re-encode of the
   game's own constants (round-trip gated). Boot, play a kickoff, `restore`. Proves the
   write path with zero gameplay risk. **Not yet run — needs an in-game session.**
2. `python tools/gameplay_tune.py scale --file constant_ballPerson --factor 0.9` — scales
   every plausible Q2.14 word of ONE file. Play ~10 min, then
   `... log --note "constant_ballPerson x0.9: <what changed>"` and `restore`.
3. Repeat per file (`constant_team`, `constant_player`, `constant_match`) and direction
   (0.9 / 1.15). Verdicts accumulate below as the family-9968 semantic map; presets and the
   per-match dt270 build on whatever this maps.

Safety: `capture` records the pristine SHA-1 (build/dt270_pristine.sha1); every write is
guard-checked against pristine-or-last-install, in-place slot patch only, PRISTINE +
timestamped backups, never while the game runs.

### Calibration verdicts (family 9968)

## Cross-pack diff study (2026-08-20, all five packs)

Packs: installed (family 9968), repo raw + EVO (10622), GabeLogan (11904), Bromi (11912).

**Patch-stable files** (byte-identical installed vs mod-era, layouts survived):
pathToGlory, positionPK, sugoroku, all three tutorials. None are gameplay levers; none were
touched by any mod.

**The four gameplay files (team/match/player/ballPerson) all restructured across patches** —
sizes differ everywhere (team 3270→912, ballPerson 315→349K). Value-fingerprint transfer of
mod changes into family 9968 FAILED (only degenerate filler runs match): old word indices
are dead on the current patch. In-game bisection (scale --start/--end) is the only path to
9968 semantics.

**What the mods agreed on (old constant_team layout, 817 words)** — the consensus cluster
changed by EVO AND GabeLogan AND Bromi, i.e. the words the modding community identified as
the gameplay knobs:
- word 131: base 49.01 → EVO 41.01 (x0.84), Bromi 41.01 (x0.84), GabeLogan 5.01 (x0.10!).
  One big scalar every "realism/slower" mod reduces — the prime TEMPO/SPEED suspect.
- word 122: 52430.996 → 2.996 in all three (identical value) — a feature gate/sentinel all
  mods disable the same way.
- words 123-125, 133, 164-170, 193: small nudges to ~1.0 and ~5.0 multipliers (±0.5-2%) —
  fine-tuning scalars.
- EVO only: word 155 (8.0 → 12.0), word 160 (40.98 → 32.98) — part of its HEAVY identity.
- constant_match consensus: EVO doubles word 189 (396 → 792) and rewrites threshold-looking
  words (many ±52428/±104856 sentinel-valued words flipped) — rule/flag territory, higher
  risk to probe blind.
- Sentinel values ±858980352 (=52428.0 Q2.14) and ±1717960704 (=104856.0) recur across all
  files — engine on/off or "unset" markers, not scalars; the scale probe's magnitude filter
  (1024..262144) correctly skips them.

**Implication for the 9968 hunt:** the old layout had ~one dominant reduced-by-everyone
scalar (49.0) among small multipliers. When bisecting the new 228-word constant_team, look
for a lone ~40-50 Q2.14 value — scan shows candidate words listed by
`python -c "…"` (values 40-56 in the installed table) — probe those words FIRST before
blind halving.

**Family-9968 constant_team landscape (scan):** 228 words = 156 sentinel-valued + 22 zeros +
47 small (<0.5) + one 0.5-2.0 + two 4.016s. The old layout's tempo-suspect 49.0 scalar and
its cluster of ~1.0/~5.0 multipliers are GONE from constant_team — the current patch moved
the team-behaviour scalars elsewhere. REVISED probe order for the calibration evening:
  1. constant_match  x0.9   (9,968 B — closest inheritor of the old scalar mass; AI
                              behaviour/rules — the AI-build-up-speed prime suspect)
  2. constant_player x0.9   (individual action scalars)
  3. constant_ballPerson x0.9  (ball feel)
  4. constant_team last     (mostly flags/ids now; scaling it should do little — a useful
                              control probe)
