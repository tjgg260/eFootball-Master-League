namespace ML.Core.Selection;

public enum NegotiationOutcome
{
    Accepted,
    Countered,
    WalkedAway,
}

/// <summary>
/// Contract negotiation (FM phase B3), pure and deterministic. The agent's demand comes from
/// rating, age and morale; lowball offers get countered across rounds with the counter easing
/// toward the demand; insulting offers end the talks. A squad-status promise sweetens the
/// deal (the player accepts a little less to be told he matters) — but B1/B2 will hold you
/// to it.
/// </summary>
public static class ContractNegotiation
{
    /// <summary>Weekly wage demand. Peak-age stars with low morale want "prove you love me" money.</summary>
    public static long WeeklyDemand(int rating, int? age, int morale, int years)
    {
        double basis = 500 + rating * 40;
        basis *= 1 + Math.Max(0, rating - 60) / 80.0;              // stars scale super-linearly
        var a = age ?? 25;
        basis *= a is >= 24 and <= 29 ? 1.2 : a >= 33 ? 0.8 : 1.0; // peak years cost more
        if (morale < MoraleModel.Neutral) basis *= 1.15;           // unhappy = expensive to keep
        basis *= years switch { 1 => 1.1, 3 => 0.95, _ => 1.0 };   // longer deals ease the weekly
        return (long)(Math.Round(basis / 50) * 50);
    }

    /// <summary>Discount (0–0.08) a squad-status promise buys off the demand.</summary>
    public static double StatusDiscount(string? status) => status switch
    {
        "Star" => 0.08,
        "First-team" => 0.05,
        "Rotation" => 0.02,
        _ => 0,
    };

    /// <summary>
    /// One negotiation round. Accepts within 3% of the (status-discounted) demand; walks away
    /// on a third lowball or anything under 70%; otherwise counters, easing toward the demand
    /// each round.
    /// </summary>
    public static (NegotiationOutcome Outcome, long Counter) Respond(
        long offer, long demand, string? status, int round)
    {
        var target = (long)(demand * (1 - StatusDiscount(status)));
        if (offer >= target * 0.97) return (NegotiationOutcome.Accepted, target);
        if (offer < target * 0.70 || round >= 3) return (NegotiationOutcome.WalkedAway, target);
        // Counter eases toward the target: round 1 asks near-full, round 2 splits the gap more.
        var ease = round switch { 1 => 1.0, 2 => 0.5, _ => 0.25 };
        var counter = offer + (long)((target - offer) * ease);
        counter = Math.Max(counter, offer + 50);
        return (NegotiationOutcome.Countered, (long)(Math.Round(counter / 50.0) * 50));
    }

    /// <summary>Starts owed inside 6 matchdays by each squad-status promise (B1 tracks it).</summary>
    public static int StatusStartsOwed(string status) => status switch
    {
        "Star" => 5,
        "First-team" => 4,
        "Rotation" => 2,
        _ => 0,
    };
}
