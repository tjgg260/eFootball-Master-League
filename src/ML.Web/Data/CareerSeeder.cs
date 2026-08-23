using System.Diagnostics;
using System.IO;
using System.Text;

namespace ML.Web.Data;

/// <summary>Runs tools/career_seed.py to start a new career (same path the WPF app used).</summary>
public sealed class CareerSeeder
{
    public static string RepoRoot
    {
        get
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "CLAUDE.md")))
                dir = dir.Parent!;
            return dir?.FullName ?? Directory.GetCurrentDirectory();
        }
    }

    /// <summary>Seed a career for the named club. Returns (success, combined output).</summary>
    public async Task<(bool Ok, string Log)> SeedAsync(string teamName)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "python",
            WorkingDirectory = RepoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        psi.ArgumentList.Add(Path.Combine(RepoRoot, "tools", "career_seed.py"));
        psi.ArgumentList.Add("--team");
        psi.ArgumentList.Add(teamName);

        try
        {
            using var proc = Process.Start(psi)!;
            var stdout = await proc.StandardOutput.ReadToEndAsync();
            var stderr = await proc.StandardError.ReadToEndAsync();
            await proc.WaitForExitAsync();
            var log = (stdout + "\n" + stderr).Trim();
            return (proc.ExitCode == 0, log);
        }
        catch (Exception ex)
        {
            return (false, $"Could not run python: {ex.Message}");
        }
    }
}
