namespace ML.App;

/// <summary>
/// The AI manager: before you face a club, it fields its STRONGEST position-correct XI and picks
/// a tactic sized to the matchup — sit deep and counter when it's the underdog, dominate when it's
/// favourite. This replaces "whatever was in slots 0-10" (which could be four keepers) with a real
/// opponent that's trying to beat you.
/// </summary>
public sealed partial class Session
{
    /// <summary>Field the best XI for <paramref name="teamId"/> and set a tactic vs the opponent.</summary>
    public void PickBestXiAndTactic(int teamId, int opponentId)
    {
        PickBestXi(teamId);
        PickTacticVs(teamId, opponentId);
        // The AI now assigns each player an in- and out-of-possession role that fits the tactic it
        // just chose (never touches the human's club — you set your own roles).
        if (teamId != CurrentTeamId)
        {
            try { AssignRolesFor(teamId); } catch { /* roles are additive */ }
        }
    }

    /// <summary>Assign the strongest player to each formation slot (GK to GK, by position + rating).</summary>
    public void PickBestXi(int teamId)
    {
        var fid = Repo.TeamTactics(teamId).FirstOrDefault(t => t.Phase == 0)?.FormationId;
        if (fid is null) return;
        var slots = Repo.FormationSlots(fid.Value).OrderBy(s => s.SlotIndex).ToList();
        if (slots.Count < 11) return;
        var squad = Repo.SquadPlayers(teamId).Where(p => p.OverallRating is not null).ToList();
        if (squad.Count < 11) return;

        // Process the GK slot first so the one keeper is claimed for goal, then outfield slots.
        var order = Enumerable.Range(0, slots.Count)
            .OrderByDescending(i => Visuals.PositionCategory(Visuals.RoleCodeLabel(slots[i].Position)) == "GK" ? 1 : 0)
            .ToList();
        var used = new HashSet<int>();
        var chosen = new int[slots.Count];
        foreach (var i in order)
        {
            var wantLabel = Visuals.RoleCodeLabel(slots[i].Position);
            var wantCat = Visuals.PositionCategory(wantLabel);
            var best = -1;
            var bestScore = int.MinValue;
            foreach (var p in squad)
            {
                if (used.Contains(p.Id)) continue;
                var pCat = Visuals.PositionCategory(p.Position);
                // hard GK rule: keepers only in goal, and goal only takes a keeper
                if ((wantCat == "GK") != (pCat == "GK")) continue;
                var fit = p.Position == wantLabel ? 3000 : pCat == wantCat ? 1500 : 0;
                var score = fit + (p.OverallRating ?? 0);
                if (score > bestScore) { bestScore = score; best = p.Id; }
            }
            if (best < 0) continue;
            used.Add(best);
            chosen[i] = best;
        }

        // Write the chosen XI into slots 0-10; everyone else keeps a bench slot.
        var benchStart = 11;
        var starters = new HashSet<int>(chosen.Where(c => c != 0));
        for (var i = 0; i < slots.Count; i++)
        {
            if (chosen[i] == 0) continue;
            SetSlot(teamId, chosen[i], i);
        }
        foreach (var p in squad)
        {
            if (starters.Contains(p.Id)) continue;
            SetSlot(teamId, p.Id, benchStart++);
        }
    }

    /// <summary>Choose a team style to beat the opponent: underdog counters, favourite dominates.</summary>
    public void PickTacticVs(int teamId, int opponentId)
    {
        var diff = EloOf(teamId) - EloOf(opponentId);
        // 0 Possession · 1 Quick Counter · 2 Long Ball Counter · 3 Long Ball · 4 Out Wide · 5 Overload
        var style = diff switch
        {
            <= -80 => 2,      // clear underdog → sit deep, long-ball counter
            <= -25 => 1,      // slight underdog → quick counter
            >= 80 => 5,       // clear favourite → overload
            >= 25 => 0,       // slight favourite → keep the ball
            _ => 0,           // even → possession
        };
        foreach (var t in Repo.TeamTactics(teamId))
        {
            Repo.SetTeamTactics(t with { Style = style });
        }
    }

    private void SetSlot(int teamId, int playerId, int slot)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE squad_members SET slot=$s WHERE team_id=$t AND player_id=$p";
        cmd.Parameters.AddWithValue("$s", slot);
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.ExecuteNonQuery();
    }
}
