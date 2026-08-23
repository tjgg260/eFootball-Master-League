namespace ML.Core.Tactics;

/// <summary>An in- or out-of-possession role: its name, the positions it fits, and the three
/// abilities that define fit (used for ★ ratings and AI auto-assignment).</summary>
public sealed record RoleDef(string Name, string[] Positions, string[] Needs);

/// <summary>
/// The single source of truth for player roles, shared by ML.App and ML.Web so the two can't
/// drift (the tactics fragmentation that hid the out-of-possession system). Primary = in
/// possession, Secondary = out of possession. AI assignment is TACTICS-AWARE: the team's chosen
/// playstyle (0-5) nudges role choice, so a Possession side fills with orchestrators and pressers
/// while a Quick Counter side fills with pace and outlets.
/// </summary>
public static class RoleCatalog
{
    public static readonly RoleDef[] Primary =
    {
        new("Goal Poacher", new[] { "CF" }, new[] { "offensive_awareness", "finishing", "acceleration" }),
        new("Dummy Runner", new[] { "CF", "SS", "AMF" }, new[] { "offensive_awareness", "speed", "balance" }),
        new("Fox in the Box", new[] { "CF" }, new[] { "finishing", "offensive_awareness", "jumping" }),
        new("Target Man", new[] { "CF" }, new[] { "heading", "physical_contact", "ball_control" }),
        new("Deep-Lying Forward", new[] { "CF", "SS" }, new[] { "ball_control", "low_pass", "finishing" }),
        new("Creative Playmaker", new[] { "SS", "RWF", "LWF", "AMF", "RMF", "LMF" }, new[] { "low_pass", "dribbling", "offensive_awareness" }),
        new("Prolific Winger", new[] { "RWF", "LWF" }, new[] { "finishing", "speed", "dribbling" }),
        new("Roaming Flank", new[] { "RWF", "LWF", "RMF", "LMF" }, new[] { "dribbling", "speed", "ball_control" }),
        new("Cross Specialist", new[] { "RWF", "LWF", "RMF", "LMF", "RB", "LB" }, new[] { "lofted_pass", "curl", "speed" }),
        new("Classic No. 10", new[] { "SS", "AMF" }, new[] { "low_pass", "ball_control", "tight_possession" }),
        new("Hole Player", new[] { "SS", "AMF", "RMF", "LMF", "CMF" }, new[] { "offensive_awareness", "finishing", "stamina" }),
        new("Box-to-Box", new[] { "RMF", "LMF", "CMF", "DMF" }, new[] { "stamina", "physical_contact", "ball_control" }),
        new("Anchor Man", new[] { "DMF" }, new[] { "defensive_awareness", "tackling", "defensive_engagement" }),
        new("Orchestrator", new[] { "CMF", "DMF" }, new[] { "low_pass", "lofted_pass", "offensive_awareness" }),
        new("Build Up", new[] { "CB" }, new[] { "low_pass", "lofted_pass", "ball_control" }),
        new("Extra Frontman", new[] { "CB" }, new[] { "heading", "physical_contact", "finishing" }),
        new("Attacking Full-back", new[] { "RB", "LB" }, new[] { "speed", "stamina", "lofted_pass" }),
        new("Defensive Full-back", new[] { "RB", "LB" }, new[] { "defensive_awareness", "tackling", "stamina" }),
        new("Full-back Finisher", new[] { "RB", "LB" }, new[] { "speed", "finishing", "stamina" }),
        new("Offensive Goalkeeper", new[] { "GK" }, new[] { "gk_awareness", "low_pass", "gk_reach" }),
        new("Defensive Goalkeeper", new[] { "GK" }, new[] { "gk_reflexes", "gk_catching", "gk_parrying" }),
    };

