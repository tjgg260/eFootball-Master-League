namespace ML.Core.Domain;

/// <summary>
/// A player. Club membership is deliberately not settable from here — go through
/// <see cref="World"/> so the squad index and the player's own team can never disagree.
/// </summary>
public sealed class Player
{
    public const int MinRating = 40;
    public const int MaxRating = 99;
    public const int MinAge = 15;
    public const int MaxAge = 50;

    public Player(
        PlayerId id,
        string name,
        Position position,
        int age,
        int overallRating,
        int weeklyWage = 0,
        int contractExpiresSeason = 0)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new ArgumentException("Player name is required.", nameof(name));
        }

        if (age is < MinAge or > MaxAge)
        {
            throw new ArgumentOutOfRangeException(
                nameof(age), age, $"Age must be between {MinAge} and {MaxAge}.");
        }

        if (overallRating is < MinRating or > MaxRating)
        {
            throw new ArgumentOutOfRangeException(
                nameof(overallRating), overallRating,
                $"Rating must be between {MinRating} and {MaxRating}.");
        }

        if (weeklyWage < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(weeklyWage), weeklyWage, "Wage cannot be negative.");
        }

        Id = id;
        Name = name;
        Position = position;
        Age = age;
        OverallRating = overallRating;
        WeeklyWage = weeklyWage;
        ContractExpiresSeason = contractExpiresSeason;
    }

    public PlayerId Id { get; }

    public string Name { get; }

    public Position Position { get; }

    public int Age { get; private set; }

    public int OverallRating { get; private set; }

    public TeamId? TeamId { get; private set; }

    public int? SquadNumber { get; private set; }

    public int WeeklyWage { get; private set; }

    /// <summary>The season id after which this contract has expired.</summary>
    public int ContractExpiresSeason { get; private set; }

    public bool IsFreeAgent => TeamId is null;

    public int AnnualWage => WeeklyWage * 52;

    internal void AssignTo(TeamId teamId, int squadNumber)
    {
        if (squadNumber is < 1 or > 99)
        {
            throw new ArgumentOutOfRangeException(
                nameof(squadNumber), squadNumber, "Squad numbers run 1-99.");
        }

        TeamId = teamId;
        SquadNumber = squadNumber;
    }

    internal void Release()
    {
        TeamId = null;
        SquadNumber = null;
    }

    public void AdvanceAge()
    {
        if (Age < MaxAge)
        {
            Age++;
        }
    }

    public void AdjustRating(int delta)
    {
        OverallRating = Math.Clamp(OverallRating + delta, MinRating, MaxRating);
    }

    public void SignContract(int expiresSeason, int weeklyWage)
    {
        if (weeklyWage < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(weeklyWage), weeklyWage, "Wage cannot be negative.");
        }

        ContractExpiresSeason = expiresSeason;
        WeeklyWage = weeklyWage;
    }

    public bool ContractHasExpired(int completedSeasonId) => ContractExpiresSeason <= completedSeasonId;

    public override string ToString() => $"{Name} ({Position}, {Age}, {OverallRating})";
}
