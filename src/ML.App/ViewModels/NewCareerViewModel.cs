using System;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.Json;
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
    public CareerTeamOption(CatalogTeam t, int squadSize = 0)
    {
        Name = t.Name;
        RfsId = t.RfsId;
        Rating = (int)Math.Round(RawToEfootball(t.Rating));
        Logo = Visuals.LoadBitmap(t.Logo);
        Badge = Visuals.Initials(t.Name);
        BadgeBrush = Visuals.Brush(null);
        SquadSize = squadSize;
    }

    public string Name { get; }
    public int RfsId { get; }
    public int Rating { get; }
    public Bitmap? Logo { get; }
    public string Badge { get; }
    public IBrush BadgeBrush { get; }

    /// <summary>Squad size from the catalog ("squad" key), 0 when unknown.</summary>
    public int SquadSize { get; }
    public bool HasSquad => SquadSize > 0;
    public string SquadLabel => Visuals.Plural(SquadSize, "player");

    /// <summary>Calibre as the app shows every rating: a letter, never the number.</summary>
    public string Grade => ML.Core.Development.AttributeKnowledge.Grade(Rating);

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

/// <summary>A league row: display-level cleanup of the raw catalog name. "England 6 (Simulated)"
/// renders as "England Division 6" plus a "simulated" chip; catalog data is never touched.</summary>
public sealed class LeagueOption
{
    public LeagueOption(CatalogLeague lg)
    {
        League = lg;
        IsSimulated = IsSimulatedName(lg.Display);
        Display = CleanDisplay(lg.Display);
    }

    public CatalogLeague League { get; }
    public bool IsSimulated { get; }
    public string Display { get; }
    public int Tier => League.Tier;
    public string Summary => League.Summary;
    public Bitmap? CompLogoBitmap => League.CompLogoBitmap;
    public bool HasCompLogo => League.HasCompLogo;

    private const string SimSuffix = "(Simulated)";

    internal static bool IsSimulatedName(string display) =>
        display.TrimEnd().EndsWith(SimSuffix, StringComparison.OrdinalIgnoreCase);

    /// <summary>"England 6 (Simulated)" → "England Division 6"; "Serie D (Simulated)" → "Serie D".
    /// Only simulated names get the "Division N" expansion — real names like "Ligue 2" keep theirs.</summary>
    internal static string CleanDisplay(string display)
    {
        var s = display.TrimEnd();
        if (!IsSimulatedName(s)) return s;
        s = s[..^SimSuffix.Length].TrimEnd();
        var m = System.Text.RegularExpressions.Regex.Match(s, @"^(.+\S)\s+(\d+)$");
        return m.Success ? $"{m.Groups[1].Value} Division {m.Groups[2].Value}" : s;
    }
}

public enum CareerStage { Continent, Country, League, Team, Manager }

public sealed partial class NewCareerViewModel : ObservableObject
{
    private readonly List<CatalogCountry> _allCountries = new();
    private readonly Dictionary<int, int> _squadOf;

    public NewCareerViewModel()
    {
        _allCountries.AddRange(CatalogData.Load());
        var (continentOverride, squadOf) = ReadCatalogExtras();
        _squadOf = squadOf;

        // A country's continent: an explicit "continent" key in catalog.json wins (data fix,
        // e.g. Peru → South America), otherwise the confederation map.
        string ContinentOf(CatalogCountry c) =>
            continentOverride.TryGetValue(c.Name, out var o) ? o : ML.App.Continents.Of(c.Name);

        foreach (var def in ML.App.Continents.All)
        {
            var members = _allCountries
                .Where(c => ContinentOf(c) == def.Name)
                .OrderByDescending(c => c.Leagues.Sum(l => l.Teams.Count))
                .ToList();
            if (members.Count > 0)
                Continents.Add(new ContinentOption(def, members));
        }
    }

