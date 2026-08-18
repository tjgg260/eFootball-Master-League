using ML.Core;
using ML.Core.Domain;
using ML.Core.Seasons;
using ML.Core.Simulation;

namespace ML.Core.Tests;

public class SeasonRolloverTests
{
    private const int TopTier = 1;
    private const int SecondTier = 2;

    private static (World World, List<Season> Seasons, SeasonRollover Rollover) PlayOneSeason(
        int seed = 31, int teamsPerLeague = 20)
    {
        var world = TestWorld.TwoTierPyramid(teamsPerLeague: teamsPerLeague, seed: seed);
        var random = new SeededRandom(seed);
        var engine = new SeasonEngine(world, new PoissonMatchSimulator(random));

        var seasons = world.LeaguesByTier()
            .Select(league => Season.Create(
                1,
                2027,
                league,
                world.TeamsIn(league.Id).Select(t => t.Id).ToList(),
                random))
            .ToList();

        foreach (var season in seasons)
        {
            engine.SimulateEntireSeason(season);
        }

        return (world, seasons, new SeasonRollover(world, random));
    }

    [Fact]
    public void TheChampionIsWhoeverTopsTheTable()
    {
        var (_, seasons, rollover) = PlayOneSeason();

        var report = rollover.Apply(completedSeasonId: 1, seasons);
        var topFlight = report.Leagues.Single(l => l.LeagueId == new LeagueId(TopTier));

        Assert.Equal(topFlight.FinalTable[0].TeamId, topFlight.Champion);
        Assert.Equal(1, topFlight.FinalTable[0].Position);
    }

    [Fact]
    public void TheBottomThreeGoDownAndTheTopThreeComeUp()
    {
        var (world, seasons, rollover) = PlayOneSeason();

        var topTable = seasons.Single(s => s.LeagueId == new LeagueId(TopTier));
        var secondTable = seasons.Single(s => s.LeagueId == new LeagueId(SecondTier));

        var expectedDown = Tables.LeagueTable.Build(topTable.Teams, topTable.Fixtures)
            .TakeLast(3).Select(r => r.TeamId).ToList();
        var expectedUp = Tables.LeagueTable.Build(secondTable.Teams, secondTable.Fixtures)
            .Take(3).Select(r => r.TeamId).ToList();

        var report = rollover.Apply(1, seasons);

        var top = report.Leagues.Single(l => l.LeagueId == new LeagueId(TopTier));
        var second = report.Leagues.Single(l => l.LeagueId == new LeagueId(SecondTier));

        Assert.Equal(expectedDown, top.Relegated);
        Assert.Equal(expectedUp, second.Promoted);

        Assert.All(expectedDown, id => Assert.Equal(new LeagueId(SecondTier), world.GetTeam(id).LeagueId));
        Assert.All(expectedUp, id => Assert.Equal(new LeagueId(TopTier), world.GetTeam(id).LeagueId));
    }

    [Fact]
    public void DivisionsKeepTheirSize()
    {
        var (world, seasons, rollover) = PlayOneSeason();

        rollover.Apply(1, seasons);

        Assert.Equal(20, world.TeamsIn(new LeagueId(TopTier)).Count);
        Assert.Equal(20, world.TeamsIn(new LeagueId(SecondTier)).Count);
    }

    [Fact]
    public void EveryPlayerAgesAYear()
    {
        var (world, seasons, rollover) = PlayOneSeason();
        var before = world.Players.ToDictionary(p => p.Id, p => p.Age);

        rollover.Apply(1, seasons);

        foreach (var player in world.Players)
        {
            Assert.Equal(before[player.Id] + 1, player.Age);
        }
    }

    [Fact]
    public void YoungPlayersImproveOnAverageAndVeteransDecline()
    {
        var (world, seasons, rollover) = PlayOneSeason();

        var before = world.Players.ToDictionary(p => p.Id, p => (p.Age, p.OverallRating));

        rollover.Apply(1, seasons);

        var youngDelta = world.Players
            .Where(p => before[p.Id].Age < 22)
            .Average(p => p.OverallRating - before[p.Id].OverallRating);

        var veteranDelta = world.Players
            .Where(p => before[p.Id].Age > 32)
            .Average(p => p.OverallRating - before[p.Id].OverallRating);

        Assert.True(youngDelta > 0, $"Young players averaged {youngDelta:F2}.");
        Assert.True(veteranDelta < 0, $"Veterans averaged {veteranDelta:F2}.");
    }

    [Fact]
    public void NoClubEverCarriesANegativeBudget()
    {
        var (world, seasons, rollover) = PlayOneSeason();

        rollover.Apply(1, seasons);

        Assert.All(world.Teams, team => Assert.True(
            team.Budget >= 0, $"{team.Name} finished on {team.Budget:N0}."));
    }

    [Fact]
    public void WinningTheTopFlightPaysMoreThanWinningTheDivisionBelow()
    {
        var (world, seasons, rollover) = PlayOneSeason();

        var budgetsBefore = world.Teams.ToDictionary(t => t.Id, t => t.Budget);
        var report = rollover.Apply(1, seasons);

        var topChampion = report.Leagues.Single(l => l.LeagueId == new LeagueId(TopTier)).Champion;
        var secondChampion = report.Leagues.Single(l => l.LeagueId == new LeagueId(SecondTier)).Champion;

        var topGain = world.GetTeam(topChampion).Budget - budgetsBefore[topChampion];
        var secondGain = world.GetTeam(secondChampion).Budget - budgetsBefore[secondChampion];

        Assert.True(topGain > secondGain, $"Top flight gained {topGain:N0}, second tier {secondGain:N0}.");
    }

    [Fact]
    public void AnUnfinishedSeasonBlocksTheRollover()
    {
        var world = TestWorld.TwoTierPyramid();
        var random = new SeededRandom(1);
        var league = world.GetLeague(new LeagueId(TopTier));

        var season = Season.Create(
            1, 2027, league, world.TeamsIn(league.Id).Select(t => t.Id).ToList(), random);

        var rollover = new SeasonRollover(world, random);

        var error = Assert.Throws<InvalidOperationException>(() => rollover.Apply(1, new[] { season }));
        Assert.Contains("must finish", error.Message);
    }

    [Fact]
    public void AMismatchedPyramidIsRejectedBeforeAnythingMoves()
    {
        // Three down but only two up would shrink the top flight every year.
        var world = TestWorld.Build(
            new[]
            {
                new TestLeagueSpec("Top", Tier: 1, Teams: 6, RelegationPlaces: 3),
                new TestLeagueSpec("Second", Tier: 2, Teams: 6, PromotionPlaces: 2),
            },
            squadSize: 20,
            seed: 1);

        var error = Assert.Throws<InvalidOperationException>(() => LeaguePyramid.Validate(world));
        Assert.Contains("drift", error.Message);
    }

    [Fact]
    public void ParallelDivisionsAtTheSameTierAreRejected()
    {
        var world = TestWorld.Build(
            new[]
            {
                new TestLeagueSpec("North", Tier: 1, Teams: 4),
                new TestLeagueSpec("South", Tier: 1, Teams: 4),
            },
            squadSize: 20,
            seed: 1);

        Assert.Throws<InvalidOperationException>(() => LeaguePyramid.AdjacentTiers(world));
    }
}
