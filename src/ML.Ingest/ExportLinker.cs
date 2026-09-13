namespace ML.Ingest;

/// <summary>A player of one of the fixture's two squads, keyed by the PID the compile gave the player.</summary>
public sealed record SquadPlayer(long PlayerId, long GamePid, string Name, int TeamId);

public sealed record LinkedPlayer(ExportPlayer Export, SquadPlayer? Player, PlayerRating Rating)
{
    /// <summary>The league's name for the player, or what the shirt said when the PID is unknown.</summary>
    public string DisplayName => Player?.Name ?? Export.ShirtName ?? $"#{Export.ShirtNumber}";
}

public sealed record LinkedSide(ExportTeam Team, int TeamId, long Goals, IReadOnlyList<LinkedPlayer> Players);

/// <summary>An export tied to a fixture: its two teams put on the fixture's home and away sides.</summary>
public sealed record LinkedMatch(MatchExport Export, LinkedSide Home, LinkedSide Away, int Resolved, int WithPid)
{
    public IEnumerable<LinkedPlayer> AllPlayers => Home.Players.Concat(Away.Players);
}

/// <summary>
/// Decides whether an export is the fixture that is waiting, by PID. Both squads were compiled into
/// the game under their <c>players.game_pid</c>, so the export of that match carries exactly those
/// PIDs; any other match — an earlier one, an exhibition, an online game — does not. Team names
/// and the game's home/away never decide it: a host slot is renamed, and the league's home side
/// is not necessarily the game's.
/// </summary>
public static class ExportLinker
{
    /// <summary>Resolved players each fixture club needs before an export counts as its match.</summary>
    public const int MinResolvedPerTeam = 3;

    public static LinkedMatch? Link(MatchExport export, int homeTeamId, int awayTeamId,
                                    IReadOnlyCollection<SquadPlayer> squads, out string reason)
    {
        if (!export.Final)
        {
            reason = "that export is a match still in progress.";
            return null;
        }

        var withPid = export.Teams.Sum(t => t.Players.Count(p => p.PlayerId is not null));
        if (withPid == 0)
        {
            reason = "that export has no player ids (written before the stats host exported PIDs).";
            return null;
        }

        var byPid = new Dictionary<long, SquadPlayer>();
        foreach (var s in squads) byPid.TryAdd(s.GamePid, s);

        SquadPlayer? Find(ExportPlayer p) =>
            p.PlayerId is { } pid && byPid.TryGetValue(unchecked((long)pid), out var s) ? s : null;

        int Hits(ExportTeam team, int teamId) => team.Players.Count(p => Find(p)?.TeamId == teamId);

        var t0 = export.Teams[0];
        var t1 = export.Teams[1];
        var straight = (Home: Hits(t0, homeTeamId), Away: Hits(t1, awayTeamId));
        var swapped = (Home: Hits(t1, homeTeamId), Away: Hits(t0, awayTeamId));
        var useSwap = swapped.Home + swapped.Away > straight.Home + straight.Away;
        var best = useSwap ? swapped : straight;

        if (best.Home < MinResolvedPerTeam || best.Away < MinResolvedPerTeam)
        {
            reason = $"that export is not this fixture — only {best.Home} home and {best.Away} away players " +
                     $"match the two squads (need {MinResolvedPerTeam} each).";
            return null;
        }

        var ratings = MatchRating.RateMatch(export);
        LinkedSide Side(int index, int teamId)
        {
            var team = export.Teams[index];
            var players = team.Players.Select((p, i) => new LinkedPlayer(p, Find(p), ratings[index][i])).ToList();
            return new LinkedSide(team, teamId, team.Total("goals"), players);
        }

        var home = Side(useSwap ? 1 : 0, homeTeamId);
        var away = Side(useSwap ? 0 : 1, awayTeamId);
        reason = "";
        return new LinkedMatch(export, home, away,
            home.Players.Concat(away.Players).Count(p => p.Player is not null), withPid);
    }

    /// <summary>
    /// The team stats the league keeps per side, under the names the full-time STATS screen uses.
    /// All but possession equalled the screen in efootball-re's recorded match. Free kicks are the
    /// opponent's fouls, which is all the game's free-kick row counts.
    ///
    /// The export has no possession percentage, so <c>possession</c> is the share of the two teams'
    /// possession time (counter 0x4B) — the same "possession share" efootball-re's report.py shows.
    /// In the one match with the screen alongside it read 74/26 against the screen's 70/30. When the
    /// host exports the game's own percentage, take that instead. The raw time is kept as well.
    /// </summary>
    public static IReadOnlyDictionary<string, int> TeamStats(LinkedSide side, LinkedSide opponent)
    {
        var stats = new Dictionary<string, int>
        {
            ["shots"] = (int)side.Team.Total("shots"),
            ["shots_on_target"] = (int)side.Team.Total("shots_on_target"),
            ["fouls"] = (int)side.Team.Total("fouls"),
            ["offsides"] = (int)side.Team.Total("offsides"),
            ["corner_kicks"] = (int)side.Team.Total("corners"),
            ["free_kicks"] = (int)opponent.Team.Total("fouls"),
            ["passes"] = (int)side.Team.Total("passes"),
            ["successful_passes"] = (int)side.Team.Total("passes_completed"),
            ["crosses"] = (int)side.Team.Total("crosses"),
            ["interceptions"] = (int)side.Team.Total("interceptions"),
            ["tackles"] = (int)side.Team.Total("tackles"),
            ["saves"] = (int)side.Team.Total("saves"),
        };
        var mine = side.Team.RawTotals.GetValueOrDefault("0x4B");
        var theirs = opponent.Team.RawTotals.GetValueOrDefault("0x4B");
        if (mine + theirs > 0)
        {
            stats["possession"] = (int)Math.Round(100.0 * mine / (mine + theirs));
            stats["possession_time"] = (int)mine;
        }
        return stats;
    }
}
