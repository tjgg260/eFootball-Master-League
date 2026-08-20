# Overnight build log — FM parity (docs/fm-parity-plan.md)

## ✅ PLAN COMPLETE — 2026-08-20 (tick 13)

Every item on docs/fm-parity-plan.md is checked. The hourly builder (cron 673406b7) has
deleted itself. Built across 13 ticks: **A1** staff (coach/physio/assistant/scout with real
effects), **A2** scouting missions + dossiers, **A2b** set-piece taker writeback, **A3**
assistant debriefs, **B1** persistent morale, **B2** player talks + promises, **B3**
multi-round contract negotiation, **C1** real-date season calendar, **C2** team talks,
**C3** opposition briefings, **C4** richer OCR (possession/shots into match reports),
**D1** League Cup + prize money + continental flags, **D2** manager career (reputation,
sackings, job offers, club switching), **D3** history & records (season archive, player
career lines, club record book). Final state: build 0 errors, 146/146 tests, smoke OK.
Calibration items still flagged for an in-game session: GK/Destroyer playstyle bits,
taker-bit confirmation, first real STATS screenshot for the C4 OCR regex.

## 2026-08-20 (tick 13)
**D3 History & records — DONE.** No schema change — the archive derives from tables the
seasons already wrote. SessionHistory.cs: ArchiveSeasons (seasons with results),
TableForSeason (rebuilds any past final table; league membership from who actually played
that season, so promotion/relegation years render correctly), HonoursIn, LeadersIn (archive
top scorers), PlayerCareerHistory (season-by-season apps/goals/assists/avg rating, club
reconstructed from the transfer log), ClubRecords (biggest win, heaviest defeat, longest
winning run, record signing, record sale, all-time top scorer). New History screen (📜 nav,
season dropdown → both division tables + honours + top scorers, record book alongside);
Squad card now shows career-history lines under the contract. Gates: build 0 errors, tests
146/146, ML_RESUME smoke OK.

## 2026-08-19 (session start, before first cron tick)
**A1 Staff system — DONE.** `staff` table (additive); SessionStaff.cs partial (hire/fire,
3 deterministic candidates/role/season, wages into FinancialOverview + weekly debit); effects
wired: 4★+ coach cuts training cadence (floor 2), 3★+ physio returns YOUR injured players a
matchday sooner, Assistant appends named reasoning to Suggest XI, Scout reserved for A2.
Staff screen (roster + hire/fire) in nav after Training. Gates: build 0 errors, tests 113/113,
ML_RESUME smoke OK.

## 2026-08-19 (late session, before cron)
**Tactics ↔ Tactics.bin parity audit — docs/tactics-menu-map.md.** Full Game Plan journey map
from the extracted string table + pesdb schema. NEW writeback: the CAPTAIN armband compiles
into PlayerAssignment (vendored bit semantics, v1 0x20@22 / v2 bit9@18) — verified in a test
CPK ("armband: James Hill"). Set-piece taker bits (0x01-0x10) identified as A2b calibration
target. GK/outfield hard position locks added everywhere (position dropdown, both swap paths,
training). Fluid Formation ON/OFF: closed as NOT-IN-TEAM-DATA after Tactics.bin bytes 10/11
all-zero scan + Team.bin differential vs El Jadida VB (the only club shipping two distinct
shapes). Formation tabs renamed to the game's own terms (Attacking/Defensive Formation);
Fluid checkbox text is the game's verbatim string. Gates: build 0, tests 113/113, smoke OK.

## 2026-08-20 (cron tick 1)
**A2 Scouting — DONE.** `scout_jobs` table (additive); SessionScout.cs: StartScoutJob (club or
player, needs a hired scout, one mission at a time, ready in 2 matchdays), CheckScoutJobs wired
into the matchday pass (report-ready mail), ClubScoutReport (shape/style/ELO always; 3★+ likely
XI; 4★+ ratings + top-3 threats with goals; 5★ condition/injuries) and PlayerScoutReport
(value + standout abilities 3★+, fit verdict vs your incumbent). Scouting screen: club picker
defaulting to your next opponent, player search, dossier list. Gates: build 0 errors, tests
113/113, ML_RESUME smoke OK.

