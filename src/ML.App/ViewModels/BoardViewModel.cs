using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.App.Views;

namespace ML.App.ViewModels;

// --- Board (board confidence, job security, manager career + job offers) ----------

public sealed record JobOfferRow(int TeamId, string Club, string Line, Avalonia.Media.Imaging.Bitmap? Crest)
{
    /// <summary>Accepting ends your current post, so it is a two-step: the label is the arm state.</summary>
    public const string AcceptIdle = "Accept job";

    public string AcceptLabel { get; init; } = AcceptIdle;
}

/// <summary>
/// One board objective. NavPage is the screen that actually answers it — a league finish is a
/// question about the table, a cup run about the cup. Objectives whose kind has no obvious
/// home (youth starts, home goals, the derby) carry no link rather than a guessed one.
/// </summary>
public sealed record ObjectiveLine(
    string Icon, string Description, string Progress, string Importance, string NavPage = "")
{
    public bool HasNav => NavPage.Length > 0;
    public string LinkText => $"{Description}  →";
}

public sealed partial class BoardViewModel : PageViewModel
{
    private readonly Session _s;

    public BoardViewModel(Session s)
    {
        _s = s;
        Expectation = Visuals.ExpectationLabel(s.Board.Expectation);
        Position = s.CurrentPosition();
        var teams = s.LeagueTeams().Count;
        Sacked = s.IsSacked;
        // Confidence is read through BoardNow, not off s.Board: s.Board is the copy the Session
        // constructor took and never refreshed, so it showed the number from app launch however
        // many objectives had been settled since. RefreshBoard() re-reads it, and the levers
        // below call it again, because asking the board for money can move the board.
        RefreshBoard();
        Summary = Sacked
            ? s.SackedLine
            : s.LeagueResultsThisSeason() == 0
                ? $"The board's demand: {Expectation}. The season is yet to kick off."
                : $"The board's demand: {Expectation}. You are {Position} of {teams}.";
        Reputation = s.Reputation;
        ReputationLabel = s.ReputationLabel;
        CareerLine = s.CareerSummary();
        // Season objectives (P2): the board's list with live progress.
        try
        {
            foreach (var o in s.Objectives())
            {
                // Kind is stored on the row, so the click-through is read, never inferred.
                var page = o.Kind switch
                {
                    "league_finish" => "Table",
                    "cup_run" => "Cup",
                    _ => "",
                };
                Objectives.Add(new ObjectiveLine(
                    o.Status == 1 ? "✅" : o.Status == 2 ? "❌" : "◻",
                    o.Description, o.Progress, o.Importance.ToUpperInvariant(), page));
            }
        }
        catch { /* objectives are additive */ }
        FanLine = $"The fans: {s.FanLabel}";

        // The club's whole trajectory: ELO after every game ever recorded (P6 chart).
        try
        {
            var history = s.EloHistoryOfCurrentClub();
            if (history.Count >= 3)
            {
                const double w = 520, h = 72;
                int lo = history.Min(), hi = Math.Max(history.Max(), lo + 1);
                var step = w / (history.Count - 1);
                for (var i = 0; i < history.Count; i++)
                {
                    var y = h - 4 - (history[i] - lo) / (double)(hi - lo) * (h - 8);
                    EloPoints.Add(new Avalonia.Point(i * step, y));
                }
                EloTrendVisible = true;
                var last = history[^1];
                var trend = last >= hi - (hi - lo) / 10 ? "at a club high"
                    : last <= lo + (hi - lo) / 10 ? "at a club low"
                    : last > history[Math.Max(0, history.Count - 6)] ? "on the rise"
                    : last < history[Math.Max(0, history.Count - 6)] ? "slipping"
                    : "holding steady";
                EloTrendLabel = $"The club's standing across {history.Count - 1} games — currently {trend}";
            }
        }
        catch { EloTrendVisible = false; }

        // Fan happiness over the matchweeks (item 11) — the mood as a line, not just a word.
        try
        {
            var fans = s.ClubHistorySeries("fans");
            if (fans.Count >= 3)
            {
                const double w = 520, h = 48;
                var step = w / (fans.Count - 1);
                for (var i = 0; i < fans.Count; i++)
                    FanPoints.Add(new Avalonia.Point(i * step, h - 4 - fans[i] / 100.0 * (h - 8)));
                FanTrendVisible = true;
            }
        }
        catch { FanTrendVisible = false; }

        // The chairman gets a face on his own screen — the generated initials avatar (no
        // photo art exists for board members; same treatment as staff).
        try { ChairmanName = s.Chairman(); } catch { ChairmanName = ""; }

        Offers = new ObservableCollection<JobOfferRow>(
            s.JobOffers().Select(o => new JobOfferRow(o.TeamId, o.Club,
                $"{o.Club}  ·  {o.League}  ·  {ML.Core.Development.StarRating.Text(o.SquadRating)} squad",
                Visuals.LoadBitmap(s.TeamLogoPath(o.TeamId)))));
        RefreshFacilities();
        RefreshOffersNote();
    }

