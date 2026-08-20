using System.IO;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// Match recording + analysis orchestration. OBS (via obs-websocket) records every played
/// match; afterwards the analyzer mines the file for goals (side + minute + scorer banner)
/// and the full-time stats screen. Everything is best-effort and settings-driven:
/// no OBS = no recording, no ffmpeg = no analysis, and the matchday never blocks.
/// </summary>
public static class VideoCapture
{
    public static bool RecordMatches { get; set; }
    public static string ObsUrl { get; set; } = "ws://127.0.0.1:4455";
    public static string ObsPassword { get; set; } = "";
    public static string FfmpegPath { get; set; } = "ffmpeg";
    public static string VideoDir { get; set; } = "";

    private static string RegionsPath =>
        Path.Combine(MatchLauncher.FindRepoRoot() ?? ".", "build", "video_regions.json");

    private static string TessdataPath =>
        Path.Combine(MatchLauncher.FindRepoRoot() ?? ".", "tools", "tessdata");

    /// <summary>Ask OBS to start recording. One line of feedback either way.</summary>
    public static async Task StartAsync(Action<string> log)
    {
        if (!RecordMatches) return;
        await using var obs = new ObsRecorder(ObsUrl, ObsPassword);
        if (!await obs.ConnectAsync())
        {
            log("🎞 OBS not reachable — match will not be recorded (Settings → Match video).");
            return;
        }
        log(await obs.StartRecordingAsync()
            ? "🎞 OBS recording started."
            : "🎞 OBS connected but refused to record (already recording?).");
    }

    /// <summary>Stop the recording (called when you come back to enter the result).</summary>
    public static async Task<string?> StopAsync(Action<string> log)
    {
        if (!RecordMatches) return null;
        await using var obs = new ObsRecorder(ObsUrl, ObsPassword);
        if (!await obs.ConnectAsync()) return null;
        var path = await obs.StopRecordingAsync();
        if (path is not null) log($"🎞 Recording saved: {Path.GetFileName(path)}");
        return path;
    }

    /// <summary>The newest recording in the video folder — the match you just played.</summary>
    public static string? NewestRecording()
    {
        var dir = string.IsNullOrWhiteSpace(VideoDir)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyVideos))
            : VideoDir;
        if (!Directory.Exists(dir)) return null;
        return Directory.GetFiles(dir)
            .Where(f => f.EndsWith(".mkv") || f.EndsWith(".mp4") || f.EndsWith(".mov"))
            .OrderByDescending(File.GetLastWriteTimeUtc)
            .FirstOrDefault();
    }

    /// <summary>
    /// Mine the newest recording: goal events (side/minute/banner text) ready for the event
    /// pickers, and the stats screen if one is seen near the end. Runs off the UI thread.
    /// </summary>
    public static Task<IReadOnlyList<VideoEvent>> AnalyzeAsync(string videoPath, Action<string> log) =>
        Task.Run<IReadOnlyList<VideoEvent>>(() =>
        {
            var regions = VideoRegions.Load(RegionsPath);
            var work = Path.Combine(MatchLauncher.FindRepoRoot() ?? ".", "build", "video_work");
            using var analyzer = new VideoAnalyzer(FfmpegPath, TessdataPath, regions, work);
            if (!analyzer.FfmpegAvailable())
            {
                log("ffmpeg not found — install it (winget install ffmpeg) or set its path in Settings.");
                return Array.Empty<VideoEvent>();
            }
            if (!regions.Calibrated)
            {
                log("⚠ Scoreboard regions are UNCALIBRATED — using 16:9 defaults. If results look " +
                    "wrong, calibrate once against a frame (docs/video-capture.md).");
            }
            return analyzer.DetectGoals(videoPath, log);
        });

    /// <summary>
    /// Parse the full-time STATS screen text (whole-screen OCR) into (stat, home, away) rows.
    /// Keyword-anchored: works from a screenshot without any region calibration.
    /// </summary>
    public static IReadOnlyList<(string Stat, int Home, int Away)> ParseStatsScreen(string imagePath)
    {
        using var ocr = new StatOcr(TessdataPath);
        var text = ocr.ReadFullText(imagePath);
        var rows = new List<(string, int, int)>();
        // The screen reads "62% Possession 38%" / "12 Shots 7" — number, label, number.
        var line = new Regex(@"^\s*(\d+)\s*%?\s+([A-Za-z][A-Za-z \-']+?)\s+(\d+)\s*%?\s*$");
        foreach (var raw in text.Split('\n'))
        {
            var m = line.Match(raw);
            if (!m.Success) continue;
            var stat = m.Groups[2].Value.Trim().ToLowerInvariant().Replace(' ', '_');
            if (stat.Length < 4) continue;
            rows.Add((stat, int.Parse(m.Groups[1].Value), int.Parse(m.Groups[3].Value)));
        }
        return rows;
    }
}
