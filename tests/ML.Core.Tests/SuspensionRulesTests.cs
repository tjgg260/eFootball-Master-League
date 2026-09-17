using ML.Core.Selection;

namespace ML.Core.Tests;

public class SuspensionRulesTests
{
    [Fact]
    public void ARedCardIsOneMatch()
    {
        Assert.Equal(1, SuspensionRules.MatchesFor(redsThisMatch: 1, yellowsThisMatch: 0, seasonYellowsBefore: 0));
        Assert.Equal("red card", SuspensionRules.Reason(1, 0, 0));
    }

    [Fact]
    public void AYellowOnItsOwnBansNobody()
    {
        Assert.Equal(0, SuspensionRules.MatchesFor(0, 1, 0));
        Assert.Equal(0, SuspensionRules.MatchesFor(0, 1, 3));
    }

    [Fact]
    public void TheFifthYellowOfTheSeasonIsOneMatch()
    {
        Assert.Equal(1, SuspensionRules.MatchesFor(0, 1, 4));
        Assert.Equal("5 yellow cards", SuspensionRules.Reason(0, 1, 4));
    }

    [Fact]
    public void TheSixthIsNotAndTheTenthIsAgain()
    {
        Assert.Equal(0, SuspensionRules.MatchesFor(0, 1, 5));
        Assert.Equal(1, SuspensionRules.MatchesFor(0, 1, 9));
        Assert.Equal("10 yellow cards", SuspensionRules.Reason(0, 1, 9));
    }

    [Fact]
    public void TwoBookingsAndOffIsOneOffenceNotTwo()
    {
        // The two yellows bought the red: they do not also count toward the five.
        Assert.Equal(0, SuspensionRules.CountedYellows(redsThisMatch: 1, yellowsThisMatch: 2));
        Assert.Equal(1, SuspensionRules.MatchesFor(1, 2, 4));
        Assert.Equal("red card", SuspensionRules.Reason(1, 2, 4));
    }

    [Fact]
    public void ABookingThenAStraightRedCountsBoth()
    {
        // One yellow and a red: a straight red on top of an ordinary booking — and that booking was his fifth.
        Assert.Equal(1, SuspensionRules.CountedYellows(1, 1));
        Assert.Equal(2, SuspensionRules.MatchesFor(1, 1, 4));
        Assert.Equal("red card and 5 yellow cards", SuspensionRules.Reason(1, 1, 4));
    }
}
