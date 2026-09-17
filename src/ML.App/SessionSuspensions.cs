using ML.Core.Selection;

namespace ML.App;

/// <summary>
/// Suspensions. Until this file, cards were decoration: the stats host imports every yellow and
/// red from the match you played, the sim invents them for everyone else, the Stats screen ranks
/// them — and nothing ever happened to anybody. A man sent off on Saturday started on Wednesday.
///
/// The rules are ML.Core's <see cref="SuspensionRules"/>. This is the bookkeeping around them:
/// after every competitive fixture, the two clubs' standing bans are SERVED (one match off each),
/// then that fixture's own cards are turned into new bans — in that order, so a ban is never
/// served by the match that earned it. It is settled once per fixture behind a meta guard, and
/// undoing a result takes its bans back off and gives back the matches it served.
///
/// Who enforces it: PrepareMatchday and SuggestXi treat a banned man exactly as an injured one,
/// the Squad and Tactics screens say SUSPENDED, and tools/play_match.py reads the same table, so
/// he cannot be compiled into the XI even if he is dragged back onto the pitch by hand.
/// </summary>
public sealed partial class Session
{
    /// <summary>A standing ban: how many of his club's fixtures he still misses, and why.</summary>
    public sealed record Suspension(long PlayerId, int Matches, string Reason);

    /// <summary>Every standing ban at a club, by player.</summary>
    public IReadOnlyDictionary<long, Suspension> SuspensionsAt(int teamId)
    {
        var bans = new Dictionary<long, Suspension>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT b.player_id, b.matches, b.reason FROM suspensions b " +
                          "JOIN squad_members s ON s.player_id=b.player_id " +
                          "WHERE s.team_id=$t AND b.matches > 0";
        cmd.Parameters.AddWithValue("$t", teamId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
            bans[r.GetInt64(0)] = new Suspension(r.GetInt64(0), r.GetInt32(1), r.GetString(2));
        return bans;
    }

    /// <summary>His standing ban, or null when he is free to play.</summary>
    public Suspension? SuspensionOf(long playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT matches, reason FROM suspensions WHERE player_id=$p AND matches > 0";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? new Suspension(playerId, r.GetInt32(0), r.GetString(1)) : null;
    }

    /// <summary>"misses the next match" / "misses the next 2 matches".</summary>
    public static string SuspensionSpan(int matches) =>
        matches == 1 ? "misses the next match" : $"misses the next {matches} matches";

    /// <summary>
    /// Serve, then sentence, for one finished fixture. Call it once the fixture's events are in
    /// match_events — after RecordMatchStats for the match you played, after the sim has invented
    /// its cards for everyone else's. Safe to call twice: the second call does nothing.
    /// </summary>
    public void SettleSuspensions(int fixtureId, int homeTeamId, int awayTeamId)
    {
        var guard = $"bans_settled_{fixtureId}";
        if (GetMeta(guard) is not null) return;
        if (FixtureKind(fixtureId) == "friendly") return;   // preseason neither bans nor serves

        // 1. Serve. Everyone at either club with a standing ban misses this one.
        var served = new List<string>();
        foreach (var teamId in new[] { homeTeamId, awayTeamId })
        {
            foreach (var ban in SuspensionsAt(teamId).Values)
            {
                served.Add($"{ban.PlayerId}|{ban.Reason}");
                using var cmd = Db.Connection.CreateCommand();
                cmd.CommandText = ban.Matches > 1
                    ? "UPDATE suspensions SET matches = matches - 1 WHERE player_id=$p"
                    : "DELETE FROM suspensions WHERE player_id=$p";
                cmd.Parameters.AddWithValue("$p", ban.PlayerId);
                cmd.ExecuteNonQuery();
                if (teamId == CurrentTeamId && ban.Matches == 1)
                {
                    PostInbox("Player", $"Ban served: {PlayerNameOf(ban.PlayerId)}",
                        $"{PlayerNameOf(ban.PlayerId)} has sat out his suspension ({ban.Reason}) and is " +
                        "available again.", NextFixture()?.Matchday, playerId: ban.PlayerId);
                }
            }
        }

        // 2. Sentence. This fixture's cards, against each man's season tally BEFORE it.
        var cards = new List<(long PlayerId, int Yellows, int Reds)>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT player_id, SUM(event_type='yellow'), SUM(event_type='red') FROM match_events " +
                "WHERE fixture_id=$f AND event_type IN ('yellow','red') AND player_id IS NOT NULL " +
                "GROUP BY player_id";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            using var r = cmd.ExecuteReader();
            while (r.Read()) cards.Add((r.GetInt64(0), r.GetInt32(1), r.GetInt32(2)));
        }
        foreach (var (playerId, yellows, reds) in cards)
        {
            var before = CountedYellowsBefore(playerId, fixtureId);
            var matches = SuspensionRules.MatchesFor(reds, yellows, before);
            if (matches == 0) continue;
            var reason = SuspensionRules.Reason(reds, yellows, before);
            using (var cmd = Db.Connection.CreateCommand())
            {
                // A second offence while already banned adds to the sentence.
                cmd.CommandText =
                    "INSERT INTO suspensions(player_id, matches, reason, season_id, from_fixture_id) " +
                    "VALUES($p,$m,$r,$s,$f) ON CONFLICT(player_id) DO UPDATE SET " +
                    "matches = matches + $m, reason = $r, season_id = $s, from_fixture_id = $f";
                cmd.Parameters.AddWithValue("$p", playerId);
                cmd.Parameters.AddWithValue("$m", matches);
                cmd.Parameters.AddWithValue("$r", reason);
                cmd.Parameters.AddWithValue("$s", SeasonId);
                cmd.Parameters.AddWithValue("$f", fixtureId);
                cmd.ExecuteNonQuery();
            }
            if (IsOwnPlayer(playerId))
            {
                PostInbox("Player", $"Suspended: {PlayerNameOf(playerId)}",
                    $"{PlayerNameOf(playerId)} {SuspensionSpan(matches)} — {reason}. He cannot be " +
                    "picked until the ban is served; the assistant will name a replacement if you " +
                    "leave him in the XI.", NextFixture()?.Matchday, playerId: playerId);
            }
        }
        SetMeta(guard, string.Join(",", served));
    }

