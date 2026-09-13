using System.Collections.ObjectModel;
using System.Globalization;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- The Match Report: everything the stats host recorded for one fixture ----------------------
//
// Reached by clicking a match on Stats (Match reports). A destination, not a sidebar page, like
// Player and Bidding: it needs a fixture to show.

public sealed record StatBarRow(string Label, string Home, string Away, double HomeWidth, double AwayWidth, string Note)
{
    public bool HasNote => Note.Length > 0;
}

public sealed record ReportPlayerRow(long PlayerId, Bitmap? Portrait, string Shirt, string Name, string Status,
    string Rating, long Goals, long Shots, long OnTarget, long Passes, long Completed, string PassPct,
    long Crosses, long Tackles, long Interceptions, long Recoveries, long Fouls, long Offsides, long Corners,
    long Saves, long ShotsFaced, long OnTargetFaced, long Receptions, long Touches, long Possessions,
    long Kept, long PossSeconds, long Sprints, string Form);

public sealed record FlowBar(double Height, string Tip);

public sealed record FlowRow(string Label, IReadOnlyList<FlowBar> Home, IReadOnlyList<FlowBar> Away, string Totals);

public sealed record CounterRow(string Id, string Label, string Home, string Away, string Confidence);

public sealed partial class MatchReportViewModel : PageViewModel, IFocusTarget
{
    private const double BarMax = 150;     // px each side of a team-stat line
    private const double FlowMax = 40;     // px, tallest segment bar

    private readonly Session _s;

    public MatchReportViewModel(Session s) => _s = s;

    public override string Title => "Match Report";
    public override string Icon => "";

    [ObservableProperty] private string _homeName = "";
    [ObservableProperty] private string _awayName = "";
    [ObservableProperty] private string _score = "";
    [ObservableProperty] private string _whenLine = "";
    [ObservableProperty] private string _metaLine = "";
    [ObservableProperty] private Bitmap? _homeCrest;
    [ObservableProperty] private Bitmap? _awayCrest;
    [ObservableProperty] private bool _hasReport;
    [ObservableProperty] private bool _hasExport;
    [ObservableProperty] private string _status = "Open a match from Stats → Match reports.";

    public ObservableCollection<StatBarRow> TeamStats { get; } = new();
    public ObservableCollection<ReportPlayerRow> HomePlayers { get; } = new();
    public ObservableCollection<ReportPlayerRow> AwayPlayers { get; } = new();
    public ObservableCollection<FlowRow> Flow { get; } = new();
    public ObservableCollection<CounterRow> Counters { get; } = new();
    public ObservableCollection<string> Caveats { get; } = new();

    public void Focus(EntityRef target)
    {
        if (target.Kind != EntityKind.Fixture)
        {
            Status = "That isn't a match. Open one from Stats → Match reports.";
            return;
        }
        try { Load((int)target.Id); }
        catch (Exception ex)
        {
            Program.Log("MatchReport.Load", ex);
            Status = $"This report could not be read: {ex.Message}";
        }
    }

