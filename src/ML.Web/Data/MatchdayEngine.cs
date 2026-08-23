using System.Diagnostics;
using System.IO;
using System.Text;
using ML.Core;
using ML.Core.Simulation;

namespace ML.Web.Data;

/// <summary>
/// Plays out the CPU side of a matchday and compiles/installs the user's fixture into eFootball.
/// CPU results only ever touch OTHER clubs' league fixtures on the same matchday — never any
/// fixture involving the user's club (the cup/league collision guard).
/// </summary>
public sealed class MatchdayEngine
{
    private readonly Db _db;

    public MatchdayEngine(Db db) => _db = db;

    /// <summary>Sim every unplayed league fixture on this matchday except the user's own.</summary>
    public int SimOthers(int leagueId, int seasonId, int matchday, int userTeamId)
    {
        var fixtures = _db.MatchdayFixtures(leagueId, seasonId, matchday)
            .Where(f => !f.Played && f.HomeId != userTeamId && f.AwayId != userTeamId)
            .ToList();
        if (fixtures.Count == 0) return 0;

        var seedBase = int.TryParse(_db.Meta("world_seed"), out var ws) ? ws : 1897;
        var strengths = new Dictionary<int, TeamStrength>();

        TeamStrength StrengthOf(int teamId)
        {
            if (strengths.TryGetValue(teamId, out var s)) return s;
            var avg = _db.Squad(teamId).OrderByDescending(p => p.Rating)
                .Take(11).Select(p => (double)p.Rating).DefaultIfEmpty(60).Average();
            // simple split until per-unit strength lands: attack = avg, defence = avg
            return strengths[teamId] = new TeamStrength(avg, avg);
        }

        foreach (var f in fixtures)
        {
            var sim = new PoissonMatchSimulator(new SeededRandom(unchecked(seedBase * 31 + (int)f.Id)));
            var r = sim.Simulate(StrengthOf(f.HomeId), StrengthOf(f.AwayId));
            _db.RecordResult(f.Id, r.HomeGoals, r.AwayGoals);
        }
        return fixtures.Count;
    }

    /// <summary>Compile both squads into dt200 and install into the game (tools/play_match.py).</summary>
    public async Task<(bool Ok, string Log)> InstallFixtureAsync(int homeId, int awayId)
    {
        var repo = CareerSeeder.RepoRoot;
        var psi = new ProcessStartInfo
        {
            FileName = "python",
            WorkingDirectory = repo,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        psi.ArgumentList.Add(Path.Combine(repo, "tools", "play_match.py"));
        psi.ArgumentList.Add("--home-id"); psi.ArgumentList.Add(homeId.ToString());
        psi.ArgumentList.Add("--away-id"); psi.ArgumentList.Add(awayId.ToString());
        psi.ArgumentList.Add("--install");
        try
        {
            using var proc = Process.Start(psi)!;
            var stdout = await proc.StandardOutput.ReadToEndAsync();
            var stderr = await proc.StandardError.ReadToEndAsync();
            await proc.WaitForExitAsync();
            return (proc.ExitCode == 0, (stdout + "\n" + stderr).Trim());
        }
        catch (Exception ex)
        {
            return (false, $"Could not run python: {ex.Message}");
        }
    }
}
