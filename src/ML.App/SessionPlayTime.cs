using ML.Data;

namespace ML.App;

/// <summary>
/// FM-style playing time (P5): every squad player carries a status — Star Player down to
/// Surplus to Requirements — with an expectation of starts. Falling short bleeds morale and
/// eventually a transfer request; the status also drives how willing a club (yours AND the
/// AI's) is to sell: a Star Player costs a fortune and angers the room when sold, Surplus
/// goes cheap and gladly. Modelled on Football Manager's squad-status system.
/// </summary>
public sealed partial class Session
{
    public static readonly string[] PlayTimeStatuses =
    {
        "Star Player", "Important Player", "Regular Starter", "Squad Player",
        "Fringe Player", "Hot Prospect", "Surplus to Requirements",
    };

    /// <summary>Expected STARTS in any rolling six matchdays; -1 = no expectation.</summary>
    public static int ExpectedStartsPer6(string status) => status switch
    {
        "Star Player" => 5,
        "Important Player" => 4,
        "Regular Starter" => 3,
        "Squad Player" => 2,
        _ => -1,
    };

    /// <summary>How the status multiplies a selling club's ask (and willingness).</summary>
    public static int StatusAskPct(string status) => status switch
    {
        "Star Player" => 145,
        "Important Player" => 120,
        "Regular Starter" => 110,
        "Squad Player" => 100,
        "Fringe Player" => 90,
        "Hot Prospect" => 130,          // clubs guard their gems
        "Surplus to Requirements" => 70,
        _ => 100,
    };

    /// <summary>
    /// A player's status: stored if the manager set one, otherwise derived from where his
    /// rating ranks in his squad (the same derivation prices CPU clubs' players).
    /// </summary>
    public string PlayTimeStatusOf(int playerId)
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT status FROM player_status WHERE player_id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            if (q.ExecuteScalar() is string s && s.Length > 0) return s;
        }
        return DerivedStatus(playerId);
    }

    private string DerivedStatus(int playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT s.team_id FROM squad_members s WHERE s.player_id=$p LIMIT 1";
        q.Parameters.AddWithValue("$p", playerId);
        var v = q.ExecuteScalar();
        if (v is null or DBNull) return "Fringe Player";
        var teamId = Convert.ToInt32(v);
        var squad = Repo.SquadPlayers(teamId).OrderByDescending(p => p.OverallRating ?? 0).ToList();
        var me = squad.FirstOrDefault(p => p.Id == playerId);
        if (me is null) return "Fringe Player";
        if ((me.Age ?? 25) <= 20 && squad.IndexOf(me) >= 11) return "Hot Prospect";
        return squad.IndexOf(me) switch
        {
            <= 1 => "Star Player",
            <= 5 => "Important Player",
            <= 10 => "Regular Starter",
            <= 17 => "Squad Player",
            _ => "Fringe Player",
        };
    }

    /// <summary>
    /// The manager sets a status: promotions please, demotions sting, and Surplus lists him
    /// in all but name (the market comes calling).
    /// </summary>
    public string SetPlayTimeStatus(int playerId, string status)
    {
        if (!PlayTimeStatuses.Contains(status)) return "Unknown status.";
        var before = PlayTimeStatusOf(playerId);
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "INSERT INTO player_status(player_id,status) VALUES($p,$s) " +
                              "ON CONFLICT(player_id) DO UPDATE SET status=excluded.status";
            cmd.Parameters.AddWithValue("$p", playerId);
            cmd.Parameters.AddWithValue("$s", status);
            cmd.ExecuteNonQuery();
        }
        var rank = Array.IndexOf(PlayTimeStatuses, status);
        var wasRank = Array.IndexOf(PlayTimeStatuses, before);
        var name = PlayerNameOf(playerId);
        if (status == "Surplus to Requirements")
        {
            SetMorale(playerId, MoraleOf(playerId) - 10);
            SetTransferListed(playerId, true);
            return $"{name} told he's surplus — he's on the market and he's not happy about it.";
        }
        if (rank < wasRank)
        {
            SetMorale(playerId, MoraleOf(playerId) + 5);
            return $"{name} promoted to {status} — he's delighted, and his agent noticed too.";
        }
        if (rank > wasRank)
        {
            SetMorale(playerId, MoraleOf(playerId) - 6);
            return $"{name} demoted to {status} — expect a knock on your door if it stands.";
        }
        return $"{name}: {status}.";
    }

    /// <summary>Starts (XI appearances) in the last six matchdays for one of your players.</summary>
    public int StartsInLastSix(int playerId, int uptoMatchday)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT COUNT(*) FROM match_events e JOIN fixtures f ON f.id=e.fixture_id " +
            "WHERE e.player_id=$p AND e.event_type='app' AND f.season_id=$s " +
            "AND f.matchday BETWEEN $lo AND $hi";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$lo", Math.Max(1, uptoMatchday - 5));
        cmd.Parameters.AddWithValue("$hi", uptoMatchday);
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    /// <summary>
    /// The six-matchday reckoning (called from the weekly pass on MD 6/12/18/24/30/36):
    /// shortfalls bleed morale (biggest names bleed fastest), met expectations settle the
    /// biggest names, and Surplus players simmer while they stay.
    /// </summary>
    public void EvaluatePlayingTime(int matchday)
    {
        if (matchday < 6 || matchday % 6 != 0) return;
        var guard = $"pt_eval_{SeasonId}_{matchday}";
        if (GetMeta(guard) is not null) return;
        SetMeta(guard, "1");
        var unhappy = new List<string>();
        foreach (var p in Repo.SquadPlayers(CurrentTeamId))
        {
            var status = PlayTimeStatusOf(p.Id);
            if (status == "Surplus to Requirements")
            {
                SetMorale(p.Id, MoraleOf(p.Id) - 2);
                continue;
            }
            var expected = ExpectedStartsPer6(status);
            if (expected < 0) continue;
            var actual = StartsInLastSix(p.Id, matchday);
            var shortfall = expected - actual;
            if (shortfall >= 2)
            {
                SetMorale(p.Id, MoraleOf(p.Id) - 6);
                unhappy.Add($"{p.Name} ({status}: wanted {expected} of the last 6 starts, got {actual})");
            }
            else if (shortfall == 1)
            {
                SetMorale(p.Id, MoraleOf(p.Id) - 3);
            }
            else if (status is "Star Player" or "Important Player")
            {
                SetMorale(p.Id, MoraleOf(p.Id) + 2);
            }
        }
        if (unhappy.Count > 0)
        {
            PostInbox("Player", "Playing-time complaints",
                "Knocks on your door this month:\n• " + string.Join("\n• ", unhappy.Take(5)) +
                "\nPlay them, demote their status honestly, or expect transfer requests.", matchday);
        }
    }
}
