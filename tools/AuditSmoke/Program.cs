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
