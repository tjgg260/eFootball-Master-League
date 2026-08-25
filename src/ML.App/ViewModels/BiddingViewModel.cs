using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Core.Development;

namespace ML.App.ViewModels;

// ═══ THE BIDDING SCREEN ══════════════════════════════════════════════════════════════
//
// Buying a footballer, on a screen the whole window wide. It lifts the negotiation out of
// the Market's 330px right rail, where the audit measured three separate faults:
//
//   1. THE MONEY WAS INVISIBLE. The Market never showed the transfer budget anywhere while
//      you bid, negotiated and signed. Here the money band is DOCKED at the top — cash,
//      transfer budget, wage budget, wage bill, the fee on the table, what goes out up
//      front, and what the club is left with — and it can never scroll away. When a fee is
//      beyond what the club can cover the screen says so BEFORE the button is pressed,
//      because the engine's refusal afterwards is a worse way to learn it.
//   2. THE FEE FIELD WAS BELOW THE FOLD, with the Complete button up to 570px below it.
//      The terms, the likelihood and the act of sending are one card here, and the card is
//      never inside a scroller.
//   3. THE NEGOTIATION READ AS A FORM, NOT A CONVERSATION. Every round the engine answers
//      with a sentence; the rail threw all but the last away. They are kept, stamped with
//      the round they belong to, and shown as a transcript beside the table.
//
// Every engine answer reaches the docked status line VERBATIM. This screen never rewrites a
// refusal, and never invents one.

/// <summary>One number in the money band. The band is the fix for fault 1, so it is a list:
/// a tile can be added without disturbing the row, and each carries its own colour so
/// "leaves you" can go red without any other tile changing.</summary>
public sealed record BidTileVm(string Label, string Value, IBrush ValueBrush, string Tip);

/// <summary>
/// One line of the talks. Speaker is either your club or theirs — named, and coloured by
/// which side said it; Stamp is the round it belongs to. Money is digits here, which is
/// correct: a fee is a statistic, not a judgement of how good the player is.
/// </summary>
public sealed record BidRoundVm(string Stamp, string Speaker, string Line, IBrush SpeakerBrush);

public sealed partial class BiddingViewModel : PageViewModel, IFocusTarget
{
    /// <summary>The app-wide knowledge floor — the same 45 the Squad card, the Market profile
    /// and the Player screen mask at. Below it we do not pretend to know a man.</summary>
    private const int ScoutFloor = 45;

    // The design-system palette, by name. Visuals.Brush takes hex, so this is where the Ml*
    // tokens land in code — every colour on this screen comes from one of these seven, and
    // each is the token beside it. Nothing here invents a colour.
    private static readonly IBrush Body = Visuals.Brush("#C7CEDA");     // MlTextBody
    private static readonly IBrush Muted = Visuals.Brush("#8A93A2");    // MlTextMuted
    private static readonly IBrush Good = Visuals.Brush("#9FE6B4");     // MlSuccessText
    private static readonly IBrush Success = Visuals.Brush("#1F9D4D");  // MlSuccess
    private static readonly IBrush Warn = Visuals.Brush("#E0A526");     // MlWarn
    private static readonly IBrush Bad = Visuals.Brush("#D64545");      // MlDanger
    private static readonly IBrush Link = Visuals.Brush("#6EA8FF");     // MlLink

    private readonly Session _s;

    private long _id;
    private string _name = "";
    private string _club = "";
    private bool _mine;
    private bool _free;
    /// <summary>His overall as stored (0 when nothing is on file) — only ever shown as a letter.</summary>
    private int _rating;
    private int? _age;
    /// <summary>What the engine itself would read: PlayerBasics COALESCEs the rating to 65, so
    /// mirroring a price means mirroring that default too, or we quote a number it never charges.</summary>
    private int EngineRating => _rating > 0 ? _rating : 65;
    private long _marketValue;
    private long _ask;
    private int _round;
    private string _sellerName = "";
    private int _knowledge;

    public BiddingViewModel(Session s)
    {
        _s = s;
        ReadWindow();
        ShowEmptyState();
        RefreshMoney();
    }

    public override string Title => "Bidding";
    public override string Icon => "💷";

    // ── subject ──────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Open the table on a man: Nav.Go("Bidding", EntityRef.Player(id, name)). Anything else
    /// is not a subject this screen can buy, and it says so rather than sitting empty.
    /// </summary>
    public void Focus(EntityRef target)
    {
        try
        {
            if (target.Kind != EntityKind.Player)
            {
                ShowEmptyState("That isn't a player. Bidding is one man at a time — find him in " +
                               "the transfer market and open the table from there.");
                return;
            }
            if (!Load(target.Id, target.Name)) return;
            if (_mine)
            {
                Say($"{_name} is already yours — there is nothing to bid for. His squad actions " +
                    "are on the Squad screen.", Tone.Warn);
                return;
            }
            if (!WindowOpen)
            {
                Say(WindowLine + ". You can still sound his club out with an enquiry — nothing " +
                    "binding can be agreed until the window opens.", Tone.Warn);
                return;
            }
            Say(Negotiating
                ? $"Back at the table with {_sellerName} over {_name} — round {_round}."
                : _free
                    ? $"{_name} is a free agent. Open talks and you are straight onto his wages."
                    : $"{_name} of {_club}. Open talks to hear what they want for him.",
                Tone.Muted);
        }
        catch (Exception ex)
        {
            Program.Log("Bidding.Focus", ex);
            ShowEmptyState("Something went wrong opening the table on that player.");
        }
    }

