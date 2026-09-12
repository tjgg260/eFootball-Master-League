using System.IO;
using Dapper;
using Microsoft.Data.Sqlite;
using ML.Data;

namespace ML.App;

/// <summary>
/// Loads the real career from build/master.db (seeded by tools/career_seed.py) if it's present and
/// populated, so the app runs on the actual enriched database — real Serbian squads, coach tactics,
/// fixtures — rather than the in-memory sample. Falls back to the sample when the DB or career meta
/// is missing, so the app always opens to something.
///
/// Two very different things used to look identical to a caller: "there is no career here yet" and
/// "your career is right there and I could not open it". <see cref="LastFailure"/> tells them apart
/// so a locked file never presents itself as a fresh save at another club.
/// </summary>
public static class CareerLoader
{
    /// <summary>
    /// Why the last <see cref="TryLoad"/> came back empty, in words a manager can read — or null
    /// when it loaded fine, or when there simply is no career on disk yet. Whatever falls back to
    /// the sample career shows this, because a transient lock on the real database used to land the
    /// manager at another club with no explanation at all.
    /// </summary>
    public static string? LastFailure { get; private set; }

    /// <summary>The exception behind <see cref="LastFailure"/>, for the crash log.</summary>
    public static Exception? LastError { get; private set; }

    /// <summary>The database the last attempt was reading, even when it could not be opened.</summary>
    public static string? LastPath { get; private set; }

    /// <summary>
    /// Non-null when a restore queued by Settings → Restore backup could not be swapped in on this
    /// attempt. The career that opens is then the OLD one, which is worth saying out loud.
    /// </summary>
    public static string? LastRestoreProblem { get; private set; }

    public static Session? TryLoad()
    {
        LastFailure = null;
        LastError = null;
        LastRestoreProblem = null;

        var dbPath = FindMasterDb();
        LastPath = dbPath;
        if (dbPath is null)
        {
            return null;   // no database at all: not a failure, just no career yet
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
            catch (Exception ex)
            {
                // Locked? Open the current DB; the pending file stays for next launch. Say so —
                // silently opening the career the restore was meant to replace looks like the
                // restore worked and then lost everything.
                LastRestoreProblem =
                    "The save you restored could not be swapped in — this is the career you were on " +
                    "before. Close anything else using the database and restart to finish restoring.";
                Program.Log("CareerLoader.PendingRestore", ex);
            }
        }

        MasterDb? db = null;
        try
        {
            db = MasterDb.Open(dbPath);

            // A skipped honours rebuild is not a load failure — it costs one award row — but it is
            // worth a line in the log, since it means the file was locked or read-only.
            if (db.HonoursRebuildError is { } rebuild)
                Program.Log("MasterDb.DropHonoursTeamFk (skipped; costs the Player of the Season row)", rebuild);

            var teamId = ReadMetaInt(db, "current_team_id");
            var seasonId = ReadMetaInt(db, "current_season_id");
            if (teamId is null || seasonId is null)
            {
                db.Dispose();
                return null;   // a database, but no career started in it
            }

            // Only treat it as a real career if the managed club actually has a squad seeded.
            var squadCount = db.Connection.ExecuteScalar<int>(
                "SELECT COUNT(*) FROM squad_members WHERE team_id=@teamId", new { teamId });
            if (squadCount == 0)
            {
                db.Dispose();
                return null;   // a career row with no squad behind it: nothing to manage
            }

            return new Session(db, teamId.Value, seasonId.Value);
        }
        catch (Exception ex)
        {
            // THE BUG: this catch returned null and said nothing, and the caller then opened the
            // built-in sample career instead — so a database locked for a few seconds by a python
            // tool looked exactly like "the app lost my save and put me at another club".
            db?.Dispose();   // never leave a half-open career holding the file's lock
            LastError = ex;
            LastFailure = Explain(ex);
            Program.Log($"CareerLoader.TryLoad ({dbPath})", ex);
            return null;
        }
    }

    // SQLite primary result codes we can turn into something a manager can act on.
    private const int Busy = 5, Locked = 6, ReadOnly = 8, Corrupt = 11, CantOpen = 14, NotADatabase = 26;

    /// <summary>Turn a load failure into a sentence that says what happened and what to do.</summary>
    private static string Explain(Exception ex) => ex switch
    {
        SqliteException s when s.SqliteErrorCode is Busy or Locked =>
            "Your career is open in another program — the career seeder or a database editor is " +
            "probably still holding it. Close it and try again; nothing has been lost.",
        SqliteException s when s.SqliteErrorCode == ReadOnly =>
            "Your career file is read-only, so it could not be opened for play. Clear the " +
            "read-only flag on it and try again.",
        SqliteException s when s.SqliteErrorCode == CantOpen =>
            "Your career file could not be opened — it may have moved, or its folder is out of reach.",
        SqliteException s when s.SqliteErrorCode is Corrupt or NotADatabase =>
            "Your career file looks damaged. Restore the most recent copy from the career vault.",
        UnauthorizedAccessException or IOException =>
            "Windows would not let the app read your career file — another program may be using it.",
        _ => $"Your career could not be opened: {ex.Message}",
    };

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
