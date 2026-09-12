using Avalonia.Controls;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class HistoryView : UserControl
{
    public HistoryView()
    {
        InitializeComponent();
        // The archive is live: those clubs still play and those scorers can still be signed,
        // so an old table row opens the same club menu the standings do, and an archived
        // top scorer the same player menu the squad list does.
        HistoryViewModel? Vm() => DataContext as HistoryViewModel;
        MlMenu.Attach<ArchiveTableRow>(
            this.FindControl<ItemsControl>("ArchiveTopList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ArchiveTableRow>(
            this.FindControl<ItemsControl>("ArchiveSecondList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ArchiveHonourRow>(
            this.FindControl<ItemsControl>("ArchiveHonoursList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ArchiveScorerRow>(
            this.FindControl<ItemsControl>("ArchiveScorersList")!, r => Vm()?.MenuFor(r));
    }
}
