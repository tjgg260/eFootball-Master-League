namespace ML.Core.Development;

/// <summary>How harshly the app masks what you have not scouted — the Settings triple.</summary>
public enum MaskingStrictness
{
    Relaxed,
    Standard,
    Strict,
}

/// <summary>
/// The five world signals a reputation is read off. Every one of them except
/// <see cref="OverallRating"/> is optional, and a missing signal must be null rather than
/// zero: "no market row" is not "worthless", and "no caps column" is not "uncapped".
/// </summary>
/// <param name="OverallRating">players.overall_rating — the only universal signal (100% coverage).</param>
/// <param name="MarketValue">player_market.value. Null means UNKNOWN, never 0.</param>
/// <param name="InternationalCaps">player_market.int_caps.</param>
/// <param name="ClubReputation">0..10000, resolved by the app's club ladder.</param>
/// <param name="SquadStatus">player_market.perceived_status.</param>
public readonly record struct ReputationInputs(
    int OverallRating,
    long? MarketValue,
    int? InternationalCaps,
    int? ClubReputation,
    string? SquadStatus);

/// <summary>
/// World reputation: how much the football public already knows about a player before your club
/// has watched him once. Everyone knows Mbappé is rapid and can finish; nobody outside his own
/// dressing room knows anything about a fourth-division reserve. Proximity scouting alone cannot
/// express that — this is the fame term that sits underneath it.
///
/// <para>Two halves, both pure and deterministic:</para>
/// <list type="number">
///   <item><b>The score</b> (0..100) — four independent CLAIMS to fame combined with max(), so a
///   missing signal contributes nothing and can never drag a player down.</item>
///   <item><b>The standout ranking</b> (<see cref="RevealOrder"/>) — fame does not reveal a random
///   slice of a man, it reveals what he is FAMOUS FOR. The order in which his abilities become
///   visible rotates towards his standout qualities in proportion to his fame.</item>
/// </list>
///
/// <para>
/// CALIBRATION. Every constant below was measured read-only against the world database
/// (368,127 live players, superseded_by IS NULL). The shape of the ability curve is the load
/// bearing bit: overall_rating is p50=60, p90=65, p99=73, and each further +5 is roughly 5x
/// rarer (>=75 is 0.55% of the world, >=80 is 0.091%, >=85 is 0.0095%, >=90 is 0.0011%). So
/// LINEAR in overall rating is LOG in rarity, which is the correct shape for fame. The price
/// curve was then fitted so that a given score means the same RARITY whether it was earned by
/// ability or by transfer value.
/// </para>
/// </summary>
public static class PlayerReputation
{
    // ------------------------------------------------------------------ the four claims

    // A — ABILITY. 66 is the top 8.4% of the world and scores 0; 90 is the top 0.0011% and
    // scores 100. The Min(,99) guard exists because a couple of rows carry a 116.
    private const int AbilityZero = 66, AbilitySpan = 24;

    // V — PRICE. Two log segments meeting at the £70M knee, each anchor within a factor 1.3 of
    // the value that is equally rare as the ability score it matches.
    private const long PriceKnee = 70_000_000L;

    // C — CAPS. Capped at 75 deliberately: a 150-cap veteran of a small nation is well known,
    // not Mbappé. This is the channel that keeps ageing greats famous after their transfer
    // value collapses (Messi at ov 82 / £14M / Inter Miami scores 100 here and 67 without it).
    private const int CapsFloor = 5, CapsCeiling = 75;

    // S — STAGE. 4,000 is the League Two zero point, 9,000 the very top. The 0.55 weight caps
    // the claim at 55: playing for a giant makes you known, it does not make you Mbappé.
    private const int StageZero = 4000, StageSpan = 5000;
    private const double StageWeight = 0.55;

    /// <summary>Every claim lives on the same 0..100 scale, so they can be compared with max().</summary>
    private static double Clamp(double claim) => Math.Clamp(claim, 0.0, 100.0);

    /// <summary>A — what his rating alone makes him. The only claim every player can make.</summary>
    public static double AbilityClaim(int overallRating) =>
        Clamp((Math.Min(overallRating, 99) - AbilityZero) / (double)AbilitySpan * 100.0);

