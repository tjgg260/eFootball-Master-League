using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class MatchReportView : UserControl
{
    private MatchReportViewModel? Vm() => DataContext as MatchReportViewModel;

    public MatchReportView()
    {
        InitializeComponent();
        // Both player tables: double-click opens the player, right-click the shared player menu.
        foreach (var name in new[] { "HomeGrid", "AwayGrid" })
        {
            var grid = this.FindControl<DataGrid>(name)!;
            MlMenu.Attach<ReportPlayerRow>(grid, r => Vm()?.MenuFor(r));
            grid.DoubleTapped += (_, _) =>
            {
                if (grid.SelectedItem is ReportPlayerRow r) Vm()?.OpenPlayerCommand.Execute(r);
            };
        }
    }

    /// <summary>The ⋯ on a player row (either grid): the SAME menu the right-click opens.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        ReportPlayerRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ReportPlayerRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Name}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("MatchReport.OnRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Name ?? "his"} options.";
        }
    }
}
