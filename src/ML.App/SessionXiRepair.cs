using Microsoft.Data.Sqlite;
using ML.Core.Selection;

namespace ML.App;

/// <summary>
/// Self-heals invalid starting XIs at load. A progression bug can leave a club with several
/// goalkeepers in its eleven (slots 0-10); for every such club this puts one keeper in goal and
/// swaps each surplus keeper out for the substitute who best fits the slot he was standing in.
/// One transaction for the whole world, never behind the manager's own hand-picked sheet, and
/// the pass says what it did (a meta record plus a letter). Idempotent and convergent: a club
/// this cannot improve is not selected again.
/// </summary>
public sealed partial class Session
{
    /// <summary>Meta key holding what the last XI repair did (date|clubs touched).</summary>
    private const string XiRepairKey = "xi_repair_v1";

    // A squad member as the repair sees him. Pid is a long: most of this world's squad rows sit
    // above Int32.MaxValue, and reading them narrower is exactly the bug that neutered this pass.
    private sealed record XiMember(long Pid, int Slot, string Name, string Position, int Rating);

    // One club's repair, planned in memory before a byte is written: every slot change with the
    // slot it came from (so a miss can be undone), whether a keeper had to be moved INTO goal,
    // the moves in a manager's words (only built for his own club), and the face for his letter.
    private sealed record XiRepairPlan(
        List<(long Pid, int From, int To)> Moves, bool KeeperMovedIntoGoal, List<string> Lines, long? Face);

    public void RepairInvalidXis()
    {
        // WHAT THE BUG WAS. This pass read player ids with GetInt32 — in Microsoft.Data.Sqlite an
        // UNCHECKED cast of the int64 column — so for the 304,437 of the world's 337,407 squad
        // rows above Int32.MaxValue it handed SwapSlots ids that belong to nobody. A sibling lane
        // widened the read to GetInt64 and the pass applied for the first time. Measured over the
        // live world at that moment: 18,837 clubs matched the "not exactly one keeper" query;
        // 14,945 of them have NO keeper in the eleven and were skipped; 2,542 were written —
        // 3,093 swaps, 6,186 UPDATEs, in 3,093 separate transactions, inside the constructor,
        // with nothing on screen to say so and the managed club swept up with the rest.
        //
        // AND THE RULE WAS WRONG. It kept the best-RATED keeper wherever he happened to stand and
        // swapped the others for the best-RATED bench outfielder, with no reference to the slot
        // being filled. In 2,007 of those 2,542 clubs the man in the GK slot was an outfielder
        // with the keepers standing at centre-back; in 2,268 the best keeper was not in goal. The
        // old rule left an outfielder in goal in most of them, and the query then read "exactly
        // one keeper" — repaired on paper, wrong on the pitch.
        //
        // NOW: the keeper standing in the GK slot keeps his place; if an outfielder (or nobody)
        // is in goal, the best keeper goes in and the man he displaces joins the candidates;
        // every other keeper in the eleven comes out for whichever candidate best fits THAT
        // slot's role — natural fit first, then his overall at that position — the same rule the
        // Tactics screen uses for substitute cover. Re-measured with this rule: 3,462 clubs,
        // 13,359 slot writes, one transaction; 2,927 keepers moved into goal; 953 clubs keep a
        // surplus keeper because they have nobody left to swap in, and the pre-filter below
        // drops those next launch. Each launch strictly shrinks the set; a clean world costs one
        // aggregate query.
        var broken = new List<int>();
        using (var q = Db.Connection.CreateCommand())
        {
            // Only clubs the pass can improve: more than one keeper in the eleven AND either an
            // outfielder on the bench to bring on, or an outfielder standing in goal to swap out.
            // Slot 0 stands in for the GK slot here — every formation in the world puts it there
            // — and the plan re-checks against the club's real shape before anything moves.
            q.CommandText =
                "SELECT s.team_id FROM squad_members s JOIN players p ON p.id=s.player_id " +
                "GROUP BY s.team_id " +
                "HAVING SUM(CASE WHEN s.slot BETWEEN 0 AND 10 AND p.position='GK' THEN 1 ELSE 0 END) > 1 " +
                "AND (SUM(CASE WHEN s.slot > 10 AND p.position<>'GK' THEN 1 ELSE 0 END) > 0 " +
                "     OR SUM(CASE WHEN s.slot = 0 AND p.position<>'GK' THEN 1 ELSE 0 END) > 0)";
            using var r = q.ExecuteReader();
            // Team ids are legitimately int: the largest club id in the world is 4,032,815, far
            // inside Int32. Player ids are NOT — never copy this GetInt32 onto a player id.
            while (r.Read()) broken.Add(r.GetInt32(0));
        }
        if (broken.Count == 0) return;

        // Plan every club first, then write. Reads go through Dapper and plain commands alike,
        // and Microsoft.Data.Sqlite refuses any command without a Transaction while one is
        // pending on the connection — so nothing is opened until the plans are in hand.
        var manual = ManualXi;   // one meta read, not one per club
        var plans = new List<(int TeamId, XiRepairPlan Plan)>();
        foreach (var tid in broken)
        {
            // Never behind a hand-picked team sheet: a manager who saved his own eleven keeps
            // it, keepers and all — that is his call to make on the Tactics screen.
            if (tid == CurrentTeamId && manual) continue;
            var plan = PlanXiRepair(tid, describe: tid == CurrentTeamId);
            if (plan is not null && plan.Moves.Count > 0) plans.Add((tid, plan));
        }
        if (plans.Count == 0) return;

        var touched = 0;
        var goalWasEmpty = 0;
        XiRepairPlan? mine = null;
        using (var tx = Db.Connection.BeginTransaction())
        {
            foreach (var (tid, plan) in plans)
            {
                if (!ApplyXiMoves(tx, tid, plan)) continue;
                touched++;
                if (plan.KeeperMovedIntoGoal) goalWasEmpty++;
                if (tid == CurrentTeamId) mine = plan;
            }
            tx.Commit();
        }
        if (touched > 0) RecordXiRepair(touched, goalWasEmpty, mine);
    }

