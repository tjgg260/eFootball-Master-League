using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using ML.Data;

namespace ML.App.ViewModels;

// --- History (D3: the season archive + the club record book) ----------------------
//
// The archive is not a photograph: the clubs and players in it are still in the world, so
// every row keeps the id of its subject and answers the same right-click as anywhere else.

public sealed record ArchiveTableRow(
    int Pos, string Team, int P, int W, int D, int L, int GD, int Pts,
    IBrush TeamBrush, FontWeight TeamWeight, Avalonia.Media.Imaging.Bitmap? Crest = null,
    string Trophy = "", int TeamId = 0);

public sealed record ArchiveScorerRow(string Player, string Team, int Goals, long PlayerId = 0);

/// <summary>An archived honour. Most were lifted by a club; Player of the Season was won by
/// a player, so the row says which before a menu offers to open a squad.</summary>
public sealed record ArchiveHonourRow(string Competition, string Team,
    Avalonia.Media.Imaging.Bitmap? Crest = null, int HolderId = 0, bool HolderIsPlayer = false);

public sealed partial class HistoryViewModel : PageViewModel
{
    private readonly Session _s;

    // Divisions resolved from league data by tier (1 = top flight, 2 = second division),
    // not hardwired ids; Session's own TopFlight/Division2 consts are private, so the
    // 9000/9001 fallbacks only cover a DB with no league rows at all.
    private readonly int _topFlightId;
    private readonly int _division2Id;
    private readonly Dictionary<int, LeagueRow> _leaguesById;

    private static readonly IBrush GoldText = Visuals.Brush("#D4AC0D");
    private static readonly IBrush GreenText = Visuals.Brush("#9FE6B4");
    private static readonly IBrush RedText = Visuals.Brush("#D64545");
    private static readonly IBrush BodyText = Visuals.Brush("#C7CEDA");

    public HistoryViewModel(Session s)
    {
        _s = s;
        var leagues = s.Repo.Leagues();
        _leaguesById = leagues.ToDictionary(l => l.Id);
        _topFlightId = leagues.FirstOrDefault(l => l.Tier == 1)?.Id ?? 9000;
        _division2Id = leagues.FirstOrDefault(l => l.Tier == 2)?.Id ?? 9001;

        foreach (var season in s.ArchiveSeasons())
        {
            // Season ids and years march in step, so a past season's year is the current
            // year minus how many seasons back it sits (no 2026/9000 base-year literals).
            var year = s.SeasonYear - (s.SeasonId - season);
            SeasonChoices.Add($"{year}/{(year + 1) % 100:00}");
            _seasonIds.Add(season);
        }
        Records = new ObservableCollection<ClubRecordRow>(s.ClubRecords());
        RecordsNote = Records.Count == 0
            ? "The record book fills as results and transfers go on file."
            : "";
        if (SeasonChoices.Count > 0)
        {
            SelectedSeason = SeasonChoices[0];
        }
        else
        {
            ArchiveNote = "Play a season to open the archive.";
        }
    }

    public override string Title => "History";
    public override string Icon => "📜";

    private readonly List<int> _seasonIds = new();
    public ObservableCollection<string> SeasonChoices { get; } = new();

    [ObservableProperty] private string? _selectedSeason;
    [ObservableProperty] private string _archiveNote = "";
    public ObservableCollection<ArchiveTableRow> TopTable { get; } = new();
    public ObservableCollection<ArchiveTableRow> SecondTable { get; } = new();
    [ObservableProperty] private string _topTableName = "";
    [ObservableProperty] private string _secondTableName = "";
    public bool HasSecondTable => SecondTable.Count > 0;
    public ObservableCollection<ArchiveHonourRow> SeasonHonours { get; } = new();
    public ObservableCollection<ArchiveScorerRow> SeasonScorers { get; } = new();
    public ObservableCollection<ClubRecordRow> Records { get; }
    public string RecordsNote { get; }

