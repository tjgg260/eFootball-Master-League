using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Tables;

namespace ML.Core.Tests;

public class LeagueTableTests
{
    private static TeamId T(int id) => new(id);

    private static Fixture Played(int id, int home, int away, int homeGoals, int awayGoals)
    {
        var fixture = new Fixture(id, matchday: 1, T(home), T(away));
        fixture.RecordResult(new MatchResult(homeGoals, awayGoals));
        return fixture;
    }

    [Fact]
    public void AwardsThreeForAWinAndOneForADraw()
    {
        var table = LeagueTable.Build(
            new[] { T(1), T(2), T(3) },
            new[]
            {
                Played(1, 1, 2, 2, 0),
                Played(2, 2, 3, 1, 1),
            });

        var first = table.Single(r => r.TeamId == T(1));
        var second = table.Single(r => r.TeamId == T(2));
        var third = table.Single(r => r.TeamId == T(3));

        Assert.Equal(3, first.Points);
        Assert.Equal(1, first.Won);
        Assert.Equal(1, second.Points);
        Assert.Equal(1, third.Points);
    }

    [Fact]
    public void OrdersOnPointsFirst()
    {
        var table = LeagueTable.Build(
            new[] { T(1), T(2) },
            new[] { Played(1, 2, 1, 3, 0) });

        Assert.Equal(T(2), table[0].TeamId);
        Assert.Equal(1, table[0].Position);
        Assert.Equal(2, table[1].Position);
    }

    [Fact]
    public void SeparatesLevelClubsOnGoalDifference()
    {
        // Both win once. Club 1 wins by three, club 2 by one.
        var table = LeagueTable.Build(
            new[] { T(1), T(2), T(3), T(4) },
            new[]
            {
                Played(1, 1, 3, 3, 0),
                Played(2, 2, 4, 1, 0),
            });

        Assert.Equal(T(1), table[0].TeamId);
        Assert.Equal(3, table[0].GoalDifference);
        Assert.Equal(T(2), table[1].TeamId);
    }

    [Fact]
    public void SeparatesEqualGoalDifferenceOnGoalsScored()
    {
        // Identical +1 difference; club 2 scored more getting there.
        var table = LeagueTable.Build(
            new[] { T(1), T(2), T(3), T(4) },
            new[]
            {
                Played(1, 1, 3, 1, 0),
                Played(2, 2, 4, 3, 2),
            });

        var first = table.Single(r => r.TeamId == T(1));
        var second = table.Single(r => r.TeamId == T(2));

        Assert.Equal(first.Points, second.Points);
        Assert.Equal(first.GoalDifference, second.GoalDifference);
        Assert.Equal(T(2), table[0].TeamId);
        Assert.Equal(T(1), table[1].TeamId);
    }

    [Fact]
    public void FallsBackToHeadToHeadWhenPointsGoalDifferenceAndGoalsAllMatch()
    {
        // Clubs 1 and 2 both finish on 3 points, zero goal difference and two goals scored.
        // Club 2 won the meeting between them, so it must finish above club 1 — and that is
        // the opposite of the by-id fallback, so this fails if head-to-head is not applied.
        var table = LeagueTable.Build(
            new[] { T(1), T(2), T(3), T(4) },
            new[]
            {
                Played(1, 2, 1, 2, 1),
                Played(2, 2, 3, 0, 1),
                Played(3, 1, 4, 1, 0),
            });

        var one = table.Single(r => r.TeamId == T(1));
        var two = table.Single(r => r.TeamId == T(2));

        Assert.Equal(two.Points, one.Points);
        Assert.Equal(two.GoalDifference, one.GoalDifference);
        Assert.Equal(two.GoalsFor, one.GoalsFor);

        Assert.True(
            two.Position < one.Position,
            $"Club 2 won the head-to-head but finished {two.Position} to club 1's {one.Position}.");
    }

    [Fact]
    public void OrdersByIdWhenEverythingIncludingHeadToHeadIsLevel()
    {
        // Two clubs, one goalless draw each way: nothing can separate them.
        var table = LeagueTable.Build(
            new[] { T(9), T(4) },
            new[] { Played(1, 9, 4, 0, 0), Played(2, 4, 9, 0, 0) });

        Assert.Equal(T(4), table[0].TeamId);
        Assert.Equal(T(9), table[1].TeamId);
    }

    [Fact]
    public void IgnoresUnplayedFixtures()
    {
        var unplayed = new Fixture(1, 1, T(1), T(2));

        var table = LeagueTable.Build(new[] { T(1), T(2) }, new[] { unplayed });

        Assert.All(table, row => Assert.Equal(0, row.Played));
    }

    [Fact]
    public void IgnoresFixturesAgainstClubsOutsideTheDivision()
    {
        // A cup tie against a club from another league must not reach the table.
        var table = LeagueTable.Build(
            new[] { T(1), T(2) },
            new[] { Played(1, 1, 99, 5, 0) });

        Assert.All(table, row => Assert.Equal(0, row.Played));
    }

    [Fact]
    public void IncludesClubsThatHaveNotPlayedYet()
    {
        var table = LeagueTable.Build(new[] { T(1), T(2), T(3) }, Array.Empty<Fixture>());

        Assert.Equal(3, table.Count);
        Assert.All(table, row => Assert.Equal(0, row.Points));
        Assert.Equal(new[] { 1, 2, 3 }, table.Select(r => r.Position));
    }

    [Fact]
    public void GoalsForAcrossTheTableEqualGoalsAgainst()
    {
        var table = LeagueTable.Build(
            new[] { T(1), T(2), T(3), T(4) },
            new[]
            {
                Played(1, 1, 2, 3, 1),
                Played(2, 3, 4, 0, 2),
                Played(3, 1, 3, 1, 1),
                Played(4, 4, 2, 2, 2),
            });

        Assert.Equal(table.Sum(r => r.GoalsFor), table.Sum(r => r.GoalsAgainst));
    }

    [Fact]
    public void WinsDrawsAndLossesSumToGamesPlayed()
    {
        var table = LeagueTable.Build(
            new[] { T(1), T(2), T(3) },
            new[]
            {
                Played(1, 1, 2, 1, 0),
                Played(2, 2, 3, 2, 2),
                Played(3, 3, 1, 0, 4),
            });

        Assert.All(table, row => Assert.Equal(row.Played, row.Won + row.Drawn + row.Lost));
    }
}
