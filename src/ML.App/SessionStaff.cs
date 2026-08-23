using Microsoft.Data.Sqlite;
using ML.Core;

namespace ML.App;

/// <summary>Legacy summary shape — kept so scout/morale/report call sites stay stable.</summary>
public sealed record StaffMember(string Role, string Name, int Quality, int Wage);

/// <summary>One person from the staff database, attributes 1-20 (FM-style).</summary>
public sealed record StaffPerson(
    long Id, string Name, int Age, string Role,
    int Coaching, int Youth, int Fitness, int Physio,
    int JudgingAbility, int JudgingPotential, int Tactical, int ManManagement,
    string PrefFormation, string PrefStyle, int Wage, int? TeamId, int? ContractUntil,
    int StylePossession = 10, int StyleQuickCounter = 10, int StyleLongBallCounter = 10,
    int StyleLongBall = 10, int StyleOutWide = 10, int StyleOverload = 10)
{
    /// <summary>Strengths in the game's six tactical styles, strongest first.</summary>
    public IReadOnlyList<(string Style, int Strength)> StyleStrengths => new[]
    {
        ("Possession Game", StylePossession), ("Quick Counter", StyleQuickCounter),
        ("Long Ball Counter", StyleLongBallCounter), ("Long Ball", StyleLongBall),
        ("Out Wide", StyleOutWide), ("Overload", StyleOverload),
    }.OrderByDescending(s => s.Item2).ToList();

    public string BestStyle => StyleStrengths[0].Style;

    public int StrengthIn(string style) =>
        StyleStrengths.FirstOrDefault(s => s.Style == style).Strength;

    /// <summary>The attribute that defines competence in this person's role.</summary>
    public int KeyAttribute => Role switch
    {
        "Assistant Manager" => Tactical,
        "Director of Football" => JudgingAbility,
        "Coach" => Coaching,
        "GK Coach" => Coaching,
        "Fitness Coach" => Fitness,
        "Youth Coach" => Youth,
        "Physio" => Physio,
        "Scout" => JudgingAbility,
        "Analyst" => Tactical,
        _ => Coaching,
    };

    /// <summary>1-5 stars derived from the key attribute (20-scale ÷ 4).</summary>
    public int Stars => Math.Clamp((KeyAttribute + 3) / 4, 1, 5);

    public string StyleLine =>
        $"prefers {PrefFormation} · best style: {BestStyle} {StyleStrengths[0].Strength}";
}

/// <summary>
/// The staff database (FM-style): a persistent world pool of individual people with 1-20
/// attributes and tactical preferences. Hire one per role, delegate responsibilities, and the
/// attributes drive real effects — training speed, injury recovery, intake quality, report
/// depth, renewals and target-finding when the Director of Football has the keys.
/// </summary>
public sealed partial class Session
{
    public static readonly string[] StaffRoles =
    {
        "Assistant Manager", "Director of Football", "Coach", "GK Coach",
        "Fitness Coach", "Youth Coach", "Physio", "Scout", "Analyst",
    };

    /// <summary>The game's six team playstyles - the only tactical vocabulary we use.</summary>
    public static readonly string[] TacticalStyles =
        { "Possession Game", "Quick Counter", "Long Ball Counter", "Long Ball", "Out Wide", "Overload" };

    private static readonly string[] StaffFormations =
        { "4-3-3", "4-2-3-1", "4-4-2", "3-5-2", "5-3-2", "4-1-2-3", "3-4-3" };

    // ------------------------------------------------------------------ the pool

    /// <summary>Seed the world's staff pool once per career (deterministic from the seed).</summary>
    public void EnsureStaffPool()
    {
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT COUNT(*) FROM staff_people";
            if (Convert.ToInt32(q.ExecuteScalar()) > 0) return;
        }
        var rng = new SeededRandom(777_001 ^ WorldSeed);

        // Real FM staff first (real names + real ratings); the synthetic pool only tops up shortfalls.
        var real = new Dictionary<string, int>();
        try { real = SeedRealStaffPool(); } catch { /* fall back to fully synthetic */ }

