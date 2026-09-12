using System.Linq;
using System.Reflection;
using Dapper;
using Microsoft.Data.Sqlite;

namespace ML.Data;

/// <summary>
/// The master database — the single source of truth for the Master League. Open it against a
/// file path (or ":memory:" for tests); the schema is created on first open.
/// </summary>
public sealed class MasterDb : IDisposable
{
    private readonly SqliteConnection _connection;

    private MasterDb(SqliteConnection connection) => _connection = connection;

    public SqliteConnection Connection => _connection;

    public static MasterDb Open(string path)
    {
        var connection = new SqliteConnection($"Data Source={path}");
        connection.Open();
        var db = new MasterDb(connection);
        db.EnsureSchema();
        return db;
    }

    /// <summary>An in-memory database that lives as long as the returned instance.</summary>
    public static MasterDb OpenInMemory()
    {
        var connection = new SqliteConnection("Data Source=:memory:");
        connection.Open();
        var db = new MasterDb(connection);
        db.EnsureSchema();
        return db;
    }

    private void EnsureSchema()
    {
        _connection.Execute("PRAGMA foreign_keys = ON;");
        _connection.Execute(SchemaSql());
        Migrate();
    }

    /// <summary>
    /// Additive column migrations for DBs created before a column existed. SQLite has no
    /// ADD COLUMN IF NOT EXISTS, so we probe pragma_table_info first. Idempotent.
    /// </summary>
    private void Migrate()
    {
        void AddColumn(string table, string col, string decl)
        {
            var has = _connection.Query<string>($"SELECT name FROM pragma_table_info('{table}')")
                .Any(n => n == col);
            if (!has) _connection.Execute($"ALTER TABLE {table} ADD COLUMN {col} {decl}");
        }
        AddColumn("teams", "parent_team_id", "INTEGER");
        AddColumn("teams", "team_kind", "TEXT NOT NULL DEFAULT 'first'");
        AddColumn("players", "personality", "TEXT");
        AddColumn("player_playstyles", "kind", "TEXT NOT NULL DEFAULT 'primary'");
        // These five reached build/master.db through the python pipeline and were never added to
        // schema.sql, so the file and the live database had drifted apart: queries written against
        // the live database ("WHERE superseded_by IS NULL", COALESCE(real_face_path, portrait_path),
        // the inbox insert's player_id/team_id, the portrait read's hair_color) threw "no such
        // column" on every database created from the schema. Fixed in both places — the schema for
        // a new file, these migrations for a file that predates the column.
        AddColumn("players", "real_face_path", "TEXT");
        AddColumn("players", "superseded_by", "INTEGER");
        AddColumn("inbox", "player_id", "INTEGER");
        AddColumn("inbox", "team_id", "INTEGER");
        AddColumn("player_appearance", "hair_color", "INTEGER");
        DropHonoursTeamFk();
    }

    /// <summary>
    /// Non-null when the honours rebuild below could not run on this open — the file was locked by
    /// another process, or read-only. The career is entirely usable without it; the one cost is the
    /// Player of the Season row. Hosts log this; nothing should treat it as a failed open.
    /// </summary>
    public Exception? HonoursRebuildError { get; private set; }

