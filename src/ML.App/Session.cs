using ML.Core;
using ML.Core.Domain;
using ML.Core.Management;
using ML.Core.Scheduling;
using ML.Core.Selection;
using ML.Core.Simulation;
using ML.Core.Tables;
using ML.Data;
using Microsoft.Data.Sqlite;

namespace ML.App;

/// <summary>
/// The running Master League the UI binds to: the master DB, the chosen club, and its live
/// manager state (board confidence, morale, finances). Bridges DB rows to ML.Core so the league
/// table and standings come from the tested engine rather than duplicated SQL.
/// </summary>
public sealed partial class Session
{
    public Session(MasterDb db, int currentTeamId, int seasonId)
    {
        Db = db;
        Repo = new Repository(db);
        CurrentTeamId = currentTeamId;
        SeasonId = seasonId;

        var team = TeamCache[currentTeamId];
        Morale = new Morale(60);
        Finances = new Finances(team.Budget);
        CurrentTeamName = team.Name;
        PrimaryColor = team.PrimaryColor;
        SecondaryColor = team.SecondaryColor;
        LogoPath = team.LogoPath;
        LeagueId = team.LeagueId ?? 0;
        LeagueName = Repo.Leagues().FirstOrDefault(l => l.Id == LeagueId)?.Name ?? "League";

        // The board is real (D2): expectation derived from where this squad ranks in its league,
        // confidence persisted across launches so a slump actually follows you home.
        Expectation expectation;
        try { expectation = DeriveExpectation(); }
        catch { expectation = Expectation.MidTable; }
        Board = new BoardConfidence(expectation, starting: StoredBoardConfidence);

        RestoreSeasonFinances();   // season income/spend survive app restarts (P0)
        // OCR paths from settings (meta), falling back to the recorded defaults.
        if (GetMeta("steam_root") is { Length: > 0 } root) ScoreImport.SteamRoot = root;
        if (GetMeta("steam_user_id") is { Length: > 0 } uid) ScoreImport.SteamUserId = uid;
        MatchLauncher.AutoBoot = GetMeta("auto_boot") != "0";
        Theme.Apply(GetMeta("ui_skin") ?? "Midnight", PrimaryColor);
        HealLegacyFormationOwnership();
        EnsureCup();
        try { EnsureObjectives(); } catch { /* objectives are additive */ }
        BackupCareer();       // your save survives anything — last five kept in build/backups
        EnsureInboxWelcome(); // a fresh career opens with mail, not an empty inbox
    }

    // Cache the team table once — TeamName/TeamColor are called per row across several screens.
    private Dictionary<int, TeamRow>? _teamCache;
    private Dictionary<int, TeamRow> TeamCache => _teamCache ??= Repo.Teams().ToDictionary(t => t.Id);

    public string? PrimaryColor { get; }
    public string? SecondaryColor { get; }
    public string? LogoPath { get; }
    public string? TeamColor(int teamId) => TeamCache.TryGetValue(teamId, out var t) ? t.PrimaryColor : null;
    public string? TeamSecondary(int teamId) => TeamCache.TryGetValue(teamId, out var t) ? t.SecondaryColor : null;
    public string? TeamLogoPath(int teamId) => TeamCache.TryGetValue(teamId, out var t) ? t.LogoPath : null;

    public MasterDb Db { get; }
    public Repository Repo { get; }
    public int CurrentTeamId { get; }
    public int SeasonId { get; private set; }
    public string CurrentTeamName { get; }
    public int LeagueId { get; private set; }
    public string LeagueName { get; private set; }
    public BoardConfidence Board { get; }
    public Morale Morale { get; }
    public Finances Finances { get; }

    public IReadOnlyList<TeamRow> LeagueTeams() => Repo.TeamsIn(LeagueId);

    public string TeamName(int teamId) => TeamCache.TryGetValue(teamId, out var t) ? t.Name : "?";

    /// <summary>League table computed by the ML.Core engine from played DB fixtures.</summary>
    public IReadOnlyList<LeagueTableRow> Table()
    {
        var teams = LeagueTeams().Select(t => new TeamId(t.Id)).ToList();
        var fixtures = new List<Fixture>();
        foreach (var f in Repo.Fixtures(SeasonId).Where(f => f.LeagueId == LeagueId && f.Kind == "league"))
        {
            var fixture = new Fixture(f.Id, f.Matchday, new TeamId(f.HomeTeamId), new TeamId(f.AwayTeamId));
            if (f.Played)
            {
                var r = ResultFor(f.Id);
                if (r is not null)
                {
                    fixture.RecordResult(new MatchResult(r.HomeGoals, r.AwayGoals));
                }
            }
            fixtures.Add(fixture);
        }
        return LeagueTable.Build(teams, fixtures);
    }

    public int CurrentPosition()
    {
        var row = Table().FirstOrDefault(r => r.TeamId.Value == CurrentTeamId);
        return row?.Position ?? 0;
    }

    /// <summary>
    /// Your league position after each played matchday — the "worm" chart's data (P6).
    /// Rebuilt from fixtures, no stored series needed.
    /// </summary>
    public IReadOnlyList<int> PositionHistory()
    {
        var teams = LeagueTeams().Select(t => new TeamId(t.Id)).ToList();
        var all = Repo.Fixtures(SeasonId)
            .Where(f => f.LeagueId == LeagueId && f.Kind == "league").ToList();
        var maxMd = all.Where(f => f.Played).Select(f => f.Matchday).DefaultIfEmpty(0).Max();
        var history = new List<int>();
        for (var md = 1; md <= maxMd; md++)
        {
            var fixtures = new List<Fixture>();
            foreach (var f in all)
            {
                var fixture = new Fixture(f.Id, f.Matchday, new TeamId(f.HomeTeamId), new TeamId(f.AwayTeamId));
                if (f.Played && f.Matchday <= md && ResultFor(f.Id) is { } r)
                {
                    fixture.RecordResult(new MatchResult(r.HomeGoals, r.AwayGoals));
                }
                fixtures.Add(fixture);
            }
            var pos = LeagueTable.Build(teams, fixtures)
                .FirstOrDefault(t => t.TeamId.Value == CurrentTeamId)?.Position ?? 0;
            if (pos > 0) history.Add(pos);
        }
        return history;
    }

