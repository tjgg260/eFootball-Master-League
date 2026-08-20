namespace ML.Core.Selection;

public enum TalkTone
{
    Calm,
    Encourage,
    Demand,
}

/// <summary>
/// Team talks (FM phase C2), pure and deterministic. The right tone depends on the moment:
/// demanding more works on confident favourites and backfires on a nervous dressing room;
/// calm words never hurt but rarely inspire; encouragement is the safe middle. Effects are
/// bounded — a talk shades a matchday, it doesn't win one.
/// </summary>
public static class TeamTalk
{
    /// <summary>
    /// Pre-match: favourites = your ELO is higher. Returns squad-wide morale delta, a small
    /// form nudge, and the dressing-room reaction line.
    /// </summary>
    public static (int MoraleDelta, double FormDelta, string Reaction) PreMatch(
        TalkTone tone, bool favourites, int squadMorale) => tone switch
    {
        TalkTone.Calm => (1, 0.1, "Heads nod. Focused, no nerves."),
        TalkTone.Encourage => squadMorale >= 35
            ? (2, 0.2, "The room lifts — they believe.")
            : (1, 0.1, "A few tired smiles. It helps, a little."),
        _ => favourites && squadMorale >= 55
            ? (3, 0.3, "Jaws set. They know the standard expected — and they're up for it.")
            : (-3, -0.2, "Too much. Shoulders drop; the room wasn't ready to be shouted at."),
    };

    /// <summary>Post-match: outcome 1 win / 0 draw / -1 loss.</summary>
    public static (int MoraleDelta, double FormDelta, string Reaction) PostMatch(
        TalkTone tone, int outcome, int squadMorale) => (tone, outcome) switch
    {
        (TalkTone.Encourage, 1) => (3, 0.2, "Deserved praise, well received."),
        (TalkTone.Encourage, _) => (2, 0.1, "You backed them despite the result — remembered."),
        (TalkTone.Calm, _) => (1, 0.1, "Level heads. On to the next one."),
        (TalkTone.Demand, 1) => (0, 0.0, "A win and still a lecture — a few rolled eyes."),
        (TalkTone.Demand, _) => squadMorale >= 55
            ? (4, 0.3, "The hairdryer lands — they're stung, and they'll respond.")
            : (-4, -0.3, "The hairdryer on a fragile room. That one will fester."),
    };

    /// <summary>The assistant's read on which tone fits the moment.</summary>
    public static TalkTone Hint(bool preMatch, bool favourites, int outcome, int squadMorale)
    {
        if (preMatch)
        {
            return favourites && squadMorale >= 55 ? TalkTone.Demand
                : squadMorale >= 35 ? TalkTone.Encourage : TalkTone.Calm;
        }
        return outcome == 1 ? TalkTone.Encourage
            : squadMorale >= 55 ? TalkTone.Demand : TalkTone.Calm;
    }
}
