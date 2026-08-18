using ML.Core;
using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Seasons;
using ML.Core.Simulation;

namespace ML.Core.Tests;

public class SeasonEngineTests
{
    private static (World World, SeasonEngine Engine, Season Season) Setup(
        int teams = 20, TeamId? userTeam = null, int seed = 4)
    {
        var world = TestWorld.SingleLeague(teams: teams, seed: seed);
        var league = world.GetLeague(new LeagueId(1));
        var teamIds = TestWorld.TeamIdsIn(world, tier: 1);

        var season = Season.Create(
            id: 1, year: 2027, league, teamIds, new SeededRandom(seed), userTeam);

        var engine = new SeasonEngine(world, new PoissonMatchSimulator(new SeededRandom(seed)));
        return (world, engine, season);
    }

    [Fact]
    public void ANewSeasonHasNotStarted()
    {
        var (_, _, season) = Setup();

        Assert.Equal(SeasonState.NotStarted, season.State);
        Assert.Equal(0, season.CurrentMatchday);
        Assert.Equal(38, season.TotalMatchdays);
        Assert.All(season.Fixtures, f => Assert.False(f.IsPlayed));
    }

    [Fact]
    public void WithNoUserClubTheWholeMatchdayIsSimulated()
    {
        var (_, engine, season) = Setup();

        var result = engine.AdvanceMatchday(season);

        Assert.Equal(AdvanceOutcome.MatchdayCompleted, result.Outcome);
        Assert.Equal(1, result.Matchday);
        Assert.Equal(10, result.SimulatedFixtures.Count);
        Assert.All(season.FixturesOn(1), f => Assert.True(f.IsPlayed));
        Assert.Equal(2, season.CurrentMatchday);
    }

    [Fact]
    public void WithAUserClubTheEngineStopsAndWaitsForTheirResult()
    {
        var world = TestWorld.SingleLeague(seed: 4);
        var userTeam = TestWorld.TeamIdsIn(world, 1)[0];
        var (_, engine, season) = Setup(userTeam: userTeam);

        var result = engine.AdvanceMatchday(season);

        Assert.Equal(AdvanceOutcome.AwaitingUserResult, result.Outcome);
        Assert.Equal(1, season.CurrentMatchday);

        // The nine CPU games are in; only the user's own fixture is outstanding.
        Assert.Equal(9, result.SimulatedFixtures.Count);
        var userFixture = season.UserFixtureOn(1);
        Assert.NotNull(userFixture);
        Assert.False(userFixture!.IsPlayed);
    }

    [Fact]
    public void AdvancingAgainWithoutTheUserResultChangesNothing()
    {
        var world = TestWorld.SingleLeague(seed: 4);
        var userTeam = TestWorld.TeamIdsIn(world, 1)[0];
        var (_, engine, season) = Setup(userTeam: userTeam);

        engine.AdvanceMatchday(season);
        var second = engine.AdvanceMatchday(season);

        Assert.Equal(AdvanceOutcome.AwaitingUserResult, second.Outcome);
        Assert.Empty(second.SimulatedFixtures);
        Assert.Equal(1, season.CurrentMatchday);
    }

    [Fact]
    public void RecordingTheUserResultReleasesTheMatchday()
    {
        var world = TestWorld.SingleLeague(seed: 4);
        var userTeam = TestWorld.TeamIdsIn(world, 1)[0];
        var (_, engine, season) = Setup(userTeam: userTeam);

        engine.AdvanceMatchday(season);
        engine.RecordUserResult(season, new MatchResult(3, 1));

        var result = engine.AdvanceMatchday(season);

        Assert.Equal(AdvanceOutcome.MatchdayCompleted, result.Outcome);
        Assert.Equal(2, season.CurrentMatchday);
        Assert.Equal(new MatchResult(3, 1), season.Fixtures.First(f => f.Involves(userTeam)).Result);
    }

    [Fact]
    public void RecordingAUserResultTwiceOnTheSameMatchdayIsRejected()
    {
        var world = TestWorld.SingleLeague(seed: 4);
        var userTeam = TestWorld.TeamIdsIn(world, 1)[0];
        var (_, engine, season) = Setup(userTeam: userTeam);

        engine.AdvanceMatchday(season);
        engine.RecordUserResult(season, new MatchResult(1, 0));

        Assert.Throws<InvalidOperationException>(
            () => engine.RecordUserResult(season, new MatchResult(2, 0)));
    }

    [Fact]
    public void RecordingAUserResultWithoutAUserClubIsRejected()
    {
        var (_, engine, season) = Setup();

        Assert.Throws<InvalidOperationException>(
            () => engine.RecordUserResult(season, new MatchResult(1, 0)));
    }

    [Fact]
    public void ASeasonCompletesAfterItsLastMatchday()
    {
        var (_, engine, season) = Setup();

        for (var i = 0; i < season.TotalMatchdays; i++)
        {
            engine.AdvanceMatchday(season);
        }

        Assert.Equal(SeasonState.Complete, season.State);
        Assert.True(season.AllFixturesPlayed);
    }

    [Fact]
    public void AdvancingAFinishedSeasonIsANoOp()
    {
        var (_, engine, season) = Setup();
        engine.SimulateEntireSeason(season);

        var result = engine.AdvanceMatchday(season);

        Assert.Equal(AdvanceOutcome.SeasonAlreadyComplete, result.Outcome);
        Assert.Empty(result.SimulatedFixtures);
    }

    [Fact]
    public void SimulatingTheWholeSeasonPlaysTheUserGamesToo()
    {
        var world = TestWorld.SingleLeague(seed: 4);
        var userTeam = TestWorld.TeamIdsIn(world, 1)[0];
        var (_, engine, season) = Setup(userTeam: userTeam);

        engine.SimulateEntireSeason(season);

        Assert.Equal(SeasonState.Complete, season.State);
        Assert.All(season.Fixtures, f => Assert.True(f.IsPlayed));
    }

    [Fact]
    public void EveryClubPlaysThirtyEightGamesAcrossACompletedSeason()
    {
        var (_, engine, season) = Setup();
        engine.SimulateEntireSeason(season);

        var table = engine.TableFor(season);

        Assert.Equal(20, table.Count);
        Assert.All(table, row => Assert.Equal(38, row.Played));
        Assert.Equal(Enumerable.Range(1, 20), table.Select(r => r.Position));
    }

    [Fact]
    public void AStrongerSquadFinishesAboveAWeakerOneOverAFullSeason()
    {
        var (world, engine, season) = Setup(seed: 12);
        engine.SimulateEntireSeason(season);

        var table = engine.TableFor(season);

        var best = table.MaxBy(r => engine.StrengthOf(r.TeamId).Overall)!;
        var worst = table.MinBy(r => engine.StrengthOf(r.TeamId).Overall)!;

        Assert.True(
            best.Position < worst.Position,
            $"Strongest squad finished {best.Position}, weakest finished {worst.Position}.");
    }

    [Fact]
    public void ChoosingAClubOutsideTheDivisionIsRejected()
    {
        var world = TestWorld.SingleLeague();
        var league = world.GetLeague(new LeagueId(1));
        var teamIds = TestWorld.TeamIdsIn(world, 1);

        Assert.Throws<ArgumentException>(() => Season.Create(
            1, 2027, league, teamIds, new SeededRandom(1), userTeam: new TeamId(9999)));
    }
}
