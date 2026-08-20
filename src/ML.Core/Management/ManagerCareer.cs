namespace ML.Core.Management;

/// <summary>
/// The manager's own career, separate from any one club: reputation earned from results and
/// silverware, the board-patience rules that end in a sacking, and which clubs would come
/// calling. Pure maths — persistence and club data live in the app layer.
/// </summary>
public static class ManagerCareer
{
    public const int RepMin = 0;
    public const int RepMax = 100;
    public const int StartingRep = 35;

    /// <summary>Matchdays the board will sit at/below the sack threshold before acting.</summary>
    public const int BoardPatience = 5;

    /// <summary>Confidence so low the board acts immediately, patience or not.</summary>
    public const int InstantSackConfidence = 5;

    /// <summary>
    /// Reputation moves a little with every competitive result: beating a stronger side is
    /// worth more than beating a weaker one, and only losing to a weaker side costs you.
    /// </summary>
    public static int RepAfterResult(int rep, int goalsFor, int goalsAgainst, bool oppositionStronger)
    {
        var delta =
            goalsFor > goalsAgainst ? (oppositionStronger ? 2 : 1) :
            goalsFor == goalsAgainst ? (oppositionStronger ? 1 : 0) :
            oppositionStronger ? 0 : -1;
        return Math.Clamp(rep + delta, RepMin, RepMax);
    }

    /// <summary>
    /// The big season-end swing: titles and promotions make a name; finishing in the
    /// relegation places erodes one.
    /// </summary>
    public static int RepAfterSeason(
        int rep, int position, int teamCount, bool topFlight, bool promoted, int trophies)
    {
        var delta = 0;
        if (position == 1) delta += topFlight ? 6 : 4;
        else if (position <= Math.Max(1, teamCount / 2)) delta += 2;
        if (teamCount >= 6 && position > teamCount - 3) delta -= 3;
        if (promoted) delta += 5;
        delta += trophies * 4;
        return Math.Clamp(rep + delta, RepMin, RepMax);
    }

    /// <summary>
    /// What the board demands, from where the squad ranks in its league (1 = strongest).
    /// </summary>
    public static Expectation ExpectationFor(int strengthRank, int teamCount, bool topFlight)
    {
        if (teamCount <= 0) return Expectation.MidTable;
        var fraction = (double)strengthRank / teamCount;
        if (strengthRank <= 1) return topFlight ? Expectation.Title : Expectation.Promotion;
        if (fraction <= 0.25) return topFlight ? Expectation.Playoffs : Expectation.Promotion;
        if (fraction <= 0.5) return Expectation.MidTable;
        if (fraction <= 0.75) return Expectation.LowerMidTable;
        return Expectation.Survival;
    }

    /// <summary>The league position the board considers "on target" for an expectation.</summary>
    public static int TargetPosition(Expectation expectation, int teamCount) => expectation switch
    {
        Expectation.Title => 1,
        Expectation.Promotion => 2,
        Expectation.Playoffs => Math.Max(2, teamCount / 4),
        Expectation.MidTable => Math.Max(3, teamCount / 2),
        Expectation.LowerMidTable => Math.Max(4, teamCount * 3 / 4),
        _ => Math.Max(5, teamCount - 3),
    };

    /// <summary>
    /// The sacking rule: confidence on the floor is instant; otherwise the board waits
    /// <see cref="BoardPatience"/> matchdays at or below the threshold before acting.
    /// </summary>
    public static bool ShouldSack(int confidence, int matchdaysUnderThreat) =>
        confidence <= InstantSackConfidence
        || (confidence <= BoardConfidence.SackThreshold && matchdaysUnderThreat >= BoardPatience);

    /// <summary>
    /// Whether a club of the given strength rank would offer the job to a manager of this
    /// reputation. Bigger clubs (lower rank fraction) need a bigger name.
    /// </summary>
    public static bool ClubWouldOffer(int rep, int clubStrengthRank, int clubCount)
    {
        if (clubCount <= 0) return false;
        // rank fraction 0 (best club) needs rep ~75+; the bottom club takes anyone above 20.
        var fraction = (double)(clubStrengthRank - 1) / clubCount;
        var required = 75 - (int)(fraction * 55);
        return rep >= required;
    }

    public static string RepLabel(int rep) => rep switch
    {
        >= 85 => "World-class",
        >= 70 => "Renowned",
        >= 55 => "Established",
        >= 40 => "Respected",
        >= 25 => "Emerging",
        _ => "Unknown",
    };
}
