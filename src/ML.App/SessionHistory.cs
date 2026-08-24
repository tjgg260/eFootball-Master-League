using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Tables;
using ML.Data;

namespace ML.App;

public sealed record CareerHistoryRow(
    int Year, string Club, int Apps, int Goals, int Assists, double? AvgRating);

public sealed record ClubRecordRow(string Record, string Holder);

/// <summary>
/// History & records (D3): every past season browsable — final tables, honours, top scorers —
/// plus player career-history rows and the club record book. All of it derives from tables the
/// seasons already wrote (fixtures, results, match_events, honours, transfers); nothing new is
/// stored.
/// </summary>
public sealed partial class Session
{
    /// <summary>Season ids with any played fixtures, newest first — the archive's index.</summary>
    public IReadOnlyList<int> ArchiveSeasons()
    {
        var rows = new List<int>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT DISTINCT season_id FROM fixtures WHERE id IN " +
                          "(SELECT fixture_id FROM results) ORDER BY season_id DESC";
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(r.GetInt32(0));
        return rows;
    }

    /// <summary>
    /// A past season's final league table, rebuilt from its own fixtures — membership comes
    /// from who actually played in that league that season, so promotion/relegation years
    /// render correctly.
    /// </summary>
    public IReadOnlyList<LeagueTableRow> TableForSeason(int seasonId, int leagueId)
    {
        var fixtures = new List<Fixture>();
        var teams = new HashSet<int>();
        foreach (var f in Repo.Fixtures(seasonId).Where(f => f.LeagueId == leagueId && f.Kind == "league"))
        {
            teams.Add(f.HomeTeamId);
            teams.Add(f.AwayTeamId);
            var fixture = new Fixture(f.Id, f.Matchday, new TeamId(f.HomeTeamId), new TeamId(f.AwayTeamId));
            if (f.Played && ResultFor(f.Id) is { } r)
            {
                fixture.RecordResult(new MatchResult(r.HomeGoals, r.AwayGoals));
            }
            fixtures.Add(fixture);
        }
        return LeagueTable.Build(teams.Select(t => new TeamId(t)).ToList(), fixtures);
    }

    /// <summary>League display name for archive headers (top flight vs Division 2).</summary>
    public string ArchiveLeagueName(int leagueId) => LeagueNameFor(leagueId);

