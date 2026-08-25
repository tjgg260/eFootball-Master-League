using ML.Data;

namespace ML.App;

public sealed record InboxMessage(
    long Id, int? Matchday, string Category, string Subject, string Body, bool IsRead,
    long? PlayerId, int? TeamId = null, bool RequiresAction = false);

/// <summary>
/// The persistent, event-driven inbox: messages are written into the DB the moment something
/// happens (a result, an injury, a cup draw, a transfer, a training milestone, a season review)
/// and stay there — read state and all — like MFL's message centre.
/// </summary>
public sealed partial class Session
{
    // team_id arrived after careers already existed — add the column lazily, once,
    // before the first read or write that names it. The ALTER failing means it's there.
    private bool _inboxTeamIdEnsured;
    private void EnsureInboxTeamIdColumn()
    {
        if (_inboxTeamIdEnsured) return;
        _inboxTeamIdEnsured = true;
        try
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText = "ALTER TABLE inbox ADD COLUMN team_id INTEGER";
            cmd.ExecuteNonQuery();
        }
        catch { /* column already exists — exactly what we want */ }
    }

    /// <summary>Write one message into the inbox; a player id lets the news feed show his face,
    /// a team id lets it show a club crest when there is no face, and requiresAction flags the
    /// letters that are waiting on a decision from you (offers, bids, approaches).</summary>
    public void PostInbox(string category, string subject, string body, int? matchday = null,
                          long? playerId = null, int? teamId = null, bool requiresAction = false)
    {
        EnsureInboxTeamIdColumn();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "INSERT INTO inbox(season_id,matchday,category,subject,body,is_read,requires_action,player_id,team_id) " +
            "VALUES($s,$m,$c,$subj,$b,0,$act,$p,$t)";
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$m", (object?)matchday ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$c", category);
        cmd.Parameters.AddWithValue("$subj", subject);
        cmd.Parameters.AddWithValue("$b", body);
        cmd.Parameters.AddWithValue("$act", requiresAction ? 1 : 0);
        cmd.Parameters.AddWithValue("$p", (object?)playerId ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$t", (object?)teamId ?? DBNull.Value);
        cmd.ExecuteNonQuery();
    }

    public IReadOnlyList<InboxMessage> InboxMessages(int count = 60)
    {
        EnsureInboxTeamIdColumn();
        var rows = new List<InboxMessage>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT id, matchday, category, subject, body, is_read, player_id, team_id, " +
            "requires_action FROM inbox ORDER BY id DESC LIMIT $n";
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            rows.Add(new InboxMessage(
                r.GetInt64(0), r.IsDBNull(1) ? null : r.GetInt32(1),
                r.GetString(2), r.GetString(3), r.GetString(4), r.GetInt32(5) == 1,
                r.IsDBNull(6) ? null : r.GetInt64(6),
                r.IsDBNull(7) ? null : r.GetInt32(7),
                !r.IsDBNull(8) && r.GetInt32(8) == 1));
        }
        return rows;
    }

    /// <summary>Portrait path + skin tone for a news face (either may be missing).</summary>
    public (string? PortraitPath, int? SkinTone) NewsFaceOf(long playerId)
    {
        // Follow the app's portrait precedence: eFootball real face (real_face_path) beats the RFS
        // photo. The generic avatar tier is drawn by the caller when both paths are absent.
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT p.real_face_path, p.portrait_path, a.skin_tone FROM players p " +
                          "LEFT JOIN player_appearance a ON a.player_id = p.id WHERE p.id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        if (!r.Read()) return (null, null);
        var real = r.IsDBNull(0) ? null : r.GetString(0);
        var rfs = r.IsDBNull(1) ? null : r.GetString(1);
        return (real ?? rfs, r.IsDBNull(2) ? null : r.GetInt32(2));
    }

    /// <summary>The market ticker with identities: latest moves, fees and faces.</summary>
    public IReadOnlyList<(long PlayerId, string Player, string ToTeam, long Fee)> TransfersFeed(int count = 8)
    {
        var rows = new List<(long, string, string, long)>();
        using var cmd = Db.Connection.CreateCommand();
        // ONLY MOVES THAT TOUCH THE CAREER'S OWN TWO DIVISIONS.
        //
        // THE BUG THIS REPLACES: the query was "ORDER BY t.rowid DESC LIMIT n" over the whole
        // table. The seed imports the real world's transfer history — 26,040 rows on this save —
        // and those land last, so a rail headed AROUND THE MARKET listed nine moves into
        // "Skala 2", "Ormeau 21" and "Somerville Eagles 21": foreign reserve sides, from before
        // the career began, presented as this week's news. The one genuine line (a signing by a
        // Premier League club) sat on top of them and looked like more of the same.
        //
        // A career club at either end is what makes a transfer news to this manager — his
        // rivals buying, or one of them selling abroad. The seeded history touches neither end.
        cmd.CommandText =
            "SELECT t.player_id, p.name, t.to_team_id, t.fee FROM transfers t " +
            "JOIN players p ON p.id = t.player_id " +
            "WHERE t.to_team_id IS NOT NULL AND (" +
            "  EXISTS (SELECT 1 FROM teams x WHERE x.id = t.to_team_id   AND x.league_id IN ($l1,$l2))" +
            "  OR EXISTS (SELECT 1 FROM teams y WHERE y.id = t.from_team_id AND y.league_id IN ($l1,$l2)))" +
            "ORDER BY t.rowid DESC LIMIT $n";
        cmd.Parameters.AddWithValue("$l1", TopFlight);
        cmd.Parameters.AddWithValue("$l2", Division2);
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            rows.Add((r.GetInt64(0), r.GetString(1), TeamName(r.GetInt32(2)),
                r.IsDBNull(3) ? 0 : r.GetInt64(3)));
        }
        return rows;
    }

    public int UnreadCount()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM inbox WHERE is_read=0";
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    public void MarkInboxRead()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE inbox SET is_read=1 WHERE is_read=0";
        cmd.ExecuteNonQuery();
    }

    /// <summary>First-run seed so a fresh career opens with a welcome, not an empty inbox.</summary>
    public void EnsureInboxWelcome()
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT COUNT(*) FROM inbox";
            if (Convert.ToInt32(q.ExecuteScalar()) > 0) return;
        }
        PostInbox("Board", $"Welcome to {CurrentTeamName}",
            $"Chairman {Chairman()} welcomes you. The board expects a {Board.Expectation} finish in " +
            $"the {LeagueName}. The squad, the academy and the training ground are yours.",
            teamId: CurrentTeamId);
        PostInbox("Media", $"{CupName} draw made",
            "The cup bracket is set — check the Cup screen for your road to the final.");
    }

    /// <summary>
    /// Post the aftermath of YOUR recorded result: press reaction, new injuries, milestones.
    /// Called once per recorded fixture from the dashboard flow.
    /// </summary>
    public void PostMatchInbox(int fixtureId, int homeId, int awayId, int matchday,
        int homeGoals, int awayGoals, string kind)
    {
        var youAreHome = homeId == CurrentTeamId;
        var us = youAreHome ? homeGoals : awayGoals;
        var them = youAreHome ? awayGoals : homeGoals;
        var opp = TeamName(youAreHome ? awayId : homeId);
        var comp = kind == "cup"
            ? CupNameFor(Repo.Fixtures(SeasonId).FirstOrDefault(f => f.Id == fixtureId)?.LeagueId ?? CupLeague)
            : kind == "friendly" ? "Friendly" : LeagueName;
        var headline = us > them
            ? $"{CurrentTeamName} beat {opp} {us}-{them}"
            : us == them
                ? $"{CurrentTeamName} held {us}-{them} by {opp}"
                : $"{opp} defeat {CurrentTeamName} {them}-{us}";
        var body = us > them
            ? "The press praise a professional performance. The dressing room is up."
            : us == them ? "Points shared. The papers call it \"a fair result\"."
            : "The back pages are not kind. A response is expected next time out.";
        PostInbox("Media", $"{comp}: {headline}", body, matchday,
            teamId: youAreHome ? awayId : homeId);   // the opponent's crest fronts the story

        // New injuries from this matchweek (rows whose comeback lies ahead).
        var hurt = Repo.ConditionsFor(CurrentTeamId)
            .Where(c => c.InjuredUntilMd is int u && u > matchday).ToList();
        if (hurt.Count > 0)
        {
            var names = Repo.SquadPlayers(CurrentTeamId).ToDictionary(p => p.Id, p => p.Name);
            var lines = hurt.Select(c =>
                $"{names.GetValueOrDefault(c.PlayerId, "A player")} (back ~MD{c.InjuredUntilMd})");
            PostInbox("Player", "Medical report",
                $"In the treatment room: {string.Join(", ", lines)}. The AI team sheet works around them.",
                matchday, teamId: CurrentTeamId);
        }

        // Training milestones surfaced by this matchweek's session.
        foreach (var note in LastTrainingNotes.Where(n => n.Contains("learned")))
        {
            PostInbox("Player", "Training ground report", note, matchday, teamId: CurrentTeamId);
        }

        // The assistant's tactical debrief (only when one is on the books).
        try
        {
            var debrief = AssistantDebrief(fixtureId, homeId, awayId);
            if (debrief.Length > 0)
            {
                PostInbox("Media", "Assistant's debrief", debrief, matchday, teamId: CurrentTeamId);
            }
        }
        catch { /* the debrief is a bonus, never a blocker */ }

        // Contract warnings late in the season.
        if (kind == "league" && matchday >= 30)
        {
            var expiring = Repo.SquadPlayers(CurrentTeamId)
                .Where(p => ContractYear(p.Id) <= 2026 + (SeasonId - 9000))
                .Select(p => p.Name).Take(6).ToList();
            if (expiring.Count > 0 && GetMeta($"warn_contracts_{SeasonId}") is null)
            {
                PostInbox("Board", "Contracts expiring",
                    $"Out of contract this summer: {string.Join(", ", expiring)}. Renew them from the " +
                    "Squad screen or lose them on frees.", matchday, teamId: CurrentTeamId);
                SetMeta($"warn_contracts_{SeasonId}", "1");
            }
        }
    }

    /// <summary>Season review posted at rollover, before the new season resets state.</summary>
    public void PostSeasonReview(string champion, int finalPosition, string movement)
    {
        var scorers = LeadersBy("goal", 1);
        var golden = scorers.Count > 0 ? $"{scorers[0].Player} took the golden boot ({scorers[0].Count})." : "";
        var cup = GetMeta($"cup_winner_{CupLeague}_{SeasonId}") is { } cw && int.TryParse(cw, out var cid)
            ? $"{TeamName(cid)} lifted the {CupName}." : "";
        if (GetMeta($"cup_winner_{LeagueCupId}_{SeasonId}") is { } lw && int.TryParse(lw, out var lid2))
        {
            cup += $" {TeamName(lid2)} took the {LeagueCupName}.";
        }
        PostInbox("Board", $"Season review — you finished {Ordinal(finalPosition)}",
            $"{champion} were champions. {golden} {cup}{movement} " +
            "The market has moved, the academy intake has arrived, and offers are on your desk.",
            teamId: CurrentTeamId);
    }

    private static string Ordinal(int n) => n switch
    {
        0 => "unplaced",
        11 or 12 or 13 => $"{n}th",
        _ when n % 10 == 1 => $"{n}st",
        _ when n % 10 == 2 => $"{n}nd",
        _ when n % 10 == 3 => $"{n}rd",
        _ => $"{n}th",
    };
}
