using System.Collections.ObjectModel;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Core.Development;
using ML.Core.Selection;

namespace ML.App.ViewModels;

// ═══ THE PLAYER SCREEN ═══════════════════════════════════════════════════════════════
//
// One full-width profile for ANY player — yours, a rival's, a free agent. It supersedes the
// three cramped implementations the audit found (the Squad card in a 262px column, the Market
// profile pane, the Tactics rail), which is why nothing here lives in a narrow rail: the
// screen is a DockPanel whose body is three columns across the whole window, with the action
// bar docked at the top and the status line docked at the FOOT, outside every scroller.
//
// The rules this screen is built to keep:
//   · ABILITY is stars, never a letter or a number. Apps, goals, fees and wages are digits,
//     and that is correct — they are statistics, not a judgement of how good he is.
//   · Traits are WORDS. The engine stores 1–20; this app has never shown that number.
//   · Everything is knowledge-gated. An unscouted man reads as unscouted — one deliberate
//     card that says what is missing and how to fix it — never as blank or broken.
//   · Every verb answers on ONE docked line. On Squad the equivalent line sits 3.4 screens
//     below the fold, which is the whole reason the right-click menu felt broken.

/// <summary>
/// One verb from the shared right-click vocabulary, rendered as a VISIBLE button.
/// <para>
/// These are not a second list of actions: they ARE the menu. <see cref="EntityActions.BuildMenu"/>
/// builds it once and every MenuItem in it becomes one of these, whose command raises that
/// item's own Click. One vocabulary behind both affordances, so the button bar and the
/// right-click menu can never drift apart — including the guards, which EntityActions has
/// already evaluated (a blocked verb arrives disabled with its reason in the label, rather
/// than greyed out saying nothing).
/// </para>
/// </summary>
public sealed class PlayerActionVm
{
    public PlayerActionVm(string label, bool enabled, Action invoke)
    {
        Label = label;
        IsEnabled = enabled;
        Run = new RelayCommand(invoke, () => enabled);
    }

    public string Label { get; }
    public bool IsEnabled { get; }
    public RelayCommand Run { get; }
}

/// <summary>One personality trait, as a word. The 1–20 score never reaches the screen.</summary>
public sealed record PlayerTraitVm(string Name, string Word);

/// <summary>One season-statistics tile. Statistics are digits — abilities are not.</summary>
public sealed record PlayerStatTileVm(string Label, string Value);

/// <summary>One season of his career, as a row of the full-width history table.</summary>
public sealed record PlayerCareerRowVm(
    string Season, string Club, string Apps, string Goals, string Assists, string Avg);

public sealed partial class PlayerViewModel : PageViewModel, IFocusTarget
{
    /// <summary>The app-wide knowledge floor: below it we do not pretend to know a man.
    /// The Squad radar, the Market profile and the Tactics rail all mask at this same 45.</summary>
    private const int ScoutFloor = 45;

    /// <summary>The reputation at which this screen starts speaking about a man as KNOWN rather
    /// than unwatched. Roughly the top 2% of the world — below it, "nobody has watched him" is
    /// still the truth, and the old copy is still the right copy.</summary>
    private const int FameFloor = 20;

    /// <summary>This screen's own menu extras. Matching on these constants when the menu is
    /// projected into buttons is safe — they are ours, not EntityActions'.</summary>
    private const string BidHeader = "💷 Open bidding";
    private const string PromoteHeader = "⬆ Promote to first team";

    /// <summary>EntityActions' own "go to the profile screen" verb. On the profile screen it
    /// is a no-op, so it is dropped from the button bar (it stays in the menu, harmlessly).</summary>
    private const string ProfileHeader = "👤 View profile";

    private readonly Session _s;

    private long _id;
    private string _name = "";
    private string _club = "";
    private bool _mine;
    private bool _free;
    /// <summary>Everything you can see of him — scouting, proximity AND world reputation.</summary>
    private int _knowledge;
    /// <summary>What your club has actually earned. Reputation is deliberately NOT in here:
    /// being famous reveals a man's football, never his character or his ceiling.</summary>
    private int _scouted;
    /// <summary>His standing in the world, 0-100.</summary>
    private int _reputation;
    private bool _fm;
    /// <summary>"u21"/"u18" when he is in one of YOUR youth sides — the promote verb's guard.</summary>
    private string _youthKind = "";
    /// <summary>The menu's own title row, which this screen's header already is.</summary>
    private string _infoHeader = "";

    public PlayerViewModel(Session s)
    {
        _s = s;
        // Opened with no subject — from the sidebar, or replayed by Back before a focus ever
        // landed. An empty screen that says nothing looks broken, so it says what to do.
        ShowEmptyState();
    }

    public override string Title => "Player";
    public override string Icon => "👤";

    // ── subject ──────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Open on a man: Nav.Go("Player", EntityRef.Player(id, name)). A club (or anything else)
    /// is not a subject this screen can show, and says so rather than sitting empty.
    /// </summary>
    public void Focus(EntityRef target)
    {
        try
        {
            if (target.Kind != EntityKind.Player)
            {
                ShowEmptyState("That isn't a player. Open a club from the Squad screen — this " +
                               "screen is one man at a time.");
                return;
            }
            if (!Load(target.Id, target.Name)) return;
            Say(_mine
                ? $"{_name} — one of yours. Every action in the bar above works on him."
                : _free
                    ? $"{_name} is a free agent. Open bidding to put terms to him."
                    : $"{_name} of {_club}. Open bidding to put an offer to them.", Tone.Muted);
        }
        catch (Exception ex)
        {
            Program.Log("Player.Focus", ex);
            ShowEmptyState("Something went wrong opening that player.");
        }
    }