    /// <summary>
    /// Rebuild `honours` without its foreign key on team_id. CREATE TABLE IF NOT EXISTS cannot
    /// change an existing table, so every database made before the schema was corrected still
    /// carries REFERENCES teams(id) — and with foreign_keys = ON that rejected the Player of the
    /// Season row, whose team_id is a PLAYER id. The insert sits inside season rollover's
    /// "the gala never blocks rollover" catch, so the failure was completely silent: no award in
    /// the Roll of Honour, and no end-of-season awards letter, in any career ever played.
    ///
    /// SQLite has no DROP CONSTRAINT, so this is the documented 12-step table rebuild, reduced
    /// to what applies here (no indexes, no triggers, no views on this table). Idempotent: it
    /// looks for the constraint first and does nothing once it is gone.
    ///
    /// It also makes Open() a DDL WRITER on a 2.2 GB career file, and that is the dangerous part.
    /// THE BUG this guards against: any failure here — SQLITE_BUSY while a tool holds the write
    /// lock, a read-only file — used to escape Open(), and the app's career loader turns any
    /// exception into "no career", which drops the manager into a different club with no message.
    /// The FK blocks exactly one insert (Player of the Season), so not dropping it costs a single
    /// award row. Losing the career costs the save. We swallow, record, and carry on.
    /// </summary>
    private void DropHonoursTeamFk()
    {
        try
        {
            var hasFk = _connection
                .Query<string>("SELECT \"table\" FROM pragma_foreign_key_list('honours')",
                    commandTimeout: LockWaitSeconds)
                .Any();
            if (!hasFk) { HonoursRebuildError = null; return; }
            // The rebuild has to run with foreign keys OFF (the pragma is a no-op inside a
            // transaction, so it is toggled around one).
            _connection.Execute("PRAGMA foreign_keys = OFF;");
            try
            {
                _connection.Execute(
                    // IMMEDIATE takes the write lock up front, so a database another process is
                    // writing fails here and now instead of part-way through the rebuild.
                    "BEGIN IMMEDIATE;" +
                    "DROP TABLE IF EXISTS honours_new;" +   // leftover from an attempt that died
                    "CREATE TABLE honours_new (" +
                    "  season_id   INTEGER NOT NULL," +
                    "  competition TEXT    NOT NULL," +
                    "  team_id     INTEGER NOT NULL," +
                    "  PRIMARY KEY (season_id, competition));" +
                    "INSERT INTO honours_new SELECT season_id, competition, team_id FROM honours;" +
                    "DROP TABLE honours;" +
                    "ALTER TABLE honours_new RENAME TO honours;" +
                    "COMMIT;",
                    commandTimeout: LockWaitSeconds);
            }
            finally
            {
                _connection.Execute("PRAGMA foreign_keys = ON;");
            }
            HonoursRebuildError = null;
        }
        catch (Exception ex)
        {
            HonoursRebuildError = ex;
            // Order matters. A half-done rebuild leaves the transaction open, and PRAGMA
            // foreign_keys is a no-op inside a transaction — so the restore in the finally above
            // silently did nothing and has to be repeated after the rollback.
            try { _connection.Execute("ROLLBACK;"); } catch { /* nothing was open */ }
            try { _connection.Execute("DROP TABLE IF EXISTS honours_new;"); } catch { /* still locked */ }
            try { _connection.Execute("PRAGMA foreign_keys = ON;"); } catch { /* connection is gone */ }
        }
    }

    /// <summary>How long a migration waits on another process's write lock before giving up. The
    /// default is 30s per command, which would stall the app's launch on a locked file.</summary>
    private const int LockWaitSeconds = 5;

    private static string SchemaSql()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var name = assembly.GetManifestResourceNames()
            .Single(n => n.EndsWith("schema.sql", StringComparison.Ordinal));
        using var stream = assembly.GetManifestResourceStream(name)!;
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    public T InTransaction<T>(Func<SqliteConnection, SqliteTransaction, T> work)
    {
        using var tx = _connection.BeginTransaction();
        var result = work(_connection, tx);
        tx.Commit();
        return result;
    }

    public void InTransaction(Action<SqliteConnection, SqliteTransaction> work) =>
        InTransaction((c, t) => { work(c, t); return 0; });

    public string? GetMeta(string key) =>
        _connection.QuerySingleOrDefault<string>("SELECT value FROM meta WHERE key = @key", new { key });

    public void SetMeta(string key, string value) =>
        _connection.Execute(
            "INSERT INTO meta(key,value) VALUES(@key,@value) " +
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            new { key, value });

    public void Dispose() => _connection.Dispose();
}
