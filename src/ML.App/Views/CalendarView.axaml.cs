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
                // The ⋯ button added for the row-actions ruling is its own left-click target
                // inside the cell; this Tunnel handler runs on PointerPressed, BEFORE the
                // button's own Click fires on release, so without this it would activate the
                // day AND (try to) open the menu on the same click.
                if (el is Button) return;
                if (el is StyledElement se && se.DataContext is DayCell c) { cell = c; break; }
                if (ReferenceEquals(el, grid)) break;
            }
            if (cell is null) return;
            vm.Activate(cell);
        }, RoutingStrategies.Tunnel);
    }

    /// <summary>The ⋯ on a day cell: the SAME menu the right-click opens.</summary>
    private void OnCellMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as CalendarViewModel;
        try
        {
            if (vm is null || sender is not Control btn) return;
            var cell = MlMenu.RowAt<DayCell>(btn);
            if (cell is null) return;
            MlMenu.OpenAt(vm.MenuFor(cell), btn);
        }
        catch (Exception ex)
        {
            Program.Log("Calendar.OnCellMenu", ex);
        }
    }
}