    /// <summary>
    /// Re-read the whole screen after a verb has changed something. It deliberately does NOT
    /// touch the status line: EntityActions runs the verb (which writes its answer there) and
    /// THEN calls this, so clearing it here would swallow every answer the menu gives.
    /// </summary>
    public void Reload()
    {
        if (_id > 0) Load(_id, _name);
    }

    private void ShowEmptyState(string? line = null)
    {
        _id = 0;
        _name = "";
        HasSubject = false;
        Actions.Clear();
        OnPropertyChanged(nameof(HasActions));
        EmptyLine = line ??
            "Right-click any name in the app and choose “View profile”, or " +
            "pick a man from your squad, the transfer market or a scouting report — his whole " +
            "profile, and everything you can do about him, opens here.";
        StatusLine = "";
    }

    [ObservableProperty] private bool _hasSubject;
    [ObservableProperty] private string _emptyLine = "";

    // ── identity ─────────────────────────────────────────────────────────────────────

    [ObservableProperty] private string _playerName = "";
    [ObservableProperty] private string _positionLabel = "";
    [ObservableProperty] private IBrush _positionBrush = Visuals.Brush("#3A4759");
    [ObservableProperty] private Bitmap? _portrait;
    [ObservableProperty] private bool _hasPortrait;
    [ObservableProperty] private string _mark = "";
    [ObservableProperty] private IBrush _markBrush = Visuals.Brush("#3A4759");
    [ObservableProperty] private string _nationality = "";
    [ObservableProperty] private Bitmap? _flag;
    [ObservableProperty] private bool _hasFlag;
    [ObservableProperty] private string _clubLine = "";
    [ObservableProperty] private Bitmap? _clubCrest;
    [ObservableProperty] private bool _hasClubCrest;
    [ObservableProperty] private string _ageDisplay = "—";
    [ObservableProperty] private string _heightDisplay = "—";
    [ObservableProperty] private string _weightDisplay = "—";

    /// <summary>The overall, as a LETTER, masked by what you know. Never the raw number.</summary>
    [ObservableProperty] private string _grade = "?";
    [ObservableProperty] private IBrush _gradeBrush = Visuals.Brush("#8A93A2");
    [ObservableProperty] private string _gradeTip = "";
    [ObservableProperty] private string _knowledgeLine = "";

    /// <summary>Scouted (or yours) — the gate on the dossier half of the screen.</summary>
    [ObservableProperty] private bool _isKnown;
    public bool IsUnknown => HasSubject && !IsKnown;
    partial void OnIsKnownChanged(bool value) => OnPropertyChanged(nameof(IsUnknown));
    [ObservableProperty] private string _unknownLine = "";

    /// <summary>The heading on the unscouted card. "NOT SCOUTED" is a lie about a man the whole
    /// game has an opinion on, so a famous player gets a heading that says what he actually is:
    /// known to the world, unknown to your staff.</summary>
    [ObservableProperty] private string _unknownHeading = "NOT SCOUTED";

    [ObservableProperty] private bool _isMine;
    [ObservableProperty] private bool _isFreeAgent;
    /// <summary>Anyone who is not yours: the bidding half of the screen is for these.</summary>
    public bool CanBid => HasSubject && !IsMine;
    partial void OnHasSubjectChanged(bool value)
    {
        OnPropertyChanged(nameof(CanBid));
        OnPropertyChanged(nameof(IsUnknown));
    }
    partial void OnIsMineChanged(bool value) => OnPropertyChanged(nameof(CanBid));

    // Status flags, as chips. Listed/loan-listed are keyed on YOUR club, so they only ever
    // light up for your own players; the shortlist is the one that matters for a rival's.
    [ObservableProperty] private bool _isTransferListed;
    [ObservableProperty] private bool _isLoanListed;
    [ObservableProperty] private bool _isShortlisted;
    [ObservableProperty] private bool _isCaptain;

    // ── ability ──────────────────────────────────────────────────────────────────────

    // The six radar axes follow the player: a keeper's are gk_* abilities (Visuals.GkRadarGroups),
    // so outfield words would lie on his card. THE BUG the Market profile had: two labels were
    // hard-coded into the view and both named the wrong axis — BuildRadarPoints puts axis k at
    // k*60−90°, so the bottom vertex is axis 3 (SPD), not DEF. All six come from here, in the
    // order the geometry draws them, and all six are bound.
    private static readonly IReadOnlyList<string> OutfieldRadarLabels =
        new[] { "SHO", "PAS", "DRI", "SPD", "DEF", "STR" };
    private static readonly IReadOnlyList<string> GkRadarLabels =
        new[] { "AWR", "PAS", "HAN", "REF", "PAR", "REA" };

