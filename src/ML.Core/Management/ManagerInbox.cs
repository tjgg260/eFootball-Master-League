namespace ML.Core.Management;

public enum MessageCategory
{
    Board,
    Player,
    Media,
    Transfer,
}

public sealed record ManagerMessage(
    MessageCategory Category,
    string Subject,
    string Body,
    bool RequiresAction = false);

/// <summary>
/// Generates the reactive manager inbox MFL is built around — board reactions to results and
/// confidence, player unrest when morale bottoms out. Pure: given state, it returns the messages
/// that state would produce, so the app can persist and display them and tests can assert them.
/// </summary>
public static class ManagerInbox
{
    public static IReadOnlyList<ManagerMessage> AfterResult(
        string opponent,
        int goalsFor,
        int goalsAgainst,
        BoardConfidence board,
        Morale morale)
    {
        var messages = new List<ManagerMessage>();

        if (board.ManagerUnderThreat)
        {
            messages.Add(new ManagerMessage(
                MessageCategory.Board,
                "The board's patience is wearing thin",
                "Results have fallen short of expectations. The board expects an immediate improvement.",
                RequiresAction: true));
        }
        else if (goalsFor > goalsAgainst && board.Value >= 75)
        {
            messages.Add(new ManagerMessage(
                MessageCategory.Board,
                "The board is delighted",
                $"A fine win over {opponent}. Keep it up."));
        }

        if (morale.Value <= 20)
        {
            messages.Add(new ManagerMessage(
                MessageCategory.Player,
                "The dressing room is unsettled",
                "Morale has hit the floor after a poor run. The squad needs a lift.",
                RequiresAction: true));
        }

        if (Math.Abs(goalsFor - goalsAgainst) >= 3)
        {
            var heavy = goalsFor > goalsAgainst ? "thrashing" : "hammering";
            messages.Add(new ManagerMessage(
                MessageCategory.Media,
                $"Press reacts to the {heavy}",
                $"The result against {opponent} is the talk of the division."));
        }

        return messages;
    }
}
