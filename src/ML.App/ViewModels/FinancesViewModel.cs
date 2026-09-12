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

    // Two-step, and priced on the button itself. Taking on debt at 5% for 34 weeks was one
    // click with no confirmation and no statement of what it costs a week — the same class of
    // action as releasing a member of staff, which has asked twice for a long time.
    [ObservableProperty] private string _borrow250Label = "Borrow £250k";
    [ObservableProperty] private string _borrow500Label = "Borrow £500k";
    [ObservableProperty] private string _borrow1000Label = "Borrow £1m";
    private long _armed;

    private static string WeeklyFor(long amount) => $"£{(long)(amount * 1.05) / 34:N0}";

    private void ResetBorrowLabels()
    {
        _armed = 0;
        Borrow250Label = "Borrow £250k";
        Borrow500Label = "Borrow £500k";
        Borrow1000Label = "Borrow £1m";
    }

    [RelayCommand]
    private void Borrow(string amount)
    {
        var value = long.Parse(amount);
        if (_armed != value)
        {
            // First press arms this one and disarms the others: the label becomes the question,
            // and the question carries the weekly cost you are agreeing to.
            ResetBorrowLabels();
            _armed = value;
            var ask = $"Confirm — {WeeklyFor(value)}/wk for 34 weeks";
            if (value == 250_000) Borrow250Label = ask;
            else if (value == 500_000) Borrow500Label = ask;
            else Borrow1000Label = ask;
            Status = $"£{value:N0} at 5% costs you {WeeklyFor(value)} every matchweek until it is " +
                     "repaid. Press again to agree, or pick a different amount.";
            HasStatus = true;
            return;
        }
        Status = _s.TakeLoan(value);
        HasStatus = Status.Length > 0;
        ResetBorrowLabels();
        Refresh();
    }
}
