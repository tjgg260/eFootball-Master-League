using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class HistoryView : UserControl
{
    private HistoryViewModel? Vm() => DataContext as HistoryViewModel;

    public HistoryView()
    {
        InitializeComponent();
        // The archive is live: those clubs still play and those scorers can still be signed,
        // so an old table row opens the same club menu the standings do, and an archived
        // top scorer the same player menu the squad list does.
        MlMenu.Attach<ArchiveTableRow>(
            this.FindControl<ItemsControl>("ArchiveTopList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ArchiveTableRow>(
            this.FindControl<ItemsControl>("ArchiveSecondList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ArchiveHonourRow>(
            this.FindControl<ItemsControl>("ArchiveHonoursList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ArchiveScorerRow>(
            this.FindControl<ItemsControl>("ArchiveScorersList")!, r => Vm()?.MenuFor(r));
    }

    /// <summary>The ⋯ on an archived table row (either table): the SAME menu the right-click opens.</summary>
    private void OnTableRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        ArchiveTableRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ArchiveTableRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Team}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("History.OnTableRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Team ?? "the"} options.";
        }
    }

    /// <summary>The ⋯ on an honours row: the SAME menu the right-click opens.</summary>
    private void OnHonourRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        ArchiveHonourRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ArchiveHonourRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Team}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("History.OnHonourRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Team ?? "the"} options.";
        }
    }

    /// <summary>The ⋯ on a top-scorer row: the SAME menu the right-click opens.</summary>
    private void OnScorerRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        ArchiveScorerRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ArchiveScorerRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Player}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("History.OnScorerRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Player ?? "his"} options.";
        }
    }
}
