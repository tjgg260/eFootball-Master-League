using ML.Core.Domain;

namespace ML.Core.Tables;

public sealed record LeagueTableRow
{
    public required TeamId TeamId { get; init; }

    /// <summary>1-based finishing position once the table has been ordered.</summary>
    public required int Position { get; init; }

    public required int Played { get; init; }

    public required int Won { get; init; }

    public required int Drawn { get; init; }

    public required int Lost { get; init; }

    public required int GoalsFor { get; init; }

    public required int GoalsAgainst { get; init; }

    public int GoalDifference => GoalsFor - GoalsAgainst;

    public int Points => (Won * PointsForWin) + Drawn;

    public const int PointsForWin = 3;

    public override string ToString() =>
        $"{Position}. {TeamId} — P{Played} W{Won} D{Drawn} L{Lost} " +
        $"{GoalsFor}:{GoalsAgainst} GD{GoalDifference:+#;-#;0} {Points}pts";
}
