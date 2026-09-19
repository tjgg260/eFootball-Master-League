using Avalonia.Controls;
using Avalonia.Interactivity;
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

        // Double-click a market row to OPEN him: the full-width Player screen, where the
        // bidding table is one button away — rather than the profile pane in the 330px rail
        // that put the fee field below the fold. Single-click still just selects (the rail's
        // profile keeps following it) and the right-click menu is untouched: a double-click
        // is two single clicks first, so the row is already selected when this runs.
        MlMenu.OnDoubleClick<MarketPlayer>(
            this.FindControl<DataGrid>("MarketGrid")!,
            r => Nav.Go("Player", EntityRef.Player(r.Id, r.Name)));
    }

    /// <summary>The ⋯ on a market row: the SAME menu the right-click opens, for anyone who
    /// never right-clicks. See SquadView.OnRowMenu for why this is guarded end to end.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as MarketViewModel;
        MarketPlayer? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<MarketPlayer>(btn);
            if (row is null) return;
            vm.SelectedPlayer = row;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.SignStatus = $"Couldn't bring up {row.Name}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Market.OnRowMenu", ex);
            if (vm is not null) vm.SignStatus = $"Couldn't bring up {row?.Name ?? "his"} options.";
        }
    }
}
