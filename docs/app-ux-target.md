# App UX target — modelled on My Football Legacy

The companion app (`ML.App`) takes its **look, feel and feature set** from
[My Football Legacy](https://www.myfootballlegacy.com/) (MFL) — a hosted co-op career-mode
tracker for EA FC / PES / SP Football Life. It is the benchmark for what the manager experience
should feel like. We are **not** adopting its code (closed-source SaaS) — only its UX as a north
star.

## The one architectural line we do NOT copy

MFL is a **parallel tracker**: you play kick-off matches in the game, then *manually log the
score* into their web app. It deliberately never touches the game's files — its headline
feature, "safe from save-file corruption", exists *because* it writes nothing back.

Our project's entire reason for being is the opposite: **the app's SQLite DB is the source of
truth and we render it back into the game** (proven — a transfer now appears on the pitch, see
[[writeback-pipeline-works]] / CLAUDE.md). So the model is:

> **MFL's manager experience  +  our writeback pipeline.**

We borrow the screens; we keep the thing MFL refuses to do.

## Feature model to match (from MFL's own site)

| MFL area | What it does | Our mapping |
|---|---|---|
| **Office / Dashboard** | Board confidence, fan satisfaction, squad morale, upcoming fixtures at a glance | `ML.App` home; morale/confidence are new `ML.Core` concepts |
| **Manager Inbox** | Reactive emails from board and players that change with results | `ML.Core` event system → `ML.App` inbox |
| **Squad** | Squad view, morale, rotation | Reads `ML.Core` world + game squad |
| **Transfers** | Buy/sell, wages, budgets | `ML.Core` transfers → **writeback pipeline into the game** |
| **Data / Stats** | League tables, standings, career stats | `ML.Core` engine (already built) |
| **Finances** | Matchday revenue, weekly wages, expenditure, sustainability | `ML.Core` finances (budgets exist; extend) |
| **Fixture calendar** | Full season schedule, congestion, cup rotation | `ML.Core` fixtures (already built) |
| **Custom leagues** | Real-world or custom league structures | `ML.Core` seasons + the moddable competition tables |
| **Co-op via League ID** | Friends share one persistent league online | Later; needs a sync backend. Not near-term. |

## What we already have vs. what MFL implies we still need

- **Have (ML.Core, tested):** fixtures, league table with tiebreakers, match sim, season
  rollover, promotion/relegation, budgets.
- **Have (unique to us):** decrypt/edit/repack pipeline that puts squad changes into the game.
- **Need for MFL-parity:** the Avalonia UI itself, board confidence / morale model, manager
  inbox / event system, richer finances (revenue streams, wage bills surfaced), and eventually
  online co-op (a real backend — treat as a much later phase).

## Priority read

Near-term the differentiator is the **writeback + tactics pipeline**, not the social features.
Co-op/online is the most expensive MFL feature (needs a hosted backend) and the least aligned
with "offline Master League" — it is explicitly deferred. Build the single-player manager
experience over the writeback engine first; that is already further than MFL goes in the
direction that matters.
