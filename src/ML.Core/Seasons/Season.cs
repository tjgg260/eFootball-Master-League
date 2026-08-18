using ML.Core.Domain;
using ML.Core.Scheduling;

namespace ML.Core.Seasons;

public enum SeasonState
{
    NotStarted,
    InProgress,
    Complete,
}

public sealed class Season
{
    private readonly List<Fixture> _fixtures;
    private readonly Dictionary<int, List<Fixture>> _byMatchday;

    private Season(
        int id,
        int year,
        LeagueId leagueId,
        IReadOnlyList<TeamId> teams,
        IReadOnlyList<Fixture> fixtures,
        TeamId? userTeam)
    {
        Id = id;
        Year = year;
        LeagueId = leagueId;
        Teams = teams;
        UserTeam = userTeam;

        _fixtures = fixtures.ToList();
        _byMatchday = _fixtures
            .GroupBy(f => f.Matchday)
            .ToDictionary(g => g.Key, g => g.ToList());

        TotalMatchdays = _byMatchday.Count == 0 ? 0 : _byMatchday.Keys.Max();
    }

    public int Id { get; }

    public int Year { get; }

    public LeagueId LeagueId { get; }

    public IReadOnlyList<TeamId> Teams { get; }

    /// <summary>The club the user manages, or null for a fully simulated division.</summary>
    public TeamId? UserTeam { get; }

    public IReadOnlyList<Fixture> Fixtures => _fixtures;

    public int TotalMatchdays { get; }

    /// <summary>1-based. Zero before kick-off; TotalMatchdays + 1 once the season is done.</summary>
    public int CurrentMatchday { get; private set; }

    public SeasonState State =>
        CurrentMatchday == 0 ? SeasonState.NotStarted
        : CurrentMatchday > TotalMatchdays ? SeasonState.Complete
        : SeasonState.InProgress;

    public static Season Create(
        int id,
        int year,
        League league,
        IReadOnlyList<TeamId> teams,
        IRandomSource random,
        TeamId? userTeam = null)
    {
        ArgumentNullException.ThrowIfNull(league);
        ArgumentNullException.ThrowIfNull(teams);
        ArgumentNullException.ThrowIfNull(random);

        if (userTeam is { } chosen && !teams.Contains(chosen))
        {
            throw new ArgumentException(
                $"Chosen club {chosen} is not in {league.Name}.", nameof(userTeam));
        }

        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(teams, random);
        return new Season(id, year, league.Id, teams.ToList(), fixtures, userTeam);
    }

    public IReadOnlyList<Fixture> FixturesOn(int matchday) =>
        _byMatchday.TryGetValue(matchday, out var fixtures)
            ? fixtures
            : Array.Empty<Fixture>();

    /// <summary>The user's match on a given matchday, or null if they are idle (odd-sized division).</summary>
    public Fixture? UserFixtureOn(int matchday) =>
        UserTeam is { } userTeam
            ? FixturesOn(matchday).FirstOrDefault(f => f.Involves(userTeam))
            : null;

    public IReadOnlyList<Fixture> FixturesFor(TeamId teamId) =>
        _fixtures.Where(f => f.Involves(teamId)).ToList();

    public bool AllFixturesPlayed => _fixtures.All(f => f.IsPlayed);

    internal void BeginIfNotStarted()
    {
        if (CurrentMatchday == 0)
        {
            CurrentMatchday = 1;
        }
    }

    internal void CompleteCurrentMatchday()
    {
        if (State != SeasonState.InProgress)
        {
            throw new InvalidOperationException($"Season {Id} is {State}; nothing to complete.");
        }

        CurrentMatchday++;
    }

    public override string ToString() =>
        $"Season {Year} (league {LeagueId}) — MD {CurrentMatchday}/{TotalMatchdays}, {State}";
}
