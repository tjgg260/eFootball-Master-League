using System.Diagnostics;
using ML.Data;

namespace ML.Sync;

public sealed record CompileOptions
{
    /// <summary>Repo root that holds tools/ and the base CPK tree.</summary>
    public required string RepoRoot { get; init; }

    /// <summary>Extracted base CPK tree to author into (a working, boots-fine base).</summary>
    public required string TreePath { get; init; }

    /// <summary>The archive <see cref="TreePath"/> was extracted from. Changed files are patched into a copy of it.</summary>
    public required string BaseCpk { get; init; }

    /// <summary>Output CPK path.</summary>
    public required string OutputCpk { get; init; }

    public string Python { get; init; } = "python";
}

public sealed record CompileResult(bool Success, string SpecPath, string OutputCpk, string Log);

/// <summary>
/// Compiles the master DB into a dt200 CPK by driving the proven Python authoring pipeline:
/// export the spec, run ml_author.py against the extracted tree, then patch the files that changed
/// into a copy of the base CPK (tools/cpk_patch.py — no full rebuild, so the base's header and
/// alignment survive). The DB is authoritative; this renders it into the game.
/// </summary>
public sealed class Compiler
{
    private readonly CompileOptions _opts;

    public Compiler(CompileOptions opts) => _opts = opts;

    public CompileResult Compile(Repository repo)
    {
        var log = new System.Text.StringBuilder();

        var spec = CompileSpecBuilder.Build(repo);
        var specPath = Path.Combine(_opts.RepoRoot, "build", "compiled_spec.json");
        Directory.CreateDirectory(Path.GetDirectoryName(specPath)!);
        File.WriteAllText(specPath, CompileSpecBuilder.ToJson(spec));
        log.AppendLine($"spec: {spec.Clubs.Count} clubs -> {specPath}");

        var author = Run(_opts.Python,
            $"tools/ml_author.py --tree \"{_opts.TreePath}\" --spec \"{specPath}\"", log);
        if (author != 0)
        {
            return new CompileResult(false, specPath, _opts.OutputCpk, log.ToString());
        }

        var build = Run(_opts.Python,
            $"tools/cpk_patch.py build --base \"{_opts.BaseCpk}\" --tree \"{_opts.TreePath}\" --out \"{_opts.OutputCpk}\"", log);

        var success = build == 0 && File.Exists(_opts.OutputCpk);
        log.AppendLine(success ? $"built {_opts.OutputCpk}" : "cpk build failed");
        return new CompileResult(success, specPath, _opts.OutputCpk, log.ToString());
    }

    /// <summary>Just the spec, for callers that drive the byte pipeline themselves or in tests.</summary>
    public string ExportSpec(Repository repo)
    {
        var specPath = Path.Combine(_opts.RepoRoot, "build", "compiled_spec.json");
        Directory.CreateDirectory(Path.GetDirectoryName(specPath)!);
        File.WriteAllText(specPath, CompileSpecBuilder.ToJson(CompileSpecBuilder.Build(repo)));
        return specPath;
    }

    private int Run(string exe, string args, System.Text.StringBuilder log)
    {
        var psi = new ProcessStartInfo
        {
            FileName = exe,
            Arguments = args,
            WorkingDirectory = _opts.RepoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        using var process = Process.Start(psi);
        if (process is null)
        {
            log.AppendLine($"failed to start {exe}");
            return -1;
        }

        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit();

        // Keep the tail so a long run does not swamp the log.
        var tail = string.Concat(stdout.TakeLast(400)) + stderr;
        log.AppendLine($"$ {Path.GetFileName(exe)} {args}\n{tail.Trim()}");
        return process.ExitCode;
    }
}
