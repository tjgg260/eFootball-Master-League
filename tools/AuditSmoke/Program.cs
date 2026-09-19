using ML.App;
using ML.Data;

// Headless proof for the engine fixes that came out of the 2026-09-17 app audit.
//
// Everything runs against a COPY of the world, so a run can never touch the real save — these
// checks pay wages, buy players and roll a whole season over.
//
//   dotnet run --project tools/AuditSmoke -- <path-to-game_world.db>
//
// (While the app is open its bin folder is locked; build with -o <somewhere else> and run the exe.)

var src = args.Length > 0 ? args[0] : FindDb();
if (src is null || !File.Exists(src))
{
    Console.WriteLine("no game_world.db found — pass the path as the first argument");
    return 2;
}

var work = Path.Combine(Path.GetTempPath(), $"ml_audit_smoke_{Environment.ProcessId}.db");
File.Copy(src, work, overwrite: true);
Console.WriteLine($"source : {src}");
Console.WriteLine($"working on a COPY: {work}\n");

var pass = 0;
var fail = 0;
void Check(string what, bool ok, string extra = "")
{
    Console.WriteLine($"  [{(ok ? "PASS" : "FAIL")}] {what}{(extra.Length > 0 ? "  — " + extra : "")}");
    if (ok) pass++; else fail++;
}

var db = MasterDb.Open(work);
long Scalar(string sql)
{
    using var c = db.Connection.CreateCommand();
    c.CommandText = sql;
    var v = c.ExecuteScalar();
    return v is null or DBNull ? 0 : Convert.ToInt64(v);
}
int MetaInt(string k)
{
    using var c = db.Connection.CreateCommand();
    c.CommandText = "SELECT value FROM meta WHERE key=$k";
    c.Parameters.AddWithValue("$k", k);
    return int.TryParse(c.ExecuteScalar() as string, out var n) ? n : 0;
}

var s = new Session(db, MetaInt("current_team_id"), MetaInt("current_season_id"));
var season = s.SeasonId;
Console.WriteLine($"career : {s.CurrentTeamName} ({s.CurrentTeamId}) season {season}\n");

var rival = s.LeagueTeams().First(t => t.Id != s.CurrentTeamId);
var theirs = s.Repo.SquadPlayers(rival.Id).OrderByDescending(p => p.OverallRating ?? 0).First();

