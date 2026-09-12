using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using ML.App.ViewModels;

namespace ML.App.Views;

/// <summary>
/// The month grid is an ItemsControl, so there is no row/selection machinery to lean on: both
/// buttons walk the visual tree up from the click to the DayCell that owns it. Right-click goes
/// through the shared MlMenu attach; left-click mirrors its walk to reach the same cell.
/// </summary>
public partial class CalendarView : UserControl
{
    public CalendarView()
    {
        InitializeComponent();

        var grid = this.FindControl<ItemsControl>("DayGrid");
        if (grid is null) return;

        MlMenu.Attach<DayCell>(grid, c => (DataContext as CalendarViewModel)?.MenuFor(c));

        grid.AddHandler(InputElement.PointerPressedEvent, (_, e) =>
        {
            if (!e.GetCurrentPoint(grid).Properties.IsLeftButtonPressed) return;
            if (DataContext is not CalendarViewModel vm) return;
            DayCell? cell = null;
            for (Visual? el = e.Source as Visual; el is not null; el = el.GetVisualParent())
            {
                if (el is StyledElement se && se.DataContext is DayCell c) { cell = c; break; }
                if (ReferenceEquals(el, grid)) break;
            }
            if (cell is null) return;
            vm.Activate(cell);
        }, RoutingStrategies.Tunnel);
    }
}
