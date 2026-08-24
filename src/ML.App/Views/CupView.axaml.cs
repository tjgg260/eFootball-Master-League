using Avalonia.Controls;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class CupView : UserControl
{
    public CupView()
    {
        InitializeComponent();
        // A tie card is a handle on the two clubs in it. The menu is attached to the OUTER
        // list: the walk up from the click finds the tie's own DataContext first, so nesting
        // (sections → rounds → ties) needs no per-level plumbing.
        MlMenu.Attach<CupTie>(
            this.FindControl<ItemsControl>("CupSections")!,
            t => (DataContext as CupViewModel)?.MenuFor(t));
    }
}
