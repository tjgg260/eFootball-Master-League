namespace ML.App;

public sealed record StaffMember(string Role, string Name, int Quality, int Wage);

/// <summary>
/// The backroom (FM parity phase A1): one hire per role, paid weekly, with real effects —
/// a good coach speeds training, a good physio shortens injuries, the assistant explains
/// XI suggestions, and the scout gates report depth (phase A2).
/// </summary>
public sealed partial class Session
{
    public static readonly string[] StaffRoles = { "Assistant", "Coach", "Scout", "Physio" };

    private static readonly string[] StaffFirst =
        { "Marco", "Steve", "Jurgen", "Paulo", "Kenny", "Ivan", "Didier", "Rafael", "Tomas", "Gareth" };
    private static readonly string[] StaffLast =
        { "Keane", "Vidic", "Molina", "Berger", "Sanchez", "Novak", "Toure", "Eriksen", "Costa", "Marsh" };

    public StaffMember? StaffFor(string role)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT name, quality, wage FROM staff WHERE team_id=$t AND role=$r";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$r", role);
        using var r = cmd.ExecuteReader();
        return r.Read() ? new StaffMember(role, r.GetString(0), r.GetInt32(1), r.GetInt32(2)) : null;
    }

    public IReadOnlyList<StaffMember> AllStaff() =>
        StaffRoles.Select(StaffFor).Where(s => s is not null).Select(s => s!).ToList();

    /// <summary>Three deterministic candidates per role per season — better ones cost more.</summary>
    public IReadOnlyList<StaffMember> StaffCandidates(string role)
    {
        var list = new List<StaffMember>();
        for (var i = 0; i < 3; i++)
        {
            var seed = (uint)((SeasonId * 131 + role.Length * 17 + i * 7919 + CurrentTeamId) * 2654435761);
            var quality = 1 + (int)(seed % 5);
            var name = $"{StaffFirst[(int)(seed / 5 % 10)]} {StaffLast[(int)(seed / 50 % 10)]}";
            list.Add(new StaffMember(role, name, quality, 1000 + quality * 1500));
        }
        return list.OrderByDescending(s => s.Quality).ToList();
    }

    public string HireStaff(StaffMember candidate)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO staff(team_id,role,name,quality,wage) VALUES($t,$r,$n,$q,$w) " +
                          "ON CONFLICT(team_id,role) DO UPDATE SET name=$n, quality=$q, wage=$w";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$r", candidate.Role);
        cmd.Parameters.AddWithValue("$n", candidate.Name);
        cmd.Parameters.AddWithValue("$q", candidate.Quality);
        cmd.Parameters.AddWithValue("$w", candidate.Wage);
        cmd.ExecuteNonQuery();
        PostInbox("Board", $"New {candidate.Role.ToLowerInvariant()} hired",
            $"{candidate.Name} ({new string('★', candidate.Quality)}) joins the backroom at " +
            $"£{candidate.Wage:N0}/week.");
        return $"{candidate.Name} hired as {candidate.Role} — £{candidate.Wage:N0}/week joins the bill.";
    }

    public string FireStaff(string role)
    {
        var current = StaffFor(role);
        if (current is null) return "Nobody in that role.";
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "DELETE FROM staff WHERE team_id=$t AND role=$r";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$r", role);
        cmd.ExecuteNonQuery();
        return $"{current.Name} released from {role}.";
    }

    /// <summary>Weekly staff wages — folded into the financial overview + matchweek debit.</summary>
    public long StaffWages() => AllStaff().Sum(s => (long)s.Wage);

    /// <summary>A 4★+ coach shaves a week off every training cadence.</summary>
    public int CoachTrainingBonus() => (StaffFor("Coach")?.Quality ?? 0) >= 4 ? 1 : 0;

    /// <summary>A 3★+ physio brings players back a matchday sooner.</summary>
    public int PhysioRecoveryBonus() => (StaffFor("Physio")?.Quality ?? 0) >= 3 ? 1 : 0;

    /// <summary>
    /// The assistant's post-match debrief (FM phase A3): where the goals came from on both
    /// sides, built from the recorded match events. Empty when no assistant is hired.
    /// </summary>
    public string AssistantDebrief(int fixtureId, int homeTeamId, int awayTeamId)
    {
        if (StaffFor("Assistant") is not { } asst) return "";
        var mySquad = Repo.Squad(CurrentTeamId).Select(m => m.PlayerId).ToHashSet();
        var scorers = new List<(string Name, bool Mine)>();
        var assists = new List<string>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT e.event_type, e.player_id, p.name FROM match_events e " +
                              "JOIN players p ON p.id=e.player_id WHERE e.fixture_id=$f " +
                              "AND e.event_type IN ('goal','assist') ORDER BY e.id";
            cmd.Parameters.AddWithValue("$f", fixtureId);
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                if (r.GetString(0) == "goal")
                {
                    scorers.Add((r.GetString(2), mySquad.Contains(r.GetInt32(1))));
                }
                else if (mySquad.Contains(r.GetInt32(1)))
                {
                    assists.Add(r.GetString(2));
                }
            }
        }
        var parts = new List<string>();
        var ours = scorers.Where(s => s.Mine).Select(s => s.Name).ToList();
        var theirs = scorers.Where(s => !s.Mine).Select(s => s.Name).ToList();
        if (ours.Count > 0) parts.Add($"Our goals: {string.Join(", ", ours)}.");
        if (assists.Count > 0) parts.Add($"Created by: {string.Join(", ", assists)}.");
        if (theirs.Count > 0) parts.Add($"Their damage came from {string.Join(", ", theirs)} — worth a scouting look.");
        if (parts.Count == 0) parts.Add("Not much in it either way — the clean sheets tell the story.");
        return $"{asst.Name}'s debrief: {string.Join(" ", parts)}";
    }

    /// <summary>Assistant's one-line reasoning for the suggested XI (named absences).</summary>
    public string AssistantNote(int matchday)
    {
        if (StaffFor("Assistant") is not { } asst) return "";
        var conditions = Repo.ConditionsFor(CurrentTeamId);
        var names = Repo.SquadPlayers(CurrentTeamId).ToDictionary(p => p.Id, p => p.Name);
        var outList = conditions.Where(c => c.InjuredUntilMd is int u && u >= matchday)
            .Select(c => names.GetValueOrDefault(c.PlayerId, "?")).Take(3).ToList();
        var tired = conditions.Where(c => c.Fatigue >= 40 && !(c.InjuredUntilMd is int u2 && u2 >= matchday))
            .Select(c => names.GetValueOrDefault(c.PlayerId, "?")).Take(3).ToList();
        var parts = new List<string>();
        if (outList.Count > 0) parts.Add($"out: {string.Join(", ", outList)}");
        if (tired.Count > 0) parts.Add($"needing a rest: {string.Join(", ", tired)}");
        return parts.Count == 0
            ? $"{asst.Name}: \"Everyone's available and fresh — strongest XI it is.\""
            : $"{asst.Name}: \"Picked around the problems — {string.Join("; ", parts)}.\"";
    }
}
