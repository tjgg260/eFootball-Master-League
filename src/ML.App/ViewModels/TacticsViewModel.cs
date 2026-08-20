using System.Collections.ObjectModel;
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Core.Selection;
using ML.Data;

namespace ML.App.ViewModels;

// --- Tactics (the eFootball/FM formation editor, on a drawn pitch) ----------------

public sealed record FormationOption(string Shape, int Id)
{
    public override string ToString() => Shape;
}

/// <summary>
/// A team playstyle. Index order is LOCKED to the game's style enum (0–5). Pages are the
/// VERBATIM "Player Movement" texts from eFootball's own English string table
/// (dt261_eng_console_win.cpk :: eng/string/all.str) — never paraphrased.
/// </summary>
public sealed record StyleOption(int Index, string Name, params string[] Pages)
{
    public string Description => Pages.Length > 0 ? Pages[0] : "";
}

/// <summary>A player role (playstyle) with a ★ fit rating for the selected player.</summary>
public sealed record RoleOption(string Name, string Description)
{
    public string Stars { get; init; } = "";
}

/// <summary>A bench player — click him and click a starter (either order) and they swap.</summary>
public sealed record BenchEntry(
    int PlayerId, int Number, string Name, string Position, int Rating, string? PortraitPath,
    int Fatigue, bool Injured, IReadOnlyList<string> Learned)
{
    public Avalonia.Media.IBrush RatingBrush => Visuals.RatingBrush(Rating);
    public Avalonia.Media.IBrush CondBrush =>
        Visuals.Brush(Injured ? "#D64545" : Fatigue < 20 ? "#1F9D4D" : Fatigue < 40 ? "#E0A526" : "#D64545");
    public string Tag => Injured ? "INJ" : Fatigue >= 40 ? "TIRED" : "";
    public Avalonia.Media.Imaging.Bitmap? Portrait => Visuals.LoadBitmap(PortraitPath);
    public bool HasPortrait => Portrait is not null;
    public string Mark => Visuals.PlayerMark(Name);
    public Avalonia.Media.IBrush MarkBrush => Visuals.PositionBrush(Position);
}

/// <summary>A draggable player token: identity + condition + positional fit ring.</summary>
public sealed partial class PitchPlayer : ObservableObject
{
    public PitchPlayer(int playerId, int number, string name, int rating, string? portraitPath,
                       string position, string role, double left, double top,
                       string registeredPosition = "", IReadOnlyList<string>? learned = null,
                       int fatigue = 0, bool injured = false)
    {
        PlayerId = playerId;
        Number = number;
        Name = name;
        Rating = rating;
        PortraitPath = portraitPath;
        Portrait = Visuals.LoadBitmap(portraitPath);
        RegisteredPosition = string.IsNullOrEmpty(registeredPosition) ? position : registeredPosition;
        Learned = learned ?? Array.Empty<string>();
        Fatigue = fatigue;
        Injured = injured;
        _position = position;
        _role = role;
        _left = left;
        _top = top;
    }

    public int PlayerId { get; }
    public int Number { get; }
    public string Name { get; }
    public int Rating { get; }
    public string? PortraitPath { get; }
    public string RegisteredPosition { get; }
    public IReadOnlyList<string> Learned { get; }
    public int Fatigue { get; }
    public bool Injured { get; }
    public string Surname => Name.Contains(' ') ? Name[(Name.LastIndexOf(' ') + 1)..] : Name;
    public Avalonia.Media.Imaging.Bitmap? Portrait { get; }
    public bool HasPortrait => Portrait is not null;
    public Avalonia.Media.IBrush RatingBrush => Visuals.RatingBrush(Rating);

    /// <summary>Condition dot: green fresh, amber leggy, red exhausted/injured.</summary>
    public Avalonia.Media.IBrush CondBrush =>
        Visuals.Brush(Injured ? "#D64545" : Fatigue < 20 ? "#1F9D4D" : Fatigue < 40 ? "#E0A526" : "#D64545");

    public bool ShowInjury => Injured;

    [ObservableProperty] private double _left;
    [ObservableProperty] private double _top;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Fill))]
    [NotifyPropertyChangedFor(nameof(FitBrush))]
    private string _position;

    [ObservableProperty] private string _role;

    public Avalonia.Media.IBrush Fill => Visuals.PositionBrush(Position);

    public Fit Fit => PlayerId == 0 ? Fit.Natural
        : PositionFit.Of(RegisteredPosition, Learned.ToArray(), Position);

    /// <summary>Fit ring around the portrait: green natural, amber same unit, red out of unit.</summary>
    public Avalonia.Media.IBrush FitBrush => Visuals.Brush(Fit switch
    {
        Fit.Natural => "#1F9D4D",
        Fit.Ok => "#E0A526",
        _ => "#D64545",
    });
}

/// <summary>The next opponent's read-only token on the mirrored right half of the pitch.</summary>
public sealed record OppToken(double Left, double Top, string Pos, int Rating, string Surname,
                              Avalonia.Media.Imaging.Bitmap? Portrait)
{
    public bool HasPortrait => Portrait is not null;
    public string Mark => Visuals.PlayerMark(Surname);
    public Avalonia.Media.IBrush MarkBrush => Visuals.PositionBrush(Pos);
    public Avalonia.Media.IBrush RatingBrush => Visuals.RatingBrush(Rating);
}

public sealed partial class TacticsViewModel : PageViewModel
{
    // Canvas + token geometry — the game's own Game Plan orientation: one full HORIZONTAL
    // pitch, your XI occupying the left half (GK far left), the opponent mirrored on the
    // right. The canvas AND the ItemsControl are BOTH PitchW x PitchH (regression guard —
    // a size mismatch silently breaks drag coordinates). Your tokens clamp to HalfW.
    public const double PitchW = 720, PitchH = 430, HalfW = 352, TokenW = 52, TokenH = 74;
    // eFootball pitch coordinate ranges (from the formation tables): y = advance toward the
    // opponent goal (canvas X), x = pitch width (canvas Y).
    private const double MinX = 12, MaxX = 92, MinY = 3, MaxY = 43;