    /// <summary>
    /// Work out one club's repair without writing anything. Null when the club is not ours to
    /// touch: no keeper in its shape, fewer than two keepers in the eleven after all, two men
    /// already sharing an XI slot, or a plan whose slot accounting does not close.
    /// </summary>
    private XiRepairPlan? PlanXiRepair(int teamId, bool describe)
    {
        var labels = SlotLabelsOf(teamId);
        var g = labels.IndexOf("GK");
        if (g < 0) return null;   // a shape with no keeper is not ours to judge

        var squad = new List<XiMember>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText =
                "SELECT s.slot, s.player_id, COALESCE(p.name,''), COALESCE(p.position,''), " +
                "COALESCE(p.overall_rating,0) " +
                "FROM squad_members s JOIN players p ON p.id=s.player_id WHERE s.team_id=$t";
            q.Parameters.AddWithValue("$t", teamId);
            using var r = q.ExecuteReader();
            while (r.Read())
            {
                squad.Add(new XiMember(r.GetInt64(1), r.GetInt32(0), r.GetString(2), r.GetString(3), r.GetInt32(4)));
            }
        }

        // The eleven by slot. Two men in one XI slot is a squad in a state this pass does not
        // understand — leave it for a human rather than guess which of them is standing there.
        var xi = new Dictionary<int, XiMember>();
        foreach (var m in squad.Where(m => m.Slot is >= 0 and <= 10))
        {
            if (!xi.TryAdd(m.Slot, m)) return null;
        }
        var keepers = xi.Values.Where(m => m.Position == "GK").ToList();
        if (keepers.Count < 2) return null;

