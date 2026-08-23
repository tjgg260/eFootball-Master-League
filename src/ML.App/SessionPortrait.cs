using Avalonia.Media.Imaging;

namespace ML.App;

/// <summary>Where a player's portrait came from, in the app's fixed precedence order.</summary>
public enum PortraitSource
{
    /// <summary>eFootball's own real/scanned face, rendered from the 3D model. Highest priority.
    /// Populated only once the pak face-asset + render pipeline exists (players.real_face_path).</summary>
    EfootballRealFace,
    /// <summary>An RFS real-photo portrait PNG.</summary>
    Rfs,
    /// <summary>A generated avatar standing in for eFootball's generic 3D face, drawn from the
    /// player's real skin tone + hair colour. Always available — the final fallback.</summary>
    EfootballGeneric,
}

/// <summary>The resolved portrait for a player: the image if one exists, the tier it came from,
/// and the parametric colours used to draw the generic avatar when there is no image.</summary>
public sealed record PortraitInfo(Bitmap? Image, PortraitSource Source, int? SkinTone, int? HairColor);

public sealed partial class Session
{
    /// <summary>
    /// Resolve a player's portrait by the app's precedence:
    ///   1. eFootball real face (3D)  — players.real_face_path, when we have it
    ///   2. RFS real photo            — players.portrait_path
    ///   3. eFootball generic face    — drawn from skin tone + hair colour (never fails)
    /// Tiers 1 and 2 only win if the file actually loads; otherwise we fall through to the avatar.
    /// </summary>
    public PortraitInfo PortraitFor(long playerId)
    {
        string? realFace = null, rfs = null;
        int? skin = null, hair = null;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT p.real_face_path, p.portrait_path, a.skin_tone, a.hair_color " +
                "FROM players p LEFT JOIN player_appearance a ON a.player_id = p.id WHERE p.id=$p";
            cmd.Parameters.AddWithValue("$p", playerId);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                realFace = r.IsDBNull(0) ? null : r.GetString(0);
                rfs = r.IsDBNull(1) ? null : r.GetString(1);
                skin = r.IsDBNull(2) ? null : r.GetInt32(2);
                hair = r.IsDBNull(3) ? null : r.GetInt32(3);
            }
        }

        // Tier 1: eFootball real face from the 3D pipeline (reserved until faces are extractable).
        var img = Visuals.LoadBitmap(realFace);
        if (img is not null) return new PortraitInfo(img, PortraitSource.EfootballRealFace, skin, hair);

        // Tier 2: RFS real photo.
        img = Visuals.LoadBitmap(rfs);
        if (img is not null) return new PortraitInfo(img, PortraitSource.Rfs, skin, hair);

        // Tier 3: generic eFootball face — drawn from the player's own skin + hair colour.
        return new PortraitInfo(null, PortraitSource.EfootballGeneric, skin, hair);
    }
}