    private void RefreshOffersNote() =>
        OffersNote = Offers.Count > 0
            ? "Accepting ends your current post immediately and reopens the app at your new club. " +
              "Right-click a club to look at the squad first."
            : Sacked
                ? "No offers on the table yet — they arrive in the inbox as your name recovers."
                : "No clubs are courting you right now. Results and silverware change that.";

    /// <summary>
    /// Pull the board gauge back off the Session. Every field here is derived from one number,
    /// so they move together or not at all — a label that disagreed with its own bar was half
    /// of what made the dead confidence value so hard to spot.
    /// </summary>
    private void RefreshBoard()
    {
        var board = _s.BoardNow;
        Confidence = board.Value;
        ConfidenceLabel = board.Label;
        UnderThreat = board.ManagerUnderThreat;
        JobSecurity = Sacked ? "DISMISSED — the board has made a change"
            : UnderThreat ? "At risk — the board expects improvement"
            : Confidence >= 70 ? "Secure — the board backs you"
            : "Stable — meet expectations and you're fine";
    }

    public override string Title => "Board";
    public override string Icon => "🏛️";
    public string Expectation { get; }
    [ObservableProperty] private int _confidence;
    [ObservableProperty] private string _confidenceLabel = "";
    [ObservableProperty] private bool _underThreat;
    public int Position { get; }
    [ObservableProperty] private string _jobSecurity = "";
    public string Summary { get; }
    public bool Sacked { get; }
    public int Reputation { get; }
    public string ReputationLabel { get; }
    public string CareerLine { get; }
    public ObservableCollection<JobOfferRow> Offers { get; }
    public string ChairmanName { get; } = "";
    public string ChairmanLine => $"Chairman · {ChairmanName}";
    public string ChairmanMark => Visuals.Initials(ChairmanName);
    public Avalonia.Media.IBrush ChairmanBrush => NameAvatar.For(ChairmanName);
    public bool HasChairman => ChairmanName.Length > 0;
    public ObservableCollection<ObjectiveLine> Objectives { get; } = new();
    public string FanLine { get; } = "";
    public Avalonia.Points EloPoints { get; } = new();
    public bool EloTrendVisible { get; }
    public Avalonia.Points FanPoints { get; } = new();
    public bool FanTrendVisible { get; }
    public string EloTrendLabel { get; } = "";
    public bool HasOffers => Offers.Count > 0;

    // --- board levers (item 4): money and bricks ---------------------------------------

    [ObservableProperty] private string _leverStatus = "";
    [ObservableProperty] private string _facilitiesLine = "";
    [ObservableProperty] private string _offersNote = "";
    /// <summary>The offers panel's own status line — engine verbs land here verbatim.</summary>
    [ObservableProperty] private string _offerStatus = "";

    // Two-step, same idiom as the job offer below: these three spend real money (or the board's
    // patience) and used to go through on the first click, the price on the label the only word
    // said about it.
    private bool _budgetArmed;
    private bool _trainingArmed;
    private bool _academyArmed;

    [RelayCommand]
    private void RequestBudget()
    {
        if (!_budgetArmed)
        {
            _budgetArmed = true;
            LeverStatus = "Ask the board to move money into the transfer budget? It costs a " +
                          "little of their confidence whether they say yes or no. Click again to confirm.";
            return;
        }
        _budgetArmed = false;
        LeverStatus = _s.RequestBudget();
        RefreshFacilities();
        RefreshBoard();   // a refused ask costs you confidence — the gauge says so at once
    }

    [RelayCommand]
    private void UpgradeTraining()
    {
        if (_s.TrainingLevel >= 5) { LeverStatus = _s.UpgradeTrainingGround(); return; }
        if (!_trainingArmed)
        {
            _trainingArmed = true;
            LeverStatus = $"Upgrade the training ground for £{_s.FacilityUpgradeCost(_s.TrainingLevel):N0}? " +
                          "Click again to confirm.";
            return;
        }
        _trainingArmed = false;
        LeverStatus = _s.UpgradeTrainingGround();
        RefreshFacilities();
    }

    [RelayCommand]
    private void UpgradeAcademy()
    {
        if (_s.AcademyLevel >= 5) { LeverStatus = _s.UpgradeAcademy(); return; }
        if (!_academyArmed)
        {
            _academyArmed = true;
            LeverStatus = $"Upgrade the academy for £{_s.FacilityUpgradeCost(_s.AcademyLevel):N0}? " +
                          "Click again to confirm.";
            return;
        }
        _academyArmed = false;
        LeverStatus = _s.UpgradeAcademy();
        RefreshFacilities();
    }

