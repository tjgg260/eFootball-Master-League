using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Finances (the Bank folded in: the Financing card lives here now, P6) ---------

public sealed partial class FinancesViewModel : PageViewModel
{
    private readonly Session _s;

    public FinancesViewModel(Session s)
    {
        _s = s;

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

        Refresh();
    }

    /// <summary>Everything a loan can move: tiles, ledger, and the financing card.</summary>
    private void Refresh()
    {
        Balance = $"£{_s.Finances.Balance:N0}";
        SeasonIncome = $"£{_s.Finances.SeasonIncome:N0}";
        SeasonExpenditure = $"£{_s.Finances.SeasonExpenditure:N0}";
        // ONE wage-bill truth: the same contracts+staff number the weekly debit uses (P0) —
        // this screen used to show a different formula from the Office header.
        var (_, _, weeklyWages) = _s.FinancialOverview();
        WageBill = $"£{weeklyWages:N0} / wk";
        InTheRed = _s.Finances.InTheRed;

        var net = _s.Finances.SeasonIncome - _s.Finances.SeasonExpenditure;
        NetNegative = net < 0;
        NetLine = net < 0 ? $"−£{-net:N0}" : $"+£{net:N0}";

        // Financing is its own ledger line (P6): borrowed cash is not income.
        FinancingIn = $"£{_s.SeasonLoanIn:N0}";

        var outstanding = _s.LoanOutstanding;
        LoanLine = outstanding > 0
            ? $"Outstanding loan: £{outstanding:N0} — repaying £{_s.LoanWeekly:N0} every matchweek."
            : "No loan outstanding. The bank offers £250k, £500k or £1m at 5% over 34 weeks.";
        CanBorrow = outstanding <= 0;
    }

    public override string Title => "Finances";
    public override string Icon => "💷";

    public Avalonia.Points BalancePoints { get; } = new();
    public bool TrendVisible { get; }
    public string TrendLabel { get; } = "";

    [ObservableProperty] private string _balance = "";
    [ObservableProperty] private string _seasonIncome = "";
    [ObservableProperty] private string _seasonExpenditure = "";
    [ObservableProperty] private string _wageBill = "";
    [ObservableProperty] private bool _inTheRed;
    [ObservableProperty] private string _netLine = "";
    [ObservableProperty] private bool _netNegative;
    [ObservableProperty] private string _financingIn = "";
    [ObservableProperty] private string _loanLine = "";
    [ObservableProperty] private bool _canBorrow;
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private bool _hasStatus;

    [RelayCommand]
    private void Borrow(string amount)
    {
        Status = _s.TakeLoan(long.Parse(amount));
        HasStatus = Status.Length > 0;
        Refresh();
    }
}
