using ML.Core.Selection;

namespace ML.Core.Tests;

public class XiSelectorTests
{
    private static CandidatePlayer P(int id, string cat, int rating = 75, int fatigue = 0,
        double form = 6.5, bool injured = false) => new(id, rating, cat, fatigue, form, injured);

    private static readonly string[] Back4 = { "GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD", "FWD" };

    [Fact]
    public void SlotsAreFilledByMatchingCategoryInSlotOrder()
    {
        var squad = new[]
        {
            P(1, "GK"), P(2, "GK", rating: 70),
            P(3, "DEF"), P(4, "DEF"), P(5, "DEF"), P(6, "DEF"), P(7, "DEF", rating: 70),
            P(8, "MID"), P(9, "MID"), P(10, "MID"), P(11, "MID", rating: 70),
            P(12, "FWD"), P(13, "FWD"), P(14, "FWD"), P(15, "FWD", rating: 70),
        };
        var byId = squad.ToDictionary(p => p.PlayerId);

        var order = XiSelector.SelectOrder(squad, Back4);

        for (var slot = 0; slot < Back4.Length; slot++)
            Assert.Equal(Back4[slot], byId[order[slot]].PositionCategory);
    }

    [Fact]
    public void BestScorerInTheCategoryTakesTheSlot()
    {
        // Fresher, in-form 78 outranks a shattered, out-of-form 84: 78-0+8=86 vs 84-15+4.5=73.5.
        var squad = new[]
        {
            P(1, "FWD", rating: 84, fatigue: 60, form: 4.5),
            P(2, "FWD", rating: 78, fatigue: 0, form: 8.0),
        };

        var order = XiSelector.SelectOrder(squad, new[] { "FWD" });

        Assert.Equal(2, order[0]);
        Assert.Equal(1, order[1]);
    }

    [Fact]
    public void InjuredPlayersNeverStartAndSortLast()
    {
        var squad = new[]
        {
            P(1, "GK", rating: 90, injured: true),       // best keeper, but out
            P(2, "GK", rating: 70),
            P(3, "DEF", rating: 80),
        };

        var order = XiSelector.SelectOrder(squad, new[] { "GK" });

        Assert.Equal(2, order[0]);                       // fit keeper starts
        Assert.Equal(3, order[1]);                       // fit bench before
        Assert.Equal(1, order[2]);                       // ...the injured star, listed last
    }

    [Fact]
    public void UnfillableCategoryFallsBackToBestAvailableAnyCategory()
    {
        var squad = new[] { P(1, "DEF", rating: 70), P(2, "MID", rating: 82), P(3, "FWD", rating: 76) };

        var order = XiSelector.SelectOrder(squad, new[] { "GK", "DEF" });

        Assert.Equal(2, order[0]);                       // no GK exists: best of the rest deputises
        Assert.Equal(1, order[1]);                       // DEF slot still category-matched
        Assert.Equal(3, order[2]);
    }

    [Fact]
    public void TiesBreakByRatingThenPlayerId()
    {
        // 80-rated on 16 fatigue and 76-rated fresh both score 82.5: the higher rating wins.
        // Identical twins (9 and 2) resolve by lower id first.
        var squad = new[]
        {
            P(9, "MID", rating: 74), P(2, "MID", rating: 74),
            P(6, "MID", rating: 76), P(4, "MID", rating: 80, fatigue: 16),
        };

        var order = XiSelector.SelectOrder(squad, new[] { "MID" });

        Assert.Equal(new[] { 4, 6, 2, 9 }, order);
    }

    [Fact]
    public void SameInputsAlwaysProduceTheSameOrder()
    {
        var squad = Enumerable.Range(1, 18)
            .Select(i => P(i, Back4[i % Back4.Length], rating: 70 + i % 9, fatigue: i % 4 * 8, form: 5 + i % 3))
            .ToArray();

        var first = XiSelector.SelectOrder(squad, Back4);
        var again = XiSelector.SelectOrder(squad, Back4);

        Assert.Equal(first, again);
    }

    [Fact]
    public void EverySquadPlayerAppearsExactlyOnce()
    {
        var squad = Enumerable.Range(1, 20)
            .Select(i => P(i, Back4[i % Back4.Length], rating: 65 + i, injured: i % 7 == 0))
            .ToArray();

        var order = XiSelector.SelectOrder(squad, Back4);

        Assert.Equal(squad.Length, order.Count);
        Assert.Equal(squad.Select(p => p.PlayerId).OrderBy(x => x), order.OrderBy(x => x));
    }

    [Fact]
    public void BenchIsOrderedByScoreDescending()
    {
        var squad = new[]
        {
            P(1, "GK", rating: 80),
            P(2, "GK", rating: 70),                      // bench: score 76.5
            P(3, "DEF", rating: 74),                     // bench: score 80.5
            P(4, "MID", rating: 78, fatigue: 40),        // bench: score 74.5
        };

        var order = XiSelector.SelectOrder(squad, new[] { "GK" });

        Assert.Equal(new[] { 1, 3, 2, 4 }, order);
    }
}
