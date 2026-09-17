using ML.Core.Development;

namespace ML.Core.Tests;

public class StarRatingTests
{
    [Theory]
    [InlineData(40, 0.5)]
    [InlineData(55, 0.5)]
    [InlineData(56, 1.0)]
    [InlineData(68, 2.5)]   // the median professional
    [InlineData(71, 3.0)]
    [InlineData(77, 4.0)]
    [InlineData(82, 4.5)]
    [InlineData(83, 5.0)]
    [InlineData(99, 5.0)]
    public void TenHalfStarTiersOnTheGamesOwnScale(int overall, double stars) =>
        Assert.Equal(stars, StarRating.Stars(overall));

    [Fact]
    public void ABetterPlayerNeverHasFewerStars()
    {
        for (var o = 40; o < 99; o++)
            Assert.True(StarRating.Tier(o + 1) >= StarRating.Tier(o));
        Assert.Equal(1, StarRating.Tier(0));
        Assert.Equal(10, StarRating.Tier(99));
    }

    [Fact]
    public void TextIsStarsNeverANumberOutOfAHundred()
    {
        Assert.Equal("4½★", StarRating.Text(4.5));
        Assert.Equal("3★", StarRating.Text(3.0));
        Assert.Equal("½★", StarRating.Text(0.5));
        Assert.Equal("5★", StarRating.Text(85));
    }

    [Fact]
    public void WhatYouSeeSharpensWithWhatYouKnow()
    {
        var known = StarRating.Masked(77, 100);
        Assert.True(known.IsExact);
        Assert.Equal(4.0, known.Low);

        var partly = StarRating.Masked(77, 50);
        Assert.Equal((3.5, 4.5), (partly.Low, partly.High));
        Assert.Equal("3½–4½★", StarRating.Text(partly));

        var stranger = StarRating.Masked(77, 10);
        Assert.True(stranger.IsUnknown);
        Assert.Equal("?", StarRating.Text(stranger));
    }

    [Fact]
    public void PartScoutedRangesStayOnTheLadder()
    {
        Assert.Equal((0.5, 1.0), (StarRating.Masked(40, 50).Low, StarRating.Masked(40, 50).High));
        Assert.Equal((4.5, 5.0), (StarRating.Masked(90, 50).Low, StarRating.Masked(90, 50).High));
    }

    [Fact]
    public void AReputationIsAWindowThatHoldsHimWithoutCentringOnHim()
    {
        var offsets = new HashSet<double>();
        for (long id = 1; id <= 400; id++)
        {
            foreach (var overall in new[] { 45, 60, 68, 74, 80, 85 })
            {
                var r = StarRating.Reputation(overall, id);
                var stars = StarRating.Stars(overall);
                Assert.InRange(stars, r.Low, r.High);             // he is always inside it
                Assert.Equal(1.5, r.High - r.Low, 6);             // always a star and a half wide
                Assert.InRange(r.Low, 0.5, 5.0);
                Assert.InRange(r.High, 0.5, 5.0);
                if (overall == 74) offsets.Add(stars - r.Low);
            }
            Assert.Equal(StarRating.Reputation(74, id), StarRating.Reputation(74, id));   // stable per player
        }
        Assert.True(offsets.Count >= 3);   // the midpoint gives nothing away
    }
}
