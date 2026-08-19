namespace ML.Core.Management;

/// <summary>What the board expects of the manager this season. Drives confidence swings.</summary>
public enum Expectation
{
    Survival,
    LowerMidTable,
    MidTable,
    Playoffs,
    Promotion,
    Title,
}

/// <summary>
/// Board confidence, 0-100, the MFL "board confidence" gauge. It nudges after every result,
/// weighted by whether the result was expected — beating a title rival lifts a survival side
/// more than a title side, and losing at home to the bottom club stings everyone.
/// </summary>
public sealed class BoardConfidence
{
    public const int Min = 0;
    public const int Max = 100;
    public const int SackThreshold = 20;

    public BoardConfidence(Expectation expectation, int starting = 55)
    {
        Expectation = expectation;
        Value = Math.Clamp(starting, Min, Max);
    }

    public Expectation Expectation { get; }

    public int Value { get; private set; }

    public bool ManagerUnderThreat => Value <= SackThreshold;

    /// <summary>
    /// Apply one of the manager's own results. Positions are 1-based; leaguePosition is where the
    /// club sits now, expectedPosition where the board wants them by season's end.
    /// </summary>
    public void ApplyResult(int goalsFor, int goalsAgainst, int leaguePosition, int expectedPosition)
    {
        var resultSwing =
            goalsFor > goalsAgainst ? 6 :
            goalsFor == goalsAgainst ? 0 : -5;

        // Standing relative to expectation: ahead of target lifts, behind it drags.
        var standingSwing = Math.Clamp(expectedPosition - leaguePosition, -4, 4);

        Value = Math.Clamp(Value + resultSwing + standingSwing, Min, Max);
    }

    public string Label => Value switch
    {
        >= 80 => "Secure",
        >= 60 => "Confident",
        >= 40 => "Stable",
        >= SackThreshold + 1 => "Concerned",
        _ => "At risk",
    };
}
