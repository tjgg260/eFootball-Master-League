using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public sealed record ScoutTargetClub(int TeamId, string Name);

public sealed record ScoutReportRow(string Title, string Body);

/// <summary>Scouting missions + finished dossiers (FM phase A2).</summary>
public sealed partial class ScoutingViewModel : PageViewModel
{
    private readonly Session _s;

    public ScoutingViewModel(Session s)
    {
        _s = s;
        foreach (var t in s.LeagueTeams().Where(t => t.Id != s.CurrentTeamId).OrderBy(t => t.Name))
        {
            Clubs.Add(new ScoutTargetClub(t.Id, t.Name));
        }
        // Default the club picker to your next opponent — the report you usually want.
        var next = s.NextFixture();
        if (next is not null)
        {
            var oppId = next.HomeTeamId == s.CurrentTeamId ? next.AwayTeamId : next.HomeTeamId;
            SelectedClub = Clubs.FirstOrDefault(c => c.TeamId == oppId) ?? Clubs.FirstOrDefault();
        }
        Refresh();
    }

    private void Refresh()
    {
        var scout = _s.StaffFor("Scout");
        ScoutLine = scout is null
            ? "No scout on the books — hire one on the Staff screen."
            : $"Scout: {scout.Name} {new string('★', scout.Quality)}";
        var active = _s.ActiveScoutJob();
        MissionLine = active is null
            ? "The scout is available."
            : $"On a mission — report ready at MD{active.ReadyMd}.";

        Reports.Clear();
        foreach (var job in _s.CompletedScoutJobs())
        {
            try
            {
                Reports.Add(job.Kind == "club"
                    ? new ScoutReportRow($"Club: {_s.TeamName(job.TargetId)}", _s.ClubScoutReport(job.TargetId))
                    : new ScoutReportRow($"Player: {PlayerName(job.TargetId)}", _s.PlayerScoutReport(job.TargetId)));
            }
            catch { /* target may have left the world */ }
        }
        Empty = Reports.Count == 0;
    }

    /// <summary>Dossier title lookup — the card header names the player, not "Player report".</summary>
    private string PlayerName(int playerId)
    {
        using var cmd = _s.Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT name FROM players WHERE id=$p";
        cmd.Parameters.AddWithValue("$p", playerId);
        return cmd.ExecuteScalar() as string ?? "Unknown player";
    }

    public override string Title => "Scouting";
    public override string Icon => "🔍";

    public ObservableCollection<ScoutTargetClub> Clubs { get; } = new();
    public ObservableCollection<ScoutReportRow> Reports { get; } = new();

    [ObservableProperty] private ScoutTargetClub? _selectedClub;
    [ObservableProperty] private string _playerSearch = "";
    [ObservableProperty] private string _scoutLine = "";
    [ObservableProperty] private string _missionLine = "";
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private bool _empty;

    [RelayCommand]
    private void ScoutClub()
    {
        if (SelectedClub is null) { Status = "Pick a club."; return; }
        Status = _s.StartScoutJob("club", SelectedClub.TeamId, SelectedClub.Name);
        Refresh();
    }

    [RelayCommand]
    private void ScoutPlayer()
    {
        if (string.IsNullOrWhiteSpace(PlayerSearch)) { Status = "Type a player name."; return; }
        using var cmd = _s.Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT id, name FROM players WHERE name LIKE $q " +
                          "ORDER BY overall_rating DESC LIMIT 1";
        cmd.Parameters.AddWithValue("$q", $"%{PlayerSearch.Trim()}%");
        using var r = cmd.ExecuteReader();
        if (!r.Read()) { Status = $"No player matching '{PlayerSearch}'."; return; }
        Status = _s.StartScoutJob("player", r.GetInt32(0), r.GetString(1));
        Refresh();
    }
}
