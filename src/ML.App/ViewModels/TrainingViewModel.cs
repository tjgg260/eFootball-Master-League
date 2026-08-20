using System.Collections.ObjectModel;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

// --- Training (weekly development: ability groups, new positions, player skills) ---

public sealed record TrainingRow(
    int PlayerId, string Name, string Position, int Age, int Rating, IBrush RatingBrush,
    string Focus, string Progress, string Personality, int Determination, string Skills);

public sealed record SkillProgressRow(string Line);

public sealed partial class TrainingViewModel : PageViewModel
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
            SkillWork.Add(new SkillProgressRow($"{t.Player} — {t.Skill}  ({t.Progress}/{t.Target} wks)"));
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
        if (SelectedFocus.StartsWith("Learn ") && Selected.Position.StartsWith("GK"))
        {
            Status = $"{Selected.Name} is a goalkeeper — keepers can't retrain outfield (the game's rule).";
            return;
        }
        var focus = SelectedFocus == "None" ? null
            : SelectedFocus.StartsWith("Learn ") ? $"pos:{SelectedFocus[6..]}"
            : SelectedFocus;
        _s.SetTraining(Selected.PlayerId, focus);
        Status = focus is null
            ? $"{Selected.Name}: training cleared."
            : $"{Selected.Name} now training {SelectedFocus} — progress ticks every recorded matchweek.";
        Reload();
    }
}