    private void ShowEmptyState(string? line = null)
    {
        _id = 0;
        _name = "";
        _sellerName = "";
        HasSubject = false;
        Negotiating = false;
        DealAgreed = false;
        Rounds.Clear();
        OnPropertyChanged(nameof(HasRounds));
        EmptyLine = line ??
            "Find a man in the transfer market — or on any list in the " +
            "app — and choose “Open bidding”. His club, their asking price and every penny it " +
            "would cost you open here.";
        StatusLine = "";
        RefreshMoney();
    }

    [ObservableProperty] private bool _hasSubject;
    [ObservableProperty] private string _emptyLine = "";

    // ── who you are buying, and how honestly you know him ────────────────────────────

    [ObservableProperty] private string _playerName = "";
    [ObservableProperty] private string _positionLabel = "";
    // #3A4759 is the shared "no position yet" placeholder the Squad card, the Market profile
    // and the Player screen all open on; Visuals.PositionBrush replaces it the moment a
    // player loads. It is a surface tint, not a semantic colour.
    [ObservableProperty] private IBrush _positionBrush = Visuals.Brush("#3A4759");
    [ObservableProperty] private Bitmap? _portrait;
    [ObservableProperty] private bool _hasPortrait;
    [ObservableProperty] private string _mark = "";
    [ObservableProperty] private IBrush _markBrush = Visuals.Brush("#3A4759");
    [ObservableProperty] private string _ageDisplay = "—";
    [ObservableProperty] private string _clubLine = "";
    [ObservableProperty] private Bitmap? _clubCrest;
    [ObservableProperty] private bool _hasClubCrest;

    /// <summary>Calibre as a LETTER, masked by what you know. Never the raw number.</summary>
    [ObservableProperty] private string _grade = "?";
    [ObservableProperty] private IBrush _gradeBrush = Muted;
    [ObservableProperty] private string _gradeTip = "";
    [ObservableProperty] private string _knowledgeLine = "";
    /// <summary>Below the floor: buying him is a gamble, and the screen says so out loud
    /// rather than presenting a half-known player as a known quantity.</summary>
    [ObservableProperty] private bool _thinlyKnown;
    [ObservableProperty] private string _thinlyKnownLine = "";

    [ObservableProperty] private bool _isMine;
    [ObservableProperty] private bool _isFreeAgent;

    // ── the seller and the price ─────────────────────────────────────────────────────

    [ObservableProperty] private string _sellerLine = "";
    [ObservableProperty] private string _askLine = "—";
    [ObservableProperty] private string _marketValueLine = "—";
    /// <summary>Their ask measured against his real imported value — the one number that says
    /// whether you are being taken for a ride.</summary>
    [ObservableProperty] private string _premiumLine = "";
    [ObservableProperty] private IBrush _premiumBrush = Muted;
    [ObservableProperty] private string _stanceLine = "";
    [ObservableProperty] private bool _hasStance;
    [ObservableProperty] private string _roundLabel = "";

    // ── the money band (fault 1) ─────────────────────────────────────────────────────

    [ObservableProperty] private IReadOnlyList<BidTileVm> _money = Array.Empty<BidTileVm>();
    [ObservableProperty] private string _affordLine = "";
    [ObservableProperty] private IBrush _affordBrush = Muted;
    /// <summary>False when the up-front money is simply not there. The Complete button reads
    /// this, so the screen refuses before the engine has to.</summary>
    [ObservableProperty] private bool _canAfford = true;

    // ── the terms (fault 2) ──────────────────────────────────────────────────────────

    [ObservableProperty] private bool _negotiating;
    [ObservableProperty] private bool _dealAgreed;
    [ObservableProperty] private decimal _fee;
    [ObservableProperty] private bool _instalments;

    public IReadOnlyList<string> SellOnOptions { get; } = new[]
        { "No sell-on", "10% sell-on", "15% sell-on", "20% sell-on", "25% sell-on" };
    [ObservableProperty] private string _sellOn = "No sell-on";
    private int SellOnPct => SellOn switch
    {
        "10% sell-on" => 10,
        "15% sell-on" => 15,
        "20% sell-on" => 20,
        "25% sell-on" => 25,
        _ => 0,
    };

    public IReadOnlyList<string> YearsOptions { get; } = new[]
        { "1 year", "2 years", "3 years", "4 years" };
    [ObservableProperty] private string _years = "3 years";
    private int YearsValue => Years.StartsWith("1", StringComparison.Ordinal) ? 1
        : Years.StartsWith("2", StringComparison.Ordinal) ? 2
        : Years.StartsWith("4", StringComparison.Ordinal) ? 4 : 3;

