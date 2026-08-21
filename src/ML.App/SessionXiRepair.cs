namespace ML.App;

/// <summary>
/// Self-heals invalid starting XIs. A progression bug can leave a club with several goalkeepers
/// in its XI (slots 0-10); this runs at load and, for any club that doesn't have exactly one GK
/// starting, swaps the surplus keepers out for its best available outfield subs. Idempotent.
/// </summary>
public sealed partial class Session
{
    public void RepairInvalidXis()
    {
        var broken = new List<int>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText =
                "SELECT s.team_id FROM squad_members s JOIN players p ON p.id=s.player_id " +
                "WHERE s.slot BETWEEN 0 AND 10 GROUP BY s.team_id " +
                "HAVING SUM(CASE WHEN p.position='GK' THEN 1 ELSE 0 END) <> 1";
            using var r = q.ExecuteReader();
            while (r.Read()) broken.Add(r.GetInt32(0));
        }
        foreach (var tid in broken) RepairTeamXi(tid);
    }

    private void RepairTeamXi(int teamId)
    {
        var xiGks = new List<(int Pid, int Slot, int Rating)>();      // keepers in the XI
        var benchOutfield = new List<(int Pid, int Slot, int Rating)>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText =
                "SELECT s.slot, s.player_id, p.position, COALESCE(p.overall_rating,0) " +
                "FROM squad_members s JOIN players p ON p.id=s.player_id WHERE s.team_id=$t";
            q.Parameters.AddWithValue("$t", teamId);
            using var r = q.ExecuteReader();
            while (r.Read())
            {
                var slot = r.GetInt32(0);
                var pid = r.GetInt32(1);
                var gk = r.GetString(2) == "GK";
                var rating = r.GetInt32(3);
                if (slot is >= 0 and <= 10 && gk) xiGks.Add((pid, slot, rating));
                else if (slot > 10 && !gk) benchOutfield.Add((pid, slot, rating));
            }
        }
        // keep the best keeper starting; swap each surplus keeper with the best bench outfielder
        var surplus = xiGks.OrderByDescending(g => g.Rating).Skip(1).ToList();
        var repls = benchOutfield.OrderByDescending(o => o.Rating).ToList();
        for (var i = 0; i < surplus.Count && i < repls.Count; i++)
        {
            SwapSlots(teamId, surplus[i].Pid, surplus[i].Slot, repls[i].Pid, repls[i].Slot);
        }
    }

    private void SwapSlots(int teamId, int pidA, int slotA, int pidB, int slotB)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "UPDATE squad_members SET slot=$sb WHERE team_id=$t AND player_id=$pa;" +
            "UPDATE squad_members SET slot=$sa WHERE team_id=$t AND player_id=$pb;";
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$pa", pidA);
        cmd.Parameters.AddWithValue("$pb", pidB);
        cmd.Parameters.AddWithValue("$sa", slotA);
        cmd.Parameters.AddWithValue("$sb", slotB);
        cmd.ExecuteNonQuery();
    }
}
