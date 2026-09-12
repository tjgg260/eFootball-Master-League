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
        // Team ids are legitimately int: the largest club id in the world is 4,032,815, far inside
        // Int32. Player ids are NOT — leave this GetInt32 alone, and never copy it onto a player id.
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
        // THE BUG: player ids were read with GetInt32, which in Microsoft.Data.Sqlite is an
        // UNCHECKED cast of the int64 column — it truncates in silence. 304,437 of the world's
        // 337,407 squad rows sit above Int32.MaxValue, so the repair was handing SwapSlots ids
        // that belong to nobody. Simulated over the live world that was 3,093 swaps: 2,854 did
        // nothing, 98 were right by luck (both ids happened to be small), and 141 landed exactly
        // ONE of the two UPDATEs — moving a keeper onto a bench slot that was still occupied and
        // leaving his XI slot empty. Every launch, on the user's real career. Slot is an int
        // (max 135 in the world) and the rating is 0-99; only the id needed widening.
        var xiGks = new List<(long Pid, int Slot, int Rating)>();      // keepers in the XI
        var benchOutfield = new List<(long Pid, int Slot, int Rating)>();
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
                var pid = r.GetInt64(1);
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

    private void SwapSlots(int teamId, long pidA, int slotA, long pidB, int slotB)
    {
        // Half a swap is worse than no swap: it doubles up one slot and empties another. The two
        // UPDATEs used to run in autocommit, so a miss on either side committed the other on its
        // own. One transaction, and a changes() check, so the pair is all-or-nothing.
        using var tx = Db.Connection.BeginTransaction();
        var moved = 0;
        foreach (var (pid, slot) in new[] { (pidA, slotB), (pidB, slotA) })
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.Transaction = tx;
            cmd.CommandText = "UPDATE squad_members SET slot=$s WHERE team_id=$t AND player_id=$p";
            cmd.Parameters.AddWithValue("$t", teamId);
            cmd.Parameters.AddWithValue("$p", pid);
            cmd.Parameters.AddWithValue("$s", slot);
            moved += cmd.ExecuteNonQuery();
        }
        if (moved == 2) tx.Commit();
        else tx.Rollback();   // one side missed — put the squad back rather than half-move it
    }
}
