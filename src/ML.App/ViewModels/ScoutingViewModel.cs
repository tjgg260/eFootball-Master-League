using System.Collections.ObjectModel;
using Avalonia.Controls;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace ML.App.ViewModels;

public sealed record ScoutTargetClub(int TeamId, string Name, Avalonia.Media.Imaging.Bitmap? Crest);

/// <summary>A name the typed search matched — the pick list row you click to dispatch the scout.</summary>
public sealed record PlayerMatch(long Id, string Name, string Club, int Age)
{
    public string Line => $"{Name}  ·  {Club}  ·  {(Age > 0 ? $"{Age}" : "—")}";
}

/// <summary>
/// A finished dossier. It keeps the job's subject (TargetId + Kind), not just the prose: the
/// card is a live handle on that player or club, so the shared right-click menu works on it.
/// </summary>
public sealed record ScoutReportRow(string Title, string Body,
    Avalonia.Media.Imaging.Bitmap? Crest = null, Avalonia.Media.Imaging.Bitmap? Face = null,
    long TargetId = 0, string Kind = "player")
{
    public bool HasCrest => Crest is not null;
    public bool HasFace => Face is not null;
}

/// <summary>Scouting missions + finished dossiers (FM phase A2).</summary>
public sealed partial class ScoutingViewModel : PageViewModel, IFocusTarget
{
    private readonly Session _s;

