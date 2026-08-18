namespace ML.Core.Seasons;

public sealed record RolloverSettings
{
    // --- Ageing -----------------------------------------------------------------
    public int PeakAgeStart { get; init; } = 24;

    public int PeakAgeEnd { get; init; } = 29;

    public int MaxYouthGain { get; init; } = 3;

    public int MaxVeteranLoss { get; init; } = 4;

    // --- Contracts --------------------------------------------------------------

    /// <summary>
    /// Placeholder policy until Phase 5 brings real negotiation: a club keeps an expiring
    /// player if it can cover the wage, and lets them go if it cannot.
    /// </summary>
    public bool AutoRenewAffordableContracts { get; init; } = true;

    public int ContractLengthYears { get; init; } = 3;

    // --- Finances ---------------------------------------------------------------

    /// <summary>Prize for winning the top flight. Halves for each tier below.</summary>
    public long TopFlightWinnersPrize { get; init; } = 60_000_000;

    /// <summary>Deducted per place below first.</summary>
    public long PrizeStepPerPlace { get; init; } = 2_000_000;

    public long MinimumPrize { get; init; } = 4_000_000;

    public static RolloverSettings Default { get; } = new();
}
