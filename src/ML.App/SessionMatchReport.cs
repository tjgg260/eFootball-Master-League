using System.Globalization;
using System.IO;
using System.Text.Json;
using ML.Ingest;

namespace ML.App;

/// <summary>One line of a report's team stats: a named counter or a share derived from two.</summary>
public sealed record ReportTeamStat(string Label, double Home, double Away, bool Percent, bool Inferred, string? Note);

/// <summary>One player of one side as the stats host saw him.</summary>
public sealed record ReportPlayer(int Slot, long? PlayerId, string Name, int? Shirt, string Status, double? Rating,
    IReadOnlyDictionary<string, long> Actions, double? FormAverage, int FormChanged);

/// <summary>A counter split across the host's time segments, per side.</summary>
public sealed record ReportSeries(string Label, long[] Home, long[] Away);

/// <summary>A raw engine counter, decoded or not.</summary>
public sealed record ReportCounter(string Id, string Label, long Home, long Away, string Confidence);

public sealed record MatchReportData(
    int FixtureId, int HomeTeamId, int AwayTeamId, string HomeName, string AwayName,
    int HomeGoals, int AwayGoals, string When, bool HasExport, string? Stem,
    DateTimeOffset? KickOff, DateTimeOffset? Finished, string? FinalReason,
    IReadOnlyList<ReportTeamStat> TeamStats, IReadOnlyList<ReportPlayer> HomePlayers,
    IReadOnlyList<ReportPlayer> AwayPlayers, IReadOnlyList<ReportSeries> Flow,
    IReadOnlyList<ReportCounter> Counters, IReadOnlyList<string> Caveats);

/// <summary>
/// The Match Report: everything the stats host recorded for one fixture, read from the export kept
/// verbatim against it (match_exports). The league's own tables keep what it computes with; this
/// shows the rest — every named counter for both teams and every player, the per-segment flow, the
/// game's pre-match form, every raw engine counter and the host's own caveats.
/// </summary>
public sealed partial class Session
{
    // The 21 named counters, in the order the report shows them.
    private static readonly (string Key, string Label)[] ReportCounterOrder =
    {
        ("goals", "Goals"), ("shots", "Shots"), ("shots_on_target", "Shots on target"),
        ("passes", "Passes"), ("passes_completed", "Passes completed"), ("crosses", "Crosses"),
        ("corners", "Corners"), ("offsides", "Offsides"), ("fouls", "Fouls"),
        ("tackles", "Tackles"), ("interceptions", "Interceptions"), ("ball_recoveries", "Ball recoveries"),
        ("saves", "Saves"), ("gk_shots_faced", "Shots faced (keeper)"),
        ("gk_shots_on_target_faced", "On target faced (keeper)"),
        ("ball_receptions", "Ball receptions"), ("ball_touches", "Ball touches"),
        ("possessions", "Possessions"), ("possessions_retained", "Possessions kept"),
        ("possession_time", "Possession time (s)"), ("sprints", "Sprints"),
    };

    // Counters efootball-re identified after this host was built (ML.Ingest.ExportCounters), read by
    // engine id and shown straight after the named counter they belong with.
    private static readonly (string AfterKey, string Id)[] IdentifiedPlacement =
    {
        ("goals", ExportCounters.PenaltyGoals), ("goals", ExportCounters.FinesseShotGoals),
        ("shots_on_target", ExportCounters.ChipShots),
        ("fouls", ExportCounters.YellowCards), ("fouls", ExportCounters.RedCards),
    };

    // Counters worth watching across the match (engine ids from the host's labels).
    private static readonly (string Label, string Id)[] FlowSeries =
    {
        ("Passes", "0x18"), ("Shots", "0x06"), ("Possession time", "0x4B"),
        ("Tackles", "0x35"), ("Ball recoveries", "0x4F"), ("Sprints", "0x4C"),
    };

    /// <summary>The host counts possession time at 48 units per real second (its label: measured).</summary>
    public const double PossessionUnitsPerSecond = 48.0;

