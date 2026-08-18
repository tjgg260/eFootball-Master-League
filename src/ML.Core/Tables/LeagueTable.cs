using ML.Core.Domain;
using ML.Core.Scheduling;

namespace ML.Core.Tables;

/// <summary>
/// Builds a league table from played fixtures.
///
/// Tiebreakers run points, then goal difference, then goals for, then head-to-head, as set out
/// in the build plan. Head-to-head is resolved by building a mini-table over only the fixtures
/// played between the tied clubs. Any club still level after that is ordered by id, so the
/// table is always deterministic — a career save that reorders itself between two reads of the
/// same data would be worse than a slightly arbitrary tiebreak.
/// </summary>
public static class LeagueTable
{
    public static IReadOnlyList<LeagueTableRow> Build(
        IEnumerable<TeamId> teams,
        IEnumerable<Fixture> fixtures)
    {
        ArgumentNullException.ThrowIfNull(teams);
        ArgumentNullException.ThrowIfNull(fixtures);

        var members = teams.ToHashSet();
        if (members.Count == 0)
        {
            return Array.Empty<LeagueTableRow>();
        }

        var relevant = fixtures
            .Where(f => f.IsPlayed && members.Contains(f.HomeTeam) && members.Contains(f.AwayTeam))
            .ToList();

        var tallies = members.ToDictionary(id => id, _ => new Tally());
        foreach (var fixture in relevant)
        {
            Apply(tallies, fixture);
        }

        var ordered = members
            .OrderByDescending(id => tallies[id].Points)
            .ThenByDescending(id => tallies[id].GoalDifference)
            .ThenByDescending(id => tallies[id].GoalsFor)
            .ToList();

        var resolved = ResolveHeadToHead(ordered, tallies, relevant);

        return resolved
            .Select((id, index) => ToRow(id, index + 1, tallies[id]))
            .ToList();
    }

    /// <summary>
    /// Walks the ordered list, finds runs of clubs level on points/GD/GF, and re-sorts each run
    /// by its own mini-table.
    /// </summary>
    private static List<TeamId> ResolveHeadToHead(
        List<TeamId> ordered,
        Dictionary<TeamId, Tally> tallies,
        List<Fixture> fixtures)
    {
        var result = new List<TeamId>(ordered.Count);

        var start = 0;
        while (start < ordered.Count)
        {
            var end = start + 1;
            while (end < ordered.Count && LevelOnPrimaryCriteria(tallies[ordered[start]], tallies[ordered[end]]))
            {
                end++;
            }

            var run = ordered.GetRange(start, end - start);
            result.AddRange(run.Count == 1 ? run : SortByMiniTable(run, fixtures));
            start = end;
        }

        return result;
    }

    private static bool LevelOnPrimaryCriteria(Tally a, Tally b) =>
        a.Points == b.Points && a.GoalDifference == b.GoalDifference && a.GoalsFor == b.GoalsFor;

    private static List<TeamId> SortByMiniTable(List<TeamId> tied, List<Fixture> fixtures)
    {
        var group = tied.ToHashSet();
        var mini = tied.ToDictionary(id => id, _ => new Tally());

        foreach (var fixture in fixtures.Where(f => group.Contains(f.HomeTeam) && group.Contains(f.AwayTeam)))
        {
            Apply(mini, fixture);
        }

        return tied
            .OrderByDescending(id => mini[id].Points)
            .ThenByDescending(id => mini[id].GoalDifference)
            .ThenByDescending(id => mini[id].GoalsFor)
            .ThenBy(id => id.Value)
            .ToList();
    }

    private static void Apply(Dictionary<TeamId, Tally> tallies, Fixture fixture)
    {
        var result = fixture.Result!.Value;
        var home = tallies[fixture.HomeTeam];
        var away = tallies[fixture.AwayTeam];

        home.GoalsFor += result.HomeGoals;
        home.GoalsAgainst += result.AwayGoals;
        away.GoalsFor += result.AwayGoals;
        away.GoalsAgainst += result.HomeGoals;

        switch (result.Outcome)
        {
            case MatchOutcome.HomeWin:
                home.Won++;
                away.Lost++;
                break;
            case MatchOutcome.AwayWin:
                away.Won++;
                home.Lost++;
                break;
            default:
                home.Drawn++;
                away.Drawn++;
                break;
        }
    }

    private static LeagueTableRow ToRow(TeamId teamId, int position, Tally tally) => new()
    {
        TeamId = teamId,
        Position = position,
        Played = tally.Played,
        Won = tally.Won,
        Drawn = tally.Drawn,
        Lost = tally.Lost,
        GoalsFor = tally.GoalsFor,
        GoalsAgainst = tally.GoalsAgainst,
    };

    private sealed class Tally
    {
        public int Won;
        public int Drawn;
        public int Lost;
        public int GoalsFor;
        public int GoalsAgainst;

        public int Played => Won + Drawn + Lost;

        public int Points => (Won * LeagueTableRow.PointsForWin) + Drawn;

        public int GoalDifference => GoalsFor - GoalsAgainst;
    }
}
