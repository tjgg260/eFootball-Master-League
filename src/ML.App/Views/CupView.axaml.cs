using Avalonia.Controls;
using Avalonia.Interactivity;
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

    /// <summary>The ⋯ on a tie card: the SAME menu the right-click opens.</summary>
    private void OnTieMenu(object? sender, RoutedEventArgs e)
    {
        var vm = DataContext as CupViewModel;
        CupTie? tie = null;
        try
        {
            if (vm is null || sender is not Control btn) return;
            tie = MlMenu.RowAt<CupTie>(btn);
            if (tie is null) return;
            if (!MlMenu.OpenAt(vm.MenuFor(tie), btn)) vm.StatusLine = "Couldn't bring up this tie's options.";
        }
        catch (Exception ex)
        {
            Program.Log("Cup.OnTieMenu", ex);
            if (vm is not null) vm.StatusLine = "Couldn't bring up this tie's options.";
        }
    }
}
