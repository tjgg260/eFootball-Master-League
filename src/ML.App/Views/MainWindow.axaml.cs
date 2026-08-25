using System;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        // Clamp the restored window onto the screen's working area (P6): a position saved
        // against a different monitor layout used to reopen half off the right edge, clipping
        // the player card's grade column.
        Opened += (_, _) =>
        {
            try
            {
                var screen = Screens.ScreenFromWindow(this) ?? Screens.Primary;
                if (screen is null) return;
                var wa = screen.WorkingArea;
                var scale = screen.Scaling;
                var w = (int)(Width * scale);
                var h = (int)(Height * scale);
                var x = Math.Max(wa.X, Math.Min(Position.X, wa.X + wa.Width - w));
                var y = Math.Max(wa.Y, Math.Min(Position.Y, wa.Y + wa.Height - h));
                if (x != Position.X || y != Position.Y)
                    Position = new Avalonia.PixelPoint(x, y);
            }
            catch { /* a clamp must never break startup */ }
        };

        // Back / forward on the keyboard. The arrows in the sidebar carry a tooltip naming where
        // they lead, but a tooltip is not discoverability — every browser, file manager and IDE
        // binds these two, and a user who never notices the buttons still reaches for Alt+Left.
        // Tunnel, so a focused grid or text box cannot swallow them first.
        AddHandler(KeyDownEvent, (_, e) =>
        {
            if (e.KeyModifiers != KeyModifiers.Alt) return;
            if (DataContext is not MainWindowViewModel vm) return;
            if (e.Key == Key.Left && vm.GoBackCommand.CanExecute(null))
            {
                vm.GoBackCommand.Execute(null);
                e.Handled = true;
            }
            else if (e.Key == Key.Right && vm.GoForwardCommand.CanExecute(null))
            {
                vm.GoForwardCommand.Execute(null);
                e.Handled = true;
            }
        }, RoutingStrategies.Tunnel);
    }
}
