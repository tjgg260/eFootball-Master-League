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
    played       INTEGER NOT NULL DEFAULT 0
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