    [ObservableProperty] private decimal _wage;
    /// <summary>The agent's floor, mirrored from what CompleteSigning itself charges — so the
    /// wage box opens on a number that will actually be accepted instead of one that gets
    /// refused on the last click of a deal.</summary>
    private long _agentFloor;
    [ObservableProperty] private string _agentFloorLine = "";
    [ObservableProperty] private string _currentWageLine = "";

    [ObservableProperty] private int _likelihood;
    [ObservableProperty] private string _likelihoodWord = "";
    [ObservableProperty] private string _likelihoodLine = "";
    [ObservableProperty] private IBrush _likelihoodBrush = Muted;
    [ObservableProperty] private double _likelihoodWidth;

    // ── the transcript (fault 3) ─────────────────────────────────────────────────────

    public ObservableCollection<BidRoundVm> Rounds { get; } = new();
    public bool HasRounds => Rounds.Count > 0;

    private void AddTheirs(string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        Rounds.Add(new BidRoundVm(RoundStamp(), _sellerName.Length > 0 ? _sellerName : "Them",
            line, Warn));
        AfterTranscriptChange();
    }

    private void AddYours(string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        Rounds.Add(new BidRoundVm(RoundStamp(), _s.CurrentTeamName, line, Link));
        AfterTranscriptChange();
    }

    private string RoundStamp() => _round > 0 ? $"ROUND {_round}" : "OPENING";

    private void AfterTranscriptChange() => OnPropertyChanged(nameof(HasRounds));

    // ── the docked status line ───────────────────────────────────────────────────────

    private enum Tone { Info, Warn, Bad, Muted }

    [ObservableProperty] private string _statusLine = "";
    [ObservableProperty] private IBrush _statusBrush = Muted;

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
    /// Colour for an answer the ENGINE wrote. It returns prose, not a result code, so this is a
    /// best-effort read of the refusal shapes it actually uses — and it only ever changes the
    /// COLOUR, never the words. A miss shows a refusal in the neutral voice; it can never hide
    /// one, and it can never invent one.
    /// </summary>
    private static readonly string[] RefusalMarkers =
    {
        "won't", "can't", "cannot", "isn't", "insist", "undervalues", "you need", "no talks",
        "no open negotiation", "walk away", "already", "at the minimum", "wants at least",
        "no agreed deal", "not for sale", "window closed", "no club",
    };

    private static Tone ToneOfAnswer(string line) =>
        line.StartsWith("DONE DEAL", StringComparison.Ordinal)
        || line.StartsWith("Loan DONE", StringComparison.Ordinal)
        || line.Contains("ACCEPT", StringComparison.Ordinal)
            ? Tone.Info
            : RefusalMarkers.Any(m => line.Contains(m, StringComparison.OrdinalIgnoreCase))
                ? Tone.Warn
                : Tone.Info;

    // ── the window ───────────────────────────────────────────────────────────────────

    [ObservableProperty] private bool _windowOpen = true;
    [ObservableProperty] private string _windowLine = "";
    /// <summary>The whole banner as one string, so the view binds a single wrapping line
    /// instead of stitching Runs together inside a compiled-binding TextBlock.</summary>
    [ObservableProperty] private string _windowShutLine = "";

    private void ReadWindow()
    {
        WindowOpen = Safe(() => _s.TransferWindowOpen(), false);
        WindowLine = Safe(() => _s.TransferWindowLabel(), "");
        WindowShutLine = $"🔒 {WindowLine} — nothing binding can be agreed while it is shut. " +
                         "An enquiry costs nothing and still works.";
    }

    // ── loading ──────────────────────────────────────────────────────────────────────

    /// <summary>Read one thing from the career file without letting a single failure blank the
    /// whole screen — the pattern the Player screen and the Tactics rail both use.</summary>
    private static T Safe<T>(Func<T> read, T fallback)
    {
        try { return read(); }
        catch { return fallback; }
    }

