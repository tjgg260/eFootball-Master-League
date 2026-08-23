# Functional spec — every system, its engine verbs, its flow states

Grounded in the shared Session engine (`src/ML.App/Session*.cs`, compile-linked into ML.Web).
Nothing here is hypothetical: every verb listed exists and worked in the pre-Blazor app.
Buckets: **(a)** engine + design exist → build now · **(b)** engine exists, interaction design
needed → Claude Design brief (§B) · **(c)** engine partial/absent → later, don't block.

---

## 1. Transfers in — negotiation with the selling club **(a)**

Design: `Master League.dc.html` §1b Negotiation modal + §1d transfer-window storyboard.
Engine: `SessionNegotiation`, `Session.SignPlayer` (free agents).

**States** (per target player):
1. *Browse* — Market search. `KnowledgeOf(pid)` gates what's visible (§9).
2. *Open talks* — `StartNegotiation(pid)` → `NegotiationView { Round, Ask, State, MarketValue, Stance }`.
3. *Offer round* — user sets fee / sell-on % / instalments; `DealLikelihood(pid, fee, sellOn, inst)`
   renders the tension meter; `SendClubOffer(...)` → `(Message, Agreed, Dead)`. Rounds escalate,
   the club counters, rivals can enter, talks can die (`WalkAwayFromNegotiation`).
4. *Agreed → personal terms* — `SigningWageDemand(pid, years)`; user picks years/wage.
5. *Signing* — `CompleteSigning(pid, fee, sellOn, inst, years, wage)` → money moves, player joins,
   inbox item posts. Sell-on clauses persist and pay out on future sales.
6. *Free agents* — short-circuit: `SignPlayer(pid)` (wage-only).
- *Deadline day* — `IsDeadlineDay()` / `RunDeadlineDay(md)` drive the ticker + forced endings.

## 2. Transfers out & contracts **(a — same design vocabulary)**

Engine: `SessionSquad`.
- List / unlist: `SetTransferListed(pid, bool)`; CPU bids arrive via the world sim (§12).
- Release: `ReleasePlayer(pid)` (severance from budget).
- Renew: `ContractYear(pid)` → `ContractDemand(pid, years, status)` → `OfferContract(...)`
  `(Accepted, Over, Message)` — a real haggle, wage budget enforced.
- Promises: `MakePromise(pid, name, kind)` / `PromiseLine(pid)` / fulfilment tracked per matchday.

## 3. Tactics **(a — DONE)**  drag XI, position-from-zone, swap, roles, takers, captain, styles.

## 4. Training & development **(b)**

Engine: `SessionSquad` + `SessionDevelopment`.
- Position retraining: `TrainingGroups`, `SetTraining(pid, focus)`, 6 sessions → `LearnedPositions`.
- Skill training: `LearnableSkillsFor(pid)` → `StartSkillTraining(pid, skill)` → `ActiveSkillTrainings()`.
- Growth inputs: `TraitsOf` (determination/professionalism/ambition/temperament), `PersonalityOf`,
  `PotentialOf/PotentialStars` — development ticks after matchdays.
**Needs design**: a Training screen — squad grid with focus assignment, active-course progress
bars, per-player development tab (personality, potential stars, growth curve).

## 5. Scouting **(b)**

Engine: `SessionScout` + `SessionKnowledge`.
- Missions: `StartScoutJob(kind, targetId, name)` (player | club | opposition), 2 matchdays,
  one active at a time; `ActiveScoutJob()`, `CompletedScoutJobs()`, reports (`PlayerScoutReport`,
  `ClubScoutReport`, `OppositionBriefingFor`).
- Knowledge: `KnowledgeOf(pid)` 0–100 masks market attributes into ranges; `FmAttributeMode`.
**Needs design**: mission board (assign scout → progress → report lands in inbox), and the
masked-range → revealed animation in Market rows.

## 6. Matchday loop **(a mechanics done · b for post-match report)**

Working: play_match install → manual score import → `PlayOutMatchday(md, exceptFixture)` CPU sim
(engine version replaces my MatchdayEngine one) → morale/objectives/career/fans updates
(`UpdateMoraleAfterMatchday`, `ApplyFansAfterResult`, `ApplyCareerAfterResult`), OCR
(`ScoreImport` + Steam screenshot dir), match memory stats (`TeamStatsFor`, `PlayerRatingsFor`),
OBS video (`VideoCapture`).
- Team talks: `TalkAvailable` / `ApplyTeamTalk(fixture, preMatch, tone)` / `TalkHint`.
**Needs design (b)**: pre-match screen (XIs, odds via `MatchOdds`, opposition briefing, team talk)
and post-match report (score, scorers, ratings grid `PlayerRatingsFor`, stats, talk, morale swings).

