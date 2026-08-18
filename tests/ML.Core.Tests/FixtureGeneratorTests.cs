using ML.Core;
using ML.Core.Domain;
using ML.Core.Scheduling;

namespace ML.Core.Tests;

public class FixtureGeneratorTests
{
    private static IReadOnlyList<TeamId> Teams(int count) =>
        Enumerable.Range(1, count).Select(i => new TeamId(i)).ToList();

    [Theory]
    [InlineData(2)]
    [InlineData(4)]
    [InlineData(18)]
    [InlineData(20)]
    public void DoubleRoundRobin_HasEveryPairTwice(int teamCount)
    {
        var teams = Teams(teamCount);
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(teams, new SeededRandom(7));

        Assert.Equal(teamCount * (teamCount - 1), fixtures.Count);

        // Every ordered pair exactly once means every unordered pair twice, once per venue.
        var orderedPairs = fixtures.Select(f => (f.HomeTeam, f.AwayTeam)).ToList();
        Assert.Equal(orderedPairs.Count, orderedPairs.Distinct().Count());
    }

    [Theory]
    [InlineData(20)]
    [InlineData(18)]
    [InlineData(4)]
    public void DoubleRoundRobin_GivesEveryClubAnEvenHomeAndAwaySplit(int teamCount)
    {
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(Teams(teamCount), new SeededRandom(3));

        foreach (var team in Teams(teamCount))
        {
            Assert.Equal(teamCount - 1, fixtures.Count(f => f.HomeTeam == team));
            Assert.Equal(teamCount - 1, fixtures.Count(f => f.AwayTeam == team));
        }
    }

    [Theory]
    [InlineData(20)]
    [InlineData(19)]
    [InlineData(7)]
    [InlineData(2)]
    public void NoClubPlaysTwiceOnAMatchday(int teamCount)
    {
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(Teams(teamCount), new SeededRandom(11));

        foreach (var matchday in fixtures.GroupBy(f => f.Matchday))
        {
            var appearances = matchday.SelectMany(f => new[] { f.HomeTeam, f.AwayTeam }).ToList();
            Assert.Equal(appearances.Count, appearances.Distinct().Count());
        }
    }

    [Fact]
    public void TwentyClubs_ProduceThirtyEightMatchdaysOfTenGames()
    {
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(Teams(20), new SeededRandom(1));

        Assert.Equal(38, fixtures.Max(f => f.Matchday));
        Assert.All(
            fixtures.GroupBy(f => f.Matchday),
            matchday => Assert.Equal(10, matchday.Count()));
    }

    [Fact]
    public void OddClubCount_GivesEveryClubExactlyOneByePerLeg()
    {
        const int teamCount = 19;
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(Teams(teamCount), new SeededRandom(5));

        // 19 clubs means 19 matchdays per leg, each club idle for exactly one of them.
        Assert.Equal(teamCount * 2, fixtures.Max(f => f.Matchday));

        foreach (var team in Teams(teamCount))
        {
            var played = fixtures.Count(f => f.Involves(team));
            Assert.Equal((teamCount - 1) * 2, played);
        }
    }

    [Fact]
    public void SingleRoundRobin_HasEveryPairOnce()
    {
        var fixtures = FixtureGenerator.GenerateSingleRoundRobin(Teams(20), new SeededRandom(2));

        Assert.Equal(190, fixtures.Count);
        Assert.Equal(19, fixtures.Max(f => f.Matchday));

        var unorderedPairs = fixtures
            .Select(f => f.HomeTeam.Value < f.AwayTeam.Value
                ? (f.HomeTeam, f.AwayTeam)
                : (f.AwayTeam, f.HomeTeam))
            .ToList();

        Assert.Equal(unorderedPairs.Count, unorderedPairs.Distinct().Count());
    }

    [Fact]
    public void SingleLeg_KeepsHomeGamesWithinOneOfEachOther()
    {
        // The pinned club would otherwise take the same venue every round.
        var fixtures = FixtureGenerator.GenerateSingleRoundRobin(Teams(20), new SeededRandom(9));

        var homeCounts = Teams(20).Select(t => fixtures.Count(f => f.HomeTeam == t)).ToList();

        Assert.True(
            homeCounts.Max() - homeCounts.Min() <= 1,
            $"Home games ranged {homeCounts.Min()}-{homeCounts.Max()}; expected a spread of at most 1.");
    }

    [Fact]
    public void SameSeed_ProducesTheSameSchedule()
    {
        var first = FixtureGenerator.GenerateDoubleRoundRobin(Teams(20), new SeededRandom(42));
        var second = FixtureGenerator.GenerateDoubleRoundRobin(Teams(20), new SeededRandom(42));

        Assert.Equal(
            first.Select(f => (f.Matchday, f.HomeTeam, f.AwayTeam)),
            second.Select(f => (f.Matchday, f.HomeTeam, f.AwayTeam)));
    }

    [Fact]
    public void DifferentSeed_ProducesADifferentSchedule()
    {
        var first = FixtureGenerator.GenerateDoubleRoundRobin(Teams(20), new SeededRandom(1));
        var second = FixtureGenerator.GenerateDoubleRoundRobin(Teams(20), new SeededRandom(2));

        Assert.NotEqual(
            first.Select(f => (f.Matchday, f.HomeTeam, f.AwayTeam)),
            second.Select(f => (f.Matchday, f.HomeTeam, f.AwayTeam)));
    }

    [Fact]
    public void RejectsALeagueOfOne()
    {
        Assert.Throws<ArgumentException>(
            () => FixtureGenerator.GenerateDoubleRoundRobin(Teams(1), new SeededRandom(1)));
    }

    [Fact]
    public void RejectsTheSameClubTwice()
    {
        var duplicated = new[] { new TeamId(1), new TeamId(2), new TeamId(1) };

        Assert.Throws<ArgumentException>(
            () => FixtureGenerator.GenerateDoubleRoundRobin(duplicated, new SeededRandom(1)));
    }
}
