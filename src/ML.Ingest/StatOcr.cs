using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;
using Tesseract;

namespace ML.Ingest;

/// <summary>
/// Reads a full-time stats screenshot into <see cref="MatchStats"/> by cropping each calibrated
/// region and OCRing it in ISOLATION. Never OCR the whole frame — accuracy collapses. Numeric
/// regions get a digit whitelist and single-line mode, which is what makes the scores reliable.
/// </summary>
public sealed class StatOcr : IDisposable
{
    private readonly TesseractEngine _engine;

    public StatOcr(string tessdataPath, string language = "eng")
    {
        _engine = new TesseractEngine(tessdataPath, language, EngineMode.Default);
    }

    public MatchStats Read(string imagePath, CalibrationProfile profile)
    {
        using var image = Image.Load<Rgba32>(imagePath);
        var stats = new MatchStats();

        foreach (var region in profile.Regions)
        {
            var (value, confidence, text) = ReadRegion(image, region);
            switch (region.Field)
            {
                case "home_score":
                    stats.HomeScore = new OcrValue<int>(value, confidence);
                    break;
                case "away_score":
                    stats.AwayScore = new OcrValue<int>(value, confidence);
                    break;
                case "scorers":
                    stats.ScorersRaw = new OcrValue<string>(text.Trim(), confidence);
                    break;
                default:
                    stats.Numbers[region.Field] = new OcrValue<int>(value, confidence);
                    break;
            }
        }

        return stats;
    }

    private (int Value, double Confidence, string Text) ReadRegion(Image<Rgba32> image, StatRegion region)
    {
        var (x, y, w, h) = region.ToPixels(image.Width, image.Height);
        x = Math.Clamp(x, 0, image.Width - 1);
        y = Math.Clamp(y, 0, image.Height - 1);
        w = Math.Clamp(w, 1, image.Width - x);
        h = Math.Clamp(h, 1, image.Height - y);

        using var crop = image.Clone(ctx => ctx
            .Crop(new Rectangle(x, y, w, h))
            .Grayscale()
            .Contrast(1.2f));

        using var ms = new MemoryStream();
        crop.SaveAsPng(ms);

        using var pix = Pix.LoadFromMemory(ms.ToArray());
        SetWhitelist(region.Kind);
        var mode = region.Kind == RegionKind.Text ? PageSegMode.SingleBlock : PageSegMode.SingleLine;
        using var page = _engine.Process(pix, mode);

        var text = page.GetText() ?? string.Empty;
        var confidence = page.GetMeanConfidence();
        var value = ParseNumber(text);
        return (value, confidence, text);
    }

    private void SetWhitelist(RegionKind kind)
    {
        var whitelist = kind switch
        {
            RegionKind.Number => "0123456789",
            RegionKind.Percentage => "0123456789%",
            _ => string.Empty,
        };
        _engine.SetVariable("tessedit_char_whitelist", whitelist);
    }

    private static int ParseNumber(string text)
    {
        var digits = new string(text.Where(char.IsDigit).ToArray());
        return int.TryParse(digits, out var n) ? n : 0;
    }

    /// <summary>
    /// Whole-image OCR for keyword-anchored parsing (the post-match STATS screen): no region
    /// calibration needed — callers regex the returned text for "Possession 62% 38%" style rows.
    /// </summary>
    public string ReadFullText(string imagePath)
    {
        using var img = Tesseract.Pix.LoadFromFile(imagePath);
        using var page = _engine.Process(img);
        return page.GetText() ?? "";
    }

    public void Dispose() => _engine.Dispose();
}