    private void Load(int fixtureId)
    {
        var r = _s.MatchReport(fixtureId);
        HasReport = r is not null;
        if (r is null) { Status = "No result is recorded for that match yet."; return; }

        HomeName = r.HomeName;
        AwayName = r.AwayName;
        Score = $"{r.HomeGoals} – {r.AwayGoals}";
        WhenLine = r.When;
        HomeCrest = Crest(r.HomeTeamId);
        AwayCrest = Crest(r.AwayTeamId);
        HasExport = r.HasExport;
        MetaLine = r.HasExport
            ? $"From the stats host · kick-off {r.KickOff?.ToLocalTime():HH:mm} · final {r.Finished?.ToLocalTime():HH:mm}" +
              (r.FinalReason is { Length: > 0 } why ? $" ({why.Replace('_', ' ')})" : "") + $" · {r.Stem}"
            : "This result was entered by hand — the stats host recorded nothing for it.";
        Status = "";

        TeamStats.Clear();
        foreach (var t in r.TeamStats)
        {
            var total = t.Percent ? 100 : t.Home + t.Away;
            string V(double v) => t.Percent ? $"{v:0}%" : v.ToString("0", CultureInfo.InvariantCulture);
            TeamStats.Add(new StatBarRow(t.Label + (t.Inferred ? "  ≈" : ""), V(t.Home), V(t.Away),
                total > 0 ? BarMax * t.Home / total : 0, total > 0 ? BarMax * t.Away / total : 0, t.Note ?? ""));
        }

        Fill(HomePlayers, r.HomePlayers);
        Fill(AwayPlayers, r.AwayPlayers);

        Flow.Clear();
        foreach (var s in r.Flow)
        {
            var max = Math.Max(1, s.Home.Concat(s.Away).DefaultIfEmpty(0).Max());
            bool time = s.Label == "Possession time";
            string Tip(int i, long v) => $"segment {i + 1}: " + (time ? $"{v / Session.PossessionUnitsPerSecond:0} s" : $"{v}");
            FlowRow row = new(s.Label,
                s.Home.Select((v, i) => new FlowBar(FlowMax * v / max, Tip(i, v))).ToList(),
                s.Away.Select((v, i) => new FlowBar(FlowMax * v / max, Tip(i, v))).ToList(),
                time ? $"{s.Home.Sum() / Session.PossessionUnitsPerSecond:0} s – {s.Away.Sum() / Session.PossessionUnitsPerSecond:0} s"
                     : $"{s.Home.Sum()} – {s.Away.Sum()}");
            Flow.Add(row);
        }

        Counters.Clear();
        foreach (var c in r.Counters)
            Counters.Add(new CounterRow(c.Id, c.Label, c.Home.ToString(), c.Away.ToString(), c.Confidence));

        Caveats.Clear();
        foreach (var c in r.Caveats) Caveats.Add(c);
    }

    private void Fill(ObservableCollection<ReportPlayerRow> target, IReadOnlyList<ReportPlayer> players)
    {
        target.Clear();
        foreach (var p in players)
        {
            long A(string k) => p.Actions.TryGetValue(k, out var v) ? v : 0;
            var passes = A("passes");
            target.Add(new ReportPlayerRow(
                p.PlayerId ?? 0, Face(p.PlayerId), p.Shirt?.ToString() ?? "", p.Name, p.Status,
                p.Rating is { } rt ? rt.ToString("0.0", CultureInfo.InvariantCulture) : "",
                A("goals"), A("shots"), A("shots_on_target"), passes, A("passes_completed"),
                passes > 0 ? $"{100.0 * A("passes_completed") / passes:0}%" : "",
                A("crosses"), A("tackles"), A("interceptions"), A("ball_recoveries"), A("fouls"),
                A("offsides"), A("corners"), A("saves"), A("gk_shots_faced"), A("gk_shots_on_target_faced"),
                A("ball_receptions"), A("ball_touches"), A("possessions"), A("possessions_retained"),
                (long)Math.Round(A("possession_time") / Session.PossessionUnitsPerSecond), A("sprints"),
                p.FormAverage is { } f
                    ? (Math.Abs(f) < 0.05 ? "±0" : f.ToString("+0.0;−0.0", CultureInfo.InvariantCulture)) +
                      (p.FormChanged > 0 ? $" ({p.FormChanged})" : "")
                    : ""));
        }
    }

    private Bitmap? Face(long? playerId)
    {
        if (playerId is not { } id || id <= 0) return null;
        try { return _s.PortraitFor(id).Image; } catch { return null; }
    }

    private Bitmap? Crest(int teamId)
    {
        try { return Visuals.LoadBitmap(_s.TeamLogoPath(teamId)); } catch { return null; }
    }

    /// <summary>A player's row: straight to his profile.</summary>
    [RelayCommand]
    private void OpenPlayer(ReportPlayerRow? row)
    {
        if (row is { PlayerId: > 0 }) Nav.Go("Player", EntityRef.Player(row.PlayerId, row.Name));
    }

    /// <summary>The shared player menu, for a row the export resolved to a league player.</summary>
    public Avalonia.Controls.ContextMenu? MenuFor(ReportPlayerRow row) =>
        row.PlayerId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(row.PlayerId, row.Name), status: t => Status = t);
}
