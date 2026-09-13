using Avalonia.Controls;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class MatchReportView : UserControl
{
    public MatchReportView()
    {
        InitializeComponent();
        // Both player tables: double-click opens the player, right-click the shared player menu.
        MatchReportViewModel? Vm() => DataContext as MatchReportViewModel;
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
}