## 2026-08-20 (cron tick 2)
**A2b Set-piece takers — DONE.** Bits calibrated against shipped data across four known clubs:
fk=8 (Odegaard/Foden/Szoboszlai — every club's real FK specialist carries it), pk=16, ckl=4
(the left-footers), ckr=1; bit 2 (secondary FK) and 0x20 (captain) preserved. Takers picked on
the Tactics Selection tab (FK/PK/CK-L/CK-R dropdowns over the XI), stored in meta, compiled by
reconcile_real_slot: shipped duties stand unless the club has takers set. Compile test PASSED
("set pieces: duties written for Alex Scott, Justin Kluivert"). v2-layout taker sub-bits left
untouched pending separate calibration (documented in code). Gates: build 0, tests 113/113,
ML_RESUME smoke OK.

## 2026-08-20 (cron tick 3)
**A3 Assistant debrief — DONE.** Post-match: AssistantDebrief(fixture) builds the analysis from
recorded match_events — our scorers, our creators, and "their damage came from X — worth a
scouting look" — posted to the inbox after every recorded result (only when an Assistant is
hired). Pre-match: the assistant's named-absences note (out/needing a rest) now shows on the
Dashboard opposition card as well as on Suggest XI. Phase A complete. Gates: build 0 errors,
tests 113/113, ML_RESUME smoke OK.

## 2026-08-20 (cron tick 4)
**B1 Per-player morale — DONE.** New pure ML.Core MoraleModel (+5 unit tests, suite now
118/118): matchday effect (starters +, benched -, result moves everyone, transfer-listed
stings), neutral drift, form adjustment ±1.8, MFL-style labels. SessionMorale.cs persists to
the existing `morale` table (no schema change), runs after every matchday for YOUR squad, and
fires a transfer request (inbox + auto-list, once per player per season) below morale 20.
Morale feeds the XI selector's form term for your club (PrepareMatchday + SuggestXi). Squad
grid gains a morale face column with label tooltip. Gates: build 0, tests 118/118, smoke OK.

## 2026-08-20 (cron tick 5)
**B2 Player talks & promises — DONE.** `promises` table (additive). MoraleModel gains
AfterTalk (bounded ±4) and AfterPromise (kept +8 / broken −15, asymmetric on purpose) with 2
new tests (suite 120/120). Squad card buttons: Praise / Criticise (one talk per player per
matchweek), Promise starts (3+ apps in 6 matchdays, settled from real app events) and Promise
contract (renew within 6 matchdays; RenewContract fulfils it early with a thank-you letter).
Deadlines settle in the matchday pass; kept/broken letters land in the inbox, with broken
promises cratering morale. Open promises show on the card ("Holding you to: …"). Gates: build
0, tests 120/120, smoke OK.

## 2026-08-20 (cron tick 6)
**B3 Contract negotiation v2 — DONE. Phase B complete.** Pure ML.Core ContractNegotiation
(+5 tests, suite 125/125): demand from rating (super-linear for stars), age curve (peak 24-29
premium, 33+ discount), morale ("prove you love me" +15% when unhappy) and length (3yrs eases
the weekly); Respond() accepts within 3% of the status-discounted target, counters easing
toward it, walks away on insults or round 3. Squad card negotiation panel: wage offer, years
(1-3), squad-status promise (Star/First-team/Rotation = wage discount, but B1/B2 police the
owed starts: 5/4/2 in 6 matchdays via kind 'status:X' in CheckPromises). Accepted wages are
REAL: contracts.weekly_wage feeds the weekly bill (stub £500 rows fall back to the formula).
Agreement letters in the inbox. Gates: build 0, tests 125/125, smoke OK.

## 2026-08-20 (cron tick 7)
**C1 Real calendar — DONE.** Pure ML.Core SeasonCalendar (+4 tests, suite 129/129): dates
derived deterministically from matchday numbers, no schema — league rounds are weekly
Saturdays from the first Saturday of August, cup rounds the midweek Wednesday of their shared
week, preseason friendlies the last Saturday of July. Calendar screen rebuilt as an FM-style
month grid (Mon-first, ◀ ▶ month nav, opens on the month of your next fixture; your matches
highlighted with competition icon, opponent, venue and result once played). Dashboard now
date-stamps the next match ("Matchday 8 · Sat 26 Sep 2026") and the schedule rows use real
short dates. Gates: build 0, tests 129/129, smoke OK.

