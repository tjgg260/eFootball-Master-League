using System.Text.RegularExpressions;
using ML.Data;

namespace ML.Ingest;

/// <summary>
/// Turns confirmed <see cref="MatchStats"/> into rows in the master DB: the result, the stats
/// blob, and a match event per scorer. Scorer names — the field OCR fumbles most — are resolved
/// against the two match squads, so a slightly-misread surname still lands on the right player.
/// </summary>
public sealed class ResultImporter
{
    private readonly Repository _repo;

    public ResultImporter(Repository repo) => _repo = repo;

    public sealed record Scorer(string RawName, int Minute, int? ResolvedPlayerId);

    /// <summary>Parses "Milnes 23', Creaney 67'" style lines into (name, minute) pairs.</summary>
    public static IReadOnlyList<(string Name, int Minute)> ParseScorers(string raw)
    {
        var results = new List<(string, int)>();
        foreach (Match m in Regex.Matches(raw, @"([A-Za-zÀ-ÿ'.\- ]+?)\s*(\d{1,3})\s*[’'`]"))
        {
            var name = m.Groups[1].Value.Trim(' ', ',', '-');
            if (name.Length >= 2 && int.TryParse(m.Groups[2].Value, out var minute) && minute is > 0 and <= 120)
            {
                results.Add((name, minute));
            }
        }
        return results;
    }

    /// <summary>
    /// Best-effort resolve a read surname to a player in one of the two squads. Exact surname
    /// wins; otherwise the closest by edit distance, but only if it is close enough to trust.
    /// </summary>
    public static int? ResolveScorer(string readName, IEnumerable<(int PlayerId, string Name)> squads)
    {
        var candidates = squads.ToList();
        var surname = readName.Split(' ').Last().ToLowerInvariant();

        var exact = candidates.FirstOrDefault(c =>
            c.Name.Split(' ').Last().Equals(surname, StringComparison.OrdinalIgnoreCase));
        if (exact.PlayerId != 0)
        {
            return exact.PlayerId;
        }

        var best = candidates
            .Select(c => (c.PlayerId, Dist: Levenshtein(surname, c.Name.Split(' ').Last().ToLowerInvariant())))
            .OrderBy(c => c.Dist)
            .FirstOrDefault();
        return best.Dist <= 2 ? best.PlayerId : null;
    }

    public void Import(
        int fixtureId,
        MatchStats stats,
        IEnumerable<(int PlayerId, string Name)> matchSquads,
        string? screenshotPath = null)
    {
        _repo.RecordResult(new ResultRow
        {
            FixtureId = fixtureId,
            HomeGoals = stats.HomeScore.Value,
            AwayGoals = stats.AwayScore.Value,
            StatsJson = stats.ToStatsJson(),
            ScreenshotPath = screenshotPath,
        });

        var squads = matchSquads.ToList();
        foreach (var (name, minute) in ParseScorers(stats.ScorersRaw.Value ?? string.Empty))
        {
            var playerId = ResolveScorer(name, squads);
            _repo.AddMatchEvent(fixtureId, playerId, "goal", minute);
        }
    }

    private static int Levenshtein(string a, string b)
    {
        var d = new int[a.Length + 1, b.Length + 1];
        for (var i = 0; i <= a.Length; i++) d[i, 0] = i;
        for (var j = 0; j <= b.Length; j++) d[0, j] = j;
        for (var i = 1; i <= a.Length; i++)
            for (var j = 1; j <= b.Length; j++)
                d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1),
                    d[i - 1, j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1));
        return d[a.Length, b.Length];
    }
}
