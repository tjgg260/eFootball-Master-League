using System;
using System.IO;

namespace ML.App;

/// <summary>
/// Where the app's world lives. RULING 2026-09-13 (MVP): the app's one database is
/// <c>build/game_world.db</c> — built by tools/game_world.py from the player's own eFootball — with
/// <c>build/game_catalog.json</c> beside it for the New Career picker. The curated
/// <c>build/master.db</c> stays on disk untouched: nothing here ever resolves to it.
///
/// Every screen used to walk up to <c>build/master.db</c> on its own (loader, catalog, vault,
/// market — five copies of the same loop). One resolver means the day the world changes it
/// changes everywhere at once, instead of four screens opening one database and one another.
///
/// Nearest folder wins: the walk starts at the running app and takes the first <c>build/</c> that
/// holds the file. That matters in a git worktree nested inside the owner's checkout, where a walk
/// that kept going would reach the owner's folder above it.
/// </summary>
public static class WorldFiles
{
    public const string DatabaseName = "game_world.db";
    public const string CatalogName = "game_catalog.json";

    /// <summary>The world database, or null when the first run has not built it yet.</summary>
    public static string? Database => FindInBuild(DatabaseName);

    /// <summary>The picker's world list: the one beside the database, or null.</summary>
    public static string? Catalog
    {
        get
        {
            var db = Database;
            if (db is null) return FindInBuild(CatalogName);
            var beside = Path.Combine(Path.GetDirectoryName(db)!, CatalogName);
            return File.Exists(beside) ? beside : null;
        }
    }

    /// <summary>
    /// The eFootball folder the first run found or was shown (build/efootball_dir.txt, which the
    /// Python tools read too), or null. The stats host writes its match exports inside it.
    /// </summary>
    public static string? EFootballDir
    {
        get
        {
            var db = Database;
            var build = db is not null ? Path.GetDirectoryName(db) : BuildDir;
            var file = build is null ? null : Path.Combine(build, "efootball_dir.txt");
            if (file is null || !File.Exists(file)) return null;
            var dir = File.ReadAllText(file).Trim();
            return Directory.Exists(dir) ? dir : null;
        }
    }

    /// <summary>Where the world is written: the download's (or checkout's) build folder.</summary>
    public static string? BuildDir
    {
        get
        {
            var root = MatchLauncher.FindRepoRoot();
            return root is null ? null : Path.Combine(root, "build");
        }
    }

    private static string? FindInBuild(string file)
    {
        var baseDir = AppContext.BaseDirectory;
        var direct = Path.Combine(baseDir, file);
        if (File.Exists(direct)) return direct;
        for (var dir = new DirectoryInfo(baseDir); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "build", file);
            if (File.Exists(candidate)) return candidate;
        }
        return null;
    }
}
