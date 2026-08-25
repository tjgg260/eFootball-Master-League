using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.VisualTree;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class TacticsView : UserControl
{
    // --- the pitch drag (a starter under the pointer) ---------------------------------
    private PitchPlayer? _pressed;   // token under the pointer since press
    private bool _dragging;          // becomes true only after real movement
    private Point _pressPoint;
    private Point _offset;
    private double _originLeft;      // his slot geometry BEFORE the drag — every refusal path
    private double _originTop;       // springs him back to it, so nothing is left stacked

    // --- the bench drag (a substitute row) --------------------------------------------
    private BenchEntry? _benchPressed;
    private bool _benchDragging;
    private Point _benchPressPoint;

    // --- drag chrome: a ghost that follows the pointer + a drop-target highlight -------
    private Border? _ghost;
    private Border? _highlight;
    private PitchPlayer? _hot;       // the token currently lit as a drop target
    private ListBox? _bench;

    // A click is a SELECT; movement beyond this becomes a DRAG. Without the threshold every
    // selection click nudged the token a few pixels and slowly wrecked the shape.
    private const double DragThreshold = 5;

    public TacticsView()
    {
        InitializeComponent();

        // Substitutes (the touchline strip under the pitch): double-tap brings him on (with no
        // starter picked the VM now falls back to the weakest man he covers rather than
        // lecturing); right-click opens the shared player menu. The menu deliberately does NOT
        // move the selection — "⇄ Bring on for <starter>" has to keep meaning the starter you
        // picked on the pitch. The control is still the ListBox named BenchList: it moved and
        // changed shape, it did not change identity, so every hook below is untouched.
        if (this.FindControl<ListBox>("BenchList") is ListBox bench)
        {
            _bench = bench;
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

            // Bench order decides who comes on first, so it needs a no-mouse path too:
            // Alt+↑/↓ (or Ctrl+↑/↓, since a window's access-key handler can claim Alt) mirror
            // the right-click menu's ▲ Move up / ▼ Move down. The bench is a horizontal
            // TOUCHLINE STRIP now, so ←/→ do the same thing — the gesture has to match the
            // geometry the user is looking at, and ↑/↓ stay because the menu still says ▲/▼.
            bench.AddHandler(InputElement.KeyDownEvent,
                new EventHandler<KeyEventArgs>((_, e) =>
                {
                    if (DataContext is not TacticsViewModel vm) return;
                    if (e.KeyModifiers is not (KeyModifiers.Alt or KeyModifiers.Control)) return;
                    if (e.Key is Key.Up or Key.Left) { vm.MoveBench(vm.PickBench, -1); e.Handled = true; }
                    else if (e.Key is Key.Down or Key.Right) { vm.MoveBench(vm.PickBench, 1); e.Handled = true; }
                }), RoutingStrategies.Tunnel);
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

        // The bench drag lives on the WHOLE view, not on the list: it has to survive the pointer
        // leaving the touchline strip and crossing up onto the pitch. Press only RECORDS —
        // nothing is handled, so the ListBox keeps its own selection, double-tap and
        // right-click untouched.
        // Tunnel throughout: these fire on the way DOWN, before a ListBoxItem marks the event
        // handled for its own selection, and they still reach us when the pointer is captured.
        AddHandler(InputElement.PointerPressedEvent, OnAnyPressed, RoutingStrategies.Tunnel);
        AddHandler(InputElement.PointerMovedEvent, OnAnyMoved, RoutingStrategies.Tunnel);
        AddHandler(InputElement.PointerReleasedEvent, OnAnyReleased, RoutingStrategies.Tunnel);
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

    // ── the pitch: press / move / drop ────────────────────────────────────────────────

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
            _originLeft = p.Left;
            _originTop = p.Top;
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
        // Dragging is live on Lineup AND on Set Formation (the game does both); everywhere else
        // a press stays a pure select/swap click.
        if (DataContext is not TacticsViewModel vm || !vm.DragEnabled) return;
        // The press itself can complete an armed ⇄ Swap, which REPLACES both tokens. Dragging a
        // token that is no longer in the XI would move something nothing renders.
        if (!vm.Players.Contains(_pressed)) { _pressed = null; return; }
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

        // The clamp keeps the TOKEN on your half, so a gesture toward the bench would otherwise
        // look like nothing is happening. A ghost follows the pointer once it leaves the pitch.
        var here = e.GetPosition(this);
        if (pos.X < 0 || pos.X > TacticsViewModel.PitchW ||
            pos.Y < 0 || pos.Y > TacticsViewModel.PitchH)
        {
            ShowGhost($"{_pressed.Position}  {_pressed.Surname}");
            MoveGhost(here);
        }
        else
        {
            HideGhost();
        }
        Highlight(vm, here, pos, _pressed);
    }

    private void OnPointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        var dragged = _pressed;
        var wasDrag = _dragging;
        _pressed = null;
        _dragging = false;
        e.Pointer.Capture(null);
        ClearHighlight();
        HideGhost();
        if (!wasDrag || dragged is null) return;         // a plain click stays a selection
        if (DataContext is not TacticsViewModel vm) return;

        var here = e.GetPosition(this);
        // The touchline strip first: a token dragged down there is a substitution, not a reposition.
        if (OverBench(vm, here))
        {
            var (row, _) = BenchRowAt(here);
            if (row is not null) vm.DropOnBenchRow(dragged, row, _originLeft, _originTop);
            else vm.DropOnBenchSpace(dragged, _originLeft, _originTop);
            return;
        }

        // Canvas space, exactly like the drag itself — Viewbox-scale independent by construction.
        var drop = e.GetPosition(Pitch);
        var target = StarterAt(vm, drop, dragged);
        if (target is not null) vm.DropOnStarter(dragged, target, _originLeft, _originTop);
        else vm.DropOnPitch(dragged, _originLeft, _originTop);
    }

    // ── the bench drag: a substitute onto the pitch, or up and down the order ─────────

    private void OnAnyPressed(object? sender, PointerPressedEventArgs e)
    {
        _benchPressed = null;
        _benchDragging = false;
        if (_bench is null) return;
        if (!e.GetCurrentPoint(this).Properties.IsLeftButtonPressed) return;
        if (DataContext is not TacticsViewModel vm || !vm.DragEnabled || !vm.ShowLineup) return;
        if (Row<BenchEntry>(e.Source) is not { } row) return;
        _benchPressed = row;                     // record only — the press stays the ListBox's
        _benchPressPoint = e.GetPosition(this);
    }

    private void OnAnyMoved(object? sender, PointerEventArgs e)
    {
        if (_benchPressed is null) return;
        if (DataContext is not TacticsViewModel vm) { _benchPressed = null; return; }
        var here = e.GetPosition(this);
        if (!_benchDragging)
        {
            if (Math.Abs(here.X - _benchPressPoint.X) < DragThreshold &&
                Math.Abs(here.Y - _benchPressPoint.Y) < DragThreshold)
            {
                return;
            }
            _benchDragging = true;
            e.Pointer.Capture(this);             // captured LATE, so the plain click is untouched
            ShowGhost($"{_benchPressed.Position}  {_benchPressed.Name}");
        }
        MoveGhost(here);
        Highlight(vm, here, e.GetPosition(Pitch), null);
    }

    private void OnAnyReleased(object? sender, PointerReleasedEventArgs e)
    {
        var dragged = _benchPressed;
        var wasDrag = _benchDragging;
        _benchPressed = null;
        _benchDragging = false;
        if (!wasDrag || dragged is null) return;
        e.Pointer.Capture(null);
        ClearHighlight();
        HideGhost();
        if (DataContext is not TacticsViewModel vm) return;

        var here = e.GetPosition(this);
        if (OverBench(vm, here))
        {
            var (row, _) = BenchRowAt(here);
            vm.ReorderBench(dragged, row);       // dropped on himself or on nothing: no-op
            return;
        }
        // Only YOUR half accepts a substitute — the mirrored right half is the opponent's.
        var drop = e.GetPosition(Pitch);
        if (drop.X < 0 || drop.X > TacticsViewModel.HalfW ||
            drop.Y < 0 || drop.Y > TacticsViewModel.PitchH)
        {
            return;
        }
        var target = StarterAt(vm, drop, null);
        if (target is not null) vm.DropBenchOnStarter(dragged, target);
        else vm.DropBenchOnPitch(dragged);
    }

    // ── hit-testing ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// The starter whose TokenW x TokenH rect contains a CANVAS-space point; when tokens overlap,
    /// the nearest centre wins. Canvas space is the same space the drag writes into, so this is
    /// Viewbox-scale independent like the rest of the gesture.
    /// </summary>
    private static PitchPlayer? StarterAt(TacticsViewModel vm, Point p, PitchPlayer? skip)
    {
        PitchPlayer? best = null;
        var bestDist = double.MaxValue;
        foreach (var t in vm.Players)
        {
            if (ReferenceEquals(t, skip)) continue;
            if (p.X < t.Left || p.X > t.Left + TacticsViewModel.TokenW) continue;
            if (p.Y < t.Top || p.Y > t.Top + TacticsViewModel.TokenH) continue;
            var dx = p.X - (t.Left + TacticsViewModel.TokenW / 2);
            var dy = p.Y - (t.Top + TacticsViewModel.TokenH / 2);
            var d = (dx * dx) + (dy * dy);
            if (d >= bestDist) continue;
            bestDist = d;
            best = t;
        }
        return best;
    }

    /// <summary>Is a view-space point over the touchline strip? The strip is only on screen on
    /// Lineup and Team (ShowBenchStrip), so a stale arranged rect can never make the Tactics tab
    /// claim a drop — the pitch owns that band there. View space, not canvas space: the strip
    /// lives outside the Viewbox, so it is measured in the same coordinates the drag reports.</summary>
    private bool OverBench(TacticsViewModel vm, Point p)
    {
        if (_bench is null || !vm.ShowBenchStrip) return false;
        if (_bench.Bounds.Width <= 0 || _bench.Bounds.Height <= 0) return false;
        if (_bench.TranslatePoint(new Point(0, 0), this) is not { } o) return false;
        return p.X >= o.X && p.X <= o.X + _bench.Bounds.Width
            && p.Y >= o.Y && p.Y <= o.Y + _bench.Bounds.Height;
    }

    /// <summary>The bench chip under a view-space point, with its container (for the highlight).
    /// The chips are laid out horizontally now, so the container rect is a ~98x105 box rather
    /// than a full-width row — ShowBox draws the highlight straight from those bounds, so no
    /// coordinate maths had to change when the list turned into a strip.</summary>
    private (BenchEntry? Row, Control? Container) BenchRowAt(Point p)
    {
        if (_bench is null) return (null, null);
        foreach (var c in _bench.GetRealizedContainers())
        {
            if (c.DataContext is not BenchEntry b) continue;
            if (c.TranslatePoint(new Point(0, 0), this) is not { } o) continue;
            if (p.X >= o.X && p.X <= o.X + c.Bounds.Width &&
                p.Y >= o.Y && p.Y <= o.Y + c.Bounds.Height)
            {
                return (b, c);
            }
        }
        return (null, null);
    }

    // ── drag chrome ──────────────────────────────────────────────────────────────────

    /// <summary>Light whatever the pointer is over, so a drop is never a guess.</summary>
    private void Highlight(TacticsViewModel vm, Point view, Point canvas, PitchPlayer? skip)
    {
        ClearHighlight();
        if (OverBench(vm, view))
        {
            var (_, container) = BenchRowAt(view);
            ShowBox(container ?? _bench);
            return;
        }
        var target = StarterAt(vm, canvas, skip);
        if (target is null) return;
        target.DropTarget = true;
        _hot = target;
    }

    private void ClearHighlight()
    {
        if (_hot is not null) { _hot.DropTarget = false; _hot = null; }
        if (_highlight is not null) _highlight.IsVisible = false;
    }

    private void ShowBox(Control? c)
    {
        if (c is null || DragLayer is null) return;
        if (c.TranslatePoint(new Point(0, 0), DragLayer) is not { } o) return;
        if (_highlight is null)
        {
            _highlight = new Border
            {
                CornerRadius = new CornerRadius(4),
                Background = new SolidColorBrush(Color.Parse("#33F5E642")),
                BorderBrush = new SolidColorBrush(Color.Parse("#F5E642")),
                BorderThickness = new Thickness(1),
                IsHitTestVisible = false,
            };
            DragLayer.Children.Add(_highlight);
        }
        _highlight.Width = c.Bounds.Width;
        _highlight.Height = c.Bounds.Height;
        Canvas.SetLeft(_highlight, o.X);
        Canvas.SetTop(_highlight, o.Y);
        _highlight.IsVisible = true;
    }

    private void ShowGhost(string text)
    {
        if (DragLayer is null) return;
        if (_ghost is null)
        {
            _ghost = new Border
            {
                MaxWidth = 190,
                CornerRadius = new CornerRadius(6),
                Background = new SolidColorBrush(Color.Parse("#E6121A22")),
                BorderBrush = new SolidColorBrush(Color.Parse("#F5E642")),
                BorderThickness = new Thickness(1),
                Padding = new Thickness(9, 4),
                IsHitTestVisible = false,
                Child = new TextBlock
                {
                    FontSize = 12,
                    FontWeight = FontWeight.SemiBold,
                    Foreground = new SolidColorBrush(Colors.White),
                    VerticalAlignment = VerticalAlignment.Center,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                },
            };
            DragLayer.Children.Add(_ghost);
        }
        if (_ghost.Child is TextBlock tb) tb.Text = text;
        _ghost.IsVisible = true;
    }

    private void MoveGhost(Point p)
    {
        if (_ghost is null || !_ghost.IsVisible) return;
        Canvas.SetLeft(_ghost, p.X + 14);
        Canvas.SetTop(_ghost, p.Y - 12);
    }

    private void HideGhost()
    {
        if (_ghost is not null) _ghost.IsVisible = false;
    }
}
