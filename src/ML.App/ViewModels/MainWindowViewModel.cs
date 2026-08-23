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
        Crest = Visuals.LoadBitmap(session.LogoPath);
        RefreshShell();

        // Nav items build their page fresh on click, so screens always reflect the latest DB state
        // (table, form, finances after you record a result and the matchday is simmed).
        Pages = new ObservableCollection<NavItem>
        {
            new("Office", "🏠", s => new DashboardViewModel(s)),
            new("Table", "📊", s => new TableViewModel(s)),
            new("Squad", "👥", s => new SquadViewModel(s)),
            new("Market", "🔁", s => new MarketViewModel(s)),
            new("Cup", "🏆", s => new CupViewModel(s)),
            new("Academy", "🎓", s => new AcademyViewModel(s)),
            new("Calendar", "📆", s => new CalendarViewModel(s)),
            new("Tactics", "♟️", s => new TacticsViewModel(s)),
            new("Board", "🏛️", s => new BoardViewModel(s)),
            new("Training", "🎯", s => new TrainingViewModel(s)),
            new("Staff", "🧑‍💼", s => new StaffViewModel(s)),
            new("Scouting", "🔍", s => new ScoutingViewModel(s)),
            new("Stats", "📈", s => new StatsViewModel(s)),
            new("History", "📜", s => new HistoryViewModel(s)),
            new("Finances", "💷", s => new FinancesViewModel(s)),
            new("News", "📰", s => new InboxViewModel(s)),
            new("Settings", "⚙️", s => new SettingsViewModel(s)),
        };
        // Tooling hook: ML_PAGE=<nav title> opens straight onto that screen (screenshot runs).
        var startPage = Environment.GetEnvironmentVariable("ML_PAGE");
        var start = Pages.FirstOrDefault(p => p.Title == startPage) ?? Pages[0];
        CurrentPage = start.Build(session);
        MarkActive(start);
    }

    public string ClubName { get; }
    public string LeagueName { get; }
    public Avalonia.Media.Imaging.Bitmap? Crest { get; }
    public bool HasCrest => Crest is not null;

    // Shell awareness (P6): the sidebar knows the date, your mail and your pending decisions.
    [ObservableProperty] private string _dateLine = "";
    [ObservableProperty] private string _unreadBadge = "";
    [ObservableProperty] private bool _hasUnread;
    [ObservableProperty] private string _actionsLine = "";
    [ObservableProperty] private bool _hasActions;

    private void RefreshShell()
    {
        try
        {
            var next = _session.NextFixture();
            DateLine = next is null
                ? $"Season {_session.SeasonYear}/{(_session.SeasonYear + 1) % 100:00} complete"
                : $"{ML.Core.Scheduling.SeasonCalendar.Label(_session.DateOfFixture(next))} · MD {next.Matchday}";
        }
        catch { DateLine = ""; }
        try
        {
            var unread = _session.UnreadCount();
            HasUnread = unread > 0;
            UnreadBadge = unread > 0 ? $"📰 {unread} unread" : "";
        }
        catch { HasUnread = false; }
        try
        {
            var actions = new List<string>();
            if (_session.PendingOffers().Count > 0) actions.Add("offers on the table");
            if (_session.IsDeadlineDay()) actions.Add("DEADLINE DAY");
            if (_session.JobOffers().Count > 0) actions.Add("a job offer");
            HasActions = actions.Count > 0;
            ActionsLine = actions.Count > 0 ? "⚠ " + string.Join(" · ", actions) : "";
        }
        catch { HasActions = false; }
    }

    public ObservableCollection<NavItem> Pages { get; }

    [ObservableProperty]
    private PageViewModel _currentPage;

    [RelayCommand]
    private void Navigate(NavItem item)
    {
        try
        {
            CurrentPage = item.Build(_session);
            MarkActive(item);
            RefreshShell();   // badges follow you around the app
        }
        catch (Exception ex)
        {
            // A page that fails to build must not take the whole app down — log it and stay put.
            Program.Log($"Navigate -> {item.Title}", ex);
        }
    }

    [RelayCommand]
    private void ContinueToOffice()
    {
        CurrentPage = Pages[0].Build(_session);
        MarkActive(Pages[0]);
        RefreshShell();
    }

    private void MarkActive(NavItem current)
    {
        foreach (var p in Pages) p.IsActive = p == current;
    }
}

public sealed partial class NavItem : ObservableObject
{
    private readonly Func<Session, PageViewModel> _build;

    public NavItem(string title, string icon, Func<Session, PageViewModel> build)
    {
        Title = title;
        Icon = icon;
        _build = build;
    }

    public string Title { get; }
    public string Icon { get; }
    public PageViewModel Build(Session s) => _build(s);

    // The sidebar highlights the page you are on.
    [ObservableProperty] private bool _isActive;
}

public abstract class PageViewModel : ObservableObject
{
    public abstract string Title { get; }
    public abstract string Icon { get; }
}