    [ObservableProperty] private IReadOnlyList<string> _radarLabels =
        new[] { "SHO", "PAS", "DRI", "SPD", "DEF", "STR" };
    [ObservableProperty] private Points _radarPoints = new();
    /// <summary>No polygon: either nothing is on file, or he is below the scouting floor.</summary>
    [ObservableProperty] private bool _radarMasked;
    [ObservableProperty] private IReadOnlyList<AbilityEntry> _abilities = Array.Empty<AbilityEntry>();
    [ObservableProperty] private bool _hasAbilities;
    [ObservableProperty] private string _abilityNote = "";
    [ObservableProperty] private bool _hasAbilityNote;

    [ObservableProperty] private IReadOnlyList<string> _coachLines = Array.Empty<string>();
    [ObservableProperty] private bool _hasCoachLines;
    /// <summary>The line under the coach's report. It has to survive a report that DOES have
    /// lines: a famous man's report is half a report, and the missing half needs explaining.</summary>
    [ObservableProperty] private string _coachNote = "";
    [ObservableProperty] private string _analystLine = "";
    [ObservableProperty] private string _analystNote = "";

    /// <summary>The six graded analysis panels — the same builder the Squad card uses, and the
    /// same row types, so there is still one implementation of a graded statement in the app.</summary>
    [ObservableProperty]
    private IReadOnlyList<SquadViewModel.AnalysisPanelVm> _analysisPanels =
        Array.Empty<SquadViewModel.AnalysisPanelVm>();
    [ObservableProperty] private bool _hasAnalysis;

    // ── the man himself ──────────────────────────────────────────────────────────────

    [ObservableProperty] private string _playstyle = "";
    [ObservableProperty] private bool _hasPlaystyle;
    [ObservableProperty] private string _playstyleOut = "";
    [ObservableProperty] private bool _hasPlaystyleOut;
    [ObservableProperty] private IReadOnlyList<string> _skills = Array.Empty<string>();
    [ObservableProperty] private bool _hasSkills;
    [ObservableProperty] private string _skillsNote = "";
    [ObservableProperty] private string _personality = "";
    [ObservableProperty] private bool _hasPersonality;
    [ObservableProperty] private IReadOnlyList<PlayerTraitVm> _traits = Array.Empty<PlayerTraitVm>();
    [ObservableProperty] private bool _hasTraits;
    [ObservableProperty] private string _traitsNote = "";
    [ObservableProperty] private string _potential = "";
    [ObservableProperty] private string _potentialNote = "";

    // ── season & club ────────────────────────────────────────────────────────────────

    [ObservableProperty] private IReadOnlyList<PlayerStatTileVm> _seasonTiles =
        Array.Empty<PlayerStatTileVm>();
    [ObservableProperty] private string _seasonNote = "";
    [ObservableProperty] private bool _hasSeasonNote;
    [ObservableProperty] private string _startsLine = "";
    [ObservableProperty] private string _moraleFace = "";
    [ObservableProperty] private string _moraleLine = "";
    [ObservableProperty] private bool _hasMorale;
    /// <summary>Form and mood are your own dressing room's — for anyone else this says so
    /// rather than reading a neutral 50 back and calling it "Content".</summary>
    [ObservableProperty] private string _outsideNote = "";
    [ObservableProperty] private bool _hasOutsideNote;

    [ObservableProperty] private string _squadRoleLabel = "SQUAD ROLE";
    [ObservableProperty] private string _squadRole = "";
    [ObservableProperty] private string _contractLine = "";
    [ObservableProperty] private bool _hasContract;
    [ObservableProperty] private string _promiseLine = "";
    [ObservableProperty] private bool _hasPromise;
    [ObservableProperty] private string _valueLine = "";
    [ObservableProperty] private string _wageLine = "";
    [ObservableProperty] private string _budgetLine = "";

    [ObservableProperty] private IReadOnlyList<PlayerCareerRowVm> _career =
        Array.Empty<PlayerCareerRowVm>();
    [ObservableProperty] private bool _hasCareer;
    [ObservableProperty] private string _careerNote = "";

    // ── the docked status line ───────────────────────────────────────────────────────

    private enum Tone { Info, Warn, Bad, Muted }

    [ObservableProperty] private string _statusLine = "";
    [ObservableProperty] private IBrush _statusBrush = Visuals.Brush("#8A93A2");

    private void Say(string text, Tone tone = Tone.Info)
    {
        if (string.IsNullOrWhiteSpace(text)) return;
        StatusLine = text;
        StatusBrush = Visuals.Brush(tone switch
        {
            Tone.Warn => "#E0A526",     // MlWarn
            Tone.Bad => "#D64545",      // MlDanger
            Tone.Muted => "#8A93A2",    // MlTextMuted
            _ => "#9FE6B4",             // MlSuccessText — the assistant voice
        });
    }

    /// <summary>
    /// Colour for an answer the ENGINE wrote. The engine returns prose, not a result code, so
    /// this is a best-effort read of the handful of refusal shapes it actually uses — and it
    /// only ever changes the COLOUR, never the words. A miss shows a refusal in the neutral
    /// voice; it can never hide one, and it can never invent one.
    /// </summary>
    private static readonly string[] RefusalMarkers =
    {
        "can't", "cannot", "won't", "isn't", "not enough", "needs a", "at the minimum",
        "too old", "on a mission", "no scout", "nothing ", "already",
    };

