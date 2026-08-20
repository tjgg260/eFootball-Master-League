using ML.Core.Management;
using Xunit;

namespace ML.Core.Tests;

public class ManagerCareerTests
{
    [Fact]
    public void Rep_rises_more_for_beating_a_stronger_side()
    {
        Assert.Equal(37, ManagerCareer.RepAfterResult(35, 2, 1, oppositionStronger: true));
        Assert.Equal(36, ManagerCareer.RepAfterResult(35, 2, 1, oppositionStronger: false));
    }

    [Fact]
    public void Rep_only_falls_for_losing_to_a_weaker_side()
    {
        Assert.Equal(35, ManagerCareer.RepAfterResult(35, 0, 1, oppositionStronger: true));
        Assert.Equal(34, ManagerCareer.RepAfterResult(35, 0, 1, oppositionStronger: false));
    }

    [Fact]
    public void Rep_draw_against_stronger_side_still_earns()
    {
        Assert.Equal(36, ManagerCareer.RepAfterResult(35, 1, 1, oppositionStronger: true));
        Assert.Equal(35, ManagerCareer.RepAfterResult(35, 1, 1, oppositionStronger: false));
    }

    [Fact]
    public void Rep_is_clamped_to_the_scale()
    {
        Assert.Equal(100, ManagerCareer.RepAfterResult(100, 3, 0, true));
        Assert.Equal(0, ManagerCareer.RepAfterResult(0, 0, 3, false));
    }

    [Fact]
    public void Season_rep_rewards_titles_promotions_and_trophies()
    {
        // Top-flight champions: +6.
        Assert.Equal(41, ManagerCareer.RepAfterSeason(35, 1, 20, topFlight: true, promoted: false, trophies: 0));
        // Promoted division-2 champions: +4 title, +5 promotion.
        Assert.Equal(44, ManagerCareer.RepAfterSeason(35, 1, 20, topFlight: false, promoted: true, trophies: 0));
        // A cup on top of mid-table safety: +4.
        Assert.Equal(41, ManagerCareer.RepAfterSeason(35, 8, 20, topFlight: true, promoted: false, trophies: 1));
    }

    [Fact]
    public void Season_rep_punishes_the_relegation_places()
    {
        Assert.Equal(32, ManagerCareer.RepAfterSeason(35, 19, 20, topFlight: true, promoted: false, trophies: 0));
    }

    [Fact]
    public void Expectation_scales_with_squad_rank()
    {
        Assert.Equal(Expectation.Title, ManagerCareer.ExpectationFor(1, 20, topFlight: true));
        Assert.Equal(Expectation.Playoffs, ManagerCareer.ExpectationFor(4, 20, topFlight: true));
        Assert.Equal(Expectation.MidTable, ManagerCareer.ExpectationFor(10, 20, topFlight: true));
        Assert.Equal(Expectation.LowerMidTable, ManagerCareer.ExpectationFor(14, 20, topFlight: true));
        Assert.Equal(Expectation.Survival, ManagerCareer.ExpectationFor(19, 20, topFlight: true));
        Assert.Equal(Expectation.Promotion, ManagerCareer.ExpectationFor(1, 20, topFlight: false));
    }

    [Fact]
    public void Sack_is_instant_on_the_floor_and_patient_above_it()
    {
        Assert.True(ManagerCareer.ShouldSack(confidence: 3, matchdaysUnderThreat: 0));
        Assert.False(ManagerCareer.ShouldSack(confidence: 15, matchdaysUnderThreat: 4));
        Assert.True(ManagerCareer.ShouldSack(confidence: 15, matchdaysUnderThreat: 5));
        Assert.False(ManagerCareer.ShouldSack(confidence: 45, matchdaysUnderThreat: 99));
    }

    [Fact]
    public void Bigger_clubs_demand_a_bigger_name()
    {
        // The league's best club will not touch an unknown.
        Assert.False(ManagerCareer.ClubWouldOffer(rep: 35, clubStrengthRank: 1, clubCount: 40));
        Assert.True(ManagerCareer.ClubWouldOffer(rep: 80, clubStrengthRank: 1, clubCount: 40));
        // The bottom club takes almost anyone.
        Assert.True(ManagerCareer.ClubWouldOffer(rep: 35, clubStrengthRank: 40, clubCount: 40));
    }

    [Fact]
    public void Target_position_tracks_the_expectation()
    {
        Assert.Equal(1, ManagerCareer.TargetPosition(Expectation.Title, 20));
        Assert.Equal(5, ManagerCareer.TargetPosition(Expectation.Playoffs, 20));
        Assert.Equal(10, ManagerCareer.TargetPosition(Expectation.MidTable, 20));
        Assert.Equal(17, ManagerCareer.TargetPosition(Expectation.Survival, 20));
    }
}
