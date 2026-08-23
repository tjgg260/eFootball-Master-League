using ML.Core.Selection;
using ML.Data;

namespace ML.App;

/// <summary>
/// Per-player morale (FM phase B1), persisted in the existing `morale` table. Minutes, results
/// and the transfer list move it; it pulls on matchday selection; and a player who stays
/// miserable hands in a transfer request.
/// </summary>
public sealed partial class Session
{
    public int MoraleOf(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT value FROM morale WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        var v = cmd.ExecuteScalar();
        return v is null or DBNull ? MoraleModel.Neutral : Convert.ToInt32(v);
    }

    private void SetMorale(long playerId, int value)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO morale(player_id,value) VALUES($p,$v) " +
                          "ON CONFLICT(player_id) DO UPDATE SET value=$v";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$v", value);
        cmd.ExecuteNonQuery();
    }

    /// <summary>
    /// One morale pass for YOUR squad after a matchday: minutes + result + list status, then
    /// transfer requests from anyone left miserable (once per player per season).
    /// </summary>
    public void UpdateMoraleAfterMatchday(int matchday, int? outcome)
    {
        var requests = new List<string>();
        foreach (var member in Repo.Squad(CurrentTeamId))
        {
            var current = MoraleOf(member.PlayerId);
            var next = MoraleModel.AfterMatchday(
                current, member.Slot is >= 0 and <= 10, outcome, IsTransferListed(member.PlayerId));
            SetMorale(member.PlayerId, next);

            if (next <= MoraleModel.RequestThreshold
                && GetMeta($"transfer_req_{member.PlayerId}_{SeasonId}") is null)
            {
                SetMeta($"transfer_req_{member.PlayerId}_{SeasonId}", "1");
                SetTransferListed(member.PlayerId, true);
                var name = Repo.SquadPlayers(CurrentTeamId)
                    .FirstOrDefault(p => p.Id == member.PlayerId)?.Name ?? "A player";
                requests.Add(name);
            }
        }
        CheckPromises(matchday);
        foreach (var name in requests)
        {
            PostInbox("Player", $"Transfer request: {name}",
                $"{name} has handed in a transfer request — starved of minutes and unhappy. " +
                "He's been placed on the transfer list; expect offers next window. Playing him " +
                "and winning is the only way back.", matchday);
        }
    }

    /// <summary>Morale's pull on the selector's form term (±1.8), used for YOUR club.</summary>
    public double MoraleFormAdjustment(long playerId) =>
        MoraleModel.FormAdjustment(MoraleOf(playerId));

    // ------------------------------------------------------------------ team talks (C2)

    public int SquadMoraleAverage()
    {
        var members = Repo.Squad(CurrentTeamId);
        return members.Count == 0 ? MoraleModel.Neutral
            : (int)members.Average(m => MoraleOf(m.PlayerId));
    }

    /// <summary>Whether the pre/post talk for this fixture is still available.</summary>
    public bool TalkAvailable(int fixtureId, bool preMatch) =>
        GetMeta($"ttalk_{(preMatch ? "pre" : "post")}_{fixtureId}") is null;

    /// <summary>
    /// Deliver the team talk (once per fixture per phase): squad-wide morale shift + a small
    /// form nudge, both bounded by the pure model.
    /// </summary>
    public string ApplyTeamTalk(int fixtureId, bool preMatch, TalkTone tone,
        int homeTeamId, int awayTeamId, int? outcome)
    {
        var key = $"ttalk_{(preMatch ? "pre" : "post")}_{fixtureId}";
        if (GetMeta(key) is not null) return "You've already had your say on this one.";
        SetMeta(key, tone.ToString());

        var avg = SquadMoraleAverage();
        var oppId = homeTeamId == CurrentTeamId ? awayTeamId : homeTeamId;
        var favourites = EloOf(CurrentTeamId) >= EloOf(oppId);
        var (moraleDelta, formDelta, reaction) = preMatch
            ? TeamTalk.PreMatch(tone, favourites, avg)
            : TeamTalk.PostMatch(tone, outcome ?? 0, avg);

        var conditions = Repo.ConditionsFor(CurrentTeamId).ToDictionary(c => c.PlayerId);
        foreach (var m in Repo.Squad(CurrentTeamId))
        {
            SetMorale(m.PlayerId, Math.Clamp(
                MoraleOf(m.PlayerId) + moraleDelta, MoraleModel.Min, MoraleModel.Max));
            conditions.TryGetValue(m.PlayerId, out var c);
            Repo.UpsertCondition(new PlayerConditionRow
            {
                PlayerId = m.PlayerId,
                Fatigue = c?.Fatigue ?? 0,
                InjuredUntilMd = c?.InjuredUntilMd,
                Form = Math.Clamp((c?.Form ?? 6.5) + formDelta, 4, 9),
            });
        }
        return reaction;
    }

    /// <summary>The assistant's tone hint ("" without an assistant — read the room yourself).</summary>
    public string TalkHint(bool preMatch, int homeTeamId, int awayTeamId, int? outcome)
    {
        if (StaffFor("Assistant") is null) return "";
        var oppId = homeTeamId == CurrentTeamId ? awayTeamId : homeTeamId;
        var hint = TeamTalk.Hint(preMatch,
            EloOf(CurrentTeamId) >= EloOf(oppId), outcome ?? 0, SquadMoraleAverage());
        return $"Assistant: \"{hint} feels right here.\"";
    }

    // ------------------------------------------------------------------ talks & promises (B2)

    /// <summary>A private word — praise or criticism. One talk per player per matchday.</summary>
    public string TalkTo(long playerId, string playerName, bool praise)
    {
        var md = NextFixture()?.Matchday ?? 0;
        var guard = $"talk_{playerId}_{SeasonId}_{md}";
        if (GetMeta(guard) is not null)
        {
            return $"You've already had a word with {playerName} this week — leave it.";
        }
        SetMeta(guard, "1");
        SetMorale(playerId, MoraleModel.AfterTalk(MoraleOf(playerId), praise));
        return praise
            ? $"You praised {playerName}'s efforts — morale up ({MoraleModel.Label(MoraleOf(playerId))})."
            : $"You told {playerName} to do better — morale down ({MoraleModel.Label(MoraleOf(playerId))}).";
    }

    /// <summary>Promise "more starts" (3+ in 6 matchdays) or "a new contract" (renew by the deadline).</summary>
    public string MakePromise(long playerId, string playerName, string kind)
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT COUNT(*) FROM promises WHERE player_id=$p AND done=0";
            q.Parameters.AddWithValue("$p", playerId);
            if (Convert.ToInt32(q.ExecuteScalar()) > 0)
            {
                return $"{playerName} is already holding you to a promise — keep that one first.";
            }
        }
        var md = NextFixture()?.Matchday ?? 0;
        using (var ins = Db.Connection.CreateCommand())
        {
            ins.CommandText = "INSERT INTO promises(player_id,kind,made_md,deadline_md,done) " +
                              "VALUES($p,$k,$m,$d,0)";
            ins.Parameters.AddWithValue("$p", playerId);
            ins.Parameters.AddWithValue("$k", kind);
            ins.Parameters.AddWithValue("$m", md);
            ins.Parameters.AddWithValue("$d", md + 6);
            ins.ExecuteNonQuery();
        }
        SetMorale(playerId, MoraleModel.AfterTalk(MoraleOf(playerId), praise: true));
        return kind == "starts"
            ? $"You promised {playerName} more starts — he expects 3+ in the next 6 matchdays."
            : $"You promised {playerName} a new contract — renew it within 6 matchdays.";
    }

    /// <summary>Any open promise line for the squad card ("holding you to: more starts (MD14)").</summary>
    public string PromiseLine(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT kind, deadline_md FROM promises WHERE player_id=$p AND done=0 LIMIT 1";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        return r.Read()
            ? $"Holding you to: {(r.GetString(0) == "starts" ? "more starts" : "a new contract")} (by MD{r.GetInt32(1)})"
            : "";
    }

    /// <summary>Called by RenewContract — a pending contract promise is thereby KEPT.</summary>
    public void FulfilContractPromise(long playerId, int matchday)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE promises SET done=1 WHERE player_id=$p AND kind='contract' AND done=0";
        cmd.Parameters.AddWithValue("$p", playerId);
        if (cmd.ExecuteNonQuery() > 0)
        {
            SetMorale(playerId, MoraleModel.AfterPromise(MoraleOf(playerId), kept: true));
            var name = Repo.SquadPlayers(CurrentTeamId).FirstOrDefault(p => p.Id == playerId)?.Name ?? "He";
            PostInbox("Player", $"Promise kept: {name}",
                $"{name} got the contract you promised — the dressing room notices these things.", matchday);
        }
    }

    /// <summary>Settle promises whose deadline has passed (runs in the matchday pass).</summary>
    private void CheckPromises(int matchday)
    {
        var open = new List<(long Id, long PlayerId, string Kind, int MadeMd)>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT id, player_id, kind, made_md FROM promises " +
                            "WHERE done=0 AND deadline_md<=$m";
            q.Parameters.AddWithValue("$m", matchday);
            using var r = q.ExecuteReader();
            while (r.Read()) open.Add((r.GetInt64(0), r.GetInt64(1), r.GetString(2), r.GetInt32(3)));
        }
        var names = Repo.SquadPlayers(CurrentTeamId).ToDictionary(p => p.Id, p => p.Name);
        foreach (var (id, pid, kind, madeMd) in open)
        {
            bool kept;
            if (kind == "starts" || kind.StartsWith("status:"))
            {
                // 'starts' owes 3; squad-status promises owe their own bar (Star 5, First-team 4…).
                var owed = kind == "starts" ? 3
                    : ML.Core.Selection.ContractNegotiation.StatusStartsOwed(kind[7..]);
                using var q = Db.Connection.CreateCommand();
                q.CommandText = "SELECT COUNT(*) FROM match_events e JOIN fixtures f ON f.id=e.fixture_id " +
                                "WHERE e.player_id=$p AND e.event_type='app' AND f.season_id=$s " +
                                "AND f.matchday>$m";
                q.Parameters.AddWithValue("$p", pid);
                q.Parameters.AddWithValue("$s", SeasonId);
                q.Parameters.AddWithValue("$m", madeMd);
                kept = Convert.ToInt32(q.ExecuteScalar()) >= owed;
            }
            else
            {
                kept = false;   // an unrenewed contract promise at the deadline is broken
            }
            using (var u = Db.Connection.CreateCommand())
            {
                u.CommandText = "UPDATE promises SET done=$d WHERE id=$id";
                u.Parameters.AddWithValue("$d", kept ? 1 : 2);
                u.Parameters.AddWithValue("$id", id);
                u.ExecuteNonQuery();
            }
            SetMorale(pid, MoraleModel.AfterPromise(MoraleOf(pid), kept));
            var name = names.GetValueOrDefault(pid, "A player");
            PostInbox("Player",
                kept ? $"Promise kept: {name}" : $"Promise BROKEN: {name}",
                kept
                    ? $"{name} got the starts you promised — trust earned."
                    : $"You broke your word to {name}. He's furious, and the dressing room heard about it.",
                matchday);
        }
    }
}