    public static readonly string[] AllPositions =
        { "GK", "CB", "LB", "RB", "LWB", "RWB", "DMF", "CMF", "LMF", "RMF", "AMF", "LWF", "RWF", "SS", "CF" };

    /// <summary>eFootball's own intro line for the playstyle screen (all.str [46354]).</summary>
    public const string StyleIntro =
        "Select a Team Playstyle to define how your team behaves in and out of possession " +
        "and various other match situations.";

    // Team playstyles: index order LOCKED to the game's style enum (style byte 0–5; 22 shipped
    // team records carry 5 = Overload). Every page below is VERBATIM from all.str — the same
    // "Player Movement" texts the game shows on its Team Playstyle screen.
    private static readonly StyleOption[] StyleCatalog =
    {
        new(0, "Possession Game",
            // all.str [5686..5689]
            "Sends a few players near the ball to achieve numerical superiority across a small " +
            "area, then uses short passes to break through the opposing defence.",
            "Shifts the entire team towards the same side as the ball and defends with a tight, " +
            "compact shape.\nWhen the ball is high up the pitch, the entire team presses aggressively.",
            "When winning possession, nearby teammates provide support and priority is placed on " +
            "keeping possession. When winning the ball high up the pitch, or when playing a forward " +
            "pass immediately after regaining possession, a counterattack will be launched.",
            "When ball possession is lost, nearby players will aggressively pressure the opponent " +
            "in numbers to try and regain possession."),
        new(1, "Quick Counter",
            // all.str [46355..46358]
            "Players will spring a counter attack by actively dashing towards the opponent's goal.",
            "Keep a high defensive line to put pressure on the opponent from the frontlines.",
            "When ball possession is regained close to the opponent's goal, the players will " +
            "immediately dash towards the goal to enable a counter attack.",
            "When ball possession is lost, nearby players will aggressively pressure the opponent " +
            "in numbers to try and regain possession."),
        new(2, "Long Ball Counter",
            // all.str [46347], [46350], [46349] — the game's behaviour texts for this style
            "After stealing possession deep inside your own half, your players rush forward into " +
            "open spaces enabling you to orchestrate a quick counter attack.",
            "Players form a deep-sitting defensive line near the goal and defend from there.",
            "After losing possession, players sprint back to their own half and line up in a " +
            "defensive formation."),
        new(3, "Long Ball",
            // all.str [46359..46362]
            "Players will focus on long balls, rather than trying to dominate the midfield.\n" +
            "They will prepare to receive long passes, and the surrounding players will also " +
            "position themselves to pick up second balls if needed.",
            "The defensive block will be kept deep to ensure a steady defense.",
            "When ball possession is regained, defenders will fall back to a supportive position, " +
            "while the attacking players will position themselves to receive a long ball.",
            "When ball possession is lost, players will fall back to form a defensive block as " +
            "soon as possible."),
        new(4, "Out Wide",
            // all.str [46363..46366]
            "Players will focus on attacking down the flanks and crossing the ball to create " +
            "goalscoring opportunities.\nWhen players notice the ball is in a good position to be " +
            "crossed into the area, they will dash into position to try and score a goal.",
            "The defensive block will be focused in the midfield, allowing players to adapt to " +
            "the game state with ease.",
            "When ball possession is regained, players will tend to open wide to the sides.\n" +
            "Even those who are positioned in the centre of the pitch will slide a bit to the " +
            "sides to provide support.",
            "When ball possession is lost, players will focus on forming a defensive block in the " +
            "midfield, then adapt their formation according to the game state."),
        new(5, "Overload",
            // Konami ships no movement text for Overload in the PC string files (its Dream Team
            // description is served online) — stated plainly rather than invented.
            "The game's PC files carry no movement description for Overload — Konami serves its " +
            "Dream Team text online. It is the all-out attacking Team Playstyle (style value 5, " +
            "used by 22 shipped teams)."),
    };

    // Player roles (Playing Styles): descriptions VERBATIM from eFootball's string table
    // (all.str [37199..37218]), and each role is offered EXACTLY for the game's own
    // "Compatible positions" — not a category approximation. Names stay the verified
    // style-table keys, so every role here is proven to write into Player.bin.
    private static readonly RoleOption Basic =
        new("Basic", "No specialised style — clears the player's role.");

    private sealed record RoleDef(string Name, string Description, string[] Compatible);

