namespace ML.App;

/// <summary>
/// The Avalonia half of the catalog model. Kept out of CatalogData.cs because that file is
/// compile-linked into ML.Web and tools/TacticsSmoke, neither of which references Avalonia —
/// a bitmap property there breaks both builds.
/// </summary>
public sealed partial class CatalogLeague
{
    [System.Text.Json.Serialization.JsonIgnore]
    public Avalonia.Media.Imaging.Bitmap? CompLogoBitmap => Visuals.LoadBitmap(CompLogo);

    [System.Text.Json.Serialization.JsonIgnore]
    public bool HasCompLogo => CompLogoBitmap is not null;
}
