using System;
using System.Collections.Generic;
using System.IO;
using Avalonia.Media;
using Avalonia.Media.Imaging;

namespace ML.App;

/// <summary>
/// Generated visual identity — team badges, kit swatches and player avatars drawn from names and
/// club colours. Real licensed portraits/crest/kit textures need source art (or the eFootball
/// texture pipeline); until then these give every team and player a distinct, coloured identity in
/// the UI from data we already hold, rather than blank silhouettes.
/// </summary>
public static class Visuals
{
    /// <summary>"1 league" / "3 leagues" — copy never reads "1 leagues".</summary>
    public static string Plural(int n, string unit) => $"{n} {unit}{(n == 1 ? "" : "s")}";

    /// <summary>Board expectation as words, never the raw enum name.</summary>
    public static string ExpectationLabel(ML.Core.Management.Expectation e) => e switch
    {
        ML.Core.Management.Expectation.Survival => "Avoid relegation",
        ML.Core.Management.Expectation.LowerMidTable => "Comfortable safety",
        ML.Core.Management.Expectation.MidTable => "Mid-table stability",
        ML.Core.Management.Expectation.Playoffs => "Push for the play-offs",
        ML.Core.Management.Expectation.Promotion => "Win promotion",
        ML.Core.Management.Expectation.Title => "Challenge for the title",
        _ => e.ToString(),
    };

    private const string Fallback = "#3A4759";

    // Load a portrait/logo PNG off disk once and cache it; null if missing so the UI shows a
    // generated badge/avatar in its place. Real RFS art where it exists, generated fallback where not.
    // Stored paths are repo-relative (forward slashes); resolve them against the repo root found by
    // walking up from the app binary. Cache is keyed by the ORIGINAL string, pre-resolution.
    private static readonly Dictionary<string, Bitmap?> _bitmaps = new();

    // Repo root, computed once: first ancestor of the binary that contains build/master.db or
    // tools/career_seed.py. Null when the app runs detached from the repo (relative paths then miss).
    private static readonly string? RepoRoot = FindRepoRoot();
    private static string? FindRepoRoot()
    {
        try
        {
            for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
            {
                if (File.Exists(Path.Combine(dir.FullName, "build", "master.db")) ||
                    File.Exists(Path.Combine(dir.FullName, "tools", "career_seed.py")))
                    return dir.FullName;
            }
        }
        catch { /* fall through to null */ }
        return null;
    }

    public static Bitmap? LoadBitmap(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return null;
        if (_bitmaps.TryGetValue(path, out var cached)) return cached;
        Bitmap? bmp = null;
        try
        {
            var resolved = !Path.IsPathRooted(path) && RepoRoot is not null
                ? Path.Combine(RepoRoot, path)
                : path;
            if (File.Exists(resolved)) bmp = new Bitmap(resolved);
        }
        catch { bmp = null; }
        _bitmaps[path] = bmp;
        return bmp;
    }

    public static IBrush Brush(string? hex)
    {
        try { return new SolidColorBrush(Color.Parse(string.IsNullOrWhiteSpace(hex) ? Fallback : hex)); }
        catch { return new SolidColorBrush(Color.Parse(Fallback)); }
    }

    /// <summary>Two-letter club mark: "FK Partizan Belgrade" -> "PB", "Red Star Belgrade" -> "RS".</summary>
    public static string Initials(string name)
    {
        var cleaned = name.Replace("FK ", "").Replace("OFK ", "").Trim();
        var words = cleaned.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (words.Length == 0) return "?";
        if (words.Length == 1) return words[0][..Math.Min(2, words[0].Length)].ToUpperInvariant();
        return ($"{words[0][0]}{words[^1][0]}").ToUpperInvariant();
    }

    /// <summary>Player mark from a surname — the last word's first two letters, e.g. "Zdjelar" -> "ZD".</summary>
    public static string PlayerMark(string name)
    {
        var words = name.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var surname = words.Length > 0 ? words[^1] : name;
        return surname.Length >= 2 ? surname[..2].ToUpperInvariant()
             : surname.ToUpperInvariant();
    }

    /// <summary>
    /// Generated-avatar ground from the player's REAL skin tone (1 lightest – 6 darkest,
    /// the PlayerAppearance/RFS field) — the face fallback where no portrait exists.
    /// </summary>
    public static IBrush SkinBrush(int? tone) => Brush(tone switch
    {
        1 => "#F0D2B6", 2 => "#E3BD95", 3 => "#CDA173",
        4 => "#A97B4F", 5 => "#7E5633", 6 => "#573A21", _ => "#3A4453",
    });

