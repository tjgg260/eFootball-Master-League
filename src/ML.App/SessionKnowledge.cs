using ML.Core.Development;
using ML.Data;

namespace ML.App;

/// <summary>
/// FM-style player knowledge (P5): how much of a player you can actually SEE. Your own squad
/// and academy are fully known; league rivals are part-known and sharpen every time you face
/// them; everyone else is a blank until scouted. The FM display toggle (colour bands + masking
/// instead of raw numbers) lives here too. Coach/scout/analyst reports are permanent features.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ the display toggle

    /// <summary>FM mode: colour bands + knowledge masking instead of raw numbers.
    /// ON by default (UX P4) — raw numbers are the opt-in, not the qualitative view.</summary>
    public bool FmAttributeMode
    {
        get => GetMeta("attr_fm_mode") != "0";
        set => SetMeta("attr_fm_mode", value ? "1" : "0");
    }

    // ------------------------------------------------------------------ knowledge

    /// <summary>
    /// Knowledge 0-100 — everything you can see of a player, from any source at all: what you
    /// have scouted, who he plays near you, and what the football world already says about him.
    /// The three combine as a MAXIMUM, so no source can ever make you know less.
    /// </summary>
    public int KnowledgeOf(long playerId) => Math.Clamp(
        Math.Max(ScoutedKnowledgeOf(playerId), FameKnowledgeOf(playerId)), 0, 100);

    /// <summary>
    /// Knowledge your CLUB has earned — scouting reports, matches played, and the proximity of
    /// men in your own league. Fame is deliberately excluded: this is the number the app gates
    /// the scouted half of a dossier on (character, ceiling, the coach's read on his flaws), and
    /// being famous must never buy any of it. Nor is fame ever written to player_knowledge, so
    /// changing the masking strictness still moves it.
    /// </summary>
    public int ScoutedKnowledgeOf(long playerId)
    {
        var stored = 0;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT level FROM player_knowledge WHERE player_id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            var v = q.ExecuteScalar();
            if (v is not null and not DBNull) stored = Convert.ToInt32(v);
        }
        return Math.Clamp(Math.Max(stored, BaselineKnowledge(playerId)), 0, 100);
    }

    /// <summary>What his reputation alone hands you, before anyone at your club has watched
    /// him once. Everyone in the world knows Mbappé is rapid and can finish.</summary>
    public int FameKnowledgeOf(long playerId) =>
        PlayerReputation.KnowledgeFloor(ReputationOf(playerId), Strictness);

    /// <summary>What you know without ever scouting: your club fully, your league partly.
    /// The Settings masking strictness moves the baselines (Relaxed/Standard/Strict).</summary>
    private int BaselineKnowledge(long playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText =
            "SELECT COALESCE((SELECT s.team_id FROM squad_members s WHERE s.player_id=$p LIMIT 1), " +
            "(SELECT a.team_id FROM academy a WHERE a.player_id=$p LIMIT 1))";
        q.Parameters.AddWithValue("$p", playerId);
        var v = q.ExecuteScalar();
        if (v is null or DBNull) return 0;
        var teamId = Convert.ToInt32(v);
        if (teamId == CurrentTeamId) return 100;
        var (sameLeague, otherDiv) = Strictness switch
        {
            MaskingStrictness.Relaxed => (60, 40),
            MaskingStrictness.Strict => (25, 10),
            _ => (40, 25),
        };
        var league = TeamCache.TryGetValue(teamId, out var t) ? t.LeagueId : null;
        return league == LeagueId ? sameLeague : league is TopFlight or Division2 ? otherDiv : 0;
    }

    /// <summary>The Settings masking triple, as the engine's enum.</summary>
    private MaskingStrictness Strictness => (GetMeta("mask_strict") ?? "Standard") switch
    {
        "Relaxed" => MaskingStrictness.Relaxed,
        "Strict" => MaskingStrictness.Strict,
        _ => MaskingStrictness.Standard,
    };

    public void BumpKnowledge(long playerId, int floor)
    {
        // Base on SCOUTED knowledge, never total: writing a fame floor into player_knowledge
        // would freeze it there and make the strictness setting a one-way ratchet.
        var level = Math.Clamp(Math.Max(ScoutedKnowledgeOf(playerId), floor), 0, 100);
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO player_knowledge(player_id,level) VALUES($p,$l) " +
                          "ON CONFLICT(player_id) DO UPDATE SET level=MAX(level, excluded.level)";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$l", level);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Facing a club teaches you their XI (called when your result is recorded).</summary>
    public void LearnOpponentFromMatch(int opponentTeamId)
    {
        foreach (var m in Repo.Squad(opponentTeamId).Where(m => m.Slot is >= 0 and <= 10))
        {
            // +15 on what you have WATCHED. Ninety minutes against a famous man teaches you as
            // much as ninety minutes against anyone; his reputation was never yours to earn.
            BumpKnowledge(m.PlayerId, Math.Min(100, ScoutedKnowledgeOf(m.PlayerId) + 15));
        }
    }

    public string KnowledgeLabelOf(long playerId) =>
        AttributeKnowledge.KnowledgeLabel(KnowledgeOf(playerId));

    // ------------------------------------------------------------------ world reputation

    private readonly Dictionary<long, int> _reputationCache = new();
    private readonly Dictionary<long, RevealOrder> _revealOrderCache = new();
    private object? _reputationCacheEpoch;
    private bool _reputationEpochSeen;
    private int _reputationQueryMode;      // 0 untried · 1 full ladder · 2 rating only

    /// <summary>
    /// Reputation is read off a player's rating, his price, his caps and his CLUB, so it goes
    /// stale for exactly the same reasons the team cache does: transfers, loans, promotion,
    /// season rollover. The app already drops _teamCache at every one of those points, so the
    /// reputation memo rides on that same signal rather than needing a second set of hooks
    /// somebody would one day forget to add.
    /// </summary>
    private void SyncReputationEpoch()
    {
        if (_reputationEpochSeen && ReferenceEquals(_teamCache, _reputationCacheEpoch)) return;
        _reputationCache.Clear();
        _revealOrderCache.Clear();
        _reputationCacheEpoch = _teamCache;
        _reputationEpochSeen = true;
    }

    /// <summary>Drop one player's memoised reputation — after his rating or his price moves.</summary>
    public void ForgetReputationOf(long playerId)
    {
        _reputationCache.Remove(playerId);
        _revealOrderCache.Remove(playerId);
    }

    /// <summary>
    /// How famous a player is in the world, 0-100 — independent of your club entirely. Memoised
    /// per session: the Market resolves this for every row it paints.
    /// </summary>
    public int ReputationOf(long playerId)
    {
        SyncReputationEpoch();
        if (_reputationCache.TryGetValue(playerId, out var cached)) return cached;
        var score = 0;
        try { score = PlayerReputation.Score(ReputationInputsFor(playerId)); }
        catch (Exception ex) { Program.Log("Session.ReputationOf", ex); }
        _reputationCache[playerId] = score;
        return score;
    }

    /// <summary>The world reputation said out loud, or "" for a man nobody has heard of.</summary>
    public string FameLabelOf(long playerId) =>
        PlayerReputation.FameLabel(ReputationOf(playerId));

    /// <summary>
    /// Read the five signals. Club standing comes off the ladder the world was built with:
    /// his squad row to team_identity to fm_clubs.reputation, and where that join is empty
    /// (a club with no FM identity) his own player_market.squad_rep, which is a per-player TEXT
    /// copy of the same number. A missing signal stays NULL — never 0, which would read as
    /// "worthless" rather than "unknown".
    /// </summary>
    private ReputationInputs ReputationInputsFor(long playerId)
    {
        if (_reputationQueryMode != 2)
        {
            try
            {
                using var cmd = Db.Connection.CreateCommand();
                cmd.CommandText =
                    "SELECT COALESCE(p.overall_rating,0), m.value, m.int_caps, " +
                    "       m.perceived_status, m.squad_rep, " +
                    "       (SELECT f.reputation FROM squad_members s " +
                    "          JOIN team_identity ti ON ti.team_id = s.team_id " +
                    "          JOIN fm_clubs f ON f.uid = ti.fm_club_id " +
                    "         WHERE s.player_id = p.id LIMIT 1) " +
                    "  FROM players p LEFT JOIN player_market m ON m.player_id = p.id " +
                    " WHERE p.id = $p";
                cmd.Parameters.AddWithValue("$p", playerId);
                using var r = cmd.ExecuteReader();
                _reputationQueryMode = 1;
                if (!r.Read()) return new ReputationInputs(0, null, null, null, null);
                var clubRep = r.IsDBNull(5) ? null : (int?)Convert.ToInt32(r.GetValue(5));
                // squad_rep is TEXT and sometimes decimal ("6600.0"), sometimes junk.
                if (clubRep is null && !r.IsDBNull(4) &&
                    double.TryParse(r.GetValue(4)?.ToString(),
                                    System.Globalization.NumberStyles.Any,
                                    System.Globalization.CultureInfo.InvariantCulture, out var sr))
                {
                    clubRep = (int)sr;
                }
                return new ReputationInputs(
                    Convert.ToInt32(r.GetValue(0)),
                    r.IsDBNull(1) ? null : Convert.ToInt64(r.GetValue(1)),
                    r.IsDBNull(2) ? null : Convert.ToInt32(r.GetValue(2)),
                    clubRep,
                    r.IsDBNull(3) ? null : r.GetValue(3)?.ToString());
            }
            catch
            {
                // A world seeded without the FM identity tables. Fall back for good — ability
                // alone still separates a superstar from a reserve.
                _reputationQueryMode = 2;
            }
        }

        using var basic = Db.Connection.CreateCommand();
        basic.CommandText = "SELECT COALESCE(overall_rating,0) FROM players WHERE id=$p";
        basic.Parameters.AddWithValue("$p", playerId);
        var v = basic.ExecuteScalar();
        return new ReputationInputs(
            v is null or DBNull ? 0 : Convert.ToInt32(v), null, null, null, null);
    }

    /// <summary>
    /// The order this player's abilities become visible in — his standouts first in proportion
    /// to his fame, the plain hash for anyone the world has not heard of. Hand this to the
    /// attribute masking and a famous man gives up his headline before his flaws.
    /// </summary>
    public RevealOrder RevealOrderOf(long playerId, string position)
    {
        SyncReputationEpoch();
        if (_revealOrderCache.TryGetValue(playerId, out var cached)) return cached;
        RevealOrder order;
        try
        {
            var reputation = ReputationOf(playerId);
            order = reputation <= 0
                ? RevealOrder.Anonymous(playerId)
                : RevealOrder.For(playerId, Repo.Attributes(playerId),
                                  position == "GK", reputation);
        }
        catch (Exception ex)
        {
            Program.Log("Session.RevealOrderOf", ex);
            order = RevealOrder.Anonymous(playerId);
        }
        _revealOrderCache[playerId] = order;
        return order;
    }

    /// <summary>
    /// What the game knows him for, in a coach's words — "his pace and his finishing". Empty
    /// when nothing about him is public. Used for the copy on an unscouted famous player, which
    /// must not claim nobody has watched him.
    /// </summary>
    public string FameHeadlineOf(long playerId, string position)
    {
        var nouns = RevealOrderOf(playerId, position)
            .Headline(KnowledgeOf(playerId), 2)
            .Select(AttributeKnowledge.Noun)
            .ToList();
        return nouns.Count switch
        {
            0 => "",
            1 => $"his {nouns[0]}",
            _ => $"his {nouns[0]} and his {nouns[1]}",
        };
    }

    // ------------------------------------------------------------------ reports (forever)

    /// <summary>The coach's verbal read — only quotes what your knowledge has revealed. For a
    /// famous player that means the praise arrives free and the flaws still cost a scout.</summary>
    public IReadOnlyList<string> CoachReportOf(long playerId, string position)
    {
        var abilities = Repo.Attributes(playerId);
        if (abilities.Count == 0) return Array.Empty<string>();
        return AttributeKnowledge.CoachReport(
            playerId, abilities, position == "GK", KnowledgeOf(playerId),
            RevealOrderOf(playerId, position));
    }

    /// <summary>The analyst's numbers line: what the season data says (knowledge-gated).</summary>
    public string AnalystLineOf(long playerId)
    {
        if (KnowledgeOf(playerId) < 45) return "";
        try
        {
            var (apps, goals, assists, _, _, avg) = PlayerSeasonStats(playerId);
            if (apps == 0) return "Analyst: no competitive minutes on record this season.";
            var parts = new List<string> { Visuals.Plural(apps, "app") };
            if (goals > 0) parts.Add($"{(double)goals / apps:0.00} goals/app");
            if (assists > 0) parts.Add($"{assists} assists");
            if (avg is { } a) parts.Add($"{a:0.0} av rating");
            using var q = Db.Connection.CreateCommand();
            q.CommandText = "SELECT form FROM player_condition WHERE player_id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            if (q.ExecuteScalar() is double form)
            {
                parts.Add(form >= 7.2 ? "trending up" : form <= 5.8 ? "out of form" : "steady");
            }
            return "Analyst: " + string.Join(" · ", parts) + ".";
        }
        catch { return ""; }
    }
}
