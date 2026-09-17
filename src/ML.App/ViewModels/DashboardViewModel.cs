using System.Collections.ObjectModel;
using System.Threading.Tasks;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.Core.Tables;
using ML.Data;

namespace ML.App.ViewModels;

// --- Portal card row models (compiled-binding item types) -------------------------

/// <summary>One W/D/L letter square in a form strip.</summary>
public sealed record FormChipVm(string Letter, IBrush Bg);

/// <summary>One schedule line: matchday label, opponent (with crest), and a result chip ("2-1" or "—").
/// Carries the ids too — a row you can right-click is a row that must know WHO it is.</summary>
public sealed record ScheduleRowVm(string Md, string Opponent, string Chip, IBrush ChipBg, IBrush ChipFg,
    Avalonia.Media.Imaging.Bitmap? Crest = null, int TeamId = 0, int FixtureId = 0);

/// <summary>One mini-table line (or the dim "· · ·" separator when you sit outside the top six).</summary>
public sealed record MiniRowVm(
    string Pos, string Team, string P, string Gd, string Pts, IBrush Bg, IBrush Fg, FontWeight Weight,
    Avalonia.Media.Imaging.Bitmap? Crest = null, int TeamId = 0);

// --- Dashboard (the MFL "Office", FM-portal style) --------------------------------

public sealed partial class DashboardViewModel : PageViewModel
{
    private static readonly IBrush WinBrush = Visuals.Brush("#1F9D4D");
    private static readonly IBrush DrawBrush = Visuals.Brush("#3A4759");
    private static readonly IBrush LossBrush = Visuals.Brush("#D64545");
    private static readonly IBrush NeutralChip = Visuals.Brush("#232B36");
    private static readonly IBrush TextBrush = Visuals.Brush("#C7CEDA");
    private static readonly IBrush DimBrush = Visuals.Brush("#8A93A2");
    private static readonly IBrush YouRowBg = Visuals.Brush("#2E1F9D4D");   // #1F9D4D tint
    private static readonly IBrush YouRowFg = Visuals.Brush("#DFF5E7");

    private readonly Session _s;
    private string _homeName = "";
    private string _awayName = "";
    private int _homeId;
    private int _awayId;
    private int _fixtureId;
    private int _matchday;
    private string _kind = "league";

    public DashboardViewModel(Session s)
    {
        _s = s;
        ClubName = s.CurrentTeamName;
        LeagueName = s.LeagueName;
        BadgeText = Visuals.Initials(ClubName);
        BadgeBrush = Visuals.Brush(s.PrimaryColor);
        BadgeStroke = Visuals.Brush(s.SecondaryColor);
        Logo = Visuals.LoadBitmap(s.LogoPath);

        // Every LIVE number on this screen used to be read exactly here, once. See RefreshGauges:
        // LoadNextMatch always ends in RefreshPortal, which fills them in — first for the opening
        // frame, and again after every result. Reading them here too would only double the queries.
        LoadNextMatch();
    }

    // ── the office gauges ─────────────────────────────────────────────────────────────
    // THE BUG: these were get-only auto-properties assigned ONCE in the constructor, while
    // RefreshPortal rebuilt only the position, the opposition card, the schedule and the mini
    // table. So the post-match report — which reads the world LIVE — printed "Board settled
    // (dented)" over tiles still showing what they were when you walked into the Office. Three
    // results without leaving the screen and the tiles were three matchdays stale. They are
    // observable now, and RefreshGauges() re-reads the lot wherever the world has moved.

    [ObservableProperty] private int _elo;
    [ObservableProperty] private string _tier = "";
    [ObservableProperty] private string _chairmanLine = "";
    [ObservableProperty] private int _fans;
    [ObservableProperty] private string _fansLabel = "";
    [ObservableProperty] private string _financeLine = "";
    [ObservableProperty] private int _boardConfidence;
    [ObservableProperty] private string _boardLabel = "";
    [ObservableProperty] private int _morale;
    [ObservableProperty] private string _moraleLabel = "";
    [ObservableProperty] private string _balance = "";
    [ObservableProperty] private string _expectation = "";

    public ObservableCollection<string> ObjectiveChips { get; } = new();
    public bool HasObjectiveChips => ObjectiveChips.Count > 0;
    public ObservableCollection<string> Ticker { get; } = new();
    public bool HasTicker => Ticker.Count > 0;

    /// <summary>
    /// Re-read every gauge from the world. Called at the end of RefreshPortal (which already runs
    /// on load and after every recorded result) and when the post-match report closes, so the
    /// tiles can never disagree with the report sitting directly above them. Each block is guarded
    /// on its own: one failing query dims one gauge, it never bricks the Office.
    /// </summary>
    private void RefreshGauges()
    {
        try
        {
            // BoardNow, not Board. `Board` is built once in Session's constructor and never
            // re-read, so a verdict landed by the season review, a refused budget ask or the
            // objectives pass moved a number this tile could not see. The Office gauge and the
            // Board screen were then quietly showing different confidence for the same club.
            BoardConfidence = _s.BoardConfidenceNow;
            BoardLabel = _s.BoardNow.Label;
            Expectation = Visuals.ExpectationLabel(_s.Board.Expectation);
        }
        catch { /* one gauge, not the screen */ }

        // The gauge reads the REAL per-player morale average (the old Session.Morale object
        // was a constant 60 that nothing ever updated).
        try { Morale = _s.SquadMoraleAverage(); }
        catch { Morale = 60; }
        MoraleLabel = Morale switch
        {
            >= 85 => "Superb", >= 70 => "Very Good", >= 55 => "Good",
            >= 40 => "Okay", >= 25 => "Poor", _ => "Abject",
        };

        try { Balance = $"£{_s.Finances.Balance:N0}"; } catch { /* one gauge, not the screen */ }

        // MFL office extras: ELO + status tier, chairman, fans gauge, financial split, ticker.
        try
        {
            Elo = _s.EloOf(_s.CurrentTeamId);
            Tier = _s.ClubTier(_s.CurrentTeamId);
            ChairmanLine = $"Chairman: {_s.Chairman()}";
        }
        catch { /* office extras never brick the dashboard */ }

        // The fan gauge carries a memory (P2): half persistent ledger, half form.
        try { Fans = _s.FanHappiness(); FansLabel = _s.FanLabel; } catch { }

        try
        {
            var (transfer, wages, weekly) = _s.FinancialOverview();
            FinanceLine = $"Transfers £{transfer:N0}  ·  Wages £{wages:N0}  ·  £{weekly:N0}/wk bill";
        }
        catch { }

        try
        {
            ObjectiveChips.Clear();
            foreach (var o in _s.Objectives().Where(o => o.Importance != "bonus").Take(2))
            {
                ObjectiveChips.Add($"{(o.Status == 1 ? "✅" : o.Status == 2 ? "❌" : "◻")} {o.Description} — {o.Progress}");
            }
        }
        catch { }
        OnPropertyChanged(nameof(HasObjectiveChips));   // a plain getter over a collection

        try
        {
            Ticker.Clear();
            foreach (var t in _s.RecentTransfers(5)) Ticker.Add(t);
        }
        catch { }
        OnPropertyChanged(nameof(HasTicker));
    }