    /// <summary>
    /// Hair colour for the generated avatar, from the PlayerAppearance hair_color field (0 black –
    /// 5 lightest). Pairs with <see cref="SkinBrush"/> to give the tier-3 generic face real colours.
    /// </summary>
    public static IBrush HairBrush(int? hair) => Brush(hair switch
    {
        0 => "#1B1712", 1 => "#3B2A1C", 2 => "#5A3A22", 3 => "#8A5A2B",
        4 => "#C79A50", 5 => "#E4C77E", _ => "#241C16",
    });

    /// <summary>Colour a player avatar by unit so a squad list reads at a glance.</summary>
    public static IBrush PositionBrush(string position) => position switch
    {
        "GK" => Brush("#E0A526"),
        "CB" or "LB" or "RB" or "LWB" or "RWB" => Brush("#2D7DD2"),
        "DMF" or "CMF" or "LMF" or "RMF" or "AMF" => Brush("#1F9D4D"),
        _ => Brush("#D64545"),
    };

    // --- Shared rating / role / radar helpers (consumed by Squad card, Tactics, Dashboard) ---

    private static readonly IBrush RatingHigh = new SolidColorBrush(Color.Parse("#8BE04A"));
    private static readonly IBrush RatingMid = new SolidColorBrush(Color.Parse("#F0A030"));
    private static readonly IBrush RatingLow = new SolidColorBrush(Color.Parse("#E05545"));

    /// <summary>eFootball-style rating colour: ≥80 green, 70–79 amber, below red.</summary>
    public static IBrush RatingBrush(int rating) =>
        rating >= 80 ? RatingHigh : rating >= 70 ? RatingMid : RatingLow;

    /// <summary>Registered-position code (Player.bin) → position label. Unknown codes read as CMF.</summary>
    public static string RoleCodeLabel(int code) => code switch
    {
        0 => "GK",
        1 => "CB",
        2 => "LB",
        3 => "RB",
        4 => "DMF",
        5 => "CMF",
        6 => "LMF",
        7 => "RMF",
        8 => "AMF",
        9 => "LWF",
        10 => "RWF",
        11 => "SS",
        12 => "CF",
        _ => "CMF",
    };

    /// <summary>Position label → registered-position code. Wingbacks map onto the fullback codes.</summary>
    public static int LabelRoleCode(string label) => (label ?? "").Trim().ToUpperInvariant() switch
    {
        "GK" => 0,
        "CB" => 1,
        "LB" => 2,
        "LWB" => 2,
        "RB" => 3,
        "RWB" => 3,
        "DMF" => 4,
        "CMF" => 5,
        "LMF" => 6,
        "RMF" => 7,
        "AMF" => 8,
        "LWF" => 9,
        "RWF" => 10,
        "SS" => 11,
        "CF" => 12,
        _ => 5,
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
        new[] { "finishing", "kicking_power", "offensive_awareness", "heading" },          // SHO
        new[] { "low_pass", "lofted_pass", "curl", "set_piece_taking" },                   // PAS
        new[] { "ball_control", "dribbling", "tight_possession", "balance" },              // DRI
        new[] { "speed", "acceleration" },                                                 // SPD
        new[] { "defensive_awareness", "tackling", "defensive_engagement", "aggression" }, // DEF
        new[] { "physical_contact", "jumping", "stamina" },                                // STR
    };

    private static readonly string[][] GkRadarGroups =
    {
        new[] { "gk_awareness" },              // SHO
        new[] { "low_pass", "lofted_pass" },   // PAS
        new[] { "gk_catching" },               // DRI
        new[] { "gk_reflexes" },               // SPD
        new[] { "gk_parrying" },               // DEF
        new[] { "gk_reach" },                  // STR
    };

    private static readonly string[] RadarLabels = { "SHO", "PAS", "DRI", "SPD", "DEF", "STR" };

    /// <summary>
    /// Six radar axes for the player card, each the average of its ability group (missing
    /// abilities read as 40). Labels are always SHO/PAS/DRI/SPD/DEF/STR; GKs get the
    /// goalkeeping abilities behind the same labels.
    /// </summary>
    public static (string Label, double Value)[] RadarAxes(IReadOnlyDictionary<string, int> abilities, bool isGk)
    {
        var groups = isGk ? GkRadarGroups : OutfieldRadarGroups;
        var axes = new (string Label, double Value)[RadarLabels.Length];
        for (var i = 0; i < RadarLabels.Length; i++)
        {
            var total = 0.0;
            foreach (var key in groups[i])
            {
                total += abilities.TryGetValue(key, out var v) ? v : 40;
            }
            axes[i] = (RadarLabels[i], total / groups[i].Length);
        }
        return axes;
    }
}