    // The five stages of the drill-down.
    public ObservableCollection<ContinentOption> Continents { get; } = new();
    public ObservableCollection<CountryOption> Countries { get; } = new();
    public ObservableCollection<LeagueOption> Leagues { get; } = new();
    public ObservableCollection<CareerTeamOption> Teams { get; } = new();

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowContinents))]
    [NotifyPropertyChangedFor(nameof(ShowCountries))]
    [NotifyPropertyChangedFor(nameof(ShowLeagues))]
    [NotifyPropertyChangedFor(nameof(ShowTeams))]
    [NotifyPropertyChangedFor(nameof(ShowManager))]
    [NotifyPropertyChangedFor(nameof(CanGoBack))]
    [NotifyPropertyChangedFor(nameof(Breadcrumb))]
    [NotifyCanExecuteChangedFor(nameof(BackCommand))]
    private CareerStage _stage = CareerStage.Continent;

    public bool ShowContinents => Stage == CareerStage.Continent;
    public bool ShowCountries => Stage == CareerStage.Country;
    public bool ShowLeagues => Stage == CareerStage.League;
    public bool ShowTeams => Stage == CareerStage.Team;
    public bool ShowManager => Stage == CareerStage.Manager;
    public bool CanGoBack => Stage != CareerStage.Continent;

    [ObservableProperty] [NotifyPropertyChangedFor(nameof(Breadcrumb))] private ContinentOption? _pickedContinent;
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(Breadcrumb))] private CountryOption? _pickedCountry;
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Breadcrumb))]
    [NotifyPropertyChangedFor(nameof(SelectedLeagueDisplay))]
    [NotifyCanExecuteChangedFor(nameof(StartCareerCommand))]
    private CatalogLeague? _selectedLeague;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasTeamPreview))]
    [NotifyPropertyChangedFor(nameof(Breadcrumb))]
    [NotifyPropertyChangedFor(nameof(ManagerBlurb))]
    [NotifyCanExecuteChangedFor(nameof(StartCareerCommand))]
    [NotifyCanExecuteChangedFor(nameof(ConfirmTeamCommand))]
    private CareerTeamOption? _selectedTeam;

    public bool HasTeamPreview => SelectedTeam is not null;
    public string SelectedLeagueDisplay => SelectedLeague is null ? "" : LeagueOption.CleanDisplay(SelectedLeague.Display);
    public string ManagerBlurb => SelectedTeam is null
        ? "The press and the board will use this name."
        : $"The press and the board at {SelectedTeam.Name} will use this name.";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Busy))]
    [NotifyCanExecuteChangedFor(nameof(BackCommand))]
    [NotifyCanExecuteChangedFor(nameof(ConfirmTeamCommand))]
    [NotifyCanExecuteChangedFor(nameof(StartCareerCommand))]
    private bool _isBuilding;

    [ObservableProperty]
    private string _status = "🌍 Pick a continent to begin.";

    // Manager identity (stage 5). Name lands in the career as meta "manager_name" — the key
    // Session.ManagerName reads; nationality as "manager_nat".
    [ObservableProperty] private string _managerNameInput = "The Gaffer";
    [ObservableProperty] private string _managerNationality = "";

    // Build failure, in plain words + the raw tail behind a "Details" fold.
    [ObservableProperty] [NotifyPropertyChangedFor(nameof(HasBuildError))] private string _buildError = "";
    [ObservableProperty] private string _buildErrorDetail = "";
    public bool HasBuildError => BuildError.Length > 0;

    public bool Busy => IsBuilding;

    public string Breadcrumb
    {
        get
        {
            var parts = new List<string> { "World" };
            if (PickedContinent is not null) parts.Add(PickedContinent.Name);
            if (PickedCountry is not null) parts.Add(PickedCountry.Name);
            if (SelectedLeague is not null) parts.Add(SelectedLeagueDisplay);
            if (Stage == CareerStage.Manager && SelectedTeam is not null) parts.Add(SelectedTeam.Name);
            return string.Join("  ›  ", parts);
        }
    }

    /// <summary>Raised with the loaded Session when a career has been built and is ready to open.</summary>
    public event Action<Session>? CareerStarted;

    [RelayCommand]
    private void PickContinent(ContinentOption? c)
    {
        if (c is null || IsBuilding) return;
        PickedContinent = c;
        PickedCountry = null;      // reset the deeper trail — stale picks made
        SelectedLeague = null;     // "World › Asia › England" breadcrumbs
        SelectedTeam = null;
        Countries.Clear();
        foreach (var co in c.Countries.OrderBy(x => x.Name, StringComparer.OrdinalIgnoreCase))
            Countries.Add(new CountryOption(co));
        Stage = CareerStage.Country;
        Status = $"{c.Name} — pick a nation.";
    }

    [RelayCommand]
    private void PickCountry(CountryOption? c)
    {
        if (c is null || IsBuilding) return;
        PickedCountry = c;
        SelectedLeague = null;
        SelectedTeam = null;
        Leagues.Clear();
        foreach (var lg in c.Country.Leagues.OrderBy(l => l.Tier))
            Leagues.Add(new LeagueOption(lg));
        Stage = CareerStage.League;
        Status = $"{c.Name} — pick a league.";
    }

    [RelayCommand]
    private void PickLeague(LeagueOption? lg)
    {
        if (lg is null || IsBuilding) return;
        SelectedLeague = lg.League;
        SelectedTeam = null;
        Teams.Clear();
        foreach (var t in lg.League.Teams.OrderBy(t => t.Name, StringComparer.OrdinalIgnoreCase))
            Teams.Add(new CareerTeamOption(t, _squadOf.TryGetValue(t.RfsId, out var n) ? n : 0));
        Stage = CareerStage.Team;
        Status = $"{lg.Display} — click a club to preview it.";
    }

    [RelayCommand]
    private void PickTeam(CareerTeamOption? t)
    {
        if (IsBuilding) return;
        SelectedTeam = t;
    }

    private bool CanConfirmTeam() => SelectedTeam is not null && !IsBuilding;

    [RelayCommand(CanExecute = nameof(CanConfirmTeam))]
    private void ConfirmTeam()
    {
        if (SelectedTeam is null || IsBuilding) return;
        Stage = CareerStage.Manager;
        Status = $"{SelectedTeam.Name} — name the new manager.";
    }

    [RelayCommand(CanExecute = nameof(CanBack))]
    private void Back()
    {
        if (IsBuilding) return;
        switch (Stage)
        {
            case CareerStage.Manager:
                Stage = CareerStage.Team;
                break;
            case CareerStage.Team:
                SelectedTeam = null; SelectedLeague = null;
                Stage = CareerStage.League;
                break;
            case CareerStage.League:
                PickedCountry = null;
                Stage = CareerStage.Country;
                break;
            case CareerStage.Country:
                PickedContinent = null;
                Stage = CareerStage.Continent;
                break;
        }
    }

    private bool CanBack() => CanGoBack && !IsBuilding;

    private bool CanStart() => SelectedTeam is not null && SelectedLeague is not null && !IsBuilding;

    [RelayCommand(CanExecute = nameof(CanStart))]
    private async Task StartCareer()
    {
        if (SelectedTeam is null || SelectedLeague is null || IsBuilding) return;
        BuildError = "";
        BuildErrorDetail = "";
        IsBuilding = true;
        var club = SelectedTeam.Name;
        var rfsId = SelectedTeam.RfsId;
        var compId = SelectedLeague.CompId;
        var tail = new List<string>();
        void Log(string line)
        {
            lock (tail)
            {
                tail.Add(line);
                if (tail.Count > 40) tail.RemoveAt(0);
            }
            Dispatcher.UIThread.Post(() => Status = line);
        }
        try
        {
            var session = await CareerBuilder.BuildAsync(compId, rfsId, club, Log);
            if (session is null)
            {
                BuildError = $"Couldn't build the {club} career. Nothing was changed — it is safe to try again.";
                lock (tail)
                    BuildErrorDetail = string.Join(Environment.NewLine, tail.TakeLast(14));
                Status = "The build stopped before it finished.";
                return;
            }
            var name = string.IsNullOrWhiteSpace(ManagerNameInput) ? "The Gaffer" : ManagerNameInput.Trim();
            session.ManagerName = name;                               // meta key "manager_name"
            if (!string.IsNullOrWhiteSpace(ManagerNationality))
                session.SetSetting("manager_nat", ManagerNationality.Trim());
            CareerStarted?.Invoke(session);
        }
        finally
        {
            IsBuilding = false;
        }
    }

    // ------------------------------------------------------------------ catalog side-channel
    // CatalogData's typed model doesn't carry "continent" (the geo-fix key) or "squad", so read
    // just those two straight from build/catalog.json. Best-effort: any failure means no
    // overrides and unknown squad sizes, never a crash.
    private static (Dictionary<string, string> ContinentOverride, Dictionary<int, int> SquadOf) ReadCatalogExtras()
    {
        var continents = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var squads = new Dictionary<int, int>();
        try
        {
            var path = FindCatalog();
            if (path is null) return (continents, squads);
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty("countries", out var countries)) return (continents, squads);
            foreach (var co in countries.EnumerateArray())
            {
                var name = co.TryGetProperty("name", out var n) ? n.GetString() : null;
                if (string.IsNullOrEmpty(name)) continue;
                if (co.TryGetProperty("continent", out var cont) && cont.ValueKind == JsonValueKind.String
                    && cont.GetString() is { Length: > 0 } cn)
                    continents[name] = cn;
                if (!co.TryGetProperty("leagues", out var lgs) || lgs.ValueKind != JsonValueKind.Array) continue;
                foreach (var lg in lgs.EnumerateArray())
                {
                    if (!lg.TryGetProperty("teams", out var teams) || teams.ValueKind != JsonValueKind.Array) continue;
                    foreach (var t in teams.EnumerateArray())
                        if (t.TryGetProperty("team_id", out var tid) && tid.TryGetInt32(out var id)
                            && t.TryGetProperty("squad", out var sq) && sq.TryGetInt32(out var count))
                            squads[id] = count;
                }
            }
        }
        catch { /* catalog extras are cosmetic; the picker works without them */ }
        return (continents, squads);
    }

    private static string? FindCatalog()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "build", "catalog.json");
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }
        return null;
    }
}
