using ML.Core.Domain;

namespace ML.Core.Scheduling;

public sealed class Fixture
{
    public Fixture(int id, int matchday, TeamId homeTeam, TeamId awayTeam)
    {
        if (matchday < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(matchday), matchday, "Matchdays are 1-based.");
        }

        if (homeTeam == awayTeam)
        {
            throw new ArgumentException("A team cannot play itself.", nameof(awayTeam));
        }

        Id = id;
        Matchday = matchday;
        HomeTeam = homeTeam;
        AwayTeam = awayTeam;
    }

    public int Id { get; }

    public int Matchday { get; }

    public TeamId HomeTeam { get; }

    public TeamId AwayTeam { get; }

    public MatchResult? Result { get; private set; }

    public bool IsPlayed => Result.HasValue;

    public bool Involves(TeamId teamId) => HomeTeam == teamId || AwayTeam == teamId;

    public TeamId OpponentOf(TeamId teamId) =>
        teamId == HomeTeam ? AwayTeam
        : teamId == AwayTeam ? HomeTeam
        : throw new ArgumentException($"Team {teamId} is not in fixture {Id}.", nameof(teamId));

    public void RecordResult(MatchResult result)
    {
        if (IsPlayed)
        {
            throw new InvalidOperationException(
                $"Fixture {Id} already has a result ({Result}). Clear it first if you are correcting it.");
        }

        Result = result;
    }

    /// <summary>
    /// Wipes the result so it can be re-entered — the Phase 3 confirm screen needs this when
    /// the user corrects an OCR misread after the fact.
    /// </summary>
    public void ClearResult() => Result = null;

    public override string ToString() =>
        $"MD{Matchday}: {HomeTeam} v {AwayTeam}" + (IsPlayed ? $" ({Result})" : string.Empty);
}
