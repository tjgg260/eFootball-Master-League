using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class AcademyView : UserControl
{
    public AcademyView()
    {
        InitializeComponent();
        // Prospects and youth-side players are neither squad players nor market targets, so
        // each grid gets the menu the ViewModel builds for its own kind of lad.
        MlMenu.Attach<AcademyEntry>(this.FindControl<DataGrid>("AcademyGrid")!,
            r => (DataContext as AcademyViewModel)?.MenuFor(r),
            r => { if (DataContext is AcademyViewModel vm) vm.Selected = r; });
        MlMenu.Attach<YouthEntry>(this.FindControl<DataGrid>("YouthGrid")!,
            r => (DataContext as AcademyViewModel)?.MenuForYouth(r),
            r => { if (DataContext is AcademyViewModel vm) vm.SelectedYouth = r; });
    }

    /// <summary>The ⋯ on a prospect row: the SAME menu the right-click opens.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as AcademyViewModel;
        AcademyEntry? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<AcademyEntry>(btn);
            if (row is null) return;
            vm.Selected = row;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Name}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Academy.OnRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Name ?? "his"} options.";
        }
    }

    /// <summary>The ⋯ on a youth-side row: the SAME menu the right-click opens.</summary>
    private void OnYouthRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as AcademyViewModel;
        YouthEntry? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<YouthEntry>(btn);
            if (row is null) return;
            vm.SelectedYouth = row;
            if (!MlMenu.OpenAt(vm.MenuForYouth(row), btn)) vm.Status = $"Couldn't bring up {row.Name}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Academy.OnYouthRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Name ?? "his"} options.";
        }
    }
}
