using System.Collections.ObjectModel;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Core.Scheduling;

namespace ML.App.ViewModels;

// --- Calendar (FM-style month grid over real season dates) ------------------------

/// <summary>
/// One square of the month grid. It carries its identity, not just its sentence: the fixture it
/// belongs to, who the opponent is (so right-click can offer the club menu), and — for event days
/// — the page title that day is really about (window → Market, intake → Academy, review → Board).
/// </summary>
public sealed record DayCell(string DayText, string Line1, string Line2, IBrush Bg, IBrush Fg,
    Avalonia.Media.Imaging.Bitmap? Crest = null, IBrush? Ring = null,
    int FixtureId = 0, int OppTeamId = 0, string OppName = "", string? EventTarget = null);

/// <summary>The season on a real calendar: league Saturdays, cup Wednesdays, Aug → May.</summary>
public sealed partial class CalendarViewModel : PageViewModel
{
    private static readonly IBrush Blank = Visuals.Brush("#151A21");
    private static readonly IBrush DayBg = Visuals.Brush("#1B222C");
    private static readonly IBrush MineBg = Visuals.Brush("#14351F");
    private static readonly IBrush PlayedBg = Visuals.Brush("#232B36");
    // Event-only days (window opens/closes, intake, breaks): a subtle MlWarn-tinted ground,
    // distinct from the green fixture tint.
    private static readonly IBrush EventBg = Visuals.Brush("#2C2410");
    // The next-fixture ring — MlPrimary (#2D7DD2 in the token sheet).
    private static readonly IBrush FocusRing = Visuals.Brush("#2D7DD2");
    private static readonly IBrush Fg = Visuals.Brush("#C7CEDA");
    private static readonly IBrush Dim = Visuals.Brush("#5E6774");

    private readonly Session _s;
    private readonly Dictionary<DateOnly, DayEntry> _days = new();
    private DateOnly _month;
    private DateOnly? _focus;   // the next fixture's date — ringed in the grid
    private int _nextFixtureId;

    /// <summary>What one dated square knows before it becomes a <see cref="DayCell"/>.</summary>
    private sealed record DayEntry(string L1, string L2, bool Mine, bool Played,
        Avalonia.Media.Imaging.Bitmap? Crest, int FixtureId, int OppTeamId, string OppName,
        string? EventTarget);

    public CalendarViewModel(Session s)
    {
        _s = s;
        var myId = s.CurrentTeamId;
        foreach (var f in s.Repo.Fixtures(s.SeasonId)
                     .Where(f => f.HomeTeamId == myId || f.AwayTeamId == myId))
        {
            var date = s.DateOfFixture(f);
            var oppId = f.HomeTeamId == myId ? f.AwayTeamId : f.HomeTeamId;
            var opp = s.TeamName(oppId);
            var venue = f.HomeTeamId == myId ? "(H)" : "(A)";
            var comp = f.Kind == "cup" ? "🏆" : f.Kind == "friendly" ? "PS" : "⚽";
            var r = f.Played ? s.ResultFor(f.Id) : null;
            var line2 = r is null ? venue
                : f.HomeTeamId == myId ? $"{r.HomeGoals}-{r.AwayGoals} {venue}" : $"{r.AwayGoals}-{r.HomeGoals} {venue}";
            _days[date] = new DayEntry($"{comp} {opp}", line2, true, f.Played,
                Visuals.LoadBitmap(s.TeamLogoPath(oppId)), f.Id, oppId, opp, null);
        }

        // Season EVENTS on the calendar (P6 UX): the days that matter beyond fixtures. `target` is
        // the page that day is ABOUT — clicking the square goes there.
        void MarkEvent(DateOnly d, string label, string? target = null)
        {
            if (_days.TryGetValue(d, out var e))
            {
                _days[d] = e with { L2 = $"{e.L2} · {label}", EventTarget = e.EventTarget ?? target };
            }
            else
            {
                _days[d] = new DayEntry(label, "", false, false, null, 0, 0, "", target);
            }
        }
        try
        {
            // League matchday dates come from the calendar model; events hang off them.
            DateOnly LeagueDate(int md) => SeasonCalendar.DateOf(s.SeasonYear, md, "league");
            MarkEvent(LeagueDate(19), "🚨 window closes", "Market");
            MarkEvent(LeagueDate(17), "🪟 window opens", "Market");
            MarkEvent(LeagueDate(19).AddDays(-2), "review due", "Board");
            MarkEvent(SeasonCalendar.DateOf(s.SeasonYear, 0, "friendly"), "🎓 intake day", "Academy");
            foreach (var md in Session.InternationalBreakMatchdays)
                MarkEvent(LeagueDate(md).AddDays(3), "🌍 international break");
        }
        catch { /* markers are decoration */ }

        var next = s.NextFixture();
        var focus = next is not null ? s.DateOfFixture(next) : SeasonCalendar.FirstLeagueSaturday(s.SeasonYear);
        _focus = next is not null ? focus : null;
        _nextFixtureId = next?.Id ?? 0;
        _month = new DateOnly(focus.Year, focus.Month, 1);
        BuildMonth();
    }

    public override string Title => "Calendar";
    public override string Icon => "📆";

    public ObservableCollection<DayCell> Cells { get; } = new();

    [ObservableProperty] private string _monthTitle = "";

    /// <summary>The screen's status line — verb results from the shared menu land here verbatim.</summary>
    [ObservableProperty] private string _status = "";

    // --- the grid is navigable (P9): a day you can see is a day you can act on ---------------

    /// <summary>Left-click: the next fixture opens the Office; an event day opens its screen.</summary>
    public void Activate(DayCell c)
    {
        if (c.FixtureId != 0 && c.FixtureId == _nextFixtureId) { Nav.Go("Office"); return; }
        if (c.EventTarget is { Length: > 0 } target) Nav.Go(target);
    }

    /// <summary>Right-click: the shared club menu for that day's opponent.</summary>
    public Avalonia.Controls.ContextMenu? MenuFor(DayCell c) =>
        c.OppTeamId == 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(c.OppTeamId, c.OppName),
                status: t => Status = t, refresh: BuildMonth);

    [RelayCommand] private void PrevMonth() { _month = _month.AddMonths(-1); BuildMonth(); }
    [RelayCommand] private void NextMonth() { _month = _month.AddMonths(1); BuildMonth(); }

    private void BuildMonth()
    {
        MonthTitle = _month.ToString("MMMM yyyy");
        Cells.Clear();
        // Monday-first grid, 6 rows of 7.
        var first = _month;
        var lead = ((int)first.DayOfWeek + 6) % 7;
        var start = first.AddDays(-lead);
        for (var i = 0; i < 42; i++)
        {
            var d = start.AddDays(i);
            if (d.Month != _month.Month)
            {
                Cells.Add(new DayCell("", "", "", Blank, Dim));
                continue;
            }
            var ring = d == _focus ? FocusRing : null;
            if (_days.TryGetValue(d, out var e))
            {
                // Fixture days keep the green/grey tints; event-only days get the amber tint.
                var bg = e.Played ? PlayedBg : e.Mine ? MineBg : EventBg;
                Cells.Add(new DayCell(d.Day.ToString(), e.L1, e.L2, bg, Fg, e.Crest, ring,
                    e.FixtureId, e.OppTeamId, e.OppName, e.EventTarget));
            }
            else
            {
                Cells.Add(new DayCell(d.Day.ToString(), "", "", DayBg, Dim, null, ring));
            }
        }
    }
}
