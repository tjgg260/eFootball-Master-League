using System.Collections.ObjectModel;

namespace ML.App.ViewModels;

// --- League table -----------------------------------------------------------------

public sealed record TableEntry(
    int Pos, string Team, int P, int W, int D, int L, int GF, int GA, int GD, int Pts, bool IsMine,
    Avalonia.Media.Imaging.Bitmap? Logo, string Badge, Avalonia.Media.IBrush BadgeBrush);

public sealed class TableViewModel : PageViewModel
{
    public TableViewModel(Session s)
    {
        foreach (var row in s.Table())
        {
            var id = row.TeamId.Value;
            var name = s.TeamName(id);
            Rows.Add(new TableEntry(
                row.Position, name, row.Played, row.Won, row.Drawn, row.Lost,
                row.GoalsFor, row.GoalsAgainst, row.GoalDifference, row.Points, id == s.CurrentTeamId,
                Visuals.LoadBitmap(s.TeamLogoPath(id)), Visuals.Initials(name),
                Visuals.Brush(s.TeamColor(id))));
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
}
