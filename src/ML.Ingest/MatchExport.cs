using System.Text.Json;
using System.Text.Json.Serialization;

namespace ML.Ingest;

/// <summary>
/// One match as written by efootball-re's stats host (schema <c>efootball-re/match-stats/1</c>).
///
/// The host is injected into the running game and hooks the engine's own stat counters, so this is
/// the match the game actually played: per-player actions keyed by the dt200 PID, substitutions,
/// attributes. It writes <c>&lt;eFootball&gt;\ml_stats\match_&lt;kick-off&gt;.json</c> atomically
/// (tmp + rename) once the match is finalised — back at the main menu, at the next kick-off, or
/// on the next game start. Only the fields the league uses are bound here; the rest are documented
/// in tools/vendor/efootball-re/mlstats/README.md.
/// </summary>
public sealed class MatchExport
{
    public const string SchemaName = "efootball-re/match-stats/1";

    [JsonPropertyName("schema")] public string Schema { get; init; } = "";
    [JsonPropertyName("final")] public bool Final { get; init; }
    [JsonPropertyName("final_reason")] public string? FinalReason { get; init; }
    [JsonPropertyName("file_stem")] public string? FileStem { get; init; }
    [JsonPropertyName("first_seen")] public DateTimeOffset? FirstSeen { get; init; }
    [JsonPropertyName("snapshot_at")] public DateTimeOffset? SnapshotAt { get; init; }
    [JsonPropertyName("teams")] public List<ExportTeam> Teams { get; init; } = new();

    /// <summary>The file this export was loaded from, when it came from disk.</summary>
    [JsonIgnore] public string? SourcePath { get; private set; }

    /// <summary>
    /// The export exactly as the host wrote it. Only the fields the league computes with are bound
    /// above; the rest (segments, form, raw counters, labels, caveats) live here so the league can
    /// keep the whole match against its fixture and the Match Report can show all of it.
    /// </summary>
    [JsonIgnore] public string RawJson { get; private set; } = "";

    /// <summary>The kick-off stamp that names the file (<c>match_20260913_215134</c>).</summary>
    [JsonIgnore] public string Stem => FileStem ?? Path.GetFileNameWithoutExtension(SourcePath ?? "");

    public static MatchExport Parse(string json)
    {
        var export = JsonSerializer.Deserialize<MatchExport>(json)
                     ?? throw new FormatException("empty match export");
        export.RawJson = json;
        if (export.Schema != SchemaName)
            throw new FormatException($"unknown match export schema '{export.Schema}' (expected {SchemaName})");
        if (export.Teams.Count != 2)
            throw new FormatException($"a match export has two teams, this one has {export.Teams.Count}");
        return export;
    }

    public static MatchExport Load(string path)
    {
        var export = Parse(File.ReadAllText(path));
        export.SourcePath = path;
        return export;
    }
}

public sealed class ExportTeam
{
    /// <summary>"home" or "away", as the game ran the match.</summary>
    [JsonPropertyName("side")] public string Side { get; init; } = "";

    /// <summary>The named counters summed over the team (shots, passes, goals, …).</summary>
    [JsonPropertyName("totals")] public Dictionary<string, long> Totals { get; init; } = new();

    /// <summary>Every non-zero counter by engine id (<c>"0x4B"</c> is possession time).</summary>
    [JsonPropertyName("raw_totals")] public Dictionary<string, long> RawTotals { get; init; } = new();

    [JsonPropertyName("players")] public List<ExportPlayer> Players { get; init; } = new();

    public long Total(string key) => Totals.GetValueOrDefault(key);

    /// <summary>A counter by engine id (<c>"0x3E"</c>), named by the host or not; 0 when it did not move.</summary>
    public long Raw(string id) => ExportCounters.TryLookup(RawTotals, id, out var v) ? v : 0;
}

public sealed class ExportPlayer
{
    /// <summary>Roster slot: 0-10 started, 11+ came off the bench.</summary>
    [JsonPropertyName("slot")] public int Slot { get; init; }

    /// <summary>The dt200 PID (64-bit). Missing in exports written before the host learnt it.</summary>
    [JsonPropertyName("player_id")] public ulong? PlayerId { get; init; }

    [JsonPropertyName("shirt_number")] public int? ShirtNumber { get; init; }
    [JsonPropertyName("shirt_name")] public string? ShirtName { get; init; }

