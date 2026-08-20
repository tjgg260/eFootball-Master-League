using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class TacticsView : UserControl
{
    private PitchPlayer? _pressed;   // token under the pointer since press
    private bool _dragging;          // becomes true only after real movement
    private Point _pressPoint;
    private Point _offset;

    // A click is a SELECT; movement beyond this becomes a DRAG. Without the threshold every
    // selection click nudged the token a few pixels and slowly wrecked the shape.
    private const double DragThreshold = 5;

    public TacticsView() => InitializeComponent();

    private void OnPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if ((e.Source as Control)?.DataContext is PitchPlayer p)
        {
            _pressed = p;
            _dragging = false;
            if (DataContext is TacticsViewModel vm)
            {
                // On Lineup a pitch click joins the game's swap flow (click one, click the
                // other); everywhere else it is a plain selection.
                if (vm.ShowLineup) vm.PickXi = p;
                else vm.SelectedPlayer = p;
            }
            _pressPoint = e.GetPosition(Pitch);
            _offset = new Point(_pressPoint.X - p.Left, _pressPoint.Y - p.Top);
            e.Pointer.Capture(Pitch);
        }
    }

    private void OnPointerMoved(object? sender, PointerEventArgs e)
    {
        if (_pressed is null) return;
        // Tokens reposition only on the Set Formation screen (the game's Edit Position);
        // everywhere else a press is a pure select/swap click.
        if (DataContext is TacticsViewModel g && !g.DragEnabled) return;
        var pos = e.GetPosition(Pitch);
        if (!_dragging)
        {
            if (Math.Abs(pos.X - _pressPoint.X) < DragThreshold &&
                Math.Abs(pos.Y - _pressPoint.Y) < DragThreshold)
            {
                return;   // still a click, not a drag
            }
            _dragging = true;
        }
        // Your XI lives on the LEFT half of the horizontal pitch — clamp to it.
        _pressed.Left = Math.Clamp(pos.X - _offset.X, 0, TacticsViewModel.HalfW - TacticsViewModel.TokenW);
        _pressed.Top = Math.Clamp(pos.Y - _offset.Y, 0, TacticsViewModel.PitchH - TacticsViewModel.TokenH);
    }

    private void OnPointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        _pressed = null;
        _dragging = false;
        e.Pointer.Capture(null);
    }
}
