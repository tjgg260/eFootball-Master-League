using System.Collections.Generic;

namespace ML.App;

/// <summary>A continent for the New Career world-picker: its name, a glyph, and a normalized
/// (0-1) position + accent colour for the stylized world map.</summary>
public sealed record ContinentDef(string Name, string Glyph, double X, double Y, string Accent);

/// <summary>Groups the catalog's countries into continents for the globe → continent → country →
/// league → team drill-down. Football confederation over strict geography (Israel/Turkey/Russia/
/// the Caucasus sit in Europe, as they do in UEFA).</summary>
public static class Continents
{
    public static readonly ContinentDef[] All =
    {
        new("Europe", "🌍", 0.50, 0.30, "#4C8DFF"),
        new("North America", "🌎", 0.19, 0.34, "#F2A63B"),
        new("South America", "🌎", 0.31, 0.68, "#2FBF71"),
        new("Africa", "🌍", 0.52, 0.60, "#E4693B"),
        new("Asia", "🌏", 0.70, 0.37, "#C05CE0"),
        new("Oceania", "🌏", 0.85, 0.75, "#31C6C0"),
    };

    private static readonly Dictionary<string, string> Map = new(System.StringComparer.OrdinalIgnoreCase)
    {
        // South America
        ["Brazil"] = "South America", ["Colombia"] = "South America", ["Argentina"] = "South America",
        ["Venezuela"] = "South America", ["Chile"] = "South America", ["Paraguay"] = "South America",
        ["Bolivia"] = "South America", ["Ecuador"] = "South America", ["Uruguay"] = "South America",
        // North & Central America
        ["United States"] = "North America", ["Mexico"] = "North America", ["Canada"] = "North America",
        ["Jamaica"] = "North America", ["Panama"] = "North America", ["Guatemala"] = "North America",
        ["Honduras"] = "North America", ["Nicaragua"] = "North America",
        // Asia
        ["Saudi Arabia"] = "Asia", ["Japan"] = "Asia", ["China"] = "Asia", ["Korea Republic"] = "Asia",
        ["Iran"] = "Asia", ["Thailand"] = "Asia", ["Uzbekistan"] = "Asia", ["Qatar"] = "Asia",
        ["United Arab Emirates"] = "Asia", ["India"] = "Asia", ["Rest of Asia"] = "Asia",
        // Africa
        ["Egypt"] = "Africa", ["Nigeria"] = "Africa", ["Rest of Africa"] = "Africa", ["Tunisia"] = "Africa",
        ["Algeria"] = "Africa", ["Ghana"] = "Africa", ["Morocco"] = "Africa", ["South Africa"] = "Africa",
        // Oceania
        ["Australia"] = "Oceania",
        // Everything else is Europe (UEFA), incl. the transcontinental members below:
        ["Turkey"] = "Europe", ["Russia"] = "Europe", ["Israel"] = "Europe", ["Kazakhstan"] = "Europe",
        ["Azerbaijan"] = "Europe", ["Armenia"] = "Europe", ["Georgia"] = "Europe",
    };

    public static string Of(string country) =>
        Map.TryGetValue(country, out var c) ? c : "Europe";
}