    private static Tone ToneOfAnswer(string line) =>
        RefusalMarkers.Any(m => line.Contains(m, StringComparison.OrdinalIgnoreCase))
            ? Tone.Warn
            : Tone.Info;

    // ── the shared action vocabulary ─────────────────────────────────────────────────

    public ObservableCollection<PlayerActionVm> Actions { get; } = new();
    public bool HasActions => Actions.Count > 0;

    /// <summary>
    /// The menu for this man — the right-click half of the affordance, and the source the
    /// visible buttons are projected from. Built fresh every time so the toggles (shortlist,
    /// transfer list, captain) and the guards (scout busy, no scout) are always current.
    /// </summary>
    public ContextMenu? BuildMenu()
    {
        if (_id <= 0) return null;
        var extras = new List<MenuItem>();
        if (!_mine)
        {
            // The one verb this screen adds: the bidding table. It goes in as an EXTRA so it
            // is in the right-click menu too, rather than existing only as a button.
            var bid = new MenuItem { Header = BidHeader };
            bid.Click += (_, _) => OpenBidding();
            extras.Add(bid);
        }
        if (_youthKind.Length > 0)
        {
            // EntityActions reads his club, and a lad in your U21s is in a DIFFERENT team row,
            // so the shared menu offers him the foreign set. Promotion is the way back up and
            // only this screen knows he is one of yours.
            var up = new MenuItem { Header = PromoteHeader };
            up.Click += (_, _) =>
            {
                var line = Safe(() => _s.PromoteToSenior(_id, _s.CurrentTeamId),
                                "That move didn't go through.");
                Say(line, ToneOfAnswer(line));
                Reload();
            };
            extras.Add(up);
        }
        try
        {
            return EntityActions.BuildMenu(_s, EntityRef.Player(_id, _name),
                status: line => Say(line, ToneOfAnswer(line)),
                refresh: Reload,
                extras: extras.Count > 0 ? extras : null);
        }
        catch (Exception ex)
        {
            Program.Log("Player.BuildMenu", ex);
            return null;
        }
    }

    /// <summary>
    /// Project the menu into visible buttons. Three items are dropped: the menu's own title
    /// row (this screen's header IS that), "View profile" (we are the profile), and the
    /// bidding verb (it gets its own prominent button beside the fee). Everything else —
    /// including anything EntityActions grows later — appears here automatically.
    /// </summary>
    private void BuildActions()
    {
        Actions.Clear();
        var menu = BuildMenu();
        if (menu is not null)
        {
            foreach (var item in menu.Items.OfType<MenuItem>())
            {
                var header = item.Header?.ToString() ?? "";
                if (header.Length == 0) continue;
                if (header == _infoHeader || header == ProfileHeader || header == BidHeader) continue;
                var mi = item;
                Actions.Add(new PlayerActionVm(header, mi.IsEnabled, () => Invoke(mi)));
            }
        }
        OnPropertyChanged(nameof(HasActions));
    }

