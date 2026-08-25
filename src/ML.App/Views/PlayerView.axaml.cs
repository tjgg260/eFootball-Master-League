using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class PlayerView : UserControl
{
    public PlayerView()
    {
        InitializeComponent();

        // BOTH affordances over ONE action list (the standing ruling): right-clicking the
        // identity band opens the shared menu, the ⋯ button opens the same menu, and the
        // buttons in the action bar are that menu's own items. MlMenu walks up from the click
        // to the first DataContext of the given type — here that is the page ViewModel itself.
        MlMenu.Attach<PlayerViewModel>(this.FindControl<Border>("IdentityBand")!,
            vm => vm.BuildMenu());
    }

    /// <summary>The ⋯ affordance: the same menu, for anyone who never right-clicks.</summary>
    private void OnMore(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not PlayerViewModel vm) return;
        var menu = vm.BuildMenu();
        if (menu is null || menu.Items.Count == 0) return;
        var target = sender as Control ?? this;
        menu.Placement = PlacementMode.BottomEdgeAlignedRight;
        menu.Open(target);
    }
}
