using System.Collections.ObjectModel;
using Avalonia.Controls;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Stats (league leaders, discipline, clean sheets, head-to-head, honours) ------
//
// Every row keeps the id of the thing it describes. A stat line is a handle on a player or
// a club, not a rendered string — that is what lets the shared right-click menu work here
// exactly as it does on the squad list.

public sealed record StatRow(string Team, int Value, Avalonia.Media.Imaging.Bitmap? Crest = null,
    int TeamId = 0);

public sealed record ScorerRow(string Player, string Team, int Goals, string Rate,
    Avalonia.Media.Imaging.Bitmap? Portrait = null, long PlayerId = 0);

public sealed record CardRow(string Player, string Team, string Cards,
    Avalonia.Media.Imaging.Bitmap? Portrait = null, long PlayerId = 0);

/// <summary>A line of the Roll of Honour. Most holders are clubs; the Player of the Season
/// award holds a PLAYER, so the row carries which — the menu dispatches on it.</summary>
public sealed record HonourRow(int Year, string Competition, string Team,
    Avalonia.Media.Imaging.Bitmap? Crest = null, long HolderId = 0, bool HolderIsPlayer = false);

public sealed record ReportRow(string When, string Line, string Stats, int FixtureId = 0);

public sealed partial class StatsViewModel : PageViewModel
{
    private readonly Session _s;

    public StatsViewModel(Session s)
    {
        _s = s;
        var table = s.Table();
        static string Rate(int count, int apps) =>
            apps > 0 ? $"{count / (double)apps:0.00}/game" : "";
        Avalonia.Media.Imaging.Bitmap? Face(long pid)
        { try { return s.PortraitFor(pid).Image; } catch { return null; } }
        // A HOLDER id is a long — a Roll of Honour row can be won by a club or by a PLAYER, and
        // player ids in this world run past Int32. TeamLogoPath still takes an int because a team
        // id genuinely is one, so narrow at the call and refuse anything that could not be a team.
        Avalonia.Media.Imaging.Bitmap? Crest(long tid)
        {
            if (tid is <= 0 or > int.MaxValue) return null;
            try { return Visuals.LoadBitmap(s.TeamLogoPath((int)tid)); } catch { return null; }
        }
        TopScorers = new ObservableCollection<ScorerRow>(
            s.LeadersBy("goal").Select(x => new ScorerRow(x.Player, x.Team, x.Count, Rate(x.Count, x.Apps),
                Face(x.PlayerId), x.PlayerId)));
        TopAssists = new ObservableCollection<ScorerRow>(
            s.LeadersBy("assist").Select(x => new ScorerRow(x.Player, x.Team, x.Count, Rate(x.Count, x.Apps),
                Face(x.PlayerId), x.PlayerId)));
        ScorersNote = TopScorers.Count == 0
            ? "Goals appear here as matches are played — type your scorers when you record a result."
            : "";
        // No games, no ranking: eight clubs on 0 GA is noise dressed as a table.
        BestDefence = new ObservableCollection<StatRow>(
            table.Any(t => t.Played > 0)
                ? table.Where(t => t.Played > 0).OrderBy(t => t.GoalsAgainst).Take(8)
                     .Select(t => new StatRow(s.TeamName(t.TeamId.Value), t.GoalsAgainst,
                         Crest(t.TeamId.Value), t.TeamId.Value))
                : Enumerable.Empty<StatRow>());
        try
        {
            CleanSheets = new ObservableCollection<StatRow>(
                s.CleanSheetTable().Select(x => new StatRow(x.Team, x.Count, Crest(x.TeamId), x.TeamId)));
            Discipline = new ObservableCollection<CardRow>(
                s.DisciplineLeaders().Select(x => new CardRow(x.Player, x.Team,
                    x.Reds > 0 ? $"{x.Yellows}🟨 {x.Reds}🟥" : $"{x.Yellows}🟨", Face(x.PlayerId), x.PlayerId)));
        }
        catch { /* season may have no events yet */ }

        // Head-to-head vs your next opponent — the record that matters this week.
        try
        {
            if (s.NextFixture() is { } next && next.Kind != "friendly")
            {
                var opp = next.HomeTeamId == s.CurrentTeamId ? next.AwayTeamId : next.HomeTeamId;
                var (w, d, l) = s.HeadToHead(s.CurrentTeamId, opp);
                if (w + d + l > 0)
                {
                    HeadToHeadLine = $"vs {s.TeamName(opp)} (all-time): {w} won · {d} drawn · {l} lost";
                    OpponentId = opp;
                    OpponentName = s.TeamName(opp);
                }
            }
        }
        catch { /* h2h is decoration */ }

        Honours = new ObservableCollection<HonourRow>(
            s.Honours().Select(h => new HonourRow(h.Year, h.Competition, h.Team,
                h.HolderIsPlayer ? Face(h.HolderId) : Crest(h.HolderId), h.HolderId, h.HolderIsPlayer)));
        MatchReports = new ObservableCollection<ReportRow>(
            s.MyMatchReportsWithIds().Select(m => new ReportRow(m.When, m.Line, m.Stats, m.FixtureId)));
        HonoursNote = Honours.Count == 0
            ? "No silverware handed out yet — finish a season to start the Roll of Honour."
            : "";
    }

