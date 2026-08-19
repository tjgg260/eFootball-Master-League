# MFL parity spec — from the real app export

Derived from the user's full My Football Legacy export (a Middlesbrough save). This is the
concrete target for `ML.App`, replacing the earlier guess from the marketing page. We match the
feature set and screen structure; we do not copy their code (closed-source SaaS, kept out of the
repo under `build/mfl_reference/`, gitignored).

## Navigation (left sidebar)

**Manager Hub:** Office · Calendar · Board · Inbox · Competitions · Squad · Training · Academy ·
Analytics · Transfermarket · Finances · Bank · World Stage · Tournament · Stats

**Documentation:** Introduction · Club Operations · Squad & Transfers · Players Training & Growth ·
Academy Development · Office & Media · Matchday & Analytics · Banking & Loans · Job Security

## Office (dashboard) — sections, in order

1. **Club header** — name, status tier ("Emerging"), stadium, capacity, **ELO rating** (1540).
2. **Financial Overview** — a status ("Critical"), Available for Transfers & Wages (€ + %), Total
   Budget, Full Season Wages, Weekly Wage Bill, Est. Transfer Budget, Est. New Wages.
3. **Three gauges** — Fans Feeling, Board Confidence, Players Morale.
4. **Club Chairman** — name + supporter tag.
5. **Inbox** — unread count + latest.
6. **Upcoming Fixtures** — next 5, with competition + matchday.
7. **Next Fixture Preview** — venue, capacity, **win/draw/loss %**, **opponent key player** card
   (position, shirt, market value, foot, wage, height, age, weight), Form Guide (last 5),
   Head-to-Head history.
8. **Press** — Press Conference, Media Room, social ("Wingplay"), Daily Press Clippings.
9. **Market Activity** — live ticker.
10. **Current Standings** — full league table.
11. **Cup/Tournament** — fixtures.
12. **Squad Updates** — player list with position + status.

## Domain concepts MFL has that we must add to ML.Core / ML.Data

- **ELO rating** per team (drives match-preview win %).
- **Club status tier** (Emerging, …).
- **Rich finances**: transfer budget vs wage budget split, "available for transfers & wages",
  season wages, estimated new wages. (We have Finances; extend to this breakdown.)
- **Fans feeling** gauge (third gauge alongside board confidence + morale — we have two).
- **Chairman** entity.
- **Match preview**: win/draw/loss probability from ELO, opponent key player.
- **Press / media / social** event streams (extend the inbox model).
- **Academy / youth** players and development.
- **Training** (ties to the role-training system already built).
- **Transfermarket** with market ticker.
- **Bank / loans**.
- **Job security** (extends board confidence + sack threshold — already have the threshold).
- **Competitions / Tournament / World Stage** (cups beyond the league).

## Build status vs this spec

Done: Office (basic), Table, Squad, Fixtures, Finances, Inbox; board confidence, morale,
finances, role training, fluid tactics.

Gap to full parity, roughly by effort:
1. Enrich Office dashboard (financial overview, ELO, status, next-fixture preview, standings,
   squad updates) — data we mostly have.
2. Add screens: Calendar, Board, Competitions, Transfermarket, Bank, Training, Stats.
3. New domain: ELO + win probability, fans feeling, chairman, academy/youth, press/media.
4. World Stage, tournaments/cups.

Portraits / league logos / team kits are game **assets**, not app data — a separate asset
pipeline, tracked under the enrichment task, not app parity.
