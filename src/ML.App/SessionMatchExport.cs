using System.Globalization;
using System.IO;
using ML.Ingest;

namespace ML.App;

/// <summary>
/// Results from efootball-re's stats host: the injected hook writes each finished match to
/// <c>&lt;eFootball&gt;\ml_stats\match_*.json</c>, and this ties an export to the fixture that is
/// waiting (by PID) and keeps what it carries — team stats, every player's counters and a rating
/// (MatchRating, a port of efootball-re's rating.py). Scorers and ratings reach season stats the
/// way typed ones do, through RecordMatchStats; the dashboard pre-fills them for the manager to
/// confirm with Record.
/// </summary>
public sealed partial class Session
{
    /// <summary>The eFootball install folder; the stats host writes ml_stats\ inside it.</summary>
    public string GameDir
    {
        get => GetMeta("game_dir") is { Length: > 0 } dir ? dir : MatchExportFolder.DefaultGameDir;
        set => SetMeta("game_dir", value.Trim());
    }

    public string MatchExportDir => MatchExportFolder.ExportDir(GameDir);

    /// <summary>
    /// Every export up to this stem belongs to a match whose result is already recorded. Stems are
    /// kick-off times (<c>match_20260913_215134</c>), so they order as strings. Without it, the
    /// return leg between the same two clubs would link to the first leg's export.
    /// </summary>
    public string? ExportWatermark => GetMeta("ml_stats_watermark") is { Length: > 0 } w ? w : null;

    public bool IsAfterExportWatermark(MatchExport export) =>
        ExportWatermark is null || string.CompareOrdinal(export.Stem, ExportWatermark) > 0;

    /// <summary>A result was recorded: whatever the host has written so far is spoken for.</summary>
    public void AdvanceExportWatermark()
    {
        var newest = MatchExportFolder.MatchFiles(MatchExportDir).Select(Path.GetFileNameWithoutExtension).FirstOrDefault();
        if (newest is not null && (ExportWatermark is null || string.CompareOrdinal(newest, ExportWatermark) > 0))
            SetMeta("ml_stats_watermark", newest);
    }

    /// <summary>The export tied to this fixture's two squads, or null with the reason it isn't.</summary>
    public LinkedMatch? LinkMatchExport(MatchExport export, int homeTeamId, int awayTeamId, out string reason)
    {
        var squads = new[] { homeTeamId, awayTeamId }
            .SelectMany(teamId => Repo.SquadPlayers(teamId)
                .Select(p => new SquadPlayer(p.Id, p.GamePid, p.Name, teamId)))
            .ToList();
        return ExportLinker.Link(export, homeTeamId, awayTeamId, squads, out reason);
    }

    /// <summary>
    /// Scorers as RecordMatchStats reads them: one full name per goal. Full names, because the
    /// recorder tries an exact name before a surname, and two players can share a surname.
    /// </summary>
    public static IReadOnlyList<string> ExportScorers(LinkedMatch m) =>
        m.AllPlayers.Where(p => p.Player is not null)
            .SelectMany(p => Enumerable.Repeat(p.Player!.Name, p.Export.Action("goals"))).ToList();

    /// <summary>Goals whose scorer's PID is not in either squad (named by shirt for the log).</summary>
    public static IReadOnlyList<string> UnresolvedScorers(LinkedMatch m) =>
        m.AllPlayers.Where(p => p.Player is null && p.Export.Action("goals") > 0)
            .Select(p => $"{p.DisplayName} ×{p.Export.Action("goals")}").ToList();

    /// <summary>"Name 7.5, Name 6.8" for every resolved player of both sides.</summary>
    public static string ExportRatingsText(LinkedMatch m) =>
        string.Join(", ", m.AllPlayers.Where(p => p.Player is not null)
            .Select(p => $"{p.Player!.Name} {p.Rating.Rating.ToString("0.0", CultureInfo.InvariantCulture)}"));

    /// <summary>
    /// Keep an export's numbers against the recorded fixture: team stats per side, each player's
    /// rating and counters (keyed by the export's roster slot, with the league player id as a stat
    /// so the row can be joined), and shots into the result for the post-match report.
    /// </summary>
    public string StoreMatchExport(int fixtureId, LinkedMatch m)
    {
        using var tx = Db.Connection.BeginTransaction();
        foreach (var (side, mine, theirs) in new[] { ("home", m.Home, m.Away), ("away", m.Away, m.Home) })
        {
            foreach (var (stat, value) in ExportLinker.TeamStats(mine, theirs))
                Insert("INSERT OR REPLACE INTO match_team_stats(fixture_id,side,stat,value) VALUES($f,$s,$k,$v)",
                    ("$f", fixtureId), ("$s", side), ("$k", stat), ("$v", value));
            foreach (var p in mine.Players)
            {
                Insert("INSERT OR REPLACE INTO match_player_ratings(fixture_id,side,slot,rating) VALUES($f,$s,$i,$v)",
                    ("$f", fixtureId), ("$s", side), ("$i", p.Export.Slot), ("$v", p.Rating.Rating));
                var stats = p.Export.Actions.Select(a => (Stat: a.Key, Value: (double)a.Value)).ToList();
                stats.Add(("rating", p.Rating.Rating));
                if (p.Player is not null) stats.Add(("player_id", p.Player.PlayerId));
                foreach (var (stat, value) in stats)
                    Insert("INSERT OR REPLACE INTO match_player_stats(fixture_id,side,slot,stat,value) VALUES($f,$s,$i,$k,$v)",
                        ("$f", fixtureId), ("$s", side), ("$i", p.Export.Slot), ("$k", stat), ("$v", value));
            }
        }
        tx.Commit();
        var home = ExportLinker.TeamStats(m.Home, m.Away);
        var away = ExportLinker.TeamStats(m.Away, m.Home);
        SaveMatchStats(fixtureId, home.TryGetValue("possession", out var ph) ? ph : null,
            away.TryGetValue("possession", out var pa) ? pa : null,
            (int)m.Home.Team.Total("shots"), (int)m.Away.Team.Total("shots"));
        return $"📊 Match data stored from {m.Export.Stem}: team stats, and counters and ratings for " +
               $"{m.Home.Players.Count + m.Away.Players.Count} players ({m.Resolved} of {m.WithPid} matched to the squads).";

        void Insert(string sql, params (string Name, object Value)[] args)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.Transaction = tx;
            cmd.CommandText = sql;
            foreach (var (name, value) in args) cmd.Parameters.AddWithValue(name, value);
            cmd.ExecuteNonQuery();
        }
    }
}
