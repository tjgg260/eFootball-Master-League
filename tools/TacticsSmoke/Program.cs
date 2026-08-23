using ML.App;

if (args.Length > 0 && args[0] == "gameplan")
{
    // Save a DISTINCTIVE tactic through the same engine call the Blazor Save button makes,
    // so verify_match_build can positively prove geometry+role writes reach dt200.
    var sg = CareerLoader.TryLoad() ?? throw new InvalidOperationException("no career");
    var (f0, _) = sg.OwnFormationIds();
    var cur = sg.Repo.FormationSlots(f0).OrderBy(x => x.SlotIndex).ToList();
    var sq = sg.Squad().OrderBy(x => x.Slot.Slot).ToList();
    var slots2 = new List<(int, int, string, string, int, int)>();
    for (var i = 0; i < cur.Count; i++)
    {
        var pid = i < sq.Count ? sq[i].Player.Id : 0;
        var pos = Visuals.RoleCodeLabel(cur[i].Position);
        var role = pid > 0 ? sg.RoleOf(pid) : "Basic";
        var x = cur[i].X; var y = cur[i].Y;
        if (i == 5) { pos = "CMF"; role = "Box-to-Box"; x = Math.Min(92, x + 4); y = Math.Min(43, y + 3); }
        slots2.Add((i, pid, pos, role, x, y));
    }
    Console.WriteLine($"db conn: {sg.Db.Connection.ConnectionString}");
    Console.WriteLine($"fid0={f0}; cur[5] pre-save: pos={cur[5].Position} x={cur[5].X} y={cur[5].Y}");
    Console.WriteLine($"slots2[5] to write: {slots2[5]}");
    sg.SaveCustomFormation(sg.Repo.TeamTactics(sg.CurrentTeamId).First(t => t.Phase == 0).Style,
        false, slots2, null);
    var back = sg.Repo.FormationSlots(f0).OrderBy(x => x.SlotIndex).ToList();
    Console.WriteLine($"read-back same process: slot5 pos={back[5].Position} x={back[5].X} y={back[5].Y}");
    Console.WriteLine($"saved: slot5 -> CMF/Box-to-Box for {sq[5].Player.Name}");
    return;
}

if (args.Length > 0 && args[0] == "market")
{
    var sm = CareerLoader.TryLoad() ?? throw new InvalidOperationException("no career");
    Console.WriteLine($"career: {sm.CurrentTeamName} ({sm.CurrentTeamId})");

    // pick a negotiation target: a mid player from another club in the career league
    var rival = sm.LeagueTeams().First(t => t.Id != sm.CurrentTeamId);
    var target = sm.Repo.SquadPlayers(rival.Id).First();
    Console.WriteLine($"target: {target.Name} at {rival.Name}");

    var open = sm.StartNegotiation(target.Id);
    Console.WriteLine($"  open: {open}");
    var v = sm.NegotiationFor(target.Id);
    Console.WriteLine($"  PASS? view round={v?.Round} ask={v?.Ask:N0} state={v?.State}");
    if (v is not null)
    {
        var like = sm.DealLikelihood(target.Id, v.Ask, 0, false);
        Console.WriteLine($"  likelihood at ask: {like}%");
        var (msg, agreed, dead) = sm.SendClubOffer(target.Id, v.Ask, 0, false);
        Console.WriteLine($"  offer at ask -> agreed={agreed} dead={dead}: {msg}");
        if (agreed)
        {
            var wage = sm.SigningWageDemand(target.Id, 3);
            Console.WriteLine($"  wage demand (3y): £{wage:N0}/wk — NOT completing (no real signing).");
        }
        sm.WalkAwayFromNegotiation(target.Id);
    }
    // clean the test negotiation row
    using (var cmd = sm.Db.Connection.CreateCommand())
    {
        cmd.CommandText = $"DELETE FROM negotiations WHERE player_id={target.Id}";
        cmd.ExecuteNonQuery();
    }
    Console.WriteLine("cleaned up test negotiation. MARKET SMOKE DONE");
    return;
}

// Headless proof that the Blazor Tactics screen's save path really persists through the shared
// Session engine: load career -> swap two XI players -> move one + change position/role ->
// SaveCustomFormation + SaveSquadOrder -> reload fresh session -> assert everything round-trips.

