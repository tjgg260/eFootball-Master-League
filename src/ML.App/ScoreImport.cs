using System;
using System.IO;
using System.Linq;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// Reads the score off your latest eFootball screenshot (F12 saves one to Steam's folder) with the
/// existing Tesseract OCR + 1080p calibration, so results import instead of being typed. Low OCR
/// confidence is surfaced so you can eyeball the digits before recording.
/// </summary>
public static class ScoreImport
{
    private const string EFootballAppId = "1665460";

    // Defaults from the recorded environment; overridable via meta (Settings screen) and
    // auto-discovered when neither matches this machine (P0 — these were hardcoded).
    public static string SteamRoot { get; set; } = @"C:\Program Files (x86)\Steam";
    public static string SteamUserId { get; set; } = "1253972527";

    /// <summary>
    /// The screenshot folder: configured values first, then auto-discovery — any user id under
    /// Steam userdata that has an eFootball screenshot folder wins.
    /// </summary>
    private static string ScreenshotDir()
    {
        var configured = ScreenshotWatcher.SteamScreenshotDir(SteamRoot, SteamUserId, EFootballAppId);
        if (Directory.Exists(configured)) return configured;
        foreach (var root in new[] { SteamRoot, @"C:\Program Files (x86)\Steam", @"C:\Program Files\Steam" })
        {
            var userdata = Path.Combine(root, "userdata");
            if (!Directory.Exists(userdata)) continue;
            foreach (var user in Directory.GetDirectories(userdata))
            {
                var candidate = Path.Combine(user, "760", "remote", EFootballAppId, "screenshots");
                if (Directory.Exists(candidate)) return candidate;
            }
        }
        return configured;   // let the caller report "no folder yet"
    }

    public static (int Home, int Away, bool Confident, string Message)? FromLatestScreenshot()
    {
        try
        {
            var dir = ScreenshotDir();
            if (!Directory.Exists(dir))
            {
                return (0, 0, false, "No screenshot folder yet — press F12 in eFootball on the result screen.");
            }
            var latest = new DirectoryInfo(dir).GetFiles("*.png")
                .OrderByDescending(f => f.LastWriteTime).FirstOrDefault();
            if (latest is null)
            {
                return (0, 0, false, "No screenshots found — press F12 on the full-time screen.");
            }

            var tessdata = FindTessdata();
            if (tessdata is null)
            {
                return (0, 0, false, "OCR model (tools/tessdata) not found.");
            }

            using var ocr = new StatOcr(tessdata);
            var stats = ocr.Read(latest.FullName, CalibrationProfile.Default1080p());
            var confident = stats.HomeScore.IsConfident() && stats.AwayScore.IsConfident();
            var msg = $"Read {latest.Name}: {stats.HomeScore.Value}–{stats.AwayScore.Value}" +
                      (confident ? " — looks clean." : " — LOW confidence, double-check the digits.");
            return (stats.HomeScore.Value, stats.AwayScore.Value, confident, msg);
        }
        catch (Exception ex)
        {
            return (0, 0, false, $"OCR failed: {ex.Message}");
        }
    }

    /// <summary>
    /// Parse the post-match STATS screen (press F12 on it) with keyword-anchored full-text OCR —
    /// no pixel calibration needed. Returns whatever rows it could read: possession and shots
    /// as (home, away) pairs.
    /// </summary>
    public static (int? PossH, int? PossA, int? ShotsH, int? ShotsA, string Message)? StatsFromLatestScreenshot()
    {
        try
        {
            var dir = ScreenshotDir();
            var latest = Directory.Exists(dir)
                ? new DirectoryInfo(dir).GetFiles("*.png").OrderByDescending(f => f.LastWriteTime).FirstOrDefault()
                : null;
            if (latest is null)
            {
                return (null, null, null, null, "No screenshot — press F12 on the match STATS screen.");
            }
            var tessdata = FindTessdata();
            if (tessdata is null) return (null, null, null, null, "OCR model not found.");

            using var ocr = new StatOcr(tessdata);
            var text = ocr.ReadFullText(latest.FullName);

            (int, int)? PairAfter(string keyword, bool percent)
            {
                var ix = text.IndexOf(keyword, StringComparison.OrdinalIgnoreCase);
                if (ix < 0) return null;
                var window = text.Substring(Math.Max(0, ix - 40), Math.Min(120, text.Length - Math.Max(0, ix - 40)));
                var nums = System.Text.RegularExpressions.Regex.Matches(window, percent ? @"(\d{1,2})\s*%" : @"\b(\d{1,2})\b")
                    .Select(m => int.Parse(m.Groups[1].Value)).ToList();
                return nums.Count >= 2 ? (nums[0], nums[1]) : null;
            }

            var poss = PairAfter("Possession", percent: true);
            var shots = PairAfter("Shots", percent: false);
            var found = new System.Collections.Generic.List<string>();
            if (poss is { } p2) found.Add($"possession {p2.Item1}%–{p2.Item2}%");
            if (shots is { } s2) found.Add($"shots {s2.Item1}–{s2.Item2}");
            var msg = found.Count > 0
                ? $"Read {latest.Name}: {string.Join(", ", found)}."
                : $"Couldn't find stat rows in {latest.Name} — is it the STATS screen?";
            return (poss?.Item1, poss?.Item2, shots?.Item1, shots?.Item2, msg);
        }
        catch (Exception ex)
        {
            return (null, null, null, null, $"Stats OCR failed: {ex.Message}");
        }
    }

    private static string? FindTessdata()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "tools", "tessdata");
            if (File.Exists(Path.Combine(candidate, "eng.traineddata"))) return candidate;
            dir = dir.Parent;
        }
        return null;
    }
}
