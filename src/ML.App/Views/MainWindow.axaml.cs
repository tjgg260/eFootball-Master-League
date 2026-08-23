using System;
using Avalonia.Controls;

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
    }
}
