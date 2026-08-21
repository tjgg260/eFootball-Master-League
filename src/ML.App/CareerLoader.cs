using System.IO;
using Dapper;
using ML.Data;

namespace ML.App;

/// <summary>
/// Loads the real career from build/master.db (seeded by tools/career_seed.py) if it's present and
/// populated, so the app runs on the actual enriched database — real Serbian squads, coach tactics,
/// fixtures — rather than the in-memory sample. Falls back to the sample when the DB or career meta
/// is missing, so the app always opens to something.
/// </summary>
public static class CareerLoader
{
    public static Session? TryLoad()
    {
        var dbPath = FindMasterDb();
        if (dbPath is null)
        {
            return null;
        }

        // A pending restore (Settings → Restore backup) swaps in before the DB opens —
        // the only moment the file is guaranteed unlocked.
        var pending = Path.Combine(Path.GetDirectoryName(dbPath)!, "master.restore.db");
        if (File.Exists(pending))
        {
            try
            {
                File.Copy(pending, dbPath, overwrite: true);
                File.Delete(pending);
            }
            catch { /* locked? open the current DB; the pending file stays for next launch */ }
        }

        try
        {
            var db = MasterDb.Open(dbPath);
            var teamId = ReadMetaInt(db, "current_team_id");
            var seasonId = ReadMetaInt(db, "current_season_id");
            if (teamId is null || seasonId is null)
            {
                db.Connection.Dispose();
                return null;
            }

            // Only treat it as a real career if the managed club actually has a squad seeded.
            var squadCount = db.Connection.ExecuteScalar<int>(
                "SELECT COUNT(*) FROM squad_members WHERE team_id=@teamId", new { teamId });
            if (squadCount == 0)
            {
                db.Connection.Dispose();
                return null;
            }

            return new Session(db, teamId.Value, seasonId.Value);
        }
        catch
        {
            return null;   // any load problem -> fall back to the sample career
        }
    }

    private static int? ReadMetaInt(MasterDb db, string key)
    {
        var value = db.Connection.QueryFirstOrDefault<string>(
            "SELECT value FROM meta WHERE key=@key", new { key });
        return int.TryParse(value, out var n) ? n : null;
    }

    private static string? FindMasterDb()
    {
        // A shipped package can drop master.db right next to the exe (or in build/ under it);
        // a dev checkout keeps it in the repo's build/. Check the simple spots first, then walk up.
        var baseDir = AppContext.BaseDirectory;
        foreach (var direct in new[]
                 {
                     Path.Combine(baseDir, "master.db"),
                     Path.Combine(baseDir, "build", "master.db"),
                 })
        {
            if (File.Exists(direct)) return direct;
        }
        var dir = new DirectoryInfo(baseDir);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "build", "master.db");
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }
        return null;
    }
}
