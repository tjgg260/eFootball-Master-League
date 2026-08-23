using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace ML.App;

/// <summary>
/// Reads a finished match's TEAM STATS + PLAYER RATINGS straight out of eFootball's live memory
/// (read-only — tools/read_match_memory.py, no debugger/injection) and stores them against the
/// fixture. The one thing the game computes but never lets you keep: pass completion, shot
/// accuracy, tackles, and every player's rating, captured at the full-time results screen.
/// </summary>
public sealed partial class Session
{
    /// <summary>
    /// Run the memory reader for the given fixture and persist team stats + ratings.
    /// Returns a human summary (pass completion etc.) or an error line.
    /// </summary>
    public string ReadMatchStatsFromMemory(int fixtureId)
    {
        var root = MatchLauncher.FindRepoRoot();
        if (root is null) return "Can't find the repo (tools/read_match_memory.py).";

        string stdout;
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = CareerBuilder.PythonExe(),
                WorkingDirectory = root,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            psi.ArgumentList.Add(Path.Combine("tools", "read_match_memory.py"));
            psi.Environment["PYTHONIOENCODING"] = "utf-8";
            using var proc = Process.Start(psi)!;
            stdout = proc.StandardOutput.ReadToEnd();
            proc.StandardError.ReadToEnd();
            proc.WaitForExit(20000);
        }
        catch (Exception ex)
        {
            return $"Couldn't run the memory reader ({ex.Message}). Is Python on PATH?";
        }

        MatchMemory? data;
        try { data = JsonSerializer.Deserialize<MatchMemory>(stdout, JsonOpts); }
        catch { return "The memory reader returned no usable data. Be on the full-time results screen."; }
        if (data is null || (data.Error is { Length: > 0 }))
            return data?.Error ?? "No match data found in memory — be on the full-time results screen.";

        var parts = new List<string>();
        if (data.TeamStats is { } ts)
        {
            StoreTeamStats(fixtureId, "home", ts.Home);
            StoreTeamStats(fixtureId, "away", ts.Away);
            var (ph, pa) = (Pct(ts.Home, "successful_passes", "passes"), Pct(ts.Away, "successful_passes", "passes"));
            parts.Add($"team stats stored — pass completion {ph}% / {pa}%");
        }
        if (data.Ratings is { } r)
        {
            StoreRatings(fixtureId, "home", r.Home);
            StoreRatings(fixtureId, "away", r.Away);
            parts.Add($"{r.Home.Count + r.Away.Count} player ratings stored");
        }
        return parts.Count > 0 ? "📊 " + string.Join(" · ", parts) : "No data captured.";
    }

    private void StoreTeamStats(int fixtureId, string side, Dictionary<string, int> stats)
    {
        foreach (var (stat, value) in stats)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText = "INSERT OR REPLACE INTO match_team_stats(fixture_id,side,stat,value) " +
                              "VALUES($f,$s,$k,$v)";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            cmd.Parameters.AddWithValue("$s", side);
            cmd.Parameters.AddWithValue("$k", stat);
            cmd.Parameters.AddWithValue("$v", value);
            cmd.ExecuteNonQuery();
        }
    }

    private void StoreRatings(int fixtureId, string side, IReadOnlyList<double> ratings)
    {
        for (var i = 0; i < ratings.Count; i++)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText = "INSERT OR REPLACE INTO match_player_ratings(fixture_id,side,slot,rating) " +
                              "VALUES($f,$s,$i,$r)";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            cmd.Parameters.AddWithValue("$s", side);
            cmd.Parameters.AddWithValue("$i", i);
            cmd.Parameters.AddWithValue("$r", ratings[i]);
            cmd.ExecuteNonQuery();
        }
    }

    /// <summary>Team stats for a fixture as (stat, home, away) rows, for the Stats screen.</summary>
    public IReadOnlyList<(string Stat, int Home, int Away)> TeamStatsFor(int fixtureId)
    {
        var home = new Dictionary<string, int>();
        var away = new Dictionary<string, int>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT side, stat, value FROM match_team_stats WHERE fixture_id=$f";
        cmd.Parameters.AddWithValue("$f", fixtureId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            (r.GetString(0) == "home" ? home : away)[r.GetString(1)] = r.GetInt32(2);
        }
        var order = new[] { "possession", "shots", "shots_on_target", "passes", "successful_passes",
                            "crosses", "interceptions", "tackles", "saves" };
        return order.Where(k => home.ContainsKey(k) || away.ContainsKey(k))
            .Select(k => (k, home.GetValueOrDefault(k), away.GetValueOrDefault(k))).ToList();
    }

    /// <summary>Stored per-player ratings for a fixture side, in results-screen order.</summary>
    public IReadOnlyList<double> PlayerRatingsFor(int fixtureId, string side)
    {
        var rows = new List<double>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT rating FROM match_player_ratings WHERE fixture_id=$f AND side=$s " +
                          "ORDER BY slot";
        cmd.Parameters.AddWithValue("$f", fixtureId);
        cmd.Parameters.AddWithValue("$s", side);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(r.GetDouble(0));
        return rows;
    }

    private static int Pct(Dictionary<string, int> s, string num, string den) =>
        s.GetValueOrDefault(den) > 0 ? (int)Math.Round(100.0 * s.GetValueOrDefault(num) / s[den]) : 0;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,   // team_stats, successful_passes…
        PropertyNameCaseInsensitive = true,
    };

    private sealed record MatchMemory(TeamStatsPair? TeamStats, RatingsPair? Ratings, string? Error);
    private sealed record TeamStatsPair(Dictionary<string, int> Home, Dictionary<string, int> Away);
    private sealed record RatingsPair(List<double> Home, List<double> Away);
}
