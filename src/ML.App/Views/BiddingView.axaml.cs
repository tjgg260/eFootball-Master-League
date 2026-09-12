using Avalonia.Controls;
using Avalonia.Interactivity;
using ML.App.ViewModels;

namespace ML.App.Views;

public partial class BiddingView : UserControl
{
    public BiddingView()
    {
        InitializeComponent();

        // BOTH affordances over ONE action list (the standing ruling): right-clicking the
        // subject band opens the shared player menu, and the ⋯ button opens the same menu.
        // MlMenu walks up from the click to the first DataContext of the given type — here
        // that is the page ViewModel itself.
        MlMenu.Attach<BiddingViewModel>(this.FindControl<Border>("SubjectBand")!,
            vm => vm.BuildMenu());
    }

    /// <summary>The ⋯ affordance: the same menu, for anyone who never right-clicks.</summary>
    private void OnMore(object? sender, RoutedEventArgs e)
    {
        if (DataContext is not BiddingViewModel vm) return;
        var menu = vm.BuildMenu();
        if (menu is null || menu.Items.Count == 0) return;
        var target = sender as Control ?? this;
        menu.Placement = PlacementMode.BottomEdgeAlignedRight;
        menu.Open(target);
    }
}
