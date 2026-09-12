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

    /// <summary>A 0-99 ability as a qualitative letter grade (F..A+) — the app never shows the raw
    /// number, only this. A 99 is A+, a 40 is F, so the world's crap players read as crap.</summary>
    public static string Grade(int value) => value switch
    {
        >= 90 => "A+",
        >= 85 => "A",
        >= 82 => "A-",
        >= 78 => "B+",
        >= 74 => "B",
        >= 70 => "B-",
        >= 66 => "C+",
        >= 62 => "C",
        >= 58 => "C-",
        >= 52 => "D",
        _ => "F",
    };

    /// <summary>The grade you're allowed to SEE at a knowledge level: the true letter once a player
    /// is well-scouted (>=75) or on your team (100); an approximate "B?" while part-scouted; a bare
    /// "?" until you've scouted enough. This is the overall-rating equivalent of per-attribute
    /// masking.</summary>
    public static string GradeMasked(int value, int knowledge) =>
        knowledge >= 75 ? Grade(value) : knowledge >= 45 ? Grade(value) + "?" : "?";

    /// <summary>
    /// How much knowledge one attribute costs to see, 0-99. The unbiased order: a stable
    /// pseudo-random difficulty per (player, attribute), so the same partial dossier always
    /// shows the same subset. <see cref="RevealOrder"/> blends this with a famous player's
    /// standout ranking; on its own it knows nothing about who a man is.
    /// </summary>
    public static int RevealDifficulty(long playerId, string attribute)
    {
        var h = unchecked((uint)playerId * 2654435761);
        foreach (var ch in attribute) h = unchecked((h ^ ch) * 16777619);
        return (int)(h % 100);
    }

    /// <summary>
    /// Whether one attribute is revealed at a knowledge level (0-100). Deterministic per
    /// (player, attribute): the same partial dossier always shows the same subset, and more
    /// knowledge only ever reveals MORE (monotonic).
    /// </summary>
    public static bool IsRevealed(long playerId, string attribute, int knowledge)
    {
        if (knowledge >= 100) return true;
        if (knowledge <= 0) return false;
        return RevealDifficulty(playerId, attribute) < knowledge;
    }

    /// <summary>
    /// The same question, asked of a player the world may already have an opinion about. Pass
    /// the player's <see cref="RevealOrder"/> and a famous man gives up his headline abilities
    /// first; pass null and this is the plain unbiased reveal.
    /// </summary>
    public static bool IsRevealed(long playerId, string attribute, int knowledge, RevealOrder? order) =>
        order is not null
            ? order.IsRevealed(attribute, knowledge)
            : IsRevealed(playerId, attribute, knowledge);

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

    /// <summary>The 26 keys this app treats as ABILITIES — 21 outfield plus 5 keeper. The
    /// player_attributes table also carries foot, form, injury resistance and weak-foot usage,
    /// which are not abilities and belong to none of this.</summary>
    public static IReadOnlyCollection<string> AbilityKeys => Nouns.Keys;

    /// <summary>An attribute key as a coach would name it: "speed" -> "pace".</summary>
    public static string Noun(string attribute) =>
        Nouns.GetValueOrDefault(attribute, attribute.Replace('_', ' '));

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
        $"{Adjective(value)} {Noun(attribute)}";

    /// <summary>
    /// The coach's report: his standout qualities (top revealed attributes worth praising)
    /// and the flaws an opponent would target. Only revealed attributes are quotable.
    ///
    /// <para>
    /// Pass a famous player's <paramref name="order"/> and the halves separate the way they
    /// should: reputation hands you the praise for free, because the qualities a man is famous
    /// for are the first thing anyone tells you about him, while the flaws stay unquotable
    /// until somebody has actually watched him.
    /// </para>
    /// </summary>
    public static IReadOnlyList<string> CoachReport(
        long playerId, IReadOnlyDictionary<string, int> abilities, bool isGk, int knowledge,
        RevealOrder? order = null)
    {
        var relevant = abilities
            .Where(a => a.Key.StartsWith("gk_") == isGk || (!isGk && !a.Key.StartsWith("gk_")))
            .Where(a => IsRevealed(playerId, a.Key, knowledge, order))
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