    public MatchReportData? MatchReport(int fixtureId)
    {
        int season;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT season_id FROM fixtures WHERE id=$f";
            q.Parameters.AddWithValue("$f", fixtureId);
            if (q.ExecuteScalar() is not long s) return null;
            season = (int)s;
        }
        var f = Repo.Fixtures(season).FirstOrDefault(x => x.Id == fixtureId);
        if (f is null || ResultFor(fixtureId) is not { } r) return null;
        var when = ML.Core.Scheduling.SeasonCalendar.Label(DateOfFixture(f));

        var stored = StoredExport(fixtureId) ?? BackfillExport(fixtureId);
        if (stored is not { } found)
            return new MatchReportData(fixtureId, f.HomeTeamId, f.AwayTeamId, TeamName(f.HomeTeamId),
                TeamName(f.AwayTeamId), r.HomeGoals, r.AwayGoals, when, false, null, null, null, null,
                Array.Empty<ReportTeamStat>(), Array.Empty<ReportPlayer>(), Array.Empty<ReportPlayer>(),
                Array.Empty<ReportSeries>(), Array.Empty<ReportCounter>(), Array.Empty<string>());

        using var doc = JsonDocument.Parse(found.Json);
        var root = doc.RootElement;
        var teams = root.GetProperty("teams");
        var hi = found.HomeIndex is 0 or 1 ? found.HomeIndex : 0;
        var home = teams[hi];
        var away = teams[1 - hi];

        // The host's own labels: engine id -> (name, confidence).
        var labels = new Dictionary<string, (string Key, string Confidence)>(StringComparer.OrdinalIgnoreCase);
        if (root.TryGetProperty("labels", out var lab) && lab.ValueKind == JsonValueKind.Object)
            foreach (var p in lab.EnumerateObject())
                labels[p.Name] = (Str(p.Value, "key") ?? "", Str(p.Value, "confidence") ?? "");
        var confidenceOf = labels.Values.GroupBy(v => v.Key)
            .ToDictionary(g => g.Key, g => g.First().Confidence, StringComparer.OrdinalIgnoreCase);

        // ---- team stats: the named counters, then the shares a reader actually wants
        var stats = new List<ReportTeamStat>();
        long ht(string k) => Total(home, k);
        long at(string k) => Total(away, k);
        static double Share(long mine, long theirs) => mine + theirs > 0 ? Math.Round(100.0 * mine / (mine + theirs)) : 0;
        static double Pct(long part, long whole) => whole > 0 ? Math.Round(100.0 * part / whole) : 0;
        stats.Add(new ReportTeamStat("Possession", Share(ht("possession_time"), at("possession_time")),
            Share(at("possession_time"), ht("possession_time")), true, false,
            "share of the two teams' possession time — the export carries no possession figure of its own"));
        stats.Add(new ReportTeamStat("Pass accuracy", Pct(ht("passes_completed"), ht("passes")),
            Pct(at("passes_completed"), at("passes")), true, false, null));
        stats.Add(new ReportTeamStat("Shot accuracy", Pct(ht("shots_on_target"), ht("shots")),
            Pct(at("shots_on_target"), at("shots")), true, false, null));
        stats.Add(new ReportTeamStat("Possessions kept", Pct(ht("possessions_retained"), ht("possessions")),
            Pct(at("possessions_retained"), at("possessions")), true, false, null));
        foreach (var (key, label) in ReportCounterOrder)
        {
            double h = ht(key), a = at(key);
            if (key == "possession_time")
            {
                h = Math.Round(h / PossessionUnitsPerSecond);
                a = Math.Round(a / PossessionUnitsPerSecond);
            }
            // efootball-re's later findings outrank the label the host that wrote this export carried
            var conf = ExportCounters.ByKey(key)?.Confidence ?? confidenceOf.GetValueOrDefault(key);
            var inferred = conf?.StartsWith("inferred", StringComparison.OrdinalIgnoreCase) == true;
            stats.Add(new ReportTeamStat(label, h, a, false, inferred, inferred ? conf : null));
            foreach (var (_, id) in IdentifiedPlacement.Where(x => x.AfterKey == key))
            {
                var c = ExportCounters.ById(id)!;
                stats.Add(new ReportTeamStat(c.Label, Raw(home, id), Raw(away, id), false, c.Inferred,
                    c.Inferred ? c.Confidence : null));
            }
        }