## 2026-08-20 (cron tick 8)
**C2 Team talks — DONE.** Pure ML.Core TeamTalk (+4 tests, suite 133/133): pre-match tones
Calm/Encourage/Demand and full-time Praise/Measured/Hairdryer, effects contextual — Demand
lifts confident favourites (+3 morale, +0.3 form) and backfires on fragile rooms (−3/−0.2);
the hairdryer after a loss cuts both ways on squad morale ≥/< 55; Calm never backfires.
Bounded squad-wide morale + form nudges, one say per fixture per phase (meta-guarded).
Dashboard: talk buttons on the next-match card pre-match and after recording, with the
assistant hinting the right tone (ELO favourites + dressing-room read) when hired. Gates:
build 0, tests 133/133, smoke OK.

## 2026-08-20 (cron tick 9)
**C3 Opposition briefing — DONE.** Pure ML.Core OppositionBriefing (+3 tests, suite 136/136):
a counter-plan per opponent style (Out Wide → back three eats crosses / counter teams starved
of transitions / Overload → absorb and break). Dashboard opposition card now shows the scout's
dossier summary (their style + the man to stop) and the counter suggestion — ONLY when that
club has actually been scouted; otherwise it prompts you to send the scout. Honest boundary
stated in the UI: suggestions set up YOUR compile only, the opponent's in-game AI is untouched.
Gates: build 0, tests 136/136, smoke OK.

## 2026-08-20 (cron tick 10, user said keep going)
**C4 Richer OCR — DONE. Phase C complete.** StatOcr gains ReadFullText (whole-image OCR, no
region calibration needed); ScoreImport.StatsFromLatestScreenshot parses keyword-anchored rows
(Possession NN% NN%, Shots N N) from the game's STATS screen. Dashboard: 📊 Import stats
button in the full-time row writes possession/shots into results.stats_json for the recorded
fixture. Stats screen gains a Match Reports panel (dated recent results with captured stats).
NOTE: parsing is keyword-anchored so it tolerates layout, but the first real STATS-screen
screenshot from the user will confirm the regex — flagged for a live check. Gates: build 0,
tests 136/136, smoke OK.

## 2026-08-20 (tick 11)
**D1 League Cup + continental flags + prize money — DONE.** Cup machinery generalized to a
CupSpec array: National Cup (9002, mds 8/15/22/29/33) and League Cup (9003, mds 5/11/19/26/31)
draw, sim and advance independently (per-cup salt, per-cup winner meta cup_winner_{lid}_{season});
EnsureCup/AdvanceCup/CompleteCup loop both. New PayPrizesAndFlagEurope at rollover: league
position money (top flight 2m down to 400k min 200k, Division 2 half), cup prizes 750k/400k,
continental_{nextSeason} meta flags the top two, all with inbox letters and your money through
Finances. Honours records both trophies (cup/lcup). Cups screen renders both brackets as
sections; dashboard fixture label and post-match press name the right competition via
CupNameFor(leagueId). Gates: build 0 errors, tests 136/136, ML_RESUME smoke OK.

## 2026-08-20 (tick 12)
**D2 Manager career — DONE.** New pure model ML.Core/Management/ManagerCareer.cs: reputation
0-100 moves with every competitive result (beating stronger sides worth more, only losing to
weaker sides costs), a big season-end swing (titles/promotions/trophies vs relegation places),
ShouldSack (confidence <=5 instant, or 5 matchdays at/below the threshold), ClubWouldOffer
(bigger clubs demand a bigger name) and ExpectationFor/TargetPosition — 10 new tests.
SessionCareer.cs persists rep, board confidence and the threat streak in meta; the Session ctor
now derives the board expectation from squad-strength rank instead of hard-coding Playoffs, and
seeds confidence from the stored value so slumps survive restarts. Recording your result runs
the board: a final warning lands one matchday before the axe, and a sacking darkens the
dashboard (career summary + pointer to offers) and posts desperation offers. Board screen:
reputation + career tiles, dismissal banner, job offers with an Accept button that switches
current_team_id and reloads the whole app on the new club. Rollover applies the season rep
swing, cools the board to >=45 and (35% seeded) brings suitors. Gates: build 0 errors, tests
146/146, ML_RESUME smoke OK.

