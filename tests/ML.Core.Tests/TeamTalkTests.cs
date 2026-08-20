using ML.Core.Selection;
using Xunit;

namespace ML.Core.Tests;

public class TeamTalkTests
{
    [Fact]
    public void DemandLiftsConfidentFavouritesAndBackfiresOnFragileRooms()
    {
        var confident = TeamTalk.PreMatch(TalkTone.Demand, favourites: true, squadMorale: 70);
        var fragile = TeamTalk.PreMatch(TalkTone.Demand, favourites: false, squadMorale: 30);
        Assert.True(confident.MoraleDelta > 0);
        Assert.True(fragile.MoraleDelta < 0);
    }

    [Fact]
    public void CalmNeverBackfires()
    {
        foreach (var fav in new[] { true, false })
        {
            foreach (var morale in new[] { 15, 50, 90 })
            {
                Assert.True(TeamTalk.PreMatch(TalkTone.Calm, fav, morale).MoraleDelta >= 0);
                Assert.True(TeamTalk.PostMatch(TalkTone.Calm, -1, morale).MoraleDelta >= 0);
            }
        }
    }

    [Fact]
    public void HairdryerAfterALossCutsBothWays()
    {
        Assert.True(TeamTalk.PostMatch(TalkTone.Demand, -1, 70).MoraleDelta > 0);
        Assert.True(TeamTalk.PostMatch(TalkTone.Demand, -1, 30).MoraleDelta < 0);
    }

    [Fact]
    public void HintMatchesTheMoment()
    {
        Assert.Equal(TalkTone.Demand, TeamTalk.Hint(true, favourites: true, 0, 70));
        Assert.Equal(TalkTone.Calm, TeamTalk.Hint(true, favourites: false, 0, 20));
        Assert.Equal(TalkTone.Encourage, TeamTalk.Hint(false, false, outcome: 1, 50));
    }
}