    /// <summary>One past season's silverware (competition, winner).</summary>
    public IReadOnlyList<(string Competition, string Team, int TeamId)> HonoursIn(int seasonId)
    {
        var rows = new List<(string, string, int)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT competition, team_id FROM honours WHERE season_id=$s ORDER BY competition";
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var comp = r.GetString(0) switch
            {
                "league" => LeagueNameFor(TopFlight),
                "division2" => LeagueNameFor(Division2),
                "lcup" => LeagueCupName,
                _ => CupName,
            };
            rows.Add((comp, TeamName(r.GetInt32(1)), r.GetInt32(1)));
        }
        return rows;
    }

    /// <summary>Top scorers of any season — the archive variant of LeadersBy.</summary>
    public IReadOnlyList<(string Player, string Team, int Count)> LeadersIn(
        int seasonId, string eventType, int count = 10) =>
        LeadersInWithIds(seasonId, eventType, count)
            .Select(x => (x.Player, x.Team, x.Count)).ToList();

    /// <summary>
    /// LeadersIn with each scorer's player id kept. An archived leaderboard row is a handle
    /// on a real player — he may still be signable — so the id has to survive the query.
    /// </summary>
    public IReadOnlyList<(string Player, string Team, int Count, long PlayerId, int TeamId)> LeadersInWithIds(
        int seasonId, string eventType, int count = 10)
    {
        var rows = new List<(string, string, int, long, int)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.name, COALESCE(s.team_id, 0), COUNT(*) AS g, e.player_id FROM match_events e " +
            "JOIN players p ON p.id = e.player_id " +
            "LEFT JOIN squad_members s ON s.player_id = e.player_id " +
            "JOIN fixtures f ON f.id = e.fixture_id " +
            "WHERE e.event_type=$t AND f.season_id=$s " +
            "GROUP BY e.player_id ORDER BY g DESC, p.name LIMIT $n";
        cmd.Parameters.AddWithValue("$t", eventType);
        cmd.Parameters.AddWithValue("$s", seasonId);
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            // cols: 0 name · 1 team_id · 2 count · 3 player_id
            rows.Add((r.GetString(0), TeamName(r.GetInt32(1)), r.GetInt32(2),
                      r.GetInt64(3), r.GetInt32(1)));
        }
        return rows;
    }

    /// <summary>
    /// HonoursIn with the holder's identity kept. Award rows ('pots') store a PLAYER id in
    /// the team column, so a caller wiring a right-click menu has to know which it is before
    /// it offers to view a squad that does not exist.
    /// </summary>
    public IReadOnlyList<(string Competition, string Holder, int HolderId, bool HolderIsPlayer)>
        HonoursInWithHolders(int seasonId)
    {
        var rows = new List<(string, string, int, bool)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT competition, team_id FROM honours WHERE season_id=$s ORDER BY competition";
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var raw = r.GetString(0);
            var comp = raw switch
            {
                "league" => LeagueNameFor(TopFlight),
                "division2" => LeagueNameFor(Division2),
                "lcup" => LeagueCupName,
                "ccup" => ContinentalName,
                "pots" => "Player of the Season",
                _ => CupName,
            };
            var isPlayer = raw == "pots";
            var id = r.GetInt32(1);
            rows.Add((comp, isPlayer ? PlayerNameOf(id) : TeamName(id), id, isPlayer));
        }
        return rows;
    }

    /// <summary>
    /// A player's season-by-season line for the card. The club per season is reconstructed from
    /// the transfer log (last move at or before that season wins; otherwise today's club).
    /// </summary>
    public IReadOnlyList<CareerHistoryRow> PlayerCareerHistory(long playerId)
    {
        // Transfer trail, oldest first: (season, to_team).
        var moves = new List<(int Season, int ToTeam)>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT COALESCE(season_id, 0), COALESCE(to_team_id, 0) FROM transfers " +
                              "WHERE player_id=$p AND to_team_id IS NOT NULL ORDER BY season_id, id";
            cmd.Parameters.AddWithValue("$p", playerId);
            using var r = cmd.ExecuteReader();
            while (r.Read()) moves.Add((r.GetInt32(0), r.GetInt32(1)));
        }
        int currentClub;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT team_id FROM squad_members WHERE player_id=$p LIMIT 1";
            cmd.Parameters.AddWithValue("$p", playerId);
            var v = cmd.ExecuteScalar();
            currentClub = v is null or DBNull ? 0 : Convert.ToInt32(v);
        }
        string ClubIn(int season)
        {
            var club = moves.Where(m => m.Season <= season).Select(m => (int?)m.ToTeam).LastOrDefault()
                       ?? (moves.Count > 0 ? moves[0].ToTeam : currentClub);
            // Before the first logged move the player was wherever the first move took them FROM —
            // unknowable from to_team alone, so fall back to today's club for pre-log seasons.
            if (moves.Count > 0 && season < moves[0].Season) club = currentClub;
            return club > 0 ? TeamName(club) : "—";
        }

        var rows = new List<CareerHistoryRow>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT f.season_id, " +
                "SUM(CASE WHEN e.event_type='app' THEN 1 ELSE 0 END), " +
                "SUM(CASE WHEN e.event_type='goal' THEN 1 ELSE 0 END), " +
                "SUM(CASE WHEN e.event_type='assist' THEN 1 ELSE 0 END) " +
                "FROM match_events e JOIN fixtures f ON f.id=e.fixture_id " +
                "WHERE e.player_id=$p GROUP BY f.season_id ORDER BY f.season_id DESC";
            cmd.Parameters.AddWithValue("$p", playerId);
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                var season = r.GetInt32(0);
                rows.Add(new CareerHistoryRow(
                    2026 + (season - 9000), ClubIn(season),
                    r.GetInt32(1), r.GetInt32(2), r.GetInt32(3), null));
            }
        }
        // Average ratings joined per season in one pass.
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT f.season_id, AVG(r.rating) FROM player_match_ratings r " +
                              "JOIN fixtures f ON f.id=r.fixture_id WHERE r.player_id=$p " +
                              "GROUP BY f.season_id";
            cmd.Parameters.AddWithValue("$p", playerId);
            using var r = cmd.ExecuteReader();
            var avgBySeason = new Dictionary<int, double>();
            while (r.Read()) avgBySeason[r.GetInt32(0)] = r.GetDouble(1);
            for (var i = 0; i < rows.Count; i++)
            {
                var season = 9000 + (rows[i].Year - 2026);
                if (avgBySeason.TryGetValue(season, out var avg))
                {
                    rows[i] = rows[i] with { AvgRating = Math.Round(avg, 1) };
                }
            }
        }
        return rows;
    }

    /// <summary>The club record book, computed across every season on file.</summary>
    public IReadOnlyList<ClubRecordRow> ClubRecords()
    {
        var records = new List<ClubRecordRow>();

        // Biggest win + heaviest defeat, from every result involving the club.
        var games = new List<(int Season, int Md, int Us, int Them, string Opp)>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT f.season_id, f.matchday, f.home_team_id, f.away_team_id, r.home_goals, r.away_goals " +
                "FROM results r JOIN fixtures f ON f.id=r.fixture_id " +
                "WHERE (f.home_team_id=$t OR f.away_team_id=$t) AND f.kind != 'friendly' " +
                "ORDER BY f.season_id, f.matchday";
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                var home = r.GetInt32(2) == CurrentTeamId;
                var us = home ? r.GetInt32(4) : r.GetInt32(5);
                var them = home ? r.GetInt32(5) : r.GetInt32(4);
                games.Add((r.GetInt32(0), r.GetInt32(1), us, them,
                    TeamName(home ? r.GetInt32(3) : r.GetInt32(2))));
            }
        }
        if (games.Count > 0)
        {
            var big = games.OrderByDescending(g => g.Us - g.Them).ThenByDescending(g => g.Us).First();
            if (big.Us > big.Them)
            {
                records.Add(new ClubRecordRow("Biggest win",
                    $"{big.Us}–{big.Them} v {big.Opp} ({2026 + (big.Season - 9000)})"));
            }
            var heavy = games.OrderBy(g => g.Us - g.Them).ThenByDescending(g => g.Them).First();
            if (heavy.Them > heavy.Us)
            {
                records.Add(new ClubRecordRow("Heaviest defeat",
                    $"{heavy.Us}–{heavy.Them} v {heavy.Opp} ({2026 + (heavy.Season - 9000)})"));
            }

            var best = 0;
            var run = 0;
            foreach (var g in games)
            {
                run = g.Us > g.Them ? run + 1 : 0;
                best = Math.Max(best, run);
            }
            if (best > 0) records.Add(new ClubRecordRow("Longest winning run", $"{best} matches"));
        }

        // Record signing + record sale, from the transfer log.
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT p.name, t.fee, COALESCE(t.season_id, 0) FROM transfers t " +
                "JOIN players p ON p.id=t.player_id " +
                "WHERE t.to_team_id=$t AND t.fee > 0 ORDER BY t.fee DESC LIMIT 1";
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                records.Add(new ClubRecordRow("Record signing",
                    $"{r.GetString(0)} — £{r.GetInt64(1):N0} ({2026 + (r.GetInt32(2) - 9000)})"));
            }
        }
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT p.name, t.fee, COALESCE(t.season_id, 0) FROM transfers t " +
                "JOIN players p ON p.id=t.player_id " +
                "WHERE t.from_team_id=$t AND t.fee > 0 ORDER BY t.fee DESC LIMIT 1";
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                records.Add(new ClubRecordRow("Record sale",
                    $"{r.GetString(0)} — £{r.GetInt64(1):N0} ({2026 + (r.GetInt32(2) - 9000)})"));
            }
        }

        // All-time club top scorer, from the event log.
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT p.name, COUNT(*) AS g FROM match_events e " +
                "JOIN players p ON p.id=e.player_id " +
                "JOIN squad_members s ON s.player_id=e.player_id " +
                "WHERE e.event_type='goal' AND s.team_id=$t GROUP BY e.player_id " +
                "ORDER BY g DESC LIMIT 1";
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                records.Add(new ClubRecordRow("All-time top scorer", $"{r.GetString(0)} — {r.GetInt64(1)} goals"));
            }
        }

        return records;
    }
}
