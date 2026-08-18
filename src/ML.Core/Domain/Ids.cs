namespace ML.Core.Domain;

/// <summary>
/// The game's PID. This is the key everything hangs off — see the build plan.
/// </summary>
public readonly record struct PlayerId(int Value)
{
    public override string ToString() => Value.ToString();
}

public readonly record struct TeamId(int Value)
{
    public override string ToString() => Value.ToString();
}

public readonly record struct LeagueId(int Value)
{
    public override string ToString() => Value.ToString();
}
