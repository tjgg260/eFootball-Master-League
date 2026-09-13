using Avalonia.Media.Imaging;

namespace ML.App;

/// <summary>Where a player's portrait came from, in the app's fixed precedence order.</summary>
public enum PortraitSource
{
    /// <summary>eFootball's own face: the game's UI thumbnail by PID (players.game_face_path, from
    /// pak\pc1000 via tools/game_faces.py), else the facepack photo (players.real_face_path).</summary>
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
    ///   1. eFootball's own face      — players.game_face_path (game thumbnail), then real_face_path
    ///   2. RFS real photo            — players.portrait_path
    ///   3. eFootball generic face    — drawn from skin tone + hair colour (never fails)
    /// Tiers 1 and 2 only win if the file actually loads; otherwise we fall through to the avatar.
    /// </summary>
    public PortraitInfo PortraitFor(long playerId)
    {
        // Tier 0: the owner's own photo — custom_faces/<player_id>.<ext> beats every pack.
        // Loaded uncached: Visuals' cache would remember a miss forever, and "Set photo"
        // must show up without an app restart.
        if (MatchLauncher.FindRepoRoot() is { } root)
        {
            foreach (var ext in new[] { "png", "jpg", "jpeg", "webp" })
            {
                var custom = System.IO.Path.Combine(root, "custom_faces", $"{playerId}.{ext}");
                if (System.IO.File.Exists(custom))
                {
                    try { return new PortraitInfo(new Bitmap(custom), PortraitSource.Rfs, null, null); }
                    catch { /* unreadable file — fall through to the packs */ }
                }
            }
        }

        string? gameFace = null, realFace = null, rfs = null;
        int? skin = null, hair = null;
        using (var cmd = Db.Connection.CreateCommand())
        {
            cmd.CommandText =
                "SELECT p.game_face_path, p.real_face_path, p.portrait_path, a.skin_tone, a.hair_color " +
                "FROM players p LEFT JOIN player_appearance a ON a.player_id = p.id WHERE p.id=$p";
            cmd.Parameters.AddWithValue("$p", playerId);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                gameFace = r.IsDBNull(0) ? null : r.GetString(0);
                realFace = r.IsDBNull(1) ? null : r.GetString(1);
                rfs = r.IsDBNull(2) ? null : r.GetString(2);
                skin = r.IsDBNull(3) ? null : r.GetInt32(3);
                hair = r.IsDBNull(4) ? null : r.GetInt32(4);
            }
        }

        // Tier 1: eFootball's own face — the game's UI thumbnail by PID, then the facepack photo.
        var img = Visuals.LoadBitmap(gameFace) ?? Visuals.LoadBitmap(realFace);
        if (img is not null) return new PortraitInfo(img, PortraitSource.EfootballRealFace, skin, hair);

        // Tier 2: RFS real photo.
        img = Visuals.LoadBitmap(rfs);
        if (img is not null) return new PortraitInfo(img, PortraitSource.Rfs, skin, hair);

        // Tier 3: generic eFootball face — drawn from the player's own skin + hair colour.
        return new PortraitInfo(null, PortraitSource.EfootballGeneric, skin, hair);
    }
}
