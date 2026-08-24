using Avalonia.Controls;
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
}
