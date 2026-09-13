using System.Globalization;

namespace ML.Ingest;

/// <summary>
/// Player match ratings from a stats-host export: a port of the <c>match_rating</c> layer of
/// efootball-re/mlstats/rating.py (model <c>mlstats-rating/1</c>). The game's own ratings are not
/// in the export, so this is what fills them.
///
/// Start at 6.0, add or subtract per action by role, clamp to [3, 10]. Age plays no part — the same
/// performance is not worth more because the player is 19 (that is rating.py's separate context
/// layer, not ported). Every contribution is kept as an item so a rating can be explained.
///
/// Keep it identical to rating.py: tests compare every player of two real exports against the
/// ratings rating.py produced for them (samples/ml-stats/*.expected-ratings.json). When the Python
/// model changes, regenerate those files and port the change.
/// </summary>
public static class MatchRating
{
    public const string Model = "mlstats-rating/1";

    // Attribute array indices (efootball-re memprobe README, measured).
    private static readonly Dictionary<string, int> Attr = new()
    {
        ["att_awareness"] = 20, ["def_awareness"] = 21, ["gk_awareness"] = 22, ["def_engagement"] = 23,
        ["dribbling"] = 24, ["ball_control"] = 25, ["tight_possession"] = 26, ["finishing"] = 27,
        ["low_pass"] = 28, ["lofted_pass"] = 29, ["header"] = 30, ["tackling"] = 31, ["aggression"] = 32,
        ["set_piece"] = 33, ["curl"] = 34, ["gk_catching"] = 35, ["gk_parrying"] = 36, ["gk_reflexes"] = 37,
        ["gk_reach"] = 38, ["weak_foot"] = 39, ["speed"] = 40, ["physical"] = 41, ["balance"] = 42,
        ["kicking_power"] = 43, ["acceleration"] = 44, ["jump"] = 45, ["stamina"] = 46,
        ["age"] = 49, ["height"] = 50, ["weight"] = 51,
    };

    private static readonly string[] InferredLabels = { "gk_shots_faced", "gk_shots_on_target_faced", "goals", "saves" };
    private static readonly string[] GkOnlyActions = { "saves", "gk_shots_faced", "gk_shots_on_target_faced" };

    public static int AttrIndex(string name) => Attr[name];

    /// <summary>Linear up to k, half slope after it: padding a stat pays less and less.</summary>
    public static double Knee(double n, double k) => n <= k ? n : k + (n - k) * 0.5;

    /// <summary>0 at 0, 0.5 at <paramref name="half"/>, approaching 1.</summary>
    public static double Soft(double x, double half) => x > 0 ? x / (x + half) : 0.0;

    /// <summary>
    /// GK / DEF / MID / FWD and what it was inferred from. The keeper comes first from the two
    /// certain signals — lineup position 0, or a keeper-only action — because attributes alone
    /// cannot tell a keeper in a squad file-modded to 99 across the board.
    /// </summary>
    public static (string Role, string Source) InferRole(ExportPlayer p)
    {
        if (p.LineupIndex == 0) return ("GK", "lineup");
        if (GkOnlyActions.Any(k => p.Action(k) != 0)) return ("GK", "actions");

        var attrs = p.AttributesBase is { Length: > 0 } b ? b
                  : p.AttributesForm is { Length: > 0 } f ? f : null;
        if (attrs is not null)
        {
            double Mean(params string[] names) => names.Sum(n => (double)attrs[Attr[n]]) / names.Length;
            var gk = Mean("gk_awareness", "gk_catching", "gk_parrying", "gk_reflexes", "gk_reach");
            var dfn = Mean("def_awareness", "def_engagement", "tackling", "aggression");
            var att = Mean("att_awareness", "finishing");
            if (gk >= 60 && gk > Math.Max(dfn, att)) return ("GK", "attributes");
            if (dfn - att >= 8) return ("DEF", "attributes");
            if (att - dfn >= 8) return ("FWD", "attributes");
            // Every value equal (a modded squad) carries no information: fall through to actions.
            if (!(gk == dfn && dfn == att)) return ("MID", "attributes");
        }

        var defensive = p.Action("tackles") + p.Action("interceptions");
        var attacking = p.Action("shots") + p.Action("offsides");
        if (defensive >= 3 && defensive >= 3 * Math.Max(attacking, 1)) return ("DEF", "actions");
        if (attacking >= 2 && attacking > defensive) return ("FWD", "actions");
        return ("MID", "actions");
    }

