using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class StatsView : UserControl
{
    private StatsViewModel? Vm() => DataContext as StatsViewModel;

    public StatsView()
    {
        InitializeComponent();
        // Every leaderboard row is a handle on its subject: scorers, assists and bookings
        // open the shared player menu; the defensive tables and the Roll of Honour open the
        // club one. DataContext resolves at click time, so attaching in the ctor is safe.
        MlMenu.Attach<ScorerRow>(this.FindControl<DataGrid>("ScorersGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ScorerRow>(this.FindControl<DataGrid>("AssistsGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<StatRow>(this.FindControl<DataGrid>("DefenceGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<StatRow>(this.FindControl<DataGrid>("CleanSheetGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<CardRow>(this.FindControl<DataGrid>("DisciplineGrid")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<HonourRow>(this.FindControl<ItemsControl>("HonoursList")!, r => Vm()?.MenuFor(r));
        MlMenu.Attach<ReportRow>(this.FindControl<ItemsControl>("ReportsList")!, r => Vm()?.MenuFor(r));
    }

    /// <summary>The ⋯ on a scorer/assist row (both grids share the row type): the SAME menu
    /// the right-click opens.</summary>
    private void OnScorerRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        ScorerRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ScorerRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Player}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Stats.OnScorerRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Player ?? "his"} options.";
        }
    }

    /// <summary>The ⋯ on a Best Defence row: the SAME menu the right-click opens.</summary>
    private void OnDefenceRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        StatRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<StatRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Team}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Stats.OnDefenceRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Team ?? "the"} options.";
        }
    }

    /// <summary>The ⋯ on a Clean Sheets row: the SAME menu the right-click opens.</summary>
    private void OnCleanSheetRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        StatRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<StatRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Team}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Stats.OnCleanSheetRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Team ?? "the"} options.";
        }
    }

    /// <summary>The ⋯ on a Discipline row: the SAME menu the right-click opens.</summary>
    private void OnDisciplineRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        CardRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<CardRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Player}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Stats.OnDisciplineRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Player ?? "his"} options.";
        }
    }

    /// <summary>The ⋯ on a Roll of Honour row: the SAME menu the right-click opens.</summary>
    private void OnHonourRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        HonourRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<HonourRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Team}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Stats.OnHonourRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Team ?? "the"} options.";
        }
    }

    /// <summary>The ⋯ on a match-report row: the SAME menu the right-click opens. Nested
    /// inside the row's own open-report Button — see InboxView.OnFeedRowMenu for why the
    /// inner Click never also opens the report.</summary>
    private void OnReportRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = Vm();
        ReportRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<ReportRow>(btn);
            if (row is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = "Couldn't bring up this match's options.";
            e.Handled = true;
        }
        catch (Exception ex)
        {
            Program.Log("Stats.OnReportRowMenu", ex);
            if (vm is not null) vm.Status = "Couldn't bring up this match's options.";
        }
    }
}
