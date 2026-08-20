using System.Collections.ObjectModel;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public sealed record AcademyEntry(
    int PlayerId, string Name, string Position, int Age, int Rating, IBrush RatingBrush,
    string Potential, IBrush FaceBrush)
{
    public string Mark => Visuals.PlayerMark(Name);
}

/// <summary>Your youth setup: this season's prospects, with promotion to the senior squad.</summary>
public sealed partial class AcademyViewModel : PageViewModel
{
    private readonly Session _s;

    public AcademyViewModel(Session s)
    {
        _s = s;
        Reload();
    }

    private void Reload()
    {
        Rows.Clear();
        foreach (var p in _s.AcademyPlayers())
        {
            var rating = p.OverallRating ?? 50;
            // REAL potential (P2): the same stored ceiling development grows toward.
            var stars = _s.PotentialStars(p.Id);
            int? tone = null;
            try { tone = _s.NewsFaceOf(p.Id).SkinTone; } catch { }
            Rows.Add(new AcademyEntry(p.Id, p.Name, p.Position, p.Age ?? 17, rating,
                Visuals.RatingBrush(rating), new string('★', stars) + new string('☆', 5 - stars),
                Visuals.SkinBrush(tone)));
        }
        Note = Rows.Count == 0
            ? "No prospects yet — the academy produces a new intake every preseason."
            : "★ is the youth coach's read of each lad's real ceiling — development chases it. " +
              "Young players develop fastest before 24; promote them when a squad place opens.";
    }

    public override string Title => "Academy";
    public override string Icon => "🎓";
    public ObservableCollection<AcademyEntry> Rows { get; } = new();

    [ObservableProperty]
    private AcademyEntry? _selected;

    [ObservableProperty]
    private string _note = "";

    [ObservableProperty]
    private string _status = "";

    [RelayCommand]
    private void Promote()
    {
        if (Selected is null)
        {
            Status = "Select a prospect first.";
            return;
        }
        Status = $"{Selected.Name}: {_s.PromoteAcademy(Selected.PlayerId)}";
        Reload();
    }
}