    public override string Title => "Stats";
    public override string Icon => "📈";
    public ObservableCollection<ScorerRow> TopScorers { get; }
    public ObservableCollection<ScorerRow> TopAssists { get; }
    public string ScorersNote { get; }
    public ObservableCollection<StatRow> BestDefence { get; }
    public ObservableCollection<StatRow> CleanSheets { get; } = new();
    public ObservableCollection<CardRow> Discipline { get; } = new();
    public string HeadToHeadLine { get; } = "";
    public bool HasHeadToHead => HeadToHeadLine.Length > 0;
    public bool HasCleanSheets => CleanSheets.Count > 0;
    public bool HasDiscipline => Discipline.Count > 0;
    public ObservableCollection<HonourRow> Honours { get; }
    public ObservableCollection<ReportRow> MatchReports { get; }
    public string HonoursNote { get; }

    /// <summary>Verb results land here — the one line this screen talks on.</summary>
    [ObservableProperty] private string _status = "";

    // The head-to-head panel's subject, so the opponent is one click away.
    public int OpponentId { get; }
    public string OpponentName { get; } = "";
    public string OpponentButton => OpponentName.Length > 0 ? $"View {OpponentName}" : "View club";

    [RelayCommand]
    private void ViewOpponent()
    {
        if (OpponentId > 0) Nav.Go("Squad", EntityRef.Club(OpponentId, OpponentName));
    }

    // --- shared right-click menus ------------------------------------------------
    // A leaderboard is a squad list by another name: the same verbs apply, and the menu
    // itself decides what a foreign player may be offered (scout, enquire, shortlist).
    // No refresh callback: nothing on this screen is derived from the state these verbs
    // change, and the menu is rebuilt fresh on every open, so toggles are never stale.

    public ContextMenu? MenuFor(ScorerRow r) =>
        r.PlayerId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(r.PlayerId, r.Player), status: t => Status = t);

    public ContextMenu? MenuFor(CardRow r) =>
        r.PlayerId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(r.PlayerId, r.Player), status: t => Status = t);

    public ContextMenu? MenuFor(StatRow r) =>
        r.TeamId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(r.TeamId, r.Team), status: t => Status = t);

    /// <summary>Roll of Honour: a club lifted most of these, a player won the award.</summary>
    public ContextMenu? MenuFor(HonourRow h) =>
        h.HolderId <= 0 ? null
            : EntityActions.BuildMenu(_s,
                h.HolderIsPlayer ? EntityRef.Player(h.HolderId, h.Team) : EntityRef.Club(h.HolderId, h.Team),
                status: t => Status = t);

    /// <summary>A filed report is a fixture: the only verb it has is "show me that day".</summary>
    public ContextMenu? MenuFor(ReportRow r)
    {
        if (r.FixtureId <= 0) return null;
        var menu = new ContextMenu();
        var open = new MenuItem { Header = "📅 Show in Calendar" };
        open.Click += (_, _) => Nav.Go("Calendar", new EntityRef(EntityKind.Fixture, r.FixtureId, r.Line));
        menu.Items.Add(open);
        return menu;
    }
}