    public static readonly RoleDef[] Secondary =
    {
        new("The Destroyer", new[] { "CB", "DMF" }, new[] { "tackling", "aggression", "defensive_engagement" }),
        new("Press Back", new[] { "AMF", "RMF", "LMF", "SS", "CF", "RWF", "LWF" }, new[] { "stamina", "defensive_engagement", "aggression" }),
        new("Front Line Pressure", new[] { "CF", "SS", "RWF", "LWF" }, new[] { "defensive_engagement", "stamina", "aggression" }),
        new("Front Line Poacher", new[] { "CF", "SS" }, new[] { "offensive_awareness", "finishing", "acceleration" }),
        new("Attack Outlet", new[] { "CF", "SS", "RWF", "LWF" }, new[] { "speed", "ball_control", "offensive_awareness" }),
        new("All-action Defender", new[] { "CB", "RB", "LB" }, new[] { "stamina", "tackling", "defensive_awareness" }),
        new("Pass Disruptor", new[] { "DMF", "CMF" }, new[] { "defensive_awareness", "low_pass", "tackling" }),
        new("Covering Role", new[] { "CB", "RB", "LB" }, new[] { "defensive_awareness", "speed", "balance" }),
        new("High Line Master", new[] { "CB" }, new[] { "speed", "defensive_awareness", "acceleration" }),
        new("Tough Marker", new[] { "CB", "RB", "LB", "DMF" }, new[] { "physical_contact", "tackling", "defensive_awareness" }),
        new("Deep Defender", new[] { "CB" }, new[] { "defensive_awareness", "tackling", "heading" }),
        new("Sweeper GK", new[] { "GK" }, new[] { "gk_reach", "low_pass", "speed" }),
        new("Build-up GK", new[] { "GK" }, new[] { "low_pass", "lofted_pass", "gk_reach" }),
        new("Attacking GK", new[] { "GK" }, new[] { "gk_reach", "low_pass", "gk_awareness" }),
        new("Defensive GK", new[] { "GK" }, new[] { "gk_reflexes", "gk_catching", "gk_parrying" }),
    };

    // Team style (0 Possession · 1 Quick Counter · 2 Long Ball Counter · 3 Long Ball · 4 Out Wide ·
    // 5 Overload) -> the roles that style favours. A favoured role gets a fit bonus at assignment.
    private static readonly Dictionary<int, HashSet<string>> StyleFavoured = new()
    {
        [0] = new() { "Orchestrator", "Classic No. 10", "Deep-Lying Forward", "Build Up", "Creative Playmaker", "Box-to-Box", "Front Line Pressure", "Press Back", "Pass Disruptor", "High Line Master", "Build-up GK" },
        [1] = new() { "Prolific Winger", "Goal Poacher", "Roaming Flank", "Hole Player", "Attacking Full-back", "Covering Role", "All-action Defender", "Attack Outlet", "Sweeper GK" },
        [2] = new() { "Target Man", "Fox in the Box", "Cross Specialist", "Prolific Winger", "Deep Defender", "Covering Role", "Tough Marker", "Defensive GK" },
        [3] = new() { "Target Man", "Extra Frontman", "Cross Specialist", "Tough Marker", "Deep Defender", "The Destroyer", "Defensive GK" },
        [4] = new() { "Cross Specialist", "Prolific Winger", "Roaming Flank", "Attacking Full-back", "All-action Defender", "Press Back", "Sweeper GK" },
        [5] = new() { "Goal Poacher", "Dummy Runner", "Attacking Full-back", "Full-back Finisher", "Extra Frontman", "Front Line Pressure", "High Line Master", "The Destroyer", "Attacking GK" },
    };

    /// <summary>Fit of a role for a player: mean of the role's three need-attributes (0-99), plus a
    /// bonus when the team's chosen style favours the role.</summary>
    public static double Fit(RoleDef role, IReadOnlyDictionary<string, int> abilities, int? teamStyle)
    {
        var sum = 0;
        foreach (var k in role.Needs) sum += abilities.TryGetValue(k, out var v) ? v : 0;
        var score = (double)sum / role.Needs.Length;
        if (teamStyle is { } s && StyleFavoured.TryGetValue(s, out var fav) && fav.Contains(role.Name))
            score += 8;   // a nudge, not an override — attributes still lead
        return score;
    }

    public static string? BestPrimary(string position, IReadOnlyDictionary<string, int> abilities, int? teamStyle = null)
        => Best(Primary, position, abilities, teamStyle);

    public static string? BestSecondary(string position, IReadOnlyDictionary<string, int> abilities, int? teamStyle = null)
        => Best(Secondary, position, abilities, teamStyle);

    private static string? Best(RoleDef[] catalog, string position,
        IReadOnlyDictionary<string, int> abilities, int? teamStyle)
    {
        string? best = null;
        var bestScore = double.MinValue;
        foreach (var role in catalog)
        {
            if (!role.Positions.Contains(position)) continue;
            var f = Fit(role, abilities, teamStyle);
            if (f > bestScore) { bestScore = f; best = role.Name; }
        }
        return best;
    }
}