## 2026-08-20 (user session — Game Plan video replica)
**Tactics screen rebuilt as an exact Game Plan replica** from the user's in-game recording
(Aberdeen v Aberdeen, 174 frames extracted, 69 distinct screens). Structure now mirrors the
game: pill bar Lineup / Tactics / Team + blue Save (Done); left context column (yellow screen
title, menu tree Set Formation -> Fluid Formation / Attacking / Defensive Formation + template
list, Team Playstyle, Individual Instructions, Sub-Tactic); crest + Substitutes right rail;
ONE horizontal pitch: your XI on the left half (GK far left, drag only on Set Formation, pink
Attack / teal Defence phase frame, live shape label) and the NEXT REAL OPPONENT mirrored on
the right half (their fid geometry + XI + shape) — better than the game's own mirror. New
verbatim strings pulled from all.str: Individual Instruction options (Defensive, Anchoring,
Tight Marking, Man Marking, Counter Target + descriptions), captions ("Set the formation when
attacking/defending", set-piece join-attack caption), toast "Formation changed". Instructions
persist per club in meta as planning state (honest 🔒: the game keeps them in its save — not
compiled). Team tab = In-Match Roles: Captain + FK/L-CK/R-CK/PK takers (all compiled),
Player-to-Join-Attack shown locked. Coordinate system rotated to horizontal with exact
inverse round-trip (writeback unchanged); window widened to 1640x820; ML_PAGE env hook added
for screenshot tooling. Gates: build 0 errors, tests 146/146, smoke OK, screenshot-verified.

## 2026-08-20 (deep-build day — approved roadmap P0-P4)
**Audit → plan → executed.** Two adversarial code sweeps produced the audit + roadmap
(.claude/plans/elegant-booping-firefly.md, approved). Landed today, all gated (build 0,
155/155 tests, smoke):
**P0 correctness:** cup/league matchday collision fixed (your league game can no longer be
simmed behind your back); Dashboard morale gauge reads real SquadMoraleAverage (was a
constant 60 forever); cup weeks now run the full weekly economy (training/wages/loans/
scouts/morale/gate) via shared RunWeeklyEconomy; ONE wage-bill truth (FinancialOverview)
+ season income/spend persisted per season; OCR Steam paths de-hardcoded → Settings screen
+ auto-discovery.
**P1 skills/personality/determination:** player_traits/player_skills/skill_training tables;
verbatim eFootball skill catalog (innate + boosted-tier never learnable, GK/MidFwd gates,
Track Back mid/fwd only); FM personality ladder from Det/Prof/Amb/Temper (1-20); skill
training with sessions scaled by determination+coach; growth multiplier wired into season
development; Training screen skill panel + personality/Det/skills columns; Squad card
character+skills lines. 9 new ML.Core tests.
**P2 living world:** world_seed mixed into all 12 roll sites (two saves finally live
different lives); REAL stored potential (development caps at it, breakout seasons ~1/8 for
kids far below ceiling, Academy ★ now truth); intake day event (1-4 varied prospects, youth
coach report, gems); needs-based CPU market (thinnest position group, varied pool slice,
inter-club raids with real fees, "Around the market" news); retirements (age-curved) +
out-of-contract players actually leave on frees; FM board objectives (4 kinds x importance
tiers, mid-season review at MD19, season verdict moving confidence/rep/budget backing) +
persistent fan ledger blended into the fan gauge; Board objectives panel + Dashboard chips.
**P3 matchday:** sim now XI-based attack/defence with fatigue+form adjustment and home
advantage (replaces avg(squad) as both numbers); XI-driven goal/assist/card pickers replace
free-text scorer entry (both XIs known — no more typos/fuzzy matching).
**P4 dt270 infra:** gameplay_tune.py gains capture (PRISTINE + sha guard baseline — RUN,
family 9968 confirmed), selftest (round-trip-gated byte-identical boot test), scale
(per-file Q2.14 calibration probes), log (verdicts → docs/dt270-gameplay.md); calibration
protocol documented. Awaiting the user's first calibration evening.
**Also today:** Market overhaul (RFS overall repair: recomputed 31,507 ratings from
abilities calibrated ±1.3 pts on 22k natives, 226 outlier compressions, 2 junk rows
deleted; star-premium valuations; real filters; click-through profile card) and the
Game Plan tactics replica from the user's video.

## 2026-08-20 (evening — FM knowledge system + full Settings)
**FM attribute masking (P5 core).** ML.Core AttributeKnowledge (4 colour bands split 58/70/80;
deterministic monotonic per-attribute reveal by knowledge 0-100; coach phrasing engine
"Exceptional close control") + 6 tests (suite 161/161). player_knowledge table; baselines:
own squad/academy 100, same league 40, other division 25, world 0 — scaled by the masking
strictness setting. Knowledge grows: facing a club teaches their XI (+15/meeting), player
dossier 90, club dossier 60 (scouting finally has mechanical value). Squad card: coach's
report (knowledge-quoted) + analyst line (apps/goals-per-app/rating/form, gated). Market
profile: knowledge label + scout nudge, radar hidden below 45, abilities masked.
**Settings suite ("build it all").** One screen, five panels: Display (UI skin dropdown —
Midnight/Club Colours/Broadsheet/Retro PES via runtime theme tokens (App.axaml
DynamicResource; full per-view tokenisation deferred to design polish) + the FM view toggle);
Realism (masking strictness, transfer difficulty → seller ask ±, injury frequency →
RollInjury halves/adds, board patience → sack streak shift — all wired into the live
systems); Matchday & world (auto-boot eFootball toggle → MatchLauncher, real-names-in-game
toggle → play_match honours meta real_names, world-seed display); OCR paths; Data (backup
now, restore-from-backup staged via master.restore.db swap in CareerLoader at next launch).
Gates: build 0, tests 161/161, ML_RESUME smoke + Settings screenshot verified.
Also: Claude Design project "Master League" created; 4 transfer-screen prototype cards
pushed (market full screen, negotiation dialog, shortlist & incoming offers, deadline day).

## 2026-08-20 (night — appearance pipeline: RFS truth into eFootball faces)
**PlayerAppearance.bin cracked (skin tone).** WESYS container, 64-byte records, u32 pid@0,
23,388 natives. SKIN TONE = 3-bit field at bit 292 (byte 36 bits 4-6), values 1 lightest -
6 darkest — recovered by portrait correlation (1,029 name-matched players; face luminance
strictly monotonic 165->97 across the six values). Round-trip gated (tools/appearance.py;
payload-identical re-encode proven, level-1 container same encoding the shipping authoring
path uses). Hair colour in PlayerAppearance NOT mapped (weak candidates ~byte 47 — likely a
model id, flagged).
**RFS appearance offsets cracked.** players record (207 B): skintonecode = byte 113 (FIFA
1-10, |r|=0.72, monotonic across all 10 codes over 4,000 portrait samples); byte 116 = 5-class
hair colour (0 dark -> 1/4 blond). Stored: player_appearance table (skin_tone 1-6 eFootball
scale, rfs_skin exact 1-10, hair_color class, source bin/portrait/rfs) — 52,608 players
covered: 19,831 natives read from the game bin, 32,621 imported with EXACT RFS codes
(11,372 linked by portrait id, 21,251 by name), 156 portrait-sampled fallbacks.
**Compile: donor-less-as-possible authoring (user request).** ml_author DonorPool now picks
appearance-MATCHED donors (same skin tone class, ±1 fallback) so the whole cloned appearance
record comes from a matching player, then writes the target's EXACT skin bits over the
clone (bit 292). play_match squad_from_db carries skin_tone per player. Current club: 23/23
squad members resolve appearance. True donor-free authoring still needs face/hair model id
cracks — flagged as the next appearance milestone.
Gates: tools syntax OK, build 0 errors, tests 161/161, smoke OK.

## 2026-08-20 (late night — negotiation v2 + deadline day, P5 market drama)
**Club negotiation (from the approved prototypes).** Pure ML.Core ClubNegotiation (+7 tests,
suite 168/168): package EffectiveValue (fee + sell-on option value at 60p/£ + instalment
time-cost), Respond (accept within 3%, walk under 78% or after round 3, counters ease the
ask 40% toward the offer, never below value), Likelihood %, difficulty-scaled OpeningAsk,
stance lines with information in them. negotiations table (additive). SessionNegotiation:
StartNegotiation (free agents skip the club step), SendClubOffer rounds, CompleteSigning —
agent wage floor via the existing ContractNegotiation model, REAL contract written for every
signing (no more £500 stubs), instalments (half now, half later), sell-on clause stored.
**Sell-on clauses are real:** granted clauses deduct from YOUR sale in AcceptOffer and pay
the holder club; clauses you hold pay out on CPU inter-club moves with an inbox letter.
**Deadline day:** fires as the window's last matchday approaches — a 25%+ premium late bid
for one of your better players, open negotiations soften 5% or die at the deadline, yellow
DEADLINE DAY banner on the Office. Market profile rail gains the full negotiation panel:
stance quote, fee entry, sell-on/instalment checkboxes, live deal likelihood, then the
agent step (wage x years) and "Complete signing".
Gates: build 0 errors, tests 168/168, smoke on Market OK.

## 2026-08-20 (small hours — post-match report, realistic values, FM playing time)
**Post-match report (P3 complete).** Full time is a moment: verdict banner
(VICTORY/DRAW/DEFEAT coloured), big scoreline, competition, events list (goals/assists/
cards with sides), top ratings, morale/board/fans DELTAS from pre-kickoff snapshots, the
assistant's debrief, Continue button. Built from EventsForFixture/RatingsForFixture.
**Realistic valuations (user request).** ValuationOf now an exponential market curve:
60=£650k, 70=£4.5m, 75=£11m, 80=£30m, 85=£78m, 90=£200m, with steeper age decay and a
bigger youth premium. Prize money rescaled to match (top flight £12m→£1.5m floor, cups
£4m/£2m) so the economy can carry the fees.
**FM playing-time system (user request, FM-modelled).** player_status table; statuses Star
Player / Important Player / Regular Starter / Squad Player / Fringe Player / Hot Prospect /
Surplus to Requirements; stored when set, otherwise derived from squad rating rank (also
prices CPU squads). Expectations (starts per 6 MDs: 5/4/3/2) evaluated every 6th matchday:
shortfalls bleed morale (−6/−3), met expectations settle stars, complaints letter names
names; Surplus = auto-listed, −10 morale, simmering. Status drives the AI's willingness to
sell BOTH ways: negotiation opening asks ×145% Star / ×130% Prospect / ×70% Surplus (with
stance flavour), and offers for YOUR players are status-weighted (Surplus 85% chance at a
discount, Star 15% but heavy). Squad card: status dropdown (promotions please +5, demotions
sting −6) + wants/got starts line.
**dt270:** scale gains --start/--end word-slice bisection — the protocol for isolating the
AI build-up tempo words in constant_team (912 B / 228 words on family 9968).
Gates: build 0, tests 168/168, smoke OK.

## 2026-08-20 (Sky-style News + dt270 diff study)
**News screen (P6 pass 4, pulled forward on user request).** The Inbox is now a Sky-style
feed: DONE DEAL hero card (latest paid move — portrait in a green-ringed cutout, club route,
gold fee), category accent bars (gold transfers / blue board / teal player / grey media),
circular faces on every story about a player (inbox.player_id added; signing/skill/
retirement/sell-on/deadline-bid letters all carry ids now), and an AROUND THE MARKET ticker
rail with faces from the transfers log. Nav renamed Inbox -> News 📰. Screenshot-verified.
**dt270 diff study (all five packs).** Patch-stable files identified (positionPK etc, none
gameplay); the four gameplay files restructure every patch; value-fingerprint transfer of
mod knowledge into family 9968 FAILED (honest negative). Consensus mod knowledge recorded:
old constant_team word 131 (a 49.0 scalar) reduced by ALL three realism mods (GabeLogan to
5.0!) = the tempo suspect; word 122 = a gate all mods disable identically. New-table scan:
family-9968 constant_team is now mostly sentinels/flags (156/228) — the scalars MOVED.
Revised calibration probe order: constant_match first (AI build-up suspect), player,
ballPerson, team as control. All in docs/dt270-gameplay.md.
Gates: build 0, tests 168/168, smoke + News screenshot OK.

## 2026-08-20 (P6 passes 1-3: shell, imagery, charts)
**Shell awareness.** Sidebar now carries: club crest + name, the DATE + matchday line
(SeasonCalendar), a 📰 unread badge, a red ⚠ decisions line (pending offers / DEADLINE DAY /
job offers), and a themed Continue → button. Badges refresh on every navigation.
**Imagery.** Market result rows lead with faces (portrait, else a skin-tone avatar from the
appearance data — Visuals.SkinBrush 1-6); Academy prospects get skin-tone avatars with
initials (intake now seeds a tone per prospect); the News feed + ticker carry faces from the
previous pass; the Table has always had crests — now the sidebar does too.
**Charts.** Session.PositionHistory rebuilds your league position after every played
matchday from fixtures alone (no stored series); the Table screen opens with the position
WORM — accent-coloured polyline over gridlines with a best/worst/now caption. Hidden until
two matchdays exist.
Gates: build 0, tests 168/168, smoke + screenshot (shell verified: crest, date MD 0,
3-unread badge, Continue button, crests in table).

## 2026-08-20 (P6 continued: cup bracket + end-of-season awards)
**The cup is a BRACKET now:** rounds render as side-by-side columns of tie cards (home/away
stacked, gold score chip, your ties highlighted), scrolling horizontally toward the final;
later rounds appear as they are drawn. Screenshot-verified on the National Cup R32.
**End-of-season awards:** at rollover the season data crowns Player of the Season (best
average rating, min 8 rated games — into the honours roll under 'pots'), Young Player of
the Season (best av, 21 or under), and the Golden Boot — one gala letter in the news with
the POTS face. Honours() renders award rows with player names.
Gates: build 0, tests 168/168, smoke + bracket screenshot OK.

## 2026-08-20 (UX depth block — no new mechanics, per user direction)
**Squad screen:** search box + filter chips (All/GK/DEF/MID/FWD/Injured/Tired/Unhappy/
Listed) over the roster; selection follows the filter. Screenshot-verified.
**Calendar events:** window opens/closes (🚨 on the deadline), mid-season review and intake
day now marked on the month grid alongside fixtures.
**Board chart:** the club's whole ELO trajectory (every recorded game, all seasons, derived
not stored) as an accent polyline with now/peak/low caption.
**Skins pass 2:** recurring panel/ground backgrounds across MainWindow/Dashboard/Squad/
Tactics views converted to DynamicResource theme tokens — Broadsheet/Retro PES/Club Colours
now restyle far more of the app.
Gates: build 0, tests 168/168, smoke + Squad screenshot OK.

