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

    /// <summary>Knowledge 0-100: stored level (scouting, meetings) or the derived baseline.</summary>
    public int KnowledgeOf(long playerId)
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
        var (sameLeague, otherDiv) = (GetMeta("mask_strict") ?? "Standard") switch
        {
            "Relaxed" => (60, 40),
            "Strict" => (25, 10),
            _ => (40, 25),
        };
        var league = TeamCache.TryGetValue(teamId, out var t) ? t.LeagueId : null;
        return league == LeagueId ? sameLeague : league is TopFlight or Division2 ? otherDiv : 0;
    }

    public void BumpKnowledge(long playerId, int floor)
    {
        var level = Math.Clamp(Math.Max(KnowledgeOf(playerId), floor), 0, 100);
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
            BumpKnowledge(m.PlayerId, Math.Min(100, KnowledgeOf(m.PlayerId) + 15));
        }
    }

    public string KnowledgeLabelOf(long playerId) =>
        AttributeKnowledge.KnowledgeLabel(KnowledgeOf(playerId));

    // ------------------------------------------------------------------ reports (forever)

    /// <summary>The coach's verbal read — only quotes what your knowledge has revealed.</summary>
    public IReadOnlyList<string> CoachReportOf(long playerId, string position)
    {
        var abilities = Repo.Attributes(playerId);
        if (abilities.Count == 0) return Array.Empty<string>();
        return AttributeKnowledge.CoachReport(
            playerId, abilities, position == "GK", KnowledgeOf(playerId));
    }

    /// <summary>The analyst's numbers line: what the season data says (knowledge-gated).</summary>
    public string AnalystLineOf(long playerId)
    {
        if (KnowledgeOf(playerId) < 45) return "";
        try
        {
            var (apps, goals, assists, _, _, avg) = PlayerSeasonStats(playerId);
            if (apps == 0) return "Analyst: no competitive minutes on record this season.";
            var parts = new List<string> { $"{apps} apps" };
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
