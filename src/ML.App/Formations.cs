using System.Collections.Generic;
using System.Linq;

namespace ML.App;

/// <summary>Derives a readable formation shape (e.g. "4-3-3") from a formation's slot depths.</summary>
public static class Formations
{
    /// <summary>
    /// The formation these slot depths make: 4-3-3, 4-2-3-1, 5-3-2, …
    ///
    /// The clustering below is a reading of the geometry, not a name — it over-splits a line whose
    /// wide players sit a few units deeper than the central pair, so a 3-4-2-1 comes out as
    /// "3-2-2-2-1" and a back five as "3-2-1-2-2". <see cref="FormationCatalog"/> holds the name
    /// each of those readings belongs to; anything it does not name keeps the raw reading.
    /// </summary>
    public static string ShapeOf(IEnumerable<int> ys)
    {
        var lines = LinesOf(ys);
        return FormationCatalog.NameFor(lines) ?? lines;
    }

    /// <summary>Cluster the ten outfield players by pitch depth into lines.</summary>
    private static string LinesOf(IEnumerable<int> ys)
    {
        var outfield = ys.Where(y => y >= 9).OrderBy(y => y).ToList();
        if (outfield.Count == 0) return "—";
        var lines = new List<int>();
        int count = 0, prev = int.MinValue;
        foreach (var y in outfield)
        {
            if (prev != int.MinValue && y - prev > 3) { lines.Add(count); count = 0; }
            count++; prev = y;
        }
        if (count > 0) lines.Add(count);
        return string.Join("-", lines);
    }

    /// <summary>
    /// A shape worth printing by name rather than calling "Custom": one the catalogue names, or a
    /// normal outfield reading — 3–4 lines, each 1–5, ten outfield players in total.
    /// </summary>
    public static bool IsStandard(string shape)
    {
        if (FormationCatalog.IsNamed(shape)) return true;
        var parts = shape.Split('-');
        if (parts.Length is < 3 or > 4) return false;
        if (!parts.All(p => int.TryParse(p, out var n) && n is >= 1 and <= 5)) return false;
        return parts.Sum(int.Parse) == 10;
    }
}