        // Real coach names first (Coach.bin pool), synthetic fill after.
        var names = new List<string>();
        try
        {
            using var n = Db.Connection.CreateCommand();
            n.CommandText = "SELECT name FROM coach_names ORDER BY name";
            using var r = n.ExecuteReader();
            while (r.Read()) names.Add(r.GetString(0));
        }
        catch { /* pool falls back to synthetic names */ }
        for (var i = names.Count; i < 400; i++) names.Add($"Staff Member {i + 1}");
        // Deterministic shuffle so careers don't all hire the same alphabet.
        for (var i = names.Count - 1; i > 0; i--)
        {
            var j = rng.Next(i + 1);
            (names[i], names[j]) = (names[j], names[i]);
        }

        var counts = new (string Role, int N)[]
        {
            ("Assistant Manager", 28), ("Director of Football", 16), ("Coach", 44),
            ("GK Coach", 20), ("Fitness Coach", 20), ("Youth Coach", 24),
            ("Physio", 24), ("Scout", 28), ("Analyst", 16),
        };
        var next = 0;
        int Attr(bool key) => key ? 8 + rng.Next(12) : 3 + rng.Next(12);
        foreach (var (role, count) in counts)
        {
            var shortfall = Math.Max(0, count - real.GetValueOrDefault(role, 0));
            for (var i = 0; i < shortfall; i++)
            {
                // Style strengths: a modest base everywhere and one clear speciality.
                var styles = new int[6];
                for (var k = 0; k < 6; k++) styles[k] = 3 + rng.Next(11);
                var special = rng.Next(6);
                styles[special] = 13 + rng.Next(8);
                var person = new StaffPerson(
                    0, names[next++ % names.Count], 33 + rng.Next(30), role,
                    Attr(role is "Coach" or "GK Coach" or "Assistant Manager"),
                    Attr(role is "Youth Coach"),
                    Attr(role is "Fitness Coach"),
                    Attr(role is "Physio"),
                    Attr(role is "Scout" or "Director of Football"),
                    Attr(role is "Scout" or "Youth Coach" or "Director of Football"),
                    Attr(role is "Assistant Manager" or "Analyst"),
                    Attr(role is "Assistant Manager" or "Director of Football"),
                    StaffFormations[rng.Next(StaffFormations.Length)],
                    TacticalStyles[special],
                    0, null, null,
                    styles[0], styles[1], styles[2], styles[3], styles[4], styles[5]);
                InsertStaffPerson(person with { Wage = 600 + person.KeyAttribute * 190 + rng.Next(400) });
            }
        }

