namespace ML.App;

/// <summary>
/// Cheap per-entity identity lookups the shared context menu and focused navigation lean on.
/// Pure ADO — no Avalonia — but deliberately NOT in ML.Web's engine include list; nothing
/// web-side calls these.
/// </summary>
public sealed partial class Session
{
    /// <summary>The club currently holding a player, or (null, "Free agent").</summary>
    public (int? TeamId, string Club) ClubOfPlayer(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT sm.team_id, t.name FROM squad_members sm " +
                          "JOIN teams t ON t.id = sm.team_id WHERE sm.player_id=$p LIMIT 1";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? (r.GetInt32(0), r.GetString(1)) : (null, "Free agent");
    }

    public string PlayerNameOf(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT name FROM players WHERE id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        return cmd.ExecuteScalar() as string ?? "";
    }

    public int? PlayerAgeOf(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT age FROM players WHERE id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        var v = cmd.ExecuteScalar();
        return v is null or DBNull ? null : Convert.ToInt32(v);
    }

    public bool IsOwnPlayer(long playerId) => ClubOfPlayer(playerId).TeamId == CurrentTeamId;
}