    /// <summary>Load the table for one man. False when there is nobody to buy.</summary>
    private bool Load(long id, string fallbackName = "")
    {
        var name = Safe(() => _s.PlayerNameOf(id), "");
        if (name.Length == 0) name = fallbackName ?? "";
        if (id <= 0 || name.Length == 0)
        {
            ShowEmptyState("That player isn't in your world, so there is nobody to negotiate " +
                           "with. Players you can actually sign live in the transfer market.");
            return false;
        }

        var subjectChanged = _id != id;
        _id = id;
        _name = name;
        PlayerName = name;
        ReadWindow();
        DisarmAll();

        // --- who he is, and whose he is -------------------------------------------------
        var where = Safe<(int? TeamId, string Club)>(() => _s.ClubOfPlayer(id), (null, "Free agent"));
        _club = where.Club;
        _free = where.TeamId is null;
        _mine = Safe(() => _s.IsOwnPlayer(id), false);
        IsMine = _mine;
        IsFreeAgent = _free;
        ClubLine = _free ? "Free agent" : _club;
        ClubCrest = where.TeamId is { } logoTeam
            ? Visuals.LoadBitmap(Safe<string?>(() => _s.TeamLogoPath(logoTeam), null))
            : null;
        HasClubCrest = ClubCrest is not null;

        var bio = ReadBio(id);
        _rating = bio.Rating;
        _age = Safe<int?>(() => _s.PlayerAgeOf(id), null) ?? bio.Age;
        PositionLabel = bio.Position.Length > 0 ? bio.Position : "—";
        PositionBrush = Visuals.PositionBrush(bio.Position);
        AgeDisplay = _age is > 0 ? $"{_age}" : "—";

        var por = Safe(() => _s.PortraitFor(id),
            new PortraitInfo(null, PortraitSource.EfootballGeneric, null, null));
        Portrait = por.Image;
        HasPortrait = por.Image is not null;
        Mark = Visuals.PlayerMark(name);
        MarkBrush = por.Image is null
            ? Visuals.SkinBrush(por.SkinTone)
            : Visuals.PositionBrush(bio.Position);

        // --- the honest knowledge state ---------------------------------------------------
        // Your own player is fully known by definition; the engine owns the rest, and a failed
        // read falls to 0 rather than pretending.
        _knowledge = _mine ? 100 : Safe(() => _s.KnowledgeOf(id), 0);
        var label = Safe(() => _s.KnowledgeLabelOf(id), _mine ? "Fully known" : "Unknown");
        KnowledgeLine = _mine ? "Fully known — one of yours" : label;
        Grade = AttributeKnowledge.GradeMasked(_rating, _knowledge);
        GradeBrush = _knowledge >= 75 ? Visuals.RatingBrush(_rating) : Muted;
        GradeTip = _knowledge >= 75
            ? "Fully known — this is his real calibre."
            : _knowledge >= ScoutFloor
                ? "Part-scouted — the letter is close, the question mark is the margin."
                : "Nobody at the club has watched him. Scout him before you spend on him.";
        ThinlyKnown = !_mine && _knowledge < ScoutFloor;
        ThinlyKnownLine =
            $"{label}. Nobody at the club has watched {name} play — the letter beside his name is " +
            "a guess, and so is any fee you put on him. A scout costs a few weeks; this costs " +
            "millions.";

        // --- the price ---------------------------------------------------------------------
        // The REAL imported value, not the Market grid's synthetic curve.
        _marketValue = Safe(() => _s.MarketValueOf(id, EngineRating, _age), 0L);
        MarketValueLine = _marketValue > 0 ? $"£{_marketValue:N0}" : "—";
        var earns = ReadImportedWage(id) ?? 0;
        CurrentWageLine = earns > 0
            ? $"He earns £{earns:N0}/wk today"
            : "No wage on file for his current deal";

        if (subjectChanged) { Rounds.Clear(); Wage = 0; }
        SyncTable(subjectChanged);
        RefreshAgentFloor();
        RefreshLikelihood();
        RefreshMoney();
        AfterTranscriptChange();
        RefreshVerbs();
        HasSubject = true;
        return true;
    }

    private sealed record Bio(string Position, int Rating, int? Age);

    /// <summary>
    /// The bio row in one read — raw ADO against the career file, exactly as the Squad card and
    /// the Player screen read it. No engine method covers these columns together.
    /// </summary>
    private Bio ReadBio(long id)
    {
        try
        {
            using var cmd = _s.Db.Connection.CreateCommand();
            cmd.CommandText = "SELECT COALESCE(position,''), COALESCE(overall_rating,0), age " +
                              "FROM players WHERE id=$p";
            cmd.Parameters.AddWithValue("$p", id);
            using var r = cmd.ExecuteReader();
            if (!r.Read()) return new Bio("", 0, null);
            // A few dozen rows carry overall_rating (and age) as REAL — Convert, never GetInt32,
            // or those players throw on the way in.
            return new Bio(
                r.GetString(0),
                Convert.ToInt32(r.GetValue(1)),
                r.IsDBNull(2) ? null : Convert.ToInt32(r.GetValue(2)));
        }
        catch (Exception ex)
        {
            Program.Log("Bidding.ReadBio", ex);
            return new Bio("", 0, null);
        }
    }

    /// <summary>What he is paid today, where the import knows. Context for the agent's ask.</summary>
    private long? ReadImportedWage(long id)
    {
        try
        {
            using var cmd = _s.Db.Connection.CreateCommand();
            cmd.CommandText = "SELECT COALESCE(wage,0) FROM player_market WHERE player_id=$p";
            cmd.Parameters.AddWithValue("$p", id);
            var v = cmd.ExecuteScalar();
            return v is null or DBNull ? null : Convert.ToInt64(v);
        }
        catch { return null; }
    }

