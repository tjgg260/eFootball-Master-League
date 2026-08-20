using ML.Core.Scheduling;
using Xunit;

namespace ML.Core.Tests;

public class SeasonCalendarTests
{
    [Fact]
    public void SeasonStartsOnTheFirstSaturdayOfAugust()
    {
        var d = SeasonCalendar.FirstLeagueSaturday(2026);
        Assert.Equal(DayOfWeek.Saturday, d.DayOfWeek);
        Assert.Equal(8, d.Month);
        Assert.True(d.Day <= 7);
    }

    [Fact]
    public void LeagueRoundsAreWeeklySaturdays()
    {
        var md1 = SeasonCalendar.DateOf(2026, 1, "league");
        var md2 = SeasonCalendar.DateOf(2026, 2, "league");
        Assert.Equal(DayOfWeek.Saturday, md1.DayOfWeek);
        Assert.Equal(7, md2.DayNumber - md1.DayNumber);
    }

    [Fact]
    public void CupRoundsAreTheMidweekWednesday()
    {
        var league = SeasonCalendar.DateOf(2026, 8, "league");
        var cup = SeasonCalendar.DateOf(2026, 8, "cup");
        Assert.Equal(DayOfWeek.Wednesday, cup.DayOfWeek);
        Assert.Equal(4, cup.DayNumber - league.DayNumber);
    }

    [Fact]
    public void FriendliesSitInLateJuly()
    {
        var ps = SeasonCalendar.DateOf(2026, 0, "friendly");
        Assert.Equal(7, ps.Month);
        Assert.True(ps < SeasonCalendar.FirstLeagueSaturday(2026));
    }
}
