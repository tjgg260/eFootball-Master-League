namespace ML.Core.Management;

/// <summary>
/// A club's money model for the MFL finances screen: a running balance fed by matchday income
/// and prize money, drained by wages and transfers. Everything is whole currency units; the UI
/// formats. Balance can go negative here (unlike the engine's budget floor) because the finances
/// view is meant to show a club in the red, with the board reacting to it.
/// </summary>
public sealed class Finances
{
    public Finances(long openingBalance) => Balance = openingBalance;

    public long Balance { get; private set; }

    public long SeasonIncome { get; private set; }

    public long SeasonExpenditure { get; private set; }

    /// <summary>Restore persisted season tallies on load — they survive app restarts.</summary>
    public void RestoreSeasonTallies(long income, long expenditure)
    {
        SeasonIncome = income;
        SeasonExpenditure = expenditure;
    }

    public long MatchdayIncome(int attendance, int ticketPrice) => (long)attendance * ticketPrice;

    public void RecordMatchday(int attendance, int ticketPrice)
    {
        var income = MatchdayIncome(attendance, ticketPrice);
        Balance += income;
        SeasonIncome += income;
    }

    public void PayWages(long weeklyWageBill)
    {
        Balance -= weeklyWageBill;
        SeasonExpenditure += weeklyWageBill;
    }

    public void ReceivePrize(long amount)
    {
        Balance += amount;
        SeasonIncome += amount;
    }

    /// <summary>Returns false and does nothing if the fee would break a hard spending floor.</summary>
    public bool TrySpendOnTransfer(long fee, long minBalanceAfter = long.MinValue)
    {
        if (Balance - fee < minBalanceAfter)
        {
            return false;
        }

        Balance -= fee;
        SeasonExpenditure += fee;
        return true;
    }

    public void ReceiveTransferFee(long fee)
    {
        Balance += fee;
        SeasonIncome += fee;
    }

    public bool InTheRed => Balance < 0;
}
