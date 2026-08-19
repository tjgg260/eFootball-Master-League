using ML.Core.Management;

namespace ML.Core.Tests;

public class EloRatingTests
{
    [Fact]
    public void EvenSidesFavourTheHomeTeamSlightly()
    {
        var outlook = EloRating.Preview(1500, 1500);
        Assert.True(outlook.HomeWin > outlook.AwayWin);          // home advantage
        Assert.InRange(outlook.Draw, 0.22, 0.28);                // healthy draw share
    }

    [Fact]
    public void ProbabilitiesSumToOneHundredPercent()
    {
        var o = EloRating.Preview(1620, 1490);
        Assert.Equal(100, o.HomePercent + o.DrawPercent + o.AwayPercent);
    }

    [Fact]
    public void StrongerSideIsFavoured()
    {
        var o = EloRating.Preview(1700, 1400);
        Assert.True(o.HomeWin > 0.6);
        Assert.True(o.Draw < 0.24);                              // draw shrinks as sides diverge
    }

    [Fact]
    public void BeatingAStrongerSideGainsMoreThanBeatingAWeakerOne()
    {
        var (upsetGain, _) = EloRating.Update(1400, 1700, actualHome: 1.0);
        var (expectedGain, _) = EloRating.Update(1700, 1400, actualHome: 1.0);
        Assert.True(upsetGain > expectedGain);
        Assert.True(upsetGain > 0 && expectedGain > 0);
    }

    [Fact]
    public void RatingUpdatesAreZeroSum()
    {
        var (home, away) = EloRating.Update(1550, 1500, EloRating.ActualScore(2, 1));
        Assert.Equal(0, home + away);
    }
}
