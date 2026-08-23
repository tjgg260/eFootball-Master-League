namespace ML.Ingest;

/// <summary>
/// How normalised (0..1) region coordinates map onto a real screenshot. The game on this machine
/// renders NATIVE 16:10 at 2560x1600 (verified against a real F12 capture: the full-time banner
/// spans the full frame), so Native is the default. Letterbox16x9 is for setups that render a
/// 16:9 frame with bars inside a taller/wider screenshot.
/// </summary>
public enum AspectMode
{
    /// <summary>Normalised coordinates apply to the full image, whatever its aspect.</summary>
    Native,

    /// <summary>
    /// Normalised coordinates apply to a centred 16:9 content box inside the image
    /// (black bars top/bottom on 16:10, pillarboxed on ultrawide).
    /// </summary>
    Letterbox16x9,
}

/// <summary>
/// A stat field's location on the full-time screen, stored in NORMALISED coordinates (0..1) so a
/// profile calibrated at one resolution keeps working at another. Kind drives the OCR settings —
/// numeric fields get a digit whitelist, which is the single biggest accuracy win.
/// </summary>
public sealed record StatRegion(string Field, RegionKind Kind, double X, double Y, double W, double H)
{
    public (int X, int Y, int W, int H) ToPixels(int imageW, int imageH) =>
        ToPixels(imageW, imageH, AspectMode.Native);

    /// <summary>
    /// Resolution-aware mapping: the normalised rect is applied to the ACTUAL image dimensions
    /// (or to the centred 16:9 content box when the profile says the game letterboxes).
    /// </summary>
    public (int X, int Y, int W, int H) ToPixels(int imageW, int imageH, AspectMode aspect)
    {
        var (cx, cy, cw, ch) = ContentRect(imageW, imageH, aspect);
        return (
            (int)Math.Round(cx + X * cw),
            (int)Math.Round(cy + Y * ch),
            (int)Math.Round(W * cw),
            (int)Math.Round(H * ch));
    }

    /// <summary>The pixel box the normalised coordinates are relative to.</summary>
    public static (double X, double Y, double W, double H) ContentRect(int imageW, int imageH, AspectMode aspect)
    {
        if (aspect != AspectMode.Letterbox16x9) return (0, 0, imageW, imageH);
        var targetH = imageW * 9.0 / 16.0;
        if (targetH <= imageH) return (0, (imageH - targetH) / 2.0, imageW, targetH);   // bars top/bottom
        var targetW = imageH * 16.0 / 9.0;
        return ((imageW - targetW) / 2.0, 0, targetW, imageH);                          // pillarboxed
    }
}

public enum RegionKind
{
    /// <summary>Digits only — score, possession, shots, fouls. Whitelisted to 0-9.</summary>
    Number,

    /// <summary>Percentage like possession "58%". Whitelisted to digits and %.</summary>
    Percentage,

    /// <summary>Free text — the scorer list. No whitelist; hardest to read, always reviewed.</summary>
    Text,
}

/// <summary>
/// A calibration profile for one screen layout at one resolution. The user drags boxes over one
/// sample screenshot; we store the normalised rectangles. Ships with a default 1920x1080 layout
/// that the user nudges rather than builds from nothing.
/// </summary>
public sealed class CalibrationProfile
{
    public required string Name { get; init; }
    public required int Width { get; init; }
    public required int Height { get; init; }
    public required IReadOnlyList<StatRegion> Regions { get; init; }

    /// <summary>How this profile's normalised coordinates map onto a screenshot (per-profile).</summary>
    public AspectMode Aspect { get; init; } = AspectMode.Native;

    // Score-box positions measured off a REAL 2560x1600 (16:10) full-time capture — the banner
    // scales with the frame, so the same fractions hold at 1080p. [x, y, w, h] normalised.
    // Deliberately INSIDE the yellow score boxes: a sliver of the navy banner at the crop edge
    // binarises into a bar that Tesseract happily reads as a "1".
    public static readonly double[] DefaultHomeScoreRegion = { 0.442, 0.203, 0.030, 0.045 };
    public static readonly double[] DefaultAwayScoreRegion = { 0.522, 0.203, 0.030, 0.045 };

