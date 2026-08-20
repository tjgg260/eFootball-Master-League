namespace ML.Core.Selection;

/// <summary>
/// Maps the game's formation-slot role codes (0-12, formation_slots.position) onto the four
/// coarse categories <see cref="XiSelector"/> matches players against.
/// </summary>
public static class PositionCodes
{
    public const string Gk = "GK";
    public const string Def = "DEF";
    public const string Mid = "MID";
    public const string Fwd = "FWD";

    /// <summary>0 = GK, 1-3 = DEF, 4-8 = MID, 9-12 = FWD. Anything else is corrupt slot data.</summary>
    public static string ToCategory(int roleCode) => roleCode switch
    {
        0 => Gk,
        >= 1 and <= 3 => Def,
        >= 4 and <= 8 => Mid,
        >= 9 and <= 12 => Fwd,
        _ => throw new ArgumentOutOfRangeException(nameof(roleCode), roleCode,
            "Role codes are 0-12; anything else is corrupt formation data."),
    };
}
