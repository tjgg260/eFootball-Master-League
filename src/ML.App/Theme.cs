using Avalonia;
using Avalonia.Media;

namespace ML.App;

/// <summary>
/// Skin system v1 (Settings): a small set of dynamic theme tokens swapped at runtime.
/// The window ground, panel chrome and accent respond today; per-view inline colours join
/// the token set in the design-polish pass (P6). "Club Colours" pulls the accent from the
/// managed club's real kit colour.
/// </summary>
public static class Theme
{
    public sealed record Skin(string Name, string Bg, string Panel, string PanelAlt, string Accent, string NavHover);

    public static readonly Skin[] Skins =
    {
        new("Midnight", "#0E1116", "#171C24", "#12161C", "#1F9D4D", "#1E2530"),
        new("Club Colours", "#0E1116", "#171C24", "#12161C", "#1F9D4D", "#1E2530"),   // accent overridden
        new("Broadsheet", "#181B20", "#22262D", "#1D2126", "#C8A24A", "#2A2F37"),
        new("Retro PES", "#0B1220", "#12203A", "#0E1830", "#4FA3E0", "#1A2C4E"),
    };

    public static void Apply(string skinName, string? clubAccent = null)
    {
        var skin = Skins.FirstOrDefault(s => s.Name == skinName) ?? Skins[0];
        var accent = skin.Name == "Club Colours" && !string.IsNullOrWhiteSpace(clubAccent)
            ? clubAccent : skin.Accent;
        var res = Application.Current?.Resources;
        if (res is null) return;
        res["ThemeBgBrush"] = Brush(skin.Bg);
        res["ThemePanelBrush"] = Brush(skin.Panel);
        res["ThemePanelAltBrush"] = Brush(skin.PanelAlt);
        res["ThemeAccentBrush"] = Brush(accent!);
        res["ThemeNavHoverBrush"] = Brush(skin.NavHover);
    }

    private static SolidColorBrush Brush(string hex) => new(Color.Parse(hex));
}
