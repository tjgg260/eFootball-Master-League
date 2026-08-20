using System.Collections.ObjectModel;
using Avalonia.Controls.ApplicationLifetimes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ML.App.Views;

namespace ML.App.ViewModels;

// --- Board (board confidence, job security, manager career + job offers) ----------

public sealed record JobOfferRow(int TeamId, string Line);

public sealed record ObjectiveLine(string Icon, string Description, string Progress, string Importance);

public sealed partial class BoardViewModel : PageViewModel
{
    private readonly Session _s;

    public BoardViewModel(Session s)
    {
        _s = s;
        Expectation = s.Board.Expectation.ToString();
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
            : $"The board expects a {Expectation} finish. You are {Position} of {teams}.";
        Reputation = s.Reputation;
        ReputationLabel = s.ReputationLabel;
        CareerLine = s.CareerSummary();
        // Season objectives (P2): the board's list with live progress.
        try
        {
            foreach (var o in s.Objectives())
            {
                Objectives.Add(new ObjectiveLine(
                    o.Status == 1 ? "✅" : o.Status == 2 ? "❌" : "◻",
                    o.Description, o.Progress, o.Importance.ToUpperInvariant()));
            }
        }
        catch { /* objectives are additive */ }
        FanLine = $"The fans: {s.FanLabel} ({s.FanHappiness()}/100)";

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
                EloTrendLabel = $"Club rating over {history.Count - 1} games — now {history[^1]} " +
                                $"(peak {hi}, low {lo})";
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

        Offers = new ObservableCollection<JobOfferRow>(
            s.JobOffers().Select(o => new JobOfferRow(o.TeamId,
                $"{o.Club}  ·  {o.League}  ·  squad {o.SquadRating}")));
        RefreshFacilities();
        OffersNote = Offers.Count > 0
            ? "Accepting ends your current post immediately and reopens the app at your new club."
            : Sacked
                ? "No offers on the table yet — they arrive in the inbox as your name recovers."
                : "No clubs are courting you right now. Results and silverware change that.";
    }

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
    public string OffersNote { get; }
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

    /// <summary>Take the job, then reload the whole app on the new club's Session.</summary>
    [RelayCommand]
    private void AcceptOffer(JobOfferRow offer)
    {
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
}
