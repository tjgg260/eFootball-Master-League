using System.Collections.ObjectModel;

namespace ML.App.ViewModels;

// --- Stats (league leaders + roll of honour) --------------------------------------

public sealed record StatRow(string Team, int Value);

public sealed record ScorerRow(string Player, string Team, int Goals);

public sealed record HonourRow(int Year, string Competition, string Team);

public sealed record ReportRow(string When, string Line, string Stats);

public sealed class StatsViewModel : PageViewModel
{
    public StatsViewModel(Session s)
    {
        var table = s.Table();
        TopScorers = new ObservableCollection<ScorerRow>(
            s.LeadersBy("goal").Select(x => new ScorerRow(x.Player, x.Team, x.Count)));
        TopAssists = new ObservableCollection<ScorerRow>(
            s.LeadersBy("assist").Select(x => new ScorerRow(x.Player, x.Team, x.Count)));
        ScorersNote = TopScorers.Count == 0
            ? "Goals appear here as matches are played — type your scorers when you record a result."
            : "";
        BestDefence = new ObservableCollection<StatRow>(
            table.OrderBy(t => t.GoalsAgainst).Take(8)
                 .Select(t => new StatRow(s.TeamName(t.TeamId.Value), t.GoalsAgainst)));
        Honours = new ObservableCollection<HonourRow>(
            s.Honours().Select(h => new HonourRow(h.Year, h.Competition, h.Team)));
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
    public ObservableCollection<HonourRow> Honours { get; }
    public ObservableCollection<ReportRow> MatchReports { get; }
    public string HonoursNote { get; }
}
