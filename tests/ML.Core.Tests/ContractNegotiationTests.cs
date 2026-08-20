using ML.Core.Selection;
using Xunit;

namespace ML.Core.Tests;

public class ContractNegotiationTests
{
    [Fact]
    public void StarsInTheirPeakCostMore()
    {
        var star = ContractNegotiation.WeeklyDemand(85, 26, 60, 2);
        var journeyman = ContractNegotiation.WeeklyDemand(68, 26, 60, 2);
        var veteran = ContractNegotiation.WeeklyDemand(85, 34, 60, 2);
        Assert.True(star > journeyman);
        Assert.True(star > veteran);
    }

    [Fact]
    public void UnhappyPlayersWantAPremium()
    {
        var content = ContractNegotiation.WeeklyDemand(75, 26, 70, 2);
        var unsettled = ContractNegotiation.WeeklyDemand(75, 26, 30, 2);
        Assert.True(unsettled > content);
    }

    [Fact]
    public void FairOfferAccepted_LowballCountered_InsultEndsTalks()
    {
        const long demand = 4000;
        Assert.Equal(NegotiationOutcome.Accepted,
            ContractNegotiation.Respond(3950, demand, null, 1).Outcome);
        var (outcome, counter) = ContractNegotiation.Respond(3200, demand, null, 1);
        Assert.Equal(NegotiationOutcome.Countered, outcome);
        Assert.InRange(counter, 3200, demand + 50);
        Assert.Equal(NegotiationOutcome.WalkedAway,
            ContractNegotiation.Respond(2000, demand, null, 1).Outcome);
    }

    [Fact]
    public void StatusPromiseBuysADiscount()
    {
        const long demand = 4000;
        // 3750 is short of the plain target but inside the Star-status discounted one.
        Assert.Equal(NegotiationOutcome.Countered,
            ContractNegotiation.Respond(3600, demand, null, 1).Outcome);
        Assert.Equal(NegotiationOutcome.Accepted,
            ContractNegotiation.Respond(3600, demand, "Star", 1).Outcome);
    }

    [Fact]
    public void TalksEndByRoundThree()
    {
        Assert.Equal(NegotiationOutcome.WalkedAway,
            ContractNegotiation.Respond(3200, 4000, null, 3).Outcome);
    }
}