        // Who keeps goal: the man already there if he can, else the best keeper, who moves in —
        // and whoever he displaces becomes a candidate for an outfield slot like anyone else.
        XiMember goalie;
        XiMember? displaced = null;
        if (xi.TryGetValue(g, out var inGoal) && inGoal.Position == "GK")
        {
            goalie = inGoal;
        }
        else
        {
            goalie = keepers.OrderByDescending(k => k.Rating).ThenBy(k => k.Pid).First();
            displaced = xi.GetValueOrDefault(g);   // null when the slot simply stands empty
        }

        // Outfield slots with a keeper standing in them. The goalie's own slot is filled FIRST
        // when he is moving into goal: the displaced man is always a candidate, so that slot can
        // never be left empty behind him — which is what keeps the slot accounting below whole.
        var toFill = keepers.Where(k => k.Slot != g && k.Pid != goalie.Pid)
            .Select(k => k.Slot).OrderBy(s => s).ToList();
        if (goalie.Slot != g) toFill.Insert(0, goalie.Slot);

        var candidates = squad.Where(m => m.Slot > 10 && m.Position != "GK").ToList();
        if (displaced is not null) candidates.Add(displaced);
        var attrs = AttributesOf(candidates.Select(c => c.Pid));
        var learned = LearnedPositionsOf(candidates.Select(c => c.Pid));
        IReadOnlyCollection<string> LearnedOf(long pid) =>
            learned.TryGetValue(pid, out var l) ? l : Array.Empty<string>();

        var moves = new List<(long Pid, int From, int To)>();
        var lines = new List<string>();
        if (goalie.Slot != g)
        {
            moves.Add((goalie.Pid, goalie.Slot, g));
            if (describe) lines.Add($"{goalie.Name} goes in goal.");
        }

        var freedBench = new List<int>();
        var leaving = new List<XiMember>();
        foreach (var slot in toFill)
        {
            if (candidates.Count == 0) break;   // nobody left to bring on: the rest stay, for now
            var label = labels[slot];
            // The slot's role chooses the man: a natural fit beats a same-unit stand-in beats
            // anyone else, and within a band his overall AT THAT POSITION (his abilities scored
            // the way the pitch grades them), then raw rating, then id so the pick is stable.
            var best = candidates
                .OrderBy(c => (int)PositionFit.Of(c.Position, LearnedOf(c.Pid), label))
                .ThenByDescending(c => PositionOverall.Of(attrs.GetValueOrDefault(c.Pid), label) ?? c.Rating)
                .ThenByDescending(c => c.Rating)
                .ThenBy(c => c.Pid)
                .First();
            candidates.Remove(best);
            moves.Add((best.Pid, best.Slot, slot));
            if (best.Slot > 10) freedBench.Add(best.Slot);
            var outgoing = xi[slot];
            if (outgoing.Pid != goalie.Pid) leaving.Add(outgoing);
            if (describe)
            {
                lines.Add(outgoing.Pid == goalie.Pid
                    ? $"{best.Name} takes the {label} slot he leaves."
                    : $"{outgoing.Name} comes out of the {label} slot; {best.Name} takes it.");
            }
        }
        if (displaced is { } benched && moves.All(m => m.Pid != benched.Pid))
        {
            leaving.Add(benched);
            if (describe) lines.Add($"{benched.Name} drops to the bench.");
        }

        // Slot accounting: every man leaving the eleven takes a bench slot a substitute vacated.
        // Filling the goalie's old slot first is what makes this hold; if it ever does not, do
        // nothing to this club rather than write a sheet with two men in one slot.
        if (leaving.Count > freedBench.Count) return null;
        freedBench.Sort();
        for (var i = 0; i < leaving.Count; i++) moves.Add((leaving[i].Pid, leaving[i].Slot, freedBench[i]));

        // And prove it before handing the plan back: the finished squad holds one man per slot.
        var final = squad.ToDictionary(m => m.Pid, m => m.Slot);
        foreach (var (pid, _, to) in moves) final[pid] = to;
        if (final.Values.Distinct().Count() != final.Count) return null;

