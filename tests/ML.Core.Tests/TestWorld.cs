using ML.Core;
using ML.Core.Domain;

namespace ML.Core.Tests;

public sealed record TestLeagueSpec(
    string Name,
    int Tier,
    int Teams,
    int PromotionPlaces = 0,
    int RelegationPlaces = 0);

/// <summary>
/// Synthetic worlds for the engine tests. ML.Core has no I/O by design, so nothing here needs
/// the game installed or a CSV export — that is the whole point of keeping the engine pure.
/// </summary>
public static class TestWorld
{
    public static World SingleLeague(int teams = 20, int squadSize = 22, int seed = 1) =>
        Build(new[] { new TestLeagueSpec("Premier Division", Tier: 1, Teams: teams) }, squadSize, seed);

    /// <summary>Two divisions with three up and three down — the shape the milestone test uses.</summary>
    public static World TwoTierPyramid(int teamsPerLeague = 20, int squadSize = 22, int seed = 20260818) =>
        Build(
            new[]
            {
                new TestLeagueSpec("Premier Division", Tier: 1, Teams: teamsPerLeague, RelegationPlaces: 3),
                new TestLeagueSpec("Championship", Tier: 2, Teams: teamsPerLeague, PromotionPlaces: 3),
            },
            squadSize,
            seed);

    public static World Build(IReadOnlyList<TestLeagueSpec> specs, int squadSize, int seed)
    {
        var random = new SeededRandom(seed);
        var world = new World();

        var nextTeamId = 1;
        var nextPlayerId = 1;
        var nextLeagueId = 1;

        foreach (var spec in specs)
        {
            // Sequential rather than keyed on tier, so a world can hold two divisions at the
            // same level for the tests that check those are rejected.
            var leagueId = new LeagueId(nextLeagueId++);
            world.AddLeague(new League(
                leagueId, spec.Name, spec.Tier, spec.PromotionPlaces, spec.RelegationPlaces));

            for (var t = 0; t < spec.Teams; t++)
            {
                var teamId = new TeamId(nextTeamId++);

                // Weaker clubs the further down the pyramid, plus spread inside each division,
                // so the table has something to sort and promotion actually means something.
                var tierPenalty = (spec.Tier - 1) * 8;
                var baseRating = 78 - tierPenalty - random.Next(14);
                var budget = 20_000_000L + (random.Next(80) * 1_000_000L);

                world.AddTeam(new Team(teamId, $"{spec.Name} Club {t + 1}", leagueId, budget));

                foreach (var position in SquadPositions(squadSize))
                {
                    var rating = Math.Clamp(
                        baseRating + random.Next(13) - 6, Player.MinRating, Player.MaxRating);

                    var player = new Player(
                        new PlayerId(nextPlayerId++),
                        $"Player {nextPlayerId - 1}",
                        position,
                        age: 17 + random.Next(19),
                        overallRating: rating,
                        weeklyWage: (rating - 39) * 250,
                        contractExpiresSeason: 1 + random.Next(4));

                    world.AddPlayer(player);
                    world.AssignPlayer(
                        player.Id,
                        teamId,
                        world.NextFreeSquadNumber(teamId)
                            ?? throw new InvalidOperationException("Ran out of shirt numbers."));
                }
            }
        }

        return world;
    }

    private static IEnumerable<Position> SquadPositions(int squadSize)
    {
        var keepers = Math.Max(3, squadSize / 8);
        var outfield = squadSize - keepers;
        var defenders = outfield * 35 / 100;
        var midfielders = outfield * 40 / 100;
        var forwards = outfield - defenders - midfielders;

        for (var i = 0; i < keepers; i++)
        {
            yield return Position.GK;
        }

        var defenderRoles = new[] { Position.CB, Position.CB, Position.LB, Position.RB };
        for (var i = 0; i < defenders; i++)
        {
            yield return defenderRoles[i % defenderRoles.Length];
        }

        var midfieldRoles = new[] { Position.DMF, Position.CMF, Position.CMF, Position.AMF, Position.LMF, Position.RMF };
        for (var i = 0; i < midfielders; i++)
        {
            yield return midfieldRoles[i % midfieldRoles.Length];
        }

        var forwardRoles = new[] { Position.CF, Position.SS, Position.LWF, Position.RWF };
        for (var i = 0; i < forwards; i++)
        {
            yield return forwardRoles[i % forwardRoles.Length];
        }
    }

    public static IReadOnlyList<TeamId> TeamIdsIn(World world, int tier) =>
        world.TeamsIn(new LeagueId(tier)).Select(t => t.Id).ToList();
}
