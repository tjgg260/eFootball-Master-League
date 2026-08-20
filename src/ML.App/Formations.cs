using System.Collections.Generic;
using System.Linq;

namespace ML.App;

/// <summary>Derives a readable formation shape (e.g. "4-3-3") from a formation's slot depths.</summary>
public static class Formations
{
    /// <summary>Cluster the ten outfield players by pitch depth into lines: 4-3-3, 4-2-3-1, ...</summary>
    public static string ShapeOf(IEnumerable<int> ys)
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

    /// <summary>A normal outfield shape: 3–4 lines, each 1–5, ten outfield players in total.</summary>
    public static bool IsStandard(string shape)
    {
        var parts = shape.Split('-');
        if (parts.Length is < 3 or > 4) return false;
        if (!parts.All(p => int.TryParse(p, out var n) && n is >= 1 and <= 5)) return false;
        return parts.Sum(int.Parse) == 10;
    }
}
