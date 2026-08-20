using ML.Core;
using ML.Core.Management;
using ML.Data;

namespace ML.App;

public sealed record ObjectiveRow(
    long Id, string Kind, int Target, string Importance, int Status, string Description, string Progress);

/// <summary>
/// FM-style board &amp; fan objectives (P2): at each season start the board issues concrete
/// objectives with importance tiers, derived from where the squad ranks. A mid-season review
/// and a season-end verdict feed board confidence, sacking pressure, reputation and next
/// season's backing. The fans keep their own ledger: results move a persistent happiness
/// score that blends with the positional FansFeeling gauge.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ generation

    /// <summary>Issue this season's objectives if none exist yet (called from the ctor).</summary>
    public void EnsureObjectives()
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT COUNT(*) FROM objectives WHERE season_id=$s AND team_id=$t";
            q.Parameters.AddWithValue("$s", SeasonId);
            q.Parameters.AddWithValue("$t", CurrentTeamId);
            if (Convert.ToInt32(q.ExecuteScalar()) > 0) return;
        }

        var teams = Math.Max(LeagueTeams().Count, 2);
        var finishTarget = ManagerCareer.TargetPosition(Board.Expectation, teams);
        var rng = new SeededRandom((SeasonId * 12889 + CurrentTeamId) ^ WorldSeed);

        void Add(string kind, int target, string importance)
        {
            using var ins = Db.Connection.CreateCommand();
            ins.CommandText = "INSERT INTO objectives(season_id,team_id,kind,target,importance,status) " +
                              "VALUES($s,$t,$k,$g,$i,0)";
            ins.Parameters.AddWithValue("$s", SeasonId);
            ins.Parameters.AddWithValue("$t", CurrentTeamId);
            ins.Parameters.AddWithValue("$k", kind);
            ins.Parameters.AddWithValue("$g", target);
            ins.Parameters.AddWithValue("$i", importance);
            ins.ExecuteNonQuery();
        }

        Add("league_finish", finishTarget, "critical");
        // Cup ambition scales with the league demand: strong sides must reach the last 8.
        Add("cup_run", finishTarget <= teams / 3 ? 8 : 16, "important");
        Add("youth_apps", 6 + rng.Next(5), "bonus");        // starts by players 21 or under
        Add("home_goals", 18 + rng.Next(9), "bonus");       // the fans want entertaining

        PostInbox("Board", "The board sets this season's objectives",
            $"Chairman {Chairman()} lays it out:\n" +
            string.Join("\n", Objectives().Select(o => $"• {o.Description}  [{o.Importance}]")) +
            "\nA mid-season review comes at matchday 19; the final verdict at the season's end.");
    }

    // ------------------------------------------------------------------ reading + progress

    public IReadOnlyList<ObjectiveRow> Objectives()
    {
        var rows = new List<ObjectiveRow>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT id, kind, target, importance, status FROM objectives " +
                          "WHERE season_id=$s AND team_id=$t ORDER BY " +
                          "CASE importance WHEN 'critical' THEN 0 WHEN 'important' THEN 1 ELSE 2 END";
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var kind = r.GetString(1);
            var target = r.GetInt32(2);
            rows.Add(new ObjectiveRow(r.GetInt64(0), kind, target, r.GetString(3), r.GetInt32(4),
                DescribeObjective(kind, target), ProgressOf(kind, target)));
        }
        return rows;
    }

    private string DescribeObjective(string kind, int target) => kind switch
    {
        "league_finish" => $"Finish {Ordinal(target)} or better in the {LeagueName}",
        "cup_run" => $"Reach the {RoundName(target)} in a cup",
        "youth_apps" => $"Give players 21 or under {target} starts",
        "home_goals" => $"Score {target} league goals at home — the fans want a show",
        _ => kind,
    };

    private static string RoundName(int size) => size switch
    {
        <= 2 => "final", 4 => "semi-finals", 8 => "quarter-finals", _ => "round of 16",
    };

    private string ProgressOf(string kind, int target) => kind switch
    {
        "league_finish" => CurrentPosition() is var p and > 0
            ? $"currently {Ordinal(p)}" : "season not started",
        "cup_run" => BestCupRunSize() is { } best
            ? best <= target ? $"reached (best: {RoundName(best)})" : $"best so far: {RoundName(best)}"
            : "no cup ties yet",
        "youth_apps" => $"{YouthStarts()} of {target}",
        "home_goals" => $"{HomeLeagueGoals()} of {target}",
        _ => "",
    };

    /// <summary>The deepest round (by entrant count) any of your cup ties reached this season.</summary>
    private int? BestCupRunSize()
    {
        int? best = null;
        foreach (var f in Repo.Fixtures(SeasonId).Where(f => f.Kind == "cup"
                     && (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId)))
        {
            var size = Cups.SelectMany(c => c.Rounds)
                .FirstOrDefault(rd => rd.Matchday == f.Matchday).Size;
            if (size > 0 && (best is null || size < best)) best = size;
            // Winning the final counts as size 1 ("won it").
            if (size == 2 && f.Played && CupWinnerOf(f) == CurrentTeamId) best = 1;
        }
        return best;
    }

    private int YouthStarts()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT COUNT(*) FROM match_events e " +
            "JOIN fixtures f ON f.id=e.fixture_id " +
            "JOIN players p ON p.id=e.player_id " +
            "JOIN squad_members s ON s.player_id=e.player_id AND s.team_id=$t " +
            "WHERE e.event_type='app' AND f.season_id=$s AND COALESCE(p.age, 25) <= 21";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$s", SeasonId);
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    private int HomeLeagueGoals()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT COALESCE(SUM(r.home_goals),0) FROM results r JOIN fixtures f ON f.id=r.fixture_id " +
            "WHERE f.season_id=$s AND f.kind='league' AND f.home_team_id=$t";
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    // ------------------------------------------------------------------ review + verdict

    /// <summary>Mid-season board review (fires once, after matchday 19's pass).</summary>
    public void MidSeasonReview(int matchday)
    {
        if (matchday != 19 || GetMeta($"objreview_{SeasonId}") is not null) return;
        var lines = Objectives()
            .Select(o => $"• {o.Description} — {o.Progress}  [{o.Importance}]").ToList();
        var pos = CurrentPosition();
        var teams = Math.Max(LeagueTeams().Count, 2);
        var onTrack = pos > 0 && pos <= ManagerCareer.TargetPosition(Board.Expectation, teams);
        StoredBoardConfidence += onTrack ? 3 : -4;
        PostInbox("Board", "Mid-season review",
            (onTrack
                ? $"Chairman {Chairman()} is satisfied at the halfway mark."
                : $"Chairman {Chairman()} expected more by now — the second half of the season matters.")
            + "\n\n" + string.Join("\n", lines), matchday);
        SetMeta($"objreview_{SeasonId}", "1");
    }

    /// <summary>
    /// Season-end verdict: settle every objective, move the board and your reputation, and
    /// let met criticals unlock extra backing for next season.
    /// </summary>
    public void EvaluateObjectives(int finalPosition)
    {
        var met = 0;
        var failedCritical = false;
        foreach (var o in Objectives())
        {
            var achieved = o.Kind switch
            {
                "league_finish" => finalPosition > 0 && finalPosition <= o.Target,
                "cup_run" => BestCupRunSize() is { } b && b <= o.Target,
                "youth_apps" => YouthStarts() >= o.Target,
                "home_goals" => HomeLeagueGoals() >= o.Target,
                _ => false,
            };
            using var upd = Db.Connection.CreateCommand();
            upd.CommandText = "UPDATE objectives SET status=$st WHERE id=$id";
            upd.Parameters.AddWithValue("$st", achieved ? 1 : 2);
            upd.Parameters.AddWithValue("$id", o.Id);
            upd.ExecuteNonQuery();

            var swing = (o.Importance, achieved) switch
            {
                ("critical", true) => +8, ("critical", false) => -12,
                ("important", true) => +5, ("important", false) => -5,
                (_, true) => +3, _ => 0,
            };
            StoredBoardConfidence += swing;
            if (achieved) met++;
            if (!achieved && o.Importance == "critical") failedCritical = true;
        }

        var verdictLines = Objectives()
            .Select(o => $"{(o.Status == 1 ? "✅" : "❌")} {o.Description}").ToList();
        var backing = 0L;
        if (met >= 3 && !failedCritical)
        {
            backing = 2_000_000;
            Finances.ReceivePrize(backing);
            AdjustBudget(backing);
        }
        Reputation += met >= 3 ? 2 : failedCritical ? -2 : 0;
        PostInbox("Board", "Season verdict from the board",
            string.Join("\n", verdictLines) +
            (backing > 0
                ? $"\n\nThe board is delighted — £{backing:N0} of extra backing lands in the budget."
                : failedCritical
                    ? "\n\nThe critical objective was missed. Patience is not infinite."
                    : "\n\nA mixed year. The bar does not move."));
    }

    // ------------------------------------------------------------------ the fans (P2)

    /// <summary>Persistent fan ledger 0-100: results move it, the gauge blends it with form.</summary>
    private int FanLedger
    {
        get => int.TryParse(GetMeta($"fans_{CurrentTeamId}"), out var v) ? v : 55;
        set => SetMeta($"fans_{CurrentTeamId}", Math.Clamp(value, 0, 100).ToString());
    }

    /// <summary>Called with every one of YOUR recorded results.</summary>
    public void ApplyFansAfterResult(int homeId, int awayId, int homeGoals, int awayGoals, string kind)
    {
        if (kind == "friendly") return;
        var home = homeId == CurrentTeamId;
        var us = home ? homeGoals : awayGoals;
        var them = home ? awayGoals : homeGoals;
        var delta = us > them
            ? (home ? 4 : 3) + (us >= 3 ? 2 : 0)     // wins lift; a show at home lifts more
            : us == them ? (home ? -1 : 1)
            : home ? -5 : -3;                          // losing at home stings hardest
        FanLedger += delta;
    }

    /// <summary>The fan gauge: half long-memory ledger, half current position/form feeling.</summary>
    public int FanHappiness() => (FanLedger + FansFeeling()) / 2;

    public string FanLabel => FanHappiness() switch
    {
        >= 80 => "Adoring", >= 65 => "Happy", >= 50 => "Content",
        >= 35 => "Restless", >= 20 => "Angry", _ => "Mutinous",
    };
}
