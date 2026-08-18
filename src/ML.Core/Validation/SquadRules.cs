namespace ML.Core.Validation;

/// <summary>
/// Squad legality limits.
///
/// PLACEHOLDER VALUES. The build plan's Phase 0 says to record "roster size limits before the
/// game complains" — replace these with what eFootball actually accepts once that is measured,
/// because Phase 4 refuses to emit a CSV that breaks them and a wrong limit here either blocks
/// legal transfers or lets a corrupt squad through.
/// </summary>
public sealed record SquadRules
{
    public int MinSquadSize { get; init; } = 18;

    public int MaxSquadSize { get; init; } = 35;

    public int MinGoalkeepers { get; init; } = 2;

    public int MinSquadNumber { get; init; } = 1;

    public int MaxSquadNumber { get; init; } = 99;

    public static SquadRules Default { get; } = new();
}
