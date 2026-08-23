using System.Text;

namespace ML.App;

public sealed record ScoutJob(long Id, string Kind, int TargetId, int ReadyMd, bool Done);

/// <summary>
/// Scouting (FM phase A2): assign your scout to a club or a player; the report is ready two
/// matchdays later and lands in the inbox. Report DEPTH scales with the scout's quality:
/// 1–2★ shape and style only · 3★ + likely XI · 4★+ ratings, threats and condition.
/// </summary>
public sealed partial class Session
{
    public const int ScoutMatchdays = 2;

    public ScoutJob? ActiveScoutJob()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT id, kind, target_id, ready_md, done FROM scout_jobs " +
                          "WHERE done=0 ORDER BY id DESC LIMIT 1";
        using var r = cmd.ExecuteReader();
        return r.Read()
            ? new ScoutJob(r.GetInt64(0), r.GetString(1), r.GetInt32(2), r.GetInt32(3), false)
            : null;
    }

    public IReadOnlyList<ScoutJob> CompletedScoutJobs(int count = 8)
    {
        var jobs = new List<ScoutJob>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT id, kind, target_id, ready_md, done FROM scout_jobs " +
                          "WHERE done=1 ORDER BY id DESC LIMIT $n";
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            jobs.Add(new ScoutJob(r.GetInt64(0), r.GetString(1), r.GetInt32(2), r.GetInt32(3), true));
        }
        return jobs;
    }

    /// <summary>Send the scout out. One mission at a time; needs a scout on the books.</summary>
    public string StartScoutJob(string kind, int targetId, string targetName)
    {
        if (StaffFor("Scout") is null)
        {
            return "You have no scout — hire one on the Staff screen first.";
        }
        if (ActiveScoutJob() is not null)
        {
            return "Your scout is already on a mission — one at a time.";
        }
        var md = NextFixture()?.Matchday ?? 0;
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO scout_jobs(kind,target_id,started_md,ready_md,done) " +
                          "VALUES($k,$t,$s,$r,0)";
        cmd.Parameters.AddWithValue("$k", kind);
        cmd.Parameters.AddWithValue("$t", targetId);
        cmd.Parameters.AddWithValue("$s", md);
        cmd.Parameters.AddWithValue("$r", md + ScoutMatchdays);
        cmd.ExecuteNonQuery();
        return $"Scout dispatched to watch {targetName} — report ready in {ScoutMatchdays} matchdays.";
    }

    /// <summary>Mature due missions (called from the matchday pass) — report lands in the inbox.</summary>
    public void CheckScoutJobs(int matchday)
    {
        var due = new List<(long Id, string Kind, int Target)>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT id, kind, target_id FROM scout_jobs WHERE done=0 AND ready_md<=$m";
            q.Parameters.AddWithValue("$m", matchday);
            using var r = q.ExecuteReader();
            while (r.Read()) due.Add((r.GetInt64(0), r.GetString(1), r.GetInt32(2)));
        }
        foreach (var (id, kind, target) in due)
        {
            using (var u = Db.Connection.CreateCommand())
            {
                u.CommandText = "UPDATE scout_jobs SET done=1 WHERE id=$id";
                u.Parameters.AddWithValue("$id", id);
                u.ExecuteNonQuery();
            }
            var name = kind == "club" ? TeamName(target) : PlayerNameOf(target);
            // Scouting IS knowledge (P5): a player dossier reveals him; a club dossier
            // part-reveals their whole squad.
            try
            {
                if (kind == "player")
                {
                    BumpKnowledge(target, 90);
                }
                else
                {
                    foreach (var m in Repo.Squad(target)) BumpKnowledge(m.PlayerId, 60);
                }
            }
            catch { /* knowledge is additive */ }
            PostInbox("Media", $"Scout report ready: {name}",
                "The dossier is on your desk — open the Scouting screen to read it.", matchday);
        }
    }

    /// <summary>Has a completed club dossier for this opponent (any age — intel keeps).</summary>
    public bool HasClubReport(int teamId) =>
        CompletedScoutJobs(50).Any(j => j.Kind == "club" && j.TargetId == teamId);

    /// <summary>
    /// The pre-match briefing for the dashboard (FM phase C3): only when the club has been
    /// scouted. Suggestion configures YOUR compile only — the opponent's in-game AI is untouched.
    /// </summary>
    public (bool Scouted, string Summary, string Suggestion) OppositionBriefingFor(int oppId)
    {
        if (!HasClubReport(oppId))
        {
            return (false, "", "");
        }
        var styleIx = Repo.TeamTactics(oppId).FirstOrDefault(t => t.Phase == 0)?.Style ?? 0;
        string[] styles = { "Possession Game", "Quick Counter", "Long Ball Counter", "Long Ball", "Out Wide", "Overload" };
        var threat = Repo.SquadPlayers(oppId).OrderByDescending(p => p.OverallRating ?? 0).FirstOrDefault();
        var summary = $"Dossier: they play {styles[Math.Clamp(styleIx, 0, 5)]}" +
                      (threat is not null ? $"; the man to stop is {threat.Name}." : ".");
        var (shape, style, line) = ML.Core.Selection.OppositionBriefing.Counter(styleIx);
        return (true, summary, $"Scout's plan: {line} (Try {shape}, {style} — sets up YOUR side only.)");
    }

    private string PlayerNameOf(int playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT name FROM players WHERE id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        return cmd.ExecuteScalar() as string ?? "?";
    }

    /// <summary>The club dossier, depth-gated by scout quality.</summary>
    public string ClubScoutReport(int teamId)
    {
        var quality = StaffFor("Scout")?.Quality ?? 1;
        var sb = new StringBuilder();
        sb.AppendLine($"SCOUT REPORT — {TeamName(teamId)}  (scout: {new string('★', quality)})");
        sb.AppendLine();

        var (fid0, _) = OwnFormationIds(teamId);
        var shape = Formations.ShapeOf(Repo.FormationSlots(fid0).Select(s => s.Y));
        var styleIx = Repo.TeamTactics(teamId).FirstOrDefault(t => t.Phase == 0)?.Style ?? 0;
        string[] styles = { "Possession Game", "Quick Counter", "Long Ball Counter", "Long Ball", "Out Wide", "Overload" };
        sb.AppendLine($"Shape: {shape}   Playstyle: {styles[Math.Clamp(styleIx, 0, 5)]}   Standing: {ClubTier(teamId)}");

        if (quality >= 3)
        {
            sb.AppendLine();
            sb.AppendLine("Likely XI (their current pecking order):");
            var xi = Repo.Squad(teamId).Where(m => m.Slot is >= 0 and <= 10).OrderBy(m => m.Slot).ToList();
            var players = Repo.SquadPlayers(teamId).ToDictionary(p => p.Id);
            foreach (var m in xi)
            {
                if (!players.TryGetValue(m.PlayerId, out var p)) continue;
                sb.AppendLine(quality >= 4
                    ? $"  {p.Position,-4} {p.Name}  {ML.Core.Development.AttributeKnowledge.Grade(p.OverallRating ?? 0)}"
                    : $"  {p.Position,-4} {p.Name}");
            }
        }
        if (quality >= 4)
        {
            sb.AppendLine();
            sb.AppendLine("Key threats:");
            var conditions = Repo.ConditionsFor(teamId).ToDictionary(c => c.PlayerId);
            foreach (var p in Repo.SquadPlayers(teamId)
                         .OrderByDescending(p => p.OverallRating ?? 0).Take(3))
            {
                conditions.TryGetValue(p.Id, out var c);
                var goals = GoalsThisSeason(p.Id);
                var legs = c?.Fatigue switch { >= 70 => ", running on empty", >= 40 => ", looking leggy", _ => "" };
                var cond = quality >= 5 && c is not null
                    ? $"{legs}{(c.InjuredUntilMd is not null ? ", INJURED" : "")}"
                    : "";
                sb.AppendLine($"  {p.Name} ({p.Position}, {ML.Core.Development.AttributeKnowledge.Grade(p.OverallRating ?? 0)}) — {goals} goals{cond}");
            }
        }
        if (quality <= 2)
        {
            sb.AppendLine();
            sb.AppendLine("A better scout would name their likely XI and key threats.");
        }
        return sb.ToString();
    }

    /// <summary>The player dossier, depth-gated by scout quality, with a fit verdict.</summary>
    public string PlayerScoutReport(int playerId)
    {
        var quality = StaffFor("Scout")?.Quality ?? 1;
        string name = "?", position = "CMF";
        int rating = 0;
        int? age = null;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT name, position, COALESCE(overall_rating,0), age FROM players WHERE id=$p";
            q.Parameters.AddWithValue("$p", playerId);
            using var r = q.ExecuteReader();
            if (r.Read())
            {
                name = r.GetString(0);
                position = r.GetString(1);
                rating = r.GetInt32(2);
                age = r.IsDBNull(3) ? null : r.GetInt32(3);
            }
        }
        var sb = new StringBuilder();
        sb.AppendLine($"SCOUT REPORT — {name}  ({position}, {ML.Core.Development.AttributeKnowledge.Grade(rating)})  (scout: {new string('★', quality)})");
        sb.AppendLine($"Age {age?.ToString() ?? "—"}   Value £{MarketValueOf(playerId, rating, age):N0}");

        if (quality >= 3)
        {
            var abilities = Repo.Attributes(playerId);
            var top = abilities.Where(a => !a.Key.StartsWith("gk_") || position == "GK")
                .OrderByDescending(a => a.Value).Take(5)
                .Select(a => $"{a.Key.Replace('_', ' ')} {ML.Core.Development.AttributeKnowledge.Grade(a.Value)}");
            sb.AppendLine($"Standout abilities: {string.Join(", ", top)}");
        }
        // Fit verdict vs your current best in that position.
        var incumbent = Repo.SquadPlayers(CurrentTeamId)
            .Where(p => p.Position == position)
            .OrderByDescending(p => p.OverallRating ?? 0).FirstOrDefault();
        sb.AppendLine();
        sb.AppendLine(incumbent is null
            ? $"Verdict: you have nobody registered at {position} — an obvious gap he'd fill."
            : rating > (incumbent.OverallRating ?? 0) + 2
                ? $"Verdict: clear upgrade on {incumbent.Name}."
                : rating >= (incumbent.OverallRating ?? 0) - 2
                    ? $"Verdict: comparable to {incumbent.Name} — squad depth."
                    : $"Verdict: below {incumbent.Name} — not worth the fee.");
        return sb.ToString();
    }
}
