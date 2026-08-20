using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

/// <summary>The bank: balance, one loan at a time, weekly repayments collected each matchweek.</summary>
public sealed partial class BankViewModel : PageViewModel
{
    private readonly Session _s;

    public BankViewModel(Session s)
    {
        _s = s;
        Refresh();
    }

    private void Refresh()
    {
        Balance = $"£{_s.Finances.Balance:N0}";
        var outstanding = _s.LoanOutstanding;
        LoanLine = outstanding > 0
            ? $"Outstanding loan: £{outstanding:N0} — repaying £{_s.LoanWeekly:N0} every matchweek."
            : "No loan outstanding. The bank offers £250k, £500k or £1m at 5% over 34 weeks.";
        CanBorrow = outstanding <= 0;
    }

    public override string Title => "Bank";
    public override string Icon => "🏦";

    [ObservableProperty]
    private string _balance = "";

    [ObservableProperty]
    private string _loanLine = "";

    [ObservableProperty]
    private bool _canBorrow;

    [ObservableProperty]
    private string _status = "";

    [RelayCommand]
    private void Borrow(string amount)
    {
        Status = _s.TakeLoan(long.Parse(amount));
        Refresh();
    }
}
