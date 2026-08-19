using ML.Ingest;

namespace ML.Core.Tests;

public class ResultImporterTests
{
    [Fact]
    public void ParsesScorerLinesWithMinutes()
    {
        var scorers = ResultImporter.ParseScorers("Milnes 23', Creaney 67', Milnes 90'");
        Assert.Equal(3, scorers.Count);
        Assert.Equal(("Milnes", 23), scorers[0]);
        Assert.Equal(("Creaney", 67), scorers[1]);
        Assert.Equal(90, scorers[2].Minute);
    }

    [Fact]
    public void IgnoresGarbageAndOutOfRangeMinutes()
    {
        // OCR noise: a dashes-only token, an impossible minute; a real scorer survives
        var scorers = ResultImporter.ParseScorers("--- 999', Kelly 45'");
        Assert.Single(scorers);
        Assert.Equal(("Kelly", 45), scorers[0]);
    }

    [Fact]
    public void ResolvesExactSurnameToPlayer()
    {
        var squad = new[] { (10, "Ben Milnes"), (9, "Dan Creaney"), (7, "Ben Acquaye") };
        Assert.Equal(10, ResultImporter.ResolveScorer("Milnes", squad));
        Assert.Equal(9, ResultImporter.ResolveScorer("D. Creaney", squad));
    }

    [Fact]
    public void ResolvesNearMissWithinEditDistance()
    {
        var squad = new[] { (10, "Ben Milnes"), (9, "Dan Creaney") };
        // OCR read "Crearey" instead of "Creaney" — one substitution
        Assert.Equal(9, ResultImporter.ResolveScorer("Crearey", squad));
    }

    [Fact]
    public void RefusesToGuessWhenNothingIsClose()
    {
        var squad = new[] { (10, "Ben Milnes"), (9, "Dan Creaney") };
        Assert.Null(ResultImporter.ResolveScorer("Ronaldo", squad));
    }

    [Fact]
    public void FullTimeStatsRoundTripToDbWithScorers()
    {
        using var db = ML.Data.MasterDb.OpenInMemory();
        var repo = new ML.Data.Repository(db);
        repo.UpsertLeague(new ML.Data.LeagueRow { Id = 1, Name = "NL", Tier = 5 });
        repo.UpsertTeam(new ML.Data.TeamRow { Id = 1, GameTeamId = 100, Name = "Tamworth", LeagueId = 1 });
        repo.UpsertTeam(new ML.Data.TeamRow { Id = 2, GameTeamId = 101, Name = "Woking", LeagueId = 1 });
        repo.UpsertSeason(new ML.Data.SeasonRow { Id = 1, Year = 2026, IsCurrent = true });
        repo.AddFixture(new ML.Data.FixtureRow { Id = 1, SeasonId = 1, LeagueId = 1, Matchday = 1, HomeTeamId = 1, AwayTeamId = 2 });
        repo.UpsertPlayer(new ML.Data.PlayerRow { Id = 10, GamePid = 90010, IsCustom = true, Name = "Ben Milnes", Position = "CMF" });

        var stats = new MatchStats
        {
            HomeScore = new OcrValue<int>(2, 0.99),
            AwayScore = new OcrValue<int>(1, 0.99),
            ScorersRaw = new OcrValue<string>("Milnes 23', Milnes 78'", 0.6),
        };
        stats.Numbers["home_shots"] = new OcrValue<int>(14, 0.95);

        new ResultImporter(repo).Import(1, stats, new[] { (10, "Ben Milnes") });

        Assert.True(repo.Fixtures(1).Single().Played);
        var events = repo.MatchEvents(1);
        Assert.Equal(2, events.Count);
        Assert.All(events, e => Assert.Equal(10, e.PlayerId)); // both resolved to Milnes
    }

    [Fact]
    public void FlagsLowConfidenceFieldsForReview()
    {
        var stats = new MatchStats
        {
            HomeScore = new OcrValue<int>(2, 0.99),
            AwayScore = new OcrValue<int>(1, 0.4),   // shaky
            ScorersRaw = new OcrValue<string>("...", 0.5), // always shaky
        };
        var flagged = stats.LowConfidenceFields().ToHashSet();
        Assert.Contains("away_score", flagged);
        Assert.Contains("scorers", flagged);
        Assert.DoesNotContain("home_score", flagged);
    }
}