    public IReadOnlyList<FixtureRow> UpcomingFixtures(int count = 5) =>
        Repo.Fixtures(SeasonId)
            .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && !f.Played)
            .OrderBy(f => f.Matchday)
            .Take(count).ToList();

    /// <summary>Average squad rating — used for market/valuation comparisons.</summary>
    private double SquadStrengthOf(int teamId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT AVG(p.overall_rating) FROM squad_members s JOIN players p " +
                          "ON p.id=s.player_id WHERE s.team_id=$t AND p.overall_rating IS NOT NULL";
        cmd.Parameters.AddWithValue("$t", teamId);
        var v = cmd.ExecuteScalar();
        return v is null or DBNull ? 70.0 : Convert.ToDouble(v);
    }

    /// <summary>
    /// What the CPU simulator actually uses (P3): the LIKELY XI's attack and defence read
    /// separately, moved by fatigue and form. A glass-cannon squad no longer sims identically
    /// to a balanced one, and a tired, out-of-form XI actually drops points.
    /// </summary>
    internal (double Attack, double Defence) XiStrengthOf(int teamId)
    {
        double atkSum = 0, defSum = 0, atkN = 0, defN = 0, fatigue = 0, form = 0;
        var n = 0;
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.position, COALESCE(p.overall_rating, 62), COALESCE(c.fatigue, 0), " +
            "COALESCE(c.form, 6.5) FROM squad_members s " +
            "JOIN players p ON p.id = s.player_id " +
            "LEFT JOIN player_condition c ON c.player_id = s.player_id " +
            "WHERE s.team_id=$t AND s.slot BETWEEN 0 AND 10";
        cmd.Parameters.AddWithValue("$t", teamId);
        using (var r = cmd.ExecuteReader())
        {
            while (r.Read())
            {
                var cat = Visuals.PositionCategory(r.GetString(0));
                double rating = r.GetInt32(1);
                var (aw, dw) = cat switch
                {
                    "FWD" => (1.0, 0.15), "MID" => (0.7, 0.55), "DEF" => (0.2, 1.0), _ => (0.0, 1.1),
                };
                atkSum += rating * aw; atkN += aw;
                defSum += rating * dw; defN += dw;
                fatigue += r.GetInt32(2);
                form += r.GetDouble(3);
                n++;
            }
        }
        if (n < 6) { var avg = SquadStrengthOf(teamId); return (avg, avg); }
        var atk = atkSum / atkN;
        var def = defSum / defN;
        var condAdj = -(fatigue / n) / 12.0 + (form / n - 6.5) * 1.2;   // ± a few rating points
        return (atk + condAdj, def + condAdj);
    }

    /// <summary>
    /// Sim every other league fixture on a matchday (the CPU games), so the table advances when you
    /// play only your own match. Deterministic per (season, matchday) so re-runs are stable.
    /// </summary>
    public void PlayOutMatchday(int matchday, int exceptFixtureId)
    {
        if (matchday <= 0) return;   // preseason friendlies have no CPU round to sim
        var rng = new SeededRandom((SeasonId * 1000 + matchday) ^ WorldSeed);
        var sim = new PoissonMatchSimulator(rng);
        // BOTH divisions tick together — the league you're not in must not sit frozen all season.
        // YOUR fixtures are never simmed here: cup matchdays share numbers with league rounds,
        // and without this guard recording a cup tie played your league game behind your back.
        foreach (var f in Repo.Fixtures(SeasonId, matchday)
                     .Where(f => f.LeagueId is TopFlight or Division2 && f.Kind == "league"
                                 && !f.Played && f.Id != exceptFixtureId
                                 && f.HomeTeamId != CurrentTeamId && f.AwayTeamId != CurrentTeamId))
        {
            var h = XiStrengthOf(f.HomeTeamId);
            var a = XiStrengthOf(f.AwayTeamId);
            // A point and a half of home advantage on the attack — crowds matter (P3).
            var r = sim.Simulate(new TeamStrength(h.Attack + 1.5, h.Defence),
                                 new TeamStrength(a.Attack, a.Defence));
            Repo.RecordResult(new ResultRow { FixtureId = f.Id, HomeGoals = r.HomeGoals, AwayGoals = r.AwayGoals });
            AttributeSimmedMatch(f.Id, f.HomeTeamId, f.AwayTeamId, r.HomeGoals, r.AwayGoals, rng);
        }
        _results = null;   // invalidate the results cache so the table recomputes
        _elos = null;      // ratings follow results
    }

    /// <summary>True once every league fixture this season has a result — time to roll over.</summary>
    public bool SeasonComplete() =>
        Repo.Fixtures(SeasonId).Where(f => f.LeagueId == LeagueId && f.Kind == "league").All(f => f.Played)
        && Repo.Fixtures(SeasonId).Any(f => f.LeagueId == LeagueId && f.Kind == "league");

    /// <summary>
    /// End-of-season rollover: finish any unplayed games, crown the champion, age and develop every
    /// player in the division, then generate next season's fixtures. Returns a one-line summary.
    /// </summary>
    private const int TopFlight = 9000, Division2 = 9001;

    public string AdvanceToNextSeason()
    {
        SimAllUnplayed();

        var top = TableFor(TopFlight);
        var second = TableFor(Division2);
        var champion = top.Count > 0 ? TeamName(top[0].TeamId.Value) : "—";

        // Promotion / relegation: bottom 3 of the top flight swap with the top 3 of Division 2.
        // Single-division careers (countries with one league in the data) simply skip it.
        var movement = "";
        if (top.Count > 0 && second.Count > 0)
        {
            var relegated = top.TakeLast(3).Select(r => r.TeamId.Value).ToHashSet();
            var promoted = second.Take(3).Select(r => r.TeamId.Value).ToHashSet();
            foreach (var id in relegated) SetTeamLeague(id, Division2);
            foreach (var id in promoted) SetTeamLeague(id, TopFlight);
            _teamCache = null;   // team leagues changed

            movement = relegated.Contains(CurrentTeamId) ? " You were RELEGATED to Division 2."
                : promoted.Contains(CurrentTeamId) ? " You were PROMOTED to the top flight!" : "";
        }

        // Silverware into the Roll of Honour before anything resets — then the money follows it.
        RecordHonours(top, second);
        try { SeasonAwards(); } catch { /* the gala never blocks rollover */ }
        try { PayPrizesAndFlagEurope(top, second); } catch { /* prizes never block rollover */ }

        // Season review lands in the inbox before anything resets.
        var myTable = LeagueId == TopFlight ? top : second;
        var myPos = myTable.FirstOrDefault(r => r.TeamId.Value == CurrentTeamId)?.Position ?? 0;
        PostSeasonReview(champion, myPos, movement);

        // The manager's own career rolls with the season: rep swing, patience reset, suitors.
        try
        {
            RollCareerAtSeasonEnd(myPos, myTable.Count, movement.Contains("PROMOTED"));
        }
        catch { /* the career layer never blocks rollover */ }

        // The board settles its objectives (P2) — confidence, rep and backing move here.
        try { EvaluateObjectives(myPos); } catch { /* the verdict never blocks rollover */ }

        try { ReturnAllLoans(); } catch { /* loans never block rollover */ }
        AgeAndDevelopSquads();
        try { RetireAndExpire(); } catch { /* the world never blocks rollover */ }
        CpuTransferActivity();     // the market moves between seasons (and re-fills the retired)
        AcademyIntake();           // every club's youth setup produces new prospects
        GenerateOffers();          // CPU clubs bid for your best players
        foreach (var o in PendingOffers())
        {
            PostInbox("Transfer", $"Offer: {o.FromTeam} want {o.PlayerName}",
                $"£{o.Fee:N0} on the table. Accept or reject it on the Market screen.");
        }
        BackupCareer();            // season boundary = backup point

        // Everyone reports back for preseason fresh: fatigue and injuries cleared, form
        // drifting back toward neutral (6.5).
        using (var cond = Db.Connection.CreateCommand())
        {
            cond.CommandText = "UPDATE player_condition SET fatigue=0, injured_until_md=NULL, " +
                               "form=6.5+(form-6.5)*0.5";
            cond.ExecuteNonQuery();
        }

        var newSeason = SeasonId + 1;
        Repo.UpsertSeason(new SeasonRow { Id = newSeason, Year = 2026 + (newSeason - 9000), IsCurrent = true });

        var nextId = NextFixtureId();
        foreach (var lg in new[] { TopFlight, Division2 })
        {
            var ids = Repo.TeamsIn(lg).Select(t => new TeamId(t.Id)).ToList();
            if (ids.Count < 2) continue;
            foreach (var f in FixtureGenerator.GenerateDoubleRoundRobin(ids, new SeededRandom((newSeason * 104729 + lg) ^ WorldSeed)))
            {
                Repo.AddFixture(new FixtureRow
                {
                    Id = nextId++, SeasonId = newSeason, LeagueId = lg, Matchday = f.Matchday,
                    HomeTeamId = f.HomeTeam.Value, AwayTeamId = f.AwayTeam.Value, Kind = "league", Played = false,
                });
            }
        }

        // The managed club may have changed division — follow it.
        LeagueId = TeamCache.TryGetValue(CurrentTeamId, out var me) ? me.LeagueId ?? TopFlight : TopFlight;
        LeagueName = Repo.Leagues().FirstOrDefault(l => l.Id == LeagueId)?.Name ?? "League";
        var rival = Repo.TeamsIn(LeagueId).FirstOrDefault(t => t.Id != CurrentTeamId);
        if (rival is not null)
        {
            Repo.AddFixture(new FixtureRow
            {
                Id = nextId++, SeasonId = newSeason, LeagueId = LeagueId, Matchday = 0,
                HomeTeamId = CurrentTeamId, AwayTeamId = rival.Id, Kind = "friendly", Played = false,
            });
        }

        SetMeta("current_season_id", newSeason.ToString());
        SeasonId = newSeason;
        _results = null;
        _elos = null;
        EnsureCup();               // draw the new season's cup
        return $"{champion} won the top flight.{movement} Season {2026 + (newSeason - 9000)} begins — " +
               "squads aged, the market moved, academy intakes arrived, new fixtures and cup drawn.";
    }

    /// <summary>League table for any division (used to rank both tiers at rollover).</summary>
    public IReadOnlyList<LeagueTableRow> TableFor(int leagueId)
    {
        var teams = Repo.TeamsIn(leagueId).Select(t => new TeamId(t.Id)).ToList();
        var fixtures = new List<Fixture>();
        foreach (var f in Repo.Fixtures(SeasonId).Where(f => f.LeagueId == leagueId && f.Kind == "league"))
        {
            var fx = new Fixture(f.Id, f.Matchday, new TeamId(f.HomeTeamId), new TeamId(f.AwayTeamId));
            if (f.Played)
            {
                var r = ResultFor(f.Id);
                if (r is not null) fx.RecordResult(new MatchResult(r.HomeGoals, r.AwayGoals));
            }
            fixtures.Add(fx);
        }
        return LeagueTable.Build(teams, fixtures);
    }

    private void SetTeamLeague(int teamId, int leagueId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE teams SET league_id=$l WHERE id=$id";
        cmd.Parameters.AddWithValue("$l", leagueId);
        cmd.Parameters.AddWithValue("$id", teamId);
        cmd.ExecuteNonQuery();
    }

    private void SimAllUnplayed()
    {
        var rng = new SeededRandom((SeasonId * 20011 + 7) ^ WorldSeed);
        var sim = new PoissonMatchSimulator(rng);
        foreach (var f in Repo.Fixtures(SeasonId).Where(f => f.Kind == "league" && !f.Played).ToList())
        {
            var h = XiStrengthOf(f.HomeTeamId);
            var a = XiStrengthOf(f.AwayTeamId);
            // A point and a half of home advantage on the attack — crowds matter (P3).
            var r = sim.Simulate(new TeamStrength(h.Attack + 1.5, h.Defence),
                                 new TeamStrength(a.Attack, a.Defence));
            Repo.RecordResult(new ResultRow { FixtureId = f.Id, HomeGoals = r.HomeGoals, AwayGoals = r.AwayGoals });
            AttributeSimmedMatch(f.Id, f.HomeTeamId, f.AwayTeamId, r.HomeGoals, r.AwayGoals, rng);
        }
        _results = null;
    }

    // Age every player across both divisions and nudge ratings: youth improve, veterans decline.
    private void AgeAndDevelopSquads()
    {
        var players = new List<(int Id, int Age, int Ovr)>();
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT DISTINCT p.id, COALESCE(p.age,24), COALESCE(p.overall_rating,70) " +
                "FROM players p JOIN squad_members s ON s.player_id=p.id " +
                "WHERE s.team_id IN (SELECT id FROM teams WHERE league_id IN (9000,9001))";
            using var r = q.ExecuteReader();
            while (r.Read()) players.Add((r.GetInt32(0), r.GetInt32(1), r.GetInt32(2)));
        }
        var rng = new SeededRandom((SeasonId * 7919 + 3) ^ WorldSeed);
        // Character + potential drive development (P1/P2): determined professionals grow harder
        // and decline softer; growth aims at each player's stored ceiling, with rare breakout
        // seasons for kids far below theirs. Computed before the transaction opens (TraitsOf /
        // PotentialOf write their own rows).
        var growth = new Dictionary<int, double>();
        var ceilings = new Dictionary<int, int>();
        foreach (var (id, age0, ovr0) in players)
        {
            try
            {
                growth[id] = GrowthMultiplierOf(id);
                ceilings[id] = PotentialOf(id, age0, ovr0);
            }
            catch { growth[id] = 1.0; ceilings[id] = 99; }
        }
        using var tx = Db.Connection.BeginTransaction();
        foreach (var (id, age, ovr) in players)
        {
            var newAge = age + 1;
            var raw = newAge < 24 ? rng.Next(4) - 1 : newAge <= 30 ? rng.Next(3) - 1 : -(1 + rng.Next(2));
            var m = growth.GetValueOrDefault(id, 1.0);
            var ceiling = ceilings.GetValueOrDefault(id, 99);
            // Positive growth scales up with character; decline is softened by it (and worsened
            // by its absence): a 0.6 slacker ages like milk, a 1.5 model pro like wine.
            var delta = raw > 0
                ? (int)Math.Round(raw * m)
                : raw < 0 ? (int)Math.Round(raw * (2.0 - m)) : 0;
            // Breakout season: a kid far below his ceiling occasionally leaps (~1 in 8).
            if (newAge <= 22 && ceiling - ovr >= 8 && rng.Next(8) == 0)
            {
                delta = Math.Max(delta, 3 + rng.Next(3));
            }
            // Nobody grows past his potential — the ceiling is what scouting is about.
            if (delta > 0) delta = Math.Min(delta, Math.Max(0, ceiling - ovr));
            using var u = Db.Connection.CreateCommand();
            u.Transaction = tx;   // Microsoft.Data.Sqlite requires it while a transaction is pending
            u.CommandText = "UPDATE players SET age=$a, overall_rating=$o WHERE id=$id";
            u.Parameters.AddWithValue("$a", newAge);
            u.Parameters.AddWithValue("$o", Math.Clamp(ovr + delta, 40, 99));
            u.Parameters.AddWithValue("$id", id);
            u.ExecuteNonQuery();

            // Development reaches the PITCH: the 26 abilities move with the rating, because
            // those are what the match compile writes into the game. Summary-only growth would
            // leave a wonderkid playing with his old attributes forever.
            if (delta != 0)
            {
                using var ab = Db.Connection.CreateCommand();
                ab.Transaction = tx;
                ab.CommandText = "UPDATE player_attributes SET value=MAX(30,MIN(99,value+$d)) " +
                                 "WHERE player_id=$id";
                ab.Parameters.AddWithValue("$d", delta);
                ab.Parameters.AddWithValue("$id", id);
                ab.ExecuteNonQuery();
            }
        }
        tx.Commit();
    }

    private int NextFixtureId()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT COALESCE(MAX(id),9000000)+1 FROM fixtures";
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    // ------------------------------------------------------------------ the world seed (P2)

    private int? _worldSeed;

    /// <summary>
    /// One random seed per career, rolled at first use and stored forever. Mixed into every
    /// world roll so two careers from the same master DB live DIFFERENT lives — before this,
    /// every save produced identical academy intakes, cup draws, CPU signings and offers.
    /// </summary>
    public int WorldSeed
    {
        get
        {
            if (_worldSeed is { } cached) return cached;
            if (int.TryParse(GetMeta("world_seed"), out var stored))
            {
                _worldSeed = stored;
                return stored;
            }
            var rolled = Random.Shared.Next(int.MinValue, int.MaxValue);
            SetMeta("world_seed", rolled.ToString());
            _worldSeed = rolled;
            return rolled;
        }
    }

    /// <summary>App settings live in meta; the Settings screen edits them through here.</summary>
    public string? GetSetting(string key) => GetMeta(key);

    public void SetSetting(string key, string value) => SetMeta(key, value);

    private void SetMeta(string key, string value)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO meta(key,value) VALUES($k,$v) " +
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value";
        cmd.Parameters.AddWithValue("$k", key);
        cmd.Parameters.AddWithValue("$v", value);
        cmd.ExecuteNonQuery();
    }

    private string? GetMeta(string key)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT value FROM meta WHERE key=$k";
        cmd.Parameters.AddWithValue("$k", key);
        return cmd.ExecuteScalar() as string;
    }

    /// <summary>The season's calendar year (career seasons start at id 9000 = 2026/27).</summary>
    public int SeasonYear => 2026 + (SeasonId - 9000);

    /// <summary>The real date a fixture is played (league Saturdays, cup Wednesdays).</summary>
    public DateOnly DateOfFixture(FixtureRow f) =>
        SeasonCalendar.DateOf(SeasonYear, f.Matchday, f.Kind);

    /// <summary>The next match to be played — the one the Play Match button compiles and boots.</summary>
    public FixtureRow? NextFixture() =>
        Repo.Fixtures(SeasonId)
            .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && !f.Played)
            .OrderBy(f => f.Matchday)
            .FirstOrDefault();

    public IReadOnlyList<FixtureRow> RecentResults(int count = 5) =>
        Repo.Fixtures(SeasonId)
            .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && f.Played)
            .Reverse().Take(count).ToList();

    public ResultRow? ResultFor(int fixtureId)
    {
        _results ??= LoadResults();
        return _results.TryGetValue(fixtureId, out var res) ? res : null;
    }

    private Dictionary<int, ResultRow>? _results;

    private Dictionary<int, ResultRow> LoadResults()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT fixture_id,home_goals,away_goals,stats_json,screenshot_path FROM results";
        using var reader = cmd.ExecuteReader();
        var dict = new Dictionary<int, ResultRow>();
        while (reader.Read())
        {
            dict[reader.GetInt32(0)] = new ResultRow
            {
                FixtureId = reader.GetInt32(0),
                HomeGoals = reader.GetInt32(1),
                AwayGoals = reader.GetInt32(2),
                StatsJson = reader.IsDBNull(3) ? null : reader.GetString(3),
                ScreenshotPath = reader.IsDBNull(4) ? null : reader.GetString(4),
            };
        }
        return dict;
    }

    /// <summary>Distinct, standard-looking formation shapes available in the DB, as (label, id).</summary>
    public IReadOnlyList<(string Shape, int Id)> FormationOptions()
    {
        var byFormation = new Dictionary<int, List<int>>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT formation_id, y FROM formation_slots ORDER BY formation_id, y";
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                var fid = r.GetInt32(0);
                if (!byFormation.TryGetValue(fid, out var list)) byFormation[fid] = list = new();
                list.Add(r.GetInt32(1));
            }
        }
        var byShape = new Dictionary<string, int>();
        foreach (var (fid, ys) in byFormation)
        {
            var shape = Formations.ShapeOf(ys);
            if (Formations.IsStandard(shape) && !byShape.ContainsKey(shape))
                byShape[shape] = fid;
        }
        return byShape.Select(kv => (kv.Key, kv.Value))
                      .OrderByDescending(x => x.Key.Length).ThenBy(x => x.Key).ToList();
    }

    // ------------------------------------------------------------------ tactics ownership
    //
    // Every club OWNS its two formation records (fid pair: phase 0 = Main, phase 1 = the in-game
    // Sub-Tactic). Tactics edits rewrite the geometry of the owner's own fids in place;
    // team_tactics.formation_id is NEVER repointed at another formation — repointing at shared
    // geometry was the legacy (corrupting) model.

    private const int FormationBase = 910_000;

    // 4-4-2 used only when a legacy formation has no readable geometry to copy.
    private static readonly (int Role, int X, int Y)[] Default442 =
    {
        (0, 52, 3), (2, 16, 15), (1, 40, 13), (1, 64, 13), (3, 88, 15),
        (6, 16, 28), (5, 42, 26), (5, 62, 26), (7, 88, 28), (12, 42, 40), (12, 62, 40),
    };

    /// <summary>The managed club's own (Main, Sub) formation ids from team_tactics.</summary>
    public (int Fid0, int Fid1) OwnFormationIds() => OwnFormationIds(CurrentTeamId);

    private (int Fid0, int Fid1) OwnFormationIds(int teamId)
    {
        var tactics = Repo.TeamTactics(teamId);
        var fid0 = tactics.FirstOrDefault(t => t.Phase == 0)?.FormationId
                   ?? tactics.FirstOrDefault()?.FormationId ?? 0;
        var fid1 = tactics.FirstOrDefault(t => t.Phase == 1)?.FormationId ?? fid0;
        return (fid0, fid1);
    }

    /// <summary>
    /// Legacy careers pointed every club at ONE shared catalogue formation id (or at ids below
    /// the career block). Give each career club its own pair by copying whatever geometry it
    /// currently points at, then repair team_tactics. Pure DB — no game files touched.
    /// </summary>
    private void HealLegacyFormationOwnership()
    {
        var career = Repo.Teams()
            .Where(t => t.LeagueId is TopFlight or Division2 && t.Id >= 800_000)
            .OrderBy(t => t.Id).ToList();
        if (career.Count == 0) return;

        var claimed = new HashSet<int>();
        foreach (var team in career)
        {
            var tactics = Repo.TeamTactics(team.Id);
            var fid0 = tactics.FirstOrDefault(t => t.Phase == 0)?.FormationId ?? 0;
            var fid1 = tactics.FirstOrDefault(t => t.Phase == 1)?.FormationId ?? 0;
            var ownsPair = fid0 >= FormationBase && fid1 >= FormationBase && fid0 != fid1
                           && !claimed.Contains(fid0) && !claimed.Contains(fid1);
            if (ownsPair)
            {
                claimed.Add(fid0);
                claimed.Add(fid1);
                continue;
            }

            // Same allocation formula as the seeder: deterministic, injective per team id.
            var own0 = FormationBase + (team.Id - 800_000) * 2;
            var style0 = tactics.FirstOrDefault(t => t.Phase == 0)?.Style ?? 0;
            var style1 = tactics.FirstOrDefault(t => t.Phase == 1)?.Style ?? style0;
            CopyFormationGeometry(fid0, own0);
            CopyFormationGeometry(fid1 != 0 ? fid1 : fid0, own0 + 1);
            Repo.SetTeamTactics(new TeamTacticsRow
            { TeamId = team.Id, Phase = 0, FormationId = own0, Style = style0 });
            Repo.SetTeamTactics(new TeamTacticsRow
            { TeamId = team.Id, Phase = 1, FormationId = own0 + 1, Style = style1 });
            claimed.Add(own0);
            claimed.Add(own0 + 1);
        }
    }

    private void CopyFormationGeometry(int sourceFid, int destFid)
    {
        var source = sourceFid > 0
            ? Repo.FormationSlots(sourceFid).OrderBy(s => s.SlotIndex).ToList()
            : new List<FormationSlotRow>();
        var slots = source.Count == 11
            ? source.Select(s => new FormationSlotRow
            { FormationId = destFid, SlotIndex = s.SlotIndex, Position = s.Position, X = s.X, Y = s.Y })
            : Default442.Select((s, ix) => new FormationSlotRow
            { FormationId = destFid, SlotIndex = ix, Position = s.Role, X = s.X, Y = s.Y });
        var list = slots.ToList();
        var shape = Formations.ShapeOf(list.Select(s => s.Y));
        Repo.UpsertFormation(
            new FormationRow { Id = destFid, Name = Formations.IsStandard(shape) ? shape : "Custom" },
            list);
    }

    /// <summary>
    /// Sign a player to the managed club — add them to the squad. If they exist in eFootball, the
    /// match reconcile puts their real record (real face/rating) into your team; a squad that grows
    /// past 32 drops its lowest-rated reserve so it stays legal.
    /// </summary>
    public string SignPlayer(int playerId)
    {
        var squad = Repo.Squad(CurrentTeamId);
        if (squad.Any(s => s.PlayerId == playerId))
        {
            return "That player is already in your squad.";
        }

        string name = "player";
        int? rating = null;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT name, overall_rating FROM players WHERE id=$id";
            q.Parameters.AddWithValue("$id", playerId);
            using var r = q.ExecuteReader();
            if (r.Read())
            {
                name = r.GetString(0);
                rating = r.IsDBNull(1) ? null : r.GetInt32(1);
            }
        }

        var used = squad.Select(s => s.SquadNumber).ToHashSet();
        var shirt = Enumerable.Range(1, 99).FirstOrDefault(n => !used.Contains(n), 99);
        Repo.SetSquadMember(new SquadMemberRow
        {
            TeamId = CurrentTeamId, PlayerId = playerId, SquadNumber = shirt, Slot = squad.Count,
        });
        Repo.RecordTransfer(playerId, CurrentTeamId, SeasonId);

        // Trim to a legal size by releasing the weakest reserve.
        var withNew = Repo.SquadPlayers(CurrentTeamId).OrderBy(p => p.OverallRating ?? 0).ToList();
        if (withNew.Count > 32)
        {
            var drop = withNew.First(p => p.Id != playerId);
            Repo.RemoveSquadMember(CurrentTeamId, drop.Id);
        }

        _teamCache = null;
        return $"Signed {name}{(rating is { } v ? $" ({v})" : "")} — squad number {shirt}. " +
               "They'll line up for you on your next match.";
    }

    /// <summary>
    /// Persist the tactics screen into the club's OWN formation-id pair: main geometry + role
    /// codes into fid0; fid1 gets the sub slots when fluid, else a mirror of the main shape.
    /// team_tactics keeps its formation ids — only the style changes. The custom flag tells the
    /// compile to render this shape onto the in-game team's own fids.
    /// </summary>
    public void SaveCustomFormation(
        int styleIndex, bool fluid,
        IReadOnlyList<(int Index, int PlayerId, string Position, string Role, int X, int Y)> mainSlots,
        IReadOnlyList<(int Index, int PlayerId, string Position, string Role, int X, int Y)>? subSlots)
    {
        var (fid0, fid1) = OwnFormationIds();
        WriteFormation(fid0, mainSlots);
        WriteFormation(fid1, fluid && subSlots is not null ? subSlots : mainSlots);

        // Only the style moves; formation_id stays the club's own pair (never repointed).
        foreach (var t in Repo.TeamTactics(CurrentTeamId))
        {
            Repo.SetTeamTactics(t with { Style = styleIndex });
        }

        SetMeta($"tactics_custom_{CurrentTeamId}", "1");
        SetMeta($"tactics_fluid_{CurrentTeamId}", fluid ? "1" : "0");

        // Persist each player's chosen role — the compile writes it into Player.bin in-game.
        foreach (var sl in mainSlots)
        {
            PersistRole(sl.PlayerId, sl.Role);
        }
    }

    private void WriteFormation(
        int fid, IReadOnlyList<(int Index, int PlayerId, string Position, string Role, int X, int Y)> slots)
    {
        if (fid <= 0 || slots.Count == 0) return;
        var rows = slots.Select(s => new FormationSlotRow
        {
            FormationId = fid, SlotIndex = s.Index,
            Position = Visuals.LabelRoleCode(s.Position), X = s.X, Y = s.Y,
        }).ToList();
        var shape = Formations.ShapeOf(rows.Select(r => r.Y));
        Repo.UpsertFormation(
            new FormationRow { Id = fid, Name = Formations.IsStandard(shape) ? shape : "Custom" },
            rows);
    }

    private void PersistRole(int playerId, string role)
    {
        if (playerId <= 0) return;
        using (var del = Db.Connection.CreateCommand())
        {
            del.CommandText = "DELETE FROM player_playstyles WHERE player_id=$p";
            del.Parameters.AddWithValue("$p", playerId);
            del.ExecuteNonQuery();
        }
        // "Basic" (and the legacy "Balanced") mean no specialised style — the delete alone.
        if (string.IsNullOrWhiteSpace(role) || role is "Basic" or "Balanced") return;
        using var ins = Db.Connection.CreateCommand();
        ins.CommandText = "INSERT INTO player_playstyles(player_id,playstyle) VALUES($p,$r)";
        ins.Parameters.AddWithValue("$p", playerId);
        ins.Parameters.AddWithValue("$r", role);
        ins.ExecuteNonQuery();
    }

    /// <summary>A player's saved role (playstyle) — "Basic" when none is set.</summary>
    public string RoleOf(int playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT playstyle FROM player_playstyles WHERE player_id=$p LIMIT 1";
        cmd.Parameters.AddWithValue("$p", playerId);
        return cmd.ExecuteScalar() as string ?? "Basic";
    }

    /// <summary>Whether the club last saved with a fluid (distinct Sub) shape.</summary>
    public bool SavedFluid() => GetMeta($"tactics_fluid_{CurrentTeamId}") == "1";

    // ------------------------------------------------------------- condition + AI selection

    /// <summary>
    /// AI matchday selection for BOTH clubs of the fixture: every manager picks an XI from
    /// rating, fatigue, form and availability against their own Main formation's slot
    /// categories, and the full order is persisted into squad_members.slot (0..10 = the XI in
    /// formation-slot order) so the compile and the game see the same team sheet.
    /// </summary>
    public void PrepareMatchday(int homeTeamId, int awayTeamId, int matchday)
    {
        foreach (var teamId in new[] { homeTeamId, awayTeamId })
        {
            var conditions = Repo.ConditionsFor(teamId).ToDictionary(c => c.PlayerId);
            bool InjuredNow(int pid) =>
                conditions.TryGetValue(pid, out var c) && c.InjuredUntilMd is int u && u >= matchday;

            // Your hand-picked XI is respected: the AI only steps in for players who are out.
            if (teamId == CurrentTeamId && ManualXi)
            {
                var members = Repo.Squad(teamId).OrderBy(m => m.Slot).ToList();
                var starters = members.Where(m => m.Slot is >= 0 and <= 10).ToList();
                var benchFit = members.Where(m => m.Slot > 10 && !InjuredNow(m.PlayerId))
                    .Select(m => m.PlayerId).ToList();
                foreach (var hurt in starters.Where(m => InjuredNow(m.PlayerId)))
                {
                    if (benchFit.Count == 0) break;
                    var sub = benchFit[0];
                    benchFit.RemoveAt(0);
                    SwapSlots(teamId, hurt.PlayerId, sub);
                }
                continue;
            }

            var (fid0, _) = OwnFormationIds(teamId);
            var slotPositions = Repo.FormationSlots(fid0)
                .OrderBy(s => s.SlotIndex)
                .Select(s => Visuals.RoleCodeLabel(s.Position))
                .ToList();
            if (slotPositions.Count == 0) continue;

            var squad = Repo.SquadPlayers(teamId).Select(p =>
            {
                conditions.TryGetValue(p.Id, out var c);
                var form = c?.Form ?? 6.5;
                if (teamId == CurrentTeamId) form += MoraleFormAdjustment(p.Id);   // morale pulls
                return new CandidatePlayer(
                    p.Id, p.OverallRating ?? 70, Visuals.PositionCategory(p.Position),
                    c?.Fatigue ?? 0, form, InjuredNow(p.Id));
            }).ToList();
            if (squad.Count == 0) continue;

            // Position-aware pick: registered + learned positions vs the formation's exact slots.
            var registered = Repo.SquadPlayers(teamId).ToDictionary(p => p.Id, p => p.Position);
            var order = XiSelector.SelectOrder(squad, slotPositions,
                pid => (registered.GetValueOrDefault(pid, "CMF"),
                        (IReadOnlyCollection<string>)LearnedPositions(pid)));
            using var tx = Db.Connection.BeginTransaction();
            for (var i = 0; i < order.Count; i++)
            {
                using var cmd = Db.Connection.CreateCommand();
                cmd.Transaction = tx;   // Microsoft.Data.Sqlite requires it while a transaction is pending
                cmd.CommandText = "UPDATE squad_members SET slot=$s WHERE team_id=$t AND player_id=$p";
                cmd.Parameters.AddWithValue("$s", i);
                cmd.Parameters.AddWithValue("$t", teamId);
                cmd.Parameters.AddWithValue("$p", order[i]);
                cmd.ExecuteNonQuery();
            }
            tx.Commit();
        }
    }

    private void SwapSlots(int teamId, int playerA, int playerB)
    {
        var members = Repo.Squad(teamId);
        var a = members.FirstOrDefault(m => m.PlayerId == playerA);
        var b = members.FirstOrDefault(m => m.PlayerId == playerB);
        if (a is null || b is null) return;
        using var tx = Db.Connection.BeginTransaction();
        foreach (var (pid, slot) in new[] { (playerA, b.Slot), (playerB, a.Slot) })
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.Transaction = tx;
            cmd.CommandText = "UPDATE squad_members SET slot=$s WHERE team_id=$t AND player_id=$p";
            cmd.Parameters.AddWithValue("$s", slot);
            cmd.Parameters.AddWithValue("$t", teamId);
            cmd.Parameters.AddWithValue("$p", pid);
            cmd.ExecuteNonQuery();
        }
        tx.Commit();
    }

    /// <summary>
    /// One condition pass for every club in both divisions after a matchday's results are in:
    /// everyone recovers, that day's starters pick up fatigue and injury risk, and form follows
    /// the result. Guarded by a meta flag so re-recording a score never double-applies.
    /// </summary>
    public void UpdateConditionsAfterMatchday(int matchday)
    {
        var guard = $"cond_applied_{SeasonId}_{matchday}";
        if (GetMeta(guard) is not null) return;

        var fixtures = Repo.Fixtures(SeasonId, matchday);
        foreach (var team in Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2))
        {
            var fx = fixtures.FirstOrDefault(
                f => f.HomeTeamId == team.Id || f.AwayTeamId == team.Id);
            int? outcome = null;
            if (fx is not null && fx.Played && ResultFor(fx.Id) is { } r)
            {
                var us = fx.HomeTeamId == team.Id ? r.HomeGoals : r.AwayGoals;
                var them = fx.HomeTeamId == team.Id ? r.AwayGoals : r.HomeGoals;
                outcome = us > them ? 1 : us == them ? 0 : -1;
            }

            var conditions = Repo.ConditionsFor(team.Id).ToDictionary(c => c.PlayerId);
            foreach (var member in Repo.Squad(team.Id))
            {
                conditions.TryGetValue(member.PlayerId, out var c);
                var fatigue = ConditionModel.AfterRest(c?.Fatigue ?? 0);
                var injuredUntil = c?.InjuredUntilMd;
                var form = c?.Form ?? 6.5;
                if (outcome is { } o)
                {
                    if (member.Slot is >= 0 and <= 10)   // that matchday's starters
                    {
                        fatigue = ConditionModel.AfterStart(fatigue);
                        var rolled = RollInjury(matchday, member.PlayerId);
                        if (rolled is { } until)
                        {
                            // Your physio gets YOUR players back sooner (never below next matchday).
                            if (team.Id == CurrentTeamId)
                            {
                                until = Math.Max(matchday + 1, until - PhysioRecoveryBonus());
                            }
                            injuredUntil = until;
                        }
                    }
                    form = ConditionModel.FormAfterResult(form, o);
                }
                Repo.UpsertCondition(new PlayerConditionRow
                {
                    PlayerId = member.PlayerId, Fatigue = fatigue,
                    InjuredUntilMd = injuredUntil, Form = form,
                });
            }
        }
        RunWeeklyEconomy(matchday, fixtures);
        SetMeta(guard, "1");
    }

    /// <summary>Injury roll honouring the Settings frequency (Low halves, High adds a chance).</summary>
    internal int? RollInjury(int matchday, int playerId)
    {
        var rolled = ConditionModel.InjuryRoll(SeasonId, matchday, playerId);
        return (GetMeta("injury_freq") ?? "Normal") switch
        {
            "Low" => (playerId & 1) == 0 ? rolled : null,
            "High" => rolled ?? ConditionModel.InjuryRoll(SeasonId ^ 0x5A5A, matchday, playerId),
            _ => rolled,
        };
    }

    /// <summary>
    /// Everything that happens every matchWEEK regardless of competition: loans collect, the
    /// training ground works, scouts report, morale moves, wages go out, gate money comes in.
    /// Called from both the league pass and the cup pass — cup weeks used to silently skip
    /// the entire weekly economy (P0 fix).
    /// </summary>
    private void RunWeeklyEconomy(int matchday, IReadOnlyList<FixtureRow> fixtures)
    {
        RepayLoanInstalment();   // the bank collects every matchweek
        var trainingNotes = ApplyTraining().ToList();   // the training ground works every matchweek
        try { trainingNotes.AddRange(AdvanceSkillTraining()); }   // skill work ticks too (P1)
        catch { /* skills never block the weekly pass */ }
        LastTrainingNotes = trainingNotes;
        try { CheckScoutJobs(matchday); } catch { /* scouting is optional */ }

        // Morale follows the matchweek for YOUR squad (minutes, result, list status).
        try
        {
            var myFx = fixtures.FirstOrDefault(
                f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && f.Played);
            int? myOutcome = null;
            if (myFx is not null && ResultFor(myFx.Id) is { } mr)
            {
                var us = myFx.HomeTeamId == CurrentTeamId ? mr.HomeGoals : mr.AwayGoals;
                var them = myFx.HomeTeamId == CurrentTeamId ? mr.AwayGoals : mr.HomeGoals;
                myOutcome = us > them ? 1 : us == them ? 0 : -1;
            }
            UpdateMoraleAfterMatchday(matchday, myOutcome);
        }
        catch { /* morale never blocks the matchday pass */ }

        // The weekly economy: wages out every matchweek, gate receipts in when you play at home.
        var (_, _, weeklyWages) = FinancialOverview();
        Finances.PayWages(weeklyWages);
        var home = fixtures.FirstOrDefault(f => f.HomeTeamId == CurrentTeamId && f.Played);
        if (home is not null)
        {
            var attendance = Math.Clamp(8000 + (EloOf(CurrentTeamId) - 1450) * 30, 4000, 60000);
            Finances.RecordMatchday(attendance, 24);
        }
        SyncBudget();
        try { MidSeasonReview(matchday); } catch { /* the review never blocks the pass */ }
        try { RunDeadlineDay(matchday); } catch { /* deadline drama never blocks the pass */ }
        try { EvaluatePlayingTime(matchday); } catch { /* playing time never blocks the pass */ }

        // Weekly history snapshot (item 11): the trend charts read this series.
        try { RecordClubHistory(matchday); }
        catch { /* history never blocks the pass */ }

        // International breaks (item 5): after MDs 4/9/14/25 your stars fly off and come home
        // leggy. The best players in the squad pick up extra fatigue; a letter says who.
        try { ApplyInternationalBreak(matchday); }
        catch { /* call-ups never block the pass */ }

        // The January window: mid-season market activity + fresh offers for your players.
        if (matchday == 17 && GetMeta($"jan_{SeasonId}") is null)
        {
            CpuTransferActivityMidSeason();
            PostInbox("Transfer", "The January window is open",
                "Clubs are shopping until matchday 19. Offers for your listed players are in on the " +
                "Market screen, and the free-agent pool is live.", matchday);
            SetMeta($"jan_{SeasonId}", "1");
        }
    }

    /// <summary>One snapshot per matchday pass: money, fans, board, ELO (item 11 charts).</summary>
    private void RecordClubHistory(int matchday)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "INSERT OR REPLACE INTO club_history(season_id, matchday, team_id, balance, fans, board, elo) " +
            "VALUES($s, $m, $t, $bal, $fans, $board, $elo)";
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$m", matchday);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.Parameters.AddWithValue("$bal", Finances.Balance);
        cmd.Parameters.AddWithValue("$fans", FanHappiness());
        cmd.Parameters.AddWithValue("$board", Board.Value);
        cmd.Parameters.AddWithValue("$elo", EloOf(CurrentTeamId));
        cmd.ExecuteNonQuery();
    }

    /// <summary>The stored weekly series for one column of club_history, oldest first.</summary>
    public IReadOnlyList<long> ClubHistorySeries(string column)
    {
        if (column is not ("balance" or "fans" or "board" or "elo"))
            throw new ArgumentException("unknown history column", nameof(column));
        var rows = new List<long>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = $"SELECT {column} FROM club_history WHERE team_id=$t " +
                          "ORDER BY season_id, matchday";
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add(r.GetInt64(0));
        return rows;
    }

    /// <summary>FIFA windows, roughly: Sept, Oct, Nov and the late-March window.</summary>
    public static readonly int[] InternationalBreakMatchdays = { 4, 9, 14, 25 };

    /// <summary>Your best players get called up after these matchdays and come home leggy.</summary>
    private void ApplyInternationalBreak(int matchday)
    {
        if (!InternationalBreakMatchdays.Contains(matchday)) return;
        if (GetMeta($"intbreak_{SeasonId}_{matchday}") is not null) return;
        SetMeta($"intbreak_{SeasonId}_{matchday}", "1");

        // Call-ups: everyone rated 78+, capped at the six best (a small club may send none).
        var called = Repo.SquadPlayers(CurrentTeamId)
            .Where(p => (p.OverallRating ?? 0) >= 78)
            .OrderByDescending(p => p.OverallRating)
            .Take(6).ToList();
        if (called.Count == 0) return;
        foreach (var p in called)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText =
                "INSERT INTO player_condition(player_id, fatigue) VALUES($p, 12) " +
                "ON CONFLICT(player_id) DO UPDATE SET fatigue = MIN(100, fatigue + 12)";
            cmd.Parameters.AddWithValue("$p", p.Id);
            cmd.ExecuteNonQuery();
        }
        PostInbox("Club", "International break — call-ups",
            "Country comes calling. Away on duty this window:\n" +
            string.Join("\n", called.Select(p => $"• {p.Name} ({p.OverallRating})")) +
            "\nThey return with heavier legs — rotate or manage their minutes next matchday.",
            matchday);
    }

    /// <summary>What the training ground produced on the last matchday pass (for the UI).</summary>
    public IReadOnlyList<string> LastTrainingNotes { get; private set; } = Array.Empty<string>();

    public IReadOnlyList<(PlayerRow Player, SquadMemberRow Slot)> Squad()
    {
        var players = Repo.SquadPlayers(CurrentTeamId).ToDictionary(p => p.Id);
        return Repo.Squad(CurrentTeamId)
            .Where(s => players.ContainsKey(s.PlayerId))
            .Select(s => (players[s.PlayerId], s))
            .ToList();
    }
}
