using ML.Core;
using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Simulation;
using ML.Data;

namespace ML.App;

/// <summary>
/// Seeds an in-memory master DB with a playable National League so the app runs without the game
/// installed. Uses the same club set the compiler authored into dt200, real fixtures from the
/// engine, and a few played matchdays so the table, form and dashboard have content.
/// </summary>
public static class SampleData
{
    private static readonly string[] Clubs =
    {
        "Aldershot Town", "Altrincham", "Boreham Wood", "Boston United", "Brackley Town",
        "Braintree Town", "Carlisle United", "Eastleigh", "FC Halifax Town", "Forest Green Rovers",
        "Gateshead", "Hartlepool United", "Morecambe", "Rochdale", "Scunthorpe United",
        "Solihull Moors", "Southend United", "Sutton United", "Tamworth", "Truro City",
        "Wealdstone", "Woking", "Yeovil Town", "York City",
    };

    public static Session Build()
    {
        var db = MasterDb.OpenInMemory();
        var repo = new Repository(db);
        var rng = new SeededRandom(2027);

        repo.UpsertLeague(new LeagueRow
        {
            Id = 1, Name = "National League", Tier = 5, PromotionPlaces = 3, RelegationPlaces = 4,
            CompetitionSlot = 586,
        });
        repo.UpsertSeason(new SeasonRow { Id = 1, Year = 2026, IsCurrent = true });

        var playerId = 1;
        for (var i = 0; i < Clubs.Length; i++)
        {
            var teamId = i + 1;
            repo.UpsertTeam(new TeamRow
            {
                Id = teamId, GameTeamId = 5000 + teamId, IsCustom = true, Name = Clubs[i],
                ShortName = Clubs[i][..Math.Min(3, Clubs[i].Length)].ToUpperInvariant(),
                LeagueId = 1, Budget = 150_000 + rng.Next(400) * 1000,
            });

            foreach (var (pos, shirt) in Formation())
            {
                repo.UpsertPlayer(new PlayerRow
                {
                    Id = playerId, GamePid = 9_000_000 + playerId, IsCustom = true,
                    Name = $"{Clubs[i].Split(' ')[0]} Player {shirt}", ShortName = $"P{shirt}",
                    Position = pos, Age = 19 + rng.Next(18), Nationality = "England",
                    OverallRating = 58 + rng.Next(16),
                });
                repo.SetSquadMember(new SquadMemberRow
                {
                    TeamId = teamId, PlayerId = playerId, SquadNumber = shirt, Slot = shirt - 1,
                });
                playerId++;
            }
        }

        // Real fixtures from the engine, then simulate the first third of the season.
        var teamIds = Enumerable.Range(1, Clubs.Length).Select(t => new TeamId(t)).ToList();
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(teamIds, rng);
        var strengths = teamIds.ToDictionary(
            t => t.Value, t => 55 + (t.Value * 37 % 20)); // spread, deterministic
        var sim = new PoissonMatchSimulator(rng);

        var playedThrough = fixtures.Max(f => f.Matchday) / 3;
        foreach (var f in fixtures)
        {
            repo.AddFixture(new FixtureRow
            {
                Id = f.Id, SeasonId = 1, LeagueId = 1, Matchday = f.Matchday,
                HomeTeamId = f.HomeTeam.Value, AwayTeamId = f.AwayTeam.Value,
            });
            if (f.Matchday <= playedThrough)
            {
                var hs = strengths[f.HomeTeam.Value];
                var as_ = strengths[f.AwayTeam.Value];
                var result = sim.Simulate(
                    new ML.Core.Simulation.TeamStrength(hs, hs),
                    new ML.Core.Simulation.TeamStrength(as_, as_));
                repo.RecordResult(new ResultRow
                {
                    FixtureId = f.Id, HomeGoals = result.HomeGoals, AwayGoals = result.AwayGoals,
                });
            }
        }

        // Manage Tamworth by default (the club we proved on the pitch).
        var current = Array.IndexOf(Clubs, "Tamworth") + 1;

        // Preseason friendlies for the managed club (matchday 0, before the league kicks off).
        var fixtureId = fixtures.Max(f => f.Id) + 1;
        int[] opponents = { 7, 14, 22, 3 }; // a few clubs to warm up against
        foreach (var opp in opponents)
        {
            if (opp == current) continue;
            var home = fixtureId % 2 == 0;
            repo.AddFixture(new FixtureRow
            {
                Id = fixtureId, SeasonId = 1, LeagueId = 1, Matchday = 0,
                HomeTeamId = home ? current : opp, AwayTeamId = home ? opp : current,
                Kind = "friendly", Played = true,
            });
            var result = sim.Simulate(
                new ML.Core.Simulation.TeamStrength(60, 60),
                new ML.Core.Simulation.TeamStrength(58, 58));
            repo.RecordResult(new ResultRow
            {
                FixtureId = fixtureId, HomeGoals = result.HomeGoals, AwayGoals = result.AwayGoals,
            });
            fixtureId++;
        }

        return new Session(db, current, seasonId: 1);
    }

    private static IEnumerable<(string Pos, int Shirt)> Formation()
    {
        yield return ("GK", 1);
        yield return ("RB", 2); yield return ("CB", 5); yield return ("CB", 6); yield return ("LB", 3);
        yield return ("DMF", 4); yield return ("CMF", 8); yield return ("AMF", 10);
        yield return ("RWF", 7); yield return ("CF", 9); yield return ("LWF", 11);
        yield return ("GK", 13); yield return ("CB", 12); yield return ("CMF", 14);
        yield return ("CF", 15); yield return ("RB", 16); yield return ("LWF", 17);
    }
}
