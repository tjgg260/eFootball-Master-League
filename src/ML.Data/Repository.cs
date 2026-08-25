using Dapper;
using Microsoft.Data.Sqlite;

namespace ML.Data;

/// <summary>
/// Data access over <see cref="MasterDb"/>. Upserts on the game-facing ids so a re-import of the
/// same world is idempotent, and read queries shaped for the compiler and the UI.
/// </summary>
public sealed class Repository
{
    private readonly SqliteConnection _c;

    public Repository(MasterDb db) => _c = db.Connection;

    // --- leagues --------------------------------------------------------------

    public void UpsertLeague(LeagueRow l) => _c.Execute(
        """
        INSERT INTO leagues(id,name,tier,promotion_places,relegation_places,competition_slot,logo_path)
        VALUES(@Id,@Name,@Tier,@PromotionPlaces,@RelegationPlaces,@CompetitionSlot,@LogoPath)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name, tier=excluded.tier, promotion_places=excluded.promotion_places,
          relegation_places=excluded.relegation_places, competition_slot=excluded.competition_slot,
          logo_path=excluded.logo_path
        """, l);

    public IReadOnlyList<LeagueRow> Leagues() =>
        _c.Query<LeagueRow>("SELECT id Id,name Name,tier Tier,promotion_places PromotionPlaces," +
            "relegation_places RelegationPlaces,competition_slot CompetitionSlot,logo_path LogoPath " +
            "FROM leagues ORDER BY tier").ToList();

    // --- teams ----------------------------------------------------------------

    public void UpsertTeam(TeamRow t) => _c.Execute(
        """
        INSERT INTO teams(id,game_team_id,base_team_id,is_custom,name,short_name,league_id,budget,
          home_stadium,primary_color,secondary_color,kit_home_path,kit_away_path,logo_path)
        VALUES(@Id,@GameTeamId,@BaseTeamId,@IsCustom,@Name,@ShortName,@LeagueId,@Budget,
          @HomeStadium,@PrimaryColor,@SecondaryColor,@KitHomePath,@KitAwayPath,@LogoPath)
        ON CONFLICT(id) DO UPDATE SET
          game_team_id=excluded.game_team_id, base_team_id=excluded.base_team_id,
          is_custom=excluded.is_custom, name=excluded.name, short_name=excluded.short_name,
          league_id=excluded.league_id, budget=excluded.budget, home_stadium=excluded.home_stadium,
          primary_color=excluded.primary_color, secondary_color=excluded.secondary_color,
          kit_home_path=excluded.kit_home_path, kit_away_path=excluded.kit_away_path,
          logo_path=excluded.logo_path
        """, t);

    public IReadOnlyList<TeamRow> Teams() => _c.Query<TeamRow>(
        "SELECT id Id,game_team_id GameTeamId,base_team_id BaseTeamId,is_custom IsCustom,name Name," +
        "short_name ShortName,league_id LeagueId,budget Budget,home_stadium HomeStadium," +
        "primary_color PrimaryColor,secondary_color SecondaryColor,kit_home_path KitHomePath," +
        "kit_away_path KitAwayPath,logo_path LogoPath FROM teams ORDER BY id").ToList();

    public IReadOnlyList<TeamRow> TeamsIn(int leagueId) =>
        Teams().Where(t => t.LeagueId == leagueId).ToList();

    // --- players --------------------------------------------------------------

    public void UpsertPlayer(PlayerRow p) => _c.Execute(
        """
        INSERT INTO players(id,game_pid,base_pid,donor_pid,is_custom,name,short_name,position,age,
          dob,nationality,height_cm,weight_kg,overall_rating,portrait_path)
        VALUES(@Id,@GamePid,@BasePid,@DonorPid,@IsCustom,@Name,@ShortName,@Position,@Age,@Dob,
          @Nationality,@HeightCm,@WeightKg,@OverallRating,@PortraitPath)
        ON CONFLICT(id) DO UPDATE SET
          game_pid=excluded.game_pid, base_pid=excluded.base_pid, donor_pid=excluded.donor_pid,
          is_custom=excluded.is_custom, name=excluded.name, short_name=excluded.short_name,
          position=excluded.position, age=excluded.age, dob=excluded.dob,
          nationality=excluded.nationality, height_cm=excluded.height_cm, weight_kg=excluded.weight_kg,
          overall_rating=excluded.overall_rating, portrait_path=excluded.portrait_path
        """, p);

    public IReadOnlyList<PlayerRow> Players() => _c.Query<PlayerRow>(
        "SELECT id Id,game_pid GamePid,base_pid BasePid,donor_pid DonorPid,is_custom IsCustom," +
        "name Name,short_name ShortName,position Position,age Age,dob Dob,nationality Nationality," +
        "height_cm HeightCm,weight_kg WeightKg,overall_rating OverallRating,portrait_path PortraitPath " +
        "FROM players WHERE superseded_by IS NULL ORDER BY id").ToList();

