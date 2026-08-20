namespace ML.App.ViewModels;

// --- Finances ---------------------------------------------------------------------

public sealed class FinancesViewModel : PageViewModel
{
    public FinancesViewModel(Session s)
    {
        Balance = $"£{s.Finances.Balance:N0}";
        SeasonIncome = $"£{s.Finances.SeasonIncome:N0}";
        SeasonExpenditure = $"£{s.Finances.SeasonExpenditure:N0}";
        // ONE wage-bill truth: the same contracts+staff number the weekly debit uses (P0) —
        // this screen used to show a different formula from the Office header.
        var (_, _, weeklyWages) = s.FinancialOverview();
        WageBill = $"£{weeklyWages:N0} / wk";
        InTheRed = s.Finances.InTheRed;
    }

    public override string Title => "Finances";
    public override string Icon => "💷";
    public string Balance { get; }
    public string SeasonIncome { get; }
    public string SeasonExpenditure { get; }
    public string WageBill { get; }
    public bool InTheRed { get; }
}
