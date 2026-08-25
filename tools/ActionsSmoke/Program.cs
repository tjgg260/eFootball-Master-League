using ML.App;

// Headless proof for the P9-P11 cross-screen action verbs.
//
// Everything runs against a COPY of the career DB, so a smoke run can never touch the real
// save — these verbs sell players and start trials, which is not something a test should do
// to someone's league.
//
//   dotnet run --project tools/ActionsSmoke -- <path-to-master.db>

var src = args.Length > 0 ? args[0] : FindDb();
if (src is null || !File.Exists(src))
{
    Console.WriteLine("no master.db found — pass the path as the first argument");
    return 2;
}

var work = Path.Combine(Path.GetTempPath(), $"ml_actions_smoke_{Environment.ProcessId}.db");
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

var db = ML.Data.MasterDb.Open(work);
int MetaInt(string k)
{
    using var c = db.Connection.CreateCommand();
    c.CommandText = "SELECT value FROM meta WHERE key=$k";
    c.Parameters.AddWithValue("$k", k);
    return int.TryParse(c.ExecuteScalar() as string, out var n) ? n : 0;
}

var s = new Session(db, MetaInt("current_team_id"), MetaInt("current_season_id"));
Console.WriteLine($"career : {s.CurrentTeamName} ({s.CurrentTeamId}) season {s.SeasonId}\n");

var mine = s.Repo.SquadPlayers(s.CurrentTeamId).ToList();
var me = mine.First();
var rival = s.LeagueTeams().First(t => t.Id != s.CurrentTeamId);
var theirs = s.Repo.SquadPlayers(rival.Id).First();
Console.WriteLine($"mine   : {me.Name}\ntheirs : {theirs.Name} ({rival.Name})\n");

Console.WriteLine("identity (what every menu resolves first)");
var (ownClubId, ownClubName) = s.ClubOfPlayer(me.Id);
Check("ClubOfPlayer finds my club", ownClubId == s.CurrentTeamId, ownClubName);
Check("ClubOfPlayer finds theirs", s.ClubOfPlayer(theirs.Id).TeamId == rival.Id);
Check("IsOwnPlayer true for mine", s.IsOwnPlayer(me.Id));
Check("IsOwnPlayer false for theirs", !s.IsOwnPlayer(theirs.Id));
Check("PlayerNameOf round-trips", s.PlayerNameOf(me.Id) == me.Name, s.PlayerNameOf(me.Id));
Check("PlayerNameOf is empty for a bogus id", s.PlayerNameOf(-1).Length == 0);

Console.WriteLine("\nshortlist (new)");
s.SetShortlisted(theirs.Id, true);
Check("add", s.IsShortlisted(theirs.Id) && s.ShortlistIds().Contains(theirs.Id));
s.SetShortlisted(theirs.Id, true);
Check("add is idempotent", s.ShortlistIds().Count(x => x == theirs.Id) == 1);
s.SetShortlisted(theirs.Id, false);
Check("remove", !s.IsShortlisted(theirs.Id));

Console.WriteLine("\nloan list (new — the label the UI already showed)");
s.SetLoanListed(me.Id, true);
Check("add", s.IsLoanListed(me.Id) && s.LoanListedIds().Contains(me.Id));
s.SetLoanListed(me.Id, false);
Check("remove", !s.IsLoanListed(me.Id));

Console.WriteLine("\nenquiry (new — must stay non-committal)");
using (var c = db.Connection.CreateCommand())
{
    c.CommandText = "DELETE FROM negotiations";
    c.ExecuteNonQuery();
}
var enq = s.MakeEnquiry(theirs.Id);
long negRows;
using (var c = db.Connection.CreateCommand())
{
    c.CommandText = "SELECT COUNT(*) FROM negotiations";
    negRows = Convert.ToInt64(c.ExecuteScalar());
}
Check("answers with a number", enq.Length > 0, enq);
Check("writes no negotiation row", negRows == 0);
Check("refuses my own player", s.MakeEnquiry(me.Id).Contains("already your player"),
    s.MakeEnquiry(me.Id));

Console.WriteLine("\noffer to clubs (new)");
var offered = s.OfferToClubs(me.Id);
Check("runs", offered.Length > 0, offered);
Check("puts him on the transfer list", s.IsTransferListed(me.Id));
Check("refuses a player who isn't mine", s.OfferToClubs(theirs.Id).Contains("not in your squad"),
    s.OfferToClubs(theirs.Id));

