using ML.Core.Development;
using Xunit;

namespace ML.Core.Tests;

public class AttributeKnowledgeTests
{
    [Fact]
    public void Bands_split_at_the_documented_cutoffs()
    {
        Assert.Equal(0, AttributeKnowledge.Band(40));
        Assert.Equal(0, AttributeKnowledge.Band(57));
        Assert.Equal(1, AttributeKnowledge.Band(58));
        Assert.Equal(1, AttributeKnowledge.Band(69));
        Assert.Equal(2, AttributeKnowledge.Band(70));
        Assert.Equal(2, AttributeKnowledge.Band(79));
        Assert.Equal(3, AttributeKnowledge.Band(80));
        Assert.Equal(3, AttributeKnowledge.Band(99));
    }

    [Fact]
    public void Reveal_is_deterministic_and_monotonic_in_knowledge()
    {
        var attrs = new[] { "speed", "finishing", "ball_control", "tackling", "stamina", "curl" };
        foreach (var a in attrs)
        {
            Assert.Equal(AttributeKnowledge.IsRevealed(123, a, 50),
                         AttributeKnowledge.IsRevealed(123, a, 50));
            // More knowledge never HIDES an attribute.
            for (var k = 0; k < 100; k += 10)
            {
                if (AttributeKnowledge.IsRevealed(123, a, k))
                {
                    Assert.True(AttributeKnowledge.IsRevealed(123, a, k + 10));
                }
            }
        }
        Assert.All(attrs, a => Assert.True(AttributeKnowledge.IsRevealed(123, a, 100)));
        Assert.All(attrs, a => Assert.False(AttributeKnowledge.IsRevealed(123, a, 0)));
    }

    [Fact]
    public void Partial_knowledge_reveals_roughly_the_right_share()
    {
        var attrs = new[]
        {
            "offensive_awareness", "ball_control", "dribbling", "tight_possession", "low_pass",
            "lofted_pass", "finishing", "heading", "set_piece_taking", "curl", "speed",
            "acceleration", "kicking_power", "jumping", "physical_contact", "balance",
            "stamina", "defensive_awareness", "tackling", "aggression", "defensive_engagement",
        };
        var revealed = attrs.Count(a => AttributeKnowledge.IsRevealed(777, a, 50));
        Assert.InRange(revealed, 5, 16);   // ~half, with hash noise
    }

    [Fact]
    public void Coach_phrases_read_like_a_coach()
    {
        Assert.Equal("Exceptional close control", AttributeKnowledge.CoachPhrase("ball_control", 90));
        Assert.Equal("Poor heading", AttributeKnowledge.CoachPhrase("heading", 45));
        Assert.Equal("Excellent burst over the first yards", AttributeKnowledge.CoachPhrase("acceleration", 84));
    }

    [Fact]
    public void Coach_report_praises_strengths_and_flags_flaws()
    {
        var abilities = new Dictionary<string, int>
        {
            ["ball_control"] = 90, ["dribbling"] = 85, ["speed"] = 82,
            ["heading"] = 45, ["tackling"] = 50, ["stamina"] = 70,
        };
        var report = AttributeKnowledge.CoachReport(1, abilities, isGk: false, knowledge: 100);
        Assert.Contains("Exceptional close control", report);
        Assert.Contains("Poor heading", report);
        Assert.True(report.Count is >= 3 and <= 5);
    }

    [Fact]
    public void Unknown_players_yield_an_empty_coach_report()
    {
        var abilities = new Dictionary<string, int> { ["ball_control"] = 90, ["speed"] = 88 };
        Assert.Empty(AttributeKnowledge.CoachReport(1, abilities, false, knowledge: 0));
    }
}
