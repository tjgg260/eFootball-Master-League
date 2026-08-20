using System.Collections.ObjectModel;
using Avalonia;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Dapper;

namespace ML.App.ViewModels;

// --- Squad (master-detail: roster grid + eFootball-style player card) -------------

/// <summary>
/// One roster row. Carries everything the card header needs so selecting a player only fetches
/// abilities. Condition defaults (fatigue 0, no injury) cover squads with no player_condition
/// rows yet — a fresh career reads as fully fit.
/// </summary>
public sealed record SquadEntry
{
    public int PlayerId { get; init; }
    public int Number { get; init; }
    public string Name { get; init; } = "";
    public string Position { get; init; } = "";
    public int Age { get; init; }
    public int Rating { get; init; }
    public string Playstyle { get; init; } = "Basic";
    public int Fatigue { get; init; }
    public int? InjuredUntil { get; init; }
    public int Morale { get; init; } = 50;

    public string MoraleFace => Morale >= 75 ? "😀" : Morale >= 60 ? "🙂" : Morale >= 40 ? "😐"
        : Morale >= 25 ? "🙁" : "😡";
    public string MoraleLabel => ML.Core.Selection.MoraleModel.Label(Morale);
    public int? HeightCm { get; init; }
    public int? WeightKg { get; init; }
    public Bitmap? Portrait { get; init; }
    public string Mark { get; init; } = "";
    public IBrush MarkBrush { get; init; } = CondGreen;

    public IBrush RatingBrush => Visuals.RatingBrush(Rating);
    public IBrush ConditionBrush => Fatigue < 20 ? CondGreen : Fatigue < 40 ? CondAmber : CondRed;
    public bool IsInjured => InjuredUntil is not null;
    public string HeightDisplay => HeightCm is > 0 ? $"{HeightCm} cm" : "—";
    public string WeightDisplay => WeightKg is > 0 ? $"{WeightKg} kg" : "—";
    public string AgeDisplay => Age > 0 ? Age.ToString() : "—";

    private static readonly IBrush CondGreen = new SolidColorBrush(Color.Parse("#1F9D4D"));
    private static readonly IBrush CondAmber = new SolidColorBrush(Color.Parse("#E0A526"));
    private static readonly IBrush CondRed = new SolidColorBrush(Color.Parse("#D64545"));
}

/// <summary>One line of the card's Ability list, value coloured like an in-game rating.</summary>
public sealed record AbilityEntry(
    string Name, string Display, IBrush ValueBrush, IBrush BandBrush, bool ShowBand);

/// <summary>The player-card visual maths, shared by the Squad card and the Market profile.</summary>
public static class PlayerCard
{
    /// <summary>
    /// Hexagon radar vertices on the 200x200 card canvas: centre (100,100), axis k at angle
    /// k*60-90 deg, radius 78 spanning ability 40 (centre) to 99 (outer gridline).
    /// </summary>
    public static Points BuildRadarPoints((string Label, double Value)[] axes)
    {
        var pts = new Points();
        for (var k = 0; k < axes.Length; k++)
        {
            var radius = 78.0 * (Math.Clamp(axes[k].Value, 40.0, 99.0) - 40.0) / 59.0;
            var angle = (k * 60 - 90) * Math.PI / 180.0;
            pts.Add(new Point(100 + radius * Math.Cos(angle), 100 + radius * Math.Sin(angle)));
        }
        return pts;
    }

    // Rows a pure outfielder never uses; hidden from a GK's list alongside their gk_* priority.
    private static readonly string[] PureAttack = { "finishing", "offensive_awareness" };

    // The FM colour bands: poor / average / good / elite.
    private static readonly IBrush[] BandBrushes =
    {
        Visuals.Brush("#E05545"), Visuals.Brush("#E0A526"),
        Visuals.Brush("#8BE04A"), Visuals.Brush("#38B6FF"),
    };
    private static readonly IBrush MaskedBrush = Visuals.Brush("#3A4453");

