using System;
using System.IO;
using Avalonia;

namespace ML.App;

internal static class Program
{
    /// <summary>Crash log written next to the exe so a hard crash leaves a trace we can read.</summary>
    public static readonly string CrashLog = Path.Combine(AppContext.BaseDirectory, "ml-crash.log");

    public static void Log(string where, Exception ex)
    {
        try
        {
            File.AppendAllText(CrashLog,
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {where}\n{ex}\n\n");
        }
        catch { /* logging must never itself throw */ }
    }

    [STAThread]
    public static void Main(string[] args)
    {
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            if (e.ExceptionObject is Exception ex) Log("AppDomain.UnhandledException", ex);
        };
        try
        {
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        }
        catch (Exception ex)
        {
            Log("Main", ex);
            throw;
        }
    }

    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>()
        .UsePlatformDetect()
        .WithInterFont()
        .LogToTrace();
}
