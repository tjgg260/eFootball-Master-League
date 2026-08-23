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

/// <summary>A continent tile on the stylized world map.</summary>
public sealed class ContinentOption
{
    public ContinentOption(ContinentDef def, IReadOnlyList<CatalogCountry> countries)
    {
        Def = def;
        Countries = countries;
        ClubCount = countries.Sum(c => c.Leagues.Sum(l => l.Teams.Count));
    }
    public ContinentDef Def { get; }
    public IReadOnlyList<CatalogCountry> Countries { get; }
    public string Name => Def.Name;
    public string Glyph => Def.Glyph;
    public int CountryCount => Countries.Count;
    public int ClubCount { get; }
    public string Summary => $"{Visuals.Plural(CountryCount, "nation")} · {Visuals.Plural(ClubCount, "club")}";
    public IBrush Accent => Visuals.Brush(Def.Accent);
    public double NX => Def.X;   // normalized map position (0-1)
    public double NY => Def.Y;
}

/// <summary>A country card in the continent view.</summary>
public sealed class CountryOption
{
    public CountryOption(CatalogCountry c)
    {
        Country = c;
        ClubCount = c.Leagues.Sum(l => l.Teams.Count);
    }
    public CatalogCountry Country { get; }
    public string Name => Country.Name;
    public int LeagueCount => Country.Leagues.Count;
    public int ClubCount { get; }
    public string Summary => $"{Visuals.Plural(LeagueCount, "league")} · {Visuals.Plural(ClubCount, "club")}";
    public string Badge => Country.Name.Length >= 2 ? Country.Name[..2].ToUpperInvariant() : Country.Name;
    public Bitmap? Flag => Visuals.LoadBitmap(Country.Flag);
    public bool HasFlag => Flag is not null;
}

public enum CareerStage { Continent, Country, League, Team }

public sealed partial class NewCareerViewModel : ObservableObject
{
    private readonly List<CatalogCountry> _allCountries = new();

    public NewCareerViewModel()
    {
        _allCountries.AddRange(CatalogData.Load());
        foreach (var def in ML.App.Continents.All)
        {
            var members = _allCountries
                .Where(c => ML.App.Continents.Of(c.Name) == def.Name)
                .OrderByDescending(c => c.Leagues.Sum(l => l.Teams.Count))
                .ToList();
            if (members.Count > 0)
                Continents.Add(new ContinentOption(def, members));
        }
    }

    // The four stages of the world drill-down.
    public ObservableCollection<ContinentOption> Continents { get; } = new();
    public ObservableCollection<CountryOption> Countries { get; } = new();
    public ObservableCollection<CatalogLeague> Leagues { get; } = new();
    public ObservableCollection<CareerTeamOption> Teams { get; } = new();

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowContinents))]
    [NotifyPropertyChangedFor(nameof(ShowCountries))]
    [NotifyPropertyChangedFor(nameof(ShowLeagues))]
    [NotifyPropertyChangedFor(nameof(ShowTeams))]
    [NotifyPropertyChangedFor(nameof(CanGoBack))]
    [NotifyPropertyChangedFor(nameof(Breadcrumb))]
    [NotifyCanExecuteChangedFor(nameof(BackCommand))]
    private CareerStage _stage = CareerStage.Continent;

    public bool ShowContinents => Stage == CareerStage.Continent;
    public bool ShowCountries => Stage == CareerStage.Country;
    public bool ShowLeagues => Stage == CareerStage.League;
    public bool ShowTeams => Stage == CareerStage.Team;
    public bool CanGoBack => Stage != CareerStage.Continent;

    [ObservableProperty] [NotifyPropertyChangedFor(nameof(Breadcrumb))] private ContinentOption? _pickedContinent;
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(Breadcrumb))] private CountryOption? _pickedCountry;
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(Breadcrumb))] private CatalogLeague? _selectedLeague;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartCareerCommand))]
    private CareerTeamOption? _selectedTeam;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Busy))]
    private bool _isBuilding;

    [ObservableProperty]
    private string _status = "🌍 Pick a continent to begin.";

    public bool Busy => IsBuilding;

    public string Breadcrumb
    {
        get
        {
            var parts = new List<string> { "World" };
            if (PickedContinent is not null) parts.Add(PickedContinent.Name);
            if (PickedCountry is not null) parts.Add(PickedCountry.Name);
            if (Stage == CareerStage.Team && SelectedLeague is not null) parts.Add(SelectedLeague.Display);
            return string.Join("  ›  ", parts);
        }
    }

    /// <summary>Raised with the loaded Session when a career has been built and is ready to open.</summary>
    public event Action<Session>? CareerStarted;

    [RelayCommand]
    private void PickContinent(ContinentOption? c)
    {
        if (c is null) return;
        PickedContinent = c;
        Countries.Clear();
        foreach (var co in c.Countries.OrderBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            Countries.Add(new CountryOption(co));
        Stage = CareerStage.Country;
        Status = $"{c.Name} — pick a nation.";
    }

    [RelayCommand]
    private void PickCountry(CountryOption? c)
    {
        if (c is null) return;
        PickedCountry = c;
        Leagues.Clear();
        foreach (var lg in c.Country.Leagues.OrderBy(l => l.Tier))
            Leagues.Add(lg);
        Stage = CareerStage.League;
        Status = $"{c.Name} — pick a league.";
    }

    [RelayCommand]
    private void PickLeague(CatalogLeague? lg)
    {
        if (lg is null) return;
        SelectedLeague = lg;
        Teams.Clear();
        foreach (var t in lg.Teams.OrderBy(t => t.Name, StringComparer.OrdinalIgnoreCase))
            Teams.Add(new CareerTeamOption(t));
        Stage = CareerStage.Team;
        Status = $"{lg.Display} — pick your club.";
    }

    [RelayCommand]
    private void PickTeam(CareerTeamOption? t) => SelectedTeam = t;

    [RelayCommand(CanExecute = nameof(CanGoBack))]
    private void Back()
    {
        switch (Stage)
        {
            case CareerStage.Team: Stage = CareerStage.League; SelectedTeam = null; break;
            case CareerStage.League: Stage = CareerStage.Country; break;
            case CareerStage.Country: Stage = CareerStage.Continent; break;
        }
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
