using System.IO;
using System.Threading.Tasks;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Ingest;

namespace ML.App.ViewModels;

// --- Settings: OCR calibration (score regions, aspect mapping, Test OCR) ----------------------
//
// The one manual pass the plan demands: load your newest F12 capture, see exactly which pixels
// the two score boxes cover (crop thumbnails), nudge the normalised x/y/w/h until the digits
// read clean — every change re-runs OCR live and persists to build/ocr_calibration.json, which
// is the profile both the 📷 Import button and the automatic capture watcher use.

public sealed partial class SettingsViewModel
{
    private const string AspectNative = "Native (full frame — correct for 16:10)";
    private const string AspectLetterbox = "Letterboxed 16:9 (bars top/bottom)";

    public IReadOnlyList<string> OcrAspectOptions { get; } = new[] { AspectNative, AspectLetterbox };

    [ObservableProperty] private string _ocrAspect =
        CaptureSettings.Current.Mode == AspectMode.Letterbox16x9 ? AspectLetterbox : AspectNative;

    // Normalised (0..1) score boxes; defaults measured off the real 2560x1600 capture.
    [ObservableProperty] private decimal? _ocrHomeX = (decimal)CaptureSettings.Current.HomeScore[0];
    [ObservableProperty] private decimal? _ocrHomeY = (decimal)CaptureSettings.Current.HomeScore[1];
    [ObservableProperty] private decimal? _ocrHomeW = (decimal)CaptureSettings.Current.HomeScore[2];
    [ObservableProperty] private decimal? _ocrHomeH = (decimal)CaptureSettings.Current.HomeScore[3];
    [ObservableProperty] private decimal? _ocrAwayX = (decimal)CaptureSettings.Current.AwayScore[0];
    [ObservableProperty] private decimal? _ocrAwayY = (decimal)CaptureSettings.Current.AwayScore[1];
    [ObservableProperty] private decimal? _ocrAwayW = (decimal)CaptureSettings.Current.AwayScore[2];
    [ObservableProperty] private decimal? _ocrAwayH = (decimal)CaptureSettings.Current.AwayScore[3];

    [ObservableProperty] private Bitmap? _ocrScreenshot;
    [ObservableProperty] private Bitmap? _ocrHomeCrop;
    [ObservableProperty] private Bitmap? _ocrAwayCrop;

    [ObservableProperty] private string _ocrResultLine =
        "🧪 Test OCR loads your newest F12 screenshot, shows the two score crops and what " +
        "Tesseract reads from them. Nudge the boxes until the digits come out right — every " +
        "change re-runs live and saves.";

    partial void OnOcrAspectChanged(string value) => OcrCalibrationChanged();
    partial void OnOcrHomeXChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrHomeYChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrHomeWChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrHomeHChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrAwayXChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrAwayYChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrAwayWChanged(decimal? value) => OcrCalibrationChanged();
    partial void OnOcrAwayHChanged(decimal? value) => OcrCalibrationChanged();

    private void OcrCalibrationChanged()
    {
        PersistOcr();
        if (_ocrTestPath is not null) _ = RunOcrTestAsync();   // live re-run against the loaded shot
    }

    private void PersistOcr()
    {
        var c = CaptureSettings.Current;
        static void Put(double[] r, decimal? x, decimal? y, decimal? w, decimal? h)
        {
            if (x is { } vx) r[0] = (double)vx;
            if (y is { } vy) r[1] = (double)vy;
            if (w is { } vw) r[2] = (double)vw;
            if (h is { } vh) r[3] = (double)vh;
        }
        Put(c.HomeScore, OcrHomeX, OcrHomeY, OcrHomeW, OcrHomeH);
        Put(c.AwayScore, OcrAwayX, OcrAwayY, OcrAwayW, OcrAwayH);
        c.Aspect = OcrAspect == AspectLetterbox ? "Letterbox16x9" : "Native";
        c.Save();
    }

    [RelayCommand]
    private void ResetOcrRegions()
    {
        var home = CalibrationProfile.DefaultHomeScoreRegion;
        var away = CalibrationProfile.DefaultAwayScoreRegion;
        (OcrHomeX, OcrHomeY, OcrHomeW, OcrHomeH) =
            ((decimal)home[0], (decimal)home[1], (decimal)home[2], (decimal)home[3]);
        (OcrAwayX, OcrAwayY, OcrAwayW, OcrAwayH) =
            ((decimal)away[0], (decimal)away[1], (decimal)away[2], (decimal)away[3]);
        OcrAspect = AspectNative;
    }

    // ---------------------------------------------------------------- test run

    private string? _ocrTestPath;
    private bool _ocrRunning;
    private bool _ocrQueued;

    [RelayCommand]
    private async Task TestOcr()
    {
        // Apply any unsaved Steam path edits so the test looks where the user is pointing.
        ScoreImport.SteamRoot = SteamRoot.Trim();
        ScoreImport.SteamUserId = SteamUserId.Trim();

        var latest = ScoreImport.LatestScreenshot();
        if (latest is null)
        {
            OcrResultLine = $"No screenshot found in {ScoreImport.ResolveScreenshotDir()} — " +
                            "press F12 in eFootball on the full-time screen first.";
            return;
        }
        _ocrTestPath = latest.FullName;
        await RunOcrTestAsync();
    }

    private async Task RunOcrTestAsync()
    {
        if (_ocrTestPath is null) return;
        if (_ocrRunning) { _ocrQueued = true; return; }
        _ocrRunning = true;
        try
        {
            do
            {
                _ocrQueued = false;
                var path = _ocrTestPath;
                var profile = CaptureSettings.Current.ScoreProfile();
                var result = await Task.Run(() =>
                {
                    var tessdata = ScoreImport.TessdataDir()
                        ?? throw new InvalidOperationException("OCR model (tools/tessdata) not found.");
                    using var ocr = new StatOcr(tessdata);
                    return ocr.ReadDetailed(path, profile);
                });
                ApplyOcrTest(path, result);
            }
            while (_ocrQueued);
        }
        catch (Exception ex)
        {
            OcrResultLine = $"Test OCR failed: {ex.Message}";
        }
        finally
        {
            _ocrRunning = false;
        }
    }

    private void ApplyOcrTest(
        string path, (int ImageW, int ImageH, IReadOnlyList<StatOcr.RegionReadout> Regions) r)
    {
        try
        {
            using var fs = File.OpenRead(path);
            OcrScreenshot = Bitmap.DecodeToWidth(fs, 640);
        }
        catch { OcrScreenshot = null; }

        var home = r.Regions.FirstOrDefault(x => x.Field == "home_score");
        var away = r.Regions.FirstOrDefault(x => x.Field == "away_score");
        OcrHomeCrop = home is null ? null : new Bitmap(new MemoryStream(home.CropPng));
        OcrAwayCrop = away is null ? null : new Bitmap(new MemoryStream(away.CropPng));

        string Line(string side, StatOcr.RegionReadout? x) => x is null
            ? $"{side}: (no region)"
            : $"{side}: crop px [{x.X},{x.Y}  {x.W}x{x.H}] read \"{x.Text}\" → {x.Value}  " +
              $"({x.Confidence:P0} conf)";

        var aspect = CaptureSettings.Current.Mode == AspectMode.Letterbox16x9
            ? "letterboxed 16:9 mapping"
            : "native mapping";
        OcrResultLine =
            $"{Path.GetFileName(path)} — {r.ImageW}x{r.ImageH}, {aspect}\n" +
            Line("HOME", home) + "\n" + Line("AWAY", away) + "\n" +
            $"Score as imported: {home?.Value ?? 0}–{away?.Value ?? 0}";
    }
}
