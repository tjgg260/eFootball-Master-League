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
    public string Grade => ML.Core.Development.StarRating.Text(Rating);   // your academy — full knowledge, always
}

/// <summary>A lad on one of the youth sides. Same read as a prospect — he's already yours,
/// so nothing is masked; what differs is where he can go next. Carries the SAME face fields
/// as a prospect: both grids draw the same row anatomy, so switching tabs no longer shuffles
/// every column sideways as the avatar appears and disappears.</summary>
public sealed record YouthEntry(
    long PlayerId, string Name, string Position, int Age, int Rating, IBrush RatingBrush,
    string Potential, string Level, string Readiness, IBrush FaceBrush,
    Avalonia.Media.Imaging.Bitmap? Portrait = null)
{
    public string Mark => Visuals.PlayerMark(Name);
    public bool HasPortrait => Portrait is not null;
    public string Grade => ML.Core.Development.StarRating.Text(Rating);   // your youth side — full knowledge, always
}

/// <summary>Your youth setup: this season's prospects and the U21/U18 sides beneath the first
/// team, with promotion, demotion and the scouting verbs on every lad.</summary>
public sealed partial class AcademyViewModel : PageViewModel
{
    private readonly Session _s;

    /// <summary>Which prospect the "release" verb is armed for. Destructive verbs are
    /// two-step, and the arm belongs to one lad only — selecting anyone else disarms it.</summary>
    private long? _armedRelease;

