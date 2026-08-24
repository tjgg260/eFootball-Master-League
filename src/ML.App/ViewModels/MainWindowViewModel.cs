using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    private readonly Session _session;
    private readonly NavItem _newsItem;

    public MainWindowViewModel(Session session)
    {
        _session = session;
        ClubName = session.CurrentTeamName;
        LeagueName = session.LeagueName;
        Crest = Visuals.LoadBitmap(session.LogoPath);

        // Nav items build their page fresh on click, so screens always reflect the latest DB state
        // (table, form, finances after you record a result and the matchday is simmed).
        // Icons are Segoe MDL2 Assets glyphs — monochrome, tinted by the nav styles.
        Pages = new ObservableCollection<NavItem>
        {
            // MATCHDAY
            new("Office",   "\uE80F", s => new DashboardViewModel(s)),
            new("Tactics",  "\uE8A9", s => new TacticsViewModel(s)),
            new("Calendar", "\uE787", s => new CalendarViewModel(s)),
            // CLUB
            new("Squad",    "\uE716", s => new SquadViewModel(s)),
            new("Training", "\uE945", s => new TrainingViewModel(s)),
            new("Academy",  "\uE8F1", s => new AcademyViewModel(s)),
            new("Staff",    "\uE77B", s => new StaffViewModel(s)),
            new("Board",    "\uE825", s => new BoardViewModel(s)),
            new("Finances", "\uE8EF", s => new FinancesViewModel(s)),
            // COMPETITION
            new("Table",    "\uE8FD", s => new TableViewModel(s)),
            new("Cup",      "\uE735", s => new CupViewModel(s)),
            new("Stats",    "\uE9E9", s => new StatsViewModel(s)),
            new("History",  "\uE736", s => new HistoryViewModel(s)),
            // WORLD
            new("Market",   "\uE8AB", s => new MarketViewModel(s)),
            new("Scouting", "\uE721", s => new ScoutingViewModel(s)),
            new("News",     "\uE715", s => new InboxViewModel(s)),
            // pinned at the foot of the sidebar, outside the section scroll
            new("Settings", "\uE713", s => new SettingsViewModel(s)),
        };

        NavItem P(string title) => Pages.First(p => p.Title == title);
        Sections = new List<NavSection>
        {
            new("MATCHDAY",    new[] { P("Office"), P("Tactics"), P("Calendar") }),
            new("CLUB",        new[] { P("Squad"), P("Training"), P("Academy"), P("Staff"), P("Board"), P("Finances") }),
            new("COMPETITION", new[] { P("Table"), P("Cup"), P("Stats"), P("History") }),
            new("WORLD",       new[] { P("Market"), P("Scouting"), P("News") }),
        };
        SettingsItem = P("Settings");
        _newsItem = P("News");

        RefreshShell();

        // Cross-screen navigation with a subject: any page raises Nav.Go("Squad", player)
        // and lands here. Single-handler assignment so a full-window rebuild (job accepted)
        // replaces the old shell instead of stacking subscribers.
        Nav.Handler = OnNavRequest;

        // Tooling hook: ML_PAGE=<nav title> opens straight onto that screen (screenshot runs).
        var startPage = Environment.GetEnvironmentVariable("ML_PAGE");
        var start = Pages.FirstOrDefault(p => p.Title == startPage) ?? Pages[0];
        CurrentPage = start.Build(session);
        MarkActive(start);
    }

    private void OnNavRequest(string pageTitle, EntityRef? focus)
    {
        var item = Pages.FirstOrDefault(p => p.Title == pageTitle);
        if (item is null) return;
        // The shared context menu offers "View profile" and "Set training" beside "Swap with X",
        // so this path is the easiest way to walk out on unsaved work — it must be guarded too.
        if (!ClearToLeave(() => GoTo(item, focus))) return;
        GoTo(item, focus);
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
            UnreadBadge = unread > 0 ? $"{unread} unread" : "";
            _newsItem.BadgeCount = unread;   // pill on the News nav row
        }
        catch { HasUnread = false; }
        try
        {
            // Each pending decision knows the screen that resolves it — the sidebar line
            // is buttons, not prose (P9: the shell used to warn and make you hunt).
            Alerts.Clear();
            if (_session.PendingOffers().Count > 0) Alerts.Add(new ActionAlert("⚠ offers on the table", "Market"));
            if (_session.IsDeadlineDay()) Alerts.Add(new ActionAlert("⚠ DEADLINE DAY", "Market"));
            if (_session.JobOffers().Count > 0) Alerts.Add(new ActionAlert("⚠ a job offer", "Board"));
            HasActions = Alerts.Count > 0;
            ActionsLine = "";
        }
        catch { HasActions = false; }
    }

    public ObservableCollection<NavItem> Pages { get; }

    // Pending decisions rendered as sidebar buttons; each names the page that resolves it.
    public ObservableCollection<ActionAlert> Alerts { get; } = new();

    [RelayCommand]
    private void OpenAlert(ActionAlert alert) => OnNavRequest(alert.Page, null);

    // The sidebar renders these; every NavItem inside is the same instance as in Pages,
    // so MarkActive/ML_PAGE keep working untouched.
    public IReadOnlyList<NavSection> Sections { get; }
    public NavItem SettingsItem { get; }

    [ObservableProperty]
    private PageViewModel _currentPage;

    [RelayCommand]
    private void Navigate(NavItem item)
    {
        if (!ClearToLeave(() => GoTo(item, null))) return;
        GoTo(item, null);
    }

    private void GoTo(NavItem item, EntityRef? focus)
    {
        try
        {
            var page = item.Build(_session);
            if (focus is not null && page is IFocusTarget f) f.Focus(focus);
            CurrentPage = page;
            MarkActive(item);
            RefreshShell();   // badges follow you around the app
        }
        catch (Exception ex)
        {
            // A page that fails to build must not take the whole app down — log it and stay put.
            Program.Log($"Navigate -> {item.Title}", ex);
        }
    }

    // ---- the unsaved-work guard -------------------------------------------------
    // Pages are rebuilt from the DB on every nav click, so leaving a page with unsaved
    // edits destroyed them silently. Any page that can hold unsaved work says so through
    // PageViewModel.IsDirty and the shell asks before it throws the work away.

    [ObservableProperty] private bool _leaveArmed;
    [ObservableProperty] private string _leavePrompt = "";
    private Action? _pendingLeave;

    /// <summary>True when it is safe to leave now. False parks the trip until the user answers.</summary>
    private bool ClearToLeave(Action resume)
    {
        if (CurrentPage is not { IsDirty: true } dirty) { DismissLeave(); return true; }
        _pendingLeave = resume;
        LeavePrompt = dirty.DirtySummary is { Length: > 0 } s
            ? $"⚠ {s} — leaving loses it."
            : "⚠ Unsaved changes — leaving loses them.";
        LeaveArmed = true;
        return false;
    }

    [RelayCommand]
    private void SaveAndLeave()
    {
        (CurrentPage as ISaveablePage)?.SaveNow();
        var go = _pendingLeave;
        DismissLeave();
        go?.Invoke();
    }

    [RelayCommand]
    private void DiscardAndLeave()
    {
        // The resume is GoTo, which does not re-check — the user has answered, so it just goes.
        var go = _pendingLeave;
        DismissLeave();
        go?.Invoke();
    }

    [RelayCommand]
    private void DismissLeave()
    {
        LeaveArmed = false;
        LeavePrompt = "";
        _pendingLeave = null;
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

/// <summary>A pending decision surfaced in the sidebar; Page is the screen that resolves it.</summary>
public sealed record ActionAlert(string Text, string Page);

/// <summary>A labeled group of nav rows ("MATCHDAY", "CLUB", ...).</summary>
public sealed class NavSection
{
    public NavSection(string header, IReadOnlyList<NavItem> items)
    {
        Header = header;
        Items = items;
    }

    public string Header { get; }
    public IReadOnlyList<NavItem> Items { get; }
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

    // Unread pill on the News row (0 = hidden).
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasBadge))]
    private int _badgeCount;
    public bool HasBadge => BadgeCount > 0;
}

public abstract class PageViewModel : ObservableObject
{
    public abstract string Title { get; }
    public abstract string Icon { get; }

    /// <summary>
    /// True while the page holds edits that only exist in memory. The shell asks before it
    /// rebuilds the page (which is how unsaved work used to disappear without a word).
    /// Set by the page; cleared by its own save.
    /// </summary>
    public virtual bool IsDirty => false;

    /// <summary>What would be lost, in words — "3 unsaved changes", "an unsaved formation".</summary>
    public virtual string DirtySummary => "";

}

/// <summary>A page whose unsaved work the shell can commit on the user's behalf.</summary>
public interface ISaveablePage
{
    void SaveNow();
}