        var face = leaving.FirstOrDefault(m => m.Position == "GK")?.Pid;
        return new XiRepairPlan(moves, goalie.Slot != g, lines, face);
    }

    /// <summary>
    /// The role label of each of a club's eleven slots: its own Main formation when it has a
    /// readable one, else the same 4-4-2 the formation heal falls back to. On the live world
    /// only a dozen of the clubs this pass touches own a formation at all.
    /// </summary>
    private List<string> SlotLabelsOf(int teamId)
    {
        var (fid0, _) = OwnFormationIds(teamId);
        var own = fid0 > 0 ? Repo.FormationSlots(fid0) : null;
        if (own is { Count: 11 }
            && own.All(s => s.SlotIndex is >= 0 and <= 10)
            && own.Select(s => s.SlotIndex).Distinct().Count() == 11)
        {
            var labels = new string[11];
            foreach (var s in own) labels[s.SlotIndex] = Visuals.RoleCodeLabel(s.Position);
            return labels.ToList();
        }
        return Default442.Select(s => Visuals.RoleCodeLabel(s.Role)).ToList();
    }

    /// <summary>The 26 abilities of each listed player, one read for the lot.</summary>
    private Dictionary<long, Dictionary<string, int>> AttributesOf(IEnumerable<long> playerIds)
    {
        var ids = playerIds.Distinct().ToList();
        var result = new Dictionary<long, Dictionary<string, int>>();
        if (ids.Count == 0) return result;
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT player_id, attribute, value FROM player_attributes WHERE player_id IN (" +
                        string.Join(",", ids.Select((_, i) => $"$p{i}")) + ")";
        for (var i = 0; i < ids.Count; i++) q.Parameters.AddWithValue($"$p{i}", ids[i]);
        using var r = q.ExecuteReader();
        while (r.Read())
        {
            var pid = r.GetInt64(0);
            if (!result.TryGetValue(pid, out var abilities)) result[pid] = abilities = new();
            abilities[r.GetString(1)] = r.GetInt32(2);
        }
        return result;
    }

    /// <summary>Positions each listed player has trained into, one read for the lot.</summary>
    private Dictionary<long, List<string>> LearnedPositionsOf(IEnumerable<long> playerIds)
    {
        var ids = playerIds.Distinct().ToList();
        var result = new Dictionary<long, List<string>>();
        if (ids.Count == 0) return result;
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT player_id, position FROM player_positions WHERE player_id IN (" +
                        string.Join(",", ids.Select((_, i) => $"$p{i}")) + ")";
        for (var i = 0; i < ids.Count; i++) q.Parameters.AddWithValue($"$p{i}", ids[i]);
        using var r = q.ExecuteReader();
        while (r.Read())
        {
            var pid = r.GetInt64(0);
            if (!result.TryGetValue(pid, out var list)) result[pid] = list = new();
            list.Add(r.GetString(1));
        }
        return result;
    }

    /// <summary>
    /// Write one club's plan inside the pass-wide transaction. Half a repair is worse than none
    /// — it doubles up one slot and empties another — so a row that is not there to update undoes
    /// this club's moves so far and leaves it be; the rest of the world still commits.
    /// </summary>
    private bool ApplyXiMoves(SqliteTransaction tx, int teamId, XiRepairPlan plan)
    {
        var applied = new List<(long Pid, int From)>();
        foreach (var (pid, fromSlot, toSlot) in plan.Moves)
        {
            if (MoveToSlot(tx, teamId, pid, toSlot) == 1)
            {
                applied.Add((pid, fromSlot));
                continue;
            }
            foreach (var (p, f) in applied) MoveToSlot(tx, teamId, p, f);
            return false;
        }
        return true;
    }

    // Returns the row count so the caller can tell a landed move from a miss. Distinct from the
    // AI selector's autocommit SetSlot: this one rides the pass-wide transaction.
    private int MoveToSlot(SqliteTransaction tx, int teamId, long playerId, int slot)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.Transaction = tx;   // Microsoft.Data.Sqlite requires it while a transaction is pending
        cmd.CommandText = "UPDATE squad_members SET slot=$s WHERE team_id=$t AND player_id=$p";
        cmd.Parameters.AddWithValue("$s", slot);
        cmd.Parameters.AddWithValue("$t", teamId);
        cmd.Parameters.AddWithValue("$p", playerId);
        return cmd.ExecuteNonQuery();
    }

    /// <summary>
    /// Leave a trace of a repair the manager did not ask for, the way the youth repair does: the
    /// meta record goes down FIRST (a screen can explain a changed sheet even if the letter
    /// fails), then one letter the first time the pass ever fires — never repeated — and a letter
    /// naming the players every time it is HIS side that was put right.
    /// </summary>
    private void RecordXiRepair(int clubs, int goalWasEmpty, XiRepairPlan? mine)
    {
        var firstTime = GetMeta(XiRepairKey) is null;
        SetMeta(XiRepairKey, $"{DateTime.Now:yyyy-MM-dd}|{clubs}");
        if (firstTime)
        {
            var who = clubs == 1 ? "One club" : $"{clubs} clubs";
            var were = clubs == 1 ? "was" : "were";
            var goal = goalWasEmpty == 0 ? "" :
                goalWasEmpty == 1
                    ? " One of them had nobody who could keep goal standing in the goalkeeper's place, with the keepers out in the back line."
                    : $" {goalWasEmpty} of them had nobody who could keep goal standing in the goalkeeper's place, with the keepers out in the back line.";
            var yours = mine is null ? "" : " Yours was among them — the letter beside this one names the players.";
            PostInbox("Club", "Team sheets around the world have been put right",
                $"{who} around the world {were} fielding more than one goalkeeper.{goal} Nobody had " +
                "picked those sides: the sheets were squad lists in the order they arrived.\n\n" +
                "Each has been put right: one keeper in goal, and every surplus keeper swapped for the " +
                "substitute who best fits the slot he was standing in. Nothing else has moved — the " +
                "same squads, the same shirt numbers, only the team sheet.\n\n" +
                "Your own eleven is never touched once you have picked and saved a team of your own on " +
                $"the Tactics screen.{yours}");
        }
        if (mine is not null)
        {
            PostInbox("Club", "Your team sheet has been tidied",
                "Your eleven had more than one goalkeeper in it, so the assistant has stepped in:\n" +
                string.Join("\n", mine.Lines.Select(l => $"• {l}")) +
                "\n\nNothing else has moved. Pick and save a team of your own on the Tactics screen and " +
                "it will not be touched again.",
                playerId: mine.Face, teamId: CurrentTeamId);
        }
    }

    /// <summary>
    /// What the last XI repair did, in a sentence, or null if there has never been one. A screen
    /// showing a team sheet the manager does not remember arranging can use this so the change
    /// explains itself.
    /// </summary>
    public string? XiRepairNote()
    {
        var raw = GetMeta(XiRepairKey);
        if (string.IsNullOrEmpty(raw)) return null;
        var parts = raw.Split('|');
        if (parts.Length < 2 || !int.TryParse(parts[1], out var clubs) || clubs <= 0) return null;
        // Stored exact (yyyy-MM-dd), read back exact, shown in the reader's own language.
        var when = DateOnly.TryParseExact(parts[0], "yyyy-MM-dd", out var d)
            ? d.ToString("d MMM yyyy")
            : parts[0];
        return $"Team sheets were put right on {when}: {clubs} " +
               $"{(clubs == 1 ? "club was" : "clubs were")} fielding more than one goalkeeper, and " +
               "each now has one keeper in goal with the surplus swapped for the substitutes who " +
               "best fit their slots.";
    }
}
