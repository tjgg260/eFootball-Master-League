using Avalonia.Controls;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class MarketView : UserControl
{
    public MarketView()
    {
        InitializeComponent();
        // Right-click any market row: the shared player vocabulary (scout, enquire, shortlist,
        // open his club) plus this screen's own two verbs. The row is selected first, so the
        // profile pane is showing the same man the menu is about to act on.
        MlMenu.Attach<MarketPlayer>(
            this.FindControl<DataGrid>("MarketGrid")!,
            r => (DataContext as MarketViewModel)?.MenuFor(r),
            r => { if (DataContext is MarketViewModel vm) vm.SelectedPlayer = r; });
    }
}
