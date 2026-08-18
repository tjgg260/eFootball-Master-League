namespace ML.Core.Scheduling;

public enum MatchOutcome
{
    HomeWin,
    Draw,
    AwayWin,
}

public readonly record struct MatchResult
{
    public MatchResult(int homeGoals, int awayGoals)
    {
        if (homeGoals < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(homeGoals), homeGoals, "Goals cannot be negative.");
        }

        if (awayGoals < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(awayGoals), awayGoals, "Goals cannot be negative.");
        }

        HomeGoals = homeGoals;
        AwayGoals = awayGoals;
    }

    public int HomeGoals { get; }

    public int AwayGoals { get; }

    public MatchOutcome Outcome =>
        HomeGoals > AwayGoals ? MatchOutcome.HomeWin
        : HomeGoals < AwayGoals ? MatchOutcome.AwayWin
        : MatchOutcome.Draw;

    public override string ToString() => $"{HomeGoals}-{AwayGoals}";
}
