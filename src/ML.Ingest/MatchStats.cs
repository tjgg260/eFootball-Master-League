namespace ML.Ingest;

/// <summary>
/// The parsed full-time stats. Every field carries the OCR confidence so the confirm screen can
/// highlight the shaky ones — the scorer list, above all, which OCR gets wrong most often.
/// </summary>
public sealed class MatchStats
{
    public OcrValue<int> HomeScore { get; set; } = OcrValue<int>.Empty;
    public OcrValue<int> AwayScore { get; set; } = OcrValue<int>.Empty;

    /// <summary>Every numeric stat read, keyed by field name (home_shots, away_fouls, …).</summary>
    public Dictionary<string, OcrValue<int>> Numbers { get; } = new();

    /// <summary>Scorer lines as read — always reviewed, never trusted blind.</summary>
    public OcrValue<string> ScorersRaw { get; set; } = OcrValue<string>.Empty;

    /// <summary>Fields the confirm screen should flag because OCR was not confident.</summary>
    public IEnumerable<string> LowConfidenceFields(double threshold = 0.80)
    {
        if (HomeScore.Confidence < threshold) yield return "home_score";
        if (AwayScore.Confidence < threshold) yield return "away_score";
        foreach (var (field, value) in Numbers)
            if (value.Confidence < threshold) yield return field;
        if (ScorersRaw.Confidence < threshold) yield return "scorers";
    }

    public string ToStatsJson()
    {
        var pairs = Numbers.Select(kv => $"\"{kv.Key}\":{kv.Value.Value}");
        return "{" + string.Join(",", pairs) + "}";
    }
}

public readonly record struct OcrValue<T>(T Value, double Confidence)
{
    public static OcrValue<T> Empty => new(default!, 0.0);
    public bool IsConfident(double threshold = 0.80) => Confidence >= threshold;
}
