using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public sealed record AcademyEntry(
    long PlayerId, string Name, string Position, int Age, int Rating, IBrush RatingBrush,
    string Potential, IBrush FaceBrush, Avalonia.Media.Imaging.Bitmap? Portrait = null)
{
    public string Mark => Visuals.PlayerMark(Name);
    public bool HasPortrait => Portrait is not null;
    public string Grade => ML.Core.Development.AttributeKnowledge.Grade(Rating);   // your academy
}

/// <summary>A lad on one of the youth sides. Same read as a prospect — he's already yours,
/// so nothing is masked; what differs is where he can go next.</summary>
public sealed record YouthEntry(
    long PlayerId, string Name, string Position, int Age, int Rating, IBrush RatingBrush,
    string Potential, string Level)
{
    public string Grade => ML.Core.Development.AttributeKnowledge.Grade(Rating);   // your youth side
}

/// <summary>Your youth setup: this season's prospects and the U21/U18 sides beneath the first
/// team, with promotion, demotion and the scouting verbs on every lad.</summary>
public sealed partial class AcademyViewModel : PageViewModel
{
    private readonly Session _s;

    /// <summary>Which prospect the "release" verb is armed for. Destructive verbs are
    /// two-step, and the arm belongs to one lad only — selecting anyone else disarms it.</summary>
    private long? _armedRelease;

    public AcademyViewModel(Session s)
    {
        _s = s;
        Reload();
    }

    private void Reload()
    {
        Selected = null;
        Rows.Clear();
        foreach (var p in _s.AcademyPlayers())
        {
            var rating = p.OverallRating ?? 50;
            // REAL potential (P2): the same stored ceiling development grows toward.
            var stars = _s.PotentialStars(p.Id);
            int? tone = null;
            Avalonia.Media.Imaging.Bitmap? face = null;
            try
            {
                var por = _s.PortraitFor(p.Id);
                tone = por.SkinTone;
                face = por.Image;
            }
            catch { }
            Rows.Add(new AcademyEntry(p.Id, p.Name, p.Position, p.Age ?? 17, rating,
                Visuals.RatingBrush(rating), Stars(stars),
                Visuals.SkinBrush(tone), face));
        }
        HasProspects = Rows.Count > 0;
        // When there are no prospects the view shows its own empty state; no note needed.
        Note = HasProspects
            ? "★ is the youth coach's read of each lad's real ceiling — development chases it. " +
              "Young players develop fastest before 24; promote them when a squad place opens."
            : "";
    }

    /// <summary>Load the U21 or U18 side for the tab currently showing.</summary>
    private void LoadYouth()
    {
        SelectedYouth = null;
        YouthRows.Clear();
        var kind = IsU18Tab ? "u18" : "u21";
        try
        {
            foreach (var y in _s.YouthSquad(_s.CurrentTeamId, kind))
            {
                var stars = _s.PotentialStars(y.PlayerId);
                YouthRows.Add(new YouthEntry(y.PlayerId, y.Name, y.Position, y.Age, y.Overall,
                    Visuals.RatingBrush(y.Overall), Stars(stars), y.Level));
            }
        }
        catch { /* youth sides are additive — an older career simply shows an empty side */ }
        HasYouth = YouthRows.Count > 0;
        Note = HasYouth
            ? $"Your {kind.ToUpperInvariant()} side. Minutes here still develop a lad; minutes above " +
              "him do it faster — bring him up the moment he has outgrown the level."
            : "";
    }

    private static string Stars(int n) => new string('★', n) + new string('☆', 5 - n);