    partial void OnSelectedSeasonChanged(string? value)
    {
        var ix = value is null ? -1 : SeasonChoices.IndexOf(value);
        if (ix < 0 || ix >= _seasonIds.Count) return;
        var season = _seasonIds[ix];

        TopTable.Clear();
        SecondTable.Clear();
        SeasonHonours.Clear();
        SeasonScorers.Clear();
        try
        {
            Fill(TopTable, season, _topFlightId);
            Fill(SecondTable, season, _division2Id);
            TopTableName = TopTable.Count > 0 ? _s.ArchiveLeagueName(_topFlightId) : "";
            SecondTableName = SecondTable.Count > 0 ? _s.ArchiveLeagueName(_division2Id) : "";
            foreach (var (comp, holder, holderId, isPlayer) in _s.HonoursInWithHolders(season))
            {
                SeasonHonours.Add(new ArchiveHonourRow(comp, holder,
                    isPlayer ? Face(holderId) : Visuals.LoadBitmap(_s.TeamLogoPath(holderId)),
                    holderId, isPlayer));
            }
            foreach (var (player, team, goals, playerId, _) in _s.LeadersInWithIds(season, "goal"))
            {
                SeasonScorers.Add(new ArchiveScorerRow(player, team, goals, playerId));
            }
        }
        catch { /* a partial archive still renders */ }
        OnPropertyChanged(nameof(HasSecondTable));
        ArchiveNote = SeasonHonours.Count == 0 && season == _seasonIds.FirstOrDefault()
            ? "This season is still in progress — the table shows its current state."
            : "";
    }

    private void Fill(ObservableCollection<ArchiveTableRow> into, int season, int leagueId)
    {
        // Zone sizes come from the same league rows the rollover uses — nothing hardcoded.
        var promo = _leaguesById.TryGetValue(leagueId, out var lg) ? lg.PromotionPlaces : 0;
        var releg = lg?.RelegationPlaces ?? 0;
        var complete = season != _s.SeasonId; // archived seasons are finished; the live one isn't
        var rows = _s.TableForSeason(season, leagueId).ToList();
        foreach (var r in rows)
        {
            var mine = r.TeamId.Value == _s.CurrentTeamId;
            var champion = complete && r.Position == 1;
            var promoted = r.Position <= promo;
            var relegated = releg > 0 && r.Position > rows.Count - releg;
            var brush = champion ? GoldText
                : relegated ? RedText
                : promoted ? GreenText
                : mine ? GreenText
                : BodyText;
            into.Add(new ArchiveTableRow(
                r.Position, _s.TeamName(r.TeamId.Value), r.Played, r.Won, r.Drawn, r.Lost,
                r.GoalDifference, r.Points,
                brush,
                mine ? FontWeight.Bold : FontWeight.Normal,
                Visuals.LoadBitmap(_s.TeamLogoPath(r.TeamId.Value)),
                champion ? "🏆" : "", r.TeamId.Value));
        }
    }

    private Avalonia.Media.Imaging.Bitmap? Face(long playerId)
    {
        try { return _s.PortraitFor(playerId).Image; } catch { return null; }
    }

    // --- shared right-click menus ------------------------------------------------
    // Refreshing means rebuilding the selected season, which is exactly what the season
    // picker already does — so a verb that changes the world redraws the same archive.

    private void Reload() => OnSelectedSeasonChanged(SelectedSeason);

    /// <summary>Verb results land here, verbatim.</summary>
    [ObservableProperty] private string _status = "";

    /// <summary>An archived standings row is still a club today.</summary>
    public ContextMenu? MenuFor(ArchiveTableRow r) =>
        r.TeamId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Club(r.TeamId, r.Team),
                status: t => Status = t, refresh: Reload);

    /// <summary>An archived honour: a club lifted it, or a player won the award.</summary>
    public ContextMenu? MenuFor(ArchiveHonourRow h) =>
        h.HolderId <= 0 ? null
            : EntityActions.BuildMenu(_s,
                h.HolderIsPlayer ? EntityRef.Player(h.HolderId, h.Team) : EntityRef.Club(h.HolderId, h.Team),
                status: t => Status = t, refresh: Reload);

    /// <summary>A past season's top scorer may still be signable — the player menu says so.</summary>
    public ContextMenu? MenuFor(ArchiveScorerRow r) =>
        r.PlayerId <= 0 ? null
            : EntityActions.BuildMenu(_s, EntityRef.Player(r.PlayerId, r.Player),
                status: t => Status = t, refresh: Reload);
}
