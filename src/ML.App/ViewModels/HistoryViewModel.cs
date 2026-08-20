using System.Collections.ObjectModel;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;

namespace ML.App.ViewModels;

// --- History (D3: the season archive + the club record book) ----------------------

public sealed record ArchiveTableRow(
    int Pos, string Team, int P, int W, int D, int L, int GD, int Pts,
    IBrush TeamBrush, FontWeight TeamWeight);

public sealed record ArchiveScorerRow(string Player, string Team, int Goals);

public sealed record ArchiveHonourRow(string Competition, string Team);

public sealed partial class HistoryViewModel : PageViewModel
{
    private readonly Session _s;

    public HistoryViewModel(Session s)
    {
        _s = s;
        foreach (var season in s.ArchiveSeasons())
        {
            SeasonChoices.Add($"{2026 + (season - 9000)}/{(2027 + (season - 9000)) % 100:00}");
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
            Fill(TopTable, season, 9000);
            Fill(SecondTable, season, 9001);
            TopTableName = TopTable.Count > 0 ? _s.ArchiveLeagueName(9000) : "";
            SecondTableName = SecondTable.Count > 0 ? _s.ArchiveLeagueName(9001) : "";
            foreach (var (comp, team) in _s.HonoursIn(season))
            {
                SeasonHonours.Add(new ArchiveHonourRow(comp, team));
            }
            foreach (var (player, team, goals) in _s.LeadersIn(season, "goal"))
            {
                SeasonScorers.Add(new ArchiveScorerRow(player, team, goals));
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
        foreach (var r in _s.TableForSeason(season, leagueId))
        {
            var mine = r.TeamId.Value == _s.CurrentTeamId;
            into.Add(new ArchiveTableRow(
                r.Position, _s.TeamName(r.TeamId.Value), r.Played, r.Won, r.Drawn, r.Lost,
                r.GoalDifference, r.Points,
                mine ? Visuals.Brush("#9FE6B4") : Visuals.Brush("#C7CEDA"),
                mine ? FontWeight.Bold : FontWeight.Normal));
        }
    }
}
