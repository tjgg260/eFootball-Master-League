using System.Collections.Generic;

namespace ML.App;

/// <summary>
/// ML.Web shim for ML.App.Visuals: the PURE helpers the shared Session engine calls
/// (position/role mapping, marks, radar math). The Avalonia brush/bitmap members of the
/// original stay in ML.App — Blazor renders with CSS instead.
/// </summary>
public static class Visuals
{
    /// <summary>Two-letter club mark: "FK Partizan Belgrade" -> "PB".</summary>
    public static string Initials(string name)
    {
        var cleaned = name.Replace("FK ", "").Replace("OFK ", "").Trim();
        var words = cleaned.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (words.Length == 0) return "?";
        if (words.Length == 1) return words[0][..Math.Min(2, words[0].Length)].ToUpperInvariant();
        return ($"{words[0][0]}{words[^1][0]}").ToUpperInvariant();
    }

    /// <summary>Player mark from a surname — the last word's first two letters.</summary>
    public static string PlayerMark(string name)
    {
        var words = name.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var surname = words.Length > 0 ? words[^1] : name;
        return surname.Length >= 2 ? surname[..2].ToUpperInvariant() : surname.ToUpperInvariant();
    }

    /// <summary>Registered-position code (Player.bin) → position label. Unknown codes read as CMF.</summary>
    public static string RoleCodeLabel(int code) => code switch
    {
        0 => "GK", 1 => "CB", 2 => "LB", 3 => "RB", 4 => "DMF", 5 => "CMF", 6 => "LMF",
        7 => "RMF", 8 => "AMF", 9 => "LWF", 10 => "RWF", 11 => "SS", 12 => "CF", _ => "CMF",
    };

    /// <summary>Position label → registered-position code. Wingbacks map onto the fullback codes.</summary>
    public static int LabelRoleCode(string label) => (label ?? "").Trim().ToUpperInvariant() switch
    {
        "GK" => 0, "CB" => 1, "LB" => 2, "LWB" => 2, "RB" => 3, "RWB" => 3, "DMF" => 4,
        "CMF" => 5, "LMF" => 6, "RMF" => 7, "AMF" => 8, "LWF" => 9, "RWF" => 10,
        "SS" => 11, "CF" => 12, _ => 5,
    };

    /// <summary>Coarse unit for a position label: GK, DEF, MID or FWD.</summary>
    public static string PositionCategory(string pos) => (pos ?? "").Trim().ToUpperInvariant() switch
    {
        "GK" => "GK",
        "CB" or "LB" or "RB" or "LWB" or "RWB" => "DEF",
        "DMF" or "CMF" or "LMF" or "RMF" or "AMF" => "MID",
        _ => "FWD",
    };

    private static readonly string[][] OutfieldRadarGroups =
    {
        new[] { "finishing", "kicking_power", "offensive_awareness", "heading" },
        new[] { "low_pass", "lofted_pass", "curl", "set_piece_taking" },
        new[] { "ball_control", "dribbling", "tight_possession", "balance" },
        new[] { "speed", "acceleration" },
        new[] { "defensive_awareness", "tackling", "defensive_engagement", "aggression" },
        new[] { "physical_contact", "jumping", "stamina" },
    };

    private static readonly string[][] GkRadarGroups =
    {
        new[] { "gk_awareness" }, new[] { "low_pass", "lofted_pass" }, new[] { "gk_catching" },
        new[] { "gk_reflexes" }, new[] { "gk_parrying" }, new[] { "gk_reach" },
    };

    private static readonly string[] RadarLabels = { "SHO", "PAS", "DRI", "SPD", "DEF", "STR" };

    /// <summary>Six radar axes for the player card (missing abilities read as 40).</summary>
    public static (string Label, double Value)[] RadarAxes(IReadOnlyDictionary<string, int> abilities, bool isGk)
    {
        var groups = isGk ? GkRadarGroups : OutfieldRadarGroups;
        var axes = new (string Label, double Value)[RadarLabels.Length];
        for (var i = 0; i < RadarLabels.Length; i++)
        {
            var total = 0.0;
            foreach (var key in groups[i])
                total += abilities.TryGetValue(key, out var v) ? v : 40;
            axes[i] = (RadarLabels[i], total / groups[i].Length);
        }
        return axes;
    }
}

/// <summary>ML.Web shim for ML.App.Theme — Blazor themes via CSS; the engine's Apply is a no-op.</summary>
public static class Theme
{
    public static string Current { get; private set; } = "Midnight";

    public static void Apply(string skinName, string? clubAccent = null) => Current = skinName;
}
