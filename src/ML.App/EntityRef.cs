namespace ML.App;

public enum EntityKind { Player, Club, Fixture, Staff }

/// <summary>
/// A handle to a thing on screen — the payload context menus and focused navigation carry.
/// Row records keep one of these (or the raw id) instead of flattening identity into strings.
/// </summary>
public sealed record EntityRef(EntityKind Kind, long Id, string Name = "")
{
    public static EntityRef Player(long id, string name = "") => new(EntityKind.Player, id, name);
    public static EntityRef Club(long id, string name = "") => new(EntityKind.Club, id, name);
}

/// <summary>A page that can open focused on a specific entity (via Nav.Go's focus payload).</summary>
public interface IFocusTarget
{
    void Focus(EntityRef target);
}
