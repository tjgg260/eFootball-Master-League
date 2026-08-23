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
            var (value, confidence, text) = ReadRegion(image, region, profile.Aspect);
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

    private (int Value, double Confidence, string Text) ReadRegion(
        Image<Rgba32> image, StatRegion region, AspectMode aspect = AspectMode.Native)
    {
        var (x, y, w, h) = ClampedPixels(image, region, aspect);

        using var crop = image.Clone(ctx => ctx.Crop(new Rectangle(x, y, w, h)));

        return OcrCrop(crop, region.Kind);
    }

    private static (int X, int Y, int W, int H) ClampedPixels(
        Image<Rgba32> image, StatRegion region, AspectMode aspect)
    {
        var (x, y, w, h) = region.ToPixels(image.Width, image.Height, aspect);
        x = Math.Clamp(x, 0, image.Width - 1);
        y = Math.Clamp(y, 0, image.Height - 1);
        w = Math.Clamp(w, 1, image.Width - x);
        h = Math.Clamp(h, 1, image.Height - y);
        return (x, y, w, h);
    }

    private (int Value, double Confidence, string Text) OcrCrop(Image<Rgba32> crop, RegionKind kind)
    {
        using var prepared = kind == RegionKind.Text
            ? crop.Clone(ctx => ctx.Grayscale().Contrast(1.2f))
            : PrepareNumeric(crop);

        using var ms = new MemoryStream();
        prepared.SaveAsPng(ms);
        var png = ms.ToArray();

        SetWhitelist(kind);
        if (kind == RegionKind.Text)
        {
            return OcrPass(png, PageSegMode.SingleBlock);
        }

        // Numeric: SingleLine reads multi-digit values best (a "3" at 96%) but rejects a lone
        // "0" outright; SingleWord picks that up at 91%, SingleBlock is the last resort. All
        // measured on the real 2560x1600 capture. First pass that yields a digit wins.
        var best = OcrPass(png, PageSegMode.SingleLine);
        foreach (var fallback in new[] { PageSegMode.SingleWord, PageSegMode.SingleBlock })
        {
            if (best.Text.Any(char.IsDigit)) break;
            var retry = OcrPass(png, fallback);
            if (retry.Text.Any(char.IsDigit) || retry.Confidence > best.Confidence) best = retry;
        }
        return best;
    }

    private (int Value, double Confidence, string Text) OcrPass(byte[] png, PageSegMode mode)
    {
        using var pix = Pix.LoadFromMemory(png);
        using var page = _engine.Process(pix, mode);

        var text = page.GetText() ?? string.Empty;
        var confidence = page.GetMeanConfidence();
        var value = ParseNumber(text);
        return (value, confidence, text);
    }

    /// <summary>
    /// Numeric crops are tiny (one or two digits on a coloured box), which raw Tesseract reads
    /// badly. Upscale, binarise, flip to dark-glyphs-on-white if the box is dark, and pad with a
    /// white margin — measured against the real 2560x1600 capture this took the score digits
    /// from unreadable to a confident read.
    /// </summary>
    private static Image<Rgba32> PrepareNumeric(Image<Rgba32> crop)
    {
        var img = crop.Clone(ctx => ctx
            .Resize(Math.Max(1, crop.Width * 3), Math.Max(1, crop.Height * 3))
            .Grayscale()
            .Contrast(1.3f)
            .BinaryThreshold(0.5f));

        // Polarity: Tesseract wants dark text on a light background.
        long white = 0;
        img.ProcessPixelRows(accessor =>
        {
            for (var yy = 0; yy < accessor.Height; yy++)
            {
                var row = accessor.GetRowSpan(yy);
                for (var xx = 0; xx < row.Length; xx++)
                {
                    if (row[xx].R > 127) white++;
                }
            }
        });
        var total = (long)img.Width * img.Height;
        if (white * 2 < total)
        {
            img.Mutate(ctx => ctx.Invert());
        }

        // Breathing room: Tesseract misreads glyphs that touch the image border.
        img.Mutate(ctx => ctx.Pad(img.Width + 24, img.Height + 24, Color.White));
        return img;
    }

    /// <summary>
    /// Everything the calibration screen wants to show for one region: the pixel rect the
    /// normalised coordinates landed on, the raw (colour) crop as a PNG thumbnail, and what
    /// Tesseract read out of it.
    /// </summary>
    public sealed record RegionReadout(
        string Field, int X, int Y, int W, int H, string Text, int Value, double Confidence,
        byte[] CropPng);

    /// <summary>
    /// Region-by-region diagnostic read for the Settings "Test OCR" screen: reports the actual
    /// image dimensions and, per region, the resolved crop rectangle + thumbnail + OCR result.
    /// </summary>
    public (int ImageW, int ImageH, IReadOnlyList<RegionReadout> Regions) ReadDetailed(
        string imagePath, CalibrationProfile profile)
    {
        using var image = Image.Load<Rgba32>(imagePath);
        var readouts = new List<RegionReadout>();

        foreach (var region in profile.Regions)
        {
            var (x, y, w, h) = ClampedPixels(image, region, profile.Aspect);

            byte[] png;
            using (var raw = image.Clone(ctx => ctx.Crop(new Rectangle(x, y, w, h))))
            using (var ms = new MemoryStream())
            {
                raw.SaveAsPng(ms);
                png = ms.ToArray();
            }

            var (value, confidence, text) = ReadRegion(image, region, profile.Aspect);
            readouts.Add(new RegionReadout(
                region.Field, x, y, w, h, text.Trim(), value, confidence, png));
        }

        return (image.Width, image.Height, readouts);
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

    /// <summary>OCR one fractional region [x,y,w,h] of a frame as free text (video pipeline).</summary>
    public (string Text, double Confidence) ReadTextRegion(string imagePath, double[] frac)
    {
        using var image = Image.Load<Rgba32>(imagePath);
        var region = new StatRegion("adhoc", RegionKind.Text, frac[0], frac[1], frac[2], frac[3]);
        var (_, conf, text) = ReadRegion(image, region);
        return (text, conf);
    }

    /// <summary>OCR one fractional region digits-only (scoreboard / clock in the video pipeline).</summary>
    public (string Text, double Confidence) ReadDigitsRegion(string imagePath, double[] frac)
    {
        using var image = Image.Load<Rgba32>(imagePath);
        var region = new StatRegion("adhoc", RegionKind.Number, frac[0], frac[1], frac[2], frac[3]);
        var (_, conf, text) = ReadRegion(image, region);
        return (new string(text.Where(char.IsDigit).ToArray()), conf);
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
