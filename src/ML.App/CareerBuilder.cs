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
    /// for the real interpreter: an ML_PYTHON override, the per-user install, common machine paths,
    /// the Windows py launcher, then finally the bare name.
    /// </summary>
    public static string PythonExe()
    {
        var env = Environment.GetEnvironmentVariable("ML_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return env;

        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var pyRoot = Path.Combine(local, "Programs", "Python");
        if (Directory.Exists(pyRoot))
        {
            var exe = Directory.GetDirectories(pyRoot, "Python3*")
                .OrderByDescending(d => d)
                .Select(d => Path.Combine(d, "python.exe"))
                .FirstOrDefault(File.Exists);
            if (exe is not null) return exe;
        }
        foreach (var p in new[]
                 {
                     @"C:\Python313\python.exe", @"C:\Python312\python.exe", @"C:\Python311\python.exe",
                     @"C:\Program Files\Python313\python.exe", @"C:\Program Files\Python312\python.exe",
                 })
            if (File.Exists(p)) return p;

        var windir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        var py = Path.Combine(windir, "py.exe");
        return File.Exists(py) ? py : "python";
    }

    public static async Task<Session?> BuildAsync(int compId, int rfsId, string teamName, Action<string> log)
    {
        var root = MatchLauncher.FindRepoRoot();
        if (root is null)
        {
            log("Could not find the project (tools/career_seed.py).");
            return null;
        }

        log($"Building {teamName}'s career (squads, tactics, fixtures)…");
        var psi = new ProcessStartInfo
        {
            FileName = PythonExe(),
            WorkingDirectory = root,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.ArgumentList.Add(Path.Combine("tools", "career_seed.py"));
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
            log($"Failed to run the seeder: {ex.Message}. Is Python on PATH?");
            return null;
        }

        // Apply the latest hand-curated squads (2026/27 Liverpool/Arsenal etc.) over the seed, so a
        // fresh career doesn't fall back to the older RFS rosters.
        await RunScript(root, "update_career_squad.py", log);

        return CareerLoader.TryLoad();
    }

    /// <summary>Run any tools/ script with arguments; true on exit code 0. The career vault
    /// (snapshot save/restore) rides through here.</summary>
    public static async Task<bool> RunTool(string script, string[] args, Action<string> log)
    {
        var root = MatchLauncher.FindRepoRoot();
        if (root is null) { log("Could not find the project root."); return false; }
        var psi = new ProcessStartInfo
        {
            FileName = PythonExe(), WorkingDirectory = root,
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

    private static async Task RunScript(string root, string script, Action<string> log)
    {
        var psi = new ProcessStartInfo
        {
            FileName = PythonExe(), WorkingDirectory = root,
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
        }
        catch { /* best-effort overlay; the seed is already usable without it */ }
    }
}
