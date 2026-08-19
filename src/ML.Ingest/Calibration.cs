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
    /// A starting-point layout for eFootball's full-time stats screen at 1920x1080. These are
    /// deliberately approximate — Phase 3's calibration UI exists so the user corrects them once
    /// against a real screenshot; hard-coding exact pixels would be guessing.
    /// </summary>
    public static CalibrationProfile Default1080p() => new()
    {
        Name = "eFootball full-time 1080p (starter)",
        Width = 1920,
        Height = 1080,
        Regions = new StatRegion[]
        {
            new("home_score", RegionKind.Number, 0.42, 0.10, 0.05, 0.08),
            new("away_score", RegionKind.Number, 0.53, 0.10, 0.05, 0.08),
            new("home_possession", RegionKind.Percentage, 0.30, 0.30, 0.07, 0.05),
            new("away_possession", RegionKind.Percentage, 0.63, 0.30, 0.07, 0.05),
            new("home_shots", RegionKind.Number, 0.30, 0.38, 0.06, 0.05),
            new("away_shots", RegionKind.Number, 0.64, 0.38, 0.06, 0.05),
            new("home_shots_on_target", RegionKind.Number, 0.30, 0.44, 0.06, 0.05),
            new("away_shots_on_target", RegionKind.Number, 0.64, 0.44, 0.06, 0.05),
            new("home_fouls", RegionKind.Number, 0.30, 0.50, 0.06, 0.05),
            new("away_fouls", RegionKind.Number, 0.64, 0.50, 0.06, 0.05),
            new("home_corners", RegionKind.Number, 0.30, 0.56, 0.06, 0.05),
            new("away_corners", RegionKind.Number, 0.64, 0.56, 0.06, 0.05),
            new("scorers", RegionKind.Text, 0.20, 0.66, 0.60, 0.25),
        },
    };
}
