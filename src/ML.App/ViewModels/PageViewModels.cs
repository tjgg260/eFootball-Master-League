using System.Collections.ObjectModel;
using ML.Core.Management;

namespace ML.App.ViewModels;

// --- Dashboard (the MFL "Office") -------------------------------------------------

public sealed class DashboardViewModel : PageViewModel
{
    public DashboardViewModel(Session s)
    {
        ClubName = s.CurrentTeamName;
        LeagueName = s.LeagueName;
        Position = Ordinal(s.CurrentPosition());
        BoardConfidence = s.Board.Value;
        BoardLabel = s.Board.Label;
        Morale = s.Morale.Value;
        MoraleLabel = s.Morale.Label;
        Balance = $"£{s.Finances.Balance:N0}";
        Expectation = s.Board.Expectation.ToString();

        foreach (var f in s.UpcomingFixtures())
        {
            var opp = f.HomeTeamId == s.CurrentTeamId ? s.TeamName(f.AwayTeamId) : s.TeamName(f.HomeTeamId);
            var venue = f.HomeTeamId == s.CurrentTeamId ? "(H)" : "(A)";
            Upcoming.Add($"MD{f.Matchday}   {opp} {venue}");
        }

        foreach (var f in s.RecentResults())
        {
            var r = s.ResultFor(f.Id);
            if (r is null) continue;
            var us = f.HomeTeamId == s.CurrentTeamId ? r.HomeGoals : r.AwayGoals;
            var them = f.HomeTeamId == s.CurrentTeamId ? r.AwayGoals : r.HomeGoals;
            var opp = f.HomeTeamId == s.CurrentTeamId ? s.TeamName(f.AwayTeamId) : s.TeamName(f.HomeTeamId);
            var outcome = us > them ? "W" : us == them ? "D" : "L";
            Form.Add($"{outcome}  {us}-{them}  {opp}");
        }
    }

    public override string Title => "Office";
    public override string Icon => "🏠";

    public string ClubName { get; }
    public string LeagueName { get; }
    public string Position { get; }
    public int BoardConfidence { get; }
    public string BoardLabel { get; }
    public int Morale { get; }
    public string MoraleLabel { get; }
    public string Balance { get; }
    public string Expectation { get; }
    public ObservableCollection<string> Upcoming { get; } = new();
    public ObservableCollection<string> Form { get; } = new();

    private static string Ordinal(int n) => n switch
    {
        0 => "—",
        11 or 12 or 13 => $"{n}th",
        _ when n % 10 == 1 => $"{n}st",
        _ when n % 10 == 2 => $"{n}nd",
        _ when n % 10 == 3 => $"{n}rd",
        _ => $"{n}th",
    };
}

// --- League table -----------------------------------------------------------------

public sealed record TableEntry(
    int Pos, string Team, int P, int W, int D, int L, int GF, int GA, int GD, int Pts, bool IsMine);

public sealed class TableViewModel : PageViewModel
{
    public TableViewModel(Session s)
    {
        foreach (var row in s.Table())
        {
            Rows.Add(new TableEntry(
                row.Position, s.TeamName(row.TeamId.Value), row.Played, row.Won, row.Drawn, row.Lost,
                row.GoalsFor, row.GoalsAgainst, row.GoalDifference, row.Points,
                row.TeamId.Value == s.CurrentTeamId));
        }
    }

    public override string Title => "Table";
    public override string Icon => "📊";
    public ObservableCollection<TableEntry> Rows { get; } = new();
}

// --- Squad ------------------------------------------------------------------------

public sealed record SquadEntry(int Number, string Name, string Position, int Age, int Rating);

public sealed class SquadViewModel : PageViewModel
{
    public SquadViewModel(Session s)
    {
        foreach (var (player, slot) in s.Squad().OrderBy(x => x.Slot.Slot))
        {
            Rows.Add(new SquadEntry(slot.SquadNumber, player.Name, player.Position,
                player.Age ?? 0, player.OverallRating ?? 0));
        }
    }

    public override string Title => "Squad";
    public override string Icon => "👥";
    public ObservableCollection<SquadEntry> Rows { get; } = new();
}

// --- Fixtures ---------------------------------------------------------------------

public sealed record FixtureEntry(string Matchday, string Home, string Away, string Score, bool Played);

public sealed class FixturesViewModel : PageViewModel
{
    public FixturesViewModel(Session s)
    {
        foreach (var f in s.Repo.Fixtures(s.SeasonId)
                     .Where(f => f.HomeTeamId == s.CurrentTeamId || f.AwayTeamId == s.CurrentTeamId))
        {
            var r = f.Played ? s.ResultFor(f.Id) : null;
            var score = r is null ? "v" : $"{r.HomeGoals}-{r.AwayGoals}";
            Rows.Add(new FixtureEntry($"MD{f.Matchday}", s.TeamName(f.HomeTeamId),
                s.TeamName(f.AwayTeamId), score, f.Played));
        }
    }

    public override string Title => "Fixtures";
    public override string Icon => "📅";
    public ObservableCollection<FixtureEntry> Rows { get; } = new();
}

// --- Finances ---------------------------------------------------------------------

public sealed class FinancesViewModel : PageViewModel
{
    public FinancesViewModel(Session s)
    {
        Balance = $"£{s.Finances.Balance:N0}";
        SeasonIncome = $"£{s.Finances.SeasonIncome:N0}";
        SeasonExpenditure = $"£{s.Finances.SeasonExpenditure:N0}";
        WageBill = $"£{s.Squad().Sum(x => 500L + (x.Player.OverallRating ?? 60) * 40):N0} / wk";
        InTheRed = s.Finances.InTheRed;
    }

    public override string Title => "Finances";
    public override string Icon => "💷";
    public string Balance { get; }
    public string SeasonIncome { get; }
    public string SeasonExpenditure { get; }
    public string WageBill { get; }
    public bool InTheRed { get; }
}

// --- Inbox ------------------------------------------------------------------------

public sealed record InboxEntry(string Icon, string Category, string Subject, string Body, bool Action);

public sealed class InboxViewModel : PageViewModel
{
    public InboxViewModel(Session s)
    {
        // A couple of representative reactive messages from current state.
        var pos = s.CurrentPosition();
        var messages = ManagerInbox.AfterResult(
            "Woking", 2, 0, s.Board, s.Morale).ToList();
        messages.Insert(0, new ManagerMessage(MessageCategory.Board,
            $"Season expectations: {s.Board.Expectation}",
            $"The board expects a {s.Board.Expectation} finish. You are currently {pos}th."));

        foreach (var m in messages)
        {
            Rows.Add(new InboxEntry(IconFor(m.Category), m.Category.ToString(), m.Subject, m.Body, m.RequiresAction));
        }
    }

    public override string Title => "Inbox";
    public override string Icon => "✉️";
    public ObservableCollection<InboxEntry> Rows { get; } = new();

    private static string IconFor(MessageCategory c) => c switch
    {
        MessageCategory.Board => "🏛️",
        MessageCategory.Player => "👤",
        MessageCategory.Media => "📰",
        MessageCategory.Transfer => "🔁",
        _ => "•",
    };
}
