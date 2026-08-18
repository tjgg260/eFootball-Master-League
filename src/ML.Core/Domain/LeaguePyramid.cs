namespace ML.Core.Domain;

/// <summary>
/// The promotion/relegation ladder.
///
/// Assumes one division per tier — parallel divisions at the same level (a north/south third
/// tier, say) would need play-off handling this does not have, so it rejects them outright
/// rather than silently picking one.
/// </summary>
public static class LeaguePyramid
{
    public static IReadOnlyList<(League Upper, League Lower)> AdjacentTiers(World world)
    {
        ArgumentNullException.ThrowIfNull(world);

        var byTier = world.LeaguesByTier().ToList();

        var shared = byTier.GroupBy(l => l.Tier).FirstOrDefault(g => g.Count() > 1);
        if (shared is not null)
        {
            var names = string.Join(", ", shared.Select(l => l.Name));
            throw new InvalidOperationException(
                $"Tier {shared.Key} has more than one division ({names}); parallel divisions are not supported.");
        }

        var pairs = new List<(League, League)>();
        for (var i = 0; i < byTier.Count - 1; i++)
        {
            var upper = byTier[i];
            var lower = byTier[i + 1];
            if (lower.Tier == upper.Tier + 1)
            {
                pairs.Add((upper, lower));
            }
        }

        return pairs;
    }

    /// <summary>
    /// Fails if any adjacent pair would change size at a rollover — three down and two up
    /// leaves the top flight a club short forever, and it is much cheaper to catch here.
    /// </summary>
    public static void Validate(World world)
    {
        foreach (var (upper, lower) in AdjacentTiers(world))
        {
            if (upper.RelegationPlaces != lower.PromotionPlaces)
            {
                throw new InvalidOperationException(
                    $"{upper.Name} relegates {upper.RelegationPlaces} but {lower.Name} promotes " +
                    $"{lower.PromotionPlaces}; division sizes would drift every season.");
            }
        }
    }
}
