using ML.Core;
using ML.Core.Scheduling;
using ML.Core.Simulation;

namespace ML.Core.Tests;

public class MatchSimulatorTests
{
    private static readonly TeamStrength Strong = new(Attack: 84, Defence: 82);
    private static readonly TeamStrength Weak = new(Attack: 66, Defence: 64);
    private static readonly TeamStrength Average = new(Attack: 75, Defence: 75);

    private static (int Home, int Draw, int Away) RunMany(
        TeamStrength home, TeamStrength away, int games = 4000, int seed = 1)
    {
        var simulator = new PoissonMatchSimulator(new SeededRandom(seed));
        int homeWins = 0, draws = 0, awayWins = 0;

        for (var i = 0; i < games; i++)
        {
            switch (simulator.Simulate(home, away).Outcome)
            {
                case MatchOutcome.HomeWin: homeWins++; break;
                case MatchOutcome.Draw: draws++; break;
                default: awayWins++; break;
            }
        }

        return (homeWins, draws, awayWins);
    }

    [Fact]
    public void SameSeedReplaysTheSameSeason()
    {
        var first = new PoissonMatchSimulator(new SeededRandom(2026));
        var second = new PoissonMatchSimulator(new SeededRandom(2026));

        for (var i = 0; i < 200; i++)
        {
            Assert.Equal(first.Simulate(Strong, Weak), second.Simulate(Strong, Weak));
        }
    }

    [Fact]
    public void DifferentSeedsDivergeSoLeaguesAreNotIdentical()
    {
        var first = new PoissonMatchSimulator(new SeededRandom(1));
        var second = new PoissonMatchSimulator(new SeededRandom(2));

        var a = Enumerable.Range(0, 100).Select(_ => first.Simulate(Average, Average)).ToList();
        var b = Enumerable.Range(0, 100).Select(_ => second.Simulate(Average, Average)).ToList();

        Assert.NotEqual(a, b);
    }

    [Fact]
    public void TheBetterSquadWinsMoreOften()
    {
        var (strongHome, _, weakAway) = RunMany(Strong, Weak);

        Assert.True(
            strongHome > weakAway * 3,
            $"Expected the stronger side to dominate; got {strongHome} to {weakAway}.");
    }

    [Fact]
    public void TheBetterSquadStillLosesSometimes()
    {
        // A deterministic league is a boring one. The favourite must drop games.
        var (_, draws, upsets) = RunMany(Strong, Weak);

        Assert.True(upsets > 0, "The weaker side never won once in 4000 games.");
        Assert.True(draws > 0, "There was never a draw in 4000 games.");
    }

    [Fact]
    public void HomeAdvantageShowsUpBetweenEvenlyMatchedSides()
    {
        var (home, _, away) = RunMany(Average, Average);

        Assert.True(home > away, $"Home won {home}, away won {away}; expected a home edge.");
    }

    [Fact]
    public void ScoresAreNeverNegativeAndNeverAbsurd()
    {
        var settings = SimulationSettings.Default;
        var simulator = new PoissonMatchSimulator(new SeededRandom(77), settings);

        for (var i = 0; i < 5000; i++)
        {
            var result = simulator.Simulate(Strong, Weak);

            Assert.InRange(result.HomeGoals, 0, settings.MaxGoals);
            Assert.InRange(result.AwayGoals, 0, settings.MaxGoals);
        }
    }

    [Fact]
    public void AverageGoalsLandInARealisticRange()
    {
        var simulator = new PoissonMatchSimulator(new SeededRandom(5));

        var total = Enumerable.Range(0, 5000)
            .Select(_ => simulator.Simulate(Average, Average))
            .Average(r => r.HomeGoals + r.AwayGoals);

        Assert.InRange(total, 2.0, 3.8);
    }

    [Fact]
    public void ExpectedGoalsIsClampedAtBothEnds()
    {
        var settings = new SimulationSettings { MinExpectedGoals = 0.2, MaxExpectedGoals = 4.0 };
        var simulator = new PoissonMatchSimulator(new SeededRandom(1), settings);

        Assert.Equal(4.0, simulator.ExpectedGoals(attack: 99, opposingDefence: 40, venueFactor: 1.25));
        Assert.Equal(0.2, simulator.ExpectedGoals(attack: 40, opposingDefence: 99, venueFactor: 0.88));
    }
}
