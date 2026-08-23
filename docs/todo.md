# TODO — started but not completed

Snapshot of open threads (as of this session). ✅ = done, 🟡 = partial, ⬜ = not started.

## Portraits / faces
- ⬜ **Wire up the SortitoutSI cutout facepack** (`sortitoutsi_cutout_megapack_2026.08.rar`, 15.8 GB) —
  real 2D player portrait PNGs, the practical answer to tier-1/2 portraits.
  - Needs an extractor (7-Zip/WinRAR — not on the CLI here).
  - Map images → our players. SortitoutSI cutouts are named by FM/UID; we map by name (like RFS).
  - Populate `players.real_face_path` (the reserved column) → feeds the portrait resolver directly.
- 🟡 **Portrait resolver** built (`SessionPortrait.cs`: real-face → RFS → generic avatar). Wired into
  Squad + inbox; tier-1 slot still empty until the facepack lands.
- ⬜ eFootball 3D face render → portrait: **declined** (needs a 3D renderer). Faces are runtime
  renders, no stored 2D source. Facepack supersedes this need.

## Playstyles
- ✅ All names + writeback codes (20 offensive + 16 defensive/GK), data-confirmed via `all.str`.
- 🟡 **Descriptions for the new v6.0.0 defensive styles** (Pass Disruptor, Front Line Pressure,
  Front Line Poacher, All-action Defender, High Line Master, Covering Role, Tough Marker, Deep
  Defender, Press Back, Attack Outlet, Sweeper GK, Build-up GK, High Line GK). Core 22 have text in
  `all.str`; these newer ones ship none on PC (like Overload) → **source online**.

## Design uplift (the big track)
- ✅ Design brief ([docs/design-brief.md](design-brief.md)); ✅ Overload description wired in;
  ✅ tactics-animation feasibility scoped (build native, not extract).
- ✅ Received design output — "Organic" design system + animated tactics scene ([design/tactanim](../design/tactanim)).
- ⬜ **Decision pending:** adopt "Organic" warm theme app-wide, or keep dark + use for tactics surfaces.
- ⬜ **Port design system → Avalonia** (tokens: colours, radii, Caprasimo/Figtree fonts, spacing,
  components) as the app's visual language.
- ⬜ **Ask #2 — native Avalonia animated pitch control**, keyframe-driven per playstyle (Long Ball
  Counter first). The JSX scene is the spec.
- ⬜ **Ask #3 — player profile panel**: fill the Lineup dead space with everything eFootball shows
  (ability radar, grouped attributes, skills, both playstyles, weak foot, form, condition, contract).
- ⬜ Break the 800-line MainWindow into per-screen views; add charts; post-match report screen; kill
  the grey monospace status blob (from the audit plan).

## Data / world (mostly done, small gaps)
- ✅ Full RFS world imported; ✅ competition membership + standings; ✅ team→league links.
- ✅ Manager→team (nationality-matched **heuristic** — RFS has no real link). 🟡 could improve.
- 🟡 **Competition rules**: team count, rounds, points, relegation ✅; **promotion places,
  league-vs-cup type, tier** not yet decoded from `competformat`.

## Writeback / deploy
- ✅ Per-match authoring writes fully faithful players (attributes, 52 skills, all playstyles).
- 🟡 **dt200 grow-and-resort**: built + round-trip-proven but **not deployed**, and per-match
  authoring is the preferred path — so this is parked unless we want players to persist by real PID.

## Parked / declined (not really TODO, listed for completeness)
- Sider / LiveCPK runtime: cloned `Efootball-Sider` repo; setup blocked by the safety classifier;
  doesn't deliver the live-swap goal anyway. Parked.
- Mid-match playstyle change: needs live memory editing (anti-tamper-resisted). Use eFootball's own
  in-match game-plan menu instead.
- Post-match capture / score OCR automation (from earlier phases): score OCR uncalibrated — separate
  thread, not touched this session.
