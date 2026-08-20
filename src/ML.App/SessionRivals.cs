namespace ML.App;

/// <summary>
/// Rivalries. Konami's Derby.bin pairs are imported into `team_rivals` (tools/derby_import.py);
/// career clubs the data doesn't cover get one synthesized rival — the nearest-ELO club in the
/// same division, mutual, made once and stored. Derby days spike the fan ledger both ways.
/// </summary>
public sealed partial class Session
{
    /// <summary>All rivals of a club, fiercest first.</summary>
    public IReadOnlyList<int> RivalsOf(int teamId)
    {
        EnsureRival(teamId);
        var rows = new List<int>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT rival_id FROM team_rivals WHERE team_id=$t ORDER BY intensity";
        cmd.Parameters.AddWithValue("$t", teamId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(r.GetInt32(0));
        return rows;
    }

    public bool IsDerby(int homeId, int awayId) =>
        RivalsOf(homeId).Contains(awayId);

    /// <summary>Rival name for the given club, or null if the world genuinely has none.</summary>
    public string? RivalNameOf(int teamId)
    {
        var rivals = RivalsOf(teamId);
        return rivals.Count == 0 ? null : TeamName(rivals[0]);
    }

    /// <summary>Give an uncovered club one mutual rival: nearest ELO in its own division.</summary>
    private void EnsureRival(int teamId)
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT 1 FROM team_rivals WHERE team_id=$t LIMIT 1";
            q.Parameters.AddWithValue("$t", teamId);
            if (q.ExecuteScalar() is not null) return;
        }
        var me = Repo.Teams().FirstOrDefault(t => t.Id == teamId);
        if (me is null) return;
        var rival = Repo.Teams()
            .Where(t => t.LeagueId == me.LeagueId && t.Id != teamId)
            .OrderBy(t => Math.Abs(EloOf(t.Id) - EloOf(teamId)))
            .ThenBy(t => t.Id)
            .FirstOrDefault();
        if (rival is null) return;
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT OR IGNORE INTO team_rivals(team_id, rival_id, intensity) " +
                          "VALUES ($a,$b,1), ($b,$a,1)";
        cmd.Parameters.AddWithValue("$a", teamId);
        cmd.Parameters.AddWithValue("$b", rival.Id);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Derby swing on top of the normal fan movement — beating your rival is remembered.</summary>
    public void ApplyDerbySwing(int homeId, int awayId, int homeGoals, int awayGoals)
    {
        if (!IsDerby(homeId, awayId)) return;
        var home = homeId == CurrentTeamId;
        if (!home && awayId != CurrentTeamId) return;
        var us = home ? homeGoals : awayGoals;
        var them = home ? awayGoals : homeGoals;
        if (us > them)
        {
            FanLedger += 8;
            PostInbox("Fans", "Derby day belongs to us",
                $"The fans will sing about this one for months — a {us}-{them} derby win over " +
                $"{TeamName(home ? awayId : homeId)}.");
        }
        else if (us < them)
        {
            FanLedger -= 8;
            PostInbox("Fans", "Derby defeat cuts deep",
                $"Losing {us}-{them} to {TeamName(home ? awayId : homeId)} is the kind of result " +
                "supporters don't forgive quickly.");
        }
    }
}