    public void SetAttribute(long playerId, string attribute, int value) => _c.Execute(
        "INSERT INTO player_attributes(player_id,attribute,value) VALUES(@playerId,@attribute,@value) " +
        "ON CONFLICT(player_id,attribute) DO UPDATE SET value=excluded.value",
        new { playerId, attribute, value });

    public IReadOnlyDictionary<string, int> Attributes(long playerId) =>
        _c.Query<(string Attribute, int Value)>(
            "SELECT attribute Attribute,value Value FROM player_attributes WHERE player_id=@playerId",
            new { playerId }).ToDictionary(x => x.Attribute, x => x.Value);

    // --- squads ---------------------------------------------------------------

    public void SetSquadMember(SquadMemberRow s) => _c.Execute(
        """
        INSERT INTO squad_members(team_id,player_id,squad_number,slot,role)
        VALUES(@TeamId,@PlayerId,@SquadNumber,@Slot,@Role)
        ON CONFLICT(team_id,player_id) DO UPDATE SET
          squad_number=excluded.squad_number, slot=excluded.slot, role=excluded.role
        """, s);

    public IReadOnlyList<SquadMemberRow> Squad(int teamId) => _c.Query<SquadMemberRow>(
        "SELECT team_id TeamId,player_id PlayerId,squad_number SquadNumber,slot Slot,role Role " +
        "FROM squad_members WHERE team_id=@teamId ORDER BY slot", new { teamId }).ToList();

    public void RemoveSquadMember(int teamId, long playerId) => _c.Execute(
        "DELETE FROM squad_members WHERE team_id=@teamId AND player_id=@playerId", new { teamId, playerId });

    public void RecordTransfer(long playerId, int toTeamId, int seasonId) => _c.Execute(
        "INSERT INTO transfers(player_id,to_team_id,season_id,window) " +
        "VALUES(@playerId,@toTeamId,@seasonId,'signing')", new { playerId, toTeamId, seasonId });

    /// <summary>Just one club's players (joined via squad_members) — avoids loading the whole DB.
    /// PortraitPath prefers the facepack photo (real_face_path) over the RFS portrait: career
    /// copies carry their face in real_face_path, so a portrait_path-only read shows no faces.</summary>
    public IReadOnlyList<PlayerRow> SquadPlayers(int teamId) => _c.Query<PlayerRow>(
        "SELECT p.id Id,p.game_pid GamePid,p.base_pid BasePid,p.donor_pid DonorPid,p.is_custom IsCustom," +
        "p.name Name,p.short_name ShortName,p.position Position,p.age Age,p.dob Dob,p.nationality Nationality," +
        "p.height_cm HeightCm,p.weight_kg WeightKg,p.overall_rating OverallRating," +
        "COALESCE(p.real_face_path, p.portrait_path) PortraitPath " +
        "FROM players p JOIN squad_members s ON s.player_id=p.id WHERE s.team_id=@teamId", new { teamId }).ToList();

    // --- condition ------------------------------------------------------------

    /// <summary>
    /// Condition rows for one club's current squad. Only players that HAVE a row come back —
    /// callers treat a missing player as fresh (fatigue 0, form 6.5, fit).
    /// </summary>
    public IReadOnlyList<PlayerConditionRow> ConditionsFor(int teamId) => _c.Query<PlayerConditionRow>(
        "SELECT c.player_id PlayerId,c.fatigue Fatigue,c.injured_until_md InjuredUntilMd,c.form Form " +
        "FROM player_condition c JOIN squad_members s ON s.player_id=c.player_id " +
        "WHERE s.team_id=@teamId ORDER BY c.player_id", new { teamId }).ToList();

    public void UpsertCondition(PlayerConditionRow c) => _c.Execute(
        "INSERT INTO player_condition(player_id,fatigue,injured_until_md,form) " +
        "VALUES(@PlayerId,@Fatigue,@InjuredUntilMd,@Form) " +
        "ON CONFLICT(player_id) DO UPDATE SET fatigue=excluded.fatigue, " +
        "injured_until_md=excluded.injured_until_md, form=excluded.form", c);

    // --- tactics --------------------------------------------------------------

    public void UpsertFormation(FormationRow f, IEnumerable<FormationSlotRow> slots)
    {
        _c.Execute("INSERT INTO formations(id,name) VALUES(@Id,@Name) " +
                   "ON CONFLICT(id) DO UPDATE SET name=excluded.name", f);
        _c.Execute("DELETE FROM formation_slots WHERE formation_id=@Id", f);
        _c.Execute(
            "INSERT INTO formation_slots(formation_id,slot_index,position,x,y) " +
            "VALUES(@FormationId,@SlotIndex,@Position,@X,@Y)", slots);
    }

