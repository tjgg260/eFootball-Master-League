using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

/// <summary>A club option in the New Career picker — catalog data plus its loaded crest.</summary>
public sealed class CareerTeamOption
{
    public CareerTeamOption(CatalogTeam t)
    {
        Name = t.Name;
        RfsId = t.RfsId;
        Rating = (int)Math.Round(RawToEfootball(t.Rating));
        Logo = Visuals.LoadBitmap(t.Logo);
        Badge = Visuals.Initials(t.Name);
        BadgeBrush = Visuals.Brush(null);
    }

    public string Name { get; }
    public int RfsId { get; }
    public int Rating { get; }
    public Bitmap? Logo { get; }
    public string Badge { get; }
    public IBrush BadgeBrush { get; }

    // Catalog rating is RFS raw overall; show it on eFootball's ~40-99 feel.
    private static double RawToEfootball(double raw) => raw <= 40 ? raw : Math.Min(99, 40 + (raw - 40));
}

public sealed partial class NewCareerViewModel : ObservableObject
{
    public NewCareerViewModel()
    {
        foreach (var c in CatalogData.Load())
        {
            Countries.Add(c);
        }
        SelectedCountry = Countries.FirstOrDefault(c => c.Name == "England") ?? Countries.FirstOrDefault();
    }

    public ObservableCollection<CatalogCountry> Countries { get; } = new();
    public ObservableCollection<CatalogLeague> Leagues { get; } = new();
    public ObservableCollection<CareerTeamOption> Teams { get; } = new();

    [ObservableProperty]
    private CatalogCountry? _selectedCountry;

    [ObservableProperty]
    private CatalogLeague? _selectedLeague;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartCareerCommand))]
    private CareerTeamOption? _selectedTeam;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Busy))]
    private bool _isBuilding;

    [ObservableProperty]
    private string _status = "Pick a country, a league, then the club you want to manage.";

    public bool Busy => IsBuilding;

    /// <summary>Raised with the loaded Session when a career has been built and is ready to open.</summary>
    public event Action<Session>? CareerStarted;

    partial void OnSelectedCountryChanged(CatalogCountry? value)
    {
        Leagues.Clear();
        if (value is null) { SelectedLeague = null; return; }
        foreach (var lg in value.Leagues)
        {
            Leagues.Add(lg);
        }
        SelectedLeague = Leagues.FirstOrDefault();
    }

    partial void OnSelectedLeagueChanged(CatalogLeague? value)
    {
        Teams.Clear();
        if (value is null) return;
        foreach (var t in value.Teams.OrderBy(t => t.Name, StringComparer.OrdinalIgnoreCase))
        {
            Teams.Add(new CareerTeamOption(t));
        }
        SelectedTeam = Teams.FirstOrDefault();
    }

    private bool CanStart() => SelectedTeam is not null && SelectedLeague is not null && !IsBuilding;

    [RelayCommand(CanExecute = nameof(CanStart))]
    private async Task StartCareer()
    {
        if (SelectedTeam is null || SelectedLeague is null) return;
        IsBuilding = true;
        var club = SelectedTeam.Name;
        var rfsId = SelectedTeam.RfsId;
        var compId = SelectedLeague.CompId;
        void Log(string line) => Dispatcher.UIThread.Post(() => Status = line);
        try
        {
            var session = await CareerBuilder.BuildAsync(compId, rfsId, club, Log);
            if (session is null)
            {
                Status = $"Couldn't start {club}. See the log; is Python installed?";
                return;
            }
            CareerStarted?.Invoke(session);
        }
        finally
        {
            IsBuilding = false;
        }
    }
}