## Block: Continental Cup + Loans (items 1-2 of 12)

- Continental Cup (id 9004): 8 teams, MDs 13/21/35, qualifiers from `continental_{season}` meta
  + ELO fill, £10m prize, honours 'ccup'. Wired into Cups array / EnsureCup / PayPrizes / Honours.
- Loans both directions (SessionLoans.cs + `loans` table): Loan out from the Squad card
  (deterministic lower-half host, dev bonus ≤22 at return), Loan in from the Market profile
  (10% of value fee), recall from January (MD≥17) via the OUT ON LOAN strip on Squad,
  ReturnAllLoans() at season rollover with "returns sharper" letter.
- Gates: build 0 errors · tests 168/168 · ML_RESUME smoke on Squad OK.

## Block: Derby.bin crack + board levers + breaks + stats + history (items 3-6, 8, 11)

- **Derby.bin CRACKED** (12-byte records: team u32, group u32, row u16, intensity u16 —
  794 anchored rivalry groups). tools/derby_import.py → `team_rivals` (1,764 directed pairs).
  Career (RFS) clubs aren't covered by Konami data, so EnsureRival synthesizes one mutual
  rival per club (nearest ELO, same division). Wired: 🔥 DERBY tag on the Dashboard,
  ±8 fan-ledger derby swings with letters, and a "Beat {rival}" board objective.
