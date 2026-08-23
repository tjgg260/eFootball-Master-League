namespace ML.Core.Selection;

/// <summary>
/// One squad player as the AI manager sees him on matchday. <see cref="PositionCategory"/> is
/// GK/DEF/MID/FWD (see <see cref="PositionCodes"/>); Fatigue and Form come from the
/// player_condition table via <see cref="ConditionModel"/>.
/// </summary>
public sealed record CandidatePlayer(
    long PlayerId, int Rating, string PositionCategory, int Fatigue, double Form, bool Injured);

/// <summary>
/// Deterministic AI matchday selection. Given a squad and the formation's slot categories
/// (in slot order), produces a full squad ordering: the starting XI first, then the bench.
/// No randomness — the same squad state always yields the same XI, so a replayed matchday
/// compiles the same team sheet.
/// </summary>
public static class XiSelector
{
    /// <summary>
    /// Returns every squad player's id exactly once. The first slotCategories.Count ids are the
    /// starting XI in slot order: each slot is filled greedily with the best-scoring available
    /// (not injured, not already picked) player whose category matches the slot, falling back to
    /// the best available of any category when none match. The remainder is the bench by score
    /// descending, with injured players last (also by score). Score = Rating - Fatigue/4 + Form;
    /// ties break by score desc, then Rating desc, then PlayerId asc.
    /// </summary>
    public static IReadOnlyList<long> SelectOrder(
        IReadOnlyList<CandidatePlayer> squad, IReadOnlyList<string> slotCategories)
    {
        var picked = new HashSet<long>();
        var order = new List<long>(squad.Count);

        foreach (var category in slotCategories)
        {
            var choice =
                Best(squad, p => !picked.Contains(p.PlayerId) && !p.Injured && p.PositionCategory == category)
                ?? Best(squad, p => !picked.Contains(p.PlayerId) && !p.Injured)
                // Degenerate cases (injuries outnumber the squad): an XI must still be named.
                ?? Best(squad, p => !picked.Contains(p.PlayerId) && p.PositionCategory == category)
                ?? Best(squad, p => !picked.Contains(p.PlayerId));
            if (choice is null) break;                           // squad smaller than the formation
            picked.Add(choice.PlayerId);
            order.Add(choice.PlayerId);
        }

        AppendByScore(order, squad, p => !picked.Contains(p.PlayerId) && !p.Injured);
        AppendByScore(order, squad, p => !picked.Contains(p.PlayerId) && p.Injured);
        return order;
    }

    /// <summary>
    /// Position-aware selection: slots carry EXACT position labels ("LB", "AMF"), and each
    /// candidate's registered + learned positions shape the score via <see cref="PositionFit"/> —
    /// a Natural fit outranks a same-unit stand-in, and out-of-unit picks are heavily penalised
    /// (chosen only when nobody in the unit is available). Ordering guarantees match
    /// <see cref="SelectOrder(IReadOnlyList{CandidatePlayer},IReadOnlyList{string})"/>.
    /// </summary>
    public static IReadOnlyList<long> SelectOrder(
        IReadOnlyList<CandidatePlayer> squad,
        IReadOnlyList<string> slotPositions,
        Func<long, (string Registered, IReadOnlyCollection<string> Learned)> positionsOf,
        Func<long, string, int?>? ratingAt = null)
    {
        var picked = new HashSet<long>();
        var order = new List<long>(squad.Count);

        double SlotScore(CandidatePlayer p, string slot)
        {
            var (reg, learned) = positionsOf(p.PlayerId);
            // When abilities are known, the slot rating IS position-adjusted (a winger's GK
            // overall is his gk_* abilities, ~40) — the flat fit bonus then only breaks ties
            // toward trained positions. Without abilities, fall back to native rating + bonus,
            // which is too weak a penalty on its own to keep a star winger out of goal — so a
            // GK/outfield mismatch gets a hard extra penalty there.
            var adjusted = ratingAt?.Invoke(p.PlayerId, slot);
            var baseScore = (adjusted ?? p.Rating) - p.Fatigue / 4.0 + p.Form
                            + PositionFit.Bonus(PositionFit.Of(reg, learned, slot));
            if (adjusted is null
                && (slot == "GK") != (PositionFit.Category(reg) == "GK"))
            {
                baseScore -= 40;                 // never a winger in goal / keeper up front
            }
            return baseScore;
        }

        foreach (var slot in slotPositions)
        {
            CandidatePlayer? best = null;
            double bestScore = double.MinValue;
            foreach (var p in squad)
            {
                if (picked.Contains(p.PlayerId) || p.Injured) continue;
                var s = SlotScore(p, slot);
                if (best is null || s > bestScore
                    || (s == bestScore && (p.Rating > best.Rating
                        || (p.Rating == best.Rating && p.PlayerId < best.PlayerId))))
                {
                    best = p;
                    bestScore = s;
                }
            }
            best ??= Best(squad, p => !picked.Contains(p.PlayerId));   // injuries outnumber the squad
            if (best is null) break;
            picked.Add(best.PlayerId);
            order.Add(best.PlayerId);
        }

        AppendByScore(order, squad, p => !picked.Contains(p.PlayerId) && !p.Injured);
        AppendByScore(order, squad, p => !picked.Contains(p.PlayerId) && p.Injured);
        return order;
    }

    /// <summary>Matchday desirability: high rating helps, fatigue hurts, form helps.</summary>
    public static double Score(CandidatePlayer p) => p.Rating - p.Fatigue / 4.0 + p.Form;

    private static CandidatePlayer? Best(
        IReadOnlyList<CandidatePlayer> squad, Func<CandidatePlayer, bool> eligible)
    {
        CandidatePlayer? best = null;
        foreach (var p in squad)
        {
            if (!eligible(p)) continue;
            if (best is null || Compare(p, best) < 0) best = p;
        }
        return best;
    }

    private static void AppendByScore(
        List<long> order, IReadOnlyList<CandidatePlayer> squad, Func<CandidatePlayer, bool> eligible)
    {
        var group = new List<CandidatePlayer>();
        foreach (var p in squad)
            if (eligible(p)) group.Add(p);
        group.Sort(Compare);
        foreach (var p in group) order.Add(p.PlayerId);
    }

    /// <summary>Total order: score desc, Rating desc, PlayerId asc. Negative = a ranks first.</summary>
    private static int Compare(CandidatePlayer a, CandidatePlayer b)
    {
        var byScore = Score(b).CompareTo(Score(a));
        if (byScore != 0) return byScore;
        var byRating = b.Rating.CompareTo(a.Rating);
        if (byRating != 0) return byRating;
        return a.PlayerId.CompareTo(b.PlayerId);
    }
}
