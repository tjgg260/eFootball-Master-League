# Master League — UX & Design Brief

The complete brief for prototyping and designing every screen in **Claude Design**. We now build
the UI in **HTML/CSS (Blazor Hybrid + WebView2)**, so the UI can be genuinely dynamic and
interactive — animation, charts, drag-and-drop, live-updating surfaces, broadcast-style reveals.
Pair this with the **Floodlit design system** ([floodlit-design-system.md](../floodlit-design-system.md)) — Floodlit is the *how it looks*; this is the *what and why*.

---

## 0. Product in one paragraph

You run a **persistent Master League career** across seasons. The app is the manager's desk; the
matches are played inside **eFootball**. You prepare a fixture (squad, tactics), the app writes it
into the game, you play it, and the result comes back into the app — which advances the world
(table, form, development, transfers, finances, board, youth). It's **Football Manager's depth of
world + eFootball's on-pitch fidelity**, on a second screen beside the game. The database is an
unbounded, deduped world (~95k+ real players with photos, thousands of clubs, real leagues).

---

## 1. Design principles (the UX bar)

1. **The core loop is sacred — remove all friction from it.** Prepare → Play → Import → Review.
   Everything else orbits this. Importing a result must feel like one gesture.
2. **Second-screen ergonomics.** Used *while* eFootball runs. Glanceable, high-contrast, keyboard-
   and controller-friendly, never demanding deep focus mid-match.
3. **Show, don't tabulate.** We have a rich world — render it: form worms, position-over-season
   lines, money flows, player-growth curves, animated tactics, radar charts. Kill grey text grids.
4. **Progressive disclosure.** A screen shows the one thing that matters, then drills down. Never
   dump every column at once; reveal on demand.
5. **One primary action per screen**, stated as a verb, consistent through its flow
   ("Import result" → toast "Result imported").
6. **Emotional payoff.** This is a *story*. Surface milestones, drama, rivalries, wonderkids
   breaking through, deadline-day tension, board verdicts. Make seasons memorable.
7. **Every state designed** — empty ("Generate a season to start"), loading (broadcast wipe),
   error ("Couldn't read the scoreline — crop to the stats screen"), success (count-up + toast).
8. **Identity everywhere** — real crests, kits, and the **player face photos** we extracted.
   A face beside every name; a crest beside every club.

---

## 2. Game systems (what's under the hood — the data each screen renders)

| System | What it models | Surfaces on |
|---|---|---|
| **League engine** | fixtures, results, tables, promotion/relegation, multiple tiers | Season hub, Table, Fixtures |
| **Squad & tactics** | XI + bench, formation (attack/defence shapes), team playstyle, per-player role, both in/out-of-possession playstyles | Squad, Tactics |
| **Matchday I/O** | write fixture → eFootball; import result via screenshot OCR / memory read / manual | Matchday, Import |
| **Development** | potential, per-attribute growth, personality/determination, breakout & decline, ageing | Player, Squad, Training |
| **Transfers & contracts** | valuations, negotiation, rival bids, loans, clauses, wages, expiries, Bosmans, deadline day | Transfers, Player, Finances |
| **Scouting** | attribute masking outside your leagues, scout assignments, shortlists | Scouting, Transfers |
| **Youth / academy** | intake day, prospects, potential ★, graduation | Academy |
| **Finances** | budget (transfer/wage), income/spend, sponsors, board funding | Finances |
| **Board & fans** | objectives with importance tiers, confidence, sacking pressure, reputation, fan happiness | Board, Season hub |
| **Staff** | Director of Football, assistant, coaches, physio, scouts — with tactical-style strengths, delegation | Staff |
| **Cups & continental** | knockout brackets, seeded draws | Cup, Fixtures |
| **World life** | CPU transfers, retirements, free agents, news events, world seed (each save unique) | Inbox, Transfers |
| **History** | past seasons, honours, career arc, records | History, Board |

---

## 3. Jobs to be done (what the user actually wants)

- **JTBD-1 — "Get me into a career fast."** Pick a club/league and start, with a club preview and
  my manager identity, in under a minute.