var s = CareerLoader.TryLoad() ?? throw new InvalidOperationException("no career");
Console.WriteLine($"career: {s.CurrentTeamName} ({s.CurrentTeamId}) season {s.SeasonId}");

var (fid0, _) = s.OwnFormationIds();
var before = s.Repo.FormationSlots(fid0).OrderBy(x => x.SlotIndex).ToList();
var squad = s.Squad().OrderBy(x => x.Slot.Slot).ToList();
Console.WriteLine($"formation {fid0}: {before.Count} slots; squad {squad.Count}; " +
                  $"XI[1]={squad[1].Player.Name}, XI[2]={squad[2].Player.Name}");

// snapshot for restore
var beforeOrder = squad.Select(x => x.Player.Id).ToList();
var beforeStyle = s.Repo.TeamTactics(s.CurrentTeamId).First(t => t.Phase == 0).Style;
var beforeManual = XiManual(s);

// build "UI state": same 11 slots, but swap players 1<->2, move slot 5 and change its position+role
var slots = new List<(int Index, int PlayerId, string Position, string Role, int X, int Y)>();
for (var i = 0; i < before.Count; i++)
{
    var pid = i < squad.Count ? squad[i].Player.Id : 0;
    var pos = Visuals.RoleCodeLabel(before[i].Position);
    var role = pid > 0 ? s.RoleOf(pid) : "Basic";
    slots.Add((i, pid, pos, role, before[i].X, before[i].Y));
}
(slots[1], slots[2]) = ((slots[1].Index, slots[2].PlayerId, slots[1].Position, slots[2].Role, slots[1].X, slots[1].Y),
                        (slots[2].Index, slots[1].PlayerId, slots[2].Position, slots[1].Role, slots[2].X, slots[2].Y));
slots[5] = (5, slots[5].PlayerId, "DMF", "Anchor Man", 52, 20);

s.SaveCustomFormation(styleIndex: 4 /* Out Wide */, fluid: false, slots, null);
var newOrder = slots.Where(x => x.PlayerId > 0).Select(x => x.PlayerId)
    .Concat(squad.Skip(before.Count).Select(x => x.Player.Id)).ToList();
s.SaveSquadOrder(newOrder, manual: true);
Console.WriteLine("saved: style=Out Wide, swap XI 1<->2, slot5 -> DMF/Anchor Man @(52,20)");

// fresh session (new connection) — verify persistence
var s2 = CareerLoader.TryLoad()!;
var after = s2.Repo.FormationSlots(fid0).OrderBy(x => x.SlotIndex).ToList();
var squad2 = s2.Squad().OrderBy(x => x.Slot.Slot).ToList();
var style2 = s2.Repo.TeamTactics(s2.CurrentTeamId).First(t => t.Phase == 0).Style;

void Check(string what, bool ok) => Console.WriteLine($"  {(ok ? "PASS" : "FAIL")}  {what}");
Check("style persisted (4)", style2 == 4);
Check("XI swap persisted", squad2[1].Player.Id == beforeOrder[2] && squad2[2].Player.Id == beforeOrder[1]);
Check("slot5 position=DMF", Visuals.RoleCodeLabel(after[5].Position) == "DMF");
Check("slot5 coords (52,20)", after[5].X == 52 && after[5].Y == 20);
Check("slot5 role=Anchor Man", s2.RoleOf(slots[5].PlayerId) == "Anchor Man");
Check("xi_manual flag set", XiManual(s2));

// ---- restore original state so the user's career is untouched ----
var restore = new List<(int, int, string, string, int, int)>();
for (var i = 0; i < before.Count; i++)
{
    var pid = i < beforeOrder.Count ? beforeOrder[i] : 0;
    restore.Add((i, pid, Visuals.RoleCodeLabel(before[i].Position),
                 pid > 0 ? s.RoleOf(pid) : "Basic", before[i].X, before[i].Y));
}
s2.SaveCustomFormation(beforeStyle, s2.SavedFluid(), restore, null);
s2.SaveSquadOrder(beforeOrder, manual: beforeManual);
Console.WriteLine("restored original formation, XI order and style.");

static bool XiManual(ML.App.Session s)
{
    using var cmd = s.Db.Connection.CreateCommand();
    cmd.CommandText = $"SELECT value FROM meta WHERE key='xi_manual_{s.CurrentTeamId}'";
    return cmd.ExecuteScalar() as string == "1";
}