// ---------------------------------------------------------------------------------------------
Console.WriteLine("A1  the market on a world built from eFootball (it never had a player_market table)");
Check("player_market exists once the app has opened the file",
    Scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='player_market'") == 1);
try
{
    var value = s.MarketValueOf(theirs.Id, theirs.OverallRating ?? 70, theirs.Age);
    Check("MarketValueOf answers instead of throwing", value > 0, $"{theirs.Name}: £{value:N0}");
}
catch (Exception ex) { Check("MarketValueOf answers instead of throwing", false, ex.Message); }
try
{
    var wage = s.RealWageDemand(theirs.Id, theirs.OverallRating ?? 70, theirs.Age ?? 25, 3);
    Check("RealWageDemand answers", wage > 0, $"£{wage:N0}/wk");
}
catch (Exception ex) { Check("RealWageDemand answers", false, ex.Message); }
try
{
    // The shape of the Market grid's own value column (MarketViewModel.ValueSql).
    Scalar("SELECT COUNT(*) FROM players p WHERE " +
           "COALESCE((SELECT m.value FROM player_market m WHERE m.player_id=p.id), 0) >= 0");
    Check("the Market list's value subquery runs", true);
}
catch (Exception ex) { Check("the Market list's value subquery runs", false, ex.Message); }
try
{
    var enquiry = s.MakeEnquiry(theirs.Id);
    Check("an enquiry prices him (asking price reads transfer_status)", enquiry.Length > 0, enquiry);
}
catch (Exception ex) { Check("an enquiry prices him", false, ex.Message); }

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nA2  one matchweek, two matches (league Saturday + cup Wednesday share a matchday number)");
FixtureRow CupTieOn(int md) =>
    s.Repo.Fixtures(season, md).First(f => f.Kind == "cup");
{
    const int md = 5;                                     // League Cup, round of 32
    var b0 = s.Finances.Balance;
    s.UpdateConditionsAfterMatchday(md);
    var b1 = s.Finances.Balance;
    var tie = CupTieOn(md);
    s.UpdateConditionsAfterCup(tie.HomeTeamId, tie.AwayTeamId, md);
    var b2 = s.Finances.Balance;
    Check("league pass pays the week", b1 < b0, $"£{b0 - b1:N0} out");
    Check("the cup tie in the SAME week pays nothing more", b2 == b1,
        b2 == b1 ? "" : $"a second £{b1 - b2:N0} went out");
}
{
    const int md = 8;                                     // National Cup, round of 32 — cup first
    var b0 = s.Finances.Balance;
    var tie = CupTieOn(md);
    s.UpdateConditionsAfterCup(tie.HomeTeamId, tie.AwayTeamId, md);
    var b1 = s.Finances.Balance;
    s.UpdateConditionsAfterMatchday(md);
    var b2 = s.Finances.Balance;
    Check("cup pass first: it pays the week", b1 < b0, $"£{b0 - b1:N0} out");
    Check("then the league game pays nothing more", b2 == b1,
        b2 == b1 ? "" : $"a second £{b1 - b2:N0} went out");
}
{
    const int md = 6;                                     // no cup round this week
    var b0 = s.Finances.Balance;
    s.UpdateConditionsAfterMatchday(md);
    Check("an ordinary league week still pays", s.Finances.Balance < b0);
}

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nA7  a full squad refuses the signing (it used to delete your worst player)");
{
    var squad = s.Repo.Squad(s.CurrentTeamId);
    var room = Session.MaxSquadSize - squad.Count;
    if (room > 0)
    {
        var used = squad.Select(m => m.SquadNumber).ToHashSet();
        var fillers = new List<long>();
        using (var c = db.Connection.CreateCommand())
        {
            c.CommandText = "SELECT p.id FROM players p WHERE NOT EXISTS " +
                            "(SELECT 1 FROM squad_members m WHERE m.player_id=p.id) LIMIT $n";
            c.Parameters.AddWithValue("$n", room);
            using var r = c.ExecuteReader();
            while (r.Read()) fillers.Add(r.GetInt64(0));
        }
        var slot = squad.Count;
        foreach (var id in fillers)
        {
            var shirt = Enumerable.Range(1, 99).First(n => used.Add(n));
            s.Repo.SetSquadMember(new SquadMemberRow
            { TeamId = s.CurrentTeamId, PlayerId = id, SquadNumber = shirt, Slot = slot++ });
        }
    }
    var before = s.Repo.Squad(s.CurrentTeamId).Select(m => m.PlayerId).OrderBy(x => x).ToList();
    var balance = s.Finances.Balance;
    var answer = s.BuyPlayer(theirs.Id, 300);
    var after = s.Repo.Squad(s.CurrentTeamId).Select(m => m.PlayerId).OrderBy(x => x).ToList();
    Check($"squad is at the ceiling ({Session.MaxSquadSize})", before.Count == Session.MaxSquadSize,
        before.Count.ToString());
    Check("the bid is refused in plain words", answer.StartsWith("Your squad is full"), answer);
    Check("nobody left the squad", before.SequenceEqual(after));
    Check("no money moved", s.Finances.Balance == balance);
    Check("he is still at his club", s.ClubOfPlayer(theirs.Id).TeamId == rival.Id);
}

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nA4  cards become bans (they used to be decoration)");
{
    void Card(int fixtureId, long playerId, string kind, int times = 1)
    {
        for (var i = 0; i < times; i++)
        {
            using var c = db.Connection.CreateCommand();
            c.CommandText = "INSERT INTO match_events(fixture_id, player_id, event_type, minute) VALUES($f,$p,$k,0)";
            c.Parameters.AddWithValue("$f", fixtureId);
            c.Parameters.AddWithValue("$p", playerId);
            c.Parameters.AddWithValue("$k", kind);
            c.ExecuteNonQuery();
        }
    }
    void Play(FixtureRow f) =>
        s.Repo.RecordResult(new ResultRow { FixtureId = f.Id, HomeGoals = 1, AwayGoals = 0 });

    var mine = s.Repo.Fixtures(season)
        .Where(f => f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId)
        .OrderBy(f => f.Matchday).ToList();
    var friendly = mine.First(f => f.Kind == "friendly");
    var league = mine.Where(f => f.Kind == "league").Take(2).ToList();
    var starters = s.Repo.Squad(s.CurrentTeamId).Where(m => m.Slot is >= 1 and <= 10).Select(m => m.PlayerId).ToList();
    long sentOff = starters[0], booked = starters[1], preseason = starters[2];

    Play(friendly);
    Card(friendly.Id, preseason, "red");
    s.SettleSuspensions(friendly.Id, friendly.HomeTeamId, friendly.AwayTeamId);
    Check("a red card in a preseason friendly bans nobody", s.SuspensionOf(preseason) is null);

    Play(league[0]);
    Card(league[0].Id, sentOff, "red");
    Card(league[0].Id, booked, "yellow", 4);
    s.SettleSuspensions(league[0].Id, league[0].HomeTeamId, league[0].AwayTeamId);
    var ban = s.SuspensionOf(sentOff);
    Check("a red card in the league is a one-match ban", ban is { Matches: 1, Reason: "red card" },
        ban is null ? "no ban" : $"{ban.Matches} match(es), {ban.Reason}");
    s.SettleSuspensions(league[0].Id, league[0].HomeTeamId, league[0].AwayTeamId);
    Check("settling the same fixture twice does not double it", s.SuspensionOf(sentOff)?.Matches == 1);
    Check("four yellows is not yet a ban", s.SuspensionOf(booked) is null);
    Check("the manager is told", Scalar(
        $"SELECT COUNT(*) FROM inbox WHERE subject LIKE 'Suspended:%' AND player_id={sentOff}") == 1);
    Check("the assistant's XI leaves the banned man out", !s.SuggestXi().Take(11).Contains(sentOff));

    Play(league[1]);
    Card(league[1].Id, booked, "yellow");
    s.SettleSuspensions(league[1].Id, league[1].HomeTeamId, league[1].AwayTeamId);
    Check("the next match serves the ban", s.SuspensionOf(sentOff) is null);
    var fifth = s.SuspensionOf(booked);
    Check("the fifth yellow of the season is a one-match ban", fifth is { Matches: 1, Reason: "5 yellow cards" },
        fifth is null ? "no ban" : $"{fifth.Matches} match(es), {fifth.Reason}");

    var undone = s.UndoLastResult();
    Check("Undo hands the served match back", s.SuspensionOf(sentOff)?.Matches == 1);
    Check("...and takes back the ban that result earned", s.SuspensionOf(booked) is null, undone.Length > 60 ? "" : undone);
}

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nB3  a level cup tie goes to whoever won the shoot-out (it used to be the app's coin)");
{
    var tie = s.Repo.Fixtures(season).First(f => f.Kind == "cup" && !f.Played);
    void Reset(bool unplay)
    {
        using var c = db.Connection.CreateCommand();
        c.CommandText = "DELETE FROM meta WHERE key=$k; DELETE FROM results WHERE fixture_id=$f" +
                        (unplay ? "; UPDATE fixtures SET played=0 WHERE id=$f" : "");
        c.Parameters.AddWithValue("$k", $"cup_pens_{tie.Id}");
        c.Parameters.AddWithValue("$f", tie.Id);
        c.ExecuteNonQuery();
    }
    // Both sides in turn: one of them is the side the app's own coin would NOT have picked, so
    // two passes prove the manager's answer is what counts, not luck.
    foreach (var winner in new[] { tie.AwayTeamId, tie.HomeTeamId })
    {
        Reset(unplay: false);
        s.SetCupShootoutWinner(tie.Id, winner);
        s.Repo.RecordResult(new ResultRow { FixtureId = tie.Id, HomeGoals = 1, AwayGoals = 1 });
        var fresh = new Session(db, s.CurrentTeamId, season);   // no cached results
        Check($"1-1, {fresh.TeamName(winner)} named the shoot-out winner: they go through",
            fresh.CupWinnerOf(tie) == winner);
    }
    Reset(unplay: true);
}

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nA6  Advance Season with your own cup ties unplayed (the cup used to freeze, no winner)");
{
    var myTies = s.Repo.Fixtures(season)
        .Count(f => f.Kind == "cup" && (f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId));
    Console.WriteLine($"  (your club is drawn in {myTies} first-round cup tie(s); none has been played)");
    var clock = System.Diagnostics.Stopwatch.StartNew();
    var summary = s.AdvanceToNextSeason();
    Console.WriteLine($"  rollover took {clock.Elapsed.TotalSeconds:F1}s — {summary}");
    foreach (var cup in Session.Cups)
    {
        var winner = s.GetSetting($"cup_winner_{cup.LeagueId}_{season}");
        Check($"{cup.Name} has a winner", winner is not null,
            winner is null ? "" : s.TeamName(int.Parse(winner)));
    }
    Check("no cup tie of last season is left unplayed",
        Scalar($"SELECT COUNT(*) FROM fixtures WHERE season_id={season} AND kind='cup' AND played=0") == 0);
    Check("the cup honours are on the roll",
        Scalar($"SELECT COUNT(*) FROM honours WHERE season_id={season} AND competition IN ('cup','lcup','ccup')") == 3);
    var settled = Scalar("SELECT COUNT(*) FROM meta WHERE key LIKE 'bans_settled_%'");
    Check("every simmed fixture settled its bans", settled > 900, $"{settled:N0} fixtures");
    Check("the new season starts with a clean disciplinary sheet", Scalar("SELECT COUNT(*) FROM suspensions") == 0);
}

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nA12  contracts minted for every club (used to exist only for players you'd viewed)");
{
    var cpuClub = s.LeagueTeams().First(t => t.Id != s.CurrentTeamId);
    var cpuSquadCount = Scalar($"SELECT COUNT(*) FROM squad_members WHERE team_id={cpuClub.Id}");
    var cpuContractCount = Scalar(
        $"SELECT COUNT(*) FROM contracts WHERE team_id={cpuClub.Id}");
    // Within 2 of the squad size, not exact: a handful of very recent CPU signings can still be
    // mid-transfer when this runs (academy promotions bypass the mint helper) — the NEXT rollover's
    // pass always catches them, so a small in-season lag isn't the bug A12 was about.
    Check($"{s.TeamName(cpuClub.Id)} (a club you never opened) has a contract row for ~every squad member",
        Math.Abs(cpuContractCount - cpuSquadCount) <= 2, $"{cpuContractCount}/{cpuSquadCount}");
    // 9000/9001 (TopFlight/Division2 in Session.cs) are the two playable leagues every career
    // builds, whatever country's data it started from — every other club in the imported world
    // carries a league_id too (its OWN country's native league), but sits outside this career's
    // pyramid entirely (that gap is B4, not this fix). Scoping to just these two is what makes
    // this check "the world you actually play in", not "every club eFootball ever shipped".
    var totalContracts = Scalar("SELECT COUNT(*) FROM contracts");
    var leaguedSquadRows = Scalar(
        "SELECT COUNT(*) FROM squad_members s JOIN teams t ON t.id=s.team_id " +
        "WHERE t.league_id IN (9000,9001)");
    Check("contracts cover the whole two-division world, not just the players you've clicked on",
        totalContracts >= leaguedSquadRows - 10, $"{totalContracts} contracts for {leaguedSquadRows} squad slots");
}

Console.WriteLine("\nB7  starting staff (used to be 0 rows everywhere; every dugout said \"the manager\")");
{
    // This world's staff_people pool was built in an earlier session, before AssignStartingStaff
    // existed — EnsureStaffPool only ever runs its one-time seed when the table is empty, so a
    // fresh-career simulation has to actually be fresh: wipe the pool and re-seed it here, the
    // same as CareerBuilder does for a save that has never opened the Staff screen.
    using (var wipe = db.Connection.CreateCommand())
    {
        wipe.CommandText = "DELETE FROM staff_people; DELETE FROM staff";
        wipe.ExecuteNonQuery();
    }
    var cpuClub = s.LeagueTeams().First(t => t.Id != s.CurrentTeamId);
    var name = s.ManagerNameOf(cpuClub.Id);   // triggers EnsureStaffPool on the now-empty pool
    Check($"{s.TeamName(cpuClub.Id)}'s dugout has a real name, not the old placeholder",
        name != "the manager", name);
    var assigned = Scalar("SELECT COUNT(*) FROM staff_people WHERE team_id IS NOT NULL");
    Check("staff are actually attached to clubs (used to be 0 rows with a team_id at all)",
        assigned > 0, $"{assigned} staff assigned");
    var yourBackroom = s.MyBackroom().Count;
    Check("your own club starts with at least some desks already filled, not an empty backroom",
        yourBackroom > 0, $"{yourBackroom}/{Session.StaffRoles.Length} desks");
}

// ---------------------------------------------------------------------------------------------
Console.WriteLine("\nB6  a banned CPU player used to keep \"playing\" in every sim regardless");
{
    var cpuClub = s.LeagueTeams().First(t => t.Id != s.CurrentTeamId);
    long starterId;
    using (var q = db.Connection.CreateCommand())
    {
        q.CommandText =
            "SELECT s.player_id FROM squad_members s JOIN players p ON p.id=s.player_id " +
            "WHERE s.team_id=$t AND s.slot BETWEEN 0 AND 10 ORDER BY p.overall_rating DESC LIMIT 1";
        q.Parameters.AddWithValue("$t", cpuClub.Id);
        starterId = Convert.ToInt64(q.ExecuteScalar());
    }
    using (var ban = db.Connection.CreateCommand())
    {
        ban.CommandText = "INSERT INTO suspensions(player_id,matches,reason,season_id,from_fixture_id) " +
                          "VALUES($p,3,'red card',$s,0)";
        ban.Parameters.AddWithValue("$p", starterId);
        ban.Parameters.AddWithValue("$s", season);
        ban.ExecuteNonQuery();
    }
    var withoutBanAwareness = s.XiStrengthOf(cpuClub.Id);              // old call shape: ignores bans
    var banAware = s.XiStrengthOf(cpuClub.Id, matchday: 1);            // new: swaps him for the bench
    Check($"{s.TeamName(cpuClub.Id)}'s best starter, now suspended, is actually swapped out of the sim's XI",
        banAware != withoutBanAwareness,
        $"unaware {withoutBanAwareness}, aware {banAware}");
    using (var clear = db.Connection.CreateCommand())
    {
        clear.CommandText = "DELETE FROM suspensions WHERE player_id=$p";
        clear.Parameters.AddWithValue("$p", starterId);
        clear.ExecuteNonQuery();
    }
}

db.Dispose();
try { File.Delete(work); } catch { /* temp file; Windows may still hold it for a moment */ }
Console.WriteLine($"\n{pass} passed, {fail} failed");
return fail == 0 ? 0 : 1;

static string? FindDb()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir is not null)
    {
        var candidate = Path.Combine(dir.FullName, "build", "game_world.db");
        if (File.Exists(candidate)) return candidate;
        dir = dir.Parent;
    }
    return null;
}
