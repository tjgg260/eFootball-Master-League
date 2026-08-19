using ML.Core.Domain;
using ML.Core.Management;
using ML.Core.Scheduling;
using ML.Core.Tables;
using ML.Data;

namespace ML.App;

/// <summary>
/// The running Master League the UI binds to: the master DB, the chosen club, and its live
/// manager state (board confidence, morale, finances). Bridges DB rows to ML.Core so the league
/// table and standings come from the tested engine rather than duplicated SQL.
/// </summary>
public sealed class Session
{
    public Session(MasterDb db, int currentTeamId, int seasonId)
    {
        Db = db;
        Repo = new Repository(db);
        CurrentTeamId = currentTeamId;
        SeasonId = seasonId;

        var team = Repo.Teams().Single(t => t.Id == currentTeamId);
        Board = new BoardConfidence(Expectation.Playoffs, starting: 58);
        Morale = new Morale(60);
        Finances = new Finances(team.Budget);
        CurrentTeamName = team.Name;
        LeagueId = team.LeagueId ?? 0;
        LeagueName = Repo.Leagues().FirstOrDefault(l => l.Id == LeagueId)?.Name ?? "League";
    }

    public MasterDb Db { get; }
    public Repository Repo { get; }
    public int CurrentTeamId { get; }
    public int SeasonId { get; }
    public string CurrentTeamName { get; }
    public int LeagueId { get; }
    public string LeagueName { get; }
    public BoardConfidence Board { get; }
    public Morale Morale { get; }
    public Finances Finances { get; }

    public IReadOnlyList<TeamRow> LeagueTeams() => Repo.TeamsIn(LeagueId);

    public string TeamName(int teamId) => Repo.Teams().FirstOrDefault(t => t.Id == teamId)?.Name ?? "?";

    /// <summary>League table computed by the ML.Core engine from played DB fixtures.</summary>
    public IReadOnlyList<LeagueTableRow> Table()
    {
        var teams = LeagueTeams().Select(t => new TeamId(t.Id)).ToList();
        var fixtures = new List<Fixture>();
        foreach (var f in Repo.Fixtures(SeasonId).Where(f => f.LeagueId == LeagueId && f.Kind == "league"))
        {
            var fixture = new Fixture(f.Id, f.Matchday, new TeamId(f.HomeTeamId), new TeamId(f.AwayTeamId));
            if (f.Played)
            {
                var r = ResultFor(f.Id);
                if (r is not null)
                {
                    fixture.RecordResult(new MatchResult(r.HomeGoals, r.AwayGoals));
                }
            }
            fixtures.Add(fixture);
        }
        return LeagueTable.Build(teams, fixtures);
    }

    public int CurrentPosition()
    {
        var row = Table().FirstOrDefault(r => r.TeamId.Value == CurrentTeamId);
        return row?.Position ?? 0;
    }

    public IReadOnlyList<FixtureRow> UpcomingFixtures(int count = 5) =>
        Repo.Fixtures(SeasonId)
            .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && !f.Played)
            .Take(count).ToList();

    public IReadOnlyList<FixtureRow> RecentResults(int count = 5) =>
        Repo.Fixtures(SeasonId)
            .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && f.Played)
            .Reverse().Take(count).ToList();

    public ResultRow? ResultFor(int fixtureId)
    {
        _results ??= LoadResults();
        return _results.TryGetValue(fixtureId, out var res) ? res : null;
    }

    private Dictionary<int, ResultRow>? _results;

    private Dictionary<int, ResultRow> LoadResults()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT fixture_id,home_goals,away_goals,stats_json,screenshot_path FROM results";
        using var reader = cmd.ExecuteReader();
        var dict = new Dictionary<int, ResultRow>();
        while (reader.Read())
        {
            dict[reader.GetInt32(0)] = new ResultRow
            {
                FixtureId = reader.GetInt32(0),
                HomeGoals = reader.GetInt32(1),
                AwayGoals = reader.GetInt32(2),
                StatsJson = reader.IsDBNull(3) ? null : reader.GetString(3),
                ScreenshotPath = reader.IsDBNull(4) ? null : reader.GetString(4),
            };
        }
        return dict;
    }

    public IReadOnlyList<(PlayerRow Player, SquadMemberRow Slot)> Squad()
    {
        var players = Repo.Players().ToDictionary(p => p.Id);
        return Repo.Squad(CurrentTeamId)
            .Where(s => players.ContainsKey(s.PlayerId))
            .Select(s => (players[s.PlayerId], s))
            .ToList();
    }
}