- **Coach name pool from Coach.bin** (906 real names; full 176-byte record layout has odd
  string alignment — names extracted, team-link not cracked). ManagerNameOf() assigns a
  stable real name to every AI dugout; shown pre-match. Your own name is a Settings field.
- **Board levers**: RequestBudget (once/season, confidence-gated grant), training ground +
  academy upgrades (£2m×level, 5 levels) — training level multiplies weekly development of
  YOUR squad, academy level lifts intake floors. New Club Infrastructure panel on Board.
- **International breaks** after MDs 4/9/14/25: top-rated players (78+, max 6) return with
  +12 fatigue + call-ups letter; 🌍 markers on the Calendar.
- **Stats depth**: clean-sheet table, discipline leaders (🟨/🟥, red = 3 pts), per-game rates
  on scorers/assists, all-time head-to-head vs your next opponent.
- **Weekly club history** (`club_history`): balance/fans/board/ELO snapshot per matchweek —
  money trend chart on Finances, fan-mood sparkline on Board.
- Gates: build 0 errors · tests 168/168 · ML_RESUME smoke on Board OK.

## Block: research passes — hair bits (item 7), kit colours (item 10), portraits (item 9)

- **Hair colour bits (item 7): honest negative.** No RFS↔native dual-source players exist
  (hair_color only covers RFS-authored records), so the label source is portrait top-strip
  pixels — and those labels are too noisy: best candidate bit field scores MI 0.06 against
  0.91 bits of label entropy, indistinguishable from the noise floor (the *known* skin field
  scores 0.026 vs the same labels). Parked until a cleaner label source appears.
