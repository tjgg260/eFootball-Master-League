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
    long PlayerId, int Number, string Name, string Position, int Rating, string? PortraitPath,
    int Fatigue, bool Injured, IReadOnlyList<string> Learned)
{
    public Avalonia.Media.IBrush RatingBrush => Visuals.RatingBrush(Rating);
    public string Grade => ML.Core.Development.AttributeKnowledge.Grade(Rating);   // own squad: true letter
    public Avalonia.Media.IBrush CondBrush =>
        Visuals.Brush(Injured ? "#D64545" : Fatigue < 20 ? "#1F9D4D" : Fatigue < 40 ? "#E0A526" : "#D64545");
    public string Tag => Injured ? "INJ" : Fatigue >= 40 ? "TIRED" : "";
    /// <summary>Amber bench flag: leggy but not injured (injury outranks tiredness).</summary>
    public bool IsTired => !Injured && Fatigue >= 40;
    /// <summary>Plain-English condition, for the hover card (never a raw fatigue number).</summary>
    public string CondText =>
        Injured ? "injured" : Fatigue < 20 ? "fresh" : Fatigue < 40 ? "leggy" : "exhausted";
    /// <summary>Hover card: everything the row can't fit — full name, grade, condition, cover.</summary>
    public string Tip => $"{Name} · {Position} · {Grade} · {CondText}" +
        (Learned.Count > 0 ? $" · also covers {string.Join(", ", Learned)}" : "");
    public Avalonia.Media.Imaging.Bitmap? Portrait => Visuals.LoadBitmap(PortraitPath);
    public bool HasPortrait => Portrait is not null;
    public string Mark => Visuals.PlayerMark(Name);
    public Avalonia.Media.IBrush MarkBrush => Visuals.PositionBrush(Position);
}

/// <summary>A draggable player token: identity + condition + positional fit ring.</summary>
public sealed partial class PitchPlayer : ObservableObject
{
    public PitchPlayer(long playerId, int number, string name, int rating, string? portraitPath,
                       string position, string role, double left, double top,
                       string registeredPosition = "", IReadOnlyList<string>? learned = null,
                       int fatigue = 0, bool injured = false,
                       IReadOnlyDictionary<string, int>? abilities = null)
    {
        Abilities = abilities;
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

    public long PlayerId { get; }
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
    public IReadOnlyDictionary<string, int>? Abilities { get; }

    /// <summary>His overall AT THE SLOT he's standing in — a winger dropped in goal is scored on
    /// his goalkeeping (an F), not his wing play. Falls back to native rating without abilities.</summary>
    public int EffectiveRating => ML.Core.Selection.PositionOverall.Of(Abilities, Position) ?? Rating;
    public Avalonia.Media.IBrush RatingBrush => Visuals.RatingBrush(EffectiveRating);
    public string Grade => ML.Core.Development.AttributeKnowledge.Grade(EffectiveRating);

    /// <summary>Condition dot: green fresh, amber leggy, red exhausted/injured.</summary>
    public Avalonia.Media.IBrush CondBrush =>
        Visuals.Brush(Injured ? "#D64545" : Fatigue < 20 ? "#1F9D4D" : Fatigue < 40 ? "#E0A526" : "#D64545");

    /// <summary>Plain-English condition, for the hover card (never a raw fatigue number).</summary>
    public string CondText =>
        Injured ? "injured" : Fatigue < 20 ? "fresh" : Fatigue < 40 ? "leggy" : "exhausted";

    /// <summary>Hover card: the whole token in one line — a 52px chip can't say this much.</summary>
    public string Tip => PlayerId == 0
        ? $"{Position} · empty slot"
        : $"{Name} · {Position} · {Grade} · {CondText} · " +
          (Role == "Basic" ? "no playstyle" : Role);

    public bool ShowInjury => Injured;

    /// <summary>One line for a picker list: who he is, where he plays, how good he is. The
    /// rating is a LETTER, exactly as it is on the token — a picker never shows a number.</summary>
    public string PickerLine => PlayerId == 0
        ? $"— · empty {Position} slot"
        : $"{Surname} · {Position} · {Grade}";

    [ObservableProperty] private double _left;
    [ObservableProperty] private double _top;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Fill))]
    [NotifyPropertyChangedFor(nameof(FitBrush))]
    [NotifyPropertyChangedFor(nameof(EffectiveRating))]
    [NotifyPropertyChangedFor(nameof(Grade))]
    [NotifyPropertyChangedFor(nameof(RatingBrush))]
    [NotifyPropertyChangedFor(nameof(Tip))]
    [NotifyPropertyChangedFor(nameof(PickerLine))]
    private string _position;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Tip))]
    private string _role;

    /// <summary>He is the man the left rail is showing. On Set Formation there used to be NO
    /// sign of a selection anywhere, so clicking a token read as a dead click.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(SelBrush))]
    [NotifyPropertyChangedFor(nameof(NameBrush))]
    private bool _selected;

    /// <summary>Selection outline on the name plate. Unselected is TRANSPARENT rather than a
    /// zero thickness, so picking a player can never nudge the token's layout by a pixel.</summary>
    public Avalonia.Media.IBrush SelBrush => Visuals.Brush(Selected ? "#F5E642" : "#00000000");

    /// <summary>The surname goes the same yellow the game uses for a focused entry.</summary>
    public Avalonia.Media.IBrush NameBrush => Visuals.Brush(Selected ? "#F5E642" : "#FFFFFF");

    /// <summary>The drop target under a drag right now — a highlight, not a selection.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HoverBrush))]
    private bool _dropTarget;

    public Avalonia.Media.IBrush HoverBrush => Visuals.Brush(DropTarget ? "#66F5E642" : "#00000000");

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

/// <summary>
/// The next opponent's token on the mirrored right half of the pitch. Read-only as a LINEUP —
/// you can't move him — but he is a real entity: PlayerId carries his identity so the shared
/// right-click vocabulary (scout, enquiry, shortlist, open in Market) reaches him from here.
/// </summary>
public sealed record OppToken(double Left, double Top, string Pos, int Rating, string Surname,
                              Avalonia.Media.Imaging.Bitmap? Portrait, int Knowledge = 100,
                              long PlayerId = 0, string Name = "")
{
    public bool HasPortrait => Portrait is not null;
    public string Mark => Visuals.PlayerMark(Surname);
    public Avalonia.Media.IBrush MarkBrush => Visuals.PositionBrush(Pos);
    // Opponent overalls are knowledge-gated: "?" until you've scouted or faced them enough.
    public string Grade => ML.Core.Development.AttributeKnowledge.GradeMasked(Rating, Knowledge);
    public Avalonia.Media.IBrush RatingBrush =>
        Knowledge >= 75 ? Visuals.RatingBrush(Rating) : Visuals.Brush("#8A93A2");

    /// <summary>Empty formation slots carry no player — nothing to right-click there.</summary>
    public bool IsKnown => PlayerId > 0;
    public string FullName => Name.Length > 0 ? Name : Surname;
    /// <summary>Hover card. The grade stays masked here exactly as it is on the token.</summary>
    public string Tip => IsKnown
        ? $"{FullName} · {Pos} · {Grade}" + (Knowledge >= 75 ? "" : " · not scouted yet")
        : $"{Pos} · no player in this slot";
}

