using System.Collections.Generic;
using System.IO;
using Microsoft.Data.Sqlite;

namespace ML.Web.Data;

/// <summary>Read-only access to the league database (master.db). PoC data layer for the Blazor UI.</summary>
public sealed class Db
{
    private readonly string _path;

    public Db() => _path = FindDb();

    private static string FindDb()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var p = Path.Combine(dir.FullName, "build", "master.db");
            if (File.Exists(p)) return p;
            dir = dir.Parent;
        }
        return @"C:\Users\tjgg2\Downloads\eFootball Master League\build\master.db";
    }

    private SqliteConnection Open()
    {
        var c = new SqliteConnection($"Data Source={_path};Mode=ReadOnly;Cache=Shared");
        c.Open();
        return c;
    }

    public List<TeamRow> Teams(int limit = 300)
    {
        var list = new List<TeamRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT t.id, t.name, COUNT(s.player_id) n FROM teams t " +
            "JOIN squad_members s ON s.team_id=t.id " +
            "WHERE t.name IS NOT NULL AND t.name<>'' GROUP BY t.id HAVING n>=11 " +
            "ORDER BY t.name LIMIT $l";
        cmd.Parameters.AddWithValue("$l", limit);
        using var r = cmd.ExecuteReader();
        while (r.Read()) list.Add(new TeamRow(r.GetInt32(0), r.GetString(1), r.GetInt32(2)));
        return list;
    }

    /// <summary>Find a team by exact name (for the default landing club).</summary>
    public TeamRow? FindTeam(string name)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT t.id, t.name, COUNT(s.player_id) n FROM teams t " +
            "JOIN squad_members s ON s.team_id=t.id WHERE t.name=$n GROUP BY t.id ORDER BY n DESC LIMIT 1";
        cmd.Parameters.AddWithValue("$n", name);
        using var r = cmd.ExecuteReader();
        return r.Read() ? new TeamRow(r.GetInt32(0), r.GetString(1), r.GetInt32(2)) : null;
    }

    /// <summary>Substring search across ALL teams (name picker). Ranks fuller squads first.</summary>
    public List<TeamRow> SearchTeams(string q, int limit = 40)
    {
        var list = new List<TeamRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        // one row per club name (largest squad wins) so dt200/reference twins don't both appear
        cmd.CommandText =
            "SELECT id, name, n FROM (" +
            "  SELECT t.id id, t.name name, COUNT(s.player_id) n, " +
            "    ROW_NUMBER() OVER (PARTITION BY t.name ORDER BY COUNT(s.player_id) DESC) rk " +
            "  FROM teams t JOIN squad_members s ON s.team_id=t.id " +
            "  WHERE t.name LIKE $q GROUP BY t.id HAVING n>=7" +
            ") WHERE rk=1 ORDER BY (name LIKE $exact) DESC, n DESC, name LIMIT $l";
        cmd.Parameters.AddWithValue("$q", "%" + q + "%");
        cmd.Parameters.AddWithValue("$exact", q + "%");
        cmd.Parameters.AddWithValue("$l", limit);
        using var r = cmd.ExecuteReader();
        while (r.Read()) list.Add(new TeamRow(r.GetInt32(0), r.GetString(1), r.GetInt32(2)));
        return list;
    }

    public string TeamName(int teamId)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT name FROM teams WHERE id=$t";
        cmd.Parameters.AddWithValue("$t", teamId);
        return cmd.ExecuteScalar() as string ?? "Squad";
    }

    public List<PlayerRow> Squad(int teamId)
    {
        var list = new List<PlayerRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT p.id, p.name, COALESCE(p.position,''), COALESCE(p.age,0), " +
            "COALESCE(p.overall_rating,0), COALESCE(p.real_face_path,p.portrait_path), s.slot, COALESCE(s.squad_number,0) " +
            "FROM squad_members s JOIN players p ON p.id=s.player_id " +
            "WHERE s.team_id=$t ORDER BY (s.slot BETWEEN 0 AND 10) DESC, s.slot, p.overall_rating DESC";
        cmd.Parameters.AddWithValue("$t", teamId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(new PlayerRow(r.GetInt64(0), r.GetString(1), r.GetString(2), r.GetInt32(3),
                r.GetInt32(4), r.IsDBNull(5) ? null : r.GetString(5), r.GetInt32(6), r.GetInt32(7)));
        return list;
    }

    public PlayerBio Bio(long id)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT name, COALESCE(position,''), COALESCE(nationality,''), COALESCE(age,0), " +
            "COALESCE(height_cm,0), COALESCE(weight_kg,0), COALESCE(overall_rating,0), COALESCE(real_face_path,portrait_path) " +
            "FROM players WHERE id=$p";
        cmd.Parameters.AddWithValue("$p", id);
        using var r = cmd.ExecuteReader();
        if (!r.Read()) return new PlayerBio(id, "—", "", "", 0, 0, 0, 0, null);
        return new PlayerBio(id, r.GetString(0), r.GetString(1), r.GetString(2), r.GetInt32(3),
            r.GetInt32(4), r.GetInt32(5), r.GetInt32(6), r.IsDBNull(7) ? null : r.GetString(7));
    }

    public Dictionary<string, int> Attributes(long id)
    {
        var d = new Dictionary<string, int>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT attribute, value FROM player_attributes WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", id);
        using var r = cmd.ExecuteReader();
        while (r.Read()) d[r.GetString(0)] = r.GetInt32(1);
        return d;
    }

    public List<string> Skills(long id)
    {
        var list = new List<string>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT skill FROM player_skills WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", id);
        using var r = cmd.ExecuteReader();
        while (r.Read()) list.Add(r.GetString(0));
        return list;
    }

    public (string? Primary, string? Secondary) Playstyles(long id)
    {
        string? pri = null, sec = null;
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT kind, playstyle FROM player_playstyles WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", id);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            if (r.GetString(0) == "primary") pri = r.GetString(1);
            else if (r.GetString(0) == "secondary") sec = r.GetString(1);
        }
        return (pri, sec);
    }

    /// <summary>Market search across the whole world DB (375k players), with current club.</summary>
    public List<MarketRow> SearchPlayers(string q, string? unit = null, int? maxAge = null, int limit = 60)
    {
        var list = new List<MarketRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        var posFilter = unit switch
        {
            "GK" => " AND p.position='GK'",
            "DEF" => " AND p.position IN ('CB','LB','RB','LWB','RWB')",
            "MID" => " AND p.position IN ('DMF','CMF','AMF','LMF','RMF')",
            "FWD" => " AND p.position IN ('CF','SS','LWF','RWF')",
            _ => "",
        };
        cmd.CommandText =
            "SELECT p.id, p.name, COALESCE(p.position,''), COALESCE(p.age,0), COALESCE(p.overall_rating,0), " +
            "COALESCE(p.real_face_path,p.portrait_path), COALESCE(t.name,'Free agent') " +
            "FROM players p LEFT JOIN squad_members s ON s.player_id=p.id LEFT JOIN teams t ON t.id=s.team_id " +
            "WHERE p.name LIKE $q AND (p.id < 20000000 OR p.id >= 700000000)" + posFilter +
            (maxAge is not null ? " AND p.age <= $age" : "") +
            " ORDER BY p.overall_rating DESC LIMIT $l";
        cmd.Parameters.AddWithValue("$q", "%" + q + "%");
        if (maxAge is not null) cmd.Parameters.AddWithValue("$age", maxAge.Value);
        cmd.Parameters.AddWithValue("$l", limit);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(new MarketRow(r.GetInt64(0), r.GetString(1), r.GetString(2), r.GetInt32(3),
                r.GetInt32(4), r.IsDBNull(5) ? null : r.GetString(5), r.GetString(6)));
        return list;
    }

    public long PlayerCount()
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM players";
        return (long)cmd.ExecuteScalar()!;
    }

    // ================= career state =================

    private SqliteConnection OpenWrite()
    {
        var c = new SqliteConnection($"Data Source={_path};Mode=ReadWrite");
        c.Open();
        return c;
    }

    public string? Meta(string key)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT value FROM meta WHERE key=$k";
        cmd.Parameters.AddWithValue("$k", key);
        return cmd.ExecuteScalar() as string;
    }

    public void SetMeta(string key, string value)
    {
        using var con = OpenWrite();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "INSERT OR REPLACE INTO meta(key,value) VALUES($k,$v)";
        cmd.Parameters.AddWithValue("$k", key);
        cmd.Parameters.AddWithValue("$v", value);
        cmd.ExecuteNonQuery();
    }

    public CareerContext? Career()
    {
        var team = Meta("current_team_id");
        var season = Meta("current_season_id");
        if (team is null || season is null) return null;
        var tid = int.Parse(team);
        var sid = int.Parse(season);
        var mgr = Meta($"mgrname_{tid}") ?? "Manager";
        var chair = Meta($"chairman_{tid}") ?? "";
        return new CareerContext(tid, TeamName(tid), sid, mgr, chair);
    }

    public FixtureRow? NextFixture(int teamId, int seasonId)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT f.id, f.matchday, f.home_team_id, f.away_team_id, h.name, a.name, f.kind, f.played " +
            "FROM fixtures f JOIN teams h ON h.id=f.home_team_id JOIN teams a ON a.id=f.away_team_id " +
            "WHERE f.season_id=$s AND f.played=0 AND (f.home_team_id=$t OR f.away_team_id=$t) " +
            "ORDER BY f.matchday LIMIT 1";
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        if (!r.Read()) return null;
        return new FixtureRow(r.GetInt64(0), r.GetInt32(1), r.GetInt32(2), r.GetInt32(3),
            r.GetString(4), r.GetString(5), r.GetString(6), r.GetInt32(7) != 0, null, null);
    }

    public List<FixtureRow> TeamFixtures(int teamId, int seasonId)
    {
        var list = new List<FixtureRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT f.id, f.matchday, f.home_team_id, f.away_team_id, h.name, a.name, f.kind, f.played, " +
            "r.home_goals, r.away_goals " +
            "FROM fixtures f JOIN teams h ON h.id=f.home_team_id JOIN teams a ON a.id=f.away_team_id " +
            "LEFT JOIN results r ON r.fixture_id=f.id " +
            "WHERE f.season_id=$s AND (f.home_team_id=$t OR f.away_team_id=$t) ORDER BY f.matchday";
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(new FixtureRow(r.GetInt64(0), r.GetInt32(1), r.GetInt32(2), r.GetInt32(3),
                r.GetString(4), r.GetString(5), r.GetString(6), r.GetInt32(7) != 0,
                r.IsDBNull(8) ? null : r.GetInt32(8), r.IsDBNull(9) ? null : r.GetInt32(9)));
        return list;
    }

    public List<FixtureRow> MatchdayFixtures(int leagueId, int seasonId, int matchday)
    {
        var list = new List<FixtureRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText =
            "SELECT f.id, f.matchday, f.home_team_id, f.away_team_id, h.name, a.name, f.kind, f.played, " +
            "r.home_goals, r.away_goals " +
            "FROM fixtures f JOIN teams h ON h.id=f.home_team_id JOIN teams a ON a.id=f.away_team_id " +
            "LEFT JOIN results r ON r.fixture_id=f.id " +
            "WHERE f.season_id=$s AND f.league_id=$l AND f.matchday=$m AND f.kind='league' ORDER BY f.id";
        cmd.Parameters.AddWithValue("$l", leagueId);
        cmd.Parameters.AddWithValue("$s", seasonId);
        cmd.Parameters.AddWithValue("$m", matchday);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(new FixtureRow(r.GetInt64(0), r.GetInt32(1), r.GetInt32(2), r.GetInt32(3),
                r.GetString(4), r.GetString(5), r.GetString(6), r.GetInt32(7) != 0,
                r.IsDBNull(8) ? null : r.GetInt32(8), r.IsDBNull(9) ? null : r.GetInt32(9)));
        return list;
    }

    public int LeagueOf(int teamId, int seasonId)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT league_id FROM fixtures WHERE season_id=$s AND kind='league' " +
                          "AND (home_team_id=$t OR away_team_id=$t) LIMIT 1";
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$s", seasonId);
        return cmd.ExecuteScalar() is long l ? (int)l : 0;
    }

    /// <summary>League table computed from played fixtures + results.</summary>
    public List<TableRow> LeagueTable(int leagueId, int seasonId)
    {
        var rows = new Dictionary<int, TableRow>();
        using var con = Open();
        using (var teams = con.CreateCommand())
        {
            teams.CommandText =
                "SELECT DISTINCT t.id, t.name FROM fixtures f JOIN teams t " +
                "ON t.id=f.home_team_id OR t.id=f.away_team_id " +
                "WHERE f.season_id=$s AND f.league_id=$l AND f.kind='league'";
            teams.Parameters.AddWithValue("$l", leagueId);
            teams.Parameters.AddWithValue("$s", seasonId);
            using var r = teams.ExecuteReader();
            while (r.Read()) rows[r.GetInt32(0)] = new TableRow(r.GetInt32(0), r.GetString(1));
        }
        using (var res = con.CreateCommand())
        {
            res.CommandText =
                "SELECT f.home_team_id, f.away_team_id, r.home_goals, r.away_goals " +
                "FROM fixtures f JOIN results r ON r.fixture_id=f.id " +
                "WHERE f.season_id=$s AND f.league_id=$l AND f.kind='league'";
            res.Parameters.AddWithValue("$l", leagueId);
            res.Parameters.AddWithValue("$s", seasonId);
            using var r = res.ExecuteReader();
            while (r.Read())
            {
                var (h, a, hg, ag) = (r.GetInt32(0), r.GetInt32(1), r.GetInt32(2), r.GetInt32(3));
                if (rows.TryGetValue(h, out var hr)) hr.Add(hg, ag);
                if (rows.TryGetValue(a, out var ar)) ar.Add(ag, hg);
            }
        }
        return rows.Values.OrderByDescending(t => t.Pts).ThenByDescending(t => t.Gd)
            .ThenByDescending(t => t.Gf).ThenBy(t => t.Name).ToList();
    }

    public List<InboxRow> Inbox(int seasonId)
    {
        var list = new List<InboxRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT id, category, subject, body, is_read, requires_action, matchday " +
                          "FROM inbox WHERE season_id=$s ORDER BY id DESC";
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(new InboxRow(r.GetInt64(0), r.GetString(1), r.GetString(2), r.GetString(3),
                r.GetInt32(4) != 0, r.GetInt32(5) != 0, r.IsDBNull(6) ? null : r.GetInt32(6)));
        return list;
    }

    public int UnreadCount(int seasonId)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM inbox WHERE season_id=$s AND is_read=0";
        cmd.Parameters.AddWithValue("$s", seasonId);
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    public void MarkRead(long inboxId)
    {
        using var con = OpenWrite();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "UPDATE inbox SET is_read=1 WHERE id=$i";
        cmd.Parameters.AddWithValue("$i", inboxId);
        cmd.ExecuteNonQuery();
    }

    public List<ObjectiveRow> Objectives(int teamId, int seasonId)
    {
        var list = new List<ObjectiveRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT kind, target, importance, status FROM objectives " +
                          "WHERE team_id=$t AND season_id=$s ORDER BY " +
                          "CASE importance WHEN 'critical' THEN 0 WHEN 'important' THEN 1 ELSE 2 END";
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(new ObjectiveRow(r.GetString(0), r.GetInt32(1), r.GetString(2), r.GetInt32(3)));
        return list;
    }

    public (int Confidence, string Expectation)? Board(int teamId, int seasonId)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT confidence, expectation FROM board_confidence WHERE team_id=$t AND season_id=$s";
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$s", seasonId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? (r.GetInt32(0), r.GetString(1)) : null;
    }

    public int? MoraleAvg(int teamId)
    {
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT CAST(AVG(m.value) AS INT) FROM morale m " +
                          "JOIN squad_members s ON s.player_id=m.player_id WHERE s.team_id=$t";
        cmd.Parameters.AddWithValue("$t", teamId);
        return cmd.ExecuteScalar() is long v ? (int)v : null;
    }

    public List<StaffRow> Staff(int teamId)
    {
        var list = new List<StaffRow>();
        using var con = Open();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT role, name, quality, wage FROM staff WHERE team_id=$t ORDER BY wage DESC";
        cmd.Parameters.AddWithValue("$t", teamId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) list.Add(new StaffRow(r.GetString(0), r.GetString(1), r.GetInt32(2), r.GetInt32(3)));
        return list;
    }

    public (long Budget, long Income, long Spend) Finances(int teamId, int seasonId)
    {
        using var con = Open();
        long budget = 0;
        using (var cmd = con.CreateCommand())
        {
            cmd.CommandText = "SELECT COALESCE(budget,0) FROM teams WHERE id=$t";
            cmd.Parameters.AddWithValue("$t", teamId);
            budget = Convert.ToInt64(cmd.ExecuteScalar() ?? 0L);
        }
        long income = long.TryParse(Meta($"fin_income_{seasonId}"), out var i) ? i : 0;
        long spend = long.TryParse(Meta($"fin_spend_{seasonId}"), out var s) ? s : 0;
        return (budget, income, spend);
    }

    /// <summary>Persist a player's out-of-possession (defending) playstyle choice.</summary>
    public void SetSecondaryPlaystyle(long playerId, string name)
    {
        using var con = OpenWrite();
        using var cmd = con.CreateCommand();
        cmd.CommandText = "INSERT OR REPLACE INTO player_playstyles(player_id,kind,playstyle) VALUES($p,'secondary',$s)";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$s", name);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Record a played result (career writeback: results + fixtures.played).</summary>
    public void RecordResult(long fixtureId, int homeGoals, int awayGoals)
    {
        using var con = OpenWrite();
        using var tx = con.BeginTransaction();
        using (var cmd = con.CreateCommand())
        {
            cmd.CommandText = "INSERT OR REPLACE INTO results(fixture_id,home_goals,away_goals) VALUES($f,$h,$a)";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            cmd.Parameters.AddWithValue("$h", homeGoals);
            cmd.Parameters.AddWithValue("$a", awayGoals);
            cmd.ExecuteNonQuery();
        }
        using (var cmd = con.CreateCommand())
        {
            cmd.CommandText = "UPDATE fixtures SET played=1 WHERE id=$f";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            cmd.ExecuteNonQuery();
        }
        tx.Commit();
    }

    /// <summary>A face PNG as a data URI, or null if the file isn't extracted yet.</summary>
    public string? FaceDataUri(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) return null;
        try
        {
            var bytes = File.ReadAllBytes(path);
            return "data:image/png;base64," + Convert.ToBase64String(bytes);
        }
        catch { return null; }
    }
}