    /// <summary>
    /// Point the screen at whatever is ACTUALLY stored for this player.
    /// <para>
    /// Live talks come back exactly where they stand — round, ask, agreed-or-not — because the
    /// engine has always stored the round and the rail simply ignored it. Re-entering must never
    /// call StartNegotiation: its upsert resets round=1 and re-prices the ask, which is how the
    /// rounds you had already spent used to disappear.
    /// </para>
    /// <para>
    /// Outside the window a stored row is deliberately NOT re-entered. SendClubOffer and
    /// CompleteSigning do not check the window themselves, so a live table on a shut window
    /// would let the engine honour an offer that should not exist.
    /// </para>
    /// </summary>
    private void SyncTable(bool announceResume)
    {
        Negotiating = false;
        DealAgreed = false;
        HasStance = false;
        StanceLine = "";
        RoundLabel = "";
        _ask = 0;
        _round = 0;
        _sellerName = _free ? "Free agent" : _club;
        SellerLine = _mine
            ? "Your own player"
            : _free ? "No club to negotiate with — his terms are his own"
            : $"Selling club: {_club}";
        AskLine = "—";
        PremiumLine = "";

        if (_mine || !WindowOpen) return;
        if (Safe<NegotiationView?>(() => _s.NegotiationFor(_id), null) is not { } n) return;
        if (n.State == "dead")
        {
            SellerLine = $"{n.SellerName} walked away from talks over him.";
            return;
        }

        Negotiating = true;
        DealAgreed = n.State == "agreed";
        _sellerName = n.SellerName;
        _ask = n.Ask;
        _round = n.Round;
        SellerLine = $"Selling club: {n.SellerName}";
        AskLine = $"£{n.Ask:N0}";
        RoundLabel = DealAgreed ? "TERMS AGREED" : $"ROUND {n.Round} OF 3";
        StanceLine = n.Stance;
        HasStance = n.Stance.Length > 0;
        PricePremium(n.Ask, n.MarketValue > 0 ? n.MarketValue : _marketValue);
        Fee = n.Ask;                 // opens on their number; the manager argues it down
        if (announceResume)
        {
            AddTheirs(DealAgreed
                ? "Package agreed. Settle his wages and he is yours."
                : $"Talks are live at round {n.Round}: they want £{n.Ask:N0}.");
        }
    }

    /// <summary>Their ask against his real value — one line that says whether this is a mugging.</summary>
    private void PricePremium(long ask, long value)
    {
        if (ask <= 0 || value <= 0) { PremiumLine = ""; return; }
        var pct = (int)Math.Round((ask - value) * 100.0 / value);
        PremiumLine = pct switch
        {
            > 0 => $"{pct}% above his market value",
            < 0 => $"{-pct}% below his market value",
            _ => "exactly his market value",
        };
        PremiumBrush = pct >= 60 ? Bad : pct >= 20 ? Warn : Good;
    }

    /// <summary>
    /// The agent's floor, mirrored from the gate CompleteSigning itself applies: the REAL wage
    /// where one was imported, else the model demand, with the same deal-done discount. Quoting
    /// SigningWageDemand alone would open the box below the floor for every player who has an
    /// imported wage — and the manager would only find out on the last click of the deal.
    /// </summary>
    private void RefreshAgentFloor()
    {
        var years = YearsValue;
        var model = Safe(() => _s.SigningWageDemand(_id, years), 0L);
        var real = Safe(() => _s.RealWageDemand(_id, EngineRating, _age ?? 25, years) * 92 / 100, 0L);
        _agentFloor = Math.Max(model, real);
        AgentFloorLine = _agentFloor > 0
            ? $"His agent won't go below £{_agentFloor:N0}/wk on {years} year{(years == 1 ? "" : "s")}."
            : "No wage demand on file — offer what you think he is worth.";
        if (Wage < _agentFloor) Wage = _agentFloor;
    }

    private void RefreshLikelihood()
    {
        if (!Negotiating || _id <= 0)
        {
            Likelihood = 0;
            LikelihoodWord = "";
            LikelihoodLine = "";
            LikelihoodWidth = 0;
            return;
        }
        var pct = Safe(() => _s.DealLikelihood(_id, (long)Fee, SellOnPct, Instalments), 0);
        Likelihood = pct;
        LikelihoodWidth = Math.Clamp(pct, 0, 100) * 2.4;
        LikelihoodWord = pct >= 80 ? "They'd take this"
            : pct >= 60 ? "Likely"
            : pct >= 40 ? "It could go either way"
            : pct >= 20 ? "Unlikely"
            : "A long shot";
        LikelihoodBrush = pct >= 60 ? Success : pct >= 40 ? Warn : Bad;
        LikelihoodLine = DealAgreed
            ? "The fee is settled — only his wages stand between you and the signing."
            : $"~{pct}% · a sell-on counts as real money to them, instalments do not. " +
              "Talks run to three rounds.";
    }

    // ── the money band ───────────────────────────────────────────────────────────────

