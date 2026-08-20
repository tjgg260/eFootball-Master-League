namespace ML.Core.Development;

/// <summary>Who a skill is for. Gates are the hard rule at training time.</summary>
public enum SkillGate
{
    Outfield,      // any outfield position, never GK
    MidFwd,        // midfielders and forwards only (e.g. Track Back)
    Goalkeeper,    // GK only
}

/// <summary>
/// One eFootball Player Skill. Names are VERBATIM from the game's string table
/// (dt261 all.str [66105..66178]). <see cref="Innate"/> skills can NEVER be learned on the
/// training ground: flair gifts you are born with, mentality traits, and the boosted-tier
/// skills the game itself only ships on special cards.
/// </summary>
public sealed record SkillDef(string Name, SkillGate Gate, bool Innate);

public static class PlayerSkillCatalog
{
    public static readonly SkillDef[] All =
    {
        // --- dribbling technique (trainable) ---
        new("Scissors Feint", SkillGate.Outfield, false),
        new("Double Touch", SkillGate.Outfield, false),
        new("Cut Behind & Turn", SkillGate.Outfield, false),
        new("Chop Turn", SkillGate.Outfield, false),
        new("Sole Control", SkillGate.Outfield, false),
        // --- flair gifts: born with them, never coached into a player ---
        new("Flip Flap", SkillGate.Outfield, true),
        new("Marseille Turn", SkillGate.Outfield, true),
        new("Sombrero", SkillGate.Outfield, true),
        new("Scotch Move", SkillGate.Outfield, true),
        new("Heel Trick", SkillGate.Outfield, true),
        new("Rabona", SkillGate.Outfield, true),
        new("No Look Pass", SkillGate.Outfield, true),
        new("Acrobatic Finishing", SkillGate.Outfield, true),
        new("Acrobatic Clearance", SkillGate.Outfield, true),
        // --- shooting (trainable) ---
        new("Heading", SkillGate.Outfield, false),
        new("Chip Shot Control", SkillGate.Outfield, false),
        new("Long-range Shooting", SkillGate.Outfield, false),
        new("Knuckle Shot", SkillGate.Outfield, false),
        new("Dipping Shot", SkillGate.Outfield, false),
        new("Rising Shot", SkillGate.Outfield, false),
        new("First-time Shot", SkillGate.Outfield, false),
        // --- passing (trainable) ---
        new("One-touch Pass", SkillGate.Outfield, false),
        new("Through Passing", SkillGate.Outfield, false),
        new("Weighted Pass", SkillGate.Outfield, false),
        new("Pinpoint Crossing", SkillGate.Outfield, false),
        new("Outside Curler", SkillGate.Outfield, false),
        new("Low Lofted Pass", SkillGate.Outfield, false),
        // --- defending (trainable; Track Back is for players AHEAD of the back line) ---
        new("Man Marking", SkillGate.Outfield, false),
        new("Track Back", SkillGate.MidFwd, false),
        new("Interception", SkillGate.Outfield, false),
        new("Blocker", SkillGate.Outfield, false),
        new("Sliding Tackle", SkillGate.Outfield, false),
        // --- set pieces / mentality ---
        new("Penalty Specialist", SkillGate.Outfield, false),
        new("Gamesmanship", SkillGate.Outfield, true),
        new("Captaincy", SkillGate.Outfield, true),
        new("Super-sub", SkillGate.Outfield, true),
        new("Fighting Spirit", SkillGate.Outfield, true),
        // --- goalkeeper (trainable, GK only) ---
        new("GK Low Punt", SkillGate.Goalkeeper, false),
        new("GK High Punt", SkillGate.Goalkeeper, false),
        new("GK Long Throw", SkillGate.Goalkeeper, false),
        new("GK Penalty Saver", SkillGate.Goalkeeper, false),
        // --- boosted tier: the game ships these only on special cards — never learnable ---
        new("Phenomenal Finishing", SkillGate.Outfield, true),
        new("Phenomenal Pass", SkillGate.Outfield, true),
        new("Fortress", SkillGate.Outfield, true),
        new("Momentum Dribbling", SkillGate.Outfield, true),
        new("Game-changing Pass", SkillGate.Outfield, true),
        new("Visionary Pass", SkillGate.Outfield, true),
        new("Edged Crossing", SkillGate.Outfield, true),
        new("Blitz Curler", SkillGate.Outfield, true),
        new("Bullet Header", SkillGate.Outfield, true),
        new("Acceleration Burst", SkillGate.Outfield, true),
        new("Aerial Fort", SkillGate.Outfield, true),
        new("Long-reach Tackle", SkillGate.Outfield, true),
        new("Low Screamer", SkillGate.Outfield, true),
        new("Willpower", SkillGate.Outfield, true),
        new("Magnetic Feet", SkillGate.Outfield, true),
        new("GK Directing Defence", SkillGate.Goalkeeper, true),
        new("GK Spirit Roar", SkillGate.Goalkeeper, true),
    };

    private static readonly HashSet<string> MidFwdCategories = new() { "MID", "FWD" };

    /// <summary>Whether this position may ever carry the skill (gate check only).</summary>
    public static bool GateAllows(SkillDef skill, string position, string positionCategory) =>
        skill.Gate switch
        {
            SkillGate.Goalkeeper => position == "GK",
            SkillGate.MidFwd => position != "GK" && MidFwdCategories.Contains(positionCategory),
            _ => position != "GK",
        };

    /// <summary>
    /// The skills a player could take onto the training ground: gate passes, not innate,
    /// not already known.
    /// </summary>
    public static IReadOnlyList<SkillDef> LearnableFor(
        string position, string positionCategory, IReadOnlyCollection<string> known) =>
        All.Where(s => !s.Innate
                       && GateAllows(s, position, positionCategory)
                       && !known.Contains(s.Name))
           .ToList();

    public static bool IsInnate(string name) =>
        All.FirstOrDefault(s => s.Name == name)?.Innate ?? false;
}