    /// <summary>
    /// A minimal profile that reads ONLY the two score boxes — the score-import path. Two OCR
    /// passes instead of forty makes the F12 capture feel instant, and it is the profile the
    /// Settings calibration screen edits.
    /// </summary>
    public static CalibrationProfile ScoreOnly(
        double[] home, double[] away, AspectMode aspect = AspectMode.Native) => new()
    {
        Name = "eFootball full-time score",
        Width = 2560,
        Height = 1600,
        Aspect = aspect,
        Regions = new List<StatRegion>
        {
            new("home_score", RegionKind.Number, home[0], home[1], home[2], home[3]),
            new("away_score", RegionKind.Number, away[0], away[1], away[2], away[3]),
        },
    };

    /// <summary>
    /// The full eFootball full-time stat table, in the order the game lists it. Every stat has a
    /// home and away column. These are the stat rows eFootball actually shows — the profile
    /// captures all of them; the calibration UI just nudges the row band to the real screenshot.
    /// </summary>
    public static readonly IReadOnlyList<(string Key, RegionKind Kind)> StatRows = new[]
    {
        ("possession", RegionKind.Percentage),
        ("shots", RegionKind.Number),
        ("shots_on_target", RegionKind.Number),
        ("fouls", RegionKind.Number),
        ("offside", RegionKind.Number),
        ("corner_kicks", RegionKind.Number),
        ("free_kicks", RegionKind.Number),
        ("passes", RegionKind.Number),
        ("pass_accuracy", RegionKind.Percentage),
        ("crosses", RegionKind.Number),
        ("interceptions", RegionKind.Number),
        ("tackles", RegionKind.Number),
        ("saves", RegionKind.Number),
        ("possession_time", RegionKind.Number),
        ("ball_recovery", RegionKind.Number),
        ("clearances", RegionKind.Number),
        ("shots_blocked", RegionKind.Number),
        ("yellow_cards", RegionKind.Number),
        ("red_cards", RegionKind.Number),
    };

    /// <summary>
    /// A starting-point layout for eFootball's full-time stats screen at 1920x1080. The score sits
    /// up top; the stat table is a two-column grid the calibration UI aligns once against a real
    /// screenshot — hard-coding exact pixels would be guessing, so these are honest approximations.
    /// </summary>
    public static CalibrationProfile Default1080p()
    {
        var regions = new List<StatRegion>
        {
            // Measured off a real capture (the old 0.10 band sat ABOVE the banner and read air).
            new("home_score", RegionKind.Number,
                DefaultHomeScoreRegion[0], DefaultHomeScoreRegion[1],
                DefaultHomeScoreRegion[2], DefaultHomeScoreRegion[3]),
            new("away_score", RegionKind.Number,
                DefaultAwayScoreRegion[0], DefaultAwayScoreRegion[1],
                DefaultAwayScoreRegion[2], DefaultAwayScoreRegion[3]),
        };

        // The stat table occupies a vertical band; distribute the rows evenly down it. Home
        // column on the left of centre, away on the right.
        const double tableTop = 0.28, tableBottom = 0.80;
        const double rowH = 0.035, colW = 0.07;
        var n = StatRows.Count;
        for (var i = 0; i < n; i++)
        {
            var (key, kind) = StatRows[i];
            var y = tableTop + (tableBottom - tableTop) * i / Math.Max(1, n - 1);
            regions.Add(new StatRegion($"home_{key}", kind, 0.30, y, colW, rowH));
            regions.Add(new StatRegion($"away_{key}", kind, 0.63, y, colW, rowH));
        }

        regions.Add(new StatRegion("scorers", RegionKind.Text, 0.20, 0.82, 0.60, 0.16));

        return new CalibrationProfile
        {
            Name = "eFootball full-time 1080p (full stat table)",
            Width = 1920,
            Height = 1080,
            Regions = regions,
        };
    }
}
