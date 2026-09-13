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
            // THE BUG: the swap was File.Copy(pending, dbPath, overwrite: true) and nothing else.
            // The live 2.2 GB career was written over with no copy of it taken first, so a restore
            // staged in error — Settings used to offer the python pipeline's snapshots of OTHER
            // worlds in the same list as our own copies — was the last anyone saw of that career.
            // Now the world about to be replaced goes into the vault first, and the overwrite only
            // happens once that copy is on disk with the right number of bytes in it. If the copy
            // cannot be taken, nothing is overwritten: the pending file stays for the next launch
            // and the career that opens is the old one, which is said out loud.
            var problem = KeepPreRestoreCopy(dbPath);
            if (problem is not null)
            {
                LastRestoreProblem = problem;
            }
            else
            {
                try
                {
                    File.Copy(pending, dbPath, overwrite: true);
                    File.Delete(pending);
                    // THE OLD WORLD'S WAL. The live file runs in WAL mode, and SQLite validates
                    // WAL frames against the WAL's own header salts, never against the main file
                    // beside it. So the previous career's master.db-wal, left sitting next to the
                    // freshly restored master.db, would be replayed onto the restored world at the
                    // next open — committed pages from a save that no longer exists, stitched into
                    // one that does. KeepPreRestoreCopy has already carried that -wal into the
                    // -prerestore copy, so nothing is lost by removing it here; leaving it is how a
                    // restore silently corrupts the thing it restored.
                    foreach (var sidecar in new[] { dbPath + "-wal", dbPath + "-shm" })
                    {
                        try { if (File.Exists(sidecar)) File.Delete(sidecar); }
                        catch (Exception ex) { Program.Log("CareerLoader.Restore (stale sidecar)", ex); }
                    }
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

    // Air left on the drive after the pre-restore copy — the same margin Session.BackupCareer
    // keeps, for the same reason: a drive run to zero takes Steam and the game down with it.
    private const long PreRestoreHeadroomBytes = 512L << 20;

    /// <summary>
    /// Copy the career that a pending restore is about to replace into build/backups as
    /// master-yyyyMMdd-HHmmss-prerestore.db, with its hot -wal / -journal if one is on disk, and
    /// verify the copy. Null when the copy is there; otherwise why not, in a manager's words —
    /// and nothing has been written over.
    ///
    /// The '-prerestore' tail is deliberate. Session.BackupCareer's prune owns only names that
    /// are EXACTLY master-&lt;15-character stamp&gt;.db — IsOwnBackupName rejects on length before
    /// it ever parses the stamp — so this file is never counted among the five it keeps and
    /// never deleted by it. It is the one copy of a world the manager chose to leave, and it
    /// stays until they remove it themselves.
    /// </summary>
    private static string? KeepPreRestoreCopy(string dbPath)
    {
        const string prefix = "master-", tail = "-prerestore.db";
        string dest;
        long need;
        try
        {
            var dir = Path.Combine(Path.GetDirectoryName(dbPath)!, "backups");
            Directory.CreateDirectory(dir);
            var stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss", System.Globalization.CultureInfo.InvariantCulture);
            dest = Path.Combine(dir, prefix + stamp + tail);

            need = new FileInfo(dbPath).Length;
            foreach (var sidecar in new[] { "-wal", "-journal" })
                if (File.Exists(dbPath + sidecar)) need += new FileInfo(dbPath + sidecar).Length;

            // Don't start a copy the drive cannot hold. Advisory — an odd root (UNC, subst)
            // simply skips the check — and the copy is still verified below on its own merits.
            long free = -1;
            try { free = new DriveInfo(Path.GetPathRoot(dir)!).AvailableFreeSpace; }
            catch { /* no DriveInfo for this root; the copy is still gated on its own success */ }
            if (free >= 0 && free < need + PreRestoreHeadroomBytes)
            {
                Program.Log("CareerLoader.KeepPreRestoreCopy (skipped: drive full)", new IOException(
                    $"{free:N0} bytes free on {Path.GetPathRoot(dir)}; {need + PreRestoreHeadroomBytes:N0} needed to copy {dbPath}"));
                return $"The restore was NOT applied — the drive has no room to keep a copy of the current " +
                       $"world first (about {(need >> 20):N0} MB is needed in build/backups), and the app will " +
                       "not overwrite a career without one. This is the career you were on before. Free " +
                       "some space and restart to finish restoring; the restore is still queued.";
            }
        }
        catch (Exception ex)
        {
            Program.Log("CareerLoader.KeepPreRestoreCopy (preparing)", ex);
            return PreRestoreCopyFailed;
        }

        var created = new List<string>();
        try
        {
            // overwrite: false — a same-second name can only mean an earlier copy is already
            // here, and a real pre-restore copy is never written over. The restore then simply
            // waits a launch; the alternative was clobbering the one file that undoes a restore.
            File.Copy(dbPath, dest, overwrite: false);
            created.Add(dest);
            foreach (var sidecar in new[] { "-wal", "-journal" })
            {
                if (!File.Exists(dbPath + sidecar)) continue;
                File.Copy(dbPath + sidecar, dest + sidecar, overwrite: false);
                created.Add(dest + sidecar);
            }

            // The copy counts only once it is on disk with every byte of the career in it. An
            // overwrite on the strength of a copy that is short is the exact loss this guards.
            var written = new FileInfo(dest);
            var expected = new FileInfo(dbPath).Length;
            if (!written.Exists || written.Length == 0 || written.Length != expected)
            {
                throw new IOException(
                    $"the copy at {dest} is {(written.Exists ? written.Length : 0):N0} bytes although the career is {expected:N0}");
            }
            return null;
        }
        catch (Exception ex)
        {
            Program.Log($"CareerLoader.KeepPreRestoreCopy ({dest})", ex);
            // Only what THIS attempt wrote is removed: a half-written copy must not sit in the
            // list Restore picks from, and a file that was already there is not ours to touch.
            foreach (var partial in created)
            {
                try { if (File.Exists(partial)) File.Delete(partial); }
                catch (Exception del) { Program.Log($"CareerLoader.KeepPreRestoreCopy delete ({partial})", del); }
            }
            return PreRestoreCopyFailed;
        }
    }

    private const string PreRestoreCopyFailed =
        "The restore was NOT applied — a copy of the current world could not be taken first, and " +
        "the app will not overwrite a career without one. This is the career you were on before. " +
        "Close anything else using the database (or free some space) and restart to finish " +
        "restoring; the restore is still queued, and the detail is in the crash log.";

    private static int? ReadMetaInt(MasterDb db, string key)
    {
        var value = db.Connection.QueryFirstOrDefault<string>(
            "SELECT value FROM meta WHERE key=@key", new { key });
        return int.TryParse(value, out var n) ? n : null;
    }

    // The career lives in the one world the app uses: build/game_world.db (WorldFiles). The name
    // is kept for the callers above; master.db itself is never opened any more (ruling 2026-09-13).
    private static string? FindMasterDb() => WorldFiles.Database;
}
