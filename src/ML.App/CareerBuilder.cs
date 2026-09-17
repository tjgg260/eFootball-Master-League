using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace ML.App;

/// <summary>Runs tools/career_seed.py for the chosen club, then loads the resulting career.</summary>
public static class CareerBuilder
{
    /// <summary>
    /// Resolve a working Python. The app is usually launched from Explorer, which does NOT inherit
    /// the shell PATH where Python lives — so "python" alone fails ("is Python installed?"). We look
    /// for the real interpreter: an ML_PYTHON override, the interpreter that ships inside the
    /// download, the per-user install, common machine paths, the Windows py launcher, then finally
    /// the bare name.
    /// </summary>
    public static string PythonExe() => Resolve().Exe;

    /// <summary>
    /// Non-null when we found nothing we are willing to run, with the reason in plain words.
    /// The one case: the download's own <c>python\</c> folder is there but python.exe is not
    /// (half-extracted zip, or antivirus quarantine). Falling through to the bare name there hits
    /// the Microsoft Store stub, which opens the Store, exits, and leaves the build log saying only
    /// "Career build failed" — so we stop and say what actually happened instead.
    /// </summary>
    public static string? PythonProblem => Resolve().Problem;

    private static (string Exe, string? Problem) Resolve()
    {
        // 1. Explicit override — the owner's machine may point at a specific interpreter.
        var env = Environment.GetEnvironmentVariable("ML_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return (env, null);

        // 2. The interpreter that ships in the release, beside tools/. This is what makes a fresh
        //    download work for somebody who has never installed Python.
        var root = MatchLauncher.FindRepoRoot();
        var bundledDir = root is null ? null : Path.Combine(root, "python");
        var bundledExe = bundledDir is null ? null : Path.Combine(bundledDir, "python.exe");
        if (bundledExe is not null && File.Exists(bundledExe)) return (bundledExe, null);

        // 3. Anything already installed on this machine (unchanged).
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var pyRoot = Path.Combine(local, "Programs", "Python");
        if (Directory.Exists(pyRoot))
        {
            var exe = Directory.GetDirectories(pyRoot, "Python3*")
                .OrderByDescending(d => d)
                .Select(d => Path.Combine(d, "python.exe"))
                .FirstOrDefault(File.Exists);
            if (exe is not null) return (exe, null);
        }
        foreach (var p in new[]
                 {
                     @"C:\Python313\python.exe", @"C:\Python312\python.exe", @"C:\Python311\python.exe",
                     @"C:\Program Files\Python313\python.exe", @"C:\Program Files\Python312\python.exe",
                 })
            if (File.Exists(p)) return (p, null);

        var windir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        var py = Path.Combine(windir, "py.exe");
        if (File.Exists(py)) return (py, null);

        // 4. Nothing real anywhere. When we know where the download is, the interpreter that
        //    SHOULD be beside it is the answer — whether its folder is half there or gone
        //    entirely (an unzip that stopped early, antivirus taking the whole directory, app\
        //    copied out on its own). It used to demand the folder still exist, and fell through
        //    to the bare name otherwise — which on a clean Windows 11 is the Microsoft Store stub:
        //    the Store opens, the process exits, and the log says only "Career build failed".
        if (bundledExe is not null)
            return (bundledExe,
                "Python is missing from the download folder — extract the zip again, or check your antivirus quarantine.");

        // No download folder at all (tools/play_match.py not found above us). Nothing else would
        // work in that state either; say so rather than launch the Store.
        return ("python",
            "Couldn't find the download folder (the one holding tools and Play Master League.bat) — extract the zip again and start the app from inside it.");
    }

    /// <summary>
    /// Resolve the interpreter for one launch and name it in the log. A wrong or missing Python is
    /// the commonest reason a seed dies, and the log never said which one it had picked. Null means
    /// there is nothing safe to run, and <paramref name="log"/> has already said why.
    /// Every launch goes through here — Play Match included: it used to take PythonExe() directly,
    /// which skips the Problem check, so the button pressed every matchday was the one place the
    /// Microsoft Store stub could still be launched.
    /// </summary>
    internal static string? LaunchPython(Action<string> log)
    {
        var (exe, problem) = Resolve();
        if (problem is not null)
        {
            log(problem);
            return null;
        }
        log($"Using Python: {exe}");
        return exe;
    }

    public static async Task<Session?> BuildAsync(int compId, int rfsId, string teamName, Action<string> log)
    {
        var root = MatchLauncher.FindRepoRoot();
        if (root is null)
        {
            log("Could not find the project (tools/career_seed.py).");
            return null;
        }

        var python = LaunchPython(log);
        if (python is null) return null;

        log($"Building {teamName}'s career (squads, tactics, fixtures)…");
        var psi = new ProcessStartInfo
        {
            FileName = python,
            WorkingDirectory = root,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        // The seeder used to be given no --db and fell back to its own default, build/master.db —
        // so the picker browsed one world and the career was built in another. It is told exactly
        // which world, and which picker list, the app is looking at.
        var world = WorldFiles.Database;
        var catalog = WorldFiles.Catalog;
        if (world is null || catalog is null)
        {
            log("The world hasn't been built from your eFootball yet — nothing to seed a career into.");
            return null;
        }
        psi.ArgumentList.Add(Path.Combine("tools", "career_seed.py"));
        psi.ArgumentList.Add("--db"); psi.ArgumentList.Add(world);
        psi.ArgumentList.Add("--catalog"); psi.ArgumentList.Add(catalog);
        psi.ArgumentList.Add("--comp-id"); psi.ArgumentList.Add(compId.ToString());
        psi.ArgumentList.Add("--rfs-id"); psi.ArgumentList.Add(rfsId.ToString());
        psi.ArgumentList.Add("--team"); psi.ArgumentList.Add(teamName);
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        // Consent flows through the app's own vault UI ("your current save goes to the vault
        // first") — with this set, career_seed snapshots any active career to /careers before
        // it reseeds, so New Career never destroys a save.
        psi.Environment["ML_CONFIRM_RESEED"] = "1";

        try
        {
            using var proc = new Process { StartInfo = psi };
            proc.OutputDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.ErrorDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await proc.WaitForExitAsync();
            if (proc.ExitCode != 0)
            {
                log("Career build failed.");
                return null;
            }
        }
        catch (Exception ex)
        {
            log($"Couldn't start the career builder ({python}): {ex.Message}");
            return null;
        }

        // The curated 2026/27 squad overlay (update_career_squad.py) is NOT run any more: it writes
        // the curated world's 45-46bn overlay players into whatever database it is handed, and the
        // world is now the one read from the player's own eFootball — its squads ARE the game's.
        // (Ruling 2026-09-13: master.db and its overlays stay in the background until the MVP is proven.)

        return CareerLoader.TryLoad();
    }

    /// <summary>Run any tools/ script with arguments; true on exit code 0. The career vault
    /// (snapshot save/restore) rides through here.</summary>
    public static async Task<bool> RunTool(string script, string[] args, Action<string> log)
    {
        var root = MatchLauncher.FindRepoRoot();
        if (root is null) { log("Could not find the project root."); return false; }
        var python = LaunchPython(log);
        if (python is null) return false;
        var psi = new ProcessStartInfo
        {
            FileName = python, WorkingDirectory = root,
            RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true,
        };
        psi.ArgumentList.Add(Path.Combine("tools", script));
        foreach (var a in args) psi.ArgumentList.Add(a);
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        try
        {
            using var proc = new Process { StartInfo = psi };
            proc.OutputDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.ErrorDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await proc.WaitForExitAsync();
            return proc.ExitCode == 0;
        }
        catch (Exception ex)
        {
            log($"Failed to run {script}: {ex.Message}");
            return false;
        }
    }

    /// <summary>Run a tools/ script with no arguments. Returns its exit code, or -1 when it could
    /// not be started at all — the caller decides whether that matters.</summary>
    private static async Task<int> RunScript(string root, string script, Action<string> log)
    {
        var python = LaunchPython(log);
        if (python is null) return -1;
        var psi = new ProcessStartInfo
        {
            FileName = python, WorkingDirectory = root,
            RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true,
        };
        psi.ArgumentList.Add(Path.Combine("tools", script));
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        try
        {
            using var proc = new Process { StartInfo = psi };
            proc.OutputDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.ErrorDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await proc.WaitForExitAsync();
            return proc.ExitCode;
        }
        catch (Exception ex)
        {
            log($"Couldn't run {script}: {ex.Message}");
            return -1;
        }
    }
}
