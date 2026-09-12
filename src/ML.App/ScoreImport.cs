using System;
using System.IO;
using System.Linq;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// One attempt at reading a score off a screenshot. <see cref="Ok"/> is the ONLY success signal.
///
/// THE BUG this type exists to kill: every failure path used to return a
/// <c>(0, 0, false, message)</c> tuple from a method typed as nullable, so the callers' natural
/// `if (r is null)` guard could never fire — a screenshot folder that didn't exist, a missing OCR
/// model, a menu screenshot, an exception, all of them arrived at the dashboard looking exactly
/// like a genuine 0-0 and silently overwrote the score you had typed. The return type is
/// deliberately NOT nullable now: there is no second "null means failure" channel left to forget.
/// </summary>
public sealed record ScoreRead(bool Ok, int Home, int Away, bool Confident, string Message)
{
    /// <summary>No score was read. The boxes must not be touched; the reason gets shown.</summary>
    public static ScoreRead Failed(string message) => new(false, 0, 0, false, message);
}

/// <summary>
/// Reads the score off your latest eFootball screenshot (F12 saves one to Steam's folder) with the
/// existing Tesseract OCR + 1080p calibration, so results import instead of being typed. Low OCR
/// confidence is surfaced so you can eyeball the digits before recording.
/// </summary>
public static class ScoreImport
{
    /// <summary>Same threshold <see cref="OcrValue{T}.IsConfident"/> uses.</summary>
    private const double ConfidenceFloor = 0.80;

    /// <summary>Above this in either box the crop caught something that is not a scoreline
    /// (matches the entry stepper's Maximum, so an "imported" score can always be recorded).</summary>
    private const int MaxPlausibleGoals = 20;

    /// <summary>
    /// Closest of <paramref name="candidates"/> to OCR'd <paramref name="text"/> (video banner
    /// pipeline). 22 known names make even scrappy OCR reliable; null when nothing is close.
    /// </summary>
    public static string? BestNameMatch(string text, IEnumerable<string> candidates)
    {
        var t = new string(text.ToLowerInvariant().Where(char.IsLetter).ToArray());
        if (t.Length < 3) return null;
        string? best = null;
        var bestScore = 0.0;
        foreach (var cand in candidates)
        {
            var c = new string(cand.ToLowerInvariant().Where(char.IsLetter).ToArray());
            if (c.Length < 3) continue;
            // Containment first (banner often shows SURNAME only), else edit distance.
            double score;
            if (t.Contains(c) || c.Contains(t))
            {
                score = 0.9;
            }
            else
            {
                var d = Levenshtein(t, c);
                score = 1.0 - d / (double)Math.Max(t.Length, c.Length);
            }
            if (score > bestScore) (best, bestScore) = (cand, score);
        }
        return bestScore >= 0.62 ? best : null;
    }

