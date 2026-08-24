using Avalonia.Controls;
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
}
