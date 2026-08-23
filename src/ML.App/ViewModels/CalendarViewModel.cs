using System.Collections.ObjectModel;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Core.Scheduling;

namespace ML.App.ViewModels;

// --- Calendar (FM-style month grid over real season dates) ------------------------

public sealed record DayCell(string DayText, string Line1, string Line2, IBrush Bg, IBrush Fg,
    Avalonia.Media.Imaging.Bitmap? Crest = null, IBrush? Ring = null);

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
    private readonly Dictionary<DateOnly, (string L1, string L2, bool Mine, bool Played,
        Avalonia.Media.Imaging.Bitmap? Crest)> _days = new();
    private DateOnly _month;
    private DateOnly? _focus;   // the next fixture's date — ringed in the grid

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
            _days[date] = ($"{comp} {opp}", line2, true, f.Played,
                Visuals.LoadBitmap(s.TeamLogoPath(oppId)));
        }

        // Season EVENTS on the calendar (P6 UX): the days that matter beyond fixtures.
        void MarkEvent(DateOnly d, string label)
        {
            if (_days.TryGetValue(d, out var e))
            {
                _days[d] = (e.L1, $"{e.L2} · {label}", e.Mine, e.Played, e.Crest);
            }
            else
            {
                _days[d] = (label, "", false, false, null);
            }
        }
        try
        {
            // League matchday dates come from the calendar model; events hang off them.
            DateOnly LeagueDate(int md) => SeasonCalendar.DateOf(s.SeasonYear, md, "league");
            MarkEvent(LeagueDate(19), "🚨 window closes");
            MarkEvent(LeagueDate(17), "🪟 window opens");
            MarkEvent(LeagueDate(19).AddDays(-2), "review due");
            MarkEvent(SeasonCalendar.DateOf(s.SeasonYear, 0, "friendly"), "🎓 intake day");
            foreach (var md in Session.InternationalBreakMatchdays)
                MarkEvent(LeagueDate(md).AddDays(3), "🌍 international break");
        }
        catch { /* markers are decoration */ }

        var next = s.NextFixture();
        var focus = next is not null ? s.DateOfFixture(next) : SeasonCalendar.FirstLeagueSaturday(s.SeasonYear);
        _focus = next is not null ? focus : null;
        _month = new DateOnly(focus.Year, focus.Month, 1);
        BuildMonth();
    }

    public override string Title => "Calendar";
    public override string Icon => "📆";

    public ObservableCollection<DayCell> Cells { get; } = new();

    [ObservableProperty] private string _monthTitle = "";

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
                Cells.Add(new DayCell(d.Day.ToString(), e.L1, e.L2, bg, Fg, e.Crest, ring));
            }
            else
            {
                Cells.Add(new DayCell(d.Day.ToString(), "", "", DayBg, Dim, null, ring));
            }
        }
    }
}
