using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class ScoutingView : UserControl
{
    public ScoutingView()
    {
        InitializeComponent();
        // A dossier card is a handle on its subject: right-click gives the player his shared
        // menu (open in market, shortlist, enquire) and a club its own.
        MlMenu.Attach<ScoutReportRow>(
            this.FindControl<ItemsControl>("ReportList")!,
            r => (DataContext as ScoutingViewModel)?.MenuFor(r));
    }

    /// <summary>The ⋯ on a dossier card: the SAME menu the right-click opens.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as ScoutingViewModel;
        ScoutReportRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ScoutReportRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = "Couldn't bring up its options.";
        }
        catch (Exception ex)
        {
            Program.Log("Scouting.OnRowMenu", ex);
            if (vm is not null) vm.Status = "Couldn't bring up its options.";
        }
    }
}
