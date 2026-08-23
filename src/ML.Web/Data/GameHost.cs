using ML.App;

namespace ML.Web.Data;

/// <summary>
/// Holds the live game <see cref="Session"/> — the same engine ML.App runs (board, morale,
/// tactics, market, development), loaded from build/master.db via CareerLoader. Pages that
/// manage the career bind to this; browse-only pages can keep using the lightweight Db.
/// </summary>
public sealed class GameHost
{
    public Session? Session { get; private set; }
    public event Action? Changed;

    public GameHost() => Reload();

    /// <summary>(Re)open the career session — call after seeding a new career.</summary>
    public void Reload()
    {
        try { Session = CareerLoader.TryLoad(); }
        catch { Session = null; }
        Changed?.Invoke();
    }
}