    /// <summary>Run a menu item's own Click handler. The button and the menu row are the same
    /// object, so there is exactly one implementation of every verb.</summary>
    private void Invoke(MenuItem item)
    {
        try { item.RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent)); }
        catch (Exception ex)
        {
            Program.Log("Player.Invoke", ex);
            Say("That action didn't go through — nothing was changed.", Tone.Bad);
        }
    }

    /// <summary>The way out of an empty profile: your own squad, where every name opens one.</summary>
    [RelayCommand]
    private void GoToSquad() => Nav.Go("Squad", null);

    [RelayCommand]
    private void OpenBidding()
    {
        if (_id <= 0) { Say("No player open.", Tone.Muted); return; }
        if (_mine)
        {
            Say($"{_name} is already yours — there is nothing to bid for.", Tone.Warn);
            return;
        }
        Say($"Opening the bidding table for {_name}.");
        Nav.Go("Bidding", EntityRef.Player(_id, _name));
    }

    // ── loading ──────────────────────────────────────────────────────────────────────

    /// <summary>Read one thing from the career file without letting a single failure blank the
    /// whole screen. Copied in spirit from the Tactics rail, for the same reason.</summary>
    private static T Safe<T>(Func<T> read, T fallback)
    {
        try { return read(); }
        catch { return fallback; }
    }

    /// <summary>Load the whole screen for one man. False when there is nobody to show.</summary>
    private bool Load(long id, string fallbackName = "")
    {
        var name = Safe(() => _s.PlayerNameOf(id), "");
        if (name.Length == 0) name = fallbackName ?? "";
        if (id <= 0 || name.Length == 0)
        {
            ShowEmptyState("That player isn't in your world — there is nothing on file to show. " +
                           "Players you can sign live in the transfer market.");
            return false;
        }

        _id = id;
        _name = name;
        PlayerName = name;

        // --- who he is, and whose he is -------------------------------------------------
        var where = Safe<(int? TeamId, string Club)>(() => _s.ClubOfPlayer(id), (null, "Free agent"));
        _club = where.Club;
        _free = where.TeamId is null;
        _mine = Safe(() => _s.IsOwnPlayer(id), false);
        IsMine = _mine;
        IsFreeAgent = _free;
        _infoHeader = $"{name} · {(_mine ? "your squad" : _club)}";

        // A lad in YOUR U21s/U18s sits in a different team row, so he is neither "yours" by
        // squad membership nor a rival's — the screen has to know, or promotion is unreachable.
        _youthKind = "";
        if (!_mine && where.TeamId is { } tid)
        {
            var kind = Safe(() => _s.TeamKindOf(tid), "first");
            if (kind is "u21" or "u18" &&
                Safe(() => _s.YouthSquad(_s.CurrentTeamId, kind).Any(y => y.PlayerId == id), false))
            {
                _youthKind = kind;
            }
        }

        ClubLine = _free ? "Free agent" : _club;
        ClubCrest = where.TeamId is { } logoTeam
            ? Visuals.LoadBitmap(Safe<string?>(() => _s.TeamLogoPath(logoTeam), null))
            : null;
        HasClubCrest = ClubCrest is not null;

        // --- the bio row ------------------------------------------------------------------
        var bio = ReadBio(id);
        PositionLabel = bio.Position.Length > 0 ? bio.Position : "—";
        PositionBrush = Visuals.PositionBrush(bio.Position);
        Nationality = bio.Nationality;
        Flag = NationFlags.For(bio.Nationality);
        HasFlag = Flag is not null;
        var age = Safe<int?>(() => _s.PlayerAgeOf(id), null) ?? bio.Age;
        AgeDisplay = age is > 0 ? age.Value.ToString() : "—";
        HeightDisplay = bio.Height is > 0 ? $"{bio.Height} cm" : "—";
        WeightDisplay = bio.Weight is > 0 ? $"{bio.Weight} kg" : "—";
        Playstyle = bio.Playstyle;
        HasPlaystyle = Playstyle.Length > 0;
        PlaystyleOut = bio.PlaystyleOut;
        HasPlaystyleOut = PlaystyleOut.Length > 0;

        var por = Safe(() => _s.PortraitFor(id),
            new PortraitInfo(null, PortraitSource.EfootballGeneric, null, null));
        Portrait = por.Image;
        HasPortrait = por.Image is not null;
        Mark = Visuals.PlayerMark(name);
        // Real skin tone behind the initials when there is no photo (the generic-face tier).
        MarkBrush = por.Image is null
            ? Visuals.SkinBrush(por.SkinTone)
            : Visuals.PositionBrush(bio.Position);

        // --- what you are allowed to see --------------------------------------------------
        // Your own player is fully known by definition; the engine owns the rest, and a failed
        // read falls to 0 rather than pretending.
        // Two numbers, deliberately. SCOUTED is what your club has earned and it alone opens the
        // dossier; KNOWLEDGE adds what the world already says about him, and drives his football.
        _scouted = _mine ? 100 : Safe(() => _s.ScoutedKnowledgeOf(id), 0);
        _knowledge = _mine ? 100 : Safe(() => _s.KnowledgeOf(id), 0);
        _reputation = _mine ? 0 : Safe(() => _s.ReputationOf(id), 0);
        _fm = Safe(() => _s.FmAttributeMode, true);
        IsKnown = _mine || _scouted >= ScoutFloor;
        var fame = _mine ? "" : Safe(() => _s.FameLabelOf(id), "");
        var knownFor = _mine ? "" : Safe(() => _s.FameHeadlineOf(id, bio.Position), "");
        // "Well known" means the game has an opinion worth repeating AND something concrete to
        // repeat. A trace of reputation with nothing showing yet is still an unknown man.
        var wellKnown = _reputation >= FameFloor && fame.Length > 0 && knownFor.Length > 0;
        var label = Safe(() => _s.KnowledgeLabelOf(id), _mine ? "Fully known" : "Unknown");
        KnowledgeLine = _mine
            ? "Fully known — one of yours"
            : fame.Length > 0 ? $"{label}  ·  {fame}" : label;

        // The unscouted card. A £354m forward is not "not scouted" in any sense a manager would
        // recognise — the game knows exactly what he does. What it does not know is the man.
        UnknownHeading = wellKnown ? "WHAT THE GAME KNOWS" : "NOT SCOUTED";
        UnknownLine = wellKnown
            ? $"{fame}. Nobody had to watch {name} to tell you about {knownFor} — that much is " +
              "common knowledge, and it is already on this screen. What reputation cannot tell " +
              "you is the rest of him: his weaknesses, his character, his ceiling and the read " +
              "your own coach would give. Send a scout from the actions above for those."
            : $"{label}. You know where {name} stands and nothing else — his skills, his character " +
              "and the coach's read on him stay dark until somebody watches him play. Send a scout " +
              "from the actions above and this whole column fills in.";

        Grade = StarRating.Text(StarRating.Masked(bio.Rating, _knowledge));
        GradeBrush = _knowledge >= 75 ? Visuals.RatingBrush(bio.Rating) : Visuals.Brush("#8A93A2");
        GradeTip = _knowledge >= 75
            ? "Fully known — this is his real calibre."
            : _knowledge >= ScoutFloor
                ? "Part-scouted — the range is close, the gap is the margin."
                : _reputation >= FameFloor
                    ? "This is his reputation, not a scouting report. Watch him for his real tier."
                    : "Nobody at the club has watched him. Scout him for his real tier.";

        LoadAbility(id, bio);
        LoadDossier(id, name);
        LoadSeason(id, name);
        LoadClubSide(id);
        LoadCareer(id);

        HasSubject = true;
        BuildActions();
        return true;
    }

    private sealed record Bio(
        string Position, int Rating, int? Age, int? Height, int? Weight,
        string Nationality, string Playstyle, string PlaystyleOut);

    /// <summary>
    /// The bio row in one read. Raw ADO against the career file, exactly as the Squad card
    /// reads player_market — no engine method covers these columns together, and eight
    /// separate round trips for one header would be worse.
    /// </summary>
    private Bio ReadBio(long id)
    {
        try
        {
            using var cmd = _s.Db.Connection.CreateCommand();
            cmd.CommandText =
                "SELECT COALESCE(p.position,''), COALESCE(p.overall_rating,0), p.age, " +
                "p.height_cm, p.weight_kg, COALESCE(p.nationality,''), " +
                "(SELECT playstyle FROM player_playstyles WHERE player_id=p.id " +
                "   AND kind='primary' LIMIT 1), " +
                "(SELECT playstyle FROM player_playstyles WHERE player_id=p.id " +
                "   AND kind='secondary' LIMIT 1) " +
                "FROM players p WHERE p.id=$p";
            cmd.Parameters.AddWithValue("$p", id);
            using var r = cmd.ExecuteReader();
            if (!r.Read()) return new Bio("", 0, null, null, null, "", "", "");
            // A few dozen rows carry overall_rating (and the measurements) as REAL — Convert,
            // never GetInt32, or those players throw on the way in.
            return new Bio(
                r.GetString(0),
                Convert.ToInt32(r.GetValue(1)),
                r.IsDBNull(2) ? null : Convert.ToInt32(r.GetValue(2)),
                r.IsDBNull(3) ? null : Convert.ToInt32(r.GetValue(3)),
                r.IsDBNull(4) ? null : Convert.ToInt32(r.GetValue(4)),
                r.GetString(5),
                r.IsDBNull(6) ? "" : r.GetString(6),
                r.IsDBNull(7) ? "" : r.GetString(7));
        }
        catch (Exception ex)
        {
            Program.Log("Player.ReadBio", ex);
            return new Bio("", 0, null, null, null, "", "", "");
        }
    }

    /// <summary>
    /// The radar, the ability list and the graded panels.
    /// <para>
    /// Two different gates, deliberately: the FM display toggle governs the ATTRIBUTE view
    /// (that is what the toggle is for — turn it off and you have asked for raw numbers), and
    /// SCOUTING governs the dossier. So the radar hides when FM mode is on and he is below the
    /// floor, and the character half of the screen hides whenever he is below it.
    /// </para>
    /// </summary>
    private void LoadAbility(long id, Bio bio)
    {
        var abilities = Safe<IReadOnlyDictionary<string, int>>(
            () => _s.Repo.Attributes(id), new Dictionary<string, int>());
        var isGk = bio.Position == "GK";
        RadarLabels = isGk ? GkRadarLabels : OutfieldRadarLabels;
        HasAbilities = abilities.Count > 0;

        // The reveal ORDER is where reputation lands: at his fame level the abilities the world
        // already talks about come off the top, and the ones it never mentions stay masked.
        // The radar is an aggregate of ALL of them, so it stays behind the scouting gate — a
        // full shape drawn from a headline would be a guess dressed up as data.
        var order = Safe(() => _s.RevealOrderOf(id, bio.Position), RevealOrder.Anonymous(id));
        var belowFloor = _fm && !IsKnown;
        RadarMasked = !HasAbilities || belowFloor;
        RadarPoints = RadarMasked
            ? new Points()
            : PlayerCard.BuildRadarPoints(Visuals.RadarAxes(abilities, isGk));
        Abilities = HasAbilities
            ? PlayerCard.BuildAbilityList(abilities, isGk, _fm, _knowledge, id, order)
            : Array.Empty<AbilityEntry>();

        AbilityNote = !HasAbilities
            ? "No abilities on file for him in your world. He can still be signed — his numbers " +
              "arrive with him."
            : belowFloor
                ? _reputation >= FameFloor
                    ? "Reputation, not scouting — what is showing here is what the game already " +
                      "says about him. The rest of his game stays masked until someone watches him."
                    : "Barely scouted — the shape of his game is guesswork until someone watches him."
                : "";
        HasAbilityNote = AbilityNote.Length > 0;

        // The coach only quotes what your knowledge has revealed, so an empty report is a real
        // answer — it just has to be SAID, or an unwatched player looks like a broken panel.
        var coach = Safe(() => _s.CoachReportOf(id, bio.Position).Select(l => "• " + l).ToList(),
                         new List<string>());
        CoachLines = coach;
        HasCoachLines = coach.Count > 0;
        CoachNote = coach.Count > 0
            ? ""
            : _mine
                ? "Nothing stands out either way — no strong qualities and no obvious flaws on file."
                : $"Your coach has seen enough of {_name} to place him, not enough to call out a " +
                  "strength or a weakness.";
        // A famous man's praise is free and his flaws are not: the coach can repeat what the
        // game says he is good at long before anyone has found what he is bad at. Say so, or
        // the one-sided report reads like a bug.
        if (coach.Count > 0 && !_mine && _scouted < ScoutFloor && _reputation >= FameFloor)
        {
            CoachNote = "Reputation only — these are the qualities everyone already credits him " +
                        "with. Scout him and your coach will tell you where he can be got at.";
        }

        AnalystLine = Safe(() => _s.AnalystLineOf(id), "");
        AnalystNote = AnalystLine.Length > 0
            ? ""
            : IsKnown
                ? "Your analyst has nothing to add on him this season."
                : _reputation >= FameFloor
                    ? "Below the knowledge floor. Your analyst can read his reputation as well as " +
                      "anyone; he won't put his name to a season read until somebody watches him."
                    : "Below the knowledge floor — your analyst won't put his name to a read on a " +
                      "player nobody has watched.";

        try
        {
            AnalysisPanels = PlayerAnalysis.Build(id, abilities, isGk, _knowledge, order)
                .Select(p => new SquadViewModel.AnalysisPanelVm(
                    p.Name,
                    p.Lines.Select(l => new SquadViewModel.AnalysisLineVm(
                        l.Text, l.Grade,
                        l.Tone switch
                        {
                            PlayerAnalysis.Tone.Good => "✓",
                            PlayerAnalysis.Tone.Mid => "○",
                            _ => "✗",
                        },
                        Visuals.Brush(l.Tone switch
                        {
                            PlayerAnalysis.Tone.Good => "#1F9D4D",
                            PlayerAnalysis.Tone.Mid => "#8A93A2",
                            _ => "#D64545",
                        }))).ToList()))
                .ToList();
        }
        catch { AnalysisPanels = Array.Empty<SquadViewModel.AnalysisPanelVm>(); }
        HasAnalysis = AnalysisPanels.Count > 0;
    }

    /// <summary>Character, skills and ceiling — the scouted half. Below the floor none of it
    /// is read at all: the unknown card says so instead.</summary>
    private void LoadDossier(long id, string name)
    {
        if (!IsKnown)
        {
            Skills = Array.Empty<string>();
            HasSkills = false;
            SkillsNote = "";
            Personality = "";
            HasPersonality = false;
            Traits = Array.Empty<PlayerTraitVm>();
            HasTraits = false;
            TraitsNote = "";
            Potential = "";
            PotentialNote = "";
            return;
        }

        var skills = Safe(() => _s.SkillsOf(id).ToList(), new List<string>());
        Skills = skills;
        HasSkills = skills.Count > 0;
        SkillsNote = skills.Count > 0 ? "" : "No signature skills on record.";

        Personality = Safe(() => _s.PersonalityOf(id), "");
        HasPersonality = Personality.Length > 0;

        var (det, prof, amb, temp) = Safe(() => _s.TraitsOf(id), default);
        // Traits are 1–20 in the engine and WORDS on screen — this app never shows the score.
        // The bands are Squad's and the Tactics rail's, kept identical on purpose so one man
        // reads the same wherever you meet him.
        Traits = det <= 0
            ? Array.Empty<PlayerTraitVm>()
            : new[]
            {
                new PlayerTraitVm("Determination",
                    TraitWord(det, "Driven", "Steady", "Inconsistent", "Flaky")),
                new PlayerTraitVm("Professionalism",
                    TraitWord(prof, "Model pro", "Professional", "Casual", "Unprofessional")),
                new PlayerTraitVm("Ambition",
                    TraitWord(amb, "Hungry", "Ambitious", "Content", "Unambitious")),
                new PlayerTraitVm("Temperament",
                    TraitWord(temp, "Unflappable", "Level-headed", "Volatile", "Hot-headed")),
            };
        HasTraits = Traits.Count > 0;
        TraitsNote = HasTraits ? "" : $"No read on {name}'s character yet.";

        var stars = Safe(() => _s.PotentialStars(id), 0);
        Potential = Stars(stars);
        PotentialNote = stars <= 0
            ? "no read on his ceiling yet"
            : _mine ? "your coaches' read on his ceiling"
            : "your scouts' read on his ceiling";
    }

    /// <summary>A 1–20 trait as one word. Four bands, the same shape for every trait.</summary>
    private static string TraitWord(int v, string high, string mid, string low, string worst) =>
        v >= 16 ? high : v >= 11 ? mid : v >= 6 ? low : worst;

    /// <summary>Potential as filled/hollow stars — the game's own currency for a ceiling.</summary>
    private static string Stars(int n)
    {
        if (n <= 0) return "";
        var filled = Math.Clamp(n, 1, 5);
        return new string('★', filled) + new string('☆', 5 - filled);
    }

    private void LoadSeason(long id, string name)
    {
        // Appearances, goals and cards are STATISTICS — digits are correct here. The star-rating
        // rule is about how good a player IS, which is a different question.
        var (apps, goals, assists, yellows, reds, avg) =
            Safe(() => _s.PlayerSeasonStats(id), default);
        SeasonTiles = new[]
        {
            new PlayerStatTileVm("APPS", apps.ToString()),
            new PlayerStatTileVm("GOALS", goals.ToString()),
            new PlayerStatTileVm("ASSISTS", assists.ToString()),
            new PlayerStatTileVm("CARDS", $"{yellows} 🟨   {reds} 🟥"),
            new PlayerStatTileVm("AVG RATING", avg is { } a ? $"{a:0.0}" : "—"),
        };
        SeasonNote = apps == 0
            ? $"No competitive minutes this season — {name}'s numbers start when he plays."
            : avg is null
                ? "No match ratings on file yet — the average fills in as he plays."
                : "";
        HasSeasonNote = SeasonNote.Length > 0;

        if (_mine)
        {
            var md = Safe<int?>(() => _s.NextFixture()?.Matchday, null) ?? 0;
            StartsLine = md <= 0
                ? "No matchday ahead yet — his run of starts begins with the season."
                : $"{Safe(() => _s.StartsInLastSix(id, Math.Max(1, md - 1)), 0)} of the last 6 starts";
            var morale = Safe(() => _s.MoraleOf(id), MoraleModel.Neutral);
            MoraleFace = morale >= 75 ? "😀" : morale >= 60 ? "🙂" : morale >= 40 ? "😐"
                : morale >= 25 ? "🙁" : "😡";
            MoraleLine = MoraleModel.Label(morale);
            HasMorale = true;
            OutsideNote = "";
            HasOutsideNote = false;
        }
        else
        {
            StartsLine = "";
            MoraleFace = "";
            MoraleLine = "";
            HasMorale = false;
            // Reading a neutral 50 back for another club's player and calling it "Content"
            // would be inventing a fact.
            OutsideNote = $"Form and morale are your own dressing room's — for {name} you have " +
                          "the record above and whatever your analyst can see.";
            HasOutsideNote = true;
        }
    }

    private void LoadClubSide(long id)
    {
        // PlayTimeStatusOf is read-only and derived from where he ranks in HIS OWN squad, so it
        // is honest for anyone — it is only the WORD "promise" that belongs to your own club.
        SquadRoleLabel = _mine ? "PLAYING TIME" : "SQUAD ROLE";
        SquadRole = Safe(() => _s.PlayTimeStatusOf(id), "");

        // ContractYear WRITES a contract row against YOUR club on first sight. Asking it about
        // a rival's player would file him a deal at your club behind your back, so it is asked
        // about your own players and nobody else's. Same for the promise line.
        if (_mine)
        {
            var year = Safe(() => _s.ContractYear(id), 0);
            var learned = Safe(() => _s.LearnedPositions(id), (IReadOnlyList<string>)Array.Empty<string>());
            ContractLine = year > 0
                ? $"Contract until {year}" +
                  (learned.Count > 0 ? $"  ·  plays {string.Join("/", learned)} too" : "")
                : "";
            PromiseLine = Safe(() => _s.PromiseLine(id), "");
        }
        else
        {
            ContractLine = "";
            PromiseLine = "";
        }
        HasContract = ContractLine.Length > 0;
        HasPromise = PromiseLine.Length > 0;

        // Market value comes from the engine's own accessor, NOT a private query.
        // THE BUG this replaces: this screen read player_market directly and printed "—" when a
        // player had no imported row, while the Market grid falls back to the valuation curve for
        // exactly those players. The same man showed £354,350,000 on one screen and "—" on the
        // other. MarketValueOf is the canonical rule — the real imported fee when there is one,
        // the curve when there is not — and until now nothing called it.
        ValueLine = Safe(() =>
        {
            var b = ReadBio(id);
            var v = _s.MarketValueOf(id, b.Rating, b.Age > 0 ? b.Age : null);
            return v > 0 ? $"£{v:N0}" : "—";
        }, "—");

        // Same rule as the market value above: ask the ENGINE, not a private query. This read
        // player_market.wage on its own and printed "—" for anyone with no imported market row,
        // which is most of a squad — so a club paying £111,240 a week showed no wage for its own
        // goalkeeper. WeeklyWageOf is the line the wage bill itself is summed from.
        WageLine = Safe(() =>
        {
            var wage = _s.WeeklyWageOf(id, _s.ClubOfPlayer(id).TeamId);
            return wage > 0 ? $"£{wage:N0}/wk" : "—";
        }, "—");

        // The audit's third finding: the transfer budget was never shown anywhere while you
        // spent it. It belongs beside the button that starts the spending.
        var budget = Safe(() => _s.FinancialOverview().TransferBudget, 0L);
        BudgetLine = $"Transfer budget  £{budget:N0}";

        IsTransferListed = Safe(() => _s.IsTransferListed(id), false);
        IsLoanListed = Safe(() => _s.IsLoanListed(id), false);
        IsShortlisted = Safe(() => _s.IsShortlisted(id), false);
        IsCaptain = Safe(() => _s.Captain == id, false);
    }

    private void LoadCareer(long id)
    {
        var rows = Safe(() => _s.PlayerCareerHistory(id).ToList(), new List<CareerHistoryRow>());
        Career = rows.Select(h => new PlayerCareerRowVm(
            $"{h.Year}/{(h.Year + 1) % 100:00}",
            h.Club,
            h.Apps.ToString(),
            h.Goals.ToString(),
            h.Assists.ToString(),
            h.AvgRating is { } a ? $"{a:0.0}" : "—")).ToList();
        HasCareer = Career.Count > 0;
        CareerNote = HasCareer ? "" : "No seasons on record yet — his history starts here.";
    }
}
