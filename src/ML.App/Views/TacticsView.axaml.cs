using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
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

    public TacticsView()
    {
        InitializeComponent();

        // Substitutes: double-tap brings him on for the selected starter (the GK rule lives in
        // the VM's swap, so it is enforced here too); right-click opens the shared player menu.
        // The menu deliberately does NOT move the selection — "⇄ Bring on for <starter>" has to
        // keep meaning the starter you picked on the pitch.
        if (this.FindControl<ListBox>("BenchList") is ListBox bench)
        {
            bench.AddHandler(Gestures.DoubleTappedEvent,
                new EventHandler<TappedEventArgs>((_, e) =>
                {
                    if (DataContext is TacticsViewModel vm && Row<BenchEntry>(e.Source) is { } b)
                    {
                        vm.BringOn(b);
                        e.Handled = true;
                    }
                }), RoutingStrategies.Bubble);
            MlMenu.Attach<BenchEntry>(bench, b => (DataContext as TacticsViewModel)?.MenuForBench(b));
        }

        // The opponent half's header is the CLUB: either button opens its shared menu.
        if (this.FindControl<Border>("OppHeader") is Border header)
        {
            header.AddHandler(InputElement.PointerPressedEvent,
                new EventHandler<PointerPressedEventArgs>((_, e) =>
                {
                    if (Open((DataContext as TacticsViewModel)?.MenuForOpponentClub(), header))
                        e.Handled = true;
                }), RoutingStrategies.Tunnel);
        }
    }

    /// <summary>The nearest ancestor of the event source that is bound to a T (a row/token).</summary>
    private static T? Row<T>(object? source) where T : class
    {
        for (Visual? el = source as Visual; el is not null; el = el.GetVisualParent())
            if (el is StyledElement se && se.DataContext is T t) return t;
        return null;
    }

    private static bool Open(ContextMenu? menu, Control target)
    {
        if (menu is null || menu.Items.Count == 0) return false;
        menu.Placement = PlacementMode.Pointer;
        menu.Open(target);
        return true;
    }

    private void OnPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        var vm = DataContext as TacticsViewModel;
        // Right-click is a MENU, never a select and never the start of a drag: it must not
        // disturb the selection, because the menu's swap items act on the selected starter.
        var right = e.GetCurrentPoint(Pitch).Properties.IsRightButtonPressed;
        var ctx = (e.Source as Control)?.DataContext;

        if (ctx is PitchPlayer p)
        {
            if (right)
            {
                if (Open(vm?.MenuForXi(p), Pitch)) e.Handled = true;
                return;
            }
            _pressed = p;
            _dragging = false;
            if (vm is not null)
            {
                // On Lineup a pitch click joins the game's swap flow (click one, click the
                // other); everywhere else it is a plain selection.
                if (vm.ShowLineup) vm.PickXi = p;
                else vm.SelectedPlayer = p;
            }
            _pressPoint = e.GetPosition(Pitch);
            _offset = new Point(_pressPoint.X - p.Left, _pressPoint.Y - p.Top);
            e.Pointer.Capture(Pitch);
            return;
        }

        // The opponent half: read-only as a lineup, a real entity as a player. Left-click parks
        // him in the left rail's read-only card; right-click opens the shared foreign menu.
        if (ctx is OppToken o)
        {
            if (right) { if (Open(vm?.MenuForOpponent(o), Pitch)) e.Handled = true; }
            else if (vm is not null && o.IsKnown) { vm.OppSelected = o; e.Handled = true; }
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
