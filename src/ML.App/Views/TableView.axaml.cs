using Avalonia.Controls;
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
}
