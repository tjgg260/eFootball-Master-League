using ML.Core.Tactics;

namespace ML.App;

/// <summary>
/// Player role assignment (parity with ML.Web + the AI request): every player gets an in-possession
/// and an out-of-possession role from the shared <see cref="RoleCatalog"/>, chosen by attribute fit
/// AND the team's chosen playstyle. The AI runs this for its clubs when it sets a tactic, so a
/// Possession side lines up with orchestrators/pressers and a Counter side with pace/outlets. Both
/// roles compile into Player.bin on install (play_match.py reads both kinds).
/// </summary>
public sealed partial class Session
{
    /// <summary>The team's chosen in-possession style (0-5), or null if unset.</summary>
    private int? TeamStyleOf(int teamId)
    {
        try
        {
            using var q = Db.Connection.CreateCommand();
            q.CommandText = "SELECT style FROM team_tactics WHERE team_id=$t AND phase=0 LIMIT 1";
            q.Parameters.AddWithValue("$t", teamId);
            var v = q.ExecuteScalar();
            return v is null or DBNull ? null : Convert.ToInt32(v);
        }
        catch { return null; }
    }

    /// <summary>Assign both roles to every player in a team, fitting attributes + the chosen style.
    /// Overwrites — call it whenever the tactic changes.</summary>
    public void AssignRolesFor(int teamId)
    {
        var style = TeamStyleOf(teamId);
        var players = Repo.SquadPlayers(teamId)
            .Where(p => !string.IsNullOrWhiteSpace(p.Position)).ToList();
        if (players.Count == 0) return;
        var ab = LoadAbilitiesFor(players.Select(p => p.Id).ToList());

        using var tx = Db.Connection.BeginTransaction();
        foreach (var p in players)
        {
            var pos = p.Position!.ToUpperInvariant();
            var a = ab.GetValueOrDefault(p.Id) ?? new Dictionary<string, int>();
            Write(tx, p.Id, "primary", RoleCatalog.BestPrimary(pos, a, style));
            Write(tx, p.Id, "secondary", RoleCatalog.BestSecondary(pos, a, style));
        }
        tx.Commit();

        void Write(Microsoft.Data.Sqlite.SqliteTransaction t, int pid, string kind, string? role)
        {
            if (role is null) return;
            using var del = Db.Connection.CreateCommand();
            del.Transaction = t;
            del.CommandText = "DELETE FROM player_playstyles WHERE player_id=$p AND kind=$k";
            del.Parameters.AddWithValue("$p", pid);
            del.Parameters.AddWithValue("$k", kind);
            del.ExecuteNonQuery();
            using var ins = Db.Connection.CreateCommand();
            ins.Transaction = t;
            ins.CommandText = "INSERT OR IGNORE INTO player_playstyles(player_id,playstyle,kind) " +
                              "VALUES($p,$s,$k)";
            ins.Parameters.AddWithValue("$p", pid);
            ins.Parameters.AddWithValue("$s", role);
            ins.Parameters.AddWithValue("$k", kind);
            ins.ExecuteNonQuery();
        }
    }

    private Dictionary<int, Dictionary<string, int>> LoadAbilitiesFor(IReadOnlyList<int> pids)
    {
        var map = new Dictionary<int, Dictionary<string, int>>();
        if (pids.Count == 0) return map;
        var inClause = string.Join(",", pids);
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = $"SELECT player_id, attribute, value FROM player_attributes " +
                          $"WHERE player_id IN ({inClause})";
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var pid = r.GetInt32(0);
            if (!map.TryGetValue(pid, out var m)) map[pid] = m = new Dictionary<string, int>();
            m[r.GetString(1)] = r.GetInt32(2);
        }
        return map;
    }
}