        // ---- players, joined to the league player the export's PID resolved to when it was recorded
        var links = StoredPlayerLinks(fixtureId);
        var homePlayers = Players(home, "home", links);
        var awayPlayers = Players(away, "away", links);

        // ---- the flow: a counter summed over each side's players, per time segment (first 8)
        var flow = FlowSeries.Select(s => new ReportSeries(s.Label, Segments(home, s.Id), Segments(away, s.Id))).ToList();

        // ---- every raw engine counter, decoded or not
        var ids = RawIds(home).Union(RawIds(away), StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => Convert.ToInt32(id, 16)).ToList();
        var counters = ids.Select(id =>
        {
            var known = ExportCounters.ById(id);
            var hasLabel = labels.TryGetValue(id, out var l) && l.Key.Length > 0;
            var name = known?.Label.ToLowerInvariant() ?? (hasLabel ? l.Key.Replace('_', ' ') : "not yet identified");
            var confidence = known?.Confidence ?? (hasLabel ? l.Confidence : "");
            return new ReportCounter(id, name, Raw(home, id), Raw(away, id), confidence);
        }).ToList();

        var caveats = root.TryGetProperty("caveats", out var cv) && cv.ValueKind == JsonValueKind.Array
            ? cv.EnumerateArray().Select(c => c.GetString() ?? "").Where(c => c.Length > 0).ToList()
            : new List<string>();