    /// <summary>First and last of the 8 stat segments in which the player did anything.</summary>
    public static (int First, int Last)? ActivePeriods(ExportPlayer p)
    {
        var segments = p.RawSegments;
        if (segments is null || segments.Count == 0) return null;
        var active = Enumerable.Range(0, 8).Where(k => segments.Values.Any(v => v[k] != 0)).ToList();
        return active.Count > 0 ? (active[0], active[^1]) : null;
    }

    /// <summary>Share of the match the player was active for (inferred from the segments).</summary>
    public static double? MinutesShare(ExportPlayer p, int? matchPeriods)
    {
        var span = ActivePeriods(p);
        if (span is null || matchPeriods is null or 0) return null;
        return (span.Value.Last - span.Value.First + 1) / (double)matchPeriods.Value;
    }

    public static PlayerRating RatePlayer(ExportPlayer p, long teamGoals, long oppGoals,
                                          RatingConfig cfg, int? matchPeriods = null)
    {
        var (role, roleSource) = InferRole(p);
        var goals = p.Action("goals");
        var shots = p.Action("shots");
        var sot = p.Action("shots_on_target");
        var passes = p.Action("passes");
        var completed = p.Action("passes_completed");
        var share = MinutesShare(p, matchPeriods);

        // Component order and float accumulation order follow rating.py, so rounding agrees.
        var order = new List<string>();
        var scores = new Dictionary<string, double>();
        var items = new List<RatingItem>();
        void Add(string component, string item, double count, double value)
        {
            if (!scores.ContainsKey(component)) { scores[component] = 0.0; order.Add(component); }
            if (count != 0 || value != 0)
            {
                items.Add(new RatingItem(component, item, count, value));
                scores[component] += value;
            }
        }

        Add("attacking", "goals", goals, goals * cfg.Goal[role]);
        Add("attacking", "shots_on_target_saved_or_blocked", Math.Max(0, sot - goals),
            Math.Max(0, sot - goals) * cfg.ShotOnTarget);
        Add("attacking", "crosses", p.Action("crosses"), Knee(p.Action("crosses"), cfg.CrossKnee) * cfg.Cross);

        Add("passing", "completed_volume", completed, cfg.PassVolume * Soft(completed, cfg.PassVolumeHalf));
        if (passes >= cfg.PassAccuracyMinAttempts)
        {
            var accuracy = completed / (double)passes;
            var delta = (accuracy - cfg.ExpectedAccuracy[role]) * cfg.PassAccuracyWeight;
            delta = Math.Max(-cfg.PassAccuracyCap, Math.Min(cfg.PassAccuracyCap, delta));
            // Few attempts make the percentage unreliable: scaled down below 20.
            Add("passing", "accuracy_vs_role", PyRound(accuracy, 3), delta * Math.Min(1.0, passes / 20.0));
        }

        var mult = cfg.DefensiveRoleMult[role];
        Add("defending", "tackles", p.Action("tackles"), Knee(p.Action("tackles"), cfg.DefensiveKnee) * cfg.Tackle * mult);
        Add("defending", "interceptions", p.Action("interceptions"),
            Knee(p.Action("interceptions"), cfg.DefensiveKnee) * cfg.Interception * mult);

        if (role == "GK")
            Add("goalkeeping", "saves", p.Action("saves"), Knee(p.Action("saves"), cfg.SaveKnee) * cfg.Save);
        Add("goalkeeping", "goals_conceded", oppGoals, oppGoals * cfg.Conceded[role]);
        if (oppGoals == 0 && (share is null || share >= cfg.CleanSheetMinShare))
            Add("goalkeeping", "clean_sheet", 1, cfg.CleanSheet[role]);

        Add("errors_discipline", "shots_off_target", Math.Max(0, shots - sot), Math.Max(0, shots - sot) * cfg.ShotOffTarget);
        Add("errors_discipline", "offsides", p.Action("offsides"), p.Action("offsides") * cfg.Offside);
        Add("errors_discipline", "fouls", p.Action("fouls"), p.Action("fouls") * cfg.Foul);

        var gd = Math.Max(-cfg.GoalDifferenceCap, Math.Min(cfg.GoalDifferenceCap, teamGoals - oppGoals));
        Add("result", "goal_difference", teamGoals - oppGoals, gd * cfg.GoalDifference);

        // rating.py: base + sum(component scores), where sum() starts from integer 0.
        var total = 0.0;
        foreach (var c in order) total += scores[c];
        var raw = cfg.Base + total;
        var rating = Math.Max(cfg.Floor, Math.Min(cfg.Ceiling, raw));

        var caveats = InferredLabels.Where(k => p.Action(k) != 0).Select(k => $"uses inferred label: {k}").ToList();
        return new PlayerRating(p.Slot, role, roleSource, PyRound(rating, 1), PyRound(raw, 3),
            share is null ? null : PyRound(share.Value, 3), items, caveats);
    }

