using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using ML.App.ViewModels;

namespace ML.App.Views;

/// <summary>
/// The Office is the career's hub: every card on it is a door. Right-click carries the shared
/// entity vocabulary (EntityActions), left-click carries the hand-offs (Nav.Go). DataContext is
/// resolved lazily inside each handler, so attaching in the constructor is safe.
/// </summary>
public partial class DashboardView : UserControl
{
    public DashboardView()
    {
        InitializeComponent();

        // Schedule + mini table: list-shaped, so the shared attach does the row walk for us.
        if (this.FindControl<ItemsControl>("ScheduleList") is { } schedule)
        {
            MlMenu.Attach<ScheduleRowVm>(schedule, r => (DataContext as DashboardViewModel)?.MenuFor(r));
        }
        if (this.FindControl<ItemsControl>("MiniTableList") is { } mini)
        {
            MlMenu.Attach<MiniRowVm>(mini, r => (DataContext as DashboardViewModel)?.MenuFor(r));
        }

        // The opposition card is ONE target with a nested one: the key-player line owns its own
        // menu. A single tunnel handler decides which, because a tunnel handler on the card would
        // otherwise always beat a handler on the line inside it.
        if (this.FindControl<Border>("OppCard") is { } card)
        {
            card.AddHandler(InputElement.PointerPressedEvent, (_, e) =>
            {
                if (!e.GetCurrentPoint(card).Properties.IsRightButtonPressed) return;
                if (DataContext is not DashboardViewModel vm) return;
                var key = this.FindControl<TextBlock>("KeyPlayerBlock");
                var onKey = false;
                for (Visual? el = e.Source as Visual; el is not null; el = el.GetVisualParent())
                {
                    if (ReferenceEquals(el, key)) { onKey = true; break; }
                    if (ReferenceEquals(el, card)) break;
                }
                var menu = onKey ? vm.KeyPlayerMenu() : vm.OppositionMenu();
                if (menu is null || menu.Items.Count == 0) return;
                menu.Placement = PlacementMode.Pointer;
                menu.Open(card);
                e.Handled = true;
            }, RoutingStrategies.Tunnel);
        }

        // Deadline day: the banner IS the button.
        if (this.FindControl<Border>("DeadlineBanner") is { } deadline)
        {
            deadline.AddHandler(InputElement.PointerPressedEvent, (_, e) =>
            {
                if (!e.GetCurrentPoint(deadline).Properties.IsLeftButtonPressed) return;
                Nav.Go("Market");
                e.Handled = true;
            }, RoutingStrategies.Tunnel);
        }
    }

    /// <summary>The ⋯ on a schedule row: the SAME menu the right-click opens.</summary>
    private void OnScheduleRowMenu(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not DashboardViewModel vm || sender is not Control btn) return;
        try
        {
            var row = MlMenu.RowAt<ScheduleRowVm>(btn);
            if (row is not null) MlMenu.OpenAt(vm.MenuFor(row), btn);
        }
        catch (Exception ex) { Program.Log("Dashboard.OnScheduleRowMenu", ex); }
    }

    /// <summary>The ⋯ on a mini-table row: the SAME menu the right-click opens.</summary>
    private void OnMiniTableRowMenu(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not DashboardViewModel vm || sender is not Control btn) return;
        try
        {
            var row = MlMenu.RowAt<MiniRowVm>(btn);
            if (row is not null) MlMenu.OpenAt(vm.MenuFor(row), btn);
        }
        catch (Exception ex) { Program.Log("Dashboard.OnMiniTableRowMenu", ex); }
    }

    /// <summary>The ⋯ on the opposition card: the SAME menu the right-click on the card opens.</summary>
    private void OnOppCardMenu(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not DashboardViewModel vm || sender is not Control btn) return;
        try { MlMenu.OpenAt(vm.OppositionMenu(), btn); }
        catch (Exception ex) { Program.Log("Dashboard.OnOppCardMenu", ex); }
    }

    /// <summary>The ⋯ on the key-player line: the SAME menu the right-click on it opens.</summary>
    private void OnKeyPlayerMenu(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not DashboardViewModel vm || sender is not Control btn) return;
        try { MlMenu.OpenAt(vm.KeyPlayerMenu(), btn); }
        catch (Exception ex) { Program.Log("Dashboard.OnKeyPlayerMenu", ex); }
    }
}