    private static int Levenshtein(string a, string b)
    {
        var d = new int[a.Length + 1, b.Length + 1];
        for (var i = 0; i <= a.Length; i++) d[i, 0] = i;
        for (var j = 0; j <= b.Length; j++) d[0, j] = j;
        for (var i = 1; i <= a.Length; i++)
        for (var j = 1; j <= b.Length; j++)
        {
            d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1),
                d[i - 1, j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1));
        }
        return d[a.Length, b.Length];
    }

    private const string EFootballAppId = "1665460";

    // Defaults from the recorded environment; overridable via meta (Settings screen) and
    // auto-discovered when neither matches this machine (P0 — these were hardcoded).
    public static string SteamRoot { get; set; } = @"C:\Program Files (x86)\Steam";
    public static string SteamUserId { get; set; } = "1253972527";

    /// <summary>
    /// The screenshot folder: configured values first, then auto-discovery — any user id under
    /// Steam userdata that has an eFootball screenshot folder wins. Public so the capture
    /// watcher (CaptureService) points at the same folder the import buttons read.
    /// </summary>
    public static string ResolveScreenshotDir()
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

    /// <summary>
    /// The newest screenshot in <paramref name="dir"/>. Steam writes .jpg (F12 default) — the
    /// old "*.png" glob matched NOTHING on a stock install. Top-level only, so Steam's
    /// thumbnails/ subfolder never wins.
    /// </summary>
    internal static FileInfo? LatestScreenshot(string? dir = null)
    {
        dir ??= ResolveScreenshotDir();
        if (!Directory.Exists(dir)) return null;
        return new DirectoryInfo(dir)
            .EnumerateFiles("*", SearchOption.TopDirectoryOnly)
            .Where(f => f.Extension.ToLowerInvariant() is ".jpg" or ".jpeg" or ".png")
            .OrderByDescending(f => f.LastWriteTime)
            .FirstOrDefault();
    }

    internal static string? TessdataDir() => FindTessdata();

    public static ScoreRead FromLatestScreenshot()
    {
        try
        {
            var dir = ResolveScreenshotDir();
            if (!Directory.Exists(dir))
            {
                return ScoreRead.Failed(
                    "No screenshot folder yet — press F12 in eFootball on the result screen.");
            }
            var latest = LatestScreenshot(dir);
            if (latest is null)
            {
                return ScoreRead.Failed("No screenshots found — press F12 on the full-time screen.");
            }
            return FromScreenshot(latest.FullName);
        }
        catch (Exception ex)
        {
            return ScoreRead.Failed($"OCR failed: {ex.Message}");
        }
    }

    /// <summary>
    /// OCR the score off ONE specific screenshot (the watcher hands each new F12 capture here).
    /// Uses the calibrated score regions from Settings, applied to the file's actual dimensions.
    /// </summary>
    public static ScoreRead FromScreenshot(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return ScoreRead.Failed($"Screenshot not found: {Path.GetFileName(path)}");
            }

            var tessdata = FindTessdata();
            if (tessdata is null)
            {
                return ScoreRead.Failed(
                    "OCR model not found — tools/tessdata/eng.traineddata is missing.");
            }

            var name = Path.GetFileName(path);
            using var ocr = new StatOcr(tessdata);

            // ReadDetailed, not Read: StatOcr.ParseNumber returns 0 both for a genuine "0" and for
            // a crop with no digits in it at all, so Read()'s ints CANNOT tell a real 0-0 full-time
            // screen from a screenshot of the main menu. Only the raw OCR text can, and
            // ReadDetailed is the one public call that hands it back. Without this every F12 —
            // a squad screen, a replay, a pause menu — came back as a confident-looking 0-0.
            var (_, _, regions) = ocr.ReadDetailed(path, CaptureSettings.Current.ScoreProfile());
            var home = regions.FirstOrDefault(r => r.Field == "home_score");
            var away = regions.FirstOrDefault(r => r.Field == "away_score");
            if (home is null || away is null
                || !home.Text.Any(char.IsDigit) || !away.Text.Any(char.IsDigit))
            {
                return ScoreRead.Failed(
                    $"No score in {name} — that doesn't look like the full-time screen. " +
                    "Press F12 on it, or re-calibrate the score boxes in Settings.");
            }
            if (home.Value > MaxPlausibleGoals || away.Value > MaxPlausibleGoals)
            {
                return ScoreRead.Failed(
                    $"Read \"{home.Text}\"–\"{away.Text}\" from {name}, which isn't a scoreline — " +
                    "nothing was filled in. Re-calibrate the score boxes in Settings.");
            }

            var confident = home.Confidence >= ConfidenceFloor && away.Confidence >= ConfidenceFloor;
            var msg = $"Read {name}: {home.Value}–{away.Value}" +
                      (confident ? " — looks clean." : " — LOW confidence, double-check the digits.");
            return new ScoreRead(true, home.Value, away.Value, confident, msg);
        }
        catch (Exception ex)
        {
            return ScoreRead.Failed($"OCR failed: {ex.Message}");
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
            var latest = LatestScreenshot();
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