        return new MatchReportData(fixtureId, f.HomeTeamId, f.AwayTeamId, TeamName(f.HomeTeamId),
            TeamName(f.AwayTeamId), r.HomeGoals, r.AwayGoals, when, true, found.Stem,
            Time(root, "first_seen"), Time(root, "snapshot_at"), Str(root, "final_reason"),
            stats, homePlayers, awayPlayers, flow, counters, caveats);
    }

    private IReadOnlyList<ReportPlayer> Players(JsonElement team, string side,
        IReadOnlyDictionary<(string, int), (long? PlayerId, double? Rating)> links)
    {
        var rows = new List<ReportPlayer>();
        if (!team.TryGetProperty("players", out var players) || players.ValueKind != JsonValueKind.Array) return rows;
        foreach (var p in players.EnumerateArray())
        {
            var slot = p.TryGetProperty("slot", out var sl) && sl.TryGetInt32(out var sv) ? sv : -1;
            links.TryGetValue((side, slot), out var link);
            var name = link.PlayerId is { } pid ? PlayerName(pid) : null;
            name ??= Str(p, "shirt_name") ?? $"Slot {slot}";
            int? shirt = p.TryGetProperty("shirt_number", out var sn) && sn.TryGetInt32(out var sh) ? sh : null;
            var onPitch = p.TryGetProperty("lineup_index", out var li) && li.ValueKind == JsonValueKind.Number;
            // Slots 0-10 started; 11+ came off the bench. A null lineup_index means he was taken off.
            var status = slot <= 10 ? (onPitch ? "Started" : "Started · subbed off")
                                    : (onPitch ? "Came on" : "Came on · subbed off");
            var actions = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
            if (p.TryGetProperty("actions", out var ac) && ac.ValueKind == JsonValueKind.Object)
                foreach (var a in ac.EnumerateObject())
                    if (a.Value.TryGetInt64(out var n)) actions[a.Name] = n;
            // the identified counters, by engine id: in raw_segments whether or not the host named them
            foreach (var c in ExportCounters.Identified)
                actions[c.Key] = PlayerRaw(p, c.Id);
            var (formAvg, formChanged) = Form(p);
            rows.Add(new ReportPlayer(slot, link.PlayerId, name, shirt, status, link.Rating, actions, formAvg, formChanged));
        }
        return rows.OrderBy(x => x.Slot).ToList();
    }

    /// <summary>
    /// The game's pre-match form, as the host read it: attributes_form minus attributes_base over
    /// the ability block (indices 20-46; only values on the 40-99 ability scale are compared, which
    /// leaves out the one non-ability flag the block carries). Null when the host sent no attributes.
    /// </summary>
    private static (double? Average, int Changed) Form(JsonElement p)
    {
        if (!p.TryGetProperty("attributes_base", out var b) || !p.TryGetProperty("attributes_form", out var f)
            || b.ValueKind != JsonValueKind.Array || f.ValueKind != JsonValueKind.Array) return (null, 0);
        var bs = b.EnumerateArray().Select(x => x.TryGetInt32(out var v) ? v : 0).ToArray();
        var fs = f.EnumerateArray().Select(x => x.TryGetInt32(out var v) ? v : 0).ToArray();
        var deltas = new List<int>();
        for (var i = 20; i <= 46 && i < bs.Length && i < fs.Length; i++)
            if (bs[i] is >= 40 and <= 99 && fs[i] is >= 40 and <= 99)
                deltas.Add(fs[i] - bs[i]);
        return deltas.Count == 0 ? (null, 0) : (deltas.Average(), deltas.Count(d => d != 0));
    }

    private static long[] Segments(JsonElement team, string id)
    {
        var sum = new long[8];
        if (!team.TryGetProperty("players", out var players)) return sum;
        foreach (var p in players.EnumerateArray())
            if (p.TryGetProperty("raw_segments", out var segs) && segs.TryGetProperty(id, out var arr)
                && arr.ValueKind == JsonValueKind.Array)
            {
                var i = 0;
                foreach (var v in arr.EnumerateArray())
                {
                    if (i >= 8) break;        // the host: the first 8 segments sum to the match total
                    if (v.TryGetInt64(out var n)) sum[i] += n;
                    i++;
                }
            }
        return sum;
    }

    /// <summary>One player's counter by engine id: the first 8 of its 9 segments (the host's match total).</summary>
    private static long PlayerRaw(JsonElement player, string id)
    {
        if (!player.TryGetProperty("raw_segments", out var segs) || segs.ValueKind != JsonValueKind.Object) return 0;
        foreach (var prop in segs.EnumerateObject())
        {
            if (!string.Equals(prop.Name, id, StringComparison.OrdinalIgnoreCase) || prop.Value.ValueKind != JsonValueKind.Array)
                continue;
            long sum = 0;
            var i = 0;
            foreach (var v in prop.Value.EnumerateArray())
            {
                if (i++ >= 8) break;
                if (v.TryGetInt64(out var n)) sum += n;
            }
            return sum;
        }
        return 0;
    }

    private static long Total(JsonElement team, string key) =>
        team.TryGetProperty("totals", out var t) && t.TryGetProperty(key, out var v) && v.TryGetInt64(out var n) ? n : 0;

    private static long Raw(JsonElement team, string id)
    {
        if (!team.TryGetProperty("raw_totals", out var t) || t.ValueKind != JsonValueKind.Object) return 0;
        foreach (var prop in t.EnumerateObject())
            if (string.Equals(prop.Name, id, StringComparison.OrdinalIgnoreCase) && prop.Value.TryGetInt64(out var n))
                return n;
        return 0;
    }

    private static IEnumerable<string> RawIds(JsonElement team) =>
        team.TryGetProperty("raw_totals", out var t) && t.ValueKind == JsonValueKind.Object
            ? t.EnumerateObject().Select(p => p.Name) : Enumerable.Empty<string>();

    private static string? Str(JsonElement e, string key) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() : null;

    private static DateTimeOffset? Time(JsonElement e, string key) =>
        Str(e, key) is { } s && DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.None, out var t)
            ? t : null;

    private string? PlayerName(long playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT name FROM players WHERE id=$p";
        q.Parameters.AddWithValue("$p", playerId);
        return q.ExecuteScalar() as string;
    }

    private (string Json, int HomeIndex, string Stem)? StoredExport(int fixtureId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT json, home_team_index, stem FROM match_exports WHERE fixture_id=$f";
        q.Parameters.AddWithValue("$f", fixtureId);
        using var rd = q.ExecuteReader();
        return rd.Read() ? (rd.GetString(0), rd.GetInt32(1), rd.GetString(2)) : null;
    }

    /// <summary>(side, slot) -> the league player and rating Record stored for this fixture.</summary>
    private IReadOnlyDictionary<(string, int), (long? PlayerId, double? Rating)> StoredPlayerLinks(int fixtureId)
    {
        var map = new Dictionary<(string, int), (long? PlayerId, double? Rating)>();
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT side, slot, stat, value FROM match_player_stats " +
                        "WHERE fixture_id=$f AND stat IN ('player_id','rating')";
        q.Parameters.AddWithValue("$f", fixtureId);
        using var rd = q.ExecuteReader();
        while (rd.Read())
        {
            var key = (rd.GetString(0), rd.GetInt32(1));
            map.TryGetValue(key, out var cur);
            map[key] = rd.GetString(2) == "player_id"
                ? (Convert.ToInt64(rd.GetDouble(3)), cur.Rating)
                : (cur.PlayerId, rd.GetDouble(3));
        }
        return map;
    }

    /// <summary>
    /// A fixture recorded before exports were kept verbatim (the league's first stats-host match):
    /// find its file in ml_stats by the team totals Record stored — shots, passes and tackles for
    /// both sides must all agree — and keep it now. Nothing matching, nothing kept.
    /// </summary>
    private (string Json, int HomeIndex, string Stem)? BackfillExport(int fixtureId)
    {
        var mine = new Dictionary<(string, string), long>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT side, stat, value FROM match_team_stats WHERE fixture_id=$f " +
                            "AND stat IN ('shots','passes','tackles')";
            q.Parameters.AddWithValue("$f", fixtureId);
            using var rd = q.ExecuteReader();
            while (rd.Read()) mine[(rd.GetString(0), rd.GetString(1))] = rd.GetInt64(2);
        }
        if (mine.Count < 6) return null;
        (long, long, long) Want(string side) => (mine[(side, "shots")], mine[(side, "passes")], mine[(side, "tackles")]);
        var (h, a) = (Want("home"), Want("away"));

        foreach (var path in MatchExportFolder.MatchFiles(MatchExportDir))
        {
            string json;
            try { json = File.ReadAllText(path); } catch (IOException) { continue; }
            try
            {
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;
                if (!root.TryGetProperty("final", out var fin) || fin.ValueKind != JsonValueKind.True) continue;
                var teams = root.GetProperty("teams");
                (long, long, long) Got(int i) => (Total(teams[i], "shots"), Total(teams[i], "passes"), Total(teams[i], "tackles"));
                var homeIndex = Got(0) == h && Got(1) == a ? 0 : Got(1) == h && Got(0) == a ? 1 : -1;
                if (homeIndex < 0) continue;
                var stem = Path.GetFileNameWithoutExtension(path);
                using var ins = Db.Connection.CreateCommand();
                ins.CommandText = "INSERT OR REPLACE INTO match_exports(fixture_id,stem,json,home_team_index,stored_at) " +
                                  "VALUES($f,$st,$j,$h,$t)";
                ins.Parameters.AddWithValue("$f", fixtureId);
                ins.Parameters.AddWithValue("$st", stem);
                ins.Parameters.AddWithValue("$j", json);
                ins.Parameters.AddWithValue("$h", homeIndex);
                ins.Parameters.AddWithValue("$t", DateTime.Now.ToString("s", CultureInfo.InvariantCulture));
                ins.ExecuteNonQuery();
                return (json, homeIndex, stem);
            }
            catch (Exception ex) when (ex is JsonException or KeyNotFoundException or InvalidOperationException
                                        or IndexOutOfRangeException)
            {
                // a file from another schema, or mid-write: try the next
            }
        }
        return null;
    }
}