    /// <summary>
    /// Rebuild every number on the docked band. This is fault 1's whole fix, so it runs after
    /// anything that can move the money: a new subject, a changed fee, the instalments tick, a
    /// completed signing.
    /// </summary>
    private void RefreshMoney()
    {
        var (transfer, wageBudget, weekly) =
            Safe<(long Transfer, long Wage, long Weekly)>(() => _s.FinancialOverview(), (0L, 0L, 0L));
        var cash = Safe(() => _s.Finances.Balance, 0L);
        var fee = HasSubject && Negotiating ? (long)Fee : 0L;
        // Half now, half next summer — CompleteSigning only ever debits the up-front half.
        var upfront = Instalments ? fee / 2 : fee;
        var wage = HasSubject && Negotiating ? (long)Wage : 0L;
        var after = cash - upfront;

        Money = new[]
        {
            new BidTileVm("CASH AT THE BANK", $"£{cash:N0}", cash < 0 ? Bad : Body,
                "Every fee is paid out of this. It is what the engine checks when you complete."),
            new BidTileVm("TRANSFER BUDGET", $"£{transfer:N0}", Body,
                "The board's transfer pot — the share of the balance earmarked for fees."),
            new BidTileVm("WAGE BUDGET", $"£{wageBudget:N0}", Body,
                "The share of the balance earmarked for wages."),
            new BidTileVm("WAGE BILL NOW", $"£{weekly:N0}/wk", Body,
                "Players and backroom staff, every matchweek."),
            new BidTileVm("FEE ON THE TABLE", fee > 0 ? $"£{fee:N0}" : "—", Body,
                "What you are currently offering them."),
            new BidTileVm("PAID UP FRONT", upfront > 0 ? $"£{upfront:N0}" : "—",
                upfront > cash ? Bad : Body,
                Instalments
                    ? "Half now, half next summer — only this half leaves the bank today."
                    : "The whole fee leaves the bank the moment the deal completes."),
            new BidTileVm("LEAVES YOU", $"£{after:N0}", after < 0 ? Bad : after < cash / 5 ? Warn : Good,
                "The bank balance the moment this deal goes through."),
            new BidTileVm("WAGE BILL AFTER", wage > 0 ? $"£{weekly + wage:N0}/wk" : $"£{weekly:N0}/wk",
                wage > 0 ? Warn : Body,
                "Your weekly bill with his wages added."),
        };

        CanAfford = upfront <= cash;
        if (!HasSubject || !Negotiating || fee <= 0)
        {
            AffordLine = HasSubject
                ? "No offer on the table yet — nothing is committed."
                : "Nothing on the table.";
            AffordBrush = Muted;
            CanAfford = true;
        }
        else if (!CanAfford)
        {
            AffordLine = $"£{upfront:N0} up front is more than the £{cash:N0} you have. " +
                         (Instalments
                             ? "Even split in half this deal cannot complete — lower the fee or raise the money."
                             : "Split it into instalments and only half leaves the bank today.");
            AffordBrush = Bad;
        }
        else if (upfront > transfer)
        {
            AffordLine = $"£{upfront:N0} up front is above your £{transfer:N0} transfer budget — " +
                         "the club can cover it out of the balance, but the board will notice.";
            AffordBrush = Warn;
        }
        else
        {
            AffordLine = $"You can cover the £{upfront:N0} up front" +
                         (wage > 0 ? $" and the £{wage:N0}/wk." : ".");
            AffordBrush = Good;
        }
    }

    // ── property reactions ───────────────────────────────────────────────────────────

    partial void OnFeeChanged(decimal value)
    {
        DisarmComplete();
        RefreshLikelihood();
        RefreshMoney();
        RefreshVerbs();
    }

    partial void OnSellOnChanged(string value)
    {
        DisarmComplete();
        RefreshLikelihood();
    }

    partial void OnInstalmentsChanged(bool value)
    {
        DisarmComplete();
        RefreshLikelihood();
        RefreshMoney();
    }

    partial void OnWageChanged(decimal value)
    {
        DisarmComplete();
        RefreshMoney();
    }

    partial void OnYearsChanged(string value)
    {
        DisarmComplete();
        RefreshAgentFloor();
        RefreshMoney();
    }

    // ── the verbs ────────────────────────────────────────────────────────────────────

    [ObservableProperty] private string _openLabel = "🤝 Open negotiation";
    [ObservableProperty] private bool _canOpen;
    [ObservableProperty] private string _loanLabel = "↔ Loan him until June";
    [ObservableProperty] private bool _canLoan;
    [ObservableProperty] private bool _canEnquire;
    [ObservableProperty] private string _enquireLabel = "💬 Make enquiry";
    [ObservableProperty] private bool _canSend;
    [ObservableProperty] private bool _canComplete;
    [ObservableProperty] private string _completeLabel = CompleteIdle;
    [ObservableProperty] private string _walkLabel = WalkIdle;

    private const string CompleteIdle = "✓ Complete the signing";
    private const string CompleteArm = "✓ Sure? Sign him";
    private const string WalkIdle = "Walk away";
    private const string WalkArm = "Sure? End the talks";

    private bool _completeArmed;
    private bool _walkArmed;

    private void DisarmComplete()
    {
        _completeArmed = false;
        CompleteLabel = CompleteIdle;
    }

    /// <summary>An arm that survives the NEXT action is a trap: doing anything else on this
    /// screen puts the walk-away back to its first click.</summary>
    private void DisarmWalk()
    {
        _walkArmed = false;
        WalkLabel = WalkIdle;
    }

    private void DisarmAll()
    {
        DisarmComplete();
        DisarmWalk();
    }

