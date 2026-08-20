namespace ML.Core.Management;

/// <summary>
/// Multi-round transfer negotiation with the SELLING CLUB (the agent's wage step reuses
/// ContractNegotiation). Three rounds: the club states an ask, you structure a package —
/// fee, a sell-on percentage, instalments — and the club weighs the package's effective
/// value. Lowballs end talks; near misses get countered with a softening ask. Pure maths.
/// </summary>
public static class ClubNegotiation
{
    public const int MaxRounds = 3;

    /// <summary>
    /// What the package is worth in the selling club's eyes. Sell-on percentage carries
    /// real option value (60p per £1 of its expectation); instalments cost the seller a
    /// little time-value.
    /// </summary>
    public static long EffectiveValue(long fee, int sellOnPct, bool instalments, long marketValue)
    {
        var v = (double)fee;
        v += sellOnPct / 100.0 * marketValue * 0.6;
        if (instalments) v *= 0.94;
        return (long)v;
    }

    public enum Verdict { Accepted, Countered, WalkedAway }

    /// <summary>
    /// The club's response. `ask` is their current ask; a package within 3% closes the
    /// deal, an insulting one (under 78%) ends talks, anything between draws a counter
    /// with the ask easing toward the offer (they want to sell too).
    /// </summary>
    public static (Verdict Verdict, long NewAsk) Respond(
        long ask, long fee, int sellOnPct, bool instalments, long marketValue, int round)
    {
        var effective = EffectiveValue(fee, sellOnPct, instalments, marketValue);
        if (effective >= ask * 97L / 100L) return (Verdict.Accepted, ask);
        if (effective < ask * 78L / 100L || round >= MaxRounds) return (Verdict.WalkedAway, ask);
        // Counter: the ask eases 40% of the way toward the package, never below value.
        var eased = ask - (ask - effective) * 40L / 100L;
        return (Verdict.Countered, Math.Max(eased, marketValue));
    }

    /// <summary>Deal likelihood % for the UI gauge (bounded, monotonic in the package).</summary>
    public static int Likelihood(long ask, long fee, int sellOnPct, bool instalments, long marketValue)
    {
        if (ask <= 0) return 0;
        var effective = EffectiveValue(fee, sellOnPct, instalments, marketValue);
        var ratio = (double)effective / ask;
        return Math.Clamp((int)Math.Round((ratio - 0.70) / 0.30 * 100), 2, 98);
    }

    /// <summary>The club's opening ask: market value plus a stable premium, difficulty-scaled.</summary>
    public static long OpeningAsk(long marketValue, int premiumPct, int difficultyPct) =>
        marketValue * (100 + premiumPct) / 100 * difficultyPct / 100;

    /// <summary>The club's stance line for the given gap — flavour with information in it.</summary>
    public static string Stance(long ask, long lastEffective, int round)
    {
        if (lastEffective <= 0) return "\"Make us an offer worth discussing.\"";
        var ratio = (double)lastEffective / ask;
        return ratio >= 0.95 ? "\"We are close. Tidy up the numbers and he can travel.\""
            : ratio >= 0.88 ? "\"Bring a serious structure — or a sell-on — and we can talk.\""
            : round >= MaxRounds - 1 ? "\"This is your last conversation with us on the matter.\""
            : "\"That does not respect the player or this club.\"";
    }
}