    /// <summary>
    /// Ability rows for the card. Numbers mode shows the raw value; FM mode (P5) shows a
    /// colour band instead — and only for attributes your knowledge of the player has
    /// revealed. Unrevealed attributes show a dash in BOTH modes' FM variant.
    /// </summary>
    public static IReadOnlyList<AbilityEntry> BuildAbilityList(
        IReadOnlyDictionary<string, int> abilities, bool isGk,
        bool fmMode = false, int knowledge = 100, int playerId = 0)
    {
        var rows = isGk
            ? abilities.Where(a => a.Key.StartsWith("gk_")).OrderBy(a => a.Key)
                .Concat(abilities
                    .Where(a => !a.Key.StartsWith("gk_") && !PureAttack.Contains(a.Key))
                    .OrderBy(a => a.Key))
            : abilities.Where(a => !a.Key.StartsWith("gk_")).OrderBy(a => a.Key);
        return rows.Select(a =>
        {
            if (!fmMode)
            {
                return new AbilityEntry(TitleCase(a.Key), a.Value.ToString(),
                    Visuals.RatingBrush(a.Value), MaskedBrush, false);
            }
            var revealed = ML.Core.Development.AttributeKnowledge.IsRevealed(playerId, a.Key, knowledge);
            return revealed
                ? new AbilityEntry(TitleCase(a.Key), "", MaskedBrush,
                    BandBrushes[ML.Core.Development.AttributeKnowledge.Band(a.Value)], true)
                : new AbilityEntry(TitleCase(a.Key), "—", MaskedBrush, MaskedBrush, false);
        }).ToList();
    }

    /// <summary>snake_case attribute key → display name: "offensive_awareness" → "Offensive Awareness".</summary>
    public static string TitleCase(string snake) =>
        string.Join(' ', snake.Split('_', StringSplitOptions.RemoveEmptyEntries)
            .Select(w => w == "gk" ? "GK" : char.ToUpperInvariant(w[0]) + w[1..]));
}

public sealed record LoanRowVm(int PlayerId, string Line, bool IsOut);

public sealed partial class SquadViewModel : PageViewModel
{
    private readonly Session _s;

    public SquadViewModel(Session s)
    {
        _s = s;
        _fmMode = s.FmAttributeMode;   // backing field: no rebuild side-effect during ctor

        // One query for the whole roster: playstyle + condition joined in. player_condition may
        // hold no rows yet (COALESCE covers it); playstyle via subquery so a player with several
        // stored styles can never duplicate a roster row.
        var rows = s.Db.Connection.Query<SquadRowDto>(
            """
            SELECT s.player_id PlayerId, s.squad_number Number, p.name Name, p.position Position,
                   COALESCE(p.age,0) Age, COALESCE(p.overall_rating,0) Rating,
                   p.height_cm HeightCm, p.weight_kg WeightKg, p.portrait_path PortraitPath,
                   (SELECT playstyle FROM player_playstyles WHERE player_id=s.player_id LIMIT 1) Playstyle,
                   COALESCE(c.fatigue,0) Fatigue, c.injured_until_md InjuredUntil,
                   COALESCE(m.value,50) Morale
            FROM squad_members s
            JOIN players p ON p.id=s.player_id
            LEFT JOIN player_condition c ON c.player_id=s.player_id
            LEFT JOIN morale m ON m.player_id=s.player_id
            WHERE s.team_id=@teamId
            ORDER BY s.slot
            """, new { teamId = s.CurrentTeamId });

        var md = 0;
        try { md = s.NextFixture()?.Matchday ?? 0; } catch { }
        foreach (var r in rows)
        {
            _all.Add(new SquadEntry
            {
                PlayerId = r.PlayerId,
                Number = r.Number,
                Name = r.Name,
                Position = r.Position,
                Age = r.Age,
                Rating = r.Rating,
                Playstyle = string.IsNullOrWhiteSpace(r.Playstyle) ? "Basic" : r.Playstyle,
                Fatigue = r.Fatigue,
                InjuredUntil = r.InjuredUntil,
                Morale = r.Morale,
                HeightCm = r.HeightCm,
                WeightKg = r.WeightKg,
                Portrait = Visuals.LoadBitmap(r.PortraitPath),
                Mark = Visuals.PlayerMark(r.Name),
                MarkBrush = Visuals.PositionBrush(r.Position),
            });
        }
        _nextMd = md;
        ApplyFilter();
        Selected = Rows.FirstOrDefault();
        ReloadLoans();
    }

