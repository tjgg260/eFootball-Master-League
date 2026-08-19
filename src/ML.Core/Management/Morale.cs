namespace ML.Core.Management;

/// <summary>
/// Squad morale, 0-100, the MFL "squad morale" gauge. Wins lift it, defeats sap it, and a run of
/// either compounds — a settled winning side stays high, a losing streak spirals. Kept simple and
/// deterministic so it is testable and the UI can explain every movement.
/// </summary>
public sealed class Morale
{
    public const int Min = 0;
    public const int Max = 100;

    private int _streak; // + for unbeaten run, - for winless run

    public Morale(int starting = 55) => Value = Math.Clamp(starting, Min, Max);

    public int Value { get; private set; }

    public void ApplyResult(int goalsFor, int goalsAgainst)
    {
        if (goalsFor > goalsAgainst)
        {
            _streak = Math.Max(1, _streak + 1);
            Value += 5 + Math.Min(_streak, 4);          // streak bonus, capped
        }
        else if (goalsFor == goalsAgainst)
        {
            _streak = 0;
            Value += 0;
        }
        else
        {
            _streak = Math.Min(-1, _streak - 1);
            Value -= 5 + Math.Min(-_streak, 4);         // losing run compounds
        }

        Value = Math.Clamp(Value, Min, Max);
    }

    public string Label => Value switch
    {
        >= 80 => "Buoyant",
        >= 60 => "Good",
        >= 40 => "Settled",
        >= 20 => "Low",
        _ => "Rock bottom",
    };
}
