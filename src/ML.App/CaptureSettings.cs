using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// The OCR capture calibration: normalised score-box regions + how they map onto the screenshot
/// (native frame vs letterboxed 16:9). Persisted as build/ocr_calibration.json next to master.db
/// so it survives careers and never touches the game DB. Defaults are measured off a real
/// 2560x1600 capture from this machine; the Settings screen tunes them live.
/// </summary>
public sealed class CaptureSettings
{
    /// <summary>[x, y, w, h] normalised 0..1.</summary>
    public double[] HomeScore { get; set; } = CalibrationProfile.DefaultHomeScoreRegion.ToArray();

    public double[] AwayScore { get; set; } = CalibrationProfile.DefaultAwayScoreRegion.ToArray();

    /// <summary>"Native" (default — the game renders the full frame, 16:10 included) or "Letterbox16x9".</summary>
    public string Aspect { get; set; } = "Native";

    public AspectMode Mode =>
        string.Equals(Aspect, "Letterbox16x9", StringComparison.OrdinalIgnoreCase)
            ? AspectMode.Letterbox16x9
            : AspectMode.Native;

    public CalibrationProfile ScoreProfile() => CalibrationProfile.ScoreOnly(HomeScore, AwayScore, Mode);

    // ---------------------------------------------------------------- load / save

    private static readonly object Gate = new();
    private static CaptureSettings? _current;

    public static CaptureSettings Current
    {
        get
        {
            lock (Gate) return _current ??= Load();
        }
    }

    public void Save()
    {
        try
        {
            var path = SettingsPath(forWrite: true);
            File.WriteAllText(path, JsonSerializer.Serialize(this, new JsonSerializerOptions
            {
                WriteIndented = true,
            }));
        }
        catch { /* calibration must never take a screen down; worst case defaults return */ }
    }

    private static CaptureSettings Load()
    {
        try
        {
            var path = SettingsPath(forWrite: false);
            if (File.Exists(path))
            {
                var loaded = JsonSerializer.Deserialize<CaptureSettings>(File.ReadAllText(path));
                if (loaded is not null && IsSane(loaded.HomeScore) && IsSane(loaded.AwayScore))
                {
                    return loaded;
                }
            }
        }
        catch { /* fall through to defaults */ }
        return new CaptureSettings();
    }

    private static bool IsSane(double[]? r) =>
        r is { Length: 4 }
        && r.All(v => v is >= 0 and <= 1)
        && r[2] > 0.001 && r[3] > 0.001;

    /// <summary>
    /// build/ocr_calibration.json — found the same way CareerLoader finds master.db: walk up
    /// from the exe until a build/ directory appears (dev checkout), else use build/ under the exe.
    /// </summary>
    private static string SettingsPath(bool forWrite)
    {
        const string fileName = "ocr_calibration.json";
        var baseDir = AppContext.BaseDirectory;
        var dir = new DirectoryInfo(baseDir);
        while (dir is not null)
        {
            var build = Path.Combine(dir.FullName, "build");
            if (Directory.Exists(build)) return Path.Combine(build, fileName);
            dir = dir.Parent;
        }
        var fallback = Path.Combine(baseDir, "build");
        if (forWrite) Directory.CreateDirectory(fallback);
        return Path.Combine(fallback, fileName);
    }
}
