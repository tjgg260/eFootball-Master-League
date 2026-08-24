using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Tables;

namespace ML.App.ViewModels;

// --- League table -----------------------------------------------------------------

/// <summary>A standings row. It carries the club's id, not just its name: the table is the
/// most natural place in the app to right-click a rival, and arriving here from elsewhere
/// (Nav.Go("Table", club)) has to be able to find the row again.</summary>
public sealed record TableEntry(
    int Pos, string Team, int P, int W, int D, int L, int GF, int GA, int GD, int Pts, bool IsMine,
    Avalonia.Media.Imaging.Bitmap? Logo, string Badge, IBrush BadgeBrush,
    IBrush? ZoneBrush, IBrush PosBrush, FontWeight Weight, string Movement, IBrush MovementBrush,
    int TeamId = 0);

public sealed partial class TableViewModel : PageViewModel, IFocusTarget
{
    private readonly Session _s;

    // Token hex mirrors Theme.axaml (MlGold/MlSuccess/MlDanger/MlSuccessText/MlTextBody) —
    // zone assignment is per-row data, so the brushes come from the VM like HistoryViewModel's.
    private static readonly IBrush Gold = Visuals.Brush("#D4AC0D");
    private static readonly IBrush Green = Visuals.Brush("#1F9D4D");
    private static readonly IBrush Red = Visuals.Brush("#D64545");
    private static readonly IBrush GreenText = Visuals.Brush("#9FE6B4");
    private static readonly IBrush BodyText = Visuals.Brush("#C7CEDA");
    private static readonly IBrush NoBrush = Avalonia.Media.Brushes.Transparent;

    public TableViewModel(Session s)
    {
        _s = s;
        // Zone sizes come from league data, never hardcoded: the leagues table carries
        // promotion_places/relegation_places for the division the user is sitting in.
        var league = s.Repo.Leagues().FirstOrDefault(l => l.Id == s.LeagueId);
        var promo = league?.PromotionPlaces ?? 0;
        var releg = league?.RelegationPlaces ?? 0;

        // P5 guard: with zero results the table is alphabetical noise — no zones, no legend.
        var table = s.Table();
        var hasResults = table.Any(r => r.Played > 0);

        // Movement vs last matchday: rebuild the table without the latest played matchday
        // (one extra LeagueTable.Build — same trick PositionHistory uses, but once).
        var prev = new Dictionary<int, int>();
        try
        {
            if (hasResults)
            {
                var all = s.Repo.Fixtures(s.SeasonId)
                    .Where(f => f.LeagueId == s.LeagueId && f.Kind == "league").ToList();
                var maxMd = all.Where(f => f.Played).Select(f => f.Matchday).DefaultIfEmpty(0).Max();
                if (maxMd >= 2)
                {
                    var teamIds = s.LeagueTeams().Select(t => new TeamId(t.Id)).ToList();
                    var fixtures = new List<Fixture>();
                    foreach (var f in all)
                    {
                        var fixture = new Fixture(f.Id, f.Matchday,
                            new TeamId(f.HomeTeamId), new TeamId(f.AwayTeamId));
                        if (f.Played && f.Matchday < maxMd && s.ResultFor(f.Id) is { } r)
                        {
                            fixture.RecordResult(new MatchResult(r.HomeGoals, r.AwayGoals));
                        }
                        fixtures.Add(fixture);
                    }
                    foreach (var row in LeagueTable.Build(teamIds, fixtures))
                    {
                        prev[row.TeamId.Value] = row.Position;
                    }
                }
            }
        }
        catch { prev.Clear(); /* movement is garnish, the table must still render */ }

        foreach (var row in table)
        {
            var id = row.TeamId.Value;
            var name = s.TeamName(id);
            var mine = id == s.CurrentTeamId;

            var champion = hasResults && row.Position == 1;
            var promoted = hasResults && !champion && row.Position <= promo;
            var relegated = hasResults && releg > 0 && row.Position > table.Count - releg;
            var zone = champion ? Gold : promoted ? Green : relegated ? Red : null;
            var posBrush = champion ? Gold : promoted ? GreenText : relegated ? Red : BodyText;

            var delta = prev.TryGetValue(id, out var was) ? was - row.Position : 0;
            var movement = delta > 0 ? "▲" : delta < 0 ? "▼" : "";
            var movementBrush = delta > 0 ? GreenText : delta < 0 ? Red : NoBrush;

            Rows.Add(new TableEntry(
                row.Position, name, row.Played, row.Won, row.Drawn, row.Lost,
                row.GoalsFor, row.GoalsAgainst, row.GoalDifference, row.Points, mine,
                Visuals.LoadBitmap(s.TeamLogoPath(id)), Visuals.Initials(name),
                Visuals.Brush(s.TeamColor(id)),
                zone, posBrush, mine ? FontWeight.Bold : FontWeight.Normal,
                movement, movementBrush, id));
        }

        // Legend in words, built from the zones this league actually has.
        if (hasResults && Rows.Count > 0)
        {
            var parts = new List<string> { "gold champions" };
            if (promo > 0) parts.Add("green promotion");
            if (releg > 0) parts.Add("red relegation");
            LegendText = string.Join(" · ", parts);
            LegendVisible = true;
        }

        // The position worm (P6): your season's shape at a glance.
        try
        {
            var history = s.PositionHistory();
            var teams = Math.Max(Rows.Count, 2);
            if (history.Count >= 2)
            {
                const double w = 560, h = 84;
                var step = w / Math.Max(history.Count - 1, 1);
                for (var i = 0; i < history.Count; i++)
                {
                    var y = (history[i] - 1) / (double)(teams - 1) * (h - 8) + 4;
                    WormPoints.Add(new Avalonia.Point(i * step, y));
                }
                WormVisible = true;
                WormLabel = $"Position by matchday — now {Ordinal(history[^1])} " +
                            $"(best {Ordinal(history.Min())}, worst {Ordinal(history.Max())})";
            }
        }
        catch { WormVisible = false; }
    }

