using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using ML.App.ViewModels;
using ML.App.Views;

namespace ML.App;

public partial class App : Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // Fast resume: ML_RESUME=1 skips the picker and opens the saved career directly
            // (used by tooling/screenshot runs; harmless if no career is seeded — falls through).
            if (Environment.GetEnvironmentVariable("ML_RESUME") == "1" && CareerLoader.TryLoad() is Session s)
            {
                desktop.MainWindow = new MainWindow { DataContext = new MainWindowViewModel(s) };
                base.OnFrameworkInitializationCompleted();
                return;
            }

            // Start on the New Career picker: choose any club, and its real league is built and opened.
            var picker = new NewCareerViewModel();
            // A fast resume that could not open the career lands here; say why rather than
            // presenting the picker as if there were no career.
            if (CareerLoader.LastFailure is { } why) picker.Status = why;
            var window = new NewCareerWindow { DataContext = picker };
            picker.CareerStarted += session =>
            {
                var main = new MainWindow { DataContext = new MainWindowViewModel(session) };
                desktop.MainWindow = main;
                main.Show();
                window.Close();
            };
            desktop.MainWindow = window;
        }

        base.OnFrameworkInitializationCompleted();
    }
}