    /// <summary>
    /// Every button says WHY it is off rather than sitting greyed out with no reason — the
    /// standing idiom, and the one the audit keeps catching screens breaking.
    /// </summary>
    private void RefreshVerbs()
    {
        var live = Negotiating && !DealAgreed;
        CanOpen = HasSubject && !_mine && WindowOpen && !Negotiating;
        OpenLabel = !HasSubject ? "🤝 Open negotiation"
            : _mine ? "🤝 He is already yours"
            : !WindowOpen ? "🤝 Open negotiation — window closed"
            : Negotiating ? "🤝 Talks are already open"
            : _free ? "🤝 Open talks with him"
            : "🤝 Open negotiation";

        CanEnquire = HasSubject && !_mine && !_free;
        EnquireLabel = !HasSubject ? "💬 Make enquiry"
            : _mine ? "💬 He is already yours"
            : _free ? "💬 No club to ask — he is a free agent"
            : "💬 Make enquiry";
        CanLoan = HasSubject && !_mine && !_free && WindowOpen;
        LoanLabel = !HasSubject ? "↔ Loan him until June"
            : _mine ? "↔ He is already yours"
            : _free ? "↔ Free agents sign permanently"
            : !WindowOpen ? "↔ Loan — window closed"
            : "↔ Loan him until June";

        CanSend = live && WindowOpen && Fee > 0;
        CanComplete = HasSubject && DealAgreed && WindowOpen && CanAfford;
    }

    partial void OnNegotiatingChanged(bool value) => RefreshVerbs();
    partial void OnDealAgreedChanged(bool value) => RefreshVerbs();
    partial void OnCanAffordChanged(bool value) => RefreshVerbs();

    [RelayCommand]
    private void OpenTalks()
    {
        if (!Ready()) return;
        DisarmWalk();
        if (!WindowOpen)
        {
            Say(WindowLine + ". No talks outside the window — an enquiry is all that's available.",
                Tone.Warn);
            return;
        }
        // Re-entering live talks must NOT call StartNegotiation: its upsert sets round=1 and
        // re-prices the ask, which is exactly how spent rounds used to vanish.
        if (Safe<NegotiationView?>(() => _s.NegotiationFor(_id), null) is { } livetable
            && livetable.State != "dead")
        {
            SyncTable(announceResume: true);
            RefreshLikelihood();
            RefreshMoney();
            RefreshVerbs();
            Say(livetable.State == "agreed"
                ? $"{livetable.SellerName} have already agreed terms for {_name} — settle his wages."
                : $"Back at the table with {livetable.SellerName} — round {livetable.Round}.");
            return;
        }

        var msg = Safe(() => _s.StartNegotiation(_id), "The talks could not be opened.");
        SyncTable(announceResume: false);
        AddTheirs(msg);
        RefreshLikelihood();
        RefreshMoney();
        RefreshVerbs();
        Say(msg, ToneOfAnswer(msg));
    }

    [RelayCommand]
    private void SendOffer()
    {
        if (!Ready()) return;
        DisarmWalk();
        if (!Negotiating || DealAgreed) { Say("There is no open offer to send.", Tone.Warn); return; }
        if (!WindowOpen) { Say(WindowLine + ". Nothing can be agreed now.", Tone.Warn); return; }

        AddYours($"We offer {PackageLine()}.");
        var (msg, agreed, dead) = Safe<(string Msg, bool Agreed, bool Dead)>(
            () => _s.SendClubOffer(_id, (long)Fee, SellOnPct, Instalments),
            ("The offer could not be sent — nothing was changed.", false, false));
        DealAgreed = agreed;
        if (dead) Negotiating = false;

        // Re-read the stored row so the round counter, the ask and their stance on screen are
        // the engine's, not ours.
        if (!dead && Safe<NegotiationView?>(() => _s.NegotiationFor(_id), null) is { } n)
        {
            _ask = n.Ask;
            _round = n.Round;
            AskLine = $"£{n.Ask:N0}";
            RoundLabel = agreed ? "TERMS AGREED" : $"ROUND {n.Round} OF 3";
            StanceLine = n.Stance;
            HasStance = n.Stance.Length > 0;
            PricePremium(n.Ask, n.MarketValue > 0 ? n.MarketValue : _marketValue);
        }
        AddTheirs(msg);
        if (agreed) RefreshAgentFloor();
        RefreshLikelihood();
        RefreshMoney();
        RefreshVerbs();
        Say(msg, dead ? Tone.Bad : ToneOfAnswer(msg));
    }

    /// <summary>The package in the words the transcript uses — one description, one truth.</summary>
    private string PackageLine() =>
        $"£{(long)Fee:N0}" +
        (SellOnPct > 0 ? $" plus a {SellOnPct}% sell-on" : "") +
        (Instalments ? ", half now and half next summer" : "");

    [RelayCommand]
    private void MeetTheirAsk()
    {
        if (!Ready()) return;
        DisarmWalk();
        if (_ask <= 0) { Say("They haven't named a price yet.", Tone.Warn); return; }
        Fee = _ask;
        Say($"Fee set to their asking price, £{_ask:N0}. Send it and they can hardly refuse.");
    }

