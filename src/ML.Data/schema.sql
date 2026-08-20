-- ML.Data master schema. The single source of truth for the Master League.
-- The game's dt200 is a render target compiled FROM this DB; nothing here is ever
-- authoritatively read back from the game except match results.
--
-- Design notes:
--  * A row that mirrors real eFootball data carries its base id (base_pid / base_team_id)
--    so the compiler keeps the real record (real face, real attributes) instead of
--    regenerating it. is_custom = 1 rows are authored from scratch.
--  * Every id we control is an INTEGER we assign; the game-facing ids (pid, team_id,
--    formation_id) are stored explicitly so the compiler is deterministic.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- world

CREATE TABLE IF NOT EXISTS leagues (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    tier               INTEGER NOT NULL,
    promotion_places   INTEGER NOT NULL DEFAULT 0,
    relegation_places  INTEGER NOT NULL DEFAULT 0,
    competition_slot   INTEGER,               -- CompetitionUnit id this renders into
    logo_path          TEXT                   -- league badge asset
);

CREATE TABLE IF NOT EXISTS teams (
    id            INTEGER PRIMARY KEY,         -- our id
    game_team_id  INTEGER NOT NULL UNIQUE,     -- the Team.bin team id it compiles to
    base_team_id  INTEGER,                     -- non-null: reuse this real team slot
    is_custom     INTEGER NOT NULL DEFAULT 0,
    name          TEXT NOT NULL,
    short_name    TEXT,
    league_id     INTEGER REFERENCES leagues(id),
    budget        INTEGER NOT NULL DEFAULT 0,
    home_stadium  TEXT,
    primary_color TEXT,
    secondary_color TEXT,
    kit_home_path TEXT,
    kit_away_path TEXT,
    logo_path     TEXT
);

CREATE TABLE IF NOT EXISTS coaches (
    id            INTEGER PRIMARY KEY,
    game_coach_id INTEGER NOT NULL,
    team_id       INTEGER NOT NULL REFERENCES teams(id),
    name          TEXT NOT NULL,
    nationality   TEXT
);

-- ---------------------------------------------------------------- players

CREATE TABLE IF NOT EXISTS players (
    id            INTEGER PRIMARY KEY,         -- our id
    game_pid      INTEGER NOT NULL UNIQUE,     -- external PID it compiles to
    base_pid      INTEGER,                     -- non-null: reuse this real player record
    donor_pid     INTEGER,                     -- custom players clone this record's bytes
    is_custom     INTEGER NOT NULL DEFAULT 0,
    name          TEXT NOT NULL,
    short_name    TEXT,
    position      TEXT NOT NULL,               -- GK/CB/.../CF
    age           INTEGER,
    dob           TEXT,
    nationality   TEXT,
    height_cm     INTEGER,
    weight_kg     INTEGER,
    overall_rating INTEGER,
    portrait_path TEXT                          -- face/portrait asset
);

-- abilities keyed by name so we can carry the full FM-style attribute set without a
-- 40-column table; the compiler maps known keys onto Player.bin bit fields.
CREATE TABLE IF NOT EXISTS player_attributes (
    player_id  INTEGER NOT NULL REFERENCES players(id),
    attribute  TEXT NOT NULL,                  -- e.g. finishing, tackling, speed
    value      INTEGER NOT NULL,
    PRIMARY KEY (player_id, attribute)
);

CREATE TABLE IF NOT EXISTS player_playstyles (
    player_id  INTEGER NOT NULL REFERENCES players(id),
    playstyle  TEXT NOT NULL,
    PRIMARY KEY (player_id, playstyle)
);

-- squad membership (compiles to PlayerAssignment). One row per player per team.
CREATE TABLE IF NOT EXISTS squad_members (
    team_id       INTEGER NOT NULL REFERENCES teams(id),
    player_id     INTEGER NOT NULL REFERENCES players(id),
    squad_number  INTEGER NOT NULL,
    slot          INTEGER NOT NULL,            -- position in the squad list (0-based)
    role          INTEGER NOT NULL DEFAULT 0,  -- captain / set-piece bit mask
    PRIMARY KEY (team_id, player_id)
);

CREATE TABLE IF NOT EXISTS contracts (
    player_id      INTEGER NOT NULL REFERENCES players(id),
    team_id        INTEGER NOT NULL REFERENCES teams(id),
    weekly_wage    INTEGER NOT NULL DEFAULT 0,
    expires_season INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, team_id)
);

