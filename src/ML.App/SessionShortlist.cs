namespace ML.App;

/// <summary>
/// The shortlist — FM's most-used right-click action; feeds the Market filter and the shared
/// context menu. Per-team CSV of player ids in meta, exactly the transfer-list mechanism.
/// </summary>
public sealed partial class Session
{
    /// <summary>Whether a player sits on YOUR club's shortlist.</summary>
    public bool IsShortlisted(long playerId) =>
        (GetMeta($"shortlist_{CurrentTeamId}") ?? "").Split(',').Contains(playerId.ToString());

    /// <summary>Add a player to (or drop him from) YOUR club's shortlist.</summary>
    public void SetShortlisted(long playerId, bool on)
    {
        var ids = (GetMeta($"shortlist_{CurrentTeamId}") ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries).ToHashSet();
        if (on) ids.Add(playerId.ToString());
        else ids.Remove(playerId.ToString());
        SetMeta($"shortlist_{CurrentTeamId}", string.Join(",", ids));
    }

    /// <summary>Every player id on YOUR club's shortlist (empty list, never null).</summary>
    public IReadOnlyList<long> ShortlistIds() =>
        (GetMeta($"shortlist_{CurrentTeamId}") ?? "")
        .Split(',', StringSplitOptions.RemoveEmptyEntries)
        .Where(s => long.TryParse(s, out _)).Select(long.Parse).ToList();
}