    private static readonly RoleDef[] RoleCatalog =
    {
        new("Goal Poacher",
            "A player who is skilled at running into space between the defenders and keeper. " +
            "Try to score goals with well-timed runs.\nCompatible positions: CF",
            new[] { "CF" }),
        new("Dummy Runner",
            "A player who acts as a decoy to draw off defenders and create space for teammates " +
            "to attack. This playing style elevates the play of teammates.\nCompatible positions: CF/SS/AMF",
            new[] { "CF", "SS", "AMF" }),
        new("Fox in the Box",
            "A player who waits in the centre for the ball. He is often in position to receive " +
            "crosses in the centre, so take advantage and go for goal.\nCompatible positions: CF",
            new[] { "CF" }),
        new("Target Man",
            "A player that positions himself at the front as a target man. Can initiate " +
            "counter-attacks and hold the ball high up the pitch.\nCompatible positions: CF",
            new[] { "CF" }),
        new("Deep-Lying Forward",
            "A forward player that is willing to fall back to receive the ball and help build " +
            "opportunities. Drives the play to create goal-scoring chances.\nCompatible positions: CF/SS",
            new[] { "CF", "SS" }),
        new("Creative Playmaker",
            "A player who takes advantage of any opening in the defence to initiate attacks and " +
            "provide final balls.\nCompatible positions: SS/RWF/LWF/AMF/RMF/LMF",
            new[] { "SS", "RWF", "LWF", "AMF", "RMF", "LMF" }),
        new("Prolific Winger",
            "A player who stays near the touchline to receive passes, skilled at dribbling past " +
            "defenders. Also cuts into the centre looking for shots on goal.\nCompatible positions: RWF/LWF",
            new[] { "RWF", "LWF" }),
        new("Roaming Flank",
            "A player more effective in a somewhat central position, rather that out by the " +
            "touchline. Effective in attacks accompanied by full-backs and at breaking though " +
            "the centre.\nCompatible positions: RWF/LWF/RMF/LMF",
            new[] { "RWF", "LWF", "RMF", "LMF" }),
        new("Cross Specialist",
            "A player who hugs the touchline, waiting for a chance to cross the ball in. As a " +
            "skilled crosser, he works best with central players who are strong headers of the " +
            "ball.\nCompatible positions: RWF/LWF/RMF/LMF/RB/LB",
            new[] { "RWF", "LWF", "RMF", "LMF", "RB", "LB" }),
        new("Classic No. 10",
            "A playmaker who initiates attacks near the opponent's penalty area. Will go for " +
            "goal himself when the opportunity presents.\nCompatible positions: SS/AMF",
            new[] { "SS", "AMF" }),
        new("Hole Player",
            "A player who heads straight for goal when his team is on the attack. Goal " +
            "opportunities are increased with a teammate who can hold the ball high up the " +
            "pitch.\nCompatible positions: SS/AMF/RMF/LMF/CMF",
            new[] { "SS", "AMF", "RMF", "LMF", "CMF" }),
        new("Box-to-Box",
            "A player who tirelessly covers every blade of grass.\nCompatible positions: RMF/LMF/CMF/DMF",
            new[] { "RMF", "LMF", "CMF", "DMF" }),
        new("Anchor Man",
            "A defensive midfielder who sits deep, and helps out in both defence and attack.\n" +
            "Compatible positions: DMF",
            new[] { "DMF" }),
        new("Orchestrator",
            "A player who initiates attacks from positions deep in his own half.\n" +
            "Compatible positions: CMF/DMF",
            new[] { "CMF", "DMF" }),
        new("Build Up",
            "A player who likes to build up attacks from the back, and also looks to make long " +
            "forward passes.\nCompatible positions: CB",
            new[] { "CB" }),
        new("Extra Frontman",
            "A defender who likes to join in the attack.\nCompatible positions: CB",
            new[] { "CB" }),
        new("Attacking Full-back",
            "An attack-minded full-back who will run upfield and join the attack when presented " +
            "with a chance.\nCompatible positions: RB/LB",
            new[] { "RB", "LB" }),
        new("Defensive Full-back",
            "A solid full-back who prefers to stay back and stick to defensive duties.\n" +
            "Compatible positions: RB/LB",
            new[] { "RB", "LB" }),
        new("Full-back Finisher",
            "An attacking full-back who enjoys joining the attack in high central areas.\n" +
            "Compatible positions: RB/LB",
            new[] { "RB", "LB" }),
    };

    private readonly Session _s;

    // Per-phase token state: geometry + per-slot position label for Main (0) and Sub (1).
    // Player identity/role live on the shared tokens; only the shape differs per phase.
    private readonly (double Left, double Top, string Position)[][] _phase = new (double, double, string)[2][];

    public TacticsViewModel(Session s)
    {
        _s = s;
        foreach (var st in StyleCatalog) Styles.Add(st);
        foreach (var p in AllPositions) Positions.Add(p);
        foreach (var f in s.FormationOptions()) Templates.Add(new FormationOption(f.Shape, f.Id));

        var tactics = s.Repo.TeamTactics(s.CurrentTeamId);
        var styleIx = tactics.FirstOrDefault(t => t.Phase == 0)?.Style ?? 0;
        _selectedStyle = styleIx >= 0 && styleIx < Styles.Count ? Styles[styleIx] : Styles[0];
        _fluid = s.SavedFluid();

        var (fid0, fid1) = s.OwnFormationIds();
        var main = s.Repo.FormationSlots(fid0).OrderBy(sl => sl.SlotIndex).ToList();
        var sub = s.Repo.FormationSlots(fid1).OrderBy(sl => sl.SlotIndex).ToList();
        if (sub.Count != main.Count) sub = main;

        _phase[0] = main.Select(sl => (LeftFor(sl.Y), TopFor(sl.X), Visuals.RoleCodeLabel(sl.Position)))
                        .ToArray();
        _phase[1] = sub.Select(sl => (LeftFor(sl.Y), TopFor(sl.X), Visuals.RoleCodeLabel(sl.Position)))
                       .ToArray();

        // Tokens fill position-aware: squad slot i (the current XI order) mans formation slot i,
        // labelled with the fid's slot role code — NOT best-rating-first. The rest form the bench.
        var conditions = s.Repo.ConditionsFor(s.CurrentTeamId).ToDictionary(c => c.PlayerId);
        var md = s.NextFixture()?.Matchday ?? 0;
        (int Fatigue, bool Injured) CondOf(int pid)
        {
            conditions.TryGetValue(pid, out var c);
            return (c?.Fatigue ?? 0, c?.InjuredUntilMd is int u && u >= md);
        }

        var squad = _s.Squad().OrderBy(x => x.Slot.Slot).ToList();
        for (var i = 0; i < _phase[0].Length; i++)
        {
            var (left, top, pos) = _phase[0][i];
            PitchPlayer token;
            if (i < squad.Count)
            {
                var (player, slot) = squad[i];
                var (fat, inj) = CondOf(player.Id);
                token = new PitchPlayer(player.Id, slot.SquadNumber, player.Name,
                                        player.OverallRating ?? 0, player.PortraitPath, pos,
                                        _s.RoleOf(player.Id), left, top,
                                        player.Position, _s.LearnedPositions(player.Id), fat, inj);
            }
            else
            {
                token = new PitchPlayer(0, 0, "—", 0, null, pos, "Basic", left, top);
            }
            token.PropertyChanged += OnTokenChanged;
            Players.Add(token);
        }
        foreach (var (player, slot) in squad.Skip(_phase[0].Length))
        {
            var (fat, inj) = CondOf(player.Id);
            Bench.Add(new BenchEntry(player.Id, slot.SquadNumber, player.Name, player.Position,
                                     player.OverallRating ?? 0, player.PortraitPath, fat, inj,
                                     _s.LearnedPositions(player.Id)));
        }
        SelectedPlayer = Players.FirstOrDefault();
        InitTakers();
        Captain = Players.FirstOrDefault(p => p.PlayerId == s.Captain);
        _attack1 = s.InstructionOf("attack1");
        _attack2 = s.InstructionOf("attack2");
        _defence1 = s.InstructionOf("defence1");
        _defence2 = s.InstructionOf("defence2");
        LoadOpponent();
        UpdateYourShape();
    }

