using ML.Core.Management;

namespace ML.Core.Tests;

public class ManagementTests
{
    [Fact]
    public void BoardConfidenceRisesWithWinsAboveExpectation()
    {
        var board = new BoardConfidence(Expectation.MidTable, starting: 55);
        // winning while sitting 3rd against a 10th-place target
        board.ApplyResult(goalsFor: 2, goalsAgainst: 0, leaguePosition: 3, expectedPosition: 10);
        Assert.True(board.Value > 55);
    }

    [Fact]
    public void BoardConfidenceFallsAndThreatensWithLossesBelowExpectation()
    {
        var board = new BoardConfidence(Expectation.Promotion, starting: 28);
        for (var i = 0; i < 3; i++)
        {
            board.ApplyResult(goalsFor: 0, goalsAgainst: 2, leaguePosition: 18, expectedPosition: 2);
        }
        Assert.True(board.ManagerUnderThreat);
        Assert.Equal("At risk", board.Label);
    }

    [Fact]
    public void ConfidenceStaysInRange()
    {
        var board = new BoardConfidence(Expectation.Title, starting: 98);
        for (var i = 0; i < 10; i++)
        {
            board.ApplyResult(5, 0, leaguePosition: 1, expectedPosition: 1);
        }
        Assert.InRange(board.Value, BoardConfidence.Min, BoardConfidence.Max);
    }

    [Fact]
    public void MoraleCompoundsOnStreaks()
    {
        var winning = new Morale(50);
        var losing = new Morale(50);
        for (var i = 0; i < 4; i++)
        {
            winning.ApplyResult(2, 0);
            losing.ApplyResult(0, 2);
        }
        Assert.True(winning.Value > 70);
        Assert.True(losing.Value < 30);
    }

    [Fact]
    public void FinancesTrackIncomeExpenditureAndRed()
    {
        var money = new Finances(openingBalance: 100_000);
        money.RecordMatchday(attendance: 4_000, ticketPrice: 20);   // +80,000
        money.PayWages(weeklyWageBill: 150_000);                    // -150,000
        Assert.Equal(30_000, money.Balance);
        Assert.False(money.InTheRed);

        Assert.False(money.TrySpendOnTransfer(fee: 50_000, minBalanceAfter: 0)); // would go under floor
        Assert.Equal(30_000, money.Balance);                        // unchanged
        money.PayWages(50_000);
        Assert.True(money.InTheRed);
    }

    [Fact]
    public void InboxEscalatesWhenManagerUnderThreat()
    {
        var board = new BoardConfidence(Expectation.Promotion, starting: 15);
        var morale = new Morale(50);
        var messages = ManagerInbox.AfterResult("Woking", 0, 3, board, morale);
        Assert.Contains(messages, m => m.Category == MessageCategory.Board && m.RequiresAction);
        Assert.Contains(messages, m => m.Category == MessageCategory.Media); // 3-goal margin
    }

    [Fact]
    public void InboxQuietOnARoutineResult()
    {
        var board = new BoardConfidence(Expectation.MidTable, starting: 55);
        var morale = new Morale(55);
        var messages = ManagerInbox.AfterResult("Woking", 1, 1, board, morale);
        Assert.Empty(messages);
    }
}
