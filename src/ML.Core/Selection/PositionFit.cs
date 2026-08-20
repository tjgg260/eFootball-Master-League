namespace ML.Core.Selection;

public enum Fit
{
    Natural,   // registered or learned position
    Ok,        // same unit (a CB can do RB, a CMF can do AMF)
    Awkward,   // out of unit — a real penalty on the pitch
}

/// <summary>
/// Positional familiarity. eFootball models per-position aptitude; ours is three-valued:
/// a player is Natural in his registered position and any position he has trained into,
/// Ok elsewhere in the same unit, and Awkward outside it. Goalkeeping is special both ways.
/// </summary>
public static class PositionFit
{
    public static string Category(string pos) => (pos ?? "").Trim().ToUpperInvariant() switch
    {
        "GK" => "GK",
        "CB" or "LB" or "RB" or "LWB" or "RWB" => "DEF",
        "DMF" or "CMF" or "LMF" or "RMF" or "AMF" => "MID",
        _ => "FWD",
    };

    public static Fit Of(string registered, IReadOnlyCollection<string> learned, string slot)
    {
        var reg = (registered ?? "").Trim().ToUpperInvariant();
        var target = (slot ?? "").Trim().ToUpperInvariant();
        if (reg == target) return Fit.Natural;
        if (learned.Any(l => string.Equals(l?.Trim(), target, StringComparison.OrdinalIgnoreCase)))
            return Fit.Natural;
        // Wingbacks are the fullback slots by another name.
        if (Pair(reg) == target || Pair(target) == reg) return Fit.Natural;
        if (Category(reg) == "GK" || target == "GK") return Fit.Awkward;
        return Category(reg) == Category(target) ? Fit.Ok : Fit.Awkward;
    }

    private static string Pair(string p) => p switch
    {
        "LWB" => "LB", "LB" => "LWB", "RWB" => "RB", "RB" => "RWB", _ => "",
    };

    /// <summary>Score adjustment the XI selector applies for a candidate in a slot.</summary>
    public static double Bonus(Fit fit) => fit switch
    {
        Fit.Natural => 3.0,
        Fit.Ok => 0.0,
        _ => -6.0,
    };
}
