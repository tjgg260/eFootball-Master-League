using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    private readonly Session _session;

    public MainWindowViewModel(Session session)
    {
        _session = session;
        ClubName = session.CurrentTeamName;
        LeagueName = session.LeagueName;

        Pages = new ObservableCollection<PageViewModel>
        {
            new DashboardViewModel(session),
            new TableViewModel(session),
            new SquadViewModel(session),
            new MarketViewModel(session),
            new FixturesViewModel(session),
            new FinancesViewModel(session),
            new InboxViewModel(session),
        };
        CurrentPage = Pages[0];
    }

    public string ClubName { get; }
    public string LeagueName { get; }

    public ObservableCollection<PageViewModel> Pages { get; }

    [ObservableProperty]
    private PageViewModel _currentPage;

    [RelayCommand]
    private void Navigate(PageViewModel page) => CurrentPage = page;
}

public abstract class PageViewModel : ObservableObject
{
    public abstract string Title { get; }
    public abstract string Icon { get; }
}