    // The price of a lever belongs ON the lever. These three buttons said "Upgrade training
    // ground" and nothing else; you found out an upgrade costs £2m by pressing it, and if the
    // money was not there the only feedback was a refusal. A costly action states its price
    // before it is taken.
    [ObservableProperty] private string _upgradeTrainingLabel = "";
    [ObservableProperty] private string _upgradeAcademyLabel = "";
    [ObservableProperty] private string _requestBudgetTip = "";

    private void RefreshFacilities()
    {
        FacilitiesLine = $"Training ground: level {_s.TrainingLevel}/5 · Academy: level {_s.AcademyLevel}/5" +
                         $" · Manager: {_s.ManagerName}";
        UpgradeTrainingLabel = FacilityLabel("🏋 Upgrade training ground", _s.TrainingLevel,
            "The training ground is already state of the art");
        UpgradeAcademyLabel = FacilityLabel("🎓 Upgrade academy", _s.AcademyLevel,
            "The academy is already elite");
        RequestBudgetTip = "Ask the board to move money into the transfer budget. Asking costs " +
                           "you a little of their confidence whether they say yes or no.";
    }

    private string FacilityLabel(string verb, int level, string maxed) => level >= 5
        ? maxed
        : $"{verb} — £{_s.FacilityUpgradeCost(level):N0}";

    /// <summary>Open the screen that actually answers this objective (table, cup).</summary>
    [RelayCommand]
    private void OpenObjective(ObjectiveLine line)
    {
        if (line.HasNav) Nav.Go(line.NavPage);
    }

    // --- job offers: two-step accept, a real decline, and a look before you leap --------

    private int _armedOfferId;

    /// <summary>
    /// Take the job, then reload the whole app on the new club's Session. Two-step, because
    /// this is the single most irreversible button in the app: the first click arms the row.
    /// </summary>
    [RelayCommand]
    private void AcceptOffer(JobOfferRow offer)
    {
        if (_armedOfferId != offer.TeamId)
        {
            ArmOffer(offer.TeamId);
            OfferStatus = Sacked
                ? $"Take the {offer.Club} job? Click again to confirm."
                : $"Leaving {_s.CurrentTeamName} for {offer.Club} ends your post immediately. " +
                  "Click again to confirm.";
            return;
        }
        ArmOffer(0);
        _s.AcceptJobOffer(offer.TeamId);
        if (Avalonia.Application.Current?.ApplicationLifetime
                is IClassicDesktopStyleApplicationLifetime desktop
            && CareerLoader.TryLoad() is Session fresh)
        {
            var old = desktop.MainWindow;
            var main = new MainWindow { DataContext = new MainWindowViewModel(fresh) };
            desktop.MainWindow = main;
            main.Show();
            old?.Close();
            return;
        }
        // The job IS taken — AcceptJobOffer has already moved the career — but the window could
        // not be rebuilt on it. This branch used to not exist: the confirm click changed the
        // world and the screen sat there unchanged, saying nothing.
        OfferStatus = $"You have taken the {offer.Club} job, but the app could not reopen the career" +
                      (CareerLoader.LastFailure is { } why ? $": {why}" : ".") +
                      " Close and reopen the app to carry on at your new club.";
    }

    /// <summary>Turn an approach down: the club comes off the list and the season goes on.</summary>
    [RelayCommand]
    private void DeclineOffer(JobOfferRow offer)
    {
        ArmOffer(0);
        OfferStatus = _s.DeclineJobOffer(offer.TeamId);
        if (Offers.FirstOrDefault(o => o.TeamId == offer.TeamId) is { } row) Offers.Remove(row);
        RefreshOffersNote();
    }

    /// <summary>Arm exactly one offer row (0 = none) by re-stamping the accept labels.</summary>
    private void ArmOffer(int teamId)
    {
        _armedOfferId = teamId;
        for (var i = 0; i < Offers.Count; i++)
        {
            var want = teamId != 0 && Offers[i].TeamId == teamId
                ? (Sacked ? "Confirm — take the job?" : $"Confirm — leave {_s.CurrentTeamName}?")
                : JobOfferRow.AcceptIdle;
            if (Offers[i].AcceptLabel != want)
                Offers[i] = Offers[i] with { AcceptLabel = want };
        }
    }

    /// <summary>Turning your attention to another offer disarms the primed one.</summary>
    public void FocusOffer(JobOfferRow offer)
    {
        if (_armedOfferId != 0 && _armedOfferId != offer.TeamId) ArmOffer(0);
    }

    /// <summary>The shared club menu on an offer row: look at the squad before you decide.</summary>
    public ContextMenu? MenuFor(JobOfferRow offer) =>
        EntityActions.BuildMenu(_s, EntityRef.Club(offer.TeamId, offer.Club),
            status: t => OfferStatus = t);
}
