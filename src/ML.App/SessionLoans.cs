using ML.Core;
using ML.Data;

namespace ML.App;

public sealed record LoanRow(long PlayerId, string Player, string OtherClub, string Direction);

/// <summary>
/// Loans (FM-style): park your youngsters at a host club for minutes (they develop faster
/// for it), or borrow a body for the season at a tenth of his value. Recalls open with the
/// January window; everyone goes home at rollover.
/// </summary>
public sealed partial class Session
{
    public IReadOnlyList<LoanRow> ActiveLoans()
    {
        var rows = new List<LoanRow>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT l.player_id, p.name, l.host_team, l.owner_team, l.direction " +
                          "FROM loans l JOIN players p ON p.id=l.player_id " +
                          "WHERE l.season_id=$s AND (l.owner_team=$t OR l.host_team=$t)";
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var dir = r.GetString(4);
            var other = dir == "out" ? r.GetInt32(2) : r.GetInt32(3);
            rows.Add(new LoanRow(r.GetInt64(0), r.GetString(1), TeamName(other), dir));
        }
        return rows;
    }

    /// <summary>Send one of yours to a lower-half club for the season.</summary>
    public string LoanOut(long playerId)
    {
        if (!TransferWindowOpen()) return TransferWindowLabel() + ". Loans need an open window.";
        var p = Repo.SquadPlayers(CurrentTeamId).FirstOrDefault(x => x.Id == playerId);
        if (p is null) return "Not in your squad.";
        if (Repo.Squad(CurrentTeamId).Count <= 18) return "Squad at the minimum — you can't spare him.";
        var hosts = Repo.Teams()
            .Where(t => t.LeagueId is TopFlight or Division2 && t.Id != CurrentTeamId)
            .OrderBy(t => EloOf(t.Id)).Take(10).ToList();
        if (hosts.Count == 0) return "No club will host a loan.";
        var host = hosts[(int)((uint)(playerId * 2654435761) % hosts.Count)];
        Repo.RemoveSquadMember(CurrentTeamId, playerId);
        MoveIntoSquad(host.Id, playerId);
        RecordLoan(playerId, CurrentTeamId, host.Id, "out");
        PostInbox("Transfer", $"Loan: {p.Name} → {host.Name}",
            $"{p.Name} joins {host.Name} on loan until the end of the season. Regular minutes " +
            "there will do his development good; a recall opens with the January window.",
            playerId: playerId);
        _teamCache = null;
        _shooterPool = null;
        return $"{p.Name} loaned to {host.Name} until June — recall from January.";
    }

    /// <summary>Borrow an owned player for the season at 10% of value (no option to buy).</summary>
    public string LoanIn(long playerId)
    {
        if (!TransferWindowOpen()) return TransferWindowLabel() + ". Loans need an open window.";
        if (Repo.Squad(CurrentTeamId).Any(s => s.PlayerId == playerId)) return "He is already yours.";
        var owner = OwningClub(playerId);
        if (owner is null) return "Free agents sign permanently — bid instead.";
        if (Repo.Squad(owner.Value.TeamId).Count <= 18)
            return $"{owner.Value.Name} can't spare him — squad at the minimum.";
        var (rating, age, name) = PlayerBasics(playerId);
        var fee = ValuationOf(rating, age) / 10;
        if (!Finances.TrySpendOnTransfer(fee, minBalanceAfter: 0))
            return $"The loan fee is £{fee:N0} — you have £{Finances.Balance:N0}.";
        AdjustBudget(-fee);
        Repo.RemoveSquadMember(owner.Value.TeamId, playerId);
        MoveIntoSquad(CurrentTeamId, playerId);
        RecordLoan(playerId, owner.Value.TeamId, CurrentTeamId, "in");
        PostInbox("Transfer", $"Loan signing: {name}",
            $"{name} ({rating}) arrives from {owner.Value.Name} until June — £{fee:N0} loan fee. " +
            "He goes back in the summer.", playerId: playerId);
        _teamCache = null;
        _shooterPool = null;
        SyncBudget();
        return $"Loan DONE — {name} is yours until June (£{fee:N0} fee).";
    }

    /// <summary>Bring your loanee home (January window onward).</summary>
    public string RecallLoan(long playerId)
    {
        var next = NextFixture();
        if (next is not null && next.Matchday < 17)
            return "Recalls open with the January window (matchday 17).";
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT host_team FROM loans WHERE player_id=$p AND season_id=$s AND direction='out'";
        q.Parameters.AddWithValue("$p", playerId);
        q.Parameters.AddWithValue("$s", SeasonId);
        if (q.ExecuteScalar() is not long host) return "No loan to recall.";
        Repo.RemoveSquadMember((int)host, playerId);
        MoveIntoSquad(CurrentTeamId, playerId);
        DeleteLoan(playerId);
        _teamCache = null;
        _shooterPool = null;
        return $"{PlayerNameOf(playerId)} recalled from {TeamName((int)host)}.";
    }

    /// <summary>Rollover: everyone goes home; young loanees come back improved by the minutes.</summary>
    internal void ReturnAllLoans()
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT player_id, owner_team, host_team, direction FROM loans WHERE season_id=$s";
        q.Parameters.AddWithValue("$s", SeasonId);
        var rows = new List<(long Pid, int Owner, int Host, string Dir)>();
        using (var r = q.ExecuteReader())
        {
            while (r.Read()) rows.Add((r.GetInt64(0), r.GetInt32(1), r.GetInt32(2), r.GetString(3)));
        }
        foreach (var (pid, owner, host, dir) in rows)
        {
            var at = dir == "out" ? host : CurrentTeamId;
            Repo.RemoveSquadMember(at, pid);
            MoveIntoSquad(owner, pid);
            if (dir == "out")
            {
                // The whole point of the loan: minutes. Young loanees develop for it.
                using var pq = Db.Connection.CreateCommand();
                pq.CommandText = "UPDATE players SET overall_rating = MIN(99, overall_rating + 1) " +
                                 "WHERE id=$p AND COALESCE(age, 25) <= 22";
                pq.Parameters.AddWithValue("$p", pid);
                if (pq.ExecuteNonQuery() > 0 && owner == CurrentTeamId)
                {
                    PostInbox("Player", $"{PlayerNameOf(pid)} returns from loan sharper",
                        "A season of real minutes has done him good — he comes back a better player.",
                        playerId: pid);
                }
            }
            DeleteLoan(pid);
        }
        _teamCache = null;
        _shooterPool = null;
    }

    private void RecordLoan(long playerId, int owner, int host, string direction)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO loans(player_id,owner_team,host_team,season_id,direction) " +
                          "VALUES($p,$o,$h,$s,$d) ON CONFLICT(player_id) DO UPDATE SET " +
                          "owner_team=$o, host_team=$h, season_id=$s, direction=$d";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$o", owner);
        cmd.Parameters.AddWithValue("$h", host);
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$d", direction);
        cmd.ExecuteNonQuery();
    }

    private void DeleteLoan(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "DELETE FROM loans WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.ExecuteNonQuery();
    }
}