    public ScoutingViewModel(Session s)
    {
        _s = s;
        foreach (var t in s.LeagueTeams().Where(t => t.Id != s.CurrentTeamId).OrderBy(t => t.Name))
        {
            Clubs.Add(new ScoutTargetClub(t.Id, t.Name, Visuals.LoadBitmap(s.TeamLogoPath(t.Id))));
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
        NoScout = scout is null;
        ScoutLine = scout is null
            ? "No scout on the books —"
            : $"Scout: {scout.Name} {new string('★', scout.Quality)}";
        var active = _s.ActiveScoutJob();
        // "The scout is available" only means anything when there IS one. With the desk vacant
        // this line sat directly beside "No scout on the books —" and flatly contradicted it.
        MissionLine = scout is null ? ""
            : active is null ? "The scout is available."
            : $"On a mission — report ready at MD{active.ReadyMd}.";
        // The engine refuses a mission with no scout and says why; a button you can press only
        // to be told no is worse than one that says no before you press it.
        SendTip = scout is null
            ? "You have no scout — hire one on the Staff screen first."
            : active is not null ? $"He is already out — his report lands at MD{active.ReadyMd}."
            : "";
        CanSend = scout is not null && active is null;

        Reports.Clear();
        foreach (var job in _s.CompletedScoutJobs())
        {
            try
            {
                Reports.Add(job.Kind == "club"
                    ? new ScoutReportRow($"Club: {_s.TeamName((int)job.TargetId)}", _s.ClubScoutReport((int)job.TargetId),
                        Crest: Visuals.LoadBitmap(_s.TeamLogoPath((int)job.TargetId)),
                        TargetId: job.TargetId, Kind: "club")
                    : new ScoutReportRow($"Player: {PlayerName(job.TargetId)}", _s.PlayerScoutReport(job.TargetId),
                        Face: FaceFor(job.TargetId),
                        TargetId: job.TargetId, Kind: "player"));
            }
            catch { /* target may have left the world */ }
        }
        Empty = Reports.Count == 0;
    }

    /// <summary>The dossier's face: the player's portrait where one resolves, nothing where not.</summary>
    private Avalonia.Media.Imaging.Bitmap? FaceFor(long playerId)
    {
        try { return _s.PortraitFor(playerId).Image; }
        catch { return null; }
    }

    /// <summary>Dossier title lookup — the card header names the player, not "Player report".</summary>
    private string PlayerName(long playerId)
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
    /// <summary>The typed search's shortlist of candidates — click one to send the scout.</summary>
    public ObservableCollection<PlayerMatch> Matches { get; } = new();
    public bool HasMatches => Matches.Count > 0;

    [ObservableProperty] private ScoutTargetClub? _selectedClub;
    [ObservableProperty] private PlayerMatch? _selectedMatch;
    [ObservableProperty] private string _playerSearch = "";
    [ObservableProperty] private string _scoutLine = "";
    [ObservableProperty] private string _missionLine = "";
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private bool _empty;
    /// <summary>Can a mission be sent at all? False with no scout, or one already out.</summary>
    [ObservableProperty] private bool _canSend;

    /// <summary>Why the send buttons are off, when they are.</summary>
    [ObservableProperty] private string _sendTip = "";

    /// <summary>No scout on the books — the line ends in a link to the Staff screen.</summary>
    [ObservableProperty] private bool _noScout;

    [RelayCommand]
    private void OpenStaff() => Nav.Go("Staff");

    [RelayCommand]
    private void ScoutClub()
    {
        if (SelectedClub is null) { Status = "Pick a club."; return; }
        Status = _s.StartScoutJob("club", SelectedClub.TeamId, SelectedClub.Name);
        Refresh();
    }

    /// <summary>
    /// Typed search. One match goes straight out; several put up a pick list, because
    /// "highest-rated LIKE match" silently sent the scout to the wrong Silva often enough.
    /// </summary>
    [RelayCommand]
    private void ScoutPlayer()
    {
        if (string.IsNullOrWhiteSpace(PlayerSearch)) { Status = "Type a player name."; return; }
        var matches = FindPlayers(PlayerSearch);
        if (matches.Count == 0)
        {
            ClearMatches();
            Status = $"No player matching '{PlayerSearch}'.";
            return;
        }
        if (matches.Count == 1)
        {
            ClearMatches();
            Dispatch(matches[0]);
            return;
        }
        SetMatches(matches);
        Status = $"{matches.Count} players match '{PlayerSearch.Trim()}' — pick the one you meant.";
    }

    /// <summary>Clicking a row in the pick list IS the dispatch. Emptying the list is posted:
    /// the ListBox is mid-selection-change here and must not have its items pulled out from
    /// under it.</summary>
    partial void OnSelectedMatchChanged(PlayerMatch? value)
    {
        if (value is null) return;
        var pick = value;
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            ClearMatches();
            Dispatch(pick);
        });
    }

    private void Dispatch(PlayerMatch p)
    {
        Status = _s.StartScoutJob("player", p.Id, p.Name);
        Refresh();
    }

    /// <summary>Up to eight candidates, best-rated first — name, club and age to tell them apart.</summary>
    private List<PlayerMatch> FindPlayers(string term)
    {
        var found = new List<PlayerMatch>();
        try
        {
            using var cmd = _s.Db.Connection.CreateCommand();
            cmd.CommandText =
                "SELECT p.id, p.name, COALESCE(p.age,0), " +
                "(SELECT t.name FROM squad_members sm JOIN teams t ON t.id=sm.team_id " +
                " WHERE sm.player_id=p.id LIMIT 1) " +
                "FROM players p WHERE p.name LIKE $q " +
                "ORDER BY COALESCE(p.overall_rating,0) DESC LIMIT 8";
            cmd.Parameters.AddWithValue("$q", $"%{term.Trim()}%");
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                // Ids run past Int32 in the curated/generated bands — GetInt64 or the search
                // throws on exactly the players you most want to scout.
                found.Add(new PlayerMatch(r.GetInt64(0), r.GetString(1),
                    r.IsDBNull(3) ? "Free agent" : r.GetString(3), r.GetInt32(2)));
            }
        }
        catch { /* a bad search must never take the screen down */ }
        return found;
    }

    private void SetMatches(IEnumerable<PlayerMatch> matches)
    {
        Matches.Clear();
        foreach (var m in matches) Matches.Add(m);
        OnPropertyChanged(nameof(HasMatches));
    }

    private void ClearMatches()
    {
        Matches.Clear();
#pragma warning disable MVVMTK0034   // deliberate: notification is raised by hand on the next line
        _selectedMatch = null;              // no re-entry through OnSelectedMatchChanged
#pragma warning restore MVVMTK0034
        OnPropertyChanged(nameof(SelectedMatch));
        OnPropertyChanged(nameof(HasMatches));
    }

    /// <summary>
    /// The dossier card's right-click: a player report opens the shared player menu, a club
    /// report the club menu. Older dossiers (before the subject was kept) carry no id.
    /// </summary>
    public ContextMenu? MenuFor(ScoutReportRow row)
    {
        if (row.TargetId <= 0) return null;
        var target = row.Kind == "club"
            ? EntityRef.Club(row.TargetId, _s.TeamName((int)row.TargetId))
            : EntityRef.Player(row.TargetId, PlayerName(row.TargetId));
        return EntityActions.BuildMenu(_s, target, status: t => Status = t, refresh: Refresh);
    }

    /// <summary>
    /// Focused arrival (Nav.Go("Scouting", …)). A player fills the search box and puts his
    /// namesakes up as a pick list — dispatching is still YOUR click, never a side effect of
    /// navigating. A club is selected in the picker, added to it if it isn't a league rival.
    /// </summary>
    public void Focus(EntityRef target)
    {
        try
        {
            if (target.Kind == EntityKind.Club)
            {
                var tid = (int)target.Id;
                var option = Clubs.FirstOrDefault(c => c.TeamId == tid);
                if (option is null)
                {
                    var label = target.Name.Length > 0 ? target.Name : _s.TeamName(tid);
                    option = new ScoutTargetClub(tid, label, Visuals.LoadBitmap(_s.TeamLogoPath(tid)));
                    // StartScoutJob takes any team id, so a club from another division belongs
                    // in the picker rather than being silently unscoutable. Keep it in order.
                    var ix = 0;
                    while (ix < Clubs.Count && string.Compare(Clubs[ix].Name, label,
                               StringComparison.OrdinalIgnoreCase) < 0) ix++;
                    Clubs.Insert(ix, option);
                }
                SelectedClub = option;
                Status = $"{option.Name} is ready to scout.";
                return;
            }
            if (target.Kind != EntityKind.Player) return;

            var name = target.Name.Length > 0 ? target.Name : _s.PlayerNameOf(target.Id);
            PlayerSearch = name;
            var matches = FindPlayers(name);
            SetMatches(matches);
            Status = matches.Count == 0
                ? $"No player matching '{name}'."
                : matches.Count == 1
                    ? $"{matches[0].Name} — click him to send the scout."
                    : $"{matches.Count} players match '{name}' — pick the one you meant.";
        }
        catch { /* focused navigation must never take the screen down */ }
    }
}