    public void SetTeamTactics(TeamTacticsRow t) => _c.Execute(
        "INSERT INTO team_tactics(team_id,phase,formation_id,style) VALUES(@TeamId,@Phase,@FormationId,@Style) " +
        "ON CONFLICT(team_id,phase) DO UPDATE SET formation_id=excluded.formation_id, style=excluded.style", t);

    public IReadOnlyList<TeamTacticsRow> TeamTactics(int teamId) => _c.Query<TeamTacticsRow>(
        "SELECT team_id TeamId,phase Phase,formation_id FormationId,style Style " +
        "FROM team_tactics WHERE team_id=@teamId ORDER BY phase", new { teamId }).ToList();

    public IReadOnlyList<FormationSlotRow> FormationSlots(int formationId) => _c.Query<FormationSlotRow>(
        "SELECT formation_id FormationId,slot_index SlotIndex,position Position,x X,y Y " +
        "FROM formation_slots WHERE formation_id=@formationId ORDER BY slot_index",
        new { formationId }).ToList();

    // --- season / fixtures / results -----------------------------------------

    public void UpsertSeason(SeasonRow s) => _c.Execute(
        "INSERT INTO seasons(id,year,is_current) VALUES(@Id,@Year,@IsCurrent) " +
        "ON CONFLICT(id) DO UPDATE SET year=excluded.year, is_current=excluded.is_current", s);

    public void AddFixture(FixtureRow f) => _c.Execute(
        "INSERT INTO fixtures(id,season_id,league_id,matchday,home_team_id,away_team_id,played,kind) " +
        "VALUES(@Id,@SeasonId,@LeagueId,@Matchday,@HomeTeamId,@AwayTeamId,@Played,@Kind) " +
        "ON CONFLICT(id) DO UPDATE SET played=excluded.played", f);

    public void RecordResult(ResultRow r)
    {
        _c.Execute(
            "INSERT INTO results(fixture_id,home_goals,away_goals,stats_json,screenshot_path) " +
            "VALUES(@FixtureId,@HomeGoals,@AwayGoals,@StatsJson,@ScreenshotPath) " +
            "ON CONFLICT(fixture_id) DO UPDATE SET home_goals=excluded.home_goals, " +
            "away_goals=excluded.away_goals, stats_json=excluded.stats_json, " +
            "screenshot_path=excluded.screenshot_path", r);
        _c.Execute("UPDATE fixtures SET played=1 WHERE id=@FixtureId", r);
    }

    public void AddMatchEvent(int fixtureId, int? playerId, string eventType, int minute) => _c.Execute(
        "INSERT INTO match_events(fixture_id,player_id,event_type,minute) " +
        "VALUES(@fixtureId,@playerId,@eventType,@minute)",
        new { fixtureId, playerId, eventType, minute });

    public IReadOnlyList<(int PlayerId, string EventType, int Minute)> MatchEvents(int fixtureId) =>
        _c.Query<(int PlayerId, string EventType, int Minute)>(
            "SELECT player_id PlayerId, event_type EventType, minute Minute FROM match_events " +
            "WHERE fixture_id=@fixtureId ORDER BY minute", new { fixtureId }).ToList();

    public IReadOnlyList<FixtureRow> Fixtures(int seasonId, int? matchday = null) => _c.Query<FixtureRow>(
        "SELECT id Id,season_id SeasonId,league_id LeagueId,matchday Matchday,home_team_id HomeTeamId," +
        "away_team_id AwayTeamId,played Played,kind Kind FROM fixtures WHERE season_id=@seasonId " +
        (matchday is null ? "" : "AND matchday=@matchday ") + "ORDER BY matchday,id",
        new { seasonId, matchday }).ToList();

    // --- manager --------------------------------------------------------------

    public void AddInbox(InboxRow m) => _c.Execute(
        "INSERT INTO inbox(id,season_id,matchday,category,subject,body,is_read,requires_action) " +
        "VALUES(@Id,@SeasonId,@Matchday,@Category,@Subject,@Body,@IsRead,@RequiresAction)", m);

    public IReadOnlyList<InboxRow> Inbox() => _c.Query<InboxRow>(
        "SELECT id Id,season_id SeasonId,matchday Matchday,category Category,subject Subject," +
        "body Body,is_read IsRead,requires_action RequiresAction FROM inbox ORDER BY id DESC").ToList();

    public void SetBoardConfidence(BoardConfidenceRow b) => _c.Execute(
        "INSERT INTO board_confidence(team_id,season_id,confidence,expectation) " +
        "VALUES(@TeamId,@SeasonId,@Confidence,@Expectation) " +
        "ON CONFLICT(team_id,season_id) DO UPDATE SET confidence=excluded.confidence, " +
        "expectation=excluded.expectation", b);
}