- **JTBD-2 — "Get my team ready for the next match"** without fighting the UI (pick XI, set the
  tactic, know who's injured/tired).
- **JTBD-3 — "Play the match and get the result in effortlessly."** The moment I finish in
  eFootball, the app should capture score + stats + scorers with minimal typing.
- **JTBD-4 — "Tell me how I'm doing."** At a glance: league position, form, objective progress,
  what needs my attention.
- **JTBD-5 — "Let me build my squad over time"** — sign players, sell, loan, promote youth, watch
  them develop, all with real drama and consequence.
- **JTBD-6 — "Run the club, not just the team"** — finances, board expectations, staff.
- **JTBD-7 — "Make it feel like my story"** — history, milestones, rivalries, memorable seasons.

---

## 4. Key user journeys (design these end-to-end)

**J1 · New career** — choose country → league → club (with crest, squad strength, budget preview) →
manager identity (name, portrait) → confirm → land on the Season hub with an "inbox: welcome" and
the first fixture teed up.

**J2 · Matchday loop (the heartbeat)** — Season hub shows *Next: vs X*. → Pre-match screen (both
XIs, form, injuries, referee, weather line, tactic vs opponent) → "Play in eFootball" (writes the
fixture) → play the game → **auto-import on return** (or drop a screenshot) → **post-match report**
(score reveal, scorers, ratings grid, morale swings, assistant debrief) → Season hub updated
(table, form worm, objective chips).

**J3 · Transfer window** — Inbox flags the window open → Transfers screen (shortlist, market search,
scout reports with masked attributes) → open a player → negotiate (rounds, rival bids, clauses,
wage agreement) → deal confirmed → squad + finances update → deadline-day pressure toward the end.

**J4 · Season rollover** — final matchday → season-end sequence (final table, honours, board verdict
on objectives, reputation change, next-season budget) → summer (retirements, youth intake day,
released players, contract renewals) → new fixtures generated → back to J2.

**J5 · Squad development arc** — over weeks: training focus → player growth (breakout/decline
seasons) → the Player screen shows the growth curve → decisions (renew, sell, promote youth).

**J6 · Off-pitch management** — Board objectives review (mid-season + end), finances (budget
requests, wage constraint), staff hiring (delegate scouting/training).

---

## 5. Screen map

**Shell:** 72px icon rail + persistent match bar (live score bug during import) + content.
**Primary:** Season Hub (home) · Squad · Tactics · Fixtures/Calendar · Table · Transfers · Player
(detail) · Inbox · Finances · Board · Staff · Academy · Scouting · History/Stats · Import result ·
New Career · Settings. **Modals/overlays:** Pre-match, Post-match report, Negotiation, Player
compare, Deadline-day ticker.

---

## 6. Per-screen briefs (for Claude Design — design each of these)

For each: **Purpose/JTBD · Key content · Primary action · Interactions & dynamic elements · States.**
Ask Claude Design for **both Floodlit themes** on every screen.

### 6.1 Season Hub (home)
- **JTBD-4.** The command centre — what's happening and what needs me.
- **Content:** next fixture card (crests, kickoff, competition), league position mini-table (your row
  sticky/highlighted), **form worm** (last 8, animated), objective-progress chips, squad morale &
  fitness gauges, top-3 inbox items, a "in form / out of form" player, money headline.
- **Primary action:** "Go to matchday" (or "Play next fixture").
- **Dynamic:** count-up stats on load; form worm draws in; position line updates with a wipe;
  live match bar if a result is mid-import.
- **States:** pre-first-match (welcome), mid-season (dense), season-end (verdict banner).

### 6.2 Squad
- **JTBD-2/5.** See and manage the whole squad.
- **Content:** the Floodlit squad table (face · name · position pill · age · overall · **growth
  arrow** · form chips · condition dot · contract · status), filters (position, age, status),
  sort. Side/lower panel = selected player summary.
- **Primary action:** open Player / set lineup.
- **Dynamic:** click-to-select opens the player profile in the *dead space below* (see 6.9);
  sortable headers (solid triangle); condition/morale animated gauges; growth deltas coloured.
- **States:** injured/suspended flags, loan-listed, transfer-listed.

### 6.3 Tactics
- **JTBD-2.** Define how the team plays.
- **Content:** **animated pitch** showing the selected **team playstyle** (Possession / Quick
  Counter / Long Ball Counter / Long Ball / Out Wide / Overload) as a looping diagram of player
  movement (in & out of possession) — built natively (we have the movement text per style);
  formation picker (attack + defence shapes / fluid toggle); per-player role with **both playstyles
  (attacking + defending)**; opponent-aware suggestion.
- **Primary action:** "Save tactic".
- **Dynamic:** the pitch animation is the signature moment — dots slide to the ball side (Overload),
  fan wide (Out Wide), drop into a block (Long Ball Counter); drag players between slots (square
  tokens, guide line to nearest slot); switching playstyle re-choreographs the pitch.
- **States:** vs specific opponent (shows their shape), fluid on/off.

### 6.4 Fixtures / Calendar
- **JTBD-4.** The schedule and what's coming.
- **Content:** month/season calendar with **events** (matches, intake day, deadline day, contract
  expiries, board reviews); fixture rows (crest · scoreline or kickoff · competition tag).
- **Primary action:** open a fixture / jump to next.
- **Dynamic:** unplayed fixtures show "Import result" on hover; results wipe in; today pinned.

### 6.5 League Table
- **JTBD-4.** Where I stand.
- **Content:** full table with qualifying/relegation leading bars; **your row highlighted (chyron
  bar) + sticky**; form column; expandable to xG-style extras.
- **Dynamic:** **position-over-season worm chart** toggle; sortable; animated rank changes after a
  result; tap a club → their squad/next fixture.

### 6.6 Transfers / Market
- **JTBD-5.** Buy and sell.
- **Content:** search (name/position/age/value/nationality) over the **world DB** (now deduped —
  one entry per player, with face); shortlist; scout reports; your listed players; active offers.
- **Primary action:** "Make an offer" / "Open negotiation".
- **Dynamic:** attribute **masking** outside your scouted range (ranges until scouted); deadline-day
  **live ticker**; rival-bid alerts; value trend sparkline per player.
- **States:** window open/closed, deadline day (heightened), embargo.

### 6.7 Negotiation (modal)
- **JTBD-5.** Close a deal.
- **Content:** offer builder (fee, add-ons, clauses, loan terms), club stance, rival bids, wage +
  contract-length agreement with the player, agent line.
- **Dynamic:** round-by-round back-and-forth with a tension meter; counter-offers animate in;
  "deal agreed" celebratory reveal.

### 6.8 Inbox
- **JTBD-4/7.** News and decisions.
- **Content:** master-detail list (unread badge), categories (board, transfers, injuries, media,
  world news), **required-action** items pinned; faces on player news; breaking-news styling.
- **Primary action:** act on the item (inline).
- **Dynamic:** unread count; a "breaking" ticker; hero cards for big stories (wonderkid, big result).

### 6.9 Player (detail) — the profile
- **JTBD-2/5.** Everything about one player.
- **Content:** **ability radar/hexagon**; all attributes by group (offence/defence/GK/physical);
  **player skills** list; **both playstyles** (attacking + defending); weak foot, form, condition,
  age/height/weight, nationality (flag), contract, morale, value; **growth history chart** (always
  show the delta since last season — growth is the point); career/stats.
- **Primary action:** contextual (renew, list, set role).
- **Dynamic:** radar animates; attribute bars with delta ticks; growth line chart; the big
  **face photo**; compare-to-another-player overlay.
- **This fills the Lineup dead space** — selecting a player in Squad opens this profile below.

### 6.10 Import result (the money screen)
- **JTBD-3.** Get the match result in with near-zero effort.
- **Content:** the app **auto-captures on eFootball close** (memory read / screenshot watch);
  fallback drop-zone for a screenshot; a compact review table of parsed values (score, team stats,
  ratings) with low-confidence fields flagged "Check"; **scorer/assist pickers driven by the two
  XIs** (kill fuzzy text entry — the app knows both squads).
- **Primary action:** "Confirm result".
- **Dynamic:** drop-zone turns solid on drag-over; parsed values populate live; confirmation flows
  into the post-match report.

### 6.11 Post-match report (modal/sequence)
- **JTBD-3/7.** The payoff after a match.
- **Content:** score reveal (count-up, big expanded numerals), scorers timeline, ratings grid with
  faces, MOTM, morale swings, injuries picked up, assistant debrief line, table/position delta.
- **Dynamic:** broadcast-style sequence (wipes, score bug flip); "who impressed" highlight; share-
  card feel.

### 6.12 Finances
- **JTBD-6.** Money at a glance.
- **Content:** transfer & wage budgets (with headroom bars), income vs spend, sponsors, projected
  balance, biggest earners.
- **Dynamic:** money-flow chart (season), wage-budget constraint bar (turns red near limit),
  budget-request action to the board.

### 6.13 Board & Objectives
- **JTBD-6/7.** Expectations and standing.
- **Content:** season **objectives with importance tiers** (critical/important/nice-to-have) +
  progress; **fan happiness** track; board confidence gauge; manager profile + **honours**;
  mid-season review + season-end verdict.
- **Dynamic:** confidence gauge; objective chips (also on Season hub); verdict reveal at season end.

### 6.14 Staff
- **JTBD-6.** Hire and delegate.
- **Content:** roles (Director of Football, Assistant, Coaches, Physio, Scouts) with 1–20
  attributes and **strengths across the 6 team playstyles**; delegate responsibilities (scouting,
  training, negotiations).
- **Dynamic:** hire flow (candidate compare), delegation toggles, a "coaching coverage" viz.

### 6.15 Academy / Youth
- **JTBD-5/7.** The future.
- **Content:** **intake-day event** (annual, with a youth report), prospects with **real potential
  ★**, positions, comparisons to current squad; promote-to-first-team action.
- **Dynamic:** intake-day reveal sequence; potential vs current-ability viz; "next big thing" hero.

### 6.16 Scouting
- **JTBD-5.** Find talent, unmask attributes.
- **Content:** scout assignments (region/role), knowledge %, shortlist feeding Transfers.
- **Dynamic:** masked→revealed attribute animation as knowledge grows; assignment map.

### 6.17 History / Stats
- **JTBD-7.** The career arc.
- **Content:** past seasons (finish, honours), records, stat leaders, your manager honours page.
- **Dynamic:** career timeline; trophy cabinet; position-by-season chart.

### 6.18 New Career
- **JTBD-1.** Start fast, feel invested.
- **Content:** country → league → club grid (crests, squad rating, budget, rep), manager identity
  (name, portrait), settings; club preview panel.
- **Dynamic:** club cards with crest + key info on hover; smooth stepper; "Start" reveal.

### 6.19 Settings
- OCR/game paths (Steam id, screenshot dir) — no longer hardcoded; theme (Floodlit light/dark);
  data sources; simulation aggressiveness.

---

## 7. Dynamic & interactive opportunities (now that we're in HTML)

- **Animated tactical pitch** per playstyle (signature) — the movement diagrams.
- **Charts everywhere:** form worm, league-position line, finance flow, player-growth curve,
  value sparklines, potential-vs-CA.
- **Drag-and-drop lineup** with snap-to-slot guides.
- **Broadcast reveals:** score count-ups, wipes, the post-match sequence.
- **Live surfaces:** the match bar as a score bug during import; deadline-day ticker; inbox breaking.
- **Player radar** and **compare overlay** (animated).
- **Faces & crests** as first-class UI (we have the photos).
- **Keyboard/controller nav** across tables and panels (single-key shortcuts shown in chyron meta).

---

## 8. Design system & assets

- **Floodlit** — dark indigo broadcast look + light theme, chyrons, position pills, form chips,
  chamfered cards, the "wipe" motion. Both themes on every screen.
- **Assets we hold:** club crests, kits/colours, **player face photos** (facepack), generated
  avatars for the rest, nation flags, real league/club/competition names.

---

## 9. Prototype & build order (for Claude Design)

Design in this order — the core loop first, then the world around it:

1. **Season Hub** — sets the visual language + the "what needs me" model.
2. **Squad + Player profile** — the table + the profile that fills the dead space.
3. **Tactics** — the animated pitch (the signature interactive moment).
4. **Import result + Post-match report** — the core-loop payoff.
5. **Transfers + Negotiation** — the drama.
6. **League Table + Fixtures** — the season context (charts).
7. **Board/Objectives, Finances, Staff, Academy, Scouting** — the club depth.
8. **New Career, History, Settings** — bookends.

For each screen ask Claude Design for: both themes, key states (empty/loading/error/success), the
dynamic elements called out above, and mobile-of-the-desktop density (1440 target, 1120 min).
