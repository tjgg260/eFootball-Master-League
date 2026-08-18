namespace ML.Core.Domain;

/// <summary>
/// A club. The squad is not held here — <see cref="Player.TeamId"/> is authoritative and
/// <see cref="World.SquadOf"/> indexes it. Two lists of the same fact is how squads desync.
/// </summary>
public sealed class Team
{
    public Team(TeamId id, string name, LeagueId leagueId, long budget = 0)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new ArgumentException("Team name is required.", nameof(name));
        }

        if (budget < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(budget), budget, "Budget cannot start negative.");
        }

        Id = id;
        Name = name;
        LeagueId = leagueId;
        Budget = budget;
    }

    public TeamId Id { get; }

    public string Name { get; }

    public LeagueId LeagueId { get; private set; }

    public long Budget { get; private set; }

    public void Credit(long amount)
    {
        if (amount < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(amount), amount, "Use Debit for outgoings.");
        }

        Budget += amount;
    }

    public bool CanAfford(long amount) => amount <= Budget;

    /// <summary>Spends <paramref name="amount"/>, or throws if the club cannot cover it.</summary>
    public void Debit(long amount)
    {
        if (amount < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(amount), amount, "Use Credit for income.");
        }

        if (amount > Budget)
        {
            throw new InsufficientFundsException(this, amount);
        }

        Budget -= amount;
    }

    /// <summary>
    /// Spends as much of <paramref name="amount"/> as the club can and returns the shortfall.
    /// Budgets floor at zero by construction — the engine never carries a negative balance.
    /// </summary>
    public long DebitUpTo(long amount)
    {
        if (amount < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(amount), amount, "Use Credit for income.");
        }

        var paid = Math.Min(amount, Budget);
        Budget -= paid;
        return amount - paid;
    }

    public void MoveToLeague(LeagueId leagueId) => LeagueId = leagueId;

    public override string ToString() => Name;
}

public sealed class InsufficientFundsException : InvalidOperationException
{
    public InsufficientFundsException(Team team, long attempted)
        : base($"{team.Name} cannot spend {attempted:N0} — budget is {team.Budget:N0}.")
    {
        TeamId = team.Id;
        Attempted = attempted;
        Available = team.Budget;
    }

    public TeamId TeamId { get; }

    public long Attempted { get; }

    public long Available { get; }
}
