namespace ML.Core.Selection;

/// <summary>
/// When cards become bans. Pure rules over counts — Session reads the counts out of match_events
/// and persists what these return.
///
/// A red card is one match. Every fifth yellow card of the season is one match. A sending-off for
/// two bookings is ONE offence: those two yellows bought the red and do not also count toward the
/// five. Friendlies neither hand out bans nor serve them (Session's side of the rule).
/// </summary>
public static class SuspensionRules
{
    /// <summary>Season yellows that trigger a one-match ban, and every multiple of it after.</summary>
    public const int YellowsPerBan = 5;

    /// <summary>Matches missed for a sending-off.</summary>
    public const int RedCardBan = 1;

    /// <summary>The yellows from one match that count toward accumulation.</summary>
    public static int CountedYellows(int redsThisMatch, int yellowsThisMatch) =>
        Math.Max(0, redsThisMatch > 0 && yellowsThisMatch >= 2 ? yellowsThisMatch - 2 : yellowsThisMatch);

    /// <summary>
    /// Matches a player must now sit out after a fixture in which he collected these cards, given
    /// the counted yellows he already had this season. 0 = no ban.
    /// </summary>
    public static int MatchesFor(int redsThisMatch, int yellowsThisMatch, int seasonYellowsBefore)
    {
        var ban = redsThisMatch > 0 ? RedCardBan : 0;
        var after = seasonYellowsBefore + CountedYellows(redsThisMatch, yellowsThisMatch);
        if (after / YellowsPerBan > seasonYellowsBefore / YellowsPerBan) ban++;
        return ban;
    }

    /// <summary>Why, in the words the manager reads: "red card", "5 yellow cards", or both.</summary>
    public static string Reason(int redsThisMatch, int yellowsThisMatch, int seasonYellowsBefore)
    {
        var after = seasonYellowsBefore + CountedYellows(redsThisMatch, yellowsThisMatch);
        var crossed = after / YellowsPerBan > seasonYellowsBefore / YellowsPerBan;
        var tally = $"{after / YellowsPerBan * YellowsPerBan} yellow cards";
        return redsThisMatch > 0 ? (crossed ? $"red card and {tally}" : "red card") : tally;
    }
}