    public override string Title => "Squad";
    public override string Icon => "👥";

    public ObservableCollection<SquadEntry> Rows { get; } = new();

    // --- roster search + filter chips (P6 UX): find the player you mean, fast ----------

    private readonly List<SquadEntry> _all = new();
    private readonly int _nextMd;

    public IReadOnlyList<string> FilterChips { get; } =
        new[] { "All", "GK", "DEF", "MID", "FWD", "Injured", "Tired", "Unhappy", "Listed" };

    [ObservableProperty] private string _squadSearch = "";
    [ObservableProperty] private string _activeChip = "All";

    partial void OnSquadSearchChanged(string value) => ApplyFilter();
    partial void OnActiveChipChanged(string value) => ApplyFilter();

    [RelayCommand] private void SetChip(string chip) => ActiveChip = chip;

    // Loans (P-next): out from the card, recalls from the loans strip.
    public ObservableCollection<LoanRowVm> Loans { get; } = new();
    public bool HasLoans => Loans.Count > 0;

    private void ReloadLoans()
    {
        Loans.Clear();
        try
        {
            foreach (var l in _s.ActiveLoans())
            {
                var line = l.Direction == "out"
                    ? $"{l.Player} → {l.OtherClub} (until June)"
                    : $"{l.Player} — on loan from {l.OtherClub}";
                Loans.Add(new LoanRowVm(l.PlayerId, line, l.Direction == "out"));
            }
        }
        catch { /* loans are additive */ }
        OnPropertyChanged(nameof(HasLoans));
    }

    [RelayCommand]
    private void LoanOut()
    {
        if (Selected is null) return;
        var pid = Selected.PlayerId;
        SquadStatus = _s.LoanOut(pid);
        // If the loan went through he's no longer in the squad — drop the row.
        if (!_s.Repo.Squad(_s.CurrentTeamId).Any(m => m.PlayerId == pid))
        {
            _all.RemoveAll(e => e.PlayerId == pid);
            ApplyFilter();
            Selected = Rows.FirstOrDefault();
        }
        ReloadLoans();
    }

    [RelayCommand]
    private void RecallLoan(LoanRowVm loan)
    {
        SquadStatus = _s.RecallLoan(loan.PlayerId);
        ReloadLoans();
    }

    private void ApplyFilter()
    {
        var q = SquadSearch?.Trim() ?? "";
        IEnumerable<SquadEntry> set = _all;
        set = ActiveChip switch
        {
            "GK" => set.Where(p => p.Position == "GK"),
            "DEF" => set.Where(p => Visuals.PositionCategory(p.Position) == "DEF"),
            "MID" => set.Where(p => Visuals.PositionCategory(p.Position) == "MID"),
            "FWD" => set.Where(p => Visuals.PositionCategory(p.Position) == "FWD"),
            "Injured" => set.Where(p => p.InjuredUntil is { } u && u >= _nextMd),
            "Tired" => set.Where(p => p.Fatigue >= 40),
            "Unhappy" => set.Where(p => p.Morale < 40),
            "Listed" => set.Where(p => _s.IsTransferListed(p.PlayerId)),
            _ => set,
        };
        if (q.Length > 0)
        {
            set = set.Where(p => p.Name.Contains(q, StringComparison.OrdinalIgnoreCase));
        }
        Rows.Clear();
        foreach (var p in set) Rows.Add(p);
        if (Selected is null || !Rows.Contains(Selected)) Selected = Rows.FirstOrDefault();
    }

