namespace ML.Web.Data;

/// <summary>Shared UI state: the active career (from meta) plus whichever club a browse screen shows.</summary>
public sealed class AppState
{
    private readonly Db _db;

    public AppState(Db db)
    {
        _db = db;
        Reload();
    }

    public CareerContext? Career { get; private set; }
    public FixtureRow? Next { get; private set; }
    public int Unread { get; private set; }

    /// <summary>Club currently being browsed (defaults to the career club).</summary>
    public long TeamId { get; private set; }
    public string TeamName { get; private set; } = "Master League";

    public event Action? Changed;

    public void Reload()
    {
        Career = _db.Career();
        if (Career is { } c)
        {
            Next = _db.NextFixture(c.TeamId, c.SeasonId);
            Unread = _db.UnreadCount(c.SeasonId);
            if (TeamId == 0) { TeamId = c.TeamId; TeamName = c.TeamName; }
        }
        Changed?.Invoke();
    }

    public void SetTeam(long id, string name)
    {
        if (id == TeamId && name == TeamName) return;
        TeamId = id;
        TeamName = name;
        Changed?.Invoke();
    }

    public string Crest
    {
        get
        {
            var w = TeamName.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (w.Length == 0) return "ML";
            var s = w[0].Length >= 2 ? w[0][..2] : w[0];
            return s.ToUpperInvariant();
        }
    }
}