    public override string Title => "Academy";
    public override string Icon => "🎓";
    public ObservableCollection<AcademyEntry> Rows { get; } = new();
    public ObservableCollection<YouthEntry> YouthRows { get; } = new();

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(PromoteCommand))]
    private AcademyEntry? _selected;

    partial void OnSelectedChanged(AcademyEntry? value)
    {
        // The release arm survives re-picking the SAME lad (right-click selects before it opens);
        // anyone else, or nobody, disarms it.
        if (value is null || value.PlayerId != _armedRelease) _armedRelease = null;
    }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(PromoteYouthCommand))]
    private YouthEntry? _selectedYouth;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowAcademyEmpty))]
    private bool _hasProspects;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowYouthEmpty))]
    private bool _hasYouth;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasNote))]
    private string _note = "";

    public bool HasNote => Note.Length > 0;

    [ObservableProperty]
    private string _status = "";

    // ── the three-tab strip: academy intake, then the two sides beneath the first team ──

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsAcademyTab))]
    [NotifyPropertyChangedFor(nameof(IsU21Tab))]
    [NotifyPropertyChangedFor(nameof(IsU18Tab))]
    [NotifyPropertyChangedFor(nameof(IsYouthTab))]
    [NotifyPropertyChangedFor(nameof(ShowAcademyEmpty))]
    [NotifyPropertyChangedFor(nameof(ShowYouthEmpty))]
    private string _tab = "academy";

    public bool IsAcademyTab => Tab == "academy";
    public bool IsU21Tab => Tab == "u21";
    public bool IsU18Tab => Tab == "u18";
    public bool IsYouthTab => !IsAcademyTab;
    public bool ShowAcademyEmpty => IsAcademyTab && !HasProspects;
    public bool ShowYouthEmpty => IsYouthTab && !HasYouth;

    [RelayCommand]
    private void SelectTab(string? kind)
    {
        Tab = kind == "u21" ? "u21" : kind == "u18" ? "u18" : "academy";
        Status = "";
        if (IsAcademyTab) Reload(); else LoadYouth();
    }

    [RelayCommand]
    private void OpenCalendar() => Nav.Go("Calendar");

    // ── promotion (the buttons; the menus below carry the same verbs) ───────────────

    // P6: the button is DISABLED until a prospect is picked — no more silent no-op.
    private bool CanPromote() => Selected is not null;

    [RelayCommand(CanExecute = nameof(CanPromote))]
    private void Promote()
    {
        if (Selected is null) return;   // belt-and-braces; CanExecute already gates this
        Status = $"{Selected.Name}: {_s.PromoteAcademy(Selected.PlayerId)}";
        Reload();
    }

    private bool CanPromoteYouth() => SelectedYouth is not null;

    [RelayCommand(CanExecute = nameof(CanPromoteYouth))]
    private void PromoteYouth()
    {
        if (SelectedYouth is null) return;
        Status = _s.PromoteToSenior(SelectedYouth.PlayerId, _s.CurrentTeamId);
        LoadYouth();
    }

    // ── right-click menus ──────────────────────────────────────────────────────────
    // Hand-built rather than the shared player menu: a prospect is neither a squad player
    // (no contract, no armband, no transfer list) nor a market free agent (he's already
    // yours). The Ml chrome is the same — ContextMenu styling lives in Theme.axaml.

    /// <summary>Menu for an academy prospect.</summary>
    public ContextMenu? MenuFor(AcademyEntry r)
    {
        var menu = new ContextMenu();
        var scoutBusy = _s.ActiveScoutJob() is not null;
        var noScout = _s.StaffFor("Scout") is null;

        menu.Items.Add(Info($"{r.Name} · {r.Position}, {r.Age} · your academy"));
        menu.Items.Add(new Separator());
        menu.Items.Add(Leaf("⬆ Promote to senior",
            () => { Status = $"{r.Name}: {_s.PromoteAcademy(r.PlayerId)}"; Reload(); }));
        menu.Items.Add(ScoutLeaf(r.PlayerId, r.Name, noScout, scoutBusy));
        menu.Items.Add(Leaf("🧪 Offer trial", () => Status = _s.TrialPlayer(r.PlayerId)));

        // extras: the one destructive verb, armed then fired — this app has no dialogs.
        menu.Items.Add(new Separator());
        var armed = _armedRelease == r.PlayerId;
        menu.Items.Add(Leaf(armed ? $"⛔ Sure? Release {r.Name}" : "⛔ Release prospect", () =>
        {
            if (_armedRelease == r.PlayerId)
            {
                _armedRelease = null;
                Status = _s.ReleaseProspect(r.PlayerId);
                Reload();
            }
            else
            {
                _armedRelease = r.PlayerId;
                Status = $"Release {r.Name}? He leaves without a senior deal and you cannot " +
                         "get him back — right-click him again to confirm.";
            }
        }));
        return menu;
    }

    /// <summary>Menu for a lad on the U21/U18 side.</summary>
    public ContextMenu? MenuForYouth(YouthEntry r)
    {
        var menu = new ContextMenu();
        var scoutBusy = _s.ActiveScoutJob() is not null;
        var noScout = _s.StaffFor("Scout") is null;
        var free = _s.ClubOfPlayer(r.PlayerId).TeamId is null;

        menu.Items.Add(Info($"{r.Name} · {r.Position}, {r.Age} · {r.Level}"));
        menu.Items.Add(new Separator());
        menu.Items.Add(Leaf("⬆ Promote to first team",
            () => { Status = _s.PromoteToSenior(r.PlayerId, _s.CurrentTeamId); LoadYouth(); }));
        if (r.Level == "U21")
        {
            menu.Items.Add(Leaf("⬇ Move to U18s",
                () => { Status = _s.DemoteToYouth(r.PlayerId, _s.CurrentTeamId, "u18"); LoadYouth(); }));
        }
        menu.Items.Add(new Separator());
        menu.Items.Add(ScoutLeaf(r.PlayerId, r.Name, noScout, scoutBusy));
        // A trial is how you look at someone who ISN'T yours; he already is. Shown, and
        // shown why it's shut, rather than quietly missing.
        menu.Items.Add(Leaf(free ? "🧪 Offer trial" : "🧪 Offer trial — already on your books",
            () => Status = _s.TrialPlayer(r.PlayerId), free));
        return menu;
    }

    private MenuItem ScoutLeaf(long id, string name, bool noScout, bool scoutBusy) =>
        Leaf(noScout ? "🔍 Scout prospect — needs a scout"
             : scoutBusy ? "🔍 Scout prospect — scout on a mission"
             : "🔍 Scout prospect",
            () => Status = _s.StartScoutJob("player", id, name), !noScout && !scoutBusy);

    private static MenuItem Info(string header) => new() { Header = header, IsEnabled = false };

    /// <summary>Menu leaf with the same honesty contract as EntityActions: a thrown verb
    /// reports itself on the status line instead of taking the app down.</summary>
    private MenuItem Leaf(string header, Action act, bool enabled = true)
    {
        var mi = new MenuItem { Header = header, IsEnabled = enabled };
        mi.Click += (_, _) =>
        {
            try { act(); }
            catch (Exception ex) { Status = ex.Message; }
        };
        return mi;
    }
}
