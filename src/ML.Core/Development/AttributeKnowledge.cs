namespace ML.Core.Development;

/// <summary>
/// The FM-style attribute presentation layer: four colour bands instead of numbers, a
/// knowledge model that hides what you have not scouted, and the coach's verbal read of a
/// player. Pure maths/wording — persistence and toggles live in the app layer.
/// </summary>
public static class AttributeKnowledge
{
    /// <summary>The four bands: 0 poor, 1 average, 2 good, 3 elite.</summary>
    public static int Band(int value) => value switch
    {
        >= 80 => 3,
        >= 70 => 2,
        >= 58 => 1,
        _ => 0,
    };

    public static string BandName(int band) => band switch
    {
        3 => "Elite", 2 => "Good", 1 => "Average", _ => "Poor",
    };

    /// <summary>
    /// Whether one attribute is revealed at a knowledge level (0-100). Deterministic per
    /// (player, attribute): the same partial dossier always shows the same subset, and more
    /// knowledge only ever reveals MORE (monotonic).
    /// </summary>
    public static bool IsRevealed(int playerId, string attribute, int knowledge)
    {
        if (knowledge >= 100) return true;
        if (knowledge <= 0) return false;
        var h = unchecked((uint)playerId * 2654435761);
        foreach (var ch in attribute) h = unchecked((h ^ ch) * 16777619);
        return h % 100 < (uint)knowledge;
    }

    public static string KnowledgeLabel(int knowledge) => knowledge switch
    {
        >= 100 => "Fully known",
        >= 75 => "Well scouted",
        >= 45 => "Part-scouted",
        >= 15 => "Glimpsed",
        _ => "Unknown",
    };

    // ---------------------------------------------------------------- the coach's voice

    private static readonly Dictionary<string, string> Nouns = new()
    {
        ["ball_control"] = "close control",
        ["dribbling"] = "dribbling",
        ["tight_possession"] = "possession under pressure",
        ["low_pass"] = "short passing",
        ["lofted_pass"] = "long passing",
        ["finishing"] = "finishing",
        ["heading"] = "heading",
        ["set_piece_taking"] = "set-piece delivery",
        ["curl"] = "curled deliveries",
        ["speed"] = "pace",
        ["acceleration"] = "burst over the first yards",
        ["kicking_power"] = "striking power",
        ["jumping"] = "leap",
        ["physical_contact"] = "physicality",
        ["balance"] = "balance",
        ["stamina"] = "engine",
        ["defensive_awareness"] = "defensive reading",
        ["tackling"] = "tackling",
        ["aggression"] = "bite in the duels",
        ["defensive_engagement"] = "pressing",
        ["offensive_awareness"] = "movement in the final third",
        ["gk_awareness"] = "command of his area",
        ["gk_catching"] = "handling",
        ["gk_parrying"] = "shot-stopping",
        ["gk_reflexes"] = "reflexes",
        ["gk_reach"] = "reach",
    };

    private static string Adjective(int value) => value switch
    {
        >= 88 => "Exceptional",
        >= 80 => "Excellent",
        >= 72 => "Good",
        >= 62 => "Tidy",
        >= 52 => "Modest",
        _ => "Poor",
    };

    /// <summary>"Exceptional close control", "Poor heading" — one coach line per attribute.</summary>
    public static string CoachPhrase(string attribute, int value) =>
        $"{Adjective(value)} {Nouns.GetValueOrDefault(attribute, attribute.Replace('_', ' '))}";

    /// <summary>
    /// The coach's report: his standout qualities (top revealed attributes worth praising)
    /// and the flaws an opponent would target. Only revealed attributes are quotable.
    /// </summary>
    public static IReadOnlyList<string> CoachReport(
        int playerId, IReadOnlyDictionary<string, int> abilities, bool isGk, int knowledge)
    {
        var relevant = abilities
            .Where(a => a.Key.StartsWith("gk_") == isGk || (!isGk && !a.Key.StartsWith("gk_")))
            .Where(a => IsRevealed(playerId, a.Key, knowledge))
            .Where(a => Nouns.ContainsKey(a.Key))
            .ToList();
        var lines = relevant.OrderByDescending(a => a.Value).Take(3)
            .Where(a => a.Value >= 62)
            .Select(a => CoachPhrase(a.Key, a.Value))
            .ToList();
        lines.AddRange(relevant.OrderBy(a => a.Value).Take(2)
            .Where(a => a.Value <= 55)
            .Select(a => CoachPhrase(a.Key, a.Value)));
        return lines;
    }
}