    /// <summary>
    /// V — what the market says he is worth. £1M scores 10, £10M 41, £50M 62, £120M 81,
    /// £240M 99. A null or non-positive value is an ABSENT signal and scores 0.
    /// </summary>
    public static double PriceClaim(long? marketValue)
    {
        if (marketValue is not { } v || v <= 0) return 0.0;
        return Clamp(v <= PriceKnee
            ? 10.0 + 30.5 * Math.Log10(v / 1_000_000.0)
            : 68.0 + 57.8 * Math.Log10(v / (double)PriceKnee));
    }

    /// <summary>C — an international career. 10 caps score 17, 20 score 34, 50 score 56,
    /// 100 score 73, and the claim never passes 75.</summary>
    public static double CapsClaim(int? internationalCaps)
    {
        if (internationalCaps is not { } caps || caps < CapsFloor) return 0.0;
        return Math.Clamp(56.0 * Math.Log10(caps / (double)CapsFloor), 0.0, CapsCeiling);
    }

    /// <summary>S — the stage he plays on, discounted by how central he is to that club's team.
    /// A League Two squad player is invisible; a Real Madrid starter is not.</summary>
    public static double StageClaim(int? clubReputation, string? squadStatus)
    {
        if (clubReputation is not { } rep || rep <= 0) return 0.0;
        return Clamp((rep - StageZero) / (double)StageSpan * 100.0)
               * RoleWeight(squadStatus) * StageWeight;
    }

    /// <summary>
    /// How much of a club's standing rubs off on one of its players. This is the one table here
    /// that is judged rather than measured — perceived_status has no numeric counterpart in the
    /// data to fit against — so it is deliberately gentle, and an unrecognised or missing status
    /// takes a NEUTRAL 0.60 rather than being punished for a vocabulary gap.
    /// </summary>
    public static double RoleWeight(string? squadStatus) => squadStatus switch
    {
        "Star Player" => 1.00,
        "Important Player" => 0.85,
        "First-Choice Goalkeeper" => 0.85,
        "Regular Starter" => 0.70,
        "Breakthrough Prospect" => 0.45,
        "Squad Player" => 0.35,
        "Fringe Player" => 0.35,
        "Surplus to Requirements" => 0.35,
        "Backup" => 0.30,
        "Emergency Backup" => 0.25,
        "Youngster" => 0.25,
        "Future Prospect" => 0.25,
        "B Team Regular" => 0.20,
        _ => 0.60,
    };

    /// <summary>
    /// World reputation, 0..100. The four claims combine with max() and not with a mean: a man
    /// is famous if ANY of them is loud, and a blank column must never make him less famous than
    /// he is. There is no age term — caps already ARE the accumulated-career signal.
    /// </summary>
    public static int Score(in ReputationInputs x)
    {
        var best = Math.Max(
            Math.Max(AbilityClaim(x.OverallRating), PriceClaim(x.MarketValue)),
            Math.Max(CapsClaim(x.InternationalCaps),
                     StageClaim(x.ClubReputation, x.SquadStatus)));
        return (int)Math.Round(Math.Clamp(best, 0.0, 100.0), MidpointRounding.AwayFromZero);
    }

    // ------------------------------------------------------------------ fame as a floor

    /// <summary>
    /// The knowledge a reputation hands you for free, before anyone at your club has watched
    /// him. Linear in fame, because fame is already log-in-rarity.
    ///
    /// <para>
    /// The ceilings are chosen against the app's 45-point scouting floor. On Standard the floor
    /// never PASSES 45, and only a reputation of 99 or 100 — a handful of men in a world of
    /// 368,000 — so much as reaches it. Fame therefore lifts a superstar to "part-scouted" and
    /// stops. It never buys the scouted half of a dossier (character, ceiling, the flaws a scout
    /// would find): the app gates those on scouted knowledge alone, which this floor
    /// deliberately does not touch.
    /// </para>
    /// </summary>
    public static int KnowledgeFloor(int reputation, MaskingStrictness strictness)
    {
        if (reputation <= 0) return 0;
        var ceiling = strictness switch
        {
            MaskingStrictness.Relaxed => 60.0,
            MaskingStrictness.Strict => 30.0,
            _ => 45.0,
        };
        return (int)Math.Round(ceiling * Math.Clamp(reputation, 0, 100) / 100.0,
                               MidpointRounding.AwayFromZero);
    }

    /// <summary>How the app says a reputation out loud. Empty for a man nobody has heard of.</summary>
    public static string FameLabel(int reputation) => reputation switch
    {
        >= 80 => "Known the world over",
        >= 60 => "A household name",
        >= 40 => "Widely known",
        >= 20 => "A name in the game",
        >= 8 => "Known to the people who follow it",
        _ => "",
    };