Console.WriteLine("\ntrial (new — free agents only)");
Check("refuses a contracted player", s.TrialPlayer(theirs.Id).Contains("under contract"),
    s.TrialPlayer(theirs.Id));

Console.WriteLine("\nskill training cancel (new)");
Check("honest when nothing is running", s.CancelSkillTraining(me.Id).Contains("isn't working on a skill"),
    s.CancelSkillTraining(me.Id));
var learnable = s.LearnableSkillsFor(me.Id);
if (learnable.Count > 0)
{
    s.StartSkillTraining(me.Id, learnable[0]);
    var started = s.ActiveSkillTrainings().Any(t => t.PlayerId == me.Id);
    var cancelled = s.CancelSkillTraining(me.Id);
    Check("start then cancel clears the programme",
        started && !s.ActiveSkillTrainings().Any(t => t.PlayerId == me.Id), cancelled);
}
else
{
    Console.WriteLine($"  [skip] {me.Name} can't learn a new skill — nothing to cancel");
}

Console.WriteLine("\njob offers (new decline)");
Check("honest about an offer that isn't there",
    s.DeclineJobOffer(rival.Id).Contains("no longer on the table"), s.DeclineJobOffer(rival.Id));

Console.WriteLine("\nindividual instructions (new: they can name a player)");
s.SetInstruction("attack1", "Anchor Man", me.Id);
Check("name survives", s.InstructionOf("attack1") == "Anchor Man", s.InstructionOf("attack1"));
Check("player survives", s.InstructionPlayerOf("attack1") == me.Id, $"{s.InstructionPlayerOf("attack1")}");
s.SetInstruction("attack1", "Anchor Man");
Check("no player = no orphan id", s.InstructionPlayerOf("attack1") == 0);
Check("bare name still reads", s.InstructionOf("attack1") == "Anchor Man");
s.SetInstruction("attack2", "Off");
Check("cleared slot is clean", s.InstructionOf("attack2") == "Off" && s.InstructionPlayerOf("attack2") == 0);

Console.WriteLine("\nidentity kept for the screens that lost it");
var reps = s.MyMatchReportsWithIds(3);
Check("match reports carry a fixture id", reps.Count == 0 || reps.All(r => r.FixtureId > 0),
    $"{reps.Count} rows");
var youth = s.YouthSquad(s.CurrentTeamId, "u21");
Check("youth squad reads (long ids)", youth.Count >= 0, $"{youth.Count} in the U21s");

// The squad menu can now demote — prove the player lands somewhere real and comes back,
// because a move into a youth side that was never created would lose him entirely.
var kid = mine.Where(p => p.Age is { } a && a <= 21).OrderBy(p => p.OverallRating ?? 0).FirstOrDefault();
if (kid is not null)
{
    var down = s.DemoteToYouth(kid.Id, s.CurrentTeamId, "u21");
    var inYouth = s.YouthSquad(s.CurrentTeamId, "u21").Any(y => y.PlayerId == kid.Id);
    Check("demote to U21 lands him in the U21 squad", inYouth, down);
    // He is in team 9,000,0xx now, not your club — and he is STILL yours. This is the whole
    // point of IsOwnPlayer walking parent_team_id: the shared menu asks this question before
    // it decides whether to offer you the chance to bid for him.
    Check("a lad in my own U21s is still my player", s.IsOwnPlayer(kid.Id),
        s.ClubOfPlayer(kid.Id).Club);
    var up = s.PromoteToSenior(kid.Id, s.CurrentTeamId);
    var backUp = s.Repo.SquadPlayers(s.CurrentTeamId).Any(p => p.Id == kid.Id);
    Check("promote brings him back to the first team", backUp, up);
}
else
{
    Console.WriteLine("  [skip] nobody 21-or-under in the squad to demote");
}

Console.WriteLine("\nboard confidence (one number, re-read every time)");
{
    var before = s.BoardConfidenceNow;
    s.MoveBoardConfidence(-7);
    var after = s.BoardConfidenceNow;
    // The bug this replaces: Session.Board is built once in the constructor, so a verdict
    // written by the season review or a refused budget ask moved a number nothing read back.
    Check("a swing is visible on the very next read", after == Math.Clamp(before - 7, 0, 100),
        $"{before} -> {after}");
    Check("the gauge agrees with the composite", s.BoardNow.Value == s.BoardConfidenceNow);
    Check("the label agrees with the value", s.BoardNow.Label.Length > 0, s.BoardNow.Label);
    s.MoveBoardConfidence(+7);
    Check("and it moves back", s.BoardConfidenceNow == before);
    s.MoveBoardConfidence(-500);
    Check("it cannot be driven below the floor", s.BoardConfidenceNow >= 0, $"{s.BoardConfidenceNow}");
    s.MoveBoardConfidence(+500);
    Check("or above the ceiling", s.BoardConfidenceNow <= 100, $"{s.BoardConfidenceNow}");
}

