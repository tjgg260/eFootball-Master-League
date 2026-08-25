using System;
using System.Threading.Tasks;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// One OCR'd F12 capture. <paramref name="Ok"/> says whether a score was actually READ — every
/// capture used to arrive at the dashboard as a result, so a screenshot of the squad screen (or
/// an OCR that failed outright) read as 0-0 and took the screen over. Consumers must check it.
/// </summary>
public sealed record CaptureResult(
    bool Ok, int Home, int Away, bool Confident, string Path, DateTime Time, string Message);

/// <summary>
/// The hands-off half of the core loop: watches Steam's eFootball screenshot folder while a
/// career is open, and every new F12 capture is OCR'd (score regions from Settings) and pushed
/// at the current Dashboard as a pre-filled pending result. This is the first (and only) caller
/// of ML.Ingest.ScreenshotWatcher — it existed for two phases with nobody listening.
/// </summary>
public sealed class CaptureService : IDisposable
{
    public static CaptureService Instance { get; } = new();

    private readonly object _gate = new();
    private ScreenshotWatcher? _watcher;
    private string? _watchedDir;
    private string? _lastPath;
    private DateTime _lastAt = DateTime.MinValue;

    /// <summary>
    /// The current consumer (the newest DashboardViewModel — pages rebuild on every navigation,
    /// so this is a single replaceable slot, not a multicast event, to avoid stale subscribers).
    /// Raised on a worker thread; the consumer dispatches to the UI itself.
    /// </summary>
    public Action<CaptureResult>? OnCaptured { get; set; }

    private CaptureResult? _latest;
    private bool _latestConsumed = true;

    /// <summary>
    /// Start (or re-point) the watcher. Idempotent and cheap, so the dashboard calls it every
    /// time it loads — which also means a Steam path changed in Settings takes effect the next
    /// time you land on the Office.
    /// </summary>
    public void Start()
    {
        lock (_gate)
        {
            string dir;
            try
            {
                dir = ScoreImport.ResolveScreenshotDir();
            }
            catch
            {
                return;
            }

            if (_watcher is not null &&
                string.Equals(dir, _watchedDir, StringComparison.OrdinalIgnoreCase))
            {
                return;   // already watching the right folder
            }

            _watcher?.Dispose();
            _watcher = null;
            _watchedDir = null;
            try
            {
                var watcher = new ScreenshotWatcher(dir);
                watcher.ScreenshotAdded += OnScreenshotAdded;
                watcher.Start();
                _watcher = watcher;
                _watchedDir = dir;
            }
            catch (Exception ex)
            {
                // A missing/uncreatable folder (Steam not installed here) must never crash the app.
                Program.Log("CaptureService.Start", ex);
            }
        }
    }

    /// <summary>The folder currently being watched, for the Settings screen's status line.</summary>
    public string? WatchedDir
    {
        get { lock (_gate) return _watchedDir; }
    }

    private void OnScreenshotAdded(object? sender, string path)
    {
        lock (_gate)
        {
            // Debounce: FileSystemWatcher likes to double-fire Created, and Steam touches the
            // file more than once while flushing. One capture per file per few seconds.
            var now = DateTime.UtcNow;
            if (string.Equals(path, _lastPath, StringComparison.OrdinalIgnoreCase) &&
                now - _lastAt < TimeSpan.FromSeconds(4))
            {
                return;
            }
            _lastPath = path;
            _lastAt = now;
        }

        Task.Run(() => Process(path));
    }

    private void Process(string path)
    {
        try
        {
            var read = ScoreImport.FromScreenshot(path);
            var result = new CaptureResult(
                read.Ok, read.Home, read.Away, read.Confident, path, DateTime.Now, read.Message);

            Action<CaptureResult>? sink;
            lock (_gate)
            {
                sink = OnCaptured;
                // Only a capture that actually carries a score is worth HOLDING: queueing a
                // failed read would ambush the next dashboard with a stale "that wasn't the
                // full-time screen" the moment it opened. Failures still go to a live listener,
                // which reports them quietly and changes nothing.
                if (read.Ok)
                {
                    _latest = result;
                    _latestConsumed = sink is not null;   // no dashboard? hold it for the next one
                }
            }
            sink?.Invoke(result);
        }
        catch (Exception ex)
        {
            Program.Log("CaptureService.Process", ex);
        }
    }

    /// <summary>
    /// A capture that arrived while no dashboard was listening (user was on another screen).
    /// The next dashboard drains it once so the result still lands.
    /// </summary>
    public CaptureResult? TakePending()
    {
        lock (_gate)
        {
            if (_latest is null || _latestConsumed) return null;
            _latestConsumed = true;
            return _latest;
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _watcher?.Dispose();
            _watcher = null;
            _watchedDir = null;
        }
    }
}
