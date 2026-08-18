namespace ML.Core.Domain;

/// <summary>
/// A division. <see cref="Tier"/> 1 is the top flight; promotion moves a club to a lower tier
/// number. <see cref="PromotionPlaces"/> of tier N must equal <see cref="RelegationPlaces"/>
/// of tier N-1 or club counts drift over a rollover — <see cref="LeaguePyramid"/> enforces it.
/// </summary>
public sealed class League
{
    public League(
        LeagueId id,
        string name,
        int tier,
        int promotionPlaces = 0,
        int relegationPlaces = 0)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new ArgumentException("League name is required.", nameof(name));
        }

        if (tier < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(tier), tier, "Tier 1 is the top flight.");
        }

        if (promotionPlaces < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(promotionPlaces), promotionPlaces, null);
        }

        if (relegationPlaces < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(relegationPlaces), relegationPlaces, null);
        }

        Id = id;
        Name = name;
        Tier = tier;
        PromotionPlaces = promotionPlaces;
        RelegationPlaces = relegationPlaces;
    }

    public LeagueId Id { get; }

    public string Name { get; }

    public int Tier { get; }

    /// <summary>How many clubs go up from this division.</summary>
    public int PromotionPlaces { get; }

    /// <summary>How many clubs go down from this division.</summary>
    public int RelegationPlaces { get; }

    public override string ToString() => Name;
}