Console.WriteLine("\nundo (must not re-run the week)");
{
    // A brand-new career has nothing played, and this regression is too expensive to skip —
    // so record one on the COPY. It is the same call the Office makes when you type a score.
    var played = s.Repo.Fixtures(s.SeasonId)
        .Where(f => (f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId) && f.Played)
        .OrderByDescending(f => f.Matchday).FirstOrDefault();
    if (played is null)
    {
        var open = s.Repo.Fixtures(s.SeasonId)
            .FirstOrDefault(f => f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId);
        if (open is not null)
        {
            s.Repo.RecordResult(new ML.Data.ResultRow
            { FixtureId = open.Id, HomeGoals = 2, AwayGoals = 1 });
            played = s.Repo.Fixtures(s.SeasonId).First(f => f.Id == open.Id);
        }
    }
    if (played is null)
    {
        Console.WriteLine("  [skip] this career has no fixture of mine at all");
    }
    else
    {
        // These two keys are the only thing gating RunWeeklyEconomy. Undo used to delete them,
        // so re-recording a corrected score paid the wages twice and took the gate twice.
        var guard = $"cond_applied_{s.SeasonId}_{played.Matchday}";
        var cupGuard = $"cond_cup_{s.SeasonId}_{played.Matchday}";
        s.SetSetting(guard, "1");
        s.SetSetting(cupGuard, "1");
        var said = s.UndoLastResult();
        Check("the matchweek guard survives an undo", s.GetSetting(guard) == "1");
        Check("so does the cup guard", s.GetSetting(cupGuard) == "1");
        Check("the fixture is open again",
            s.Repo.Fixtures(s.SeasonId).First(f => f.Id == played.Id).Played == false);
        Check("and it says what it did NOT undo", said.Contains("stands"), said);
    }
}

Console.WriteLine("\nids that outgrow Int32");
{
    foreach (var prospect in s.AcademyPlayers())
    {
        if (prospect.Id is >= 30_000_000 and < 40_000_000) continue;
        Check("every academy prospect sits in the academy band", false, $"{prospect.Id}");
        break;
    }
    Check("academy reads without truncating", s.AcademyPlayers().All(p => p.Id > 0),
        $"{s.AcademyPlayers().Count} prospects");

    // Player of the Season stores a PLAYER id in the honours team column. Read as an int it
    // came back truncated (often negative) and the archive row lost its name and its menu.
    var big = s.Repo.SquadPlayers(s.CurrentTeamId).OrderByDescending(p => p.Id).First().Id;
    using (var ins = db.Connection.CreateCommand())
    {
        ins.CommandText = "INSERT INTO honours(season_id,competition,team_id) VALUES($s,'pots',$t)";
        ins.Parameters.AddWithValue("$s", s.SeasonId);
        ins.Parameters.AddWithValue("$t", big);
        ins.ExecuteNonQuery();
    }
    var pots = s.HonoursInWithHolders(s.SeasonId).FirstOrDefault(h => h.HolderIsPlayer);
    Check("the archive keeps a player-sized holder id", pots.HolderId == big, $"{pots.HolderId} vs {big}");
    Check("and finds his name", pots.Holder.Length > 0, pots.Holder);
}

db.Connection.Dispose();
try { File.Delete(work); } catch { /* the temp copy can wait for the OS */ }

Console.WriteLine($"\nACTIONS SMOKE: {pass} passed, {fail} failed — the real career was never opened");
return fail == 0 ? 0 : 1;

static string? FindDb()
{
    var dir = AppContext.BaseDirectory;
    for (var i = 0; i < 10 && dir is not null; i++)
    {
        var candidate = Path.Combine(dir, "build", "master.db");
        if (File.Exists(candidate)) return candidate;
        dir = Path.GetDirectoryName(dir.TrimEnd(Path.DirectorySeparatorChar));
    }
    return null;
}
