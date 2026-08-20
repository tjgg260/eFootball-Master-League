namespace ML.Core.Selection;

/// <summary>
/// The scout's counter-plan (FM phase C3): given the opponent's playstyle, a suggested answer.
/// HONEST BOUNDARY: these suggestions configure YOUR pre-match compile only — the opponent's
/// in-game AI is Konami's and stays untouched.
/// </summary>
public static class OppositionBriefing
{
    /// <summary>Counter suggestion per opponent style byte (0–5).</summary>
    public static (string Shape, string Style, string Line) Counter(int oppStyleIndex) =>
        oppStyleIndex switch
        {
            0 => ("4-2-3-1", "Quick Counter",
                "They'll pass you to sleep — stay compact in a 4-2-3-1, then break the moment it turns over."),
            1 => ("4-3-3", "Possession Game",
                "They live for the counter — deny them the transition. Keep the ball, keep the full-backs honest."),
            2 => ("4-3-3", "Possession Game",
                "They sit deep and launch it — a patient 4-3-3 starves the outlet, with the DMF sweeping seconds."),
            3 => ("4-2-3-1", "Possession Game",
                "Long balls all night — win the seconds with a double pivot and make them chase yours."),
            4 => ("3-5-2", "Long Ball Counter",
                "Everything comes from their flanks — three centre-backs eat crosses, wing-backs pin their wide men."),
            _ => ("4-2-3-1", "Long Ball Counter",
                "They'll commit everyone — stay compact, absorb, and hit the space they leave behind."),
        };
}