- **Kit colours (item 10): format mapped, write gate NOT passed.** Per-team kit configs live
  at `common/etc/uniform/team/<id>/<id>_DEF_{1st,2nd,3rd,GK1st}_realUni.bin` — small WESYS
  containers (~92-byte payload): shirt/sleeve RGB triplets, a float block, and a texture ref
  string (e.g. `u0101p1`). One zlib parameterization (level 4, memLevel 1, Z_FIXED) rebuilt a
  sample byte-exactly but only 6/400 files match — Konami's deflate isn't reproducible by
  Python zlib in general, so `prove_round_trip` fails and **no kit write ships**. TeamColor.bin
  (menu colours) also decoded: 20-byte records, team id + 3 RGB-ish triplets.
- **Native portrait pack (item 9): still blocked** — no legal asset source for real player
  portraits beyond the 12.8k already imported from RFS. Nothing to build.
- Item 12 (toast unification / full view-split) remains partially done from the earlier token
  sweep; SquadView/TacticsView/DashboardView are split out, the rest still inline.

## Block: Staff database (FM-style)

- `staff_people`: 220 persistent individuals across 9 roles (Assistant Manager, Director of
  Football, Coach, GK Coach, Fitness Coach, Youth Coach, Physio, Scout, Analyst) with 1-20
  attributes (coaching/youth/fitness/physio/judging ability/judging potential/tactical/man
  management), tactical preferences (formation + style), wages, contracts. Names from the
  Coach.bin pool; deterministic per world seed; old 4-role hires migrated in.
- Hiring: free-agent market per role, best first; hire = 2-year deal, replaces + releases the
  incumbent; release returns people to the pool.
- Delegation (5 toggles): Assistant picks XI · DoF handles renewals · DoF suggests targets
  (judging-ability-scaled shortlist letters every 4 MDs) · Scout auto-reports next opponent ·
  Fitness Coach manages recovery (2-6 fatigue/wk relief). Runs in the weekly pass.
- Attribute-driven effects: Coach 14+ = faster training · Physio attr/8 matchdays off layoffs ·
  Youth Coach 13+ = +2 intake floor · GK Coach 12+ = ×1.25 keeper growth · assistant tactical
  read of the next opponent in their own preferred style.
- New Staff screen: backroom cards (attributes + style line + release), staff market with
  full detail rows, delegation panel with role-gating hints.
- Gates: build 0 errors · tests 168/168 · ML_RESUME smoke on Staff OK.
