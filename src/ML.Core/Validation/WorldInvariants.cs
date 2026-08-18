using ML.Core.Domain;

namespace ML.Core.Validation;

/// <summary>
/// Everything that must be true of the world at rest. The engine's tests assert this after
/// every season, and Phase 4 runs it before emitting a CSV — the plan's "validate before
/// emitting, fail loudly" rule. A corrupt Player.bin costs an evening; this costs nothing.
/// </summary>
public static class WorldInvariants
{
    public static IReadOnlyList<string> Check(World world, SquadRules? rules = null)
    {
        ArgumentNullException.ThrowIfNull(world);
        rules ??= SquadRules.Default;

        var violations = new List<string>();

        foreach (var team in world.Teams)
        {
            if (!world.HasLeague(team.LeagueId))
            {
                violations.Add($"{team.Name} is in league {team.LeagueId}, which does not exist.");
            }

            if (team.Budget < 0)
            {
                violations.Add($"{team.Name} has a negative budget ({team.Budget:N0}).");
            }

            CheckSquad(world, team, rules, violations);
        }

        foreach (var player in world.Players)
        {
            CheckPlayer(world, player, violations);
        }

        return violations;
    }

    public static void AssertValid(World world, SquadRules? rules = null)
    {
        var violations = Check(world, rules);
        if (violations.Count > 0)
        {
            throw new WorldInvariantException(violations);
        }
    }

    private static void CheckSquad(World world, Team team, SquadRules rules, List<string> violations)
    {
        var squad = world.SquadOf(team.Id);

        if (squad.Count < rules.MinSquadSize)
        {
            violations.Add(
                $"{team.Name} has {squad.Count} players, below the minimum of {rules.MinSquadSize}.");
        }

        if (squad.Count > rules.MaxSquadSize)
        {
            violations.Add(
                $"{team.Name} has {squad.Count} players, above the maximum of {rules.MaxSquadSize}.");
        }

        var keepers = squad.Count(p => p.Position.IsGoalkeeper());
        if (keepers < rules.MinGoalkeepers)
        {
            violations.Add(
                $"{team.Name} has {keepers} goalkeeper(s), below the minimum of {rules.MinGoalkeepers}.");
        }

        var duplicates = squad
            .Where(p => p.SquadNumber.HasValue)
            .GroupBy(p => p.SquadNumber!.Value)
            .Where(g => g.Count() > 1);

        foreach (var duplicate in duplicates)
        {
            var names = string.Join(", ", duplicate.Select(p => p.Name));
            violations.Add($"{team.Name} has shirt {duplicate.Key} on more than one player: {names}.");
        }

        foreach (var player in squad.Where(p => p.SquadNumber is { } n
                     && (n < rules.MinSquadNumber || n > rules.MaxSquadNumber)))
        {
            violations.Add(
                $"{player.Name} at {team.Name} wears {player.SquadNumber}, outside " +
                $"{rules.MinSquadNumber}-{rules.MaxSquadNumber}.");
        }
    }

    private static void CheckPlayer(World world, Player player, List<string> violations)
    {
        if (player.TeamId is { } teamId)
        {
            if (!world.HasTeam(teamId))
            {
                violations.Add($"{player.Name} belongs to team {teamId}, which does not exist.");
            }
            else if (!world.SquadOf(teamId).Contains(player))
            {
                violations.Add(
                    $"{player.Name} thinks they are at {world.GetTeam(teamId).Name} " +
                    "but are missing from its squad.");
            }

            if (player.SquadNumber is null)
            {
                violations.Add($"{player.Name} is at a club but has no squad number.");
            }
        }
        else if (player.SquadNumber is not null)
        {
            violations.Add($"{player.Name} is a free agent but still holds shirt {player.SquadNumber}.");
        }
    }
}

public sealed class WorldInvariantException : InvalidOperationException
{
    public WorldInvariantException(IReadOnlyList<string> violations)
        : base($"World is invalid ({violations.Count} violation(s)):{Environment.NewLine}" +
               string.Join(Environment.NewLine, violations.Select(v => "  - " + v)))
    {
        Violations = violations;
    }

    public IReadOnlyList<string> Violations { get; }
}
