namespace ML.Ingest;

/// <summary>
/// A stat field's location on the full-time screen, stored in NORMALISED coordinates (0..1) so a
/// profile calibrated at one resolution keeps working at another. Kind drives the OCR settings —
/// numeric fields get a digit whitelist, which is the single biggest accuracy win.
/// </summary>
public sealed record StatRegion(string Field, RegionKind Kind, double X, double Y, double W, double H)
{
    public (int X, int Y, int W, int H) ToPixels(int imageW, int imageH) => (
        (int)Math.Round(X * imageW),
        (int)Math.Round(Y * imageH),
        (int)Math.Round(W * imageW),
        (int)Math.Round(H * imageH));
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
            new("home_score", RegionKind.Number, 0.42, 0.10, 0.05, 0.08),
            new("away_score", RegionKind.Number, 0.53, 0.10, 0.05, 0.08),
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