    private static string Ordinal(int n) => n switch
    {
        11 or 12 or 13 => $"{n}th",
        _ when n % 10 == 1 => $"{n}st",
        _ when n % 10 == 2 => $"{n}nd",
        _ when n % 10 == 3 => $"{n}rd",
        _ => $"{n}th",
    };

    public override string Title => "Table";
    public override string Icon => "📊";
    public ObservableCollection<TableEntry> Rows { get; } = new();
    public Avalonia.Points WormPoints { get; } = new();
    public bool WormVisible { get; }
    public string WormLabel { get; } = "";
    public bool LegendVisible { get; }
    public string LegendText { get; } = "";

    /// <summary>The highlighted row — set by a click, by right-click, or by arriving focused.</summary>
    [ObservableProperty] private TableEntry? _selected;

    /// <summary>Verb results land here, verbatim.</summary>
    [ObservableProperty] private string _status = "";

    /// <summary>Right-click a standings row: the shared club menu (squad, scout, head-to-head).</summary>
    public ContextMenu? MenuFor(TableEntry r) =>
        r.TeamId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(r.TeamId, r.Team), status: t => Status = t);

    /// <summary>Arriving from elsewhere on a club ("where are they in the table?") — the row
    /// is selected, not merely present. Anything else focusable here is still just a club.</summary>
    public void Focus(EntityRef target)
    {
        var tid = target.Kind == EntityKind.Club ? (int)target.Id
            : target.Kind == EntityKind.Player ? _s.ClubOfPlayer(target.Id).TeamId ?? 0
            : 0;
        if (tid <= 0) return;
        var row = Rows.FirstOrDefault(r => r.TeamId == tid);
        if (row is null) return;
        Selected = row;
        Status = $"{row.Team} — {Ordinal(row.Pos)}, {row.Pts} pts.";
    }
}