    /// <summary>The armband (compiled into PlayerAssignment like the takers).</summary>
    [ObservableProperty] private PitchPlayer? _captain;

    // Right-rail chrome, exactly as the game frames it: crest above the Substitutes list.
    public Avalonia.Media.Imaging.Bitmap? ClubLogo => Visuals.LoadBitmap(_s.LogoPath);
    public bool HasClubLogo => ClubLogo is not null;
    public string ClubName => _s.CurrentTeamName;

    /// <summary>Your current shape label (bottom-left of the pitch, like the game's 4-3-2-1).</summary>
    [ObservableProperty] private string _yourShape = "";

    private void UpdateYourShape()
    {
        try
        {
            YourShape = Formations.ShapeOf(Players.Select(p => GameCoords(p.Left, p.Top).Y));
        }
        catch { /* label only */ }
    }

    // How well a player's abilities suit each role: the abilities a role leans on.
    private static readonly Dictionary<string, string[]> RoleNeeds = new()
    {
        ["Build Up"] = new[] { "low_pass", "lofted_pass", "ball_control" },
        ["Attacking Full-back"] = new[] { "speed", "stamina", "lofted_pass" },
        ["Defensive Full-back"] = new[] { "defensive_awareness", "tackling", "stamina" },
        ["Full-back Finisher"] = new[] { "speed", "finishing", "stamina" },
        ["Cross Specialist"] = new[] { "lofted_pass", "curl", "speed" },
        ["Extra Frontman"] = new[] { "heading", "physical_contact", "finishing" },
        ["Box-to-Box"] = new[] { "stamina", "physical_contact", "ball_control" },
        ["Anchor Man"] = new[] { "defensive_awareness", "tackling", "defensive_engagement" },
        ["Orchestrator"] = new[] { "low_pass", "lofted_pass", "offensive_awareness" },
        ["Creative Playmaker"] = new[] { "low_pass", "dribbling", "offensive_awareness" },
        ["Hole Player"] = new[] { "offensive_awareness", "finishing", "stamina" },
        ["Classic No. 10"] = new[] { "low_pass", "ball_control", "tight_possession" },
        ["Roaming Flank"] = new[] { "dribbling", "speed", "ball_control" },
        ["Prolific Winger"] = new[] { "finishing", "speed", "dribbling" },
        ["Dummy Runner"] = new[] { "offensive_awareness", "speed", "balance" },
        ["Goal Poacher"] = new[] { "offensive_awareness", "finishing", "acceleration" },
        ["Fox in the Box"] = new[] { "finishing", "offensive_awareness", "jumping" },
        ["Target Man"] = new[] { "heading", "physical_contact", "ball_control" },
        ["Deep-Lying Forward"] = new[] { "ball_control", "low_pass", "finishing" },
    };

    public override string Title => "Tactics";
    public override string Icon => "♟️";

    public ObservableCollection<FormationOption> Templates { get; } = new();
    public ObservableCollection<StyleOption> Styles { get; } = new();
    public ObservableCollection<string> Positions { get; } = new();
    public ObservableCollection<RoleOption> Roles { get; } = new();
    public ObservableCollection<PitchPlayer> Players { get; } = new();
    public ObservableCollection<BenchEntry> Bench { get; } = new();

    [ObservableProperty] private FormationOption? _selectedTemplate;
    [ObservableProperty] private StyleOption? _selectedStyle;
    [ObservableProperty] private RoleOption? _selectedRole;
    [ObservableProperty] private bool _fluid;
    [ObservableProperty] private PitchPlayer? _selectedPlayer;

    // Set-piece duties (compiled into the game: fk=8, pk=16, ckl=4, ckr=1 in the flag byte).
    [ObservableProperty] private PitchPlayer? _takerFk;
    [ObservableProperty] private PitchPlayer? _takerPk;
    [ObservableProperty] private PitchPlayer? _takerCkl;
    [ObservableProperty] private PitchPlayer? _takerCkr;

    private void InitTakers()
    {
        PitchPlayer? ById(int? id) =>
            id is null ? null : Players.FirstOrDefault(p => p.PlayerId == id);
        TakerFk = ById(_s.TakerOf("fk"));
        TakerPk = ById(_s.TakerOf("pk"));
        TakerCkl = ById(_s.TakerOf("ckl"));
        TakerCkr = ById(_s.TakerOf("ckr"));
    }
    [ObservableProperty] private BenchEntry? _selectedBench;

