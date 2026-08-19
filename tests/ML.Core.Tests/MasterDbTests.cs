using ML.Data;

namespace ML.Core.Tests;

public class MasterDbTests
{
    [Fact]
    public void CreatesSchemaAndRoundTripsTheWorld()
    {
        using var db = MasterDb.OpenInMemory();
        var repo = new Repository(db);

        repo.UpsertLeague(new LeagueRow
        {
            Id = 1, Name = "National League", Tier = 5, RelegationPlaces = 3,
            CompetitionSlot = 586, LogoPath = "logos/nl.png",
        });
        repo.UpsertTeam(new TeamRow
        {
            Id = 1, GameTeamId = 5804, IsCustom = false, Name = "Tamworth", ShortName = "TAM",
            LeagueId = 1, Budget = 250_000, HomeStadium = "The Lamb",
            PrimaryColor = "#D50032", SecondaryColor = "#FFFFFF", LogoPath = "logos/tamworth.png",
        });
        repo.UpsertPlayer(new PlayerRow
        {
            Id = 1, GamePid = 9_000_100, DonorPid = 57123, IsCustom = true, Name = "Ben Milnes",
            ShortName = "MILNES", Position = "CMF", Age = 34, Nationality = "England",
            HeightCm = 175, WeightKg = 72, OverallRating = 66,
        });
        repo.SetAttribute(1, "finishing", 60);
        repo.SetAttribute(1, "low_pass", 72);
        repo.SetSquadMember(new SquadMemberRow { TeamId = 1, PlayerId = 1, SquadNumber = 8, Slot = 7 });

        Assert.Single(repo.Leagues());
        Assert.Equal("Tamworth", repo.Teams().Single().Name);
        var player = repo.Players().Single();
        Assert.True(player.IsCustom);
        Assert.Equal(9_000_100, player.GamePid);
        Assert.Equal(72, repo.Attributes(1)["low_pass"]);
        Assert.Equal(8, repo.Squad(1).Single().SquadNumber);
    }

    [Fact]
    public void UpsertIsIdempotentOnId()
    {
        using var db = MasterDb.OpenInMemory();
        var repo = new Repository(db);
        var p = new PlayerRow { Id = 1, GamePid = 90001, DonorPid = 100, IsCustom = true, Name = "A", Position = "CF", OverallRating = 60 };

        repo.UpsertPlayer(p);
        repo.UpsertPlayer(p with { Name = "A Renamed", OverallRating = 70 });

        var only = repo.Players().Single();
        Assert.Equal("A Renamed", only.Name);
        Assert.Equal(70, only.OverallRating);
    }

    [Fact]
    public void FluidFormationStoresTwoDistinctPhaseShapes()
    {
        using var db = MasterDb.OpenInMemory();
        var repo = new Repository(db);
        repo.UpsertLeague(new LeagueRow { Id = 1, Name = "L", Tier = 1 });
        repo.UpsertTeam(new TeamRow { Id = 1, GameTeamId = 100, Name = "T", LeagueId = 1 });
        repo.UpsertFormation(new FormationRow { Id = 10, Name = "4-4-2" },
            Enumerable.Range(0, 11).Select(i => new FormationSlotRow { FormationId = 10, SlotIndex = i, Position = i == 0 ? 0 : 5, X = 52, Y = 3 + i }));
        repo.UpsertFormation(new FormationRow { Id = 11, Name = "3-2-5" },
            Enumerable.Range(0, 11).Select(i => new FormationSlotRow { FormationId = 11, SlotIndex = i, Position = i == 0 ? 0 : 12, X = 52, Y = 5 + i }));
        repo.SetTeamTactics(new TeamTacticsRow { TeamId = 1, Phase = 0, FormationId = 11, Style = 2 }); // attacking
        repo.SetTeamTactics(new TeamTacticsRow { TeamId = 1, Phase = 1, FormationId = 10, Style = 0 }); // defending

        var tactics = repo.TeamTactics(1);
        Assert.Equal(2, tactics.Count);
        Assert.NotEqual(tactics[0].FormationId, tactics[1].FormationId); // genuinely fluid
    }

    [Fact]
    public void RecordingAResultMarksTheFixturePlayed()
    {
        using var db = MasterDb.OpenInMemory();
        var repo = new Repository(db);
        repo.UpsertLeague(new LeagueRow { Id = 1, Name = "L", Tier = 1 });
        repo.UpsertTeam(new TeamRow { Id = 1, GameTeamId = 100, Name = "H", LeagueId = 1 });
        repo.UpsertTeam(new TeamRow { Id = 2, GameTeamId = 101, Name = "A", LeagueId = 1 });
        repo.UpsertSeason(new SeasonRow { Id = 1, Year = 2026, IsCurrent = true });
        repo.AddFixture(new FixtureRow { Id = 1, SeasonId = 1, LeagueId = 1, Matchday = 1, HomeTeamId = 1, AwayTeamId = 2 });

        repo.RecordResult(new ResultRow { FixtureId = 1, HomeGoals = 2, AwayGoals = 1, ScreenshotPath = "s.png" });

        Assert.True(repo.Fixtures(1).Single().Played);
    }
}