    /// <summary>Why the last youth read failed, empty when it didn't. A failure and an empty
    /// side are DIFFERENT things and the screen has to say which — see LoadYouth.</summary>
    private string _youthError = "";

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
        // THE BUG: this used to read `Note = HasProspects ? "…" : ""` — the explanation was
        // blanked in the one case where the manager has never seen the screen work and most
        // needs telling what it is. An empty list is a REASON to explain, not a reason to
        // go quiet. Both branches now say something true.
        Note = HasProspects
            ? "★ is the youth coach's read of each lad's real ceiling — development chases it. " +
              "Young players develop fastest before 24; promote them when a squad place opens."
            : "The academy is your own intake: one class of home-grown lads arrives each " +
              "close season, and ★ is the youth coach's read of how far each could go. " +
              "A prospect is promoted into the first team — from there you can send him down " +
              "to the U21s to keep developing.";
    }

    /// <summary>Load the U21 or U18 side for the tab currently showing.</summary>
    private void LoadYouth()
    {
        SelectedYouth = null;
        YouthRows.Clear();
        _youthError = "";
        var kind = IsU18Tab ? "u18" : "u21";
        var label = kind.ToUpperInvariant();
        try
        {
            foreach (var y in _s.YouthSquad(_s.CurrentTeamId, kind))
            {
                var stars = _s.PotentialStars(y.PlayerId);
                int? tone = null;
                Avalonia.Media.Imaging.Bitmap? face = null;
                try
                {
                    var por = _s.PortraitFor(y.PlayerId);
                    tone = por.SkinTone;
                    face = por.Image;
                }
                catch { /* a missing face never costs the row */ }
                YouthRows.Add(new YouthEntry(y.PlayerId, y.Name, y.Position, y.Age, y.Overall,
                    Visuals.RatingBrush(y.Overall), Stars(stars), y.Level,
                    ReadinessOf(y.Age, y.Overall, y.Potential, kind),
                    Visuals.SkinBrush(tone), face));
            }
        }
        catch (Exception ex)
        {
            // THE BUG: this was a bare `catch { }` with the comment "an older career simply
            // shows an empty side" — so a broken read and a genuinely empty side produced the
            // IDENTICAL screen, and the one that needs fixing looked like the one that needs
            // a signing. The failure now has its own state, its own words and the log line.
            _youthError = ex.Message;
            Program.Log("Academy.LoadYouth", ex);
        }
        HasYouth = YouthRows.Count > 0;
        YouthFailed = _youthError.Length > 0;

        if (YouthFailed)
        {
            // Rows may have been added before the throw — say so rather than pretend the list
            // in front of the manager is the whole side.
            Say(HasYouth
                ? $"Your {label} side is only part-read — the rest could not be loaded: {_youthError}"
                : $"Could not read your {label} side: {_youthError}", Tone.Bad);
            Note = $"This is not an empty {label} side — the read itself failed, so the list " +
                   "below may be short or blank. Nothing has been lost; the details are in " +
                   "ml-crash.log.";
            return;
        }

        // Same inversion as the academy tab: the empty side is exactly when a manager needs
        // telling what a U21 side IS and how a lad gets onto it.
        Note = HasYouth
            ? $"Your {label} side. Minutes here still develop a lad; minutes above him do it " +
              "faster — bring him up the moment he has outgrown the level."
            : $"Your {label}s are a real team beneath the first team, not a list: lads here age, " +
              $"train and develop every season. Anyone {(kind == "u18" ? 18 : 21)} or under can " +
              "be sent down from the first team, and comes back up whenever you want him.";
    }

    /// <summary>
    /// The youth coach's read of where a lad is at THIS level. The column this fills used to
    /// be "Level", which restated the tab — every row said U21 on the U21 tab. Age band comes
    /// first because a deadline beats an opinion: a lad at the top of the band leaves the level
    /// this season whatever his rating.
    /// </summary>
    private static string ReadinessOf(int age, int rating, int ceiling, string kind)
    {
        var bandTop = kind == "u18" ? 18 : 21;
        if (age >= bandTop) return "Last year here";
        return (ceiling - rating) switch
        {
            <= 2 => "Ready now",
            <= 6 => "Nearly there",
            _ => "One for later",
        };
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
    [NotifyPropertyChangedFor(nameof(ShowYouthError))]
    private bool _hasYouth;

    /// <summary>The youth read threw. Kept apart from "empty" so the screen never blames the
    /// manager for a fault of ours.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowYouthEmpty))]
    [NotifyPropertyChangedFor(nameof(ShowYouthError))]
    private bool _youthFailed;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasNote))]
    private string _note = "";

    public bool HasNote => Note.Length > 0;

    // ── the docked status line ─────────────────────────────────────────────────────
    // Same contract as the Player screen: the words come from the engine, only the COLOUR is
    // ours. A refusal used to read in the assistant's success green.

    private enum Tone { Info, Warn, Bad }

    [ObservableProperty]
    private string _status = "";

    [ObservableProperty]
    private IBrush _statusBrush = Visuals.Brush("#9FE6B4");   // MlSuccessText

    private void Say(string text, Tone tone = Tone.Info)
    {
        Status = text;
        StatusBrush = Visuals.Brush(tone switch
        {
            Tone.Warn => "#E0A526",   // MlWarn
            Tone.Bad => "#D64545",    // MlDanger
            _ => "#9FE6B4",           // MlSuccessText — the assistant voice
        });
    }

    /// <summary>
    /// Colour for an answer the ENGINE wrote. It returns prose, not a result code, so this is
    /// a best-effort read of the refusal shapes the youth verbs actually use ("Too old for the
    /// U18s.", "That prospect is no longer in the academy."). It only ever changes the colour,
    /// never the words: a miss shows a refusal in the neutral voice, and can never invent one.
    /// </summary>
    private static readonly string[] RefusalMarkers =
    {
        "too old", "no longer", "isn't", "already", "didn't", "cannot", "can't", "needs a",
        "on a mission",
    };

    private static Tone ToneOfAnswer(string line) =>
        RefusalMarkers.Any(m => line.Contains(m, StringComparison.OrdinalIgnoreCase))
            ? Tone.Warn
            : Tone.Info;

    // ── the three-tab strip: academy intake, then the two sides beneath the first team ──

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsAcademyTab))]
    [NotifyPropertyChangedFor(nameof(IsU21Tab))]
    [NotifyPropertyChangedFor(nameof(IsU18Tab))]
    [NotifyPropertyChangedFor(nameof(IsYouthTab))]
    [NotifyPropertyChangedFor(nameof(ShowAcademyEmpty))]
    [NotifyPropertyChangedFor(nameof(ShowYouthEmpty))]
    [NotifyPropertyChangedFor(nameof(ShowYouthError))]
    [NotifyPropertyChangedFor(nameof(SendDownLabel))]
    [NotifyPropertyChangedFor(nameof(SendDownHint))]
    private string _tab = "academy";

    public bool IsAcademyTab => Tab == "academy";
    public bool IsU21Tab => Tab == "u21";
    public bool IsU18Tab => Tab == "u18";
    public bool IsYouthTab => !IsAcademyTab;
    public bool ShowAcademyEmpty => IsAcademyTab && !HasProspects;
    public bool ShowYouthEmpty => IsYouthTab && !HasYouth && !YouthFailed;
    public bool ShowYouthError => IsYouthTab && YouthFailed;

    /// <summary>
    /// The visible affordance for the verb the empty state used to only TALK about ("send a
    /// young first-teamer down") — there was no such control anywhere on this screen, so the
    /// advice read as the manager's fault. The button is a signpost, not a lie: it opens the
    /// squad, which is where the verb lives, and SendDownHint says exactly that.
    /// </summary>
    public string SendDownLabel =>
        IsU18Tab ? "⬇ Send an under-18 down" : "⬇ Send an under-21 down";

    /// <summary>What the button will actually do, and the age gate DemoteToYouth enforces
    /// for this level — so nobody clicks it expecting a picker.</summary>
    public string SendDownHint =>
        IsU18Tab
            ? "Opens your squad: right-click anyone 18 or under and send him to the U18s. " +
              "He comes back up whenever you want him."
            : "Opens your squad: right-click anyone 21 or under and send him to the U21s. " +
              "He comes back up whenever you want him.";

    [RelayCommand]
    private void SelectTab(string? kind)
    {
        Tab = kind == "u21" ? "u21" : kind == "u18" ? "u18" : "academy";
        Say("");   // clears the WORDS and the tone — a bare `Status = ""` left the last colour on
        if (IsAcademyTab) { YouthFailed = false; Reload(); } else LoadYouth();
    }

    [RelayCommand]
    private void OpenCalendar() => Nav.Go("Calendar");

    /// <summary>The squad screen, where every player's menu carries "Move to U21s/U18s".
    /// Honest about being a signpost: this screen cannot pick a first-teamer for you.</summary>
    [RelayCommand]
    private void OpenSquad() => Nav.Go("Squad");

    // ── promotion (the buttons; the menus below carry the same verbs) ───────────────

    // P6: the button is DISABLED until a prospect is picked — no more silent no-op.
    private bool CanPromote() => Selected is not null;

    [RelayCommand(CanExecute = nameof(CanPromote))]
    private void Promote()
    {
        if (Selected is null) return;   // belt-and-braces; CanExecute already gates this
        var line = $"{Selected.Name}: {_s.PromoteAcademy(Selected.PlayerId)}";
        Say(line, ToneOfAnswer(line));
        Reload();
    }

    private bool CanPromoteYouth() => SelectedYouth is not null;

    [RelayCommand(CanExecute = nameof(CanPromoteYouth))]
    private void PromoteYouth()
    {
        if (SelectedYouth is null) return;
        var line = _s.PromoteToSenior(SelectedYouth.PlayerId, _s.CurrentTeamId);
        Say(line, ToneOfAnswer(line));
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
            () => { var l = $"{r.Name}: {_s.PromoteAcademy(r.PlayerId)}"; Say(l, ToneOfAnswer(l)); Reload(); }));
        menu.Items.Add(ScoutLeaf(r.PlayerId, r.Name, noScout, scoutBusy));
        menu.Items.Add(Leaf("🧪 Offer trial",
            () => { var l = _s.TrialPlayer(r.PlayerId); Say(l, ToneOfAnswer(l)); }));

        // extras: the one destructive verb, armed then fired — this app has no dialogs.
        menu.Items.Add(new Separator());
        var armed = _armedRelease == r.PlayerId;
        menu.Items.Add(Leaf(armed ? $"⛔ Sure? Release {r.Name}" : "⛔ Release prospect", () =>
        {
            if (_armedRelease == r.PlayerId)
            {
                _armedRelease = null;
                Say(_s.ReleaseProspect(r.PlayerId), Tone.Warn);
                Reload();
            }
            else
            {
                _armedRelease = r.PlayerId;
                Say($"Release {r.Name}? He leaves without a senior deal and you cannot " +
                    "get him back — right-click him again to confirm.", Tone.Warn);
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
        var u21 = r.Level == "U21";

        menu.Items.Add(Info($"{r.Name} · {r.Position}, {r.Age} · {r.Level}"));
        menu.Items.Add(new Separator());
        menu.Items.Add(Leaf("⬆ Promote to first team",
            () => { var l = _s.PromoteToSenior(r.PlayerId, _s.CurrentTeamId); Say(l, ToneOfAnswer(l)); LoadYouth(); }));
        if (u21)
        {
            // "Move to U18s" is only legal for a lad of 18 or under — DemoteToYouth refuses the
            // rest with "Too old for the U18s.". Shown, and shown WHY it's shut, rather than
            // firing a refusal the manager could have been spared.
            var canDrop = r.Age <= 18;
            menu.Items.Add(Leaf(canDrop ? "⬇ Move down to the U18s" : "⬇ Move down to the U18s — too old",
                () => { var l = _s.DemoteToYouth(r.PlayerId, _s.CurrentTeamId, "u18"); Say(l, ToneOfAnswer(l)); LoadYouth(); },
                canDrop));
        }
        else
        {
            // THE BUG: a U18 lad could jump straight to the first team but had no way UP to the
            // U21s — the rung between them was missing from the menu though DemoteToYouth has
            // always accepted "u21". A lad on the U18 side is 18 or under, so this is always
            // legal (the age gate there is 21).
            menu.Items.Add(Leaf("⬆ Move up to the U21s",
                () => { var l = _s.DemoteToYouth(r.PlayerId, _s.CurrentTeamId, "u21"); Say(l, ToneOfAnswer(l)); LoadYouth(); }));
        }
        menu.Items.Add(new Separator());
        menu.Items.Add(ScoutLeaf(r.PlayerId, r.Name, noScout, scoutBusy));
        // A trial is how you look at someone who ISN'T yours; he already is. Shown, and
        // shown why it's shut, rather than quietly missing.
        menu.Items.Add(Leaf(free ? "🧪 Offer trial" : "🧪 Offer trial — already on your books",
            () => { var l = _s.TrialPlayer(r.PlayerId); Say(l, ToneOfAnswer(l)); }, free));
        return menu;
    }

    private MenuItem ScoutLeaf(long id, string name, bool noScout, bool scoutBusy) =>
        Leaf(noScout ? "🔍 Scout prospect — needs a scout"
             : scoutBusy ? "🔍 Scout prospect — scout on a mission"
             : "🔍 Scout prospect",
            () => { var l = _s.StartScoutJob("player", id, name); Say(l, ToneOfAnswer(l)); },
            !noScout && !scoutBusy);

    private static MenuItem Info(string header) => new() { Header = header, IsEnabled = false };

    /// <summary>Menu leaf with the same honesty contract as EntityActions: a thrown verb
    /// reports itself on the status line instead of taking the app down.</summary>
    private MenuItem Leaf(string header, Action act, bool enabled = true)
    {
        var mi = new MenuItem { Header = header, IsEnabled = enabled };
        mi.Click += (_, _) =>
        {
            try { act(); }
            catch (Exception ex) { Say(ex.Message, Tone.Bad); }
        };
        return mi;
    }
}