    // --- top pill tabs, the game's own three: Lineup | Tactics | Team ------------------

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowLineup))]
    [NotifyPropertyChangedFor(nameof(ShowTacticsTab))]
    [NotifyPropertyChangedFor(nameof(ShowTeam))]
    [NotifyPropertyChangedFor(nameof(Tab0Brush))]
    [NotifyPropertyChangedFor(nameof(Tab1Brush))]
    [NotifyPropertyChangedFor(nameof(Tab2Brush))]
    [NotifyPropertyChangedFor(nameof(Tab0Fg))]
    [NotifyPropertyChangedFor(nameof(Tab1Fg))]
    [NotifyPropertyChangedFor(nameof(Tab2Fg))]
    [NotifyPropertyChangedFor(nameof(DragEnabled))]
    [NotifyPropertyChangedFor(nameof(PitchCaption))]
    private int _section;

    public bool ShowLineup => Section == 0;
    public bool ShowTacticsTab => Section == 1;
    public bool ShowTeam => Section == 2;
    // The game's pill bar: the active tab is a WHITE pill with dark text.
    public Avalonia.Media.IBrush Tab0Brush => SectionBrush(0);
    public Avalonia.Media.IBrush Tab1Brush => SectionBrush(1);
    public Avalonia.Media.IBrush Tab2Brush => SectionBrush(2);
    public Avalonia.Media.IBrush Tab0Fg => SectionFg(0);
    public Avalonia.Media.IBrush Tab1Fg => SectionFg(1);
    public Avalonia.Media.IBrush Tab2Fg => SectionFg(2);
    private Avalonia.Media.IBrush SectionBrush(int i) =>
        Visuals.Brush(Section == i ? "#F2F4F7" : "#22262D");
    private Avalonia.Media.IBrush SectionFg(int i) =>
        Visuals.Brush(Section == i ? "#12161C" : "#C7CEDA");

    [RelayCommand] private void SetSection(string index) => Section = int.Parse(index);

    // --- the Tactics tab's own left menu (Set Formation / Team Playstyle / ...) --------

    // 0 = root menu, 1 = Set Formation, 2 = Team Playstyle, 3 = Individual Instructions,
    // 4 = Sub-Tactic.
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowMenuRoot))]
    [NotifyPropertyChangedFor(nameof(ShowSetFormation))]
    [NotifyPropertyChangedFor(nameof(ShowPlaystyle))]
    [NotifyPropertyChangedFor(nameof(ShowInstructions))]
    [NotifyPropertyChangedFor(nameof(ShowSubTactic))]
    [NotifyPropertyChangedFor(nameof(MenuTitle))]
    [NotifyPropertyChangedFor(nameof(DragEnabled))]
    [NotifyPropertyChangedFor(nameof(PitchCaption))]
    private int _tacticsMenu;

    public bool ShowMenuRoot => TacticsMenu == 0;
    public bool ShowSetFormation => TacticsMenu == 1;
    public bool ShowPlaystyle => TacticsMenu == 2;
    public bool ShowInstructions => TacticsMenu == 3;
    public bool ShowSubTactic => TacticsMenu == 4;

    /// <summary>The yellow context title, exactly as the game names each screen.</summary>
    public string MenuTitle => TacticsMenu switch
    {
        1 => "Set Formation",
        2 => "Team Playstyle",
        3 => "Individual Instructions",
        4 => "Sub-Tactic",
        _ => "Tactics",
    };

    [RelayCommand] private void OpenMenu(string index) => TacticsMenu = int.Parse(index);
    [RelayCommand] private void BackMenu() => TacticsMenu = 0;

    /// <summary>Tokens drag only on the Set Formation screen (the game's Edit Position).</summary>
    public bool DragEnabled => Section == 1 && TacticsMenu == 1;

    /// <summary>The game's own caption line under the pitch, per screen.</summary>
    public string PitchCaption => Section switch
    {
        1 when TacticsMenu == 1 && !Fluid => "Formations can be set separately for attack and defence.",
        1 when TacticsMenu == 1 && ActiveTab == 0 => "Set the formation when attacking.",
        1 when TacticsMenu == 1 => "Set the formation when defending.",
        2 => "Select which players will go forward and join the attack in set pieces.\n" +
             "The value indicates the player's suitability for the role.",
        _ => "",
    };

    // --- Individual Instructions (verbatim from the game's string table) ---------------
    // The live game stores these in the user save, not team data — so they are planning
    // state here (persisted per club in meta), NOT compiled. Names + texts are the game's own.

    public sealed record InstrOption(string Name, string Description);

    public static readonly InstrOption[] AttackInstrOptions =
    {
        new("Off", "No individual attacking instruction."),
        new("Defensive",
            "The instructed player will refrain from pushing forward in attack."),
        new("Anchoring",
            "The instructed player is restricted from drifting out of position horizontally."),
    };

    public static readonly InstrOption[] DefenceInstrOptions =
    {
        new("Off", "No individual defensive instruction."),
        new("Tight Marking",
            "The selected opposition player will be marked much tighter than usual, with the " +
            "marker switching depending on the position.\nSpace tends to open up as the markers " +
            "track the opposition player they're marking. This instruction can only be set when " +
            "in-match."),
        new("Man Marking",
            "The instructed player will perform a tighter man marking on his target.\nSpace " +
            "tends to open up as the markers track the opposition player they're marking. This " +
            "instruction can only be set when in-match."),
        new("Counter Target",
            "The instructed player will stay in the vicinity of the opposition's box rather " +
            "than dropping back to help the defence."),
    };

    public const string InstrNote =
        "eFootball keeps Individual Instructions in your in-game Game Plan save, not in team " +
        "data — set them here to plan, then mirror them in-game before kick-off.";

    // The four slots, exactly as the game lists them.
    [ObservableProperty] private string _attack1 = "Off";
    [ObservableProperty] private string _attack2 = "Off";
    [ObservableProperty] private string _defence1 = "Off";
    [ObservableProperty] private string _defence2 = "Off";

    partial void OnAttack1Changed(string value) => _s.SetInstruction("attack1", value);
    partial void OnAttack2Changed(string value) => _s.SetInstruction("attack2", value);
    partial void OnDefence1Changed(string value) => _s.SetInstruction("defence1", value);
    partial void OnDefence2Changed(string value) => _s.SetInstruction("defence2", value);

    public IReadOnlyList<string> AttackInstrNames { get; } =
        AttackInstrOptions.Select(o => o.Name).ToList();
    public IReadOnlyList<string> DefenceInstrNames { get; } =
        DefenceInstrOptions.Select(o => o.Name).ToList();

    // --- the opponent's mirrored half (the game shows your next opponent's plan) --------

    public ObservableCollection<OppToken> Opponents { get; } = new();
    [ObservableProperty] private string _opponentLabel = "";
    [ObservableProperty] private string _opponentShape = "";

    private void LoadOpponent()
    {
        try
        {
            var next = _s.NextFixture();
            if (next is null) return;
            var oppId = next.HomeTeamId == _s.CurrentTeamId ? next.AwayTeamId : next.HomeTeamId;
            var fid = _s.Repo.TeamTactics(oppId).FirstOrDefault(t => t.Phase == 0)?.FormationId;
            if (fid is null) return;
            var slots = _s.Repo.FormationSlots(fid.Value).OrderBy(sl => sl.SlotIndex).ToList();
            if (slots.Count == 0) return;
            var xi = _s.Repo.Squad(oppId).Where(m => m.Slot is >= 0 and <= 10)
                .OrderBy(m => m.Slot).ToList();
            var players = _s.Repo.SquadPlayers(oppId).ToDictionary(p => p.Id);
            for (var i = 0; i < slots.Count; i++)
            {
                var (left, top) = MirrorPos(slots[i].X, slots[i].Y);
                var pos = Visuals.RoleCodeLabel(slots[i].Position);
                PlayerRow? pl = i < xi.Count && players.TryGetValue(xi[i].PlayerId, out var p) ? p : null;
                var name = pl?.Name ?? "—";
                var surname = name.Contains(' ') ? name[(name.LastIndexOf(' ') + 1)..] : name;
                Opponents.Add(new OppToken(left, top, pos, pl?.OverallRating ?? 0, surname,
                    Visuals.LoadBitmap(pl?.PortraitPath)));
            }
            OpponentLabel = _s.TeamName(oppId);
            OpponentShape = Formations.ShapeOf(slots.Select(sl => sl.Y));
        }
        catch { /* no opponent preview is fine (preseason, season end) */ }
    }

    // --- eFootball-style swapping: click one player, click another, they trade places ---

    private bool _swapping;
    private PitchPlayer? _pendingXi;

    [ObservableProperty] private PitchPlayer? _pickXi;
    [ObservableProperty] private BenchEntry? _pickBench;

    partial void OnPickXiChanged(PitchPlayer? value)
    {
        if (_swapping || value is null) return;
        SelectedPlayer = value;   // keep the roles panel in step
        if (PickBench is not null)
        {
            DoBenchSwap(value, PickBench);
        }
        else if (_pendingXi is not null && !ReferenceEquals(_pendingXi, value))
        {
            DoXiSwap(_pendingXi, value);
        }
        else
        {
            _pendingXi = value;
            SaveStatus = $"{value.Name} picked — now click who he swaps with (XI or bench).";
        }
    }

    partial void OnPickBenchChanged(BenchEntry? value)
    {
        if (_swapping || value is null) return;
        if (_pendingXi is not null)
        {
            DoBenchSwap(_pendingXi, value);
        }
        else if (PickXi is not null)
        {
            DoBenchSwap(PickXi, value);
        }
        else
        {
            SaveStatus = $"{value.Name} picked — now click the starter he replaces.";
        }
    }

    private void ClearPicks()
    {
        _swapping = true;
        PickXi = null;
        PickBench = null;
        _pendingXi = null;
        _swapping = false;
    }

    /// <summary>The game's hard rule at swap time: GK and outfield never trade places.</summary>
    private bool GkRuleBlocks(string slotPosition, string incomingRegistered, string incomingName)
    {
        if (slotPosition == "GK" && incomingRegistered != "GK")
        {
            SaveStatus = $"⛔ {incomingName} is not a goalkeeper — only a GK can take the GK slot.";
            ClearPicks();
            return true;
        }
        if (slotPosition != "GK" && incomingRegistered == "GK")
        {
            SaveStatus = $"⛔ {incomingName} is a goalkeeper — he can't be fielded outfield.";
            ClearPicks();
            return true;
        }
        return false;
    }

    /// <summary>Starter ↔ bench: the bench player takes the starter's slot on the pitch.</summary>
    private void DoBenchSwap(PitchPlayer outgoing, BenchEntry incoming)
    {
        var ix = Players.IndexOf(outgoing);
        var bx = Bench.IndexOf(incoming);
        if (ix < 0 || bx < 0 || outgoing.PlayerId == 0) { ClearPicks(); return; }
        if (GkRuleBlocks(outgoing.Position, incoming.Position, incoming.Name)) return;

        var token = new PitchPlayer(incoming.PlayerId, incoming.Number, incoming.Name,
            incoming.Rating, incoming.PortraitPath, outgoing.Position, _s.RoleOf(incoming.PlayerId),
            outgoing.Left, outgoing.Top, incoming.Position, incoming.Learned,
            incoming.Fatigue, incoming.Injured);
        token.PropertyChanged += OnTokenChanged;
        outgoing.PropertyChanged -= OnTokenChanged;
        _swapping = true;
        Players[ix] = token;
        Bench[bx] = new BenchEntry(outgoing.PlayerId, outgoing.Number, outgoing.Name,
            outgoing.RegisteredPosition, outgoing.Rating, outgoing.PortraitPath,
            outgoing.Fatigue, outgoing.Injured, outgoing.Learned);
        SelectedPlayer = token;
        _swapping = false;
        ClearPicks();
        SaveStatus = $"⇄ {incoming.Name} starts, {outgoing.Name} drops to the bench — Save to lock it in.";
    }

    /// <summary>Starter ↔ starter: the two players trade formation slots (roles travel with them).</summary>
    private void DoXiSwap(PitchPlayer a, PitchPlayer b)
    {
        var ia = Players.IndexOf(a);
        var ib = Players.IndexOf(b);
        if (ia < 0 || ib < 0) { ClearPicks(); return; }
        if (GkRuleBlocks(a.Position, b.RegisteredPosition, b.Name)) return;
        if (GkRuleBlocks(b.Position, a.RegisteredPosition, a.Name)) return;

        PitchPlayer At(PitchPlayer identity, PitchPlayer slot) =>
            new(identity.PlayerId, identity.Number, identity.Name, identity.Rating,
                identity.PortraitPath, slot.Position, identity.Role, slot.Left, slot.Top,
                identity.RegisteredPosition, identity.Learned, identity.Fatigue, identity.Injured);

        var newA = At(b, a);
        var newB = At(a, b);
        newA.PropertyChanged += OnTokenChanged;
        newB.PropertyChanged += OnTokenChanged;
        a.PropertyChanged -= OnTokenChanged;
        b.PropertyChanged -= OnTokenChanged;
        _swapping = true;
        Players[ia] = newA;
        Players[ib] = newB;
        SelectedPlayer = newB;
        _swapping = false;
        ClearPicks();
        SaveStatus = $"⇄ {a.Name} and {b.Name} trade places — Save to lock it in.";
    }

    /// <summary>Let the AI propose an XI (form/fatigue/fit) — you can still edit before saving.</summary>
    [RelayCommand]
    private void SuggestXi()
    {
        var order = _s.SuggestXi();
        if (order.Count == 0) return;
        var byId = _s.Squad().ToDictionary(x => x.Player.Id, x => x);
        var conditions = _s.Repo.ConditionsFor(_s.CurrentTeamId).ToDictionary(c => c.PlayerId);
        var md = _s.NextFixture()?.Matchday ?? 0;

        for (var i = 0; i < Players.Count && i < order.Count; i++)
        {
            if (!byId.TryGetValue(order[i], out var entry)) continue;
            var (player, slot) = entry;
            conditions.TryGetValue(player.Id, out var c);
            var old = Players[i];
            var token = new PitchPlayer(player.Id, slot.SquadNumber, player.Name,
                player.OverallRating ?? 0, player.PortraitPath, old.Position, _s.RoleOf(player.Id),
                old.Left, old.Top, player.Position, _s.LearnedPositions(player.Id),
                c?.Fatigue ?? 0, c?.InjuredUntilMd is int u && u >= md);
            token.PropertyChanged += OnTokenChanged;
            old.PropertyChanged -= OnTokenChanged;
            Players[i] = token;
        }
        Bench.Clear();
        foreach (var pid in order.Skip(Players.Count))
        {
            if (!byId.TryGetValue(pid, out var entry)) continue;
            var (player, slot) = entry;
            conditions.TryGetValue(player.Id, out var c);
            Bench.Add(new BenchEntry(player.Id, slot.SquadNumber, player.Name, player.Position,
                player.OverallRating ?? 0, player.PortraitPath, c?.Fatigue ?? 0,
                c?.InjuredUntilMd is int u2 && u2 >= md, _s.LearnedPositions(player.Id)));
        }
        SelectedPlayer = Players.FirstOrDefault();
        var note = "";
        try { note = _s.AssistantNote(_s.NextFixture()?.Matchday ?? 0); } catch { /* optional */ }
        SaveStatus = "AI suggestion loaded (form, fatigue, fit and injuries considered) — " +
                     "edit as you like, then Save." + (note.Length > 0 ? $"\n{note}" : "");
    }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainTabBrush))]
    [NotifyPropertyChangedFor(nameof(SubTabBrush))]
    [NotifyPropertyChangedFor(nameof(PhaseBanner))]
    [NotifyPropertyChangedFor(nameof(PhaseBrush))]
    [NotifyPropertyChangedFor(nameof(PitchCaption))]
    private int _activeTab;   // 0 = Attacking Formation, 1 = Defensive Formation

    [ObservableProperty]
    private string _saveStatus = "Drag players to reposition, set each one's position & role, then Save.";

    public Avalonia.Media.IBrush MainTabBrush => TabBrush(0);
    public Avalonia.Media.IBrush SubTabBrush => TabBrush(1);

    private Avalonia.Media.IBrush TabBrush(int tab) =>
        Visuals.Brush(ActiveTab == tab ? "#F2F4F7" : "#22262D");

    // The game's phase banner on the pitch: pink "Attack" / teal "Defence".
    public string PhaseBanner => ActiveTab == 0 ? "Attack" : "Defence";
    public Avalonia.Media.IBrush PhaseBrush => Visuals.Brush(ActiveTab == 0 ? "#E83E7B" : "#2EC4A6");

    // --- canvas <-> game coordinate mapping (horizontal, left half) -----------------
    // Game y (advance) -> canvas Left across the left half; game x (width) -> canvas Top.

    private static double LeftFor(int y) => (y - MinY) / (MaxY - MinY) * (HalfW - TokenW);
    private static double TopFor(int x) => (x - MinX) / (MaxX - MinX) * (PitchH - TokenH);

    private static (int X, int Y) GameCoords(double left, double top)
    {
        var y = MinY + left / (HalfW - TokenW) * (MaxY - MinY);
        var x = MinX + top / (PitchH - TokenH) * (MaxX - MinX);
        return ((int)Math.Round(x), (int)Math.Round(y));
    }

    /// <summary>The opponent's mirrored token spot on the right half of the same pitch.</summary>
    private static (double Left, double Top) MirrorPos(int x, int y) =>
        (PitchW - TokenW - LeftFor(y), PitchH - TokenH - TopFor(x));

    // --- Main / Sub tabs ----------------------------------------------------------

    [RelayCommand] private void ShowMain() => SwitchTab(0);
    [RelayCommand] private void ShowSub() { if (Fluid) SwitchTab(1); }

    private void SwitchTab(int tab)
    {
        if (tab == ActiveTab) return;
        SnapshotActive();
        ActiveTab = tab;
        for (var i = 0; i < Players.Count && i < _phase[tab].Length; i++)
        {
            var (left, top, pos) = _phase[tab][i];
            Players[i].Left = left;
            Players[i].Top = top;
            Players[i].Position = pos;
        }
        UpdateYourShape();
    }

    /// <summary>Store the live canvas into the active phase's state (called on tab switch + save).</summary>
    private void SnapshotActive()
    {
        _phase[ActiveTab] = Players.Select(p => (p.Left, p.Top, p.Position)).ToArray();
    }

    partial void OnFluidChanged(bool value)
    {
        if (!value && ActiveTab == 1) SwitchTab(0);
    }

    // --- template loader (geometry only — never saved as an id) --------------------

    partial void OnSelectedTemplateChanged(FormationOption? value)
    {
        if (value is null) return;
        var slots = _s.Repo.FormationSlots(value.Id).OrderBy(sl => sl.SlotIndex).ToList();
        for (var i = 0; i < Players.Count && i < slots.Count; i++)
        {
            Players[i].Left = LeftFor(slots[i].Y);
            Players[i].Top = TopFor(slots[i].X);
            Players[i].Position = Visuals.RoleCodeLabel(slots[i].Position);
        }
        UpdateYourShape();
        SaveStatus = "Formation changed";   // the game's own toast
    }

    // --- selected player + role list ----------------------------------------------

    // The position ComboBox binds HERE, not straight into SelectedPlayer.Position: a direct
    // nested two-way binding writes stale values onto the newly selected player while the
    // selection is switching (players "randomly" changing position, roles wiped). The guard
    // makes selection changes read-only and only user edits write through.
    private bool _syncingSelection;

    [ObservableProperty] private string? _selectedPosition;

    /// <summary>
    /// The game's hard positional rule: goalkeeper and outfield never mix. A registered GK's
    /// position is locked to GK; an outfielder can be registered anywhere EXCEPT GK.
    /// </summary>
    public ObservableCollection<string> PositionChoices { get; } = new();

    private void RefreshPositionChoices()
    {
        PositionChoices.Clear();
        if (SelectedPlayer is null) return;
        if (SelectedPlayer.RegisteredPosition == "GK")
        {
            PositionChoices.Add("GK");
        }
        else
        {
            foreach (var p in AllPositions.Where(p => p != "GK")) PositionChoices.Add(p);
        }
    }

    partial void OnSelectedPositionChanged(string? value)
    {
        if (_syncingSelection || value is null || SelectedPlayer is null) return;
        if (SelectedPlayer.Position != value) SelectedPlayer.Position = value;
    }

    partial void OnSelectedPlayerChanged(PitchPlayer? value)
    {
        _syncingSelection = true;
        RefreshPositionChoices();
        SelectedPosition = value?.Position;
        _syncingSelection = false;
        RefreshRoles();
    }

    private void OnTokenChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (sender == SelectedPlayer && e.PropertyName == nameof(PitchPlayer.Position))
        {
            _syncingSelection = true;
            SelectedPosition = SelectedPlayer.Position;
            _syncingSelection = false;
            RefreshRoles();
        }
    }

    /// <summary>Roles exactly as the game gates them: by the role's Compatible positions.</summary>
    private static RoleOption[] RolesFor(string position)
    {
        var pos = position switch { "LWB" => "LB", "RWB" => "RB", _ => position };
        return new[] { Basic }
            .Concat(RoleCatalog.Where(r => r.Compatible.Contains(pos))
                .Select(r => new RoleOption(r.Name, r.Description)))
            .ToArray();
    }

    private void RefreshRoles()
    {
        Roles.Clear();
        if (SelectedPlayer is null) return;
        var options = RolesFor(SelectedPlayer.Position);

        // ★ role fit from the player's real abilities — the roles that suit him float up.
        var abilities = SelectedPlayer.PlayerId > 0
            ? _s.Repo.Attributes(SelectedPlayer.PlayerId)
            : new Dictionary<string, int>();
        string StarsFor(string role)
        {
            if (!RoleNeeds.TryGetValue(role, out var keys) || abilities.Count == 0) return "";
            var avg = keys.Average(k => abilities.TryGetValue(k, out var v) ? v : 40);
            return avg >= 80 ? "★★★" : avg >= 72 ? "★★" : avg >= 62 ? "★" : "☆";
        }
        var rated = options.Select(o => o with { Stars = StarsFor(o.Name) })
            .OrderBy(o => o.Name == "Basic" ? 0 : 1)
            .ThenByDescending(o => o.Stars.Count(ch => ch == '★'))
            .ToList();
        foreach (var r in rated) Roles.Add(r);

        var current = rated.FirstOrDefault(r => r.Name == SelectedPlayer.Role);
        if (current is null)
        {
            SelectedPlayer.Role = "Basic";   // role from another unit doesn't carry over
            current = rated.First(r => r.Name == "Basic");
        }
        SelectedRole = current;
    }

    partial void OnSelectedRoleChanged(RoleOption? value)
    {
        if (value is not null && SelectedPlayer is not null && SelectedPlayer.Role != value.Name)
            SelectedPlayer.Role = value.Name;
    }

    // --- save ----------------------------------------------------------------------

    [RelayCommand]
    private void SaveTactics()
    {
        SnapshotActive();
        var main = SlotsFor(0);
        var sub = SlotsFor(1);
        if (main.Count == 0)
        {
            SaveStatus = "Nothing to save — no formation slots loaded.";
            return;
        }
        _s.SaveCustomFormation(SelectedStyle?.Index ?? 0, Fluid, main, Fluid ? sub : null);

        // Your XI is YOURS now: persist the token order + bench, and flag it manual so the AI
        // only intervenes for injuries on matchday.
        var order = Players.Where(p => p.PlayerId > 0).Select(p => p.PlayerId)
            .Concat(Bench.Select(b => b.PlayerId)).ToList();
        _s.SaveSquadOrder(order, manual: true);

        // In-Match Roles travel with the save (armband + takers compile into the game).
        _s.Captain = Captain?.PlayerId;
        _s.SetTaker("fk", TakerFk?.PlayerId);
        _s.SetTaker("pk", TakerPk?.PlayerId);
        _s.SetTaker("ckl", TakerCkl?.PlayerId);
        _s.SetTaker("ckr", TakerCkr?.PlayerId);

        var shape = Formations.ShapeOf(main.Select(sl => sl.Y));
        var misfits = Players.Count(p => p.PlayerId > 0 && p.Fit == Fit.Awkward);
        var warn = misfits > 0
            ? $"  ⚠ {misfits} player(s) out of position (red ring) — they'll struggle there."
            : "";
        SaveStatus = $"Saved {shape}, {SelectedStyle?.Name}{(Fluid ? " + Sub shape" : "")} and YOUR " +
                     $"XI — applies in-game on the next compile.{warn}";
    }

    private List<(int Index, int PlayerId, string Position, string Role, int X, int Y)> SlotsFor(int phase)
    {
        var slots = new List<(int, int, string, string, int, int)>();
        for (var i = 0; i < Players.Count && i < _phase[phase].Length; i++)
        {
            var (left, top, pos) = _phase[phase][i];
            var (x, y) = GameCoords(left, top);
            slots.Add((i, Players[i].PlayerId, pos, Players[i].Role, x, y));
        }
        return slots;
    }
}