    /// <summary>Position in the on-pitch lineup; null for a player who was substituted off.</summary>
    [JsonPropertyName("lineup_index")] public int? LineupIndex { get; init; }

    [JsonPropertyName("actions")] public Dictionary<string, int> Actions { get; init; } = new();

    /// <summary>Per-id counters split into 9 segments; the first 8 sum to the match total.</summary>
    [JsonPropertyName("raw_segments")] public Dictionary<string, long[]>? RawSegments { get; init; }

    /// <summary>61-byte attribute array: 20-46 abilities, 49 age, 50 height.</summary>
    [JsonPropertyName("attributes_base")] public int[]? AttributesBase { get; init; }

    [JsonPropertyName("attributes_form")] public int[]? AttributesForm { get; init; }

    public int Action(string key) => Actions.GetValueOrDefault(key);

    /// <summary>
    /// A counter by engine id, named by the host or not: the sum of the first 8 of its 9 segments,
    /// which is the host's match total (the 9th is not part of it). 0 when it did not move.
    /// </summary>
    public long Raw(string id) =>
        ExportCounters.TryLookup(RawSegments, id, out var segments) && segments is not null
            ? segments.Take(8).Sum()
            : 0;
}

/// <summary>Where the stats host writes, and which files in there are finished matches.</summary>
public static class MatchExportFolder
{
    public const string DefaultGameDir = @"C:\Program Files (x86)\Steam\steamapps\common\eFootball";

    public static string ExportDir(string gameDir) => Path.Combine(gameDir, "ml_stats");

    /// <summary>
    /// <c>match_*.json</c>, and not what sits beside it: <c>live.json</c> (a match in progress),
    /// the host's <c>.json.tmp</c> half-writes, or efootball-re's own <c>.rated.json</c> output.
    /// </summary>
    public static bool IsMatchFile(string path)
    {
        var name = Path.GetFileName(path);
        return name.StartsWith("match_", StringComparison.OrdinalIgnoreCase)
               && name.EndsWith(".json", StringComparison.OrdinalIgnoreCase)
               && name.Count(c => c == '.') == 1;
    }

    /// <summary>Match files, newest kick-off first (the stem is the kick-off time).</summary>
    public static IReadOnlyList<string> MatchFiles(string dir) =>
        Directory.Exists(dir)
            ? Directory.EnumerateFiles(dir, "match_*.json").Where(IsMatchFile)
                .OrderByDescending(p => Path.GetFileName(p), StringComparer.Ordinal).ToList()
            : Array.Empty<string>();

    /// <summary>The newest export that the host has finalised, or null with the reason.</summary>
    public static MatchExport? LatestFinal(string dir, out string reason)
    {
        if (!Directory.Exists(dir))
        {
            reason = $"{dir} does not exist — the stats host has not exported a match on this install.";
            return null;
        }
        foreach (var path in MatchFiles(dir))
        {
            try
            {
                var export = MatchExport.Load(path);
                if (!export.Final) continue;
                reason = "";
                return export;
            }
            catch (Exception ex) when (ex is IOException or JsonException or FormatException)
            {
                // A file the host is mid-rename on, or one from another schema: try the next.
            }
        }
        reason = $"No finished match in {dir} yet.";
        return null;
    }
}

/// <summary>
/// Raises <see cref="ExportReady"/> for each finished match file the host drops into ml_stats.
/// The host writes <c>.json.tmp</c> and renames it, so a rename is the usual arrival.
/// </summary>
public sealed class MatchExportWatcher : IDisposable
{
    private readonly FileSystemWatcher _watcher;

    public event EventHandler<string>? ExportReady;

    public MatchExportWatcher(string exportDir)
    {
        _watcher = new FileSystemWatcher(exportDir, "match_*.json")
        {
            NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite,
            IncludeSubdirectories = false,
        };
        _watcher.Created += OnChanged;
        _watcher.Renamed += OnChanged;
    }

    public void Start() => _watcher.EnableRaisingEvents = true;

    private void OnChanged(object sender, FileSystemEventArgs e)
    {
        if (MatchExportFolder.IsMatchFile(e.FullPath)) ExportReady?.Invoke(this, e.FullPath);
    }

    public void Dispose()
    {
        _watcher.Created -= OnChanged;
        _watcher.Renamed -= OnChanged;
        _watcher.Dispose();
    }
}
