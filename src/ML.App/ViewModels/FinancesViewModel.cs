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

        // The money line over time (item 11): every weekly pass leaves a snapshot behind.
        try
        {
            var series = s.ClubHistorySeries("balance");
            if (series.Count >= 3)
            {
                const double w = 640, h = 96;
                long lo = series.Min(), hi = Math.Max(series.Max(), lo + 1);
                var step = w / (series.Count - 1);
                for (var i = 0; i < series.Count; i++)
                {
                    var y = h - 6 - (series[i] - lo) / (double)(hi - lo) * (h - 12);
                    BalancePoints.Add(new Avalonia.Point(i * step, y));
                }
                TrendVisible = true;
                TrendLabel = $"Bank balance over {series.Count} matchweeks — " +
                             $"peak £{hi:N0}, low £{lo:N0}";
            }
        }
        catch { TrendVisible = false; }
    }

    public Avalonia.Points BalancePoints { get; } = new();
    public bool TrendVisible { get; }
    public string TrendLabel { get; } = "";

    public override string Title => "Finances";
    public override string Icon => "💷";
    public string Balance { get; }
    public string SeasonIncome { get; }
    public string SeasonExpenditure { get; }
    public string WageBill { get; }
    public bool InTheRed { get; }
}
