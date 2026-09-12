using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Training (weekly development: ability groups, new positions, player skills) ---

public sealed record TrainingRow(
    long PlayerId, string Name, string Position, int Age, int Rating, IBrush RatingBrush,
    string Focus, string Progress, string Personality, int Determination, string Skills)
{
    public string Grade => ML.Core.Development.AttributeKnowledge.Grade(Rating);   // own squad

    /// <summary>Name-cell tooltip: the two traits that decide how fast he learns anything.</summary>
    public string Who => $"{Personality} · determination {Determination}/20";

    /// <summary>Skills-cell tooltip: the full list, un-truncated by the column width.</summary>
    public string SkillsTip => Skills is "—" or "" ? "No skills yet." : Skills;
}

/// <summary>A line on the training pitch. Keeps the player id so the line is clickable
/// (select his row) and callable-off (the ✕) — a readout you can act on, not just read.</summary>
public sealed record SkillProgressRow(long PlayerId, string Line);

public sealed partial class TrainingViewModel : PageViewModel, IFocusTarget
{
    private readonly Session _s;

    public TrainingViewModel(Session s)
    {
        _s = s;
        foreach (var g in Session.TrainingGroups.Keys) FocusOptions.Add(g);
        // The game's hard rule: GK and outfield never mix — nobody trains INTO goal.
        foreach (var p in TacticsViewModel.AllPositions.Where(p => p != "GK"))
        {
            FocusOptions.Add($"Learn {p}");
        }
        FocusOptions.Add("None");
        Reload();
        if (s.LastTrainingNotes.Count > 0)
        {
            Status = string.Join("  ·  ", s.LastTrainingNotes);
        }
    }

    private void Reload()
    {
        Rows.Clear();
        foreach (var (player, _) in _s.Squad().OrderByDescending(x => x.Player.OverallRating ?? 0))
        {
            var (focus, progress) = _s.TrainingOf(player.Id);
            var focusLabel = focus is null ? "—"
                : focus.StartsWith("pos:") ? $"Learn {focus[4..]}" : focus;
            var progressLabel = focus is null ? ""
                : focus.StartsWith("pos:") ? $"{Math.Min(progress, Session.PositionSessions)}/{Session.PositionSessions}"
                : $"{progress} wks";
            var learned = _s.LearnedPositions(player.Id);
            var pos = learned.Count > 0 ? $"{player.Position} (+{string.Join(",", learned)})" : player.Position;
            var (det, _, _, _) = _s.TraitsOf(player.Id);
            var skills = _s.SkillsOf(player.Id);
            Rows.Add(new TrainingRow(player.Id, player.Name, pos, player.Age ?? 0,
                player.OverallRating ?? 0, Visuals.RatingBrush(player.OverallRating ?? 0),
                focusLabel, progressLabel, _s.PersonalityOf(player.Id), det,
                skills.Count > 0 ? string.Join(", ", skills) : "—"));
        }
        SkillWork.Clear();
        foreach (var t in _s.ActiveSkillTrainings())
        {
            SkillWork.Add(new SkillProgressRow(t.PlayerId,
                $"{t.Player} — {t.Skill}  ({t.Progress}/{t.Target} wks)"));
        }
        HasSkillWork = SkillWork.Count > 0;
    }

    public override string Title => "Training";
    public override string Icon => "🎯";
    public ObservableCollection<TrainingRow> Rows { get; } = new();
    public ObservableCollection<string> FocusOptions { get; } = new();

    // Skill training (P1): pick a player, see what he can still learn, put him to work.
    public ObservableCollection<string> LearnableSkills { get; } = new();
    public ObservableCollection<SkillProgressRow> SkillWork { get; } = new();
    [ObservableProperty] private bool _hasSkillWork;
    [ObservableProperty] private string? _selectedSkill;
    [ObservableProperty] private string _skillNote = "";

    [ObservableProperty] private TrainingRow? _selected;
    [ObservableProperty] private string? _selectedFocus;

    partial void OnSelectedChanged(TrainingRow? value)
    {
        LearnableSkills.Clear();
        SelectedSkill = null;
        if (value is null) { SkillNote = ""; return; }
        var learnable = _s.LearnableSkillsFor(value.PlayerId);
        foreach (var sk in learnable) LearnableSkills.Add(sk);
        SkillNote = learnable.Count == 0
            ? $"{value.Name} ({value.Personality}, determination {value.Determination}/20) has no " +
              "skills left to learn — flair skills are innate, and veterans stop learning."
            : $"{value.Name} — {value.Personality}, determination {value.Determination}/20. " +
              $"{learnable.Count} skill(s) within reach; the driven learn in fewer weeks.";
    }

    [RelayCommand]
    private void StartSkill()
    {
        if (Selected is null || SelectedSkill is null)
        {
            SkillNote = "Pick a player and a skill first.";
            return;
        }
        SkillNote = _s.StartSkillTraining(Selected.PlayerId, SelectedSkill);
        Reload();
    }