-- matchday condition driving AI XI selection (ML.Core.Selection). Missing row = fresh player:
-- callers default fatigue 0 / form 6.5 / not injured. injured_until_md: the player is out
-- THROUGH that matchday (misses matchdays <= injured_until_md); NULL = fit.
CREATE TABLE IF NOT EXISTS player_condition (
    player_id        INTEGER PRIMARY KEY REFERENCES players(id),
    fatigue          INTEGER NOT NULL DEFAULT 0,
    injured_until_md INTEGER,
    form             REAL NOT NULL DEFAULT 6.5
);

-- ---------------------------------------------------------------- tactics

CREATE TABLE IF NOT EXISTS formations (
    id     INTEGER PRIMARY KEY,                -- game formation_id
    name   TEXT NOT NULL                       -- "4-2-3-1" etc.
);

CREATE TABLE IF NOT EXISTS formation_slots (
    formation_id INTEGER NOT NULL REFERENCES formations(id),
    slot_index   INTEGER NOT NULL,             -- 0..10
    position     INTEGER NOT NULL,             -- role code 0-12
    x            INTEGER NOT NULL,             -- pitch width 12-92 (centre 52)
    y            INTEGER NOT NULL,             -- depth from own goal 3-43
    PRIMARY KEY (formation_id, slot_index)
);

-- two rows per team: phase 0 = in-possession shape, phase 1 = out-of-possession.
-- distinct formation_ids per phase give fluid formations.
CREATE TABLE IF NOT EXISTS team_tactics (
    team_id      INTEGER NOT NULL REFERENCES teams(id),
    phase        INTEGER NOT NULL,             -- 0 in-possession, 1 out
    formation_id INTEGER NOT NULL REFERENCES formations(id),
    style        INTEGER NOT NULL DEFAULT 0,   -- attacking style enum 0-5
    PRIMARY KEY (team_id, phase)
);

-- ---------------------------------------------------------------- season state

