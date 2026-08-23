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
    }

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
