using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ML.App;

/// <summary>The browsable country → league → club catalog (build/catalog.json, v2 format).</summary>
public sealed class CatalogTeam
{
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("rfs_id")] public int RfsId { get; set; }
    [JsonPropertyName("rating")] public double Rating { get; set; }
    [JsonPropertyName("logo")] public string? Logo { get; set; }
}

public sealed class CatalogLeague
{
    [JsonPropertyName("comp_id")] public int CompId { get; set; }
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("tier")] public int Tier { get; set; }
    [JsonPropertyName("teams")] public List<CatalogTeam> Teams { get; set; } = new();
    public string Summary => $"{Teams.Count} clubs";
}

public sealed class CatalogCountry
{
    [JsonPropertyName("id")] public int Id { get; set; }
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("leagues")] public List<CatalogLeague> Leagues { get; set; } = new();
    public string Summary => $"{Leagues.Count} leagues";
}

public static class CatalogData
{
    public static IReadOnlyList<CatalogCountry> Load()
    {
        var path = Find();
        if (path is null) return new List<CatalogCountry>();
        try
        {
            var doc = JsonSerializer.Deserialize<Root>(File.ReadAllText(path));
            return doc?.Countries ?? new List<CatalogCountry>();
        }
        catch { return new List<CatalogCountry>(); }
    }

    private sealed class Root
    {
        [JsonPropertyName("countries")] public List<CatalogCountry> Countries { get; set; } = new();
    }

    private static string? Find()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "build", "catalog.json");
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }
        return null;
    }
}