    // ------------------------------------------------------------------ population tables

    // Measured read-only over the live world, split by the family a player is judged against.
    // OUTFIELD: n = 329,348 (position <> 'GK'), all 21 non-keeper ability keys.
    // KEEPER:   n =  38,779 (position  = 'GK'), the 5 gk_* keys plus the outfield keys a keeper
    //           is genuinely judged on — his distribution, his athleticism and his feet. The
    //           other outfield keys are not part of a keeper's reputation at all, and are left
    //           out so that "he can't tackle" never becomes a goalkeeper's headline.

    private static readonly Dictionary<string, (double Mean, double Sd)> OutfieldPopulation =
        new(StringComparer.Ordinal)
        {
            ["offensive_awareness"] = (55.77, 7.61),
            ["ball_control"] = (57.38, 7.64),
            ["dribbling"] = (54.49, 8.85),
            ["tight_possession"] = (56.78, 7.08),
            ["low_pass"] = (56.05, 8.03),
            ["lofted_pass"] = (55.03, 8.17),
            ["finishing"] = (52.17, 9.13),
            ["heading"] = (53.19, 9.31),
            ["set_piece_taking"] = (46.90, 8.11),
            ["curl"] = (51.64, 8.46),
            ["speed"] = (61.72, 6.18),
            ["acceleration"] = (61.91, 6.67),
            ["kicking_power"] = (51.08, 8.98),
            ["jumping"] = (55.65, 9.31),
            ["physical_contact"] = (54.75, 7.96),
            ["balance"] = (56.37, 7.60),
            ["stamina"] = (58.09, 7.87),
            ["defensive_awareness"] = (54.08, 8.06),
            ["tackling"] = (53.82, 9.97),
            ["aggression"] = (57.78, 7.35),
            ["defensive_engagement"] = (57.16, 6.69),
        };

    private static readonly Dictionary<string, (double Mean, double Sd)> KeeperPopulation =
        new(StringComparer.Ordinal)
        {
            ["gk_awareness"] = (58.97, 5.07),
            ["gk_catching"] = (61.32, 4.83),
            ["gk_parrying"] = (58.80, 5.54),
            ["gk_reflexes"] = (61.18, 6.95),
            ["gk_reach"] = (60.43, 4.74),
            ["ball_control"] = (43.32, 6.63),
            ["low_pass"] = (49.23, 7.97),
            ["lofted_pass"] = (47.91, 7.62),
            ["kicking_power"] = (43.58, 7.94),
            ["jumping"] = (60.38, 7.77),
            ["physical_contact"] = (52.86, 8.38),
            ["balance"] = (51.94, 7.55),
            ["speed"] = (55.48, 7.96),
            ["acceleration"] = (56.46, 7.67),
        };

    /// <summary>The population a player of this kind is measured against.</summary>
    public static IReadOnlyDictionary<string, (double Mean, double Sd)> Population(bool isGk) =>
        isGk ? KeeperPopulation : OutfieldPopulation;

    // How standout an ability is, measured two ways at once and added:
    //   * against the world  — (value - mean) / sd. Catches "unusual FOR a footballer".
    //   * against greatness  — (value - 70) / 15. Catches "actually elite, not merely unusual".
    // Both are needed. z alone crowns a 70 in a low-spread attribute; raw value alone always
    // crowns whichever attribute happens to have the highest population mean.
    private const double GreatnessPivot = 70.0, GreatnessSpread = 15.0;

    /// <summary>How much this number stands out for this kind of player. Higher is more famous.</summary>
    public static double Standout(int value, double populationMean, double populationSd)
    {
        var sd = populationSd > 0.01 ? populationSd : 0.01;
        return (value - populationMean) / sd + (value - GreatnessPivot) / GreatnessSpread;
    }
}

