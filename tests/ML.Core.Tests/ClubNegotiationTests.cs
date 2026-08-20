using ML.Core.Management;
using Xunit;
using static ML.Core.Management.ClubNegotiation;

namespace ML.Core.Tests;

public class ClubNegotiationTests
{
    private const long Value = 8_000_000;

    [Fact]
    public void Sell_on_and_instalments_change_the_package_value()
    {
        var flat = EffectiveValue(8_000_000, 0, false, Value);
        var sellOn = EffectiveValue(8_000_000, 15, false, Value);
        var paid = EffectiveValue(8_000_000, 0, true, Value);
        Assert.Equal(8_000_000, flat);
        Assert.Equal(8_000_000 + (long)(0.15 * Value * 0.6), sellOn);
        Assert.True(paid < flat);   // instalments cost the seller time-value
    }

    [Fact]
    public void Package_within_three_percent_closes()
    {
        var (v, _) = Respond(10_000_000, 9_800_000, 0, false, Value, round: 1);
        Assert.Equal(Verdict.Accepted, v);
    }

    [Fact]
    public void Sell_on_can_close_a_gap_cash_cannot()
    {
        var (cashOnly, _) = Respond(10_000_000, 9_300_000, 0, false, Value, 1);
        var (withSellOn, _) = Respond(10_000_000, 9_300_000, 15, false, Value, 1);
        Assert.Equal(Verdict.Countered, cashOnly);
        Assert.Equal(Verdict.Accepted, withSellOn);
    }

    [Fact]
    public void Lowballs_end_talks_and_counters_ease_the_ask()
    {
        var (walk, _) = Respond(10_000_000, 7_000_000, 0, false, Value, 1);
        Assert.Equal(Verdict.WalkedAway, walk);
        var (counter, newAsk) = Respond(10_000_000, 8_600_000, 0, false, Value, 1);
        Assert.Equal(Verdict.Countered, counter);
        Assert.InRange(newAsk, Value, 10_000_000);
        Assert.True(newAsk < 10_000_000);
    }

    [Fact]
    public void Round_three_is_final()
    {
        var (v, _) = Respond(10_000_000, 8_600_000, 0, false, Value, round: 3);
        Assert.Equal(Verdict.WalkedAway, v);
    }

    [Fact]
    public void Likelihood_is_bounded_and_monotonic()
    {
        var low = Likelihood(10_000_000, 7_500_000, 0, false, Value);
        var mid = Likelihood(10_000_000, 9_000_000, 0, false, Value);
        var high = Likelihood(10_000_000, 9_900_000, 15, false, Value);
        Assert.True(low < mid && mid < high);
        Assert.InRange(low, 2, 98);
        Assert.InRange(high, 2, 98);
    }

    [Fact]
    public void Opening_ask_scales_with_difficulty()
    {
        Assert.True(OpeningAsk(Value, 10, 115) > OpeningAsk(Value, 10, 100));
        Assert.True(OpeningAsk(Value, 10, 90) < OpeningAsk(Value, 10, 100));
    }
}