    /// <summary>
    /// Raise the career-state properties. THE BUG: IsSacked, SackedHeadline and SeasonOver are
    /// plain expression-bodied properties over the Session, and the board can sack you inside
    /// RecordResult — with nothing notifying, the SACKED card never appeared and the screen just
    /// went card-less (SeasonOver, which reads IsSacked, went false too). Raised from the one
    /// place that runs after every world change.
    /// </summary>
    private void NotifyCareerState()
    {
        OnPropertyChanged(nameof(IsSacked));
        OnPropertyChanged(nameof(SackedHeadline));
        OnPropertyChanged(nameof(SeasonOver));
    }

    public override string Title => "Office";
    public override string Icon => "🏠";

    public string ClubName { get; }
    public string LeagueName { get; }
    public string BadgeText { get; } = "";
    public IBrush BadgeBrush { get; } = Visuals.Brush(null);
    public IBrush BadgeStroke { get; } = Visuals.Brush(null);
    public Bitmap? Logo { get; }
    public bool HasLogo => Logo is not null;

    [ObservableProperty]
    private string _position = "—";

    // --- Play Match + record result: the career loop ---
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(PlayEnabled))]
    [NotifyPropertyChangedFor(nameof(SeasonOver))]
    [NotifyPropertyChangedFor(nameof(ShowPreMatch))]
    [NotifyPropertyChangedFor(nameof(ShowResultEntry))]
    [NotifyPropertyChangedFor(nameof(NeedsShootout))]
    private bool _hasNextMatch;

    // ── matchday theatre (UX P1): the card is an OCCASION before kickoff and an entry desk
    // only after — never eleven controls and a 0-0 stepper staring at you pre-match.
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowPreMatch))]
    [NotifyPropertyChangedFor(nameof(ShowResultEntry))]
    [NotifyPropertyChangedFor(nameof(NeedsShootout))]
    private bool _resultEntryOpen;

    public bool ShowPreMatch => HasNextMatch && !ResultEntryOpen;
    public bool ShowResultEntry => HasNextMatch && ResultEntryOpen;

    // ── a cup tie needs a winner ──────────────────────────────────────────────────────
    // A level score in a knockout went to penalties in the game. The desk asks who won them;
    // without the answer the engine used to flip its own coin (Session.CupWinnerOf).
    public bool NeedsShootout => ShowResultEntry && _kind == "cup" && (int)HomeScore == (int)AwayScore;
    public string ShootoutHomeLabel => _homeName;
    public string ShootoutAwayLabel => _awayName;

    [ObservableProperty] private bool _shootoutHome;
    [ObservableProperty] private bool _shootoutAway;
    partial void OnShootoutHomeChanged(bool value) { if (value) ShootoutAway = false; }
    partial void OnShootoutAwayChanged(bool value) { if (value) ShootoutHome = false; }
    partial void OnHomeScoreChanged(decimal value) => OnPropertyChanged(nameof(NeedsShootout));
    partial void OnAwayScoreChanged(decimal value) => OnPropertyChanged(nameof(NeedsShootout));

    /// <summary>The narrative line of the pre-match card ("In the other dugout: …").</summary>
    [ObservableProperty]
    private string _dugoutLine = "";

    // full-time banner: the result gets a MOMENT, not a clause in a status string
    [ObservableProperty] private bool _ftVisible;
    [ObservableProperty] private string _ftLine = "";
    [ObservableProperty] private IBrush _ftBrush = Brushes.Gray;

    // celebration overlay: titles and promotions deserve confetti, not 12px green text
    [ObservableProperty] private bool _celebrationVisible;
    [ObservableProperty] private string _celebrationTitle = "";
    [ObservableProperty] private string _celebrationSub = "";

    /// <summary>
    /// What the last match-export load has to say, shown ON the entry desk beside the score
    /// boxes. A refusal ("that export is not this fixture") has to appear where the user is
    /// already looking — the muted status line at the foot of the card is not that place.
    /// </summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasImportNotice))]
    private string _importNotice = "";

    public bool HasImportNotice => ImportNotice.Length > 0;

    [RelayCommand]
    private void OpenResultEntry()
    {
        ImportNotice = "";
        ResultEntryOpen = true;
    }

    [RelayCommand]
    private void BackToPreMatch() => ResultEntryOpen = false;

    [RelayCommand]
    private void CloseCelebration() => CelebrationVisible = false;

    [ObservableProperty]
    private string _nextMatchLabel = "No match scheduled";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(PlayEnabled))]
    private bool _isCompiling;

    [ObservableProperty]
    private string _matchStatus = "";

    [ObservableProperty]
    private decimal _homeScore;

    [ObservableProperty]
    private decimal _awayScore;

    // The four stats eFootball's post-match screens give — comma-separated, surname-matched.
    [ObservableProperty]
    private string _scorersText = "";

    [ObservableProperty]
    private string _assistsText = "";

    [ObservableProperty]
    private string _cardsText = "";

    [ObservableProperty]
    private string _ratingsText = "";

    [ObservableProperty]
    private string _jobLine = "";

    // Deadline day (P5): the banner shows when the window's last matchday is next.
    [ObservableProperty] private bool _deadlineVisible;

    // --- the post-match report (P3): full time is a moment, not a status line ----------

    [ObservableProperty] private bool _reportVisible;
    [ObservableProperty] private string _reportScore = "";
    [ObservableProperty] private string _reportComp = "";
    [ObservableProperty] private string _reportVerdict = "";
    [ObservableProperty] private Avalonia.Media.IBrush _reportVerdictBrush = Visuals.Brush("#C7CEDA");
    public ObservableCollection<string> ReportEvents { get; } = new();
    public ObservableCollection<string> ReportRatings { get; } = new();
    [ObservableProperty] private string _reportMoraleLine = "";
    [ObservableProperty] private string _reportBoardLine = "";
    [ObservableProperty] private string _reportDebrief = "";
    public bool HasReportEvents => ReportEvents.Count > 0;
    public bool HasReportRatings => ReportRatings.Count > 0;
    public bool HasReportDebrief => ReportDebrief.Length > 0;

    private void BuildPostMatchReport(int fixtureId, int homeId, int awayId,
        int homeGoals, int awayGoals, string kind,
        int moraleBefore, int boardBefore, int fansBefore)
    {
        try
        {
            var home = _s.TeamName(homeId);
            var away = _s.TeamName(awayId);
            ReportScore = $"{home}  {homeGoals} – {awayGoals}  {away}";
            var fixture = _s.Repo.Fixtures(_s.SeasonId).FirstOrDefault(f => f.Id == fixtureId);
            var leagueId = fixture?.LeagueId ?? 9002;
            // A level cup tie went to penalties: the score line alone does not say who went through.
            int? shootoutWinner = kind == "cup" && homeGoals == awayGoals && fixture is not null
                ? _s.CupWinnerOf(fixture) : null;
            if (shootoutWinner is { } through)
                ReportScore += $"   ·   {_s.TeamName(through)} won on penalties";
            ReportComp = kind == "cup" ? Session.CupNameFor(leagueId)
                : kind == "friendly" ? "Preseason Friendly" : _s.LeagueName;
            var youHome = homeId == _s.CurrentTeamId;
            var us = youHome ? homeGoals : awayGoals;
            var them = youHome ? awayGoals : homeGoals;
            (ReportVerdict, ReportVerdictBrush) = us > them
                ? ("FULL TIME — VICTORY", Visuals.Brush("#8BE04A"))
                : us < them ? ("FULL TIME — DEFEAT", Visuals.Brush("#F0655A"))
                // level: a league draw is a draw, a cup tie is whoever held their nerve
                : shootoutWinner is null ? ("FULL TIME — DRAW", Visuals.Brush("#E0A526"))
                : shootoutWinner == _s.CurrentTeamId ? ("THROUGH ON PENALTIES", Visuals.Brush("#8BE04A"))
                : ("OUT ON PENALTIES", Visuals.Brush("#F0655A"));

            ReportEvents.Clear();
            foreach (var (type, player, teamId) in _s.EventsForFixture(fixtureId))
            {
                var icon = type switch { "goal" => "⚽", "assist" => "🅰", "yellow" => "🟨", _ => "🟥" };
                var side = teamId == _s.CurrentTeamId ? "" : "  (them)";
                ReportEvents.Add($"{icon} {player}{side}");
            }
            ReportRatings.Clear();
            foreach (var (player, rating) in _s.RatingsForFixture(fixtureId).Take(11))
            {
                ReportRatings.Add($"{player}  {rating:0.0}");
            }

            var moraleNow = _s.SquadMoraleAverage();
            var boardNow = _s.BoardConfidenceNow;
            var fansNow = _s.FanHappiness();
            // Words, not numbers (P5): the report reads like an assistant, not a debugger.
            static string Mood(int v) => v switch
            {
                >= 85 => "buzzing", >= 70 => "upbeat", >= 55 => "settled",
                >= 40 => "flat", >= 25 => "unhappy", _ => "toxic",
            };
            static string Swing(int now, int before) =>
                now - before >= 4 ? "lifted" : now - before <= -4 ? "dented" : "steady";
            ReportMoraleLine = $"Dressing room {Mood(moraleNow)} — {Swing(moraleNow, moraleBefore)}";
            ReportBoardLine = $"Board {Mood(boardNow)} ({Swing(boardNow, boardBefore)})  ·  " +
                              $"Fans {Mood(fansNow)} ({Swing(fansNow, fansBefore)})";
            try { ReportDebrief = _s.AssistantDebrief(fixtureId, homeId, awayId); }
            catch { ReportDebrief = ""; }

            OnPropertyChanged(nameof(HasReportEvents));
            OnPropertyChanged(nameof(HasReportRatings));
            OnPropertyChanged(nameof(HasReportDebrief));
            ReportVisible = true;
        }
        catch { ReportVisible = false; }
    }

    [RelayCommand]
    private void CloseReport()
    {
        ReportVisible = false;
        FtVisible = false;    // the moment ends together: banner + report leave as one
        // The report quotes the gauges LIVE ("Board settled (dented)"). The tiles it was covering
        // must agree with it the instant it lifts, not at the next matchday.
        RefreshGauges();
    }

    // Team talks (C2): one pre-match and one post-match say per fixture.
    [ObservableProperty] private bool _preTalkVisible;
    [ObservableProperty] private string _talkHintLine = "";
    [ObservableProperty] private bool _postTalkVisible;
    private int _lastFixtureId;
    private int _lastHomeId;
    private int _lastAwayId;
    private int? _lastOutcome;

    [RelayCommand]
    private void PreTalk(string tone)
    {
        if (!PreTalkVisible) return;
        var reaction = _s.ApplyTeamTalk(_fixtureId, preMatch: true,
            Enum.Parse<ML.Core.Selection.TalkTone>(tone), _homeId, _awayId, null);
        PreTalkVisible = false;
        MatchStatus = $"🗣 {reaction}";
    }

    [RelayCommand]
    private void PostTalk(string tone)
    {
        if (!PostTalkVisible) return;
        var reaction = _s.ApplyTeamTalk(_lastFixtureId, preMatch: false,
            Enum.Parse<ML.Core.Selection.TalkTone>(tone), _lastHomeId, _lastAwayId, _lastOutcome);
        PostTalkVisible = false;
        MatchStatus = $"🗣 {reaction}";
    }

    public bool PlayEnabled => HasNextMatch && !IsCompiling;

    // Sacked ≠ season over: a sacked manager has no next match either, but must see the
    // SACKED card, not "SEASON COMPLETE" with a live Advance Season button.
    // These three read the Session live, so they are always CORRECT when asked — they were just
    // never asked again after the board acted. NotifyCareerState() is what asks; see RefreshPortal.
    public bool SeasonOver => !HasNextMatch && !IsSacked;

    public bool IsSacked => _s.IsSacked;
    public string SackedHeadline => IsSacked ? "SACKED — " + _s.SackedLine : "";

    /// <summary>
    /// The record you leave behind, shown ON the SACKED card. THE BUG: this line was written into
    /// MatchStatus, which is only rendered INSIDE the next-match card — the one card that is
    /// hidden precisely when you have been sacked. The copy could never reach a pixel.
    /// </summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasCareerSummary))]
    private string _careerSummaryLine = "";

    public bool HasCareerSummary => CareerSummaryLine.Length > 0;

    // --- Next Opposition card ---
    [ObservableProperty]
    private bool _hasOpposition;

    [ObservableProperty]
    private string _oppName = "";

    [ObservableProperty]
    private string _oppPositionLine = "";

    [ObservableProperty]
    private string _oppShapeLine = "";

    [ObservableProperty]
    private string _oppBadgeText = "";

    [ObservableProperty]
    private IBrush _oppBadgeBrush = Visuals.Brush(null);

    [ObservableProperty]
    private IBrush _oppBadgeStroke = Visuals.Brush(null);

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(OppHasLogo))]
    private Bitmap? _oppLogo;

    public bool OppHasLogo => OppLogo is not null;

    [ObservableProperty]
    private bool _hasOppForm;

    public ObservableCollection<FormChipVm> OppForm { get; } = new();

    // Win/draw/loss from ELO (MFL match preview) + the opponent's key player.
    [ObservableProperty]
    private string _oddsLine = "";

    [ObservableProperty]
    private double _oddsWin;

    [ObservableProperty]
    private double _oddsDraw;

    [ObservableProperty]
    private double _oddsLoss;

    [ObservableProperty]
    private string _keyPlayerLine = "";

    /// <summary>The assistant's pre-match availability note (empty until one is hired).</summary>
    [ObservableProperty]
    private string _assistantLine = "";

    // --- Schedule + mini table cards ---
    public ObservableCollection<ScheduleRowVm> Schedule { get; } = new();
    public ObservableCollection<MiniRowVm> MiniTable { get; } = new();

    /// <summary>Load the next unplayed fixture into the card — called at start and after each result.</summary>
    // --- XI-driven event pickers (P3): the app knows both XIs, so nobody types names ------

    public ObservableCollection<string> MatchPlayerNames { get; } = new();
    public ObservableCollection<EventPickRow> GoalPicks { get; } = new();
    public ObservableCollection<EventPickRow> AssistPicks { get; } = new();
    public ObservableCollection<EventPickRow> CardPicks { get; } = new();

    private void Log(string line) => MatchStatus += (MatchStatus.Length > 0 ? "\n" : "") + line;

    [RelayCommand] private void AddGoalPick() => GoalPicks.Add(new EventPickRow(MatchPlayerNames));
    [RelayCommand] private void AddAssistPick() => AssistPicks.Add(new EventPickRow(MatchPlayerNames));
    [RelayCommand] private void AddCardPick() => CardPicks.Add(new EventPickRow(MatchPlayerNames));

    [RelayCommand]
    private void ClearPicks()
    {
        GoalPicks.Clear();
        AssistPicks.Clear();
        CardPicks.Clear();
    }

    private void LoadMatchPlayers()
    {
        MatchPlayerNames.Clear();
        ClearPicks();
        try
        {
            foreach (var teamId in new[] { _homeId, _awayId })
            {
                var players = _s.Repo.SquadPlayers(teamId).ToDictionary(p => p.Id, p => p.Name);
                foreach (var m in _s.Repo.Squad(teamId).Where(m => m.Slot is >= 0 and <= 10)
                             .OrderBy(m => m.Slot))
                {
                    if (players.TryGetValue(m.PlayerId, out var name)) MatchPlayerNames.Add(name);
                }
            }
        }
        catch { /* pickers degrade to the free-text path */ }
    }

    /// <summary>Fold the picker rows into the text the stats engine already understands.</summary>
    private void FoldPicksIntoTexts()
    {
        string Fold(IEnumerable<EventPickRow> rows) =>
            string.Join(", ", rows.Select(r => r.Selected).Where(s => !string.IsNullOrWhiteSpace(s)));
        var goals = Fold(GoalPicks);
        var assists = Fold(AssistPicks);
        var cards = string.Join(", ", CardPicks
            .Where(r => !string.IsNullOrWhiteSpace(r.Selected))
            .Select(r => r.IsRed ? $"{r.Selected} r" : r.Selected));
        if (goals.Length > 0) ScorersText = goals;
        if (assists.Length > 0) AssistsText = assists;
        if (cards.Length > 0) CardsText = cards;
    }

    private void LoadNextMatch()
    {
        ImportNotice = "";   // a new fixture starts with a clean entry desk

        // Sacked managers do not pick teams: the dashboard goes dark until you take a new job.
        if (_s.IsSacked)
        {
            NextMatchLabel = "SACKED — " + _s.SackedLine;
            // The career line goes to the SACKED card's own property — MatchStatus only renders
            // inside the next-match card, which is hidden in exactly this state (see above).
            try { CareerSummaryLine = $"Your career: {_s.CareerSummary()}"; }
            catch { CareerSummaryLine = ""; }
            MatchStatus = "";
            HasNextMatch = false;
            // ...and this branch used to return BEFORE RefreshPortal, so a sacked manager got no
            // gauge refresh and — fatally — no NotifyCareerState, which is what makes the SACKED
            // card appear at all.
            RefreshPortal();
            return;
        }

        CareerSummaryLine = "";
        var next = _s.NextFixture();
        if (next is not null)
        {
            _fixtureId = next.Id;
            _matchday = next.Matchday;
            _kind = next.Kind;
            _homeId = next.HomeTeamId;
            _awayId = next.AwayTeamId;
            _homeName = _s.TeamName(_homeId);
            _awayName = _s.TeamName(_awayId);
            // The AI opponent fields its best XI + a tactic to beat you before this match.
            var oppId = _homeId == _s.CurrentTeamId ? _awayId : _homeId;
            try { _s.PickBestXiAndTactic(oppId, _s.CurrentTeamId); } catch { /* never blocks load */ }
            LoadMatchPlayers();   // both XIs feed the event pickers (P3)
            var kind = next.Kind switch
            {
                "friendly" => "Preseason Friendly",
                "cup" => $"{Session.CupNameFor(next.LeagueId)} — {Session.CupRoundName(next.Matchday)}",
                _ => $"Matchday {next.Matchday}",
            };
            var when = ML.Core.Scheduling.SeasonCalendar.Label(_s.DateOfFixture(next));
            var derby = "";
            try { if (next.Kind != "friendly" && _s.IsDerby(_homeId, _awayId)) derby = " · 🔥 DERBY"; }
            catch { /* rivalries are additive */ }
            NextMatchLabel = $"{kind} · {when}{derby}\n{_homeName}  vs  {_awayName}";
            try { DeadlineVisible = _s.IsDeadlineDay(); } catch { DeadlineVisible = false; }
            try
            {
                PreTalkVisible = _s.TalkAvailable(next.Id, preMatch: true);
                TalkHintLine = _s.TalkHint(preMatch: true, _homeId, _awayId, null);
            }
            catch { PreTalkVisible = false; }
            HasNextMatch = true;
            ResultEntryOpen = false;          // a fresh fixture always opens on the OCCASION
            ShootoutHome = ShootoutAway = false;
            OnPropertyChanged(nameof(ShootoutHomeLabel));
            OnPropertyChanged(nameof(ShootoutAwayLabel));
            OnPropertyChanged(nameof(NeedsShootout));
            // NOTE: FtVisible is NOT reset here — RecordResult raises the banner and then
            // loads the next fixture; clearing it here killed the moment before one frame
            // rendered (the audit's "dead banner"). It clears with the report, or on kickoff.
            try
            {
                var opp = _homeId == _s.CurrentTeamId ? _awayId : _homeId;
                DugoutLine = $"In the other dugout: {_s.ManagerNameOf(opp)}";
            }
            catch { DugoutLine = ""; }
            MatchStatus = "";                 // no pipeline jargon in the hero card (UX audit)
        }
        else
        {
            NextMatchLabel = "Season complete — no fixtures left";
            HasNextMatch = false;
            MatchStatus = "";
        }

        RefreshPortal();
    }

    /// <summary>
    /// Rebuild the portal cards (opposition report, schedule, mini table, position tile) AND the
    /// gauges and career state — everything on this screen that moves when the world does. It runs
    /// on load, after every recorded result, and as the refresh callback behind the right-click
    /// menus, which is precisely the set of moments the tiles used to sleep through. A card
    /// failure must never brick the Office, so this swallows and moves on.
    /// </summary>
    private void RefreshPortal()
    {
        try { Position = Ordinal(_s.CurrentPosition()); } catch { /* card-only */ }
        try { BuildOpposition(); }
        catch (Exception ex) { HasOpposition = false; Program.Log("BuildOpposition", ex); }
        try { BuildSchedule(); } catch { /* card-only */ }
        try { BuildMiniTable(); } catch { /* card-only */ }
        try
        {
            // Job security: sitting in the drop zone deep into the season turns up the heat.
            var pos = _s.CurrentPosition();
            var table = _s.Table();
            var played = table.FirstOrDefault(r => r.TeamId.Value == _s.CurrentTeamId)?.Played ?? 0;
            JobLine = pos > 0 && played >= 8 && pos > table.Count - 3
                ? "⚠ The board is losing patience — you're in the relegation places."
                : "";
        }
        catch { /* card-only */ }

        // The tiles below the fold and the card the whole screen hangs on. Last, so a card that
        // throws on its way here cannot cost us the gauges (each is guarded inside anyway).
        RefreshGauges();
        NotifyCareerState();
    }

    /// <summary>Knowledge gate for opponent players shown on the Office (letters, never numbers).</summary>
    private int OppKnowledgeOf(long playerId)
    {
        try { return _s.FmAttributeMode ? _s.KnowledgeOf(playerId) : 100; }
        catch { return 100; }
    }

    private void BuildOpposition()
    {
        OppForm.Clear();
        HasOppForm = false;
        if (!HasNextMatch)
        {
            HasOpposition = false;
            OppId = 0;
            KeyPlayerId = 0;
            KeyPlayerName = "";
            CanScoutOpp = false;
            return;
        }

        // The panel must NEVER contradict the hero ("No fixture scheduled" under "vs Arsenal" —
        // UX audit, glaring): the core identity is established first and HasOpposition set EARLY,
        // so a failure in any enrichment below degrades one line, not the whole panel.
        var oppId = _homeId == _s.CurrentTeamId ? _awayId : _homeId;
        OppId = oppId;
        OppName = _s.TeamName(oppId);
        OppBadgeText = Visuals.Initials(OppName);
        try
        {
            OppBadgeBrush = Visuals.Brush(_s.TeamColor(oppId));
            OppBadgeStroke = Visuals.Brush(_s.TeamSecondary(oppId));
        }
        catch { OppBadgeBrush = Visuals.Brush(null); OppBadgeStroke = Visuals.Brush(null); }
        try { OppLogo = Visuals.LoadBitmap(_s.TeamLogoPath(oppId)); } catch { OppLogo = null; }
        HasOpposition = true;

        try
        {
            var row = _s.Table().FirstOrDefault(r => r.TeamId.Value == oppId);
            OppPositionLine = row is null ? _s.LeagueName : $"{Ordinal(row.Position)} in {_s.LeagueName}";
        }
        catch { OppPositionLine = ""; }

        // Last five league results, oldest → newest, from the opponent's point of view.
        try
        {
            var played = _s.Repo.Fixtures(_s.SeasonId)
                .Where(f => f.Kind == "league" && f.Played
                            && (f.HomeTeamId == oppId || f.AwayTeamId == oppId))
                .OrderBy(f => f.Matchday).ThenBy(f => f.Id)
                .ToList();
            foreach (var f in played.TakeLast(5))
            {
                var r = _s.ResultFor(f.Id);
                if (r is null) continue;
                var us = f.HomeTeamId == oppId ? r.HomeGoals : r.AwayGoals;
                var them = f.HomeTeamId == oppId ? r.AwayGoals : r.HomeGoals;
                OppForm.Add(us > them ? new FormChipVm("W", WinBrush)
                    : us == them ? new FormChipVm("D", DrawBrush)
                    : new FormChipVm("L", LossBrush));
            }
        }
        catch { /* a fresh season has no form to show */ }
        HasOppForm = OppForm.Count > 0;

        // Preferred shape: the opponent's own phase-0 formation geometry, clustered into lines.
        try
        {
            var fid = _s.Repo.TeamTactics(oppId).FirstOrDefault(t => t.Phase == 0)?.FormationId;
            var shape = fid is int f0
                ? Formations.ShapeOf(_s.Repo.FormationSlots(f0).Select(sl => sl.Y))
                : "—";
            OppShapeLine = $"Preferred shape: {shape}  ·  {_s.ClubTier(oppId)}";
        }
        catch { OppShapeLine = ""; }

        // Match preview from ELO — always phrased from YOUR point of view.
        try
        {
            var youAreHome = _homeId == _s.CurrentTeamId;
            var odds = _s.MatchOdds(_homeId, _awayId);
            var (win, draw, loss) = youAreHome
                ? (odds.HomePercent, odds.DrawPercent, odds.AwayPercent)
                : (odds.AwayPercent, odds.DrawPercent, odds.HomePercent);
            OddsLine = win >= 55 ? "Clear favourites"
                : win >= 40 && win > loss ? "Slight favourites"
                : loss >= 55 ? "Firm underdogs"
                : loss >= 40 && loss > win ? "Underdogs — nothing to lose"
                : "Evenly matched";
            OddsWin = win;
            OddsDraw = draw;
            OddsLoss = loss;
        }
        catch { OddsLine = ""; }

        try
        {
            var key = _s.KeyPlayer(oppId);
            // The id survives the sentence: a line you can right-click must know WHO it names.
            KeyPlayerId = key?.Id ?? 0;
            KeyPlayerName = key?.Name ?? "";
            // GradeMasked answers "?" for a man nobody has watched, and "(AMF ?)" on a card
            // reads as a rendering fault rather than as ignorance. When there is no grade to
            // give, the bracket carries his position alone — the card says "No dossier on them
            // yet" two lines below, which is where that fact belongs.
            var grade = ML.Core.Development.AttributeKnowledge
                .GradeMasked(key?.OverallRating ?? 0, key is null ? 0 : OppKnowledgeOf(key.Id));
            KeyPlayerLine = key is null ? ""
                : grade == "?" ? $"Key player: {key.Name}  ({key.Position})"
                : $"Key player: {key.Name}  ({key.Position} {grade})";
        }
        catch { KeyPlayerLine = ""; KeyPlayerId = 0; KeyPlayerName = ""; }

        try { AssistantLine = _s.AssistantNote(_matchday); } catch { AssistantLine = ""; }

        // The scout's briefing — only when this opponent has actually been scouted. When there's
        // no dossier the card OFFERS the mission (the button below) instead of naming a screen.
        var haveDossier = false;
        try
        {
            var (scouted, summary, suggestion) = _s.OppositionBriefingFor(oppId);
            haveDossier = scouted;
            BriefingSummary = scouted ? summary : "No dossier on them yet.";
            BriefingSuggestion = scouted ? suggestion : "";
        }
        catch { BriefingSummary = ""; BriefingSuggestion = ""; }

        RefreshScoutGuard(haveDossier);

        HasOpposition = true;
    }

    [ObservableProperty] private string _briefingSummary = "";
    [ObservableProperty] private string _briefingSuggestion = "";

    // --- "Scout them" on the opposition card: the mission is an ACT here, not a signpost ------

    [ObservableProperty] private int _oppId;
    [ObservableProperty] private long _keyPlayerId;
    [ObservableProperty] private string _keyPlayerName = "";
    [ObservableProperty] private string _scoutOppLabel = "🔍 Scout them";
    [ObservableProperty] private string _scoutOppHint = "";
    [ObservableProperty] private bool _canScoutOpp;

    /// <summary>Label + enablement for the scout button — the refusal is on the button, honestly.</summary>
    private void RefreshScoutGuard(bool haveDossier)
    {
        try
        {
            var noScout = _s.StaffFor("Scout") is null;
            var busy = _s.ActiveScoutJob() is not null;
            CanScoutOpp = OppId != 0 && !noScout && !busy;
            (ScoutOppLabel, ScoutOppHint) =
                noScout ? ("🔍 Scout them — no scout hired", "Hire a scout on the Staff screen first.")
                : busy ? ("🔍 Scout them — scout busy", "Your scout is already on a mission — one at a time.")
                : haveDossier ? ("🔍 Scout them again", $"Send your scout back to watch {OppName}.")
                : ("🔍 Scout them", $"Send your scout to watch {OppName} — report in {Session.ScoutMatchdays} matchdays.");
        }
        catch { CanScoutOpp = false; }
    }

    [RelayCommand]
    private void ScoutOpposition()
    {
        if (OppId == 0) return;
        var line = _s.StartScoutJob("club", OppId, OppName);
        try { BuildOpposition(); } catch { /* the card survives a failed refresh */ }
        MatchStatus = line;
    }

    // --- cross-screen hand-offs (P9): the Office is a hub, not a cul-de-sac -------------------

    [RelayCommand] private void GoToBoard() => Nav.Go("Board");
    [RelayCommand] private void GoToMarket() => Nav.Go("Market");
    [RelayCommand] private void GoToTable() => Nav.Go("Table");

    /// <summary>Shared club menu for whoever you play next (the opposition card's right-click).</summary>
    public Avalonia.Controls.ContextMenu? OppositionMenu() =>
        OppId == 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(OppId, OppName),
                status: t => MatchStatus = t, refresh: RefreshPortal);

    /// <summary>Shared player menu for the opponent's key man.</summary>
    public Avalonia.Controls.ContextMenu? KeyPlayerMenu() =>
        KeyPlayerId == 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(KeyPlayerId, KeyPlayerName),
                status: t => MatchStatus = t, refresh: RefreshPortal);

    /// <summary>Shared club menu for a schedule row's opponent.</summary>
    public Avalonia.Controls.ContextMenu? MenuFor(ScheduleRowVm r) =>
        r.TeamId == 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(r.TeamId, _s.TeamName(r.TeamId)),
                status: t => MatchStatus = t, refresh: RefreshPortal);

    /// <summary>Shared club menu for a mini-table row (the "· · ·" spacer has no id, so no menu).</summary>
    public Avalonia.Controls.ContextMenu? MenuFor(MiniRowVm r) =>
        r.TeamId == 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(r.TeamId, r.Team),
                status: t => MatchStatus = t, refresh: RefreshPortal);

    private void BuildSchedule()
    {
        Schedule.Clear();
        var myId = _s.CurrentTeamId;
        var mine = _s.Repo.Fixtures(_s.SeasonId)
            .Where(f => f.HomeTeamId == myId || f.AwayTeamId == myId)
            .OrderBy(f => f.Matchday).ThenBy(f => f.Id)
            .ToList();

        foreach (var f in mine.Where(f => f.Played).TakeLast(3))
        {
            var r = _s.ResultFor(f.Id);
            var us = f.HomeTeamId == myId ? r?.HomeGoals ?? 0 : r?.AwayGoals ?? 0;
            var them = f.HomeTeamId == myId ? r?.AwayGoals ?? 0 : r?.HomeGoals ?? 0;
            var bg = r is null ? NeutralChip : us > them ? WinBrush : us == them ? DrawBrush : LossBrush;
            Schedule.Add(new ScheduleRowVm(
                MdLabel(f), OppLabel(f, myId), r is null ? "—" : $"{us}-{them}", bg, Brushes.White,
                OppCrest(f, myId), OppIdOf(f, myId), f.Id));
        }

        foreach (var f in mine.Where(f => !f.Played).Take(4))
        {
            Schedule.Add(new ScheduleRowVm(MdLabel(f), OppLabel(f, myId), "—", NeutralChip, DimBrush,
                OppCrest(f, myId), OppIdOf(f, myId), f.Id));
        }
    }

    private static int OppIdOf(FixtureRow f, int myId) =>
        f.HomeTeamId == myId ? f.AwayTeamId : f.HomeTeamId;

    private string MdLabel(FixtureRow f) =>
        ML.Core.Scheduling.SeasonCalendar.ShortLabel(_s.DateOfFixture(f));

    private string OppLabel(FixtureRow f, int myId) =>
        f.HomeTeamId == myId ? $"{_s.TeamName(f.AwayTeamId)} (H)" : $"{_s.TeamName(f.HomeTeamId)} (A)";

    private Avalonia.Media.Imaging.Bitmap? OppCrest(FixtureRow f, int myId)
    {
        try { return Visuals.LoadBitmap(_s.TeamLogoPath(f.HomeTeamId == myId ? f.AwayTeamId : f.HomeTeamId)); }
        catch { return null; }
    }

    private void BuildMiniTable()
    {
        MiniTable.Clear();
        var table = _s.Table();
        var myId = _s.CurrentTeamId;

        foreach (var r in table.Take(6)) MiniTable.Add(MiniRow(r, myId));

        var me = table.FirstOrDefault(r => r.TeamId.Value == myId);
        if (me is not null && me.Position > 6)
        {
            MiniTable.Add(new MiniRowVm(
                "", "· · ·", "", "", "", Brushes.Transparent, DimBrush, FontWeight.Normal));
            MiniTable.Add(MiniRow(me, myId));
        }
    }

    private MiniRowVm MiniRow(LeagueTableRow r, int myId)
    {
        var you = r.TeamId.Value == myId;
        return new MiniRowVm(
            r.Position.ToString(),
            _s.TeamName(r.TeamId.Value),
            r.Played.ToString(),
            r.GoalDifference.ToString("+#;-#;0"),
            r.Points.ToString(),
            you ? YouRowBg : Brushes.Transparent,
            you ? YouRowFg : TextBrush,
            you ? FontWeight.Bold : FontWeight.Normal,
            Visuals.LoadBitmap(_s.TeamLogoPath(r.TeamId.Value)),
            r.TeamId.Value);
    }

    [RelayCommand]
    private async Task PlayMatch()
    {
        if (!HasNextMatch || IsCompiling) return;
        IsCompiling = true;
        FtVisible = false;       // kickoff of the next one ends the last result's moment
        ReportVisible = false;
        MatchStatus = "";

        // AI managers pick both matchday XIs from form/fatigue/availability before the compile.
        // Selection failing (e.g. fresh DB without the condition table) must never brick the button.
        try
        {
            _s.PrepareMatchday(_homeId, _awayId, _matchday);
        }
        catch (Exception ex)
        {
            MatchStatus = $"XI selection skipped: {ex.Message}";
        }

        void Log(string line) => Dispatcher.UIThread.Post(() =>
            MatchStatus = string.IsNullOrEmpty(MatchStatus) ? line : $"{MatchStatus}\n{line}");
        try
        {
            await MatchLauncher.PlayMatchAsync(_homeId, _awayId, _homeName, _awayName, Log);
            ResultEntryOpen = true;   // the game is up — the card becomes the entry desk
        }
        finally
        {
            IsCompiling = false;
        }
    }

    /// <summary>Titles and promotions get the full-screen moment they deserve (UX P1) — fired
    /// when the season's last fixture is recorded, before the rollover button appears.</summary>
    private void CheckForCelebration()
    {
        try
        {
            if (!(_s.SeasonComplete())) return;
            var table = _s.Table();
            var pos = 0;
            for (var i = 0; i < table.Count; i++)
            {
                if (table[i].TeamId.Value == _s.CurrentTeamId) { pos = i + 1; break; }
            }
            if (pos <= 0) return;
            var clubName = _s.TeamName(_s.CurrentTeamId);
            var inTopFlight = _s.LeagueId == 9000;
            if (pos == 1 && inTopFlight)
            {
                CelebrationTitle = "🏆  CHAMPIONS!";
                CelebrationSub = $"{clubName} are champions. The whole city is yours tonight.";
                CelebrationVisible = true;
            }
            else if (!inTopFlight && pos <= 3)
            {
                CelebrationTitle = pos == 1 ? "🏆  CHAMPIONS — PROMOTED!" : "📈  PROMOTED!";
                CelebrationSub = $"{clubName} are going up. Top-flight football next season.";
                CelebrationVisible = true;
            }
        }
        catch { /* celebration is additive — never blocks recording */ }
    }

    /// <summary>End the season: sim the rest, age squads, generate next season's fixtures.</summary>
    [RelayCommand]
    private void AdvanceSeason()
    {
        if (HasNextMatch) return;
        var summary = _s.AdvanceToNextSeason();
        LoadNextMatch();
        MatchStatus = summary;   // after LoadNextMatch, so the rollover summary stays visible
    }

    /// <summary>Undo the most recently recorded of your results (typos happen).</summary>
    [RelayCommand]
    private void UndoResult()
    {
        try
        {
            var msg = _s.UndoLastResult();
            ReportVisible = false;   // the report on screen is the result that was just undone
            LoadNextMatch();
            ResultEntryOpen = HasNextMatch;   // straight back to the desk: undo means re-enter
            MatchStatus = msg;
        }
        catch (Exception ex)
        {
            MatchStatus = $"Undo failed: {ex.Message}";
        }
    }

    /// <summary>Record the score you played in eFootball, then advance to the next fixture.</summary>
    [RelayCommand]
    private void RecordResult()
    {
        if (!HasNextMatch) return;
        if (_kind == "cup" && (int)HomeScore == (int)AwayScore)
        {
            if (!ShootoutHome && !ShootoutAway)
            {
                ImportNotice = "A cup tie needs a winner — it finished level, so pick who won the shoot-out.";
                return;
            }
            try { _s.SetCupShootoutWinner(_fixtureId, ShootoutHome ? _homeId : _awayId); }
            catch (Exception ex)
            {
                Program.Log("Dashboard.SetCupShootoutWinner", ex);
                ImportNotice = $"The shoot-out winner could not be saved: {ex.Message}";
                return;
            }
        }
        // Snapshot the gauges so the report can show what this result MOVED (P3).
        int moraleBefore = 60, boardBefore = 58, fansBefore = 55;
        try { moraleBefore = _s.SquadMoraleAverage(); } catch { }
        try { boardBefore = _s.BoardConfidenceNow; } catch { }
        try { fansBefore = _s.FanHappiness(); } catch { }
        FoldPicksIntoTexts();   // pickers beat typing (P3)
        try
        {
            _s.Repo.RecordResult(new ResultRow
            {
                FixtureId = _fixtureId, HomeGoals = (int)HomeScore, AwayGoals = (int)AwayScore,
            });
        }
        catch (Exception ex)
        {
            // The one call in this method that had no guard — on the most-pressed button in the
            // app, where a locked file threw straight into the input dispatcher. Nothing has been
            // written at this point, so the desk stays open with everything still in it.
            Program.Log("Dashboard.RecordResult", ex);
            MatchStatus = $"The result could NOT be saved: {ex.Message}" + Environment.NewLine +
                          "Nothing was recorded — your score and scorers are still here. Try again.";
            return;
        }
        // Sim the rest of this matchday (the CPU games) so the league table moves with you,
        // then move the cup along: sim the round's other ties and draw the next round when done.
        // Cup midweeks share matchday numbers with league rounds — recording a cup tie must
        // NOT play out that league round early, so the league pass only runs for league games.
        var condNote = "";
        var condNote2 = "";
        if (_kind != "cup")
        {
            try { _s.PlayOutMatchday(_matchday, _fixtureId); }
            catch (Exception ex)
            {
                Program.Log("Dashboard.PlayOutMatchday", ex);
                condNote2 = Environment.NewLine +
                            $"The other games this matchday could not be played: {ex.Message}";
            }
        }
        try
        {
            _s.AdvanceCup(_matchday, _fixtureId);
        }
        catch (Exception ex)
        {
            condNote2 = $"\nCup update skipped: {ex.Message}";
        }

        // Your match's player stats become season stats: goals, assists, cards, ratings — the
        // four things eFootball's post-match screens actually give.
        var scorerNote = "";
        try
        {
            _s.RecordAppearances(_fixtureId, _homeId, _awayId);
            scorerNote = _s.RecordMatchStats(
                _fixtureId, _homeId, _awayId, ScorersText, AssistsText, CardsText, RatingsText);
            if (scorerNote.Length > 0) scorerNote = "\n" + scorerNote;
        }
        catch { /* stats never block recording */ }
        // Cards become bans — after the events above are in, so this match's reds count.
        try { _s.SettleSuspensions(_fixtureId, _homeId, _awayId); }
        catch (Exception ex) { Program.Log("Dashboard.SettleSuspensions", ex); }
        scorerNote += StoreExportForRecordedFixture(_fixtureId);

        // Apply fatigue/recovery, form and injuries. Cup days load only the two clubs involved;
        // league days run the league-wide pass. Guarded so a missing table never blocks recording.
        try
        {
            if (_kind == "cup")
            {
                _s.UpdateConditionsAfterCup(_homeId, _awayId, _matchday);
            }
            else
            {
                _s.UpdateConditionsAfterMatchday(_matchday);
            }
        }
        catch (Exception ex)
        {
            condNote = $"\nCondition update skipped: {ex.Message}";
        }

        // Post-match mail: press reaction, medical report, training milestones, contract warnings.
        try
        {
            _s.PostMatchInbox(_fixtureId, _homeId, _awayId, _matchday,
                (int)HomeScore, (int)AwayScore, _kind);
        }
        catch { /* mail never blocks recording */ }

        // The board, the fans and your reputation react — and the board can act (D2/P2).
        try
        {
            _s.ApplyCareerAfterResult(_homeId, _awayId, (int)HomeScore, (int)AwayScore, _kind);
        }
        catch { /* the career layer never blocks recording */ }
        try
        {
            _s.ApplyFansAfterResult(_homeId, _awayId, (int)HomeScore, (int)AwayScore, _kind);
            if (_kind != "friendly")
                _s.ApplyDerbySwing(_homeId, _awayId, (int)HomeScore, (int)AwayScore);
        }
        catch { /* the fans never block recording */ }

        // Facing a club teaches you their XI (P5 knowledge).
        try
        {
            _s.LearnOpponentFromMatch(_homeId == _s.CurrentTeamId ? _awayId : _homeId);
        }
        catch { /* knowledge is additive */ }

        // The full-time dressing room awaits your word (once, this fixture).
        _lastFixtureId = _fixtureId;
        _lastHomeId = _homeId;
        _lastAwayId = _awayId;
        var usG = (int)HomeScore;
        var themG = (int)AwayScore;
        if (_homeId != _s.CurrentTeamId) (usG, themG) = (themG, usG);
        _lastOutcome = usG > themG ? 1 : usG == themG ? 0 : -1;
        try { PostTalkVisible = _s.TalkAvailable(_lastFixtureId, preMatch: false); }
        catch { PostTalkVisible = false; }

        // The report needs the recorded fixture's identity — LoadNextMatch will overwrite it.
        var repFixture = _fixtureId;
        var repHome = _homeId;
        var repAway = _awayId;
        var repHg = (int)HomeScore;
        var repAg = (int)AwayScore;
        var repKind = _kind;

        // FULL TIME gets a MOMENT: a coloured banner in your result's honour — win green,
        // draw slate, defeat red — instead of one clause in the status string (UX P1).
        FtLine = $"FULL TIME   {_homeName} {(int)HomeScore} – {(int)AwayScore} {_awayName}";
        FtBrush = new SolidColorBrush(Color.Parse(
            _lastOutcome > 0 ? "#1F9D4D" : _lastOutcome == 0 ? "#3A4759" : "#D64545"));
        FtVisible = true;
        CheckForCelebration();

        var recorded = $"Recorded {_homeName} {(int)HomeScore}–{(int)AwayScore} {_awayName}, " +
                       "and simmed the rest of the matchday. Table updated — next match loaded."
                       + scorerNote + condNote + condNote2;
        HomeScore = 0;
        AwayScore = 0;
        ScorersText = "";
        AssistsText = "";
        CardsText = "";
        RatingsText = "";
        LoadNextMatch();
        MatchStatus = recorded;   // after LoadNextMatch, so the confirmation stays visible
        BuildPostMatchReport(repFixture, repHome, repAway, repHg, repAg, repKind,
            moraleBefore, boardBefore, fansBefore);
    }

    private static string Ordinal(int n) => n switch
    {
        0 => "—",
        11 or 12 or 13 => $"{n}th",
        _ when n % 10 == 1 => $"{n}st",
        _ when n % 10 == 2 => $"{n}nd",
        _ when n % 10 == 3 => $"{n}rd",
        _ => $"{n}th",
    };
}

/// <summary>One picked match event: a player chosen from the two known XIs (P3).</summary>
public sealed partial class EventPickRow : ObservableObject
{
    public EventPickRow(ObservableCollection<string> players) => Players = players;

    public ObservableCollection<string> Players { get; }

    [ObservableProperty] private string? _selected;

    /// <summary>Card rows only: a red, not a yellow. Folds as "Name r", the stats engine's red.</summary>
    [ObservableProperty] private bool _isRed;
}
