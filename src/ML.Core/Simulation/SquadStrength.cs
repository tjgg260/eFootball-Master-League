using ML.Core.Domain;

namespace ML.Core.Simulation;

/// <summary>Attack and defence ratings on the same 40-99 scale players use.</summary>
public readonly record struct TeamStrength(double Attack, double Defence)
{
    public double Overall => (Attack + Defence) / 2.0;

    public override string ToString() => $"ATT {Attack:F1} / DEF {Defence:F1}";
}

/// <summary>
/// Turns a squad into an attack and a defence number by picking a best XI and taking a
/// position-weighted mean. Deliberately crude: it only has to rank clubs sensibly and give the
/// simulator something to separate them by.
/// </summary>
public static class SquadStrength
{
    private const int OutfieldPlaces = 10;

    private static readonly IReadOnlyDictionary<PositionGroup, double> AttackWeights =
        new Dictionary<PositionGroup, double>
        {
            [PositionGroup.Goalkeeper] = 0.0,
            [PositionGroup.Defender] = 0.6,
            [PositionGroup.Midfielder] = 1.4,
            [PositionGroup.Forward] = 2.6,
        };

    private static readonly IReadOnlyDictionary<PositionGroup, double> DefenceWeights =
        new Dictionary<PositionGroup, double>
        {
            [PositionGroup.Goalkeeper] = 2.6,
            [PositionGroup.Defender] = 2.2,
            [PositionGroup.Midfielder] = 1.0,
            [PositionGroup.Forward] = 0.3,
        };

    public static TeamStrength Evaluate(IReadOnlyList<Player> squad)
    {
        ArgumentNullException.ThrowIfNull(squad);

        var xi = SelectBestXi(squad);
        if (xi.Count == 0)
        {
            // A club with nobody in it should lose heavily, not crash the season.
            return new TeamStrength(Player.MinRating, Player.MinRating);
        }

        return new TeamStrength(
            WeightedMean(xi, AttackWeights),
            WeightedMean(xi, DefenceWeights));
    }

    /// <summary>Best available keeper plus the ten best outfielders.</summary>
    public static IReadOnlyList<Player> SelectBestXi(IReadOnlyList<Player> squad)
    {
        var keeper = squad
            .Where(p => p.Position.IsGoalkeeper())
            .MaxBy(p => p.OverallRating);

        var outfield = squad
            .Where(p => !p.Position.IsGoalkeeper())
            .OrderByDescending(p => p.OverallRating)
            .ThenBy(p => p.Id.Value)
            .Take(OutfieldPlaces);

        var xi = new List<Player>(11);
        if (keeper is not null)
        {
            xi.Add(keeper);
        }

        xi.AddRange(outfield);
        return xi;
    }

    private static double WeightedMean(
        IReadOnlyList<Player> xi,
        IReadOnlyDictionary<PositionGroup, double> weights)
    {
        double weighted = 0;
        double total = 0;

        foreach (var player in xi)
        {
            var weight = weights[player.Position.Group()];
            weighted += player.OverallRating * weight;
            total += weight;
        }

        // A squad of nothing but keepers has zero attack weight; fall back to a flat mean.
        return total > 0
            ? weighted / total
            : xi.Average(p => (double)p.OverallRating);
    }
}
