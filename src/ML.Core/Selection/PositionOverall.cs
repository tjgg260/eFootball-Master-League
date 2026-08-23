namespace ML.Core.Selection;

/// <summary>
/// A player's overall AT A SPECIFIC POSITION, computed from his abilities the same way the data
/// pipeline computes his native overall (tools/fm_data_pass.py): rank the position's core
/// abilities and lean on the best few (0.55/0.32/0.13 top-weighting). A winger asked to keep goal
/// is scored on his gk_* abilities (~40 = F); a centre-back at CF is scored on finishing and
/// movement he doesn't have. This drives both the letter grade shown on the pitch and the AI's
/// XI selection, so "who fits here" and "what you see" can never disagree.
/// </summary>
public static class PositionOverall
{
    private static readonly Dictionary<string, string[]> Core = new()
    {
        ["GK"] = new[] { "gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach", "low_pass" },
        ["CB"] = new[] { "defensive_awareness", "tackling", "heading", "physical_contact", "jumping", "speed", "balance", "low_pass" },
        ["LB"] = new[] { "defensive_awareness", "tackling", "speed", "acceleration", "stamina", "low_pass", "dribbling", "tight_possession", "curl" },
        ["RB"] = new[] { "defensive_awareness", "tackling", "speed", "acceleration", "stamina", "low_pass", "dribbling", "tight_possession", "curl" },
        ["LWB"] = new[] { "defensive_awareness", "tackling", "speed", "acceleration", "stamina", "low_pass", "dribbling", "tight_possession", "curl" },
        ["RWB"] = new[] { "defensive_awareness", "tackling", "speed", "acceleration", "stamina", "low_pass", "dribbling", "tight_possession", "curl" },
        ["DMF"] = new[] { "defensive_awareness", "tackling", "low_pass", "lofted_pass", "ball_control", "physical_contact", "stamina", "offensive_awareness" },
        ["CMF"] = new[] { "low_pass", "lofted_pass", "ball_control", "tight_possession", "offensive_awareness", "defensive_awareness", "stamina", "dribbling" },
        ["LMF"] = new[] { "speed", "acceleration", "dribbling", "ball_control", "tight_possession", "low_pass", "curl", "stamina", "offensive_awareness" },
        ["RMF"] = new[] { "speed", "acceleration", "dribbling", "ball_control", "tight_possession", "low_pass", "curl", "stamina", "offensive_awareness" },
        ["AMF"] = new[] { "offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass", "lofted_pass", "finishing", "curl" },
        ["LWF"] = new[] { "offensive_awareness", "ball_control", "dribbling", "tight_possession", "speed", "acceleration", "finishing", "curl" },
        ["RWF"] = new[] { "offensive_awareness", "ball_control", "dribbling", "tight_possession", "speed", "acceleration", "finishing", "curl" },
        ["CF"] = new[] { "offensive_awareness", "finishing", "ball_control", "dribbling", "heading", "speed", "acceleration", "physical_contact", "kicking_power" },
        ["SS"] = new[] { "offensive_awareness", "finishing", "ball_control", "dribbling", "tight_possession", "speed", "acceleration", "low_pass" },
    };

    private static readonly string[] Fallback =
    {
        "offensive_awareness", "ball_control", "dribbling", "low_pass", "finishing",
        "speed", "physical_contact", "stamina", "defensive_awareness", "tackling",
    };

    /// <summary>Overall at <paramref name="position"/>, or null when abilities are unknown.</summary>
    public static int? Of(IReadOnlyDictionary<string, int>? abilities, string position)
    {
        if (abilities is null || abilities.Count == 0) return null;
        var core = Core.GetValueOrDefault((position ?? "").Trim().ToUpperInvariant(), Fallback);
        var vals = core.Select(k => abilities.GetValueOrDefault(k, 40))
            .OrderByDescending(v => v).ToList();
        if (vals.Count == 0) return null;
        static double Mean(IReadOnlyList<int> xs) => xs.Count == 0 ? 0 : xs.Average();
        var top = vals.Take(3).ToList();
        var mid = vals.Skip(3).Take(3).ToList();
        var rest = vals.Skip(6).ToList();
        var ov = 0.55 * Mean(top) + 0.32 * Mean(mid) + 0.13 * Mean(rest.Count > 0 ? rest : mid);
        return Math.Max(1, Math.Min(99, (int)Math.Round(ov)));
    }
}