    [ObservableProperty] private SquadEntry? _selected;
    [ObservableProperty] private IReadOnlyList<AbilityEntry> _abilities = Array.Empty<AbilityEntry>();
    [ObservableProperty] private Points _radarPoints = new();

    // Season stats + contract + management state for the selected player.
    [ObservableProperty] private string _seasonLine = "";
    [ObservableProperty] private string _contractLine = "";
    [ObservableProperty] private bool _isCaptain;
    [ObservableProperty] private string _listLabel = "Transfer-list";
    [ObservableProperty] private string _squadStatus = "";

    // Compare: pin one player's radar, overlay the next selection's.
    [ObservableProperty] private Points _pinnedPoints = new();
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasPinned))]
    private string _pinnedName = "";
    public bool HasPinned => PinnedName.Length > 0;

    // Card data is computed lazily — only the selected player's abilities are ever queried.
    partial void OnSelectedChanged(SquadEntry? value)
    {
        if (value is null || value.PlayerId <= 0)
        {
            Abilities = Array.Empty<AbilityEntry>();
            RadarPoints = new Points();
            SeasonLine = "";
            ContractLine = "";
            return;
        }
        var abilities = _s.Repo.Attributes(value.PlayerId);
        var isGk = value.Position == "GK";
        RadarPoints = BuildRadarPoints(Visuals.RadarAxes(abilities, isGk));
        // Own squad = full knowledge; the FM toggle still swaps numbers for colour bands.
        Abilities = BuildAbilityList(abilities, isGk, FmMode, 100, value.PlayerId);
        try
        {
            CoachLines = _s.CoachReportOf(value.PlayerId, value.Position)
                .Select(l => "• " + l).ToList();
            AnalystLine = _s.AnalystLineOf(value.PlayerId);
        }
        catch { CoachLines = Array.Empty<string>(); AnalystLine = ""; }
        try
        {
            var (apps, goals, assists, yellows, reds, avg) = _s.PlayerSeasonStats(value.PlayerId);
            SeasonLine = $"{apps} apps · {goals} goals · {assists} assists · {yellows}🟨 {reds}🟥" +
                         (avg is { } a ? $" · {a:0.0} avg" : "");
            var learned = _s.LearnedPositions(value.PlayerId);
            ContractLine = $"Contract until {_s.ContractYear(value.PlayerId)}" +
                           (learned.Count > 0 ? $" · plays {string.Join("/", learned)} too" : "") +
                           (_s.IsTransferListed(value.PlayerId) ? " · LISTED" : "");
            IsCaptain = _s.Captain == value.PlayerId;
            ListLabel = _s.IsTransferListed(value.PlayerId) ? "Un-list" : "Transfer-list";
            PromiseLine = _s.PromiseLine(value.PlayerId);
            var (det, _, _, _) = _s.TraitsOf(value.PlayerId);
            CharacterLine = $"{_s.PersonalityOf(value.PlayerId)}  ·  Determination {det}/20";
            _syncingPt = true;
            var ptStatus = _s.PlayTimeStatusOf(value.PlayerId);
            SelectedPtStatus = ptStatus;
            _syncingPt = false;
            RefreshPlayTimeLine(value.PlayerId, ptStatus);
            var skills = _s.SkillsOf(value.PlayerId);
            SkillsLine = skills.Count > 0 ? $"Skills: {string.Join(", ", skills)}" : "";
            CareerRows = _s.PlayerCareerHistory(value.PlayerId)
                .Select(h => $"{h.Year}/{(h.Year + 1) % 100:00}  ·  {h.Club}  ·  {h.Apps} apps · " +
                             $"{h.Goals}g {h.Assists}a" + (h.AvgRating is { } a2 ? $" · {a2:0.0} avg" : ""))
                .ToList();
        }
        catch { SeasonLine = ""; ContractLine = ""; PromiseLine = ""; CareerRows = Array.Empty<string>(); }
    }

    // Character + skills for the card (P1).
    [ObservableProperty] private string _characterLine = "";
    [ObservableProperty] private string _skillsLine = "";

    // Playing time (P5, FM-style): status drives morale AND the AI's willingness to sell.
    public IReadOnlyList<string> PtStatusOptions => Session.PlayTimeStatuses;
    private bool _syncingPt;
    [ObservableProperty] private string? _selectedPtStatus;
    [ObservableProperty] private string _playTimeLine = "";

    partial void OnSelectedPtStatusChanged(string? value)
    {
        if (_syncingPt || value is null || Selected is null) return;
        SquadStatus = _s.SetPlayTimeStatus(Selected.PlayerId, value);
        RefreshPlayTimeLine(Selected.PlayerId, value);
    }

    private void RefreshPlayTimeLine(int playerId, string status)
    {
        try
        {
            var expected = Session.ExpectedStartsPer6(status);
            var md = _s.NextFixture()?.Matchday ?? 6;
            var actual = _s.StartsInLastSix(playerId, Math.Max(1, md - 1));
            PlayTimeLine = expected < 0
                ? $"No playing-time promise · started {actual} of the last 6"
                : $"Wants {expected} of every 6 starts · got {actual}" +
                  (actual < expected - 1 ? "  ⚠ unhappy" : actual >= expected ? "  ✓ content" : "");
        }
        catch { PlayTimeLine = ""; }
    }

    // FM display toggle + the permanent reports (P5).
    [ObservableProperty] private bool _fmMode;
    [ObservableProperty] private IReadOnlyList<string> _coachLines = Array.Empty<string>();
    public bool HasCoachLines => CoachLines.Count > 0;
    partial void OnCoachLinesChanged(IReadOnlyList<string> value) => OnPropertyChanged(nameof(HasCoachLines));
    [ObservableProperty] private string _analystLine = "";

    partial void OnFmModeChanged(bool value)
    {
        _s.FmAttributeMode = value;
        // Rebuild the card under the new display mode.
        var cur = Selected;
        Selected = null;
        Selected = cur;
    }

    // Season-by-season career lines for the card (D3).
    [ObservableProperty] private IReadOnlyList<string> _careerRows = Array.Empty<string>();
    public bool HasCareerRows => CareerRows.Count > 0;
    partial void OnCareerRowsChanged(IReadOnlyList<string> value) => OnPropertyChanged(nameof(HasCareerRows));

    [ObservableProperty] private string _promiseLine = "";

    // --- contract negotiation (B3): multi-round with the agent -----------------------
    [ObservableProperty] private bool _negotiating;
    [ObservableProperty] private decimal _wageOffer;
    [ObservableProperty] private string _selectedYears = "2";
    [ObservableProperty] private string _selectedStatus = "None";
    [ObservableProperty] private string _negotiationLine = "";
    private int _round = 1;

    public IReadOnlyList<string> YearsOptions { get; } = new[] { "1", "2", "3" };
    public IReadOnlyList<string> StatusOptions { get; } = new[] { "None", "Rotation", "First-team", "Star" };

    [RelayCommand]
    private void OpenNegotiation()
    {
        if (Selected is null) return;
        _round = 1;
        var (demand, line) = _s.ContractDemand(Selected.PlayerId, int.Parse(SelectedYears), SelectedStatus);
        WageOffer = demand;
        NegotiationLine = line;
        Negotiating = true;
    }

    [RelayCommand]
    private void MakeOffer()
    {
        if (Selected is null || !Negotiating) return;
        var (accepted, over, message) = _s.OfferContract(
            Selected.PlayerId, (long)WageOffer, int.Parse(SelectedYears), SelectedStatus, _round);
        NegotiationLine = message;
        if (over)
        {
            Negotiating = false;
            if (accepted)
            {
                ContractLine = $"Contract until {_s.ContractYear(Selected.PlayerId)}";
                PromiseLine = _s.PromiseLine(Selected.PlayerId);
            }
        }
        else
        {
            _round++;
        }
    }

    [RelayCommand]
    private void CancelNegotiation() => Negotiating = false;

    [RelayCommand]
    private void Praise()
    {
        if (Selected is null) return;
        SquadStatus = _s.TalkTo(Selected.PlayerId, Selected.Name, praise: true);
    }

    [RelayCommand]
    private void Criticise()
    {
        if (Selected is null) return;
        SquadStatus = _s.TalkTo(Selected.PlayerId, Selected.Name, praise: false);
    }

    [RelayCommand]
    private void PromiseStarts()
    {
        if (Selected is null) return;
        SquadStatus = _s.MakePromise(Selected.PlayerId, Selected.Name, "starts");
        PromiseLine = _s.PromiseLine(Selected.PlayerId);
    }

    [RelayCommand]
    private void PromiseContract()
    {
        if (Selected is null) return;
        SquadStatus = _s.MakePromise(Selected.PlayerId, Selected.Name, "contract");
        PromiseLine = _s.PromiseLine(Selected.PlayerId);
    }

    [RelayCommand]
    private void MakeCaptain()
    {
        if (Selected is null) return;
        _s.Captain = Selected.PlayerId;
        IsCaptain = true;
        SquadStatus = $"{Selected.Name} is your captain.";
    }

    [RelayCommand]
    private void ToggleList()
    {
        if (Selected is null) return;
        var now = !_s.IsTransferListed(Selected.PlayerId);
        _s.SetTransferListed(Selected.PlayerId, now);
        ListLabel = now ? "Un-list" : "Transfer-list";
        SquadStatus = now
            ? $"{Selected.Name} transfer-listed — offers are far more likely next window."
            : $"{Selected.Name} taken off the list.";
    }

    [RelayCommand]
    private void Release()
    {
        if (Selected is null) return;
        var name = Selected.Name;
        var msg = _s.ReleasePlayer(Selected.PlayerId);
        SquadStatus = $"{name}: {msg}";
        if (msg.StartsWith("Released"))
        {
            Rows.Remove(Selected);
            Selected = Rows.FirstOrDefault();
        }
    }

    [RelayCommand]
    private void Renew()
    {
        if (Selected is null) return;
        SquadStatus = _s.RenewContract(Selected.PlayerId);
        ContractLine = $"Contract until {_s.ContractYear(Selected.PlayerId)}";
    }

    [RelayCommand]
    private void PinCompare()
    {
        if (Selected is null) return;
        PinnedPoints = RadarPoints;
        PinnedName = Selected.Name;
        SquadStatus = $"{Selected.Name} pinned — select another player to compare radars.";
    }

    [RelayCommand]
    private void ClearCompare()
    {
        PinnedPoints = new Points();
        PinnedName = "";
    }

    private static Points BuildRadarPoints((string Label, double Value)[] axes) =>
        PlayerCard.BuildRadarPoints(axes);

    private static IReadOnlyList<AbilityEntry> BuildAbilityList(
        IReadOnlyDictionary<string, int> abilities, bool isGk,
        bool fmMode = false, int knowledge = 100, int playerId = 0) =>
        PlayerCard.BuildAbilityList(abilities, isGk, fmMode, knowledge, playerId);

    private sealed record SquadRowDto
    {
        public int PlayerId { get; init; }
        public int Number { get; init; }
        public string Name { get; init; } = "";
        public string Position { get; init; } = "";
        public int Age { get; init; }
        public int Rating { get; init; }
        public int? HeightCm { get; init; }
        public int? WeightKg { get; init; }
        public string? PortraitPath { get; init; }
        public string? Playstyle { get; init; }
        public int Fatigue { get; init; }
        public int? InjuredUntil { get; init; }
        public int Morale { get; init; }
    }
}
