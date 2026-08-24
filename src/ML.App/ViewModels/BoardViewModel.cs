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
        Confidence = s.Board.Value;
        ConfidenceLabel = s.Board.Label;
        UnderThreat = s.Board.ManagerUnderThreat;
        Position = s.CurrentPosition();
        var teams = s.LeagueTeams().Count;
        Sacked = s.IsSacked;
        JobSecurity = Sacked ? "DISMISSED — the board has made a change"
            : s.Board.ManagerUnderThreat ? "At risk — the board expects improvement"
            : Confidence >= 70 ? "Secure — the board backs you"
            : "Stable — meet expectations and you're fine";
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
                $"{o.Club}  ·  {o.League}  ·  {ML.Core.Development.AttributeKnowledge.Grade(o.SquadRating)} squad",
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

    public override string Title => "Board";
    public override string Icon => "🏛️";
    public string Expectation { get; }
    public int Confidence { get; }
    public string ConfidenceLabel { get; }
    public bool UnderThreat { get; }
    public int Position { get; }
    public string JobSecurity { get; }
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

    [RelayCommand]
    private void RequestBudget()
    {
        LeverStatus = _s.RequestBudget();
        RefreshFacilities();
    }

    [RelayCommand]
    private void UpgradeTraining()
    {
        LeverStatus = _s.UpgradeTrainingGround();
        RefreshFacilities();
    }

    [RelayCommand]
    private void UpgradeAcademy()
    {
        LeverStatus = _s.UpgradeAcademy();
        RefreshFacilities();
    }

    private void RefreshFacilities() =>
        FacilitiesLine = $"Training ground: level {_s.TrainingLevel}/5 · Academy: level {_s.AcademyLevel}/5" +
                         $" · Manager: {_s.ManagerName}";

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
        }
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
