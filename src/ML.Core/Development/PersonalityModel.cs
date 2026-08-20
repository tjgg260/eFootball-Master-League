namespace ML.Core.Development;

/// <summary>
/// The FM-style character layer: three hidden traits (professionalism, ambition, temperament,
/// each 1-20) plus the visible Determination 1-20 combine into a named personality, and the
/// personality + determination drive how well a player develops and how fast he learns skills.
/// Pure maths — trait storage lives in the app layer.
/// </summary>
public static class PersonalityModel
{
    /// <summary>
    /// Deterministic traits for a player who has none on file yet: a bell-ish 1-20 spread
    /// seeded by the player id, so the same player always rolls the same character.
    /// </summary>
    public static (int Determination, int Professionalism, int Ambition, int Temperament)
        SeedTraits(int playerId)
    {
        // Three xorshift-style draws per trait, averaged: mean 10.5, tails rare (FM-like).
        int Draw(int salt)
        {
            var h = unchecked((uint)(playerId * 2654435761) ^ (uint)(salt * 40503));
            h ^= h >> 13; h = unchecked(h * 2246822519); h ^= h >> 11;
            var a = (int)(h % 20) + 1;
            var b = (int)((h >> 8) % 20) + 1;
            var c = (int)((h >> 16) % 20) + 1;
            return (a + b + c + 1) / 3;
        }
        return (Draw(1), Draw(2), Draw(3), Draw(4));
    }

    /// <summary>The FM-style personality name, derived from the traits.</summary>
    public static string Personality(int determination, int professionalism, int ambition, int temperament)
    {
        if (professionalism >= 18 && determination >= 18) return "Model Professional";
        if (professionalism >= 15 && determination >= 15) return "Professional";
        if (determination >= 17) return "Determined";
        if (ambition >= 16 && professionalism >= 10) return "Ambitious";
        if (ambition >= 16) return "Mercenary";
        if (temperament <= 4) return "Temperamental";
        if (professionalism <= 5) return "Casual";
        if (determination <= 4) return "Low Determination";
        if (professionalism >= 12 || determination >= 12) return "Fairly Professional";
        return "Balanced";
    }

    /// <summary>
    /// Season development multiplier: how much of a growth (or decline-softening) year the
    /// character earns. 1.0 is neutral; the span is deliberately FM-ish (0.6 – 1.5).
    /// </summary>
    public static double GrowthMultiplier(int determination, int professionalism)
    {
        var m = 1.0 + (determination - 10.5) * 0.03 + (professionalism - 10.5) * 0.02;
        return Math.Clamp(m, 0.6, 1.5);
    }

    /// <summary>
    /// Matchweeks of training needed to learn a skill: driven players with a good coach learn
    /// in a handful of sessions; slackers take most of a half-season. Range 3-12.
    /// </summary>
    public static int SkillSessions(int determination, int professionalism, int coachBonus)
    {
        var sessions = 10 - determination / 3 - professionalism / 5 - coachBonus;
        return Math.Clamp(sessions, 3, 12);
    }

    /// <summary>
    /// Age gate for skill learning: a 33-year-old does not pick up new tricks. Learners are
    /// under 30, with determined characters trusted a season longer.
    /// </summary>
    public static bool CanStillLearn(int age, int determination) =>
        age < 30 || (age <= 31 && determination >= 15);

    /// <summary>Morale swing scaling: temperamental players feel everything harder.</summary>
    public static double MoraleResilience(int temperament) =>
        Math.Clamp(1.35 - temperament * 0.035, 0.65, 1.35);
}