        // Carry over anything hired under the old 4-role system so nobody loses their backroom.
        MigrateLegacyStaff();
    }

    private void InsertStaffPerson(StaffPerson p)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "INSERT INTO staff_people(name,age,role,coaching,youth,fitness,physio,judging_ability," +
            "judging_potential,tactical,man_management,pref_formation,pref_style,wage,team_id,contract_until," +
            "style_possession,style_quick_counter,style_long_ball_counter,style_long_ball," +
            "style_out_wide,style_overload) " +
            "VALUES($n,$a,$r,$c,$y,$f,$ph,$ja,$jp,$ta,$mm,$pf,$ps,$w,$t,$cu,$s1,$s2,$s3,$s4,$s5,$s6)";
        cmd.Parameters.AddWithValue("$n", p.Name);
        cmd.Parameters.AddWithValue("$a", p.Age);
        cmd.Parameters.AddWithValue("$r", p.Role);
        cmd.Parameters.AddWithValue("$c", p.Coaching);
        cmd.Parameters.AddWithValue("$y", p.Youth);
        cmd.Parameters.AddWithValue("$f", p.Fitness);
        cmd.Parameters.AddWithValue("$ph", p.Physio);
        cmd.Parameters.AddWithValue("$ja", p.JudgingAbility);
        cmd.Parameters.AddWithValue("$jp", p.JudgingPotential);
        cmd.Parameters.AddWithValue("$ta", p.Tactical);
        cmd.Parameters.AddWithValue("$mm", p.ManManagement);
        cmd.Parameters.AddWithValue("$pf", p.PrefFormation);
        cmd.Parameters.AddWithValue("$ps", p.PrefStyle);
        cmd.Parameters.AddWithValue("$w", p.Wage);
        cmd.Parameters.AddWithValue("$t", (object?)p.TeamId ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$cu", (object?)p.ContractUntil ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$s1", p.StylePossession);
        cmd.Parameters.AddWithValue("$s2", p.StyleQuickCounter);
        cmd.Parameters.AddWithValue("$s3", p.StyleLongBallCounter);
        cmd.Parameters.AddWithValue("$s4", p.StyleLongBall);
        cmd.Parameters.AddWithValue("$s5", p.StyleOutWide);
        cmd.Parameters.AddWithValue("$s6", p.StyleOverload);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Old `staff` table hires become real people at the same club, role-mapped.</summary>
    private void MigrateLegacyStaff()
    {
        var legacy = new List<(int Team, string Role, string Name, int Quality, int Wage)>();
        try
        {
            using var q = Db.Connection.CreateCommand();
            q.CommandText = "SELECT team_id, role, name, quality, wage FROM staff";
            using var r = q.ExecuteReader();
            while (r.Read())
                legacy.Add((r.GetInt32(0), r.GetString(1), r.GetString(2), r.GetInt32(3), r.GetInt32(4)));
        }
        catch { return; }
        foreach (var (team, role, name, quality, wage) in legacy)
        {
            var mapped = role == "Assistant" ? "Assistant Manager" : role;
            var attr = Math.Clamp(quality * 4, 4, 20);
            InsertStaffPerson(new StaffPerson(0, name, 40 + quality * 3, mapped,
                attr, attr - 2, attr - 2, mapped == "Physio" ? attr : attr - 4,
                attr - 2, attr - 3, attr - 1, attr - 2,
                "4-3-3", "Balanced", wage, team, SeasonId + 1));
        }
        using var del = Db.Connection.CreateCommand();
        del.CommandText = "DELETE FROM staff";
        del.ExecuteNonQuery();
    }

    private static StaffPerson ReadStaffPerson(SqliteDataReader r) => new(
        r.GetInt64(0), r.GetString(1), r.GetInt32(2), r.GetString(3),
        r.GetInt32(4), r.GetInt32(5), r.GetInt32(6), r.GetInt32(7),
        r.GetInt32(8), r.GetInt32(9), r.GetInt32(10), r.GetInt32(11),
        r.GetString(12), r.GetString(13), r.GetInt32(14),
        r.IsDBNull(15) ? null : r.GetInt32(15),
        r.IsDBNull(16) ? null : r.GetInt32(16),
        r.GetInt32(17), r.GetInt32(18), r.GetInt32(19),
        r.GetInt32(20), r.GetInt32(21), r.GetInt32(22));

    private const string StaffColumns =
        "id,name,age,role,coaching,youth,fitness,physio,judging_ability,judging_potential," +
        "tactical,man_management,pref_formation,pref_style,wage,team_id,contract_until," +
        "style_possession,style_quick_counter,style_long_ball_counter,style_long_ball," +
        "style_out_wide,style_overload";

    // ------------------------------------------------------------------ reading

    /// <summary>Your person in a role, or null while the desk sits empty.</summary>
    public StaffPerson? StaffPersonFor(string role)
    {
        EnsureStaffPool();
        var mapped = role == "Assistant" ? "Assistant Manager" : role;
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = $"SELECT {StaffColumns} FROM staff_people WHERE team_id=$t AND role=$r LIMIT 1";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$r", mapped);
        using var r = cmd.ExecuteReader();
        return r.Read() ? ReadStaffPerson(r) : null;
    }

    /// <summary>Legacy accessor — same shape the scout/morale/report code always used.</summary>
    public StaffMember? StaffFor(string role) =>
        StaffPersonFor(role) is { } p ? new StaffMember(role, p.Name, p.Stars, p.Wage) : null;

    public IReadOnlyList<StaffPerson> MyBackroom()
    {
        EnsureStaffPool();
        var rows = new List<StaffPerson>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = $"SELECT {StaffColumns} FROM staff_people WHERE team_id=$t ORDER BY role";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(ReadStaffPerson(r));
        return rows;
    }

    /// <summary>Free agents for a role, best first — the hiring shortlist.</summary>
    public IReadOnlyList<StaffPerson> StaffMarket(string role, int count = 8)
    {
        EnsureStaffPool();
        var rows = new List<StaffPerson>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = $"SELECT {StaffColumns} FROM staff_people " +
                          "WHERE role=$r AND team_id IS NULL ORDER BY " +
                          "CASE role WHEN 'Physio' THEN physio WHEN 'Fitness Coach' THEN fitness " +
                          "WHEN 'Youth Coach' THEN youth WHEN 'Scout' THEN judging_ability " +
                          "WHEN 'Director of Football' THEN judging_ability " +
                          "WHEN 'Assistant Manager' THEN tactical WHEN 'Analyst' THEN tactical " +
                          "ELSE coaching END DESC LIMIT $n";
        cmd.Parameters.AddWithValue("$r", role);
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(ReadStaffPerson(r));
        return rows;
    }

    // ------------------------------------------------------------------ hiring + firing

    /// <summary>Hire a free agent: 2-year deal, replaces (and releases) any current holder.</summary>
    public string HireStaffPerson(long staffId)
    {
        StaffPerson? p = null;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = $"SELECT {StaffColumns} FROM staff_people WHERE id=$id";
            q.Parameters.AddWithValue("$id", staffId);
            using var r = q.ExecuteReader();
            if (r.Read()) p = ReadStaffPerson(r);
        }
        if (p is null) return "That person is no longer available.";
        if (p.TeamId is not null && p.TeamId != CurrentTeamId)
            return $"{p.Name} is under contract elsewhere — only free agents can be approached.";
        if (p.TeamId == CurrentTeamId) return $"{p.Name} already works for you.";

        var incumbent = StaffPersonFor(p.Role);
        if (incumbent is not null) ReleaseStaff(incumbent.Id, quiet: true);

        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE staff_people SET team_id=$t, contract_until=$cu WHERE id=$id";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$cu", SeasonId + 2);
        cmd.Parameters.AddWithValue("$id", staffId);
        cmd.ExecuteNonQuery();
        PostInbox("Club", $"New {p.Role.ToLowerInvariant()}: {p.Name}",
            $"{p.Name} ({p.Age}) joins the backroom — {new string('★', p.Stars)} · " +
            $"{p.StyleLine} · £{p.Wage:N0}/week." +
            (incumbent is not null ? $" {incumbent.Name} leaves to make room." : ""));
        return $"{p.Name} hired as {p.Role} — £{p.Wage:N0}/week joins the bill.";
    }

    /// <summary>Release a person back into the pool (they keep existing as a free agent).</summary>
    public string ReleaseStaff(long staffId, bool quiet = false)
    {
        string? name = null;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT name FROM staff_people WHERE id=$id AND team_id=$t";
            q.Parameters.AddWithValue("$id", staffId);
            q.Parameters.AddWithValue("$t", CurrentTeamId);
            name = q.ExecuteScalar() as string;
        }
        if (name is null) return "Not one of yours.";
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE staff_people SET team_id=NULL, contract_until=NULL WHERE id=$id";
        cmd.Parameters.AddWithValue("$id", staffId);
        cmd.ExecuteNonQuery();
        if (!quiet) PostInbox("Club", $"{name} released",
            $"{name} leaves the club and returns to the market.");
        return $"{name} released.";
    }

    /// <summary>Legacy role-based fire, used by older call sites.</summary>
    public string FireStaff(string role) =>
        StaffPersonFor(role) is { } p ? ReleaseStaff(p.Id) : "Nobody in that role.";

    // ------------------------------------------------------------------ delegation

    public static readonly (string Key, string Label)[] Delegations =
    {
        ("delegate_xi", "Assistant Manager picks the matchday XI"),
        ("delegate_renewals", "Director of Football handles contract renewals"),
        ("delegate_targets", "Director of Football suggests transfer targets"),
        ("delegate_opposition", "Scout files a report on every next opponent"),
        ("delegate_rest", "Fitness Coach manages recovery for tired players"),
    };

    public bool DelegationOn(string key) => GetMeta($"{key}_{CurrentTeamId}") == "1";

    public void SetDelegation(string key, bool on) =>
        SetMeta($"{key}_{CurrentTeamId}", on ? "1" : "0");

    /// <summary>Which role must be filled for a delegation to actually run.</summary>
    public static string DelegationRole(string key) => key switch
    {
        "delegate_xi" => "Assistant Manager",
        "delegate_renewals" or "delegate_targets" => "Director of Football",
        "delegate_opposition" => "Scout",
        "delegate_rest" => "Fitness Coach",
        _ => "Assistant Manager",
    };

    /// <summary>The weekly delegation pass — every switched-on duty with a filled desk runs.</summary>
    public void RunStaffDelegation(int matchday)
    {
        // DoF renewals: quietly extends expiring deals for anyone at/above the squad's median.
        if (DelegationOn("delegate_renewals") && StaffPersonFor("Director of Football") is { } dof)
        {
            var squad = Repo.SquadPlayers(CurrentTeamId).ToList();
            if (squad.Count > 0)
            {
                var median = squad.OrderBy(p => p.OverallRating ?? 0)
                    .ElementAt(squad.Count / 2).OverallRating ?? 0;
                var renewed = new List<string>();
                foreach (var p in squad.Where(p => (p.OverallRating ?? 0) >= median))
                {
                    if (ContractExpiresThisSeason(p.Id) && renewed.Count < 3)
                    {
                        var note = RenewContract(p.Id);
                        if (note.Contains("renew", StringComparison.OrdinalIgnoreCase) ||
                            note.Contains("sign", StringComparison.OrdinalIgnoreCase))
                            renewed.Add(p.Name);
                    }
                }
                if (renewed.Count > 0)
                    PostInbox("Club", $"{dof.Name} ties down expiring contracts",
                        $"The Director of Football renewed: {string.Join(", ", renewed)}.", matchday);
            }
        }

        // DoF targets: every 4th matchday, a shortlist picked by judging ability.
        if (DelegationOn("delegate_targets") && matchday % 4 == 0 &&
            StaffPersonFor("Director of Football") is { } dof2)
        {
            var noise = 21 - dof2.JudgingAbility;   // a poor judge sees a blurrier market
            var rng = new SeededRandom((SeasonId * 733 + matchday) ^ WorldSeed);
            var targets = Repo.Teams()
                .Where(t => t.Id != CurrentTeamId)
                .SelectMany(t => Repo.SquadPlayers(t.Id).Select(p => (Team: t.Name, P: p)))
                .Where(x => (x.P.OverallRating ?? 0) >= 68 && (x.P.Age ?? 30) <= 27)
                .OrderByDescending(x => (x.P.OverallRating ?? 0) + rng.Next(noise))
                .Take(3).ToList();
            if (targets.Count > 0)
                PostInbox("Transfer", $"{dof2.Name}'s transfer shortlist",
                    "Names worth watching this window:\n" + string.Join("\n",
                        targets.Select(x =>
                            $"• {x.P.Name} ({x.P.Position}, {x.P.Age}) — {x.Team}, " +
                            $"~£{ValuationOf(x.P.OverallRating ?? 60, x.P.Age ?? 25):N0}")),
                    matchday);
        }

        // Scout files a report on the next opponent when no job is already running.
        if (DelegationOn("delegate_opposition") && StaffPersonFor("Scout") is not null)
        {
            try
            {
                if (ActiveScoutJob() is null && NextFixture() is { } next && next.Kind != "friendly")
                {
                    var opp = next.HomeTeamId == CurrentTeamId ? next.AwayTeamId : next.HomeTeamId;
                    StartScoutJob("club", opp, TeamName(opp));
                }
            }
            catch { /* scouting is additive */ }
        }

        // Fitness coach: tired legs recover faster under a good programme.
        if (DelegationOn("delegate_rest") && StaffPersonFor("Fitness Coach") is { } fit)
        {
            var relief = 2 + fit.Fitness / 5;   // 2-6 fatigue per week
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText = "UPDATE player_condition SET fatigue = MAX(0, fatigue - $x) " +
                              "WHERE fatigue >= 35 AND player_id IN " +
                              "(SELECT player_id FROM squad_members WHERE team_id=$t)";
            cmd.Parameters.AddWithValue("$x", relief);
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            cmd.ExecuteNonQuery();
        }
    }

    /// <summary>True when a stored deal runs out at this season's end (no row = unknown = false).</summary>
    private bool ContractExpiresThisSeason(long playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT expires_season FROM contracts WHERE player_id=$p AND team_id=$t";
        q.Parameters.AddWithValue("$p", playerId);
        q.Parameters.AddWithValue("$t", CurrentTeamId);
        return q.ExecuteScalar() is long exp && exp <= SeasonId;
    }

    // ------------------------------------------------------------------ attribute-driven effects

    /// <summary>Weekly staff wages — folded into the financial overview + matchweek debit.</summary>
    public long StaffWages() => MyBackroom().Sum(s => (long)s.Wage);

    /// <summary>A strong coach (14+) shaves a week off every training cadence.</summary>
    public int CoachTrainingBonus() => (StaffPersonFor("Coach")?.Coaching ?? 0) >= 14 ? 1 : 0;

    /// <summary>Physio skill brings players back sooner: 0-2 matchdays off every layoff.</summary>
    public int PhysioRecoveryBonus() => (StaffPersonFor("Physio")?.Physio ?? 0) / 8;

    /// <summary>Youth Coach lifts the academy intake floor (stacks with the academy building).</summary>
    public int YouthCoachIntakeBonus() => (StaffPersonFor("Youth Coach")?.Youth ?? 0) >= 13 ? 2 : 0;

    /// <summary>GK Coach: goalkeepers develop faster under a proper specialist.</summary>
    public double GkCoachMultiplier(long playerId)
    {
        var coach = StaffPersonFor("GK Coach");
        if (coach is null || coach.Coaching < 12) return 1.0;
        var pos = Repo.SquadPlayers(CurrentTeamId).FirstOrDefault(p => p.Id == playerId)?.Position;
        return pos == "GK" ? 1.25 : 1.0;
    }

    /// <summary>
    /// The assistant's tactical read of the next opponent, in the game's own style vocabulary —
    /// including whether the club's current playstyle is one they can actually drill.
    /// </summary>
    public string AssistantTacticalNote(int opponentId)
    {
        if (StaffPersonFor("Assistant Manager") is not { } asst) return "";
        var oppElo = EloOf(opponentId);
        var ours = EloOf(CurrentTeamId);
        var read = asst.Tactical >= 14
            ? oppElo > ours + 40
                ? $"they're the stronger side — {asst.BestStyle} would frustrate them"
                : oppElo < ours - 40
                    ? "we should dictate — get on the ball high up the pitch"
                    : "an even contest — small margins, set pieces matter"
            : "hard to call this one";
        var fit = "";
        try
        {
            if (CurrentClubStyle() is { } style)
            {
                var s = asst.StrengthIn(style);
                fit = s >= 14 ? $" {style} is his speciality ({s}/20) — the sessions show it."
                    : s <= 7 ? $" Note: {style} is not his game ({s}/20)."
                    : "";
            }
        }
        catch { /* style fit is decoration */ }
        return $"{asst.Name} ({asst.StyleLine}): \"{read}.\"{fit}";
    }

    /// <summary>
    /// The assistant's post-match debrief: where the goals came from on both sides,
    /// built from the recorded match events. Empty when no assistant is hired.
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
