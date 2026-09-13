using System.IO;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// Watches the stats host's ml_stats folder for the whole app lifetime and hands each finished
/// match file to whoever owns the dashboard. A match that finishes while the manager is on another
/// screen is kept as pending and delivered when the dashboard next attaches.
///
/// The folder only exists once the host has exported a match on this install, so a missing folder
/// is re-checked every <see cref="RetryInterval"/> rather than created — it lives under Program
/// Files, and the host makes it itself.
/// </summary>
public sealed class MatchExportService : IDisposable
{
    public static MatchExportService Instance { get; } = new();

    private static readonly TimeSpan RetryInterval = TimeSpan.FromSeconds(15);

    private readonly object _gate = new();
    private MatchExportWatcher? _watcher;
    private Timer? _retry;
    private string? _pending;
    private Action<string>? _onExport;

    /// <summary>The folder being watched (or waited for).</summary>
    public string? ExportDir { get; private set; }

    public bool Watching => _watcher is not null;

    /// <summary>Receives the path of each new match file, on a worker thread.</summary>
    public Action<string>? OnExport
    {
        get => _onExport;
        set { lock (_gate) _onExport = value; }
    }

    /// <summary>Watch <paramref name="exportDir"/>; calling again with another folder moves the watch.</summary>
    public void Start(string exportDir)
    {
        lock (_gate)
        {
            if (string.Equals(ExportDir, exportDir, StringComparison.OrdinalIgnoreCase) && (Watching || _retry is not null))
                return;
            StopLocked();
            ExportDir = exportDir;
            if (!TryAttachLocked())
                _retry = new Timer(_ => { lock (_gate) if (TryAttachLocked()) { _retry?.Dispose(); _retry = null; } },
                                   null, RetryInterval, RetryInterval);
        }
    }

    /// <summary>A match file that arrived with nobody listening, once.</summary>
    public string? TakePending()
    {
        lock (_gate)
        {
            var p = _pending;
            _pending = null;
            return p;
        }
    }

    private bool TryAttachLocked()
    {
        if (_watcher is not null) return true;
        if (ExportDir is null || !Directory.Exists(ExportDir)) return false;
        try
        {
            var watcher = new MatchExportWatcher(ExportDir);
            watcher.ExportReady += (_, path) => Deliver(path);
            watcher.Start();
            _watcher = watcher;
            return true;
        }
        catch (Exception ex)
        {
            Program.Log("MatchExportService.Attach", ex);
            return false;
        }
    }

    private void Deliver(string path)
    {
        Action<string>? handler;
        lock (_gate)
        {
            handler = _onExport;
            if (handler is null) _pending = path;
        }
        handler?.Invoke(path);
    }

    private void StopLocked()
    {
        _retry?.Dispose();
        _retry = null;
        _watcher?.Dispose();
        _watcher = null;
    }

    public void Dispose()
    {
        lock (_gate) StopLocked();
    }
}
