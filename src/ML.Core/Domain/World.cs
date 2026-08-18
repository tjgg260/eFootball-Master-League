namespace ML.Core.Domain;

/// <summary>
/// The in-memory aggregate the engine works against: every league, club and player, plus the
/// squad index. All club membership changes go through here so <see cref="Player.TeamId"/> and
/// the squad index cannot drift apart.
/// </summary>
public sealed class World
{
    private readonly Dictionary<PlayerId, Player> _players = new();
    private readonly Dictionary<TeamId, Team> _teams = new();
    private readonly Dictionary<LeagueId, League> _leagues = new();
    private readonly Dictionary<TeamId, List<Player>> _squads = new();
    private readonly HashSet<PlayerId> _freeAgents = new();

    public IReadOnlyCollection<Player> Players => _players.Values;

    public IReadOnlyCollection<Team> Teams => _teams.Values;

    public IReadOnlyCollection<League> Leagues => _leagues.Values;

    public IReadOnlyList<Player> FreeAgents =>
        _freeAgents.Select(id => _players[id]).ToList();

    public void AddLeague(League league)
    {
        if (!_leagues.TryAdd(league.Id, league))
        {
            throw new InvalidOperationException($"League {league.Id} is already in the world.");
        }
    }

    public void AddTeam(Team team)
    {
        if (!_leagues.ContainsKey(team.LeagueId))
        {
            throw new InvalidOperationException(
                $"Cannot add {team.Name}: league {team.LeagueId} does not exist.");
        }

        if (!_teams.TryAdd(team.Id, team))
        {
            throw new InvalidOperationException($"Team {team.Id} is already in the world.");
        }

        _squads[team.Id] = new List<Player>();
    }

    /// <summary>Adds a player as a free agent. Use <see cref="AssignPlayer"/> to place them.</summary>
    public void AddPlayer(Player player)
    {
        if (!_players.TryAdd(player.Id, player))
        {
            throw new InvalidOperationException($"Player {player.Id} is already in the world.");
        }

        _freeAgents.Add(player.Id);
    }

    public void AssignPlayer(PlayerId playerId, TeamId teamId, int squadNumber)
    {
        var player = GetPlayer(playerId);
        var squad = SquadList(teamId);

        var clash = squad.FirstOrDefault(p => p.SquadNumber == squadNumber && p.Id != playerId);
        if (clash is not null)
        {
            throw new InvalidOperationException(
                $"Squad number {squadNumber} at {GetTeam(teamId).Name} is already taken by {clash.Name}.");
        }

        DetachFromCurrentClub(player);

        player.AssignTo(teamId, squadNumber);
        squad.Add(player);
        _freeAgents.Remove(playerId);
    }

    public void ReleasePlayer(PlayerId playerId)
    {
        var player = GetPlayer(playerId);
        DetachFromCurrentClub(player);
        player.Release();
        _freeAgents.Add(playerId);
    }

    private void DetachFromCurrentClub(Player player)
    {
        if (player.TeamId is { } currentTeam && _squads.TryGetValue(currentTeam, out var currentSquad))
        {
            currentSquad.Remove(player);
        }
    }

    public IReadOnlyList<Player> SquadOf(TeamId teamId) => SquadList(teamId);

    public IReadOnlyList<Team> TeamsIn(LeagueId leagueId) =>
        _teams.Values.Where(t => t.LeagueId == leagueId).OrderBy(t => t.Id.Value).ToList();

    public IReadOnlyList<League> LeaguesByTier() =>
        _leagues.Values.OrderBy(l => l.Tier).ToList();

    public Player GetPlayer(PlayerId id) =>
        _players.TryGetValue(id, out var player)
            ? player
            : throw new KeyNotFoundException($"No player with id {id}.");

    public Team GetTeam(TeamId id) =>
        _teams.TryGetValue(id, out var team)
            ? team
            : throw new KeyNotFoundException($"No team with id {id}.");

    public League GetLeague(LeagueId id) =>
        _leagues.TryGetValue(id, out var league)
            ? league
            : throw new KeyNotFoundException($"No league with id {id}.");

    public bool HasTeam(TeamId id) => _teams.ContainsKey(id);

    public bool HasLeague(LeagueId id) => _leagues.ContainsKey(id);

    /// <summary>Lowest unused shirt number at the club, or null if all 99 are taken.</summary>
    public int? NextFreeSquadNumber(TeamId teamId)
    {
        var taken = SquadList(teamId)
            .Select(p => p.SquadNumber)
            .Where(n => n.HasValue)
            .Select(n => n!.Value)
            .ToHashSet();

        for (var n = 1; n <= 99; n++)
        {
            if (!taken.Contains(n))
            {
                return n;
            }
        }

        return null;
    }

    public long WageBillOf(TeamId teamId) => SquadList(teamId).Sum(p => (long)p.AnnualWage);

    private List<Player> SquadList(TeamId teamId) =>
        _squads.TryGetValue(teamId, out var squad)
            ? squad
            : throw new KeyNotFoundException($"No team with id {teamId}.");
}