public record TeamRow(int Id, string Name, int SquadSize);

public record CareerContext(int TeamId, string TeamName, int SeasonId, string Manager, string Chairman);

public record FixtureRow(long Id, int Matchday, int HomeId, int AwayId, string Home, string Away,
    string Kind, bool Played, int? HomeGoals, int? AwayGoals);

public record InboxRow(long Id, string Category, string Subject, string Body, bool IsRead,
    bool RequiresAction, int? Matchday);

public record ObjectiveRow(string Kind, int Target, string Importance, int Status);

public record StaffRow(string Role, string Name, int Quality, int Wage);

public class TableRow
{
    public TableRow(int id, string name) { Id = id; Name = name; }
    public int Id { get; }
    public string Name { get; }
    public int P { get; private set; }
    public int W { get; private set; }
    public int D { get; private set; }
    public int L { get; private set; }
    public int Gf { get; private set; }
    public int Ga { get; private set; }
    public int Gd => Gf - Ga;
    public int Pts => W * 3 + D;
    public void Add(int gf, int ga)
    {
        P++; Gf += gf; Ga += ga;
        if (gf > ga) W++; else if (gf == ga) D++; else L++;
    }
}

public record MarketRow(long Id, string Name, string Position, int Age, int Rating,
    string? FacePath, string Club)
{
    public string Unit => Position.ToUpperInvariant() switch
    {
        "GK" => "GK",
        "CB" or "LB" or "RB" or "LWB" or "RWB" => "DEF",
        "DMF" or "CMF" or "LMF" or "RMF" or "AMF" => "MID",
        _ => "FWD",
    };
}

public record PlayerBio(long Id, string Name, string Position, string Nationality, int Age,
    int HeightCm, int WeightKg, int Overall, string? FacePath);

public record PlayerRow(long Id, string Name, string Position, int Age, int Rating,
    string? FacePath, int Slot, int Shirt)
{
    public bool IsStarter => Slot is >= 0 and <= 10;
    public string Unit => Position.ToUpperInvariant() switch
    {
        "GK" => "GK",
        "CB" or "LB" or "RB" or "LWB" or "RWB" => "DEF",
        "DMF" or "CMF" or "LMF" or "RMF" or "AMF" or "DM" or "CM" or "LM" or "RM" or "AM" => "MID",
        _ => "FWD",
    };
}
