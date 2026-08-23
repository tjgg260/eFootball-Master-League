using System.Collections.ObjectModel;

namespace ML.App.ViewModels;

// --- Stats (league leaders, discipline, clean sheets, head-to-head, honours) ------

public sealed record StatRow(string Team, int Value, Avalonia.Media.Imaging.Bitmap? Crest = null);

public sealed record ScorerRow(string Player, string Team, int Goals, string Rate,
    Avalonia.Media.Imaging.Bitmap? Portrait = null);

public sealed record CardRow(string Player, string Team, string Cards,
    Avalonia.Media.Imaging.Bitmap? Portrait = null);

public sealed record HonourRow(int Year, string Competition, string Team,
    Avalonia.Media.Imaging.Bitmap? Crest = null);

public sealed record ReportRow(string When, string Line, string Stats);

public sealed class StatsViewModel : PageViewModel
{
    public StatsViewModel(Session s)
    {
        var table = s.Table();
        static string Rate(int count, int apps) =>
            apps > 0 ? $"{count / (double)apps:0.00}/game" : "";
        Avalonia.Media.Imaging.Bitmap? Face(long pid)
        { try { return s.PortraitFor(pid).Image; } catch { return null; } }
        Avalonia.Media.Imaging.Bitmap? Crest(int tid)
        { try { return Visuals.LoadBitmap(s.TeamLogoPath(tid)); } catch { return null; } }
        TopScorers = new ObservableCollection<ScorerRow>(
            s.LeadersBy("goal").Select(x => new ScorerRow(x.Player, x.Team, x.Count, Rate(x.Count, x.Apps), Face(x.PlayerId))));
        TopAssists = new ObservableCollection<ScorerRow>(
            s.LeadersBy("assist").Select(x => new ScorerRow(x.Player, x.Team, x.Count, Rate(x.Count, x.Apps), Face(x.PlayerId))));
        ScorersNote = TopScorers.Count == 0
            ? "Goals appear here as matches are played — type your scorers when you record a result."
            : "";
        // No games, no ranking: eight clubs on 0 GA is noise dressed as a table.
        BestDefence = new ObservableCollection<StatRow>(
            table.Any(t => t.Played > 0)
                ? table.Where(t => t.Played > 0).OrderBy(t => t.GoalsAgainst).Take(8)
                     .Select(t => new StatRow(s.TeamName(t.TeamId.Value), t.GoalsAgainst, Crest(t.TeamId.Value)))
                : Enumerable.Empty<StatRow>());
        try
        {
            CleanSheets = new ObservableCollection<StatRow>(
                s.CleanSheetTable().Select(x => new StatRow(x.Team, x.Count, Crest(x.TeamId))));
            Discipline = new ObservableCollection<CardRow>(
                s.DisciplineLeaders().Select(x => new CardRow(x.Player, x.Team,
                    x.Reds > 0 ? $"{x.Yellows}🟨 {x.Reds}🟥" : $"{x.Yellows}🟨", Face(x.PlayerId))));
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
                    HeadToHeadLine = $"vs {s.TeamName(opp)} (all-time): {w} won · {d} drawn · {l} lost";
            }
        }
        catch { /* h2h is decoration */ }

        Honours = new ObservableCollection<HonourRow>(
            s.Honours().Select(h => new HonourRow(h.Year, h.Competition, h.Team,
                h.HolderIsPlayer ? Face(h.HolderId) : Crest(h.HolderId))));
        MatchReports = new ObservableCollection<ReportRow>(
            s.MyMatchReports().Select(m => new ReportRow(m.When, m.Line, m.Stats)));
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
}