public sealed partial class TacticsViewModel : PageViewModel, ISaveablePage
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
            // The PC string files carry no movement text for Overload (Konami serves it online);
            // this is Konami's own v6.0.0 Overload description, sourced from its official reveal
            // rather than invented. Style value 5, used by 22 shipped teams.
            "Players concentrate on the same side as the ball to achieve numerical superiority.\n" +
            "In attack this makes short passes easier and lets the team keep possession even in " +
            "crowded areas, breaking lines with quick combinations.",
            "Without the ball the team stays compact and closes the ball-carrier down quickly, " +
            "raising the back line for a high press when attacking in the opponent's half.",
            "When possession is regained, nearby players swarm the ball side to rebuild the " +
            "overload and keep the ball moving through tight spaces.",
            "When possession is lost, players immediately gegenpress — hunting the ball in numbers " +
            "to win it back high up the pitch (a Possession Game + Quick Counter hybrid)."),
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
        new("Offensive Goalkeeper",
            "A goalkeeper who stops shots and also proactively moves out of his area to sweep up " +
            "loose balls and start attacks.\nCompatible positions: GK",
            new[] { "GK" }),
        new("Defensive Goalkeeper",
            "A goalkeeper who stays back on his line and focuses purely on shot-stopping.\n" +
            "Compatible positions: GK",
            new[] { "GK" }),
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
        (int Fatigue, bool Injured) CondOf(long pid)
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
                                        player.Position, _s.LearnedPositions(player.Id), fat, inj,
                                        AttrsOf(player.Id));
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
        // Each Individual Instruction is a pairing — the instruction AND the man carrying it.
        // Both come out of the same "name|pid" meta value ML.Web writes, so a slot set in
        // either front-end loads here complete.
        _attack1 = s.InstructionOf("attack1");
        _attack2 = s.InstructionOf("attack2");
        _defence1 = s.InstructionOf("defence1");
        _defence2 = s.InstructionOf("defence2");
        _attack1Player = XiById(s.InstructionPlayerOf("attack1"));
        _attack2Player = XiById(s.InstructionPlayerOf("attack2"));
        _defence1Player = XiById(s.InstructionPlayerOf("defence1"));
        _defence2Player = XiById(s.InstructionPlayerOf("defence2"));
        LoadOpponent();
        UpdateYourShape();
        Bench.CollectionChanged += (_, _) => OnPropertyChanged(nameof(BenchEmpty));
        Templates.CollectionChanged += (_, _) => OnPropertyChanged(nameof(NoTemplates));
        // Everything above is the screen READING the career file. Nothing it did is an edit,
        // so the unsaved-work guard stays silent until the user actually changes something —
        // a screen you only looked at must never claim you have work to lose.
        _quiet = false;
    }

    /// <summary>The starter with this id, or null when he isn't in the XI (or isn't named).</summary>
    private PitchPlayer? XiById(long playerId) =>
        playerId <= 0 ? null : Players.FirstOrDefault(p => p.PlayerId == playerId);

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

    // --- unsaved work: what leaving this screen would throw away ------------------------
    // Pages are rebuilt from the database on every nav click, so a swap, a drag or a role edit
    // that hasn't been Saved simply vanished. The shell asks first now — but only if the page
    // says it holds something. Dirtiness is therefore tracked HONESTLY: raised where an edit
    // actually happens, cleared by the save, and never raised by the screen reading itself in
    // (or the guard becomes noise everyone learns to dismiss).

    // What changed, in the words the summary uses. Never a field or enum name.
    private const string KindXi = "your XI";
    private const string KindBench = "the bench order";
    private const string KindShape = "the shape";
    private const string KindPositions = "player positions";
    private const string KindRoles = "player playstyles";
    private const string KindStyle = "the team playstyle";
    private const string KindDuties = "the match duties";

    private int _pendingEdits;
    private readonly List<string> _dirtyKinds = new();

    /// <summary>True while an edit is being applied that the career file ALREADY holds — the
    /// initial load, a rebuild after a menu verb, a duty following its player onto a new token.
    /// None of those is unsaved work.</summary>
    private bool _quiet = true;

    public override bool IsDirty => _pendingEdits > 0;

    /// <summary>What Save would write, in words — the shell puts it in front of the user.</summary>
    public override string DirtySummary
    {
        get
        {
            if (_pendingEdits == 0) return "";
            var what = _dirtyKinds.Count == 0 ? "this screen" : JoinWords(_dirtyKinds);
            return _pendingEdits == 1
                ? $"1 unsaved change to {what}"
                : $"{_pendingEdits} unsaved changes to {what}";
        }
    }

    /// <summary>The same sentence on the status strip, so "you have work to lose" is visible
    /// here BEFORE the shell has to ask on the way out.</summary>
    public string DirtyChip => IsDirty ? $"● {DirtySummary}" : "";

    private static string JoinWords(IReadOnlyList<string> parts) => parts.Count switch
    {
        0 => "",
        1 => parts[0],
        2 => $"{parts[0]} and {parts[1]}",
        _ => string.Join(", ", parts.Take(parts.Count - 1)) + " and " + parts[^1],
    };

    /// <summary>Record one edit that only Save will persist. <paramref name="kind"/> is the
    /// plain-English thing that changed ("your XI", "the shape"), never a field name.</summary>
    private void MarkDirty(string kind)
    {
        if (_quiet) return;
        _pendingEdits++;
        if (!_dirtyKinds.Contains(kind)) _dirtyKinds.Add(kind);
        RaiseDirty();
    }

    private void ClearDirty()
    {
        _pendingEdits = 0;
        _dirtyKinds.Clear();
        RaiseDirty();
    }

    private void RaiseDirty()
    {
        OnPropertyChanged(nameof(IsDirty));
        OnPropertyChanged(nameof(DirtySummary));
        OnPropertyChanged(nameof(DirtyChip));
    }

    /// <summary>Run something the career file already knows about without it counting as
    /// unsaved work (restores the previous state, so these can nest).</summary>
    private void Quietly(Action act)
    {
        var was = _quiet;
        _quiet = true;
        try { act(); }
        finally { _quiet = was; }
    }

    /// <summary>The shell's "Save and leave": the same save the Save button runs.</summary>
    public void SaveNow() => SaveTactics();

    // --- the status strip: one line, but not one voice ----------------------------------
    // Every outcome on this screen lands on SaveStatus. A refusal used to look exactly like a
    // success (both assistant-green), so the line carries a SEVERITY now: refused reads danger,
    // caution reads warn, done reads the assistant green, and a plain instruction stays body
    // text. Messages that arrive from the shared entity menus are graded by their own glyph.

    private const int LvlInfo = 0, LvlDone = 1, LvlCaution = 2, LvlRefused = 3;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(StatusBrush))]
    private int _statusLevel = LvlInfo;

    /// <summary>MlDanger / MlWarn / MlSuccessText / MlTextBody, by severity.</summary>
    public Avalonia.Media.IBrush StatusBrush => StatusLevel switch
    {
        LvlRefused => Visuals.Brush("#D64545"),
        LvlCaution => Visuals.Brush("#E0A526"),
        LvlDone => Visuals.Brush("#9FE6B4"),
        _ => Visuals.Brush("#C7CEDA"),
    };

    /// <summary>Say something at a known severity. Text first: the assignment grades itself
    /// from the glyph, and the explicit level then wins.</summary>
    private void Say(string text, int level)
    {
        SaveStatus = text;
        StatusLevel = level;
    }

    /// <summary>Grade a line nobody told us about — including everything the shared right-click
    /// menus hand back — from the refusal/caution glyphs this app already speaks in.</summary>
    partial void OnSaveStatusChanged(string value) =>
        StatusLevel = value is not { Length: > 0 } ? LvlInfo
            : value.Contains('⛔') ? LvlRefused
            : value.Contains('⚠') ? LvlCaution
            : LvlDone;

    public ObservableCollection<FormationOption> Templates { get; } = new();
    public ObservableCollection<StyleOption> Styles { get; } = new();
    public ObservableCollection<string> Positions { get; } = new();
    public ObservableCollection<RoleOption> Roles { get; } = new();
    // Out-of-possession (defensive) roles for the selected player — parity with ML.Web's DefCatalog,
    // sourced from the shared ML.Core.Tactics.RoleCatalog so the two apps can't drift.
    public ObservableCollection<string> SecondaryRoles { get; } = new();
    [ObservableProperty] private string? _selectedSecondaryRole;
    private bool _syncingSecondary;
    public ObservableCollection<PitchPlayer> Players { get; } = new();
    public ObservableCollection<BenchEntry> Bench { get; } = new();

    /// <summary>Empty-state lines (a blank list must explain itself, never show a void).</summary>
    public bool BenchEmpty => Bench.Count == 0;
    public bool NoTemplates => Templates.Count == 0;

    [ObservableProperty] private FormationOption? _selectedTemplate;
    [ObservableProperty] private StyleOption? _selectedStyle;
    [ObservableProperty] private RoleOption? _selectedRole;
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowPhaseFrame))]
    private bool _fluid;

    /// <summary>The pink/teal phase frame only means something when Fluid is on — with a single
    /// shape there is no attack/defence distinction to frame.</summary>
    public bool ShowPhaseFrame => ShowSetFormation && Fluid;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasSelectedPlayer))]
    private PitchPlayer? _selectedPlayer;

    // Set-piece duties (compiled into the game: fk=8, pk=16, ckl=4, ckr=1 in the flag byte).
    [ObservableProperty] private PitchPlayer? _takerFk;
    [ObservableProperty] private PitchPlayer? _takerPk;
    [ObservableProperty] private PitchPlayer? _takerCkl;
    [ObservableProperty] private PitchPlayer? _takerCkr;

    // The armband and the four takers only reach the career file on Save, so changing one here
    // is unsaved work. (Quietly(...) covers the paths that write straight through instead.)
    partial void OnCaptainChanged(PitchPlayer? value) => MarkDirty(KindDuties);
    partial void OnTakerFkChanged(PitchPlayer? value) => MarkDirty(KindDuties);
    partial void OnTakerPkChanged(PitchPlayer? value) => MarkDirty(KindDuties);
    partial void OnTakerCklChanged(PitchPlayer? value) => MarkDirty(KindDuties);
    partial void OnTakerCkrChanged(PitchPlayer? value) => MarkDirty(KindDuties);

    private void InitTakers()
    {
        PitchPlayer? ById(long? id) =>
            id is null ? null : Players.FirstOrDefault(p => p.PlayerId == id);
        TakerFk = ById(_s.TakerOf("fk"));
        TakerPk = ById(_s.TakerOf("pk"));
        TakerCkl = ById(_s.TakerOf("ckl"));
        TakerCkr = ById(_s.TakerOf("ckr"));
    }

    /// <summary>
    /// The XI changed — the armband and set-piece duties must belong to players still on the
    /// pitch. Duties are remapped onto the (possibly rebuilt) starter tokens; a benched captain
    /// hands the armband to the highest-rated starter, a benched taker simply loses the duty.
    /// Returns a status note describing what changed ("" when nothing did) so callers can
    /// append it to SaveStatus.
    /// </summary>
    private string RevalidateInMatchRoles()
    {
        var notes = new List<string>();
        // Handing a duty on is a CONSEQUENCE of an edit that has already been counted — it is
        // never a new piece of unsaved work of its own.
        var was = _quiet;
        _quiet = true;
        try { RevalidateCore(notes); }
        finally { _quiet = was; }
        return notes.Count == 0 ? "" : "  ⚠ " + string.Join("; ", notes) + ".";
    }

    private void RevalidateCore(List<string> notes)
    {
        PitchPlayer? Live(PitchPlayer? cur) =>
            cur is null || cur.PlayerId <= 0
                ? null
                : Players.FirstOrDefault(p => p.PlayerId == cur.PlayerId);

        if (Captain is not null)
        {
            var live = Live(Captain);
            if (live is null)
            {
                var heir = Players.Where(p => p.PlayerId > 0)
                    .OrderByDescending(p => p.EffectiveRating).FirstOrDefault();
                if (Captain.PlayerId > 0)
                {
                    notes.Add(heir is not null
                        ? $"{Captain.Surname} no longer starts — the armband passes to {heir.Surname}"
                        : $"{Captain.Surname} no longer starts — the armband is vacant");
                }
                Captain = heir;
            }
            else if (!ReferenceEquals(live, Captain))
            {
                Captain = live;   // same player, fresh token after a swap — follow him silently
            }
        }

        void Fix(PitchPlayer? cur, string duty, Action<PitchPlayer?> set)
        {
            if (cur is null) return;
            var live = Live(cur);
            if (live is null)
            {
                if (cur.PlayerId > 0) notes.Add($"{cur.Surname} no longer takes {duty}");
                set(null);
            }
            else if (!ReferenceEquals(live, cur))
            {
                set(live);
            }
        }
        Fix(TakerFk, "free kicks", v => TakerFk = v);
        Fix(TakerPk, "penalties", v => TakerPk = v);
        Fix(TakerCkl, "left corners", v => TakerCkl = v);
        Fix(TakerCkr, "right corners", v => TakerCkr = v);

        // An Individual Instruction is nothing without the man carrying it, so it follows him
        // onto his new token — and is dropped, out loud, when he stops starting.
        void FixInstr(string slot, string label, string instr, PitchPlayer? cur,
                      Action<PitchPlayer?> set)
        {
            if (cur is null) return;
            var live = Live(cur);
            if (live is not null && ReferenceEquals(live, cur)) return;
            if (live is null && cur.PlayerId > 0)
                notes.Add($"{cur.Surname} no longer carries the {label} instruction");
            // The picker writes through on change; here WE are the ones writing, so silence it
            // and store the pairing ourselves rather than raising a second status line.
            _syncingInstructions = true;
            set(live);
            _syncingInstructions = false;
            _s.SetInstruction(slot, instr, live?.PlayerId ?? 0);
        }
        FixInstr("attack1", "Attack1", Attack1, Attack1Player, v => Attack1Player = v);
        FixInstr("attack2", "Attack2", Attack2, Attack2Player, v => Attack2Player = v);
        FixInstr("defence1", "Defence1", Defence1, Defence1Player, v => Defence1Player = v);
        FixInstr("defence2", "Defence2", Defence2, Defence2Player, v => Defence2Player = v);
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
    [NotifyPropertyChangedFor(nameof(GeometryEditable))]
    [NotifyPropertyChangedFor(nameof(DragHint))]
    [NotifyPropertyChangedFor(nameof(PitchCaption))]
    private int _section;

    /// <summary>Leaving a screen retires its pending offer — it named a spot on that screen.</summary>
    partial void OnSectionChanged(int value) => ClearZoneOffer();

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
        Visuals.Brush(Section == i ? "#F2F4F7" : "#1A222C");   // inactive = MlSurfaceControl
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
    [NotifyPropertyChangedFor(nameof(GeometryEditable))]
    [NotifyPropertyChangedFor(nameof(DragHint))]
    [NotifyPropertyChangedFor(nameof(PitchCaption))]
    [NotifyPropertyChangedFor(nameof(ShowPhaseFrame))]
    private int _tacticsMenu;

    partial void OnTacticsMenuChanged(int value) => ClearZoneOffer();

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

    /// <summary>
    /// Where dragging a player actually does something. The real game puts drag &amp; drop on the
    /// LINEUP tab as well — drop a man on another man (pitch OR bench) and the two swap — and on
    /// Tactics › Set Formation, where the drop ALSO moves the shape. Anywhere else a press stays
    /// a pure select/menu click. This used to be Set Formation only, which made press-and-drag a
    /// silent no-op on the very tab the pitch opens on.
    /// </summary>
    public bool DragEnabled => Section == 0 || (Section == 1 && TacticsMenu == 1);

    /// <summary>
    /// Where a drop on OPEN GRASS may rewrite the formation. Only Set Formation owns the shape:
    /// on Lineup a drag is a swap gesture, so an off-target drop springs back rather than
    /// silently reshaping the club's saved formation records.
    /// </summary>
    public bool GeometryEditable => Section == 1 && TacticsMenu == 1;

    /// <summary>The drag instructions for the screen you are actually on (the hint used to live
    /// only on Set Formation, so on Lineup nothing said dragging was possible at all).</summary>
    public string DragHint => GeometryEditable
        ? "Drag players on the pitch to edit positions. Drop one on another player — on the " +
          "pitch or in the Substitutes list — to swap the two. The shape saves to YOUR club's " +
          "own formation records."
        : "Drag a player onto another player, or onto a substitute, to swap the two. Drag a sub " +
          "onto the pitch to bring him on. Where players STAND is drawn on Tactics › Set Formation.";

    /// <summary>The game's own caption line under the pitch, per screen.</summary>
    public string PitchCaption => Section switch
    {
        0 => "Drag a player onto another — on the pitch or in the Substitutes list — to swap them.",
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
        "🔒 eFootball keeps Individual Instructions in your in-game Game Plan save, not in team " +
        "data, so these cannot reach the game from here — set them to plan, then mirror them " +
        "in-game before kick-off. Tight Marking and Man Marking are in-match only even there.";

    /// <summary>The picker's own line: an instruction with nobody on it says nothing.</summary>
    public const string InstrWhoNote =
        "An instruction belongs to a player — pick the man who anchors, marks or stays forward. " +
        "The pairing saves the moment you set it; it does not wait for Save.";

    // The four slots, exactly as the game lists them. Each is a PAIRING: the instruction and the
    // man carrying it, stored as "name|pid" — the same encoding ML.Web reads and writes, so a
    // slot set in either front-end shows complete in the other. They are planning state (meta),
    // written the moment they change, which is why they never make the page "unsaved".
    [ObservableProperty] private string _attack1 = "Off";
    [ObservableProperty] private string _attack2 = "Off";
    [ObservableProperty] private string _defence1 = "Off";
    [ObservableProperty] private string _defence2 = "Off";

    [ObservableProperty] private PitchPlayer? _attack1Player;
    [ObservableProperty] private PitchPlayer? _attack2Player;
    [ObservableProperty] private PitchPlayer? _defence1Player;
    [ObservableProperty] private PitchPlayer? _defence2Player;

    /// <summary>True while the screen is writing the pickers itself (a load, or a duty following
    /// its player onto a new token) — those must not re-write meta or speak.</summary>
    private bool _syncingInstructions;

    partial void OnAttack1Changed(string value) =>
        SetSlot("attack1", "Attack1", value, Attack1Player, v => Attack1Player = v);
    partial void OnAttack2Changed(string value) =>
        SetSlot("attack2", "Attack2", value, Attack2Player, v => Attack2Player = v);
    partial void OnDefence1Changed(string value) =>
        SetSlot("defence1", "Defence1", value, Defence1Player, v => Defence1Player = v);
    partial void OnDefence2Changed(string value) =>
        SetSlot("defence2", "Defence2", value, Defence2Player, v => Defence2Player = v);

    partial void OnAttack1PlayerChanged(PitchPlayer? value) =>
        SetSlot("attack1", "Attack1", Attack1, value, v => Attack1Player = v);
    partial void OnAttack2PlayerChanged(PitchPlayer? value) =>
        SetSlot("attack2", "Attack2", Attack2, value, v => Attack2Player = v);
    partial void OnDefence1PlayerChanged(PitchPlayer? value) =>
        SetSlot("defence1", "Defence1", Defence1, value, v => Defence1Player = v);
    partial void OnDefence2PlayerChanged(PitchPlayer? value) =>
        SetSlot("defence2", "Defence2", Defence2, value, v => Defence2Player = v);

    /// <summary>
    /// Store one slot's pairing and say what it now means. "Off" carries nobody, so choosing it
    /// releases the man rather than leaving his name attached to nothing; an instruction with no
    /// man on it is a caution, because it names nobody and therefore does nothing.
    /// </summary>
    private void SetSlot(string slot, string label, string instruction, PitchPlayer? who,
                         Action<PitchPlayer?> setWho)
    {
        if (_syncingInstructions) return;
        // An empty formation slot is not a man, and "Off" carries nobody — either way the name
        // comes off rather than being left attached to nothing.
        var wasEmptySlot = who is { PlayerId: <= 0 };
        if (who is not null && (wasEmptySlot || instruction == "Off"))
        {
            _syncingInstructions = true;
            setWho(null);
            _syncingInstructions = false;
            who = null;
        }
        _s.SetInstruction(slot, instruction, who?.PlayerId ?? 0);
        if (wasEmptySlot)
            Say($"⛔ Nobody is standing in that slot — {label} needs a player, not an empty spot.",
                LvlRefused);
        else if (instruction == "Off")
            Say($"{label} is off — nobody there has an individual instruction.", LvlInfo);
        else if (who is null)
            Say($"{label}: {instruction} — now pick the player who carries it, or it names " +
                "nobody and changes nothing.", LvlCaution);
        else
            Say($"{label}: {who.Surname} carries {instruction}. 🔒 Planning only — mirror it in " +
                "eFootball's own Game Plan before kick-off.", LvlDone);
    }

    /// <summary>Take the man off a slot without touching the instruction on it.</summary>
    [RelayCommand]
    private void ClearInstructionPlayer(string slot)
    {
        switch (slot)
        {
            case "attack1": Attack1Player = null; break;
            case "attack2": Attack2Player = null; break;
            case "defence1": Defence1Player = null; break;
            case "defence2": Defence2Player = null; break;
        }
    }

    public IReadOnlyList<string> AttackInstrNames { get; } =
        AttackInstrOptions.Select(o => o.Name).ToList();
    public IReadOnlyList<string> DefenceInstrNames { get; } =
        DefenceInstrOptions.Select(o => o.Name).ToList();

    // --- the opponent's mirrored half (the game shows your next opponent's plan) --------

    public ObservableCollection<OppToken> Opponents { get; } = new();
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasOpponentLabel))]
    private string _opponentLabel = "";
    public bool HasOpponentLabel => OpponentLabel.Length > 0;

    /// <summary>The next opponent's crest for the right-half header (null = no art, image hidden).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasOpponentLogo))]
    private Avalonia.Media.Imaging.Bitmap? _opponentLogo;
    public bool HasOpponentLogo => OpponentLogo is not null;
    [ObservableProperty] private string _opponentShape = "";

    /// <summary>Why the right half is dark ("" when the opponent preview is populated).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasOpponentNote))]
    private string _opponentNote = "";
    public bool HasOpponentNote => OpponentNote.Length > 0;

    private const string NoDossierNote =
        "No dossier on the next opponent — their half stays dark until your scout reports.";

    /// <summary>The club on the right half — the entity the opponent header's menu acts on.</summary>
    public int OpponentTeamId { get; private set; }

    private void LoadOpponent()
    {
        // Every early exit must LEAVE A VISIBLE TRACE (OpponentNote) — a silently empty half
        // reads as a bug, and did: at MD1 unseeded clubs have no team_tactics row yet.
        Opponents.Clear();
        OppSelected = null;
        OpponentTeamId = 0;
        OpponentNote = "";
        OpponentShape = "";
        OpponentLogo = null;
        try
        {
            var next = _s.NextFixture();
            if (next is null)
            {
                OpponentLabel = "";
                OpponentNote = "No fixture ahead — the opponent half fills in once a match is scheduled.";
                return;
            }
            var oppId = next.HomeTeamId == _s.CurrentTeamId ? next.AwayTeamId : next.HomeTeamId;
            OpponentTeamId = oppId;
            OpponentLabel = _s.TeamName(oppId);
            try { OpponentLogo = Visuals.LoadBitmap(_s.TeamLogoPath(oppId)); } catch { OpponentLogo = null; }
            // The AI manager fields its strongest position-correct XI + a tactic to beat you.
            try { _s.PickBestXiAndTactic(oppId, _s.CurrentTeamId); } catch { /* preview is additive */ }
            var fid = _s.Repo.TeamTactics(oppId).FirstOrDefault(t => t.Phase == 0)?.FormationId;
            var slots = fid is int f
                ? _s.Repo.FormationSlots(f).OrderBy(sl => sl.SlotIndex).ToList()
                : new List<FormationSlotRow>();
            if (slots.Count == 0)
            {
                // MD1 / unseeded club: no tactics row (or empty geometry). Borrow a standard
                // shape for the PREVIEW only — nothing is written back to the opponent.
                var borrowed = _s.FormationOptions().FirstOrDefault();
                if (borrowed.Id != 0)
                    slots = _s.Repo.FormationSlots(borrowed.Id).OrderBy(sl => sl.SlotIndex).ToList();
            }
            var players = _s.Repo.SquadPlayers(oppId).ToDictionary(p => p.Id);
            if (slots.Count == 0 || players.Count == 0)
            {
                OpponentNote = NoDossierNote;
                return;
            }
            var xi = _s.Repo.Squad(oppId).Where(m => m.Slot is >= 0 and <= 10)
                .OrderBy(m => m.Slot).ToList();
            var xiPlayers = xi.Select(m => players.GetValueOrDefault(m.PlayerId))
                .Where(p => p is not null).Cast<PlayerRow>().ToList();
            if (xiPlayers.Count == 0)
            {
                // Squad exists but no XI slots are set (fresh season, AI pick failed):
                // preview their best GK + ten best-rated outfielders instead of a dark half.
                var byRating = players.Values.OrderByDescending(p => p.OverallRating ?? 0).ToList();
                var bestGk = byRating.FirstOrDefault(p => Visuals.PositionCategory(p.Position) == "GK");
                xiPlayers = byRating.Where(p => !ReferenceEquals(p, bestGk)).Take(10).ToList();
                if (bestGk is not null) xiPlayers.Insert(0, bestGk);
            }
            // Assign players to slots by POSITION so a keeper never appears at RB: the GK fills
            // the GK slot; outfielders fill outfield slots matched by category (DEF/MID/FWD).
            var gk = xiPlayers.FirstOrDefault(p => Visuals.PositionCategory(p.Position) == "GK");
            static int Cat(string pos) => Visuals.PositionCategory(pos) switch
            { "DEF" => 0, "MID" => 1, _ => 2 };
            string SlotLabel(int i) => Visuals.RoleCodeLabel(slots[i].Position);
            bool SlotIsGk(int i) => Visuals.PositionCategory(SlotLabel(i)) == "GK";
            var outfield = new Queue<PlayerRow>(xiPlayers.Where(p => !ReferenceEquals(p, gk))
                .OrderBy(p => Cat(p.Position)).ThenByDescending(p => p.OverallRating ?? 0));
            var slotOrder = Enumerable.Range(0, slots.Count).Where(i => !SlotIsGk(i))
                .OrderBy(i => Cat(SlotLabel(i))).ToList();
            var assign = new PlayerRow?[slots.Count];
            for (var k = 0; k < slotOrder.Count && outfield.Count > 0; k++)
                assign[slotOrder[k]] = outfield.Dequeue();
            for (var i = 0; i < slots.Count; i++)
            {
                var (left, top) = MirrorPos(slots[i].X, slots[i].Y);
                var slotIsGk = SlotIsGk(i);
                var pl = slotIsGk ? gk : assign[i];
                var pos = Visuals.RoleCodeLabel(slots[i].Position);
                var name = pl?.Name ?? "—";
                var surname = name.Contains(' ') ? name[(name.LastIndexOf(' ') + 1)..] : name;
                var knowledge = 100;
                if (pl is not null)
                {
                    try { knowledge = _s.FmAttributeMode ? _s.KnowledgeOf(pl.Id) : 100; }
                    catch { knowledge = 100; }
                }
                Opponents.Add(new OppToken(left, top, pos, pl?.OverallRating ?? 0, surname,
                    Visuals.LoadBitmap(pl?.PortraitPath), knowledge, pl?.Id ?? 0, name));
            }
            OpponentShape = Formations.ShapeOf(slots.Select(sl => sl.Y));
        }
        catch
        {
            // A broken read must not crash the screen — but it must be SEEN, not swallowed.
            Opponents.Clear();
            OppSelected = null;
            OpponentShape = "";
            OpponentNote = NoDossierNote;
        }
    }

    // --- the opponent you clicked: a READ-ONLY mini-card beside your own ------------------
    // Your own selection is untouched by it, deliberately: "⇄ Swap with <starter>" in the
    // right-click menus still means the starter YOU picked, not the opponent you just peeked at.

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasOppSelected))]
    [NotifyPropertyChangedFor(nameof(OppCardNote))]
    private OppToken? _oppSelected;

    public bool HasOppSelected => OppSelected is not null;

    public string OppCardNote => OppSelected is null
        ? ""
        : $"{OpponentLabel} · you can look, not pick. Right-click him for scouting, an enquiry " +
          "or the shortlist.";

    [RelayCommand] private void ClearOppSelection() => OppSelected = null;

    // --- the shared right-click vocabulary, wired to this screen's entities ----------------
    // Every menu is built fresh per open, so toggle states and the "swap with <name>" label
    // are always current. Status lands on SaveStatus verbatim; refresh re-reads only what the
    // verb can actually have changed.

    /// <summary>One screen-local extra, appended after the shared menu's own separator.</summary>
    private Avalonia.Controls.MenuItem Extra(string header, Action act, bool enabled = true)
    {
        var mi = new Avalonia.Controls.MenuItem { Header = header, IsEnabled = enabled };
        mi.Click += (_, _) =>
        {
            try { act(); }
            catch (Exception ex) { Say(ex.Message, LvlRefused); }   // a failure is not a success
        };
        return mi;
    }

    /// <summary>Right-click on one of YOUR tokens: the shared player menu plus the duties and
    /// the swap that only mean something on a pitch.</summary>
    public Avalonia.Controls.ContextMenu? MenuForXi(PitchPlayer? p)
    {
        if (p is null || p.PlayerId <= 0) return null;   // an empty formation slot is not an entity
        var partner = SelectedPlayer;
        var canSwap = partner is { PlayerId: > 0 } && partner.PlayerId != p.PlayerId;
        var extras = new List<Avalonia.Controls.MenuItem>
        {
            Extra("© Make captain", () =>
            {
                // This verb writes the armband straight through, so it leaves NOTHING unsaved —
                // the pitch just follows what the career file now says.
                Quietly(() => Captain = p);
                _s.Captain = p.PlayerId;   // kept in step with the shared menu's own armband verb
                Say($"© {p.Name} wears the armband.", LvlDone);
            }, Captain?.PlayerId != p.PlayerId),
            Extra("🎯 Penalty taker", () =>
            {
                TakerPk = p;
                Say($"🎯 {p.Name} takes the penalties — Save to lock it in.", LvlDone);
            }, TakerPk?.PlayerId != p.PlayerId),
            Extra("🎯 Free-kick taker", () =>
            {
                TakerFk = p;
                Say($"🎯 {p.Name} takes the free kicks — Save to lock it in.", LvlDone);
            }, TakerFk?.PlayerId != p.PlayerId),
            Extra(canSwap ? $"⇄ Swap with {partner!.Surname}" : "⇄ Swap with selected",
                  () => SwapWithSelected(p), canSwap),
        };
        // Our captain verb also moves the armband on the pitch, so it replaces the shared one.
        return EntityActions.BuildMenu(_s, EntityRef.Player(p.PlayerId, p.Name),
            status: t => SaveStatus = t, refresh: ReloadSquad, extras: extras,
            omit: EntityActions.ItemCaptain);
    }

    /// <summary>Right-click on a bench row: the shared player menu, "bring him on" (which now
    /// NAMES the man it will replace instead of demanding you pick one first), and the bench
    /// order — the keyboard/low-dexterity path to the thing that decides who comes on first.</summary>
    public Avalonia.Controls.ContextMenu? MenuForBench(BenchEntry? b)
    {
        if (b is null || b.PlayerId <= 0) return null;
        var wantGk = b.Position == "GK";
        PitchPlayer? partner =
            SelectedPlayer is { PlayerId: > 0 } sel && (sel.Position == "GK") == wantGk ? sel : null;
        var target = partner ?? WeakestTargetFor(b.Position, out _);
        var ix = Bench.IndexOf(b);
        var extras = new List<Avalonia.Controls.MenuItem>
        {
            Extra(target is null ? "⇄ Bring on" : $"⇄ Bring on for {target.Surname}",
                  () => BringOn(b), target is not null),
            Extra("▲ Move up", () => MoveBench(b, -1), ix > 0),
            Extra("▼ Move down", () => MoveBench(b, +1), ix >= 0 && ix < Bench.Count - 1),
        };
        return EntityActions.BuildMenu(_s, EntityRef.Player(b.PlayerId, b.Name),
            status: t => SaveStatus = t, refresh: ReloadSquad, extras: extras);
    }

    /// <summary>Right-click on an opponent token: the shared FOREIGN player menu (scout, enquiry,
    /// shortlist, open in Market). Refresh re-reads the dossier — scouting unmasks his grade.</summary>
    public Avalonia.Controls.ContextMenu? MenuForOpponent(OppToken? o)
    {
        if (o is null || !o.IsKnown) return null;
        return EntityActions.BuildMenu(_s, EntityRef.Player(o.PlayerId, o.FullName),
            status: t => SaveStatus = t, refresh: LoadOpponent);
    }

    /// <summary>The opponent half's header: the club itself (view squad, scout, head-to-head).</summary>
    public Avalonia.Controls.ContextMenu? MenuForOpponentClub()
    {
        if (OpponentTeamId <= 0) return null;
        return EntityActions.BuildMenu(_s, EntityRef.Club(OpponentTeamId, OpponentLabel),
            status: t => SaveStatus = t, refresh: LoadOpponent);
    }

    /// <summary>Menu swap: trade the right-clicked starter with the one you have selected.</summary>
    private void SwapWithSelected(PitchPlayer p)
    {
        if (SelectedPlayer is not { PlayerId: > 0 } sel || sel.PlayerId == p.PlayerId)
        {
            Say("Pick the starter he swaps with first — left-click him on the pitch.", LvlCaution);
            return;
        }
        DoXiSwap(sel, p);
    }

    /// <summary>
    /// Bench double-tap / menu / drop: this sub takes a starter's slot. With a legal starter
    /// selected it is that man. Without one it no longer lectures — most people double-tap the
    /// sub FIRST — so the weakest starter he actually covers comes off and the status line names
    /// him. It refuses only when there is genuinely no legal target, and then it says which.
    /// The GK rule lives inside DoBenchSwap, so it is enforced here too.
    /// </summary>
    public void BringOn(BenchEntry? b)
    {
        if (b is null || b.PlayerId <= 0) return;
        var wantGk = b.Position == "GK";
        // A selected starter on the wrong side of the goalkeeper line is not a target — fall
        // through to the automatic pick rather than bouncing off the GK rule.
        PitchPlayer? target =
            SelectedPlayer is { PlayerId: > 0 } sel && (sel.Position == "GK") == wantGk ? sel : null;
        var picked = target is null;
        if (target is null)
        {
            target = WeakestTargetFor(b.Position, out var why);
            if (target is null)
            {
                SaveStatus = $"⛔ {b.Name} can't come on — {why}.";
                return;
            }
        }
        var chosen = target;
        DoBenchSwap(target, b);
        // Only re-word a swap that actually happened — a refusal inside DoBenchSwap has already
        // put its own ⛔ line up, and must not be papered over.
        if (picked && Players.Any(p => p.PlayerId == b.PlayerId))
        {
            Say($"⇄ {b.Name} starts for {chosen.Name} — the weakest {chosen.Position} " +
                "in your XI. Pick a starter on the pitch first if you meant someone " +
                "else. Save to lock it in.", LvlDone);
        }
    }

    /// <summary>
    /// The refresh the shared menu calls after a verb. It deliberately does NOT rebuild the XI
    /// while the squad still holds the same players: a rebuild reads the SAVED order back and
    /// would silently throw away swaps you haven't pressed Save on yet. Only a verb that
    /// actually changes who is at the club (loan out, demote, release) rebuilds.
    /// </summary>
    public void ReloadSquad()
    {
        // Everything here is the screen catching up with what the career file ALREADY says, so
        // none of it counts as unsaved work of the user's.
        Quietly(ReloadSquadCore);
    }

    private void ReloadSquadCore()
    {
        // The shared menu can hand the armband over behind our back — follow it.
        var armband = Players.FirstOrDefault(p => p.PlayerId > 0 && p.PlayerId == _s.Captain);
        if (armband is not null && !ReferenceEquals(armband, Captain)) Captain = armband;

        List<(PlayerRow Player, SquadMemberRow Slot)> squad;
        try { squad = _s.Squad().OrderBy(x => x.Slot.Slot).ToList(); }
        catch { return; }

        var onScreen = Players.Where(p => p.PlayerId > 0).Select(p => p.PlayerId)
            .Concat(Bench.Select(b => b.PlayerId)).ToHashSet();
        if (onScreen.SetEquals(squad.Select(x => x.Player.Id))) return;   // nobody left — keep your XI

        var conditions = _s.Repo.ConditionsFor(_s.CurrentTeamId).ToDictionary(c => c.PlayerId);
        var md = _s.NextFixture()?.Matchday ?? 0;
        (int Fatigue, bool Injured) CondOf(long pid)
        {
            conditions.TryGetValue(pid, out var c);
            return (c?.Fatigue ?? 0, c?.InjuredUntilMd is int u && u >= md);
        }

        var keep = SelectedPlayer?.PlayerId ?? 0;
        _swapping = true;
        for (var i = 0; i < Players.Count; i++)
        {
            var old = Players[i];
            PitchPlayer token;
            if (i < squad.Count)
            {
                var (player, slot) = squad[i];
                var (fat, inj) = CondOf(player.Id);
                token = new PitchPlayer(player.Id, slot.SquadNumber, player.Name,
                                        player.OverallRating ?? 0, player.PortraitPath, old.Position,
                                        _s.RoleOf(player.Id), old.Left, old.Top,
                                        player.Position, _s.LearnedPositions(player.Id), fat, inj,
                                        AttrsOf(player.Id));
            }
            else
            {
                token = new PitchPlayer(0, 0, "—", 0, null, old.Position, "Basic", old.Left, old.Top);
            }
            token.PropertyChanged += OnTokenChanged;
            old.PropertyChanged -= OnTokenChanged;
            Players[i] = token;
        }
        Bench.Clear();
        foreach (var (player, slot) in squad.Skip(Players.Count))
        {
            var (fat, inj) = CondOf(player.Id);
            Bench.Add(new BenchEntry(player.Id, slot.SquadNumber, player.Name, player.Position,
                                     player.OverallRating ?? 0, player.PortraitPath, fat, inj,
                                     _s.LearnedPositions(player.Id)));
        }
        _swapping = false;
        ClearPicks();
        SelectedPlayer = Players.FirstOrDefault(p => p.PlayerId > 0 && p.PlayerId == keep)
                         ?? Players.FirstOrDefault(p => p.PlayerId > 0)
                         ?? Players.FirstOrDefault();
        Captain = Players.FirstOrDefault(p => p.PlayerId == _s.Captain);
        InitTakers();
        UpdateYourShape();
    }

    // --- selecting vs swapping are now SEPARATE actions ---------------------------------
    // A single click only SELECTS a player (to edit his position/playstyle) — it never swaps.
    // Swapping is explicit: press "⇄ Swap" to arm the selected player, then click his partner.
    // This kills the accidental-swap-while-editing problem.

    private bool _swapping;
    private PitchPlayer? _pendingXi;

    [ObservableProperty] private PitchPlayer? _pickXi;
    [ObservableProperty] private BenchEntry? _pickBench;
    [ObservableProperty] private bool _swapArmed;

    partial void OnPickXiChanged(PitchPlayer? value)
    {
        if (_swapping || value is null) return;
        SelectedPlayer = value;                       // single click = select/edit, always
        if (SwapArmed && _pendingXi is not null && !ReferenceEquals(_pendingXi, value))
        {
            DoXiSwap(_pendingXi, value);
            DisarmSwap();
        }
        // not armed → just selected, no swap happens
    }

    partial void OnPickBenchChanged(BenchEntry? value)
    {
        if (_swapping || value is null) return;
        if (SwapArmed && _pendingXi is not null)
        {
            DoBenchSwap(_pendingXi, value);           // armed starter ↔ this bench player
            DisarmSwap();
        }
        else
        {
            Say($"{value.Name} selected. To bring him on: pick a starter, press ⇄ Swap, " +
                "then click him.", LvlInfo);
        }
    }

    /// <summary>Arm the currently-selected starter for a swap; the next click completes it.</summary>
    [RelayCommand]
    private void ArmSwap()
    {
        if (SelectedPlayer is null || SelectedPlayer.PlayerId == 0)
        {
            Say("Pick a starter first, then press ⇄ Swap.", LvlCaution);
            return;
        }
        SwapArmed = true;
        _pendingXi = SelectedPlayer;
        Say($"⇄ {SelectedPlayer.Name} armed — click who he swaps with (a starter or a sub).",
            LvlInfo);
    }

    private void DisarmSwap()
    {
        SwapArmed = false;
        _pendingXi = null;
    }

    private void ClearPicks()
    {
        _swapping = true;
        PickXi = null;
        PickBench = null;
        _pendingXi = null;
        SwapArmed = false;
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
            incoming.Fatigue, incoming.Injured, AttrsOf(incoming.PlayerId));
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
        var roleNote = RevalidateInMatchRoles();
        MarkDirty(KindXi);
        Say($"⇄ {incoming.Name} starts, {outgoing.Name} drops to the bench — Save to lock it in.{roleNote}",
            roleNote.Length > 0 ? LvlCaution : LvlDone);
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
                identity.RegisteredPosition, identity.Learned, identity.Fatigue, identity.Injured,
                identity.Abilities ?? AttrsOf(identity.PlayerId));

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
        var roleNote = RevalidateInMatchRoles();   // duties follow the players onto their new tokens
        MarkDirty(KindXi);
        Say($"⇄ {a.Name} and {b.Name} trade places — Save to lock it in.{roleNote}",
            roleNote.Length > 0 ? LvlCaution : LvlDone);
    }

    // --- drag & drop: what a DROP actually MEANS -----------------------------------------
    // Release used to do nothing but drop the capture, which left the dragged token parked on
    // top of whoever he landed on. GameCoords rounds to ints and the formation writer has no
    // duplicate check, so Save then wrote two slots with identical (X,Y) — an illegal shape,
    // silently. Every branch below either completes a swap and puts BOTH tokens back on slot
    // geometry, or springs the dragged token back and says why. Nothing is left stacked.

    /// <summary>Put a dragged token back on its pre-drag spot (every refusal path uses this).</summary>
    private static void Restore(PitchPlayer token, double left, double top)
    {
        token.Left = left;
        token.Top = top;
    }

    /// <summary>
    /// The starter whose GAME coordinates a spot collides with, or null when it is clear. The
    /// test is on game coords, not canvas pixels, because game coords are what gets written:
    /// two canvas points a few pixels apart still round to the same (X,Y).
    /// </summary>
    private PitchPlayer? Collides(PitchPlayer moving, double left, double top)
    {
        var (x, y) = GameCoords(left, top);
        return Players.FirstOrDefault(p =>
        {
            if (ReferenceEquals(p, moving)) return false;
            var (px, py) = GameCoords(p.Left, p.Top);
            return px == x && py == y;
        });
    }

    /// <summary>Drop one starter on another: they trade slots. Both go back to slot geometry
    /// first, so a completed swap can never leave a token stacked on its partner.</summary>
    public void DropOnStarter(PitchPlayer? dragged, PitchPlayer? target, double left, double top)
    {
        if (dragged is null) return;
        ClearZoneOffer();
        Restore(dragged, left, top);
        if (target is null || ReferenceEquals(dragged, target)) return;
        if (dragged.PlayerId <= 0 && target.PlayerId <= 0) return;   // two empty slots: nothing to trade
        DoXiSwap(dragged, target);
    }

    /// <summary>Drop a starter on a bench row: that substitute comes on, this man goes off.</summary>
    public void DropOnBenchRow(PitchPlayer? dragged, BenchEntry? target, double left, double top)
    {
        if (dragged is null || target is null) return;
        ClearZoneOffer();
        Restore(dragged, left, top);
        if (dragged.PlayerId <= 0)
        {
            Say("That slot is empty — drag a real player onto the bench to take him off.",
                LvlCaution);
            return;
        }
        DoBenchSwap(dragged, target);
    }

    /// <summary>
    /// Drop a starter on empty bench space: he comes off and the substitute who covers HIS slot
    /// best comes on — never a random name, and never across the goalkeeper line.
    /// </summary>
    public void DropOnBenchSpace(PitchPlayer? dragged, double left, double top)
    {
        if (dragged is null) return;
        ClearZoneOffer();
        Restore(dragged, left, top);
        if (dragged.PlayerId <= 0)
        {
            Say("That slot is empty — there is nobody to take off.", LvlCaution);
            return;
        }
        var cover = BestCoverFor(dragged.Position, out var why);
        if (cover is null)
        {
            SaveStatus = $"⛔ {dragged.Surname} stays on — {why}.";
            return;
        }
        DoBenchSwap(dragged, cover);
    }

    /// <summary>
    /// Drop on open grass. Only Set Formation owns the geometry, so anywhere else the token
    /// springs back and the status line says where the shape IS edited. A spot that collapses
    /// onto another man's game coordinates is refused outright rather than written.
    /// </summary>
    public void DropOnPitch(PitchPlayer? dragged, double left, double top)
    {
        if (dragged is null) return;
        ClearZoneOffer();
        if (!GeometryEditable)
        {
            Restore(dragged, left, top);
            Say($"{dragged.Surname} stays where he is — drop him on a teammate or a " +
                "substitute to swap them. Where players stand is drawn on " +
                "Tactics › Set Formation.", LvlInfo);
            return;
        }
        if (Collides(dragged, dragged.Left, dragged.Top) is { } clash)
        {
            Restore(dragged, left, top);
            SaveStatus = $"⛔ That spot is already {clash.Surname}'s — two players can't share one " +
                         "position on the pitch. Drop him beside it instead.";
            return;
        }
        UpdateYourShape();
        MarkDirty(KindShape);
        var (x, y) = GameCoords(dragged.Left, dragged.Top);
        var zone = ZoneAt(x, y);
        if (dragged.PlayerId > 0 && !SamePlace(zone, dragged.Position))
        {
            OfferZone(dragged, zone);
            Say($"{dragged.Surname} moved into the {zone} zone — he is still listed as " +
                $"{dragged.Position}. Save locks the new shape in either way.", LvlCaution);
        }
        else
        {
            Say($"{dragged.Surname} moved — Save to lock the shape in.", LvlDone);
        }
    }

    /// <summary>Drag a substitute onto a starter's token: he comes on in that man's slot.</summary>
    public void DropBenchOnStarter(BenchEntry? dragged, PitchPlayer? target)
    {
        if (dragged is null || target is null) return;
        ClearZoneOffer();
        if (target.PlayerId <= 0)
        {
            Say("Nobody mans that slot yet — drop him on a player to trade places.", LvlCaution);
            return;
        }
        DoBenchSwap(target, dragged);
    }

    /// <summary>Drag a substitute onto open grass: he replaces the starter he covers best.</summary>
    public void DropBenchOnPitch(BenchEntry? dragged)
    {
        if (dragged is null || dragged.PlayerId <= 0) return;
        ClearZoneOffer();
        var target = WeakestTargetFor(dragged.Position, out var why);
        if (target is null)
        {
            SaveStatus = $"⛔ {dragged.Name} can't come on — {why}.";
            return;
        }
        DoBenchSwap(target, dragged);
    }

    // --- bench ORDER: who comes on first ---------------------------------------------------
    // The bench was a plain list with nothing but a selection binding, so the order that decides
    // your first substitution was unreachable. It rides out on the same SaveSquadOrder call as
    // the XI (Players first, Bench after), so a reorder survives Save.

    private void MoveBenchTo(BenchEntry b, int to)
    {
        var from = Bench.IndexOf(b);
        if (from < 0 || Bench.Count == 0) return;
        to = Math.Clamp(to, 0, Bench.Count - 1);
        if (to == from) return;
        _swapping = true;      // a Move re-raises the list's selection; don't read that as a pick
        Bench.Move(from, to);
        _swapping = false;
        MarkDirty(KindBench);
        Say($"↕ {b.Name} is now substitute #{to + 1}. Bench order is who comes on first, " +
            "and it saves with your XI.", LvlDone);
    }

    /// <summary>Menu / keyboard path: nudge a substitute one place up or down the bench.</summary>
    public void MoveBench(BenchEntry? b, int delta)
    {
        if (b is null) return;
        var from = Bench.IndexOf(b);
        if (from < 0) return;
        MoveBenchTo(b, from + delta);
    }

    /// <summary>Drag path: drop a substitute on another bench row to take that place in the order.</summary>
    public void ReorderBench(BenchEntry? dragged, BenchEntry? onto)
    {
        if (dragged is null || onto is null || ReferenceEquals(dragged, onto)) return;
        var to = Bench.IndexOf(onto);
        if (to < 0) return;
        MoveBenchTo(dragged, to);
    }

    /// <summary>
    /// The starter a substitute replaces when you haven't named one: the weakest man in the XI he
    /// actually covers, scored on the effective rating this screen already shows (his overall AT
    /// THAT SLOT). Exact slot first, then the same unit, then any legal starter — and never
    /// across the goalkeeper line. Null means there is genuinely no legal target, and
    /// <paramref name="why"/> says which.
    /// </summary>
    private PitchPlayer? WeakestTargetFor(string registered, out string why)
    {
        var wantGk = registered == "GK";
        var legal = Players.Where(p => p.PlayerId > 0 && (p.Position == "GK") == wantGk).ToList();
        if (legal.Count == 0)
        {
            why = wantGk
                ? "there is no goalkeeper in your XI for him to replace"
                : "there is no outfield starter in your XI to take off";
            return null;
        }
        why = "";
        var exact = legal.Where(p => SamePlace(p.Position, registered)).ToList();
        var unit = exact.Count > 0
            ? exact
            : legal.Where(p => Visuals.PositionCategory(p.Position) ==
                               Visuals.PositionCategory(registered)).ToList();
        var band = unit.Count > 0 ? unit : legal;
        return band.OrderBy(p => p.EffectiveRating).ThenBy(p => p.Surname).First();
    }

    /// <summary>
    /// The substitute who covers a slot best: fit first (natural, then same unit), then his
    /// overall AT THAT SLOT. Injured men sort last but stay eligible — offering the only legal
    /// cover beats refusing without a word. Never across the goalkeeper line.
    /// </summary>
    private BenchEntry? BestCoverFor(string slotPosition, out string why)
    {
        var wantGk = slotPosition == "GK";
        var legal = Bench.Where(b => b.PlayerId > 0 && (b.Position == "GK") == wantGk).ToList();
        if (legal.Count == 0)
        {
            why = wantGk
                ? "there is no goalkeeper on the bench to take his place"
                : "there is no outfield substitute on the bench to take his place";
            return null;
        }
        why = "";
        return legal
            .OrderBy(b => b.Injured ? 1 : 0)
            .ThenBy(b => (int)PositionFit.Of(b.Position, b.Learned.ToArray(), slotPosition))
            .ThenByDescending(b => PositionOverall.Of(AttrsOf(b.PlayerId), slotPosition) ?? b.Rating)
            .First();
    }

    // --- pitch zones: what the SHAPE says a spot is ----------------------------------------
    // Geometry and the position LABEL stay independent on purpose — a CMF pushed forward is
    // still a CMF unless you say otherwise. This only lets the screen SAY when the two disagree
    // and offer the change, instead of a token in the DMF zone silently reading CMF forever.
    // Axis ground truth is the game's own formation tables (tools/career_seed.py FALLBACK_SHAPES):
    // x = width 12..92 with LOW = your left touchline, y = advance 3..43 with 3 on your goal line.

    public static string ZoneAt(int x, int y)
    {
        var wide = x <= 26 ? -1 : x >= 78 ? 1 : 0;
        if (y <= 6) return "GK";
        if (y <= 18) return wide < 0 ? "LB" : wide > 0 ? "RB" : "CB";
        if (y <= 24) return wide < 0 ? "LWB" : wide > 0 ? "RWB" : "DMF";
        if (y <= 30) return wide < 0 ? "LMF" : wide > 0 ? "RMF" : "CMF";
        if (y <= 36) return wide < 0 ? "LMF" : wide > 0 ? "RMF" : "AMF";
        if (y <= 38) return wide < 0 ? "LWF" : wide > 0 ? "RWF" : "SS";
        return wide < 0 ? "LWF" : wide > 0 ? "RWF" : "CF";
    }

    /// <summary>LB/LWB (and RB/RWB) are one spot under two names — never nag about those.</summary>
    private static bool SamePlace(string a, string b) =>
        a == b
        || (a is "LB" or "LWB" && b is "LB" or "LWB")
        || (a is "RB" or "RWB" && b is "RB" or "RWB");

    // The zone offer: a drop that disagrees with the label SAYS so and offers the change. It
    // never rewrites the label behind your back.
    private PitchPlayer? _zoneToken;
    private string _zoneWanted = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasZoneOffer))]
    private string _zoneOffer = "";
    public bool HasZoneOffer => ZoneOffer.Length > 0;

    [ObservableProperty] private string _zoneOfferAccept = "";
    [ObservableProperty] private string _zoneOfferKeep = "";

    private void OfferZone(PitchPlayer token, string zone)
    {
        _zoneToken = token;
        _zoneWanted = zone;
        ZoneOfferAccept = $"Change to {zone}";
        ZoneOfferKeep = $"Keep {token.Position}";
        ZoneOffer = $"{token.Surname} now stands in the {zone} zone but is still listed as " +
                    $"{token.Position}. Where he stands and what he is listed as are separate — " +
                    "change the label only if you mean to.";
    }

    private void ClearZoneOffer()
    {
        _zoneToken = null;
        _zoneWanted = "";
        ZoneOffer = "";
        ZoneOfferAccept = "";
        ZoneOfferKeep = "";
    }

    /// <summary>Take the offer: the label follows the man into his new zone.</summary>
    [RelayCommand]
    private void AcceptZoneOffer()
    {
        var token = _zoneToken;
        var zone = _zoneWanted;
        ClearZoneOffer();
        if (token is null || zone.Length == 0) return;
        if (token.RegisteredPosition == "GK" || zone == "GK")
        {
            SaveStatus = "⛔ Goalkeeper and outfield never trade labels — that one stays as it is.";
            return;
        }
        token.Position = zone;   // OnTokenChanged re-syncs the picker and the role list
        MarkDirty(KindPositions);
        Say($"{token.Surname} is listed as {zone} — Save to lock it in.", LvlDone);
    }

    /// <summary>Decline it: geometry moved, the label stays. That is a legal, deliberate shape.</summary>
    [RelayCommand]
    private void DismissZoneOffer()
    {
        var token = _zoneToken;
        ClearZoneOffer();
        if (token is not null)
            Say($"{token.Surname} keeps his {token.Position} listing in the new spot.", LvlInfo);
    }

    /// <summary>A player's abilities for position-adjusted grades; null degrades to native rating.</summary>
    private IReadOnlyDictionary<string, int>? AttrsOf(long pid)
    {
        try { return pid > 0 ? _s.Repo.Attributes(pid) : null; } catch { return null; }
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
                c?.Fatigue ?? 0, c?.InjuredUntilMd is int u && u >= md, AttrsOf(player.Id));
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
        var roleNote = RevalidateInMatchRoles();   // a benched captain/taker must not keep the duty
        var note = "";
        try { note = _s.AssistantNote(_s.NextFixture()?.Matchday ?? 0); } catch { /* optional */ }
        MarkDirty(KindXi);   // a proposed XI is still only in memory until Save
        Say("AI suggestion loaded (form, fatigue, fit and injuries considered) — " +
            "edit as you like, then Save." + roleNote + (note.Length > 0 ? $"\n{note}" : ""),
            roleNote.Length > 0 ? LvlCaution : LvlDone);
    }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(MainTabBrush))]
    [NotifyPropertyChangedFor(nameof(SubTabBrush))]
    [NotifyPropertyChangedFor(nameof(MainTabFg))]
    [NotifyPropertyChangedFor(nameof(SubTabFg))]
    [NotifyPropertyChangedFor(nameof(PhaseBanner))]
    [NotifyPropertyChangedFor(nameof(PhaseBrush))]
    [NotifyPropertyChangedFor(nameof(PitchCaption))]
    private int _activeTab;   // 0 = Attacking Formation, 1 = Defensive Formation

    [ObservableProperty]
    private string _saveStatus = "Set your XI, positions and roles, then Save to lock them in.";

    public Avalonia.Media.IBrush MainTabBrush => TabBrush(0);
    public Avalonia.Media.IBrush SubTabBrush => TabBrush(1);
    public Avalonia.Media.IBrush MainTabFg => TabFg(0);
    public Avalonia.Media.IBrush SubTabFg => TabFg(1);

    private Avalonia.Media.IBrush TabBrush(int tab) =>
        Visuals.Brush(ActiveTab == tab ? "#F2F4F7" : "#1A222C");
    private Avalonia.Media.IBrush TabFg(int tab) =>
        Visuals.Brush(ActiveTab == tab ? "#12161C" : "#C7CEDA");

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
        MarkDirty(KindShape);
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
        MarkDirty(KindShape);
        Say("Formation changed", LvlDone);   // the game's own toast
    }

    partial void OnSelectedStyleChanged(StyleOption? value) => MarkDirty(KindStyle);

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
        if (SelectedPlayer.Position == value) return;
        SelectedPlayer.Position = value;
        MarkDirty(KindPositions);
    }

    partial void OnSelectedPlayerChanged(PitchPlayer? value)
    {
        // The TOKEN says who the rail is showing. On Set Formation nothing in the rail changed
        // on a click, so picking a player looked like a dead click; the marker fixes that even
        // before the rail's own mini-card is on screen.
        foreach (var p in Players) p.Selected = ReferenceEquals(p, value);
        _syncingSelection = true;
        RefreshPositionChoices();
        SelectedPosition = value?.Position;
        _syncingSelection = false;
        RefreshRoles();
        // A squad-wide overwrite armed while looking at one player must not still be loaded
        // when the user has moved on to another.
        DisarmAutoRoles();
    }

    /// <summary>The selected man's identity for the rail on screens without the full Lineup card
    /// (Set Formation shows the pitch, so it has to show WHO you clicked too).</summary>
    public bool HasSelectedPlayer => SelectedPlayer is { PlayerId: > 0 };

    private void OnTokenChanged(object? sender, PropertyChangedEventArgs e)
    {
        // Both sides can be null (a cleared selection raising a late event) — compare as
        // objects so a null==null match can never dereference.
        if (sender is PitchPlayer token && ReferenceEquals(token, SelectedPlayer)
            && e.PropertyName == nameof(PitchPlayer.Position))
        {
            _syncingSelection = true;
            SelectedPosition = token.Position;
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

    /// <summary>True while the role list is being rebuilt for a newly selected player — the
    /// SelectedRole write that follows is the screen catching up, not a choice the user made.</summary>
    private bool _refreshingRoles;

    private void RefreshRoles()
    {
        var was = _refreshingRoles;
        _refreshingRoles = true;
        try { RefreshRolesCore(); }
        finally { _refreshingRoles = was; }
    }

    private void RefreshRolesCore()
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

        // Out-of-possession options for this position (shared catalog), with the saved pick.
        _syncingSecondary = true;
        SecondaryRoles.Clear();
        SecondaryRoles.Add("None");
        var pos = SelectedPlayer.Position switch { "LWB" => "LB", "RWB" => "RB", _ => SelectedPlayer.Position };
        foreach (var r in ML.Core.Tactics.RoleCatalog.Secondary.Where(r => r.Positions.Contains(pos)))
            SecondaryRoles.Add(r.Name);
        var savedSec = SelectedPlayer.PlayerId > 0 ? _s.SecondaryRoleOf(SelectedPlayer.PlayerId) : "None";
        SelectedSecondaryRole = SecondaryRoles.Contains(savedSec) ? savedSec : "None";
        _syncingSecondary = false;
    }

    partial void OnSelectedRoleChanged(RoleOption? value)
    {
        if (value is null || SelectedPlayer is null || SelectedPlayer.Role == value.Name) return;
        SelectedPlayer.Role = value.Name;
        // Only a PICK is unsaved work. Re-listing the roles for a newly selected player also
        // lands here, and a screen you only clicked around on must not claim you have work to lose.
        if (!_refreshingRoles) MarkDirty(KindRoles);
    }

    partial void OnSelectedSecondaryRoleChanged(string? value)
    {
        // Persist immediately (like ML.Web's SetDefStyle) — it compiles into Player.bin on install.
        if (_syncingSecondary || value is null || SelectedPlayer is null || SelectedPlayer.PlayerId <= 0)
            return;
        _s.SetSecondaryRole(SelectedPlayer.PlayerId, value);
        // This one writes straight through (like ML.Web's SetDefStyle), so it is never unsaved.
        Say($"{SelectedPlayer.Name}: {(value == "None" ? "no defending role" : value)} out of possession.",
            LvlDone);
    }

    // --- the assistant's role sweep: armed, then fired ----------------------------------
    // AssignRolesFor rewrites BOTH roles of EVERY player in the squad in one committed
    // transaction, hand-set ones included, and there is no undo (SessionRoles.cs says so).
    // So it gets the same two-step confirm as this app's other irreversible verbs.

    private const string AutoRolesIdle = "⚡ Auto-assign roles (AI)";
    private const string AutoRolesArm = "⚡ Sure? Overwrites every role";

    [ObservableProperty] private string _autoRolesLabel = AutoRolesIdle;
    [ObservableProperty] private bool _autoRolesArmed;

    /// <summary>Put the button back to its safe label — a stale "Sure?" must never fire on a
    /// player the user has moved on from.</summary>
    private void DisarmAutoRoles()
    {
        if (!AutoRolesArmed) return;
        AutoRolesArmed = false;
        AutoRolesLabel = AutoRolesIdle;
    }

    /// <summary>Let the AI fill every player's in- and out-of-possession role from their attributes
    /// and the team's chosen playstyle (parity with the AI opponent's behaviour).</summary>
    [RelayCommand]
    private void AutoAssignRoles()
    {
        if (!AutoRolesArmed)
        {
            AutoRolesArmed = true;
            AutoRolesLabel = AutoRolesArm;
            Say("The assistant rewrites the in- AND out-of-possession playstyle of every player " +
                "in the squad, including the ones you set by hand, and it cannot be undone. " +
                "Click again to confirm.", LvlCaution);
            return;
        }
        DisarmAutoRoles();
        _s.AssignRolesFor(_s.CurrentTeamId);

        // The sweep committed both roles for the whole squad to the career file — but the pitch
        // tokens still hold the PRE-sweep playstyle, and Save writes Players[i].Role straight
        // back out. Leaving them stale meant the next Save quietly undid half the assistant's
        // own work while the status line said it had worked. Re-read every token from what was
        // actually committed, so screen and file agree.
        var changed = 0;
        var mismatch = "";
        Quietly(() =>
        {
            foreach (var p in Players)
            {
                if (p.PlayerId <= 0) continue;
                var role = _s.RoleOf(p.PlayerId);
                if (p.Role == role) continue;
                p.Role = role;
                changed++;
            }
            // The rail's two pickers show one man: re-list his in-possession roles and re-read
            // his out-of-possession one, or they would keep showing what he used to be.
            var before = SelectedPlayer?.Role;
            RefreshRoles();
            // The assistant picks on a man's REGISTERED position; this list is gated by the slot
            // he is standing in. When those disagree the list drops his pick back to Basic — say
            // so rather than letting it look like the sweep skipped him.
            if (SelectedPlayer is { PlayerId: > 0 } sel && before is not null && sel.Role != before)
            {
                mismatch = $"  ⚠ {sel.Surname}'s pick ({before}) isn't allowed in the " +
                           $"{sel.Position} slot he is standing in, so he reads Basic — move him " +
                           "or choose from his list.";
            }
        });

        var who = changed == 0
            ? "every starter already had the playstyle it would have chosen"
            : changed == 1
                ? "one starter's playstyle changed on the pitch"
                : $"{changed} starters' playstyles changed on the pitch";
        Say($"⚡ The assistant set both playstyles for the whole squad — {who}. Written to your " +
            $"career already, so there is nothing here left to Save.{mismatch}",
            mismatch.Length > 0 ? LvlCaution : LvlDone);
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
            Say("⛔ Nothing to save — no formation slots loaded.", LvlRefused);
            return;
        }
        // Two slots on one spot is an illegal shape and the formation writer has no duplicate
        // check of its own — it would go into the club's records without a word. Refuse instead.
        var clash = DuplicateSlots(main) ?? (Fluid ? DuplicateSlots(sub) : null);
        if (clash is not null)
        {
            Say($"⛔ Not saved — {clash} are standing on the same spot. Two slots sharing " +
                "one position is an illegal shape; drag one of them clear on " +
                "Tactics › Set Formation, then Save.", LvlRefused);
            return;   // nothing was written, so the page stays dirty on purpose
        }
        _s.SaveCustomFormation(SelectedStyle?.Index ?? 0, Fluid, main, Fluid ? sub : null);

        // Your XI is YOURS now: persist the token order + bench, and flag it manual so the AI
        // only intervenes for injuries on matchday.
        var order = Players.Where(p => p.PlayerId > 0).Select(p => p.PlayerId)
            .Concat(Bench.Select(b => b.PlayerId)).ToList();
        _s.SaveSquadOrder(order, manual: true);

        // In-Match Roles travel with the save (armband + takers compile into the game) — but
        // only STARTERS may hold them: a player moved to the bench must not keep the armband.
        var roleNote = RevalidateInMatchRoles();
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
        ClearDirty();   // everything the screen was holding is now in the career file
        Say($"Saved {shape}, {SelectedStyle?.Name}{(Fluid ? " + Sub shape" : "")} and YOUR " +
            $"XI — applies in-game on the next compile.{warn}{roleNote}",
            warn.Length + roleNote.Length > 0 ? LvlCaution : LvlDone);
    }

    /// <summary>The first pair of slots sharing one (X,Y), named for the status line — or null
    /// when the shape is legal.</summary>
    private string? DuplicateSlots(
        IReadOnlyList<(int Index, long PlayerId, string Position, string Role, int X, int Y)> slots)
    {
        for (var i = 0; i < slots.Count; i++)
        {
            for (var j = i + 1; j < slots.Count; j++)
            {
                if (slots[i].X != slots[j].X || slots[i].Y != slots[j].Y) continue;
                return $"{SlotName(slots[i])} and {SlotName(slots[j])}";
            }
        }
        return null;
    }

    private string SlotName((int Index, long PlayerId, string Position, string Role, int X, int Y) sl)
    {
        var p = Players.FirstOrDefault(x => x.PlayerId > 0 && x.PlayerId == sl.PlayerId);
        return p is not null ? p.Surname : $"the empty {sl.Position} slot";
    }

    private List<(int Index, long PlayerId, string Position, string Role, int X, int Y)> SlotsFor(int phase)
    {
        var slots = new List<(int, long, string, string, int, int)>();
        for (var i = 0; i < Players.Count && i < _phase[phase].Length; i++)
        {
            var (left, top, pos) = _phase[phase][i];
            var (x, y) = GameCoords(left, top);
            slots.Add((i, Players[i].PlayerId, pos, Players[i].Role, x, y));
        }
        return slots;
    }
}
