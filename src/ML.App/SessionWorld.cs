using ML.Core;
using ML.Core.Management;
using ML.Core.Selection;
using ML.Core.Simulation;
using ML.Data;
using Microsoft.Data.Sqlite;

namespace ML.App;

/// <summary>
/// The world systems around the league: the knockout cup, ELO ratings and match previews, the
/// CPU transfer market, academy intakes, the bank, fans feeling, the chairman and the Roll of
/// Honour. Together with the league loop these are the MFL/RFS parity features.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ ELO + match preview

    private Dictionary<int, int>? _elos;

    /// <summary>
    /// ELO per career club, replayed from every recorded result in fixture order (all seasons),
    /// so ratings carry a club's whole history like MFL's do.
    /// </summary>
    private Dictionary<int, int> Elos()
    {
        if (_elos is not null) return _elos;
        var elos = Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2 or CupLeague)
            .ToDictionary(t => t.Id, _ => EloRating.Default);
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT f.home_team_id, f.away_team_id, r.home_goals, r.away_goals FROM fixtures f " +
            "JOIN results r ON r.fixture_id = f.id ORDER BY f.season_id, f.matchday, f.id";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            int home = reader.GetInt32(0), away = reader.GetInt32(1);
            if (!elos.ContainsKey(home) || !elos.ContainsKey(away)) continue;
            var (dh, da) = EloRating.Update(
                elos[home], elos[away], EloRating.ActualScore(reader.GetInt32(2), reader.GetInt32(3)));
            elos[home] += dh;
            elos[away] += da;
        }
        return _elos = elos;
    }

    public int EloOf(int teamId) => Elos().TryGetValue(teamId, out var e) ? e : EloRating.Default;

    /// <summary>
    /// Your club's ELO after each of its recorded games, across every season on file —
    /// the club's whole trajectory for the Board trend chart (P6). Derived, not stored.
    /// </summary>
    public IReadOnlyList<int> EloHistoryOfCurrentClub()
    {
        var elos = Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2 or CupLeague)
            .ToDictionary(t => t.Id, _ => EloRating.Default);
        var history = new List<int> { EloRating.Default };
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT f.home_team_id, f.away_team_id, r.home_goals, r.away_goals FROM fixtures f " +
            "JOIN results r ON r.fixture_id = f.id ORDER BY f.season_id, f.matchday, f.id";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            int home = reader.GetInt32(0), away = reader.GetInt32(1);
            if (!elos.ContainsKey(home) || !elos.ContainsKey(away)) continue;
            var (dh, da) = EloRating.Update(
                elos[home], elos[away], EloRating.ActualScore(reader.GetInt32(2), reader.GetInt32(3)));
            elos[home] += dh;
            elos[away] += da;
            if (home == CurrentTeamId || away == CurrentTeamId)
            {
                history.Add(elos[CurrentTeamId]);
            }
        }
        return history;
    }

    /// <summary>Win/draw/loss percentages for a fixture, from the two clubs' ELO ratings.</summary>
    public EloRating.Outlook MatchOdds(int homeTeamId, int awayTeamId) =>
        EloRating.Preview(EloOf(homeTeamId), EloOf(awayTeamId));

    /// <summary>MFL-style club status tier, driven by ELO.</summary>
    public string ClubTier(int teamId) => EloOf(teamId) switch
    {
        >= 1580 => "Elite",
        >= 1520 => "Established",
        >= 1470 => "Solid",
        _ => "Emerging",
    };

    /// <summary>A club's key player (their best-rated) for the match preview card.</summary>
    public PlayerRow? KeyPlayer(int teamId) =>
        Repo.SquadPlayers(teamId).OrderByDescending(p => p.OverallRating ?? 0).FirstOrDefault();

    // ------------------------------------------------------------------ fans + chairman

    /// <summary>
    /// Fans feeling 0-100: position against a playoff expectation plus recent form. The third
    /// gauge alongside board confidence and morale.
    /// </summary>
    public int FansFeeling()
    {
        var pos = CurrentPosition();
        var teams = Math.Max(LeagueTeams().Count, 2);
        var expected = Math.Max(teams / 3, 1);           // fans expect the top third
        var positional = pos == 0 ? 0 : (expected - pos) * 5;
        var formPts = 0;
        foreach (var f in RecentResults())
        {
            if (ResultFor(f.Id) is not { } r) continue;
            var us = f.HomeTeamId == CurrentTeamId ? r.HomeGoals : r.AwayGoals;
            var them = f.HomeTeamId == CurrentTeamId ? r.AwayGoals : r.HomeGoals;
            formPts += us > them ? 3 : us == them ? 1 : 0;
        }
        return Math.Clamp(52 + positional + (formPts - 7) * 3, 5, 95);
    }

    private static readonly string[] ChairFirst =
        { "Victor", "Harold", "Dragan", "Marcus", "Terence", "Roman", "Edward", "Salvatore", "Klaus", "Bernard" };
    private static readonly string[] ChairLast =
        { "Ashworth", "Pemberton", "Stankovic", "Whitmore", "Delacroix", "Hargreaves", "Moretti", "Lindqvist", "Osei", "Radcliffe" };

    /// <summary>The club's chairman — generated once per club, then stable for the whole save.</summary>
    public string Chairman()
    {
        var key = $"chairman_{CurrentTeamId}";
        if (GetMeta(key) is { } existing) return existing;
        var seed = CurrentTeamId * 2654435761u;
        var name = $"{ChairFirst[(int)(seed % 10)]} {ChairLast[(int)(seed / 10 % 10)]}";
        SetMeta(key, name);
        return name;
    }

    // ------------------------------------------------------------------ the cups (D1: two of them)

    public sealed record CupSpec(int LeagueId, string Name, (int Size, int Matchday, string RoundName)[] Rounds, int Salt);

    public const int CupLeague = 9002;
    public const string CupName = "National Cup";
    public const int LeagueCupId = 9003;
    public const string LeagueCupName = "League Cup";
    public const int ContinentalId = 9004;
    public const string ContinentalName = "Continental Cup";

    /// <summary>All knockouts: distinct midweek matchday tracks so rounds never collide.
    /// The Continental Cup is the eight-team elite tier — last season's top two qualify,
    /// the rest enter on rating (Elos).</summary>
    public static readonly CupSpec[] Cups =
    {
        new(CupLeague, CupName, new[]
        {
            (32, 8, "Round of 32"), (16, 15, "Round of 16"), (8, 22, "Quarter-final"),
            (4, 29, "Semi-final"), (2, 33, "Final"),
        }, 31337),
        new(LeagueCupId, LeagueCupName, new[]
        {
            (32, 5, "Round of 32"), (16, 11, "Round of 16"), (8, 19, "Quarter-final"),
            (4, 26, "Semi-final"), (2, 31, "Final"),
        }, 74747),
        new(ContinentalId, ContinentalName, new[]
        {
            (8, 13, "Quarter-final"), (4, 21, "Semi-final"), (2, 35, "Final"),
        }, 55511),
    };

    public static string CupRoundName(int matchday) =>
        Cups.SelectMany(c => c.Rounds).FirstOrDefault(r => r.Matchday == matchday).RoundName ?? "Cup";

    /// <summary>The competition name for a cup fixture (by its league id).</summary>
    public static string CupNameFor(int leagueId) =>
        Cups.FirstOrDefault(c => c.LeagueId == leagueId)?.Name ?? CupName;

    /// <summary>Draw any cup not yet drawn this season: 32 clubs each, independently shuffled.</summary>
    private void EnsureCup()
    {
        var clubs = Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2).Select(t => t.Id).ToList();
        if (clubs.Count < 4) return;
        foreach (var cup in Cups)
        {
            if (Repo.Fixtures(SeasonId).Any(f => f.Kind == "cup" && f.LeagueId == cup.LeagueId)) continue;
            Repo.UpsertLeague(new LeagueRow { Id = cup.LeagueId, Name = cup.Name, Tier = 0 });
            var rng = new SeededRandom((SeasonId * cup.Salt + 11) ^ WorldSeed);
            List<int> entrants;
            if (cup.LeagueId == ContinentalId)
            {
                // Elite entry: last season's qualifiers first, ELO fills the rest of the 8.
                var qualified = new List<int>();
                if (GetMeta($"continental_{SeasonId}") is { } q)
                {
                    foreach (var part in q.Split(','))
                    {
                        if (int.TryParse(part, out var tid) && clubs.Contains(tid)) qualified.Add(tid);
                    }
                }
                entrants = qualified
                    .Concat(clubs.Where(c => !qualified.Contains(c))
                        .OrderByDescending(EloOf))
                    .Take(8)
                    .OrderBy(_ => rng.Next(1_000_000))
                    .ToList();
            }
            else
            {
                entrants = clubs.OrderBy(_ => rng.Next(1_000_000)).Take(32).ToList();
            }
            var nextId = NextFixtureId();
            for (var i = 0; i + 1 < entrants.Count; i += 2)
            {
                Repo.AddFixture(new FixtureRow
                {
                    Id = nextId++, SeasonId = SeasonId, LeagueId = cup.LeagueId,
                    Matchday = cup.Rounds[0].Matchday,
                    HomeTeamId = entrants[i], AwayTeamId = entrants[i + 1], Kind = "cup", Played = false,
                });
            }
        }
    }

    /// <summary>Winner of a played cup tie; drawn ties go to penalties, decided once, seeded.</summary>
    public int CupWinnerOf(FixtureRow f)
    {
        var r = ResultFor(f.Id);
        if (r is null) return f.HomeTeamId;
        if (r.HomeGoals != r.AwayGoals) return r.HomeGoals > r.AwayGoals ? f.HomeTeamId : f.AwayTeamId;
        var key = $"cup_pens_{f.Id}";
        if (GetMeta(key) is { } stored && int.TryParse(stored, out var winner)) return winner;
        var decided = new SeededRandom((f.Id * 48271 + SeasonId) ^ WorldSeed).Next(2) == 0 ? f.HomeTeamId : f.AwayTeamId;
        SetMeta(key, decided.ToString());
        return decided;
    }

    /// <summary>
    /// Sim the remaining ties on a cup matchday (whichever cup owns it) and draw the next round
    /// once complete. Call after recording any result on that matchday.
    /// </summary>
    public void AdvanceCup(int matchday, int exceptFixtureId)
    {
        foreach (var cup in Cups)
        {
            var ix = Array.FindIndex(cup.Rounds, r => r.Matchday == matchday);
            if (ix < 0) continue;

            var cupRng = new SeededRandom((SeasonId * 5171 + matchday + cup.Salt) ^ WorldSeed);
            var sim = new PoissonMatchSimulator(cupRng);
            foreach (var f in Repo.Fixtures(SeasonId, matchday)
                         .Where(f => f.Kind == "cup" && f.LeagueId == cup.LeagueId
                                     && !f.Played && f.Id != exceptFixtureId))
            {
                var h = XiStrengthOf(f.HomeTeamId);
                var a = XiStrengthOf(f.AwayTeamId);
                var r = sim.Simulate(new TeamStrength(h.Attack + 1.5, h.Defence),
                                     new TeamStrength(a.Attack, a.Defence));
                Repo.RecordResult(new ResultRow { FixtureId = f.Id, HomeGoals = r.HomeGoals, AwayGoals = r.AwayGoals });
                AttributeSimmedMatch(f.Id, f.HomeTeamId, f.AwayTeamId, r.HomeGoals, r.AwayGoals, cupRng);
            }
            _results = null;
            _elos = null;

            var ties = Repo.Fixtures(SeasonId, matchday)
                .Where(f => f.Kind == "cup" && f.LeagueId == cup.LeagueId).OrderBy(f => f.Id).ToList();
            if (ties.Count == 0 || ties.Any(f => !f.Played)) continue;

            var winners = ties.Select(CupWinnerOf).ToList();
            if (ix + 1 >= cup.Rounds.Length)
            {
                SetMeta($"cup_winner_{cup.LeagueId}_{SeasonId}", winners[0].ToString());
                continue;
            }
            if (Repo.Fixtures(SeasonId, cup.Rounds[ix + 1].Matchday)
                    .Any(f => f.Kind == "cup" && f.LeagueId == cup.LeagueId)) continue;

            var nextId = NextFixtureId();
            for (var i = 0; i + 1 < winners.Count; i += 2)
            {
                Repo.AddFixture(new FixtureRow
                {
                    Id = nextId++, SeasonId = SeasonId, LeagueId = cup.LeagueId,
                    Matchday = cup.Rounds[ix + 1].Matchday,
                    HomeTeamId = winners[i], AwayTeamId = winners[i + 1], Kind = "cup", Played = false,
                });
            }
        }
    }

    /// <summary>One cup's ties grouped by round, first round first.</summary>
    public IReadOnlyList<(string Round, IReadOnlyList<FixtureRow> Ties)> CupDrawFor(int cupLeagueId) =>
        Repo.Fixtures(SeasonId).Where(f => f.Kind == "cup" && f.LeagueId == cupLeagueId)
            .GroupBy(f => f.Matchday).OrderBy(g => g.Key)
            .Select(g => (CupRoundName(g.Key), (IReadOnlyList<FixtureRow>)g.OrderBy(f => f.Id).ToList()))
            .ToList();

    /// <summary>Finish every cup with sims (rollover safety — every trophy has a winner).</summary>
    private void CompleteCup()
    {
        foreach (var cup in Cups)
        {
            foreach (var round in cup.Rounds)
            {
                AdvanceCup(round.Matchday, exceptFixtureId: -1);
            }
        }
    }

    // ------------------------------------------------------------------ prize money + Europe (D1)

    /// <summary>
    /// Rollover payouts: league position money for every club (top flight £2m→£400k, Division 2
    /// half), cup winners £750k/£400k, and continental qualification flags for the top two —
    /// your club's money flows through Finances and lands in the inbox.
    /// </summary>
    private void PayPrizesAndFlagEurope(
        IReadOnlyList<ML.Core.Tables.LeagueTableRow> top,
        IReadOnlyList<ML.Core.Tables.LeagueTableRow> second)
    {
        void Pay(int teamId, long amount)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText = "UPDATE teams SET budget = budget + $a WHERE id=$t";
            cmd.Parameters.AddWithValue("$a", amount);
            cmd.Parameters.AddWithValue("$t", teamId);
            cmd.ExecuteNonQuery();
            if (teamId == CurrentTeamId) Finances.ReceivePrize(amount);
        }

        long mine = 0;
        foreach (var (table, scale) in new[] { (top, 1.0), (second, 0.5) })
        {
            var n = Math.Max(table.Count, 1);
            foreach (var row in table)
            {
                var amount = (long)((12_000_000 - (row.Position - 1) * (9_500_000 / Math.Max(n - 1, 1))) * scale);
                amount = Math.Max(amount, 1_500_000);
                Pay(row.TeamId.Value, amount);
                if (row.TeamId.Value == CurrentTeamId) mine += amount;
            }
        }
        foreach (var cup in Cups)
        {
            if (GetMeta($"cup_winner_{cup.LeagueId}_{SeasonId}") is { } w && int.TryParse(w, out var wid))
            {
                var amount = cup.LeagueId == CupLeague ? 4_000_000L
                    : cup.LeagueId == ContinentalId ? 10_000_000L : 2_000_000L;
                Pay(wid, amount);
                if (wid == CurrentTeamId) mine += amount;
            }
        }

        // Continental football for the top two — a flag and a headline, honestly no fixtures.
        var europe = top.Take(2).Select(r => r.TeamId.Value).ToList();
        SetMeta($"continental_{SeasonId + 1}", string.Join(",", europe));
        if (europe.Contains(CurrentTeamId))
        {
            PostInbox("Board", "CONTINENTAL FOOTBALL!",
                "A top-two finish takes the club into continental competition next season — " +
                "prestige, and the board's expectations rise with it.");
        }
        if (mine > 0)
        {
            PostInbox("Board", "Season prize money",
                $"£{mine:N0} banked from league position and cup runs. It's in the budget.");
        }
    }

    // ------------------------------------------------------------------ honours

    private void RecordHonours(
        IReadOnlyList<ML.Core.Tables.LeagueTableRow> top,
        IReadOnlyList<ML.Core.Tables.LeagueTableRow> second)
    {
        CompleteCup();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT OR REPLACE INTO honours(season_id,competition,team_id) VALUES($s,$c,$t)";
        void Put(string comp, int teamId)
        {
            cmd.Parameters.Clear();
            cmd.Parameters.AddWithValue("$s", SeasonId);
            cmd.Parameters.AddWithValue("$c", comp);
            cmd.Parameters.AddWithValue("$t", teamId);
            cmd.ExecuteNonQuery();
        }
        if (top.Count > 0) Put("league", top[0].TeamId.Value);
        if (second.Count > 0) Put("division2", second[0].TeamId.Value);
        if (GetMeta($"cup_winner_{CupLeague}_{SeasonId}") is { } cw && int.TryParse(cw, out var cupWinner))
            Put("cup", cupWinner);
        if (GetMeta($"cup_winner_{LeagueCupId}_{SeasonId}") is { } lw && int.TryParse(lw, out var lcupWinner))
            Put("lcup", lcupWinner);
        if (GetMeta($"cup_winner_{ContinentalId}_{SeasonId}") is { } cc && int.TryParse(cc, out var ccWinner))
            Put("ccup", ccWinner);
    }

    /// <summary>
    /// End-of-season awards (P6 depth): Player of the Season, Young Player, Golden Boot —
    /// computed from the season's real data, into the news (with faces) and the honours roll.
    /// </summary>
    private void SeasonAwards()
    {
        var lines = new List<string>();
        int? potsFace = null;

        (int Pid, string Name, double Avg, int Apps)? Best(int? maxAge, int minApps)
        {
            using var cmd = Db.Connection.CreateCommand();
            cmd.CommandText =
                "SELECT r.player_id, p.name, AVG(r.rating) avgr, COUNT(*) n " +
                "FROM player_match_ratings r " +
                "JOIN fixtures f ON f.id = r.fixture_id " +
                "JOIN players p ON p.id = r.player_id " +
                "WHERE f.season_id=$s " + (maxAge is null ? "" : "AND COALESCE(p.age, 25) <= $a ") +
                "GROUP BY r.player_id HAVING n >= $m ORDER BY avgr DESC LIMIT 1";
            cmd.Parameters.AddWithValue("$s", SeasonId);
            if (maxAge is { } a2) cmd.Parameters.AddWithValue("$a", a2);
            cmd.Parameters.AddWithValue("$m", minApps);
            using var r = cmd.ExecuteReader();
            return r.Read() ? (r.GetInt32(0), r.GetString(1), r.GetDouble(2), r.GetInt32(3)) : null;
        }

        if (Best(null, 8) is { } pots)
        {
            lines.Add($"🏅 Player of the Season: {pots.Name} ({pots.Avg:0.00} av over {pots.Apps} rated games)");
            potsFace = pots.Pid;
            using var ins = Db.Connection.CreateCommand();
            ins.CommandText = "INSERT OR REPLACE INTO honours(season_id,competition,team_id) VALUES($s,'pots',$t)";
            ins.Parameters.AddWithValue("$s", SeasonId);
            ins.Parameters.AddWithValue("$t", pots.Pid);   // honours stores the PLAYER for awards
            ins.ExecuteNonQuery();
        }
        if (Best(21, 5) is { } young)
        {
            lines.Add($"⭐ Young Player of the Season: {young.Name} ({young.Avg:0.00} av, 21 or under)");
        }
        var boots = LeadersBy("goal", 1);
        if (boots.Count > 0)
        {
            lines.Add($"👟 Golden Boot: {boots[0].Player} ({boots[0].Count} goals, {boots[0].Team})");
        }
        if (lines.Count > 0)
        {
            PostInbox("Media", $"End-of-season awards {SeasonYear}/{(SeasonYear + 1) % 100:00}",
                string.Join("\n", lines), playerId: potsFace);
        }
    }

    /// <summary>The Roll of Honour: every season's champions, newest first.</summary>
    public IReadOnlyList<(int Year, string Competition, string Team)> Honours()
    {
        var rows = new List<(int, string, string)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT season_id, competition, team_id FROM honours ORDER BY season_id DESC, competition";
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            var raw = r.GetString(1);
            var comp = raw switch
            {
                "league" => LeagueNameFor(TopFlight),
                "division2" => LeagueNameFor(Division2),
                "lcup" => LeagueCupName,
                "ccup" => ContinentalName,
                "pots" => "Player of the Season",
                _ => CupName,
            };
            // Award rows store a PLAYER id in the team column; everything else a club.
            var holder = raw == "pots" ? PlayerNameOf(r.GetInt32(2)) : TeamName(r.GetInt32(2));
            rows.Add((2026 + (r.GetInt32(0) - 9000), comp, holder));
        }
        return rows;
    }

    private string LeagueNameFor(int leagueId) =>
        Repo.Leagues().FirstOrDefault(l => l.Id == leagueId)?.Name ?? "League";

    // ------------------------------------------------------------------ CPU transfer market

    /// <summary>
    /// The market moves between seasons: CPU clubs sign upgrades from the free-player pool
    /// (players in the master DB who aren't on any career squad), dropping their weakest to make
    /// room. Deterministic per season; feeds the Market Activity ticker and the inbox.
    /// </summary>
    private void CpuTransferActivity()
    {
        var rng = new SeededRandom((SeasonId * 6151 + 29) ^ WorldSeed);
        var clubs = Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2 && t.Id != CurrentTeamId).ToList();
        var bigMoves = new List<string>();
        foreach (var club in clubs)
        {
            if (rng.Next(100) >= 55) continue;   // not every club buys

            var squad = Repo.SquadPlayers(club.Id).OrderBy(p => p.OverallRating ?? 0).ToList();
            if (squad.Count == 0) continue;
            var avg = squad.Average(p => p.OverallRating ?? 65);

            // NEEDS-BASED (P2): the club shops for its thinnest position group, not "anyone".
            var byCat = squad.GroupBy(p => Visuals.PositionCategory(p.Position))
                .ToDictionary(g => g.Key, g => g.Count());
            var needCat = new[] { "GK", "DEF", "MID", "FWD" }
                .OrderBy(c => byCat.GetValueOrDefault(c, 0))
                .First();
            string needClause = needCat switch
            {
                "GK" => "p.position = 'GK'",
                "DEF" => "p.position IN ('CB','LB','RB')",
                "MID" => "p.position IN ('DMF','CMF','LMF','RMF','AMF')",
                _ => "p.position IN ('LWF','RWF','SS','CF')",
            };
            var floor = (int)avg - 2 + rng.Next(4);

            // A varied slice of the free pool (seeded offset, not the same 40 ids forever).
            using var q = Db.Connection.CreateCommand();
            q.CommandText =
                "SELECT p.id, p.name, p.overall_rating FROM players p " +
                $"WHERE p.overall_rating BETWEEN $lo AND $hi AND {needClause} " +
                "AND COALESCE(p.age, 25) <= 29 " +
                "AND NOT EXISTS (SELECT 1 FROM squad_members s WHERE s.player_id=p.id) " +
                "AND NOT EXISTS (SELECT 1 FROM academy a WHERE a.player_id=p.id) " +
                "ORDER BY (p.id * 2654435761) % 100000 LIMIT 40 OFFSET $off";
            q.Parameters.AddWithValue("$lo", floor);
            q.Parameters.AddWithValue("$hi", floor + 6);
            q.Parameters.AddWithValue("$off", rng.Next(60));
            var pool = new List<(int Id, string Name, int Ovr)>();
            using (var r = q.ExecuteReader())
            {
                while (r.Read()) pool.Add((r.GetInt32(0), r.GetString(1), r.IsDBNull(2) ? 60 : r.GetInt32(2)));
            }

            // Inter-club buying (P2): ~1 in 4 raids another CPU club for an upgrade instead —
            // a real fee changes hands and the transfer log carries both ends.
            if ((pool.Count == 0 || rng.Next(4) == 0) && clubs.Count > 1)
            {
                var seller = clubs[rng.Next(clubs.Count)];
                if (seller.Id != club.Id)
                {
                    var sellable = Repo.SquadPlayers(seller.Id)
                        .Where(p => Visuals.PositionCategory(p.Position) == needCat
                                    && (p.OverallRating ?? 0) >= avg - 1)
                        .OrderByDescending(p => p.OverallRating ?? 0)
                        .Skip(1)   // never their best player
                        .FirstOrDefault();
                    if (sellable is not null && Repo.Squad(seller.Id).Count > 19)
                    {
                        var fee = ValuationOf(sellable.OverallRating ?? 65, sellable.Age);
                        Repo.RemoveSquadMember(seller.Id, sellable.Id);
                        MoveIntoSquad(club.Id, sellable.Id);
                        RecordPaidTransfer(sellable.Id, seller.Id, club.Id, fee);
                        try { PaySellOnIfDue(sellable.Id, fee); } catch { /* clause optional */ }
                        if ((sellable.OverallRating ?? 0) >= avg + 3)
                        {
                            bigMoves.Add($"{sellable.Name} → {club.Name} (£{fee:N0} from {seller.Name})");
                        }
                        continue;
                    }
                }
            }
            if (pool.Count == 0) continue;

            var signing = pool[rng.Next(pool.Count)];
            var drop = squad[0];
            Repo.RemoveSquadMember(club.Id, drop.Id);
            MoveIntoSquad(club.Id, signing.Id);
            Repo.RecordTransfer(signing.Id, club.Id, SeasonId);
        }

        // The biggest moves make the news.
        if (bigMoves.Count > 0)
        {
            PostInbox("Transfer", "Around the market",
                "The moves everyone is talking about:\n" + string.Join("\n", bigMoves.Take(5)));
        }
    }

    private void MoveIntoSquad(int teamId, int playerId)
    {
        var used = Repo.Squad(teamId).Select(s => s.SquadNumber).ToHashSet();
        var shirt = Enumerable.Range(1, 99).FirstOrDefault(n => !used.Contains(n), 99);
        Repo.SetSquadMember(new SquadMemberRow
        { TeamId = teamId, PlayerId = playerId, SquadNumber = shirt, Slot = Repo.Squad(teamId).Count });
    }

    private void RecordPaidTransfer(int playerId, int fromTeam, int toTeam, long fee)
    {
        using var t = Db.Connection.CreateCommand();
        t.CommandText = "INSERT INTO transfers(player_id,from_team_id,to_team_id,fee,window,season_id) " +
                        "VALUES($p,$f,$t,$fee,'summer',$s)";
        t.Parameters.AddWithValue("$p", playerId);
        t.Parameters.AddWithValue("$f", fromTeam);
        t.Parameters.AddWithValue("$t", toTeam);
        t.Parameters.AddWithValue("$fee", fee);
        t.Parameters.AddWithValue("$s", SeasonId);
        t.ExecuteNonQuery();
    }

    /// <summary>
    /// Rollover mortality (P2): veterans hang up their boots (odds climb with age), and
    /// out-of-contract players actually LEAVE on frees — contracts stopped being theatre.
    /// Squads never drop below 18; the market pass right after re-fills the gaps.
    /// </summary>
    private void RetireAndExpire()
    {
        var rng = new SeededRandom((SeasonId * 30011 + 13) ^ WorldSeed);
        var notable = new List<string>();
        foreach (var club in Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2).ToList())
        {
            foreach (var p in Repo.SquadPlayers(club.Id).ToList())
            {
                if (Repo.Squad(club.Id).Count <= 18) break;
                var age = p.Age ?? 25;   // already aged by AgeAndDevelopSquads
                var retireChance = age switch
                {
                    >= 39 => 95, 38 => 80, 37 => 65, 36 => 50, 35 => 32, 34 => 16, _ => 0,
                };
                if (retireChance > 0 && rng.Next(100) < retireChance)
                {
                    Repo.RemoveSquadMember(club.Id, p.Id);
                    if (club.Id == CurrentTeamId)
                    {
                        PostInbox("Player", $"{p.Name} retires",
                            $"At {age}, {p.Name} has hung up his boots. The dressing room gives " +
                            "him a send-off; his shirt number is free.", playerId: p.Id);
                    }
                    else if ((p.OverallRating ?? 0) >= 78)
                    {
                        notable.Add($"{p.Name} ({club.Name}, {age})");
                    }
                }
            }
        }
        if (notable.Count > 0)
        {
            PostInbox("Media", "End of an era",
                "Calling time on their careers this summer: " + string.Join(", ", notable.Take(6)) + ".");
        }

        // YOUR out-of-contract players walk (the mails warned you from matchday 30).
        var gone = new List<string>();
        foreach (var m in Repo.Squad(CurrentTeamId).ToList())
        {
            if (Repo.Squad(CurrentTeamId).Count <= 18) break;
            using var q = Db.Connection.CreateCommand();
            q.CommandText = "SELECT expires_season FROM contracts WHERE player_id=$p AND team_id=$t";
            q.Parameters.AddWithValue("$p", m.PlayerId);
            q.Parameters.AddWithValue("$t", CurrentTeamId);
            if (q.ExecuteScalar() is long v and > 0 && v <= SeasonId)
            {
                var name = Repo.SquadPlayers(CurrentTeamId).FirstOrDefault(p => p.Id == m.PlayerId)?.Name ?? "A player";
                Repo.RemoveSquadMember(CurrentTeamId, m.PlayerId);
                using var del = Db.Connection.CreateCommand();
                del.CommandText = "DELETE FROM contracts WHERE player_id=$p AND team_id=$t";
                del.Parameters.AddWithValue("$p", m.PlayerId);
                del.Parameters.AddWithValue("$t", CurrentTeamId);
                del.ExecuteNonQuery();
                gone.Add(name);
            }
        }
        if (gone.Count > 0)
        {
            PostInbox("Transfer", "Departures on free transfers",
                $"Out of contract and gone: {string.Join(", ", gone)}. Renew earlier from the " +
                "Squad screen if you want to keep the next batch.");
        }
    }

    /// <summary>Latest market moves for the ticker, newest first.</summary>
    public IReadOnlyList<string> RecentTransfers(int count = 6)
    {
        var rows = new List<string>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.name, t.to_team_id FROM transfers t JOIN players p ON p.id = t.player_id " +
            "ORDER BY t.rowid DESC LIMIT $n";
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            rows.Add($"{r.GetString(0)} → {TeamName(r.GetInt32(1))}");
        }
        return rows;
    }

    // ------------------------------------------------------------------ academy

    private const int AcademyIdBase = 30_000_000;

    /// <summary>
    /// Preseason intake: every club's academy produces two prospects (16-18, raw ratings, built
    /// from the career world's own name pool). CPU clubs auto-promote their best prospect when
    /// their squad runs short; yours wait on the Academy screen for your decision.
    /// </summary>
    private void AcademyIntake()
    {
        var rng = new SeededRandom((SeasonId * 9973 + 5) ^ WorldSeed);
        var first = new List<string>();
        var last = new List<string>();
        using (var names = Db.Connection.CreateCommand())
        {
            names.CommandText = "SELECT name FROM players WHERE name LIKE '% %' LIMIT 4000";
            using var r = names.ExecuteReader();
            while (r.Read())
            {
                var parts = r.GetString(0).Split(' ');
                if (parts.Length < 2) continue;
                first.Add(parts[0]);
                last.Add(parts[^1]);
            }
        }
        if (first.Count == 0) { first.Add("Alex"); last.Add("Walker"); }

        int nextId;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT COALESCE(MAX(id), $b) + 1 FROM players WHERE id >= $b";
            q.Parameters.AddWithValue("$b", AcademyIdBase);
            nextId = Convert.ToInt32(q.ExecuteScalar());
        }

        string[] positions = { "GK", "CB", "RB", "LB", "DMF", "CMF", "AMF", "RWF", "LWF", "CF", "CF" };
        foreach (var club in Repo.Teams().Where(t => t.LeagueId is TopFlight or Division2).ToList())
        {
            // Intake day (P2): a varied class of 1-4, each with REAL stored potential —
            // the intake size and quality differ per club per season per world.
            var classSize = 1 + rng.Next(4);
            var yours = club.Id == CurrentTeamId;
            var report = new List<string>();
            var bestPotential = 0;
            for (var i = 0; i < classSize; i++)
            {
                var id = nextId++;
                var age = 16 + rng.Next(3);
                var rating = 44 + rng.Next(16);
                var name = $"{first[rng.Next(first.Count)]} {last[rng.Next(last.Count)]}";
                var position = positions[rng.Next(positions.Length)];
                Repo.UpsertPlayer(new PlayerRow
                {
                    Id = id, GamePid = id, IsCustom = true, Name = name, Position = position,
                    Age = age, Nationality = club.ShortName, OverallRating = rating,
                });
                // Real potential: most are journeymen; ~1 in 9 is a genuine prospect.
                var gem = rng.Next(9) == 0;
                var potential = Math.Clamp(
                    rating + 8 + rng.Next(14) + (gem ? 12 + rng.Next(9) : 0), rating, 94);
                SetPotential(id, potential);
                // A face for the avatar: seeded skin tone (bell across 1-6).
                using (var app = Db.Connection.CreateCommand())
                {
                    app.CommandText = "INSERT OR IGNORE INTO player_appearance" +
                                      "(player_id,skin_tone,source) VALUES($p,$t,'seeded')";
                    app.Parameters.AddWithValue("$p", id);
                    app.Parameters.AddWithValue("$t", 1 + (rng.Next(6) + rng.Next(6)) / 2);
                    app.ExecuteNonQuery();
                }
                bestPotential = Math.Max(bestPotential, potential);
                if (yours)
                {
                    var stars = potential switch { >= 86 => "★★★★★", >= 79 => "★★★★", >= 71 => "★★★", >= 62 => "★★", _ => "★" };
                    report.Add($"{name} ({position}, {age}) — current {rating}, potential {stars}" +
                               (gem ? "  ← one to watch" : ""));
                }
                using var ins = Db.Connection.CreateCommand();
                ins.CommandText = "INSERT OR REPLACE INTO academy(player_id,team_id,joined_season) VALUES($p,$t,$s)";
                ins.Parameters.AddWithValue("$p", id);
                ins.Parameters.AddWithValue("$t", club.Id);
                ins.Parameters.AddWithValue("$s", SeasonId);
                ins.ExecuteNonQuery();
            }

            // YOUR intake day is an event: the youth coach's report lands in the inbox.
            if (yours && report.Count > 0)
            {
                var verdict = bestPotential >= 86
                    ? "The coaches are excited — this class has a special one in it."
                    : bestPotential >= 79 ? "A promising class, worth real minutes."
                    : bestPotential >= 71 ? "A solid, unspectacular year group."
                    : "A thin year — don't expect first-teamers from this class.";
                PostInbox("Player", $"Youth intake day — {report.Count} join the academy",
                    $"{verdict}\n\n{string.Join("\n", report)}\n\nPotential stars are the youth " +
                    "coach's read of each lad's ceiling — development chases it from now on.");
            }

            // CPU clubs bring their best prospect through when the squad runs short.
            if (!yours && Repo.Squad(club.Id).Count < 26)
            {
                var best = AcademyPlayers(club.Id).OrderByDescending(p => p.OverallRating ?? 0).FirstOrDefault();
                if (best is not null) PromoteAcademy(best.Id, club.Id);
            }
        }
    }

    public IReadOnlyList<PlayerRow> AcademyPlayers() => AcademyPlayers(CurrentTeamId);

    private IReadOnlyList<PlayerRow> AcademyPlayers(int teamId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.id, p.name, p.position, p.age, p.overall_rating FROM academy a " +
            "JOIN players p ON p.id = a.player_id WHERE a.team_id=$t ORDER BY p.overall_rating DESC";
        cmd.Parameters.AddWithValue("$t", teamId);
        var rows = new List<PlayerRow>();
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            rows.Add(new PlayerRow
            {
                Id = r.GetInt32(0), GamePid = r.GetInt32(0), IsCustom = true, Name = r.GetString(1),
                Position = r.IsDBNull(2) ? "CMF" : r.GetString(2),
                Age = r.IsDBNull(3) ? null : r.GetInt32(3),
                OverallRating = r.IsDBNull(4) ? null : r.GetInt32(4),
            });
        }
        return rows;
    }

    /// <summary>Promote an academy prospect into the senior squad.</summary>
    public string PromoteAcademy(int playerId) => PromoteAcademy(playerId, CurrentTeamId);

    private string PromoteAcademy(int playerId, int teamId)
    {
        using (var del = Db.Connection.CreateCommand())
        {
            del.CommandText = "DELETE FROM academy WHERE player_id=$p AND team_id=$t";
            del.Parameters.AddWithValue("$p", playerId);
            del.Parameters.AddWithValue("$t", teamId);
            if (del.ExecuteNonQuery() == 0) return "That prospect is no longer in the academy.";
        }
        var used = Repo.Squad(teamId).Select(s => s.SquadNumber).ToHashSet();
        var shirt = Enumerable.Range(30, 70).FirstOrDefault(n => !used.Contains(n), 99);
        Repo.SetSquadMember(new SquadMemberRow
        { TeamId = teamId, PlayerId = playerId, SquadNumber = shirt, Slot = Repo.Squad(teamId).Count });
        return $"Promoted to the senior squad — squad number {shirt}.";
    }

    // ------------------------------------------------------------------ the bank

    public long LoanOutstanding => long.TryParse(GetMeta($"loan_{CurrentTeamId}"), out var v) ? v : 0;

    /// <summary>Weekly repayment while a loan is outstanding (34 instalments at 5% interest).</summary>
    public long LoanWeekly => long.TryParse(GetMeta($"loan_wk_{CurrentTeamId}"), out var v) ? v : 0;

    /// <summary>Take a bank loan: cash now, 34 weekly instalments at 5%. One loan at a time.</summary>
    public string TakeLoan(long amount)
    {
        if (LoanOutstanding > 0) return "You already have a loan outstanding — repay it first.";
        if (amount is not (250_000 or 500_000 or 1_000_000)) return "The bank offers £250k, £500k or £1m.";
        var total = (long)(amount * 1.05);
        SetMeta($"loan_{CurrentTeamId}", total.ToString());
        SetMeta($"loan_wk_{CurrentTeamId}", (total / 34).ToString());
        Finances.ReceivePrize(amount);   // cash in: balance up, counted as season income
        AdjustBudget(amount);
        return $"Loan agreed: £{amount:N0} received. Repaying £{total / 34:N0}/week over 34 weeks (5% interest).";
    }

    private void RepayLoanInstalment()
    {
        var outstanding = LoanOutstanding;
        if (outstanding <= 0) return;
        var instalment = Math.Min(LoanWeekly, outstanding);
        Finances.PayWages(instalment);   // debit: balance down, counted as season expenditure
        AdjustBudget(-instalment);
        var left = outstanding - instalment;
        SetMeta($"loan_{CurrentTeamId}", left.ToString());
        if (left <= 0) SetMeta($"loan_wk_{CurrentTeamId}", "0");
    }

    private void AdjustBudget(long delta)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE teams SET budget = MAX(budget + $d, 0) WHERE id=$t";
        cmd.Parameters.AddWithValue("$d", delta);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Persist the running balance (wages, gate receipts) so it survives restarts.</summary>
    private void SyncBudget()
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE teams SET budget = MAX($b, 0) WHERE id=$t";
        cmd.Parameters.AddWithValue("$b", Finances.Balance);
        cmd.Parameters.AddWithValue("$t", CurrentTeamId);
        cmd.ExecuteNonQuery();
        // Season tallies persist per season (P0): keys carry the SeasonId, so rollover
        // naturally starts a fresh pair at zero.
        SetMeta($"fin_income_{SeasonId}", Finances.SeasonIncome.ToString());
        SetMeta($"fin_spend_{SeasonId}", Finances.SeasonExpenditure.ToString());
    }

    /// <summary>Restore this season's income/spend into the in-memory ledger (ctor).</summary>
    internal void RestoreSeasonFinances()
    {
        var income = long.TryParse(GetMeta($"fin_income_{SeasonId}"), out var i) ? i : 0;
        var spend = long.TryParse(GetMeta($"fin_spend_{SeasonId}"), out var e) ? e : 0;
        if (income > 0 || spend > 0) Finances.RestoreSeasonTallies(income, spend);
    }

    /// <summary>January: a lighter burst of CPU buying plus fresh offers for your players.</summary>
    private void CpuTransferActivityMidSeason()
    {
        CpuTransferActivity();
        GenerateOffers();
    }

    /// <summary>MFL-style financial overview: budget split into transfer and wage pots. The
    /// weekly bill covers players (NEGOTIATED wages where a real contract exists — stub rows at
    /// £500 fall back to the rating formula) AND the backroom staff.</summary>
    public (long TransferBudget, long WageBudget, long WeeklyWages) FinancialOverview()
    {
        long weekly;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT COALESCE(SUM(CASE WHEN c.weekly_wage > 500 THEN c.weekly_wage " +
                "ELSE 500 + COALESCE(p.overall_rating, 60) * 40 END), 0) " +
                "FROM squad_members s JOIN players p ON p.id = s.player_id " +
                "LEFT JOIN contracts c ON c.player_id = s.player_id AND c.team_id = s.team_id " +
                "WHERE s.team_id = $t";
            cmd.Parameters.AddWithValue("$t", CurrentTeamId);
            weekly = Convert.ToInt64(cmd.ExecuteScalar());
        }
        weekly += StaffWages();
        var balance = Finances.Balance;
        return ((long)(balance * 0.6), (long)(balance * 0.4), weekly);
    }

    // ------------------------------------------------------------------ scorers + player stats

    private static string NormName(string s)
    {
        var d = s.Normalize(System.Text.NormalizationForm.FormD);
        var sb = new System.Text.StringBuilder();
        foreach (var ch in d)
        {
            if (System.Globalization.CharUnicodeInfo.GetUnicodeCategory(ch)
                != System.Globalization.UnicodeCategory.NonSpacingMark) sb.Append(ch);
        }
        return sb.ToString().ToLowerInvariant().Trim();
    }

    /// <summary>
    /// Record your match's player stats — the four things eFootball's post-match screens give:
    /// goals, assists, cards ("Name" = yellow, "Name r" = red) and ratings ("Name 7.5"). Names
    /// are comma-separated and matched against BOTH squads by surname.
    /// </summary>
    public string RecordMatchStats(
        int fixtureId, int homeTeamId, int awayTeamId,
        string scorers, string assists, string cards, string ratings)
    {
        var candidates = Repo.SquadPlayers(homeTeamId).Concat(Repo.SquadPlayers(awayTeamId)).ToList();
        var missed = new List<string>();
        var notes = new List<string>();

        PlayerRow? Find(string raw)
        {
            var norm = NormName(raw);
            var hit = candidates.FirstOrDefault(p => NormName(p.Name) == norm)
                      ?? candidates.FirstOrDefault(p => NormName(p.Name).EndsWith(" " + norm))
                      ?? candidates.FirstOrDefault(p => NormName(p.Name).Contains(norm));
            if (hit is null) missed.Add(raw);
            return hit;
        }

        static IEnumerable<string> Split(string s) =>
            s.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);

        var goals = new List<string>();
        foreach (var raw in Split(scorers))
        {
            if (Find(raw) is { } p) { AddEvent(fixtureId, p.Id, "goal", goals.Count + 1); goals.Add(p.Name); }
        }
        if (goals.Count > 0) notes.Add($"⚽ {string.Join(", ", goals)}");

        var assisted = new List<string>();
        foreach (var raw in Split(assists))
        {
            if (Find(raw) is { } p) { AddEvent(fixtureId, p.Id, "assist", assisted.Count + 1); assisted.Add(p.Name); }
        }
        if (assisted.Count > 0) notes.Add($"🅰 {string.Join(", ", assisted)}");

        var booked = new List<string>();
        foreach (var raw in Split(cards))
        {
            var red = raw.EndsWith(" r", StringComparison.OrdinalIgnoreCase)
                      || raw.EndsWith(" red", StringComparison.OrdinalIgnoreCase);
            var name = red ? raw[..raw.LastIndexOf(' ')] : raw;
            if (Find(name) is { } p)
            {
                AddEvent(fixtureId, p.Id, red ? "red" : "yellow", 0);
                booked.Add($"{p.Name}{(red ? " 🟥" : " 🟨")}");
            }
        }
        if (booked.Count > 0) notes.Add(string.Join(", ", booked));

        var rated = 0;
        foreach (var raw in Split(ratings))
        {
            var ix = raw.LastIndexOf(' ');
            if (ix <= 0 || !double.TryParse(raw[(ix + 1)..],
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out var val)) { missed.Add(raw); continue; }
            if (Find(raw[..ix]) is { } p)
            {
                using var cmd = Db.Connection.CreateCommand();
                cmd.CommandText = "INSERT OR REPLACE INTO player_match_ratings(fixture_id,player_id,rating) " +
                                  "VALUES($f,$p,$r)";
                cmd.Parameters.AddWithValue("$f", fixtureId);
                cmd.Parameters.AddWithValue("$p", p.Id);
                cmd.Parameters.AddWithValue("$r", val);
                cmd.ExecuteNonQuery();
                rated++;
            }
        }
        if (rated > 0) notes.Add($"{rated} rating(s) saved");
        if (missed.Count > 0) notes.Add($"(no match: {string.Join(", ", missed)})");
        return notes.Count > 0 ? string.Join("  ·  ", notes) : "";
    }

    /// <summary>Appearances: both XIs (squad slots 0-10) get an 'app' event when a result lands.</summary>
    public void RecordAppearances(int fixtureId, int homeTeamId, int awayTeamId)
    {
        foreach (var teamId in new[] { homeTeamId, awayTeamId })
        {
            foreach (var m in Repo.Squad(teamId).Where(m => m.Slot is >= 0 and <= 10))
            {
                AddEvent(fixtureId, m.PlayerId, "app", 0);
            }
        }
    }

    private void AddEvent(int fixtureId, int playerId, string type, int minute)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO match_events(fixture_id,player_id,event_type,minute) " +
                          "VALUES($f,$p,$t,$m)";
        cmd.Parameters.AddWithValue("$f", fixtureId);
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$t", type);
        cmd.Parameters.AddWithValue("$m", minute);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Store the post-match stats screen (possession/shots) on the result (C4).</summary>
    public void SaveMatchStats(int fixtureId, int? possH, int? possA, int? shotsH, int? shotsA)
    {
        var json = System.Text.Json.JsonSerializer.Serialize(new
        { possH, possA, shotsH, shotsA });
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE results SET stats_json=$j WHERE fixture_id=$f";
        cmd.Parameters.AddWithValue("$j", json);
        cmd.Parameters.AddWithValue("$f", fixtureId);
        cmd.ExecuteNonQuery();
    }

    /// <summary>Recorded events of one fixture for the post-match report (P3).</summary>
    public IReadOnlyList<(string Type, string Player, int TeamId)> EventsForFixture(int fixtureId)
    {
        var rows = new List<(string, string, int)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT e.event_type, p.name, COALESCE(s.team_id, 0) FROM match_events e " +
            "JOIN players p ON p.id = e.player_id " +
            "LEFT JOIN squad_members s ON s.player_id = e.player_id " +
            "WHERE e.fixture_id=$f AND e.event_type IN ('goal','assist','yellow','red') " +
            "ORDER BY e.id";
        cmd.Parameters.AddWithValue("$f", fixtureId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add((r.GetString(0), r.GetString(1), r.GetInt32(2)));
        return rows;
    }

    /// <summary>Saved match ratings of one fixture (player, rating), best first.</summary>
    public IReadOnlyList<(string Player, double Rating)> RatingsForFixture(int fixtureId)
    {
        var rows = new List<(string, double)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.name, r.rating FROM player_match_ratings r " +
            "JOIN players p ON p.id = r.player_id WHERE r.fixture_id=$f ORDER BY r.rating DESC";
        cmd.Parameters.AddWithValue("$f", fixtureId);
        using var r = cmd.ExecuteReader();
        while (r.Read()) rows.Add((r.GetString(0), r.GetDouble(1)));
        return rows;
    }

    /// <summary>Your recent matches with any captured stats — the match-report list.</summary>
    public IReadOnlyList<(string When, string Line, string Stats)> MyMatchReports(int count = 6)
    {
        var rows = new List<(string, string, string)>();
        foreach (var f in Repo.Fixtures(SeasonId)
                     .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && f.Played)
                     .OrderByDescending(f => f.Matchday).Take(count))
        {
            if (ResultFor(f.Id) is not { } r) continue;
            var line = $"{TeamName(f.HomeTeamId)} {r.HomeGoals}–{r.AwayGoals} {TeamName(f.AwayTeamId)}";
            var stats = "";
            if (!string.IsNullOrEmpty(r.StatsJson))
            {
                try
                {
                    using var doc = System.Text.Json.JsonDocument.Parse(r.StatsJson);
                    var root = doc.RootElement;
                    int? G(string k) => root.TryGetProperty(k, out var v) && v.ValueKind
                        == System.Text.Json.JsonValueKind.Number ? v.GetInt32() : null;
                    var parts = new List<string>();
                    if (G("possH") is { } ph && G("possA") is { } pa) parts.Add($"possession {ph}%–{pa}%");
                    if (G("shotsH") is { } sh && G("shotsA") is { } sa) parts.Add($"shots {sh}–{sa}");
                    stats = string.Join("  ·  ", parts);
                }
                catch { /* legacy json shapes are fine to skip */ }
            }
            rows.Add((ML.Core.Scheduling.SeasonCalendar.ShortLabel(DateOfFixture(f)), line, stats));
        }
        return rows;
    }

    /// <summary>Season line for one player: the four stats the game gives + apps.</summary>
    public (int Apps, int Goals, int Assists, int Yellows, int Reds, double? AvgRating)
        PlayerSeasonStats(int playerId)
    {
        var counts = new Dictionary<string, int>();
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT e.event_type, COUNT(*) FROM match_events e " +
                              "JOIN fixtures f ON f.id=e.fixture_id " +
                              "WHERE e.player_id=$p AND f.season_id=$s GROUP BY e.event_type";
            cmd.Parameters.AddWithValue("$p", playerId);
            cmd.Parameters.AddWithValue("$s", SeasonId);
            using var r = cmd.ExecuteReader();
            while (r.Read()) counts[r.GetString(0)] = r.GetInt32(1);
        }
        double? avg = null;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT AVG(r.rating) FROM player_match_ratings r " +
                              "JOIN fixtures f ON f.id=r.fixture_id " +
                              "WHERE r.player_id=$p AND f.season_id=$s";
            cmd.Parameters.AddWithValue("$p", playerId);
            cmd.Parameters.AddWithValue("$s", SeasonId);
            var v = cmd.ExecuteScalar();
            if (v is not null and not DBNull) avg = Convert.ToDouble(v);
        }
        return (counts.GetValueOrDefault("app"), counts.GetValueOrDefault("goal"),
                counts.GetValueOrDefault("assist"), counts.GetValueOrDefault("yellow"),
                counts.GetValueOrDefault("red"), avg);
    }

    /// <summary>League leaders for any counted event type ('goal', 'assist').</summary>
    public IReadOnlyList<(string Player, string Team, int Count)> LeadersBy(string eventType, int count = 12)
    {
        var rows = new List<(string, string, int)>();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText =
            "SELECT p.name, COALESCE(s.team_id, 0), COUNT(*) AS g FROM match_events e " +
            "JOIN players p ON p.id = e.player_id " +
            "LEFT JOIN squad_members s ON s.player_id = e.player_id " +
            "JOIN fixtures f ON f.id = e.fixture_id " +
            "WHERE e.event_type=$t AND f.season_id=$s " +
            "GROUP BY e.player_id ORDER BY g DESC, p.name LIMIT $n";
        cmd.Parameters.AddWithValue("$t", eventType);
        cmd.Parameters.AddWithValue("$s", SeasonId);
        cmd.Parameters.AddWithValue("$n", count);
        using var r = cmd.ExecuteReader();
        while (r.Read())
        {
            rows.Add((r.GetString(0), TeamName(r.GetInt32(1)), r.GetInt32(2)));
        }
        return rows;
    }

    // Squad cache for CPU goal attribution: (player id, weight) per team, weighted to the front.
    private Dictionary<int, List<(int Id, int Weight)>>? _shooterPool;

    /// <summary>Attribute a simmed team's goals to plausible players (FWD-weighted, seeded).</summary>
    private void AttributeGoals(int fixtureId, int teamId, int goals, IRandomSource rng)
    {
        if (goals <= 0) return;
        _shooterPool ??= new Dictionary<int, List<(int, int)>>();
        if (!_shooterPool.TryGetValue(teamId, out var pool))
        {
            pool = Repo.SquadPlayers(teamId)
                .Where(p => p.Position != "GK")
                .Select(p => (p.Id, Visuals.PositionCategory(p.Position) switch
                { "FWD" => 6, "MID" => 3, _ => 1 } + (p.OverallRating ?? 60) / 25))
                .ToList();
            _shooterPool[teamId] = pool;
        }
        if (pool.Count == 0) return;
        var total = pool.Sum(x => x.Weight);
        int Pick()
        {
            var roll = rng.Next(total);
            foreach (var (id, w) in pool)
            {
                roll -= w;
                if (roll < 0) return id;
            }
            return pool[0].Id;
        }
        for (var g = 0; g < goals; g++)
        {
            var scorer = Pick();
            AddEvent(fixtureId, scorer, "goal", 10 + rng.Next(80));
            if (rng.Next(100) < 55)                     // most goals are assisted
            {
                var assist = Pick();
                if (assist != scorer) AddEvent(fixtureId, assist, "assist", 0);
            }
        }
    }

    /// <summary>Simmed bookings: a couple of yellows most games, the odd red.</summary>
    private void AttributeCards(int fixtureId, int homeTeamId, int awayTeamId, IRandomSource rng)
    {
        foreach (var teamId in new[] { homeTeamId, awayTeamId })
        {
            var squad = Repo.Squad(teamId).Where(m => m.Slot is >= 0 and <= 10).ToList();
            if (squad.Count == 0) continue;
            for (var c = rng.Next(3); c > 0; c--)
            {
                var victim = squad[rng.Next(squad.Count)];
                AddEvent(fixtureId, victim.PlayerId, rng.Next(100) < 5 ? "red" : "yellow", 0);
            }
        }
    }

    /// <summary>Full stat attribution for one simmed result: apps, scorers+assists, cards.</summary>
    private void AttributeSimmedMatch(int fixtureId, int homeId, int awayId,
        int homeGoals, int awayGoals, IRandomSource rng)
    {
        RecordAppearances(fixtureId, homeId, awayId);
        AttributeGoals(fixtureId, homeId, homeGoals, rng);
        AttributeGoals(fixtureId, awayId, awayGoals, rng);
        AttributeCards(fixtureId, homeId, awayId, rng);
    }

    /// <summary>A player's goals this season (for the squad card).</summary>
    public int GoalsThisSeason(int playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM match_events e JOIN fixtures f ON f.id=e.fixture_id " +
                          "WHERE e.player_id=$p AND e.event_type='goal' AND f.season_id=$s";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$s", SeasonId);
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    // ------------------------------------------------------------------ transfer economics

    /// <summary>Market valuation: quadratic in rating, discounted with age past the peak.</summary>
    public static long ValuationOf(int rating, int? age)
    {
        // Realistic market curve (P5): exponential in rating, calibrated against the real
        // market — 60 ≈ £650k, 70 ≈ £4.5m, 75 ≈ £11m, 80 ≈ £30m, 85 ≈ £78m, 90 ≈ £200m.
        double v = 15_000 * Math.Exp(0.19 * (Math.Clamp(rating, 40, 99) - 40));
        var a = age ?? 25;
        if (a > 29) v *= Math.Max(0.20, 1 - (a - 29) * 0.13);
        if (a < 22) v *= 1.30;
        return (long)(Math.Round(v / 25_000) * 25_000);
    }

    /// <summary>Which club (if any) in the career world currently holds this player.</summary>
    private (int TeamId, string Name)? OwningClub(int playerId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT s.team_id, t.name FROM squad_members s JOIN teams t ON t.id=s.team_id " +
                          "WHERE s.player_id=$p AND t.league_id IN (9000, 9001) LIMIT 1";
        cmd.Parameters.AddWithValue("$p", playerId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? (r.GetInt32(0), r.GetString(1)) : null;
    }

    /// <summary>The transfer window: open in preseason, in January (MD 17-19), and post-season.</summary>
    public bool TransferWindowOpen()
    {
        var next = NextFixture();
        if (next is null) return true;                       // season done — summer window
        if (next.Kind == "friendly" || next.Matchday <= 1) return true;   // preseason
        return next.Matchday is >= 17 and <= 19;             // January window
    }

    public string TransferWindowLabel()
    {
        if (TransferWindowOpen()) return "Transfer window OPEN";
        var next = NextFixture();
        return next is { Matchday: < 17 }
            ? $"Window closed — reopens in January (MD17), now MD{next.Matchday}"
            : "Window closed until the summer";
    }

    /// <summary>
    /// Bid for a player. bidPct is your offer as a percentage of market value (85 / 100 / 115).
    /// Free agents take fair value; a club holding the player wants a premium (they may counter),
    /// won't sell if it leaves them short, and pockets the fee when they do.
    /// </summary>
    public string BuyPlayer(int playerId, int bidPct = 100)
    {
        if (!TransferWindowOpen())
        {
            return TransferWindowLabel() + ". No deals outside the window.";
        }
        var squad = Repo.Squad(CurrentTeamId);
        if (squad.Any(s => s.PlayerId == playerId)) return "That player is already in your squad.";

        string name = "player";
        int rating = 65;
        int? age = null;
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT name, COALESCE(overall_rating,65), age FROM players WHERE id=$id";
            q.Parameters.AddWithValue("$id", playerId);
            using var r = q.ExecuteReader();
            if (r.Read())
            {
                name = r.GetString(0);
                rating = r.GetInt32(1);
                age = r.IsDBNull(2) ? null : r.GetInt32(2);
            }
        }

        var value = ValuationOf(rating, age);
        var bid = value * bidPct / 100;
        var seller = OwningClub(playerId);
        if (seller is { } club)
        {
            if (Repo.Squad(club.TeamId).Count <= 18)
            {
                return $"{club.Name} won't sell {name} — their squad is already at the minimum.";
            }
            // The seller's ask: value plus a stable premium (0-20%) per player/season,
            // scaled by the Settings transfer difficulty.
            var difficulty = (GetMeta("transfer_difficulty") ?? "Normal") switch
            {
                "Easy" => 90, "Hard" => 115, _ => 100,
            };
            var ask = value * (105 + (int)((uint)((playerId + SeasonId) * 2654435761) % 16)) / 100
                      * difficulty / 100;
            if (bid < ask)
            {
                return $"{club.Name} reject £{bid:N0} for {name} — they'd listen to about £{ask:N0}.";
            }
        }
        else if (bid < value)
        {
            return $"{name} is a free agent but £{bid:N0} undervalues him — offer the £{value:N0} market rate.";
        }

        if (!Finances.TrySpendOnTransfer(bid, minBalanceAfter: 0))
        {
            return $"That deal needs £{bid:N0} — you only have £{Finances.Balance:N0}. The bank offers loans.";
        }
        AdjustBudget(-bid);
        if (seller is { } sellingClub)
        {
            Repo.RemoveSquadMember(sellingClub.TeamId, playerId);
            using var pay = Db.Connection.CreateCommand();
            pay.CommandText = "UPDATE teams SET budget = budget + $f WHERE id=$t";
            pay.Parameters.AddWithValue("$f", bid);
            pay.Parameters.AddWithValue("$t", sellingClub.TeamId);
            pay.ExecuteNonQuery();
        }

        var used = squad.Select(s => s.SquadNumber).ToHashSet();
        var shirt = Enumerable.Range(1, 99).FirstOrDefault(n => !used.Contains(n), 99);
        Repo.SetSquadMember(new SquadMemberRow
        { TeamId = CurrentTeamId, PlayerId = playerId, SquadNumber = shirt, Slot = squad.Count });
        using (var t = Db.Connection.CreateCommand())
        {
            t.CommandText = "INSERT INTO transfers(player_id,from_team_id,to_team_id,fee,window,season_id) " +
                            "VALUES($p,$from,$t,$f,'signing',$s)";
            t.Parameters.AddWithValue("$p", playerId);
            t.Parameters.AddWithValue("$from", (object?)seller?.TeamId ?? DBNull.Value);
            t.Parameters.AddWithValue("$t", CurrentTeamId);
            t.Parameters.AddWithValue("$f", bid);
            t.Parameters.AddWithValue("$s", SeasonId);
            t.ExecuteNonQuery();
        }

        var withNew = Repo.SquadPlayers(CurrentTeamId).OrderBy(p => p.OverallRating ?? 0).ToList();
        if (withNew.Count > 32)
        {
            var drop = withNew.First(p => p.Id != playerId);
            Repo.RemoveSquadMember(CurrentTeamId, drop.Id);
        }
        _teamCache = null;
        _shooterPool = null;
        var from = seller is { } s2 ? $" from {s2.Name}" : "";
        PostInbox("Transfer", $"Signed: {name}",
            $"{name} ({rating}) joins{from} for £{bid:N0}. Squad number {shirt}.", playerId: playerId);
        return $"Signed {name} ({rating}){from} for £{bid:N0} — squad number {shirt}.";
    }

    public sealed record TransferOffer(int PlayerId, string PlayerName, string FromTeam, long Fee);

    /// <summary>Standing offers from CPU clubs for your players (generated each preseason).</summary>
    public IReadOnlyList<TransferOffer> PendingOffers()
    {
        var raw = GetMeta($"offers_{CurrentTeamId}");
        if (string.IsNullOrEmpty(raw)) return Array.Empty<TransferOffer>();
        try
        {
            return System.Text.Json.JsonSerializer.Deserialize<List<TransferOffer>>(raw)
                   ?? (IReadOnlyList<TransferOffer>)Array.Empty<TransferOffer>();
        }
        catch { return Array.Empty<TransferOffer>(); }
    }

    private void SaveOffers(IReadOnlyList<TransferOffer> offers) =>
        SetMeta($"offers_{CurrentTeamId}", System.Text.Json.JsonSerializer.Serialize(offers));

    /// <summary>
    /// Preseason: CPU clubs bid for your best players at a premium — and transfer-listed players
    /// draw offers far more often (that's the point of listing them).
    /// </summary>
    private void GenerateOffers()
    {
        var rng = new SeededRandom((SeasonId * 4241 + CurrentTeamId) ^ WorldSeed);
        var squad = Repo.SquadPlayers(CurrentTeamId).ToList();
        var targets = squad.OrderByDescending(p => p.OverallRating ?? 0).Take(5)
            .Concat(squad.Where(p => IsTransferListed(p.Id)))
            .DistinctBy(p => p.Id).ToList();
        var buyers = Repo.Teams()
            .Where(t => t.LeagueId is TopFlight or Division2 && t.Id != CurrentTeamId).ToList();
        var offers = new List<TransferOffer>();
        foreach (var p in targets)
        {
            // FM-style (P5): status shapes who gets bids — Surplus attracts vultures at a
            // discount, Fringe players draw modest interest, and bids for your Star arrive
            // rarely but heavy.
            var status = PlayTimeStatusOf(p.Id);
            var chance = IsTransferListed(p.Id) || status == "Surplus to Requirements" ? 85
                : status == "Fringe Player" ? 55
                : status == "Star Player" ? 15 : 35;
            if (rng.Next(100) >= chance || buyers.Count == 0) continue;
            var buyer = buyers[rng.Next(buyers.Count)];
            var mult = status switch
            {
                "Star Player" => 1.45 + rng.Next(30) / 100.0,      // they know what it takes
                "Surplus to Requirements" => 0.75 + rng.Next(20) / 100.0,
                _ => 1.1 + rng.Next(30) / 100.0,
            };
            var fee = (long)(ValuationOf(p.OverallRating ?? 65, p.Age) * mult);
            offers.Add(new TransferOffer(p.Id, p.Name, buyer.Name, fee));
            if (offers.Count == 3) break;
        }
        SaveOffers(offers);
    }

    public string AcceptOffer(int playerId)
    {
        var offer = PendingOffers().FirstOrDefault(o => o.PlayerId == playerId);
        if (offer is null) return "That offer is no longer on the table.";
        var buyerId = Repo.Teams().FirstOrDefault(t => t.Name == offer.FromTeam)?.Id;
        Repo.RemoveSquadMember(CurrentTeamId, playerId);
        // Honour any sell-on clause granted to his old club when you bought him (P5).
        var net = offer.Fee;
        if (GetMeta($"sellon_{playerId}") is { } clause)
        {
            var parts = clause.Split(':');
            if (parts.Length == 2 && int.TryParse(parts[0], out var holder)
                && int.TryParse(parts[1], out var pct) && holder != CurrentTeamId && pct > 0)
            {
                var cut = offer.Fee * pct / 100;
                net -= cut;
                using var pay = Db.Connection.CreateCommand();
                pay.CommandText = "UPDATE teams SET budget = budget + $f WHERE id=$t";
                pay.Parameters.AddWithValue("$f", cut);
                pay.Parameters.AddWithValue("$t", holder);
                pay.ExecuteNonQuery();
                SetMeta($"sellon_{playerId}", "");
                PostInbox("Transfer", $"Sell-on clause honoured: {offer.PlayerName}",
                    $"{TeamName(holder)}'s {pct}% sell-on takes £{cut:N0} out of the £{offer.Fee:N0} fee.");
            }
        }
        Finances.ReceiveTransferFee(net);
        AdjustBudget(net);
        if (buyerId is { } b)
        {
            var used = Repo.Squad(b).Select(s => s.SquadNumber).ToHashSet();
            var shirt = Enumerable.Range(1, 99).FirstOrDefault(n => !used.Contains(n), 99);
            Repo.SetSquadMember(new SquadMemberRow
            { TeamId = b, PlayerId = playerId, SquadNumber = shirt, Slot = Repo.Squad(b).Count });
        }
        using (var t = Db.Connection.CreateCommand())
        {
            t.CommandText = "INSERT INTO transfers(player_id,from_team_id,to_team_id,fee,window,season_id) " +
                            "VALUES($p,$f,$t,$fee,'sale',$s)";
            t.Parameters.AddWithValue("$p", playerId);
            t.Parameters.AddWithValue("$f", CurrentTeamId);
            t.Parameters.AddWithValue("$t", (object?)buyerId ?? DBNull.Value);
            t.Parameters.AddWithValue("$fee", offer.Fee);
            t.Parameters.AddWithValue("$s", SeasonId);
            t.ExecuteNonQuery();
        }
        SaveOffers(PendingOffers().Where(o => o.PlayerId != playerId).ToList());
        _teamCache = null;
        _shooterPool = null;
        PostInbox("Transfer", $"Sold: {offer.PlayerName}",
            $"{offer.PlayerName} joins {offer.FromTeam} for £{offer.Fee:N0}. The fee is in the balance.");
        return $"Sold {offer.PlayerName} to {offer.FromTeam} for £{offer.Fee:N0}.";
    }

    public void RejectOffer(int playerId) =>
        SaveOffers(PendingOffers().Where(o => o.PlayerId != playerId).ToList());

    // ------------------------------------------------------------------ undo + cup conditions

    /// <summary>Undo the most recently recorded result of YOUR fixtures (typos happen).</summary>
    public string UndoLastResult()
    {
        var last = Repo.Fixtures(SeasonId)
            .Where(f => (f.HomeTeamId == CurrentTeamId || f.AwayTeamId == CurrentTeamId) && f.Played)
            .OrderByDescending(f => f.Matchday).ThenByDescending(f => f.Id)
            .FirstOrDefault();
        if (last is null) return "Nothing to undo.";
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText = "DELETE FROM results WHERE fixture_id=$f; " +
                              "DELETE FROM match_events WHERE fixture_id=$f; " +
                              "UPDATE fixtures SET played=0 WHERE id=$f; " +
                              "DELETE FROM meta WHERE key IN ($g1,$g2)";
            cmd.Parameters.AddWithValue("$f", last.Id);
            cmd.Parameters.AddWithValue("$g1", $"cond_applied_{SeasonId}_{last.Matchday}");
            cmd.Parameters.AddWithValue("$g2", $"cond_cup_{SeasonId}_{last.Matchday}");
            cmd.ExecuteNonQuery();
        }
        _results = null;
        _elos = null;
        return $"Undid {TeamName(last.HomeTeamId)} v {TeamName(last.AwayTeamId)} — re-enter the score.";
    }

    /// <summary>Cup-day condition pass: only the two clubs' starters load up — no league-wide double dip.</summary>
    public void UpdateConditionsAfterCup(int homeTeamId, int awayTeamId, int matchday)
    {
        var guard = $"cond_cup_{SeasonId}_{matchday}";
        if (GetMeta(guard) is not null) return;
        foreach (var teamId in new[] { homeTeamId, awayTeamId })
        {
            var conditions = Repo.ConditionsFor(teamId).ToDictionary(c => c.PlayerId);
            foreach (var member in Repo.Squad(teamId).Where(m => m.Slot is >= 0 and <= 10))
            {
                conditions.TryGetValue(member.PlayerId, out var c);
                Repo.UpsertCondition(new PlayerConditionRow
                {
                    PlayerId = member.PlayerId,
                    Fatigue = ConditionModel.AfterStart(c?.Fatigue ?? 0),
                    InjuredUntilMd = RollInjury(matchday, member.PlayerId) ?? c?.InjuredUntilMd,
                    Form = c?.Form ?? 6.5,
                });
            }
        }
        // Cup weeks are matchweeks too: wages, training, loans, scouts, morale and gate money
        // all run — they used to be silently skipped on cup days (P0 fix).
        try
        {
            RunWeeklyEconomy(matchday,
                Repo.Fixtures(SeasonId, matchday).Where(f => f.Kind == "cup").ToList());
        }
        catch { /* the weekly pass never blocks recording */ }
        SetMeta(guard, "1");
    }

    // ------------------------------------------------------------------ career backups

    /// <summary>Copy the career DB to build/backups (kept: last five). Called at open + rollover.</summary>
    public void BackupCareer()
    {
        try
        {
            var source = Db.Connection.DataSource;
            if (string.IsNullOrEmpty(source) || !File.Exists(source)) return;
            var dir = Path.Combine(Path.GetDirectoryName(source)!, "backups");
            Directory.CreateDirectory(dir);
            var dest = Path.Combine(dir, $"master-{DateTime.Now:yyyyMMdd-HHmmss}.db");
            using (var destCon = new SqliteConnection($"Data Source={dest}"))
            {
                destCon.Open();
                Db.Connection.BackupDatabase(destCon);
            }
            foreach (var old in Directory.GetFiles(dir, "master-*.db")
                         .OrderByDescending(f => f).Skip(5))
            {
                File.Delete(old);
            }
        }
        catch { /* a failed backup must never block play */ }
    }
}
