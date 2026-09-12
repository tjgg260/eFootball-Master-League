namespace ML.App;

/// <summary>
/// Cheap per-entity identity lookups the shared context menu and focused navigation lean on.
/// Pure ADO — no Avalonia — but deliberately NOT in ML.Web's engine include list; nothing
/// web-side calls these.
/// </summary>
public sealed partial class Session
{
    /// <summary>
    /// The club currently holding a player, or (null, "Free agent"). The side is reported as it
    /// really is — "AFC Bournemouth U21", not the senior club — because that is what the screen
    /// should say. Ownership is a separate question: see <see cref="IsOwnPlayer"/>.
    /// </summary>
    public (int? TeamId, string Club) ClubOfPlayer(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT sm.team_id, t.name FROM squad_members sm " +
                          "JOIN teams t ON t.id = sm.team_id WHERE sm.player_id=$p LIMIT 1";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? (r.GetInt32(0), r.GetString(1)) : (null, "Free agent");
    }

    /// <summary>The senior club a side answers to: itself, or its parent for a U21/U18 team.</summary>
    public int? ParentClubOf(int teamId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT COALESCE(parent_team_id, id) FROM teams WHERE id=$t";
        cmd.Parameters.AddWithValue("$t", teamId);
        var v = cmd.ExecuteScalar();
        return v is null or DBNull ? null : Convert.ToInt32(v);
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

    /// <summary>
    /// Is he yours? Yes for the first team AND for your own U21/U18 sides.
    ///
    /// THE BUG this shape exists to prevent: this used to compare squad_members.team_id straight
    /// against CurrentTeamId. A player in your own U21s sits in team 9,000,014, not 800,007, so
    /// "own" came back FALSE for a lad you already own — and every consumer believed it. The
    /// shared menu offered "Open bidding", "Make enquiry" and "Add to shortlist" for your own
    /// academy graduate, and the Player screen showed him a big Open-bidding button with your
    /// transfer budget under it, inviting you to buy him from yourself. Ownership walks
    /// parent_team_id; it is never the raw side id.
    /// </summary>
    public bool IsOwnPlayer(long playerId)
    {
        var (teamId, _) = ClubOfPlayer(playerId);
        if (teamId is not { } tid) return false;              // free agent
        if (tid == CurrentTeamId) return true;                // first team
        return ParentClubOf(tid) == CurrentTeamId;            // your U21 / U18
    }
}
