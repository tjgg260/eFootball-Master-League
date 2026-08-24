using Avalonia.Controls;
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
}