## 7. Squad management beyond tactics **(a)**
`SuggestXi()` (assistant picks), `RepairInvalidXis`, play-time statuses
(`SetPlayTimeStatus` — Star/First-Team/Rotation/Fringe/Youth with expected starts + wage ask),
private talks `TalkTo(pid, praise|criticise)`.

## 8. Loans **(b, small)**  `LoanOut/LoanIn/RecallLoan`, `ActiveLoans()` — needs a home in Market/Squad.

## 9. Staff **(b, small)**  backroom: `MyBackroom()`, `StaffMarket(role)`, `HireStaffPerson(id)`;
staff quality feeds training/scouting/analysis lines. Needs hire-flow design (list → compare → hire).

## 10. Board & finances **(a)**
`RequestBudget()`, facility levels + `UpgradeTrainingGround/UpgradeAcademy` (costs scale),
`Finances` ledger, objectives (`EnsureObjectives`, `MidSeasonReview`, `EvaluateObjectives`),
fan happiness (`FanHappiness/FanLabel`). Board page needs the levers wired (buttons exist in design).

## 11. Manager career **(b)**
Reputation ladder, sackings (`IsSacked`), `JobOffers()` → `AcceptJobOffer(teamId)` mid-career club
moves, `CareerSummary`, season rollover `RollCareerAtSeasonEnd` + `AdvanceToNextSeason()`.
**Needs design**: job-offer inbox flow + season-end review ceremony.

## 12. Living world **(a — engine-driven, no UI needed)**
`SessionWorld`: Elo per club, CPU transfer market between clubs, cup draws (National/League/
Continental), retirement/rollover. Runs off matchday ticks; surfaces via inbox + transfers feed.

## 13. History & stats **(a, read-only)**
Season archive, per-season tables, honours, top scorers/assists, player career history, club records.

## 14. Cups **(a)**  CupSpec rounds exist; Fixtures already shows ties; bracket view is cosmetic (c).

## 15. Academy / youth intake **(c)** — engine has academy table + intake stubs; youth-teams vision
(U18/U21 promote/demote, youth leagues) is design-and-engine work for the next phase.

---

# §B — Claude Design brief (bucket b)

Design the **interaction states** below in the existing Floodlit system (project
`Form wireframes and mockups`, file `Master League.dc.html`). Screens exist; these are flows.
For each: render every state, the control that advances it, and the failure/dead states.

1. **Training** — squad list with per-player focus pill (position groups: GK/DEF/MID/FWD specifics)
   + skill-course picker (only learnable skills), active courses with 6-session progress bars,
   completion celebration → inbox. Player dev tab: personality line, determination et al. (1–20),
   potential stars, season-by-season overall curve.
2. **Scouting missions** — one-active-mission board: pick kind (player/club/next opponent) →
   target search → 2-matchday progress → report card arrives (player: ability ranges narrow;
   club: style + key player; opposition: briefing + suggestion chip on Tactics).
   Market rows: knowledge % bar; attributes as ranges (66–79) until scouted; reveal animation.
3. **Pre-match** — fixture hero, both XIs with ratings, `MatchOdds` outlook, opposition briefing
   (if scouted), team-talk tone picker (Calm/Fire/Demand) with hint line, "Play in eFootball" CTA.
4. **Post-match report** — final score + scorer timeline (XI-driven pickers, no free text),
   team stats bars (possession/shots/etc. from match memory), player ratings grid + MOTM,
   post-match talk, morale/fans/board deltas, "CPU played N other fixtures" strip.
5. **Job offers & season end** — sack/offer letter states, accept-move confirmation (squad/board
   preview), season review ceremony: final table, objectives verdict, honours, rep change.
6. **Loans + staff hiring** (small) — loan in/out rows with recall; staff market compare-and-hire.

Constraints: 1440×920 frames, Floodlit tokens, states side-by-side per flow (like §1d storyboard),
placeholder crests/faces. Name each frame `NN · <flow> · <state>`.
