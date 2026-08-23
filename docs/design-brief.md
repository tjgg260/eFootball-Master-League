# Design Brief — Master League companion app

## What it is

A desktop companion app that restores a **persistent Master League career** to eFootball 2027
(PC/Steam). You manage a club across seasons — squad, tactics, transfers, finances, youth, board
objectives — and *play the actual matches inside eFootball*. The app simulates the whole football
world; eFootball is the pitch.

**One-line pitch:** Football Manager's depth of world + eFootball's on-pitch fidelity, stitched
together by a companion that writes your league into the game each time you kick off.

## The core idea a designer must internalise

- **The app's database is an unbounded football world** — 109,000+ players, 4,975 clubs, 440+
  competitions with real rules, managers, squads, finances. Nothing is capped by the game.
- **eFootball is a per-match render target.** When you launch a fixture, the app authors *just
  that match's two squads* (real names, attributes, skills, playstyles, faces) into the game, you
  play it, and results come back. The user never edits the game directly — they manage in the app.

So the app is where the user *lives*. It has to feel like a premium football-management product,
not a database front-end. Right now it's functional but plain — that's the gap to close.

## Tech + constraints (design must be buildable here)

- **Avalonia UI on .NET 8** (XAML, MVVM via CommunityToolkit.Mvvm). Designs need to be expressible
  in Avalonia XAML — flex/grid layouts, styles, control templates, data templates, vector paths,
  gradients, bitmaps. No web/React.
- **Dark theme**, desktop, typically maximised (~1280–1920 wide).
- Assets we have: real club **crests**, some **kits**, RFS **player photos** (~12k), generated
  skin/hair **avatars** for the rest, league/nation data. (No live 3D face renders — those stay in
  eFootball.)
- Everything is local/offline. Fast.

## Current screens (the surface to redesign)

~20 screens. Most are **inline DataTemplates inside one 800-line MainWindow** — mostly DataGrids
and TextBlocks, crests on only a few screens. The dedicated views are Dashboard, Squad, Tactics.

| Screen | What it does | Current state |
|---|---|---|
| **Dashboard** | next match, form, morale, news ticker, quick actions | busiest screen; a grey monospace status blob mixes logs + results |
| **Squad / Lineup** | formation pitch, XI + bench, player detail panel, drag-to-reposition | **see pain point #3** — huge empty space below |
| **Tactics** | team playstyle picker (Possession/Counter/Long Ball/Out Wide/Overload…), formation, per-player role | **see pain points #1–2** |
| **Market** | transfers, listed players, offers | data grid |
| **Inbox** | news, board messages, events | list; no detail view, no unread badge |
| **Academy / Youth** | intake, prospects, potential | grid |
| **Table / Stats / History** | league tables, stat leaders, past seasons | text grids, **no charts anywhere** |
| **Finances / Bank / Board** | budget, wages, objectives, confidence | numbers, no visual identity |
| **Staff / Scouting / Training / Cup / Calendar / Settings** | supporting screens | mostly grids/forms |

## Three specific things to build (this is the trigger for the redesign)

**1. Team-playstyle descriptions — fill the gaps.** The Tactics tab shows each Team Playstyle with
an in/out-of-possession description pulled from the game files. Some (e.g. **Overload**) have no
description in the PC files because Konami serves that text online. We now have the text; the
design should present each playstyle as a rich, readable card. For reference, the six styles are:
Possession Game, Quick Counter, Long Ball Counter, Long Ball, Out Wide, **Overload** — the last
being *"players shift to the ball side to create passing overloads in attack (numerical
superiority, easy short passes, keep possession in tight spaces) and apply aggressive gegenpressing
when possession is lost — a Possession + Quick-Counter hybrid."*

**2. Animated playstyle diagrams — build them natively.** eFootball shows a short animation per
playstyle (dots sliding to the ball side, the pressing shape forming). **Scoped:** there is *no*
extractable clip — eFootball keyframes static texture parts (`GamePlanTeamStylePitch`,
`…PlayerRadar` dots, `…Ball`, `…Arrow`) via a UMG WidgetAnimation at runtime. So the design should
create **native looping pitch diagrams in Avalonia** — a small pitch with player dots + ball +
arrows that animate the movement described in each playstyle's text (we have those descriptions).
These become signature animated diagrams, crisp/vector/themeable, one per playstyle. Treat them as
a reusable component: pitch canvas + positioned dots + tweened transitions + directional arrows.

**3. Use the dead space in the Lineup tab.** When you click a player, the left panel shows only his
position + playstyle picker; the **entire lower half of the screen is black**. Fill it with a full
player profile — **everything eFootball shows**: the ability radar/hexagon, all attribute values by
group (offence/defence/GK/physical), the **player skills** list, both **playstyles** (attacking +
defensive), weak-foot, form, condition, age/height/weight, contract, morale. Make selecting a
player open a proper detail surface, not a cramped sidebar.
*eFootball's own layout is a direct reference — its player-detail modal is a radar
(`GamePlanTeamStylePlayerRadar`) plus grouped stat cells (`GamePlanPlayerDetailLeft/Right`,
`…BasicCell_1..4`, compare cells). We hold every value (attributes, 52 skills, both playstyles) in
the DB, so this is layout, not data.*

## Design goals

- **North star:** the polish and warmth of *My Football Legacy*, the information density of Football
  Manager, the visual language of eFootball. Premium, tactile, football-first.
- **Make the data sing.** We have a huge, real world — league tables, form worms, position-over-
  season lines, finance flows, squad depth charts, player radars. Right now it's text grids.
  Charts, crests, faces, kit colours everywhere.
- **A visual identity / component system.** Consistent cards, chips, badges, rating pills (colour by
  tier), condition/morale gauges, a real post-match report screen, a proper inbox master-detail.
- **Kill the monospace blob.** Compile logs → a collapsible debug drawer; results/news → designed
  surfaces.
- **Every screen its own View.** Break the 800-line MainWindow into per-screen views with shared
  styles.

## What we'd love from the design pass

1. A **visual system**: palette (dark, football-premium), type scale, spacing, the core components
   (player card, rating pill, crest badge, gauge, stat radar, chip, chart frame).
2. Reimagined **Dashboard**, **Squad/Lineup + player profile** (ask #3), and **Tactics** (asks #1–2)
   as the three flagship screens.
3. A pattern for **charts** (form, league position, finances) and for **post-match reports**.
4. Ideas that use what we uniquely have: real crests, kits, RFS photos, avatars, and the fact that
   this is a *living* world the user shapes across seasons.

Keep it buildable in Avalonia. Prioritise the three flagship screens; the rest can inherit the
system.
