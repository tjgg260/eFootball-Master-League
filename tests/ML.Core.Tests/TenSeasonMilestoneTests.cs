using ML.Core;
using ML.Core.Domain;
using ML.Core.Seasons;
using ML.Core.Simulation;
using ML.Core.Tables;
using ML.Core.Validation;

namespace ML.Core.Tests;

/// <summary>
/// The Phase 2 milestone from the build plan: simulate ten full seasons end to end, and after
/// every one of them the table is valid, no budget has gone negative and no player has been
/// orphaned.
/// </summary>
public class TenSeasonMilestoneTests
{
    private const int Seasons = 10;
    private const int TeamsPerLeague = 20;
    private const int MatchdaysPerSeason = (TeamsPerLeague - 1) * 2;

    [Theory]
    [InlineData(1)]
    [InlineData(20260818)]
    [InlineData(int.MaxValue / 3)]
    public void TenSeasonsRunEndToEndAndLeaveTheWorldValid(int seed)
    {
        var world = TestWorld.TwoTierPyramid(teamsPerLeague: TeamsPerLeague, seed: seed);
        var random = new SeededRandom(seed);
        var engine = new SeasonEngine(world, new PoissonMatchSimulator(random));
        var rollover = new SeasonRollover(world, random);

        var champions = new List<TeamId>();

        for (var seasonId = 1; seasonId <= Seasons; seasonId++)
        {
            var seasons = world.LeaguesByTier()
                .Select(league => Season.Create(
                    seasonId,
                    2026 + seasonId,
                    league,
                    world.TeamsIn(league.Id).Select(t => t.Id).ToList(),
                    random))
                .ToList();

            foreach (var season in seasons)
            {
                engine.SimulateEntireSeason(season);

                Assert.Equal(SeasonState.Complete, season.State);
                Assert.True(season.AllFixturesPlayed, $"Season {seasonId} left fixtures unplayed.");

                AssertTableIsValid(LeagueTable.Build(season.Teams, season.Fixtures), seasonId);
            }

            var report = rollover.Apply(seasonId, seasons);
            champions.Add(report.Leagues[0].Champion);

            AssertWorldIsValid(world, seasonId);
        }

        Assert.Equal(Seasons, champions.Count);

        // Ten identical champions would mean the simulation has no variance worth the name.
        Assert.True(
            champions.Distinct().Count() > 1,
            "The same club won the title all ten seasons; the simulation is effectively deterministic.");
    }

    [Fact]
    public void PromotionAndRelegationActuallyMoveClubsAroundOverADecade()
    {
        var world = TestWorld.TwoTierPyramid(teamsPerLeague: TeamsPerLeague, seed: 99);
        var random = new SeededRandom(99);
        var engine = new SeasonEngine(world, new PoissonMatchSimulator(random));
        var rollover = new SeasonRollover(world, random);

        var startingTopFlight = world.TeamsIn(new LeagueId(1)).Select(t => t.Id).ToHashSet();
        var everPromoted = new HashSet<TeamId>();

        for (var seasonId = 1; seasonId <= Seasons; seasonId++)
        {
            var seasons = world.LeaguesByTier()
                .Select(league => Season.Create(
                    seasonId, 2026 + seasonId, league,
                    world.TeamsIn(league.Id).Select(t => t.Id).ToList(), random))
                .ToList();

            foreach (var season in seasons)
            {
                engine.SimulateEntireSeason(season);
            }

            var report = rollover.Apply(seasonId, seasons);

            foreach (var league in report.Leagues)
            {
                Assert.Equal(3, league.Promoted.Count + league.Relegated.Count);
                foreach (var promoted in league.Promoted)
                {
                    everPromoted.Add(promoted);
                }
            }

            Assert.Equal(TeamsPerLeague, world.TeamsIn(new LeagueId(1)).Count);
            Assert.Equal(TeamsPerLeague, world.TeamsIn(new LeagueId(2)).Count);
        }

        Assert.True(
            everPromoted.Any(id => !startingTopFlight.Contains(id)),
            "No club from the second tier ever reached the top flight in ten seasons.");
    }

    private static void AssertTableIsValid(IReadOnlyList<LeagueTableRow> table, int seasonId)
    {
        Assert.Equal(TeamsPerLeague, table.Count);
        Assert.Equal(Enumerable.Range(1, TeamsPerLeague), table.Select(r => r.Position));
        Assert.Equal(table.Count, table.Select(r => r.TeamId).Distinct().Count());

        foreach (var row in table)
        {
            Assert.Equal(MatchdaysPerSeason, row.Played);
            Assert.Equal(row.Played, row.Won + row.Drawn + row.Lost);
            Assert.True(row.GoalsFor >= 0 && row.GoalsAgainst >= 0);
            Assert.Equal((row.Won * 3) + row.Drawn, row.Points);
        }

        // Every goal scored was conceded by somebody in the same division.
        Assert.Equal(table.Sum(r => r.GoalsFor), table.Sum(r => r.GoalsAgainst));

        // The table must never contradict its own ordering.
        for (var i = 1; i < table.Count; i++)
        {
            var above = table[i - 1];
            var below = table[i];

            Assert.True(
                above.Points > below.Points
                || (above.Points == below.Points && above.GoalDifference > below.GoalDifference)
                || (above.Points == below.Points && above.GoalDifference == below.GoalDifference),
                $"Season {seasonId}: position {above.Position} sits above {below.Position} on fewer points.");
        }
    }

    private static void AssertWorldIsValid(World world, int seasonId)
    {
        var violations = WorldInvariants.Check(world);
        Assert.True(
            violations.Count == 0,
            $"Season {seasonId} left the world invalid:{Environment.NewLine}" +
            string.Join(Environment.NewLine, violations.Select(v => "  - " + v)));

        Assert.All(world.Teams, team => Assert.True(
            team.Budget >= 0, $"Season {seasonId}: {team.Name} is on {team.Budget:N0}."));

        // No orphans: every player is either a free agent or in a real squad at a real club.
        foreach (var player in world.Players)
        {
            if (player.TeamId is not { } teamId)
            {
                Assert.Null(player.SquadNumber);
                continue;
            }

            Assert.True(world.HasTeam(teamId), $"{player.Name} points at missing team {teamId}.");
            Assert.Contains(player, world.SquadOf(teamId));
            Assert.NotNull(player.SquadNumber);
        }
    }
}
