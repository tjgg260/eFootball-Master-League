using Avalonia.Controls;
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
}