    [ObservableProperty]
    private string _status = "Assign each player a weekly focus. Ability work nudges the REAL " +
                             "attributes that compile into the game; position training unlocks a " +
                             "new position after 6 matchweeks. Young players develop fastest.";

    [RelayCommand]
    private void Assign()
    {
        if (Selected is null || SelectedFocus is null)
        {
            Status = "Pick a player and a focus first.";
            return;
        }
        ApplyFocus(Selected, SelectedFocus);
    }

    /// <summary>The ONE place a training focus is written. The toolbar combo and the
    /// right-click submenu both land here, so the GK rule and the status wording can
    /// never drift apart.</summary>
    private void ApplyFocus(TrainingRow row, string option)
    {
        if (option.StartsWith("Learn ") && row.Position.StartsWith("GK"))
        {
            Status = $"{row.Name} is a goalkeeper — keepers can't retrain outfield (the game's rule).";
            return;
        }
        var focus = option == "None" ? null
            : option.StartsWith("Learn ") ? $"pos:{option[6..]}"
            : option;
        _s.SetTraining(row.PlayerId, focus);
        Status = focus is null
            ? $"{row.Name}: training cleared."
            : $"{row.Name} now training {option} — progress ticks every recorded matchweek.";
        Reload();
    }

    // ── the training pitch readout: click a line, or call the work off ──────────────

    /// <summary>Clicking a skill-work line jumps to that player's row in the grid, where
    /// the focus combo and the skill list are already about him.</summary>
    [RelayCommand]
    private void FocusSkillPlayer(SkillProgressRow? row)
    {
        if (row is null) return;
        var target = Rows.FirstOrDefault(r => r.PlayerId == row.PlayerId);
        if (target is not null) Selected = target;
    }

    [RelayCommand]
    private void CancelSkill(SkillProgressRow? row)
    {
        if (row is null) return;
        Status = _s.CancelSkillTraining(row.PlayerId);
        Reload();
    }

    // ── the shared right-click menu, plus the four verbs that only live here ────────

    /// <summary>Every row on this screen is one of yours, so the shared own-player menu
    /// applies whole; training's own verbs ride in as extras.</summary>
    public ContextMenu? MenuFor(TrainingRow r)
    {
        var extras = new List<MenuItem>();

        // 🎯 Set focus ▸ — ability groups, a rule, then the positions he could learn.
        var groups = FocusOptions.Where(o => o != "None" && !o.StartsWith("Learn ")).ToList();
        var learns = FocusOptions.Where(o => o.StartsWith("Learn ")).ToList();
        var keeper = r.Position.StartsWith("GK");
        var focusItem = new MenuItem { Header = "🎯 Set focus" };
        foreach (var g in groups) focusItem.Items.Add(Leaf(g, () => ApplyFocus(r, g)));
        if (groups.Count > 0 && learns.Count > 0) focusItem.Items.Add(new Separator());
        foreach (var l in learns) focusItem.Items.Add(Leaf(l, () => ApplyFocus(r, l), !keeper));
        extras.Add(focusItem);

        // ✨ Start skill ▸ — only what the engine says is still within reach.
        var learnable = _s.LearnableSkillsFor(r.PlayerId);
        var skillItem = new MenuItem
        {
            Header = learnable.Count == 0 ? "✨ Start skill — nothing left to learn" : "✨ Start skill",
            IsEnabled = learnable.Count > 0,
        };
        foreach (var sk in learnable)
        {
            skillItem.Items.Add(Leaf(sk, () =>
            {
                Status = _s.StartSkillTraining(r.PlayerId, sk);
                Reload();
            }));
        }
        extras.Add(skillItem);

        extras.Add(Leaf("🛑 Clear training", () => ApplyFocus(r, "None"), r.Focus != "—"));

        var working = SkillWork.Any(w => w.PlayerId == r.PlayerId);
        extras.Add(Leaf(working ? "❌ Cancel skill training" : "❌ Cancel skill training — he isn't on one",
            () => { Status = _s.CancelSkillTraining(r.PlayerId); Reload(); }, working));

        return EntityActions.BuildMenu(_s, EntityRef.Player(r.PlayerId, r.Name),
            status: t => Status = t, refresh: Reload, extras: extras);
    }

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

    /// <summary>Where the shared menu's "🎯 Set training" lands: his row, selected, with the
    /// focus combo and skill list already loaded for him.</summary>
    public void Focus(EntityRef target)
    {
        if (target.Kind != EntityKind.Player) return;
        var row = Rows.FirstOrDefault(r => r.PlayerId == target.Id);
        if (row is null) return;
        Selected = row;
        Status = $"{row.Name} — pick a focus above, or right-click him for the whole menu.";
    }
}
