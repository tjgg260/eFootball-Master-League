namespace ML.Core.Selection;

/// <summary>
/// Per-player morale (FM phase B1). Pure and deterministic: starters feel valued, benched
/// players want minutes, results move the whole dressing room, and being transfer-listed
/// stings. Values live 10–95 around a neutral 50, with a gentle drift back toward neutral so
/// grudges and euphoria both fade.
/// </summary>
public static class MoraleModel
{
    public const int Neutral = 50;
    public const int Min = 10;
    public const int Max = 95;

    /// <summary>Morale below this, sustained, triggers a transfer request.</summary>
    public const int RequestThreshold = 20;

    /// <summary>
    /// One matchday's effect. outcome: 1 win / 0 draw / -1 loss (null = didn't play a match).
    /// </summary>
    public static int AfterMatchday(int current, bool started, int? outcome, bool transferListed)
    {
        var value = (double)current;
        value += (Neutral - value) * 0.06;           // grudges and euphoria both fade
        if (outcome is { } o)
        {
            value += o switch { 1 => 3, 0 => 1, _ => -2 };
            value += started ? 2 : -1;               // minutes matter more than anything
        }
        if (transferListed) value -= 2;
        return Math.Clamp((int)Math.Round(value), Min, Max);
    }

    /// <summary>Morale's pull on matchday selection: up to ±1.8 on the form term.</summary>
    public static double FormAdjustment(int morale) => (morale - Neutral) / 25.0;

    public const int TalkEffect = 4;        // a word from the manager, either way
    public const int PromiseKept = 8;       // delivered on your word
    public const int PromiseBroken = 15;    // your word turned out worthless

    /// <summary>A private word after the match: bounded either way (praise or criticism).</summary>
    public static int AfterTalk(int current, bool praise) =>
        Math.Clamp(current + (praise ? TalkEffect : -TalkEffect), Min, Max);

    /// <summary>Settling a promise at its deadline.</summary>
    public static int AfterPromise(int current, bool kept) =>
        Math.Clamp(current + (kept ? PromiseKept : -PromiseBroken), Min, Max);

    /// <summary>MFL-style label for the UI.</summary>
    public static string Label(int morale) => morale switch
    {
        >= 75 => "Delighted",
        >= 60 => "Happy",
        >= 40 => "Content",
        >= 25 => "Unsettled",
        _ => "Wants out",
    };
}
