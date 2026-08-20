using ML.Core.Selection;
using Xunit;

namespace ML.Core.Tests;

public class OppositionBriefingTests
{
    [Fact]
    public void EveryStyleHasACompleteCounterPlan()
    {
        for (var style = 0; style <= 5; style++)
        {
            var (shape, counterStyle, line) = OppositionBriefing.Counter(style);
            Assert.False(string.IsNullOrWhiteSpace(shape));
            Assert.False(string.IsNullOrWhiteSpace(counterStyle));
            Assert.True(line.Length > 20);
        }
    }

    [Fact]
    public void OutWideOpponentsMeetABackThree()
    {
        Assert.Equal("3-5-2", OppositionBriefing.Counter(4).Shape);
    }

    [Fact]
    public void CounterTeamsAreStarvedOfTransitions()
    {
        Assert.Equal("Possession Game", OppositionBriefing.Counter(1).Style);
        Assert.Equal("Possession Game", OppositionBriefing.Counter(2).Style);
    }
}
