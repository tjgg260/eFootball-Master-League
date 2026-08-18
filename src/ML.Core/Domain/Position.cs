namespace ML.Core.Domain;

/// <summary>
/// eFootball's position codes. The numeric values are ours, not the game's — the real
/// mapping comes out of a Player.bin CSV export and belongs in ML.Sync, not here.
/// </summary>
public enum Position
{
    GK,
    CB,
    LB,
    RB,
    DMF,
    CMF,
    AMF,
    LMF,
    RMF,
    LWF,
    RWF,
    SS,
    CF,
}

public enum PositionGroup
{
    Goalkeeper,
    Defender,
    Midfielder,
    Forward,
}

public static class PositionExtensions
{
    public static PositionGroup Group(this Position position) => position switch
    {
        Position.GK => PositionGroup.Goalkeeper,
        Position.CB or Position.LB or Position.RB => PositionGroup.Defender,
        Position.DMF or Position.CMF or Position.AMF or Position.LMF or Position.RMF
            => PositionGroup.Midfielder,
        Position.LWF or Position.RWF or Position.SS or Position.CF => PositionGroup.Forward,
        _ => throw new ArgumentOutOfRangeException(nameof(position), position, null),
    };

    public static bool IsGoalkeeper(this Position position) => position == Position.GK;
}
