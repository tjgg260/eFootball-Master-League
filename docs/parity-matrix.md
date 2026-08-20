# Parity matrix — ML.App vs My Football Legacy vs RFS

The measurable definition of "full feature parity". MFL columns come from the user's real MFL
export ([mfl-parity-spec.md](mfl-parity-spec.md)); RFS columns from the RFS.DB table surface.
✅ = built and verified in-app · 🟡 = built in reduced form (noted) · ⛔ = deliberately out of
scope (noted why).

## MFL feature surface

| MFL feature | Status | Where in ML.App |
|---|---|---|
| Office dashboard | ✅ | Office: hero, next match, portal cards, gauges, tiles |
| Club status tier ("Emerging"…) | ✅ | Office header (ELO-driven: Emerging/Solid/Established/Elite) |
| ELO rating | ✅ | Office header + opposition card (replayed from all recorded results) |
| Financial overview (transfer/wage split, weekly bill) | ✅ | Office header line + Finances screen |
| Board Confidence gauge | ✅ | Office tile + Board screen |
| Players Morale gauge | ✅ | Office tile |
| Fans Feeling gauge | ✅ | Office tile (position vs expectation + form) |
| Chairman | ✅ | Office header + Inbox board message |
| Inbox | ✅ | Inbox: board expectations, press reaction, treatment room, market |
| Upcoming fixtures | ✅ | Office schedule card + Calendar screen |
| Next-fixture preview: win/draw/loss % | ✅ | Office opposition card (ELO model, from your POV) |
| Opponent key player card | ✅ | Office opposition card (best-rated: name/pos/rating) |
| Form guide (last 5) | ✅ | Office opposition card (W/D/L chips) |
| Press / media clippings | 🟡 | Inbox press reactions (no separate media-room screen) |
| Market activity ticker | ✅ | Office ticker + Inbox (CPU clubs buy between seasons) |
| Current standings | ✅ | Office mini table + Table screen |
| Cup / Tournament | ✅ | Cup screen: 32-club knockout, rounds simmed, pens on draws, bracket view |
| Squad screen + player cards | ✅ | Squad: portraits, radar, colour-coded abilities, condition |
| Training | ✅ | Training screen + age-curve development at rollover |
| Academy / youth development | ✅ | Academy screen: preseason intake, promote to squad; CPU auto-promotes |
| Analytics / Stats | ✅ | Stats: scorers, defence + OCR stats stored per result |
| Transfermarket | ✅ | Market: search 74k players, sign to squad |
| Finances | ✅ | Finances screen |
| Bank / loans | ✅ | Bank screen: £250k/£500k/£1m at 5%, weekly instalments auto-collected |
| Job security | ✅ | Board screen (confidence + under-threat state) |
| World Stage | ⛔ | International management — different game loop, not part of the club career |
| Documentation pages | ⛔ | MFL's help articles — not app functionality |

## RFS feature surface

| RFS data/feature | Status | Where |
|---|---|---|
| 79k-player world (players, abilities) | ✅ | master.db: 57,199 unique (more unique players than RFS's 47,193 — plus eFootball's own) |
| Competitions (leagues) | ✅ | 91 real leagues, career in any of them (2-division pyramid + cup) |
| Teams + real squads | ✅ | teamplayerlinks imported; career seeds real rosters |
| Managers/coaches | ✅ | 981 coach records with formations + styles |
| Formations + per-team tactics | ✅ | Per-team owned formation pairs, editor + in-game writeback (verified byte-exact) |
| formations **ai** / substitutions ai | ✅ | XiSelector: AI managers pick XIs (rating/fatigue/form/injuries) |
| Contracts | 🟡 | Season-based contracts settle at rollover (no individual negotiation UI) |
| Injuries | ✅ | player_condition: seeded injury rolls, treatment room, XI avoidance |
| Transfers | ✅ | Your signings + CPU market activity, transfers table + ticker |
| Youth teams | ✅ | Academy intake per club per season |
| Standings | ✅ | Engine-computed tables both divisions |
| Stadiums, referees, weather | ⛔ | Cosmetic fixture metadata — the match runs in eFootball itself |
| Kits/jerseys (colour data) | 🟡 | Kit colours in DB (teams.primary/secondary); in-game shirt recolour descoped by user |
| Roll of honour | ✅ | Stats screen: every season's league + Division 2 + cup winners |
| News channels | 🟡 | Inbox clippings (no fake TV channel branding) |
| Calendars | ✅ | Calendar screen; cup rounds interleave the league schedule |

## What neither reference has (ours alone)

- The match is **played in eFootball itself** — one button compiles both real squads, tactics,
  roles and AI-picked XIs into dt200 and boots the game; OCR imports the score back.
- Byte-verified writeback with a corruption guard (all 1,778 other teams' formations proven
  untouched).

## Verified

`dotnet build` 0 errors · `dotnet test` 113/113 · app smoke-launched on a live career and
screenshotted (build/ui/04-office-parity.png) with ELO/tier/chairman/finances/Cup/Academy/Bank
all rendering.
