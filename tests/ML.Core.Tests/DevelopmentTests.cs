using ML.Core.Development;
using Xunit;

namespace ML.Core.Tests;

public class PlayerSkillCatalogTests
{
    [Fact]
    public void Gk_skills_are_for_goalkeepers_only()
    {
        var learnable = PlayerSkillCatalog.LearnableFor("CF", "FWD", Array.Empty<string>());
        Assert.DoesNotContain(learnable, s => s.Name.StartsWith("GK"));
        var gk = PlayerSkillCatalog.LearnableFor("GK", "GK", Array.Empty<string>());
        Assert.All(gk, s => Assert.StartsWith("GK", s.Name));
        Assert.Contains(gk, s => s.Name == "GK Low Punt");
    }

    [Fact]
    public void Innate_skills_are_never_learnable()
    {
        var learnable = PlayerSkillCatalog.LearnableFor("CF", "FWD", Array.Empty<string>());
        Assert.DoesNotContain(learnable, s => s.Name == "Rabona");
        Assert.DoesNotContain(learnable, s => s.Name == "Fighting Spirit");
        Assert.DoesNotContain(learnable, s => s.Name == "Phenomenal Finishing");
        Assert.Contains(learnable, s => s.Name == "Outside Curler");
    }

    [Fact]
    public void Track_back_is_for_midfielders_and_forwards()
    {
        Assert.Contains(PlayerSkillCatalog.LearnableFor("AMF", "MID", Array.Empty<string>()),
            s => s.Name == "Track Back");
        Assert.DoesNotContain(PlayerSkillCatalog.LearnableFor("CB", "DEF", Array.Empty<string>()),
            s => s.Name == "Track Back");
    }

    [Fact]
    public void Known_skills_drop_out_of_the_learnable_list()
    {
        var learnable = PlayerSkillCatalog.LearnableFor("CF", "FWD", new[] { "Outside Curler" });
        Assert.DoesNotContain(learnable, s => s.Name == "Outside Curler");
    }
}

public class PersonalityModelTests
{
    [Fact]
    public void Traits_are_deterministic_per_player_and_in_range()
    {
        var a = PersonalityModel.SeedTraits(20_000_123);
        var b = PersonalityModel.SeedTraits(20_000_123);
        Assert.Equal(a, b);
        foreach (var v in new[] { a.Determination, a.Professionalism, a.Ambition, a.Temperament })
        {
            Assert.InRange(v, 1, 20);
        }
        Assert.NotEqual(PersonalityModel.SeedTraits(1), PersonalityModel.SeedTraits(2));
    }

    [Fact]
    public void Personalities_follow_the_fm_ladder()
    {
        Assert.Equal("Model Professional", PersonalityModel.Personality(19, 19, 10, 10));
        Assert.Equal("Professional", PersonalityModel.Personality(15, 16, 10, 10));
        Assert.Equal("Determined", PersonalityModel.Personality(18, 8, 10, 10));
        Assert.Equal("Ambitious", PersonalityModel.Personality(10, 11, 17, 10));
        Assert.Equal("Mercenary", PersonalityModel.Personality(10, 5, 17, 10));
        Assert.Equal("Temperamental", PersonalityModel.Personality(10, 10, 10, 3));
        Assert.Equal("Casual", PersonalityModel.Personality(10, 4, 10, 10));
        Assert.Equal("Low Determination", PersonalityModel.Personality(3, 10, 10, 10));
        Assert.Equal("Balanced", PersonalityModel.Personality(10, 10, 10, 10));
    }

    [Fact]
    public void Determination_drives_growth()
    {
        Assert.True(PersonalityModel.GrowthMultiplier(20, 15)
                    > PersonalityModel.GrowthMultiplier(10, 10));
        Assert.True(PersonalityModel.GrowthMultiplier(2, 3) < 0.8);
        Assert.InRange(PersonalityModel.GrowthMultiplier(20, 20), 1.0, 1.5);
    }

    [Fact]
    public void Skill_sessions_shrink_with_character_and_coaching()
    {
        Assert.True(PersonalityModel.SkillSessions(18, 15, 1)
                    < PersonalityModel.SkillSessions(5, 5, 0));
        Assert.InRange(PersonalityModel.SkillSessions(20, 20, 2), 3, 12);
        Assert.InRange(PersonalityModel.SkillSessions(1, 1, 0), 3, 12);
    }

    [Fact]
    public void Old_dogs_do_not_learn_new_tricks()
    {
        Assert.True(PersonalityModel.CanStillLearn(24, 10));
        Assert.False(PersonalityModel.CanStillLearn(31, 10));
        Assert.True(PersonalityModel.CanStillLearn(31, 16));   // the determined get one more year
        Assert.False(PersonalityModel.CanStillLearn(33, 20));
    }
}
