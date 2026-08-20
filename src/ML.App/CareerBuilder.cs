using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace ML.App;

/// <summary>Runs tools/career_seed.py for the chosen club, then loads the resulting career.</summary>
public static class CareerBuilder
{
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
            FileName = "python",
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

    private static async Task RunScript(string root, string script, Action<string> log)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "python", WorkingDirectory = root,
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
