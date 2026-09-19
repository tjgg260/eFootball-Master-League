using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class StaffView : UserControl
{
    public StaffView()
    {
        InitializeComponent();

        // The candidate list gets the right-click profile: hire, the whole 1-20 sheet, and
        // the incumbent he would replace. DataContext resolves lazily, so attaching here is safe.
        MlMenu.Attach<StaffMarketRow>(
            this.FindControl<ListBox>("MarketList")!,
            r => (DataContext as StaffViewModel)?.MenuFor(r),
            r => { if (DataContext is StaffViewModel vm) vm.SelectedCandidate = r; });
    }

    /// <summary>The ⋯ on a candidate row: the SAME menu the right-click opens.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as StaffViewModel;
        StaffMarketRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<StaffMarketRow>(btn);
            if (row is null) return;
            vm.SelectedCandidate = row;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Name}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Staff.OnRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Name ?? "his"} options.";
        }
    }
}