/// <summary>
/// The order in which one player's abilities become visible to you.
///
/// <para>
/// Knowledge alone reveals a pseudo-random slice — at 40 you learn 40% of a man, which might be
/// his balance and his curl. That is right for an anonymous player and wrong for a famous one:
/// the world knows Mbappé's pace and finishing precisely BECAUSE they are his standout
/// qualities. So reputation ROTATES the reveal order towards his standouts, in proportion to
/// his fame: at fame 0 the order is exactly the old hash (nothing changes for the 87% of the
/// world nobody has heard of), and at fame 100 it is exactly his standout ranking.
/// </para>
///
/// <para>
/// Crucially the rotation changes WHICH abilities you learn, never HOW MANY: at a given
/// knowledge level a famous man and an unknown one both show about that percentage of
/// themselves. Fame is not a substitute for scouting — it is a different question answered.
/// A superstar you have never watched shows his headline and hides his flaws; scouting him is
/// what turns up the rest.
/// </para>
/// </summary>
public sealed class RevealOrder
{
    private readonly long _playerId;
    private readonly Dictionary<string, int> _difficulty;
    private readonly string[] _standouts;

    private RevealOrder(long playerId, int reputation,
                        Dictionary<string, int> difficulty, string[] standouts)
    {
        _playerId = playerId;
        Reputation = reputation;
        _difficulty = difficulty;
        _standouts = standouts;
    }

    /// <summary>The world reputation this order was built from, 0..100.</summary>
    public int Reputation { get; }

    /// <summary>An order for a player the world has never heard of — the plain hash, exactly as
    /// before reputation existed.</summary>
    public static RevealOrder Anonymous(long playerId) =>
        new(playerId, 0, new Dictionary<string, int>(StringComparer.Ordinal), Array.Empty<string>());

    /// <summary>
    /// Build the reveal order for one player. Cheap enough to do per render (one sort of at most
    /// 21 keys) and worth caching per player; the result is pure in its inputs.
    /// </summary>
    public static RevealOrder For(
        long playerId, IReadOnlyDictionary<string, int>? abilities, bool isGk, int reputation)
    {
        var fame = Math.Clamp(reputation, 0, 100);
        if (fame <= 0 || abilities is null || abilities.Count == 0) return Anonymous(playerId);

        var population = PlayerReputation.Population(isGk);
        // Ordinal tie-break, not dictionary order: two identical values must rank the same way
        // on every render and on every machine.
        var ranked = abilities
            .Where(a => population.ContainsKey(a.Key))
            .Select(a =>
            {
                var (mean, sd) = population[a.Key];
                return (a.Key, Score: PlayerReputation.Standout(a.Value, mean, sd));
            })
            .OrderByDescending(a => a.Score)
            .ThenBy(a => a.Key, StringComparer.Ordinal)
            .Select(a => a.Key)
            .ToArray();
        if (ranked.Length == 0) return Anonymous(playerId);

        var f = fame / 100.0;
        var difficulty = new Dictionary<string, int>(ranked.Length, StringComparer.Ordinal);
        for (var rank = 0; rank < ranked.Length; rank++)
        {
            // Where this ability sits in the famous order (rank 0 = the first thing anyone
            // tells you about him), blended against where the blind hash would have put it.
            var famous = (rank + 0.5) / ranked.Length * 100.0;
            var blind = AttributeKnowledge.RevealDifficulty(playerId, ranked[rank]);
            difficulty[ranked[rank]] =
                (int)Math.Round((1.0 - f) * blind + f * famous, MidpointRounding.AwayFromZero);
        }
        return new RevealOrder(playerId, fame, difficulty, ranked);
    }

    /// <summary>
    /// Whether one ability is visible at this knowledge level. Deterministic, monotonic in
    /// knowledge, everything at 100 and nothing at 0 — the same contract the unbiased reveal
    /// has always honoured. Abilities outside the player's family (an outfielder's keeper
    /// numbers, a keeper's tackling, the non-ability rows like foot and form) are not part of
    /// anybody's reputation and keep the plain hash.
    /// </summary>
    public bool IsRevealed(string attribute, int knowledge)
    {
        if (knowledge >= 100) return true;
        if (knowledge <= 0) return false;
        var d = _difficulty.TryGetValue(attribute, out var v)
            ? v
            : AttributeKnowledge.RevealDifficulty(_playerId, attribute);
        return d < knowledge;
    }

    /// <summary>
    /// What he is known for, best first, limited to what this knowledge level actually shows.
    /// For a famous player these are the headline abilities; for an anonymous one it is
    /// whatever happens to be visible, which is the honest answer.
    /// </summary>
    public IReadOnlyList<string> Headline(int knowledge, int max = 2)
    {
        if (max <= 0) return Array.Empty<string>();
        var picked = new List<string>(max);
        foreach (var key in _standouts)
        {
            if (!IsRevealed(key, knowledge)) continue;
            picked.Add(key);
            if (picked.Count == max) break;
        }
        return picked;
    }
}
