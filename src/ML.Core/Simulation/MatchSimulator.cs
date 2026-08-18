using ML.Core.Scheduling;

namespace ML.Core.Simulation;

public interface IMatchSimulator
{
    MatchResult Simulate(TeamStrength home, TeamStrength away);
}

public sealed record SimulationSettings
{
    /// <summary>Goals per team per game before any home or strength adjustment.</summary>
    public double BaseGoals { get; init; } = 1.35;

    public double HomeAdvantage { get; init; } = 1.25;

    public double AwayPenalty { get; init; } = 0.88;

    /// <summary>
    /// Rating points per e-fold of scoring rate. Lower makes the league more predictable;
    /// at 24 a fifteen-point gap roughly doubles the favourite's expected goals.
    /// </summary>
    public double RatingScale { get; init; } = 24.0;

    public double MinExpectedGoals { get; init; } = 0.10;

    public double MaxExpectedGoals { get; init; } = 6.0;

    public int MaxGoals { get; init; } = 9;

    public static SimulationSettings Default { get; } = new();
}

/// <summary>
/// Poisson scoreline model. Each side's expected goals come from its attack against the
/// opponent's defence, then the actual score is drawn from that — so the better squad wins
/// most of the time but not every time, which is the point.
/// </summary>
public sealed class PoissonMatchSimulator : IMatchSimulator
{
    private readonly IRandomSource _random;
    private readonly SimulationSettings _settings;

    public PoissonMatchSimulator(IRandomSource random, SimulationSettings? settings = null)
    {
        _random = random ?? throw new ArgumentNullException(nameof(random));
        _settings = settings ?? SimulationSettings.Default;
    }

    public MatchResult Simulate(TeamStrength home, TeamStrength away)
    {
        var homeGoals = SampleGoals(ExpectedGoals(home.Attack, away.Defence, _settings.HomeAdvantage));
        var awayGoals = SampleGoals(ExpectedGoals(away.Attack, home.Defence, _settings.AwayPenalty));
        return new MatchResult(homeGoals, awayGoals);
    }

    public double ExpectedGoals(double attack, double opposingDefence, double venueFactor)
    {
        var edge = Math.Exp((attack - opposingDefence) / _settings.RatingScale);
        return Math.Clamp(
            _settings.BaseGoals * venueFactor * edge,
            _settings.MinExpectedGoals,
            _settings.MaxExpectedGoals);
    }

    /// <summary>Knuth's method. Fine at these rates — lambda never gets far above six.</summary>
    private int SampleGoals(double lambda)
    {
        var limit = Math.Exp(-lambda);
        var product = 1.0;
        var goals = -1;

        do
        {
            goals++;
            product *= _random.NextDouble();
        }
        while (product > limit && goals <= _settings.MaxGoals);

        return Math.Min(goals, _settings.MaxGoals);
    }
}
