using ML.Core;
using ML.Core.Domain;
using ML.Core.Scheduling;
using ML.Core.Simulation;
using ML.Data;

namespace ML.App;

/// <summary>
/// Seeds an in-memory master DB with the Serbian SuperLiga so the app runs without the game
/// installed. Club names are the real RFS names (so "Play Match" can resolve each club's true
/// squad from RFS and author it into dt200). You manage Partizan; the next match on the calendar
/// is the preseason Eternal Derby against Red Star — press Play Match to compile and play it.
/// </summary>
public static class SampleData
{
    // Real Serbian SuperLiga clubs, in the exact spelling RFS uses — the compiler matches on these.
    private static readonly string[] Clubs =
    {
        "FK Partizan Belgrade", "Red Star Belgrade", "FK Vojvodina Novi Sad", "FK Cukaricki",
        "FK TSC Backa Topola", "FK Radnicki Nis", "FK Radnicki 1923 Kragujevac", "FK Novi Pazar",
        "FK Napredak Krusevac", "FK Mladost Lucani", "FK Zeleznicar Pancevo", "OFK Beograd",
    };

    private const int Partizan = 1;   // teamId of the managed club (index 0 + 1)
    private const int RedStar = 2;    // the derby rival — opponent in the opening friendly

    public static Session Build()
    {
        var db = MasterDb.OpenInMemory();
        var repo = new Repository(db);
        var rng = new SeededRandom(2027);

        repo.UpsertLeague(new LeagueRow
        {
            Id = 1, Name = "Serbian SuperLiga", Tier = 1, PromotionPlaces = 0, RelegationPlaces = 3,
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
                ShortName = ShortName(Clubs[i]),
                LeagueId = 1, Budget = 800_000 + rng.Next(600) * 1000,
            });

            foreach (var (pos, shirt) in Formation())
            {
                repo.UpsertPlayer(new PlayerRow
                {
                    Id = playerId, GamePid = 9_000_000 + playerId, IsCustom = true,
                    Name = $"{ShortName(Clubs[i])} Player {shirt}", ShortName = $"P{shirt}",
                    Position = pos, Age = 19 + rng.Next(18), Nationality = "Serbia",
                    OverallRating = 62 + rng.Next(16),
                });
                repo.SetSquadMember(new SquadMemberRow
                {
                    TeamId = teamId, PlayerId = playerId, SquadNumber = shirt, Slot = shirt - 1,
                });
                playerId++;
            }
        }

        // Real fixtures from the engine, then simulate the first third of the season so the table
        // and form have content.
        var teamIds = Enumerable.Range(1, Clubs.Length).Select(t => new TeamId(t)).ToList();
        var fixtures = FixtureGenerator.GenerateDoubleRoundRobin(teamIds, rng);
        var strengths = teamIds.ToDictionary(
            t => t.Value, t => 60 + (t.Value * 37 % 20));
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

        // The opening preseason friendly — the Eternal Derby, and the very next match to be PLAYED.
        // Left unplayed on purpose: it is what the Play Match button compiles and boots.
        var friendlyId = fixtures.Max(f => f.Id) + 1;
        repo.AddFixture(new FixtureRow
        {
            Id = friendlyId, SeasonId = 1, LeagueId = 1, Matchday = 0,
            HomeTeamId = Partizan, AwayTeamId = RedStar, Kind = "friendly", Played = false,
        });

        return new Session(db, Partizan, seasonId: 1);
    }

    private static string ShortName(string club)
    {
        // "FK Partizan Belgrade" -> "Partizan"; "Red Star Belgrade" -> "Red Star".
        var words = club.Replace("FK ", "").Replace("OFK ", "").Split(' ');
        return words.Length >= 2 && words[0] == "Red" ? "Red Star" : words[0];
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
