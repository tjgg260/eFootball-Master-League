using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace ML.App;

/// <summary>
/// The Play Match button's engine. Compiles the next fixture's two clubs into dt200 (real RFS
/// squads + translated abilities authored into host slots, rebuilt at align=512, installed into
/// the game folder) and then boots eFootball through Steam. The heavy lifting lives in the proven
/// tools/play_match.py; this just drives it and reports progress back to the UI.
/// </summary>
public static class MatchLauncher
{
    /// <summary>Settings: boot eFootball automatically after a successful compile.</summary>
    public static bool AutoBoot { get; set; } = true;

    private const string SteamAppId = "1665460";

    /// <summary>Walk up from the running app to the repo root (the folder holding tools/play_match.py).</summary>
    public static string? FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "tools", "play_match.py")))
            {
                return dir.FullName;
            }
            dir = dir.Parent;
        }
        return null;
    }

    /// <summary>
    /// Compile home vs away into dt200, install it, then launch eFootball. <paramref name="log"/>
    /// receives progress lines (already marshalled by the caller onto the UI thread if needed).
    /// Returns true only if the CPK built and installed; the game boot is best-effort after that.
    /// </summary>
    public static async Task<bool> PlayMatchAsync(
        int homeId, int awayId, string homeName, string awayName, Action<string> log)
    {
        var root = FindRepoRoot();
        if (root is null)
        {
            log("Could not find the repo (tools/play_match.py). Is the app running from the project?");
            return false;
        }

        log($"Compiling {homeName} vs {awayName} from your career database…");
        var psi = new ProcessStartInfo
        {
            FileName = "python",
            WorkingDirectory = root,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.ArgumentList.Add(Path.Combine("tools", "play_match.py"));
        psi.ArgumentList.Add("--home-id"); psi.ArgumentList.Add(homeId.ToString());
        psi.ArgumentList.Add("--away-id"); psi.ArgumentList.Add(awayId.ToString());
        psi.ArgumentList.Add("--install");
        psi.Environment["PYTHONIOENCODING"] = "utf-8";

        int exit;
        try
        {
            using var proc = new Process { StartInfo = psi };
            proc.OutputDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.ErrorDataReceived += (_, e) => { if (e.Data is not null) log(e.Data); };
            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await proc.WaitForExitAsync();
            exit = proc.ExitCode;
        }
        catch (Exception ex)
        {
            log($"Failed to run the compiler: {ex.Message}");
            log("Make sure Python is installed and on PATH.");
            return false;
        }

        if (exit != 0)
        {
            log("Compile/install failed. If dt200 is locked, close eFootball and try again.");
            return false;
        }

        if (!AutoBoot)
        {
            log("Installed. Auto-boot is off (Settings) — start eFootball from Steam when ready.");
            return true;
        }
        log("Installed. Booting eFootball…");
        try
        {
            Process.Start(new ProcessStartInfo($"steam://rungameid/{SteamAppId}") { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            log($"Built and installed, but couldn't auto-launch eFootball ({ex.Message}). Start it from Steam.");
            return true;
        }

        log($"Open Exhibition → find the host league → {homeName} vs {awayName}. Enjoy the match!");
        return true;
    }
}
