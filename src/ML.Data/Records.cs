namespace ML.Data;

// Row records mirror the schema. Init-only properties (not positional) so Dapper maps by name
// and coerces SQLite's Int64/Int columns onto int/bool — the positional-constructor path does
// not coerce and fails on the width mismatch. Records keep value equality and `with`.

public sealed record LeagueRow
{
    public int Id { get; init; }
    public string Name { get; init; } = "";
    public int Tier { get; init; }
    public int PromotionPlaces { get; init; }
    public int RelegationPlaces { get; init; }
    public int? CompetitionSlot { get; init; }
    public string? LogoPath { get; init; }
}

public sealed record TeamRow
{
    public int Id { get; init; }
    public int GameTeamId { get; init; }
    public int? BaseTeamId { get; init; }
    public bool IsCustom { get; init; }
    public string Name { get; init; } = "";
    public string? ShortName { get; init; }
    public int? LeagueId { get; init; }
    public long Budget { get; init; }
    public string? HomeStadium { get; init; }
    public string? PrimaryColor { get; init; }
    public string? SecondaryColor { get; init; }
    public string? KitHomePath { get; init; }
    public string? KitAwayPath { get; init; }
    public string? LogoPath { get; init; }
}

public sealed record CoachRow
{
    public int Id { get; init; }
    public int GameCoachId { get; init; }
    public int TeamId { get; init; }
    public string Name { get; init; } = "";
    public string? Nationality { get; init; }
}

// PLAYER ids are long: the id namespaces run past Int32 (curated 45–46bn, generated ≥50bn).
// Team/league/fixture ids stay int — their namespaces are all well under 2^31.
public sealed record PlayerRow
{
    public long Id { get; init; }
    // A LONG. The world rebuild sets game_pid = id for every curated and generated record —
    // 306,185 of 401,149 players on the live save, every one of them past Int32 — and Dapper
    // mapping an int64 column into an int property does not truncate, it THROWS. So
    // Repository.SquadPlayers threw OverflowException for any club in the 45bn band, which is
    // Liverpool and Arsenal, and every screen built on Session.Squad() — Tactics first — died
    // before it existed. The write side (academy prospects, sample data) already fits.
    public long GamePid { get; init; }
    public int? BasePid { get; init; }
    public int? DonorPid { get; init; }
    public bool IsCustom { get; init; }
    public string Name { get; init; } = "";
    public string? ShortName { get; init; }
    public string Position { get; init; } = "";
    public int? Age { get; init; }
    public string? Dob { get; init; }
    public string? Nationality { get; init; }
    public int? HeightCm { get; init; }
    public int? WeightKg { get; init; }
    public int? OverallRating { get; init; }
    public string? PortraitPath { get; init; }
}

public sealed record PlayerAttributeRow
{
    public long PlayerId { get; init; }
    public string Attribute { get; init; } = "";
    public int Value { get; init; }
}

public sealed record SquadMemberRow
{
    public int TeamId { get; init; }
    public long PlayerId { get; init; }
    public int SquadNumber { get; init; }
    public int Slot { get; init; }
    public int Role { get; init; }
}

public sealed record PlayerConditionRow
{
    public long PlayerId { get; init; }
    public int Fatigue { get; init; }
    public int? InjuredUntilMd { get; init; }
    public double Form { get; init; }
}

public sealed record FormationRow
{
    public int Id { get; init; }
    public string Name { get; init; } = "";
}

public sealed record FormationSlotRow
{
    public int FormationId { get; init; }
    public int SlotIndex { get; init; }
    public int Position { get; init; }
    public int X { get; init; }
    public int Y { get; init; }
}

public sealed record TeamTacticsRow
{
    public int TeamId { get; init; }
    public int Phase { get; init; }
    public int FormationId { get; init; }
    public int Style { get; init; }
}

public sealed record SeasonRow
{
    public int Id { get; init; }
    public int Year { get; init; }
    public bool IsCurrent { get; init; }
}

public sealed record FixtureRow
{
    public int Id { get; init; }
    public int SeasonId { get; init; }
    public int LeagueId { get; init; }
    public int Matchday { get; init; }
    public int HomeTeamId { get; init; }
    public int AwayTeamId { get; init; }
    public bool Played { get; init; }
    public string Kind { get; init; } = "league";
}

public sealed record ResultRow
{
    public int FixtureId { get; init; }
    public int HomeGoals { get; init; }
    public int AwayGoals { get; init; }
    public string? StatsJson { get; init; }
    public string? ScreenshotPath { get; init; }
}

public sealed record InboxRow
{
    public int Id { get; init; }
    public int? SeasonId { get; init; }
    public int? Matchday { get; init; }
    public string Category { get; init; } = "";
    public string Subject { get; init; } = "";
    public string Body { get; init; } = "";
    public bool IsRead { get; init; }
    public bool RequiresAction { get; init; }
}

public sealed record BoardConfidenceRow
{
    public int TeamId { get; init; }
    public int SeasonId { get; init; }
    public int Confidence { get; init; }
    public string? Expectation { get; init; }
}
