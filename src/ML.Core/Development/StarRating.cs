namespace ML.Core.Development;

/// <summary>
/// How good a player is, as the app shows it: STARS in half-star tiers, ½ to 5 — ten tiers
/// (ruling 2026-09-13). Never an overall number, and no longer a letter grade. The engine keeps its
/// internal strength (sims, selection, valuation all read overall_rating); this is its only face.
///
/// The tiers are ABSOLUTE — a player carries the same stars on every screen and at every club — and
/// they are cut on the scale the game itself uses. eFootball's base players run 40 to the mid-80s
/// (the best in the world is 85; the median professional 68), which is why the old letter ladder,
/// cut for a 40-99 scale with A+ at 90, could never award an A to anybody and graded half of every
/// top-flight squad "B+". Measured on the 21,611 players of a world built from the game:
///
///     5★ 83+   the best eighteen in the world        2½★ 68+   the median professional
///     4½★ 80+  ~80 players, every one a star          2★ 65+
///     4★ 77+   top 2%: a first-choice international   1½★ 61+
///     3½★ 74+  top 8%: a good top-flight starter      1★ 56+
///     3★ 71+   top quarter: a top-flight squad man    ½★ below that
///
/// A club's strength (its best eleven's average) reads on the same ladder.
/// </summary>
public static class StarRating
{
    /// <summary>The lowest overall of tiers 2..10 (tier 1 is everything below the first).</summary>
    private static readonly int[] Floors = { 56, 61, 65, 68, 71, 74, 77, 80, 83 };

    /// <summary>1..10: the half-star tier of an internal strength.</summary>
    public static int Tier(int overall)
    {
        var tier = 1;
        foreach (var floor in Floors)
        {
            if (overall >= floor) tier++;
        }
        return tier;
    }

    /// <summary>0.5 .. 5.0.</summary>
    public static double Stars(int overall) => Tier(overall) / 2.0;

    /// <summary>What may be SHOWN of a player: a solid part that is known and a faint part that is
    /// only possible. Exact when Low == High; Unknown when nothing may be shown at all.</summary>
    public readonly record struct Range(double Low, double High)
    {
        public bool IsExact => Low > 0 && Low == High;
        public bool IsUnknown => High <= 0;
    }

    /// <summary>
    /// The stars you are allowed to SEE at a knowledge level (0-100): the true tier once he is
    /// well scouted (75+) or yours; half a star either way while part-scouted (45+); nothing below.
    /// </summary>
    public static Range Masked(int overall, int knowledge)
    {
        var stars = Stars(overall);
        if (knowledge >= 75) return new Range(stars, stars);
        if (knowledge >= 45) return new Range(Math.Max(0.5, stars - 0.5), Math.Min(5.0, stars + 0.5));
        return new Range(0, 0);
    }

    /// <summary>
    /// The public read on a man nobody at the club has watched: his reputation, a window a star and
    /// a half wide that CONTAINS his tier without sitting centred on it — where in the window he
    /// falls is fixed per player, so the same stranger always reads the same and the midpoint
    /// gives nothing away. It replaces the letter band the Market used to infer from his price.
    /// </summary>
    public static Range Reputation(int overall, long playerId)
    {
        var stars = Stars(overall);
        var slide = (int)(unchecked((uint)playerId * 2654435761u) % 4) * 0.5;   // window starts 0..1½ below him
        var low = stars - slide;
        var high = low + 1.5;
        if (low < 0.5) { high += 0.5 - low; low = 0.5; }      // slide the window back inside ½..5;
        if (high > 5.0) { low -= high - 5.0; high = 5.0; }    // he stays inside it either way
        return new Range(low, high);
    }

    /// <summary>"4½★", "½★" — for prose, tooltips and tokens too small for five drawn stars.</summary>
    public static string Text(double stars)
    {
        var whole = (int)Math.Floor(stars);
        var half = stars - whole >= 0.5;
        return (whole > 0 ? whole.ToString() : "") + (half ? "½" : "") + "★";
    }

    public static string Text(int overall) => Text(Stars(overall));

    /// <summary>A masked read as text: "4½★", "3½–4½★", or "?" when nothing is known.</summary>
    public static string Text(Range range) =>
        range.IsUnknown ? "?"
        : range.IsExact ? Text(range.Low)
        : $"{Text(range.Low).TrimEnd('★')}–{Text(range.High)}";
}
