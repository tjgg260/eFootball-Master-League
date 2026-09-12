using Avalonia.Controls;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class StatsView : UserControl
{
    public StatsView()
    {
        InitializeComponent();
        // Every leaderboard row is a handle on its subject: scorers, assists and bookings
        // open the shared player menu; the defensive tables and the Roll of Honour open the
        // club one. DataContext resolves at click time, so attaching in the ctor is safe.
        StatsViewModel? Vm() => DataContext as StatsViewModel;
        MlMenu.Attach<ScorerRow>(this.FindControl<DataGrid>("ScorersGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ScorerRow>(this.FindControl<DataGrid>("AssistsGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<StatRow>(this.FindControl<DataGrid>("DefenceGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<StatRow>(this.FindControl<DataGrid>("CleanSheetGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<CardRow>(this.FindControl<DataGrid>("DisciplineGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<HonourRow>(this.FindControl<ItemsControl>("HonoursList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ReportRow>(this.FindControl<ItemsControl>("ReportsList")!, r => Vm()?.MenuFor(r));
    }
}
