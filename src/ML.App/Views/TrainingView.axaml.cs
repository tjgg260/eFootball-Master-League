using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class TrainingView : UserControl
{
    public TrainingView()
    {
        InitializeComponent();
        // Every row here is one of yours: the shared own-player menu, plus training's own verbs.
        MlMenu.Attach<TrainingRow>(this.FindControl<DataGrid>("TrainingGrid")!,
            r => (DataContext as TrainingViewModel)?.MenuFor(r),
            r => { if (DataContext is TrainingViewModel vm) vm.Selected = r; });
    }

    /// <summary>The ⋯ on a training row: the SAME menu the right-click opens.</summary>
    private void OnRowMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as TrainingViewModel;
        TrainingRow? row = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            row = MlMenu.RowAt<TrainingRow>(btn);
            if (row is null) return;
            vm.Selected = row;
            if (!MlMenu.OpenAt(vm.MenuFor(row), btn)) vm.Status = $"Couldn't bring up {row.Name}'s options.";
        }
        catch (Exception ex)
        {
            Program.Log("Training.OnRowMenu", ex);
            if (vm is not null) vm.Status = $"Couldn't bring up {row?.Name ?? "his"} options.";
        }
    }
}
