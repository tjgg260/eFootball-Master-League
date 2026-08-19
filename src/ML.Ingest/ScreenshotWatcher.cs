namespace ML.Ingest;

/// <summary>
/// Watches the Steam screenshot directory and raises an event for each new full-frame capture.
/// This is what makes stats import "hands-off" — the user presses F12 at full time and the app
/// picks the file up, OCRs it, and shows a pre-filled confirm screen with no file wrangling.
/// </summary>
public sealed class ScreenshotWatcher : IDisposable
{
    private readonly FileSystemWatcher _watcher;

    public event EventHandler<string>? ScreenshotAdded;

    public ScreenshotWatcher(string screenshotDir)
    {
        if (!Directory.Exists(screenshotDir))
        {
            // The folder is created by Steam on the first F12; watch the parent until it appears
            // rather than throwing, so the app can start before any screenshot exists.
            Directory.CreateDirectory(screenshotDir);
        }

        _watcher = new FileSystemWatcher(screenshotDir)
        {
            Filter = "*.jpg",
            NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite,
        };
        _watcher.Created += OnCreated;
    }

    /// <summary>The Steam screenshot path for a Steam user and app id (Phase 3 watcher target).</summary>
    public static string SteamScreenshotDir(string steamRoot, string userId, string appId) =>
        Path.Combine(steamRoot, "userdata", userId, "760", "remote", appId, "screenshots");

    public void Start() => _watcher.EnableRaisingEvents = true;

    public void Stop() => _watcher.EnableRaisingEvents = false;

    private void OnCreated(object sender, FileSystemEventArgs e)
    {
        // Steam writes the file then flushes; wait for the handle to free before OCR reads it.
        WaitForFile(e.FullPath);
        ScreenshotAdded?.Invoke(this, e.FullPath);
    }

    private static void WaitForFile(string path, int attempts = 20)
    {
        for (var i = 0; i < attempts; i++)
        {
            try
            {
                using var _ = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.None);
                return;
            }
            catch (IOException)
            {
                Thread.Sleep(100);
            }
        }
    }

    public void Dispose()
    {
        _watcher.Created -= OnCreated;
        _watcher.Dispose();
    }
}