    /// <summary>
    /// Take one fixture's suspension bookkeeping back out — Undo's half. The bans it handed out
    /// go, and the matches it counted as served are given back, so re-recording the corrected
    /// result settles from the same place the first recording did.
    /// </summary>
    private void UnsettleSuspensions(int fixtureId)
    {
        var guard = $"bans_settled_{fixtureId}";
        var served = GetMeta(guard);
        if (served is null) return;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "DELETE FROM suspensions WHERE from_fixture_id=$f";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            cmd.ExecuteNonQuery();
        }
        foreach (var entry in served.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var bar = entry.IndexOf('|');
            if (bar <= 0 || !long.TryParse(entry[..bar], out var playerId)) continue;
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText =
                "INSERT INTO suspensions(player_id, matches, reason, season_id, from_fixture_id) " +
                "VALUES($p,1,$r,$s,0) ON CONFLICT(player_id) DO UPDATE SET matches = matches + 1";
            cmd.Parameters.AddWithValue("$p", playerId);
            cmd.Parameters.AddWithValue("$r", entry[(bar + 1)..]);
            cmd.Parameters.AddWithValue("$s", SeasonId);
            cmd.ExecuteNonQuery();
        }
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "DELETE FROM meta WHERE key=$k";
            cmd.Parameters.AddWithValue("$k", guard);
            cmd.ExecuteNonQuery();
        }
    }

    /// <summary>A new season starts with a clean disciplinary sheet.</summary>
    private void ClearSuspensionsForNewSeason()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "DELETE FROM suspensions";
        cmd.ExecuteNonQuery();
    }

    private string FixtureKind(int fixtureId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT kind FROM fixtures WHERE id=$f";
        cmd.Parameters.AddWithValue("$f", fixtureId);
        return cmd.ExecuteScalar() as string ?? "league";
    }

    /// <summary>His yellows that count toward accumulation, from this season's competitive
    /// fixtures other than the one being settled.</summary>
    private int CountedYellowsBefore(long playerId, int exceptFixtureId)
    {
        var total = 0;
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT SUM(e.event_type='yellow'), SUM(e.event_type='red') FROM match_events e " +
            "JOIN fixtures f ON f.id=e.fixture_id " +
            "WHERE e.player_id=$p AND f.season_id=$s AND f.kind<>'friendly' AND f.id<>$x " +
            "AND e.event_type IN ('yellow','red') GROUP BY e.fixture_id";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$x", exceptFixtureId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) total += SuspensionRules.CountedYellows(r.GetInt32(1), r.GetInt32(0));
        return total;
    }
}