    [RelayCommand]
    private void WalkAway()
    {
        if (!Ready()) return;
        if (!Negotiating) { Say("There are no talks to walk away from.", Tone.Warn); return; }
        // Deliberate, because the engine marks the row dead and the club will not reopen it
        // this window.
        if (!_walkArmed)
        {
            _walkArmed = true;
            WalkLabel = WalkArm;
            Say($"Walk away from {_sellerName}? They will not reopen talks over {_name} this " +
                "window. Click again to confirm.", Tone.Warn);
            return;
        }
        _walkArmed = false;
        WalkLabel = WalkIdle;
        Safe<object?>(() => { _s.WalkAwayFromNegotiation(_id); return null; }, null);
        AddYours("We're walking away.");
        Negotiating = false;
        DealAgreed = false;
        SyncTable(announceResume: false);
        RefreshLikelihood();
        RefreshMoney();
        RefreshVerbs();
        Say("You walked away from the table.", Tone.Warn);
    }

    [RelayCommand]
    private void CompleteDeal()
    {
        if (!Ready()) return;
        DisarmWalk();
        if (!DealAgreed) { Say("Their club hasn't agreed a fee yet.", Tone.Warn); return; }
        if (!WindowOpen) { Say(WindowLine + ". The signing can't be registered.", Tone.Warn); return; }
        if (!CanAfford) { Say(AffordLine, Tone.Bad); return; }

        // Two-step, because the money leaves the bank and the signing cannot be undone.
        if (!_completeArmed)
        {
            _completeArmed = true;
            CompleteLabel = CompleteArm;
            var upfront = Instalments ? (long)Fee / 2 : (long)Fee;
            Say($"Sign {_name} for {PackageLine()} on £{(long)Wage:N0}/wk × {YearsValue} " +
                $"year{(YearsValue == 1 ? "" : "s")}? £{upfront:N0} leaves the bank the moment " +
                "you confirm, and none of it comes back. Click again to go ahead.", Tone.Warn);
            return;
        }
        DisarmComplete();

        var msg = Safe(
            () => _s.CompleteSigning(_id, (long)Fee, SellOnPct, Instalments, (long)Wage, YearsValue),
            "The signing could not be completed.");
        AddTheirs(msg);
        Say(msg, ToneOfAnswer(msg));
        if (msg.StartsWith("DONE DEAL", StringComparison.Ordinal))
        {
            Negotiating = false;
            DealAgreed = false;
            Load(_id, _name);              // he is ours now — the screen re-reads as such
            Say(msg);                      // ...and the engine's own words survive the reload
        }
        else
        {
            // The agent said no, or the money wasn't there. His refusal names the number, so
            // the fee and wage boxes stay exactly as they are for the manager to adjust.
            RefreshMoney();
            RefreshVerbs();
        }
    }

    [RelayCommand]
    private void Enquire()
    {
        if (!Ready()) return;
        DisarmWalk();
        // Free and non-committal: MakeEnquiry writes no negotiation row and needs no window.
        var msg = Safe(() => _s.MakeEnquiry(_id), "The enquiry went nowhere.");
        AddYours("We ask, informally, what it would take.");
        AddTheirs(msg);
        Say(msg, ToneOfAnswer(msg));
    }

    [RelayCommand]
    private void LoanFor()
    {
        if (!Ready()) return;
        DisarmWalk();
        var msg = Safe(() => _s.LoanIn(_id), "The loan could not be arranged.");
        AddTheirs(msg);
        Say(msg, ToneOfAnswer(msg));
        if (msg.StartsWith("Loan DONE", StringComparison.Ordinal)) Load(_id, _name);
        else { RefreshMoney(); RefreshVerbs(); }
    }

    [RelayCommand]
    private void GoToSquad() => Nav.Go("Squad", EntityRef.Player(_id, _name));

    [RelayCommand]
    private void ViewProfile() => Nav.Go("Player", EntityRef.Player(_id, _name));

    [RelayCommand]
    private void GoToMarket() => Nav.Go("Market");

    /// <summary>The guard every verb opens with: a subject, and not one of your own.</summary>
    private bool Ready()
    {
        if (_id <= 0)
        {
            Say("Nobody is at the table. Open a player from the transfer market first.", Tone.Muted);
            return false;
        }
        if (_mine)
        {
            Say($"{_name} is already your player — there is nothing to bid for. His squad " +
                "actions live on the Squad screen.", Tone.Warn);
            return false;
        }
        return true;
    }

    // ── the shared right-click vocabulary ────────────────────────────────────────────

    /// <summary>
    /// The same menu every name in the app carries, so scouting, the shortlist and his club are
    /// one click away from the table. Built fresh per open so the toggles and guards are current.
    /// </summary>
    public ContextMenu? BuildMenu()
    {
        if (_id <= 0) return null;
        try
        {
            var extras = new List<MenuItem>();
            var profile = new MenuItem { Header = "👤 Open his profile" };
            profile.Click += (_, _) => ViewProfile();
            extras.Add(profile);
            return EntityActions.BuildMenu(_s, EntityRef.Player(_id, _name),
                status: line => Say(line, ToneOfAnswer(line)),
                refresh: () => Load(_id, _name),
                extras: extras);
        }
        catch (Exception ex)
        {
            Program.Log("Bidding.BuildMenu", ex);
            return null;
        }
    }
}
