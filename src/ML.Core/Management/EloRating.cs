namespace ML.Core.Management;

/// <summary>
/// Team ELO ratings and the win/draw/loss probabilities MFL's match preview shows. Standard ELO
/// with a home-advantage bump and a draw model, so a fixture preview can read "45% / 25% / 30%"
/// straight off the two ratings — and the same numbers can weight the CPU simulation.
/// </summary>
public static class EloRating
{
    public const int Default = 1500;

    /// <summary>Rating points of home advantage folded into the expectation.</summary>
    public const double HomeAdvantage = 70;

    /// <summary>K-factor: how far one result moves a rating.</summary>
    public const double K = 24;

    public readonly record struct Outlook(double HomeWin, double Draw, double AwayWin)
    {
        public int HomePercent => (int)Math.Round(HomeWin * 100);
        public int DrawPercent => (int)Math.Round(Draw * 100);
        public int AwayPercent => 100 - HomePercent - DrawPercent;
    }

    /// <summary>Expected score for the home side in [0,1]; 0.5 is an even game.</summary>
    public static double ExpectedHomeScore(int homeElo, int awayElo) =>
        1.0 / (1.0 + Math.Pow(10, (awayElo - (homeElo + HomeAdvantage)) / 400.0));

    /// <summary>
    /// Win / draw / loss probabilities for a fixture. The draw share is largest for even games
    /// and shrinks as the sides diverge — a simple, well-behaved model rather than a fitted one.
    /// </summary>
    public static Outlook Preview(int homeElo, int awayElo)
    {
        var expected = ExpectedHomeScore(homeElo, awayElo);
        // Draw likelihood peaks (~0.27) at parity and tapers with the gap between the sides.
        var draw = 0.27 * (1 - Math.Abs(expected - 0.5) * 2 * 0.6);
        var remaining = 1 - draw;
        var homeWin = remaining * expected;
        var awayWin = remaining * (1 - expected);
        return new Outlook(homeWin, draw, awayWin);
    }

    /// <summary>
    /// New ratings after a result. actualHome is 1 win / 0.5 draw / 0 loss. Returns the deltas so
    /// callers can show "+8 / -8" and persist the updated ratings.
    /// </summary>
    public static (int HomeDelta, int AwayDelta) Update(int homeElo, int awayElo, double actualHome)
    {
        var expected = ExpectedHomeScore(homeElo, awayElo);
        var homeDelta = (int)Math.Round(K * (actualHome - expected));
        return (homeDelta, -homeDelta);
    }

    public static double ActualScore(int homeGoals, int awayGoals) =>
        homeGoals > awayGoals ? 1.0 : homeGoals == awayGoals ? 0.5 : 0.0;
}
