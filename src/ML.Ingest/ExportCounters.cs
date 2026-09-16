namespace ML.Ingest;

/// <summary>
/// Engine counters efootball-re identified after the host this project vendors was built, read by
/// engine id rather than by name. That makes them work on every export already written: the host
/// puts every non-zero counter into <c>raw_totals</c> (per team) and <c>raw_segments</c> (per
/// player) whether or not its LABELS table has a name for it, so a card shown in a match played
/// with the old host is in its export already. When the host's own labels name these ids, the ids
/// stay the same and nothing here needs to change.
///
/// Identified on two live matches (2026-09-16). The confidence text is efootball-re's own finding:
/// "verified" is a counter checked against events and against counter-examples; "measured" agrees
/// with the game's own screen; "inferred" is consistent with every match seen but not yet pinned.
/// </summary>
public static class ExportCounters
{
    public const string PenaltyGoals = "0x03";
    public const string FinesseShotGoals = "0x13";
    public const string ChipShots = "0x14";
    public const string YellowCards = "0x3E";
    public const string RedCards = "0x3F";
    public const string KeeperShotsFaced = "0x6D";
    public const string KeeperShotsOnTargetFaced = "0x6E";

    /// <param name="Key">The name the report and the league use for it (the host's name where it has one).</param>
    public sealed record Counter(string Id, string Key, string Label, string Confidence)
    {
        public bool Inferred => Confidence.StartsWith("inferred", StringComparison.OrdinalIgnoreCase);
    }

    public static readonly IReadOnlyList<Counter> Identified = new Counter[]
    {
        new(YellowCards, "yellow_cards", "Yellow cards",
            "verified: moved on all 9 bookings seen; 2 fouls without a card left it unchanged"),
        new(RedCards, "red_cards", "Red cards",
            "verified: moved on all 4 second-yellow dismissals seen; a straight red has not been seen yet"),
        new(PenaltyGoals, "penalty_goals", "Penalty goals",
            "verified: counts a scored penalty; the award, a saved penalty and open-play goals leave it unchanged"),
        new(FinesseShotGoals, "finesse_shot_goals", "Finesse-shot goals",
            "verified: moved on 8+ finesse-shot goals; headers, penalties, power shots, chips and normal shots all leave it unchanged"),
        new(ChipShots, "chip_shots", "Chip shots",
            "inferred: zero in 15 finished matches, and 1 each for the two players who chipped on stream; attempts and goals not yet told apart"),
        new(KeeperShotsFaced, "gk_shots_faced", "Shots faced (keeper)",
            "measured: agrees item by item with the game's own screen (9 of 9)"),
        new(KeeperShotsOnTargetFaced, "gk_shots_on_target_faced", "On target faced (keeper)",
            "measured: agrees item by item with the game's own screen (7 of 7)"),
    };

    public static Counter? ById(string id) =>
        Identified.FirstOrDefault(c => string.Equals(c.Id, id, StringComparison.OrdinalIgnoreCase));

    public static Counter? ByKey(string key) =>
        Identified.FirstOrDefault(c => string.Equals(c.Key, key, StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// An entry by engine id. The host writes ids as <c>0x3E</c>; the lookup tolerates any case so
    /// a change of formatting on the host side cannot silently zero a counter.
    /// </summary>
    internal static bool TryLookup<T>(IReadOnlyDictionary<string, T>? map, string id, out T value)
    {
        value = default!;
        if (map is null) return false;
        if (map.TryGetValue(id, out var exact)) { value = exact; return true; }
        foreach (var (k, v) in map)
            if (string.Equals(k, id, StringComparison.OrdinalIgnoreCase)) { value = v; return true; }
        return false;
    }
}
