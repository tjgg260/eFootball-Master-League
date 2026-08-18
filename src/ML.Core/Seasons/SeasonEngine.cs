using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Simulation;
using ML.Core.Tables;

namespace ML.Core.Seasons;

public enum AdvanceOutcome
{
    /// <summary>Every fixture on the matchday is in; the season has moved on.</summary>
    MatchdayCompleted,

    /// <summary>
    /// The CPU games are done but the user's own match has not been entered yet. The matchday
    /// does not advance until it is — that hand-off is where Phase 3's screenshot import lands.
    /// </summary>
    AwaitingUserResult,

    SeasonAlreadyComplete,
}

public sealed record AdvanceResult(
    AdvanceOutcome Outcome,
    int Matchday,
    IReadOnlyList<Fixture> SimulatedFixtures,
    SeasonState SeasonState);

/// <summary>
/// Drives a season forward one matchday at a time: simulate every game the user is not
/// playing, wait for theirs, then move on.
/// </summary>
public sealed class SeasonEngine
{
    private readonly World _world;
    private readonly IMatchSimulator _simulator;

    public SeasonEngine(World world, IMatchSimulator simulator)
    {
        _world = world ?? throw new ArgumentNullException(nameof(world));
        _simulator = simulator ?? throw new ArgumentNullException(nameof(simulator));
    }

    public AdvanceResult AdvanceMatchday(Season season)
    {
        ArgumentNullException.ThrowIfNull(season);

        if (season.State == SeasonState.Complete)
        {
            return new AdvanceResult(
                AdvanceOutcome.SeasonAlreadyComplete,
                season.CurrentMatchday,
                Array.Empty<Fixture>(),
                season.State);
        }

        season.BeginIfNotStarted();
        var matchday = season.CurrentMatchday;

        var simulated = SimulateFixtures(
            season.FixturesOn(matchday).Where(f => !f.IsPlayed && !IsUserFixture(season, f)));

        var userFixture = season.UserFixtureOn(matchday);
        if (userFixture is { IsPlayed: false })
        {
            return new AdvanceResult(
                AdvanceOutcome.AwaitingUserResult, matchday, simulated, season.State);
        }

        season.CompleteCurrentMatchday();
        return new AdvanceResult(
            AdvanceOutcome.MatchdayCompleted, matchday, simulated, season.State);
    }

    /// <summary>
    /// Files the user's own result for the current matchday. Phase 3 calls this once the
    /// confirm-and-correct screen is accepted; then call <see cref="AdvanceMatchday"/> again.
    /// </summary>
    public void RecordUserResult(Season season, MatchResult result)
    {
        ArgumentNullException.ThrowIfNull(season);

        if (season.UserTeam is null)
        {
            throw new InvalidOperationException($"Season {season.Id} has no user club.");
        }

        if (season.State == SeasonState.Complete)
        {
            throw new InvalidOperationException($"Season {season.Id} is already complete.");
        }

        season.BeginIfNotStarted();

        var fixture = season.UserFixtureOn(season.CurrentMatchday)
            ?? throw new InvalidOperationException(
                $"The user's club has no fixture on matchday {season.CurrentMatchday}.");

        fixture.RecordResult(result);
    }

    /// <summary>
    /// Runs the whole season out, the user's own games included. This is the "simulate rest of
    /// season" button, and it is what the multi-season tests drive.
    /// </summary>
    public void SimulateEntireSeason(Season season)
    {
        ArgumentNullException.ThrowIfNull(season);

        while (season.State != SeasonState.Complete)
        {
            season.BeginIfNotStarted();
            SimulateFixtures(season.FixturesOn(season.CurrentMatchday).Where(f => !f.IsPlayed));
            season.CompleteCurrentMatchday();
        }
    }

    public IReadOnlyList<LeagueTableRow> TableFor(Season season) =>
        LeagueTable.Build(season.Teams, season.Fixtures);

    public TeamStrength StrengthOf(TeamId teamId) =>
        SquadStrength.Evaluate(_world.SquadOf(teamId));

    private static bool IsUserFixture(Season season, Fixture fixture) =>
        season.UserTeam is { } userTeam && fixture.Involves(userTeam);

    private List<Fixture> SimulateFixtures(IEnumerable<Fixture> fixtures)
    {
        // Squads cannot change inside a matchday, so one strength lookup per club is enough.
        var strengths = new Dictionary<TeamId, TeamStrength>();
        var played = new List<Fixture>();

        foreach (var fixture in fixtures)
        {
            var home = StrengthFor(strengths, fixture.HomeTeam);
            var away = StrengthFor(strengths, fixture.AwayTeam);
            fixture.RecordResult(_simulator.Simulate(home, away));
            played.Add(fixture);
        }

        return played;
    }

    private TeamStrength StrengthFor(Dictionary<TeamId, TeamStrength> cache, TeamId teamId)
    {
        if (!cache.TryGetValue(teamId, out var strength))
        {
            strength = SquadStrength.Evaluate(_world.SquadOf(teamId));
            cache[teamId] = strength;
        }

        return strength;
    }
}