    /// <summary>Ratings for both teams, in the export's team and player order.</summary>
    public static IReadOnlyList<IReadOnlyList<PlayerRating>> RateMatch(MatchExport export, RatingConfig? cfg = null)
    {
        cfg ??= new RatingConfig();
        var goals = export.Teams.Select(t => t.Total("goals")).ToArray();
        var ends = export.Teams.SelectMany(t => t.Players).Select(ActivePeriods)
            .Where(e => e is not null).Select(e => e!.Value.Last + 1).ToList();
        int? matchPeriods = ends.Count > 0 ? ends.Max() : null;
        return export.Teams.Select((team, i) => (IReadOnlyList<PlayerRating>)team.Players
            .Select(p => RatePlayer(p, goals[i], goals[1 - i], cfg, matchPeriods)).ToList()).ToList();
    }

    /// <summary>
    /// Python's round(x, n): nearest, ties to even, decided on the double's own value. Math.Round
    /// scales by 10^n first, which can flip a value like 6.35 (stored as 6.3499…) the wrong way.
    /// 17 significant digits identify the double, and decimal rounds them without binary error.
    /// </summary>
    public static double PyRound(double x, int digits)
    {
        var d = decimal.Parse(x.ToString("G17", CultureInfo.InvariantCulture),
                              NumberStyles.Float, CultureInfo.InvariantCulture);
        return (double)Math.Round(d, digits, MidpointRounding.ToEven);
    }
}

public sealed record RatingItem(string Component, string Item, double Count, double Value);

public sealed record PlayerRating(
    int Slot, string Role, string RoleSource, double Rating, double Unclamped, double? MinutesShare,
    IReadOnlyList<RatingItem> Items, IReadOnlyList<string> Caveats);

/// <summary>rating.py's RatingConfig (the match layer), same defaults.</summary>
public sealed class RatingConfig
{
    public double Base { get; init; } = 6.0;
    public double Floor { get; init; } = 3.0;
    public double Ceiling { get; init; } = 10.0;

    public Dictionary<string, double> Goal { get; init; } = new() { ["GK"] = 1.2, ["DEF"] = 1.1, ["MID"] = 1.0, ["FWD"] = 0.9 };
    public double ShotOnTarget { get; init; } = 0.12;
    public double Cross { get; init; } = 0.04;
    public double CrossKnee { get; init; } = 5.0;

    public double PassVolume { get; init; } = 0.6;
    public double PassVolumeHalf { get; init; } = 30.0;
    public double PassAccuracyWeight { get; init; } = 2.0;
    public double PassAccuracyCap { get; init; } = 0.4;
    public int PassAccuracyMinAttempts { get; init; } = 5;
    public Dictionary<string, double> ExpectedAccuracy { get; init; } = new() { ["GK"] = 0.70, ["DEF"] = 0.85, ["MID"] = 0.83, ["FWD"] = 0.75 };

    public double Tackle { get; init; } = 0.14;
    public double Interception { get; init; } = 0.11;
    public double DefensiveKnee { get; init; } = 6.0;
    public Dictionary<string, double> DefensiveRoleMult { get; init; } = new() { ["GK"] = 1.0, ["DEF"] = 1.0, ["MID"] = 1.0, ["FWD"] = 1.2 };

    public double Save { get; init; } = 0.30;
    public double SaveKnee { get; init; } = 5.0;
    public Dictionary<string, double> Conceded { get; init; } = new() { ["GK"] = -0.30, ["DEF"] = -0.12, ["MID"] = -0.05, ["FWD"] = 0.0 };
    public Dictionary<string, double> CleanSheet { get; init; } = new() { ["GK"] = 0.5, ["DEF"] = 0.3, ["MID"] = 0.05, ["FWD"] = 0.0 };
    public double CleanSheetMinShare { get; init; } = 0.6;

    public double ShotOffTarget { get; init; } = -0.04;
    public double Offside { get; init; } = -0.08;
    public double Foul { get; init; } = -0.10;

    public double GoalDifference { get; init; } = 0.10;
    public long GoalDifferenceCap { get; init; } = 3;
}
