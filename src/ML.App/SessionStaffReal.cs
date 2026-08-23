namespace ML.App;

/// <summary>
/// Populates the staff pool from the REAL imported FM staff (fm_staff_attributes + fm_raw_staff)
/// instead of synthetic dice: real names, real coaching/judging/physio ratings, real preferred
/// formations. The hire pool becomes actual football coaches. Any role that comes up short is
/// topped up by the synthetic generator, so the pool is always full.
/// </summary>
public sealed partial class Session
{
    // FM Job text -> our staff role. First match wins; order matters (Assistant before Manager).
    private static readonly (string Needle, string Role)[] JobRoleMap =
    {
        ("Assistant Manager", "Assistant Manager"),
        ("Director of Football", "Director of Football"),
        ("Sporting Director", "Director of Football"),
        ("Technical Director", "Director of Football"),
        ("Goalkeeping Coach", "GK Coach"),
        ("Fitness Coach", "Fitness Coach"),
        ("Sports Scientist", "Fitness Coach"),
        ("Under-18", "Youth Coach"),
        ("Under-21", "Youth Coach"),
        ("Youth", "Youth Coach"),
        ("Head of Youth", "Youth Coach"),
        ("Physio", "Physio"),
        ("Scout", "Scout"),
        ("Chief Scout", "Scout"),
        ("Analyst", "Analyst"),
        ("Coach", "Coach"),
    };

    private static string? RoleForJob(string job)
    {
        foreach (var (needle, role) in JobRoleMap)
            if (job.Contains(needle, StringComparison.OrdinalIgnoreCase))
                return role;
        return null;
    }

    /// <summary>How many real staff to keep per role in the hire pool.</summary>
    private static readonly Dictionary<string, int> RoleTarget = new()
    {
        ["Assistant Manager"] = 40, ["Director of Football"] = 24, ["Coach"] = 70,
        ["GK Coach"] = 30, ["Fitness Coach"] = 30, ["Youth Coach"] = 36,
        ["Physio"] = 34, ["Scout"] = 40, ["Analyst"] = 24,
    };

    /// <summary>Seed the pool from real FM staff. Returns how many were inserted per role so the
    /// caller can synth-fill the rest.</summary>
    public Dictionary<string, int> SeedRealStaffPool()
    {
        var filled = RoleTarget.Keys.ToDictionary(r => r, _ => 0);

        // identities: uid -> (name, age, job)
        var ident = new Dictionary<long, (string Name, int Age, string Job)>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT key, col, val FROM fm_raw_staff WHERE col IN ('Name','Age','Job')";
            using var r = q.ExecuteReader();
            var tmp = new Dictionary<long, Dictionary<string, string>>();
            while (r.Read())
            {
                if (!long.TryParse(r.GetString(0), out var uid)) continue;
                if (!tmp.TryGetValue(uid, out var d)) tmp[uid] = d = new Dictionary<string, string>();
                d[r.GetString(1)] = r.GetString(2);
            }
            foreach (var (uid, d) in tmp)
            {
                if (!d.TryGetValue("Name", out var nm) || !d.TryGetValue("Job", out var job)) continue;
                int.TryParse(d.GetValueOrDefault("Age", "40"), out var age);
                ident[uid] = (nm, age == 0 ? 45 : age, job);
            }
        }
        if (ident.Count == 0) return filled;   // no real staff imported

        // attributes: uid -> {attr: value}
        var attrs = new Dictionary<long, Dictionary<string, int>>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT uid, attr, value FROM fm_staff_attributes";
            using var r = q.ExecuteReader();
            while (r.Read())
            {
                var uid = r.GetInt64(0);
                if (!attrs.TryGetValue(uid, out var m)) attrs[uid] = m = new Dictionary<string, int>();
                m[r.GetString(1)] = r.GetInt32(2);
            }
        }

        int A(Dictionary<string, int> m, params string[] keys)
        {
            var best = 0;
            foreach (var k in keys) if (m.TryGetValue(k, out var v)) best = Math.Max(best, v);
            return best;
        }

        // Rank candidates per role by the attribute that matters, keep the best N.
        var byRole = new Dictionary<string, List<(long Uid, int Score)>>();
        foreach (var (uid, id) in ident)
        {
            var role = RoleForJob(id.Job);
            if (role is null || !attrs.TryGetValue(uid, out var m)) continue;
            var score = role switch
            {
                "GK Coach" => A(m, "coaching_gk_shot_stopping", "coaching_gk_handling"),
                "Fitness Coach" => A(m, "coaching_fitness"),
                "Youth Coach" => A(m, "working_with_youngsters"),
                "Physio" => A(m, "physiotherapy", "sports_science"),
                "Scout" => A(m, "judging_player_ability", "judging_player_potential"),
                "Director of Football" => A(m, "negotiating", "judging_player_ability"),
                "Analyst" => A(m, "analysing_data", "tactical_knowledge"),
                _ => A(m, "coaching_technical", "coaching_tactical", "coaching_mental"),
            };
            if (!byRole.TryGetValue(role, out var lst)) byRole[role] = lst = new List<(long, int)>();
            lst.Add((uid, score));
        }

        foreach (var (role, target) in RoleTarget)
        {
            if (!byRole.TryGetValue(role, out var cands)) continue;
            foreach (var (uid, _) in cands.OrderByDescending(c => c.Score).Take(target))
            {
                var id = ident[uid];
                var m = attrs[uid];
                var styles = new int[6];
                for (var k = 0; k < 6; k++) styles[k] = 8;   // real tactical-style splits are TODO
                var coaching = A(m, "coaching_technical", "coaching_tactical", "coaching_mental",
                                 "coaching_attacking", "coaching_defending");
                var person = new StaffPerson(
                    0, id.Name, Math.Clamp(id.Age, 28, 72), role,
                    coaching == 0 ? 8 : coaching,
                    Math.Max(1, A(m, "working_with_youngsters")),
                    Math.Max(1, A(m, "coaching_fitness")),
                    Math.Max(1, A(m, "physiotherapy", "sports_science")),
                    Math.Max(1, A(m, "judging_player_ability")),
                    Math.Max(1, A(m, "judging_player_potential")),
                    Math.Max(1, A(m, "tactical_knowledge")),
                    Math.Max(1, A(m, "man_management")),
                    StaffFormations[(int)(uid % StaffFormations.Length)],
                    TacticalStyles[(int)(uid % TacticalStyles.Length)],
                    0, null, null,
                    styles[0], styles[1], styles[2], styles[3], styles[4], styles[5]);
                InsertStaffPerson(person with { Wage = 600 + person.KeyAttribute * 190 });
                filled[role]++;
            }
        }
        return filled;
    }
}
