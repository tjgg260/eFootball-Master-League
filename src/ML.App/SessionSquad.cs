using ML.Core.Selection;
using ML.Data;

namespace ML.App;

/// <summary>
/// Squad-management systems: weekly training (ability groups + learning new positions), manual
/// XI control (the AI only steps in for the injured once you've picked a team), captaincy,
/// releases, the transfer list and visible contracts.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ training

    /// <summary>Ability groups a player can focus on, and the attributes each one trains.</summary>
    public static readonly IReadOnlyDictionary<string, string[]> TrainingGroups =
        new Dictionary<string, string[]>
        {
            ["Shooting"] = new[] { "finishing", "kicking_power", "offensive_awareness", "curl" },
            ["Passing"] = new[] { "low_pass", "lofted_pass", "tight_possession", "set_piece_taking" },
            ["Dribbling"] = new[] { "ball_control", "dribbling", "balance" },
            ["Defending"] = new[] { "defensive_awareness", "tackling", "defensive_engagement", "aggression" },
            ["Physical"] = new[] { "physical_contact", "jumping", "stamina" },
            ["Pace"] = new[] { "speed", "acceleration" },
            ["Goalkeeping"] = new[] { "gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach" },
        };

    public const int PositionSessions = 6;   // RoleTraining's bar: six sessions to learn a position

    public (string? Focus, int Progress) TrainingOf(int playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT focus, progress FROM training_focus WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? (r.GetString(0), r.GetInt32(1)) : (null, 0);
    }

    public void SetTraining(int playerId, string? focus)
    {
        using var cmd = Db.Connection.CreateCommand();
        if (string.IsNullOrEmpty(focus))
        {
            cmd.CommandText = "DELETE FROM training_focus WHERE player_id=$p";
        }
        else
        {
            cmd.CommandText = "INSERT INTO training_focus(player_id,focus,progress) VALUES($p,$f,0) " +
                              "ON CONFLICT(player_id) DO UPDATE SET focus=$f, progress=0";
            cmd.Parameters.AddWithValue("$f", focus);
        }
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.ExecuteNonQuery();
    }

    public IReadOnlyList<string> LearnedPositions(int playerId)
    {
        var list = new List<string>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT position FROM player_positions WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) list.Add(r.GetString(0));
        return list;
    }

    /// <summary>
    /// One training tick for every focused player in YOUR squad (runs per recorded league
    /// matchday). Ability focuses nudge the real attributes — the ones that compile into the
    /// game — on an age curve; position focuses unlock a new Natural position after six
    /// sessions. Returns human-readable notes for the inbox/status line.
    /// </summary>
    public IReadOnlyList<string> ApplyTraining()
    {
        var notes = new List<string>();
        var squad = Repo.SquadPlayers(CurrentTeamId).ToDictionary(p => p.Id);
        var focused = new List<(int PlayerId, string Focus, int Progress)>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT player_id, focus, progress FROM training_focus";
            using var r = q.ExecuteReader();
            while (r.Read())
            {
                if (squad.ContainsKey(r.GetInt32(0)))
                    focused.Add((r.GetInt32(0), r.GetString(1), r.GetInt32(2)));
            }
        }

        foreach (var (pid, focus, progress) in focused)
        {
            var p = squad[pid];
            var next = progress + 1;
            if (focus.StartsWith("pos:", StringComparison.Ordinal))
            {
                if (next >= PositionSessions)
                {
                    var pos = focus[4..];
                    using (var ins = Db.Connection.CreateCommand())
                    {
                        ins.CommandText = "INSERT OR IGNORE INTO player_positions(player_id,position) " +
                                          "VALUES($p,$pos)";
                        ins.Parameters.AddWithValue("$p", pid);
                        ins.Parameters.AddWithValue("$pos", pos);
                        ins.ExecuteNonQuery();
                    }
                    SetTraining(pid, null);
                    notes.Add($"{p.Name} has learned to play {pos}.");
                    continue;
                }
            }
            else if (TrainingGroups.TryGetValue(focus, out var abilities))
            {
                // Age curve: youngsters gain every 3rd session, prime every 4th, veterans every
                // 6th — and a 4★+ coach shaves a week off all of it (floor 2).
                var cadence = Math.Max(2,
                    ((p.Age ?? 25) < 24 ? 3 : (p.Age ?? 25) <= 30 ? 4 : 6) - CoachTrainingBonus());
                if (next % cadence == 0)
                {
                    using var up = Db.Connection.CreateCommand();
                    up.CommandText = "UPDATE player_attributes SET value=MIN(99,value+1) " +
                                     $"WHERE player_id=$p AND attribute IN ({string.Join(",", abilities.Select((_, i) => $"$a{i}"))})";
                    up.Parameters.AddWithValue("$p", pid);
                    for (var i = 0; i < abilities.Length; i++) up.Parameters.AddWithValue($"$a{i}", abilities[i]);
                    up.ExecuteNonQuery();
                    notes.Add($"{p.Name}: {focus} +1.");
                    if (next % (cadence * 2) == 0)
                    {
                        using var ovr = Db.Connection.CreateCommand();
                        ovr.CommandText = "UPDATE players SET overall_rating=MIN(99,COALESCE(overall_rating,60)+1) " +
                                          "WHERE id=$p";
                        ovr.Parameters.AddWithValue("$p", pid);
                        ovr.ExecuteNonQuery();
                    }
                }
            }
            using var upd = Db.Connection.CreateCommand();
            upd.CommandText = "UPDATE training_focus SET progress=$n WHERE player_id=$p";
            upd.Parameters.AddWithValue("$n", next);
            upd.Parameters.AddWithValue("$p", pid);
            upd.ExecuteNonQuery();
        }
        return notes;
    }

    // ------------------------------------------------------------------ manual XI

    /// <summary>Once you've picked a team by hand, the AI only steps in to replace the injured.</summary>
    public bool ManualXi
    {
        get => GetMeta($"xi_manual_{CurrentTeamId}") == "1";
        set => SetMeta($"xi_manual_{CurrentTeamId}", value ? "1" : "0");
    }

    /// <summary>
    /// Persist an explicit squad order (XI = first eleven ids, bench after). Any squad member
    /// missing from the list is appended, so every player always holds a unique slot — a partial
    /// order must never leave two players sharing one.
    /// </summary>
    public void SaveSquadOrder(IReadOnlyList<int> playerIdsInOrder, bool manual)
    {
        var order = playerIdsInOrder.Distinct().ToList();
        foreach (var m in Repo.Squad(CurrentTeamId).OrderBy(m => m.Slot))
        {
            if (!order.Contains(m.PlayerId)) order.Add(m.PlayerId);
        }
        using var tx = Db.Connection.BeginTransaction();
        for (var i = 0; i < order.Count; i++)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.Transaction = tx;
            cmd.CommandText = "UPDATE squad_members SET slot=$s WHERE team_id=$t AND player_id=$p";
            cmd.Parameters.AddWithValue("$s", i);
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            cmd.Parameters.AddWithValue("$p", order[i]);
            cmd.ExecuteNonQuery();
        }
        tx.Commit();
        ManualXi = manual;
    }

    /// <summary>The AI's suggested order for YOUR club (doesn't persist — preview for the UI).</summary>
    public IReadOnlyList<int> SuggestXi()
    {
        var (fid0, _) = OwnFormationIds();
        var slotPositions = Repo.FormationSlots(fid0).OrderBy(s => s.SlotIndex)
            .Select(s => Visuals.RoleCodeLabel(s.Position)).ToList();
        var conditions = Repo.ConditionsFor(CurrentTeamId).ToDictionary(c => c.PlayerId);
        var next = NextFixture();
        var md = next?.Matchday ?? 0;
        var squad = Repo.SquadPlayers(CurrentTeamId).Select(p =>
        {
            conditions.TryGetValue(p.Id, out var c);
            return new CandidatePlayer(
                p.Id, p.OverallRating ?? 70, Visuals.PositionCategory(p.Position),
                c?.Fatigue ?? 0, (c?.Form ?? 6.5) + MoraleFormAdjustment(p.Id),
                c?.InjuredUntilMd is int until && until >= md);
        }).ToList();
        var registered = Repo.SquadPlayers(CurrentTeamId).ToDictionary(p => p.Id, p => p.Position);
        return XiSelector.SelectOrder(squad, slotPositions,
            pid => (registered.GetValueOrDefault(pid, "CMF"), LearnedPositions(pid)));
    }

    // ------------------------------------------------------------------ set-piece takers

    /// <summary>
    /// Set-piece taker kinds → PlayerAssignment role-flag bits, calibrated against the shipped
    /// data (Ødegaard/Foden/Szoboszlai all carry bit 8 = FK; left-footers carry 4 = left CK).
    /// Bit 32 is the captain (vendored semantics); bit 2 (secondary FK) is preserved untouched.
    /// </summary>
    public static readonly (string Kind, string Label, int Bit)[] TakerKinds =
    {
        ("fk", "Free kicks", 8),
        ("pk", "Penalties", 16),
        ("ckl", "Corners (left)", 4),
        ("ckr", "Corners (right)", 1),
    };

    public int? TakerOf(string kind) =>
        int.TryParse(GetMeta($"taker_{kind}_{CurrentTeamId}"), out var v) ? v : null;

    public void SetTaker(string kind, int? playerId) =>
        SetMeta($"taker_{kind}_{CurrentTeamId}", playerId?.ToString() ?? "");

    // Individual Instructions (Game Plan replica). Planning state only: the game reads these
    // from the user save, not team data, so they are NOT compiled — see docs/tactics-menu-map.md.
    public string InstructionOf(string slot) => GetMeta($"instr_{slot}_{CurrentTeamId}") ?? "Off";

    public void SetInstruction(string slot, string name) =>
        SetMeta($"instr_{slot}_{CurrentTeamId}", name);

    // ------------------------------------------------------------------ captain / release / list

    public int? Captain
    {
        get => int.TryParse(GetMeta($"captain_{CurrentTeamId}"), out var v) ? v : null;
        set => SetMeta($"captain_{CurrentTeamId}", value?.ToString() ?? "");
    }

    /// <summary>Release a player on a free — squad must stay a legal size.</summary>
    public string ReleasePlayer(int playerId)
    {
        var squad = Repo.Squad(CurrentTeamId);
        if (squad.All(s => s.PlayerId != playerId)) return "Not in your squad.";
        if (squad.Count <= 18) return "Squad is at the minimum (18) — sign a replacement first.";
        Repo.RemoveSquadMember(CurrentTeamId, playerId);
        if (Captain == playerId) Captain = null;
        _teamCache = null;
        _shooterPool = null;
        return "Released on a free. Their wages come off the bill.";
    }

    public bool IsTransferListed(int playerId) =>
        (GetMeta($"listed_{CurrentTeamId}") ?? "").Split(',').Contains(playerId.ToString());

    public void SetTransferListed(int playerId, bool listed)
    {
        var ids = (GetMeta($"listed_{CurrentTeamId}") ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries).ToHashSet();
        if (listed) ids.Add(playerId.ToString());
        else ids.Remove(playerId.ToString());
        SetMeta($"listed_{CurrentTeamId}", string.Join(",", ids));
    }

    // ------------------------------------------------------------------ contracts

    /// <summary>
    /// A player's contract expiry season-year, synthesised deterministically on first sight
    /// (1-3 seasons) and persisted, so every squad shows real, stable contract lengths.
    /// </summary>
    public int ContractYear(int playerId)
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT expires_season FROM contracts WHERE player_id=$p AND team_id=$t";
            q.Parameters.AddWithValue("$p", playerId);
            q.Parameters.AddWithValue("$t", CurrentTeamId);
            if (q.ExecuteScalar() is long v and > 0) return 2026 + ((int)v - 9000);
        }
        var expires = SeasonId + 1 + (int)((uint)(playerId * 2654435761) % 3);
        using (var ins = Db.Connection.CreateCommand())
        {
            ins.CommandText = "INSERT OR REPLACE INTO contracts(player_id,team_id,weekly_wage,expires_season) " +
                              "VALUES($p,$t,$w,$e)";
            ins.Parameters.AddWithValue("$p", playerId);
            ins.Parameters.AddWithValue("$t", CurrentTeamId);
            ins.Parameters.AddWithValue("$w", 500);
            ins.Parameters.AddWithValue("$e", expires);
            ins.ExecuteNonQuery();
        }
        return 2026 + (expires - 9000);
    }

    // ------------------------------------------------------------------ negotiation v2 (B3)

    private (int Rating, int? Age, string Name) PlayerBasics(int playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT COALESCE(overall_rating,65), age, name FROM players WHERE id=$p";
        q.Parameters.AddWithValue("$p", playerId);
        using var r = q.ExecuteReader();
        return r.Read()
            ? (r.GetInt32(0), r.IsDBNull(1) ? null : r.GetInt32(1), r.GetString(2))
            : (65, null, "?");
    }

    /// <summary>The agent's opening ask for the squad card's negotiation panel.</summary>
    public (long Demand, string Line) ContractDemand(int playerId, int years, string? status)
    {
        var (rating, age, name) = PlayerBasics(playerId);
        var demand = ML.Core.Selection.ContractNegotiation.WeeklyDemand(
            rating, age, MoraleOf(playerId), years);
        var target = (long)(demand * (1 - ML.Core.Selection.ContractNegotiation.StatusDiscount(status)));
        return (target, $"{name}'s agent opens at £{target:N0}/week for {years} year(s)" +
                        (status is not null and not "None" ? $" with {status} status promised." : "."));
    }

    /// <summary>
    /// One offer round. Accepting writes the REAL wage into the contract (it joins the weekly
    /// bill), registers the squad-status promise for B1/B2 to police, and settles any pending
    /// contract promise.
    /// </summary>
    public (bool Accepted, bool Over, string Message) OfferContract(
        int playerId, long weeklyOffer, int years, string? status, int round)
    {
        var (rating, age, name) = PlayerBasics(playerId);
        var demand = ML.Core.Selection.ContractNegotiation.WeeklyDemand(
            rating, age, MoraleOf(playerId), years);
        var st = status is "None" ? null : status;
        var (outcome, counter) = ML.Core.Selection.ContractNegotiation.Respond(
            weeklyOffer, demand, st, round);

        switch (outcome)
        {
            case ML.Core.Selection.NegotiationOutcome.Accepted:
                using (var up = Db.Connection.CreateCommand())
                {
                    up.CommandText =
                        "INSERT INTO contracts(player_id,team_id,weekly_wage,expires_season) " +
                        "VALUES($p,$t,$w,$e) ON CONFLICT(player_id,team_id) " +
                        "DO UPDATE SET weekly_wage=$w, expires_season=$e";
                    up.Parameters.AddWithValue("$p", playerId);
                    up.Parameters.AddWithValue("$t", CurrentTeamId);
                    up.Parameters.AddWithValue("$w", weeklyOffer);
                    up.Parameters.AddWithValue("$e", SeasonId + years);
                    up.ExecuteNonQuery();
                }
                var md = NextFixture()?.Matchday ?? 0;
                if (st is not null)
                {
                    using var ins = Db.Connection.CreateCommand();
                    ins.CommandText = "INSERT INTO promises(player_id,kind,made_md,deadline_md,done) " +
                                      "VALUES($p,$k,$m,$d,0)";
                    ins.Parameters.AddWithValue("$p", playerId);
                    ins.Parameters.AddWithValue("$k", $"status:{st}");
                    ins.Parameters.AddWithValue("$m", md);
                    ins.Parameters.AddWithValue("$d", md + 6);
                    ins.ExecuteNonQuery();
                }
                try { FulfilContractPromise(playerId, md); } catch { /* bonus */ }
                PostInbox("Player", $"Contract agreed: {name}",
                    $"{name} signs until {2026 + (SeasonId + years - 9000)} at £{weeklyOffer:N0}/week" +
                    (st is not null ? $" with {st} status — he'll hold you to the starts." : "."));
                return (true, true, $"{name} signs — £{weeklyOffer:N0}/week until " +
                                    $"{2026 + (SeasonId + years - 9000)}{(st is not null ? $", {st} status promised" : "")}.");

            case ML.Core.Selection.NegotiationOutcome.Countered:
                return (false, false,
                    $"The agent counters: £{counter:N0}/week. (Round {round} of 3.)");

            default:
                return (false, true,
                    $"{name}'s agent ends the talks — that offer wasn't serious. Try again another week.");
        }
    }

    /// <summary>Extend a contract two seasons for a signing bonus (10% of value).</summary>
    public string RenewContract(int playerId)
    {
        int rating = 65;
        int? age = null;
        string name = "player";
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT name, COALESCE(overall_rating,65), age FROM players WHERE id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            using var r = q.ExecuteReader();
            if (r.Read())
            {
                name = r.GetString(0);
                rating = r.GetInt32(1);
                age = r.IsDBNull(2) ? null : r.GetInt32(2);
            }
        }
        var bonus = ValuationOf(rating, age) / 10;
        if (!Finances.TrySpendOnTransfer(bonus, minBalanceAfter: 0))
        {
            return $"{name} wants a £{bonus:N0} signing bonus — you can't cover it.";
        }
        AdjustBudget(-bonus);
        using (var up = Db.Connection.CreateCommand())
        {
            up.CommandText = "INSERT INTO contracts(player_id,team_id,weekly_wage,expires_season) " +
                             "VALUES($p,$t,500,$e) " +
                             "ON CONFLICT(player_id,team_id) DO UPDATE SET expires_season=$e";
            up.Parameters.AddWithValue("$p", playerId);
            up.Parameters.AddWithValue("$t", CurrentTeamId);
            up.Parameters.AddWithValue("$e", SeasonId + 2);
            up.ExecuteNonQuery();
        }
        try { FulfilContractPromise(playerId, NextFixture()?.Matchday ?? 0); } catch { /* bonus */ }
        return $"{name} signed until {2026 + (SeasonId + 2 - 9000)} (£{bonus:N0} bonus paid).";
    }
}
