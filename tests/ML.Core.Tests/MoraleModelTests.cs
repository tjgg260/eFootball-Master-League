using ML.Core.Selection;
using Xunit;

namespace ML.Core.Tests;

public class MoraleModelTests
{
    [Fact]
    public void StartersGainMoreThanBenchOnAWin()
    {
        var starter = MoraleModel.AfterMatchday(50, started: true, outcome: 1, transferListed: false);
        var benched = MoraleModel.AfterMatchday(50, started: false, outcome: 1, transferListed: false);
        Assert.True(starter > benched);
        Assert.True(starter > 50);
    }

    [Fact]
    public void BenchedLossOnTheListGrindsDown()
    {
        var m = 50;
        for (var i = 0; i < 10; i++)
        {
            m = MoraleModel.AfterMatchday(m, started: false, outcome: -1, transferListed: true);
        }
        Assert.True(m < MoraleModel.RequestThreshold + 10);
    }

    [Fact]
    public void ClampsToBounds()
    {
        Assert.Equal(MoraleModel.Min,
            MoraleModel.AfterMatchday(MoraleModel.Min, false, -1, true));
        Assert.True(MoraleModel.AfterMatchday(MoraleModel.Max, true, 1, false) <= MoraleModel.Max);
    }

    [Fact]
    public void DriftsTowardNeutralWithoutAMatch()
    {
        var high = MoraleModel.AfterMatchday(90, started: false, outcome: null, transferListed: false);
        var low = MoraleModel.AfterMatchday(15, started: false, outcome: null, transferListed: false);
        Assert.True(high < 90);
        Assert.True(low > 15);
    }

    [Fact]
    public void TalksAreBoundedBothWays()
    {
        Assert.Equal(54, MoraleModel.AfterTalk(50, praise: true));
        Assert.Equal(46, MoraleModel.AfterTalk(50, praise: false));
        Assert.Equal(MoraleModel.Max, MoraleModel.AfterTalk(MoraleModel.Max, praise: true));
    }

    [Fact]
    public void BrokenPromisesHurtMoreThanKeptOnesHelp()
    {
        var kept = MoraleModel.AfterPromise(50, kept: true) - 50;
        var broken = 50 - MoraleModel.AfterPromise(50, kept: false);
        Assert.True(broken > kept);
    }

    [Fact]
    public void FormAdjustmentIsBoundedAndSigned()
    {
        Assert.True(MoraleModel.FormAdjustment(MoraleModel.Max) is > 0 and <= 2.0);
        Assert.True(MoraleModel.FormAdjustment(MoraleModel.Min) is < 0 and >= -2.0);
        Assert.Equal(0, MoraleModel.FormAdjustment(MoraleModel.Neutral), 3);
    }
}