CREATE TABLE IF NOT EXISTS seasons (
    id         INTEGER PRIMARY KEY,
    year       INTEGER NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fixtures (
    id           INTEGER PRIMARY KEY,
    season_id    INTEGER NOT NULL REFERENCES seasons(id),
    league_id    INTEGER NOT NULL REFERENCES leagues(id),
    matchday     INTEGER NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES teams(id),
    away_team_id INTEGER NOT NULL REFERENCES teams(id),
    played       INTEGER NOT NULL DEFAULT 0,
    kind         TEXT NOT NULL DEFAULT 'league'   -- 'league' | 'friendly' (preseason) | 'cup'
);

CREATE TABLE IF NOT EXISTS results (
    fixture_id      INTEGER PRIMARY KEY REFERENCES fixtures(id),
    home_goals      INTEGER NOT NULL,
    away_goals      INTEGER NOT NULL,
    stats_json      TEXT,
    screenshot_path TEXT
);

CREATE TABLE IF NOT EXISTS match_events (
    id         INTEGER PRIMARY KEY,
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    player_id  INTEGER REFERENCES players(id),
    event_type TEXT NOT NULL,                  -- goal, assist, yellow, red, sub
    minute     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transfers (
    id           INTEGER PRIMARY KEY,
    player_id    INTEGER NOT NULL REFERENCES players(id),
    from_team_id INTEGER REFERENCES teams(id),
    to_team_id   INTEGER REFERENCES teams(id),
    fee          INTEGER NOT NULL DEFAULT 0,
    window       TEXT,
    season_id    INTEGER REFERENCES seasons(id)
);

-- ---------------------------------------------------------------- manager (MFL parity)

CREATE TABLE IF NOT EXISTS board_confidence (
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    season_id   INTEGER NOT NULL REFERENCES seasons(id),
    confidence  INTEGER NOT NULL DEFAULT 50,   -- 0-100
    expectation TEXT,                          -- "mid-table", "promotion", ...
    PRIMARY KEY (team_id, season_id)
);

CREATE TABLE IF NOT EXISTS morale (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    value     INTEGER NOT NULL DEFAULT 50
);

CREATE TABLE IF NOT EXISTS inbox (
    id            INTEGER PRIMARY KEY,
    season_id     INTEGER REFERENCES seasons(id),
    matchday      INTEGER,
    category      TEXT NOT NULL,               -- board, player, media, transfer
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    is_read       INTEGER NOT NULL DEFAULT 0,
    requires_action INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_squad_team ON squad_members(team_id);
CREATE INDEX IF NOT EXISTS ix_fixtures_season_md ON fixtures(season_id, matchday);
CREATE INDEX IF NOT EXISTS ix_players_team ON squad_members(player_id);

-- ---------------------------------------------------------------- world (cup, academy, honours)

-- Knockout cup ties live in fixtures (kind='cup', league_id=9002); this records each season's
-- silverware for the Roll of Honour.
CREATE TABLE IF NOT EXISTS honours (
    season_id   INTEGER NOT NULL,
    competition TEXT    NOT NULL,              -- 'league' | 'division2' | 'cup'
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    PRIMARY KEY (season_id, competition)
);

-- Youth players attached to a club but not yet in its senior squad.
CREATE TABLE IF NOT EXISTS academy (
    player_id     INTEGER PRIMARY KEY REFERENCES players(id),
    team_id       INTEGER NOT NULL REFERENCES teams(id),
    joined_season INTEGER NOT NULL
);

-- Per-player match ratings (typed in from eFootball's post-match screen for your games).
CREATE TABLE IF NOT EXISTS player_match_ratings (
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    player_id  INTEGER NOT NULL REFERENCES players(id),
    rating     REAL    NOT NULL,
    PRIMARY KEY (fixture_id, player_id)
);

-- Weekly training focus per player: an ability group ('shooting','passing','defending',
-- 'physical','pace') or a new position ('pos:LB'). Progress ticks on recorded matchdays.
CREATE TABLE IF NOT EXISTS training_focus (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    focus     TEXT    NOT NULL,
    progress  INTEGER NOT NULL DEFAULT 0
);

-- Positions a player has LEARNED beyond their registered one (role training, 6 sessions).
CREATE TABLE IF NOT EXISTS player_positions (
    player_id INTEGER NOT NULL REFERENCES players(id),
    position  TEXT    NOT NULL,
    PRIMARY KEY (player_id, position)
);

-- Backroom staff (FM parity phase A): one hired member per role, quality drives effects
-- (coach -> training speed, physio -> injury recovery, scout -> report depth, assistant -> advice).
CREATE TABLE IF NOT EXISTS staff (
    team_id INTEGER NOT NULL REFERENCES teams(id),
    role    TEXT    NOT NULL,               -- 'Assistant' | 'Coach' | 'Scout' | 'Physio'
    name    TEXT    NOT NULL,
    quality INTEGER NOT NULL DEFAULT 3,     -- 1-5 stars
    wage    INTEGER NOT NULL DEFAULT 2000,  -- weekly, joins the wage bill
    PRIMARY KEY (team_id, role)
);

-- Scouting missions (FM phase A2): the scout watches a club or a player; the report unlocks
-- after ready_md. Depth of the rendered report scales with the scout's quality at view time.
CREATE TABLE IF NOT EXISTS scout_jobs (
    id          INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,              -- 'club' | 'player'
    target_id   INTEGER NOT NULL,
    started_md  INTEGER NOT NULL,
    ready_md    INTEGER NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0
);

-- Manager promises (FM phase B2): "more starts" / "a new contract", tracked to a deadline.
-- Kept promises lift morale; broken ones crater it.
CREATE TABLE IF NOT EXISTS promises (
    id          INTEGER PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    kind        TEXT    NOT NULL,              -- 'starts' | 'contract'
    made_md     INTEGER NOT NULL,
    deadline_md INTEGER NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0    -- 0 open, 1 kept, 2 broken
);

-- FM-style character layer (P1): visible Determination + hidden traits (all 1-20), seeded
-- deterministically per player on first read; the personality name derives from these.
CREATE TABLE IF NOT EXISTS player_traits (
    player_id       INTEGER PRIMARY KEY REFERENCES players(id),
    determination   INTEGER NOT NULL,
    professionalism INTEGER NOT NULL,
    ambition        INTEGER NOT NULL,
    temperament     INTEGER NOT NULL
);

-- eFootball Player Skills a player carries (learned on the training ground or seeded innate).
CREATE TABLE IF NOT EXISTS player_skills (
    player_id INTEGER NOT NULL REFERENCES players(id),
    skill     TEXT    NOT NULL,
    source    TEXT    NOT NULL DEFAULT 'trained',   -- 'trained' | 'innate'
    PRIMARY KEY (player_id, skill)
);

-- Active skill training: one skill in progress per player; sessions tick each matchweek and
-- the target session count comes from determination + professionalism + coaching.
CREATE TABLE IF NOT EXISTS skill_training (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    team_id   INTEGER NOT NULL REFERENCES teams(id),
    skill     TEXT    NOT NULL,
    progress  INTEGER NOT NULL DEFAULT 0,
    target    INTEGER NOT NULL
);

-- P2 living world: stored potential (the ceiling development grows toward; academy stars are
-- real now), and FM-style board objectives with importance tiers, evaluated mid-season + end.
CREATE TABLE IF NOT EXISTS player_potential (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    potential INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS objectives (
    id         INTEGER PRIMARY KEY,
    season_id  INTEGER NOT NULL REFERENCES seasons(id),
    team_id    INTEGER NOT NULL REFERENCES teams(id),
    kind       TEXT    NOT NULL,   -- 'league_finish' | 'cup_run' | 'youth_apps' | 'home_goals'
    target     INTEGER NOT NULL,   -- position / round size / apps / goals
    importance TEXT    NOT NULL,   -- 'critical' | 'important' | 'bonus'
    status     INTEGER NOT NULL DEFAULT 0   -- 0 open, 1 met, 2 failed
);

-- FM-style knowledge (P5): how well YOU know each player this save. Baselines (own squad,
-- league rivals) are derived in code; stored rows come from scouting and facing a club.
CREATE TABLE IF NOT EXISTS player_knowledge (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    level     INTEGER NOT NULL DEFAULT 0
);

-- Appearance (P6 imagery): skin tone 1 (lightest) - 6 (darkest), the PlayerAppearance.bin
-- field recovered by portrait correlation. Sources: 'bin' (read from the game),
-- 'portrait' (sampled from the player's own portrait), 'seeded' (generated).
CREATE TABLE IF NOT EXISTS player_appearance (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    skin_tone INTEGER NOT NULL,
    source    TEXT    NOT NULL DEFAULT 'seeded'
);

-- Live transfer negotiations with selling clubs (P5): one open negotiation per target.
CREATE TABLE IF NOT EXISTS negotiations (
    player_id   INTEGER PRIMARY KEY REFERENCES players(id),
    seller_id   INTEGER NOT NULL,               -- 0 = free agent (no club step)
    round       INTEGER NOT NULL DEFAULT 1,
    ask         INTEGER NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'open' -- 'open' | 'agreed' | 'dead'
);

-- FM-style playing-time status (P5): the manager's promise of minutes, the player's
-- expectation, and the AI's willingness to sell all hang off this.
CREATE TABLE IF NOT EXISTS player_status (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    status    TEXT    NOT NULL
);

-- News imagery (P6): letters about a player carry his id so the feed can show his face.
-- (Existing DBs migrate via ALTER in tools; CREATE TABLE IF NOT EXISTS covers fresh ones
-- through the column list below being additive-only.)

-- Loans (P-next): players parked at another club for the season; recalls from the January
-- window; everyone comes home at rollover. direction: 'out' = yours at a host, 'in' = theirs
-- with you.
-- The staff DATABASE (FM-style): persistent individual people with 1-20 attributes and
-- tactical preferences. team_id NULL = free agent. One person per (team, role) is enforced
-- in code; firing returns the person to the pool rather than deleting them.
CREATE TABLE IF NOT EXISTS staff_people (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL,
    age              INTEGER NOT NULL,
    role             TEXT    NOT NULL,   -- Assistant Manager | Director of Football | Coach |
                                         -- GK Coach | Fitness Coach | Youth Coach | Physio |
                                         -- Scout | Analyst
    coaching         INTEGER NOT NULL,   -- all attributes 1-20, FM-style
    youth            INTEGER NOT NULL,
    fitness          INTEGER NOT NULL,
    physio           INTEGER NOT NULL,
    judging_ability  INTEGER NOT NULL,
    judging_potential INTEGER NOT NULL,
    tactical         INTEGER NOT NULL,
    man_management   INTEGER NOT NULL,
    pref_formation   TEXT    NOT NULL,   -- e.g. '4-3-3'
    pref_style       TEXT    NOT NULL,   -- Possession | High Press | Counter-Attack | Direct | Balanced
    wage             INTEGER NOT NULL,   -- weekly
    team_id          INTEGER,            -- NULL = free agent
    contract_until   INTEGER             -- season id the deal runs to (employed only)
);

-- Weekly club history: one row per matchday pass, feeds the trend charts (item 11).
CREATE TABLE IF NOT EXISTS club_history (
    season_id  INTEGER NOT NULL,
    matchday   INTEGER NOT NULL,
    team_id    INTEGER NOT NULL,
    balance    INTEGER NOT NULL,
    fans       INTEGER NOT NULL,
    board      INTEGER NOT NULL,
    elo        INTEGER NOT NULL,
    PRIMARY KEY (season_id, matchday, team_id)
);

-- Rivalries: Konami Derby.bin import (tools/derby_import.py) + synthesized career rivals.
CREATE TABLE IF NOT EXISTS team_rivals (
    team_id   INTEGER NOT NULL,
    rival_id  INTEGER NOT NULL,
    intensity INTEGER NOT NULL DEFAULT 5,   -- 1 fierce, 5 moderate, 6 mild
    PRIMARY KEY (team_id, rival_id)
);

CREATE TABLE IF NOT EXISTS loans (
    player_id  INTEGER PRIMARY KEY REFERENCES players(id),
    owner_team INTEGER NOT NULL,
    host_team  INTEGER NOT NULL,
    season_id  INTEGER NOT NULL,
    direction  TEXT    NOT NULL
);
