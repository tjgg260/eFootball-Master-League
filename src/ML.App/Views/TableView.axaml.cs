using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class TableView : UserControl
{
    public TableView()
    {
        InitializeComponent();
        // The table is a list of clubs: right-click one and you get the club's own verbs
        // (view squad, scout, head-to-head) without leaving the standings.
        MlMenu.Attach<TableEntry>(
            this.FindControl<DataGrid>("StandingsGrid")!,
            r => (DataContext as TableViewModel)?.MenuFor(r),
            r => { if (DataContext is TableViewModel vm) vm.Selected = r; });
    }

    /// <summary>The ⋯ on a table row: the SAME menu the right-click opens.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as TableViewModel;
        TableEntry? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<TableEntry>(btn);
            if (row is null) return;
            vm.Selected = row;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Team}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Table.OnRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Team ?? "the"} options.";
        }
    }
}
