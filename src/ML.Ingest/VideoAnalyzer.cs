using System.Diagnostics;
using System.Text.Json;

namespace ML.Ingest;

/// <summary>One detected in-match event, with the frame time it was seen at.</summary>
public sealed record VideoEvent(
    double VideoSeconds, string Kind, string Side, int Minute, string PlayerText, double Confidence);

/// <summary>Where the in-match overlays live, as fractions of the frame (resolution-independent).</summary>
public sealed class VideoRegions
{
    // Sensible 16:9 defaults for eFootball's top-left scoreboard; REPLACED by calibration
    // against a real recording (tools: AnalyzeVideo calibrate).
    public double[] HomeScore { get; set; } = { 0.115, 0.045, 0.022, 0.038 };
    public double[] AwayScore { get; set; } = { 0.175, 0.045, 0.022, 0.038 };
    public double[] Clock { get; set; } = { 0.045, 0.045, 0.055, 0.038 };
    public double[] GoalBanner { get; set; } = { 0.25, 0.78, 0.50, 0.10 };
    public bool Calibrated { get; set; }

    public static VideoRegions Load(string path) =>
        File.Exists(path)
            ? JsonSerializer.Deserialize<VideoRegions>(File.ReadAllText(path)) ?? new VideoRegions()
            : new VideoRegions();

    public void Save(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(
            this, new JsonSerializerOptions { WriteIndented = true }));
    }
}

/// <summary>
/// Mines a match recording for events the game shows but never stores: samples the scoreboard
/// strip at 1 fps via ffmpeg, OCRs score + clock in isolation, and turns score CHANGES into
/// goal events (side + minute). Around each change it OCRs the goal-banner region for the
/// scorer's name, which the caller fuzzy-matches against the 22 players it already knows.
/// The full-time stats screen goes through the existing <see cref="StatOcr"/> calibration.
/// </summary>
public sealed class VideoAnalyzer : IDisposable
{
    private readonly string _ffmpeg;
    private readonly StatOcr _ocr;
    private readonly VideoRegions _regions;
    private readonly string _workDir;

    public VideoAnalyzer(string ffmpegPath, string tessdataPath, VideoRegions regions, string workDir)
    {
        _ffmpeg = string.IsNullOrWhiteSpace(ffmpegPath) ? "ffmpeg" : ffmpegPath;
        _ocr = new StatOcr(tessdataPath);
        _regions = regions;
        _workDir = workDir;
    }

    public bool FfmpegAvailable()
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo(_ffmpeg, "-version")
            { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, CreateNoWindow = true });
            p!.WaitForExit(4000);
            return p.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>Dump a single frame as PNG — the calibration workflow marks regions on it.</summary>
    public string? ExtractFrame(string videoPath, double seconds, string outPng)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(outPng)!);
        return Run($"-ss {seconds:0.###} -i \"{videoPath}\" -frames:v 1 -y \"{outPng}\"") == 0
            && File.Exists(outPng) ? outPng : null;
    }

    /// <summary>
    /// The main pass. Samples one frame per <paramref name="stepSeconds"/>, reads the score
    /// pair, and reports each score change as a goal with the clock minute and any banner text
    /// seen near the change. Progress lines go to <paramref name="log"/>.
    /// </summary>
    public IReadOnlyList<VideoEvent> DetectGoals(
        string videoPath, Action<string> log, double stepSeconds = 2.0)
    {
        var frames = Path.Combine(_workDir, "frames");
        if (Directory.Exists(frames)) Directory.Delete(frames, recursive: true);
        Directory.CreateDirectory(frames);

        log($"sampling {Path.GetFileName(videoPath)} every {stepSeconds:0.#}s…");
        if (Run($"-i \"{videoPath}\" -vf fps=1/{stepSeconds:0.###} -y \"{Path.Combine(frames, "f%05d.png")}\"") != 0)
        {
            log("ffmpeg sampling failed — is the path right and ffmpeg installed?");
            return Array.Empty<VideoEvent>();
        }

        var files = Directory.GetFiles(frames, "f*.png").OrderBy(f => f).ToList();
        log($"{files.Count} frames; reading the scoreboard strip…");
        var events = new List<VideoEvent>();
        var (prevH, prevA) = (0, 0);
        var seenScoreboard = false;
        for (var i = 0; i < files.Count; i++)
        {
            var t = i * stepSeconds;
            var (h, a, minute, okH, okA) = ReadScoreboard(files[i]);
            if (!okH || !okA)
            {
                continue;   // menus, replays, cutscenes — no scoreboard, no signal
            }
            if (!seenScoreboard)
            {
                seenScoreboard = true;
                (prevH, prevA) = (h, a);   // first sighting sets the baseline (usually 0-0)
                continue;
            }
            // A score can only step by one; anything else is an OCR misread — ignore it.
            if (h == prevH + 1 && a == prevA)
            {
                events.Add(MakeGoal(videoPath, t, "home", minute));
            }
            else if (a == prevA + 1 && h == prevH)
            {
                events.Add(MakeGoal(videoPath, t, "away", minute));
            }
            if (Math.Abs(h - prevH) <= 1 && Math.Abs(a - prevA) <= 1)
            {
                (prevH, prevA) = (h, a);
            }
        }
        log($"{events.Count} goal(s) detected.");
        return events;
    }

    private VideoEvent MakeGoal(string videoPath, double t, string side, int minute)
    {
        // The scorer banner shows within a few seconds of the score ticking over —
        // OCR the banner region on a handful of frames just after the change.
        var name = "";
        var conf = 0.0;
        for (var dt = 0.5; dt <= 6.5; dt += 1.5)
        {
            var png = Path.Combine(_workDir, "banner.png");
            if (ExtractFrame(videoPath, t + dt, png) is null) continue;
            var (text, c) = _ocr.ReadTextRegion(png, _regions.GoalBanner);
            if (c > conf && text.Trim().Length >= 3)
            {
                (name, conf) = (text.Trim(), c);
            }
        }
        return new VideoEvent(t, "goal", side, minute, name, conf);
    }

    private (int Home, int Away, int Minute, bool OkH, bool OkA) ReadScoreboard(string framePng)
    {
        var (hT, hC) = _ocr.ReadDigitsRegion(framePng, _regions.HomeScore);
        var (aT, aC) = _ocr.ReadDigitsRegion(framePng, _regions.AwayScore);
        var (mT, _) = _ocr.ReadDigitsRegion(framePng, _regions.Clock);
        var okH = hC > 0.45 && int.TryParse(hT, out var h);
        var okA = aC > 0.45 && int.TryParse(aT, out var a);
        int.TryParse(hT, out var hv);
        int.TryParse(aT, out var av);
        var minute = int.TryParse(new string(mT.TakeWhile(char.IsDigit).ToArray()), out var m)
            ? Math.Clamp(m, 0, 130) : 0;
        return (hv, av, minute, okH, okA);
    }

    private int Run(string args)
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo(_ffmpeg, args)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            });
            p!.StandardOutput.ReadToEnd();
            p.StandardError.ReadToEnd();
            p.WaitForExit();
            return p.ExitCode;
        }
        catch
        {
            return -1;
        }
    }

    public void Dispose() => _ocr.Dispose();
}
